"""18Sound parse_artifact: replays the captured 18LW1400 fixture through the
scraper and asserts every numerical value matches the recon baseline."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.eighteensound import EighteenSoundScraper
from tests.conftest import load_fixture


_18LW1400_URL = "https://www.eighteensound.it/en/products/lf-driver/18-0/8/18LW1400"


@pytest.fixture
def scraper() -> EighteenSoundScraper:
    return EighteenSoundScraper()


def test_parse_18lw1400_extracts_all_ts_fields(scraper: EighteenSoundScraper) -> None:
    raw = load_fixture("eighteensound", "products/18LW1400.html", url=_18LW1400_URL)
    ctx = SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="lf-driver")
    res = scraper.parse_artifact(raw, ctx)

    assert len(res.fragments) == 1 and res.followups == []
    f = res.fragments[0]

    # identity
    assert f.manufacturer == "18Sound"
    assert f.model == "18LW1400"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S values — recon baseline (0.00 % delta at recon time)
    assert f.fs_hz == pytest.approx(31.0)
    assert f.qts == pytest.approx(0.29)
    assert f.qes == pytest.approx(0.31)
    assert f.qms == pytest.approx(7.2)
    assert f.vas_liters == pytest.approx(297.0)
    assert f.sd_cm2 == pytest.approx(1225.0)
    assert f.xmax_mm == pytest.approx(9.0)
    assert f.mms_g == pytest.approx(190.0)
    assert f.bl_tm == pytest.approx(24.7)
    assert f.le_mh == pytest.approx(2.3)
    assert f.re_ohm == pytest.approx(5.0)
    assert f.ebp_hz == pytest.approx(100.0)

    # electrical / sensitivity / power
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.4)
    assert f.sensitivity_db_1w_1m == pytest.approx(98.0)
    assert f.power_aes_watts == pytest.approx(1000.0)
    assert f.power_long_term_watts == pytest.approx(1400.0)

    # frequency range
    assert f.freq_low_hz == pytest.approx(28.0)
    assert f.freq_high_hz == pytest.approx(2500.0)

    # physical
    assert f.nominal_size_mm == pytest.approx(460.0)
    assert f.voice_coil_diameter_mm == pytest.approx(100.0)
    assert f.overall_diameter_mm == pytest.approx(462.0)
    assert f.mounting_diameter_mm == pytest.approx(416.0)
    assert f.depth_mm == pytest.approx(215.0)
    assert f.net_weight_kg == pytest.approx(13.3)

    # coerced magnet enum
    assert f.magnet_type == MagnetType.CERAMIC

    # every populated field has a spec_source recorded
    for field_name in (
        "fs_hz",
        "qts",
        "vas_liters",
        "xmax_mm",
        "power_aes_watts",
        "power_long_term_watts",
        "sensitivity_db_1w_1m",
        "freq_low_hz",
        "freq_high_hz",
        "magnet_type",
    ):
        assert field_name in f.spec_source
    assert f.spec_source["fs_hz"] == SpecSource.HTML_PROSE


def test_parse_returns_empty_when_url_malformed(scraper: EighteenSoundScraper) -> None:
    raw = load_fixture(
        "eighteensound",
        "products/18LW1400.html",
        url="https://www.eighteensound.it/some/other/path",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert res.fragments == []


def test_impedance_from_url_is_seeded_before_html(
    scraper: EighteenSoundScraper,
) -> None:
    """The scraper seeds impedance from URL then lets HTML override.
    Confirm impedance_nominal_ohm ends up at the HTML value (both are 8 here)."""
    raw = load_fixture("eighteensound", "products/18LW1400.html", url=_18LW1400_URL)
    res = scraper.parse_artifact(raw, SeedContext())
    assert res.fragments[0].impedance_nominal_ohm == pytest.approx(8.0)


def test_size_from_inches_wrapper_beats_url_fallback(
    scraper: EighteenSoundScraper,
) -> None:
    """The 18iD200 product page omits the 'Nominal Diameter' label but the
    header carries the size in <div class="inchesWrapper"><span>18.0</span> In</div>.
    That widget must populate nominal_size_mm with SpecSource.HTML_GRID —
    otherwise the URL-slug fallback stamps SpecSource.INFERRED and the value
    appears as 'inferred' in the UI when the page actually publishes it."""
    url = "https://www.eighteensound.it/en/products/lf-driver/18-0/2/18ID200"
    raw = load_fixture("eighteensound", "products/18ID200.html", url=url)
    ctx = SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="lf-driver")
    res = scraper.parse_artifact(raw, ctx)
    assert len(res.fragments) == 1
    f = res.fragments[0]
    assert f.nominal_size_mm == pytest.approx(457.2)
    assert f.spec_source["nominal_size_mm"] == SpecSource.HTML_GRID
