"""Shared cache of known interpreters and environments."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core import conda, health, packages, python_versions, venvs
from ..core.interpreters import Interpreter, find_system_pythons
from .tasks import TaskManager


class AppState(QObject):
    changed = Signal()
    health_changed = Signal()
    loading_changed = Signal(bool)

    def __init__(self, tasks: TaskManager):
        super().__init__(tasks)
        self._tasks = tasks
        self.managed: list[Interpreter] = []
        self.system: list[Interpreter] = []
        self.envs: list[venvs.VirtualEnv] = []
        self.conda_envs: list[conda.CondaEnv] = []
        self.loading = False
        self.health: dict[str, health.Report] = health.load()  # keyed by interpreter path
        self.health_checking = False

    def set_health(self, reports: dict[str, health.Report]) -> None:
        self.health = reports
        self.health_checking = False
        self.health_changed.emit()

    def packages_changed(self, executable: Path, installed: list[packages.Package]) -> None:
        """Drop findings of the last check that no longer apply after packages were changed."""
        report = self.health.get(str(executable))
        if report:
            self.health = {**self.health, str(executable): report.current(installed)}
            health.save(self.health)
            self.health_changed.emit()

    def set_health_checking(self, checking: bool) -> None:
        self.health_checking = checking
        self.health_changed.emit()

    def refresh(self, include_system: bool = False) -> None:
        """Reload lists in the background. System discovery is slow, so it is opt-in."""
        scan_system = include_system or not self.system

        def load(_ctx):
            system = find_system_pythons() if scan_system else self.system
            return python_versions.list_installed(), system, venvs.list_envs(), conda.list_envs()

        def done(result):
            self.managed, self.system, self.envs, self.conda_envs = result
            self.loading = False
            self.loading_changed.emit(False)
            self.changed.emit()

        def failed(_msg):
            self.loading = False
            self.loading_changed.emit(False)

        self.loading = True
        self.loading_changed.emit(True)
        self._tasks.run("Scanning interpreters", load, done, failed, foreground=False)

    def interpreters(self, include_envs: bool = True) -> list[Interpreter]:
        result = list(self.managed) + list(self.system)
        if include_envs:
            result += [e.interpreter() for e in self.envs if e.valid]
            # A conda base on PATH is already listed as a system Python.
            known = {os.path.realpath(i.executable) for i in result}
            result += [e.interpreter() for e in self.conda_envs
                       if e.valid and os.path.realpath(e.executable) not in known]
        return result

    def checked_interpreters(self) -> list[Interpreter]:
        """What scheduled checks cover: environments and Pythons installed by the app, not system ones."""
        return list(self.managed) + [e.interpreter() for e in self.envs if e.valid]
