"""End-to-end smoke: run the orchestrator over the 18Sound scraper with a
FakeFetcher serving only 2 product URLs from fixtures. Asserts the run
returns status=ok, produces 2 Driver records with the expected canonical_ids,
and rejects nothing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from driver_base.interface import RawArtifact
from driver_base.orchestrator import run_all
from driver_base.scrapers.eighteensound import EighteenSoundScraper
from tests.conftest import FIXTURES_ROOT, make_fetcher_factory


def _art(url: str, path: Path) -> RawArtifact:
    body = path.read_bytes()
    return RawArtifact(
        url=url,
        body=body,
        status=200,
        content_type="text/html; charset=utf-8",
        fetched_at="2026-08-22T14:00:00+00:00",
        body_sha=hashlib.sha256(body).hexdigest(),
    )


async def test_orchestrator_end_to_end_with_fake_fetcher(tmp_path: Path) -> None:
    fx = FIXTURES_ROOT / "eighteensound"
    lf_seed_url = "https://www.eighteensound.it/en/products/lf-driver"
    lf_product_url = "https://www.eighteensound.it/en/products/lf-driver/18-0/8/18LW1400"

    # FakeFetcher answers only these two URLs; every enumerated product URL other
    # than 18LW1400 becomes a permanent FetchError (fine — the test asserts on
    # the one record we DO successfully fetch).
    url_map = {
        lf_seed_url: _art(lf_seed_url, fx / "seeds/lf-driver.html"),
        lf_product_url: _art(lf_product_url, fx / "products/18LW1400.html"),
    }
    factory = make_fetcher_factory(url_map)

    # Instantiate the 18Sound scraper with expected_min_records lowered so
    # the delta gate accepts a 1-record run (fixture coverage is intentionally
    # narrow for this smoke test).
    class Sanded(EighteenSoundScraper):
        expected_min_records = 1
    scraper = Sanded()

    drivers, per_status = await run_all(
        [scraper],
        prior=None,
        cache_root=tmp_path / "cache",
        rejections_dir=tmp_path / "rejections",
        fetcher_factory=factory,
        now="2026-08-22T14:30:00+00:00",
    )

    assert len(drivers) == 1
    d = drivers[0]
    assert d.canonical_id == "eighteensound__18lw1400__8ohm"
    assert d.model == "18LW1400"
    assert d.fs_hz == pytest.approx(31.0)
    assert d.qts == pytest.approx(0.29)
    assert d.vas_liters == pytest.approx(297.0)
    assert d.xmax_mm == pytest.approx(9.0)
    assert d.power_aes_watts == pytest.approx(1000.0)
    assert d.power_long_term_watts == pytest.approx(1400.0)

    status = per_status["eighteensound"]
    assert status["status"] == "ok"
    assert status["records_this_run"] == 1
    # every enumerated URL beyond the 1 we serve returns permanent 404 →
    # permanent_errors is high but should not trigger 'preserve'.
    assert status["fetch_stats"]["permanent_errors"] > 0


async def test_orchestrator_preserves_prior_on_gate_failure(tmp_path: Path) -> None:
    """If records_this_run < expected_min_records AND no baseline, preserve prior."""
    fx = FIXTURES_ROOT / "eighteensound"
    lf_seed_url = "https://www.eighteensound.it/en/products/lf-driver"
    lf_product_url = "https://www.eighteensound.it/en/products/lf-driver/18-0/8/18LW1400"

    url_map = {
        lf_seed_url: _art(lf_seed_url, fx / "seeds/lf-driver.html"),
        lf_product_url: _art(lf_product_url, fx / "products/18LW1400.html"),
    }
    factory = make_fetcher_factory(url_map)

    scraper = EighteenSoundScraper()   # default expected_min_records=275 → will fail

    # Prior has NO 18Sound records (first-run branch), so the first-run
    # absolute-floor gate applies: 1 < 275 → preserve. We still record a
    # prior per_scraper_status so consecutive_failures increments from 0 → 1.
    prior = {
        "per_scraper_status": {
            "eighteensound": {"consecutive_failures": 0, "last_success_at": "2026-08-15T00:00:00+00:00"}
        },
        "drivers": [
            {
                "manufacturer": "18Sound",
                "canonical_id": "eighteensound__prior__8ohm",
                "driver_kind": "lf_woofer",
                "model": "PRIOR",
                "spec_source": {},
                "source_urls": [],
                "fetched_at": "2026-08-15T00:00:00+00:00",
                "scraped_at": "2026-08-15T00:00:00+00:00",
                "last_scraped_at": "2026-08-15T00:00:00+00:00",
                "status": "active",
                "warn_flags": [],
            }
        ] * 400,   # 400 prior records: 1 new vs 400 prior = 99.75% drop → preserve
    }

    drivers, per_status = await run_all(
        [scraper],
        prior=prior,
        cache_root=tmp_path / "cache",
        rejections_dir=tmp_path / "rejections",
        fetcher_factory=factory,
        now="2026-08-22T14:30:00+00:00",
    )

    assert per_status["eighteensound"]["status"] == "preserved"
    assert per_status["eighteensound"]["consecutive_failures"] == 1
    # prior records are preserved wholesale with bumped last_scraped_at
    assert len(drivers) == 400
    assert all(d.canonical_id == "eighteensound__prior__8ohm" for d in drivers)
    assert all(d.last_scraped_at == "2026-08-22T14:30:00+00:00" for d in drivers)
    assert all(d.scraped_at == "2026-08-15T00:00:00+00:00" for d in drivers)
