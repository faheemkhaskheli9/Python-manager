"""Command-line tools installed with ``uv tool`` or pipx."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from ..core import tools
from ..core.tools import Tool
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, loading_overlay, make_table, open_folder, selected_payload

UPDATE_COLOR = "#ef6c00"
NO_MANAGER = "Neither uv nor pipx was found on PATH. Install one of them to manage command-line tools."


class ToolsPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self.loaded = False
        self._tools: list[Tool] = []
        self._latest: dict[str, str] = {}
        self._generation = 0

        self.table = make_table(["Tool", "Version", "Latest", "Manager", "Python", "Commands", "Location"], stretch=5)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.overlay = loading_overlay(self.table)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.selection_buttons = [
            button("Upgrade", self.upgrade),
            button("Uninstall", self.uninstall),
            button("Open folder", self._open_folder, "Open the tool's environment"),
        ]
        self.upgrade_all_btn = button("Upgrade all", self.upgrade_all, "Upgrade every tool of each manager")

        self.spec = QLineEdit(placeholderText="Package, e.g. ruff, black==24.8.0 or httpie[socks]")
        self.spec.returnPressed.connect(self.install)
        self.manager = QComboBox()
        self.python = QComboBox()
        install_box = QGroupBox("Install a tool")
        form = QFormLayout(install_box)
        form.addRow("Package:", self.spec)
        form.addRow("Install with:", self.manager)
        form.addRow("Python:", self.python)
        form.addRow(button_row(button("Install", self.install)))

        layout = QVBoxLayout(self)
        layout.addLayout(button_row(button("Refresh", self.reload), self.upgrade_all_btn))
        layout.addWidget(self.table, 1)
        layout.addWidget(self.status)
        layout.addLayout(button_row(*self.selection_buttons))
        layout.addWidget(install_box)
        state.changed.connect(self._fill_pythons)
        self._fill_pythons()
        self._update_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.loaded:
            self.loaded = True
            self.reload()

    def _fill_pythons(self) -> None:
        current = self.python.currentData()
        self.python.clear()
        self.python.addItem("Default (chosen by the manager)", None)
        for interp in self.state.interpreters(include_envs=False):
            self.python.addItem(interp.label, interp.executable)
        index = self.python.findData(current) if current else 0
        self.python.setCurrentIndex(max(index, 0))

    def reload(self) -> None:
        managers = tools.managers()
        self.manager.clear()
        self.manager.addItems(managers)
        if not managers:
            self._tools, self._latest = [], {}
            self._render()
            self.status.setText(NO_MANAGER)
            return
        self._generation += 1
        generation = self._generation
        self.status.setText("Loading tools…")
        self.overlay.start("Loading tools…")

        def done(found: list[Tool]):
            if generation != self._generation:
                return
            self.overlay.stop()
            self._tools, self._latest = found, {}
            self._render()
            if found:
                self._check_latest(generation)

        def failed(message: str):
            if generation != self._generation:
                return
            self.overlay.stop()
            self.status.setText(f"Could not list tools: {message.splitlines()[0]}")

        self.tasks.run("Listing tools", lambda _: tools.list_tools(), done, failed, foreground=False)

    def _check_latest(self, generation: int) -> None:
        found = list(self._tools)

        def done(latest: dict[str, str]):
            if generation == self._generation:
                self._latest = latest
                self._render()

        self.tasks.run("Checking tools for updates", lambda _: tools.latest_versions(found), done,
                       lambda _: None, foreground=False)

    def _outdated(self, tool: Tool) -> bool:
        latest = self._latest.get(tool.name)
        if not latest or latest == tool.version:
            return False
        try:
            from packaging.version import Version

            return Version(latest) > Version(tool.version)
        except Exception:
            return True

    def _render(self) -> None:
        outdated = [t for t in self._tools if self._outdated(t)]
        fill_table(self.table, [(t, (t.name, t.version, self._latest.get(t.name, ""), t.manager, t.python,
                                     ", ".join(t.commands), str(t.path or ""))) for t in self._tools])
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) in outdated:
                item = self.table.item(row, 2)
                item.setForeground(QBrush(QColor(UPDATE_COLOR)))
                item.setToolTip("Update available")
        updates = f", {len(outdated)} with updates" if outdated else ""
        managers = " and ".join(tools.managers())
        self.status.setText(f"{len(self._tools)} tools{updates} · using {managers}" if managers else NO_MANAGER)
        self.upgrade_all_btn.setEnabled(bool(self._tools))
        self._update_buttons()

    def _selected(self) -> Optional[Tool]:
        return selected_payload(self.table)

    def _update_buttons(self) -> None:
        tool = self._selected()
        for btn in self.selection_buttons:
            btn.setEnabled(tool is not None)
        if tool:
            self.selection_buttons[2].setEnabled(bool(tool.path and tool.path.is_dir()))

    def _open_folder(self) -> None:
        tool = self._selected()
        if tool and tool.path:
            open_folder(tool.path)

    def install(self) -> None:
        spec = self.spec.text().strip()
        manager = self.manager.currentText()
        if not spec or not manager:
            if not manager:
                QMessageBox.information(self, "Install tool", NO_MANAGER)
            return
        python = self.python.currentData()
        self.tasks.run(f"Installing tool {spec} ({manager})",
                       lambda ctx: tools.install(manager, spec, python, ctx), lambda _: self._installed())

    def _installed(self) -> None:
        self.spec.clear()
        self.reload()

    def upgrade(self) -> None:
        tool = self._selected()
        if tool:
            self.tasks.run(f"Upgrading tool {tool.name}", lambda ctx: tools.upgrade(tool, ctx),
                           lambda _: self.reload())

    def upgrade_all(self) -> None:
        managers = sorted({t.manager for t in self._tools})

        def upgrade_all(ctx):
            for manager in managers:
                ctx.check()
                tools.upgrade_all(manager, ctx)

        if managers:
            self.tasks.run("Upgrading all tools", upgrade_all, lambda _: self.reload())

    def uninstall(self) -> None:
        tool = self._selected()
        if not tool:
            return
        commands = f"\n\nCommands removed: {', '.join(tool.commands)}" if tool.commands else ""
        answer = QMessageBox.question(self, "Uninstall tool", f"Uninstall {tool.name} ({tool.manager})?{commands}")
        if answer == QMessageBox.StandardButton.Yes:
            self.tasks.run(f"Uninstalling tool {tool.name}", lambda ctx: tools.uninstall(tool, ctx),
                           lambda _: self.reload())
