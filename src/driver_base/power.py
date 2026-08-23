"""Power-handling derivation.

The AES 2-1984 standard defines program power as **2 × AES rated power**.
When one is published but not the other, we compute the missing slot and tag
`spec_source[...] = SpecSource.DERIVED`.

Long-term / peak / EIA values are NOT derived — their ratios to AES vary by
manufacturer (18Sound Continuous ≈ 1.4×, Faital Max ≈ 2×, Dayton Max ≈ 2×,
some peak conventions go 4×+). Deriving them would produce plausible-looking
but wrong numbers.
"""

from __future__ import annotations

from driver_base.model import DriverFragment, SpecSource


def derive_missing_power(fragment: DriverFragment) -> None:
    """Fill the AES↔Program relationship at 2× per AES standard.
    No-op if both slots are populated or neither is."""
    aes = fragment.power_aes_watts
    program = fragment.power_program_watts
    if aes is not None and program is None:
        fragment.power_program_watts = round(2.0 * aes, 1)
        fragment.spec_source["power_program_watts"] = SpecSource.DERIVED
    elif program is not None and aes is None:
        fragment.power_aes_watts = round(program / 2.0, 1)
        fragment.spec_source["power_aes_watts"] = SpecSource.DERIVED
