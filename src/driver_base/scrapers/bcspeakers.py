"""B&C Speakers (bcspeakers.com) scraper.

Enumeration: 2 category listing pages (/en/products/lf-driver and /hf-driver),
both fully server-rendered (Remix.js SSR — no headless browser needed). All
product URLs are `<a href>` links matching
    /en/products/{category}/{inches}/{ohms}/{model}
and no pagination is used.

Extraction: `div.grid.grid-cols-2` with `<p>` label + `<h6><span>` value.
Values that have a tooltip icon nest a second `<span>` containing an SVG;
`get_text(strip=True)` correctly returns only the visible text (the SVG has
no text content).

Sensitivity slot: B&C's tooltip text explicitly states 'Applied RMS Voltage
is set to 2.83 V for 8 ohms Nominal Impedance', so values land in the
`sensitivity_db_2_83v_1m` slot regardless of the driver's actual impedance.
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


_BASE = "https://www.bcspeakers.com"

_CATEGORIES: list[tuple[str, DriverKind]] = [
    ("lf-driver", DriverKind.LF_WOOFER),
    ("hf-driver", DriverKind.HF_COMPRESSION),
]
_CAT_TO_KIND: dict[str, DriverKind] = {slug: kind for slug, kind in _CATEGORIES}

# Product URL captured from category HTML.
_PRODUCT_URL_RE = re.compile(
    r'/en/products/(?P<category>lf-driver|hf-driver)/[\d.]+/\d+/[A-Za-z0-9._-]+',
    re.IGNORECASE,
)
# Parse the `<inches>/<ohms>/<model>` tail — the inches segment is the LF cone
# diameter for lf-driver URLs, or the HF throat diameter for hf-driver URLs.
_URL_PATH_RE = re.compile(
    r'/en/products/(?P<category>lf-driver|hf-driver)/(?P<size>[\d.]+)/\d+/[A-Za-z0-9._-]+',
    re.IGNORECASE,
)
_MM_PER_INCH = 25.4


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    "fs":                          ("fs_hz",                  parse_frequency),
    "re":                          ("re_ohm",                 parse_impedance),
    "qes":                         ("qes",                    parse_float),
    "qms":                         ("qms",                    parse_float),
    "qts":                         ("qts",                    parse_float),
    "vas":                         ("vas_liters",             parse_liters),
    "sd":                          ("sd_cm2",                 parse_sd_cm2),
    "xmax":                        ("xmax_mm",                parse_length_mm),
    "mms":                         ("mms_g",                  parse_mass_g),
    "bl":                          ("bl_tm",                  parse_bl_tm),
    "le":                          ("le_mh",                  parse_le_mh),
    "ebp":                         ("ebp_hz",                 parse_frequency),
    "eta0":                        ("eta_zero_pct",           parse_float),
    "nominal impedance":           ("impedance_nominal_ohm",  parse_impedance),
    "minimum impedance":           ("impedance_min_ohm",      parse_impedance),
    "nominal power handling":      ("power_aes_watts",        parse_power),
    "continuous power handling":   ("power_long_term_watts",  parse_power),
    "sensitivity":                 ("sensitivity_db_2_83v_1m", parse_float),  # B&C tooltip: 2.83V
    "frequency range":             ("__freq_range__",         parse_range),
    "nominal diameter":            ("nominal_size_mm",        parse_length_mm),
    "voice coil diameter":         ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter":            ("overall_diameter_mm",    parse_length_mm),
    "baffle cutout diameter":      ("mounting_diameter_mm",   parse_length_mm),
    "depth":                       ("depth_mm",               parse_length_mm),
    "net weight":                  ("net_weight_kg",          _weight_kg),
    "magnet material":             ("magnet_type",            lambda s: normalize_magnet_type(s)),
}


@register
class BcSpeakersScraper(Scraper):
    name = "bcspeakers"
    manufacturer_display = "B&C Speakers"
    schema_version = "1.0"
    expected_min_records = 200    # recon: ~274 variants across LF+HF
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(
                url=f"{_BASE}/en/products/{slug}",
                context=SeedContext(driver_kind_hint=kind, category_id=slug),
            )
            for slug, kind in _CATEGORIES
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            # Determine which category this seed belongs to and only accept
            # product URLs from THAT category (cross-category "related product"
            # links exist on both category pages and would mis-tag DriverKind).
            seed_cat = art.url.rstrip("/").rsplit("/", 1)[-1].lower()
            seed_kind = _CAT_TO_KIND.get(seed_cat)
            if seed_kind is None:
                continue
            body_text = art.body.decode("utf-8", errors="ignore")
            for match in _PRODUCT_URL_RE.finditer(body_text):
                rel = match.group(0)
                if match.group("category").lower() != seed_cat:
                    continue
                key = rel.lower()
                if key in seen:
                    continue
                seen.add(key)
                products.append(
                    SeedRef(
                        url=f"{_BASE}{rel}",
                        context=SeedContext(driver_kind_hint=seed_kind, category_id=seed_cat),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        specs: dict[str, str] = {}
        for grid in soup.select("div.grid.grid-cols-2"):
            label_el = grid.select_one("p")
            value_el = grid.select_one("h6 span")
            if label_el is None or value_el is None:
                continue
            label = label_el.get_text(strip=True)
            value = value_el.get_text(strip=True)
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
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_GRID
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_GRID
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_GRID

        # B&C HF drivers don't publish a "Nominal Diameter" label — the URL
        # carries the throat inches (e.g. `/hf-driver/1.4/8/DE900TN`). Use it
        # as nominal_size_mm AND throat_diameter_mm, matching Faital/18Sound.
        # For LF drivers the label is authoritative; skip the URL fallback if
        # nominal_size_mm was already set.
        url_match = _URL_PATH_RE.search(raw.url)
        if url_match is not None:
            try:
                size_mm = float(url_match.group("size")) * _MM_PER_INCH
            except ValueError:
                size_mm = None
            if size_mm is not None:
                if frag.nominal_size_mm is None:
                    frag.nominal_size_mm = size_mm
                    frag.spec_source["nominal_size_mm"] = SpecSource.INFERRED
                if (
                    url_match.group("category").lower() == "hf-driver"
                    and frag.throat_diameter_mm is None
                ):
                    frag.throat_diameter_mm = size_mm
                    frag.spec_source["throat_diameter_mm"] = SpecSource.INFERRED

        return ParseResult(fragments=[frag])

    @staticmethod
    def _model_from_url(url: str) -> Optional[str]:
        m = _PRODUCT_URL_RE.search(url)
        if not m:
            return None
        model = url.rstrip("/").rsplit("/", 1)[-1]
        return model or None
