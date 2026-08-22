"""Jensen Loudspeakers (jensentone.com) scraper.

Jensen is exclusively guitar / bass amp speakers — every product maps to
`DriverKind.GUITAR_BASS` (T/S-optional per the framework's kind-conditional
consistency gates).

Enumeration: single `sitemap.xml` seed; filter to `/`-tail URLs under one of
the 7 known category slugs (vintage-alnico, vintage-ceramic, vintage-neo,
jet-series, mod-series, d-series, bass-speakers).

Extraction: `div.jensentone-ohm-specs` container holds four `<table>`s, each
with a `<caption>` naming its section:
    General Characteristics       physical / weights (metric | imperial)
    Thiele-Small Parameters       T/S (label | symbol | value_imp0 [| value_imp1 …])
    Constructive Characteristics  materials (label | empty | value)
    Electrical Characteristics    power / sensitivity (per-impedance columns)

Multi-impedance: many Jensen products come in both 8 Ω and 16 Ω from one URL.
The "Nominal Impedance" header row in the T/S or Electrical table lists the
impedances; we emit one `DriverFragment` per column, so the canonical_id
scheme (`jensen__{model}__{N}ohm`) records both. Rows with only one value
apply that value to every impedance fragment.
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
    parse_sd_cm2,
)


_BASE = "https://www.jensentone.com"
_SITEMAP_URL = f"{_BASE}/sitemap.xml"

_CATEGORIES = (
    "vintage-alnico",
    "vintage-ceramic",
    "vintage-neo",
    "jet-series",
    "mod-series",
    "d-series",
    "bass-speakers",
)

_LOC_RE = re.compile(r"<loc>([^<]+)</loc>", re.IGNORECASE)
_PRODUCT_URL_RE = re.compile(
    r"^https?://www\.jensentone\.com/(?:" + "|".join(re.escape(c) for c in _CATEGORIES) + r")/[a-z0-9-]+/?$",
    re.IGNORECASE,
)


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


# Label → (Driver field, parser). Every Jensen label lands in exactly one
# canonical field; missing labels are simply skipped.
_LABEL_MAP: dict[str, tuple[str, Callable[[Optional[str]], Any]]] = {
    # General Characteristics — read the metric column (index 1)
    "nominal overall diameter":        ("nominal_size_mm",        parse_length_mm),
    "nominal voice coil diameter":     ("voice_coil_diameter_mm", parse_length_mm),
    "overall weight":                  ("net_weight_kg",          _weight_kg),
    # Thiele-Small
    "voice coil dc resistance":        ("re_ohm",                 parse_impedance),
    "resonance frequency":             ("fs_hz",                  parse_frequency),
    "mechanical q factor":             ("qms",                    parse_float),
    "electrical q factor":             ("qes",                    parse_float),
    "total q factor":                  ("qts",                    parse_float),
    "mechanical moving mass":          ("mms_g",                  parse_mass_g),
    "mechanical compliance":           ("cms_mm_per_n",           parse_compliance_mm_per_n),
    "force factor":                    ("bl_tm",                  parse_bl_tm),
    "equivalent acoustic volume":      ("vas_liters",             parse_liters),
    "maximum linear displacement":     ("xmax_mm",                parse_length_mm),
    "reference efficiency":            ("eta_zero_pct",           parse_float),
    "diaphragm area":                  ("sd_cm2",                 parse_sd_cm2),
    "voice coil inductance @ 1khz":    ("le_mh",                  parse_le_mh),
    # Constructive
    "magnet":                          ("magnet_type",            lambda s: normalize_magnet_type(s)),
    # Electrical
    "rated power":                     ("power_aes_watts",        parse_power),
    "musical power":                   ("power_peak_watts",       parse_power),
    "sensitivity@1w,1m":               ("sensitivity_db_1w_1m",   parse_float),
}


def _row_cells(tr) -> list:
    return tr.find_all(["td", "th"])


def _extract_impedances(tables) -> list[float]:
    """Return the ordered impedance list (e.g. [8.0, 16.0]) from the first
    'Nominal Impedance' row found across the tables. Empty list if none."""
    for tbl in tables:
        for tr in tbl.find_all("tr"):
            cells = _row_cells(tr)
            if len(cells) < 2:
                continue
            label = cells[0].get_text(strip=True).lower()
            if "nominal impedance" in label:
                out: list[float] = []
                # Values start at index 2 (skip label + empty/symbol column)
                for c in cells[2:]:
                    txt = c.get_text(strip=True)
                    v = parse_impedance(txt)
                    if v is not None and v > 0:
                        out.append(v)
                if out:
                    return out
    return []


def _general_metric_value(cells) -> Optional[str]:
    """General Characteristics rows are `label | metric | imperial` — take
    cell[1] (metric)."""
    if len(cells) >= 2:
        return cells[1].get_text(strip=True) or None
    return None


def _material_value(cells) -> Optional[str]:
    """Constructive Characteristics rows are `label | empty | value` — take
    the last non-empty cell."""
    for c in reversed(cells[1:]):
        t = c.get_text(strip=True)
        if t:
            return t
    return None


def _per_impedance_value(cells, imp_idx: int, n_impedances: int) -> Optional[str]:
    """Impedance-split rows are `label | symbol_or_empty | v_imp0 | v_imp1 …`.
    Prefer the imp_idx-th value column; fall back to a single shared value."""
    values = [c.get_text(strip=True) for c in cells[2:]]
    values = [v for v in values if v != ""]
    if not values:
        return None
    if imp_idx < len(values):
        return values[imp_idx]
    return values[0]   # single-value row → apply to every impedance fragment


def _caption_key(table) -> str:
    cap = table.find("caption")
    return (cap.get_text(" ", strip=True).lower() if cap else "")


def _model_from_page(soup: BeautifulSoup, url: str) -> Optional[str]:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return t
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.upper() if slug else None


@register
class JensenScraper(Scraper):
    name = "jensen"
    manufacturer_display = "Jensen"
    schema_version = "1.0"
    expected_min_records = 55    # 63 product URLs; some emit 2 fragments (8+16Ω); some emit 1
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
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(driver_kind_hint=DriverKind.GUITAR_BASS),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")
        container = soup.find(
            "div", class_=lambda c: c and "jensentone-ohm-specs" in c
        )
        if container is None:
            return ParseResult(fragments=[])

        tables = container.find_all("table")
        if not tables:
            return ParseResult(fragments=[])

        model = _model_from_page(soup, raw.url)
        if not model:
            return ParseResult(fragments=[])

        impedances = _extract_impedances(tables) or [None]

        fragments: list[DriverFragment] = []
        slug = raw.url.rstrip("/").rsplit("/", 1)[-1]

        for imp_idx, impedance in enumerate(impedances):
            frag = DriverFragment(
                manufacturer=self.manufacturer_display,
                source_url=raw.url,
                fetched_at=raw.fetched_at,
                driver_kind=seed_context.driver_kind_hint or DriverKind.GUITAR_BASS,
                model=model,
                canonical_id_seed=slug,
            )
            frag.impedance_nominal_ohm = impedance

            for tbl in tables:
                cap = _caption_key(tbl)
                for tr in tbl.find_all("tr"):
                    cells = _row_cells(tr)
                    if len(cells) < 2:
                        continue
                    label = cells[0].get_text(strip=True)
                    if not label:
                        continue
                    key = normalize_label(label)
                    mapping = _LABEL_MAP.get(key)
                    if mapping is None:
                        continue
                    field_name, parser = mapping

                    if "general" in cap:
                        raw_val = _general_metric_value(cells)
                    elif "constructive" in cap:
                        raw_val = _material_value(cells)
                    else:
                        # Thiele-Small / Electrical / anything with per-impedance columns
                        raw_val = _per_impedance_value(cells, imp_idx, len(impedances))

                    if not raw_val:
                        continue
                    parsed = parser(raw_val) if parser else raw_val
                    if parsed is None:
                        continue
                    setattr(frag, field_name, parsed)
                    frag.spec_source[field_name] = SpecSource.HTML_TABLE

            fragments.append(frag)

        return ParseResult(fragments=fragments)
