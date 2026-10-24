"""Command-line tools installed in their own environments with ``uv tool`` or pipx."""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from . import packages
from .venvs import read_pyvenv_cfg
from .tasks import NULL, CommandError, TaskContext, capture, run

UV = "uv"
PIPX = "pipx"

# "httpie v3.2.4 (/home/me/.local/share/uv/tools/httpie)" followed by "- http (/home/me/.local/bin/http)"
_UV_TOOL = re.compile(r"^(?P<name>\S+) v(?P<version>\S+)(?P<rest>.*)$")
_PATH = re.compile(r"\(([^()]*)\)\s*$")


@dataclass(frozen=True)
class Tool:
    name: str
    version: str
    manager: str  # UV or PIPX
    commands: tuple[str, ...]
    path: Optional[Path]  # the tool's environment
    python: str = ""
    env: str = ""  # name the manager knows the tool by (pipx: may carry a suffix); defaults to name

    @property
    def key(self) -> str:
        return self.env or self.name


def executable(manager: str) -> Optional[str]:
    """The uv or pipx command when it is installed (regardless of the "use uv" setting)."""
    return shutil.which(manager)


def managers() -> list[str]:
    return [m for m in (UV, PIPX) if executable(m)]


def _python_version(env: Optional[Path]) -> str:
    if env is None:
        return ""
    cfg = read_pyvenv_cfg(env)
    return cfg.get("version_info") or cfg.get("version") or ""


def parse_uv_list(text: str) -> list[Tool]:
    """Parse ``uv tool list --show-paths``; also accepts the output without paths."""
    tools: list[Tool] = []
    current: Optional[dict] = None

    def flush() -> None:
        if current:
            tools.append(Tool(current["name"], current["version"], UV, tuple(current["commands"]),
                              current["path"], _python_version(current["path"])))

    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("- "):
            if current is not None:
                current["commands"].append(_PATH.sub("", line[2:]).strip())
            continue
        m = _UV_TOOL.match(line)
        if not m:
            continue  # warnings and notes
        flush()
        path = _PATH.search(m.group("rest"))
        current = {"name": m.group("name"), "version": m.group("version"), "commands": [],
                   "path": Path(path.group(1)) if path else None}
    flush()
    return tools


def _metadata_path(value) -> Optional[Path]:
    if isinstance(value, dict) and "__Path__" in value:
        return Path(value["__Path__"])
    return Path(value) if isinstance(value, str) and value else None


def parse_pipx_list(data: dict, venvs_dir: Optional[Path] = None) -> list[Tool]:
    """Parse ``pipx list --json``."""
    tools = []
    for env_name, entry in (data.get("venvs") or {}).items():
        meta = entry.get("metadata") or {}
        main = meta.get("main_package") or {}
        path = venvs_dir / env_name if venvs_dir else None
        if path is None:
            apps = [_metadata_path(p) for p in main.get("app_paths") or []]
            app = next((p for p in apps if p), None)
            path = app.parent.parent if app else None
        python = (meta.get("python_version") or "").replace("Python", "").strip()
        tools.append(Tool(main.get("package") or env_name, main.get("package_version") or "?", PIPX,
                          tuple(main.get("apps") or []), path, python, env_name))
    return tools


def _uv_tools(uv: str) -> list[Tool]:
    cmd = [uv, "tool", "list", "--show-paths"]
    proc = capture(cmd, timeout=60)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr or proc.stdout)
    return parse_uv_list(proc.stdout)


def _pipx_tools(pipx: str) -> list[Tool]:
    cmd = [pipx, "list", "--json"]
    proc = capture(cmd, timeout=60)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr or proc.stdout)
    venvs_dir = None
    env = capture([pipx, "environment", "--value", "PIPX_LOCAL_VENVS"], timeout=30)
    if env.returncode == 0 and env.stdout.strip():
        venvs_dir = Path(env.stdout.strip().splitlines()[-1])
    return parse_pipx_list(json.loads(proc.stdout or "{}"), venvs_dir)


def list_tools() -> list[Tool]:
    """Tools of every installed manager, sorted by name."""
    jobs = [(f, exe) for f, exe in ((_uv_tools, executable(UV)), (_pipx_tools, executable(PIPX))) if exe]
    with ThreadPoolExecutor(max_workers=2) as pool:
        found = [tool for tools in pool.map(lambda job: job[0](job[1]), jobs) for tool in tools]
    return sorted(found, key=lambda t: (t.name.lower(), t.manager))


def latest_versions(tools: Iterable[Tool]) -> dict[str, str]:
    """Latest PyPI version of each tool name; tools not on PyPI are left out."""
    names = sorted({t.name for t in tools})

    def lookup(name: str) -> Optional[str]:
        try:
            return packages.project_info(name).latest
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return {n: v for n, v in zip(names, pool.map(lookup, names)) if v}


def _require(manager: str) -> str:
    exe = executable(manager)
    if not exe:
        raise FileNotFoundError(f"{manager} is not installed")
    return exe


def install(manager: str, spec: str, python: Optional[Path] = None, ctx: TaskContext = NULL) -> None:
    exe = _require(manager)
    cmd = [exe, "tool", "install", spec] if manager == UV else [exe, "install", spec]
    if python:
        cmd += ["--python", str(python)]
    run(cmd, ctx)


def upgrade(tool: Tool, ctx: TaskContext = NULL) -> None:
    exe = _require(tool.manager)
    run([exe, "tool", "upgrade", tool.key] if tool.manager == UV else [exe, "upgrade", tool.key], ctx)


def upgrade_all(manager: str, ctx: TaskContext = NULL) -> None:
    exe = _require(manager)
    run([exe, "tool", "upgrade", "--all"] if manager == UV else [exe, "upgrade-all"], ctx)


def uninstall(tool: Tool, ctx: TaskContext = NULL) -> None:
    exe = _require(tool.manager)
    run([exe, "tool", "uninstall", tool.key] if tool.manager == UV else [exe, "uninstall", tool.key], ctx)
