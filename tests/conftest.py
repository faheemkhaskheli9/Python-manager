import shutil

import pytest

from python_manager.core import config


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    """Point the app data folder at a temporary directory and default to pip for every test."""
    home = tmp_path / "home"
    monkeypatch.setenv("PYTHON_MANAGER_HOME", str(home))
    config.set("use_uv", False)
    return home


@pytest.fixture(params=["pip", "uv"])
def backend(request, app_home):
    """Run a test once with pip and once with uv (skipped when uv is not installed)."""
    if request.param == "uv" and not shutil.which("uv"):
        pytest.skip("uv is not installed")
    config.set("use_uv", request.param == "uv")
    return request.param
