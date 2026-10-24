"""Light, dark or system colours, and status colours that stay readable in either."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QTableWidget, QTableWidgetItem

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
MODES = {SYSTEM: "Same as the system", LIGHT: "Light", DARK: "Dark"}

# Status colour name -> (on a light background, on a dark background).
COLORS = {
    "error": ("#c62828", "#ef5350"),
    "warning": ("#ef6c00", "#ffa726"),
    "ok": ("#2e7d32", "#66bb6a"),
    "muted": ("#757575", "#9e9e9e"),
}

COLOR_ROLE = Qt.ItemDataRole.UserRole + 41  # the colour name painted on a table cell

_original: dict = {}  # the platform's style and palette, restored for SYSTEM


def _dark_palette() -> QPalette:
    p = QPalette()
    window, base, text = QColor("#2b2b2b"), QColor("#1f1f1f"), QColor("#e6e6e6")
    disabled = QColor("#7f7f7f")
    roles = {
        QPalette.ColorRole.Window: window,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: QColor("#262626"),
        QPalette.ColorRole.ToolTipBase: QColor("#3c3c3c"),
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.PlaceholderText: disabled,
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: QColor("#353535"),
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.BrightText: QColor("#ff5252"),
        QPalette.ColorRole.Light: QColor("#4a4a4a"),
        QPalette.ColorRole.Midlight: QColor("#3e3e3e"),
        QPalette.ColorRole.Mid: QColor("#555555"),
        QPalette.ColorRole.Dark: QColor("#191919"),
        QPalette.ColorRole.Shadow: QColor("#000000"),
        QPalette.ColorRole.Highlight: QColor("#2f65ca"),
        QPalette.ColorRole.HighlightedText: QColor("#ffffff"),
        QPalette.ColorRole.Link: QColor("#64b5f6"),
        QPalette.ColorRole.LinkVisited: QColor("#ba68c8"),
    }
    for role, color in roles.items():
        p.setColor(role, color)
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, disabled)
    return p


def _set_color_scheme(app: QApplication, mode: str) -> None:
    """Qt 6.8+: tells the platform too, e.g. for a dark title bar on Windows."""
    hints = app.styleHints()
    if not hasattr(hints, "setColorScheme"):
        return
    scheme = {LIGHT: Qt.ColorScheme.Light, DARK: Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
    hints.setColorScheme(scheme)


def apply(mode: str, app: Optional[QApplication] = None) -> None:
    app = app or QApplication.instance()
    if not _original:
        _original["style"] = app.style().name()
    _set_color_scheme(app, mode)
    if mode in (LIGHT, DARK):
        fusion = QStyleFactory.create("Fusion")
        app.setStyle(fusion)
        app.setPalette(_dark_palette() if mode == DARK else fusion.standardPalette())
    else:
        app.setStyle(QStyleFactory.create(_original["style"]))
        app.setPalette(QPalette())  # an empty palette drops the override: the platform's colours return
    repaint_tables(app)


def is_dark(app: Optional[QApplication] = None) -> bool:
    app = app or QApplication.instance()
    return app is not None and app.palette().color(QPalette.ColorRole.Base).lightness() < 128


def color(name: str) -> str:
    light, dark = COLORS[name]
    return dark if is_dark() else light


def paint(item: Optional[QTableWidgetItem], name: str) -> None:
    """Colour a cell's text with a status colour that follows the theme."""
    if item is None:
        return
    item.setData(COLOR_ROLE, name)
    item.setForeground(QBrush(QColor(color(name))))


def repaint_tables(app: QApplication) -> None:
    """Recolour cells painted with :func:`paint` after the theme changed."""
    for widget in app.allWidgets():
        if not isinstance(widget, QTableWidget):
            continue
        for row in range(widget.rowCount()):
            for col in range(widget.columnCount()):
                item = widget.item(row, col)
                name = item.data(COLOR_ROLE) if item else None
                if name in COLORS:
                    item.setForeground(QBrush(QColor(color(name))))
