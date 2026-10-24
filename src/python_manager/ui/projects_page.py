"""Project folders: their environment, how it compares with the requirements, and syncing it."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import config, imports, projects, venvs
from ..core.projects import Check, Project, Source
from .export_dialog import export_environment
from .imports_dialog import ImportsDialog
from .state import AppState
from .tasks import TaskManager
from .upgrade_dialog import update_all
from .widgets import button, button_row, color_rows, fill_table, loading_overlay, make_table, open_folder

STATUS_COLORS = {projects.MISSING: "error", projects.MISMATCH: "warning", projects.OK: "ok",
                 projects.UNLISTED: "muted"}
UV_SYNC = "uv.lock (uv sync)"


class ProjectsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager, manage_packages: Callable[[Path], None]):
        super().__init__()
        self.state, self.tasks, self.manage_packages = state, tasks, manage_packages
        self._generation = 0
        # Re-check when a requirements file is edited or packages change outside the app.
        self.watcher = QFileSystemWatcher(self)
        self.refresh_timer = QTimer(self, singleShot=True, interval=800)  # editors save in bursts
        self.refresh_timer.timeout.connect(lambda: self._show(keep_source=True))
        self.watcher.fileChanged.connect(lambda _: self.refresh_timer.start())
        self.watcher.directoryChanged.connect(lambda _: self.refresh_timer.start())

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
        self.python = QLabel()
        self.python.setWordWrap(True)
        self.pin_btn = button("Set…", self.set_python, f"Write the Python version to {projects.PYTHON_VERSION}")
        python_row = QHBoxLayout()
        python_row.addWidget(self.python, 1)
        python_row.addWidget(self.pin_btn)
        self.source = QComboBox()
        self.source.currentIndexChanged.connect(lambda _: self.check())
        form = QFormLayout()
        form.addRow("Folder:", self.path)
        form.addRow("Files:", self.files)
        form.addRow("Python:", python_row)
        form.addRow("Environment:", self.env)
        form.addRow("Requirements:", self.source)

        self.unlisted = QCheckBox("Show installed packages the requirements do not list")
        self.unlisted.setChecked(True)
        self.unlisted.toggled.connect(lambda _: self.check())
        self.table = make_table(["Requirement", "Installed", "Status"], stretch=0)
        self.overlay = loading_overlay(self.table)
        self.summary = QLabel()
        self.create_btn = button("Create environment…", self.create_env, "Create .venv in the project and sync it")
        self.sync_btn = button("Sync", self.sync, "Install the requirements into the environment")
        self.env_buttons = [
            self.sync_btn,
            button("Check", self.check, "Compare the environment with the requirements again"),
            button("Check imports…", self.check_imports,
                   "Find imports the requirements miss and requirements the code never imports"),
            button("Update all…", self._update_all, "Choose which outdated packages to update"),
            button("Export…", self._export, "Freeze the environment to requirements.txt or pylock.toml"),
            button("Manage packages", self._manage),
            button("Open terminal", self._terminal),
        ]
        self.folder_btn = button("Open folder", lambda: self._with_project(lambda p: open_folder(p.path)))
        details = QGroupBox("Project")
        dlay = QVBoxLayout(details)
        dlay.addLayout(form)
        dlay.addWidget(self.unlisted)
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

    def _show(self, keep_source: bool = False) -> None:
        project = self.project()
        previous = self.source.currentText() if keep_source else ""
        if not keep_source:
            fill_table(self.table, [])
            self.summary.clear()
        self.source.blockSignals(True)
        self.source.clear()
        self._watch(project)
        if project is None:
            for label in (self.path, self.files, self.env, self.python):
                label.setText("—")
            self.source.blockSignals(False)
            self._update_buttons(None, None)
            return
        env = project.env()
        self.path.setText(str(project.path))
        self.files.setText(", ".join(project.files) or "none")
        self.python.setText(self._python_text(project))
        env_text = f"{env.path.name} (Python {env.version})" if env else "none"
        problems = projects.python_problems(project, env.version) if env else []
        if problems:
            env_text += f" ⚠ {' and '.join(problems)}; recreate the environment to match"
        self.env.setText(env_text)
        for source in project.sources():
            self.source.addItem(source.label, source)
        if projects.can_uv_sync(project):
            self.source.insertItem(0, UV_SYNC, None)
            self.source.setCurrentIndex(0)
        if previous and self.source.findText(previous) >= 0:
            self.source.setCurrentIndex(self.source.findText(previous))
        self.source.blockSignals(False)
        self._update_buttons(project, env)
        self.check()

    @staticmethod
    def _python_text(project: Project) -> str:
        pin, requires = projects.python_pin(project), projects.requires_python(project)
        parts = ([f"{pin} ({projects.PYTHON_VERSION})"] if pin else []) + \
            ([f"{requires} (requires-python)"] if requires else [])
        return " · ".join(parts) or "any (not pinned)"

    def _update_buttons(self, project: Optional[Project], env: Optional[venvs.VirtualEnv]) -> None:
        self.pin_btn.setEnabled(project is not None)
        self.create_btn.setEnabled(project is not None and env is None)
        for btn in self.env_buttons:
            btn.setEnabled(env is not None)
        self.sync_btn.setEnabled(env is not None and self.source.count() > 0)
        self.folder_btn.setEnabled(project is not None)

    def _watch(self, project: Optional[Project]) -> None:
        if self.watcher.files() or self.watcher.directories():
            self.watcher.removePaths(self.watcher.files() + self.watcher.directories())
        if project:
            # Re-added on every refresh: editors that save by replacing a file drop it from the watch.
            self.watcher.addPaths([str(p) for p in project.watched_paths() if p.exists()])

    def _source(self) -> Optional[Source]:
        return self.source.currentData()

    def _compare_source(self, project: Project) -> Optional[Source]:
        """uv sync installs from the lock file; its declared requirements are in pyproject.toml."""
        if self.source.currentText() == UV_SYNC:
            return Source(project.path / projects.PYPROJECT)
        return self._source()

    def check(self) -> None:
        project = self.project()
        env = project.env() if project else None
        source = self._compare_source(project) if project else None
        self._generation += 1
        generation = self._generation
        if env is None or source is None or not source.path.is_file():
            self.overlay.stop()
            fill_table(self.table, [])
            self.summary.setText("Create an environment to compare it with the requirements." if project and not env
                                 else "")
            return
        unlisted = self.unlisted.isChecked()
        if not self.table.rowCount():  # a refresh after a file change keeps the old rows until done
            self.summary.setText("Comparing…")
            self.overlay.start(f"Comparing {env.name} with {source.label}…")

        def done(checks: list[Check]):
            if generation != self._generation:
                return
            self.overlay.stop()
            fill_table(self.table, [(c, (c.requirement, c.installed or "—", c.status)) for c in checks])
            color_rows(self.table, 2, STATUS_COLORS)
            missing = sum(c.status == projects.MISSING for c in checks)
            wrong = sum(c.status == projects.MISMATCH for c in checks)
            extra = sum(c.status == projects.UNLISTED for c in checks)
            listed = len(checks) - extra
            if not listed:
                text = f"{source.label} lists no requirements."
            elif missing or wrong:
                text = f"{missing} missing, {wrong} with the wrong version. Press Sync to install them."
            else:
                text = f"All {listed} requirements are satisfied."
            if extra:
                text += f" {extra} installed package{'s are' if extra != 1 else ' is'} not listed."
            self.summary.setText(text)

        def failed(message: str):
            if generation == self._generation:
                self.overlay.stop()
                self.summary.setText(f"Could not compare: {message.splitlines()[0]}")

        self.tasks.run(f"Comparing {project.name}",
                       lambda _: projects.compare(projects.read_requirements(source), env.executable, unlisted),
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
        default = config.get("default_python")
        index = next((i for i, b in enumerate(bases) if default and str(b.executable) == default), 0)
        index = projects.preferred_python(project, [b.version for b in bases], index)
        label, ok = QInputDialog.getItem(self, "Create environment",
                                         f"Python for {project.name}/.venv:", [b.label for b in bases], index, False)
        if not ok:
            return
        base = bases[[b.label for b in bases].index(label)]

        def done(_):
            self.state.refresh()
            self._show()

        self.tasks.run(f"Creating {project.name}/.venv",
                       lambda ctx: projects.create_env(project, base.executable, ctx), done)

    def set_python(self) -> None:
        project = self.project()
        if not project:
            return
        minors = []
        for interp in self.state.interpreters(include_envs=False):
            minor = ".".join(interp.version.split(".")[:2])
            if minor not in minors:
                minors.append(minor)
        minors.sort(key=lambda v: tuple(int(n) for n in v.split(".") if n.isdigit()), reverse=True)
        current = projects.python_pin(project)
        choices = [current] + [m for m in minors if m != current] if current else minors
        version, ok = QInputDialog.getItem(
            self, "Python version", f"Python for {project.name} ({projects.PYTHON_VERSION}; empty removes it):",
            choices or [""], 0, True)
        if not ok:
            return
        try:
            projects.set_python_pin(project, version)
        except OSError as exc:
            QMessageBox.warning(self, "Python version", str(exc))
            return
        self._show(keep_source=True)

    def sync(self) -> None:
        project = self.project()
        if not project or not project.env():
            return
        source = self._source()
        self.tasks.run(f"Syncing {project.name}", lambda ctx: projects.sync(project, source, ctx),
                       lambda _: self.check())

    def check_imports(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if not env:
            return
        source = self._compare_source(project)
        has_source = source is not None and source.path.is_file()
        label = source.label if has_source else "the requirements"

        def work(_):
            requirements = projects.read_requirements(source) if has_source else []
            return imports.check(project.path, requirements, env.executable)

        self.tasks.run(f"Checking imports of {project.name}", work,
                       lambda result: ImportsDialog(*result, project.name, label, self).exec())

    def _update_all(self) -> None:
        project = self.project()
        env = project.env() if project else None
        if not env:
            return
        source = self._compare_source(project)
        requirements = (lambda: projects.read_requirements(source)) if source and source.path.is_file() else None
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
