"""Label normalization: turn a raw spec label into a canonical lookup key.

Each scraper owns its own LABEL_TO_FIELD dict keyed on the OUTPUT of
`normalize_label(raw_label)`. Normalization:
  1. Unicode fold (Ω → 'ohm', η → 'eta', ÷ → '-', ₀ → '0', × → 'x', ...).
  2. Every parenthetical is stripped from the base ('AES Power Handling (1)' →
     'aes power handling'; 'Resonance Frequency (Fs)' → 'resonance frequency').
  3. Then measurement-context parentheticals ('RMS', 'max', 'peak', 'AES',
     'program', 'Continuous', 'EIA', '1W/1m', '2.83V/1m', 'peak to peak',
     'linear one-way') are re-appended in a canonical form so
     'Power Handling (RMS)' and 'Power Handling (max)' map to distinct keys.
  4. Lowercase, collapse whitespace.
"""

from __future__ import annotations

import re

# Unicode replacements applied before lowercasing.
# Multi-codepoint combined forms MUST precede their sub-tokens so the
# in-order replace pass catches them first.
_UNICODE_FOLD: dict[str, str] = {
    "η₀": "eta0",   # η + subscript 0
    "η°": "eta0",   # η + degree sign (defensive)
    "Ω": "ohm",          # ohm sign
    "Ω": "ohm",          # Greek capital omega
    "η": "eta",          # Greek small eta
    "μ": "u",            # Greek small mu
    "µ": "u",            # micro sign
    "÷": "-",            # division sign
    "–": "-",             # en dash
    "—": "-",             # em dash
    "×": "x",            # multiplication sign
    "³": "3",            # superscript 3
    "²": "2",            # superscript 2
    "₀": "0",            # subscript 0
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    " ": " ",            # non-breaking space
}

# Parentheticals that must be PRESERVED because they route to a different field.
# Ordered longest-first so "peak to peak" wins over "peak", "2.83vrms" over "rms".
_MEASUREMENT_CONTEXT_TOKENS: list[str] = [
    "linear one-way",
    "peak to peak",
    "2.83v/1m",
    "2.83vrms",
    "1w/1m",
    "continuous",
    "maximum",
    "program",
    "peak",
    "max",
    "rms",
    "aes",
    "eia",
]

_ASTERISK_TRAILING_RE = re.compile(r"\s*\*+\s*$")


def _fold_unicode(s: str) -> str:
    for k, v in _UNICODE_FOLD.items():
        if k in s:
            s = s.replace(k, v)
    return s


def _preserve_measurement_context(raw: str, normalized: str) -> str:
    """If raw contains a measurement-context parenthetical, retain it in the
    normalized form. Word-boundary-matches each token against the
    parenthetical content, then prunes tokens subsumed by a longer matched
    token so 'peak to peak' doesn't also register as 'peak'.

    Word-boundary matching is critical: bare `token in inner` misfires on
    'max' inside '(Xmax)', appending a spurious '(max)' to the normalized
    key.
    """
    hits: list[str] = []
    for m in re.finditer(r"[\(\[]([^)\]]+)[\)\]]", raw):
        inner = _fold_unicode(m.group(1)).strip().lower()
        for token in _MEASUREMENT_CONTEXT_TOKENS:  # longest-first
            if token in hits:
                continue
            pattern = r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])"
            if not re.search(pattern, inner):
                continue
            # skip if another (longer) already-matched token contains this one
            if any(token in longer and token != longer for longer in hits):
                continue
            hits.append(token)
    if hits:
        joined = " ".join(sorted(set(hits)))
        return f"{normalized} ({joined})"
    return normalized


def normalize_label(raw: str) -> str:
    """Turn a raw scraper label into a stable lookup key."""
    if not raw:
        return ""
    folded = _fold_unicode(raw)
    # Strip every parenthetical/bracket for the base
    base = re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", folded)
    base = _ASTERISK_TRAILING_RE.sub("", base)
    base = re.sub(r"\s+", " ", base).strip().lower()
    return _preserve_measurement_context(folded, base)
