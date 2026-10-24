"""Install and uninstall Python versions."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from ..core import config, paths, python_versions, venvs
from ..core.interpreters import MANAGED, Interpreter
from ..core.python_versions import RemotePython
from ..core.venvs import VirtualEnv
from . import theme
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, loading_overlay, make_table, open_folder, selected_payload


class PythonsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self._available: list[RemotePython] = []
        self._updates: dict[str, RemotePython] = {}
        self._loaded_once = False

        # Installed interpreters
        self.installed = make_table(["Name", "Version", "Type", "Update", "Location"])
        self.installed.itemSelectionChanged.connect(self._update_buttons)
        self.installed_overlay = loading_overlay(self.installed)
        self.uninstall_btn = button("Uninstall", self.uninstall)
        self.folder_btn = button("Open folder", self.open_selected_folder)
        self.update_btn = button("Install update", self.install_update,
                                 "Install the newest patch release next to this Python")
        installed_box = QGroupBox("Installed Pythons")
        lay = QVBoxLayout(installed_box)
        lay.addWidget(self.installed)
        lay.addLayout(button_row(self.update_btn, self.uninstall_btn, self.folder_btn,
                                 button("Rescan system", lambda: self.state.refresh(include_system=True))))

        # Downloadable versions
        self.filter = QLineEdit(placeholderText="Filter, e.g. 3.12")
        self.filter.textChanged.connect(self._render_available)
        self.prerelease = QCheckBox("Pre-releases")
        self.prerelease.setChecked(bool(config.get("show_prereleases")))
        self.prerelease.toggled.connect(lambda v: (config.set("show_prereleases", v), self._render_available()))
        self.freethreaded = QCheckBox("Free-threaded")
        self.freethreaded.setChecked(bool(config.get("show_freethreaded")))
        self.freethreaded.toggled.connect(lambda v: (config.set("show_freethreaded", v), self._render_available()))
        self.releases = QSpinBox(minimum=1, maximum=30, value=int(config.get("release_count")))
        self.releases.setToolTip("How many build releases to scan. More releases list older patch versions.")
        self.releases.valueChanged.connect(lambda v: config.set("release_count", v))
        filters = QHBoxLayout()
        filters.addWidget(self.filter, 1)
        filters.addWidget(self.prerelease)
        filters.addWidget(self.freethreaded)
        filters.addWidget(QLabel("Releases:"))
        filters.addWidget(self.releases)
        filters.addWidget(button("Refresh list", self.load_available))

        self.available = make_table(["Version", "Variant", "Build", "Status"])
        self.available.itemSelectionChanged.connect(self._update_buttons)
        self.available_overlay = loading_overlay(self.available)
        self.available.doubleClicked.connect(lambda _: self.install())
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.download_btn = button("Download", self.download, "Download the archive without installing")
        self.install_btn = button("Install", self.install)
        available_box = QGroupBox("Available to download")
        lay = QVBoxLayout(available_box)
        lay.addLayout(filters)
        lay.addWidget(self.available)
        lay.addWidget(self.info)
        lay.addLayout(button_row(self.download_btn, self.install_btn))

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(installed_box)
        splitter.addWidget(available_box)
        root = QVBoxLayout(self)
        root.addWidget(splitter)

        state.changed.connect(self._render_installed)
        state.loading_changed.connect(
            lambda on: self.installed_overlay.start("Looking for installed Pythons…") if on and not self.installed.rowCount()
            else self.installed_overlay.stop())
        self._update_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.load_available()

    # Installed -------------------------------------------------------------

    def _render_installed(self) -> None:
        interpreters = self.state.interpreters(include_envs=False)
        self._updates = python_versions.updates(interpreters, self._available)
        rows = []
        for i in interpreters:
            update = self._updates.get(i.name)
            rows.append((i, (i.name, i.version, "Managed" if i.kind == MANAGED else "System",
                             update.version if update else "", str(i.executable))))
        fill_table(self.installed, rows)
        for row in range(self.installed.rowCount()):
            cell = self.installed.item(row, 3)
            if cell.text():
                theme.paint(cell, "warning")
        self._render_available()

    def _dependents(self, interp: Interpreter) -> list[VirtualEnv]:
        root = paths.pythons_dir() / interp.name
        return [e for e in self.state.envs if venvs.created_from(e, root)]

    def install_update(self) -> None:
        interp: Interpreter = selected_payload(self.installed)
        update = self._updates.get(interp.name) if interp else None
        if not update or update.key in python_versions.installed_keys():
            return

        def done(new: Interpreter) -> None:
            self.state.refresh()
            dependents = self._dependents(interp)
            message = f"Python {update.version} is installed next to {interp.version}."
            if not dependents:
                QMessageBox.information(self, "Python updated",
                                        message + "\n\nNo environment uses the old one; it can be uninstalled.")
                return
            message += ("\n\nThese environments still use Python " + interp.version + ":\n  "
                        + "\n  ".join(e.name for e in dependents)
                        + f"\n\nRebuild them on Python {update.version} now? Each keeps its folder and packages.")
            if QMessageBox.question(self, "Python updated", message) == QMessageBox.StandardButton.Yes:
                self.rebuild_envs(dependents, new)

        self.tasks.run(f"Installing Python {update.version}", lambda ctx: python_versions.install(update, ctx), done)

    def rebuild_envs(self, envs: list[VirtualEnv], base: Interpreter) -> None:
        """Rebuild ``envs`` on ``base`` one after another; one that fails is restored and the rest go on."""
        def rebuild(ctx) -> list[str]:
            failed = []
            for env in envs:
                ctx.check()
                try:
                    venvs.rebuild(env, base.executable, ctx)
                except Exception as exc:  # restored by rebuild; report it and carry on
                    ctx.log(f"Could not rebuild {env.name}: {exc}")
                    failed.append(env.name)
            return failed

        def done(failed: list[str]) -> None:
            self.state.refresh()
            if failed:
                QMessageBox.warning(self, "Rebuild environments",
                                    "These environments could not be rebuilt and were left as they were "
                                    "(see the Output panel):\n  " + "\n  ".join(failed))
            else:
                QMessageBox.information(self, "Rebuild environments",
                                        f"{len(envs)} environments now use Python {base.version}. "
                                        "The old Python can be uninstalled.")

        self.tasks.run(f"Rebuilding {len(envs)} environments on Python {base.version}", rebuild, done)

    def uninstall(self) -> None:
        interp: Interpreter = selected_payload(self.installed)
        if not interp or interp.kind != MANAGED:
            return
        dependents = self._dependents(interp)
        message = f"Uninstall Python {interp.version} ({interp.name})?"
        if dependents:
            message += ("\n\nThese virtual environments use it and will stop working:\n  "
                        + "\n  ".join(e.name for e in dependents))
        if QMessageBox.question(self, "Uninstall Python", message) != QMessageBox.StandardButton.Yes:
            return
        self.tasks.run(f"Uninstalling Python {interp.version}",
                       lambda ctx: python_versions.uninstall(interp, ctx),
                       lambda _: self.state.refresh())

    def open_selected_folder(self) -> None:
        interp = selected_payload(self.installed)
        if interp:
            open_folder(interp.executable.parent)

    # Available -------------------------------------------------------------

    def load_available(self) -> None:
        count = self.releases.value()
        self.info.setText("Loading available versions…")

        def failed(message: str) -> None:
            self.available_overlay.stop()
            self.info.setText(f"Could not load the version list: {message.splitlines()[0]}")

        if self.tasks.run("Fetching available Python versions",
                          lambda ctx: python_versions.list_available(count, ctx),
                          self._set_available, failed):
            self.available_overlay.start("Fetching the list of Python builds…")

    def _set_available(self, items: list[RemotePython]) -> None:
        self.available_overlay.stop()
        self._available = items
        self.info.setText(f"{len(items)} builds for {python_versions.target_triple()} "
                          f"from python-build-standalone. Installs go to {paths.pythons_dir()}")
        self._render_installed()

    def _render_available(self) -> None:
        installed = python_versions.installed_keys()
        text = self.filter.text().strip()
        rows = []
        for item in self._available:
            if item.prerelease and not self.prerelease.isChecked():
                continue
            if item.freethreaded and not self.freethreaded.isChecked():
                continue
            if text and not item.version.startswith(text):
                continue
            if item.key in installed:
                status = "Installed"
            elif python_versions.archive_path(item).exists():
                status = "Downloaded"
            else:
                status = ""
            rows.append((item, (item.version, item.variant, item.build, status)))
        fill_table(self.available, rows)
        self._update_buttons()

    def download(self) -> None:
        item: RemotePython = selected_payload(self.available)
        if item:
            self.tasks.run(f"Downloading Python {item.version}",
                           lambda ctx: python_versions.download(item, ctx),
                           lambda _: self._render_available())

    def install(self) -> None:
        item: RemotePython = selected_payload(self.available)
        if not item or item.key in python_versions.installed_keys():
            return
        self.tasks.run(f"Installing Python {item.version}",
                       lambda ctx: python_versions.install(item, ctx),
                       lambda _: self.state.refresh())

    def _update_buttons(self) -> None:
        interp = selected_payload(self.installed)
        self.uninstall_btn.setEnabled(bool(interp and interp.kind == MANAGED))
        self.folder_btn.setEnabled(interp is not None)
        update = self._updates.get(interp.name) if interp else None
        self.update_btn.setEnabled(bool(update) and update.key not in python_versions.installed_keys())
        item = selected_payload(self.available)
        installed = bool(item and item.key in python_versions.installed_keys())
        self.install_btn.setEnabled(bool(item) and not installed)
        self.download_btn.setEnabled(bool(item) and not installed)
