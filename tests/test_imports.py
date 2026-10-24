import sys
from pathlib import Path

from python_manager.core import imports, venvs
from python_manager.core.imports import ImportCheck


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_module_imports():
    source = "import os.path, yaml as y\nfrom requests.adapters import X\nfrom . import sib\nfrom .a import b\n"
    assert imports.module_imports(source) == {"os", "yaml", "requests"}
    optional = ("try:\n    import ujson as json\nexcept ImportError:\n    import json\n"
                "try:\n    import certifi\nexcept (ModuleNotFoundError, OSError):\n    pass\n"
                "try:\n    import needed\nexcept KeyError:\n    pass\n")
    assert imports.module_imports(optional) == {"json", "needed"}


def test_scan_skips_envs_hidden_and_build(tmp_path):
    write(tmp_path / "app" / "__init__.py", "import requests\n")
    write(tmp_path / "app" / "util.py", "import app.helpers\nimport util\n")
    write(tmp_path / "src" / "lib" / "core.py", "import numpy\n")
    write(tmp_path / "scripts" / "run.py", "import click\nimport helper\n")
    write(tmp_path / "scripts" / "helper.py", "")
    write(tmp_path / "bad.py", "def (:\n")
    write(tmp_path / ".venv" / "pyvenv.cfg", "")
    write(tmp_path / ".venv" / "x.py", "import hidden\n")
    write(tmp_path / "myenv" / "pyvenv.cfg", "")
    write(tmp_path / "myenv" / "y.py", "import inenv\n")
    write(tmp_path / "build" / "z.py", "import built\n")
    found, local, unreadable = imports.scan(tmp_path)
    assert set(found) == {"requests", "app", "util", "numpy", "click", "helper"}
    assert found["requests"] == tmp_path / "app" / "__init__.py"
    assert {"app", "util", "lib", "helper", "scripts"} <= local
    assert unreadable == [tmp_path / "bad.py"]


def test_compare(tmp_path):
    found = {"requests": tmp_path / "a.py", "yaml": tmp_path / "b.py", "json": tmp_path / "a.py",
             "app": tmp_path / "a.py", "missing_mod": tmp_path / "sub" / "c.py", "__future__": tmp_path / "a.py",
             "urllib3": tmp_path / "a.py"}
    modules = {"requests": ["requests"], "yaml": ["PyYAML"], "urllib3": ["urllib3"],
               "pytest": ["pytest"], "_pytest": ["pytest"], "black": ["black"]}
    checks = imports.compare(found, {"app"}, ["Requests>=2", "pyyaml; python_version>'3'", "pytest", "absent",
                                              "not a requirement!"],
                             modules, {"json"}, tmp_path)
    assert checks == [
        ImportCheck("missing_mod", imports.NOT_INSTALLED, "sub/c.py"),
        ImportCheck("urllib3", imports.NOT_DECLARED, "urllib3"),
        ImportCheck("pytest", imports.NOT_IMPORTED, "_pytest, pytest"),
    ]


def test_environment_of_running_python():
    modules, stdlib = imports.environment(Path(sys.executable))
    assert {"json", "os", "sys"} <= stdlib
    assert "pytest" in modules["pytest"]


def test_check_with_venv(tmp_path):
    project = tmp_path / "proj"
    env = venvs.create_at(project / ".venv", Path(sys.executable), with_pip=True)
    write(project / "main.py", "import json\nimport pip\nimport notinstalled\n")
    checks, unreadable = imports.check(project, [], env.executable)
    assert unreadable == []
    assert {(c.name, c.status) for c in checks} == {("notinstalled", imports.NOT_INSTALLED),
                                                    ("pip", imports.NOT_DECLARED)}
    checks, _ = imports.check(project, ["pip"], env.executable)
    assert [(c.name, c.status) for c in checks] == [("notinstalled", imports.NOT_INSTALLED)]
