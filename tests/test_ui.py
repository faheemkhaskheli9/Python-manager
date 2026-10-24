"""Smoke tests that build the windows offscreen and click through them."""

import csv
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from python_manager.core import config, licenses  # noqa: E402
from python_manager.ui import theme  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    """The QApplication, with message boxes answered automatically so nothing blocks."""
    application = QApplication.instance() or QApplication([])
    config.set("auto_check", False)
    shown = []
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _n=name, **k: shown.append((_n, a[1:3])))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    application.shown_messages = shown
    yield application
    QThreadPool.globalInstance().waitForDone(30000)
    application.processEvents()
    theme.apply(theme.SYSTEM, application)


def wait_until(app, condition, timeout=60.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise TimeoutError("condition not met")
        app.processEvents()
        time.sleep(0.02)


def test_main_window_pages(app, monkeypatch):
    from python_manager.ui import licenses_dialog
    from python_manager.ui.main_window import MainWindow

    opened = []
    monkeypatch.setattr(licenses_dialog.LicensesDialog, "exec", lambda self: opened.append(self.items))

    window = MainWindow()
    window.show()
    wait_until(app, lambda: not window.state.loading)
    for row in range(window.nav.count()):
        window.nav.setCurrentRow(row)
        app.processEvents()
        assert window.stack.currentIndex() == row
    wait_until(app, lambda: not window.tasks.busy)
    assert window.packages.target.count() >= 1  # at least the Python running the tests
    window.packages.show_licenses()
    wait_until(app, lambda: opened)
    assert opened[0] and all(isinstance(i, licenses.PackageLicense) for i in opened[0])
    window.close()


def test_theme_switch(app):
    for mode in (theme.DARK, theme.LIGHT, theme.SYSTEM):
        theme.apply(mode, app)
        app.processEvents()
    theme.apply(theme.DARK, app)
    assert app.palette().color(app.palette().ColorRole.Window).lightness() < 128


def test_licenses_dialog(app, tmp_path, monkeypatch):
    from python_manager.ui.licenses_dialog import LicensesDialog

    items = [licenses.resolve({"name": "a", "version": "1", "expression": "MIT"}),
             licenses.resolve({"name": "b", "version": "2", "license": "GPL-3.0"}),
             licenses.resolve({"name": "c", "version": "3"})]
    dialog = LicensesDialog(items, "env", folder=tmp_path)
    assert dialog.table.rowCount() == 3
    dialog.category.setCurrentText(licenses.COPYLEFT)
    assert [i.name for i in dialog.visible_items()] == ["b"]
    dialog.category.setCurrentText("All categories")
    dialog.filter.setText("mit")
    assert dialog.table.rowCount() == 1

    target = tmp_path / "report"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "CSV (*.csv)"))
    dialog.filter.clear()
    dialog.save()
    rows = list(csv.reader((tmp_path / "report.csv").open(encoding="utf-8")))
    assert [r[0] for r in rows] == ["Package", "a", "b", "c"]
    assert app.shown_messages[-1][0] == "information"


def test_settings_package_index(app):
    from python_manager.core import indexes
    from python_manager.ui.settings_dialog import SettingsDialog
    from python_manager.ui.state import AppState
    from python_manager.ui.tasks import TaskManager

    window = QtWidgets.QWidget()
    dialog = SettingsDialog(AppState(TaskManager(window)))
    dialog.index_url.setText("not a url")
    dialog.accept()
    assert app.shown_messages[-1][0] == "warning" and dialog.result() != dialog.DialogCode.Accepted
    dialog.index_url.setText("https://mirror.example/simple")
    dialog.extra_indexes.setText("https://a.example/simple, https://b.example/simple")
    dialog.trusted_hosts.setText("a.example")
    dialog.accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    dialog.save()
    assert config.get("extra_index_urls") == "https://a.example/simple https://b.example/simple"
    assert indexes.env()["PIP_INDEX_URL"] == "https://mirror.example/simple"


def test_pythons_page_offers_patch_update(app, monkeypatch):
    from python_manager.core import python_versions
    from python_manager.core.interpreters import MANAGED, Interpreter
    from python_manager.core.python_versions import RemotePython
    from python_manager.ui.pythons_page import PythonsPage
    from python_manager.ui.state import AppState
    from python_manager.ui.tasks import TaskManager

    old = Interpreter(python_versions.paths.pythons_dir() / "bin" / "python3", "3.12.4", MANAGED, "cpython-3.12.4")
    new = RemotePython("3.12.11", "20250101", False, "x.tar.gz", "https://example/x")
    window = QtWidgets.QWidget()
    tasks = TaskManager(window)
    state = AppState(tasks)
    monkeypatch.setattr(state, "interpreters", lambda include_envs=True: [old])
    installs = []
    monkeypatch.setattr(python_versions, "install", lambda remote, ctx: installs.append(remote))
    page = PythonsPage(state, tasks)
    page._set_available([new])
    assert page.installed.item(0, 3).text() == "3.12.11"
    page.installed.selectRow(0)
    assert page.update_btn.isEnabled()
    page.install_update()
    wait_until(app, lambda: installs and app.shown_messages)
    assert installs == [new] and app.shown_messages[-1][0] == "information"
