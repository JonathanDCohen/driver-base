"""Hand-patched field values for individual drivers.

Used sparingly, for cases where a manufacturer's own published spec is
wrong (typo, obvious data-entry error) and we have high confidence in the
correct value from another source on the same page (URL slug, product
name, feature bullets, datasheet PDF).

Every entry declares a `still_needed(driver)` predicate that gates whether
the override actually fires this run. The predicate must check that the
freshly-parsed value is STILL the specific bad value we're compensating
for — NOT that it matches our corrected value. Rationale:

  1. `d.field == OUR_VALUE` assumes we're right. If the vendor later
     publishes a different-but-still-plausible value, that check would
     force-overwrite legitimate new data with our guess.
  2. Equality on floats is fragile: 457.2 vs 457.20 vs 460.0 (mm) would
     all trip an anti-match test in surprising ways.

So we phrase predicates as `did we just re-parse the known-bad value`.
When the predicate returns False, the override is skipped and a
`warn_flag: override_no_longer_needed:{field}` is stamped on the driver
so a human knows to retire the entry from OVERRIDES.

Applied post-merge, right before drivers.json is written. Each overridden
field is stamped `spec_source = OVERRIDE` and its `note` (if any) is
written to `Driver.override_notes[field_name]` so the UI popover can
surface the specific reason on click.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dc_fields
from typing import Any, Callable, Optional

from driver_base.model import Driver, SpecSource


class OverrideError(Exception):
    """Raised when an OVERRIDES entry targets an unknown or bookkeeping field."""


_DRIVER_FIELD_TYPES: dict[str, Any] = {f.name: f.type for f in dc_fields(Driver)}

# Bookkeeping fields — never a valid override target.
_NON_OVERRIDABLE: frozenset[str] = frozenset(
    {
        "manufacturer",
        "canonical_id",
        "driver_kind",
        "model",
        "spec_source",
        "source_urls",
        "fetched_at",
        "scraped_at",
        "last_scraped_at",
        "status",
        "warn_flags",
        "override_notes",
    }
)


@dataclass(frozen=True)
class Override:
    """One hand-patched field on one driver.

    Attributes:
        canonical_id: the driver to patch (silently no-ops if the driver
            isn't in this run's dataset — a manufacturer might have been
            preserved via gate failure).
        field: the Driver dataclass field to overwrite.
        value: the replacement value. Types are not coerced — pass the
            right shape (float for float fields, MagnetType enum for
            magnet_type, etc.).
        still_needed: **required** predicate over the pre-override Driver.
            Return True when the upstream data still exhibits the bad
            value this override corrects. There is intentionally no
            default: every override must declare when it can be retired,
            otherwise stale patches accumulate forever with no signal to
            remove them. Phrase as "the freshly-parsed value still equals
            the known-bad value" — see the module docstring for why.
        note: optional short sentence surfaced in the web UI popover on
            click of the override sigil. Keep tight.
    """

    canonical_id: str
    field: str
    value: Any
    still_needed: Callable[[Driver], bool]
    note: Optional[str] = None


OVERRIDES: list[Override] = [
    Override(
        canonical_id="dayton__ss18_22__2ohm",
        field="nominal_size_mm",
        value=457.2,
        note="Dayton's spec table lists 15\"",
        # Dayton's product-page spec table lists Nominal Diameter as 15"
        # (381 mm) — a typo; every other signal on the page (URL slug,
        # model number, feature-bullet, 470 mm overall diameter) says 18".
        # Predicate is "the table still says 15 inches" — if Dayton fixes
        # it, we'll get a warn_flag and can retire this entry.
        still_needed=lambda d: d.nominal_size_mm == 381.0,
    ),
]


def _validate() -> None:
    """Called at import time — fails loudly on typos in OVERRIDES."""
    for ov in OVERRIDES:
        if ov.field not in _DRIVER_FIELD_TYPES:
            raise OverrideError(
                f"OVERRIDES entry {ov.canonical_id!r}: field {ov.field!r} is not a Driver field"
            )
        if ov.field in _NON_OVERRIDABLE:
            raise OverrideError(
                f"OVERRIDES entry {ov.canonical_id!r}: field {ov.field!r} is a bookkeeping field, not overridable"
            )


_validate()


@dataclass
class OverrideStats:
    applied_fields: int = 0  # (canonical_id, field) pairs actually written
    applied_drivers: int = 0  # distinct drivers touched
    retired_entries: list[str] = field(
        default_factory=list
    )  # "cid.field" for each entry whose predicate returned False
    missing_ids: list[str] = field(
        default_factory=list
    )  # canonical_ids in OVERRIDES not present in this run


def apply_overrides(drivers: list[Driver]) -> OverrideStats:
    """Mutate `drivers` in place. Returns a stats bundle for logging.

    For each Override:
      - if its canonical_id isn't in `drivers`, record it in missing_ids
        and continue (a preserved-manufacturer scenario)
      - if still_needed(driver) is False, log warn_flag on the driver and
        record the entry in retired_entries (skip the patch)
      - otherwise write the value, stamp spec_source=OVERRIDE, and add the
        note to driver.override_notes (if the entry declared one)
    """
    by_id: dict[str, Driver] = {d.canonical_id: d for d in drivers}
    touched_drivers: set[str] = set()
    stats = OverrideStats()
    for ov in OVERRIDES:
        driver = by_id.get(ov.canonical_id)
        if driver is None:
            stats.missing_ids.append(ov.canonical_id)
            continue
        if not ov.still_needed(driver):
            flag = f"override_no_longer_needed:{ov.field}"
            if flag not in driver.warn_flags:
                driver.warn_flags.append(flag)
            stats.retired_entries.append(f"{ov.canonical_id}.{ov.field}")
            continue
        setattr(driver, ov.field, ov.value)
        driver.spec_source[ov.field] = SpecSource.OVERRIDE
        if ov.note:
            driver.override_notes[ov.field] = ov.note
        touched_drivers.add(ov.canonical_id)
        stats.applied_fields += 1
    stats.applied_drivers = len(touched_drivers)
    return stats
