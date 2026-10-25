"""`diskwise ui`: the visual view, served to your browser from this computer only.

The page never sends file paths. It asks for a scan, gets back items with ids,
and asks to clean ids from that scan; the paths come from the server's own
copy of the results. Every request needs a random token that only the page
opened by `diskwise ui` knows, and only localhost Host headers are accepted.
"""

from __future__ import annotations

import json
import secrets
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, android
from .cleaner import History, clean, undo
from .model import CATEGORIES, Item
from .scanner import ScanOptions, scan
from .util import platform_name


class State:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.items: dict[str, Item] = {}
        self.lock = threading.Lock()
        self.progress = ""


def _disk() -> dict:
    u = shutil.disk_usage(Path.home())
    return {"total": u.total, "used": u.used, "free": u.free}


def make_handler(state: State, port_ref: list[int]):
    page = resources.files("diskwise").joinpath("ui.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        server_version = f"diskwise/{__version__}"

        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

        def _host_ok(self) -> bool:
            host = self.headers.get("Host", "")
            return host in (f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}")

        def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200) -> None:
            self._send(code, json.dumps(data).encode())

        def _authorized(self) -> bool:
            if not self._host_ok():
                self._json({"error": "bad host"}, 403)
                return False
            if not secrets.compare_digest(self.headers.get("X-Diskwise-Token", ""), state.token):
                self._json({"error": "bad token"}, 403)
                return False
            return True

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                if not self._host_ok():
                    return self._send(403, b"Forbidden", "text/plain")
                html = page.replace("__TOKEN__", state.token).replace("__VERSION__", __version__)
                html = html.replace("__PLATFORM__", platform_name())
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if not self._authorized():
                return
            if url.path == "/api/scan":
                q = parse_qs(url.query)
                return self._scan(phone=q.get("android") == ["1"], projects=q.get("projects") != ["0"])
            if url.path == "/api/progress":
                return self._json({"message": state.progress})
            if url.path == "/api/history":
                return self._json({"sessions": list(reversed(History().load()))})
            self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            if not self._authorized():
                return
            length = min(int(self.headers.get("Content-Length") or 0), 100_000)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            path = urlparse(self.path).path
            if path == "/api/clean":
                return self._clean(body.get("ids") or [])
            if path == "/api/undo":
                r = undo()
                return self._json({
                    "session": r.session, "restored": r.restored,
                    "errors": r.errors, "skipped": r.skipped_commands,
                })
            self._json({"error": "not found"}, 404)

        def _scan(self, phone: bool, projects: bool) -> None:
            if not state.lock.acquire(blocking=False):
                return self._json({"error": "A scan or clean is already running."}, 409)
            try:
                state.progress = "Starting"
                if phone:
                    state.progress = "Reading your phone's storage"
                    result = android.scan()
                else:
                    result = scan(ScanOptions(projects=projects, progress=lambda m: setattr(state, "progress", m)))
                state.items = {i.id: i for i in result.items}
                data = result.to_dict()
                data["disk"] = _disk()
                data["categories"] = CATEGORIES
                self._json(data)
            finally:
                state.progress = ""
                state.lock.release()

        def _clean(self, ids: list) -> None:
            chosen = [state.items[i] for i in ids if isinstance(i, str) and i in state.items]
            if not chosen:
                return self._json({"error": "Nothing selected, or the scan is out of date. Scan again."}, 400)
            if not state.lock.acquire(blocking=False):
                return self._json({"error": "A scan or clean is already running."}, 409)
            try:
                state.progress = "Cleaning"
                outcomes = clean(chosen)
                for o in outcomes:
                    if o.freed and not o.errors:
                        state.items.pop(o.item.id, None)
                self._json({
                    "outcomes": [
                        {"id": o.item.id, "name": o.item.name, "freed": o.freed, "moved": o.moved,
                         "errors": o.errors[:20], "ran": o.ran}
                        for o in outcomes
                    ],
                    "freed": sum(o.freed for o in outcomes),
                    "disk": _disk(),
                })
            finally:
                state.progress = ""
                state.lock.release()

    return Handler


def make_server(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Bind the server on 127.0.0.1 and return it with the page's URL, without serving yet."""
    state = State()
    port_ref = [port]
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, port_ref))
    port_ref[0] = server.server_address[1]
    return server, f"http://127.0.0.1:{port_ref[0]}/"


def serve(port: int = 0, open_browser: bool = True) -> int:
    server, url = make_server(port)
    print(f"\n  Diskwise is open at {url}")
    print("  It only listens on this computer. Press Ctrl+C to stop.\n")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("  Stopped.")
    return 0

