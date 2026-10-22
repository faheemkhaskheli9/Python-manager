"""Create and manage virtual environments."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..core import paths, venvs
from ..core.venvs import VirtualEnv
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, make_table, open_folder, selected_payload


class CreateEnvDialog(QDialog):
    def __init__(self, state: AppState, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Create virtual environment")
        self.setMinimumWidth(520)
        self.name = QLineEdit(placeholderText="my-project")
        self.base = QComboBox()
        for interp in state.interpreters(include_envs=False):
            self.base.addItem(interp.label, interp)
        self.location = QLineEdit(str(paths.envs_dir()))
        loc_row = QHBoxLayout()
        loc_row.addWidget(self.location, 1)
        loc_row.addWidget(button("Browse…", self._browse))
        self.with_pip = QCheckBox("Install pip")
        self.with_pip.setChecked(True)
        self.upgrade = QCheckBox("Upgrade pip to the latest version")
        self.with_pip.toggled.connect(self.upgrade.setEnabled)
        self.system_site = QCheckBox("Give access to the base interpreter's site-packages")

        form = QFormLayout()
        form.addRow("Name:", self.name)
        form.addRow("Python:", self.base)
        form.addRow("Location:", loc_row)
        form.addRow(self.with_pip)
        form.addRow(self.upgrade)
        form.addRow(self.system_site)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        if self.base.count() == 0:
            layout.addWidget(QLabel("No Python found. Install one on the Python Versions page first."))
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Parent folder", self.location.text())
        if folder:
            self.location.setText(folder)

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not venvs.NAME_RE.match(name):
            QMessageBox.warning(self, "Invalid name", "Use letters, digits, '.', '_' or '-' only.")
            return
        if self.base.currentData() is None:
            return
        if (Path(self.location.text()) / name).exists():
            QMessageBox.warning(self, "Already exists", "A folder with that name already exists there.")
            return
        self.accept()


class VenvsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager, manage_packages: Callable[[Path], None]):
        super().__init__()
        self.state, self.tasks, self.manage_packages = state, tasks, manage_packages

        self.table = make_table(["Name", "Python", "Location", "Base interpreter"], stretch=2)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self._manage())
        self.activate_hint = QLineEdit(readOnly=True, placeholderText="Activation command")
        self.unregister_btn = button("Remove from list", self._unregister, "Forget the environment without deleting files")
        self.selection_buttons = [
            button("Manage packages", self._manage),
            button("Open terminal", self._terminal, "Open a terminal with the environment activated"),
            button("Open folder", lambda: self._with_selected(lambda e: open_folder(e.path))),
            self.unregister_btn,
            button("Delete", self._delete),
        ]
        layout = QVBoxLayout(self)
        layout.addLayout(button_row(button("Create…", self.create), button("Add existing…", self._add_existing),
                                    button("Refresh", lambda: self.state.refresh())))
        layout.addWidget(self.table)
        layout.addWidget(self.activate_hint)
        layout.addLayout(button_row(*self.selection_buttons))
        state.changed.connect(self._render)
        self._update_buttons()

    def _render(self) -> None:
        rows = [(e, (e.name, e.version, str(e.path), e.base or "?")) for e in self.state.envs]
        fill_table(self.table, rows)
        self._update_buttons()

    def _selected(self) -> VirtualEnv:
        return selected_payload(self.table)

    def _with_selected(self, fn) -> None:
        env = self._selected()
        if env:
            fn(env)

    def _update_buttons(self) -> None:
        env = self._selected()
        for btn in self.selection_buttons:
            btn.setEnabled(env is not None)
        if env:
            self.unregister_btn.setEnabled(not env.managed)
        self.activate_hint.setText(venvs.activation_command(env) if env else "")

    def create(self) -> None:
        dialog = CreateEnvDialog(self.state, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, base = dialog.name.text().strip(), dialog.base.currentData()
        location = Path(dialog.location.text())
        options = dict(with_pip=dialog.with_pip.isChecked(), upgrade_deps=dialog.upgrade.isChecked(),
                       system_site_packages=dialog.system_site.isChecked())
        self.tasks.run(f"Creating environment {name}",
                       lambda ctx: venvs.create(name, base.executable, location, ctx=ctx, **options),
                       lambda _: self.state.refresh())

    def _add_existing(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a virtual environment folder")
        if not folder:
            return
        try:
            venvs.register(Path(folder))
        except ValueError as exc:
            QMessageBox.warning(self, "Not a virtual environment", str(exc))
            return
        self.state.refresh()

    def _manage(self) -> None:
        self._with_selected(lambda e: self.manage_packages(e.interpreter().executable))

    def _terminal(self) -> None:
        env = self._selected()
        if not env:
            return
        try:
            venvs.open_terminal(env)
        except OSError as exc:
            QMessageBox.warning(self, "Open terminal", str(exc))

    def _unregister(self) -> None:
        env = self._selected()
        if env and not env.managed:
            venvs.unregister(env.path)
            self.state.refresh()

    def _delete(self) -> None:
        env = self._selected()
        if not env:
            return
        answer = QMessageBox.question(
            self, "Delete environment", f"Permanently delete “{env.name}”?\n\n{env.path}")
        if answer == QMessageBox.StandardButton.Yes:
            self.tasks.run(f"Deleting environment {env.name}", lambda ctx: venvs.delete(env, ctx),
                           lambda _: self.state.refresh())
