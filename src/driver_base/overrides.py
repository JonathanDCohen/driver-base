"""Load and apply data/overrides.yaml — hand-patched field values.

Schema:

  overrides:
    {canonical_id}:
      reason: "free-text why this override exists (not written to drivers.json)"
      fields:
        {field_name}:
          value: {value}
          note: "short, user-facing sentence for the web UI popover"
        # or plain scalar shorthand when a UI note isn't needed:
        {field_name}: {value}

Applied post-merge, right before drivers.json is written. Each overridden
field is stamped with `spec_source = override` so the UI can flag it, and
its optional `note` is written to `Driver.override_notes[field_name]` so
the UI can surface the specific reason on click.

Unknown field names raise on load — this file is hand-edited and typos
should fail loudly.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path
from typing import Any

import yaml

from driver_base.model import Driver, MagnetType, SpecSource


class OverrideError(Exception):
    """Raised for malformed or field-unknown entries in overrides.yaml."""


_DRIVER_FIELD_TYPES: dict[str, Any] = {f.name: f.type for f in dc_fields(Driver)}

# Bookkeeping fields — never a valid override target.
_NON_OVERRIDABLE: frozenset[str] = frozenset({
    "manufacturer", "canonical_id", "driver_kind", "model",
    "spec_source", "source_urls",
    "fetched_at", "scraped_at", "last_scraped_at",
    "status", "warn_flags", "override_notes",
})


class Overrides:
    def __init__(
        self,
        values: dict[str, dict[str, Any]],
        notes: dict[str, dict[str, str]],
    ) -> None:
        # {canonical_id: {field_name: coerced_value}}
        self._values = values
        # {canonical_id: {field_name: note_string}} — only fields with a note
        self._notes = notes

    def canonical_ids(self) -> list[str]:
        return list(self._values.keys())

    def fields_for(self, canonical_id: str) -> dict[str, Any]:
        return self._values.get(canonical_id, {})

    def notes_for(self, canonical_id: str) -> dict[str, str]:
        return self._notes.get(canonical_id, {})


def load_overrides(path: Path) -> Overrides:
    if not path.exists():
        return Overrides({}, {})
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw = data.get("overrides") or {}
    if not isinstance(raw, dict):
        raise OverrideError("overrides.yaml: top-level `overrides:` must be a mapping")
    values: dict[str, dict[str, Any]] = {}
    notes: dict[str, dict[str, str]] = {}
    for cid, body in raw.items():
        if not isinstance(body, dict):
            raise OverrideError(f"overrides.yaml: entry {cid!r} must be a mapping")
        fields = body.get("fields") or {}
        if not isinstance(fields, dict):
            raise OverrideError(f"overrides.yaml: entry {cid!r} `fields:` must be a mapping")
        entry_values: dict[str, Any] = {}
        entry_notes: dict[str, str] = {}
        for name, spec in fields.items():
            if name not in _DRIVER_FIELD_TYPES:
                raise OverrideError(
                    f"overrides.yaml: entry {cid!r} field {name!r} is not a Driver field"
                )
            if name in _NON_OVERRIDABLE:
                raise OverrideError(
                    f"overrides.yaml: entry {cid!r} field {name!r} is a bookkeeping field, not overridable"
                )
            if isinstance(spec, dict):
                if "value" not in spec:
                    raise OverrideError(
                        f"overrides.yaml: entry {cid!r} field {name!r} mapping must include `value:`"
                    )
                entry_values[name] = _coerce(name, spec["value"])
                note = spec.get("note")
                if note is not None:
                    entry_notes[name] = str(note).strip()
            else:
                entry_values[name] = _coerce(name, spec)
        values[str(cid)] = entry_values
        if entry_notes:
            notes[str(cid)] = entry_notes
    return Overrides(values, notes)


def _coerce(name: str, val: Any) -> Any:
    # Enum-valued fields need string→enum conversion so downstream code that
    # asks for e.g. `d.magnet_type.value` doesn't break.
    if name == "magnet_type" and isinstance(val, str):
        try:
            return MagnetType(val)
        except ValueError as e:
            raise OverrideError(f"overrides.yaml: bad magnet_type {val!r}") from e
    return val


def apply_overrides(drivers: list[Driver], overrides: Overrides) -> tuple[int, int]:
    """Mutate `drivers` in place. Returns (drivers_touched, fields_touched).

    Overrides for canonical_ids not present in `drivers` are silently skipped
    (a manufacturer might have been dropped by a gate this run — we shouldn't
    force it back). Callers can compare `len(overrides.canonical_ids())` with
    the returned count to detect that case.
    """
    by_id = {d.canonical_id: d for d in drivers}
    d_touched = 0
    f_touched = 0
    for cid in overrides.canonical_ids():
        driver = by_id.get(cid)
        if driver is None:
            continue
        d_touched += 1
        notes = overrides.notes_for(cid)
        for name, val in overrides.fields_for(cid).items():
            setattr(driver, name, val)
            driver.spec_source[name] = SpecSource.OVERRIDE
            if name in notes:
                driver.override_notes[name] = notes[name]
            f_touched += 1
    return d_touched, f_touched
