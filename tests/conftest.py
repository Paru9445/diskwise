import os
from pathlib import Path

import pytest


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A throwaway home folder, so tests never see or touch real files."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("DISKWISE_DATA_DIR", str(tmp_path / "diskwise-data"))
    (home / ".Trash").mkdir()
    # Keep system-wide locations (/Applications/Xcode*.app, simulator runtimes) out of
    # tests: CI Macs have many Xcodes, and tests should only see the fake home.
    from diskwise import catalog, finders

    monkeypatch.setattr(catalog, "RULES", [r for r in catalog.RULES if not any(p.startswith("/") for p in r.paths)])
    monkeypatch.setattr(finders, "simulator_runtimes", lambda notices: [])
    return home


def write(path: Path, size: int = 10_000, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    if age_days:
        import time

        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path
