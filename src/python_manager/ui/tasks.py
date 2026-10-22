"""Runs core operations on a thread pool and relays progress back to the UI thread."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.tasks import Cancelled, TaskContext


class _Signals(QObject):
    log = Signal(int, str)
    progress = Signal(int, int, int)
    done = Signal(int, object)
    failed = Signal(int, str, bool)


class _Job(QRunnable):
    def __init__(self, job_id: int, fn: Callable[[TaskContext], Any], signals: _Signals, ctx: TaskContext):
        super().__init__()
        self.job_id, self.fn, self.signals, self.ctx = job_id, fn, signals, ctx

    def run(self) -> None:
        try:
            result = self.fn(self.ctx)
        except Cancelled:
            self.signals.failed.emit(self.job_id, "Cancelled", True)
        except Exception as exc:  # reported to the user, never crash the worker thread
            self.signals.failed.emit(self.job_id, str(exc) or type(exc).__name__, False)
        else:
            self.signals.done.emit(self.job_id, result)


@dataclass
class _Entry:
    title: str
    foreground: bool
    ctx: TaskContext
    on_done: Optional[Callable[[Any], None]]
    on_error: Optional[Callable[[str], None]]


class TaskManager(QObject):
    """One foreground task at a time (shown in the status bar); any number of background ones."""

    started = Signal(str)
    progress = Signal(int, int)
    finished = Signal(str)
    log = Signal(str)

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._pool = QThreadPool.globalInstance()
        self._ids = itertools.count(1)
        self._jobs: dict[int, _Entry] = {}
        self._signals = _Signals(self)
        self._signals.log.connect(self._on_log)
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)

    @property
    def busy(self) -> bool:
        return any(e.foreground for e in self._jobs.values())

    def run(
        self,
        title: str,
        fn: Callable[[TaskContext], Any],
        on_done: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        foreground: bool = True,
    ) -> bool:
        if foreground and self.busy:
            current = next(e.title for e in self._jobs.values() if e.foreground)
            QMessageBox.information(self._window, "Busy", f"Please wait for “{current}” to finish.")
            return False
        job_id = next(self._ids)
        signals = self._signals
        ctx = TaskContext(
            log=lambda msg: signals.log.emit(job_id, msg),
            progress=lambda done, total: signals.progress.emit(job_id, done, total),
        )
        self._jobs[job_id] = _Entry(title, foreground, ctx, on_done, on_error)
        if foreground:
            self.log.emit(f"▶ {title}")
            self.started.emit(title)
        self._pool.start(_Job(job_id, fn, signals, ctx))
        return True

    def cancel(self) -> None:
        for entry in self._jobs.values():
            if entry.foreground:
                entry.ctx.cancel()

    @Slot(int, str)
    def _on_log(self, job_id: int, message: str) -> None:
        entry = self._jobs.get(job_id)
        if entry and entry.foreground:
            self.log.emit(message)

    @Slot(int, int, int)
    def _on_progress(self, job_id: int, done: int, total: int) -> None:
        entry = self._jobs.get(job_id)
        if entry and entry.foreground:
            self.progress.emit(done, total)

    @Slot(int, object)
    def _on_done(self, job_id: int, result: object) -> None:
        entry = self._jobs.pop(job_id, None)
        if entry is None:
            return
        if entry.foreground:
            self.log.emit(f"✔ {entry.title}: done")
            self.finished.emit(f"{entry.title}: done")
        if entry.on_done:
            entry.on_done(result)

    @Slot(int, str, bool)
    def _on_failed(self, job_id: int, message: str, cancelled: bool) -> None:
        entry = self._jobs.pop(job_id, None)
        if entry is None:
            return
        if entry.foreground:
            self.log.emit(f"✖ {entry.title}: {message}")
            self.finished.emit(f"{entry.title}: {'cancelled' if cancelled else 'failed'}")
        if entry.on_error:
            entry.on_error(message)
        elif entry.foreground and not cancelled:
            box = QMessageBox(QMessageBox.Icon.Critical, "Operation failed", entry.title, parent=self._window)
            box.setInformativeText(message.splitlines()[0] if message else "")
            box.setDetailedText(message)
            box.exec()
