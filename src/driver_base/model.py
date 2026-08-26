"""Driver dataclass, DriverFragment, and status/source/magnet enums.

`model` is mandatory on both DriverFragment and Driver: if a parser cannot
extract a model string, it must raise/skip rather than emit a partial
fragment. Every identity operation downstream (canonical_id derivation, alias
lookup, retailer matching) depends on a non-empty model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from driver_base.interface import DriverKind


class DriverStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    UNAVAILABLE = "unavailable"    # temporarily out of stock but listed


class MagnetType(str, Enum):
    CERAMIC = "ceramic"            # includes raw values "ferrite"/"ceramic"
    NEODYMIUM = "neodymium"        # includes "neo"/"neodymium slug/ring"
    ALNICO = "alnico"              # Celestion Blue and similar classics
    OTHER = "other"                # hybrid, unknown, or unparseable


class SpecSource(str, Enum):
    HTML_TABLE = "html_table"
    HTML_GRID = "html_grid"
    HTML_PROSE = "html_prose"
    HTML_DIV_PAIRS = "html_div_pairs"
    INLINE_JS = "inline_js"        # HOQS var speakerData = {...};
    PDF_TEXT = "pdf_text"
    PDF_TABLE = "pdf_table"
    JSON_API = "json_api"          # Shopify /products.json, B&C _data=
    XLSX = "xlsx"
    INFERRED = "inferred"          # driver_kind from category slug
    DERIVED = "derived"            # xmech doubled from labelled one-way


# Best-first ordering when a field appears in multiple fragments. INLINE_JS
# is ranked ABOVE the HTML variants because it's typically the same
# structured payload the HTML view is derived from server-side.
SPEC_SOURCE_PRECEDENCE: list[SpecSource] = [
    SpecSource.JSON_API,
    SpecSource.XLSX,
    SpecSource.INLINE_JS,
    SpecSource.PDF_TABLE,
    SpecSource.PDF_TEXT,
    SpecSource.HTML_TABLE,
    SpecSource.HTML_GRID,
    SpecSource.HTML_DIV_PAIRS,
    SpecSource.HTML_PROSE,
    SpecSource.DERIVED,
    SpecSource.INFERRED,
]


@dataclass
class DriverFragment:
    """A partial Driver, one per parsed artifact. Merged post-parse by canonical_id.

    Field ordering follows dataclass rules (mandatory fields precede fields with
    defaults). `model` is mandatory — no scraper may emit a fragment without one.
    `driver_kind` may be None at parse time and resolved via
    Scraper.classify_driver_kind() before merge.
    """

    manufacturer: str
    source_url: str
    fetched_at: str
    driver_kind: Optional[DriverKind]
    model: str

    spec_source: dict[str, SpecSource] = field(default_factory=dict)

    # Identity
    canonical_id_seed: Optional[str] = None    # e.g. Celestion post-id, RCF productCode
    canonical_id: Optional[str] = None         # assigned post-merge

    # T/S parameters
    fs_hz: Optional[float] = None
    qts: Optional[float] = None
    qes: Optional[float] = None
    qms: Optional[float] = None
    vas_liters: Optional[float] = None
    mms_g: Optional[float] = None
    cms_mm_per_n: Optional[float] = None
    rms_ns_per_m: Optional[float] = None
    bl_tm: Optional[float] = None
    re_ohm: Optional[float] = None
    le_mh: Optional[float] = None              # canonical: Le at 1 kHz
    sd_cm2: Optional[float] = None
    eta_zero_pct: Optional[float] = None
    ebp_hz: Optional[float] = None

    # Physical / mechanical
    xmax_mm: Optional[float] = None            # one-way linear excursion
    xmech_mm: Optional[float] = None           # peak-to-peak by convention
    voice_coil_diameter_mm: Optional[float] = None
    voice_coil_layers: Optional[int] = None
    overall_diameter_mm: Optional[float] = None
    mounting_diameter_mm: Optional[float] = None
    depth_mm: Optional[float] = None
    net_weight_kg: Optional[float] = None
    magnet_type: Optional[MagnetType] = None

    # Electrical
    impedance_nominal_ohm: Optional[float] = None
    impedance_min_ohm: Optional[float] = None

    # Power. See per_manufacturer_strategy for scraper label→field mappings.
    # `power.derive_missing_power` fills these post-parse:
    #   - `power_program_watts` ↔ `power_aes_watts` at 2× per AES standard
    #   - `power_long_term_watts` = `power_aes_watts` when long_term is empty
    #     (AES is a 2h continuous test; mfgs that don't publish a distinct
    #     longer-duration rating effectively treat AES as their continuous
    #     rating). Manufacturers that DO publish a distinct larger continuous
    #     number (18Sound, B&C, Celestion) have this slot populated
    #     directly and the derivation is a no-op.
    power_aes_watts: Optional[float] = None
    power_program_watts: Optional[float] = None
    power_long_term_watts: Optional[float] = None
    power_peak_watts: Optional[float] = None
    power_eia_watts: Optional[float] = None

    # Frequency
    freq_low_hz: Optional[float] = None
    freq_high_hz: Optional[float] = None
    fs_diaphragm_hz: Optional[float] = None    # compression-driver diaphragm Fs

    # Sensitivity — both slots may be populated; slot chosen per manufacturer
    sensitivity_db_1w_1m: Optional[float] = None
    sensitivity_db_2_83v_1m: Optional[float] = None

    # Commercial (thin in v1; retailers land in v2 with a price_history sidecar)
    msrp_currency: Optional[str] = None
    msrp_amount: Optional[float] = None

    # Nominal size
    nominal_size_mm: Optional[float] = None

    # Coax HF-section fields — populated only for `driver_kind = COAX`. The
    # generic fields above hold the coax LF-section values (that's the primary
    # usable range); these carry the HF section's rating. Same pattern will be
    # used for future multi-section speaker kinds — see docs/tasks.md.
    coax_hf_impedance_nominal_ohm: Optional[float] = None
    coax_hf_impedance_min_ohm: Optional[float] = None
    coax_hf_power_aes_watts: Optional[float] = None
    coax_hf_power_peak_watts: Optional[float] = None
    coax_hf_sensitivity_db_1w_1m: Optional[float] = None
    coax_hf_freq_low_hz: Optional[float] = None
    coax_hf_freq_high_hz: Optional[float] = None
    coax_hf_voice_coil_diameter_mm: Optional[float] = None
    coax_hf_re_ohm: Optional[float] = None

    status: DriverStatus = DriverStatus.ACTIVE

    # Diagnostics
    warn_flags: list[str] = field(default_factory=list)
    raw_identity_strings: list[str] = field(default_factory=list)


@dataclass
class Driver:
    """Post-merge, post-consistency-check record. Written to drivers.json.

    Same fields as DriverFragment PLUS:
     - canonical_id: MANDATORY (REJECT if None post-merge)
     - driver_kind: MANDATORY (Fragment.driver_kind=None must be resolved via
       Scraper.classify_driver_kind() before merge)
     - source_urls (plural): every artifact that contributed
     - fetched_at: latest across contributing fragments
     - scraped_at: stable across preserved runs
     - last_scraped_at: bumped every run
    """

    manufacturer: str
    canonical_id: str
    driver_kind: DriverKind
    model: str
    spec_source: dict[str, SpecSource]
    source_urls: list[str]
    fetched_at: str
    scraped_at: str
    last_scraped_at: str
    status: DriverStatus
    warn_flags: list[str]

    # All Fragment spec fields inlined here.
    fs_hz: Optional[float] = None
    qts: Optional[float] = None
    qes: Optional[float] = None
    qms: Optional[float] = None
    vas_liters: Optional[float] = None
    mms_g: Optional[float] = None
    cms_mm_per_n: Optional[float] = None
    rms_ns_per_m: Optional[float] = None
    bl_tm: Optional[float] = None
    re_ohm: Optional[float] = None
    le_mh: Optional[float] = None
    sd_cm2: Optional[float] = None
    eta_zero_pct: Optional[float] = None
    ebp_hz: Optional[float] = None

    xmax_mm: Optional[float] = None
    xmech_mm: Optional[float] = None
    voice_coil_diameter_mm: Optional[float] = None
    voice_coil_layers: Optional[int] = None
    overall_diameter_mm: Optional[float] = None
    mounting_diameter_mm: Optional[float] = None
    depth_mm: Optional[float] = None
    net_weight_kg: Optional[float] = None
    magnet_type: Optional[MagnetType] = None

    impedance_nominal_ohm: Optional[float] = None
    impedance_min_ohm: Optional[float] = None

    power_aes_watts: Optional[float] = None
    power_program_watts: Optional[float] = None
    power_long_term_watts: Optional[float] = None
    power_peak_watts: Optional[float] = None
    power_eia_watts: Optional[float] = None

    freq_low_hz: Optional[float] = None
    freq_high_hz: Optional[float] = None
    fs_diaphragm_hz: Optional[float] = None

    sensitivity_db_1w_1m: Optional[float] = None
    sensitivity_db_2_83v_1m: Optional[float] = None

    msrp_currency: Optional[str] = None
    msrp_amount: Optional[float] = None

    nominal_size_mm: Optional[float] = None

    # Coax HF section — see DriverFragment for docstring.
    coax_hf_impedance_nominal_ohm: Optional[float] = None
    coax_hf_impedance_min_ohm: Optional[float] = None
    coax_hf_power_aes_watts: Optional[float] = None
    coax_hf_power_peak_watts: Optional[float] = None
    coax_hf_sensitivity_db_1w_1m: Optional[float] = None
    coax_hf_freq_low_hz: Optional[float] = None
    coax_hf_freq_high_hz: Optional[float] = None
    coax_hf_voice_coil_diameter_mm: Optional[float] = None
    coax_hf_re_ohm: Optional[float] = None
