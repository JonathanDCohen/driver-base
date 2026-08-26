# driver-base framework spec (v1)

## Purpose

A Python 3.10+ asyncio harness that scrapes ~9 speaker-driver manufacturer sites weekly and produces one versioned `web/drivers.json` for a static Cloudflare Pages SPA to consume. Scope for v1 is **manufacturer scrapers only**; retailer scraping (Parts Express, Solen, Madisound) is out of scope. La Voce is deferred (site unreachable — see `memory/la-voce-parked.md`).

The design was arrived at across three workflows that (a) reconned each manufacturer, (b) empirically validated the recon with throwaway Python scripts (10/10 converged with 0.00 % numerical delta on sampled T/S values), and (c) iterated framework synthesis against two adversarial reviewers. This doc captures the design that emerged; per-manufacturer specifics live in `docs/manufacturers.md`.

## Directory layout

```
driver-base/
├── pyproject.toml
├── uv.lock
├── main.py                                # cli entrypoint
├── docs/
│   ├── framework.md                       # this doc
│   └── manufacturers.md                   # per-scraper data sources + mechanics
├── data/
│   ├── drivers.json                       # THE artifact; consumed by SPA
│   ├── aliases.yaml                       # canonical_id rewrites; human-edited
│   ├── baselines.yaml                     # per-scraper expected_min_records overrides
│   ├── collision_registry.yaml            # first-seen -v2 suffix persistence (v2)
│   ├── cache/{scraper}/{sha}.body         # response cache (gitignored)
│   ├── cache/{scraper}/{sha}.meta.json    # cache sidecar
│   └── rejections/{scraper}-{run_id}.json # dropped fragments for debugging
├── src/driver_base/
│   ├── interface.py                       # Scraper ABC + types
│   ├── model.py                           # DriverFragment, Driver, SpecSource
│   ├── orchestrator.py                    # run_all(); per-scraper isolation
│   ├── cache.py                           # on-disk cache
│   ├── fetch.py                           # HttpxFetcher, PlaywrightFetcher, XlsxFetcher
│   ├── rate_limiter.py                    # per-host token bucket
│   ├── robots.py                          # robots.txt parser
│   ├── playwright_pool.py                 # process-wide singleton
│   ├── units.py                           # parse_frequency, parse_length, parse_bl_tm, ...
│   ├── labels.py                          # LABEL_TO_FIELD; FOOTNOTE vs MEASUREMENT_CONTEXT
│   ├── magnets.py                         # normalize_magnet_type(raw) -> MagnetType
│   ├── id.py                              # canonical_id builder
│   ├── aliases.py                         # load/apply aliases.yaml
│   ├── merge.py                           # merge_fragments_by_id
│   ├── consistency.py                     # cross-field REJECT gates
│   ├── sanity.py                          # single-field REJECT + WARN gates
│   ├── schema.py                          # SchemaVersion; JSON writer
│   ├── rejections.py                      # sidecar writer
│   ├── parsers/{html,pdf,xlsx}.py         # shared extraction primitives
│   └── scrapers/                          # one file per manufacturer
├── tests/
│   ├── fixtures/{scraper}/                # real captured HTML/JSON/PDF/xlsx
│   ├── test_parse_{scraper}.py            # per-scraper parse_artifact tests
│   ├── test_discover_{scraper}.py         # per-scraper enumerate tests
│   ├── test_units.py                      # unit-parser table
│   ├── test_labels.py                     # label taxonomy
│   ├── test_id.py                         # canonical_id derivation
│   ├── test_merge.py                      # synthetic conflict fragments
│   ├── test_consistency.py                # cross-field REJECT
│   └── test_orchestrator_smoke.py         # end-to-end w/ FakeFetcher
├── tools/
│   └── capture_fixtures.py                # one-shot fixture recorder
├── .github/workflows/
│   └── scrape.yml                         # weekly cron
└── web/                                   # static SPA (out of scope for this doc)
```

## Pipeline overview

Every scraper implements three pure functions and the orchestrator wires them together. Nothing in the scraper subclass does I/O — fetching is centralized so the orchestrator owns rate-limiting, caching, robots.txt honoring, retry, and per-scraper isolation.

```
                orchestrator
                     |
      discover_seeds()  (pure static)
                     |
              fetch_many(seed URLs)   ← preferred_fetcher() consulted per URL
                     |
      enumerate(fetched seeds)         (pure bytes → SeedRef[])
                     |
              (loop: additional_seed_urls until stable, ≤ max_seed_rounds)
                     |
              fetch_many(product URLs) ← preferred_fetcher() again
                     |
      parse_artifact(raw, seed_context)  (pure bytes → DriverFragment[] + followup SeedRef[])
                     |
              fetch_many(followup URLs)  (≤ 2 followup rounds)
                     |
              parse_artifact(followups)
                     |
              apply_aliases            (rewrite canonical_id from aliases.yaml)
                     |
              merge_fragments_by_id    (v1: trivial pass-through)
                     |
              enforce_consistency      (cross-field REJECT → ParseConsistencyFailure)
                     |
              sanity gates             (single-field REJECT / WARN; delta vs baseline)
                     |
              per_scraper_status ok | preserved | blocked
```

Per-scraper failures are isolated: an exception, a below-floor record count, or a >30 % drop preserves that scraper's prior records with `last_scraped_at` bumped but `scraped_at` unchanged. Only after 3 consecutive failed runs does the status escalate to `blocked`.

## Interface

```python
# src/driver_base/interface.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Protocol

class DriverKind(str, Enum):
    LF_WOOFER = "lf_woofer"
    HF_COMPRESSION = "hf_compression"
    TWEETER = "tweeter"
    COAX = "coax"
    HORN = "horn"
    PASSIVE = "passive"
    SHAKER = "shaker"
    FULLRANGE = "fullrange"
    GUITAR_BASS = "guitar_bass"    # Celestion; exempt from T/S REJECT (WARN only)

class FetcherKind(str, Enum):
    HTTPX = "httpx"
    PLAYWRIGHT = "playwright"
    XLSX = "xlsx"

@dataclass(frozen=True)
class SeedContext:
    """Typed context carried alongside a URL. Prevents dict-typo bugs."""
    driver_kind_hint: Optional[DriverKind] = None
    category_id: Optional[str] = None
    series: Optional[str] = None
    # For followups: propagate parent identity so merge groups by same key
    parent_canonical_id_seed: Optional[str] = None
    parent_model: Optional[str] = None
    parent_impedance_ohm: Optional[float] = None
    parent_driver_kind: Optional[DriverKind] = None

@dataclass(frozen=True)
class SeedRef:
    url: str
    context: SeedContext = field(default_factory=SeedContext)
    # When set, the fetcher POSTs these fields as application/x-www-form-urlencoded
    # (tuple-of-pairs, not dict, so SeedRef stays hashable and cache keys stay stable).
    # Used by Faital to POST to search.php with the listing page's default filter.
    post_data: Optional[tuple[tuple[str, str], ...]] = None

@dataclass(frozen=True)
class RawArtifact:
    url: str
    body: bytes
    status: int
    content_type: str
    fetched_at: str         # ISO 8601
    body_sha: str           # hex sha256 (change-detection only; not in cache key)
    from_cache: bool = False

@dataclass(frozen=True)
class FetchError:
    url: str
    kind: Literal["transient", "permanent"]
    reason: str             # http_404, dns_nxdomain, timeout_read, playwright_unavailable, ...
    attempts: int

@dataclass
class ParseResult:
    fragments: list["DriverFragment"]
    followups: list[SeedRef] = field(default_factory=list)  # inherits parent SeedContext

@dataclass
class EnumerateResult:
    product_urls: list[SeedRef]                              # SeedRefs with kind_hint from category
    additional_seed_urls: list[SeedRef] = field(default_factory=list)

class Fetcher(Protocol):
    async def fetch(self, url: str) -> RawArtifact | FetchError: ...

class FetchCtx(Protocol):
    """Bound per scraper by the orchestrator; captures scraper reference in closure so
    ctx.fetch() consults scraper.preferred_fetcher(url) at BOTH seed-fetch time and
    product-fetch time. This is how 18Sound's Playwright-needing tweeter seed URL
    gets routed to Playwright without affecting the other 5 category seeds."""
    scraper: "Scraper"
    scraper_name: str
    async def fetch(self, url: str) -> RawArtifact | FetchError: ...
    async def fetch_many(self, urls: list[str]) -> list[RawArtifact | FetchError]: ...
    async def fetch_seed(self, seed: SeedRef) -> RawArtifact | FetchError: ...
    async def fetch_seeds(self, seeds: list[SeedRef]) -> list[RawArtifact | FetchError]: ...

class Scraper(ABC):
    name: str                                                    # "eighteensound"
    manufacturer_display: str                                    # "18Sound"
    schema_version: str = "1.0"
    playwright_required: bool = False                            # health-check hint
    expected_min_records: int = 10                               # absolute floor for first run
    populated_field_floors: dict[DriverKind, dict[str, float]] = {}  # {kind: {field: min_pct}}
    max_seed_rounds: int = 8

    # PHASE 1a: pure static; no I/O.
    @abstractmethod
    def discover_seeds(self) -> list[SeedRef]: ...

    # PHASE 1b: pure bytes → URLs. Receives THIS ROUND's fetched seeds only.
    # Dedup of product_urls across rounds is centralized in the orchestrator.
    @abstractmethod
    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult: ...

    # PHASE 2: pure bytes → fragments. seed_context is the SeedContext of the URL that
    # produced this artifact; for a followup, it inherits the parent's SeedContext.
    @abstractmethod
    def parse_artifact(self, raw: RawArtifact, seed_context: SeedContext) -> ParseResult: ...

    # OPTIONAL: assign driver_kind from parsed fragment content when SeedContext can't
    # supply it at enumeration time. Eminence uses this because Shopify /products.json
    # returns a flat list without category info; classify from product.product_type or
    # a handle-regex map. Default is a no-op that trusts fragment.driver_kind.
    def classify_driver_kind(self, fragment: "DriverFragment") -> Optional[DriverKind]:
        return fragment.driver_kind

    # Consulted at BOTH seed-fetch and product-fetch time. None → default HTTPX.
    def preferred_fetcher(self, url: str) -> Optional[FetcherKind]:
        return None

    # v2 extension. Default: no discontinued products.
    async def discover_archive(self) -> "AsyncIterator[SeedRef]":
        if False:
            yield  # empty generator
```

Registration is import-driven (no filesystem scanning):

```python
# src/driver_base/scrapers/__init__.py
SCRAPERS: dict[str, type[Scraper]] = {}
def register(cls: type[Scraper]) -> type[Scraper]:
    SCRAPERS[cls.name] = cls
    return cls
```

Each `driver_base/scrapers/{name}.py` decorates its subclass with `@register`; `driver_base/scrapers/__init__.py` imports them.

## Data model

```python
# src/driver_base/model.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from driver_base.interface import DriverKind

class DriverStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    UNAVAILABLE = "unavailable"    # temporarily out of stock but listed

class MagnetType(str, Enum):
    CERAMIC = "ceramic"            # includes raw values "ferrite", "ceramic"
    NEODYMIUM = "neodymium"        # includes "neo", "neodymium", "neodymium slug/ring"
    ALNICO = "alnico"              # Celestion Blue and similar classics
    OTHER = "other"                # hybrid ("Neo/Ferrite"), unknown, or unparseable
# Normalization lives in driver_base/magnets.py — normalize_magnet_type(raw).

class SpecSource(str, Enum):
    HTML_TABLE = "html_table"
    HTML_GRID = "html_grid"
    HTML_PROSE = "html_prose"
    HTML_DIV_PAIRS = "html_div_pairs"
    INLINE_JS = "inline_js"        # HOQS var speakerData = {...};
    PDF_TEXT = "pdf_text"
    PDF_TABLE = "pdf_table"
    JSON_API = "json_api"          # Shopify /products.json, B&C _data=
    XLSX = "xlsx"                  # Faital comparison tables (if used)
    INFERRED = "inferred"          # driver_kind from category slug
    DERIVED = "derived"            # xmech doubled from labelled one-way

# Precedence (best-first) when a field appears in multiple fragments:
SPEC_SOURCE_PRECEDENCE = [
    SpecSource.JSON_API, SpecSource.XLSX,
    SpecSource.INLINE_JS,          # clean structured; ranked ABOVE HTML variants
    SpecSource.PDF_TABLE, SpecSource.PDF_TEXT,
    SpecSource.HTML_TABLE, SpecSource.HTML_GRID, SpecSource.HTML_DIV_PAIRS,
    SpecSource.HTML_PROSE,
    SpecSource.DERIVED, SpecSource.INFERRED,
]

@dataclass
class DriverFragment:
    """A partial Driver, one per parsed artifact. Merged post-parse by canonical_id.

    `model` is MANDATORY: if a parser cannot extract a model string from the source,
    it must raise/skip rather than emit an incomplete fragment. Every downstream
    identity operation (canonical_id derivation, alias lookup, retailer matching)
    depends on a non-empty model."""
    manufacturer: str
    source_url: str
    fetched_at: str
    driver_kind: Optional[DriverKind]      # may be None until classify_driver_kind runs
    model: str                             # required — no fragment without a model
    spec_source: dict[str, SpecSource] = field(default_factory=dict)

    # Identity
    canonical_id_seed: Optional[str] = None    # e.g. Celestion post-id, RCF productCode
    canonical_id: Optional[str] = None         # assigned post-merge

    # T/S
    fs_hz: Optional[float] = None
    qts: Optional[float] = None
    qes: Optional[float] = None
    qms: Optional[float] = None
    vas_liters: Optional[float] = None
    mms_g: Optional[float] = None
    cms_mm_per_n: Optional[float] = None
    rms_ns_per_m: Optional[float] = None
    bl_tm: Optional[float] = None
    re_ohm: Optional[float] = None
    le_mh: Optional[float] = None              # canonical: Le at 1 kHz
    sd_cm2: Optional[float] = None
    eta_zero_pct: Optional[float] = None

    # Physical
    xmax_mm: Optional[float] = None            # one-way linear excursion
    xmech_mm: Optional[float] = None           # PEAK-TO-PEAK by convention (see units.py)
    voice_coil_diameter_mm: Optional[float] = None
    voice_coil_layers: Optional[int] = None
    overall_diameter_mm: Optional[float] = None
    mounting_diameter_mm: Optional[float] = None
    net_weight_kg: Optional[float] = None
    magnet_type: Optional[MagnetType] = None    # coerced via normalize_magnet_type(raw)

    # Electrical
    impedance_nominal_ohm: Optional[float] = None
    impedance_min_ohm: Optional[float] = None

    # Power — split to accommodate divergent manufacturer conventions.
    # Never coerce one into another; leave missing ones None. See per_manufacturer_strategy.
    #   power_aes_watts        AES / RMS / Nominal (18Sound "Nominal", B&C "Nominal", ...)
    #   power_program_watts    2× AES (Beyma "Program", RCF "Program", HOQS "Program")
    #   power_long_term_watts  Continuous, when LARGER than AES (18Sound / B&C / Celestion Continuous)
    #   power_peak_watts       Peak / Max (Dayton "Max", Faital "Maximum")
    #   power_eia_watts        EIA 2-hour pink noise (Celestion only)
    power_aes_watts: Optional[float] = None
    power_program_watts: Optional[float] = None
    power_long_term_watts: Optional[float] = None
    power_peak_watts: Optional[float] = None
    power_eia_watts: Optional[float] = None

    # Frequency
    freq_low_hz: Optional[float] = None
    freq_high_hz: Optional[float] = None
    fs_diaphragm_hz: Optional[float] = None    # compression-driver diaphragm Fs

    # Sensitivity — BOTH may be populated; slot chosen per manufacturer convention
    sensitivity_db_1w_1m: Optional[float] = None
    sensitivity_db_2_83v_1m: Optional[float] = None

    # Commercial (thin in v1; retailers land in v2 with price_history sidecar)
    msrp_currency: Optional[str] = None
    msrp_amount: Optional[float] = None

    # Status
    status: DriverStatus = DriverStatus.ACTIVE

    # Diagnostics
    warn_flags: list[str] = field(default_factory=list)
    raw_identity_strings: list[str] = field(default_factory=list)   # for audit

@dataclass
class Driver:
    """Post-merge, post-consistency-check record. Shape written to drivers.json.

    Same fields as DriverFragment PLUS:
      - canonical_id: MANDATORY (REJECT gate if None post-merge)
      - driver_kind: MANDATORY (any None on DriverFragment must be resolved by
        Scraper.classify_driver_kind() before merge)
      - model: MANDATORY (inherited from Fragment; every Driver has a model)
      - spec_source values are the winning (post-precedence) sources per field
      - warn_flags aggregates flags from all merged fragments
      - source_urls (plural) records every artifact that contributed
      - fetched_at is the LATEST fetched_at across contributing fragments
      - scraped_at is stable across preserved runs; last_scraped_at bumps every run
    """
    manufacturer: str
    canonical_id: str
    driver_kind: DriverKind
    model: str
    spec_source: dict[str, SpecSource]
    source_urls: list[str]
    fetched_at: str
    scraped_at: str                     # unchanged on preserved runs
    last_scraped_at: str                # bumped every run
    status: DriverStatus
    warn_flags: list[str]
    # ... all Fragment T/S / physical / electrical / power / sensitivity fields inlined ...
```

## Top-level drivers.json

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-08-22T14:30:00Z",
  "generator": { "name": "driver-base", "version": "0.1.0", "git_sha": "abc1234" },

  "per_scraper_status": {
    "eighteensound": {
      "status": "ok",
      "last_success_at": "2026-08-22T14:30:00Z",
      "last_run_at":     "2026-08-22T14:30:00Z",
      "consecutive_failures": 0,
      "records_this_run": 324,
      "records_prior_run": 328,
      "delta_pct": -1.2,
      "fetch_stats": { "requested": 328, "cache_hits": 12, "network_fetches": 316,
                       "transient_errors": 4, "permanent_errors": 3, "playwright_incidents": 0 },
      "parse_stats": { "fragments_parsed": 324, "fragments_after_merge": 324,
                       "parse_consistency_failures": 0, "records_rejected": 4,
                       "warn_flags_total": 18 },
      "warn_flags": ["playwright_unavailable_tweeter_seed_skipped"]
    },
    "celestion": {
      "status": "preserved",
      "last_success_at": "2026-08-15T14:30:00Z",
      "last_run_at":     "2026-08-22T14:30:00Z",
      "consecutive_failures": 1,
      "records_this_run": null,
      "records_prior_run": 213,
      "reason": "rate_limited_530_persistent",
      "rejection_sidecar": "data/rejections/celestion-20260822143000.json"
    }
  },

  "scraper_run_stats": {
    "total_scrapers": 9, "ok": 8, "preserved": 1, "blocked": 0,
    "wall_time_seconds": 512, "total_records": 1287
  },

  "drivers": [
    {
      "manufacturer": "18Sound",
      "canonical_id": "18sound__18lw1400__8ohm",
      "driver_kind": "lf_woofer",
      "model": "18LW1400",
      "status": "active",
      "source_urls": ["https://www.eighteensound.it/en/products/lf-driver/18-0/8/18LW1400"],
      "fetched_at":     "2026-08-22T14:30:00Z",
      "scraped_at":     "2026-08-22T14:30:00Z",
      "last_scraped_at":"2026-08-22T14:30:00Z",

      "impedance_nominal_ohm": 8.0,  "impedance_min_ohm": 6.4,
      "fs_hz": 31.0, "qts": 0.29, "qes": 0.31, "qms": 7.2,
      "vas_liters": 297.0, "sd_cm2": 1225.0, "xmax_mm": 9.0, "xmech_mm": null,
      "mms_g": 190.0, "bl_tm": 24.7, "re_ohm": 5.0, "le_mh": 2.3,
      "voice_coil_diameter_mm": 100.0, "magnet_type": "ceramic",
      "power_aes_watts": 1000.0, "power_long_term_watts": 1400.0,
      "power_program_watts": null, "power_peak_watts": null, "power_eia_watts": null,
      "sensitivity_db_1w_1m": 98.0, "sensitivity_db_2_83v_1m": null,
      "freq_low_hz": 28.0, "freq_high_hz": 2500.0,
      "net_weight_kg": 13.3,

      "spec_source": {
        "fs_hz": "html_prose", "qts": "html_prose", "vas_liters": "html_prose",
        "xmax_mm": "html_prose", "power_aes_watts": "html_prose",
        "power_long_term_watts": "html_prose", "sensitivity_db_1w_1m": "html_prose",
        "driver_kind": "inferred", "impedance_nominal_ohm": "inferred"
      },
      "warn_flags": []
    }
  ]
}
```

`schema_version` is a `MAJOR.MINOR` string. The SPA parses via `SchemaVersion.parse("1.0")`; it fails hard on unknown MAJOR (breaking: field removed, id scheme changed, `driver_kind` semantics changed, power fields resplit). Unknown MINOR is ignored (additive: new nullable field, new `SpecSource` variant, new `DriverKind` variant). Enum-value forward-compat is per consumer: an unknown enum in a known field either coerces to null with a warn or crashes, at consumer discretion.

## Orchestrator

```python
# src/driver_base/orchestrator.py
import asyncio

MAX_SCRAPER_CONCURRENCY = 4      # 4 scrapers in flight at once
MAX_FOLLOWUP_ROUNDS = 2          # bounded loop for parse_artifact followups

async def run_all(scrapers: list[Scraper], prior: dict | None) -> dict:
    sem = asyncio.Semaphore(MAX_SCRAPER_CONCURRENCY)
    async def _bounded(s):
        async with sem:
            return await _run_isolated(s, prior)
    results = await asyncio.gather(*[_bounded(s) for s in scrapers])
    return _assemble_drivers_json(results, prior)

async def _run_isolated(scraper: Scraper, prior: dict | None) -> ScraperResult:
    ctx = BoundFetchCtx(scraper)         # binds preferred_fetcher for all ctx.fetch calls
    try:
        # PHASE 1a/1b: seed rounds with centralized dedup
        seen_seed_urls, seen_product_urls = set(), set()
        product_urls: list[SeedRef] = []
        current_seeds = scraper.discover_seeds()
        for round_num in range(scraper.max_seed_rounds):
            new_seeds = [s for s in current_seeds if s.url not in seen_seed_urls]
            if not new_seeds:
                break
            seen_seed_urls.update(s.url for s in new_seeds)
            arts = await ctx.fetch_many([s.url for s in new_seeds])
            arts = [a for a in arts if isinstance(a, RawArtifact)]
            # attach SeedContext to each artifact by URL lookup
            enum_result = scraper.enumerate(arts)
            new_products = [p for p in enum_result.product_urls if p.url not in seen_product_urls]
            if not new_products and round_num > 0:
                break   # pagination wrapped (site returned same set)
            seen_product_urls.update(p.url for p in new_products)
            product_urls.extend(new_products)
            current_seeds = enum_result.additional_seed_urls

        # PHASE 2: product fetch + parse
        arts_and_errors = await ctx.fetch_many([p.url for p in product_urls])
        art_ctx = {p.url: p.context for p in product_urls}
        fragments, pending = [], []
        for r in arts_and_errors:
            if isinstance(r, RawArtifact):
                res = scraper.parse_artifact(r, art_ctx.get(r.url, SeedContext()))
                fragments.extend(res.fragments)
                pending.extend(res.followups)

        # bounded followup rounds (parent SeedContext already attached to each followup)
        for _ in range(MAX_FOLLOWUP_ROUNDS):
            if not pending: break
            f_arts = await ctx.fetch_many([f.url for f in pending])
            f_ctx = {f.url: f.context for f in pending}
            new_pending = []
            for r in f_arts:
                if isinstance(r, RawArtifact):
                    res = scraper.parse_artifact(r, f_ctx.get(r.url, SeedContext()))
                    fragments.extend(res.fragments)
                    new_pending.extend(res.followups)
            pending = new_pending

        # driver_kind classification for scrapers that couldn't tag at enumeration time
        for frag in fragments:
            if frag.driver_kind is None:
                frag.driver_kind = scraper.classify_driver_kind(frag) or DriverKind.LF_WOOFER

        # alias rewrite → group → merge → consistency
        fragments = apply_aliases(fragments)
        drivers, rejected = merge_fragments_by_id(fragments)
        drivers, extra_rejected = enforce_consistency(drivers)   # cross-field REJECT
        rejected += extra_rejected

        # gates
        prior_records = _prior_count(prior, scraper.name)
        n = len(drivers)
        if prior_records == 0:
            baseline_floor = _baseline_floor(scraper)
            if n < baseline_floor:
                raise ScraperLevelFailure(f"below_expected_min_records ({n} < {baseline_floor})")
        elif n < 0.70 * prior_records:
            raise ScraperLevelFailure(f"records_dropped_more_than_30pct ({n} vs {prior_records})")

        _write_rejection_sidecar(scraper.name, run_id, rejected)
        return ScraperResult(status="ok", drivers=drivers, ...)

    except Exception as e:
        # PER-SCRAPER ISOLATION: preserve prior on any exception
        prior_belonging = [d for d in (prior or {}).get("drivers", [])
                           if d["manufacturer"] == scraper.manufacturer_display]
        prev = (prior or {}).get("per_scraper_status", {}).get(scraper.name, {})
        consecutive = prev.get("consecutive_failures", 0) + 1
        status = "blocked" if consecutive >= 3 else "preserved"
        _write_rejection_sidecar(scraper.name, run_id, [], reason=str(e))
        return ScraperResult(status=status, reason=str(e),
                             consecutive_failures=consecutive,
                             preserved_drivers=prior_belonging)

class BoundFetchCtx(FetchCtx):
    def __init__(self, scraper): self.scraper = scraper; self.scraper_name = scraper.name
    async def fetch(self, url):
        kind = self.scraper.preferred_fetcher(url) or FetcherKind.HTTPX
        return await _dispatch_fetcher(kind, url, scraper_name=self.scraper.name)
    async def fetch_many(self, urls):
        return await asyncio.gather(*[self.fetch(u) for u in urls])
```

**Partial-success rule:** high permanent-error rate (>10 %) emits a `warn_flag` but does NOT preserve. Only record-count-vs-baseline gates decide preserve/blocked. This eliminates the anti-pattern where a 269-of-300 successful run was discarded in favor of a stale prior run.

## Cache

- **Key**: `sha256(scraper_name + ":" + url)` — deterministic, per-scraper isolated. Body SHA is stored in the sidecar for change-detection stats but is NOT part of the cache key (the key must be computable before the fetch).
- **TTL**: 7 days per file (from `fetched_at`).
- **Non-2xx responses**: NEVER cached. Prevents poisoning the cache with transient error responses.
- **Bypass**: `--refetch` reads fresh (still writes to cache); `--cache-purge --scraper NAME` clears one scraper; `--cache-purge --url URL` clears one entry.
- **Layout**: `data/cache/{scraper}/{sha}.body` + `data/cache/{scraper}/{sha}.meta.json` sidecar with `{url, fetched_at, status, content_type, body_sha}`.

## Retry & rate-limiting

**Classifier:**
- **Transient** (retry with exponential backoff, max 3 attempts): HTTP 5xx, HTTP 429, socket timeout, connection reset, DNS timeout.
- **Permanent** (no retry, immediate `FetchError`): HTTP 404, 403, 410, DNS NXDOMAIN, invalid TLS.

**Backoff schedule:** base is 1s → 3s → 9s, BUT the actual sleep is `max(exponential, host_crawl_delay)`. For HTTP 429 with a `Retry-After` header, honor the header if present (`max(Retry-After, exponential)`). This is critical for Celestion (`Crawl-delay: 10s` per robots.txt) — the naive exponential would trigger an IP ban.

**Per-host rate limiter:** token bucket driven by the host's robots.txt `Crawl-delay`. `HttpxFetcher.fetch()` blocks on the bucket before every request. Default is 1 req/s if the site publishes no `Crawl-delay`.

**`fetch_many` returns `list[RawArtifact | FetchError]`** preserving input order. Per-scraper `fetch_stats` counts `requested`, `cache_hits`, `network_fetches`, `transient_errors`, `permanent_errors`, `playwright_incidents`, `bodies_changed_since_last_fetch`.

## Sanity gates

Two categories with **different scopes**:

**Single-field range gates (nulls the FIELD only, keeps the record):**
- REJECT (null the field, log flag): `fs_hz` outside (5, 5000); `qts` outside (0.05, 5.0); `vas_liters` outside (0.1, 10000); `xmax_mm` outside (0.1, 60); `sd_cm2` outside (0.5, 10000); `impedance_nominal_ohm` outside (1, 32); `bl_tm` outside (0.5, 100); sensitivity outside (50, 130) dB; `freq_low_hz` outside (5, 10000); `freq_high_hz` outside (100, 100000); power fields outside their per-field bounds.
- WARN (keeps value, log flag): `impedance_nominal_ohm` not in `{2, 2.5, 3, 4, 6, 8, 12, 16}` (e.g. 3.2 is unusual but plausible); `fs_hz > 100` on `LF_WOOFER`; `fs_hz < 500` on `HF_COMPRESSION` / `TWEETER`; SPL identity `|db_2_83v - db_1w - 10*log10(8/Z)| > 1.5 dB` when both slots populated.

**Cross-field consistency gates (REJECTS the whole record with `ParseConsistencyFailure`):** see next section.

**First-run baseline:** if no prior baseline exists, `records_this_run >= expected_min_records`. Override via `data/baselines.yaml`:

```yaml
# data/baselines.yaml — per-scraper expected_min_records overrides
# checked into git; edit when a manufacturer legitimately shrinks or you want to accept
# a first-run below the code default. --accept-baseline CLI writes to this file.
faital_pro: 15         # code default 40; sitemap yields ~18 English URLs
hoqs: 10               # code default 20; site has 13 products total
```

`--accept-baseline` CLI flag runs the scraper, and on completion writes the observed count to `data/baselines.yaml` regardless of the code default — the escape hatch when ops has verified the smaller catalog.

**Delta gate:** after a baseline exists, `records_this_run < 0.70 * records_prior_run` REJECTS the scraper run into `preserved` (>30 % drop). Per-field populated-rate drops >20 percentage points between runs → WARN with `populated_rate_drop_{field}` (does not preserve).

## Cross-field consistency (post-merge, drops the RECORD)

```python
# src/driver_base/consistency.py
class ParseConsistencyFailure(Exception): pass

def enforce_consistency(drivers: list[Driver]) -> tuple[list[Driver], list[RejectedDriver]]:
    kept, rejected = [], []
    for d in drivers:
        try:
            _check(d)
            kept.append(d)
        except ParseConsistencyFailure as e:
            rejected.append(RejectedDriver(driver=d, reason=str(e)))
    return kept, rejected

def _check(d: Driver) -> None:
    if d.canonical_id is None:
        raise ParseConsistencyFailure("canonical_id is None")
    if d.xmech_mm is not None and d.xmax_mm is not None:
        # xmech is peak-to-peak by convention → must be ≥ 2x xmax (0.05 safety margin)
        if d.xmech_mm < 1.9 * d.xmax_mm:
            raise ParseConsistencyFailure(f"xmech_under_doubling: {d.xmech_mm} < 1.9*{d.xmax_mm}")
    if d.impedance_min_ohm is not None and d.impedance_nominal_ohm is not None:
        if d.impedance_min_ohm > d.impedance_nominal_ohm:
            raise ParseConsistencyFailure(f"impedance_min>nominal: {d.impedance_min_ohm}>{d.impedance_nominal_ohm}")
    if d.power_aes_watts is not None:
        for f in ("power_long_term_watts", "power_peak_watts", "power_program_watts"):
            v = getattr(d, f)
            if v is not None and v < d.power_aes_watts:
                raise ParseConsistencyFailure(f"{f}<aes: {v}<{d.power_aes_watts}")
    # freq_high must exceed freq_low, but the minimum bandwidth is kind-conditional
    if d.freq_low_hz is not None and d.freq_high_hz is not None:
        min_bw = _min_bandwidth_for_kind(d.driver_kind)  # SHAKER=10Hz, TWEETER=1kHz, LF_WOOFER=500Hz
        if d.freq_high_hz < d.freq_low_hz + min_bw:
            raise ParseConsistencyFailure(f"bandwidth_too_narrow: {d.freq_low_hz}→{d.freq_high_hz}")

    # WARN-only (does NOT raise; adds to d.warn_flags):
    if d.xmech_mm and d.xmax_mm and d.xmech_mm / d.xmax_mm > 6:
        d.warn_flags.append("xmech_xmax_ratio_high")     # over-doubling? or legit high-excursion?
    # sensitivity SPL identity
    if d.sensitivity_db_1w_1m and d.sensitivity_db_2_83v_1m and d.impedance_nominal_ohm:
        delta = abs(d.sensitivity_db_2_83v_1m - d.sensitivity_db_1w_1m
                    - 10 * math.log10(8 / d.impedance_nominal_ohm))
        if delta > 1.5:
            d.warn_flags.append("sensitivity_inconsistent")
    # T/S expected for lf_woofer / fullrange / coax except guitar_bass
    if d.driver_kind in {DriverKind.LF_WOOFER, DriverKind.FULLRANGE, DriverKind.COAX} \
            and d.driver_kind is not DriverKind.GUITAR_BASS:
        if d.fs_hz is None or not any([d.qts, d.qes, d.qms]):
            d.warn_flags.append("missing_ts_for_expected_kind")
```

**Xmech convention: values are stored AS-REPORTED (peak-to-peak).** The historical assumption of "double any labelled one-way" was proven wrong empirically in review — RCF's 52 mm and Faital's 17 mm are already peak-to-peak. The `xmech >= 1.9 * xmax` REJECT catches under-doubling parser bugs; the `xmech / xmax > 6` WARN catches suspicious over-doubling without rejecting legitimate high-excursion pro drivers.

## Playwright singleton

Process-wide browser context, launched lazily on first `PLAYWRIGHT` fetch. `driver_base/playwright_pool.py`:

- **Startup health-check** when first requested; on failure, mark pool as unavailable and every subsequent per-URL request returns `FetchError(kind="permanent", reason="playwright_unavailable")`. Other scrapers using HTTPX proceed normally.
- **Recycle policy**: kill and relaunch after (a) 100 total page loads, (b) 30 minutes wall time, or (c) any single-page load failure. Rate-limited to at most 5 recycles per hour per scraper; beyond that the pool marks itself unavailable for the remainder of the run.
- **Per-scraper serialization** via `asyncio.Lock` inside the pool to prevent concurrent `page.goto()` calls from racing (Chromium OOMs if too many pages open simultaneously).
- **Per-URL graceful skip**: `PlaywrightUnavailable` is caught and returned as a `FetchError` for that URL only; the scraper's other URLs proceed. 18Sound survives without Playwright — it skips the tweeter category-listing seed and emits a `warn_flag`; the 5 static categories still yield ~290 records.

`playwright_incidents` counter (recycle events + `PlaywrightUnavailable` raises) is surfaced in `per_scraper_status.fetch_stats`.

## Playwright degradation

No v1 scraper declares Playwright as a hard requirement. 18Sound is the only scraper that touches Playwright at all, and it only needs it for the tweeter category-listing seed URL — routed via `preferred_fetcher(url)`. Absent a working Playwright pool, 18Sound still runs, produces ~290 records (missing the tweeter category), and emits `warn_flag: playwright_unavailable_tweeter_seed_skipped`. Per-URL `PlaywrightUnavailable` is caught by the fetcher and returned as `FetchError(kind="permanent", reason="playwright_unavailable")` for that URL only.

If a future scraper genuinely cannot degrade (must have Playwright end-to-end, or must run from a specific egress), reintroduce `Scraper.execution_constraints: set[ExecutionConstraint]` with orchestrator-level checks. Not in v1 — no scraper needs it.

## Aliases

`data/aliases.yaml` is human-edited, append-only, checked into git. Two sections:

```yaml
# aliases.yaml — canonical_id rewrites for driver-base
# Direction: OLD_canonical_id → NEW_canonical_id (chain-resolved; validated acyclic on load)

canonical_id_aliases:
  18sound__18lw1400__8ohm: 18sound__18lw1400nd__8ohm    # manufacturer renamed 2026-Q3

# Optional: rewrite the raw model string BEFORE canonical_id derivation, so two
# fragments with different-model-strings-but-same-physical-driver merge in v2.
# In v1 (trivial merge), a model_aliases collision produces two records with the
# same canonical_id, which the merge step logs as WARN + disambiguates with a
# URL-slug suffix. Full cross-rename merging waits for v2.
model_aliases:
  faitalpro:
    12PR320: 12PR320N
```

`apply_aliases(fragments)` runs BEFORE `merge_fragments_by_id`, rewriting each fragment's `canonical_id` (or `model` for the pre-derivation form). Chains are transitive; a cycle fails hard on load.

## Merge

**v1 is a trivial pass-through** (1 fragment → 1 Driver after alias application), because no v1 scraper produces multi-fragment products. The full machinery — `conflict_matrix.yaml`, per-field precedence resolution via `SPEC_SOURCE_PRECEDENCE`, identity normalization — sits behind a `max_fragments_per_id > 1` flag and is exercised by synthetic tests only.

**Duplicate canonical_id in v1:** if two fragments emit the same `canonical_id` (impedance parse failure fell back to URL slug, or a model_aliases collision), the trivial merge:
1. Logs `warn_flag: duplicate_canonical_id_collision`.
2. Emits BOTH fragments, disambiguated by suffixing the second with a URL-slug hash: `{original_id}__dup{sha8}`.
3. The sanity gate `output_record_count == input_fragment_count - rejected_count` still passes because both are kept.

The v2 upgrade to real merge_fragments_by_id will consume these duplicates and either merge them by content or apply the collision registry.

## Testing

Fixtures live in `tests/fixtures/{scraper}/`:
```
tests/fixtures/eighteensound/
├── seeds/
│   ├── lf-driver.html                    # category listing
│   └── ...
├── products/
│   ├── 18LW1400.html
│   └── ...
└── followups/                            # unused in v1; interface-test-only
```

Fixtures are real bytes captured via `tools/capture_fixtures.py --scraper NAME`. Checked into git (few MB total). `tests/conftest.py` exposes `load_fixture(scraper, path)` → `RawArtifact`.

**Three test tiers:**

1. **`tests/test_parse_{scraper}.py`** — construct `RawArtifact` from a fixture, call `scraper.parse_artifact(raw, seed_context)`, assert on `ParseResult.fragments` field values (Fs, Qts, Vas, model, id, spec_source). No fetcher, no orchestrator, no cache.
2. **`tests/test_discover_{scraper}.py`** — `scraper.discover_seeds()` returns expected SeedRef count with correct `driver_kind_hint`. `scraper.enumerate(seed_arts)` yields expected product URLs; paginated scrapers test full-page fixture (→ `additional_seed_urls` populated) and empty-page fixture (→ empty).
3. **Shared utility tests** — `test_units.py` (label-variance table: Bl "N/A" → T·m, HOQS Bl "T/M" → multiplication, Dayton imperial `3.3 lbs.` → 1.497 kg, `6.50"` → 165.1 mm, Faital `45÷5000 Hz` frequency separator, etc.); `test_labels.py` (FOOTNOTE_SUFFIX strip vs MEASUREMENT_CONTEXT preserve: `Power Handling (RMS)` and `Power Handling (max)` map to different fields; `AES Power Handling (1)` → `power_aes_watts`); `test_id.py` (`2p5ohm` encoding, `canonical_id_seed` fallback, disambiguation); `test_merge.py` (synthetic fragments with forced conflicts); `test_consistency.py` (xmech under-doubling REJECT, sensitivity SPL WARN, guitar_bass T/S exemption).

**End-to-end smoke:** `tests/test_orchestrator_smoke.py` runs `run_all()` against a `FakeFetcher` returning pre-recorded fixtures; asserts `drivers.json` shape + record counts within 5 % of recorded baseline.

**Adding a scraper (recipe):**
1. `python -m tools.capture_fixtures --scraper NAME --url URL` captures fixtures.
2. Create `src/driver_base/scrapers/{name}.py` with a `@register`-decorated subclass.
3. Write `tests/test_parse_{name}.py` with at least one fixture per `DriverKind` the scraper handles.
4. Add the manufacturer's entry to `docs/manufacturers.md`.
5. `uv run pytest tests/test_parse_{name}.py -v` — must pass before merge.

CI runs `uv run pytest tests/ --ignore=tests/integration` on every PR. Integration tests under `tests/integration/` are marked `@pytest.mark.slow` and only run nightly.

## Extension points

**Archive support (v2)** — `Scraper.discover_archive() -> AsyncIterator[SeedRef]` defaults to empty. Override to yield `SeedRef`s pointing at discontinued paths (18Sound `/archive`, Beyma `/en/products/discontinued/`, Eminence archive-only sitemap entries). Orchestrator gains `--include-archive` CLI flag; when set, calls `discover_archive()` and appends yielded seeds to the enumerate pipeline; fragments emerge with `status=DriverStatus.ARCHIVED`.

**Retailer scrapers (v2)** — a `RetailerScraper` subclass sits alongside `Scraper` and implements a different flow: enumerate a retailer's catalog, extract `(retailer_sku, external_manufacturer, external_model, external_impedance, price, currency, stock, url)` per listing, then a fuzzy-match layer resolves each retailer record to an existing `canonical_id` in `drivers.json` (normalize model slugs, bucket impedance, configurable Levenshtein/Jaro thresholds, corroborating signal check with `impedance_hint`, `nominal_size_mm ±5%`, or power `±20%`). Matches emit `StoreLinkUpdate` records into a **separate** `data/store_links.json` — `drivers.json` stays manufacturer-only, preserving its stability contract. Prices flow into `data/price_history/{canonical_id}.jsonl` (append-only, per-driver). `fx_snapshot` returns as a top-level object in `store_links.json` (NOT `drivers.json`), locked direction: `price_usd = price_native * fx_rate[currency]`.

## Deployment

**GitHub Actions cron** (`.github/workflows/scrape.yml`): weekly on Sunday 00:00 UTC (plus `workflow_dispatch` for manual runs). Runs `uv run driver-base` which writes `web/drivers.json` and any `data/rejections/*.json`, then commits those changes directly to `main` with a `[skip ci]` message. Uses `concurrency: group: scrape-workflow` to prevent overlap. The push to `main` triggers a Cloudflare Pages redeploy.

**Cloudflare Pages**: connect the repo; build command none; output directory `web/`; deploy `web/drivers.json` alongside the SPA. `_headers` file caps `drivers.json` cache to 1 week (matches the scrape cadence); SPA assets cached 1 hour. First-time CF Pages hookup steps live in `docs/deployment.md` (out of scope for this doc).

## Known risks

- **La Voce parked** — site was unreachable from every tested environment 2026-08-22 (see `memory/la-voce-parked.md`). Almost certainly a transient outage on their end; recon schema was validated against a Wayback snapshot. Port when the site is up.
- **RCF slug discovery** relies on `?serieId=` enumeration. If RCF restructures URL parameters, all 7 series break at once. Detect: `records_this_run` collapses; delta gate preserves; ops investigates.
- **Faital sitemap staleness** (`lastmod=2017` per recon). Sitemap still returns the current 36 English URLs correctly, but if Faital moves to a new sitemap URL, discovery goes to zero. Detect: `records_this_run < expected_min_records` on first-run branch, or delta gate on subsequent runs.
- **Xmech convention** is stored AS-REPORTED (peak-to-peak by assumption). If a manufacturer adopts one-way convention without labelling, we silently under-count excursion. Detect: cross-field `xmech >= 1.9*xmax` REJECT fires when the assumption is wrong.
- **Playwright singleton crash cascades** — recycle at most 5×/hour; beyond that, per-URL `PlaywrightUnavailable` errors accumulate as `warn_flags`. 18Sound tweeters are the only v1 URL affected.
- **First-run baseline** is a one-way trapdoor without `data/baselines.yaml`. Set floors below recon-verified counts; ops adjusts via `--accept-baseline` after legitimate catalog changes.
- **Multi-fragment merge machinery** is documented but unexercised in v1. First-time production use (v2 retailer or Celestion PDF followup) will exercise `conflict_matrix.yaml` for the first time.
- **Aliases automation is manual.** A silent manufacturer rename (18LW1400 → 18LW1400ND without our notice) ships the old canonical_id as `ARCHIVED` (preserved from prior run) and the new one with a new id — consumers see a delete+add. Ops periodically diffs `drivers.json` for suspicious ADD+DELETE clusters and adds the alias.
- **Eminence `classify_driver_kind` heuristic risk** — we rely on Shopify `product.product_type` field (or a handle-regex fallback). If Eminence changes `product_type` values, kind mapping drifts; the `populated_field_floors` gate catches severe drift.
- **Sensitivity slot inference** — manufacturers that don't explicitly label 1W/1m vs 2.83V/1m get the slot from `per_manufacturer_strategy` default + `warn_flag: sensitivity_slot_inferred`. Silent convention changes on the manufacturer side are undetectable without SPL identity check triggering.
