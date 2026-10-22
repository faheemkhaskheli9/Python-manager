"""Small reusable widgets and helpers."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


def make_table(headers: Sequence[str], stretch: int = -1, multi: bool = False) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(list(headers))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection if multi else QAbstractItemView.SelectionMode.SingleSelection
    )
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # keep insertion order until a header is clicked
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch if stretch >= 0 else len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    return table


class SortedItem(QTableWidgetItem):
    """A cell that sorts by a key other than its text, e.g. a size in bytes."""

    def __init__(self, text: str, key: Any):
        super().__init__(text)
        self.key = key

    def __lt__(self, other) -> bool:
        if isinstance(other, SortedItem):
            return self.key < other.key
        return super().__lt__(other)


def fill_table(table: QTableWidget, rows: Iterable[tuple[Any, Sequence[Any]]]) -> None:
    """Replace table contents. Each row is (payload, cells); payload is kept on column 0.

    A cell is its text, or a (text, sort key) pair.
    """
    table.setUpdatesEnabled(False)  # one repaint at the end instead of one per cell
    table.setSortingEnabled(False)
    table.setRowCount(0)
    for payload, cells in rows:
        row = table.rowCount()
        table.insertRow(row)
        for col, cell in enumerate(cells):
            if isinstance(cell, tuple):
                text = cell[0]
                item = SortedItem(str(text), cell[1])
            else:
                text = cell
                item = QTableWidgetItem(str(text))
            item.setToolTip(str(text))
            if col == 0:
                item.setData(Qt.ItemDataRole.UserRole, payload)
            table.setItem(row, col, item)
    table.setSortingEnabled(True)
    table.setUpdatesEnabled(True)


def color_rows(table: QTableWidget, column: int, colors: dict[str, str]) -> None:
    """Colour each row's ``column`` text by its value, e.g. {"Missing": "#c62828"}."""
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item and item.text() in colors:
            item.setForeground(QBrush(QColor(colors[item.text()])))


def selected_payloads(table: QTableWidget) -> list[Any]:
    rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
    return [table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]


def selected_payload(table: QTableWidget) -> Optional[Any]:
    items = selected_payloads(table)
    return items[0] if items else None


def button_row(*buttons: QWidget, stretch_first: bool = False) -> QHBoxLayout:
    layout = QHBoxLayout()
    if stretch_first:
        layout.addStretch(1)
    for button in buttons:
        layout.addWidget(button)
    if not stretch_first:
        layout.addStretch(1)
    return layout


def button(text: str, slot, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.clicked.connect(slot)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def open_folder(path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class LogView(QPlainTextEdit):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

    def append_line(self, text: str) -> None:
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class LoadingOverlay(QWidget):
    """A spinner and a message drawn over a widget (e.g. a table's viewport) while its data loads."""

    def __init__(self, target: QWidget):
        super().__init__(target)
        self._text = ""
        self._angle = 0
        self._timer = QTimer(self, interval=60)
        self._timer.timeout.connect(self._spin)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        target.installEventFilter(self)
        self.hide()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self, text: str = "Loading…") -> None:
        self._text = text
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _spin(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        veil = self.palette().color(QPalette.ColorRole.Base)
        veil.setAlpha(190)
        painter.fillRect(self.rect(), veil)
        size = 28
        box = QRectF(self.width() / 2 - size / 2, self.height() / 2 - size, size, size)
        track = self.palette().color(QPalette.ColorRole.Mid)
        painter.setPen(QPen(track, 3))
        painter.drawEllipse(box)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 3,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(box, -self._angle * 16, 100 * 16)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        text_box = QRectF(0, box.bottom() + 8, self.width(), 24)
        painter.drawText(text_box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._text)


def loading_overlay(table: QTableWidget) -> LoadingOverlay:
    """An overlay over the rows of ``table`` that keeps the header visible."""
    return LoadingOverlay(table.viewport())
