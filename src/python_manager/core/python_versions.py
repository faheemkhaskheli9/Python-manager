"""Download, install and uninstall standalone CPython builds.

Builds come from https://github.com/astral-sh/python-build-standalone, which publishes
relocatable CPython distributions for Windows, macOS and Linux. An "install" is simply the
archive extracted into the app's data folder, so uninstalling is deleting that folder.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from . import net, paths
from .fs import remove_tree
from .interpreters import MANAGED, Interpreter, version_key
from .tasks import NULL, TaskContext

REPO = "astral-sh/python-build-standalone"
API_RELEASES = "https://api.github.com/repos/" + REPO + "/releases?per_page={count}"
LATEST_RELEASE = "https://github.com/" + REPO + "/releases/latest"
DOWNLOAD = "https://github.com/" + REPO + "/releases/download/{tag}/{name}"
MARKER = ".python-manager.json"


@dataclass(frozen=True)
class RemotePython:
    version: str
    build: str
    freethreaded: bool
    filename: str
    url: str
    sha256: Optional[str] = None

    @property
    def key(self) -> str:
        """Folder name of the installation; one install per version and variant."""
        return f"cpython-{self.version}{'t' if self.freethreaded else ''}"

    @property
    def prerelease(self) -> bool:
        return bool(re.search(r"(a|b|rc)\d+$", self.version))

    @property
    def variant(self) -> str:
        return "free-threaded" if self.freethreaded else "standard"


def target_triple() -> str:
    """The python-build-standalone target name for this machine."""
    machine = platform.machine().lower()
    arch = {
        "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "arm64": "aarch64", "aarch64": "aarch64",
        "x86": "i686", "i386": "i686", "i686": "i686",
        "armv7l": "armv7", "ppc64le": "ppc64le", "s390x": "s390x", "riscv64": "riscv64",
    }.get(machine, machine)
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    libc = "musl" if _is_musl() else "gnu"
    if arch == "armv7":
        return f"armv7-unknown-linux-{libc}eabihf"
    return f"{arch}-unknown-linux-{libc}"


def _is_musl() -> bool:
    lib, _ = platform.libc_ver()
    if lib == "glibc":
        return False
    return any(Path("/lib").glob("ld-musl-*"))


def parse_sha256sums(text: str, tag: str, triple: str) -> list[RemotePython]:
    """Extract the installable archives for ``triple`` from a release's SHA256SUMS file."""
    pattern = re.compile(
        r"^cpython-(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\+(?P<build>\d+)-"
        + re.escape(triple)
        + r"(?:-shared)?(?P<ft>-freethreaded)?-install_only\.tar\.gz$"
    )
    found = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        digest, name = parts
        m = pattern.match(name.lstrip("*"))
        if not m:
            continue
        url = DOWNLOAD.format(tag=tag, name=urllib.parse.quote(m.group(0)))
        found.append(RemotePython(m["version"], m["build"], bool(m["ft"]), m.group(0), url, digest))
    return found


def release_tags(count: int) -> list[str]:
    """Most recent release tags. Falls back to just the latest one if the API is unavailable."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        releases = net.get_json(API_RELEASES.format(count=max(1, min(count, 100))), headers)
        tags = [r["tag_name"] for r in releases if not r.get("draft")]
        if tags:
            return tags
    except Exception:
        pass
    with net.open_url(LATEST_RELEASE) as resp:  # redirects to .../releases/tag/<tag>
        return [resp.geturl().rstrip("/").rsplit("/", 1)[-1]]


def list_available(count: int = 3, ctx: TaskContext = NULL) -> list[RemotePython]:
    """Python versions downloadable for this machine, newest first, newest build per version."""
    triple = target_triple()
    ctx.log(f"Looking up Python builds for {triple}")
    best: dict[str, RemotePython] = {}
    tags = release_tags(count)[:count]

    def fetch(tag: str):
        try:
            return net.get_text(DOWNLOAD.format(tag=tag, name="SHA256SUMS")), None
        except Exception as exc:
            return None, exc

    with ThreadPoolExecutor(max_workers=6) as pool:  # one request per release, fetched in parallel
        for i, (tag, (text, error)) in enumerate(zip(tags, pool.map(fetch, tags))):
            ctx.check()
            ctx.progress(i + 1, len(tags))
            if error is not None:
                ctx.log(f"Skipping release {tag}: {error}")
                continue
            for item in parse_sha256sums(text, tag, triple):
                current = best.get(item.key)
                if current is None or int(item.build) > int(current.build):
                    best[item.key] = item
    return sorted(best.values(), key=lambda r: (version_key(r.version), not r.freethreaded), reverse=True)


def archive_path(remote: RemotePython) -> Path:
    return paths.cache_dir() / remote.filename


def install_dir(remote: RemotePython) -> Path:
    return paths.pythons_dir() / remote.key


def download(remote: RemotePython, ctx: TaskContext = NULL) -> Path:
    """Download the archive into the cache (reused if already present)."""
    target = archive_path(remote)
    if target.exists():
        ctx.log(f"Using cached {target.name}")
        return target
    ctx.log(f"Downloading {remote.url}")
    return net.download(remote.url, target, ctx, remote.sha256)


def _safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
            return
        root = dest.resolve()
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"Unsafe path in archive: {member.name}")
            if member.issym() or member.islnk():
                link = (target.parent / member.linkname).resolve()
                if root not in link.parents:
                    raise ValueError(f"Unsafe link in archive: {member.name}")
        tar.extractall(dest)


def find_executable(root: Path) -> Optional[Path]:
    """Locate the interpreter binary inside an extracted installation."""
    if sys.platform == "win32":
        names = [root / "python.exe", *sorted(root.glob("python3*.exe"))]
    else:
        bin_dir = root / "bin"
        names = [bin_dir / "python3", bin_dir / "python", *sorted(bin_dir.glob("python3*"))]
    for candidate in names:
        if candidate.is_file():
            return candidate
    return None


def install(remote: RemotePython, ctx: TaskContext = NULL) -> Interpreter:
    target = install_dir(remote)
    if target.exists():
        raise FileExistsError(f"Python {remote.version} ({remote.variant}) is already installed")
    archive = download(remote, ctx)
    ctx.log(f"Extracting {archive.name}")
    with tempfile.TemporaryDirectory(dir=paths.pythons_dir(), prefix=".extract-") as tmp:
        _safe_extract(archive, Path(tmp))
        extracted = Path(tmp) / "python"
        if not extracted.is_dir():
            raise ValueError("Unexpected archive layout: no 'python' folder")
        ctx.check()
        shutil.move(str(extracted), str(target))
    (target / MARKER).write_text(json.dumps(asdict(remote), indent=2), encoding="utf-8")
    exe = find_executable(target)
    if exe is None:
        shutil.rmtree(target, ignore_errors=True)
        raise FileNotFoundError("Installed archive contains no Python executable")
    ctx.log(f"Installed Python {remote.version} to {target}")
    return Interpreter(exe, remote.version, MANAGED, remote.key)


def list_installed() -> list[Interpreter]:
    """Pythons installed by this app."""
    result = []
    for folder in paths.pythons_dir().iterdir():
        marker = folder / MARKER
        if folder.name.startswith(".") or not marker.is_file():
            continue
        exe = find_executable(folder)
        if exe is None:
            continue
        try:
            version = json.loads(marker.read_text(encoding="utf-8"))["version"]
        except (OSError, ValueError, KeyError):
            continue
        result.append(Interpreter(exe, version, MANAGED, folder.name))
    return sorted(result, key=lambda i: version_key(i.version), reverse=True)


def uninstall(interpreter: Interpreter, ctx: TaskContext = NULL) -> None:
    if interpreter.kind != MANAGED:
        raise PermissionError("Only Pythons installed by Python Manager can be uninstalled here")
    root = paths.pythons_dir() / interpreter.name
    if not (root / MARKER).is_file():
        raise FileNotFoundError(f"{root} is not a managed installation")
    ctx.log(f"Removing {root}")
    remove_tree(root)


def installed_keys() -> set[str]:
    return {p.name for p in paths.pythons_dir().iterdir() if (p / MARKER).is_file()}
