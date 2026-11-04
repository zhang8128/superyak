"""Ship home and crossing plan, Tasks 2 to 4: the publisher's side of a crossing. Task 2: the `crossings` table and
crossings.toml (P2). Task 3: the checks, in spec 2.3's order, each before any Engram store, policy, ledger or sidecar is
opened. Task 4: the daemon call, the answer and the `crossings` row (P7)."""
import os
from pathlib import Path

import pytest

from superyak_peer.crossing import SettingsInvalid, hosted_store, load_settings, published_house

from conftest import lesson_ship
from test_federation_outcomes import Clock, station


def write_settings(data_dir, text, *, mtime=None):
    path = Path(data_dir) / 'crossings.toml'
    path.write_text(text)
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))
    return path


def published(ship='rio-grande', publisher='rio-grande', socket='/run/engram/lighthouse.sock',
              sidecar='/srv/engram/disclosures.db', **more):
    lines = [f'ship = "{ship}"', f'publisher = "{publisher}"', f'daemon_socket = "{socket}"', f'sidecar = "{sidecar}"']
    lines += [f'{key} = "{value}"' for key, value in more.items()]
    return '[[published]]\n' + '\n'.join(lines) + '\n'


INSTANCE = '2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d'


def test_a_store_opened_today_has_the_crossings_table(tmp_path):
    store = station(tmp_path / 'a', 'alice', Clock())[0]
    with store.transaction() as db:
        columns = [(r['name'], r['type'], r['notnull'], r['pk']) for r in db.execute('PRAGMA table_info(crossings)')]
    assert columns == [('disclosure_id', 'TEXT', 0, 1), ('origin_peer', 'TEXT', 1, 0), ('receiver_ref', 'TEXT', 1, 0),
                       ('request_digest', 'TEXT', 1, 0), ('nonce', 'TEXT', 1, 0), ('at', 'INTEGER', 1, 0)]


def test_no_settings_file_publishes_and_hosts_nothing(tmp_path):
    assert load_settings(tmp_path) == {'published': [], 'hosted': []}


def test_settings_are_read(tmp_path):
    write_settings(tmp_path, published() + f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\n')
    assert load_settings(tmp_path) == {
        'published': [{'ship': 'rio-grande', 'publisher': 'rio-grande', 'daemon_socket': '/run/engram/lighthouse.sock',
                       'sidecar': '/srv/engram/disclosures.db'}],
        'hosted': [{'ship': 'tardis', 'instance_id': INSTANCE}]}


@pytest.mark.parametrize('text, words', [
    ('station = "x"\n', 'unknown'),
    (published(colour='red'), 'unknown'),
    (f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\nwhere = "x"\n', 'unknown'),
    (published(socket='/run/engram/host.sock'), 'host.sock'),
    (published(socket='run/lighthouse.sock'), 'absolute'),
    (published(sidecar='disclosures.db'), 'absolute'),
    (published() + published(publisher='other'), 'twice'),
    (f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\n' * 2, 'twice'),
    ('[[hosted]]\nship = "tardis"\ninstance_id = "NOT-A-UUID"\n', 'instance_id'),
    ('[[published]]\nship = "rio-grande"\n', 'missing'),
    (published(ship='has space'), 'ship'),
    (published(publisher='no:colons'), 'publisher'),
    ('published = 3\n', 'list'),
    ('[[published\n', 'TOML')])
def test_a_bad_settings_file_is_refused(tmp_path, text, words):
    write_settings(tmp_path, text)
    with pytest.raises(SettingsInvalid) as refused:
        load_settings(tmp_path)
    assert words in str(refused.value)


def test_a_symlinked_settings_file_is_refused(tmp_path):
    real = tmp_path / 'elsewhere.toml'
    real.write_text(published())
    (tmp_path / 'crossings.toml').symlink_to(real)
    with pytest.raises(SettingsInvalid):
        load_settings(tmp_path)


def test_an_edit_is_picked_up_without_a_restart(tmp_path):
    write_settings(tmp_path, published(), mtime=1_000_000_000_000_000_000)
    assert load_settings(tmp_path)['published'][0]['publisher'] == 'rio-grande'
    write_settings(tmp_path, published(publisher='the-house'), mtime=1_000_000_001_000_000_000)
    assert load_settings(tmp_path)['published'][0]['publisher'] == 'the-house'
    write_settings(tmp_path, 'station = 1\n', mtime=1_000_000_002_000_000_000)
    with pytest.raises(SettingsInvalid):
        load_settings(tmp_path)


def test_ships_resolve_to_users_of_kind_ship_only(tmp_path):
    """B2: both tables name a ship by username, resolved per request to a users.id of kind `ship`. A person's username
    resolves to nothing, so it publishes nothing and hosts nothing."""
    store, alice, _ = station(tmp_path / 'a', 'alice', Clock())
    rio = lesson_ship(store, alice, 'rio-grande')
    bob = store.create_user('bob', 'Bob', 'a-long-password', is_admin=False)['id']
    write_settings(store.data_dir, published() + published(ship='bob', publisher='bobs')
                   + f'[[hosted]]\nship = "rio-grande"\ninstance_id = "{INSTANCE}"\n'
                   + '[[hosted]]\nship = "bob"\ninstance_id = "00000000-0000-4000-8000-000000000000"\n')
    settings = load_settings(store.data_dir)
    assert published_house(store, settings, rio['id'])['publisher'] == 'rio-grande'
    assert published_house(store, settings, bob) is None
    assert published_house(store, settings, 'nobody') is None
    assert hosted_store(store, settings, rio['id'], INSTANCE)
    assert not hosted_store(store, settings, rio['id'], '00000000-0000-4000-8000-000000000000')
    assert not hosted_store(store, settings, bob, '00000000-0000-4000-8000-000000000000')


# Task 3: the checks, in order. A fake daemon socket records every connection, so "no Engram store, policy, ledger or
# sidecar was opened" is "the daemon socket saw nothing" (the peer opens nothing else of Engram's).

import json
import socketserver
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass

from superyak_peer import crossing
from superyak_peer.common import Problem
from superyak_peer.identity import PeerIdentity, canonical

from conftest import paired


def recall_result(frame, disclosure='d' * 32, candidates=()):
    return {'protocolVersion': '0.1', 'kind': 'recall_result', 'turnId': str(uuid.uuid4()),
            'queryDigest': {'algorithm': 'sha256', 'value': '0' * 64}, 'context': frame['context'],
            'candidates': list(candidates), 'decision': {'effect': 'allow', 'ruleId': 'r1', 'code': None},
            'disclosureId': disclosure}


def read_result(frame, disclosure='e' * 32, content='a shared memory'):
    return {'protocolVersion': '0.1', 'kind': 'read_result', 'disclosureId': disclosure,
            'items': [{'memoryId': m, 'content': content, 'audiences': ['commons'],
                       'decision': {'effect': 'allow', 'ruleId': 'r1', 'code': None}} for m in frame['memoryIds']]}


class FakeDaemon:
    """A lighthouse daemon socket: one line in, one line out, per connection. It records each connection and frame, and
    answers with `self.answer(frame)` (bytes are sent as they are). `hold`, when set, is waited on before answering."""

    def __init__(self, folder):
        self.path = folder / 'd.sock'
        self.frames, self.connections, self.hold, self.lock = [], 0, None, threading.Lock()
        self.answer = lambda frame: recall_result(frame) if frame['kind'] == 'recall' else read_result(frame)
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                with daemon.lock:
                    daemon.connections += 1
                line = self.rfile.readline(2 * 1024 * 1024)
                frame = json.loads(line)
                with daemon.lock:
                    daemon.frames.append(frame)
                if daemon.hold is not None:
                    daemon.hold.wait(10)
                reply = daemon.answer(frame)
                if reply is None:
                    return
                self.wfile.write(reply if isinstance(reply, bytes) else canonical(reply) + b'\n')

        self.server = socketserver.ThreadingUnixStreamServer(str(self.path), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        if self.hold is not None:
            self.hold.set()
        self.server.shutdown()
        self.server.server_close()


@dataclass
class World:
    clock: object
    a: tuple          # the publisher's push peer (the Pi): store, owner, Federation
    m: tuple          # the asking pull peer (Tardis)
    rio: dict         # the publishing ship on `a`
    tardis: dict      # the receiving ship on `m`
    contact: str      # `m`'s tardis ship as a contact on `a`
    daemon: FakeDaemon
    sidecar: Path
    folder: Path


@pytest.fixture
def world(tmp_path):
    folder = Path(tempfile.mkdtemp(prefix='x'))  # a Unix socket path must stay under 108 bytes
    clock = Clock()
    a = station(tmp_path / 'a', 'alice', clock)
    m = station(tmp_path / 'm', 'mo', clock, mode='pull')
    rio = lesson_ship(a[0], a[1], 'rio-grande')
    tardis = lesson_ship(m[0], m[1], 'tardis')
    contact = paired(a[2], a[1], m[2].card(tardis['id']))['id']
    paired(m[2], m[1], a[2].card(rio['id']))
    daemon = FakeDaemon(folder)
    sidecar = folder / 'sidecar.db'
    sidecar.write_bytes(b'the sidecar fixture')
    write_settings(a[0].data_dir, published(socket=str(daemon.path), sidecar=str(sidecar)))
    yield World(clock, a, m, rio, tardis, contact, daemon, sidecar, folder)
    daemon.close()
    shutil.rmtree(folder, ignore_errors=True)


def frame_of(kind='recall', **change):
    base = {'protocolVersion': '0.1', 'kind': kind, 'receiver': 'anything', 'publisher': 'anything',
            'context': {'id': 'work/lighthouse', 'path': ['work', 'lighthouse']}, 'purpose': 'session-recall'}
    if kind == 'recall':
        base.update(audience='self', query='what did the lighthouse decide', k=20, at='2026-11-03T12:00:00+00:00')
    else:
        base.update(turnId=str(uuid.uuid4()), memoryIds=['m1', 'm2'])
    base.update(change)
    return base


def request(w, frame=None, *, signer=None, **change):
    signer = signer or w.m[2].identity
    value = {'version': 1, 'kind': 'crossing', 'origin': signer.peer_id, 'destination': w.a[2].identity.peer_id,
             'receiver_instance': INSTANCE, 'receiver_ship': w.tardis['id'], 'publisher_ship': w.rio['id'],
             'frame': frame or frame_of(), 'deadline_ms': 2000, 'nonce': uuid.uuid4().hex, 'at': int(w.clock())}
    value.update(change)
    return signer.sign_crossing(value)


def serve(w, value):
    return w.a[2].serve_crossing(canonical(value) if isinstance(value, dict) else value)


def refused(w, value, status, message):
    with pytest.raises(Problem) as answer:
        serve(w, value)
    assert (answer.value.status, answer.value.message) == (status, message)


def nonce_kept(w, value):
    with w.a[0].transaction() as db:
        return db.execute('SELECT at FROM pull_nonces WHERE origin=? AND nonce=?',
                          (value['origin'], value['nonce'])).fetchone()


def daemon_saw_nothing(w):
    assert (w.daemon.connections, w.daemon.frames) == (0, [])


def hold_contact(w):
    with w.a[0].transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES(?,?)', (w.contact, w.clock()))


def test_a_body_off_the_shape_is_400(world):
    refused(world, b'{"not": "a crossing"}', 400, 'Invalid crossing request')
    refused(world, b'not json', 400, 'Invalid envelope JSON')
    envelope = {'session_id': 's', 'outbox_id': 'o', 'seq': 1, 'op_id': 'op', 'client_time': 1, 'deadline_ms': 2000,
                'kind': 'tool', 'tool': 'remember', 'arguments': {}}
    refused(world, envelope, 400, 'Invalid crossing request')  # spec section 4, "Two routes"
    daemon_saw_nothing(world)


def test_a_wrong_destination_is_403_and_keeps_no_nonce(world):
    value = request(world, destination='c' * 64)
    refused(world, value, 403, 'Not addressed to this peer')
    assert nonce_kept(world, value) is None
    daemon_saw_nothing(world)


def test_an_unpaired_origin_is_403_and_leaves_the_sidecar_untouched(world, tmp_path):
    stranger = PeerIdentity.load_or_create(tmp_path / 'stranger')
    before = (world.sidecar.read_bytes(), world.sidecar.stat().st_mtime_ns)
    refused(world, request(world, signer=stranger), 403, 'Unknown or unpaired peer')
    world.a[2].unpair(world.a[1], world.contact)
    refused(world, request(world), 403, 'Unknown or unpaired peer')
    assert (world.sidecar.read_bytes(), world.sidecar.stat().st_mtime_ns) == before
    daemon_saw_nothing(world)


def test_a_bad_signature_is_403(world):
    value = request(world)
    refused(world, {**value, 'deadline_ms': 3000}, 403, 'Peer authentication failed')
    refused(world, {**value, 'receiver_ship': world.m[1]}, 403, 'Peer authentication failed')
    daemon_saw_nothing(world)


def test_a_stale_at_is_403(world):
    refused(world, request(world, at=int(world.clock()) - 301), 403, 'Clocks differ by more than 5 minutes')
    refused(world, request(world, at=int(world.clock()) + 301), 403, 'Clocks differ by more than 5 minutes')
    daemon_saw_nothing(world)


def test_a_replayed_nonce_is_409_and_crossing_nonces_share_pull_nonces(world):
    """P3: a crossing's nonce is a row of pull_nonces, kept by the request's `at`, so the restore floor and the carry
    cover it. A replay is 409 before the contact is read."""
    hold_contact(world)
    value = request(world)
    refused(world, value, 403, 'Receiving ship is not a current contact')
    assert nonce_kept(world, value)[0] == value['at']
    refused(world, value, 409, 'Replay')
    daemon_saw_nothing(world)


def test_an_at_at_the_restore_floor_is_409(world):
    restored = int(world.clock())
    with world.a[0].transaction() as db:
        db.execute("INSERT OR REPLACE INTO system_meta VALUES('restore_reconcile', ?)",
                   (json.dumps({'at': float(restored), 'replaced': True, 'path': '/x'}),))
    refused(world, request(world, at=restored), 409, 'Replay')
    refused(world, request(world, at=restored + 300), 409, 'Replay')  # within the clock check: now + 300
    daemon_saw_nothing(world)


def test_a_held_receiving_ship_is_403_and_leaves_the_sidecar_untouched(world):
    before = (world.sidecar.read_bytes(), world.sidecar.stat().st_mtime_ns)
    hold_contact(world)
    refused(world, request(world), 403, 'Receiving ship is not a current contact')
    assert (world.sidecar.read_bytes(), world.sidecar.stat().st_mtime_ns) == before
    daemon_saw_nothing(world)


def test_a_contact_whose_confirmation_no_longer_matches_its_card_is_403(world):
    with world.a[0].transaction() as db:
        db.execute('UPDATE pairing_confirmations SET code=? WHERE contact_id=?', ('0' * 32, world.contact))
    refused(world, request(world), 403, 'Receiving ship is not a current contact')
    daemon_saw_nothing(world)


def test_a_ship_that_is_no_contact_of_the_origin_is_403(world):
    refused(world, request(world, receiver_ship=world.m[1]), 403, 'Receiving ship is not a current contact')
    daemon_saw_nothing(world)


def test_a_contact_confirmed_only_by_an_owner_trust_is_403(world):
    """Spec 2.2 asks for a current *typed* confirmation, by code_current (the rule connections() uses). A contact an
    owner trust confirmed, with no typed code, doesn't pass check 5: a decision for the partners to confirm."""
    with world.a[0].transaction() as db:
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (world.contact,))
        db.execute('INSERT INTO trust_confirmations VALUES(?,?,?,?,?,?,?,?)',
                   ('t1', world.contact, 'g1', '{}', world.rio['id'], world.clock(), '1970-01-12', 1))
    refused(world, request(world), 403, 'Receiving ship is not a current contact')
    daemon_saw_nothing(world)


def test_an_unmapped_publisher_ship_is_404(world):
    refused(world, request(world, publisher_ship=world.a[1]), 404, 'No published house for that ship')
    refused(world, request(world, publisher_ship='z' * 32), 404, 'No published house for that ship')
    daemon_saw_nothing(world)


def test_a_bad_settings_file_refuses_every_crossing_with_503(world):
    write_settings(world.a[0].data_dir, 'station = 1\n', mtime=2_000_000_000_000_000_000)
    refused(world, request(world), 503, 'Crossings are not configured on this peer')
    daemon_saw_nothing(world)


def test_a_pull_origin_card_passes_every_check(world, monkeypatch):
    """S3: a crossing isn't v2-only (serve_pull's check). Tardis's card is a v2 pull card, and its request reaches the
    processing step with the house its publisher_ship maps to."""
    reached = []
    monkeypatch.setattr(crossing, '_answer', lambda federation, value, house: reached.append(house) or {'ok': 1})
    assert serve(world, request(world)) == {'ok': 1}
    assert [h['publisher'] for h in reached] == ['rio-grande']


def test_the_signature_is_checked_before_the_contact(world):
    hold_contact(world)
    refused(world, {**request(world), 'deadline_ms': 3000}, 403, 'Peer authentication failed')


def test_a_wrong_destination_replay_is_403_not_409(world):
    hold_contact(world)
    first = request(world)
    refused(world, first, 403, 'Receiving ship is not a current contact')
    again = request(world, nonce=first['nonce'], destination='c' * 64)
    refused(world, again, 403, 'Not addressed to this peer')
