"""Dialog listing the licence of every installed package, with a report to save."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..core import licenses
from ..core.licenses import PackageLicense
from .widgets import color_rows, fill_table, make_table

ALL = "All categories"
COLORS = {licenses.COPYLEFT: "error", licenses.WEAK_COPYLEFT: "warning", licenses.OTHER: "warning",
          licenses.UNKNOWN: "muted"}
# File filter -> (suffix, writer)
FORMATS = {
    "CSV (*.csv)": (".csv", lambda items, _title: licenses.to_csv(items)),
    "Markdown (*.md)": (".md", licenses.to_markdown),
    "JSON (*.json)": (".json", lambda items, _title: licenses.to_json(items)),
}


class LicensesDialog(QDialog):
    def __init__(self, items: list[PackageLicense], env_name: str, parent=None, folder: Optional[Path] = None):
        super().__init__(parent)
        self.items, self.env_name, self.folder = items, env_name, folder
        self.setWindowTitle(f"Licenses · {env_name}")
        self.resize(900, 520)

        counts = licenses.summary(items)
        self.summary = QLabel(f"{len(items)} packages. " + ", ".join(f"{k}: {n}" for k, n in counts.items()) + ".")
        self.summary.setWordWrap(True)
        self.filter = QLineEdit(placeholderText="Filter by package or licence")
        self.filter.textChanged.connect(self._render)
        self.category = QComboBox()
        self.category.addItems([ALL, *counts])
        self.category.currentIndexChanged.connect(self._render)
        row = QHBoxLayout()
        row.addWidget(self.filter, 1)
        row.addWidget(self.category)
        self.table = make_table(["Package", "Version", "License", "Category", "Source"], stretch=2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        save = buttons.addButton("Save report…", QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addLayout(row)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self._render()

    def visible_items(self) -> list[PackageLicense]:
        text = self.filter.text().strip().lower()
        kind = self.category.currentText()
        return [i for i in self.items
                if (kind == ALL or i.category == kind) and (text in i.name.lower() or text in i.license.lower())]

    def _render(self) -> None:
        fill_table(self.table, [(i, (i.name, i.version, i.license or "—", i.category, i.source or "—"))
                                for i in self.visible_items()])
        color_rows(self.table, 3, COLORS)

    def save(self) -> None:
        start = str((self.folder or Path.home()) / "licenses.csv")
        path, chosen = QFileDialog.getSaveFileName(self, f"Save license report · {self.env_name}", start,
                                                   ";;".join(FORMATS))
        if not path:
            return
        suffix, writer = FORMATS.get(chosen) or next(
            (f for f in FORMATS.values() if path.lower().endswith(f[0])), FORMATS["CSV (*.csv)"])
        target = Path(path) if Path(path).suffix else Path(path).with_suffix(suffix)
        items = self.visible_items()
        try:
            target.write_text(writer(items, f"Licenses of {self.env_name}"), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save license report", str(exc))
            return
        QMessageBox.information(self, "Save license report", f"Saved {len(items)} packages to {target}.")
