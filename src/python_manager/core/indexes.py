"""Package index settings (a private index or mirror) passed to pip and uv."""

from __future__ import annotations

import re
import urllib.parse

from . import config


def split(text: str) -> list[str]:
    """Entries separated by spaces, commas or new lines."""
    return [part for part in re.split(r"[\s,]+", text or "") if part]


def invalid_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme not in ("http", "https") or not parsed.netloc


def env() -> dict[str, str]:
    """Environment variables that point pip, uv and pipx at the configured indexes.

    Empty when nothing is configured, so variables the user set themselves still apply.
    """
    index = (config.get("index_url") or "").strip()
    extra = " ".join(split(config.get("extra_index_urls") or ""))
    trusted = " ".join(split(config.get("trusted_hosts") or ""))
    result = {}
    if index:
        result.update(PIP_INDEX_URL=index, UV_INDEX_URL=index)
    if extra:
        result.update(PIP_EXTRA_INDEX_URL=extra, UV_EXTRA_INDEX_URL=extra)
    if trusted:
        result.update(PIP_TRUSTED_HOST=trusted, UV_INSECURE_HOST=trusted)
    return result
