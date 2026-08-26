"""Jensen enumerate + multi-impedance parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.jensen import JensenScraper
from tests.conftest import load_fixture


_P12N_URL = "https://www.jensentone.com/vintage-alnico/p12n"


@pytest.fixture
def scraper() -> JensenScraper:
    return JensenScraper()


def test_enumerate_sitemap_filters_to_product_urls(scraper: JensenScraper) -> None:
    seed = load_fixture(
        "jensen", "seeds/sitemap.xml",
        url="https://www.jensentone.com/sitemap.xml",
    )
    res = scraper.enumerate([seed])
    # 63 product URLs across 7 categories per recon
    assert len(res.product_urls) == 63
    # Every URL is a product under a known category. Kind is GUITAR_BASS except
    # for /bass-speakers/v-11-compression-driver which is reclassified to
    # HF_COMPRESSION (it's a horn driver, not a guitar cone).
    for p in res.product_urls:
        assert any(f"/{c}/" in p.url for c in
                   ("vintage-alnico", "vintage-ceramic", "vintage-neo",
                    "jet-series", "mod-series", "d-series", "bass-speakers"))
        if p.url.rstrip("/").endswith("/v-11-compression-driver"):
            assert p.context.driver_kind_hint == DriverKind.HF_COMPRESSION
        else:
            assert p.context.driver_kind_hint == DriverKind.GUITAR_BASS


def test_parse_p12n_emits_two_impedance_fragments(scraper: JensenScraper) -> None:
    """P12N ships in 8Ω and 16Ω from a single URL — the scraper must emit
    one fragment per impedance so each variant gets its own canonical_id."""
    raw = load_fixture("jensen", "products/p12n.html", url=_P12N_URL)
    res = scraper.parse_artifact(
        raw, SeedContext(driver_kind_hint=DriverKind.GUITAR_BASS),
    )
    assert len(res.fragments) == 2

    by_impedance = {f.impedance_nominal_ohm: f for f in res.fragments}
    assert set(by_impedance) == {8.0, 16.0}

    # Shared fields (identical across both variants)
    for f in res.fragments:
        assert f.manufacturer == "Jensen"
        assert f.model == "P12N"
        assert f.driver_kind == DriverKind.GUITAR_BASS
        assert f.magnet_type == MagnetType.ALNICO
        assert f.nominal_size_mm == pytest.approx(307.0)
        assert f.voice_coil_diameter_mm == pytest.approx(38.0)
        assert f.net_weight_kg == pytest.approx(3.1)
        assert f.xmax_mm == pytest.approx(1.0)
        assert f.power_aes_watts == pytest.approx(50.0)
        assert f.power_peak_watts == pytest.approx(100.0)
        # Qes has one value across both impedance columns → applied to each fragment
        assert f.qes == pytest.approx(0.98)

    # 8Ω variant
    f8 = by_impedance[8.0]
    assert f8.re_ohm == pytest.approx(6.03)
    assert f8.fs_hz == pytest.approx(90.0)
    assert f8.qms == pytest.approx(4.36)
    assert f8.qts == pytest.approx(0.77)
    assert f8.vas_liters == pytest.approx(34.6)
    assert f8.mms_g == pytest.approx(30.9)
    assert f8.bl_tm == pytest.approx(10.62)
    assert f8.le_mh == pytest.approx(0.87)
    assert f8.cms_mm_per_n == pytest.approx(0.101)   # from '101 µm/N'
    assert f8.sd_cm2 == pytest.approx(490.9, rel=1e-3)
    assert f8.eta_zero_pct == pytest.approx(3.4)
    assert f8.sensitivity_db_1w_1m == pytest.approx(97.5)

    # 16Ω variant — different Re / Fs / Q / Vas / Bl / Le / Cms / sensitivity
    f16 = by_impedance[16.0]
    assert f16.re_ohm == pytest.approx(12.0)
    assert f16.fs_hz == pytest.approx(91.0)
    assert f16.qms == pytest.approx(5.77)
    assert f16.qts == pytest.approx(0.84)
    assert f16.vas_liters == pytest.approx(42.2)
    assert f16.mms_g == pytest.approx(27.0)
    assert f16.bl_tm == pytest.approx(13.71)
    assert f16.le_mh == pytest.approx(1.05)
    assert f16.cms_mm_per_n == pytest.approx(0.125)
    assert f16.sensitivity_db_1w_1m == pytest.approx(97.8)

    # spec_source tagged
    assert f8.spec_source["fs_hz"] == SpecSource.HTML_TABLE
