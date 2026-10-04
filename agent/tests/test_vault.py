import os
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
    assert vault.read(INBOX, '../../secret.txt') == ''
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
