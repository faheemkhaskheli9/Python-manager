import sys

from python_manager.core import config, indexes, tasks


def test_split_and_validate():
    assert indexes.split(" https://a/simple,https://b/simple\nhttps://c ") == [
        "https://a/simple", "https://b/simple", "https://c"]
    assert not indexes.invalid_url("https://user:token@pkgs.example.com/simple")
    assert indexes.invalid_url("pkgs.example.com/simple")
    assert indexes.invalid_url("ftp://example.com/simple")


def test_env_empty_by_default():
    assert indexes.env() == {}


def test_env_sets_pip_and_uv_variables():
    config.set("index_url", " https://mirror.example/simple ")
    config.set("extra_index_urls", "https://a.example/simple https://b.example/simple")
    config.set("trusted_hosts", "a.example")
    assert indexes.env() == {
        "PIP_INDEX_URL": "https://mirror.example/simple",
        "UV_INDEX_URL": "https://mirror.example/simple",
        "PIP_EXTRA_INDEX_URL": "https://a.example/simple https://b.example/simple",
        "UV_EXTRA_INDEX_URL": "https://a.example/simple https://b.example/simple",
        "PIP_TRUSTED_HOST": "a.example",
        "UV_INSECURE_HOST": "a.example",
    }


def test_commands_receive_index_settings():
    config.set("index_url", "https://mirror.example/simple")
    code = "import os; print(os.environ['PIP_INDEX_URL'], os.environ['UV_INDEX_URL'])"
    expected = "https://mirror.example/simple https://mirror.example/simple"
    assert tasks.capture([sys.executable, "-c", code]).stdout.strip() == expected
    assert tasks.run([sys.executable, "-c", code], echo=False).strip() == expected
