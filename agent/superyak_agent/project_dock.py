"""Docking a project ship (D7, S5 and S9): the checks that run before the docking request, before each poll of a
pending docking and inside the lock hold that writes the claim, all writing nothing; then the claim, and the project's
wiring, none of it in git: the excludes in .git/info/exclude, the station tools at Claude Code's local scope, the hooks
in .claude/settings.local.json (backed up into the ship's home), and the Codex profile. A failure after the claim rolls
back what this run wrote, the claim last. docs/superpowers/specs/2026-10-09-many-ships-one-machine-design.md"""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from superyak_team.workers import HARDENED_GIT, _isolated_git_env
from . import claims, install
from .claims import Refused
from .station import read_json, write_private

EXCLUDES = ('/.claude/settings.local.json', '/.claude/.settings.local.json.*')
PROBES = ('.claude/settings.local.json', '.claude/.settings.local.json.probe.tmp')
CHECKOUT = install.AGENT_DIR.parent           # this superyak checkout
GIT_TIMEOUT = 30


def _git(repo, *args, config=()):
    """R5: git in the repository only as --git-dir/--work-tree with HARDENED_GIT, the isolated environment and the
    root as the working directory, so no repository config, hook, fsmonitor or filter runs and a pathspec means the
    same from anywhere."""
    argv = ['git', '--git-dir', str(repo.common), '--work-tree', str(repo.root), *HARDENED_GIT, *config, *args]
    return subprocess.run(argv, cwd=str(repo.root), env=_isolated_git_env(), capture_output=True, text=True,
                          timeout=GIT_TIMEOUT)


def git_checks(repo):
    """S5, writing nothing: .claude is a real folder, settings.local.json a regular file, untracked, and ignored by
    the two exclude lines alone (a dry check-ignore against a temporary core.excludesFile outside the repository).
    Every unexpected answer refuses."""
    claude = repo.root / '.claude'
    if os.path.lexists(claude) and (claude.is_symlink() or not claude.is_dir()):
        raise Refused(f'{claude} is a symlink or not a folder, so dock would write outside the repository. Make it a '
                      'real folder, then dock again.')
    settings = claude / 'settings.local.json'
    if os.path.lexists(settings) and (settings.is_symlink() or not settings.is_file()):
        raise Refused(f'{settings} is a symlink or not a regular file. Make it a plain file, then dock again.')
    tracked = _git(repo, 'ls-files', '--error-unmatch', '--', PROBES[0])
    if tracked.returncode == 0:
        raise Refused(f'{settings} is tracked by git, so the ship\'s hooks would be committed. Untrack it (git rm '
                      '--cached), then dock again.')
    if tracked.returncode != 1:
        raise Refused(f'git ls-files answered {tracked.returncode} in {repo.root}: {tracked.stderr.strip()[:200]}')
    fd, excludes = tempfile.mkstemp(prefix='superyak-excludes-', suffix='.txt')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join(EXCLUDES) + '\n')
        for probe in PROBES:
            answer = _git(repo, 'check-ignore', '-q', '--', probe, config=('-c', f'core.excludesFile={excludes}'))
            if answer.returncode != 0:
                why = _git(repo, 'check-ignore', '-v', '--', probe, config=('-c', f'core.excludesFile={excludes}'))
                rule = why.stdout.strip() if why.returncode == 0 else ''
                raise Refused(f'{probe} is not ignored even with the two exclude lines (check-ignore answered '
                              f'{answer.returncode}{"; the rule that wins: " + rule if rule else ""}). A negation in '
                              '.gitignore or .git/info/exclude would let it be committed. Remove it, then dock again.')
    finally:
        Path(excludes).unlink(missing_ok=True)


def real_exclude_check(repo):
    """After the real append, before anything is written in the work tree: ignored with no -c, as git will see it."""
    for probe in PROBES:
        answer = _git(repo, 'check-ignore', '-q', '--', probe)
        if answer.returncode != 0:
            raise Refused(f'after adding the exclude lines, git still doesn\'t ignore {probe} (check-ignore answered '
                          f'{answer.returncode}).')


def append_excludes(repo):
    """The two lines, once each, at the end of <common>/info/exclude. Returns the file's bytes before, or None when
    it didn't exist, so a rollback puts it back as it was."""
    path = repo.common / 'info' / 'exclude'
    before = path.read_bytes() if path.exists() else None
    text = (before or b'').decode()
    lines = text.splitlines()
    missing = [line for line in EXCLUDES if line not in lines]
    if missing:
        path.parent.mkdir(exist_ok=True)
        path.write_text(text + ('' if not text or text.endswith('\n') else '\n') + '\n'.join(missing) + '\n')
    return before


def _restore(path, before):
    if before is None:
        Path(path).unlink(missing_ok=True)
    else:
        Path(path).write_bytes(before)


# ---------- the machine ship's wiring must run this checkout's code (S9, R10) ----------

def _run_agent_paths(words, then):
    return [w for w, following in zip(words, words[1:]) if Path(w).name == 'run_agent.py' and following == then]


def _mcp_get(cwd):
    """`claude mcp get station` from `cwd`: (scope line, args line) or None."""
    if not install.shutil.which('claude'):
        return None
    got = subprocess.run(['claude', 'mcp', 'get', 'station'], cwd=str(cwd), capture_output=True, text=True)
    if got.returncode != 0:
        return None
    lines = [line.strip() for line in (got.stdout or '').splitlines()]
    scope = next((line for line in lines if line.lower().startswith('scope:')), '')
    args = next((line for line in lines if line.lower().startswith('args:')), '')
    command = next((line for line in lines if line.lower().startswith('command:')), '')
    return scope, args, command


TABLE = re.compile(r'^\[mcp_servers\.station\]\s*$(.*?)(?=^\[|\Z)', re.MULTILINE | re.DOTALL)


def _codex_station_table(path):
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return None
    found = TABLE.search(text)
    return found.group(1) if found else None


def foreign_machine_wiring():
    """Each entry of the machine ship's wiring that runs another checkout's run_agent.py: its hooks in
    ~/.claude/settings.json, its user-scope station, and the station table in ~/.codex/config.toml."""
    ours, found = str(install.RUN_AGENT), []
    settings = Path.home() / '.claude' / 'settings.json'
    try:
        data = json.loads(settings.read_text()) if settings.exists() else {}
    except (OSError, ValueError) as error:
        raise Refused(f'{settings} can\'t be read ({type(error).__name__}), so dock can\'t check the machine ship\'s hooks.')
    for event in install.HOOK_EVENTS:
        entries = (data.get('hooks') or {}).get(event) if isinstance(data, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            for hook in (entry.get('hooks') if isinstance(entry, dict) else None) or []:
                command = hook.get('command') if isinstance(hook, dict) else None
                for path in _run_agent_paths(install._hook_words(command), 'hook') if isinstance(command, str) else []:
                    if path != ours:
                        found.append((path, f'the {event} hook in {settings}: {command}'))
    got = _mcp_get(claims.machine_home())
    if got and 'user' in got[0].lower():
        for path in _run_agent_paths(shlex.split(got[1].split(':', 1)[1]) if ':' in got[1] else [], 'mcp'):
            if path != ours:
                found.append((path, 'the user-scope station tools (claude mcp get station, run from ~/.superyak)'))
    codex = Path.home() / '.codex' / 'config.toml'
    table = _codex_station_table(codex)
    if table:
        for path in re.findall(r'"([^"]*run_agent\.py)"', table):
            if path != ours:
                found.append((path, f'the [mcp_servers.station] table in {codex}'))
    return found


def check_machine_wiring():
    """R10: the stand-down and the MCP refusals live in the machine ship's code, so every piece of its wiring must run
    this checkout's. Docking the machine ship again doesn't fix a foreign entry (install_hooks replaces only this
    checkout's hooks; register_claude and register_codex skip an existing station), so the entries are named."""
    found = foreign_machine_wiring()
    if not found:
        return
    others = sorted({str(Path(path).parents[1]) for path, _ in found})
    listed = '\n'.join(f'  - {where}, which runs {path}' for path, where in found)
    raise Refused(
        f'The machine ship\'s wiring runs another checkout ({", ".join(others)}), not this one ({CHECKOUT}, whose '
        f'agent is {install.RUN_AGENT}). The '
        f'project ship\'s stand-down lives in the machine ship\'s code, so it must be this checkout\'s. Entries:\n'
        f'{listed}\nFix it one of two ways:\n'
        f'  1. remove those entries (the hook entries from ~/.claude/settings.json, `claude mcp remove --scope user '
        f'station`, the [mcp_servers.station] table from ~/.codex/config.toml), then dock the machine ship again from '
        f'this checkout, then this project dock;\n'
        f'  2. or run this project dock from the other checkout, where the same check runs against its code.')


# ---------- the Codex profile (S5, R20) ----------

def write_codex_profile(path, argv, config):
    """Only the station table of ~/.codex/<name>.config.toml: added when absent, left when it names this home,
    refused when it names another. Returns the bytes before (None when the file didn't exist)."""
    path = Path(path)
    before = path.read_bytes() if path.exists() else None
    table = _codex_station_table(path)
    if table is not None:
        if f'"{config}"' not in table:
            raise Refused(f'{path} has a station table for another home. Remove that table, then dock again.')
        return before
    install.register_codex(path, 'station', argv)
    return before


# ---------- the dock ----------

class ProjectDock:
    def __init__(self, ship, project, out=print):
        self.ship, self.project, self.out = ship, Path(project), out
        self.home = claims.project_home(ship)
        self.config = self.home / 'station.json'

    def checks(self):
        """S9's refusal checks, writing nothing: the mode and name (R2), the root (R3), no other ship's claim on it
        (full or partial), the machine ship's checkout (R10) and the git checks (R4). Returns the repository."""
        claims.check_mode(self.ship, None, self.project)
        repo = claims.project_root(self.project)
        if repo is None:
            raise Refused(f'{self.project} is in no repository (or one this dock can\'t read: a submodule, a bare '
                          'repository\'s worktree and a --separate-git-dir checkout count as none).')
        try:
            entries = claims.read_registry()
        except claims.Unreadable as error:
            raise Refused(f'{error}; fix it before docking.') from None
        for entry in entries:
            if entry['ship'] != self.ship and claims.match(entry, repo.root):
                raise Refused(f'{repo.root} is claimed by {entry["ship"]!r} ({claims.match(entry, repo.root)} match). '
                              'A repository has one claim.')
        check_machine_wiring()
        git_checks(repo)
        return repo

    def cleanup(self, error, rolled_back=False):
        """R9: what failed, that the ship exists on the station, and how to clean up; station.json is kept."""
        pending = read_json(self.home / 'docking.json') if (self.home / 'docking.json').exists() else None
        lines = [f'dock stopped: {error}']
        if rolled_back:
            lines.append('What this run wrote has been rolled back, the claim last.')
        if pending and isinstance(pending, dict) and pending.get('id'):
            short = str(pending['id'])[:6]
            lines.append(f'The ship {self.ship!r} has a docking request waiting on the station (request {short}). To clean '
                         f'up: delete {self.home / "docking.json"}, then run make station-deny ID={short} on the station '
                         f'host, or let it expire: a pending docking lasts 10 minutes.')
        else:
            lines.append(f'The ship {self.ship!r} exists on the station. Its key is kept in {self.config}, so after you fix '
                         f'the cause, dock again uses it with no new docking. To remove the ship instead, run '
                         f'agent/run_agent.py undock --home {self.home} from the superyak checkout; undock works with no '
                         'claim.')
        return '\n'.join(lines)

    def install(self, *, hook=False, service=False, client=None):
        """S9 after docking: the last checks and the claim in one hold of the lock (a reservation), then the excludes
        and their real check, the local tools, the hooks, the Codex profile and the service, in order. A failure
        after the claim rolls back this run's writes, the claim last."""
        with claims.registry_lock():
            repo = self.checks()
            claims.claim(self.ship, repo.root, held=True)
        undo = [lambda: claims.unclaim(self.home)]
        try:
            before = append_excludes(repo)
            undo.append(lambda: _restore(repo.common / 'info' / 'exclude', before))
            real_exclude_check(repo)
            argv = [sys.executable, str(install.RUN_AGENT), 'mcp', '--config', str(self.config)]
            undo.append(lambda: subprocess.run(['claude', 'mcp', 'remove', '--scope', 'local', 'station'], cwd=str(repo.root),
                                               capture_output=True))
            self._local_station(repo, argv)
            settings = repo.root / '.claude' / 'settings.local.json'
            backup = self.home / 'settings.local.json.bak-superyak'
            settings_before = settings.read_bytes() if settings.exists() else None
            backup_existed = backup.exists()
            undo.append(lambda: (_restore(settings, settings_before),
                                 None if backup_existed else backup.unlink(missing_ok=True)))
            settings.parent.mkdir(exist_ok=True)
            install.install_hooks(settings, self.config, messages=hook, backup=backup)
            if install.shutil.which('codex') or (Path.home() / '.codex').exists():
                profile = Path.home() / '.codex' / f'{self.ship}.config.toml'
                profile_before = profile.read_bytes() if profile.exists() else None
                undo.append(lambda: _restore(profile, profile_before))
                write_codex_profile(profile, argv, self.config)
            run_mcp = self.home / 'run-mcp.json'
            run_mcp_before = run_mcp.read_bytes() if run_mcp.exists() else None
            undo.append(lambda: _restore(run_mcp, run_mcp_before))
            write_private(run_mcp, install.run_mcp_config(self.config))
            if service and install.start_at_newest_mention(self.config, self.home / 'ship-state.json', client, self.out):
                names = install.service_names(self.home)
                undo.append(lambda: install.remove_service(names))
                install.install_service([sys.executable, str(install.RUN_AGENT), 'watch', '--config', str(self.config),
                                         '--state', str(self.home / 'ship-state.json'), '--mcp-config', str(run_mcp)],
                                        self.out, names=names)
        except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
            for step in reversed(undo):
                try:
                    step()
                except Exception:  # noqa: BLE001 - every undo step runs; the claim goes last
                    pass
            refused = Refused(f'{error}')
            refused.rolled_back = True
            raise refused from error
        self.out(f'{self.ship} is docked as a project ship. Home: {self.home}. Project: {repo.root}.')
        self.out(f'Claude Code sessions started in that project or any of its worktrees act as {self.ship}; '
                 'sessions started anywhere else act as the machine ship.')
        self.out(f'Codex sessions there need `codex -p {self.ship}`: plain codex is the machine ship, which refuses '
                 'inside this project.')
        return repo

    def _local_station(self, repo, argv):
        """R7: a local `station` registered from the root, replacing a stale local one, then confirmed: local scope,
        and args that carry this home."""
        if not install.shutil.which('claude'):
            raise Refused('Claude Code (claude) isn\'t on PATH, so the project\'s station tools can\'t be registered.')
        subprocess.run(['claude', 'mcp', 'remove', '--scope', 'local', 'station'], cwd=str(repo.root), capture_output=True)
        subprocess.run(['claude', 'mcp', 'add', '--scope', 'local', 'station', '--', *argv], cwd=str(repo.root),
                       check=True, capture_output=True)
        got = _mcp_get(repo.root)
        if not got or 'local' not in got[0].lower() or f'--config {self.config}' not in got[1]:
            raise Refused(f'claude mcp get station in {repo.root} doesn\'t show this ship\'s local tools (scope '
                          f'{got[0] if got else "none"!r}).')
