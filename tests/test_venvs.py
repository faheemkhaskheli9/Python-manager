import sys
from pathlib import Path

import pytest

from python_manager.core import packages, paths, venvs
from python_manager.core.tasks import CommandError


def test_create_list_delete_managed(backend):
    env = venvs.create("demo", Path(sys.executable), with_pip=False)
    assert env.managed and env.valid
    assert env.path.parent == paths.envs_dir()
    assert [e.name for e in venvs.list_envs()] == ["demo"]
    assert env.version.startswith(f"{sys.version_info.major}.{sys.version_info.minor}")

    with pytest.raises(FileExistsError):
        venvs.create("demo", Path(sys.executable), with_pip=False)

    venvs.delete(env)
    assert venvs.list_envs() == []


def test_external_env_is_registered(tmp_path):
    env = venvs.create("outside", Path(sys.executable), tmp_path / "projects", with_pip=False)
    assert not env.managed
    assert [e.path for e in venvs.list_envs()] == [env.path]

    venvs.unregister(env.path)
    assert venvs.list_envs() == []
    assert env.path.exists()  # unregistering keeps the files

    venvs.register(env.path)
    assert len(venvs.list_envs()) == 1


def test_invalid_name_and_register():
    with pytest.raises(ValueError):
        venvs.create("bad name", Path(sys.executable))
    with pytest.raises(ValueError):
        venvs.register(paths.data_dir())


def test_failed_create_cleans_up(backend, tmp_path):
    missing = tmp_path / "no-python"
    with pytest.raises((OSError, CommandError)):
        venvs.create("broken", missing)
    assert not (paths.envs_dir() / "broken").exists()


def test_create_with_pip(backend, tmp_path):
    env = venvs.create("seeded", Path(sys.executable), tmp_path, with_pip=True)
    assert (env.executable.parent / ("pip.exe" if sys.platform == "win32" else "pip")).exists()


def test_base_executable_and_plain_clone(backend, tmp_path):
    env = venvs.create("src", Path(sys.executable), tmp_path, with_pip=False)
    base = venvs.base_executable(env)
    assert base is not None and base.is_file()

    copy = venvs.clone(env, "copy", location=tmp_path, with_pip=False)
    assert copy.valid and copy.version == env.version


def test_create_from_file_and_clone(backend, tmp_path, monkeypatch):
    from test_packages import _build_wheel

    wheel = _build_wheel(tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(f"--no-index\n{wheel}\n", encoding="utf-8")
    env = venvs.create("from-file", Path(sys.executable), tmp_path, with_pip=False, packages_file=req)
    assert "pm-demo" in {p.name.lower() for p in packages.list_packages(env.executable)}

    out = tmp_path / "exported.txt"
    venvs.export(env, out)
    assert "pm-demo" in out.read_text(encoding="utf-8")

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path))
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_FIND_LINKS", str(tmp_path))
    copy = venvs.clone(env, "copy", location=tmp_path, with_pip=False)
    assert "pm-demo" in {p.name.lower() for p in packages.list_packages(copy.executable)}


def test_failed_package_install_removes_env(backend, tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("--no-index\nthis-package-does-not-exist-pm\n", encoding="utf-8")
    with pytest.raises(CommandError):
        venvs.create("bad-reqs", Path(sys.executable), tmp_path, packages_file=req)
    assert not (tmp_path / "bad-reqs").exists()


def test_rebuild_keeps_path_and_packages(backend, tmp_path, monkeypatch):
    from test_packages import _build_wheel

    wheel = _build_wheel(tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(f"--no-index\n{wheel}\n", encoding="utf-8")
    env = venvs.create("rebuilt", Path(sys.executable), with_pip=False, packages_file=req)
    marker = env.path / "old-marker"
    marker.write_text("", encoding="utf-8")

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path))
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_FIND_LINKS", str(tmp_path))
    new = venvs.rebuild(env, Path(sys.executable))
    assert new.path == env.path and new.valid and not marker.exists()
    assert "pm-demo" in {p.name.lower() for p in packages.list_packages(new.executable)}
    assert [e.name for e in venvs.list_envs()] == ["rebuilt"]  # no backup left behind
    assert [p.name for p in paths.envs_dir().iterdir()] == ["rebuilt"]


def test_failed_rebuild_restores_env(backend, tmp_path):
    env = venvs.create("keep", Path(sys.executable), tmp_path / "envs", with_pip=False)
    marker = env.path / "old-marker"
    marker.write_text("", encoding="utf-8")
    with pytest.raises((OSError, CommandError)):
        venvs.rebuild(env, tmp_path / "no-python")
    assert marker.exists() and env.valid
    assert [p.name for p in (tmp_path / "envs").iterdir()] == ["keep"]


def test_requirements_of_broken_env(tmp_path, monkeypatch):
    env = venvs.create("orphan", Path(sys.executable), tmp_path, with_pip=False)
    site = venvs.site_packages(env)[0]
    dist = site / "pm_orphan-1.2.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: pm-orphan\nVersion: 1.2\n", encoding="utf-8")
    monkeypatch.setattr(venvs, "is_broken", lambda _env: True)
    assert venvs.requirements_of(env) == "pm-orphan==1.2\n"


def test_requirements_of_broken_env_keeps_direct_sources(tmp_path, monkeypatch):
    import json

    env = venvs.create("direct", Path(sys.executable), tmp_path, with_pip=False)
    site = venvs.site_packages(env)[0]
    sources = {
        "pm-edit": {"url": "file:///src/pm-edit", "dir_info": {"editable": True}},
        "pm-git": {"url": "https://example.com/pm-git.git", "vcs_info": {"vcs": "git", "commit_id": "abc123"}},
        "pm-zip": {"url": "file:///wheels/pm_zip-1.0.zip", "archive_info": {}},
        "pm-index": None,
    }
    for name, info in sources.items():
        dist = site / f"{name.replace('-', '_')}-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8")
        if info:
            (dist / "direct_url.json").write_text(json.dumps(info), encoding="utf-8")
    monkeypatch.setattr(venvs, "is_broken", lambda _env: True)
    assert venvs.requirements_of(env).splitlines() == [
        "-e file:///src/pm-edit",
        "pm-git @ git+https://example.com/pm-git.git@abc123",
        "pm-index==1.0",
        "pm-zip @ file:///wheels/pm_zip-1.0.zip",
    ]


def test_list_envs_skips_only_rebuild_backups():
    for name in (".hidden", "with space", ".demo.rebuild-123"):
        (paths.envs_dir() / name).mkdir()
        (paths.envs_dir() / name / "pyvenv.cfg").write_text("version = 3.12.0\n", encoding="utf-8")
    assert [e.name for e in venvs.list_envs()] == [".hidden", "with space"]


def test_created_from_matches_folder_boundary(tmp_path):
    def env(base):
        return venvs.VirtualEnv("e", tmp_path / "e", "3.13.1", str(base), True)

    root = tmp_path / "cpython-3.13.1"
    assert venvs.created_from(env(root / "bin" / "python3"), root)
    assert not venvs.created_from(env(tmp_path / "cpython-3.13.1t" / "bin" / "python3"), root)
    assert not venvs.created_from(env(""), root)


def test_rebuild_retargets_versioned_kernel(backend, tmp_path, monkeypatch):
    import json

    from python_manager.core import kernels

    env = venvs.create("kern", Path(sys.executable), with_pip=False)
    versioned = env.executable.with_name("python9.99")
    versioned.write_text("", encoding="utf-8")
    spec = tmp_path / "kernels" / "kern"
    spec.mkdir(parents=True)
    (spec / "kernel.json").write_text(json.dumps({"argv": [str(versioned), "-m", "ipykernel_launcher"],
                                                  "display_name": "kern"}), encoding="utf-8")
    monkeypatch.setattr(kernels, "data_dirs", lambda: [tmp_path])
    new = venvs.rebuild(env, Path(sys.executable))
    argv = json.loads((spec / "kernel.json").read_text(encoding="utf-8"))["argv"]
    assert argv == [str(new.executable), "-m", "ipykernel_launcher"]
