"""Licenses of the packages installed for an interpreter, read from their metadata."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .tasks import CommandError, capture

# Runs inside the target interpreter, so it must work on any Python 3.8+ with only the stdlib.
_SCRIPT = r"""
import json, re
from importlib import metadata

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

result = {}
for dist in metadata.distributions():
    meta = dist.metadata
    name = meta["Name"]
    if not name or norm(name) in result:
        continue
    result[norm(name)] = {
        "name": name,
        "version": dist.version,
        "expression": meta.get("License-Expression") or "",
        "license": meta.get("License") or "",
        "classifiers": [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")],
        "files": meta.get_all("License-File") or [],
    }
print(json.dumps(sorted(result.values(), key=lambda d: d["name"].lower())))
"""

PERMISSIVE = "Permissive"
WEAK_COPYLEFT = "Weak copyleft"
COPYLEFT = "Copyleft"
PUBLIC_DOMAIN = "Public domain"
OTHER = "Other"
UNKNOWN = "Unknown"

# Trove classifier (after "License :: OSI Approved :: ") -> SPDX identifier.
_CLASSIFIERS = {
    "MIT License": "MIT",
    "MIT No Attribution License (MIT-0)": "MIT-0",
    "BSD License": "BSD",
    "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL",
    "GNU General Public License (GPL)": "GPL",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0",
    "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Affero General Public License v3": "AGPL-3.0",
    "GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
    "zlib/libpng License": "Zlib",
    "Academic Free License (AFL)": "AFL",
    "Artistic License": "Artistic",
    "Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND",
}

# Checked in order: the first pattern found in a licence text or expression decides its category.
_CATEGORIES = [
    (re.compile(r"\b(AGPL|Affero)", re.I), COPYLEFT),
    (re.compile(r"\b(LGPL|Lesser General|Library General)", re.I), WEAK_COPYLEFT),
    (re.compile(r"\b(MPL|Mozilla|EPL|Eclipse|CDDL|EUPL)", re.I), WEAK_COPYLEFT),
    (re.compile(r"\b(GPL|General Public License)", re.I), COPYLEFT),
    (re.compile(r"\b(Unlicense|CC0|Public Domain)", re.I), PUBLIC_DOMAIN),
    (re.compile(r"\b(MIT|BSD|Apache|ISC|PSF|Python Software Foundation|Zlib|HPND|BSL|Boost|AFL|Artistic|"
                r"0BSD|X11|Expat|UPL|Unicode)", re.I), PERMISSIVE),
]

# Longer "License" fields are usually the whole licence text, not its name.
_MAX_NAME = 80


@dataclass(frozen=True)
class PackageLicense:
    name: str
    version: str
    license: str  # SPDX expression or short name; empty when unknown
    source: str  # "License-Expression", "classifier", "License" or "" when unknown
    files: tuple[str, ...]  # License-File entries

    @property
    def category(self) -> str:
        return category(self.license)


def category(license: str) -> str:
    """Rough kind of licence: permissive, weak copyleft, copyleft, public domain, other or unknown.

    For an expression with ``OR`` the most permissive choice counts; with ``AND`` the strictest.
    """
    if not license.strip():
        return UNKNOWN
    order = [PUBLIC_DOMAIN, PERMISSIVE, WEAK_COPYLEFT, COPYLEFT, OTHER]
    if re.search(r"\sOR\s", license):
        return min((category(part) for part in re.split(r"\sOR\s", license)), key=order.index)
    if re.search(r"\sAND\s|\sWITH\s", license):
        parts = re.split(r"\sAND\s", re.sub(r"\sWITH\s+\S+", "", license))
        return max((category(part) for part in parts), key=order.index)
    for pattern, kind in _CATEGORIES:
        if pattern.search(license):
            return kind
    return OTHER


def _from_classifier(classifier: str) -> str:
    name = classifier.split("::")[-1].strip()
    return _CLASSIFIERS.get(name, name)


def resolve(entry: dict) -> PackageLicense:
    """Pick the clearest licence from a metadata entry: expression, classifiers, then License."""
    expression = entry.get("expression", "").strip()
    classifiers = [c for c in entry.get("classifiers", []) if c.strip() != "License :: OSI Approved"]
    text = " ".join(entry.get("license", "").split())
    if expression:
        license, source = expression, "License-Expression"
    elif classifiers:
        license, source = " OR ".join(dict.fromkeys(_from_classifier(c) for c in classifiers)), "classifier"
    elif text and text.upper() not in ("UNKNOWN", "NONE") and len(text) <= _MAX_NAME:
        license, source = text, "License"
    elif text and text.upper() not in ("UNKNOWN", "NONE"):
        license, source = _first_line(entry.get("license", "")), "License"
    else:
        license, source = "", ""
    return PackageLicense(entry["name"], entry["version"], license, source, tuple(entry.get("files", [])))


def _first_line(text: str) -> str:
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return line if len(line) <= _MAX_NAME else line[:_MAX_NAME - 1] + "…"


def scan(python: Path) -> list[PackageLicense]:
    cmd = [str(python), "-I", "-c", _SCRIPT]
    proc = capture(cmd, timeout=120)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    return [resolve(entry) for entry in json.loads(proc.stdout.strip().splitlines()[-1])]


def summary(items: list[PackageLicense]) -> dict[str, int]:
    """Number of packages per category, most common first."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def to_csv(items: list[PackageLicense]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Package", "Version", "License", "Category", "Source", "License files"])
    for i in items:
        writer.writerow([i.name, i.version, i.license, i.category, i.source, "; ".join(i.files)])
    return out.getvalue()


def to_markdown(items: list[PackageLicense], title: str = "") -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|") or "—"

    lines = [f"# {title}", ""] if title else []
    lines += [", ".join(f"{kind}: {n}" for kind, n in summary(items).items()), ""]
    lines += ["| Package | Version | License | Category |", "|---|---|---|---|"]
    lines += [f"| {cell(i.name)} | {cell(i.version)} | {cell(i.license)} | {i.category} |" for i in items]
    return "\n".join(lines) + "\n"


def to_json(items: list[PackageLicense]) -> str:
    return json.dumps([{"name": i.name, "version": i.version, "license": i.license, "category": i.category,
                        "source": i.source, "files": list(i.files)} for i in items], indent=2) + "\n"
