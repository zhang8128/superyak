#!/usr/bin/env python3
"""Browser-lane acceptance run (docs/superpowers/specs/2026-10-08-browser-lane-design.md, "Mac acceptance").

Serenity (an agent, through its Bash tool) normally runs it on the Mac, from the superyak repository, at a time the
Bricks lead picks, with uv's Python (lanes need 3.11.4 or later for tarfile's data filter):

    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --list-listeners      # fill lane-listeners.json
    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --bricks ~/Projects/bricks --self-check-only
    cd team && uv run --python 3.13 python scripts/lane_acceptance.py --bricks ~/Projects/bricks

Prerequisites (the spec's, plus this script's):
- lane_node in ~/.superyak/team/config.json, and no browser_lane anywhere yet: the run makes its own preset, with
  browser_lane on, and removes it when it ends, so no lead can open a lane before the acceptance has passed;
- ~/.superyak/team/lane-listeners.json filled in (--list-listeners shows what is listening now), and nothing else
  listening: dev servers, Ollama, Postgres and Serena dashboards stopped;
- the Bricks checkout on the branch with the Bricks change (lane ports in the Playwright config and fixtures);
- the worktree prepared, so npx needs no registry: the workers are spawned with --prepare (npm-ci by default);
- the headless shell's manifest hash recorded for this revision (--self-check-only prints it the first time);
- a root-owned listener to observe in step 4. Before step 1 the run looks for one that already exists (netstat plus
  `ps -o uid=` equal to 0, on loopback or a wildcard: launchd's *:22 with Remote Login on, or cupsd's 631) and needs no
  sudo for it. If there is none it tries `sudo -n -v` (an agent's Bash tool can't sudo: macOS caches credentials per
  terminal). If that fails too, the run uses a PERSON: inside step 4, after the D9/D10/D11 rows, it prints

      ANDY ACTION: in your own Terminal run: sudo /usr/bin/nc -lk 127.0.0.1 <port>
      (leave it running; this run waits up to 15 minutes)

  and, after the "seen" and "named" rows, `ANDY ACTION: stop it now: press Ctrl-C in that Terminal`. Serenity runs
  the script in the background and passes each `ANDY ACTION:` line to Andy as soon as it appears; Andy's own terminal
  is needed only for this. The script never signals that listener (no sudo, no kill): if it isn't gone 10 minutes
  after the stop request, the row is BROKEN with its pid and `sudo kill <pid>`, and the run stops.

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
import signal
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
HOLDER_POLLS, HOLDER_POLL_S = 30, 2     # how long to look for a first-lane process that carries the endpoint
NOT_READ = object()          # the approved list existed but couldn't be read: it is never touched
# A list entry the approved-list rules refuse for one specific reason (D10), without needing the file to exist.
D10_ENTRY = "/usr/sbin/python3"
# The specs the Bricks lead tagged @lane-advisory (via Serenity), by file; an advisory failure anywhere else is a real
# failure. This is a file-level set for now: tests/gtm/visual-recipes.spec.ts and the individual test titles are still
# pending from the Bricks lead, and until then a failure in a file not listed here (visual-recipes included) is a FAIL.
# visual.spec.ts is skipped unless GTM_SOURCE_VISUAL=1 and uses its own visual.config.ts, so an ordinary lane run
# doesn't run it; it is listed so that it is advisory whenever it does run.
ADVISORY_SPECS = ("tests/gtm/approval-anatomy.spec.ts", "tests/gtm/four-up-school.spec.ts",
                  "tests/gtm/content-recipes-cards.spec.ts", "tests/gtm/supplied-presentation.spec.ts",
                  "tests/gtm/visual.spec.ts")
NO_ROOT = "no root-owned listener to observe; run this once from Andy's own terminal (sudo)"
# What the lead's inbox may be reduced to in a transcript: reason codes, never the messages (they name programs).
REASONS = ("LANE WAITING", "LANE REFUSED", "only Apple programs", "an interpreter is never approved",
           "sealed system volume", "can't be identified", "beyond loopback", "lsof failed", "netstat failed",
           "settings outside the lane", "one browser lane per machine", "manifest")


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
    """The headless shell's main browser process: node's child with no --type= argument (not node's own pid). With no
    broker pid there is nothing to look under: never launchd's children."""
    if not broker_pid:
        return None
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
    "approvable" is exactly what lane.load_approved accepts (lane.approval_problem). Pid 1 is launchd holding a
    socket-activated job's socket; approving /sbin/launchd covers every such job until the job's own program first
    accepts a connection (then it is that program's)."""
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
        elif not lane.approval_problem(exe):
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
    dotfile = next((home / n for n in (".zshrc", ".bashrc", ".profile", ".gitconfig")
                    if (home / n).is_file() and (home / n).stat().st_size > 0), None)
    wanted = {"a dotfile in $HOME": dotfile, "a decoy lane's folder": Path(decoy),
              "the other lane's real folder": Path(other_lane),
              "/private/tmp/claude-<uid>": Path("/private/tmp/claude-%d" % uid)}
    present = {name: str(path) for name, path in wanted.items() if path is not None and path.exists()}
    return present, sorted(set(wanted) - set(present))


# ---------- facts only a Mac can settle (review rows): each returns rows, or a (verdict, detail) ----------

def judge_row(row):
    """A worker-probe row's verdict. ok: exit 0 passes. fail: exit 0 FAILS (the wall let it through); exit 1 is a
    refusal that passes only if its code is one the row accepts (`refusals`, None meaning the probe proved it
    itself); anything else (a timeout, a crash, exit 2, a refusal for another reason such as ENOENT) proves nothing
    and is BROKEN. info is only shown."""
    expect, code = row["expect"], row["code"]
    if expect == "info":
        return "INFO"
    if expect == "ok":
        return "PASS" if code == 0 else "FAIL"
    if code == 0:
        return "FAIL"
    if code != 1:
        return "BROKEN"
    refusals = row.get("refusals")
    if refusals is None:
        return "PASS"
    found = re.match(r"refused: (\S+)", row.get("detail") or "")
    return "PASS" if found and found.group(1) in refusals else "BROKEN"


def download_shaped(names):
    """Of the new names in $HOME, those a download makes: the expected file name, `name (n).ext`, Chrome's
    `*.crdownload` and `Unconfirmed *`. Anything else (history files, caches) is somebody else's."""
    stem, ext = os.path.splitext(WRITE_PROBE)
    pattern = re.compile(r"%s(?: \([0-9]+\))?%s" % (re.escape(stem), re.escape(ext)))
    return sorted(n for n in names if n.endswith(".crdownload") or n.startswith("Unconfirmed ") or pattern.fullmatch(n))


def download_verdict(code, detail, new_names, control_present, leftovers, home_in_b=False):
    """The browser download row (spec step 3): the client reports whether each download began and for how many contexts
    the download behaviour was set; the driver, outside the sandbox, compares $HOME's top-level names and looks for the
    control file in the lane's b/. PASS needs the control to have landed, a behaviour set for $HOME and its download
    begun, that download NOT to have landed in b/ (then the override didn't reach it), and no new download-shaped name
    in $HOME. Names only are ever printed."""
    if leftovers:
        return "BROKEN", "left alone, from an earlier run: %s" % ", ".join(sorted(leftovers))
    try:
        result = json.loads(detail)
        result["control"]["began"], result["home"]["began"], result["home"]["set"]
    except (ValueError, KeyError, TypeError):
        result = None
    if code != 0 or result is None:
        return "BROKEN", "the client could not run the downloads: %s" % " ".join(str(detail).split())[:160]
    if not result["control"]["began"] or not control_present:
        return "BROKEN", "the control download into the lane's b/ did not land (began: %s), so a missing download in $HOME " \
                         "would prove nothing" % result["control"]["began"]
    if not result["home"]["set"]:
        return "BROKEN", "no download behaviour could be set for the page's context, so $HOME was never the target"
    if not result["home"]["began"]:
        return "BROKEN", "no download into $HOME ever started"
    if home_in_b:
        return "BROKEN", "the download meant for $HOME landed in the lane's b/: the override didn't reach it"
    shaped = download_shaped(new_names)
    if shaped:
        return "FAIL", "new in $HOME: %s" % ", ".join(shaped)
    return "PASS", "the control landed in b/, the download into $HOME began (%s), and $HOME has no new download" \
                   % "/".join(result["home"]["states"] or ["no progress event"])



def reason_codes(inbox):
    """The lead's messages reduced to known reason codes, in order, without the messages: they name the programs that
    listen on the machine and their paths."""
    found = []
    for message in inbox:
        for code in REASONS:
            if code in str(message) and code not in found:
                found.append(code)
    return found


def rendezvous_verdict(rc, denials, pid):
    """Step 3's rendezvous lookup from inside the worker: 1100, or a deny line for the probe's own pid, passes; 1102 is a
    broken check; reachable fails."""
    kind = classify_lookup(rc)
    if kind == "other" and denied_lookup(denials, pid):
        kind = "denied"
    return {"denied": "PASS", "reachable": "FAIL", "broken": "BROKEN"}.get(kind, "FAIL"), "rc %d (%s)" % (rc, kind)


def peer_targets(pids, environ=None, command=None):
    """(holders, others): only a process whose environment holds the endpoint is a target for the second lane's
    check; for any other, "can't read the endpoint" would be true of everything. With `command`, only claude and the
    worker_probes process count (a shell or a leftover child carrying the same environment says little)."""
    environ = environ or lane._environ
    holders = [pid for pid in pids if any(e.startswith("PW_TEST_CONNECT_WS_ENDPOINT=") for e in environ(pid) or [])]
    if command is not None:
        holders = [pid for pid in holders if re.search(r"claude|worker_probes\.py", command(pid) or "")]
    return holders, [pid for pid in pids if pid not in holders]


def commands_of(ps_text):
    """{pid: command} from `ps -A -o pid=,ppid=,command=`."""
    out = {}
    for line in ps_text.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            out[int(fields[0])] = fields[2]
    return out



def usable_sockets(paths):
    """(accepting, [(path, why)]): which sockets accept a connection from outside the sandbox. A refusal inside
    proves nothing about one that wouldn't accept anyone."""
    ok, bad = [], []
    for path in paths:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        try:
            s.connect(path)
            ok.append(path)
        except OSError as e:
            bad.append((path, e.strerror or e.__class__.__name__))
        finally:
            s.close()
    return ok, bad


def nc_descendants(ps_text, root_pid, port):
    """Every descendant of `root_pid` (sudo, its pty monitor, nc: the tree is sudo -> monitor -> nc under a pty) whose
    command is /usr/bin/nc on this port, from `ps -A -o pid=,ppid=,command=`. Never a process found by port alone."""
    if root_pid <= 1:
        return []
    children, commands = {}, commands_of(ps_text)
    for line in ps_text.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found, stack, seen = [], list(children.get(root_pid, [])), set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack += children.get(pid, [])
        words = commands.get(pid, "").split()
        if words[:1] == [NETCAT] and str(port) in words:
            found.append(pid)
    return sorted(found)



def both_serving(states, listeners, brokers):
    """Step 5's "at the same time": both workers running, and in each block a listener that isn't the broker."""
    return all(states.get(w) == "running" and (listeners.get(w, set()) - brokers.get(w, set())) for w in ("kaylee", "wash"))


def missing_probe_rows(rows):
    """Step 1: the probes lane.self_check should have produced a row for and didn't."""
    got = {name for name, _, _ in rows}
    return sorted(set(lane.SELF_CHECK_PROBES + lane.SELF_CHECK_POSITIVE) - got)


def root_listener_proof(pid, port, owner=None):
    """Step 4's root listener: it must be owned by uid 0 (`ps -o uid=`), and the user's own lsof must NOT show it, which is
    what proves the netstat path is the one that sees it. Returns (verdict, detail)."""
    owner = owner or (lambda p: _owner_uid(p))
    uid = owner(pid)
    if uid != 0:
        return "BROKEN", "pid %d on port %d is owned by uid %s, not root, so it doesn't show that root's sockets are seen" % (pid, port, uid)
    seen = lane.lsof_listeners()
    if seen is None:
        return "BROKEN", "lsof failed, so the cross-check couldn't be made"
    if (pid, port) in seen:
        return "BROKEN", "the user's lsof also shows pid %d on port %d, so netstat isn't what proves root's listeners are seen" % (pid, port)
    return "PASS", "pid %d (uid 0) on port %d is in netstat and not in the user's lsof" % (pid, port)


def _owner_uid(pid):
    r = lane._run(["/bin/ps", "-o", "uid=", "-p", str(pid)], timeout=10)
    text = (r.stdout if r is not None and r.returncode == 0 else "").strip()
    return int(text) if text.isdigit() else None



class DenialStream:
    """The sandbox's denial stream (`log stream`), drained on a thread from the moment it starts (as lane._drain does a
    broker's output), so a full pipe never drops a line. wait_ready() returns once its first line (the header) has
    arrived; finish() reads until it has been quiet for `quiet` seconds or `cap` have passed, then stops it with SIGINT.
    `proc` is lane.start_denial_stream()'s Popen, or None where the stream isn't available."""

    def __init__(self, proc):
        self.proc, self.lines, self.last = proc, [], time.monotonic()
        self.available = proc is not None
        self.lock = threading.Lock()
        self.thread = None
        if proc is not None:
            self.thread = threading.Thread(target=self._drain, daemon=True)
            self.thread.start()

    def _drain(self):
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip("\n"))
                self.last = time.monotonic()

    def wait_ready(self, timeout=10):
        end = time.monotonic() + timeout
        while self.available and time.monotonic() < end:
            with self.lock:
                if self.lines:
                    return True
            time.sleep(0.1)
        return False

    def finish(self, quiet=3, cap=20):
        if self.proc is None:
            return []
        start = time.monotonic()
        while time.monotonic() - start < cap and self.proc.poll() is None:
            with self.lock:
                idle = time.monotonic() - max(self.last, start)
            if idle >= quiet:
                break
            time.sleep(0.1)
        try:
            os.kill(self.proc.pid, signal.SIGINT)
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.thread.join(timeout=5)
        with self.lock:
            return list(self.lines)


class PidRecorder:
    """subprocess.run for lane.self_check's `run` seam, remembering each probe's pids: sandbox-exec execs the probe in
    its own pid, and profile_probe.js prints the pid of the child it spawns (the process refused an exec is that child)
    on stderr as `child pid N`. A row is (probe, planted, pid); planted is True when a system.sb sat in the probe's cwd
    (the planted-import rerun)."""

    def __init__(self):
        self.pids, self.windows = [], []

    def __call__(self, cmd, env=None, cwd=None, timeout=None, **_):
        started = time.time()
        try:
            return self._run(cmd, env, cwd, timeout)
        finally:
            self.windows.append((cmd[-1], os.path.exists(os.path.join(cwd or "", "system.sb")), started, time.time()))

    def _run(self, cmd, env, cwd, timeout):
        proc = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                errors="replace")
        planted = os.path.exists(os.path.join(cwd or "", "system.sb"))
        self.pids.append((cmd[-1], planted, proc.pid))
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        for child in re.findall(r"^child pid ([0-9]+)$", err or "", re.M):
            if int(child) > 0:
                self.pids.append((cmd[-1], planted, int(child)))
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

    def pids_of(self, probe, planted=False):
        return [pid for name, was_planted, pid in self.pids if name == probe and was_planted == planted]

    def pid_of(self, probe, planted=False):
        found = self.pids_of(probe, planted)
        return found[0] if found else None






DENIAL_TIME = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})")


def exec_denials(lines, program, start, end):
    """`process-exec` denials whose target is `program`, stamped within [start, end] (epoch seconds, local time as
    `log stream` prints it). When an exec is refused, spawnSync's pid is 0 and the denial is charged to a process we
    never learned the pid of, so it is matched by what it tried to run and when."""
    found = []
    for line in lines:
        stamp, match = DENIAL_TIME.match(line), lane.DENIAL_RE.search(line)
        if not stamp or not match or not match.group(3).startswith("process-exec") or match.group(4).strip() != program:
            continue
        when = time.mktime(time.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S"))
        if start <= when <= end:
            key = "%s(%s): %s %s" % (match.group(1).strip(), match.group(2), match.group(3), match.group(4)[:160])
            if key not in found:
                found.append(key)
    return found


def report_profile_rows(report, rows, recorder, denials, step=1, stream=True):
    """Every profile row with its whole detail (`refused: <code> (<message>)`). A BROKEN row also gets the sandbox
    denial lines for that probe's pids (the probe and the child it spawned), filtered by pid with lane.denials_for,
    never by name, plus the `process-exec` denials of the probe's program within the probe's time window."""
    for probe, verdict, detail in rows:
        notes = []
        if verdict == "BROKEN":
            planted = probe.startswith("planted-import:")
            name = probe.split(":", 1)[1] if planted else probe
            pids = recorder.pids_of(name, planted)
            label = "pid %d" % pids[0] if len(pids) == 1 else "pids " + ", ".join(str(p) for p in pids)
            if not pids:
                notes.append("no sandbox denial lines: the probe never ran")
            elif not stream:
                notes.append("no sandbox denial lines for %s: the denial stream isn't available" % label)
            else:
                lines = lane.denials_for(denials, set(pids))
                program = lane.PROBE_PROGRAMS.get(name)
                for probe_name, was_planted, begin, finish in getattr(recorder, "windows", []):
                    if program and probe_name == name and was_planted == planted:
                        lines += [l for l in exec_denials(denials, program, begin - 1, finish + 2) if l not in lines]
                notes += ["sandbox denial: " + line for line in lines] or ["no sandbox denial lines for %s" % label]
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
            rows.extend(("planted-import:" + probe, "BROKEN", "the profile has no (import \"system.sb\") to test, or the "
                         "planted file isn't there") for probe in ("write_home", "read_dotfile"))
            return rows                                  # the same list: the cleanup below still adds its rows
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
    """Review row `lsof-exit`: the full listing cleanup runs (`lsof -nP -a -u <uid> -F pn`) and its exit code, recorded
    as information. Cleanup needs 0 (lane_pids treats anything else as "can't say" and keeps the block held), so a
    routine exit 1 on this Mac shows up here, and step 7's rows show its consequence. lsof's stderr is not echoed (it can
    name files). Returns (verdict, detail)."""
    run = run or lane._run
    lsof = shutil.which("lsof", path=lane.SYSTEM_PATH)
    if not lsof:
        return "BROKEN", "lsof isn't in %s" % lane.SYSTEM_PATH
    r = run([lsof, "-nP", "-a", "-u", str(os.getuid()), "-F", "pn"], timeout=120)
    if r is None:
        return "BROKEN", "lsof couldn't run (or timed out)"
    return "INFO", "exit %d (cleanup needs 0), %d lines of output, %d bytes of stderr" \
                   % (r.returncode, (r.stdout or "").count("\n"), len(r.stderr or ""))



HELPERS = []            # the helper processes hardlink_naming started (the tests find their pids here)
HOLDER = "import sys, time\nf = open(sys.argv[1])\nprint('ready', flush=True)\ntime.sleep(300)\n"


def _descriptors(text):
    """`lsof -F pfin` output as [(fd, inode, name)] for one process."""
    out, current = [], None
    for line in text.splitlines():
        if line.startswith("f"):
            current = {"fd": line[1:], "inode": None, "name": None}
            out.append(current)
        elif current is not None and line.startswith("i"):
            current["inode"] = line[1:]
        elif current is not None and line.startswith("n"):
            current["name"] = line[1:]
    return [(d["fd"], d["inode"], d["name"]) for d in out]


def hardlink_naming():
    """Review row `hardlink-naming`: a file another process of this user holds open, hard-linked into the lane's tmp/.
    lsof may name a hard-linked file by whichever name was looked up last, so the file is stat'ed and opened through
    the LANE's path first, as a hostile lane would; the helper's descriptor is then found by inode (under either name)
    and the name lsof reports is printed. The verdict is the cleanup matcher's own: lane.lane_pids must NOT name the
    helper. BROKEN if no descriptor of the helper has the file's inode. The only process involved is a helper this
    function starts and ends. Returns (verdict, detail)."""
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
        linked = path / "tmp" / "linked.txt"
        os.link(held, linked)
        st = os.lstat(linked)                               # through the lane's path, as a hostile lane would
        os.close(os.open(linked, os.O_RDONLY | os.O_NOFOLLOW))
        lsof = shutil.which("lsof", path=lane.SYSTEM_PATH)
        seen = lane._run([lsof, "-nP", "-p", str(helper.pid), "-F", "pfin"]) if lsof else None
        matches = [(fd, name) for fd, inode, name in _descriptors(seen.stdout if seen is not None else "")
                   if inode == str(st.st_ino)]
        if not matches:
            return "BROKEN", "none of the helper's descriptors has inode %d, so the matcher had nothing to name" % st.st_ino
        pids = lane.lane_pids(path, None)
        if pids is None:
            return "BROKEN", "lsof couldn't say (lane_pids gave None)"
        where = "descriptor %s (inode %d), which lsof reports as %s" % (matches[0][0], st.st_ino, matches[0][1])
        if helper.pid in pids:
            return "FAIL", "the helper (pid %d), %s, is in the kill set: the hard link made it look like the lane's" \
                   % (helper.pid, where)
        return "PASS", "the helper (pid %d) holds %s; it is not in the kill set" % (helper.pid, where)
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
    for test fixtures. A listening address that is neither a wildcard nor loopback becomes `<addr>.<port>`. Process names that aren't Apple's (by proc_pidpath, in the folders the approved list allows)
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
        address = line.split()[3]
        host, _, port = address.rpartition(".")
        keep = host in lane.WILDCARDS or lane.is_loopback(host) or host.endswith("%lo0")
        if named:
            fields = line.split()
            segment = " ".join(fields[index:len(fields) - trailing])
            found = re.fullmatch(r"(.*):([0-9]+)", segment)
            exe = path_of(int(found.group(2))) if found else None
            if not (exe and exe.startswith(lane.APPROVED_DIRS)) and segment in line:
                line = line.replace(segment, "<name>:%s" % (found.group(2) if found else "0"), 1)
        if not keep:                                        # a LAN or tailnet address identifies the machine
            line = line.replace(address, "<addr>." + port, 1)
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

    @staticmethod
    def clean(text):
        """Whatever is printed or kept: an endpoint's secret is removed first (global-constraints: no log line)."""
        return lane.ENDPOINT_RE.sub(r"\1[lane secret]", str(text))

    def add(self, step, name, verdict, detail="", full=False, notes=()):
        """One row. `full` prints the whole detail (the profile rows: the refusal's code and message are the
        evidence); `notes` are extra lines under it (a BROKEN probe's sandbox denials)."""
        name, detail = self.clean(name), self.clean(detail)
        self.rows.append((step, name, verdict, detail))
        text = " ".join(detail.split())
        print("%-6s step %s  %-44s %s" % (verdict, step, name, text if full else text[:220]), flush=True)
        for note in notes:
            print("         %s" % " ".join(self.clean(note).split()), flush=True)

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
                raise RuntimeError("%s is %s; the lead's messages name: %s"
                                   % (wid, state, ", ".join(reason_codes(self.inbox[-3:])) or "no known reason"))
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


def serving_pids(base):
    """(servers, brokers) in a lane's block right now: the broker is whatever listens on base + 31 at THIS poll (a
    restarted broker has new pids), the servers are the rest of the block."""
    brokers = lsof_pids("-iTCP:%d" % (base + lane.BLOCK - 1), "-sTCP:LISTEN")
    return block_listeners(base) - brokers, brokers


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


class Canary:
    """A loopback service on `port`. close() stops it and waits, so the port is free when it returns (a thread blocked in
    accept() would otherwise keep the listening socket alive)."""

    def __init__(self, port):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", port))
        self.srv.listen(5)
        self.srv.settimeout(0.2)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stopped.is_set():
            try:
                conn, _ = self.srv.accept()
                conn.sendall(b"HTTP/1.0 200 OK\r\n\r\ncanary\n")
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                return

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=5)
        self.srv.close()


def serve_canary(port):
    """A loopback service outside the first lane's ports (in the second lane's block, so the listener check passes)."""
    return Canary(port)


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
    # lsof-exit: cleanup needs the full listing to exit 0 (information; step 7 shows the consequence)
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
    recorder, stream = PidRecorder(), DenialStream(lane.start_denial_stream())
    if stream.available and not stream.wait_ready(10):
        report.add(1, "denial stream", "INFO", "no output from `log stream` within 10 s: BROKEN rows may lack denial lines")
    rows = guarded(report, 1, "profile:self_check", lambda: lane.self_check(node, pw, shell, run=recorder)) or []
    for probe in missing_probe_rows(rows) if rows else []:
        rows.append((probe, "BROKEN", "the self-check produced no row for this probe"))
    rows += guarded(report, 1, "planted-import", lambda: planted_import(node, pw, shell, recorder)) or []
    denials = stream.finish(quiet=3, cap=20)
    report_profile_rows(report, rows, recorder, denials, stream=stream.available)
    return True


class SudoKeeper:
    """`sudo -n -v` (credentials the person already has in this terminal) at the start and every 60 s while the run
    lasts, so step 4's root listener can start however long steps 1-3 take. Never a password prompt."""

    def __init__(self, run=subprocess.run, every=60):
        self.run, self.every, self.stopper, self.thread = run, every, threading.Event(), None

    def start(self):
        if self.run(["/usr/bin/sudo", "-n", "-v"], capture_output=True).returncode != 0:
            return False
        self.thread = threading.Thread(target=self._refresh, daemon=True)
        self.thread.start()
        return True

    def _refresh(self):
        while not self.stopper.wait(self.every):
            self.run(["/usr/bin/sudo", "-n", "-v"], capture_output=True)

    def stop(self):
        self.stopper.set()
        if self.thread is not None:
            self.thread.join(timeout=5)


def root_listener(port):
    """A root-owned listener for step 4: `sudo -n nc -l` on a loopback port (SudoKeeper holds the credentials), or
    None."""
    if subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/true"], capture_output=True).returncode != 0:
        return None
    return subprocess.Popen(["/usr/bin/sudo", "-n", NETCAT, "-l", "127.0.0.1", str(port)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _ps_text():
    return subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,command="], capture_output=True, text=True).stdout


def _listening(port):
    return any(item["port"] == port for item in lane.read_listeners() or [])


def stop_root_listener(root, port, ps=None, kill=None, listening=None, say=print):
    """End the listener we started: `sudo -n /bin/kill -TERM` to our sudo (it relays the signal), then to every `nc` on
    our port among sudo's descendants (under a pty the tree is sudo -> monitor -> nc), found from the process table
    by parentage and command, never by port alone. If the port is still listening afterwards, say loudly how to
    stop it by hand."""
    ps = ps or _ps_text
    kill = kill or (lambda pid: subprocess.run(["/usr/bin/sudo", "-n", "/bin/kill", "-TERM", str(pid)], capture_output=True))
    listening = listening or _listening
    left = nc_descendants(ps(), root.pid, port)        # BEFORE the kill: once sudo is gone an nc belongs to launchd
    kill(root.pid)
    try:
        root.wait(timeout=10)
    except subprocess.TimeoutExpired:
        say("the root listener's sudo (pid %d) is still running: stop it by hand with `sudo kill %d`" % (root.pid, root.pid))
    for pid in left:
        kill(pid)
    for _ in range(6):
        if not listening(port):
            return
        time.sleep(0.5)
    say("*** STILL LISTENING: a root-owned nc is still listening on 127.0.0.1:%d. Stop it by hand: sudo kill %s ***"
        % (port, " ".join(str(p) for p in left + [root.pid])))


def choose_root_listener(read=None, owner=None, path_of=None, run=None):
    """Before step 1: the root-owned listener step 4 will observe. First an EXISTING one (netstat, owner uid 0 by
    `ps -o uid=`, reachable: loopback or a wildcard, program identified), which needs no sudo. Only if there is none,
    `sudo -n -v` (an agent's Bash tool can't sudo: macOS caches credentials per terminal). Otherwise a PERSON starts
    one in step 4 (person_root_rows). Returns {"kind": "existing", pid, port, host, exe} | {"kind": "sudo"} |
    {"kind": "person"}."""
    read, owner = read or lane.read_listeners, owner or _owner_uid
    path_of, run = path_of or lane.pid_path, run or subprocess.run
    for item in sorted(read() or [], key=lambda i: (i["port"], i["pid"])):
        if not (item["host"] in lane.WILDCARDS or lane.is_loopback(item["host"])) or owner(item["pid"]) != 0:
            continue
        exe = path_of(item["pid"])
        if exe:
            return {"kind": "existing", "pid": item["pid"], "port": item["port"], "host": item["host"], "exe": exe}
    try:
        if run(["/usr/bin/sudo", "-n", "-v"], capture_output=True).returncode == 0:
            return {"kind": "sudo"}
    except OSError:
        pass
    return {"kind": "person"}


def root_rows_unavailable(report, reason):
    for row in ("a root-owned listener is seen", "it holds the lane, named by its path"):
        report.add(4, row, "BROKEN", reason)


def socket_candidates(team_id, env, home):
    """The sockets steps 2-3 try: the ssh-agent's, THIS run's team socket (never another team's live teamd) and
    Docker's."""
    out = [env["SSH_AUTH_SOCK"]] if env.get("SSH_AUTH_SOCK") else []
    mine = Path(teamlib.sock_path(team_id))
    if mine.exists():
        out.append(str(mine))
    out += [p for p in (str(Path(home) / ".docker/run/docker.sock"), "/var/run/docker.sock") if os.path.exists(p)]
    return out


def reach_targets(connect=None, resolve=None):
    """The network targets the probes use (curl and node: 1.1.1.1:80, example.com), tried from outside the sandbox.
    Returns the list of targets that failed (empty: the network is up)."""
    connect, resolve = connect or socket.create_connection, resolve or socket.getaddrinfo
    failed = []
    for label, action in (("1.1.1.1:80", lambda: connect(("1.1.1.1", 80), timeout=3).close()),
                          ("example.com (resolve)", lambda: resolve("example.com", 443)),
                          ("example.com:443", lambda: connect(("example.com", 443), timeout=3).close())):
        try:
            action()
        except OSError:
            failed.append(label)
    return failed


def read_original(path):
    """The approved list as it is now: its text, None when there is none, NOT_READ when it exists but can't be read
    (then it is never touched)."""
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return NOT_READ


def write_approved(path, text):
    """The approved list, whole or not at all: a temp file in the same folder (0600), fsynced, then os.replace. A kill
    can never leave it truncated."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".lane-listeners-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def restore_approved(path, original, touched):
    """Put back exactly what read_original saw, if this run changed it. True when it did."""
    if not touched or original is NOT_READ:
        return False
    if original is None:
        Path(path).unlink(missing_ok=True)
    else:
        write_approved(path, original)
    return True


class ApprovedList:
    """Andy's lane-listeners.json for the length of the run: read once, changed only through write() (which marks it
    touched AFTER the write succeeded), and put back by restore() (idempotent)."""

    def __init__(self, path):
        self.path = Path(path)
        self.original = read_original(path)
        self.touched = False

    def entries(self):
        try:
            return json.loads(self.original) if self.original else []
        except ValueError:
            return []

    def write(self, text):
        write_approved(self.path, text)
        self.touched = True

    def restore(self):
        if restore_approved(self.path, self.original, self.touched):
            self.touched = False


def git_try(repo, *args):
    """git whose failure is not an error (cleanup in a finally): the output, or ''."""
    try:
        return git(repo, *args)
    except (subprocess.CalledProcessError, OSError):
        return ""


def delete_branches(bricks, team_id):
    for branch in git_try(bricks, "branch", "--list", "team/%s/*" % team_id, "--format=%(refname:short)").split():
        git_try(bricks, "branch", "-D", branch)


def broker_and_browser_pids(report, ps_text, brokers):
    """The headless shell's pid, or None with a BROKEN row. `brokers` is every pid listening on the broker's port
    (base + 31), however many; never launchd's children when there are none."""
    pids = sorted(brokers) if isinstance(brokers, (set, frozenset, list, tuple)) else ([brokers] if brokers else [])
    if not pids:
        report.add(3, "rendezvous positive control (teamd)", "BROKEN",
                   "no broker pid: lsof found no listener on the lane's broker port")
        return None
    for pid in pids:
        shell_pid = rendezvous_pid(ps_text, pid)
        if shell_pid is not None:
            return shell_pid
    report.add(3, "rendezvous positive control (teamd)", "BROKEN",
               "the broker (pid %s) has no browser process" % ", ".join(str(p) for p in pids))
    return None



def preflight(args, report):
    """The world, before blaming the sandbox: a refusal inside a lane means nothing if the probes' own targets can't be
    reached from outside it."""
    failed = reach_targets()
    report.add(2, "the probes' network targets are reachable outside the sandbox", "BROKEN" if failed else "PASS",
               ("a refusal would prove nothing: no steps 2-7; unreachable: " + ", ".join(failed)) if failed
               else "1.1.1.1:80 and example.com, so a refusal in a lane is the sandbox's")
    return not failed



def install_signal_handlers():
    """SIGTERM and SIGHUP raise SystemExit, so every `finally` (the settings, the list, the preset, the team) runs."""
    def stop(signum, frame):
        raise SystemExit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)


def steps2to7(args, report):
    bricks, uid = args.bricks, os.getuid()
    stamp = time.strftime("%m%d%H%M")
    team, preset = Team(bricks, "lane-acceptance-%s" % stamp), "lane-acceptance-%s" % stamp
    presets_file = teamlib.presets_path()
    presets_before = presets_file.read_text() if presets_file.exists() else None
    approved = lane.approved_path()
    al = ApprovedList(approved)
    decoy = lane.private_parent() / "acceptance-decoy"
    settings_file, settings_before, canary = None, None, None
    try:
        if not preflight(args, report):
            return
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
        brokers = {"kaylee": lsof_pids("-iTCP:%d" % (a["lane"]["base"] + 31), "-sTCP:LISTEN"),
                   "wash": lsof_pids("-iTCP:%d" % (b["lane"]["base"] + 31), "-sTCP:LISTEN")}

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
        broker_ids = set(brokers["kaylee"])              # by the broker's port (base + 31), however many pids hold it
        ps = _ps_text()
        shell_pid = broker_and_browser_pids(report, ps, broker_ids)
        name = RENDEZVOUS % (shell_pid or 0)
        if shell_pid:
            rc = worker_probes.bootstrap_look_up(name)
            report.add(3, "rendezvous positive control (teamd)", "PASS" if rc == 0 else "BROKEN",
                       "%s -> %d (broker %s, browser %s)" % (name, rc, sorted(broker_ids), shell_pid))
            for service in NEVER_LIST:
                verdict = sandbox_check(shell_pid, service)
                report.add(3, "sandbox_check %s" % service, "INFO" if verdict is None else
                           ("PASS" if verdict == 1 else "FAIL"), {None: "unavailable", 0: "allowed", 1: "denied"}[verdict])
        if not os.environ.get("SSH_AUTH_SOCK"):
            report.add(2, "an ssh-agent socket to test", "BROKEN", "SSH_AUTH_SOCK isn't set, so that wall isn't tested")
        candidates = socket_candidates(team.id, os.environ, Path.home())
        sockets, unusable = usable_sockets(candidates)
        for path, why in unusable:
            report.add(2, "socket %s" % path, "BROKEN" if path == os.environ.get("SSH_AUTH_SOCK") else "INFO",
                       "it doesn't accept a connection from outside the sandbox (%s), so a refusal would prove nothing" % why)
        claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        domains = effective_domains([claude_dir / "settings.json", claude_dir / "settings.local.json",
                                     lane.MANAGED_SETTINGS, settings_file, settings_file.with_name("settings.local.json")])
        reads, missing = read_targets(b["lane"]["path"], decoy, uid)
        for target in missing:
            report.add(2, "read %s" % target, "BROKEN", "it doesn't exist here, so a refusal would prove nothing")
        home = Path.home()
        control_dir, control_name = Path(a["lane"]["path"]) / "b", WRITE_PROBE.replace(".txt", "-control.txt")
        leftovers = [str(x) for x in (home / WRITE_PROBE, control_dir / control_name, control_dir / WRITE_PROBE)
                     if os.path.lexists(x)]
        home_before = set(os.listdir(home))
        marker = Path(a["path"]) / PROBE_DIR / "peer-done"
        install_probes(a["path"], {"lane": a["lane"]["path"], "base": a["lane"]["base"], "worktree": a["path"],
                                   "domains": domains, "sockets": sockets, "reads": reads,
                                   "dotfile": reads.get("a dotfile in $HOME"), "home": str(home),
                                   "control_dir": str(control_dir), "write_probe_control": control_name,
                                   "rendezvous": name, "canary_port": canary_port, "write_probe": WRITE_PROBE,
                                   "hold_marker": str(marker), "hold_s": 900})
        stream = DenialStream(lane.start_denial_stream())
        stream.wait_ready(10)
        team.message("kaylee", probe_message(args.python, "lane"))
        team.wait("kaylee", ("running",), timeout=120)
        a_turn = team.state()["workers"]["kaylee"]["pid"]
        holders = []
        for _ in range(HOLDER_POLLS):                    # the turn and its children that carry the endpoint
            holders, _others = peer_targets(sorted(lane.family(a_turn)[0] | {a_turn}), command=commands_of(_ps_text()).get)
            if holders:
                break
            time.sleep(HOLDER_POLL_S)
        if not holders:
            report.add(3, "second lane: a first-lane process that holds the endpoint", "BROKEN",
                       "none of the turn's processes carries PW_TEST_CONNECT_WS_ENDPOINT, so there is nothing to read")
        targets = holders
        before = {pid: alive(pid) for pid in targets}
        install_probes(b["path"], {"peer_pids": targets})
        team.message("wash", probe_message(args.python, "peer"))
        team.wait("wash", ("idle",))
        after = {pid: alive(pid) for pid in targets}
        marker.write_text("done\n")                       # kaylee's round was held open until now
        team.wait("kaylee", ("idle",))
        denials = stream.finish(quiet=3, cap=20)
        lane_results = results(a["path"], "lane")
        download = {}
        for row in lane_results["rows"]:
            step = 3 if row["probe"].startswith(("browser", "rendezvous")) else 2
            if row["expect"] == "denied":
                verdict, detail = rendezvous_verdict(row["code"], denials, lane_results["pid"])
                report.add(3, row["probe"], verdict, detail, full=True,
                           notes=["sandbox denial: " + line for line in lane.denials_for(denials, {lane_results["pid"]})]
                           if verdict == "BROKEN" else ())
            else:
                if row["probe"] == "browser write":
                    download = row
                report.add(step, row["probe"], judge_row(row), row["detail"], full=True)
        new_names = sorted(set(os.listdir(home)) - home_before)
        written = home / WRITE_PROBE
        control_present = os.path.lexists(control_dir / control_name)
        home_in_b = os.path.lexists(control_dir / WRITE_PROBE) and str(control_dir / WRITE_PROBE) not in leftovers
        verdict, detail = download_verdict(download.get("code", 2), download.get("detail", "no result"), new_names,
                                           control_present, leftovers, home_in_b=home_in_b)
        report.add(3, "browser download into $HOME", verdict, detail, full=True)
        for created in (written, control_dir / control_name, control_dir / WRITE_PROBE):      # what this run made; a leftover from before stays
            if str(created) not in leftovers and os.path.lexists(created):
                try:
                    os.unlink(created)
                except OSError:
                    pass
        peer_rows = results(b["path"], "peer")["rows"]
        for row in peer_rows:
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
        if al.original is NOT_READ:
            report.add(4, "the approved list can be put back", "BROKEN",
                       "%s exists but can't be read, so it is left alone and D10 isn't tried" % approved)
        try:
            team.message("kaylee", "Reply with only the word done. Do not run anything.")
            team.wait("kaylee", ("waiting",), timeout=60)
            exe = os.path.realpath(sys.executable)
            named = any("LANE WAITING" in m and "port %d" % port in m and exe in m for m in team.inbox)
            report.add(4, "an unapproved listener makes the turn wait", "PASS" if named else "FAIL",
                       "port %d, named with its path %s" % (port, exe) if named else "port %d: the lead's messages name: %s"
                       % (port, ", ".join(reason_codes(team.inbox)) or "nothing"))
            if al.original is not NOT_READ:
                al.write(json.dumps(al.entries() + [D10_ENTRY]))             # touched only once the write has succeeded
                time.sleep(40)                               # one retry (LANE_RETRY_S) with the widened list
                team.status()
                still = team.status()["workers"]["kaylee"]["state"] == "waiting"
                refused = any("an interpreter is never approved" in m for m in team.inbox)
                report.add(4, "an interpreter on the approved list is refused (D10)", "PASS" if still and refused else "FAIL",
                           "still waiting; the lead's messages name: %s" % (", ".join(reason_codes(team.inbox)) or "nothing")
                           if still else "the turn ran")
                al.write(json.dumps([exe]))
                try:
                    lane.load_approved()
                    d11 = ("FAIL", "%s was accepted as an approved program" % exe)
                except lane.LaneRefused as e:
                    d11 = ("PASS", "refused: only Apple programs") if "only Apple programs" in str(e) else \
                          ("BROKEN", "refused for another reason: %s" % lane.approval_problem(exe))
                report.add(4, "a non-Apple program on the approved list is refused (D11)", *d11)
        finally:
            al.restore()
            listener.close()
        state = team.wait("kaylee", ("running", "idle"), timeout=120, patient=True)
        report.add(4, "once it is gone, the turn runs", "PASS", state)
        team.wait("kaylee", ("idle",))
        plan = getattr(args, "root_plan", None) or choose_root_listener()
        if plan["kind"] is None:
            root_rows_unavailable(report, plan["reason"])
        elif plan["kind"] == "existing":
            try:
                existing_root_rows(report, team, plan, al)
            finally:
                al.restore()
        elif plan["kind"] == "person":
            person_root_rows(report, team)
        else:
            root_port = free_port()
            root = root_listener(root_port)
            if root is None:
                root_rows_unavailable(report, "sudo -n stopped working during the run; " + NO_ROOT)
            else:
                try:
                    time.sleep(2)
                    found = [item for item in lane.read_listeners() or [] if item["port"] == root_port]
                    exe = lane.pid_path(found[0]["pid"]) if found else None
                    if found and exe:
                        verdict, detail = root_listener_proof(found[0]["pid"], root_port)
                        report.add(4, "a root-owned listener is seen", verdict, "%s: %s" % (detail, exe))
                    else:
                        report.add(4, "a root-owned listener is seen", "FAIL",
                                   "netstat didn't show it, or its program couldn't be identified")
                    team.message("kaylee", "Reply with only the word done. Do not run anything.")
                    team.wait("kaylee", ("waiting",), timeout=60)
                    named = any("LANE WAITING" in m and "port %d" % root_port in m and NETCAT in m for m in team.inbox)
                    report.add(4, "it holds the lane, named by its path", "PASS" if named else "FAIL", NETCAT)
                finally:
                    stop_root_listener(root, root_port)
                team.wait("kaylee", ("idle",), timeout=180, patient=True)

        # ---- step 5: two browser workers at once, each running Bricks spec 1 ----
        servers, broker_seen = {"kaylee": set(), "wash": set()}, {"kaylee": set(), "wash": set()}
        for wid, w in (("kaylee", a), ("wash", b)):
            install_probes(w["path"], {"worktree": w["path"], "specs": SMOKE_SPECS[:1]})
            team.message(wid, probe_message(args.python, "spec"))
        both = False
        end = time.time() + 2400
        while time.time() < end:
            states = {wid: v["state"] for wid, v in team.status()["workers"].items()}
            if {"failed", "waiting"} & {states["kaylee"], states["wash"]}:
                raise RuntimeError("step 5 stopped: %s; the lead's messages name: %s"
                                   % (states, ", ".join(reason_codes(team.inbox[-3:])) or "no known reason"))
            polled = {wid: serving_pids(w["lane"]["base"]) for wid, w in (("kaylee", a), ("wash", b))}
            current = {wid: polled[wid][0] for wid in polled}        # the block minus whatever is on base + 31 NOW
            now_brokers = {wid: polled[wid][1] for wid in polled}
            both = both or both_serving(states, current, now_brokers)
            for wid in servers:
                servers[wid].update(current[wid])
                broker_seen[wid].update(now_brokers[wid])
            if states["kaylee"] == states["wash"] == "idle":
                break
            time.sleep(5)
        report.add(5, "both ran at the same time", "PASS" if both else "FAIL",
                   "" if both else "no poll found both running with a listener in each block besides the brokers")
        for wid, w in (("kaylee", a), ("wash", b)):
            report_spec(report, 5, wid, w["path"], SMOKE_SPECS[:1])

        # ---- step 6: the smoke specs, in order ----
        install_probes(a["path"], {"worktree": a["path"], "specs": SMOKE_SPECS})
        team.message("kaylee", probe_message(args.python, "spec"))
        team.wait("kaylee", ("running",), timeout=120)
        while team.status()["workers"]["kaylee"]["state"] == "running":
            now_servers, now_broker = serving_pids(a["lane"]["base"])
            servers["kaylee"].update(now_servers)
            broker_seen["kaylee"].update(now_broker)
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
        kaylee_brokers = broker_ids | broker_seen["kaylee"] | {shell_pid or 0}
        check_cleanup(report, "after worker_done", a, servers["kaylee"] | kaylee_brokers, kaylee_brokers)
        b_broker = broker_seen["wash"] | brokers["wash"] | lsof_pids("-iTCP:%d" % (b["lane"]["base"] + 31), "-sTCP:LISTEN")
        team.call("stop", "worker=wash")
        check_cleanup(report, "after stop_worker", b, servers["wash"] | b_broker, b_broker)
    finally:
        if canary is not None:
            canary.close()
        if settings_file is not None:
            if settings_before is None:
                settings_file.unlink(missing_ok=True)
            else:
                settings_file.write_text(settings_before)
        al.restore()
        shutil.rmtree(decoy, ignore_errors=True)
        if presets_before is None:                       # the presets file goes back before anything can fail below
            presets_file.unlink(missing_ok=True)
        else:
            presets_file.write_text(presets_before)
        try:
            team.call("end", "summary=browser-lane acceptance")
        except Exception as e:
            print("team end: %s: %s" % (type(e).__name__, e))
        delete_branches(bricks, team.id)


def existing_root_rows(report, team, plan, al):
    """Step 4 with a root-owned listener that was already there (launchd's *:22, cupsd's 631): netstat sees it and the
    user's lsof doesn't. To see it NAMED, its program is taken off the approved list for a moment (it must be on it, or
    the lanes would have been waiting all along); `al` (an ApprovedList) puts the list back."""
    pid, port, exe = plan["pid"], plan["port"], plan["exe"]
    if not any(i["pid"] == pid and i["port"] == port for i in lane.read_listeners() or []):
        root_rows_unavailable(report, "the root-owned listener (pid %d, port %d) isn't listening any more" % (pid, port))
        return
    verdict, detail = root_listener_proof(pid, port)
    report.add(4, "a root-owned listener is seen", verdict, "%s: %s" % (detail, exe))
    if al.original is NOT_READ:                          # checked before it is parsed
        report.add(4, "it holds the lane, named by its path", "BROKEN",
                   "%s exists but can't be read, so it can't be changed to see the listener named" % al.path)
        return
    entries = al.entries()
    if exe not in entries:
        report.add(4, "it holds the lane, named by its path", "BROKEN",
                   "%s isn't on the approved list, so it can't be taken off to see it named" % exe)
        return
    al.write(json.dumps([e for e in entries if e != exe]))
    try:
        team.message("kaylee", "Reply with only the word done. Do not run anything.")
        team.wait("kaylee", ("waiting",), timeout=60)
        named = any("LANE WAITING" in m and "port %d" % port in m and exe in m for m in team.inbox)
        report.add(4, "it holds the lane, named by its path", "PASS" if named else "FAIL", exe)
    finally:
        al.restore()
    team.wait("kaylee", ("idle",), timeout=180, patient=True)


def person_root_rows(report, team, read=None, path_of=None, owner=None, clock=None, sleep=None, say=None,
                     pick_port=None, port_free=None, appear_s=900, gone_s=600):
    """Step 4 when no root-owned listener exists and sudo -n fails: a PERSON starts `sudo /usr/bin/nc -lk` on a port
    this run names, in his own Terminal. Runs after the D9/D10/D11 rows, with kaylee idle (an unapproved root nc
    makes every lane turn wait). The script NEVER signals that listener: it asks the person to stop it and waits.
    Raises RuntimeError (after a BROKEN row) when it is still listening 10 minutes after the request, since steps 5-7
    would only wait."""
    read, path_of, owner = read or lane.read_listeners, path_of or lane.pid_path, owner or _owner_uid
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    say = say or (lambda line: print(line, flush=True))
    pick_port, port_free = pick_port or free_port, port_free or lane.port_free
    port = pick_port()
    while not port_free(port):                           # right before printing: still free, outside the lane pool
        port = pick_port()
    say("ANDY ACTION: in your own Terminal run: sudo %s -lk 127.0.0.1 %d" % (NETCAT, port))
    say("(leave it running; this run waits up to 15 minutes)")

    def on_port():
        return [item for item in read() or [] if item["port"] == port]
    found, deadline = None, clock() + appear_s
    while clock() < deadline:
        for item in on_port():
            if path_of(item["pid"]) == NETCAT:
                found = item
        if found:
            break
        sleep(2)
    if not found:
        root_rows_unavailable(report, "no root-owned nc appeared on port %d within 15 minutes" % port)
        return
    pid = found["pid"]
    if owner(pid) != 0:
        root_rows_unavailable(report, "pid %d on port %d is not root-owned: started without sudo" % (pid, port))
    else:
        verdict, detail = root_listener_proof(pid, port)
        report.add(4, "a root-owned listener is seen", verdict, "%s: %s" % (detail, NETCAT))
        try:
            team.message("kaylee", "Reply with only the word done. Do not run anything.")
            team.wait("kaylee", ("waiting",), timeout=60)
            named = any("LANE WAITING" in m and "port %d" % port in m and NETCAT in m for m in team.inbox)
            report.add(4, "it holds the lane, named by its path", "PASS" if named else "FAIL", NETCAT)
        except RuntimeError as e:                        # the person must still be asked to stop it
            report.add(4, "it holds the lane, named by its path", "FAIL", str(e))
    say("ANDY ACTION: stop it now: press Ctrl-C in that Terminal")
    deadline = clock() + gone_s
    while clock() < deadline:
        if not on_port():
            report.add(4, "the root-owned listener is gone", "PASS", "nothing listens on port %d" % port)
            team.wait("kaylee", ("idle",), timeout=180, patient=True)
            return
        sleep(2)
    left = on_port()
    pid = left[0]["pid"] if left else pid
    report.add(4, "the root-owned listener is gone", "BROKEN",
               "pid %d still listens on port %d ten minutes after the request: stop it with `sudo kill %d`" % (pid, port, pid))
    raise RuntimeError("the root-owned nc (pid %d, port %d) is still running: steps 5-7 would only wait. Stop it with "
                       "`sudo kill %d` and run again" % (pid, port, pid))


def advisory_details(report, root):
    """(full path, 'file:line title', first error message) of every failing @lane-advisory spec in a Playwright JSON
    report. A spec's file is relative to the report's test folder (config.rootDir), or to `root` when it has none."""
    found = []
    base = (report.get("config") or {}).get("rootDir") or root

    def walk(suite):
        for spec in suite.get("specs") or []:
            tags = [str(t).lstrip("@") for t in spec.get("tags") or []]
            if "lane-advisory" not in tags and "@lane-advisory" not in spec.get("title", ""):
                continue
            for test in spec.get("tests") or []:
                if test.get("status") in ("expected", "skipped", "flaky"):
                    continue
                message = next((r["error"]["message"] for r in test.get("results") or []
                                if isinstance(r.get("error"), dict) and r["error"].get("message")), "no message")
                found.append((os.path.normpath(os.path.join(base, str(spec.get("file")))),
                              "%s:%s %s" % (spec.get("file"), spec.get("line"), spec.get("title")),
                              " ".join(message.split())[:200]))
        for child in suite.get("suites") or []:
            walk(child)
    for suite in report.get("suites") or []:
        walk(suite)
    return found


def report_spec(report, step, wid, worktree, specs):
    agreed = {os.path.normpath(os.path.join(worktree, spec)) for spec in ADVISORY_SPECS}
    for i, spec in enumerate(specs):
        path = Path(worktree) / PROBE_DIR / ("spec-%d.json" % i)
        try:
            data = json.loads(path.read_text())
            got = summarize(data)
        except (OSError, ValueError) as e:
            report.add(step, "%s %s" % (wid, spec), "FAIL", "no JSON report (%s)" % e.__class__.__name__)
            continue
        ok = got["passed"] > 0 and not got["failed"] and not got["errors"]
        report.add(step, "%s %s" % (wid, spec), "PASS" if ok else "FAIL",
                   "%d passed, %d skipped, failed: %s, errors: %s, flaky: %s"
                   % (got["passed"], got["skipped"], got["failed"] or "none", got["errors"] or "none", got["flaky"] or "none"))
        for full, name, message in advisory_details(data, worktree):
            if full in agreed:
                report.add(step, "%s advisory (reported separately)" % wid, "INFO", "%s: %s" % (name, message))
            else:
                report.add(step, "%s advisory outside the agreed set" % wid, "FAIL",
                           "%s is tagged @lane-advisory but isn't one of the agreed specs: %s" % (name, message))


def check_cleanup(report, when, w, pids, broker_pids):
    """Step 7's rows, each with its evidence. netstat (root's sockets included) lists the lane's ports; lane_pids and
    env_pids are the cleanup's own matchers and must come back empty; "gone" counts only if a pid besides the broker's
    was recorded while the lane ran. A matcher that can't say is BROKEN, never a pass."""
    base, path = w["lane"]["base"], w["lane"]["path"]
    listening = lane.read_listeners()
    if listening is None:
        report.add(7, "%s: nothing listens on the lane's ports" % when, "BROKEN", "netstat failed or printed an unknown format")
    else:
        left = sorted(item["pid"] for item in listening if base <= item["port"] < base + lane.BLOCK)
        report.add(7, "%s: nothing listens on the lane's ports" % when, "FAIL" if left else "PASS", left or "")
    recorded = sorted(p for p in pids if p)
    others = [p for p in recorded if p not in {x for x in broker_pids if x}]
    running = [p for p in recorded if alive(p)]
    if not others:
        report.add(7, "%s: broker and webServer gone" % when, "BROKEN",
                   "no webServer pid was recorded while the lane ran, so 'gone' proves nothing about it")
    else:
        report.add(7, "%s: broker and webServer gone" % when, "FAIL" if running else "PASS", running or recorded)
    left, extra = lane.lane_pids(Path(path), base), lane.env_pids("CLAUDE_CODE_TMPDIR", str(Path(path) / "tmp"))
    if left is None or extra is None:
        report.add(7, "%s: no lane process is left" % when, "BROKEN", "lsof or ps couldn't say (lsof-exit above shows why)")
    else:
        report.add(7, "%s: no lane process is left" % when, "FAIL" if left | extra else "PASS", sorted(left | extra) or "")
    gone = not os.path.lexists(path)
    report.add(7, "%s: lane folder gone" % when, "PASS" if gone else "FAIL", path)


def list_listeners():
    """Every listener, from the listener check's own enumeration (netstat, root's included, and proc_pidpath), the live
    lane blocks, and the lsof cross-check. A broken approved list is shown as broken, and the rows still print."""
    found = lane.read_listeners()
    if found is None:
        sys.exit("netstat failed, or printed a header the listener check doesn't know")
    try:
        approved = lane.load_approved()
    except lane.LaneRefused as e:
        approved = set()
        print("The approved list is broken, so every listener below counts as unapproved: %s\n" % e)
    rows = listener_rows(found, lane.pid_path, approved)
    for pid, address, exe, verdict in rows:
        print("pid %-7d %-26s %s  (%s)" % (pid, address, exe, verdict))
    try:
        lanes = lane.live_lanes()
    except lane.LaneRefused as e:
        lanes = None
        print("\nThe lane registry can't be read: %s" % e)
    for base, key in lanes or []:
        print("\nlive lane block %d-%d (lane %s): listeners there are expected" % (base, base + lane.BLOCK - 1, key))
    seen = lane.lsof_listeners()
    if seen is None:
        print("\nlsof failed, so the listener check would fail closed")
    else:
        for pid, port in sorted(seen - {(item["pid"], item["port"]) for item in found}):
            print("\nlsof shows pid %d listening on port %d, which netstat doesn't list: the check fails until only "
                  "one process holds it" % (pid, port))
    approvable = sorted({exe for _, _, exe, verdict in rows if verdict.startswith(("approved", "approvable"))})
    print("\nThe approvable ones, for %s:\n%s" % (lane.approved_path(), json.dumps(approvable, indent=1)))


def report_skipped(report, self_check_only, failed):
    report.add("-", "steps 2-7", "INFO", "skipped: --self-check-only runs step 1 only" if self_check_only
               else "skipped: step 1 has %d failing row(s)" % failed)


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
    install_signal_handlers()
    report, keeper = Report(), None
    try:
        print("== step 1: the profile, before any worker ==", flush=True)
        step1(args, report)
        if args.self_check_only or report.failed():
            report_skipped(report, args.self_check_only, len(report.failed()))
        else:
            args.root_plan = choose_root_listener()
            plan = args.root_plan
            print("== step 4's root-owned listener: %s ==" % (
                "the existing one on port %d (%s)" % (plan["port"], plan["exe"]) if plan["kind"] == "existing"
                else "a new one through sudo -n" if plan["kind"] == "sudo"
                else "a person starts one (watch for ANDY ACTION lines)"), flush=True)
            if args.root_plan["kind"] == "sudo":
                keeper = SudoKeeper()
                keeper.start()
            steps2to7(args, report)
    except Exception as e:                       # the summary below is always printed
        report.add("-", "the run stopped", "FAIL", "%s: %s" % (type(e).__name__, e))
    finally:
        if keeper is not None:
            keeper.stop()
        failed = report.failed()
        print("\n== %s: %d rows, %d failed ==" % ("PASSED" if not failed else "FAILED", len(report.rows), len(failed)))
        for step, name, verdict, detail in failed:
            print("%-6s step %s  %s  %s" % (verdict, step, name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
