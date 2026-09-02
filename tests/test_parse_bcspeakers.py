"""B&C Speakers enumerate + parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.bcspeakers import BcSpeakersScraper
from tests.conftest import load_fixture


_12FW64_URL = "https://www.bcspeakers.com/en/products/lf-driver/12/8/12FW64"


@pytest.fixture
def scraper() -> BcSpeakersScraper:
    return BcSpeakersScraper()


def test_enumerate_lf_category(scraper: BcSpeakersScraper) -> None:
    seed = load_fixture(
        "bcspeakers",
        "seeds/lf-driver.html",
        url="https://www.bcspeakers.com/en/products/lf-driver",
    )
    res = scraper.enumerate([seed])
    # Recon: 175 LF variants; observed 179 on 2026-08-22
    assert len(res.product_urls) >= 170
    assert all(
        p.context.driver_kind_hint == DriverKind.LF_WOOFER for p in res.product_urls
    )
    assert all("/en/products/lf-driver/" in p.url for p in res.product_urls)
    # dedup: case-insensitive
    lowered = {p.url.lower() for p in res.product_urls}
    assert len(lowered) == len(res.product_urls)


def test_parse_12fw64(scraper: BcSpeakersScraper) -> None:
    raw = load_fixture("bcspeakers", "products/12FW64.html", url=_12FW64_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="lf-driver"),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "B&C Speakers"
    assert f.model == "12FW64"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S
    assert f.fs_hz == pytest.approx(55.0)
    assert f.qts == pytest.approx(0.29)
    assert f.qes == pytest.approx(0.32)
    assert f.qms == pytest.approx(3.5)
    assert f.vas_liters == pytest.approx(64.0)
    assert f.sd_cm2 == pytest.approx(522.0)
    assert f.xmax_mm == pytest.approx(5.0)
    assert f.mms_g == pytest.approx(47.0)
    assert f.bl_tm == pytest.approx(15.5)
    assert f.re_ohm == pytest.approx(5.2)
    assert f.le_mh == pytest.approx(1.0)
    assert f.ebp_hz == pytest.approx(172.0)
    assert f.eta_zero_pct == pytest.approx(3.6)

    # Sensitivity — B&C tooltip explicitly says 2.83V, so 2.83V slot
    assert f.sensitivity_db_2_83v_1m == pytest.approx(98.0)
    assert f.sensitivity_db_1w_1m is None

    # Electrical + power (Continuous > AES per B&C convention)
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.7)
    assert f.power_aes_watts == pytest.approx(250.0)
    assert f.power_long_term_watts == pytest.approx(500.0)

    # Frequency range
    assert f.freq_low_hz == pytest.approx(55.0)
    assert f.freq_high_hz == pytest.approx(3000.0)

    # Physical + magnet (Ferrite → CERAMIC)
    assert f.nominal_size_mm == pytest.approx(320.0)
    assert f.voice_coil_diameter_mm == pytest.approx(64.0)
    assert f.overall_diameter_mm == pytest.approx(315.0)
    assert f.depth_mm == pytest.approx(136.0)
    assert f.net_weight_kg == pytest.approx(5.65)
    assert f.magnet_type == MagnetType.CERAMIC

    assert f.spec_source["fs_hz"] == SpecSource.HTML_GRID
