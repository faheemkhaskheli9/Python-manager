"""Cached list of every project name on PyPI, used for name autocomplete."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import net, paths
from .tasks import NULL, TaskContext

SIMPLE_URL = "https://pypi.org/simple/"
MAX_AGE = 7 * 24 * 3600  # refresh the cache weekly


def cache_file() -> Path:
    return paths.cache_dir() / "pypi-names.txt"


def cached() -> list[str]:
    """Names from the cache, sorted case-insensitively; empty when there is no cache."""
    try:
        return cache_file().read_text(encoding="utf-8").split()
    except OSError:
        return []


def is_stale() -> bool:
    try:
        return time.time() - cache_file().stat().st_mtime > MAX_AGE
    except OSError:
        return True


def fetch(ctx: TaskContext = NULL) -> list[str]:
    """Download the name list from PyPI's JSON simple index and cache it."""
    ctx.log("Downloading the PyPI package list…")
    data = json.loads(net.get_text(SIMPLE_URL, {"Accept": "application/vnd.pypi.simple.v1+json"}, timeout=120))
    ctx.check()
    names = sorted({p["name"] for p in data.get("projects", []) if p.get("name")}, key=str.lower)
    target = cache_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text("\n".join(names), encoding="utf-8")
    tmp.replace(target)
    ctx.log(f"Cached {len(names)} package names.")
    return names


def load(ctx: TaskContext = NULL) -> list[str]:
    """Cached names, downloading them first when the cache is missing or older than a week.

    A failed refresh falls back to the old cache when there is one.
    """
    names = cached()
    if names and not is_stale():
        return names
    try:
        return fetch(ctx)
    except Exception:
        if names:
            return names
        raise
