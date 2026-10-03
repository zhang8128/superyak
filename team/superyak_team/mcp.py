#!/usr/bin/env python3
"""Team mode client: a thin front end for teamd. Three ways in, one behaviour:

  MCP (stdio):  superyak-runtime team            — Claude Code or Codex, lead or worker mode
  CLI:          superyak-runtime team <op> ...    — any shell, e.g. `superyak-runtime team status`
  Daemon:       run_team.py teamd --team ...      — started by team_start, never by hand

Mode: SUPERYAK_TEAM_ROLE=w<N> (set by teamd for workers) → worker; otherwise lead.
The lead may be Claude Code or Codex; its kind is detected from the environment
(or SUPERYAK_TEAM_LEAD_KIND) and only changes the display name.
Lead tools resolve the active team from the current repo (one active team per repo).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import teamlib

ROLE = os.environ.get("SUPERYAK_TEAM_ROLE", "")
IS_WORKER = ROLE.startswith("w")


def lead_kind():
    k = os.environ.get("SUPERYAK_TEAM_LEAD_KIND")
    if k in ("claude", "codex"):
        return k
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID") or os.environ.get("CODEX_HOME_MARKER"):
        return "codex"
    return "claude"


def git_root(cwd=None):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise teamlib.RejectedMessage("not inside a git repository (team mode needs one)")
    return r.stdout.strip()


def active_team(repo):
    p = teamlib.current_team_file(repo)
    if not p.exists():
        raise teamlib.RejectedMessage("no active team for this repo; call team_start first")
    return p.read_text().strip()


def daemon_alive(team_id):
    pid_file = teamlib.team_dir(team_id) / "teamd.pid"
    sock = teamlib.sock_path(team_id)
    if not (pid_file.exists() and sock.exists()):
        return False
    try:
        os.kill(int(pid_file.read_text()), 0)
        return True
    except (OSError, ValueError):
        return False


def resolve_team(requested=None):
    repo = git_root()
    if requested:
        if requested not in teamlib.active_teams(repo):
            raise teamlib.RejectedMessage("no active team %r in this repo; team_list shows them" % requested)
        return requested
    return active_team(repo)


def call(op, args=None):
    args = dict(args or {})
    if IS_WORKER:
        team_id, caller = os.environ["SUPERYAK_TEAM_ID"], ROLE
    else:
        team_id, caller = resolve_team(args.pop("team", None)), "lead"
    token = teamlib.get_token(team_id, caller)
    if not daemon_alive(team_id):
        raise teamlib.RejectedMessage("team %s daemon is not running (team_start to restart)" % team_id)
    resp = teamlib.rpc(team_id, op, caller, args, token=token)
    if not resp.get("ok"):
        raise teamlib.RejectedMessage(resp.get("error", "unknown error"))
    return resp["result"]


def team_start(args):
    goal = (args.get("goal") or "").strip()
    if not goal:
        raise teamlib.RejectedMessage("goal is required")
    repo = git_root()
    preset = args.get("preset") or None
    overrides = args.get("config") or {}
    if isinstance(overrides, str):          # CLI: config='{"max_workers": 2}'
        overrides = json.loads(overrides)
    cfg = teamlib.team_config(preset, overrides)   # validate before starting anything
    team_id = args.get("name") or "%s-%s" % (teamlib.slugify(goal, 20), time.strftime("%m%d%H%M"))
    team_id = teamlib.slugify(team_id, 40)
    if team_id in teamlib.active_teams(repo) and daemon_alive(team_id):
        return {"team": team_id, "note": "already running; use a different name to start another team"}
    tdir = teamlib.team_dir(team_id)
    tdir.mkdir(parents=True, exist_ok=True)
    log = open(tdir / "teamd.stdout", "a")
    subprocess.Popen([sys.executable, str(teamlib.run_team_path()), "teamd",
                      "--team", team_id, "--repo", repo, "--goal", goal, "--lead-kind", lead_kind(),
                      "--preset", preset or "", "--config-json", json.dumps(overrides)],
                     stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                     cwd=repo)
    for _ in range(50):
        if daemon_alive(team_id):
            break
        time.sleep(0.1)
    else:
        raise teamlib.RejectedMessage("teamd did not start; see %s" % (tdir / "teamd.stdout"))
    cur = teamlib.current_team_file(repo)
    cur.parent.mkdir(parents=True, exist_ok=True)
    cur.write_text(team_id)
    active = [t for t in teamlib.active_teams(repo) if t != team_id and daemon_alive(t)] + [team_id]
    teamlib.set_active_teams(repo, active)
    return {"team": team_id, "repo": repo, "lead": lead_kind(), "preset": preset or "(defaults)",
            "default_mode": cfg.get("default_mode", "build"), "default_kind": cfg.get("default_kind", "codex"),
            "max_workers": cfg["max_workers"], "other_active_teams": active[:-1],
            "slack": ("mirrored to Slack" if cfg.get("slack_channel") and teamlib.slack_allowed_for_repo(repo)
                      else "off (local transcript only; add this repo to slack_repos to mirror)")}


def team_list(args):
    repo = git_root()
    out = []
    for t in teamlib.active_teams(repo):
        sf = teamlib.team_dir(t) / "state.json"
        st = json.loads(sf.read_text()) if sf.exists() else {}
        out.append({"team": t, "running": daemon_alive(t), "goal": st.get("goal", ""),
                    "preset": (st.get("config") or {}).get("preset", ""),
                    "workers": {k: "%s/%s/%s" % (v["kind"], v.get("mode", "build"), v["state"])
                                for k, v in st.get("workers", {}).items()}})
    cur = teamlib.current_team_file(repo)
    return {"current": cur.read_text().strip() if cur.exists() else None, "teams": out,
            "presets": {k: v.get("description", "") for k, v in teamlib.load_presets().items()}}


def team_end(args):
    team_id = resolve_team(args.get("team"))
    res = call("end", dict(args, team=team_id))
    repo = git_root()
    remaining = [t for t in teamlib.active_teams(repo) if t != team_id]
    teamlib.set_active_teams(repo, remaining)
    cur = teamlib.current_team_file(repo)
    if remaining:
        cur.write_text(remaining[-1])
    elif cur.exists():
        cur.unlink()
    return res


OBJ = {"type": "object"}
LEAD_TOOLS = [
    ("team_start", "Start a team (its own daemon, Slack kickoff, config). Several teams can run in one "
                   "repo. preset: build | research | review | mixed (or custom from "
                   "~/.superyak/team/presets.json); config: per-team overrides such as max_workers, "
                   "default_mode, default_kind, codex_effort, claude_model, collab_max_turns.",
     {"goal": {"type": "string"}, "name": {"type": "string", "description": "optional team id"},
      "preset": {"type": "string"}, "config": {"type": "object"}}, ["goal"], team_start),
    ("team_list", "Active teams in this repo (state, preset, workers) and the available presets.",
     {}, [], team_list),
    ("team_spawn", "Add a worker. mode 'build': implements in its own git worktree (code). mode 'collab': "
                   "read-only collaborator that researches, discusses with teammates live and publishes "
                   "documents. kind: 'codex' (gpt-6.1-sol) or 'claude'. Defaults come from the team's "
                   "preset. Give a self-contained task with acceptance criteria.",
     {"task": {"type": "string"}, "kind": {"type": "string", "enum": ["codex", "claude"]},
      "mode": {"type": "string", "enum": ["build", "collab"]}, "context": {"type": "string"},
      "base": {"type": "string", "description": "build only: branch/tag/commit to branch from "
                                                "(default: the lead's HEAD)"},
      "prepare": {"type": "string", "enum": ["npm-ci", "pnpm-install"],
                  "description": "build only: install dependencies (outside the sandbox) before "
                                 "the first turn; workers have no network"},
      "team": {"type": "string"}}, ["task"], lambda a: call("spawn", a)),
    ("team_message", "Send a message to a worker (delivered into its running turn when possible).",
     {"worker": {"type": "string"}, "text": {"type": "string"}, "team": {"type": "string"}}, ["worker", "text"],
     lambda a: call("message", a)),
    ("team_plan", "Publish or update a plan as a document (Slack canvas in the team channel, plus a "
                  "local copy) and link it in the kickoff thread. Use it for the team plan before "
                  "spawning; calling again with the same title updates the same document.",
     {"title": {"type": "string"}, "markdown": {"type": "string"}, "team": {"type": "string"}}, ["title", "markdown"],
     lambda a: call("plan", a)),
    ("team_post", "Post to the team's kickoff thread on Slack (as the lead).",
     {"text": {"type": "string"}, "team": {"type": "string"}}, ["text"], lambda a: call("post", a)),
    ("team_status", "Workers, their states, and unread messages for the lead (questions, DONE, Slack replies).",
     {"team": {"type": "string"}}, [], lambda a: call("status", a)),
    ("team_collect", "A worker's result: commit, summary, tests, diff stat vs its base, worktree path.",
     {"worker": {"type": "string"}, "team": {"type": "string"}}, ["worker"], lambda a: call("collect", a)),
    ("team_stop", "Stop a worker's process.", {"worker": {"type": "string"}, "team": {"type": "string"}}, ["worker"],
     lambda a: call("stop", a)),
    ("team_end", "End the team: stop workers, remove worktrees (branches are kept), post a summary.",
     {"summary": {"type": "string"}, "keep_worktrees": {"type": "boolean"}, "team": {"type": "string"}},
     [], team_end),
]
WORKER_TOOLS = [
    ("team_post", "Post progress to your task thread (team + human can see it). Keep it short and factual.",
     {"text": {"type": "string"}}, ["text"], lambda a: call("post", a)),
    ("team_message", "Message teammates: to='lead', a worker id (e.g. 'w2'), or 'all'. Collaborators "
                     "receive it live; builders read it with team_read. Short and specific.",
     {"to": {"type": "string"}, "text": {"type": "string"}}, ["to", "text"],
     lambda a: call("message", a)),
    ("team_plan", "Publish your plan for your task as a document (Slack canvas + local copy), linked in "
                  "your thread. Do this before implementing anything non-trivial; same title updates it.",
     {"title": {"type": "string"}, "markdown": {"type": "string"}}, ["title", "markdown"],
     lambda a: call("plan", a)),
    ("team_read", "Read new messages for you (from the lead, teammates, or the human on Slack). "
                  "Check between steps.",
     {}, [], lambda a: call("read", a)),
    ("team_ask_lead", "Ask the lead a blocking question (scope, design, conflicts). Then continue other work "
                      "or call team_read later for the answer.",
     {"text": {"type": "string"}}, ["text"], lambda a: call("ask_lead", a)),
    ("team_done", "Finish: the team daemon commits your changes on your branch. Give a summary and the "
                  "actual test command + result.",
     {"summary": {"type": "string"}, "tests": {"type": "string"}}, ["summary"], lambda a: call("done", a)),
    ("team_status", "Your task, branch, goal, and what teammates are doing.", {}, [],
     lambda a: call("status", a)),
]
TOOLS = WORKER_TOOLS if IS_WORKER else LEAD_TOOLS
IMPL = {name: fn for name, _, _, _, fn in TOOLS}


def tool_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": props, "required": req}}
            for n, d, props, req, _ in TOOLS]


def handle(msg):
    mid, method = msg.get("id"), msg.get("method", "")
    if method == "initialize":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "superyak-team", "version": "1.0.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": tool_list()}}
    if method == "tools/call":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        fn = IMPL.get(params.get("name"))
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": "unknown tool %r" % params.get("name")}}
        try:
            out, err = fn(params.get("arguments") or {}), False
        except teamlib.RejectedMessage as e:
            out, err = str(e), True
        except Exception as e:  # never crash the agent's MCP server
            out, err = "team error: %r" % e, True
        text = out if isinstance(out, str) else json.dumps(out, indent=1)
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}],
                                                        "isError": err}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method %r" % method}}


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            resp = handle(msg)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def cli(argv):
    """superyak-runtime team <tool-without-team_-prefix> [key=value ...]  e.g. spawn task="..." kind=codex
    `superyak-runtime team brief` prints the lead brief, wherever the repo is checked out."""
    if argv[0] == "brief":
        print((teamlib.package_dir() / "roles" / "lead.md").read_text())
        return 0
    name = argv[0] if argv[0].startswith("team_") else "team_" + argv[0]
    fn = IMPL.get(name)
    if fn is None:
        sys.exit("unknown command %r; available: %s" % (argv[0], ", ".join(n[5:] for n in IMPL)))
    args = {}
    for kv in argv[1:]:
        k, _, v = kv.partition("=")
        args[k] = v.lower() == "true" if v.lower() in ("true", "false") else v
    try:
        out = fn(args)
    except teamlib.RejectedMessage as e:
        sys.exit("error: %s" % e)
    print(out if isinstance(out, str) else json.dumps(out, indent=1))


def main(argv=None):
    """Entry for `superyak-runtime team`, `superyak-team`, and team/run_team.py:
    no args → MCP over stdio; `teamd ...` → the team daemon; anything else → CLI."""
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "teamd":
        from . import teamd
        return teamd.main(argv[1:])
    if argv:
        return cli(argv)
    return serve_stdio()


if __name__ == "__main__":
    main()
