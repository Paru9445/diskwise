"""Terminal output."""

from __future__ import annotations

import os
import sys
import textwrap
import threading
import time

from .model import CHECK, KEEP, MANUAL, SAFE, SAFETY_DOTS, SAFETY_LABELS, Item, ScanResult
from .util import human, plural

INDENT = " " * 29


def _color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Style:
    def __init__(self, stream=sys.stdout):
        on = _color_enabled(stream)
        self.bold = "\033[1m" if on else ""
        self.dim = "\033[2m" if on else ""
        self.green = "\033[32m" if on else ""
        self.yellow = "\033[33m" if on else ""
        self.red = "\033[31m" if on else ""
        self.reset = "\033[0m" if on else ""

    def safety(self, safety: str) -> str:
        color = {SAFE: self.green, CHECK: self.yellow, KEEP: self.red}[safety]
        return f"{SAFETY_DOTS[safety]} {color}{SAFETY_LABELS[safety]:<13}{self.reset}"


def wrap(text: str, indent: str = INDENT, width: int = 100) -> str:
    return textwrap.fill(text, width=width, initial_indent=indent, subsequent_indent=indent)


def item_lines(item: Item, s: Style, number: int | None = None, details: bool = False) -> list[str]:
    num = f"{number:>3}. " if number is not None else "  "
    lines = [f"{num}{s.bold}{human(item.size):>8}{s.reset}   {s.safety(item.safety)}{item.name}"]
    pad = INDENT + ("   " if number is not None else "")
    lines.append(s.dim + wrap(item.what, pad) + s.reset)
    if details:
        lines.append(wrap(f"Made by: {item.creator}. Comes back: {item.comes_back}", pad))
        if item.hint:
            lines.append(wrap(f"Tip: {item.hint}", pad))
        if item.action == MANUAL:
            lines.append(wrap("Diskwise doesn't remove this itself; follow the tip above.", pad))
        lines.append(f"{pad}{s.dim}id: {item.id}{s.reset}")
        for d in item.details[:12]:
            lines.append(f"{pad}  {human(d.size):>9}  {d.label}")
        if len(item.details) > 12:
            lines.append(f"{pad}  … and {len(item.details) - 12} more")
        if item.denied:
            lines.append(wrap(f"({plural(item.denied, 'folder')} inside could not be read and are not counted.)", pad))
    elif item.action == MANUAL and item.hint and item.safety != KEEP:
        lines.append(wrap(f"Do it yourself: {item.hint}", pad))
    return lines


def print_scan(result: ScanResult, details: bool = False, min_size: int = 0, numbered: bool = False,
               out=sys.stdout) -> list[Item]:
    """Print the report. Returns the items shown, in order (numbering for `clean`)."""
    s = Style(out)
    items = result.sorted()
    shown = [i for i in items if i.size >= min_size]
    hidden = len(items) - len(shown)
    if not items and result.notices:
        # Nothing was scanned (no phone, no adb...): the notices say why.
        print(file=out)
        for notice in result.notices:
            print(wrap(notice, "  "), file=out)
        print(file=out)
        return []
    if not shown:
        print("\n  Nothing big found. Your disk is in good shape.\n", file=out)
    else:
        head = "       " if numbered else ""
        print(f"\n  {head}{s.dim}SIZE       SAFETY         ITEM{s.reset}", file=out)
        for n, item in enumerate(shown, 1):
            for line in item_lines(item, s, n if numbered else None, details):
                print(line, file=out)
    print(file=out)
    safe = sum(i.size for i in items if i.safety == SAFE)
    check = [i for i in items if i.safety == CHECK]
    print(f"  {s.bold}Total you could free safely: {human(safe)}{s.reset}", file=out)
    if check:
        print(f"  Worth a look: {human(sum(i.size for i in check))} in {plural(len(check), 'item')} marked 🟡 Check first", file=out)
    if hidden:
        print(f"  {s.dim}{plural(hidden, 'smaller item')} not shown (use --all to see everything){s.reset}", file=out)
    for notice in result.notices:
        print(wrap(f"Note: {notice}", "  "), file=out)
    print(file=out)
    return shown


class Spinner:
    """A one-line progress message on stderr, only when stderr is a terminal."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, stream=sys.stderr):
        self.stream = stream
        self.enabled = hasattr(stream, "isatty") and stream.isatty()
        self.message = "Scanning"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def update(self, message: str) -> None:
        self.message = message

    def __enter__(self) -> "Spinner":
        if self.enabled:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        return self

    def _spin(self) -> None:
        i = 0
        while not self._stop.wait(0.1):
            self.stream.write(f"\r\033[K{self.FRAMES[i % len(self.FRAMES)]} {self.message}…")
            self.stream.flush()
            i += 1

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
            self.stream.write("\r\033[K")
            self.stream.flush()


def elapsed(start: float) -> str:
    return f"{time.time() - start:.0f}s"
