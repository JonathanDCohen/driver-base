"""LaVoce (lavocespeakers.com) scraper.

Enumeration: `products-sitemap.xml` — the WordPress All-in-One SEO plugin
lists every published product. Filter to English `/product/<slug>/` URLs
(non-English locales are listed alongside; we only ingest the English catalog).
276 product URLs as of 2026-11-05.

DriverKind: breadcrumb (JSON-LD `BreadcrumbList` in the product HTML) carries
the collection name (`Pro Audio > Ferrite Low Frequency Transducers > MODEL`).
Map by collection slug.

Extraction: specs live in `div.lv--product-section-specifications`. Each spec
is a Bootstrap grid `div.row` whose two `div.col-6` children are label (first)
and value (second, inside `span.lv--fw-bold`). Dimensional specs additionally
embed a `span.lv--product-unit` listing units; existing unit parsers already
tolerate the concatenated `"165mm(6.5in)"` shape.

Sensitivity slot: `sensitivity_db_1w_1m` — LaVoce doesn't carry an explicit
2.83V annotation on its "Sensitivity dB" label; per European pro-audio
convention we treat the unlabelled value as 1W/1m.
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


_KHZ_TAIL_RE = re.compile(
    r"^\s*(-?\d+(?:[.,]\d+)?)\s*([÷\-–—])\s*(-?\d+(?:[.,]\d+)?)\s*(khz|hz)\b",
    re.IGNORECASE,
)


def _parse_frequency_range(s: Optional[str]) -> Optional[tuple[float, float]]:
    """LaVoce writes frequency ranges with the unit on the high endpoint only.
    Two shapes seen in practice:

      "500÷18000Hz"   both endpoints share the trailing unit (Hz here)
      "70 ÷ 22kHz"    2-way coax: low is implicit Hz, high is kHz

    The shared `parse_range` doesn't handle the second case — a single tagged
    endpoint drops its multiplier when flattened to the all-numbers path.

    Rule: apply the tagged unit to both endpoints; if that produces a range
    where the bare values would be physically impossible (low > high ÷ 100 when
    the unit is kHz, i.e. low endpoint is implausibly deep into the ultrasonic
    region), treat the low as Hz instead.
    """
    if s is None:
        return None
    m = _KHZ_TAIL_RE.match(s)
    if not m:
        return parse_range(s)
    low_s, high_s, unit = m.group(1), m.group(3), m.group(4)
    try:
        low = float(low_s.replace(",", "."))
        high = float(high_s.replace(",", "."))
    except ValueError:
        return parse_range(s)
    mult = 1000.0 if unit.lower() == "khz" else 1.0
    # Same-unit interpretation. If this gives low > high, the low must have
    # been in Hz (`"70 ÷ 22kHz"` style) — recompute with Hz on the low side.
    if unit.lower() == "khz" and low > high:
        return (low, high * mult)
    return (low * mult, high * mult)


_BASE = "https://lavocespeakers.com"
_SITEMAP_URL = f"{_BASE}/products-sitemap.xml"

_LOC_RE = re.compile(r"<loc><!\[CDATA\[([^\]]+)\]\]>")
_PRODUCT_URL_RE = re.compile(r"^https?://lavocespeakers\.com/product/[^/]+/?$")

# JSON-LD BreadcrumbList item names → DriverKind.  Checked against the
# penultimate breadcrumb (the collection, one step above the product itself).
# Keys compared case-insensitively on the name string in @context JSON.
# Keys compared case-insensitively against the second-to-last breadcrumb
# `name`. Checked by substring containment (longest key wins) so phrasing
# tweaks like "LF Transducers" vs "Low Frequency Transducers" both map.
_COLLECTION_TO_KIND: dict[str, DriverKind] = {
    # Order-sensitive on substring overlap: list more-specific collection
    # names (that would also match a shorter key) BEFORE the shorter key.
    "weather resistant coaxials": DriverKind.COAX,
    "hf compression drivers": DriverKind.HF_COMPRESSION,
    "compression drivers": DriverKind.HF_COMPRESSION,
    "lf transducers": DriverKind.LF_WOOFER,
    "low frequency transducers": DriverKind.LF_WOOFER,
    "bass speakers": DriverKind.LF_WOOFER,
    "lead guitar speakers": DriverKind.GUITAR_BASS,
    "guitar speakers": DriverKind.GUITAR_BASS,
    "small size fullranges": DriverKind.FULLRANGE,
    "fullranges": DriverKind.FULLRANGE,
    "soft dome tweeters": DriverKind.TWEETER,
    "dome tweeters": DriverKind.TWEETER,
    "tweeters": DriverKind.TWEETER,
    "coaxials": DriverKind.COAX,
    "coaxial": DriverKind.COAX,
    "horns": DriverKind.HORN,
}


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


# Normalized-label → (Driver field, parser). `normalize_label` lower-cases and
# strips descriptive parentheticals like "(Re)" / "(Fs)" but preserves
# measurement-context ones.
_LABEL_MAP: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    # General
    "nominal diameter": ("nominal_size_mm", parse_length_mm),
    "nominal impedance": ("impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("impedance_min_ohm", parse_impedance),
    "program power": ("power_program_watts", parse_power),
    "aes power rating": ("power_aes_watts", parse_power),
    "sensitivity": ("sensitivity_db_1w_1m", parse_float),
    "frequency range": ("__freq_range__", _parse_frequency_range),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "chassis material": (None, None),  # not captured in schema
    "magnet material": ("magnet_type", lambda s: normalize_magnet_type(s)),
    "magnet dimensions od x id x h": (None, None),
    "coil material": ("winding_material", lambda s: (s or "").strip() or None),
    "former material": ("former_material", lambda s: (s or "").strip() or None),
    "cone material": (None, None),
    "surround material": ("surround_material", lambda s: (s or "").strip() or None),
    "xmax": ("xmax_mm", parse_length_mm),
    "xmech": ("xmech_mm", parse_length_mm),
    "gap height": (None, None),  # schema gap
    "voice coil winding height": (None, None),  # schema gap
    "driver displacement volume": ("vd_liters", parse_liters),
    "recommended enclosure": (
        "recommended_enclosure_volume_liters",
        parse_liters,
    ),
    "recommended tuning": (None, None),  # schema gap
    # Small Signal Parameters
    "dc resistance": ("re_ohm", parse_impedance),
    "diaphragm area": ("sd_cm2", parse_sd_cm2),
    "resonance frequency": ("fs_hz", parse_frequency),
    "moving mass": ("mms_g", parse_mass_g),
    "compliance": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "force factor": ("bl_tm", parse_bl_tm),
    "force factor (bxl)": ("bl_tm", parse_bl_tm),
    "mechanical q-factor": ("qms", parse_float),
    "electrical q-factor": ("qes", parse_float),
    "total q-factor": ("qts", parse_float),
    "equivalent air volume": ("vas_liters", parse_liters),
    "voice coil inductance": ("le_mh", parse_le_mh),
    "reference efficiency": ("eta_zero_pct", parse_float),
    "efficiency bandwidth product": ("ebp_hz", parse_frequency),
    # Shipping / mounting (appear on some products)
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "mounting hole diameter": ("mounting_diameter_mm", parse_length_mm),
    "cutout diameter": ("mounting_diameter_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),
    "net weight": ("net_weight_kg", _weight_kg),
    "weight": ("net_weight_kg", _weight_kg),
    "flux density": ("flux_density_t", parse_float),
    # HF-specific
    "throat diameter": ("throat_diameter_mm", parse_length_mm),
    "diaphragm material": (
        "diaphragm_material",
        lambda s: (s or "").strip() or None,
    ),
    "recommended crossover": ("recommended_crossover_hz", parse_frequency),
}


_MODEL_H1_CLEAN_RE = re.compile(r"\s+-\s*LAVOCE\s*$", re.IGNORECASE)


def _extract_model(soup: BeautifulSoup, html: str) -> Optional[str]:
    """Prefer the H1 (empirically matches the published model with periods and
    dashes preserved); fall back to the og:title / <title> stripped of the
    ` - LAVOCE` suffix."""
    h1 = soup.find("h1")
    if h1 is not None:
        txt = h1.get_text(strip=True)
        if txt:
            return txt
    title = soup.title.get_text(strip=True) if soup.title else ""
    title = _MODEL_H1_CLEAN_RE.sub("", title).strip()
    return title or None


def _extract_breadcrumb_kind(html: str) -> Optional[DriverKind]:
    """Parse the JSON-LD BreadcrumbList to find the collection (position=4
    typically — Home > Products > Pro Audio > <Collection> > <Model>), look it
    up in the collection map."""
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        body = m.group(1).strip()
        # Strip XML-style leading whitespace (seen on LaVoce) that would break
        # strict json.loads; `body.strip()` is the most robust move.
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        graph = parsed.get("@graph") if isinstance(parsed, dict) else None
        if not isinstance(graph, list):
            continue
        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "BreadcrumbList":
                continue
            items = node.get("itemListElement") or []
            # The last item is the product; the one before is the collection.
            names: list[str] = []
            for it in items:
                if isinstance(it, dict) and isinstance(it.get("name"), str):
                    names.append(it["name"])
            if len(names) < 2:
                continue
            # Walk breadcrumbs from the collection (one before product) up
            # toward the root. First substring match wins. The map is ordered
            # so more-specific keys ("weather resistant coaxials") are checked
            # before less-specific ones ("coaxials").
            for name in reversed(names[:-1]):
                needle = name.strip().lower()
                for key, kind in _COLLECTION_TO_KIND.items():
                    if key in needle:
                        return kind
    return None


@register
class LaVoceScraper(Scraper):
    name = "lavoce"
    manufacturer_display = "LaVoce"
    schema_version = "1.0"
    # Sitemap currently lists 276 English product URLs. The floor is kept
    # low because SG captcha can pick off most of a run at random, leaving a
    # handful of cached-or-pre-captcha pages — we'd rather publish those
    # than preserve-with-empty-prior. On a healthy run this is a no-op
    # (records will be 250+); on a captcha-gated run the delta gate still
    # catches a >30% drop against a non-zero prior.
    expected_min_records = 2
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_SITEMAP_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            body = art.body.decode("utf-8", errors="ignore")
            for m in _LOC_RE.finditer(body):
                url = m.group(1).strip()
                if not _PRODUCT_URL_RE.match(url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                products.append(SeedRef(url=url, context=SeedContext()))
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        html = raw.body.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(raw.body, "lxml")

        model = _extract_model(soup, html)
        if not model:
            return ParseResult(fragments=[])

        kind = seed_context.driver_kind_hint or _extract_breadcrumb_kind(html)

        spec_section = soup.find(class_="lv--product-section-specifications")
        if spec_section is None:
            # No spec block — emit a minimal fragment so the product still
            # appears in the catalog, as long as we have a kind.
            if kind is None:
                return ParseResult(fragments=[])
            frag = DriverFragment(
                manufacturer=self.manufacturer_display,
                source_url=raw.url,
                fetched_at=raw.fetched_at,
                driver_kind=kind,
                model=model,
            )
            return ParseResult(fragments=[frag])

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=model,
        )

        # Each spec row is a `div.row` with two `div.col-6`.
        for row in spec_section.select("div.row"):
            cols = row.find_all("div", class_="col-6", recursive=False)
            if len(cols) < 2:
                continue
            label_txt = cols[0].get_text(" ", strip=True)
            value_el = cols[1].find(class_="lv--fw-bold")
            if value_el is None:
                continue
            # Strip the inline unit `<span>` children so the raw string is
            # "165mm(6.5in)" rather than "165 mm (6.5 in )" — existing unit
            # parsers handle both but the compact form keeps thousands-comma
            # heuristics tight.
            raw_val = value_el.get_text(strip=True)
            if not label_txt or not raw_val:
                continue
            key = normalize_label(label_txt)
            mapping = _LABEL_MAP.get(key)
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
