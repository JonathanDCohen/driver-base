"""Faital Pro (faitalpro.com) scraper.

Enumeration: parse `faitalpro-sitemap.xml`, filter to English product-detail
URLs `/en/products/{CATEGORY}/product_details/index.php?id={ID}`. Yields
18 active English products; archived_products/ paths are excluded at
enumerate (v1 scope: active only). Category slug → DriverKind directly.

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


_BASE = "https://www.faitalpro.com"
_SITEMAP_URL = f"{_BASE}/faitalpro-sitemap.xml"

# The Faital sitemap has lowercase category paths; the live server redirects
# `www.faitalpro.com` → `faitalpro.com` (without www), and the redirect
# target requires MIXED-case category paths — lowercase 404s. Rewrite before
# yielding product URLs from enumerate.
_CATEGORY_TO_KIND: dict[str, DriverKind] = {
    "lf_loudspeakers":      DriverKind.LF_WOOFER,
    "hf_drivers":           DriverKind.HF_COMPRESSION,
    "coaxial_loudspeakers": DriverKind.COAX,
    "hf_horns":             DriverKind.HORN,
}
_CATEGORY_MIXED_CASE: dict[str, str] = {
    "lf_loudspeakers":      "LF_Loudspeakers",
    "hf_drivers":           "HF_Drivers",
    "coaxial_loudspeakers": "Coaxial_Loudspeakers",
    "hf_horns":             "HF_Horns",
}

_PRODUCT_URL_RE = re.compile(
    r"https?://www\.faitalpro\.com/en/products/(?P<category>[^/]+)/product_details/index\.php\?id=(?P<id>\d+)",
    re.IGNORECASE,
)
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)

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
    expected_min_records = 15    # recon: 18 active English URLs
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_SITEMAP_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            body = art.body.decode("utf-8", errors="ignore")
            for loc in _LOC_RE.findall(body):
                m = _PRODUCT_URL_RE.match(loc.strip())
                if not m:
                    continue
                category = m.group("category").lower()
                # v1 excludes archived_products
                if category == "archived_products":
                    continue
                kind = _CATEGORY_TO_KIND.get(category)
                if kind is None:
                    continue
                # Rewrite the lowercase category path to mixed-case so the
                # `faitalpro.com` (no-www) redirect target returns 200, not 404.
                mixed = _CATEGORY_MIXED_CASE.get(category, category)
                rewritten = loc.replace(f"/en/products/{category}/", f"/en/products/{mixed}/")
                if rewritten in seen:
                    continue
                seen.add(rewritten)
                products.append(
                    SeedRef(
                        url=rewritten,
                        context=SeedContext(driver_kind_hint=kind, category_id=category),
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
