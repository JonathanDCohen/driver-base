"""SB Acoustics enumerate + parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import SpecSource
from driver_base.scrapers.sbacoustics import SBAcousticsScraper
from tests.conftest import load_fixture


_SB17_URL = "https://sbacoustics.com/product/6in-sb17nac35-8/"
_TW29_URL = "https://sbacoustics.com/product/satori-tw29bn-b-8/"
_SW26_URL = "https://sbacoustics.com/product/10in-sw26dac76-8/"
_COAX_URL = "https://sbacoustics.com/product/sb15bac30-8-coax/"


@pytest.fixture
def scraper() -> SBAcousticsScraper:
    return SBAcousticsScraper()


def test_enumerate_sitemap(scraper: SBAcousticsScraper) -> None:
    seed = load_fixture(
        "sbacoustics",
        "seeds/product-sitemap.xml",
        url="https://sbacoustics.com/product-sitemap.xml",
    )
    res = scraper.enumerate([seed])
    # Sitemap has ~231 URLs; after dropping hard-listed kits (~18) we expect ~210.
    assert len(res.product_urls) >= 200
    # Every URL is a /product/ page.
    assert all("/product/" in p.url for p in res.product_urls)
    # Kits are excluded at enumeration.
    slugs = {p.url.rstrip("/").rsplit("/", 1)[-1] for p in res.product_urls}
    assert "rinjani" not in slugs
    assert "ara" not in slugs
    assert "bromo" not in slugs
    # Real driver products are kept.
    assert "6in-sb17nac35-8" in slugs
    assert "satori-tw29bn-b-8" in slugs


def test_parse_sb17nac35_midwoofer(scraper: SBAcousticsScraper) -> None:
    raw = load_fixture("sbacoustics", "products/SB17NAC35-8.html", url=_SB17_URL)
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "SB Acoustics"
    assert f.model == "SB17NAC35-8"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S
    assert f.fs_hz == pytest.approx(31.5)
    assert f.qts == pytest.approx(0.42)
    assert f.qes == pytest.approx(0.45)
    assert f.qms == pytest.approx(6.0)
    assert f.vas_liters == pytest.approx(33.0)
    assert f.sd_cm2 == pytest.approx(118.0)
    assert f.mms_g == pytest.approx(15.2)
    assert f.bl_tm == pytest.approx(6.2)
    assert f.re_ohm == pytest.approx(5.7)
    assert f.le_mh == pytest.approx(0.15)
    assert f.cms_mm_per_n == pytest.approx(1.68)

    # SB reports Linear coil travel PEAK-TO-PEAK (`(p-p)`); framework xmax_mm
    # is one-way. Divide by 2, mark DERIVED.
    assert f.xmax_mm == pytest.approx(5.5)  # 11 mm p-p / 2
    assert f.spec_source["xmax_mm"] == SpecSource.DERIVED

    # SB explicitly labels 2.83V/1m — must NOT go to the 1W slot.
    assert f.sensitivity_db_2_83v_1m == pytest.approx(86.5)
    assert f.sensitivity_db_1w_1m is None

    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.power_aes_watts == pytest.approx(60.0)  # "Rated power handling*"

    assert f.voice_coil_diameter_mm == pytest.approx(35.5)
    assert f.net_weight_kg == pytest.approx(1.56)

    # Nominal size derived from URL slug ('6in-...').
    assert f.nominal_size_mm == pytest.approx(6 * 25.4)
    assert f.spec_source["nominal_size_mm"] == SpecSource.DERIVED

    # 'Magnetic flux density 1.0 T' → flux_density_t
    assert f.flux_density_t == pytest.approx(1.0)

    assert f.spec_source["fs_hz"] == SpecSource.HTML_PROSE


def test_parse_tw29bn_tweeter(scraper: SBAcousticsScraper) -> None:
    raw = load_fixture("sbacoustics", "products/TW29BN-B-8.html", url=_TW29_URL)
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "TW29BN-B-8"
    assert f.driver_kind == DriverKind.TWEETER
    assert f.fs_hz == pytest.approx(750.0)
    assert f.qts == pytest.approx(0.55)
    # 'Sensitivity (2.83V/1m)' — no space
    assert f.sensitivity_db_2_83v_1m == pytest.approx(93.5)
    assert f.sensitivity_db_1w_1m is None
    assert f.power_aes_watts == pytest.approx(80.0)
    assert f.bl_tm == pytest.approx(4.1)
    # 'Effective piston area, Sd 9.6 cm 2' — space before superscript
    assert f.sd_cm2 == pytest.approx(9.6)
    # Satori tweeter slug has no size prefix; VC diameter (29mm) fallback.
    assert f.voice_coil_diameter_mm == pytest.approx(29.0)
    assert f.nominal_size_mm == pytest.approx(29.0)
    assert f.spec_source["nominal_size_mm"] == SpecSource.DERIVED


def test_parse_sw26dac_subwoofer(scraper: SBAcousticsScraper) -> None:
    raw = load_fixture("sbacoustics", "products/SW26DAC76-8.html", url=_SW26_URL)
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "SW26DAC76-8"
    assert f.driver_kind == DriverKind.LF_WOOFER  # Shallow Subwoofers-OEM
    assert f.fs_hz == pytest.approx(19.5)
    assert f.xmax_mm == pytest.approx(12.0)  # 24 mm p-p / 2
    assert f.sensitivity_db_2_83v_1m == pytest.approx(83.0)
    assert f.power_aes_watts == pytest.approx(250.0)
    # 'Equivalent volume, Vas 54 ltr.' — abbreviated units
    assert f.vas_liters == pytest.approx(54.0)
    # 'Moving mass incl. air,Mms 172 g' — missing space after comma
    assert f.mms_g == pytest.approx(172.0)
    # Slug '10in-sw26dac76-8' → 10 inches
    assert f.nominal_size_mm == pytest.approx(10 * 25.4)


def test_parse_sb15bac30_coax(scraper: SBAcousticsScraper) -> None:
    raw = load_fixture("sbacoustics", "products/SB15BAC30-8-coax.html", url=_COAX_URL)
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "SB15BAC30-8-COAX"
    assert f.driver_kind == DriverKind.COAX

    # LF section → generic fields
    assert f.fs_hz == pytest.approx(43.0)
    assert f.qts == pytest.approx(0.36)
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.sensitivity_db_2_83v_1m == pytest.approx(86.0)
    assert f.power_aes_watts == pytest.approx(40.0)
    assert f.re_ohm == pytest.approx(5.7)

    # HF section → coax_hf_* fields
    assert f.coax_hf_impedance_nominal_ohm == pytest.approx(4.0)
    assert f.coax_hf_re_ohm == pytest.approx(3.8)
    assert f.coax_hf_voice_coil_diameter_mm == pytest.approx(19.1)
    # HF sensitivity — SB's coax HF sensitivity is 2.83V/1m too but the
    # framework's coax_hf slot is `coax_hf_sensitivity_db_1w_1m`; leave null
    # to avoid mis-slotting.
    assert f.coax_hf_sensitivity_db_1w_1m is None
    # HF power (25 W) routes into coax_hf_power_aes_watts.
    assert f.coax_hf_power_aes_watts == pytest.approx(25.0)
