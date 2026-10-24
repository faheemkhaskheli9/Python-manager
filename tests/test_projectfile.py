import sys
from pathlib import Path

from python_manager.core import deps, packages, projectfile
from python_manager.core.deps import Dist


def test_clone_requirements_skips_packaging_tools(monkeypatch):
    monkeypatch.setattr(packages, "freeze", lambda python: "pip==24.0\nRequests==2.32.0\nsetuptools==70.0\n")
    assert projectfile.clone_requirements(Path(sys.executable)) == "Requests==2.32.0\n"
    monkeypatch.setattr(packages, "freeze", lambda python: "pip==24.0\n")
    assert projectfile.clone_requirements(Path(sys.executable)) == ""


def test_pyproject_lists_top_level_packages(monkeypatch, tmp_path):
    graph = {
        "requests": Dist("requests", "2.32.0", ("idna",)),
        "idna": Dist("idna", "3.7", ()),
        "pip": Dist("pip", "24.0", ()),
        "Rich": Dist("Rich", "13.7", ()),
    }
    graph = {deps.normalize(k): v for k, v in graph.items()}
    monkeypatch.setattr(deps, "load_graph", lambda python: graph)
    text = projectfile.pyproject_for(Path(sys.executable), "my env", "3.12.4")
    assert 'name = "my-env"' in text
    assert 'requires-python = ">=3.12"' in text
    assert '"requests>=2.32.0",' in text and '"Rich>=13.7",' in text
    assert "idna" not in text and "pip" not in text

    file = tmp_path / "pyproject.toml"
    file.write_text(text, encoding="utf-8")
    assert projectfile.pyproject_dependencies(file) == ["requests>=2.32.0", "Rich>=13.7"]
    assert projectfile._toml_fallback(text)["project"]["dependencies"] == ["requests>=2.32.0", "Rich>=13.7"]


def test_toml_fallback_parser():
    text = """
[build-system]
requires = ["setuptools"]

[project]
name = "x"
dependencies = [
    "a>=1",  # comment
    'b[extra]; python_version < "4"',
    "c @ https://example.com/c.whl",
]

[project.optional-dependencies]
dev = ["pytest"]

[dependency-groups]
test = ["coverage", {include-group = "lint"}]
lint = ['ruff']
"""
    data = projectfile._toml_fallback(text)
    assert data["project"]["name"] == "x"
    assert data["project"]["dependencies"] == ["a>=1", 'b[extra]; python_version < "4"',
                                               "c @ https://example.com/c.whl"]
    assert data["project"]["optional-dependencies"] == {"dev": ["pytest"]}
    assert data["dependency-groups"] == {"test": ["coverage", {"include-group": "lint"}], "lint": ["ruff"]}
    assert projectfile._toml_fallback("[tool.x]\ndependencies = ['z']\n")["project"] == \
        {"optional-dependencies": {}}


def test_pyproject_requirements(tmp_path):
    file = tmp_path / "pyproject.toml"
    file.write_text("""
[project]
name = "My_App"
dependencies = ["requests"]

[project.optional-dependencies]
docs = ["sphinx"]
all = ["my-app[docs]", "rich"]

[dependency-groups]
dev = ["pytest", {include-group = "lint"}]
lint = ["ruff", {include-group = "dev"}]
""")
    assert projectfile.pyproject_options(file) == (["docs", "all"], ["dev", "lint"])
    assert projectfile.pyproject_requirements(file) == ["requests"]
    assert projectfile.pyproject_requirements(file, extras=["all"]) == ["requests", "sphinx", "rich"]
    assert projectfile.pyproject_requirements(file, groups=["dev"]) == ["requests", "pytest", "ruff"]


def test_install_file_dispatch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(packages, "install", lambda py, specs, ctx: calls.append(("install", list(specs))))
    monkeypatch.setattr(packages, "install_requirements", lambda py, f, ctx: calls.append(("req", f.name)))
    toml = tmp_path / "pyproject.toml"
    toml.write_text('[project]\nname = "x"\ndependencies = ["a"]\n', encoding="utf-8")
    req = tmp_path / "requirements.txt"
    req.write_text("a\n", encoding="utf-8")
    empty = tmp_path / "empty.toml"
    empty.write_text('[project]\nname = "x"\n', encoding="utf-8")

    projectfile.install_file(Path(sys.executable), toml)
    projectfile.install_file(Path(sys.executable), req)
    projectfile.install_file(Path(sys.executable), empty)
    assert calls == [("install", ["a"]), ("req", "requirements.txt")]
