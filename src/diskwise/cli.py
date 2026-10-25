"""The `diskwise` command."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, android, catalog
from .cleaner import History, clean, undo
from .model import CHECK, COMMAND, SAFE, SAFETY_DOTS, SAFETY_LABELS, TRASH, Item, ScanResult
from .report import Spinner, Style, elapsed, print_scan
from .scanner import ScanOptions, scan
from .util import human, parse_size, platform_name, plural


def _scan(args) -> ScanResult:
    start = time.time()
    with Spinner() as spinner:
        if args.android:
            spinner.update("Reading your phone's storage")
            result = android.scan(args.device)
        else:
            options = ScanOptions(
                projects=not args.no_projects,
                project_roots=[Path(p).expanduser().resolve() for p in args.projects or []],
                stale_days=args.stale_days,
                docker=not args.no_docker,
                progress=spinner.update,
            )
            result = scan(options)
    if not args.json:
        where = "your phone" if args.android else "this computer"
        print(f"\n  Diskwise scanned {where} in {elapsed(start)}.", file=sys.stderr)
    return result


def cmd_scan(args) -> int:
    result = _scan(args)
    if args.json:
        json.dump(result.to_dict(), sys.stdout, indent=2)
        print()
        return 0
    print_scan(result, details=args.details, min_size=0 if args.all else args.min_size)
    if result.items:
        again = "diskwise clean --android" if args.android else "diskwise clean"
        print(f"  Nothing was deleted. Run `{again}` to choose what to remove.\n")
    return 0


def parse_selection(text: str, count: int, items: list[Item]) -> list[int]:
    """'1 3 5-7', '1,2', 'safe' or 'all' -> zero-based indexes. Raises ValueError."""
    text = text.strip().lower()
    if text in ("safe", "green"):
        return [i for i, item in enumerate(items) if item.safety == SAFE]
    if text == "all":
        return list(range(count))
    picked: list[int] = []
    for part in text.replace(",", " ").split():
        if "-" in part:
            a, b = part.split("-", 1)
            nums = range(int(a), int(b) + 1)
        else:
            nums = [int(part)]
        for n in nums:
            if not 1 <= n <= count:
                raise ValueError(f"there is no item {n}")
            if n - 1 not in picked:
                picked.append(n - 1)
    return picked


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def yes(prompt: str) -> bool:
    return ask(prompt).strip().lower() in ("y", "yes")


def cmd_clean(args) -> int:
    s = Style()
    result = _scan(args)
    cleanable = [i for i in result.sorted() if i.cleanable]

    if args.only:
        wanted = set(args.only)
        chosen = [i for i in cleanable if i.id in wanted]
        unknown = wanted - {i.id for i in chosen}
        if unknown:
            print(f"  Not found or not cleanable: {', '.join(sorted(unknown))}", file=sys.stderr)
    elif args.yes:
        chosen = [i for i in cleanable if i.safety == SAFE]
    else:
        if not cleanable:
            print_scan(result, details=args.details, min_size=0 if args.all else args.min_size)
            print("  Nothing here that Diskwise can clean for you.\n")
            return 0
        shown = print_scan(
            ScanResult(cleanable, result.notices), details=args.details,
            min_size=0 if args.all else args.min_size, numbered=True,
        )
        if not sys.stdin.isatty():
            print("  Not running in a terminal, so nothing was cleaned. Use --only ID --yes to clean without prompts.")
            return 1
        while True:
            answer = ask("  Which items? Numbers like 1 3 5-7, 'safe' for every 🟢 item, or Enter to cancel: ")
            if not answer.strip():
                print("  Cancelled. Nothing was deleted.\n")
                return 0
            try:
                chosen = [shown[i] for i in parse_selection(answer, len(shown), shown)]
                break
            except ValueError as exc:
                print(f"  {exc}. Try again.")
        confirmed = []
        for item in chosen:
            if item.safety == CHECK:
                print(f"\n  {SAFETY_DOTS[CHECK]} {s.bold}{item.name}{s.reset} ({human(item.size)})")
                if item.hint:
                    print(f"     {item.hint}")
                if not yes("     Clean this one? [y/N] "):
                    continue
            confirmed.append(item)
        chosen = confirmed

    if not chosen:
        print("  Nothing selected. Nothing was deleted.\n")
        return 0

    to_trash = [i for i in chosen if i.action == TRASH]
    commands = [i for i in chosen if i.action == COMMAND]
    print(f"\n  {s.bold}Ready to clean {plural(len(chosen), 'item')} ({human(sum(i.size for i in chosen))}):{s.reset}")
    for item in to_trash:
        print(f"   • {item.name}: move {plural(len(item.paths), 'item')} to the Trash")
    for item in commands:
        print(f"   • {item.name}: run `{' '.join(item.command)}` (can't be undone, but {item.comes_back[0].lower() + item.comes_back[1:]})")

    if args.dry_run:
        print("\n  Dry run: nothing was changed.\n")
        return 0
    if not args.yes and not yes("\n  Go ahead? [y/N] "):
        print("  Cancelled. Nothing was deleted.\n")
        return 0

    with Spinner() as spinner:
        spinner.update("Cleaning")
        outcomes = clean(chosen)
    freed = 0
    print()
    for o in outcomes:
        freed += o.freed
        mark = "✓" if not o.errors else ("!" if o.freed else "✗")
        print(f"  {mark} {o.item.name}: {human(o.freed)}")
        for err in o.errors[:5]:
            print(f"      skipped {err}")
        if len(o.errors) > 5:
            print(f"      … and {len(o.errors) - 5} more skipped")
    print(f"\n  {s.bold}Cleaned {human(freed)}.{s.reset}")
    if any(o.moved for o in outcomes):
        bin_name = "Recycle Bin" if platform_name() == "windows" else "Trash"
        print(f"  Files went to the {bin_name}: empty it to get the space back.")
        print("  Changed your mind? Run `diskwise undo` to put everything back.")
    print()
    return 0


def cmd_undo(args) -> int:
    result = undo(args.session)
    if not result.session:
        print("  Nothing to undo.")
        return 0
    print(f"  Restored {plural(result.restored, 'item')} from the clean on {result.session}.")
    for err in result.errors:
        print(f"  ! Couldn't restore {err}")
    for name in result.skipped_commands:
        print(f"  • {name} was removed by its own tool and can't be restored (it comes back when needed).")
    return 1 if result.errors else 0


def cmd_history(args) -> int:
    sessions = History().load()
    if not sessions:
        print("  No cleans yet.")
        return 0
    for s in reversed(sessions):
        names = sorted({e["name"] for e in s["entries"]})
        state = " (undone)" if s.get("undone") else ""
        print(f"  {s['id']}{state}: {human(s.get('freed', 0))}, {', '.join(names)}")
    return 0


def cmd_rules(args) -> int:
    rules = catalog.RULES
    if args.json:
        json.dump([r.__dict__ for r in rules], sys.stdout, indent=2, default=list)
        print()
        return 0
    for r in rules:
        print(f"{SAFETY_DOTS[r.safety]} {r.id:<26} {SAFETY_LABELS[r.safety]:<12} {', '.join(r.platforms):<22} {r.name}")
    print(f"\n{len(rules)} rules, plus finders for simulators, backups, Downloads, Trash, Docker, projects and Android.")
    return 0


def cmd_measure(args) -> int:
    from .folders import measure, resolve_folder, to_dicts

    try:
        folder = resolve_folder(args.folder)
        entries = measure(folder)
    except (ValueError, OSError) as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1
    if args.json:
        # One line on stdout: the administrator helper is read this way, so it never writes a file.
        print(json.dumps({"path": str(folder), "entries": to_dicts(entries)}))
        return 0
    for e in entries:
        if e.size or e.other_disk:
            note = "  (another disk)" if e.other_disk else (f"  ({e.denied} unreadable)" if e.denied else "")
            print(f"  {human(e.size):>10}  {e.name}{'/' if e.is_dir else ''}{note}")
    print(f"\n  {human(sum(e.size for e in entries))} in {folder}")
    return 0


def cmd_ui(args) -> int:
    from .ui import serve

    return serve(port=args.port, open_browser=not args.no_browser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskwise",
        description="Find out what's eating your disk, why it's there, and whether it's safe to delete.",
    )
    parser.add_argument("--version", action="version", version=f"diskwise {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan_opts = argparse.ArgumentParser(add_help=False)
    scan_opts.add_argument("--android", action="store_true", help="scan a connected Android phone over adb")
    scan_opts.add_argument("--device", help="adb serial of the phone to scan (with --android)")
    scan_opts.add_argument("--details", "-d", action="store_true", help="show paths, ids and what's inside each item")
    scan_opts.add_argument("--all", action="store_true", help="also show small items")
    scan_opts.add_argument("--min-size", type=parse_size, default=parse_size("50MB"), metavar="SIZE",
                           help="hide items smaller than this (default 50MB)")
    scan_opts.add_argument("--projects", action="append", metavar="DIR",
                           help="where to look for project leftovers (default: your home folder; repeatable)")
    scan_opts.add_argument("--no-projects", action="store_true", help="skip looking through projects")
    scan_opts.add_argument("--stale-days", type=int, default=180, metavar="DAYS",
                           help="a project counts as old after this many days (default 180)")
    scan_opts.add_argument("--no-docker", action="store_true", help="skip Docker")
    scan_opts.add_argument("--json", action="store_true", help="print results as JSON")

    p = sub.add_parser("scan", parents=[scan_opts], help="report what's using space (deletes nothing)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("clean", parents=[scan_opts], help="pick items and move them to the Trash")
    p.add_argument("--only", nargs="+", metavar="ID", help="clean these item ids (see `scan --details`)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="don't ask; with --only cleans those ids, otherwise every 🟢 Safe item")
    p.add_argument("--dry-run", action="store_true", help="show what would be cleaned and stop")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("undo", help="put back what the last clean moved to the Trash")
    p.add_argument("session", nargs="?", help="a session from `diskwise history` (default: the last one)")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("history", help="list past cleans")
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("rules", help="list every location Diskwise knows about")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("measure", help="show what's inside any folder, biggest first (deletes nothing)")
    p.add_argument("folder", nargs="?", default="~", help="the folder to measure (default: your home folder)")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("ui", help="open the visual view in your browser")
    p.add_argument("--port", type=int, default=0, help="port to listen on (default: any free port)")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    p.set_defaults(func=cmd_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # Windows consoles default to a code page that can't print the safety dots.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  Stopped. Nothing more was changed.")
        return 130
