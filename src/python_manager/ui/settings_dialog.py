"""Application settings: backend, defaults for new environments, scheduled checks and disk usage."""

from __future__ import annotations

import shutil

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ..core import config, paths
from .state import AppState
from .widgets import button

FIRST = "First in the list"


class SettingsDialog(QDialog):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        self.use_uv = QCheckBox("Use uv for packages and environments when it is installed")
        self.use_uv.setChecked(bool(config.get("use_uv")))
        uv = shutil.which("uv")
        uv_status = QLabel(f"uv found at {uv}" if uv else "uv was not found on PATH; pip and venv are used")
        uv_status.setEnabled(False)  # greyed out: information, not a control
        general = QGroupBox("Backend")
        glay = QVBoxLayout(general)
        glay.addWidget(self.use_uv)
        glay.addWidget(uv_status)

        self.default_python = QComboBox()
        self.default_python.addItem(FIRST, "")
        saved = config.get("default_python") or ""
        for interp in state.interpreters(include_envs=False):
            self.default_python.addItem(interp.label, str(interp.executable))
        index = self.default_python.findData(saved)
        if saved and index < 0:  # no longer installed: keep it visible rather than silently dropping it
            self.default_python.addItem(f"{saved} (not found)", saved)
            index = self.default_python.count() - 1
        self.default_python.setCurrentIndex(max(index, 0))
        self.location = QLineEdit(config.get("envs_location") or "", placeholderText=str(paths.envs_dir()))
        loc_row = QHBoxLayout()
        loc_row.addWidget(self.location, 1)
        loc_row.addWidget(button("Browse…", self._browse))
        envs = QGroupBox("New environments")
        elay = QFormLayout(envs)
        elay.addRow("Default Python:", self.default_python)
        elay.addRow("Location:", loc_row)

        self.auto_check = QCheckBox("Check environments for outdated and vulnerable packages automatically")
        self.auto_check.setChecked(bool(config.get("auto_check")))
        self.hours = QSpinBox(minimum=1, maximum=24 * 30, suffix=" hours")
        self.hours.setValue(int(config.get("auto_check_hours") or 24))
        self.security = QCheckBox("Include the security check (sends package names and versions to osv.dev)")
        self.security.setChecked(bool(config.get("auto_check_security")))
        self.notify = QCheckBox("Show a desktop notification when something needs attention")
        self.notify.setChecked(bool(config.get("notify")))
        for widget in (self.hours, self.security, self.notify):
            self.auto_check.toggled.connect(widget.setEnabled)
            widget.setEnabled(self.auto_check.isChecked())
        checks = QGroupBox("Scheduled checks")
        clay = QFormLayout(checks)
        clay.addRow(self.auto_check)
        clay.addRow("Every:", self.hours)
        clay.addRow(self.security)
        clay.addRow(self.notify)

        self.stale_days = QSpinBox(minimum=7, maximum=3650, suffix=" days")
        self.stale_days.setValue(int(config.get("stale_days") or 180))
        disk = QGroupBox("Disk usage")
        dlay = QFormLayout(disk)
        dlay.addRow("Flag environments unchanged for:", self.stale_days)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for box in (general, envs, checks, disk):
            layout.addWidget(box)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Location for new environments",
                                                  self.location.text() or str(paths.envs_dir()))
        if folder:
            self.location.setText(folder)

    def save(self) -> None:
        data = config.load()
        data.update(
            use_uv=self.use_uv.isChecked(),
            default_python=self.default_python.currentData() or "",
            envs_location=self.location.text().strip(),
            auto_check=self.auto_check.isChecked(),
            auto_check_hours=self.hours.value(),
            auto_check_security=self.security.isChecked(),
            notify=self.notify.isChecked(),
            stale_days=self.stale_days.value(),
        )
        config.save(data)
