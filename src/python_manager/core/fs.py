"""Filesystem helpers."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (common on Windows)."""

    def on_error(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onerror=on_error)
