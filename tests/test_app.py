import os
import subprocess
import sys
from pathlib import Path

import pytest

import python_manager
from python_manager import __version__

SRC = str(Path(python_manager.__file__).resolve().parents[1])


def run_app(*args):
    path = os.pathsep.join(p for p in (SRC, os.environ.get("PYTHONPATH")) if p)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": path}
    return subprocess.run([sys.executable, "-m", "python_manager", *args],
                          capture_output=True, text=True, timeout=120, env=env)


def test_version():
    result = run_app("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"Python Manager {__version__}"


def test_self_test_starts_and_exits():
    pytest.importorskip("PySide6")
    result = run_app("--self-test")
    assert result.returncode == 0, result.stderr
