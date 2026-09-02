"""Dayton parse_artifact against captured DC160-8 fixture + discover_seeds."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import SpecSource
from driver_base.scrapers.dayton import DaytonScraper
from tests.conftest import load_fixture


_DC160_URL = "https://www.daytonaudio.com/product/22/dc160-8-6-1-2-classic-woofer-8-ohm"


@pytest.fixture
def scraper() -> DaytonScraper:
    return DaytonScraper()


def test_discover_seeds_covers_12_categories(scraper: DaytonScraper) -> None:
    seeds = scraper.discover_seeds()
    assert len(seeds) == 11  # 12 in _CATEGORIES minus replacement-diaphragms
    assert all(s.url.startswith("https://www.daytonaudio.com/category/") for s in seeds)
    assert all(s.url.endswith("?pagenum=1") for s in seeds)


def test_enumerate_yields_products_and_next_page(scraper: DaytonScraper) -> None:
    seed = load_fixture(
        "dayton",
        "seeds/woofers-p1.html",
        url="https://www.daytonaudio.com/category/118/woofers?pagenum=1",
    )
    res = scraper.enumerate([seed])
    assert len(res.product_urls) == 20  # Dayton serves 20/page
    # Full page → additional_seed_urls carries page 2
    assert any("pagenum=2" in s.url for s in res.additional_seed_urls)
    for p in res.product_urls:
        assert p.url.startswith("https://www.daytonaudio.com/product/")
        assert p.context.driver_kind_hint == DriverKind.LF_WOOFER
        assert p.context.category_id == "woofers"


def test_parse_dc160(scraper: DaytonScraper) -> None:
    raw = load_fixture("dayton", "products/dc160-8.html", url=_DC160_URL)
    res = scraper.parse_artifact(
        raw, SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="woofers")
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Dayton Audio"
    assert f.model == "DC160-8"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S
    assert f.fs_hz == pytest.approx(35.7)
    assert f.qts == pytest.approx(0.34)
    assert f.qes == pytest.approx(0.38)
    assert f.qms == pytest.approx(3.46)
    assert f.vas_liters == pytest.approx(17.9)
    assert f.sd_cm2 == pytest.approx(134.8)
    assert f.xmax_mm == pytest.approx(3.15)
    assert f.mms_g == pytest.approx(29.3)
    assert f.cms_mm_per_n == pytest.approx(0.68)
    assert f.bl_tm == pytest.approx(10.7)
    assert f.re_ohm == pytest.approx(6.6)
    assert f.le_mh == pytest.approx(2.26)

    # Sensitivity → 2.83V slot (Dayton convention)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(86.1)
    assert f.sensitivity_db_1w_1m is None

    # Power — RMS→AES, max→peak
    assert f.power_aes_watts == pytest.approx(50.0)
    assert f.power_peak_watts == pytest.approx(100.0)

    # Frequency range (thousands comma handled)
    assert f.freq_low_hz == pytest.approx(30.0)
    assert f.freq_high_hz == pytest.approx(4000.0)

    # Physical
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.nominal_size_mm == pytest.approx(165.1)  # 6.50" → 165.1 mm
    assert f.voice_coil_diameter_mm == pytest.approx(35.0)
    assert f.net_weight_kg == pytest.approx(3.3 * 0.453592, rel=1e-3)  # 3.3 lbs.

    # spec_source: table-based
    assert f.spec_source["fs_hz"] == SpecSource.HTML_TABLE
