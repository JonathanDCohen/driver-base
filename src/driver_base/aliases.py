"""Load and apply data/aliases.yaml — canonical_id rewrites.

Two sections:

  canonical_id_aliases:
    OLD_canonical_id: NEW_canonical_id

  model_aliases:
    {manufacturer_slug}:
      old_model: new_model

Chains are transitive (`A→B; B→C` resolves `A→C`); cycles fail hard on load.
Applied BEFORE `merge_fragments_by_id` so grouping keys reflect the
post-rewrite ids.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from driver_base.model import DriverFragment


class AliasCycleError(Exception):
    """Raised when aliases.yaml contains a cycle in canonical_id_aliases."""


def load_aliases(path: Path) -> "Aliases":
    if not path.exists():
        return Aliases({}, {})
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    canonical = _resolve_chains(data.get("canonical_id_aliases") or {})
    model = data.get("model_aliases") or {}
    if not isinstance(model, dict):
        model = {}
    # normalize model section: {mfg_slug: {old: new}}
    model_norm: dict[str, dict[str, str]] = {}
    for mfg, mapping in model.items():
        if isinstance(mapping, dict):
            model_norm[str(mfg)] = {str(k): str(v) for k, v in mapping.items()}
    return Aliases(canonical, model_norm)


def _resolve_chains(raw: dict[str, str]) -> dict[str, str]:
    """Follow chains; raise on cycles. Returns {old: terminal_new}."""
    resolved: dict[str, str] = {}
    for start in raw:
        seen: list[str] = []
        cur = start
        while cur in raw:
            if cur in seen:
                raise AliasCycleError(
                    f"cycle in canonical_id_aliases: {' -> '.join(seen + [cur])}"
                )
            seen.append(cur)
            cur = raw[cur]
        resolved[start] = cur
    return resolved


class Aliases:
    def __init__(
        self,
        canonical: dict[str, str],
        model: dict[str, dict[str, str]],
    ) -> None:
        self._canonical = canonical
        self._model = model

    def rewrite_model(self, manufacturer_slug: str, model: str) -> str:
        """Return the aliased model if any, else the original."""
        return self._model.get(manufacturer_slug, {}).get(model, model)

    def rewrite_canonical_id(self, canonical_id: str) -> str:
        """Return the aliased canonical_id if any, else the original."""
        return self._canonical.get(canonical_id, canonical_id)


def apply_aliases(
    fragments: list[DriverFragment], aliases: Optional[Aliases]
) -> list[DriverFragment]:
    """Rewrite each fragment's canonical_id in place (only if set) via the
    canonical-id alias table. `model_aliases` is applied at parse time by the
    scraper — this hook covers the post-parse canonical_id rewrite path.
    """
    if aliases is None:
        return fragments
    for f in fragments:
        if f.canonical_id is not None:
            f.canonical_id = aliases.rewrite_canonical_id(f.canonical_id)
    return fragments
