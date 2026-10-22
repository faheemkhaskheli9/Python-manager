"""Create, discover and delete virtual environments."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, packages, paths
from .fs import remove_tree
from .interpreters import VENV, Interpreter
from .tasks import NULL, TaskContext, run

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class VirtualEnv:
    name: str
    path: Path
    version: str
    base: str
    managed: bool

    @property
    def executable(self) -> Path:
        if sys.platform == "win32":
            return self.path / "Scripts" / "python.exe"
        return self.path / "bin" / "python"

    @property
    def valid(self) -> bool:
        return self.executable.exists()

    def interpreter(self) -> Interpreter:
        return Interpreter(self.executable, self.version, VENV, self.name)


def read_pyvenv_cfg(path: Path) -> dict[str, str]:
    values = {}
    try:
        text = (path / "pyvenv.cfg").read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip().lower()] = value.strip()
    return values


def is_venv(path: Path) -> bool:
    return (path / "pyvenv.cfg").is_file()


def load(path: Path, managed: bool) -> VirtualEnv:
    cfg = read_pyvenv_cfg(path)
    version = cfg.get("version_info") or cfg.get("version") or "?"
    base = cfg.get("executable") or cfg.get("home", "")
    return VirtualEnv(path.name, path, version, base, managed)


def _registered() -> list[str]:
    return list(config.get("venvs") or [])


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def list_envs() -> list[VirtualEnv]:
    """Environments in the app's envs folder plus any the user registered from elsewhere."""
    envs = [load(p, True) for p in sorted(paths.envs_dir().iterdir()) if is_venv(p)]
    for entry in _registered():
        path = Path(entry)
        if is_venv(path) and not any(_same(path, e.path) for e in envs):
            envs.append(load(path, False))
    return envs


def register(path: Path) -> VirtualEnv:
    path = Path(path).absolute()
    if not is_venv(path):
        raise ValueError(f"{path} is not a virtual environment (pyvenv.cfg not found)")
    if path.parent != paths.envs_dir() and not any(_same(path, Path(p)) for p in _registered()):
        config.set("venvs", _registered() + [str(path)])
    return load(path, path.parent == paths.envs_dir())


def unregister(path: Path) -> None:
    config.set("venvs", [p for p in _registered() if not _same(Path(p), path)])


def create(
    name: str,
    base_python: Path,
    location: Optional[Path] = None,
    system_site_packages: bool = False,
    with_pip: bool = True,
    upgrade_deps: bool = False,
    ctx: TaskContext = NULL,
) -> VirtualEnv:
    if not NAME_RE.match(name):
        raise ValueError("Name may contain only letters, digits, '.', '_' and '-'")
    parent = Path(location) if location else paths.envs_dir()
    target = parent / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    parent.mkdir(parents=True, exist_ok=True)
    uv = packages.uv_path()
    if uv:
        # uv always seeds the latest pip, so upgrade_deps has nothing left to do.
        cmd = [uv, "venv", "--python", str(base_python), str(target)]
        if with_pip:
            cmd.append("--seed")
    else:
        cmd = [str(base_python), "-m", "venv", str(target)]
        if not with_pip:
            cmd.append("--without-pip")
        elif upgrade_deps:
            cmd.append("--upgrade-deps")
    if system_site_packages:
        cmd.append("--system-site-packages")
    try:
        run(cmd, ctx)
    except BaseException:
        if target.exists():
            remove_tree(target)
        raise
    ctx.log(f"Created virtual environment {target}")
    return register(target)


def delete(env: VirtualEnv, ctx: TaskContext = NULL) -> None:
    if not is_venv(env.path):
        raise ValueError(f"{env.path} is not a virtual environment")
    ctx.log(f"Removing {env.path}")
    remove_tree(env.path)
    unregister(env.path)


def activation_command(env: VirtualEnv) -> str:
    if sys.platform == "win32":
        return f'"{env.path / "Scripts" / "activate.bat"}"'
    return f"source {shlex.quote(str(env.path / 'bin' / 'activate'))}"


def open_terminal(env: VirtualEnv) -> None:
    """Open a terminal window with the environment activated (best effort per platform)."""
    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd.exe", "/k", str(env.path / "Scripts" / "activate.bat")],
            cwd=str(env.path),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return
    activate = shlex.quote(str(env.path / "bin" / "activate"))
    if sys.platform == "darwin":
        script = f'tell application "Terminal" to do script "source {activate}"'
        subprocess.Popen(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'])
        return
    shell_cmd = f"source {activate}; exec ${{SHELL:-bash}} -i"
    for term, args in (
        ("x-terminal-emulator", ["-e", "bash", "-c", shell_cmd]),
        ("gnome-terminal", ["--", "bash", "-c", shell_cmd]),
        ("konsole", ["-e", "bash", "-c", shell_cmd]),
        ("xfce4-terminal", ["-x", "bash", "-c", shell_cmd]),
        ("xterm", ["-e", "bash", "-c", shell_cmd]),
    ):
        exe = shutil.which(term)
        if exe:
            subprocess.Popen([exe, *args], cwd=str(env.path))
            return
    raise FileNotFoundError("No terminal emulator found. Run: " + activation_command(env))
