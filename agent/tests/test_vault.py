import os
import shutil
import stat
import subprocess
import pytest
from superyak_agent.vault import INBOX, OUTBOUND, RECEIPTS, Vault, VaultError


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def vault(tmp_path):
    template = tmp_path / 'template'
    (template / 'who' / 'coordination').mkdir(parents=True)
    (template / 'CLAUDE.md').write_text('base\n')
    (template / 'node_modules').mkdir()
    (template / 'node_modules' / 'x.js').write_text('x')
    return Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone', template=template), tmp_path


def stanley(tmp_path):
    path = tmp_path / 'stanley'
    if not path.exists():
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'Station.aDNA.git'), str(path)], check=True)
    git(path, 'pull', '-q')
    return path


def test_create_makes_a_bare_repository_with_the_layout_and_drop_box(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    for folder in (OUTBOUND, INBOX, RECEIPTS):
        assert (other / folder / 'README.md').exists()
    assert (other / 'CLAUDE.md').read_text() == 'base\n' and (other / 'README.md').exists()
    assert not (other / 'node_modules').exists()
    with pytest.raises(VaultError):
        Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone2')


def test_outbound_memos_are_committed_once_and_published(vault):
    vault, tmp_path = vault
    assert vault.add_outbound('coord_a.md', 'hello\n') is True
    assert vault.add_outbound('coord_a.md', 'changed\n') is False
    vault.publish()
    other = stanley(tmp_path)
    assert (other / OUTBOUND / 'coord_a.md').read_text() == 'hello\n'
    assert 'Wormhole' in git(other, 'log', '-1', '--format=%an')


def test_both_sides_committing_between_syncs_keeps_every_file(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    git(other, 'add', '-A')
    git(other, 'commit', '-q', '-m', 'stanley')
    git(other, 'push', '-q')
    vault.add_outbound('coord_b.md', 'out\n')
    vault.sync()
    vault.publish()
    assert vault.files(INBOX) == ['coord_reply.md']
    other = stanley(tmp_path)
    assert (other / OUTBOUND / 'coord_b.md').exists() and (other / INBOX / 'coord_reply.md').exists()


def test_files_and_read_skip_readmes_hidden_files_and_symlinks(vault, tmp_path):
    vault, _ = vault
    secret = tmp_path / 'secret.txt'
    secret.write_text('id_ed25519 private')
    (vault.clone / INBOX / 'coord_ok.md').write_text('ok')
    (vault.clone / INBOX / '.hidden.md').write_text('x')
    os.symlink(secret, vault.clone / INBOX / 'coord_link.md')
    assert vault.files(INBOX) == ['coord_ok.md']
    assert vault.read(INBOX, 'coord_ok.md') == 'ok'
    assert vault.read(INBOX, 'coord_link.md') == ''
    assert vault.read(INBOX, '../../../../secret.txt') == ''
    (vault.clone / INBOX / 'coord_big.md').write_bytes(b'a' * 300_000 + b'\xff')
    assert len(vault.read(INBOX, 'coord_big.md')) == 200_000


def test_a_symlinked_parent_folder_cannot_lead_outside_the_vault(tmp_path):
    clone = tmp_path / 'clone'
    clone.mkdir()
    outside = tmp_path / 'other' / 'coordination' / 'inbox'
    outside.mkdir(parents=True)
    (outside / 'coord_x.md').write_text('another vault')
    os.symlink(tmp_path / 'other', clone / 'who')
    vault = Vault(clone)
    assert vault.files(INBOX) == []
    assert vault.read(INBOX, 'coord_x.md') == ''


# --- the server-side gate: a pre-receive hook on the bare repository -------------------------------

LATTICE = {**os.environ, 'STATION_VAULT_PUSHER': 'lattice'}


def push(path, *args, lattice=False):
    return subprocess.run(['git', '-C', str(path), 'push', '-q', *args], capture_output=True, text=True,
                          env=LATTICE if lattice else None)


def commit_all(path, message='stanley'):
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', message)


def tip(tmp_path):
    return git(tmp_path / 'Station.aDNA.git', 'rev-parse', 'refs/heads/main').strip()


def blob(tmp_path, path):
    return subprocess.run(['git', '-C', str(tmp_path / 'Station.aDNA.git'), 'show', f'main:{path}'],
                          capture_output=True, check=True).stdout


def test_create_configures_the_bare_repository_to_refuse_rewrites_and_installs_the_gate(vault):
    _, tmp_path = vault
    bare = tmp_path / 'Station.aDNA.git'
    for key in ('receive.denyNonFastForwards', 'receive.denyDeletes', 'receive.fsckObjects'):
        assert git(bare, 'config', '--get', key).strip() == 'true'
    hook = bare / 'hooks' / 'pre-receive'
    assert stat.S_IMODE(hook.stat().st_mode) == 0o755 and hook.read_text().startswith('#!/usr/bin/env python3')


def test_the_lattice_may_add_inbox_memos_and_receipts(vault):
    _, tmp_path = vault
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    (other / RECEIPTS / 'coord_a.md').write_text('')
    (other / INBOX / 'coord_big.md').write_bytes(b'a' * 1_048_576)
    commit_all(other)
    result = push(other, lattice=True)
    assert result.returncode == 0, result.stderr


def test_a_lattice_merge_of_our_new_memo_with_its_own_is_accepted(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    commit_all(other)
    vault.add_outbound('coord_out.md', 'out\n')
    vault.publish()
    git(other, 'pull', '-q', '--no-rebase', '--no-edit')
    assert (other / OUTBOUND / 'coord_out.md').exists()
    result = push(other, lattice=True)
    assert result.returncode == 0, result.stderr
    assert (blob(tmp_path, f'{OUTBOUND}/coord_out.md'), blob(tmp_path, f'{INBOX}/coord_reply.md')) == (b'out\n', b'reply\n')


def make_outbound_file(other):
    (other / OUTBOUND / 'coord_forged.md').write_text('forged\n')


def make_symlink(other):
    os.symlink('/etc/passwd', other / INBOX / 'coord_link.md')


def make_gitattributes(other):
    (other / '.gitattributes').write_text('* text=auto\n')


def make_inbox_gitattributes(other):
    (other / INBOX / '.gitattributes').write_text('* -text\n')


def modify_existing(other):
    (other / INBOX / 'README.md').write_text('rewritten\n')


def delete_existing(other):
    (other / RECEIPTS / 'README.md').unlink()


def make_executable(other):
    path = other / INBOX / 'coord_run.md'
    path.write_text('#!/bin/sh\n')
    path.chmod(0o755)


def make_subfolder(other):
    (other / INBOX / 'sub').mkdir()
    (other / INBOX / 'sub' / 'coord_deep.md').write_text('deep\n')


def make_outside_path(other):
    (other / 'CLAUDE.md').write_text('rewritten\n')
    (other / 'who' / 'new.md').write_text('x\n')


def make_hidden(other):
    (other / INBOX / '.hidden').write_text('x\n')


def make_oversized(other):
    (other / INBOX / 'coord_huge.md').write_bytes(b'a' * 1_048_577)


def make_gitlink(other):
    sub = other / INBOX / 'coord_sub'
    sub.mkdir()
    git(sub, 'init', '-q')
    git(sub, 'commit', '-q', '--allow-empty', '-m', 'sub')


@pytest.mark.parametrize('change', [make_outbound_file, make_symlink, make_gitattributes, make_inbox_gitattributes,
                                    modify_existing, delete_existing, make_executable, make_subfolder,
                                    make_outside_path, make_hidden, make_oversized, make_gitlink])
def test_the_lattice_cannot_push_anything_but_new_plain_inbox_or_receipt_files(vault, change):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    (other / INBOX / 'coord_ok.md').write_text('fine\n')
    change(other)
    commit_all(other)
    result = push(other, lattice=True)
    assert result.returncode != 0 and 'station vault' in result.stderr
    assert tip(tmp_path) == before


def test_a_tree_with_a_dot_git_entry_is_refused_even_without_fsck(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)

    def plumbing(*args, stdin=None):
        return subprocess.run(['git', '-C', str(other), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                              input=stdin, capture_output=True, text=True, check=True).stdout.strip()

    config = plumbing('hash-object', '-w', '--stdin', stdin='[core]\n')
    dotgit = plumbing('mktree', stdin=f'100644 blob {config}\tconfig\n')
    inbox = plumbing('mktree', stdin=f'040000 tree {dotgit}\t.git\n')
    coordination = plumbing('mktree', stdin=f'040000 tree {inbox}\tinbox\n')
    who = plumbing('mktree', stdin=f'040000 tree {coordination}\tcoordination\n')
    root = plumbing('mktree', stdin=plumbing('ls-tree', 'HEAD') + f'\n040000 tree {who}\twho\n')
    commit = plumbing('commit-tree', root, '-p', 'HEAD', '-m', 'dotgit')
    assert push(other, 'origin', f'{commit}:refs/heads/main', lattice=True).returncode != 0
    git(tmp_path / 'Station.aDNA.git', 'config', 'receive.fsckObjects', 'false')
    result = push(other, 'origin', f'{commit}:refs/heads/main', lattice=True)
    assert result.returncode != 0 and 'station vault' in result.stderr
    assert tip(tmp_path) == before


def test_the_lattice_cannot_hide_a_forbidden_file_in_an_earlier_commit(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    os.symlink('/etc/passwd', other / INBOX / 'coord_link.md')
    commit_all(other, 'symlink')
    git(other, 'rm', '-q', '--cached', f'{INBOX}/coord_link.md')
    (other / INBOX / 'coord_link.md').unlink()
    commit_all(other, 'tidy')
    assert push(other, lattice=True).returncode != 0
    assert tip(tmp_path) == before


def test_nobody_can_rewrite_delete_or_branch_the_vault(vault):
    vault, tmp_path = vault
    vault.add_outbound('coord_a.md', 'ours\n')
    vault.publish()
    before = tip(tmp_path)
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_a.md').write_text('rewritten\n')
    git(other, 'add', '-A')
    git(other, 'commit', '-q', '--amend', '-m', 'rewrite')
    for lattice in (False, True):
        assert push(other, '-f', 'origin', 'HEAD:main', lattice=lattice).returncode != 0
        assert push(other, 'origin', ':main', lattice=lattice).returncode != 0
        assert push(other, 'origin', 'HEAD:refs/heads/other', lattice=lattice).returncode != 0
    git(other, 'checkout', '-q', '--orphan', 'orphan')
    (other / 'README.md').write_text('different\n')
    commit_all(other, 'orphan')
    assert push(other, '-f', 'origin', 'HEAD:main').returncode != 0
    assert tip(tmp_path) == before


def test_pushes_without_the_lattice_marker_may_add_outbound_memos(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_b.md').write_text('out\n')
    commit_all(other)
    assert push(other).returncode == 0
    vault.add_outbound('coord_c.md', 'out\n')
    vault.sync()
    vault.publish()
    assert blob(tmp_path, f'{OUTBOUND}/coord_c.md') == b'out\n'


# --- client-side defence in depth ---------------------------------------------------------------------

def replace_with_symlink(tmp_path, target, link):
    """Stanley's side swaps `link` (a path in the vault) for a symlink to `target`, outside the vault."""
    other = stanley(tmp_path)
    shutil.rmtree(other / link)
    os.symlink(target, other / link)
    commit_all(other, 'symlink')
    assert push(other).returncode == 0  # without the lattice marker the gate lets it through


@pytest.mark.parametrize('link', [OUTBOUND, 'who/coordination', 'who'])
def test_add_outbound_refuses_a_symlinked_outbound_folder_and_writes_nothing_outside(vault, link):
    vault, tmp_path = vault
    outside = tmp_path / 'outside'
    outside.mkdir()
    replace_with_symlink(tmp_path, outside, link)
    vault.sync()
    with pytest.raises(VaultError):
        vault.add_outbound('coord_x.md', 'memo\n')
    assert list(outside.rglob('*')) == []
    with pytest.raises(VaultError):  # still refused, not silently "already there"
        vault.add_outbound('coord_x.md', 'memo\n')


@pytest.mark.parametrize('name', ['../x.md', 'a/b.md', '.hidden.md', 'x.txt', '', '.md', 'x.md\n', 'x\n.md',
                                  'x' * 201 + '.md', 'caf\u00e9.md', 'a b.md', '/etc/passwd.md'])
def test_add_outbound_rejects_unsafe_names(vault, name):
    vault, tmp_path = vault
    with pytest.raises(VaultError):
        vault.add_outbound(name, 'x')
    assert vault.git('status', '--porcelain').stdout == ''
    assert not [p for p in tmp_path.iterdir() if p.name.endswith('.md')]


def test_a_failed_commit_leaves_no_memo_behind_and_the_name_stays_usable(vault):
    vault, _ = vault
    lock = vault.clone / '.git' / 'refs' / 'heads' / 'main.lock'
    lock.write_text('')  # `git add` works, then `git commit` cannot update the branch
    with pytest.raises(VaultError):
        vault.add_outbound('coord_f.md', 'memo\n')
    assert not (vault.clone / OUTBOUND / 'coord_f.md').exists()
    assert vault.git('status', '--porcelain').stdout == ''
    lock.unlink()
    assert vault.add_outbound('coord_f.md', 'memo\n') is True


@pytest.mark.parametrize('attributes', [
    'who/coordination/outbound/coord_* working-tree-encoding=UTF-16\n',
    '* text eol=crlf ident filter=evil\n',
])
def test_pushed_gitattributes_cannot_change_or_block_our_memos(vault, attributes):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / '.gitattributes').write_text(attributes)
    commit_all(other, 'attributes')
    assert push(other).returncode == 0
    vault.sync()
    assert vault.add_outbound('coord_e.md', 'odd $Id$\nlines\n') is True
    assert vault.git('status', '--porcelain').stdout == ''
    vault.publish()
    assert blob(tmp_path, f'{OUTBOUND}/coord_e.md') == b'odd $Id$\nlines\n'


def test_files_and_read_survive_symlink_loops_and_odd_names(vault, tmp_path):
    vault, _ = vault
    inbox = vault.clone / INBOX
    (inbox / 'coord_ok.md').write_text('ok')
    os.symlink('coord_self.md', inbox / 'coord_self.md')
    for name in (b'coord_\xff.md', b'coord_new\nline.md', 'coord_\u202eevil.md'.encode()):
        (inbox / os.fsdecode(name)).write_bytes(b'x')
    assert vault.files(INBOX) == ['coord_ok.md']
    assert vault.read(INBOX, 'coord_self.md') == ''
    shutil.rmtree(inbox)
    os.symlink('inbox', inbox)
    assert vault.files(INBOX) == [] and vault.read(INBOX, 'coord_ok.md') == ''
    shutil.rmtree(vault.clone / 'who')
    os.symlink('who', vault.clone / 'who')
    assert vault.files(INBOX) == [] and vault.read(INBOX, 'coord_ok.md') == ''
