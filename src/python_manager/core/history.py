"""Package history: a snapshot of an environment's packages before each change, and restoring one."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import compare, packages, paths
from .deps import KEEP, normalize
from .packages import Package
from .tasks import NULL, TaskContext

LIMIT = 30  # snapshots kept per environment; the oldest are dropped


@dataclass(frozen=True)
class Snapshot:
    time: float
    action: str  # what was about to happen, e.g. "Upgrading requests"
    packages: tuple[Package, ...]


def _file(python: Path) -> Path:
    key = os.path.normcase(os.path.abspath(python))
    return paths.data_dir() / "history" / (hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".json")


def _load(python: Path) -> list[Snapshot]:
    try:
        data = json.loads(_file(python).read_text(encoding="utf-8"))
        return [Snapshot(float(s["time"]), str(s["action"]),
                         tuple(Package(n, v) for n, v in s["packages"].items())) for s in data["snapshots"]]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _save(python: Path, snapshots: list[Snapshot]) -> None:
    file = _file(python)
    file.parent.mkdir(parents=True, exist_ok=True)
    data = {"python": str(python), "snapshots": [
        {"time": s.time, "action": s.action, "packages": {p.name: p.version for p in s.packages}}
        for s in snapshots[-LIMIT:]]}
    file.write_text(json.dumps(data, indent=1), encoding="utf-8")


def snapshots(python: Path) -> list[Snapshot]:
    """Saved snapshots of ``python``'s packages, newest first."""
    return list(reversed(_load(python)))


def snapshot(python: Path, action: str) -> Optional[Snapshot]:
    """Save the current packages before ``action``; nothing is saved when they match the last snapshot."""
    try:
        current = tuple(packages.installed(python))
    except Exception:  # an environment that cannot be read is not worth failing the change for
        return None
    saved = _load(python)
    if saved and _same(saved[-1].packages, current):
        return None
    snap = Snapshot(time.time(), action, current)
    _save(python, saved + [snap])
    return snap


def _same(a: tuple[Package, ...], b: tuple[Package, ...]) -> bool:
    return {normalize(p.name): p.version for p in a} == {normalize(p.name): p.version for p in b}


@dataclass(frozen=True)
class Plan:
    install: list[str]  # name==version pins
    remove: list[str]  # names installed now that the snapshot did not have

    @property
    def empty(self) -> bool:
        return not self.install and not self.remove


def plan(current: list[Package], snap: Snapshot) -> Plan:
    """What restoring ``snap`` changes; pip, setuptools and wheel are never removed."""
    rows = compare.diff(snap.packages, current)
    remove = [r.name for r in rows if r.status == compare.ONLY_RIGHT and normalize(r.name) not in KEEP]
    return Plan(compare.match_left(rows), remove)


def restore(python: Path, snap: Snapshot, ctx: TaskContext = NULL) -> Plan:
    """Put ``python``'s packages back as they were in ``snap``; the current state is saved first."""
    todo = plan(packages.installed(python), snap)
    if todo.empty:
        ctx.log("The packages already match the snapshot")
        return todo
    snapshot(python, "Restoring snapshot of " + time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.time)))
    if todo.install:
        packages.install(python, todo.install, ctx)
    if todo.remove:
        packages.uninstall(python, todo.remove, ctx)
    return todo


def clear(python: Path) -> None:
    try:
        _file(python).unlink()
    except FileNotFoundError:
        pass
