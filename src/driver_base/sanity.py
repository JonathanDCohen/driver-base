"""Single-field range gates + delta gate.

Single-field REJECT: values outside a physically-plausible range are nulled on
the fragment (the FIELD is dropped; the record is kept). A `warn_flag` is
recorded so ops can see the redaction.

Single-field WARN: unusual-but-plausible values (uncommon impedances, extreme
Fs for a kind) are kept AS-IS with a `warn_flag`.

Delta gate: applied at the scraper level in the orchestrator after merge; see
`check_record_count`.
"""

from __future__ import annotations

from typing import Optional

from driver_base.interface import DriverKind
from driver_base.model import DriverFragment

# Field name → (low, high, inclusive?) for REJECT. Values outside are nulled.
_RANGE_GATES: dict[str, tuple[float, float]] = {
    "fs_hz": (5.0, 5000.0),
    "qts": (0.05, 5.0),
    "qes": (0.05, 5.0),
    "qms": (0.05, 100.0),
    "vas_liters": (0.1, 10000.0),
    "sd_cm2": (0.5, 10000.0),
    "xmax_mm": (0.1, 60.0),
    "xmech_mm": (0.1, 200.0),
    "mms_g": (0.05, 5000.0),
    "bl_tm": (0.5, 100.0),
    "re_ohm": (0.5, 100.0),
    "le_mh": (0.001, 20.0),
    "eta_zero_pct": (0.01, 30.0),
    "voice_coil_diameter_mm": (5.0, 500.0),
    "overall_diameter_mm": (10.0, 900.0),
    "mounting_diameter_mm": (10.0, 900.0),
    "depth_mm": (10.0, 500.0),
    "net_weight_kg": (0.05, 100.0),
    "impedance_nominal_ohm": (1.0, 32.0),
    "impedance_min_ohm": (0.5, 32.0),
    "sensitivity_db_1w_1m": (50.0, 130.0),
    "sensitivity_db_2_83v_1m": (50.0, 130.0),
    "freq_low_hz": (5.0, 10000.0),
    "freq_high_hz": (100.0, 100000.0),
    "power_aes_watts": (0.5, 20000.0),
    "power_program_watts": (0.5, 40000.0),
    "power_long_term_watts": (0.5, 20000.0),
    "power_peak_watts": (0.5, 40000.0),
    "power_eia_watts": (0.5, 20000.0),
    "nominal_size_mm": (10.0, 700.0),
}

# Impedance values that ARE physically plausible but unusual (WARN, keep value).
_COMMON_IMPEDANCES: frozenset[float] = frozenset(
    {2.0, 2.5, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0}
)


def sanity_check_fragment(f: DriverFragment) -> DriverFragment:
    """In-place: null out-of-range values, append warn_flags. Returns f."""
    for field_name, (low, high) in _RANGE_GATES.items():
        val = getattr(f, field_name, None)
        if val is None:
            continue
        if not (low <= val <= high):
            setattr(f, field_name, None)
            f.spec_source.pop(field_name, None)
            f.warn_flags.append(f"range_reject:{field_name}={val!r}")

    imp = f.impedance_nominal_ohm
    if imp is not None and imp not in _COMMON_IMPEDANCES:
        f.warn_flags.append(f"impedance_unusual:{imp}")

    if f.driver_kind == DriverKind.LF_WOOFER and f.fs_hz is not None and f.fs_hz > 100:
        f.warn_flags.append(f"fs_hz_high_for_lf_woofer:{f.fs_hz}")
    if (
        f.driver_kind in (DriverKind.HF_COMPRESSION, DriverKind.TWEETER)
        and f.fs_hz is not None
        and f.fs_hz < 300
    ):
        f.warn_flags.append(f"fs_hz_low_for_hf:{f.fs_hz}")

    return f


def check_record_count(
    *,
    records_this_run: int,
    records_prior_run: Optional[int],
    expected_min_records: int,
    drop_pct_threshold: float = 0.30,
) -> tuple[str, Optional[str]]:
    """Decide whether to accept the run.

    Returns:
      ('ok', None)                                       – accept
      ('preserve', reason)                               – gate failed → preserve prior
    """
    if records_this_run == 0:
        return ("preserve", "zero_records_this_run")
    if records_prior_run is None or records_prior_run == 0:
        if records_this_run < expected_min_records:
            return (
                "preserve",
                f"below_expected_min_records:{records_this_run}<{expected_min_records}",
            )
        return ("ok", None)
    drop = 1.0 - records_this_run / records_prior_run
    if drop > drop_pct_threshold:
        return (
            "preserve",
            f"records_dropped_pct:{drop:.2%}>{drop_pct_threshold:.0%}",
        )
    return ("ok", None)


# convenience for tests / callers
def known_fields() -> list[str]:
    return list(_RANGE_GATES.keys())
