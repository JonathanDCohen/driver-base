"""Scraper registry. Subclasses register themselves via @register decorator."""

from __future__ import annotations

from driver_base.interface import Scraper

SCRAPERS: dict[str, type[Scraper]] = {}


def register(cls: type[Scraper]) -> type[Scraper]:
    """Decorator: add a Scraper subclass to the registry keyed on cls.name."""
    if not getattr(cls, "name", None):
        raise ValueError(f"{cls.__name__} must declare a class-level `name` attribute")
    if cls.name in SCRAPERS:
        raise ValueError(
            f"Duplicate scraper name {cls.name!r}: "
            f"{SCRAPERS[cls.name].__name__} vs {cls.__name__}"
        )
    SCRAPERS[cls.name] = cls
    return cls


def instantiate_all() -> list[Scraper]:
    """Import concrete scraper modules and return instances of each registered class."""
    from driver_base.scrapers import bcspeakers  # noqa: F401
    from driver_base.scrapers import beyma  # noqa: F401
    from driver_base.scrapers import celestion  # noqa: F401
    from driver_base.scrapers import dayton  # noqa: F401
    from driver_base.scrapers import eighteensound  # noqa: F401
    from driver_base.scrapers import eminence  # noqa: F401
    from driver_base.scrapers import faital  # noqa: F401
    from driver_base.scrapers import hoqs  # noqa: F401
    from driver_base.scrapers import rcf  # noqa: F401
    return [cls() for cls in SCRAPERS.values()]
