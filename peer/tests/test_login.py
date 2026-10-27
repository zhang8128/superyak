"""The login (docs/superpowers/specs/2026-10-27-public-route-design.md section 3): per-(username, source) and
per-source holds, a public-only username hold, reserve first, and recovery from the tailnet. Requests go through
uvicorn's ProxyHeadersMiddleware as `serve` configures it: a public one carries X-Forwarded-For, a tailnet one comes
from 127.0.0.1 (or forwards a tailnet address)."""
import json
import threading
from types import SimpleNamespace
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import pytest
from superyak_peer import auth
from superyak_peer.app import TRUSTED_PROXY, create_app

ORIGIN = 'https://testserver'
WRONG = 'not-the-password'
INVALID = (401, {'error': 'Invalid username or password'})
HELD = (429, {'error': 'Too many attempts; try again later'})


@pytest.fixture
def station(tmp_path):
    clock = [1000000.0]
    app = create_app(tmp_path / 'peer', clock=lambda: clock[0], allowed_origins=[ORIGIN])
    for name in ('patient', 'doctor'):
        app.state.store.create_user(name, name.title(), 'long-password-' + name)
    return SimpleNamespace(app=app, store=app.state.store, clock=clock)


def browser(station):
    """One browser: its own cookie jar, behind the proxy serve trusts."""
    return TestClient(ProxyHeadersMiddleware(station.app, trusted_hosts=TRUSTED_PROXY), base_url=ORIGIN, headers={'origin': ORIGIN})


def sign_in(station, username, password=None, source=None, client=None):
    """source: the address the proxy forwards (None is a tailnet request from 127.0.0.1)."""
    client = client or browser(station)
    response = client.post('/api/login', json={'username': username, 'password': password or f'long-password-{username}'},
                           headers={'x-forwarded-for': source} if source else {})
    return response.status_code, response.json()


def counters(station):
    with station.store.transaction() as db:
        return {tuple(json.loads(r['key'])): r['count'] for r in db.execute('SELECT key,count FROM login_attempts')}


def test_eight_public_failures_from_one_source_hold_that_pair_only(station):
    """Hold 1: someone guessing from elsewhere no longer locks the account."""
    for _ in range(8):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID
    assert sign_in(station, 'patient', source='203.0.113.5') == HELD  # the right password, held
    assert sign_in(station, 'patient', source='203.0.113.6')[0] == 200
    assert sign_in(station, 'doctor', source='203.0.113.5')[0] == 200
    assert sign_in(station, 'patient')[0] == 200  # tailnet
    station.clock[0] += 301
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200


def test_forty_failures_from_one_source_hold_that_source(station):
    """Hold 2, as today's source: limit: rotating usernames from one source doesn't buy more guesses."""
    for name in ('a1', 'a2', 'a3', 'a4', 'a5'):
        for _ in range(8):
            assert sign_in(station, name, WRONG, '203.0.113.5') == INVALID
    assert sign_in(station, 'doctor', source='203.0.113.5') == HELD
    assert sign_in(station, 'doctor', source='203.0.113.6')[0] == 200


def test_thirty_public_failures_hold_the_username_for_public_sign_ins_and_a_tailnet_sign_in_clears_it(station):
    """Hold 3: 30 public failures on one username in an hour; the tailnet is never held by it, and its success is
    the recovery."""
    for n in range(1, 30):
        assert sign_in(station, 'patient', WRONG, f'203.0.113.{n}') == INVALID
    assert sign_in(station, 'patient', source='198.51.100.1')[0] == 200  # 29 failures, and success gives one back
    assert sign_in(station, 'patient', WRONG, '203.0.113.30') == INVALID  # the 30th public failure
    assert sign_in(station, 'patient', source='198.51.100.2') == HELD
    assert sign_in(station, 'doctor', source='198.51.100.2')[0] == 200  # another username isn't held
    assert sign_in(station, 'patient')[0] == 200  # tailnet: never held by hold 3, and it clears it
    assert ('user', 'patient') not in counters(station)
    assert sign_in(station, 'patient', source='198.51.100.2')[0] == 200


def test_tailnet_failures_never_count_toward_the_username_hold(station):
    for n in range(1, 41):
        assert sign_in(station, 'patient', WRONG, f'100.70.0.{n}') == INVALID
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station)[('user', 'patient')] == 0  # only this public sign-in's reservation, given back


def test_the_username_hold_lasts_an_hour(station):
    for n in range(1, 31):
        assert sign_in(station, 'patient', WRONG, f'203.0.113.{n}') == INVALID
    station.clock[0] += 3599
    assert sign_in(station, 'patient', source='198.51.100.1') == HELD
    station.clock[0] += 2
    assert sign_in(station, 'patient', source='198.51.100.1')[0] == 200


def test_public_ipv6_sources_share_their_64_and_tailnet_ipv6_addresses_do_not(station):
    for host in ('2001:db8:1:2::1', '2001:db8:1:2::2'):
        for _ in range(4):
            assert sign_in(station, 'patient', WRONG, host) == INVALID
    assert sign_in(station, 'patient', source='2001:db8:1:2:aaaa::3') == HELD
    assert sign_in(station, 'patient', source='2001:db8:1:3::1')[0] == 200
    for _ in range(8):
        assert sign_in(station, 'doctor', WRONG, 'fd7a:115c:a1e0::1') == INVALID
    assert sign_in(station, 'doctor', source='fd7a:115c:a1e0::1') == HELD
    assert sign_in(station, 'doctor', source='fd7a:115c:a1e0::2')[0] == 200


@pytest.mark.parametrize('host, public, bucket', [
    ('203.0.113.5', True, '203.0.113.5'), ('::ffff:203.0.113.5', True, '203.0.113.5'),
    ('2001:db8:1:2:3:4:5:6', True, '2001:db8:1:2::/64'), ('2001:db8:1:2:3:4:5:6', False, '2001:db8:1:2:3:4:5:6'),
    ('fd7a:115c:a1e0::1', False, 'fd7a:115c:a1e0::1'), ('100.70.0.1', False, '100.70.0.1'), ('::1', False, '::1'),
    ('::ffff:100.70.0.1', False, '100.70.0.1'), ('testclient', True, 'testclient'), ('unknown', True, 'unknown')])
def test_the_bucket_a_source_counts_in(host, public, bucket):
    assert auth.login_source(host, public) == bucket


def test_counter_keys_are_json_arrays(station):
    assert sign_in(station, 'odd:"name"', WRONG, '203.0.113.5') == INVALID
    assert counters(station) == {('user-source', '203.0.113.5', 'odd:"name"'): 1, ('source', '203.0.113.5'): 1,
                                 ('user', 'odd:"name"'): 1}


def test_the_reservation_is_visible_while_hashing(station, monkeypatch):
    """Reserve first (S2): the counters are written before the hash, so concurrent guesses can't all pass a limit.
    Concurrent requests share one event loop: one `with TestClient`."""
    hashing, release = threading.Event(), threading.Event()
    real = auth.password_hash

    def paused(password, salt):
        hashing.set()
        assert release.wait(10)
        return real(password, salt)
    monkeypatch.setattr(auth, 'password_hash', paused)
    with browser(station) as client:
        answers = []
        guess = threading.Thread(target=lambda: answers.append(sign_in(station, 'patient', WRONG, '203.0.113.5', client)))
        guess.start()
        assert hashing.wait(10)
        assert counters(station) == {('user-source', '203.0.113.5', 'patient'): 1, ('source', '203.0.113.5'): 1, ('user', 'patient'): 1}
        release.set()
        guess.join(10)
    assert answers == [INVALID]
    assert counters(station) == {('user-source', '203.0.113.5', 'patient'): 1, ('source', '203.0.113.5'): 1, ('user', 'patient'): 1}


def test_success_gives_back_the_reservation(station):
    for _ in range(7):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station) == {('source', '203.0.113.5'): 7, ('user', 'patient'): 7}  # the pair's row is gone


def test_the_give_back_stays_in_its_window_and_never_goes_below_zero(station, monkeypatch):
    """A window that ended while the hash ran is not touched: a new row for the next window keeps its count."""
    real = auth.password_hash

    def slow(password, salt):
        station.clock[0] += 301  # the source window ends while this attempt hashes
        with station.store.transaction() as db:
            db.execute('UPDATE login_attempts SET reset=?, count=5 WHERE key=?', (station.clock[0] + 300, json.dumps(['source', '203.0.113.5'])))
        return real(password, salt)
    monkeypatch.setattr(auth, 'password_hash', slow)
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station)[('source', '203.0.113.5')] == 5


def test_an_activation_between_the_hash_and_the_reread_gives_401(station, monkeypatch, tmp_path):
    """Step 3 re-reads the user: an activation that changes the salt and hash while the old password hashes wins."""
    store = station.store
    record_path = tmp_path / 'activation.json'
    store.bootstrap_super_admin('stanley', 'Stanley', record_path)
    record = json.loads(record_path.read_text())
    salt = b'\1' * 16
    with store.transaction() as db:  # the pending account's placeholder password, made knowable for the test
        db.execute('UPDATE users SET salt=?, password_hash=?, activation_pending=0 WHERE username=?',
                   (salt, auth.password_hash('placeholder-password', salt), 'stanley'))
    real, activated = auth.password_hash, []

    def activate_meanwhile(password, salt):
        digest = real(password, salt)
        if password == 'placeholder-password' and not activated:
            activated.append(True)
            with store.transaction() as db:
                db.execute('UPDATE users SET activation_pending=1 WHERE username=?', ('stanley',))
            store.redeem(record['token'], 'stanley', 'Stanley', 'stanley-chosen-password')
        return digest
    monkeypatch.setattr(auth, 'password_hash', activate_meanwhile)
    assert sign_in(station, 'stanley', 'placeholder-password', '203.0.113.5') == INVALID and activated
    assert sign_in(station, 'stanley', 'stanley-chosen-password', '203.0.113.5')[0] == 200


def test_expired_rows_are_deleted(station):
    now = station.clock[0]
    with station.store.transaction() as db:
        db.executemany('INSERT INTO login_attempts VALUES(?,?,?)', [
            (json.dumps(['source', '198.51.100.9']), 3, now - 1), ('user:patient', 8, now), ('source:198.51.100.9', 40, now - 50),
            (json.dumps(['user', 'doctor']), 2, now + 100)])
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station) == {('user', 'doctor'): 2, ('source', '203.0.113.5'): 0, ('user', 'patient'): 0}


def test_held_attempts_neither_hash_nor_count(station, monkeypatch):
    for _ in range(8):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID
    before, hashed = counters(station), []
    monkeypatch.setattr(auth, 'password_hash', lambda password, salt: hashed.append(1) or b'\0' * 32)
    assert sign_in(station, 'patient', WRONG, '203.0.113.5') == HELD
    assert sign_in(station, 'patient', source='203.0.113.5') == HELD
    assert hashed == [] and counters(station) == before


def test_rows_from_before_the_upgrade_hold_nobody(station):
    """Today's user: and source: rows go inert at deploy: the new keys are different."""
    now = station.clock[0]
    with station.store.transaction() as db:
        db.executemany('INSERT INTO login_attempts VALUES(?,?,?)', [('user:patient', 8, now + 300), ('source:203.0.113.5', 40, now + 300)])
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert sign_in(station, 'patient')[0] == 200


def test_unknown_and_known_names_answer_the_same_and_both_hash_once(station, monkeypatch):
    hashed, real = [], auth.password_hash
    monkeypatch.setattr(auth, 'password_hash', lambda password, salt: hashed.append(salt) or real(password, salt))
    assert sign_in(station, 'patient', WRONG, '203.0.113.5') == sign_in(station, 'nobody', WRONG, '203.0.113.5') == INVALID
    assert len(hashed) == 2 and hashed[1] == b'\0' * 16  # the dummy hash for the unknown name
    for _ in range(7):
        assert sign_in(station, 'nobody', WRONG, '203.0.113.5') == INVALID
    assert sign_in(station, 'nobody', WRONG, '203.0.113.5') == HELD  # unknown names are held alike
