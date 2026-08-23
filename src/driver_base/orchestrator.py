"""Runs all registered scrapers, isolates per-scraper failures, and emits
per_scraper_status for the drivers.json writer.

Pipeline for one scraper (see `docs/framework.md`):
    discover_seeds → fetch seeds → enumerate(seed_arts) → (loop up to
    max_seed_rounds) → fetch products → parse_artifact → followup rounds
    → sanity → classify_driver_kind → assign canonical_id → apply_aliases
    → merge_fragments_by_id → enforce_consistency → gates

Per-scraper isolation: any exception preserves the prior run's records with
`last_scraped_at` bumped but `scraped_at` unchanged, and increments
`consecutive_failures`. After 3 consecutive failures the status escalates to
`blocked`.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from driver_base.aliases import Aliases, apply_aliases, load_aliases
from driver_base.cache import Cache
from driver_base.consistency import enforce_consistency
from driver_base.fetch import HttpxFetcher
from driver_base.interface import (
    DriverKind,
    FetchError,
    FetcherKind,
    RawArtifact,
    Scraper,
    SeedContext,
    SeedRef,
)
from driver_base.merge import assign_canonical_ids, merge_fragments_by_id
from driver_base.model import Driver, DriverFragment
from driver_base.rate_limiter import HostRateLimiter
from driver_base.power import derive_missing_power
from driver_base.rejections import write_rejections_sidecar
from driver_base.robots import RobotsCache
from driver_base.sanity import check_record_count, sanity_check_fragment
from driver_base.sensitivity import derive_missing_sensitivity

MAX_SCRAPER_CONCURRENCY = 4
MAX_FOLLOWUP_ROUNDS = 2


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class ScraperResult:
    scraper_name: str
    manufacturer_display: str
    status: str                              # "ok" | "preserved" | "blocked"
    drivers: list[Driver] = field(default_factory=list)
    reason: Optional[str] = None
    consecutive_failures: int = 0
    last_success_at: Optional[str] = None
    last_run_at: Optional[str] = None
    records_this_run: Optional[int] = None
    records_prior_run: Optional[int] = None
    fetch_stats: dict[str, int] = field(default_factory=dict)
    parse_stats: dict[str, int] = field(default_factory=dict)
    warn_flags: list[str] = field(default_factory=list)
    rejection_sidecar: Optional[str] = None


FetcherFactory = Callable[[Scraper, Cache], HttpxFetcher]


async def run_all(
    scrapers: list[Scraper],
    prior: Optional[dict[str, Any]],
    *,
    cache_root: Path,
    aliases_path: Optional[Path] = None,
    rejections_dir: Path = Path("data/rejections"),
    force_refresh: bool = False,
    fetcher_factory: Optional[FetcherFactory] = None,
    now: Optional[str] = None,
) -> tuple[list[Driver], dict[str, dict[str, Any]]]:
    """Run all scrapers concurrently. Returns (all_drivers, per_scraper_status)."""
    now_iso = now or _iso_now()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    aliases = load_aliases(aliases_path) if aliases_path else Aliases({}, {})
    cache = Cache(cache_root)
    sem = asyncio.Semaphore(MAX_SCRAPER_CONCURRENCY)

    async def _bounded(s: Scraper) -> ScraperResult:
        async with sem:
            return await _run_isolated(
                s,
                prior=prior,
                cache=cache,
                aliases=aliases,
                rejections_dir=rejections_dir,
                force_refresh=force_refresh,
                fetcher_factory=fetcher_factory,
                now_iso=now_iso,
                run_id=run_id,
            )

    results = await asyncio.gather(*[_bounded(s) for s in scrapers])
    all_drivers: list[Driver] = []
    per_status: dict[str, dict[str, Any]] = {}
    for r in results:
        all_drivers.extend(r.drivers)
        per_status[r.scraper_name] = _result_to_status(r, prior=prior, now_iso=now_iso)
    return all_drivers, per_status


def _result_to_status(
    r: ScraperResult, *, prior: Optional[dict[str, Any]], now_iso: str
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": r.status,
        "last_run_at": r.last_run_at or now_iso,
        "last_success_at": r.last_success_at,
        "consecutive_failures": r.consecutive_failures,
        "records_this_run": r.records_this_run,
        "records_prior_run": r.records_prior_run,
        "fetch_stats": r.fetch_stats,
        "parse_stats": r.parse_stats,
        "warn_flags": r.warn_flags,
    }
    if r.reason:
        payload["reason"] = r.reason
    if r.rejection_sidecar:
        payload["rejection_sidecar"] = r.rejection_sidecar
    return payload


class _BoundFetchCtx:
    """Bound per scraper. `fetch()` consults `scraper.preferred_fetcher(url)`
    at both seed- and product-fetch time. In v1, Playwright is not
    implemented, so a PLAYWRIGHT preference degrades gracefully to a
    permanent per-URL FetchError with reason='playwright_unavailable'."""

    def __init__(self, scraper: Scraper, httpx_fetcher: HttpxFetcher) -> None:
        self.scraper = scraper
        self.scraper_name = scraper.name
        self.httpx = httpx_fetcher

    async def fetch(
        self, url: str, *, force_refresh: bool = False
    ) -> "RawArtifact | FetchError":
        kind = self.scraper.preferred_fetcher(url)
        if kind == FetcherKind.PLAYWRIGHT:
            return FetchError(
                url=url, kind="permanent", reason="playwright_unavailable", attempts=0
            )
        if kind == FetcherKind.XLSX:
            # v1: fall through to httpx (works for direct xlsx downloads too)
            pass
        return await self.httpx.fetch(url, force_refresh=force_refresh)

    async def fetch_many(
        self, urls: list[str], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return await asyncio.gather(
            *[self.fetch(u, force_refresh=force_refresh) for u in urls]
        )


async def _run_isolated(
    scraper: Scraper,
    *,
    prior: Optional[dict[str, Any]],
    cache: Cache,
    aliases: Aliases,
    rejections_dir: Path,
    force_refresh: bool,
    fetcher_factory: Optional[FetcherFactory],
    now_iso: str,
    run_id: str,
) -> ScraperResult:
    prior_status = _prior_status(prior, scraper.name)
    consec_failures_prior = int(prior_status.get("consecutive_failures", 0) or 0)
    prior_records = _prior_records_for(prior, scraper.manufacturer_display)
    prior_count = len(prior_records)
    prior_scraped_at_by_id = {
        d["canonical_id"]: d.get("scraped_at", now_iso)
        for d in prior_records
        if "canonical_id" in d
    }
    prior_last_success = prior_status.get("last_success_at")

    fetch_stats = {
        "requested": 0, "cache_hits": 0, "network_fetches": 0,
        "transient_errors": 0, "permanent_errors": 0, "playwright_incidents": 0,
    }

    if fetcher_factory is not None:
        httpx_fetcher = fetcher_factory(scraper, cache)
    else:
        robots = RobotsCache(user_agent=scraper.name)
        limiter = HostRateLimiter(robots=robots)
        httpx_fetcher = HttpxFetcher(
            scraper_name=scraper.name, cache=cache, rate_limiter=limiter
        )
    ctx = _BoundFetchCtx(scraper, httpx_fetcher)

    try:
        product_urls = await _run_seed_phase(scraper, ctx, fetch_stats, force_refresh)
        fragments, dropped = await _run_parse_phase(
            scraper, ctx, product_urls, fetch_stats, force_refresh
        )
        drivers = _post_parse_pipeline(
            scraper,
            fragments,
            aliases=aliases,
            now_iso=now_iso,
            prior_scraped_at_by_id=prior_scraped_at_by_id,
        )
        parse_stats = _parse_stats(fragments, drivers)

        decision, gate_reason = check_record_count(
            records_this_run=len(drivers),
            records_prior_run=prior_count if prior_count else None,
            expected_min_records=scraper.expected_min_records,
        )
        if decision == "preserve":
            sidecar = write_rejections_sidecar(
                scraper_name=scraper.name,
                run_id=run_id,
                rejected=list(dropped[:20]),
                reason=gate_reason or "",
                out_dir=rejections_dir,
            )
            return _preserve_result(
                scraper,
                prior_records,
                prior_last_success=prior_last_success,
                consec_failures_prior=consec_failures_prior,
                now_iso=now_iso,
                reason=gate_reason or "gate_failed",
                fetch_stats=fetch_stats,
                parse_stats=parse_stats,
                records_this_run=len(drivers),
                records_prior_run=prior_count,
                sidecar=str(sidecar),
            )

        return ScraperResult(
            scraper_name=scraper.name,
            manufacturer_display=scraper.manufacturer_display,
            status="ok",
            drivers=drivers,
            reason=None,
            consecutive_failures=0,
            last_success_at=now_iso,
            last_run_at=now_iso,
            records_this_run=len(drivers),
            records_prior_run=prior_count if prior_count else None,
            fetch_stats=fetch_stats,
            parse_stats=parse_stats,
            warn_flags=[],
        )

    except Exception as e:
        sidecar = write_rejections_sidecar(
            scraper_name=scraper.name,
            run_id=run_id,
            rejected=[],
            reason=f"exception:{type(e).__name__}:{e}",
            out_dir=rejections_dir,
        )
        return _preserve_result(
            scraper,
            prior_records,
            prior_last_success=prior_last_success,
            consec_failures_prior=consec_failures_prior,
            now_iso=now_iso,
            reason=f"{type(e).__name__}:{e}",
            fetch_stats=fetch_stats,
            parse_stats={},
            records_this_run=None,
            records_prior_run=prior_count,
            sidecar=str(sidecar),
        )
    finally:
        # Only close if factory wasn't overridden (test uses FakeFetcher).
        if fetcher_factory is None:
            try:
                await httpx_fetcher.aclose()
            except Exception:
                pass


async def _run_seed_phase(
    scraper: Scraper,
    ctx: _BoundFetchCtx,
    fetch_stats: dict[str, int],
    force_refresh: bool,
) -> list[SeedRef]:
    seen_seeds: set[str] = set()
    seen_products: set[str] = set()
    product_urls: list[SeedRef] = []
    current: list[SeedRef] = list(scraper.discover_seeds())
    for round_num in range(scraper.max_seed_rounds):
        new_seeds = [s for s in current if s.url not in seen_seeds]
        if not new_seeds:
            break
        seen_seeds.update(s.url for s in new_seeds)
        arts = await ctx.fetch_many([s.url for s in new_seeds], force_refresh=force_refresh)
        _tally_fetches(arts, fetch_stats)
        seed_arts_ok = [a for a in arts if isinstance(a, RawArtifact)]
        enum = scraper.enumerate(seed_arts_ok)
        new_products = [p for p in enum.product_urls if p.url not in seen_products]
        if not new_products and round_num > 0:
            break
        seen_products.update(p.url for p in new_products)
        product_urls.extend(new_products)
        current = list(enum.additional_seed_urls)
    return product_urls


async def _run_parse_phase(
    scraper: Scraper,
    ctx: _BoundFetchCtx,
    product_urls: list[SeedRef],
    fetch_stats: dict[str, int],
    force_refresh: bool,
) -> tuple[list[DriverFragment], list[dict]]:
    url_to_ctx = {p.url: p.context for p in product_urls}
    arts = await ctx.fetch_many([p.url for p in product_urls], force_refresh=force_refresh)
    _tally_fetches(arts, fetch_stats)

    fragments: list[DriverFragment] = []
    pending_followups: list[SeedRef] = []
    dropped_dbg: list[dict] = []
    for r in arts:
        if not isinstance(r, RawArtifact):
            dropped_dbg.append({"url": r.url, "reason": r.reason, "kind": r.kind})
            continue
        try:
            res = scraper.parse_artifact(r, url_to_ctx.get(r.url, SeedContext()))
        except Exception as e:
            dropped_dbg.append({"url": r.url, "reason": f"parse_exception:{type(e).__name__}:{e}"})
            continue
        fragments.extend(res.fragments)
        pending_followups.extend(res.followups)

    for _round in range(MAX_FOLLOWUP_ROUNDS):
        if not pending_followups:
            break
        f_urls = [f.url for f in pending_followups]
        f_ctx_map = {f.url: f.context for f in pending_followups}
        f_arts = await ctx.fetch_many(f_urls, force_refresh=force_refresh)
        _tally_fetches(f_arts, fetch_stats)
        new_pending: list[SeedRef] = []
        for r in f_arts:
            if not isinstance(r, RawArtifact):
                continue
            try:
                res = scraper.parse_artifact(r, f_ctx_map.get(r.url, SeedContext()))
            except Exception:
                continue
            fragments.extend(res.fragments)
            new_pending.extend(res.followups)
        pending_followups = new_pending

    return fragments, dropped_dbg


def _post_parse_pipeline(
    scraper: Scraper,
    fragments: list[DriverFragment],
    *,
    aliases: Aliases,
    now_iso: str,
    prior_scraped_at_by_id: dict[str, str],
) -> list[Driver]:
    for f in fragments:
        sanity_check_fragment(f)

    for f in fragments:
        derive_missing_sensitivity(f)
        derive_missing_power(f)

    for f in fragments:
        if f.driver_kind is None:
            resolved = scraper.classify_driver_kind(f)
            f.driver_kind = resolved or DriverKind.LF_WOOFER

    assign_canonical_ids(fragments, scraper_name=scraper.name)
    fragments = apply_aliases(fragments, aliases)
    drivers, _dropped = merge_fragments_by_id(
        fragments,
        now_iso=now_iso,
        prior_scraped_at_by_id=prior_scraped_at_by_id,
    )
    drivers, _rejected = enforce_consistency(drivers)
    return drivers


def _tally_fetches(
    arts: list["RawArtifact | FetchError"], stats: dict[str, int]
) -> None:
    for r in arts:
        stats["requested"] += 1
        if isinstance(r, RawArtifact):
            if r.from_cache:
                stats["cache_hits"] += 1
            else:
                stats["network_fetches"] += 1
        else:
            if r.kind == "transient":
                stats["transient_errors"] += 1
            else:
                stats["permanent_errors"] += 1
            if r.reason == "playwright_unavailable":
                stats["playwright_incidents"] += 1


def _parse_stats(
    fragments: list[DriverFragment], drivers: list[Driver]
) -> dict[str, int]:
    return {
        "fragments_parsed": len(fragments),
        "fragments_after_merge": len(drivers),
        "records_rejected": len(fragments) - len(drivers),
        "warn_flags_total": sum(len(d.warn_flags) for d in drivers),
    }


def _prior_status(
    prior: Optional[dict[str, Any]], scraper_name: str
) -> dict[str, Any]:
    if not prior:
        return {}
    return (prior.get("per_scraper_status") or {}).get(scraper_name) or {}


def _prior_records_for(
    prior: Optional[dict[str, Any]], manufacturer_display: str
) -> list[dict[str, Any]]:
    if not prior:
        return []
    return [
        d for d in (prior.get("drivers") or [])
        if d.get("manufacturer") == manufacturer_display
    ]


def _preserve_result(
    scraper: Scraper,
    prior_records: list[dict[str, Any]],
    *,
    prior_last_success: Optional[str],
    consec_failures_prior: int,
    now_iso: str,
    reason: str,
    fetch_stats: dict[str, int],
    parse_stats: dict[str, int],
    records_this_run: Optional[int],
    records_prior_run: int,
    sidecar: Optional[str],
) -> ScraperResult:
    consec = consec_failures_prior + 1
    status = "blocked" if consec >= 3 else "preserved"
    # rehydrate prior records as Drivers, preserving scraped_at, bumping last_scraped_at
    preserved_drivers = _rehydrate_drivers(prior_records, now_iso=now_iso)
    return ScraperResult(
        scraper_name=scraper.name,
        manufacturer_display=scraper.manufacturer_display,
        status=status,
        drivers=preserved_drivers,
        reason=reason,
        consecutive_failures=consec,
        last_success_at=prior_last_success,
        last_run_at=now_iso,
        records_this_run=records_this_run,
        records_prior_run=records_prior_run,
        fetch_stats=fetch_stats,
        parse_stats=parse_stats,
        warn_flags=[],
        rejection_sidecar=sidecar,
    )


def _rehydrate_drivers(
    prior_records: list[dict[str, Any]], *, now_iso: str
) -> list[Driver]:
    """Preserve-on-failure path: rehydrate prior records with `last_scraped_at`
    bumped to `now_iso` (scraped_at stays)."""
    return rehydrate_drivers(prior_records, now_iso=now_iso)


def rehydrate_drivers(
    prior_records: list[dict[str, Any]], *, now_iso: Optional[str] = None
) -> list[Driver]:
    """Turn prior drivers.json records back into Driver dataclasses.

    Passing `now_iso=None` keeps each record's own `last_scraped_at` — used by
    the CLI's per-scraper regen path where an unrun scraper's records must
    pass through untouched. Passing an ISO timestamp bumps `last_scraped_at`
    (used by the preserve-on-failure branch)."""
    from dataclasses import fields as dc_fields

    driver_fields = {f.name: f for f in dc_fields(Driver)}
    out: list[Driver] = []
    for rec in prior_records:
        kwargs: dict[str, Any] = {}
        for name in driver_fields:
            if name == "last_scraped_at" and now_iso is not None:
                kwargs[name] = now_iso
                continue
            v = rec.get(name)
            kwargs[name] = _coerce_field(name, v)
        try:
            out.append(Driver(**kwargs))
        except TypeError:
            continue
    return out


def _coerce_field(name: str, v: Any) -> Any:
    from driver_base.model import DriverStatus, MagnetType, SpecSource

    if v is None:
        return None
    if name == "driver_kind" and isinstance(v, str):
        try:
            return DriverKind(v)
        except ValueError:
            return DriverKind.LF_WOOFER
    if name == "status" and isinstance(v, str):
        try:
            return DriverStatus(v)
        except ValueError:
            return DriverStatus.ACTIVE
    if name == "magnet_type" and isinstance(v, str):
        try:
            return MagnetType(v)
        except ValueError:
            return None
    if name == "spec_source" and isinstance(v, dict):
        out: dict[str, SpecSource] = {}
        for k, val in v.items():
            try:
                out[k] = SpecSource(val)
            except ValueError:
                continue
        return out
    return v
