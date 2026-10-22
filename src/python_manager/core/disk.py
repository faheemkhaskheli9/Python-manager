"""Disk space used by environments, installed Pythons and package caches, and cleaning the caches."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths, python_versions, venvs
from .fs import remove_tree
from .tasks import NULL, TaskContext, capture, run

ENV = "Virtual environment"
PYTHON = "Python"
APP_CACHE = "Download cache"
PIP_CACHE = "pip cache"
UV_CACHE = "uv cache"
CACHES = (APP_CACHE, PIP_CACHE, UV_CACHE)

# Small files in the app cache that are cheaper to keep than to rebuild.
KEEP = {"pypi-names.txt", "health.json"}


@dataclass(frozen=True)
class Usage:
    kind: str
    name: str
    path: Path
    size: int  # bytes
    payload: object = None  # the VirtualEnv or Interpreter behind an ENV or PYTHON row

    @property
    def cleanable(self) -> bool:
        return self.kind in CACHES


def dir_size(path: Path) -> int:
    """Total size of the files under ``path`` without following symlinks; 0 when missing."""
    total, stack = 0, [str(path)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"  # unreachable


def _user_cache_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def pip_cache_dir() -> Path:
    """pip's cache folder (``PIP_CACHE_DIR`` or the platform default)."""
    override = os.environ.get("PIP_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return _user_cache_root() / "pip" / "Cache"
    return _user_cache_root() / "pip"


def uv_cache_dir() -> Optional[Path]:
    """uv's cache folder, asked from uv itself when it is installed; None when uv was never used."""
    uv = shutil.which("uv")
    if uv:
        try:
            proc = capture([uv, "cache", "dir"])
            if proc.returncode == 0 and proc.stdout.strip():
                return Path(proc.stdout.strip().splitlines()[-1])
        except Exception:
            pass
    override = os.environ.get("UV_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        default = _user_cache_root() / "uv" / "cache"
    else:
        default = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "uv"
    return default if uv or default.exists() else None


def scan(ctx: TaskContext = NULL) -> list[Usage]:
    """Every environment, managed Python and cache with its size, largest first."""
    items = [(ENV, e.name, e.path, e) for e in venvs.list_envs()]
    items += [(PYTHON, i.name, paths.pythons_dir() / i.name, i) for i in python_versions.list_installed()]
    items.append((APP_CACHE, "Python Manager downloads", paths.cache_dir(), None))
    items.append((PIP_CACHE, "pip", pip_cache_dir(), None))
    uv_dir = uv_cache_dir()
    if uv_dir:
        items.append((UV_CACHE, "uv", uv_dir, None))
    result = []
    for done, (kind, name, path, payload) in enumerate(items):
        ctx.check()
        ctx.progress(done, len(items))
        result.append(Usage(kind, name, path, dir_size(path), payload))
    return sorted(result, key=lambda u: u.size, reverse=True)


def clean(usage: Usage, ctx: TaskContext = NULL) -> None:
    """Empty a cache. uv's cache is cleaned with uv so it stays consistent."""
    if not usage.cleanable:
        raise ValueError(f"{usage.name} is not a cache")
    uv = shutil.which("uv")
    if usage.kind == UV_CACHE and uv:
        run([uv, "cache", "clean"], ctx)
        return
    if not usage.path.is_dir():
        return
    ctx.log(f"Emptying {usage.path}")
    for entry in usage.path.iterdir():
        ctx.check()
        if usage.kind == APP_CACHE and entry.name in KEEP:
            continue
        if entry.is_dir() and not entry.is_symlink():
            remove_tree(entry)
        else:
            entry.unlink()
