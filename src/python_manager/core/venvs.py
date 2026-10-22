"""Create, discover and delete virtual environments."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, packages, paths, projectfile
from .fs import remove_tree
from .interpreters import VENV, Interpreter
from .tasks import NULL, TaskContext, run

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Conventional folder names of an environment inside a project; shown as "<project>/<folder>".
PROJECT_ENV_NAMES = (".venv", "venv", "env")


@dataclass(frozen=True)
class VirtualEnv:
    name: str
    path: Path
    version: str
    base: str
    managed: bool

    @property
    def executable(self) -> Path:
        return _executable(self.path)

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
    name = path.name
    if not managed and name in PROJECT_ENV_NAMES:
        name = f"{path.parent.name}/{name}"
    return VirtualEnv(name, path, version, base, managed)


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
    packages_file: Optional[Path] = None,
) -> VirtualEnv:
    """Create an environment; ``packages_file`` (requirements.txt or pyproject.toml) is installed into it."""
    if not NAME_RE.match(name):
        raise ValueError("Name may contain only letters, digits, '.', '_' and '-'")
    parent = Path(location) if location else paths.envs_dir()
    return create_at(parent / name, base_python, system_site_packages, with_pip, upgrade_deps, ctx, packages_file)


def create_at(
    target: Path,
    base_python: Path,
    system_site_packages: bool = False,
    with_pip: bool = True,
    upgrade_deps: bool = False,
    ctx: TaskContext = NULL,
    packages_file: Optional[Path] = None,
) -> VirtualEnv:
    """Create an environment in the folder ``target`` (any name, e.g. a project's ``.venv``)."""
    target = Path(target)
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    uv = packages.uv_path()
    if packages_file and not uv:
        with_pip = True  # pip installs the listed packages
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
        if packages_file:
            ctx.log(f"Installing packages from {Path(packages_file).name}")
            projectfile.install_file(_executable(target), packages_file, ctx)
    except BaseException:
        if target.exists():
            remove_tree(target)
        raise
    ctx.log(f"Created virtual environment {target}")
    return register(target)


def _executable(path: Path) -> Path:
    if sys.platform == "win32":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def base_executable(env: VirtualEnv) -> Optional[Path]:
    """The interpreter the environment was created from, if it still exists."""
    cfg = read_pyvenv_cfg(env.path)
    exe = cfg.get("executable")
    if exe and Path(exe).is_file():
        return Path(exe)
    home = cfg.get("home")
    if not home:
        return None
    if sys.platform == "win32":
        names = ["python.exe"]
    else:
        short = ".".join(env.version.split(".")[:2])
        names = [f"python{short}", "python3", "python"]
    return next((Path(home) / n for n in names if (Path(home) / n).is_file()), None)


def clone(
    source: VirtualEnv,
    name: str,
    base_python: Optional[Path] = None,
    location: Optional[Path] = None,
    ctx: TaskContext = NULL,
    **options,
) -> VirtualEnv:
    """New environment with the same packages as ``source``; same base Python unless one is given."""
    base = base_python or base_executable(source)
    if base is None:
        raise ValueError(f"The Python that {source.name} was created from no longer exists; choose another")
    ctx.log(f"Reading packages of {source.name}")
    requirements = projectfile.clone_requirements(source.executable)
    if not requirements:
        return create(name, base, location, ctx=ctx, **options)
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "requirements.txt"
        file.write_text(requirements, encoding="utf-8")
        return create(name, base, location, ctx=ctx, packages_file=file, **options)


def export(env: VirtualEnv, path: Path) -> None:
    """Write the environment's packages to requirements.txt (pinned) or pyproject.toml (top-level)."""
    path = Path(path)
    if path.name.endswith(".toml"):
        text = projectfile.pyproject_for(env.executable, env.name, env.version)
    else:
        text = packages.freeze(env.executable)
    path.write_text(text, encoding="utf-8")


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
