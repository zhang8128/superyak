"""The confirm's password counts as /api/login counts it (R19; section 2 review S2): with the request's own `public` and
browser `device`, so a tailnet confirm counts as tailnet and a known browser counts on its device token."""
from fastapi.testclient import TestClient
import pytest

from superyak_peer.auth import attempts_key, token_hash
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.identity import canonical
from imprint_support import request_doc, station
from test_imprint_confirm import SAM_PASSWORD, row

ORIGIN = 'http://testserver'
HELD = (429, {'error': 'Too many attempts; try again later'})


def attempts(store):
    with store.transaction() as db:
        return sorted(tuple(r) for r in db.execute('SELECT key,count,reset FROM login_attempts'))


def opened(st):
    return st.voyager.post('/api/imprints', content=canonical(request_doc())).json()


def owner_from(st, host, *, base_url=ORIGIN, device=None):
    """Sam's signed-in browser (its session and CSRF token) from `host`, optionally with a known-device cookie."""
    cookies = {'superyak_session': st.sam.cookies.get('superyak_session')}
    if device is not None:
        cookies['superyak_device'] = device
    return TestClient(st.app, base_url=base_url, client=(host, 4000), cookies=cookies,
                      headers={'origin': base_url, 'x-csrf-token': st.sam.headers['x-csrf-token']})


def confirm_from(client, made, password=SAM_PASSWORD):
    return client.post(f"/api/imprints/{made['id']}/confirm",
                       json={'code': made['code'], 'attest': True, 'password': password})


def public_login_failures(st, n=30):
    """n public /api/login failures for sam, 8 or fewer from each of 4 sources, so only the user hold (30 an hour,
    public only) is reached."""
    for i in range(n):
        TestClient(st.app, base_url=ORIGIN, client=(f'198.51.100.{i // 8 + 1}', 4000),
                   headers={'origin': ORIGIN}).post('/api/login', json={'username': 'sam', 'password': 'wrong-wrong-wrong'})
    with st.store.transaction() as db:
        assert db.execute('SELECT count FROM login_attempts WHERE key=?', (attempts_key('user', 'sam'),)).fetchone()[0] == n


def test_public_failures_no_longer_hold_the_owners_tailnet_confirm(tmp_path):
    """The review's probe, now the other way: 30 public failures hold a public confirm (429) but not a tailnet one."""
    st = station(tmp_path)
    made = opened(st)
    public_login_failures(st)
    assert (lambda r: (r.status_code, r.json()))(confirm_from(owner_from(st, '203.0.113.50'), made)) == HELD
    confirmed = confirm_from(owner_from(st, '100.70.202.124'), made)
    assert confirmed.status_code == 200, confirmed.text
    assert row(st, made['id'])['status'] == 'allowed'


def test_a_tailnet_ipv6_confirm_counts_on_its_own_address_not_its_64(tmp_path):
    st = station(tmp_path)
    made = opened(st)
    here, neighbour = owner_from(st, 'fd7a:115c:a1e0::3'), owner_from(st, 'fd7a:115c:a1e0::4')
    assert [confirm_from(here, made, 'wrong-wrong-wrong').status_code for _ in range(8)] == [401] * 8
    assert confirm_from(here, made).status_code == 429                         # the pair is held
    assert confirm_from(neighbour, made).status_code == 200                    # the same /64, another tailnet node


def test_a_known_browser_confirm_counts_on_its_device_token(tmp_path):
    """Over the public route, a browser with a valid device cookie counts its failures on that token (8 in 5 minutes),
    not on the pair, source or user holds, and a right password resets them, as a sign-in from it does."""
    secure = 'https://testserver'                 # the device cookie is Secure, so the browser is on https
    st = station(tmp_path, allowed_origins=(ORIGIN, secure))
    browser = TestClient(st.app, base_url=secure, client=('203.0.113.60', 4000), headers={'origin': secure})
    signed = browser.post('/api/login', json={'username': 'sam', 'password': SAM_PASSWORD})
    browser.headers['x-csrf-token'] = signed.json()['csrf_token']
    device = browser.cookies.get('superyak_device')
    made, before = opened(st), attempts(st.store)

    def devices():
        with st.store.transaction() as db:
            return sorted(tuple(r) for r in db.execute('SELECT token_hash, user_id, expires FROM login_devices'))
    browsers = devices()

    def failures():
        with st.store.transaction() as db:
            return db.execute('SELECT failures FROM login_devices WHERE token_hash=?', (token_hash(device),)).fetchone()[0]
    assert [confirm_from(browser, made, 'wrong-wrong-wrong').status_code for _ in range(3)] == [401] * 3
    known, after = attempts_key('known', 'sam'), attempts(st.store)
    assert failures() == 3 and [r for r in after if r[0] != known] == before   # the device counted, no hold did
    assert [r[1] for r in after if r[0] == known] == [3]                        # and so did the account's known browsers
    ok = confirm_from(browser, made)
    assert ok.status_code == 200 and 'set-cookie' not in ok.headers and failures() == 0
    assert devices() == browsers                                               # no new token, no extended one


# ---- The confirm's counting is login's, step by step (section 2 review S6, the review's probe) ----------------------

SOURCES = ['203.0.113.9', '2001:db8::5', '127.0.0.1', 'fd7a:115c:a1e0::3']     # IPv4 and IPv6, public and tailnet
STEPS = ['wrong'] * 3 + ['right'] + ['wrong'] * 9 + ['right']                 # 14 steps; the pair holds at the 13th
BROWSER = 'a-known-browser-token'


def counters(store):
    """Every hold's counter, and the known browser's failures and public attempts (not its expiry, which only a
    sign-in extends; a sign-in's new browser token is not a counter, and the check makes none)."""
    with store.transaction() as db:
        return (sorted(tuple(r) for r in db.execute('SELECT key,count,reset FROM login_attempts')),
                [tuple(r) for r in db.execute('SELECT failures,failure_reset,attempts,attempt_reset FROM login_devices '
                                              'WHERE token_hash=?', (token_hash(BROWSER),))])


def outcome(call):
    try:
        return 'ok' if call() else 401
    except Problem as problem:
        return problem.status


def two_stores(tmp_path, device):
    clock = [1000.0]
    stores = [Store(tmp_path / name, clock=lambda: clock[0], signing=False) for name in ('login', 'check')]
    for store in stores:
        user = store.create_user('sam', 'Sam', SAM_PASSWORD)
        if device:
            with store.transaction() as db:
                db.execute('INSERT INTO login_devices(token_hash,user_id,expires) VALUES(?,?,?)',
                           (token_hash(BROWSER), user['id'], 10 ** 9))
    return clock, stores


@pytest.mark.parametrize('device', [False, True], ids=['no-browser', 'known-browser'])
@pytest.mark.parametrize('public', [True, False], ids=['public', 'tailnet'])
@pytest.mark.parametrize('source', SOURCES)
def test_check_password_attempt_counts_as_login_step_by_step(tmp_path, source, public, device):
    """After each of 14 steps, login and check_password_attempt answer alike and leave identical counters, holds on
    the same step; the check makes no session and no browser token."""
    clock, (signs, checks) = two_stores(tmp_path, device)
    token = BROWSER if device else None
    answers = []
    for n, word in enumerate(STEPS):
        password = SAM_PASSWORD if word == 'right' else 'wrong-wrong-wrong'
        login = outcome(lambda: signs.login('sam', password, source, public=public, device=token))
        check = outcome(lambda: checks.check_password_attempt('sam', password, source, public=public, device=token))
        assert login == check, (n, login, check)
        assert counters(signs) == counters(checks), (n, counters(signs), counters(checks))
        answers.append(check)
        clock[0] += 7
    if public and device:   # a known browser's public tries count on its token, 8 in 5 minutes, successes included
        assert answers == [401] * 3 + ['ok'] + [401] * 4 + [429] * 6
    else:
        assert answers == [401] * 3 + ['ok'] + [401] * 8 + [429, 429]
    with checks.transaction() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM login_devices').fetchone()[0] == (1 if device else 0)


@pytest.mark.parametrize('public', [True, False], ids=['public', 'tailnet'])
def test_an_unknown_name_counts_as_login_counts_it(tmp_path, public):
    clock, (signs, checks) = two_stores(tmp_path, False)
    with pytest.raises(Problem):
        signs.login('nobody', 'x' * 12, '203.0.113.1', public=public)
    assert checks.check_password_attempt('nobody', 'x' * 12, '203.0.113.1', public=public) is False
    assert counters(signs) == counters(checks)


@pytest.mark.parametrize('host', SOURCES)
def test_the_confirm_route_counts_as_the_login_route_step_by_step(tmp_path, host):
    """The same 14 steps through the routes from one client address: confirms on one station, sign-ins on another.
    Each answers with the same status and leaves the same counters, so the confirm route passes the request's own
    `public` as /api/login does."""
    confirms, logins = station(tmp_path / 'confirms'), station(tmp_path / 'logins')
    assert attempts(confirms.store) == attempts(logins.store)
    owner, made = owner_from(confirms, host), opened(confirms)
    statuses = []
    for n, word in enumerate(STEPS):
        password = SAM_PASSWORD if word == 'right' else 'wrong-wrong-wrong'
        confirmed = confirm_from(owner, made, password)
        signed = TestClient(logins.app, base_url=ORIGIN, client=(host, 4000), headers={'origin': ORIGIN}).post(
            '/api/login', json={'username': 'sam', 'password': password})
        assert confirmed.status_code == signed.status_code, (n, confirmed.text, signed.text)
        assert attempts(confirms.store) == attempts(logins.store), n
        statuses.append(confirmed.status_code)
        if confirmed.status_code == 200:
            made = opened(confirms)                                             # a used code is gone: ask again
        confirms.clock[0] += 7
        logins.clock[0] += 7
    assert statuses == [401] * 3 + [200] + [401] * 8 + [429, 429]
