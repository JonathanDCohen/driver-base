"""Faital Pro (faitalpro.com) scraper.

Enumeration: seed each of the four category listing pages. The two large
categories (LF_Loudspeakers, HF_Drivers) render their product tables via
XHR — the browser POSTs to `<category>/search.php` with the default filter
and injects the response into `#main_content`. We POST directly instead of
running JS. The two small categories (Coaxial_Loudspeakers, HF_Horns) ship
their tables inline in the listing HTML. Either way, enumerate scrapes
`product_details/index.php?id=<N>` occurrences from the response body and
tags each product with the DriverKind derived from the seed URL.

The sitemap is NOT used — it lists only a handful of the ~158 active
English products.

Extraction: `table.tbl_data tr` label/value pairs. The spec data appears in
6 tables per page (mobile + desktop layouts); the parser deduplicates by
label, first occurrence wins. Footnote suffixes ('AES Power Handling(1)',
'Xmax(4)') are stripped by `normalize_label`.

Frequency range uses `÷` as the separator ('45÷5000 Hz') — `parse_range`
handles it.

Model: extracted from the `<title>` tag pattern
    'FaitalPRO | {Category} | {MODEL} ({impedance})'
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


_BASE = "https://faitalpro.com"

# Use the no-www hostname directly. `www.faitalpro.com` 301-redirects to
# `faitalpro.com`, and httpx drops POST bodies on 301 (RFC-compliant), which
# breaks the search.php seeds. Category paths are mixed-case — lowercase 404s.
# Kind is set from the seed URL in enumerate().
_CATEGORY_TO_KIND: dict[str, DriverKind] = {
    "LF_Loudspeakers":      DriverKind.LF_WOOFER,
    "HF_Drivers":           DriverKind.HF_COMPRESSION,
    "Coaxial_Loudspeakers": DriverKind.COAX,
    "HF_Horns":             DriverKind.HORN,
}

# Default filter payloads copied verbatim from each listing page's
# `update_data()` JS. Wide-open ranges — matches "show me everything".
# LF_Loudspeakers/search.php filter:
_LF_SEARCH_POST: tuple[tuple[str, str], ...] = (
    ("neodymium", "10"), ("ferrite", "20"),
    ("size", "All"),
    ("powermin", "20"), ("powermax", "3000"),
    ("vcmin", "15"), ("vcmax", "170"),
    ("fsmin", "20"), ("fsmax", "180"),
    ("demod", "1"), ("nodemod", "1"),
)
# HF_Drivers/search.php filter:
_HF_SEARCH_POST: tuple[tuple[str, str], ...] = (
    ("neodymium", "10"), ("ferrite", "20"),
    ("size", "All"),
    ("powermin", "30"), ("powermax", "120"),
    ("vcdiam", "All"),
    ("crossfreqmin", "0.4"), ("crossfreqmax", "2.6"),
    ("demod", "1"), ("nodemod", "1"),
    ("dshape1", "Dome"), ("dshape2", "Annular"), ("dshape3", "Double Edge Cone"),
    ("dmaterial1", "Titanium"), ("dmaterial2", "Ketone Polymer"),
    ("dmaterial3", "Paper"), ("dmaterial4", "Carbon Fiber"),
    ("plugdesign1", "Annular"), ("plugdesign2", "Radial"),
)

# Match the URL segment naming the category, in either a seed URL
# (`.../en/products/LF_Loudspeakers/search.php` or `.../en/products/HF_Horns/`)
# or a discovered product URL.
_SEED_CATEGORY_RE = re.compile(
    r"/en/products/(?P<category>LF_Loudspeakers|HF_Drivers|Coaxial_Loudspeakers|HF_Horns)/"
)
# `product_details/index.php?id=101050135` — id is the only capture we need;
# category comes from the seed URL that yielded this body. search.php responses
# JSON-escape the slash as `product_details\/index.php` — optional backslash.
_PRODUCT_ID_RE = re.compile(r"product_details\\?/index\.php\?id=(\d+)")

# `FaitalPRO | LF Loudspeakers | 12PR320 (8Ω)` → group(1) = '12PR320'
_TITLE_MODEL_RE = re.compile(r"\|\s*([^|()]+?)\s*(?:\(|$)")


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    # T/S
    "fs":                          ("fs_hz",                  parse_frequency),
    "re":                          ("re_ohm",                 parse_impedance),
    "qes":                         ("qes",                    parse_float),
    "qms":                         ("qms",                    parse_float),
    "qts":                         ("qts",                    parse_float),
    "vas":                         ("vas_liters",             parse_liters),
    "sd":                          ("sd_cm2",                 parse_sd_cm2),
    "xmax":                        ("xmax_mm",                parse_length_mm),
    "xdamage":                     ("xmech_mm",               parse_length_mm),   # Faital pp AS-REPORTED
    "mms":                         ("mms_g",                  parse_mass_g),
    "bl":                          ("bl_tm",                  parse_bl_tm),
    "le":                          ("le_mh",                  parse_le_mh),
    "cms":                         ("cms_mm_per_n",           parse_compliance_mm_per_n),
    "rms":                         ("rms_ns_per_m",           parse_float),       # kg/s ≡ N·s/m
    "eta zero":                    ("eta_zero_pct",           parse_float),
    "ebp":                         ("ebp_hz",                 parse_frequency),
    # electrical / commercial
    "nominal impedance":           ("impedance_nominal_ohm",  parse_impedance),
    "minimum impedance":           ("impedance_min_ohm",      parse_impedance),
    "aes power handling":          ("power_aes_watts",        parse_power),
    "maximum power handling":      ("power_peak_watts",       parse_power),
    "sensitivity (1w/1m)":         ("sensitivity_db_1w_1m",   parse_float),
    "frequency range":             ("__freq_range__",         parse_range),
    # physical
    "nominal diameter":            ("nominal_size_mm",        parse_length_mm),
    "voice coil diameter":         ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter":            ("overall_diameter_mm",    parse_length_mm),
    "baffle cutout diameter":      ("mounting_diameter_mm",   parse_length_mm),
    "depth":                       ("depth_mm",               parse_length_mm),
    "net weight":                  ("net_weight_kg",          _weight_kg),
    "magnet":                      ("magnet_type",            lambda s: normalize_magnet_type(s)),
}


def _model_from_title(title: str) -> Optional[str]:
    """Extract '12PR320' from '`FaitalPRO | LF Loudspeakers | 12PR320 (8Ω)`'."""
    if not title:
        return None
    m = None
    for m in _TITLE_MODEL_RE.finditer(title):
        pass
    return m.group(1).strip() if m else None


@register
class FaitalScraper(Scraper):
    name = "faital"
    manufacturer_display = "Faital Pro"
    schema_version = "1.0"
    expected_min_records = 120   # recon: ~158 active English URLs across 4 categories
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(
                url=f"{_BASE}/en/products/LF_Loudspeakers/search.php",
                context=SeedContext(
                    driver_kind_hint=DriverKind.LF_WOOFER,
                    category_id="LF_Loudspeakers",
                ),
                post_data=_LF_SEARCH_POST,
            ),
            SeedRef(
                url=f"{_BASE}/en/products/HF_Drivers/search.php",
                context=SeedContext(
                    driver_kind_hint=DriverKind.HF_COMPRESSION,
                    category_id="HF_Drivers",
                ),
                post_data=_HF_SEARCH_POST,
            ),
            SeedRef(
                url=f"{_BASE}/en/products/Coaxial_Loudspeakers/",
                context=SeedContext(
                    driver_kind_hint=DriverKind.COAX,
                    category_id="Coaxial_Loudspeakers",
                ),
            ),
            SeedRef(
                url=f"{_BASE}/en/products/HF_Horns/",
                context=SeedContext(
                    driver_kind_hint=DriverKind.HORN,
                    category_id="HF_Horns",
                ),
            ),
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            m = _SEED_CATEGORY_RE.search(art.url)
            if not m:
                continue
            category = m.group("category")
            kind = _CATEGORY_TO_KIND[category]
            body = art.body.decode("utf-8", errors="ignore")
            for pid in _PRODUCT_ID_RE.findall(body):
                product_url = (
                    f"{_BASE}/en/products/{category}"
                    f"/product_details/index.php?id={pid}"
                )
                if product_url in seen:
                    continue
                seen.add(product_url)
                products.append(
                    SeedRef(
                        url=product_url,
                        context=SeedContext(
                            driver_kind_hint=kind, category_id=category
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        specs: dict[str, str] = {}
        for table in soup.select("table.tbl_data"):
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

        title_text = soup.title.get_text(strip=True) if soup.title else ""
        model = _model_from_title(title_text)
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
                frag.spec_source["freq_low_hz"] = SpecSource.HTML_TABLE
                frag.spec_source["freq_high_hz"] = SpecSource.HTML_TABLE
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_TABLE

        return ParseResult(fragments=[frag])
