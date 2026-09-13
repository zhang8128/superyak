import json
import os
import subprocess
import sys
import pytest

def run(*args):
    return subprocess.run([sys.executable, '-m', 'superyak_peer', *map(str, args)], capture_output=True, text=True)

def test_demo_is_private_idempotent_and_refuses_unrelated_state(tmp_path):
    target = tmp_path / 'demo'
    result = run('demo', '--data-dir', target)
    assert result.returncode == 0, result.stderr
    credentials = json.loads((target / 'demo-credentials.json').read_text())
    assert len(credentials) == 4
    assert all(u['password'] not in result.stdout for u in credentials)
    assert (target / 'demo-credentials.json').stat().st_mode & 0o077 == 0
    assert run('demo', '--data-dir', target).returncode == 0
    assert json.loads((target / 'demo-credentials.json').read_text()) == credentials
    unrelated = tmp_path / 'unrelated'
    unrelated.mkdir()
    (unrelated / 'keep').write_text('preserve')
    assert run('demo', '--data-dir', unrelated).returncode != 0
    assert (unrelated / 'keep').read_text() == 'preserve'

def test_remote_plaintext_serve_refused(tmp_path):
    result = run('serve', '--data-dir', tmp_path / 'peer', '--host', '0.0.0.0')
    assert result.returncode != 0
    assert 'TLS' in result.stderr

def test_symlink_state_refused(tmp_path):
    from superyak_peer.db import Store
    victim = tmp_path / 'victim'
    victim.write_text('untouched')
    target = tmp_path / 'peer'
    target.mkdir()
    (target / 'peer.sqlite3').symlink_to(victim)
    with pytest.raises(ValueError):
        Store(target)
    assert victim.read_text() == 'untouched'

def test_init_owner_and_restart_persists_draft(tmp_path):
    from superyak_peer.db import Store
    password = tmp_path / 'password'
    password.write_text('an-explicit-owner-password\n')
    target = tmp_path / 'initialized'
    result = run('init', '--data-dir', target, '--username', 'owner', '--name', 'Owner', '--password-file', password)
    assert result.returncode == 0, result.stderr
    assert 'an-explicit-owner-password' not in result.stdout
    store = Store(target)
    owner = store.login('owner', 'an-explicit-owner-password', 'local')['user']
    assert owner['is_admin'] == 1
    draft = store.create_layer(owner['id'], {'title': 'Persistent', 'body': 'saved offline'})
    assert Store(target).get_layer(owner['id'], draft['id'])['body'] == 'saved offline'
    assert run('init', '--data-dir', target, '--username', 'other', '--name', 'Other', '--password-file', password).returncode != 0
    assert (target / 'peer.sqlite3').stat().st_mode & 0o077 == 0

@pytest.mark.parametrize('name', ['peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal'])
def test_symlink_sidecars_are_refused(tmp_path, name):
    from superyak_peer.db import Store
    target = tmp_path / 'state'
    target.mkdir()
    victim = tmp_path / 'victim'
    victim.write_text('preserve')
    (target / name).symlink_to(victim)
    with pytest.raises(ValueError):
        Store(target)
    assert victim.read_text() == 'preserve'
