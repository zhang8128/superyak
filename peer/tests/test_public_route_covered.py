"""The public-route-bound plan, Task 10: every public store call before identity is covered (the spec reviewer's
finding 1). Each allow-listed route, and PublicRoute's own credential paths, is driven as a public client with each
kind of junk, many at once, under store.counting(), with every store call slowed so that unbounded work would overlap.
Each must make no store call at all, or make every one inside its named lane and never more at once than the lane's
size (the high-water mark), or be named below with its reason. A route added to PUBLIC_ROUTES later fails here until
it says which."""
import asyncio
from contextlib import contextmanager
import time

import httpx
import pytest

from superyak_peer import counting
from superyak_peer.app import PUBLIC_ROUTES, create_app
from superyak_peer.db import Store

PUBLIC_CLIENT = ('203.0.113.5', 50000)
AT_ONCE = 12  # more than every lane's size, so a missing lane shows as a peak above it
JUNK = 'j' * 43
LONG = 'x' * 4000

# Routes whose public answer makes no store call at all.
NO_STORE = {
    '/': {'GET', 'HEAD'}, '/public/': {'GET', 'HEAD'}, '/assets': {'GET', 'HEAD'},
    '/api/health': {'GET'},  # Task 8
    '/api/invitations/redeem': {'POST'},  # Task 7b: junk is refused in memory, before redeem's lane
}
# Routes whose public store work all runs in a lane: (lane, how many inside at once).
LANED = {
    '/api/login': ('public', 2),  # public route spec 3's sign-in lane; a junk device cookie reads nothing before it (Task 4)
    '/public/layers/{key}': ('layers', 4),  # Task 6
    '/public/layers/{layer_id}/files/{key}': ('layers', 4),
}
# Named, with the reason each is not bounded here.
EXEMPT = {
    'the connector': ({'/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp',
                       '/.well-known/oauth-authorization-server', '/register', '/authorize', '/authorize/signin',
                       '/authorize/decision', '/token', '/mcp'},
                      "phase 1b: it isn't deployed (serve --public-origin is off), and its tags come with it"),
    'the door': (set(), 'phase 2: its own app on its own port (door.py), outside PUBLIC_ROUTES'),
}

# What each route is sent: (path, body) for each junk shape it takes.
SENT = {
    '/': [('/', None)], '/public/': [('/public/?layer=' + JUNK, None)], '/assets': [('/assets/' + JUNK + '.js', None)],
    '/api/health': [('/api/health', None)],
    '/api/invitations/redeem': [('/api/invitations/redeem', {'token': JUNK, 'username': 'junk', 'name': 'Junk', 'password': JUNK}),
                                ('/api/invitations/redeem', {'token': LONG, 'username': 'junk', 'name': 'Junk', 'password': JUNK})],
    '/api/login': [('/api/login', {'username': 'junk', 'password': JUNK})],
    '/public/layers/{key}': [('/public/layers/' + JUNK, None)],
    '/public/layers/{layer_id}/files/{key}': [(f'/public/layers/{JUNK}/files/{JUNK}', None)],
}
CREDENTIALS = {  # each kind of junk credential, sent with every request above
    'none': {}, 'session': {'cookie': f'superyak_session={JUNK}'}, 'device': {'cookie': f'superyak_device={JUNK}'},
    'long session': {'cookie': f'superyak_session={LONG}'}, 'long key': {'authorization': f'Bearer {LONG}'},
}


def test_every_allow_listed_route_says_how_it_is_bounded():
    exempt = set().union(*(paths for paths, _ in EXEMPT.values()))
    named = set(NO_STORE) | set(LANED) | exempt
    assert set(PUBLIC_ROUTES) - named == set(), 'a public route that says neither its bound nor why it has none'
    assert named - set(PUBLIC_ROUTES) == set(), 'a name here for a route that is no longer public'
    assert not set(NO_STORE) & set(LANED) and not (set(NO_STORE) | set(LANED)) & exempt
    for path, methods in NO_STORE.items():
        assert methods == PUBLIC_ROUTES[path], path
    assert set(SENT) == set(NO_STORE) | set(LANED)


@pytest.fixture
def slowed(tmp_path, monkeypatch):
    """The app, with every store call held 30 ms once inside, so calls that nothing bounds overlap."""
    app = create_app(tmp_path / 'home', allowed_origins=['http://testserver'])
    for name in ('transaction', 'reading'):
        real = getattr(Store, name)

        def slow(self, *args, _real=real, **kwargs):
            @contextmanager
            def held():
                with _real(self, *args, **kwargs) as db:
                    time.sleep(0.03)
                    yield db
            return held()
        monkeypatch.setattr(Store, name, slow)
    return app


def flood(app, method, path, body, headers):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=PUBLIC_CLIENT), base_url='http://testserver',
                                     headers={'origin': 'http://testserver', **headers}) as http:
            return await asyncio.gather(*(http.request(method, path, json=body) for _ in range(AT_ONCE)))
    return asyncio.run(run())


ROUTES = [(path, method) for path in sorted(set(NO_STORE) | set(LANED)) for method in sorted(PUBLIC_ROUTES[path])]


@pytest.mark.parametrize('path, method', ROUTES)
@pytest.mark.parametrize('credential', sorted(CREDENTIALS))
def test_a_public_route_under_junk_makes_no_store_call_or_keeps_to_its_lane(slowed, path, method, credential):
    app = slowed
    for sent, body in SENT[path]:
        with app.state.store.counting() as counted:
            answers = flood(app, method, sent, body, CREDENTIALS[credential])
        assert all(answer.status_code < 500 for answer in answers), (sent, [a.status_code for a in answers])
        assert counted.total(lane=counting.BEFORE) == 0 and counted.total(where=counting.UNFILED) == 0, counted.table()
        if path in NO_STORE:
            assert counted.total() == 0, (sent, credential, counted.table())
        else:
            lane, size = LANED[path]
            assert counted.total(lane=lane) == counted.total(), counted.table()  # all of it in its own lane
            for kind in ('read', 'transaction'):
                assert counted.peak(kind, lane=lane) <= size, (sent, kind, counted.peak(kind, lane=lane))


@pytest.mark.parametrize('credential, lane, size', [
    ({'cookie': f'superyak_session={JUNK}'}, None, 0), ({'cookie': f'superyak_device={JUNK}'}, None, 0),
    ({'cookie': f'superyak_session={LONG}'}, None, 0), ({'authorization': f'Bearer {LONG}'}, None, 0),
    ({'authorization': f'Bearer {JUNK}'}, 'miss', 1),  # Task 3: a key the live set lacks waits in the miss lane
])
@pytest.mark.parametrize('path', ['/api/chats', '/api/me', '/api/home', '/no-such-page'])
def test_publicroutes_own_credential_paths_under_junk(slowed, path, credential, lane, size):
    """Off the allow-list, PublicRoute's own check is the only store call before identity: none for a session or device
    the live set lacks or anything over 128 characters, and a junk key's lookup in the miss lane, one at a time."""
    app = slowed
    with app.state.store.counting() as counted:
        answers = flood(app, 'GET', path, None, credential)
    assert all(answer.status_code in (401, 404, 503) for answer in answers)
    if lane is None:
        assert counted.total() == 0, counted.table()
    else:
        assert counted.total(lane=lane) == counted.total() > 0
        assert counted.peak('read', lane=lane) <= size
