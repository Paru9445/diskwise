import os
import sys
from pathlib import Path

import pytest

from conftest import write
from diskwise.cleaner import History, Refused, check_target, clean, undo
from diskwise.cli import parse_selection
from diskwise.model import CHECK, KEEP, SAFE, Item


def make_item(paths, safety=SAFE, **kw):
    return Item(
        id=kw.pop("id", "test-item"), name="Test item", category="Test", safety=safety,
        what="x.", creator="tests", comes_back="yes", size=sum(Path(p).stat().st_size for p in paths),
        paths=[str(p) for p in paths], **kw,
    )


def test_refuses_places_outside_the_rules(fake_home):
    with pytest.raises(Refused):
        check_target(str(fake_home))
    with pytest.raises(Refused):
        check_target(str(fake_home / "Documents"))
    with pytest.raises(Refused):
        check_target(str(fake_home / ".ssh" / "id_ed25519"))
    with pytest.raises(Refused):
        check_target(str(Path(fake_home).parent / "elsewhere" / "file"))
    with pytest.raises(Refused):
        check_target("relative/path")
    assert check_target(str(fake_home / ".npm" / "_cacache")).name == "_cacache"


def test_clean_moves_to_trash_and_undo_puts_back(fake_home):
    a = write(fake_home / ".cache" / "tool" / "a.bin", 5000)
    b = write(fake_home / ".cache" / "tool" / "sub" / "b.bin", 5000)
    item = make_item([a, b.parent])
    history = History()

    [outcome] = clean([item], history=history)
    assert outcome.errors == []
    assert outcome.moved == 2
    assert not a.exists() and not b.exists()
    sessions = history.load()
    assert len(sessions) == 1 and len(sessions[0]["entries"]) == 2

    result = undo(history=history)
    assert result.errors == []
    assert result.restored == 2
    assert a.read_bytes() and b.read_bytes()
    assert history.load()[0]["undone"] is True
    if sys.platform == "darwin":
        assert list((fake_home / ".Trash").iterdir()) == []  # empty Diskwise folders are tidied up
    assert undo(history=history).session == ""  # nothing left to undo


def test_undo_does_not_overwrite_recreated_files(fake_home):
    a = write(fake_home / ".cache" / "tool" / "a.bin", 100)
    history = History()
    clean([make_item([a])], history=history)
    write(a, 50)  # the app made a new one meanwhile
    result = undo(history=history)
    assert result.restored == 0 and len(result.errors) == 1
    assert a.stat().st_size == 50


def test_clean_never_touches_keep_items(fake_home):
    a = write(fake_home / "Apps" / "Important" / "data", 100)
    [outcome] = clean([make_item([a], safety=KEEP)], history=History())
    assert a.exists() and outcome.errors


def test_clean_skips_refused_paths_but_cleans_the_rest(fake_home):
    good = write(fake_home / ".cache" / "x" / "ok.bin", 100)
    bad = write(fake_home / "notes.txt", 100)  # directly in home: refused
    [outcome] = clean([make_item([good, bad])], history=History())
    assert not good.exists() and bad.exists()
    assert outcome.moved == 1 and len(outcome.errors) == 1


@pytest.mark.skipif(os.name == "nt", reason="freedesktop Trash layout is for Linux")
def test_linux_trash_writes_trashinfo(fake_home, monkeypatch):
    import diskwise.trash as trash_mod

    monkeypatch.setattr(trash_mod, "MACOS", False)
    a = write(fake_home / ".cache" / "t" / "file.bin", 100)
    clean([make_item([a])], history=History())
    info = fake_home / ".local/share/Trash/info/file.bin.trashinfo"
    assert info.exists()
    assert "Path=" in info.read_text() and "DeletionDate=" in info.read_text()
    assert (fake_home / ".local/share/Trash/files/file.bin").exists()
    undo(history=History())
    assert a.exists() and not info.exists()


def test_parse_selection():
    items = [
        Item(id=str(i), name="", category="", safety=SAFE if i % 2 else CHECK, what="", creator="", comes_back="", size=1)
        for i in range(6)
    ]
    assert parse_selection("1 3", 6, items) == [0, 2]
    assert parse_selection("2-4, 6", 6, items) == [1, 2, 3, 5]
    assert parse_selection("safe", 6, items) == [1, 3, 5]
    assert parse_selection("all", 6, items) == list(range(6))
    with pytest.raises(ValueError):
        parse_selection("9", 6, items)
    with pytest.raises(ValueError):
        parse_selection("one", 6, items)
