"""Measure how much disk space a file or folder really uses.

Sizes are allocated blocks, not apparent sizes, so sparse files (like a Docker
or emulator disk image) are counted for what they actually take up. Symlinks
are never followed, and hard-linked files are counted once (except on Windows,
where os.scandir doesn't report link counts; hard links are rare there).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: junctions and symlinks on Windows


@dataclass
class Usage:
    bytes: int = 0
    files: int = 0
    denied: list[str] = field(default_factory=list)

    def add(self, other: "Usage") -> None:
        self.bytes += other.bytes
        self.files += other.files
        self.denied.extend(other.denied)


def _allocated(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    if blocks is not None:
        return blocks * 512
    return st.st_size


def _is_link(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def usage(
    path: str | os.PathLike,
    seen: set | None = None,
    one_device: bool = False,
    cancelled: Callable[[], bool] | None = None,
    skip: set[str] | frozenset[str] = frozenset(),
) -> Usage:
    """Total allocated size of `path` (file or folder), walking without following links.

    With `one_device`, folders on another disk or mount (like /Volumes/* or /proc)
    are skipped, so measuring / doesn't walk other drives or system mounts.
    Folders in `skip` are never entered. `cancelled` is checked between folders
    to stop a long walk early.
    """
    seen = set() if seen is None else seen
    result = Usage()
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return result
    except OSError:
        result.denied.append(str(path))
        return result

    if not stat.S_ISDIR(st.st_mode) or _is_link(st):
        _count(st, result, seen)
        return result

    result.bytes += _allocated(st)
    device = st.st_dev
    stack = [os.fspath(path)]
    while stack:
        if cancelled and cancelled():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            result.denied.append(current)
            continue
        for entry in entries:
            try:
                est = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(est.st_mode) and not _is_link(est):
                if (one_device and est.st_dev != device) or entry.path in skip:
                    continue
                result.bytes += _allocated(est)
                stack.append(entry.path)
            else:
                _count(est, result, seen)
    return result


def _count(st: os.stat_result, result: Usage, seen: set) -> None:
    if st.st_nlink > 1 and not stat.S_ISDIR(st.st_mode):
        key = (st.st_dev, st.st_ino)
        if key in seen:
            return
        seen.add(key)
    result.bytes += _allocated(st)
    result.files += 1


def total(paths: list[Path]) -> Usage:
    seen: set = set()
    result = Usage()
    for p in paths:
        result.add(usage(p, seen))
    return result


def newest_mtime(folder: Path, skip: set[str], depth: int = 2, limit: int = 3000) -> float:
    """Most recent modification time of files near the top of a project folder.

    Used to tell an active project from one nobody has opened in months. Only the
    first couple of levels are checked, and generated folders are skipped, so a
    fresh `npm install` does not make an old project look active.
    """
    newest = 0.0
    seen = 0
    stack = [(folder, 0)]
    while stack and seen < limit:
        current, level = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if entry.name in skip or entry.name == ".git":
                continue
            try:
                est = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(est.st_mode):
                if level + 1 < depth and not entry.name.startswith("."):
                    stack.append((Path(entry.path), level + 1))
            else:
                newest = max(newest, est.st_mtime)
    return newest
