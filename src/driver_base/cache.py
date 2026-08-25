"""On-disk response cache.

Layout under `cache_root/`:
    {scraper_name}/{sha[:2]}/{sha}.body
    {scraper_name}/{sha[:2]}/{sha}.meta.json

Key: sha256(scraper_name + ':' + url) — deterministic, per-scraper isolated.
TTL: 7 days (per file). Non-2xx responses NEVER cached. --refetch bypasses reads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from driver_base.interface import RawArtifact

DEFAULT_TTL = timedelta(days=7)


@dataclass
class CacheHit:
    artifact: RawArtifact


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


PostData = Optional[tuple[tuple[str, str], ...]]


def _key(scraper_name: str, url: str, post_data: PostData = None) -> str:
    h = hashlib.sha256()
    h.update(scraper_name.encode("utf-8"))
    h.update(b":")
    h.update(url.encode("utf-8"))
    if post_data is not None:
        h.update(b":POST:")
        h.update(repr(post_data).encode("utf-8"))
    return h.hexdigest()


def _paths(
    root: Path, scraper_name: str, url: str, post_data: PostData = None
) -> tuple[Path, Path]:
    key = _key(scraper_name, url, post_data)
    dir_ = root / scraper_name / key[:2]
    return dir_ / f"{key}.body", dir_ / f"{key}.meta.json"


class Cache:
    def __init__(self, root: Path, ttl: timedelta = DEFAULT_TTL) -> None:
        self.root = Path(root)
        self.ttl = ttl

    def read(
        self,
        scraper_name: str,
        url: str,
        force_refresh: bool = False,
        post_data: PostData = None,
    ) -> Optional[RawArtifact]:
        if force_refresh:
            return None
        body_p, meta_p = _paths(self.root, scraper_name, url, post_data)
        if not body_p.exists() or not meta_p.exists():
            return None
        try:
            meta = json.loads(meta_p.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        try:
            fetched_at = _parse_iso(meta["fetched_at"])
        except (KeyError, ValueError):
            return None
        if fetched_at + self.ttl < datetime.now(timezone.utc):
            return None
        try:
            body = body_p.read_bytes()
        except OSError:
            return None
        return RawArtifact(
            url=meta.get("url", url),
            body=body,
            status=int(meta.get("status", 200)),
            content_type=meta.get("content_type", ""),
            fetched_at=meta["fetched_at"],
            body_sha=meta.get("body_sha", hashlib.sha256(body).hexdigest()),
            from_cache=True,
        )

    def write(
        self,
        scraper_name: str,
        artifact: RawArtifact,
        post_data: PostData = None,
    ) -> None:
        """Store `artifact` in the cache. Non-2xx responses are silently skipped."""
        if not (200 <= artifact.status < 300):
            return
        body_p, meta_p = _paths(self.root, scraper_name, artifact.url, post_data)
        body_p.parent.mkdir(parents=True, exist_ok=True)
        body_p.write_bytes(artifact.body)
        meta_p.write_text(
            json.dumps(
                {
                    "url": artifact.url,
                    "fetched_at": artifact.fetched_at,
                    "status": artifact.status,
                    "content_type": artifact.content_type,
                    "body_sha": artifact.body_sha,
                },
                sort_keys=True,
            )
        )

    def purge(self, scraper_name: Optional[str] = None, url: Optional[str] = None) -> int:
        """Delete matching entries; returns count removed."""
        removed = 0
        if url is not None:
            if scraper_name is None:
                raise ValueError("purge(url=...) requires scraper_name too")
            body_p, meta_p = _paths(self.root, scraper_name, url)
            for p in (body_p, meta_p):
                if p.exists():
                    p.unlink()
                    removed += 1
            return removed
        target = self.root / scraper_name if scraper_name else self.root
        if not target.exists():
            return 0
        for p in target.rglob("*"):
            if p.is_file():
                p.unlink()
                removed += 1
        return removed
