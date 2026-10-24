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
    assert [s.path for s in project.sources()] == [folder / "requirements.txt"]
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


def test_held_back():
    from python_manager.core.packages import Upgrade

    upgrades = [Upgrade("Django", "4.2", "5.1"), Upgrade("requests", "2.30", "2.32"), Upgrade("rich", "13", "14")]
    held = projects.held_back(upgrades, ["django>=4,<5", "requests>=2", "rich", "not a valid req!"])
    assert held == {"Django": "django<5,>=4"}


def test_sources_with_extras_and_groups(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    (tmp_path / "requirements.txt").write_text("requests\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["rich"]\n'
        '[project.optional-dependencies]\ndocs = ["sphinx"]\n[dependency-groups]\ndev = ["ruff"]\n')
    sources = projects.Project(tmp_path).sources()
    assert [s.label for s in sources] == [
        "requirements.txt", "requirements-dev.txt", "pyproject.toml", "pyproject.toml [docs]",
        "pyproject.toml (group dev)", "pyproject.toml (all extras and groups)"]
    assert projects.read_requirements(sources[3]) == ["rich", "sphinx"]
    assert projects.read_requirements(sources[5]) == ["rich", "sphinx", "ruff"]


def test_sync_pyproject_source(tmp_path, monkeypatch):
    venvs.create_at(tmp_path / ".venv", Path(sys.executable), with_pip=False)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\ndependencies = ["rich"]\n[dependency-groups]\ndev = ["ruff"]\n')
    calls = []
    monkeypatch.setattr(packages, "install", lambda python, specs, ctx: calls.append(list(specs)))
    project = projects.Project(tmp_path)
    projects.sync(project, projects.Source(tmp_path / "pyproject.toml", groups=("dev",)))
    assert calls == [["rich", "ruff"]]


def test_compare_unlisted(tmp_path, monkeypatch):
    from python_manager.core import deps

    graph = {"requests": deps.Dist("requests", "2.0", ("idna",)), "idna": deps.Dist("idna", "3", ()),
             "black": deps.Dist("black", "24", ()), "pip": deps.Dist("pip", "24", ())}
    monkeypatch.setattr(deps, "load_graph", lambda python: graph)
    monkeypatch.setattr(projects, "marker_environment", lambda python: {})
    checks = projects.compare(["requests"], Path(sys.executable), unlisted=True)
    assert [(c.name, c.status) for c in checks] == [("requests", projects.OK), ("black", projects.UNLISTED)]
    assert len(projects.compare(["requests"], Path(sys.executable))) == 1


def test_python_pin_and_requires_python(tmp_path):
    project = projects.Project(tmp_path)
    assert projects.python_pin(project) == "" and projects.requires_python(project) == ""
    assert projects.python_problems(project, "3.8.1") == []
    projects.set_python_pin(project, "3.12 ")
    assert (tmp_path / ".python-version").read_text() == "3.12\n"
    (tmp_path / ".python-version").write_text("# comment\n\n3.11  # pinned\n3.12\n")
    assert projects.python_pin(project) == "3.11"
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = ">=3.10"\n')
    assert projects.requires_python(project) == ">=3.10"
    assert projects.python_problems(project, "3.11.4") == []
    assert projects.python_problems(project, "3.9.0.final.0") == [".python-version asks for 3.11",
                                                                  "requires-python is >=3.10"]
    assert tmp_path / ".python-version" in project.watched_paths()
    projects.set_python_pin(project, "")
    assert not (tmp_path / ".python-version").exists()
    projects.set_python_pin(project, "")  # already gone


@pytest.mark.parametrize("pin, version, expected", [
    ("3.12", "3.12.4", True), ("3.12", "3.13.0", False), ("3.12.4", "3.12.3", False),
    ("cpython-3.12", "3.12.0", True), ("cpython@3.13", "3.12.9", False), ("3.13t", "3.13.1", True),
    ("system", "3.8.0", True), ("3", "3.14.0", True), ("3.1", "3.12.0", False),
])
def test_pin_matches(pin, version, expected):
    assert projects.pin_matches(pin, version) is expected


def test_satisfies():
    assert projects.satisfies(">=3.10,<4", "3.12.1")
    assert not projects.satisfies(">=3.10", "3.9.18")
    assert projects.satisfies("", "3.9")
    assert projects.satisfies("not a specifier", "3.9")
    assert projects.satisfies(">=3.13", "3.13.0rc1.candidate.1")


def test_preferred_python(tmp_path):
    project = projects.Project(tmp_path)
    versions = ["3.11.9", "3.13.1", "3.12.7", "3.10.4"]
    assert projects.preferred_python(project, versions, 3) == 3  # nothing asked for: the default
    (tmp_path / ".python-version").write_text("3.12\n")
    assert projects.preferred_python(project, versions, 0) == 2
    (tmp_path / ".python-version").unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
    assert projects.preferred_python(project, versions, 0) == 1  # the newest that fits
    assert projects.preferred_python(project, versions, 2) == 2  # the default fits
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = ">=3.20"\n')
    assert projects.preferred_python(project, versions, 3) == 3  # none fits


def _remote(version, freethreaded=False):
    from python_manager.core.python_versions import RemotePython

    return RemotePython(version, "1", freethreaded, f"cpython-{version}.tar.gz", "https://example.org/x")


def test_matching_download(tmp_path):
    project = projects.Project(tmp_path)
    available = [_remote("3.14.0rc1"), _remote("3.13.2"), _remote("3.13.2", True), _remote("3.12.9")]
    assert projects.matching_download(project, available).version == "3.13.2"  # newest final release
    (tmp_path / ".python-version").write_text("3.12\n")
    assert projects.matching_download(project, available).version == "3.12.9"
    (tmp_path / ".python-version").write_text("3.13t\n")
    assert projects.matching_download(project, available).freethreaded
    (tmp_path / ".python-version").write_text("3.14\n")
    assert projects.matching_download(project, available).version == "3.14.0rc1"  # only a pre-release fits
    (tmp_path / ".python-version").unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = "<3.12"\n')
    assert projects.matching_download(project, available) is None


def test_install_python_and_env(tmp_path, monkeypatch):
    from python_manager.core import python_versions
    from python_manager.core.interpreters import MANAGED, Interpreter

    project = projects.Project(tmp_path)
    remote = _remote("3.13.2")
    calls = []
    monkeypatch.setattr(python_versions, "installed_keys", lambda: set())
    monkeypatch.setattr(python_versions, "install", lambda r, ctx: calls.append(r) or
                        Interpreter(Path(sys.executable), r.version, MANAGED, r.key))
    monkeypatch.setattr(projects, "create_env", lambda p, exe, ctx, install: (p, exe, install))
    assert projects.install_python_and_env(project, remote) == (project, Path(sys.executable), True)
    assert calls == [remote]
    monkeypatch.setattr(python_versions, "installed_keys", lambda: {remote.key})  # already installed: reused
    monkeypatch.setattr(python_versions, "find_executable", lambda root: Path(sys.executable))
    projects.install_python_and_env(project, remote)
    assert calls == [remote]
