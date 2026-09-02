"""Beyma enumerate + parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.beyma import BeymaScraper
from tests.conftest import load_fixture


_18LEX_URL = "https://www.beyma.com/en/products/c/low-mid-frequency/118LEX16FE8/altavoz-18lex1600fe-8-oh/"


@pytest.fixture
def scraper() -> BeymaScraper:
    return BeymaScraper()


def test_enumerate_low_mid_frequency(scraper: BeymaScraper) -> None:
    seed = load_fixture(
        "beyma",
        "seeds/low-mid-frequency.html",
        url="https://www.beyma.com/en/products/c/low-mid-frequency/",
    )
    res = scraper.enumerate([seed])
    assert len(res.product_urls) >= 60
    assert all(
        p.context.driver_kind_hint == DriverKind.LF_WOOFER for p in res.product_urls
    )
    assert all("/low-mid-frequency/" in p.url for p in res.product_urls)


def test_parse_18lex1600fe(scraper: BeymaScraper) -> None:
    raw = load_fixture("beyma", "products/18LEX1600Fe.html", url=_18LEX_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(
            driver_kind_hint=DriverKind.LF_WOOFER, category_id="low-mid-frequency"
        ),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Beyma"
    assert f.model == "18LEX1600Fe"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S
    assert f.fs_hz == pytest.approx(34.0)
    assert f.qts == pytest.approx(0.38)
    assert f.qes == pytest.approx(0.4)
    assert f.qms == pytest.approx(7.4)
    assert f.vas_liters == pytest.approx(188.0)
    assert f.sd_cm2 == pytest.approx(1255.0)  # from '0.1255 m²'
    assert f.xmax_mm == pytest.approx(13.0)
    assert f.xmech_mm == pytest.approx(60.0)  # "Xdamage pp" AS-REPORTED
    assert f.mms_g == pytest.approx(252.0)  # from '0.252 kg'
    assert f.cms_mm_per_n == pytest.approx(0.085)  # from '85 µm/N'
    assert f.bl_tm == pytest.approx(26.9)  # "26.9 N/A"
    assert f.re_ohm == pytest.approx(5.3)
    assert f.le_mh == pytest.approx(1.7)
    assert f.eta_zero_pct == pytest.approx(1.9)

    # Sensitivity — 1W/1m per label
    assert f.sensitivity_db_1w_1m == pytest.approx(97.0)

    # Power (AES + Program per Beyma convention)
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.1)
    assert f.power_aes_watts == pytest.approx(1600.0)
    assert f.power_program_watts == pytest.approx(3200.0)

    # Range
    assert f.freq_low_hz == pytest.approx(35.0)
    assert f.freq_high_hz == pytest.approx(1000.0)

    # Physical + magnet
    assert f.nominal_size_mm == pytest.approx(460.0)
    assert f.voice_coil_diameter_mm == pytest.approx(101.6)
    assert f.depth_mm == pytest.approx(233.0)
    assert f.net_weight_kg == pytest.approx(14.9)
    assert f.magnet_type == MagnetType.CERAMIC

    assert f.spec_source["fs_hz"] == SpecSource.HTML_DIV_PAIRS
