"""Jupyter kernels: list the installed kernel specs and register or remove an environment's kernel."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from . import packages
from .fs import remove_tree
from .tasks import NULL, TaskContext, capture, run

IPYKERNEL = "ipykernel"
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class Kernel:
    name: str  # folder name, what Jupyter calls the kernel
    display_name: str
    language: str
    path: Path  # the kernel spec folder (with kernel.json)
    executable: Optional[Path]  # argv[0] when it is a path to an interpreter

    @property
    def broken(self) -> bool:
        """Its interpreter is gone, e.g. the environment was deleted."""
        return self.executable is not None and self.executable.is_absolute() and not self.executable.exists()

    @property
    def user(self) -> bool:
        """Installed in the user's own Jupyter folder (removable without admin rights)."""
        return _same(self.path.parent.parent, user_data_dir())


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def user_data_dir() -> Path:
    """Jupyter's per-user data folder, where ``ipykernel install --user`` writes."""
    if os.environ.get("JUPYTER_DATA_DIR"):
        return Path(os.environ["JUPYTER_DATA_DIR"])
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "jupyter"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Jupyter"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "jupyter"


def data_dirs() -> list[Path]:
    """Jupyter data folders in search order: ``JUPYTER_PATH``, user, system.

    Kernels inside an environment (``<env>/share/jupyter``) are left out: only a Jupyter running
    from that environment sees them, and ipykernel puts a generic ``python3`` there.
    """
    result = [Path(p) for p in os.environ.get("JUPYTER_PATH", "").split(os.pathsep) if p]
    result.append(user_data_dir())
    if sys.platform == "win32":
        if os.environ.get("PROGRAMDATA"):
            result.append(Path(os.environ["PROGRAMDATA"]) / "jupyter")
    else:
        result += [Path("/usr/local/share/jupyter"), Path("/usr/share/jupyter")]
    return result


def read_spec(folder: Path) -> Optional[Kernel]:
    try:
        spec = json.loads((folder / "kernel.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(spec, dict) or not isinstance(spec.get("argv"), list):
        return None
    argv = spec["argv"]
    first = argv[0] if argv and isinstance(argv[0], str) else ""
    executable = Path(first) if first and (os.sep in first or "/" in first) else None
    display_name = spec.get("display_name")
    language = spec.get("language")
    return Kernel(folder.name, display_name if isinstance(display_name, str) and display_name else folder.name,
                  language if isinstance(language, str) else "", folder, executable)


def list_kernels() -> list[Kernel]:
    """Every kernel spec Jupyter would find; a name found twice keeps the first, as Jupyter does."""
    seen: set[str] = set()
    result = []
    for data in data_dirs():
        try:
            folders = sorted((data / "kernels").iterdir())
        except OSError:
            continue
        for folder in folders:
            kernel = read_spec(folder) if folder.is_dir() else None
            if kernel and kernel.name.lower() not in seen:
                seen.add(kernel.name.lower())
                result.append(kernel)
    return result


def kernels_for(python: Path, kernels: Iterable[Kernel]) -> list[Kernel]:
    """Kernels that run ``python`` (or another interpreter in the same environment folder)."""
    folder = Path(python).parent
    return [k for k in kernels if k.executable is not None and k.executable.is_absolute()
            and (_same(k.executable, python) or _same(k.executable.parent, folder))]


def kernel_name(name: str, taken: Iterable[str] = ()) -> str:
    """A valid kernel name (letters, digits, ``.``, ``_``, ``-``) from an environment name.

    A number is added when the name is ``taken``: installing over a kernel replaces it.
    """
    base = _NAME_RE.sub("-", name).strip("-.").lower() or "python"
    taken = {t.lower() for t in taken}
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def has_ipykernel(python: Path) -> bool:
    proc = capture([str(python), "-c", "import importlib.util,sys;"
                    "sys.exit(importlib.util.find_spec('ipykernel') is None)"])
    return proc.returncode == 0


def register(python: Path, name: str, display_name: str, ctx: TaskContext = NULL) -> Kernel:
    """Install ipykernel when missing, then add a user kernel that runs ``python``."""
    if not has_ipykernel(python):
        ctx.log(f"Installing {IPYKERNEL}…")
        packages.install(python, [IPYKERNEL], ctx)
    run([str(python), "-m", IPYKERNEL, "install", "--user", "--name", name, "--display-name", display_name],
        ctx)
    kernel = read_spec(user_data_dir() / "kernels" / name)
    if kernel is None:
        raise FileNotFoundError(f"ipykernel did not create the kernel {name}")
    return kernel


def retarget(kernel: Kernel, python: Path) -> Kernel:
    """Point ``kernel`` at another interpreter (its first argument); the rest of the spec is kept."""
    file = kernel.path / "kernel.json"
    spec = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("argv"), list) or not spec["argv"]:
        raise ValueError(f"{file} has no argv")
    spec["argv"][0] = str(python)
    file.write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    return read_spec(kernel.path) or kernel


def remove(kernel: Kernel, ctx: TaskContext = NULL) -> None:
    ctx.log(f"Removing kernel {kernel.name} ({kernel.path})")
    remove_tree(kernel.path)
