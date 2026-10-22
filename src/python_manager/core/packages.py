"""Package management through the target interpreter's pip, plus PyPI lookups."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import net
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
class ProjectInfo:
    name: str
    summary: str
    latest: str
    versions: list[str] = field(default_factory=list)  # newest first
    requires_python: str = ""
    home_page: str = ""


def _pip(python: Path) -> list[str]:
    return [str(python), "-m", "pip"]


def _pip_json(python: Path, *args: str) -> list[dict]:
    proc = capture([*_pip(python), *args, "--format=json"], timeout=300)
    if proc.returncode != 0:
        if "No module named pip" in proc.stderr:
            raise PipMissing(f"pip is not installed for {python}")
        raise CommandError([*_pip(python), *args], proc.returncode, proc.stderr or proc.stdout)
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("["):
            return json.loads(line)
    return []


def list_packages(python: Path) -> list[Package]:
    items = _pip_json(python, "list")
    return sorted((Package(i["name"], i["version"]) for i in items), key=lambda p: p.name.lower())


def outdated(python: Path) -> dict[str, str]:
    """Map of package name -> newest version available, for packages with updates."""
    return {i["name"]: i["latest_version"] for i in _pip_json(python, "list", "--outdated")}


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
    cmd = [*_pip(python), "install"]
    if upgrade:
        cmd.append("--upgrade")
    run([*cmd, *extra_args, *specs], ctx)


def install_requirements(python: Path, requirements: Path, ctx: TaskContext = NULL) -> None:
    run([*_pip(python), "install", "-r", str(requirements)], ctx)


def uninstall(python: Path, names: Iterable[str], ctx: TaskContext = NULL) -> None:
    names = list(names)
    if not names:
        raise ValueError("Nothing to uninstall")
    run([*_pip(python), "uninstall", "-y", *names], ctx)


def download(
    python: Path, specs: Iterable[str], dest: Path, ctx: TaskContext = NULL, with_deps: bool = True
) -> None:
    """Download distributions (wheels/sdists) to ``dest`` without installing them."""
    cmd = [*_pip(python), "download", "-d", str(dest)]
    if not with_deps:
        cmd.append("--no-deps")
    run([*cmd, *specs], ctx)


def freeze(python: Path) -> str:
    proc = capture([*_pip(python), "freeze"], timeout=120)
    if proc.returncode != 0:
        raise CommandError([*_pip(python), "freeze"], proc.returncode, proc.stderr)
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
