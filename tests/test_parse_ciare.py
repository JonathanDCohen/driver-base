"""Ciare parse_artifact + enumerate across catalog + detail fixtures.

The scraper's flow is: fetch one category listing → enumerate yields 148
per-product detail URLs → parse_artifact on each detail page extracts the
one matching wrappedProduct and emits its variants.
"""

from __future__ import annotations


import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.ciare import CiareScraper
from tests.conftest import load_fixture


@pytest.fixture
def scraper() -> CiareScraper:
    return CiareScraper()


def test_enumerate_catalog(scraper: CiareScraper) -> None:
    """Catalog page yields per-product detail URLs following the SPA's
    `/products/:preview?/:category/:inches/:ohms/:code` route."""
    seed = load_fixture(
        "ciare",
        "seeds/lf-driver.html",
        url="https://ciare.com/en/products/lf-driver",
    )
    res = scraper.enumerate([seed])
    urls = [p.url for p in res.product_urls]
    # Catalog captured 2026-11-05: 148 unique products across 5 categories.
    assert len(urls) >= 140
    # Check a couple of expected shapes
    assert any(u.endswith("/lf-driver/8/8/HW210") for u in urls)
    assert any(u.endswith("/coaxial/4/4/CX102") for u in urls)
    assert any(u.endswith("/tweeter/1/4/CT268ND") for u in urls)
    # Every URL carries the detail-route shape (category/inches/ohms/model).
    for u in urls:
        tail = u.split("/en/products/", 1)[1]
        assert tail.count("/") == 3, f"unexpected URL shape: {u}"


def _parse(scraper: CiareScraper, slug: str, url: str, kind: DriverKind):
    raw = load_fixture("ciare", f"products/{slug}.html", url=url)
    return scraper.parse_artifact(
        raw, SeedContext(driver_kind_hint=kind, category_id=kind.value)
    )


def test_parse_ndh18_full_ts(scraper: CiareScraper) -> None:
    """NDH18-4S — 18" pro LF driver with full Thiele–Small params.
    Confirms the detail-page pipeline unlocks the data the catalog view
    doesn't publish."""
    res = _parse(
        scraper,
        "ndh18-4s",
        "https://ciare.com/en/products/lf-driver/18/4/NDH18-4S",
        DriverKind.LF_WOOFER,
    )
    # Two variants (8Ω, 4Ω) emitted from one page.
    assert len(res.fragments) == 2
    by_imp = {f.impedance_nominal_ohm: f for f in res.fragments}
    f8 = by_imp[8.0]
    assert f8.manufacturer == "Ciare"
    assert f8.model == "NDH18-4S"
    assert f8.driver_kind == DriverKind.LF_WOOFER

    # T/S params from `variants[].params` — the catalog view has NONE of these.
    assert f8.fs_hz == pytest.approx(31.0)
    assert f8.re_ohm == pytest.approx(6.1)
    assert f8.qts == pytest.approx(0.32)
    assert f8.qes == pytest.approx(0.33)
    assert f8.qms == pytest.approx(9.8)
    assert f8.vas_liters == pytest.approx(239.0)
    assert f8.sd_cm2 == pytest.approx(1164.0)
    assert f8.xmax_mm == pytest.approx(11.5)
    assert f8.mms_g == pytest.approx(212.0)
    assert f8.bl_tm == pytest.approx(27.7)
    assert f8.le_mh == pytest.approx(1.9)
    assert f8.ebp_hz == pytest.approx(94.0)
    assert f8.eta_zero_pct == pytest.approx(2.1)

    # Power split: nominal (AES) vs continuous (= program).
    assert f8.power_aes_watts == pytest.approx(1000.0)
    assert f8.power_program_watts == pytest.approx(2000.0)

    # Mounting fields from shippingMounting.
    assert f8.overall_diameter_mm == pytest.approx(388.0)
    assert f8.mounting_diameter_mm == pytest.approx(354.0)
    assert f8.depth_mm == pytest.approx(208.0)
    assert f8.net_weight_kg == pytest.approx(8.0)

    # Spec source stamps.
    assert f8.spec_source["fs_hz"] == SpecSource.INLINE_JS
    assert f8.spec_source["power_aes_watts"] == SpecSource.INLINE_JS

    # 4Ω variant has distinct T/S (re and qes change with coil wiring).
    f4 = by_imp[4.0]
    assert f4.re_ohm == pytest.approx(3.0)
    assert f4.qes == pytest.approx(0.25)
    assert f4.bl_tm == pytest.approx(22.2)


def test_parse_hw210_consumer(scraper: CiareScraper) -> None:
    """HW210 — consumer woofer; detail page also publishes richer physical
    specs even when T/S isn't included."""
    res = _parse(
        scraper,
        "hw210",
        "https://ciare.com/en/products/lf-driver/8/8/HW210",
        DriverKind.LF_WOOFER,
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]
    assert f.model == "HW210"
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    # Catalog view publishes only the 150 W continuous (program) figure;
    # the detail page adds the 60 W nominal (AES) rating. Keep them in the
    # right slots so downstream power consistency checks (program >= AES)
    # stay valid.
    assert f.power_aes_watts == pytest.approx(60.0)
    assert f.power_program_watts == pytest.approx(150.0)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(90.0)
    assert f.freq_low_hz == pytest.approx(30.0)
    assert f.freq_high_hz == pytest.approx(6000.0)
    assert f.voice_coil_diameter_mm == pytest.approx(25.0)
    # 8 inches → 203.2 mm (lfSpecs.nominalDiameter is 215 mm; the
    # section-value takes precedence on the detail page).
    assert f.nominal_size_mm is not None
    assert 200 <= f.nominal_size_mm <= 220
    assert f.magnet_type == MagnetType.CERAMIC


def test_parse_cx102_coax(scraper: CiareScraper) -> None:
    """Coax detail page routes LF → generic, HF → coax_hf_*."""
    res = _parse(
        scraper,
        "cx102",
        "https://ciare.com/en/products/coaxial/4/4/CX102",
        DriverKind.COAX,
    )
    assert len(res.fragments) >= 1
    f = res.fragments[0]
    assert f.driver_kind == DriverKind.COAX
    assert f.impedance_nominal_ohm == pytest.approx(4.0)
    assert f.power_aes_watts == pytest.approx(40.0)
    assert f.power_program_watts == pytest.approx(100.0)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(89.0)
    assert f.voice_coil_diameter_mm == pytest.approx(25.0)
    assert f.coax_hf_impedance_nominal_ohm == pytest.approx(4.0)
    assert f.coax_hf_power_aes_watts == pytest.approx(40.0)


def test_parse_ct268nd_tweeter(scraper: CiareScraper) -> None:
    """Tweeter: hfSpecs → generic fields; diaphragm material populated."""
    res = _parse(
        scraper,
        "ct268nd",
        "https://ciare.com/en/products/tweeter/1/4/CT268ND",
        DriverKind.TWEETER,
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]
    assert f.driver_kind == DriverKind.TWEETER
    assert f.magnet_type == MagnetType.NEODYMIUM
    assert f.impedance_nominal_ohm == pytest.approx(4.0)
    assert f.power_aes_watts == pytest.approx(150.0)
    assert f.power_program_watts == pytest.approx(250.0)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(105.0)
    assert f.diaphragm_material == "Aluminum"


def test_parse_cmi160_full_ts(scraper: CiareScraper) -> None:
    """Mid-tier 6.5" woofer with full T/S on the detail page."""
    res = _parse(
        scraper,
        "cmi160",
        "https://ciare.com/en/products/lf-driver/6.5/4/CMI160",
        DriverKind.LF_WOOFER,
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]
    assert f.model == "CMI160"
    assert f.fs_hz == pytest.approx(70.0)
    assert f.qts == pytest.approx(0.41)
    assert f.vas_liters == pytest.approx(7.8)
    assert f.sd_cm2 == pytest.approx(137.0)
    assert f.mms_g == pytest.approx(18.5)
    assert f.bl_tm == pytest.approx(7.2)
    assert f.le_mh == pytest.approx(0.7)
    assert f.xmax_mm == pytest.approx(4.5)
    assert f.power_aes_watts == pytest.approx(220.0)
    assert f.power_program_watts == pytest.approx(450.0)
    # Continuous = 2× nominal, matching Ciare's "Program Power = 3 dB
    # greater than Nominal" rule stamped in their spec notes.
    assert f.sensitivity_db_2_83v_1m == pytest.approx(94.0)
