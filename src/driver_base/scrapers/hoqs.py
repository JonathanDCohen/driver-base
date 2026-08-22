"""HOQS (hoqs.org) scraper.

Enumeration: single seed at `/products.json?limit=250&page=1` (Shopify API).
The seed's JSON `products[]` array carries `handle`, `product_type`, `title`
per product — enough to build the product-page URL AND assign
`driver_kind_hint` before fetching.

Extraction: each product page has an inline `var speakerData = {...};` JS
object literal (static text in the HTML — no JS execution required). Three
sub-objects: `general`, `physical`, and `thieleSmall` (an array of
`{name, symbol, value, unit}` items). Extraction is a regex plus
`json.loads` — SpecSource is INLINE_JS.

We filter out non-driver product_types (Amplifier, Recone). Products with
empty `product_type` are kept only if the handle contains a speaker-ish
token; otherwise skipped.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from driver_base.interface import (
    DriverKind,
    EnumerateResult,
    ParseResult,
    RawArtifact,
    Scraper,
    SeedContext,
    SeedRef,
)
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
    parse_sd_cm2,
)


_BASE = "https://hoqs.org"

_TYPE_TO_KIND: dict[str, DriverKind] = {
    "Speaker": DriverKind.LF_WOOFER,
    "Compression Driver": DriverKind.HF_COMPRESSION,
    "Horn": DriverKind.HORN,
    "Waveguide": DriverKind.HORN,
    "Midrange": DriverKind.FULLRANGE,
}
_SKIP_TYPES: frozenset[str] = frozenset({"Amplifier", "Recone"})
_SPEAKERISH_HANDLE_TOKENS = ("speaker", "driver", "sub", "woofer", "midwave", "coax")

# symbol (from speakerData.thieleSmall) → (Driver field, parser)
_TS_SYMBOL_MAP: dict[str, tuple[str, Any]] = {
    "fs": ("fs_hz", parse_frequency),
    "qts": ("qts", parse_float),
    "qes": ("qes", parse_float),
    "qms": ("qms", parse_float),
    "vas": ("vas_liters", parse_liters),
    "re": ("re_ohm", parse_impedance),
    "sd": ("sd_cm2", parse_sd_cm2),
    "mms": ("mms_g", parse_mass_g),
    "bl": ("bl_tm", parse_bl_tm),
    "xmax": ("xmax_mm", parse_length_mm),
    "xmech": ("xmech_mm", parse_length_mm),
    "le_1k": ("le_mh", parse_le_mh),
    "le": ("le_mh", parse_le_mh),
    "n0": ("eta_zero_pct", parse_float),
    "ebp": ("ebp_hz", parse_frequency),
    "spl": ("sensitivity_db_2_83v_1m", parse_float),   # HOQS labels sensitivity as 2.83V
}

# general/physical keys → (Driver field, parser)
_GENERAL_KEY_MAP: dict[str, tuple[str, Any]] = {
    "Nominal Diameter": ("nominal_size_mm", parse_length_mm),
    "Nominal Impedance": ("impedance_nominal_ohm", parse_impedance),
    "Power Handling Nominal": ("power_aes_watts", parse_power),
    "Power Handling Program": ("power_program_watts", parse_power),
    "Voice Coil Diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "Cone Material": (None, None),                                  # kept for docs
    "Magnetic Material": ("magnet_type", lambda s: normalize_magnet_type(s)),
    "Overall Diameter": ("overall_diameter_mm", parse_length_mm),
    "Bolt Circle Diameter": (None, None),
    "Cutout Diameter": ("mounting_diameter_mm", parse_length_mm),
    "Total Depth": ("depth_mm", parse_length_mm),
    "Net Weight": ("net_weight_kg", lambda s: (parse_mass_g(s) or 0) / 1000.0 if parse_mass_g(s) else None),
}

_SPEAKER_DATA_RE = re.compile(r"var speakerData = (\{.*?\});", re.DOTALL)


def _kind_for_product(product_type: str, handle: str) -> Optional[DriverKind]:
    if product_type in _SKIP_TYPES:
        return None
    if product_type in _TYPE_TO_KIND:
        return _TYPE_TO_KIND[product_type]
    # empty product_type → keep if handle looks driver-ish
    h = handle.lower()
    if any(t in h for t in _SPEAKERISH_HANDLE_TOKENS):
        return DriverKind.LF_WOOFER
    return None


def _model_from_handle(handle: str) -> Optional[str]:
    parts = [p for p in handle.split("-") if p]
    if not parts:
        return None
    if parts[0].lower() == "hoqs":
        parts = parts[1:]
    if not parts:
        return None
    return parts[0].upper()


@register
class HoqsScraper(Scraper):
    name = "hoqs"
    manufacturer_display = "HOQS"
    schema_version = "1.0"
    expected_min_records = 4         # recon: 13 total, ~9 drivers; not all publish speakerData
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=f"{_BASE}/products.json?limit=250&page=1", context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            try:
                payload = json.loads(art.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for p in payload.get("products") or []:
                handle = p.get("handle")
                if not handle or handle in seen:
                    continue
                seen.add(handle)
                kind = _kind_for_product(p.get("product_type") or "", handle)
                if kind is None:
                    continue
                products.append(
                    SeedRef(
                        url=f"{_BASE}/products/{handle}",
                        context=SeedContext(
                            driver_kind_hint=kind,
                            category_id=p.get("product_type") or None,
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        text = raw.body.decode("utf-8", errors="ignore")
        m = _SPEAKER_DATA_RE.search(text)
        if not m:
            return ParseResult(fragments=[])
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return ParseResult(fragments=[])

        handle = raw.url.rsplit("/", 1)[-1]
        model = _model_from_handle(handle)
        if not model:
            return ParseResult(fragments=[])

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=seed_context.driver_kind_hint,
            model=model,
        )

        # general + physical: string labels
        for section_key in ("general", "physical"):
            section = data.get(section_key) or {}
            if not isinstance(section, dict):
                continue
            for label, raw_val in section.items():
                mapping = _GENERAL_KEY_MAP.get(label)
                if mapping is None or mapping[0] is None:
                    continue
                field_name, parser = mapping
                parsed = parser(raw_val) if parser else raw_val
                if parsed is None or parsed == "":
                    continue
                setattr(frag, field_name, parsed)
                frag.spec_source[field_name] = SpecSource.INLINE_JS

        # thieleSmall: array of {name, symbol, value, unit}
        ts = data.get("thieleSmall") or data.get("ThieleSmall") or []
        if isinstance(ts, list):
            for entry in ts:
                if not isinstance(entry, dict):
                    continue
                symbol = str(entry.get("symbol") or "").strip().lower()
                mapping = _TS_SYMBOL_MAP.get(symbol)
                if mapping is None:
                    continue
                field_name, parser = mapping
                raw_val = entry.get("value")
                if raw_val is None:
                    continue
                # thieleSmall values arrive numeric; stringify for the parsers
                parsed = parser(str(raw_val))
                if parsed is None:
                    continue
                setattr(frag, field_name, parsed)
                frag.spec_source[field_name] = SpecSource.INLINE_JS

        return ParseResult(fragments=[frag])
