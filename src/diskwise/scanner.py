"""Turn the catalog into measured items for this computer."""

from __future__ import annotations

import glob
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import catalog, docker, finders, projects
from .model import Detail, Item, Rule, ScanResult
from .sizes import usage
from .util import expand, platform_name

Progress = Callable[[str], None]


@dataclass
class ScanOptions:
    projects: bool = True
    project_roots: list[Path] = field(default_factory=list)  # empty: your home folder
    stale_days: int = 180
    docker: bool = True
    platform: str = field(default_factory=platform_name)
    progress: Progress | None = None
    workers: int = 8


def resolve(templates: tuple[str, ...]) -> list[Path]:
    """Expand path templates into the existing paths they match, without duplicates."""
    found: list[Path] = []
    for template in templates:
        path = expand(template)
        # Templates for another OS (like %LOCALAPPDATA% on a Mac) stay unexpanded: skip them.
        if "%" in path or "$" in path or not os.path.isabs(path):
            continue
        matches = glob.glob(path) if glob.has_magic(path) else [path]
        for m in sorted(matches):
            p = Path(m)
            if (p.exists() or p.is_symlink()) and p not in found:
                found.append(p)
    return found


def targets(rule: Rule, roots: list[Path]) -> list[Path]:
    """What cleaning this rule would move to the Trash."""
    if rule.mode == "whole":
        return roots
    out: list[Path] = []
    for root in roots:
        if root.is_dir() and not root.is_symlink():
            try:
                out.extend(sorted(root.iterdir()))
            except OSError:
                continue
        else:
            out.append(root)
    return out


def _short(p: Path) -> str:
    text, h = str(p), str(Path.home())
    return "~" + text[len(h):] if text.startswith(h) else text


def measure_rule(rule: Rule) -> tuple[Item | None, list[Path]]:
    roots = resolve(rule.paths)
    if not roots:
        return None, []
    # Measure each thing cleaning would move, so --details can show what's inside.
    seen: set = set()
    measured = [(p, usage(p, seen)) for p in targets(rule, roots)]
    item = Item.from_rule(
        rule,
        sum(u.bytes for _, u in measured),
        paths=[str(p) for p, _ in measured],
        files=sum(u.files for _, u in measured),
        denied=sum(len(u.denied) for _, u in measured),
    )
    multi = len(roots) > 1
    item.details = sorted(
        (
            Detail(label=_short(p) if multi else p.name, size=u.bytes, path=str(p))
            for p, u in measured
            if u.bytes
        ),
        key=lambda d: -d.size,
    )
    return item, roots


def scan(options: ScanOptions | None = None) -> ScanResult:
    options = options or ScanOptions()
    say = options.progress or (lambda _msg: None)
    result = ScanResult()
    claimed: list[Path] = []

    rules = catalog.rules_for(options.platform)
    say("Checking known app and tool folders")
    with ThreadPoolExecutor(max_workers=options.workers) as pool:
        for item, roots in pool.map(measure_rule, rules):
            claimed.extend(roots)
            if item and item.size > 0:
                result.items.append(item)

    for name, finder in finders.for_platform(options.platform):
        say(f"Checking {name}")
        try:
            result.items.extend(finder(result.notices))
        except Exception as exc:  # one broken finder should never stop a scan
            result.notices.append(f"Skipped {name}: {exc}")

    say("Checking other app caches")
    result.items.extend(finders.other_caches(options.platform, claimed))

    if options.docker:
        say("Checking Docker")
        result.items.extend(docker.scan(result.notices))

    if options.projects:
        roots = options.project_roots or [Path.home()]
        result.items.extend(
            projects.scan(roots, stale_days=options.stale_days, progress=say, workers=options.workers)
        )

    result.items = [i for i in result.items if i.size > 0]
    return result
