"""Compare the packages of two interpreters and find a package across many."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import packages
from .deps import normalize
from .packages import Package
from .tasks import NULL, TaskContext

SAME = "Same"
DIFFERENT = "Different"
ONLY_LEFT = "Only left"
ONLY_RIGHT = "Only right"


@dataclass(frozen=True)
class Row:
    name: str
    left: str  # version, empty when not installed on that side
    right: str
    status: str


def diff(left: Iterable[Package], right: Iterable[Package]) -> list[Row]:
    """One row per package installed on either side, sorted by name."""
    a = {normalize(p.name): p for p in left}
    b = {normalize(p.name): p for p in right}
    rows = []
    for key in a.keys() | b.keys():
        pa, pb = a.get(key), b.get(key)
        if pa and pb:
            status = SAME if pa.version == pb.version else DIFFERENT
        else:
            status = ONLY_LEFT if pa else ONLY_RIGHT
        rows.append(Row((pa or pb).name, pa.version if pa else "", pb.version if pb else "", status))
    return sorted(rows, key=lambda r: r.name.lower())


def summary(rows: list[Row]) -> dict[str, int]:
    counts = {s: 0 for s in (DIFFERENT, ONLY_LEFT, ONLY_RIGHT, SAME)}
    for row in rows:
        counts[row.status] += 1
    return counts


def match_left(rows: Iterable[Row]) -> list[str]:
    """Pins that give the right side the left side's versions (extra packages on the right stay)."""
    return [f"{r.name}=={r.left}" for r in rows if r.left and r.status != SAME]


@dataclass(frozen=True)
class Match:
    location: str  # label of the interpreter or environment
    executable: Path
    name: str
    version: str


def matcher(pattern: str):
    """A predicate on package names: a glob when ``pattern`` has wildcards, else a substring test."""
    text = normalize(pattern.strip())
    if any(c in text for c in "*?["):
        return lambda name: fnmatch.fnmatchcase(normalize(name), text)
    return lambda name: text in normalize(name)


def find(pattern: str, targets: Iterable[tuple[str, Path]], ctx: TaskContext = NULL) -> tuple[list[Match], list[str]]:
    """Packages matching ``pattern`` in each (label, executable); also returns labels that could not be read."""
    test = matcher(pattern)
    found, failed = [], []
    for label, executable in targets:
        ctx.check()
        try:
            installed = packages.installed(executable)
        except Exception as exc:
            ctx.log(f"Could not list packages of {label}: {exc}")
            failed.append(label)
            continue
        found += [Match(label, executable, p.name, p.version) for p in installed if test(p.name)]
    return found, failed

