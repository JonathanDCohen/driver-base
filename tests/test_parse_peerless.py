"""Peerless enumerate + parse tests. JSON-API scraper."""

from __future__ import annotations

import hashlib

import pytest

from driver_base.interface import DriverKind, RawArtifact, SeedContext
from driver_base.model import SpecSource
from driver_base.scrapers.peerless import PeerlessScraper
from tests.conftest import load_fixture


def _json_fixture(scraper: str, relpath: str, url: str) -> RawArtifact:
    """Peerless serves application/json; the conftest loader defaults to
    text/html. Wrap it with the JSON content-type."""
    r = load_fixture(scraper, relpath, url=url)
    return RawArtifact(
        url=r.url,
        body=r.body,
        status=r.status,
        content_type="application/json",
        fetched_at=r.fetched_at,
        body_sha=r.body_sha,
        from_cache=r.from_cache,
    )


@pytest.fixture
def scraper() -> PeerlessScraper:
    return PeerlessScraper()


def test_enumerate_first_page_yields_products_and_next_page(
    scraper: PeerlessScraper,
) -> None:
    seed = _json_fixture(
        "peerless",
        "seeds/drivers-page1.json",
        url="https://products.peerless-audio.com/api/drivers?page=1",
    )
    res = scraper.enumerate([seed])
    # 12 rows/page. Any Preliminary/Prototype records are filtered — 12 is a
    # ceiling, real count may be a little less.
    assert 8 <= len(res.product_urls) <= 12
    for sr in res.product_urls:
        assert sr.url.startswith("https://products.peerless-audio.com/api/driver/")

    # Additional seed URLs: pages 2..last_page (last_page=10 per envelope).
    seed_urls = [s.url for s in res.additional_seed_urls]
    assert "https://products.peerless-audio.com/api/drivers?page=2" in seed_urls
    assert "https://products.peerless-audio.com/api/drivers?page=10" in seed_urls


def test_parse_fsl_woofer(scraper: PeerlessScraper) -> None:
    raw = _json_fixture(
        "peerless",
        "products/1497.json",
        url="https://products.peerless-audio.com/api/driver/1497",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.manufacturer == "Peerless"
    assert f.model == "FSL-0512R01-08"
    assert f.driver_kind == DriverKind.LF_WOOFER

    assert f.fs_hz == pytest.approx(120.0)
    assert f.qts == pytest.approx(0.58)
    assert f.vas_liters == pytest.approx(3.48)
    assert f.sd_cm2 == pytest.approx(100.0)
    assert f.xmax_mm == pytest.approx(4.33)
    assert f.xmech_mm == pytest.approx(4.8)
    assert f.mms_g == pytest.approx(6.99)
    assert f.bl_tm == pytest.approx(6.44)
    assert f.le_mh == pytest.approx(0.278)
    assert f.re_ohm == pytest.approx(5.9)
    assert f.cms_mm_per_n == pytest.approx(0.240)  # 240 µm/N → 0.240 mm/N

    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.impedance_min_ohm == pytest.approx(6.5)
    assert f.nominal_size_mm == pytest.approx(133.0)

    # TestVolt=2.83 → SensZ lands in 2.83V slot; SensRe always lands in 1W slot.
    assert f.sensitivity_db_2_83v_1m == pytest.approx(91.2)
    assert f.sensitivity_db_1w_1m == pytest.approx(89.9)

    assert f.power_aes_watts == pytest.approx(90.0)  # PowerSTD = AES2-1984

    # PowerLF / PowerUF are frequency limits in Hz, NOT power ratings.
    assert f.freq_low_hz == pytest.approx(90.0)
    assert f.freq_high_hz == pytest.approx(900.0)

    assert f.net_weight_kg == pytest.approx(0.98)
    assert f.voice_coil_diameter_mm == pytest.approx(30.5)  # VCID
    from driver_base.model import MagnetType

    assert f.magnet_type == MagnetType.CERAMIC  # 'Ferrite' → CERAMIC
    assert f.winding_material == "Copper-clad aluminium"  # VCMat CCAW
    assert f.spec_source["fs_hz"] == SpecSource.JSON_API


def test_parse_bc_tweeter(scraper: PeerlessScraper) -> None:
    raw = _json_fixture(
        "peerless",
        "products/28.json",
        url="https://products.peerless-audio.com/api/driver/28",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "BC25SC08-04"
    assert f.driver_kind == DriverKind.TWEETER
    assert f.impedance_nominal_ohm == pytest.approx(4.0)
    assert f.fs_hz == pytest.approx(1600.0)

    # Tweeter: TestVolt=0 → SensZ is effectively 1W/1m. SensRe is 1W/1m Re-
    # corrected. Both go to 1W slot; SensRe wins (more rigorous). No 2.83V.
    assert f.sensitivity_db_2_83v_1m is None
    assert f.sensitivity_db_1w_1m == pytest.approx(94.8)

    # PowerSTD = IEC 268-5 (not AES). We store into power_aes_watts either way
    # and let downstream conventions apply — a warn flag is added.
    assert f.power_aes_watts == pytest.approx(15.0)
    assert "power_std_non_aes" in f.warn_flags

    assert f.freq_low_hz == pytest.approx(2500.0)
    assert f.freq_high_hz == pytest.approx(20000.0)

    # VC + magnet — tweeter uses N35 neodymium.
    from driver_base.model import MagnetType

    assert f.magnet_type == MagnetType.NEODYMIUM
    assert f.voice_coil_diameter_mm == pytest.approx(25.4)


def test_parse_compression_driver(scraper: PeerlessScraper) -> None:
    raw = _json_fixture(
        "peerless",
        "products/597.json",
        url="https://products.peerless-audio.com/api/driver/597",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "DFL-2525R00-08"
    assert f.driver_kind == DriverKind.HF_COMPRESSION
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.sensitivity_db_1w_1m == pytest.approx(103.0)  # SensRe


def test_parse_fullrange_micro(scraper: PeerlessScraper) -> None:
    raw = _json_fixture(
        "peerless",
        "products/16.json",
        url="https://products.peerless-audio.com/api/driver/16",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    f = res.fragments[0]

    assert f.model == "ANC-50N25AL04-04"
    assert f.driver_kind == DriverKind.FULLRANGE
    # TestVolt=2.83 → SensZ to 2.83V slot; SensRe to 1W slot.
    assert f.sensitivity_db_2_83v_1m == pytest.approx(84.2)
    assert f.sensitivity_db_1w_1m == pytest.approx(83.6)


def test_parse_ignores_non_json_content_type(scraper: PeerlessScraper) -> None:
    """Defensive: if the fetcher ever returns HTML (proxy interception, error
    page), the parser must return an empty ParseResult rather than crash."""
    body = b"<html>not json</html>"
    raw = RawArtifact(
        url="https://products.peerless-audio.com/api/driver/1497",
        body=body,
        status=200,
        content_type="text/html",
        fetched_at="2026-09-01T00:00:00+00:00",
        body_sha=hashlib.sha256(body).hexdigest(),
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert res.fragments == []
