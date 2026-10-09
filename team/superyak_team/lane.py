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
