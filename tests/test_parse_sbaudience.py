"""SB Audience enumerate + two-phase parse (product HTML → datasheet PDF).

Fixture PDFs are the live datasheets (2026-11-06) with raster images
stripped (pypdf `remove_images`) to keep the repo small; stripping was
verified to leave the text layer byte-for-byte identical in extraction.
Expected values below were read off `pdftotext -layout` of the ORIGINAL
PDFs, an extractor independent of the scraper's pypdfium2 path.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from driver_base.interface import DriverKind, SeedContext
from driver_base.model import MagnetType, SpecSource
from driver_base.orchestrator import run_all
from driver_base.scrapers.sbaudience import SBAudienceScraper
from tests.conftest import load_fixture, make_fetcher_factory

_PRODUCTS = "https://www.sbaudience.com/index.php/products"


@pytest.fixture
def scraper() -> SBAudienceScraper:
    return SBAudienceScraper()


def _pdf(scraper: SBAudienceScraper, name: str, ctx: SeedContext):
    raw = load_fixture(
        "sbaudience",
        f"datasheets/{name}.pdf",
        url="https://www.sbaudience.com/index.php/download_file/-/view/1/",
    )
    res = scraper.parse_artifact(raw, ctx)
    assert res.followups == []
    assert len(res.fragments) == 1
    return res.fragments[0]


def _ctx(kind: DriverKind, page: str) -> SeedContext:
    return SeedContext(driver_kind_hint=kind, parent_source_url=f"{_PRODUCTS}/{page}/")


def test_enumerate_nav(scraper: SBAudienceScraper) -> None:
    seed = load_fixture("sbaudience", "seeds/products.html", url=f"{_PRODUCTS}/")
    urls = {p.url: p.context for p in scraper.enumerate([seed]).product_urls}
    # 64 products live on 2026-11-06; the 4 horns are skipped.
    assert len(urls) == 60
    assert not any("/horns/" in u for u in urls)
    assert urls[f"{_PRODUCTS}/woofers/bianco-15mw350/"].driver_kind_hint == (
        DriverKind.LF_WOOFER
    )
    assert urls[f"{_PRODUCTS}/coaxials/rosso-8cx250/"].driver_kind_hint == (
        DriverKind.COAX
    )
    assert urls[f"{_PRODUCTS}/compression-drivers/rosso-65cd-t/"].driver_kind_hint == (
        DriverKind.HF_COMPRESSION
    )
    assert (
        urls[f"{_PRODUCTS}/open-baffle-drivers/nero-18obn500d/"].driver_kind_hint
        == DriverKind.LF_WOOFER
    )


def test_product_page_emits_datasheet_followup(scraper: SBAudienceScraper) -> None:
    url = f"{_PRODUCTS}/compression-drivers/bianco-44cd-pk/"
    raw = load_fixture("sbaudience", "products/bianco-44cd-pk.html", url=url)
    ctx = SeedContext(
        driver_kind_hint=DriverKind.HF_COMPRESSION, category_id="compression-drivers"
    )
    res = scraper.parse_artifact(raw, ctx)
    assert res.fragments == []
    assert len(res.followups) == 1
    f = res.followups[0]
    # Page has two download_file links; the datasheet is the labelled one
    # (3246 is an empty-text link to an older revision).
    assert f.url == "https://www.sbaudience.com/index.php/download_file/-/view/3419/"
    assert f.context.parent_model == "BIANCO-44CD-PK"
    assert f.context.parent_source_url == url
    assert f.context.driver_kind_hint == DriverKind.HF_COMPRESSION


def test_standard_sheet(scraper: SBAudienceScraper) -> None:
    """ROSSO-15SW800 — 3-column layout; `Cone Surround` value is set on the
    row below its label."""
    d = _pdf(
        scraper, "rosso-15sw800", _ctx(DriverKind.LF_WOOFER, "subwoofers/rosso-15sw800")
    )
    assert d.model == "ROSSO-15SW800"
    assert d.source_url == f"{_PRODUCTS}/subwoofers/rosso-15sw800/"
    assert d.driver_kind == DriverKind.LF_WOOFER
    assert d.nominal_size_mm == pytest.approx(381.0)
    assert d.spec_source["nominal_size_mm"] == SpecSource.PDF_TEXT
    # Dimensions & Weight
    assert d.overall_diameter_mm == pytest.approx(394.0)
    assert d.mounting_diameter_mm == pytest.approx(361.4)
    assert d.depth_mm == pytest.approx(168.5)
    assert d.net_weight_kg == pytest.approx(11.63)
    # Specs
    assert d.impedance_nominal_ohm == pytest.approx(8.0)
    assert d.impedance_min_ohm == pytest.approx(5.2)
    assert d.power_aes_watts == pytest.approx(800.0)
    assert d.power_program_watts == pytest.approx(1600.0)  # "3dB greater"
    assert d.power_peak_watts is None
    assert d.sensitivity_db_1w_1m == pytest.approx(99.0)
    assert d.sensitivity_db_2_83v_1m is None  # labelled 1W/1m; derived later
    assert (d.freq_low_hz, d.freq_high_hz) == (45.0, 4600.0)
    assert d.voice_coil_diameter_mm == pytest.approx(99.2)
    assert d.winding_material == "Flat copper clad aluminium"
    assert d.former_material == "Till"
    assert d.flux_density_t == pytest.approx(1.03)
    assert d.magnet_type == MagnetType.CERAMIC
    assert d.surround_material == "Double half roll"
    # Thiele Small Parameters
    assert d.fs_hz == pytest.approx(45.0)
    assert d.re_ohm == pytest.approx(5.2)
    assert d.qes == pytest.approx(0.48)
    assert d.qms == pytest.approx(9.99)
    assert d.qts == pytest.approx(0.46)
    assert d.vas_liters == pytest.approx(87.6)
    assert d.sd_cm2 == pytest.approx(850.1)
    assert d.xmax_mm == pytest.approx(11.28)  # one-way per footnote (3)
    assert d.xmech_mm == pytest.approx(26.0)  # Xdamage, p-p per footnote (4)
    assert d.mms_g == pytest.approx(143.6)
    assert d.bl_tm == pytest.approx(21.1)
    assert d.le_mh == pytest.approx(1.18)
    assert d.cms_mm_per_n == pytest.approx(0.09)
    assert d.rms_ns_per_m == pytest.approx(4.1)
    assert d.eta_zero_pct == pytest.approx(1.64)
    assert d.ebp_hz == pytest.approx(94.0)
    assert d.spec_source["fs_hz"] == SpecSource.PDF_TABLE


def test_image_header_sheet_ignores_graph_axis(scraper: SBAudienceScraper) -> None:
    """BIANCO-18SW450 — column headers are images (no header text to anchor
    on), and graph-axis text below the tables also matches `Bl`."""
    d = _pdf(
        scraper,
        "bianco-18sw450",
        _ctx(DriverKind.LF_WOOFER, "subwoofers/bianco-18sw450"),
    )
    assert d.model == "BIANCO-18SW450"
    assert d.bl_tm == pytest.approx(18.8)
    assert d.fs_hz == pytest.approx(28.0)
    assert d.qts == pytest.approx(0.45)
    assert d.sd_cm2 == pytest.approx(1244.1)
    assert d.impedance_nominal_ohm == pytest.approx(8.0)
    assert d.nominal_size_mm == pytest.approx(457.2)


def test_coax_sheet_splits_lf_hf(scraper: SBAudienceScraper) -> None:
    d = _pdf(scraper, "rosso-8cx250", _ctx(DriverKind.COAX, "coaxials/rosso-8cx250"))
    assert d.model == "ROSSO-8CX250"
    assert d.driver_kind == DriverKind.COAX
    # LF column → generic fields
    assert d.impedance_nominal_ohm == pytest.approx(8.0)
    assert d.impedance_min_ohm == pytest.approx(6.2)
    assert d.power_aes_watts == pytest.approx(250.0)
    assert d.power_program_watts == pytest.approx(500.0)
    assert d.sensitivity_db_2_83v_1m == pytest.approx(94.0)
    assert (d.freq_low_hz, d.freq_high_hz) == (70.0, 9200.0)
    assert d.voice_coil_diameter_mm == pytest.approx(49.5)
    assert d.winding_material == "EISVCAW"
    assert d.former_material == "Till"
    assert d.flux_density_t == pytest.approx(0.88)
    assert d.magnet_type == MagnetType.CERAMIC
    assert d.surround_material == "Cloth triple roll"
    assert d.overall_diameter_mm == pytest.approx(208.0)
    # HF column → coax_hf_* (and the dome material)
    assert d.coax_hf_impedance_nominal_ohm == pytest.approx(8.0)
    assert d.coax_hf_impedance_min_ohm == pytest.approx(7.1)
    assert d.coax_hf_power_aes_watts == pytest.approx(50.0)
    assert (d.coax_hf_freq_low_hz, d.coax_hf_freq_high_hz) == (1100.0, 19400.0)
    assert d.coax_hf_voice_coil_diameter_mm == pytest.approx(44.3)
    assert d.diaphragm_material == "PEEK"
    # HF max power (program-class) and HF sensitivity (2.83V) have no slot.
    assert d.coax_hf_power_peak_watts is None
    assert d.coax_hf_sensitivity_db_1w_1m is None
    # T/S block is the LF section
    assert d.fs_hz == pytest.approx(70.0)
    assert d.re_ohm == pytest.approx(5.3)
    assert d.bl_tm == pytest.approx(11.4)
    assert d.xmax_mm == pytest.approx(5.4)
    assert d.xmech_mm == pytest.approx(24.0)


def test_compression_sheet(scraper: SBAudienceScraper) -> None:
    """ROSSO-65CD-T — 2-column layout, `RDC` for Re, `Depth` for depth,
    `Phase Plug Design` value set on the row below its label."""
    d = _pdf(
        scraper,
        "rosso-65cd-t",
        _ctx(DriverKind.HF_COMPRESSION, "compression-drivers/rosso-65cd-t"),
    )
    assert d.model == "ROSSO-65CD-T"
    assert d.driver_kind == DriverKind.HF_COMPRESSION
    assert d.throat_diameter_mm == pytest.approx(35.6)
    assert d.nominal_size_mm == pytest.approx(1.4 * 25.4)
    assert d.overall_diameter_mm == pytest.approx(156.0)
    assert d.depth_mm == pytest.approx(65.9)
    assert d.net_weight_kg == pytest.approx(3.76)
    assert d.re_ohm == pytest.approx(6.2)
    assert d.power_aes_watts == pytest.approx(70.0)
    assert d.power_program_watts == pytest.approx(140.0)
    assert d.sensitivity_db_1w_1m == pytest.approx(108.0)
    assert (d.freq_low_hz, d.freq_high_hz) == (500.0, 20000.0)
    assert d.recommended_crossover_hz == pytest.approx(1000.0)
    assert d.voice_coil_diameter_mm == pytest.approx(65.0)
    assert d.former_material == "Kapton"
    assert d.diaphragm_material == "Titanium"
    assert d.phase_plug_design == "Annular"
    assert d.flux_density_t == pytest.approx(1.6)
    assert d.fs_hz is None and d.qts is None


def test_value_set_above_its_label(scraper: SBAudienceScraper) -> None:
    """NERO-8MWN400D — `Cone Surround` value sits on the row ABOVE the label."""
    d = _pdf(
        scraper, "nero-8mwn400d", _ctx(DriverKind.LF_WOOFER, "woofers/nero-8mwn400d")
    )
    assert d.surround_material == "Triple roll with damping glue"
    assert d.ebp_hz == pytest.approx(154.0)  # the EBP cell keeps its own value


def test_midrange_with_chamber(scraper: SBAudienceScraper) -> None:
    """NERO-5CCN125D — listed under woofers but titled Midrange → FULLRANGE.
    Ships with a removable rear chamber; T/S and sensitivity are taken from
    the as-shipped `With Chamber` column."""
    d = _pdf(
        scraper, "nero-5ccn125d", _ctx(DriverKind.LF_WOOFER, "woofers/nero-5ccn125d")
    )
    assert d.driver_kind == DriverKind.FULLRANGE
    assert d.nominal_size_mm == pytest.approx(127.0)
    assert d.sensitivity_db_2_83v_1m == pytest.approx(99.0)
    assert d.fs_hz == pytest.approx(360.0)
    assert d.qts == pytest.approx(0.73)
    assert d.vas_liters == pytest.approx(0.3)
    assert d.magnet_type == MagnetType.NEODYMIUM


async def test_orchestrator_followup_handoff(tmp_path: Path) -> None:
    """Seed → product HTML → datasheet PDF through the real orchestrator.
    Proves the followup round carries kind, model and the product-page URL.
    Uses a compression driver: LF_WOOFER is the pipeline's fallback kind, so
    a lost hint would show here."""
    seed_url = f"{_PRODUCTS}/"
    page_url = f"{_PRODUCTS}/compression-drivers/rosso-65cd-t/"
    pdf_url = "https://www.sbaudience.com/index.php/download_file/-/view/3440/"
    factory = make_fetcher_factory(
        {
            seed_url: load_fixture("sbaudience", "seeds/products.html", url=seed_url),
            page_url: load_fixture(
                "sbaudience", "products/rosso-65cd-t.html", url=page_url
            ),
            pdf_url: load_fixture(
                "sbaudience", "datasheets/rosso-65cd-t.pdf", url=pdf_url
            ),
        }
    )

    class Narrow(SBAudienceScraper):
        expected_min_records = 1

    drivers, per_status = await run_all(
        [Narrow()],
        prior=None,
        cache_root=tmp_path / "cache",
        rejections_dir=tmp_path / "rejections",
        fetcher_factory=factory,
        now="2026-11-06T14:30:00+00:00",
    )

    assert per_status["sbaudience"]["status"] == "ok"
    assert len(drivers) == 1
    d = drivers[0]
    assert d.canonical_id == "sbaudience__rosso_65cd_t__8ohm"
    assert d.manufacturer == "SB Audience"
    assert d.source_urls == [page_url]
    assert d.driver_kind == DriverKind.HF_COMPRESSION
    assert d.phase_plug_design == "Annular"
    # power.py fills long-term from AES; sensitivity.py derives 2.83V from 1W @ 8Ω.
    assert d.power_long_term_watts == pytest.approx(70.0)
    assert d.sensitivity_db_2_83v_1m == pytest.approx(108.0)
    assert d.warn_flags == []


def test_model_mismatch_is_flagged(scraper: SBAudienceScraper) -> None:
    ctx = dataclasses.replace(
        _ctx(DriverKind.LF_WOOFER, "subwoofers/rosso-15sw800"),
        parent_model="ROSSO-15SW801",
    )
    d = _pdf(scraper, "rosso-15sw800", ctx)
    assert d.model == "ROSSO-15SW800"  # the datasheet's own title wins
    assert d.warn_flags == ["model_mismatch:page=ROSSO-15SW801,datasheet=ROSSO-15SW800"]


def test_html_where_datasheet_expected_raises(scraper: SBAudienceScraper) -> None:
    """A followup that returns HTML (error page / captcha) must surface as a
    parse exception — the orchestrator records it — not vanish silently."""
    raw = load_fixture(
        "sbaudience",
        "products/rosso-65cd-t.html",
        url="https://www.sbaudience.com/index.php/download_file/-/view/3440/",
    )
    ctx = _ctx(DriverKind.HF_COMPRESSION, "compression-drivers/rosso-65cd-t")
    with pytest.raises(ValueError, match="expected a datasheet PDF"):
        scraper.parse_artifact(raw, ctx)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("rosso-8cx250", DriverKind.COAX),  # subtitle says Coaxial
        ("rosso-65cd-t", DriverKind.HF_COMPRESSION),  # has a throat row
        ("nero-5ccn125d", DriverKind.FULLRANGE),  # subtitle says Midrange
        ("rosso-15sw800", DriverKind.LF_WOOFER),
    ],
)
def test_kind_inferred_when_context_lost(
    scraper: SBAudienceScraper, name: str, kind: DriverKind
) -> None:
    """If the followup context is lost (the orchestrator keys it on the
    final, post-redirect URL), the kind comes from the sheet itself."""
    d = _pdf(scraper, name, SeedContext())
    assert d.driver_kind == kind
    if kind == DriverKind.COAX:
        assert d.coax_hf_impedance_nominal_ohm == pytest.approx(8.0)


def test_product_page_without_datasheet_raises(scraper: SBAudienceScraper) -> None:
    raw = load_fixture("sbaudience", "seeds/products.html", url=f"{_PRODUCTS}/x/y/")
    with pytest.raises(ValueError, match="no datasheet link"):
        scraper.parse_artifact(raw, SeedContext(driver_kind_hint=DriverKind.LF_WOOFER))
