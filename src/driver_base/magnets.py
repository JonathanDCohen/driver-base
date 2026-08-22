"""Coerce a raw magnet-material string to a MagnetType enum value."""

from __future__ import annotations

from typing import Optional

from driver_base.model import MagnetType


def normalize_magnet_type(raw: Optional[str]) -> Optional[MagnetType]:
    """Return the MagnetType enum for a raw spec value. None for empty input.

    Coercion rules:
      'Ferrite', 'ferrite', 'Ceramic', 'Ferrite Motor'   → CERAMIC
      'Neodymium', 'Neo', 'Neodymium Slug', 'Neo Ring'   → NEODYMIUM
      'Alnico', 'AlNiCo'                                 → ALNICO
      'Neo/Ferrite', 'hybrid', unknown/unparseable       → OTHER
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if not s:
        return None
    # Hybrid detection first — a Neo/Ferrite string mentions BOTH.
    mentions_neo = "neo" in s
    mentions_ferrite = "ferrite" in s or "ceramic" in s
    if mentions_neo and mentions_ferrite:
        return MagnetType.OTHER
    if mentions_neo:
        return MagnetType.NEODYMIUM
    if mentions_ferrite:
        return MagnetType.CERAMIC
    if "alnico" in s:
        return MagnetType.ALNICO
    return MagnetType.OTHER
