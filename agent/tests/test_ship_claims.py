"""Many ships on one machine (D7), build step 2: the root reader (R17), the claims registry, its lock, <home>/claim.json
and their write order (R8), the missing-registry rule (R16), and `status` naming an unreadable registry first."""
import json
import os
from pathlib import Path
import subprocess
import pytest
from superyak_agent import __main__ as cli, claims
from superyak_agent.station import write_private
from ships_fakes import git, isolate_git, make_repo


@pytest.fixture
def home(monkeypatch, tmp_path):
    h = tmp_path / 'home'
    h.mkdir()
    monkeypatch.setenv('HOME', str(h))
    return h


def forbid_git(monkeypatch, tmp_path):
    """The reader must never run git: a failing `git` first on PATH, and subprocess refusing to run anything."""
    bin_dir = tmp_path / 'failing-bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / 'git').write_text('#!/bin/sh\nexit 97\n')
    (bin_dir / 'git').chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}{os.pathsep}{os.environ["PATH"]}')

    def refuse(*a, **kw):
        raise AssertionError('the root reader ran a process')
    monkeypatch.setattr(subprocess, 'run', refuse)
    monkeypatch.setattr(subprocess, 'Popen', refuse)


def test_project_root_reader_layouts(monkeypatch, tmp_path):
    """R17, S6: the main checkout and a subdirectory, a worktree through commondir, a relative gitdir, a broken
    back-link, a submodule, a bare repository's worktree, a --separate-git-dir checkout and an unreadable .git."""
    isolate_git(monkeypatch, tmp_path)
    root = make_repo(tmp_path / 'repo', worktree=tmp_path / 'wt')
    wt = Path(os.path.realpath(tmp_path / 'wt'))
    # a relative gitdir: the same worktree reached through a .git file that names its gitdir relatively
    rel = tmp_path / 'wt-rel'
    git('worktree', 'add', '-q', str(rel), '-b', 'rel', cwd=root)
    rel_gitdir = Path((rel / '.git').read_text().split(':', 1)[1].strip())
    (rel / '.git').write_text('gitdir: ' + os.path.relpath(rel_gitdir, os.path.realpath(rel)) + '\n')
    # a broken back-link: a worktree whose gitdir names another .git file
    broken = tmp_path / 'wt-broken'
    git('worktree', 'add', '-q', str(broken), '-b', 'broken', cwd=root)
    broken_gitdir = Path((broken / '.git').read_text().split(':', 1)[1].strip())
    (broken_gitdir / 'gitdir').write_text(str(tmp_path / 'somewhere-else' / '.git') + '\n')
    # a submodule-shaped checkout: .git file into <super>/.git/modules/<name>
    sub = make_repo(tmp_path / 'super') / 'mod'
    modules = tmp_path / 'super' / '.git' / 'modules' / 'mod'
    modules.parent.mkdir()
    git('clone', '-q', '--separate-git-dir', str(modules), str(root), str(sub), cwd=tmp_path)
    # a bare repository with a worktree
    git('clone', '-q', '--bare', str(root), str(tmp_path / 'bare.git'), cwd=tmp_path)
    git('worktree', 'add', '-q', str(tmp_path / 'bare-wt'), 'main', cwd=tmp_path / 'bare.git')
    # --separate-git-dir
    git('clone', '-q', '--separate-git-dir', str(tmp_path / 'sep-store'), str(root), str(tmp_path / 'sep'), cwd=tmp_path)
    unreadable = make_repo(tmp_path / 'locked-wt-host')
    locked = tmp_path / 'locked'
    git('worktree', 'add', '-q', str(locked), '-b', 'locked', cwd=unreadable)
    forbid_git(monkeypatch, tmp_path)

    def answer(start):
        found = claims.project_root(start)
        return None if found is None else (found.root, found.common)
    assert answer(root) == answer(root / 'sub') == (root, root / '.git')
    assert answer(wt) == answer(wt / 'sub') == (root, root / '.git')
    assert answer(rel) == (root, root / '.git')
    assert answer(broken) is None
    assert answer(sub) is None
    assert answer(tmp_path / 'bare-wt') is None
    assert answer(tmp_path / 'sep') is None
    assert answer(tmp_path / 'not-a-repo-at-all') is None
    (locked / '.git').chmod(0)
    try:
        assert answer(locked) is None
    finally:
        (locked / '.git').chmod(0o644)


def entry(ship, root, dev=None, ino=None):
    st = os.stat(root)
    return {'ship': ship, 'home': str(claims.project_home(ship)), 'root': str(root),
            'dev': st.st_dev if dev is None else dev, 'ino': st.st_ino if ino is None else ino}


@pytest.mark.parametrize('content', [
    '{not json',
    '{"ship": "x"}',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": 1}]',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": 1, "ino": 2, "extra": 3}]',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": true, "ino": 2}]',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": "1", "ino": 2}]',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": 1, "ino": 2}, {"ship": "a", "home": "/h2", "root": "/r2", "dev": 1, "ino": 3}]',
    '[{"ship": "a", "home": "/h", "root": "/r", "dev": 1, "ino": 2}, {"ship": "b", "home": "/h2", "root": "/r", "dev": 1, "ino": 3}]',
])
def test_a_registry_that_fails_its_schema_is_unreadable(home, content):
    write_private(claims.registry_path(), [])
    claims.registry_path().write_text(content)
    with pytest.raises(claims.Unreadable) as refused:
        claims.read_registry()
    assert str(claims.registry_path()) in str(refused.value)


def test_a_missing_registry_is_unreadable_only_while_a_claim_json_exists(home, tmp_path):
    """R16, Rio Grande's required edit 2: a project home with only station.json (docked, or stopped before its claim)
    never makes a missing registry unreadable, so a first project dock can't refuse itself."""
    write_private(claims.project_home('serenity-bricks') / 'station.json', {'ship': 'serenity-bricks', 'key': 'k'})
    assert claims.read_registry() == []
    write_private(claims.project_home('serenity-bricks') / 'claim.json', entry('serenity-bricks', tmp_path))
    with pytest.raises(claims.Unreadable) as refused:
        claims.read_registry()
    assert 'claim.json' in str(refused.value)


class Lock:
    """A fake registry lock that records whether it is held, so writes can be checked to happen inside one hold."""
    def __init__(self):
        self.held, self.holds = False, 0

    def __call__(self):
        lock = self

        class Hold:
            def __enter__(self):
                assert not lock.held
                lock.held, lock.holds = True, lock.holds + 1

            def __exit__(self, *exc):
                lock.held = False
        return Hold()


def test_claims_are_written_and_removed_in_one_lock_hold_registry_first_and_never_deleted(monkeypatch, home, tmp_path):
    """R8: adding writes the registry entry, then claim.json; removing deletes claim.json, then the entry; each inside
    one hold of the lock. The last removal leaves [] and the registry file stays."""
    lock, writes = Lock(), []
    monkeypatch.setattr(claims, 'registry_lock', lock)
    real_write = claims.write_private

    def recording(path, value):
        writes.append(('write', Path(path).name, lock.held, lock.holds))
        real_write(path, value)
    monkeypatch.setattr(claims, 'write_private', recording)
    real_unlink = Path.unlink

    def unlinking(self, *a, **kw):
        writes.append(('unlink', self.name, lock.held, lock.holds))
        return real_unlink(self, *a, **kw)
    monkeypatch.setattr(Path, 'unlink', unlinking)
    project = make_dir(tmp_path / 'project')
    write_private(claims.project_home('serenity-bricks') / 'station.json', {'ship': 'serenity-bricks'})
    writes.clear()
    claims.claim('serenity-bricks', project)
    assert writes == [('write', 'projects.json', True, 1), ('write', 'claim.json', True, 1)]
    assert claims.read_registry() == [entry('serenity-bricks', project)]
    assert json.loads((claims.project_home('serenity-bricks') / 'claim.json').read_text()) == entry('serenity-bricks', project)
    writes.clear()
    claims.unclaim(claims.project_home('serenity-bricks'))
    assert writes == [('unlink', 'claim.json', True, 2), ('write', 'projects.json', True, 2)]
    assert json.loads(claims.registry_path().read_text()) == [] and claims.read_registry() == []


def test_the_real_lock_is_exclusive_and_private(home):
    with claims.registry_lock():
        assert claims.lock_path().stat().st_mode & 0o777 == 0o600
        import fcntl
        with open(claims.lock_path(), 'a') as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def make_dir(path):
    path.mkdir(parents=True)
    return Path(os.path.realpath(path))


def test_status_names_an_unreadable_registry_before_reading_the_config(home, capsys):
    """R16: status says the registry can't be read before it reads the config or calls the station."""
    write_private(claims.registry_path(), [])
    claims.registry_path().write_text('{broken')
    with pytest.raises(SystemExit):
        cli.main(['status', '--home', str(home / '.superyak')])   # no config here: load_config stops it, after the line
    out = capsys.readouterr().out
    assert out.startswith(f'Superyak: {claims.registry_path()} can\'t be read')
