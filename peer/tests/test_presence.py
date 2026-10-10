"""Ship status (docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md): presence, the watch lease and
the directory. The first test is the guard (R2): requests behave the same with and without the presence headers."""
from fastapi.testclient import TestClient

HEADERS = {'x-superyak-session': 'session-one', 'x-superyak-client': 'hook/abc123', 'x-superyak-mode': 'write'}


def ship_client(app, key, **headers):
    return TestClient(app, base_url='http://testserver',
                      headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}', **headers})


def docked(store, owner_id, name='serenity'):
    started = store.start_docking(name, 'test-host')
    ship = store.confirm_docking(owner_id, started['id'], started['code'])
    return ship, store.docking_status(started['id'], started['secret'])['key']


def say(client, room, cid, body):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body})
    assert response.status_code == 201, response.text
    return response.json()


def scrub(value):
    """Times move with every request; everything else must be equal."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in ('created', 'last_activity', 'last_used')}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def test_without_the_headers_nothing_changes(env):
    """R2: the same calls with and without the headers give the same answers."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id']]}).json()['id']
    asked = say(clients[0], room, 'a', '@serenity what changed?')
    plain, marked = ship_client(app, key), ship_client(app, key, **HEADERS)
    answers = []
    for client in (plain, marked):
        answers.append([
            client.get('/api/me').json(),
            client.get('/api/chats').json(),
            client.get(f'/api/chats/{room}').json(),
            client.get('/api/mentions?after=0').json(),
            client.post('/api/ships/me/unread', json={'cursor': f'c-{len(answers)}'}).json()['messages'],
        ])
    assert scrub(answers[0]) == scrub(answers[1])
    first = plain.post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    again = marked.post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    assert first['id'] == again['id'] and 'decision' not in first and 'decision' not in again
