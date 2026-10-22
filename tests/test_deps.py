from python_manager.core import deps
from python_manager.core.deps import Dist


def _graph(**requires):
    return {deps.normalize(k): Dist(k, "1.0", tuple(v)) for k, v in requires.items()}


GRAPH = _graph(
    app=["requests", "click"],
    requests=["urllib3", "idna", "certifi"],
    httpx=["idna", "certifi"],
    click=[],
    urllib3=[],
    idna=[],
    certifi=[],
    pip=[],
)


def test_required_by():
    reverse = deps.required_by(GRAPH)
    assert reverse["idna"] == ["httpx", "requests"]
    assert "app" not in reverse


def test_dependents_ignores_packages_being_removed():
    assert deps.dependents(GRAPH, ["requests"]) == {"requests": ["app"]}
    assert deps.dependents(GRAPH, ["app", "requests"]) == {}


def test_unused_after_removal():
    assert deps.unused_after_removal(GRAPH, ["app"]) == ["click", "requests", "urllib3"]
    assert deps.unused_after_removal(GRAPH, ["app", "httpx"]) == ["certifi", "click", "idna", "requests", "urllib3"]


def test_unused_keeps_packaging_tools():
    graph = _graph(tool=["setuptools", "pip"], setuptools=[], pip=[])
    assert deps.unused_after_removal(graph, ["tool"]) == []
