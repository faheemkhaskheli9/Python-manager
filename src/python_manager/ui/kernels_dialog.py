"""Every installed Jupyter kernel, with the ones whose Python is gone flagged for removal."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout, QWidget

from ..core import kernels
from ..core.kernels import Kernel
from . import theme
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, make_table, open_folder, selected_payloads

MISSING = "missing"


class KernelsDialog(QDialog):
    def __init__(self, tasks: TaskManager, parent: QWidget = None):
        super().__init__(parent)
        self.tasks = tasks
        self.setWindowTitle("Jupyter kernels")
        self.resize(820, 420)
        self.table = make_table(["Name", "Display name", "Language", "Python", "Location"], stretch=4, multi=True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.summary = QLabel()
        self.remove_btn = button("Remove", self._remove, "Delete the selected kernel specs")
        self.folder_btn = button("Open folder", lambda: [open_folder(k.path) for k in selected_payloads(self.table)[:1]])
        self.broken_btn = button("Select broken", self._select_broken, "Kernels whose Python no longer exists")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        layout.addLayout(button_row(self.broken_btn, self.remove_btn, self.folder_btn,
                                    button("Refresh", self.load)))
        layout.addWidget(buttons)
        self.load()

    def load(self) -> None:
        found = kernels.list_kernels()
        fill_table(self.table, [(k, (k.name, k.display_name, k.language,
                                     MISSING if k.broken else str(k.executable or ""), str(k.path)))
                                for k in found])
        for row in range(self.table.rowCount()):
            if self.table.item(row, 3).text() == MISSING:
                theme.paint(self.table.item(row, 3), "error")
        broken = sum(k.broken for k in found)
        self.summary.setText(f"{len(found)} kernels" + (f", {broken} with a missing Python" if broken else ""))
        self.broken_btn.setEnabled(broken > 0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        selected = selected_payloads(self.table)
        self.remove_btn.setEnabled(bool(selected))
        self.folder_btn.setEnabled(bool(selected))

    def _select_broken(self) -> None:
        self.table.clearSelection()
        model = self.table.selectionModel()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole).broken:
                model.select(self.table.model().index(row, 0),
                             QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def _remove(self) -> None:
        selected: list[Kernel] = selected_payloads(self.table)
        if not selected:
            return
        names = "\n".join(f"{k.display_name} ({k.path})" for k in selected)
        if QMessageBox.question(self, "Remove kernels", f"Delete these kernel specs?\n\n{names}") \
                != QMessageBox.StandardButton.Yes:
            return

        def remove(ctx):
            for kernel in selected:
                kernels.remove(kernel, ctx)

        self.tasks.run(f"Removing {len(selected)} Jupyter kernel{'s' * (len(selected) != 1)}", remove,
                       lambda _: self.load(), lambda _: self.load())
