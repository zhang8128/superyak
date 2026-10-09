"""Browser lanes (docs/superpowers/specs/2026-10-08-browser-lane-design.md). These run on the Pi with fakes: a patched
sys.platform, a patched Claude Code version, lsof fixtures, a fake fetch and a fake clock. The Mac acceptance run is
team/scripts/lane_acceptance.py.

Run: make check-team (from the superyak root)
"""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import tomllib
from pathlib import Path

import pytest

from superyak_team import lane, teamd, teamlib, workers

MOCK_BIN = Path(__file__).resolve().parent / "mock-bin"


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo)] + cmd, check=True)
    (repo / "README.md").write_text("toy\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("SUPERYAK_TEAM_HOME", str(tmp_path / "teamhome"))
    monkeypatch.setenv("SUPERYAK_TEAM_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SUPERYAK_TEAM_TOKEN_STORE", "file")
    monkeypatch.setenv("PATH", "%s:%s" % (MOCK_BIN, os.environ["PATH"]))
    monkeypatch.setenv("MOCK_TEAM_LOG", str(tmp_path / "agent.log"))
    monkeypatch.setattr(lane, "MANAGED_SETTINGS", tmp_path / "managed-settings.json")
    return {"repo": repo, "tmp": tmp_path, "home": home}


@pytest.fixture
def mac(monkeypatch):
    """A Mac with a new enough Claude Code and Python, as far as the spawn checks can tell."""
    monkeypatch.setattr(lane.sys, "platform", "darwin")
    monkeypatch.setattr(lane, "claude_version", lambda: (2, 1, 290))
    monkeypatch.setattr(lane, "python_ok", lambda: True)
    # From Task 8, spawn installs and checks the broker's Playwright and browser before taking teamd's lock.
    monkeypatch.setattr(lane, "prepare_broker", lambda repo, base, worktrees: None, raising=False)


def lane_team(env, team_id="t1", **cfg_over):
    cfg = dict(teamlib.DEFAULT_CONFIG, browser_lane=True, max_workers=4)
    cfg.update(cfg_over)
    return teamd.Team(team_id, env["repo"], "toy goal", cfg)


def lead(team, op, args):
    return team.handle({"op": op, "caller": "lead", "token": teamlib.get_token(team.team_id, "lead"), "args": args})


# ---------- Task 1: who sets browser_lane, and who gets a lane ----------

def test_browser_lane_is_set_by_a_person_never_by_team_start(env, tmp_path, monkeypatch):
    """Spec unit test 4."""
    assert teamlib.team_config()["browser_lane"] is False
    (tmp_path / "cfg.json").write_text(json.dumps({"browser_lane": True}))
    assert teamlib.team_config()["browser_lane"] is True                       # config.json
    (tmp_path / "cfg.json").write_text("{}")
    presets = tmp_path / "presets.json"
    presets.write_text(json.dumps({"lane": {"description": "UX checks", "browser_lane": True}}))
    monkeypatch.setenv("SUPERYAK_TEAM_PRESETS", str(presets))
    assert teamlib.team_config("lane")["browser_lane"] is True                  # a preset
    with pytest.raises(teamlib.RejectedMessage, match="browser_lane can't be set in team_start"):
        teamlib.team_config(None, {"browser_lane": True})
    with pytest.raises(teamlib.RejectedMessage, match="browser_lane can't be set in team_start"):
        teamlib.team_config("lane", {"browser_lane": False})                    # not even to turn it off
    for bad in ("yes", 1, None):
        presets.write_text(json.dumps({"lane": {"browser_lane": bad}}))
        with pytest.raises(teamlib.RejectedMessage, match="browser_lane must be true or false"):
            teamlib.team_config("lane")
        (tmp_path / "cfg.json").write_text(json.dumps({"browser_lane": bad}))
        with pytest.raises(teamlib.RejectedMessage, match="browser_lane must be true or false"):
            teamlib.team_config()
        (tmp_path / "cfg.json").write_text("{}")
    assert "browser_lane" in teamlib.PRESET_KEYS and "browser_lane" not in teamlib.OVERRIDE_KEYS
    assert teamlib.PRESET_KEYS - teamlib.OVERRIDE_KEYS == {"browser_lane"}


def test_status_shows_browser_lane(env):
    team = lane_team(env)
    assert team.status()["config"]["browser_lane"] is True


@pytest.mark.parametrize("case, kind, mode, setup, reason", [
    ("codex", "codex", "build", None, "for Claude workers only"),
    ("collab", "claude", "collab", None, "for builders only"),
    ("lane off", "claude", "build", "off", "browser lanes are off for this team"),
    ("linux", "claude", "build", "linux", "macOS only"),
    ("old python", "claude", "build", "python", "needs teamd on Python 3.11.4 or later"),
    ("old claude", "claude", "build", "old", "needs Claude Code 2.1.285 or later \\(found 2.1.284\\)"),
    ("no claude", "claude", "build", "none", "needs Claude Code 2.1.285 or later \\(found none\\)"),
    ("user allowlist", "claude", "build", "domains", "adds sandbox.network.allowedDomains"),
    ("user webfetch", "claude", "build", "webfetch", "allows WebFetch\\(domain:...\\)"),
    ("local mach", "claude", "build", "mach", "settings.local.json adds sandbox.network.allowMachLookup"),
    ("managed mach", "claude", "build", "managed", "managed-settings.json adds sandbox.network.allowMachLookup"),
    ("unreadable", "claude", "build", "broken", "settings.json can't be read"),
])
def test_a_browser_spawn_is_refused_with_its_reason(env, mac, monkeypatch, case, kind, mode, setup, reason):
    """Spec unit test 3: each refusal names its reason, and nothing is created."""
    claude_dir = env["home"] / ".claude"
    claude_dir.mkdir()
    if setup == "linux":
        monkeypatch.setattr(lane.sys, "platform", "linux")
    if setup == "python":
        monkeypatch.setattr(lane, "python_ok", lambda: False)
    if setup == "old":
        monkeypatch.setattr(lane, "claude_version", lambda: (2, 1, 284))
    if setup == "none":
        monkeypatch.setattr(lane, "claude_version", lambda: None)
    if setup == "domains":
        (claude_dir / "settings.json").write_text(json.dumps({"sandbox": {"network": {"allowedDomains": ["github.com"]}}}))
    if setup == "webfetch":
        (claude_dir / "settings.json").write_text(json.dumps({"permissions": {"allow": ["WebFetch(domain:example.com)"]}}))
    if setup == "mach":
        (claude_dir / "settings.local.json").write_text(json.dumps({"sandbox": {"network": {"allowMachLookup": ["*"]}}}))
    if setup == "managed":
        lane.MANAGED_SETTINGS.write_text(json.dumps({"sandbox": {"network": {"allowMachLookup": ["com.apple.x"]}}}))
    if setup == "broken":
        (claude_dir / "settings.json").write_text("{not json")
    team = lane_team(env, browser_lane=(setup != "off"))
    with pytest.raises(teamlib.RejectedMessage, match=reason):
        team.spawn("check the login page", kind, mode=mode, browser=True)
    assert team.state["workers"] == {}
    assert not (env["repo"].parent / "repo-worktrees").exists()


def test_a_browser_spawn_needs_a_strict_bool(env, mac):
    team = lane_team(env)
    for bad in ("yes", "true", 1, None):
        with pytest.raises(teamlib.RejectedMessage, match="browser must be true or false"):
            team.spawn("t", "claude", browser=bad)
        with pytest.raises(teamlib.RejectedMessage, match="browser must be true or false"):
            lead(team, "spawn", {"task": "t", "kind": "claude", "browser": bad})
    assert team.state["workers"] == {}


def test_a_browser_worker_is_recorded_and_others_are_not(env, mac, monkeypatch):
    monkeypatch.setattr(teamd.Team, "_fill_slots", lambda self: None)   # no turn: this is about the record
    team = lane_team(env)
    r = lead(team, "spawn", {"task": "check the login page", "kind": "claude", "browser": True})
    assert team.state["workers"][r["worker"]]["browser"] is True
    r = lead(team, "spawn", {"task": "write docs", "kind": "claude"})
    assert team.state["workers"][r["worker"]]["browser"] is False
    saved = json.loads((team.dir / "state.json").read_text())
    assert saved["workers"]["kaylee"]["browser"] is True


def test_team_spawn_offers_browser_as_a_boolean(env):
    from superyak_team import mcp      # here, not at the top: mcp reads SUPERYAK_TEAM_ROLE when it is imported
    spawn = [t for t in mcp.LEAD_TOOLS if t[0] == "team_spawn"][0]
    assert spawn[2]["browser"]["type"] == "boolean"
