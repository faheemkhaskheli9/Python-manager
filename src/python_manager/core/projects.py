"""Project folders: find their environment, compare it with the declared requirements and sync it."""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config, deps, packages, projectfile, python_versions, venvs
from .tasks import NULL, CommandError, TaskContext, capture, run

PYPROJECT = "pyproject.toml"
REQUIREMENTS = "requirements.txt"
UV_LOCK = "uv.lock"
PYTHON_VERSION = ".python-version"  # read by uv and pyenv
PROJECT_FILES = (PYPROJECT, REQUIREMENTS, UV_LOCK)

OK = "OK"
MISSING = "Missing"
MISMATCH = "Wrong version"
UNCHECKED = "Not checked"
UNLISTED = "Not listed"  # installed on purpose (nothing requires it) but not in the requirements

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

    def sources(self) -> list["Source"]:
        """Where the requirements can be read from, preferred first: requirements files, then
        pyproject.toml on its own, with each extra and dependency group, and with all of them."""
        files = sorted(self.path.glob("requirements*.txt"), key=lambda p: (p.name != REQUIREMENTS, p.name))
        result = [Source(f) for f in files if f.is_file()]
        pyproject = self.path / PYPROJECT
        if pyproject.is_file():
            result.append(Source(pyproject))
            try:
                extras, groups = projectfile.pyproject_options(pyproject)
            except (OSError, ValueError):  # unreadable or invalid TOML: the base entry reports it
                extras, groups = [], []
            result += [Source(pyproject, extras=(e,)) for e in extras]
            result += [Source(pyproject, groups=(g,)) for g in groups]
            if len(extras) + len(groups) > 1:
                result.append(Source(pyproject, tuple(extras), tuple(groups)))
        return result

    def watched_paths(self) -> list[Path]:
        """Files and folders whose changes can change the comparison."""
        result = [self.path] + [s.path for s in self.sources()]
        for name in (UV_LOCK, PYTHON_VERSION):
            if (self.path / name).is_file():
                result.append(self.path / name)
        env = self.env()
        if env:
            result += venvs.site_packages(env)
        return list(dict.fromkeys(result))


@dataclass(frozen=True)
class Source:
    """A requirements file, or a pyproject.toml with some of its extras and dependency groups."""

    path: Path
    extras: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        if len(self.extras) + len(self.groups) > 1:
            return f"{self.path.name} (all extras and groups)"
        if self.extras:
            return f"{self.path.name} [{self.extras[0]}]"
        if self.groups:
            return f"{self.path.name} (group {self.groups[0]})"
        return self.path.name


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


def read_requirements(source: Path | Source) -> list[str]:
    """Requirements listed in a requirements file (following ``-r`` includes), a pyproject.toml or a pylock.toml."""
    if not isinstance(source, Source):
        source = Source(Path(source))
    if projectfile.is_pylock(source.path):
        return projectfile.pylock_requirements(source.path)
    if source.path.name.endswith(".toml"):
        return projectfile.pyproject_requirements(source.path, source.extras, source.groups)
    return _requirements_lines(source.path, set())


def python_pin(project: Project) -> str:
    """The version in ``.python-version`` (its first entry), or empty."""
    try:
        text = (project.path / PYTHON_VERSION).read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            return line
    return ""


def set_python_pin(project: Project, version: str) -> None:
    """Write ``.python-version``; an empty version removes the file."""
    target = project.path / PYTHON_VERSION
    if version.strip():
        target.write_text(version.strip() + "\n", encoding="utf-8")
    elif target.is_file():
        target.unlink()


def requires_python(project: Project) -> str:
    """``requires-python`` from pyproject.toml, or empty."""
    pyproject = project.path / PYPROJECT
    if not pyproject.is_file():
        return ""
    try:
        return str(projectfile.read_pyproject(pyproject).get("project", {}).get("requires-python") or "").strip()
    except (OSError, ValueError):
        return ""


def _numbers(version: str) -> tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)*", version)
    return tuple(int(n) for n in match.group().split(".")) if match else ()


def pin_matches(pin: str, version: str) -> bool:
    """Whether Python ``version`` is what a ``.python-version`` entry asks for.

    ``3.12`` matches every 3.12.x; ``cpython-3.12``, ``cpython@3.12`` and ``3.13t`` are understood.
    Entries without a version (``system``) match anything.
    """
    wanted, actual = _numbers(pin), _numbers(version)
    return not wanted or actual[:len(wanted)] == wanted


def satisfies(requires: str, version: str) -> bool:
    """Whether ``version`` is allowed by a ``requires-python`` specifier (True when it is invalid)."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    numbers = ".".join(map(str, _numbers(version)))
    try:
        return not requires or not numbers or SpecifierSet(requires).contains(numbers, prereleases=True)
    except InvalidSpecifier:
        return True


def python_problems(project: Project, version: str) -> list[str]:
    """Why an environment on Python ``version`` does not fit the project's Python requirements."""
    result = []
    pin, requires = python_pin(project), requires_python(project)
    if pin and not pin_matches(pin, version):
        result.append(f"{PYTHON_VERSION} asks for {pin}")
    if requires and not satisfies(requires, version):
        result.append(f"requires-python is {requires}")
    return result


def preferred_python(project: Project, versions: list[str], default: int = 0) -> int:
    """Index in ``versions`` of the Python to create the project's environment with.

    ``default`` when it fits both ``.python-version`` and ``requires-python`` (or none fits),
    otherwise the newest that does.
    """
    pin, requires = python_pin(project), requires_python(project)
    fits = [i for i, v in enumerate(versions) if pin_matches(pin, v) and satisfies(requires, v)]
    if not fits or default in fits:
        return default
    return max(fits, key=lambda i: _numbers(versions[i]))


def fits(project: Project, version: str) -> bool:
    """Whether Python ``version`` fits both ``.python-version`` and ``requires-python``."""
    return pin_matches(python_pin(project), version) and satisfies(requires_python(project), version)


def matching_download(project: Project,
                      available: list[python_versions.RemotePython]) -> Optional[python_versions.RemotePython]:
    """The newest downloadable Python that fits the project, or None.

    A pin ending in ``t`` (``3.13t``) asks for a free-threaded build; pre-releases are picked only
    when no final release fits.
    """
    freethreaded = python_pin(project).lower().endswith("t")
    candidates = [r for r in available if r.freethreaded == freethreaded and fits(project, r.version)]
    final = [r for r in candidates if not r.prerelease]
    return max(final or candidates, key=lambda r: _numbers(r.version), default=None)


def install_python_and_env(project: Project, remote: python_versions.RemotePython, ctx: TaskContext = NULL,
                           install: bool = True) -> venvs.VirtualEnv:
    """Install ``remote`` (unless it already is) and create the project's environment on it."""
    if remote.key in python_versions.installed_keys():
        exe = python_versions.find_executable(python_versions.install_dir(remote))
        if exe is None:
            raise FileNotFoundError(f"{python_versions.install_dir(remote)} contains no Python executable")
    else:
        exe = python_versions.install(remote, ctx).executable
    ctx.check()
    return create_env(project, exe, ctx, install)


def marker_environment(python: Path) -> dict[str, str]:
    cmd = [str(python), "-I", "-c", _MARKERS]
    proc = capture(cmd)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def compare(requirements: list[str], python: Path, unlisted: bool = False) -> list[Check]:
    """Each requirement that applies to ``python`` and whether the installed version satisfies it.

    With ``unlisted``, installed packages that nothing requires and the requirements do not name
    are added at the end as UNLISTED (packaging tools aside).
    """
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
    if unlisted:
        named = {deps.normalize(c.name) for c in result}
        for dist in projectfile.top_level(graph):
            if deps.normalize(dist.name) not in named:
                result.append(Check(dist.name, dist.name, dist.version, UNLISTED))
    return result


NEEDS_INSTALL = (MISSING, MISMATCH, UNCHECKED)


def install_source(python: Path, source: Path | Source, only: Optional[list[str]] = None,
                   ctx: TaskContext = NULL) -> None:
    """Install the packages ``source`` lists, or just the requirements in ``only`` (from ``read_requirements``).

    A whole requirements file goes to pip as ``-r`` so its options (indexes, hashes) still apply.
    """
    if not isinstance(source, Source):
        source = Source(Path(source))
    if only is None and not source.path.name.endswith(".toml"):
        packages.install_requirements(python, source.path, ctx)
        return
    specs = read_requirements(source) if only is None else only
    if specs:
        packages.install(python, specs, ctx)
    else:
        ctx.log(f"Nothing to install from {source.label}.")


def held_back(upgrades: list[packages.Upgrade], requirements: list[str]) -> dict[str, str]:
    """Upgrades the project's requirements exclude: package name -> the requirement that pins it."""
    from packaging.requirements import InvalidRequirement, Requirement

    pins: dict[str, list[Requirement]] = {}
    for text in requirements:
        try:
            req = Requirement(text)
        except InvalidRequirement:
            continue
        if req.specifier:
            pins.setdefault(deps.normalize(req.name), []).append(req)
    result = {}
    for upgrade in upgrades:
        for req in pins.get(deps.normalize(upgrade.name), []):
            if not req.specifier.contains(upgrade.latest, prereleases=True):
                result[upgrade.name] = str(req)
                break
    return result


def can_uv_sync(project: Project) -> bool:
    """``uv sync`` installs the lock file exactly, but only into the project's ``.venv``."""
    env = project.env()
    return bool(packages.uv_path() and UV_LOCK in project.files and env
                and _same(env.path, project.path / ".venv"))


def sync(project: Project, source: Optional[Path | Source] = None, ctx: TaskContext = NULL) -> None:
    """Install the project's requirements into its environment.

    With uv, a uv.lock and a ``.venv`` this is ``uv sync --frozen``; otherwise the packages listed
    in ``source`` (default: the first of the project's sources) are installed.
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
    if isinstance(source, Source) and source.path.name.endswith(".toml"):
        specs = read_requirements(source)
        if specs:
            packages.install(env.executable, specs, ctx)
        else:
            ctx.log(f"{source.label} lists no dependencies.")
        return
    projectfile.install_file(env.executable, source.path if isinstance(source, Source) else source, ctx)


def create_env(project: Project, base_python: Path, ctx: TaskContext = NULL,
               install: bool = True) -> venvs.VirtualEnv:
    """Create ``.venv`` in the project and, when ``install``, sync it."""
    env = venvs.create_at(project.path / ".venv", base_python, ctx=ctx)
    if install and (project.sources() or can_uv_sync(project)):
        sync(project, ctx=ctx)
    return env
