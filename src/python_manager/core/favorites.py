"""Packages the user marked as favourite, stored in the app config."""

from __future__ import annotations

import re

from . import config


def normalize(name: str) -> str:
    """PEP 503 normalised name, so 'Foo_Bar' and 'foo-bar' are the same package."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def list_favorites() -> list[str]:
    return sorted(config.get("favorites") or [], key=str.lower)


def is_favorite(name: str) -> bool:
    key = normalize(name)
    return any(normalize(f) == key for f in list_favorites())


def add(name: str) -> None:
    name = name.strip()
    if not name or is_favorite(name):
        return
    config.set("favorites", list_favorites() + [name])


def remove(name: str) -> None:
    key = normalize(name)
    config.set("favorites", [f for f in list_favorites() if normalize(f) != key])


def toggle(name: str) -> bool:
    """Flip the favourite state; returns True if the package is now a favourite."""
    if is_favorite(name):
        remove(name)
        return False
    add(name)
    return True
