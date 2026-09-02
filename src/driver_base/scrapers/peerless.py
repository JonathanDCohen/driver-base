"""Peerless (Peerless-by-Tymphany, products.peerless-audio.com) scraper.

Unlike every other v1 scraper, Peerless has no HTML product pages worth
parsing — `/transducer/{id}` is a Vue/Laravel SPA shell with zero
server-rendered specs. All data comes from a public unauthenticated JSON API:

  GET /api/drivers?page=N        paginated list (12/page, Laravel envelope)
  GET /api/driver/{id}           full per-driver record

Enumeration: fetch page 1, discover `last_page` from the envelope, enqueue
pages 2..last_page as additional seeds, and emit `/api/driver/{id}` product
URLs for every record on each page. Filter `Status == "Final"` (drops
Preliminary/Prototype). `per_page` > 12 returns HTTP 500 — do not override.

Parse: `json.loads(raw.body)` when `content_type` starts with
`application/json`; otherwise (defensive against HTML error pages) return
an empty ParseResult.

Sensitivity: Peerless publishes both `SensZ` (measured at TestVolt/1m) and
`SensRe` (corrected to 1W/1m using Re). Slot rules:
 - SensRe → `sensitivity_db_1w_1m` (always, when present)
 - SensZ  → `sensitivity_db_2_83v_1m` only when TestVolt == 2.83

Traps corrected from other scrapers:
 - `PowerLF` / `PowerUF` are frequency limits in Hz, NOT power ratings —
   they map to `freq_low_hz` / `freq_high_hz`.
 - `Cms` is µm/N (Peerless internal unit), divide by 1000 for mm/N.
 - `PowerSTD` varies per record (`AES2-1984`, `IEC 268-5`). Route the value
   to `power_aes_watts` either way; add `power_std_non_aes` warn flag when
   the standard is not AES2-1984.
"""

from __future__ import annotations

import json
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

# Peerless VC winding material codes (from Tymphany internal taxonomy).
# CCAW = Copper-Clad Aluminum Wire; AL = solid aluminium; CU = copper.
_VCMAT_TO_WINDING: dict[str, str] = {
    "CCAW": "Copper-clad aluminium",
    "AL": "Aluminium",
    "CU": "Copper",
    "CCAR": "Copper-clad aluminium (round)",
}

_BASE = "https://products.peerless-audio.com"
_DRIVERS_LIST_URL = f"{_BASE}/api/drivers"
_DRIVER_DETAIL_TEMPLATE = f"{_BASE}/api/driver/{{id}}"

# JSON `Type` field → DriverKind. Values not listed are dropped at parse
# (Headphone / Micro / any Tymphany-only category out of loudspeaker scope).
_TYPE_TO_KIND: dict[str, DriverKind] = {
    "Woofer": DriverKind.LF_WOOFER,
    "Subwoofer": DriverKind.LF_WOOFER,
    "Tweeter": DriverKind.TWEETER,
    "Compression": DriverKind.HF_COMPRESSION,
    "Fullrange": DriverKind.FULLRANGE,
    "Coaxial": DriverKind.COAX,
}


def _is_json(raw: RawArtifact) -> bool:
    return raw.content_type.split(";", 1)[0].strip().lower() == "application/json"


def _f(d: dict, key: str) -> Optional[float]:
    """Coerce a JSON numeric field to float. Treats null/absent/empty as None."""
    v = d.get(key)
    if (
        v is None or v == "" or v == 0 and key in ("Xmech",)
    ):  # 0 in Xmech = not measured
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _decide_page_number(url: str) -> int:
    """Extract `?page=N` from a listing URL. Defaults to 1."""
    import re

    m = re.search(r"[?&]page=(\d+)", url)
    return int(m.group(1)) if m else 1


@register
class PeerlessScraper(Scraper):
    name = "peerless"
    manufacturer_display = "Peerless"
    schema_version = "1.0"
    expected_min_records = 85  # ~94 in-scope Final records (109 total minus filters)
    max_seed_rounds = 3  # page-1 → discover last_page → fetch 2..N in one round

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=f"{_DRIVERS_LIST_URL}?page=1", context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        additional: list[SeedRef] = []
        page_seed_seen: set[str] = set()

        for art in seed_artifacts:
            # Only paginated listing envelopes go through enumerate.
            if "/api/drivers" not in art.url or "/api/driver/" in art.url:
                continue
            if not _is_json(art):
                continue
            try:
                envelope = json.loads(art.body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            rows = envelope.get("data", []) or []
            for row in rows:
                if row.get("Status") != "Final":
                    continue
                if row.get("Type") not in _TYPE_TO_KIND:
                    continue
                rid = row.get("id")
                if rid is None:
                    continue
                products.append(
                    SeedRef(
                        url=_DRIVER_DETAIL_TEMPLATE.format(id=rid),
                        context=SeedContext(),
                    )
                )

            # On page 1, enqueue every remaining page as one batch.
            current = _decide_page_number(art.url)
            last_page = int(envelope.get("last_page") or current)
            for p in range(current + 1, last_page + 1):
                next_url = f"{_DRIVERS_LIST_URL}?page={p}"
                if next_url in page_seed_seen:
                    continue
                page_seed_seen.add(next_url)
                additional.append(SeedRef(url=next_url, context=SeedContext()))

        return EnumerateResult(product_urls=products, additional_seed_urls=additional)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        if not _is_json(raw):
            return ParseResult(fragments=[])
        try:
            d: dict[str, Any] = json.loads(raw.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return ParseResult(fragments=[])

        model = d.get("MarketingNo")
        if not model:
            return ParseResult(fragments=[])
        kind = _TYPE_TO_KIND.get(d.get("Type", ""))
        if kind is None:
            return ParseResult(fragments=[])
        if d.get("Status") not in (None, "Final"):
            # Defensive — enumerate filters Preliminary/Prototype, but a direct
            # fetch of an unlisted ID could slip through.
            return ParseResult(fragments=[])

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=str(model),
        )

        # T/S — all numeric, all in canonical units already except Cms (µm/N).
        _set(frag, "fs_hz", _f(d, "Fs"))
        _set(frag, "qts", _f(d, "Qts"))
        _set(frag, "qes", _f(d, "Qes"))
        _set(frag, "qms", _f(d, "Qms"))
        _set(frag, "vas_liters", _f(d, "Vas"))
        _set(frag, "sd_cm2", _f(d, "Sd"))
        _set(frag, "mms_g", _f(d, "Mms"))
        _set(frag, "bl_tm", _f(d, "BL"))
        _set(frag, "le_mh", _f(d, "Le"))
        _set(frag, "re_ohm", _f(d, "Re"))
        cms_um = _f(d, "Cms")
        if cms_um is not None:
            _set(frag, "cms_mm_per_n", cms_um / 1000.0)
        _set(frag, "xmax_mm", _f(d, "Xmax"))
        _set(frag, "xmech_mm", _f(d, "Xmech"))

        _set(frag, "impedance_nominal_ohm", _f(d, "Impedance"))
        _set(frag, "impedance_min_ohm", _f(d, "Zmin"))
        _set(frag, "nominal_size_mm", _f(d, "Size"))
        _set(frag, "net_weight_kg", _f(d, "NetWeight"))
        _set(frag, "voice_coil_diameter_mm", _f(d, "VCID"))

        magnet = normalize_magnet_type(d.get("MagnetType"))
        if magnet is not None:
            frag.magnet_type = magnet
            frag.spec_source["magnet_type"] = SpecSource.JSON_API

        vcmat = _VCMAT_TO_WINDING.get((d.get("VCMat") or "").strip().upper())
        if vcmat:
            frag.winding_material = vcmat
            frag.spec_source["winding_material"] = SpecSource.JSON_API

        # Sensitivity: SensRe → 1W/1m always; SensZ → 2.83V/1m only when
        # TestVolt says so.
        _set(frag, "sensitivity_db_1w_1m", _f(d, "SensRe"))
        if _f(d, "TestVolt") == 2.83:
            _set(frag, "sensitivity_db_2_83v_1m", _f(d, "SensZ"))

        # Power. Slot into AES; warn when the standard is not AES.
        _set(frag, "power_aes_watts", _f(d, "Power"))
        std = (d.get("PowerSTD") or "").strip()
        if std and "AES" not in std.upper():
            frag.warn_flags.append("power_std_non_aes")

        # PowerLF / PowerUF are recommended usable BAND edges in Hz.
        _set(frag, "freq_low_hz", _f(d, "PowerLF"))
        _set(frag, "freq_high_hz", _f(d, "PowerUF"))

        return ParseResult(fragments=[frag])


def _set(frag: DriverFragment, field_name: str, value: Optional[float]) -> None:
    if value is None:
        return
    setattr(frag, field_name, value)
    frag.spec_source[field_name] = SpecSource.JSON_API
