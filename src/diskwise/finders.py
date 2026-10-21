"""Space hogs that need more than a fixed path to find: simulators, phone
backups, old downloads, the Trash, and caches no rule covers yet."""

from __future__ import annotations

import json
import os
import plistlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .model import (
    APPS,
    BACKUPS,
    CHECK,
    COMMAND,
    DEV,
    MANUAL,
    SAFE,
    TRASH,
    Detail,
    Item,
)
from .sizes import usage
from .util import MACOS, expand, home, parse_size, plural, run, which

Finder = Callable[[list], list]

DAY = 86400


# ------------------------------------------------------------ iOS simulators
def simulators(notices: list[str]) -> list[Item]:
    devices_dir = home() / "Library/Developer/CoreSimulator/Devices"
    if not devices_dir.is_dir():
        return []
    code, out, _ = run(["xcrun", "simctl", "list", "devices", "-j"], timeout=60)
    known: dict[str, dict] = {}
    if code == 0:
        try:
            for runtime, devices in json.loads(out).get("devices", {}).items():
                for d in devices:
                    d["runtime"] = runtime.rsplit(".", 1)[-1].replace("-", " ", 1).replace("-", ".")
                    known[d["udid"]] = d
        except (ValueError, KeyError):
            known = {}

    old, current = [], []
    for entry in sorted(devices_dir.iterdir()):
        if not entry.is_dir():
            continue
        info = known.get(entry.name, {})
        size = usage(entry).bytes
        label = f"{info.get('name', entry.name)} ({info.get('runtime', 'unknown iOS')})"
        detail = Detail(label=label, size=size, path=str(entry))
        if info and not info.get("isAvailable", True):
            old.append(detail)
        else:
            current.append(detail)

    items = []
    if old:
        items.append(
            Item(
                id="xcode-old-simulators",
                name=f"{plural(len(old), 'simulator')} for iOS versions you no longer have",
                category=DEV,
                safety=SAFE,
                what="Simulators whose iOS version is no longer installed, so Xcode can't run them anyway.",
                creator="Xcode",
                comes_back="No, and you won't need them.",
                size=sum(d.size for d in old),
                action=COMMAND,
                command=["xcrun", "simctl", "delete", "unavailable"],
                details=sorted(old, key=lambda d: -d.size),
            )
        )
    if current:
        items.append(
            Item(
                id="xcode-simulators",
                name="iOS simulators",
                category=DEV,
                safety=CHECK,
                what="Simulators you can run, including the apps and data installed in them.",
                creator="Xcode",
                comes_back="No. Xcode creates fresh ones when you add them.",
                size=sum(d.size for d in current),
                action=MANUAL,
                hint=(
                    "Delete the ones you don't use in Xcode > Window > Devices and Simulators. "
                    "`xcrun simctl erase all` resets every simulator to new (removes their apps and data)."
                ),
                details=sorted(current, key=lambda d: -d.size),
            )
        )
    return items


def simulator_runtimes(notices: list[str]) -> list[Item]:
    if not which("xcrun"):
        return []
    code, out, _ = run(["xcrun", "simctl", "runtime", "list", "-j"], timeout=60)
    if code != 0:
        return []
    try:
        runtimes = list(json.loads(out).values())
    except ValueError:
        return []
    details = []
    for r in runtimes:
        platform = r.get("platformIdentifier", "").replace("com.apple.platform.", "").replace("simulator", "")
        platform = {"iphone": "iOS", "watch": "watchOS", "appletv": "tvOS", "xr": "visionOS"}.get(platform, platform)
        used = (r.get("lastUsedAt") or "")[:10]
        label = f"{platform} {r.get('version', '?')}" + (f", last used {used}" if used else ", never used")
        details.append(Detail(label=label, size=int(r.get("sizeBytes") or 0), path=r.get("identifier", "")))
    if not details:
        return []
    return [
        Item(
            id="xcode-simulator-runtimes",
            name="Simulator runtimes",
            category=DEV,
            safety=CHECK,
            what="Whole copies of iOS, watchOS and other systems that simulators run on, several GB each.",
            creator="Xcode",
            comes_back="No. Download a runtime again in Xcode > Settings > Components.",
            size=sum(d.size for d in details),
            action=MANUAL,
            hint=(
                "Remove old versions in Xcode > Settings > Components, or with "
                "`xcrun simctl runtime delete <identifier>` (identifiers are listed with --details)."
            ),
            details=sorted(details, key=lambda d: -d.size),
        )
    ]


# ---------------------------------------------------------- iPhone backups
BACKUP_DIRS = (
    "~/Library/Application Support/MobileSync/Backup",
    "%APPDATA%/Apple Computer/MobileSync/Backup",
    "~/Apple/MobileSync/Backup",
)


def ios_backups(notices: list[str]) -> list[Item]:
    found = []
    for template in BACKUP_DIRS:
        root = Path(expand(template))
        if "%" in str(root) or not root.is_dir():
            continue
        try:
            entries = [e for e in root.iterdir() if e.is_dir()]
        except PermissionError:
            notices.append(
                "iPhone backups can't be read without Full Disk Access. To include them, allow your "
                "terminal in System Settings > Privacy & Security > Full Disk Access."
            )
            continue
        for entry in entries:
            info = {}
            try:
                with open(entry / "Info.plist", "rb") as fh:
                    info = plistlib.load(fh)
            except (OSError, plistlib.InvalidFileException, ValueError):
                pass
            when = info.get("Last Backup Date")
            if not isinstance(when, datetime):
                when = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            found.append((entry, info.get("Device Name") or "iPhone", info.get("Product Type", ""), when))

    newest: dict[str, datetime] = {}
    for _, device, _, when in found:
        newest[device] = max(newest.get(device, when), when)

    items = []
    for entry, device, _, when in found:
        latest = newest[device] == when
        hint = (
            f"This is your newest backup of {device}. Remove it only if the device backs up to iCloud."
            if latest
            else f"You have a newer backup of {device}, so this older one is usually safe to remove."
        )
        items.append(
            Item(
                id=f"ios-backup-{entry.name[:8].lower()}",
                name=f"{device} backup ({when.strftime('%B %Y')})",
                category=BACKUPS,
                safety=CHECK,
                what="A full backup of an iPhone or iPad made with Finder or iTunes.",
                creator="Finder / iTunes",
                comes_back="No.",
                size=usage(entry).bytes,
                action=TRASH,
                paths=[str(entry)],
                hint="Make sure you have a newer backup before removing this one. " + hint,
            )
        )
    return items


# --------------------------------------------------------------- Downloads
INSTALLER_EXT = {".dmg", ".pkg", ".exe", ".msi", ".iso", ".deb", ".rpm", ".appimage", ".apk", ".ipa", ".xip"}


def downloads(notices: list[str], now: float | None = None, folder: Path | None = None) -> list[Item]:
    folder = folder or home() / "Downloads"
    now = now or time.time()
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    installers, large = [], []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            age = (now - entry.lstat().st_mtime) / DAY
        except OSError:
            continue
        is_installer = entry.suffix.lower() in INSTALLER_EXT
        if is_installer and age >= 7:
            bucket = installers
        elif age >= 30:
            bucket = large
        else:
            continue
        size = usage(entry).bytes
        if bucket is large and size < 100_000_000:
            continue
        if bucket is installers and size < 1_000_000:
            continue
        bucket.append(Detail(label=f"{entry.name} ({int(age)} days old)", size=size, path=str(entry)))

    items = []
    if installers:
        items.append(
            Item(
                id="downloads-installers",
                name=f"{plural(len(installers), 'installer')} in Downloads",
                category=BACKUPS,
                safety=CHECK,
                what="App installers (.dmg, .pkg, .exe, .iso and similar) you downloaded more than a week ago. Usually already installed.",
                creator="You, through your browser",
                comes_back="No. Download them again if you need to reinstall.",
                size=sum(d.size for d in installers),
                paths=[d.path for d in installers],
                details=sorted(installers, key=lambda d: -d.size),
            )
        )
    if large:
        items.append(
            Item(
                id="downloads-large",
                name=f"{plural(len(large), 'large file')} in Downloads older than a month",
                category=BACKUPS,
                safety=CHECK,
                what="Big files and folders you downloaded more than 30 days ago.",
                creator="You, through your browser",
                comes_back="No.",
                size=sum(d.size for d in large),
                paths=[d.path for d in large],
                details=sorted(large, key=lambda d: -d.size),
                hint="Look through the list (use --details) and keep anything you still need.",
            )
        )
    return items


# --------------------------------------------------------------- the Trash
def trash(notices: list[str]) -> list[Item]:
    folder = home() / (".Trash" if MACOS else ".local/share/Trash/files")
    if not folder.is_dir():
        return []
    used = usage(folder)
    if used.bytes == 0:
        return []
    return [
        Item(
            id="trash",
            name="Trash",
            category=APPS,
            safety=CHECK,
            what="Files you already deleted. They still take up space until the Trash is emptied.",
            creator="You",
            comes_back="No.",
            size=used.bytes,
            action=MANUAL,
            hint="Look through it, then empty the Trash to free this space.",
        )
    ]


# ---------------------------------------------------------- Linux journald
def journal(notices: list[str]) -> list[Item]:
    if not which("journalctl"):
        return []
    code, out, _ = run(["journalctl", "--disk-usage"], timeout=30)
    m = re.search(r"take up ([\d.]+\s*[KMGT]?)", out)
    if code != 0 or not m:
        return []
    value = m.group(1).replace(" ", "")
    size = parse_size(value + "iB" if value[-1].isalpha() else value)  # journalctl uses 1024-based units
    return [
        Item(
            id="systemd-journal",
            name="System logs (journald)",
            category=APPS,
            safety=SAFE,
            what="System log history. Only recent logs are useful for fixing problems.",
            creator="systemd",
            comes_back="Yes, slowly, as the system logs new events.",
            size=size,
            action=MANUAL,
            hint="Keep the last two weeks with `sudo journalctl --vacuum-time=2weeks`.",
        )
    ]


# ------------------------------------------------- caches no rule covers yet
CACHE_ROOTS = {"macos": "~/Library/Caches", "linux": "~/.cache"}


def partition(root: Path, claimed: set[Path]) -> list[Path]:
    """Children of `root`, splitting open any child that contains a claimed path."""
    out: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return out
    for child in children:
        if child in claimed:
            continue
        if any(c != child and child in c.parents for c in claimed):
            if child.is_dir() and not child.is_symlink():
                out.extend(partition(child, claimed))
            continue
        out.append(child)
    return out


def other_caches(platform: str, claimed: list[Path]) -> list[Item]:
    template = CACHE_ROOTS.get(platform)
    if not template:
        return []
    root = Path(expand(template))
    if not root.is_dir():
        return []
    claimed_set = {p for p in claimed if root in p.parents}
    rest = [
        p
        for p in partition(root, claimed_set)
        # Apple's own caches belong to the system; leave them alone.
        if not p.name.startswith("com.apple.")
    ]
    details = []
    for p in rest:
        size = usage(p).bytes
        if size:
            details.append(Detail(label=p.name, size=size, path=str(p)))
    if not details:
        return []
    details.sort(key=lambda d: -d.size)
    return [
        Item(
            id="other-app-caches",
            name="Other app caches",
            category=APPS,
            safety=SAFE,
            what="Caches other apps keep to start and load faster. Apps rebuild them as needed.",
            creator="Your apps",
            comes_back="Yes, as you use the apps.",
            size=sum(d.size for d in details),
            paths=[d.path for d in details],
            details=details,
            hint="Quit open apps first. Use --details to see which apps these belong to.",
        )
    ]


def for_platform(platform: str) -> list[tuple[str, Finder]]:
    finders: list[tuple[str, Finder]] = [("Downloads", downloads)]
    if platform == "macos":
        finders += [
            ("iOS simulators", simulators),
            ("simulator runtimes", simulator_runtimes),
            ("iPhone backups", ios_backups),
            ("Trash", trash),
        ]
    elif platform == "windows":
        finders += [("iPhone backups", ios_backups)]
    else:
        finders += [("Trash", trash), ("system logs", journal)]
    return finders
