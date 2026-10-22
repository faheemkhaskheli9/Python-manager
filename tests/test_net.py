import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from python_manager.core import net


class _Handler(BaseHTTPRequestHandler):
    def _reply(self, payload):
        body = json.dumps(payload).encode()
        gzipped = "gzip" in self.headers.get("Accept-Encoding", "")
        if gzipped:
            body = gzip.compress(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply({"path": self.path})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._reply({"echo": data, "type": self.headers["Content-Type"]})

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_get_json_decompresses_gzip(server):
    assert net.get_json(server + "/x") == {"path": "/x"}


def test_post_json(server):
    assert net.post_json(server + "/q", {"a": [1, 2]}) == {"echo": {"a": [1, 2]}, "type": "application/json"}
