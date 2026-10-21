import os
import struct
from pathlib import Path

import pytest

from conftest import write
from diskwise import catalog, finders
from diskwise.model import CHECK, KEEP, SAFE, Item
from diskwise.scanner import measure_rule, resolve
from diskwise.sizes import usage
from diskwise.trash import parse_recycle_info
from diskwise.util import human, parse_size


def test_human_and_parse_size():
    assert human(0) == "0 B"
    assert human(18_400_000_000) == "18.4 GB"
    assert human(999) == "999 B"
    assert parse_size("1.2GB") == 1_200_000_000
    assert parse_size("512.5kB") == 512_500
    assert parse_size("0B") == 0
    assert parse_size("50MB") == 50_000_000
    assert parse_size("1GiB") == 1024**3
    with pytest.raises(ValueError):
        parse_size("lots")


def test_usage_counts_files_and_skips_symlinks(tmp_path):
    write(tmp_path / "a" / "one.bin", 50_000)
    write(tmp_path / "a" / "sub" / "two.bin", 50_000)
    outside = write(tmp_path / "outside.bin", 500_000)
    try:
        os.symlink(outside, tmp_path / "a" / "link")
    except (OSError, NotImplementedError):
        pass  # no symlink permission on some Windows setups
    u = usage(tmp_path / "a")
    assert u.files >= 2
    assert 100_000 <= u.bytes < 400_000  # the 500 KB file behind the link is not counted


def test_usage_counts_hard_links_once(tmp_path):
    original = write(tmp_path / "d" / "file.bin", 200_000)
    try:
        os.link(original, tmp_path / "d" / "again.bin")
    except (OSError, NotImplementedError):
        pytest.skip("hard links not supported here")
    assert usage(tmp_path / "d").bytes < 350_000


def test_resolve_skips_templates_for_other_systems(fake_home):
    write(fake_home / ".npm" / "_cacache" / "index", 1000)
    found = resolve(("~/.npm/_cacache", "%NOT_A_REAL_VAR%/npm-cache", "$NOT_SET_EITHER/x"))
    assert found == [fake_home / ".npm" / "_cacache"]


def test_measure_rule_targets_folder_contents(fake_home):
    write(fake_home / ".npm" / "_cacache" / "content" / "a", 30_000)
    write(fake_home / ".npm" / "_cacache" / "index" / "b", 30_000)
    item, roots = measure_rule(catalog.find_rule("npm-cache"))
    assert item.safety == SAFE
    assert sorted(Path(p).name for p in item.paths) == ["content", "index"]
    assert item.size >= 60_000
    assert {d.label for d in item.details} == {"content", "index"}


def test_catalog_is_well_formed():
    ids = [r.id for r in catalog.RULES]
    assert len(ids) == len(set(ids)), "rule ids must be unique"
    for r in catalog.RULES:
        assert r.safety in (SAFE, CHECK, KEEP)
        assert r.what.endswith("."), r.id
        assert r.paths and r.platforms
        if r.safety == KEEP:
            assert r.action == "none"


def test_keep_items_are_never_cleanable():
    item = Item(id="x", name="x", category="c", safety=KEEP, what="", creator="", comes_back="", size=1)
    assert not item.cleanable


def test_partition_splits_folders_holding_claimed_paths(tmp_path):
    for name in ("Google/Chrome/x", "Google/Other/y", "Slack/z", "Homebrew/w"):
        write(tmp_path / name, 10)
    claimed = {tmp_path / "Google" / "Chrome", tmp_path / "Homebrew"}
    rest = finders.partition(tmp_path, claimed)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in rest) == ["Google/Other", "Slack"]


def test_downloads_finds_old_installers_and_large_files(tmp_path):
    write(tmp_path / "Tool.dmg", 2_000_000, age_days=10)
    write(tmp_path / "fresh.dmg", 2_000_000, age_days=1)
    write(tmp_path / "movie.mp4", 100_500_000, age_days=60)
    write(tmp_path / "small.pdf", 1000, age_days=60)
    items = {i.id: i for i in finders.downloads([], folder=tmp_path)}
    assert [Path(p).name for p in items["downloads-installers"].paths] == ["Tool.dmg"]
    assert [Path(p).name for p in items["downloads-large"].paths] == ["movie.mp4"]
    assert all(i.safety == CHECK for i in items.values())


def test_parse_recycle_bin_info_v2():
    path = "C:\\Users\\me\\AppData\\Local\\Temp\\old"
    raw = path.encode("utf-16-le") + b"\0\0"
    data = struct.pack("<qqq", 2, 1234, 132000000000000000) + struct.pack("<i", len(path) + 1) + raw
    assert parse_recycle_info(data) == (path, 132000000000000000)


def test_parse_recycle_bin_info_v1():
    path = "C:\\temp\\file.txt"
    raw = (path.encode("utf-16-le") + b"\0" * 520)[:520]
    data = struct.pack("<qqq", 1, 10, 5) + raw
    assert parse_recycle_info(data)[0] == path
