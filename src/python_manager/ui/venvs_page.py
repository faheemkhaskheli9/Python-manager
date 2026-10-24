"""Create and manage virtual environments."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..core import conda, config, favorites, kernels, packages, paths, venvs
from ..core.venvs import VirtualEnv
from .export_dialog import export_environment
from .kernels_dialog import KernelsDialog
from .state import AppState
from .tasks import TaskManager
from .upgrade_dialog import update_all
from .widgets import button, button_row, fill_table, loading_overlay, make_table, open_folder, selected_payload


FILE_FILTER = "requirements.txt or pyproject.toml (*.txt *.toml);;All files (*)"


class CreateEnvDialog(QDialog):
    """Create a new environment, or clone ``source`` when given."""

    def __init__(self, state: AppState, parent: QWidget, source: Optional[VirtualEnv] = None,
                 packages_file: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Clone {source.name}" if source else "Create virtual environment")
        self.setMinimumWidth(520)
        self.name = QLineEdit(f"{source.name}-copy" if source else "", placeholderText="my-project")
        self.base = QComboBox()
        for interp in state.interpreters(include_envs=False):
            self.base.addItem(interp.label, interp)
        if source:
            self._select_base(venvs.base_executable(source))
        elif config.get("default_python"):
            self._select_base(Path(config.get("default_python")))
        self.location = QLineEdit(str(source.path.parent if source else config.get("envs_location") or paths.envs_dir()))
        loc_row = QHBoxLayout()
        loc_row.addWidget(self.location, 1)
        loc_row.addWidget(button("Browse…", self._browse))
        self.packages_file = QLineEdit(packages_file, placeholderText="Optional requirements.txt or pyproject.toml")
        file_row = QHBoxLayout()
        file_row.addWidget(self.packages_file, 1)
        file_row.addWidget(button("Browse…", self._browse_file))
        self.with_pip = QCheckBox("Install pip")
        self.with_pip.setChecked(True)
        self.upgrade = QCheckBox("Upgrade pip to the latest version")
        self.with_pip.toggled.connect(self.upgrade.setEnabled)
        self.system_site = QCheckBox("Give access to the base interpreter's site-packages")
        count = len(favorites.list_favorites())
        self.install_favorites = QCheckBox(f"Install favourite packages ({count})")
        self.install_favorites.setEnabled(count > 0)
        self.with_pip.toggled.connect(lambda on: self.install_favorites.setEnabled(on and count > 0))

        form = QFormLayout()
        form.addRow("Name:", self.name)
        form.addRow("Python:", self.base)
        form.addRow("Location:", loc_row)
        if source:
            form.addRow("Packages:", QLabel(f"Same as {source.name}"))
        else:
            form.addRow("Packages from:", file_row)
        form.addRow(self.with_pip)
        form.addRow(self.upgrade)
        form.addRow(self.system_site)
        form.addRow(self.install_favorites)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        if self.base.count() == 0:
            layout.addWidget(QLabel("No Python found. Install one on the Python Versions page first."))
        layout.addWidget(buttons)

    def _select_base(self, executable: Optional[Path]) -> None:
        if executable is None:
            return
        target = os.path.realpath(executable)
        for i in range(self.base.count()):
            if os.path.realpath(self.base.itemData(i).executable) == target:
                self.base.setCurrentIndex(i)
                return

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Install packages from", "", FILE_FILTER)
        if path:
            self.packages_file.setText(path)

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
        file = self.packages_file.text().strip()
        if file and not Path(file).is_file():
            QMessageBox.warning(self, "File not found", f"{file} does not exist.")
            return
        self.accept()


class VenvsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager, manage_packages: Callable[[Path], None]):
        super().__init__()
        self.state, self.tasks, self.manage_packages = state, tasks, manage_packages

        self.table = make_table(["Name", "Python", "Updates", "Jupyter kernel", "Location", "Base interpreter"],
                                stretch=4)
        self._kernels: list[kernels.Kernel] = []
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self._manage())
        self.overlay = loading_overlay(self.table)
        self.activate_hint = QLineEdit(readOnly=True, placeholderText="Activation command")
        self.kernel_btn = button("Add Jupyter kernel", self._toggle_kernel,
                                 "Make the environment selectable in Jupyter (installs ipykernel if needed)")
        self.unregister_btn = button("Remove from list", self._unregister, "Forget the environment without deleting files")
        self.selection_buttons = [
            button("Manage packages", self._manage),
            button("Clone…", self.clone, "New environment with the same packages"),
            button("Rebuild…", self.rebuild,
                   "Recreate the environment in place on another Python with the same packages"),
            button("Update all…", self._update_all, "Choose which outdated packages to update"),
            button("Export…", self._export, "Save as requirements.txt, pylock.toml or pyproject.toml"),
            button("Open terminal", self._terminal, "Open a terminal with the environment activated"),
            self.kernel_btn,
            button("Open folder", lambda: self._with_selected(lambda e: open_folder(e.path))),
            self.unregister_btn,
            button("Delete", self._delete),
        ]
        layout = QVBoxLayout(self)
        layout.addLayout(button_row(button("Create…", lambda: self.create()),
                                    button("Create from file…", self._create_from_file,
                                           "New environment from a requirements.txt or pyproject.toml"),
                                    button("Add existing…", self._add_existing),
                                    button("Jupyter kernels…", self._kernels_dialog,
                                           "All installed kernels; remove the ones whose Python is gone"),
                                    button("Refresh", lambda: self.state.refresh())))
        layout.addWidget(self.table)
        layout.addWidget(self.activate_hint)
        layout.addLayout(button_row(*self.selection_buttons))

        # Conda environments are listed so their packages can be inspected; conda manages them.
        self.conda_table = make_table(["Name", "Python", "Location"], stretch=2)
        self.conda_table.itemSelectionChanged.connect(self._update_conda_buttons)
        self.conda_table.doubleClicked.connect(lambda _: self._conda_packages())
        self.conda_hint = QLineEdit(readOnly=True, placeholderText="Activation command")
        self.conda_buttons = [
            button("Show packages", self._conda_packages, "Packages are listed read-only; change them with conda"),
            button("Open folder", lambda: self._with_conda(lambda e: open_folder(e.path))),
        ]
        self.conda_box = QGroupBox("Conda environments (read-only)")
        conda_layout = QVBoxLayout(self.conda_box)
        conda_layout.addWidget(self.conda_table)
        conda_layout.addWidget(self.conda_hint)
        conda_layout.addLayout(button_row(*self.conda_buttons))
        self.conda_box.hide()
        layout.addWidget(self.conda_box)
        state.changed.connect(self._render)
        state.health_changed.connect(self._render)
        state.loading_changed.connect(
            lambda on: self.overlay.start("Looking for environments…") if on and not self.table.rowCount()
            else self.overlay.stop())
        self._update_buttons()

    def _status(self, env: VirtualEnv) -> str:
        if venvs.is_broken(env):
            return "⚠ base Python missing"
        if self.state.health_checking:
            return "checking…"
        report = self.state.health.get(str(env.executable))
        return report.summary if report else ""

    def _render(self) -> None:
        self._kernels = kernels.list_kernels()
        rows = [(e, (e.name, e.version, self._status(e), self._kernel_names(e), str(e.path), e.base or "?"))
                for e in self.state.envs]
        fill_table(self.table, rows)
        self.table.setToolTip("Updates: result of the last scheduled check (File → Check environments now)")
        self._update_buttons()
        fill_table(self.conda_table, [(e, (e.name, e.version or "no Python", str(e.path)))
                                      for e in self.state.conda_envs])
        self.conda_box.setVisible(bool(self.state.conda_envs))
        self._update_conda_buttons()

    def _env_kernels(self, env: VirtualEnv) -> list[kernels.Kernel]:
        return kernels.kernels_for(env.executable, self._kernels)

    def _kernel_names(self, env: VirtualEnv) -> str:
        return ", ".join(k.display_name for k in self._env_kernels(env))

    def _with_conda(self, fn) -> None:
        env = selected_payload(self.conda_table)
        if env:
            fn(env)

    def _update_conda_buttons(self) -> None:
        env: Optional[conda.CondaEnv] = selected_payload(self.conda_table)
        self.conda_buttons[0].setEnabled(bool(env and env.valid))
        self.conda_buttons[1].setEnabled(env is not None)
        self.conda_hint.setText(conda.activation_command(env) if env else "")

    def _conda_packages(self) -> None:
        self._with_conda(lambda e: e.valid and self.manage_packages(e.executable))

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
            self.kernel_btn.setText("Remove Jupyter kernel" if self._env_kernels(env) else "Add Jupyter kernel")
            self.kernel_btn.setEnabled(env.valid or bool(self._env_kernels(env)))
        self.activate_hint.setText(venvs.activation_command(env) if env else "")

    def create(self, source: Optional[VirtualEnv] = None, packages_file: str = "") -> None:
        dialog = CreateEnvDialog(self.state, self, source, packages_file)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, base = dialog.name.text().strip(), dialog.base.currentData()
        location = Path(dialog.location.text())
        options = dict(with_pip=dialog.with_pip.isChecked(), upgrade_deps=dialog.upgrade.isChecked(),
                       system_site_packages=dialog.system_site.isChecked())
        file = dialog.packages_file.text().strip()
        if file and not source:
            options["packages_file"] = Path(file)
        extras = favorites.list_favorites() if dialog.install_favorites.isEnabled() \
            and dialog.install_favorites.isChecked() else []

        def create(ctx):
            if source:
                env = venvs.clone(source, name, base.executable, location, ctx=ctx, **options)
            else:
                env = venvs.create(name, base.executable, location, ctx=ctx, **options)
            if extras:
                packages.install(env.executable, extras, ctx)
            return env

        verb = f"Cloning {source.name} to" if source else "Creating environment"
        self.tasks.run(f"{verb} {name}", create, lambda _: self.state.refresh())

    def clone(self) -> None:
        env = self._selected()
        if env:
            self.create(source=env)

    def rebuild(self) -> None:
        env = self._selected()
        if not env:
            return
        bases = self.state.interpreters(include_envs=False)
        if not bases:
            QMessageBox.information(self, "Rebuild", "No Python found. Install one on the Python Versions page first.")
            return
        current = venvs.base_executable(env)
        index = next((i for i, b in enumerate(bases)
                      if current and os.path.realpath(b.executable) == os.path.realpath(current)), 0)
        label, ok = QInputDialog.getItem(
            self, f"Rebuild {env.name}",
            f"Recreate {env.name} (Python {env.version}) in the same folder with the same packages on:",
            [b.label for b in bases], index, False)
        if not ok:
            return
        base = bases[[b.label for b in bases].index(label)]
        self.tasks.run(f"Rebuilding {env.name} on Python {base.version}",
                       lambda ctx: venvs.rebuild(env, base.executable, ctx), lambda _: self.state.refresh())

    def _create_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Create environment from", "", FILE_FILTER)
        if path:
            self.create(packages_file=path)

    def _export(self) -> None:
        env = self._selected()
        if env:
            export_environment(self, self.tasks, env.executable, env.name, env.version)

    def _update_all(self) -> None:
        env = self._selected()
        if env:
            update_all(self, self.state, self.tasks, env.executable, env.name, lambda: None, self.overlay)

    def _toggle_kernel(self) -> None:
        env = self._selected()
        if not env:
            return
        existing = self._env_kernels(env)
        if existing:
            names = "\n".join(f"{k.display_name} ({k.path})" for k in existing)
            if QMessageBox.question(self, "Remove Jupyter kernel", f"Remove the kernel of {env.name}?\n\n{names}") \
                    != QMessageBox.StandardButton.Yes:
                return

            def remove(ctx):
                for kernel in existing:
                    kernels.remove(kernel, ctx)

            self.tasks.run(f"Removing the Jupyter kernel of {env.name}", remove, lambda _: self._render())
            return
        display, ok = QInputDialog.getText(self, "Add Jupyter kernel", "Name shown in Jupyter:",
                                           text=f"Python {env.version} ({env.name})")
        if not ok or not display.strip():
            return
        name = kernels.kernel_name(env.name, [k.name for k in self._kernels])
        self.tasks.run(f"Adding a Jupyter kernel for {env.name}",
                       lambda ctx: kernels.register(env.executable, name, display.strip(), ctx),
                       lambda _: self._render())

    def _kernels_dialog(self) -> None:
        KernelsDialog(self.tasks, self).exec()
        self._render()

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
