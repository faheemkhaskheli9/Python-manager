import sys
import urllib.error
from pathlib import Path

import pytest

from python_manager.core import deps, lock

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

GRAPH = {
    "requests": deps.Dist("requests", "2.32.3", ("idna",)),
    "idna": deps.Dist("idna", "3.10", ()),
    "local-pkg": deps.Dist("local_pkg", "0.1", ()),
    "pip": deps.Dist("pip", "24.2", ()),
}


def _release(name, version):
    if name == "local_pkg":
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
    files = [{"filename": f"{name}-{version}-py3-none-any.whl", "url": f"https://files/{name}.whl",
              "digests": {"sha256": "a" * 64}, "size": 100, "upload_time_iso_8601": "2024-05-29T15:37:47.027320Z",
              "packagetype": "bdist_wheel"},
             {"filename": f"{name}-{version}.tar.gz", "url": f"https://files/{name}.tar.gz",
              "digests": {"sha256": "b" * 64}, "size": 200, "upload_time_iso_8601": "2024-05-29T15:37:49.536005Z",
              "packagetype": "sdist"}]
    return {"urls": files}


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setattr(deps, "load_graph", lambda python: GRAPH)
    monkeypatch.setattr(lock.net, "get_json", lambda url: _release(*url.split("/")[-3:-1]))


def test_hashed_requirements(fake_env, tmp_path):
    result = lock.export(Path(sys.executable), lock.HASHES, tmp_path / "req.txt", "demo", "3.12.4")
    text = result.path.read_text()
    assert result.packages == 2 and result.skipped == ["local_pkg==0.1"]
    assert f"requests==2.32.3 \\\n    --hash=sha256:{'a' * 64} \\\n    --hash=sha256:{'b' * 64}\n" in text
    assert "pip==" not in text
    assert "# not on PyPI, add it by hand: local_pkg==0.1" in text


@pytest.mark.skipif(tomllib is None, reason="needs tomllib")
def test_pylock(fake_env, tmp_path):
    result = lock.export(Path(sys.executable), lock.PYLOCK, tmp_path / "pylock.toml", "demo", "3.12.4",
                         exclude_tools=False)
    data = tomllib.loads(result.path.read_text())
    assert data["lock-version"] == "1.0"
    assert data["requires-python"] == "==3.12.*"
    assert [p["name"] for p in data["packages"]] == ["idna", "pip", "requests"]
    requests = data["packages"][2]
    assert requests["version"] == "2.32.3"
    assert requests["sdist"]["hashes"]["sha256"] == "b" * 64
    assert requests["wheels"][0]["url"] == "https://files/requests.whl"
    assert requests["wheels"][0]["upload-time"].year == 2024


def test_top_level(fake_env, tmp_path):
    result = lock.export(Path(sys.executable), lock.TOP_LEVEL, tmp_path / "req.txt", "demo", "3.12.4")
    lines = [l for l in result.path.read_text().splitlines() if not l.startswith("#")]
    assert lines == ["local_pkg==0.1", "requests==2.32.3"]


def test_release_files_not_found(fake_env):
    with pytest.raises(LookupError):
        lock.release_files("local_pkg", "0.1")
