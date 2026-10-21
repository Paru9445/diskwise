import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from conftest import write
from diskwise.ui import State, make_handler


@pytest.fixture
def server(fake_home, monkeypatch):
    # Keep the scan small and offline: no projects walk, no Docker.
    import diskwise.ui as ui_mod
    from diskwise.scanner import ScanOptions, scan

    monkeypatch.setattr(ui_mod, "scan", lambda opts: scan(ScanOptions(projects=False, docker=False)))
    state = State()
    port = [0]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state, port))
    port[0] = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield state, port[0]
    httpd.shutdown()
    httpd.server_close()


def call(port, path, token=None, body=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode())
    if token:
        req.add_header("X-Diskwise-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_page_carries_token(server):
    state, port = server
    status, body = call(port, "/")
    assert status == 200 and state.token.encode() in body


def test_api_needs_token_and_local_host(server):
    state, port = server
    assert call(port, "/api/history")[0] == 403
    assert call(port, "/api/history", token="wrong")[0] == 403
    assert call(port, "/api/history", token=state.token, host="evil.example")[0] == 403
    assert call(port, "/", host=f"evil.example:{port}")[0] == 403
    assert call(port, "/api/history", token=state.token)[0] == 200


def test_clean_only_accepts_ids_from_the_last_scan(server, fake_home):
    state, port = server
    cache = write(fake_home / ".npm" / "_cacache" / "blob", 50_000)
    status, body = call(port, "/api/scan", token=state.token)
    assert status == 200
    assert "npm-cache" in [i["id"] for i in json.loads(body)["items"]]

    status, _ = call(port, "/api/clean", token=state.token, body={"ids": ["made-up", "/etc/passwd"]})
    assert status == 400 and cache.exists()

    status, body = call(port, "/api/clean", token=state.token, body={"ids": ["npm-cache"]})
    assert status == 200 and json.loads(body)["freed"] > 0
    assert not cache.exists()

    status, body = call(port, "/api/undo", token=state.token, body={})
    assert json.loads(body)["restored"] == 1 and cache.exists()
