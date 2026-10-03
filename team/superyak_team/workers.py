"""Worker lifecycle for Superyak team mode: worktrees, Codex/Claude processes,
follow-up delivery, and commits on the worker's behalf.

Design notes (verified 2026-10-02 against codex 0.160 in a scratch repo):
- Codex's workspace-write sandbox protects every `.git` (even with --add-dir), so a
  sandboxed worker cannot commit. Workers only edit files; teamd commits for them
  on team_done. Workers therefore can never rewrite history or push.
- Never set sandbox_workspace_write.writable_roots: it replaces Codex's defaults
  (documented in ~/Projects/codex-team/codex-team:91-95).
- Workers are not --ephemeral: `codex exec resume` and `codex queue` need a
  persistent thread.
"""
import json
import re
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import teamlib


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True,
                          text=True, check=check)


# teamd is unsandboxed, so git it runs inside a worker's folder must not take direction from
# anything the worker can write: the worktree's `.git` pointer file is ignored in favour of the
# git dir recorded at spawn, and hooks / fsmonitor / untracked-cache helpers are switched off.
HARDENED_GIT = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                "-c", "core.untrackedCache=false", "-c", "protocol.file.allow=never",
                "-c", "commit.gpgsign=false", "-c", "core.sshCommand=false"]


# Subsection names may contain dots, spaces and quotes (filter."a.b c".clean), and section/key
# names are case-insensitive, so match the whole middle and ignore case.
_DRIVER_KEY = re.compile(r"^(filter|diff|merge)\..+\.(clean|smudge|process|textconv|command|driver)$",
                         re.IGNORECASE | re.DOTALL)


def _isolated_git_env():
    """No user/system git config: a worker's .gitattributes can name filter/diff/merge drivers,
    and the drivers' commands live in config (e.g. a global git-lfs filter)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return env


def _driver_overrides(gitdir):
    """Blank every driver command the repo's own config defines, so attributes have nothing to run."""
    out = subprocess.run(["git", "--git-dir", str(gitdir), "config", "-z", "--name-only", "--list"],
                         env=_isolated_git_env(), capture_output=True, text=True)
    flags = []
    for key in sorted({k for k in out.stdout.split("\0") if k}):   # NUL-separated: names may hold spaces
        if _DRIVER_KEY.match(key):
            flags += ["-c", key + "="]
            if key.startswith("filter."):
                flags += ["-c", key.rsplit(".", 1)[0] + ".required=false"]
    return flags


# Dependency installs teamd may run in a builder's worktree before its first turn (workers have
# no network). A fixed menu, never a lead-supplied command line.
# Installs run unsandboxed, so they never run lifecycle scripts: neither the repo's (which may
# come from someone else's branch) nor dependencies'. A package that truly needs its install
# script is rebuilt deliberately by the lead. Trust model: prepare runs once, before any agent
# turn, on the lead-chosen base commit; it is for repos whose lockfile the lead would install anyway.
PREPARE_COMMANDS = {
    # --git/--script-shell on the command line beat a repo .npmrc that points them at its own program.
    "npm-ci": ["npm", "ci", "--no-audit", "--no-fund", "--ignore-scripts",
               "--git=/usr/bin/git", "--script-shell=/bin/sh"],
    "pnpm-install": ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile",
                     "--config.git=/usr/bin/git", "--config.script-shell=/bin/sh"],
}


def start_prepare(name, cwd, log_path):
    """Start an install in its own process group so stop/end can kill all of it."""
    cmd = PREPARE_COMMANDS[name]
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    log = open(log_path, "w")
    return subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log,
                            stderr=subprocess.STDOUT, env=env, start_new_session=True)


def worker_git(path, gitdir, *args, check=True, input=None):
    return subprocess.run(["git", "--git-dir", str(gitdir), "--work-tree", str(path)]
                          + HARDENED_GIT + _driver_overrides(gitdir) + list(args),
                          cwd=str(path), env=_isolated_git_env(), input=input,
                          capture_output=True, text=True, check=check)


def _is_tool_state(rel):
    return any(part in COMMIT_EXCLUDES for part in Path(rel).parts)


def repo_root(path):
    return Path(git(path, "rev-parse", "--show-toplevel").stdout.strip())


def resolve_base(root, base=None):
    """The commit a worker branches from: the lead's HEAD, or an explicit ref/commit the lead
    names (e.g. origin/main when the local branch is stale). Never parsed as an option."""
    if base is None or base == "":
        return git(root, "rev-parse", "HEAD").stdout.strip()
    if not isinstance(base, str) or base.startswith("-") or len(base) > 200:
        raise teamlib.RejectedMessage("base must be a branch, tag or commit")
    out = git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", base + "^{commit}", check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise teamlib.RejectedMessage("base %r is not a commit in this repo (fetch first?)" % base)
    return out.stdout.strip()


def create_worktree(root, team_id, worker, base=None):
    """Branch team/<team>/<worker> off `base` (default: the lead's HEAD), in <root>-worktrees/."""
    root = Path(root)
    base = resolve_base(root, base)
    branch = "team/%s/%s" % (team_id, worker)
    path = root.parent / (root.name + "-worktrees") / team_id / worker
    path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-q", "-b", branch, str(path), base)
    # Recorded now, before any agent runs; every later git call uses this, not path/.git.
    gitdir = git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    return {"branch": branch, "path": str(path), "base": base, "gitdir": gitdir}


def remove_worktree(root, path, branch, keep_branch=True):
    git(root, "worktree", "remove", "--force", str(path), check=False)
    if not keep_branch:
        git(root, "branch", "-D", branch, check=False)


# Tool state that agents' own tooling writes into a worktree; never part of the work.
COMMIT_EXCLUDES = (".engram", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                   ".venv", "node_modules", ".DS_Store")


def commit_subject(worker, summary, limit=72):
    first = " ".join((summary or "work").split())
    subject = "%s: %s" % (worker, first)
    return subject if len(subject) <= limit else subject[:limit - 1].rstrip() + "…"


def commit_for_worker(path, worker, kind, summary, gitdir):
    """Commit what the worker changed (minus tool state). Returns the new SHA or None if clean."""
    # Stage exactly the changed paths (git's own ignore rules applied), minus tool state.
    # Exclude pathspecs are not used: git refuses them with exit 1 when .gitignore already
    # ignores the same path (e.g. node_modules), which failed team_done on 2026-10-02.
    listed = worker_git(path, gitdir, "ls-files", "-z", "--modified", "--others", "--deleted",
                        "--exclude-standard").stdout
    changed = sorted({f for f in listed.split("\0") if f and not _is_tool_state(f)})
    if changed:
        worker_git(path, gitdir, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
                   input="\0".join(changed) + "\0")
    if not worker_git(path, gitdir, "diff", "--cached", "--name-only").stdout.strip():
        return None
    name = "%s (%s)" % (worker, kind)
    worker_git(path, gitdir, "-c", "user.name=" + name, "-c", "user.email=agent-team@noreply.local",
               "commit", "-q", "--no-verify", "-m", commit_subject(worker, summary),
               "-m", (summary or "").strip() or "(no summary)",
               "-m", "Committed by the Superyak team daemon on behalf of %s." % name)
    return worker_git(path, gitdir, "rev-parse", "HEAD").stdout.strip()


def diff_stat(path, base, gitdir):
    return worker_git(path, gitdir, "diff", "--stat", base, check=False).stdout.strip()


def mcp_env(team_id, worker):
    # No secrets here: config/argv are visible via ps. The MCP server (outside the sandbox)
    # fetches this worker's token from the token store itself.
    env = {"SUPERYAK_TEAM_ID": team_id, "SUPERYAK_TEAM_ROLE": worker,
           "SUPERYAK_TEAM_HOME": str(teamlib.team_home())}
    if os.environ.get("SUPERYAK_TEAM_TOKEN_STORE"):
        env["SUPERYAK_TEAM_TOKEN_STORE"] = os.environ["SUPERYAK_TEAM_TOKEN_STORE"]
    return env


def configured_codex_mcp(config_path=None):
    """Names of MCP servers defined as [mcp_servers.<name>] tables in Codex's config.
    Overriding a server that isn't defined there (e.g. one a Codex plugin provides) makes
    Codex create an empty entry and fail with "invalid transport" (seen 2026-10-02)."""
    p = Path(config_path or os.path.join(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
                                         "config.toml"))
    if not p.exists():
        return set()
    import re
    names = set()
    for m in re.finditer(r'^\[mcp_servers\.("?)([A-Za-z0-9_-]+)\1\]\s*$', p.read_text(), re.MULTILINE):
        names.add(m.group(2))
    return names


def configured_codex_plugins(config_path=None):
    """Enabled Codex plugins ([plugins."name@source"] tables with enabled = true)."""
    p = Path(config_path or os.path.join(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
                                         "config.toml"))
    if not p.exists():
        return []
    import re
    text, names = p.read_text(), []
    for m in re.finditer(r'^\[plugins\."([^"]+)"\]\s*\n((?:(?!\[).*\n?)*)', text, re.MULTILINE):
        if re.search(r"^\s*enabled\s*=\s*true", m.group(2), re.MULTILINE):
            names.append(m.group(1))
    return names


# MCP servers a Codex worker keeps. Everything else (context7, github, docs, plugins, ...) is a
# potential data-egress channel for an agent whose sandbox can read all of $HOME, so it is
# switched off rather than relying on approval_policy="never" rejecting unapproved tools.
CODEX_WORKER_MCP = {"team", "engram"}


def codex_command(cfg, team_id, worker, cwd, prompt, thread_id=None, mode="build"):
    """mode "build": workspace-write in the worker's worktree. mode "collab": read-only sandbox
    (repo for context); collaborators produce messages and documents.
    Codex's sandbox cannot restrict reads, so Codex workers get no egress at all: web search
    (on by default in Codex, verified 2026-10-02) is disabled and so are other MCP servers/plugins."""
    py, mcp = sys.executable, str(teamlib.run_team_path())
    flags = ["--json", "-m", cfg["codex_model"],
             "-c", "model_reasoning_effort=%s" % json.dumps(cfg["codex_effort"]),
             "-c", 'sandbox_mode="%s"' % ("read-only" if mode == "collab" else "workspace-write"),
             "-c", 'approval_policy="never"',
             "-c", 'web_search="disabled"',
             "-c", "mcp_servers.team.command=%s" % json.dumps(py),
             "-c", "mcp_servers.team.args=%s" % json.dumps([mcp])]
    for k, v in mcp_env(team_id, worker).items():
        flags += ["-c", "mcp_servers.team.env.%s=%s" % (k, json.dumps(v))]
    for tool in ("team_post", "team_read", "team_ask_lead", "team_done", "team_status",
                 "team_message", "team_plan"):
        flags += ["-c", 'mcp_servers.team.tools.%s.approval_mode="approve"' % tool]
    defined = configured_codex_mcp()
    # approval_policy="never" auto-rejects MCP tools that aren't pre-approved; the worker brief
    # relies on these engram tools (seen live 2026-10-02: "Engram recall was rejected").
    if "engram" in defined:
        for tool in ("recall", "remember", "share", "shares"):
            flags += ["-c", 'mcp_servers.engram.tools.%s.approval_mode="approve"' % tool]
    # Only servers defined as [mcp_servers.X] can be overridden (plugin servers break config).
    for name in sorted(defined - CODEX_WORKER_MCP):
        flags += ["-c", "mcp_servers.%s.enabled=false" % name]
    for plugin in configured_codex_plugins():
        flags += ["-c", 'plugins."%s".enabled=false' % plugin]
    head = ["codex"]
    prompt = safe_prompt(prompt)
    if thread_id:
        return head + ["exec", "resume"] + flags + ["--skip-git-repo-check", thread_id, prompt]
    extra = ["--skip-git-repo-check"] if mode == "collab" else []   # collab rooms aren't repos
    return head + ["exec"] + flags + extra + ["-C", str(cwd), prompt]


def safe_prompt(prompt):
    """Prompts are the last argv element; text from the lead, Slack or a teammate must never be
    parsed as an option (e.g. a message starting with --dangerously-...)."""
    prompt = str(prompt)
    return prompt if not prompt.lstrip().startswith("-") else "(message) " + prompt


# Read-only paths a sandboxed shell needs for ordinary dev tools (git, uv, node via fnm, bun).
# Everything else under $HOME is unreadable to Claude workers.
TOOL_READ_PATHS = ("~/.gitconfig", "~/.config/git", "~/.local/bin", "~/.local/share/fnm",
                   "~/.local/share/uv", "~/.cache/uv", "~/.bun")
TEAM_TOOLS = ("team_post", "team_read", "team_ask_lead", "team_done", "team_status",
              "team_message", "team_plan")
ENGRAM_TOOLS = ("recall", "remember", "share", "shares")


def _home(p):
    return p.replace("~", str(Path.home()), 1)


def claude_sandbox_settings(cwd, mode="build", web_search=False, repo=None,
                            engram_prefix="mcp__plugin_engram_engram__"):
    """Allowlist, not denylist, for Claude workers (all verified live 2026-10-02):
    - permissions run in dontAsk mode: any tool call not explicitly allowed is refused, which
      also shuts out the user's other plugins/MCP servers (Slack, browser, ...) as egress paths;
    - the Read/Grep/Glob tools may only see the worker's folder and the repo;
      absolute paths need the `//` prefix (a bare /path is relative to the settings file);
    - the OS sandbox denies reading $HOME except the worker folder, the repo and tool paths,
      and .env files anywhere (deny globs win over allowRead);
    - writes: the worktree for builders, nothing for collaborators; no WebFetch; WebSearch only
      for collaborators when the team enables it."""
    cwd, repo = str(cwd), str(repo or cwd)
    home = str(Path.home())
    scopes = sorted({cwd, repo})
    allow = []
    for scope in scopes:
        for tool in ("Read", "Grep", "Glob"):
            allow.append("%s(/%s/**)" % (tool, scope))
    allow += ["Bash"] + ["mcp__team__%s" % t for t in TEAM_TOOLS] + \
             [engram_prefix + t for t in ENGRAM_TOOLS]
    deny = ["Read(//**/.env)", "Read(//**/.env.*)", "WebFetch",
            "Bash(git push*)", "Bash(git commit*)", "Bash(git reset*)", "Bash(git rebase*)",
            "Bash(security*)", "Bash(*security *)"]
    if mode == "collab":
        deny += ["Edit", "Write", "NotebookEdit"]
        allow_write = []
        if web_search:
            allow.append("WebSearch")
        else:
            deny.append("WebSearch")
    else:
        allow += ["Edit(/%s/**)" % cwd, "Write(/%s/**)" % cwd]
        deny += ["WebSearch", "Edit(/%s/.git)" % cwd, "Write(/%s/.git)" % cwd,
                 "Edit(/%s/.git/**)" % cwd, "Write(/%s/.git/**)" % cwd]
        allow_write = [cwd]
    return {
        "permissions": {"defaultMode": "dontAsk", "allow": allow, "deny": deny},
        "sandbox": {"enabled": True, "failIfUnavailable": True,
                    "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False,
                    "filesystem": {"allowWrite": allow_write,
                                   "denyWrite": [os.path.join(cwd, ".git")] if allow_write else [],
                                   "denyRead": [home, "**/.env", "**/.env.*"],
                                   "allowRead": scopes + [_home(p) for p in TOOL_READ_PATHS]}},
    }


def claude_command(cfg, team_id, worker, cwd, prompt, session_id=None, mode="build", repo=None):
    wdir = teamlib.team_dir(team_id) / "workers" / worker
    wdir.mkdir(parents=True, exist_ok=True)
    mcp_cfg, settings = wdir / "mcp.json", wdir / "settings.json"
    mcp_cfg.write_text(json.dumps({"mcpServers": {"team": {
        "command": sys.executable,
        "args": [str(teamlib.run_team_path())],
        "env": mcp_env(team_id, worker)}}}))
    web = mode == "collab" and bool(cfg.get("collab_web_search", True))
    settings.write_text(json.dumps(claude_sandbox_settings(
        cwd, mode, web, repo, cfg.get("engram_tool_prefix", "mcp__plugin_engram_engram__"))))
    # The permission mode is set here too: a CLI --permission-mode overrides the settings file.
    cmd = ["claude", "-p", safe_prompt(prompt), "--output-format", "stream-json", "--verbose",
           "--model", cfg["claude_model"], "--permission-mode", "dontAsk",
           "--settings", str(settings), "--mcp-config", str(mcp_cfg)]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def launch(cmd, cwd, worker_dir, env_extra=None):
    """Start an agent turn; stdout (JSON events) appends to events.jsonl."""
    worker_dir = Path(worker_dir)
    worker_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(env_extra or {})
    env["VOICE_NOTIFY_MUTE"] = "1"   # background agents don't ring the human's bell
    out = open(worker_dir / "events.jsonl", "a")
    err = open(worker_dir / "stderr.log", "a")
    (worker_dir / "last-command.txt").write_text(" ".join(shlex.quote(c) for c in cmd[:6]) + " ...\n")
    return subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                            env=env, start_new_session=True)


def parse_events(worker_dir, kind):
    """Extract thread/session id and the last agent message from events.jsonl."""
    ident, last = None, ""
    p = Path(worker_dir) / "events.jsonl"
    if not p.exists():
        return ident, last
    for line in p.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind == "codex":
            if ev.get("type") == "thread.started" and ev.get("thread_id"):
                ident = ev["thread_id"]
            item = ev.get("item") or {}
            if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
                last = item.get("text", last)
        else:
            if ev.get("session_id"):
                ident = ev["session_id"]
            if ev.get("type") == "result" and isinstance(ev.get("result"), str):
                last = ev["result"]
    return ident, last


def queue_message(thread_id, text):
    """Deliver into a running Codex turn. Returns True on success."""
    r = subprocess.run(["codex", "queue", "--thread", thread_id, "--message", text],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0
