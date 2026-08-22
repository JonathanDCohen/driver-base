"""Canonical id derivation for Driver records.

Scheme: `{mfg_slug}__{model_slug}__{impedance}ohm[__{variant}]`

Impedance encoding:
  8.0  → '8ohm'
  4.0  → '4ohm'
  2.5  → '2p5ohm'           (fractional; never int-truncated)
  None → uses canonical_id_seed, else URL-slug fallback, NEVER 'na'.

Deterministic tie-break for collisions is handled downstream in merge.py.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional
from urllib.parse import urlparse


def slugify(s: str) -> str:
    """Lower-case ASCII slug: strip diacritics, non-alphanumerics → '_',
    collapse runs of '_', trim leading/trailing '_'."""
    if not s:
        return ""
    norm = unicodedata.normalize("NFKD", s)
    ascii_ = norm.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_).strip("_").lower()
    return slug


def encode_impedance(ohm: Optional[float]) -> Optional[str]:
    """Encode ohm as a slug fragment. None for unparseable input.

    2.0   → '2ohm'
    2.5   → '2p5ohm'
    8.0   → '8ohm'
    3.2   → '3p2ohm'
    12.0  → '12ohm'
    None  → None
    """
    if ohm is None:
        return None
    if ohm <= 0:
        return None
    # Round to 1 decimal to avoid float noise (5.00000001 → 5.0)
    rounded = round(ohm, 1)
    if rounded == int(rounded):
        return f"{int(rounded)}ohm"
    integer, frac = str(rounded).split(".")
    return f"{integer}p{frac}ohm"


def _url_slug_fallback(source_url: str) -> Optional[str]:
    """Last-resort id suffix derived from the URL's last path segment."""
    if not source_url:
        return None
    try:
        path = urlparse(source_url).path
    except Exception:
        return None
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return slugify(last) or None


def build_canonical_id(
    *,
    manufacturer_slug: str,
    model: str,
    impedance_ohm: Optional[float],
    source_url: str,
    canonical_id_seed: Optional[str] = None,
    variant: Optional[str] = None,
) -> Optional[str]:
    """Build the canonical id or None if we cannot derive a stable key.

    Priority for the impedance segment:
      1. `encode_impedance(impedance_ohm)` if parseable
      2. slugified `canonical_id_seed` if provided (e.g. Celestion post-id)
      3. slugified last path segment of `source_url`
      4. Give up (return None) — orchestrator will treat as a REJECT and log.
    """
    mfg = slugify(manufacturer_slug)
    mod = slugify(model)
    if not mfg or not mod:
        return None
    imp = encode_impedance(impedance_ohm)
    if imp is None and canonical_id_seed:
        imp = slugify(canonical_id_seed)
    if imp is None:
        imp = _url_slug_fallback(source_url)
    if not imp:
        return None
    parts = [mfg, mod, imp]
    if variant:
        v = slugify(variant)
        if v:
            parts.append(v)
    return "__".join(parts)
