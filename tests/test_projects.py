import sys
from pathlib import Path

import pytest

from python_manager.core import packages, projects, venvs


def test_add_remove_and_detect(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    (folder / "requirements.txt").write_text("requests\n")
    (folder / "uv.lock").write_text("")
    project = projects.add(folder)
    projects.add(folder)  # no duplicates
    assert projects.list_projects() == [project]
    assert project.files == ["requirements.txt", "uv.lock"]
    assert project.sources() == [folder / "requirements.txt"]
    assert project.env() is None
    projects.remove(folder)
    assert projects.list_projects() == []
    with pytest.raises(ValueError):
        projects.add(tmp_path / "missing")


def test_read_requirements(tmp_path):
    (tmp_path / "base.txt").write_text("attrs>=20\n")
    (tmp_path / "requirements.txt").write_text(
        "# comment\n-r base.txt\n--index-url https://example.org\n"
        "requests==2.0 --hash=sha256:abc  # pinned\nclick \\\n  >=8\n-e .\n")
    assert projects.read_requirements(tmp_path / "requirements.txt") == ["attrs>=20", "requests==2.0", "click   >=8"]
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["rich>=13"]\n')
    assert projects.read_requirements(tmp_path / "pyproject.toml") == ["rich>=13"]


def test_compare_with_environment(tmp_path):
    env = venvs.create_at(tmp_path / "app" / ".venv", Path(sys.executable), with_pip=True)
    assert env.name == "app/.venv"
    pip = next(p for p in packages.list_packages(env.executable) if p.name == "pip")
    checks = projects.compare([
        "pip", "pip<1", "not-installed-xyz", "pip; python_version < '2'", "::bad::",
    ], env.executable)
    assert [(c.name, c.status) for c in checks] == [
        ("pip", projects.OK), ("pip", projects.MISMATCH),
        ("not-installed-xyz", projects.MISSING), ("::bad::", projects.UNCHECKED),
    ]
    assert checks[0].installed == pip.version


def test_create_env_and_sync(tmp_path, backend):
    folder = tmp_path / "app"
    pkg = folder / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "pyproject.toml").write_text(
        '[project]\nname = "pm-demo"\nversion = "1.0"\n[build-system]\nrequires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n')
    (pkg / "pm_demo.py").write_text("")
    (folder / "requirements.txt").write_text(f"{pkg}\n")
    project = projects.add(folder)
    with pytest.raises(FileNotFoundError):
        projects.sync(project)
    env = projects.create_env(project, Path(sys.executable))
    assert project.env() == env
    assert "pm-demo" in {p.name.lower() for p in packages.list_packages(env.executable)}
