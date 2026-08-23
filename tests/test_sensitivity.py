"""derive_missing_sensitivity: convert between 1W/1m and 2.83V/1m slots."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind
from driver_base.model import DriverFragment, SpecSource
from driver_base.sensitivity import derive_missing_sensitivity


def _frag(**over) -> DriverFragment:
    defaults = dict(
        manufacturer="X",
        source_url="",
        fetched_at="",
        driver_kind=DriverKind.LF_WOOFER,
        model="M",
    )
    defaults.update(over)
    return DriverFragment(**defaults)


def test_derive_1w_from_283v_at_8_ohm_is_identity() -> None:
    f = _frag(impedance_nominal_ohm=8.0, sensitivity_db_2_83v_1m=98.0)
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m == pytest.approx(98.0)
    assert f.spec_source["sensitivity_db_1w_1m"] == SpecSource.DERIVED


def test_derive_1w_from_283v_at_4_ohm_subtracts_3db() -> None:
    """4Ω: 2.83V measurement is +3 dB louder than 1W → 1W = 2.83V − 3."""
    f = _frag(impedance_nominal_ohm=4.0, sensitivity_db_2_83v_1m=97.0)
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m == pytest.approx(94.0, abs=0.05)


def test_derive_1w_from_283v_at_16_ohm_adds_3db() -> None:
    """16Ω: 2.83V measurement is −3 dB quieter than 1W → 1W = 2.83V + 3."""
    f = _frag(impedance_nominal_ohm=16.0, sensitivity_db_2_83v_1m=97.0)
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m == pytest.approx(100.0, abs=0.05)


def test_derive_283v_from_1w_at_4_ohm_adds_3db() -> None:
    f = _frag(impedance_nominal_ohm=4.0, sensitivity_db_1w_1m=94.0)
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(97.0, abs=0.05)
    assert f.spec_source["sensitivity_db_2_83v_1m"] == SpecSource.DERIVED


def test_no_op_when_impedance_unknown() -> None:
    f = _frag(sensitivity_db_2_83v_1m=97.0)   # impedance None
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m is None
    assert "sensitivity_db_1w_1m" not in f.spec_source


def test_no_op_when_both_slots_already_populated() -> None:
    """If a manufacturer publishes both slots we don't touch them."""
    f = _frag(
        impedance_nominal_ohm=8.0,
        sensitivity_db_1w_1m=98.0,
        sensitivity_db_2_83v_1m=99.5,
    )
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m == pytest.approx(98.0)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(99.5)
    assert "sensitivity_db_1w_1m" not in f.spec_source
    assert "sensitivity_db_2_83v_1m" not in f.spec_source


def test_no_op_when_neither_slot_populated() -> None:
    f = _frag(impedance_nominal_ohm=8.0)
    derive_missing_sensitivity(f)
    assert f.sensitivity_db_1w_1m is None
    assert f.sensitivity_db_2_83v_1m is None
