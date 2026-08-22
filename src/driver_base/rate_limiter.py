"""Per-host asyncio rate limiter (minimum interval between requests to a host).

Interval derives from:
  - The scraper's declared `default_rate_limit_rps` (1.0 by default → 1s min interval).
  - robots.txt `Crawl-delay` if the host publishes one AND it's longer.

Consumers await `throttle(url)` immediately BEFORE issuing the fetch. The
limiter enforces max(1/rps, crawl_delay) between successive calls per host.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional
from urllib.parse import urlparse

from driver_base.robots import RobotsCache


class HostRateLimiter:
    def __init__(
        self,
        robots: Optional[RobotsCache] = None,
        default_rps: float = 1.0,
    ) -> None:
        self._robots = robots
        self._default_interval = 1.0 / default_rps if default_rps > 0 else 1.0
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_call: dict[str, float] = {}

    def _host(self, url: str) -> str:
        return (urlparse(url).netloc or "").lower()

    def _interval(self, url: str) -> float:
        base = self._default_interval
        if self._robots is not None:
            cd = self._robots.crawl_delay(url)
            if cd is not None and cd > base:
                base = cd
        return base

    def _lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def throttle(self, url: str) -> None:
        """Block until it's safe to fetch `url`. Updates last-call timestamp on exit."""
        host = self._host(url)
        interval = self._interval(url)
        async with self._lock(host):
            now = time.monotonic()
            last = self._last_call.get(host, 0.0)
            wait = last + interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[host] = time.monotonic()
