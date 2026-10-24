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
