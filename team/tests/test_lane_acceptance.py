"""The Mac acceptance script's logic (team/scripts/lane_acceptance.py and lane_acceptance/worker_probes.py), on the
Pi. The run itself is macOS only: Serenity runs it, and it is the spec's Mac acceptance, steps 1-7."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(scope="module")
def acceptance():
    spec = importlib.util.spec_from_file_location("lane_acceptance", SCRIPTS / "lane_acceptance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rows_are_judged_by_what_they_expect(acceptance):
    assert [acceptance.judge("ok", 0), acceptance.judge("ok", 1)] == ["PASS", "FAIL"]
    assert [acceptance.judge("fail", 1), acceptance.judge("fail", 0), acceptance.judge("fail", -1)] == ["PASS", "FAIL", "PASS"]
    assert acceptance.judge("info", 0) == "INFO"


def test_a_rendezvous_lookup_is_denied_reachable_or_a_broken_check(acceptance):
    """Spec acceptance step 3: 1100 is the sandbox's denial; 1102 means the check itself is broken."""
    assert [acceptance.classify_lookup(rc) for rc in (1100, 0, 1102, 5)] == ["denied", "reachable", "broken", "other"]
    lines = ["Sandbox: Python(812) deny(1) mach-lookup org.chromium.Chromium.MachPortRendezvousServer.4711",
             "Sandbox: Python(900) deny(1) mach-lookup com.apple.pasteboard.1"]
    assert acceptance.denied_lookup(lines, 812) and not acceptance.denied_lookup(lines, 900)


def test_a_second_lane_row_counts_only_if_its_target_was_alive_throughout(acceptance):
    """Review: a target that died meanwhile proves nothing, so the row is BROKEN, never a pass."""
    assert acceptance.peer_verdict("fail", 1, True, True) == "PASS"
    assert acceptance.peer_verdict("fail", 0, True, True) == "FAIL"
    assert acceptance.peer_verdict("fail", 1, True, False) == "BROKEN"
    assert acceptance.peer_verdict("fail", 1, None, True) == "BROKEN"


def test_listeners_are_listed_as_the_check_sees_them(acceptance):
    """--list-listeners and step 4 use the listener check's own enumeration and its rules (D11, reachability)."""
    listeners = [{"pid": 612, "command": "", "host": "*", "port": 49152},
                 {"pid": 1, "command": "", "host": "*", "port": 22},
                 {"pid": 777, "command": "", "host": "127.0.0.1", "port": 11434},
                 {"pid": 333, "command": "", "host": "100.101.102.103", "port": 8080},
                 {"pid": 999, "command": "", "host": "::1", "port": 9000}]
    paths = {612: "/usr/libexec/rapportd", 1: "/sbin/launchd", 777: "/opt/homebrew/bin/ollama",
             333: "/opt/homebrew/bin/tailscaled"}
    assert acceptance.listener_rows(listeners, paths.get, {"/usr/libexec/rapportd"}) == [
        (612, "*:49152", "/usr/libexec/rapportd", "approved"),
        (1, "*:22", "/sbin/launchd", "approvable; launchd holds it for a socket-activated job"),
        (777, "127.0.0.1:11434", "/opt/homebrew/bin/ollama", "stop it while a lane runs"),
        (333, "100.101.102.103:8080", "/opt/homebrew/bin/tailscaled", "doesn't count: a lane can't reach it"),
        (999, "::1:9000", "?", "can't be identified: a lane waits")]


def test_the_rendezvous_name_carries_the_browsers_pid_not_nodes(acceptance):
    ps = ("  700     1 /opt/homebrew/bin/node -e // Superyak browser-lane broker (spike 4's script, ... 41031\n"
          "  712   700 /Users/me/.superyak/team/broker/browsers/chromium_headless_shell-1243/chrome-headless-shell --type=zygote\n"
          "  711   700 /Users/me/.superyak/team/broker/browsers/chromium_headless_shell-1243/chrome-headless-shell --headless --remote-debugging-pipe\n"
          "  713   711 /Users/me/.superyak/team/broker/browsers/chromium_headless_shell-1243/chrome-headless-shell --type=renderer\n")
    assert acceptance.rendezvous_pid(ps, 700) == 711
    assert acceptance.rendezvous_pid(ps, 999) is None


def test_a_playwright_report_keeps_advisory_failures_apart_and_whole(acceptance):
    """Spec: advisory failures are reported in full and separately, never dropped; everything else must pass."""
    report = {"errors": [], "suites": [{"title": "auth-pages.spec.ts", "specs": [
        {"title": "signs in", "file": "tests/auth-pages.spec.ts", "line": 6, "tags": [], "tests": [{"status": "expected"}]},
        {"title": "card widths", "file": "tests/auth-pages.spec.ts", "line": 20, "tags": ["@lane-advisory"],
         "tests": [{"status": "unexpected"}]},
        {"title": "retries", "file": "tests/auth-pages.spec.ts", "line": 30, "tags": [], "tests": [{"status": "flaky"}]},
    ], "suites": [{"title": "nested", "specs": [
        {"title": "signs out", "file": "tests/auth-pages.spec.ts", "line": 40, "tags": [], "tests": [{"status": "unexpected"}]},
        {"title": "later", "file": "tests/auth-pages.spec.ts", "line": 50, "tags": [], "tests": [{"status": "skipped"}]},
    ]}]}]}
    assert acceptance.summarize(report) == {
        "passed": 1, "failed": ["tests/auth-pages.spec.ts:40 signs out"],
        "advisory": ["tests/auth-pages.spec.ts:20 card widths"], "flaky": ["tests/auth-pages.spec.ts:30 retries"],
        "skipped": 1, "errors": []}


def test_the_domains_to_try_are_every_one_the_settings_name(acceptance, tmp_path):
    user = tmp_path / "settings.json"
    user.write_text(json.dumps({"sandbox": {"network": {"allowedDomains": ["*.github.com", "registry.npmjs.org"]}}}))
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    assert acceptance.effective_domains([user, broken, tmp_path / "missing.json"]) == \
        ["example.com", "github.com", "registry.npmjs.org"]


def test_step_2_reads_only_what_exists_outside_the_sandbox(acceptance, tmp_path):
    """Review (N7): a read of something that isn't there proves nothing, so it is BROKEN before it runs."""
    home, other, decoy = tmp_path / "home", tmp_path / "wash-lane", tmp_path / "decoy"
    for folder in (home, other, decoy):
        folder.mkdir()
    (home / ".bashrc").write_text("x\n")
    present, missing = acceptance.read_targets(other, decoy, 424242, home=home)
    assert present == {"a dotfile in $HOME": str(home / ".bashrc"), "a decoy lane's folder": str(decoy),
                       "the other lane's real folder": str(other)}
    assert missing == ["/private/tmp/claude-<uid>"]


def test_the_planted_project_settings_keep_what_was_there(acceptance):
    planted = acceptance.planted_settings({"permissions": {"allow": ["Bash(npm test)"]}, "env": {"CI": "1"}})
    assert planted["env"] == {"CI": "1"}
    assert planted["permissions"]["allow"] == ["Bash(npm test)", "WebFetch(domain:example.com)"]
    assert planted["sandbox"]["network"] == {"allowedDomains": ["example.com"], "allowMachLookup": ["*"]}


def test_the_worker_probes_never_return_contents(tmp_path, acceptance):
    import worker_probes
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET CONTENT")
    code, detail = worker_probes.can_read(str(secret))
    assert code == 0 and "TOP SECRET" not in detail
    assert worker_probes.can_read(str(tmp_path))[1].startswith("listed ")
    assert worker_probes.can_read(str(tmp_path / "missing"))[0] == 1
    assert worker_probes.leaked("A=1 PW_TEST_CONNECT_WS_ENDPOINT=ws://x SUPERYAK_BROKER_SECRET=y") == \
        ["SUPERYAK_BROKER_SECRET", "PW_TEST_CONNECT_WS_ENDPOINT"]
    assert worker_probes.leaked(None) == []


def test_the_scripts_start_and_refuse_to_run_off_the_mac():
    for script in ("lane_acceptance.py", "lane_acceptance/worker_probes.py"):
        assert subprocess.run([sys.executable, "-m", "py_compile", str(SCRIPTS / script)]).returncode == 0
    r = subprocess.run([sys.executable, str(SCRIPTS / "lane_acceptance.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--self-check-only" in r.stdout
    if sys.platform != "darwin":
        r = subprocess.run([sys.executable, str(SCRIPTS / "lane_acceptance.py"), "--bricks", "/tmp"],
                           capture_output=True, text=True)
        assert r.returncode != 0 and "run it on the Mac" in r.stderr


# ---------- the facts only a Mac can settle (review rows): their logic, on the Pi, with fakes and seams ----------

import subprocess as sp  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from superyak_team import lane  # noqa: E402


class Ran(SimpleNamespace):
    def __init__(self, returncode=0, stdout="", stderr=""):
        super().__init__(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """HOME, teamd's home and /tmp stand-ins under tmp_path; nothing real is touched."""
    home, tmp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    tmp.mkdir()
    (home / ".zshrc").write_text("export X=1\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SUPERYAK_TEAM_HOME", str(tmp_path / "teamhome"))
    monkeypatch.setattr(lane, "TMP_ROOT", tmp)
    monkeypatch.setattr(lane, "UNSAFE_ROOTS", ())
    monkeypatch.setattr(lane, "port_free", lambda port: True)
    return {"home": home, "tmp": tmp, "root": tmp_path}


def test_a_profile_row_prints_all_of_its_detail(acceptance, capsys):
    detail = "refused: EPERM (EPERM: operation not permitted, open '/Users/me/superyak-lane-probe.txt') " + "x" * 200
    report = acceptance.Report()
    report.add(1, "profile:write_home", "PASS", detail, full=True)
    report.add(1, "other", "PASS", detail)
    lines = capsys.readouterr().out.splitlines()
    assert detail in lines[0] and detail not in lines[1]


def test_a_broken_probe_prints_the_sandbox_denials_of_its_own_pid(acceptance, capsys):
    """Review: a BROKEN row shows the denial lines for that probe's pid, from the stream filtered by pid."""
    recorder = acceptance.PidRecorder()
    recorder.pids = [("net_domain", False, 812), ("exec_curl", False, 900), ("write_home", True, 950)]
    denials = ["Sandbox: node(812) deny(1) network-outbound 93.184.216.34:443",
               "Sandbox: curl(900) deny(1) file-read-data /etc/hosts"]
    report = acceptance.Report()
    acceptance.report_profile_rows(report, [("net_domain", "BROKEN", "refused: nocode"), ("exec_curl", "PASS", "refused: EPERM"),
                                            ("planted-import:write_home", "BROKEN", "x")], recorder, denials)
    out = capsys.readouterr().out
    assert "node(812): network-outbound 93.184.216.34:443" in out
    assert "curl(900)" not in out                                          # a PASS row prints no denials, and only its pid's
    assert "no sandbox denial lines for pid 950" in out
    assert report.failed() and len(report.rows) == 3


def test_the_recorder_runs_a_command_and_remembers_its_pid(acceptance, tmp_path):
    recorder = acceptance.PidRecorder()
    r = recorder([sys.executable, "-c", "import os; print(os.getpid())", "write_home"], env=os.environ.copy(),
                 cwd=str(tmp_path), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and recorder.pids == [("write_home", False, int(r.stdout))]
    with pytest.raises(sp.TimeoutExpired):
        recorder([sys.executable, "-c", "import time; time.sleep(60)", "slow"], timeout=0.5)
    (tmp_path / "system.sb").write_text("x")
    recorder([sys.executable, "-c", "0", "read_dotfile"], cwd=str(tmp_path), timeout=30)
    assert recorder.pids[-1][:2] == ("read_dotfile", True)                 # a system.sb in the cwd marks a planted run


def test_the_planted_import_reruns_both_probes_with_the_file_in_the_brokers_cwd(acceptance, world, monkeypatch):
    broker = world["root"] / "broker"
    pw, shell = broker / "playwright-core-1.55.0", broker / "browsers" / "chromium_headless_shell-1243"
    pw.mkdir(parents=True)
    shell.mkdir(parents=True)
    monkeypatch.setattr(lane, "browsers_root", lambda: broker / "browsers")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, ""))
    seen = []

    def sandbox(cmd, env=None, cwd=None, **kw):
        planted = Path(cwd, "system.sb")
        seen.append((cmd[-1], cwd, planted.read_text() if planted.exists() else None, "(import \"system.sb\")" in cmd[2]))
        return Ran(1, "refused: EPERM (EPERM: operation not permitted)")
    rows = acceptance.planted_import(Path("/opt/lane-test-node/22.9.0/bin/node"), pw, shell, sandbox)
    assert [(n, v) for n, v, _ in rows] == [("planted-import:write_home", "PASS"), ("planted-import:read_dotfile", "PASS")]
    assert [s[0] for s in seen] == ["write_home", "read_dotfile"]
    assert all(cwd.endswith("/b") and text == "(allow default)\n" and imported for _, cwd, text, imported in seen)
    assert "EPERM" in rows[0][2]
    team_id = "superyak-planted-import-%d" % os.getpid()
    assert not lane.lane_path(team_id, "check").exists() and lane.block_of(team_id, "check") is None
    assert not list(world["tmp"].glob("*/*/b/system.sb"))                  # the planted file is gone


def test_a_planted_import_that_lets_a_probe_through_fails_and_cleans_up(acceptance, world, monkeypatch):
    broker = world["root"] / "broker"
    pw, shell = broker / "pw", broker / "browsers" / "shell"
    pw.mkdir(parents=True)
    shell.mkdir(parents=True)
    monkeypatch.setattr(lane, "browsers_root", lambda: broker / "browsers")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, ""))

    def sandbox(cmd, env=None, cwd=None, **kw):
        if cmd[-1] == "write_home":
            (Path(env["HOME"]) / "superyak-lane-probe.txt").write_text("x")
        return Ran(0, "succeeded")
    rows = acceptance.planted_import(Path("/opt/n/bin/node"), pw, shell, sandbox)
    assert [v for _, v, _ in rows] == ["FAIL", "FAIL"]
    assert not (world["home"] / "superyak-lane-probe.txt").exists()


def test_the_planted_import_is_broken_when_a_target_is_missing(acceptance, world, monkeypatch):
    (world["home"] / ".zshrc").unlink()
    broker = world["root"] / "broker"
    pw, shell = broker / "pw", broker / "browsers" / "shell"
    pw.mkdir(parents=True)
    shell.mkdir(parents=True)
    monkeypatch.setattr(lane, "browsers_root", lambda: broker / "browsers")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, ""))
    ran = []
    rows = acceptance.planted_import(Path("/opt/n/bin/node"), pw, shell, lambda cmd, **kw: ran.append(cmd[-1]) or Ran(1, "refused: EPERM"))
    verdicts = {n: v for n, v, _ in rows}
    assert verdicts == {"planted-import:write_home": "PASS", "planted-import:read_dotfile": "BROKEN"}
    assert ran == ["write_home"]


def test_the_lsof_exit_code_is_recorded_as_information(acceptance):
    got = []
    ok = lambda cmd, timeout=60: got.append(cmd) or Ran(0, "p1\nn/a\np2\nn/b\n")
    verdict, detail = acceptance.lsof_exit(ok)
    assert verdict == "INFO" and "exit 0" in detail and "4 lines" in detail
    assert got[0][1:] == ["-nP", "-a", "-u", str(os.getuid()), "-F", "pn"] and got[0][0].endswith("lsof")
    verdict, detail = acceptance.lsof_exit(lambda cmd, timeout=60: Ran(1, "", "WARNING: can't stat() fuse\n more"))
    assert verdict == "INFO" and "exit 1" in detail and "can't stat() fuse" not in detail     # stderr isn't echoed
    assert acceptance.lsof_exit(lambda cmd, timeout=60: None)[0] == "BROKEN"


def test_a_hard_link_to_a_file_a_stranger_holds_open_is_not_named_for_the_lane(acceptance, world):
    """Review: lsof names an open file by the name it was opened with, so the holder of a hard link into the lane
    must not be in the cleanup's kill set. A real helper, a real lsof, a lane under tmp."""
    verdict, detail = acceptance.hardlink_naming()
    assert verdict == "PASS", detail
    assert "not in the kill set" in detail
    assert not any(p.name.startswith("sy-acc-hl") for p in world["tmp"].iterdir())
    leftovers = sp.run(["pgrep", "-f", "sy-acc-hl"], capture_output=True, text=True).stdout.strip()
    assert leftovers == ""                                                   # the helper is gone


def test_a_matcher_that_would_kill_the_holder_fails_the_row(acceptance, world, monkeypatch):
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: {p.pid for p in acceptance.HELPERS})
    verdict, detail = acceptance.hardlink_naming()
    assert verdict == "FAIL" and "in the kill set" in detail
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: None)
    assert acceptance.hardlink_naming()[0] == "BROKEN"


def test_the_browsers_folder_is_listed_with_anything_besides_the_shell(acceptance, tmp_path):
    browsers = tmp_path / "browsers"
    (browsers / "chromium_headless_shell-1243").mkdir(parents=True)
    assert acceptance.extra_browser_folders(browsers, browsers / "chromium_headless_shell-1243") == []
    (browsers / "ffmpeg-1011").mkdir()
    (browsers / "link").symlink_to(tmp_path)
    (browsers / ".links").write_text("x")
    assert acceptance.extra_browser_folders(browsers, browsers / "chromium_headless_shell-1243") == \
        [".links (file)", "ffmpeg-1011 (folder)", "link (symlink)"]


NETSTAT = """Active Internet connections (including servers)
Proto Recv-Q Send-Q  Local Address          Foreign Address        (state)      rxbytes   txbytes  rhiwat shiwat    pid   epid state    options           gencnt    flags   flags1 usscnt rtncnt fltrs
tcp4       0      0  127.0.0.1.8080         *.*                    LISTEN            0         0  131072 131072   4001   4001 00180081 00000006 000000000000a001 00000900 00000001      0      0 000000
tcp46      0      0  *.49152                *.*                    LISTEN            0         0  131072 131072    612    612 00180081 00000006 000000000000a002 00000900 00000001      0      0 000000
tcp4       0      0  127.0.0.1.5000         127.0.0.1.50000        ESTABLISHED       0         0  131072 131072    777    777 00180081 00000006 000000000000a003 00000900 00000001      0      0 000000
tcp6       0      0  ::1.631                *.*                    LISTEN            0         0  131072 131072    300    300 00180081 00000006 000000000000a004 00000900 00000001      0      0 000000
tcp4       0      0  *.9000                 *.*                    LISTEN            0         0  131072 131072    999    999 00180081 00000006 000000000000a005 00000900 00000001      0      0 000000
"""
NETSTAT_NAMED = NETSTAT.replace("(state)      rxbytes", "(state)      rxbytes").replace(
    "  pid   epid state", " process:pid   epid state").replace("   4001   4001", " Google Chrome He:4001   4001").replace(
    "    612    612", " rapportd:612    612").replace("    300    300", " cupsd:300    300").replace(
    "    999    999", " my-secret-app:999    999")


def test_the_netstat_fixture_keeps_apple_names_and_redacts_the_rest(acceptance):
    paths = {612: "/usr/libexec/rapportd", 300: "/usr/sbin/cupsd", 4001: "/Applications/Google Chrome.app/x",
             999: "/Users/me/bin/my-secret-app"}
    lines = acceptance.netstat_fixture(NETSTAT_NAMED, paths.get)
    assert lines[0].startswith("Proto Recv-Q Send-Q  Local Address") and "process:pid" in lines[0]
    assert len(lines) == 4                                                   # the header and three LISTEN rows
    text = "\n".join(lines)
    assert "rapportd:612" in text and "cupsd:300" in text
    assert "Google" not in text and "my-secret-app" not in text and "ESTABLISHED" not in text
    assert "<name>:4001" in text and "999" not in text                       # one row of each address kind first
    # the plain `pid` format has no names: nothing to redact, rows kept as they are
    plain = acceptance.netstat_fixture(NETSTAT, paths.get)
    assert len(plain) == 4 and "4001" in plain[1]
    assert acceptance.netstat_fixture("no header here\n", paths.get) is None


def test_the_netstat_capture_writes_a_file_and_names_it(acceptance, tmp_path):
    dest = tmp_path / "out" / "netstat.txt"
    verdict, detail = acceptance.capture_netstat(lambda cmd, timeout=60: Ran(0, NETSTAT_NAMED), lambda pid: None, dest)
    assert verdict == "INFO" and str(dest) in detail
    assert "my-secret-app" not in dest.read_text() and dest.read_text().count("LISTEN") == 3
    assert acceptance.capture_netstat(lambda cmd, timeout=60: Ran(1, ""), lambda pid: None, dest)[0] == "BROKEN"
    assert acceptance.capture_netstat(lambda cmd, timeout=60: Ran(0, "garbage\n"), lambda pid: None, dest)[0] == "BROKEN"


# ================= Fix round 1: no row passes without proving its property =================

import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402


# ---- Critical 1: Andy's real lane-listeners.json survives any failure in step 4 ----

class FakeTeam:
    """A Team whose turns do what the test says; the run's own logic is the real steps2to7."""
    fail_at = "waiting"            # which wait raises

    def __init__(self, bricks, team_id):
        self.id, self.inbox, self.bricks = team_id, [], bricks

    def call(self, *a, **k):
        return {}

    def state(self):
        w = self.world
        return {"workers": {n: {"path": str(w["wk"][n]), "pid": 4242, "lane": {"path": str(w["lanes"][n]), "base": b,
                                                                               "preload": None}}
                            for n, b in (("kaylee", 41000), ("wash", 41032))}}

    def message(self, wid, text):
        getattr(FakeTeam, "messages", []).append((wid, text))
        d = self.world["wk"][wid] / "node_modules" / ".superyak-lane-acceptance"
        d.mkdir(parents=True, exist_ok=True)
        (d / ("results-%s.json" % ("lane" if wid == "kaylee" else "peer"))).write_text(json.dumps({"pid": 1, "rows": []}))

    def wait(self, wid, states, timeout=900, patient=False):
        if states == (self.fail_at,):
            raise RuntimeError("%s is not %s" % (wid, self.fail_at))
        return states[0]

    def status(self):
        return {"workers": {}}


@pytest.fixture
def driven(acceptance, world, monkeypatch):
    """steps2to7 with a fake team, no lsof and no browser: only the logic around the lane's files runs."""
    root = world["root"]
    bricks = root / "bricks"
    bricks.mkdir()
    subprocess.run(["git", "init", "-q", str(bricks)], check=True)
    wk = {w: root / w for w in ("kaylee", "wash")}
    lanes = {w: world["tmp"] / ("lane-" + w) for w in wk}
    for w in wk:
        (wk[w] / ".claude").mkdir(parents=True)
        lanes[w].mkdir()
    FakeTeam.world = {"wk": wk, "lanes": lanes}
    FakeTeam.fail_at = "waiting"
    lane.approved_path().parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(acceptance, "Team", FakeTeam)
    monkeypatch.setattr(acceptance, "lsof_pids", lambda *a: set())
    monkeypatch.setattr(acceptance.worker_probes, "bootstrap_look_up", lambda name: 0)
    monkeypatch.setattr(acceptance, "HOLDER_POLLS", 1)
    monkeypatch.setattr(acceptance, "HOLDER_POLL_S", 0)
    monkeypatch.setattr(acceptance, "preflight", lambda args, report: True, raising=False)
    monkeypatch.setattr(acceptance, "zoe_rows", lambda args, report, team: None)       # its own tests cover it
    real_run = subprocess.run
    monkeypatch.setattr(acceptance.subprocess, "run",
                        lambda cmd, **k: Ran(0, "") if "start" in cmd else real_run(cmd, **k))
    args = SimpleNamespace(bricks=bricks, python="python3", prepare="npm-ci",
                           root_plan={"kind": None, "reason": "none in the test"})
    return SimpleNamespace(args=args, world=FakeTeam.world)


def run_steps(acceptance, driven):
    report = acceptance.Report()
    try:
        acceptance.steps2to7(driven.args, report)
    except RuntimeError:
        pass
    return report


def test_a_failure_in_step_4_leaves_the_real_approved_list_as_it_was(acceptance, driven):
    original = json.dumps(["/usr/libexec/rapportd", "/sbin/launchd"])
    lane.approved_path().write_text(original)
    run_steps(acceptance, driven)
    assert lane.approved_path().read_text() == original


def test_an_approved_list_that_never_existed_does_not_appear_either(acceptance, driven):
    assert not lane.approved_path().exists()
    run_steps(acceptance, driven)
    assert not lane.approved_path().exists()


def test_an_approved_list_that_cannot_be_read_is_never_touched(acceptance, driven, monkeypatch):
    lane.approved_path().write_text("[]")
    lane.approved_path().chmod(0)
    try:
        report = run_steps(acceptance, driven)
    finally:
        lane.approved_path().chmod(0o600)
    assert lane.approved_path().read_text() == "[]"
    assert acceptance.NOT_READ is not None and any(r[2] == "BROKEN" and r[0] == 4 for r in report.rows)


# ---- Critical 2: the download row ----

def test_the_download_row_needs_a_control_and_a_download_that_began(acceptance):
    ok = json.dumps({"control": {"set": 2, "began": True, "states": ["completed"]},
                     "home": {"set": 2, "began": True, "states": ["canceled"]}})
    assert acceptance.download_verdict(0, ok, [], True, [])[0] == "PASS"
    verdict, detail = acceptance.download_verdict(0, ok, ["Unconfirmed 12345.crdownload", acceptance.WRITE_PROBE], True, [])
    assert verdict == "FAIL" and "Unconfirmed 12345.crdownload" in detail and acceptance.WRITE_PROBE in detail
    assert acceptance.download_verdict(0, ok, [], False, [])[0] == "BROKEN"                       # the control never landed
    never = json.dumps({"control": {"set": 1, "began": True, "states": []}, "home": {"set": 1, "began": False, "states": []}})
    assert acceptance.download_verdict(0, never, [], True, [])[0] == "BROKEN"                      # nothing was tried
    assert acceptance.download_verdict(0, ok, [], True, ["/home/x/superyak-lane-acceptance-download.txt"])[0] == "BROKEN"
    assert acceptance.download_verdict(2, "broken: no cdp", [], True, [])[0] == "BROKEN"
    # N6: unrelated new names in $HOME are not download-shaped and do not fail the row
    assert acceptance.download_verdict(0, ok, [".zsh_history", "notes.txt", ".DS_Store"], True, [])[0] == "PASS"
    stem, ext = os.path.splitext(acceptance.WRITE_PROBE)
    assert acceptance.download_verdict(0, ok, ["%s (1)%s" % (stem, ext)], True, [])[0] == "FAIL"
    # N7: a $HOME download that set no behaviour, or landed in b/, proves nothing
    unset = json.dumps({"control": {"set": 2, "began": True, "states": []}, "home": {"set": 0, "began": True, "states": []}})
    assert acceptance.download_verdict(0, unset, [], True, [])[0] == "BROKEN"
    assert acceptance.download_verdict(0, ok, [], True, [], home_in_b=True)[0] == "BROKEN"
    assert acceptance.download_verdict(1, "not json", [], True, [])[0] == "BROKEN"


# ---- Critical 3: steps 2-3 judge refusals by their codes ----

def test_a_negative_row_passes_only_with_a_refusal_code_it_expects(acceptance):
    row = lambda code, detail, refusals=None, expect="fail": {"probe": "p", "expect": expect, "code": code, "detail": detail,
                                                               "refusals": refusals}
    net = list(worker_probes_module().NET_REFUSALS)
    assert acceptance.judge_row(row(1, "refused: EPERM (x)", net)) == "PASS"
    assert acceptance.judge_row(row(1, "refused: ENOENT (x)", net)) == "BROKEN"                  # a refusal for another reason
    assert acceptance.judge_row(row(2, "broken: timeout", net)) == "BROKEN"
    assert acceptance.judge_row(row(-1, "timed out", net)) == "BROKEN"
    assert acceptance.judge_row(row(0, "succeeded", net)) == "FAIL"
    assert acceptance.judge_row(row(1, "refused: NotAllowedError")) == "PASS"                    # the client proved it itself
    assert acceptance.judge_row(row(0, "fine", expect="ok")) == "PASS"
    assert acceptance.judge_row(row(1, "refused: EPERM", expect="ok")) == "FAIL"
    assert acceptance.judge_row(row(0, "x", expect="info")) == "INFO"


def worker_probes_module():
    import worker_probes
    return worker_probes


def test_worker_probe_results_separate_refused_from_broken(tmp_path):
    wp = worker_probes_module()
    assert wp.classify(0, "succeeded") == (0, "succeeded")
    assert wp.classify(1, "refused: EPERM (x)") == (1, "refused: EPERM (x)")
    assert wp.classify(1, "something else")[0] == 2 and wp.classify(124, "")[0] == 2
    assert wp.curl_result(7, "Operation not permitted")[1].startswith("refused: curl-7")
    assert wp.curl_result(28, "timed out")[0] == 2 and wp.curl_result(0, "")[0] == 0
    missing = wp.can_read(str(tmp_path / "missing"))
    assert missing[0] == 1 and missing[1].startswith("refused: ENOENT")


def test_the_driver_checks_the_world_before_blaming_the_sandbox(acceptance, tmp_path):
    srv = tmp_path / "ok.sock"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(srv))
    s.listen(1)
    dead = tmp_path / "dead.sock"
    d = socket.socket(socket.AF_UNIX)
    d.bind(str(dead))
    d.close()
    try:
        ok, bad = acceptance.usable_sockets([str(srv), str(dead), str(tmp_path / "none.sock")])
    finally:
        s.close()
    assert ok == [str(srv)] and sorted(name for name, _ in bad) == sorted([str(dead), str(tmp_path / "none.sock")])


import socket  # noqa: E402


def test_the_dotfile_for_the_file_row_must_have_content(acceptance, tmp_path):
    home, other, decoy = tmp_path / "home", tmp_path / "o", tmp_path / "d"
    for f in (home, other, decoy):
        f.mkdir()
    (home / ".zshrc").write_text("")
    present, missing = acceptance.read_targets(other, decoy, 424242, home=home)
    assert "a dotfile in $HOME" not in present and "a dotfile in $HOME" in missing
    (home / ".bashrc").write_text("x\n")
    assert acceptance.read_targets(other, decoy, 424242, home=home)[0]["a dotfile in $HOME"] == str(home / ".bashrc")


# ---- Critical 4: hardlink-naming looks at the inode, through the lane's own path ----

def test_the_hardlink_row_finds_the_holders_descriptor_by_inode(acceptance, world, monkeypatch):
    seen = {}
    real = lane.lane_pids

    def spy(path, base):
        seen["linked"] = (path / "tmp" / "linked.txt").exists()
        return real(path, base)
    monkeypatch.setattr(lane, "lane_pids", spy)
    verdict, detail = acceptance.hardlink_naming()
    assert verdict == "PASS" and seen["linked"] and "descriptor" in detail and "lsof reports" in detail


def test_a_holder_whose_inode_lsof_never_lists_is_broken_not_passed(acceptance, world, monkeypatch):
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, "p1\nf3\ni99999999\nn/nowhere\n"))
    assert acceptance.hardlink_naming()[0] == "BROKEN"


# ---- Important 1: the denial stream ----

STREAM = """
import sys, time, signal
signal.signal(signal.SIGINT, lambda *a: sys.exit(0))
print("Filtering the log data using ...", flush=True)
time.sleep(0.6)
print("Sandbox: node(812) deny(1) file-write-create /Users/me/x", flush=True)
time.sleep(0.6)
print("Sandbox: node(813) deny(1) process-exec* /usr/bin/open", flush=True)
time.sleep(60)
"""


def test_the_denial_stream_is_drained_from_the_start_and_read_until_quiet(acceptance):
    proc = sp.Popen([sys.executable, "-c", STREAM], stdout=sp.PIPE, stderr=sp.DEVNULL, text=True)
    stream = acceptance.DenialStream(proc)
    assert stream.wait_ready(10) is True
    t0 = time.monotonic()
    lines = stream.finish(quiet=1.5, cap=15)
    assert time.monotonic() - t0 < 10
    assert [l for l in lines if "deny" in l] == ["Sandbox: node(812) deny(1) file-write-create /Users/me/x",
                                                  "Sandbox: node(813) deny(1) process-exec* /usr/bin/open"]
    assert proc.poll() is not None                                           # stopped (SIGINT), not left running


def test_a_missing_denial_stream_is_reported_as_unavailable(acceptance):
    stream = acceptance.DenialStream(None)
    assert stream.wait_ready(1) is False and stream.finish() == [] and not stream.available


def test_a_probes_whole_family_is_matched_against_the_denials(acceptance, capsys):
    recorder = acceptance.PidRecorder()
    r = recorder([sys.executable, "-c", "import sys; sys.stderr.write('child pid 777\\n'); print('refused: EPERM')", "exec_open_calculator"],
                 timeout=30)
    assert recorder.pids[0][0] == "exec_open_calculator" and recorder.pids[-1][2] == 777
    assert recorder.pids_of("exec_open_calculator") == [recorder.pids[0][2], 777]
    report = acceptance.Report()
    acceptance.report_profile_rows(report, [("exec_open_calculator", "BROKEN", "refused: nocode")], recorder,
                                   ["Sandbox: open(777) deny(1) process-exec* /usr/bin/open"])
    assert "open(777): process-exec* /usr/bin/open" in capsys.readouterr().out


# ---- Important 3: the cross-lane check ----

def test_only_processes_that_hold_the_endpoint_are_targets(acceptance):
    env = {10: ["A=1", "PW_TEST_CONNECT_WS_ENDPOINT=ws://127.0.0.1:41031/x"], 11: ["A=1"], 12: None}
    holders, others = acceptance.peer_targets([10, 11, 12], env.get)
    assert holders == [10] and others == [11, 12]


def test_the_first_lane_holds_its_round_open_until_the_marker_appears(tmp_path):
    wp = worker_probes_module()
    marker = tmp_path / "peer-done"
    assert wp.hold(str(marker), 0.3) is False                                  # bounded: never waits forever
    threading.Timer(0.3, lambda: marker.write_text("x")).start()
    assert wp.hold(str(marker), 10) is True


# ---- Important 4 and 5: the root listener ----

PS = """  900   1 /usr/bin/sudo -n /usr/bin/nc -l 127.0.0.1 5555
  901 900 /usr/bin/nc -l 127.0.0.1 5555
  902 900 /bin/sleep 5
  950   1 /usr/bin/nc -l 127.0.0.1 6666
"""


def test_a_root_listener_must_be_root_owned_and_invisible_to_lsof(acceptance, monkeypatch):
    monkeypatch.setattr(lane, "lsof_listeners", lambda: {(901, 5555)})
    verdict, detail = acceptance.root_listener_proof(901, 5555, owner=lambda pid: 0)
    assert verdict == "BROKEN" and "lsof" in detail                            # lsof sees it: netstat isn't what saw it
    monkeypatch.setattr(lane, "lsof_listeners", lambda: set())
    assert acceptance.root_listener_proof(901, 5555, owner=lambda pid: 501)[0] == "BROKEN"
    assert acceptance.root_listener_proof(901, 5555, owner=lambda pid: 0)[0] == "PASS"


def test_sudo_is_refreshed_while_the_run_lasts(acceptance):
    calls = []
    keeper = acceptance.SudoKeeper(run=lambda cmd, **k: calls.append(cmd) or Ran(0), every=0.05)
    assert keeper.start() is True
    time.sleep(0.3)
    keeper.stop()
    n = len(calls)
    time.sleep(0.2)
    assert n >= 3 and len(calls) == n and calls[0] == ["/usr/bin/sudo", "-n", "-v"] and calls[-1] == ["/usr/bin/sudo", "-n", "-v"]
    assert acceptance.SudoKeeper(run=lambda cmd, **k: Ran(1)).start() is False


# ---- Important 6: step 7 needs evidence ----

def test_cleanup_rows_need_evidence_and_fail_on_leftovers(acceptance, world, monkeypatch):
    w = {"lane": {"base": 41000, "path": str(world["tmp"] / "gone")}}
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: set())
    monkeypatch.setattr(lane, "env_pids", lambda name, value: set())
    monkeypatch.setattr(lane, "read_listeners", lambda: [])
    report = acceptance.Report()
    acceptance.check_cleanup(report, "after worker_done", w, {5000, 5001, 5002}, {5000})
    assert {r[1].split(": ")[1]: r[2] for r in report.rows} == {
        "nothing listens on the lane's ports": "PASS", "broker and webServer gone": "PASS",
        "no lane process is left": "PASS", "lane folder gone": "PASS"}
    # only the broker's pid was ever recorded: "gone" proves nothing about the web server
    report = acceptance.Report()
    acceptance.check_cleanup(report, "x", w, {5000}, {5000})
    assert [r[2] for r in report.rows if "webServer" in r[1]] == ["BROKEN"]
    # netstat or lsof unable to say is BROKEN, and a leftover is FAIL
    monkeypatch.setattr(lane, "read_listeners", lambda: None)
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: None)
    report = acceptance.Report()
    acceptance.check_cleanup(report, "x", w, {5000, 5001}, {5000})
    assert {r[1].split(": ")[1]: r[2] for r in report.rows}["nothing listens on the lane's ports"] == "BROKEN"
    assert {r[1].split(": ")[1]: r[2] for r in report.rows}["no lane process is left"] == "BROKEN"
    monkeypatch.setattr(lane, "read_listeners", lambda: [{"pid": 7, "command": "", "host": "127.0.0.1", "port": 41005}])
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: {7})
    report = acceptance.Report()
    acceptance.check_cleanup(report, "x", w, {5000, 5001}, {5000})
    got = {r[1].split(": ")[1]: r[2] for r in report.rows}
    assert got["nothing listens on the lane's ports"] == "FAIL" and got["no lane process is left"] == "FAIL"


# ---- Important 7: the netstat fixture keeps no private address ----

def test_the_netstat_fixture_redacts_lan_and_tailnet_addresses(acceptance):
    hdr = NETSTAT_NAMED.split("\n")[1]
    row = lambda addr, name: ("tcp4       0      0  %-22s *.*                    LISTEN            0         0  131072 131072 %s   612 "
                              "00180081 00000006 000000000000a001 00000900 00000001      0      0 000000" % (addr, name))
    text = "\n".join(["Active Internet connections (including servers)", hdr,
                      row("100.101.102.103.8080", "tailscaled:333"), row("192.168.1.23.5000", "rapportd:612"),
                      row("fe80::1c2b:3aff:fe4d:5e6f%en0.7000", "rapportd:612"), row("127.0.0.1.631", "rapportd:612"),
                      row("*.49152", "rapportd:612")]) + "\n"
    lines = acceptance.netstat_fixture(text, lambda pid: "/usr/libexec/rapportd", rows=5)
    joined = "\n".join(lines)
    for private in ("100.101.102", "192.168.1", "fe80", "5e6f"):
        assert private not in joined
    assert "<addr>.8080" in joined and "127.0.0.1.631" in joined and "*.49152" in joined


# ---- Important 8: --list-listeners and load_approved agree ----

@pytest.mark.parametrize("path", [
    "/System/Library/CoreServices/CoreTypes.bundle/Contents/Library/Foo.app/Contents/MacOS/Foo",
    "/System/Volumes/Data/x", "/usr/libexec/../libexec/rapportd", "/usr/libexec/python3", "/usr/libexec/cups/daemon/x",
    "/usr/libexec/rapportd", "/sbin/launchd"])
def test_what_is_listed_as_approvable_is_what_load_approved_accepts(acceptance, world, path):
    rows = acceptance.listener_rows([{"pid": 50, "command": "", "host": "*", "port": 9}], {50: path}.get, set())
    lane.approved_path().parent.mkdir(parents=True, exist_ok=True)
    lane.approved_path().write_text(json.dumps([path]))
    try:
        lane.load_approved()
        accepted = True
    except lane.LaneRefused:
        accepted = False
    assert rows[0][3].startswith("approvable") == accepted
    assert (lane.approval_problem(path) == "") == accepted


# ---- Important 9: an interrupted run restores and still reports ----

def test_sigterm_and_sighup_raise_so_every_finally_runs(acceptance):
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        acceptance.install_signal_handlers()
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with pytest.raises(SystemExit):
                signal.raise_signal(sig)
    finally:
        for s, h in old.items():
            signal.signal(s, h)


def test_main_prints_its_summary_even_when_the_run_raises(acceptance, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(acceptance.sys, "platform", "darwin")
    monkeypatch.setattr(lane, "python_ok", lambda: True)
    monkeypatch.setattr(acceptance, "step1", lambda args, report: (_ for _ in ()).throw(KeyError("boom")))
    monkeypatch.setattr(acceptance.sys, "argv", ["lane_acceptance.py", "--bricks", str(tmp_path)])
    assert acceptance.main() == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "the run stopped" in out


# ---- Important 10: privacy ----

def test_an_endpoint_never_reaches_the_transcript(acceptance, capsys):
    secret = "ab" * 32
    report = acceptance.Report()
    report.add(3, "browser page", "FAIL", "refused: connect ws://127.0.0.1:41031/%s failed" % secret,
               notes=["ws://127.0.0.1:41031/%s" % secret])
    out = capsys.readouterr().out
    assert secret not in out and "ws://127.0.0.1:41031/" in out
    assert secret not in repr(report.rows)


def test_the_leads_inbox_is_summarised_as_reason_codes_never_dumped(acceptance):
    inbox = ["LANE WAITING: kaylee waits ...: tailscaled (pid 5) listens on port 8080 (/Applications/Tailscale.app/x)",
             "/home/me/.superyak/team/lane-listeners.json: '/opt/x/python3' refused: only Apple programs in /System ..."]
    codes = acceptance.reason_codes(inbox)
    assert "LANE WAITING" in codes and "only Apple programs" in codes
    assert not any("Tailscale" in c or "/opt" in c for c in codes)


# ---- Important 11: the verdict helpers, extracted ----

def test_the_rendezvous_verdicts(acceptance):
    assert acceptance.rendezvous_verdict(1100, [], 5)[0] == "PASS"
    assert acceptance.rendezvous_verdict(0, [], 5)[0] == "FAIL"
    assert acceptance.rendezvous_verdict(1102, [], 5)[0] == "BROKEN"
    assert acceptance.rendezvous_verdict(5, ["Sandbox: Python(5) deny(1) mach-lookup org.chromium.Chromium.MachPortRendezvousServer.1"], 5)[0] == "PASS"
    assert acceptance.rendezvous_verdict(5, [], 5)[0] == "FAIL"
    ps = "    1     0 /sbin/launchd\n  700     1 /opt/homebrew/bin/node -e broker\n"
    assert acceptance.rendezvous_pid(ps, 0) is None                              # never launchd's children


def test_a_report_spec_fails_a_missing_report_and_untagged_advisories(acceptance, tmp_path):
    wt = tmp_path / "wt"
    (wt / acceptance.PROBE_DIR).mkdir(parents=True)
    report = acceptance.Report()
    acceptance.report_spec(report, 6, "kaylee", str(wt), ["tests/a.spec.ts"])
    assert report.rows[0][2] == "FAIL" and "no JSON report" in report.rows[0][3]
    msg = {"results": [{"error": {"message": "expected 300 got 280"}}]}
    spec = lambda f, tags: {"title": "t", "file": f, "line": 1, "tags": tags, "tests": [dict(status="unexpected", **msg)]}
    (wt / acceptance.PROBE_DIR / "spec-0.json").write_text(json.dumps({"errors": [], "suites": [{"title": "s", "specs": [
        {"title": "ok", "file": "tests/a.spec.ts", "line": 1, "tags": [], "tests": [{"status": "expected"}]},
        spec("tests/gtm/four-up-school.spec.ts", ["@lane-advisory"]), spec("tests/a.spec.ts", ["@lane-advisory"])]}]}))
    report = acceptance.Report()
    acceptance.report_spec(report, 6, "kaylee", str(wt), ["tests/a.spec.ts"])
    by = {r[1]: r for r in report.rows}
    assert by["kaylee tests/a.spec.ts"][2] == "PASS"
    infos = [r for r in report.rows if r[2] == "INFO"]
    assert len(infos) == 1 and "four-up-school" in infos[0][3] and "expected 300 got 280" in infos[0][3]
    assert [r[2] for r in report.rows if "outside the agreed set" in r[1]] == ["FAIL"]


def test_list_listeners_survives_a_broken_approved_list_and_shows_the_cross_check(acceptance, world, monkeypatch, capsys):
    lane.approved_path().parent.mkdir(parents=True, exist_ok=True)
    lane.approved_path().write_text("{not json")
    monkeypatch.setattr(lane, "read_listeners", lambda: [{"pid": 612, "command": "", "host": "*", "port": 49152}])
    monkeypatch.setattr(lane, "pid_path", lambda pid: "/usr/libexec/rapportd")
    monkeypatch.setattr(lane, "lsof_listeners", lambda: {(612, 49152), (999, 7000)})
    monkeypatch.setattr(lane, "live_lanes", lambda: [(41000, "abc123")])
    acceptance.list_listeners()
    out = capsys.readouterr().out
    assert "rapportd" in out and "approved list is broken" in out and "approvable" in out
    assert "41000" in out and "999" in out and "7000" in out


def test_a_lane_run_skipped_says_why(acceptance, capsys):
    report = acceptance.Report()
    acceptance.report_skipped(report, self_check_only=False, failed=2)
    acceptance.report_skipped(report, self_check_only=True, failed=0)
    assert [r[2] for r in report.rows] == ["INFO", "INFO"] and "step 1" in report.rows[0][3] and "--self-check-only" in report.rows[1][3]


def test_step_1_names_every_probe_that_produced_no_row(acceptance):
    rows = [(p, "PASS", "x") for p in lane.SELF_CHECK_PROBES + lane.SELF_CHECK_POSITIVE if p != "net_ip"]
    assert acceptance.missing_probe_rows(rows) == ["net_ip"]
    assert acceptance.missing_probe_rows(rows + [("net_ip", "BROKEN", "")]) == []


def test_the_interpreter_row_names_its_specific_reason(acceptance):
    assert acceptance.D10_ENTRY.startswith("/usr/sbin/") and lane.approval_problem(acceptance.D10_ENTRY) == \
        "an interpreter is never approved"
    assert "only Apple programs" in lane.approval_problem("/opt/homebrew/bin/python3.13")


def test_a_planted_import_keeps_its_cleanup_rows_on_an_early_return(acceptance, world, monkeypatch):
    broker = world["root"] / "broker"
    pw, shell = broker / "pw", broker / "browsers" / "shell"
    pw.mkdir(parents=True)
    shell.mkdir(parents=True)
    monkeypatch.setattr(lane, "browsers_root", lambda: broker / "browsers")
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=60: Ran(0, ""))
    monkeypatch.setattr(lane, "render_profile", lambda *a, **k: "(version 1)\n")          # no import line to test
    monkeypatch.setattr(lane, "release_block", lambda *a: (_ for _ in ()).throw(OSError("registry gone")))
    rows = acceptance.planted_import(Path("/opt/n/bin/node"), pw, shell, lambda *a, **k: Ran(1, "refused: EPERM"))
    assert [v for _, v, _ in rows[:2]] == ["BROKEN", "BROKEN"] and any(n == "planted-import:cleanup" for n, _, _ in rows)


def test_git_branch_cleanup_errors_do_not_escape(acceptance, tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    acceptance.delete_branches(tmp_path, "t1")                                # no branches, no commits: still no raise
    assert acceptance.git_try(tmp_path, "branch", "-D", "nope") == ""


def test_a_missing_broker_pid_is_a_broken_row_and_never_launchds_child(acceptance):
    report = acceptance.Report()
    pid = acceptance.broker_and_browser_pids(report, "  1  0 /sbin/launchd\n", 0)
    assert pid is None and [r[2] for r in report.rows] == ["BROKEN"]


def test_both_ran_at_the_same_time_needs_a_server_in_each_block(acceptance):
    assert acceptance.both_serving({"kaylee": "running", "wash": "running"}, {"kaylee": {5, 9}, "wash": {6, 8}}, {"kaylee": {5}, "wash": {6}}) is True
    assert acceptance.both_serving({"kaylee": "running", "wash": "running"}, {"kaylee": {5}, "wash": {6, 8}}, {"kaylee": {5}, "wash": {6}}) is False
    assert acceptance.both_serving({"kaylee": "running", "wash": "idle"}, {"kaylee": {5, 9}, "wash": {6, 8}}, {"kaylee": {5}, "wash": {6}}) is False


# ================= Fix round 2 =================

# ---- N1: the download override targets the page's own browser context ----

def test_the_download_override_targets_the_pages_own_context():
    """Playwright gives browser.newPage() a NEW context with its own download behaviour; an override sent for the
    contexts listed before the page existed never reaches it. The module is run by node with fake CDP sessions."""
    script = r"""
const { overrideDownloads } = require(process.argv[1]);
const calls = [];
const cdp = { send: async (m, p) => { calls.push([m, p]); return {}; } };
const page = { send: async (m) => m === 'Target.getTargetInfo' ? { targetInfo: { browserContextId: 'CTX-OF-THE-PAGE' } } : {} };
(async () => {
  const set = await overrideDownloads(cdp, page, '/lane/b');
  const none = await overrideDownloads(cdp, { send: async () => ({ targetInfo: {} }) }, '/lane/b');
  console.log(JSON.stringify({ set, none, calls }));
})();
"""
    r = subprocess.run(["node", "-e", script, str(SCRIPTS / "lane_acceptance" / "download_override.js")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["set"] == 1 and got["none"] == 0
    assert got["calls"] == [["Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": "/lane/b",
                                                             "eventsEnabled": True, "browserContextId": "CTX-OF-THE-PAGE"}]]


def test_the_client_uses_that_module_and_not_the_contexts_listed_before_the_page():
    text = (SCRIPTS / "lane_acceptance" / "broker_client.js").read_text()
    assert "download_override" in text and "Target.getBrowserContexts" not in text


# ---- N2: a link the sandbox refuses to create is a refusal ----

def test_a_link_the_sandbox_refuses_to_make_passes_and_other_failures_do_not(acceptance):
    import errno as errno_
    wp = worker_probes_module()
    for code in (errno_.EPERM, errno_.EACCES):
        result, refusals = wp.link_failure(OSError(code, "x"))
        row = {"probe": "hard link", "expect": "fail", "code": result[0], "detail": result[1], "refusals": refusals}
        assert acceptance.judge_row(row) == "PASS" and "sandbox refused the link" in result[1]
    result, refusals = wp.link_failure(OSError(errno_.EXDEV, "x"))
    row = {"probe": "hard link", "expect": "fail", "code": result[0], "detail": result[1], "refusals": refusals}
    assert acceptance.judge_row(row) == "BROKEN"
    result, refusals = wp.link_failure(OSError(errno_.ENOENT, "x"))
    assert acceptance.judge_row({"probe": "p", "expect": "fail", "code": result[0], "detail": result[1], "refusals": refusals}) == "BROKEN"


# ---- N3: the root nc is stopped even under a sudo pty ----

PTY_TREE = ("  900     1 /usr/bin/sudo -n /usr/bin/nc -l 127.0.0.1 5555\n"
            "  901   900 /usr/bin/sudo -n /usr/bin/nc -l 127.0.0.1 5555\n"       # sudo's monitor (use_pty)
            "  902   901 /usr/bin/nc -l 127.0.0.1 5555\n"
            "  950     1 /usr/bin/nc -l 127.0.0.1 6666\n")


def test_nc_is_found_in_sudos_descendants_whatever_the_depth(acceptance):
    assert acceptance.nc_descendants(PTY_TREE, 900, 5555) == [902]
    flat = "  900   1 /usr/bin/sudo -n /usr/bin/nc -l 127.0.0.1 5555\n  901 900 /usr/bin/nc -l 127.0.0.1 5555\n"
    assert acceptance.nc_descendants(flat, 900, 5555) == [901]
    assert acceptance.nc_descendants(PTY_TREE, 900, 6666) == []                    # not another nc, not another port
    assert acceptance.nc_descendants(PTY_TREE, 1, 5555) == []


def test_stopping_the_root_listener_signals_sudo_then_the_nc_and_checks_the_port(acceptance):
    killed, said = [], []
    state = {"up": True}

    def kill(pid):
        killed.append(pid)
        if pid == 902:
            state["up"] = False
    root = SimpleNamespace(pid=900, wait=lambda timeout=None: 0)
    acceptance.stop_root_listener(root, 5555, ps=lambda: PTY_TREE, kill=kill, listening=lambda port: state["up"], say=said.append)
    assert killed == [900, 902] and said == []
    # still listening after everything: say loudly how to stop it by hand
    said.clear()
    acceptance.stop_root_listener(root, 5555, ps=lambda: PTY_TREE, kill=lambda pid: None, listening=lambda port: True,
                                  say=said.append)
    assert any("STILL LISTENING" in line and "5555" in line and "sudo kill" in line and "902" in line for line in said)


def test_stopping_a_sudo_that_will_not_exit_is_reported(acceptance):
    said = []
    root = SimpleNamespace(pid=900, wait=lambda timeout=None: (_ for _ in ()).throw(sp.TimeoutExpired("sudo", 1)))
    acceptance.stop_root_listener(root, 5555, ps=lambda: PTY_TREE, kill=lambda pid: None, listening=lambda port: False,
                                  say=said.append)
    assert any("900" in line and "by hand" in line for line in said)


# ---- N4: an existing root-owned listener first; sudo only if there is none ----

ROOT_LISTENERS = [{"pid": 1, "command": "", "host": "*", "port": 22}, {"pid": 612, "command": "", "host": "*", "port": 49152},
                  {"pid": 300, "command": "", "host": "::1", "port": 631}, {"pid": 700, "command": "", "host": "127.0.0.1", "port": 8000}]


def test_an_existing_root_owned_reachable_listener_is_used_without_sudo(acceptance):
    sudo_calls = []
    plan = acceptance.choose_root_listener(
        read=lambda: ROOT_LISTENERS, owner=lambda pid: {1: 0, 612: 501, 300: 0, 700: 501}[pid],
        path_of={1: "/sbin/launchd", 300: "/usr/sbin/cupsd"}.get, run=lambda cmd, **k: sudo_calls.append(cmd) or Ran(1))
    assert plan["kind"] == "existing" and (plan["pid"], plan["port"], plan["exe"]) == (1, 22, "/sbin/launchd")
    assert sudo_calls == []


def test_without_an_existing_root_listener_sudo_n_decides(acceptance):
    user_only = [item for item in ROOT_LISTENERS if item["pid"] in (612, 700)]
    calls = []
    plan = acceptance.choose_root_listener(read=lambda: user_only, owner=lambda pid: 501, path_of=lambda pid: "/x",
                                           run=lambda cmd, **k: calls.append(cmd) or Ran(0))
    assert plan == {"kind": "sudo"} and calls == [["/usr/bin/sudo", "-n", "-v"]]


def test_with_neither_the_root_rows_say_what_to_do(acceptance):
    plan = acceptance.choose_root_listener(read=lambda: [], owner=lambda pid: 501, path_of=lambda pid: "/x",
                                           run=lambda cmd, **k: Ran(1))
    assert plan == {"kind": "person"}                                           # Andy starts one in his own terminal
    # a netstat that fails is not "none exist": the same plan, never a crash
    assert acceptance.choose_root_listener(read=lambda: None, owner=lambda pid: 0, path_of=lambda pid: "/x",
                                           run=lambda cmd, **k: Ran(1))["kind"] == "person"


def test_an_unreachable_or_unidentified_root_listener_does_not_count(acceptance):
    odd = [{"pid": 5, "command": "", "host": "100.101.102.103", "port": 9}, {"pid": 6, "command": "", "host": "*", "port": 10}]
    plan = acceptance.choose_root_listener(read=lambda: odd, owner=lambda pid: 0, path_of=lambda pid: None,
                                           run=lambda cmd, **k: Ran(1))
    assert plan["kind"] == "person"


def test_step_4_without_a_root_listener_reports_the_reason_broken(acceptance, driven, monkeypatch):
    """The fake team stops step 4 before the root rows, so test the rows through their own function."""
    report = acceptance.Report()
    acceptance.root_rows_unavailable(report, "no root-owned listener to observe; run this once from Andy's own terminal (sudo)")
    assert [(r[1], r[2]) for r in report.rows] == [("a root-owned listener is seen", "BROKEN"),
                                                    ("it holds the lane, named by its path", "BROKEN")]
    assert "Andy's own terminal" in report.rows[0][3]


def test_the_docs_say_who_runs_it_and_when_a_terminal_is_needed(acceptance):
    text = (SCRIPTS / "lane_acceptance.py").read_text().split('"""')[1]
    readme = (SCRIPTS.parent / "README.md").read_text()
    for doc in (text, readme):
        assert "Serenity" in doc and "root-owned listener" in doc and "Andy's own terminal" in doc
        assert "ANDY ACTION" in doc and "background" in doc


# ---- the advisory set (from the Bricks lead) ----

def test_the_advisory_set_is_the_agreed_files(acceptance, tmp_path):
    assert acceptance.ADVISORY_SPECS == ("tests/gtm/approval-anatomy.spec.ts", "tests/gtm/four-up-school.spec.ts",
                                         "tests/gtm/content-recipes-cards.spec.ts", "tests/gtm/supplied-presentation.spec.ts",
                                         "tests/gtm/visual.spec.ts")
    source = (SCRIPTS / "lane_acceptance.py").read_text()
    assert "visual-recipes" in source and "pending" in source                     # the comment about what is still open
    wt = tmp_path / "wt"
    (wt / acceptance.PROBE_DIR).mkdir(parents=True)
    spec = lambda f: {"title": "t", "file": f, "line": 1, "tags": ["@lane-advisory"],
                      "tests": [{"status": "unexpected", "results": [{"error": {"message": "m"}}]}]}
    files = ["gtm/approval-anatomy.spec.ts", "gtm/visual.spec.ts", "gtm/visual-recipes.spec.ts", "a.spec.ts"]
    (wt / acceptance.PROBE_DIR / "spec-0.json").write_text(json.dumps({"config": {"rootDir": str(wt / "tests")}, "errors": [], "suites": [{"title": "s", "specs":
        [{"title": "ok", "file": "a.spec.ts", "line": 1, "tags": [], "tests": [{"status": "expected"}]}] + [spec(f) for f in files]}]}))
    report = acceptance.Report()
    acceptance.report_spec(report, 6, "kaylee", str(wt), ["tests/a.spec.ts"])
    assert [r[2] for r in report.rows if "reported separately" in r[1]] == ["INFO", "INFO"]
    assert [r[2] for r in report.rows if "outside the agreed set" in r[1]] == ["FAIL", "FAIL"]


# ---- N5: only this run's team socket ----

def test_only_this_runs_team_socket_is_a_candidate(acceptance, tmp_path, monkeypatch):
    mine, other = tmp_path / "mine.sock", tmp_path / "other.sock"
    for f in (mine, other):
        f.write_text("")
    monkeypatch.setattr(acceptance.teamlib, "sock_path", lambda team_id: mine if team_id == "t1" else other)
    got = acceptance.socket_candidates("t1", {"SSH_AUTH_SOCK": "/tmp/agent.sock"}, tmp_path / "nohome")
    assert got[0] == "/tmp/agent.sock" and str(mine) in got and str(other) not in got


# ---- N8: preflight the probes' own targets ----

def test_preflight_tries_the_targets_the_probes_use(acceptance):
    tried = []
    ok = acceptance.reach_targets(connect=lambda addr, timeout=3: tried.append(addr) or SimpleNamespace(close=lambda: None),
                                  resolve=lambda host, port: tried.append(("resolve", host)) or [1])
    assert ok == [] and ("1.1.1.1", 80) in tried and ("resolve", "example.com") in tried
    failed = acceptance.reach_targets(connect=lambda addr, timeout=3: (_ for _ in ()).throw(OSError("no route")),
                                      resolve=lambda host, port: [1])
    assert any("1.1.1.1:80" in f for f in failed)


# ---- N9: exec denials by program path and time window ----

def test_a_refused_exec_is_matched_by_program_and_time_when_the_pid_is_unknown(acceptance, capsys):
    lines = ["2026-10-09 12:00:05.100 Df kernel[0:1] Sandbox: node(901) deny(1) process-exec* /usr/bin/open",
             "2026-10-09 12:00:05.200 Df kernel[0:1] Sandbox: node(902) deny(1) process-exec* /usr/bin/osascript",
             "2026-10-09 12:30:00.000 Df kernel[0:1] Sandbox: node(903) deny(1) process-exec* /usr/bin/open",
             "2026-10-09 12:00:05.300 Df kernel[0:1] Sandbox: node(904) deny(1) file-read-data /etc/hosts"]
    start = time.mktime(time.strptime("2026-10-09 12:00:04", "%Y-%m-%d %H:%M:%S"))
    got = acceptance.exec_denials(lines, "/usr/bin/open", start, start + 3)
    assert got == ["node(901): process-exec* /usr/bin/open"]
    recorder = acceptance.PidRecorder()
    recorder.pids = [("exec_open_calculator", False, 800)]
    recorder.windows = [("exec_open_calculator", False, start, start + 3)]
    report = acceptance.Report()
    acceptance.report_profile_rows(report, [("exec_open_calculator", "BROKEN", "refused: nocode")], recorder, lines)
    assert "node(901): process-exec* /usr/bin/open" in capsys.readouterr().out


# ---- N10: presets are restored before the team ends, and an error ending it is caught ----

def test_presets_are_back_before_the_team_is_ended(acceptance, driven, monkeypatch):
    from superyak_team import teamlib
    seen = {}
    original = FakeTeam.call

    def call(self, *a, **k):
        if a and a[0] == "end":
            seen["presets_exist"] = teamlib.presets_path().exists()
            raise ValueError("end blew up")
        return original(self, *a, **k)
    monkeypatch.setattr(FakeTeam, "call", call)
    run_steps(acceptance, driven)                                               # nothing escapes the finally
    assert seen == {"presets_exist": False}


# ---- N11: a proxy is easy to see ----

def test_curl_exits_22_and_56_say_proxy(acceptance):
    wp = worker_probes_module()
    for rc in (22, 56):
        code, text = wp.curl_result(rc, "x")
        assert code == 2 and "proxy?" in text


# ---- N12: only claude and the probe process are peer targets ----

def test_peer_targets_are_claude_and_the_probe_process_only(acceptance):
    env = {10: ["PW_TEST_CONNECT_WS_ENDPOINT=x"], 11: ["PW_TEST_CONNECT_WS_ENDPOINT=x"], 12: ["PW_TEST_CONNECT_WS_ENDPOINT=x"]}
    commands = {10: "claude --print", 11: "python3 node_modules/.superyak-lane-acceptance/worker_probes.py lane",
                12: "/bin/bash -c sleep 100"}
    holders, others = acceptance.peer_targets([10, 11, 12], env.get, command=commands.get)
    assert holders == [10, 11] and others == [12]


# ---- N13: brokers are identified by their port ----

def test_a_broker_is_every_process_on_its_port_not_the_first(acceptance, monkeypatch):
    ps = "  800     1 /usr/bin/node broker\n  801   800 /x/chrome-headless-shell --headless\n"
    report = acceptance.Report()
    assert acceptance.broker_and_browser_pids(report, ps, {799, 800}) == 801 and report.rows == []
    monkeypatch.setattr(lane, "read_listeners", lambda: [])
    monkeypatch.setattr(lane, "lane_pids", lambda path, base: set())
    monkeypatch.setattr(lane, "env_pids", lambda name, value: set())
    monkeypatch.setattr(acceptance, "alive", lambda pid: False)
    w = {"lane": {"base": 41000, "path": "/nonexistent/lane"}}
    report = acceptance.Report()                                           # a webServer pid (9000) besides every broker pid
    acceptance.check_cleanup(report, "x", w, {799, 800, 801, 9000}, {799, 800, 801})
    assert [r[2] for r in report.rows if "webServer" in r[1]] == ["PASS"]
    report = acceptance.Report()                                           # only broker pids: nothing about the web server
    acceptance.check_cleanup(report, "x", w, {799, 800}, {799, 800})
    assert [r[2] for r in report.rows if "webServer" in r[1]] == ["BROKEN"]


# ================= Fix round 3 =================

# ---- 1. the person plan ----

class PersonWorld:
    """A fake clock, listener table and owner for the person flow. `script` decides what netstat shows at time t."""

    def __init__(self, appear_at=None, owner=0, gone_after_stop=None, port=55555):
        self.t, self.port, self.owner = 0.0, port, owner
        self.appear_at, self.gone_after_stop, self.stopped_at = appear_at, gone_after_stop, None
        self.said, self.inbox = [], []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def say(self, line, **k):
        self.said.append(line)
        if "stop it now" in line:
            self.stopped_at = self.t

    def listening(self):
        if self.appear_at is None or self.t < self.appear_at:
            return False
        if self.stopped_at is not None and self.gone_after_stop is not None and self.t >= self.stopped_at + self.gone_after_stop:
            return False
        return True

    def read(self):
        return [{"pid": 4321, "command": "", "host": "127.0.0.1", "port": self.port}] if self.listening() else []

    # the team
    def message(self, wid, text):
        self.inbox.append("LANE WAITING: kaylee waits ...: nc (pid 4321) listens on port %d (/usr/bin/nc)" % self.port)

    def wait(self, wid, states, timeout=900, patient=False):
        return states[0]


def run_person(acceptance, monkeypatch, world, **kw):
    monkeypatch.setattr(acceptance, "root_listener_proof", lambda pid, port: ("PASS", "pid %d (uid 0) on port %d" % (pid, port)))
    world.team = SimpleNamespace(message=world.message, wait=world.wait, inbox=world.inbox)
    report = acceptance.Report()
    error = None
    try:
        acceptance.person_root_rows(report, world.team, read=world.read, path_of=lambda pid: "/usr/bin/nc",
                                    owner=lambda pid: world.owner, clock=world.clock, sleep=world.sleep, say=world.say,
                                    pick_port=lambda: world.port, port_free=lambda port: True, **kw)
    except RuntimeError as e:
        error = e
    return report, error


def never_signals(monkeypatch, acceptance):
    """The person's listener is never signalled by the script: any subprocess.run would be a kill or a sudo."""
    def boom(*a, **k):
        raise AssertionError("the script ran %r" % (a,))
    monkeypatch.setattr(acceptance.subprocess, "run", boom)
    monkeypatch.setattr(acceptance.os, "kill", boom)


def test_person_plan_a_root_nc_appears_is_seen_named_and_gone(acceptance, monkeypatch, capsys):
    world = PersonWorld(appear_at=30, owner=0, gone_after_stop=20)
    never_signals(monkeypatch, acceptance)
    report, error = run_person(acceptance, monkeypatch, world)
    assert error is None
    assert [(r[1], r[2]) for r in report.rows] == [("a root-owned listener is seen", "PASS"),
                                                    ("it holds the lane, named by its path", "PASS"),
                                                    ("the root-owned listener is gone", "PASS")]
    assert world.said[0] == "ANDY ACTION: in your own Terminal run: sudo /usr/bin/nc -lk 127.0.0.1 55555"
    assert world.said[1] == "(leave it running; this run waits up to 15 minutes)"
    assert "ANDY ACTION: stop it now: press Ctrl-C in that Terminal" in world.said


def test_person_plan_a_nc_started_without_sudo_is_broken_and_still_asked_to_stop(acceptance, monkeypatch):
    world = PersonWorld(appear_at=10, owner=501, gone_after_stop=5)
    never_signals(monkeypatch, acceptance)
    report, error = run_person(acceptance, monkeypatch, world)
    assert error is None
    assert [r[2] for r in report.rows[:2]] == ["BROKEN", "BROKEN"] and "started without sudo" in report.rows[0][3]
    assert any("stop it now" in line for line in world.said)


def test_person_plan_nothing_by_the_deadline_makes_both_rows_broken(acceptance, monkeypatch):
    """T10 (c): at the deadline Andy may have started it anyway (on another port, too late): he is told to stop it."""
    world = PersonWorld(appear_at=None)
    report, error = run_person(acceptance, monkeypatch, world)
    assert error is None and [r[2] for r in report.rows] == ["BROKEN", "BROKEN"]
    assert world.t >= 900
    assert world.said[-1] == "ANDY ACTION: stop it now (if you started it): press Ctrl-C in that Terminal"


def test_person_plan_a_listener_that_is_never_stopped_stops_the_run_with_the_pid(acceptance, monkeypatch):
    world = PersonWorld(appear_at=10, owner=0, gone_after_stop=None)
    never_signals(monkeypatch, acceptance)
    report, error = run_person(acceptance, monkeypatch, world)
    assert isinstance(error, RuntimeError)
    last = report.rows[-1]
    assert last[2] == "BROKEN" and "4321" in last[3] and "sudo kill 4321" in last[3]
    assert world.t >= 10 + 600                                                   # it waited up to 10 minutes for the stop


def test_person_plan_rechecks_the_port_right_before_printing(acceptance, monkeypatch):
    world = PersonWorld(appear_at=None)
    ports, checks = iter([50001, 50002]), []
    monkeypatch.setattr(acceptance, "root_listener_proof", lambda pid, port: ("PASS", ""))
    report = acceptance.Report()
    acceptance.person_root_rows(report, SimpleNamespace(message=world.message, wait=world.wait, inbox=[]), read=world.read,
                                path_of=lambda pid: None, owner=lambda pid: 0, clock=world.clock, sleep=world.sleep,
                                say=world.say, pick_port=lambda: next(ports), port_free=lambda p: checks.append(p) or p == 50002)
    assert checks == [50001, 50002] and "127.0.0.1 50002" in world.said[0]


# ---- 2 and 3 and 4: the approved list ----

def test_an_unreadable_list_is_checked_before_it_is_parsed(acceptance, world, monkeypatch):
    monkeypatch.setattr(lane, "read_listeners", lambda: [{"pid": 1, "port": 22, "host": "*", "command": ""}])
    monkeypatch.setattr(acceptance, "root_listener_proof", lambda pid, port: ("PASS", "ok"))
    al = acceptance.ApprovedList(world["root"] / "lane-listeners.json")
    al.original = acceptance.NOT_READ
    report = acceptance.Report()
    acceptance.existing_root_rows(report, None, {"pid": 1, "port": 22, "exe": "/sbin/launchd"}, al)   # no TypeError
    assert report.rows[-1][2] == "BROKEN" and not al.touched


def test_the_list_counts_as_touched_only_after_a_write_succeeded(acceptance, driven, monkeypatch):
    original = json.dumps(["/usr/libexec/rapportd"])
    lane.approved_path().write_text(original)
    FakeTeam.fail_at = "never"
    restores = []
    real = acceptance.restore_approved
    monkeypatch.setattr(acceptance, "restore_approved", lambda path, orig, touched: restores.append(touched) or real(path, orig, touched))
    monkeypatch.setattr(acceptance, "write_approved", lambda path, text: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(acceptance.time, "sleep", lambda s: None)
    report = acceptance.Report()
    with pytest.raises(OSError):
        acceptance.steps2to7(driven.args, report)
    assert restores and not any(restores)                                        # nothing written: nothing restored
    assert lane.approved_path().read_text() == original


def test_the_list_is_written_whole_or_not_at_all(acceptance, tmp_path, monkeypatch):
    path = tmp_path / "sub" / "lane-listeners.json"
    acceptance.write_approved(path, '["/sbin/launchd"]')
    assert path.read_text() == '["/sbin/launchd"]' and (path.stat().st_mode & 0o777) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["lane-listeners.json"]            # no temp file left
    monkeypatch.setattr(acceptance.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("killed")))
    with pytest.raises(OSError):
        acceptance.write_approved(path, "[")
    assert path.read_text() == '["/sbin/launchd"]' and [p.name for p in path.parent.iterdir()] == ["lane-listeners.json"]


# ---- 5. an orphaned nc ----

def test_an_nc_orphaned_by_the_kill_is_still_found_and_named(acceptance):
    said, killed = [], []
    orphan = "  902     1 /usr/bin/nc -l 127.0.0.1 5555\n"                           # once sudo is signalled, nc belongs to launchd
    root = SimpleNamespace(pid=900, wait=lambda timeout=None: 0)
    acceptance.stop_root_listener(root, 5555, ps=lambda: orphan if killed else PTY_TREE, kill=killed.append,
                                  listening=lambda p: True, say=said.append)
    assert 902 in killed and killed[0] == 900                                            # looked up before the kill
    assert any("STILL LISTENING" in line and "902" in line for line in said)


# ---- 7. brokers per poll ----

def test_the_servers_in_a_block_are_whatever_is_not_listening_on_the_broker_port_now(acceptance, monkeypatch):
    def lsof(*args):
        return {5} if "-iTCP:41031" in args else {5, 9} if any(a.startswith("-iTCP:41000-") for a in args) else set()
    monkeypatch.setattr(acceptance, "lsof_pids", lsof)
    assert acceptance.serving_pids(41000) == ({9}, {5})
    monkeypatch.setattr(acceptance, "lsof_pids", lambda *a: {7} if "-iTCP:41031" in a else {7, 8})
    assert acceptance.serving_pids(41000) == ({8}, {7})                                  # a restarted broker is still the broker


# ---- 8. the advisory match uses full paths ----

def test_an_advisory_file_must_be_the_agreed_path_not_just_the_same_name(acceptance, tmp_path):
    wt = tmp_path / "wt"
    (wt / acceptance.PROBE_DIR).mkdir(parents=True)
    spec = lambda f: {"title": "t", "file": f, "line": 1, "tags": ["@lane-advisory"],
                      "tests": [{"status": "unexpected", "results": [{"error": {"message": "m"}}]}]}
    report_json = {"config": {"rootDir": str(wt / "tests")}, "errors": [], "suites": [{"title": "s", "specs": [
        {"title": "ok", "file": "a.spec.ts", "line": 1, "tags": [], "tests": [{"status": "expected"}]},
        spec("gtm/visual.spec.ts"), spec("other/visual.spec.ts"), spec("visual.spec.ts")]}]}
    (wt / acceptance.PROBE_DIR / "spec-0.json").write_text(json.dumps(report_json))
    report = acceptance.Report()
    acceptance.report_spec(report, 6, "kaylee", str(wt), ["tests/a.spec.ts"])
    assert [r[2] for r in report.rows if "reported separately" in r[1]] == ["INFO"]
    assert [r[2] for r in report.rows if "outside the agreed set" in r[1]] == ["FAIL", "FAIL"]


def test_main_announces_the_person_plan_without_crashing(acceptance, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(acceptance.sys, "platform", "darwin")
    monkeypatch.setattr(lane, "python_ok", lambda: True)
    monkeypatch.setattr(acceptance, "step1", lambda args, report: True)
    monkeypatch.setattr(acceptance, "choose_root_listener", lambda: {"kind": "person"})
    monkeypatch.setattr(acceptance, "steps2to7", lambda args, report: report.add(4, "x", "PASS"))
    monkeypatch.setattr(acceptance.sys, "argv", ["lane_acceptance.py", "--bricks", str(tmp_path)])
    assert acceptance.main() == 0
    assert "ANDY ACTION" in capsys.readouterr().out


# ================= Final fix wave =================

def test_listeners_on_a_specific_address_are_listed_by_whose_they_are(acceptance):
    """I3: --list-listeners shows that the user's own listener beyond loopback counts while a lane runs, and another
    user's doesn't; with no owner known it counts (the check fails closed)."""
    listeners = [{"pid": 333, "command": "", "host": "100.101.102.103", "port": 8080},
                 {"pid": 777, "command": "", "host": "192.168.1.20", "port": 11434},
                 {"pid": 778, "command": "", "host": "192.168.1.20", "port": 11435}]
    paths = {333: "/opt/homebrew/bin/tailscaled", 777: "/opt/homebrew/bin/ollama", 778: "/opt/homebrew/bin/x"}
    owners = {333: 0, 777: os.getuid()}
    assert acceptance.listener_rows(listeners, paths.get, set(), owner=owners.get) == [
        (333, "100.101.102.103:8080", "/opt/homebrew/bin/tailscaled", "doesn't count: a lane can't reach it"),
        (777, "192.168.1.20:11434", "/opt/homebrew/bin/ollama", "stop it while a lane runs: it is yours, beyond loopback"),
        (778, "192.168.1.20:11435", "/opt/homebrew/bin/x", "stop it while a lane runs: whose it is can't be told")]
    sharingd = [{"pid": 640, "command": "", "host": "fe80::1%awdl0", "port": 8770}]
    mine = {640: os.getuid()}.get
    assert acceptance.listener_rows(sharingd, {640: "/usr/libexec/sharingd"}.get, set(), owner=mine)[0][3] == \
        "approvable (yours, beyond loopback: it counts while a lane runs)"
    assert acceptance.listener_rows(sharingd, {640: "/usr/libexec/sharingd"}.get, {"/usr/libexec/sharingd"},
                                    owner=mine)[0][3] == "approved"



# ---- T10: the person flow ----

class NetstatGlitch(PersonWorld):
    """netstat fails (None) for a while after the stop request, then shows the port free."""
    def __init__(self, fail_for, **kw):
        super().__init__(**kw)
        self.fail_for = fail_for

    def read(self):
        if self.stopped_at is not None and self.t < self.stopped_at + self.fail_for:
            return None
        return super().read()


def test_person_plan_a_failed_netstat_read_is_not_gone(acceptance, monkeypatch):
    """T10 (a): a netstat that can't be read says nothing about the listener: the run keeps polling."""
    world = NetstatGlitch(fail_for=30, appear_at=10, owner=0, gone_after_stop=20)
    never_signals(monkeypatch, acceptance)
    report, error = run_person(acceptance, monkeypatch, world)
    gone = [r for r in report.rows if r[1] == "the root-owned listener is gone"]
    assert error is None and [r[2] for r in gone] == ["PASS"] and world.t >= world.stopped_at + 30


def test_person_plan_a_netstat_that_never_reads_again_is_broken_not_gone(acceptance, monkeypatch):
    world = NetstatGlitch(fail_for=10 ** 6, appear_at=10, owner=0, gone_after_stop=0)
    never_signals(monkeypatch, acceptance)
    report, error = run_person(acceptance, monkeypatch, world)
    last = report.rows[-1]
    assert last[1] == "the root-owned listener is gone" and last[2] == "BROKEN" and "netstat" in last[3]
    assert isinstance(error, RuntimeError)


@pytest.mark.parametrize("when", ["waiting for it", "while it is named"])
def test_person_plan_says_stop_after_an_interrupt(acceptance, monkeypatch, when):
    """T10 (b): Ctrl-C (or SIGTERM's SystemExit) anywhere after the start line still tells Andy to stop his listener,
    once, and the interrupt goes on."""
    world = PersonWorld(appear_at=10 if when == "while it is named" else None, owner=0, gone_after_stop=5)
    never_signals(monkeypatch, acceptance)
    if when == "waiting for it":
        def sleep(s):
            raise KeyboardInterrupt
        world.sleep = sleep
    else:
        def message(wid, text):
            raise KeyboardInterrupt
        world.message = message
    with pytest.raises(KeyboardInterrupt):
        run_person(acceptance, monkeypatch, world)
    stops = [line for line in world.said if "stop it now" in line]
    assert stops == ["ANDY ACTION: stop it now (if you started it): press Ctrl-C in that Terminal"]


def test_person_plan_says_stop_after_an_error(acceptance, monkeypatch):
    world = PersonWorld(appear_at=10, owner=0, gone_after_stop=5)
    never_signals(monkeypatch, acceptance)

    def broken(pid, port):
        raise ValueError("lsof printed something odd")
    monkeypatch.setattr(acceptance, "root_listener_proof", broken)
    world.team = SimpleNamespace(message=world.message, wait=world.wait, inbox=world.inbox)
    with pytest.raises(ValueError):
        acceptance.person_root_rows(acceptance.Report(), world.team, read=world.read, path_of=lambda pid: "/usr/bin/nc",
                                    owner=lambda pid: 0, clock=world.clock, sleep=world.sleep, say=world.say,
                                    pick_port=lambda: world.port, port_free=lambda port: True)
    assert [line for line in world.said if "stop it now" in line] == [
        "ANDY ACTION: stop it now (if you started it): press Ctrl-C in that Terminal"]


# ---- C1, I3 and I5: the new step 2 rows ----

def test_a_write_probe_reports_written_or_the_refusal_and_never_truncates(tmp_path):
    wp = worker_probes_module()
    target = tmp_path / "preload.cjs"
    target.write_text("teamd's\n")
    assert wp.try_write(str(target)) == (0, "opened for writing") and target.read_text() == "teamd's\n"
    assert wp.try_write(str(tmp_path / "a" / "b.json"), "{}") == (0, "written")
    assert (tmp_path / "a" / "b.json").read_text() == "{}"
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("running as a user who can write anything")
        code, detail = wp.try_write(str(locked / "x.json"), "{}")
        assert code == 1 and detail.startswith("refused: EACCES")
    finally:
        locked.chmod(0o700)


def test_the_npx_cache_probe_writes_where_an_npx_server_would_install(tmp_path):
    wp = worker_probes_module()
    code, detail = wp.npx_write(tmp_path / "npm-cache")
    assert code == 0 and (tmp_path / "npm-cache" / "_npx" / "superyak-lane-acceptance" / "index.js").is_file()


def test_the_widen_round_plants_each_file_in_the_worktree(tmp_path):
    wp = worker_probes_module()
    rows = []
    wp.widen_round({"worktree": str(tmp_path), "plant": {".claude/settings.json": "{}", ".mcp.json": "{}"}}, rows)
    assert [(r["probe"], r["code"]) for r in rows] == [("plant .claude/settings.json", 0), ("plant .mcp.json", 0)]
    assert (tmp_path / ".claude" / "settings.json").read_text() == "{}"


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="needs node")
def test_the_bind_probe_says_at_once_and_holds_until_the_marker(tmp_path):
    """I3's probe: `env -i node` listens on the address it is given, says so in its state file at once, and holds the
    socket until the driver's marker appears (or its time runs out); an address that isn't this machine's is refused
    with its code."""
    wp = worker_probes_module()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    state, marker = tmp_path / "bind-state.json", tmp_path / "release"
    params = {"bind_ip": "127.0.0.1", "bind_port": port, "bind_marker": str(marker), "bind_hold_s": 30,
              "bind_state": str(state)}
    rows = []
    t = threading.Thread(target=wp.bind_round, args=(params, rows), daemon=True)
    t.start()
    end = time.time() + 20
    while time.time() < end and not state.exists():
        time.sleep(0.1)
    said = json.loads(state.read_text())
    try:
        assert said["code"] == 0 and said["detail"] == "listening"
        socket.create_connection(("127.0.0.1", port), timeout=5).close()       # it really listens meanwhile
    finally:
        marker.write_text("done")
        t.join(20)
    assert not t.is_alive() and rows[0]["code"] == 0
    state.unlink()
    rows = []
    wp.bind_round(dict(params, bind_ip="192.0.2.1"), rows)                      # TEST-NET-1: never this machine's
    assert rows[0]["code"] == 1 and rows[0]["detail"].startswith("refused: EADDRNOTAVAIL")


def test_the_planted_files_widen_every_way_a_worker_would_try(acceptance, tmp_path):
    plants = acceptance.widen_plants(str(tmp_path))
    assert sorted(plants) == [".claude/settings.json", ".claude/settings.local.json", ".mcp.json"]
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        data = json.loads(plants[rel])
        assert data["disableAllHooks"] is False and data["enableAllProjectMcpServers"] is True
        assert data["sandbox"]["network"]["allowedDomains"] == ["example.com"]
        assert data["sandbox"]["network"]["allowAllUnixSockets"] is True and "WebFetch" in data["permissions"]["allow"]
        assert data["sandbox"]["filesystem"]["allowWrite"] == ["~"]
        hooks = json.dumps(data["hooks"])
        assert str(tmp_path) in hooks and "SessionStart" in hooks and "PreToolUse" in hooks
    server = json.loads(plants[".mcp.json"])["mcpServers"]["superyak-acceptance"]
    assert server["args"] == [os.path.join(str(tmp_path), "mcp")]


def test_a_planted_file_passes_if_refused_or_inert_on_the_next_turn(acceptance):
    refused = {"code": 1, "detail": "refused: EPERM (Operation not permitted)"}
    written = {"code": 0, "detail": "written"}
    held = [{"probe": "curl example.com", "expect": "fail", "code": 1, "detail": "refused: curl-6 (x)",
             "refusals": list(worker_probes_module().NET_REFUSALS)}]
    leaked = [dict(held[0], code=0, detail="succeeded")]
    verdict = acceptance.widen_verdict
    assert verdict(".claude/settings.json", refused, held, False, False)[0] == "PASS"
    assert verdict(".claude/settings.json", written, held, False, False)[0] == "PASS"
    assert verdict(".claude/settings.json", written, held, True, False)[0] == "FAIL"        # its hook ran outside
    assert verdict(".claude/settings.json", written, leaked, False, False)[0] == "FAIL"     # the next turn reached out
    assert verdict(".mcp.json", written, held, False, False)[0] == "PASS"
    assert verdict(".mcp.json", written, held, False, True)[0] == "FAIL"                    # its server ran outside
    assert verdict(".mcp.json", {"code": 1, "detail": "refused: ENOENT (x)"}, held, False, False)[0] == "BROKEN"
    assert verdict(".claude/settings.json", written, [dict(held[0], code=2, detail="broken: timeout")],
                   False, False)[0] == "BROKEN"
    assert verdict(".claude/settings.json", None, held, False, False)[0] == "BROKEN"


def test_the_bind_row_passes_if_refused_or_the_turn_was_stopped_for_it(acceptance):
    verdict = acceptance.bind_verdict
    assert verdict({"code": 1, "detail": "refused: EPERM"}, False)[0] == "PASS"
    assert verdict({"code": 0, "detail": "listening"}, True)[0] == "PASS"
    assert verdict({"code": 0, "detail": "listening"}, False)[0] == "FAIL"
    assert verdict({"code": 1, "detail": "refused: EADDRNOTAVAIL"}, False)[0] == "BROKEN"
    assert verdict({"code": 2, "detail": "broken: no node"}, False)[0] == "BROKEN"
    assert verdict(None, False)[0] == "BROKEN"


def test_the_turns_processes_outside_the_sandbox_are_only_teamds_team_server(acceptance):
    """C1's evidence from ps: claude's argv carries --strict-mcp-config, its flag settings turn hooks off, and every
    process under the turn that runs outside the sandbox is teamd's team server."""
    argv = "claude -p go --settings /s.json --mcp-config /m.json --strict-mcp-config"
    under = [(11, "/usr/bin/python3 /x/team/run_team.py", False), (12, "/bin/bash -c npx playwright test", True)]
    rows = acceptance.outside_verdicts(argv, {"disableAllHooks": True}, under)
    assert [(name, verdict) for name, verdict, _ in rows] == [
        ("C1: the turn runs with --strict-mcp-config", "PASS"), ("C1: the worker's flag settings turn hooks off", "PASS"),
        ("C1: outside the sandbox, only teamd's team server runs under the turn", "PASS")]
    rows = acceptance.outside_verdicts(argv.replace(" --strict-mcp-config", ""), {}, under + [
        (13, "node /Users/me/.npm/_npx/abc/node_modules/.bin/some-mcp", False)])
    assert [verdict for _, verdict, _ in rows] == ["FAIL", "FAIL", "FAIL"] and "pid 13" in rows[2][2]
    rows = acceptance.outside_verdicts(argv, {"disableAllHooks": True}, under + [(14, "node x", None)])
    assert rows[2][1] == "BROKEN"


def test_the_preload_row_needs_teamds_own_file_outside_tmp(acceptance, tmp_path):
    good = tmp_path / "teams" / "lane-preload.cjs"
    good.parent.mkdir()
    good.write_text("x")
    good.chmod(0o644)
    assert acceptance.preload_verdict(str(good), unsafe=())[0] == "PASS"
    assert acceptance.preload_verdict(str(good), unsafe=(str(tmp_path),))[0] == "FAIL"
    good.chmod(0o666)
    assert acceptance.preload_verdict(str(good), unsafe=())[0] == "FAIL"
    assert acceptance.preload_verdict(None, unsafe=())[0] == "BROKEN"
    link = tmp_path / "link.cjs"
    link.symlink_to(good)
    assert acceptance.preload_verdict(str(link), unsafe=())[0] == "FAIL"


def test_the_third_workers_rows_run_end_to_end_with_fakes(acceptance, world, monkeypatch, tmp_path):
    """zoe_rows with a fake team that runs the real worker rounds in this process: no sandbox here, so every write
    gets through and the rows must say so; nothing reaches the network; the planted files, the $HOME probe and the
    listener all go, and zoe is stopped."""
    import re as re_
    wp = worker_probes_module()
    monkeypatch.setattr(wp, "run", lambda cmd, timeout=60, cwd=None: (6, "Could not resolve host"))
    monkeypatch.setattr(wp, "node", lambda code, *a, timeout=60: (1, "refused: ENOTFOUND"))
    monkeypatch.setattr(acceptance, "lan_address", lambda: "127.0.0.1")
    monkeypatch.setattr(lane, "read_listeners", lambda: [])
    if not __import__("shutil").which("node"):
        pytest.skip("needs node")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    base = s.getsockname()[1] - 5
    s.close()
    wt = tmp_path / "zoe"
    wt.mkdir()
    threads, ports = [], []

    class ZoeTeam:
        inbox, calls = [], []

        def call(self, *a, **k):
            self.calls.append(a)
            return {}

        def wait(self, wid, states, timeout=900, patient=False):
            return states[0]

        def state(self):
            return {"workers": {"zoe": {"path": str(wt), "lane": {"path": str(world["tmp"] / "zoe-lane"), "base": base}}}}

        def status(self):
            params = json.loads((wt / acceptance.PROBE_DIR / "params.json").read_text())
            ports.append(params["bind_port"])
            self.inbox.append("LANE STOPPED: zoe's turn ...: node (pid 9) listens on 127.0.0.1 port %d, beyond loopback, "
                              "as this user while a lane runs" % params["bind_port"])
            return {}

        def message(self, wid, text):
            round_name = re_.search(r"worker_probes\.py (\w+)", text).group(1)
            probes = wt / acceptance.PROBE_DIR
            params = json.loads((probes / "params.json").read_text())
            params["reported"] = dict(re_.findall(r"(\w+)=(\S+)", text.split("worker_probes.py")[-1]))

            def go():
                rows = []
                getattr(wp, round_name + "_round")(params, rows)
                (probes / ("results-%s.json" % round_name)).write_text(json.dumps({"rows": rows}))
            if round_name == "bind":
                threads.append(threading.Thread(target=go, daemon=True))
                threads[-1].start()
            else:
                go()
    team = ZoeTeam()
    report = acceptance.Report()
    acceptance.zoe_rows(SimpleNamespace(python="python3"), report, team)
    for t in threads:
        t.join(20)
    rows = {name: (verdict, detail) for _, name, verdict, detail in report.rows}
    assert rows["I5: the worker plants a widening .mcp.json"][0] == "PASS"
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        verdict, detail = rows["I5: the worker plants a widening %s" % rel]
        assert verdict == "FAIL" and "write in $HOME" in detail and "read a dotfile" in detail
    assert rows["I5: the next turn: curl example.com"][0] == "PASS"
    assert rows["I3: env -i node listens beyond loopback (an address of this Mac's)"][0] == "PASS"
    assert ports and not any(lane.PORT_FIRST <= port <= lane.PORT_LAST for port in ports)    # R1: beyond every block
    assert not (wt / ".claude" / "settings.json").exists() and not (wt / ".mcp.json").exists()
    assert not (world["home"] / "superyak-lane-acceptance-widen.txt").exists()
    # H4: the driver's four plants are judged, and everything it made (settings file, .claude folder, canary) is gone
    assert {n: v for n, (v, _) in rows.items() if n.startswith("I5: ") and "Write tool" in n or "headersHelper" in n
            or "additionalDirectories" in n or "PYTHONPATH" in n} == {
        "I5: the Write tool, allowed in $HOME by a project rule": "PASS", "I5: additionalDirectories naming $HOME": "PASS",
        "I5: a marketplace headersHelper": "PASS", "I5: PYTHONPATH in the project settings": "PASS"}
    assert not (wt / ".claude" / "settings.local.json").exists() and not list(world["home"].glob(".superyak-lane-probe-*"))
    assert not (world["home"] / "superyak-lane-probe-write").exists()
    assert ("stop", "worker=zoe") in team.calls and not any(t.is_alive() for t in threads)
    assert "127.0.0.1" not in json.dumps(report.rows)                         # the address is never printed



# ================= Round 2 =================

def test_the_bind_rows_port_lies_outside_every_lane_block(acceptance):
    """R1: a port in zoe's own block is stopped by the older in-block rule, so the I3 row binds outside the pool."""
    picks = iter([41005, lane.PORT_FIRST, lane.PORT_LAST, 49321])
    assert acceptance.port_beyond_pool(pick=lambda: next(picks)) == 49321
    port = acceptance.port_beyond_pool("127.0.0.1")
    assert not lane.PORT_FIRST <= port <= lane.PORT_LAST
    with pytest.raises(RuntimeError, match="outside"):
        acceptance.port_beyond_pool(pick=lambda: 41000)


def test_the_plants_also_set_every_helper_command(acceptance, tmp_path):
    """R2: the I5 plants set apiKeyHelper and the other helpers to scripts that would touch a marker outside the
    sandbox; any marker of a file's tag fails its row."""
    plants = acceptance.widen_plants(str(tmp_path))
    for rel, tag in ((".claude/settings.json", "settings"), (".claude/settings.local.json", "local")):
        data = json.loads(plants[rel])
        for key in lane.HELPER_KEYS:
            script = Path(data[key])
            assert script.parent == tmp_path and os.access(script, os.X_OK)
            r = subprocess.run([str(script)], capture_output=True, text=True)
            assert r.returncode == 0 and (tmp_path / ("%s-%s" % (tag, key))).exists()
    assert acceptance.marker_ran(str(tmp_path), "settings") and not acceptance.marker_ran(str(tmp_path), "other")


def test_the_held_lane_turn_opens_ts_tsx_and_py_files_before_the_c1_snapshot(acceptance, driven):
    """R2: a plugin's LSP server starts lazily, when a file of its language is opened; the lane round's message has
    the worker Read a .ts, a .tsx and a .py file first, so any such server is running when C1's ps snapshot is
    taken."""
    FakeTeam.messages = []
    run_steps(acceptance, driven)
    lane_round = [text for wid, text in FakeTeam.messages if wid == "kaylee" and "worker_probes.py lane" in text]
    assert lane_round, FakeTeam.messages
    text = lane_round[0]
    probes = Path(driven.world["wk"]["kaylee"]) / acceptance.PROBE_DIR
    for ext in (".ts", ".tsx", ".py"):
        path = probes / ("lsp-probe" + ext)
        assert path.is_file() and str(path) in text and text.index(str(path)) < text.index("Run exactly")


# ================= Lane hardening H4: the driver's own plants (more widening, written from outside the worker) =================

def test_h4_the_drivers_plant_widens_four_more_ways(acceptance, tmp_path):
    """H4: a Write(//<home>/...) allow rule (and its Edit twin), additionalDirectories naming $HOME, an
    extraKnownMarketplaces entry whose headersHelper touches a marker, and PYTHONPATH in the project settings' env."""
    home = tmp_path / "home"
    plants = acceptance.driver_plants(str(tmp_path), str(home), "/tmp/pypath")
    assert sorted(plants) == [".claude/settings.local.json"]
    data = json.loads(plants[".claude/settings.local.json"])
    target = "%s/superyak-lane-probe-write" % home
    assert "Write(/%s)" % target in data["permissions"]["allow"] and "Edit(/%s)" % target in data["permissions"]["allow"]
    assert data["permissions"]["additionalDirectories"] == [str(home)]
    assert data["env"] == {"PYTHONPATH": "/tmp/pypath"}
    helper = next(iter(data["extraKnownMarketplaces"].values()))["headersHelper"]
    assert os.access(helper, os.X_OK) and Path(helper).parent == tmp_path
    subprocess.run([helper], capture_output=True, check=True)
    assert acceptance.marker_ran(str(tmp_path), "market")
    assert "superyak-lane-probe-write" in acceptance.driver_message("python3", "/h/.canary")
    assert "Write tool" in acceptance.driver_message("python3", "/h/.canary")


def test_h4_each_plant_is_judged_on_its_own_evidence(acceptance):
    verdicts = acceptance.driven_verdicts
    ok = dict(write_exists=False, market_ran=False, nonce="abcdef0123456789",
              rows=[{"probe": "read_tool report", "expect": "info", "code": 0, "detail": "none"},
                    {"probe": "PYTHONPATH from project settings", "expect": "fail", "code": 1,
                     "detail": "refused: FILTERED (not set)", "refusals": ["FILTERED"]}])

    def run(**change):
        return {name.split(":", 1)[1].strip(): v for name, v, _ in verdicts(**dict(ok, **change))}
    assert set(run().values()) == {"PASS"} and len(run()) == 4
    assert run(write_exists=True)["the Write tool, allowed in $HOME by a project rule"] == "FAIL"
    assert run(market_ran=True)["a marketplace headersHelper"] == "FAIL"
    leaked = [dict(ok["rows"][0], detail="abcdef01"), ok["rows"][1]]
    assert run(rows=leaked)["additionalDirectories naming $HOME"] == "FAIL"
    assert run(rows=[dict(ok["rows"][0], detail="")] + ok["rows"][1:])["additionalDirectories naming $HOME"] == "BROKEN"
    assert run(rows=[ok["rows"][1]])["additionalDirectories naming $HOME"] == "BROKEN"
    reached = [ok["rows"][0], dict(ok["rows"][1], code=0, detail="reached")]
    assert run(rows=reached)["PYTHONPATH in the project settings"] == "FAIL"


def test_h4_the_driven_round_reports_the_env_and_what_the_worker_said(tmp_path, monkeypatch):
    wp = worker_probes_module()
    rows = []
    monkeypatch.delenv("PYTHONPATH", raising=False)
    wp.driven_round({"pythonpath": "/tmp/pypath", "reported": {"read_tool": "none"}}, rows)
    byname = {r["probe"]: r for r in rows}
    assert byname["read_tool report"]["detail"] == "none" and byname["PYTHONPATH from project settings"]["code"] == 1
    monkeypatch.setenv("PYTHONPATH", "/x" + os.pathsep + "/tmp/pypath")
    rows = []
    wp.driven_round({"pythonpath": "/tmp/pypath", "reported": {}}, rows)
    assert {r["probe"]: r for r in rows}["PYTHONPATH from project settings"]["code"] == 0
    assert {r["probe"]: r for r in rows}["read_tool report"]["detail"] == ""
