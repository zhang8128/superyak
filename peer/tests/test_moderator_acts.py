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
