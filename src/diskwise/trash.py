"""Move files to the Trash (macOS, Linux) or Recycle Bin (Windows), and put them back.

- macOS: items go into one folder per clean in your Trash, named like
  "Diskwise 2026-10-21 18.30.05", so you can see what Diskwise moved.
- Linux: the freedesktop.org Trash spec, so your file manager's Restore works too.
- Windows: the shell's Recycle Bin, so Explorer's Restore works too.

Nothing is ever deleted permanently here. If a path can't be moved to the
Trash (for example it is on another drive), it is left where it is.
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .util import MACOS, WINDOWS, home


class TrashError(Exception):
    pass


@dataclass
class Moved:
    original: str
    location: str  # where it sits in the Trash ("" on Windows: the Recycle Bin tracks it)


def _same_drive(a: Path, b: Path) -> bool:
    try:
        return os.lstat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def _unique(folder: Path, name: str) -> Path:
    candidate = folder / name
    n = 2
    while candidate.exists() or candidate.is_symlink():
        stem, dot, ext = name.partition(".") if not name.startswith(".") else (name, "", "")
        candidate = folder / (f"{stem} {n}{dot}{ext}")
        n += 1
    return candidate


class Trash:
    """One clean session. All paths moved by one `diskwise clean` share a session."""

    def __init__(self, session: str | None = None):
        self.session = session or datetime.now().strftime("%Y-%m-%d %H.%M.%S")

    # -------------------------------------------------------------- moving
    def move(self, path: str | os.PathLike, group: str = "") -> Moved:
        path = Path(path)
        if not (path.exists() or path.is_symlink()):
            raise TrashError("it no longer exists")
        if MACOS:
            return self._move_macos(path, group)
        if WINDOWS:
            return self._move_windows(path)
        return self._move_freedesktop(path)

    def _move_macos(self, path: Path, group: str) -> Moved:
        trash = home() / ".Trash"
        if not _same_drive(path, trash):
            raise TrashError("it is on another drive; move it to the Trash in Finder instead")
        folder = trash / f"Diskwise {self.session}"
        if group:
            folder = folder / group
        folder.mkdir(parents=True, exist_ok=True)
        dest = _unique(folder, path.name)
        os.rename(path, dest)
        return Moved(original=str(path), location=str(dest))

    def _move_freedesktop(self, path: Path) -> Moved:
        data = Path(os.environ.get("XDG_DATA_HOME") or home() / ".local" / "share")
        files, info = data / "Trash" / "files", data / "Trash" / "info"
        files.mkdir(parents=True, exist_ok=True)
        info.mkdir(parents=True, exist_ok=True)
        if not _same_drive(path, files):
            raise TrashError("it is on another drive; move it to the Trash in your file manager instead")
        name = path.name
        n = 1
        while True:
            try:
                fd = os.open(info / f"{name}.trashinfo", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                n += 1
                name = f"{path.name}.{n}"
        with os.fdopen(fd, "w") as fh:
            fh.write(
                "[Trash Info]\n"
                f"Path={quote(str(path.absolute()))}\n"
                f"DeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
            )
        dest = files / name
        try:
            os.rename(path, dest)
        except OSError:
            os.unlink(info / f"{name}.trashinfo")
            raise
        return Moved(original=str(path), location=str(dest))

    def _move_windows(self, path: Path) -> Moved:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x4, 0x10, 0x40
        FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x400, 0x4000
        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = str(path.absolute()) + "\0"  # the list must end with two NULs
        # WANTNUKEWARNING makes Windows ask first if something is too big for the
        # Recycle Bin, instead of silently deleting it for good.
        op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if code != 0 or op.fAnyOperationsAborted:
            raise TrashError(f"Windows couldn't move it to the Recycle Bin (error {code:#x}); it may be in use")
        return Moved(original=str(path), location="")

    # ----------------------------------------------------------- restoring
    @staticmethod
    def restore(moved: Moved) -> None:
        original = Path(moved.original)
        if original.exists() or original.is_symlink():
            raise TrashError("something new already exists at its original place (the app recreated it)")
        location = Path(moved.location) if moved.location else None
        info = None
        if WINDOWS and not location:
            location, info = _find_in_recycle_bin(original)
        if location is None or not (location.exists() or location.is_symlink()):
            raise TrashError("it is no longer in the Trash (was the Trash emptied?)")
        original.parent.mkdir(parents=True, exist_ok=True)
        os.rename(location, original)
        if not MACOS and not WINDOWS:
            info = location.parent.parent / "info" / f"{location.name}.trashinfo"
        if info is not None:
            try:
                os.unlink(info)
            except OSError:
                pass
        if MACOS:
            # Remove the "Diskwise <session>/<item>" folders once they are empty.
            for folder in (location.parent, location.parent.parent):
                if folder.name.startswith("Diskwise ") or folder.parent.name.startswith("Diskwise "):
                    try:
                        folder.rmdir()
                    except OSError:
                        break


def parse_recycle_info(data: bytes) -> tuple[str, int]:
    """Original path and deletion time (FILETIME) from a Windows $I file."""
    version, _size, deleted = struct.unpack_from("<qqq", data, 0)
    if version == 1:
        raw = data[24:24 + 520]
    else:
        (length,) = struct.unpack_from("<i", data, 24)
        raw = data[28:28 + length * 2]
    return raw.decode("utf-16-le").split("\0", 1)[0], deleted


def _find_in_recycle_bin(original: Path) -> tuple[Path | None, Path | None]:
    bin_root = Path(original.anchor) / "$Recycle.Bin"
    best: tuple[int, Path, Path] | None = None
    target = str(original).lower()
    try:
        sids = list(bin_root.iterdir())
    except OSError:
        return None, None
    for sid in sids:
        try:
            entries = list(sid.glob("$I*"))
        except OSError:
            continue  # another user's Recycle Bin
        for info in entries:
            try:
                path, deleted = parse_recycle_info(info.read_bytes())
            except (OSError, struct.error, UnicodeDecodeError):
                continue
            if path.lower() == target and (best is None or deleted > best[0]):
                best = (deleted, info.with_name("$R" + info.name[2:]), info)
    if best is None:
        return None, None
    return best[1], best[2]
