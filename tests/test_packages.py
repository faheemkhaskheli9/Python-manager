import base64
import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from python_manager.core import deps, packages, venvs


def _build_wheel(folder: Path) -> Path:
    """A minimal pure-Python wheel so install/uninstall can be tested offline."""
    name, version = "pm_demo", "1.0"
    dist = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": b"VALUE = 1\n",
        f"{dist}/METADATA": f"Metadata-Version: 2.1\nName: pm-demo\nVersion: {version}\n".encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    for path, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{path},sha256={digest},{len(data)}")
    record.append(f"{dist}/RECORD,,")
    files[f"{dist}/RECORD"] = ("\n".join(record) + "\n").encode()
    wheel = folder / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    return wheel


def test_install_list_uninstall(backend, tmp_path):
    env = venvs.create("pkgs", Path(sys.executable), tmp_path, with_pip=True)
    python = env.executable
    assert packages.backend() == backend
    assert packages.has_pip(python)
    wheel = _build_wheel(tmp_path)

    packages.install(python, [str(wheel)], extra_args=["--no-index"])
    names = {p.name.lower(): p.version for p in packages.list_packages(python)}
    assert names.get("pm-demo") == "1.0"
    assert any(line.startswith("pm-demo") for line in packages.freeze(python).splitlines())

    graph = deps.load_graph(python)
    assert graph["pm-demo"].version == "1.0"
    assert "pip" in graph

    packages.uninstall(python, ["pm-demo"])
    assert "pm-demo" not in {p.name.lower() for p in packages.list_packages(python)}


def test_upgrade_all_nothing_outdated(monkeypatch):
    monkeypatch.setattr(packages, "outdated", lambda python: {})
    monkeypatch.setattr(packages, "install", lambda *a, **k: pytest.fail("nothing to upgrade"))
    assert packages.upgrade_all(Path(sys.executable)) == []


def test_upgrade_all(monkeypatch):
    calls = []
    monkeypatch.setattr(packages, "outdated", lambda python: {"b": "2", "A": "3"})
    monkeypatch.setattr(packages, "install", lambda python, names, ctx, upgrade: calls.append((names, upgrade)))
    assert packages.upgrade_all(Path(sys.executable)) == ["A", "b"]
    assert calls == [(["A", "b"], True)]


def test_pip_missing(tmp_path):
    bare = venvs.create("bare", Path(sys.executable), tmp_path, with_pip=False)
    assert not packages.has_pip(bare.executable)
    with pytest.raises(packages.PipMissing):
        packages.list_packages(bare.executable)


def test_project_info(monkeypatch):
    data = {
        "info": {"name": "Demo", "version": "2.0", "summary": "A demo", "requires_python": ">=3.8"},
        "releases": {
            "1.0": [{"upload_time_iso_8601": "2020-01-01T00:00:00Z"}],
            "2.0": [{"upload_time_iso_8601": "2022-01-01T00:00:00Z"}],
            "1.5": [{"upload_time_iso_8601": "2021-01-01T00:00:00Z", "yanked": True}],
            "0.1": [],
        },
    }
    monkeypatch.setattr(packages.net, "get_json", lambda url: data)
    info = packages.project_info("demo")
    assert info.latest == "2.0"
    assert info.versions == ["2.0", "1.0"]
    assert info.requires_python == ">=3.8"


def test_install_requires_specs():
    with pytest.raises(ValueError):
        packages.install(Path(sys.executable), [" "])
