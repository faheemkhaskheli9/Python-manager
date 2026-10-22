import os
import time

import pytest

from python_manager.core import net, pypi_names


def _fake_index(names):
    def get_text(url, headers=None, timeout=30):
        assert url == pypi_names.SIMPLE_URL
        assert headers["Accept"] == "application/vnd.pypi.simple.v1+json"
        return '{"meta": {}, "projects": [%s]}' % ", ".join(f'{{"name": "{n}"}}' for n in names)
    return get_text


def test_fetch_caches_sorted_names(monkeypatch):
    monkeypatch.setattr(net, "get_text", _fake_index(["requests", "Django", "attrs", "django-rest"]))
    assert pypi_names.load() == ["attrs", "Django", "django-rest", "requests"]
    assert pypi_names.cached() == ["attrs", "Django", "django-rest", "requests"]
    assert not pypi_names.is_stale()

    monkeypatch.setattr(net, "get_text", lambda *a, **k: pytest.fail("fresh cache must not be refetched"))
    assert pypi_names.load() == ["attrs", "Django", "django-rest", "requests"]


def test_stale_cache_refreshes_and_falls_back(monkeypatch):
    monkeypatch.setattr(net, "get_text", _fake_index(["old"]))
    pypi_names.load()
    old = time.time() - pypi_names.MAX_AGE - 60
    os.utime(pypi_names.cache_file(), (old, old))
    assert pypi_names.is_stale()

    def offline(*_a, **_k):
        raise OSError("offline")

    monkeypatch.setattr(net, "get_text", offline)
    assert pypi_names.load() == ["old"]  # old cache beats no suggestions

    monkeypatch.setattr(net, "get_text", _fake_index(["new"]))
    assert pypi_names.load() == ["new"]


def test_no_cache_and_offline_raises(monkeypatch):
    monkeypatch.setattr(net, "get_text", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError):
        pypi_names.load()
