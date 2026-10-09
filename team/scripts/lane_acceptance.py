#!/usr/bin/env python3
"""Browser-lane acceptance run (docs/superpowers/specs/2026-10-08-browser-lane-design.md, "Mac acceptance").

Serenity runs it on the Mac, from the superyak repository, at a time the Bricks lead picks, with uv's Python (lanes
need 3.11.4 or later for tarfile's data filter):

    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --list-listeners      # fill lane-listeners.json
    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --bricks ~/Projects/bricks --self-check-only
    sudo -v                                                                                 # for step 4's root listener
    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --bricks ~/Projects/bricks

Prerequisites (the spec's, plus this script's):
- lane_node in ~/.superyak/team/config.json, and no browser_lane anywhere yet: the run makes its own preset, with
  browser_lane on, and removes it when it ends, so no lead can open a lane before the acceptance has passed;
- ~/.superyak/team/lane-listeners.json filled in (--list-listeners shows what is listening now), and nothing else
  listening: dev servers, Ollama, Postgres and Serena dashboards stopped;
- the Bricks checkout on the branch with the Bricks change (lane ports in the Playwright config and fixtures);
- the worktree prepared, so npx needs no registry: the workers are spawned with --prepare (npm-ci by default);
- the headless shell's manifest hash recorded for this revision (--self-check-only prints it the first time);
- `sudo -v` shortly before, so step 4 can start a root-owned listener (or Printer Sharing on, whose cupsd is one).

It starts its own team in the Bricks checkout (two browser workers, kaylee and wash), drives them as their lead
through `run_team.py`, and ends the team and deletes its branches when it is done. The probes inside the workers are
lane_acceptance/worker_probes.py and broker_client.js, which this script copies into each worker's
node_modules/.superyak-lane-acceptance/. Every row prints as PASS, FAIL, BROKEN or INFO; the run passes only when
steps 1-7 all pass in one run. Post the whole transcript in the room. It never prints a file's contents or a secret.
"""
import argparse
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBES = HERE / "lane_acceptance"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(PROBES))
from superyak_team import lane, teamlib  # noqa: E402
import worker_probes  # noqa: E402

RUN_TEAM = HERE.parent / "run_team.py"
SMOKE_SPECS = ["tests/auth-pages.spec.ts", "tests/journey-auth-first-run.spec.ts",
               "tests/gtm/integration-lifetime.spec.ts:6"]
PROBE_DIR = "node_modules/.superyak-lane-acceptance"
WRITE_PROBE = "superyak-lane-acceptance-download.txt"
RENDEZVOUS = "org.chromium.Chromium.MachPortRendezvousServer.%d"
# Never-list services, plus the camera and microphone ones the getUserMedia row leans on.
NEVER_LIST = ["com.apple.SecurityServer", "com.apple.securityd.xpc", "com.apple.coreservices.launchservicesd",
              "com.apple.lsd.mapdb", "com.apple.pasteboard.1", "com.apple.cmio.registerassistantservice",
              "com.apple.cmio.VDCAssistant", "com.apple.audio.coreaudiod", "com.apple.audio.AudioComponentRegistrar",
              "org.chromium.Chromium.MachPortRendezvousServer.1x"]
READY_TASK = ("Browser-lane acceptance worker. Reply with only the word ready. Do not run any command, and do not "
              "call team_done until a message asks you to.")
NETCAT = "/usr/bin/nc"


# ---------- pure helpers (team/tests/test_lane_acceptance.py runs these on the Pi) ----------

def judge(expect, code):
    """A probe row's verdict: ok must exit 0, fail must not, info is only shown."""
    if expect == "info":
        return "INFO"
    return "PASS" if (code == 0) == (expect == "ok") else "FAIL"


def classify_lookup(rc):
    """bootstrap_look_up from inside the worker: 1100 is the sandbox's denial; 1102 means the name was wrong, so the
    check itself is broken; 0 means the worker reached the browser's rendezvous service."""
    return {1100: "denied", 1102: "broken", 0: "reachable"}.get(rc, "other")


def peer_verdict(expect, code, alive_before, alive_after):
    """The second lane's rows: a target that wasn't alive both before and after the probes proves nothing, so the
    check is BROKEN, not passed."""
    return judge(expect, code) if alive_before and alive_after else "BROKEN"


def rendezvous_pid(ps_text, broker_pid):
    """The headless shell's main browser process: node's child with no --type= argument (not node's own pid)."""
    for line in ps_text.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1] == str(broker_pid) and "--type=" not in fields[2]:
            return int(fields[0])
    return None


def summarize(report):
    """A Playwright JSON report: passes, real failures, advisory failures (@lane-advisory, reported separately and in
    full), flaky tests, skips and top-level errors."""
    out = {"passed": 0, "failed": [], "advisory": [], "flaky": [], "skipped": 0,
           "errors": [str(e.get("message", e))[:200] for e in report.get("errors") or []]}

    def walk(suite):
        for spec in suite.get("specs") or []:
            tags = [str(t).lstrip("@") for t in spec.get("tags") or []]
            advisory = "lane-advisory" in tags or "@lane-advisory" in spec.get("title", "")
            name = "%s:%s %s" % (spec.get("file"), spec.get("line"), spec.get("title"))
            for test in spec.get("tests") or []:
                status = test.get("status")
                if status == "expected":
                    out["passed"] += 1
                elif status == "skipped":
                    out["skipped"] += 1
                elif status == "flaky":
                    out["flaky"].append(name)
                elif advisory:
                    out["advisory"].append(name)
                else:
                    out["failed"].append(name)
        for child in suite.get("suites") or []:
            walk(child)
    for suite in report.get("suites") or []:
        walk(suite)
    return out


def effective_domains(paths):
    """Every allowedDomains entry the settings files that merge into a worker's sandbox contain, plus example.com."""
    found = {"example.com"}
    for path in paths:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        network = ((data.get("sandbox") or {}).get("network") or {}) if isinstance(data, dict) else {}
        found |= {d.lstrip("*.") for d in network.get("allowedDomains") or [] if isinstance(d, str)}
    return sorted(found)


def denied_lookup(lines, pid):
    """A `deny mach-lookup org.chromium...` line for this pid in the sandbox's denial stream."""
    return any("(%d) deny" % pid in line and "mach-lookup org.chromium.Chromium.MachPortRendezvousServer" in line
               for line in lines)


def planted_settings(existing):
    """The worktree's .claude/settings.json for step 2: whatever it held, plus example.com in allowedDomains, a
    WebFetch(domain:example.com) allow rule and allowMachLookup ["*"]."""
    data = dict(existing or {})
    sandbox = dict(data.get("sandbox") or {})
    network = dict(sandbox.get("network") or {})
    network["allowedDomains"] = list(network.get("allowedDomains") or []) + ["example.com"]
    network["allowMachLookup"] = ["*"]
    sandbox["network"] = network
    data["sandbox"] = sandbox
    permissions = dict(data.get("permissions") or {})
    permissions["allow"] = list(permissions.get("allow") or []) + ["WebFetch(domain:example.com)"]
    data["permissions"] = permissions
    return data


def listener_rows(listeners, path_of, approved):
    """--list-listeners, from the listener check's own enumeration and rules: (pid, address, executable, verdict).
    Pid 1 is launchd holding a socket-activated job's socket; approving /sbin/launchd covers every such job until the
    job's own program first accepts a connection (then it is that program's)."""
    rows = []
    for item in listeners:
        exe = path_of(item["pid"])
        address = "%s:%d" % (item["host"], item["port"])
        if not lane.reachable(item["host"]):
            verdict = "doesn't count: a lane can't reach it"
        elif exe is None:
            verdict = "can't be identified: a lane waits"
        elif exe in approved:
            verdict = "approved"
        elif (exe.startswith(lane.APPROVED_DIRS) and not exe.startswith(lane.NOT_SEALED)
              and not lane.INTERPRETER_RE.fullmatch(os.path.basename(exe).lower())):
            verdict = "approvable"
        else:
            verdict = "stop it while a lane runs"
        if item["pid"] == 1:
            verdict += "; launchd holds it for a socket-activated job"
        rows.append((item["pid"], address, exe or "?", verdict))
    return rows


def read_targets(other_lane, decoy, uid, home=None):
    """Step 2's reads, each checked outside the sandbox first: ({name: path} that exist, [names that don't]). A read
    of something that isn't there would be "refused" with ENOENT, which proves nothing."""
    home = Path(home or Path.home())
    dotfile = next((home / n for n in (".zshrc", ".bashrc", ".profile", ".gitconfig") if (home / n).is_file()), None)
    wanted = {"a dotfile in $HOME": dotfile, "a decoy lane's folder": Path(decoy),
              "the other lane's real folder": Path(other_lane),
              "/private/tmp/claude-<uid>": Path("/private/tmp/claude-%d" % uid)}
    present = {name: str(path) for name, path in wanted.items() if path is not None and path.exists()}
    return present, sorted(set(wanted) - set(present))


# ---------- facts only a Mac can settle (review rows): each returns rows, or a (verdict, detail) ----------

class PidRecorder:
    """subprocess.run for lane.self_check's `run` seam, remembering each probe's pid: sandbox-exec execs the probe in
    its own pid, so the denial stream's lines for that pid are that probe's. A row is (probe, planted, pid); planted
    is True when a system.sb sat in the probe's cwd (the planted-import rerun)."""

    def __init__(self):
        self.pids = []

    def __call__(self, cmd, env=None, cwd=None, timeout=None, **_):
        proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                errors="replace")
        self.pids.append((cmd[-1], os.path.exists(os.path.join(cwd or "", "system.sb")), proc.pid))
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

    def pid_of(self, probe, planted=False):
        found = [pid for name, was_planted, pid in self.pids if name == probe and was_planted == planted]
        return found[-1] if found else None


def report_profile_rows(report, rows, recorder, denials, step=1, stream=True):
    """Every profile row with its whole detail (`refused: <code> (<message>)`). A BROKEN row also gets the sandbox
    denial lines for that probe's pid (lane.denials_for filters the stream by pid, never by name)."""
    for probe, verdict, detail in rows:
        notes = []
        if verdict == "BROKEN":
            planted = probe.startswith("planted-import:")
            pid = recorder.pid_of(probe.split(":", 1)[1] if planted else probe, planted)
            if pid is None:
                notes.append("no sandbox denial lines: the probe never ran")
            elif not stream:
                notes.append("no sandbox denial lines for pid %d: the denial stream isn't available" % pid)
            else:
                lines = lane.denials_for(denials, {pid})
                notes += ["sandbox denial: " + line for line in lines] or \
                    ["no sandbox denial lines for pid %d" % pid]
        report.add(step, "profile:" + probe if not probe.startswith("planted-import:") else probe,
                   verdict, detail, full=True, notes=notes)


def planted_import(node, pw, shell, run):
    """Spec review row `planted-import`: with `<lane>/b/system.sb` holding `(allow default)` and the broker's cwd at
    b/, the write_home and read_dotfile probes must still be refused under the generated profile: `(import
    "system.sb")` resolves from the system's profile folder, never the cwd. The planted file is removed afterwards.
    A scratch lane, as lane.self_check makes one. Returns [(row name, verdict, detail)]."""
    rows, team_id, worker_id = [], "superyak-planted-import-%d" % os.getpid(), "check"
    held = lane.hold_team(team_id)
    path = lane.lane_path(team_id, worker_id)
    leftover = Path.home() / "superyak-lane-probe.txt"
    existed = os.path.lexists(leftover)
    try:
        lane.ensure_lane(team_id, worker_id)
        base = lane.allocate_block(team_id, worker_id)
        b_text = lane.lane_text(path / "b")
        profile = lane.render_profile(b_text, pw, lane.browsers_root(), shell, node, base)
        source = (teamlib.package_dir() / "lane" / "profile_probe.js").read_text()
        targets = lane.probe_targets(None, path)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "TMPDIR": b_text}
        env.update({var: str(target) for var, target in targets.values() if var and target})
        planted = path / "b" / "system.sb"
        lane._write_text(planted, "(allow default)\n", 0o600)
        if '(import "system.sb")' not in profile or not planted.is_file():
            return [("planted-import:" + probe, "BROKEN", "the profile has no (import \"system.sb\") to test, or the "
                     "planted file isn't there") for probe in ("write_home", "read_dotfile")]
        for probe in ("write_home", "read_dotfile"):
            name = "planted-import:" + probe
            if probe == "write_home" and existed:
                rows.append((name, "BROKEN", "%s exists from before this run, so a refusal can't be shown" % leftover))
                continue
            if targets[probe][1] is None:
                rows.append((name, "BROKEN", "its target is missing or unusable here, so a refusal would prove nothing"))
                continue
            try:
                r = run([lane.SANDBOX_EXEC, "-p", profile, str(node), "-e", source, probe],
                        env=env, cwd=b_text, capture_output=True, text=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError, ValueError) as e:
                rows.append((name, "BROKEN", ("%s: %s" % (type(e).__name__, e))[:160]))
                continue
            rows.append((name, lane.judge_probe(probe, r.returncode, r.stdout), (r.stdout or r.stderr or "").strip()[:160]))
    finally:
        def step(what, fn):
            try:
                fn()
            except Exception as e:                        # one cleanup step failing must not skip the rest
                rows.append(("planted-import:cleanup", "BROKEN", ("%s: %s: %s" % (what, type(e).__name__, e))[:160]))
        if not existed and os.path.lexists(leftover):
            step("remove %s" % leftover, lambda: os.unlink(leftover))
        step("remove the planted file", lambda: os.unlink(path / "b" / "system.sb") if os.path.lexists(path / "b" / "system.sb") else None)
        step("remove the lane", lambda: lane.remove_lane(path))
        step("release the block", lambda: lane.release_block(team_id, worker_id))
        step("release the team lock", held.close)
        step("remove the lock file", lambda: lane._team_lock(team_id).unlink(missing_ok=True))
    return rows


def lsof_exit(run=None):
    """Review row `lsof-exit`: the full listing cleanup runs (`lsof -nP -a -u <uid> -F pn`) and its exit code. Cleanup
    needs 0 (lane_pids treats anything else as "can't say" and keeps the block held), so a routine exit 1 on this
    Mac is a FAIL, shown here. Returns (verdict, detail)."""
    run = run or lane._run
    lsof = shutil.which("lsof", path=lane.SYSTEM_PATH)
    if not lsof:
        return "BROKEN", "lsof isn't in %s" % lane.SYSTEM_PATH
    r = run([lsof, "-nP", "-a", "-u", str(os.getuid()), "-F", "pn"], timeout=120)
    if r is None:
        return "BROKEN", "lsof couldn't run (or timed out)"
    why = " ".join((r.stderr or "").split())[:120]
    return ("PASS" if r.returncode == 0 else "FAIL",
            "exit %d, %d lines of output%s" % (r.returncode, (r.stdout or "").count("\n"), ", stderr: " + why if why else ""))


HELPERS = []            # the helper processes hardlink_naming started (the tests find their pids here)
HOLDER = ("import sys, time\nf = open(sys.argv[1])\nprint('ready', flush=True)\ntime.sleep(300)\n")


def hardlink_naming():
    """Review row `hardlink-naming`: a file another process of this user holds open, hard-linked into the lane's
    tmp/. lsof names an open file by the name it was opened with, so the cleanup matcher (lane.lane_pids) must NOT
    name the holder. The only process involved is a helper this function starts and ends. Returns (verdict, detail)."""
    team_id, worker_id = "superyak-hardlink-naming-%d" % os.getpid(), "check"
    path = lane.lane_path(team_id, worker_id)
    folder, helper = None, None
    try:
        lane.ensure_lane(team_id, worker_id)
        folder = tempfile.mkdtemp(prefix="sy-acc-hl-", dir=str(lane.TMP_ROOT))
        held = os.path.join(folder, "held.txt")
        Path(held).write_text("held open by a helper\n")
        helper = subprocess.Popen([sys.executable, "-c", HOLDER, held], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL, text=True)
        HELPERS.append(helper)
        if helper.stdout.readline().strip() != "ready":
            return "BROKEN", "the helper didn't start"
        os.link(held, path / "tmp" / "linked.txt")
        # Control: lsof does list the holder, under the name it opened (so the matcher had something to find).
        lsof = shutil.which("lsof", path=lane.SYSTEM_PATH)
        seen = lane._run([lsof, "-nP", "-p", str(helper.pid), "-F", "n"]) if lsof else None
        names = [line[1:] for line in (seen.stdout if seen is not None else "").splitlines() if line.startswith("n")]
        if not any(os.path.realpath(held) == os.path.realpath(n) for n in names if n.startswith("/")):
            return "BROKEN", "lsof doesn't list the helper's open file, so the matcher had nothing to name"
        pids = lane.lane_pids(path, None)
        if pids is None:
            return "BROKEN", "lsof couldn't say (lane_pids gave None)"
        if helper.pid in pids:
            return "FAIL", "the helper (pid %d) holding %s is in the kill set: the hard link made it look like the lane's" \
                   % (helper.pid, held)
        return "PASS", "the helper (pid %d) holds a file hard-linked into the lane's tmp/ and is not in the kill set; " \
                       "lsof names it %s" % (helper.pid, held)
    except (lane.LaneRefused, OSError) as e:
        return "BROKEN", "%s: %s" % (type(e).__name__, e)
    finally:
        if helper is not None:
            helper.kill()
            helper.wait()
            if helper in HELPERS:
                HELPERS.remove(helper)
            if helper.stdout:
                helper.stdout.close()
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        try:
            lane.remove_lane(path)
        except lane.LaneRefused:
            pass


def extra_browser_folders(browsers, shell):
    """Review row `ffmpeg-folder`: everything in the browsers folder besides the headless shell's own folder, as
    `name (kind)`. Playwright's installer may add ffmpeg-<rev> there. Names only; nothing is followed."""
    out = []
    for name in sorted(os.listdir(browsers)):
        if name == Path(shell).name:
            continue
        mode = os.lstat(os.path.join(browsers, name)).st_mode
        out.append("%s (%s)" % (name, "symlink" if stat.S_ISLNK(mode) else "folder" if stat.S_ISDIR(mode) else "file"))
    return out


def netstat_fixture(text, path_of, rows=3):
    """The real `netstat -anv -p tcp` header line and three sample LISTEN rows (varied by address kind where it can),
    for test fixtures. Process names that aren't Apple's (by proc_pidpath, in the folders the approved list allows)
    become `<name>`. None when the header isn't one the listener check knows (nothing is written then)."""
    lines = text.split("\n")
    header = next((line for line in lines if line.startswith("Proto")), None)
    if header is None or lane._netstat_rows(text)[0] is None:
        return None
    columns = [c.replace("\0", " ") for c in header.replace("Local Address", "Local\0Address")
               .replace("Foreign Address", "Foreign\0Address").split()]
    named = "process:pid" in columns
    index = columns.index("process:pid" if named else "pid")
    trailing = len(columns) - index - 1
    listening = [line for line in lines if len(line.split()) >= 6 and line.split()[5] == "LISTEN"
                 and line.split()[0].startswith("tcp")]

    def kind(line):
        host = line.split()[3].rpartition(".")[0]
        return "wildcard" if host in lane.WILDCARDS else "loopback" if lane.is_loopback(host) else "other"
    chosen, seen = [], set()
    for line in listening:                                  # one of each address kind first, then the rest in order
        if kind(line) not in seen:
            seen.add(kind(line))
            chosen.append(line)
    chosen += [line for line in listening if line not in chosen]
    out = [header]
    for line in chosen[:rows]:
        if named:
            fields = line.split()
            segment = " ".join(fields[index:len(fields) - trailing])
            found = re.fullmatch(r"(.*):([0-9]+)", segment)
            exe = path_of(int(found.group(2))) if found else None
            if not (exe and exe.startswith(lane.APPROVED_DIRS)) and segment in line:
                line = line.replace(segment, "<name>:%s" % (found.group(2) if found else "0"), 1)
        out.append(line)
    return out


def capture_netstat(run, path_of, dest):
    """Review row `netstat-capture`: save the redacted header and sample rows to `dest`. Returns (verdict, detail)."""
    netstat = shutil.which("netstat", path=lane.SYSTEM_PATH)
    r = run([netstat or "/usr/sbin/netstat", "-anv", "-p", "tcp"])
    if r is None or r.returncode != 0:
        return "BROKEN", "netstat failed"
    lines = netstat_fixture(r.stdout, path_of)
    if lines is None or len(lines) < 2:
        return "BROKEN", "netstat printed a header the listener check doesn't know, or no listening row; nothing written"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    return "INFO", "header and %d rows, non-Apple process names redacted, written to %s" % (len(lines) - 1, dest)


# ---------- the run ----------

class Report:
    def __init__(self):
        self.rows = []

    def add(self, step, name, verdict, detail="", full=False, notes=()):
        """One row. `full` prints the whole detail (the profile rows: the refusal's code and message are the
        evidence); `notes` are extra lines under it (a BROKEN probe's sandbox denials)."""
        self.rows.append((step, name, verdict, detail))
        text = " ".join(str(detail).split())
        print("%-6s step %s  %-44s %s" % (verdict, step, name, text if full else text[:220]), flush=True)
        for note in notes:
            print("         %s" % " ".join(str(note).split()), flush=True)

    def failed(self):
        return [r for r in self.rows if r[2] in ("FAIL", "BROKEN")]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def worktrees(repo):
    out = git(repo, "worktree", "list", "--porcelain")
    return [str(repo)] + [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]


class Team:
    """The acceptance's own team, driven as its lead through run_team.py (the same path a lead's tools take)."""

    def __init__(self, bricks, team_id):
        self.bricks, self.id, self.inbox = bricks, team_id, []

    def call(self, *args, timeout=900):
        r = subprocess.run([sys.executable, str(RUN_TEAM), *args, "team=" + self.id], cwd=self.bricks,
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError("team %s failed: %s" % (args[0], (r.stderr or r.stdout).strip()[-500:]))
        return json.loads(r.stdout)

    def status(self):
        st = self.call("status")
        self.inbox += [m.get("message", "") for m in st.get("inbox") or []]
        return st

    def state(self):
        return json.loads((teamlib.team_dir(self.id) / "state.json").read_text())

    def wait(self, wid, states, timeout=900, patient=False):
        """Until the worker is in one of `states`. A worker that fails, or waits for its lane (unless `patient`),
        stops the run with the lead's last messages, which name the reason."""
        end = time.time() + timeout
        while time.time() < end:
            state = self.status()["workers"][wid]["state"]
            if state in states:
                return state
            if state == "failed" or (state == "waiting" and not patient):
                raise RuntimeError("%s is %s; the lead's inbox says: %s"
                                   % (wid, state, " | ".join(self.inbox[-3:])[:800]))
            time.sleep(3)
        raise RuntimeError("%s is not %s after %d s" % (wid, "/".join(states), timeout))

    def message(self, wid, text):
        return self.call("message", "worker=" + wid, "text=" + text)


def probe_message(python, round_name):
    return ("Run exactly this one Bash command, once, with a timeout of 2400000 ms: %s %s/worker_probes.py %s\n"
            "Then reply with only the word done. Do not run anything else." % (python, PROBE_DIR, round_name))


def install_probes(worktree, params):
    dest = Path(worktree) / PROBE_DIR
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(PROBES, dest, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / "params.json").write_text(json.dumps(params))
    return dest


def results(worktree, round_name):
    return json.loads((Path(worktree) / PROBE_DIR / ("results-%s.json" % round_name)).read_text())


def lsof_pids(*args):
    r = subprocess.run(["/usr/sbin/lsof", "-nP", "-t", *args], capture_output=True, text=True)
    return {int(x) for x in r.stdout.split() if x.isdigit()}


def block_listeners(base):
    return lsof_pids("-a", "-u", str(os.getuid()), "-iTCP:%d-%d" % (base, base + lane.BLOCK - 1), "-sTCP:LISTEN")


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def serve_canary(port):
    """A loopback service outside the first lane's ports (in the second lane's block, so the listener check passes)."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                conn.sendall(b"HTTP/1.0 200 OK\r\n\r\ncanary\n")
                conn.close()
            except OSError:
                return
    threading.Thread(target=serve, daemon=True).start()
    return srv


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def sandbox_check(pid, name):
    """Optional (spec unit test 9): libsystem_sandbox's verdict on a Mach lookup by a live process. 0 allowed,
    1 denied, None when the call isn't available. Information only, unless a never-list service shows allowed."""
    import ctypes
    try:
        lib = ctypes.CDLL("/usr/lib/system/libsystem_sandbox.dylib")
        check = lib.sandbox_check
        check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]       # variadic: the fixed arguments only
        check.restype = ctypes.c_int
        rc = check(pid, b"mach-lookup", 2 | 0x40000000, ctypes.c_char_p(name.encode()))   # GLOBAL_NAME | NO_REPORT
    except (OSError, AttributeError):
        return None
    return rc if rc in (0, 1) else None


def guarded(report, step, name, fn):
    """A row's own failure to run is a BROKEN row, never a crash that hides the rows after it."""
    try:
        return fn()
    except (lane.LaneRefused, OSError, ValueError, subprocess.SubprocessError) as e:
        report.add(step, name, "BROKEN", "%s: %s" % (type(e).__name__, e))


def step1(args, report):
    """Before any worker: the manifest, the facts only a Mac can settle, then every spike 5 probe and `open -a
    Calculator` under the profile (plus the planted system.sb rerun). Returns whether the install succeeded."""
    bricks = args.bricks
    try:
        node = lane.check_lane_node(teamlib.load_config().get("lane_node"), worktrees(bricks))
        pw = lane.pinned_playwright(bricks, git(bricks, "rev-parse", "HEAD"))
        shell, revision = lane.install_headless_shell(node, pw)
    except lane.LaneRefused as e:
        report.add(1, "pinned Playwright and headless shell", "FAIL", e)
        return False
    actual, recorded = lane.manifest_hash(shell), lane.recorded_manifest(revision)
    name = "manifest %s %s" % (revision, lane.platform_key())
    if recorded == actual:
        report.add(1, name, "PASS", actual)
    elif recorded is None:
        report.add(1, name, "INFO" if args.self_check_only else "FAIL", "not recorded yet: %s" % actual)
        print('\nOnce the probes below pass, record it in team/superyak_team/lane/browsers.json:\n'
              '  "chromium-headless-shell": {"%s": {"%s": "%s"}}\n' % (revision, lane.platform_key(), actual))
    else:
        report.add(1, name, "FAIL", "recorded %s, found %s" % (recorded, actual))
    # ffmpeg-folder: what else the installer left in the browsers folder
    extras = guarded(report, 1, "ffmpeg-folder", lambda: extra_browser_folders(lane.browsers_root(), shell))
    if extras is not None:
        report.add(1, "ffmpeg-folder", "INFO", ("besides the shell: " + ", ".join(extras)) if extras
                   else "only %s" % Path(shell).name, full=True)
    # lsof-exit: cleanup needs the full listing to exit 0
    result = guarded(report, 1, "lsof-exit", lsof_exit)
    if result:
        report.add(1, "lsof-exit", result[0], result[1], full=True)
    # netstat-capture: the real header and sample rows, for test fixtures
    dest = Path.home() / ".superyak" / ("lane-netstat-fixture-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    result = guarded(report, 1, "netstat-capture", lambda: capture_netstat(lane._run, lane.pid_path, dest))
    if result:
        report.add(1, "netstat-capture", result[0], result[1], full=True)
    # hardlink-naming: a stranger's open file, hard-linked into a lane, isn't the lane's
    result = guarded(report, 1, "hardlink-naming", hardlink_naming)
    if result:
        report.add(1, "hardlink-naming", result[0], result[1], full=True)
    # the profile probes, with the denial stream open so a BROKEN probe can show its pid's denials
    recorder, stream = PidRecorder(), lane.start_denial_stream()
    rows = guarded(report, 1, "profile:self_check", lambda: lane.self_check(node, pw, shell, run=recorder)) or []
    rows += guarded(report, 1, "planted-import", lambda: planted_import(node, pw, shell, recorder)) or []
    time.sleep(2 if stream is not None else 0)             # the stream lags the events it reports
    denials = lane.stop_denial_stream(stream)
    report_profile_rows(report, rows, recorder, denials, stream=stream is not None)
    return True


def root_listener(port):
    """A root-owned listener for step 4: `sudo -n nc -l` on a loopback port (sudo -v beforehand), or None."""
    if subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/true"], capture_output=True).returncode != 0:
        return None
    return subprocess.Popen(["/usr/bin/sudo", "-n", NETCAT, "-l", "127.0.0.1", str(port)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_root_listener(port):
    for item in lane.read_listeners() or []:
        if item["port"] == port:
            subprocess.run(["/usr/bin/sudo", "-n", "/bin/kill", str(item["pid"])], capture_output=True)


def steps2to7(args, report):
    bricks, uid = args.bricks, os.getuid()
    stamp = time.strftime("%m%d%H%M")
    team, preset = Team(bricks, "lane-acceptance-%s" % stamp), "lane-acceptance-%s" % stamp
    presets_file = teamlib.presets_path()
    presets_before = presets_file.read_text() if presets_file.exists() else None
    decoy = lane.private_parent() / "acceptance-decoy"
    settings_file, settings_before, listeners_before, canary = None, None, None, None
    try:
        presets = json.loads(presets_before) if presets_before else {}
        presets[preset] = {"description": "browser-lane acceptance (removed when the run ends)", "browser_lane": True,
                           "default_kind": "claude", "default_mode": "build", "max_workers": 2}
        presets_file.parent.mkdir(parents=True, exist_ok=True)
        presets_file.write_text(json.dumps(presets, indent=1))
        print("\n== team %s in %s ==" % (team.id, bricks), flush=True)
        subprocess.run([sys.executable, str(RUN_TEAM), "start", "goal=browser-lane acceptance", "name=" + team.id,
                        "preset=" + preset], cwd=bricks, check=True, capture_output=True, text=True, timeout=60)
        for _ in range(2):
            team.call("spawn", "task=" + READY_TASK, "kind=claude", "mode=build", "browser=true",
                      "prepare=" + args.prepare)
        for wid in ("kaylee", "wash"):
            team.wait(wid, ("idle",), timeout=1800)
        state = team.state()
        a, b = state["workers"]["kaylee"], state["workers"]["wash"]
        report.add(5, "two lanes, two blocks", "PASS" if a["lane"]["base"] != b["lane"]["base"] else "FAIL",
                   "%d and %d" % (a["lane"]["base"], b["lane"]["base"]))

        # ---- steps 2 and 3: inside the first lane, then the second lane looks at the first ----
        settings_file = Path(a["path"]) / ".claude" / "settings.json"
        settings_before = settings_file.read_text() if settings_file.exists() else None
        settings_file.parent.mkdir(exist_ok=True)
        settings_file.write_text(json.dumps(planted_settings(json.loads(settings_before) if settings_before else {})))
        decoy.mkdir(mode=0o700, exist_ok=True)
        lane.check_lane(decoy)                           # never through a link someone planted in /tmp
        lane._write_text(decoy / "secret.txt", "decoy\n", 0o600)
        canary_port = b["lane"]["base"] + 10
        canary = serve_canary(canary_port)
        broker_pid = min(lsof_pids("-iTCP:%d" % (a["lane"]["base"] + 31), "-sTCP:LISTEN") or {0})
        ps = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout
        shell_pid = rendezvous_pid(ps, broker_pid)
        name = RENDEZVOUS % (shell_pid or 0)
        rc = worker_probes.bootstrap_look_up(name)
        report.add(3, "rendezvous positive control (teamd)", "PASS" if rc == 0 else "BROKEN",
                   "%s -> %d (broker %d, browser %s)" % (name, rc, broker_pid, shell_pid))
        if shell_pid:
            for service in NEVER_LIST:
                verdict = sandbox_check(shell_pid, service)
                report.add(3, "sandbox_check %s" % service, "INFO" if verdict is None else
                           ("PASS" if verdict == 1 else "FAIL"), {None: "unavailable", 0: "allowed", 1: "denied"}[verdict])
        sockets = [os.environ["SSH_AUTH_SOCK"]] if os.environ.get("SSH_AUTH_SOCK") else []
        sockets += sorted(str(p) for p in Path("/tmp/sy-team-%d" % uid).glob("*.sock"))
        sockets += [p for p in (str(Path.home() / ".docker/run/docker.sock"), "/var/run/docker.sock") if os.path.exists(p)]
        claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        domains = effective_domains([claude_dir / "settings.json", claude_dir / "settings.local.json",
                                     lane.MANAGED_SETTINGS, settings_file, settings_file.with_name("settings.local.json")])
        reads, missing = read_targets(b["lane"]["path"], decoy, uid)
        for target in missing:
            report.add(2, "read %s" % target, "BROKEN", "it doesn't exist here, so a refusal would prove nothing")
        install_probes(a["path"], {"lane": a["lane"]["path"], "base": a["lane"]["base"], "worktree": a["path"],
                                   "domains": domains, "sockets": sockets, "reads": reads,
                                   "rendezvous": name, "canary_port": canary_port, "write_probe": WRITE_PROBE})
        stream = lane.start_denial_stream()
        team.message("kaylee", probe_message(args.python, "lane"))
        team.wait("kaylee", ("running",), timeout=120)
        a_turn = team.state()["workers"]["kaylee"]["pid"]
        targets = [p for p in (broker_pid, shell_pid, a_turn) if p]
        before = {pid: alive(pid) for pid in targets}
        install_probes(b["path"], {"peer_pids": targets})
        team.message("wash", probe_message(args.python, "peer"))
        team.wait("wash", ("idle",))
        after = {pid: alive(pid) for pid in targets}
        team.wait("kaylee", ("idle",))
        denials = lane.stop_denial_stream(stream)
        lane_results = results(a["path"], "lane")
        for row in lane_results["rows"]:
            step = 3 if row["probe"].startswith(("browser", "rendezvous")) else 2
            if row["expect"] == "denied":
                kind = classify_lookup(row["code"])
                if kind == "other" and denied_lookup(denials, lane_results["pid"]):
                    kind = "denied"
                verdict = {"denied": "PASS", "reachable": "FAIL", "broken": "BROKEN"}.get(kind, "FAIL")
                report.add(3, row["probe"], verdict, "rc %d (%s)" % (row["code"], kind), full=True,
                           notes=["sandbox denial: " + line for line in lane.denials_for(denials, {lane_results["pid"]})]
                           if verdict == "BROKEN" else ())
            else:
                report.add(step, row["probe"], judge(row["expect"], row["code"]), row["detail"])
        written = Path.home() / WRITE_PROBE
        report.add(3, "browser download into $HOME", "FAIL" if written.exists() else "PASS",
                   "written (removed)" if written.exists() else "nothing written")
        if written.exists():
            written.unlink()
        for row in results(b["path"], "peer")["rows"]:
            pid = row["pid"]
            verdict = peer_verdict(row["expect"], row["code"], before.get(pid), after.get(pid))
            report.add(3, "second lane: " + row["probe"], verdict,
                       row["detail"] if verdict != "BROKEN" else "pid %d wasn't alive throughout: rerun" % pid)
        if any(r[2] == "FAIL" and r[1].startswith("second lane") for r in report.rows):
            print("\nA second lane's worker can read the first lane's endpoint: set lane_one_at_a_time in "
                  "~/.superyak/team/config.json, and the spec records it.\n")

        # ---- step 4: D9, D10 and D11 ----
        canary.close()
        canary = None
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        port = listener.getsockname()[1]
        try:
            team.message("kaylee", "Reply with only the word done. Do not run anything.")
            team.wait("kaylee", ("waiting",), timeout=60)
            named = any("LANE WAITING" in m and "port %d" % port in m for m in team.inbox)
            report.add(4, "an unapproved listener makes the turn wait", "PASS" if named else "FAIL", "port %d" % port)
            approved = lane.approved_path()
            listeners_before = approved.read_text() if approved.exists() else None
            entries = json.loads(listeners_before) if listeners_before else []
            approved.write_text(json.dumps(entries + [os.path.realpath(sys.executable)]))
            time.sleep(40)                                   # one retry (LANE_RETRY_S) with the widened list
            team.status()
            still = team.status()["workers"]["kaylee"]["state"] == "waiting"
            refused = any("only Apple programs" in m or "never approved" in m for m in team.inbox)
            report.add(4, "approving an interpreter is refused (D10)", "PASS" if still and refused else "FAIL",
                       "still waiting" if still else "the turn ran")
        finally:
            if listeners_before is None:
                lane.approved_path().unlink(missing_ok=True)
            else:
                lane.approved_path().write_text(listeners_before)
            listeners_before = None
            listener.close()
        state = team.wait("kaylee", ("running", "idle"), timeout=120, patient=True)
        report.add(4, "once it is gone, the turn runs", "PASS", state)
        team.wait("kaylee", ("idle",))
        root_port = free_port()
        root = root_listener(root_port)
        try:
            time.sleep(2)
            found = [item for item in lane.read_listeners() or []
                     if (root and item["port"] == root_port) or (not root and item["port"] == 631)]
            exe = lane.pid_path(found[0]["pid"]) if found else None
            if found and exe:
                report.add(4, "a root-owned listener is seen", "PASS", "pid %d on port %d: %s"
                           % (found[0]["pid"], found[0]["port"], exe))
            else:
                report.add(4, "a root-owned listener is seen", "FAIL", "run `sudo -v` first, or turn Printer Sharing on"
                           if not root else "netstat didn't show it, or its program couldn't be identified")
            if root:
                team.message("kaylee", "Reply with only the word done. Do not run anything.")
                team.wait("kaylee", ("waiting",), timeout=60)
                named = any("LANE WAITING" in m and "port %d" % root_port in m and NETCAT in m for m in team.inbox)
                report.add(4, "it holds the lane, named by its path", "PASS" if named else "FAIL", NETCAT)
        finally:
            if root:
                stop_root_listener(root_port)
                root.wait(timeout=30)
        if root:
            team.wait("kaylee", ("idle",), timeout=180, patient=True)

        # ---- step 5: two browser workers at once, each running Bricks spec 1 ----
        servers = {}
        for wid, w in (("kaylee", a), ("wash", b)):
            install_probes(w["path"], {"worktree": w["path"], "specs": SMOKE_SPECS[:1]})
            team.message(wid, probe_message(args.python, "spec"))
        both = False
        end = time.time() + 2400
        while time.time() < end:
            states = {wid: v["state"] for wid, v in team.status()["workers"].items()}
            if {"failed", "waiting"} & {states["kaylee"], states["wash"]}:
                raise RuntimeError("step 5 stopped: %s; the lead's inbox says: %s"
                                   % (states, " | ".join(team.inbox[-3:])[:800]))
            both = both or (states["kaylee"] == states["wash"] == "running")
            for wid, w in (("kaylee", a), ("wash", b)):
                servers.setdefault(wid, set()).update(block_listeners(w["lane"]["base"]))
            if states["kaylee"] == states["wash"] == "idle":
                break
            time.sleep(5)
        report.add(5, "both ran at the same time", "PASS" if both else "FAIL")
        for wid, w in (("kaylee", a), ("wash", b)):
            report_spec(report, 5, wid, w["path"], SMOKE_SPECS[:1])

        # ---- step 6: the smoke specs, in order ----
        install_probes(a["path"], {"worktree": a["path"], "specs": SMOKE_SPECS})
        team.message("kaylee", probe_message(args.python, "spec"))
        team.wait("kaylee", ("running",), timeout=120)
        while team.status()["workers"]["kaylee"]["state"] == "running":
            servers["kaylee"].update(block_listeners(a["lane"]["base"]))
            time.sleep(5)
        team.wait("kaylee", ("idle",), timeout=60)
        report_spec(report, 6, "kaylee", a["path"], SMOKE_SPECS)

        # ---- step 7: cleanup after worker_done and after stop_worker ----
        shutil.rmtree(Path(a["path"]) / PROBE_DIR, ignore_errors=True)
        shutil.rmtree(Path(b["path"]) / PROBE_DIR, ignore_errors=True)
        if settings_before is None:
            settings_file.unlink()
        else:
            settings_file.write_text(settings_before)
        settings_file = None
        team.message("kaylee", "Call team_done now, with summary 'browser-lane acceptance' and tests 'see the "
                               "acceptance transcript'. Do not run anything else.")
        team.wait("kaylee", ("done",), timeout=600)
        end = time.time() + 120
        while time.time() < end and Path(a["lane"]["path"]).exists():
            time.sleep(2)
        check_cleanup(report, "after worker_done", a, servers["kaylee"] | {broker_pid, shell_pid})
        b_broker = lsof_pids("-iTCP:%d" % (b["lane"]["base"] + 31), "-sTCP:LISTEN")
        team.call("stop", "worker=wash")
        check_cleanup(report, "after stop_worker", b, servers["wash"] | b_broker)
    finally:
        if canary is not None:
            canary.close()
        if settings_file is not None:
            if settings_before is None:
                settings_file.unlink(missing_ok=True)
            else:
                settings_file.write_text(settings_before)
        if listeners_before is not None:
            lane.approved_path().write_text(listeners_before)
        shutil.rmtree(decoy, ignore_errors=True)
        try:
            team.call("end", "summary=browser-lane acceptance")
        except RuntimeError as e:
            print("team end: %s" % e)
        if presets_before is None:
            presets_file.unlink(missing_ok=True)
        else:
            presets_file.write_text(presets_before)
        for branch in git(bricks, "branch", "--list", "team/%s/*" % team.id, "--format=%(refname:short)").split():
            git(bricks, "branch", "-D", branch)


def report_spec(report, step, wid, worktree, specs):
    for i, spec in enumerate(specs):
        path = Path(worktree) / PROBE_DIR / ("spec-%d.json" % i)
        try:
            got = summarize(json.loads(path.read_text()))
        except (OSError, ValueError) as e:
            report.add(step, "%s %s" % (wid, spec), "FAIL", "no JSON report (%s)" % e.__class__.__name__)
            continue
        ok = got["passed"] > 0 and not got["failed"] and not got["errors"]
        report.add(step, "%s %s" % (wid, spec), "PASS" if ok else "FAIL",
                   "%d passed, %d skipped, failed: %s, errors: %s, flaky: %s"
                   % (got["passed"], got["skipped"], got["failed"] or "none", got["errors"] or "none", got["flaky"] or "none"))
        for name in got["advisory"]:
            report.add(step, "%s advisory (reported separately)" % wid, "INFO", name)


def check_cleanup(report, when, w, pids):
    left = block_listeners(w["lane"]["base"])
    report.add(7, "%s: nothing listens on the lane's ports" % when, "FAIL" if left else "PASS", sorted(left) or "")
    running = sorted(p for p in pids if p and alive(p))
    report.add(7, "%s: broker and webServer gone" % when, "FAIL" if running else "PASS", running or "")
    gone = not os.path.lexists(w["lane"]["path"])
    report.add(7, "%s: lane folder gone" % when, "PASS" if gone else "FAIL", w["lane"]["path"])


def list_listeners():
    """Every listener, from the listener check's own enumeration (netstat, root's included, and proc_pidpath)."""
    found = lane.read_listeners()
    if found is None:
        sys.exit("netstat failed, or printed a header the listener check doesn't know")
    try:
        approved = lane.load_approved()
    except lane.LaneRefused as e:
        sys.exit(str(e))
    rows = listener_rows(found, lane.pid_path, approved)
    for pid, address, exe, verdict in rows:
        print("pid %-7d %-26s %s  (%s)" % (pid, address, exe, verdict))
    approvable = sorted({exe for _, _, exe, verdict in rows if verdict.startswith(("approved", "approvable"))})
    print("\nThe approvable ones, for %s:\n%s" % (lane.approved_path(), json.dumps(approvable, indent=1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bricks", type=Path, help="the Bricks checkout, with the Bricks change")
    parser.add_argument("--prepare", default="npm-ci", choices=["npm-ci", "pnpm-install"])
    parser.add_argument("--python", default="/usr/bin/python3", help="the Python the workers run the probes with")
    parser.add_argument("--self-check-only", action="store_true", help="step 1 only (the first install of a revision)")
    parser.add_argument("--list-listeners", action="store_true", help="show every listener, for lane-listeners.json")
    args = parser.parse_args()
    if sys.platform != "darwin" or not (args.bricks or args.list_listeners):
        sys.exit("run it on the Mac, with --bricks")
    if not lane.python_ok():
        sys.exit("lanes need Python 3.11.4 or later (tarfile's data filter); this is %s. Run it as "
                 "`cd team && uv run --python 3.13 python scripts/lane_acceptance.py ...`" % sys.version.split()[0])
    if args.list_listeners:
        return list_listeners()
    args.bricks = args.bricks.expanduser().resolve()
    report = Report()
    print("== step 1: the profile, before any worker ==", flush=True)
    step1(args, report)
    if not args.self_check_only and not report.failed():
        try:
            steps2to7(args, report)
        except (RuntimeError, subprocess.CalledProcessError, OSError, KeyError, ValueError) as e:
            report.add("-", "the run stopped", "FAIL", e)
    failed = report.failed()
    print("\n== %s: %d rows, %d failed ==" % ("PASSED" if not failed else "FAILED", len(report.rows), len(failed)))
    for step, name, verdict, detail in failed:
        print("%-6s step %s  %s  %s" % (verdict, step, name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
