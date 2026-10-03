"""Persistent named agents: each one has its own engram memory, carried from team to team.

An agent (e.g. `sol-1`, `claude-2`, or a name Kairos gives) is a registry entry in
~/.superyak/team/agents.json plus an engram instance `agent-<name>`. A team seats agents as
workers (w1, w2, ...); one agent sits in at most one live team at a time. What an agent
remembers stays in its own store; it shares deliberately (`share(..., audience=
"group:agent-team", reason)`) and teammates read the group through teamd (`shared`), because
worker sandboxes cannot open the published house themselves.

The engram side is engram/cli.py (agent-create, house-init, shared), run with the engram
venv and ENGRAM_HOME from the Superyak runtime config. Every call fails closed: if a store
cannot be made, the worker is not spawned (it would otherwise fall back to Kairos's store).
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import teamlib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
NAME_PREFIX = {"codex": "sol", "claude": "claude"}
SEEDS = ("empty", "genome-core")


def registry_path():
    return teamlib.team_home() / "agents.json"


def _load(f):
    f.seek(0)
    raw = f.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}


def _store(f, data):
    f.seek(0)
    f.truncate()
    f.write(json.dumps(data, indent=1))
    f.flush()


def instance_name(name):
    return "agent-" + name


def list_agents():
    with teamlib.locked(registry_path()) as f:
        return _load(f)


def claim(name, kind, team_id, wid, seed="empty", live=lambda team_id: False, roster="voyager"):
    """Register (first time) and seat an agent; returns its registry entry.
    name=None picks the roster's next unused crew name (then `<sol|claude>-<n>`). An agent
    keeps its kind: its memory belongs to one model's line. live(team_id) says whether
    another team's seat still holds."""
    crew = teamlib.roster(roster)
    with teamlib.locked(registry_path()) as f:
        data = _load(f)
        if not name:                       # a new agent: next crew name, then <sol|claude>-<n>
            name = next((c for c in crew["crew"] if c not in data), None)
            n = 1
            while not name:
                candidate = "%s-%d" % (NAME_PREFIX[kind], n)
                name = candidate if candidate not in data else None
                n += 1
        name = name.lower()
        if name in ("lead", "all", "teamd") or any(name == r.get("lead") for r in teamlib.all_rosters().values()):
            raise teamlib.RejectedMessage("%r is reserved (the lead or a channel keyword)" % name)
        if not NAME_RE.match(name):
            raise teamlib.RejectedMessage("agent names are lowercase letters, digits and '-', "
                                          "starting with a letter (got %r)" % name)
        a = data.get(name)
        if a is None:
            a = {"kind": kind, "instance": instance_name(name), "created": time.time(),
                 "seed": seed, "teams": [], "seat": None}
        elif a["kind"] != kind:
            raise teamlib.RejectedMessage("agent %s is a %s agent; its memory stays with that kind"
                                          % (name, a["kind"]))
        seat = a.get("seat")
        if seat and seat["team"] != team_id and live(seat["team"]):
            raise teamlib.RejectedMessage("agent %s is already working in team %s"
                                          % (name, seat["team"]))
        a["seat"] = {"team": team_id, "worker": wid, "since": time.time()}
        if team_id not in a["teams"]:
            a["teams"].append(team_id)
        data[name] = a
        _store(f, data)
        return dict(a, name=name)


def release(name, team_id):
    with teamlib.locked(registry_path()) as f:
        data = _load(f)
        a = data.get(name)
        if a and a.get("seat") and a["seat"]["team"] == team_id:
            a["seat"] = None
            _store(f, data)


# ---------- engram bridge ----------

def engram_dir():
    return teamlib.package_dir().parent.parent / "engram"


def engram_home():
    """ENGRAM_HOME as the Superyak runtime resolves it (memory_home in runtime.json)."""
    if os.environ.get("ENGRAM_HOME"):
        return os.environ["ENGRAM_HOME"]
    cfg = Path(os.environ.get("SUPERYAK_RUNTIME_CONFIG",
                              str(Path.home() / ".config" / "superyak" / "runtime.json")))
    try:
        home = json.loads(cfg.read_text()).get("memory_home")
    except (OSError, json.JSONDecodeError):
        home = None
    if not home:
        raise teamlib.RejectedMessage("no engram memory_home (set it in %s)" % cfg)
    return home


def engram_cli(args, timeout=120):
    """Run engram/cli.py with the engram venv; returns its JSON object or raises."""
    py = os.environ.get("SUPERYAK_ENGRAM_PYTHON") or str(engram_dir() / ".venv" / "bin" / "python")
    cli = os.environ.get("SUPERYAK_ENGRAM_CLI") or str(engram_dir() / "cli.py")
    env = dict(os.environ, ENGRAM_HOME=engram_home())
    try:
        r = subprocess.run([py, cli] + list(args), capture_output=True, text=True, timeout=timeout,
                           cwd=str(Path(cli).parent), env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise teamlib.RejectedMessage("engram %s failed: %s" % (args[0], e))
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {}
    if r.returncode != 0 or not isinstance(out, dict) or "error" in out:
        detail = out.get("error") if isinstance(out, dict) and out.get("error") else r.stderr.strip()[-300:]
        raise teamlib.RejectedMessage("engram %s failed: %s" % (args[0], detail or "rc=%d" % r.returncode))
    return out


def ensure_store(entry, seed):
    if seed not in SEEDS:
        raise teamlib.RejectedMessage("agent_seed must be one of: %s" % ", ".join(SEEDS))
    return engram_cli(["agent-create", entry["instance"], "--seed", seed])


def shared(audience, query="", after="", limit=20):
    args = ["shared", "--audience", audience, "--limit", str(int(limit))]
    if query:
        args += ["--query", query]
    if after:
        args += ["--after", after]
    return engram_cli(args, timeout=60).get("shares", [])


def seeded_config(repo_config_bytes, instance):
    """The repo's engram config with its top-level `instance` replaced by the agent's."""
    text = repo_config_bytes.decode("utf-8", "replace") if repo_config_bytes else ""
    lines, top = [], True
    for ln in text.splitlines():
        if ln.strip().startswith("["):
            top = False
        if top and re.match(r"^\s*instance\s*=", ln):
            continue
        lines.append(ln)
    rest = "\n".join(lines).strip("\n")
    return ('instance = "%s"\n' % instance + (rest + "\n" if rest else "")).encode()
