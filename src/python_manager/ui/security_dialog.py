"""Dialog listing known vulnerabilities in the installed packages."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..core import security
from ..core.security import Vulnerability
from .widgets import fill_table, make_table, selected_payload


class SecurityDialog(QDialog):
    def __init__(self, vulns: list[Vulnerability], env_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Security check · {env_name}")
        self.resize(900, 460)
        self.specs = security.upgrade_specs(vulns)

        packages = len({v.package.lower() for v in vulns})
        summary = QLabel(f"{len(vulns)} known vulnerabilities in {packages} packages. "
                         "Double-click a row to open its details on osv.dev.")
        summary.setWordWrap(True)
        self.table = make_table(["Package", "Version", "Vulnerability", "Severity", "Fixed in", "Summary"], stretch=5)
        fill_table(self.table, [(v, (v.package, v.version, v.title, v.severity, v.fixed or "no fix yet", v.summary))
                                for v in vulns])
        self.table.doubleClicked.connect(self._open)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        upgrade = buttons.addButton("Upgrade to fixed versions", QDialogButtonBox.ButtonRole.AcceptRole)
        upgrade.setEnabled(bool(self.specs))
        upgrade.setToolTip("\n".join(self.specs) or "No fixed versions are known")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def _open(self) -> None:
        vuln = selected_payload(self.table)
        if vuln:
            QDesktopServices.openUrl(QUrl(vuln.url))
