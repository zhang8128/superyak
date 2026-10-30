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
    assert receipts.status_code == 200 and receipts.json()['before'] is None
    [receipt] = receipts.json()['receipts']
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
    [ended] = andy.get('/api/admin/connected-apps').json()
    assert ended['ended'] == {'at': connected.clock[0]}  # when, never why: that is the person's to see (S4)


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
    [receipt] = sam(connected).get('/api/connected-apps/grant-gone/receipts').json()['receipts']
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


# ---- the section 2's round (M1, S1 to S5, the nits) ----

def gone_connection(connected):
    """A connection a restore removed, built as production leaves one: a real call wrote its receipt, then the grant row
    went (the fixture lesson: rows in production's own shape)."""
    read(connected)
    with connected.store.transaction() as db:
        grant = db.execute('SELECT grant_id FROM connector_reads').fetchone()[0]
        db.execute('DELETE FROM connector_tokens WHERE grant_id=?', (grant,))
        db.execute('DELETE FROM connector_grants WHERE id=?', (grant,))
    return grant


def test_a_damaged_connection_row_never_breaks_the_lists(connected):
    """M1: one row a restore left damaged (a room set that isn't JSON, an end that isn't a finite number) made the person's
    list and every admin's answer 500, so no one could find another connection to revoke."""
    andy = admin(connected)
    ids = [sam(connected).get('/api/connected-apps').json()[0]['id']]
    for state in ('st-2', 'st-3'):
        client, code = allowed(connected, state=state)
        exchange(connected, client, code)
    with connected.store.transaction() as db:
        ids = [r[0] for r in db.execute('SELECT id FROM connector_grants ORDER BY rowid')]
        db.execute("UPDATE connector_grants SET rooms='not json' WHERE id=?", (ids[0],))
        db.execute('UPDATE connector_grants SET ends=? WHERE id=?', (float('inf'), ids[1]))
        db.execute("UPDATE connector_grants SET ends='soon' WHERE id=?", (ids[2],))
    listed = sam(connected).get('/api/connected-apps')
    assert listed.status_code == 200
    apps = {app['id']: app for app in listed.json()}
    assert apps[ids[0]]['damaged'] is True and apps[ids[0]]['rooms'] == []
    assert apps[ids[1]]['ends'] is None and apps[ids[2]]['ends'] is None
    assert apps[ids[2]]['ended'] == {'at': None, 'why': 'damaged'} and apps[ids[1]]['ended']['why'] == 'damaged'
    assert andy.get('/api/admin/connected-apps').status_code == 200
    assert sam(connected).post(f'/api/connected-apps/{ids[2]}/revoke').status_code == 409  # never a 500
    assert sam(connected).post(f'/api/connected-apps/{ids[0]}/revoke').status_code == 200  # a live one still ends


def test_receipts_are_paged_newest_first(connected):
    """S1: a connection at its limit for 30 days has 60,000 receipts; the page holds at most `limit` (100 by default),
    and `before` reads on."""
    for _ in range(5):
        read(connected)
        connected.clock[0] += 2
    [app] = sam(connected).get('/api/connected-apps').json()
    seen, before = [], None
    while True:
        query = '?limit=2' + (f'&before={before}' if before is not None else '')
        page = sam(connected).get(f"/api/connected-apps/{app['id']}/receipts{query}").json()
        assert len(page['receipts']) <= 2
        seen += [receipt['at'] for receipt in page['receipts']]
        before = page['before']
        if before is None:
            break
    assert len(seen) == 5 and seen == sorted(seen, reverse=True)
    for bad in ('limit=0', 'limit=501', 'limit=x', 'before=x', 'before=-1', 'before=' + 'y' * 100):
        assert sam(connected).get(f"/api/connected-apps/{app['id']}/receipts?{bad}").status_code == 400, bad


def test_a_replaced_room_already_shared_can_stay_while_narrowing(connected):
    """S2: Care plan continues in a newer room, and the grant still reads the old one; dropping Lab notes while keeping
    it was refused, leaving only a wider choice."""
    andy = person(connected, 'andy@example.org', 'Andy Example')
    connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [connected.rooms[0]]}).status_code == 200
    assert read(connected).json()['result']['isError'] is False
    assert read(connected, connected.rooms[1]).json()['result']['isError'] is True


def test_an_earlier_room_not_already_shared_cant_be_added(connected):
    """m7: S2 keeps a replaced room the grant already has; it never adds one."""
    andy = person(connected, 'andy@example.org', 'Andy Example')
    diary = connected.store.create_room(connected.person['id'], 'Diary', [])['id']
    later = connected.store.add_participants(connected.person['id'], diary, [andy['id']])['id']
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [diary]}).status_code == 400
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [later]}).status_code == 200


def test_a_marked_room_is_never_offered_and_says_so(connected):
    """S3 and N7: a newer room someone marked isn't offered, a listed room shows its mark, and adding a marked room is
    refused in words of its own."""
    andy = person(connected, 'andy@example.org', 'Andy Example')
    later = connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])['id']
    connected.store.mark_room(andy['id'], later)
    connected.store.mark_room(connected.person['id'], connected.rooms[1])
    [app] = sam(connected).get('/api/connected-apps').json()
    rooms = {room['room']: room for room in app['rooms']}
    assert rooms[connected.rooms[0]]['continues_in'] is None and rooms[connected.rooms[0]]['cloud'] is False
    assert rooms[connected.rooms[1]]['cloud'] is True
    refused = sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [later]})
    assert refused.status_code == 400 and 'cloud' in refused.json()['error'].lower()


def test_a_left_room_shows_no_title(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    theirs = connected.store.create_room(andy['id'], 'Secret plan', [connected.person['id']])['id']
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [theirs]}).status_code == 200
    assert read(connected, theirs).json()['result']['isError'] is False
    later = connected.store.add_participants(andy['id'], theirs, [person(connected, 'kim@example.org', 'Kim')['id']])['id']
    connected.store.remove_participant(andy['id'], later, connected.person['id'])
    [app] = sam(connected).get('/api/connected-apps').json()
    [receipt] = sam(connected).get(f"/api/connected-apps/{app['id']}/receipts").json()['receipts']
    assert 'Secret plan' not in json.dumps(app) and 'Secret plan' not in json.dumps(receipt)


def test_another_person_never_lists_a_gone_connection(connected):
    gone_connection(connected)
    person(connected, 'pat@example.org', 'Pat Example')
    assert browser(connected, 'pat@example.org').get('/api/connected-apps').json() == []
    assert any(app['ended'] == {'at': None, 'why': 'restore'} for app in sam(connected).get('/api/connected-apps').json())


def test_only_a_super_admin_ends_another_persons_connection(connected):
    [app] = sam(connected).get('/api/connected-apps').json()
    connected.store.create_user('lee', 'Lee', 'long-password-lee', is_admin=True)  # an admin, not a super admin
    lee = browser(connected, 'lee', 'long-password-lee')
    person(connected, 'pat@example.org', 'Pat Example')
    pat = browser(connected, 'pat@example.org')
    assert lee.get('/api/admin/connected-apps').status_code == 403
    for who in (lee, pat):
        assert who.post(f"/api/admin/connected-apps/{app['id']}/revoke").status_code == 403
    assert read(connected).status_code == 200


def test_a_reason_nobody_recorded_reads_unknown(connected):
    """N1: a connection revoked with no reason (before 9a, or carried as NULL) isn't said to be a restore's."""
    with connected.store.transaction() as db:
        db.execute('UPDATE connector_grants SET revoked=?', (connected.clock[0],))
    assert sam(connected).get('/api/connected-apps').json()[0]['ended']['why'] == 'unknown'


def test_last_used_is_the_newest_receipt_when_that_is_later(connected):
    """N4: after a restore the grant's last_used is the copy's, older than the receipts the page shows."""
    read(connected)
    with connected.store.transaction() as db:
        db.execute('UPDATE connector_grants SET last_used=0')
    assert sam(connected).get('/api/connected-apps').json()[0]['last_used'] == connected.clock[0]


# ---- the re-check's S6, T1, T2, N10 and N11 ----

def test_the_cursor_tells_a_person_nothing_of_anyone_else(connected):
    """S6: the cursor was the table's rowid, a counter the whole home shares, so its gaps counted other people's calls.
    It is the person's own receipt's random id, found only inside this connection's and this person's receipts."""
    person(connected, 'pat@example.org', 'Pat Example')
    pat_client, pat_code = allowed(connected, state='st-pat')  # a second connection, then made Pat's
    pat = exchange(connected, pat_client, pat_code).json()['access_token']
    with connected.store.transaction() as db:
        pat_id = db.execute("SELECT id FROM users WHERE username='pat@example.org'").fetchone()[0]
        db.execute('UPDATE connector_grants SET person_id=? WHERE id=(SELECT grant_id FROM connector_tokens WHERE '
                   "kind='access' ORDER BY rowid DESC LIMIT 1)", (pat_id,))
    for _ in range(3):
        read(connected)
        for _ in range(5):  # Pat's calls between each of Sam's
            mcp(connected, rpc('tools/call', {'name': 'rooms', 'arguments': {}}), pat)
        connected.clock[0] += 2
    [app] = [a for a in sam(connected).get('/api/connected-apps').json() if a['ended'] is None]
    with connected.store.transaction() as db:
        mine = {r[0] for r in db.execute('SELECT id FROM connector_reads WHERE grant_id=?', (app['id'],))}
        theirs = db.execute('SELECT id FROM connector_reads WHERE grant_id!=? LIMIT 1', (app['id'],)).fetchone()[0]
    cursor, cursors = None, []
    for _ in range(5):
        page = sam(connected).get(f"/api/connected-apps/{app['id']}/receipts?limit=1" + (f'&before={cursor}' if cursor else '')).json()
        cursor = page['before']
        if cursor is None:
            break
        cursors.append(cursor)
    assert cursor is None and len(set(cursors)) == 2 and set(cursors) <= mine  # its own receipts' ids, no one's count
    assert sam(connected).get(f"/api/connected-apps/{app['id']}/receipts?before={theirs}").status_code == 400


def test_each_connection_pages_only_its_own_receipts(connected):
    """T1: one person's two connections, each read once: each page holds only its own receipt."""
    client, code = allowed(connected, state='st-second')
    second = exchange(connected, client, code).json()['access_token']
    read(connected)
    mcp(connected, rpc('tools/call', {'name': 'rooms', 'arguments': {}}), second)
    apps = sam(connected).get('/api/connected-apps').json()
    assert len(apps) == 2
    tools = sorted(sam(connected).get(f"/api/connected-apps/{app['id']}/receipts").json()['receipts'][0]['tool'] for app in apps)
    assert tools == ['read_room', 'rooms'] and all(
        len(sam(connected).get(f"/api/connected-apps/{app['id']}/receipts").json()['receipts']) == 1 for app in apps)
    with connected.store.transaction() as db:  # a cursor from one connection is no cursor for the other
        other = db.execute('SELECT id FROM connector_reads WHERE grant_id=?', (apps[0]['id'],)).fetchone()[0]
    assert sam(connected).get(f"/api/connected-apps/{apps[1]['id']}/receipts?before={other}").status_code == 400


def test_a_kept_room_the_person_left_cant_stay(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    theirs = connected.store.create_room(andy['id'], 'Shared', [connected.person['id']])['id']
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [theirs, connected.rooms[1]]}).status_code == 200
    connected.store.remove_participant(andy['id'], theirs, connected.person['id'])
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [theirs]}).status_code == 400


def test_a_kept_earlier_room_marked_later_is_refused_in_its_words(connected):
    andy = person(connected, 'andy@example.org', 'Andy Example')
    later = connected.store.add_participants(connected.person['id'], connected.rooms[0], [andy['id']])['id']
    [app] = sam(connected).get('/api/connected-apps').json()
    assert sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [connected.rooms[0]]}).status_code == 200
    marked = connected.store.mark_room(connected.person['id'], later, earlier=True)['marked']
    assert connected.rooms[0] in marked
    again = sam(connected).put(f"/api/connected-apps/{app['id']}/rooms", json={'rooms': [connected.rooms[0]]})
    assert again.status_code == 400 and 'cloud' in again.json()['error']
    assert read(connected).json()['result']['isError'] is True


def test_identity_comes_before_the_page_arguments(connected):
    """N10: no session and a bad limit or cursor is 401, as on every other route, not the page's 400."""
    [app] = sam(connected).get('/api/connected-apps').json()
    anonymous = TestClient(connected.app, base_url='http://testserver', headers={'origin': 'http://testserver'})
    for bad in ('limit=x', 'before=%25'):
        assert anonymous.get(f"/api/connected-apps/{app['id']}/receipts?{bad}").status_code == 401


def test_a_damaged_receipt_never_breaks_its_page(connected):
    """N11: a receipt a restore carried over damaged (an inf size, a refusal's why that is a number) 500ed the page."""
    read(connected)
    [app] = sam(connected).get('/api/connected-apps').json()
    with connected.store.transaction() as db:
        db.execute('INSERT INTO connector_reads VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('r-bad', app['id'], connected.person['id'], 'claude.ai', connected.clock[0], b'\xff', '[]',
                    json.dumps([{'room': connected.rooms[0], 'why': 1}]).replace('1}', 'Infinity}'), float('inf'), b'\xfe'))
    page = sam(connected).get(f"/api/connected-apps/{app['id']}/receipts")
    assert page.status_code == 200
    bad = next(r for r in page.json()['receipts'] if r['size'] is None)
    assert bad['rooms_refused'][0]['why'] is None and bad['tool'] is None and bad['outcome'] is None

