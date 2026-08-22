"""Top-level drivers.json writer + SchemaVersion parser."""

from __future__ import annotations

import json
from dataclasses import asdict, fields as dc_fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from driver_base.model import Driver

SCHEMA_VERSION = "1.0"


class SchemaVersion:
    def __init__(self, major: int, minor: int) -> None:
        self.major = major
        self.minor = minor

    @classmethod
    def parse(cls, s: str) -> "SchemaVersion":
        parts = s.strip().split(".")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError(f"invalid schema_version {s!r}")
        return cls(int(parts[0]), int(parts[1]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SchemaVersion):
            return NotImplemented
        return self.major == other.major and self.minor == other.minor


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj):
        return _asdict_no_none_defaults(obj)
    return str(obj)


def _asdict_no_none_defaults(obj: Any) -> dict[str, Any]:
    """Like dataclasses.asdict but keeps enum values as strings via _json_default."""
    out: dict[str, Any] = {}
    for f in dc_fields(obj):
        val = getattr(obj, f.name)
        out[f.name] = _serialize(val)
    return out


def _serialize(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, dict):
        return {k: _serialize(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_serialize(x) for x in v]
    if is_dataclass(v):
        return _asdict_no_none_defaults(v)
    return v


def write_drivers_json(
    *,
    path: Path,
    per_scraper_status: dict[str, dict[str, Any]],
    drivers: list[Driver],
    generator_version: str,
    git_sha: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> None:
    """Write the top-level drivers.json artifact."""
    ok = sum(1 for s in per_scraper_status.values() if s.get("status") == "ok")
    preserved = sum(1 for s in per_scraper_status.values() if s.get("status") == "preserved")
    blocked = sum(1 for s in per_scraper_status.values() if s.get("status") == "blocked")
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "generator": {
            "name": "driver-base",
            "version": generator_version,
            "git_sha": git_sha,
        },
        "per_scraper_status": per_scraper_status,
        "scraper_run_stats": {
            "total_scrapers": len(per_scraper_status),
            "ok": ok,
            "preserved": preserved,
            "blocked": blocked,
            "total_records": len(drivers),
        },
        "drivers": [_serialize(d) for d in drivers],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=_json_default, indent=2))


def read_prior_drivers_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data
