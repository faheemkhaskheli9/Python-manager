import json
import os
import sys
from pathlib import Path

from python_manager import cli
from python_manager.core import pathcheck

EXE = ".exe" if sys.platform == "win32" else ""


def make_exe(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (name + EXE)
    path.write_text("")
    path.chmod(0o755)
    return path


def pythons(table):
    """A probe returning ``table[folder name]`` for interpreters in that folder."""
    return lambda exe: table.get(Path(exe).parent.name)


def pips(table):
    """``pip --version`` results keyed by folder name; ``-m pip`` uses the interpreter's folder too."""
    return lambda cmd: table.get(Path(cmd[0]).parent.name)


def run_check(dirs, probe, pip, tool_dirs=None, monkeypatch=None):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    return pathcheck.check(os.pathsep.join(str(d) for d in dirs), probe, pip, lambda commands: tool_dirs or {})


def py(folder, version):
    return {"version": version, "prefix": str(folder), "user_scripts": ""}


def pipv(folder, python):
    return {"version": "24.0", "python": python, "location": str(folder / "site-packages" / "pip")}


def test_consistent_path(tmp_path, monkeypatch):
    a = tmp_path / "a"
    for name in ("python", "python3", "pip", "pip3"):
        make_exe(a, name)
    report = run_check([a], pythons({"a": py(a, "3.12.4")}), pips({"a": pipv(a, "3.12")}), monkeypatch=monkeypatch)
    assert report.problems == []
    assert report.command("python").version == "3.12.4"
    assert report.command("pip").detail.startswith("Python 3.12")
    assert report.command("uv") is None
    assert "PATH looks fine" in report.summary


def test_pip_from_another_python_and_shadowed(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    make_exe(a, "pip")
    make_exe(b, "python")
    make_exe(b, "python3")
    make_exe(a, "python3")  # an earlier python3 shadows b's
    second = make_exe(tmp_path / "c", "python")
    probe = pythons({"a": py(a, "3.11.9"), "b": py(b, "3.13.1"), "c": py(second.parent, "3.10.0")})
    report = run_check([a, b, second.parent], probe, pips({"a": pipv(a, "3.11"), "b": pipv(b, "3.13")}),
                       monkeypatch=monkeypatch)
    messages = [p.message for p in report.warnings]
    assert any(m.startswith("pip installs into Python 3.11") and "python runs Python 3.13.1" in m for m in messages)
    assert any("python (3.13.1) and python3 (3.11.9) are different" in m for m in messages)
    assert report.command("python").shadowed == (second,)
    assert any(p.severity == pathcheck.NOTE and p.message.startswith("python runs") for p in report.problems)


def test_same_pip_location_is_not_a_mismatch(tmp_path, monkeypatch):
    """A Python reading another prefix's site-packages (Debian /usr/local) still matches its pip."""
    local, usr = tmp_path / "local", tmp_path / "usr"
    make_exe(local, "python")
    make_exe(local, "pip")
    shared = pipv(usr, "3.13")
    report = run_check([local], pythons({"local": py(local, "3.13.1")}), lambda cmd: shared, monkeypatch=monkeypatch)
    assert report.warnings == []


def test_missing_folders_and_duplicates(tmp_path, monkeypatch):
    a = tmp_path / "a"
    make_exe(a, "python")
    scripts = tmp_path / "user-scripts"
    make_exe(scripts, "black")
    tools = tmp_path / "tools"
    make_exe(tools, "ruff")
    empty = tmp_path / "empty"
    empty.mkdir()
    gone = tmp_path / "gone"
    probe = pythons({"a": {**py(a, "3.12.0"), "user_scripts": str(scripts)}})
    report = run_check([a, gone, a], probe, lambda cmd: None, {"uv tool": str(tools), "pipx": str(empty)},
                       monkeypatch=monkeypatch)
    warnings = [p.message for p in report.warnings]
    assert any(str(scripts) in m and "pip install --user" in m for m in warnings)
    assert any(str(tools) in m and "uv tool" in m for m in warnings)
    assert not any(str(empty) in m for m in warnings)  # nothing installed there yet
    notes = [p.message for p in report.problems if p.severity == pathcheck.NOTE]
    assert any("does not exist" in m and str(gone) in m for m in notes)
    assert any("already on PATH earlier" in m for m in notes)
    assert [(e.exists, e.duplicate) for e in report.entries] == [(True, False), (False, False), (True, True)]
    assert report.entries[0].pythons == ("python" + EXE,)


def test_no_python(tmp_path, monkeypatch):
    report = run_check([tmp_path], pythons({}), lambda cmd: None, monkeypatch=monkeypatch)
    assert report.warnings[0].message == "No python or python3 on PATH."


def test_store_alias():
    assert pathcheck.store_alias(Path("C:/Users/me/AppData/Local/Microsoft/WindowsApps/python.exe"))
    assert not pathcheck.store_alias(Path("/usr/bin/python3"))


def test_parse_pip_version():
    info = pathcheck.parse_pip_version("pip 24.2 from /usr/lib/python3/dist-packages/pip (python 3.12)\n")
    assert info == {"version": "24.2", "location": "/usr/lib/python3/dist-packages/pip", "python": "3.12"}
    assert pathcheck.parse_pip_version("") is None


def test_real_path_and_report_formats(monkeypatch):
    """The live check runs against this process's PATH with the test interpreter first."""
    monkeypatch.setenv("PATH", os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]))
    report = pathcheck.check()
    assert report.entries[0].exists
    assert "PATH:" in report.to_text()
    assert json.loads(json.dumps(report.to_json()))["path"][0]["exists"] is True


def test_cli_path(capsys, monkeypatch):
    report = pathcheck.Report(problems=[pathcheck.Problem(pathcheck.WARNING, "pip is from another Python", "fix")])
    monkeypatch.setattr(pathcheck, "check", lambda: report)
    assert cli.main(["path"]) == 1
    assert "[warning] pip is from another Python" in capsys.readouterr().out
    assert cli.main(["path", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["problems"][0]["severity"] == "warning"
    monkeypatch.setattr(pathcheck, "check", lambda: pathcheck.Report())
    assert cli.main(["path"]) == 0
