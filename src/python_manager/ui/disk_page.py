"""Disk space used by environments, installed Pythons and package caches."""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from ..core import config, disk, python_versions, venvs
from ..core.disk import Usage
from . import theme
from .state import AppState
from .tasks import TaskManager
from .widgets import button, button_row, fill_table, loading_overlay, make_table, open_folder, selected_payloads



class DiskPage(QWidget):
    def __init__(self, state: AppState, tasks: TaskManager):
        super().__init__()
        self.state, self.tasks = state, tasks
        self.scanned = False

        self.table = make_table(["Type", "Name", "Size", "Note", "Location"], stretch=4, multi=True)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.overlay = loading_overlay(self.table)
        self.total = QLabel("Sizes are calculated when this page is opened.")
        self.clean_btn = button("Clean", self.clean, "Empty the selected cache")
        self.delete_btn = button("Delete", self.delete, "Delete the selected environments or Pythons")
        self.stale_btn = button("Select stale", self.select_stale,
                                "Select environments whose Python is gone or that have not changed for a long time")
        self.folder_btn = button("Open folder", lambda: self._with_selected(lambda u: open_folder(u.path)))
        layout = QVBoxLayout(self)
        layout.addLayout(button_row(button("Refresh", self.scan)))
        layout.addWidget(self.table)
        layout.addWidget(self.total)
        layout.addLayout(button_row(self.clean_btn, self.delete_btn, self.stale_btn, self.folder_btn))
        self._update_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.scanned:
            self.scanned = True
            self.scan()

    def scan(self) -> None:
        self.total.setText("Calculating sizes…")
        self.overlay.start("Calculating folder sizes…")

        def done(items: list[Usage]):
            self.overlay.stop()
            fill_table(self.table, [(u, (u.kind, u.name, (disk.format_size(u.size), u.size), u.note, str(u.path)))
                                    for u in items])
            for row in range(self.table.rowCount()):
                note = self.table.item(row, 3)
                if note.text():
                    theme.paint(note, "error" if note.text() == disk.BROKEN else "warning")
            caches = sum(u.size for u in items if u.cleanable)
            stale = [u for u in items if u.stale]
            text = f"Total: {disk.format_size(sum(u.size for u in items))} · caches: {disk.format_size(caches)}"
            if stale:
                text += f" · {len(stale)} stale environment{'s' * (len(stale) != 1)}: " \
                        f"{disk.format_size(sum(u.size for u in stale))}"
            self.total.setText(text)
            self._update_buttons()

        def failed(message: str):
            self.overlay.stop()
            self.total.setText(f"Could not calculate sizes: {message.splitlines()[0]}")

        self.tasks.run("Calculating disk usage", disk.scan, done, failed, foreground=False)

    def _selected_all(self) -> list[Usage]:
        return selected_payloads(self.table)

    def _selected(self) -> Usage | None:
        """The selected row when exactly one is selected."""
        items = self._selected_all()
        return items[0] if len(items) == 1 else None

    def _with_selected(self, fn) -> None:
        usage = self._selected()
        if usage:
            fn(usage)

    def _deletable(self) -> list[Usage]:
        return [u for u in self._selected_all() if u.kind in (disk.ENV, disk.PYTHON)]

    def _update_buttons(self) -> None:
        usage = self._selected()
        self.clean_btn.setEnabled(bool(usage and usage.cleanable))
        self.delete_btn.setEnabled(bool(self._deletable()))
        self.folder_btn.setEnabled(usage is not None)

    def select_stale(self) -> None:
        self.table.clearSelection()
        model, found = self.table.selectionModel(), 0
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole).stale:
                found += 1
                model.select(self.table.model().index(row, 0),
                             QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        if not found:
            days = int(config.get("stale_days") or 180)
            QMessageBox.information(self, "Select stale", "No environment is broken or unchanged for "
                                                          f"{days} days (change the limit in Settings).")

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
        items = self._deletable()
        if not items:
            return
        total = disk.format_size(sum(u.size for u in items))
        listed = "\n".join(f"• {u.name} ({disk.format_size(u.size)})" for u in items[:15])
        more = f"\n… and {len(items) - 15} more" if len(items) > 15 else ""
        what = f"{items[0].kind.lower()} “{items[0].name}”" if len(items) == 1 else f"{len(items)} items"
        answer = QMessageBox.question(self, "Delete", f"Permanently delete {what} ({total})?\n\n{listed}{more}")
        if answer != QMessageBox.StandardButton.Yes:
            return

        def delete_all(ctx):
            for done, usage in enumerate(items):
                ctx.check()
                ctx.progress(done, len(items))
                if usage.kind == disk.ENV:
                    venvs.delete(usage.payload, ctx)
                else:
                    python_versions.uninstall(usage.payload, ctx)

        def done(_):
            self.state.refresh()
            self.scan()

        title = f"Deleting {items[0].name}" if len(items) == 1 else f"Deleting {len(items)} items"
        self.tasks.run(title, delete_all, done)
