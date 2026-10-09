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


def test_the_lsof_exit_code_is_recorded_and_only_0_passes(acceptance):
    got = []
    ok = lambda cmd, timeout=60: got.append(cmd) or Ran(0, "p1\nn/a\np2\nn/b\n")
    verdict, detail = acceptance.lsof_exit(ok)
    assert verdict == "PASS" and "exit 0" in detail and "4 lines" in detail
    assert got[0][1:] == ["-nP", "-a", "-u", str(os.getuid()), "-F", "pn"] and got[0][0].endswith("lsof")
    verdict, detail = acceptance.lsof_exit(lambda cmd, timeout=60: Ran(1, "", "WARNING: can't stat() fuse\n more"))
    assert verdict == "FAIL" and "exit 1" in detail and "can't stat() fuse" in detail
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
