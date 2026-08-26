"""Cross-field consistency gates. Post-merge REJECTs the WHOLE record.

Single-field REJECTs (null the field only, keep the record) live in `sanity.py`.
This module raises `ParseConsistencyFailure` for records that fail an
inter-field invariant, and adds `warn_flags` for anomalies that pass through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from driver_base.interface import DriverKind
from driver_base.model import Driver


class ParseConsistencyFailure(Exception):
    """Raised for a record that violates a cross-field invariant."""


@dataclass
class RejectedDriver:
    driver: Driver
    reason: str


# Manufacturers whose reported Xdamage / xmech_mm is ONE-WAY, not peak-to-peak.
# The `xmech ≥ 1.9 * xmax` gate assumes p-p and is meaningless for one-way values
# (both are then in the same units, and Xdamage typically sits 1.5–2× Xmax — well
# under 1.9). Skip the gate for these manufacturers. This is an ASSUMPTION we're
# tracking — see docs/tasks.md "surface per-manufacturer assumptions".
_XMECH_ONE_WAY_MANUFACTURERS: frozenset[str] = frozenset({"Faital Pro"})


_MIN_BANDWIDTH_HZ: dict[DriverKind, float] = {
    DriverKind.LF_WOOFER: 500.0,
    DriverKind.FULLRANGE: 500.0,
    DriverKind.COAX: 500.0,
    DriverKind.HF_COMPRESSION: 1000.0,
    DriverKind.TWEETER: 1000.0,
    DriverKind.HORN: 100.0,
    DriverKind.PASSIVE: 10.0,
    DriverKind.SHAKER: 10.0,
    DriverKind.GUITAR_BASS: 100.0,
}


def enforce_consistency(
    drivers: list[Driver],
) -> tuple[list[Driver], list[RejectedDriver]]:
    """Run cross-field REJECT gates. Kept records get WARN flags for anomalies."""
    kept: list[Driver] = []
    rejected: list[RejectedDriver] = []
    for d in drivers:
        try:
            _hard_gates(d)
            _soft_warns(d)
            kept.append(d)
        except ParseConsistencyFailure as e:
            rejected.append(RejectedDriver(driver=d, reason=str(e)))
    return kept, rejected


def _hard_gates(d: Driver) -> None:
    if not d.canonical_id:
        raise ParseConsistencyFailure("canonical_id is empty")
    if not d.model:
        raise ParseConsistencyFailure("model is empty")

    if (
        d.xmech_mm is not None
        and d.xmax_mm is not None
        and d.manufacturer not in _XMECH_ONE_WAY_MANUFACTURERS
    ):
        if d.xmech_mm < 1.9 * d.xmax_mm:
            raise ParseConsistencyFailure(
                f"xmech_under_doubling: {d.xmech_mm} < 1.9*{d.xmax_mm}"
            )

    # Nominal impedance is a rating bin (4/8/16 Ω), not a physical maximum, so
    # min impedance can legitimately sit slightly above nominal (Faital HF drivers
    # routinely publish 8.1–8.4 Ω min on an 8 Ω nominal). Gate removed 2026-08-25.

    if d.power_aes_watts is not None:
        for field_name in (
            "power_long_term_watts",
            "power_peak_watts",
            "power_program_watts",
        ):
            v = getattr(d, field_name)
            if v is not None and v < d.power_aes_watts - 0.05:
                raise ParseConsistencyFailure(
                    f"{field_name}<aes: {v}<{d.power_aes_watts}"
                )

    if d.freq_low_hz is not None and d.freq_high_hz is not None:
        min_bw = _MIN_BANDWIDTH_HZ.get(d.driver_kind, 100.0)
        if d.freq_high_hz < d.freq_low_hz + min_bw:
            raise ParseConsistencyFailure(
                f"bandwidth_too_narrow_for_{d.driver_kind.value}: "
                f"{d.freq_low_hz}->{d.freq_high_hz} < +{min_bw}"
            )


def _soft_warns(d: Driver) -> None:
    if d.xmech_mm and d.xmax_mm and d.xmech_mm / d.xmax_mm > 6.0:
        d.warn_flags.append(
            f"xmech_xmax_ratio_high:{d.xmech_mm}/{d.xmax_mm}"
        )

    if (
        d.sensitivity_db_1w_1m is not None
        and d.sensitivity_db_2_83v_1m is not None
        and d.impedance_nominal_ohm is not None
        and d.impedance_nominal_ohm > 0
    ):
        expected_2_83 = d.sensitivity_db_1w_1m + 10.0 * math.log10(
            8.0 / d.impedance_nominal_ohm
        )
        if abs(d.sensitivity_db_2_83v_1m - expected_2_83) > 1.5:
            d.warn_flags.append(
                f"sensitivity_inconsistent:{d.sensitivity_db_2_83v_1m}vs{expected_2_83:.2f}"
            )

    if d.driver_kind in {
        DriverKind.LF_WOOFER,
        DriverKind.FULLRANGE,
        DriverKind.COAX,
    } and d.driver_kind is not DriverKind.GUITAR_BASS:
        if d.fs_hz is None or all(getattr(d, q) is None for q in ("qts", "qes", "qms")):
            d.warn_flags.append("missing_ts_for_expected_kind")
