from python_manager.core import favorites


def test_add_remove_toggle_normalised():
    assert favorites.list_favorites() == []
    favorites.add("Requests")
    favorites.add("requests")  # same package, not duplicated
    favorites.add("Foo_Bar")
    assert favorites.list_favorites() == ["Foo_Bar", "Requests"]
    assert favorites.is_favorite("foo-bar")

    assert favorites.toggle("foo.bar") is False
    assert favorites.toggle("numpy") is True
    assert favorites.list_favorites() == ["numpy", "Requests"]

    favorites.remove("REQUESTS")
    assert favorites.list_favorites() == ["numpy"]


def test_blank_name_ignored():
    favorites.add("  ")
    assert favorites.list_favorites() == []
