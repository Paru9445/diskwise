# Contributing to Diskwise

Thanks for helping. The most useful contribution is teaching Diskwise about a space hog it doesn't know yet.

## Adding a new location

Most locations are one `Rule` in [`src/diskwise/catalog.py`](src/diskwise/catalog.py):

```python
Rule(
    id="pnpm-store",                      # unique, kebab-case; used by `clean --only`
    name="pnpm store",                    # short name shown in the list
    category=PACKAGES,                    # one of the categories in model.py
    safety=SAFE,                          # SAFE, CHECK or KEEP
    what="pnpm's shared package store. Projects that use pnpm download packages again on the next install.",
    creator="pnpm",                       # which app or tool makes it
    comes_back="Yes, on your next `pnpm install`.",
    paths=("~/Library/pnpm/store", "~/.local/share/pnpm/store", "%LOCALAPPDATA%/pnpm/store"),
),
```

- `paths` can use `~`, `$VAR` (macOS/Linux), `%VAR%` (Windows) and glob wildcards like `AndroidStudio*`. Paths that don't exist are skipped, so one rule can list the location on every OS.
- `mode="contents"` (the default) empties the folder but keeps it. `mode="whole"` removes the path itself.
- `action=MANUAL` with a `hint` when the right way to clean is inside the app (for example `ollama rm`).
- `platforms` limits a rule to some systems; it defaults to all three.

### Choosing the safety rating

- 🟢 **SAFE**: deleting it only costs a re-download or rebuild, and no app breaks.
- 🟡 **CHECK**: it could hold something the person wants (backups, emulators with data, downloads, models that take hours to fetch).
- 🔴 **KEEP**: an app or the system needs it. Shown for context, never cleaned.

When in doubt, choose the more careful rating. Write `what` for someone who has never opened a terminal: what it is, and what deleting it costs.

Things that need more than a fixed path (reading a plist, calling a tool) go in [`finders.py`](src/diskwise/finders.py).

## Development

```bash
git clone https://github.com/Paru9445/diskwise && cd diskwise
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest
diskwise scan --details
```

Tests use a fake home folder and never touch your real files. CI runs them on macOS, Windows and Linux.

Before opening a pull request, please run `diskwise scan` on your own machine and check that the new item shows up with the right size and wording.

## Safety first

Changes to [`cleaner.py`](src/diskwise/cleaner.py) or [`trash.py`](src/diskwise/trash.py) need a test. Diskwise must never delete permanently, never act outside the paths it reported, and never clean a Keep item.
