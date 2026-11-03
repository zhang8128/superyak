"""Owner trust, Task 7 (docs/superpowers/specs/2026-11-02-machine-trust-design.md, items 2, 4a and 6): the admin grants,
renews and revokes an owner trust in the browser with their password, and can unpair a peer as retired. The routes take
a person's session with CSRF, so a ship key never acts; the two password routes count a wrong password as /api/login
counts one."""
from datetime import datetime, timezone
import socket
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
import pytest
import uvicorn

from superyak_peer.app import create_app
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import make_ship_assertion, pairing_code
from test_presence import docked

NOW = 1_800_000_000
ORIGIN = 'http://testserver'
PASSWORD = 'long-password-andy'
B_ENDPOINT = 'https://localhost:7435'
FORBIDDEN = (403, {'error': 'Ship keys cannot use this route'})


def build(tmp_path, *, clock=None, origins=(ORIGIN,), name='Andy B'):
    """A station with Andy (admin), Sam (not an admin) and Andy's docked ship rio-grande, and peer B's person `name`
    paired here with its code. `clock` is the station's (None: real time)."""
    app = create_app(tmp_path / 'station', clock=clock or time.time, allowed_origins=list(origins))
    store = app.state.store
    andy = store.create_user('andy', 'Andy', PASSWORD, is_admin=True)
    sam = store.create_user('sam', 'Sam', 'long-password-sam')
    ship, key = docked(store, andy['id'], 'rio-grande')
    b_store = Store(tmp_path / 'b')
    b_person = b_store.create_user('andy-b', name, 'long-password-b', is_admin=True)
    b_fed = Federation(b_store, endpoint=B_ENDPOINT)
    b_store.claim_federation_mode('push')
    card = b_fed.card(b_person['id'])
    owner = app.state.federation.pair(andy['id'], card, code=pairing_code(card))
    return SimpleNamespace(app=app, store=store, fed=app.state.federation, andy=andy, sam=sam, ship=ship, key=key,
                           b_fed=b_fed, b_person=b_person, owner=owner)


def now_of(st):
    return int(st.store.clock())


def grant(st, *, days=90, expect=5):
    return st.store.grant_owner_trust(st.andy['id'], st.owner['id'], days=days, expect=expect, password=PASSWORD,
                                      source='127.0.0.1')


def pair_ship(st, name):
    """B's ship `name`, paired here by rio-grande within the owner's trust."""
    ship_id = f'ship-{name}'
    card = st.b_fed.identity.card(B_ENDPOINT, {'id': ship_id, 'name': name})
    assertion = make_ship_assertion(st.b_fed.identity, ship_id=ship_id, ship_name=name, owner_id=st.b_person['id'],
                                    now=now_of(st))
    return st.fed.pair_trusted(st.ship['id'], card, assertion)


def table(st, sql):
    with st.store.transaction() as db:
        return [dict(r) for r in db.execute(sql)]


def trust_rows(st):
    return table(st, 'SELECT grant_id, event, until, expect, by_id, reason FROM owner_trust ORDER BY seq')


def written(st):
    """What any trust route could write."""
    return {name: table(st, f'SELECT * FROM {name}') for name in
            ('owner_trust', 'trust_confirmations', 'contact_holds', 'retired_peers', 'pairing_confirmations', 'peers')}


def person(app, username, password, *, host='127.0.0.1'):
    client = TestClient(app, base_url=ORIGIN, client=(host, 4000), headers={'origin': ORIGIN})
    signed = client.post('/api/login', json={'username': username, 'password': password})
    assert signed.status_code == 200, signed.text
    client.headers['x-csrf-token'] = signed.json()['csrf_token']
    return client


@pytest.fixture
def trust_station(tmp_path):
    clock = [float(NOW)]
    st = build(tmp_path, clock=lambda: clock[0])
    st.clock = clock
    st.andy_client = person(st.app, 'andy', PASSWORD)
    st.sam_client = person(st.app, 'sam', 'long-password-sam')
    return st


def answer(response):
    return response.status_code, response.json()


# ---- The routes ------------------------------------------------------------------------------------------------------

def test_a_ship_key_cannot_grant_renew_revoke_or_retire(trust_station):
    """Spec item 2: a ship never grants, renews or revokes. Every route takes a person's session (current_user), so a
    request with a ship's key gets 403 even when it also carries the admin's session and CSRF token, and nothing is
    written: no trust, no hold, no retirement and no counted password."""
    st = trust_station
    done = grant(st)
    pair_ship(st, 'tardis')
    window = st.andy_client.get(f"/api/owner-trust/{done['grant_id']}").json()
    seen = [window['window_seq'], window['paired']]
    bare = TestClient(st.app, base_url=ORIGIN, headers={'origin': ORIGIN, 'authorization': f'Bearer {st.key}'})
    riding = TestClient(st.app, base_url=ORIGIN, cookies={'superyak_session': st.andy_client.cookies.get('superyak_session')},
                        headers={'origin': ORIGIN, 'authorization': f'Bearer {st.key}',
                                 'x-csrf-token': st.andy_client.headers['x-csrf-token']})
    before, attempts = written(st), table(st, 'SELECT * FROM login_attempts')
    for client in (bare, riding):
        assert answer(client.post(f"/api/connections/{st.owner['id']}/trust",
                                  json={'days': 90, 'expect': 5, 'password': PASSWORD})) == FORBIDDEN
        assert answer(client.get(f"/api/owner-trust/{done['grant_id']}")) == FORBIDDEN
        assert answer(client.post(f"/api/owner-trust/{done['grant_id']}/renew",
                                  json={'days': 90, 'expect': 5, 'seen': seen, 'password': PASSWORD})) == FORBIDDEN
        assert answer(client.post(f"/api/owner-trust/{done['grant_id']}/revoke", json={})) == FORBIDDEN
        assert answer(client.request('DELETE', f"/api/connections/{st.owner['id']}", json={'retire': True})) == FORBIDDEN
    assert written(st) == before and table(st, 'SELECT * FROM login_attempts') == attempts


def counters(st):
    return sorted(tuple(r.values()) for r in table(st, 'SELECT key, count, reset FROM login_attempts'))


@pytest.mark.parametrize('host', ['127.0.0.1', '100.70.202.124', '203.0.113.9', '2001:db8::5'])
def test_a_wrong_password_is_counted_as_a_sign_in(tmp_path, host):
    """Spec item 2, "like the imprint confirm": the grant's and the renewal's password are laned and counted as
    /api/login counts a sign-in from the same client (its own `public` and browser), step by step. A station that
    takes the routes and one that takes sign-ins answer each step alike and keep the same counters."""
    clocks = {'trusts': [float(NOW)], 'logins': [float(NOW)]}
    trusts, logins = (build(tmp_path / which, clock=lambda c=clocks[which]: c[0]) for which in ('trusts', 'logins'))
    signed = person(trusts.app, 'andy', PASSWORD, host=host)
    andy = TestClient(trusts.app, base_url=ORIGIN, client=(host, 4000),
                      cookies={'superyak_session': signed.cookies.get('superyak_session')},
                      headers={'origin': ORIGIN, 'x-csrf-token': signed.headers['x-csrf-token']})
    login = TestClient(logins.app, base_url=ORIGIN, client=(host, 4000), headers={'origin': ORIGIN})
    login.post('/api/login', json={'username': 'andy', 'password': PASSWORD})  # the session the other station opened
    assert counters(trusts) == counters(logins)

    def step(call, password):
        mine, theirs = call(password), login.post('/api/login', json={'username': 'andy', 'password': password})
        for clock in clocks.values():
            clock[0] += 7
        return mine, theirs

    def granted(password):
        return andy.post(f"/api/connections/{trusts.owner['id']}/trust", json={'days': 90, 'expect': 5, 'password': password})
    for word in ('wrong', 'wrong', 'right'):
        mine, theirs = step(granted, PASSWORD if word == 'right' else 'wrong-wrong-wrong')
        if word == 'wrong':
            assert answer(mine) == (401, {'error': 'Invalid password'}) and theirs.status_code == 401
        else:
            assert mine.status_code == 201 and theirs.status_code == 200, mine.text
        assert counters(trusts) == counters(logins), word
    grant_id = mine.json()['grant_id']
    window = andy.get(f'/api/owner-trust/{grant_id}').json()

    def renewed(password):
        return andy.post(f'/api/owner-trust/{grant_id}/renew', json={
            'days': 90, 'expect': 5, 'seen': [window['window_seq'], window['paired']], 'password': password})
    mine, theirs = step(renewed, 'wrong-wrong-wrong')
    assert answer(mine) == (401, {'error': 'Invalid password'}) and theirs.status_code == 401
    assert counters(trusts) == counters(logins)
    assert [r['event'] for r in trust_rows(trusts)] == ['grant']


def test_the_routes_grant_show_renew_and_revoke(trust_station):
    st = trust_station
    owner, andy = st.owner, st.andy_client
    made = andy.post(f"/api/connections/{owner['id']}/trust", json={'days': 30, 'expect': 2, 'password': PASSWORD})
    assert made.status_code == 201, made.text
    done = made.json()
    assert done == {'grant_id': done['grant_id'], 'until': NOW + 30 * 86400,
                    'text': f"ships owned by Andy B on {owner['peer_id'][:12]} may be paired by this station's ships, "
                            'until 2027-02-14'}
    tardis = pair_ship(st, 'tardis')
    view = andy.get(f"/api/owner-trust/{done['grant_id']}").json()
    assert {k: v for k, v in view.items() if k not in ('ships', 'window_seq')} == {
        'grant_id': done['grant_id'], 'owner': 'Andy B', 'peer_id': owner['peer_id'], 'until': NOW + 30 * 86400,
        'state': 'live', 'expect': 2, 'paired': 1}
    assert view['ships'] == [{'contact_id': tardis['id'], 'label': 'ship of Andy B: tardis', 'acting_ship': 'rio-grande',
                              'confirmed': NOW, 'held': False}]
    seen = [view['window_seq'], view['paired']]
    pair_ship(st, 'defiant')  # the window fills after the page was read: the renewal refuses, and writes nothing
    stale = andy.post(f"/api/owner-trust/{done['grant_id']}/renew",
                      json={'days': 90, 'expect': 5, 'seen': seen, 'password': PASSWORD})
    assert answer(stale) == (409, {'error': 'the trust paired more ships since you looked; read the page again'})
    view = andy.get(f"/api/owner-trust/{done['grant_id']}").json()
    assert (view['state'], view['paired'], [s['label'] for s in view['ships']]) == (
        'paused', 2, ['ship of Andy B: tardis', 'ship of Andy B: defiant'])
    for bad in ('1,2', [1], [1, 2, 3], [True, 2], [1.0, 2], None):  # `seen` is the two whole numbers the page showed
        refused = andy.post(f"/api/owner-trust/{done['grant_id']}/renew",
                            json={'days': 90, 'expect': 5, 'seen': bad, 'password': PASSWORD})
        assert refused.status_code == 400, bad
    renewed = andy.post(f"/api/owner-trust/{done['grant_id']}/renew",
                        json={'days': 90, 'expect': 5, 'seen': [view['window_seq'], view['paired']], 'password': PASSWORD})
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()['until'] == NOW + 90 * 86400
    assert andy.get(f"/api/owner-trust/{done['grant_id']}").json()['paired'] == 0  # a new window
    revoked = andy.post(f"/api/owner-trust/{done['grant_id']}/revoke", json={})
    assert answer(revoked) == (200, {'grant_id': done['grant_id'], 'held': 2})
    assert [r['event'] for r in trust_rows(st)] == ['grant', 'renew', 'revoke']
    assert trust_rows(st)[-1]['by_id'] == st.andy['id']


def test_only_an_admin_with_csrf_reaches_the_routes(trust_station):
    st = trust_station
    done = grant(st)
    before = written(st)
    view = st.andy_client.get(f"/api/owner-trust/{done['grant_id']}").json()
    calls = [('POST', f"/api/connections/{st.owner['id']}/trust", {'days': 90, 'expect': 5, 'password': 'long-password-sam'}),
             ('GET', f"/api/owner-trust/{done['grant_id']}", None),
             ('POST', f"/api/owner-trust/{done['grant_id']}/renew",
              {'days': 90, 'expect': 5, 'seen': [view['window_seq'], view['paired']], 'password': 'long-password-sam'}),
             ('POST', f"/api/owner-trust/{done['grant_id']}/revoke", {}),
             ('DELETE', f"/api/connections/{st.owner['id']}", {'retire': True})]
    for method, path, payload in calls:
        assert answer(st.sam_client.request(method, path, json=payload)) == (403, {'error': 'Admin required'}), path
    no_csrf = TestClient(st.app, base_url=ORIGIN, cookies={'superyak_session': st.andy_client.cookies.get('superyak_session')},
                         headers={'origin': ORIGIN})
    for method, path, payload in calls:
        if method != 'GET':
            assert answer(no_csrf.request(method, path, json=payload)) == (403, {'error': 'Refresh the page before making changes'})
    assert written(st) == before
    assert st.andy_client.get('/api/owner-trust/nope').status_code == 404


def test_unpairing_as_retired(trust_station):
    """Spec item 6, S11: DELETE with {"retire": true} retires the peer; with no body, or retire false, it only unpairs,
    as before; anything else is refused and writes nothing."""
    st = trust_station
    before = written(st)
    for bad in ({'retire': 'yes'}, {'retire': 1}, {'retire': None}, [True]):
        refused = st.andy_client.request('DELETE', f"/api/connections/{st.owner['id']}", json=bad)
        assert refused.status_code == 400, bad
    assert written(st) == before
    assert answer(st.andy_client.request('DELETE', f"/api/connections/{st.owner['id']}", json={'retire': False})) == (200, {'ok': True})
    assert table(st, 'SELECT * FROM retired_peers') == []
    assert answer(st.andy_client.delete(f"/api/connections/{st.owner['id']}")) == (200, {'ok': True})  # no body at all
    assert table(st, 'SELECT * FROM retired_peers') == []
    assert answer(st.andy_client.request('DELETE', f"/api/connections/{st.owner['id']}", json={'retire': True})) == (200, {'ok': True})
    assert table(st, 'SELECT peer_id, retired, by_id FROM retired_peers') == [
        {'peer_id': st.owner['peer_id'], 'retired': NOW, 'by_id': st.andy['id']}]


# ---- What connections() and contacts() say -------------------------------------------------------------------------

def test_connections_say_a_paused_trust_is_paused(trust_station):
    """Task 6's review: `live` read True for a paused trust. Each code-confirmed contact's trust now carries its state
    (live, paused, expired or revoked) and its window's count, as trust_list says them."""
    st = trust_station
    done = grant(st, expect=1)

    def trust():
        return next(c for c in st.fed.connections(st.andy['id']) if c['id'] == st.owner['id'])['owner_trust']
    window = trust()['window_seq']
    assert trust() == {'grant_id': done['grant_id'], 'until': done['until'], 'live': True, 'state': 'live',
                       'window_seq': window, 'expect': 1, 'paired': 0}
    pair_ship(st, 'tardis')
    assert trust() == {'grant_id': done['grant_id'], 'until': done['until'], 'live': False, 'state': 'paused',
                       'window_seq': window, 'expect': 1, 'paired': 1}
    st.clock[0] = done['until']
    assert (trust()['live'], trust()['state']) == (False, 'expired')
    st.store.revoke_owner_trust(st.andy['id'], done['grant_id'])
    assert (trust()['live'], trust()['state']) == (False, 'revoked')


def test_a_trust_with_no_until_reads_as_expired(trust_station):
    """Only a damaged file holds a grant with a NULL `until`. It fails closed, as a window with no count does: the trust
    reads as expired in connections(), the renewal page and the trust list, and nothing raises."""
    from superyak_peer.owner_trust import trust_list
    st = trust_station
    with st.store.transaction() as db:
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,expect) "
                   "VALUES ('damaged','grant',?,?,NULL,?,?,5)", (st.owner['peer_id'], st.owner['user_id'], st.andy['id'], NOW))
    trust = next(c for c in st.fed.connections(st.andy['id']) if c['id'] == st.owner['id'])['owner_trust']
    assert (trust['grant_id'], trust['state'], trust['live']) == ('damaged', 'expired', False)
    assert st.andy_client.get('/api/owner-trust/damaged').json()['state'] == 'expired'
    with st.store.transaction() as db:
        assert [t['state'] for t in trust_list(db, NOW)] == ['expired']


def test_a_trust_ship_and_a_retired_peer_say_what_holds_them(trust_station):
    """Task 6's review: a ship held because its owner's trust was revoked read "held until its own code is typed",
    which leaves out the trust. Each contact says whether a trust made it and whether its peer was retired, and the
    CLI's words say why it's held."""
    from superyak_peer.__main__ import contact_state, describe_connections
    st = trust_station
    grant(st)
    tardis = pair_ship(st, 'tardis')

    def listed():
        return {c['id']: c for c in st.fed.connections(st.andy['id'])}
    ship, owner = listed()[tardis['id']], listed()[st.owner['id']]
    assert (ship['trust_ship'], ship['retired'], owner['trust_ship'], owner['retired']) == (True, False, False, False)
    assert contact_state(ship) == 'confirmed by owner trust'
    st.store.revoke_owner_trust(st.andy['id'], table(st, 'SELECT grant_id FROM owner_trust')[0]['grant_id'])
    assert contact_state(listed()[tardis['id']]) == ("held: its owner's trust was revoked; a new trust and a fresh "
                                                     'export-ship bring it back, or its own code')
    assert contact_state(listed()[st.owner['id']]) == 'confirmed by typing'
    st.fed.unpair(st.andy['id'], st.owner['id'])
    assert contact_state(listed()[st.owner['id']]) == 'held until its own code is typed'
    st.fed.unpair(st.andy['id'], st.owner['id'], retire=True)
    for contact in listed().values():
        assert contact['retired'] is True
        assert contact_state(contact) == 'held: its peer was retired; it comes back only as a new identity'
    shown = describe_connections(list(listed().values()), now=NOW)
    assert 'held: its peer was retired' in shown and 'held until its own code' not in shown


def test_contacts_mark_a_trust_ship(trust_station):
    """Task 6's review: the audience picker named a trust ship "Named person". contacts() marks each remote contact a
    trust made, so the page reads it as a ship."""
    st = trust_station
    grant(st)
    tardis = pair_ship(st, 'tardis')
    contacts = {c['id']: c for c in st.store.contacts(st.andy['id'])}
    assert (contacts[tardis['id']]['name'], contacts[tardis['id']]['trust_ship']) == ('ship of Andy B: tardis', True)
    assert (contacts[st.owner['id']]['name'], contacts[st.owner['id']]['trust_ship']) == ('Andy B', False)
    assert 'trust_ship' not in contacts[st.sam['id']]  # a local account


# ---- In a real browser -----------------------------------------------------------------------------------------------

@pytest.fixture
def chromium():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def trust_browser(tmp_path, chromium, request):
    """The station at a free port in real time, as tests/test_imprint_browser.py serves one."""
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    st = build(tmp_path, origins=(ORIGIN, url), **getattr(request, 'param', {}))
    server = uvicorn.Server(uvicorn.Config(st.app, host='127.0.0.1', port=port, log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            urlopen(url + '/', timeout=2)
            break
        except HTTPError:
            break
        except (URLError, TimeoutError, ConnectionError):
            time.sleep(0.05)
    else:
        pytest.fail('browser test server did not start')
    st.url, st.browser = url, chromium
    yield st
    server.should_exit = True
    thread.join(timeout=10)


def connections_page(st):
    page = st.browser.new_context(viewport={'width': 1440, 'height': 960}).new_page()
    page.goto(st.url + '/')
    page.get_by_label('Username', exact=True).fill('andy')
    page.get_by_label('Password', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='Sign in').click()
    expect(page.get_by_role('heading', name='Your home', exact=True)).to_be_visible()
    page.get_by_role('link', name='Connections', exact=True).click()
    expect(page.get_by_role('heading', name='Paired peers')).to_be_visible()
    return page


def utc_date(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d')


def grant_line(st, days, name='Andy B'):
    return (f"ships owned by {name} on {st.owner['peer_id'][:12]} may be paired by this station's ships, "
            f'until {utc_date(time.time() + days * 86400)}')


def flash(page):
    return page.locator('.notice[role=status]')


def test_granting_in_the_browser(trust_browser):
    """The brief's test: Connections, the button, the grant line verbatim; Grant without a password (or without the
    expected count) does nothing; Grant with it shows the live trust, Renew and Revoke."""
    st = trust_browser
    page = connections_page(st)
    sent = []
    page.on('request', lambda request: sent.append(request.url) if '/trust' in request.url else None)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    owner.get_by_role('button', name='Trust ships owned by Andy B').click()
    expect(owner.get_by_text(grant_line(st, 90), exact=True)).to_be_visible()
    expect(owner.get_by_label('Days')).to_have_value('90')
    expect(owner.get_by_label('Expect up to')).to_have_value('')
    expect(owner.get_by_label('Password')).to_have_value('')
    expect(owner.get_by_label('Password')).to_have_attribute('autocomplete', 'new-password')
    expect(owner.get_by_text("Type your own station password. Don't accept a password your browser suggests.")).to_be_visible()
    owner.get_by_label('Password').fill(PASSWORD)
    owner.get_by_role('button', name='Grant', exact=True).click()  # no expected count: the form refuses it
    owner.get_by_label('Password').fill('')
    owner.get_by_label('Expect up to').fill('5')
    owner.get_by_label('Days').fill('30')
    expect(owner.get_by_text(grant_line(st, 30), exact=True)).to_be_visible()  # the line follows the days
    owner.get_by_role('button', name='Grant', exact=True).click()  # no password: nothing is sent
    page.wait_for_timeout(300)
    assert sent == [] and trust_rows(st) == []
    expect(owner.get_by_text(grant_line(st, 30), exact=True)).to_be_visible()
    owner.get_by_label('Password').fill(PASSWORD)
    owner.get_by_role('button', name='Grant', exact=True).click()
    expect(flash(page)).to_have_text(f'Owner trust granted: {grant_line(st, 30)}')
    expect(owner.get_by_text(grant_line(st, 30), exact=True)).to_be_visible()
    expect(owner.get_by_text('Live: 0 of 5 expected ships paired in this window.', exact=True)).to_be_visible()
    expect(owner.get_by_role('button', name='Renew', exact=True)).to_be_visible()
    expect(owner.get_by_role('button', name='Revoke', exact=True)).to_be_visible()
    expect(owner.get_by_role('button', name='Trust ships owned by Andy B')).to_have_count(0)
    rows = trust_rows(st)
    assert [(r['event'], r['expect'], r['by_id']) for r in rows] == [('grant', 5, st.andy['id'])]
    assert abs(rows[0]['until'] - (time.time() + 30 * 86400)) < 60


def test_a_wrong_password_in_the_browser_grants_nothing_and_says_so(trust_browser):
    st = trust_browser
    page = connections_page(st)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    owner.get_by_role('button', name='Trust ships owned by Andy B').click()
    owner.get_by_label('Expect up to').fill('5')
    owner.get_by_label('Password').fill('not-the-password')
    owner.get_by_role('button', name='Grant', exact=True).click()
    expect(owner.get_by_role('alert')).to_have_text('Invalid password')
    expect(owner.get_by_label('Password')).to_have_value('')
    expect(owner.get_by_label('Expect up to')).to_have_value('5')
    assert trust_rows(st) == []


def test_renewing_lists_the_window_and_refuses_a_page_gone_stale(trust_browser):
    """Spec item 4a: a paused trust says so and offers Renew; the renewal lists the ships paired in the window before
    its password, is prefilled with the last count and 90 days, and sends what it showed, so a ship paired after the
    page was read makes it refuse and show the list again."""
    st = trust_browser
    grant(st, expect=2)
    pair_ship(st, 'tardis')
    page = connections_page(st)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    expect(owner.get_by_text('Live: 1 of 2 expected ships paired in this window.', exact=True)).to_be_visible()
    owner.get_by_role('button', name='Renew', exact=True).click()
    form = owner.locator('#trust-renew-form')
    expect(form.get_by_text('ship of Andy B: tardis', exact=False)).to_be_visible()
    expect(form.get_by_label('Expect up to')).to_have_value('2')
    expect(form.get_by_label('Days')).to_have_value('90')
    expect(form.get_by_text(grant_line(st, 90), exact=True)).to_be_visible()
    assert form.evaluate("f => !!(f.querySelector('.trust-window').compareDocumentPosition("
                         "f.querySelector('#trust-password')) & Node.DOCUMENT_POSITION_FOLLOWING)")
    pair_ship(st, 'defiant')  # the second of two: the trust pauses while the page shows one
    form.get_by_label('Expect up to').fill('5')
    form.get_by_label('Password').fill(PASSWORD)
    form.get_by_role('button', name='Renew', exact=True).click()
    expect(owner.get_by_role('alert')).to_have_text('the trust paired more ships since you looked; read the page again')
    assert [r['event'] for r in trust_rows(st)] == ['grant']
    expect(owner.get_by_text('Paused after 2 pairings: renew or revoke it.', exact=True)).to_be_visible()
    form = owner.locator('#trust-renew-form')
    expect(form.get_by_text('ship of Andy B: defiant', exact=False)).to_be_visible()
    expect(form.get_by_text('2 ships paired in this window', exact=False)).to_be_visible()
    form.get_by_label('Expect up to').fill('5')
    form.get_by_label('Password').fill(PASSWORD)
    form.get_by_role('button', name='Renew', exact=True).click()
    expect(flash(page)).to_have_text(f'Owner trust renewed: {grant_line(st, 90)}')
    expect(owner.get_by_text('Live: 0 of 5 expected ships paired in this window.', exact=True)).to_be_visible()
    assert [(r['event'], r['expect']) for r in trust_rows(st)] == [('grant', 2), ('renew', 5)]


def test_a_refusal_that_ends_the_form_says_so_in_the_flash(trust_browser):
    """A trust revoked elsewhere while its renewal is open: the renewal is refused, the page reads the trust again and
    offers a new grant instead of the form, and the refusal is said in the flash, not lost with the form."""
    st = trust_browser
    done = grant(st)
    page = connections_page(st)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    owner.get_by_role('button', name='Renew', exact=True).click()
    form = owner.locator('#trust-renew-form')
    expect(form.get_by_text('No ships paired in this window yet.', exact=True)).to_be_visible()
    st.store.revoke_owner_trust(st.andy['id'], done['grant_id'])
    form.get_by_label('Password').fill(PASSWORD)
    form.get_by_role('button', name='Renew', exact=True).click()
    expect(flash(page)).to_have_text('That owner trust was revoked')
    expect(owner.get_by_role('button', name='Trust ships owned by Andy B')).to_be_visible()
    assert [r['event'] for r in trust_rows(st)] == ['grant', 'revoke']


def test_revoking_asks_first_and_holds_the_ships(trust_browser):
    st = trust_browser
    grant(st)
    tardis = pair_ship(st, 'tardis')
    page = connections_page(st)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    ship = page.locator(f"[data-contact=\"{tardis['id']}\"]")
    expect(ship).to_have_text('ship of Andy B: tardis, confirmed by owner trust')
    owner.get_by_role('button', name='Revoke', exact=True).click()
    expect(owner.get_by_text('Every ship it paired is held at once', exact=False)).to_be_visible()
    assert [r['event'] for r in trust_rows(st)] == ['grant']
    owner.get_by_role('button', name='Yes, revoke').click()
    expect(flash(page)).to_have_text('Owner trust revoked; 1 ship held.')
    expect(ship).to_have_text("ship of Andy B: tardis, held: its owner's trust was revoked; a new trust and a fresh "
                              'export-ship bring it back, or its own code')
    expect(owner.get_by_role('button', name='Trust ships owned by Andy B')).to_be_visible()
    expect(owner.get_by_role('button', name='Revoke', exact=True)).to_have_count(0)
    assert [(r['event'], r['by_id']) for r in trust_rows(st)] == [('grant', st.andy['id']), ('revoke', st.andy['id'])]


def test_unpairing_as_retired_asks_first(trust_browser):
    st = trust_browser
    page = connections_page(st)
    retire = page.get_by_role('button', name='Unpair as retired (this machine may be compromised)')
    retire.click()
    expect(page.get_by_text('No code typed for it pairs it again', exact=False)).to_be_visible()
    page.get_by_role('button', name='Cancel', exact=True).click()
    expect(retire).to_be_visible()
    assert table(st, 'SELECT * FROM retired_peers') == []
    retire.click()
    page.get_by_role('button', name='Yes, unpair as retired').click()
    expect(flash(page)).to_have_text('The peer is retired, and all of its contacts are held.')
    expect(page.get_by_text('Retired peer', exact=True)).to_be_visible()
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    expect(owner).to_contain_text('Held: its peer was retired; it comes back only as a new identity')
    expect(retire).to_have_count(0)
    expect(page.get_by_role('button', name='Disconnect peer and 1 contact')).to_have_count(0)
    assert [r['peer_id'] for r in table(st, 'SELECT * FROM retired_peers')] == [st.owner['peer_id']]


def test_a_trust_ship_reads_as_a_ship_in_the_audience_picker(trust_browser):
    st = trust_browser
    grant(st)
    pair_ship(st, 'tardis')
    page = connections_page(st)
    page.get_by_role('link', name='My sharing layers').click()
    page.get_by_role('button', name='New layer').click()
    expect(page.get_by_label('Layer title')).to_have_value('Untitled')
    choice = page.locator('label.choice', has_text='ship of Andy B: tardis')
    expect(choice.locator('small')).to_have_text('Ship · paired contact')
    expect(page.locator('label.choice', has_text='Andy B').filter(has_not_text='ship of').locator('small')).to_have_text(
        'Named person · paired contact')


HOSTILE = '<img src=x onerror="window.pwned=1">Andy & "B"'


@pytest.mark.parametrize('trust_browser', [{'name': HOSTILE}], indirect=True)
def test_names_are_escaped(trust_browser):
    """Every name and label is escaped as the view escapes them: the button, the grant line, the live line, the
    renewal's ship list and the revoke question show the name as text, and no element is made from it."""
    st = trust_browser
    page = connections_page(st)
    owner = page.locator(f"[data-contact=\"{st.owner['id']}\"]")
    owner.get_by_role('button', name=f'Trust ships owned by {HOSTILE}').click()
    expect(owner.get_by_text(grant_line(st, 90, HOSTILE), exact=True)).to_be_visible()
    owner.get_by_label('Expect up to').fill('3')
    owner.get_by_label('Days').fill('89')
    owner.get_by_label('Password').fill(PASSWORD)
    owner.get_by_role('button', name='Grant', exact=True).click()
    expect(owner.get_by_text('Live: 0 of 3 expected ships paired in this window.', exact=True)).to_be_visible()
    expect(owner.get_by_text(grant_line(st, 89, HOSTILE), exact=True)).to_be_visible()
    pair_ship(st, 'tardis')
    page.get_by_role('button', name='Check delivery now').click()
    expect(flash(page)).to_have_text('Delivery status refreshed')
    owner.get_by_role('button', name='Renew', exact=True).click()
    expect(owner.locator('#trust-renew-form').get_by_text(f'ship of {HOSTILE}: tardis', exact=False)).to_be_visible()
    owner.get_by_role('button', name='Cancel', exact=True).click()
    owner.get_by_role('button', name='Revoke', exact=True).click()
    expect(owner.get_by_text(f'Revoke the owner trust for ships owned by {HOSTILE}?', exact=False)).to_be_visible()
    assert page.locator('#main-content img').count() == 0
    assert page.evaluate('window.pwned') is None
