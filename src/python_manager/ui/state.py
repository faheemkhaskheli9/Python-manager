"""Shared cache of known interpreters and environments."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core import python_versions, venvs
from ..core.interpreters import Interpreter, find_system_pythons
from .tasks import TaskManager


class AppState(QObject):
    changed = Signal()

    def __init__(self, tasks: TaskManager):
        super().__init__(tasks)
        self._tasks = tasks
        self.managed: list[Interpreter] = []
        self.system: list[Interpreter] = []
        self.envs: list[venvs.VirtualEnv] = []
        self.loading = False

    def refresh(self, include_system: bool = False) -> None:
        """Reload lists in the background. System discovery is slow, so it is opt-in."""
        scan_system = include_system or not self.system

        def load(_ctx):
            system = find_system_pythons() if scan_system else self.system
            return python_versions.list_installed(), system, venvs.list_envs()

        def done(result):
            self.managed, self.system, self.envs = result
            self.loading = False
            self.changed.emit()

        def failed(_msg):
            self.loading = False

        self.loading = True
        self._tasks.run("Scanning interpreters", load, done, failed, foreground=False)

    def interpreters(self, include_envs: bool = True) -> list[Interpreter]:
        result = list(self.managed) + list(self.system)
        if include_envs:
            result += [e.interpreter() for e in self.envs if e.valid]
        return result
