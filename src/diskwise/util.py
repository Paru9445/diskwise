"""Small helpers shared by the scanner, the cleaner and the CLI."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MACOS = sys.platform == "darwin"
WINDOWS = os.name == "nt"
LINUX = sys.platform.startswith("linux")


def platform_name() -> str:
    if MACOS:
        return "macos"
    if WINDOWS:
        return "windows"
    return "linux"


def home() -> Path:
    return Path.home()


def human(n: float) -> str:
    """Format a byte count the way Finder and Explorer users expect (1 GB = 1000 MB)."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


_SIZE_RE = re.compile(r"^\s*([\d.]+)\s*([kKmMgGtT]?)(i?)[bB]?\s*$")


def parse_size(text: str) -> int:
    """Parse '1.2GB', '512.5kB', '300M', '0B' into bytes. Raises ValueError."""
    m = _SIZE_RE.match(text)
    if not m:
        raise ValueError(f"not a size: {text!r}")
    value, unit, binary = m.groups()
    base = 1024 if binary else 1000
    power = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}[unit.lower()]
    return int(float(value) * base**power)


def expand(template: str) -> str:
    """Expand ~ and environment variables ($VAR, %VAR%) in a path template."""
    return os.path.expandvars(os.path.expanduser(template))


def which(name: str, extra_dirs: list[str] | None = None) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for d in extra_dirs or []:
        candidate = Path(expand(d)) / (name + (".exe" if WINDOWS else ""))
        if candidate.is_file():
            return str(candidate)
    return None


def run(cmd: list[str], timeout: float = 60) -> tuple[int, str, str]:
    """Run a command, never raising for a missing binary or a timeout."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} timed out after {timeout:.0f}s"
    except OSError as exc:
        return 126, "", str(exc)


def data_dir() -> Path:
    """Where Diskwise keeps its clean history (used by `diskwise undo`)."""
    override = os.environ.get("DISKWISE_DATA_DIR")
    if override:
        return Path(override)
    if MACOS:
        return home() / "Library" / "Application Support" / "Diskwise"
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", home() / "AppData" / "Local")) / "Diskwise"
    state = os.environ.get("XDG_STATE_HOME") or str(home() / ".local" / "state")
    return Path(state) / "diskwise"


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"
