"""CLI entrypoint. Usage:

    uv run driver-base [--output PATH] [--cache-root PATH] [--scraper NAME]
                       [--refetch] [--rejections-dir PATH] [--aliases PATH]

Runs every registered scraper (or a single filtered one via --scraper), applies
all gates, and writes the merged drivers.json.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from driver_base import __version__
from driver_base.orchestrator import rehydrate_drivers, run_all
from driver_base.schema import read_prior_drivers_json, write_drivers_json
from driver_base.scrapers import SCRAPERS, instantiate_all


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="driver-base",
        description="Scrape speaker-driver catalogs and emit drivers.json",
    )
    p.add_argument("--output", type=Path, default=Path("web/drivers.json"))
    p.add_argument("--cache-root", type=Path, default=Path("data/cache"))
    p.add_argument("--rejections-dir", type=Path, default=Path("data/rejections"))
    p.add_argument("--aliases", type=Path, default=Path("data/aliases.yaml"))
    p.add_argument(
        "--scraper", action="append", default=None,
        help="Run only the named scraper(s); may be repeated. Default: all.",
    )
    p.add_argument("--refetch", action="store_true", help="Bypass HTTP cache reads.")
    p.add_argument("--list-scrapers", action="store_true", help="Print registered scraper names and exit.")
    return p.parse_args(argv)


async def _amain(args: argparse.Namespace) -> int:
    all_scrapers = instantiate_all()
    if args.scraper:
        wanted = set(args.scraper)
        run_scrapers = [s for s in all_scrapers if s.name in wanted]
        missing = wanted - {s.name for s in run_scrapers}
        if missing:
            print(f"error: unknown scraper(s): {sorted(missing)}", file=sys.stderr)
            return 2
    else:
        run_scrapers = all_scrapers
    if not run_scrapers:
        print("error: no scrapers registered / selected", file=sys.stderr)
        return 2

    prior = read_prior_drivers_json(args.output)
    aliases_path = args.aliases if args.aliases.exists() else None

    drivers, per_status = await run_all(
        run_scrapers,
        prior=prior,
        cache_root=args.cache_root,
        aliases_path=aliases_path,
        rejections_dir=args.rejections_dir,
        force_refresh=args.refetch,
    )

    # Per-manufacturer regen: preserve records + per_scraper_status for any
    # scraper NOT in this run, so a `--scraper jensen` invocation doesn't
    # nuke the other 9 manufacturers' data.
    if prior:
        run_names = {s.name for s in run_scrapers}
        prior_status = prior.get("per_scraper_status") or {}
        prior_records = prior.get("drivers") or []
        for s in all_scrapers:
            if s.name in run_names:
                continue
            if s.name in prior_status:
                per_status[s.name] = prior_status[s.name]
            belonging = [
                r for r in prior_records
                if r.get("manufacturer") == s.manufacturer_display
            ]
            if belonging:
                drivers.extend(rehydrate_drivers(belonging, now_iso=None))

    write_drivers_json(
        path=args.output,
        per_scraper_status=per_status,
        drivers=drivers,
        generator_version=__version__,
    )

    ok = sum(1 for s in per_status.values() if s.get("status") == "ok")
    preserved = sum(1 for s in per_status.values() if s.get("status") == "preserved")
    blocked = sum(1 for s in per_status.values() if s.get("status") == "blocked")
    print(
        f"wrote {args.output}: "
        f"{len(drivers)} drivers | scrapers ok={ok} preserved={preserved} blocked={blocked}"
    )
    for name, st in per_status.items():
        tag = st.get("status", "?")
        reason = f" ({st.get('reason')})" if st.get("reason") else ""
        print(
            f"  {tag:>9} {name}: "
            f"records={st.get('records_this_run')} "
            f"fetches={st.get('fetch_stats', {}).get('network_fetches')} "
            f"errors_perm={st.get('fetch_stats', {}).get('permanent_errors')}"
            f"{reason}"
        )
    return 0 if blocked == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.list_scrapers:
        # Ensure scrapers are imported/registered before listing.
        instantiate_all()
        for name in sorted(SCRAPERS):
            print(name)
        return 0
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
