"""Shared fakes for many ships on one machine (D7): a fake machine whose HOME is a temporary folder, whose
subprocess calls are recorded with their working directory, and whose `claude mcp` keeps user and local entries the
way Claude Code does (local entries keyed by the project root the command ran in). Git runs for real, isolated from
the machine's own config (R11)."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from superyak_agent import install
from superyak_agent.station import write_private

REAL_RUN = subprocess.run      # git runs for real even while a FakeMachine stands in for everything else


def isolate_git(monkeypatch, tmp_path):
    """R11: no global or system git config, so a machine's global ignore can't make a test pass."""
    config_home, global_config = tmp_path / 'xdg', tmp_path / 'gitconfig-empty'
    config_home.mkdir(exist_ok=True)
    global_config.write_text('')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config_home))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(global_config))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        monkeypatch.delenv(name, raising=False)


def git(*args, cwd):
    env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@example.com'}
    return REAL_RUN(['git', *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def make_repo(path, worktree=None):
    """A repository with one commit, a subdirectory and, optionally, a linked worktree. Returns its real root."""
    path.mkdir(parents=True)
    git('init', '-q', '-b', 'main', cwd=path)
    (path / 'sub').mkdir()
    (path / 'sub' / 'file.txt').write_text('x\n')
    git('add', '-A', cwd=path)
    git('commit', '-q', '-m', 'first', cwd=path)
    if worktree is not None:
        git('worktree', 'add', '-q', str(worktree), '-b', 'side', cwd=path)
    return Path(os.path.realpath(path))


class FakeMachine:
    """HOME is `<tmp>/home`; `subprocess.run` in install records (argv, cwd) and answers for claude, codex,
    systemctl, launchctl and loginctl; `shutil.which` finds only `tools`. `claude mcp` keeps a user entry and local
    entries per project root, so `get` answers for the directory it runs in, as Claude Code does (M2)."""

    def __init__(self, monkeypatch, tmp_path, system='Linux', tools=('claude', 'codex'), fail=()):
        self.calls, self.fail, self.out, self.git_calls = [], fail, [], []
        self.home = tmp_path / 'home'
        self.home.mkdir(exist_ok=True)
        monkeypatch.setenv('HOME', str(self.home))
        monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
        monkeypatch.setattr(install.subprocess, 'run', self.run)
        monkeypatch.setattr(install.shutil, 'which', lambda name, *a, **kw: f'/fake/bin/{name}' if name in tools else None)
        monkeypatch.setattr(install, 'platform', SimpleNamespace(system=lambda: system))
        self.user_station, self.local_station = None, {}       # Claude Code's MCP entries
        self.config = self.home / '.superyak' / 'station.json'

    def dock_machine(self, ship='serenity', **extra):
        write_private(self.config, {'station': 'http://station', 'key': 'k', 'ship': ship, 'ship_name': ship.title(), **extra})
        return self.config

    def _project_of(self, cwd):
        here = Path(os.path.realpath(cwd or os.getcwd()))
        for root in self.local_station:
            if here == Path(root) or Path(root) in here.parents:
                return root
        return None

    def run(self, argv, **kwargs):
        argv = [str(a) for a in argv]
        cwd = kwargs.get('cwd')
        if Path(argv[0]).name == 'git':
            self.git_calls.append((argv, None if cwd is None else str(cwd), dict(kwargs.get('env') or {})))
            return REAL_RUN(argv, **kwargs)
        self.calls.append((argv, None if cwd is None else str(cwd)))
        name = Path(argv[0]).name
        if any(name == f[0] and argv[1:len(f)] == list(f[1:]) for f in self.fail):
            raise subprocess.CalledProcessError(1, argv)
        if name == 'claude' and argv[1:2] == ['mcp']:
            return self._claude_mcp(argv[2:], cwd)
        return subprocess.CompletedProcess(argv, 0, stdout='', stderr='')

    def _claude_mcp(self, args, cwd):
        project = self._project_of(cwd)
        if args[:1] == ['get']:
            if project is not None and args[1] == 'station':
                entry, scope = self.local_station[project], 'Local config'
            elif self.user_station is not None and args[1] == 'station':
                entry, scope = self.user_station, 'User config'
            else:
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='No MCP server named station')
            text = f'station:\n  Scope: {scope}\n  Command: {entry[0]}\n  Args: {" ".join(entry[1:])}\n'
            return subprocess.CompletedProcess(args, 0, stdout=text, stderr='')
        if args[:1] == ['add']:
            scope = args[args.index('--scope') + 1]
            argv = args[args.index('--') + 1:]
            if scope == 'user':
                self.user_station = argv
            else:
                self.local_station[str(Path(os.path.realpath(cwd)))] = argv
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
        if args[:1] == ['remove']:
            scope = args[args.index('--scope') + 1]
            if scope == 'user':
                self.user_station = None
            else:
                self.local_station.pop(str(Path(os.path.realpath(cwd))), None)
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
        return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

    def argvs(self):
        return [argv for argv, cwd in self.calls]

    def settings(self, path=None):
        path = path or self.home / '.claude' / 'settings.json'
        return json.loads(Path(path).read_text())


def hook_commands(settings_path, event):
    data = json.loads(Path(settings_path).read_text())
    return [h['command'] for entry in data.get('hooks', {}).get(event, []) for h in entry['hooks']]


PYTHON, RUN_AGENT = sys.executable, str(install.RUN_AGENT)
