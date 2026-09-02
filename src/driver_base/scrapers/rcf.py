"""RCF (rcf.it) scraper.

Enumeration: 6 per-series search-results pages (`/en/search-results?serieId=`).
serieId=14 (Custom Designs) is excluded — its 34 items are accessories, not
standard transducers. The `/o/v1/*` Liferay REST endpoints are OAuth2-gated
and unusable without a token; the recon path is static HTML for both
listings and product detail pages.

Product URL: `/en/products/product-detail/{slug}` where the slug is
extracted from `product-detail/{slug}"` in the listing HTML.

Extraction: `div.specifications div.row` where each row has two
`div.col-md-6` children — first is the label, second is the value. Multiple
section headings ("General specifications", "Thiele - small parameters",
etc.) share the same container class, so one selector captures all.
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


_BASE = "https://www.rcf.it"

# serieId → DriverKind. serieId=14 (Custom Designs) EXCLUDED as non-driver.
_SERIES: list[tuple[int, str, DriverKind]] = [
    (27, "ferrite-lf", DriverKind.LF_WOOFER),
    (51, "neodymium-lf", DriverKind.LF_WOOFER),
    (50, "neodymium-compression", DriverKind.HF_COMPRESSION),
    (26, "ferrite-compression", DriverKind.HF_COMPRESSION),
    (11, "coaxial", DriverKind.COAX),
    (34, "horn-series", DriverKind.HORN),
]
_SERIE_TO_KIND: dict[int, DriverKind] = {sid: kind for sid, _, kind in _SERIES}

_SLUG_IN_LISTING_RE = re.compile(r'product-detail/([^"\'\s#?]+)')


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    # electrical / commercial
    "rated impedance": ("impedance_nominal_ohm", parse_impedance),
    # HF drivers + coax pages use "Related Impedance" (RCF phrasing) instead of
    # "Rated Impedance". On coax the LF section is listed first, so first-wins
    # keeps the LF value for the generic field.
    "related impedance": ("impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("impedance_min_ohm", parse_impedance),
    "cut-off frequency": ("recommended_crossover_hz", parse_frequency),
    "program power": ("power_program_watts", parse_power),
    "power handling capacity": ("power_aes_watts", parse_power),
    "sensitivity": ("sensitivity_db_1w_1m", parse_float),
    "frequency range": ("__freq_range__", parse_range),
    # T/S — RCF labels values (not the label) with the abbreviation, so
    # "Mechanical factor" → "6.50 Qms".  parse_float ignores trailing text.
    "resonance frequency": ("fs_hz", parse_frequency),
    "dc resistance": ("re_ohm", parse_impedance),
    "mechanical factor": ("qms", parse_float),
    "electrical factor": ("qes", parse_float),
    "total factor": ("qts", parse_float),
    "bl factor": ("bl_tm", parse_bl_tm),
    "effective moving mass": ("mms_g", parse_mass_g),
    "equivalent cas air loaded": ("vas_liters", parse_liters),
    "effective piston area": ("sd_cm2", parse_sd_cm2),
    "max. linear excursion": ("xmax_mm", parse_length_mm),
    "max. excursion before damage": ("xmech_mm", parse_length_mm),  # PP as-reported
    "voice coil inductance @ 1khz": ("le_mh", parse_le_mh),
    "half-space efficency": ("eta_zero_pct", parse_float),  # note typo in RCF source
    # physical
    "nominal diameter": ("nominal_size_mm", parse_length_mm),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "front mount baffle cut-out": ("mounting_diameter_mm", parse_length_mm),
    # HF driver pages publish `Exit Throat Diameter`; used as size fallback below.
    "exit throat diameter": ("throat_diameter_mm", parse_length_mm),
    "weight": ("net_weight_kg", _weight_kg),
    "magnets": ("magnet_type", lambda s: normalize_magnet_type(s)),
    # HF/coax pages label the magnet field "Magnetics" (plural, without 's').
    "magnetics": ("magnet_type", lambda s: normalize_magnet_type(s)),
    "diaphragm material": ("diaphragm_material", lambda s: (s or "").strip() or None),
    # Construction descriptors.
    "voice coil winding material": ("winding_material", lambda s: s or None),
    "voice coil former design": (
        "former_material",
        lambda s: s or None,
    ),  # "Direct Drive Kapton" style
    "surround material": ("surround_material", lambda s: s or None),
    "phase plug design": ("phase_plug_design", lambda s: s or None),
    "flux density": ("flux_density_t", parse_float),
    # Volume occupied — driver's own displacement, not enclosure recommendation.
    # RCF doesn't publish a recommended enclosure volume field consistently.
}


@register
class RcfScraper(Scraper):
    name = "rcf"
    manufacturer_display = "RCF"
    schema_version = "1.0"
    expected_min_records = 90  # recon: ~103 across 6 series (excl. Custom Designs)
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(
                url=f"{_BASE}/en/search-results?serieId={sid}",
                context=SeedContext(
                    driver_kind_hint=kind, series=slug, category_id=slug
                ),
            )
            for sid, slug, kind in _SERIES
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            # Derive kind from serieId query param on the seed URL
            m = re.search(r"serieId=(\d+)", art.url)
            if not m:
                continue
            sid = int(m.group(1))
            kind = _SERIE_TO_KIND.get(sid)
            if kind is None:
                continue
            body_text = art.body.decode("utf-8", errors="ignore")
            for slug_m in _SLUG_IN_LISTING_RE.finditer(body_text):
                slug = slug_m.group(1)
                key = slug.lower()
                if key in seen:
                    continue
                seen.add(key)
                products.append(
                    SeedRef(
                        url=f"{_BASE}/en/products/product-detail/{slug}",
                        context=SeedContext(
                            driver_kind_hint=kind,
                            series=str(sid),
                            category_id=str(sid),
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        specs: dict[str, str] = {}
        for row in soup.select("div.specifications div.row"):
            cols = row.select(":scope > div.col-md-6")
            if len(cols) < 2:
                continue
            label = cols[0].get_text(strip=True)
            value = cols[1].get_text(" ", strip=True)
            if not label or not value:
                continue
            key = normalize_label(label)
            if key not in specs:
                specs[key] = value

        model = self._model_from_url(raw.url)
        if not model:
            return ParseResult(fragments=[])

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
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_DIV_PAIRS
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_DIV_PAIRS
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_DIV_PAIRS

        # HF driver pages publish `Exit Throat Diameter` but no `Nominal
        # Diameter`. Use throat → size (Faital/18Sound/Beyma/B&C/Celestion
        # pattern). Only HF drivers publish "Exit Throat Diameter"; on coax
        # pages the LF section already sets nominal_size_mm, so this fallback
        # doesn't fire.
        if frag.throat_diameter_mm is not None and frag.nominal_size_mm is None:
            frag.nominal_size_mm = frag.throat_diameter_mm
            frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        return ParseResult(fragments=[frag])

    @staticmethod
    def _model_from_url(url: str) -> Optional[str]:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return slug.upper() if slug else None
