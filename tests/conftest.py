"""Test helpers: fixture loader + FakeFetcher for orchestrator smoke tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterable, Optional

import pytest

from driver_base.cache import Cache
from driver_base.fetch import HttpxFetcher
from driver_base.interface import FetchError, RawArtifact, Scraper

FIXTURES_ROOT = Path(__file__).parent / "fixtures"


def load_fixture(scraper: str, relpath: str, *, url: Optional[str] = None) -> RawArtifact:
    """Load a fixture from tests/fixtures/{scraper}/{relpath} as a RawArtifact."""
    path = FIXTURES_ROOT / scraper / relpath
    body = path.read_bytes()
    return RawArtifact(
        url=url or path.as_uri(),
        body=body,
        status=200,
        content_type="text/html; charset=utf-8",
        fetched_at="2026-08-22T14:00:00+00:00",
        body_sha=hashlib.sha256(body).hexdigest(),
        from_cache=False,
    )


class FakeFetcher:
    """Duck-types HttpxFetcher. Returns RawArtifacts for URLs the caller
    pre-registered; every other URL returns FetchError('permanent'/'http_404')."""

    def __init__(self, url_to_artifact: dict[str, RawArtifact]) -> None:
        self._map = dict(url_to_artifact)

    async def fetch(
        self, url: str, *, force_refresh: bool = False
    ) -> "RawArtifact | FetchError":
        if url in self._map:
            return self._map[url]
        return FetchError(url=url, kind="permanent", reason="http_404", attempts=1)

    async def fetch_many(
        self, urls: list[str], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return [await self.fetch(u, force_refresh=force_refresh) for u in urls]

    async def aclose(self) -> None:
        pass


def make_fetcher_factory(
    url_to_artifact: dict[str, RawArtifact],
) -> Callable[[Scraper, Cache], FakeFetcher]:
    def _factory(scraper: Scraper, cache: Cache) -> FakeFetcher:
        return FakeFetcher(url_to_artifact)

    return _factory


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT
