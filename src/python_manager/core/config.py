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
    "favorites": [],  # package names the user marked as favourite
    "use_uv": True,  # use uv for packages and environments when it is installed
    "auto_check": True,  # check environments for outdated and vulnerable packages in the background
    "auto_check_hours": 24,
    "auto_check_security": True,  # include the vulnerability lookup in scheduled checks
    "notify": True,  # desktop notification when a scheduled check finds something
    "last_health_check": 0,
    "projects": [],  # project folders added on the Projects page
    "default_python": "",  # interpreter preselected for new environments; empty: the first listed
    "envs_location": "",  # parent folder for new environments; empty: the app's envs folder
    "stale_days": 180,  # Disk Usage flags environments unchanged for longer
}

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "data": {}}  # parsed file, reused while it is unchanged


def load() -> dict[str, Any]:
    target = paths.config_file()
    try:
        stat = target.stat()
        key = (str(target), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return dict(DEFAULTS)
    if _cache["key"] != key:
        try:
            stored = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        _cache.update(key=key, data=stored)
    return {**DEFAULTS, **_cache["data"]}


def save(data: dict[str, Any]) -> None:
    with _lock:
        target = paths.config_file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(target)
        _cache["key"] = None


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def set(key: str, value: Any) -> None:  # noqa: A001 - mirrors get()
    data = load()
    data[key] = value
    save(data)
