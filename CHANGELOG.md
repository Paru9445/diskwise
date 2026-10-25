# Changelog

## Unreleased

- Desktop app for macOS, Windows and Linux: the visual view in its own window, with an app icon and a menu bar. Built by `packaging/build.py`; GitHub Actions builds all three on version tags.
- Folders: pick any folder (or the whole disk) and see what's inside, biggest first, with what Diskwise recognises marked. Looking never changes anything. Also `diskwise measure FOLDER`.
- Access: a first-run screen that asks for permissions properly. On macOS it checks Full Disk Access and opens the right System Settings page, and asks for Desktop, Documents and Downloads in one go instead of halfway through a scan.
- Administrator measuring: folders outside your account can be measured with the system's own password prompt (macOS), polkit (Linux) or UAC (Windows). Only a read-only helper runs elevated; cleaning still stays inside your home folder.

## 0.1.0 (2026-10-21)

First public release.

- `diskwise scan` for macOS, Windows and Linux: 46 known locations across developer tools, package managers, browsers and apps, plus simulators, iPhone backups, Downloads, the Trash and Docker.
- Project leftovers: `node_modules`, Python virtual environments, CocoaPods and build output, split into old and active projects.
- `diskwise scan --android`: app caches, photos and videos, downloads and large files over adb.
- `diskwise clean`: pick items, moves files to the Trash or Recycle Bin; `diskwise undo` puts them back; `diskwise history`.
- `diskwise ui`: visual view in your browser.
- `diskwise rules`: list every location Diskwise knows.
