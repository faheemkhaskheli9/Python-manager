"""Disk space used by environments, installed Pythons and package caches."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from ..core import disk, python_versions, venvs
from ..core.disk import Usage
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, loading_overlay, make_table, open_folder, selected_payload


class DiskPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self._scanned = False

        self.table = make_table(["Type", "Name", "Size", "Location"], stretch=3)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.overlay = loading_overlay(self.table)
        self.total = QLabel("Sizes are calculated when this page is opened.")
        self.clean_btn = button("Clean", self.clean, "Empty the selected cache")
        self.delete_btn = button("Delete", self.delete, "Delete the selected environment or Python")
        self.folder_btn = button("Open folder", lambda: self._with_selected(lambda u: open_folder(u.path)))
        layout = QVBoxLayout(self)
        layout.addLayout(button_row(button("Refresh", self.scan)))
        layout.addWidget(self.table)
        layout.addWidget(self.total)
        layout.addLayout(button_row(self.clean_btn, self.delete_btn, self.folder_btn))
        self._update_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._scanned:
            self._scanned = True
            self.scan()

    def scan(self) -> None:
        self.total.setText("Calculating sizes…")
        self.overlay.start("Calculating folder sizes…")

        def done(items: list[Usage]):
            self.overlay.stop()
            fill_table(self.table, [(u, (u.kind, u.name, (disk.format_size(u.size), u.size), str(u.path)))
                                    for u in items])
            caches = sum(u.size for u in items if u.cleanable)
            self.total.setText(f"Total: {disk.format_size(sum(u.size for u in items))}"
                               f" · caches: {disk.format_size(caches)}")
            self._update_buttons()

        def failed(message: str):
            self.overlay.stop()
            self.total.setText(f"Could not calculate sizes: {message.splitlines()[0]}")

        self.tasks.run("Calculating disk usage", disk.scan, done, failed, foreground=False)

    def _selected(self) -> Usage:
        return selected_payload(self.table)

    def _with_selected(self, fn) -> None:
        usage = self._selected()
        if usage:
            fn(usage)

    def _update_buttons(self) -> None:
        usage = self._selected()
        self.clean_btn.setEnabled(bool(usage and usage.cleanable))
        self.delete_btn.setEnabled(bool(usage and usage.kind in (disk.ENV, disk.PYTHON)))
        self.folder_btn.setEnabled(usage is not None)

    def clean(self) -> None:
        usage = self._selected()
        if not usage or not usage.cleanable:
            return
        answer = QMessageBox.question(
            self, "Clean cache",
            f"Empty the {usage.kind} ({disk.format_size(usage.size)})?\n\n{usage.path}\n\n"
            "Packages and Pythons will be downloaded again when needed.")
        if answer == QMessageBox.StandardButton.Yes:
            self.tasks.run(f"Cleaning {usage.kind}", lambda ctx: disk.clean(usage, ctx), lambda _: self.scan())

    def delete(self) -> None:
        usage = self._selected()
        if not usage or usage.kind not in (disk.ENV, disk.PYTHON):
            return
        answer = QMessageBox.question(
            self, "Delete", f"Permanently delete {usage.kind.lower()} “{usage.name}” "
                            f"({disk.format_size(usage.size)})?\n\n{usage.path}")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if usage.kind == disk.ENV:
            fn = lambda ctx: venvs.delete(usage.payload, ctx)  # noqa: E731
        else:
            fn = lambda ctx: python_versions.uninstall(usage.payload, ctx)  # noqa: E731

        def done(_):
            self.state.refresh()
            self.scan()

        self.tasks.run(f"Deleting {usage.name}", fn, done)
