"""The agent component against the real station (skipped in the standalone peer bundle)."""
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs
import pytest
from fastapi.testclient import TestClient

AGENT = Path(__file__).resolve().parents[2] / 'agent'
pytestmark = pytest.mark.skipif(not (AGENT / 'superyak_agent').is_dir(), reason='needs agent/ from the full repository')
if (AGENT / 'superyak_agent').is_dir():
    sys.path[:0] = [str(AGENT), str(AGENT.parent / 'team')]


def transport_for(app):
    client = TestClient(app, base_url='http://testserver')

    def send(method, url, headers, data):
        response = client.request(method, url.removeprefix('http://testserver'), headers=headers, content=data)
        return response.status_code, response.content
    return send


@pytest.fixture
def docking(env, tmp_path):
    from superyak_agent.dock import Dock
    app, clients, users, clock = env
    opened, home = [], tmp_path / 'ship-home'

    def make(ship):
        return Dock('http://testserver', door='http://testserver', ship=ship, workspace=str(tmp_path / 'repo'), home=home,
                    transport=transport_for(app), clock=lambda: clock[0], sleep=lambda s: None, out=lambda *a: None,
                    machine='test-host', open_url=opened.append)
    return app, clients, users, clock, make, opened, home


def test_existing_person_docks_after_confirming_in_the_browser(docking):
    app, clients, users, clock, make, opened, home = docking
    dock = make('serenity')
    assert dock.step() == 'waiting-for-confirm'
    pending = json.loads((home / 'docking.json').read_text())
    assert opened == [pending['confirm_url']]
    assert dock.step() == 'waiting-for-confirm' and opened == [pending['confirm_url']]
    clients[0].post(f'/api/dockings/{pending["id"]}/confirm', json={'code': pending['code']})
    assert dock.step() == 'docked'
    config = json.loads((home / 'station.json').read_text())
    assert (config['ship'], config['owner_id'], config['machine']) == ('serenity', users[0]['id'], 'test-host')
    assert (home / 'station.json').stat().st_mode & 0o777 == 0o600 and not (home / 'docking.json').exists()
    assert make('serenity').step() == 'docked'


def test_newcomer_requests_access_then_docks_after_one_approval(docking):
    app, clients, users, clock, make, opened, home = docking
    fields = {'name': 'Jenn', 'contact': 'jenn@example.org', 'note': 'Andy invited me'}
    dock = make('rio-grande')
    assert dock.step(fields) == 'waiting-for-approval'
    assert dock.step(fields) == 'waiting-for-approval'
    request = json.loads((home / 'access-request.json').read_text())
    clients[2].post(f'/api/access-requests/{request["id"]}/approve', json={})
    assert dock.step(fields) == 'waiting-for-confirm'
    invitation = (home / 'invitation.txt').read_text().strip()
    assert invitation.startswith('http://testserver/#activate?') and opened[0] == invitation
    token = parse_qs(invitation.split('#activate?', 1)[1])['token'][0]
    jenn = TestClient(app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    assert jenn.post('/api/invitations/redeem', json={'token': token, 'username': 'jenn', 'name': 'Jenn', 'password': 'jenn-chosen-password'}).status_code == 201
    jenn.headers['x-csrf-token'] = jenn.post('/api/login', json={'username': 'jenn', 'password': 'jenn-chosen-password'}).json()['csrf_token']
    pending = json.loads((home / 'docking.json').read_text())
    assert jenn.post(f'/api/dockings/{pending["id"]}/confirm', json={'code': pending['code']}).status_code == 200
    assert dock.step(fields) == 'docked'
    assert json.loads((home / 'station.json').read_text())['ship'] == 'rio-grande'
    assert not (home / 'access-request.json').exists() and not (home / 'invitation.txt').exists()


def test_denied_request_stops(docking):
    app, clients, users, clock, make, opened, home = docking
    fields = {'name': 'Mallory', 'contact': 'm@example.org', 'note': ''}
    dock = make('raider')
    dock.step(fields)
    request = json.loads((home / 'access-request.json').read_text())
    clients[2].post(f'/api/access-requests/{request["id"]}/deny', json={})
    assert dock.step(fields) == 'denied' and dock.run(fields, wait=0) == 1


def test_expired_code_restarts_and_a_revoked_key_docks_again(docking):
    app, clients, users, clock, make, opened, home = docking
    dock = make('serenity')
    dock.step()
    first = json.loads((home / 'docking.json').read_text())
    clock[0] += 601
    assert dock.step() == 'waiting-for-confirm'
    second = json.loads((home / 'docking.json').read_text())
    assert second['id'] != first['id']
    clients[0].post(f'/api/dockings/{second["id"]}/confirm', json={'code': second['code']})
    assert dock.step() == 'docked'
    ship_id = json.loads((home / 'station.json').read_text())['ship_id']
    clients[0].post(f'/api/ships/{ship_id}/revoke', json={})
    assert dock.step() == 'waiting-for-confirm' and not (home / 'station.json').exists()
