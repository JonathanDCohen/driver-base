"""HTTP fetching for scrapers. httpx-backed with retry classifier + cache.

The `HttpxFetcher.fetch()` contract:
  - Consults `Cache.read()` first (unless force_refresh).
  - Rate-limits per host via `HostRateLimiter.throttle()`.
  - Retries transient errors (5xx, 429, timeouts, DNS timeout) with exponential
    backoff; honors Retry-After on 429 and per-host Crawl-delay.
  - Does NOT retry permanent errors (404, 403, 410, DNS NXDOMAIN, TLS).
  - Returns a `RawArtifact` on 2xx, a `FetchError` otherwise.
  - Writes 2xx responses to the cache.

Playwright and Xlsx fetchers are not implemented in v1 (18Sound MVP uses httpx
only for LF/HF/coax/horn/line-array; tweeters would need Playwright but are
deferred).
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional

import httpx

from driver_base.cache import Cache
from driver_base.interface import FetchError, RawArtifact, SeedRef
from driver_base.rate_limiter import HostRateLimiter

DEFAULT_USER_AGENT = "driver-base/0.1 (+contact: jon@joncohen.dev)"
_TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 406, 410, 451})
_BACKOFF_SCHEDULE = (1.0, 3.0, 9.0)  # seconds; length = max retry attempts


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class HttpxFetcher:
    def __init__(
        self,
        scraper_name: str,
        cache: Cache,
        rate_limiter: HostRateLimiter,
        user_agent: str = DEFAULT_USER_AGENT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.scraper_name = scraper_name
        self.cache = cache
        self.rate_limiter = rate_limiter
        self.user_agent = user_agent
        self._client = client
        self._owns_client = client is None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": self.user_agent, "Accept": "*/*"},
                follow_redirects=True,
                timeout=httpx.Timeout(20.0, connect=10.0),
                http2=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def fetch(
        self,
        url: str,
        *,
        force_refresh: bool = False,
        post_data: Optional[tuple[tuple[str, str], ...]] = None,
    ) -> "RawArtifact | FetchError":
        cached = self.cache.read(
            self.scraper_name, url, force_refresh=force_refresh, post_data=post_data
        )
        if cached is not None:
            return cached

        client = await self._ensure_client()

        attempts = 0
        for i, base_delay in enumerate((0.0,) + _BACKOFF_SCHEDULE):
            attempts += 1
            if base_delay > 0:
                await asyncio.sleep(base_delay)
            await self.rate_limiter.throttle(url)
            try:
                if post_data is not None:
                    resp = await client.post(url, data=dict(post_data))
                else:
                    resp = await client.get(url)
            except httpx.TimeoutException:
                if i == len(_BACKOFF_SCHEDULE):
                    return FetchError(url=url, kind="transient", reason="timeout", attempts=attempts)
                continue
            except httpx.HTTPError as e:
                reason_ = _classify_httpx_error(e)
                if reason_ == "permanent" or i == len(_BACKOFF_SCHEDULE):
                    return FetchError(
                        url=url,
                        kind="permanent" if reason_ == "permanent" else "transient",
                        reason=type(e).__name__.lower(),
                        attempts=attempts,
                    )
                continue

            status = resp.status_code

            if 200 <= status < 300:
                body = resp.content
                artifact = RawArtifact(
                    url=str(resp.request.url),
                    body=body,
                    status=status,
                    content_type=resp.headers.get("content-type", ""),
                    fetched_at=_iso_now(),
                    body_sha=hashlib.sha256(body).hexdigest(),
                    from_cache=False,
                )
                self.cache.write(self.scraper_name, artifact, post_data=post_data)
                return artifact

            if status in _PERMANENT_STATUSES:
                return FetchError(url=url, kind="permanent", reason=f"http_{status}", attempts=attempts)

            if status in _TRANSIENT_STATUSES or 500 <= status < 600:
                if status == 429:
                    retry_after = _retry_after_seconds(resp.headers.get("retry-after"))
                    if retry_after is not None and i < len(_BACKOFF_SCHEDULE):
                        wait = max(retry_after, _BACKOFF_SCHEDULE[i])
                        await asyncio.sleep(wait)
                        continue
                if i == len(_BACKOFF_SCHEDULE):
                    return FetchError(url=url, kind="transient", reason=f"http_{status}", attempts=attempts)
                continue

            # any other status is treated as permanent
            return FetchError(url=url, kind="permanent", reason=f"http_{status}", attempts=attempts)

        return FetchError(url=url, kind="transient", reason="retries_exhausted", attempts=attempts)

    async def fetch_many(
        self, urls: list[str], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return await asyncio.gather(
            *[self.fetch(u, force_refresh=force_refresh) for u in urls]
        )

    async def fetch_seed(
        self, seed: "SeedRef", *, force_refresh: bool = False
    ) -> "RawArtifact | FetchError":
        return await self.fetch(
            seed.url, force_refresh=force_refresh, post_data=seed.post_data
        )

    async def fetch_seeds(
        self, seeds: list["SeedRef"], *, force_refresh: bool = False
    ) -> list["RawArtifact | FetchError"]:
        return await asyncio.gather(
            *[self.fetch_seed(s, force_refresh=force_refresh) for s in seeds]
        )


def _classify_httpx_error(e: Exception) -> str:
    name = type(e).__name__.lower()
    if "connect" in name or "network" in name or "read" in name or "write" in name:
        return "transient"
    if "invalidurl" in name or "unsupported" in name:
        return "permanent"
    return "transient"


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        try:
            return float(v)
        except ValueError:
            return None
    return None  # HTTP-date form: ignore for simplicity
