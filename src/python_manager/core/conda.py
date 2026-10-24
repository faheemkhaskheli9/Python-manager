"""Read-only discovery of conda, mamba and micromamba environments."""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .interpreters import CONDA, Interpreter

# conda-meta/python-3.12.4-h99e199e_0_cpython.json; "python-dateutil-…" does not match.
_PYTHON_META = re.compile(r"^python-(\d+\.\d+(?:\.\d+)?[a-z0-9]*)-.*\.json$")
_ROOT_NAMES = ("miniconda3", "anaconda3", "miniforge3", "mambaforge", "micromamba", "miniconda", "anaconda")


@dataclass(frozen=True)
class CondaEnv:
    name: str
    path: Path
    version: str  # Python version; empty when the environment has no Python

    @property
    def executable(self) -> Path:
        if sys.platform == "win32":
            return self.path / "python.exe"
        return self.path / "bin" / "python"

    @property
    def valid(self) -> bool:
        return bool(self.version) and self.executable.exists()

    def interpreter(self) -> Interpreter:
        return Interpreter(self.executable, self.version, CONDA, self.name)


def is_conda_env(path: Path) -> bool:
    return (path / "conda-meta").is_dir()


def python_version(path: Path) -> str:
    """Python version recorded in conda-meta, without starting the interpreter."""
    try:
        names = os.listdir(path / "conda-meta")
    except OSError:
        return ""
    for name in names:
        m = _PYTHON_META.match(name)
        if m:
            return m.group(1)
    return ""


def _env_name(path: Path) -> str:
    if path.parent.name == "envs" and is_conda_env(path.parent.parent):
        return path.name
    if (path / "envs").is_dir():
        return f"base ({path.name})"
    return path.name


def _roots() -> Iterable[Path]:
    home = Path.home()
    for var in ("CONDA_ROOT", "MAMBA_ROOT_PREFIX"):
        if os.environ.get(var):
            yield Path(os.environ[var])
    if os.environ.get("CONDA_EXE"):  # <root>/bin/conda or <root>\Scripts\conda.exe
        yield Path(os.environ["CONDA_EXE"]).parent.parent
    parents = [home]
    if sys.platform == "win32":
        parents += [Path(os.environ[v]) for v in ("LOCALAPPDATA", "ProgramData") if v in os.environ]
    else:
        parents += [Path("/opt"), Path("/usr/local")]
    for parent in parents:
        for name in _ROOT_NAMES:
            yield parent / name
    yield home / ".conda"  # environments created with `conda create -n` when the root is read-only


def _listed() -> Iterable[Path]:
    """Environments conda recorded in ~/.conda/environments.txt (includes ones created with -p)."""
    try:
        text = (Path.home() / ".conda" / "environments.txt").read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            yield Path(line.strip())


def _candidates() -> Iterable[Path]:
    yield from _listed()
    if os.environ.get("CONDA_PREFIX"):
        yield Path(os.environ["CONDA_PREFIX"])
    for root in _roots():
        yield root
        try:
            yield from sorted((root / "envs").iterdir())
        except OSError:
            pass


def list_envs() -> list[CondaEnv]:
    seen: set[str] = set()
    envs = []
    for path in _candidates():
        try:
            if not is_conda_env(path):
                continue
        except OSError:
            continue
        key = os.path.normcase(os.path.realpath(path))
        if key in seen:
            continue
        seen.add(key)
        envs.append(CondaEnv(_env_name(path), path, python_version(path)))
    return envs


def activation_command(env: CondaEnv) -> str:
    target = env.name if env.path.parent.name == "envs" else str(env.path)
    if sys.platform == "win32":
        return f'conda activate "{target}"' if " " in target else f"conda activate {target}"
    return f"conda activate {shlex.quote(target)}"
