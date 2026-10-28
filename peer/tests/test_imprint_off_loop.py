"""The imprint routes' blocking work runs off the event loop (section 2 review S3): the confirm's scrypt and store
transactions in a sign-in lane, and the request's, manifest's and each part's hashing, re-reads, writes and fsyncs in a
worker, as /api/login and /api/invitations/redeem do."""
import asyncio

from fastapi.testclient import TestClient

from superyak_peer import auth, imprints
from superyak_peer.identity import canonical
from superyak_peer.imprints import PART_SIZE as PART_BYTES
from imprint_support import request_doc, station
from test_imprint_confirm import SAM_PASSWORD, confirm, row
from test_imprint_upload import allowed_with_manifest, manifest_for_doc, put_manifest, put_part, requested_with_package


def where():
    try:
        asyncio.get_running_loop()
        return 'loop'
    except RuntimeError:
        return 'worker'


def record(monkeypatch, owner, name, seen):
    """Wraps owner.name so each call notes whether its thread runs an event loop."""
    real = getattr(owner, name)

    def recording(*args, **kwargs):
        seen.append((name, where()))
        return real(*args, **kwargs)
    monkeypatch.setattr(owner, name, recording)


def watch_store(monkeypatch, st, seen, *names):
    for name in ('session', 'ship_for_key', 'transaction', *names):
        record(monkeypatch, st.store, name, seen)


def on_the_loop(seen):
    return [name for name, place in seen if place == 'loop']


def test_the_request_runs_off_the_event_loop(tmp_path, monkeypatch):
    st, seen = station(tmp_path), []
    watch_store(monkeypatch, st, seen, 'create_imprint_request')
    assert st.voyager.post('/api/imprints', content=canonical(request_doc())).status_code == 201
    assert ('create_imprint_request', 'worker') in seen and on_the_loop(seen) == [], seen


def test_the_confirm_runs_its_scrypt_and_transactions_off_the_event_loop(tmp_path, monkeypatch):
    st = station(tmp_path)
    made = st.voyager.post('/api/imprints', content=canonical(request_doc())).json()
    seen = []
    watch_store(monkeypatch, st, seen, 'confirm_imprint', 'check_password_attempt')
    record(monkeypatch, auth, 'password_hash', seen)
    assert confirm(st.sam, made, password='wrong-wrong-wrong').status_code == 401
    assert confirm(st.sam, made).status_code == 200
    assert {name for name, _ in seen} >= {'session', 'transaction', 'confirm_imprint', 'check_password_attempt',
                                          'password_hash'}
    assert on_the_loop(seen) == [], seen


def test_the_confirm_goes_through_a_sign_in_lane(tmp_path):
    """A full tailnet lane answers the confirm 429 without hashing or counting, as it answers a tailnet sign-in."""
    st = station(tmp_path)
    made = st.voyager.post('/api/imprints', content=canonical(request_doc())).json()
    lane = st.app.state.sign_in_lanes.tailnet
    with st.store.transaction() as db:
        before = sorted(tuple(r) for r in db.execute('SELECT * FROM login_attempts'))
    lane.inside = lane.size + lane.queue
    try:
        full = confirm(st.sam, made, password='wrong-wrong-wrong')
    finally:
        lane.inside = 0
    assert (full.status_code, full.json()) == (429, {'error': 'Too many sign-ins at once; try again shortly'})
    with st.store.transaction() as db:
        assert sorted(tuple(r) for r in db.execute('SELECT * FROM login_attempts')) == before
    assert row(st, made['id'])['status'] == 'requested'
    assert confirm(st.sam, made).status_code == 200


def test_the_manifest_runs_off_the_event_loop(tmp_path, monkeypatch):
    st = station(tmp_path)
    made, data = requested_with_package(st)
    assert confirm(st.sam, made, password=SAM_PASSWORD).status_code == 200
    seen = []
    watch_store(monkeypatch, st, seen, 'put_imprint_manifest')
    record(monkeypatch, imprints, '_write_file', seen)
    assert put_manifest(st, made, manifest_for_doc(st, made, data)).status_code == 200
    assert ('_write_file', 'worker') in seen and on_the_loop(seen) == [], seen


def test_each_part_hashes_rereads_and_fsyncs_off_the_event_loop(tmp_path, monkeypatch):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES + 5)
    seen = []
    watch_store(monkeypatch, st, seen, 'put_imprint_part', '_staged_manifest')
    for name in ('_write_file', '_held', '_folder_lock'):
        record(monkeypatch, imprints, name, seen)
    real_sha = imprints.hashlib.sha256

    class Hashlib:                                  # the part's SHA-256, and the held part's re-read and hash
        @staticmethod
        def sha256(*args):
            seen.append(('sha256', where()))
            return real_sha(*args)
    monkeypatch.setattr(imprints, 'hashlib', Hashlib)
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200          # held: re-read and hashed, not written
    assert put_part(st, made, 1, data[PART_BYTES:]).status_code == 200
    names = [name for name, _ in seen]
    assert names.count('_write_file') == 2 and names.count('sha256') >= 4 and 'put_imprint_part' in names
    assert on_the_loop(seen) == [], seen


def test_complete_runs_off_the_event_loop(tmp_path, monkeypatch):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES + 5)
    assert put_part(st, made, 0, data[:PART_BYTES]).status_code == 200
    assert put_part(st, made, 1, data[PART_BYTES:]).status_code == 200
    seen = []
    watch_store(monkeypatch, st, seen, 'complete_imprint')
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()['status'] == 'received'
    assert ('complete_imprint', 'worker') in seen and on_the_loop(seen) == [], seen


def test_shorten_runs_off_the_event_loop(tmp_path, monkeypatch):
    """Not in the review's list, but the same kind of route: async, with a signed receipt and file replaces."""
    from test_imprint_withdrawal import at_status, current_end, shorten
    st = at_status(tmp_path, 'admitted')
    seen = []
    watch_store(monkeypatch, st, seen, 'shorten_imprint')
    assert shorten(st, 'owner', current_end(st) - 100).status_code == 200
    assert shorten(st, 'ship', current_end(st) - 100).status_code == 200
    assert ('shorten_imprint', 'worker') in seen and on_the_loop(seen) == [], seen
