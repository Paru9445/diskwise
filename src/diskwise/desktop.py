"""The Diskwise desktop app: the visual view in its own window instead of a browser tab.

It runs the same server as `diskwise ui` on 127.0.0.1 and shows the page in the
system's web view (WebKit on macOS, Edge WebView2 on Windows, Qt WebEngine on Linux).
Needs the optional `pywebview` package: `pip install diskwise[desktop]`.
"""

from __future__ import annotations

import os
import sys
import threading

from . import __version__
from .ui import make_server

# Apps opened from Finder, the Start Menu or a Linux launcher get a short PATH,
# so tools like docker, brew and adb would look missing. Add the usual places.
EXTRA_PATHS = {
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin", "/Applications/Docker.app/Contents/Resources/bin"],
    "linux": ["/usr/local/bin", "/snap/bin", "~/.local/bin"],
    "win32": [],
}


def _extend_path() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in EXTRA_PATHS.get(sys.platform, []):
        d = os.path.expanduser(d)
        if d not in parts and os.path.isdir(d):
            parts.append(d)
    os.environ["PATH"] = os.pathsep.join(p for p in parts if p)


def main() -> int:
    try:
        import webview
    except ImportError:
        print("The desktop app needs pywebview: pip install 'diskwise[desktop]'", file=sys.stderr)
        return 1

    _extend_path()
    server, url = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webview.create_window(f"Diskwise {__version__}", url, width=1100, height=800, min_size=(720, 520))
    try:
        # On Linux the app ships with Qt's web view, so it doesn't depend on GTK WebKit being installed.
        webview.start(gui="qt" if sys.platform.startswith("linux") else None)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
