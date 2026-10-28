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
from superyak_peer.common import Problem

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


def sign_in(station, username, password=None, source=None, client=None, headers=None):
    """source: the address the proxy forwards (None is a tailnet request from 127.0.0.1); headers: any others to send."""
    client = client or browser(station)
    response = client.post('/api/login', json={'username': username, 'password': password or f'long-password-{username}'},
                           headers={**({'x-forwarded-for': source} if source else {}), **(headers or {})})
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
    assert counters(station) == {('user-source', 'public', '203.0.113.5', 'odd:"name"'): 1, ('source', 'public', '203.0.113.5'): 1,
                                 ('user', 'odd:"name"'): 1}


def test_a_public_and_a_tailnet_failure_never_share_a_counter(station):
    """Section 2 review should-fix 4: a Funnel request from a tailnet node is public, yet its source is the address a
    tailnet sign-in from that node counts in. The keys name the request's class, so neither holds the other."""
    funnel = {'tailscale-funnel-request': '?1'}
    for _ in range(8):
        assert sign_in(station, 'patient', WRONG, '100.70.0.1', headers=funnel) == INVALID
    assert sign_in(station, 'patient', source='100.70.0.1', headers=funnel) == HELD
    assert sign_in(station, 'patient', source='100.70.0.1')[0] == 200  # tailnet, from the same node
    for _ in range(8):
        assert sign_in(station, 'doctor', WRONG, '100.70.0.1') == INVALID
    assert sign_in(station, 'doctor', source='100.70.0.1') == HELD
    assert sign_in(station, 'doctor', source='100.70.0.1', headers=funnel)[0] == 200
    assert counters(station) == {('user-source', 'public', '100.70.0.1', 'patient'): 8, ('source', 'public', '100.70.0.1'): 8,
                                 ('user-source', 'tailnet', '100.70.0.1', 'doctor'): 8, ('source', 'tailnet', '100.70.0.1'): 8,
                                 ('user', 'doctor'): 0}


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
        assert counters(station) == {('user-source', 'public', '203.0.113.5', 'patient'): 1, ('source', 'public', '203.0.113.5'): 1, ('user', 'patient'): 1}
        release.set()
        guess.join(10)
    assert answers == [INVALID]
    assert counters(station) == {('user-source', 'public', '203.0.113.5', 'patient'): 1, ('source', 'public', '203.0.113.5'): 1, ('user', 'patient'): 1}


def test_success_gives_back_the_reservation(station):
    for _ in range(7):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station) == {('source', 'public', '203.0.113.5'): 7, ('user', 'patient'): 7}  # the pair's row is gone


def test_the_give_back_stays_in_its_window_and_never_goes_below_zero(station, monkeypatch):
    """A window that ended while the hash ran is not touched: a new row for the next window keeps its count."""
    real = auth.password_hash

    def slow(password, salt):
        station.clock[0] += 301  # the source window ends while this attempt hashes
        with station.store.transaction() as db:
            db.execute('UPDATE login_attempts SET reset=?, count=5 WHERE key=?', (station.clock[0] + 300, json.dumps(['source', 'public', '203.0.113.5'])))
        return real(password, salt)
    monkeypatch.setattr(auth, 'password_hash', slow)
    assert sign_in(station, 'patient', source='203.0.113.5')[0] == 200
    assert counters(station)[('source', 'public', '203.0.113.5')] == 5


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
    assert counters(station) == {('user', 'doctor'): 2, ('source', 'public', '203.0.113.5'): 0, ('user', 'patient'): 0}


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


DEVICE = 'superyak_device'
DEVICE_LIFETIME = 180 * 86400


def devices(station, username='patient'):
    """username's device rows, oldest expiry first."""
    with station.store.transaction() as db:
        return [dict(r) for r in db.execute('SELECT login_devices.* FROM login_devices JOIN users ON users.id=login_devices.user_id '
                                            'WHERE users.username=? ORDER BY expires', (username,))]


def known_browser(station, username='patient', source='203.0.113.5'):
    client = browser(station)
    assert sign_in(station, username, source=source, client=client)[0] == 200
    assert client.cookies.get(DEVICE)
    return client


def test_a_sign_in_sets_a_random_device_cookie_stored_hashed_as_one_row(station):
    """The OWASP device cookie: 256 random bits, HttpOnly, Secure, SameSite=Strict, 180 days; stored hashed."""
    client = browser(station)
    response = client.post('/api/login', json={'username': 'patient', 'password': 'long-password-patient'}, headers={'x-forwarded-for': '203.0.113.5'})
    cookie = next(value for value in response.headers.get_list('set-cookie') if value.startswith(DEVICE + '='))
    attributes = {part.strip().split('=')[0].lower() for part in cookie.split(';')[1:]}
    assert {'httponly', 'secure', 'samesite', 'max-age'} <= attributes
    assert 'samesite=strict' in cookie.lower() and f'max-age={DEVICE_LIFETIME}' in cookie.lower()
    token = client.cookies.get(DEVICE)
    assert len(token) >= 43
    assert devices(station) == [{'token_hash': auth.token_hash(token), 'user_id': devices(station)[0]['user_id'],
                                 'expires': station.clock[0] + DEVICE_LIFETIME, 'failures': 0, 'failure_reset': 0, 'attempts': 0,
                                 'attempt_reset': 0}]
    assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID and len(devices(station)) == 1  # failures add none


def test_a_known_browser_is_exempt_from_holds_1_to_3_and_its_failures_hold_only_its_token(station):
    known, other, exempt = known_browser(station), known_browser(station, source='203.0.113.7'), known_browser(station)
    for n in range(1, 31):  # hold 3
        assert sign_in(station, 'patient', WRONG, f'198.51.100.{n}') == INVALID
    for name in ('patient', 'a2', 'a3', 'a4', 'a5'):  # holds 1 and 2 on the known browser's own source
        for _ in range(8):
            sign_in(station, name, WRONG, '203.0.113.5')
    assert sign_in(station, 'patient', source='203.0.113.5') == HELD  # a new browser there is held
    assert sign_in(station, 'patient', source='198.51.100.99') == HELD  # and anywhere public, by hold 3
    before = counters(station)
    assert sign_in(station, 'patient', source='203.0.113.5', client=exempt)[0] == 200
    for _ in range(8):  # its failures count against its own token, never toward holds 1-3
        assert sign_in(station, 'patient', WRONG, '203.0.113.5', client=known) == INVALID
    assert counters(station) == before
    assert sign_in(station, 'patient', source='203.0.113.5', client=known) == HELD
    assert sign_in(station, 'patient', source='203.0.113.7', client=other)[0] == 200  # only that token is held
    station.clock[0] += 301
    assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200


def test_a_known_browsers_success_resets_its_tokens_failures(station):
    known = known_browser(station)
    for _ in range(7):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5', client=known) == INVALID
    assert devices(station)[0]['failures'] == 7
    assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200
    assert devices(station)[0]['failures'] == 0


def test_a_known_browser_signing_in_over_and_over_is_held_before_any_lane(station, monkeypatch):
    """Section 2 review should-fix 1: eight public sign-ins in five minutes, successes included, hold a known browser's
    token, so one browser signing in correctly over and over can't keep the known lane full. The pre-lane read
    refuses a held token with 429, so it enters no lane; another user's known browser still gets in. Tailnet sign-ins
    neither count nor are held by it."""
    known, doctors = known_browser(station), known_browser(station, 'doctor', '203.0.113.7')
    lanes, entered = station.app.state.sign_in_lanes, []
    for name in ('public', 'tailnet', 'known'):
        lane = getattr(lanes, name)

        async def run(call, *args, name=name, real=lane.run, **kwargs):
            entered.append(name)
            return await real(call, *args, **kwargs)
        monkeypatch.setattr(lane, 'run', run)
    for _ in range(8):
        assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200
    assert sign_in(station, 'patient', source='203.0.113.5', client=known) == HELD
    assert entered == ['known'] * 8  # the ninth entered no lane
    assert sign_in(station, 'doctor', source='203.0.113.7', client=doctors)[0] == 200 and entered[-1] == 'known'
    assert sign_in(station, 'patient', client=known)[0] == 200 and entered[-1] == 'tailnet'
    station.clock[0] += 301
    assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200


def test_store_login_enforces_the_attempts_hold_itself(station):
    """The pre-lane read can race, so Store.login holds the token in its own transaction too. Failures and successes
    count alike, and a success resets only the failures. The failure hold still holds a token on its own: eight
    tailnet failures, which the attempts count skips."""
    store, token = station.store, known_browser(station).cookies.get(DEVICE)
    for password in [WRONG] * 4 + ['long-password-patient'] * 4:
        try:
            store.login('patient', password, '203.0.113.5', device=token)
        except Problem as failed:
            assert failed.status == 401
    assert devices(station)[0]['failures'] == 0
    with pytest.raises(Problem) as held:
        store.login('patient', 'long-password-patient', '203.0.113.5', device=token)
    assert (held.value.status, held.value.message) == (HELD[0], HELD[1]['error'])
    tailnet = known_browser(station, source=None).cookies.get(DEVICE)
    for _ in range(8):
        with pytest.raises(Problem) as failed:
            store.login('patient', WRONG, '127.0.0.1', public=False, device=tailnet)
        assert failed.value.status == 401
    with pytest.raises(Problem) as held:
        store.login('patient', 'long-password-patient', '127.0.0.1', public=False, device=tailnet)
    assert held.value.status == 429


def test_a_cookie_for_another_user_an_expired_one_or_a_made_up_one_exempts_nothing(station):
    doctors = known_browser(station, 'doctor')
    expired = known_browser(station)
    with station.store.transaction() as db:
        db.execute('UPDATE login_devices SET expires=? WHERE token_hash=?', (station.clock[0] - 1, auth.token_hash(expired.cookies.get(DEVICE))))
    made_up = browser(station)
    made_up.cookies.set(DEVICE, 'made-up-device-token')
    for _ in range(8):
        assert sign_in(station, 'patient', WRONG, '203.0.113.5') == INVALID
    for client in (doctors, expired, made_up):
        assert sign_in(station, 'patient', source='203.0.113.5', client=client) == HELD
        assert sign_in(station, 'patient', WRONG, '203.0.113.6', client=client) == INVALID  # counted as anyone's
    assert counters(station)[('user-source', 'public', '203.0.113.6', 'patient')] == 3


def test_a_sign_in_with_a_valid_cookie_keeps_its_row_and_extends_it(station):
    known = known_browser(station)
    token, first = known.cookies.get(DEVICE), devices(station)
    station.clock[0] += 1000
    assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200
    assert known.cookies.get(DEVICE) == token
    assert devices(station) == [first[0] | {'expires': station.clock[0] + DEVICE_LIFETIME, 'attempts': 1,
                                            'attempt_reset': station.clock[0] + 300}]
    known_browser(station, source='203.0.113.8')
    assert len(devices(station)) == 2  # another browser, another row


def test_logout_keeps_the_device_cookie(station):
    known = known_browser(station)
    token = known.cookies.get(DEVICE)
    response = known.post('/api/logout', headers={'x-csrf-token': known.get('/api/me', headers={'x-forwarded-for': '203.0.113.5'}).json()['csrf_token'],
                                                  'x-forwarded-for': '203.0.113.5'})
    assert response.status_code == 200
    assert not [value for value in response.headers.get_list('set-cookie') if value.startswith(DEVICE + '=')]
    assert known.cookies.get(DEVICE) == token and len(devices(station)) == 1
    assert sign_in(station, 'patient', source='203.0.113.5', client=known)[0] == 200 and len(devices(station)) == 1


def test_at_most_20_device_rows_per_user_and_expired_rows_go(station):
    first = known_browser(station, source=None)
    with station.store.transaction() as db:
        doctor = db.execute("SELECT id FROM users WHERE username='doctor'").fetchone()[0]
        db.execute('INSERT INTO login_devices(token_hash,user_id,expires) VALUES(?,?,?)', ('stale', doctor, station.clock[0] - 1))
    for _ in range(20):
        station.clock[0] += 1
        known_browser(station, source=None)
    rows = devices(station)
    assert len(rows) == 20 and auth.token_hash(first.cookies.get(DEVICE)) not in {r['token_hash'] for r in rows}  # the oldest went
    assert devices(station, 'doctor') == []


def test_a_full_public_lane_refuses_without_hashing_or_counting_and_other_lanes_still_sign_in(station, monkeypatch):
    """Sign-in lanes (re-check must-fix 1): public sign-ins 2 at a time with 8 waiting; tailnet sign-ins and known
    browsers have lanes of their own, so a flood that fills the public lane locks neither out. Every request shares
    one event loop (one `with TestClient`)."""
    known = known_browser(station).cookies.get(DEVICE)
    real, entered, release, hashed = auth.password_hash, threading.Semaphore(0), threading.Event(), []

    def held_open(password, salt):
        hashed.append(password)
        if password == 'hold-the-lane':
            entered.release()
            assert release.wait(20)
        return real(password, salt)
    monkeypatch.setattr(auth, 'password_hash', held_open)
    lane = station.app.state.sign_in_lanes.public
    with browser(station) as client:
        answers = []

        def flood(n):
            answers.append(sign_in(station, 'patient', 'hold-the-lane', f'203.0.113.{n}', client))
        threads = [threading.Thread(target=flood, args=(n,)) for n in range(1, 11)]
        try:
            for thread in threads:
                thread.start()
            assert entered.acquire(timeout=10) and entered.acquire(timeout=10)  # 2 hashing
            for _ in range(200):
                if lane.inside == 10:
                    break
                threading.Event().wait(0.05)
            assert lane.inside == 10  # and 8 waiting: the lane is full
            before, hashes = counters(station), len(hashed)
            refused = client.post('/api/login', json={'username': 'doctor', 'password': 'long-password-doctor'},
                                  headers={'x-forwarded-for': '203.0.113.99'})
            assert (refused.status_code, refused.json()) == (429, {'error': 'Too many sign-ins at once; try again shortly'})
            assert len(hashed) == hashes and counters(station) == before  # neither hashed nor counted
            assert client.post('/api/login', json={'username': 'patient', 'password': 'long-password-patient'},
                               headers={'x-forwarded-for': '203.0.113.98', 'cookie': f'{DEVICE}={known}'}).status_code == 200
            assert client.post('/api/login', json={'username': 'doctor', 'password': 'long-password-doctor'}).status_code == 200  # tailnet
        finally:
            release.set()
            for thread in threads:
                thread.join(20)
    assert answers == [INVALID] * 10 and lane.inside == 0


def test_the_lanes_sizes(station):
    lanes = station.app.state.sign_in_lanes
    assert [(lane.size, lane.queue) for lane in (lanes.public, lanes.tailnet, lanes.known)] == [(2, 8), (1, 4), (1, 4)]
