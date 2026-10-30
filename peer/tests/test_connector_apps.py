"""Remote connector, Task 9a: Connected apps, the admins' view, the new-connection notice and why each ended (spec
"Receipts and revoking"; board build:connector-revoke-reason)."""
import json

from fastapi.testclient import TestClient
from connector_support import (RESOURCE_URL, allowed, connected, exchange, home, mcp, person, refresh,  # noqa: F401
                               rpc)

WEEK = 7 * 86400


def browser(home, username, password=None):
    """A signed-in browser on the home's own origin, with its CSRF token for writes."""
    client = TestClient(home.app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    signed = client.post('/api/login', json={'username': username,
                                             'password': password or 'long-password-' + username.split('@')[0]})
    assert signed.status_code == 200, signed.text
    client.headers['x-csrf-token'] = signed.json()['csrf_token']
    return client


def sam(connected):
    return browser(connected, 'sam@example.org')


def admin(connected):
    andy = connected.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    with connected.store.transaction() as db:
        db.execute('UPDATE users SET is_super_admin=1 WHERE id=?', (andy['id'],))
    return browser(connected, 'andy', 'long-password-andy')


def read(connected, room=None):
    room = room or connected.rooms[0]
    return mcp(connected, rpc('tools/call', {'name': 'read_room', 'arguments': {'room': room}}),
               connected.tokens['access_token'])


def test_connected_apps_lists_each_connection_with_its_rooms(connected):
    listed = sam(connected).get('/api/connected-apps')
    assert listed.status_code == 200
    [app] = listed.json()
    assert set(app) == {'id', 'app', 'created', 'last_used', 'ends', 'rooms', 'all_rooms', 'ended', 'usable'}
    assert app['app'] == 'claude.ai' and app['all_rooms'] is False and app['ended'] is None and app['usable'] is True
    assert [(r['room'], r['title'], r['continues_in']) for r in app['rooms']] == [
        (connected.rooms[0], 'Care plan', None), (connected.rooms[1], 'Lab notes', None)]
    assert app['last_used'] is None
    read(connected)
    assert sam(connected).get('/api/connected-apps').json()[0]['last_used'] == connected.clock[0]


def test_revoke_ends_access_at_once(connected):
    """Spec: Revoke ends it at once; its access and refresh tokens stop working, and the next /mcp call gets 401."""
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).post(f"/api/connected-apps/{app['id']}/revoke").status_code == 200
    assert read(connected).status_code == 401
    assert refresh(connected, connected.client, connected.tokens['refresh_token']).json() == {'error': 'invalid_grant'}
    [ended] = sam(connected).get('/api/connected-apps').json()
    assert ended['ended'] == {'at': connected.clock[0], 'why': 'you'} and ended['usable'] is False


def test_changing_rooms_takes_effect_on_the_next_call(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    changed = sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [connected.rooms[1]]})
    assert changed.status_code == 200, changed.text
    assert read(connected).json()['result']['isError'] is True  # Care plan is no longer shared
    assert read(connected, connected.rooms[1]).json()['result']['isError'] is False
    for bad in ([], ['nope'], 'all', None, [connected.rooms[1], connected.rooms[1]]):
        assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': bad}).status_code == 400, bad
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': '*'}).json()['all_rooms'] is True


def test_a_marked_room_cant_be_added(connected):
    connected.store.mark_room(connected.person['id'], connected.rooms[1])
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [connected.rooms[1]]}).status_code == 400


def test_a_continued_room_is_offered_not_added(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    later = connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])['id']
    [app] = sam(connected).get('/api/connected-apps').json()
    first = next(r for r in app['rooms'] if r['room'] == connected.rooms[0])
    assert first['continues_in'] == {'room': later, 'title': 'Care plan'}
    assert read(connected, later).json()['result']['isError'] is True  # offered, not added


def test_the_receipts_are_the_persons_own(connected):
    read(connected)
    [app] = sam(connected).get('/api/connected-apps').json()
    receipts = sam(connected).get(f"/api/connected-apps/{app['id']}/receipts")
    assert receipts.status_code == 200
    [receipt] = receipts.json()
    assert set(receipt) == {'at', 'tool', 'rooms_read', 'rooms_refused', 'size', 'outcome'}
    assert receipt['rooms_read'] == [{'room': connected.rooms[0], 'title': 'Care plan'}]  # titles resolved, never stored


def test_another_person_cant_see_or_revoke_my_connection(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    person(connected, 'pat@example.org', 'Pat Example')
    pat = browser(connected, 'pat@example.org')
    assert pat.get('/api/connected-apps').json() == []
    for answer in (pat.get(f"/api/connected-apps/{app['id']}/receipts"), pat.post(f"/api/connected-apps/{app['id']}/revoke"),
                   pat.put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': '*'})):
        assert answer.status_code == 404, answer.text
    assert read(connected).status_code == 200


def test_admins_see_connections_but_never_rooms_or_receipts(connected):
    andy = admin(connected)
    [item] = andy.get('/api/admin/connected-apps').json()
    assert set(item) == {'id', 'person', 'app', 'created', 'last_used', 'ends', 'ended'}
    assert item['person'] == 'Sam Example' and 'sam@example.org' not in json.dumps(item)
    assert andy.get(f"/api/connected-apps/{item['id']}/receipts").status_code == 404
    assert andy.post(f"/api/admin/connected-apps/{item['id']}/revoke").status_code == 200
    assert read(connected).status_code == 401
    assert sam(connected).get('/api/connected-apps').json()[0]['ended']['why'] == 'admin'
    assert sam(connected).get('/api/admin/connected-apps').status_code == 403  # a person who isn't one


def test_the_notice_shows_for_7_days(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).get('/api/connected-apps/notice').json() == {'id': app['id'], 'app': 'claude.ai',
                                                                       'created': app['created']}
    connected.clock[0] += WEEK + 1
    assert sam(connected).get('/api/connected-apps/notice').json() is None


def test_a_revoked_connection_shows_no_notice(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    sam(connected).post(f"/api/connected-apps/{app['id']}/revoke")
    assert sam(connected).get('/api/connected-apps/notice').json() is None


def test_each_way_a_connection_ends_is_named(connected):
    """build:connector-revoke-reason: the first week's revokes are read by their reason (spec "Measure")."""
    def why():
        with connected.store.transaction() as db:
            return [r[0] for r in db.execute('SELECT revoked_why FROM connector_grants ORDER BY created, rowid')]
    refresh(connected, connected.client, connected.tokens['refresh_token'])
    connected.clock[0] += 61
    refresh(connected, connected.client, connected.tokens['refresh_token'])  # used 61 s ago: a late reuse
    assert why() == ['refresh_reused']
    client, code = allowed(connected, state='st-two')
    first = exchange(connected, client, code).json()
    assert exchange(connected, client, code).json() == {'error': 'invalid_grant'}  # the code again
    assert why() == ['refresh_reused', 'code_reused']
    client, code = allowed(connected, state='st-three')
    third = exchange(connected, client, code).json()
    successor = refresh(connected, client, third['refresh_token']).json()
    refresh(connected, client, third['refresh_token'])  # within the window: the successor is rotated out
    refresh(connected, client, successor['refresh_token'])  # presented: a split chain
    assert why() == ['refresh_reused', 'code_reused', 'split_chain']
    assert first


def test_a_ship_key_cant_use_connected_apps(connected):
    andy = connected.store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    started = connected.store.start_docking('serenity', 'test-host')
    connected.store.confirm_docking(andy['id'], started['id'], started['code'])
    key = connected.store.docking_status(started['id'], started['secret'])['key']
    ship = TestClient(connected.app, base_url='http://testserver',
                      headers={'origin': 'http://testserver', 'authorization': f'Bearer {key}'})
    assert ship.get('/api/connected-apps').status_code == 403


def test_a_connection_a_restore_removed_still_shows_its_receipts(connected):
    """Rio Grande and Tardis, on Task 8's restore design: a receipt names its person and app, so a connection a restore
    removed is listed by its receipts as ended by the restore, and what it read stays visible."""
    with connected.store.transaction() as db:
        db.execute('INSERT INTO connector_reads VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('r-gone', 'grant-gone', connected.person['id'], 'claude.ai', connected.clock[0] - 50, 'read_room',
                    json.dumps([connected.rooms[0]]), '[]', 10, 'ok'))
    gone = next(app for app in sam(connected).get('/api/connected-apps').json() if app['id'] == 'grant-gone')
    assert gone['ended'] == {'at': None, 'why': 'restore'} and gone['usable'] is False and gone['app'] == 'claude.ai'
    [receipt] = sam(connected).get('/api/connected-apps/grant-gone/receipts').json()
    assert receipt['rooms_read'] == [{'room': connected.rooms[0], 'title': 'Care plan'}]
    person(connected, 'pat@example.org', 'Pat Example')
    assert browser(connected, 'pat@example.org').get('/api/connected-apps/grant-gone/receipts').status_code == 404


def test_a_connection_that_ran_to_its_end_says_so(connected):
    connected.clock[0] += 31 * 86400
    [app] = sam(connected).get('/api/connected-apps').json()
    assert app['ended'] == {'at': app['ends'], 'why': 'ended'} and app['usable'] is False
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': '*'}).status_code == 409


def test_no_hostile_input_is_a_500(connected):
    """The hostile-input pass (Serenity's review change) over every field these routes take."""
    [app] = sam(connected).get('/api/connected-apps').json()
    client, bad = sam(connected), []
    for key in ('', 'x' * 500, '%00', '..', 'a:b', app['id'] + chr(0x202e)):
        for method, path, payload in (('get', f'/api/connected-apps/{key}/receipts', None),
                                      ('post', f'/api/connected-apps/{key}/revoke', None),
                                      ('put', f'/api/connected-apps/{key}/rooms', {'rooms': '*'})):
            answer = getattr(client, method)(path, **({'json': payload} if payload is not None else {}))
            if answer.status_code >= 500:
                bad.append((method, repr(key)[:20], answer.status_code))
    for rooms in ([], {}, True, None, 1.5, 10 ** 30, 'x' * 10000, [[]], [{}], [None], ['a'] * 1000):
        answer = client.put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': rooms})
        if answer.status_code >= 500:
            bad.append(('rooms', repr(rooms)[:20], answer.status_code))
    for raw in (b'[]', b'"x"', b'null', b'{"rooms": "*"'):
        answer = client.put(f"/api/connected-apps/{app['id']}/rooms", content=raw, headers={'content-type': 'application/json'})
        if answer.status_code >= 500:
            bad.append(('raw', raw, answer.status_code))
    assert bad == []


def test_a_live_connection_without_a_usable_token_says_so(connected):
    """After a restore took its tokens back, a connection can stay live with none left (Rio Grande's restore case): it
    shows as not usable, so the person connects again."""
    with connected.store.transaction() as db:
        db.execute('DELETE FROM connector_tokens')
    [app] = sam(connected).get('/api/connected-apps').json()
    assert app['ended'] is None and app['usable'] is False


def test_a_store_from_before_9a_gains_the_reason_column(tmp_path):
    from superyak_peer.db import Store
    import sqlite3
    from contextlib import closing
    store = Store(tmp_path / 'old')
    with closing(sqlite3.connect(store.db_path)) as db:
        db.execute('ALTER TABLE connector_grants DROP COLUMN revoked_why')
        db.commit()
    again = Store(tmp_path / 'old')
    with again.transaction() as db:
        assert 'revoked_why' in {row['name'] for row in db.execute('PRAGMA table_info(connector_grants)')}



def test_an_ended_connection_cant_be_revoked_again(connected):
    """Tardis's nit: revoking a connection that already ran to its end wrote "ended by you" over "ended". An ended one,
    by any way, answers 409 and its record stays as it was."""
    [app] = sam(connected).get('/api/connected-apps').json()
    connected.clock[0] += 31 * 86400
    assert sam(connected).post(f"/api/connected-apps/{app['id']}/revoke").status_code == 409
    andy = admin(connected)
    assert andy.post(f"/api/admin/connected-apps/{app['id']}/revoke").status_code == 409
    assert sam(connected).get('/api/connected-apps').json()[0]['ended']['why'] == 'ended'
    with connected.store.transaction() as db:
        assert db.execute('SELECT revoked, revoked_why FROM connector_grants').fetchone()[:] == (None, None)


def test_a_revoked_connection_revoked_again_keeps_who_ended_it(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).post(f"/api/connected-apps/{app['id']}/revoke").status_code == 200
    assert admin(connected).post(f"/api/admin/connected-apps/{app['id']}/revoke").status_code == 409
    assert sam(connected).get('/api/connected-apps').json()[0]['ended']['why'] == 'you'
