# Diskwise

**Find out what's eating your disk, why it's there, and whether it's safe to delete.**

Most disk cleaners show you a big number and a "Clean" button. Diskwise shows you *what* each space hog is, *which app made it*, and *what happens if you delete it*, so you can free up space without breaking anything.

Works on **macOS, Windows and Linux**, and can scan an **Android phone** over USB with `adb`.

[![Tests](https://github.com/Paru9445/diskwise/actions/workflows/ci.yml/badge.svg)](https://github.com/Paru9445/diskwise/actions/workflows/ci.yml)

---

## Why Diskwise?

Your disk fills up with things you never saved yourself: build caches, old simulators, Docker images, `node_modules` folders from projects you forgot, phone backups, package-manager caches. They hide in folders most people never open, and they can add up to tens of gigabytes.

Diskwise was built after a real cleanup on a MacBook Air where most of the lost space turned out to be developer tool leftovers, not personal files.

## What it does

- **Finds hidden space hogs**: scans the places where apps and tools quietly pile up data, not just your Downloads folder.
- **Shows real sizes**: the space files actually take on disk, sorted from largest to smallest, so you fix the biggest problem first.
- **Explains every item in plain English**: what it is, which app created it, and whether it comes back on its own.
- **Gives a safety rating** for each item:
  - 🟢 **Safe**: a cache or rebuildable file. Deleting it only costs a re-download or rebuild.
  - 🟡 **Check first**: might hold something you want, like old backups or large downloads.
  - 🔴 **Keep**: needed by your system or apps. Diskwise shows it but never offers to delete it.
- **Cleans what you choose**: nothing is deleted without your confirmation, and you can undo.
- **Looks inside any folder**: pick a folder, or the whole disk, and see what's in it, biggest first, with what Diskwise recognises marked.
- **Runs as an app or in the terminal**: a desktop app for macOS, Windows and Linux, or the `diskwise` command.

## Built to be safe

- **Scanning only looks.** `diskwise scan` never changes anything. You choose what to clean.
- **Moves to Trash / Recycle Bin** instead of deleting permanently, and `diskwise undo` puts it all back.
- **Never touches system files** or anything outside the known locations it scans. It refuses anything outside your home folder (except old macOS installers in Applications), your home folder itself, and folders directly in it (like Documents or Desktop).
- **Proves a folder is generated before calling it a leftover.** A `node_modules` only counts next to a `package.json`; a `build` or `dist` folder must also be ignored by git.
- **Asks before it looks.** On macOS it asks for Full Disk Access and your Desktop, Documents and Downloads folders up front, with the reason for each, instead of surprising you mid-scan.
- **Administrator rights only to measure.** Folders outside your account are measured only when you ask, after the system's own password prompt, and only by a helper that reads sizes. Diskwise never cleans with administrator rights.
- **Never deletes from your phone.** On Android it only clears app caches, using Android's own cleanup.
- **Works offline.** Diskwise never sends anything anywhere. The visual view runs on your computer only.
- **No dependencies.** The `diskwise` command is plain Python, open source, so you can read exactly what it does before you run it. Only the desktop app adds one, [pywebview](https://pywebview.flowrl.com), for its window.

## Install

**The app:** download it for your system from [Releases](https://github.com/Paru9445/diskwise/releases) (see [Desktop app](#desktop-app)).

**The command:** you need Python 3.9 or newer (already on macOS and most Linux; on Windows get it from [python.org](https://www.python.org/downloads/)).

```bash
pipx install git+https://github.com/Paru9445/diskwise
```

No pipx? `pip install --user git+https://github.com/Paru9445/diskwise` works too. Or run it from a checkout without installing:

```bash
git clone https://github.com/Paru9445/diskwise && cd diskwise
python3 -m pip install -e .
```

## Quick start

```bash
# Scan and report only (nothing is deleted)
diskwise scan

# See what's inside each item, which app made it, and its id
diskwise scan --details

# Review items and clean the ones you pick
diskwise clean

# Changed your mind? Put back everything the last clean moved
diskwise undo

# What's inside a folder, biggest first (deletes nothing)
diskwise measure ~/Projects

# Open the visual view in your browser
diskwise ui

# Scan a connected Android phone
diskwise scan --android
```

## Example output

From a real scan of a developer's MacBook:

```
  SIZE       SAFETY         ITEM
    8.1 GB   🟡 Check first  Simulator runtimes
                             Whole copies of iOS, watchOS and other systems that simulators run on,
                             several GB each.
                             Do it yourself: Remove old versions in Xcode > Settings > Components.
    5.7 GB   🟡 Check first  15 node_modules folders in projects you worked on recently
                             Packages installed for each JavaScript project.
    3.1 GB   🟢 Safe         Gradle caches
                             Libraries and build caches Gradle downloads for Android and Java
                             projects.
    2.2 GB   🟢 Safe         Chrome cache
                             Web pages and images Chrome saved to load sites faster. Your bookmarks,
                             passwords and history are not touched.
    1.6 GB   🟢 Safe         Xcode DerivedData
                             Build files Xcode recreates automatically on the next build.

  Total you could free safely: 10.7 GB
  Worth a look: 32.1 GB in 9 items marked 🟡 Check first

  Nothing was deleted. Run `diskwise clean` to choose what to remove.
```

## Cleaning

`diskwise clean` shows the cleanable items with numbers. Type the ones you want (`1 3 5-7`), or `safe` for every 🟢 item. Each 🟡 item asks again on its own, and nothing happens until you confirm the final summary.

- Files go to the **Trash** (macOS, in a folder named `Diskwise <date>`), the **Trash** (Linux, so your file manager can restore them too) or the **Recycle Bin** (Windows). Empty it afterwards to get the space back.
- A few things are cleaned by their own tool instead, because that's the right way to remove them: Docker (`docker image prune`, `docker builder prune`…), old iOS simulators (`xcrun simctl delete unavailable`) and Android app caches (`pm trim-caches`). Diskwise shows the exact command before running it. These can't be undone, which is why only rebuildable things are cleaned this way.
- Some items are **do it yourself**: Diskwise explains the steps (for example removing a simulator runtime in Xcode) instead of guessing for you.

For scripts: `diskwise clean --only npm-cache gradle-caches --yes` cleans exactly those ids (find them with `scan --details`). `--dry-run` shows what would happen and stops.

## Visual view

`diskwise ui` opens the same view as the desktop app, in your browser. It only listens on `127.0.0.1`, and the page can only ask to clean items from its own scan, never arbitrary paths. It has three tabs:

- **Cleanup**: your disk, a breakdown by category, and every item with its explanation. Tick what you want and click **Clean selected**, with the same safety rules and an Undo button.
- **Folders**: choose any folder, or **Whole disk**, and see what's inside it, biggest first. Click a folder to go in, and **Show** opens it in Finder or Explorer. Folders Diskwise recognises are marked, like "6.8 GB inside is 🟢 safe to clean". This view only looks: to free space, use Cleanup.
- **Access**: what Diskwise may read, and buttons to allow more. If some folders couldn't be read, Folders offers **Measure as administrator**.

## Desktop app

Diskwise also comes as an app: a `.dmg` for macOS (Apple silicon), a `.zip` for Windows and a `.tar.gz` for Linux, on the [Releases](https://github.com/Paru9445/diskwise/releases) page. It's the visual view in its own window, with a menu bar (**Scan**, **Permissions**, **Help**) and a native folder picker.

**First launch.** Diskwise shows a welcome screen that asks for access, one step at a time:

1. **Full Disk Access** (macOS, recommended): click **Open System Settings**, turn on Diskwise, and choose **Quit & Reopen** if macOS asks. This lets Diskwise measure Mail, Messages, Safari, iPhone backups and the Trash.
2. **Desktop, Documents and Downloads** (macOS): click **Allow access…**, then **Allow** on each system prompt. Not needed if you turned on Full Disk Access.
3. **System folders and the whole disk**: nothing to do now. Diskwise asks for administrator rights with the system's own prompt (macOS password dialog, Windows UAC, Linux polkit) only when you measure such a folder.

You can change any of this later in the **Access** tab.

**Not code-signed yet.** On macOS, right-click Diskwise and choose **Open** the first time; on Windows, click **More info > Run anyway**. Until builds are signed, macOS may also forget Full Disk Access when you install a new version, so turn it on again after updating.

**Build it yourself:**

```bash
python3 -m pip install -e ".[desktop]" pyinstaller
python3 packaging/build.py
```

The download lands in `dist/release/`. Each system builds its own version; GitHub Actions builds all three when a version tag like `v0.2.0` is pushed and attaches them to a release.

## What it looks for

| Category | Examples |
|---|---|
| Developer tools | Xcode DerivedData, archives, device support files, simulators and simulator runtimes; Android Studio and Gradle caches; Android emulators, system images and NDKs; JetBrains and VS Code caches; Playwright browsers; downloaded AI models |
| Project leftovers | `node_modules`, Python virtual environments, CocoaPods `Pods`, and build output (`build`, `dist`, `target`, `.next`, `.gradle`, `.dart_tool`…), split into projects untouched for 6+ months and ones you use now |
| Package managers | npm, pnpm, Yarn, Bun, pip, uv, Homebrew, Composer, CocoaPods, Swift Package Manager, Cargo, Go, Maven, NuGet, Deno, Dart/Flutter |
| Containers | Unused Docker images, build cache, stopped containers and unused volumes |
| Apps and browsers | Chrome, Edge, Brave and Firefox caches; Slack, Discord, Teams and Spotify caches; app logs; Windows temp files; other app caches; the Trash; Linux system logs |
| Backups and media | Old iPhone/iPad backups (with device name and date), iOS update files, old macOS installers, old installers and large forgotten files in Downloads |
| Android (via adb) | App caches, photos and videos, downloads, other large files, and installed apps by size |

Run `diskwise rules` to see every location and its safety rating.

On macOS, iPhone backups and the Trash are protected by the system. To include them, allow your terminal app in **System Settings > Privacy & Security > Full Disk Access**. Diskwise tells you when that's the case.

## Android

1. On the phone: **Settings > About phone**, tap **Build number** 7 times, then turn on **Developer options > USB debugging**.
2. Install `adb` ([platform-tools](https://developer.android.com/tools/releases/platform-tools), or it comes with Android Studio; Diskwise finds it there too).
3. Connect with USB, tap **Allow** on the phone, and run `diskwise scan --android`.

`diskwise clean --android` can clear app caches. Photos, videos and downloads are shown with advice, but Diskwise never deletes them, because a phone has no Trash to undo from.

## Roadmap

- [x] macOS scanner
- [x] Windows scanner
- [x] Linux scanner
- [x] Android scan over adb
- [x] Interactive clean with undo
- [x] Visual view in your browser (`diskwise ui`)
- [x] Desktop app with folder view and proper permission prompts
- [ ] Code-signed and notarized builds
- [ ] Install with Homebrew, winget and PyPI

## Contributing

Found a space hog Diskwise doesn't know about? [Open an issue](https://github.com/Paru9445/diskwise/issues/new?template=space-hog.yml) with the folder path, the app that created it, and whether it's safe to delete. Pull requests are welcome: most new locations are a few lines in [`catalog.py`](src/diskwise/catalog.py). See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)

---

Built by [Praveen Saxena](https://praveensaxena.pages.dev)
