"""Test helpers: fixture loader + FakeFetcher for orchestrator smoke tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterable, Optional

import pytest

from driver_base.cache import Cache
from driver_base.fetch import HttpxFetcher
from driver_base.interface import FetchError, RawArtifact, Scraper, SeedRef

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

    def __init__(self, url_to_artifact: dict) -> None:
        self._map = dict(url_to_artifact)

    async def fetch(
        self,
        url: str,
        *,
        force_refresh: bool = False,
        post_data: Optional[tuple[tuple[str, str], ...]] = None,
    ) -> "RawArtifact | FetchError":
        key = (url, post_data) if post_data is not None else url
        if key in self._map:
            return self._map[key]
        if url in self._map:
            return self._map[url]
        return FetchError(url=url, kind="permanent", reason="http_404", attempts=1)

    async def fetch_many(
        self, urls: list[str], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return [await self.fetch(u, force_refresh=force_refresh) for u in urls]

    async def fetch_seed(
        self, seed: SeedRef, *, force_refresh: bool = False
    ) -> "RawArtifact | FetchError":
        return await self.fetch(
            seed.url, force_refresh=force_refresh, post_data=seed.post_data
        )

    async def fetch_seeds(
        self, seeds: list[SeedRef], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return [await self.fetch_seed(s, force_refresh=force_refresh) for s in seeds]

    async def aclose(self) -> None:
        pass


def make_fetcher_factory(
    url_to_artifact: dict,
) -> Callable[[Scraper, Cache], FakeFetcher]:
    def _factory(scraper: Scraper, cache: Cache) -> FakeFetcher:
        return FakeFetcher(url_to_artifact)

    return _factory


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT
