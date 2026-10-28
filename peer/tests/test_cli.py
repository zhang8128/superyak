import json
import os
import subprocess
import sys
import pytest

def run(*args):
    return subprocess.run([sys.executable, '-m', 'superyak_peer', *map(str, args)], capture_output=True, text=True)


def test_bootstrap_first_super_admin_preserves_demo_and_writes_private_activation(tmp_path):
    from superyak_peer.db import Store
    target = tmp_path / 'demo'
    assert run('demo', '--data-dir', target).returncode == 0
    credentials = (target / 'demo-credentials.json').read_bytes()
    activation = tmp_path / 'activation.json'
    result = run('bootstrap-super-admin', '--data-dir', target, '--username', 'science.stanley@example.org', '--name', 'Stanley', '--activation-file', activation)
    assert result.returncode == 0, result.stderr
    record = json.loads(activation.read_text())
    assert record['token'] not in result.stdout + result.stderr
    assert record['username'] == 'science.stanley@example.org'
    assert activation.stat().st_mode & 0o777 == 0o600
    assert run('demo', '--data-dir', target).returncode == 0
    assert (target / 'demo-credentials.json').read_bytes() == credentials
    store = Store(target)
    with store.transaction() as db:
        supers = db.execute('SELECT username,activation_pending FROM users WHERE is_super_admin=1').fetchall()
    assert [tuple(r) for r in supers] == [('science.stanley@example.org', 1)]


def test_legacy_account_migration_keeps_existing_credentials_and_identity(tmp_path):
    import sqlite3
    from superyak_peer.auth import password_hash
    from superyak_peer.db import Store
    target = tmp_path / 'legacy'; target.mkdir()
    with sqlite3.connect(target / 'peer.sqlite3') as db:
        db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,name TEXT NOT NULL,salt BLOB NOT NULL,password_hash BLOB NOT NULL,is_admin INTEGER NOT NULL,created REAL NOT NULL)')
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', ('retained-id', 'owner', 'Owner', b'old-salt', password_hash('retained-password', b'old-salt'), 1, 100))
    store = Store(target)
    user = store.login('owner', 'retained-password', 'test')['user']
    assert user['id'] == 'retained-id' and user['is_admin'] == 1
    assert user['is_super_admin'] == 0 and user['role_version'] == 1
    assert Store(target).login('owner', 'retained-password', 'test')['user'] == user

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


def test_pending_super_admin_activation_can_be_renewed_without_replacing_identity(tmp_path):
    from superyak_peer.common import Problem
    from superyak_peer.db import Store
    target = tmp_path / 'peer'
    first = tmp_path / 'first.json'
    args = ['bootstrap-super-admin', '--data-dir', target, '--username', 'science.stanley@example.org', '--name', 'Stanley']
    assert run(*args, '--activation-file', first).returncode == 0
    original = json.loads(first.read_text())
    second = tmp_path / 'second.json'
    renewed = run(*args, '--activation-file', second, '--renew-activation')
    assert renewed.returncode == 0, renewed.stderr
    current = json.loads(second.read_text())
    assert current['user_id'] == original['user_id'] and current['token'] != original['token']
    store = Store(target)
    with pytest.raises(Problem):
        store.redeem(original['token'], original['username'], original['name'], 'long-user-password')
    assert store.redeem(current['token'], current['username'], current['name'], 'long-user-password')['id'] == original['user_id']
    third = tmp_path / 'third.json'
    assert run(*args, '--activation-file', third, '--renew-activation').returncode != 0
    assert not third.exists()
    assert store.login(current['username'], 'long-user-password', 'test')['user']['is_super_admin'] == 1


# fix:pairing-code (plan Task 3): `pair` reads the code from the controlling terminal only; `card` shows it on stderr

PROMPT = b'Type the code shown on the other machine:'


def peers(tmp_path, remote_name='Remote One'):
    """Here: a store with an admin `bob`, no identity yet. There: a peer whose card `card` printed to a file."""
    from superyak_peer.db import Store
    from superyak_peer.federation import Federation
    here = Store(tmp_path / 'here')
    here.create_user('bob', 'Bob', 'long-password', is_admin=True)
    there = Store(tmp_path / 'there')
    user = there.create_user('remote', remote_name, 'long-password', is_admin=True)
    card = Federation(there, endpoint='https://localhost:7436').card(user['id'])
    path = tmp_path / 'card.json'
    path.write_text(json.dumps(card))
    return here, card, path


def contacts(store):
    with store.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT user_id FROM remote_contacts')]


def in_pty(args, typed=None, stdin=None, timeout=60):
    """Run the CLI under a new pty, its controlling terminal. With `stdin`, fd 0 is a pipe holding that text instead,
    so a read of stdin and a read of /dev/tty differ (plan review MF2). Types `typed` only after the prompt shows.
    (exit code, everything the terminal showed, whether the prompt showed)."""
    import pty
    import select
    import time
    pid, master = pty.fork()
    if pid == 0:
        try:
            if stdin is not None:
                r, w = os.pipe()
                os.write(w, stdin.encode())
                os.close(w)
                os.dup2(r, 0)
                os.close(r)
            os.execv(sys.executable, [sys.executable, '-m', 'superyak_peer', *map(str, args)])
        finally:
            os._exit(127)
    shown, prompted, status, deadline = b'', False, None, time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO on Linux once the child has gone
                break
            if not chunk:
                break
            shown += chunk
            if not prompted and PROMPT in shown:
                prompted = True
                if typed is not None:
                    os.write(master, (typed + '\n').encode())
        else:
            done, waited = os.waitpid(pid, os.WNOHANG)  # reaping keeps the status, or it's lost
            if done:
                status = waited
                break
    else:
        os.kill(pid, 9)
    if status is None:
        _, status = os.waitpid(pid, 0)
    os.close(master)
    return os.waitstatus_to_exitcode(status), shown.decode('utf-8', 'replace'), prompted


def pair_args(here, path, user='bob'):
    return ['pair', '--data-dir', here.data_dir, '--card', path, '--as', user]


def test_card_prints_the_card_on_stdout_as_before_and_its_code_on_stderr(tmp_path, capsys):
    from superyak_peer.__main__ import main
    from superyak_peer.db import Store
    from superyak_peer.identity import pairing_code, show_code
    store = Store(tmp_path / 'state')
    store.create_user('owner', 'Owner', 'long-password', is_admin=True)
    main(['card', '--data-dir', str(store.data_dir), '--username', 'owner', '--endpoint', 'https://localhost:7435'])
    out, err = capsys.readouterr()
    card = json.loads(out)
    assert out == json.dumps(card, indent=2) + '\n'  # stdout stays exactly a card
    assert err == f'Pairing code: {show_code(pairing_code(card))}\n'


def test_with_no_terminal_pair_refuses_even_with_the_right_code_on_stdin(tmp_path):
    """MF2a: start_new_session leaves the child no controlling terminal, so /dev/tty can't open."""
    from superyak_peer.identity import pairing_code
    here, card, path = peers(tmp_path)
    done = subprocess.run([sys.executable, '-m', 'superyak_peer', *map(str, pair_args(here, path))],
                          input=pairing_code(card) + '\n', capture_output=True, text=True, timeout=60,
                          start_new_session=True)
    assert done.returncode == 2 and 'pairing needs a person at a terminal' in done.stderr
    assert contacts(here) == []


def test_the_code_typed_on_the_terminal_pairs_whatever_stdin_holds(tmp_path):
    """MF2b: stdin is a pipe holding a wrong code; the terminal gets the right one."""
    from superyak_peer.identity import pairing_code, show_code
    here, card, path = peers(tmp_path)
    code, shown, prompted = in_pty(pair_args(here, path), typed=show_code(pairing_code(card)), stdin='0' * 32 + '\n')
    assert prompted and code == 0, shown
    assert contacts(here) == [(card['participant']['id'],)]
    assert f"code {show_code(pairing_code(card))}, confirmed by typing" in shown


def test_the_right_code_on_stdin_never_pairs_when_the_terminal_types_a_wrong_one(tmp_path):
    """MF2c, the reverse."""
    from superyak_peer.identity import pairing_code, show_code
    here, card, path = peers(tmp_path)
    code, shown, prompted = in_pty(pair_args(here, path), typed='0' * 32, stdin=pairing_code(card) + '\n')
    assert prompted and code == 1, shown
    assert f'Its code is {show_code(pairing_code(card))}' in shown and contacts(here) == []


@pytest.mark.parametrize('who', ['participant', 'pending', 'nobody'])
def test_an_account_that_may_not_pair_is_refused_before_the_prompt(tmp_path, who):
    """MF2d: under a pty, so a check after the prompt would block here instead of failing."""
    here, card, path = peers(tmp_path)
    if who != 'nobody':
        user = here.create_user('carol', 'Carol', 'long-password', is_admin=who == 'pending')
        if who == 'pending':
            with here.transaction() as db:
                db.execute('UPDATE users SET activation_pending=1 WHERE id=?', (user['id'],))
    code, shown, prompted = in_pty(pair_args(here, path, user='carol'), typed=None, timeout=30)
    assert code == 1 and not prompted, shown
    assert contacts(here) == []


def test_pair_and_connections_make_no_identity(tmp_path):
    """SF2: a peer's identity is made by `card --endpoint`, which names its host; pairing never makes one."""
    from superyak_peer.identity import pairing_code
    here, card, path = peers(tmp_path)
    assert run('connections', '--data-dir', here.data_dir, '--as', 'bob').returncode == 0
    code, shown, _ = in_pty(pair_args(here, path), typed=pairing_code(card))
    assert code == 0, shown
    assert not (here.data_dir / 'identity.json').exists()


def test_a_name_with_control_characters_reaches_the_terminal_as_one_safe_line(tmp_path):
    """SF3: validate_card lets a participant name hold ESC and a newline; the terminal never runs them."""
    from superyak_peer.identity import pairing_code
    here, card, path = peers(tmp_path, remote_name='Eve\x1b[2J\nRoot ok')
    code, shown, prompted = in_pty(pair_args(here, path), typed=pairing_code(card))
    assert code == 0 and prompted
    assert '\x1b[2J' not in shown and 'Eve [2J Root ok' in shown
    listed = run('connections', '--data-dir', here.data_dir, '--as', 'bob')
    assert '\x1b' not in listed.stdout and 'Eve [2J Root ok' in listed.stdout


def test_both_sides_see_one_code(tmp_path):
    """SF6a: the code `card` prints on the exporting side is the code the importing side lists after pairing."""
    from superyak_peer.db import Store
    there = Store(tmp_path / 'there')
    there.create_user('alice', 'Alice', 'long-password', is_admin=True)
    exported = run('card', '--data-dir', there.data_dir, '--username', 'alice', '--endpoint', 'https://localhost:7436')
    assert exported.returncode == 0, exported.stderr
    shown_there = exported.stderr.removeprefix('Pairing code: ').strip()
    path = tmp_path / 'card.json'
    path.write_text(exported.stdout)  # the card file exactly as `card` wrote it
    here = Store(tmp_path / 'here')
    here.create_user('bob', 'Bob', 'long-password', is_admin=True)
    code, shown, _ = in_pty(pair_args(here, path), typed=shown_there)
    assert code == 0, shown
    listed = run('connections', '--data-dir', here.data_dir, '--as', 'bob')
    assert f'code {shown_there}' in listed.stdout and 'confirmed by typing' in listed.stdout


def test_connections_needs_an_admin(tmp_path):
    here, _, _ = peers(tmp_path)
    here.create_user('carol', 'Carol', 'long-password')
    refused = run('connections', '--data-dir', here.data_dir, '--as', 'carol')
    assert refused.returncode == 1 and 'Admin required' in refused.stderr
