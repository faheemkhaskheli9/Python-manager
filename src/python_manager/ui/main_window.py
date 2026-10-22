"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
    QSystemTrayIcon,
)

from .. import __version__
from ..core import config, health, logs, packages, paths
from .disk_page import DiskPage
from .packages_page import PackagesPage
from .projects_page import ProjectsPage
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
        self.projects = ProjectsPage(self.state, self.tasks, self.show_packages_for)
        self.disk = DiskPage(self.state, self.tasks)

        self.stack = QStackedWidget()
        self.nav = QListWidget()
        for title, page in (("Python Versions", self.pythons), ("Packages", self.packages),
                            ("Virtual Environments", self.venvs), ("Projects", self.projects),
                            ("Disk Usage", self.disk)):
            self.nav.addItem(title)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setFixedWidth(190)
        splitter = QSplitter()
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 1000])
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

        self.tray: QSystemTrayIcon | None = None
        self._checking = False
        self.check_timer = QTimer(self, interval=30 * 60 * 1000)  # is a scheduled check due?
        self.check_timer.timeout.connect(self._maybe_check)
        self.check_timer.start()
        self.state.health_changed.connect(self._update_nav_badges)
        self.state.changed.connect(self._update_nav_badges)
        self.state.changed.connect(self._first_check)

        self._build_menu(dock)
        self.nav.setCurrentRow(0)
        self._update_nav_badges()
        self.state.refresh(include_system=True)

    def _build_menu(self, dock: QDockWidget) -> None:
        file_menu = self.menuBar().addMenu("&File")
        open_data = QAction("Open data folder", self)
        open_data.triggered.connect(lambda: open_folder(paths.data_dir()))
        file_menu.addAction(open_data)
        open_log = QAction("Open log file", self)
        open_log.triggered.connect(self._open_log)
        file_menu.addAction(open_log)
        use_uv = QAction("Use uv when installed", self, checkable=True)
        use_uv.setChecked(bool(config.get("use_uv")))
        use_uv.setToolTip("Faster installs and environment creation with uv (https://docs.astral.sh/uv/)")
        use_uv.toggled.connect(self._set_use_uv)
        file_menu.addAction(use_uv)
        file_menu.addSeparator()
        check_now = QAction("Check environments now", self)
        check_now.setToolTip("Look for outdated and vulnerable packages in every environment")
        check_now.triggered.connect(lambda: self.check_environments(manual=True))
        file_menu.addAction(check_now)
        auto_check = QAction("Check environments daily", self, checkable=True)
        auto_check.setChecked(bool(config.get("auto_check")))
        auto_check.toggled.connect(lambda on: config.set("auto_check", on))
        file_menu.addAction(auto_check)
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

    def _set_use_uv(self, enabled: bool) -> None:
        config.set("use_uv", enabled)
        backend = packages.backend()
        if enabled and backend != "uv":
            self.status_label.setText("uv was not found on PATH; using pip")
        else:
            self.status_label.setText(f"Using {backend} for packages and environments")
        self.packages.reload()

    # Scheduled checks --------------------------------------------------------

    def _first_check(self) -> None:
        self.state.changed.disconnect(self._first_check)
        self._maybe_check()

    def _maybe_check(self) -> None:
        if health.is_due() and not self.state.loading:
            self.check_environments(manual=False)

    def check_environments(self, manual: bool) -> None:
        """Check environments for outdated and vulnerable packages; notify when something is found."""
        if self._checking:
            return
        targets = [i.executable for i in self.state.checked_interpreters()]
        if not targets:
            if manual:
                self.status_label.setText("No environments to check")
            return

        def done(reports):
            self._checking = False
            self.state.set_health(reports)
            message = health.summarize(reports[str(t)] for t in targets if str(t) in reports)
            self.status_label.setText(message or f"Checked {len(targets)} environments: all up to date")
            if message:
                self._notify("Packages need attention", message)

        def failed(message):
            self._checking = False
            self.status_label.setText(f"Environment check failed: {message.splitlines()[0]}")

        self._checking = True
        started = self.tasks.run(f"Checking {len(targets)} environments",
                                 lambda ctx: health.check_all(targets, ctx), done, failed, foreground=manual)
        if not started:
            self._checking = False

    def _notify(self, title: str, message: str) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull()
                                        else self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon),
                                        self)
            self.tray.setToolTip("Python Manager")
            self.tray.messageClicked.connect(lambda: (self.nav.setCurrentRow(2), self.showNormal(), self.raise_()))
            self.tray.show()
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning)

    def _update_nav_badges(self) -> None:
        reports = (self.state.health.get(str(e.executable)) for e in self.state.envs)
        flagged = sum(bool(r and r.needs_attention) for r in reports)
        item = self.nav.item(2)
        item.setText(f"Virtual Environments ({flagged})" if flagged else "Virtual Environments")
        item.setToolTip(f"{flagged} environments have outdated or vulnerable packages" if flagged else "")

    def _open_log(self) -> None:
        path = logs.setup()
        path.touch()
        open_folder(path)

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
            f"Data folder: {paths.data_dir()}<br>Log file: {logs.log_file()}</p>")

    def closeEvent(self, event) -> None:
        if self.tasks.busy:
            answer = QMessageBox.question(self, "Quit", "An operation is still running. Cancel it and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.tasks.cancel()
        super().closeEvent(event)
