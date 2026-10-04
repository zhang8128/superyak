import os
import shutil
import stat
import subprocess
import pytest
from superyak_agent.vault import AUTHOR, INBOX, OUTBOUND, RECEIPTS, Vault, VaultError, install_gate


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

def pusher_env(marker=None, **extra):
    """The environment of a push: STATION_VAULT_PUSHER is `lattice` (Stanley's forced command), `bridge` (our
    own Vault) or, for anything else, unset or some other value."""
    env = {k: v for k, v in os.environ.items() if k != 'STATION_VAULT_PUSHER'}
    if marker is not None:
        env['STATION_VAULT_PUSHER'] = marker
    return {**env, **extra}


LATTICE = pusher_env('lattice')


def push(path, *args, lattice=False, marker=None, **extra):
    return subprocess.run(['git', '-C', str(path), 'push', '-q', *args], capture_output=True, text=True,
                          env=pusher_env('lattice' if lattice else marker, **extra))


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
    assert git(bare, 'config', '--get', 'receive.maxInputSize').strip() == '8388608'
    assert git(bare, 'config', '--get', 'core.hooksPath').strip() == 'hooks'  # relative: it follows the repository
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


def dot_git_commit(other):
    """A commit on top of HEAD whose tree also holds who/coordination/inbox/.git/config (built with plumbing:
    `git add` refuses such a path). Every other entry of the tree is kept, so only the .git entry is wrong."""
    def plumbing(*args, stdin=None):
        return subprocess.run(['git', '-C', str(other), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                              input=stdin, capture_output=True, text=True, check=True).stdout.strip()

    def tree_with(base, name, entry):
        kept = [line for line in plumbing('ls-tree', base).splitlines() if line.split('\t')[1] != name]
        return plumbing('mktree', stdin='\n'.join([*kept, entry]) + '\n')

    config = plumbing('hash-object', '-w', '--stdin', stdin='[core]\n')
    dotgit = plumbing('mktree', stdin=f'100644 blob {config}\tconfig\n')
    inbox = tree_with('HEAD:who/coordination/inbox', '.git', f'040000 tree {dotgit}\t.git')
    coordination = tree_with('HEAD:who/coordination', 'inbox', f'040000 tree {inbox}\tinbox')
    who = tree_with('HEAD:who', 'coordination', f'040000 tree {coordination}\tcoordination')
    root = tree_with('HEAD', 'who', f'040000 tree {who}\twho')
    return plumbing('commit-tree', root, '-p', 'HEAD', '-m', 'dotgit')


def test_git_itself_refuses_a_tree_with_a_dot_git_entry(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    result = push(other, 'origin', f'{dot_git_commit(other)}:refs/heads/main', lattice=True)
    assert result.returncode != 0 and 'hasDotgit' in result.stderr and 'station vault' not in result.stderr
    assert tip(tmp_path) == before


def test_the_hooks_own_path_rule_refuses_a_dot_git_entry_that_fsck_lets_through(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    commit = dot_git_commit(other)
    git(tmp_path / 'Station.aDNA.git', 'config', 'receive.fsck.hasDotgit', 'ignore')
    result = push(other, 'origin', f'{commit}:refs/heads/main', lattice=True)
    assert result.returncode != 0 and 'station vault' in result.stderr and 'inbox/.git/config' in result.stderr
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
    for marker in (None, 'lattice', 'bridge'):
        assert push(other, '-f', 'origin', 'HEAD:main', marker=marker).returncode != 0
        assert push(other, 'origin', ':main', marker=marker).returncode != 0
        assert push(other, 'origin', 'HEAD:refs/heads/other', marker=marker).returncode != 0
    git(other, 'checkout', '-q', '--orphan', 'orphan')
    (other / 'README.md').write_text('different\n')
    commit_all(other, 'orphan')
    assert push(other, '-f', 'origin', 'HEAD:main', marker='bridge').returncode != 0
    assert tip(tmp_path) == before


def test_the_bridge_marker_may_add_outbound_memos_and_publishes_still_work(vault):
    vault, tmp_path = vault
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_b.md').write_text('out\n')
    commit_all(other)
    assert push(other, marker='bridge').returncode == 0
    vault.add_outbound('coord_c.md', 'out\n')
    vault.sync()
    vault.publish()
    assert blob(tmp_path, f'{OUTBOUND}/coord_c.md') == b'out\n'


@pytest.mark.parametrize('marker', [None, '', 'Bridge', 'bridge ', 'nonsense'])
@pytest.mark.parametrize('change', [make_outbound_file, make_outside_path, modify_existing])
def test_a_push_without_the_bridge_marker_is_held_to_the_drop_box_rules(vault, change, marker):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    (other / INBOX / 'coord_ok.md').write_text('fine\n')
    change(other)
    commit_all(other)
    result = push(other, marker=marker)
    assert result.returncode != 0 and 'station vault' in result.stderr
    assert tip(tmp_path) == before


def test_a_push_without_a_marker_may_still_add_inbox_memos(vault):
    _, tmp_path = vault
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    commit_all(other)
    assert push(other).returncode == 0, 'an unmarked push is the drop-box, not a ban'
    assert blob(tmp_path, f'{INBOX}/coord_reply.md') == b'reply\n'


def test_the_vaults_own_pushes_carry_the_bridge_marker_and_the_bare_hook_does_run(vault, monkeypatch):
    vault, tmp_path = vault
    seen = tmp_path / 'seen-marker'
    hook = tmp_path / 'Station.aDNA.git' / 'hooks' / 'pre-receive'
    hook.write_text(f'#!/bin/sh\nprintf %s "$STATION_VAULT_PUSHER" >> {seen}\ncat >/dev/null\n')
    for inherited in (None, 'lattice'):  # nothing we are run with changes who the vault says it is
        monkeypatch.delenv('STATION_VAULT_PUSHER', raising=False)
        if inherited:
            monkeypatch.setenv('STATION_VAULT_PUSHER', inherited)
        vault.add_outbound(f'coord_{inherited}.md', 'out\n')
        vault.publish()
        assert os.environ.get('STATION_VAULT_PUSHER') == inherited  # the push did not change our own environment
    assert seen.read_text() == 'bridgebridge'  # the hook ran for both, despite the `core.hooksPath=/dev/null` we pass


def test_creating_a_vault_pushes_as_the_bridge_whatever_the_environment_says(tmp_path, monkeypatch):
    monkeypatch.setenv('STATION_VAULT_PUSHER', 'lattice')  # would hold README.md and the folders to the drop-box rules
    Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone')
    assert blob(tmp_path, 'README.md')


def test_the_gate_refuses_every_push_unless_the_repository_has_fsck_on(vault):
    _, tmp_path = vault
    bare = tmp_path / 'Station.aDNA.git'
    other = stanley(tmp_path)
    for value in ('false', 'unset'):
        if value == 'unset':
            git(bare, 'config', '--unset', 'receive.fsckObjects')
        else:
            git(bare, 'config', 'receive.fsckObjects', value)
        for marker in (None, 'lattice', 'bridge'):
            (other / INBOX / f'coord_{value}_{marker}.md').write_text('x\n')
            commit_all(other)
            result = push(other, marker=marker)
            assert result.returncode != 0 and 'receive.fsckObjects' in result.stderr and 'station vault' in result.stderr
    git(bare, 'config', 'receive.fsckObjects', 'true')
    assert push(other, marker='lattice').returncode == 0  # the earlier commits go through once fsck is back on


def test_a_huge_push_is_refused_before_it_is_stored(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_ok.md').write_bytes(os.urandom(1_000_000))
    commit_all(other, 'fits')
    assert push(other, marker='bridge').returncode == 0
    fits = tip(tmp_path)
    (other / OUTBOUND / 'coord_huge.md').write_bytes(os.urandom(9 * 1_048_576))  # incompressible, over 8 MiB
    commit_all(other, 'huge')
    result = push(other, marker='bridge')
    assert result.returncode != 0 and 'station vault' not in result.stderr  # git itself, before the hook
    assert tip(tmp_path) == fits != before


def test_a_big_template_can_be_created_but_pushes_are_limited_afterwards(tmp_path):
    template = tmp_path / 'template'
    template.mkdir()
    (template / 'big.bin').write_bytes(os.urandom(9 * 1_048_576))  # the live aDNA template is larger than the push limit
    vault = Vault.create(tmp_path / 'Station.aDNA.git', tmp_path / 'clone', template=template)
    assert len(blob(tmp_path, 'big.bin')) == 9 * 1_048_576
    bare = tmp_path / 'Station.aDNA.git'
    assert git(bare, 'config', '--get', 'receive.maxInputSize').strip() == '8388608'
    assert git(bare, 'config', '--get', 'core.hooksPath').strip() == 'hooks'
    (vault.clone / OUTBOUND / 'coord_huge.md').write_bytes(os.urandom(9 * 1_048_576))
    commit_all(vault.clone, 'huge')
    assert push(vault.clone, marker='bridge').returncode != 0


def test_a_hooks_path_in_global_config_or_on_the_command_line_cannot_switch_the_gate_off(vault):
    _, tmp_path = vault
    before = tip(tmp_path)
    off = tmp_path / 'gitconfig'
    off.write_text('[core]\n\thooksPath = /dev/null\n')
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_forged.md').write_text('forged\n')
    commit_all(other)
    for args, extra in ((['-c', 'core.hooksPath=/dev/null'], {}),
                        ([], {'GIT_CONFIG_GLOBAL': str(off), 'GIT_CONFIG_NOSYSTEM': '1'})):
        result = subprocess.run(['git', '-C', str(other), *args, 'push', '-q'], capture_output=True, text=True,
                                env=pusher_env('lattice', **extra))
        assert result.returncode != 0 and 'station vault' in result.stderr
    assert tip(tmp_path) == before


def test_the_gate_still_holds_after_the_bare_repository_is_moved_or_restored_elsewhere(vault):
    _, tmp_path = vault
    other = stanley(tmp_path)
    moved = tmp_path / 'elsewhere' / 'Restored.aDNA.git'
    moved.parent.mkdir()
    (tmp_path / 'Station.aDNA.git').rename(moved)  # a pinned absolute hooks path would now point nowhere, and git skips that
    git(other, 'remote', 'set-url', 'origin', str(moved))
    (other / OUTBOUND / 'coord_forged.md').write_text('forged\n')
    commit_all(other)
    result = push(other)
    assert result.returncode != 0 and 'station vault' in result.stderr
    assert git(moved, 'rev-parse', 'refs/heads/main').strip() != git(other, 'rev-parse', 'HEAD').strip()


def test_install_gate_is_safe_to_run_again_and_upgrades_an_old_repository(vault):
    _, tmp_path = vault
    bare = tmp_path / 'Station.aDNA.git'
    hook = bare / 'hooks' / 'pre-receive'
    current = hook.read_text()
    install_gate(bare)
    assert hook.read_text() == current and stat.S_IMODE(hook.stat().st_mode) == 0o755
    # an older repository: the previous hook, no size limit, no pinned hooks path
    hook.write_text('#!/bin/sh\nexit 0\n')
    git(bare, 'config', '--unset', 'receive.maxInputSize')
    git(bare, 'config', 'core.hooksPath', str(bare / 'hooks'))  # the first version pinned an absolute path
    git(bare, 'config', 'receive.fsckObjects', 'false')
    install_gate(bare)
    install_gate(bare)
    assert hook.read_text() == current and stat.S_IMODE(hook.stat().st_mode) == 0o755
    assert git(bare, 'config', '--get', 'receive.maxInputSize').strip() == '8388608'
    assert git(bare, 'config', '--get', 'core.hooksPath').strip() == 'hooks'
    assert git(bare, 'config', '--get-all', 'receive.fsckObjects').split() == ['true']
    assert not hook.with_name('pre-receive.tmp').exists()
    other = stanley(tmp_path)
    (other / OUTBOUND / 'coord_forged.md').write_text('forged\n')
    commit_all(other)
    assert push(other, lattice=True).returncode != 0  # and the upgraded gate is live


# --- client-side defence in depth ---------------------------------------------------------------------

def replace_with_symlink(tmp_path, target, link):
    """Stanley's side swaps `link` (a path in the vault) for a symlink to `target`, outside the vault."""
    other = stanley(tmp_path)
    shutil.rmtree(other / link)
    os.symlink(target, other / link)
    commit_all(other, 'symlink')
    assert push(other, marker='bridge').returncode == 0  # only the lattice (and unmarked pushers) are held to the drop-box


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
    assert push(other, marker='bridge').returncode == 0
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


MEMO = '---\nto_persona: Venus\n---\n\n'  # what every memo of ours starts with


def test_recover_commits_memos_a_crash_left_untracked_or_staged_in_one_commit(vault):
    vault, tmp_path = vault
    outbound = vault.clone / OUTBOUND
    (outbound / 'coord_untracked.md').write_text(MEMO + 'u\n')
    (outbound / 'coord_staged.md').write_text(MEMO + 's\n')
    vault.git('add', '--', f'{OUTBOUND}/coord_staged.md')
    before = vault.git('rev-parse', 'HEAD').stdout
    assert vault.recover() == ['coord_staged.md', 'coord_untracked.md']
    assert vault.git('rev-list', '--count', f'{before.strip()}..HEAD').stdout.strip() == '1'
    assert vault.git('log', '-1', '--format=%an|%s').stdout.strip() == 'Wormhole|wormhole: recover interrupted memos'
    assert vault.git('status', '--porcelain').stdout == ''
    assert vault.tracked(OUTBOUND, 'coord_untracked.md') and vault.tracked(OUTBOUND, 'coord_staged.md')
    vault.publish()
    other = stanley(tmp_path)
    assert (other / OUTBOUND / 'coord_untracked.md').read_text() == MEMO + 'u\n'
    assert (other / OUTBOUND / 'coord_staged.md').read_text() == MEMO + 's\n'
    head = vault.git('rev-parse', 'HEAD').stdout
    assert vault.recover() == [] and vault.git('rev-parse', 'HEAD').stdout == head  # nothing to do: no commit


def test_recover_leaves_unsafe_or_foreign_files_alone_and_unstages_them(vault, tmp_path):
    vault, _ = vault
    outbound = vault.clone / OUTBOUND
    secret = tmp_path / 'secret'
    secret.write_text('s')
    os.symlink(secret, outbound / 'coord_link.md')
    (outbound / 'sub').mkdir()
    (outbound / 'sub' / 'coord_nested.md').write_text('n')
    (outbound / 'bad name.md').write_text('b')
    (outbound / 'notes.txt').write_text('t')
    (outbound / 'coord_good.md').write_text(MEMO + 'g')
    (vault.clone / 'scratch.txt').write_text('mine')  # untracked, outside the outbound folder
    (vault.clone / 'staged.txt').write_text('staged')
    vault.git('add', '--', 'staged.txt', f'{OUTBOUND}/coord_link.md')
    vault.git('add', '-f', '--', f'{OUTBOUND}/bad name.md')
    assert vault.recover() == ['coord_good.md']
    assert vault.git('diff', '--cached', '--name-only').stdout == ''  # nothing else stays staged
    assert vault.git('ls-tree', '-r', '--name-only', 'HEAD', OUTBOUND).stdout.split() == [
        f'{OUTBOUND}/README.md', f'{OUTBOUND}/coord_good.md']
    assert (vault.clone / 'scratch.txt').read_text() == 'mine' and (vault.clone / 'staged.txt').read_text() == 'staged'
    assert (outbound / 'coord_link.md').is_symlink() and (outbound / 'sub' / 'coord_nested.md').exists()
    vault.sync()  # an index that is clean (and untracked files elsewhere) no longer blocks the rebase


def test_a_staged_index_blocks_sync_until_recover_commits_it(vault):
    vault, tmp_path = vault
    (vault.clone / OUTBOUND / 'coord_half.md').write_text(MEMO + 'half\n')
    vault.git('add', '--', f'{OUTBOUND}/coord_half.md')
    other = stanley(tmp_path)
    (other / INBOX / 'coord_reply.md').write_text('reply\n')
    commit_all(other, 'stanley')
    assert push(other, lattice=True).returncode == 0
    with pytest.raises(VaultError):
        vault.sync()
    vault.recover()
    vault.sync()
    vault.publish()
    assert blob(tmp_path, f'{OUTBOUND}/coord_half.md') == (MEMO + 'half\n').encode()
    assert blob(tmp_path, f'{INBOX}/coord_reply.md') == b'reply\n'


def test_tracked_is_true_only_for_plain_files_committed_in_head(vault):
    vault, _ = vault
    assert vault.tracked(OUTBOUND, 'README.md') is True
    (vault.clone / OUTBOUND / 'coord_t.md').write_text('t')
    assert vault.tracked(OUTBOUND, 'coord_t.md') is False  # on disk only
    vault.git('add', '--', f'{OUTBOUND}/coord_t.md')
    assert vault.tracked(OUTBOUND, 'coord_t.md') is False  # staged only
    vault.git(*AUTHOR, 'commit', '-q', '-m', 'x')
    assert vault.tracked(OUTBOUND, 'coord_t.md') is True
    assert vault.tracked(OUTBOUND, 'missing.md') is False and vault.tracked(OUTBOUND, '') is False
    assert vault.tracked('who/coordination', 'outbound') is False  # a folder is not a file
    assert vault.tracked(OUTBOUND, '../outbound/coord_t.md') is False


@pytest.mark.parametrize('content', [b'', b'-', b'--', b'\n---\n', b'hello\n', b' ---\n', b'\xff\xfe---'])
@pytest.mark.parametrize('staged', [False, True])
def test_recover_skips_an_outbound_file_that_is_empty_or_has_no_front_matter(vault, content, staged):
    vault, _ = vault
    outbound = vault.clone / OUTBOUND
    (outbound / 'coord_blank.md').write_bytes(content)  # a crash between creating the file and writing it
    (outbound / 'coord_good.md').write_text(MEMO + 'g')
    if staged:
        vault.git('add', '--', f'{OUTBOUND}/coord_blank.md')
    assert vault.recover() == ['coord_good.md']
    assert (outbound / 'coord_blank.md').read_bytes() == content  # left on disk untouched
    assert not vault.tracked(OUTBOUND, 'coord_blank.md') and vault.tracked(OUTBOUND, 'coord_good.md')
    assert vault.git('diff', '--cached', '--name-only').stdout == ''
    head = vault.git('rev-parse', 'HEAD').stdout
    assert vault.recover() == [] and vault.git('rev-parse', 'HEAD').stdout == head
    vault.sync()  # nothing staged: the rebase is not blocked


def test_recover_unstages_with_literal_pathspecs(vault):
    vault, _ = vault
    (vault.clone / ':(top)x').write_text('magic name')
    (vault.clone / 'x').write_text('plain name')
    vault.git('--literal-pathspecs', 'add', '--', ':(top)x', 'x')
    assert vault.git('diff', '--cached', '--name-only').stdout.split('\n')[:-1] == [':(top)x', 'x']
    assert vault.recover() == []
    assert vault.git('diff', '--cached', '--name-only').stdout == ''  # a `:(top)x` pathspec would have spared it
    assert (vault.clone / ':(top)x').read_text() == 'magic name'
    vault.sync()
