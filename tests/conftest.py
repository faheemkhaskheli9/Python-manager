import pytest


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    """Point the app data folder at a temporary directory for every test."""
    home = tmp_path / "home"
    monkeypatch.setenv("PYTHON_MANAGER_HOME", str(home))
    return home
