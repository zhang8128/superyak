from fastapi.testclient import TestClient
import pytest
from superyak_peer.responder import Responder


class ClientHttp:
    """Responder transport backed by the in-process test server."""
    def __init__(self, app):
        self.client = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
        self.csrf = ''

    def request(self, method, path, json=None):
        response = self.client.request(method, path, json=json, headers={'x-csrf-token': self.csrf})
        data = response.json() if response.content else None
        if path == '/api/login' and response.status_code == 200:
            self.csrf = data['csrf_token']
        return response.status_code, data


@pytest.fixture
def lighthouse(env, tmp_path):
    app, clients, users, clock = env
    mal = app.state.store.create_user('mal', 'Mal', 'mal-long-password')
    asked = []

    def ask(history, title):
        asked.append((title, [(m['author'], m['body']) for m in history]))
        return f'reply to {history[-1]["body"]}'

    def make(ask=ask):
        return Responder(ClientHttp(app), 'mal', 'mal-long-password', tmp_path / 'state.json', ask, store=app.state.store)
    return app, clients, users, clock, mal, asked, make


def messages(client, room):
    return [(m['author_id'], m['body']) for m in client.get(f'/api/chats/{room}').json()['messages']]


def test_replies_once_to_latest_message_on_first_sight(lighthouse):
    app, clients, users, clock, mal, asked, make = lighthouse
    room = clients[0].post('/api/chats', json={'title': 'Ask Mal', 'member_ids': [mal['id']]}).json()['id']
    for n in (1, 2):
        clock[0] += 1
        clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': f'm{n}', 'body': f'hello {n}'})
    clock[0] += 1
    responder = make()
    assert responder.cycle() == 1
    assert asked == [('Ask Mal', [('Patient', 'hello 1'), ('Patient', 'hello 2')])]
    assert messages(clients[0], room)[-1] == (mal['id'], 'reply to hello 2')
    assert responder.cycle() == 0


def test_new_messages_after_restart_and_never_itself(lighthouse):
    app, clients, users, clock, mal, asked, make = lighthouse
    room = clients[0].post('/api/chats', json={'title': 'Ask Mal', 'member_ids': [mal['id']]}).json()['id']
    clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'm1', 'body': 'first'})
    clock[0] += 1
    make().cycle()
    assert make().cycle() == 0
    clock[0] += 5
    clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'm2', 'body': 'second'})
    clock[0] += 1
    assert make().cycle() == 1
    assert [body for _, body in messages(clients[0], room)] == ['first', 'reply to first', 'second', 'reply to second']


def test_rooms_without_mal_are_invisible(lighthouse):
    app, clients, users, clock, mal, asked, make = lighthouse
    room = clients[0].post('/api/chats', json={'title': 'Private', 'member_ids': [users[1]['id']]}).json()['id']
    clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'm1', 'body': 'secret'})
    assert make().cycle() == 0 and asked == []


def test_three_failures_post_a_fallback_note(lighthouse):
    app, clients, users, clock, mal, asked, make = lighthouse
    room = clients[0].post('/api/chats', json={'title': 'Ask Mal', 'member_ids': [mal['id']]}).json()['id']
    clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'm1', 'body': 'hard'})
    clock[0] += 1

    def broken(history, title):
        raise RuntimeError('model unavailable')
    for _ in range(2):
        assert make(broken).cycle() == 0
    assert make(broken).cycle() == 1
    assert 'couldn' in messages(clients[0], room)[-1][1]
    assert make(broken).cycle() == 0


def test_access_requests_are_announced_once_in_lighthouse_room(lighthouse):
    app, clients, users, clock, mal, asked, make = lighthouse
    room = clients[2].post('/api/chats', json={'title': 'Lighthouse', 'member_ids': [mal['id']]}).json()['id']
    guest = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    guest.post('/api/access-requests', json={'name': 'Jenn', 'contact': 'jenn@example.org', 'note': ''})
    assert make().cycle() == 1
    assert make().cycle() == 0
    bodies = [body for _, body in messages(clients[2], room)]
    assert bodies == ['Jenn is asking for access. Approve or deny it under Accounts → Access requests.']
    assert asked == []
