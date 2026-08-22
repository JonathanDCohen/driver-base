"""Unit-parser tests. Every entry is a real value string captured during
recon of the 9 v1 manufacturers."""

from __future__ import annotations

import pytest

from driver_base.units import (
    parse_bl_tm,
    parse_compliance_mm_per_n,
    parse_float,
    parse_frequency,
    parse_impedance,
    parse_le_mh,
    parse_length_mm,
    parse_liters,
    parse_mass_g,
    parse_percent,
    parse_power,
    parse_range,
    parse_sd_cm2,
)


def close(a: float, b: float, rel: float = 0.01) -> bool:
    return abs(a - b) <= max(abs(a), abs(b)) * rel


@pytest.mark.parametrize("s,expected", [
    ("31 Hz", 31.0),
    ("2500 Hz", 2500.0),
    ("1 kHz", 1000.0),
    ("2.5 kHz", 2500.0),
    ("4,000 Hz", 4000.0),
    ("47.60Hz", 47.60),
    ("30", 30.0),
])
def test_parse_frequency(s: str, expected: float) -> None:
    assert parse_frequency(s) == pytest.approx(expected)


@pytest.mark.parametrize("s,expected", [
    ("45÷5000 Hz", (45.0, 5000.0)),
    ("45 - 5000 Hz", (45.0, 5000.0)),
    ("45–5000 Hz", (45.0, 5000.0)),
    ("28 - 2500 Hz", (28.0, 2500.0)),
    ("40-3000Hz", (40.0, 3000.0)),
    ("30 - 4,000 Hz", (30.0, 4000.0)),
    ("35 to 1000 Hz", (35.0, 1000.0)),
    ("1 - 2 kHz", (1000.0, 2000.0)),
    # Eminence mixed units: low = Hz, high = kHz
    ("33 Hz - 0.3 kHz", (33.0, 300.0)),
    ("50 Hz - 2 kHz", (50.0, 2000.0)),
])
def test_parse_range(s: str, expected: tuple[float, float]) -> None:
    got = parse_range(s)
    assert got is not None
    assert got == pytest.approx(expected)


def test_parse_range_none_when_only_one_number() -> None:
    assert parse_range("just 42 Hz") is None


@pytest.mark.parametrize("s,expected", [
    ("8 Ω", 8.0),
    ("6.4 Ω", 6.4),
    ("6.7Ω", 6.7),
    ("8 Ohm", 8.0),
    ("5.15Ω", 5.15),
    ("8 ohms", 8.0),
])
def test_parse_impedance(s: str, expected: float) -> None:
    assert parse_impedance(s) == pytest.approx(expected)


@pytest.mark.parametrize("s,expected", [
    ("1000 W", 1000.0),
    ("250W", 250.0),
    ("50 watts", 50.0),
    ("1600 W AES", 1600.0),
    ("1.2 kW", 1200.0),
])
def test_parse_power(s: str, expected: float) -> None:
    assert parse_power(s) == pytest.approx(expected)


@pytest.mark.parametrize("s,expected", [
    # every Bl unit variant seen across the 9 manufacturers
    ("24.7 Txm", 24.7),          # 18Sound: letter x as multiplier
    ("15.5 Tm", 15.5),           # B&C
    ("14.57Tm", 14.57),          # Celestion no space
    ("17.2 T-M", 17.2),          # Eminence hyphen
    ("27.80 T x m", 27.80),      # RCF spaced
    ("35.7 T/M", 35.7),          # HOQS slash
    ("13.5 N/A", 13.5),          # Faital Newton-per-Ampere
    ("26.9 N/A", 26.9),          # Beyma
])
def test_parse_bl_tm_all_variants(s: str, expected: float) -> None:
    assert parse_bl_tm(s) == pytest.approx(expected)


@pytest.mark.parametrize("s,expected", [
    ("460 mm ( in)", 460.0),
    ("460 mm (18.11 in)", 460.0),
    ("100 mm", 100.0),
    ("13.5 cm", 135.0),
    ('6.50"', 165.1),
    ("6.50 in", 165.1),
    ("1 m", 1000.0),
])
def test_parse_length_mm(s: str, expected: float) -> None:
    got = parse_length_mm(s)
    assert got is not None
    assert close(got, expected, rel=0.001)


@pytest.mark.parametrize("s,expected", [
    ("190.0 g", 190.0),
    ("143 grams", 143.0),
    ("281.5 grams", 281.5),
    ("13.3 kg", 13300.0),
    ("0.252 kg", 252.0),
    ("3.3 lbs.", 1496.85),
    ("109 oz.", 3090.10),
])
def test_parse_mass_g(s: str, expected: float) -> None:
    got = parse_mass_g(s)
    assert got is not None
    assert close(got, expected, rel=0.001)


@pytest.mark.parametrize("s,expected", [
    ("297.0 dm3 (10.49 ft3)", 297.0),
    ("148.41l / 5.24ft3", 148.41),
    ("242 liters", 242.0),
    ("143,9 (5.08)", 143.9),        # European decimal comma
    ("11.71 cu.ft.", 331.5),        # imperial only → convert
    ("113.3 dm^3 (4.00 ft^3)", 113.3),   # Faital caret-notation superscript
])
def test_parse_liters(s: str, expected: float) -> None:
    got = parse_liters(s)
    assert got is not None
    assert close(got, expected, rel=0.005)


@pytest.mark.parametrize("s,expected", [
    ("1225 cm2", 1225.0),
    ("1225.0 cm2 (189.88 in2)", 1225.0),
    ("134.8 cm²", 134.8),
    ("1225 sq cm", 1225.0),
    ("0.120 m2", 1200.0),
    ("0.1255 m²", 1255.0),
    ("539 cm^2 (83.55 in^2)", 539.0),   # Faital caret notation
])
def test_parse_sd_cm2(s: str, expected: float) -> None:
    got = parse_sd_cm2(s)
    assert got is not None
    assert close(got, expected, rel=0.005)


@pytest.mark.parametrize("s,expected", [
    ("2.3 mH", 2.3),
    ("0.90mH", 0.90),
    ("1.461 mH", 1.461),
    ("1.59m H", 1.59),               # Eminence weird spacing
    ("2.26 mH @ 1 kHz", 2.26),       # annotation
])
def test_parse_le_mh(s: str, expected: float) -> None:
    assert parse_le_mh(s) == pytest.approx(expected)


@pytest.mark.parametrize("s,expected", [
    ("0.28 mm/N", 0.28),
    ("0.68 mm/N", 0.68),
    ("85 µm/N", 0.085),
    ("85  µm / N", 0.085),
    ("0,068", 0.068),                # European decimal
])
def test_parse_compliance(s: str, expected: float) -> None:
    got = parse_compliance_mm_per_n(s)
    assert got is not None
    assert close(got, expected, rel=0.001)


@pytest.mark.parametrize("s,expected", [
    ("3.6 %", 3.6),
    ("2.06 %", 2.06),
    ("1.42%", 1.42),
])
def test_parse_percent(s: str, expected: float) -> None:
    assert parse_percent(s) == pytest.approx(expected)


@pytest.mark.parametrize("s", ["", None, "   ", "abc"])
def test_parse_float_none(s) -> None:
    assert parse_float(s) is None
