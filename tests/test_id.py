"""canonical_id derivation tests."""

from __future__ import annotations

import pytest

from driver_base.id import build_canonical_id, encode_impedance, slugify


@pytest.mark.parametrize(
    "s,expected",
    [
        ("18LW1400", "18lw1400"),
        ("18-LW-1400", "18_lw_1400"),
        ("18 LW 1400", "18_lw_1400"),
        # Greek letters have no ASCII decomposition — they get dropped, leaving
        # separators. Empty result is the expected outcome.
        ("Α-Ω", ""),
        ("N/A", "n_a"),
        ("", ""),
    ],
)
def test_slugify(s: str, expected: str) -> None:
    assert slugify(s) == expected


@pytest.mark.parametrize(
    "ohm,expected",
    [
        (8.0, "8ohm"),
        (4.0, "4ohm"),
        (2.5, "2p5ohm"),
        (12.0, "12ohm"),
        (3.2, "3p2ohm"),
        (16.0, "16ohm"),
        (None, None),
        (0.0, None),
        (-1.0, None),
    ],
)
def test_encode_impedance(ohm, expected) -> None:
    assert encode_impedance(ohm) == expected


def test_canonical_id_full() -> None:
    got = build_canonical_id(
        manufacturer_slug="18Sound",
        model="18LW1400",
        impedance_ohm=8.0,
        source_url="https://example.com/x",
    )
    assert got == "18sound__18lw1400__8ohm"


def test_canonical_id_fractional_impedance() -> None:
    got = build_canonical_id(
        manufacturer_slug="Dayton",
        model="ND25FN",
        impedance_ohm=2.5,
        source_url="https://example.com/x",
    )
    assert got == "dayton__nd25fn__2p5ohm"


def test_canonical_id_uses_seed_when_impedance_missing() -> None:
    got = build_canonical_id(
        manufacturer_slug="celestion",
        model="G12-EVH",
        impedance_ohm=None,
        source_url="https://example.com/x",
        canonical_id_seed="11103",
    )
    assert got == "celestion__g12_evh__11103"


def test_canonical_id_falls_back_to_url_slug() -> None:
    got = build_canonical_id(
        manufacturer_slug="celestion",
        model="G12-EVH",
        impedance_ohm=None,
        source_url="https://celestion.com/product/g12-evh-16ohm/",
    )
    assert got == "celestion__g12_evh__g12_evh_16ohm"


def test_canonical_id_never_na() -> None:
    """Confirm the framework's 'NEVER use na' rule."""
    got = build_canonical_id(
        manufacturer_slug="somebrand",
        model="somemodel",
        impedance_ohm=None,
        source_url="",
        canonical_id_seed=None,
    )
    assert got is None  # no fallback → None (orchestrator drops fragment)


def test_canonical_id_returns_none_on_empty_model() -> None:
    assert (
        build_canonical_id(
            manufacturer_slug="X",
            model="",
            impedance_ohm=8.0,
            source_url="",
        )
        is None
    )
