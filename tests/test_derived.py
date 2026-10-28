"""derive_vd and derive_ebp: Vd = Sd × Xmax, EBP = Fs / Qes."""

from __future__ import annotations

import pytest

from driver_base.derived import derive_ebp, derive_vd
from driver_base.interface import DriverKind
from driver_base.model import DriverFragment, SpecSource


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


# --- derive_vd ---------------------------------------------------------------


def test_derive_vd_from_sd_and_xmax() -> None:
    # 350 cm² × 8 mm = 2800 cm³·mm/10000 = 0.28 L
    f = _frag(sd_cm2=350.0, xmax_mm=8.0)
    derive_vd(f)
    assert f.vd_liters == pytest.approx(0.28)
    assert f.spec_source["vd_liters"] == SpecSource.DERIVED


def test_derive_vd_no_op_when_sd_missing() -> None:
    f = _frag(xmax_mm=8.0)
    derive_vd(f)
    assert f.vd_liters is None
    assert "vd_liters" not in f.spec_source


def test_derive_vd_no_op_when_xmax_missing() -> None:
    f = _frag(sd_cm2=350.0)
    derive_vd(f)
    assert f.vd_liters is None


def test_derive_vd_preserves_existing() -> None:
    """Nothing scrapes vd_liters today, but the guard keeps the pattern."""
    f = _frag(sd_cm2=350.0, xmax_mm=8.0, vd_liters=0.30)
    derive_vd(f)
    assert f.vd_liters == pytest.approx(0.30)
    assert "vd_liters" not in f.spec_source


# --- derive_ebp --------------------------------------------------------------


def test_derive_ebp_from_fs_and_qes() -> None:
    f = _frag(fs_hz=45.0, qes=0.30)
    derive_ebp(f)
    assert f.ebp_hz == pytest.approx(150.0)
    assert f.spec_source["ebp_hz"] == SpecSource.DERIVED


def test_derive_ebp_preserves_scraped_value() -> None:
    """When the mfg publishes EBP directly (18Sound, B&C, Eminence, Faital,
    HOQS), the derivation must NOT overwrite it."""
    f = _frag(fs_hz=45.0, qes=0.30, ebp_hz=138.0)
    derive_ebp(f)
    assert f.ebp_hz == pytest.approx(138.0)
    assert "ebp_hz" not in f.spec_source


def test_derive_ebp_no_op_when_qes_missing() -> None:
    f = _frag(fs_hz=45.0)
    derive_ebp(f)
    assert f.ebp_hz is None


def test_derive_ebp_no_op_when_fs_missing() -> None:
    f = _frag(qes=0.30)
    derive_ebp(f)
    assert f.ebp_hz is None


def test_derive_ebp_no_op_when_qes_is_zero() -> None:
    """Defensive against bad data — a zero Qes would divide by zero."""
    f = _frag(fs_hz=45.0, qes=0.0)
    derive_ebp(f)
    assert f.ebp_hz is None
