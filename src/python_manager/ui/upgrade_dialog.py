"""Confirm which outdated packages to upgrade, then upgrade them and report what changed."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ..core import packages
from ..core.packages import Upgrade, UpgradeResult
from .state import AppState
from .tasks import TaskManager
from .widgets import LoadingOverlay, button, button_row, fill_table, make_table

MAJOR = "major version"
HELD_COLOR = "#9e9e9e"
MAJOR_COLOR = "#ef6c00"


class UpgradeDialog(QDialog):
    def __init__(self, upgrades: list[Upgrade], env_name: str, held: Optional[dict[str, str]] = None, parent=None):
        super().__init__(parent)
        held = held or {}
        self.setWindowTitle(f"Update packages · {env_name}")
        self.resize(760, 460)

        majors = sum(u.major for u in upgrades)
        text = f"{len(upgrades)} package{'s' * (len(upgrades) != 1)} in {env_name} can be updated."
        if majors:
            text += f" {majors} {'are' if majors != 1 else 'is a'} major version{'s' * (majors != 1)}, " \
                    "which may contain breaking changes."
        if held:
            text += f" {len(held)} {'are' if len(held) != 1 else 'is'} held back by the project's requirements " \
                    "and left unticked."
        summary = QLabel(text)
        summary.setWordWrap(True)

        self.table = make_table(["Package", "Installed", "Latest", "Note"], stretch=3)
        rows = []
        for u in upgrades:
            note = f"held back by {held[u.name]}" if u.name in held else MAJOR if u.major else ""
            rows.append((u, (u.name, u.current, u.latest, note)))
        fill_table(self.table, rows)
        self.table.setSortingEnabled(False)  # rows are read back by index
        for row, u in enumerate(upgrades):
            item = self.table.item(row, 0)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if u.name in held else Qt.CheckState.Checked)
            color = HELD_COLOR if u.name in held else MAJOR_COLOR if u.major else ""
            if color:
                self.table.item(row, 3).setForeground(QBrush(QColor(color)))
        self.table.itemChanged.connect(lambda _: self._update_count())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok: QPushButton = buttons.addButton("Update", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table)
        layout.addLayout(button_row(button("Select all", lambda: self._check_all(True)),
                                    button("Select none", lambda: self._check_all(False)),
                                    button("Skip major versions", self._skip_major,
                                           "Untick updates that may contain breaking changes")))
        layout.addWidget(buttons)
        self._update_count()

    def _items(self):
        return [self.table.item(row, 0) for row in range(self.table.rowCount())]

    def _check_all(self, checked: bool) -> None:
        for item in self._items():
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _skip_major(self) -> None:
        for item in self._items():
            if item.data(Qt.ItemDataRole.UserRole).major:
                item.setCheckState(Qt.CheckState.Unchecked)

    def selected(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole).name for item in self._items()
                if item.checkState() == Qt.CheckState.Checked]

    def _update_count(self) -> None:
        count = len(self.selected())
        self.ok.setText(f"Update {count} package{'s' * (count != 1)}")
        self.ok.setEnabled(count > 0)


def _report(parent: QWidget, env_name: str, result: UpgradeResult) -> None:
    updated = [c for c in result.changed if c.current]
    added = [c for c in result.changed if not c.current]
    lines = [f"Updated {len(updated)} package{'s' * (len(updated) != 1)} in {env_name}."]
    if added:
        lines.append("New dependencies: " + ", ".join(f"{c.name} {c.latest}" for c in added) + ".")
    if result.conflicts:
        lines.append("\nSome installed packages now have unmet requirements:\n" + "\n".join(result.conflicts[:10]))
        QMessageBox.warning(parent, "Update packages", "\n".join(lines))
    else:
        QMessageBox.information(parent, "Update packages", "\n".join(lines))


def update_all(parent: QWidget, state: AppState, tasks: TaskManager, python: Path, env_name: str,
               on_done: Callable[[], None], overlay: Optional[LoadingOverlay] = None,
               requirements: Optional[Callable[[], list[str]]] = None) -> None:
    """Find outdated packages, let the user pick which to update, update them and report the result.

    ``requirements`` returns a project's requirements; updates they exclude are left unticked.
    """
    def found(result):
        upgrades, held = result
        if overlay:
            overlay.stop()
        if not upgrades:
            QMessageBox.information(parent, "Update packages", f"All packages in {env_name} are up to date.")
            return
        dialog = UpgradeDialog(upgrades, env_name, held, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        names = dialog.selected()

        def finished(result: UpgradeResult):
            state.packages_changed(python, result.installed)
            on_done()
            _report(parent, env_name, result)

        tasks.run(f"Updating {len(names)} packages ({env_name})",
                  lambda ctx: packages.upgrade(python, names, ctx), finished)

    def failed(message: str):
        if overlay:
            overlay.stop()
        if message != "Cancelled":
            QMessageBox.warning(parent, "Update packages", message.splitlines()[0] if message else "Check failed")

    def check(_ctx):
        from ..core import projects

        upgrades = packages.upgrades(python)
        held = projects.held_back(upgrades, requirements()) if requirements and upgrades else {}
        return upgrades, held

    if tasks.run(f"Checking for updates ({env_name})", check, found, failed, foreground=False) and overlay:
        overlay.start(f"Checking {env_name} for updates…")
