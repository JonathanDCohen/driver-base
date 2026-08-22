"""RCF enumerate + parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.rcf import RcfScraper
from tests.conftest import load_fixture


_LF18N401_URL = "https://www.rcf.it/en/products/product-detail/lf18n401"


@pytest.fixture
def scraper() -> RcfScraper:
    return RcfScraper()


def test_discover_seeds_covers_six_series(scraper: RcfScraper) -> None:
    seeds = scraper.discover_seeds()
    assert len(seeds) == 6                # excludes serieId=14 (Custom Designs)
    for s in seeds:
        assert "serieId=" in s.url
        assert s.context.driver_kind_hint is not None


def test_enumerate_serieid_51_neodymium_lf(scraper: RcfScraper) -> None:
    seed = load_fixture(
        "rcf", "seeds/serieId-51.html",
        url="https://www.rcf.it/en/search-results?serieId=51",
    )
    res = scraper.enumerate([seed])
    assert len(res.product_urls) >= 15    # 23 observed on 2026-08-22
    assert all(p.context.driver_kind_hint == DriverKind.LF_WOOFER for p in res.product_urls)
    assert all("/en/products/product-detail/" in p.url for p in res.product_urls)


def test_parse_lf18n401(scraper: RcfScraper) -> None:
    raw = load_fixture("rcf", "products/lf18n401.html", url=_LF18N401_URL)
    res = scraper.parse_artifact(
        raw, SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, series="51", category_id="51"),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "RCF"
    assert f.model == "LF18N401"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S — RCF stores unit tokens in the VALUE ("6.50 Qms"); parse_float ignores trailing text
    assert f.fs_hz == pytest.approx(32.0)
    assert f.qms == pytest.approx(6.5)
    assert f.qes == pytest.approx(0.27)
    assert f.qts == pytest.approx(0.26)
    assert f.vas_liters == pytest.approx(257.0)
    assert f.sd_cm2 == pytest.approx(1200.0)   # from '0.120 m2'
    assert f.xmax_mm == pytest.approx(9.0)
    assert f.xmech_mm == pytest.approx(52.0)   # 'Max. Excursion Before Damage' PP as-reported
    assert f.mms_g == pytest.approx(201.0)
    assert f.bl_tm == pytest.approx(27.8)      # '27.80 T x m'
    assert f.re_ohm == pytest.approx(5.1)
    assert f.le_mh == pytest.approx(2.5)
    assert f.eta_zero_pct == pytest.approx(3.01)

    # Sensitivity → 1W/1m per RCF convention
    assert f.sensitivity_db_1w_1m == pytest.approx(98.0)

    # Electrical + power (Program > AES per RCF convention)
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.3)
    assert f.power_program_watts == pytest.approx(2400.0)
    assert f.power_aes_watts == pytest.approx(1200.0)

    # Range
    assert f.freq_low_hz == pytest.approx(30.0)
    assert f.freq_high_hz == pytest.approx(1000.0)

    # Physical + magnet
    assert f.nominal_size_mm == pytest.approx(457.0)
    assert f.voice_coil_diameter_mm == pytest.approx(102.0)
    assert f.overall_diameter_mm == pytest.approx(465.0)
    assert f.mounting_diameter_mm == pytest.approx(424.0)
    assert f.net_weight_kg == pytest.approx(9.5)
    assert f.magnet_type == MagnetType.NEODYMIUM

    assert f.spec_source["fs_hz"] == SpecSource.HTML_DIV_PAIRS
