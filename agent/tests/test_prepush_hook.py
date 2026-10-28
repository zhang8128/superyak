"""scripts/git-hooks/pre-push, run as git runs it, against a throwaway repo and a made-up terms file. The real terms
never appear in the repo: the hook reads them from a private file (docs/checklists.md, Before any push)."""
import os
import subprocess
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parents[2] / 'scripts' / 'git-hooks' / 'pre-push'
ZERO = '0' * 40
PUBLIC = 'git@github.com:zhang8128/superyak.git'
pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason='needs scripts/ from the full repository')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name, text):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    git(repo, 'add', name)
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', name)
    return git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    base = commit(repo, 'README', 'the rewritten history\n')
    terms = tmp_path / 'scrub-terms'
    terms.write_text('# made-up terms for the test\nzebra-condition\n')
    terms.chmod(0o600)
    return repo, base, terms


def push(repo, base, sha, terms, url=PUBLIC):
    env = {**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)}
    run = subprocess.run([str(HOOK), 'origin', url], input=f'refs/heads/t {sha} refs/heads/t {ZERO}\n', cwd=repo,
                         env=env, capture_output=True, text=True)
    return run.returncode, run.stderr


def test_a_clean_branch_on_the_rewritten_history_pushes(repo):
    repo, base, terms = repo
    assert push(repo, base, commit(repo, 'notes.md', 'an archive of hives\n'), terms)[0] == 0


def test_a_scrubbed_term_or_path_is_refused(repo):
    repo, base, terms = repo
    term = commit(repo, 'notes.md', 'the patient has zebra-condition\n')
    code, said = push(repo, base, term, terms)
    assert code == 1 and 'zebra' not in said  # the refusal never repeats the term
    git(repo, 'reset', '-q', '--hard', base)
    assert push(repo, base, commit(repo, 'engram/docs/sessions/a.md', 'x\n'), terms)[0] == 1


def test_a_branch_not_built_on_the_base_is_refused_but_the_private_archive_takes_it(repo):
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old')
    old = commit(repo, 'other', 'the old history\n')
    assert push(repo, base, old, terms)[0] == 1
    assert push(repo, base, old, terms, url='https://github.com/superyak-archive/other.git')[0] == 1
    assert push(repo, base, old, terms, url='git@github.com:zhang8128/superyak-archive.git')[0] == 0


def test_without_a_private_terms_file_every_push_is_refused(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    assert push(repo, base, clean, tmp_path / 'missing')[0] == 1
    terms.chmod(0o644)
    assert push(repo, base, clean, terms)[0] == 1


def test_a_delete_pushes_no_history(repo):
    repo, base, terms = repo
    run = subprocess.run([str(HOOK), 'origin', PUBLIC], input=f'refs/heads/t {ZERO} refs/heads/t {base}\n', cwd=repo,
                         env={**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)},
                         capture_output=True, text=True)
    assert run.returncode == 0
