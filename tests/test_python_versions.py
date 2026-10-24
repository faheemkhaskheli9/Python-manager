import hashlib
import io
import sys
import tarfile

import pytest

from python_manager.core import paths, python_versions
from python_manager.core.interpreters import MANAGED, version_key
from python_manager.core.python_versions import RemotePython

SUMS = """\
aaa  cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz
bbb  cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
ccc  cpython-3.12.7+20241016-x86_64-unknown-linux-gnu-pgo+lto-full.tar.zst
ddd  cpython-3.13.0+20241016-x86_64-unknown-linux-gnu-freethreaded-install_only.tar.gz
eee  cpython-3.14.0a1+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz
fff  cpython-3.12.7+20241016-x86_64_v3-unknown-linux-gnu-install_only.tar.gz
ggg  cpython-3.12.7+20241016-aarch64-apple-darwin-install_only.tar.gz
hhh  cpython-3.10.8+20221106-x86_64-pc-windows-msvc-shared-install_only.tar.gz
"""


def test_parse_sha256sums_filters_by_triple_and_variant():
    items = python_versions.parse_sha256sums(SUMS, "20241016", "x86_64-unknown-linux-gnu")
    assert [(i.version, i.freethreaded, i.sha256) for i in items] == [
        ("3.12.7", False, "aaa"),
        ("3.13.0", True, "ddd"),
        ("3.14.0a1", False, "eee"),
    ]
    assert items[0].url.endswith("/20241016/cpython-3.12.7%2B20241016-x86_64-unknown-linux-gnu-install_only.tar.gz")
    assert items[1].key == "cpython-3.13.0t"
    assert items[2].prerelease and not items[0].prerelease


def test_parse_sha256sums_windows_shared_suffix():
    items = python_versions.parse_sha256sums(SUMS, "20221106", "x86_64-pc-windows-msvc")
    assert [i.version for i in items] == ["3.10.8"]


@pytest.mark.parametrize(
    "plat, machine, expected",
    [
        ("win32", "AMD64", "x86_64-pc-windows-msvc"),
        ("win32", "ARM64", "aarch64-pc-windows-msvc"),
        ("darwin", "arm64", "aarch64-apple-darwin"),
        ("linux", "x86_64", "x86_64-unknown-linux-gnu"),
        ("linux", "aarch64", "aarch64-unknown-linux-gnu"),
    ],
)
def test_target_triple(monkeypatch, plat, machine, expected):
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(python_versions.platform, "machine", lambda: machine)
    monkeypatch.setattr(python_versions, "_is_musl", lambda: False)
    assert python_versions.target_triple() == expected


def test_list_available_keeps_newest_build(monkeypatch):
    triple = "x86_64-unknown-linux-gnu"
    sums = {
        "20241016": f"a  cpython-3.12.7+20241016-{triple}-install_only.tar.gz\n",
        "20241008": f"b  cpython-3.12.7+20241008-{triple}-install_only.tar.gz\n"
                    f"c  cpython-3.11.9+20241008-{triple}-install_only.tar.gz\n",
    }
    monkeypatch.setattr(python_versions, "target_triple", lambda: triple)
    monkeypatch.setattr(python_versions, "release_tags", lambda count: list(sums))
    monkeypatch.setattr(python_versions.net, "get_text", lambda url: sums[url.split("/")[-2]])
    items = python_versions.list_available(2)
    assert [(i.version, i.build) for i in items] == [("3.12.7", "20241016"), ("3.11.9", "20241008")]


def test_list_available_skips_failed_release(monkeypatch):
    triple = "x86_64-unknown-linux-gnu"
    good = f"a  cpython-3.12.7+20241016-{triple}-install_only.tar.gz\n"

    def get_text(url):
        if "20241008" in url:
            raise OSError("timed out")
        return good

    logs = []
    monkeypatch.setattr(python_versions, "target_triple", lambda: triple)
    monkeypatch.setattr(python_versions, "release_tags", lambda count: ["20241016", "20241008"])
    monkeypatch.setattr(python_versions.net, "get_text", get_text)
    ctx = python_versions.TaskContext(log=logs.append)
    assert [i.build for i in python_versions.list_available(2, ctx)] == ["20241016"]
    assert any("Skipping release 20241008" in line for line in logs)


def test_version_key_orders_prereleases():
    versions = ["3.12.0", "3.12.0rc1", "3.9.18", "3.12.0a7", "3.13.1"]
    assert sorted(versions, key=version_key) == ["3.9.18", "3.12.0a7", "3.12.0rc1", "3.12.0", "3.13.1"]


def _fake_archive(path):
    """An archive shaped like python-build-standalone's install_only builds."""
    exe = "python/python.exe" if sys.platform == "win32" else "python/bin/python3"
    with tarfile.open(path, "w:gz") as tar:
        data = b"#!/bin/sh\necho fake\n"
        info = tarfile.TarInfo(exe)
        info.size = len(data)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_install_list_uninstall(tmp_path):
    archive = tmp_path / "src" / "cpython-3.12.7+1-test-install_only.tar.gz"
    archive.parent.mkdir()
    digest = _fake_archive(archive)
    remote = RemotePython("3.12.7", "1", False, archive.name, archive.as_uri(), digest)

    interp = python_versions.install(remote)
    assert interp.kind == MANAGED and interp.executable.is_file()
    assert python_versions.archive_path(remote).exists()  # cached for reuse
    assert [i.version for i in python_versions.list_installed()] == ["3.12.7"]
    assert python_versions.installed_keys() == {"cpython-3.12.7"}

    with pytest.raises(FileExistsError):
        python_versions.install(remote)

    python_versions.uninstall(interp)
    assert python_versions.list_installed() == []
    assert not (paths.pythons_dir() / "cpython-3.12.7").exists()


def test_install_rejects_bad_checksum(tmp_path):
    archive = tmp_path / "cpython-3.11.0+1-test-install_only.tar.gz"
    _fake_archive(archive)
    remote = RemotePython("3.11.0", "1", False, archive.name, archive.as_uri(), "0" * 64)
    with pytest.raises(ValueError, match="Checksum"):
        python_versions.install(remote)
    assert python_versions.list_installed() == []
    assert not python_versions.archive_path(remote).exists()


def _remote(version, freethreaded=False):
    return RemotePython(version, "20250101", freethreaded, f"{version}.tar.gz", "https://example/x")


def test_updates_newest_patch_of_same_minor_and_variant():
    from python_manager.core.interpreters import SYSTEM, Interpreter

    installed = [
        Interpreter(paths.pythons_dir() / "a", "3.12.4", MANAGED, "cpython-3.12.4"),
        Interpreter(paths.pythons_dir() / "b", "3.13.1", MANAGED, "cpython-3.13.1t"),
        Interpreter(paths.pythons_dir() / "c", "3.14.0rc2", MANAGED, "cpython-3.14.0rc2"),
        Interpreter(paths.pythons_dir() / "d", "3.11.2", SYSTEM, "python3.11"),
        Interpreter(paths.pythons_dir() / "e", "3.10.16", MANAGED, "cpython-3.10.16"),
    ]
    available = [
        _remote("3.13.0"), _remote("3.12.9"), _remote("3.12.11"), _remote("3.12.12rc1"),
        _remote("3.13.3"), _remote("3.13.2", freethreaded=True), _remote("3.14.0"),
        _remote("3.11.9"), _remote("3.10.16"),
    ]
    found = {name: r.version for name, r in python_versions.updates(installed, available).items()}
    assert found == {"cpython-3.12.4": "3.12.11", "cpython-3.13.1t": "3.13.2", "cpython-3.14.0rc2": "3.14.0"}
