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
    table = window.packages.table
    wait_until(app, lambda: window.packages._sizes)
    assert any(table.item(r, 5).text().endswith("B") for r in range(table.rowCount()))
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


def test_python_update_rebuilds_dependents(app, monkeypatch):
    from python_manager.core import python_versions, venvs
    from python_manager.core.interpreters import MANAGED, Interpreter
    from python_manager.core.python_versions import RemotePython
    from python_manager.ui.pythons_page import PythonsPage
    from python_manager.ui.state import AppState
    from python_manager.ui.tasks import TaskManager

    old = Interpreter(python_versions.paths.pythons_dir() / "bin" / "python3", "3.12.4", MANAGED, "cpython-3.12.4")
    installed = Interpreter(python_versions.paths.pythons_dir() / "new" / "python3", "3.12.11", MANAGED, "new")
    new = RemotePython("3.12.11", "20250101", False, "x.tar.gz", "https://example/x")
    envs = [venvs.VirtualEnv(n, python_versions.paths.envs_dir() / n, "3.12.4", "", True) for n in ("a", "b")]
    window = QtWidgets.QWidget()
    tasks = TaskManager(window)
    state = AppState(tasks)
    monkeypatch.setattr(state, "interpreters", lambda include_envs=True: [old])
    monkeypatch.setattr(python_versions, "install", lambda remote, ctx: installed)
    rebuilt = []

    def rebuild(env, base, ctx):
        if env.name == "b":
            raise OSError("in use")
        rebuilt.append((env.name, base))

    monkeypatch.setattr(venvs, "rebuild", rebuild)
    page = PythonsPage(state, tasks)
    monkeypatch.setattr(page, "_dependents", lambda interp: envs)
    page._set_available([new])
    page.installed.selectRow(0)
    page.install_update()
    wait_until(app, lambda: app.shown_messages and "Rebuild" in app.shown_messages[-1][1][0])
    assert rebuilt == [("a", installed.executable)]
    kind, (title, text) = app.shown_messages[-1]
    assert kind == "warning" and "b" in text.split("\n")[-1]


def test_compare_and_find_dialogs(app, monkeypatch):
    from pathlib import Path

    from python_manager.core import packages
    from python_manager.core.interpreters import VENV, Interpreter
    from python_manager.core.packages import Package
    from python_manager.ui.compare_dialog import CompareDialog
    from python_manager.ui.find_dialog import FindPackageDialog
    from python_manager.ui.tasks import TaskManager

    a = Interpreter(Path("/envs/a/bin/python"), "3.12.1", VENV, "a")
    b = Interpreter(Path("/envs/b/bin/python"), "3.12.1", VENV, "b")
    contents = {a.executable: [Package("requests", "2.32.0"), Package("idna", "3.7")],
                b.executable: [Package("requests", "2.31.0"), Package("idna", "3.7")]}
    monkeypatch.setattr(packages, "installed", lambda python: contents[python])
    installs = []
    monkeypatch.setattr(packages, "install", lambda python, specs, ctx: installs.append((python, specs)))
    window = QtWidgets.QWidget()
    tasks = TaskManager(window)

    dialog = CompareDialog([a, b], tasks, left=a)
    wait_until(app, lambda: dialog.rows)
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 3).text() == "Different"
    dialog.hide_same.setChecked(False)
    assert dialog.table.rowCount() == 2
    dialog.match_left()
    wait_until(app, lambda: dialog.changed)
    assert installs == [(b.executable, ["requests==2.32.0"])]

    managed = []
    finder = FindPackageDialog([a, b], tasks, managed.append)
    finder.pattern.setText("req*")
    finder.search()
    wait_until(app, lambda: finder.table.rowCount() == 2)
    finder.table.selectRow(0)
    finder._manage()
    assert managed and managed[0] in contents
