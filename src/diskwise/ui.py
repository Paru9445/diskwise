"""`diskwise ui`: the visual view, served to your browser from this computer only.

The page never sends file paths to clean. It asks for a scan, gets back items
with ids, and asks to clean ids from that scan; the paths come from the
server's own copy of the results. The folder view does send a folder path, but
only to measure it, which never changes anything, and "Show in Finder" only
accepts paths the server itself listed. Every request needs a random token that
only the page opened by `diskwise ui` knows, and only localhost Host headers
are accepted.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, access, android, folders
from .cleaner import History, clean, undo
from .model import CATEGORIES, Item
from .scanner import ScanOptions, scan
from .util import platform_name


class FolderJob:
    def __init__(self, path: Path, admin: bool) -> None:
        self.path = path
        self.admin = admin
        self.entries: list[folders.Entry] = []
        self.done = False
        self.error = ""


class State:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(24)
        self.items: dict[str, Item] = {}
        self.lock = threading.Lock()
        self.progress = ""
        self.folder: FolderJob | None = None
        self.listed: set[str] = set()  # paths the server has shown, which "Show in Finder" may open
        self._places: list[tuple[str, int, Item]] | None = None
        self._known: dict[str, dict | None] = {}

    def set_items(self, items: list[Item]) -> None:
        self.items = {i.id: i for i in items}
        self._places, self._known = None, {}

    def known(self, path: str) -> dict | None:
        """What the last scan knows about `path`: the item it belongs to, or how much
        🟢 Safe space is somewhere inside it."""
        if path in self._known:
            return self._known[path]
        if self._places is None:
            self._places = []
            for item in self.items.values():
                spots = [(d.path, d.size) for d in item.details if d.path] or [(p, item.size) for p in item.paths]
                self._places.extend((os.path.normpath(p), size, item) for p, size in spots)
        result: dict | None = None
        inside = 0
        for place, size, item in self._places:
            if path == place or path.startswith(place + os.sep):
                result = {"id": item.id, "name": item.name, "safety": item.safety}
                break
            if place.startswith(path.rstrip(os.sep) + os.sep) and item.cleanable and item.safety == "safe":
                inside += size
        if result is None and inside:
            result = {"safe_inside": inside}
        self._known[path] = result
        return result


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
            if url.path == "/api/access":
                return self._json(access.status())
            if url.path == "/api/folder":
                return self._json(self._folder_snapshot())
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
            if path == "/api/folder":
                return self._start_folder(str(body.get("path") or "~"), bool(body.get("admin")))
            if path == "/api/reveal":
                target = body.get("path")
                if not isinstance(target, str) or target not in state.listed:
                    return self._json({"error": "Diskwise can only show folders it listed."}, 400)
                access.reveal(target)
                return self._json({"ok": True})
            if path == "/api/access/folders":
                return self._json({"folders": access.request_folders(), **access.status()})
            if path == "/api/access/settings":
                try:
                    access.open_settings(str(body.get("pane")))
                except access.AccessError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json({"ok": True})
            if path == "/api/onboarded":
                access.save_settings(onboarded=True)
                return self._json(access.status())
            self._json({"error": "not found"}, 404)

        def _start_folder(self, text: str, admin: bool) -> None:
            try:
                folder = folders.resolve_folder(text)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            job = FolderJob(folder, admin)
            state.folder = job  # a running walk for another folder sees this and stops
            threading.Thread(target=self._run_folder, args=(job,), daemon=True).start()
            self._json(self._folder_snapshot())

        def _run_folder(self, job: FolderJob) -> None:
            try:
                if job.admin:
                    data = access.measure_as_admin(str(job.path))
                    job.entries = [folders.Entry(**e) for e in data["entries"]]
                else:
                    job.entries = folders.list_entries(job.path)
                    folders.measure(job.path, entries=job.entries, cancelled=lambda: state.folder is not job)
            except PermissionError:
                job.error = "denied"
            except (OSError, access.AccessError, KeyError, TypeError) as exc:
                job.error = str(exc)
            finally:
                job.done = True

        def _folder_snapshot(self) -> dict:
            job = state.folder
            if not job:
                return {"path": None}
            entries = sorted(job.entries, key=lambda e: (not e.done, -e.size))
            out = []
            for e in entries:
                state.listed.add(e.path)
                d = folders.to_dicts([e])[0]
                d["known"] = state.known(e.path) if e.done else None
                out.append(d)
            state.listed.add(str(job.path))
            return {
                "path": str(job.path),
                "crumbs": list(folders.crumbs(job.path)),
                "entries": out,
                "done": job.done,
                "error": job.error,
                "admin": job.admin,
                "denied": sum(e.denied for e in job.entries),
            }

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
                state.set_items(result.items)
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
                cleaned = {o.item.id for o in outcomes if o.freed and not o.errors}
                state.set_items([i for i in state.items.values() if i.id not in cleaned])
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

