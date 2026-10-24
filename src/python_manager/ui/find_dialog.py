"""Find which interpreters and environments have a package installed."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..core import compare
from ..core.interpreters import Interpreter
from .tasks import TaskManager
from .widgets import button, fill_table, loading_overlay, make_table, selected_payload


class FindPackageDialog(QDialog):
    def __init__(self, interpreters: list[Interpreter], tasks: TaskManager,
                 manage_packages: Callable[[Path], None], parent: QWidget = None):
        super().__init__(parent)
        self.interpreters, self.tasks, self.manage_packages = interpreters, tasks, manage_packages
        self._generation = 0
        self.setWindowTitle("Find a package")
        self.resize(820, 480)

        self.pattern = QLineEdit(placeholderText="Package name, part of it, or a pattern such as django-*")
        self.pattern.returnPressed.connect(self.search)
        row = QHBoxLayout()
        row.addWidget(self.pattern, 1)
        row.addWidget(button("Search", self.search))
        self.table = make_table(["Environment", "Package", "Version", "Interpreter"], stretch=3)
        self.table.doubleClicked.connect(lambda _: self._manage())
        self.overlay = loading_overlay(self.table)
        self.summary = QLabel(f"Searches {len(interpreters)} interpreters and environments.")
        self.summary.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.manage_btn = buttons.addButton("Manage packages", QDialogButtonBox.ButtonRole.ActionRole)
        self.manage_btn.clicked.connect(self._manage)
        self.manage_btn.setEnabled(False)
        self.table.itemSelectionChanged.connect(
            lambda: self.manage_btn.setEnabled(selected_payload(self.table) is not None))
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)

    def search(self) -> None:
        pattern = self.pattern.text().strip()
        if not pattern:
            return
        self._generation += 1
        generation = self._generation
        targets = [(i.name, i.executable) for i in self.interpreters]

        def done(result) -> None:
            if generation != self._generation:
                return
            self.overlay.stop()
            matches, failed = result
            fill_table(self.table, [(m, (m.location, m.name, m.version, str(m.executable))) for m in matches])
            places = len({m.executable for m in matches})
            text = f"{len(matches)} matches in {places} of {len(targets)} interpreters and environments."
            if failed:
                text += " Could not read: " + ", ".join(failed) + "."
            self.summary.setText(text)

        def failed(message: str) -> None:
            if generation == self._generation:
                self.overlay.stop()
                self.summary.setText(f"Search failed: {message.splitlines()[0] if message else ''}")

        fill_table(self.table, [])
        self.overlay.start(f"Searching {len(targets)} interpreters and environments…")
        self.tasks.run(f"Finding {pattern}", lambda ctx: compare.find(pattern, targets, ctx), done, failed,
                       foreground=False)

    def _manage(self) -> None:
        match = selected_payload(self.table)
        if match:
            self.manage_packages(match.executable)
            self.accept()
