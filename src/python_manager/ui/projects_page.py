"""Project folders: their environment, how it compares with the requirements, and syncing it."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import projects, venvs
from ..core.projects import Check, Project
from .export_dialog import export_environment
from .state import AppState
from .tasks import TaskManager
from .upgrade_dialog import update_all
from .widgets import button, button_row, color_rows, fill_table, loading_overlay, make_table, open_folder

STATUS_COLORS = {projects.MISSING: "#c62828", projects.MISMATCH: "#ef6c00", projects.OK: "#2e7d32"}
UV_SYNC = "uv.lock (uv sync)"


class ProjectsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager, manage_packages: Callable[[Path], None]):
        super().__init__()
        self.state, self.tasks, self.manage_packages = state, tasks, manage_packages
        self._generation = 0

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show())
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.addWidget(self.list)
        llay.addLayout(button_row(button("Add folder…", self.add_folder,
                                         "A folder with pyproject.toml, requirements.txt or uv.lock"),
                                  button("Remove", self.remove, "Remove from the list without deleting files")))

        self.path = QLabel()
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.files = QLabel()
        self.env = QLabel()
        self.env.setWordWrap(True)
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(lambda _: self.check())
        form = QFormLayout()
        form.addRow("Folder:", self.path)
        form.addRow("Files:", self.files)
        form.addRow("Environment:", self.env)
        form.addRow("Requirements:", self.source)

        self.table = make_table(["Requirement", "Installed", "Status"], stretch=0)
        self.overlay = loading_overlay(self.table)
        self.summary = QLabel()
        self.create_btn = button("Create environment…", self.create_env, "Create .venv in the project and sync it")
        self.sync_btn = button("Sync", self.sync, "Install the requirements into the environment")
        self.env_buttons = [
            self.sync_btn,
            button("Check", self.check, "Compare the environment with the requirements again"),
            button("Update all…", self._update_all, "Choose which outdated packages to update"),
            button("Export…", self._export, "Freeze the environment to requirements.txt or pylock.toml"),
            button("Manage packages", self._manage),
            button("Open terminal", self._terminal),
        ]
        self.folder_btn = button("Open folder", lambda: self._with_project(lambda p: open_folder(p.path)))
        details = QGroupBox("Project")
        dlay = QVBoxLayout(details)
        dlay.addLayout(form)
        dlay.addWidget(self.table)
        dlay.addWidget(self.summary)
        dlay.addLayout(button_row(self.create_btn, *self.env_buttons, self.folder_btn))

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(details)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        root = QVBoxLayout(self)
        root.addWidget(splitter)
        self._render_list()

    # Project list ----------------------------------------------------------

    def _render_list(self, select: Optional[Path] = None) -> None:
        self.list.clear()
        for project in projects.list_projects():
            item = QListWidgetItem(project.name)
            item.setToolTip(str(project.path))
            item.setData(Qt.ItemDataRole.UserRole, project)
            self.list.addItem(item)
            if select and project.path == select:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show()

    def project(self) -> Optional[Project]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _with_project(self, fn) -> None:
        project = self.project()
        if project:
            fn(project)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a project folder")
        if folder:
            self.add(Path(folder))

    def add(self, folder: Path) -> None:
        project = projects.add(folder)
        if not project.files:
            QMessageBox.information(self, "Project", "No pyproject.toml, requirements.txt or uv.lock found "
                                                     "in that folder; you can still create an environment.")
        self._render_list(project.path)

    def remove(self) -> None:
        project = self.project()
        if project:
            projects.remove(project.path)
            self._render_list()

    # Details ---------------------------------------------------------------

    def _show(self) -> None:
        project = self.project()
        fill_table(self.table, [])
        self.summary.clear()
        self.source.blockSignals(True)
        self.source.clear()
        if project is None:
            for label in (self.path, self.files, self.env):
                label.setText("—")
            self.source.blockSignals(False)
            self._update_buttons(None, None)
            return
        env = project.env()
        self.path.setText(str(project.path))
        self.files.setText(", ".join(project.files) or "none")
        self.env.setText(f"{env.path.name} (Python {env.version})" if env else "none")
        for path in project.sources():
            self.source.addItem(path.name, path)
        if projects.can_uv_sync(project):
            self.source.insertItem(0, UV_SYNC, None)
            self.source.setCurrentIndex(0)
        self.source.blockSignals(False)
        self._update_buttons(project, env)
        self.check()

    def _update_buttons(self, project: Optional[Project], env: Optional[venvs.VirtualEnv]) -> None:
        self.create_btn.setEnabled(project is not None and env is None)
        for btn in self.env_buttons:
            btn.setEnabled(env is not None)
        self.sync_btn.setEnabled(env is not None and self.source.count() > 0)
        self.folder_btn.setEnabled(project is not None)

    def _source(self) -> Optional[Path]:
        return self.source.currentData()

    def _compare_source(self, project: Project) -> Optional[Path]:
        """uv sync installs from the lock file; its declared requirements are in pyproject.toml."""
        if self.source.currentText() == UV_SYNC:
            return project.path / projects.PYPROJECT
        return self._source()

    def check(self) -> None:
        project = self.project()
        env = project.env() if project else None
        source = self._compare_source(project) if project else None
        self._generation += 1
        generation = self._generation
        if env is None or source is None or not source.is_file():
            self.overlay.stop()
            fill_table(self.table, [])
            self.summary.setText("Create an environment to compare it with the requirements." if project and not env
                                 else "")
            return
        self.summary.setText("Comparing…")
        self.overlay.start(f"Comparing {env.name} with {source.name}…")

        def done(checks: list[Check]):
            if generation != self._generation:
                return
            self.overlay.stop()
            fill_table(self.table, [(c, (c.requirement, c.installed or "—", c.status)) for c in checks])
            color_rows(self.table, 2, STATUS_COLORS)
            missing = sum(c.status == projects.MISSING for c in checks)
            wrong = sum(c.status == projects.MISMATCH for c in checks)
            if not checks:
                self.summary.setText(f"{source.name} lists no requirements.")
            elif missing or wrong:
                self.summary.setText(f"{missing} missing, {wrong} with the wrong version. Press Sync to install them.")
            else:
                self.summary.setText(f"All {len(checks)} requirements are satisfied.")

        def failed(message: str):
            if generation == self._generation:
                self.overlay.stop()
                self.summary.setText(f"Could not compare: {message.splitlines()[0]}")

        self.tasks.run(f"Comparing {project.name}",
                       lambda _: projects.compare(projects.read_requirements(source), env.executable),
                       done, failed, foreground=False)

    # Actions ---------------------------------------------------------------

    def create_env(self) -> None:
        project = self.project()
        if not project:
            return
        bases = self.state.interpreters(include_envs=False)
        if not bases:
            QMessageBox.information(self, "No Python", "Install a Python on the Python Versions page first.")
            return
        label, ok = QInputDialog.getItem(self, "Create environment",
                                         f"Python for {project.name}/.venv:", [b.label for b in bases], 0, False)
        if not ok:
            return
        base = bases[[b.label for b in bases].index(label)]

        def done(_):
            self.state.refresh()
            self._show()

        self.tasks.run(f"Creating {project.name}/.venv",
                       lambda ctx: projects.create_env(project, base.executable, ctx), done)

    def sync(self) -> None:
        project = self.project()
        if not project or not project.env():
            return
        source = self._source()
        self.tasks.run(f"Syncing {project.name}", lambda ctx: projects.sync(project, source, ctx),
                       lambda _: self.check())

    def _update_all(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if not env:
            return
        source = self._compare_source(project)
        requirements = (lambda: projects.read_requirements(source)) if source and source.is_file() else None
        update_all(self, self.state, self.tasks, env.executable, project.name, self.check, self.overlay,
                   requirements)

    def _export(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if env:
            export_environment(self, self.tasks, env.executable, project.name, env.version, project.path)

    def _manage(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if env:
            if not any(e.path == env.path for e in self.state.envs):
                venvs.register(env.path)  # list it with the other environments
                self.state.refresh()
            self.manage_packages(env.executable)

    def _terminal(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if not env:
            return
        try:
            venvs.open_terminal(env)
        except OSError as exc:
            QMessageBox.warning(self, "Open terminal", str(exc))
