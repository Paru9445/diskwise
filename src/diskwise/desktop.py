"""The Diskwise desktop app: the visual view in its own window instead of a browser tab.

It runs the same server as `diskwise ui` on 127.0.0.1 and shows the page in the
system's web view (WebKit on macOS, Edge WebView2 on Windows, Qt WebEngine on Linux).
Needs the optional `pywebview` package: `pip install diskwise[desktop]`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser

from . import __version__
from .ui import make_server

# Apps opened from Finder, the Start Menu or a Linux launcher get a short PATH,
# so tools like docker, brew and adb would look missing. Add the usual places.
EXTRA_PATHS = {
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin", "/Applications/Docker.app/Contents/Resources/bin"],
    "linux": ["/usr/local/bin", "/snap/bin", "~/.local/bin"],
    "win32": [],
}

HOMEPAGE = "https://github.com/Paru9445/diskwise"


def _extend_path() -> None:
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for d in EXTRA_PATHS.get(sys.platform, []):
        d = os.path.expanduser(d)
        if d not in parts and os.path.isdir(d):
            parts.append(d)
    os.environ["PATH"] = os.pathsep.join(p for p in parts if p)


def _dark() -> bool:
    if sys.platform != "darwin":
        return False
    out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True)
    return "Dark" in out.stdout


class Api:
    """Called from the page as window.pywebview.api.*: things only a real app can do."""

    def __init__(self) -> None:
        self.window = None

    def pick_folder(self, start: str = "") -> str | None:
        import webview

        picked = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start or os.path.expanduser("~"))
        return picked[0] if picked else None


def main() -> int:
    # The administrator helper re-runs this same app with `measure …`: no window then.
    if len(sys.argv) > 1 and sys.argv[1] == "measure":
        from .cli import main as cli_main

        return cli_main(sys.argv[1:])

    try:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator
    except ImportError:
        print("The desktop app needs pywebview: pip install 'diskwise[desktop]'", file=sys.stderr)
        return 1

    _extend_path()
    server, url = make_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    api = Api()
    window = webview.create_window(
        "Diskwise", url, js_api=api, width=1120, height=820, min_size=(760, 560),
        background_color="#141513" if _dark() else "#f6f6f3",
    )
    api.window = window

    def call(js: str):
        return lambda: window.evaluate_js(js)

    menu = [
        Menu("Scan", [
            MenuAction("Scan This Computer", call("app.scan()")),
            MenuAction("Scan Android Phone", call("app.scan(true)")),
            MenuSeparator(),
            MenuAction("Choose Folder…", call("app.chooseFolder()")),
            MenuAction("Look at Whole Disk", call("app.openFolder(ACCESS.root)")),
        ]),
        Menu("Permissions", [
            MenuAction("Check Access…", call("app.showAccess()")),
        ]),
        Menu("Help", [
            MenuAction(f"Diskwise {__version__} on GitHub", lambda: webbrowser.open(HOMEPAGE)),
            MenuAction("Report a Space Hog", lambda: webbrowser.open(HOMEPAGE + "/issues/new?template=space-hog.yml")),
        ]),
    ]
    try:
        # On Linux the app ships with Qt's web view, so it doesn't depend on GTK WebKit being installed.
        webview.start(gui="qt" if sys.platform.startswith("linux") else None, menu=menu)
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
