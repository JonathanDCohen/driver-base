"""Per-host robots.txt cache. Uses stdlib urllib.robotparser."""

from __future__ import annotations

import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse


class RobotsCache:
    """Fetches and parses robots.txt on first request per host. Cheap in-memory."""

    def __init__(self, user_agent: str = "*") -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _get(self, url: str) -> urllib.robotparser.RobotFileParser:
        host = _host_of(url)
        if host not in self._parsers:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{_scheme_of(url)}://{host}/robots.txt")
            try:
                rp.read()
            except Exception:
                # network/parse error → permissive fallback
                rp = urllib.robotparser.RobotFileParser()
                rp.parse([])
            self._parsers[host] = rp
        return self._parsers[host]

    def can_fetch(self, url: str) -> bool:
        return self._get(url).can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> Optional[float]:
        rp = self._get(url)
        d = rp.crawl_delay(self._user_agent)
        if d is None:
            return None
        try:
            return float(d)
        except (TypeError, ValueError):
            return None


def _host_of(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def _scheme_of(url: str) -> str:
    return (urlparse(url).scheme or "https").lower()
