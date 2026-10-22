"""Project folders: find their environment, compare it with the declared requirements and sync it."""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, deps, packages, projectfile, venvs
from .tasks import NULL, CommandError, TaskContext, capture, run

PYPROJECT = "pyproject.toml"
REQUIREMENTS = "requirements.txt"
UV_LOCK = "uv.lock"
PROJECT_FILES = (PYPROJECT, REQUIREMENTS, UV_LOCK)

OK = "OK"
MISSING = "Missing"
MISMATCH = "Wrong version"
UNCHECKED = "Not checked"

# Runs inside the target interpreter: the values PEP 508 markers are evaluated against.
_MARKERS = r"""
import json, os, platform, sys
v = sys.implementation.version
iver = "%d.%d.%d" % (v.major, v.minor, v.micro)
if v.releaselevel != "final":
    iver += v.releaselevel[0] + str(v.serial)
print(json.dumps({
    "implementation_name": sys.implementation.name,
    "implementation_version": iver,
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version_tuple()[:2]),
    "sys_platform": sys.platform,
}))
"""


@dataclass(frozen=True)
class Project:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def files(self) -> list[str]:
        """Which of pyproject.toml, requirements.txt and uv.lock the folder has."""
        return [f for f in PROJECT_FILES if (self.path / f).is_file()]

    def env(self) -> Optional[venvs.VirtualEnv]:
        """The project's environment: the first of .venv, venv, env that is one."""
        for name in venvs.PROJECT_ENV_NAMES:
            if venvs.is_venv(self.path / name):
                return venvs.load(self.path / name, managed=False)
        return None

    def sources(self) -> list[Path]:
        """Files the requirements can be read from, preferred first."""
        return [self.path / f for f in (REQUIREMENTS, PYPROJECT) if (self.path / f).is_file()]


@dataclass(frozen=True)
class Check:
    requirement: str  # as written in the file
    name: str
    installed: str  # installed version, empty when missing
    status: str


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def list_projects() -> list[Project]:
    return [Project(Path(p)) for p in config.get("projects") or [] if Path(p).is_dir()]


def add(path: Path) -> Project:
    path = Path(path).absolute()
    if not path.is_dir():
        raise ValueError(f"{path} is not a folder")
    stored = list(config.get("projects") or [])
    if not any(_same(path, Path(p)) for p in stored):
        config.set("projects", stored + [str(path)])
    return Project(path)


def remove(path: Path) -> None:
    config.set("projects", [p for p in config.get("projects") or [] if not _same(Path(p), path)])


def _requirements_lines(path: Path, seen: set[str]) -> list[str]:
    key = os.path.normcase(os.path.abspath(path))
    if key in seen:
        return []
    seen.add(key)
    text = re.sub(r"\\\n", "", Path(path).read_text(encoding="utf-8"))
    result = []
    for line in text.splitlines():
        line = re.sub(r"(^|\s)#.*", "", line).strip()
        if not line:
            continue
        include = re.match(r"(?:-r|--requirement)(?:\s+|=)(.+)", line)
        if include:
            result += _requirements_lines(Path(path).parent / include.group(1).strip(), seen)
        elif not line.startswith("-"):  # other options (-e, -c, --index-url …) are not requirements
            result.append(re.sub(r"\s+--\S.*$", "", line))  # per-line options such as --hash
    return result


def read_requirements(path: Path) -> list[str]:
    """Requirements listed in a requirements file (following ``-r`` includes) or a pyproject.toml."""
    path = Path(path)
    if path.name.endswith(".toml"):
        return projectfile.pyproject_dependencies(path)
    return _requirements_lines(path, set())


def marker_environment(python: Path) -> dict[str, str]:
    cmd = [str(python), "-I", "-c", _MARKERS]
    proc = capture(cmd)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def compare(requirements: list[str], python: Path) -> list[Check]:
    """Each requirement that applies to ``python`` and whether the installed version satisfies it."""
    from packaging.requirements import InvalidRequirement, Requirement

    with ThreadPoolExecutor(max_workers=2) as pool:  # two subprocesses, started together
        graph_job = pool.submit(deps.load_graph, python)
        markers = marker_environment(python)
        graph = graph_job.result()
    env = {**markers, "extra": ""}
    result = []
    for text in requirements:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            result.append(Check(text, text, "", UNCHECKED))
            continue
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        dist = graph.get(deps.normalize(req.name))
        if dist is None:
            status = MISSING
        elif req.specifier and not req.specifier.contains(dist.version, prereleases=True):
            status = MISMATCH
        else:
            status = OK
        result.append(Check(text, req.name, dist.version if dist else "", status))
    return result


def can_uv_sync(project: Project) -> bool:
    """``uv sync`` installs the lock file exactly, but only into the project's ``.venv``."""
    env = project.env()
    return bool(packages.uv_path() and UV_LOCK in project.files and env
                and _same(env.path, project.path / ".venv"))


def sync(project: Project, source: Optional[Path] = None, ctx: TaskContext = NULL) -> None:
    """Install the project's requirements into its environment.

    With uv, a uv.lock and a ``.venv`` this is ``uv sync --frozen``; otherwise the packages listed
    in ``source`` (default: the first of requirements.txt, pyproject.toml) are installed.
    """
    env = project.env()
    if env is None:
        raise FileNotFoundError(f"{project.name} has no environment; create one first")
    if source is None and can_uv_sync(project):
        run([packages.uv_path(), "sync", "--frozen"], ctx, cwd=str(project.path))
        return
    source = source or next(iter(project.sources()), None)
    if source is None:
        raise FileNotFoundError(f"{project.name} has no requirements.txt or pyproject.toml")
    projectfile.install_file(env.executable, source, ctx)


def create_env(project: Project, base_python: Path, ctx: TaskContext = NULL,
               install: bool = True) -> venvs.VirtualEnv:
    """Create ``.venv`` in the project and, when ``install``, sync it."""
    env = venvs.create_at(project.path / ".venv", base_python, ctx=ctx)
    if install and (project.sources() or can_uv_sync(project)):
        sync(project, ctx=ctx)
    return env
