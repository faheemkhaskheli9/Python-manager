"""Export an environment: pinned requirements files (optionally with hashes), pylock.toml, pyproject.toml
and a CycloneDX SBOM."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .. import __version__
from . import deps, licenses, net, projectfile
from .tasks import NULL, TaskContext

PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
PYPI_INDEX = "https://pypi.org/simple"


@dataclass(frozen=True)
class Format:
    key: str
    label: str
    description: str
    filename: str
    online: bool = False  # needs PyPI for file hashes


PINNED = Format("pinned", "requirements.txt — all packages, pinned",
                "Every installed package with its exact version (pip freeze).", "requirements.txt")
TOP_LEVEL = Format("top", "requirements.txt — top-level packages, pinned",
                   "Only the packages nothing else requires; pip resolves their dependencies.", "requirements.txt")
HASHES = Format("hashes", "requirements.txt — pinned with hashes",
                "Exact versions plus file hashes, for pip install --require-hashes.", "requirements.txt", True)
PYLOCK = Format("pylock", "pylock.toml — lock file (PEP 751)",
                "Exact versions with file URLs and hashes; installable with uv or pip.", "pylock.toml", True)
PYPROJECT = Format("pyproject", "pyproject.toml — top-level dependencies",
                   "A minimal project listing the top-level packages as minimum versions.", "pyproject.toml")
SBOM = Format("sbom", "sbom.cdx.json — CycloneDX SBOM",
              "Every package with its version, purl, licence and dependencies, as a CycloneDX 1.6 JSON SBOM.",
              "sbom.cdx.json", True)
FORMATS = (PINNED, TOP_LEVEL, HASHES, PYLOCK, PYPROJECT, SBOM)


@dataclass(frozen=True)
class File:
    filename: str
    url: str
    sha256: str
    size: int
    upload_time: str  # ISO 8601, UTC
    wheel: bool


@dataclass(frozen=True)
class Result:
    path: Path
    packages: int
    skipped: list[str]  # name==version of packages that could not be locked (not on PyPI)


def release_files(name: str, version: str) -> list[File]:
    """The files PyPI has for one release. Raises LookupError when PyPI does not have it."""
    url = PYPI_RELEASE.format(name=urllib.parse.quote(name), version=urllib.parse.quote(version))
    try:
        data = net.get_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(f"{name} {version} is not on PyPI") from None
        raise
    return [File(f["filename"], f["url"], f["digests"]["sha256"], int(f.get("size") or 0),
                 f.get("upload_time_iso_8601") or "", f.get("packagetype") == "bdist_wheel")
            for f in data.get("urls", []) if f.get("digests", {}).get("sha256")]


def fetch_files(dists: list[deps.Dist], ctx: TaskContext = NULL) -> tuple[dict[str, list[File]], list[str]]:
    """Files of each release (keyed by normalised name) and the name==version of those PyPI lacks."""
    def one(dist: deps.Dist) -> Optional[list[File]]:
        ctx.check()
        try:
            return release_files(dist.name, dist.version) or None
        except LookupError:
            return None

    found, missing = {}, []
    with ThreadPoolExecutor(max_workers=8) as pool:  # one small request each
        for done, (dist, files) in enumerate(zip(dists, pool.map(one, dists)), 1):
            ctx.progress(done, len(dists))
            if files:
                found[deps.normalize(dist.name)] = files
            else:
                missing.append(f"{dist.name}=={dist.version}")
    return found, missing


def _header(env_name: str, python_version: str) -> str:
    return f"# {env_name} · Python {python_version} · exported {time.strftime('%Y-%m-%d')} by Python Manager\n"


def hashed_requirements(dists: list[deps.Dist], files: dict[str, list[File]], header: str = "") -> str:
    lines = [header] if header else []
    for dist in dists:
        hashes = sorted({f.sha256 for f in files.get(deps.normalize(dist.name), [])})
        if not hashes:
            lines.append(f"# not on PyPI, add it by hand: {dist.name}=={dist.version}\n")
            continue
        lines.append(f"{dist.name}=={dist.version} \\\n")
        lines.append(" \\\n".join(f"    --hash=sha256:{h}" for h in hashes) + "\n")
    return "".join(lines)


def _toml_file(file: File) -> str:
    fields = [f"name = {json.dumps(file.filename)}", f"url = {json.dumps(file.url)}"]
    if file.size:
        fields.append(f"size = {file.size}")
    if file.upload_time:
        fields.append(f"upload-time = {file.upload_time}")  # a TOML datetime, not a string
    fields.append(f"hashes = {{sha256 = {json.dumps(file.sha256)}}}")
    return "{" + ", ".join(fields) + "}"


def pylock(dists: list[deps.Dist], files: dict[str, list[File]], python_version: str, header: str = "") -> str:
    """A PEP 751 lock file for exactly these releases."""
    major_minor = ".".join(python_version.split(".")[:2])
    out = [header] if header else []
    out += ['lock-version = "1.0"\n', 'created-by = "python-manager"\n',
            f'requires-python = "=={major_minor}.*"\n']
    for dist in dists:
        key = deps.normalize(dist.name)
        found = files.get(key)
        if not found:
            out.append(f"\n# not on PyPI, left out: {dist.name}=={dist.version}\n")
            continue
        out += ["\n[[packages]]\n", f"name = {json.dumps(key)}\n", f"version = {json.dumps(dist.version)}\n",
                f"index = {json.dumps(PYPI_INDEX)}\n"]
        sdists = [f for f in found if not f.wheel]
        if sdists:
            out.append(f"sdist = {_toml_file(sdists[0])}\n")
        wheels = [f for f in found if f.wheel]
        if wheels:
            out.append("wheels = [\n" + "".join(f"    {_toml_file(w)},\n" for w in wheels) + "]\n")
    return "".join(out)


def purl(name: str, version: str) -> str:
    """Package URL of a PyPI release: normalised name, percent-encoded version."""
    return f"pkg:pypi/{deps.normalize(name)}@{urllib.parse.quote(version, safe='.-_~!')}"


def _license_entry(item: licenses.PackageLicense) -> list[dict]:
    if not item.license:
        return []
    if item.source == "License-Expression":
        return [{"expression": item.license}]
    return [{"license": {"name": item.license}}]


def cyclonedx(dists: list[deps.Dist], files: dict[str, list[File]], found_licenses: dict[str, licenses.PackageLicense],
              env_name: str, python_version: str) -> str:
    """A CycloneDX 1.6 JSON SBOM of these releases; PyPI file hashes are added where ``files`` has them."""
    refs = {deps.normalize(d.name): purl(d.name, d.version) for d in dists}
    components = []
    for dist in dists:
        key = deps.normalize(dist.name)
        component = {"type": "library", "bom-ref": refs[key], "name": dist.name, "version": dist.version,
                     "purl": refs[key]}
        license = found_licenses.get(key)
        if license and _license_entry(license):
            component["licenses"] = _license_entry(license)
        if files.get(key):
            component["externalReferences"] = [
                {"type": "distribution", "url": f.url, "hashes": [{"alg": "SHA-256", "content": f.sha256}]}
                for f in files[key]]
        components.append(component)
    root = f"{env_name} (Python {python_version})"
    top = [refs[k] for k in sorted(refs) if not any(k in d.requires for d in dists)]
    dependencies = [{"ref": root, "dependsOn": top}]
    dependencies += [{"ref": refs[deps.normalize(d.name)],
                      "dependsOn": [refs[r] for r in sorted(d.requires) if r in refs]} for d in dists]
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tools": {"components": [{"type": "application", "name": "python-manager", "version": __version__}]},
            "component": {"type": "application", "bom-ref": root, "name": env_name,
                          "properties": [{"name": "python:version", "value": python_version}]},
        },
        "components": components,
        "dependencies": dependencies,
    }
    return json.dumps(bom, indent=2) + "\n"


def export(python: Path, fmt: Format, path: Path, env_name: str, python_version: str,
           ctx: TaskContext = NULL, exclude_tools: bool = True) -> Result:
    """Write the environment's packages at ``python`` to ``path`` in format ``fmt``."""
    path = Path(path)
    skip = projectfile.SKIP if exclude_tools else set()
    if fmt is PINNED:
        text = projectfile.clone_requirements(python, skip)
        path.write_text(_header(env_name, python_version) + text, encoding="utf-8")
        return Result(path, len(text.splitlines()), [])
    if fmt is PYPROJECT:
        text = projectfile.pyproject_for(python, env_name, python_version, skip)
        path.write_text(text, encoding="utf-8")
        return Result(path, text.count('",\n'), [])

    ctx.log("Reading installed packages")
    graph = deps.load_graph(python)
    if fmt is TOP_LEVEL:
        top = projectfile.top_level(graph, skip)
        path.write_text(_header(env_name, python_version) + "".join(f"{d.name}=={d.version}\n" for d in top),
                        encoding="utf-8")
        return Result(path, len(top), [])

    dists = sorted((d for k, d in graph.items() if k not in skip), key=lambda d: d.name.lower())
    ctx.log(f"Fetching file hashes of {len(dists)} packages from PyPI")
    files, missing = fetch_files(dists, ctx)
    if fmt is SBOM:
        ctx.log("Reading licences")
        found = {deps.normalize(i.name): i for i in licenses.scan(python)}
        path.write_text(cyclonedx(dists, files, found, env_name, python_version), encoding="utf-8")
        for spec in missing:
            ctx.log(f"Not on PyPI, no hashes: {spec}")
        return Result(path, len(dists), [])
    header = _header(env_name, python_version)
    text = pylock(dists, files, python_version, header) if fmt is PYLOCK else hashed_requirements(dists, files, header)
    path.write_text(text, encoding="utf-8")
    for spec in missing:
        ctx.log(f"Not on PyPI, left out: {spec}")
    return Result(path, len(dists) - len(missing), missing)
