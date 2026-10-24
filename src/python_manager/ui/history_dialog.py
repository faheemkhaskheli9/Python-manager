"""Snapshots of an environment's packages taken before each change, and restoring one."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget

from ..core import history
from ..core.packages import Package
from .tasks import TaskManager
from .widgets import fill_table, make_table, selected_payload


def _when(snap: history.Snapshot) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.time))


class HistoryDialog(QDialog):
    def __init__(self, python: Path, env_name: str, current: list[Package], tasks: TaskManager,
                 parent: QWidget = None):
        super().__init__(parent)
        self.python, self.env_name, self.current, self.tasks = python, env_name, current, tasks
        self.changed = False  # packages were restored, so the caller should reload
        self.setWindowTitle(f"Package history · {env_name}")
        self.resize(760, 520)

        self.table = make_table(["Taken", "Before", "Packages", "Restoring changes"], stretch=1)
        self.table.itemSelectionChanged.connect(self._update)
        self.details = QLabel()
        self.details.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.restore_btn = buttons.addButton("Restore", QDialogButtonBox.ButtonRole.ActionRole)
        self.restore_btn.setToolTip("Install the snapshot's versions and remove packages it did not have")
        self.restore_btn.clicked.connect(self.restore)
        self.clear_btn = buttons.addButton("Clear history", QDialogButtonBox.ButtonRole.ResetRole)
        self.clear_btn.clicked.connect(self.clear)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("A snapshot is saved before each install, upgrade or uninstall made with the app."))
        layout.addWidget(self.table)
        layout.addWidget(self.details)
        layout.addWidget(buttons)
        self._render()

    def _render(self) -> None:
        rows = []
        for snap in history.snapshots(self.python):
            todo = history.plan(self.current, snap)
            change = "none" if todo.empty else f"{len(todo.install)} install, {len(todo.remove)} remove"
            rows.append((snap, ((_when(snap), snap.time), snap.action, (len(snap.packages), len(snap.packages)),
                                change)))
        fill_table(self.table, rows)
        self.clear_btn.setEnabled(bool(rows))
        if rows:
            self.table.selectRow(0)
        self._update()

    def _update(self) -> None:
        snap = selected_payload(self.table)
        todo = history.plan(self.current, snap) if snap else None
        self.restore_btn.setEnabled(bool(todo and not todo.empty))
        if not snap:
            self.details.setText("No snapshots yet." if not self.table.rowCount() else "")
        elif todo.empty:
            self.details.setText("The packages match this snapshot.")
        else:
            parts = []
            if todo.install:
                parts.append("Install: " + ", ".join(todo.install))
            if todo.remove:
                parts.append("Remove: " + ", ".join(todo.remove))
            self.details.setText("\n".join(parts))

    def restore(self) -> None:
        snap = selected_payload(self.table)
        if not snap:
            return
        todo = history.plan(self.current, snap)
        text = f"Restore {self.env_name} to {_when(snap)}?\n\n{self.details.text()}"
        if todo.empty or QMessageBox.question(self, "Restore snapshot", text) != QMessageBox.StandardButton.Yes:
            return

        def done(_) -> None:
            self.changed = True
            self.accept()

        self.tasks.run(f"Restoring packages ({self.env_name})", lambda ctx: history.restore(self.python, snap, ctx),
                       done)

    def clear(self) -> None:
        if QMessageBox.question(self, "Clear history", f"Delete every snapshot of {self.env_name}?") \
                == QMessageBox.StandardButton.Yes:
            history.clear(self.python)
            self._render()
