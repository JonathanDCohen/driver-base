"""18Sound (eighteensound.it) scraper.

Enumeration: 6 category listing pages. Five (`lf-driver`, `hf-driver`,
`coaxial`, `line-array-source`, `horn`) are static HTML; `tweeter` is JS-
rendered and must be Playwright-fetched at discover time. Product pages are
always static HTML, one product per URL, regardless of category.

Extraction: `li.float30` elements. Structure per element is
    <li class="float30">
      <span>LABEL</span>
      <sup class="note">(N)</sup>   <!-- optional footnote outside <b> -->
      <b>VALUE</b>
    </li>
so `li.select_one("span").get_text()` is the label and
`li.select_one("b").get_text()` is the value.

Field mapping notes:
  - "Resonance Frequency"           → fs_hz         (label is verbose, not "Fs")
  - "Nominal Power Handling"        → power_aes_watts
  - "Continuous Power Handling"     → power_long_term_watts  (18Sound convention: continuous > nominal)
  - "Sensitivity"                   → sensitivity_db_1w_1m   (1W/1m by 18Sound convention)
  - "Bl" value like "24.7 Txm" — the `x` is a multiplier; `parse_bl_tm` handles.

Model + impedance are lifted from the URL (path segments 5 and 4 respectively):
    /en/products/{category}/{diameter}/{impedance}/{model}
"""

from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup

from driver_base.interface import (
    DriverKind,
    EnumerateResult,
    FetcherKind,
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


_BASE = "https://www.eighteensound.it"

# Category slug → (DriverKind, needs_playwright_at_discover)
_CATEGORIES: list[tuple[str, DriverKind, bool]] = [
    ("lf-driver", DriverKind.LF_WOOFER, False),
    ("hf-driver", DriverKind.HF_COMPRESSION, False),
    ("coaxial", DriverKind.COAX, False),
    ("line-array-source", DriverKind.FULLRANGE, False),
    ("horn", DriverKind.HORN, False),
    ("tweeter", DriverKind.TWEETER, True),
]

_CAT_TO_KIND: dict[str, DriverKind] = {slug: kind for slug, kind, _ in _CATEGORIES}
_CATEGORY_SLUGS: str = "|".join(re.escape(slug) for slug, _, _ in _CATEGORIES)
_PRODUCT_URL_RE = re.compile(
    r'href="(/en/products/(?:' + _CATEGORY_SLUGS + r')/[0-9]+-[0-9]+/[0-9]+/[^"#?]+)"',
    re.IGNORECASE,
)
_URL_PATH_RE = re.compile(
    r'^/en/products/(?P<category>[^/]+)/[0-9]+-[0-9]+/(?P<impedance>[0-9]+)/(?P<model>[^/?#]+)/?$'
)
# Product pages display the model as the first `<h1 class="darkGrey">…</h1>`.
# URL slugs are inconsistently cased (some lowercase, some canonical) — prefer
# the h1 as the authoritative model name; slug is only a fallback.
_H1_MODEL_RE = re.compile(
    r'<h1\b[^>]*\bclass="[^"]*\bdarkGrey\b[^"]*"[^>]*>\s*([^<]+?)\s*</h1>',
    re.IGNORECASE,
)


def _parse_kg(s: Optional[str]) -> Optional[float]:
    """Convert a mass string (kg preferred, else lb) to kilograms."""
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


def _parse_magnet(s: Optional[str]):  # noqa: ANN202 - Optional[MagnetType]
    return normalize_magnet_type(s)


# Marker used for the "Frequency Range" label: parse_range returns a tuple
# which we unpack into both freq_low_hz and freq_high_hz.
_FREQ_RANGE_MARKER = "__freq_range__"

# Label (post normalize_label) → (Driver field | marker, parser)
_LABEL_MAP: dict[str, tuple[str, Callable[[Optional[str]], object]]] = {
    "resonance frequency": ("fs_hz", parse_frequency),
    "re": ("re_ohm", parse_impedance),
    "qes": ("qes", parse_float),
    "qms": ("qms", parse_float),
    "qts": ("qts", parse_float),
    "vas": ("vas_liters", parse_liters),
    "sd": ("sd_cm2", parse_sd_cm2),
    "xmax": ("xmax_mm", parse_length_mm),
    "mms": ("mms_g", parse_mass_g),
    "bl": ("bl_tm", parse_bl_tm),
    "le": ("le_mh", parse_le_mh),
    "ebp": ("ebp_hz", parse_frequency),
    "eta0": ("eta_zero_pct", parse_float),
    "nominal impedance": ("impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("impedance_min_ohm", parse_impedance),
    "sensitivity": ("sensitivity_db_1w_1m", parse_float),
    "nominal power handling": ("power_aes_watts", parse_power),
    "continuous power handling": ("power_long_term_watts", parse_power),
    "frequency range": (_FREQ_RANGE_MARKER, parse_range),
    "nominal diameter": ("nominal_size_mm", parse_length_mm),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "baffle cutout diameter": ("mounting_diameter_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),
    "net weight": ("net_weight_kg", _parse_kg),
    "magnet material": ("magnet_type", _parse_magnet),
}


@register
class EighteenSoundScraper(Scraper):
    name = "eighteensound"
    manufacturer_display = "18Sound"
    schema_version = "1.0"
    expected_min_records = 275
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(
                url=f"{_BASE}/en/products/{slug}",
                context=SeedContext(driver_kind_hint=kind, category_id=slug),
            )
            for slug, kind, _ in _CATEGORIES
        ]

    def preferred_fetcher(self, url: str) -> Optional[FetcherKind]:
        # Only the tweeter category-listing seed URL is JS-rendered.
        # Individual tweeter product pages ARE static once we know the URL.
        for slug, _, needs_pw in _CATEGORIES:
            if needs_pw and url.rstrip("/").endswith(f"/en/products/{slug}"):
                return FetcherKind.PLAYWRIGHT
        return None

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        seen: set[str] = set()
        products: list[SeedRef] = []
        for art in seed_artifacts:
            category_slug = _category_slug_of_seed(art.url)
            kind = _CAT_TO_KIND.get(category_slug)
            body_text = art.body.decode("utf-8", errors="ignore")
            for rel in _PRODUCT_URL_RE.findall(body_text):
                key = rel.lower()
                if key in seen:
                    continue
                seen.add(key)
                url = f"{_BASE}{rel}"
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(driver_kind_hint=kind, category_id=category_slug),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        model_and_impedance = _extract_model_and_impedance_from_url(raw.url)
        if model_and_impedance is None:
            return ParseResult(fragments=[])
        model_from_url, impedance_from_url, category_from_url = model_and_impedance

        kind = seed_context.driver_kind_hint or _CAT_TO_KIND.get(category_from_url or "")

        # Prefer the page's own display heading — URL slugs are inconsistently
        # cased across 18Sound's catalog (some `15NTLW3500`, some `15ntlw2500`).
        text = raw.body.decode("utf-8", errors="ignore")
        h1_match = _H1_MODEL_RE.search(text)
        model = (h1_match.group(1).strip() if h1_match else "") or model_from_url

        soup = BeautifulSoup(raw.body, "lxml")
        specs: dict[str, str] = {}
        for li in soup.select("li.float30"):
            label_el = li.select_one("span")
            val_el = li.select_one("b")
            if label_el is None or val_el is None:
                continue
            label = label_el.get_text(strip=True)
            val = val_el.get_text(strip=True)
            if not label or not val:
                continue
            normalized = normalize_label(label)
            # First-wins if a label repeats across the 4 spec sections.
            if normalized not in specs:
                specs[normalized] = val

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=model,
        )
        # Seed impedance from URL if HTML doesn't provide one; HTML wins if both.
        if impedance_from_url is not None:
            frag.impedance_nominal_ohm = impedance_from_url
            frag.spec_source["impedance_nominal_ohm"] = SpecSource.INFERRED

        for label, raw_val in specs.items():
            mapping = _LABEL_MAP.get(label)
            if mapping is None:
                continue
            field_name, parser = mapping
            parsed = parser(raw_val)
            if parsed is None:
                continue
            if field_name == _FREQ_RANGE_MARKER:
                low, high = parsed  # type: ignore[misc]
                frag.freq_low_hz = low
                frag.freq_high_hz = high
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_PROSE
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_PROSE
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_PROSE

        return ParseResult(fragments=[frag])


def _category_slug_of_seed(url: str) -> str:
    """Extract the category slug from a seed URL like
    'https://www.eighteensound.it/en/products/lf-driver'."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _extract_model_and_impedance_from_url(
    url: str,
) -> Optional[tuple[str, Optional[float], Optional[str]]]:
    """Parse '/en/products/{category}/{diameter}/{impedance}/{model}'.

    Returns (model, impedance_ohm, category_slug) or None if the URL doesn't
    match the expected shape.
    """
    from urllib.parse import urlparse

    path = urlparse(url).path
    m = _URL_PATH_RE.match(path)
    if not m:
        return None
    model = unquote(m.group("model")).strip()
    if not model:
        return None
    try:
        impedance = float(m.group("impedance"))
    except (TypeError, ValueError):
        impedance = None
    return model, impedance, m.group("category")
