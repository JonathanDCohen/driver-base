"""LaVoce parse_artifact + enumerate against captured fixtures.

Values below were cross-checked against the live product pages at
https://lavocespeakers.com/product/<slug>/ on 2026-11-05.
"""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.lavoce import LaVoceScraper
from tests.conftest import load_fixture


@pytest.fixture
def scraper() -> LaVoceScraper:
    return LaVoceScraper()


def test_enumerate_sitemap(scraper: LaVoceScraper) -> None:
    seed = load_fixture(
        "lavoce",
        "seeds/products-sitemap.xml",
        url="https://lavocespeakers.com/products-sitemap.xml",
    )
    res = scraper.enumerate([seed])
    # sitemap captured 2026-11-05 lists 276 English product URLs
    assert len(res.product_urls) >= 200
    # Spot-check a known URL is present and non-English variants are filtered
    urls = {p.url for p in res.product_urls}
    assert "https://lavocespeakers.com/product/icf061-00/" in urls
    assert not any("/zh/" in u for u in urls)


def test_parse_icf061_coaxial(scraper: LaVoceScraper) -> None:
    """2-way weather-resistant coaxial. Tests the kHz-tail frequency range
    parse (`70 ÷ 22kHz` → low=70 Hz, high=22 kHz) and breadcrumb classification
    of "Weather Resistant Coaxials" → COAX."""
    raw = load_fixture(
        "lavoce",
        "products/icf061.html",
        url="https://lavocespeakers.com/product/icf061-00/",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1 and res.followups == []
    f = res.fragments[0]

    assert f.manufacturer == "LaVoce"
    assert f.model == "ICF061.00"
    assert f.driver_kind == DriverKind.COAX

    assert f.impedance_nominal_ohm == pytest.approx(6.0)
    assert f.impedance_min_ohm == pytest.approx(5.1)
    assert f.power_aes_watts == pytest.approx(50.0)
    assert f.power_program_watts == pytest.approx(100.0)
    assert f.sensitivity_db_1w_1m == pytest.approx(86.0)
    # The kHz-tail range parse: 70 Hz low, 22 kHz high.
    assert f.freq_low_hz == pytest.approx(70.0)
    assert f.freq_high_hz == pytest.approx(22000.0)
    assert f.voice_coil_diameter_mm == pytest.approx(25.0)
    assert f.nominal_size_mm == pytest.approx(165.0)
    assert f.magnet_type == MagnetType.CERAMIC

    # Small-signal parameters populate
    assert f.re_ohm == pytest.approx(4.9)
    assert f.sd_cm2 == pytest.approx(122.7)
    assert f.fs_hz == pytest.approx(60.0)
    assert f.bl_tm == pytest.approx(5.3)
    assert f.vas_liters == pytest.approx(10.7)
    assert f.qts == pytest.approx(0.75)
    assert f.le_mh == pytest.approx(0.32)

    # Xmax / Xmech are stored as-reported (both one-way per LaVoce)
    assert f.xmax_mm == pytest.approx(3.4)
    assert f.xmech_mm == pytest.approx(4.8)

    # Construction materials propagate
    assert f.winding_material == "COPPER"
    assert f.former_material == "POLYIMIDE"

    # spec_source tagged HTML_DIV_PAIRS
    assert f.spec_source["fs_hz"] == SpecSource.HTML_DIV_PAIRS
    assert f.spec_source["sensitivity_db_1w_1m"] == SpecSource.HTML_DIV_PAIRS


def test_parse_wsn122_lf_woofer(scraper: LaVoceScraper) -> None:
    """12" neodymium LF transducer — full T/S set populated."""
    raw = load_fixture(
        "lavoce",
        "products/wsn122_50_3.html",
        url="https://lavocespeakers.com/product/wsn122-50-3/",
    )
    f = scraper.parse_artifact(raw, SeedContext()).fragments[0]

    assert f.model == "WSN122.50-16"
    assert f.driver_kind == DriverKind.LF_WOOFER
    assert f.impedance_nominal_ohm == pytest.approx(16.0)
    assert f.impedance_min_ohm == pytest.approx(14.2)
    assert f.power_aes_watts == pytest.approx(250.0)
    assert f.power_program_watts == pytest.approx(500.0)
    assert f.sensitivity_db_1w_1m == pytest.approx(96.5)
    assert f.freq_low_hz == pytest.approx(50.0)
    assert f.freq_high_hz == pytest.approx(3000.0)
    assert f.nominal_size_mm == pytest.approx(300.0)
    assert f.magnet_type == MagnetType.NEODYMIUM

    # T/S
    assert f.fs_hz == pytest.approx(53.0)
    assert f.qts == pytest.approx(0.4)
    assert f.qes == pytest.approx(0.45)
    assert f.qms == pytest.approx(3.88)
    assert f.vas_liters == pytest.approx(65.84)
    assert f.mms_g == pytest.approx(54.7)
    assert f.bl_tm == pytest.approx(23.03)
    assert f.re_ohm == pytest.approx(13.1)
    assert f.le_mh == pytest.approx(1.4)
    assert f.sd_cm2 == pytest.approx(531.0)
    assert f.eta_zero_pct == pytest.approx(2.09)
    assert f.ebp_hz == pytest.approx(118.0)
    assert f.cms_mm_per_n == pytest.approx(0.165)

    # Vd and recommended enclosure propagate
    assert f.vd_liters == pytest.approx(1.6)
    assert f.recommended_enclosure_volume_liters == pytest.approx(39.6)

    assert f.xmax_mm == pytest.approx(4.6)
    assert f.xmech_mm == pytest.approx(8.7)


def test_parse_df20_compression_driver(scraper: LaVoceScraper) -> None:
    """Ferrite HF compression driver — no T/S, HF_COMPRESSION kind."""
    raw = load_fixture(
        "lavoce",
        "products/df20_30t_2.html",
        url="https://lavocespeakers.com/product/df20-30t-2/",
    )
    f = scraper.parse_artifact(raw, SeedContext()).fragments[0]

    assert f.model == "DF20.30T-16"
    assert f.driver_kind == DriverKind.HF_COMPRESSION
    assert f.impedance_nominal_ohm == pytest.approx(16.0)
    assert f.power_aes_watts == pytest.approx(110.0)
    assert f.power_program_watts == pytest.approx(220.0)
    assert f.sensitivity_db_1w_1m == pytest.approx(107.5)
    assert f.freq_low_hz == pytest.approx(500.0)
    assert f.freq_high_hz == pytest.approx(18000.0)
    assert f.voice_coil_diameter_mm == pytest.approx(75.0)
    assert f.magnet_type == MagnetType.CERAMIC
    assert f.surround_material == "TITANIUM"
    # HF compression drivers lack T/S — expected
    assert f.fs_hz is None
    assert f.qts is None
