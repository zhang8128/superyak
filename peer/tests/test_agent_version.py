import subprocess

import pytest

from superyak_peer.agent_version import AgentHistory, agent_update, find_checkout, load, read_history


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, files, message):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


RUNTIME = {'agent/superyak_agent/a.py': 'v1\n', 'agent/run_agent.py': 'run\n', 'team/superyak_team/__init__.py': '',
           'team/superyak_team/teamlib.py': 'lib\n', 'team/superyak_team/workers.py': 'w\n'}


@pytest.fixture
def history_repo(tmp_path):
    """O: before any runtime file. P: runtime v1. A: runtime v2. B: docs only. T: only agent/tests and agent/README.md.
    C: docs only, HEAD, with refs/remotes/origin/main at C (spec requirement 2)."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    o = commit(repo, {'README.md': 'old\n'}, 'O')
    p = commit(repo, RUNTIME, 'P')
    a = commit(repo, {'agent/superyak_agent/a.py': 'v2\n'}, 'A')
    b = commit(repo, {'docs/x.md': 'b\n'}, 'B')
    t = commit(repo, {'agent/tests/test_a.py': 't\n', 'agent/README.md': 'r\n'}, 'T')
    c = commit(repo, {'docs/x.md': 'c\n'}, 'C')
    git(repo, 'update-ref', 'refs/remotes/origin/main', c)
    (repo / 'peer' / 'superyak_peer').mkdir(parents=True)
    return repo, dict(O=o, P=p, A=a, B=b, T=t, C=c)


def test_behind_holds_only_ancestors_whose_runtime_files_differ(history_repo):
    repo, c = history_repo
    history, reason = read_history(repo)
    assert reason is None
    assert history.station == c['C'][:12]
    assert history.behind == frozenset({c['P'][:12], c['O'][:12]})  # O has no runtime file at all: "missing" differs


def test_the_limit_bounds_how_far_back_the_read_goes(history_repo):
    repo, c = history_repo
    history, _ = read_history(repo, limit=3)  # C, T, B: all share HEAD's runtime files
    assert history.behind == frozenset()


def test_agent_update_names_the_station_only_for_a_client_behind(history_repo):
    repo, c = history_repo
    history, _ = read_history(repo)
    for name in ('C', 'T', 'B', 'A'):
        assert agent_update(history, {'name': 's', 'client': f'hook/{c[name][:12]}', 'mode': None}) is None, name
    assert agent_update(history, {'name': 's', 'client': f'hook/{c["P"][:12]}', 'mode': None}) == {'station': c['C'][:12]}


@pytest.mark.parametrize('presence', [None, {'name': 's', 'client': 'unknown', 'mode': None},
                                      {'name': 's', 'client': 'hook/0123456789ab', 'mode': None}])
def test_no_presence_unknown_or_a_commit_outside_the_history_gets_nothing(history_repo, presence):
    repo, _ = history_repo
    history, _ = read_history(repo)
    assert agent_update(history, presence) is None


def test_no_history_means_no_key():
    assert agent_update(None, {'name': 's', 'client': 'hook/0123456789ab', 'mode': None}) is None


def test_find_checkout_needs_git_and_agent(history_repo, tmp_path):
    repo, _ = history_repo
    module = repo / 'peer' / 'superyak_peer' / 'agent_version.py'
    assert find_checkout(module) == repo.resolve()
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert find_checkout(lone / 'agent_version.py') is None


def test_a_worktree_checkout_is_found_and_read(history_repo, tmp_path):
    repo, c = history_repo
    tree = tmp_path / 'wt'
    git(repo, 'worktree', 'add', '-q', str(tree), c['C'])
    (tree / 'peer' / 'superyak_peer').mkdir(parents=True)
    assert (tree / '.git').is_file()
    assert find_checkout(tree / 'peer' / 'superyak_peer' / 'agent_version.py') == tree.resolve()
    history, reason = read_history(tree)
    assert reason is None and history.station == c['C'][:12]


def test_a_detached_head_reads(history_repo):
    repo, c = history_repo
    git(repo, 'checkout', '-q', '--detach', c['B'])
    history, reason = read_history(repo)
    assert reason is None and history.station == c['B'][:12] and c['P'][:12] in history.behind


@pytest.mark.parametrize('error', [FileNotFoundError('git'), subprocess.TimeoutExpired('git', 10),
                                   subprocess.CalledProcessError(128, 'git')])
def test_git_missing_slow_or_failing_turns_the_check_off(history_repo, error):
    repo, _ = history_repo

    def run(*args, **kwargs):
        raise error
    history, reason = read_history(repo, run=run)
    assert history is None and reason


def test_the_ten_second_budget_is_shared_by_every_call(history_repo):
    repo, _ = history_repo
    times = iter([0.0, 4.0, 8.0, 12.0, 16.0])
    seen = []

    def run(argv, **kwargs):
        seen.append(kwargs['timeout'])
        return subprocess.run(argv, **kwargs)
    history, reason = read_history(repo, run=run, clock=lambda: next(times))
    assert history is None and 'time' in reason
    assert seen == [6.0, 2.0]  # 10 - 4, then 10 - 8; the third call finds no time left


def test_load_logs_one_line_when_off(tmp_path, capsys):
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert load(lone / 'agent_version.py') is None
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'version check off' in err


def test_load_reads_a_real_checkout_and_says_it_is_on(history_repo, capsys):
    repo, c = history_repo
    history = load(repo / 'peer' / 'superyak_peer' / 'agent_version.py')
    assert history == AgentHistory(c['C'][:12], frozenset({c['P'][:12], c['O'][:12]}))
    assert capsys.readouterr().err == (f'superyak: version check on: {c["C"][:12]} (ships on any of 2 older agent '
                                       'versions are told to update)\n')


def test_load_turns_off_with_one_line_when_reading_raises(history_repo, monkeypatch, capsys):
    from superyak_peer import agent_version
    repo, _ = history_repo

    def boom(*args, **kwargs):
        raise ValueError('odd')
    monkeypatch.setattr(agent_version, 'read_history', boom)
    assert load(repo / 'peer' / 'superyak_peer' / 'agent_version.py') is None
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'unexpected error (ValueError)' in err


def test_a_failing_git_says_what_it_printed(history_repo):
    repo, _ = history_repo

    def run(*args, **kwargs):
        raise subprocess.CalledProcessError(128, 'git', stderr='fatal: not a git repository\n')
    history, reason = read_history(repo, run=run)
    assert history is None and 'git failed (CalledProcessError): fatal: not a git repository' in reason


def test_a_team_runtime_change_makes_earlier_commits_behind(tmp_path):
    repo = tmp_path / 'repo2'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    p = commit(repo, RUNTIME, 'P')
    x = commit(repo, {'team/superyak_team/teamlib.py': 'lib v2\n'}, 'X')
    git(repo, 'update-ref', 'refs/remotes/origin/main', x)
    history, reason = read_history(repo)
    assert reason is None and history.behind == frozenset({p[:12]})


def test_a_runtime_path_missing_from_head_and_its_ancestors_alike_is_ignored(tmp_path):
    repo = tmp_path / 'repo3'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    p = commit(repo, {k: v for k, v in RUNTIME.items() if not k.endswith('workers.py')}, 'P')
    c = commit(repo, {'docs/x.md': 'c\n'}, 'C')
    git(repo, 'update-ref', 'refs/remotes/origin/main', c)
    history, reason = read_history(repo)
    assert reason is None and history.behind == frozenset()  # workers.py is missing from both: not a difference


def test_head_not_on_origin_main_turns_the_check_off(history_repo):
    repo, c = history_repo
    git(repo, 'checkout', '-q', '-b', 'feature')
    commit(repo, {'agent/superyak_agent/a.py': 'feature\n'}, 'F')
    assert read_history(repo) == (None, 'HEAD is not on origin/main')


def test_no_origin_main_turns_the_check_off_with_gits_reason(history_repo):
    repo, _ = history_repo
    git(repo, 'update-ref', '-d', 'refs/remotes/origin/main')
    history, reason = read_history(repo)
    assert history is None and reason.startswith('git failed (CalledProcessError): ') and len(reason) > 33


def test_an_unexpected_answer_from_git_turns_the_check_off(history_repo):
    repo, c = history_repo

    def run(argv, **kwargs):
        if 'cat-file' in argv:
            return subprocess.CompletedProcess(argv, 0, stdout='only-one-line\n', stderr='')
        return subprocess.run(argv, **kwargs)
    assert read_history(repo, run=run) == (None, 'git answered in an unexpected form')


def test_load_never_raises_when_finding_the_checkout_raises(history_repo, monkeypatch, capsys):
    from superyak_peer import agent_version
    repo, _ = history_repo

    def boom(*args, **kwargs):
        raise PermissionError('no')
    monkeypatch.setattr(agent_version, 'find_checkout', boom)
    assert load(repo / 'peer' / 'superyak_peer' / 'agent_version.py') is None
    err = capsys.readouterr().err
    assert err.count('\n') == 1 and 'unexpected error (PermissionError)' in err


def test_load_never_raises_when_printing_raises(tmp_path):
    class Broken:
        def write(self, text):
            raise OSError('stderr is gone')

        def flush(self):
            raise OSError('stderr is gone')
    lone = tmp_path / 'lone' / 'peer' / 'superyak_peer'
    lone.mkdir(parents=True)
    assert load(lone / 'agent_version.py', err=Broken()) is None
