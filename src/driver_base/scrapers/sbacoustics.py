"""SB Acoustics (sbacoustics.com) scraper.

Enumeration: `product-sitemap.xml` (WordPress All-in-One SEO). Contains every
active `/product/{slug}/` URL — currently ~231 entries. A hard-coded kit-slug
list is subtracted at enumerate time; passive radiators and any other
non-driver categories are dropped at parse time by inspecting the product's
`.posted_in` category list.

Extraction: each product page is a WooCommerce single-product view. The spec
section is one (or, for coax, two) unadorned `<ul>` blocks of `<li>` items;
label and value are concatenated inside each `<li>`, e.g.
    <li>DC resistance, Re 5.7 Ω</li>
We locate the spec `<ul>` by presence of enough "signal" labels (Nominal
Impedance, DC resistance, Free air resonance, Sensitivity, ...), then peel
each `<li>` into (label, value) by regex — the value is the trailing
number-plus-unit token.

DriverKind is derived from the product page's WooCommerce `.posted_in`
category anchors. SB Acoustics has no HF-compression drivers, no horns, and
no guitar/bass — the observed kinds are LF_WOOFER, TWEETER, COAX, FULLRANGE.

Sensitivity slot: **2.83V/1m**. SB explicitly labels every sensitivity row
`Sensitivity (2.83V/1m)` — routing to the 1W/1m slot would silently
mis-report by 3 dB on 4Ω drivers. Same trap as HOQS and B&C.

Xmax: SB reports `Linear coil travel (p-p)` — peak-to-peak. Framework
`xmax_mm` is one-way; the parser halves and tags DERIVED.

Nominal size: not published as a labeled spec. Derived from the URL slug
(`6in-sb17nac35-8` → 6″, `10in-sw26dac76-8` → 10″) and tagged DERIVED.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional
from urllib.parse import unquote

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

_BASE = "https://sbacoustics.com"
_SITEMAP_URL = f"{_BASE}/product-sitemap.xml"

# Kits — assembled speakers, not drivers. Same URL pattern as products, no
# distinguishing slug marker, so hard-list from recon (2026-09-01).
_KIT_SLUGS: set[str] = {
    "raiya-tx",
    "gema",
    "sasandu",
    "sasandu-tx",
    "rinjani",
    "rinjani-be",
    "rinjani-tx",
    "ara",
    "ara-be",
    "ara-tx",
    "arya",
    "micro",
    "micro-c",
    "kinnara",
    "tifa-6",
    "tifa-8",
    "bromo",
    "eka",
}

# Categories that mean "not a driver we want" — checked case-insensitively
# against each `.posted_in` anchor's text.
_SKIP_CATEGORY_MARKERS: tuple[str, ...] = (
    "passive radiator",
    "kits",
    "accessories",
)

# Category-text substring → DriverKind. First match wins. `subwoofer` intentionally
# comes before generic `woofer` even though both map to LF_WOOFER; if we ever
# split them apart the ordering matters.
_CATEGORY_TO_KIND: list[tuple[str, DriverKind]] = [
    ("coax", DriverKind.COAX),
    ("tweeter", DriverKind.TWEETER),
    ("widebander", DriverKind.FULLRANGE),
    ("full range", DriverKind.FULLRANGE),
    ("filler driver", DriverKind.FULLRANGE),
    ("subwoofer", DriverKind.LF_WOOFER),
    ("midwoofer", DriverKind.LF_WOOFER),
    ("woofer", DriverKind.LF_WOOFER),
    ("midrange", DriverKind.FULLRANGE),  # no dedicated MIDRANGE kind
]

# Sitemap URL extraction — sbacoustics wraps every <loc> in CDATA.
_SITEMAP_LOC_RE = re.compile(
    r"<loc>\s*(?:<!\[CDATA\[)?\s*(https://sbacoustics\.com/product/[^\]<\s]+/)"
)

# SB `<li>` texts concatenate label and value with no delimiter, and labels
# often contain a parenthetical unit hint (`Linear coil travel (p-p)`,
# `Sensitivity (2.83 V / 1 m)`) with interior spaces and digits. Prefix
# matching against the known-label set beats a value-peel regex, which would
# fail on `Sensitivity (2.83 V / 1 m) 86.5 dB` by treating `1 m) 86.5 dB` as
# the value.

# Missing-space-after-comma normalization: `Moving mass incl. air,Mms 172 g`
# → `Moving mass incl. air, Mms 172 g`. Applied to the lowered text before
# prefix lookup.
_COMMA_SPACE_RE = re.compile(r",\s*")

# Model extraction from the H1 (e.g. '6″ SB17NAC35-8 / Aluminum',
# 'SATORI TW29BN-B-8 / Beryllium', '5″ SB15BAC30-8-COAX/ aluminum').
# Take everything before the first '/', then the last uppercase-alnum token
# with dashes.
_MODEL_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9\-]{2,}")

# Slug size prefix: '6in-...', '10in-...', '6%c2%bd-...', '6½-...', '7½-...'
# — the leading integer (or integer + ½) before 'in' or '-'.
_SLUG_SIZE_RE = re.compile(r"^(?P<num>\d+)(?P<half>½)?(?:in|-)", re.IGNORECASE)


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


def _xmax_from_pp(s: Optional[str]) -> Optional[float]:
    """SB reports peak-to-peak; framework xmax_mm is one-way. Halve."""
    v = parse_length_mm(s)
    return v / 2.0 if v is not None else None


# Label lookup after concatenated `<li>` split. Label side gets `.lower()`
# and whitespace-collapse; no full `normalize_label` because these labels are
# already free-form prose without parentheticals (except Sensitivity, handled
# by prefix match below).
_LABEL_MAP: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    "nominal impedance": ("impedance_nominal_ohm", parse_impedance),
    "dc resistance, re": ("re_ohm", parse_impedance),
    "voice coil inductance, le": ("le_mh", parse_le_mh),
    "effective piston area, sd": ("sd_cm2", parse_sd_cm2),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "linear coil travel": ("xmax_mm", _xmax_from_pp),  # matches '(p-p)' variant too
    "free air resonance, fs": ("fs_hz", parse_frequency),
    "mechanical q-factor, qms": ("qms", parse_float),
    "electrical q-factor, qes": ("qes", parse_float),
    "total q-factor, qts": ("qts", parse_float),
    "moving mass incl. air, mms": ("mms_g", parse_mass_g),
    "force factor, bl": ("bl_tm", parse_bl_tm),
    "equivalent volume, vas": ("vas_liters", parse_liters),
    "compliance, cms": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "mechanical loss, rms": ("rms_ns_per_m", parse_float),  # kg/s ≡ N·s/m
    "rated power handling": ("power_aes_watts", parse_power),
    "net weight": ("net_weight_kg", _weight_kg),
    "magnetic flux density": ("flux_density_t", parse_float),
}

# Coax HF-section — second `<ul>` on coax pages. Fewer fields than LF (SB
# publishes only impedance/Re/VC-geometry/Fs/sensitivity/power for the HF
# section). Sensitivity is 2.83V/1m but the framework's coax_hf slot is
# `coax_hf_sensitivity_db_1w_1m` — leaving unset avoids mis-slotting.
_LABEL_MAP_COAX_HF: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    "nominal impedance": ("coax_hf_impedance_nominal_ohm", parse_impedance),
    "dc resistance, re": ("coax_hf_re_ohm", parse_impedance),
    "voice coil inductance, le": (None, None),
    "voice coil diameter": ("coax_hf_voice_coil_diameter_mm", parse_length_mm),
    "rated power handling": ("coax_hf_power_aes_watts", parse_power),
}


def _model_from_h1(h1_text: str) -> Optional[str]:
    """Extract the model code from the WooCommerce H1.

    Examples:
      '6″ SB17NAC35-8 / Aluminum'        -> 'SB17NAC35-8'
      'SATORI TW29BN-B-8 / Beryllium'    -> 'TW29BN-B-8'
      '5″ SB15BAC30-8-COAX/ aluminum'    -> 'SB15BAC30-8-COAX'
    """
    if not h1_text:
        return None
    head = h1_text.split("/", 1)[0]
    matches = _MODEL_TOKEN_RE.findall(head)
    return matches[-1] if matches else None


def _nominal_size_mm_from_slug(slug: str) -> Optional[float]:
    """Read the size prefix from an SB Acoustics URL slug.

    '6in-sb17nac35-8'   -> 152.4  (6″)
    '10in-sw26dac76-8'  -> 254.0  (10″)
    '6½-satori-mw16pf-8-paper' -> 165.1  (6.5″)
    'satori-tw29bn-b-8' -> None (Satori tweeters carry no size prefix)
    """
    decoded = unquote(slug)
    # Replace URL-encoded ½ (%c2%bd is already un-encoded to ½ above) and ″
    m = _SLUG_SIZE_RE.match(decoded)
    if not m:
        return None
    inches = float(m.group("num"))
    if m.group("half"):
        inches += 0.5
    return inches * 25.4


def _pick_spec_uls(soup: BeautifulSoup) -> list[list[str]]:
    """Return a list of spec-<ul>s (in document order), each as its <li> texts.

    A qualifying <ul> has at least 3 signal labels among its <li>s. Coax
    pages produce two matches (LF then HF); every other product produces one.
    """
    signals = (
        "nominal impedance",
        "dc resistance",
        "free air resonance",
        "sensitivity",
        "force factor",
        "rated power handling",
    )
    out: list[list[str]] = []
    for ul in soup.find_all("ul"):
        items = ul.find_all("li", recursive=False)
        if len(items) < 5:
            continue
        texts = [li.get_text(" ", strip=True) for li in items]
        joined = " | ".join(t.lower() for t in texts)
        hits = sum(1 for s in signals if s in joined)
        if hits >= 3:
            out.append(texts)
    return out


def _split_li(
    text: str,
    known_labels: list[str],
) -> Optional[tuple[str, str]]:
    """Match one known label prefix against the `<li>` text and return
    (label_key, value_str). Normalizes missing-space-after-comma before
    matching. Skips over any parenthetical hint on the label (`Linear coil
    travel (p-p) 11 mm` → value `11 mm`)."""
    normalized = _COMMA_SPACE_RE.sub(", ", text).lower()
    for key in known_labels:  # sorted longest-first by caller
        if not normalized.startswith(key):
            continue
        rest = _COMMA_SPACE_RE.sub(", ", text)[len(key) :].lstrip()
        if rest.startswith("("):
            close = rest.find(")")
            if close == -1:
                return None
            rest = rest[close + 1 :].lstrip()
        return key, rest
    return None


def _classify_from_categories(categories: list[str]) -> Optional[DriverKind]:
    lowered = [c.lower() for c in categories]
    for marker in _SKIP_CATEGORY_MARKERS:
        if any(marker in c for c in lowered):
            return None
    for needle, kind in _CATEGORY_TO_KIND:
        if any(needle in c for c in lowered):
            return kind
    return None


@register
class SBAcousticsScraper(Scraper):
    name = "sbacoustics"
    manufacturer_display = "SB Acoustics"
    schema_version = "1.0"
    expected_min_records = 175  # sitemap ~231; ~18 kits + ~13 passives excluded
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_SITEMAP_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            if "product-sitemap.xml" not in art.url:
                continue
            body = art.body.decode("utf-8", errors="ignore")
            for m in _SITEMAP_LOC_RE.finditer(body):
                url = m.group(1)
                slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
                if slug in _KIT_SLUGS:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                products.append(SeedRef(url=url, context=SeedContext()))
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")

        # Category-driven skip + DriverKind assignment. Every legit product
        # page carries a `.posted_in` block.
        categories = [a.get_text(strip=True) for a in soup.select(".posted_in a")]
        kind = _classify_from_categories(categories)
        if kind is None:
            return ParseResult(fragments=[])

        spec_uls = _pick_spec_uls(soup)
        if not spec_uls:
            return ParseResult(fragments=[])

        h1_el = soup.select_one("h1.product_title, h1.entry-title, h1")
        model = _model_from_h1(h1_el.get_text(strip=True) if h1_el else "")
        if not model:
            return ParseResult(fragments=[])

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=model,
        )

        # Prefix-match keys, longest first. Union LF-section keys + the special
        # `sensitivity` prefix (any casing/spacing of the parenthetical).
        lf_keys = sorted(
            list(_LABEL_MAP.keys()) + ["sensitivity"], key=len, reverse=True
        )

        # LF (or sole) section — first spec <ul>.
        for text in spec_uls[0]:
            split = _split_li(text, lf_keys)
            if split is None:
                continue
            label, value = split
            # Sensitivity: SB always publishes 2.83V/1m regardless of paren
            # formatting (`(2.83 V / 1 m)` vs `(2.83V/1m)`); slot accordingly.
            if label == "sensitivity":
                v = parse_float(value)
                if v is not None:
                    frag.sensitivity_db_2_83v_1m = v
                    frag.spec_source["sensitivity_db_2_83v_1m"] = SpecSource.HTML_PROSE
                continue
            mapping = _LABEL_MAP.get(label)
            if mapping is None or mapping[0] is None:
                continue
            field_name, parser = mapping
            parsed = parser(value) if parser else value
            if parsed is None:
                continue
            setattr(frag, field_name, parsed)
            # xmax is DERIVED from the peak-to-peak reading; everything else
            # lands from the prose <li>.
            frag.spec_source[field_name] = (
                SpecSource.DERIVED if field_name == "xmax_mm" else SpecSource.HTML_PROSE
            )

        # Coax HF section — second spec <ul>, if present.
        if kind == DriverKind.COAX and len(spec_uls) >= 2:
            hf_keys = sorted(_LABEL_MAP_COAX_HF.keys(), key=len, reverse=True)
            for text in spec_uls[1]:
                split = _split_li(text, hf_keys)
                if split is None:
                    continue
                label, value = split
                mapping = _LABEL_MAP_COAX_HF.get(label)
                if mapping is None or mapping[0] is None:
                    continue
                field_name, parser = mapping
                parsed = parser(value) if parser else value
                if parsed is None:
                    continue
                setattr(frag, field_name, parsed)
                frag.spec_source[field_name] = SpecSource.HTML_PROSE

        # Nominal size — derive from the URL slug; not published as a spec row.
        slug = raw.url.rstrip("/").rsplit("/", 1)[-1]
        size_mm = _nominal_size_mm_from_slug(slug)
        if size_mm is not None:
            frag.nominal_size_mm = size_mm
            frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        # Satori tweeters have slugs like `satori-tw29bn-b-8` — no size prefix,
        # but the VC diameter and the dome share the same nominal size. Fall
        # back to the voice-coil diameter for tweeters when the slug yielded
        # nothing (mirrors Beyma's tweeter fallback).
        if (
            frag.nominal_size_mm is None
            and frag.driver_kind == DriverKind.TWEETER
            and frag.voice_coil_diameter_mm is not None
        ):
            frag.nominal_size_mm = frag.voice_coil_diameter_mm
            frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        return ParseResult(fragments=[frag])
