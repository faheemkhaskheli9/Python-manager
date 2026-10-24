"""Disk space used by each package installed for an interpreter, from the files its metadata lists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .tasks import CommandError, capture

# Runs inside the target interpreter, so it must work on any Python 3.8+ with only the stdlib.
# A package without a file list (no RECORD, e.g. some system packages) gets null.
_SCRIPT = r"""
import json, os, re
from importlib import metadata

def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()

sizes, seen = {}, set()
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if not name or norm(name) in sizes:
        continue
    files = dist.files
    if files is None:
        sizes[norm(name)] = None
        continue
    total = 0
    for file in files:
        path = os.path.normcase(os.path.abspath(str(dist.locate_file(file))))
        if path in seen:
            continue
        seen.add(path)
        try:
            total += os.lstat(path).st_size
        except OSError:
            pass
    sizes[norm(name)] = total
print(json.dumps(sizes))
"""


def scan(python: Path) -> dict[str, Optional[int]]:
    """Normalised package name -> bytes on disk (None when the package lists no files)."""
    cmd = [str(python), "-I", "-c", _SCRIPT]
    proc = capture(cmd, timeout=300)
    if proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])
