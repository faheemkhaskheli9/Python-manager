"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
)

from .. import __version__
from ..core import paths
from .packages_page import PackagesPage
from .pythons_page import PythonsPage
from .state import AppState
from .tasks import TaskManager
from .venvs_page import VenvsPage
from .widgets import LogView, open_folder


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Manager")
        self.resize(1100, 760)

        self.tasks = TaskManager(self)
        self.state = AppState(self.tasks)

        self.pythons = PythonsPage(self.state, self.tasks)
        self.packages = PackagesPage(self.state, self.tasks)
        self.venvs = VenvsPage(self.state, self.tasks, self.show_packages_for)

        self.stack = QStackedWidget()
        self.nav = QListWidget()
        for title, page in (("Python Versions", self.pythons), ("Packages", self.packages),
                            ("Virtual Environments", self.venvs)):
            self.nav.addItem(title)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setFixedWidth(190)
        splitter = QSplitter()
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.log = LogView()
        dock = QDockWidget("Output", self)
        dock.setObjectName("output")
        dock.setWidget(self.log)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        self.status_label = QLabel("Ready")
        self.progress = QProgressBar(maximumWidth=220)
        self.progress.hide()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.tasks.cancel)
        self.cancel_btn.hide()
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_btn)

        self.tasks.log.connect(self.log.append_line)
        self.tasks.started.connect(self._task_started)
        self.tasks.progress.connect(self._task_progress)
        self.tasks.finished.connect(self._task_finished)

        self._build_menu(dock)
        self.nav.setCurrentRow(0)
        self.state.refresh(include_system=True)

    def _build_menu(self, dock: QDockWidget) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_data = QAction("Open data folder", self)
        open_data.triggered.connect(lambda: open_folder(paths.data_dir()))
        file_menu.addAction(open_data)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(dock.toggleViewAction())

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("About", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def show_packages_for(self, executable) -> None:
        self.packages.select(executable)
        self.nav.setCurrentRow(1)

    def _task_started(self, title: str) -> None:
        self.status_label.setText(title + "…")
        self.progress.setRange(0, 0)  # busy indicator until real progress arrives
        self.progress.show()
        self.cancel_btn.show()

    def _task_progress(self, done: int, total: int) -> None:
        if total > 0:
            # Scale to keep large byte counts within the int range of QProgressBar.
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            if total > 1024 * 1024:
                self.progress.setFormat(f"{done / 1048576:.1f} / {total / 1048576:.1f} MB")
            else:
                self.progress.setFormat("%p%")

    def _task_finished(self, message: str) -> None:
        self.status_label.setText(message)
        self.progress.hide()
        self.progress.setFormat("%p%")
        self.cancel_btn.hide()

    def _about(self) -> None:
        QMessageBox.about(
            self, "About Python Manager",
            f"<b>Python Manager {__version__}</b><p>Install Python versions, manage packages and "
            f"virtual environments.</p><p>Python builds: python-build-standalone.<br>"
            f"Data folder: {paths.data_dir()}</p>")

    def closeEvent(self, event) -> None:
        if self.tasks.busy:
            answer = QMessageBox.question(self, "Quit", "An operation is still running. Cancel it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.tasks.cancel()
        super().closeEvent(event)
