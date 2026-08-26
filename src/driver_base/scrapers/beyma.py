"""Beyma (beyma.com) scraper.

Enumeration: 10 English category pages (dropping non-driver `passive-filter`,
`accesories`, plus `discontinued`). Each page is fully server-rendered
WordPress HTML — no pagination is used; all products for a category are on a
single page. Product URLs match the pattern
    https://www.beyma.com/en/products/c/{category}/{PRODUCT-CODE}/{slug}/

Extraction: `div.block-product-features div.items div.item` where each item
has `div.title` (label) + `div.description` (value). Multiple section
containers (Technical specifications, Parameters Thiele & Small, Construction
details) all use the same class, so one selector captures every spec.

Sensitivity slot: 1W/1m (label carries explicit "1 W @ 1 m" annotation).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup

from driver_base.interface import (
    DriverKind,
    EnumerateResult,
    ParseResult,
    RawArtifact,
    Scraper,
    SeedContext,
    SeedRef,
)
from driver_base.labels import normalize_label
from driver_base.magnets import normalize_magnet_type
from driver_base.model import DriverFragment, SpecSource
from driver_base.scrapers import register
from driver_base.units import (
    parse_bl_tm,
    parse_compliance_mm_per_n,
    parse_float,
    parse_frequency,
    parse_impedance,
    parse_le_mh,
    parse_length_mm,
    parse_liters,
    parse_mass_g,
    parse_power,
    parse_range,
    parse_sd_cm2,
)


_BASE = "https://www.beyma.com"

# Category slug → DriverKind. Excluded: passive-filter, accesories (not drivers),
# discontinued (v2 archive scope).
_CATEGORIES: list[tuple[str, DriverKind]] = [
    ("low-mid-frequency",              DriverKind.LF_WOOFER),
    ("coaxial",                        DriverKind.COAX),
    ("compression-driver",             DriverKind.HF_COMPRESSION),
    ("compression-driver-wave-guide",  DriverKind.HF_COMPRESSION),
    # AMT drivers classified as tweeters — the "AMT-ness" is captured in
    # `diaphragm_shape` at parse time so users can filter/search for them.
    ("amt-driver",                     DriverKind.TWEETER),
    ("compression-tweeter",            DriverKind.TWEETER),
    ("dome-tweeter",                   DriverKind.TWEETER),
    ("full-range",                     DriverKind.FULLRANGE),
    ("horns",                          DriverKind.HORN),
    ("shaker",                         DriverKind.SHAKER),
]

_PRODUCT_URL_RE = re.compile(
    r'https://www\.beyma\.com/en/products/c/([a-z0-9-]+)/[A-Z0-9]+/[a-z0-9-]+/?',
    re.IGNORECASE,
)

# Title pattern: '{TYPE} {MODEL} {impedance}[ Oh[m]]' — extract MODEL. Beyma
# truncates titles inconsistently: seen `... 8 Ohm`, `... 8 Oh`, `... 8`, and
# `... 8/16 ohm` (multi-impedance). The trailing "Oh"/"Ohm" is optional and the
# impedance may include `/` and `.`.
_TITLE_MODEL_WITH_OHM_RE = re.compile(
    r"\s(\S+)\s+[\d/.]+\s*(?:Oh|Ohm)?\s*$", re.IGNORECASE
)


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


def _model_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    m = _TITLE_MODEL_WITH_OHM_RE.search(title)
    if m:
        return m.group(1).strip()
    # Fallback: last token (works for horns / passives without impedance)
    parts = title.split()
    return parts[-1] if parts else None


# Beyma coax pages combine LF- and HF-section values into a single row labelled
# `X LF/HF` with a value like `8/16 ohm` or `350/90 W AES`. Split the value on
# the first `/` to route the LF number to the generic field and the HF number
# to the coax_hf_* field.
_COAX_LF_HF_PAIR_RE = re.compile(r"^\s*([\d.]+)\s*/\s*([\d.]+)")
# label → (LF-field, HF-field). None for either side means "don't route".
_COAX_LFHF_LABELS: dict[str, tuple[Optional[str], Optional[str]]] = {
    "nominal impedance lf/hf":   ("impedance_nominal_ohm",  "coax_hf_impedance_nominal_ohm"),
    "minimum impedance lf/hf":   ("impedance_min_ohm",      "coax_hf_impedance_min_ohm"),
    "power capacity lf/hf":      ("power_aes_watts",        "coax_hf_power_aes_watts"),
    "sensitivity lf/hf":         ("sensitivity_db_1w_1m",   "coax_hf_sensitivity_db_1w_1m"),
    "voice coil diameter lf/hf": ("voice_coil_diameter_mm", "coax_hf_voice_coil_diameter_mm"),
    # `program power lf/hf` = `700/180 w` — LF Program routes to
    # power_program_watts; there's no coax_hf_power_program_watts today.
    "program power lf/hf":       ("power_program_watts",    None),
}


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    # electrical / commercial
    "power capacity":              ("power_aes_watts",        parse_power),
    "program power":               ("power_program_watts",    parse_power),
    "nominal impedance":           ("impedance_nominal_ohm",  parse_impedance),
    "minimum impedance":           ("impedance_min_ohm",      parse_impedance),
    "sensitivity":                 ("sensitivity_db_1w_1m",   parse_float),
    "frequency range":             ("__freq_range__",         parse_range),
    # physical
    "nominal diameter":            ("nominal_size_mm",        parse_length_mm),
    "voice coil diameter":         ("voice_coil_diameter_mm", parse_length_mm),
    "throat diameter":             ("throat_diameter_mm",     parse_length_mm),
    "recom. crossover frequency":  ("recommended_crossover_hz", parse_frequency),
    "external diameter":           ("overall_diameter_mm",    parse_length_mm),
    "cutout diameter":             ("mounting_diameter_mm",   parse_length_mm),
    "depth":                       ("depth_mm",               parse_length_mm),
    "net weight":                  ("net_weight_kg",          _weight_kg),
    "magnet":                      ("magnet_type",            lambda s: normalize_magnet_type(s)),
    # T/S
    "fs":                          ("fs_hz",                  parse_frequency),
    "re":                          ("re_ohm",                 parse_impedance),
    "qes":                         ("qes",                    parse_float),
    "qms":                         ("qms",                    parse_float),
    "qts":                         ("qts",                    parse_float),
    "vas":                         ("vas_liters",             parse_liters),
    "cms":                         ("cms_mm_per_n",           parse_compliance_mm_per_n),
    "rms":                         ("rms_ns_per_m",           parse_float),   # kg/s = N·s/m
    "efficiency %":                ("eta_zero_pct",           parse_float),
    "sd":                          ("sd_cm2",                 parse_sd_cm2),
    "xmax":                        ("xmax_mm",                parse_length_mm),
    "xdamage pp":                  ("xmech_mm",               parse_length_mm),   # pp AS-REPORTED
    "moving mass":                 ("mms_g",                  parse_mass_g),
    "bl factor":                   ("bl_tm",                  parse_bl_tm),
    "le @1 khz":                   ("le_mh",                  parse_le_mh),
    "le":                          ("le_mh",                  parse_le_mh),
}


@register
class BeymaScraper(Scraper):
    name = "beyma"
    manufacturer_display = "Beyma"
    schema_version = "1.0"
    expected_min_records = 160    # recon: ~194 active drivers across 10 kept categories
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(
                url=f"{_BASE}/en/products/c/{slug}/",
                context=SeedContext(driver_kind_hint=kind, category_id=slug),
            )
            for slug, kind in _CATEGORIES
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            seed_cat = art.url.rstrip("/").rsplit("/", 1)[-1].lower()
            seed_kind = next((k for c, k in _CATEGORIES if c == seed_cat), None)
            if seed_kind is None:
                continue
            body_text = art.body.decode("utf-8", errors="ignore")
            for m in _PRODUCT_URL_RE.finditer(body_text):
                if m.group(1).lower() != seed_cat:
                    continue
                url = m.group(0)
                if not url.endswith("/"):
                    url = url + "/"
                key = url.lower()
                if key in seen:
                    continue
                seen.add(key)
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(driver_kind_hint=seed_kind, category_id=seed_cat),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        specs: dict[str, str] = {}
        for item in soup.select("div.block-product-features div.items div.item"):
            t = item.select_one("div.title")
            d = item.select_one("div.description")
            if not t or not d:
                continue
            label = t.get_text(strip=True)
            value = d.get_text(" ", strip=True)
            if not label or not value:
                continue
            key = normalize_label(label)
            if key not in specs:
                specs[key] = value

        title = soup.title.get_text(strip=True) if soup.title else ""
        model = _model_from_title(title)
        if not model:
            return ParseResult(fragments=[])

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=seed_context.driver_kind_hint,
            model=model,
        )
        if seed_context.category_id == "amt-driver":
            frag.diaphragm_shape = "AMT"
            frag.spec_source["diaphragm_shape"] = SpecSource.INFERRED

        is_coax = seed_context.category_id == "coaxial"

        for norm_label, raw_val in specs.items():
            # Coax LF/HF-split rows first — value is like `8/16 ohm`.
            if is_coax and norm_label in _COAX_LFHF_LABELS:
                m = _COAX_LF_HF_PAIR_RE.match(raw_val)
                if m:
                    lf_field, hf_field = _COAX_LFHF_LABELS[norm_label]
                    try:
                        lf_val = float(m.group(1))
                        hf_val = float(m.group(2))
                    except ValueError:
                        continue
                    if lf_field is not None:
                        setattr(frag, lf_field, lf_val)
                        frag.spec_source[lf_field] = SpecSource.HTML_DIV_PAIRS
                    if hf_field is not None:
                        setattr(frag, hf_field, hf_val)
                        frag.spec_source[hf_field] = SpecSource.HTML_DIV_PAIRS
                continue
            mapping = _LABEL_MAP.get(norm_label)
            if mapping is None or mapping[0] is None:
                continue
            field_name, parser = mapping
            parsed = parser(raw_val) if parser else raw_val
            if parsed is None:
                continue
            if field_name == "__freq_range__":
                low, high = parsed  # type: ignore[misc]
                frag.freq_low_hz = low
                frag.freq_high_hz = high
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_DIV_PAIRS
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_DIV_PAIRS
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_DIV_PAIRS

        # Beyma HF compression drivers and tweeters don't publish a "Nominal
        # Diameter". Fall back through: throat (HF compressions), then cutout
        # (dome tweeters that publish it), then VC diameter (small dome tweeters
        # where the VC equals the dome diameter). AMT tweeters (Beyma TPL-*)
        # publish no diameters and stay size-less.
        if frag.nominal_size_mm is None and frag.driver_kind in (
            DriverKind.TWEETER, DriverKind.HF_COMPRESSION,
        ):
            derived = (
                frag.throat_diameter_mm
                or frag.mounting_diameter_mm
                or frag.voice_coil_diameter_mm
            )
            if derived is not None:
                frag.nominal_size_mm = derived
                frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        return ParseResult(fragments=[frag])
