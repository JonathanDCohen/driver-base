"""Unit parsers for the raw spec strings scrapers extract.

Each parser accepts an arbitrary string and returns a float (in the canonical
unit for that field) or None if the input cannot be parsed. Every parser is
defensive: bad input never raises, always returns None.

Canonical units (matching the Driver dataclass):
    frequency        Hz
    impedance        ohm
    length           mm
    mass             g
    power            W
    liters           l  (a.k.a. dm³)
    area             cm²
    bl               T·m  (equivalent to N/A)
    compliance       mm/N
    inductance       mH

Comma vs. period as decimal separator: European catalogs (La Voce, some Faital)
use `,` as a decimal separator (e.g. `0,068`). Others use `.`. `parse_frequency`
treats `,` as a thousands separator (Dayton `30 - 4,000 Hz`). Other parsers
treat `,` as a decimal (converting to `.`).
"""

from __future__ import annotations

import re
from typing import Optional

# Match a signed float; accepts . or , as the decimal marker.
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _first_float(s: Optional[str], comma_is_decimal: bool = True) -> Optional[float]:
    """Extract the first float from a string. None on failure."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    token = m.group(0)
    if comma_is_decimal and "," in token and "." not in token:
        token = token.replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _all_floats(s: Optional[str], comma_is_decimal: bool = True) -> list[float]:
    """Extract every float from a string; empty list on failure."""
    if s is None:
        return []
    out: list[float] = []
    for m in _NUM_RE.finditer(s):
        token = m.group(0)
        if comma_is_decimal and "," in token and "." not in token:
            token = token.replace(",", ".")
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def parse_frequency(s: Optional[str]) -> Optional[float]:
    """Return Hz. Handles 'kHz' multiplier and thousands commas ('4,000 Hz')."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    stripped = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)  # strip thousands commas only
    v = _first_float(stripped, comma_is_decimal=True)
    if v is None:
        return None
    if re.search(r"\bkhz\b", s, re.IGNORECASE):
        v *= 1000.0
    return v


def parse_range(s: Optional[str]) -> Optional[tuple[float, float]]:
    """Return (low_hz, high_hz). Accepts '-', '–', '÷', 'to' separators.

    Interior '-' inside `40-3000Hz` is a separator, not a sign — endpoints
    are taken as absolute values.

    Mixed units per endpoint are respected: `"33 Hz - 0.3 kHz"` → (33, 300),
    not (33000, 300).
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # Strip thousands commas so 4,000 doesn't fragment into two numbers.
    # Use (?!\d) not \b — `20,000Hz` has no word boundary between `000` and `Hz`
    # (both are word chars), which caused Celestion's "800-20,000Hz" to parse
    # as (20, 800) instead of (800, 20000).
    stripped = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)

    # First-pass: look for explicitly unit-tagged endpoints so mixed
    # `33 Hz - 0.3 kHz` handles correctly.
    tagged = re.findall(
        r"(-?\d+(?:[.,]\d+)?)\s*(khz|hz)\b",
        stripped,
        re.IGNORECASE,
    )
    if len(tagged) >= 2:
        (a_s, a_u), (b_s, b_u) = tagged[0], tagged[1]
        low = abs(float(a_s.replace(",", "."))) * (1000.0 if a_u.lower() == "khz" else 1.0)
        high = abs(float(b_s.replace(",", "."))) * (1000.0 if b_u.lower() == "khz" else 1.0)
    else:
        nums = [abs(n) for n in _all_floats(stripped, comma_is_decimal=True)]
        if len(nums) < 2:
            return None
        low, high = nums[0], nums[1]
        if re.search(r"\bkhz\b", s, re.IGNORECASE):
            low *= 1000.0
            high *= 1000.0

    if low > high:
        low, high = high, low
    return low, high


def parse_impedance(s: Optional[str]) -> Optional[float]:
    """Return ohm."""
    return _first_float(s)


def parse_power(s: Optional[str]) -> Optional[float]:
    """Return watts. Handles kW and thousands commas ('1,300 watts')."""
    if s is None:
        return None
    # Strip thousands commas first so '1,300' isn't read as European '1.300'
    # by _first_float's comma-is-decimal heuristic. Dayton's spec tables
    # write four-digit power ratings this way ('1,300 watts', '2,600 watts').
    stripped = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)
    v = _first_float(stripped)
    if v is None:
        return None
    if re.search(r"\bkw\b", s, re.IGNORECASE):
        v *= 1000.0
    return v


def parse_percent(s: Optional[str]) -> Optional[float]:
    return _first_float(s)


def parse_length_mm(s: Optional[str]) -> Optional[float]:
    """Return mm. Prefers metric if both metric and imperial are present.

    Examples:
      '460 mm (18.19 in)'  -> 460.0
      '6.50"'              -> 165.1
      '3.3 in'             -> 83.82
      '13.5 cm'            -> 135.0
      '0.5 m'              -> 500.0
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    metric_m = re.search(
        r"(-?\d+(?:[.,]\d+)?)\s*(mm|cm|m)\b", s, re.IGNORECASE
    )
    if metric_m:
        val = float(metric_m.group(1).replace(",", "."))
        unit = metric_m.group(2).lower()
        return val * {"mm": 1.0, "cm": 10.0, "m": 1000.0}[unit]
    imperial_m = re.search(r'(-?\d+(?:[.,]\d+)?)\s*(?:in\b|")', s, re.IGNORECASE)
    if imperial_m:
        return float(imperial_m.group(1).replace(",", ".")) * 25.4
    ft_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:ft\b|')", s, re.IGNORECASE)
    if ft_m:
        return float(ft_m.group(1).replace(",", ".")) * 304.8
    return _first_float(s)  # last-resort: assume already mm


def parse_mass_g(s: Optional[str]) -> Optional[float]:
    """Return grams. Handles kg, g, lb/lbs, oz."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    kg_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*kg\b", s, re.IGNORECASE)
    if kg_m:
        return float(kg_m.group(1).replace(",", ".")) * 1000.0
    g_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:g|grams?)\b", s, re.IGNORECASE)
    if g_m:
        return float(g_m.group(1).replace(",", "."))
    lb_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:lbs?\.?|pounds?)\b", s, re.IGNORECASE)
    if lb_m:
        return float(lb_m.group(1).replace(",", ".")) * 453.592
    oz_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*oz\b", s, re.IGNORECASE)
    if oz_m:
        return float(oz_m.group(1).replace(",", ".")) * 28.3495
    return _first_float(s)  # last-resort


def parse_liters(s: Optional[str]) -> Optional[float]:
    """Return liters (= dm³). Prefers metric.

    Examples:
      '297.0 dm3 (10.49 ft3)'      -> 297.0
      '148.41l / 5.24ft3'          -> 148.41
      '242 liters'                 -> 242.0
      '11.71 cu.ft.'               -> 331.5
      '0,068' (European decimal)   -> 0.068
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    metric_m = re.search(
        r"(-?\d+(?:[.,]\d+)?)\s*(?:dm\s*\^?\s*[³3]|l\b|liters?|litres?)",
        s,
        re.IGNORECASE,
    )
    if metric_m:
        return float(metric_m.group(1).replace(",", "."))
    ft3_m = re.search(
        r"(-?\d+(?:[.,]\d+)?)\s*(?:ft\s*\^?\s*[³3]|cu\.?\s*ft\.?)", s, re.IGNORECASE
    )
    if ft3_m:
        return float(ft3_m.group(1).replace(",", ".")) * 28.3168
    return _first_float(s)


def parse_sd_cm2(s: Optional[str]) -> Optional[float]:
    """Return cm². Handles m² and in²."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    cm2_m = re.search(
        r"(-?\d+(?:[.,]\d+)?)\s*(?:cm\s*\^?\s*[²2]|sq\.?\s*cm)", s, re.IGNORECASE
    )
    if cm2_m:
        return float(cm2_m.group(1).replace(",", "."))
    m2_m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*m\s*\^?\s*[²2]\b", s, re.IGNORECASE)
    if m2_m:
        return float(m2_m.group(1).replace(",", ".")) * 10000.0
    in2_m = re.search(
        r"(-?\d+(?:[.,]\d+)?)\s*(?:in\s*\^?\s*[²2]|sq\.?\s*in)", s, re.IGNORECASE
    )
    if in2_m:
        return float(in2_m.group(1).replace(",", ".")) * 6.4516
    return _first_float(s)


def parse_bl_tm(s: Optional[str]) -> Optional[float]:
    """Return T·m. The Bl 'unit' varies wildly:

      '24.7 Txm'   (18Sound; letter x as multiplier)
      '15.5 Tm'    (B&C)
      '14.57Tm'    (Celestion; no space)
      '17.2 T-M'   (Eminence; hyphen)
      '27.80 T x m' (RCF; spaced)
      '35.7 T/M'   (HOQS; slash — treated as multiplication)
      '13.5 N/A'   (Faital; Newton-per-Ampere = T·m by physics)
      '26.9 N/A'   (Beyma)

    All variants reduce to: take the first float.
    """
    return _first_float(s)


def parse_le_mh(s: Optional[str]) -> Optional[float]:
    """Return mH. Handles Eminence's '1.59m H' (space + lowercase m), annotations
    like '@1 kHz' or '@ 1 kHz', and dual-unit strings."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    stripped = re.sub(r"@\s*\d+(?:\.\d+)?\s*k?Hz\b", "", s, flags=re.IGNORECASE)
    return _first_float(stripped)


def parse_compliance_mm_per_n(s: Optional[str]) -> Optional[float]:
    """Return mm/N. Converts µm/N → mm/N (÷1000)."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if re.search(r"[µu]m\s*/\s*N", s, re.IGNORECASE):
        v = _first_float(s)
        return v / 1000.0 if v is not None else None
    return _first_float(s)


def parse_float(s: Optional[str]) -> Optional[float]:
    """Bare float parser for Q values and other unitless fields."""
    return _first_float(s)
