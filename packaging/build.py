"""Build the Diskwise desktop app for the system this runs on.

    python -m pip install -e ".[desktop]" pyinstaller
    python packaging/build.py

Writes the download to dist/release/:
    macOS   Diskwise-<version>-macos-<arch>.dmg
    Windows Diskwise-<version>-windows-x64.zip
    Linux   Diskwise-<version>-linux-x64.tar.gz
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RELEASE = DIST / "release"


def version() -> str:
    text = (ROOT / "src" / "diskwise" / "__init__.py").read_text()
    return re.search(r'__version__ = "(.+?)"', text).group(1)


def arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)


def pyinstaller() -> None:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build" / "pyinstaller"),
         str(ROOT / "packaging" / "diskwise.spec")],
        check=True,
    )


def package_macos(name: str) -> Path:
    app = DIST / "Diskwise.app"
    out = RELEASE / f"{name}-macos-{arch()}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "Diskwise"
        stage.mkdir()
        subprocess.run(["ditto", str(app), str(stage / "Diskwise.app")], check=True)
        (stage / "Applications").symlink_to("/Applications")
        out.unlink(missing_ok=True)
        subprocess.run(
            ["hdiutil", "create", "-volname", "Diskwise", "-srcfolder", str(stage),
             "-ov", "-format", "UDZO", str(out)],
            check=True,
        )
    return out


def package_windows(name: str) -> Path:
    base = RELEASE / f"{name}-windows-{arch()}"
    return Path(shutil.make_archive(str(base), "zip", DIST, "Diskwise"))


def package_linux(name: str) -> Path:
    out = RELEASE / f"{name}-linux-{arch()}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(DIST / "Diskwise", arcname="Diskwise")
    return out


def main() -> int:
    pyinstaller()
    RELEASE.mkdir(parents=True, exist_ok=True)
    name = f"Diskwise-{version()}"
    if sys.platform == "darwin":
        out = package_macos(name)
    elif sys.platform == "win32":
        out = package_windows(name)
    else:
        out = package_linux(name)
    print(f"\nBuilt {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
