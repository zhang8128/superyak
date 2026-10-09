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
    assert lane.listeners_ok() == (True, [])       # not reachable, so not counted at all
    listeners["sockets"][-1] = ("tcp4", "127.0.0.1.9100", "LISTEN", 902, "node")
    ok, problems = lane.listeners_ok()             # on loopback it is an ordinary unapproved listener
    assert problems == ["node (pid 902) listens on port 9100 (/opt/homebrew/bin/node)"]


def test_a_lane_process_on_a_lan_address_outside_its_block_is_checked(listeners, monkeypatch):
    listeners["environ"][902] = ["CLAUDE_CODE_TMPDIR=" + lane_tmp()]
    listeners["exe"][902] = "/opt/homebrew/bin/node"
    monkeypatch.setattr(lane, "reachable", lambda host: True)                     # the address counts as listed
    listeners["sockets"].append(("tcp4", "192.168.1.20.9100", "LISTEN", 902, "node"))
    ok, problems = lane.listeners_ok()
    assert not ok and [p for p in problems if "192.168.1.20 port 9100, beyond loopback" in p]


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


def test_pid_1_is_explained_to_the_lead(listeners):
    approve([p for p in APPROVED if p != "/sbin/launchd"])
    ok, problems = lane.listeners_ok()
    assert problems == ["launchd (pid 1) listens on port 22 (/sbin/launchd), launchd holds it for a socket-activated job"]
