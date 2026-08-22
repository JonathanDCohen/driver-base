"""18Sound discover_seeds + enumerate."""

from __future__ import annotations

from driver_base.interface import DriverKind, FetcherKind
from driver_base.scrapers.eighteensound import EighteenSoundScraper
from tests.conftest import load_fixture


def test_discover_seeds_has_six_categories() -> None:
    s = EighteenSoundScraper()
    seeds = s.discover_seeds()
    assert len(seeds) == 6
    assert {seed.context.category_id for seed in seeds} == {
        "lf-driver", "hf-driver", "coaxial", "line-array-source", "horn", "tweeter",
    }
    tweeter = next(seed for seed in seeds if seed.context.category_id == "tweeter")
    assert tweeter.context.driver_kind_hint == DriverKind.TWEETER


def test_preferred_fetcher_routes_tweeter_to_playwright() -> None:
    s = EighteenSoundScraper()
    assert s.preferred_fetcher("https://www.eighteensound.it/en/products/tweeter") == FetcherKind.PLAYWRIGHT
    assert s.preferred_fetcher("https://www.eighteensound.it/en/products/lf-driver") is None
    # Product pages under tweeter are static; only the CATEGORY-listing seed is JS.
    assert s.preferred_fetcher(
        "https://www.eighteensound.it/en/products/tweeter/1-25/8/nsd1095n"
    ) is None


def test_enumerate_lf_category_yields_all_products() -> None:
    s = EighteenSoundScraper()
    raw = load_fixture(
        "eighteensound", "seeds/lf-driver.html",
        url="https://www.eighteensound.it/en/products/lf-driver",
    )
    res = s.enumerate([raw])
    # Recon reported 194 unique LF product URLs; case-insensitive dedup may
    # collapse a few. Assert ≥180 and every URL matches the expected pattern.
    assert len(res.product_urls) >= 180
    for p in res.product_urls:
        assert p.url.startswith("https://www.eighteensound.it/en/products/lf-driver/")
        assert p.context.driver_kind_hint == DriverKind.LF_WOOFER
        assert p.context.category_id == "lf-driver"
    assert res.additional_seed_urls == []


def test_enumerate_dedups_case_insensitively() -> None:
    """Two seed pages that both list overlapping URLs (case-varying) should
    dedup to one entry per unique URL (case-insensitive)."""
    s = EighteenSoundScraper()
    raw = load_fixture(
        "eighteensound", "seeds/lf-driver.html",
        url="https://www.eighteensound.it/en/products/lf-driver",
    )
    res = s.enumerate([raw, raw])   # same seed twice
    urls = [p.url for p in res.product_urls]
    assert len(urls) == len(set(u.lower() for u in urls))
