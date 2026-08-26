"""Celestion (celestion.com) scraper.

Enumeration: parse `product-sitemap.xml`, filter to `/product/*/` URLs
(the sitemap's single `/products/` index URL is skipped). Yields 213 product
detail URLs as of 2026-08-22.

Rate limit: robots.txt sets **`Crawl-delay: 10`** — the shared HostRateLimiter
honors that automatically, so a full run is ~35 minutes. `max_seed_rounds`
stays at the default 2 (sitemap is a single fetch).

Extraction: `div.product-detail-spec-col-line` — each contains two anonymous
child `<div>`s: first is the label, second is the value. A single selector
captures both the 'Specifications' and 'Parameters' sections on pro drivers.

DriverKind classification: derived from the on-page breadcrumb
    `Home / {top-level} / {subtype} / {model}`
Guitar and bass drivers land in `DriverKind.GUITAR_BASS` (exempt from the
missing-T/S REJECT); pro-audio drivers map by subtype (LF Loudspeakers,
Compression Drivers, Tweeters, Coaxial, Horns).

Sensitivity slot: `sensitivity_db_1w_1m` (Celestion convention).

Guitar drivers use comma-suffix labels: `Resonance frequency, Fs` and
`DC resistance, Re` — both handled explicitly in the label map.

Label quirks:
  - `BI` (letter I) is a Celestion typo for `Bl`; both map to bl_tm.
  - `Le (at 1kHz)` normalizes to `le`; the annotation is stripped.
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


_BASE = "https://celestion.com"
_SITEMAP_URL = f"{_BASE}/product-sitemap.xml"

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
_PRODUCT_URL_RE = re.compile(r"^https?://celestion\.com/product/[^/]+/?$", re.IGNORECASE)


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    # T/S — both plain and guitar-driver comma-suffix variants
    "fs":                          ("fs_hz",                  parse_frequency),
    "resonance frequency, fs":     ("fs_hz",                  parse_frequency),
    "re":                          ("re_ohm",                 parse_impedance),
    "dc resistance, re":           ("re_ohm",                 parse_impedance),
    "qms":                         ("qms",                    parse_float),
    "qes":                         ("qes",                    parse_float),
    "qts":                         ("qts",                    parse_float),
    "vas":                         ("vas_liters",             parse_liters),
    "sd":                          ("sd_cm2",                 parse_sd_cm2),
    "xmax":                        ("xmax_mm",                parse_length_mm),
    "mms":                         ("mms_g",                  parse_mass_g),
    "cms":                         ("cms_mm_per_n",           parse_compliance_mm_per_n),
    "rms":                         ("rms_ns_per_m",           parse_float),
    "le":                          ("le_mh",                  parse_le_mh),   # "Le (at 1kHz)"→"le"
    "bl":                          ("bl_tm",                  parse_bl_tm),
    "bi":                          ("bl_tm",                  parse_bl_tm),   # Celestion typo
    # electrical / commercial
    "nominal diameter":            ("nominal_size_mm",        parse_length_mm),
    "rated impedance":             ("impedance_nominal_ohm",  parse_impedance),
    "power rating":                ("power_aes_watts",        parse_power),
    "continuous power rating":     ("power_long_term_watts",  parse_power),
    "eia power rating":            ("power_eia_watts",        parse_power),
    "sensitivity":                 ("sensitivity_db_1w_1m",   parse_float),
    "frequency range":             ("__freq_range__",         parse_range),
    # Coax pages label this "Recommended min. crossover 12dB/oct" (slope info
    # is baked into the label); normalize_label doesn't strip it, so match the
    # full string.
    "recommended min. crossover 12db/oct": ("recommended_crossover_hz", parse_frequency),
    # physical
    "magnet type":                 ("magnet_type",            lambda s: normalize_magnet_type(s)),
    "voice coil diameter":         ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter":            ("overall_diameter_mm",    parse_length_mm),
    "overall depth":               ("depth_mm",               parse_length_mm),
    "cut-out diameter":            ("mounting_diameter_mm",   parse_length_mm),
    "unit weight":                 ("net_weight_kg",          _weight_kg),
}


def _kind_from_breadcrumb(text: str) -> DriverKind:
    """Derive DriverKind from Celestion breadcrumb text
    ('Home / Guitar & Bass Speakers / Guitar Speakers / TF1525' etc.)."""
    t = text.lower()
    if "guitar" in t or "bass" in t:
        return DriverKind.GUITAR_BASS
    if "compression" in t:
        return DriverKind.HF_COMPRESSION
    if "tweeter" in t:
        return DriverKind.TWEETER
    if "coaxial" in t or "coax" in t:
        return DriverKind.COAX
    if "waveguide" in t or "horn" in t:
        return DriverKind.HORN
    if "hf driver" in t:
        return DriverKind.HF_COMPRESSION
    return DriverKind.LF_WOOFER


def _model_from_page(soup: BeautifulSoup, url: str) -> Optional[str]:
    """Prefer <h1> text; fall back to the URL slug uppercased."""
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(strip=True)
        if text:
            return text
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.upper() if slug else None


@register
class CelestionScraper(Scraper):
    name = "celestion"
    manufacturer_display = "Celestion"
    schema_version = "1.0"
    expected_min_records = 180   # sitemap has 213; some guitar drivers drop for missing model/etc.
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_SITEMAP_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            body = art.body.decode("utf-8", errors="ignore")
            for loc in _LOC_RE.findall(body):
                url = loc.strip()
                if not _PRODUCT_URL_RE.match(url):
                    continue
                key = url.lower().rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                # Kind is unknown at enumeration time — classified from breadcrumb
                # in parse_artifact. Leave driver_kind_hint=None.
                products.append(SeedRef(url=url, context=SeedContext()))
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        # Extract specs
        specs: dict[str, str] = {}
        for row in soup.select("div.product-detail-spec-col-line"):
            children = row.find_all("div", recursive=False)
            if len(children) < 2:
                continue
            label = children[0].get_text(strip=True)
            value = children[1].get_text(strip=True)
            if not label or not value:
                continue
            key = normalize_label(label)
            if key not in specs:
                specs[key] = value

        # DriverKind from breadcrumb
        breadcrumb_text = ""
        for el in soup.find_all(class_=lambda c: c and "breadcrumb" in c.lower()):
            t = el.get_text(" ", strip=True)
            if t and len(t) > len(breadcrumb_text):
                breadcrumb_text = t
                break
        kind = _kind_from_breadcrumb(breadcrumb_text) if breadcrumb_text else DriverKind.LF_WOOFER

        model = _model_from_page(soup, raw.url)
        if not model:
            return ParseResult(fragments=[])

        # URL slug is a stable identity seed if impedance is unparseable
        slug = raw.url.rstrip("/").rsplit("/", 1)[-1]

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=model,
            canonical_id_seed=slug,
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

        return ParseResult(fragments=[frag])
