"""The receipt-place spec's "How a checkout of this repository is told", for `receipt_place.place_of`: identity by the
installed checkout's registered worktrees, never by a file in the folder asked about; a nested repository is "other";
failed or ambiguous discovery is None, never "other"."""
import os
import shutil
import subprocess
import time

import pytest

from superyak_agent import receipt_place as rp

GIT = ['git', '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', '-c', 'init.defaultBranch=main']


def git(*args, cwd):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A checkout with a commit, a worktree beside it and one inside it, and folders of every kind around them."""
    monkeypatch.setattr(rp, '_roots_memo', {})
    checkout = tmp_path / 'superyak'
    (checkout / 'agent' / 'superyak_agent').mkdir(parents=True)
    (checkout / 'agent' / 'superyak_agent' / 'lessons_hook.py').write_text('# the marker file\n')
    git('init', '-q', cwd=checkout)
    git('add', '.', cwd=checkout)
    git('commit', '-q', '-m', 'one', cwd=checkout)
    git('worktree', 'add', '-q', str(tmp_path / 'beside'), cwd=checkout)
    git('worktree', 'add', '-q', str(checkout / 'inner'), cwd=checkout)
    return tmp_path, checkout


def place(cwd, checkout, seconds=5.0):
    return rp.place_of(str(cwd), time.monotonic() + seconds, checkout=checkout)


def test_the_checkout_its_worktrees_and_their_subfolders_are_superyak(world):
    tmp, checkout = world
    (checkout / 'docs').mkdir()
    for cwd in (checkout, checkout / 'agent', checkout / 'docs', tmp / 'beside', tmp / 'beside' / 'agent',
                checkout / 'inner', checkout / 'inner' / 'agent'):
        assert place(cwd, checkout) == 'superyak', cwd


def test_a_planted_marker_a_link_to_it_a_copy_a_fork_and_a_same_name_folder_are_other(world):
    tmp, checkout = world
    planted = tmp / 'planted' / 'agent' / 'superyak_agent'
    planted.mkdir(parents=True)
    (planted / 'lessons_hook.py').write_text('# planted\n')
    linked = tmp / 'linked' / 'agent'
    linked.mkdir(parents=True)
    (linked / 'superyak_agent').symlink_to(checkout / 'agent' / 'superyak_agent')
    shutil.copytree(checkout, tmp / 'copy', symlinks=True)
    subprocess.run(['git', 'clone', '-q', str(checkout), str(tmp / 'fork')], check=True, capture_output=True)
    (tmp / 'elsewhere' / 'superyak').mkdir(parents=True)
    for cwd in (tmp / 'planted', tmp / 'linked', tmp / 'copy', tmp / 'fork', tmp / 'elsewhere' / 'superyak'):
        assert place(cwd, checkout) == 'other', cwd


@pytest.mark.parametrize('under', ['checkout', 'worktree'])
def test_an_unrelated_repository_nested_inside_a_root_is_other(world, under):
    tmp, checkout = world
    base = checkout if under == 'checkout' else tmp / 'beside'
    nested = base / 'vendor' / 'theirs'
    nested.mkdir(parents=True)
    git('init', '-q', cwd=nested)
    (nested / 'src').mkdir()
    assert place(nested, checkout) == 'other' and place(nested / 'src', checkout) == 'other'
    assert place(base / 'vendor', checkout) == 'superyak'


def test_a_dot_git_git_cant_resolve_or_read_gives_no_place(world):
    tmp, checkout = world
    bad = checkout / 'bad'
    bad.mkdir()
    (bad / '.git').write_text('gitdir: /nowhere/at/all\n')
    assert place(bad, checkout) is None
    unreadable = checkout / 'unreadable'
    (unreadable / '.git').mkdir(parents=True)
    (unreadable / '.git').chmod(0)
    try:
        assert place(unreadable, checkout) in (None, 'superyak')   # git decides; never "other" by guess
        assert place(unreadable, checkout) != 'other'
    finally:
        (unreadable / '.git').chmod(0o700)


def test_failed_or_ambiguous_discovery_is_none(world, monkeypatch):
    tmp, checkout = world
    plain = tmp / 'plain'
    plain.mkdir()
    assert place(plain, plain) is None                        # roots that can't be read: not a repository
    assert rp.place_of(None, time.monotonic() + 5, checkout=checkout) is None
    assert rp.place_of('relative/path', time.monotonic() + 5, checkout=checkout) is None
    assert place(tmp / 'missing', checkout) is None
    shut = tmp / 'shut'
    (shut / 'in').mkdir(parents=True)
    shut.chmod(0)
    try:
        assert place(shut / 'in', checkout) is None           # an inaccessible cwd
    finally:
        shut.chmod(0o700)
    deep = checkout
    for n in range(rp.MAX_FOLDERS + 1):
        deep = deep / f'd{n}'
    deep.mkdir(parents=True)
    assert place(deep, checkout) is None                       # more than 64 folders to check
    monkeypatch.setattr(rp, '_roots_memo', {})
    monkeypatch.setenv('PATH', str(tmp / 'no-git-here'))
    assert place(checkout, checkout) is None                   # a missing git


def test_no_time_left_is_none_and_the_caller_s_git_variables_are_ignored(world, monkeypatch):
    tmp, checkout = world
    assert place(checkout, checkout, seconds=0) is None
    other = tmp / 'other-repo'
    other.mkdir()
    git('init', '-q', cwd=other)
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))         # would point discovery at another repository
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    assert place(checkout / 'agent', checkout) == 'superyak'


def test_the_roots_are_kept_in_memory_only(world):
    tmp, checkout = world
    before = {p for p in tmp.rglob('*')}
    assert place(checkout, checkout) == 'superyak'
    after = {p for p in tmp.rglob('*')}
    assert after == before and str(checkout) in rp._roots_memo
