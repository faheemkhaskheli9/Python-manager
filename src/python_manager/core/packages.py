"""Package management through the target interpreter's pip, plus PyPI lookups."""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import config, net
from .tasks import NULL, CommandError, TaskContext, capture, run

PYPI_JSON = "https://pypi.org/pypi/{name}/json"


class PipMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    latest: Optional[str] = None


@dataclass(frozen=True)
class Upgrade:
    name: str
    current: str  # empty for a package the upgrade newly installed
    latest: str

    @property
    def major(self) -> bool:
        """The release number that signals breaking changes moves: the first one, or the second for 0.x."""
        try:
            from packaging.version import Version

            old, new = Version(self.current).release, Version(self.latest).release
        except Exception:
            old, new = tuple(self.current.split(".")), tuple(self.latest.split("."))
        if not old or not new:
            return False
        if old[0] != new[0]:
            return True
        return str(old[0]) == "0" and old[1:2] != new[1:2]


@dataclass(frozen=True)
class UpgradeResult:
    changed: list[Upgrade]  # what the resolver actually changed, new dependencies included
    conflicts: list[str]  # broken requirements reported by ``pip check`` afterwards
    installed: list[Package]


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    summary: str
    latest: str
    versions: list[str] = field(default_factory=list)  # newest first
    requires_python: str = ""
    home_page: str = ""


def uv_path() -> Optional[str]:
    """The uv executable when it is installed and enabled in settings, else None."""
    if not config.get("use_uv"):
        return None
    return shutil.which("uv")


def backend() -> str:
    return "uv" if uv_path() else "pip"


def _pip(python: Path) -> list[str]:
    return [str(python), "-m", "pip"]


def _cmd(python: Path, command: str, *args: str) -> list[str]:
    """A pip-style command for ``python``, run through uv when available."""
    uv = uv_path()
    if uv:
        return [uv, "pip", command, "--python", str(python), *args]
    return [*_pip(python), command, *args]


def _pip_json(python: Path, command: str, *args: str) -> list[dict]:
    cmd = _cmd(python, command, *args, "--format=json")
    proc = capture(cmd, timeout=300)
    if proc.returncode != 0:
        if "No module named pip" in proc.stderr:
            raise PipMissing(f"pip is not installed for {python}")
        raise CommandError(cmd, proc.returncode, proc.stderr or proc.stdout)
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("["):
            return json.loads(line)
    return []


def list_packages(python: Path) -> list[Package]:
    items = _pip_json(python, "list")
    return sorted((Package(i["name"], i["version"]) for i in items), key=lambda p: p.name.lower())


def from_dists(dists: Iterable) -> list[Package]:
    """Packages from installed metadata (objects with ``name`` and ``version``), sorted by name."""
    return sorted((Package(d.name, d.version) for d in dists), key=lambda p: p.name.lower())


def installed(python: Path) -> list[Package]:
    """Installed packages read from metadata: much faster than ``pip list`` and works without pip."""
    from .deps import load_graph

    try:
        return from_dists(load_graph(python).values())
    except Exception:  # e.g. Python < 3.8 has no importlib.metadata
        return list_packages(python)


def upgrades(python: Path) -> list[Upgrade]:
    """Packages with a newer version on the index, sorted by name."""
    items = _pip_json(python, "list", "--outdated")
    return sorted((Upgrade(i["name"], i["version"], i["latest_version"]) for i in items),
                  key=lambda u: u.name.lower())


def outdated(python: Path) -> dict[str, str]:
    """Map of package name -> newest version available, for packages with updates."""
    return {u.name: u.latest for u in upgrades(python)}


def has_pip(python: Path) -> bool:
    try:
        return capture([*_pip(python), "--version"]).returncode == 0
    except Exception:
        return False


def ensure_pip(python: Path, ctx: TaskContext = NULL) -> None:
    run([str(python), "-m", "ensurepip", "--upgrade"], ctx)


def install(
    python: Path,
    specs: Iterable[str],
    ctx: TaskContext = NULL,
    upgrade: bool = False,
    extra_args: Iterable[str] = (),
) -> None:
    specs = [s for s in specs if s.strip()]
    if not specs:
        raise ValueError("Nothing to install")
    args = ["--upgrade"] if upgrade else []
    run(_cmd(python, "install", *args, *extra_args, *specs), ctx)


def conflicts(python: Path) -> list[str]:
    """Broken requirements among the installed packages (``pip check``); empty when consistent."""
    cmd = _cmd(python, "check")
    proc = capture(cmd, timeout=120)
    if proc.returncode == 0:
        return []
    lines = (proc.stdout + "\n" + proc.stderr).splitlines()
    return [l.strip() for l in lines if l.strip() and "No broken requirements" not in l]


def upgrade(python: Path, names: Iterable[str], ctx: TaskContext = NULL) -> UpgradeResult:
    """Upgrade ``names`` and report what changed; the resolver may hold some back or add new ones."""
    from .deps import normalize

    before = {normalize(p.name): p.version for p in installed(python)}
    install(python, names, ctx, upgrade=True)
    after = installed(python)
    changed = [Upgrade(p.name, before.get(normalize(p.name), ""), p.version)
               for p in after if before.get(normalize(p.name)) != p.version]
    try:
        broken = conflicts(python)
    except Exception as exc:  # e.g. no pip: the upgrade itself still succeeded
        ctx.log(f"Could not check for conflicts: {exc}")
        broken = []
    for line in broken:
        ctx.log(f"Conflict: {line}")
    return UpgradeResult(changed, broken, after)


def upgrade_all(python: Path, ctx: TaskContext = NULL) -> list[str]:
    """Upgrade every outdated package. Returns the names that were upgraded."""
    ctx.log("Checking for outdated packages…")
    names = sorted(outdated(python), key=str.lower)
    ctx.check()
    if not names:
        ctx.log("All packages are up to date.")
        return []
    install(python, names, ctx, upgrade=True)
    return names


def install_requirements(python: Path, requirements: Path, ctx: TaskContext = NULL) -> None:
    run(_cmd(python, "install", "-r", str(requirements)), ctx)


def uninstall(python: Path, names: Iterable[str], ctx: TaskContext = NULL) -> None:
    names = list(names)
    if not names:
        raise ValueError("Nothing to uninstall")
    args = [] if uv_path() else ["-y"]
    run(_cmd(python, "uninstall", *args, *names), ctx)


def download(
    python: Path, specs: Iterable[str], dest: Path, ctx: TaskContext = NULL, with_deps: bool = True
) -> None:
    """Download distributions (wheels/sdists) to ``dest`` without installing them.

    Always uses pip: uv has no download command.
    """
    cmd = [*_pip(python), "download", "-d", str(dest)]
    if not with_deps:
        cmd.append("--no-deps")
    run([*cmd, *specs], ctx)


def freeze(python: Path) -> str:
    cmd = _cmd(python, "freeze")
    proc = capture(cmd, timeout=120)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    return proc.stdout


def _sort_versions(uploads: dict[str, str]) -> list[str]:
    """Newest first. Uses ``packaging`` when available, otherwise upload time."""
    try:
        from packaging.version import Version

        return sorted(uploads, key=Version, reverse=True)
    except Exception:  # packaging missing or a non-PEP 440 version
        return sorted(uploads, key=lambda v: uploads[v], reverse=True)


def project_info(name: str) -> ProjectInfo:
    """Look a project up on PyPI. Raises LookupError if it does not exist."""
    url = PYPI_JSON.format(name=urllib.parse.quote(name.strip()))
    try:
        data = net.get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(f"'{name}' was not found on PyPI") from None
        raise
    info = data["info"]
    uploads = {}
    for version, files in data.get("releases", {}).items():
        live = [f for f in files if not f.get("yanked")]
        if live:
            uploads[version] = min(f.get("upload_time_iso_8601") or "" for f in live)
    versions = _sort_versions(uploads)
    return ProjectInfo(
        name=info["name"],
        summary=info.get("summary") or "",
        latest=info["version"],
        versions=versions,
        requires_python=info.get("requires_python") or "",
        home_page=info.get("home_page") or (info.get("project_urls") or {}).get("Homepage", "") or "",
    )
