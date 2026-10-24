import sys
from pathlib import Path

from python_manager.core import compare
from python_manager.core.packages import Package


def test_diff_and_summary():
    left = [Package("Requests", "2.32.0"), Package("idna", "3.7"), Package("only_left", "1.0")]
    right = [Package("requests", "2.31.0"), Package("idna", "3.7"), Package("Only-Right", "0.1")]
    rows = compare.diff(left, right)
    assert [(r.name, r.left, r.right, r.status) for r in rows] == [
        ("idna", "3.7", "3.7", compare.SAME),
        ("Only-Right", "", "0.1", compare.ONLY_RIGHT),
        ("only_left", "1.0", "", compare.ONLY_LEFT),
        ("Requests", "2.32.0", "2.31.0", compare.DIFFERENT),
    ]
    assert compare.summary(rows) == {compare.DIFFERENT: 1, compare.ONLY_LEFT: 1, compare.ONLY_RIGHT: 1,
                                     compare.SAME: 1}
    assert compare.match_left(rows) == ["only_left==1.0", "Requests==2.32.0"]


def test_matcher():
    assert compare.matcher("Django")("django-filter")
    assert not compare.matcher("django-*")("django")
    assert compare.matcher("django-*")("Django_Filter")
    assert compare.matcher("py?est")("pytest")


def test_find_reports_unreadable(tmp_path):
    targets = [("tests", Path(sys.executable)), ("gone", tmp_path / "missing-python")]
    matches, failed = compare.find("pytest", targets)
    assert any(m.name.lower() == "pytest" and m.location == "tests" for m in matches)
    assert failed == ["gone"]
