"""Install, upgrade, download and uninstall packages for any interpreter or environment."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import deps, favorites, licenses, packages, pypi_names, security
from ..core.interpreters import CONDA, Interpreter
from ..core.packages import Package, ProjectInfo
from .deps_dialog import DependencyDialog
from .export_dialog import export_environment
from .licenses_dialog import LicensesDialog
from .security_dialog import SecurityDialog
from .state import AppState
from .tasks import TaskManager
from .upgrade_dialog import update_all
from .widgets import button, button_row, fill_table, loading_overlay, make_table, selected_payloads

LATEST = "Latest"
STAR = "★"
WARN = "⚠"
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?$")


class PackagesPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self._packages: list[Package] = []
        self._latest: dict[str, str] = {}
        self._graph: deps.Graph = {}
        self._required_by: dict[str, list[str]] = {}
        self._vulns: list[security.Vulnerability] = []
        self._names_requested = False
        self._generation = 0
        self._pending_select: Optional[Path] = None

        self.target = QComboBox()
        self.target.setMinimumWidth(420)
        self.target.currentIndexChanged.connect(lambda _: self.reload())
        top = QHBoxLayout()
        top.addWidget(QLabel("Environment:"))
        top.addWidget(self.target, 1)
        top.addWidget(button("Refresh", self.reload))

        self.pip_bar = QWidget()
        bar = QHBoxLayout(self.pip_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("pip is not available for this interpreter."))
        bar.addWidget(button("Install pip", self.ensure_pip))
        bar.addStretch(1)
        self.pip_bar.hide()
        self.conda_bar = QLabel("Conda environment: packages are shown read-only. "
                                "Change them with conda, mamba or micromamba.")
        self.conda_bar.setWordWrap(True)
        self.conda_bar.hide()

        # Installed packages
        self.filter = QLineEdit(placeholderText="Filter installed packages")
        self.filter.textChanged.connect(self._apply_filter)
        self.favorites_only = QCheckBox("Favourites only")
        self.favorites_only.toggled.connect(self._apply_filter)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter, 1)
        filter_row.addWidget(self.favorites_only)
        self.table = make_table([STAR, "Package", "Version", "Latest", "Security", "Required by"], stretch=5, multi=True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.overlay = loading_overlay(self.table)
        self.status = QLabel()
        self.uninstall_btn = button("Uninstall", self.uninstall)
        self.upgrade_btn = button("Upgrade", self.upgrade)
        self.favorite_btn = button("★ Favourite", self.toggle_selected_favorites, "Mark or unmark as favourite")
        self.deps_btn = button("Dependencies…", self.show_dependencies, "What the package requires and what requires it")
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(filter_row)
        lay.addWidget(self.table)
        lay.addWidget(self.status)
        lay.addLayout(button_row(self.uninstall_btn, self.upgrade_btn, self.favorite_btn, self.deps_btn))
        lay.addLayout(button_row(button("Check for updates", self.check_updates),
                                 button("Update all…", self.upgrade_all, "Choose which outdated packages to update"),
                                 button("Security check", self.security_check,
                                        "Look up known vulnerabilities in the OSV database")))
        lay.addLayout(button_row(button("Install from file…", self.install_from_file,
                                        "Install a wheel, source archive or requirements.txt"),
                                 button("Export…", self.export_requirements,
                                        "Save as requirements.txt, pylock.toml or pyproject.toml"),
                                 button("Licenses…", self.show_licenses,
                                        "List each package's licence and save a report")))

        # Install / download panel
        self.name = QLineEdit(placeholderText="Package name, e.g. requests")
        self.name.returnPressed.connect(self.lookup)
        self.name.textEdited.connect(self._clear_info)
        self.names_model = QStringListModel(self)
        self.completer = QCompleter(self.names_model, self.name)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setModelSorting(QCompleter.ModelSorting.CaseInsensitivelySortedModel)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(lambda _: self.lookup())
        self.name.setCompleter(self.completer)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name, 1)
        name_row.addWidget(button("Look up", self.lookup, "Fetch details and versions from PyPI"))
        self.version = QComboBox()
        self.version.addItem(LATEST)
        self.info = QLabel("Enter a package name and press Look up to see its versions.")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.info.setOpenExternalLinks(True)
        self.upgrade_chk = QCheckBox("Upgrade if already installed")
        self.deps_chk = QCheckBox("Include dependencies when downloading")
        self.deps_chk.setChecked(True)
        install_box = QGroupBox("Install or download a package")
        form = QFormLayout(install_box)
        form.addRow("Package:", name_row)
        form.addRow("Version:", self.version)
        form.addRow(self.info)
        form.addRow(self.upgrade_chk)
        form.addRow(self.deps_chk)
        form.addRow(button_row(button("Install", self.install),
                               button("Download…", self.download, "Save wheels/sdists to a folder"),
                               button("☆ Add to favourites", self.add_favorite)))

        self.favorites = QListWidget()
        self.favorites.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.favorites.itemDoubleClicked.connect(lambda item: self.name.setText(item.data(Qt.ItemDataRole.UserRole)))
        favorites_box = QGroupBox("Favourite packages")
        flay = QVBoxLayout(favorites_box)
        flay.addWidget(self.favorites)
        flay.addLayout(button_row(
            button("Install selected", self.install_selected_favorites),
            button("Install all missing", self.install_missing_favorites),
            button("Remove", self.remove_selected_favorites, "Remove from favourites")))
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.addWidget(install_box)
        rlay.addWidget(favorites_box, 1)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.pip_bar)
        root.addWidget(self.conda_bar)
        root.addWidget(splitter, 1)

        state.changed.connect(self._fill_targets)
        self._render_favorites()
        self._update_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._names_requested:
            self._names_requested = True
            self.load_names()

    def load_names(self) -> None:
        """Fill the name completer from the cached PyPI list, downloading it when missing or old."""
        def done(names):
            self.names_model.setStringList(names)
            self.name.setPlaceholderText("Package name, e.g. requests")

        self.name.setPlaceholderText("Package name (loading suggestions…)")
        self.tasks.run("Loading PyPI package names", pypi_names.load, done, lambda _: None, foreground=False)

    # Target selection ------------------------------------------------------

    def _fill_targets(self) -> None:
        current = self._pending_select or (self.python and self.python.executable)
        self.target.blockSignals(True)
        self.target.clear()
        for interp in self.state.interpreters():
            self.target.addItem(interp.label, interp)
            self.target.setItemData(self.target.count() - 1, str(interp.executable), Qt.ItemDataRole.ToolTipRole)
        index = next((i for i in range(self.target.count())
                      if current and self.target.itemData(i).executable == current), 0)
        self.target.setCurrentIndex(index)
        self.target.blockSignals(False)
        self._pending_select = None
        self.reload()

    def select(self, executable: Path) -> None:
        """Show packages of the interpreter at ``executable`` (used by the environments page)."""
        for i in range(self.target.count()):
            if self.target.itemData(i).executable == executable:
                self.target.setCurrentIndex(i)
                return
        self._pending_select = executable  # list not refreshed yet

    @property
    def python(self) -> Optional[Interpreter]:
        return self.target.currentData()

    @property
    def read_only(self) -> bool:
        """Conda environments are inspected here but changed with conda, which pip would bypass."""
        return bool(self.python and self.python.kind == CONDA)

    def _refuse_read_only(self) -> bool:
        if self.read_only:
            QMessageBox.information(self, "Read-only", "Packages of conda environments are changed with conda, "
                                                       "mamba or micromamba, not here.")
        return self.read_only

    # Installed packages ----------------------------------------------------

    def reload(self) -> None:
        interp = self.python
        self._packages, self._latest, self._graph, self._required_by = [], {}, {}, {}
        self._vulns = []
        self.pip_bar.hide()
        self.conda_bar.setVisible(self.read_only)
        self._render()
        if interp is None:
            self.overlay.stop()
            self.status.setText("No interpreter selected.")
            return
        self._generation += 1
        generation = self._generation
        self.status.setText("Loading packages…")
        self.overlay.start(f"Loading packages of {interp.name}…")

        def done(result):
            if generation != self._generation:
                return
            self.overlay.stop()
            self._packages, self._graph, has_pip = result
            self._required_by = deps.required_by(self._graph)
            report = self.state.health.get(str(interp.executable))
            if report:  # results of the last scheduled check that still apply
                report = report.current(self._packages)
                self._latest, self._vulns = dict(report.outdated), list(report.vulns)
            self.pip_bar.setVisible(not has_pip and not self.read_only)
            self._render()

        def failed(message):
            if generation != self._generation:
                return
            self.overlay.stop()
            if "pip is not installed" in message and not self.read_only:
                self.pip_bar.show()
                self.status.setText("pip is not installed.")
            else:
                self.status.setText(f"Could not list packages: {message.splitlines()[0]}")

        def load(_ctx):
            # Installed metadata gives names, versions and dependencies in one quick call;
            # pip list is only the fallback (e.g. Python < 3.8).
            try:
                graph = deps.load_graph(interp.executable)
            except Exception:
                return packages.list_packages(interp.executable), {}, True
            has_pip = packages.uv_path() is not None or "pip" in graph
            return packages.from_dists(graph.values()), graph, has_pip

        self.tasks.run("Listing packages", load, done, failed, foreground=False)

    def _render(self) -> None:
        favs = {favorites.normalize(f) for f in favorites.list_favorites()}
        vulns: dict[tuple[str, str], int] = {}
        for v in self._vulns:
            key = (deps.normalize(v.package), v.version)
            vulns[key] = vulns.get(key, 0) + 1
        rows = []
        for p in self._packages:
            fav = favorites.normalize(p.name) in favs
            users = ", ".join(self._required_by.get(deps.normalize(p.name), []))
            count = vulns.get((deps.normalize(p.name), p.version), 0)
            alert = f"{WARN} {count}" if count else ""
            rows.append((p, (STAR if fav else "", p.name, p.version, self._latest.get(p.name, ""), alert, users)))
        fill_table(self.table, rows)
        self._render_favorites()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide rows that do not match instead of rebuilding the table on every keystroke."""
        text = self.filter.text().strip().lower()
        only_favs = self.favorites_only.isChecked()
        shown = 0
        for row in range(self.table.rowCount()):
            visible = text in self.table.item(row, 1).text().lower() and \
                (not only_favs or self.table.item(row, 0).text() == STAR)
            self.table.setRowHidden(row, not visible)
            shown += visible
        if self._packages:
            updates = f", {len(self._latest)} with updates" if self._latest else ""
            listed = f"{shown} of {len(self._packages)}" if shown != len(self._packages) else f"{shown}"
            self.status.setText(f"{listed} packages{updates} · using {packages.backend()}")
        self._update_buttons()

    def _selected_names(self) -> list[str]:
        return [p.name for p in selected_payloads(self.table)]

    def _update_buttons(self) -> None:
        has = bool(self.table.selectionModel().selectedRows())
        self.uninstall_btn.setEnabled(has and not self.read_only)
        self.upgrade_btn.setEnabled(has and not self.read_only)
        self.favorite_btn.setEnabled(has)
        self.deps_btn.setEnabled(len(self.table.selectionModel().selectedRows()) == 1 and bool(self._graph))

    def _run(self, title: str, fn) -> None:
        """Run a modifying pip operation, then reload the package list."""
        interp = self.python
        if interp is None:
            QMessageBox.information(self, "No environment", "Select an interpreter or environment first.")
            return
        if self._refuse_read_only():
            return
        self.tasks.run(f"{title} ({interp.name})", lambda ctx: fn(interp.executable, ctx),
                       lambda _: self.reload())

    def uninstall(self) -> None:
        names = self._selected_names()
        if not names:
            return
        text = "Uninstall " + ", ".join(names) + "?"
        needed = deps.dependents(self._graph, names)
        if needed:
            lines = "".join(f"<li><b>{n}</b> is required by {', '.join(users)}</li>" for n, users in needed.items())
            text += f"<p>Other packages depend on this:</p><ul>{lines}</ul>They may stop working."
        box = QMessageBox(QMessageBox.Icon.Warning if needed else QMessageBox.Icon.Question, "Uninstall", text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        unused = deps.unused_after_removal(self._graph, names)
        if unused:
            check = QCheckBox(f"Also remove {len(unused)} unused dependencies: " + ", ".join(unused))
            box.setCheckBox(check)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        if unused and box.checkBox().isChecked():
            names = names + unused
        self._run("Uninstalling " + ", ".join(names), lambda py, ctx: packages.uninstall(py, names, ctx))

    def show_dependencies(self) -> None:
        names = self._selected_names()
        if len(names) == 1:
            DependencyDialog(self._graph, names[0], self).exec()

    def upgrade(self) -> None:
        names = self._selected_names()
        if names:
            self._run("Upgrading " + ", ".join(names), lambda py, ctx: packages.install(py, names, ctx, upgrade=True))

    def upgrade_all(self) -> None:
        interp = self.python
        if interp is not None and not self._refuse_read_only():
            update_all(self, self.state, self.tasks, interp.executable, interp.name, self.reload, self.overlay)

    def check_updates(self) -> None:
        interp = self.python
        if interp is None:
            return

        def done(latest):
            self.overlay.stop()
            self._latest = latest
            self._render()

        if self.tasks.run(f"Checking for updates ({interp.name})", lambda _: packages.outdated(interp.executable),
                          done, self._failed("Check for updates")):
            self.overlay.start("Checking PyPI for newer versions…")

    def security_check(self) -> None:
        interp, items = self.python, list(self._packages)
        if interp is None or not items:
            return

        def done(vulns):
            self.overlay.stop()
            self._vulns = vulns
            self._render()
            if not vulns:
                QMessageBox.information(self, "Security check",
                                        f"No known vulnerabilities in {len(items)} packages of {interp.name}.")
                return
            dialog = SecurityDialog(vulns, interp.name, self)
            if dialog.exec() and dialog.specs:
                specs = dialog.specs
                self._run("Upgrading vulnerable packages", lambda py, ctx: packages.install(py, specs, ctx))

        if self.tasks.run(f"Security check ({interp.name})", lambda ctx: security.scan(items, ctx), done,
                          self._failed("Security check")):
            self.overlay.start("Looking up known vulnerabilities…")

    def show_licenses(self) -> None:
        interp = self.python
        if interp is None:
            return

        def done(items):
            self.overlay.stop()
            LicensesDialog(items, interp.name, self).exec()

        if self.tasks.run(f"Reading licences ({interp.name})", lambda _: licenses.scan(interp.executable), done,
                          self._failed("Licenses")):
            self.overlay.start("Reading package licences…")

    def _failed(self, title: str):
        """Error handler for a task shown with the overlay: hide it and report the error."""
        def failed(message: str) -> None:
            self.overlay.stop()
            if message != "Cancelled":
                QMessageBox.warning(self, title, message.splitlines()[0] if message else title)
        return failed

    def ensure_pip(self) -> None:
        self._run("Installing pip", packages.ensure_pip)

    def install_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Install from file", "",
            "Packages and requirements (*.whl *.tar.gz *.zip *.txt);;All files (*)")
        if not path:
            return
        file = Path(path)
        if file.suffix == ".txt":
            self._run(f"Installing {file.name}", lambda py, ctx: packages.install_requirements(py, file, ctx))
        else:
            self._run(f"Installing {file.name}", lambda py, ctx: packages.install(py, [str(file)], ctx))

    def export_requirements(self) -> None:
        interp = self.python
        if interp is not None:
            export_environment(self, self.tasks, interp.executable, interp.name, interp.version)

    # Install / download ----------------------------------------------------

    def _clear_info(self) -> None:
        self.version.clear()
        self.version.addItem(LATEST)

    def lookup(self) -> None:
        name = self.name.text().strip()
        if not name:
            return
        self.info.setText(f"Looking up {name}…")

        def done(info: ProjectInfo):
            self._clear_info()
            self.version.addItems(info.versions)
            link = f' — <a href="https://pypi.org/project/{info.name}/">PyPI</a>'
            details = f"<b>{info.name} {info.latest}</b>{link}<br>{info.summary}"
            if info.requires_python:
                details += f"<br>Requires Python {info.requires_python}"
            self.info.setText(details)

        self.tasks.run(f"Looking up {name}", lambda _: packages.project_info(name), done,
                       lambda msg: self.info.setText(msg.splitlines()[0]), foreground=False)

    def _spec(self) -> Optional[str]:
        name = self.name.text().strip()
        if not name:
            QMessageBox.information(self, "Package", "Enter a package name.")
            return None
        version = self.version.currentText()
        if version and version != LATEST and _PLAIN_NAME.match(name):
            return f"{name}=={version}"
        return name

    def install(self) -> None:
        spec = self._spec()
        if spec:
            upgrade = self.upgrade_chk.isChecked()
            self._run(f"Installing {spec}", lambda py, ctx: packages.install(py, spec.split(), ctx, upgrade=upgrade))

    def download(self) -> None:
        spec = self._spec()
        if not spec or self.python is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Download to folder")
        if not folder:
            return
        with_deps = self.deps_chk.isChecked()
        interp = self.python
        self.tasks.run(f"Downloading {spec}",
                       lambda ctx: packages.download(interp.executable, spec.split(), Path(folder), ctx, with_deps))

    # Favourites ------------------------------------------------------------

    def _installed_names(self) -> set[str]:
        return {favorites.normalize(p.name) for p in self._packages}

    def _render_favorites(self) -> None:
        installed = self._installed_names()
        self.favorites.clear()
        for name in favorites.list_favorites():
            is_installed = favorites.normalize(name) in installed
            item = QListWidgetItem(f"{STAR} {name}" + ("   (installed)" if is_installed else ""))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.favorites.addItem(item)

    def _selected_favorites(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.favorites.selectedItems()]

    def toggle_selected_favorites(self) -> None:
        for name in self._selected_names():
            favorites.toggle(name)
        self._render()

    def add_favorite(self) -> None:
        name = self.name.text().strip()
        if not _PLAIN_NAME.match(name):
            QMessageBox.information(self, "Favourites", "Enter a package name (without a version).")
            return
        favorites.add(name)
        self._render()

    def remove_selected_favorites(self) -> None:
        for name in self._selected_favorites():
            favorites.remove(name)
        self._render()

    def _install_favorites(self, names: list[str]) -> None:
        if names:
            self._run("Installing " + ", ".join(names), lambda py, ctx: packages.install(py, names, ctx))

    def install_selected_favorites(self) -> None:
        self._install_favorites(self._selected_favorites())

    def install_missing_favorites(self) -> None:
        installed = self._installed_names()
        missing = [n for n in favorites.list_favorites() if favorites.normalize(n) not in installed]
        if not missing:
            QMessageBox.information(self, "Favourites", "All favourite packages are already installed.")
            return
        self._install_favorites(missing)
