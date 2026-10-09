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
from contextlib import contextmanager
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
DEPENDENCIES_MARKER = "DEPENDENCIES_VALIDATED"


def broker_root():
    """~/.superyak/team/broker: teamd's own copies of Playwright and its browser, outside every worktree."""
    root = teamlib.team_home() / "broker"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def browsers_root():
    """PLAYWRIGHT_BROWSERS_PATH for the installer and the broker: never the user's own browsers folder."""
    root = broker_root() / "browsers"
    root.mkdir(exist_ok=True)
    os.chmod(root, 0o700)
    return root


def lock_entry(repo, base):
    """playwright-core's version and integrity from the lockfile at the worker's base commit (the lead's, fixed at
    spawn), never from the worktree, which the worker can write."""
    r = workers.git(repo, "cat-file", "blob", "%s:package-lock.json" % base, check=False)
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


def https_get(url, limit=64 * 2 ** 20):
    """teamd's own download, with no proxy: the integrity check, not the transport, is what the pin rests on."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise LaneRefused("%s is larger than %d bytes" % (url, limit))
    return data


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
            _write_text(tmp / "package" / STAMP, stamp + "\n", 0o600)
            os.rename(tmp / "package", dest)
        except OSError as e:
            raise LaneRefused("playwright-core can't be unpacked into %s (%s)" % (dest, e.strerror or e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def pinned_playwright(repo, base, fetch=None):
    """~/.superyak/team/broker/playwright-core-<version>/, fetched from the npm registry the first time. The tarball is
    checked against the integrity hash in the base commit's lockfile, never the registry's own claim. A mismatch
    anywhere refuses the lane."""
    version, integrity = lock_entry(repo, base)
    dest = broker_root() / ("playwright-core-" + version)
    if dest.is_dir():
        stamp = dest / STAMP
        if not stamp.is_file() or stamp.read_text().strip() != integrity:
            raise LaneRefused("%s isn't stamped with the integrity hash the base commit names; remove it and the next "
                              "lane fetches it again" % dest)
        return dest
    fetch = fetch or https_get
    try:
        meta = json.loads(fetch(REGISTRY + "playwright-core/" + version))
    except (OSError, ValueError) as e:
        raise LaneRefused("the npm registry's metadata for playwright-core %s can't be read (%s)" % (version, e))
    dist = meta.get("dist") if isinstance(meta, dict) and isinstance(meta.get("dist"), dict) else {}
    tarball = dist.get("tarball")
    if not isinstance(tarball, str) or not tarball.startswith(REGISTRY + "playwright-core/-/"):
        raise LaneRefused("playwright-core %s's tarball isn't on %s" % (version, REGISTRY))
    try:
        data = fetch(tarball)
    except OSError as e:
        raise LaneRefused("playwright-core %s's tarball can't be downloaded (%s)" % (version, e))
    if "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode() != integrity:
        raise LaneRefused("playwright-core %s's tarball doesn't match the integrity hash in the base commit's "
                          "lockfile" % version)
    extract_package(data, dest, integrity)
    return dest


def shell_revision(pw_dir):
    """The headless shell's revision, as the pinned Playwright names it in its browsers.json."""
    try:
        data = json.loads((Path(pw_dir) / "browsers.json").read_text())
    except (OSError, ValueError):
        data = {}
    for browser in data.get("browsers") or []:
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
    for parent in Path(os.path.realpath(path)).parents:
        _check_owner(parent, os.stat(parent), sticky_ok=True)


def manifest_hash(folder):
    """sha256 over every entry under folder, sorted: its path, kind, mode, and its symlink target or its content's
    sha256. Every entry must be owned by this user and writable by nobody else, and a symlink must stay inside the
    folder (relative, never escaping). An empty DEPENDENCIES_VALIDATED at the top, the marker Playwright writes when
    an unsandboxed process launches the browser, carries no code and is left out (the broker can't write it)."""
    folder = Path(folder)
    _check_owner(folder, os.lstat(folder))
    root = os.path.realpath(folder)
    digest = hashlib.sha256()
    for top, dirs, files in os.walk(folder, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            full = Path(top) / name
            st = os.lstat(full)
            _check_owner(full, st)
            rel = full.relative_to(folder).as_posix()
            if rel == DEPENDENCIES_MARKER and stat.S_ISREG(st.st_mode) and st.st_size == 0:
                continue
            if stat.S_ISLNK(st.st_mode):
                target = os.readlink(full)
                resolved = os.path.realpath(full)       # through every link in a chain, not just this one
                if os.path.isabs(target) or not (resolved == root or resolved.startswith(root + os.sep)):
                    raise LaneRefused("%s links outside the browser's folder (to %s)" % (full, target))
                kind, extra = "l", target
            elif stat.S_ISDIR(st.st_mode):
                kind, extra = "d", ""
            elif stat.S_ISREG(st.st_mode):
                kind, extra = "f", _file_sha256(full)
            else:
                raise LaneRefused("%s is neither a file, a folder nor a symlink" % full)
            digest.update(("%s\0%s\0%o\0%s\n" % (rel, kind, stat.S_IMODE(st.st_mode), extra)).encode())
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
    data = json.loads(MANIFESTS.read_text())
    return ((data.get(SHELL) or {}).get(revision) or {}).get(platform_key())


def check_manifest(folder, revision):
    """The installed browser must match the hash the repo records for its revision and platform, and its folder and
    every folder above it must be safe as lane_node's are. Run after every install and at every broker start.
    Returns the hash."""
    root = browsers_root()
    _check_owner(root, os.lstat(root))
    _check_ancestors(root)
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
