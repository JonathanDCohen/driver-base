"""Celestion enumerate + parse tests (pro + guitar driver fixtures)."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.celestion import CelestionScraper
from tests.conftest import load_fixture


@pytest.fixture
def scraper() -> CelestionScraper:
    return CelestionScraper()


def test_enumerate_product_sitemap(scraper: CelestionScraper) -> None:
    seed = load_fixture(
        "celestion", "seeds/product-sitemap.xml",
        url="https://celestion.com/product-sitemap.xml",
    )
    res = scraper.enumerate([seed])
    # Sitemap has 213 /product/*/ URLs + 1 /products/ index (filtered out).
    assert len(res.product_urls) == 213
    assert all("/product/" in p.url and "/products/" not in p.url for p in res.product_urls)


def test_parse_tf1525_pro_lf(scraper: CelestionScraper) -> None:
    raw = load_fixture(
        "celestion", "products/tf1525.html",
        url="https://celestion.com/product/tf1525/",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Celestion"
    assert f.model == "TF1525"
    assert f.driver_kind == DriverKind.LF_WOOFER   # from breadcrumb 'Pro Audio / LF Loudspeakers'

    # T/S
    assert f.fs_hz == pytest.approx(47.6)
    assert f.qts == pytest.approx(0.493)
    assert f.qes == pytest.approx(0.565)
    assert f.qms == pytest.approx(3.835)
    assert f.vas_liters == pytest.approx(148.41)
    assert f.sd_cm2 == pytest.approx(855.3, rel=1e-3)   # '855.30cm2' (sup-tag stripped)
    assert f.xmax_mm == pytest.approx(4.5)
    assert f.mms_g == pytest.approx(77.93)
    assert f.bl_tm == pytest.approx(14.57)              # 'BI' typo variant maps to bl_tm
    assert f.re_ohm == pytest.approx(5.15)
    assert f.le_mh == pytest.approx(0.9)
    assert f.cms_mm_per_n == pytest.approx(0.14)
    assert f.rms_ns_per_m == pytest.approx(6.08)

    # Sensitivity → 1W/1m per Celestion convention
    assert f.sensitivity_db_1w_1m == pytest.approx(98.0)

    # Power triple — Celestion is the only manufacturer that publishes EIA
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.power_aes_watts == pytest.approx(250.0)
    assert f.power_long_term_watts == pytest.approx(500.0)
    assert f.power_eia_watts == pytest.approx(400.0)

    assert f.freq_low_hz == pytest.approx(40.0)
    assert f.freq_high_hz == pytest.approx(3000.0)

    # Physical + magnet
    assert f.nominal_size_mm == pytest.approx(381.0)
    assert f.voice_coil_diameter_mm == pytest.approx(64.0)
    assert f.overall_diameter_mm == pytest.approx(385.0)
    assert f.depth_mm == pytest.approx(153.0)
    assert f.mounting_diameter_mm == pytest.approx(351.0)
    assert f.net_weight_kg == pytest.approx(5.2)
    assert f.magnet_type == MagnetType.CERAMIC

    assert f.spec_source["fs_hz"] == SpecSource.HTML_DIV_PAIRS
    assert f.canonical_id_seed == "tf1525"


def test_parse_vintage_30_guitar(scraper: CelestionScraper) -> None:
    """Guitar drivers use `Resonance frequency, Fs` labels and legitimately
    lack T/S params. GUITAR_BASS kind exempts them from the T/S REJECT."""
    raw = load_fixture(
        "celestion", "products/vintage-30.html",
        url="https://celestion.com/product/vintage-30/",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "Vintage 30"
    assert f.driver_kind == DriverKind.GUITAR_BASS  # breadcrumb 'Guitar & Bass Speakers'

    # Present via comma-suffix labels
    assert f.fs_hz == pytest.approx(75.0)             # 'Resonance frequency, Fs' → fs_hz
    assert f.re_ohm == pytest.approx(7.3)             # 'DC resistance, Re' → re_ohm

    # T/S absent (expected for a guitar driver — no Qms/Qes/Qts/Vas/Xmax on page)
    assert f.qts is None
    assert f.qes is None
    assert f.qms is None
    assert f.vas_liters is None
    assert f.xmax_mm is None

    # Basic specs present
    assert f.impedance_nominal_ohm == pytest.approx(8.0)   # from '8Ω or 16Ω' → first
    assert f.sensitivity_db_1w_1m == pytest.approx(100.0)
    assert f.power_aes_watts == pytest.approx(60.0)
    assert f.freq_low_hz == pytest.approx(70.0)
    assert f.freq_high_hz == pytest.approx(5000.0)
    assert f.nominal_size_mm == pytest.approx(305.0)
    assert f.magnet_type == MagnetType.CERAMIC


def test_discover_seeds_single_sitemap_url(scraper: CelestionScraper) -> None:
    seeds = scraper.discover_seeds()
    assert len(seeds) == 1
    assert seeds[0].url == "https://celestion.com/product-sitemap.xml"
