"""Preview what a requirements file, pyproject.toml or pylock.toml would install, then install it."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core import projectfile, projects
from ..core.projects import Check, Source
from .tasks import TaskManager
from .widgets import color_rows, fill_table, loading_overlay, make_table

COLORS = {projects.OK: "muted", projects.MISSING: "error", projects.MISMATCH: "warning",
          projects.UNCHECKED: "warning"}


class InstallFileDialog(QDialog):
    """After ``exec``, ``source`` and ``only`` are the arguments for ``projects.install_source``."""

    def __init__(self, python: Path, path: Path, tasks: TaskManager, parent: QWidget = None):
        super().__init__(parent)
        self.python, self.path, self.tasks = python, Path(path), tasks
        self.checks: list[Check] = []
        self._generation = 0
        self.setWindowTitle(f"Install from {self.path.name}")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(str(self.path)))

        self.options: list[tuple[str, str, QCheckBox]] = []  # ("extra" or "group", name, box)
        if self.path.name.endswith(".toml") and not projectfile.is_pylock(self.path):
            extras, groups = projectfile.pyproject_options(self.path)
            for kind, names, title in (("extra", extras, "Extras"), ("group", groups, "Dependency groups")):
                if not names:
                    continue
                box, row = QGroupBox(title), QHBoxLayout()
                box.setLayout(row)
                for name in names:
                    check = QCheckBox(name)
                    check.toggled.connect(lambda _: self.load())
                    row.addWidget(check)
                    self.options.append((kind, name, check))
                row.addStretch(1)
                layout.addWidget(box)

        self.only_needed = QCheckBox("Only install missing packages and wrong versions")
        self.only_needed.setChecked(True)
        self.only_needed.toggled.connect(self._render)
        self.table = make_table(["Package", "Requirement", "Installed", "Status"], stretch=1)
        self.overlay = loading_overlay(self.table)
        self.summary = QLabel()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.install_btn = self.buttons.addButton("Install", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.only_needed)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        layout.addWidget(self.buttons)
        self.load()

    @property
    def source(self) -> Source:
        chosen = lambda kind: tuple(n for k, n, box in self.options if k == kind and box.isChecked())  # noqa: E731
        return Source(self.path, chosen("extra"), chosen("group"))

    @property
    def only(self) -> Optional[list[str]]:
        """The requirements to install; None for all of them."""
        if not self.only_needed.isChecked():
            return None
        needed = [c.requirement for c in self.checks if c.status in projects.NEEDS_INSTALL]
        return None if len(needed) == len(self.checks) and not self.path.name.endswith(".toml") else needed

    def load(self) -> None:
        self._generation += 1
        generation, source = self._generation, self.source
        self.checks = []
        self.overlay.start("Comparing with the installed packages…")
        self._render()

        def done(checks: list[Check]) -> None:
            if generation == self._generation:
                self.overlay.stop()
                self.checks = checks
                self._render()

        def failed(message: str) -> None:
            if generation == self._generation:
                self.overlay.stop()
                self.summary.setText(f"Could not read {self.path.name}: {message.splitlines()[0] if message else ''}")

        self.tasks.run(f"Reading {self.path.name}",
                       lambda _: projects.compare(projects.read_requirements(source), self.python),
                       done, failed, foreground=False)

    def _render(self) -> None:
        fill_table(self.table, [(c, (c.name, c.requirement, c.installed or "—", c.status)) for c in self.checks])
        color_rows(self.table, 3, COLORS)
        needed = [c for c in self.checks if c.status in projects.NEEDS_INSTALL]
        if self.checks:
            self.summary.setText(f"{len(self.checks)} requirements apply to this Python: {len(needed)} to install, "
                                 f"{len(self.checks) - len(needed)} already satisfied.")
        elif not self.overlay.active:
            self.summary.setText(f"{self.source.label} lists no requirements for this Python.")
        else:
            self.summary.setText("")
        self.install_btn.setEnabled(bool(needed) if self.only_needed.isChecked() else bool(self.checks))
