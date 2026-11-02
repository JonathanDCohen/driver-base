"""One-off: reparse Dayton product pages from the on-disk cache against the
current parser, then write drivers.json with the fresh Dayton records merged
in. Needed when Dayton's seed pages are bot-blocked (Incapsula) so the normal
scrape path can't reach product discovery, but product-page bodies are still
cached and we want a parser-only improvement (e.g. Sd thousands-comma fix) to
take effect without waiting for the block to lift.

Reads prior drivers.json for Dayton source_urls + driver_kind, bypasses the
cache TTL (the product cache is from August), skips Incapsula block pages,
runs the same post-parse pipeline the orchestrator runs, and rewrites
drivers.json. per_scraper_status for Dayton is left intact (still 'blocked')
since no live scrape happened.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from driver_base import __version__
from driver_base.aliases import Aliases, apply_aliases
from driver_base.consistency import enforce_consistency
from driver_base.derived import derive_ebp, derive_vd
from driver_base.interface import RawArtifact, SeedContext
from driver_base.merge import assign_canonical_ids, merge_fragments_by_id
from driver_base.model import DriverKind
from driver_base.orchestrator import rehydrate_drivers
from driver_base.power import derive_missing_power
from driver_base.sanity import sanity_check_fragment
from driver_base.schema import read_prior_drivers_json, write_drivers_json
from driver_base.scrapers import instantiate_all
from driver_base.sensitivity import derive_missing_sensitivity

CACHE_ROOT = Path("data/cache")
OUTPUT = Path("web/drivers.json")
NOW_ISO = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
MANUFACTURER = "Dayton Audio"
SCRAPER = "dayton"


def _key(scraper_name: str, url: str) -> str:
    h = hashlib.sha256()
    h.update(scraper_name.encode("utf-8"))
    h.update(b":")
    h.update(url.encode("utf-8"))
    return h.hexdigest()


def _read_cached(scraper_name: str, url: str) -> RawArtifact | None:
    k = _key(scraper_name, url)
    body_p = CACHE_ROOT / scraper_name / k[:2] / f"{k}.body"
    meta_p = CACHE_ROOT / scraper_name / k[:2] / f"{k}.meta.json"
    if not body_p.exists() or not meta_p.exists():
        return None
    meta = json.loads(meta_p.read_text())
    body = body_p.read_bytes()
    return RawArtifact(
        url=meta.get("url", url),
        body=body,
        status=int(meta.get("status", 200)),
        content_type=meta.get("content_type", ""),
        fetched_at=meta["fetched_at"],
        body_sha=meta.get("body_sha", hashlib.sha256(body).hexdigest()),
        from_cache=True,
    )


def _is_block_page(body: bytes) -> bool:
    head = body[:4096].decode("utf-8", errors="ignore")
    return "Incapsula incident" in head or "_Incapsula_Resource" in head


def main() -> int:
    prior = read_prior_drivers_json(OUTPUT)
    if prior is None:
        print(f"error: no prior drivers.json at {OUTPUT}")
        return 2
    scraper = next(s for s in instantiate_all() if s.name == SCRAPER)

    prior_dayton = [
        d for d in prior["drivers"] if d.get("manufacturer") == MANUFACTURER
    ]
    prior_scraped_at_by_id = {
        d["canonical_id"]: d.get("scraped_at", NOW_ISO)
        for d in prior_dayton
        if "canonical_id" in d
    }

    fragments: list = []
    missing_cache = 0
    blocked_pages = 0
    no_fragments = 0
    unparsed_records: list[dict] = []
    for rec in prior_dayton:
        kind_name = rec.get("driver_kind")
        try:
            kind_hint = DriverKind(kind_name) if kind_name else None
        except ValueError:
            kind_hint = None
        urls = rec.get("source_urls") or []
        any_parsed = False
        for url in urls:
            raw = _read_cached(SCRAPER, url)
            if raw is None:
                missing_cache += 1
                continue
            if _is_block_page(raw.body):
                blocked_pages += 1
                continue
            res = scraper.parse_artifact(raw, SeedContext(driver_kind_hint=kind_hint))
            if not res.fragments:
                no_fragments += 1
                continue
            any_parsed = True
            fragments.extend(res.fragments)
        if not any_parsed:
            unparsed_records.append(rec)

    print(
        f"product URLs: parsed_fragments={len(fragments)} "
        f"cache_miss={missing_cache} blocked_pages={blocked_pages} "
        f"empty_parse={no_fragments}"
    )

    for f in fragments:
        sanity_check_fragment(f)
    for f in fragments:
        derive_missing_sensitivity(f)
        derive_missing_power(f)
        derive_vd(f)
        derive_ebp(f)
    for f in fragments:
        if f.driver_kind is None:
            resolved = scraper.classify_driver_kind(f)
            f.driver_kind = resolved or DriverKind.LF_WOOFER
    fragments = [f for f in fragments if f.driver_kind is not DriverKind.HORN]

    assign_canonical_ids(fragments, scraper_name=SCRAPER)
    fragments = apply_aliases(fragments, Aliases({}, {}))
    drivers, _dropped = merge_fragments_by_id(
        fragments, now_iso=NOW_ISO, prior_scraped_at_by_id=prior_scraped_at_by_id
    )
    drivers, _rejected = enforce_consistency(drivers)
    rehydrated_dayton = rehydrate_drivers(unparsed_records, now_iso=None)
    print(
        f"merged dayton drivers: {len(drivers)} reparsed + "
        f"{len(rehydrated_dayton)} preserved (no cache)"
    )

    non_dayton = [d for d in prior["drivers"] if d.get("manufacturer") != MANUFACTURER]
    others = rehydrate_drivers(non_dayton, now_iso=None)

    per_status = dict(prior.get("per_scraper_status", {}))

    write_drivers_json(
        path=OUTPUT,
        per_scraper_status=per_status,
        drivers=list(drivers) + list(rehydrated_dayton) + list(others),
        generator_version=__version__,
    )
    print(f"wrote {OUTPUT}: {len(drivers) + len(others)} total drivers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
