"""Find generated folders inside your projects: node_modules, virtual
environments, build output and CocoaPods.

A folder only counts when the project around it proves it is generated (for
example node_modules next to a package.json). Folders with common names like
`build` or `dist` must also be ignored by git, or sit in a project type that
always generates them, so hand-written folders that happen to share the name
are left alone.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .model import CHECK, PROJECTS, SAFE, TRASH, Detail, Item
from .sizes import newest_mtime, usage
from .util import plural, run, which

DAY = 86400


@dataclass(frozen=True)
class Kind:
    key: str
    label: str  # plural noun, e.g. "node_modules folders"
    what: str
    restore: str


NODE = Kind(
    "node-modules",
    "node_modules folders",
    "Packages installed for each JavaScript project.",
    "Restored with `npm install` (or yarn / pnpm install) if you return to the project.",
)
VENV = Kind(
    "python-venvs",
    "Python virtual environments",
    "Python packages installed for each project.",
    "Recreate it with `python -m venv .venv` and reinstall the project's requirements.",
)
BUILD = Kind(
    "build-output",
    "build output folders",
    "Compiled output and build caches (build, dist, target, .next, .gradle and similar).",
    "Recreated the next time you build the project.",
)
PODS = Kind(
    "cocoapods-pods",
    "CocoaPods Pods folders",
    "iOS libraries installed for each project.",
    "Restored with `pod install`.",
)

# folder name -> (kind, project files that prove it is generated, needs git-ignored check)
ARTIFACTS: dict[str, tuple[Kind, tuple[str, ...], bool]] = {
    "node_modules": (NODE, ("package.json",), False),
    "Pods": (PODS, ("Podfile",), False),
    ".next": (BUILD, ("package.json",), False),
    ".nuxt": (BUILD, ("package.json",), False),
    ".svelte-kit": (BUILD, ("package.json",), False),
    ".angular": (BUILD, ("angular.json",), False),
    ".turbo": (BUILD, ("package.json",), False),
    ".parcel-cache": (BUILD, ("package.json",), False),
    ".dart_tool": (BUILD, ("pubspec.yaml",), False),
    ".gradle": (BUILD, ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"), False),
    "target": (BUILD, ("Cargo.toml", "pom.xml"), True),
    "build": (BUILD, ("build.gradle", "build.gradle.kts", "pubspec.yaml", "CMakeLists.txt", "package.json", "setup.py", "pyproject.toml"), True),
    "dist": (BUILD, ("package.json", "setup.py", "pyproject.toml"), True),
}
# Project types where these folders are always generated, so no git check is needed.
ALWAYS_GENERATED = {
    "target": ("Cargo.toml",),
    "build": ("build.gradle", "build.gradle.kts", "pubspec.yaml"),
}

VENV_NAMES = {".venv", "venv", "env", ".env", "virtualenv"}

# Folders in your home that never hold projects, or are too big to walk for nothing.
SKIP_IN_HOME = {
    "Library", "Applications", "Pictures", "Music", "Movies", "AppData",
    "Android", "go", "snap", "OneDrive", "Dropbox", "Google Drive", "iCloud Drive",
}
SKIP_ANYWHERE = {".git", "__pycache__", ".Trash", "$RECYCLE.BIN"}
MAX_DEPTH = 9


@dataclass
class Found:
    path: Path
    project: Path
    kind: Kind
    size: int = 0
    last_used: float = 0.0


def _git_ignored(project: Path, folder: Path) -> bool | None:
    """True/False when git can tell, None when the project isn't in a git repo."""
    if not which("git"):
        return None
    code, _, _ = run(["git", "-C", str(project), "check-ignore", "-q", folder.name], timeout=10)
    if code == 0:
        return True
    if code == 1:
        return False
    return None  # 128: not a git repository


def _is_artifact(project: Path, name: str, entries: set[str]) -> Kind | None:
    spec = ARTIFACTS.get(name)
    if not spec:
        return None
    kind, markers, needs_git = spec
    if not any(m in entries for m in markers):
        return None
    if needs_git:
        if any(m in entries for m in ALWAYS_GENERATED.get(name, ())):
            return kind
        ignored = _git_ignored(project, project / name)
        if ignored is None:
            # No git to ask: only trust package.json projects for dist/, never build/.
            return kind if name == "dist" and "package.json" in entries else None
        return kind if ignored else None
    return kind


def find(roots: list[Path], progress: Callable[[str], None] | None = None) -> list[Found]:
    say = progress or (lambda _m: None)
    home = Path.home()
    found: list[Found] = []
    stack = [(r, 0) for r in roots]
    walked = 0
    while stack:
        folder, depth = stack.pop()
        walked += 1
        if walked % 500 == 0:
            say(f"Looking through your projects ({walked:,} folders)")
        try:
            with os.scandir(folder) as it:
                entries = [e for e in it]
        except OSError:
            continue
        names = {e.name for e in entries}
        for e in entries:
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            path = Path(e.path)
            kind = _is_artifact(folder, e.name, names)
            if kind is None and (e.name in VENV_NAMES or not e.name.startswith(".")):
                if os.path.isfile(os.path.join(e.path, "pyvenv.cfg")):
                    kind = VENV
            if kind is not None:
                found.append(Found(path=path, project=folder, kind=kind))
                continue
            if e.name.startswith(".") or e.name in SKIP_ANYWHERE or e.name in ARTIFACTS:
                continue
            if folder == home and e.name in SKIP_IN_HOME:
                continue
            if depth + 1 < MAX_DEPTH:
                stack.append((path, depth + 1))
    return found


def scan(
    roots: list[Path],
    stale_days: int = 180,
    progress: Callable[[str], None] | None = None,
    workers: int = 8,
    now: float | None = None,
) -> list[Item]:
    say = progress or (lambda _m: None)
    say("Looking through your projects")
    found = find(roots, progress)
    if not found:
        return []
    say(f"Measuring {plural(len(found), 'project folder')}")
    skip = set(ARTIFACTS) | VENV_NAMES
    last_used: dict[Path, float] = {}

    def measure(f: Found) -> Found:
        f.size = usage(f.path).bytes
        if f.project not in last_used:
            last_used[f.project] = newest_mtime(f.project, skip)
        f.last_used = last_used[f.project]
        return f

    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = list(pool.map(measure, found))

    now = now or time.time()
    cutoff = now - stale_days * DAY
    months = max(1, round(stale_days / 30))
    items: list[Item] = []
    for kind in (NODE, VENV, BUILD, PODS):
        for stale in (True, False):
            group = [f for f in found if f.kind is kind and (f.last_used < cutoff) == stale and f.size]
            if not group:
                continue
            group.sort(key=lambda f: -f.size)
            where = f"in projects untouched for {months}+ months" if stale else "in projects you worked on recently"
            items.append(
                Item(
                    id=f"projects-{kind.key}-{'old' if stale else 'recent'}",
                    name=f"{len(group)} {kind.label if len(group) != 1 else kind.label[:-1]} {where}",
                    category=PROJECTS,
                    safety=SAFE if stale else CHECK,
                    what=kind.what,
                    creator="Your projects",
                    comes_back=kind.restore,
                    size=sum(f.size for f in group),
                    action=TRASH,
                    paths=[str(f.path) for f in group],
                    details=[
                        Detail(
                            label=f"{f.path} (last changed {time.strftime('%b %Y', time.localtime(f.last_used))})"
                            if f.last_used
                            else str(f.path),
                            size=f.size,
                            path=str(f.path),
                        )
                        for f in group
                    ],
                    hint="" if stale else "You used these projects recently; you'll need to reinstall before working on them.",
                )
            )
    return items
