"""Eminence (eminence.com) scraper.

Enumeration: single Shopify `/products.json?limit=250` call yields all 155
active products in one response. `product.product_type` on each item drives
`driver_kind_hint` before the per-product fetch — this scraper does NOT need
`Scraper.classify_driver_kind()` because kind is known at enumeration time.

Extraction: a single spec table under `table#em-detail` with `<tr><td>label
</td><td>value</td></tr>` rows. Labels are verbose ("Resonant Frequency
(fs)"); the `(fs)`/`(Re)`/... parentheticals are descriptive and stripped by
`normalize_label`. Asterisks on labels (`"Nominal Impedance*"`) are also
stripped.

Sensitivity slot: 1W/1m (Eminence convention — the "Sensitivity*" label is
unlabelled and per manufacturer datasheets it is 1W/1m).

Non-driver product_types (Crossover, Speaker Cable, Components, Protection,
Hardware, empty) are filtered out at enumerate.
"""

from __future__ import annotations

import json
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


_BASE = "https://eminence.com"

# product_type → DriverKind. Unmapped types are dropped at enumerate.
_TYPE_TO_KIND: dict[str, DriverKind] = {
    "American Standard Series Replacement Speaker":  DriverKind.LF_WOOFER,
    "Professional Series Replacement Speaker":       DriverKind.LF_WOOFER,
    "Neodymium Series Replacement Speaker":          DriverKind.LF_WOOFER,
    "Replacement Speaker":                           DriverKind.LF_WOOFER,
    "Tour Grade Replacement Speaker":                DriverKind.LF_WOOFER,
    "Signature Series Guitar Replacement Speaker":   DriverKind.GUITAR_BASS,
    "Patriot Guitar Replacement Speaker":            DriverKind.GUITAR_BASS,
    "Legend Guitar":                                 DriverKind.GUITAR_BASS,
    "Redcoat Guitar Replacement Speaker":            DriverKind.GUITAR_BASS,
    "Bass Guitar Replacement Speaker":               DriverKind.GUITAR_BASS,
    "High Frequency":                                DriverKind.HF_COMPRESSION,
    "Tweeter":                                       DriverKind.TWEETER,
    "Waveguide":                                     DriverKind.HORN,
}
_SKIP_TYPES: frozenset[str] = frozenset({
    "Crossover", "Speaker Cable", "Components", "Protection", "Hardware", "",
})


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


# `X", Y mm` pattern — cross-check both sides. Eminence has published typos
# where the metric value is `0 mm`, an empty string, or has a spurious space
# (`12", 25 4 mm` where the "254mm" got split). When mm and inches disagree
# by more than 5%, prefer inches × 25.4 — typos are almost always on the
# metric side, and the inches value is the primary spec.
_INCHES_RE = re.compile(r"([\d.]+)\s*(?:\"|″|in\b)", re.IGNORECASE)

def _parse_diameter_mm(s: Optional[str]) -> Optional[float]:
    mm = parse_length_mm(s)
    if s is None:
        return mm
    m = _INCHES_RE.search(s)
    if m:
        try:
            inches_mm = float(m.group(1)) * 25.4
        except ValueError:
            return mm
        if mm is None or mm < 1.0:
            return inches_mm
        # Both present — trust inches when metric is way off.
        if abs(mm - inches_mm) / inches_mm > 0.05:
            return inches_mm
    return mm


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    # T/S (verbose Eminence labels)
    "resonant frequency":                      ("fs_hz",           parse_frequency),
    "resonance":                               ("fs_hz",           parse_frequency),
    "dc resistance":                           ("re_ohm",          parse_impedance),
    "coil inductance":                         ("le_mh",           parse_le_mh),
    "voice coil inductance":                   ("le_mh",           parse_le_mh),
    "mechanical q":                            ("qms",             parse_float),
    "electromagnetic q":                       ("qes",             parse_float),
    "total q":                                 ("qts",             parse_float),
    "compliance equivalent volume":            ("vas_liters",      parse_liters),
    "mechanical compliance of suspension":     ("cms_mm_per_n",    parse_compliance_mm_per_n),
    "bl product":                              ("bl_tm",           parse_bl_tm),
    "diaphragm mass inc. airload":             ("mms_g",           parse_mass_g),
    "efficiency bandwidth product":            ("ebp_hz",          parse_frequency),
    "maximum linear excursion":                ("xmax_mm",         parse_length_mm),
    "maximum mechanical limit":                ("xmech_mm",        parse_length_mm),
    "surface area of cone":                    ("sd_cm2",          parse_sd_cm2),
    # electrical / commercial
    "nominal impedance":                       ("impedance_nominal_ohm", parse_impedance),
    "program power":                           ("power_program_watts",   parse_power),
    "watts":                                   ("power_aes_watts",       parse_power),  # Eminence 'Watts' is the AES rating (2× → 'Program Power' matches AES convention)
    "power rating":                            ("power_aes_watts",       parse_power),  # HF/tweeter pages use "Power Rating" instead of "Watts"
    "sensitivity":                             ("sensitivity_db_1w_1m",  parse_float),
    "usable frequency range":                  ("__freq_range__",        parse_range),
    "recommended crossover":                   ("recommended_crossover_hz", parse_frequency),
    "low rec. crossover":                      ("recommended_crossover_hz", parse_frequency),
    # physical
    "nominal basket diameter":                 ("nominal_size_mm",       _parse_diameter_mm),
    "voice coil diameter":                     ("voice_coil_diameter_mm", _parse_diameter_mm),
    "overall diameter":                        ("overall_diameter_mm",   _parse_diameter_mm),
    "baffle hole diameter":                    ("mounting_diameter_mm",  _parse_diameter_mm),
    "depth":                                   ("depth_mm",              _parse_diameter_mm),
    # HF compression drivers and tweeters publish `Throat Size` in place of
    # `Nominal basket diameter`; used as size fallback in the post-parse step.
    "throat size":                             ("throat_diameter_mm",    _parse_diameter_mm),
    "net weight":                              ("net_weight_kg",         _weight_kg),
    "weight":                                  ("net_weight_kg",         _weight_kg),  # HF/tweeter pages use "Weight"
    "magnet material":                         ("magnet_type",           lambda s: normalize_magnet_type(s)),
}


def _model_from_handle(handle: str) -> str:
    """Uppercase the URL handle and turn '_' into ' '. Best-effort readable id."""
    return handle.replace("_", " ").upper().strip() or handle


@register
class EminenceScraper(Scraper):
    name = "eminence"
    manufacturer_display = "Eminence"
    schema_version = "1.0"
    expected_min_records = 70     # recon enumerated ~139 driver types; live parse yields ~80 (many lack #em-detail)
    max_seed_rounds = 2           # Shopify limit=250 → single page suffices

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=f"{_BASE}/products.json?limit=250&page=1", context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            try:
                payload = json.loads(art.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for p in payload.get("products") or []:
                handle = p.get("handle")
                if not handle or handle in seen:
                    continue
                seen.add(handle)
                product_type = (p.get("product_type") or "").strip()
                if product_type in _SKIP_TYPES:
                    continue
                kind = _TYPE_TO_KIND.get(product_type)
                if kind is None:
                    continue
                products.append(
                    SeedRef(
                        url=f"{_BASE}/products/{handle}",
                        context=SeedContext(
                            driver_kind_hint=kind,
                            category_id=product_type,
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")
        table = soup.select_one("table#em-detail")
        if table is None:
            return ParseResult(fragments=[])

        specs: dict[str, str] = {}
        for tr in table.select("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if not label or not value or value in ("--", "-"):
                continue
            key = normalize_label(label)
            if key not in specs:
                specs[key] = value

        handle = raw.url.rstrip("/").rsplit("/", 1)[-1]
        model = _model_from_handle(handle)

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=seed_context.driver_kind_hint,
            model=model,
        )

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
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_TABLE
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_TABLE
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_TABLE

        # HF compression drivers and tweeters publish `Throat Size` but no
        # `Nominal basket diameter` — use throat as size (Faital/18Sound/Beyma/
        # B&C/Celestion pattern). Only compression drivers/tweeters publish
        # Throat Size on Eminence pages so the fallback is safe.
        if frag.throat_diameter_mm is not None and frag.nominal_size_mm is None:
            frag.nominal_size_mm = frag.throat_diameter_mm
            frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        return ParseResult(fragments=[frag])
