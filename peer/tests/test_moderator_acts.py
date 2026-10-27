"""Room moderators: what a moderator can and can't do (spec §2, §3; T2, T2a, T3, T5, T6, T11)."""
import pytest
from superyak_peer.grants import _utc
from test_member_changes import rows
from test_moderate_grants import (city, charge, grant_row, login, moderate, notices, remote_contact,  # noqa: F401
                                  validity)
from test_station_cli import race

NOT_A_MODERATOR = "Only the room's owner or one of its moderators can change its members"


def add(client, room, member, **extra):
    return client.post(f'/api/chats/{room}/participants', json={'member_ids': [member], **extra})


def drop(client, room, member, **query):
    return client.delete(f'/api/chats/{room}/participants/{member}', params=query)


def snapshot(store):
    with store.transaction() as db:
        return [[tuple(r) for r in db.execute(q)] for q in (
            'SELECT * FROM member_changes ORDER BY id', 'SELECT * FROM room_members ORDER BY room_id, user_id',
            'SELECT id, revoked FROM grants ORDER BY id', 'SELECT count(*) FROM messages', 'SELECT count(*) FROM rooms')]


def test_a_moderators_add_makes_the_owners_new_room_and_says_who(city):
    c = city
    c.store.save_brief(c.andy['id'], c.room, 'City of AI: law only.', 0)
    for key in ('spec:a', 'spec:b'):
        c.store.post_item(c.andy['id'], c.room, key, 'City work', 'spec')
    c.store.claim(c.rio['id'], c.room, 'spec:a')
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    added = add(login(c.app, 'jenn'), c.room, c.tardis['id'], carry_brief=0)  # R-S3: ignored, the brief comes anyway
    assert added.status_code == 201, added.text
    new = added.json()
    assert (new['owner_id'], new['title'], new['linked_room_id'], new['brief_carried'], new['board_carried'], new['bridged']) == (
        c.andy['id'], 'Superyak: city of AI', c.room, True, 2, False)
    assert set(new['member_ids']) == {c.andy['id'], c.jenn['id'], c.doctor['id'], c.rio['id'], c.odo['id'], c.tardis['id']}
    brief = c.store.get_room(c.tardis['id'], new['id'])['brief']
    assert (brief['body'], brief['carried_from'], brief['author_id']) == ('City of AI: law only.', c.room, c.andy['id'])
    assert c.store.room_board(c.tardis['id'], new['id'])[0]['claim']['holder_id'] == c.rio['id']
    [row] = rows(c.store)
    assert (row['grant_id'], row['actor_id'], row['member_id'], row['new_room_id']) == (grant, c.jenn['id'], c.tardis['id'], new['id'])
    assert notices(c.store, new['id'], 'member-') == [
        (f'member-{row["id"]}', f'Jenn, a moderator, added Tardis to this room. It continues room {c.room[:6]}.')]
    view = next(g for g in login(c.app, 'jenn').get('/api/grants').json() if g['id'] == grant)
    assert (view['budget_left'], view['valid'], view['rooms'][0]['current']['id']) == (9, True, new['id'])


def test_a_brief_saved_between_the_read_and_the_add_gives_409_and_writes_nothing(city, monkeypatch):
    c = city
    c.store.save_brief(c.andy['id'], c.room, 'Plan.', 0)
    moderate(c.store, c.andy, c.jenn, c.room)
    jenn, before = login(c.app, 'jenn'), snapshot(c.store)
    race(monkeypatch, lambda store, db, room: store._write_brief(db, room['id'], 'Plan, changed.', 2, room['owner_id']))
    refused = add(jenn, c.room, c.tardis['id'])
    assert (refused.status_code, refused.json()['error']) == (409, 'The room brief changed while adding the member; run station_add_member again')
    assert snapshot(c.store) == before and c.store.get_room(c.andy['id'], c.room)['brief']['body'] == 'Plan.'


def test_adding_a_current_member_charges_and_posts_nothing(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    before = snapshot(c.store)
    refused = add(login(c.app, 'jenn'), c.room, c.rio['id'])
    assert (refused.status_code, refused.json()['error']) == (409, f'Rio Grande is already a member of room {c.room[:6]}; nothing changed')
    assert snapshot(c.store) == before and validity(c.store, grant) == (True, None)


@pytest.mark.parametrize('case, status, error', [
    ('blank', 400, 'Name the member to add'),
    ('wormhole', 403, "Adding wormhole bridges the room to Stanley's aDNA lattice; only the room's owner bridges it (make station-bridge)"),
    ('nobody', 404, '{typed} is not someone a moderator can add'),
    ('system', 404, '{typed} is not someone a moderator can add'),
    ('pending', 404, '{typed} is not someone a moderator can add'),
    ('remote', 404, '{typed} is not someone a moderator can add'),
    ('odo', 403, 'Odo is a station ship with no owner; a moderator never adds or removes it'),
    ('kestrel', 403, "Kestrel is not one of Andy's ships"),
    ('removed', 403, 'Andy removed Doctor from this room; only he can add them back'),
    ('two', 400, 'A moderator changes one member at a time'),
])
def test_a_moderators_add_refuses_each_member_and_writes_nothing(city, case, status, error):
    c, store = city, city.store
    moderate(store, c.andy, c.jenn, c.room)
    with store.transaction() as db:
        system = store.system_author_id(db)
    if case == 'removed':
        store.remove_participant(c.andy['id'], c.room, c.doctor['id'])
    members = {'blank': [''], 'wormhole': [c.wormhole['id']], 'nobody': ['nobody'], 'system': [system],
               'pending': [c.pending['id']], 'remote': [remote_contact(store)], 'odo': [c.odo['id']],
               'kestrel': [c.kestrel['id']], 'removed': [c.doctor['id']], 'two': [c.tardis['id'], c.kestrel['id']]}[case]
    jenn, before = login(c.app, 'jenn'), snapshot(store)
    refused = jenn.post(f'/api/chats/{c.room}/participants', json={'member_ids': members})
    assert (refused.status_code, refused.json()['error']) == (status, error.format(typed=members[0]))
    assert snapshot(store) == before


@pytest.mark.parametrize('case', ['replaced', 'none', 'direct', 'elsewhere', 'named', 'remove-only', 'expired', 'revoked', 'spent'])
def test_a_moderators_add_is_refused_by_its_grant_and_writes_nothing(city, case):
    c, store, extra = city, city.store, {}
    if case == 'replaced':  # Review Focus 2: the old id after an add
        moderate(store, c.andy, c.jenn, c.room)
        store.add_participants(c.andy['id'], c.room, [c.kestrel['id']])
        expected = (409, 'This room was replaced by a newer linked room; add members there')
    elif case in ('none', 'direct', 'elsewhere', 'named'):
        if case == 'direct':  # T6: a direct grant never moderates
            with store.transaction() as db:
                store._insert_grant(db, c.andy['id'], c.jenn['id'], [c.rio['id']], [c.room], 24, 5)
        if case == 'elsewhere':
            moderate(store, c.andy, c.jenn, store.create_room(c.andy['id'], 'Ops', [c.jenn['id']])['id'])
        if case == 'named':  # another holder's grant, named: answered as if Jenn held none
            moderate(store, c.andy, c.jenn, c.room)
            extra = {'grant_id': moderate(store, c.andy, c.doctor, c.room)}
        expected = (403, NOT_A_MODERATOR)
    else:
        grant = moderate(store, c.andy, c.jenn, c.room, hours=1, budget=1,
                         actions=['remove_member'] if case == 'remove-only' else None)
        if case == 'expired':
            c.clock[0] += 3600
        if case == 'revoked':
            store.revoke_grant(c.andy['id'], grant)
        if case == 'spent':
            charge(store, grant, c.room, 5)
        short = f'#{grant[:4]}'
        expected = (403, {'remove-only': f"Grant {short} doesn't let you add members",
                          'expired': f'Grant {short} expired {_utc(grant_row(store, grant)["expires"])}',
                          'revoked': f'Grant {short} was revoked by Andy',
                          'spent': f'Grant {short} has used its 1 change for the last 24 hours'}[case])
    jenn, before = login(c.app, 'jenn'), snapshot(store)
    refused = jenn.post(f'/api/chats/{c.room}/participants', json={'member_ids': [c.tardis['id']], **extra})
    assert (refused.status_code, refused.json()['error']) == expected
    assert snapshot(store) == before


def test_without_grant_id_the_oldest_valid_grant_with_the_action_is_spent(city):
    c = city
    remove_only = moderate(c.store, c.andy, c.jenn, c.room, actions=['remove_member'])
    c.clock[0] += 1
    both = moderate(c.store, c.andy, c.jenn, c.room)
    jenn = login(c.app, 'jenn')
    named = add(jenn, c.room, c.tardis['id'], grant_id=remove_only)
    assert (named.status_code, named.json()['error']) == (403, f"Grant #{remove_only[:4]} doesn't let you add members")
    assert add(jenn, c.room, c.tardis['id']).status_code == 201 and rows(c.store)[-1]['grant_id'] == both


def test_only_the_owners_own_add_clears_his_removal(city):
    """S1, M7: the owner removed the doctor; a moderator can't add him back, and the owner's own add clears it."""
    c = city
    moderate(c.store, c.andy, c.jenn, c.room)
    c.store.remove_participant(c.andy['id'], c.room, c.doctor['id'])
    newer = c.store.add_participants(c.andy['id'], c.room, [c.doctor['id']])['id']
    with c.store.transaction() as db:
        assert c.store._owner_removed(db, newer, c.doctor['id'], c.andy['id']) is False


def test_moderating_adds_no_brief_or_grant_power(city):
    """M9: the brief's rules and G10 are unchanged for a moderator."""
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    jenn = login(c.app, 'jenn')
    saved = jenn.put(f'/api/chats/{c.room}/brief', json={'body': 'Mine now.', 'revision': 0})
    history = jenn.get(f'/api/chats/{c.room}/brief/revisions')
    revoked = jenn.post(f'/api/grants/{grant}/revoke', json={})
    assert [(r.status_code, r.json()['error']) for r in (saved, history, revoked)] == [
        (403, 'Only the room owner can change its brief'), (403, 'Only the room owner can read its brief history'),
        (403, 'Only its issuer or the owner of one of its ships can revoke this grant')]


def test_a_moderators_removal_takes_the_member_out_of_the_chain_and_says_who(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    newer = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])['id']
    removed = drop(login(c.app, 'jenn'), newer, c.doctor['id'])
    assert removed.status_code == 200, removed.text
    assert removed.json()['earlier_rooms'] == 1 and c.store.list_rooms(c.doctor['id']) == []
    row = rows(c.store)[-1]
    assert (row['change'], row['grant_id'], row['actor_id']) == ('remove', grant, c.jenn['id'])
    assert notices(c.store, newer)[-1] == (f'member-{row["id"]}', 'Jenn, a moderator, removed Doctor from this room and the room before it.')
    assert validity(c.store, grant) == (True, None)
    assert next(g for g in login(c.app, 'andy').get('/api/grants').json() if g['id'] == grant)['budget_left'] == 9


@pytest.mark.parametrize('case, status, error', [
    ('nobody', 404, '{typed} is not a member of this room'),
    ('system', 404, '{typed} is not a member of this room'),
    ('owner', 403, "A moderator can't remove the room's owner"),
    ('wormhole', 403, "Removing wormhole unbridges the room; only the room's owner does that (make station-unbridge)"),
    ('odo', 403, 'Odo is a station ship with no owner; a moderator never adds or removes it'),
    ('moderator', 403, 'Rio Grande moderates this room too; only Andy can remove a moderator'),
    ('remote', 403, 'Willa is on another station; only Andy manages them'),
])
def test_a_moderators_removal_refuses_each_member_and_writes_nothing(city, monkeypatch, case, status, error):
    c, store = city, city.store
    moderate(store, c.andy, c.jenn, c.room)
    moderate(store, c.andy, c.rio, c.room)
    contact = remote_contact(store)
    with store.transaction() as db:
        system = store.system_author_id(db)
        db.execute('INSERT INTO room_members VALUES(?,?)', (c.room, c.wormhole['id']))  # bridged by hand
        if case == 'remote':
            db.execute('INSERT INTO remote_room_members VALUES(?,?)', (c.room, contact))
    if case == 'remote':  # check 5 pauses every grant in such a room; this refusal is the defence behind it (M8)
        monkeypatch.setattr(type(store), '_grant_validity', lambda self, db, grant, budget=True: (True, None))
    typed = {'nobody': 'nobody', 'system': system, 'owner': c.andy['id'], 'wormhole': c.wormhole['id'],
             'odo': c.odo['id'], 'moderator': c.rio['id'], 'remote': contact}[case]
    jenn, before = login(c.app, 'jenn'), snapshot(store)
    refused = drop(jenn, c.room, typed)
    assert (refused.status_code, refused.json()['error']) == (status, error.format(typed=typed))
    assert snapshot(store) == before


def test_a_holder_whose_grant_expired_is_no_longer_a_moderator(city):
    """Ruling 5: the 403 and the moderators list agree; the removal still revokes the expired grant it finds."""
    c = city
    moderate(c.store, c.andy, c.jenn, c.room)
    old = moderate(c.store, c.andy, c.rio, c.room, hours=1)
    c.clock[0] += 3600
    assert drop(login(c.app, 'jenn'), c.room, c.rio['id']).status_code == 200
    assert grant_row(c.store, old)['revoke_reason'] == 'removed from the room'


def test_a_moderator_may_remove_itself_under_either_action_even_when_spent(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room, actions=['add_member'], budget=1)
    charge(c.store, grant, c.room, 5)
    assert drop(login(c.app, 'jenn'), c.room, c.jenn['id']).status_code == 200
    row = grant_row(c.store, grant)
    assert (row['revoked_by'], row['revoke_reason']) == (c.jenn['id'], 'removed from the room')
    assert notices(c.store, c.room)[-1][1] == "Jenn, a moderator, removed Jenn from this room. Jenn's moderate grant here is revoked."


def test_a_self_removed_moderator_added_back_by_another_keeps_its_grant_revoked(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    moderate(c.store, c.andy, c.doctor, c.room)
    assert drop(login(c.app, 'jenn'), c.room, c.jenn['id']).status_code == 200
    assert add(login(c.app, 'doctor'), c.room, c.jenn['id']).status_code == 201  # not the owner's removal: allowed
    assert validity(c.store, grant) == (False, f'Grant #{grant[:4]} was revoked by Jenn')


def test_a_removal_under_an_add_only_grant_is_refused_and_writes_nothing(city):
    """T3, the reverse of Task 5's remove-only case: only self-removal ignores the grant's actions (R-S4)."""
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room, actions=['add_member'])
    jenn, before = login(c.app, 'jenn'), snapshot(c.store)
    refused = drop(jenn, c.room, c.doctor['id'])
    assert (refused.status_code, refused.json()['error']) == (403, f"Grant #{grant[:4]} doesn't let you remove members")
    assert snapshot(c.store) == before


from test_instructions import ship_client


def test_a_ship_moderator_adds_and_removes_by_username_through_its_own_routes(city):
    c = city
    grant = moderate(c.store, c.andy, c.rio, c.room)
    rio = ship_client(c.app, c.rio_key)
    added = rio.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': 'tardis'})
    assert added.status_code == 201, added.text
    new = added.json()
    assert (new['added'][0]['username'], new['short'], new['owner_id']) == ('tardis', new['id'][:6], c.andy['id'])
    assert notices(c.store, new['id'], 'member-')[0][1] == f'Rio Grande, a moderator, added Tardis to this room. It continues room {c.room[:6]}.'
    removed = rio.delete(f'/api/ships/me/rooms/{new["id"]}/members/tardis')
    assert removed.status_code == 200 and removed.json()['removed']['username'] == 'tardis'
    assert [r['grant_id'] for r in rows(c.store)] == [grant, grant]


def test_the_ship_route_reads_the_member_as_people_write_it(city):
    """Review Focus 1 and 2."""
    c = city
    moderate(c.store, c.andy, c.rio, c.room)
    rio = ship_client(c.app, c.rio_key)
    added = rio.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': ' @Tardis '})
    assert added.status_code == 201 and added.json()['added'][0]['username'] == 'tardis'
    stale = rio.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': 'doctor'})
    assert (stale.status_code, stale.json()['error']) == (409, 'This room was replaced by a newer linked room; add members there')
    for blank in ('  ', None, 7):
        refused = rio.post(f'/api/ships/me/rooms/{added.json()["id"]}/members', json={'member': blank})
        assert (refused.status_code, refused.json()['error']) == (400, 'Name the member to add')


def test_each_member_route_takes_one_kind_of_caller(city):
    c = city
    jenn, rio = login(c.app, 'jenn'), ship_client(c.app, c.rio_key)
    for answer in (jenn.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': 'tardis'}),
                   jenn.delete(f'/api/ships/me/rooms/{c.room}/members/doctor')):
        assert (answer.status_code, answer.json()['error']) == (403, 'Only a ship key can use this route')
    for answer in (add(rio, c.room, c.tardis['id']), drop(rio, c.room, c.doctor['id'])):
        assert (answer.status_code, answer.json()['error']) == (403, 'Ship keys cannot use this route')
    refused = rio.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': 'tardis'})
    assert (refused.status_code, refused.json()['error']) == (403, NOT_A_MODERATOR)


def test_moderating_shows_only_the_callers_own_grant(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room, actions=['add_member'], budget=2)
    charge(c.store, grant, c.room, 5, 6)  # spent: still shown, with 0 left (ruling 14)

    def mark(client):
        return {r['id']: r.get('moderating') for r in client.get('/api/chats').json()}[c.room]
    assert mark(login(c.app, 'jenn')) == {'grant': f'#{grant[:4]}', 'actions': ['add_member'], 'budget_left': 0}
    rio = ship_client(c.app, c.rio_key)
    assert mark(login(c.app, 'doctor')) is None and mark(login(c.app, 'andy')) is None and mark(rio) is None
    mine = moderate(c.store, c.andy, c.rio, c.room)
    assert mark(rio) == {'grant': f'#{mine[:4]}', 'actions': ['add_member', 'remove_member'], 'budget_left': 10}
    with c.store.transaction() as db:  # check 5 pauses both grants (Andy no longer owns the room): Ruling 14 hides them
        db.execute('UPDATE rooms SET owner_id=? WHERE id=?', (c.doctor['id'], c.room))
    assert mark(login(c.app, 'jenn')) is None and mark(rio) is None
    with c.store.transaction() as db:
        db.execute('UPDATE rooms SET owner_id=? WHERE id=?', (c.andy['id'], c.room))
    assert mark(rio)['grant'] == f'#{mine[:4]}'


def test_the_room_lists_its_moderators_by_name_only(city):
    c = city
    jenn_grant = moderate(c.store, c.andy, c.jenn, c.room)
    moderate(c.store, c.andy, c.rio, c.room, hours=1)
    doctor = login(c.app, 'doctor')

    def listed():
        return doctor.get(f'/api/chats/{c.room}').json()['moderators']
    assert listed() == [{'id': c.jenn['id'], 'name': 'Jenn'}, {'id': c.rio['id'], 'name': 'Rio Grande'}]
    c.clock[0] += 3600
    assert listed() == [{'id': c.jenn['id'], 'name': 'Jenn'}]
    c.store.revoke_grant(c.andy['id'], jenn_grant)
    assert listed() == []


def test_the_room_lists_a_holder_once_however_many_grants_he_holds(city):
    c = city
    moderate(c.store, c.andy, c.rio, c.room, actions=['add_member'])
    moderate(c.store, c.andy, c.rio, c.room, actions=['remove_member'])
    assert login(c.app, 'doctor').get(f'/api/chats/{c.room}').json()['moderators'] == [{'id': c.rio['id'], 'name': 'Rio Grande'}]
    assert [m['id'] for m in c.store.get_room(c.andy['id'], c.room)['moderators']] == [c.rio['id']]


def test_the_grant_view_shows_its_changes_to_the_issuer_only(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    jenn, andy = login(c.app, 'jenn'), login(c.app, 'andy')
    new = add(jenn, c.room, c.tardis['id']).json()['id']
    assert drop(jenn, new, c.tardis['id']).status_code == 200

    def view(client):
        return next(g for g in client.get('/api/grants').json() if g['id'] == grant)
    changes = view(andy)['changes']
    assert [(ch['member']['name'], ch['change'], ch['room']['id'], ch['room']['title']) for ch in changes] == [
        ('Tardis', 'remove', new, 'Superyak: city of AI'), ('Tardis', 'add', c.room, 'Superyak: city of AI')]
    assert all(set(ch) == {'member', 'change', 'room', 'created'} for ch in changes) and 'changes' not in view(jenn)
    charge(c.store, grant, c.room, *range(10, 70))
    assert len(view(andy)['changes']) == 50


def test_the_ship_route_refuses_wormhole_early_and_writes_nothing(city):
    """Fixed texts: WORMHOLE_ADD, however the name is typed, before any lookup."""
    c = city
    moderate(c.store, c.andy, c.rio, c.room)
    rio = ship_client(c.app, c.rio_key)
    before = snapshot(c.store)
    for typed in ('wormhole', ' @Wormhole '):
        refused = rio.post(f'/api/ships/me/rooms/{c.room}/members', json={'member': typed})
        assert (refused.status_code, refused.json()['error']) == (403, (
            "Adding wormhole bridges the room to Stanley's aDNA lattice; only the room's owner bridges it (make station-bridge)"))
    assert snapshot(c.store) == before


def test_the_ship_route_removal_refusals_and_self_removal(city):
    """The ship route reads a username: wormhole by name, another moderator and a raw id are refused with nothing
    written; the ship's own removal of itself is allowed."""
    c = city
    bridged, _ = c.store.station_bridge('andy', c.room[:6], True)
    room = bridged['id']
    moderate(c.store, c.andy, c.rio, room)
    moderate(c.store, c.andy, c.jenn, room)
    rio = ship_client(c.app, c.rio_key)
    before = snapshot(c.store)

    def refused(member, status, error):
        answer = rio.delete(f'/api/ships/me/rooms/{room}/members/{member}')
        assert (answer.status_code, answer.json()['error']) == (status, error)
    refused('wormhole', 403, "Removing wormhole unbridges the room; only the room's owner does that (make station-unbridge)")
    refused('jenn', 403, 'Jenn moderates this room too; only Andy can remove a moderator')
    refused(c.doctor['id'], 404, f'{c.doctor["id"]} is not a member of this room')
    assert snapshot(c.store) == before
    mine = rio.delete(f'/api/ships/me/rooms/{room}/members/rio-grande')
    assert mine.status_code == 200 and mine.json()['removed']['username'] == 'rio-grande'
