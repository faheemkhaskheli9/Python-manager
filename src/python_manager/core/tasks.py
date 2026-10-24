"""Progress, logging and cancellation shared by long-running operations."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable, Optional, Sequence

from . import indexes


class Cancelled(Exception):
    """Raised when the user cancels an operation."""


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], returncode: int, output: str):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.output = output
        tail = "\n".join(output.strip().splitlines()[-15:])
        super().__init__(f"Command failed ({returncode}): {' '.join(map(str, cmd))}\n{tail}")


class TaskContext:
    """Passed to core functions so they can report progress and honour cancellation."""

    def __init__(
        self,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[int, int], None]] = None,
    ):
        self._log = log
        self._progress = progress
        self._cancel = threading.Event()

    def log(self, message: str) -> None:
        if self._log:
            self._log(message)

    def progress(self, done: int, total: int) -> None:
        if self._progress:
            self._progress(done, total)

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()


NULL = TaskContext()

# Prevent console windows from flashing up on Windows.
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _env() -> dict[str, str]:
    return dict(os.environ, PYTHONIOENCODING="utf-8", PIP_DISABLE_PIP_VERSION_CHECK="1", **indexes.env())


def run(
    cmd: Sequence[str],
    ctx: TaskContext = NULL,
    cwd: Optional[str] = None,
    check: bool = True,
    echo: bool = True,
) -> str:
    """Run a command, streaming its output to ``ctx.log``. Returns the combined output."""
    if echo:
        ctx.log("$ " + " ".join(map(str, cmd)))
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=cwd,
        env=_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_FLAGS,
    )
    watcher_done = threading.Event()

    def watch_cancel() -> None:
        while not watcher_done.wait(0.2):
            if ctx.cancelled and proc.poll() is None:
                proc.terminate()
                return

    threading.Thread(target=watch_cancel, daemon=True).start()
    lines = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if echo:
                ctx.log(line.rstrip("\n"))
        proc.wait()
    finally:
        watcher_done.set()
    ctx.check()
    output = "".join(lines)
    if check and proc.returncode != 0:
        raise CommandError(cmd, proc.returncode, output)
    return output


def capture(cmd: Sequence[str], timeout: float = 30) -> subprocess.CompletedProcess:
    """Run a quick command silently and return the completed process."""
    return subprocess.run(
        [str(c) for c in cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        creationflags=_CREATE_FLAGS,
        env=_env(),
    )
