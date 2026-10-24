from datetime import date

from python_manager.core import eol

TODAY = date(2026, 10, 24)


def test_support_status():
    assert eol.support("3.13.1", TODAY).status == eol.SUPPORTED
    assert eol.support("3.10.14", TODAY).status == eol.ENDS_SOON
    assert eol.support("3.9.18", TODAY).status == eol.END_OF_LIFE
    assert eol.support("3.11.0", TODAY).status == eol.SUPPORTED
    assert eol.support("3.11.0", date(2027, 6, 1)).status == eol.ENDS_SOON
    assert eol.support("3.10.0", date(2026, 10, 31)).status == eol.END_OF_LIFE


def test_versions_outside_the_table():
    assert eol.support("3.14.0rc1", TODAY).end == date(2030, 10, 31)
    assert eol.support("3.99.0", TODAY) == eol.Support(eol.SUPPORTED, None)
    assert eol.support("3.4.10", TODAY).status == eol.END_OF_LIFE
    assert eol.support("2.6.9", TODAY).status == eol.END_OF_LIFE
    assert eol.support("", TODAY) is None
    assert eol.support("unknown", TODAY) is None


def test_labels():
    assert eol.support("3.9.1", TODAY).label == "End of life since 2025-10-31"
    assert eol.support("3.10.1", TODAY).label == "Ends soon (until 2026-10-31)"
    assert eol.support("3.99", TODAY).label == "Supported"
    assert not eol.support("3.13.0", TODAY).needs_attention
    assert eol.support("3.8.0", TODAY).needs_attention
