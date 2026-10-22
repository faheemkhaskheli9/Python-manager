"""Locations used by the application for its data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PythonManager"


def data_dir() -> Path:
    """Root folder for everything the app stores. Override with PYTHON_MANAGER_HOME."""
    override = os.environ.get("PYTHON_MANAGER_HOME")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "python-manager"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sub(name: str) -> Path:
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def pythons_dir() -> Path:
    return _sub("pythons")


def envs_dir() -> Path:
    return _sub("envs")


def cache_dir() -> Path:
    return _sub("cache")


def config_file() -> Path:
    return data_dir() / "config.json"
