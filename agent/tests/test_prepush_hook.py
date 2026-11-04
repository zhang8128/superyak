"""scripts/git-hooks/pre-push, run as git runs it, against a throwaway repo and a made-up terms file. The real terms
never appear in the repo: the hook reads them from a private file (docs/checklists.md, Before any push)."""
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parents[2] / 'scripts' / 'git-hooks' / 'pre-push'
ZERO = '0' * 40
PUBLIC = 'git@github.com:zhang8128/superyak.git'
TERM = 'zebra-condition'
ACCENT = 'z' + chr(0xe9) + 'bra'  # written from its code point, so this file stays ASCII
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
    terms.write_text('# made-up terms for the test\n\nzebra-condition\n')
    terms.chmod(0o600)
    return repo, base, terms


def push(repo, base, sha, terms, url=PUBLIC, local_ref='refs/heads/t', remote_ref='refs/heads/t', path=None, extra=None):
    env = {**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms), **(extra or {})}
    if path:
        env['PATH'] = f'{path}:{os.environ["PATH"]}'
    run = subprocess.run([str(HOOK), 'origin', url], input=f'{local_ref} {sha} {remote_ref} {ZERO}\n', cwd=repo,
                         env=env, capture_output=True, text=True)
    return run.returncode, run.stderr


def commit_as(repo, message='ordinary', name='t', email='t@t', committer=None, committer_email=None, file='notes.md',
              text='fine\n', binary=None):
    (repo / file).parent.mkdir(parents=True, exist_ok=True)
    (repo / file).write_bytes(binary if binary is not None else text.encode())
    git(repo, 'add', '-A')
    subprocess.run(['git', '-C', str(repo), '-c', f'user.name={committer or "t"}', '-c', f'user.email={committer_email or "t@t"}',
                    'commit', '-qm', message, '--author', f'{name} <{email}>'], check=True, capture_output=True)
    return git(repo, 'rev-parse', 'HEAD')


def hand_built_commit(repo, body):
    """A commit object git commit wouldn't make: it repairs bad bytes in a message and has no way to add a header."""
    tree, parent = git(repo, 'rev-parse', 'HEAD^{tree}'), git(repo, 'rev-parse', 'HEAD')
    head = f'tree {tree}\nparent {parent}\nauthor t <t@t> 1 +0000\ncommitter t <t@t> 1 +0000\n'.encode()
    return subprocess.run(['git', '-C', str(repo), 'hash-object', '-t', 'commit', '-w', '--stdin', '--literally'], input=head + body,
                          check=True, capture_output=True).stdout.decode().strip()


def merge_with(repo, adds):
    git(repo, 'checkout', '-q', '-b', 'side')
    commit(repo, 'side.md', 'side\n')
    git(repo, 'checkout', '-q', 'main')
    commit(repo, 'main.md', 'main\n')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--no-commit', '--no-ff', '-s', 'ours', 'side')
    for name, text in adds.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'merge')
    return git(repo, 'rev-parse', 'HEAD')


def shim(tmp_path, tool, marker, action='echo "broken" >&2; exit 128'):
    """A tool that dies when its arguments hold `marker`, and otherwise runs the real one."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / tool).write_text(f'#!/bin/sh\ncase " $* " in *"{marker}"*) {action} ;; esac\nexec {shutil.which(tool)} "$@"\n')
    (bin_dir / tool).chmod(0o755)
    return bin_dir


# The base, and the plain cases

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


@pytest.mark.parametrize('mode, code', [(0o600, 0), (0o400, 0), (0o640, 1), (0o604, 1), (0o660, 1), (0o620, 1)])
def test_only_an_owner_only_terms_file_is_accepted(repo, mode, code):
    """macOS's /usr/bin/find rejects `-perm /077` as an illegal mode, and a check that swallowed its error passed
    a 0644 file there (Serenity, 2026-10-28). The exact modes are POSIX on both finds."""
    repo, base, terms = repo
    terms.chmod(mode)
    assert push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)[0] == code


def test_a_find_that_fails_refuses_the_push(repo, tmp_path):
    """A permission check that can't run refuses, never passes."""
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    assert push(repo, base, clean, terms, path=shim(tmp_path, 'find', ' '))[0] == 1


def test_a_delete_pushes_no_history(repo):
    repo, base, terms = repo
    run = subprocess.run([str(HOOK), 'origin', PUBLIC], input=f'refs/heads/t {ZERO} refs/heads/t {base}\n', cwd=repo,
                         env={**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)},
                         capture_output=True, text=True)
    assert run.returncode == 0


def test_old_history_a_merge_hides_is_still_refused(repo):
    """Serenity's case: an old branch adds a scrubbed path, later removes it, and is merged into a branch on the base.
    The merge carries no scrubbed path, so a simplified log would never show the side; the push uploads it anyway."""
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old')
    git(repo, 'rm', '-rqf', '.')
    commit(repo, 'engram/docs/sessions/a.md', 'x\n')
    git(repo, 'rm', '-q', 'engram/docs/sessions/a.md')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'removed')
    git(repo, 'checkout', '-q', 'main')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--allow-unrelated-histories', '-s', 'ours', 'old',
        '-m', 'merge the old side')
    merged = git(repo, 'rev-parse', 'HEAD')
    code, said = push(repo, base, merged, terms)
    assert code == 1 and 'old history' in said


def test_a_push_by_url_passes_a_clean_branch(repo):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    run = subprocess.run([str(HOOK), PUBLIC, PUBLIC], input=f'refs/heads/t {clean} refs/heads/t {ZERO}\n', cwd=repo,
                         env={**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)},
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_a_stale_remote_tracking_ref_on_old_history_vouches_for_nothing(repo):
    """Serenity's second case: an old branch was pushed, the scrub rewrote the remote, and the clone kept its tracking
    ref (no prune). A branch on the base merging that ref must still be refused: the ref no longer means GitHub has it."""
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old-session')
    git(repo, 'rm', '-rqf', '.')
    commit(repo, 'docs/sessions/s.md', 'zebra-condition\n')
    git(repo, 'rm', '-q', 'docs/sessions/s.md')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'removed')
    stale = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/old-session', stale)
    git(repo, 'checkout', '-q', 'main')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--allow-unrelated-histories', '-s', 'ours',
        'refs/remotes/origin/old-session', '-m', 'merge a stale ref')
    code, said = push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)
    assert code == 1 and 'old history' in said


# Everything a push uploads is read

@pytest.mark.parametrize('kwargs', [
    {'text': f'{TERM.upper()}\n'},
    {'message': f'a note on {TERM}'},
    {'message': f'a note on {TERM.upper()}'},
    {'name': f'a {TERM}'},
    {'email': f'{TERM}@t'},
    {'committer': f'a {TERM}'},
    {'committer_email': f'{TERM}@t'},
    {'file': f'{TERM}.md'},
    {'file': f'{TERM}/notes.md'},
    {'binary': f'{TERM}\0more\n'.encode()},
    {'binary': f'more\0{TERM}\n'.encode()},
    {'binary': f'{TERM}\n'.encode('utf-16')},
], ids=['text-case', 'message', 'message-case', 'author', 'author-email', 'committer', 'committer-email', 'file-name',
        'directory-name', 'nul-after', 'nul-before', 'utf-16'])
def test_a_term_anywhere_in_a_commit_is_refused(repo, kwargs):
    repo, base, terms = repo
    code, said = push(repo, base, commit_as(repo, **kwargs), terms)
    assert code == 1 and TERM not in said and TERM.upper() not in said and 'carries what the scrub removed' in said


def test_a_term_in_a_non_ascii_file_name_is_refused(repo):
    repo, base, terms = repo
    terms.write_text(ACCENT + '\n')
    assert push(repo, base, commit_as(repo, file=ACCENT + '.md'), terms)[0] == 1


def test_a_term_in_an_unchanged_line_of_a_changed_file_is_refused(repo):
    """The whole blob goes up, so the whole blob is read: a line can't hide by being older than the change."""
    repo, _, terms = repo
    commit(repo, 'old.md', 'first\nsecond\n')
    base = git(repo, 'rev-parse', 'HEAD')
    commit(repo, 'old.md', f'first\nsecond\n{TERM}\n')
    git(repo, 'update-ref', 'refs/heads/dirty', 'HEAD')
    tip = commit(repo, 'old.md', f'first changed\nsecond\n{TERM}\n')
    assert push(repo, base, tip, terms)[0] == 1


def test_what_came_before_the_base_is_not_scanned_again(repo):
    """The scrub's job, not a push's: a term in the base's own tree can't be fixed by refusing the next branch."""
    repo, _, terms = repo
    commit(repo, 'old.md', f'{TERM}\n')
    base = git(repo, 'rev-parse', 'HEAD')
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 0, said


def test_a_term_in_a_merge_resolution_is_refused(repo):
    repo, base, terms = repo
    assert push(repo, base, merge_with(repo, {'resolved.md': f'{TERM}\n'}), terms)[0] == 1


def test_a_term_in_a_file_name_only_a_merge_adds_is_refused(repo):
    repo, base, terms = repo
    assert push(repo, base, merge_with(repo, {f'{TERM}.md': 'clean\n'}), terms)[0] == 1


def test_a_clean_merge_pushes(repo):
    repo, base, terms = repo
    code, said = push(repo, base, merge_with(repo, {'resolved.md': 'clean\n'}), terms)
    assert code == 0, said


def test_a_scrubbed_path_behind_an_ours_merge_past_the_base_is_refused(repo):
    """--full-history: the merge drops the path, so a simplified log wouldn't walk the side that added it."""
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '-b', 'side')
    commit(repo, 'docs/sessions/a.md', 'clean\n')
    git(repo, 'rm', '-q', 'docs/sessions/a.md')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'removed')
    git(repo, 'checkout', '-q', 'main')
    commit(repo, 'main.md', 'main\n')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '-s', 'ours', 'side', '-m', 'merge')
    assert push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)[0] == 1


def test_a_term_in_an_annotated_tag_is_refused(repo):
    repo, base, terms = repo
    commit(repo, 'notes.md', 'fine\n')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'tag', '-a', '-m', f'about {TERM}', 'v1')
    assert push(repo, base, git(repo, 'rev-parse', 'v1'), terms)[0] == 1


def test_a_term_in_a_tag_inside_a_tag_is_refused(repo):
    repo, base, terms = repo
    commit(repo, 'notes.md', 'fine\n')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'tag', '-a', '-m', f'about {TERM}', 'inner')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'tag', '-a', '-m', 'clean', 'outer', 'inner')
    assert push(repo, base, git(repo, 'rev-parse', 'outer'), terms)[0] == 1


def test_a_clean_annotated_tag_pushes(repo):
    repo, base, terms = repo
    commit(repo, 'notes.md', 'fine\n')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'tag', '-a', '-m', 'a release', 'v1')
    code, said = push(repo, base, git(repo, 'rev-parse', 'v1'), terms)
    assert code == 0, said


@pytest.mark.parametrize('body', [f'\nbefore\0{TERM}\n'.encode(), f'x-note {TERM}\n\nclean\n'.encode()], ids=['after-a-nul', 'extra-header'])
def test_a_hand_built_commit_is_read_whole(repo, body):
    repo, base, terms = repo
    assert push(repo, base, hand_built_commit(repo, body), terms)[0] == 1


def test_a_replaced_commit_is_read_as_it_really_is(repo):
    repo, base, terms = repo
    dirty = commit(repo, 'notes.md', f'{TERM}\n')
    git(repo, 'reset', '-q', '--hard', base)
    clean = commit(repo, 'notes.md', 'clean\n')
    git(repo, 'replace', dirty, clean)
    assert push(repo, base, dirty, terms)[0] == 1


def test_a_textconv_cant_hide_a_file(repo):
    repo, base, terms = repo
    git(repo, 'config', 'diff.hide.textconv', 'true')
    (repo / '.gitattributes').write_text('*.md diff=hide\n')
    assert push(repo, base, commit_as(repo, text=f'{TERM}\n'), terms)[0] == 1


def test_a_log_encoding_cant_hide_a_message(repo):
    repo, base, terms = repo
    terms.write_text(ACCENT + '\n')
    git(repo, 'config', 'i18n.logOutputEncoding', 'ISO-8859-1')
    assert push(repo, base, commit_as(repo, message=f'a note on {ACCENT}'), terms)[0] == 1


@pytest.mark.parametrize('kwargs', [{'text': f'{TERM}\n'}, {'message': f'about {TERM}'}, {'file': 'docs/sessions/a.md'}],
                         ids=['text', 'message', 'scrubbed-path'])
def test_a_tracking_ref_vouches_for_nothing(repo, kwargs):
    """A remote branch was deleted and its tracking ref stayed. A new branch on top of it uploads that commit again."""
    repo, base, terms = repo
    stale = commit_as(repo, **kwargs)
    git(repo, 'update-ref', 'refs/remotes/origin/gone', stale)
    tip = commit(repo, 'later.md', 'clean\n')
    assert push(repo, base, tip, terms)[0] == 1


# Readings: bytes and characters

def test_a_term_beside_a_bad_byte_is_refused_in_a_file(repo):
    """Under a UTF-8 locale, macOS's grep finds no match on a line holding a byte that isn't UTF-8."""
    repo, base, terms = repo
    assert push(repo, base, commit_as(repo, binary=f'caf\xe9 {TERM}\n'.encode('latin-1')), terms)[0] == 1


def test_a_term_beside_a_bad_byte_is_refused_in_a_message(repo):
    repo, base, terms = repo
    assert push(repo, base, hand_built_commit(repo, f'\ncaf\xe9 {TERM}\n'.encode('latin-1')), terms)[0] == 1


def test_a_bad_byte_alone_pushes(repo):
    repo, base, terms = repo
    code, said = push(repo, base, hand_built_commit(repo, b'\ncaf\xe9\n'), terms, extra={'LC_ALL': 'en_US.UTF-8'})
    assert code == 0, said


@pytest.mark.parametrize('kwargs', [{'text': f'the {ACCENT}\n'}, {'message': f'the {ACCENT}'}, {'file': f'{ACCENT}.md'}], ids=['text', 'message', 'file-name'])
def test_a_dot_in_a_term_matches_a_letter_outside_ascii(repo, kwargs):
    """In bytes `.` can't match a two-byte letter, so the reading in characters is what finds this."""
    repo, base, terms = repo
    terms.write_text('z.bra\n')
    assert push(repo, base, commit_as(repo, **kwargs), terms)[0] == 1


def test_a_term_with_a_space_survives_a_line_break(repo):
    repo, base, terms = repo
    terms.write_text('zebra condition\n')
    assert push(repo, base, commit_as(repo, text='the zebra\ncondition here\n'), terms)[0] == 1
    git(repo, 'reset', '-q', '--hard', base)
    assert push(repo, base, commit_as(repo, message='the zebra\n\ncondition here'), terms)[0] == 1
    git(repo, 'reset', '-q', '--hard', base)
    assert push(repo, base, commit_as(repo, text='the zebra  condition\n'), terms)[0] == 1
    git(repo, 'reset', '-q', '--hard', base)
    code, said = push(repo, base, commit_as(repo, text='the zebra and the condition\n'), terms)
    assert code == 0, said


def test_a_machine_with_no_utf8_locale_refuses_the_push(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'locale').write_text('#!/bin/sh\nprintf "C\\nPOSIX\\n"\n')
    (bin_dir / 'locale').chmod(0o755)
    code, said = push(repo, base, clean, terms, path=bin_dir)
    assert code == 1 and 'UTF-8' in said


def test_any_utf8_locale_will_do(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'locale').write_text('#!/bin/sh\nprintf "C\\nPOSIX\\nde_DE.UTF-8\\n"\n')
    (bin_dir / 'locale').chmod(0o755)
    code, said = push(repo, base, clean, terms, path=bin_dir)
    assert code == 0, said


# It never prints a term, and no command's arguments hold one

@pytest.mark.parametrize('refs', [{'local_ref': f'refs/heads/{TERM}'}, {'remote_ref': f'refs/heads/{TERM}'}], ids=['local', 'remote'])
def test_a_term_in_a_ref_name_is_refused_and_not_repeated(repo, refs):
    repo, base, terms = repo
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms, **refs)
    assert code == 1 and TERM not in said and 'in a ref name or a path' in said


def test_a_branch_off_the_base_is_refused_without_its_name(repo):
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old')
    code, said = push(repo, base, commit(repo, 'other', 'old\n'), terms, local_ref=f'refs/heads/{TERM}')
    assert code == 1 and TERM not in said


def test_old_history_is_refused_without_the_branchs_name(repo):
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old')
    git(repo, 'rm', '-rqf', '.')
    commit(repo, 'other.md', 'old\n')
    git(repo, 'checkout', '-q', 'main')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--allow-unrelated-histories', '-s', 'ours', 'old', '-m', 'merge')
    code, said = push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms, local_ref=f'refs/heads/{TERM}')
    assert code == 1 and TERM not in said


def test_a_dead_scan_is_refused_without_the_branchs_name(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, local_ref=f'refs/heads/{TERM}', path=shim(tmp_path, 'git', 'rev-list --objects'))
    assert code == 1 and TERM not in said


@pytest.mark.parametrize('variable', ['GIT_TRACE', 'GIT_TRACE2', 'GIT_TRACE2_EVENT', 'GIT_TRACE2_PERF', 'GIT_TRACE_PACKET'])
@pytest.mark.parametrize('dirty', [False, True], ids=['clean', 'dirty'])
def test_git_tracing_never_shows_a_term(repo, variable, dirty):
    repo, base, terms = repo
    sha = commit(repo, 'notes.md', f'{TERM}\n' if dirty else 'fine\n')
    code, said = push(repo, base, sha, terms, extra={variable: '1' if variable == 'GIT_TRACE' else '2'})
    assert code == int(dirty) and TERM not in said


@pytest.mark.parametrize('tool', ['git', 'grep', 'tr', 'sort', 'comm', 'cut', 'cmp', 'sed'])
def test_no_commands_arguments_hold_a_term(repo, tmp_path, tool):
    repo, base, terms = repo
    log = tmp_path / 'argv'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / tool).write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec {shutil.which(tool)} "$@"\n')
    (bin_dir / tool).chmod(0o755)
    sha = commit(repo, 'notes.md', f'{TERM}\n')
    assert push(repo, base, sha, terms, path=bin_dir)[0] == 1
    assert log.read_text() and TERM not in log.read_text()


def test_a_hit_names_its_object_by_hash(repo):
    repo, base, terms = repo
    dirty = commit_as(repo, message=f'a note on {TERM}')
    commit(repo, 'later.md', 'clean\n')
    code, said = push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)
    assert code == 1 and f'commit {dirty[:8]}' in said


def test_a_hit_in_a_file_names_the_blob(repo):
    repo, base, terms = repo
    commit(repo, 'notes.md', f'{TERM}\n')
    code, said = push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)
    assert code == 1 and f'blob {git(repo, "rev-parse", "HEAD:notes.md")[:8]}' in said


# The terms file

def test_comments_and_blank_lines_in_the_terms_file_are_not_terms(repo):
    repo, base, terms = repo
    code, said = push(repo, base, commit(repo, 'notes.md', 'an ordinary note\n# made-up terms for the test\n'), terms)
    assert code == 0, said


def test_every_term_counts(repo):
    repo, base, terms = repo
    terms.write_text('first-term\nsecond-term\nthird-term\n')
    for term in ('first-term', 'second-term', 'third-term'):
        git(repo, 'reset', '-q', '--hard', base)
        assert push(repo, base, commit(repo, 'notes.md', f'{term}\n'), terms)[0] == 1


def test_a_term_that_is_a_bad_regex_refuses_the_push_and_names_only_its_line(repo):
    """A dead scan prints nothing: one broken line in the file passed a commit holding a good term."""
    repo, base, terms = repo
    terms.write_text('zebra-condition\nbroken(\n')
    code, said = push(repo, base, commit(repo, 'notes.md', 'the patient has zebra-condition\n'), terms)
    assert code == 1 and "couldn't run" in said and 'line 2 of' in said and 'line 1 of' not in said
    assert 'zebra' not in said and 'broken' not in said


def test_a_dead_git_doesnt_blame_the_terms_file(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'git', 'rev-list --objects'))
    assert code == 1 and "couldn't run" in said and 'regex' not in said


def test_a_dead_grep_doesnt_blame_the_terms_file(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'grep', ' -f '))
    assert code == 1 and "couldn't run" in said and 'regex' not in said


@pytest.mark.parametrize('content, line', [('zebra-condition\r\n', 1), ('other\nzebra-condition \n', 2), ('zebra-condition\n \n', 2), ('a\n\tb\t\n', 2)],
                         ids=['crlf', 'trailing-space', 'only-a-space', 'trailing-tab'])
def test_a_term_that_could_never_match_is_refused_by_its_line(repo, content, line):
    repo, base, terms = repo
    terms.write_bytes(content.encode())
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 1 and f'line {line} ends in whitespace' in said and 'zebra' not in said


def test_a_comment_may_end_in_whitespace(repo):
    repo, base, terms = repo
    terms.write_text('# a comment \nzebra-condition\n')
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 0, said


def test_a_nul_in_the_terms_file_refuses(repo):
    repo, base, terms = repo
    terms.write_bytes(b'zebra\0condition\n')
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 1 and 'NUL' in said and 'zebra' not in said


def test_a_terms_file_with_only_comments_refuses(repo):
    repo, base, terms = repo
    terms.write_text('# nothing yet\n\n')
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 1 and 'no terms' in said


def test_a_read_of_the_terms_that_dies_partway_refuses(repo, tmp_path):
    repo, base, terms = repo
    terms.write_text('first-term\nsecond-term\n')
    sha = commit(repo, 'notes.md', 'second-term\n')
    code, said = push(repo, base, sha, terms, path=shim(tmp_path, 'grep', ' -v ', 'echo first-term; exit 2'))
    assert code == 1 and "couldn't be read" in said


def test_a_term_in_latin1_over_latin1_text_is_refused(repo):
    """Under a UTF-8 locale GNU grep drops such a line from the terms and exits 0."""
    repo, base, terms = repo
    terms.write_bytes(b'z\xe9bra\n')
    code, _ = push(repo, base, commit_as(repo, binary=b'the z\xe9bra\n'), terms, extra={'LC_ALL': 'en_US.UTF-8'})
    assert code == 1


def test_a_lone_term_that_looks_like_an_option_is_still_a_term(repo):
    repo, base, terms = repo
    terms.write_text('-v\n')
    assert push(repo, base, commit_as(repo, message='use -v here'), terms)[0] == 1
    git(repo, 'reset', '-q', '--hard', base)
    code, said = push(repo, base, commit_as(repo, message='nothing here'), terms)
    assert code == 0, said


# A scan that dies refuses

@pytest.mark.parametrize('tool, marker', [
    ('git', ':(glob)'), ('git', 'rev-list --objects'), ('git', 'cat-file --batch '), ('git', 'cat-file --batch-check'),
    ('grep', ' -a -q -i -E -f '), ('grep', ' missing$'), ('sort', '/new.raw'), ('sort', '/after.raw'), ('comm', ' '),
    ('git', '--name-only'), ('git', 'rev-list --ancestry-path'),
], ids=['path-scan', 'object-list', 'object-read', 'object-check', 'term-scan', 'missing-scan', 'sort-new', 'sort-after', 'comm',
        'paths', 'ancestry'])
def test_any_scan_that_dies_refuses_the_push(repo, tmp_path, tool, marker):
    """A dead scan prints nothing, which must never read as "nothing found"."""
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, tool, marker))
    assert code == 1 and "couldn't run" in said, said


def test_a_dead_mktemp_says_so(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'mktemp', ' '))
    assert code == 1 and 'no temporary directory' in said


# A stage that dies at once breaks the pipe, so the stage before it reports too. These read all they're given and then fail,
# so only their own status can say.
@pytest.mark.parametrize('tool, marker', [('tr', ' -d '), ('grep', ' -a -q -i -E -f ')], ids=['strip', 'term-scan'])
def test_a_stage_that_reads_everything_then_dies_refuses(repo, tmp_path, tool, marker):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    passed = tmp_path / 'passed'  # tr's first call reads the terms file: that one runs, and the pipeline's is the one that dies
    action = f'if [ -f "{passed}" ]; then {shutil.which("cat")} > /dev/null; exit 2; fi; : > "{passed}"'
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, tool, marker, action))
    assert code == 1 and "couldn't run" in said, said


def test_a_term_scan_that_reads_everything_then_dies_refuses(repo, tmp_path):
    """Only the pipeline's grep dies: the ref names' scan keeps its own status, and would hide this one."""
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    real_cat, real_grep = shutil.which('cat'), shutil.which('grep')
    (bin_dir / 'grep').write_text(f"""#!/bin/sh
case " $* " in *" -f "*/names*) ;; *" -a -q -i -E -f "*) {real_cat} > /dev/null; exit 2 ;; esac
exec {real_grep} "$@"
""")
    (bin_dir / 'grep').chmod(0o755)
    code, said = push(repo, base, clean, terms, path=bin_dir)
    assert code == 1 and "couldn't run" in said, said


def test_a_tr_that_dies_on_the_terms_file_doesnt_call_it_a_nul(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'tr', ' -d '))
    assert code == 1 and "couldn't be read" in said and 'NUL' not in said


def test_an_ancestor_of_the_base_is_refused(repo):
    """Older than the base: nothing past the base to scan, so only the base check can say."""
    repo, older, terms = repo
    base = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, older, terms)
    assert code == 1 and "isn't built on the rewritten history" in said


def test_a_term_beside_a_bad_byte_in_a_ref_name_is_refused(repo):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    line = f'refs/heads/caf\xe9-{TERM} {clean} refs/heads/t {ZERO}\n'.encode('latin-1')
    env = {**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)}
    run = subprocess.run([str(HOOK), 'origin', PUBLIC], input=line, cwd=repo, env=env, capture_output=True)
    assert run.returncode == 1 and TERM.encode() not in run.stderr


def test_a_filter_that_dies_refuses_the_push(repo, tmp_path):
    repo, base, terms = repo
    terms.write_text('zebra condition\n')
    clean = commit(repo, 'notes.md', 'fine\n')
    assert push(repo, base, clean, terms, path=shim(tmp_path, 'tr', ' -s '))[0] == 1


def test_a_cat_that_dies_refuses_the_push(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    real = shutil.which('cat')
    (bin_dir / 'cat').write_text(f'#!/bin/sh\nif [ $# -eq 0 ]; then {real} > /dev/null; exit 3; fi\nexec {real} "$@"\n')
    (bin_dir / 'cat').chmod(0o755)
    assert push(repo, base, clean, terms, path=bin_dir)[0] == 1


def test_a_plain_rev_list_that_dies_refuses_the_push(repo, tmp_path):
    """The old-history check's first read. Nothing later looks at this commit's ancestry, so it must refuse by itself."""
    repo, base, terms = repo
    git(repo, 'checkout', '-q', '--orphan', 'old')
    git(repo, 'rm', '-rqf', '.')
    commit(repo, 'other.md', 'old\n')
    git(repo, 'checkout', '-q', 'main')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'merge', '-q', '--allow-unrelated-histories', '-s', 'ours', 'old', '-m', 'merge')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'git').write_text(f'#!/bin/sh\ncase "$1 $2" in "rev-list "[0-9a-f]*) exit 128 ;; esac\nexec {shutil.which("git")} "$@"\n')
    (bin_dir / 'git').chmod(0o755)
    code, said = push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms, path=bin_dir)
    assert code == 1 and "couldn't run" in said


def test_a_missing_object_refuses_the_push(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    bin_dir = shim(tmp_path, 'git', 'cat-file --batch-check', 'echo "1234 missing"; exit 0')
    assert push(repo, base, clean, terms, path=bin_dir)[0] == 1


@pytest.mark.parametrize('sent', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP], ids=['term', 'int', 'hup'])
def test_a_signal_leaves_no_copy_of_the_terms_behind(repo, tmp_path, sent):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    scratch = tmp_path / 'hook-tmp'
    scratch.mkdir()
    bin_dir = shim(tmp_path, 'git', 'rev-list --objects', 'sleep 1')
    env = {**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms), 'TMPDIR': str(scratch),
           'PATH': f'{bin_dir}:{os.environ["PATH"]}'}
    run = subprocess.Popen([str(HOOK), 'origin', PUBLIC], stdin=subprocess.PIPE, cwd=repo, env=env, stderr=subprocess.DEVNULL, text=True)
    run.stdin.write(f'refs/heads/t {clean} refs/heads/t {ZERO}\n')
    run.stdin.close()
    limit = time.monotonic() + 20
    while time.monotonic() < limit and not list(scratch.glob('*/terms')):
        time.sleep(0.02)
    assert list(scratch.glob('*/terms'))
    run.send_signal(sent)
    run.wait(timeout=20)
    assert run.returncode != 0 and list(scratch.iterdir()) == []


def characters_only(tmp_path, tool_args):
    """A grep that dies only in the reading in characters, on the given arguments."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    real = shutil.which('grep')
    (bin_dir / 'grep').write_text(f"""#!/bin/sh
if [ "$LC_ALL" != C ]; then case " $* " in {tool_args}) {shutil.which('cat')} > /dev/null; exit 2 ;; esac; fi
exec {real} "$@"
""")
    (bin_dir / 'grep').chmod(0o755)
    return bin_dir


def test_a_reading_in_characters_that_dies_refuses(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=characters_only(tmp_path, '*" -f "*/terms*'))
    assert code == 1 and "couldn't run" in said, said


def test_a_names_scan_in_characters_that_dies_refuses(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=characters_only(tmp_path, '*/names*'))
    assert code == 1 and "couldn't run" in said, said


def test_a_shape_check_that_dies_refuses(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'grep', ' -a -n -E '))
    assert code == 1 and "couldn't be read" in said, said


@pytest.mark.parametrize('tool, marker', [('cmp', '/no-nul'), ('cmp', '/mark'), ('sed', 's/'), ('head', ' -c 3 ')], ids=['cmp-nul', 'cmp-mark', 'sed', 'head'])
def test_a_tool_that_dies_on_the_terms_file_says_only_it_couldnt_read_it(repo, tmp_path, tool, marker):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, tool, marker))
    assert code == 1 and "couldn't be read" in said and 'NUL' not in said and 'mark' not in said


def test_a_dead_find_doesnt_say_the_file_is_missing(repo, tmp_path):
    repo, base, terms = repo
    clean = commit(repo, 'notes.md', 'fine\n')
    code, said = push(repo, base, clean, terms, path=shim(tmp_path, 'find', ' '))
    assert code == 1 and "couldn't be read" in said and 'Copy the file' not in said


def test_a_head_that_dies_cant_throw_away_a_path_hit(repo, tmp_path):
    repo, base, terms = repo
    dirty = commit(repo, 'docs/sessions/a.md', 'clean\n')
    code, said = push(repo, base, dirty, terms, path=shim(tmp_path, 'head', ' -5 '))
    assert code == 1, said


def test_a_byte_order_mark_refuses(repo):
    repo, base, terms = repo
    terms.write_bytes(b'\xef\xbb\xbfzebra-condition\n')
    code, said = push(repo, base, commit(repo, 'notes.md', 'fine\n'), terms)
    assert code == 1 and 'byte-order mark' in said and 'zebra' not in said


# Squeezing adds a reading, it never replaces one

@pytest.mark.parametrize('term, text', [
    ('^zebra$', 'zebra'), ('^zebra', 'zebra here'), ('zebra$', 'a zebra'), ('zebra  condition', 'zebra  condition'), ('zebra\tcondition', 'zebra\tcondition'),
], ids=['both-anchors', 'start-anchor', 'end-anchor', 'two-spaces', 'tab'])
def test_a_spaced_term_beside_it_kills_no_term(repo, term, text):
    repo, base, terms = repo
    terms.write_text(f'{term}\nother term\n')
    assert push(repo, base, commit_as(repo, text=f'{text}\n'), terms)[0] == 1


@pytest.mark.parametrize('term, text', [('zebra  condition', 'zebra  condition'), ('zebra\tcondition', 'zebra\tcondition')], ids=['two-spaces', 'tab'])
def test_a_term_that_turns_on_squeezing_can_still_match_itself(repo, term, text):
    repo, base, terms = repo
    terms.write_text(f'{term}\n')
    assert push(repo, base, commit_as(repo, text=f'{text}\n'), terms)[0] == 1


def test_a_term_with_two_spaces_still_crosses_a_line_break(repo):
    """Only terms squeezed the same way as the text can match across the break."""
    repo, base, terms = repo
    terms.write_text('zebra  condition\n')
    assert push(repo, base, commit_as(repo, text='the zebra\ncondition here\n'), terms)[0] == 1


@pytest.mark.parametrize('term', ['zebra.condition', 'zebra[[:space:]]condition'])
def test_a_term_with_no_literal_space_still_crosses_a_line_break(repo, term):
    repo, base, terms = repo
    terms.write_text(f'{term}\n')
    assert push(repo, base, commit_as(repo, text='the zebra\ncondition here\n'), terms)[0] == 1


# Paths: every one, on a line of its own. On macOS a raw tree's hash bytes defeat the reading in characters.

def test_a_second_name_for_a_blob_is_read(repo):
    repo, base, terms = repo
    terms.write_text('z.bra\n')
    (repo / 'first.md').write_text('clean\n')
    (repo / f'{ACCENT}.md').write_text('clean\n')
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'two names')
    assert push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)[0] == 1


def test_a_name_renamed_away_is_read(repo):
    repo, base, terms = repo
    terms.write_text('z.bra\n')
    commit_as(repo, file=f'{ACCENT}.md', text='clean\n')
    git(repo, 'mv', f'{ACCENT}.md', 'later.md')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'renamed')
    assert push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)[0] == 1


def test_a_copy_of_a_blob_in_the_base_under_a_new_name_is_read(repo):
    repo, _, terms = repo
    terms.write_text('z.bra\n')
    base = commit(repo, 'old.md', 'clean\n')
    (repo / f'{ACCENT}.md').write_text('clean\n')
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'a copy')
    assert push(repo, base, git(repo, 'rev-parse', 'HEAD'), terms)[0] == 1


def test_a_name_only_a_merge_adds_is_read_on_its_own_line(repo):
    """Only -m lists it: the raw tree holds it too, but bytes can't match `.`, and on macOS characters can't match that line."""
    repo, base, terms = repo
    terms.write_text('z.bra\n')
    assert push(repo, base, merge_with(repo, {f'{ACCENT}.md': 'clean\n'}), terms)[0] == 1


def test_a_tracking_ref_vouches_for_no_path(repo):
    repo, base, terms = repo
    terms.write_text('z.bra\n')
    stale = commit_as(repo, file=f'{ACCENT}.md', text='clean\n')
    git(repo, 'update-ref', 'refs/remotes/origin/gone', stale)
    assert push(repo, base, commit(repo, 'later.md', 'clean\n'), terms)[0] == 1


@pytest.mark.parametrize('kwargs', [{'text': f'the {ACCENT}\n'}, {'message': f'the {ACCENT}'}], ids=['text', 'message'])
def test_a_spaced_term_beside_it_leaves_a_dot_able_to_match(repo, kwargs):
    repo, base, terms = repo
    terms.write_text('z.bra\nother term\n')
    assert push(repo, base, commit_as(repo, **kwargs), terms)[0] == 1


@pytest.mark.parametrize('kwargs', [{'text': 'the Z' + chr(0xc9) + 'BRA\n'}, {'message': 'the Z' + chr(0xc9) + 'BRA'}], ids=['text', 'message'])
def test_case_folds_outside_ascii(repo, kwargs):
    repo, base, terms = repo
    terms.write_text(ACCENT + '\nother term\n')
    assert push(repo, base, commit_as(repo, **kwargs), terms)[0] == 1


# Through a real git push, refs and all

@pytest.fixture
def pushing(repo, tmp_path):
    repo, base, terms = repo
    bare = tmp_path / 'bare.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(bare)], check=True)
    git(repo, 'config', 'core.hooksPath', str(HOOK.parent))
    env = {**os.environ, 'SUPERYAK_PREPUSH_BASE': base, 'SUPERYAK_SCRUB_TERMS': str(terms)}

    def real_push(*refspecs):
        return subprocess.run(['git', '-C', str(repo), 'push', '--dry-run', str(bare), *refspecs], env=env, capture_output=True, text=True)
    git(repo, 'branch', 'clean', commit(repo, 'clean.md', 'fine\n'))
    git(repo, 'branch', 'dirty', commit(repo, 'dirty.md', f'{TERM}\n'))
    git(repo, 'checkout', '-q', 'clean')
    return real_push, repo


def test_a_real_push_of_a_clean_branch_passes(pushing):
    real_push, _ = pushing
    done = real_push('clean')
    assert done.returncode == 0, done.stderr


def test_a_real_push_of_a_dirty_branch_is_refused(pushing):
    real_push, _ = pushing
    assert real_push('dirty').returncode != 0


@pytest.mark.parametrize('refspecs', [('dirty', 'clean'), ('clean', 'dirty')], ids=['dirty-first', 'dirty-last'])
def test_one_dirty_ref_among_many_refuses_the_push(pushing, refspecs):
    real_push, _ = pushing
    assert real_push(*refspecs).returncode != 0


def test_a_delete_beside_a_dirty_ref_still_refuses(pushing):
    real_push, _ = pushing
    done = real_push(':refs/heads/gone', 'dirty')
    assert done.returncode != 0 and 'scrub removed' in done.stderr
