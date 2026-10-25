import json
import os
import sys
import time

import pytest

from conftest import write
from diskwise import access, folders
from diskwise.cli import main
from test_ui import call, server  # noqa: F401  (the server fixture)


def test_measure_lists_biggest_first(tmp_path):
    write(tmp_path / "big" / "a.bin", 300_000)
    write(tmp_path / "big" / "deep" / "b.bin", 200_000)
    write(tmp_path / "small.bin", 10_000)
    entries = folders.measure(tmp_path)
    assert [e.name for e in entries] == ["big", "small.bin"]
    assert entries[0].is_dir and entries[0].files == 2 and entries[0].size >= 500_000
    assert all(e.done for e in entries)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need admin rights on Windows")
def test_measure_skips_symlinks(tmp_path):
    write(tmp_path / "real" / "a.bin", 100_000)
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert [e.name for e in folders.measure(tmp_path)] == ["real"]


def test_resolve_folder_rejects_relative_and_missing(tmp_path):
    with pytest.raises(ValueError):
        folders.resolve_folder("relative/path")
    with pytest.raises(ValueError):
        folders.resolve_folder(str(tmp_path / "nope"))
    assert folders.resolve_folder(str(tmp_path)) == tmp_path


def test_crumbs_go_from_root_down(tmp_path):
    names = [c["path"] for c in folders.crumbs(tmp_path)]
    assert names[-1] == str(tmp_path) and len(names) == len(tmp_path.parts)


def test_measure_command_prints_json(tmp_path, capsys):
    write(tmp_path / "x" / "f.bin", 50_000)
    assert main(["measure", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["path"] == str(tmp_path) and data["entries"][0]["name"] == "x"


def test_admin_helper_output_is_read_from_stdout_not_a_file(tmp_path):
    """The elevated helper must never write a file: run it as the app would and parse its output."""
    import subprocess

    write(tmp_path / "x" / "f.bin", 50_000)
    before = set(tmp_path.rglob("*"))
    proc = subprocess.run(access.self_command("measure", str(tmp_path), "--json"), capture_output=True, text=True, check=True)
    assert access.parse_helper_output(proc.stdout)["entries"][0]["name"] == "x"
    assert set(tmp_path.rglob("*")) == before


def test_parse_helper_output_rejects_garbage():
    for bad in ("", "password incorrect", "[1, 2]", '{"entries": "nope"}'):
        with pytest.raises(access.AccessError):
            access.parse_helper_output(bad)


def test_no_admin_measuring_on_windows(monkeypatch):
    monkeypatch.setattr(access, "MACOS", False)
    monkeypatch.setattr(access, "LINUX", False)
    monkeypatch.setattr(access, "WINDOWS", True)
    assert access.admin_available() is False
    with pytest.raises(access.AccessError):
        access.measure_as_admin("C:\\")


def wait_for_folder(port, token):
    for _ in range(100):
        status, body = call(port, "/api/folder", token=token)
        snap = json.loads(body)
        if snap["done"]:
            return snap
        time.sleep(0.05)
    raise AssertionError("folder measuring never finished")


def test_folder_view_marks_what_the_scan_knows(server, fake_home):  # noqa: F811
    state, port = server
    write(fake_home / ".npm" / "_cacache" / "blob", 50_000)
    write(fake_home / "notes" / "todo.txt", 5_000)
    assert call(port, "/api/scan", token=state.token)[0] == 200

    status, _ = call(port, "/api/folder", token=state.token, body={"path": str(fake_home)})
    assert status == 200
    snap = wait_for_folder(port, state.token)
    by_name = {e["name"]: e for e in snap["entries"]}
    assert by_name[".npm"]["known"] == {"safe_inside": by_name[".npm"]["known"]["safe_inside"]}
    assert by_name[".npm"]["known"]["safe_inside"] > 0
    assert by_name["notes"]["known"] is None

    call(port, "/api/folder", token=state.token, body={"path": str(fake_home / ".npm" / "_cacache")})
    snap = wait_for_folder(port, state.token)
    assert snap["entries"][0]["known"]["id"] == "npm-cache"


def test_folder_view_rejects_bad_paths(server):  # noqa: F811
    state, port = server
    assert call(port, "/api/folder", token=state.token, body={"path": "not/absolute"})[0] == 400


def test_reveal_only_opens_listed_paths(server, fake_home, monkeypatch):  # noqa: F811
    state, port = server
    opened = []
    monkeypatch.setattr(access, "reveal", opened.append)
    write(fake_home / "notes" / "todo.txt", 5_000)
    assert call(port, "/api/reveal", token=state.token, body={"path": "/etc"})[0] == 400

    call(port, "/api/folder", token=state.token, body={"path": str(fake_home)})
    wait_for_folder(port, state.token)
    target = str(fake_home / "notes")
    assert call(port, "/api/reveal", token=state.token, body={"path": target})[0] == 200
    assert opened == [target]


def test_access_status_and_onboarding(server, fake_home):  # noqa: F811
    state, port = server
    status, body = call(port, "/api/access", token=state.token)
    a = json.loads(body)
    assert status == 200 and a["onboarded"] is False and a["home"] == str(fake_home)
    if sys.platform != "darwin":
        assert a["full_disk_access"] is None  # only macOS has Full Disk Access

    _, body = call(port, "/api/onboarded", token=state.token, body={})
    assert json.loads(body)["onboarded"] is True


def test_request_folders_records_answers(fake_home):
    (fake_home / "Desktop").mkdir()
    (fake_home / "Downloads").mkdir()
    assert access.request_folders() == {"Desktop": True, "Downloads": True}
    assert access.load_settings()["folders"] == {"Desktop": True, "Downloads": True}
