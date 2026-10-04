import json
from pathlib import Path
import subprocess
import pytest
from superyak_agent.runs import ClaudeRunner, RunTimeout

FAKE_CLAUDE = '''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
prompt = sys.stdin.read()
args = sys.argv[1:]
settings = json.loads(Path(args[args.index('--settings') + 1]).read_text())
with open(os.environ['FAKE_CLAUDE_LOG'], 'a') as log:
    log.write(json.dumps({'args': args, 'cwd': os.getcwd(), 'prompt': prompt, 'settings': settings}) + '\\n')
behavior = os.environ.get('FAKE_CLAUDE', 'answer')
if behavior == 'fail':
    sys.exit(1)
if behavior == 'sleep':
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


def test_read_only_run_reads_only_the_workspace_with_no_shell_edits_or_web(repo, tmp_path, claude):
    script, calls = claude
    result = runner(repo, tmp_path, script).run('read', 'What is this?', 'm1')
    assert result.reply == 'Here is my answer.' and result.branch is None
    call = calls()[0]
    allow, deny = call['settings']['permissions']['allow'], call['settings']['permissions']['deny']
    assert f'Read(/{repo}/**)' in allow and 'Bash' not in allow
    assert {'Bash', 'Edit', 'Write', 'NotebookEdit', 'WebFetch', 'WebSearch'} <= set(deny)
    assert call['settings']['sandbox'] == {'enabled': False}
    assert Path(call['cwd']).resolve() == repo.resolve() and call['prompt'] == 'What is this?'
    assert call['args'][call['args'].index('--permission-mode') + 1] == 'dontAsk'


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


def test_linux_runs_are_wrapped_in_a_memory_capped_scope(repo, tmp_path, claude):
    script, _ = claude
    capped = ClaudeRunner({'ship': 'serenity', 'owner_id': 'u', 'workspace': str(repo)}, tmp_path / 'runs', claude=script, memory_cap=True)
    command = capped._command(tmp_path / 's.json')
    assert command[:8] == ['systemd-run', '--user', '--scope', '--quiet', '-p', 'MemoryMax=2G', '-p', 'MemorySwapMax=0']
