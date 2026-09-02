"""normalize_label test table — every entry is a real label from the 9 v1 manufacturers."""

from __future__ import annotations

import pytest

from driver_base.labels import normalize_label


@pytest.mark.parametrize(
    "raw,expected",
    [
        # descriptive parenthetical → stripped
        ("Resonance Frequency (Fs)", "resonance frequency"),
        ("Total Q (Qts)", "total q"),
        ("Vas (Equivalent Cas air loaded)", "vas"),
        # numeric footnote suffix → stripped
        ("AES Power Handling (1)", "aes power handling"),
        ("Xmax (4)", "xmax"),
        ("Xdamage (5)", "xdamage"),
        ("Cone Surround (3)", "cone surround"),
        # (Xmax) parenthetical must NOT trigger the "max" measurement-context token
        ("Maximum Linear Excursion (Xmax)", "maximum linear excursion"),
        ("Total Q (Qts)", "total q"),
        # measurement-context parenthetical → preserved
        ("Power Handling (RMS)", "power handling (rms)"),
        ("Power Handling (max)", "power handling (max)"),
        ("Xmax (Linear one-way)", "xmax (linear one-way)"),
        ("Xmech (Peak to peak)", "xmech (peak to peak)"),
        # unit annotation embedded in parenthetical (routes sensitivity slot)
        ("Sensitivity (1W/1m)", "sensitivity (1w/1m)"),
        ("SPL (Sensitivity 2.83Vrms)", "spl (2.83vrms)"),
        ("Sensitivity (dB 1W/1m)", "sensitivity (1w/1m)"),
        # unicode fold
        ("η₀", "eta0"),
        ("η", "eta"),
        ("8 Ω", "8 ohm"),
        # multiple parentheticals (unit annotation + abbrev)
        ("Bl factor (Bl) (T x m)", "bl factor"),
        # asterisk trailing
        ("Fs*", "fs"),
        # comma-suffix variant on Celestion guitar drivers
        ("Resonance frequency, Fs", "resonance frequency, fs"),
        # empty / degenerate
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_label(raw: str, expected: str) -> None:
    assert normalize_label(raw) == expected


def test_distinct_measurement_context_routing() -> None:
    """The whole point: RMS and max map to DIFFERENT normalized keys."""
    assert normalize_label("Power Handling (RMS)") != normalize_label(
        "Power Handling (max)"
    )


def test_peak_to_peak_wins_over_peak() -> None:
    """Longest measurement-context token should suppress shorter substrings."""
    got = normalize_label("Xmech (Peak to peak)")
    assert "peak to peak" in got
    assert got.count("peak") == 2  # exactly the "peak to peak" occurrence
