"""Faital Pro (faitalpro.com) scraper.

Enumeration: seed the three product-carrying category listing pages
(LF_Loudspeakers, HF_Drivers, Coaxial_Loudspeakers). LF and HF-drivers
render their product tables via XHR — the browser POSTs to
`<category>/search.php` with the default filter and injects the response
into `#main_content`; we POST directly instead of running JS. Coax ships
its table inline in the listing HTML (plain GET). Either way, enumerate
scrapes `product_details/index.php?id=<N>` occurrences from the response
body and tags each product with the DriverKind derived from the seed URL.

HF_Horns is intentionally excluded — passive horns don't share the driver
schema meaningfully (no T/S, no impedance/power the way transducers have
them) and horn expertise isn't in the near-term scope. See docs/tasks.md
if we want to bring them back.

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
    "LF_Loudspeakers": DriverKind.LF_WOOFER,
    "HF_Drivers": DriverKind.HF_COMPRESSION,
    "Coaxial_Loudspeakers": DriverKind.COAX,
}

# Default filter payloads copied verbatim from each listing page's
# `update_data()` JS. Wide-open ranges — matches "show me everything".
# LF_Loudspeakers/search.php filter:
_LF_SEARCH_POST: tuple[tuple[str, str], ...] = (
    ("neodymium", "10"),
    ("ferrite", "20"),
    ("size", "All"),
    ("powermin", "20"),
    ("powermax", "3000"),
    ("vcmin", "15"),
    ("vcmax", "170"),
    ("fsmin", "20"),
    ("fsmax", "180"),
    ("demod", "1"),
    ("nodemod", "1"),
)
# HF_Drivers/search.php filter:
_HF_SEARCH_POST: tuple[tuple[str, str], ...] = (
    ("neodymium", "10"),
    ("ferrite", "20"),
    ("size", "All"),
    ("powermin", "30"),
    ("powermax", "120"),
    ("vcdiam", "All"),
    ("crossfreqmin", "0.4"),
    ("crossfreqmax", "2.6"),
    ("demod", "1"),
    ("nodemod", "1"),
    ("dshape1", "Dome"),
    ("dshape2", "Annular"),
    ("dshape3", "Double Edge Cone"),
    ("dmaterial1", "Titanium"),
    ("dmaterial2", "Ketone Polymer"),
    ("dmaterial3", "Paper"),
    ("dmaterial4", "Carbon Fiber"),
    ("plugdesign1", "Annular"),
    ("plugdesign2", "Radial"),
)

# Match the URL segment naming the category, in either a seed URL
# (`.../en/products/LF_Loudspeakers/search.php` or `.../en/products/Coaxial_Loudspeakers/`)
# or a discovered product URL.
_SEED_CATEGORY_RE = re.compile(
    r"/en/products/(?P<category>LF_Loudspeakers|HF_Drivers|Coaxial_Loudspeakers)/"
)
# `product_details/index.php?id=101050135` — id is the only capture we need;
# category comes from the seed URL that yielded this body. search.php responses
# JSON-escape the slash as `product_details\/index.php` — optional backslash.
_PRODUCT_ID_RE = re.compile(r"product_details\\?/index\.php\?id=(\d+)")

# HF compression drivers publish per-crossover-frequency AES/Max ratings —
# "AES Power above 0.9 kHz" and "AES Power above 0.65 kHz" side by side. Collapse
# both to the plain `aes power handling` / `maximum power handling` labels used
# by LF drivers so they hit the same map entries. The higher-crossover rating
# (safer, matches "Minimum Crossover Frequency") is listed first in every Faital
# HF page we've inspected, so the first-occurrence-wins dedup keeps that one.
_POWER_ABOVE_KHZ_RE = re.compile(r"^(aes power|maximum power) above [\d.]+ khz$")

# `FaitalPRO | LF Loudspeakers | 12PR320 (8Ω)` → group(1) = '12PR320'
_TITLE_MODEL_RE = re.compile(r"\|\s*([^|()]+?)\s*(?:\(|$)")


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


_LABEL_MAP: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    # T/S
    "fs": ("fs_hz", parse_frequency),
    "re": ("re_ohm", parse_impedance),
    "qes": ("qes", parse_float),
    "qms": ("qms", parse_float),
    "qts": ("qts", parse_float),
    "vas": ("vas_liters", parse_liters),
    "sd": ("sd_cm2", parse_sd_cm2),
    "xmax": ("xmax_mm", parse_length_mm),
    "xdamage": (
        "xmech_mm",
        parse_length_mm,
    ),  # Faital ONE-WAY AS-REPORTED (framework nominally p-p; see docs/manufacturers.md)
    "mms": ("mms_g", parse_mass_g),
    "bl": ("bl_tm", parse_bl_tm),
    "le": ("le_mh", parse_le_mh),
    "cms": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "rms": ("rms_ns_per_m", parse_float),  # kg/s ≡ N·s/m
    "eta zero": ("eta_zero_pct", parse_float),
    "ebp": ("ebp_hz", parse_frequency),
    # electrical / commercial
    "nominal impedance": ("impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("impedance_min_ohm", parse_impedance),
    "aes power handling": ("power_aes_watts", parse_power),
    "maximum power handling": ("power_peak_watts", parse_power),
    "sensitivity (1w/1m)": ("sensitivity_db_1w_1m", parse_float),
    "frequency range": ("__freq_range__", parse_range),
    # physical
    "nominal diameter": ("nominal_size_mm", parse_length_mm),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "baffle cutout diameter": ("mounting_diameter_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),
    "net weight": ("net_weight_kg", _weight_kg),
    "magnet": ("magnet_type", lambda s: normalize_magnet_type(s)),
    # Compression-driver fields (HF pages have no Nominal Diameter; the throat
    # is used to derive `nominal_size_mm` in a post-parse step below).
    "throat diameter": ("throat_diameter_mm", parse_length_mm),
    # HF drivers: `Minimum Crossover Frequency (3)` → `minimum crossover frequency`.
    # Coax: `Min. Cross. Freq. (4)` in the 3-col HF cell → `min. cross. freq.`
    # (handled by _LABEL_MAP_COAX_HF below, routing to the same generic field).
    "minimum crossover frequency": ("recommended_crossover_hz", parse_frequency),
    "diaphragm material": ("diaphragm_material", lambda s: s or None),
    "diaphragm shape": ("diaphragm_shape", lambda s: s or None),
    # Construction descriptors — mostly LF, some on HF.
    "winding material": ("winding_material", lambda s: s or None),
    "former material": ("former_material", lambda s: s or None),
    "cone surround": ("surround_material", lambda s: s or None),
    "phase plug design": ("phase_plug_design", lambda s: s or None),
    "flux density": ("flux_density_t", parse_float),
    "net air volume filled by loudspeaker": (
        "recommended_enclosure_volume_liters",
        parse_liters,
    ),
    # Coax pages use abbreviated forms of the same labels — keep original entries
    # above (for LF/HF pages) and add abbreviated aliases here.
    "nom. diameter": ("nominal_size_mm", parse_length_mm),
    "nom. impedance": ("impedance_nominal_ohm", parse_impedance),
    "max power handling": ("power_peak_watts", parse_power),
}


# Coax "Technical Parameters" is a 3-column table — label | LF value | HF value.
# The generic map above populates fields from the LF value (cells[1]); this map
# routes the HF value (cells[2]) to the coax_hf_* fields. Only labels that have
# both an LF and HF variant need entries here; single-section labels (e.g.
# `Basket Material`, `Cone Surround`) don't.
_LABEL_MAP_COAX_HF: dict[
    str, tuple[Optional[str], Optional[Callable[[Optional[str]], Any]]]
] = {
    "nominal impedance": ("coax_hf_impedance_nominal_ohm", parse_impedance),
    "nom. impedance": ("coax_hf_impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("coax_hf_impedance_min_ohm", parse_impedance),
    "aes power handling": ("coax_hf_power_aes_watts", parse_power),
    "max power handling": ("coax_hf_power_peak_watts", parse_power),
    "maximum power handling": ("coax_hf_power_peak_watts", parse_power),
    "sensitivity (1w/1m)": ("coax_hf_sensitivity_db_1w_1m", parse_float),
    "frequency range": ("__coax_hf_freq_range__", parse_range),
    "voice coil diameter": ("coax_hf_voice_coil_diameter_mm", parse_length_mm),
    # Diaphragm fields — on coax, LF cell is `-` and HF has the real value; the
    # HF value routes into the GENERIC field (the HF section IS the compression
    # driver, and there's no LF competitor for the diaphragm slot).
    "diaphragm material": ("diaphragm_material", lambda s: s or None),
    "diaphragm shape": ("diaphragm_shape", lambda s: s or None),
    # `Min. Cross. Freq.` HF cell → recommended_crossover_hz (LF cell is `-`).
    "min. cross. freq.": ("recommended_crossover_hz", parse_frequency),
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
    expected_min_records = 120  # recon: ~158 active English URLs across 4 categories
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
            # HF_Horns intentionally omitted — see module docstring.
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
                    f"{_BASE}/en/products/{category}/product_details/index.php?id={pid}"
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

        # `tbl_data` = mini "quick specs" tables shared across LF/HF/coax pages.
        # `tbl_datasheet` = master table; coax's 3-col "Technical Parameters"
        # block (label | LF | HF) lives ONLY here. Use `recursive=False` on cell
        # lookup so nested tables don't bleed their content into outer rows.
        specs: dict[str, str] = {}  # label → LF-or-only value
        specs_hf: dict[str, str] = {}  # label → HF value (3-col rows only)
        for table in soup.select("table.tbl_data, table.tbl_datasheet"):
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"], recursive=False)
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(" ", strip=True)
                # `Re [LF]` and `Re [HF]` come as 2-col rows with the [LF]/[HF]
                # tag baked into the label. Preserve the tag so `re` doesn't
                # collide across sections after normalize_label strips brackets.
                if "[LF]" in label:
                    label = label.replace("[LF]", "").strip()
                    hf_from_2col = False
                    force_lf = True
                elif "[HF]" in label:
                    label = label.replace("[HF]", "").strip()
                    force_lf = False
                    hf_from_2col = True
                else:
                    force_lf = False
                    hf_from_2col = False
                if not label:
                    continue
                key = normalize_label(label)
                m = _POWER_ABOVE_KHZ_RE.match(key)
                if m:
                    key = f"{m.group(1)} handling"
                value_lf = cells[1].get_text(" ", strip=True)
                value_hf = (
                    cells[2].get_text(" ", strip=True) if len(cells) >= 3 else None
                )
                if hf_from_2col:
                    # `Re [HF]` — the single value belongs to the HF section.
                    if value_lf and value_lf not in ("--", "-") and key not in specs_hf:
                        specs_hf[key] = value_lf
                    continue
                if value_lf and value_lf not in ("--", "-") and key not in specs:
                    specs[key] = value_lf
                if value_hf and value_hf not in ("--", "-") and key not in specs_hf:
                    specs_hf[key] = value_hf
                # `force_lf` is redundant (already-populated in `specs`) but
                # named to make the [LF]-tag intent explicit at the callsite.
                del force_lf

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

        # Route Re from 2-col [HF] rows into coax_hf_re_ohm (no map entry needed
        # since it's a single-column value promoted directly to the HF slot).
        if "re" in specs_hf:
            re_hf = parse_impedance(specs_hf["re"])
            if re_hf is not None:
                frag.coax_hf_re_ohm = re_hf
                frag.spec_source["coax_hf_re_ohm"] = SpecSource.HTML_TABLE

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

        # Coax HF-section fields.
        for norm_label, raw_val in specs_hf.items():
            mapping = _LABEL_MAP_COAX_HF.get(norm_label)
            if mapping is None or mapping[0] is None:
                continue
            field_name, parser = mapping
            parsed = parser(raw_val) if parser else raw_val
            if parsed is None:
                continue
            if field_name == "__coax_hf_freq_range__":
                low, high = parsed  # type: ignore[misc]
                frag.coax_hf_freq_low_hz = low
                frag.coax_hf_freq_high_hz = high
                frag.spec_source["coax_hf_freq_low_hz"] = SpecSource.HTML_TABLE
                frag.spec_source["coax_hf_freq_high_hz"] = SpecSource.HTML_TABLE
                continue
            setattr(frag, field_name, parsed)
            frag.spec_source[field_name] = SpecSource.HTML_TABLE

        # HF compression drivers have no "Nominal Diameter" label — the throat
        # is what the product is sized by ("2\" driver", "1.4\" driver"). Use
        # it as `nominal_size_mm` when nothing else set the field; tagged
        # DERIVED so the UI can indicate the transform. A few older-style HF
        # drivers (e.g. FD371/FD375) report `Throat Diameter: N/A` — those
        # legitimately have no throat and stay size-less.
        if frag.throat_diameter_mm is not None and frag.nominal_size_mm is None:
            frag.nominal_size_mm = frag.throat_diameter_mm
            frag.spec_source["nominal_size_mm"] = SpecSource.DERIVED

        return ParseResult(fragments=[frag])
