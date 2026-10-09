"""Browser lanes (docs/superpowers/specs/2026-10-08-browser-lane-design.md): a Claude builder runs the app it builds
and tests it in Playwright's headless shell, with no network beyond the lane's own loopback ports.

Chrome never runs inside the worker's sandbox. A broker, started by teamd outside every sandbox under a deny-default
Seatbelt profile that teamd owns, runs `launchServer` on the lane's last port behind a secret path; the worker's
Playwright connects to it through PW_TEST_CONNECT_WS_ENDPOINT. macOS only. Everything here runs in teamd, outside
every sandbox; the parts that only work on macOS (sandbox-exec, `log stream`, proc_pidpath) sit behind seams so the
Pi's tests cover the logic. Folders under /tmp/sy-lane-<uid> can be written by hostile processes (the broker's
renderer, a Codex worker anywhere on the Mac), so teamd never follows a link there and nothing there decides what the
broker is.
"""
import base64
import ctypes
import errno
import fcntl
import hashlib
import http.client
import io
import ipaddress
import json
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath

from . import teamlib, workers

MIN_CLAUDE = (2, 1, 285)
DROP_ENV = ("SSH_AUTH_SOCK", "GPG_AGENT_INFO", "DOCKER_HOST")
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")
LIVE_STATES = ("preparing", "queued", "running", "idle", "waiting")   # teamd.LIVE: a worker in one of these is alive


class LaneRefused(teamlib.RejectedMessage):
    """The lane can't run. teamd fails the worker and tells the lead why; `details` (sandbox denials) stay local."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = list(details or [])


class LaneWait(LaneRefused):
    """The lane can't run yet (the listener check failed): the worker waits and teamd tries again."""


# ---------- who gets a lane (spec: Spawn) ----------

def claude_version():
    """Claude Code's version as a tuple, or None when `claude --version` can't be read."""
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in found.groups()) if found else None


def python_ok():
    """tarfile's data filter (Python 3.11.4 or later): the broker's Playwright is never unpacked without it."""
    return hasattr(tarfile, "data_filter")


def _claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def settings_widenings():
    """What settings outside the lane would merge into its sandbox: allowedDomains and WebFetch(domain:...) allow rules
    widen the lane's network allowlist, and allowMachLookup its Mach services. Claude Code ignores allowMachLookup from
    project and local settings when allowUnsandboxedCommands is false, so the user's and the managed files are the ones
    that matter. A file that exists but can't be read counts as a widening: the check fails closed."""
    found = []
    for path in (_claude_dir() / "settings.json", _claude_dir() / "settings.local.json", MANAGED_SETTINGS):
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            found.append("%s can't be read (%s)" % (path, e.__class__.__name__))
            continue
        if not isinstance(data, dict):
            found.append("%s isn't a JSON object" % path)
            continue
        sandbox = data.get("sandbox") if isinstance(data.get("sandbox"), dict) else {}
        network = sandbox.get("network") if isinstance(sandbox.get("network"), dict) else {}
        permissions = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        if network.get("allowedDomains"):
            found.append("%s adds sandbox.network.allowedDomains" % path)
        if network.get("allowMachLookup"):
            found.append("%s adds sandbox.network.allowMachLookup" % path)
        if any(str(rule).startswith("WebFetch(domain:") for rule in permissions.get("allow") or []):
            found.append("%s allows WebFetch(domain:...)" % path)
    return found


def check_spawn(cfg, kind, mode):
    """Raise RejectedMessage, naming the reason, unless this worker may have a browser lane."""
    if cfg.get("browser_lane") is not True:
        raise teamlib.RejectedMessage("browser lanes are off for this team: a person turns them on with "
                                      "browser_lane in ~/.superyak/team/config.json or a preset")
    if kind != "claude":
        raise teamlib.RejectedMessage("a browser lane is for Claude workers only (kind='claude'): Codex's "
                                      "sandbox can't limit the network to the lane or restrict reads")
    if mode != "build":
        raise teamlib.RejectedMessage("a browser lane is for builders only (mode='build')")
    if sys.platform != "darwin":
        raise teamlib.RejectedMessage("browser lanes run on macOS only: on Linux the worker's network "
                                      "namespace can't reach the lane's browser")
    if not python_ok():
        raise teamlib.RejectedMessage("a browser lane needs teamd on Python 3.11.4 or later (tarfile's data filter); "
                                      "this one runs %s. Run team mode from uv's Python: cd team && uv sync --locked "
                                      "--python 3.13" % platform.python_version())
    version = claude_version()
    if version is None or version < MIN_CLAUDE:
        raise teamlib.RejectedMessage("a browser lane needs Claude Code %s or later (found %s)"
                                      % (".".join(map(str, MIN_CLAUDE)),
                                         ".".join(map(str, version)) if version else "none"))
    widened = settings_widenings()
    if widened:
        raise teamlib.RejectedMessage("a browser lane can't start while settings outside it widen its sandbox: "
                                      + "; ".join(widened))


# ---------- the lane's directory (spec: Lane directory) ----------

TMP_ROOT = Path("/tmp")
SUBDIRS = ("tmp", "npm-cache", "b")


def lane_hash(team_id, worker_id):
    """<h>: the first 10 hex characters of sha256(team_id + '/' + worker_id). Short, so Chrome's and tsx's sockets
    stay under macOS's 104-byte limit for a Unix socket path."""
    return hashlib.sha256(("%s/%s" % (team_id, worker_id)).encode()).hexdigest()[:10]


def _parent_path():
    return TMP_ROOT / ("sy-lane-%d" % os.getuid())


def private_parent():
    """/tmp/sy-lane-<uid>, created 0700. Refused if it is a symlink, belongs to another user, or has any other mode:
    the checks of teamlib.private_sock_dir, except that a wrong mode is refused, never repaired."""
    parent = _parent_path()
    try:
        try:
            os.mkdir(parent, 0o700)
        except FileExistsError:
            pass
        st = os.lstat(parent)                           # a process that can write /tmp may have removed it meanwhile
    except OSError as e:
        raise LaneRefused("unsafe lane folder %s (%s)" % (parent, e.strerror or e))
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise LaneRefused("unsafe lane folder %s (not a directory you own)" % parent)
    if stat.S_IMODE(st.st_mode) != 0o700:
        raise LaneRefused("unsafe lane folder %s (mode %o, not 700)" % (parent, stat.S_IMODE(st.st_mode)))
    return parent


def lane_path(team_id, worker_id):
    """Where this worker's lane lives. Nothing is created or checked."""
    return _parent_path() / lane_hash(team_id, worker_id)


def check_lane(path):
    """lstat, never stat: a lane (or one of its folders) that is a symlink or someone else's is refused."""
    try:
        st = os.lstat(path)
    except OSError as e:
        raise LaneRefused("unsafe lane %s (%s)" % (path, e.strerror or e))
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise LaneRefused("unsafe lane %s (a symlink, not a directory, or not yours)" % path)


def _open_dir(name, dir_fd=None):
    """A folder opened without following a symlink, and checked as this user's."""
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        raise LaneRefused("unsafe lane folder %s (not yours)" % name)
    return fd


def _new_fd(name, mode=0o644, dir_fd=None):
    """A new file for teamd to write where something hostile may have put a name first: unlink the name, then create
    it with O_EXCL|O_NOFOLLOW. Never truncates through an existing name, so a planted symlink or hard link is
    replaced, not followed."""
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass
    return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=dir_fd)


def _write_text(path, text, mode=0o644, dir_fd=None):
    with os.fdopen(_new_fd(str(path), mode, dir_fd), "w") as f:
        f.write(text)


def ensure_lane(team_id, worker_id):
    """The lane at a turn's start: created 0700 the first time, checked every time, with tmp/ (CLAUDE_CODE_TMPDIR),
    npm-cache/ (npm_config_cache), b/ (the broker's folder) and preload.cjs. Everything goes through folder
    descriptors opened without following links, so a lane or folder swapped for a link is refused, never followed.
    The worker may write tmp/ and npm-cache/ only (workers.claude_sandbox_settings)."""
    parent = private_parent()
    h = lane_hash(team_id, worker_id)
    try:
        preload = (teamlib.package_dir() / "lane" / "preload.cjs").read_text()
        pfd = _open_dir(str(parent))
        try:
            try:
                os.mkdir(h, 0o700, dir_fd=pfd)
            except FileExistsError:
                pass
            lfd = _open_dir(h, pfd)
            try:
                for sub in SUBDIRS:
                    try:
                        os.mkdir(sub, 0o700, dir_fd=lfd)
                    except FileExistsError:
                        pass
                    os.close(_open_dir(sub, lfd))
                _write_text("preload.cjs", preload, dir_fd=lfd)
            finally:
                os.close(lfd)
        finally:
            os.close(pfd)
    except OSError as e:
        raise LaneRefused("unsafe lane %s (%s)" % (parent / h, e.strerror or e))
    return parent / h


def lane_text(path):
    """A folder in a lane as the broker's profile names it: the parent resolved (/tmp is /private/tmp on macOS), the
    rest as it is, each part checked right now as a real folder of this user's. A link below the parent refuses it,
    so a profile can never name the target of a link a hostile process planted."""
    path, parent = Path(path), _parent_path()
    try:
        parts = path.relative_to(parent).parts
    except ValueError:
        raise LaneRefused("unsafe lane %s (not under %s)" % (path, parent))
    check_lane(parent)
    current = parent
    for part in parts:
        current = current / part
        check_lane(current)
    return os.path.join(os.path.realpath(parent), *parts)


def remove_lane(path):
    """One fd-based rmtree of the lane root only. Returns False when there was nothing to remove."""
    if not shutil.rmtree.avoids_symlink_attacks:
        raise LaneRefused("this platform can't remove a folder without following symlinks; remove %s by hand" % path)
    if not os.path.lexists(path):
        return False
    path = Path(path)
    if path.parent != _parent_path() or not path.name:
        raise LaneRefused("unsafe lane %s (not directly under %s)" % (path, _parent_path()))
    check_lane(path)
    try:
        pfd = _open_dir(str(path.parent))               # never follows a parent swapped for a link
        try:
            shutil.rmtree(path.name, dir_fd=pfd)
        finally:
            os.close(pfd)
    except FileNotFoundError:
        return False
    except OSError as e:
        raise LaneRefused("the lane %s can't be removed (%s)" % (path, e.strerror or e))
    return True


def leftover_lanes(team_id, workers, live_states):
    """The lanes teamd sweeps when it starts: those of this team's workers that state.json shows as not alive, with
    a folder or a block still there. Matching is by each worker's exact <h>, never by prefix, so another team's lanes
    (and anything else in the parent) are never touched. Returns [(worker id, path)]."""
    out = []
    for wid, w in sorted(workers.items()):
        if w.get("state") in live_states:
            continue
        path = lane_path(team_id, wid)
        if os.path.lexists(path) or block_of(team_id, wid) is not None:
            out.append((wid, path))
    return out


# ---------- port blocks (spec: Ports) ----------

PORT_FIRST, PORT_LAST, BLOCK = 41000, 48999, 32   # below macOS's ephemeral range (49152-65535)


def _registry():
    """The machine-wide record of every lane's block, shared by all teams: {<h>: {base, team, worker}}."""
    return teamlib.team_home() / "lane-ports.json"


@contextmanager
def _registry_lock():
    path = teamlib.team_home() / "lane-ports.lock"
    try:
        cm = teamlib.locked(path)
        cm.__enter__()
    except OSError as e:
        raise LaneRefused("%s is damaged or can't be locked (%s), so no lane can take a block" % (path, e.strerror or e))
    try:
        yield
    finally:
        cm.__exit__(None, None, None)


def _read_registry():
    """The registry, read under _registry_lock. A damaged file refuses lanes rather than forgetting their blocks."""
    path = _registry()
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:                  # a directory, no permission, bytes that aren't UTF-8
        raise LaneRefused("%s is damaged or can't be read (%s), so no lane can take a block; look at it, then remove it"
                          % (path, getattr(e, "strerror", None) or e))
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not all(isinstance(e, dict) and type(e.get("base")) is int
                                             and PORT_FIRST <= e["base"] <= PORT_LAST - BLOCK + 1
                                             and (e["base"] - PORT_FIRST) % BLOCK == 0 for e in data.values()):
        raise LaneRefused("%s is damaged, so no lane can take a block; look at it, then remove it" % path)
    return data


def _write_registry(data):
    """A whole new file, renamed into place: a crash never leaves half a registry."""
    path = _registry()
    tmp = path.with_name(path.name + ".tmp")
    try:
        _write_text(tmp, json.dumps(data, indent=1, sort_keys=True), 0o600)
        os.replace(tmp, path)
    except OSError as e:
        raise LaneRefused("%s can't be written (%s), so no lane can take a block" % (path, e.strerror or e))


def _team_lock(team_id):
    return teamlib.team_home() / "lane-teams" / (team_id + ".lock")


def hold_team(team_id):
    """teamd holds this lock for its whole life: a team's lane blocks count as live only while it is held. Returns
    the open file, which must stay open."""
    path = _team_lock(team_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "a")
    except OSError as e:
        raise LaneRefused("the lock %s can't be opened (%s)" % (path, e.strerror or e))
    for attempt in range(10):                           # about a second: a teamd that is just exiting lets go
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except BlockingIOError:
            time.sleep(0.1)
        except OSError as e:
            f.close()
            raise LaneRefused("the lock %s can't be taken (%s)" % (path, e.strerror or e))
    f.close()
    raise LaneRefused("another teamd already runs team %s" % team_id)


def team_alive(team_id):
    """Whether a teamd holds this team's lock right now. A pid could be reused; a lock dies with its holder."""
    try:
        f = open(_team_lock(team_id))
    except (OSError, ValueError):                       # ValueError: a NUL in the team id
        return False
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
        return False


def port_free(port):
    """Nothing else holds this loopback port right now, on 127.0.0.1 or on ::1 (where the machine has IPv6)."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            s = socket.socket(family)
        except OSError:
            continue                                    # no IPv6 here
        try:
            s.bind((host, port))
        except OSError as e:
            if family == socket.AF_INET6 and e.errno == errno.EADDRNOTAVAIL:
                continue                                # IPv6, but no ::1
            return False
        finally:
            s.close()
    return True


def _worker_live(team_id, worker_id):
    try:
        state = json.loads((teamlib.team_dir(team_id) / "state.json").read_text())
    except (OSError, ValueError):
        return False
    return ((state.get("workers") or {}).get(worker_id) or {}).get("state") in LIVE_STATES


def _reclaimable(entry):
    """A dead teamd's block: its team's lock is free, state.json doesn't show its worker alive, and its ports are
    free (nothing it started still listens there)."""
    team = str(entry.get("team", ""))
    return (not team_alive(team) and not _worker_live(team, str(entry.get("worker", "")))
            and all(port_free(p) for p in range(entry["base"], entry["base"] + BLOCK)))


def allocate_block(team_id, worker_id):
    """The lane's block of BLOCK ports: the one it already holds, else the lowest free block that no lane holds and
    nothing else uses, after reclaiming dead teamds' blocks. With `lane_one_at_a_time` in the person's config.json
    (the fallback when a second lane could read the first one's endpoint), a lane waits while another holds a
    block. The broker listens on the block's last port."""
    h = lane_hash(team_id, worker_id)
    with _registry_lock():
        data = _read_registry()
        if h in data:
            return data[h]["base"]
        stale = [key for key, entry in data.items() if _reclaimable(entry)]
        for key in stale:
            del data[key]
        try:
            one_at_a_time = teamlib.load_config().get("lane_one_at_a_time") is True
        except (OSError, ValueError, AttributeError) as e:
            raise LaneRefused("the config can't be read (%s)" % e)
        if one_at_a_time and data:
            other = min(data.values(), key=lambda e: e["base"])
            if stale:
                _write_registry(data)
            raise LaneWait("one browser lane per machine at a time (lane_one_at_a_time): %s of team %s holds it"
                           % (other.get("worker"), other.get("team")))
        held = {entry["base"] for entry in data.values()}
        for base in range(PORT_FIRST, PORT_LAST - BLOCK + 2, BLOCK):
            if base in held or not all(port_free(p) for p in range(base, base + BLOCK)):
                continue
            data[h] = {"base": base, "team": team_id, "worker": worker_id}
            _write_registry(data)
            return base
        if stale:
            _write_registry(data)
    raise LaneRefused("no free block of %d loopback ports in %d-%d" % (BLOCK, PORT_FIRST, PORT_LAST))


def release_block(team_id, worker_id):
    """Back to the pool. Call only once the lane's process cleanup has finished."""
    try:
        with _registry_lock():
            data = _read_registry()
            if data.pop(lane_hash(team_id, worker_id), None) is not None:
                _write_registry(data)
    except LaneRefused as e:                            # cleanup never raises: the registry needs a person
        print("superyak-team: lane block of %s/%s not released: %s" % (team_id, worker_id, e), file=sys.stderr)


def block_of(team_id, worker_id):
    """The lane's base port, or None (also when the registry is damaged: a lookup never refuses a cleanup)."""
    try:
        with _registry_lock():
            entry = _read_registry().get(lane_hash(team_id, worker_id))
    except LaneRefused:
        return None
    return entry["base"] if entry else None


def live_lanes():
    """(base, lane folder name) of every lane whose teamd is running."""
    with _registry_lock():
        data = _read_registry()
    return sorted((entry["base"], key) for key, entry in data.items() if team_alive(str(entry.get("team", ""))))


def live_blocks():
    """Bases of the blocks whose teamd is running. A dead teamd's block stays held until it is reclaimed, but it no
    longer counts as a lane for the listener check: a listener there fails, which fails closed."""
    return [base for base, _ in live_lanes()]


# ---------- the worker's environment (spec: Worker environment) ----------

def worker_env(path, base, endpoint):
    """What a browser worker's turn adds to its environment. workers.launch also drops DROP_ENV."""
    path = Path(path)
    return {"CLAUDE_CODE_TMPDIR": str(path / "tmp"),
            "npm_config_cache": str(path / "npm-cache"),
            "SUPERYAK_BROWSER_LANE": "1",
            "SUPERYAK_LANE_PORT_BASE": str(base),
            "SUPERYAK_LANE_PORT_COUNT": str(BLOCK),
            "PW_TEST_CONNECT_WS_ENDPOINT": endpoint,
            "NODE_OPTIONS": "--require " + str(path / "preload.cjs"),
            # Bricks' shards run 20-35 minutes: one Bash call may take up to 40, within worker_timeout_s.
            "BASH_DEFAULT_TIMEOUT_MS": "600000",
            "BASH_MAX_TIMEOUT_MS": "2400000"}


# ---------- the listener check, D9, D10 and D11 (spec: The listener check; Approved listeners) ----------

CHECK_EVERY_S = 60
APPROVED_DIRS = ("/System/", "/usr/libexec/", "/usr/sbin/", "/sbin/")
# Under those folders, but not on the sealed system volume: the writable Data volume and the firmlink targets.
NOT_SEALED = ("/System/Volumes/", "/usr/libexec/cups/", "/System/Library/Caches/", "/System/Library/Assets/",
              "/System/Library/AssetsV2/", "/System/Library/PreinstalledAssets/",
              "/System/Library/PreinstalledAssetsV2/", "/System/Library/Speech/")
WILDCARDS = ("*", "0.0.0.0", "::")
INTERPRETER_RE = re.compile(r"(python|perl|ruby|php|node|deno|bun|lua|tclsh|wish|osascript|java|swift"
                            r"|(ba|z|da|k|tc|c|fi)?sh)[0-9.]*")
NETSTAT_HEAD = ["Proto", "Recv-Q", "Send-Q", "Local Address", "Foreign Address", "(state)"]


def approved_path():
    """Only the person edits this file; it is never a team key."""
    return teamlib.team_home() / "lane-listeners.json"


def _device(path):
    return os.lstat(path).st_dev


def _sealed(entry):
    """On a Mac the program must sit on the same volume as /usr/sbin (the sealed system volume). Elsewhere this is
    skipped. Returns "" when fine, else why not: a missing file has its own reason."""
    if sys.platform != "darwin":
        return ""
    try:
        return "" if _device(entry) == _device("/usr/sbin") else "not on the sealed system volume"
    except FileNotFoundError:
        return "does not exist"
    except (OSError, ValueError):
        return "not on the sealed system volume"


def load_approved():
    """D10 and D11: the approved list holds executable paths only, each an Apple program in one of its SIP-protected
    folders (/System, /usr/libexec, /usr/sbin, /sbin) and never an interpreter. It is approved on any port. A list
    with any other entry is refused as a whole, so the check fails closed."""
    path = approved_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as e:
        raise LaneWait("%s can't be read (%s)" % (path, e.__class__.__name__))
    if not isinstance(data, list):
        raise LaneWait("%s must be a list of executable paths" % path)
    out = set()
    for entry in data:
        if not isinstance(entry, str) or os.path.normpath(entry) != entry or not entry.startswith(APPROVED_DIRS):
            raise LaneWait("%s: %r refused: only Apple programs in /System, /usr/libexec, /usr/sbin or /sbin may "
                           "listen while a lane runs" % (path, entry))
        if INTERPRETER_RE.fullmatch(os.path.basename(entry).lower()):
            raise LaneWait("%s: %r refused: an interpreter is never approved" % (path, entry))
        why = ("not on the sealed system volume" if entry.startswith(NOT_SEALED)
               or "/CoreTypes.bundle/Contents/Library/" in entry else _sealed(entry))
        if why:
            raise LaneWait("%s: %r refused: %s%s" % (path, entry, why, ", so a person could change what it runs"
                                                     if why.startswith("not") else ""))
        out.add(entry)
    return out


def _run(cmd, timeout=60):
    """Every command lane.py runs outside the sandbox goes through here (the tests' seam). None when it can't run."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def parse_lsof(text):
    """`lsof -F pn` output (or `-F pcn`): one dict per listening socket, {pid, command, host, port}. IPv6 hosts come
    in brackets ([::1]:41000), a wildcard as *."""
    out, pid, command = [], None, ""
    for line in text.split("\n"):
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            pid, command = int(value), ""
        elif field == "c":
            command = value
        elif field == "n" and pid is not None:
            host, sep, port = value.rpartition(":")
            if not sep or not port.isdigit():
                continue
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            out.append({"pid": pid, "command": command, "host": host, "port": int(port)})
    return out


def _netstat_rows(text):
    """(rows, why): why is "header" or "row" when the text can't be read, so the lead is told which."""
    lines = text.split("\n")
    header = next((line for line in lines if line.startswith("Proto")), None)
    if header is None:
        return None, "header"
    columns = header.replace("Local Address", "Local\0Address").replace("Foreign Address", "Foreign\0Address").split()
    columns = [c.replace("\0", " ") for c in columns]
    if columns[:6] != NETSTAT_HEAD or ("pid" in columns) == ("process:pid" in columns):
        return None, "header"
    named = "process:pid" in columns
    index = columns.index("process:pid" if named else "pid")
    trailing = len(columns) - index - 1                 # the columns after it, counted from the header
    out = []
    for line in lines:
        fields = line.split()
        if len(fields) < 6 or fields[5] != "LISTEN" or not fields[0].startswith("tcp"):
            continue
        if fields[0] not in ("tcp4", "tcp6", "tcp46") or len(fields) < index + 1 + trailing:
            return None, "row"
        host, sep, port = fields[3].rpartition(".")
        if named:                                       # a process name may hold spaces: "Google Chrome He:4321"
            found = re.fullmatch(r"(.*):([0-9]+)", " ".join(fields[index:len(fields) - trailing]))
            command, pid = (found.group(1), found.group(2)) if found else ("", "")
        else:
            command, pid = "", fields[index]
        if not sep or not host or not port.isdigit() or not pid.isdigit():
            return None, "row"
        out.append({"pid": int(pid), "command": command, "host": host, "port": int(port)})
    return out, ""


def parse_netstat(text):
    """`netstat -anv -p tcp` (macOS): every listening TCP socket, whoever owns it, as {pid, command, host, port}.
    Addresses end in .<port> (127.0.0.1.631, *.5000, ::1.631, fe80::1%lo0.631). The pid column is found from the
    header: older macOS calls it `pid`, newer `process:pid` (values like rapportd:571). A header it doesn't
    recognise, or a listening line it can't read (an unknown tcp* proto too), gives None, so the check fails closed."""
    return _netstat_rows(text)[0]


def is_loopback(host):
    """127.0.0.0/8 and ::1 only. A wildcard, ::, a link-local, LAN or tailnet address is not loopback, and neither is
    an IPv4-mapped one."""
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if address.version == 4:
        return address in ipaddress.ip_network("127.0.0.0/8")
    return address == ipaddress.ip_address("::1")


def reachable(host):
    """Whether a lane could reach a socket bound to this address: loopback (an IPv4-mapped one too), a wildcard, or
    anything scoped to lo0. An address it can't read counts, so the check fails closed."""
    if host in WILDCARDS or is_loopback(host) or host.endswith("%lo0"):
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return True
    if address.is_unspecified:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped is not None and (mapped.is_loopback or mapped.is_unspecified)


def _read_netstat():
    """(rows, why): see _netstat_rows; why is "run" when netstat itself failed."""
    netstat = shutil.which("netstat", path=SYSTEM_PATH)
    if not netstat:
        return None, "run"
    r = _run([netstat, "-anv", "-p", "tcp"])
    if r is None or r.returncode != 0:
        return None, "run"
    return _netstat_rows(r.stdout)


def read_listeners():
    """Every listening TCP socket on the machine, root's included (netstat sees them; lsof run as the user doesn't),
    or None when netstat fails or prints something this check doesn't know."""
    return _read_netstat()[0]


def lsof_listeners():
    """The cross-check: the user's own listening sockets as lsof sees them, as (pid, port) pairs, or None when lsof
    fails (it exits 1, saying nothing, when it finds none)."""
    lsof = shutil.which("lsof", path=SYSTEM_PATH)
    if not lsof:
        return None
    r = _run([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pn"])
    if r is None or r.returncode not in (0, 1) or (r.returncode == 1 and (r.stdout.strip() or r.stderr.strip())):
        return None
    return {(item["pid"], item["port"]) for item in parse_lsof(r.stdout)}


def pid_path(pid):
    """A process's full executable path from proc_pidpath() (macOS), or None. Never `ps -o comm=`, which can give a
    short name for root's processes (D11)."""
    if sys.platform != "darwin":
        return None
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    except OSError:
        return None
    buf = ctypes.create_string_buffer(4096)                  # PROC_PIDPATHINFO_MAXSIZE
    n = libc.proc_pidpath(ctypes.c_int(int(pid)), buf, ctypes.c_uint32(len(buf)))
    return buf.value.decode("utf-8", "replace") if n > 0 else None


def listeners_ok():
    """D9, with D11 and the reachability ruling. Every listening socket a lane can reach, on loopback or a wildcard,
    must be in a live lane's block on loopback, or belong to an approved Apple program, by its full path, on any port.
    A socket bound only to another specific address (the tailnet, say) is unreachable and doesn't count; a lane's
    own port beyond loopback always fails. Any doubt fails too: netstat or lsof failing, a socket lsof sees that
    netstat doesn't (in two rounds running), a process that can't be identified, an unreadable list or registry.
    Returns (ok, problems).
    The check is machine-wide, so it takes no team."""
    try:
        return _check(load_approved(), live_lanes())
    except LaneRefused as e:
        return False, [str(e)]
    except ValueError as e:                             # anything unreadable fails closed, never raises
        return False, ["the listener check could not read what it was given (%s), so it fails closed"
                       % e.__class__.__name__]


def _lane_process(pid, tmps):
    """Whether this pid's environment holds exactly CLAUDE_CODE_TMPDIR=<a live lane's tmp folder>."""
    env = _environ(pid) or []
    return any("CLAUDE_CODE_TMPDIR=" + tmp in env for tmp in tmps)


def _check(approved, lanes):
    blocks = [base for base, _ in lanes]
    tmps = [str(_parent_path() / key / "tmp") for _, key in lanes]
    missing, listeners = None, None
    for attempt in range(2):                            # a socket that opened or closed between the two reads
        listeners, why = _read_netstat()                # is gone from the second round
        if listeners is None:
            if why == "row":
                return False, ["netstat failed: it printed a listening row this check can't read, so the listener "
                               "check fails closed"]
            return False, ["netstat failed, or printed a header this check doesn't know, so the listener check "
                           "fails closed"]
        seen = lsof_listeners()
        if seen is None:
            return False, ["lsof failed, so the listener check fails closed"]
        lacking = seen - {(item["pid"], item["port"]) for item in listeners}
        missing = lacking if missing is None else missing & lacking
        if not missing:
            break
    problems = ["lsof shows pid %d listening on port %d, which netstat doesn't list (a socket several processes "
                "share, such as a pre-fork server or inherited descriptors, fails until only one holds it)" % pair
                for pair in sorted(missing)]
    paths, lane_pids = {}, {}
    for item in listeners:
        port, host, pid = item["port"], item["host"], item["pid"]
        in_lane = any(base <= port < base + BLOCK for base in blocks)
        is_lane = False
        if not in_lane and not is_loopback(host):       # a lane's process exposes the app to the network, however
            if pid not in lane_pids:                    # it is reached: checked before the reachability skip
                lane_pids[pid] = _lane_process(pid, tmps)
            is_lane = lane_pids[pid]
        if not in_lane and not is_lane and not reachable(host):
            continue                                    # bound to one other address: no lane can reach it
        if pid not in paths:
            paths[pid] = pid_path(pid)
        exe = paths[pid]
        name = "%s (pid %d)" % (item["command"] or (os.path.basename(exe) if exe else "?"), pid)
        launchd = ", launchd holds it for a socket-activated job" if pid == 1 else ""
        if exe is None:
            problems.append("%s listens on %s port %d, and its program can't be identified%s"
                            % (name, host, port, launchd))
            continue
        if is_lane:
            problems.append("%s, a lane's process, listens on %s port %d, beyond loopback (%s)"
                            % (name, host, port, exe))
            continue
        if in_lane:
            if not is_loopback(host):
                problems.append("%s listens on %s port %d, beyond loopback, in a lane's block (%s)"
                                % (name, host, port, exe))
        elif exe not in approved:
            problems.append("%s listens on port %d (%s)%s" % (name, port, exe, launchd))
    return not problems, sorted(set(problems))


def _parse_procargs2(raw):
    """KERN_PROCARGS2's buffer: argc, the executable's path, padding, argc arguments, then the environment."""
    if len(raw) < 4:
        return []
    argc = int.from_bytes(raw[:4], sys.byteorder)
    parts = raw[4:].split(b"\0")
    i = 1
    while i < len(parts) and parts[i] == b"":
        i += 1
    env = []
    for part in parts[i + argc:]:
        if not part:
            break
        env.append(part.decode("utf-8", "replace"))
    return env


def _environ(pid):
    """A process's environment as NAME=value strings, or None: KERN_PROCARGS2 on macOS, /proc on Linux."""
    if sys.platform != "darwin":
        try:
            data = Path("/proc/%d/environ" % pid).read_bytes()
        except OSError:
            return None
        return [s.decode("utf-8", "replace") for s in data.split(b"\0") if s]
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    except OSError:
        return None
    mib = (ctypes.c_int * 3)(1, 49, int(pid))           # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(1 << 20)
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
        return None
    return _parse_procargs2(ctypes.string_at(buf, size.value))


# ---------- the broker's code and browser (spec: The broker; Decisions: the lane's browser, the broker's code) ----------

REGISTRY = "https://registry.npmjs.org/"
SHELL = "chromium-headless-shell"
MANIFESTS = teamlib.package_dir() / "lane" / "browsers.json"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
STAMP = ".superyak-integrity"
STAMP_MANIFEST = ".superyak-manifest"          # the manifest hash of the unpacked package, written beside the stamp
DEPENDENCIES_MARKER = "DEPENDENCIES_VALIDATED"
UNSAFE_ROOTS = ("/private/tmp", "/tmp", "/private/var/folders")    # shared temp folders: the broker never lives there


def broker_root():
    """~/.superyak/team/broker: teamd's own copies of Playwright and its browser, outside every worktree."""
    root = teamlib.team_home() / "broker"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise LaneRefused("%s can't be made (%s)" % (root, e.strerror or e))
    _plain_folder(root)                                   # before the chmod, which would follow a link
    real = os.path.realpath(root)
    for unsafe in UNSAFE_ROOTS:
        if real == unsafe or real.startswith(unsafe + os.sep):
            raise LaneRefused("%s lies under the shared temp folder %s" % (root, unsafe))
    os.chmod(root, 0o700)
    return root


def browsers_root():
    """PLAYWRIGHT_BROWSERS_PATH for the installer and the broker: never the user's own browsers folder."""
    root = broker_root() / "browsers"
    root.mkdir(exist_ok=True)
    os.chmod(root, 0o700)
    return root


def install_lock_path():
    return broker_root() / ".install.lock"


_INSTALL_MUTEX = threading.RLock()
_install_depth = 0


@contextmanager
def install_lock():
    """One teamd installs at a time (Task 7 and Task 10 take this too). The installers take it themselves, and it
    nests: a caller that already holds it (prepare_broker) can call them without waiting on itself."""
    global _install_depth
    with _INSTALL_MUTEX:
        if _install_depth:
            yield
            return
        stack = ExitStack()
        try:
            stack.enter_context(teamlib.locked(install_lock_path()))
        except OSError as e:                              # only taking the lock; the caller's own errors pass through
            raise LaneRefused("the install lock can't be taken (%s)" % (e.strerror or e))
        with stack:
            _install_depth = 1
            try:
                yield
            finally:
                _install_depth = 0


def lock_entry(repo, base):
    """playwright-core's version and integrity from the lockfile at the worker's base commit (the lead's, fixed at
    spawn), never from the worktree, which the worker can write. base must be a full SHA, and replace refs are off."""
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise LaneRefused("the base commit %r isn't a 40-character hex SHA" % (base,))
    try:
        r = workers.git(repo, *workers.HARDENED_GIT, "--no-replace-objects", "cat-file", "blob",
                        "%s:package-lock.json" % base, check=False)
    except (OSError, ValueError):                     # git missing, or a lockfile that isn't UTF-8
        raise LaneRefused("the base commit's package-lock.json can't be read")
    if r.returncode != 0:
        raise LaneRefused("the base commit %s has no package-lock.json, so the broker's Playwright can't be pinned"
                          % base[:12])
    try:
        packages = json.loads(r.stdout).get("packages") or {}
    except (ValueError, AttributeError):
        raise LaneRefused("the base commit's package-lock.json can't be read")
    entry = packages.get("node_modules/playwright-core") if isinstance(packages, dict) else None
    if not isinstance(entry, dict):
        raise LaneRefused("the base commit's package-lock.json has no node_modules/playwright-core entry")
    version, integrity = entry.get("version"), entry.get("integrity")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise LaneRefused("playwright-core's version %r in the base commit's lockfile isn't x.y.z" % (version,))
    if not isinstance(integrity, str) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", integrity):
        raise LaneRefused("playwright-core %s has no sha512 integrity in the base commit's lockfile" % version)
    return version, integrity


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise LaneRefused("%s redirects to %s, which isn't https" % (req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_get(url, limit=64 * 2 ** 20, deadline=300):
    """teamd's own download, with no proxy, https all the way, within `deadline` seconds in all: the integrity check,
    not the transport, is what the pin rests on. Anything that goes wrong is a LaneRefused."""
    if not url.lower().startswith("https://"):
        raise LaneRefused("%s isn't https" % url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _HttpsOnly)
    start, chunks, size = time.monotonic(), [], 0
    try:
        with opener.open(url, timeout=max(0.1, min(60, deadline))) as response:
            if not str(response.geturl()).lower().startswith("https://"):
                raise LaneRefused("%s ended on %s, which isn't https" % (url, response.geturl()))
            while True:
                if time.monotonic() - start > deadline:
                    raise LaneRefused("downloading %s took longer than %d seconds" % (url, deadline))
                chunk = response.read1(1 << 16)          # what has arrived, never waiting for a full block
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise LaneRefused("%s is larger than %d bytes" % (url, limit))
                chunks.append(chunk)
    except LaneRefused:
        raise
    except (OSError, http.client.HTTPException, ValueError) as e:
        raise LaneRefused("%s can't be downloaded (%s)" % (url, e))
    return b"".join(chunks)


def _extract(tar, members, where):
    """tarfile's data filter, or no unpacking at all."""
    if not python_ok():
        raise LaneRefused("teamd's Python has no tarfile data filter (it needs 3.11.4 or later), so the "
                          "broker's Playwright can't be unpacked safely")
    tar.extractall(where, members=members, filter="data")


def extract_package(data, dest, stamp):
    """Unpack an npm tarball's package/ folder into dest: every member checked first, then tarfile's data filter, into
    a temporary folder. The stamp (the integrity hash the bytes matched) goes inside before the folder is renamed into
    place, so the folder is either complete and stamped or not there at all."""
    dest = Path(dest)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except (tarfile.TarError, OSError) as e:
        raise LaneRefused("playwright-core's tarball can't be opened (%s)" % e)
    with tar:
        members = tar.getmembers()
        for m in members:
            parts = PurePosixPath(m.name).parts
            if (m.name.startswith("/") or not parts or parts[0] != "package" or ".." in parts
                    or not (m.isfile() or m.isdir())):
                raise LaneRefused("playwright-core's tarball has a member outside its package folder: %r" % m.name)
        tmp = Path(tempfile.mkdtemp(prefix=".unpack-", dir=dest.parent))
        try:
            _extract(tar, members, tmp)
            for top, dirs, _files in os.walk(tmp / "package", followlinks=False):
                os.chmod(top, 0o755)                     # folders tarfile made implicitly: not whatever the umask made
            recorded = manifest_hash(tmp / "package", ignore=(STAMP, STAMP_MANIFEST))
            _write_text(tmp / "package" / STAMP_MANIFEST, recorded + "\n", 0o600)
            _write_text(tmp / "package" / STAMP, stamp + "\n", 0o600)
            os.rename(tmp / "package", dest)
        except OSError as e:
            raise LaneRefused("playwright-core can't be unpacked into %s (%s)" % (dest, e.strerror or e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _read_plain(path):
    """A regular file's text, read without following a link."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise LaneRefused("%s isn't a plain file; remove its folder and the next lane fetches it again" % path)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise LaneRefused("%s isn't a plain file; remove its folder and the next lane fetches it again" % path)
        try:
            return f.read(4096).decode()
        except (OSError, ValueError):
            raise LaneRefused("%s can't be read" % path)


def _sweep_unpacks(root):
    for old in Path(root).glob(".unpack-*"):
        if old.is_symlink() or not old.is_dir():
            try:
                old.unlink()
            except OSError:
                pass
        else:
            shutil.rmtree(old, ignore_errors=True)


def pinned_playwright(repo, base, fetch=None):
    """~/.superyak/team/broker/playwright-core-<version>/, fetched from the npm registry the first time. The tarball is
    checked against the integrity hash in the base commit's lockfile, never the registry's own claim. A mismatch
    anywhere refuses the lane. Its cli.js runs unsandboxed as the installer, so a reused folder is checked again: owner
    and mode (it and every folder above), the stamp, and the manifest hash recorded at unpack time."""
    version, integrity = lock_entry(repo, base)
    with install_lock():
        dest = broker_root() / ("playwright-core-" + version)
        if os.path.lexists(dest):
            _plain_folder(dest)
            _check_owner(dest, os.lstat(dest))
            _check_ancestors(dest)
            stamp, recorded = dest / STAMP, dest / STAMP_MANIFEST
            if not os.path.lexists(stamp) or not os.path.lexists(recorded):
                raise LaneRefused("%s isn't stamped with the integrity hash the base commit names; remove it and the "
                                  "next lane fetches it again" % dest)
            stamped, was = _read_plain(stamp).strip(), _read_plain(recorded).strip()
            if stamped != integrity:
                raise LaneRefused("%s isn't stamped with the integrity hash the base commit names; remove it and the "
                                  "next lane fetches it again" % dest)
            if manifest_hash(dest, ignore=(STAMP, STAMP_MANIFEST)) != was:
                raise LaneRefused("%s has changed since it was installed; remove it and the next lane fetches it "
                                  "again" % dest)
            return dest
        fetch = fetch or https_get
        tarball = REGISTRY + "playwright-core/-/playwright-core-%s.tgz" % version
        try:
            meta = json.loads(fetch(REGISTRY + "playwright-core/" + version))
        except LaneRefused:
            raise
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise LaneRefused("the npm registry's metadata for playwright-core %s can't be read (%s)" % (version, e))
        dist = meta.get("dist") if isinstance(meta, dict) and isinstance(meta.get("dist"), dict) else {}
        if dist.get("tarball") != tarball:               # the URL is ours; the registry may only agree with it
            raise LaneRefused("playwright-core %s's tarball isn't on %s" % (version, tarball))
        try:
            data = fetch(tarball)
        except LaneRefused:
            raise
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise LaneRefused("playwright-core %s's tarball can't be downloaded (%s)" % (version, e))
        if "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode() != integrity:
            raise LaneRefused("playwright-core %s's tarball doesn't match the integrity hash in the base commit's "
                              "lockfile" % version)
        _sweep_unpacks(dest.parent)
        extract_package(data, dest, integrity)
        return dest


def shell_revision(pw_dir):
    """The headless shell's revision, as the pinned Playwright names it in its browsers.json."""
    try:
        data = json.loads((Path(pw_dir) / "browsers.json").read_text())
    except (OSError, ValueError):
        data = {}
    browsers = data.get("browsers") if isinstance(data, dict) else None
    for browser in browsers if isinstance(browsers, list) else []:
        if isinstance(browser, dict) and browser.get("name") == SHELL:
            revision = browser.get("revision")
            if isinstance(revision, str) and re.fullmatch(r"[0-9]+", revision):
                return revision
    raise LaneRefused("the Playwright at %s names no %s revision" % (pw_dir, SHELL))


def install_headless_shell(node_bin, pw_dir):
    """The headless shell at the pinned Playwright's revision, installed by that Playwright's own installer, outside
    every sandbox, with an environment built from nothing (no download host, proxy or TLS override can reach it).
    The installer only downloads; only sandboxed brokers ever launch from this folder. Returns (folder, revision).
    The manifest is checked separately (check_manifest)."""
    with install_lock():
        revision = shell_revision(pw_dir)
        folder = browsers_root() / ("chromium_headless_shell-" + revision)
        if not (folder / "INSTALLATION_COMPLETE").is_file():
            env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "PLAYWRIGHT_BROWSERS_PATH": str(browsers_root()),
                   "PLAYWRIGHT_SKIP_BROWSER_GC": "1"}
            r = _run_env([str(node_bin), str(Path(pw_dir) / "cli.js"), "install", SHELL], env, cwd=browsers_root())
            if r is None or r.returncode != 0 or not (folder / "INSTALLATION_COMPLETE").is_file():
                tail = teamlib.redact(((r.stdout + r.stderr) if r is not None else "")[-600:])
                raise LaneRefused("installing %s %s failed (exit %s): %s"
                                  % (SHELL, revision, r.returncode if r is not None else "none", tail))
        return folder, revision


def _run_env(cmd, env, cwd, timeout=900):
    """The installer's run: a fixed umask, so the modes in the manifest don't depend on teamd's."""
    try:
        return subprocess.run(cmd, env=env, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              umask=0o022)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_owner(path, st, sticky_ok=False):
    """Owned by this user (or root) and writable by nobody else. A sticky folder (like /tmp) may be writable by all,
    since nobody else can rename or remove what this user owns in it; that is allowed only for folders above."""
    if st.st_uid not in (os.getuid(), 0):
        raise LaneRefused("%s belongs to another user" % path)
    if stat.S_ISLNK(st.st_mode) or not st.st_mode & 0o022:
        return
    if not (sticky_ok and stat.S_ISDIR(st.st_mode) and st.st_mode & stat.S_ISVTX):
        raise LaneRefused("%s is writable by someone other than its owner" % path)


def _check_ancestors(path):
    try:
        for parent in Path(os.path.realpath(path)).parents:
            _check_owner(parent, os.stat(parent), sticky_ok=True)
    except OSError as e:
        raise LaneRefused("%s can't be checked (%s)" % (path, e.strerror or e))


def _plain_folder(path):
    """A real folder, not a link to one: _check_owner lets links through, and a link hashes its target."""
    try:
        ok = stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError as e:
        raise LaneRefused("%s can't be checked (%s)" % (path, e.strerror or e))
    if not ok:
        raise LaneRefused("%s isn't a plain folder" % path)


def manifest_hash(folder, ignore=()):
    """sha256 over every entry under folder, sorted: its path, kind, mode, and its symlink target or its content's
    sha256 (all as bytes, so a name that isn't UTF-8 hashes too). The folder must be a real one, and every entry owned
    by this user and writable by nobody else, and a symlink must stay inside the folder (relative, never escaping).
    An empty DEPENDENCIES_VALIDATED at the top, the marker Playwright writes when an unsandboxed process launches the
    browser, carries no code and is left out (the broker can't write it); so are the top-level names in `ignore`.
    Anything unreadable refuses."""
    folder = Path(folder)
    _plain_folder(folder)
    _check_owner(folder, os.lstat(folder))
    root = os.path.realpath(folder)
    digest = hashlib.sha256()

    def fail(e):
        raise e
    try:
        for top, dirs, files in os.walk(folder, followlinks=False, onerror=fail):
            dirs.sort()
            for name in sorted(dirs + files):
                full = Path(top) / name
                st = os.lstat(full)
                _check_owner(full, st)
                rel = full.relative_to(folder).as_posix()
                if rel in ignore:
                    continue
                if rel == DEPENDENCIES_MARKER and stat.S_ISREG(st.st_mode) and st.st_size == 0:
                    continue
                if stat.S_ISLNK(st.st_mode):
                    target = os.readlink(full)
                    resolved = os.path.realpath(full)       # through every link in a chain, not just this one
                    if os.path.isabs(target) or not (resolved == root or resolved.startswith(root + os.sep)):
                        raise LaneRefused("%s links outside the browser's folder (to %s)" % (full, target))
                    kind, extra = "l", os.fsencode(target)
                elif stat.S_ISDIR(st.st_mode):
                    kind, extra = "d", b""
                elif stat.S_ISREG(st.st_mode):
                    kind, extra = "f", _file_sha256(full).encode()
                else:
                    raise LaneRefused("%s is neither a file, a folder nor a symlink" % full)
                digest.update(os.fsencode(rel) + b"\0" + kind.encode() + b"\0" + b"%o" % stat.S_IMODE(st.st_mode)
                              + b"\0" + extra + b"\n")
    except OSError as e:
        raise LaneRefused("%s can't be read (%s)" % (folder, e.strerror or e))
    return digest.hexdigest()


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def platform_key():
    return "%s-%s" % (sys.platform, platform.machine())


def recorded_manifest(revision):
    try:
        data = json.loads(MANIFESTS.read_text())
        if not isinstance(data, dict):
            raise ValueError("not an object")
        shell = data.get(SHELL)
        if shell is None:
            return None
        revisions = shell.get(revision) if isinstance(shell, dict) else ValueError("not an object")
        if isinstance(revisions, ValueError):
            raise revisions
        if revisions is None:
            return None
        if not isinstance(revisions, dict):
            raise ValueError("not an object")
        value = revisions.get(platform_key())
        if value is not None and not isinstance(value, str):
            raise ValueError("not a string")
        return value
    except (OSError, ValueError) as e:
        raise LaneRefused("%s can't be read (%s)" % (MANIFESTS, e))


def check_manifest(folder, revision):
    """The installed browser must match the hash the repo records for its revision and platform, and its folder and
    every folder above it must be safe as lane_node's are. Run after every install and at every broker start.
    Returns the hash."""
    root = browsers_root()
    _plain_folder(root)
    _check_owner(root, os.lstat(root))
    _plain_folder(folder)
    if Path(os.path.realpath(folder)).parent != Path(os.path.realpath(root)):
        raise LaneRefused("%s isn't directly in %s" % (folder, root))
    _check_ancestors(folder)                          # the folder's real path: root and everything above it
    actual = manifest_hash(folder)
    recorded = recorded_manifest(revision)
    if recorded is None:
        raise LaneRefused("no manifest hash is recorded for %s %s on %s. Once lane_acceptance.py --self-check-only "
                          "passes, Andy records this one in team/superyak_team/lane/browsers.json: %s"
                          % (SHELL, revision, platform_key(), actual))
    if recorded != actual:
        raise LaneRefused("%s doesn't match the manifest hash recorded for %s %s on %s (recorded %s, found %s). "
                          "If nobody changed it, remove that folder and the next lane installs it again"
                          % (folder, SHELL, revision, platform_key(), recorded, actual))
    return actual


def check_lane_node(value, worktrees):
    """The broker's node: an absolute path in the person's config.json (`lane_node`), never `which node`. Refused
    under a worktree, under $HOME (the broker's profile reads nothing there but the pinned Playwright and browsers),
    or writable by anyone but its owner, itself or any folder above it. Returns the resolved binary."""
    if not isinstance(value, str) or not os.path.isabs(value):
        raise LaneRefused("set lane_node in ~/.superyak/team/config.json to the absolute path of the node binary the "
                          "lane's broker runs (for example /opt/homebrew/bin/node)")
    real = Path(os.path.realpath(value))
    if not real.is_file() or not os.access(real, os.X_OK):
        raise LaneRefused("lane_node %s isn't an executable file" % value)
    home = Path(os.path.realpath(Path.home()))
    if real == home or home in real.parents:
        raise LaneRefused("lane_node %s lies under your home folder, which the broker's profile never reads" % real)
    for tree in worktrees:
        tree = Path(os.path.realpath(tree))
        if real == tree or tree in real.parents:
            raise LaneRefused("lane_node %s lies under the worktree %s" % (real, tree))
    _check_owner(real, os.stat(real))
    _check_ancestors(real)
    return real


# ---------- the broker's profile (spec: Its profile) ----------

TEMPLATE = teamlib.package_dir() / "lane" / "broker.sb.tmpl"


def sb_quote(path):
    """A path as a profile string: resolved (Seatbelt matches real paths), and refused if a profile can't quote it."""
    try:
        return _sb_literal(os.path.realpath(str(path)))
    except ValueError:
        raise LaneRefused("refusing a path a sandbox profile can't quote: %r" % str(path))


def _sb_literal(path):
    """A path as given (not resolved), refused if a profile can't quote it."""
    path = str(path)
    if re.search(r'["\\{}\x00-\x1f\x7f]', path):
        raise LaneRefused("refusing a path a sandbox profile can't quote: %r" % path)
    return path


# A node prefix may not be, hold or lie under $HOME or any of these ("/" and /private hold them; /System/Volumes/Data is
# the Data volume the same /Users and /private/tmp live on).
SHARED_ROOTS = ("/Users", "/Volumes", "/private/tmp", "/private/var/folders", "/System/Volumes")


def node_prefix(node_bin):
    """node's own folder (the resolved binary's grandparent), which the broker reads whole. Refused when it equals,
    holds or lies under $HOME or any of SHARED_ROOTS (/Users, /Volumes, /private/tmp, /private/var/folders,
    /System/Volumes); so /, /private and /private/var go too, since they hold those. The profile would read far more
    than node."""
    try:
        prefix = Path(os.path.realpath(node_bin)).parents[1]
    except (ValueError, IndexError):
        raise LaneRefused("lane_node %r has no folder the broker could read" % str(node_bin))
    roots = [Path(os.path.realpath(Path.home()))] + [Path(r) for r in SHARED_ROOTS]
    if any(prefix == root or root in prefix.parents or prefix in root.parents for root in roots):
        raise LaneRefused("lane_node's folder %s is too wide for the broker to read; install node somewhere like "
                          "/opt/homebrew" % prefix)
    return prefix


def render_profile(b_text, pw_dir, browsers_dir, shell_dir, node_bin, base):
    """The broker's profile for one lane, from the checked-in template. Only these are filled in: b/ (read and write;
    `b_text` comes from lane_text, never resolved here), the pinned Playwright and browsers folders (read), node's
    prefix (read), node itself and the headless shell's folder (exec), metadata literals of exactly their ancestors,
    one rule per lane port apart from the broker's, and the broker's port for bind and inbound only."""
    node_bin = Path(node_bin)
    prefix = node_prefix(node_bin)
    paths = [Path(pw_dir), Path(browsers_dir), Path(shell_dir), prefix, node_bin]
    try:
        ancestors = {str(parent) for p in paths for q in (p, Path(os.path.realpath(p))) for parent in q.parents}
    except ValueError:
        raise LaneRefused("refusing a path a sandbox profile can't quote")
    ancestors = sorted(ancestors | {str(parent) for parent in Path(b_text).parents})   # b_text as given
    values = {
        "B_DIR": _sb_literal(b_text), "PLAYWRIGHT_DIR": sb_quote(pw_dir), "BROWSERS_DIR": sb_quote(browsers_dir),
        "NODE_PREFIX": sb_quote(prefix), "NODE_BIN": sb_quote(node_bin), "SHELL_DIR": sb_quote(shell_dir),
        "ANCESTORS": " ".join('(literal "%s")' % _sb_literal(a) for a in ancestors),
        "LANE_PORTS": " ".join('(remote ip "localhost:%d")' % port for port in range(base, base + BLOCK - 1)),
        "BROKER_PORT": str(base + BLOCK - 1),
    }
    def fill(match):                                  # one pass: a value is never scanned for placeholders again
        if match.group(1) not in values:
            raise LaneRefused("the broker's profile template has a value lane.render_profile doesn't fill in")
        return values[match.group(1)]
    text = re.sub(r"\{\{([A-Z_]+)\}\}", fill, TEMPLATE.read_text())
    if "{{" in text or "}}" in text:
        raise LaneRefused("the broker's profile template has a value lane.render_profile doesn't fill in")
    return text


# Spike 5's fifteen probes plus `open -a Calculator`, which spike 5 never ran. osascript, launchctl and security run
# with arguments that succeed outside any sandbox, so a refusal can only be the profile's. The positive controls
# include exec_node: if fork were denied, every exec_* probe would "pass" for the wrong reason.
SELF_CHECK_PROBES = ("exec_osascript", "exec_launchctl", "exec_security", "exec_pbpaste", "exec_open_calculator",
                     "exec_curl", "net_domain", "net_ip", "net_canary", "read_dotfile", "link_dotfile",
                     "read_claude_tmp",
                     "read_user_temp", "write_home", "write_launchagents", "open_rc_for_write", "write_users_shared")
SELF_CHECK_POSITIVE = ("lane_port", "write_own_folder", "exec_node")


PRIVATE_TMP = Path("/private/tmp")
USERS_SHARED = Path("/Users/Shared")
CALCULATOR_APP = Path("/System/Applications/Calculator.app")
PROBE_PROGRAMS = {"exec_osascript": "/usr/bin/osascript", "exec_launchctl": "/bin/launchctl",
                  "exec_security": "/usr/bin/security", "exec_pbpaste": "/usr/bin/pbpaste",
                  "exec_open_calculator": "/usr/bin/open", "exec_curl": "/usr/bin/curl"}
NETWORK_PROBES = ("exec_curl", "net_domain", "net_ip")      # refused for the wrong reason if the network is down here


def network_up():
    """Outside the sandbox: can this machine resolve a name and reach an address? (The seam for the network probes.)"""
    try:
        socket.getaddrinfo("example.com", 443)
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return True
    except OSError:
        return False


def _probe_leftovers():
    """{probe: what it would create if it got through}."""
    return {"write_home": Path.home() / "superyak-lane-probe.txt",
            "write_launchagents": Path.home() / "Library/LaunchAgents/superyak-lane-probe.plist",
            "write_users_shared": USERS_SHARED / "superyak-lane-probe"}


def probe_targets(user_temp, lane_dir=None):
    """What each probe acts on, checked outside the sandbox: a probe whose target doesn't exist, or exists but can't
    be used (an unreadable rc file, an unwritable folder), would be "refused" for the wrong reason, so its row is
    BROKEN. link_dotfile also needs a regular file (not a link) on the lane's device (`lane_dir`), or the link would
    fail with EXDEV, a reason unrelated to the wall. {probe: (variable for the probe or None, path or None)}."""
    home = Path.home()

    def usable(path, mode):
        return os.access(os.path.realpath(path), mode)
    first = lambda names, mode: next((home / n for n in names if (home / n).is_file() and usable(home / n, mode)), None)
    folder = lambda path, mode: path if path and Path(path).is_dir() and usable(path, mode) else None
    targets = {name: (None, Path(path) if os.path.isfile(path) and usable(path, os.X_OK) else None)
               for name, path in PROBE_PROGRAMS.items()}
    if not CALCULATOR_APP.is_dir():
        targets["exec_open_calculator"] = (None, None)
    def linkable():
        for n in (".zshrc", ".bashrc", ".profile", ".gitconfig"):
            p = home / n
            if p.is_file() and not p.is_symlink() and usable(p, os.R_OK):
                if lane_dir is None or _device(p) == _device(lane_dir):
                    return p
                return None
        return None
    read, write = os.R_OK | os.X_OK, os.W_OK | os.X_OK
    return {**targets,
            "read_dotfile": ("PROBE_DOTFILE", first((".zshrc", ".bashrc", ".profile", ".gitconfig"), os.R_OK)),
            "link_dotfile": ("PROBE_DOTFILE", linkable()),
            "open_rc_for_write": ("PROBE_RC", first((".zshrc", ".bashrc", ".profile"), os.R_OK | os.W_OK)),
            "read_claude_tmp": ("PROBE_CLAUDE_TMP", folder(PRIVATE_TMP / ("claude-%d" % os.getuid()), read)),
            "read_user_temp": ("PROBE_USER_TEMP", folder(user_temp, read)),
            "write_home": (None, folder(home, write)),
            "write_launchagents": ("PROBE_LAUNCHAGENTS", folder(home / "Library" / "LaunchAgents", write)),
            "write_users_shared": ("PROBE_USERS_SHARED", folder(USERS_SHARED, write))}


# The codes a probe's refusal may carry. Only these prove the profile said no: a mistake (an unknown probe, a missing
# input), a program that ran and failed, a timeout (code 23 from AbortSignal), a signal or ENOENT proves nothing. DNS
# reaches mDNSResponder over its Unix socket, which the profile denies; network_up() showed resolution works outside the
# sandbox, so any resolver failure inside it is the profile's doing and net_domain accepts the resolver's codes too.
REFUSAL_CODES = ("EPERM", "EACCES")
EXTRA_REFUSAL_CODES = {"net_domain": ("ENOTFOUND", "EAI_AGAIN", "EAI_FAIL")}


def judge_probe(name, returncode, output=""):
    """PASS, FAIL or BROKEN for one probe. A probe exits 0 when its action SUCCEEDED (a pass for the positive controls,
    a failure for the rest) and 1 with `refused: <code> ...` when it was refused. Anything else (a signal, 64, the
    probe's own exit 2, a refusal without a code the profile gives) is BROKEN: the probe never showed what it was
    meant to."""
    output = (output or "").strip()
    if returncode == 0:
        if not output.startswith("succeeded"):
            return "BROKEN"
        return "PASS" if name in SELF_CHECK_POSITIVE else "FAIL"
    match = re.match(r"refused: (\S+)", output)
    if returncode != 1 or not match:
        return "BROKEN"
    if name in SELF_CHECK_POSITIVE:
        return "FAIL"
    return "PASS" if match.group(1) in REFUSAL_CODES + EXTRA_REFUSAL_CODES.get(name, ()) else "BROKEN"


def self_check(node_bin, pw_dir, shell_dir, run=None):
    """Spec acceptance step 1 (and whenever the pinned revision changes): every spike 5 probe, plus `open -a
    Calculator`, run directly under a freshly generated profile, as code that took over the browser would run. The
    profile goes inline (sandbox-exec -p) and the probe as node -e, so nothing in the scratch lane decides what runs.
    Each probe's target is checked outside the sandbox first (it must exist and be usable, and the network probes need
    the network). Returns [(probe, verdict, detail)], the verdict PASS, FAIL or BROKEN (the probe proved nothing).
    macOS only; `run` is the seam the tests use."""
    run = run or subprocess.run
    team_id, worker_id = "superyak-self-check-%d" % os.getpid(), "check"
    held = hold_team(team_id)
    path = lane_path(team_id, worker_id)
    canary, listener = socket.socket(), socket.socket()
    rows = []
    leftovers = _probe_leftovers()
    before = {name for name, target in leftovers.items() if os.path.lexists(target)}
    try:
        ensure_lane(team_id, worker_id)
        base = allocate_block(team_id, worker_id)
        b_text = lane_text(path / "b")
        canary.bind(("127.0.0.1", 0))
        canary.listen(5)
        listener.bind(("127.0.0.1", base + 2))
        listener.listen(5)
        profile = render_profile(b_text, pw_dir, browsers_root(), shell_dir, node_bin, base)
        source = (teamlib.package_dir() / "lane" / "profile_probe.js").read_text()
        user_temp = _run(["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], timeout=10)
        targets = probe_targets(user_temp.stdout.strip() if user_temp and user_temp.returncode == 0 else None, path)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "TMPDIR": b_text,
               "PROBE_CANARY_PORT": str(canary.getsockname()[1]), "PROBE_LANE_PORT": str(base + 2)}
        env.update({var: str(path) for var, path in targets.values() if var and path})
        for name in sorted(before):
            rows.append(("leftover", "BROKEN", "%s exists from before this run, so it is left alone and %s is skipped"
                         % (leftovers[name], name)))
        net_ok = None
        for name in SELF_CHECK_PROBES + SELF_CHECK_POSITIVE:
            if name in before:
                rows.append((name, "BROKEN", "its leftover file already exists, so it could not show a refusal"))
                continue
            if name in targets and targets[name][1] is None:
                rows.append((name, "BROKEN", "its target is missing or unusable here, so a refusal would prove nothing"))
                continue
            if name in NETWORK_PROBES:
                net_ok = network_up() if net_ok is None else net_ok
                if not net_ok:
                    rows.append((name, "BROKEN", "this machine can't reach the network, so a refusal proves nothing"))
                    continue
            try:
                r = run([SANDBOX_EXEC, "-p", profile, str(node_bin), "-e", source, name],
                        env=env, cwd=b_text, capture_output=True, text=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError, ValueError) as e:
                rows.append((name, "BROKEN", ("%s: %s" % (type(e).__name__, e))[:160]))
                continue
            rows.append((name, judge_probe(name, r.returncode, r.stdout),
                         (r.stdout or r.stderr or "").strip()[:160]))
    finally:
        def step(what, fn):
            try:
                fn()
            except Exception as e:                    # one step failing must not skip the rest
                rows.append(("cleanup", "BROKEN", ("%s: %s: %s" % (what, type(e).__name__, e))[:160]))

        def sweep():
            for name, target in leftovers.items():
                if name not in before and os.path.lexists(target):
                    step("remove %s" % target, lambda: os.unlink(target))
                    if not os.path.lexists(target):
                        rows.append(("leftover", "FAIL", "removed %s, which a probe created" % target))
        step("close the canary", canary.close)
        step("close the listener", listener.close)
        step("remove what a probe created", sweep)
        step("remove the lane", lambda: remove_lane(path))
        step("release the block", lambda: release_block(team_id, worker_id))
        step("release the team lock", held.close)
        step("remove the lock file", lambda: _team_lock(team_id).unlink(missing_ok=True))
    return rows


# ---------- the broker: start, stop, process cleanup, diagnostics (spec: The broker, Process cleanup) ----------

START_TIMEOUT_S = 90
KILL_GRACE_S = 5


class Broker:
    """A running broker: its process, which leads its own process group, its port (the block's last) and its secret,
    32 random bytes, new for each broker."""

    def __init__(self, proc, port, secret):
        self.proc, self.port, self.secret = proc, port, secret

    @property
    def endpoint(self):
        return "ws://127.0.0.1:%d/%s" % (self.port, self.secret)

    def alive(self):
        return self.proc.poll() is None


def broker_env(b_dir, pw_dir):
    """Built from nothing, never inherited, so no NODE_OPTIONS, PLAYWRIGHT_* or PW_* of teamd's can reach the broker.
    The secret isn't here: it goes on the broker's stdin, so Chrome, which inherits this environment, never has it."""
    b = str(b_dir)
    return {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "TMPDIR": b, "MAC_CHROMIUM_TMPDIR": b,
            "PLAYWRIGHT_BROWSERS_PATH": str(browsers_root()), "SUPERYAK_BROKER_PLAYWRIGHT": str(pw_dir)}


def prepare_broker(repo, base_commit, worktrees, fetch=None):
    """Everything a broker needs before it starts: lane_node, the pinned Playwright and the checked headless shell.
    One teamd installs at a time. Returns (node_bin, pw_dir, shell_dir)."""
    node_bin = check_lane_node(teamlib.load_config().get("lane_node"), worktrees)
    with install_lock():  # Task 5 fix round: reentrant; teamlib.locked on the same file would deadlock
        pw_dir = pinned_playwright(repo, base_commit, fetch)
        shell_dir, revision = install_headless_shell(node_bin, pw_dir)
        check_manifest(shell_dir, revision)
    return node_bin, pw_dir, shell_dir


def _drain(stream, lines):
    for line in stream:
        lines.put(line)
    lines.put("")


def start_broker(path, base, node_bin, pw_dir, shell_dir, stderr_path):
    """Start the lane's broker in its own process group and wait for its endpoint. The profile goes inline
    (sandbox-exec -p) and the script runs as node -e from teamd's own package, with the port in argv, so nothing in
    the lane, which hostile processes can write, decides what the broker is. Every process still using the lane's b/
    ends first. sandbox-exec gets the resolved node binary, never a bare `node` (a deny-default profile refuses the
    PATH search). Its stderr goes to stderr_path, in teamd's own folder, never the lane. A broker that doesn't start
    is stopped, and LaneRefused carries the last lines of its stderr, scrubbed of the secret, plus its sandbox
    denials (details)."""
    b = Path(path) / "b"
    b_text = lane_text(b)
    if not cleanup_processes(b, None):
        raise LaneRefused("lsof can't say which processes still use %s, so the lane's browser doesn't start" % b)
    secret = secrets.token_hex(32)
    port = base + BLOCK - 1
    profile = render_profile(b_text, pw_dir, browsers_root(), shell_dir, node_bin, base)
    stderr_path = Path(stderr_path)
    try:
        source = (teamlib.package_dir() / "lane_broker.js").read_text()
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise LaneRefused("the lane's browser can't start (%s)" % (e.strerror or e))
    stream = start_denial_stream()
    try:
        err = _new_fd(str(stderr_path), 0o600)
        try:
            proc = subprocess.Popen([SANDBOX_EXEC, "-p", profile, str(node_bin), "-e", source, str(port)],
                                    cwd=b_text, env=broker_env(b_text, pw_dir), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=err, text=True, start_new_session=True)
        finally:
            os.close(err)
        try:
            proc.stdin.write(secret + "\n")
            proc.stdin.flush()
        except OSError:
            pass                                        # it died already: the endpoint check below says so
    except OSError as e:
        stop_denial_stream(stream)
        raise LaneRefused("the lane's browser can't start (%s)" % (e.strerror or e))
    broker = Broker(proc, port, secret)
    lines = queue.Queue()
    threading.Thread(target=_drain, args=(proc.stdout, lines), daemon=True).start()
    pids, first, deadline = {proc.pid}, None, time.monotonic() + START_TIMEOUT_S
    while first is None and time.monotonic() < deadline:
        try:
            first = lines.get(timeout=0.5).strip()
        except queue.Empty:
            pids |= family(proc.pid)[0]
    if first == "ENDPOINT " + broker.endpoint:
        stop_denial_stream(stream)
        return broker
    exited = proc.poll()
    pids |= family(proc.pid)[0]
    stop_broker(broker)
    cleanup_processes(b, None)                          # node is gone: what it started is found by its folder now
    denials = denials_for(stop_denial_stream(stream), pids)
    try:
        log = stderr_path.read_text(errors="replace").splitlines()
    except OSError:
        log = []
    tail = [scrub(line, [secret])[:300] for line in log if not line.lstrip().startswith("at ")][-20:]
    said = first or ("no endpoint within %d s" % START_TIMEOUT_S if exited is None
                     else "the broker exited (%s) before its endpoint" % exited)
    detail = scrub(teamlib.redact("\n".join([said] + tail)), [secret])
    raise LaneRefused("the lane's browser didn't start: " + detail[-1500:],
                      details=[scrub(line, [secret]) for line in denials])


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def stop_broker(broker):
    """Close its stdin (it closes the browser and exits), then SIGTERM every group and process of its family, then
    after KILL_GRACE_S SIGKILL. The family is taken first, while node lives: once node exits, Chrome's parent is
    launchd, and Chrome was never in node's group (Playwright launches it detached)."""
    proc = broker.proc
    if proc.poll() is not None:
        # Already reaped: its pid may belong to someone else now, so no family walk and no signal. What it left
        # behind is ended by path (cleanup_processes: Chrome's cwd is b/).
        return
    pids, groups = family(proc.pid)
    try:
        proc.stdin.close()
    except (OSError, ValueError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass
    def running(pid):                                    # the root is the Popen's: never a reused pid
        return proc.poll() is None if pid == proc.pid else _alive(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for group in groups:
            _killpg(group, sig)
        for pid in pids:
            if running(pid):
                _kill(pid, sig)
        deadline = time.monotonic() + KILL_GRACE_S
        while sig == signal.SIGTERM and time.monotonic() < deadline and any(running(pid) for pid in pids):
            time.sleep(0.1)
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        pass


def _process_table():
    """(pid, ppid, pgid, uid) for every process, from ps; [] when ps can't say."""
    r = _run(["/bin/ps", "-A", "-o", "pid=,ppid=,pgid=,uid="], timeout=10)
    rows = []
    for line in (r.stdout if r is not None and r.returncode == 0 else "").splitlines():
        fields = line.split()
        if len(fields) == 4 and all(f.isdigit() for f in fields):
            rows.append(tuple(int(f) for f in fields))
    return rows


def family(root):
    """The broker's processes: root, its descendants by ppid, and every process in a group one of them leads (Chrome
    and its helpers: Playwright launches the browser detached, in its own group). Returns (pids, groups), the groups
    being only those a member of the family leads."""
    rows = _process_table()
    children = {}
    for pid, ppid, pgid, uid in rows:
        children.setdefault(ppid, []).append(pid)
    tree, stack = {root}, [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in tree:
                tree.add(child)
                stack.append(child)
    groups = {root} | {pgid for pid, ppid, pgid, uid in rows if pid in tree and pgid in tree}
    return tree | {pid for pid, ppid, pgid, uid in rows if pgid in groups}, groups


def _lane_prefixes(path):
    """The names an open file under this lane path can have in lsof's output: the path as teamd names it, and with
    the parent resolved. Nothing below the parent is ever resolved, so a lane swapped for a link to $HOME matches
    nothing in $HOME. A parent that is a link refuses."""
    path, parent = Path(path), _parent_path()
    st = os.lstat(parent)
    if stat.S_ISLNK(st.st_mode):
        raise LaneRefused("unsafe lane folder %s (a symlink)" % parent)
    return {str(path), os.path.join(os.path.realpath(parent), *path.relative_to(parent).parts)}


def lane_pids(path, base):
    """Processes of this uid that listen on a port in the lane's block (base None: no block was allocated), or have
    their cwd or an open file under the lane. The files come from one `lsof -F pn` over all of this uid's open files,
    matched by name: the lane folder is never walked. None when lsof can't say."""
    lsof = shutil.which("lsof", path=SYSTEM_PATH)
    if not lsof:
        return None
    uid, pids = str(os.getuid()), set()
    if base is not None:
        r = _run([lsof, "-nP", "-a", "-u", uid, "-iTCP:%d-%d" % (base, base + BLOCK - 1), "-sTCP:LISTEN", "-t"])
        if r is None or r.returncode not in (0, 1):     # lsof exits 1 when it finds nothing
            return None
        pids |= {int(x) for x in r.stdout.split() if x.isdigit()}
    try:
        prefixes = _lane_prefixes(path)
    except FileNotFoundError:
        prefixes = set()                                # no parent: nothing can be open under the lane
    except (OSError, LaneRefused):
        return None
    if prefixes:
        r = _run([lsof, "-nP", "-a", "-u", uid, "-F", "pn"])
        if r is None or r.returncode != 0:              # teamd always has open files: 1 means an error here
            return None
        pid = None
        for line in r.stdout.splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None:
                name = line[1:]
                if any(name == prefix or name.startswith(prefix + "/") for prefix in prefixes):
                    pids.add(pid)
    return pids - _spared(_process_table())


def _spared(rows):
    """teamd and every process above it: never signalled."""
    parent = {pid: ppid for pid, ppid, pgid, uid in rows}
    spared, pid = set(), os.getpid()
    while pid and pid not in spared:
        spared.add(pid)
        pid = parent.get(pid, 0)
    return spared


def env_pids(name, value):
    """This uid's processes whose environment holds exactly name=value: the lane's CLAUDE_CODE_TMPDIR finds what a
    turn left behind in a new session (a setsid child), which neither the worker's group nor lsof's files would.
    Never teamd itself or any process above it. None when ps can't say."""
    rows = _process_table()
    if not rows:
        return None
    spared = _spared(rows)
    wanted = "%s=%s" % (name, value)
    return {pid for pid, ppid, pgid, uid in rows
            if uid == os.getuid() and pid not in spared and wanted in (_environ(pid) or [])}


def _alive(pid):
    """Whether pid is a running process. Never reaps: a child that some Popen owns still reports its own exit code.
    A zombie (exited, not yet reaped) is not running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    r = _run(["/bin/ps", "-o", "stat=", "-p", str(pid)], timeout=10)
    return not (r is not None and r.returncode == 0 and r.stdout.strip().startswith("Z"))


def _kill(pid, sig):
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def cleanup_processes(path, base, broker=None, env=None):
    """When a lane ends (and before a broker starts in its b/): the broker, then every process found by lane_pids
    (Playwright's detached webServer and dev servers, which killing the worker's group misses) and, with env as
    (name, value), by env_pids. SIGTERM and after KILL_GRACE_S SIGKILL, then a second look for anything started
    meanwhile. True once finished; False when lsof or ps couldn't say, so the block stays held."""
    if broker is not None:
        stop_broker(broker)

    def found():
        pids = lane_pids(path, base)
        extra = env_pids(*env) if env else set()
        return None if pids is None or extra is None else pids | extra
    pids = found()
    if pids is None:
        return False
    for pid in pids:
        _kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    again = found()                                      # only what still matches: a pid that exited may be reused
    if again is None:
        return False
    for pid in again:
        _kill(pid, signal.SIGKILL)
    return True


DENIAL_RE = re.compile(r"Sandbox: (.+?)\((\d+)\) deny\(\d+\) (\S+) ?(.*)$")


def start_denial_stream():
    """Sandbox denials as they happen (macOS only): `log show` after the fact caught nothing in spikes 1 and 2."""
    if sys.platform != "darwin":
        return None
    try:
        return subprocess.Popen(["/usr/bin/log", "stream", "--style", "compact", "--predicate",
                                 'eventMessage CONTAINS "Sandbox:" OR subsystem == "com.apple.sandbox.reporting"'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return None


def stop_denial_stream(stream):
    if stream is None:
        return []
    stream.terminate()
    try:
        out, _ = stream.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        stream.kill()
        out, _ = stream.communicate()
    return out.splitlines()


def denials_for(lines, pids):
    """Only the denials of these pids, the broker's process group. Never by name: a `node` prefix would match every
    node on the Mac, and the stream sees every sandbox (spike 5 printed file names from Mail's downloads)."""
    seen = []
    for line in lines:
        found = DENIAL_RE.search(line)
        if not found or int(found.group(2)) not in pids:
            continue
        key = "%s(%s): %s %s" % (found.group(1).strip(), found.group(2), found.group(3), found.group(4)[:160])
        if key not in seen:
            seen.append(key)
    return seen


# ---------- the secret (spec: Worker environment) ----------

def scrub(text, secrets_):
    """Playwright's errors quote the whole endpoint, and teamlib.redact doesn't know the secret: remove it."""
    text = text if isinstance(text, str) else str(text)
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "[lane secret]")
    return text


def scrub_file(path, secrets_):
    """Rewrite a file teamd keeps (events.jsonl, stderr.log) without the secret. Only after the turn has ended."""
    path = Path(path)
    if not secrets_ or not path.is_file() or path.is_symlink():
        return
    try:
        text = path.read_text(errors="replace")
        clean = scrub(text, secrets_)
        if clean != text:
            tmp = path.with_name(path.name + ".scrub")
            _write_text(tmp, clean, 0o600)
            os.replace(tmp, path)
    except OSError as e:
        raise LaneRefused("%s can't be scrubbed of the lane's secret (%s)" % (path, e.strerror or e))
