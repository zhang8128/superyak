"""The restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S6, S7, S16; R7-R9, R18). Every
test works in tmp_path; the restore test boots real loopback servers and stops every one of them."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import pytest
from fastapi.testclient import TestClient
from superyak_peer import backups
from superyak_peer.__main__ import main as cli
from superyak_peer.app import create_app
from superyak_peer.auth import token_hash
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.door import create_door


def test_health_answers_without_a_session(tmp_path, monkeypatch):
    """R7: 200 with exactly {"ok": true}, no session, after one database read (a failing read is the 500 handler's);
    the door answers 404."""
    app = create_app(tmp_path / 'peer', clock=lambda: 1000000.0, allowed_origins=['http://testserver'])
    reply = TestClient(app, base_url='http://testserver').get('/api/health')
    assert reply.status_code == 200 and reply.json() == {'ok': True} and 'set-cookie' not in reply.headers
    door = TestClient(create_door(tmp_path / 'peer', clock=lambda: 1000000.0), base_url='https://door.example:8443')
    assert door.get('/api/health').status_code == 404

    def broken():
        raise sqlite3.OperationalError('disk I/O error')

    monkeypatch.setattr(app.state.store, 'transaction', broken)
    reply = TestClient(app, base_url='http://testserver', raise_server_exceptions=False).get('/api/health')
    assert reply.status_code == 500 and reply.json() == {'error': 'Request could not be completed'}


def docked(store, owner_id, name):
    """A ship docked for owner_id, as its machine sees it: (ship, key)."""
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def staged(tmp_path, store, label='replaced-20261017-120000'):
    """Runbook steps 4-5: a checked copy staged as restored.sqlite3 in a replaced-<time> directory (no dispatch.lock)."""
    aside = tmp_path / 'backups' / label
    aside.mkdir(parents=True, mode=0o700)
    return backups.run_backup(store.data_dir, None, output=aside / 'restored.sqlite3')


def go_live(copy, directory):
    """Runbook step 6: the reconciled copy installed as a data directory's peer.sqlite3, opened as the station does."""
    directory.mkdir(mode=0o700)
    shutil.copyfile(copy, directory / 'peer.sqlite3')
    return Store(directory)


def reconcile(capsys, *args):
    """station-restore-reconcile; returns (exit code, stdout, stderr)."""
    try:
        cli(['station-restore-reconcile', *map(str, args)])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def overwrite_pages(path, first=2):
    """Junk over every page after the first two: the header survives, the tables don't."""
    size = path.stat().st_size
    with open(path, 'r+b') as stream:
        stream.seek(first * 4096)
        stream.write(b'\xff' * (size - first * 4096))


def test_reconcile_refuses_the_live_data_dir_and_symlinks(tmp_path, capsys):
    """R18: the directory --live-data-dir names, a directory holding dispatch.lock (the live one), a symlink and a copy
    that fails its check are each refused with exit 1, and the file is unchanged."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy = staged(tmp_path, store)
    named = tmp_path / 'named'
    named.mkdir()
    shutil.copyfile(copy, named / 'peer.sqlite3')
    link = copy.parent / 'link.sqlite3'
    link.symlink_to(copy)
    damaged = tmp_path / 'damaged' / 'restored.sqlite3'
    damaged.parent.mkdir()
    shutil.copyfile(copy, damaged)
    overwrite_pages(damaged)
    for path, extra in [(named / 'peer.sqlite3', ['--live-data-dir', named]), (store.db_path, []), (link, []), (damaged, [])]:
        before = path.read_bytes()
        code, out, err = reconcile(capsys, '--db', path, *extra)
        assert code == 1 and err.startswith('Refused') and out == '', (path, err)
        assert path.read_bytes() == before


def test_reconcile_rolls_back_when_a_step_fails(tmp_path, monkeypatch, capsys):
    """R18: a later step raises; the earlier steps' writes roll back, the staged bytes are unchanged and the exit is 1."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')               # a session for step 1 to delete
    copy = staged(tmp_path, store)
    before = copy.read_bytes()

    def fails(*args):
        raise RuntimeError('step 5 failed')

    monkeypatch.setattr(backups, '_raise_sequences', fails)
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 1 and 'nothing was changed' in err and 'RuntimeError' in err
    assert copy.read_bytes() == before and not Path(f'{copy}-journal').exists()


def test_reconcile_without_the_replaced_file_fails_closed(tmp_path, capsys):
    """R18: without a usable replaced file every owned ship's keys are revoked, and the station's ships (no owner) keep
    theirs. A replaced file of junk bytes, or a symlink (here to the usable live file), gives the same result as none,
    and the report says it was treated as absent and why."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, serenity_key = docked(store, andy['id'], 'serenity')
    odo = store.create_station_ship('odo', 'Odo')
    odo_key = store.issue_ship_key(odo['id'])
    why = {None: 'not given', 'junk': 'treated as absent (it failed its check)', 'link': 'treated as absent (it is a symlink)'}
    for label, replaced in (('replaced-none', None), ('replaced-junk', 'junk'), ('replaced-link', 'link')):
        copy = staged(tmp_path, store, label)
        args = ['--db', copy]
        if replaced == 'junk':
            (copy.parent / 'peer.sqlite3').write_bytes(os.urandom(8192))
        elif replaced == 'link':
            (copy.parent / 'peer.sqlite3').symlink_to(store.db_path)
        if replaced:
            args += ['--replaced', copy.parent / 'peer.sqlite3']
        code, out, err = reconcile(capsys, *args)
        assert code == 0, err
        assert 'Ship keys revoked for: serenity.' in out.splitlines()
        assert f'The replaced file was {why[replaced]}.' in out
        live = go_live(copy, tmp_path / f'live-{label}')
        with pytest.raises(Problem):
            live.ship_for_key(serenity_key)
        assert live.ship_for_key(odo_key)['username'] == 'odo'


def test_reconcile_skips_what_an_older_copy_lacks(tmp_path, capsys):
    """R18, S16 'An older copy': a copy without access_requests.share_url and without space_members reconciles with exit
    0, takes back its sessions, invitations and keys, and names the two skipped steps."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    store.create_space(andy['id'], 'Crew', 'project', [jenn['id']])
    session = store.login('jenn', 'long-password-jenn', 'test')
    invitation = store.invite(andy['id'])
    started = store.start_docking('defiant', 'bazzite')
    store.confirm_docking(andy['id'], started['id'], started['code'])   # confirmed; its key not collected yet
    with store.transaction() as db:
        held_key = db.execute('SELECT key FROM dockings WHERE id=?', (started['id'],)).fetchone()[0]
    copy = staged(tmp_path, store)
    with closing(sqlite3.connect(copy)) as db:                          # the copy as an older station wrote it
        db.execute('ALTER TABLE access_requests DROP COLUMN share_url')
        db.execute('DROP TABLE space_members')
        db.commit()
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert 'Skipped, because this copy lacks them: access_requests.share_url, space_members.' in out.splitlines()
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.session(session['token'])
    with pytest.raises(Problem):
        live.redeem(invitation['token'], 'newcomer', 'Newcomer', 'long-password-newcomer')
    with pytest.raises(Problem):
        live.ship_for_key(held_key)


def test_reconcile_takes_back_what_the_restore_revived(tmp_path, capsys):
    """R18: copy a station (A); then in the live file (B) revoke a key, remove a room member, demote an admin, use an
    invitation, deny a request and record a mention. Reconciling A against B takes all of it back, never raises a role,
    reports a changed password and a changed active layer without applying them, and prints no hash, key or token."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn', is_admin=True)
    patient = store.create_user('patient', 'Patient', 'long-password-patient')
    serenity, key = docked(store, andy['id'], 'serenity')
    room = store.create_room(andy['id'], 'Ops', [patient['id'], serenity['id']])
    space = store.create_space(andy['id'], 'Crew', 'project', [patient['id']])
    invitation = store.invite(andy['id'])
    request = store.request_access('Eve', 'eve@example.org', '')
    session = store.login('patient', 'long-password-patient', 'test')
    layer = store.create_layer(andy['id'], {'title': 'Station law', 'body': 'Ask before you merge.'})
    store.activate_layer(andy['id'], layer['id'], layer['version'])
    copy = staged(tmp_path, store)                                               # A
    store.revoke_ship(andy['id'], serenity['id'])                                # B moves on
    store.remove_participant(andy['id'], room['id'], patient['id'])
    store.change_space_member(andy['id'], space['id'], patient['id'], remove=True)
    store.redeem(invitation['token'], 'newcomer', 'Newcomer', 'long-password-newcomer')
    store.decide_access_request(andy['id'], request['id'], False)
    store.send_message(andy['id'], room['id'], 'after-the-copy', '@serenity a mention recorded after the copy')
    store.withdraw_layer(andy['id'], layer['id'])
    with store.transaction() as db:
        db.execute('UPDATE users SET is_admin=0 WHERE id=?', (jenn['id'],))                        # demoted in B
        db.execute('UPDATE users SET is_admin=1 WHERE id=?', (patient['id'],))                     # promoted in B
        db.execute('UPDATE users SET salt=?, password_hash=? WHERE id=?', (b'\x01' * 16, b'\x02' * 32, patient['id']))
        mention_seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name='mentions'").fetchone()[0]
        hashes = [row[0].hex() for row in db.execute('SELECT password_hash FROM users')]
    with closing(sqlite3.connect(copy)) as db:
        hashes += [row[0].hex() for row in db.execute('SELECT password_hash FROM users')]
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.ship_for_key(key)                                                   # the key is refused
    with pytest.raises(Problem):
        live.get_room(patient['id'], room['id'])                                 # the member can't read the room
    with live.transaction() as db:
        roles = {row['username']: row['is_admin'] for row in db.execute('SELECT username, is_admin FROM users')}
        crew = [row[0] for row in db.execute('SELECT user_id FROM space_members WHERE space_id=?', (space['id'],))]
        sessions = db.execute('SELECT count(*) FROM sessions').fetchone()[0]
        counters = (db.execute('SELECT epoch FROM rooms WHERE id=?', (room['id'],)).fetchone()[0],
                    db.execute('SELECT version FROM spaces WHERE id=?', (space['id'],)).fetchone()[0])
    assert (roles['jenn'], roles['patient'], roles['andy']) == (0, 0, 1)         # lowered, never raised
    assert counters == (2, 2)            # raised once, as remove_participant and change_space_member do (review N6)
    assert patient['id'] not in crew
    with pytest.raises(Problem):
        live.redeem(invitation['token'], 'newcomer-again', 'Newcomer', 'long-password-newcomer')
    assert request['id'] not in [item['id'] for item in live.station_pending()]
    with pytest.raises(Problem):
        live.decide_access_request(andy['id'], request['id'], True)
    assert sessions == 0
    with pytest.raises(Problem):
        live.session(session['token'])
    live.send_message(andy['id'], room['id'], 'after-the-restore', '@serenity a mention after the restore')
    with live.transaction() as db:
        assert db.execute('SELECT max(seq) FROM mentions').fetchone()[0] > mention_seq
    assert live.login('patient', 'long-password-patient', 'test')['user']['username'] == 'patient'   # reported, not applied
    lines = out.splitlines()
    assert lines[0] == backups.REPORT_HEADER
    assert 'Ship keys revoked for: serenity.' in lines and 'Roles lowered for: jenn.' in lines
    assert f'Removed: patient from room {room["id"][:6]} Ops; patient from space {space["id"][:6]} Crew.' in lines
    assert any(line.startswith('Reported, not applied: these passwords differ from the replaced file: patient.') for line in lines)
    assert any(line.startswith(f'Reported, not applied: law layers whose active revision differs: {layer["id"][:6]} Station law')
               for line in lines)
    for secret in [key, token_hash(key), invitation['token'], token_hash(invitation['token']), session['token'], *hashes]:
        assert secret not in out


def test_reconcile_takes_back_every_other_step(tmp_path, capsys):
    """R18, S16 (plan review M1): the steps the main test doesn't reach. An activation, an approved request's uncollected
    token and share link, a waiting docking, a remote room member, a super admin's role, a peer's pairing and the events
    sequence. Lowering the only active super admin is said (review N5)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    activation = json.loads((tmp_path / 'activation.json').read_text())['token']
    request = store.request_access('Eve', 'eve@example.org', '')
    store.decide_access_request(andy['id'], request['id'], True)                  # approved; token not yet collected
    waiting = store.start_docking('defiant', 'bazzite')                           # waiting for a person to confirm
    room = store.create_room(andy['id'], 'Ops', [])
    peer = 'ab' * 32
    with store.transaction() as db:
        db.execute("UPDATE access_requests SET share_url='https://login.tailscale.com/admin/invite/abc', share_status='ready' WHERE id=?", (request['id'],))
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
        db.execute("INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES('contact-1', ?, 'remote-user', 'Remote')", (peer,))
        db.execute("INSERT INTO remote_room_members(room_id, contact_id) VALUES(?, 'contact-1')", (room['id'],))
        db.execute('UPDATE users SET is_super_admin=1 WHERE id=?', (andy['id'],))
    copy = staged(tmp_path, store)                                                # A
    store.redeem(activation, 'root', 'Root', 'long-password-root')                # B moves on
    with store.transaction() as db:
        db.execute('DELETE FROM remote_room_members WHERE room_id=?', (room['id'],))
        db.execute('UPDATE users SET is_super_admin=0 WHERE id=?', (andy['id'],))
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (peer,))
    store.send_message(andy['id'], room['id'], 'after-the-copy', 'an event after the copy')
    with store.transaction() as db:
        events = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.redeem(activation, 'root', 'Root', 'long-password-root')
    status = live.access_request_status(request['id'], request['secret'])
    assert 'token' not in status and 'share_url' not in status
    assert waiting['id'] not in [item['id'] for item in live.station_pending()]
    with pytest.raises(Problem):
        live.confirm_docking(andy['id'], waiting['id'], waiting['code'])
    with live.transaction() as db:
        assert db.execute('SELECT count(*) FROM remote_room_members').fetchone()[0] == 0
        assert db.execute("SELECT is_super_admin FROM users WHERE username='andy'").fetchone()[0] == 0
        assert live.emit(db, 'probe', 'probe', 1) > events
    lines = out.splitlines()
    assert f'Reported, not applied: peers whose pairing differs: {peer[:12]}.' in lines
    assert any(line.startswith('No active super admin remains after lowering roles') for line in lines)
    for secret in ['https://login.tailscale.com/admin/invite/abc', activation, token_hash(activation)]:
        assert secret not in out


def test_reconcile_without_a_replaced_file_raises_both_sequences(tmp_path, capsys):
    """R18, S16 step 5 without a replaced file (plan review M1): mentions and events jump by SEQUENCE_JUMP."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    copy = staged(tmp_path, store)
    with closing(sqlite3.connect(copy)) as db:
        before = dict(db.execute("SELECT name, seq FROM sqlite_sequence WHERE name IN ('mentions', 'events')").fetchall())
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        after = dict(db.execute("SELECT name, seq FROM sqlite_sequence WHERE name IN ('mentions', 'events')").fetchall())
    # S16's 1,000,000, not the module's constant: a smaller jump would leave a watcher's saved cursor hiding mentions
    assert after == {table: before.get(table, 0) + 1_000_000 for table in ('mentions', 'events')}


def test_reconcile_refuses_a_hard_link_and_a_same_or_older_replaced_file(tmp_path, capsys):
    """R18, S16 fails closed (plan review M2): a hard link to the live file elsewhere, --replaced naming the staged copy
    itself, and a replaced file older than the staged copy (DB= and REPLACED= swapped) are each refused, and no file
    changes."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    older = staged(tmp_path, store, 'replaced-older')
    store.send_message(andy['id'], room['id'], 'after-the-copy', 'an event after the copy')
    newer = staged(tmp_path, store, 'replaced-newer')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    os.link(store.db_path, elsewhere / 'peer-link.sqlite3')
    for args, touched in [(['--db', elsewhere / 'peer-link.sqlite3'], store.db_path),
                          (['--db', older, '--replaced', older], older),
                          (['--db', newer, '--replaced', older], newer)]:
        before = touched.read_bytes()
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and err.startswith('Refused') and out == '', (args, err)
        assert touched.read_bytes() == before


def test_reconcile_closes_breakouts_closed_since_the_copy(tmp_path, capsys):
    """R18, S16 (Rio Grande's ruling on the plan review's Q1): a breakout closed in the replaced file is closed in the copy
    too, so its members can't post or be mentioned there again, and its deferrals are dropped as closing one drops them
    (fix round 1, review minor 3); a breakout open in both stays open, with its deferral."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, _ = docked(store, andy['id'], 'serenity')
    rio, _ = docked(store, andy['id'], 'rio-grande')
    store.create_room(andy['id'], 'City of AI', [serenity['id'], rio['id']])      # the ships share a person's room
    side = store.open_breakout(serenity['id'], 'Side', ['rio-grande'])
    other = store.open_breakout(serenity['id'], 'Other side', ['rio-grande'])
    asked = store.send_message(serenity['id'], side['id'], 'asked', '@rio-grande over here')
    kept = store.send_message(serenity['id'], other['id'], 'kept', '@rio-grande and here')
    with store.transaction() as db:                                               # rio-grande deferred both (S5)
        db.executemany('INSERT INTO deferrals(ship_id, message_id, first_deferred) VALUES(?, ?, 0)',
                       [(rio['id'], asked['id']), (rio['id'], kept['id'])])
    copy = staged(tmp_path, store)                                                # A: both open
    store.close_breakout(serenity['id'], side['id'])                              # B: Side closed
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert f'Breakouts closed as in the replaced file: {side["id"][:6]} Side.' in out.splitlines()
    live = go_live(copy, tmp_path / 'live')
    with live.transaction() as db:
        assert [row[0] for row in db.execute('SELECT message_id FROM deferrals')] == [kept['id']]
    with pytest.raises(Problem):
        live.send_message(rio['id'], side['id'], 'after-the-restore', 'still here?')
    assert live.send_message(rio['id'], other['id'], 'after-the-restore', 'still open')['replayed'] is False


def sequences(path):
    """The mentions and events sequences of a database file, as {name: seq}."""
    with closing(sqlite3.connect(path)) as db:
        return dict(db.execute("SELECT name, seq FROM sqlite_sequence WHERE name IN ('mentions', 'events')").fetchall())


def test_reconcile_treats_a_replaced_file_that_isnt_this_stations_as_absent(tmp_path, capsys):
    """Fix round 1 (review I1): a replaced file can pass quick_check and still not be this station's: a 0-byte file is a
    valid empty database, and another station's file has the tables but not the copy's accounts and ship keys. Either is
    treated as absent, so the reconcile fails closed: every owned ship's keys are revoked, both sequences jump by
    1,000,000, and the report says why without naming an id. So is this station's file with its ship keys lost, since
    keys are never deleted."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, key = docked(store, andy['id'], 'serenity')
    elsewhere = Store(tmp_path / 'elsewhere')                                    # another station, built the same way
    docked(elsewhere, elsewhere.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)['id'], 'serenity')
    why = {'empty': 'treated as absent (it lacks tables or columns the copy has: ',
           'elsewhere': "treated as absent (it lacks accounts or ship keys the copy has, so it is another station's file "
                        'or a damaged one)'}
    why['keys-lost'] = why['elsewhere']
    for label in ('empty', 'elsewhere', 'keys-lost'):
        copy = staged(tmp_path, store, f'replaced-{label}')
        replaced = copy.parent / 'peer.sqlite3'
        if label == 'empty':
            replaced.write_bytes(b'')
        elif label == 'elsewhere':
            shutil.copyfile(elsewhere.db_path, replaced)
        else:
            shutil.copyfile(store.db_path, replaced)
            with closing(sqlite3.connect(replaced)) as db:
                db.execute('DELETE FROM ship_keys')
                db.commit()
        before = sequences(copy)
        code, out, err = reconcile(capsys, '--db', copy, '--replaced', replaced)
        assert code == 0, err
        lines = out.splitlines()
        assert lines[1].startswith(f'The replaced file was {why[label]}') and 'Compared with the replaced file.' not in lines
        assert 'Ship keys revoked for: serenity.' in lines
        assert sequences(copy) == {table: before.get(table, 0) + 1_000_000 for table in ('mentions', 'events')}
        live = go_live(copy, tmp_path / f'live-{label}')
        with pytest.raises(Problem):
            live.ship_for_key(key)
        with live.transaction() as db:
            ids = [row[0] for row in db.execute('SELECT id FROM users UNION ALL SELECT id FROM ship_keys')]
        assert not any(value in out for value in ids)


def test_reconcile_reports_the_error_sqlite_rolled_back_on(tmp_path, monkeypatch, capsys):
    """Fix round 1 (review minor 1): SQLite rolls a transaction back by itself on some errors (SQLITE_FULL, an I/O
    error). The CLI then reports that error, not a failed ROLLBACK, and the staged bytes are unchanged."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')                           # a session for step 1 to delete
    copy = staged(tmp_path, store)
    before = copy.read_bytes()

    def full(db, old, now, report):
        db.execute('ROLLBACK')                                                   # what SQLite did before raising
        raise sqlite3.OperationalError('database or disk is full')

    monkeypatch.setattr(backups, '_raise_sequences', full)
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 1 and out == ''
    assert 'nothing was changed: OperationalError: database or disk is full' in err, err
    assert copy.read_bytes() == before


def interrupted(source, target):
    """target as a write interrupted mid-transaction leaves it: the file, and beside it a hot journal. With synchronous
    off SQLite writes the journal's header at once, so a copy taken mid-write is what a power cut leaves."""
    writing = target.parent / 'writing.sqlite3'
    shutil.copyfile(source, writing)
    with closing(sqlite3.connect(writing, isolation_level=None)) as writer:
        writer.execute('PRAGMA synchronous=OFF')
        writer.execute('BEGIN IMMEDIATE')
        writer.execute("UPDATE users SET name='mid-write'")
        shutil.copyfile(writing, target)
        shutil.copyfile(f'{writing}-journal', f'{target}-journal')
        writer.execute('ROLLBACK')
    writing.unlink()


def test_reconcile_says_why_the_replaced_file_was_treated_as_absent(tmp_path, capsys):
    """Fix round 1 (review minor 2): no file at the --replaced path; a replaced file with a hot journal beside it; and a
    damaged one beside a journal SQLite wouldn't treat as hot (an empty one, or one whose header is still zero because
    its write never synced). Each fails closed with its own reason, and the journal is never touched."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, key = docked(store, andy['id'], 'serenity')
    cases = {'missing': ('there is no such file', None),
             'hot': ('a hot journal beside it, peer.sqlite3-journal', None),
             'empty-journal': ('it failed its check', b''),
             'zeroed-journal': ('it failed its check', bytes(512))}
    for label, (why, journal) in cases.items():
        copy = staged(tmp_path, store, f'replaced-{label}')
        replaced = copy.parent / 'peer.sqlite3'
        if label == 'hot':
            interrupted(store.db_path, replaced)
        elif label != 'missing':
            replaced.write_bytes(os.urandom(8192))
            Path(f'{replaced}-journal').write_bytes(journal)
        beside = Path(f'{replaced}-journal')
        kept = beside.read_bytes() if beside.exists() else None
        code, out, err = reconcile(capsys, '--db', copy, '--replaced', replaced)
        assert code == 0, err
        assert f'The replaced file was treated as absent ({why}).' in out.splitlines()[1], (label, out)
        assert 'Ship keys revoked for: serenity.' in out.splitlines()
        assert (beside.read_bytes() if beside.exists() else None) == kept


def test_reconcile_refuses_a_copy_in_the_backups_rotation(tmp_path, capsys):
    """Fix round 1 (review minor 4): a copy in the rotation is a checked copy, never the staged one, so reconciling it in
    place is refused: a directory holding the rotation's .lock, and backups/station beside the --live-data-dir. Neither
    file changes."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')                           # a session the reconcile would delete
    rotation = backups.default_backup_dir(store.data_dir)
    newest = backups.run_backup(store.data_dir, rotation)
    for args in (['--db', newest], ['--db', newest, '--live-data-dir', store.data_dir]):
        if '--live-data-dir' in args:
            (rotation / '.lock').unlink()                                        # the rotation's own mark gone
        before = newest.read_bytes()
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and err.startswith('Refused') and 'rotation' in err and out == '', (args, err)
        assert newest.read_bytes() == before


def small_station(tmp_path):
    """Two people, a room and a message, with one checked copy in the rotation beside the data dir."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    room = store.create_room(andy['id'], 'Ops', [jenn['id']])
    store.send_message(andy['id'], room['id'], 'm1', 'hello')
    rotation = tmp_path / 'backups' / 'station'
    backups.run_backup(store.data_dir, rotation)
    return store, rotation


def runtime_dir(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(run))
    return run


def restore_test(*args):
    """station-restore-test as the timer runs it; returns its exit code."""
    try:
        cli(['station-restore-test', *map(str, args)])
    except SystemExit as stopped:
        return stopped.code
    return 0


def record_processes(monkeypatch):
    """Every process the restore test starts, so a test can prove none is left."""
    started, real_popen = [], subprocess.Popen

    class Recorded(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(backups.subprocess, 'Popen', Recorded)
    return started


def test_restore_test_boots_a_throwaway_station_from_the_newest_copy(tmp_path, monkeypatch, capsys):
    """R8: a real subprocess server boots from the newest copy; the command exits 0, the scratch directory is gone and the
    port is closed. Leftover scratch directories over a day old are removed; fresh ones and symlinks are not."""
    run = runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    old, fresh, elsewhere = run / 'superyak-restore-test-old', run / 'superyak-restore-test-fresh', tmp_path / 'elsewhere'
    for directory in (old, fresh, elsewhere):
        directory.mkdir()
    (run / 'superyak-restore-test-link').symlink_to(elsewhere)
    two_days_ago = time.time() - 2 * 86400
    for directory in (old, elsewhere):
        os.utime(directory, (two_days_ago, two_days_ago))
    assert restore_test('--backup-dir', rotation) == 0
    out = capsys.readouterr().out
    assert out.startswith(f'Restore test passed: {backups.newest_copy(rotation).name} booted on 127.0.0.1:')
    assert out.rstrip().endswith('; users 2, rooms 1, messages 1.')
    port = int(re.search(r'127\.0\.0\.1:(\d+)', out)[1])
    assert sorted(p.name for p in run.iterdir()) == ['superyak-restore-test-fresh', 'superyak-restore-test-link']
    assert elsewhere.is_dir()
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0


@pytest.mark.parametrize('failure, code', [('no copy', 20), ('damaged copy', 21), ('server exits', 22),
                                           ('counts changed', 23), ('reconcile raises', 24)])
def test_restore_test_failures_clean_up_and_exit_with_their_code(tmp_path, monkeypatch, failure, code):
    """R8, R9: each failure exits with its code, removes the scratch directory and leaves no process."""
    run = runtime_dir(tmp_path, monkeypatch)
    rotation = tmp_path / 'backups' / 'station' if failure == 'no copy' else small_station(tmp_path)[1]
    started = record_processes(monkeypatch)
    if failure == 'damaged copy':
        overwrite_pages(backups.newest_copy(rotation))
    elif failure == 'server exits':
        monkeypatch.setattr(backups, 'server_command', lambda scratch, port: [sys.executable, '-c', 'raise SystemExit(3)'])
    elif failure == 'counts changed':
        real_counts, seen = backups.counts, []

        def changed(db):
            seen.append(real_counts(db))
            users, rooms, messages = seen[-1]
            return seen[-1] if len(seen) == 1 else (users, rooms, messages + 1)

        monkeypatch.setattr(backups, 'counts', changed)
    elif failure == 'reconcile raises':
        def raises(*args, **kwargs):
            raise RuntimeError('a schema change broke the reconcile')

        monkeypatch.setattr(backups, 'reconcile', raises)
    assert restore_test('--backup-dir', rotation) == code
    assert list(run.iterdir()) == []
    assert all(process.poll() is not None for process in started)
    assert len(started) == {'server exits': 3, 'counts changed': 1}.get(failure, 0)


def test_restore_test_has_no_data_dir_option(tmp_path, capsys):
    """R9: it can't name the live data dir."""
    with pytest.raises(SystemExit) as refused:
        cli(['station-restore-test', '--backup-dir', str(tmp_path), '--data-dir', str(tmp_path)])
    assert refused.value.code == 2 and 'unrecognized arguments: --data-dir' in capsys.readouterr().err


def test_restore_test_passes_on_a_copy_from_before_a_migration(tmp_path, monkeypatch, capsys):
    """Review Focus 1: runbook step 2 most likely tests the copy from before a bad migration. A copy without the system
    author, message_kinds, space_members and access_requests.share_url still passes: the counts read the same before the
    server migrates it and after."""
    runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    with closing(sqlite3.connect(backups.newest_copy(rotation))) as db:
        db.execute("DELETE FROM users WHERE id=(SELECT value FROM system_meta WHERE key='system_author')")
        db.execute('DROP TABLE system_meta')
        db.execute('DROP TABLE message_kinds')
        db.execute('DROP TABLE space_members')
        db.execute('ALTER TABLE access_requests DROP COLUMN share_url')
        db.commit()
    assert restore_test('--backup-dir', rotation) == 0
    assert capsys.readouterr().out.rstrip().endswith('; users 2, rooms 1, messages 1.')


@pytest.mark.parametrize('stop', [signal.SIGTERM, signal.SIGHUP])
def test_a_stopped_restore_test_leaves_no_server_and_no_scratch(tmp_path, monkeypatch, stop):
    """Review Focus 3: systemd's TimeoutStartSec= or a person stops the restore test while its station boots. The signal
    becomes SystemExit, so the server is stopped and reaped and the scratch directory is removed."""
    run = runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    started = record_processes(monkeypatch)
    booting = 'import pathlib, sys, time\npathlib.Path(sys.argv[1], "booting").touch()\ntime.sleep(120)\n'
    monkeypatch.setattr(backups, 'server_command', lambda scratch, port: [sys.executable, '-c', booting, str(scratch)])

    def stop_while_booting():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any((p / 'booting').exists() for p in run.glob('superyak-restore-test-*')):
                os.kill(os.getpid(), stop)  # the handler the command installed turns it into SystemExit
                return
            time.sleep(0.05)

    threading.Thread(target=stop_while_booting, daemon=True).start()
    assert restore_test('--backup-dir', rotation) == 128 + stop
    assert list(run.iterdir()) == []
    assert started and all(process.poll() is not None for process in started)
