"""Clean the items you picked, keep a history, and undo.

Safety rules enforced here, whatever the caller asks for:
- Keep items are never cleaned.
- Only paths inside your home folder (plus a short allow-list such as old macOS
  installers) can be moved, never your home folder itself or a folder directly
  inside it like Documents or Desktop.
- Files go to the Trash / Recycle Bin, never deleted permanently.
"""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .model import COMMAND, KEEP, TRASH, Item
from .sizes import usage
from .trash import Moved, Trash, TrashError
from .util import data_dir, home, is_within, run

ALLOWED_OUTSIDE_HOME = ("/Applications/Install macOS*.app",)
NEVER_TOUCH = {".ssh", ".gnupg", "Keychains", ".git"}


class Refused(Exception):
    pass


def check_target(path: str) -> Path:
    """Raise Refused unless `path` is somewhere Diskwise is allowed to clean."""
    p = Path(path)
    if not p.is_absolute():
        raise Refused("not an absolute path")
    # Resolve the folder it sits in, but not the item itself: trashing a symlink moves the link only.
    p = p.parent.resolve() / p.name
    h = home().resolve()
    if is_within(p, h):
        rel = p.relative_to(h)
        if len(rel.parts) < 2:
            raise Refused("it is your home folder or a folder directly in it")
        if NEVER_TOUCH & set(rel.parts):
            raise Refused("it is inside a protected folder")
        return p
    if any(fnmatch.fnmatch(str(p), pattern) for pattern in ALLOWED_OUTSIDE_HOME):
        return p
    raise Refused("it is outside your home folder")


@dataclass
class Outcome:
    item: Item
    freed: int = 0
    moved: int = 0
    errors: list[str] = field(default_factory=list)
    ran: str = ""


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "history.json"

    def load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("sessions", [])
        except (OSError, ValueError):
            return []

    def save(self, sessions: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sessions": sessions[-50:]}, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, session: dict) -> None:
        sessions = self.load()
        sessions.append(session)
        self.save(sessions)


def clean(items: list[Item], history: History | None = None, trash: Trash | None = None) -> list[Outcome]:
    history = history or History()
    trash = trash or Trash()
    session = {"id": trash.session, "time": datetime.now().isoformat(timespec="seconds"), "entries": []}
    outcomes = []
    for item in items:
        outcome = Outcome(item)
        outcomes.append(outcome)
        if item.safety == KEEP or not item.cleanable:
            outcome.errors.append("Diskwise never cleans this item")
            continue
        if item.action == COMMAND:
            _run_command(item, outcome)
            session["entries"].append(
                {"item": item.id, "name": item.name, "kind": "command", "command": item.command, "size": outcome.freed}
            )
            continue
        if item.action != TRASH:
            continue
        failed_size = 0
        for path in item.paths:
            try:
                target = check_target(path)
                moved = trash.move(target, group=item.id)
            except (Refused, TrashError, OSError) as exc:
                outcome.errors.append(f"{path}: {exc}")
                failed_size += usage(path).bytes
                continue
            outcome.moved += 1
            session["entries"].append(
                {"item": item.id, "name": item.name, "kind": "trash", "original": moved.original, "location": moved.location}
            )
        outcome.freed = max(0, item.size - failed_size) if outcome.moved else 0
    if session["entries"]:
        session["freed"] = sum(o.freed for o in outcomes)
        history.add(session)
    return outcomes


def _run_command(item: Item, outcome: Outcome) -> None:
    outcome.ran = " ".join(item.command)
    code, out, err = run(item.command, timeout=900)
    if code != 0 and item.id == "docker-volumes" and "-a" in item.command:
        # Docker before 23.0 has no --all for volume prune and only removes anonymous volumes.
        cmd = [c for c in item.command if c != "-a"]
        outcome.ran = " ".join(cmd)
        code, out, err = run(cmd, timeout=900)
    if code == 0:
        outcome.freed = item.size
    else:
        outcome.errors.append((err or out).strip()[:300] or f"exited with code {code}")


@dataclass
class UndoResult:
    restored: int = 0
    errors: list[str] = field(default_factory=list)
    skipped_commands: list[str] = field(default_factory=list)
    session: str = ""


def undo(session_id: str | None = None, history: History | None = None) -> UndoResult:
    history = history or History()
    sessions = history.load()
    candidates = [s for s in sessions if not s.get("undone")]
    if session_id:
        candidates = [s for s in candidates if s["id"] == session_id]
    result = UndoResult()
    if not candidates:
        return result
    session = candidates[-1]
    result.session = session["id"]
    for entry in session["entries"]:
        if entry["kind"] == "command":
            result.skipped_commands.append(entry["name"])
            continue
        if entry.get("restored"):
            continue
        try:
            Trash.restore(Moved(original=entry["original"], location=entry.get("location", "")))
            entry["restored"] = True
            result.restored += 1
        except (TrashError, OSError) as exc:
            result.errors.append(f"{entry['original']}: {exc}")
    session["undone"] = not result.errors
    history.save(sessions)
    return result
