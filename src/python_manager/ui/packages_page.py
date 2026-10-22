"""Install, upgrade, download and uninstall packages for any interpreter or environment."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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

from ..core import favorites, packages
from ..core.interpreters import Interpreter
from ..core.packages import Package, PipMissing, ProjectInfo
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, make_table, selected_payloads

LATEST = "Latest"
STAR = "★"
_PLAIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?$")


class PackagesPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self._packages: list[Package] = []
        self._latest: dict[str, str] = {}
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

        # Installed packages
        self.filter = QLineEdit(placeholderText="Filter installed packages")
        self.filter.textChanged.connect(self._render)
        self.favorites_only = QCheckBox("Favourites only")
        self.favorites_only.toggled.connect(self._render)
        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter, 1)
        filter_row.addWidget(self.favorites_only)
        self.table = make_table([STAR, "Package", "Version", "Latest"], stretch=1, multi=True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.status = QLabel()
        self.uninstall_btn = button("Uninstall", self.uninstall)
        self.upgrade_btn = button("Upgrade", self.upgrade)
        self.favorite_btn = button("★ Favourite", self.toggle_selected_favorites, "Mark or unmark as favourite")
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(filter_row)
        lay.addWidget(self.table)
        lay.addWidget(self.status)
        lay.addLayout(button_row(self.uninstall_btn, self.upgrade_btn, self.favorite_btn,
                                 button("Check for updates", self.check_updates)))
        lay.addLayout(button_row(button("Install from file…", self.install_from_file,
                                        "Install a wheel, source archive or requirements.txt"),
                                 button("Export requirements…", self.export_requirements)))

        # Install / download panel
        self.name = QLineEdit(placeholderText="Package name, e.g. requests")
        self.name.returnPressed.connect(self.lookup)
        self.name.textEdited.connect(self._clear_info)
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
        root.addWidget(splitter, 1)

        state.changed.connect(self._fill_targets)
        self._render_favorites()
        self._update_buttons()

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

    # Installed packages ----------------------------------------------------

    def reload(self) -> None:
        interp = self.python
        self._packages, self._latest = [], {}
        self.pip_bar.hide()
        self._render()
        if interp is None:
            self.status.setText("No interpreter selected.")
            return
        self._generation += 1
        generation = self._generation
        self.status.setText("Loading packages…")

        def done(items):
            if generation == self._generation:
                self._packages = items
                self._render()

        def failed(message):
            if generation != self._generation:
                return
            if "pip is not installed" in message:
                self.pip_bar.show()
                self.status.setText("pip is not installed.")
            else:
                self.status.setText(f"Could not list packages: {message.splitlines()[0]}")

        self.tasks.run("Listing packages", lambda _: packages.list_packages(interp.executable),
                       done, failed, foreground=False)

    def _render(self) -> None:
        text = self.filter.text().strip().lower()
        favs = {favorites.normalize(f) for f in favorites.list_favorites()}
        only_favs = self.favorites_only.isChecked()
        rows = []
        for p in self._packages:
            fav = favorites.normalize(p.name) in favs
            if text in p.name.lower() and (fav or not only_favs):
                rows.append((p, (STAR if fav else "", p.name, p.version, self._latest.get(p.name, ""))))
        fill_table(self.table, rows)
        self._render_favorites()
        if self._packages:
            updates = f", {len(self._latest)} with updates" if self._latest else ""
            self.status.setText(f"{len(self._packages)} packages{updates}")
        self._update_buttons()

    def _selected_names(self) -> list[str]:
        return [p.name for p in selected_payloads(self.table)]

    def _update_buttons(self) -> None:
        has = bool(self.table.selectionModel().selectedRows())
        self.uninstall_btn.setEnabled(has)
        self.upgrade_btn.setEnabled(has)
        self.favorite_btn.setEnabled(has)

    def _run(self, title: str, fn) -> None:
        """Run a modifying pip operation, then reload the package list."""
        interp = self.python
        if interp is None:
            QMessageBox.information(self, "No environment", "Select an interpreter or environment first.")
            return
        self.tasks.run(f"{title} ({interp.name})", lambda ctx: fn(interp.executable, ctx),
                       lambda _: self.reload())

    def uninstall(self) -> None:
        names = self._selected_names()
        if not names:
            return
        if QMessageBox.question(self, "Uninstall", "Uninstall " + ", ".join(names) + "?") != QMessageBox.StandardButton.Yes:
            return
        self._run("Uninstalling " + ", ".join(names), lambda py, ctx: packages.uninstall(py, names, ctx))

    def upgrade(self) -> None:
        names = self._selected_names()
        if names:
            self._run("Upgrading " + ", ".join(names), lambda py, ctx: packages.install(py, names, ctx, upgrade=True))

    def check_updates(self) -> None:
        interp = self.python
        if interp is None:
            return

        def done(latest):
            self._latest = latest
            self._render()

        self.tasks.run(f"Checking for updates ({interp.name})", lambda _: packages.outdated(interp.executable), done)

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
        if interp is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export requirements", "requirements.txt", "Text files (*.txt)")
        if not path:
            return

        def save(_ctx):
            Path(path).write_text(packages.freeze(interp.executable), encoding="utf-8")

        self.tasks.run("Exporting requirements", save)

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
