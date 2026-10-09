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
import math
import os
import platform
import queue
import re
import resource
import secrets
import selectors
import shutil
import signal
import socket
import stat
import struct
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
DROP_ENV = ("SSH_AUTH_SOCK", "GPG_AGENT_INFO", "DOCKER_HOST", "CLAUDE_CODE_PROCESS_WRAPPER")
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")
MANAGED_MCP = Path("/Library/Application Support/ClaudeCode/managed-mcp.json")
# Settings whose value is a command Claude Code runs outside the sandbox, with its own environment (the lane's), in
# claude -p too; neither disableAllHooks nor --strict-mcp-config stops them. The binary's credential-helper list, plus
# otelHeadersHelper and proxyAuthHelper.
HELPER_KEYS = ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "gcpAuthRefresh", "otelHeadersHelper",
               "proxyAuthHelper")
# H1: keys read from the user's and the managed files that also run a command (processWrapper: managed, flag and user
# settings only, confirmed in 2.1.295), and the managed-only policy helpers (both spellings the binary knows).
USER_COMMAND_KEYS = ("processWrapper",)
MANAGED_COMMAND_KEYS = ("policyHelper", "policyHelpers")
LIVE_STATES = ("preparing", "queued", "running", "idle", "waiting")   # teamd.LIVE: a worker in one of these is alive


class LaneRefused(teamlib.RejectedMessage):
    """The lane can't run. teamd fails the worker and tells the lead why; `details` (sandbox denials) stay local, and
    `log` (what only Andy should act on, such as a manifest hash to record) goes to teamd.log, never to the lead."""

    def __init__(self, message, details=None, log=None):
        super().__init__(message)
        self.details = list(details or [])
        self.log = log


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
    """What settings outside the lane would merge into its sandbox. The check is an allowlist: in the user's files and
    the managed one, any sandbox key at any depth refuses (network keys, filesystem.allowWrite, excludedCommands, which
    run fully outside the sandbox, allowUnsandboxedCommands, any key Claude Code adds later), except an empty
    network.allowedDomains; any WebFetch allow rule widens the lane's network too. Workers without a lane never call
    it. A managed policy's hooks run outside the sandbox with the lane's
    environment even under disableAllHooks, and so does any helper command (HELPER_KEYS); a managed MCP config refuses
    too. A file that exists but can't be read, or holds a sandbox, network,
    permissions or allow list of the wrong shape, counts as a widening: the check fails closed. Only plain-word key
    names are quoted back (this text reaches the lead)."""
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
        found += ["%s %s" % (path, why) for why in _widenings(data, managed=path == MANAGED_SETTINGS)]
    if os.path.lexists(MANAGED_MCP):
        found.append("%s exists: its MCP servers would run outside the sandbox with the lane's environment"
                     % MANAGED_MCP)
    # Managed sources this check doesn't read (paths from the 2.1.295 binary): the drop-in folder beside the managed
    # file, and the server-managed settings Claude Code caches in its config folder.
    for unread in (MANAGED_SETTINGS.with_name("managed-settings.d"), _claude_dir() / "remote-settings.json"):
        if os.path.lexists(unread):
            found.append("%s exists: its settings are never read by this check and would apply to the lane" % unread)
    if os.environ.get("CLAUDE_CODE_PROCESS_WRAPPER"):
        found.append("teamd's environment sets CLAUDE_CODE_PROCESS_WRAPPER, a launcher Claude Code runs outside the "
                     "sandbox")
    return found


def _widenings(data, managed):
    sandbox, permissions = data.get("sandbox", {}), data.get("permissions", {})
    if not isinstance(sandbox, dict):
        return ["can't be read (its sandbox isn't an object)"]
    network = sandbox.get("network", {})
    if not isinstance(network, dict):
        return ["can't be read (its sandbox.network isn't an object)"]
    if not isinstance(permissions, dict):
        return ["can't be read (its permissions isn't an object)"]
    allow = permissions.get("allow", [])
    if not isinstance(allow, list):
        return ["can't be read (its permissions.allow isn't a list)"]
    if not all(isinstance(rule, str) for rule in allow):
        return ["can't be read (its permissions.allow holds a rule that isn't a string)"]
    out = ["adds sandbox.%s" % ".".join(keys) if all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", k) for k in keys)
           else "adds a sandbox key this check doesn't know" for keys in _sandbox_keys(sandbox)]
    if any(rule == "WebFetch" or rule.startswith("WebFetch(") for rule in allow):
        out.append("allows WebFetch")
    out += ["sets %s, which Claude Code runs outside the sandbox with the lane's environment" % key
            for key in HELPER_KEYS + USER_COMMAND_KEYS + (MANAGED_COMMAND_KEYS if managed else ())
            if data.get(key) not in (None, "")]
    if managed:
        plugins = data.get("enabledPlugins")
        if plugins is not None and not isinstance(plugins, dict):
            out.append("can't be read (its enabledPlugins isn't an object)")
        elif isinstance(plugins, dict) and any(value is not False for value in plugins.values()):   # true or a version list is on
            out.append("forces a plugin on with enabledPlugins, whose LSP servers and monitors would run with the "
                       "lane's environment")
    if managed and data.get("hooks"):
        out.append("defines hooks, which Claude Code runs outside the sandbox with the lane's environment even under "
                   "disableAllHooks")
    return out


def _sandbox_keys(sandbox, above=()):
    """Every key path in a sandbox block, down to its leaves (an empty object is a leaf), except the one a lane allows:
    network.allowedDomains holding an empty list."""
    for key, value in sandbox.items():
        keys = above + (str(key),)
        if keys == ("network", "allowedDomains") and value == []:
            continue
        if isinstance(value, dict) and value:
            yield from _sandbox_keys(value, keys)
        else:
            yield keys


PLUGIN_SETTINGS_MAX = 1 << 20


def _plugins_named(path, follow):
    """The plugin ids a settings file's enabledPlugins names, whatever their values; [] when there is no such file.
    A file that exists but can't be fully read (not a regular file, over 1 MB, not JSON, not an object, enabledPlugins
    not an object, any other OSError) raises LaneRefused naming it: the plugins it enables would stay on (H2). Never
    waits on a FIFO and never reads past 1 MB. A user's file is read where it is; the worktree's are the worker's, so
    one that is a link is still read (Claude Code would follow it) but only as a plain file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | (0 if follow else os.O_NOFOLLOW))
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as e:
        raise LaneRefused("%s can't be read (%s), so the plugins it enables can't be switched off"
                          % (path, e.strerror or e.__class__.__name__))
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)
    except OSError:
        regular = False
    if not regular:
        os.close(fd)
        raise LaneRefused("%s isn't a regular file, so the plugins it enables can't be switched off" % path)
    with os.fdopen(fd, "rb") as f:
        try:
            raw = f.read(PLUGIN_SETTINGS_MAX + 1)
        except OSError as e:
            raise LaneRefused("%s can't be read (%s), so the plugins it enables can't be switched off"
                              % (path, e.strerror or e.__class__.__name__))
    if len(raw) > PLUGIN_SETTINGS_MAX:
        raise LaneRefused("%s is over 1 MB, so the plugins it enables can't be switched off" % path)
    try:
        data = json.loads(raw)
    except ValueError:
        raise LaneRefused("%s isn't valid JSON, so the plugins it enables can't be switched off" % path)
    if not isinstance(data, dict):
        raise LaneRefused("%s isn't a JSON object, so the plugins it enables can't be switched off" % path)
    plugins = data.get("enabledPlugins")
    if plugins is None:
        return []
    if not isinstance(plugins, dict):
        raise LaneRefused("%s: its enabledPlugins isn't an object, so the plugins it enables can't be switched off"
                          % path)
    return [str(key) for key in plugins]


def lane_plugins(worktree):
    """Round 2, item 1: every plugin a browser turn could load, to be switched off in its flag settings
    (enabledPlugins: false). Claude Code has no single switch for "no plugins" (--safe-mode also drops CLAUDE.md, and
    --bare needs API-key auth), and its settings precedence is user < project < local < flag < policy, so false in the
    flag settings beats every file named here: the user's settings.json and settings.local.json, and the worktree's
    own .claude/settings.json and settings.local.json, which the worker could write. Read at every turn's start."""
    names = set()
    for path in (_claude_dir() / "settings.json", _claude_dir() / "settings.local.json"):
        names.update(_plugins_named(path, follow=True))
    for name in ("settings.json", "settings.local.json"):
        names.update(_plugins_named(Path(worktree) / ".claude" / name, follow=True))
    return sorted(names)


def check_spawn(cfg, kind, mode):
    """Raise RejectedMessage, naming the reason, unless this worker may have a browser lane."""
    if cfg.get("browser_lane") is not True:
        raise teamlib.RejectedMessage("browser lanes are off for this team: a person turns them on with "
                                      "browser_lane in a preset (~/.superyak/team/presets.json)")
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
    npm-cache/ (npm_config_cache) and b/ (the broker's folder). Everything goes through folder descriptors opened
    without following links, so a lane or folder swapped for a link is refused, never followed. The worker may write
    tmp/ and npm-cache/ only (workers.claude_sandbox_settings). teamd writes no file here: the preload, which every
    node process outside the sandbox would load, is teamd's own (ensure_preload)."""
    parent = private_parent()
    h = lane_hash(team_id, worker_id)
    try:
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
    """Back to the pool. Call only once the lane's process cleanup has finished. Never raises: True once the block is
    out of the registry (or never was in it), False when the registry needs a person (the caller says so)."""
    try:
        with _registry_lock():
            data = _read_registry()
            if data.pop(lane_hash(team_id, worker_id), None) is not None:
                _write_registry(data)
        return True
    except LaneRefused as e:
        print("superyak-team: lane block of %s/%s not released: %s" % (team_id, worker_id, e), file=sys.stderr)
        return False


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


# ---------- the preload (spec: The preload) ----------

PRELOAD_NAME = "lane-preload.cjs"


def preload_path(team_id, worker_id):
    """teamd's own copy of the preload for this worker's lane, in its worker folder under ~/.superyak/team, never under
    /tmp: NODE_OPTIONS names it in claude's own environment, so every node process claude starts, inside the sandbox
    or not, requires it, and a Codex worker can write /tmp."""
    return teamlib.team_dir(team_id) / "workers" / worker_id / PRELOAD_NAME


def _private_folder(folder):
    """A real folder of this user's that nobody else can write, outside the shared temp folders, every folder above it
    owned by this user or root and writable by nobody else (a sticky one, like /tmp, aside), as lane_node's are."""
    try:
        st = os.lstat(folder)
    except OSError as e:
        raise LaneRefused("%s can't be checked (%s)" % (folder, e.strerror or e))
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise LaneRefused("%s isn't a folder of yours" % folder)
    if st.st_mode & 0o022:
        raise LaneRefused("%s is writable by someone other than its owner" % folder)
    real = os.path.realpath(folder)
    for unsafe in UNSAFE_ROOTS:
        if real == unsafe or real.startswith(unsafe + os.sep):
            raise LaneRefused("%s lies under the shared temp folder %s" % (folder, unsafe))
    _check_ancestors(folder)


def _preload_is(path, text):
    """Whether path is already exactly the preload: a plain file of this user's, mode 0644, one link, these bytes.
    False when it is missing or must be replaced. A symlink or another user's file in teamd's own folder is somebody
    else's doing: refused, never replaced or followed."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as e:
        raise LaneRefused("the lane's preload %s can't be checked (%s)" % (path, e.strerror or e))
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise LaneRefused("the lane's preload %s isn't a plain file" % path)
    if st.st_uid != os.getuid():
        raise LaneRefused("the lane's preload %s belongs to another user" % path)
    if stat.S_IMODE(st.st_mode) != 0o644 or st.st_nlink != 1 or st.st_size != len(text):
        return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return False
    with os.fdopen(fd, "rb") as f:
        now = os.fstat(f.fileno())
        if (now.st_dev, now.st_ino) != (st.st_dev, st.st_ino):
            return False
        return f.read(len(text) + 1) == text


def ensure_preload(team_id, worker_id):
    """The preload at a browser turn's start, from teamd's shipped copy: a plain file of this user's at mode 0644 in a
    folder only this user can write, outside the shared temp folders. A file that is already right is left alone; one
    with other bytes, another mode or a second link is replaced (unlink, then O_CREAT|O_EXCL|O_NOFOLLOW), never written
    through. Returns its path."""
    path = preload_path(team_id, worker_id)
    try:
        text = (teamlib.package_dir() / "lane" / "preload.cjs").read_bytes()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        raise LaneRefused("the lane's preload can't be prepared (%s)" % (e.strerror or e))
    _private_folder(path.parent)
    if _preload_is(path, text):
        return path
    try:
        with os.fdopen(_new_fd(str(path), 0o644), "wb") as f:
            os.fchmod(f.fileno(), 0o644)                # whatever teamd's umask
            f.write(text)
    except OSError as e:
        raise LaneRefused("the lane's preload %s can't be written (%s)" % (path, e.strerror or e))
    if not _preload_is(path, text):
        raise LaneRefused("the lane's preload %s changed as it was written" % path)
    return path


def node_require(preload):
    """NODE_OPTIONS's --require for the preload, quoted, since a home folder may hold a space. A path node's parser
    couldn't take inside quotes is refused."""
    text = str(preload)
    if re.search(r'["\\\x00-\x1f\x7f]', text):
        raise LaneRefused("refusing a preload path NODE_OPTIONS can't quote: %r" % text)
    return '--require "%s"' % text


# ---------- the worker's environment (spec: Worker environment) ----------

def worker_env(path, base, endpoint, preload):
    """What a browser worker's turn adds to its environment. workers.launch also drops DROP_ENV. All of it is in
    claude's own environment, so whatever claude starts outside its sandbox inherits it too: browser workers run with
    --strict-mcp-config and disableAllHooks (workers.claude_command), the preload is teamd's own file, and claude's
    own updater is off (an npm install of claude would use npm_config_cache, which the worker can write)."""
    path = Path(path)
    return {"CLAUDE_CODE_TMPDIR": str(path / "tmp"),
            "npm_config_cache": str(path / "npm-cache"),
            "SUPERYAK_BROWSER_LANE": "1",
            "SUPERYAK_LANE_PORT_BASE": str(base),
            "SUPERYAK_LANE_PORT_COUNT": str(BLOCK),
            "PW_TEST_CONNECT_WS_ENDPOINT": endpoint,
            "NODE_OPTIONS": node_require(preload),
            "DISABLE_AUTOUPDATER": "1",
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
# `nettop -L 1 -n -m tcp`'s CSV header, measured on macOS 27.0.1 (build 26A434) on 2026-10-09. There netstat shows a
# user no TCP socket at all, so nettop names other users' listeners; the loopback scan decides what is reachable.
# nettop is a private tool's output: a header that isn't exactly this one names nothing, so the ports it would have
# named stay unnamed and refuse the lane.
NETTOP_HEAD = ("time,,interface,state,bytes_in,bytes_out,rx_dupe,rx_ooo,re-tx,rtt_avg,rcvsize,tx_win,tc_class,tc_mgt,"
               "cc_algo,P,C,R,W,arch,")
NETTOP_TAIL = NETTOP_HEAD.count(",") - 1           # the fields after a process line's name (a name may hold commas)
NETTOP_PROCESS_RE = re.compile(r"(.+)\.([0-9]+)")
NETTOP_SOCKET_RE = re.compile(r"(tcp4|tcp6) (\S+)<->(\S+)")
IFF_LOOPBACK = 0x8
# The loopback scan (spec: The listener check, amendment of 2026-10-09, revision 2): every address on the loopback
# interfaces, ports 1-65535, non-blocking connects at most SCAN_BATCH in flight with SCAN_BATCH_S for each batch to
# answer, SCAN_DEADLINE_S for the whole scan. Only ECONNREFUSED is closed. Pending, erroring and unnamed ports are
# probed again one at a time with REPROBE_S (a self-connect or an incomplete probe up to REPROBE_TRIES times).
SCAN_BATCH, SCAN_BATCH_S, SCAN_DEADLINE_S = 1024, 0.5, 60
REPROBE_S, REPROBE_TRIES = 2.0, 3
SCAN_LOCK_S = 90            # how long a check waits for another teamd's scan before it fails closed
INCOMPLETE = (errno.EADDRNOTAVAIL, errno.EMFILE, errno.ENOBUFS)     # the scan's own trouble, never a port's verdict
NOFILE_CAP = 10240          # when kern.maxfilesperproc can't be read (and on Linux): the soft limit's ceiling


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


def approval_problem(entry):
    """Why this path can't be on the approved list, or "" when it can: the rules load_approved applies to each entry
    (an Apple program in a SIP-protected folder, never an interpreter, on the sealed system volume). Shared with the
    acceptance script's --list-listeners, so what it calls approvable is what load_approved accepts."""
    if not isinstance(entry, str) or os.path.normpath(entry) != entry or not entry.startswith(APPROVED_DIRS):
        return "only Apple programs in /System, /usr/libexec, /usr/sbin or /sbin may listen while a lane runs"
    if INTERPRETER_RE.fullmatch(os.path.basename(entry).lower()):
        return "an interpreter is never approved"
    why = ("not on the sealed system volume" if entry.startswith(NOT_SEALED)
           or "/CoreTypes.bundle/Contents/Library/" in entry else _sealed(entry))
    if why:
        return "%s%s" % (why, ", so a person could change what it runs" if why.startswith("not") else "")
    return ""


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
        problem = approval_problem(entry)
        if problem:
            raise LaneWait("%s: %r refused: %s" % (path, entry, problem))
        out.add(entry)
    return out


def _run(cmd, timeout=60):
    """Every command lane.py runs outside the sandbox goes through here (the tests' seam). None when it can't run."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def parse_lsof(text):
    """`lsof -F pn` output (or `-F pctn`): one dict per listening socket, {pid, command, host, port}, plus "family"
    (4 or 6) when lsof gave the socket's type (`tIPv4`, `tIPv6`). IPv6 hosts come in brackets ([::1]:41000), a
    wildcard as *. A * without its type is a row it can't read (ruling 2b6e272b): None, and the check refuses."""
    out, pid, command, family = [], None, "", None
    for line in text.split("\n"):
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            pid, command, family = int(value), "", None
        elif field == "c":
            command = value
        elif field == "f":
            family = None
        elif field == "t":
            family = {"IPv4": 4, "IPv6": 6}.get(value)
        elif field == "n" and pid is not None:
            host, sep, port = value.rpartition(":")
            if not sep or not port.isdigit():
                continue
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            if host == "*" and family is None:              # which family's wildcard can't be told
                return None
            row = {"pid": pid, "command": command, "host": host, "port": int(port)}
            if family is not None:
                row["family"] = family
            out.append(row)
    return out


def _nettop_sockets(text):
    """(sockets, why) from `nettop -L 1 -n -m tcp`: every socket row as {pid, command, host, port, family, state}; why is
    "header" or "row" when the text can't be read completely. Each process line (`<time>,<name>.<pid>,...`) comes
    before its sockets (`<time>,tcp4 127.0.0.1:631<->*:*,lo0,Listen,...`); tcp4 addresses end in :<port> and tcp6 ones
    in .<port>, a wildcard is *. A name may hold dots, spaces and commas (nettop doesn't quote them): the pid is the
    trailing digits of everything between the time and the last NETTOP_TAIL fields."""
    lines = text.split("\n")
    if lines[0] != NETTOP_HEAD:
        return None, "header"
    out, pid, command = [], None, ""
    for line in lines[1:]:
        if not line:
            continue
        fields = line.split(",")
        if len(fields) < NETTOP_TAIL + 2:
            return None, "row"
        if "<->" not in fields[1]:                      # a process line
            found = NETTOP_PROCESS_RE.fullmatch(",".join(fields[1:len(fields) - NETTOP_TAIL]))
            if found is None:
                return None, "row"
            command, pid = found.group(1), int(found.group(2))
            continue
        row = NETTOP_SOCKET_RE.fullmatch(fields[1])
        if pid is None or row is None or len(fields) != NETTOP_TAIL + 2 or not fields[3]:
            return None, "row"
        proto, local = row.group(1), row.group(2)
        host, sep, port = local.rpartition(":" if proto == "tcp4" else ".")
        if not sep or not host or not port.isdigit():
            return None, "row"
        out.append({"pid": pid, "command": command, "host": host, "port": int(port),
                    "family": 4 if proto == "tcp4" else 6, "state": fields[3]})
    return out, ""


def parse_nettop(text):
    """`nettop -L 1 -n -m tcp` (macOS 27, where netstat shows a user no TCP socket): every listening TCP socket, root's
    included, as {pid, command, host, port, family}. A header that isn't NETTOP_HEAD, a socket before any process line,
    a process field without its .<pid>, an unknown tcp row or anything else it can't read gives None: nettop then names
    nothing. The name field only labels a row; an owner is always identified by proc_pidpath."""
    sockets = _nettop_sockets(text)[0]
    if sockets is None:
        return None
    return [{k: v for k, v in item.items() if k != "state"} for item in sockets if item["state"] == "Listen"]


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


def lsof_rows():
    """This uid's listening TCP sockets as lsof sees them, authoritative for this uid (spec: naming), or None when lsof
    fails (it exits 1, saying nothing, when it finds none) or prints a row parse_lsof can't read."""
    lsof = shutil.which("lsof", path=SYSTEM_PATH)
    if not lsof:
        return None
    r = _run([lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-F", "pctn"])
    if r is None or r.returncode not in (0, 1) or (r.returncode == 1 and (r.stdout.strip() or r.stderr.strip())):
        return None
    return parse_lsof(r.stdout)


def lsof_listeners():
    """This uid's listeners as (pid, port) pairs, or None when lsof fails."""
    rows = lsof_rows()
    return None if rows is None else {(item["pid"], item["port"]) for item in rows}


def nettop_sockets():
    """(sockets, why): every socket nettop shows, root's included, as _nettop_sockets gives them; why is "run",
    "header" or "row" when they can't be read, and nettop then names nothing."""
    nettop = shutil.which("nettop", path=SYSTEM_PATH)
    if not nettop:
        return None, "run"
    r = _run([nettop, "-L", "1", "-n", "-m", "tcp"])
    if r is None or r.returncode != 0:
        return None, "run"
    return _nettop_sockets(r.stdout)


def _named():
    """(rows, sockets, problems): the naming snapshot, taken before any scan. rows are every listener a source names,
    each with its owner's "uid": this uid's from lsof (authoritative for this uid), other uids' from nettop's Listen
    rows, each uid read by ps (nettop prints none; a pid ps can't place names nothing). sockets are all of nettop's
    rows, any state, to word a refusal. problems is non-empty when the naming failed in any way, and then the whole
    check refuses: lsof or nettop missing, failing, timing out, printing an unknown header or a row it can't read, or
    ps unable to place nettop's listeners."""
    mine = lsof_rows()
    if mine is None:
        return None, None, ["lsof failed, so the listener check fails closed"]
    sockets, why = nettop_sockets()
    if sockets is None:
        return None, None, ["nettop couldn't be read (%s), so the listener check fails closed" % why]
    me = os.getuid()
    listening = [item for item in sockets if item["state"] == "Listen"]
    owners = _owners() if listening else {}
    if listening and not owners:
        return None, None, ["ps failed, so nettop's listeners can't be placed and the listener check fails closed"]
    for item in listening:                              # a pid ps can't place names nothing (see _unplaced)
        item["placed"] = owners.get(item["pid"]) is not None
    others = [dict({k: v for k, v in item.items() if k != "state"}, uid=owners[item["pid"]]) for item in listening
              if owners.get(item["pid"]) not in (None, me)]
    return [dict(item, uid=me) for item in mine] + others, sockets, []


def read_listeners():
    """Every listening TCP socket a source names, root's included, each with its owner's uid: this uid's from lsof,
    other uids' from nettop. None when the naming fails. What is reachable is the loopback scan's to say."""
    return _named()[0]


class _IfAddrs(ctypes.Structure):
    pass


_IfAddrs._fields_ = [("ifa_next", ctypes.POINTER(_IfAddrs)), ("ifa_name", ctypes.c_char_p),
                     ("ifa_flags", ctypes.c_uint), ("ifa_addr", ctypes.c_void_p), ("ifa_netmask", ctypes.c_void_p),
                     ("ifa_dstaddr", ctypes.c_void_p), ("ifa_data", ctypes.c_void_p)]


def _sockaddr(pointer):
    """(family, address, scope_id) of a struct sockaddr, or None for a family other than IPv4 or IPv6. macOS's sockaddr
    starts with sa_len and a one-byte family, Linux's with a two-byte family. macOS (KAME) carries a link-local
    address's scope in bytes 2-3 of the address (fe80:1::1 for fe80::1%lo0): it is moved to the scope id."""
    head = ctypes.string_at(pointer, 2)
    family = head[1] if _on_macos() else int.from_bytes(head, sys.byteorder)
    if family == socket.AF_INET:
        return family, socket.inet_ntop(socket.AF_INET, ctypes.string_at(pointer, 8)[4:8]), 0
    if family == socket.AF_INET6:
        raw = ctypes.string_at(pointer, 28)
        address, scope = bytearray(raw[8:24]), int.from_bytes(raw[24:28], sys.byteorder)
        if address[0] == 0xfe and address[1] & 0xc0 == 0x80 and (address[2] or address[3]):
            scope, address[2:4] = scope or int.from_bytes(address[2:4], "big"), b"\0\0"
        return family, socket.inet_ntop(socket.AF_INET6, bytes(address)), scope
    return None


def _loopback_addresses():
    """[(family, address, scope_id, interface)] for every IPv4 and IPv6 address on a loopback interface (IFF_LOOPBACK),
    from getifaddrs(); None when it can't be read."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        head = ctypes.POINTER(_IfAddrs)()
        if libc.getifaddrs(ctypes.byref(head)) != 0:
            return None
    except (OSError, AttributeError):
        return None
    try:
        out, node = [], head
        while node:
            item = node.contents
            if item.ifa_flags & IFF_LOOPBACK and item.ifa_addr:
                found = _sockaddr(item.ifa_addr)
                if found is not None:
                    out.append(found + ((item.ifa_name or b"").decode("utf-8", "replace"),))
            node = item.ifa_next
        return out
    finally:
        libc.freeifaddrs(head)


def loopback_targets():
    """(targets, notes, refusals) for the scan. targets are [(family, address, scope_id, label)]: every address the
    loopback interface holds by itself, 127.0.0.1, ::1 and fe80::1 scoped to it. Any other address there (an alias such
    as 127.0.0.2) is a refusal that names it: a listener there would be outside what the scan was measured on. ::1
    missing is a note, and the scan skips it; 127.0.0.1 missing, or getifaddrs failing, is a refusal."""
    found = _loopback_addresses()
    if found is None:
        return [], [], ["getifaddrs() failed, so the loopback interface's addresses can't be listed and the listener "
                        "check fails closed"]
    targets, refusals = [], []
    for family, address, scope, name in found:
        label = "%s%%%s" % (address, name) if address.startswith("fe80:") else address
        if address in ("127.0.0.1", "::1") or (address == "fe80::1" and scope):
            targets.append((family, address, scope, label))
        else:
            refusals.append("the loopback interface %s also holds %s (an alias): a listener there is outside what the "
                            "loopback scan covers, so the listener check refuses" % (name, label))
    labels = {target[3] for target in targets}
    notes = [] if "::1" in labels else ["::1 isn't configured on the loopback interface, so the scan skips it"]
    if "127.0.0.1" not in labels:
        refusals.append("127.0.0.1 isn't on the loopback interface, so the listener check fails closed")
    return targets, notes, refusals


def _maxfiles(hard):
    """The ceiling for RLIMIT_NOFILE's soft limit: the hard limit, capped at kern.maxfilesperproc (macOS can't take
    RLIM_INFINITY as a soft limit), or NOFILE_CAP where that can't be read."""
    cap = NOFILE_CAP
    if _on_macos():
        r = _run(["/usr/sbin/sysctl", "-n", "kern.maxfilesperproc"], timeout=10)
        if r is not None and r.returncode == 0 and r.stdout.strip().isdigit():
            cap = int(r.stdout.strip())
    return cap if hard == resource.RLIM_INFINITY else min(hard, cap)


@contextmanager
def _raised_nofile():
    """RLIMIT_NOFILE's soft limit raised to _maxfiles for the scan (a launchd process starts with 256) and restored
    after it, so no worker teamd starts later inherits it. Yields the soft limit in force; never lowers it."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    original, raised = soft, False
    if soft != resource.RLIM_INFINITY:
        want = _maxfiles(hard)
        if soft < want:
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))
                soft, raised = want, True
            except (ValueError, OSError):
                pass
    try:
        yield soft
    finally:
        if raised:
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (original, hard))
            except (ValueError, OSError):
                pass


def scan_loopback(targets, ports=None, batch_s=SCAN_BATCH_S, deadline_s=SCAN_DEADLINE_S):
    """What is reachable: {(label, port): how} for every target and port (1-65535 unless `ports`) where a TCP connect
    isn't refused. `how` is "accepted"; "timed out" (no answer within batch_s: macOS drops a SYN to a port bound but
    not listening, or to a full backlog); "self" (a self-connect: the probe's own address is the target, so it says
    nothing and is probed again); "incomplete" (EADDRNOTAVAIL, EMFILE or ENOBUFS: the scan's own trouble, never the
    port's); or another errno's name. Only ECONNREFUSED is closed. At most SCAN_BATCH probes are in flight, each socket
    is closed at once and nothing is sent. None when a socket can't be opened or the scan runs past deadline_s."""
    ports = list(range(1, 65536) if ports is None else ports)
    end, found = time.monotonic() + deadline_s, {}

    def verdict(key, sock, code):
        if code == errno.ECONNREFUSED:
            return
        if code in INCOMPLETE:
            found[key] = "incomplete"
        elif code != 0:
            found[key] = errno.errorcode.get(code, "errno %d" % code)
        else:
            try:
                mine, theirs = sock.getsockname()[:2], sock.getpeername()[:2]
            except OSError:
                mine, theirs = None, ()
            found[key] = "self" if mine == theirs else "accepted"
    with _raised_nofile() as limit:
        batch = max(16, min(SCAN_BATCH, (SCAN_BATCH + 64 if limit == resource.RLIM_INFINITY else limit) - 64))
        for family, address, scope, label in targets:
            for start in range(0, len(ports), batch):
                if time.monotonic() > end:
                    return None
                selector, pending = selectors.DefaultSelector(), {}
                try:
                    for port in ports[start:start + batch]:
                        try:
                            sock = socket.socket(family, socket.SOCK_STREAM)
                        except OSError:
                            return None
                        sock.setblocking(False)
                        code = sock.connect_ex((address, port, 0, scope) if family == socket.AF_INET6
                                               else (address, port))
                        if code in (errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN):
                            pending[sock] = port
                            selector.register(sock, selectors.EVENT_WRITE)
                        else:
                            verdict((label, port), sock, code)
                            sock.close()
                    stop = time.monotonic() + batch_s
                    while pending:
                        left = stop - time.monotonic()
                        if left <= 0:
                            break
                        for key, _ in selector.select(left):
                            sock = key.fileobj
                            port = pending.pop(sock)
                            selector.unregister(sock)
                            verdict((label, port), sock, sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR))
                            sock.close()
                    for port in pending.values():
                        found[(label, port)] = "timed out"
                finally:
                    for sock in pending:
                        sock.close()
                    selector.close()
    return found


@contextmanager
def _canaries(targets):
    """One listener on an ephemeral port on each scanned address, so the scan can prove it sees: {label: port}, or
    None when one can't be opened (the check then fails closed)."""
    socks, ports = [], {}
    try:
        for family, address, scope, label in targets:
            sock = socket.socket(family, socket.SOCK_STREAM)
            socks.append(sock)
            sock.bind((address, 0, 0, scope) if family == socket.AF_INET6 else (address, 0))
            sock.listen(16)
            ports[label] = sock.getsockname()[1]
    except OSError:
        ports = None
    try:
        yield ports
    finally:
        for sock in socks:
            sock.close()


@contextmanager
def _scan_lock(wait_s=None):
    """Two teamds never scan at once: an exclusive flock on ~/.superyak/team/scan.lock, waited for up to SCAN_LOCK_S.
    Yields whether it was taken."""
    path = teamlib.team_home() / "scan.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        end, held = time.monotonic() + (SCAN_LOCK_S if wait_s is None else wait_s), False
        while not held:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
            except BlockingIOError:
                if time.monotonic() > end:
                    break
                time.sleep(0.2)
        yield held
    finally:
        os.close(fd)


def _probe_one(target, port):
    """One (address, port) again, alone, with REPROBE_S to answer: its "how", or None when it is closed."""
    found = scan_loopback([target], ports=[port], batch_s=REPROBE_S, deadline_s=REPROBE_S + 5)
    return "incomplete" if found is None else found.get((target[3], port))


def _reprobe(keys, targets):
    """Each (label, port) in keys probed again one at a time: {key: how} for those not closed. A self-connect or an
    incomplete probe is tried up to REPROBE_TRIES times; if it stays so, it stays so (and the check refuses)."""
    by_label = {target[3]: target for target in targets}
    out = {}
    for label, port in sorted(keys, key=lambda key: (key[1], key[0])):
        how = None
        for _ in range(REPROBE_TRIES):
            how = _probe_one(by_label[label], port)
            if how not in ("self", "incomplete"):
                break
        if how is not None:
            out[(label, port)] = how
    return out


def _covers(item, target):
    """Whether a named Listen row covers this scanned (family, address, scope_id, label): a row on that address, on
    its family's wildcard (* or 0.0.0.0 for IPv4, * or :: for IPv6), or, for 127.0.0.1, on its IPv4-mapped form. Never
    the other family's wildcard: a dual-stack socket (tcp6 *) doesn't cover 127.0.0.1 (spec, Known limits). A row on
    the loopback interface's link-local address covers it only by its scoped label. A * without its family covers
    nothing: parse_lsof refuses one (ruling 2b6e272b)."""
    family, address, scope, label = target
    host, kind, four = item["host"], item.get("family"), family == socket.AF_INET
    if host == "*":
        return kind == (4 if four else 6)
    if host in ("0.0.0.0", "::"):
        return four == (host == "0.0.0.0")
    if "%" in host:
        return host == label
    if four:
        return host in (address, "::ffff:" + address)
    return host == address and not address.startswith("fe80:")


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
    A socket bound only to another specific address (the tailnet, say) is unreachable, so another user's doesn't
    count; while a lane is live, this user's does (I3: a lane process that cleared its environment looks like any
    other). A lane's own port beyond loopback always fails, and a listener in a lane's block must be that lane's (its
    CLAUDE_CODE_TMPDIR) or its broker's (TMPDIR=<lane>/b) (I4: lanes share localhost). What is reachable is the
    loopback scan's to say, and lsof and nettop only name owners (_check). Any doubt fails too: lsof, nettop or ps
    failing, a scan that can't see or finish, a reachable (address, port) nobody names, a named listener the scan finds
    closed, a process that can't be identified, an unreadable list or registry, any error at all. Returns (ok,
    problems).
    The check is machine-wide, so it takes no team."""
    try:
        return _check(load_approved(), live_lanes())
    except LaneRefused as e:
        return False, [str(e)]
    except ValueError as e:                             # anything unreadable fails closed, never raises
        return False, ["the listener check could not read what it was given (%s), so it fails closed"
                       % e.__class__.__name__]
    except Exception as e:                              # deep JSON, a lock that errs, a bug: closed, never raised
        return False, ["the listener check failed (%s), so it fails closed" % e.__class__.__name__]


def _lane_process(pid, tmps):
    """Whether this pid's environment holds exactly CLAUDE_CODE_TMPDIR=<a live lane's tmp folder>."""
    env = _environ(pid) or []
    return any("CLAUDE_CODE_TMPDIR=" + tmp in env for tmp in tmps)


def _lanes_own(pid, key):
    """I4: whether this pid belongs in lane `key`'s block: its environment holds exactly that lane's
    CLAUDE_CODE_TMPDIR (the worker's servers), or exactly TMPDIR=<that lane>/b (its broker, whose b/ is named with the
    parent resolved, as lane_text names it). An environment that can't be read belongs to no lane."""
    parent = _parent_path()
    env = _environ(pid) or []
    wanted = {"CLAUDE_CODE_TMPDIR=" + str(parent / key / "tmp"), "TMPDIR=" + str(parent / key / "b"),
              "TMPDIR=" + os.path.join(os.path.realpath(parent), key, "b")}
    return any(entry in wanted for entry in env)


def _owners():
    """{pid: uid} for every process, from ps ({} when ps can't say: then no owner is known, which fails closed)."""
    return {pid: uid for pid, ppid, pgid, uid in _process_table()}


def _unnamed(found, targets, rows):
    """The scanned (label, port)s no named row covers: {key: how}."""
    by_label = {target[3]: target for target in targets}
    return {(label, port): how for (label, port), how in found.items()
            if not any(item["port"] == port and _covers(item, by_label[label]) for item in rows)}


def _unnamed_problems(unnamed, targets, sockets):
    """One refusal per unnamed (address, port), at most 20 listed, each quoting any row nettop shows for that address
    and port in another state (a Closed one for a socket bound but not listening), by pid and proc_pidpath: wording
    only, never a pass (ruling 4db21a5e)."""
    by_label = {target[3]: target for target in targets}
    problems = []
    for label, port in sorted(unnamed, key=lambda key: (key[1], key[0]))[:20]:
        how = unnamed[(label, port)]
        what = ("accepts connections" if how == "accepted" else "doesn't answer a connect (it timed out)"
                if how == "timed out" else "answers a connect with %s" % how)
        seen = ["%s (pid %d, %s) holds it in nettop's %s state" % (item["command"] or "?", item["pid"],
                                                                     pid_path(item["pid"]) or "?", item["state"])
                for item in sockets or [] if item["port"] == port and _covers(item, by_label[label])]
        problems.append("port %d on %s %s, and no listener there is named (lsof for this user, nettop for others), so "
                        "it can't be identified%s%s" % (port, label, what, "; " if seen else "", "; ".join(seen)))
    if len(unnamed) > 20:
        problems.append("and %d more reachable ports nobody names" % (len(unnamed) - 20))
    return problems


def _disagreeing(rows, targets, found):
    """{(label, port): [rows]} for each scanned address a named Listen row covers, on a loopback address or a wildcard,
    that the scan found closed: the scan and the naming disagree there."""
    out = {}
    for item in rows:
        if not reachable(item["host"]):
            continue
        for target in targets:
            key = (target[3], item["port"])
            if _covers(item, target) and key not in found:
                out.setdefault(key, []).append(item)
    return out


def _unplaced(sockets, targets, found):
    """nettop's Listen rows whose pid ps couldn't place, covering a reachable (address, port): an owner that vanished,
    or one ps can't see, must never slip past because another row covers the same address (ruling 2b6e272b)."""
    by_label = {target[3]: target for target in targets}
    return [item for item in sockets or [] if item.get("state") == "Listen" and item.get("placed") is False
            and any(port == item["port"] and _covers(item, by_label[label]) for label, port in found)]


def _scan_with_canaries(targets):
    """(found, problems): the full scan, with a canary listening on each scanned address that the scan must reach
    (else "the scan can't see": something answers teamd's connects with RST). A scan that can't finish is tried once
    more. The canaries' own ports are left out of what is found."""
    with _canaries(targets) as canaries:
        if canaries is None:
            return None, ["a canary couldn't listen on the loopback interface, so the scan can't be checked and the "
                          "listener check fails closed"]
        found = scan_loopback(targets)
        if found is None:
            found = scan_loopback(targets)
        if found is None:
            return None, ["the loopback scan couldn't finish (a socket couldn't be opened, or it ran past %d s), so "
                          "the listener check fails closed" % SCAN_DEADLINE_S]
        blind = [label for label, port in sorted(canaries.items()) if (label, port) not in found]
        if blind:
            return None, ["the scan can't see: it didn't reach its own canary on %s (something answers teamd's "
                          "connects there with a reset), so the listener check fails closed" % ", ".join(blind)]
        return {key: how for key, how in found.items() if canaries.get(key[0]) != key[1]}, []


def _judge(rows, approved, lanes):
    """The rules on every named row a lane could reach (D10, D11, I3, I4): this uid's rows anywhere (I3 beyond
    loopback while a lane is live), another uid's unless it is on a specific non-loopback address. Returns problems."""
    tmps = [str(_parent_path() / key / "tmp") for _, key in lanes]
    me, problems, paths, lane_pids = os.getuid(), [], {}, {}
    unique = {(item["pid"], item["host"], item["port"]): item for item in rows}
    for item in sorted(unique.values(), key=lambda item: (item["port"], item["pid"], item["host"])):
        port, host, pid = item["port"], item["host"], item["pid"]
        can_reach = reachable(host)
        if item["uid"] != me and not can_reach:         # another uid's on one specific address beyond loopback
            continue
        block = next((key for base, key in lanes if base <= port < base + BLOCK), None)
        in_lane = block is not None
        is_lane, beyond = False, None
        if not in_lane and not is_loopback(host):       # a lane's process exposes the app to the network, however
            if pid not in lane_pids:                    # it is reached: checked before the reachability skip
                lane_pids[pid] = _lane_process(pid, tmps)
            is_lane = lane_pids[pid]
        if not in_lane and not is_lane and not can_reach:
            # This uid's, bound to one other address: no lane can reach it, but while a lane is live it counts (I3:
            # a lane process that cleared its environment looks like any other), unless it is an approved Apple
            # program (sharingd keeps AirDrop on awdl0 as the user), which no lane process can be.
            if not lanes:
                continue
            beyond = "as this user while a lane runs"
        if pid not in paths:
            paths[pid] = pid_path(pid)
        exe = paths[pid]
        name = "%s (pid %d)" % (item["command"] or (os.path.basename(exe) if exe else "?"), pid)
        launchd = ", launchd holds it for a socket-activated job" if pid == 1 else ""
        if beyond:
            if exe is not None and exe in approved:     # an approved Apple program passes on any address it uses (D11)
                continue
            problems.append("%s listens on %s port %d, beyond loopback, %s (%s)" % (name, host, port, beyond, exe or "?"))
            continue
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
            elif not _lanes_own(pid, block):            # I4: lanes share localhost; a block is its lane's alone
                problems.append("%s listens on %s port %d, in lane %s's block, but isn't that lane's or its broker "
                                "(%s)" % (name, host, port, block, exe))
        elif exe not in approved:
            problems.append("%s listens on port %d (%s)%s" % (name, port, exe, launchd))
    return sorted(set(problems))


def _check(approved, lanes):
    """Name, judge, then scan (spec amendment of 2026-10-09, revision 2). Naming only adds refusals: a scanned
    (address, port) passes only when a named row covers it and every covering row passes."""
    targets, notes, refusals = loopback_targets()
    if refusals:
        return False, refusals
    rows, sockets, problems = _named()
    if problems:
        return False, problems
    problems = _judge(rows, approved, lanes)
    if problems:                                        # name first: a waiting lane doesn't scan Andy's services
        return False, problems
    with _scan_lock() as held:
        if not held:
            return False, ["another listener check's scan held the scan lock for %d s, so this one fails closed"
                           % SCAN_LOCK_S]
        found, problems = _scan_with_canaries(targets)
        if problems:
            return False, problems
        disagree = _disagreeing(rows, targets, found)
        suspect = ({key for key, how in found.items() if how != "accepted"} | set(_unnamed(found, targets, rows))
                   | set(disagree))
        if suspect:                                     # before the verdict: probe again, alone, and name again
            again = _reprobe(suspect, targets)
            found = {key: how for key, how in found.items() if key not in suspect}
            found.update(again)
            rows, sockets, problems = _named()
            if problems:
                return False, problems
            problems = _judge(rows, approved, lanes)
            if problems:
                return False, problems
            disagree = {key: items for key, items in _disagreeing(rows, targets, found).items() if key in disagree}
    if _unplaced(sockets, targets, found):              # name once more; still unplaced, it refuses
        rows, sockets, problems = _named()
        if problems:
            return False, problems
        problems = _judge(rows, approved, lanes)
        if problems:
            return False, problems
        ghosts = _unplaced(sockets, targets, found)
        if ghosts:
            return False, sorted({"nettop shows pid %d (%s) listening on %s port %d, which a lane can reach, but ps "
                                  "can't place it, so the listener check fails closed"
                                  % (item["pid"], item["command"] or "?", item["host"], item["port"]) for item in ghosts})
    problems = ["the scan is incomplete at %s port %d (%s), so the listener check fails closed" % (label, port, how)
                for (label, port), how in sorted(found.items(), key=lambda kv: (kv[0][1], kv[0][0]))
                if how in ("self", "incomplete")]
    unnamed = {key: how for key, how in _unnamed(found, targets, rows).items() if how not in ("self", "incomplete")}
    problems += _unnamed_problems(unnamed, targets, sockets)
    for (label, port), items in sorted(disagree.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        problems.append("scan and naming disagree: %s says %s listens on %s port %d, but the scan finds it closed "
                        "twice" % (" and ".join("lsof" if item["uid"] == os.getuid() else "nettop" for item in items[:1]),
                                   ", ".join("%s (pid %d)" % (item["command"] or "?", item["pid"]) for item in items),
                                   label, port))
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
    """A regular file's text, read without following a link, and without waiting on a FIFO planted in its place."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
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


def pinned_playwright(repo, base, fetch=None, verify=True):
    """~/.superyak/team/broker/playwright-core-<version>/, fetched from the npm registry the first time. The tarball is
    checked against the integrity hash in the base commit's lockfile, never the registry's own claim. A mismatch
    anywhere refuses the lane. Its cli.js runs unsandboxed as the installer, so a reused folder is checked again: owner
    and mode (it and every folder above), the stamp, and (unless `verify` is False: a waiting lane's retry, whose
    broker won't start yet) the manifest hash recorded at unpack time."""
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
            if verify and manifest_hash(dest, ignore=(STAMP, STAMP_MANIFEST)) != was:
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
        raise LaneRefused("no manifest hash is recorded for %s %s on %s: a person records the browser's manifest "
                          "after `lane_acceptance.py --self-check-only` passes" % (SHELL, revision, platform_key()),
                          log="the manifest hash of %s %s on %s, for Andy to record in "
                              "team/superyak_team/lane/browsers.json once lane_acceptance.py --self-check-only passes: "
                              "%s" % (SHELL, revision, platform_key(), actual))
    if recorded != actual:
        raise LaneRefused("%s doesn't match the manifest hash recorded for %s %s on %s. If nobody changed it, remove "
                          "that folder and the next lane installs it again" % (folder, SHELL, revision, platform_key()),
                          log="%s %s on %s: recorded manifest hash %s, found %s" % (SHELL, revision, platform_key(),
                                                                                 recorded, actual))
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
    BROKEN. Each dotfile is taken by its real path, which must lie under the real $HOME (a refused read of a file
    elsewhere says nothing about $HOME). link_dotfile has its own variable and also needs a regular file (not a link)
    on the lane's device (`lane_dir`), or the link would fail with EXDEV, a reason unrelated to the wall.
    {probe: (variable for the probe or None, path or None)}."""
    home = Path.home()
    real_home = os.path.realpath(home)

    def usable(path, mode):
        return os.access(os.path.realpath(path), mode)

    def in_home(path):
        real = os.path.realpath(path)
        return Path(real) if real.startswith(real_home + os.sep) and os.path.isfile(real) else None

    def first(names, mode):
        return next((in_home(home / n) for n in names if in_home(home / n) and usable(home / n, mode)), None)
    folder = lambda path, mode: path if path and Path(path).is_dir() and usable(path, mode) else None
    targets = {name: (None, Path(path) if os.path.isfile(path) and usable(path, os.X_OK) else None)
               for name, path in PROBE_PROGRAMS.items()}
    if not CALCULATOR_APP.is_dir():
        targets["exec_open_calculator"] = (None, None)
    def linkable():
        for n in (".zshrc", ".bashrc", ".profile", ".gitconfig"):
            p = home / n
            if p.is_file() and not p.is_symlink() and usable(p, os.R_OK) and in_home(p):
                if lane_dir is None or _device(p) == _device(lane_dir):
                    return in_home(p)
                return None
        return None
    read, write = os.R_OK | os.X_OK, os.W_OK | os.X_OK
    return {**targets,
            "read_dotfile": ("PROBE_DOTFILE", first((".zshrc", ".bashrc", ".profile", ".gitconfig"), os.R_OK)),
            "link_dotfile": ("PROBE_LINK_DOTFILE", linkable()),
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


def prepare_broker(repo, base_commit, worktrees, fetch=None, verify=True):
    """Everything a broker needs before it starts: lane_node, the pinned Playwright and the checked headless shell.
    One teamd installs at a time. With verify=False (before a lane's listener check, which may make it wait and retry
    every 30 s) an install that is already there is made sure of without hashing it; the hashing runs with
    verify=True, once the check has passed and just before the broker starts. Returns (node_bin, pw_dir, shell_dir)."""
    node_bin = check_lane_node(teamlib.load_config().get("lane_node"), worktrees)
    with install_lock():  # Task 5 fix round: reentrant; teamlib.locked on the same file would deadlock
        pw_dir = pinned_playwright(repo, base_commit, fetch, verify=verify)
        shell_dir, revision = install_headless_shell(node_bin, pw_dir)
        if verify:
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
    if not cleanup_processes(Path(path), None):
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
    pids |= family(proc.pid)[0]                         # before poll(), which may reap it and free its pid for reuse
    exited = proc.poll()
    stop_broker(broker)
    cleanup_processes(Path(path), None)                 # node is gone: what it started is found by b/ now (no env is passed here)
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


def _lsof_descriptors(text):
    """`lsof -F pfitDn` output as (pid, fd, type, inode, device, name) for every descriptor that has a name. Fields of
    one descriptor follow its `f` line, in any order."""
    out, pid, current = [], None, None

    def finish():
        if current is not None and pid is not None and current.get("n") is not None:
            out.append((pid, current.get("f"), current.get("t"), current.get("i"), current.get("D"), current["n"]))
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            finish()
            pid, current = int(line[1:]), None
        elif line.startswith("f"):
            finish()
            current = {"f": line[1:]}
        elif current is not None and line[:1] in ("t", "i", "D", "n"):
            current[line[0]] = line[1:]
    finish()
    return out


def _lstat_below(anchor, parts):
    """lstat of anchor/<parts...> without following any link: anchor, then each component down to the last, is opened
    with O_NOFOLLOW|O_DIRECTORY through the one before, and the last is stat'ed with dir_fd and follow_symlinks=False.
    None if any step is missing or is a link, or a name climbs out (. or ..). Nothing here is resolved by name."""
    if not parts or any(part in (".", "..") for part in parts):
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fds = []
    try:
        fds.append(os.open(anchor, flags))
        for part in parts[:-1]:
            fds.append(os.open(part, flags, dir_fd=fds[-1]))
        return os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False)
    except OSError:
        return None
    finally:
        for fd in fds:
            os.close(fd)


def _lstat_in_b(path, rel):
    """lstat of <lane>/b/<rel...> without following any link: the walk (_lstat_below) starts at the lane's parent. None
    if any step is missing or is a link."""
    parent = _parent_path()
    if any(part in (".", "..") for part in rel):          # a name that climbs out of b/ is not evidence
        return None
    try:
        parts = list(Path(path).relative_to(parent).parts) + ["b"] + list(rel)
    except ValueError:
        return None
    return _lstat_below(parent, parts)


def _counts_as_the_lanes(path, prefixes, fd, kind, inode, device, name):
    """Whether an open descriptor is evidence that its process belongs to the lane. Only names under <lane>/b count: the
    worker can write tmp/ and npm-cache/ (it can swap folders for links, rename its own folders in, link a stranger's
    file there), so paths in them are never evidence; membership there comes only from the exact CLAUDE_CODE_TMPDIR in
    the environment or a listening port in the block. Under b/, the name is walked from the lane without following a
    link, and the file must be a regular file with st_nlink == 1 (a cwd, a folder), and both its st_dev and st_ino must
    equal lsof's D and i fields: macOS lsof names a hard-linked file by the path the kernel looked up last. A
    descriptor without an inode and device is never evidence."""
    for prefix in prefixes:
        if name == prefix + "/b" or name.startswith(prefix + "/b/"):
            rel = [x for x in name[len(prefix) + 3:].split("/") if x]
            break
    else:
        return False
    if not (inode or "").isdigit() or not device:
        return False
    try:
        dev = int(device, 16) if device.lower().startswith("0x") else int(device)
    except ValueError:
        return False
    st = _lstat_in_b(path, rel)
    if st is None or (st.st_dev, st.st_ino) != (dev, int(inode)):
        return False
    if fd == "cwd":
        return stat.S_ISDIR(st.st_mode)
    return stat.S_ISREG(st.st_mode) and st.st_nlink == 1


def lane_pids(path, base):
    """Processes of this uid that listen on a port in the lane's block (base None: no block was allocated), or have
    their cwd or an open file under <lane>/b. The files come from one `lsof -F pfitDn` over all of this uid's open
    files; only names under b/, which the worker can't write, count, and each is re-checked without following a link
    (_counts_as_the_lanes). Paths under tmp/ and npm-cache/ are never evidence; env_pids finds what lives there. The
    lane folder is never walked. None when lsof or ps can't say."""
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
        r = _run([lsof, "-nP", "-a", "-u", uid, "-F", "pfitDn"])
        if r is None or r.returncode != 0:              # teamd always has open files: 1 means an error here
            return None
        pids |= {pid for pid, fd, kind, inode, device, name in _lsof_descriptors(r.stdout)
                 if _counts_as_the_lanes(path, prefixes, fd, kind, inode, device, name)}
    rows = _process_table()
    if not rows:                                         # without ps, teamd's own parents can't be spared
        return None
    return pids - _spared(rows)


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


# What a turn leaves that its environment can't show. macOS hides an Apple program's environment from KERN_PROCARGS2
# (a setsid child that execs /bin/sleep shows none), so env_pids can't see it. Two more kinds of evidence, both only for
# processes of this uid under the turn's Seatbelt profile (_turn_sandboxed), never teamd or above it, never the broker:
# (b) the turn's tree, sampled while the turn runs (turn_tree), each process by pid and start time;
# (a) this uid's orphans (ppid 1) started since the turn began whose cwd is in its worktree or lane folder.
# Spec, Known limits: what chdirs out and orphans between two samples is missed.
PROC_PIDTBSDINFO, PROC_BSDINFO_SIZE = 3, 136          # struct proc_bsdinfo; its start time is at 120 (s) and 128 (us)
# libsystem_sandbox exports SANDBOX_CHECK_NO_REPORT as a symbol: 0x40000000 on macOS 27 (read with ctypes, 2026-10-09).
SANDBOX_FILTER_NONE, SANDBOX_FILTER_PATH, SANDBOX_CHECK_NO_REPORT = 0, 1, 0x40000000
_LIBSYSTEM = {}                     # {"lib": libSystem, loaded once; or None when it or a symbol couldn't load}


def _on_macos():
    """Whether this is macOS, from the system itself: the tests' mac fixture says "darwin" through sys.platform, and
    that must not decide whether there is a Seatbelt to ask."""
    return platform.system() == "Darwin"


def _libsystem():
    """macOS's libSystem with proc_pidinfo and sandbox_check typed, loaded once. None off macOS; on macOS, None when
    it or either symbol can't load, and the callers then say they can't tell (_turn_sandboxed, turn_leftovers),
    never that this isn't macOS."""
    if not _on_macos():
        return None
    if "lib" not in _LIBSYSTEM:
        try:
            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            libc.proc_pidinfo.restype = ctypes.c_int
            libc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            libc.sandbox_check.restype = ctypes.c_int
            libc.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]   # then a path, variadic
        except (OSError, AttributeError):
            libc = None
        _LIBSYSTEM["lib"] = libc
    return _LIBSYSTEM["lib"]


def _started(pid):
    """When pid started, as a time.time() value, or None when it is gone or can't be read: proc_pidinfo on macOS (to
    the microsecond, None when libSystem is broken), /proc elsewhere (to the clock tick)."""
    if _on_macos():
        libc = _libsystem()
        if libc is None:
            return None
        buf = ctypes.create_string_buffer(PROC_BSDINFO_SIZE)
        try:
            if libc.proc_pidinfo(int(pid), PROC_PIDTBSDINFO, 0, buf, PROC_BSDINFO_SIZE) != PROC_BSDINFO_SIZE:
                return None
        except (AttributeError, ctypes.ArgumentError, OSError):
            return None
        sec, usec = struct.unpack_from("QQ", buf.raw, 120)
        return sec + usec / 1e6
    try:
        fields = Path("/proc/%d/stat" % int(pid)).read_text().rpartition(")")[2].split()
        return _btime() + int(fields[19]) / _ticks_per_second()        # field 22, starttime, in clock ticks
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _btime():
    """The boot time /proc/stat gives, in whole seconds since the epoch."""
    return next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                if line.startswith("btime "))


def _ticks_per_second():
    return os.sysconf("SC_CLK_TCK")


def started_clock():
    """Now, in _started's frame: what _started would say of a process starting now, so a turn's start taken with it is
    never later than its processes' starts. macOS: the wall clock, which proc_pidinfo's start is. Elsewhere _started is
    btime, whole seconds, plus clock ticks since boot, up to 1 s off the wall clock: so btime plus CLOCK_BOOTTIME (what
    starttime counts) cut to whole ticks. No tolerance, which would let a process from before the turn count. When /proc
    can't say, the wall clock: a later start only drops orphans, never takes one."""
    if _on_macos():
        return time.time()
    try:
        hz = _ticks_per_second()
        return _btime() + math.floor(time.clock_gettime(time.CLOCK_BOOTTIME) * hz) / hz
    except (OSError, ValueError, AttributeError, StopIteration):
        return time.time()


def _turn_sandboxed(pid, writable, unreadable=()):
    """Whether pid runs under the turn's Seatbelt profile, as far as sandbox_check can tell: it is sandboxed, may write
    every folder in `writable` (the turn's worktree and its lane's tmp/) and may read none in `unreadable` (its lane's
    b/, which the turn's profile denies and most other sandboxes allow). Andy's shell and what claude starts outside
    its sandbox (its MCP servers) aren't sandboxed. Each path is asked about by its real path; a missing one answers
    1. A gone pid (zombie, reaped or never used) answers 1 to everything on macOS 27 (measured 2026-10-09), so it reads
    as denied: False. Any answer but 0 or 1 is False for a pid that is gone, so one gone pid never holds up a whole
    cleanup, and None (can't say) for one still running. False off macOS; None on macOS when libSystem is broken."""
    if not _on_macos():
        return False
    libc = _libsystem()
    if libc is None:
        return None
    asks = [(None, None)] + [(b"file-write-data", f) for f in writable] + [(b"file-read-data", f) for f in unreadable]
    for operation, folder in asks:
        try:
            if folder is None:
                answer = libc.sandbox_check(int(pid), None, SANDBOX_FILTER_NONE)
            else:
                answer = libc.sandbox_check(int(pid), operation, SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT,
                                            ctypes.c_char_p(os.fsencode(os.path.realpath(folder))))
        except (AttributeError, ctypes.ArgumentError, OSError):
            return None
        if answer not in (0, 1):
            return None if _alive(pid) else False
        denied = answer == 1
        if (folder is None and not denied) or (operation == b"file-write-data" and denied) or (
                operation == b"file-read-data" and not denied):
            return False                # not sandboxed, may not write the turn's folders, or may read b/
    return True


def turn_tree(root):
    """A running turn's processes as {pid: start}: root's descendants (not root, claude itself) that are this uid's.
    {} when root isn't teamd's own child, so not a turn teamd started, or when ps can't say: a missed sample is made up
    by the next one and, when the turn ends, by the orphan rule."""
    rows = _process_table()
    if not any(pid == root and ppid == os.getpid() for pid, ppid, pgid, uid in rows):
        return {}
    children = {}
    for pid, ppid, pgid, uid in rows:
        if uid == os.getuid():
            children.setdefault(ppid, []).append(pid)
    tree, stack = set(), [root]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in tree and child != root:
                tree.add(child)
                stack.append(child)
    starts = {pid: _started(pid) for pid in tree}
    return {pid: start for pid, start in starts.items() if start is not None}


def _cwd_in(folders, inode, device, name):
    """Whether a cwd lsof names is a folder under one of `folders`: the name below the folder is walked from the
    folder's real path without following a link (_lstat_below), and the folder found must have lsof's device and
    inode (the hardlink fix's rule). A cwd without an inode and device is never evidence."""
    if not (inode or "").isdigit() or not device:
        return False
    try:
        dev = int(device, 16) if device.lower().startswith("0x") else int(device)
    except ValueError:
        return False
    for folder in folders:
        real = os.path.realpath(folder)
        for prefix in {str(folder), real}:
            if name == prefix or name.startswith(prefix + "/"):
                rel = [x for x in name[len(prefix):].split("/") if x]
                st = _lstat_below(real, rel) if rel else _lstat_below(os.path.dirname(real), [os.path.basename(real)])
                if st is not None and stat.S_ISDIR(st.st_mode) and (st.st_dev, st.st_ino) == (dev, int(inode)):
                    return True
    return False


def _orphans_in(folders, began, mine):
    """(a) This uid's orphans (ppid 1, in `mine` {pid: ppid}) that started at or after `began` and whose cwd is under
    one of `folders`, as {pid: start}. {} without a start; None when lsof can't say."""
    if began is None:
        return {}
    starts = {pid: _started(pid) for pid, ppid in mine.items() if ppid == 1}
    candidates = {pid: start for pid, start in starts.items() if start is not None and start >= began}
    if not candidates:
        return {}
    lsof = shutil.which("lsof", path=SYSTEM_PATH)
    if not lsof:
        return None
    r = _run([lsof, "-nP", "-a", "-p", ",".join(str(pid) for pid in sorted(candidates)), "-d", "cwd", "-F", "pfitDn"])
    if r is None or r.returncode not in (0, 1):         # 1: one of them exited meanwhile
        return None
    return {pid: candidates[pid] for pid, fd, kind, inode, device, name in _lsof_descriptors(r.stdout)
            if fd == "cwd" and pid in candidates and _cwd_in(folders, inode, device, name)}


def turn_leftovers(seen, folders, began, writable, spared=(), unreadable=()):
    """What a turn left that its environment can't show, as {pid: start}: (b) a process seen in its tree (`seen`,
    {pid: start}) still running with the same start time, so a reused pid is spared, and (a) _orphans_in its
    `folders` since `began`. Only this uid's, only under the turn's profile (_turn_sandboxed with `writable` and
    `unreadable`), never teamd or a process above it, never `spared` (the broker's). None when ps, lsof or the sandbox
    can't say, and on macOS when libSystem is broken, even with nothing to ask about."""
    if _on_macos() and _libsystem() is None:
        return None
    rows = _process_table()
    if not rows:
        return None
    skip = _spared(rows) | set(spared)
    mine = {pid: ppid for pid, ppid, pgid, uid in rows if uid == os.getuid() and pid not in skip}
    found = {pid: start for pid, start in seen.items() if pid in mine and _started(pid) == start}
    orphans = _orphans_in(folders, began, mine)
    if orphans is None:
        return None
    found.update(orphans)
    out = {}
    for pid, start in found.items():
        sandboxed = _turn_sandboxed(pid, writable, unreadable)
        if sandboxed is None:
            return None
        if sandboxed:
            out[pid] = start
    return out


def _signal(pids, sig):
    """pids is {pid: start or None}: one with a start is signalled only while _started still says it (checked just
    before, so a pid reused since it was found is never signalled); None (found by environment, port or file) is
    signalled as found."""
    for pid, start in pids.items():
        if start is None or _started(pid) == start:
            _kill(pid, sig)


def _merged(pids, extra):
    """{pid: None} for what was found by environment, port or file, with `extra`'s starts laid over it."""
    out = dict.fromkeys(pids)
    out.update(extra)
    return out


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


def cleanup_processes(path, base, broker=None, env=None, extra=None):
    """When a lane ends (and before a broker starts in its b/): the broker, then every process found by lane_pids
    (Playwright's detached webServer and dev servers, which killing the worker's group misses), with env as
    (name, value) by env_pids, and with extra by what it gives ({pid: start}, or None when it can't say: teamd's
    turn_leftovers). SIGTERM and after KILL_GRACE_S SIGKILL, then a second look for anything started meanwhile. True
    once finished; False when lsof, ps or extra couldn't say, so the block stays held."""
    if broker is not None:
        stop_broker(broker)

    def found():
        pids = lane_pids(path, base)
        more = env_pids(*env) if env else set()
        given = extra() if extra is not None else {}
        return None if pids is None or more is None or given is None else _merged(pids | more, given)
    pids = found()
    if pids is None:
        return False
    _signal(pids, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    again = found()                                      # only what still matches: a pid that exited may be reused
    if again is None:
        return False
    _signal(again, signal.SIGKILL)
    return True


def cleanup_env(env, extra=None):
    """End whatever still carries env=(name, value), and with extra whatever it gives ({pid: start}, or None when it
    can't say: teamd's turn_leftovers), and nothing else: no ports, no folder. A turn's setsid leftovers carry the
    lane's CLAUDE_CODE_TMPDIR, unless macOS hides their environment; the broker doesn't. SIGTERM, then SIGKILL after
    KILL_GRACE_S for what still matches. True when ps (and extra) could say."""
    def found():
        pids = env_pids(*env)
        given = extra() if extra is not None else {}
        return None if pids is None or given is None else _merged(pids, given)
    pids = found()
    if pids is None:
        return False
    _signal(pids, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    again = found()
    _signal(again or {}, signal.SIGKILL)
    return again is not None


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
    if not isinstance(text, str):
        return text
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "[lane secret]")
    return text


ENDPOINT_RE = re.compile(r"(ws://127\.0\.0\.1:\d+/)[0-9a-f]{64}")      # a dead teamd's secret, by its shape


def scrub_file(path, secrets_, shaped=False):
    """Rewrite a file teamd keeps (events.jsonl, stderr.log) without the secret. Only after the turn has ended.
    With shaped, also any endpoint of the secret's shape: the sweep doesn't know the dead teamd's secrets."""
    path = Path(path)
    if not (secrets_ or shaped) or not path.is_file() or path.is_symlink():
        return
    try:
        text = path.read_text(errors="replace")
        clean = scrub(text, secrets_)
        if shaped:
            clean = ENDPOINT_RE.sub(r"\1[lane secret]", clean)
        if clean != text:
            tmp = path.with_name(path.name + ".scrub")
            _write_text(tmp, clean, 0o600)
            os.replace(tmp, path)
    except OSError as e:
        raise LaneRefused("%s can't be scrubbed of the lane's secret (%s)" % (path, e.strerror or e))


# ---------- a turn the last teamd started (teamd.sweep_lanes) ----------

def _etime_seconds(text):
    """ps's etime ([[dd-]hh:]mm:ss) in seconds, or None."""
    days, _, rest = text.strip().rpartition("-")
    parts = rest.split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts) or (days and not days.isdigit()):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds + int(days or 0) * 86400


def lost_turn(pid, cwd, started, now=None):
    """Whether pid is still the turn a previous teamd started: the leader of its own process group, running claude,
    with its cwd the worker's folder and a start time within 30 s of the turn's. A reused pid can't pass all four,
    so Andy's own claude is never killed."""
    if not pid or not started:
        return False
    r = _run(["/bin/ps", "-ww", "-o", "pgid=,etime=,command=", "-p", str(pid)], timeout=10)
    fields = r.stdout.split(None, 2) if r is not None and r.returncode == 0 else []
    if len(fields) != 3 or fields[0] != str(pid) or "claude" not in fields[2]:
        return False
    age = _etime_seconds(fields[1])
    now = time.time() if now is None else now
    if age is None or abs((now - age) - started) > 30:
        return False
    lsof = shutil.which("lsof", path=SYSTEM_PATH)
    r = _run([lsof, "-nP", "-a", "-p", str(pid), "-d", "cwd", "-F", "n"], timeout=10) if lsof else None
    names = [line[1:] for line in (r.stdout.splitlines() if r is not None else []) if line.startswith("n")]
    return bool(names) and os.path.realpath(names[0]) == os.path.realpath(cwd)


# ---------- advisory results (spec: What the lane must allow) ----------

ADVISORY_TAG = b"@lane-advisory"
ADVISORY_MAX_FILES, ADVISORY_MAX_LINE = 20, 160
ADVISORY_MAX_CHANGED, ADVISORY_TIMEOUT_S = 500, 60
ADVISORY_MAX_BLOB = 1 << 20                    # bytes: a bigger blob is skipped, and the lead told to look by hand
ADVISORY_MAX_SKIPPED = 5


def _cat_file_header(line, sha):
    """`<sha> blob <size>` for this sha, as its size; anything else is output this check doesn't understand."""
    header = line.split()
    if len(header) != 3 or header[0].decode("ascii", "replace") != sha or header[1] != b"blob" \
            or not header[2].isdigit():
        raise RuntimeError("git cat-file output was not understood for %s" % sha)
    return int(header[2])


def _cat_file_sizes(read, shas):
    """Parse `git cat-file --batch-check` output (`<sha> <type> <size>` per object, in order) into {sha: size}."""
    lines = read.split(b"\n")
    if len(lines) != len(shas) + 1 or lines[-1] != b"":
        raise RuntimeError("git cat-file --batch-check output was not understood")
    return {sha: _cat_file_header(line, sha) for sha, line in zip(shas, lines)}


def _cat_file_batch(read, shas):
    """Parse `git cat-file --batch` output (`<sha> <type> <size>\\n<content>\\n` per object) into {sha: bytes}: each
    blob is taken by its size, never by its lines, and output cut short is an error."""
    blobs, pos = {}, 0
    for sha in shas:
        end = read.find(b"\n", pos)
        if end < 0:
            raise RuntimeError("git cat-file output was not understood for %s" % sha)
        size = _cat_file_header(read[pos:end], sha)
        if end + 1 + size + 1 > len(read) or read[end + 1 + size:end + 2 + size] != b"\n":
            raise RuntimeError("git cat-file output was cut short for %s" % sha)
        blobs[sha] = read[end + 1:end + 1 + size]
        pos = end + 1 + size + 1
    return blobs


def advisory_added(path, base, gitdir):
    """Files whose @lane-advisory tags changed between the base commit and HEAD: more of them, or tagged lines that
    weren't tagged at base (a tag moved), as "<file>: <was> -> <now> occurrences" plus the new lines. The advisory
    set is the base commit's, so the lead reviews any tag a branch adds or moves. It reads blobs as bytes (never a
    diff, which .gitattributes `-diff`, a NUL byte or a line starting `++ ` can blind), all in one `git cat-file
    --batch`, through teamd's hardened git (workers.worker_git_argv) without replace refs, under one 60 s deadline and
    a cap of 500 files. `git cat-file --batch-check` comes first: a file whose blob on either side is over 1 MB is never
    read, and the lead is told to look at it by hand. Any git failure or timeout raises RuntimeError: the caller tells
    the lead."""
    deadline = time.monotonic() + ADVISORY_TIMEOUT_S
    try:
        argv = workers.worker_git_argv(path, gitdir, "--no-replace-objects")
        env = workers._isolated_git_env()
    except OSError as e:
        raise RuntimeError("git could not run: %r" % e)

    def git(*args, input=None):
        try:
            r = subprocess.run(argv + list(args), cwd=str(path), env=env, input=input, capture_output=True,
                               timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise RuntimeError("git %s timed out" % args[0])
        except OSError as e:
            raise RuntimeError("git could not run: %r" % e)
        if r.returncode != 0:
            raise RuntimeError("git %s exited %d: %s" % (args[0], r.returncode,
                                                        r.stderr.decode("utf-8", "replace").strip()[:200]))
        return r.stdout
    raw = git("diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", "--abbrev=40", base, "HEAD")
    fields = raw.split(b"\0")
    changed, k = [], 0
    while k + 1 < len(fields) and fields[k].startswith(b":"):
        meta = fields[k][1:].split()
        changed.append((meta[0], meta[1], meta[2], meta[3], fields[k + 1]))   # old mode, new mode, old sha, new sha
        k += 2
    if any(fields[k:]):
        raise RuntimeError("git diff --raw output was not understood")
    skipped = max(0, len(changed) - ADVISORY_MAX_CHANGED)
    changed = changed[:ADVISORY_MAX_CHANGED]

    def wanted(mode, sha):                       # a submodule, or no such side, has no blob
        return None if mode == b"160000" or set(sha) == {ord("0")} else sha.decode("ascii")
    sides = [(wanted(a, c), wanted(b, d), name) for a, b, c, d, name in changed]
    shas = sorted({x for before, after, _ in sides for x in (before, after) if x})
    sizes = _cat_file_sizes(git("cat-file", "--batch-check", input=("\n".join(shas) + "\n").encode()), shas) \
        if shas else {}
    readable = [sha for sha in shas if sizes[sha] <= ADVISORY_MAX_BLOB]
    blobs = _cat_file_batch(git("cat-file", "--batch", input=("\n".join(readable) + "\n").encode())
                            if readable else b"", readable)
    found, too_big = [], []
    for before_sha, after_sha, name in sides:
        if any(sha and sizes[sha] > ADVISORY_MAX_BLOB for sha in (before_sha, after_sha)):
            too_big.append((name, max(sizes[sha] for sha in (before_sha, after_sha) if sha)))
            continue
        before, after = blobs.get(before_sha, b""), blobs.get(after_sha, b"")
        was, now = before.count(ADVISORY_TAG), after.count(ADVISORY_TAG)
        old_lines = set(before.split(b"\n"))
        new = [ln.strip() for ln in after.split(b"\n") if ADVISORY_TAG in ln and ln not in old_lines]
        if now <= was and not new:
            continue
        lines = []
        for ln in new[:3]:
            text = ln.decode("utf-8", "replace")
            lines.append(text[:ADVISORY_MAX_LINE] + ("…" if len(text) > ADVISORY_MAX_LINE else ""))
        found.append("%s: %d -> %d occurrences%s" % (name.decode("utf-8", "replace"), was, now,
                                                    "".join("\n    " + ln for ln in lines)))
    if len(found) > ADVISORY_MAX_FILES:
        found = found[:ADVISORY_MAX_FILES] + ["… and %d more" % (len(found) - ADVISORY_MAX_FILES)]
    if skipped:
        found.append("the advisory check skipped %d files (too many changes); review the tags by hand" % skipped)
    for name, size in too_big[:ADVISORY_MAX_SKIPPED]:
        found.append("the advisory check skipped %s (%d bytes, over 1 MB); review its tags by hand"
                     % (name.decode("utf-8", "replace"), size))
    if len(too_big) > ADVISORY_MAX_SKIPPED:
        found.append("… and %d more files over 1 MB" % (len(too_big) - ADVISORY_MAX_SKIPPED))
    return found


# ---------- instruction files a browser turn changed (final fix wave, additions; round 2) ----------

INSTRUCTION_NAMES = ("claude.md", "claude.local.md", "agents.md")
INSTRUCTION_TIMEOUT_S, INSTRUCTION_MAX_BYTES = 60, 1 << 20
INSTRUCTION_MAX_ENTRIES, INSTRUCTION_MAX_DEPTH = 2_000_000, 256
TOO_LARGE = "too large to compare"


def is_instruction_path(rel):
    """CLAUDE.md, CLAUDE.local.md and AGENTS.md at any depth, and a .claude of any kind (folder, file or link) with
    anything under it, at any depth: what Claude Code may read as instructions when a turn starts. Case-insensitive,
    as the Mac's file system is."""
    parts = rel.split("/")
    return parts[-1].lower() in INSTRUCTION_NAMES or any(part.lower() == ".claude" for part in parts)


def _under_node_modules(rel):
    return "node_modules" in rel.split("/")[:-1]


def instruction_snapshot(path):
    """A worktree's instruction-bearing paths as they are right now, from teamd's own walk (git ls-files --others never
    enters a nested repository): every folder is opened through its parent's descriptor with O_NOFOLLOW, never through
    a link, and nested repositories are entered (only .git is skipped). A plain instruction file is opened the same
    way with O_NONBLOCK, confirmed regular with fstat and hashed here (sha256, at most 1 MB: a larger one is
    TOO_LARGE); a link is recorded by its target, never followed: any link outside node_modules, since it can bring a
    folder's CLAUDE.md into the next turn's reads; a FIFO, socket or device by its kind. {path: text}. One deadline
    and a cap on entries; a walk that can't finish raises RuntimeError."""
    deadline, counted = time.monotonic() + INSTRUCTION_TIMEOUT_S, [0]
    snapshot = {}

    def walk(dfd, rel, depth):
        if depth > INSTRUCTION_MAX_DEPTH:
            raise RuntimeError("the worktree is more than %d folders deep" % INSTRUCTION_MAX_DEPTH)
        entries = []
        with os.scandir(dfd) as it:
            for entry in it:                             # counted as it is read: a huge folder hits the cap, not memory
                counted[0] += 1
                if counted[0] > INSTRUCTION_MAX_ENTRIES or time.monotonic() > deadline:
                    raise RuntimeError("the worktree's walk took longer than %d s or %d entries"
                                       % (INSTRUCTION_TIMEOUT_S, INSTRUCTION_MAX_ENTRIES))
                entries.append(entry)
        for entry in entries:
            name, child = entry.name, (rel + "/" + entry.name if rel else entry.name)
            if name == ".git":
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(st.st_mode):
                if is_instruction_path(child) or not _under_node_modules(child):
                    try:
                        snapshot[child] = "l " + os.readlink(name, dir_fd=dfd)
                    except OSError as e:
                        snapshot[child] = "x %s" % (e.strerror or e.__class__.__name__)
            elif stat.S_ISDIR(st.st_mode):
                try:
                    cfd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
                except OSError as e:                     # swapped meanwhile, or unreadable: recorded, never followed
                    if is_instruction_path(child):
                        snapshot[child] = "x %s" % (e.strerror or e.__class__.__name__)
                    continue
                try:
                    walk(cfd, child, depth + 1)
                finally:
                    os.close(cfd)
            elif is_instruction_path(child):
                snapshot[child] = _instruction_content(dfd, name, st)
    try:
        root = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise RuntimeError("the worktree can't be opened (%s)" % (e.strerror or e))
    try:
        walk(root, "", 0)
    except OSError as e:
        raise RuntimeError("the worktree can't be walked (%s)" % (e.strerror or e))
    finally:
        os.close(root)
    return dict(sorted(snapshot.items()))            # the walk's order is the file system's; the result's is not


def _instruction_content(dfd, name, st):
    """One instruction file's record, read only as a plain file: opened O_NOFOLLOW|O_NONBLOCK through its folder's
    descriptor, fstat'ed, and read to at most 1 MB."""
    if not stat.S_ISREG(st.st_mode):
        return "x mode %o" % st.st_mode
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError as e:
        return "x %s" % (e.strerror or e.__class__.__name__)          # swapped for a link or a FIFO meanwhile
    with os.fdopen(fd, "rb") as f:
        now = os.fstat(f.fileno())
        if not stat.S_ISREG(now.st_mode):
            return "x mode %o" % now.st_mode
        if now.st_size > INSTRUCTION_MAX_BYTES:
            return TOO_LARGE
        data = f.read(INSTRUCTION_MAX_BYTES + 1)
    if len(data) > INSTRUCTION_MAX_BYTES:
        return TOO_LARGE
    return "f " + hashlib.sha256(data).hexdigest()


def instruction_changes(before, after):
    """The paths added, removed or changed between two snapshots, sorted. A file too large to compare counts as
    changed."""
    return sorted(rel for rel in set(before) | set(after)
                  if before.get(rel) != after.get(rel) or after.get(rel) == TOO_LARGE)


def describe_instruction_changes(before, after, limit=20):
    """The lead's list: each path (too large ones and links noted), at most
    `limit`, then one line for those under node_modules."""
    changed = instruction_changes(before, after)
    folded = [rel for rel in changed if _under_node_modules(rel)]
    listed = []
    for rel in changed:
        if rel in folded:
            continue
        note = (" (%s)" % TOO_LARGE if after.get(rel) == TOO_LARGE else
                " (a link)" if str(after.get(rel, before.get(rel))).startswith("l ") else "")
        listed.append(rel[:160] + note)
    if len(listed) > limit:
        listed = listed[:limit] + ["… and %d more" % (len(listed) - limit)]
    if folded:
        listed.append("%d instruction file%s under node_modules changed" % (len(folded), "" if len(folded) == 1 else "s"))
    return listed
