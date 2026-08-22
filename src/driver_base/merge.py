"""Assign canonical_ids, apply aliases, merge fragments → Driver records.

v1 merge is a trivial pass-through: one DriverFragment becomes one Driver. If
two fragments (after alias rewrite) share a canonical_id, both are emitted with
a URL-slug disambiguation suffix and a `duplicate_canonical_id_collision`
warn_flag; the future multi-fragment merge machinery will handle real
conflict-resolution.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Optional

from driver_base.aliases import Aliases, apply_aliases
from driver_base.id import build_canonical_id, slugify
from driver_base.interface import DriverKind
from driver_base.model import Driver, DriverFragment, DriverStatus


def assign_canonical_ids(
    fragments: list[DriverFragment], *, scraper_name: str
) -> list[DriverFragment]:
    """Populate `canonical_id` on each fragment via `build_canonical_id`."""
    for f in fragments:
        f.canonical_id = build_canonical_id(
            manufacturer_slug=scraper_name,
            model=f.model,
            impedance_ohm=f.impedance_nominal_ohm,
            source_url=f.source_url,
            canonical_id_seed=f.canonical_id_seed,
        )
    return fragments


def merge_fragments_by_id(
    fragments: list[DriverFragment],
    *,
    now_iso: str,
    prior_scraped_at_by_id: Optional[dict[str, str]] = None,
) -> tuple[list[Driver], list[DriverFragment]]:
    """Trivial pass-through: 1 fragment → 1 Driver.

    Duplicate canonical_ids are disambiguated with a URL-slug suffix and a
    `duplicate_canonical_id_collision` warn_flag. Fragments without a
    canonical_id are dropped and returned in the rejected list.

    Returns (drivers, dropped_fragments).
    """
    prior_scraped = prior_scraped_at_by_id or {}
    kept: list[Driver] = []
    dropped: list[DriverFragment] = []
    seen: dict[str, int] = {}

    for f in fragments:
        if not f.canonical_id:
            dropped.append(f)
            continue
        cid = f.canonical_id
        if cid in seen:
            seen[cid] += 1
            suffix = _url_slug(f.source_url) or f"v{seen[cid]}"
            new_cid = f"{cid}__dup_{suffix}"
            f.warn_flags.append(f"duplicate_canonical_id_collision:{cid}")
            cid = new_cid
        seen.setdefault(cid, 1)
        kept.append(_fragment_to_driver(f, cid, now_iso=now_iso, prior_scraped=prior_scraped))

    return kept, dropped


def _url_slug(source_url: str) -> Optional[str]:
    if not source_url:
        return None
    from urllib.parse import urlparse

    tail = urlparse(source_url).path.rstrip("/").rsplit("/", 1)[-1]
    return slugify(tail) or None


_DRIVER_FIELD_NAMES = {f.name for f in dc_fields(Driver)}


def _fragment_to_driver(
    f: DriverFragment,
    cid: str,
    *,
    now_iso: str,
    prior_scraped: dict[str, str],
) -> Driver:
    """Copy Fragment fields onto a Driver. Kind None defaults to LF_WOOFER
    (should have been resolved via classify_driver_kind by now)."""
    kind = f.driver_kind or DriverKind.LF_WOOFER
    scraped_at = prior_scraped.get(cid, f.fetched_at)
    d = Driver(
        manufacturer=f.manufacturer,
        canonical_id=cid,
        driver_kind=kind,
        model=f.model,
        spec_source=dict(f.spec_source),
        source_urls=[f.source_url] if f.source_url else [],
        fetched_at=f.fetched_at,
        scraped_at=scraped_at,
        last_scraped_at=now_iso,
        status=f.status if isinstance(f.status, DriverStatus) else DriverStatus.ACTIVE,
        warn_flags=list(f.warn_flags),
    )
    # Copy every other numeric/enum field by name.
    _SKIP = {"manufacturer", "canonical_id", "driver_kind", "model", "spec_source",
             "source_urls", "fetched_at", "scraped_at", "last_scraped_at",
             "status", "warn_flags"}
    for name in _DRIVER_FIELD_NAMES:
        if name in _SKIP:
            continue
        setattr(d, name, getattr(f, name, None))
    return d
