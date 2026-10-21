"""The data Diskwise works with: rules (what to look for) and items (what it found)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SAFE = "safe"
CHECK = "check"
KEEP = "keep"

SAFETY_LABELS = {SAFE: "Safe", CHECK: "Check first", KEEP: "Keep"}
SAFETY_DOTS = {SAFE: "🟢", CHECK: "🟡", KEEP: "🔴"}
SAFETY_ORDER = {SAFE: 0, CHECK: 1, KEEP: 2}

# How an item is cleaned.
TRASH = "trash"  # move its paths to the Trash / Recycle Bin (undoable)
COMMAND = "command"  # run the owning tool's own cleanup command (docker, simctl, adb)
MANUAL = "manual"  # Diskwise explains how; you do it yourself
NONE = "none"  # never cleaned (Keep items)

DEV = "Developer tools"
PROJECTS = "Project leftovers"
PACKAGES = "Package managers"
CONTAINERS = "Containers"
APPS = "Apps and browsers"
BACKUPS = "Backups and media"
ANDROID = "Android phone"

CATEGORIES = [DEV, PROJECTS, PACKAGES, CONTAINERS, APPS, BACKUPS, ANDROID]


@dataclass(frozen=True)
class Rule:
    """A known place where an app or tool piles up data."""

    id: str
    name: str
    category: str
    safety: str
    what: str  # one plain-English sentence: what it is and what deleting it costs
    creator: str  # which app or tool makes it
    comes_back: str  # does it come back on its own?
    paths: tuple[str, ...]  # path templates: ~, $VAR / %VAR%, and globs are allowed
    platforms: tuple[str, ...] = ("macos", "linux", "windows")
    mode: str = "contents"  # "contents": empty the folder, keep it. "whole": remove the path itself.
    action: str = TRASH
    command: tuple[str, ...] = ()
    hint: str = ""  # extra advice shown before cleaning, or the manual steps

    def __post_init__(self) -> None:
        if self.safety == KEEP and self.action != NONE:
            object.__setattr__(self, "action", NONE)


@dataclass
class Detail:
    label: str
    size: int
    path: str = ""


@dataclass
class Item:
    id: str
    name: str
    category: str
    safety: str
    what: str
    creator: str
    comes_back: str
    size: int
    action: str = TRASH
    paths: list[str] = field(default_factory=list)  # what gets moved to the Trash
    command: list[str] = field(default_factory=list)
    hint: str = ""
    files: int = 0
    details: list[Detail] = field(default_factory=list)
    denied: int = 0  # folders Diskwise was not allowed to read
    source: str = "computer"  # or "android"

    @property
    def cleanable(self) -> bool:
        return self.safety != KEEP and self.action in (TRASH, COMMAND)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["cleanable"] = self.cleanable
        data["safety_label"] = SAFETY_LABELS[self.safety]
        return data

    @classmethod
    def from_rule(cls, rule: Rule, size: int, **kwargs) -> "Item":
        base = dict(
            id=rule.id,
            name=rule.name,
            category=rule.category,
            safety=rule.safety,
            what=rule.what,
            creator=rule.creator,
            comes_back=rule.comes_back,
            size=size,
            action=rule.action,
            command=list(rule.command),
            hint=rule.hint,
        )
        base.update(kwargs)
        return cls(**base)


@dataclass
class ScanResult:
    items: list[Item] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    def sorted(self) -> list[Item]:
        return sorted(self.items, key=lambda i: -i.size)

    def total(self, safety: str) -> int:
        return sum(i.size for i in self.items if i.safety == safety)

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.sorted()],
            "notices": self.notices,
            "totals": {s: self.total(s) for s in (SAFE, CHECK, KEEP)},
        }
