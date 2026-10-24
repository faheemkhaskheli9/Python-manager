import json
import sys
from pathlib import Path

import pytest

from python_manager import cli
from python_manager.core import health, venvs


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_envs_and_pythons(capsys, tmp_path):
    env = venvs.create_at(tmp_path / "proj" / ".venv", Path(sys.executable))
    venvs.register(env.path)
    code, out, _ = run(capsys, "envs", "--json")
    assert code == 0
    assert [d["name"] for d in json.loads(out)] == ["proj/.venv"]
    code, out, _ = run(capsys, "envs")
    assert "proj/.venv" in out and str(env.path) in out
    code, out, _ = run(capsys, "pythons", "--managed", "--json")
    assert code == 0 and json.loads(out) == []


def test_check_exit_codes(capsys, monkeypatch):
    def check_all(executables, ctx, scan_security):
        assert scan_security is False
        return {str(p): health.Report(str(p), 0, {"pip": "99"} if "outdated" in str(p) else {})
                for p in executables}

    monkeypatch.setattr(health, "check_all", check_all)
    code, out, _ = run(capsys, "check", "--no-security", sys.executable)
    assert code == 0 and "up to date" in out
    monkeypatch.setattr(cli, "_resolve", lambda t: Path(t))
    code, out, _ = run(capsys, "check", "--no-security", "/x/outdated/python")
    assert code == 1 and "pip" in out and "99" in out
    monkeypatch.setattr(health, "check_all",
                        lambda e, c, scan_security: {str(p): health.Report(str(p), 0, error="boom") for p in e})
    code, out, _ = run(capsys, "check", "--no-security", "--json", "/x/python")
    assert code == 2 and json.loads(out)[0]["error"] == "boom"


def test_check_unknown_target(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "no-such-env"])
    assert exc.value.code == 2
    assert "no-such-env" in capsys.readouterr().err


def test_imports(capsys, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "requirements.txt").write_text("pytest\n")
    (project / "main.py").write_text("import json\nimport pytest\n")
    code, out, _ = run(capsys, "imports", str(project), "--python", sys.executable)
    assert code == 0 and "Imports match requirements.txt" in out
    (project / "main.py").write_text("import pytest\nimport notinstalled\n")
    code, out, _ = run(capsys, "imports", str(project), "--python", sys.executable, "--json")
    assert code == 1
    assert json.loads(out) == [{"name": "notinstalled", "status": "Not installed", "detail": "main.py"}]
    with pytest.raises(SystemExit) as exc:
        cli.main(["imports", str(project)])  # no environment in the project
    assert exc.value.code == 2


def test_envs_report_support(capsys, tmp_path):
    env = venvs.create_at(tmp_path / "proj" / ".venv", Path(sys.executable))
    venvs.register(env.path)
    code, out, _ = run(capsys, "envs", "--json")
    entry = json.loads(out)[0]
    assert entry["support"] in ("Supported", "Ends soon", "End of life")
    assert "end_of_support" in entry


def test_licenses(capsys, monkeypatch):
    from python_manager.core import licenses

    items = [licenses.PackageLicense("a", "1", "MIT", "License-Expression", ()),
             licenses.PackageLicense("b", "2", "GPL-3.0-only", "License-Expression", ())]
    monkeypatch.setattr(licenses, "scan", lambda python: items)
    code, out, err = run(capsys, "licenses", sys.executable)
    assert code == 0 and "GPL-3.0-only" in out and "Copyleft" in out
    code, out, err = run(capsys, "licenses", sys.executable, "--fail-on", "copyleft", "--format", "csv")
    assert code == 1 and out.startswith("Package,Version") and "b 2" in err
    code, out, _ = run(capsys, "licenses", sys.executable, "--json", "--fail-on", "weak-copyleft")
    assert code == 0 and [d["name"] for d in json.loads(out)] == ["a", "b"]
    with pytest.raises(SystemExit) as exc:
        cli.main(["licenses", sys.executable, "--fail-on", "nope"])
    assert exc.value.code == 2


def test_export(capsys, tmp_path, monkeypatch):
    env = venvs.create_at(tmp_path / "proj" / ".venv", Path(sys.executable))
    monkeypatch.chdir(tmp_path / "proj")
    code, out, _ = run(capsys, "export", "--json", "--include-tools")
    assert code == 0
    result = json.loads(out)
    assert Path(result["path"]).name == "requirements.txt" and result["skipped"] == []
    text = (tmp_path / "proj" / "requirements.txt").read_text()
    assert text.startswith("# proj/.venv · Python ")
    target = tmp_path / "pyproject.toml"
    code, out, _ = run(capsys, "export", str(env.path), "--format", "pyproject", "-o", str(target))
    assert code == 0 and "Saved" in out and "[project]" in target.read_text()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["export"])
    assert exc.value.code == 2
