import time

from python_manager.core import config, health, packages, security
from python_manager.core.packages import Package
from python_manager.core.security import Vulnerability

VULN = Vulnerability("GHSA-1", "Jinja2", "2.10", "Sandbox escape", ("CVE-1",), "HIGH", "2.10.1")


def fake(monkeypatch, outdated=None, vulns=(), fail_scan=False):
    monkeypatch.setattr(packages, "outdated", lambda py: dict(outdated or {}))
    monkeypatch.setattr(packages, "installed", lambda py: [Package("Jinja2", "2.10")])

    def scan(items, ctx):
        if fail_scan:
            raise OSError("offline")
        return list(vulns)

    monkeypatch.setattr(security, "scan", scan)


def test_check_all_saves_and_loads(monkeypatch, tmp_path):
    fake(monkeypatch, {"requests": "2.32.0"}, [VULN])
    python = tmp_path / "python"
    reports = health.check_all([python])
    report = reports[str(python)]
    assert report.outdated == {"requests": "2.32.0"} and report.vulns == (VULN,)
    assert report.summary == "1 outdated · ⚠ 1 vulnerable"
    assert health.load()[str(python)] == report  # round trip through JSON
    assert not health.is_due()


def test_security_failure_keeps_updates(monkeypatch, tmp_path):
    fake(monkeypatch, {"requests": "2.32.0"}, fail_scan=True)
    report = health.check(tmp_path / "python")
    assert report.outdated and not report.vulns and report.security_error == "offline"
    assert not report.error and report.summary == "1 outdated"


def test_broken_environment_is_reported(monkeypatch, tmp_path):
    def boom(py):
        raise RuntimeError("no interpreter\ndetails")

    monkeypatch.setattr(packages, "outdated", boom)
    report = health.check_all([tmp_path / "python"])[str(tmp_path / "python")]
    assert report.error == "no interpreter" and report.summary == "check failed"


def test_current_drops_resolved_findings():
    report = health.Report("py", 0, {"requests": "2.32.0", "gone": "1.0"}, (VULN,))
    now = report.current([Package("requests", "2.32.0"), Package("jinja2", "2.10")])
    assert now.outdated == {} and now.vulns == (VULN,)
    now = report.current([Package("requests", "2.0"), Package("jinja2", "3.1")])
    assert now.outdated == {"requests": "2.32.0"} and now.vulns == ()


def test_is_due():
    config.set("last_health_check", 0)
    assert health.is_due()
    config.set("last_health_check", time.time())
    assert not health.is_due()
    config.set("last_health_check", 0)
    config.set("auto_check", False)
    assert not health.is_due()


def test_summarize():
    assert health.summarize([health.Report("a", 0)]) == ""
    reports = [health.Report("a", 0, {"x": "2"}), health.Report("b", 0, {"y": "2"}, (VULN,))]
    assert health.summarize(reports) == "2 environments: 2 outdated packages and 1 known vulnerability."
