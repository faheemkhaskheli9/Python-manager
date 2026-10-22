import sys
from pathlib import Path

import pytest

from python_manager.core import paths, venvs
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
