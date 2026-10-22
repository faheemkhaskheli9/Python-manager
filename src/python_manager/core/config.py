"""Small JSON settings store."""

from __future__ import annotations

import json
import threading
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "release_count": 3,  # how many python-build-standalone releases to scan
    "show_prereleases": False,
    "show_freethreaded": False,
    "venvs": [],  # externally located environments registered by the user
}

_lock = threading.Lock()


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(paths.config_file().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save(data: dict[str, Any]) -> None:
    with _lock:
        target = paths.config_file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(target)


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value: Any) -> None:  # noqa: A001 - mirrors get()
    data = load()
    data[key] = value
    save(data)
