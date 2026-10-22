import json
import os

from python_manager.core import config, paths


def test_defaults_and_set():
    assert config.get("use_uv") is False  # set by the conftest fixture
    assert config.get("release_count") == config.DEFAULTS["release_count"]
    config.set("release_count", 7)
    assert config.get("release_count") == 7


def test_external_edit_is_picked_up():
    config.set("release_count", 5)
    assert config.get("release_count") == 5
    target = paths.config_file()
    data = json.loads(target.read_text(encoding="utf-8"))
    data["release_count"] = 12
    target.write_text(json.dumps(data), encoding="utf-8")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))  # coarse clocks
    assert config.get("release_count") == 12


def test_corrupt_file_falls_back_to_defaults():
    paths.config_file().write_text("{not json", encoding="utf-8")
    assert config.get("release_count") == config.DEFAULTS["release_count"]
