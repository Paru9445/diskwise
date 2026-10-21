"""Scan an Android phone over USB with adb.

Diskwise reads the phone's own storage stats (`dumpsys diskstats`) and looks
for large files in shared storage. The only thing it can clean is app caches,
using Android's own `pm trim-caches`. Photos, videos and downloads are shown
with advice, never deleted, because there is no Trash to undo from on a phone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .model import ANDROID, CHECK, COMMAND, KEEP, MANUAL, NONE, SAFE, Detail, Item, ScanResult
from .util import human, run, which

ADB_DIRS = [
    "$ANDROID_HOME/platform-tools",
    "$ANDROID_SDK_ROOT/platform-tools",
    "%ANDROID_HOME%/platform-tools",
    "~/Library/Android/sdk/platform-tools",
    "~/Android/Sdk/platform-tools",
    "%LOCALAPPDATA%/Android/Sdk/platform-tools",
]

LARGE_FILE_BLOCKS = 204800  # 100 MB in 512-byte blocks, the unit `find -size` uses
MEDIA_DIRS = ("/DCIM/", "/Movies/", "/Pictures/", "/WhatsApp/", "/Telegram/", "/Android/media/", "/Recordings/")


@dataclass
class Device:
    serial: str
    state: str
    model: str = ""


def find_adb() -> str | None:
    return which("adb", ADB_DIRS)


def parse_devices(output: str) -> list[Device]:
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or line.startswith("*"):
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        devices.append(Device(serial=parts[0], state=parts[1], model=model.replace("_", " ")))
    return devices


def parse_diskstats(output: str) -> dict:
    """Pull the numbers we need out of `dumpsys diskstats`."""
    stats: dict = {}
    m = re.search(r"Data-Free:\s*(\d+)K\s*/\s*(\d+)K", output)
    if m:
        stats["free"], stats["total"] = int(m.group(1)) * 1024, int(m.group(2)) * 1024
    for key in ("App Size", "App Data Size", "App Cache Size", "Photos Size", "Videos Size",
                "Audio Size", "Downloads Size", "System Size", "Other Size"):
        m = re.search(rf"^{key}:\s*(\d+)\s*$", output, re.M)
        if m:
            stats[key] = int(m.group(1))
    for key in ("Package Names", "App Sizes", "App Data Sizes", "Cache Sizes"):
        m = re.search(rf"^{key}:\s*(\[.*\])\s*$", output, re.M)
        if m:
            try:
                stats[key] = json.loads(m.group(1))
            except ValueError:
                pass
    return stats


def parse_large_files(output: str) -> list[tuple[int, str]]:
    files = []
    for line in output.splitlines():
        size, _, path = line.partition("|")
        if size.strip().isdigit() and path:
            files.append((int(size), path.strip()))
    return sorted(files, reverse=True)


def _per_app(stats: dict, *keys: str) -> list[tuple[str, int]]:
    names = stats.get("Package Names") or []
    columns = [stats.get(k) or [] for k in keys]
    if not names or any(len(c) != len(names) for c in columns):
        return []
    return sorted(((n, sum(int(c[i]) for c in columns)) for i, n in enumerate(names)), key=lambda x: -x[1])


def build_items(serial: str, stats: dict, large: list[tuple[int, str]], adb: str = "adb") -> list[Item]:
    items: list[Item] = []

    def details(pairs, limit=15):
        return [Detail(label=name, size=size, path=name) for name, size in pairs[:limit] if size]

    cache = stats.get("App Cache Size", 0)
    if cache:
        items.append(Item(
            id="android-app-caches",
            name="App caches on your phone",
            category=ANDROID, safety=SAFE,
            what="Files apps keep to load faster. Your app data, logins and photos are not touched.",
            creator="Your Android apps",
            comes_back="Yes, as you use the apps.",
            size=cache, action=COMMAND,
            command=[adb, "-s", serial, "shell", "pm", "trim-caches", "999G"],
            hint="Uses Android's own cache cleanup (`pm trim-caches`).",
            details=details(_per_app(stats, "Cache Sizes")),
            source="android",
        ))

    media = [(p, s) for s, p in large if any(d in p for d in MEDIA_DIRS)]
    downloads = [(p, s) for s, p in large if "/Download/" in p]
    other = [(p, s) for s, p in large if (p, s) not in media and (p, s) not in downloads and "/Android/data/" not in p]

    media_size = stats.get("Photos Size", 0) + stats.get("Videos Size", 0)
    if media_size or media:
        items.append(Item(
            id="android-media",
            name="Photos and videos on your phone",
            category=ANDROID, safety=CHECK,
            what="Your camera roll and saved videos. The list shows the largest files.",
            creator="Camera and messaging apps",
            comes_back="No.",
            size=media_size or sum(s for _, s in media), action=MANUAL,
            hint="Back them up first (Google Photos, or `adb pull` to this computer), then delete them on the phone. "
                 "Google Photos' 'Free up space' removes copies that are already backed up.",
            details=details(media),
            source="android",
        ))

    dl_size = stats.get("Downloads Size", 0) or sum(s for _, s in downloads)
    if dl_size:
        items.append(Item(
            id="android-downloads",
            name="Downloads on your phone",
            category=ANDROID, safety=CHECK,
            what="Files saved to the phone's Download folder, often installers and attachments you opened once.",
            creator="Your browser and apps",
            comes_back="No.",
            size=dl_size, action=MANUAL,
            hint="Open the Files app > Downloads, sort by size, and remove what you don't need.",
            details=details(downloads),
            source="android",
        ))

    if other:
        items.append(Item(
            id="android-large-files",
            name="Other large files on your phone",
            category=ANDROID, safety=CHECK,
            what="Files over 100 MB outside your photos and downloads.",
            creator="Various apps",
            comes_back="No.",
            size=sum(s for _, s in other), action=MANUAL,
            hint="Check each one in the Files app before removing it.",
            details=details(other),
            source="android",
        ))

    apps = stats.get("App Size", 0) + stats.get("App Data Size", 0)
    if apps:
        items.append(Item(
            id="android-apps",
            name="Installed apps and their data",
            category=ANDROID, safety=KEEP,
            what="The apps themselves and what they store (logins, offline content, chats).",
            creator="Your Android apps",
            comes_back="No.",
            size=apps, action=NONE,
            hint="Uninstall apps you don't use in Settings > Apps.",
            details=details(_per_app(stats, "App Sizes", "App Data Sizes")),
            source="android",
        ))
    return items


def scan(serial: str | None = None) -> ScanResult:
    result = ScanResult()
    adb = find_adb()
    if not adb:
        result.notices.append(
            "adb was not found. Install Android platform-tools (https://developer.android.com/tools/releases/platform-tools) "
            "or Android Studio, then try again."
        )
        return result

    code, out, err = run([adb, "devices", "-l"], timeout=30)
    devices = parse_devices(out) if code == 0 else []
    if serial:
        devices = [d for d in devices if d.serial == serial]
    ready = [d for d in devices if d.state == "device"]
    if not ready:
        if any(d.state == "unauthorized" for d in devices):
            result.notices.append("Your phone is asking to allow USB debugging. Unlock it, tap Allow, and scan again.")
        else:
            result.notices.append(
                "No Android phone found. Connect it with USB, turn on USB debugging "
                "(Settings > About phone > tap Build number 7 times, then Developer options > USB debugging), and scan again."
            )
        return result
    device = ready[0]
    if len(ready) > 1:
        others = ", ".join(d.serial for d in ready[1:])
        result.notices.append(f"Several phones are connected. Scanning {device.serial}; use --device to pick another ({others}).")

    shell = [adb, "-s", device.serial, "shell"]
    _, stats_out, _ = run(shell + ["dumpsys", "diskstats"], timeout=60)
    stats = parse_diskstats(stats_out)
    _, files_out, _ = run(
        shell + [f"find /sdcard/ -type f -size +{LARGE_FILE_BLOCKS} -exec stat -c '%s|%n' {{}} + 2>/dev/null"],
        timeout=180,
    )
    large = parse_large_files(files_out)

    name = device.model or device.serial
    if "free" in stats:
        result.notices.append(f"{name}: {human(stats['free'])} free of {human(stats['total'])}.")
    result.notices.append("Android refreshes its app storage numbers about once a day, so they can lag a little.")
    result.items = build_items(device.serial, stats, large, adb)
    return result
