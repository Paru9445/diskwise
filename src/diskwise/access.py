"""Permissions: what Diskwise is allowed to read, and asking for more the proper way.

- macOS keeps some folders private until you allow it: Full Disk Access (Mail,
  Safari, iPhone backups, the Trash…) is switched on in System Settings, and
  Desktop, Documents and Downloads each get a one-time system prompt.
- Folders outside your account (/, other users, system data) need administrator
  rights. Diskwise never runs as administrator itself: it asks the system to run
  a measuring helper (`diskwise measure`), which only reads sizes and writes them
  to a temp file. Cleaning always stays inside your home folder.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import LINUX, MACOS, WINDOWS, data_dir, home

PRIVATE_FOLDERS = ["Desktop", "Documents", "Downloads"]

SETTINGS_PANES = {
    "full-disk": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "files": "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders",
}


class AccessError(Exception):
    pass


def frozen() -> bool:
    """True inside the packaged desktop app (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_name() -> str:
    """Who the system shows in its permission lists for this process."""
    if frozen():
        return "Diskwise"
    return "your terminal app" if MACOS else "Diskwise"


def full_disk_access() -> bool | None:
    """macOS only: can this process read files protected by Full Disk Access?"""
    if not MACOS:
        return None
    # Only readable with Full Disk Access, and trying never shows a prompt. Which of
    # these exist differs between macOS versions, so the first one found decides.
    lib = home() / "Library"
    probes = [lib / "Safari", lib / "Mail", lib / "Messages", lib / "Application Support" / "com.apple.TCC"]
    for probe in probes:
        try:
            os.listdir(probe)
            return True
        except PermissionError:
            return False
        except OSError:
            continue
    return None


def is_admin() -> bool:
    if WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    return os.geteuid() == 0


def admin_available() -> bool:
    if MACOS or WINDOWS:
        return True
    return LINUX and shutil.which("pkexec") is not None


def load_settings() -> dict:
    try:
        return json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**changes) -> dict:
    settings = {**load_settings(), **changes}
    path = data_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def status() -> dict:
    settings = load_settings()
    return {
        "platform": "macos" if MACOS else "windows" if WINDOWS else "linux",
        "app_name": app_name(),
        "desktop_app": frozen(),
        "full_disk_access": full_disk_access(),
        "folders": settings.get("folders"),  # None until the person has been asked
        "admin": is_admin(),
        "admin_available": admin_available(),
        "onboarded": bool(settings.get("onboarded")),
        "home": str(home()),
        "root": home().anchor or "/",
    }


def request_folders() -> dict:
    """Open each private folder once. On macOS this is what shows the system's
    "Diskwise would like to access files in your Desktop folder" prompts, so they
    appear together when the person asks, not halfway through a scan."""
    results = {}
    for name in PRIVATE_FOLDERS:
        folder = home() / name
        if not folder.is_dir():
            continue
        try:
            os.listdir(folder)
            results[name] = True
        except PermissionError:
            results[name] = False
        except OSError:
            continue
    save_settings(folders=results)
    return results


def open_settings(pane: str) -> None:
    if not MACOS or pane not in SETTINGS_PANES:
        raise AccessError("There's no settings page for that on this computer.")
    subprocess.run(["open", SETTINGS_PANES[pane]], check=False)


def reveal(path: str) -> None:
    """Show a file or folder in Finder, Explorer or the Linux file manager."""
    if MACOS:
        subprocess.run(["open", "-R", path], check=False)
    elif WINDOWS:
        subprocess.run(["explorer", f"/select,{path}"], check=False)
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.run(["xdg-open", target], check=False)


def self_command(*args: str) -> list[str]:
    """A command line that runs this same Diskwise (packaged app or source checkout)."""
    if frozen():
        return [sys.executable, *args]
    package_parent = str(Path(__file__).resolve().parent.parent)
    boot = f"import sys; sys.path.insert(0, {package_parent!r}); from diskwise.cli import main; sys.exit(main())"
    return [sys.executable, "-c", boot, *args]


def measure_as_admin(folder: str) -> dict:
    """Measure `folder` with administrator rights. The system asks for the password."""
    tmp = tempfile.mkdtemp(prefix="diskwise-")
    out = os.path.join(tmp, "measure.json")
    cmd = self_command("measure", folder, "--out", out)
    try:
        if MACOS:
            _run_macos_admin(cmd)
        elif WINDOWS:
            _run_windows_admin(cmd)
        elif shutil.which("pkexec"):
            proc = subprocess.run(["pkexec", *cmd], capture_output=True, text=True)
            if proc.returncode in (126, 127):
                raise AccessError("Administrator access wasn't given.")
            if proc.returncode:
                raise AccessError(proc.stderr.strip() or "The measuring helper failed.")
        else:
            raise AccessError("This computer has no pkexec, so Diskwise can't ask for administrator rights.")
        try:
            with open(out, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            raise AccessError("The measuring helper didn't report back.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_macos_admin(cmd: list[str]) -> None:
    # Pass the command as an argument, so nothing has to be escaped into AppleScript.
    script = [
        "on run argv",
        "do shell script (item 1 of argv) with prompt (item 2 of argv) with administrator privileges",
        "end run",
    ]
    prompt = "Diskwise wants to measure folders outside your account. It only reads sizes and changes nothing."
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    proc = subprocess.run([*args, shlex.join(cmd), prompt], capture_output=True, text=True)
    if proc.returncode:
        if "-128" in proc.stderr or "User canceled" in proc.stderr:
            raise AccessError("Administrator access wasn't given.")
        raise AccessError(proc.stderr.strip() or "The measuring helper failed.")


def _run_windows_admin(cmd: list[str]) -> None:
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS: keep a handle so we can wait for it
    info.lpVerb = "runas"  # shows the UAC prompt
    info.lpFile = cmd[0]
    info.lpParameters = subprocess.list2cmdline(cmd[1:])
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.GetLastError() == 1223:  # ERROR_CANCELLED
            raise AccessError("Administrator access wasn't given.")
        raise AccessError("Windows couldn't start the measuring helper.")
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    if code.value:
        raise AccessError("The measuring helper failed.")
