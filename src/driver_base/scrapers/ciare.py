"""Ciare (ciare.com) scraper.

Enumeration: Ciare's catalog listing (`/en/products/{category}`) is a
Next-style SPA shell that embeds the FULL stripped-down catalog as inline
JSON. We fetch one category page, walk every product in the JSON, and emit
per-product detail URLs matching the SPA's Remix route
`/products/:preview?/:category/:inches/:ohms/:code`. The detail page's JSON
carries much richer data than the catalog view — full Thiele–Small
parameters under `variants[].params`, plus physical/mounting fields in
`variants[].shippingMounting` — so one fetch per model is worth the cost.

Extraction: parse each detail page, find the product object whose `name`
matches the URL's trailing path segment, iterate its `variants[]` and emit
one `DriverFragment` per (product × variant). Mapping notes:

- `nominalPowerHandling` → `power_aes_watts` (AES/Nominal rating).
- `continuousPowerHandling` → `power_program_watts` (2× Nominal per Ciare's
  own note "Program Power is defined as 3 dB greater than the Nominal
  rating").
- `sensitivity` → `sensitivity_db_2_83v_1m` — in-page tooltip says
  "measured ... when connected to 2,83V sine wave test signal" despite the
  misleading "1W/1m" heading. Framework derives the 1W/1m slot for us.
- `params.*` → canonical T/S fields; existing unit parsers handle Ciare's
  `"239 dm³ (8.44 ft³)"` / `"1164 cm² (180.42 in²)"` / `"7.2 Tm"` shapes.
- `inches` (product-level) → `nominal_size_mm` via `* 25.4`.
- `neodymium` boolean → `magnet_type` (no per-product magnet-material
  string published on 90%+ of products).

The category-page catalog is used only for enumeration — the stripped
`lfSpecs`/`hfSpecs` on the catalog view are NOT the source of truth for
anything but the (category, inches, ohms, name) tuple needed to build
detail URLs.
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
from driver_base.model import DriverFragment, MagnetType, SpecSource
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


_BASE = "https://ciare.com"
# The LF category seed returns the full catalog (Ciare's client filters by
# category._id on the inline JSON). One fetch gives us every product name,
# category, inches, and first-variant impedance — enough to build 148
# product-detail URLs.
_SEED_URL = f"{_BASE}/en/products/lf-driver"


_CATEGORY_TO_KIND: dict[str, DriverKind] = {
    "lf-driver": DriverKind.LF_WOOFER,
    "hf-driver": DriverKind.HF_COMPRESSION,
    "tweeter": DriverKind.TWEETER,
    "coaxial": DriverKind.COAX,
    "fullrange-driver": DriverKind.FULLRANGE,
}


def _iter_products(html: str):
    """Yield every top-level product object embedded in the inline JSON.

    Each product record on the catalog view contains
    `"name":"<MODEL>","archived":...`. On the detail view the wrappedProduct
    has the same shape. Walk the string, find each marker, extract the
    balanced-brace object starting at the nearest preceding `{`.
    """
    for m in re.finditer(r'"name":"([A-Z][A-Z0-9/.\-]+)","archived":', html):
        start = html.rfind("{", 0, m.start())
        if start < 0:
            continue
        depth = 0
        end = start
        j = start
        while j < len(html):
            c = html[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if depth != 0:
            continue
        try:
            obj = json.loads(html[start : end + 1])
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if "variants" not in obj or "category" not in obj:
            continue
        yield obj


def _slug(x: Any) -> str:
    """Render an `inches` / `impedance` value for the detail-URL path."""
    if isinstance(x, float) and not x.is_integer():
        return str(x)
    if isinstance(x, (int, float)):
        return str(int(x))
    return "0"


def _computed(section: Optional[dict], key: str) -> Optional[str]:
    if not isinstance(section, dict):
        return None
    entry = section.get(key)
    if not isinstance(entry, dict):
        return None
    cv = entry.get("computedValue")
    if cv in (None, "", "None"):
        return None
    return str(cv)


# `params.<key>` → (Driver field, parser). Ciare's params dict is the
# authoritative T/S block on product-detail pages.
_PARAMS_MAP: dict[str, tuple[str, Any]] = {
    "fs": ("fs_hz", parse_frequency),
    "re": ("re_ohm", parse_impedance),
    "qes": ("qes", parse_float),
    "qms": ("qms", parse_float),
    "qts": ("qts", parse_float),
    "vas": ("vas_liters", parse_liters),
    "sd": ("sd_cm2", parse_sd_cm2),
    "etaZero": ("eta_zero_pct", parse_float),
    "xmax": ("xmax_mm", parse_length_mm),
    "xvar": ("xvar_mm", parse_length_mm),
    "mms": ("mms_g", parse_mass_g),
    "bl": ("bl_tm", parse_bl_tm),
    "le": ("le_mh", parse_le_mh),
    "cms": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "ebp": ("ebp_hz", parse_frequency),
}

# shippingMounting.<key> → (Driver field, parser).
_SHIPPING_MAP: dict[str, tuple[str, Any]] = {
    "overallDiameter": ("overall_diameter_mm", parse_length_mm),
    "baffleCutoutDiameter": ("mounting_diameter_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),
    "netWeight": (
        "net_weight_kg",
        lambda s: (parse_mass_g(s) or 0) / 1000.0 if parse_mass_g(s) else None,
    ),
}


def _apply_section(
    frag: DriverFragment, section: dict, *, coax_hf: bool = False
) -> None:
    """Pull the shared LF/HF spec fields (impedance, power, sensitivity,
    frequency range, voice-coil diameter, nominal diameter, descriptors)
    out of a Ciare `lfSpecs`/`hfSpecs` dict."""
    if not isinstance(section, dict):
        return

    def set_field(name: str, value: Any) -> None:
        if value is None:
            return
        setattr(frag, name, value)
        frag.spec_source[name] = SpecSource.INLINE_JS

    imp = parse_impedance(_computed(section, "nominalImpedance"))
    imp_min = parse_impedance(_computed(section, "minimumImpedance"))
    pwr_aes = parse_power(_computed(section, "nominalPowerHandling"))
    pwr_prog = parse_power(_computed(section, "continuousPowerHandling"))
    pwr_peak = parse_power(_computed(section, "momentaryMaximumPower"))
    sens = parse_float(_computed(section, "sensitivity"))
    vc = parse_length_mm(_computed(section, "voiceCoilDiameter"))
    nominal_d = parse_length_mm(_computed(section, "nominalDiameter"))
    rng = parse_range(_computed(section, "frequencyRange"))
    if rng is not None and rng[0] >= rng[1]:
        rng = None

    if coax_hf:
        set_field("coax_hf_impedance_nominal_ohm", imp)
        set_field("coax_hf_impedance_min_ohm", imp_min)
        set_field("coax_hf_power_aes_watts", pwr_aes)
        set_field("coax_hf_voice_coil_diameter_mm", vc)
        if rng is not None:
            set_field("coax_hf_freq_low_hz", rng[0])
            set_field("coax_hf_freq_high_hz", rng[1])
        # No coax_hf_sensitivity_2.83V slot (see sbacoustics for the same
        # decision — framework has coax_hf_sensitivity_db_1w_1m only).
        return

    set_field("impedance_nominal_ohm", imp)
    set_field("impedance_min_ohm", imp_min)
    set_field("power_aes_watts", pwr_aes)
    set_field("power_program_watts", pwr_prog)
    set_field("power_peak_watts", pwr_peak)
    set_field("sensitivity_db_2_83v_1m", sens)
    set_field("voice_coil_diameter_mm", vc)
    set_field("nominal_size_mm", nominal_d)
    if rng is not None:
        set_field("freq_low_hz", rng[0])
        set_field("freq_high_hz", rng[1])

    for raw_key, field_name in (
        ("windingMaterial", "winding_material"),
        ("formerMaterial", "former_material"),
        ("diaphragmMaterial", "diaphragm_material"),
    ):
        val = _computed(section, raw_key)
        if val:
            set_field(field_name, val)


def _apply_params(frag: DriverFragment, params: dict) -> None:
    if not isinstance(params, dict):
        return
    for key, (field_name, parser) in _PARAMS_MAP.items():
        raw = _computed(params, key)
        if raw is None:
            continue
        parsed = parser(raw)
        if parsed is None:
            continue
        setattr(frag, field_name, parsed)
        frag.spec_source[field_name] = SpecSource.INLINE_JS


def _apply_shipping(frag: DriverFragment, shipping: dict) -> None:
    if not isinstance(shipping, dict):
        return
    for key, (field_name, parser) in _SHIPPING_MAP.items():
        raw = _computed(shipping, key)
        if raw is None:
            continue
        parsed = parser(raw)
        if parsed is None:
            continue
        setattr(frag, field_name, parsed)
        frag.spec_source[field_name] = SpecSource.INLINE_JS


def _build_fragments(
    prod: dict, kind: DriverKind, source_url: str, fetched_at: str
) -> list[DriverFragment]:
    """Emit one DriverFragment per variant of a single product."""
    model = prod.get("name")
    if not model:
        return []
    is_neo = bool(prod.get("neodymium"))
    inches = prod.get("inches")
    out: list[DriverFragment] = []
    for variant in prod.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        if variant.get("archived"):
            continue
        frag = DriverFragment(
            manufacturer="Ciare",
            source_url=source_url,
            fetched_at=fetched_at,
            driver_kind=kind,
            model=model,
        )

        # Nominal size from the top-level inches (always populated); lfSpecs
        # nominalDiameter overrides below when present.
        if isinstance(inches, (int, float)) and inches > 0:
            frag.nominal_size_mm = float(inches) * 25.4
            frag.spec_source["nominal_size_mm"] = SpecSource.INLINE_JS

        v_imp = variant.get("nominalImpedance")
        if isinstance(v_imp, (int, float)) and v_imp > 0:
            frag.impedance_nominal_ohm = float(v_imp)
            frag.spec_source["impedance_nominal_ohm"] = SpecSource.INLINE_JS

        lf = variant.get("lfSpecs")
        hf = variant.get("hfSpecs")
        gen = variant.get("generalSpecs")
        params = variant.get("params")
        shipping = variant.get("shippingMounting")

        if kind == DriverKind.COAX:
            _apply_section(frag, lf or {}, coax_hf=False)
            _apply_section(frag, hf or {}, coax_hf=True)
            # Route HF diaphragm material to the generic slot (the HF
            # section IS the compression driver; no LF competitor).
            hf_dia = _computed(hf, "diaphragmMaterial")
            if hf_dia:
                frag.diaphragm_material = hf_dia
                frag.spec_source["diaphragm_material"] = SpecSource.INLINE_JS
        elif kind in (DriverKind.HF_COMPRESSION, DriverKind.TWEETER):
            _apply_section(frag, hf or {}, coax_hf=False)
        else:
            _apply_section(frag, lf or {}, coax_hf=False)

        # generalSpecs impedance is an occasional coax fallback.
        gen_imp = parse_impedance(_computed(gen, "nominalImpedance"))
        if gen_imp is not None and frag.impedance_nominal_ohm is None:
            frag.impedance_nominal_ohm = gen_imp
            frag.spec_source["impedance_nominal_ohm"] = SpecSource.INLINE_JS

        _apply_params(frag, params or {})
        _apply_shipping(frag, shipping or {})

        frag.magnet_type = MagnetType.NEODYMIUM if is_neo else MagnetType.CERAMIC
        frag.spec_source["magnet_type"] = SpecSource.INLINE_JS

        out.append(frag)
    return out


@register
class CiareScraper(Scraper):
    name = "ciare"
    manufacturer_display = "Ciare"
    schema_version = "1.0"
    # ~148 products × up to 2 variants ≈ 160 fragments at 2026-11-05.
    expected_min_records = 100
    max_seed_rounds = 2

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_SEED_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        """Walk the catalog JSON once, emit one product-detail URL per
        product. Each detail page's JSON carries rich T/S + physical data
        that the catalog view omits."""
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            html = art.body.decode("utf-8", errors="ignore")
            for prod in _iter_products(html):
                name = prod.get("name")
                if not name or name in seen:
                    continue
                cat_id = (prod.get("category") or {}).get("_id")
                kind = _CATEGORY_TO_KIND.get(cat_id)
                if kind is None:
                    continue
                variants = prod.get("variants") or []
                if not variants:
                    continue
                # Use the first variant's impedance in the URL path (SPA
                # loads all variants from the same detail JSON regardless).
                first_imp = next(
                    (
                        v.get("nominalImpedance")
                        for v in variants
                        if isinstance(v, dict) and v.get("nominalImpedance")
                    ),
                    None,
                )
                inches = prod.get("inches")
                url = (
                    f"{_BASE}/en/products/{cat_id}/"
                    f"{_slug(inches)}/{_slug(first_imp)}/{name}"
                )
                seen.add(name)
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(
                            driver_kind_hint=kind,
                            category_id=cat_id,
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        """On a detail page, find the one product whose name matches the
        URL's trailing segment. Detail pages also embed related/similar
        products — we must NOT emit those (they'd duplicate across pages)."""
        html = raw.body.decode("utf-8", errors="ignore")
        # Model name is the URL's last path segment.
        try:
            target = raw.url.rstrip("/").rsplit("/", 1)[-1]
        except Exception:
            return ParseResult(fragments=[])

        kind = seed_context.driver_kind_hint
        if kind is None and seed_context.category_id:
            kind = _CATEGORY_TO_KIND.get(seed_context.category_id)

        for prod in _iter_products(html):
            if prod.get("name") != target:
                continue
            resolved_kind = kind or _CATEGORY_TO_KIND.get(
                (prod.get("category") or {}).get("_id")
            )
            if resolved_kind is None:
                continue
            return ParseResult(
                fragments=_build_fragments(prod, resolved_kind, raw.url, raw.fetched_at)
            )
        return ParseResult(fragments=[])
