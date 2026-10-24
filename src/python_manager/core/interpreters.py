"""Interpreter model and discovery of Python installations already on the system."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from . import paths
from .tasks import capture

MANAGED = "managed"
SYSTEM = "system"
VENV = "venv"
CONDA = "conda"

_PROBE = (
    "import json,sys,platform;"
    "print(json.dumps({'version':platform.python_version(),"
    "'impl':platform.python_implementation(),"
    "'prefix':sys.prefix,'base':getattr(sys,'base_prefix',sys.prefix),"
    "'bits':64 if sys.maxsize>2**32 else 32}))"
)


@dataclass(frozen=True)
class Interpreter:
    executable: Path
    version: str
    kind: str
    name: str
    implementation: str = "CPython"

    @property
    def label(self) -> str:
        kind = {MANAGED: "managed", SYSTEM: "system", VENV: "venv", CONDA: "conda, read-only"}.get(self.kind, self.kind)
        return f"{self.name}  —  Python {self.version} ({kind})"


def probe(executable: Path, timeout: float = 15) -> Optional[dict]:
    """Ask an interpreter about itself. Returns None if it is not a working Python."""
    try:
        proc = capture([str(executable), "-c", _PROBE], timeout=timeout)
    except Exception:  # missing file, permission error, timeout...
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def version_key(version: str) -> tuple:
    """Sortable key for versions like 3.12.1, 3.13.0rc2, 3.14.0a1."""
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?(?:(a|b|rc)(\d+))?", version)
    if not m:
        return (0,)
    major, minor, micro, stage, num = m.groups()
    stage_rank = {"a": 0, "b": 1, "rc": 2, None: 3}[stage]
    return (int(major), int(minor), int(micro or 0), stage_rank, int(num or 0))


_EXE_RE = re.compile(r"^python(3(\.\d+)?t?)?(\.exe)?$", re.IGNORECASE)


def _candidate_dirs() -> Iterable[Path]:
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            yield Path(entry)
    home = Path.home()
    if sys.platform == "win32":
        roots = [Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Programs" / "Python"]
        roots += [Path(os.environ[v]) for v in ("ProgramFiles", "ProgramFiles(x86)") if v in os.environ]
        for root in roots:
            yield from root.glob("Python3*")
    else:
        yield from (Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin"))
        yield from Path("/Library/Frameworks/Python.framework/Versions").glob("*/bin")
    yield from (home / ".pyenv" / "versions").glob("*/bin")
    yield from (home / ".pyenv" / "pyenv-win" / "versions").glob("*")


def _windows_launcher_paths() -> Iterable[Path]:
    launcher = shutil.which("py")
    if not launcher:
        return
    try:
        proc = capture([launcher, "-0p"], timeout=10)
    except Exception:
        return
    for line in proc.stdout.splitlines():
        m = re.search(r"([A-Za-z]:\\.*?python[w]?\.exe)\s*$", line.strip(), re.IGNORECASE)
        if m:
            yield Path(m.group(1))


def _candidates() -> list[Path]:
    seen: set[str] = set()
    found: list[Path] = []
    managed_root = os.path.realpath(paths.pythons_dir())

    def add(path: Path) -> None:
        if not path.is_file() or "WindowsApps" in str(path):
            return
        real = os.path.realpath(path)
        if real in seen or real.startswith(managed_root):
            return
        seen.add(real)
        found.append(path)

    for directory in _candidate_dirs():
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if _EXE_RE.match(entry.name) and (sys.platform == "win32" or os.access(entry, os.X_OK)):
                add(entry)
    if sys.platform == "win32":
        for path in _windows_launcher_paths():
            add(path)
    return found


def find_system_pythons() -> list[Interpreter]:
    """Python installations not managed by this app (virtual environments excluded)."""
    candidates = _candidates()
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(probe, candidates))
    result: dict[tuple, Interpreter] = {}
    for path, info in zip(candidates, infos):
        if not info or os.path.realpath(info["prefix"]) != os.path.realpath(info["base"]):
            continue
        # Several names (python3, python3.12) often point at the same installation.
        key = (os.path.realpath(info["prefix"]), info["version"], info["bits"])
        current = result.get(key)
        if current is None or len(path.name) < len(current.executable.name):
            result[key] = Interpreter(path, info["version"], SYSTEM, str(path), info["impl"])
    return sorted(result.values(), key=lambda i: version_key(i.version), reverse=True)
