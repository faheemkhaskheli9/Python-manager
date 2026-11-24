"""PATH check: which python and pip the shell runs, what they shadow and folders missing from PATH."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QGroupBox, QHeaderView, QLabel, QSplitter,
                               QVBoxLayout, QWidget)

from ..core import pathcheck
from ..core.pathcheck import Report
from . import theme
from .tasks import TaskManager
from .widgets import button, button_row, color_rows, fill_table, make_table

COLORS = {pathcheck.WARNING: "warning", pathcheck.NOTE: "muted"}


class PathDialog(QDialog):
    def __init__(self, report: Report, tasks: TaskManager, parent: QWidget = None):
        super().__init__(parent)
        self.tasks, self.report = tasks, report
        self.setWindowTitle("PATH check")
        self.resize(900, 600)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.problems = make_table(["Severity", "Problem", "Fix"], stretch=1)
        self.problems.setWordWrap(True)
        self.problems.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.commands = make_table(["Command", "Runs", "Version", "Python / installs into", "Also on PATH"],
                                   stretch=4)
        self.entries = make_table(["#", "Folder", "Pythons", "Note"], stretch=1)
        splitter = QSplitter(Qt.Orientation.Vertical)
        for title, table in (("Problems", self.problems), ("Commands", self.commands), ("PATH, in search order",
                                                                                         self.entries)):
            box = QGroupBox(title)
            QVBoxLayout(box).addWidget(table)
            splitter.addWidget(box)
        self.refresh_btn = button("Refresh", self.refresh)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, 1)
        layout.addLayout(button_row(button("Copy report", self.copy, "Copy the check as text, e.g. for a bug report"),
                                    self.refresh_btn))
        layout.addWidget(buttons)
        self.show_report(report)

    def show_report(self, report: Report) -> None:
        self.report = report
        self.refresh_btn.setEnabled(True)
        self.summary.setText(report.summary + ("" if report.problems else
                                               " python and pip come from the same Python."))
        fill_table(self.problems, [(p, (p.severity, p.message, p.fix)) for p in report.problems])
        color_rows(self.problems, 0, COLORS)
        self.problems.resizeRowsToContents()
        fill_table(self.commands, [(c, (c.name, str(c.path) if c.path else "not found", c.version, c.detail,
                                        "\n".join(map(str, c.shadowed)))) for c in report.commands])
        for row, c in enumerate(report.commands):
            if c.path is None:
                theme.paint(self.commands.item(row, 1), "muted")
        self.commands.resizeRowsToContents()
        fill_table(self.entries, [(e, ((i, i), e.path, ", ".join(e.pythons),
                                       "missing" if not e.exists else "duplicate" if e.duplicate else ""))
                                  for i, e in enumerate(report.entries, 1)])
        color_rows(self.entries, 3, {"missing": "warning", "duplicate": "muted"})

    def refresh(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.tasks.run("Checking PATH", lambda ctx: pathcheck.check(), self.show_report,
                       lambda _: self.refresh_btn.setEnabled(True), foreground=False)

    def copy(self) -> None:
        QApplication.clipboard().setText(self.report.to_text())
