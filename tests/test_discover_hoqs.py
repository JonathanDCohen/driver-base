"""HOQS discover_seeds + enumerate + model extraction."""

from __future__ import annotations

from driver_base.interface import DriverKind, SeedContext
from driver_base.scrapers.hoqs import HoqsScraper
from tests.conftest import load_fixture


def test_discover_seeds_yields_one_shopify_endpoint() -> None:
    seeds = HoqsScraper().discover_seeds()
    assert len(seeds) == 1
    assert seeds[0].url == "https://hoqs.org/products.json?limit=250&page=1"


def test_enumerate_filters_non_drivers_and_tags_kind() -> None:
    """Enumerate should skip Amplifier and Recone product_types, keep Horn/
    Compression Driver/Speaker, and derive driver_kind_hint per entry."""
    s = HoqsScraper()
    seed = load_fixture(
        "hoqs", "seeds/products.json",
        url="https://hoqs.org/products.json?limit=250&page=1",
    )
    res = s.enumerate([seed])
    urls_kinds = [(p.url.rsplit("/", 1)[-1], p.context.driver_kind_hint) for p in res.product_urls]

    # Sanity: at least the well-known drivers are present with correct kinds
    d = dict(urls_kinds)
    assert d["hoqs-hf143n-1-4"] == DriverKind.HF_COMPRESSION
    assert d["n185c-18-neodymium-carbon-fiber-subwoofer"] == DriverKind.LF_WOOFER
    assert d["hoqs-n123"] == DriverKind.LF_WOOFER
    assert d["hoqs-bh1"] == DriverKind.HORN
    assert d["hoqs-wg6"] == DriverKind.HORN

    # Amplifier + Recone are dropped
    handles = {u for u, _ in urls_kinds}
    assert "hoqs-4x1k-amplifier" not in handles
    assert "hoqs-4x3k-amplifier" not in handles
    assert "hoqs-3-recone-hf143n-rk" not in handles


def test_model_extracted_from_og_title_not_legacy_handle() -> None:
    """A handful of HOQS product URLs have legacy slugs that no longer match the
    current SKU (e.g. `hoqs-carbon-fiber-18` is now the F185C). The model must
    come from the storefront's og:title, not the handle."""
    s = HoqsScraper()
    raw = load_fixture(
        "hoqs", "products/f185c-legacy-slug.html",
        url="https://hoqs.org/products/hoqs-carbon-fiber-18",
    )
    res = s.parse_artifact(raw, SeedContext(driver_kind_hint=DriverKind.LF_WOOFER))
    assert len(res.fragments) == 1
    assert res.fragments[0].model == "F185C"
