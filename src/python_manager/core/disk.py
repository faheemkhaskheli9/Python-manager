"""Disk space used by environments, installed Pythons and package caches, and cleaning the caches."""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, paths, python_versions, venvs
from .fs import remove_tree
from .tasks import NULL, TaskContext, capture, run

ENV = "Virtual environment"
PYTHON = "Python"
APP_CACHE = "Download cache"
PIP_CACHE = "pip cache"
UV_CACHE = "uv cache"
ARCHIVE = "Python download"
CACHES = (APP_CACHE, PIP_CACHE, UV_CACHE)
DELETABLE = (ENV, PYTHON, ARCHIVE)
INSTALLED = "installed"

# A python-build-standalone archive downloaded into the app cache.
ARCHIVE_NAME = re.compile(r"^cpython-(?P<version>[^+]+)\+\d+-.+?(?P<ft>-freethreaded)?-install_only\.tar\.gz$")

# Small files in the app cache that are cheaper to keep than to rebuild.
KEEP = {"pypi-names.txt", "health.json"}


@dataclass(frozen=True)
class Usage:
    kind: str
    name: str
    path: Path
    size: int  # bytes
    payload: object = None  # the VirtualEnv or Interpreter behind an ENV or PYTHON row
    note: str = ""  # why an environment is stale
    stale: bool = False  # broken, or unchanged for longer than the ``stale_days`` setting
    modified: float = 0.0  # when a downloaded archive was last written

    @property
    def cleanable(self) -> bool:
        return self.kind in CACHES


BROKEN = "base Python missing"


def _age(seconds: float) -> str:
    days = int(seconds // 86400)
    if days >= 365:
        return f"{days // 365} year{'s' * (days >= 730)}"
    if days >= 60:
        return f"{days // 30} months"
    return f"{days} day{'s' * (days != 1)}"


def env_status(env: venvs.VirtualEnv, now: Optional[float] = None) -> tuple[str, bool]:
    """A note for an environment and whether it is stale (broken, or unchanged for too long)."""
    if venvs.is_broken(env):
        return BROKEN, True
    changed = venvs.last_changed(env)
    if not changed:
        return "", False
    age = (now or time.time()) - changed
    stale = age >= float(config.get("stale_days") or 180) * 86400
    return (f"unchanged for {_age(age)}" if stale else ""), stale


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


def archive_key(name: str) -> Optional[str]:
    """The installation folder an archive file name installs (``cpython-3.12.4``), or None."""
    m = ARCHIVE_NAME.match(name)
    return f"cpython-{m['version']}{'t' if m['ft'] else ''}" if m else None


def archives(now: Optional[float] = None) -> list[Usage]:
    """The Python archives in the download cache; the note says whether each is installed or its age."""
    folder, now = paths.cache_dir(), now or time.time()
    try:
        installed = python_versions.installed_keys()
    except OSError:
        installed = set()
    result = []
    for entry in sorted(folder.glob("cpython-*.tar.gz")):
        key = archive_key(entry.name)
        try:
            stat = entry.stat()
        except OSError:
            continue
        if key is None or not entry.is_file():
            continue
        note = INSTALLED if key in installed else f"downloaded {_age(now - stat.st_mtime)} ago"
        result.append(Usage(ARCHIVE, entry.name, entry, stat.st_size, key, note, modified=stat.st_mtime))
    return result


def old_archives(items: list[Usage], days: float, now: Optional[float] = None) -> list[Usage]:
    """Archives whose Python is installed or that were downloaded at least ``days`` days ago."""
    limit = (now or time.time()) - days * 86400
    return [u for u in items if u.kind == ARCHIVE and (u.note == INSTALLED or u.modified <= limit)]


def delete_archive(usage: Usage, ctx: TaskContext = NULL) -> None:
    if usage.kind != ARCHIVE or usage.path.parent != paths.cache_dir():
        raise ValueError(f"{usage.name} is not a downloaded Python archive")
    ctx.log(f"Deleting {usage.path}")
    usage.path.unlink(missing_ok=True)


def scan(ctx: TaskContext = NULL) -> list[Usage]:
    """Every environment, managed Python, cache and downloaded Python archive with its size, largest first.

    The download cache's size leaves out the archives, which have rows of their own."""
    items = [(ENV, e.name, e.path, e) for e in venvs.list_envs()]
    items += [(PYTHON, i.name, paths.pythons_dir() / i.name, i) for i in python_versions.list_installed()]
    items.append((APP_CACHE, "Python Manager downloads", paths.cache_dir(), None))
    items.append((PIP_CACHE, "pip", pip_cache_dir(), None))
    uv_dir = uv_cache_dir()
    if uv_dir:
        items.append((UV_CACHE, "uv", uv_dir, None))
    result = []
    with ThreadPoolExecutor(max_workers=4) as pool:  # mostly waiting on the disk
        sizes = pool.map(lambda item: dir_size(item[2]), items)
        for done, ((kind, name, path, payload), size) in enumerate(zip(items, sizes), 1):
            ctx.check()
            ctx.progress(done, len(items))
            note, stale = env_status(payload) if kind == ENV else ("", False)
            result.append(Usage(kind, name, path, size, payload, note, stale))
    downloads = archives()
    in_archives = sum(u.size for u in downloads)
    result = [Usage(u.kind, u.name, u.path, max(0, u.size - in_archives)) if u.kind == APP_CACHE else u
              for u in result] + downloads
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
