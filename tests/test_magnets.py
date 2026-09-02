"""normalize_magnet_type test table."""

from __future__ import annotations

import pytest

from driver_base.magnets import normalize_magnet_type
from driver_base.model import MagnetType


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ferrite", MagnetType.CERAMIC),
        ("ferrite", MagnetType.CERAMIC),
        ("Ferrite Motor", MagnetType.CERAMIC),
        ("Ceramic", MagnetType.CERAMIC),
        ("Neodymium", MagnetType.NEODYMIUM),
        ("Neo", MagnetType.NEODYMIUM),
        ("Neodymium Slug", MagnetType.NEODYMIUM),
        ("Neo Ring", MagnetType.NEODYMIUM),
        ("Alnico", MagnetType.ALNICO),
        ("AlNiCo V", MagnetType.ALNICO),
        # hybrid → OTHER
        ("Neo/Ferrite", MagnetType.OTHER),
        ("Neo + Ferrite hybrid", MagnetType.OTHER),
        # unknown → OTHER
        ("Samarium Cobalt", MagnetType.OTHER),
        ("some new magnet", MagnetType.OTHER),
    ],
)
def test_normalize_magnet_type(raw: str, expected: MagnetType) -> None:
    assert normalize_magnet_type(raw) == expected


@pytest.mark.parametrize("s", ["", None, "   "])
def test_normalize_magnet_type_none(s) -> None:
    assert normalize_magnet_type(s) is None
