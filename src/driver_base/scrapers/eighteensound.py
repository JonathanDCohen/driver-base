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
from urllib.parse import unquote, urlparse

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
    r"^/en/products/(?P<category>[^/]+)/(?P<size>[0-9]+-[0-9]+)/(?P<impedance>[0-9]+)/(?P<model>[^/?#]+)/?$"
)
# Categories where the URL `size` segment is the driver's nominal diameter (in
# inches; `X-Y` → `X.Y`). Horns use the same shape for their throat, but a
# horn's "size" isn't a horn concept — leave nominal_size_mm null there.
_URL_SIZE_CATEGORIES: frozenset[str] = frozenset(
    {
        "lf-driver",
        "hf-driver",
        "coaxial",
        "line-array-source",
    }
)
_MM_PER_INCH = 25.4
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
# Coax pages label the LF-side of the coaxial's shared specs with `LF ` and the
# HF-side with `HF ` (e.g. `LF Sensitivity` / `HF Sensitivity`). Also, minimum
# impedance for the woofer is labelled `Minimum Impedance LF`. Strip / rewrite
# these when parsing a coax page so the LF values feed the generic fields and
# the HF values feed the coax_hf_* fields.
_COAX_LF_LABEL_REWRITES: dict[str, str] = {
    "lf sensitivity": "sensitivity",
    "lf nominal power handling": "nominal power handling",
    "lf continuous power handling": "continuous power handling",
    "lf voice coil diameter": "voice coil diameter",
    "lf winding material": "__drop__",
    "minimum impedance lf": "minimum impedance",
}
# HF-side labels on a coax page → coax_hf_* fields.
_COAX_HF_LABEL_MAP: dict[str, tuple[str, Callable[[Optional[str]], object]]] = {
    "hf sensitivity": ("coax_hf_sensitivity_db_1w_1m", lambda s: parse_float(s)),
    "hf nominal power handling": ("coax_hf_power_aes_watts", lambda s: parse_power(s)),
    "hf continuous power handling": (
        "coax_hf_power_long_term_watts",
        lambda s: parse_power(s),
    ),
    "hf voice coil diameter": (
        "coax_hf_voice_coil_diameter_mm",
        lambda s: parse_length_mm(s),
    ),
}


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
    "recommended crossover": ("recommended_crossover_hz", parse_frequency),
    "continuous power handling": ("power_long_term_watts", parse_power),
    "frequency range": (_FREQ_RANGE_MARKER, parse_range),
    "nominal diameter": ("nominal_size_mm", parse_length_mm),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "baffle cutout diameter": ("mounting_diameter_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),
    "net weight": ("net_weight_kg", _parse_kg),
    "magnet material": ("magnet_type", _parse_magnet),
    "diaphragm material": ("diaphragm_material", lambda s: (s or "").strip() or None),
    "winding material": ("winding_material", lambda s: (s or "").strip() or None),
    "former material": ("former_material", lambda s: (s or "").strip() or None),
    "surround shape": ("surround_material", lambda s: (s or "").strip() or None),
    "phase plug design": ("phase_plug_design", lambda s: (s or "").strip() or None),
    "flux density": ("flux_density_t", parse_float),
    "xvar": ("xvar_mm", parse_length_mm),
    "recommended enclosure": ("recommended_enclosure_volume_liters", parse_liters),
    "recommended enclosure volume": (
        "recommended_enclosure_volume_liters",
        parse_liters,
    ),
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
                        context=SeedContext(
                            driver_kind_hint=kind, category_id=category_slug
                        ),
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

        kind = seed_context.driver_kind_hint or _CAT_TO_KIND.get(
            category_from_url or ""
        )

        # Prefer the page's own display heading — URL slugs are inconsistently
        # cased across 18Sound's catalog (some `15NTLW3500`, some `15ntlw2500`).
        text = raw.body.decode("utf-8", errors="ignore")
        h1_match = _H1_MODEL_RE.search(text)
        model = (h1_match.group(1).strip() if h1_match else "") or model_from_url

        soup = BeautifulSoup(raw.body, "lxml")
        is_coax = category_from_url == "coaxial"
        specs: dict[str, str] = {}
        specs_coax_hf: dict[str, str] = {}
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
            if is_coax:
                # HF-side labels on a coax page get their own bucket so they
                # route to coax_hf_* fields; LF-side labels are rewritten to
                # the generic form so they feed the primary fields.
                if normalized in _COAX_HF_LABEL_MAP:
                    if normalized not in specs_coax_hf:
                        specs_coax_hf[normalized] = val
                    continue
                rewritten = _COAX_LF_LABEL_REWRITES.get(normalized)
                if rewritten == "__drop__":
                    continue
                if rewritten is not None:
                    normalized = rewritten
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

        # Coax HF-section fields (only labels observed on coax pages route here).
        for label, raw_val in specs_coax_hf.items():
            mapping = _COAX_HF_LABEL_MAP.get(label)
            if mapping is None:
                continue
            field_name, parser = mapping
            parsed = parser(raw_val)
            if parsed is None:
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_PROSE

        # 18Sound puts the driver's nominal size in a small header widget
        # above the spec sections:
        #   <div class="inchesWrapper"><p><span> 18.0 </span> In</p></div>
        # This is the manufacturer's own labeled value (not URL / model
        # inference), so prefer it over the URL-slug fallback below.
        # For HF drivers, the "size" IS the throat diameter — populate both.
        if frag.nominal_size_mm is None:
            inches_el = soup.select_one("div.inchesWrapper span")
            if inches_el is not None:
                inches = parse_float(inches_el.get_text(strip=True))
                if inches is not None and inches > 0:
                    frag.nominal_size_mm = round(inches * _MM_PER_INCH, 1)
                    frag.spec_source["nominal_size_mm"] = SpecSource.HTML_GRID
                    if (
                        category_from_url == "hf-driver"
                        and frag.throat_diameter_mm is None
                    ):
                        frag.throat_diameter_mm = frag.nominal_size_mm
                        frag.spec_source["throat_diameter_mm"] = SpecSource.HTML_GRID

        # Fall back to the URL's size segment (`X-Y` → `X.Y` in inches) when
        # neither the inchesWrapper widget nor a spec label populated the
        # field. Applies to driver categories where the segment is the
        # driver's size — LF/HF drivers, coax, line-array sources — and
        # skipped for horns where the same segment is a throat diameter, not
        # a "size" concept for the horn. For HF drivers, the size IS the
        # throat — set both fields.
        if category_from_url in _URL_SIZE_CATEGORIES:
            path_match = _URL_PATH_RE.match(urlparse(raw.url).path)
            if path_match is not None:
                size_mm = _size_mm_from_url_segment(path_match.group("size"))
                if size_mm is not None:
                    if frag.nominal_size_mm is None:
                        frag.nominal_size_mm = size_mm
                        frag.spec_source["nominal_size_mm"] = SpecSource.INFERRED
                    if (
                        category_from_url == "hf-driver"
                        and frag.throat_diameter_mm is None
                    ):
                        frag.throat_diameter_mm = size_mm
                        frag.spec_source["throat_diameter_mm"] = SpecSource.INFERRED

        return ParseResult(fragments=[frag])


def _category_slug_of_seed(url: str) -> str:
    """Extract the category slug from a seed URL like
    'https://www.eighteensound.it/en/products/lf-driver'."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _size_mm_from_url_segment(seg: str) -> Optional[float]:
    """`18-0` → 457.2 mm; `1-4` → 35.56 mm. Returns None if unparseable."""
    parts = seg.split("-", 1)
    if len(parts) != 2:
        return None
    try:
        return (float(parts[0]) + float(parts[1]) / 10.0) * _MM_PER_INCH
    except ValueError:
        return None


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
