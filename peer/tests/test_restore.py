"""The restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S6, S7, S16; R7-R9, R18). Every
test works in tmp_path; the restore test boots real loopback servers and stops every one of them."""
from contextlib import closing
import fcntl
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
import textwrap
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
    that fails its check are each refused with exit 1, each for its own reason, and the file is unchanged. Each is named
    restored.sqlite3, so the CLI's DB= name guard lets it through to its own refusal; the live file itself is refused by
    that guard."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy = staged(tmp_path, store)
    named = tmp_path / 'named' / 'restored.sqlite3'
    named.parent.mkdir()
    shutil.copyfile(copy, named)
    in_live = store.data_dir / 'restored.sqlite3'                              # beside dispatch.lock
    shutil.copyfile(copy, in_live)
    link = tmp_path / 'linked' / 'restored.sqlite3'
    link.parent.mkdir()
    link.symlink_to(copy)
    damaged = tmp_path / 'damaged' / 'restored.sqlite3'
    damaged.parent.mkdir()
    shutil.copyfile(copy, damaged)
    overwrite_pages(damaged)
    for path, extra, why in [(named, ['--live-data-dir', named.parent], 'in a live data directory'),
                             (in_live, [], 'in a live data directory'), (link, [], 'is a symlink'),
                             (damaged, [], 'failed its integrity check'), (store.db_path, [], 'this file is named peer.sqlite3')]:
        before = path.read_bytes()
        code, out, err = reconcile(capsys, '--db', path, *extra)
        assert code == 1 and err.startswith('Refused') and why in err and out == '', (path, err)
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
    # Final review M4: today's schema against today's schema skips and leaves uncompared nothing, so a future rename
    # (against "migrations only add") can't silently drop a take-back step.
    assert not any(line.startswith(('Skipped', 'Not compared')) for line in lines), out


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
    assert any(line.startswith(f'Unpaired again: {peer[:12]} (Remote).') for line in lines)
    assert any(line.startswith('No active super admin remains after lowering roles') for line in lines)
    for secret in ['https://login.tailscale.com/admin/invite/abc', activation, token_hash(activation)]:
        assert secret not in out


def peer_station(tmp_path):
    """A station with four peers and their contacts, outbox rows (pending, failed, delivered, sent) and inbox payloads."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    peers = {'cut': 'cd' * 32, 'kept': 'ef' * 32, 'later': '12' * 32, 'ghost': '34' * 32}
    with store.transaction() as db:
        for key, paired in (('cut', 1), ('kept', 1), ('later', 0), ('ghost', 1)):
            db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', ?)", (peers[key], paired))
        for contact, key, name in (('c-cut', 'cut', 'Cut One'), ('c-cut2', 'cut', 'Cut Two'), ('c-kept', 'kept', 'Kept'),
                                   ('c-later', 'later', 'Later'), ('c-ghost', 'ghost', 'Ghost')):
            db.execute('INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES(?, ?, ?, ?)', (contact, peers[key], 'u-' + contact, name))
        for number, (contact, status) in enumerate((('c-cut', 'pending'), ('c-cut2', 'failed'), ('c-cut', 'delivered'), ('c-cut', 'sent'),
                                                    ('c-kept', 'pending'), ('c-kept', 'failed'), ('c-later', 'pending'), ('c-ghost', 'pending'))):
            db.execute("INSERT INTO outbox(id, event_seq, contact_id, resource_id, revision, action, metadata, status) "
                       "VALUES(?, ?, ?, 'r', 1, 'room.message', '{}', ?)", (f'o{number}', number, contact, status))
        for peer in peers.values():
            db.execute("INSERT INTO inbox(origin, resource_id, kind, recipient, revision, actor, payload) VALUES(?, 'r', 'k', ?, 1, 'a', 'text')",
                       (peer, andy['id']))
    return store, peers


def peer_rows(copy):
    with closing(sqlite3.connect(copy)) as db:
        return (dict(db.execute('SELECT peer_id, paired FROM peers').fetchall()),
                dict(db.execute('SELECT id, status FROM outbox').fetchall()),
                dict(db.execute('SELECT origin, payload FROM inbox').fetchall()))


def test_reconcile_unpairs_a_peer_as_federation_unpair_does(tmp_path, capsys):
    """S16 revision 4 (Task 11 review C1 and its D8 re-check). A peer paired in the copy and unpaired in the replaced file
    ends paired=0, its contacts' pending and failed outbox rows withdrawn (delivered and sent untouched), its inbox payloads
    NULL. A peer unpaired in the copy and paired in the replaced file stays unpaired and is reported; a peer the replaced
    file lacks stays paired and is reported; another peer is unchanged. Mutations: an unpair that leaves paired=1; no outbox
    withdraw; no inbox null; the reverse direction applied; an absent peer unpaired."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    with store.transaction() as db:                      # after the copy: Andy cuts one peer off, and pairs another
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (peers['cut'],))
        db.execute('UPDATE peers SET paired=1 WHERE peer_id=?', (peers['later'],))
        db.execute('DELETE FROM outbox WHERE contact_id=?', ('c-ghost',))
        db.execute('DELETE FROM inbox WHERE origin=?', (peers['ghost'],))
        db.execute('DELETE FROM remote_contacts WHERE peer_id=?', (peers['ghost'],))
        db.execute('DELETE FROM peers WHERE peer_id=?', (peers['ghost'],))    # the replaced file lacks this peer
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    paired, outbox, inbox = peer_rows(copy)
    assert paired == {peers['cut']: 0, peers['kept']: 1, peers['later']: 0, peers['ghost']: 1}
    assert outbox == {'o0': 'withdrawn', 'o1': 'withdrawn', 'o2': 'delivered', 'o3': 'sent', 'o4': 'pending', 'o5': 'failed',
                      'o6': 'pending', 'o7': 'pending'}
    assert inbox == {peers['cut']: None, peers['kept']: 'text', peers['later']: 'text', peers['ghost']: 'text'}
    lines = out.splitlines()
    assert (f'Unpaired again: {peers["cut"][:12]} (Cut One, Cut Two). Withdrew 2 pending and failed deliveries '
            'and cleared 1 received payloads.') in lines
    assert (f'Reported, not applied: peers: paired in the replaced file but not here: {peers["later"][:12]} (Later); '
            f'paired here and absent from the replaced file, so left paired: {peers["ghost"][:12]} (Ghost).') in lines
    assert not any(peers['kept'][:12] in line for line in lines)


def test_reconcile_unpair_names_a_peer_with_or_without_a_replaced_file(tmp_path, capsys):
    """--unpair PEER (revision 4): a 12-character or full id unpairs that peer as above, repeatable, with or without
    --replaced. An unknown or ambiguous id is refused with exit 2 and nothing changed. Mutation: --unpair ignored."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    before = peer_rows(copy)
    for bad in ('nope', 'c', peers['cut'][:11], peers['cut'] + 'ab'):
        code, out, err = reconcile(capsys, '--db', copy, '--unpair', bad)
        assert code == 2 and 'Refused' in err and out == '', bad
        assert peer_rows(copy) == before
    code, out, err = reconcile(capsys, '--db', copy, '--unpair', peers['cut'][:12], '--unpair', peers['kept'])
    assert code == 0, err
    paired, outbox, inbox = peer_rows(copy)
    assert paired == {peers['cut']: 0, peers['kept']: 0, peers['later']: 0, peers['ghost']: 1}
    assert outbox['o0'] == outbox['o1'] == 'withdrawn' and outbox['o2'] == 'delivered' and outbox['o6'] == 'pending'
    assert inbox[peers['cut']] is None and inbox[peers['ghost']] == 'text'
    assert f'Unpaired again: {peers["cut"][:12]} (Cut One, Cut Two); {peers["kept"][:12]} (Kept).' in out
    second = staged(tmp_path, store, 'replaced-20261017-130000')           # with a replaced file naming a third peer
    with store.transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (peers['ghost'],))
    code, out, err = reconcile(capsys, '--db', second, '--replaced', store.db_path, '--unpair', peers['cut'])
    assert code == 0, err
    assert peer_rows(second)[0] == {peers['cut']: 0, peers['kept']: 1, peers['later']: 0, peers['ghost']: 0}
    assert f'Unpaired again: {peers["ghost"][:12]} (Ghost); {peers["cut"][:12]} (Cut One, Cut Two).' in out


def test_reconcile_unpairs_nothing_without_a_replaced_file(tmp_path, capsys):
    """S16 revision 4: without a usable replaced file (or --unpair) every peer stays paired. Mutation: unpair outside the
    compared branch."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    before = peer_rows(copy)
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    assert peer_rows(copy) == before and 'Unpaired' not in out


def test_reconcile_unpair_refuses_an_ambiguous_id_and_changes_no_byte(tmp_path, capsys):
    """--unpair with a short id two peers share is refused (exit 2) and the staged copy is byte for byte unchanged, also when
    the refusal comes after other work. A full id picks the one peer even if another shares its prefix, and the report does
    not call a lacked peer both unpaired and left paired. Mutations: `len(matches) != 1` -> `not matches`; refusing only
    after COMMIT; deduplicate on the 12-character prefix; compute `lacked` before the named unpair."""
    store, peers = peer_station(tmp_path)
    twin = peers['cut'][:12] + 'f' * 52
    with store.transaction() as db:
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (twin,))
    copy = staged(tmp_path, store)
    before = copy.read_bytes()
    for args in (('--unpair', peers['cut'][:12]), ('--unpair', peers['kept'], '--unpair', peers['cut'][:12]),
                 ('--replaced', store.db_path, '--unpair', peers['cut'][:12])):
        code, out, err = reconcile(capsys, '--db', copy, *args)
        assert code == 2 and 'Refused' in err and out == ''
        assert copy.read_bytes() == before
    code, out, err = reconcile(capsys, '--db', copy, '--unpair', twin)
    assert code == 0, err
    paired = peer_rows(copy)[0]
    assert paired[twin] == 0 and paired[peers['cut']] == 1
    stale = staged(tmp_path, store, 'replaced-20261017-140000')           # still has the ghost; the replaced file will lack it
    with store.transaction() as db:
        db.execute('DELETE FROM outbox WHERE contact_id=?', ('c-ghost',))
        db.execute('DELETE FROM inbox WHERE origin=?', (peers['ghost'],))
        db.execute('DELETE FROM remote_contacts WHERE peer_id=?', (peers['ghost'],))
        db.execute('DELETE FROM peers WHERE peer_id=?', (peers['ghost'],))
    code, out, err = reconcile(capsys, '--db', stale, '--replaced', store.db_path, '--unpair', peers['ghost'])
    assert code == 0, err
    assert f'Unpaired again: {peers["ghost"][:12]} (Ghost).' in out
    assert 'left paired' not in out


def test_unpair_prefix_dedupe_is_by_full_id(tmp_path, capsys):
    """N3: two peers share a 12-character prefix and the replaced file unpaired the first; --unpair with the other's full id
    still unpairs the other. Mutation: deduplicate on the 12-character prefix."""
    store = Store(tmp_path / 'lighthouse')
    first, second = 'ab' * 6 + '1' * 52, 'ab' * 6 + '2' * 52
    with store.transaction() as db:
        for peer in (first, second):
            db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
    copy = staged(tmp_path, store)
    with store.transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (first,))
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path, '--unpair', second)
    assert code == 0, err
    assert peer_rows(copy)[0] == {first: 0, second: 0}


def test_absent_replaced_file_sends_peers_to_step_5_not_step_8(tmp_path, capsys):
    """N1: when the replaced file is treated as absent the report sends peer pairings to step 5's UNPAIR= run, before the copy
    goes live, and never to step 8 (after the lighthouse serves)."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', tmp_path / 'missing' / 'peer.sqlite3')
    assert code == 0, err
    text = next(line for line in out.splitlines() if line.startswith('The replaced file was'))
    assert 'peer pairings: list them' in text and 'UNPAIR=' in text and 'runbook step 5' in text
    assert 'peer pairings were not compared' not in text
    assert 'law layers were not compared' in text and 'step 8' in text   # the others are still checked by hand in step 8


def test_renew_activation_works_on_a_reconciled_copy(tmp_path, capsys):
    """Runbook step 7: reconcile marks every activation used, and bootstrap-super-admin --renew-activation still works on
    the reconciled copy (it needs only the pending first super admin) and its new token redeems."""
    store = Store(tmp_path / 'lighthouse')
    store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    copy = staged(tmp_path, store)
    code, out, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    renewed = tmp_path / 'renewed.json'
    cli(['bootstrap-super-admin', '--data-dir', str(tmp_path / 'live'), '--username', 'root', '--name', 'Root',
         '--activation-file', str(renewed), '--renew-activation'])
    assert stat_mode(renewed) == 0o600
    live.redeem(json.loads(renewed.read_text())['token'], 'root', 'Root', 'long-password-root')


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


def test_reconcile_runs_twice_on_one_staged_copy(tmp_path, capsys):
    """Runbook step 5 without a replaced file: a second run (with --unpair) on the same staged copy succeeds, changes
    nothing a first run took back, and raises the sequences by SEQUENCE_JUMP again (harmless)."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    assert reconcile(capsys, '--db', copy)[0] == 0
    with closing(sqlite3.connect(copy)) as db:
        first = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
    code, out, err = reconcile(capsys, '--db', copy, '--unpair', peers['cut'][:12])
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        second = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()[0]
    assert second == first + backups.SEQUENCE_JUMP
    assert peer_rows(copy)[0][peers['cut']] == 0 and peer_rows(copy)[0][peers['kept']] == 1


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
    changes. The swap's older file is named peer.sqlite3, so the CLI's REPLACED= name guard lets it through to the
    sequence check. The CLI refuses the staged copy itself as REPLACED= by its name, so the samefile check (reachable only
    through reconcile(), since two names for one file are a hard link) is tested there."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    older = staged(tmp_path, store, 'replaced-older')
    older_named = older.parent / 'peer.sqlite3'
    shutil.copyfile(older, older_named)
    store.send_message(andy['id'], room['id'], 'after-the-copy', 'an event after the copy')
    newer = staged(tmp_path, store, 'replaced-newer')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    os.link(store.db_path, elsewhere / 'restored.sqlite3')                     # a hard link to the live file
    before = older.read_bytes()
    with pytest.raises(backups.ReconcileRefused, match='the staged copy itself'):
        backups.reconcile(older, replaced=older)
    assert older.read_bytes() == before
    for args, touched, why in [(['--db', elsewhere / 'restored.sqlite3'], store.db_path, 'a hard link'),
                               (['--db', older, '--replaced', older], older, 'this file is named restored.sqlite3'),
                               (['--db', newer, '--replaced', older_named], newer, 'Are DB= and REPLACED= swapped?')]:
        before = touched.read_bytes()
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and err.startswith('Refused') and why in err and out == '', (args, err)
        assert touched.read_bytes() == before


def set_aside(store, copy):
    """Runbook step 4: the live database moved into the restore's directory as peer.sqlite3, beside the staged copy."""
    original = copy.parent / 'peer.sqlite3'
    shutil.copyfile(store.db_path, original)
    return original


def files_beside(*paths):
    """Each file's bytes, and every journal or WAL beside it, so a test can show nothing was written."""
    return {str(path): path.read_bytes() for path in paths} | {
        str(side): side.read_bytes() for path in paths for end in ('-journal', '-wal', '-shm')
        if (side := Path(f'{path}{end}')).exists()}


def test_reconcile_refuses_the_set_aside_original_as_db(tmp_path, capsys):
    """Final review I1: a slip at runbook step 5 that names the set-aside original as DB= is refused, so that file (the
    rollback target) is never rewritten and step 6 never installs a staged copy left unreconciled. (a) The original as
    DB= without REPLACED=. (b) DB= and REPLACED= swapped with no event since the copy, so the events sequences are equal
    and the swap check can't see it. Each exits 1 and says why, and neither file changes by a byte. The CLI's DB= name
    guard (DB= must be restored.sqlite3), into which I1's own check was folded, refuses both. Mutation: drop that guard
    ((a) exits 0 and rewrites the original: its sessions deleted, its owned keys revoked)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    docked(store, andy['id'], 'serenity')                                        # an owned key (a) would revoke
    store.login('andy', 'long-password-andy', 'test')                           # a session either would delete
    copy = staged(tmp_path, store)
    original = set_aside(store, copy)
    assert sequences(original) == sequences(copy)                               # (b): no event since the copy
    for args in (['--db', original, '--live-data-dir', store.data_dir],
                 ['--db', original, '--replaced', copy, '--live-data-dir', store.data_dir]):
        before = files_beside(original, copy)
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and out == '' and err.startswith('Refused'), (args, err)
        assert 'this file is named peer.sqlite3' in err and 'swapped?' in err and 'never rewritten' in err, err
        assert files_beside(original, copy) == before


REPO = Path(__file__).resolve().parents[2]
MAKE_VARIABLES = ('DB', 'REPLACED', 'UNPAIR', 'OUTPUT', 'BACKUP', 'STATION_DATA', 'STATION_BACKUPS', 'MAKEFLAGS', 'MFLAGS',
                  'MAKELEVEL')


@pytest.mark.skipif(not (REPO / 'Makefile').is_file() or not shutil.which('make') or not shutil.which('uv'),
                    reason='needs the parent repository Makefile, make and uv')
def test_make_station_restore_reconcile_refuses_the_runbook_slips(tmp_path):
    """Final review I1 and the two name rulings, through the make target and the CLI as Andy runs them: DB= naming the
    set-aside "$ASIDE/peer.sqlite3", with and without REPLACED=, REPLACED= naming "$ASIDE/chosen.sqlite3", and DB= naming
    "$ASIDE/chosen.sqlite3" with the right REPLACED= (probe (f)) each exit non-zero, say why, and change no byte. Step 5
    as written then exits 0."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')
    copy = staged(tmp_path, store)
    chosen = copy.parent / 'chosen.sqlite3'
    shutil.copyfile(copy, chosen)
    original = set_aside(store, copy)
    env = {name: value for name, value in os.environ.items() if name not in MAKE_VARIABLES}
    for db, extra, why in ((original, [], 'this file is named peer.sqlite3'),
                           (original, [f'REPLACED={copy}'], 'this file is named peer.sqlite3'),
                           (copy, [f'REPLACED={chosen}'], 'this file is named chosen.sqlite3'),
                           (chosen, [f'REPLACED={original}'], 'this file is named chosen.sqlite3')):   # probe (f)
        before = files_beside(original, copy, chosen)
        made = subprocess.run(['make', '--no-print-directory', 'station-restore-reconcile', f'DB={db}', *extra,
                               f'STATION_DATA={store.data_dir}'], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
        assert made.returncode != 0 and 'Refused' in made.stderr and why in made.stderr, made.stderr
        assert files_beside(original, copy, chosen) == before
    made = subprocess.run(['make', '--no-print-directory', 'station-restore-reconcile', f'DB={copy}', f'REPLACED={original}',
                           f'STATION_DATA={store.data_dir}'], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert made.returncode == 0 and 'Compared with the replaced file.' in made.stdout, made.stderr   # step 5 as written


def test_reconcile_refuses_a_replaced_file_not_named_peer_sqlite3(tmp_path, capsys):
    """The coordinator's ruling on the fix round's new finding: REPLACED= naming "$ASIDE/chosen.sqlite3" (a typo at runbook
    step 5) compared the copy with itself, exited 0 and left a key revoked since the copy working. REPLACED= must be the
    peer.sqlite3 step 4 set aside: chosen.sqlite3, a restored.sqlite3 and a rotation copy are each refused with exit 1,
    and no file changes by a byte. The real step 5 still reconciles and takes the key back. Mutation: drop the guard
    (the typo exits 0)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, key = docked(store, andy['id'], 'serenity')
    rotation = backups.default_backup_dir(store.data_dir)
    in_rotation = backups.run_backup(store.data_dir, rotation)
    copy = staged(tmp_path, store)                                               # A: restored.sqlite3
    chosen = copy.parent / 'chosen.sqlite3'
    shutil.copyfile(copy, chosen)                                                # what step 1 made and step 5 staged from
    earlier = staged(tmp_path, store, 'replaced-20261016-120000')               # an earlier restore's staged copy
    store.revoke_ship(andy['id'], serenity['id'])                                # B: taken away after the copy
    original = set_aside(store, copy)
    for replaced in (chosen, earlier, in_rotation):
        before = files_beside(copy, chosen, earlier, in_rotation, original)
        code, out, err = reconcile(capsys, '--db', copy, '--replaced', replaced, '--live-data-dir', store.data_dir)
        assert code == 1 and out == '' and err.startswith('Refused'), (replaced, err)
        assert 'peer.sqlite3 that runbook step 4 set aside' in err and f'this file is named {replaced.name}' in err, err
        assert files_beside(copy, chosen, earlier, in_rotation, original) == before
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', original, '--live-data-dir', store.data_dir)
    assert code == 0 and 'Compared with the replaced file.' in out.splitlines(), err
    with pytest.raises(Problem):
        go_live(copy, tmp_path / 'live').ship_for_key(key)


def test_reconcile_refuses_a_db_not_named_restored_sqlite3(tmp_path, capsys):
    """The coordinator's ruling on the re-review's probe (f): DB="$ASIDE/chosen.sqlite3" with the right REPLACED= compared
    and rewrote chosen.sqlite3 with exit 0, left restored.sqlite3 unreconciled for step 6, and a key revoked since the
    copy still worked. DB= must be the restored.sqlite3 step 5 staged: chosen.sqlite3, a hand-made --output copy and the
    set-aside peer.sqlite3 are each refused with exit 1 before anything opens, and no file changes by a byte. Mutation:
    drop the guard (probe (f) exits 0)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    serenity, key = docked(store, andy['id'], 'serenity')
    copy = staged(tmp_path, store)
    chosen = copy.parent / 'chosen.sqlite3'
    shutil.copyfile(copy, chosen)
    by_hand = backups.run_backup(store.data_dir, None, output=tmp_path / 'before-deploy.sqlite3')
    store.revoke_ship(andy['id'], serenity['id'])                                # taken away after the copy
    original = set_aside(store, copy)
    for db in (chosen, by_hand, original):
        before = files_beside(copy, chosen, by_hand, original)
        code, out, err = reconcile(capsys, '--db', db, '--replaced', original, '--live-data-dir', store.data_dir)
        assert code == 1 and out == '' and err.startswith('Refused'), (db, err)
        assert 'DB= must be the restored.sqlite3 that runbook step 5 staged' in err and f'this file is named {db.name}' in err, err
        assert files_beside(copy, chosen, by_hand, original) == before


def test_the_real_step_5_still_reconciles_with_and_without_replaced(tmp_path, capsys):
    """The DB= and REPLACED= name guards leave runbook step 5 as written working: DB="$ASIDE/restored.sqlite3" with
    REPLACED="$ASIDE/peer.sqlite3", and without it, each exit 0, and each takes a second UNPAIR= run on the same staged
    copy."""
    store, peers = peer_station(tmp_path)
    with_replaced = staged(tmp_path, store)
    without = staged(tmp_path, store, 'replaced-20261017-130000')
    original = set_aside(store, with_replaced)
    for copy, replaced, compared in ((with_replaced, ['--replaced', original], 'Compared with the replaced file.'),
                                     (without, [], 'The replaced file was not given.')):
        code, out, err = reconcile(capsys, '--db', copy, *replaced, '--live-data-dir', store.data_dir)
        assert code == 0 and out.splitlines()[1].startswith(compared), (copy, err, out)
        code, out, err = reconcile(capsys, '--db', copy, *replaced, '--live-data-dir', store.data_dir, '--unpair', peers['kept'][:12])
        assert code == 0, (copy, err)
        assert peer_rows(copy)[0][peers['kept']] == 0


def test_a_second_unpair_run_is_not_called_swapped_after_an_absent_replaced_file(tmp_path, capsys):
    """Final review M1: the first run treated the replaced file as absent because it lacks an account the copy has, and
    so raised the copy's sequences by 1,000,000. A second run with the same REPLACED= and an UNPAIR= (runbook step 5)
    treats it as absent again and unpairs the peer, instead of refusing it as swapped. Mutation: the swap check before
    the absent decision ("Are DB= and REPLACED= swapped?", exit 1)."""
    store, peers = peer_station(tmp_path)
    copy = staged(tmp_path, store)
    replaced = set_aside(store, copy)
    with closing(sqlite3.connect(replaced)) as db:                              # damaged: an account the copy has is gone
        db.execute("DELETE FROM users WHERE username='andy'")
        db.commit()
    absent = 'The replaced file was treated as absent (it lacks accounts or ship keys the copy has'
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', replaced)
    assert code == 0 and absent in out, err
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', replaced, '--unpair', peers['cut'][:12])
    assert code == 0, err
    assert absent in out and peer_rows(copy)[0][peers['cut']] == 0


def test_reconcile_refuses_a_copy_that_is_not_a_station_database(tmp_path, capsys):
    """Final review M5: a staged copy without a users table is refused before any write, so step 6 never installs an
    empty station: a 0-byte file (a valid empty database, which a bad install at step 5 leaves) and a database of
    something else. Exit 1, and the file is byte for byte unchanged. Mutation: drop the check (exit 0, "Taken back: .")."""
    aside = tmp_path / 'backups' / 'replaced-20261017-120000'
    aside.mkdir(parents=True, mode=0o700)
    empty, other = aside / 'restored.sqlite3', tmp_path / 'other' / 'restored.sqlite3'
    empty.write_bytes(b'')
    other.parent.mkdir()
    with closing(sqlite3.connect(other)) as db:
        db.execute('CREATE TABLE notes(body TEXT)')
        db.commit()
    for path in (empty, other):
        before = files_beside(path)
        code, out, err = reconcile(capsys, '--db', path)
        assert code == 1 and out == '' and err.startswith('Refused') and 'users' in err, (path, err)
        assert files_beside(path) == before


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
    file changes. The copy is named restored.sqlite3 so the CLI's DB= name guard lets it through to the rotation
    refusal; a rotation copy's own name is refused by that guard."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    store.login('andy', 'long-password-andy', 'test')                           # a session the reconcile would delete
    rotation = backups.default_backup_dir(store.data_dir)
    newest = backups.run_backup(store.data_dir, rotation)
    in_rotation = rotation / 'restored.sqlite3'
    shutil.copyfile(newest, in_rotation)
    for args, why in ((['--db', newest], f'this file is named {newest.name}'), (['--db', in_rotation], 'rotation'),
                      (['--db', in_rotation, '--live-data-dir', store.data_dir], 'rotation')):
        if '--live-data-dir' in args:
            (rotation / '.lock').unlink()                                        # the rotation's own mark gone
        before = files_beside(newest, in_rotation)
        code, out, err = reconcile(capsys, *args)
        assert code == 1 and err.startswith('Refused') and why in err and out == '', (args, err)
        assert files_beside(newest, in_rotation) == before


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


def test_a_signal_just_after_the_server_starts_still_stops_it(tmp_path, monkeypatch):
    """Final review M7: a signal that lands just after Popen returns still stops and reaps the server. Here a trace
    function raises SystemExit, as the restore test's SIGTERM handler does, at the first line _start runs after Popen.
    Mutation: Popen before the try (the server is orphaned)."""
    started = record_processes(monkeypatch)
    monkeypatch.setattr(backups, 'server_command', lambda scratch, port: [sys.executable, '-c', 'import time; time.sleep(60)'])
    fired = []

    def local(frame, event, arg):
        if event == 'line' and started and not fired:
            fired.append(frame.f_lineno)
            raise SystemExit(128 + signal.SIGTERM)
        return local

    def trace(frame, event, arg):
        return local if frame.f_code is backups._start.__code__ else None

    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        with pytest.raises(SystemExit):
            backups._start(tmp_path)
    finally:
        sys.settrace(previous)
        orphans = [process for process in started if process.poll() is None]
        for process in orphans:
            process.kill()
            process.wait()
    assert fired and len(started) == 1 and orphans == []


def test_the_restore_test_never_serves_on_the_live_ports(monkeypatch):
    """Final review M8: the lighthouse's 7435 and the door's 7436 are refused whatever the kernel's ephemeral range, so
    the picker is asked again; a picker that only gives those stops with exit 22 rather than spinning. Mutation: return
    the first port picked."""
    picked = iter([7435, 7436, 7435, 41234])
    monkeypatch.setattr(backups, '_pick_port', lambda: next(picked))
    assert backups._free_port() == 41234
    monkeypatch.setattr(backups, '_pick_port', lambda: 7436)
    with pytest.raises(backups.BackupError) as failed:
        backups._free_port()
    assert failed.value.code == 22


def test_the_restore_test_copies_under_the_rotation_lock(tmp_path, monkeypatch):
    """R8 (final review): the restore test reads the copy under the rotation lock, so pruning can't remove it mid-copy.
    While it copies, another open of the rotation's .lock can't take it. Mutation: nullcontext() for rotation_lock in
    restore_test."""
    runtime_dir(tmp_path, monkeypatch)
    store, rotation = small_station(tmp_path)
    held = []

    def probe(source, target):
        fd = os.open(rotation / '.lock', os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(fd)
        return False                                                             # then stop: exit 21

    monkeypatch.setattr(backups, '_restored_copy', probe)
    with pytest.raises(backups.BackupError) as failed:
        backups.restore_test(rotation)
    assert failed.value.code == 21 and held == [True]


RUNBOOK = REPO / 'docs' / 'station-restore.md'
SYSTEMCTL = '''#!/bin/sh
echo "$*" >> "$LOG"
case "$*" in
  "--user list-units --all --plain --no-legend superyak-ship-*") cat "$UNITS" ;;
  "--user is-enabled "*) awk -v unit="$3" '$1 == unit {print $2}' "$STATES" ;;
  "--user is-active "*) awk -v unit="$3" '$1 == unit {print $3}' "$STATES" ;;
esac
'''
# Each watcher's state before the restore: (is-enabled, is-active, list-units' SUB)
WATCHERS = {'superyak-ship-running.service': ('enabled', 'active', 'running'),
            'superyak-ship-byhand.service': ('disabled', 'active', 'running'),          # started by hand, never enabled
            'superyak-ship-crashed.service': ('enabled', 'activating', 'auto-restart'),  # Restart=always brings it back
            'superyak-ship-failed.service': ('enabled', 'failed', 'failed'),
            'superyak-ship-stopped.service': ('disabled', 'inactive', 'dead')}          # Andy stopped it


def runbook_block(step):
    """The bash lines of runbook step `step`, as Andy pastes them."""
    lines = RUNBOOK.read_text().splitlines()
    start = next(number for number, line in enumerate(lines) if line.startswith(f'{step}. **'))
    begin = next(number for number in range(start, len(lines)) if lines[number].strip() == '```bash')
    end = next(number for number in range(begin + 1, len(lines)) if lines[number].strip() == '```')
    return textwrap.dedent('\n'.join(lines[begin + 1:end]))


def run_runbook(tmp_path, step, aside):
    """Runbook step `step` in bash, with systemctl and make shimmed on PATH and HOME in tmp_path: the real ones never run.
    Returns (stdout, the systemctl and make calls)."""
    shim, home, log = tmp_path / 'bin', tmp_path / 'home', tmp_path / 'calls.log'
    if not shim.exists():
        shim.mkdir()
        home.mkdir()
        (shim / 'systemctl').write_text(SYSTEMCTL)
        (shim / 'make').write_text(f'#!/bin/sh\necho "make $*" >> "{log}"\n')
        for tool in ('systemctl', 'make'):
            (shim / tool).chmod(0o755)
        (tmp_path / 'units.txt').write_text(''.join(f'{unit} loaded {active} {sub} Superyak watcher\n'
                                                    for unit, (_, active, sub) in WATCHERS.items()))
        (tmp_path / 'states.txt').write_text(''.join(f'{unit} {enabled} {active}\n'
                                                     for unit, (enabled, active, _) in WATCHERS.items()))
    log.unlink(missing_ok=True)
    env = {'PATH': f'{shim}:{os.environ["PATH"]}', 'HOME': str(home), 'ASIDE': str(aside), 'LOG': str(log),
           'UNITS': str(tmp_path / 'units.txt'), 'STATES': str(tmp_path / 'states.txt')}
    ran = subprocess.run(['bash', '-c', runbook_block(step)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    return ran.stdout, log.read_text().splitlines() if log.exists() else []


def test_runbook_step_3_does_nothing_without_aside(tmp_path):
    """Final review M2: step 3 with ASIDE unset refuses visibly, as steps 4 and 10.2 do, and stops nothing: before, it
    stopped the ship, odo and wormhole but left every project watcher running, and step 8 never saw them."""
    out, calls = run_runbook(tmp_path, 3, '')
    assert 'NOT stopped: ASIDE is not set' in out
    assert calls == []


def test_runbook_steps_3_and_8_put_each_watcher_back_as_it_was(tmp_path):
    """Final review M3: step 3 stops and disables every loaded watcher, a crashed one in auto-restart included, and saves
    whether each was enabled and running. Step 8 enables again only those that were enabled and starts only those that
    were running, so a watcher Andy had stopped stays stopped. A second step 3 keeps the first list. Mutation: step 8
    enabling and starting every saved watcher."""
    aside = tmp_path / 'replaced-20261017-120000'
    aside.mkdir(mode=0o700)
    out, calls = run_runbook(tmp_path, 3, aside)
    for unit in WATCHERS:
        assert f'--user disable --now {unit}' in calls
    saved = (aside / 'watchers.txt').read_text()
    assert all(unit in saved for unit in WATCHERS)
    (tmp_path / 'states.txt').write_text(''.join(f'{unit} disabled inactive\n' for unit in WATCHERS))   # as step 3 left them
    run_runbook(tmp_path, 3, aside)
    assert (aside / 'watchers.txt').read_text() == saved
    out, calls = run_runbook(tmp_path, 8, aside)
    watchers = [call for call in calls if 'superyak-ship-' in call and not call.startswith('--user is-active')]
    assert watchers == ['--user enable superyak-ship-running.service', '--user enable superyak-ship-crashed.service',
                        '--user enable superyak-ship-failed.service', '--user start superyak-ship-running.service',
                        '--user start superyak-ship-byhand.service', '--user start superyak-ship-crashed.service']
    assert 'make station-rooms' in calls


def step_6(tmp_path, aside):
    """Runbook step 6 as pasted, with HOME in tmp_path: (stdout, the installed peer.sqlite3 or None)."""
    if not (tmp_path / 'home').exists():
        run_runbook(tmp_path, 3, '')                     # only to lay out the shims and HOME; with ASIDE unset it does nothing
    data = tmp_path / 'home' / '.local' / 'share' / 'superyak' / 'lighthouse'
    data.mkdir(parents=True, exist_ok=True)
    out, _ = run_runbook(tmp_path, 6, aside)
    return out, (data / 'peer.sqlite3') if (data / 'peer.sqlite3').exists() else None


def staged_for_step_6(tmp_path, store, label='replaced-20261017-120000'):
    """Runbook steps 1, 4 and 5 up to the reconcile: chosen.sqlite3, restored.sqlite3 staged from it, peer.sqlite3 set aside."""
    copy = staged(tmp_path, store, label)
    chosen = copy.parent / 'chosen.sqlite3'
    shutil.copyfile(copy, chosen)
    return copy, chosen, set_aside(store, copy)


def test_step_6_installs_a_reconciled_copy_and_refuses_one_step_5_never_ran_on(tmp_path, capsys):
    """Follow-up 1: the reconcile writes a mark into the staged copy in its own transaction; step 6's one-liner reads it
    read-only and refuses a copy without it. Mutations: the reconcile writing no mark (the reconciled copy is refused);
    the one-liner not reading the mark (the unreconciled copy is installed)."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy, chosen, original = staged_for_step_6(tmp_path, store)
    before = copy.read_bytes()
    out, installed = step_6(tmp_path, copy.parent)                      # step 5 skipped
    assert installed is None and "NOT installed: step 5 hasn't run on this copy" in out and 'INSTALLED' not in out.split()
    assert copy.read_bytes() == before                                 # the check wrote nothing
    code, report, err = reconcile(capsys, '--db', copy, '--replaced', original)
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        mark = json.loads(db.execute("SELECT value FROM system_meta WHERE key='restore_reconcile'").fetchone()[0])
    assert mark['replaced'] is True and abs(mark['at'] - time.time()) < 300
    out, installed = step_6(tmp_path, copy.parent)
    assert installed is not None and out.split()[-1] == 'INSTALLED' and 'replaced file compared' in out, out
    assert not Path(f'{copy}-journal').exists()


def test_step_6_says_when_the_replaced_file_was_not_compared(tmp_path, capsys):
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy, chosen, original = staged_for_step_6(tmp_path, store)
    code, report, err = reconcile(capsys, '--db', copy)
    assert code == 0, err
    out, installed = step_6(tmp_path, copy.parent)
    assert installed is not None and 'replaced file NOT compared' in out and out.split()[-1] == 'INSTALLED', out


def test_step_6_refuses_a_copy_whose_mark_is_older_than_chosen(tmp_path, capsys):
    """A restored station's own backups carry the mark of its restore. Choosing one of those and skipping step 5 must not
    pass: the mark has to be newer than chosen.sqlite3, which step 1 installed after the mark was written. Mutation: the
    one-liner dropping the comparison with chosen.sqlite3."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    first = staged(tmp_path, store, 'replaced-20261016-120000')
    code, _, err = reconcile(capsys, '--db', first)
    assert code == 0, err
    marked = Store(tmp_path / 'restored-station')
    shutil.copyfile(first, marked.db_path)
    later = staged(tmp_path, marked, 'replaced-20261017-120000')        # a copy of a copy that carries the old mark
    chosen = later.parent / 'chosen.sqlite3'
    shutil.copyfile(later, chosen)
    with closing(sqlite3.connect(later)) as db, db:                    # the old mark names this restore's path: only the clock can refuse it
        mark = json.loads(db.execute("SELECT value FROM system_meta WHERE key='restore_reconcile'").fetchone()[0])
        mark['path'] = str(later)
        db.execute("UPDATE system_meta SET value=? WHERE key='restore_reconcile'", (json.dumps(mark),))
    out, installed = step_6(tmp_path, later.parent)                     # step 5 skipped
    assert installed is None and "step 5 hasn't run on this copy" in out, out


def test_a_rolled_back_reconcile_leaves_no_mark(tmp_path, monkeypatch, capsys):
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy, chosen, original = staged_for_step_6(tmp_path, store)

    def broken(*args):
        raise RuntimeError('a step failed')
    monkeypatch.setattr(backups, '_end_sessions', broken)
    code, _, err = reconcile(capsys, '--db', copy, '--replaced', original)
    assert code == 1
    with closing(sqlite3.connect(copy)) as db:
        assert not db.execute("SELECT 1 FROM system_meta WHERE key='restore_reconcile'").fetchall()
    out, installed = step_6(tmp_path, copy.parent)
    assert installed is None and "step 5 hasn't run" in out


def test_lowering_a_role_bumps_role_version_and_records_a_change(tmp_path, capsys):
    """Follow-up 3: a role the reconcile lowers is recorded as the station's own role changes are (auth.py
    change_account_role): role_version goes up past both files' value, so a browser tab holding the old version is
    refused, and one account_role_changes row names the user, the old and the new role, the new version and the system
    author as actor. A role it does not lower has no row. Mutations: no version bump; no row."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn', is_admin=True)
    sam = store.create_user('sam', 'Sam', 'long-password-sam', is_admin=True)
    kept = store.create_user('kept', 'Kept', 'long-password-kept', is_admin=True)
    with store.transaction() as db:
        db.execute('UPDATE users SET is_super_admin=1 WHERE id IN (?, ?)', (andy['id'], sam['id']))
    copy = staged(tmp_path, store)                                                # A
    store.change_account_role(andy['id'], jenn['id'], 'participant', 1)           # B: jenn 2, then sam 2
    store.change_account_role(andy['id'], sam['id'], 'admin', 1)
    with store.transaction() as db:
        db.execute('UPDATE users SET role_version=5 WHERE id=?', (jenn['id'],))  # B's version is ahead of the copy's
        system = db.execute("SELECT value FROM system_meta WHERE key='system_author'").fetchone()[0]
    with closing(sqlite3.connect(copy)) as db:
        before = db.execute('SELECT count(*) FROM account_role_changes').fetchone()[0]
        copy_versions = dict(db.execute('SELECT username, role_version FROM users'))
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    live = go_live(copy, tmp_path / 'live')
    with live.transaction() as db:
        versions = dict(db.execute('SELECT username, role_version FROM users'))
        roles = dict(db.execute('SELECT username, is_admin + is_super_admin FROM users'))
        rows = [dict(row) for row in db.execute('SELECT * FROM account_role_changes ORDER BY id DESC LIMIT ?', (2,))]
        total = db.execute('SELECT count(*) FROM account_role_changes').fetchone()[0]
    assert (roles['jenn'], roles['sam'], roles['kept']) == (0, 1, 1)
    assert versions['jenn'] == 6 and versions['sam'] == 3 and versions['kept'] == copy_versions['kept']
    assert total == before + 2
    by_user = {row['user_id']: row for row in rows}
    assert {key: by_user[jenn['id']][key] for key in ('actor_id', 'old_role', 'new_role', 'role_version')} == {
        'actor_id': system, 'old_role': 'admin', 'new_role': 'participant', 'role_version': 6}
    assert {key: by_user[sam['id']][key] for key in ('actor_id', 'old_role', 'new_role', 'role_version')} == {
        'actor_id': system, 'old_role': 'super_admin', 'new_role': 'admin', 'role_version': 3}
    assert kept['id'] not in by_user and by_user[jenn['id']]['created'] > 0
    with pytest.raises(Problem) as stale:                                        # a tab that read version 5 is refused
        live.change_account_role(andy['id'], jenn['id'], 'admin', 5)
    assert stale.value.status == 409
    assert live.change_account_role(andy['id'], jenn['id'], 'admin', 6)['role_version'] == 7


def test_reconcile_reports_briefs_changed_since_the_copy_without_their_text(tmp_path, capsys):
    """Follow-up 4: a restore brings back a brief the owner changed or removed since the copy, or loses one written
    since. By room, for rooms in both files, the report names the room's short id and title and the two revisions,
    "reported, not applied", and never a word of any brief; nothing is written to the copy's briefs. Mutation: the
    comparison dropped (nothing reported)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    rooms = {name: store.create_room(andy['id'], name, []) for name in ('Edited', 'Removed', 'Written', 'Same')}
    for name in ('Edited', 'Removed', 'Same'):
        store.save_brief(andy['id'], rooms[name]['id'], f'old secret brief text of {name}', 0)
    copy = staged(tmp_path, store)                                                # A
    store.save_brief(andy['id'], rooms['Edited']['id'], 'new secret brief text of Edited', 1)
    store.save_brief(andy['id'], rooms['Removed']['id'], '', 1)
    store.save_brief(andy['id'], rooms['Written']['id'], 'secret brief written after the copy', 0)
    after_copy = store.create_room(andy['id'], 'Later', [])                       # a room the copy lacks: not compared
    store.save_brief(andy['id'], after_copy['id'], 'secret brief of a later room', 0)
    with closing(sqlite3.connect(copy)) as db:
        before = db.execute('SELECT room_id, revision, body FROM room_briefs ORDER BY room_id').fetchall()
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute('SELECT room_id, revision, body FROM room_briefs ORDER BY room_id').fetchall() == before
    line = next(line for line in out.splitlines() if line.startswith('Reported, not applied: room briefs'))
    short = lambda name: rooms[name]['id'][:6]
    for expected in (f'{short("Edited")} Edited (here revision 1, in the replaced file revision 2)',
                     f'{short("Removed")} Removed (here revision 1, in the replaced file revision 2, removed)',
                     f'{short("Written")} Written (here none, in the replaced file revision 1)'):
        assert expected in line, line
    assert 'Same' not in line and 'Later' not in line
    assert 'secret' not in out and 'brief text of' not in out
    assert not any(row.startswith(('Skipped', 'Not compared')) for row in out.splitlines()), out


def test_a_peer_sharing_its_short_id_prints_its_full_id_in_every_peer_line(tmp_path, capsys):
    """Follow-up 5: UNPAIR= takes a 12-character id or the full id and refuses a short one two peers share, so a report
    line that printed the short id twice would hand Andy an id the next run refuses. For any peer sharing its first 12
    characters with another peer of either file, "Unpaired again" and "Reported, not applied: peers" print the full id;
    a peer with a prefix of its own still prints 12. Mutation: the prefix printed whatever the collision."""
    store = Store(tmp_path / 'lighthouse')
    ids = {'cut_a': 'ab' * 6 + '1' * 52, 'cut_b': 'ab' * 6 + '2' * 52,            # share a prefix; a is unpaired in the replaced file
           'later_a': 'cd' * 6 + '3' * 52, 'later_b': 'cd' * 6 + '4' * 52,        # share a prefix; a is paired there, unpaired here
           'ghost_a': 'ef' * 6 + '5' * 52, 'ghost_b': 'ef' * 6 + '6' * 52,        # share a prefix; a is paired here, absent there
           'alone': '12' * 32}
    ids |= {'new_a': '9a' * 6 + '7' * 52, 'new_b': '9a' * 6 + '8' * 52}            # share a prefix, and only the replaced file has both
    with store.transaction() as db:
        for name, peer in [item for item in ids.items() if not item[0].startswith('new_')]:
            db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', ?)", (peer, 0 if name == 'later_a' else 1))
            db.execute('INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES(?, ?, ?, ?)', ('c-' + name, peer, 'u-' + name, name.title()))
    copy = staged(tmp_path, store)
    with store.transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id IN (?, ?)', (ids['cut_a'], ids['alone']))
        db.execute('UPDATE peers SET paired=1 WHERE peer_id=?', (ids['later_a'],))
        db.execute('DELETE FROM remote_contacts WHERE peer_id=?', (ids['ghost_a'],))
        db.execute('DELETE FROM peers WHERE peer_id=?', (ids['ghost_a'],))
        for peer in (ids['new_a'], ids['new_b']):             # paired since the copy: only the replaced file has them
            db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    lines = out.splitlines()
    unpaired = next(line for line in lines if line.startswith('Unpaired again:'))
    assert f'{ids["cut_a"]} (Cut_A)' in unpaired and f'{ids["alone"][:12]} (Alone)' in unpaired and ids['alone'] not in unpaired
    reported = next(line for line in lines if line.startswith('Reported, not applied: peers:'))
    assert f'{ids["later_a"]} (Later_A)' in reported and f'{ids["ghost_a"]} (Ghost_A)' in reported
    assert ids['new_a'] in reported and ids['new_b'] in reported
    assert ids['cut_b'] not in out and ids['later_b'] not in out and ids['ghost_b'] not in out      # not listed: nothing to name
    # the id printed is one the next run accepts
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path, '--unpair', ids['later_a'])
    assert code == 0, err


# Every table today's schema creates, sorted by what the reconcile does with it. A new table fails the first test below
# until it is put in one list on purpose (the work board's tables came after the backups work was written).
RECONCILED_TABLES = {  # read or changed by a step, or the mark
    'sessions', 'invitations', 'account_activations', 'dockings', 'access_requests', 'ship_keys', 'users', 'mentions',
    'events', 'sqlite_sequence', 'rooms', 'room_members', 'remote_room_members', 'remote_contacts', 'spaces',
    'space_members', 'breakouts', 'deferrals', 'messages', 'layers', 'peers', 'outbox', 'inbox', 'system_meta',
    'account_role_changes', 'room_briefs', 'grants', 'budget_uses', 'member_changes'}
COORDINATION_TABLES = {  # content and coordination, not access: copied as they are
    'board_items', 'board_links', 'claims', 'account_corrections', 'login_attempts', 'login_devices', 'files', 'room_activity',
    'message_kinds', 'message_replies', 'message_sources', 'tickets', 'presence', 'read_cursors', 'inbox_meta',
    'inbox_received', 'receipts', 'peer_messages', 'federation_cursor', 'layer_revisions',
    'revision_signatures', 'room_brief_revisions', 'grant_origins'}


def test_every_table_is_either_reconciled_or_named_coordination(tmp_path, capsys):
    """Follow-up (the work board): the reconcile's view of the schema skips nothing. A station started today has only
    tables in one of the two lists above; the board's items, links and claims are coordination, not access, so a reconcile
    leaves their rows as the copy has them, and reports no table as skipped or not compared. Mutation: 'claims' left out
    of COORDINATION_TABLES (the test names the unclassified table)."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Ops', [])
    with store.transaction() as db:
        db.execute("INSERT INTO board_items(id, room_id, key, title, kind, posted_by, created) VALUES('i1', ?, 'spec:d7', 'A spec', 'spec', ?, 1.0)",
                   (room['id'], andy['id']))
        db.execute("INSERT INTO board_links(item_id, link, added_by, added) VALUES('i1', 'branch:x', ?, 1.0)", (andy['id'],))
        db.execute("INSERT INTO claims(id, room_id, key, holder_id, created, expires) VALUES('c1', ?, 'spec:d7', ?, 1.0, 9e9)",
                   (room['id'], andy['id']))
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables - RECONCILED_TABLES - COORDINATION_TABLES == set()
    assert not RECONCILED_TABLES & COORDINATION_TABLES
    copy = staged(tmp_path, store)

    def rows(path):
        with closing(sqlite3.connect(path)) as db:
            return {table: db.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2').fetchall() for table in sorted(COORDINATION_TABLES & tables)}
    before = rows(copy)
    assert before['board_items'] and before['board_links'] and before['claims']
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert rows(copy) == before
    assert not any(line.startswith(('Skipped', 'Not compared')) for line in out.splitlines()), out


def test_step_6_with_aside_unset_says_to_set_it_and_not_that_step_5_hasnt_run(tmp_path):
    """M1: ASIDE unset (a new terminal) used to print "step 5 hasn't run", sending Andy to a step that cannot work. It
    opens as steps 3 and 4 do. Mutation: the ASIDE check removed from step 6."""
    out, installed = step_6(tmp_path, '')
    assert installed is None and 'NOT installed: ASIDE is not set' in out and "step 5" not in out, out


def test_step_6_refuses_a_mark_recorded_for_another_staged_file(tmp_path, capsys):
    """M2: the mark also holds the staged file's absolute path, and step 6 requires "$ASIDE/restored.sqlite3" to be it,
    so a mark carried from another restore's directory fails whatever the clock says. Mutation: the path comparison
    dropped from the one-liner, or the path not recorded."""
    store = Store(tmp_path / 'lighthouse')
    store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    copy, chosen, original = staged_for_step_6(tmp_path, store)
    code, _, err = reconcile(capsys, '--db', copy, '--replaced', original)
    assert code == 0, err
    with closing(sqlite3.connect(copy)) as db:
        assert json.loads(db.execute("SELECT value FROM system_meta WHERE key='restore_reconcile'").fetchone()[0])['path'] == str(copy)
    with closing(sqlite3.connect(copy)) as db, db:
        db.execute("UPDATE system_meta SET value=json_set(value, '$.path', ?) WHERE key='restore_reconcile'",
                   (str(tmp_path / 'backups' / 'replaced-20250101-000000' / 'restored.sqlite3'),))
    out, installed = step_6(tmp_path, copy.parent)
    assert installed is None and "step 5 hasn't run on this copy" in out, out


def step_5_listing(tmp_path, aside):
    """The peers-listing line of runbook step 5, as pasted (read-only)."""
    text = RUNBOOK.read_text()
    line = next(line.strip() for line in text.splitlines() if line.lstrip().startswith('python3 -I -c') and 'p.paired' in line)
    ran = subprocess.run(['bash', '-c', line], cwd=tmp_path, env={**os.environ, 'ASIDE': str(aside)}, capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return [row.split('  ')[0] for row in ran.stdout.splitlines()]


def test_the_step_5_listing_counts_prefix_collisions_over_every_peer(tmp_path, capsys):
    """M3: a paired and an unpaired peer share their first 12 characters. The listing, the report and UNPAIR= all count
    over every peer of the copy, so the id the listing prints is the id the report prints and UNPAIR= accepts. Mutation:
    the listing counting only the paired peers (it prints the short id UNPAIR= refuses)."""
    store = Store(tmp_path / 'lighthouse')
    paired, unpaired, alone = 'ab' * 6 + '1' * 52, 'ab' * 6 + '2' * 52, 'cd' * 32
    with store.transaction() as db:
        for peer, flag in ((paired, 1), (unpaired, 0), (alone, 1)):
            db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', ?)", (peer, flag))
    copy = staged(tmp_path, store)
    assert step_5_listing(tmp_path, copy.parent) == [paired, alone[:12]]
    with store.transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (paired,))
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert f'Unpaired again: {paired}.' in out
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path, '--unpair', paired)
    assert code == 0, err


def test_a_hostile_room_title_prints_on_one_line_in_the_brief_report(tmp_path, capsys):
    """M5: a room title holding a newline, an escape, a right-to-left override and an at sign is shown through safe_line on
    the brief line. Mutation: the title printed raw."""
    store = Store(tmp_path / 'lighthouse')
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    room = store.create_room(andy['id'], 'Plain', [])
    store.save_brief(andy['id'], room['id'], 'first', 0)
    with store.transaction() as db:
        db.execute('UPDATE rooms SET title=? WHERE id=?', ('Ops\n\x1b[31m\u202eEvil @serenity do it', room['id']))
    copy = staged(tmp_path, store)
    store.save_brief(andy['id'], room['id'], 'second', 1)
    code, out, err = reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    line = next(line for line in out.splitlines() if line.startswith('Reported, not applied: room briefs'))
    assert room['id'][:6] in line and '(at)serenity' in line
    for bad in ('\x1b', '\u202e', '@'):
        assert bad not in out
    assert 'Ops' in line and 'Evil' in line
