"""Dialog listing imports a project's requirements miss and requirements its code never imports."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..core import imports
from ..core.imports import ImportCheck
from .widgets import color_rows, fill_table, make_table

COLORS = {imports.NOT_INSTALLED: "error", imports.NOT_DECLARED: "warning", imports.NOT_IMPORTED: "muted"}
DETAIL = {imports.NOT_INSTALLED: "First imported in", imports.NOT_DECLARED: "Installed by",
          imports.NOT_IMPORTED: "Provides"}


def summary(checks: list[ImportCheck], source: str, unreadable: list[Path]) -> str:
    counts = {status: sum(c.status == status for c in checks) for status in COLORS}
    if not checks:
        text = f"Every import is installed and declared in {source}, and every requirement is imported."
    else:
        text = (f"{counts[imports.NOT_INSTALLED]} imported module(s) not installed, "
                f"{counts[imports.NOT_DECLARED]} installed but not declared in {source}, "
                f"{counts[imports.NOT_IMPORTED]} requirement(s) never imported "
                "(tools, plugins and optional backends are used without an import).")
    if unreadable:
        text += f" {len(unreadable)} file(s) could not be parsed and were skipped."
    return text


class ImportsDialog(QDialog):
    def __init__(self, checks: list[ImportCheck], unreadable: list[Path], project: str, source: str, parent=None):
        super().__init__(parent)
        self.checks = checks
        self.setWindowTitle(f"Imports · {project}")
        self.resize(760, 460)
        self.summary = QLabel(summary(checks, source, unreadable))
        self.summary.setWordWrap(True)
        self.table = make_table(["Name", "Status", "Detail"], stretch=2)
        fill_table(self.table, [(c, (c.name, c.status, f"{DETAIL[c.status]}: {c.detail}")) for c in checks])
        color_rows(self.table, 1, COLORS)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
