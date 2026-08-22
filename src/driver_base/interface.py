"""Scraper ABC, dataclasses, and Protocols shared by every scraper.

The design intent (see `docs/framework.md`):
 - `discover_seeds()` is pure static config (no I/O).
 - `enumerate(seed_artifacts)` is pure bytes → SeedRef[] and receives only
   THIS round's fetched seeds (dedup is centralized in the orchestrator).
 - `parse_artifact(raw, seed_context)` is pure bytes → DriverFragment[] + followup
   SeedRefs. Followup SeedContext inherits parent identity so downstream merge
   groups fragments by the same key.
 - `classify_driver_kind(fragment)` is a post-parse hook for scrapers whose
   enumeration path cannot supply a category (Eminence Shopify /products.json).
 - `preferred_fetcher(url)` is consulted at BOTH seed-fetch and product-fetch time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from driver_base.model import DriverFragment


class DriverKind(str, Enum):
    LF_WOOFER = "lf_woofer"
    HF_COMPRESSION = "hf_compression"
    TWEETER = "tweeter"
    COAX = "coax"
    HORN = "horn"
    PASSIVE = "passive"
    SHAKER = "shaker"
    FULLRANGE = "fullrange"
    GUITAR_BASS = "guitar_bass"
    AMT = "amt"


class FetcherKind(str, Enum):
    HTTPX = "httpx"
    PLAYWRIGHT = "playwright"
    XLSX = "xlsx"


@dataclass(frozen=True)
class SeedContext:
    driver_kind_hint: Optional[DriverKind] = None
    category_id: Optional[str] = None
    series: Optional[str] = None
    # Followup identity (inherited from parent when parse_artifact returns followups)
    parent_canonical_id_seed: Optional[str] = None
    parent_model: Optional[str] = None
    parent_impedance_ohm: Optional[float] = None
    parent_driver_kind: Optional[DriverKind] = None


@dataclass(frozen=True)
class SeedRef:
    url: str
    context: SeedContext = field(default_factory=SeedContext)


@dataclass(frozen=True)
class RawArtifact:
    url: str
    body: bytes
    status: int
    content_type: str
    fetched_at: str   # ISO 8601
    body_sha: str     # hex sha256; sidecar only, not part of cache key
    from_cache: bool = False


@dataclass(frozen=True)
class FetchError:
    url: str
    kind: str          # "transient" or "permanent"
    reason: str        # e.g. "http_404", "dns_nxdomain", "timeout_read"
    attempts: int


@dataclass
class ParseResult:
    fragments: list["DriverFragment"]
    followups: list[SeedRef] = field(default_factory=list)


@dataclass
class EnumerateResult:
    product_urls: list[SeedRef]
    additional_seed_urls: list[SeedRef] = field(default_factory=list)


class Fetcher(Protocol):
    async def fetch(self, url: str) -> "RawArtifact | FetchError": ...


class FetchCtx(Protocol):
    """Bound per scraper by the orchestrator. Captures a scraper reference so
    ctx.fetch() consults scraper.preferred_fetcher(url) at both seed-fetch and
    product-fetch time."""

    scraper: "Scraper"
    scraper_name: str

    async def fetch(self, url: str) -> "RawArtifact | FetchError": ...
    async def fetch_many(self, urls: list[str]) -> list["RawArtifact | FetchError"]: ...


class Scraper(ABC):
    """Base class for a manufacturer scraper. Subclass + register."""

    name: str                                    # e.g. "eighteensound"
    manufacturer_display: str                    # e.g. "18Sound"
    schema_version: str = "1.0"
    playwright_required: bool = False
    expected_min_records: int = 10               # first-run absolute floor
    populated_field_floors: dict[DriverKind, dict[str, float]] = {}
    max_seed_rounds: int = 8

    @abstractmethod
    def discover_seeds(self) -> list[SeedRef]:
        """Pure static config. No I/O."""

    @abstractmethod
    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        """Pure bytes → URLs. Receives only THIS round's fetched seeds."""

    @abstractmethod
    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        """Pure bytes → DriverFragment[] + followup SeedRef[]. NEVER does I/O."""

    def classify_driver_kind(
        self, fragment: "DriverFragment"
    ) -> Optional[DriverKind]:
        """Post-parse hook. Default: trust fragment.driver_kind.

        Scrapers whose enumeration path can't tag kind (Eminence /products.json)
        override this to inspect fragment contents and return the resolved kind.
        """
        return fragment.driver_kind

    def preferred_fetcher(self, url: str) -> Optional[FetcherKind]:
        """Return None to use default HTTPX. Override per URL for JS-heavy pages."""
        return None

    async def discover_archive(self) -> AsyncIterator[SeedRef]:
        """v2 extension point. Default: no discontinued products."""
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]
