"""Room moderators: one add and one removal for every path, each recorded and announced (M7's helper, M8, M14)."""
import pytest
from superyak_peer.common import Problem
from test_moderate_grants import city, login, moderate, notices, remote_contact  # noqa: F401  (city is a fixture)

BRIDGED = " This room is bridged to Stanley's aDNA lattice: posts that mention a lattice persona cross to it."


def rows(store):
    with store.transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM member_changes ORDER BY created, rowid')]


def test_the_owners_add_records_a_row_per_member_and_posts_one_notice(city):
    c = city
    added = login(c.app, 'andy').post(f'/api/chats/{c.room}/participants', json={'member_ids': [c.tardis['id'], c.kestrel['id']]})
    assert added.status_code == 201, added.text
    new = added.json()
    assert (new['short'], new['brief_carried'], new['board_carried'], new['bridged']) == (new['id'][:6], False, 0, False)
    assert [a['username'] for a in new['added']] == ['tardis', 'kestrel']
    logged = rows(c.store)
    assert [(r['change'], r['member_id'], r['actor_id'], r['grant_id'], r['room_id'], r['new_room_id']) for r in logged] == [
        ('add', c.tardis['id'], c.andy['id'], None, c.room, new['id']), ('add', c.kestrel['id'], c.andy['id'], None, c.room, new['id'])]
    assert notices(c.store, new['id']) == [(f'member-{logged[0]["id"]}', f'Andy added Tardis and Kestrel to this room. It continues room {c.room[:6]}.')]
    assert notices(c.store, c.room) == []


def test_an_add_to_a_bridged_room_and_the_bridge_itself_say_so(city):
    c = city
    bridged, changed = c.store.station_bridge('andy', c.room[:6], True)
    assert changed and notices(c.store, bridged['id']) == [
        (f'member-{rows(c.store)[0]["id"]}', f'Andy added Wormhole to this room. It continues room {c.room[:6]}.' + BRIDGED)]
    later = c.store.add_participants(c.andy['id'], bridged['id'], [c.tardis['id']])
    assert later['bridged'] is True
    assert notices(c.store, later['id'])[0][1] == f'Andy added Tardis to this room. It continues room {bridged["id"][:6]}.' + BRIDGED


def test_station_add_ship_posts_the_owners_notice(city):
    c = city
    new, name = c.store.station_add_ship('andy', c.room[:6], 'tardis')
    assert name == 'tardis' and notices(c.store, new['id'])[0][1] == f'Andy added Tardis to this room. It continues room {c.room[:6]}.'


def test_an_add_naming_no_one_new_is_refused_and_writes_nothing(city):
    c = city
    andy = login(c.app, 'andy')
    for member_ids in ([], [c.jenn['id']]):
        refused = andy.post(f'/api/chats/{c.room}/participants', json={'member_ids': member_ids})
        assert (refused.status_code, refused.json()['error']) == (409, f'Everyone named is already a member of room {c.room[:6]}; nothing changed')
    assert rows(c.store) == [] and len(c.store.list_rooms(c.andy['id'])) == 1


def test_a_name_with_an_at_sign_is_stored_as_at_and_mentions_no_one(city):
    """T6: a display name is people's text; the notice keeps it to one safe line."""
    c = city
    c.store.rename_user(c.tardis['id'], '@serenity')
    new = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])
    assert notices(c.store, new['id'])[0][1] == f'Andy added (at)serenity to this room. It continues room {c.room[:6]}.'
    with c.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM mentions').fetchone()[0] == 0


def test_a_non_owner_gets_403_and_a_replaced_room_answers_first(city):
    c = city
    doctor = login(c.app, 'doctor')
    refused = doctor.post(f'/api/chats/{c.room}/participants', json={'member_ids': [c.tardis['id']]})
    assert (refused.status_code, refused.json()['error']) == (403, "Only the room's owner or one of its moderators can change its members")
    c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])
    again = doctor.post(f'/api/chats/{c.room}/participants', json={'member_ids': [c.kestrel['id']]})
    assert (again.status_code, again.json()['error']) == (409, 'This room was replaced by a newer linked room; add members there')
