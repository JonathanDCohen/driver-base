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

# Title pattern: '{TYPE} {MODEL} {N} Ohm' — extract MODEL.
_TITLE_MODEL_WITH_OHM_RE = re.compile(
    r"\s(\S+)\s+\d+(?:\.\d+)?\s*Ohm\s*$", re.IGNORECASE
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

        for norm_label, raw_val in specs.items():
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

        return ParseResult(fragments=[frag])
