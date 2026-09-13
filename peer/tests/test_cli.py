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

def test_local_demo_refuses_remote_bind_even_with_tls(tmp_path):
    target = tmp_path / 'peer'
    result = run('serve', '--local-demo', '--data-dir', target, '--host', '0.0.0.0', '--peer-tls')
    assert result.returncode != 0
    assert 'loopback' in result.stderr
    assert not target.exists()

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

@pytest.mark.parametrize('damage', ['missing_database', 'missing_account', 'replaced_identity', 'wrong_password'])
def test_demo_refuses_incomplete_or_mismatched_identity_without_repair(tmp_path, damage):
    import sqlite3
    target = tmp_path / 'demo'
    assert run('demo', '--data-dir', target).returncode == 0
    database = target / 'peer.sqlite3'
    credentials_path = target / 'demo-credentials.json'
    credentials = credentials_path.read_bytes()
    if damage == 'missing_database':
        database.unlink()
    elif damage == 'wrong_password':
        values = json.loads(credentials)
        values[0]['password'] = 'a-different-password'
        credentials_path.write_text(json.dumps(values))
        credentials = credentials_path.read_bytes()
    else:
        with sqlite3.connect(database) as db:
            if damage == 'missing_account':
                db.execute("DELETE FROM users WHERE username='patient'")
            else:
                db.execute("UPDATE users SET id='replacement-person' WHERE username='patient'")
    before_database = database.read_bytes() if database.exists() else None
    result = run('demo', '--data-dir', target)
    assert result.returncode != 0
    assert 'incomplete' in result.stderr.lower()
    assert credentials_path.read_bytes() == credentials
    assert (database.read_bytes() if database.exists() else None) == before_database


def test_card_cli_and_peer_tls_options(tmp_path, capsys):
    from superyak_peer.__main__ import main
    from superyak_peer.db import Store
    from superyak_peer.identity import validate_card
    import json
    store=Store(tmp_path/'state')
    user=store.create_user('owner','Owner','long-password',is_admin=True)
    main(['card','--data-dir',str(store.data_dir),'--username','owner','--endpoint','https://localhost:7435'])
    card=json.loads(capsys.readouterr().out)
    assert validate_card(card)['participant']['id']==user['id']


def test_model_config_is_explicit_and_rejects_unknown_before_serving(tmp_path):
    from superyak_peer.models import load_config
    from test_models import APPROVED
    assert load_config(None) is None
    config = tmp_path / 'model.json'
    config.write_text(json.dumps(APPROVED))
    assert load_config(config) == APPROVED
    for invalid in ({**APPROVED, 'model': 'unknown'}, {**APPROVED, 'publisher': 'Unknown'}):
        config.write_text(json.dumps(invalid))
        result = run('serve', '--data-dir', tmp_path / 'unused', '--model-config', config)
        assert result.returncode != 0
        assert 'not approved' in result.stderr
        assert not (tmp_path / 'unused').exists()
    config.write_text('[' * 1500 + ']' * 1500)
    result = run('serve', '--data-dir', tmp_path / 'unused', '--model-config', config)
    assert result.returncode != 0
    assert 'Traceback' not in result.stderr
