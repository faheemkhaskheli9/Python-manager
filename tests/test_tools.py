import shutil
import sys
from pathlib import Path

import pytest

from python_manager.core import tools

UV_LIST = """\
httpie v3.2.4 (/home/me/.local/share/uv/tools/httpie)
- http (/home/me/.local/bin/http)
- https (/home/me/.local/bin/https)
warning: something unrelated
ruff v0.6.9
- ruff
"""

PIPX_LIST = {
    "pipx_spec_version": "0.1",
    "venvs": {
        "black": {"metadata": {
            "main_package": {
                "package": "black", "package_version": "24.8.0", "apps": ["black", "blackd"],
                "app_paths": [{"__Path__": "/home/me/.local/pipx/venvs/black/bin/black", "__type__": "Path"}],
            },
            "python_version": "Python 3.12.4",
        }},
        "black-old": {"metadata": {"main_package": {"package": "black", "package_version": "23.1.0", "apps": []}}},
    },
}


def test_parse_uv_list():
    httpie, ruff = tools.parse_uv_list(UV_LIST)
    assert (httpie.name, httpie.version, httpie.manager) == ("httpie", "3.2.4", tools.UV)
    assert httpie.commands == ("http", "https")
    assert httpie.path == Path("/home/me/.local/share/uv/tools/httpie")
    assert (ruff.name, ruff.version, ruff.commands, ruff.path) == ("ruff", "0.6.9", ("ruff",), None)
    assert tools.parse_uv_list("No tools installed\n") == []


def test_parse_pipx_list():
    black, old = tools.parse_pipx_list(PIPX_LIST)
    assert (black.name, black.version, black.python, black.key) == ("black", "24.8.0", "3.12.4", "black")
    assert black.commands == ("black", "blackd")
    assert black.path == Path("/home/me/.local/pipx/venvs/black")  # derived from the app path
    assert (old.name, old.key, old.path) == ("black", "black-old", None)  # suffixed install
    _, old = tools.parse_pipx_list(PIPX_LIST, Path("/venvs"))
    assert old.path == Path("/venvs/black-old")


def test_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "executable", lambda m: f"/bin/{m}")
    monkeypatch.setattr(tools, "run", lambda cmd, ctx: calls.append(cmd))
    tools.install(tools.UV, "ruff", Path("/py"))
    tools.install(tools.PIPX, "black")
    tool = tools.Tool("black", "1", tools.PIPX, (), None, env="black-old")
    tools.upgrade(tool)
    tools.uninstall(tool)
    tools.upgrade_all(tools.UV)
    tools.upgrade_all(tools.PIPX)
    assert calls == [
        ["/bin/uv", "tool", "install", "ruff", "--python", str(Path("/py"))],
        ["/bin/pipx", "install", "black"],
        ["/bin/pipx", "upgrade", "black-old"],
        ["/bin/pipx", "uninstall", "black-old"],
        ["/bin/uv", "tool", "upgrade", "--all"],
        ["/bin/pipx", "upgrade-all"],
    ]


def test_missing_manager(monkeypatch):
    monkeypatch.setattr(tools, "executable", lambda m: None)
    assert tools.managers() == [] and tools.list_tools() == []
    with pytest.raises(FileNotFoundError):
        tools.install(tools.UV, "ruff")


@pytest.mark.skipif(not shutil.which("uv"), reason="uv is not installed")
def test_uv_tool_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "tools"))
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "bin"))
    monkeypatch.setattr(tools, "executable", lambda m: shutil.which(m) if m == tools.UV else None)
    wheel_dir = tmp_path / "pkg"
    (wheel_dir / "demo_tool").mkdir(parents=True)
    (wheel_dir / "demo_tool" / "__init__.py").write_text("def main():\n    print('hi')\n")
    (wheel_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo-tool"\nversion = "1.0"\n[project.scripts]\ndemo-tool = "demo_tool:main"\n'
        '[build-system]\nrequires = ["setuptools>=64"]\nbuild-backend = "setuptools.build_meta"\n')
    try:
        tools.install(tools.UV, str(wheel_dir), Path(sys.executable))
    except tools.CommandError as exc:  # offline: build dependencies cannot be fetched
        pytest.skip(str(exc).splitlines()[0])
    (tool,) = tools.list_tools()
    assert (tool.name, tool.version, tool.commands) == ("demo-tool", "1.0", ("demo-tool",))
    assert tool.path.is_dir() and tool.python.startswith("%d.%d" % sys.version_info[:2])
    tools.uninstall(tool)
    assert tools.list_tools() == []
