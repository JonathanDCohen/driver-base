"""merge_fragments_by_id: trivial pass-through + duplicate canonical_id detection."""

from __future__ import annotations

from driver_base.interface import DriverKind
from driver_base.merge import assign_canonical_ids, merge_fragments_by_id
from driver_base.model import DriverFragment


def _frag(**over) -> DriverFragment:
    defaults = dict(
        manufacturer="X",
        source_url="https://example.com/product/x",
        fetched_at="2026-01-01T00:00:00+00:00",
        driver_kind=DriverKind.LF_WOOFER,
        model="M1",
        impedance_nominal_ohm=8.0,
    )
    defaults.update(over)
    return DriverFragment(**defaults)


def test_assign_canonical_ids_populates_id() -> None:
    frags = [_frag(model="18LW1400", impedance_nominal_ohm=8.0)]
    assign_canonical_ids(frags, scraper_name="eighteensound")
    assert frags[0].canonical_id == "eighteensound__18lw1400__8ohm"


def test_trivial_merge_one_fragment_one_driver() -> None:
    frags = [_frag(model="A", impedance_nominal_ohm=8.0)]
    assign_canonical_ids(frags, scraper_name="brand")
    drivers, dropped = merge_fragments_by_id(frags, now_iso="2026-01-02T00:00:00+00:00")
    assert len(drivers) == 1 and dropped == []
    assert drivers[0].canonical_id == "brand__a__8ohm"


def test_duplicate_canonical_id_disambiguates_with_url_slug() -> None:
    """Two fragments with the SAME (model, impedance) but different source_urls
    produce two Driver records; the second gets a dup-suffix + warn_flag."""
    f1 = _frag(
        source_url="https://example.com/products/a-first-url",
        model="A",
        impedance_nominal_ohm=8.0,
    )
    f2 = _frag(
        source_url="https://example.com/products/a-second-url",
        model="A",
        impedance_nominal_ohm=8.0,
    )
    frags = [f1, f2]
    assign_canonical_ids(frags, scraper_name="brand")
    drivers, dropped = merge_fragments_by_id(frags, now_iso="2026-01-02T00:00:00+00:00")
    assert len(drivers) == 2 and dropped == []
    cids = {d.canonical_id for d in drivers}
    assert "brand__a__8ohm" in cids
    assert any(cid.startswith("brand__a__8ohm__dup_") for cid in cids)
    dup_driver = next(d for d in drivers if d.canonical_id != "brand__a__8ohm")
    assert any(
        w.startswith("duplicate_canonical_id_collision") for w in dup_driver.warn_flags
    )


def test_fragment_without_id_is_dropped() -> None:
    frags = [_frag(model="")]  # model empty → build_canonical_id → None
    assign_canonical_ids(frags, scraper_name="brand")
    assert frags[0].canonical_id is None
    drivers, dropped = merge_fragments_by_id(frags, now_iso="2026-01-02T00:00:00+00:00")
    assert drivers == [] and len(dropped) == 1


def test_merge_preserves_prior_scraped_at_by_id() -> None:
    frags = [_frag(model="A", impedance_nominal_ohm=8.0)]
    assign_canonical_ids(frags, scraper_name="brand")
    prior = {"brand__a__8ohm": "2025-12-01T00:00:00+00:00"}
    drivers, _ = merge_fragments_by_id(
        frags, now_iso="2026-01-02T00:00:00+00:00", prior_scraped_at_by_id=prior
    )
    assert drivers[0].scraped_at == "2025-12-01T00:00:00+00:00"
    assert drivers[0].last_scraped_at == "2026-01-02T00:00:00+00:00"
