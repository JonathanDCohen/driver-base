"""Monacor (monacor.com) scraper.

Enumeration: 9 English category pages under `/products/components/
speaker-technology/`, each with `?page=N` pagination (12 products/page). No
sitemap. The site silently re-serves page 1 when N is past the end, so the
orchestrator's compare-across-rounds "no new URLs → stop" applies (same as
Dayton). Product URLs are relative (`href="products/..."`); we normalize
against `_BASE`.

Explicitly excluded at enumeration:
 - The `celestion-pro-audio-` category — Monacor resells Celestion drivers
   with Celestion's own T/S values, so the `celestion` scraper is authoritative.
 - `cdx1-*`, `cdx14-*`, `cdx20-*`, `axi*` slugs inside the tweeters-and-horn-
   drivers category — same Celestion-resell trap under Monacor SKUs.
 - `speaker-building-concepts-` — kits, not drivers.

Extraction: `<tr class="spec">` rows, one per label. `td.spec-name` holds the
label; `td.spec-value` holds the value. Some labels have interior spaces
(`Linear excursion (X MAX )`, `Rec. crossov. frequ. (fmax.) (12 dB/oct.)`) —
`normalize_label` from labels.py handles whitespace collapse and paren strip.

Sensitivity slot: 1W/1m. Monacor unambiguously publishes `SPL` in `dB/W/m`.

Model: the H1 (e.g. `CF1025C/8`) carries the slash-impedance suffix. We strip
`/N` before storing so the canonical impedance-per-variant scheme kicks in
(`monacor__cf1025c__8ohm` vs `__4ohm`).
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

_BASE = "https://www.monacor.com"

# The trailing hyphen on every category slug is REAL and required — dropping
# it 404s. Do not `.rstrip('-')` at any point.
_CATEGORIES: list[tuple[str, DriverKind]] = [
    ("pa-bass-speakers-", DriverKind.LF_WOOFER),
    ("pa-midrange-speakers-", DriverKind.FULLRANGE),
    # Mostly HF compression; a few dome/piezo tweeters slip in. Default to
    # HF_COMPRESSION — the T/S-populated-rate exemption for that kind covers
    # the pattern of "no T/S published" that both share.
    ("pa-tweeters-and-horn-drivers-", DriverKind.HF_COMPRESSION),
    ("pa-coaxial-speakers-and-full-range-speakers-", DriverKind.COAX),
    ("hi-fi-speakers-", DriverKind.LF_WOOFER),
    ("hi-fi-midrange-speakers-", DriverKind.FULLRANGE),
    ("hi-fi-tweeters-", DriverKind.TWEETER),
    ("hi-fi-full-range-speakers-", DriverKind.FULLRANGE),
    ("miniature-speakers-", DriverKind.FULLRANGE),
]

_CATEGORY_PATH_PREFIX = "/products/components/speaker-technology/"

# Celestion-resell slug prefixes inside pa-tweeters-and-horn-drivers-. Filtered
# at enumeration so the `celestion` scraper stays authoritative.
_CELESTION_RESELL_PREFIXES: tuple[str, ...] = ("cdx1", "cdx14", "cdx20", "axi")

# Product URL extraction from listing HTML. Href is relative (no leading `/`).
# Guard against `?o=asc` / `?page=N` sort links by requiring an alphanumeric
# slug segment (no `?`, no `=`).
_PRODUCT_URL_RE = re.compile(
    r'href="(products/components/speaker-technology/'
    r"([a-z0-9-]+)/([a-z0-9-]+))/"
    r'"'
)


def _model_from_h1(h1_text: str) -> Optional[str]:
    """Strip the `/N` impedance suffix. 'CF1025C/8' → 'CF1025C'."""
    if not h1_text:
        return None
    return h1_text.split("/", 1)[0].strip() or None


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


def _strip_diameter_sigil(s: Optional[str]) -> Optional[float]:
    """`Ø 64 mm` / `Ø\xa076 mm` → 64.0. Also handles `dep. on horn` → None
    via parse_length_mm's number-search fallback returning None."""
    if s is None:
        return None
    if "dep." in s.lower():  # 'dep. on horn'
        return None
    return parse_length_mm(s)


# `Type of speaker` = '10"' / '2"' / '28 mm' / '1"' — imperial or metric.
def _type_to_nominal_mm(s: Optional[str]) -> Optional[float]:
    return parse_length_mm(s)


_LABEL_MAP: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    # Electrical / commercial
    "impedance": ("impedance_nominal_ohm", parse_impedance),
    "power rating (rms)": ("power_aes_watts", parse_power),
    "peak music power output (max)": ("power_peak_watts", parse_power),
    "spl": ("sensitivity_db_1w_1m", parse_float),
    "frequency range": ("__freq_range__", parse_range),
    "rec. crossov. frequ.": ("recommended_crossover_hz", parse_frequency),
    # T/S
    "resonant frequency": ("fs_hz", parse_frequency),
    "total q factor": ("qts", parse_float),
    "electr. q factor": ("qes", parse_float),
    "mech. q factor": ("qms", parse_float),
    "equivalent volume": ("vas_liters", parse_liters),
    "dc resistance": ("re_ohm", parse_impedance),
    "voice coil induct.": ("le_mh", parse_le_mh),
    "suspension compl.": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "moving mass": ("mms_g", parse_mass_g),
    # `Force factor (BxL)` — parens stripped by normalize_label → 'force factor'
    "force factor": ("bl_tm", parse_bl_tm),
    # `Linear excursion (X MAX )` — 'MAX' is a measurement-context token
    # preserved by normalize_label as '(max)'.
    "linear excursion (max)": ("xmax_mm", parse_length_mm),
    "eff. cone area": ("sd_cm2", parse_sd_cm2),
    # Physical
    "voice coil diameter": ("voice_coil_diameter_mm", _strip_diameter_sigil),
    "voice coil material": ("winding_material", lambda s: s or None),
    "voice coil former": ("former_material", lambda s: s or None),
    "mounting cutout": ("mounting_diameter_mm", _strip_diameter_sigil),
    "depth": ("depth_mm", parse_length_mm),
    "net weight": ("net_weight_kg", _weight_kg),
    "type of speaker": ("nominal_size_mm", _type_to_nominal_mm),
}


@register
class MonacorScraper(Scraper):
    name = "monacor"
    manufacturer_display = "Monacor"
    schema_version = "1.0"
    expected_min_records = 210  # recon: ~240 Monacor-authored records
    max_seed_rounds = 8  # ~12 products/page × up to ~5 pages per category

    def discover_seeds(self) -> list[SeedRef]:
        # Trailing slash on the URL matters: `.../pa-bass-speakers-` (no slash)
        # 200s in the browser but the `art.url` category regex below only
        # matches with a trailing separator.
        return [
            SeedRef(
                url=f"{_BASE}{_CATEGORY_PATH_PREFIX}{slug}/",
                context=SeedContext(driver_kind_hint=kind, category_id=slug),
            )
            for slug, kind in _CATEGORIES
        ]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        followup_seeds: list[SeedRef] = []
        seen: set[str] = set()
        seen_seed: set[str] = set()
        for art in seed_artifacts:
            # Recover the seed's category slug from its URL. Tolerate both
            # trailing-slash and no-slash forms (httpx doesn't preserve a
            # trailing slash on all servers).
            m = re.search(
                rf"{re.escape(_CATEGORY_PATH_PREFIX)}([a-z0-9-]+?-)(?:/|\?|$)",
                art.url,
            )
            if not m:
                continue
            cat_slug = m.group(1)
            seed_kind = next((k for c, k in _CATEGORIES if c == cat_slug), None)
            if seed_kind is None:
                continue

            body = art.body.decode("utf-8", errors="ignore")
            new_this_seed = 0
            for pm in _PRODUCT_URL_RE.finditer(body):
                # relative_path, cat, slug = pm.group(1), pm.group(2), pm.group(3)
                if pm.group(2) != cat_slug:
                    continue
                slug = pm.group(3).lower()
                if cat_slug == "pa-tweeters-and-horn-drivers-" and any(
                    slug.startswith(p) for p in _CELESTION_RESELL_PREFIXES
                ):
                    continue
                url = f"{_BASE}/{pm.group(1)}/"
                if url in seen:
                    continue
                seen.add(url)
                new_this_seed += 1
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(
                            driver_kind_hint=seed_kind, category_id=cat_slug
                        ),
                    )
                )

            # If this seed page yielded any new products, request its next
            # page. Silent wrap detection: if the next page yields zero new
            # URLs, this branch simply doesn't add another followup.
            if new_this_seed > 0:
                # Extract current page number from art.url; default 1.
                page_m = re.search(r"[?&]page=(\d+)", art.url)
                current = int(page_m.group(1)) if page_m else 1
                next_url = (
                    f"{_BASE}{_CATEGORY_PATH_PREFIX}{cat_slug}/?page={current + 1}"
                )
                if next_url not in seen_seed:
                    seen_seed.add(next_url)
                    followup_seeds.append(
                        SeedRef(
                            url=next_url,
                            context=SeedContext(
                                driver_kind_hint=seed_kind, category_id=cat_slug
                            ),
                        )
                    )

        return EnumerateResult(
            product_urls=products, additional_seed_urls=followup_seeds
        )

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        specs: dict[str, str] = {}
        for tr in soup.select("tr.spec"):
            n = tr.select_one("td.spec-name")
            v = tr.select_one("td.spec-value")
            if not n or not v:
                continue
            label = n.get_text(" ", strip=True)
            value = v.get_text(" ", strip=True)
            if not label or not value:
                continue
            key = normalize_label(label)
            if key not in specs:
                specs[key] = value

        h1 = soup.select_one("h1")
        model = _model_from_h1(h1.get_text(strip=True) if h1 else "")
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
