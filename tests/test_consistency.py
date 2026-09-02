"""Cross-field consistency gate tests."""

from __future__ import annotations

from driver_base.consistency import enforce_consistency
from driver_base.interface import DriverKind
from driver_base.model import Driver, DriverStatus


def _driver(**over):
    defaults = dict(
        manufacturer="X",
        canonical_id="x__m__8ohm",
        driver_kind=DriverKind.LF_WOOFER,
        model="M",
        spec_source={},
        source_urls=[],
        fetched_at="2026-01-01T00:00:00+00:00",
        scraped_at="2026-01-01T00:00:00+00:00",
        last_scraped_at="2026-01-01T00:00:00+00:00",
        status=DriverStatus.ACTIVE,
        warn_flags=[],
    )
    defaults.update(over)
    return Driver(**defaults)


def test_reject_missing_canonical_id() -> None:
    d = _driver(canonical_id="")
    kept, rejected = enforce_consistency([d])
    assert kept == [] and len(rejected) == 1
    assert "canonical_id" in rejected[0].reason


def test_reject_xmech_under_doubling() -> None:
    d = _driver(xmax_mm=10.0, xmech_mm=15.0)  # 15 < 1.9*10=19
    kept, rejected = enforce_consistency([d])
    assert kept == []
    assert "xmech_under_doubling" in rejected[0].reason


def test_accept_xmech_valid_pp() -> None:
    d = _driver(xmax_mm=9.0, xmech_mm=34.0)  # 34 >= 1.9*9=17.1 ✓
    kept, rejected = enforce_consistency([d])
    assert len(kept) == 1 and rejected == []


def test_warn_xmech_ratio_high() -> None:
    d = _driver(xmax_mm=9.0, xmech_mm=60.0)  # 60/9=6.7 > 6 → WARN
    kept, _ = enforce_consistency([d])
    assert len(kept) == 1
    assert any(f.startswith("xmech_xmax_ratio_high") for f in kept[0].warn_flags)


def test_keep_impedance_min_slightly_above_nominal() -> None:
    # Nominal is a rating bin; min > nominal by a fraction is legitimate and
    # published by e.g. Faital HF drivers. Gate removed 2026-08-25.
    d = _driver(impedance_nominal_ohm=8.0, impedance_min_ohm=8.4)
    kept, rejected = enforce_consistency([d])
    assert len(kept) == 1 and not rejected


def test_reject_power_long_term_less_than_aes() -> None:
    d = _driver(power_aes_watts=500.0, power_long_term_watts=400.0)
    _, rejected = enforce_consistency([d])
    assert "power_long_term_watts<aes" in rejected[0].reason


def test_accept_power_long_term_greater_than_aes() -> None:
    d = _driver(power_aes_watts=1000.0, power_long_term_watts=1400.0)
    kept, _ = enforce_consistency([d])
    assert len(kept) == 1


def test_reject_bandwidth_too_narrow_for_lf_woofer() -> None:
    # Subwoofer-focused LFs legitimately have narrow ranges (Celestion FTR12/TSQ
    # series 20–200 Hz); we lowered the LF gate to 100 Hz. Bandwidths under 100 Hz
    # are still parse-error suspicious. Test with 80 Hz bandwidth.
    d = _driver(
        freq_low_hz=100.0, freq_high_hz=180.0
    )  # 80Hz bandwidth < 100 for LF_WOOFER
    _, rejected = enforce_consistency([d])
    assert "bandwidth_too_narrow" in rejected[0].reason


def test_accept_narrow_bandwidth_for_shaker() -> None:
    d = _driver(driver_kind=DriverKind.SHAKER, freq_low_hz=20.0, freq_high_hz=60.0)
    kept, _ = enforce_consistency([d])
    assert len(kept) == 1


def test_warn_missing_ts_for_lf_woofer() -> None:
    d = _driver(fs_hz=None, qts=None, qes=None, qms=None)
    kept, _ = enforce_consistency([d])
    assert len(kept) == 1  # missing T/S is WARN, not REJECT
    assert "missing_ts_for_expected_kind" in kept[0].warn_flags


def test_no_ts_warn_for_hf_compression() -> None:
    d = _driver(
        driver_kind=DriverKind.HF_COMPRESSION, fs_hz=None, qts=None, qes=None, qms=None
    )
    kept, _ = enforce_consistency([d])
    assert "missing_ts_for_expected_kind" not in kept[0].warn_flags
