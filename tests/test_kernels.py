import json
import sys
from pathlib import Path

import pytest

from python_manager.core import kernels, venvs


@pytest.fixture
def jupyter_home(tmp_path, monkeypatch):
    data = tmp_path / "jupyter"
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(data))
    monkeypatch.setenv("JUPYTER_PATH", "")
    system = tmp_path / "system"
    monkeypatch.setattr(kernels, "data_dirs", lambda: [data, system])
    return data


def write_spec(folder: Path, argv, display="Kernel", language="python"):
    folder.mkdir(parents=True)
    (folder / "kernel.json").write_text(json.dumps({"argv": argv, "display_name": display, "language": language}))


def test_user_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(tmp_path))
    assert kernels.user_data_dir() == tmp_path
    monkeypatch.delenv("JUPYTER_DATA_DIR")
    if sys.platform.startswith("linux"):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert kernels.user_data_dir() == tmp_path / "xdg" / "jupyter"


def test_list_and_match_kernels(jupyter_home, tmp_path):
    env = tmp_path / "env"
    python = env / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    write_spec(jupyter_home / "kernels" / "env", [str(python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
               "Python (env)")
    write_spec(jupyter_home / "kernels" / "gone", [str(tmp_path / "deleted" / "bin" / "python")], "Gone")
    write_spec(jupyter_home / "kernels" / "plain", ["python", "-m", "ipykernel_launcher"], "Plain")
    (jupyter_home / "kernels" / "invalid").mkdir()
    (jupyter_home / "kernels" / "invalid" / "kernel.json").write_text("{")
    write_spec(tmp_path / "system" / "kernels" / "Env", [str(env / "bin" / "python3")], "Duplicate")
    write_spec(tmp_path / "system" / "kernels" / "ir", ["R"], "R", "R")

    found = {k.name: k for k in kernels.list_kernels()}
    assert sorted(found) == ["env", "gone", "ir", "plain"]  # "Env" is hidden by "env", as in Jupyter
    assert found["env"].display_name == "Python (env)" and found["env"].user and not found["env"].broken
    assert found["gone"].broken
    assert found["plain"].executable is None and not found["plain"].broken
    assert not found["ir"].user and found["ir"].language == "R"
    assert [k.name for k in kernels.kernels_for(python, found.values())] == ["env"]
    kernels.remove(found["gone"])
    assert sorted(k.name for k in kernels.list_kernels()) == ["env", "ir", "plain"]


def test_kernel_name():
    assert kernels.kernel_name("My Project/.venv") == "my-project-.venv"
    assert kernels.kernel_name("data", ["Data", "data-2"]) == "data-3"
    assert kernels.kernel_name("..") == "python"


def test_register_installs_ipykernel(jupyter_home, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(kernels, "has_ipykernel", lambda python: False)
    monkeypatch.setattr(kernels.packages, "install", lambda python, specs, ctx: calls.append(("install", specs)))

    def fake_run(cmd, ctx):
        calls.append(("run", cmd[1:4]))
        name = cmd[cmd.index("--name") + 1]
        write_spec(jupyter_home / "kernels" / name, [cmd[0]], cmd[cmd.index("--display-name") + 1])

    monkeypatch.setattr(kernels, "run", fake_run)
    kernel = kernels.register(tmp_path / "python", "proj", "Python (proj)")
    assert calls == [("install", ["ipykernel"]), ("run", ["-m", "ipykernel", "install"])]
    assert kernel.name == "proj" and kernel.display_name == "Python (proj)"


def test_register_real_environment(jupyter_home, tmp_path):
    """Network: installs ipykernel into a fresh environment."""
    env = venvs.create_at(tmp_path / "kenv", Path(sys.executable), with_pip=True)
    try:
        kernel = kernels.register(env.executable, "kenv", "Python (kenv)")
    except Exception as exc:  # offline
        pytest.skip(f"could not install ipykernel: {exc}")
    assert kernels.has_ipykernel(env.executable)
    assert kernels.kernels_for(env.executable, kernels.list_kernels()) == [kernel]
    kernels.remove(kernel)
    assert kernels.list_kernels() == []
