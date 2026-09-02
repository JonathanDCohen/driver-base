"""Sensitivity slot conversion — derive the missing 1W/1m or 2.83V/1m value
from whichever the manufacturer published + the driver's nominal impedance.

Physics: `db_2_83v_1m = db_1w_1m + 10 · log10(8 / Z_nom)`

  Z_nom (Ω)   offset (dB, 2.83V − 1W)
  --------   ------------------------
      2               +6.02
      4               +3.01
      6               +1.25
      8                0.00
     16               −3.01

Manufacturers' conventions:
  1 W / 1 m   18Sound, Beyma, Celestion, Eminence, Faital, Jensen, RCF
  2.83 V / 1 m   B&C (per product-page tooltip), Dayton (`@ 2.83V/1m` label
                 on values), HOQS (`SPL (Sensitivity 2.83Vrms)` label)

We ALWAYS derive the missing slot when impedance is known — the SPA can then
sort/filter on `sensitivity_db_1w_1m` consistently across the whole catalog.
The derived value is tagged `SpecSource.DERIVED` so consumers can tell it
apart from a manufacturer-published number.
"""

from __future__ import annotations

import math

from driver_base.model import DriverFragment, SpecSource


def _round1(x: float) -> float:
    return round(x, 1)


def derive_missing_sensitivity(fragment: DriverFragment) -> None:
    """In-place: populate whichever sensitivity slot is missing, given the
    other slot and impedance. No-op if impedance is unknown, both slots are
    populated, or both are empty."""
    Z = fragment.impedance_nominal_ohm
    if Z is None or Z <= 0:
        return

    have_1w = fragment.sensitivity_db_1w_1m is not None
    have_283 = fragment.sensitivity_db_2_83v_1m is not None

    offset = 10.0 * math.log10(8.0 / Z)  # 2.83V − 1W

    if have_283 and not have_1w:
        fragment.sensitivity_db_1w_1m = _round1(
            fragment.sensitivity_db_2_83v_1m - offset
        )
        fragment.spec_source["sensitivity_db_1w_1m"] = SpecSource.DERIVED
    elif have_1w and not have_283:
        fragment.sensitivity_db_2_83v_1m = _round1(
            fragment.sensitivity_db_1w_1m + offset
        )
        fragment.spec_source["sensitivity_db_2_83v_1m"] = SpecSource.DERIVED
