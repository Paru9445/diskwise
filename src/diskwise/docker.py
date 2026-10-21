"""Docker images, containers, volumes and build cache, measured by Docker itself."""

from __future__ import annotations

import json
import re

from .model import CHECK, COMMAND, CONTAINERS, SAFE, Item
from .util import parse_size, run, which

KINDS = {
    "Images": dict(
        id="docker-images",
        name="Unused Docker images",
        safety=SAFE,
        what="Images no container is using. Docker downloads or builds them again when needed.",
        comes_back="Yes, when you pull or build them again.",
        command=["docker", "image", "prune", "-a", "-f"],
    ),
    "Build Cache": dict(
        id="docker-build-cache",
        name="Docker build cache",
        safety=SAFE,
        what="Layers saved to make image builds faster.",
        comes_back="Rebuilt the next time you build an image.",
        command=["docker", "builder", "prune", "-a", "-f"],
    ),
    "Containers": dict(
        id="docker-containers",
        name="Stopped Docker containers",
        safety=CHECK,
        what="Containers that have stopped. Anything written inside them is lost when they are removed.",
        comes_back="No. Start a new container from its image instead.",
        command=["docker", "container", "prune", "-f"],
    ),
    "Local Volumes": dict(
        id="docker-volumes",
        name="Unused Docker volumes",
        safety=CHECK,
        what="Volumes no container is using. They can hold real data, like a local database.",
        comes_back="No.",
        command=["docker", "volume", "prune", "-a", "-f"],
    ),
}


def parse_df(output: str) -> dict[str, int]:
    """Reclaimable bytes per type from `docker system df --format '{{json .}}'`."""
    out: dict[str, int] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        m = re.match(r"\s*([\d.]+\s*[a-zA-Z]*)", row.get("Reclaimable", ""))
        if not m:
            continue
        try:
            out[row.get("Type", "")] = parse_size(m.group(1).replace(" ", ""))
        except ValueError:
            continue
    return out


def scan(notices: list[str]) -> list[Item]:
    if not which("docker"):
        return []
    code, out, err = run(["docker", "system", "df", "--format", "{{json .}}"], timeout=30)
    if code != 0:
        if re.search(r"daemon|connect|socket|pipe", err, re.I):
            notices.append(
                "Docker is installed but not running. Start Docker Desktop and scan again to see unused images and build cache."
            )
        else:
            notices.append(f"Couldn't read Docker disk usage: {err.strip()[:200]}")
        return []
    items = []
    for kind, size in parse_df(out).items():
        spec = KINDS.get(kind)
        if spec and size > 0:
            items.append(
                Item(
                    category=CONTAINERS,
                    creator="Docker",
                    size=size,
                    action=COMMAND,
                    hint="Docker removes these directly; they don't go to the Trash.",
                    **spec,
                )
            )
    return items
