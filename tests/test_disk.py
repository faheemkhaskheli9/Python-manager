import sys
from pathlib import Path

import pytest

from python_manager.core import disk, paths, venvs


def test_dir_size_and_format(tmp_path):
    tmp_path = tmp_path / "data"
    tmp_path.mkdir()
    (tmp_path / "a").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"x" * 50)
    assert disk.dir_size(tmp_path) == 150
    assert disk.dir_size(tmp_path / "missing") == 0
    assert disk.format_size(512) == "512 B"
    assert disk.format_size(1536) == "1.5 KB"
    assert disk.format_size(3 * 1024 ** 3) == "3.0 GB"


def test_scan_lists_envs_and_caches(monkeypatch, tmp_path):
    monkeypatch.setenv("PIP_CACHE_DIR", str(tmp_path / "pip"))
    monkeypatch.setattr(disk, "uv_cache_dir", lambda: None)
    env = venvs.create("demo", Path(sys.executable), with_pip=False)
    items = disk.scan()
    kinds = {u.kind: u for u in items}
    assert kinds[disk.ENV].payload == env and kinds[disk.ENV].size > 0
    assert kinds[disk.PIP_CACHE].path == tmp_path / "pip"
    assert disk.APP_CACHE in kinds and disk.UV_CACHE not in kinds
    assert [u.size for u in items] == sorted((u.size for u in items), reverse=True)


def test_clean_keeps_small_app_files(tmp_path):
    cache = paths.cache_dir()
    (cache / "cpython.tar.gz").write_bytes(b"x" * 10)
    (cache / "pypi-names.txt").write_text("requests")
    (cache / "old").mkdir()
    disk.clean(disk.Usage(disk.APP_CACHE, "downloads", cache, 10))
    assert sorted(p.name for p in cache.iterdir()) == ["pypi-names.txt"]

    pip = tmp_path / "pip"
    (pip / "http").mkdir(parents=True)
    (pip / "http" / "x").write_bytes(b"x")
    disk.clean(disk.Usage(disk.PIP_CACHE, "pip", pip, 1))
    assert pip.is_dir() and not any(pip.iterdir())

    with pytest.raises(ValueError):
        disk.clean(disk.Usage(disk.ENV, "demo", tmp_path, 1))
