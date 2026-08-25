"""Faital enumerate + parse tests against captured fixtures."""

from __future__ import annotations

from collections import Counter

import pytest

from driver_base.interface import DriverKind, RawArtifact, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.faital import FaitalScraper
from tests.conftest import load_fixture


_12PR320_URL = "https://www.faitalpro.com/en/products/LF_Loudspeakers/product_details/index.php?id=101050135"


@pytest.fixture
def scraper() -> FaitalScraper:
    return FaitalScraper()


def _seed(relpath: str, url: str) -> RawArtifact:
    return load_fixture("faital", relpath, url=url)


def test_enumerate_all_categories(scraper: FaitalScraper) -> None:
    seeds = [
        _seed(
            "seeds/LF_Loudspeakers_search.html",
            "https://www.faitalpro.com/en/products/LF_Loudspeakers/search.php",
        ),
        _seed(
            "seeds/HF_Drivers_search.html",
            "https://www.faitalpro.com/en/products/HF_Drivers/search.php",
        ),
        _seed(
            "seeds/Coaxial_Loudspeakers.html",
            "https://www.faitalpro.com/en/products/Coaxial_Loudspeakers/",
        ),
        _seed(
            "seeds/HF_Horns.html",
            "https://www.faitalpro.com/en/products/HF_Horns/",
        ),
    ]
    res = scraper.enumerate(seeds)

    # Recon counts (captured 2026-08-25): 104 LF + 35 HF + 14 coax + 5 horns = 158.
    # Assert floors, not exact counts — Faital adds/retires SKUs over time.
    kinds = Counter(p.context.driver_kind_hint for p in res.product_urls)
    assert kinds[DriverKind.LF_WOOFER] >= 90
    assert kinds[DriverKind.HF_COMPRESSION] >= 30
    assert kinds[DriverKind.COAX] >= 12
    assert kinds[DriverKind.HORN] >= 4
    assert len(res.product_urls) >= 130

    # All URLs are the canonical mixed-case English form.
    assert all("/en/products/" in p.url for p in res.product_urls)
    assert all("product_details/index.php?id=" in p.url for p in res.product_urls)
    # No dupes.
    urls = [p.url for p in res.product_urls]
    assert len(urls) == len(set(urls))


def test_parse_12pr320(scraper: FaitalScraper) -> None:
    raw = load_fixture("faital", "products/12PR320.html", url=_12PR320_URL)
    res = scraper.parse_artifact(
        raw, SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="LF_Loudspeakers"),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Faital Pro"
    assert f.model == "12PR320"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S — every value matches recon baseline (0.00% delta at recon)
    assert f.fs_hz == pytest.approx(42.0)
    assert f.qts == pytest.approx(0.37)
    assert f.qes == pytest.approx(0.39)
    assert f.qms == pytest.approx(7.8)
    assert f.vas_liters == pytest.approx(113.3)   # "113.3 dm^3" caret notation
    assert f.sd_cm2 == pytest.approx(539.0)       # "539 cm^2" caret notation
    assert f.xmax_mm == pytest.approx(7.37)
    assert f.xmech_mm == pytest.approx(17.0)      # "Xdamage" one-way AS-REPORTED
    assert f.mms_g == pytest.approx(51.4)
    assert f.cms_mm_per_n == pytest.approx(0.28)
    assert f.bl_tm == pytest.approx(13.5)         # "13.5 N/A" (Newton/Ampere = T·m)
    assert f.re_ohm == pytest.approx(5.3)
    assert f.le_mh == pytest.approx(0.67)
    assert f.ebp_hz == pytest.approx(108.0)
    assert f.eta_zero_pct == pytest.approx(2.06)

    # Electrical + power (footnote-suffix labels normalized)
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.4)
    assert f.power_aes_watts == pytest.approx(300.0)
    assert f.power_peak_watts == pytest.approx(600.0)

    # Sensitivity — 1W/1m slot (label explicitly annotated)
    assert f.sensitivity_db_1w_1m == pytest.approx(97.0)
    assert f.sensitivity_db_2_83v_1m is None

    # Frequency range: ÷ separator
    assert f.freq_low_hz == pytest.approx(45.0)
    assert f.freq_high_hz == pytest.approx(5000.0)

    # Physical
    assert f.nominal_size_mm == pytest.approx(300.0)
    assert f.voice_coil_diameter_mm == pytest.approx(65.0)
    assert f.net_weight_kg == pytest.approx(2.75)
    assert f.magnet_type == MagnetType.NEODYMIUM
    assert f.spec_source["fs_hz"] == SpecSource.HTML_TABLE
