from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import uuid


@dataclass(frozen=True)
class Isolation:
    fixture_root: Path
    engram_home: Path
    empty_mcp_config: Path


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a in b.parents or b in a.parents


@contextmanager
def isolated_fixture(source: Path, scratch_root: Path, live_root: Path):
    source, scratch_root, live_root = source.resolve(), scratch_root.resolve(), live_root.resolve()
    if _overlaps(scratch_root, live_root) or _overlaps(source, live_root):
        raise ValueError("isolation path overlaps live Engram path")
    root = scratch_root / str(uuid.uuid4())
    fixture = root / "fixture"
    engram_home = root / "empty-engram"
    try:
        shutil.copytree(source, fixture)
        engram_home.mkdir()
        empty_mcp = root / "empty-mcp.json"
        empty_mcp.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)
        subprocess.run(["git", "add", "."], cwd=fixture, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Engram Experiment", "-c",
                "user.email=experiment@invalid", "commit", "--allow-empty", "-qm",
                "fixture",
            ],
            cwd=fixture, check=True,
        )
        yield Isolation(fixture, engram_home, empty_mcp)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def isolated_environment(base: dict[str, str], isolation: Isolation) -> dict[str, str]:
    env = dict(base)
    for key in (
        "CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_PAIR_SESSION_ID",
        "ENGRAM_RUN_KEY", "ENGRAM_HARNESS",
    ):
        env.pop(key, None)
    env.update({
        "ENGRAM_WAKE": "skip",
        "ENGRAM_HOME": str(isolation.engram_home),
        "ENGRAM_PROJECT_ROOT": str(isolation.fixture_root),
        "NO_COLOR": "1",
    })
    return env
