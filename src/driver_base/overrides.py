"""Load and apply data/overrides.yaml — hand-patched field values.

Schema:

  overrides:
    {canonical_id}:
      reason: "free-text why this override exists (not written to drivers.json)"
      fields:
        {field_name}: {value}
        ...

Applied post-merge, right before drivers.json is written. Each overridden
field is stamped with `spec_source = override` so the UI can flag it.

Unknown canonical_ids and unknown field names raise on load — this file is
hand-edited and typos should fail loudly.
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


class Overrides:
    def __init__(self, entries: dict[str, dict[str, Any]]) -> None:
        # {canonical_id: {field_name: coerced_value}}
        self._entries = entries

    def canonical_ids(self) -> list[str]:
        return list(self._entries.keys())

    def fields_for(self, canonical_id: str) -> dict[str, Any]:
        return self._entries.get(canonical_id, {})


def load_overrides(path: Path) -> Overrides:
    if not path.exists():
        return Overrides({})
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    raw = data.get("overrides") or {}
    if not isinstance(raw, dict):
        raise OverrideError("overrides.yaml: top-level `overrides:` must be a mapping")
    entries: dict[str, dict[str, Any]] = {}
    for cid, body in raw.items():
        if not isinstance(body, dict):
            raise OverrideError(f"overrides.yaml: entry {cid!r} must be a mapping")
        fields = body.get("fields") or {}
        if not isinstance(fields, dict):
            raise OverrideError(f"overrides.yaml: entry {cid!r} `fields:` must be a mapping")
        coerced: dict[str, Any] = {}
        for name, val in fields.items():
            if name not in _DRIVER_FIELD_TYPES:
                raise OverrideError(
                    f"overrides.yaml: entry {cid!r} field {name!r} is not a Driver field"
                )
            coerced[name] = _coerce(name, val)
        entries[str(cid)] = coerced
    return Overrides(entries)


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
        for name, val in overrides.fields_for(cid).items():
            setattr(driver, name, val)
            driver.spec_source[name] = SpecSource.OVERRIDE
            f_touched += 1
    return d_touched, f_touched
