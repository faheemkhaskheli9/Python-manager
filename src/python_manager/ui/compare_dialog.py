"""Compare the packages of two interpreters or environments side by side."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..core import compare, history, packages
from ..core.interpreters import CONDA, Interpreter
from .tasks import TaskManager
from .widgets import color_rows, fill_table, loading_overlay, make_table

COLORS = {compare.DIFFERENT: "warning", compare.ONLY_LEFT: "error", compare.ONLY_RIGHT: "error",
          compare.SAME: "muted"}


class CompareDialog(QDialog):
    def __init__(self, interpreters: list[Interpreter], tasks: TaskManager, parent: QWidget = None,
                 left: Optional[Interpreter] = None):
        super().__init__(parent)
        self.interpreters, self.tasks = interpreters, tasks
        self.rows: list[compare.Row] = []
        self.changed = False  # packages were installed, so the caller should reload
        self._generation = 0
        self.setWindowTitle("Compare environments")
        self.resize(820, 560)

        self.left, self.right = QComboBox(), QComboBox()
        for combo in (self.left, self.right):
            for interp in interpreters:
                combo.addItem(interp.label, interp)
            combo.currentIndexChanged.connect(lambda _: self.load())
        start = next((i for i, p in enumerate(interpreters) if left and p.executable == left.executable), 0)
        for combo, index in ((self.left, start), (self.right, 1 if start == 0 and len(interpreters) > 1 else 0)):
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Left:"))
        pick.addWidget(self.left, 1)
        pick.addWidget(QLabel("Right:"))
        pick.addWidget(self.right, 1)

        self.hide_same = QCheckBox("Hide identical packages")
        self.hide_same.setChecked(True)
        self.hide_same.toggled.connect(self._render)
        self.table = make_table(["Package", "Left", "Right", "Difference"], stretch=0)
        self.overlay = loading_overlay(self.table)
        self.summary = QLabel()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.match_btn = buttons.addButton("Install left versions on right",
                                           QDialogButtonBox.ButtonRole.ActionRole)
        self.match_btn.setToolTip("Install the left side's version of every package that differs or is missing "
                                  "on the right; packages only on the right stay")
        self.match_btn.clicked.connect(self.match_left)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(pick)
        layout.addWidget(self.hide_same)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        layout.addWidget(buttons)
        self.load()

    def load(self) -> None:
        left, right = self.left.currentData(), self.right.currentData()
        self.rows = []
        self._render()
        if left is None or right is None:
            return
        self._generation += 1
        generation = self._generation

        def done(rows) -> None:
            if generation == self._generation:
                self.overlay.stop()
                self.rows = rows
                self._render()

        def failed(message: str) -> None:
            if generation == self._generation:
                self.overlay.stop()
                self.summary.setText(f"Could not compare: {message.splitlines()[0] if message else ''}")

        self.overlay.start("Reading packages…")
        self.tasks.run(f"Comparing {left.name} and {right.name}",
                       lambda _: compare.diff(packages.installed(left.executable), packages.installed(right.executable)),
                       done, failed, foreground=False)

    def _render(self) -> None:
        shown = [r for r in self.rows if not (self.hide_same.isChecked() and r.status == compare.SAME)]
        fill_table(self.table, [(r, (r.name, r.left or "—", r.right or "—", r.status)) for r in shown])
        color_rows(self.table, 3, COLORS)
        if self.rows:
            counts = compare.summary(self.rows)
            self.summary.setText(", ".join(f"{k}: {n}" for k, n in counts.items()) + ".")
        else:
            self.summary.setText("")
        right = self.right.currentData()
        self.match_btn.setEnabled(bool(compare.match_left(self.rows)) and bool(right) and right.kind != CONDA
                                  and self.left.currentIndex() != self.right.currentIndex())

    def match_left(self) -> None:
        right: Interpreter = self.right.currentData()
        specs = compare.match_left(self.rows)
        if not right or not specs:
            return
        text = f"Install these versions into {right.name}?\n\n" + "\n".join(specs[:30])
        if len(specs) > 30:
            text += f"\n… and {len(specs) - 30} more"
        if QMessageBox.question(self, "Install left versions", text) != QMessageBox.StandardButton.Yes:
            return

        def done(_) -> None:
            self.changed = True
            self.load()

        def install(ctx) -> None:
            history.snapshot(right.executable, f"Installing {self.left.currentData().name}'s versions")
            packages.install(right.executable, specs, ctx)

        self.tasks.run(f"Installing {len(specs)} packages into {right.name}", install, done)
