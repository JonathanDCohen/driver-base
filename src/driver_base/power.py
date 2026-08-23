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
    """Fill missing power slots from what's published:

    1. **program ↔ aes** at 2× per AES standard (bidirectional).
    2. **long_term = aes** when only AES is published. Rationale: the AES
       2-hour pink-noise test IS a continuous test. Manufacturers who don't
       publish a separately-tested longer-duration rating (Beyma, Dayton,
       Eminence, Faital, HOQS, Jensen, RCF) effectively treat AES as their
       continuous rating. Manufacturers who DO publish a distinct larger
       continuous number (18Sound, B&C, Celestion) have `long_term` already
       populated, and this branch is a no-op for them.

    No-op when the source slot is missing or the target is already populated.
    """
    aes = fragment.power_aes_watts
    program = fragment.power_program_watts

    # program ↔ aes
    if aes is not None and program is None:
        fragment.power_program_watts = round(2.0 * aes, 1)
        fragment.spec_source["power_program_watts"] = SpecSource.DERIVED
    elif program is not None and aes is None:
        fragment.power_aes_watts = round(program / 2.0, 1)
        fragment.spec_source["power_aes_watts"] = SpecSource.DERIVED

    # long_term = aes (only when long_term is empty — never overwrite a
    # manufacturer-published distinct value)
    if fragment.power_aes_watts is not None and fragment.power_long_term_watts is None:
        fragment.power_long_term_watts = fragment.power_aes_watts
        fragment.spec_source["power_long_term_watts"] = SpecSource.DERIVED
