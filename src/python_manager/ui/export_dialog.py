"""Choose an export format for an environment and write it."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..core import lock
from ..core.lock import Format
from .tasks import TaskManager


class ExportDialog(QDialog):
    def __init__(self, env_name: str, parent=None, default: Format = lock.PINNED):
        super().__init__(parent)
        self.setWindowTitle(f"Export · {env_name}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Save the packages of {env_name} as:"))
        self.group = QButtonGroup(self)
        for index, fmt in enumerate(lock.FORMATS):
            radio = QRadioButton(fmt.label)
            radio.setChecked(fmt is default)
            hint = QLabel(fmt.description + (" Downloads file hashes from PyPI." if fmt.online else ""))
            hint.setWordWrap(True)
            hint.setContentsMargins(24, 0, 0, 6)
            hint.setEnabled(False)  # greyed out: a description, not a control
            self.group.addButton(radio, index)
            layout.addWidget(radio)
            layout.addWidget(hint)
        self.exclude = QCheckBox("Leave out pip, setuptools and wheel")
        self.exclude.setChecked(True)
        layout.addWidget(self.exclude)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save…", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def format(self) -> Format:
        return lock.FORMATS[self.group.checkedId()]


def export_environment(parent: QWidget, tasks: TaskManager, python: Path, env_name: str, python_version: str,
                       folder: Optional[Path] = None, default: Format = lock.PINNED) -> None:
    """Ask for a format and a file, then export in the background and report the result."""
    dialog = ExportDialog(env_name, parent, default)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    fmt, exclude = dialog.format, dialog.exclude.isChecked()
    start = str((folder or Path.home()) / fmt.filename)
    suffix = Path(fmt.filename).suffix
    path, _ = QFileDialog.getSaveFileName(parent, f"Export {env_name}", start, f"{fmt.filename} (*{suffix})")
    if not path:
        return
    name = Path(path).name
    if fmt is lock.PYLOCK and not re.fullmatch(r"pylock\.([^.]+\.)?toml", name):
        # Installers only accept pylock.toml or pylock.<name>.toml.
        path = str(Path(path).with_name(f"pylock.{Path(name).stem.replace('.', '-')}.toml"))

    def done(result: lock.Result):
        text = f"Saved {result.packages} packages to {result.path}."
        if result.skipped:
            QMessageBox.warning(parent, "Export", text + "\n\nNot on PyPI, so left out:\n" + "\n".join(result.skipped))
        else:
            QMessageBox.information(parent, "Export", text)

    tasks.run(f"Exporting {env_name}",
              lambda ctx: lock.export(python, fmt, Path(path), env_name, python_version, ctx, exclude), done)
