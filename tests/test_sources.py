"""Projects, Docker and Android parsing, plus a CLI smoke test."""

import json
import shutil
import subprocess
import time

import pytest

from conftest import write
from diskwise import android, docker, projects
from diskwise.cli import main
from diskwise.model import CHECK, KEEP, SAFE


def age(path, days):
    t = time.time() - days * 86400
    import os

    for p in [path, *path.rglob("*")]:
        os.utime(p, (t, t))


def test_projects_old_and_recent_node_modules(tmp_path):
    old = tmp_path / "old-app"
    write(old / "package.json", 100)
    write(old / "node_modules" / "left-pad" / "index.js", 40_000)
    age(old, 400)
    new = tmp_path / "new-app"
    write(new / "package.json", 100)
    write(new / "node_modules" / "react" / "index.js", 40_000)

    items = {i.id: i for i in projects.scan([tmp_path])}
    assert items["projects-node-modules-old"].safety == SAFE
    assert items["projects-node-modules-old"].paths == [str(old / "node_modules")]
    assert items["projects-node-modules-recent"].safety == CHECK
    assert "untouched for 6+ months" in items["projects-node-modules-old"].name


def test_projects_need_proof_a_folder_is_generated(tmp_path):
    write(tmp_path / "loose" / "node_modules" / "x.js", 100)  # no package.json next to it
    write(tmp_path / "docs" / "build" / "page.html", 100)  # no project file at all
    venv = tmp_path / "py"
    write(venv / ".venv" / "pyvenv.cfg", 10)
    write(venv / ".venv" / "lib" / "site.py", 5000)
    found = projects.find([tmp_path])
    assert [(f.path.name, f.kind.key) for f in found] == [(".venv", "python-venvs")]


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_build_folders_must_be_git_ignored(tmp_path):
    repo = tmp_path / "web"
    write(repo / "package.json", 10)
    write(repo / "build" / "icon.png", 100)  # electron-builder style: real source files
    write(repo / "dist" / "bundle.js", 100)
    (repo / ".gitignore").write_text("dist/\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    names = sorted(f.path.name for f in projects.find([tmp_path]))
    assert names == ["dist"]


def test_projects_do_not_descend_into_artifacts(tmp_path):
    app = tmp_path / "app"
    write(app / "package.json", 10)
    write(app / "node_modules" / "dep" / "package.json", 10)
    write(app / "node_modules" / "dep" / "node_modules" / "x" / "i.js", 10)
    assert [f.path for f in projects.find([tmp_path])] == [app / "node_modules"]


def test_docker_df_parsing():
    out = "\n".join(json.dumps(r) for r in [
        {"Type": "Images", "TotalCount": "12", "Active": "3", "Size": "8.1GB", "Reclaimable": "5.2GB (64%)"},
        {"Type": "Containers", "TotalCount": "4", "Active": "1", "Size": "120MB", "Reclaimable": "100MB (83%)"},
        {"Type": "Local Volumes", "TotalCount": "2", "Active": "0", "Size": "1GB", "Reclaimable": "1GB (100%)"},
        {"Type": "Build Cache", "TotalCount": "40", "Active": "0", "Size": "9.2GB", "Reclaimable": "9.2GB"},
    ])
    assert docker.parse_df(out) == {
        "Images": 5_200_000_000,
        "Containers": 100_000_000,
        "Local Volumes": 1_000_000_000,
        "Build Cache": 9_200_000_000,
    }


DISKSTATS = """Latency: 2ms [512B Data Write]
Recent Disk Write Speed (kB/s) = 48211
Data-Free: 42135216K / 113061500K total = 37% free
Cache-Free: 42135216K / 113061500K total = 37% free
System-Free: 0K / 5767168K total = 0% free
File-based Encryption: true
App Size: 23245262848
App Data Size: 9624297472
App Cache Size: 2049482752
Photos Size: 3524136960
Videos Size: 1393426432
Audio Size: 8192
Downloads Size: 138813440
System Size: 15153684480
Other Size: 1236381696
Package Names: ["com.whatsapp","com.google.android.youtube","com.spotify.music"]
App Sizes: [100000000,200000000,150000000]
App Data Sizes: [5000000000,300000000,900000000]
Cache Sizes: [400000000,1200000000,449482752]
"""


def test_android_parsing_and_items():
    stats = android.parse_diskstats(DISKSTATS)
    assert stats["App Cache Size"] == 2049482752
    assert stats["free"] == 42135216 * 1024
    assert stats["Package Names"][1] == "com.google.android.youtube"

    large = android.parse_large_files(
        "1500000000|/storage/emulated/0/DCIM/Camera/VID_1.mp4\n"
        "300000000|/storage/emulated/0/Download/game.apk\n"
        "200000000|/storage/emulated/0/Backups/old.zip\n"
        "garbage line\n"
    )
    assert large[0] == (1500000000, "/storage/emulated/0/DCIM/Camera/VID_1.mp4")

    items = {i.id: i for i in android.build_items("SERIAL1", stats, large, adb="adb")}
    caches = items["android-app-caches"]
    assert caches.safety == SAFE and caches.cleanable
    assert caches.command == ["adb", "-s", "SERIAL1", "shell", "pm", "trim-caches", "999G"]
    assert caches.details[0].label == "com.google.android.youtube"
    assert not items["android-media"].cleanable  # photos and videos are never deleted by Diskwise
    assert items["android-downloads"].size == 138813440
    assert [d.path for d in items["android-large-files"].details] == ["/storage/emulated/0/Backups/old.zip"]
    assert items["android-apps"].safety == KEEP


def test_android_device_list_parsing():
    out = (
        "List of devices attached\n"
        "R58N12345 device usb:1-1 product:a52 model:SM_A525F device:a52q transport_id:1\n"
        "emulator-5554 unauthorized transport_id:2\n\n"
    )
    devices = android.parse_devices(out)
    assert [(d.serial, d.state, d.model) for d in devices] == [
        ("R58N12345", "device", "SM A525F"),
        ("emulator-5554", "unauthorized", ""),
    ]


def test_cli_smoke(fake_home, capsys):
    write(fake_home / ".npm" / "_cacache" / "big", 60_000)
    assert main(["rules"]) == 0
    assert main(["scan", "--no-docker", "--projects", str(fake_home)]) == 0
    assert "npm cache" in capsys.readouterr().out
    assert main(["history"]) == 0
    assert main(["undo"]) == 0


def test_cli_scan_json(fake_home, capsys):
    write(fake_home / ".npm" / "_cacache" / "big", 60_000)
    assert main(["scan", "--json", "--no-docker", "--no-projects"]) == 0
    data = json.loads(capsys.readouterr().out)
    ids = [i["id"] for i in data["items"]]
    assert "npm-cache" in ids
    assert data["totals"]["safe"] >= 60_000
