"""The confirm's password counts as /api/login counts it (R19; section 2 review S2): with the request's own `public` and
browser `device`, so a tailnet confirm counts as tailnet and a known browser counts on its device token."""
from fastapi.testclient import TestClient

from superyak_peer.auth import attempts_key, token_hash
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
    assert failures() == 3 and attempts(st.store) == before                    # the device counted, no hold did
    ok = confirm_from(browser, made)
    assert ok.status_code == 200 and 'set-cookie' not in ok.headers and failures() == 0
    assert devices() == browsers                                               # no new token, no extended one
