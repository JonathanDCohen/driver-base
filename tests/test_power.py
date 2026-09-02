"""derive_missing_power: AES ↔ Program at 2× per AES standard."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind
from driver_base.model import DriverFragment, SpecSource
from driver_base.power import derive_missing_power


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


def test_derive_program_from_aes() -> None:
    f = _frag(power_aes_watts=250.0)
    derive_missing_power(f)
    assert f.power_program_watts == pytest.approx(500.0)
    assert f.spec_source["power_program_watts"] == SpecSource.DERIVED


def test_derive_aes_from_program() -> None:
    f = _frag(power_program_watts=1000.0)
    derive_missing_power(f)
    assert f.power_aes_watts == pytest.approx(500.0)
    assert f.spec_source["power_aes_watts"] == SpecSource.DERIVED


def test_no_op_when_both_populated() -> None:
    """A manufacturer that publishes both must be trusted (may not be exactly 2×)."""
    f = _frag(power_aes_watts=100.0, power_program_watts=250.0)
    derive_missing_power(f)
    assert f.power_aes_watts == pytest.approx(100.0)
    assert f.power_program_watts == pytest.approx(250.0)
    assert "power_aes_watts" not in f.spec_source
    assert "power_program_watts" not in f.spec_source


def test_no_op_when_neither_populated() -> None:
    f = _frag()
    derive_missing_power(f)
    assert f.power_aes_watts is None
    assert f.power_program_watts is None


def test_derives_long_term_from_aes_when_missing() -> None:
    """AES is a continuous test — when the mfg doesn't publish a separately-
    tested long-term number, use AES as the continuous rating."""
    f = _frag(power_aes_watts=300.0)
    derive_missing_power(f)
    assert f.power_long_term_watts == pytest.approx(300.0)
    assert f.spec_source["power_long_term_watts"] == SpecSource.DERIVED


def test_does_not_overwrite_manufacturer_long_term() -> None:
    """When a mfg publishes a distinct larger continuous rating (18Sound / B&C /
    Celestion), the derivation must NOT overwrite it."""
    f = _frag(power_aes_watts=1000.0, power_long_term_watts=1400.0)
    derive_missing_power(f)
    assert f.power_long_term_watts == pytest.approx(1400.0)
    assert "power_long_term_watts" not in f.spec_source  # not derived — preserved


def test_derives_long_term_from_program_via_aes() -> None:
    """When only Program is published, we derive AES first, then long_term."""
    f = _frag(power_program_watts=1000.0)  # → aes 500 → long_term 500
    derive_missing_power(f)
    assert f.power_aes_watts == pytest.approx(500.0)
    assert f.power_long_term_watts == pytest.approx(500.0)
    assert f.spec_source["power_aes_watts"] == SpecSource.DERIVED
    assert f.spec_source["power_long_term_watts"] == SpecSource.DERIVED
