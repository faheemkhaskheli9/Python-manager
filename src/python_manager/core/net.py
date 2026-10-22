"""HTTP helpers built on urllib (no third-party dependency)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import ssl
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .tasks import NULL, TaskContext

USER_AGENT = "python-manager/0.1"
_CHUNK = 256 * 1024


def _ssl_context() -> ssl.SSLContext:
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi  # optional, helps on macOS python.org builds

            return ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
    return ssl.create_default_context()


def open_url(url: str, headers: Optional[dict] = None, timeout: float = 30, data: Optional[bytes] = None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    if url.startswith("https:"):
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    return urllib.request.urlopen(req, timeout=timeout)


def _read(resp) -> str:
    body = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        body = gzip.decompress(body)
    return body.decode("utf-8")


def get_text(url: str, headers: Optional[dict] = None, timeout: float = 30) -> str:
    with open_url(url, {"Accept-Encoding": "gzip", **(headers or {})}, timeout) as resp:
        return _read(resp)


def get_json(url: str, headers: Optional[dict] = None, timeout: float = 30) -> Any:
    return json.loads(get_text(url, headers, timeout))


def post_json(url: str, payload: Any, timeout: float = 60) -> Any:
    headers = {"Content-Type": "application/json", "Accept-Encoding": "gzip"}
    with open_url(url, headers, timeout, json.dumps(payload).encode("utf-8")) as resp:
        return json.loads(_read(resp))


def download(url: str, dest: Path, ctx: TaskContext = NULL, sha256: Optional[str] = None) -> Path:
    """Stream ``url`` to ``dest`` with progress reporting and optional checksum verification."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    try:
        with open_url(url, timeout=60) as resp, open(part, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                ctx.check()
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                ctx.progress(done, total)
        if sha256 and digest.hexdigest().lower() != sha256.lower():
            raise ValueError(f"Checksum mismatch for {dest.name}")
        part.replace(dest)
    finally:
        if part.exists():
            part.unlink()
    return dest
