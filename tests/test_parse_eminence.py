"""Eminence enumerate + parse tests against captured fixtures."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import SpecSource
from driver_base.scrapers.eminence import EminenceScraper
from tests.conftest import load_fixture


_KILOMAX_URL = "https://eminence.com/products/kilomax_pro_18a"


@pytest.fixture
def scraper() -> EminenceScraper:
    return EminenceScraper()


def test_enumerate_filters_non_drivers(scraper: EminenceScraper) -> None:
    seed = load_fixture(
        "eminence",
        "seeds/products.json",
        url="https://eminence.com/products.json?limit=250&page=1",
    )
    res = scraper.enumerate([seed])
    # 155 total products, 16 non-drivers (Crossover / Speaker Cable / etc.) → 139 drivers
    assert len(res.product_urls) == 139
    kinds = {p.context.driver_kind_hint for p in res.product_urls}
    # Every expected kind is represented
    assert DriverKind.LF_WOOFER in kinds
    assert DriverKind.HF_COMPRESSION in kinds
    assert DriverKind.GUITAR_BASS in kinds
    assert DriverKind.TWEETER in kinds
    assert DriverKind.HORN in kinds


def test_parse_kilomax_pro_18a(scraper: EminenceScraper) -> None:
    raw = load_fixture("eminence", "products/kilomax_pro_18a.html", url=_KILOMAX_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(
            driver_kind_hint=DriverKind.LF_WOOFER,
            category_id="Professional Series Replacement Speaker",
        ),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Eminence"
    assert f.model == "KILOMAX PRO 18A"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S (recon-verified baseline)
    assert f.fs_hz == pytest.approx(32.0)
    assert f.qts == pytest.approx(0.47)
    assert f.qes == pytest.approx(0.49)
    assert f.qms == pytest.approx(10.15)
    assert f.vas_liters == pytest.approx(331.5)  # Vas dual-unit split correctly
    assert f.sd_cm2 == pytest.approx(1159.0)
    assert f.xmax_mm == pytest.approx(10.0)
    assert f.xmech_mm == pytest.approx(19.2)  # "Maximum Mechanical Limit (Xlim)"
    assert f.mms_g == pytest.approx(143.0)  # "143 grams"
    assert f.bl_tm == pytest.approx(17.2)  # "17.2 T-M" (hyphen)
    assert f.re_ohm == pytest.approx(5.07)
    assert f.le_mh == pytest.approx(1.59)  # "1.59m H" quirk parsed
    assert f.ebp_hz == pytest.approx(65.0)

    # Electrical / commercial — Eminence's "Watts" IS the AES rating
    # (Program 2500 = 2× Watts 1250 confirms the AES convention).
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.power_program_watts == pytest.approx(2500.0)
    assert f.power_aes_watts == pytest.approx(1250.0)
    assert f.power_long_term_watts is None

    # Sensitivity — Eminence convention: 1W/1m slot
    assert f.sensitivity_db_1w_1m == pytest.approx(95.8)
    assert f.sensitivity_db_2_83v_1m is None

    # Mixed-unit frequency range: "33 Hz - 0.3 kHz" → (33, 300)
    assert f.freq_low_hz == pytest.approx(33.0)
    assert f.freq_high_hz == pytest.approx(300.0)

    # Physical (dual metric+imperial, metric picked)
    assert f.nominal_size_mm == pytest.approx(457.0)  # "18\", 457 mm"
    assert f.voice_coil_diameter_mm == pytest.approx(102.0)
    assert f.net_weight_kg == pytest.approx(12.43)  # "27.4 lbs, 12.43 kg"

    assert f.spec_source["fs_hz"] == SpecSource.HTML_TABLE
