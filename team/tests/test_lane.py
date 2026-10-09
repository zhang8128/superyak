"""Browser lanes (docs/superpowers/specs/2026-10-08-browser-lane-design.md). These run on the Pi with fakes: a patched
sys.platform, a patched Claude Code version, lsof fixtures, a fake fetch and a fake clock. The Mac acceptance run is
team/scripts/lane_acceptance.py.

Run: make check-team (from the superyak root)
"""
import base64
import fcntl
import hashlib
import http.client
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
import urllib.request
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
    monkeypatch.setattr(lane, "UNSAFE_ROOTS", ())          # the tests' own folders are under /tmp
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


# ---------- Task 2: the lane's directory, its port block and the preload ----------

@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    """lane.TMP_ROOT stands in for /tmp."""
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(lane, "TMP_ROOT", root)
    return root


@pytest.fixture
def held(env):
    """Teams whose teamd is running, as far as the registry can tell: this test holds their locks."""
    files = {}

    def hold(team_id):
        files[team_id] = lane.hold_team(team_id)
    yield hold
    for f in files.values():
        f.close()


def stat_mode(st):
    return st.st_mode & 0o7777


def test_the_lane_parent_is_private_or_refused(env, tmp_root, monkeypatch):
    """Spec unit test 6: created 0700; refused with another owner, another mode, or as a symlink."""
    parent = lane.private_parent()
    st = os.lstat(parent)
    assert parent == tmp_root / ("sy-lane-%d" % os.getuid())
    assert stat_mode(st) == 0o700 and st.st_uid == os.getuid()
    os.chmod(parent, 0o755)
    with pytest.raises(lane.LaneRefused, match="mode 755, not 700"):
        lane.private_parent()
    assert stat_mode(os.lstat(parent)) == 0o755                     # refused, never repaired
    os.rmdir(parent)
    elsewhere = env["tmp"] / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    os.symlink(elsewhere, parent)
    with pytest.raises(lane.LaneRefused, match="not a directory you own"):
        lane.private_parent()
    os.unlink(parent)
    real_uid = os.getuid()
    monkeypatch.setattr(lane.os, "getuid", lambda: real_uid + 1)   # the folder is ours, the "user" is someone else
    with pytest.raises(lane.LaneRefused, match="not a directory you own"):
        lane.private_parent()


def test_a_parent_that_vanishes_is_refused_not_raised(env, tmp_root, monkeypatch):
    """Review (M5): a process that can write /tmp may remove the parent between mkdir and lstat; teamd must get
    LaneRefused, never a raw OSError."""
    parent = tmp_root / ("sy-lane-%d" % os.getuid())
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if str(path) == str(parent):
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_lstat(path, *args, **kwargs)
    monkeypatch.setattr(lane.os, "lstat", lstat)
    with pytest.raises(lane.LaneRefused, match="unsafe lane folder .*No such file"):
        lane.private_parent()
    with pytest.raises(lane.LaneRefused):
        lane.ensure_lane("t1", "kaylee")


def test_a_lane_has_its_folders_and_the_preload_and_is_refused_as_a_symlink(env, tmp_root):
    """Spec unit test 6: the lane is refused when it is a symlink at turn time."""
    path = lane.ensure_lane("t1", "kaylee")
    assert path == tmp_root / ("sy-lane-%d" % os.getuid()) / lane.lane_hash("t1", "kaylee")
    assert len(path.name) == 10 and path.name == hashlib.sha256(b"t1/kaylee").hexdigest()[:10]
    assert sorted(p.name for p in path.iterdir()) == ["b", "npm-cache", "preload.cjs", "tmp"]
    assert stat_mode(os.lstat(path)) == 0o700
    assert "net.Server.prototype.listen" in (path / "preload.cjs").read_text()
    assert lane.ensure_lane("t1", "kaylee") == path                  # the next turn checks it again
    victim = env["tmp"] / "victim"
    victim.mkdir()
    (path / "b").rmdir()
    os.symlink(victim, path / "b")                                     # b/ swapped for a symlink
    with pytest.raises(lane.LaneRefused, match="unsafe lane"):
        lane.ensure_lane("t1", "kaylee")
    lane.remove_lane(path)
    os.symlink(victim, path)                                           # the lane itself swapped for a symlink
    with pytest.raises(lane.LaneRefused, match="unsafe lane"):
        lane.ensure_lane("t1", "kaylee")
    with pytest.raises(lane.LaneRefused, match="unsafe lane"):
        lane.remove_lane(path)
    assert victim.is_dir() and os.listdir(victim) == []


def test_teamd_never_writes_through_a_planted_link(env, tmp_root):
    """Review: every teamd write under the lane unlinks the name, then creates it with O_EXCL|O_NOFOLLOW. A preload
    swapped for a hard link, or a symlink, to someone else's file leaves that file as it was."""
    path = lane.ensure_lane("t1", "kaylee")
    victim = env["home"] / ".zshrc"
    victim.write_text("export SECRET=1\n")
    (path / "preload.cjs").unlink()
    os.link(victim, path / "preload.cjs")                              # a hard-link swap
    lane.ensure_lane("t1", "kaylee")
    assert victim.read_text() == "export SECRET=1\n"
    assert os.stat(path / "preload.cjs").st_ino != os.stat(victim).st_ino
    (path / "preload.cjs").unlink()
    os.symlink(victim, path / "preload.cjs")                           # a symlink swap
    lane.ensure_lane("t1", "kaylee")
    assert victim.read_text() == "export SECRET=1\n" and not (path / "preload.cjs").is_symlink()


def test_removal_is_fd_safe_and_refused_without_symlink_protection(env, tmp_root, monkeypatch):
    """Spec unit test 6."""
    path = lane.ensure_lane("t1", "kaylee")
    outside = env["tmp"] / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    os.symlink(outside, path / "tmp" / "link")                          # a link the worker could have made in tmp/
    assert lane.remove_lane(path) is True
    assert not os.path.lexists(path) and (outside / "keep.txt").read_text() == "keep"
    assert lane.remove_lane(path) is False                             # nothing left to remove
    path = lane.ensure_lane("t1", "kaylee")

    def unsafe_rmtree(p):
        raise AssertionError("must not be called")
    unsafe_rmtree.avoids_symlink_attacks = False
    monkeypatch.setattr(lane.shutil, "rmtree", unsafe_rmtree)
    with pytest.raises(lane.LaneRefused, match="without following symlinks"):
        lane.remove_lane(path)
    assert path.is_dir()


def test_leftovers_are_this_teams_dead_workers_by_exact_hash(env, tmp_root):
    """Spec unit test 6: team bricks never touches bricks-ux, and nothing is matched by prefix."""
    dead = lane.ensure_lane("bricks", "kaylee")
    alive = lane.ensure_lane("bricks", "wash")
    other_team = lane.ensure_lane("bricks-ux", "kaylee")
    parent = dead.parent
    (parent / (dead.name + "x")).mkdir()                                # longer name with the same start
    (parent / dead.name[:9]).mkdir()                                     # a prefix of it
    workers = {"kaylee": {"state": "done"}, "wash": {"state": "idle"}, "zoe": {"state": "stopped"}}
    assert lane.leftover_lanes("bricks", workers, lane.LIVE_STATES) == [("kaylee", dead)]
    assert alive.is_dir() and other_team.is_dir()


def test_blocks_never_overlap_and_lie_in_the_pool(env, held, monkeypatch):
    """Spec unit test 7."""
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    held("t1")
    held("t2")
    bases = [lane.allocate_block("t1", "w%d" % i) for i in range(20)]
    assert len(set(bases)) == 20
    for base in bases:
        assert lane.PORT_FIRST <= base and base + lane.BLOCK - 1 <= lane.PORT_LAST
        assert (base - lane.PORT_FIRST) % lane.BLOCK == 0
    spans = sorted((b, b + lane.BLOCK - 1) for b in bases)
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:]))
    assert lane.allocate_block("t1", "w3") == bases[3]                     # a lane keeps its block
    assert lane.allocate_block("t1", "w%d" % 20) == lane.PORT_FIRST + 20 * lane.BLOCK
    lane.release_block("t1", "w0")
    assert lane.allocate_block("t2", "kaylee") == lane.PORT_FIRST          # freed blocks are reused
    assert 48968 + lane.BLOCK - 1 == lane.PORT_LAST                        # the last block ends at 48999
    registry = teamlib.team_home() / "lane-ports.json"
    assert stat_mode(os.stat(registry)) == 0o600 and not registry.with_name("lane-ports.json.tmp").exists()


def test_a_block_something_else_uses_is_skipped(env, held, monkeypatch):
    """Spec unit test 7."""
    held("t1")
    busy = {41000, 41040}                                                 # one port in each of the first two blocks
    monkeypatch.setattr(lane, "port_free", lambda port: port not in busy)
    assert lane.allocate_block("t1", "kaylee") == 41064
    monkeypatch.setattr(lane, "port_free", lambda port: False)
    with pytest.raises(lane.LaneRefused, match="no free block of 32 loopback ports"):
        lane.allocate_block("t1", "wash")


def test_port_free_sees_a_real_listener_on_either_loopback():
    """Review (N9): a server on ::1 alone holds the port too."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    try:
        assert lane.port_free(s.getsockname()[1]) is False
    finally:
        s.close()
    try:
        s6 = socket.socket(socket.AF_INET6)
        s6.bind(("::1", 0))
    except OSError:
        pytest.skip("no IPv6 loopback here")
    s6.listen()
    try:
        assert lane.port_free(s6.getsockname()[1]) is False
    finally:
        s6.close()


def test_a_team_is_alive_while_its_teamd_holds_the_lock(env):
    """Review: liveness is a lock teamd holds for its whole life, never a pid that could be reused. A teamd that is
    just exiting gets about a second to let go (N11)."""
    assert lane.team_alive("t1") is False
    f = lane.hold_team("t1")
    assert lane.team_alive("t1") is True
    started = time.monotonic()
    with pytest.raises(lane.LaneRefused, match="another teamd already runs team t1"):
        lane.hold_team("t1")
    assert time.monotonic() - started >= 0.9
    threading.Timer(0.3, f.close).start()                                  # the old teamd exits meanwhile
    lane.hold_team("t1").close()
    assert lane.team_alive("t1") is False


def test_only_blocks_of_a_running_teamd_count_as_live(env, held, monkeypatch):
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    held("t1")
    mine = lane.allocate_block("t1", "kaylee")
    f = lane.hold_team("t2")
    theirs = lane.allocate_block("t2", "kaylee")
    assert lane.live_blocks() == [mine, theirs]
    f.close()                                                             # t2's teamd is gone
    assert lane.live_blocks() == [mine]


def test_a_dead_teamds_block_is_reclaimed_only_when_nothing_uses_it(env, held, monkeypatch):
    """Review: a block whose teamd is gone returns to the pool once its worker isn't alive and its ports are free."""
    busy = set()
    monkeypatch.setattr(lane, "port_free", lambda port: port not in busy)
    locks = [lane.hold_team(team_id) for team_id in ("gone", "restarting", "serving")]
    for team_id in ("gone", "restarting", "serving"):
        lane.allocate_block(team_id, "kaylee")                            # 41000, 41032, 41064
    for f in locks:                                                       # then their teamds die
        f.close()
    state = teamlib.team_dir("restarting")                                 # its teamd is down, its worker still alive
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"workers": {"kaylee": {"state": "idle"}}}))
    busy.add(41064 + 3)                                                   # "serving" left a server running
    held("t1")
    assert lane.allocate_block("t1", "kaylee") == 41000                   # "gone" was reclaimed
    assert lane.block_of("restarting", "kaylee") == 41032 and lane.block_of("serving", "kaylee") == 41064


def test_a_damaged_registry_refuses_lanes(env, tmp_root, held):
    """Review: a corrupt registry never forgets blocks silently."""
    held("t1")
    registry = teamlib.team_home() / "lane-ports.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    for text in ("{not json", json.dumps(["a list"]), json.dumps({"abc": {"base": "41000"}})):
        registry.write_text(text)
        with pytest.raises(lane.LaneRefused, match="is damaged"):
            lane.allocate_block("t1", "kaylee")
        assert lane.block_of("t1", "kaylee") is None
        with pytest.raises(lane.LaneRefused, match="is damaged"):
            lane.live_blocks()


def test_one_lane_per_machine_when_the_person_asks_for_it(env, held, tmp_path, monkeypatch):
    """Review: the fallback when a second lane could read the first one's endpoint lives in the registry, so it
    holds across teams, whatever max_workers says."""
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    held("t1")
    held("t2")
    (tmp_path / "cfg.json").write_text(json.dumps({"lane_one_at_a_time": True}))
    assert lane.allocate_block("t1", "kaylee") == 41000
    assert lane.allocate_block("t1", "kaylee") == 41000                   # the lane that holds it keeps it
    with pytest.raises(lane.LaneWait, match="one browser lane per machine at a time.*kaylee of team t1"):
        lane.allocate_block("t2", "wash")
    lane.release_block("t1", "kaylee")
    assert lane.allocate_block("t2", "wash") == 41000


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_preload_binds_unspecified_addresses_to_loopback(tmp_path):
    """Spec unit test 11."""
    preload = teamlib.package_dir() / "lane" / "preload.cjs"
    sock = tmp_path / "s.sock"
    script = r"""
    const net = require('net'), http = require('http');
    const cases = {
      'listen(0)': s => s.listen(0), "listen(0, '0.0.0.0')": s => s.listen(0, '0.0.0.0'),
      "listen(0, '::')": s => s.listen(0, '::'), 'listen()': s => s.listen(), 'listen(cb)': s => s.listen(() => {}),
      'listen({port: 0})': s => s.listen({port: 0}), "listen({port: 0, host: '::'})": s => s.listen({port: 0, host: '::'}),
      'listen(0, backlog)': s => s.listen(0, 5), 'http listen(0)': s => s.listen(0), "explicit '127.0.0.1'": s => s.listen(0, '127.0.0.1'),
      "listen(0, '0')": s => s.listen(0, '0'), "listen(0, '::0')": s => s.listen(0, '::0'),
      "listen(0, '0:0:0:0:0:0:0:0')": s => s.listen(0, '0:0:0:0:0:0:0:0'),
    };
    const out = {};
    const all = Object.entries(cases).map(([name, start]) => new Promise(done => {
      const s = name.startsWith('http') ? http.createServer() : net.createServer();
      start(s);
      s.on('listening', () => { out[name] = s.address().address; s.close(done); });
    }));
    all.push(new Promise(done => { const u = net.createServer().listen(process.argv[1], function () { out.unix = this.address(); this.close(done); }); }));
    Promise.all(all).then(() => console.log(JSON.stringify(out)));
    """
    r = subprocess.run(["node", "--require", str(preload), "-e", script, str(sock)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    unix, explicit = out.pop("unix"), out.pop("explicit '127.0.0.1'")
    assert set(out.values()) == {"127.0.0.1"}, out
    assert len(out) == 12 and unix == str(sock) and explicit == "127.0.0.1"


# ---------- Task 2, fix round 1 ----------

def test_removal_and_lane_text_check_the_parent_too(env, tmp_root):
    """Fix 1: a parent swapped for a symlink to a folder holding <h> must not let removal reach X/<h>."""
    path = lane.ensure_lane("t1", "kaylee")
    parent = path.parent
    x = env["tmp"] / "X"
    os.rename(parent, x)
    os.symlink(x, parent)
    with pytest.raises(lane.LaneRefused):
        lane.remove_lane(path)
    assert (x / path.name / "b").is_dir()
    with pytest.raises(lane.LaneRefused):
        lane.lane_text(path / "b")


def test_lane_text_refuses_a_path_outside_the_parent(env, tmp_root):
    """Fix 7."""
    lane.private_parent()
    with pytest.raises(lane.LaneRefused):
        lane.lane_text(env["tmp"] / "elsewhere")


@pytest.mark.parametrize("damage", ["bytes", "dir", "unreadable"])
def test_an_unreadable_registry_refuses_instead_of_raising(env, held, damage):
    """Fix 2."""
    held("t1")
    registry = teamlib.team_home() / "lane-ports.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    if damage == "bytes":
        registry.write_bytes(b"\xff\xfe\x00")
    elif damage == "dir":
        registry.mkdir()
    else:
        registry.write_text("{}")
        os.chmod(registry, 0)
    try:
        with pytest.raises(lane.LaneRefused):
            lane.allocate_block("t1", "kaylee")
        with pytest.raises(lane.LaneRefused):
            lane.live_blocks()
        assert lane.block_of("t1", "kaylee") is None
        assert lane.release_block("t1", "kaylee") is None                  # fix 5: cleanup never raises
    finally:
        if damage == "unreadable":
            os.chmod(registry, 0o600)


def test_lock_and_write_failures_refuse(env, held, monkeypatch):
    """Fix 2: the lock, the team lock and the registry write."""
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    held("t1")
    lane.allocate_block("t1", "w0")
    home = teamlib.team_home()
    real_replace = os.replace
    monkeypatch.setattr(lane.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError(13, "Permission denied")))
    with pytest.raises(lane.LaneRefused):
        lane.allocate_block("t1", "w1")
    monkeypatch.setattr(lane.os, "replace", real_replace)
    (home / "lane-teams" / "t3.lock").mkdir()
    with pytest.raises(lane.LaneRefused):
        lane.hold_team("t3")
    (home / "lane-ports.lock").unlink()
    (home / "lane-ports.lock").mkdir()
    with pytest.raises(lane.LaneRefused):
        lane.allocate_block("t1", "w2")


def test_a_bad_config_or_missing_preload_refuses(env, tmp_root, held, tmp_path, monkeypatch):
    """Fix 6."""
    held("t1")
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    (tmp_path / "cfg.json").write_text("{bad")
    with pytest.raises(lane.LaneRefused):
        lane.allocate_block("t1", "kaylee")
    monkeypatch.setattr(teamlib, "package_dir", lambda: tmp_path / "nowhere")
    with pytest.raises(lane.LaneRefused):
        lane.ensure_lane("t1", "kaylee")


# ---------- Task 3: the worker's sandbox settings and environment ----------

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"


def test_without_a_lane_nothing_changes(env, monkeypatch):
    """Spec unit test 1 (the team half; agent/tests/test_runs.py has the rest). The snapshots were taken from the code
    before lanes existed, with HOME=/home/u."""
    monkeypatch.setenv("HOME", "/home/u")
    build = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo")
    collab = workers.claude_sandbox_settings("/r/room", "collab", True, repo="/r/repo")
    assert json.dumps(build, indent=1) + "\n" == (SNAPSHOTS / "settings-build.json").read_text()
    assert json.dumps(collab, indent=1) + "\n" == (SNAPSHOTS / "settings-collab.json").read_text()
    assert workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo", lane=None) == build
    cmd = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "kaylee", "/r/wt", "go", repo="/r/repo")
    wdir = teamlib.team_dir("t1") / "workers" / "kaylee"
    assert cmd == ["claude", "-p", "go", "--output-format", "stream-json", "--verbose", "--model", "opus",
                   "--permission-mode", "dontAsk", "--settings", str(wdir / "settings.json"),
                   "--mcp-config", str(wdir / "mcp.json")]
    assert (wdir / "settings.json").read_text() == json.dumps(build)


def test_a_lane_adds_exactly_its_network_block_and_paths(env, monkeypatch):
    """Spec unit test 2: and neither the lane root nor b/ is writable."""
    monkeypatch.setenv("HOME", "/home/u")
    uid = os.getuid()
    path = "/tmp/sy-lane-%d/0123456789" % uid
    plain = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo")
    laned = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo", lane=path)
    assert laned["permissions"] == plain["permissions"]
    assert {k: v for k, v in laned["sandbox"].items() if k not in ("network", "filesystem")} == \
        {k: v for k, v in plain["sandbox"].items() if k != "filesystem"}
    assert laned["sandbox"]["network"] == {"allowedDomains": [], "strictAllowlist": True, "allowLocalBinding": True,
                                           "allowUnixSockets": [path + "/tmp"]}
    fs, before = laned["sandbox"]["filesystem"], plain["sandbox"]["filesystem"]
    assert fs["allowWrite"] == before["allowWrite"] + [path + "/tmp", path + "/npm-cache"]
    assert fs["allowRead"] == before["allowRead"] + [path + "/tmp", path + "/npm-cache", path + "/preload.cjs"]
    assert fs["denyRead"] == before["denyRead"] + ["/tmp/sy-lane-%d" % uid, "/private/tmp/claude-%d" % uid]
    assert fs["denyWrite"] == before["denyWrite"]
    assert path not in fs["allowWrite"] and path + "/b" not in fs["allowWrite"]
    assert not any(p.startswith(path + "/b") for p in fs["allowWrite"] + fs["allowRead"])
    cmd = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "kaylee", "/r/wt", "go", repo="/r/repo", lane=path)
    written = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
    assert written == laned


def test_a_browser_workers_environment(env, monkeypatch, tmp_path):
    """Spec unit test 5 (the worker's half): the lane variables, NODE_OPTIONS and the endpoint, and none of the
    agent sockets; a worker without a lane gets exactly what it got before."""
    path = Path("/tmp/sy-lane-%d/0123456789" % os.getuid())
    endpoint = "ws://127.0.0.1:41031/" + "ab" * 32
    extra = lane.worker_env(path, 41000, endpoint)
    assert extra == {"CLAUDE_CODE_TMPDIR": str(path / "tmp"), "npm_config_cache": str(path / "npm-cache"),
                     "SUPERYAK_BROWSER_LANE": "1", "SUPERYAK_LANE_PORT_BASE": "41000",
                     "SUPERYAK_LANE_PORT_COUNT": "32", "PW_TEST_CONNECT_WS_ENDPOINT": endpoint,
                     "NODE_OPTIONS": "--require " + str(path / "preload.cjs"),
                     "BASH_DEFAULT_TIMEOUT_MS": "600000", "BASH_MAX_TIMEOUT_MS": "2400000"}
    for name, value in (("SSH_AUTH_SOCK", "/tmp/agent.sock"), ("GPG_AGENT_INFO", "/tmp/gpg"),
                        ("DOCKER_HOST", "unix:///var/run/docker.sock"), ("NODE_OPTIONS", "--inspect")):
        monkeypatch.setenv(name, value)
    seen = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen.append(kwargs["env"])
    monkeypatch.setattr(workers.subprocess, "Popen", FakePopen)
    workers.launch(["claude", "-p", "x"], tmp_path, tmp_path / "w1", dict(extra, ENGRAM_PROJECT_ROOT="/r"),
                   drop_env=lane.DROP_ENV)
    workers.launch(["claude", "-p", "x"], tmp_path, tmp_path / "w2", {"ENGRAM_PROJECT_ROOT": "/r"})
    browser, plain = seen
    assert not {"SSH_AUTH_SOCK", "GPG_AGENT_INFO", "DOCKER_HOST"} & set(browser)
    assert {k: browser[k] for k in extra} == extra                        # NODE_OPTIONS is the preload, not teamd's
    assert plain == dict(os.environ, ENGRAM_PROJECT_ROOT="/r", VOICE_NOTIFY_MUTE="1", SUPERYAK_RUN="1")

# ---------- Task 4: the listener check (D9, D10, D11) ----------

CONTROL_CENTER = "/System/Library/CoreServices/ControlCenter.app/Contents/MacOS/ControlCenter"
HEADER_PID = ("Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rhiwat  shiwat    pid   "
              "epid state  options           gencnt    flags   flags1 usscnt rtncnt fltrs")
HEADER_PROCESS = ("Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rxbytes      "
                  "txbytes rhiwat  shiwat  process:pid  state  options           gencnt    flags   flags1 usscnt "
                  "rtncnt fltrs")
# The Mac's listeners: (proto, local address, state, pid, command). Root's cupsd and launchd (Remote Login, held by
# pid 1) are here too: netstat sees them, which lsof run as the user can't.
SOCKETS = [
    ("tcp46", "*.7000", "LISTEN", 501, "ControlCenter"), ("tcp46", "*.5000", "LISTEN", 501, "ControlCenter"),
    ("tcp4", "*.49152", "LISTEN", 612, "rapportd"), ("tcp6", "*.49153", "LISTEN", 612, "rapportd"),
    ("tcp4", "127.0.0.1.631", "LISTEN", 220, "cupsd"), ("tcp6", "::1.631", "LISTEN", 220, "cupsd"),
    ("tcp46", "*.22", "LISTEN", 1, "launchd"),
    ("tcp4", "100.101.102.103.8080", "LISTEN", 333, "tailscaled"),       # bound to the tailnet only: unreachable
    ("tcp4", "127.0.0.1.41000", "LISTEN", 900, "node"), ("tcp6", "::1.41001", "LISTEN", 901, "node"),
    ("tcp4", "127.0.0.1.49500", "127.0.0.1.41000", 902, "node"),         # a connection, not a listener
]
EXE = {501: CONTROL_CENTER, 612: "/usr/libexec/rapportd", 220: "/usr/sbin/cupsd", 1: "/sbin/launchd",
       333: "/opt/homebrew/bin/tailscaled", 900: "/opt/homebrew/bin/node", 901: "/opt/homebrew/bin/node",
       777: "/opt/homebrew/bin/ollama"}
APPROVED = [CONTROL_CENTER, "/usr/libexec/rapportd", "/usr/sbin/cupsd", "/sbin/launchd"]


def netstat_text(sockets, header=HEADER_PID):
    """netstat -anv -p tcp, in the old (pid column) or the new (process:pid column) format."""
    named = "process:pid" in header
    lines = ["Active Internet connections (including servers)", header]
    for proto, local, state, pid, command in sockets:
        foreign, state = ("*.*", state) if state == "LISTEN" else (state, "ESTABLISHED")
        who = "%s:%d" % (command, pid) if named else "%d" % pid
        extra = "    131072  131072  %s  0 0x0100 0x00000106 0x0000000000c5a1d 0x00000000 0x00000800 1 0 000001" % who
        if named:
            extra = "  1024  2048  131072  131072  %s  0x0100 0x00000106 0x0000000000c5a1d 0x00000000 0x00000800 1 0 000001" % who
        lines.append("%-6s     0      0  %-22s %-22s %-12s%s" % (proto, local, foreign, state, extra))
    return "\n".join(lines) + "\n"


def lsof_text(pairs):
    """lsof -nP -iTCP -sTCP:LISTEN -F pn for the user's own listeners."""
    out = []
    for pid, address in pairs:
        out += ["p%d" % pid, "f20", "n%s" % address]
    return "\n".join(out) + "\n"


class Ran:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def listeners(env, held, monkeypatch):
    """A Mac's listeners: netstat prints `state["sockets"]` (in `state["header"]`'s format), lsof the user's own,
    proc_pidpath maps pids to executables, and the block at 41000 is a live lane's (this test holds t1's lock)."""
    state = {"sockets": list(SOCKETS), "header": HEADER_PID, "netstat_rc": 0, "netstat": None,
             "lsof": [(900, "127.0.0.1:41000"), (901, "[::1]:41001")], "lsof_rc": 0, "exe": dict(EXE),
             "lsof_rounds": [], "netstat_rounds": [], "lsof_stderr": "",   # one-off answers, round by round
             "environ": {}}                              # pid -> the environment the _environ seam reports

    def run(cmd, timeout=60):
        if cmd[0].endswith("netstat"):
            sockets = state["netstat_rounds"].pop(0) if state["netstat_rounds"] else state["sockets"]
            text = state["netstat"] if state["netstat"] is not None else netstat_text(sockets, state["header"])
            return Ran(state["netstat_rc"], text)
        if cmd[0].endswith("lsof"):
            pairs = state["lsof_rounds"].pop(0) if state["lsof_rounds"] else state["lsof"]
            return Ran(state["lsof_rc"], lsof_text(pairs), state["lsof_stderr"])
        raise AssertionError(cmd)
    monkeypatch.setattr(lane, "_run", run)
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: "/usr/sbin/" + name)
    monkeypatch.setattr(lane, "pid_path", lambda pid: state["exe"].get(pid))
    monkeypatch.setattr(lane, "_environ", lambda pid: state["environ"].get(pid))
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    held("t1")
    assert lane.allocate_block("t1", "kaylee") == 41000
    approve(APPROVED)
    return state


def approve(paths):
    lane.approved_path().parent.mkdir(parents=True, exist_ok=True)
    lane.approved_path().write_text(json.dumps(paths))


@pytest.mark.parametrize("header", [HEADER_PID, HEADER_PROCESS])
def test_lane_ports_and_approved_apple_programs_pass(listeners, header):
    """Spec unit test 8: lane ports pass; an approved Apple program passes; in both of netstat's formats."""
    listeners["header"] = header
    assert lane.listeners_ok() == (True, [])


def test_an_approved_program_passes_on_any_port(listeners):
    """D11's test case: rapportd takes a new port each time it starts."""
    listeners["sockets"] += [("tcp4", "*.51234", "LISTEN", 612, "rapportd"), ("tcp6", "*.61000", "LISTEN", 612, "rapportd")]
    assert lane.listeners_ok() == (True, [])


def test_a_program_not_on_the_list_fails_on_any_port_and_is_named(listeners):
    """D11's test case and spec unit test 8: the lead's message names each one by command name and port."""
    listeners["sockets"] += [("tcp4", "127.0.0.1.11434", "LISTEN", 777, "ollama"), ("tcp46", "*.11435", "LISTEN", 777, "ollama")]
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["ollama (pid 777) listens on port 11434 (/opt/homebrew/bin/ollama)",
                                   "ollama (pid 777) listens on port 11435 (/opt/homebrew/bin/ollama)"]
    approve(APPROVED[:1])
    ok, problems = lane.listeners_ok()
    assert any("rapportd (pid 612) listens on port 49152 (/usr/libexec/rapportd)" == p for p in problems)


@pytest.mark.parametrize("address", ["*.41002", "192.168.1.20.41002", "::.41002", "fe80::1%lo0.41002",
                                     "100.101.102.103.41002"])
def test_a_lane_process_listening_beyond_loopback_fails(listeners, address):
    """Spec unit test 8: on *, a LAN, link-local or tailnet address, a lane port fails, reachable or not."""
    listeners["sockets"].append(("tcp46" if address.startswith("*") else "tcp4", address, "LISTEN", 900, "node"))
    ok, problems = lane.listeners_ok()
    assert not ok and len(problems) == 1 and "port 41002, beyond loopback" in problems[0]


@pytest.mark.parametrize("counted", ["*.9002", "::ffff:127.0.0.1.9003", "fe80::1%lo0.9004", "[weird].9005"])
def test_a_listener_bound_to_one_other_address_does_not_count(listeners, counted):
    """The reachability ruling: neither the worker nor the broker can reach a socket bound only to the tailnet or the
    LAN, so it neither blocks a lane nor needs approval. A wildcard counts, and so do an IPv4-mapped loopback address,
    anything scoped to lo0 and an address the check can't read (N8)."""
    listeners["sockets"] += [("tcp4", "100.101.102.103.9000", "LISTEN", 777, "ollama"),
                             ("tcp4", "192.168.1.20.9001", "LISTEN", 777, "ollama"),
                             ("tcp6", "fe80::1%en0.9006", "LISTEN", 777, "ollama")]
    assert lane.listeners_ok() == (True, [])
    listeners["sockets"].append(("tcp6", counted, "LISTEN", 777, "ollama"))
    ok, problems = lane.listeners_ok()
    assert not ok and len(problems) == 1 and "ollama (pid 777) listens on port 900" in problems[0]


def test_a_listener_whose_program_cant_be_identified_fails(listeners):
    """D11: a counted listener with no executable path fails, in a lane's block too."""
    listeners["exe"].pop(612)
    ok, problems = lane.listeners_ok()
    assert not ok and "? (pid 612) listens on * port 49152, and its program can't be identified" in problems
    listeners["header"] = HEADER_PROCESS                                    # the newer netstat names it
    assert "rapportd (pid 612) listens on * port 49152, and its program can't be identified" in lane.listeners_ok()[1]
    listeners["exe"][612] = "/usr/libexec/rapportd"
    listeners["exe"].pop(900)
    ok, problems = lane.listeners_ok()
    assert problems == ["node (pid 900) listens on 127.0.0.1 port 41000, and its program can't be identified"]


def test_a_root_listener_is_seen(listeners):
    """The spec's reason for netstat: root's listeners count. cupsd on 631 passes only because it is approved."""
    approve([p for p in APPROVED if p != "/usr/sbin/cupsd"])
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["cupsd (pid 220) listens on port 631 (/usr/sbin/cupsd)"]


def test_netstat_or_lsof_failing_fails(listeners, monkeypatch):
    """Spec unit test 8: an lsof failure fails, and so does a netstat failure."""
    listeners["netstat_rc"] = 1
    assert lane.listeners_ok()[0] is False
    listeners["netstat_rc"] = 0
    listeners["lsof_rc"] = 2
    assert lane.listeners_ok() == (False, ["lsof failed, so the listener check fails closed"])
    listeners["lsof_rc"], listeners["lsof"] = 1, []                        # lsof found nothing of the user's: fine
    assert lane.listeners_ok() == (True, [])
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: None)        # nothing could run at all
    assert lane.listeners_ok()[0] is False
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: None)
    assert lane.listeners_ok()[0] is False


@pytest.mark.parametrize("text", [
    "",
    "Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rhiwat  shiwat  epid\n",
    "Proto Recv-Q  Local Address          Foreign Address        (state)  pid\n",
    HEADER_PID + "\ntcp4       0      0  127.0.0.1.41000        *.*                    LISTEN\n",
    HEADER_PID + "\ntcp4       0      0  127.0.0.1.41000        *.*                    LISTEN  131072  131072  -\n",
    HEADER_PROCESS + "\ntcp4  0  0  127.0.0.1.41000  *.*  LISTEN  1  2  131072  131072  node:pid\n",
    # full-length rows (netstat_text makes them), so the pid check itself is what refuses
    netstat_text([("tcp4", "127.0.0.1.41000", "LISTEN", 4242, "node")], HEADER_PROCESS).replace("4242", "pid"),
    netstat_text([("tcp4", "127.0.0.1.41000", "LISTEN", 4242, "node")], HEADER_PID).replace("4242", "-"),
    netstat_text([("tcp4", "garbage", "LISTEN", 4242, "node")], HEADER_PID),
    netstat_text([("tcp4", "garbage", "LISTEN", 4242, "node")], HEADER_PROCESS),
    netstat_text([("tcp", "127.0.0.1.41000", "LISTEN", 4242, "node")], HEADER_PID),     # a bare "tcp" proto
    netstat_text([("tcp4", "127.0.0.1.41000", "LISTEN", 4242, "node")], HEADER_PID.replace("pid ", "pid process:pid ", 1)),
])
def test_a_netstat_it_doesnt_recognise_fails_closed(listeners, text):
    listeners["netstat"] = text
    ok, problems = lane.listeners_ok()
    assert not ok and "netstat failed" in problems[0]


def test_a_listener_lsof_sees_and_netstat_doesnt_fails(listeners):
    """The cross-check: any (pid, port) of the user's own that netstat lacks, in both of two rounds, means the
    enumeration can't be trusted."""
    listeners["lsof"].append((905, "127.0.0.1:41003"))
    ok, problems = lane.listeners_ok()
    assert not ok and problems == [
        "lsof shows pid 905 listening on port 41003, which netstat doesn't list (a socket several processes share, "
        "such as a pre-fork server or inherited descriptors, fails until only one holds it)"]


def test_a_socket_that_opens_between_netstat_and_lsof_doesnt_fail_the_check(listeners):
    """Review (N2): a socket that appeared after netstat read the table is gone from the second round."""
    listeners["lsof_rounds"] = [listeners["lsof"] + [(906, "127.0.0.1:41004")]]
    assert lane.listeners_ok() == (True, [])


def test_a_dead_teamds_block_is_not_a_lane(listeners, monkeypatch):
    held_lock = lane._team_lock("t1")
    monkeypatch.setattr(lane, "team_alive", lambda team_id: False)
    ok, problems = lane.listeners_ok()
    assert held_lock.exists() and not ok and len(problems) == 2
    assert all("node (pid 90" in p and "(/opt/homebrew/bin/node)" in p for p in problems)


@pytest.mark.parametrize("host, loopback", [
    ("::1", True), ("127.0.0.1", True), ("127.0.0.2", True), ("127.255.255.254", True),
    ("fe80::1", False), ("fe80::1%lo0", False), ("::", False), ("*", False), ("0.0.0.0", False),
    ("100.101.102.103", False), ("fd7a:115c:a1e0::1", False), ("192.168.1.20", False), ("::ffff:127.0.0.1", False),
])
def test_only_127_8_and_ipv6_loopback_count_as_loopback(host, loopback):
    """Spec unit test 8: ::1 and 127.0.0.2 count; fe80::1, :: and a tailnet address don't."""
    assert lane.is_loopback(host) is loopback


def test_a_process_name_with_spaces_or_colons_keeps_its_own_pid():
    """Review (N1): the process:pid column is everything between the columns before and after it, and the pid is its
    last :digits. A name with spaces parses, and a crafted "x:1 y:777" is pid 777, never 1."""
    text = netstat_text([("tcp4", "127.0.0.1.9000", "LISTEN", 4321, "Google Chrome He"),
                         ("tcp4", "127.0.0.1.9001", "LISTEN", 777, "x:1 y")], HEADER_PROCESS)
    assert lane.parse_netstat(text) == [
        {"pid": 4321, "command": "Google Chrome He", "host": "127.0.0.1", "port": 9000},
        {"pid": 777, "command": "x:1 y", "host": "127.0.0.1", "port": 9001}]


@pytest.mark.parametrize("header", [HEADER_PID, HEADER_PROCESS])
def test_netstat_is_parsed_with_ipv6_in_both_formats(header):
    """Addresses end in .<port>: 127.0.0.1.631, *.5000, ::1.631 and fe80::1%lo0.631, on tcp4, tcp6 and tcp46."""
    got = lane.parse_netstat(netstat_text(SOCKETS + [("tcp6", "fe80::1%lo0.631", "LISTEN", 220, "cupsd")], header))
    command = (lambda name: name) if header == HEADER_PROCESS else (lambda name: "")
    assert got == [{"pid": pid, "command": command(name), "host": local.rpartition(".")[0], "port": int(local.rpartition(".")[2])}
                   for proto, local, state, pid, name in SOCKETS + [("tcp6", "fe80::1%lo0.631", "LISTEN", 220, "cupsd")]
                   if state == "LISTEN"]
    assert {(g["host"], g["port"]) for g in got} >= {("127.0.0.1", 631), ("*", 5000), ("::1", 631), ("fe80::1%lo0", 631)}


def test_lsof_output_is_parsed_with_ipv6():
    assert lane.parse_lsof(lsof_text([(900, "127.0.0.1:41000"), (901, "[::1]:41001"), (501, "*:7000")])) == [
        {"pid": 900, "command": "", "host": "127.0.0.1", "port": 41000},
        {"pid": 901, "command": "", "host": "::1", "port": 41001},
        {"pid": 501, "command": "", "host": "*", "port": 7000}]


@pytest.mark.parametrize("entry, reason", [
    ("/opt/homebrew/bin/ollama", "only Apple programs"),                              # D11's test case
    ("/usr/bin/python3", "only Apple programs"),
    ("/usr/libexec/../../opt/homebrew/bin/ollama", "only Apple programs"),
    ("usr/libexec/rapportd", "only Apple programs"),
    ("/System/Library/Frameworks/Python.framework/Versions/3.9/bin/python3.9", "an interpreter is never approved"),
    ("/usr/libexec/perl5.30", "an interpreter is never approved"),
    ("/usr/sbin/zsh", "an interpreter is never approved"),
    ("/System/Volumes/Data/opt/homebrew/bin/ollama", "not on the sealed system volume"),
    ("/System/Volumes/Data/Users/andy/bin/tool", "not on the sealed system volume"),
    ("/usr/libexec/cups/backend/ipp", "not on the sealed system volume"),
    ("/System/Library/Caches/com.apple.x/helper", "not on the sealed system volume"),
    ("/System/Library/AssetsV2/com.apple.MobileAsset/x/bin/helper", "not on the sealed system volume"),
    ("/System/Library/Speech/Voices/helper", "not on the sealed system volume"),
    ("/System/Library/CoreServices/CoreTypes.bundle/Contents/Library/helper", "not on the sealed system volume"),
    ({"executable": "/usr/libexec/rapportd", "port": 49152}, "only Apple programs"),  # D10's old shape
    (49152, "only Apple programs"),
])
def test_the_approved_list_holds_only_apple_program_paths(env, entry, reason):
    """D10 and D11: a bad entry refuses the whole list when it is loaded, so the check fails closed."""
    approve(["/usr/libexec/rapportd", entry])
    with pytest.raises(lane.LaneWait, match=reason):
        lane.load_approved()
    ok, problems = lane.listeners_ok()
    assert not ok and reason in problems[0]


def test_the_approved_list_must_be_a_readable_list(env):
    lane.approved_path().parent.mkdir(parents=True, exist_ok=True)
    assert lane.load_approved() == set()                                              # no file: nothing approved
    for text in ("{not json", json.dumps({"executable": "/usr/libexec/rapportd"})):
        lane.approved_path().write_text(text)
        with pytest.raises(lane.LaneWait):
            lane.load_approved()
    approve(["/usr/libexec/rapportd", "/sbin/launchd", CONTROL_CENTER, "/usr/sbin/sshd"])
    assert lane.load_approved() == {"/usr/libexec/rapportd", "/sbin/launchd", CONTROL_CENTER, "/usr/sbin/sshd"}


# ---------- Task 4, fix round 1 ----------

REAL_RUN = lane._run


def test_bytes_that_are_not_utf8_fail_the_check_closed_and_never_raise(listeners, monkeypatch):
    """Critical 1: a 16-byte process name cut inside a multibyte character is not UTF-8. The real _run reads it, and
    listeners_ok answers (False, ...) instead of raising past Task 8's watch."""
    text = netstat_text([("tcp4", "127.0.0.1.9000", "LISTEN", 4321, "aaaa")], HEADER_PROCESS)
    script = "import sys; sys.stdout.buffer.write(%r.replace(b'aaaa', b'a' * 15 + b'\\xc3'))" % text.encode()

    def run(cmd, timeout=60):
        if cmd[0].endswith("netstat"):
            return REAL_RUN([sys.executable, "-c", script])
        return Ran(0, lsof_text([]))
    monkeypatch.setattr(lane, "_run", run)
    ok, problems = lane.listeners_ok()
    assert ok is False and problems


def test_a_parse_error_fails_the_check_closed(listeners, monkeypatch):
    monkeypatch.setattr(lane, "_netstat_rows", lambda text: (_ for _ in ()).throw(ValueError("boom")))
    ok, problems = lane.listeners_ok()
    assert ok is False and len(problems) == 1


def test_a_netstat_row_it_cannot_read_is_named_as_the_row_not_the_header(listeners):
    listeners["netstat"] = netstat_text([("tcp4", "garbage", "LISTEN", 4242, "node")], HEADER_PID)
    ok, problems = lane.listeners_ok()
    assert not ok and "row" in problems[0] and "header" not in problems[0]


def test_a_process_name_with_a_line_separator_is_one_row():
    text = netstat_text([("tcp4", "127.0.0.1.9000", "LISTEN", 4321, "a\x0bb c")], HEADER_PROCESS)
    assert lane.parse_netstat(text) == [{"pid": 4321, "command": "a b c", "host": "127.0.0.1", "port": 9000}]


def test_the_sealed_volume_is_checked_on_a_mac_only(env, monkeypatch):
    approve(["/usr/libexec/rapportd"])
    devices = {"/usr/sbin": 1, "/usr/libexec/rapportd": 1}
    monkeypatch.setattr(lane, "_device", lambda path: devices[path])
    assert lane.load_approved() == {"/usr/libexec/rapportd"}                     # Linux: skipped
    monkeypatch.setattr(lane.sys, "platform", "darwin")
    assert lane.load_approved() == {"/usr/libexec/rapportd"}
    devices["/usr/libexec/rapportd"] = 2                                         # another volume
    with pytest.raises(lane.LaneWait, match="not on the sealed system volume"):
        lane.load_approved()


def test_round_two_reads_netstat_again(listeners):
    """Review: a pair lsof sees that round 2's netstat lists is no failure."""
    listeners["exe"][905] = "/opt/homebrew/bin/node"
    listeners["lsof"].append((905, "127.0.0.1:41003"))
    listeners["netstat_rounds"] = [list(SOCKETS), SOCKETS + [("tcp4", "127.0.0.1.41003", "LISTEN", 905, "node")]]
    assert lane.listeners_ok() == (True, [])


def test_lsofs_own_failures_fail_the_check(listeners, monkeypatch):
    real_run, real_which = lane._run, lane.shutil.which
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: None if name == "lsof" else real_which(name, path=path))
    assert lane.listeners_ok() == (False, ["lsof failed, so the listener check fails closed"])
    monkeypatch.setattr(lane.shutil, "which", real_which)
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: None if cmd[0].endswith("lsof") else real_run(cmd, timeout))
    assert lane.listeners_ok() == (False, ["lsof failed, so the listener check fails closed"])
    monkeypatch.setattr(lane, "_run", real_run)
    listeners["lsof_rc"], listeners["lsof_stderr"] = 1, "lsof: WARNING: can't stat() fuse file system"
    assert lane.listeners_ok() == (False, ["lsof failed, so the listener check fails closed"])


def test_the_cross_check_message_mentions_shared_sockets(listeners):
    listeners["lsof"].append((905, "127.0.0.1:41003"))
    assert "several processes share" in lane.listeners_ok()[1][0]


def lane_tmp():
    return str(lane._parent_path() / lane.lane_hash("t1", "kaylee") / "tmp")


def test_a_lane_process_listening_beyond_loopback_fails_on_any_port(listeners):
    """Important 3: a lane process is a pid whose environment holds CLAUDE_CODE_TMPDIR=<a live lane's tmp>."""
    listeners["environ"][902] = ["HOME=/h", "CLAUDE_CODE_TMPDIR=" + lane_tmp()]
    listeners["exe"][902] = "/opt/homebrew/bin/node"
    listeners["sockets"].append(("tcp4", "*.9100", "LISTEN", 902, "node"))
    ok, problems = lane.listeners_ok()
    assert not ok and len(problems) == 1 and "port 9100" in problems[0] and "lane" in problems[0]
    listeners["sockets"][-1] = ("tcp4", "192.168.1.20.9100", "LISTEN", 902, "node")
    ok, problems = lane.listeners_ok()             # a lane's process exposes the app to the network, reachable or not
    assert not ok and len(problems) == 1 and "192.168.1.20 port 9100, beyond loopback" in problems[0]
    listeners["sockets"][-1] = ("tcp4", "127.0.0.1.9100", "LISTEN", 902, "node")
    ok, problems = lane.listeners_ok()             # on loopback it is an ordinary unapproved listener
    assert problems == ["node (pid 902) listens on port 9100 (/opt/homebrew/bin/node)"]


ELSEWHERE = [("tcp4", "192.168.1.5.3000"), ("tcp4", "100.101.102.104.3000"), ("tcp6", "fd00::5.3000"),
             ("tcp6", "2001:db8::5.3000"), ("tcp6", "fe80::1%en0.3000")]


@pytest.mark.parametrize("proto, address", ELSEWHERE)
def test_a_lane_process_fails_on_every_non_loopback_address_and_others_are_skipped(listeners, proto, address):
    listeners["exe"][902] = "/opt/homebrew/bin/node"
    listeners["sockets"].append((proto, address, "LISTEN", 902, "node"))
    assert lane.listeners_ok() == (True, [])                                      # not a lane's process: unreachable
    listeners["environ"][902] = ["CLAUDE_CODE_TMPDIR=" + lane_tmp()]
    ok, problems = lane.listeners_ok()
    host, _, port = address.rpartition(".")
    assert not ok and len(problems) == 1 and "%s port %s, beyond loopback" % (host, port) in problems[0]


def test_a_non_lane_process_on_a_lan_address_is_still_skipped(listeners):
    listeners["environ"][777] = ["CLAUDE_CODE_TMPDIR=/tmp/elsewhere/tmp"]
    listeners["sockets"].append(("tcp4", "192.168.1.20.9100", "LISTEN", 777, "ollama"))
    assert lane.listeners_ok() == (True, [])


def test_kern_procargs2_is_read_past_argv_to_the_environment():
    raw = (2).to_bytes(4, sys.byteorder) + b"/opt/homebrew/bin/node\0\0\0node\0-e\0A=1\0CLAUDE_CODE_TMPDIR=/x\0\0junk"
    assert lane._parse_procargs2(raw) == ["A=1", "CLAUDE_CODE_TMPDIR=/x"]
    assert lane._parse_procargs2(b"\0") == []


def test_environ_reads_a_real_process_on_linux_and_none_for_a_missing_one():
    if sys.platform == "linux":
        assert any(item.startswith("PATH=") for item in lane._environ(os.getpid()) or [])
    assert lane._environ(2 ** 22 + 12345) is None


@pytest.mark.parametrize("host, counts", [("::0", True), ("0:0:0:0:0:0:0:0", True), ("::ffff:0.0.0.0", True),
                                          ("::ffff:127.0.0.1", True), ("::ffff:192.168.1.1", False),
                                          ("fe80::1", False), ("100.101.102.103", False)])
def test_reachable_reads_addresses_not_strings(host, counts):
    assert lane.reachable(host) is counts


def test_a_nul_in_the_approved_list_never_raises(listeners, monkeypatch):
    monkeypatch.setattr(lane.sys, "platform", "darwin")
    monkeypatch.setattr(lane, "_device", lambda path: os.lstat(path).st_dev if "\0" in path else 1)
    approve(APPROVED + ["/usr/libexec/\0rapportd"])
    ok, problems = lane.listeners_ok()
    assert ok is False and problems


def test_a_nul_in_a_registry_team_never_raises(listeners):
    with lane._registry_lock():
        data = lane._read_registry()
        data["x" * 10] = {"base": 41032, "team": "a\0b", "worker": "w"}
        lane._write_registry(data)
    assert lane.team_alive("a\0b") is False
    assert lane.listeners_ok()[0] in (True, False)


def test_a_nul_in_a_mac_path_is_not_sealed(monkeypatch):
    monkeypatch.setattr(lane.sys, "platform", "darwin")
    assert lane._sealed("/usr/libexec/a\0b") == "not on the sealed system volume"


@pytest.mark.parametrize("base", [600, 41001, 49000, 48969, -32])
def test_a_registry_base_outside_the_pool_is_damaged(listeners, base):
    with lane._registry_lock():
        data = lane._read_registry()
        data["y" * 10] = {"base": base, "team": "t1", "worker": "w"}
        lane._write_registry(data)
    ok, problems = lane.listeners_ok()
    assert not ok and "damaged" in problems[0]


@pytest.mark.parametrize("entry, reason", [
    ("/usr/sbin/zsh", "an interpreter is never approved"),
    ("/usr/libexec/perl5.30", "an interpreter is never approved"),
    ("/System/Library/Frameworks/Python.framework/Versions/3.9/bin/python3.9", "an interpreter is never approved"),
    ("/usr/libexec/nonesuch", "does not exist"),
])
def test_on_a_mac_an_interpreter_is_an_interpreter_even_when_it_is_missing(env, monkeypatch, entry, reason):
    def device(path):
        if path in ("/usr/sbin", "/usr/libexec/rapportd"):
            return 1
        raise FileNotFoundError(path)
    monkeypatch.setattr(lane.sys, "platform", "darwin")
    monkeypatch.setattr(lane, "_device", device)
    approve(["/usr/libexec/rapportd", entry])
    with pytest.raises(lane.LaneWait, match=reason):
        lane.load_approved()


def test_pid_1_is_explained_to_the_lead(listeners):
    approve([p for p in APPROVED if p != "/sbin/launchd"])
    ok, problems = lane.listeners_ok()
    assert problems == ["launchd (pid 1) listens on port 22 (/sbin/launchd), launchd holds it for a socket-activated job"]


# ---------- Task 5: the broker's pinned Playwright and its browser ----------

HAS_DATA_FILTER = hasattr(tarfile, "data_filter")


@pytest.fixture
def unpack(monkeypatch):
    """The real tarfile data filter where this Python has it (the Mac's); on an older one (the Pi's 3.11.2) a stand-in
    that unpacks the members extract_package has already checked, so the rest of the path is tested everywhere."""
    if not HAS_DATA_FILTER:
        monkeypatch.setattr(lane, "_extract", lambda tar, members, where: tar.extractall(where, members=members))


def npm_tarball(members):
    """A gzipped npm tarball. members: {name: bytes}, or {name: ("symlink", target)}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            if isinstance(data, tuple):
                info.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "chr": tarfile.CHRTYPE}[data[0]]
                info.linkname = data[1]
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


PW_FILES = {"package/package.json": b'{"name": "playwright-core", "version": "1.55.0"}',
            "package/index.js": b"module.exports = {};\n",
            "package/browsers.json": json.dumps({"browsers": [
                {"name": "chromium", "revision": "1190"},
                {"name": "chromium-headless-shell", "revision": "1243"}]}).encode()}


def sri(data):
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def commit_lockfile(repo, entry, message="lockfile"):
    lock = {"name": "bricks", "lockfileVersion": 3, "packages": {"": {"name": "bricks"}}}
    if entry is not None:
        lock["packages"]["node_modules/playwright-core"] = entry
    (repo / "package-lock.json").write_text(json.dumps(lock))
    subprocess.run(["git", "-C", str(repo), "add", "package-lock.json"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


class Registry:
    """A fake fetch: the npm registry's metadata and tarball for playwright-core 1.55.0."""
    def __init__(self, tarball, integrity=None, url=None):
        self.tarball, self.calls = tarball, []
        self.meta = {"name": "playwright-core", "version": "1.55.0",
                     "dist": {"integrity": integrity or sri(tarball),
                              "tarball": url or "https://registry.npmjs.org/playwright-core/-/playwright-core-1.55.0.tgz"}}

    def __call__(self, url):
        self.calls.append(url)
        if url == "https://registry.npmjs.org/playwright-core/1.55.0":
            return json.dumps(self.meta).encode()
        if url == self.meta["dist"]["tarball"]:
            return self.tarball
        raise OSError("unexpected fetch of " + url)


def test_the_pin_comes_from_the_base_commits_lockfile_never_the_worktree(env):
    """Spec unit test 10."""
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    (env["repo"] / "package-lock.json").write_text(json.dumps({"packages": {"node_modules/playwright-core": {
        "version": "1.99.0", "integrity": sri(b"the worker's choice")}}}))                  # the worktree's copy
    (env["repo"] / "node_modules" / "playwright-core").mkdir(parents=True)
    (env["repo"] / "node_modules" / "playwright-core" / "package.json").write_text('{"version": "1.99.0"}')
    assert lane.lock_entry(env["repo"], base) == ("1.55.0", sri(tarball))
    later = commit_lockfile(env["repo"], {"version": "1.99.0", "integrity": sri(b"later")}, "worker branch")
    assert lane.lock_entry(env["repo"], base) == ("1.55.0", sri(tarball))                    # the base, still
    assert lane.lock_entry(env["repo"], later)[0] == "1.99.0"


def test_a_lockfile_without_the_entry_or_a_plain_version_refuses_the_lane(env):
    """Spec unit test 10."""
    head = subprocess.run(["git", "-C", str(env["repo"]), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with pytest.raises(lane.LaneRefused, match="has no package-lock.json"):
        lane.lock_entry(env["repo"], head)
    base = commit_lockfile(env["repo"], None)
    with pytest.raises(lane.LaneRefused, match="no node_modules/playwright-core entry"):
        lane.lock_entry(env["repo"], base)
    for version in ("1.55", "1.55.0-beta.1", "1.55.0\n", "../1.55.0", "١.55.0", 155, None):
        base = commit_lockfile(env["repo"], {"version": version, "integrity": sri(b"x")}, "v %r" % (version,))
        with pytest.raises(lane.LaneRefused, match="isn't x.y.z"):
            lane.lock_entry(env["repo"], base)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": "sha1-abc"}, "sha1")
    with pytest.raises(lane.LaneRefused, match="no sha512 integrity"):
        lane.lock_entry(env["repo"], base)


@pytest.mark.parametrize("case", ["registry claims the tampered bytes", "tarball bytes", "tarball host"])
def test_an_integrity_mismatch_refuses_the_lane_and_installs_nothing(env, unpack, case):
    """Spec unit test 10, with a fake fetch. The first case is a registry that serves tampered bytes and claims their
    hash: only the lockfile's committed hash may decide."""
    tarball = npm_tarball(PW_FILES)
    tampered = npm_tarball(dict(PW_FILES, **{"package/index.js": b"require('child_process').exec('curl evil')\n"}))
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    fetch = {"registry claims the tampered bytes": Registry(tampered, integrity=sri(tampered)),
             "tarball bytes": Registry(tampered, integrity=sri(tarball)),
             "tarball host": Registry(tarball, url="https://evil.example/playwright-core-1.55.0.tgz")}[case]
    with pytest.raises(lane.LaneRefused, match="doesn't match the integrity hash in the base commit's lockfile|isn't on"):
        lane.pinned_playwright(env["repo"], base, fetch)
    assert not (lane.broker_root() / "playwright-core-1.55.0").exists()


def test_the_pinned_playwright_is_fetched_once_stamped_and_kept_outside_every_worktree(env, unpack, monkeypatch):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    fetch = Registry(tarball)
    seen = []
    real_rename = os.rename

    def rename(src, dst, *a, **k):
        seen.append(((Path(src) / lane.STAMP).read_text(), (Path(src) / lane.STAMP_MANIFEST).is_file()))
        return real_rename(src, dst, *a, **k)
    monkeypatch.setattr(lane.os, "rename", rename)
    dest = lane.pinned_playwright(env["repo"], base, fetch)
    monkeypatch.setattr(lane.os, "rename", real_rename)
    assert seen == [(sri(tarball) + "\n", True)]                           # the stamps are inside before the rename
    assert dest == teamlib.team_home() / "broker" / "playwright-core-1.55.0"
    assert (dest / "index.js").read_text() == "module.exports = {};\n" and lane.shell_revision(dest) == "1243"
    assert (dest / lane.STAMP).read_text() == sri(tarball) + "\n"            # inside: written before the rename
    assert sorted(p.name for p in dest.parent.iterdir() if p.name != ".install.lock") == ["playwright-core-1.55.0"]
    assert lane.pinned_playwright(env["repo"], base, fetch) == dest and len(fetch.calls) == 2   # no second fetch
    (dest / lane.STAMP).write_text(sri(b"other") + "\n")
    with pytest.raises(lane.LaneRefused, match="isn't stamped with the integrity hash"):
        lane.pinned_playwright(env["repo"], base, fetch)


def test_an_unstamped_folder_is_refused_with_how_to_recover(env):
    """Review: with the stamp written inside before the rename, a crash can't leave such a folder; one made by hand
    (or by an older teamd) is refused, and the message says to remove it."""
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    (lane.broker_root() / "playwright-core-1.55.0").mkdir()
    with pytest.raises(lane.LaneRefused, match="remove it and the next lane fetches it again"):
        lane.pinned_playwright(env["repo"], base, Registry(tarball))


@pytest.mark.parametrize("name, data", [
    ("package/../../escaped.txt", b"x"), ("/tmp/absolute.txt", b"x"), ("other/index.js", b"x"),
    ("package/link", ("symlink", "/etc/passwd")), ("package/../package/ok.js", b"x"),
    ("package/hard", ("hardlink", "package/index.js")), ("package/dev", ("chr", "")),
])
def test_extraction_rejects_members_that_escape_the_package_folder(env, tmp_path, name, data):
    """Spec unit test 10."""
    dest = tmp_path / "unpacked" / "playwright-core-1.55.0"
    dest.parent.mkdir()
    with pytest.raises(lane.LaneRefused, match="outside its package folder"):
        lane.extract_package(npm_tarball(dict(PW_FILES, **{name: data})), dest, "sha512-x")
    assert not dest.exists() and not (tmp_path / "escaped.txt").exists()
    assert os.listdir(dest.parent) == []


def test_without_tarfiles_data_filter_nothing_is_unpacked(env, tmp_path, monkeypatch):
    monkeypatch.delattr(lane.tarfile, "data_filter", raising=False)
    dest = tmp_path / "playwright-core-1.55.0"
    with pytest.raises(lane.LaneRefused, match="no tarfile data filter"):
        lane.extract_package(npm_tarball(PW_FILES), dest, "sha512-x")
    assert not dest.exists()


@pytest.fixture
def manifests(tmp_path, monkeypatch):
    path = tmp_path / "browsers.json"
    path.write_text(json.dumps({"chromium-headless-shell": {}}))
    monkeypatch.setattr(lane, "MANIFESTS", path)
    return path


def record(manifests, revision, value):
    data = json.loads(manifests.read_text())
    data["chromium-headless-shell"].setdefault(revision, {})[lane.platform_key()] = value
    manifests.write_text(json.dumps(data))


def fake_shell(folder):
    (folder / "chrome-headless-shell-mac-arm64").mkdir(parents=True)
    (folder / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell").write_bytes(b"\x7fELF shell")
    os.chmod(folder / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell", 0o755)
    os.symlink("chrome-headless-shell-mac-arm64/chrome-headless-shell", folder / "current")
    (folder / "INSTALLATION_COMPLETE").write_text("")


def test_the_manifest_covers_paths_modes_links_and_contents(env, tmp_path):
    folder = tmp_path / "chromium_headless_shell-1243"
    fake_shell(folder)
    first = lane.manifest_hash(folder)
    assert lane.manifest_hash(folder) == first
    shell = folder / "chrome-headless-shell-mac-arm64" / "chrome-headless-shell"
    changes = [lambda: shell.write_bytes(b"\x7fELF other"), lambda: os.chmod(shell, 0o700),
               lambda: (os.unlink(folder / "current"), os.symlink("elsewhere", folder / "current")),
               lambda: (folder / "extra.dylib").write_bytes(b"")]
    for change in changes:
        before = lane.manifest_hash(folder)
        change()
        assert lane.manifest_hash(folder) != before
    os.chmod(shell, 0o775)                                              # writable by the group
    with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
        lane.manifest_hash(folder)


def test_the_manifest_refuses_links_out_of_the_folder_and_ignores_playwrights_marker(env, tmp_path):
    """Review: a symlink must be relative and stay inside; an empty DEPENDENCIES_VALIDATED (what Playwright writes when
    something launches the browser unsandboxed) carries no code and doesn't change the hash."""
    folder = tmp_path / "chromium_headless_shell-1243"
    fake_shell(folder)
    before = lane.manifest_hash(folder)
    (folder / "DEPENDENCIES_VALIDATED").write_text("")
    assert lane.manifest_hash(folder) == before
    (folder / "DEPENDENCIES_VALIDATED").write_text("not empty")
    assert lane.manifest_hash(folder) != before
    (folder / "DEPENDENCIES_VALIDATED").unlink()
    for target in ("/etc/passwd", "../../outside", "../chrome-headless-shell-mac-arm64/../../x"):
        link = folder / "chrome-headless-shell-mac-arm64" / "lib"
        if os.path.lexists(link):
            link.unlink()
        os.symlink(target, link)
        with pytest.raises(lane.LaneRefused, match="links outside the browser's folder"):
            lane.manifest_hash(folder)
    link.unlink()
    deep = folder / "x" / "y"
    deep.mkdir(parents=True)
    os.symlink("../..", deep / "top")                                  # x/y/top is the folder itself: inside
    os.symlink("top/../outside", deep / "out")                         # lexically x/y/outside; really ../outside
    with pytest.raises(lane.LaneRefused, match="links outside the browser's folder"):
        lane.manifest_hash(folder)
    shutil.rmtree(folder / "x")
    os.symlink("chrome-headless-shell", folder / "chrome-headless-shell-mac-arm64" / "lib")   # inside: fine
    assert lane.manifest_hash(folder) != before


def test_the_installer_runs_with_an_environment_built_from_nothing(env, manifests, monkeypatch):
    """Spec, the lane's browser: no download host, proxy or TLS variables; only chromium-headless-shell, without GC."""
    for name in ("HTTPS_PROXY", "PLAYWRIGHT_DOWNLOAD_HOST", "NODE_TLS_REJECT_UNAUTHORIZED", "NODE_EXTRA_CA_CERTS",
                 "NODE_OPTIONS", "PLAYWRIGHT_BROWSERS_PATH"):
        monkeypatch.setenv(name, "teamd's own")
    pw = env["tmp"] / "pw"
    pw.mkdir()
    (pw / "browsers.json").write_text(PW_FILES["package/browsers.json"].decode())
    runs = []

    def installer(cmd, env_, cwd, timeout=900):
        runs.append((cmd, env_))
        fake_shell(lane.browsers_root() / "chromium_headless_shell-1243")
        return Ran(0, "downloaded")
    monkeypatch.setattr(lane, "_run_env", installer)
    folder, revision = lane.install_headless_shell("/opt/homebrew/bin/node", pw)
    assert (folder, revision) == (teamlib.team_home() / "broker" / "browsers" / "chromium_headless_shell-1243", "1243")
    cmd, installer_env = runs[0]
    assert cmd == ["/opt/homebrew/bin/node", str(pw / "cli.js"), "install", "chromium-headless-shell"]
    assert installer_env == {"PATH": "/usr/bin:/bin", "HOME": str(env["home"]),
                             "PLAYWRIGHT_BROWSERS_PATH": str(lane.browsers_root()), "PLAYWRIGHT_SKIP_BROWSER_GC": "1"}
    assert lane.install_headless_shell("/opt/homebrew/bin/node", pw) == (folder, "1243") and len(runs) == 1
    assert stat_mode(os.lstat(lane.browsers_root())) == 0o700


def test_the_installer_runs_with_a_fixed_umask(env, tmp_path):
    """Review focus: a legitimate reinstall must not change the manifest because teamd's umask differs."""
    old = os.umask(0o077)
    try:
        r = lane._run_env(["/bin/sh", "-c", "umask"], {"PATH": "/usr/bin:/bin"}, cwd=tmp_path)
    finally:
        os.umask(old)
    assert r.returncode == 0 and r.stdout.strip() == "0022"


def test_a_failed_install_refuses_the_lane(env, manifests, monkeypatch):
    pw = env["tmp"] / "pw"
    pw.mkdir()
    (pw / "browsers.json").write_text(PW_FILES["package/browsers.json"].decode())
    monkeypatch.setattr(lane, "_run_env", lambda cmd, env_, cwd, timeout=900: Ran(1, "ERR npm_" + "a" * 36))
    with pytest.raises(lane.LaneRefused, match="installing chromium-headless-shell 1243 failed") as refused:
        lane.install_headless_shell("/opt/homebrew/bin/node", pw)
    assert "npm_aaaa" not in str(refused.value)                       # redacted
    (pw / "browsers.json").write_text(json.dumps({"browsers": [{"name": "chromium", "revision": "1190"}]}))
    with pytest.raises(lane.LaneRefused, match="names no chromium-headless-shell revision"):
        lane.install_headless_shell("/opt/homebrew/bin/node", pw)


def test_the_browsers_folder_and_everything_above_it_must_be_safe(env, manifests, tmp_path):
    """Review: checked as lane_node is. A folder above it that someone else can write refuses the lane (a sticky one,
    like /tmp, is fine: nobody else can rename what this user owns in it)."""
    folder = lane.browsers_root() / "chromium_headless_shell-1243"
    fake_shell(folder)
    record(manifests, "1243", lane.manifest_hash(folder))
    assert lane.check_manifest(folder, "1243")
    above = teamlib.team_home().parent
    os.chmod(above, 0o777)
    try:
        with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
            lane.check_manifest(folder, "1243")
        os.chmod(above, 0o1777)
        assert lane.check_manifest(folder, "1243")
    finally:
        os.chmod(above, 0o700)


def test_the_manifest_must_be_recorded_and_match(env, manifests):
    folder = lane.browsers_root() / "chromium_headless_shell-1243"
    fake_shell(folder)
    actual = lane.manifest_hash(folder)
    with pytest.raises(lane.LaneRefused) as unrecorded:
        lane.check_manifest(folder, "1243")
    message = str(unrecorded.value)
    assert "no manifest hash is recorded for chromium-headless-shell 1243 on " + lane.platform_key() in message
    assert actual in message and "team/superyak_team/lane/browsers.json" in message
    record(manifests, "1243", "0" * 64)
    with pytest.raises(lane.LaneRefused, match="doesn't match the manifest hash"):
        lane.check_manifest(folder, "1243")
    record(manifests, "1243", actual)
    assert lane.check_manifest(folder, "1243") == actual


def test_the_checked_in_manifest_file_is_well_formed():
    data = json.loads((teamlib.package_dir() / "lane" / "browsers.json").read_text())
    assert isinstance(data["chromium-headless-shell"], dict)
    for revision, platforms in data["chromium-headless-shell"].items():
        assert revision.isdigit() and all(re.fullmatch(r"[0-9a-f]{64}", h) for h in platforms.values())


def test_lane_node_is_an_owned_absolute_binary_outside_home_and_worktrees(env, tmp_path):
    """Spec, the broker's node: never `which node`, never under a worktree, never writable by others."""
    for bad in (None, "", "node", "bin/node"):
        with pytest.raises(lane.LaneRefused, match="set lane_node"):
            lane.check_lane_node(bad, [])
    in_home = env["home"] / "bin" / "node"
    in_home.parent.mkdir()
    in_home.write_text("#!/bin/sh\n")
    in_home.chmod(0o755)
    with pytest.raises(lane.LaneRefused, match="under your home folder"):
        lane.check_lane_node(str(in_home), [])
    worktree = tmp_path / "repo-worktrees" / "t1" / "kaylee"
    (worktree / "node_modules" / ".bin").mkdir(parents=True)
    planted = worktree / "node_modules" / ".bin" / "node"
    planted.write_text("#!/bin/sh\n")
    planted.chmod(0o755)
    with pytest.raises(lane.LaneRefused, match="lies under the worktree"):
        lane.check_lane_node(str(planted), [str(worktree)])
    loose = tmp_path / "opt" / "node"
    loose.parent.mkdir()
    loose.write_text("#!/bin/sh\n")
    loose.chmod(0o777)
    with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
        lane.check_lane_node(str(loose), [])
    open_dir = tmp_path / "opt2"
    open_dir.mkdir()
    fine = open_dir / "node"
    fine.write_text("#!/bin/sh\n")
    fine.chmod(0o755)
    open_dir.chmod(0o777)                                               # the binary is fine; the folder above is not
    try:
        with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
            lane.check_lane_node(str(fine), [])
    finally:
        open_dir.chmod(0o700)
    system_node = "/usr/bin/node"
    if os.path.isfile(system_node):
        assert lane.check_lane_node(system_node, [str(worktree)]) == Path(os.path.realpath(system_node))


# ---------- Task 5, fix round 1 ----------

def test_a_symlinked_browser_folder_or_browsers_root_is_refused(env, manifests, tmp_path):
    """Review: _check_owner lets a symlink through, and a link hashes its target, whose ancestors nobody checked."""
    real = tmp_path / "elsewhere" / "chromium_headless_shell-1243"
    fake_shell(real)
    record(manifests, "1243", lane.manifest_hash(real))
    link = lane.browsers_root() / "chromium_headless_shell-1243"
    os.symlink(real, link)
    with pytest.raises(lane.LaneRefused, match="isn't a plain folder"):
        lane.check_manifest(link, "1243")
    link.unlink()
    shutil.rmtree(lane.browsers_root())
    os.symlink(real.parent, lane.broker_root() / "browsers")
    with pytest.raises(lane.LaneRefused, match="isn't a plain folder"):
        lane.check_manifest(real, "1243")


def test_the_browser_folder_must_be_directly_in_the_browsers_root(env, manifests, tmp_path):
    folder = tmp_path / "chromium_headless_shell-1243"          # a real folder, but not in browsers_root
    fake_shell(folder)
    record(manifests, "1243", lane.manifest_hash(folder))
    with pytest.raises(lane.LaneRefused, match="isn't directly in"):
        lane.check_manifest(folder, "1243")


class FakeOpener:
    def __init__(self, chunks=(), error=None, final="https://registry.npmjs.org/x"):
        self.chunks, self.error, self.final, self.timeouts = list(chunks), error, final, []

    def open(self, url, timeout=None):
        self.timeouts.append(timeout)
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read1(self, n=-1):
        return self.chunks.pop(0) if self.chunks else b""

    def geturl(self):
        return self.final


@pytest.mark.parametrize("error", [http.client.InvalidURL("bad"), http.client.IncompleteRead(b"ab", 5),
                                   http.client.BadStatusLine("x"), ValueError("odd"), TimeoutError("slow")])
def test_a_download_that_fails_any_way_is_a_refusal(monkeypatch, error):
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: FakeOpener(error=error))
    with pytest.raises(lane.LaneRefused, match="can't be downloaded"):
        lane.https_get("https://registry.npmjs.org/x")


def test_a_download_must_be_https_all_the_way_and_finish_in_time(monkeypatch):
    with pytest.raises(lane.LaneRefused, match="isn't https"):
        lane.https_get("http://registry.npmjs.org/x")
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: FakeOpener([b"ab"], final="http://evil/x"))
    with pytest.raises(lane.LaneRefused, match="isn't https"):
        lane.https_get("https://registry.npmjs.org/x")
    with pytest.raises(lane.LaneRefused, match="isn't https"):                          # a redirect to http
        lane._HttpsOnly().redirect_request(urllib.request.Request("https://a/"), None, 302, "Found", {}, "http://b/")
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: FakeOpener([b"abcd", b"efgh"]))
    with pytest.raises(lane.LaneRefused, match="larger than"):
        lane.https_get("https://registry.npmjs.org/x", limit=5)
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: FakeOpener([b"abcd", b"efgh"]))
    assert lane.https_get("https://registry.npmjs.org/x") == b"abcdefgh"


def test_the_tarball_url_is_built_here_and_the_registry_cant_name_another(env, unpack):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    fetch = Registry(tarball)
    lane.pinned_playwright(env["repo"], base, fetch)
    assert fetch.calls == ["https://registry.npmjs.org/playwright-core/1.55.0",
                           "https://registry.npmjs.org/playwright-core/-/playwright-core-1.55.0.tgz"]
    shutil.rmtree(lane.broker_root() / "playwright-core-1.55.0")
    other = Registry(tarball, url="https://registry.npmjs.org/playwright-core/-/../../evil/-/e.tgz")
    with pytest.raises(lane.LaneRefused, match="isn't on"):
        lane.pinned_playwright(env["repo"], base, other)
    assert other.calls == ["https://registry.npmjs.org/playwright-core/1.55.0"]


def test_a_bad_base_commit_or_a_lockfile_git_cant_decode_refuses_the_lane(env):
    for bad in ("HEAD", "abc", "--output=x", "g" * 40, "A" * 40, None):
        with pytest.raises(lane.LaneRefused, match="isn't a 40-character hex"):
            lane.lock_entry(env["repo"], bad)
    (env["repo"] / "package-lock.json").write_bytes(b'{"packages": {"\xff": 1}}')
    subprocess.run(["git", "-C", str(env["repo"]), "add", "package-lock.json"], check=True)
    subprocess.run(["git", "-C", str(env["repo"]), "commit", "-qm", "latin1"], check=True)
    head = subprocess.run(["git", "-C", str(env["repo"]), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with pytest.raises(lane.LaneRefused, match="can't be read"):
        lane.lock_entry(env["repo"], head)


def test_a_replace_ref_cant_swap_the_base_commits_lockfile(env):
    good = {"version": "1.55.0", "integrity": sri(b"good")}
    base = commit_lockfile(env["repo"], good)
    blob = subprocess.run(["git", "-C", str(env["repo"]), "rev-parse", base + ":package-lock.json"],
                          capture_output=True, text=True).stdout.strip()
    evil = subprocess.run(["git", "-C", str(env["repo"]), "hash-object", "-w", "--stdin"], capture_output=True, text=True,
                          input=json.dumps({"packages": {"node_modules/playwright-core": {
                              "version": "9.9.9", "integrity": sri(b"evil")}}})).stdout.strip()
    subprocess.run(["git", "-C", str(env["repo"]), "replace", blob, evil], check=True)
    assert lane.lock_entry(env["repo"], base) == ("1.55.0", sri(b"good"))


def test_a_damaged_manifest_record_or_browsers_json_is_a_refusal_not_a_crash(env, manifests, tmp_path):
    for text in ("not json", "[]", '"x"', '{"chromium-headless-shell": []}', '{"chromium-headless-shell": {"1243": 5}}',
                 '\xff'):
        manifests.write_text(text)
        with pytest.raises(lane.LaneRefused, match="can't be read"):
            lane.recorded_manifest("1243")
    manifests.write_bytes(b"\xff\xfe")
    with pytest.raises(lane.LaneRefused, match="can't be read"):
        lane.recorded_manifest("1243")
    pw = tmp_path / "pw"
    pw.mkdir()
    for text in ("[]", "5", '{"browsers": 5}', '{"browsers": [5, null, {"name": 1}]}', "not json"):
        (pw / "browsers.json").write_text(text)
        with pytest.raises(lane.LaneRefused, match="names no chromium-headless-shell revision"):
            lane.shell_revision(pw)
    (pw / "browsers.json").write_bytes(b"\xff")
    with pytest.raises(lane.LaneRefused, match="names no chromium-headless-shell revision"):
        lane.shell_revision(pw)


def test_the_manifest_hashes_names_that_are_not_utf8(env, tmp_path):
    folder = tmp_path / "chromium_headless_shell-1243"
    fake_shell(folder)
    before = lane.manifest_hash(folder)
    fd = os.open(os.fsencode(folder) + b"/caf\xe9", os.O_CREAT | os.O_WRONLY, 0o644)
    os.close(fd)
    os.symlink(b"caf\xe9", os.fsencode(folder) + b"/lnk\xff")
    assert lane.manifest_hash(folder) != before


def test_the_manifest_refuses_a_folder_it_cant_read_and_a_link_given_as_the_folder(env, tmp_path):
    folder = tmp_path / "chromium_headless_shell-1243"
    fake_shell(folder)
    sealed = folder / "sealed"
    sealed.mkdir()
    sealed.chmod(0)
    try:
        if os.access(sealed, os.R_OK):
            pytest.skip("running as a user who can read anything")
        with pytest.raises(lane.LaneRefused, match="can't be read"):
            lane.manifest_hash(folder)
    finally:
        sealed.chmod(0o700)
    sealed.rmdir()
    link = tmp_path / "link"
    os.symlink(folder, link)
    with pytest.raises(lane.LaneRefused, match="isn't a plain folder"):
        lane.manifest_hash(link)


def test_every_property_the_manifest_covers_changes_or_refuses(env, tmp_path, monkeypatch):
    """Review: relative-only links, folder modes, hidden files, the marker at the top only, the top folder's own mode
    and owner."""
    folder = tmp_path / "chromium_headless_shell-1243"
    fake_shell(folder)
    inner = folder / "chrome-headless-shell-mac-arm64"
    shell = inner / "chrome-headless-shell"
    base = lane.manifest_hash(folder)
    os.symlink(str(shell), inner / "abs")                                # absolute, though it points inside
    with pytest.raises(lane.LaneRefused, match="links outside the browser's folder"):
        lane.manifest_hash(folder)
    (inner / "abs").unlink()
    os.chmod(inner, 0o700)                                               # a folder's mode
    assert lane.manifest_hash(folder) != base
    os.chmod(inner, 0o755)
    assert lane.manifest_hash(folder) == base
    (inner / ".hidden").write_bytes(b"")                                 # a hidden file
    assert lane.manifest_hash(folder) != base
    (inner / ".hidden").unlink()
    (inner / "DEPENDENCIES_VALIDATED").write_text("")                    # the marker only counts at the top
    assert lane.manifest_hash(folder) != base
    (inner / "DEPENDENCIES_VALIDATED").unlink()
    (folder / "DEPENDENCIES_VALIDATED").mkdir()                          # nor as a folder
    assert lane.manifest_hash(folder) != base
    (folder / "DEPENDENCIES_VALIDATED").rmdir()
    os.chmod(folder, 0o775)                                              # the top folder's own mode
    with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
        lane.manifest_hash(folder)
    os.chmod(folder, 0o755)
    if os.getuid() != 0:
        real_uid = os.getuid()
        monkeypatch.setattr(lane.os, "getuid", lambda: real_uid + 1)     # its owner
        with pytest.raises(lane.LaneRefused, match="belongs to another user"):
            lane.manifest_hash(folder)


def test_the_pinned_playwright_folder_is_checked_again_when_it_is_reused(env, unpack):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    dest = lane.pinned_playwright(env["repo"], base, Registry(tarball))
    assert stat_mode(os.lstat(dest)) == 0o755
    assert lane.pinned_playwright(env["repo"], base, Registry(tarball)) == dest
    (dest / "index.js").write_text("require('child_process').exec('curl evil')\n")      # changed after the install
    with pytest.raises(lane.LaneRefused, match="has changed since it was installed"):
        lane.pinned_playwright(env["repo"], base, Registry(tarball))
    (dest / "index.js").write_text("module.exports = {};\n")
    (dest / "extra.js").write_text("")
    with pytest.raises(lane.LaneRefused, match="has changed since it was installed"):
        lane.pinned_playwright(env["repo"], base, Registry(tarball))
    (dest / "extra.js").unlink()
    os.chmod(dest, 0o777)
    with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
        lane.pinned_playwright(env["repo"], base, Registry(tarball))
    os.chmod(dest, 0o755)
    above = dest.parent.parent                                          # broker_root() resets its own mode
    os.chmod(above, 0o777)
    try:
        with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
            lane.pinned_playwright(env["repo"], base, Registry(tarball))
    finally:
        os.chmod(above, 0o700)
    assert lane.pinned_playwright(env["repo"], base, Registry(tarball)) == dest


def test_unpack_leftovers_are_swept_before_a_new_unpack(env, unpack):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    old = lane.broker_root() / ".unpack-dead"
    (old / "package").mkdir(parents=True)
    (old / "package" / "x").write_text("x")
    os.symlink("/nonexistent", lane.broker_root() / ".unpack-link")
    lane.pinned_playwright(env["repo"], base, Registry(tarball))
    assert sorted(p.name for p in lane.broker_root().iterdir() if p.name != ".install.lock") == ["playwright-core-1.55.0"]


def holding(path):
    f = open(path, "a+")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def blocked_until_released(call, path):
    """Run call() in a thread while another file holds the lock; it must wait, then finish once released."""
    f = holding(path)
    result = []
    t = threading.Thread(target=lambda: result.append(call()))
    t.start()
    t.join(0.5)
    waited = t.is_alive()
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    t.join(10)
    return waited, result


def test_the_install_lock_is_taken_by_the_installers_themselves_and_nests(env, unpack, monkeypatch):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    path = lane.broker_root() / ".install.lock"
    assert lane.install_lock_path() == path
    waited, result = blocked_until_released(lambda: lane.pinned_playwright(env["repo"], base, Registry(tarball)), path)
    assert waited and result == [lane.broker_root() / "playwright-core-1.55.0"]
    pw = env["tmp"] / "pw"
    pw.mkdir()
    (pw / "browsers.json").write_text(PW_FILES["package/browsers.json"].decode())
    monkeypatch.setattr(lane, "_run_env", lambda cmd, e, cwd, timeout=900: (
        fake_shell(lane.browsers_root() / "chromium_headless_shell-1243"), Ran(0, ""))[1])
    waited, result = blocked_until_released(lambda: lane.install_headless_shell("/opt/homebrew/bin/node", pw), path)
    assert waited and len(result) == 1
    def nested():
        with lane.install_lock():                                       # prepare_broker's own hold: no deadlock
            assert lane.pinned_playwright(env["repo"], base, Registry(tarball))
            assert lane.install_headless_shell("/opt/homebrew/bin/node", pw)
    t = threading.Thread(target=nested, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive()


class Dripper(FakeOpener):
    """A server that sends one byte every 0.25 s. read(n) blocks until it has n bytes (capped here at 8 so a
    regression ends the test instead of hanging it); read1 returns what has arrived."""
    def read(self, n=-1):
        time.sleep(0.25 * min(n, 8))
        return b"x" * min(n, 8)

    def read1(self, n=-1):
        time.sleep(0.25)
        return b"x"


def test_the_download_deadline_holds_against_a_server_that_drips_bytes(monkeypatch):
    """Review: read(65536) blocks until it has 64 KiB, so a deadline checked between reads fires late."""
    fake = Dripper()
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: fake)
    started = time.monotonic()
    with pytest.raises(lane.LaneRefused, match="took longer than"):
        lane.https_get("https://registry.npmjs.org/x", deadline=1)
    assert time.monotonic() - started < 1.75
    assert fake.timeouts and fake.timeouts[0] <= 1                    # connect and headers are bounded by it too
    assert FakeOpener().timeouts == []
    fake = FakeOpener([b"a"])
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: fake)
    lane.https_get("https://registry.npmjs.org/x")
    assert fake.timeouts[0] <= 60


def test_https_get_installs_the_https_only_redirect_handler(monkeypatch):
    seen = []
    monkeypatch.setattr(lane.urllib.request, "build_opener", lambda *h: seen.extend(h) or FakeOpener([b"a"]))
    lane.https_get("https://registry.npmjs.org/x")
    assert lane._HttpsOnly in seen


def test_unpacking_under_a_group_writable_umask_still_gives_a_plain_package(env, unpack):
    """Review: npm tarballs have no folder entries, so tarfile makes lib/ with teamd's umask."""
    files = dict(PW_FILES, **{"package/lib/deep/util.js": b"x"})
    tarball = npm_tarball(files)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    lane.broker_root()                                                  # made before the umask changes
    old = os.umask(0o002)
    try:
        dest = lane.pinned_playwright(env["repo"], base, Registry(tarball))
    finally:
        os.umask(old)
    for folder in (dest, dest / "lib", dest / "lib" / "deep"):
        assert stat_mode(os.lstat(folder)) == 0o755
    assert lane.pinned_playwright(env["repo"], base, Registry(tarball)) == dest


@pytest.mark.parametrize("which", ["STAMP", "STAMP_MANIFEST"])
def test_a_stamp_that_is_a_symlink_is_refused(env, unpack, which):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    dest = lane.pinned_playwright(env["repo"], base, Registry(tarball))
    stamp = dest / getattr(lane, which)
    copy = env["tmp"] / "copy"
    copy.write_text(stamp.read_text())
    stamp.unlink()
    os.symlink(copy, stamp)
    with pytest.raises(lane.LaneRefused, match="isn't a plain file"):
        lane.pinned_playwright(env["repo"], base, Registry(tarball))


def test_the_broker_root_must_be_a_real_folder_outside_the_shared_temp_folders(env, monkeypatch):
    real = lane.broker_root()
    shutil.rmtree(real)
    elsewhere = env["tmp"] / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, real)
    with pytest.raises(lane.LaneRefused, match="isn't a plain folder"):
        lane.broker_root()
    real.unlink()
    monkeypatch.setattr(lane, "UNSAFE_ROOTS", (str(env["tmp"]),))
    with pytest.raises(lane.LaneRefused, match="under the shared temp folder"):
        lane.broker_root()
    monkeypatch.undo()


def test_an_oserror_inside_the_install_lock_keeps_its_own_message(env):
    with pytest.raises(OSError, match="boom"):
        with lane.install_lock():
            raise OSError(5, "boom")
    with lane.install_lock():                                           # and the lock is usable again
        pass
