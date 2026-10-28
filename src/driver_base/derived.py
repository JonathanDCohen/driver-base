"""Derived spec fields: Vd (peak displacement volume) and EBP (efficiency
bandwidth product).

Both fill in from other T/S parameters. Neither is a "listed" spec by
convention, though EBP is published directly by some manufacturers
(18Sound, B&C, Eminence, Faital, HOQS) — for them the scraper populates
`ebp_hz` from the source, and `derive_ebp` no-ops. Same "listed wins over
derived" precedence as `power.py` and `sensitivity.py`.
"""

from __future__ import annotations

from driver_base.model import DriverFragment, SpecSource


def derive_vd(fragment: DriverFragment) -> None:
    """Vd = Sd × Xmax (one-way peak displacement volume), stored in liters.

    sd_cm2·mm = 0.1 cm³ = 0.0001 L, so multiplier is 1/10000. No-op if
    either input is missing or vd_liters is already populated (no scraper
    emits it today, but the check keeps the "listed wins" pattern).
    """
    if fragment.vd_liters is not None:
        return
    if fragment.sd_cm2 is None or fragment.xmax_mm is None:
        return
    fragment.vd_liters = round(fragment.sd_cm2 * fragment.xmax_mm / 10000, 4)
    fragment.spec_source["vd_liters"] = SpecSource.DERIVED


def derive_ebp(fragment: DriverFragment) -> None:
    """EBP = Fs / Qes. Dimensionless-by-convention; units are technically Hz
    hence the `_hz` suffix on the field.

    No-op if the scraper already emitted a listed value, or if either input
    is missing. Qes ≤ 0 is treated as missing (defensive against bad data).
    """
    if fragment.ebp_hz is not None:
        return
    if fragment.fs_hz is None or fragment.qes is None or fragment.qes <= 0:
        return
    fragment.ebp_hz = round(fragment.fs_hz / fragment.qes, 1)
    fragment.spec_source["ebp_hz"] = SpecSource.DERIVED
