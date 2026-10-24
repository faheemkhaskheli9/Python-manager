import sys
from pathlib import Path

from python_manager.core import conda


def make_env(path: Path, python: str = "3.11.5") -> Path:
    (path / "conda-meta").mkdir(parents=True)
    (path / "conda-meta" / "python-dateutil-2.9.0-pyhd8ed1ab_0.json").write_text("{}")
    if python:
        (path / "conda-meta" / f"python-{python}-h955ad1f_0_cpython.json").write_text("{}")
        exe = path / "python.exe" if sys.platform == "win32" else path / "bin" / "python"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("")
    return path


def test_list_envs(tmp_path, monkeypatch):
    home = tmp_path / "user"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for var in ("CONDA_ROOT", "MAMBA_ROOT_PREFIX", "CONDA_EXE", "CONDA_PREFIX", "LOCALAPPDATA", "ProgramData"):
        monkeypatch.delenv(var, raising=False)
    root = make_env(home / "miniconda3", "3.12.4")
    make_env(root / "envs" / "science")
    make_env(root / "envs" / "r-only", python="")
    custom = make_env(tmp_path / "elsewhere" / "proj-env", "3.10.14")
    (home / ".conda").mkdir()
    (home / ".conda" / "environments.txt").write_text(f"{custom}\n{root}\n{tmp_path / 'gone'}\n")

    envs = {e.name: e for e in conda.list_envs() if tmp_path in e.path.parents}  # ignore real installs
    assert set(envs) == {"base (miniconda3)", "science", "r-only", "proj-env"}
    assert envs["base (miniconda3)"].version == "3.12.4"
    assert envs["science"].version == "3.11.5" and envs["science"].valid
    assert envs["r-only"].version == "" and not envs["r-only"].valid
    interp = envs["proj-env"].interpreter()
    assert (interp.kind, interp.version) == (conda.CONDA, "3.10.14")
    assert "read-only" in interp.label
    assert conda.activation_command(envs["science"]) == "conda activate science"
    assert str(custom) in conda.activation_command(envs["proj-env"])
