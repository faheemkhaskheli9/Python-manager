"""Dependency graph of the packages installed for an interpreter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .tasks import CommandError, capture

# Runs inside the target interpreter, so it must work on any Python 3.8+ with only the stdlib.
# Markers are evaluated with packaging (or pip's vendored copy) when one is importable.
_SCRIPT = r"""
import json, re
from importlib import metadata
try:
    from packaging.requirements import Requirement
except Exception:
    try:
        from pip._vendor.packaging.requirements import Requirement
    except Exception:
        Requirement = None

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

def requirements(dist):
    names = set()
    for text in dist.requires or []:
        if Requirement is not None:
            try:
                req = Requirement(text)
                if req.marker is None or req.marker.evaluate({"extra": ""}):
                    names.add(norm(req.name))
            except Exception:
                pass
            continue
        spec, _, marker = text.partition(";")
        if "extra" not in marker:
            match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
            if match:
                names.add(norm(match.group(1)))
    return sorted(names)

graph = {}
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if name and norm(name) not in graph:
        graph[norm(name)] = {"name": name, "version": dist.version, "requires": requirements(dist)}
print(json.dumps(graph))
"""


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Dist:
    name: str
    version: str
    requires: tuple[str, ...]  # normalised names


Graph = dict[str, Dist]  # keyed by normalised name

# Packaging tools are never offered for removal as "unused".
KEEP = {"pip", "setuptools", "wheel"}


def load_graph(python: Path) -> Graph:
    cmd = [str(python), "-I", "-c", _SCRIPT]
    proc = capture(cmd, timeout=120)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return {key: Dist(v["name"], v["version"], tuple(v["requires"])) for key, v in data.items()}


def required_by(graph: Graph) -> dict[str, list[str]]:
    """Normalised name -> display names of the installed packages that require it."""
    reverse: dict[str, list[str]] = {}
    for dist in graph.values():
        for req in dist.requires:
            reverse.setdefault(req, []).append(dist.name)
    return {key: sorted(names, key=str.lower) for key, names in reverse.items()}


def dependents(graph: Graph, names: Iterable[str]) -> dict[str, list[str]]:
    """For each of ``names``, the installed packages outside ``names`` that still require it."""
    removing = {normalize(n) for n in names}
    reverse = required_by(graph)
    result = {}
    for name in names:
        users = [u for u in reverse.get(normalize(name), []) if normalize(u) not in removing]
        if users:
            result[name] = users
    return result


def unused_after_removal(graph: Graph, names: Iterable[str]) -> list[str]:
    """Dependencies of ``names`` that nothing else would need once ``names`` are removed."""
    removing = {normalize(n) for n in names}
    reachable, stack = set(), [r for n in removing if n in graph for r in graph[n].requires]
    while stack:
        key = stack.pop()
        if key not in reachable and key not in removing and key in graph:
            reachable.add(key)
            stack.extend(graph[key].requires)
    users = {key: {u for u, d in graph.items() if key in d.requires} for key in reachable}
    candidates: set[str] = set()
    changed = True
    while changed:
        changed = False
        for key in reachable - candidates:
            if users[key] <= removing | candidates:
                candidates.add(key)
                changed = True
    return sorted((graph[k].name for k in candidates - KEEP), key=str.lower)
