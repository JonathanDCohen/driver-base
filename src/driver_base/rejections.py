"""Rejection sidecar writer. Called on every run that has rejected fragments
or a preserved/blocked scraper status; enables --dry-run debugging without
opening the main drivers.json. One file per scraper — the current run
overwrites the previous, so `data/rejections/` only ever shows the latest."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


def write_rejections_sidecar(
    *,
    scraper_name: str,
    rejected: list[Any],
    reason: str = "",
    out_dir: Path = Path("data/rejections"),
    max_records: int = 20,
) -> Path:
    """Write data/rejections/{scraper}.json. Overwrites any prior run's file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{scraper_name}.json"
    payload = {
        "scraper": scraper_name,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "rejected_count": len(rejected),
        "sample": rejected[:max_records],
    }
    path.write_text(json.dumps(payload, default=_json_default, indent=2))
    return path
