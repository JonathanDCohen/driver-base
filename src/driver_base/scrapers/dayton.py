"""Dayton Audio (daytonaudio.com) scraper.

Enumeration: crawl each of 12 loudspeaker-driver subcategories with pagination.
Category URL: /category/{id}/{slug}?pagenum={N}. Products come 20 per page.
Silent pagination wrap (page past end returns page 1 again) is handled by the
orchestrator's cross-round dedup — if a page yields no NEW product URLs, the
loop breaks.

Extraction: single spec table under `#collapseTwo table.table`. Each row is
`<tr><td>label</td><td>value</td></tr>`. The identity `Model Number` field is
also in this table.

Sensitivity is labelled `@ 2.83V/1m` (Dayton convention), so it lands in the
`sensitivity_db_2_83v_1m` slot, NOT `sensitivity_db_1w_1m`.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

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
    parse_impedance,
    parse_le_mh,
    parse_length_mm,
    parse_liters,
    parse_mass_g,
    parse_power,
    parse_range,
    parse_sd_cm2,
)


_BASE = "https://www.daytonaudio.com"

# subcategory id → (slug, DriverKind). Slug matches URL text; is stored but not
# functionally required for enumeration (id alone is enough).
_CATEGORIES: list[tuple[int, str, DriverKind]] = [
    (118, "woofers",             DriverKind.LF_WOOFER),
    (121, "subwoofers",          DriverKind.LF_WOOFER),
    (119, "tweeters",            DriverKind.TWEETER),
    (120, "midranges",           DriverKind.FULLRANGE),
    (123, "full-range",          DriverKind.FULLRANGE),
    (161, "pro-audio-drivers",   DriverKind.LF_WOOFER),
    (125, "passive-radiators",   DriverKind.PASSIVE),
    (178, "mini-micro-speakers", DriverKind.FULLRANGE),
    (272, "compression-drivers", DriverKind.HF_COMPRESSION),
    (96,  "horns-waveguides",    DriverKind.HORN),
    (274, "planar-ribbon",       DriverKind.TWEETER),
    # 126 (replacement-diaphragms) intentionally excluded — not a driver.
]
_CAT_KIND: dict[int, DriverKind] = {cid: kind for cid, _, kind in _CATEGORIES}

_PRODUCT_URL_RE = re.compile(r"^/product/(\d+)/[^?#/]+", re.IGNORECASE)
_CATEGORY_URL_RE = re.compile(r"^/category/(\d+)(?:/[^?#]*)?", re.IGNORECASE)


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]] = {
    "model number":                                                  ("__model__", None),
    "resonant frequency":                                             ("fs_hz", parse_float),
    "dc resistance":                                                  ("re_ohm", parse_impedance),
    "voice coil inductance":                                          ("le_mh", parse_le_mh),
    "mechanical q":                                                   ("qms", parse_float),
    "electromagnetic q":                                              ("qes", parse_float),
    "total q":                                                        ("qts", parse_float),
    "compliance equivalent volume":                                   ("vas_liters", parse_liters),
    "mechanical compliance of suspension":                            ("cms_mm_per_n", parse_compliance_mm_per_n),
    "surface area of cone":                                           ("sd_cm2", parse_sd_cm2),
    "bl product":                                                     ("bl_tm", parse_bl_tm),
    "diaphragm mass inc. airload":                                    ("mms_g", parse_mass_g),
    "maximum linear excursion":                                       ("xmax_mm", parse_length_mm),
    "impedance":                                                      ("impedance_nominal_ohm", parse_impedance),
    "sensitivity":                                                    ("sensitivity_db_2_83v_1m", parse_float),
    "power handling (rms)":                                           ("power_aes_watts", parse_power),
    "power handling (max)":                                           ("power_peak_watts", parse_power),
    "power handling":                                                 ("power_aes_watts", parse_power),  # fallback
    "frequency response":                                             ("__freq_range__", parse_range),
    "nominal diameter":                                               ("nominal_size_mm", parse_length_mm),
    "voice coil diameter":                                            ("voice_coil_diameter_mm", parse_length_mm),
    "overall outside diameter":                                       ("overall_diameter_mm", parse_length_mm),
    "overall depth":                                                  ("depth_mm", parse_length_mm),
    "baffle cutout diameter":                                         ("mounting_diameter_mm", parse_length_mm),
    "weight":                                                         ("net_weight_kg", _weight_kg),
    "magnet material":                                                ("magnet_type", lambda s: normalize_magnet_type(s)),
}


def _cat_slug_for_id(cid: int) -> str:
    for c, slug, _ in _CATEGORIES:
        if c == cid:
            return slug
    return str(cid)


def _cat_page_url(cid: int, page: int) -> str:
    slug = _cat_slug_for_id(cid)
    return f"{_BASE}/category/{cid}/{slug}?pagenum={page}"


def _parse_seed_url(url: str) -> tuple[Optional[int], int]:
    parsed = urlparse(url)
    m = _CATEGORY_URL_RE.match(parsed.path)
    cid = int(m.group(1)) if m else None
    qs = parse_qs(parsed.query)
    page_raw = qs.get("pagenum", ["1"])[0]
    try:
        page = int(page_raw)
    except ValueError:
        page = 1
    return cid, page


@register
class DaytonScraper(Scraper):
    name = "dayton"
    manufacturer_display = "Dayton Audio"
    schema_version = "1.0"
    expected_min_records = 250     # recon estimated ~370; go conservative
    max_seed_rounds = 8            # 20/page × ≤80 = 1600 (bounded well above catalog size)

    def discover_seeds(self) -> list[SeedRef]:
        return [
            SeedRef(url=_cat_page_url(cid, 1), context=SeedContext(driver_kind_hint=kind, category_id=slug))
            for cid, slug, kind in _CATEGORIES
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        additional: list[SeedRef] = []
        for art in seed_artifacts:
            cid, pagenum = _parse_seed_url(art.url)
            if cid is None:
                continue
            kind = _CAT_KIND.get(cid)
            slug = _cat_slug_for_id(cid)

            soup = BeautifulSoup(art.body, "lxml")
            page_urls: set[str] = set()
            for a in soup.find_all("a", href=True):
                m = _PRODUCT_URL_RE.match(a["href"])
                if m:
                    page_urls.add(a["href"].split("?")[0].split("#")[0])
            for rel in page_urls:
                products.append(
                    SeedRef(
                        url=f"{_BASE}{rel}",
                        context=SeedContext(driver_kind_hint=kind, category_id=slug),
                    )
                )
            # Pagination: if the page looks full (Dayton serves 20/page), request N+1.
            # Orchestrator dedup on product URLs stops us when the site wraps.
            if len(page_urls) >= 18:
                additional.append(
                    SeedRef(
                        url=_cat_page_url(cid, pagenum + 1),
                        context=SeedContext(driver_kind_hint=kind, category_id=slug),
                    )
                )
        return EnumerateResult(product_urls=products, additional_seed_urls=additional)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")
        table = soup.select_one("#collapseTwo table.table")
        if table is None:
            return ParseResult(fragments=[])

        specs: dict[str, str] = {}
        for tr in table.select("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if not label or value in ("", "--"):
                continue
            key = normalize_label(label)
            # first-wins on duplicate label
            if key not in specs:
                specs[key] = value

        model = specs.pop("model number", None)
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
            if field_name == "__model__":
                continue  # already consumed
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

        # Dayton's AMT tweeters are shelved under `tweeter` category with an
        # `AMT…` model prefix (AMT3-4, AMTPRO-4, AMT Mini-8, etc.). Capture the
        # AMT topology as diaphragm_shape so users can find them without a
        # separate driver_kind.
        if frag.model and frag.model.upper().startswith("AMT"):
            frag.diaphragm_shape = "AMT"
            frag.spec_source["diaphragm_shape"] = SpecSource.INFERRED

        return ParseResult(fragments=[frag])
