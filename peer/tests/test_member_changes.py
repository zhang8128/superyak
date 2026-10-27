"""Room moderators: one add and one removal for every path, each recorded and announced (M7's helper, M8, M14)."""
import pytest
from superyak_peer.common import Problem
from superyak_peer.identity import verify_record
from test_moderate_grants import city, grant_row, login, moderate, notices, remote_contact, validity  # noqa: F401  (city is a fixture)
from test_signatures import card_of

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


def chain(c):
    r1 = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])['id']
    return [c.room, r1, c.store.add_participants(c.andy['id'], r1, [c.kestrel['id']])['id']]


def epochs(store, keys):
    with store.transaction() as db:
        return [db.execute('SELECT epoch FROM rooms WHERE id=?', (key,)).fetchone()[0] for key in keys]


def test_a_removal_takes_the_member_out_of_every_room_of_the_chain(city):
    c = city
    rooms = chain(c)
    c.store.send_message(c.jenn['id'], c.room, 'old', 'Old words from Jenn')
    for key in ('spec:a', 'spec:b'):
        c.store.claim(c.jenn['id'], rooms[2], key)
    with c.store.transaction() as db:
        claim_lines = db.execute("SELECT count(*) FROM message_kinds WHERE kind='claim'").fetchone()[0]
    before = epochs(c.store, rooms)
    removed = login(c.app, 'andy').delete(f'/api/chats/{rooms[2]}/participants/{c.jenn["id"]}')
    assert removed.status_code == 200, removed.text
    got = removed.json()
    assert (got['id'], got['earlier_rooms'], got['claims_released'], got['grant_revoked'], got['removed']['username']) == (
        rooms[2], 2, 2, False, 'jenn')
    assert epochs(c.store, rooms) == [e + 1 for e in before] and len(c.store.list_rooms(c.andy['id'])) == 3
    for key in rooms:
        for act in (lambda: c.store.get_room(c.jenn['id'], key), lambda: c.store.send_message(c.jenn['id'], key, 'x', 'Still here?')):
            with pytest.raises(Problem) as gone:
                act()
            assert gone.value.status == 404
    assert 'Old words from Jenn' in [m['body'] for m in c.store.get_room(c.andy['id'], c.room)['messages']]
    with c.store.transaction() as db:
        assert db.execute("SELECT count(*) FROM message_kinds WHERE kind='claim'").fetchone()[0] == claim_lines  # silent
        assert {r[0] for r in db.execute('SELECT released_by FROM claims WHERE holder_id=?', (c.jenn['id'],))} == {c.andy['id']}
    row = rows(c.store)[-1]
    assert (row['change'], row['room_id'], row['earlier_rooms'], row['claims_released'], row['actor_id'], row['grant_id']) == (
        'remove', rooms[2], 2, 2, c.andy['id'], None)
    assert notices(c.store, rooms[2])[-1] == (f'member-{row["id"]}', 'Andy removed Jenn from this room and the 2 rooms before it. 2 claims were released.')
    assert notices(c.store, c.room) == [] and len(notices(c.store, rooms[1])) == 1  # earlier rooms get no removal notice


def test_a_removal_drops_the_ships_deferrals_in_those_rooms(city):
    c = city
    asked = c.store.send_message(c.jenn['id'], c.room, 'ask', '@rio-grande are you there?')
    with c.store.transaction() as db:
        db.execute('INSERT INTO deferrals(ship_id, message_id, first_deferred) VALUES(?,?,?)', (c.rio['id'], asked['id'], c.store.clock()))
    c.store.remove_participant(c.andy['id'], c.room, c.rio['id'])
    with c.store.transaction() as db:
        assert db.execute('SELECT count(*) FROM deferrals WHERE ship_id=?', (c.rio['id'],)).fetchone()[0] == 0
    assert notices(c.store, c.room)[-1][1] == 'Andy removed Rio Grande from this room.'


def test_an_account_left_only_in_earlier_rooms_is_taken_out_of_them(city):
    c = city
    rooms = chain(c)
    with c.store.transaction() as db:  # a removal made before merge 1 took Jenn out of the newest room only
        db.execute('DELETE FROM room_members WHERE room_id=? AND user_id=?', (rooms[2], c.jenn['id']))
    assert c.store.remove_participant(c.andy['id'], rooms[2], c.jenn['id'])['earlier_rooms'] == 2
    assert c.store.list_rooms(c.jenn['id']) == []
    assert notices(c.store, rooms[2])[-1][1] == 'Andy removed Jenn from the 2 rooms before this one.'


def test_the_owners_removal_of_a_moderator_revokes_the_grant_signed_for_good(city):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    assert c.store.remove_participant(c.andy['id'], c.room, c.jenn['id'])['grant_revoked'] is True
    row = grant_row(c.store, grant)
    assert (row['revoked_by'], row['revoke_reason']) == (c.andy['id'], 'removed from the room')
    with c.store.transaction() as db:
        assert verify_record(card_of(c.store._station_identity(db)), c.store._revocation_record(db, grant), row['revocation_signature'])
    assert notices(c.store, c.room)[-1][1] == "Andy removed Jenn from this room. Jenn's moderate grant here is revoked."
    c.store.add_participants(c.andy['id'], c.room, [c.jenn['id']])  # the owner's re-add never brings it back
    assert validity(c.store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy')


def test_a_removal_that_fails_leaves_the_grant_and_the_member_as_they_were(city, monkeypatch):
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room)
    real = type(c.store)._post_as_system

    def broken(self, db, room_id, client_id, text):
        if client_id.startswith('member-'):
            raise RuntimeError('the notice failed')
        return real(self, db, room_id, client_id, text)
    monkeypatch.setattr(type(c.store), '_post_as_system', broken)
    with pytest.raises(RuntimeError):
        c.store.remove_participant(c.andy['id'], c.room, c.jenn['id'])
    assert grant_row(c.store, grant)['revoked'] is None and c.jenn['id'] in c.store.get_room(c.andy['id'], c.room)['member_ids']


def test_the_owners_removal_refusals_change_nothing(city):
    """Rulings 9 and 10, Review Focus 3: the owner can't remove himself, someone in no room of the chain gets the
    moderator's 404, and a replaced room says where to go."""
    c = city
    andy = login(c.app, 'andy')

    def refused(key, who):
        answer = andy.delete(f'/api/chats/{key}/participants/{who}')
        return answer.status_code, answer.json()['error']
    assert refused(c.room, c.andy['id']) == (400, 'Cannot remove the room owner')
    assert refused(c.room, c.tardis['id']) == (404, f'{c.tardis["id"]} is not a member of this room')
    newer = c.store.add_participants(c.andy['id'], c.room, [c.tardis['id']])['id']
    before = (rows(c.store), epochs(c.store, [c.room, newer]))
    assert refused(c.room, c.jenn['id']) == (409, 'This room was replaced by a newer linked room; remove members there')
    assert (rows(c.store), epochs(c.store, [c.room, newer])) == before


def test_unbridging_goes_through_the_one_removal_and_announces_it(city):
    c = city
    bridged, _ = c.store.station_bridge('andy', c.room[:6], True)
    room, changed = c.store.station_bridge('andy', bridged['id'][:6], False)
    assert changed and room['id'] == bridged['id'] and c.store.list_rooms(c.wormhole['id']) == []
    assert notices(c.store, bridged['id'])[-1][1] == 'Andy removed Wormhole from this room.'  # never in the room before
