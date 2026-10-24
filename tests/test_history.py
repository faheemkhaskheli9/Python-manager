from pathlib import Path

from python_manager.core import history, packages
from python_manager.core.packages import Package

PY = Path("/envs/demo/bin/python")


def _installed(monkeypatch, items):
    state = {"packages": [Package(n, v) for n, v in items]}
    monkeypatch.setattr(packages, "installed", lambda _python: list(state["packages"]))
    return state


def test_snapshot_skips_unchanged_and_keeps_limit(monkeypatch):
    state = _installed(monkeypatch, [("requests", "2.31.0")])
    assert history.snapshot(PY, "Installing a")
    assert history.snapshot(PY, "Installing b") is None  # same packages as the last snapshot
    state["packages"] = [Package("Requests", "2.32.0")]
    history.snapshot(PY, "Upgrading requests")
    assert [s.action for s in history.snapshots(PY)] == ["Upgrading requests", "Installing a"]
    assert history.snapshots(Path("/other/python")) == []

    monkeypatch.setattr(history, "LIMIT", 3)
    for n in range(5):
        state["packages"] = [Package("pkg", str(n))]
        history.snapshot(PY, f"step {n}")
    assert [s.action for s in history.snapshots(PY)] == ["step 4", "step 3", "step 2"]
    history.clear(PY)
    assert history.snapshots(PY) == []


def test_plan_and_restore(monkeypatch):
    _installed(monkeypatch, [("requests", "2.31.0"), ("idna", "3.6"), ("pip", "24.0")])
    history.snapshot(PY, "Upgrading requests")
    snap = history.snapshots(PY)[0]
    state = _installed(monkeypatch, [("requests", "2.32.0"), ("idna", "3.6"), ("urllib3", "2.0"),
                                     ("pip", "24.0"), ("wheel", "0.43")])
    calls = []
    monkeypatch.setattr(packages, "install", lambda py, specs, ctx: calls.append(("install", specs)))
    monkeypatch.setattr(packages, "uninstall", lambda py, names, ctx: calls.append(("uninstall", names)))

    todo = history.plan(state["packages"], snap)
    assert todo.install == ["requests==2.31.0"] and todo.remove == ["urllib3"]  # wheel stays
    assert history.restore(PY, snap) == todo
    assert calls == [("install", ["requests==2.31.0"]), ("uninstall", ["urllib3"])]
    assert history.snapshots(PY)[0].action.startswith("Restoring snapshot of ")

    state["packages"] = list(snap.packages)
    calls.clear()
    assert history.restore(PY, snap).empty and calls == []
