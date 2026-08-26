"""HOQS parse_artifact against captured N185C fixture."""

from __future__ import annotations

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.scrapers.hoqs import HoqsScraper
from tests.conftest import load_fixture


_N185C_URL = "https://hoqs.org/products/n185c-18-neodymium-carbon-fiber-subwoofer"


@pytest.fixture
def scraper() -> HoqsScraper:
    return HoqsScraper()


def test_parse_n185c(scraper: HoqsScraper) -> None:
    raw = load_fixture("hoqs", "products/n185c.html", url=_N185C_URL)
    ctx = SeedContext(driver_kind_hint=DriverKind.LF_WOOFER, category_id="Speaker")
    res = scraper.parse_artifact(raw, ctx)

    assert len(res.fragments) == 1 and res.followups == []
    f = res.fragments[0]

    assert f.manufacturer == "HOQS"
    assert f.model == "N185C"
    assert f.driver_kind == DriverKind.LF_WOOFER

    # T/S from speakerData.thieleSmall
    assert f.fs_hz == pytest.approx(29.5)
    assert f.qts == pytest.approx(0.21)
    assert f.qes == pytest.approx(0.21)
    assert f.qms == pytest.approx(14.0)
    assert f.vas_liters == pytest.approx(242.0)
    assert f.re_ohm == pytest.approx(5.7)
    assert f.sd_cm2 == pytest.approx(1225.0)
    assert f.mms_g == pytest.approx(281.5)
    assert f.bl_tm == pytest.approx(35.7)
    assert f.le_mh == pytest.approx(1.461)
    # HOQS peak-to-peak stored AS-REPORTED (no doubling)
    assert f.xmax_mm == pytest.approx(13.5)
    assert f.xmech_mm == pytest.approx(54.0)

    # sensitivity — HOQS uses SPL @ 2.83V, so the 2.83V slot is populated
    assert f.sensitivity_db_2_83v_1m == pytest.approx(97.5424)
    assert f.sensitivity_db_1w_1m is None

    # electrical / commercial
    assert f.impedance_nominal_ohm == pytest.approx(8.0)
    assert f.power_aes_watts == pytest.approx(1700.0)
    assert f.power_program_watts == pytest.approx(3400.0)

    # physical
    assert f.nominal_size_mm == pytest.approx(457.2)   # 18" → 457.2mm
    assert f.voice_coil_diameter_mm == pytest.approx(125.0)
    assert f.magnet_type == MagnetType.NEODYMIUM

    # spec_source: every populated field marked INLINE_JS
    assert f.spec_source["fs_hz"] == SpecSource.INLINE_JS
    assert f.spec_source["sensitivity_db_2_83v_1m"] == SpecSource.INLINE_JS


def test_parse_emits_minimal_fragment_when_speaker_data_missing(scraper: HoqsScraper) -> None:
    """Some HOQS pages (e.g. N62C) ship `var speakerData = null;` — the T/S
    table lives in a downloadable CSV instead. We still emit a fragment carrying
    just the model + kind so the product appears in the catalog."""
    from driver_base.interface import RawArtifact
    raw = RawArtifact(
        url="https://hoqs.org/products/x",
        body=b'<html><meta property="og:title" content="HOQS X 12\" Test" /></html>',
        status=200, content_type="text/html", fetched_at="", body_sha="",
    )
    res = scraper.parse_artifact(raw, SeedContext())
    assert len(res.fragments) == 1
    assert res.fragments[0].model == "X"
