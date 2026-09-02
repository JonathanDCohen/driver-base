"""Monacor enumerate + parse tests."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import SpecSource
from driver_base.scrapers.monacor import MonacorScraper
from tests.conftest import load_fixture


_CF1025_URL = (
    "https://www.monacor.com/products/components/speaker-technology/"
    "pa-bass-speakers-/cf1025c-8/"
)
_AN2075_URL = (
    "https://www.monacor.com/products/components/speaker-technology/"
    "hi-fi-full-range-speakers-/an2075-8/"
)
_CDX1_URL = (
    "https://www.monacor.com/products/components/speaker-technology/"
    "pa-tweeters-and-horn-drivers-/cdx1-1425-8/"
)


@pytest.fixture
def scraper() -> MonacorScraper:
    return MonacorScraper()


def test_enumerate_pa_bass_speakers(scraper: MonacorScraper) -> None:
    seed = load_fixture(
        "monacor",
        "seeds/pa-bass-speakers-page1.html",
        url="https://www.monacor.com/products/components/speaker-technology/"
        "pa-bass-speakers-/",
    )
    res = scraper.enumerate([seed])
    # 12 products/page. Every URL absolute, ends with a driver slug.
    assert 10 <= len(res.product_urls) <= 12
    for sr in res.product_urls:
        assert sr.url.startswith(
            "https://www.monacor.com/products/components/speaker-technology/"
            "pa-bass-speakers-/"
        )
        assert sr.url.endswith("/")
        assert sr.context.driver_kind_hint == DriverKind.LF_WOOFER

    slugs = {sr.url.rstrip("/").rsplit("/", 1)[-1] for sr in res.product_urls}
    assert "cf1025c-8" in slugs


def test_enumerate_excludes_celestion_resells(scraper: MonacorScraper) -> None:
    # Fabricate a page fragment containing a Celestion resell URL. Real pa-tweeters
    # listings mix them in; the scraper should drop `cdx*` / `axi*` slugs.
    html = (
        '<a href="products/components/speaker-technology/'
        'pa-tweeters-and-horn-drivers-/cdx1-1425-8/">CDX1</a>'
        '<a href="products/components/speaker-technology/'
        'pa-tweeters-and-horn-drivers-/dt-284/">DT-284</a>'
    ).encode()
    from driver_base.interface import RawArtifact
    import hashlib

    seed = RawArtifact(
        url=(
            "https://www.monacor.com/products/components/speaker-technology/"
            "pa-tweeters-and-horn-drivers-/"
        ),
        body=html,
        status=200,
        content_type="text/html; charset=utf-8",
        fetched_at="2026-09-01T00:00:00+00:00",
        body_sha=hashlib.sha256(html).hexdigest(),
    )
    res = scraper.enumerate([seed])
    slugs = {sr.url.rstrip("/").rsplit("/", 1)[-1] for sr in res.product_urls}
    assert "cdx1-1425-8" not in slugs  # Celestion resell — skipped
    assert "dt-284" in slugs  # Monacor's own DT-series — kept


def test_parse_cf1025c_pa_woofer(scraper: MonacorScraper) -> None:
    raw = load_fixture("monacor", "products/CF1025C-8.html", url=_CF1025_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(
            driver_kind_hint=DriverKind.LF_WOOFER, category_id="pa-bass-speakers-"
        ),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Monacor"
    assert f.model == "CF1025C"  # slash-impedance suffix stripped
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S
    assert f.fs_hz == pytest.approx(54.8)
    assert f.qts == pytest.approx(0.265)
    assert f.qes == pytest.approx(0.299)
    assert f.qms == pytest.approx(2.338)
    assert f.vas_liters == pytest.approx(38.6)
    assert f.sd_cm2 == pytest.approx(346.36)
    assert f.xmax_mm == pytest.approx(4.25)  # '± 4.25 mm' — sign stripped
    assert f.mms_g == pytest.approx(37.03)
    assert f.bl_tm == pytest.approx(14.82)  # 'Force factor (BxL)' → force factor
    assert f.re_ohm == pytest.approx(5.15)
    assert f.le_mh == pytest.approx(0.57)
    assert f.cms_mm_per_n == pytest.approx(0.23)

    # 1W/1m — Monacor labels `SPL` with `dB/W/m` unambiguously.
    assert f.sensitivity_db_1w_1m == pytest.approx(99.0)
    assert f.sensitivity_db_2_83v_1m is None

    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.power_aes_watts == pytest.approx(300.0)  # Power rating (RMS)
    assert f.power_peak_watts == pytest.approx(600.0)  # Peak music power output (MAX)

    assert f.freq_low_hz == pytest.approx(60.0)
    assert f.freq_high_hz == pytest.approx(5000.0)

    assert f.voice_coil_diameter_mm == pytest.approx(64.0)  # 'Ø 64 mm' — sigil stripped
    assert f.mounting_diameter_mm == pytest.approx(230.8)  # 'Ø 230.8 mm'
    assert f.depth_mm == pytest.approx(119.0)
    assert f.net_weight_kg == pytest.approx(4.9)
    assert f.nominal_size_mm == pytest.approx(10 * 25.4)  # 'Type of speaker' = '10"'

    assert f.spec_source["fs_hz"] == SpecSource.HTML_TABLE


def test_parse_an2075_hifi_fullrange(scraper: MonacorScraper) -> None:
    raw = load_fixture("monacor", "products/AN-2075-8.html", url=_AN2075_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(
            driver_kind_hint=DriverKind.FULLRANGE,
            category_id="hi-fi-full-range-speakers-",
        ),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "AN2075"
    assert f.driver_kind == DriverKind.FULLRANGE
    assert f.fs_hz == pytest.approx(153.4)
    assert f.qts == pytest.approx(0.839)
    # Eff. cone area 12.56 cm 2 (space before superscript) — parse_sd_cm2 handles.
    assert f.sd_cm2 == pytest.approx(12.56)
    assert f.sensitivity_db_1w_1m == pytest.approx(80.0)
    assert f.power_aes_watts == pytest.approx(20.0)
    assert f.freq_high_hz == pytest.approx(19000.0)  # comma-thousands survives


def test_parse_cdx1_no_ts_ok(scraper: MonacorScraper) -> None:
    """HF compression drivers publish no T/S; parse must not fail on missing rows."""
    raw = load_fixture("monacor", "products/CDX1-1425-8.html", url=_CDX1_URL)
    res = scraper.parse_artifact(
        raw,
        SeedContext(
            driver_kind_hint=DriverKind.HF_COMPRESSION,
            category_id="pa-tweeters-and-horn-drivers-",
        ),
    )
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "CDX1-1425"
    assert f.driver_kind == DriverKind.HF_COMPRESSION
    assert f.fs_hz is None  # legit — no T/S for compression drivers
    assert f.qts is None
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.sensitivity_db_1w_1m == pytest.approx(108.0)
    assert f.power_aes_watts == pytest.approx(25.0)
    assert f.recommended_crossover_hz == pytest.approx(2500.0)
    assert f.freq_low_hz == pytest.approx(2000.0)
    assert f.freq_high_hz == pytest.approx(20000.0)
    # 'Mounting cutout' = 'dep. on horn' → parses to None, not a crash.
    assert f.mounting_diameter_mm is None
