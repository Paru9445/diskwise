"""Folder view: what's inside any folder you pick, biggest first.

This only measures. Nothing here moves or deletes anything, so it can look
anywhere, including / with administrator rights (see access.measure_as_admin).
"""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator

from .sizes import usage
from .util import LINUX, MACOS

# Never listed or walked: kernel and device file systems (walking /proc never ends), and
# on macOS /System/Volumes/Data, a second path to what /Users, /Applications and the
# other top-level folders already show, which would count everything twice.
PSEUDO = (
    {"/dev", "/proc", "/sys", "/run"} if LINUX
    else {"/dev", "/System/Volumes/Data"} if MACOS
    else set()
)


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    files: int = 0
    denied: int = 0
    other_disk: bool = False  # a mount point for another drive (shown, not measured)
    done: bool = False


def resolve_folder(text: str) -> Path:
    """Turn what the person typed or picked into an absolute folder. Raises ValueError."""
    path = Path(os.path.expanduser(text.strip() or "~"))
    if not path.is_absolute():
        raise ValueError("Use a full path, like / or ~/Projects.")
    path = Path(os.path.abspath(path))
    if not path.is_dir():
        raise ValueError(f"{path} isn't a folder you can open.")
    return path


def list_entries(folder: Path) -> list[Entry]:
    """The folder's direct contents, unmeasured. Raises PermissionError if it can't be read."""
    device = os.lstat(folder).st_dev
    out = []
    with os.scandir(folder) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISLNK(st.st_mode) or e.path in PSEUDO:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            # On macOS / and its firmlinked folders (like /Users) sit on different volumes,
            # so only treat /Volumes/* style mounts as "another disk".
            other = is_dir and st.st_dev != device and os.path.ismount(e.path) and not _firmlinked(e.path)
            out.append(Entry(e.name, e.path, is_dir, other_disk=other, done=other))
    return out


def _firmlinked(path: str) -> bool:
    return MACOS and os.path.dirname(path) == "/"


def measure(
    folder: Path,
    entries: list[Entry] | None = None,
    on_entry: Callable[[Entry], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    workers: int = 6,
) -> list[Entry]:
    """Measure every entry in `folder` (or the `entries` already listed from it),
    filling each one in place and calling `on_entry` as it finishes."""
    entries = list_entries(folder) if entries is None else entries

    def one(entry: Entry) -> Entry:
        if not entry.done:
            u = usage(entry.path, one_device=True, cancelled=cancelled, skip=PSEUDO)
            entry.size, entry.files, entry.denied = u.bytes, u.files, len(u.denied)
            entry.done = True
        if on_entry:
            on_entry(entry)
        return entry

    # Folders first: they take longest, and files are instant.
    order = sorted(entries, key=lambda e: not e.is_dir)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, order))
    return sorted(entries, key=lambda e: -e.size)


def to_dicts(entries: list[Entry]) -> list[dict]:
    return [asdict(e) for e in entries]


def crumbs(folder: Path) -> Iterator[dict]:
    """Breadcrumbs from the root down to `folder`."""
    parts = [folder, *folder.parents][::-1]
    for p in parts:
        yield {"name": p.name or str(p), "path": str(p)}
