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
    too, so its members can't post or be mentioned there again; a breakout open in both stays open."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, _ = docked(store, andy['id'], 'serenity')
    rio, _ = docked(store, andy['id'], 'rio-grande')
    store.create_room(andy['id'], 'City of AI', [serenity['id'], rio['id']])      # the ships share a person's room
    side = store.open_breakout(serenity['id'], 'Side', ['rio-grande'])
    other = store.open_breakout(serenity['id'], 'Other side', ['rio-grande'])
    copy = staged(tmp_path, store)                                                # A: both open
    store.close_breakout(serenity['id'], side['id'])                              # B: Side closed
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert f'Breakouts closed as in the replaced file: {side["id"][:6]} Side.' in out.splitlines()
    live = go_live(copy, tmp_path / 'live')
    with pytest.raises(Problem):
        live.send_message(rio['id'], side['id'], 'after-the-restore', 'still here?')
    assert live.send_message(rio['id'], other['id'], 'after-the-restore', 'still open')['replayed'] is False
