import json
import os
from pathlib import Path
import subprocess
import time
import pytest
from superyak_agent.runs import ClaudeRunner, RunTimeout

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, subprocess, sys, time
from pathlib import Path
prompt = sys.stdin.read()
args = sys.argv[1:]
settings = json.loads(Path(args[args.index('--settings') + 1]).read_text())
with open(os.environ['FAKE_CLAUDE_LOG'], 'a') as log:
    log.write(json.dumps({'args': args, 'cwd': os.getcwd(), 'prompt': prompt, 'settings': settings,
                          'superyak_run': os.environ.get('SUPERYAK_RUN'), 'files': sorted(os.listdir('.')),
                          'secret_visible': os.path.exists('.engram/secret.txt')}) + '\\n')
behavior = os.environ.get('FAKE_CLAUDE', 'answer')
if behavior == 'fail':
    sys.exit(1)
if behavior == 'sleep':
    child = subprocess.Popen(['sleep', '30'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.environ.get('FAKE_CLAUDE_PIDFILE'):
        Path(os.environ['FAKE_CLAUDE_PIDFILE']).write_text(str(child.pid))
    time.sleep(5)
if behavior == 'edit':
    Path('NOTES.md').write_text('added by the ship\\n')
print('Added NOTES.md' if behavior == 'edit' else 'Here is my answer.')
'''


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(path)], check=True)
    (path / 'README.md').write_text('hello\n')
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'init'], check=True)
    return path


@pytest.fixture
def claude(tmp_path, monkeypatch):
    script = tmp_path / 'claude'
    script.write_text(FAKE_CLAUDE)
    script.chmod(0o755)
    log = tmp_path / 'claude.jsonl'
    monkeypatch.setenv('FAKE_CLAUDE_LOG', str(log))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))

    def calls():
        return [json.loads(line) for line in log.read_text().splitlines()]
    return str(script), calls


def runner(repo, tmp_path, script, **kw):
    config = {'ship': 'serenity', 'ship_name': 'Serenity', 'owner_id': 'u-andy', 'workspace': str(repo), 'machine': 'andy-mac'}
    return ClaudeRunner(config, tmp_path / 'runs', claude=script, memory_cap=False, **kw)


def branches(repo):
    return subprocess.run(['git', '-C', str(repo), 'branch', '--list', 'lighthouse/*', '--format=%(refname:short)'], capture_output=True, text=True).stdout.split()


def worktrees(repo):
    out = subprocess.run(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'], capture_output=True, text=True, check=True).stdout
    return [line.removeprefix('worktree ') for line in out.splitlines() if line.startswith('worktree ')]


def test_read_only_run_reads_only_the_workspace_with_no_shell_edits_or_web(repo, tmp_path, claude):
    script, calls = claude
    result = runner(repo, tmp_path, script).run('read', 'What is this?', 'm1')
    assert result.reply == 'Here is my answer.' and result.branch is None
    call = calls()[0]
    allow, deny = call['settings']['permissions']['allow'], call['settings']['permissions']['deny']
    snapshot = tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'read-m1'
    assert f'Read(/{snapshot}/**)' in allow and f'Read(/{repo}/**)' not in allow and 'Bash' not in allow
    assert 'mcp__adna' in allow and not any(rule.startswith('mcp__station') for rule in allow) and 'mcp__station' in deny
    assert {'Bash', 'Edit', 'Write', 'NotebookEdit', 'WebFetch', 'WebSearch'} <= set(deny)
    assert call['settings']['sandbox'] == {'enabled': False}
    assert Path(call['cwd']).resolve() == snapshot.resolve() and call['prompt'] == 'What is this?'
    assert call['args'][call['args'].index('--permission-mode') + 1] == 'dontAsk'


def test_runs_ignore_user_level_settings_and_tell_the_station_hook_to_stay_quiet(repo, tmp_path, claude, monkeypatch):
    script, calls = claude
    monkeypatch.delenv('SUPERYAK_RUN', raising=False)
    runner(repo, tmp_path, script).run('read', 'What is this?', 'm1')
    runner(repo, tmp_path, script).run('build', 'Add notes', 'm2')
    assert os.environ.get('SUPERYAK_RUN') is None  # the watcher process itself is not marked
    for call in calls():
        at = call['args'].index('--settings') + 2
        assert call['args'][at - 2:at + 2] == ['--settings', call['args'][at - 1], '--setting-sources', 'project,local']
        assert call['superyak_run'] == '1'


def test_builder_run_commits_on_its_own_branch_and_never_pushes(repo, tmp_path, claude, monkeypatch):
    script, calls = claude
    monkeypatch.setenv('FAKE_CLAUDE', 'edit')
    result = runner(repo, tmp_path, script).run('build', 'Add notes', 'm7')
    assert result.branch == 'lighthouse/serenity/m7' and result.commit and 'NOTES.md' in result.stat
    shown = subprocess.run(['git', '-C', str(repo), 'show', '--stat', '--format=%s', result.branch], capture_output=True, text=True).stdout
    assert shown.startswith('serenity: Added NOTES.md') and 'NOTES.md' in shown
    assert not (repo / 'NOTES.md').exists()
    worktree = tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'm7'
    assert not worktree.exists()
    settings = calls()[0]['settings']
    assert f'Edit(/{worktree}/**)' in settings['permissions']['allow'] and 'Bash(git push*)' in settings['permissions']['deny']
    assert settings['sandbox']['enabled'] is True
    allow, deny = settings['permissions']['allow'], settings['permissions']['deny']
    assert 'mcp__adna' in allow and not any(rule.startswith('mcp__station') for rule in allow) and 'mcp__station' in deny


def test_builder_run_without_changes_leaves_no_branch(repo, tmp_path, claude):
    script, _ = claude
    result = runner(repo, tmp_path, script).run('build', 'Just a question', 'm8')
    assert result.branch is None and branches(repo) == []


def test_failed_builder_run_cleans_up_so_a_retry_can_start(repo, tmp_path, claude, monkeypatch):
    script, _ = claude
    monkeypatch.setenv('FAKE_CLAUDE', 'fail')
    with pytest.raises(RuntimeError):
        runner(repo, tmp_path, script).run('build', 'Add notes', 'm9')
    assert branches(repo) == []
    monkeypatch.setenv('FAKE_CLAUDE', 'edit')
    assert runner(repo, tmp_path, script).run('build', 'Add notes', 'm9').branch == 'lighthouse/serenity/m9'


def test_a_run_over_its_time_limit_raises_run_timeout(repo, tmp_path, claude, monkeypatch):
    script, _ = claude
    monkeypatch.setenv('FAKE_CLAUDE', 'sleep')
    with pytest.raises(RunTimeout):
        runner(repo, tmp_path, script, limits={'read': 1, 'build': 1}).run('read', 'slow', 'm10')
    assert not (tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'read-m10').exists() and worktrees(repo) == [str(repo)]


def test_linux_runs_are_wrapped_in_a_memory_capped_scope(repo, tmp_path, claude):
    script, _ = claude
    capped = ClaudeRunner({'ship': 'serenity', 'owner_id': 'u', 'workspace': str(repo)}, tmp_path / 'runs', claude=script, memory_cap=True)
    command = capped._command(tmp_path / 's.json')
    assert command[:8] == ['systemd-run', '--user', '--scope', '--quiet', '-p', 'MemoryMax=2G', '-p', 'MemorySwapMax=0']


def test_runtime_max_sec_follows_the_limit_after_the_original_prefix(repo, tmp_path, claude):
    script, _ = claude
    capped = ClaudeRunner({'ship': 'serenity', 'owner_id': 'u', 'workspace': str(repo)}, tmp_path / 'runs', claude=script, memory_cap=True)
    command = capped._command(tmp_path / 's.json', limit=300)
    assert command[:8] == ['systemd-run', '--user', '--scope', '--quiet', '-p', 'MemoryMax=2G', '-p', 'MemorySwapMax=0']
    assert command[8:10] == ['-p', 'RuntimeMaxSec=330'] and command[10] == script
    assert 'RuntimeMaxSec=330' not in ' '.join(capped._command(tmp_path / 's.json')[:10])


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


def test_a_build_run_over_its_time_limit_ends_every_process_and_cleans_up(repo, tmp_path, claude, monkeypatch):
    script, _ = claude
    pidfile = tmp_path / 'child.pid'
    monkeypatch.setenv('FAKE_CLAUDE', 'sleep')
    monkeypatch.setenv('FAKE_CLAUDE_PIDFILE', str(pidfile))
    started = time.monotonic()
    with pytest.raises(RunTimeout):
        runner(repo, tmp_path, script, limits={'read': 1, 'build': 1}).run('build', 'slow', 'm11')
    child = int(pidfile.read_text())
    try:
        for _ in range(50):
            if not alive(child):
                break
            time.sleep(0.1)
        assert not alive(child)
    finally:
        if alive(child):
            os.kill(child, 9)
    assert time.monotonic() - started < 15
    assert branches(repo) == []
    assert not (tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'm11').exists()


def private_repo(repo):
    """A repository whose workspace holds private files git does not track."""
    (repo / '.gitignore').write_text('.engram/\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.gitignore'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'ignore engram'], check=True)
    (repo / '.engram').mkdir()
    (repo / '.engram' / 'secret.txt').write_text('hunter2\n')
    (repo / '.envrc').write_text('export TOKEN=hunter2\n')


def test_read_only_run_sees_a_throwaway_worktree_of_head_not_the_private_files_in_the_workspace(repo, tmp_path, claude):
    script, calls = claude
    private_repo(repo)
    result = runner(repo, tmp_path, script).run('read', 'What is this?', 'm20')
    assert result.reply == 'Here is my answer.'
    call = calls()[0]
    snapshot = tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'read-m20'
    assert Path(call['cwd']).resolve() == snapshot.resolve() and Path(call['cwd']).resolve() != repo.resolve()
    assert call['secret_visible'] is False and '.engram' not in call['files'] and '.envrc' not in call['files']
    assert 'README.md' in call['files'] and '.gitignore' in call['files']
    allow = call['settings']['permissions']['allow']
    assert f'Read(/{snapshot}/**)' in allow and f'Grep(/{snapshot}/**)' in allow and f'Glob(/{snapshot}/**)' in allow
    assert not any(str(repo) in rule for rule in allow)
    # Always removed afterwards, leaving the workspace untouched: no worktree, no branch, the private files still there.
    assert not snapshot.exists() and worktrees(repo) == [str(repo)] and branches(repo) == []
    assert (repo / '.engram' / 'secret.txt').read_text() == 'hunter2\n' and (repo / '.envrc').exists()


def test_the_snapshot_is_of_head_so_uncommitted_edits_are_not_shown(repo, tmp_path, claude):
    script, calls = claude
    (repo / 'README.md').write_text('uncommitted edit\n')
    (repo / 'scratch.txt').write_text('untracked\n')
    runner(repo, tmp_path, script).run('read', 'What is this?', 'm21')
    assert calls()[0]['files'] == ['.git', 'README.md']


def test_a_failed_read_run_removes_its_worktree_and_a_stale_one_does_not_block_a_retry(repo, tmp_path, claude, monkeypatch):
    script, calls = claude
    snapshot = tmp_path / 'home' / '.superyak' / 'worktrees' / 'serenity' / 'read-m22'
    monkeypatch.setenv('FAKE_CLAUDE', 'fail')
    with pytest.raises(RuntimeError):
        runner(repo, tmp_path, script).run('read', 'What is this?', 'm22')
    assert not snapshot.exists() and worktrees(repo) == [str(repo)]
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-q', '--detach', str(snapshot), 'HEAD'], check=True)  # a killed watcher's leftover
    (snapshot / 'leftover.txt').write_text('x')
    monkeypatch.setenv('FAKE_CLAUDE', 'answer')
    assert runner(repo, tmp_path, script).run('read', 'What is this?', 'm22').reply == 'Here is my answer.'
    assert 'leftover.txt' not in calls()[-1]['files'] and not snapshot.exists() and worktrees(repo) == [str(repo)]


def test_a_workspace_that_is_not_a_repository_is_used_in_place(tmp_path, claude):
    script, calls = claude
    workspace = tmp_path / 'odo-workspace'
    workspace.mkdir()
    result = runner(workspace, tmp_path, script).run('read', 'Where is the door?', 'm23')
    assert result.reply == 'Here is my answer.'
    call = calls()[0]
    assert Path(call['cwd']).resolve() == workspace.resolve() and f'Read(/{workspace}/**)' in call['settings']['permissions']['allow']
    assert not (tmp_path / 'home' / '.superyak' / 'worktrees').exists()


def test_a_plain_folder_inside_some_other_repository_is_not_snapshotted(repo, tmp_path, claude):
    script, calls = claude
    workspace = repo / 'odo-workspace'   # e.g. an empty workspace under a home directory that is itself a repository
    workspace.mkdir()
    runner(workspace, tmp_path, script).run('read', 'Where is the door?', 'm24')
    assert Path(calls()[0]['cwd']).resolve() == workspace.resolve() and worktrees(repo) == [str(repo)]


def test_extra_read_paths_are_readable_in_place_in_read_only_runs_only(tmp_path, claude, monkeypatch):
    script, calls = claude
    workspace, lattice = tmp_path / 'odo-workspace', tmp_path / 'aDNA'
    workspace.mkdir()
    (lattice / 'Nebula.aDNA').mkdir(parents=True)
    config = {'ship': 'odo', 'ship_name': 'Odo', 'owner_id': None, 'workspace': str(workspace), 'read_paths': [str(lattice)]}
    ClaudeRunner(config, tmp_path / 'runs', claude=script, memory_cap=False).run('read', 'What is in the lattice?', 'm1')
    call = calls()[0]
    allow, deny = call['settings']['permissions']['allow'], call['settings']['permissions']['deny']
    root = lattice.resolve()
    assert {f'Read(/{root}/**)', f'Grep(/{root}/**)', f'Glob(/{root}/**)'} <= set(allow)
    assert {f'Read(/{root}/**/.git/**)', f'Read(/{root}/**/.claude/**)', f'Grep(/{root}/**/.git/**)', f'Grep(/{root}/**/.claude/**)'} <= set(deny)
    assert Path(call['cwd']).resolve() == workspace.resolve()  # the lattice's own .claude settings never load
    system_prompt = call['args'][call['args'].index('--append-system-prompt') + 1]
    assert str(root) in system_prompt and system_prompt.startswith('You are Odo')


def test_builder_runs_do_not_get_extra_read_paths(repo, tmp_path, claude, monkeypatch):
    script, calls = claude
    monkeypatch.setenv('FAKE_CLAUDE', 'edit')
    lattice = tmp_path / 'aDNA'
    lattice.mkdir()
    config = {'ship': 'serenity', 'ship_name': 'Serenity', 'owner_id': 'u-andy', 'workspace': str(repo), 'read_paths': [str(lattice)]}
    ClaudeRunner(config, tmp_path / 'runs', claude=script, memory_cap=False).run('build', 'Add notes', 'm2')
    assert not any(str(lattice.resolve()) in rule for rule in calls()[0]['settings']['permissions']['allow'])


def test_instructions_follow_the_persona_in_one_system_prompt_argument(tmp_path):
    runner = ClaudeRunner({'workspace': str(tmp_path), 'ship': 'serenity', 'owner_id': 'u1'}, tmp_path / 'runs', memory_cap=False)
    plain = runner._command(tmp_path / 's.json')
    assert plain[plain.index('--append-system-prompt') + 1] == runner.persona
    command = runner._command(tmp_path / 's.json', instructions='=== Instructions: X ===\nRun tests.')
    assert command[command.index('--append-system-prompt') + 1] == runner.persona + '\n\n=== Instructions: X ===\nRun tests.'
    assert command.count('--append-system-prompt') == 1


def test_a_nul_never_reaches_the_command_line(tmp_path):
    """Break caught: Popen refuses an argument with a NUL, so three runs failed and the mention got the fallback note."""
    runner = ClaudeRunner({'workspace': str(tmp_path), 'ship': 'serenity', 'ship_name': 'Sere\x00nity', 'owner_id': 'u1'},
                          tmp_path / 'runs', memory_cap=False)
    assert '\x00' in runner.persona
    for instructions in ('', '=== Instructions: X\x00 ===\nRun\x00 tests.'):
        command = runner._command(tmp_path / 's.json', instructions=instructions)
        assert not any('\x00' in str(arg) for arg in command)
    assert command[command.index('--append-system-prompt') + 1].endswith('\n\n=== Instructions: X ===\nRun tests.')
    assert 'You are Serenity' in command[command.index('--append-system-prompt') + 1]
