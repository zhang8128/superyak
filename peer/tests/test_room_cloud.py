"""Never to a cloud model, in the store (remote connector plan, Task 1; spec "Never to a cloud model", D6, D8, D10).
A ship's own add (POST /api/ships/me/rooms/{key}/members) needs the ship in the room, which a marked room never has,
so the paths below are every way a ship can reach a marked room."""
import pytest
from superyak_peer.common import Problem
from superyak_peer.room_cloud import (ASK_OWNER, EARLIER_ASK, EARLIER_FIRST, OWNER_TOLD, REMOTE_REFUSED, REPLACED_MARK,
                                      SHIP_REFUSED, SHIPS_FIRST)
from test_moderate_grants import city, login, moderate, notices, remote_contact  # noqa: F401


def people_room(c, *names):
    """Andy's room with the named people and no ship."""
    return c.store.create_room(c.andy['id'], 'Clinic notes', [getattr(c, name)['id'] for name in names])['id']


def refused(call, *args, **kwargs):
    with pytest.raises(Problem) as caught:
        call(*args, **kwargs)
    return caught.value.status, caught.value.message


def marks(store, room_id):
    with store.transaction() as db:
        return {r[0] for r in db.execute('SELECT member_id FROM room_cloud WHERE room_id=?', (room_id,))}


def room_count(store):
    with store.transaction() as db:
        return db.execute('SELECT count(*) FROM rooms').fetchone()[0]


def test_any_member_marks_and_clears_only_their_own(city):
    c = city
    room = people_room(c, 'jenn', 'doctor')
    assert c.store.mark_room(c.jenn['id'], room)['cloud'] == {'count': 1, 'mine': True}
    assert c.store.mark_room(c.doctor['id'], room)['cloud'] == {'count': 2, 'mine': True}
    assert c.store.unmark_room(c.jenn['id'], room)['cloud'] == {'count': 1, 'mine': False}
    assert c.store.get_room(c.doctor['id'], room)['cloud'] == {'count': 1, 'mine': True}  # the doctor's mark stands


def test_an_unmarked_room_carries_no_cloud_key(city):
    """Only a marked room carries `cloud`, as only a breakout carries `breakout`: every other room's view is unchanged."""
    c = city
    room = people_room(c, 'jenn')
    assert 'cloud' not in c.store.get_room(c.andy['id'], room)
    c.store.mark_room(c.jenn['id'], room)
    c.store.unmark_room(c.jenn['id'], room)
    assert 'cloud' not in c.store.get_room(c.andy['id'], room)


def test_a_mark_stands_after_its_member_is_removed(city):
    c = city
    room = people_room(c, 'jenn', 'doctor')
    c.store.mark_room(c.jenn['id'], room)
    c.store.remove_participant(c.andy['id'], room, c.jenn['id'])
    assert c.store.get_room(c.andy['id'], room)['cloud'] == {'count': 1, 'mine': False}
    assert refused(c.store.unmark_room, c.jenn['id'], room)[0] == 404  # a former member can't clear it


def test_marking_is_refused_while_a_ship_is_a_member(city):
    c = city  # c.room holds Rio Grande and Odo
    assert refused(c.store.mark_room, c.andy['id'], c.room) == (409, SHIPS_FIRST)
    assert notices(c.store, c.room, 'cloud-ask-') == []  # the owner isn't told about his own try
    assert refused(c.store.mark_room, c.jenn['id'], c.room) == (409, ASK_OWNER.format(owner='Andy'))
    assert refused(c.store.mark_room, c.doctor['id'], c.room)[0] == 409
    assert [body for _, body in notices(c.store, c.room, 'cloud-ask-')] == [OWNER_TOLD]  # one, naming no one, for a day
    c.clock[0] += 86401
    refused(c.store.mark_room, c.jenn['id'], c.room)
    assert len(notices(c.store, c.room, 'cloud-ask-')) == 2
    assert 'cloud' not in c.store.get_room(c.andy['id'], c.room) and marks(c.store, c.room) == set()


def test_adding_a_ship_to_a_marked_room_is_refused_by_every_path(city):
    c = city
    room = people_room(c, 'jenn', 'doctor')
    c.store.mark_room(c.jenn['id'], room)
    moderate(c.store, c.andy, c.jenn, room)
    before = room_count(c.store)
    assert refused(c.store.add_participants, c.andy['id'], room, [c.tardis['id']]) == (409, SHIP_REFUSED)
    by_moderator = login(c.app, 'jenn').post(f'/api/chats/{room}/participants', json={'member_ids': [c.tardis['id']]})
    assert (by_moderator.status_code, by_moderator.json()['error']) == (409, SHIP_REFUSED)
    assert refused(c.store.station_add_ship, 'andy', room[:8], 'tardis') == (409, SHIP_REFUSED)
    assert refused(c.store.station_bridge, 'andy', room[:8], True) == (409, SHIP_REFUSED)
    assert room_count(c.store) == before


def test_the_mark_moves_with_the_room_by_every_add_path(city):
    c = city
    sam = c.store.create_user('sam', 'Sam', 'long-password-sam')
    lee = c.store.create_user('lee', 'Lee', 'long-password-lee')
    room = people_room(c, 'jenn', 'doctor')
    c.store.mark_room(c.jenn['id'], room)
    c.store.mark_room(c.doctor['id'], room)
    new = c.store.add_participants(c.andy['id'], room, [sam['id']])
    assert new['cloud'] == {'count': 2, 'mine': False}  # the answer right after the add isn't shown unmarked
    assert marks(c.store, new['id']) == {c.jenn['id'], c.doctor['id']}
    moderate(c.store, c.andy, c.jenn, new['id'])
    added = login(c.app, 'jenn').post(f'/api/chats/{new["id"]}/participants', json={'member_ids': [lee['id']]})
    assert added.status_code == 201, added.text
    assert added.json()['cloud'] == {'count': 2, 'mine': True}  # the moderator's own view
    assert marks(c.store, added.json()['id']) == {c.jenn['id'], c.doctor['id']}


def test_marking_a_continuation_marks_the_earlier_rooms_the_member_is_in(city):
    c = city
    sam = c.store.create_user('sam', 'Sam', 'long-password-sam')
    first = people_room(c, 'jenn')
    second = c.store.add_participants(c.andy['id'], first, [c.doctor['id']])['id']
    third = c.store.add_participants(c.andy['id'], second, [sam['id']])['id']
    assert set(c.store.mark_room(c.doctor['id'], third)['marked']) == {third, second}  # never in the first
    assert set(c.store.mark_room(c.jenn['id'], third)['marked']) == {third, second, first}
    assert c.store.mark_room(sam['id'], third, earlier=False)['marked'] == [third]
    assert marks(c.store, first) == {c.jenn['id']} and marks(c.store, third) == {c.doctor['id'], c.jenn['id'], sam['id']}


def test_every_member_sees_the_count_and_whether_one_is_theirs(city):
    c = city
    room = people_room(c, 'jenn', 'doctor')
    c.store.mark_room(c.jenn['id'], room)
    for who, mine in ((c.andy, False), (c.jenn, True), (c.doctor, False)):
        assert c.store.get_room(who['id'], room)['cloud'] == {'count': 1, 'mine': mine}
        assert c.store.get_room(who['id'], room, {'limit': 30})['cloud'] == {'count': 1, 'mine': mine}  # paged too
        [listed] = [r for r in c.store.list_rooms(who['id']) if r['id'] == room]
        assert listed['cloud'] == {'count': 1, 'mine': mine}


def test_only_a_member_marks_a_local_room(city):
    c = city
    room = people_room(c, 'jenn')
    assert refused(c.store.mark_room, c.doctor['id'], room)[0] == 404
    assert refused(c.store.mark_room, c.jenn['id'], 'peer:room')[0] == 404
    assert refused(c.store.mark_room, c.jenn['id'], room, earlier='yes')[0] == 400
    assert refused(c.store.unmark_room, c.doctor['id'], room)[0] == 404


def test_a_member_on_another_home_isnt_added_to_a_marked_room(city):
    """This home can't tell whether a member on a paired home is a ship (`card --as` exports any account's card), and
    that home doesn't know the mark until federation carries it. So a marked room takes no new remote member; a room
    that had one before it was marked keeps them (spec, "Rooms with members on other homes")."""
    c = city
    willa = remote_contact(c.store)
    room = people_room(c, 'jenn')
    c.store.mark_room(c.jenn['id'], room)
    before = room_count(c.store)
    assert refused(c.store.add_participants, c.andy['id'], room, [willa]) == (409, REMOTE_REFUSED)
    assert room_count(c.store) == before
    earlier = c.store.create_room(c.andy['id'], 'Clinic notes', [c.jenn['id'], willa])['id']
    assert c.store.mark_room(c.jenn['id'], earlier)['cloud'] == {'count': 1, 'mine': True}


def test_an_earlier_room_with_a_ship_left_in_it_isnt_marked(city):
    """Removals from before they reached earlier rooms, or a restore of older state, can leave a ship in an earlier
    room (Tardis's review of 541670b5). A mark there would promise what a ship could still read, so marking the chain
    is refused with the reason, and marking this room alone still works."""
    c = city
    first = people_room(c, 'jenn')
    second = c.store.add_participants(c.andy['id'], first, [c.doctor['id']])['id']
    with c.store.transaction() as db:
        db.execute('INSERT INTO room_members VALUES(?,?)', (first, c.rio['id']))  # as legacy data could leave it
    assert refused(c.store.mark_room, c.jenn['id'], second) == (409, EARLIER_ASK.format(owner='Andy'))
    assert refused(c.store.mark_room, c.andy['id'], second) == (409, EARLIER_FIRST)  # the owner removes them himself
    assert marks(c.store, first) == set() and marks(c.store, second) == set()
    assert c.store.mark_room(c.jenn['id'], second, earlier=False)['marked'] == [second]


def test_a_replaced_room_isnt_marked_alone(city):
    """Rio Grande's section 2, M1: a mark on a replaced room alone would leave the room that continues it unmarked, and
    open to a ship that would get the carried brief. Clearing stays open everywhere."""
    c = city
    first = people_room(c, 'jenn')
    second = c.store.add_participants(c.andy['id'], first, [c.doctor['id']])['id']
    assert refused(c.store.mark_room, c.jenn['id'], first) == (409, REPLACED_MARK)
    assert marks(c.store, first) == set()
    c.store.mark_room(c.jenn['id'], second)  # and, by default, the room it continues
    assert c.store.unmark_room(c.jenn['id'], first)['cloud'] == {'count': 0, 'mine': False}
    assert marks(c.store, second) == {c.jenn['id']}


def test_only_a_person_marks_or_clears(city):
    """Rio Grande's section 2, S1: a ship calling the store is refused as not a person, and the room hears nothing."""
    c = city
    assert refused(c.store.mark_room, c.rio['id'], c.room) == (403, 'Only people can do this')
    assert refused(c.store.unmark_room, c.rio['id'], c.room) == (403, 'Only people can do this')
    assert notices(c.store, c.room, 'cloud-ask-') == []


def test_a_former_members_mark_moves_with_the_room(city):
    c = city
    sam = c.store.create_user('sam', 'Sam', 'long-password-sam')
    room = people_room(c, 'jenn', 'doctor')
    c.store.mark_room(c.jenn['id'], room)
    c.store.remove_participant(c.andy['id'], room, c.jenn['id'])
    new = c.store.add_participants(c.andy['id'], room, [sam['id']])
    assert marks(c.store, new['id']) == {c.jenn['id']}


def test_a_station_ship_counts_as_a_ship(city):
    c = city
    room = c.store.create_room(c.andy['id'], 'Ops', [c.jenn['id'], c.odo['id']])['id']  # Odo has no owner
    assert refused(c.store.mark_room, c.andy['id'], room) == (409, SHIPS_FIRST)


def test_every_member_named_in_an_add_is_checked(city):
    c = city
    sam = c.store.create_user('sam', 'Sam', 'long-password-sam')
    willa = remote_contact(c.store)
    room = people_room(c, 'jenn')
    c.store.mark_room(c.jenn['id'], room)
    assert refused(c.store.add_participants, c.andy['id'], room, [sam['id'], c.tardis['id']]) == (409, SHIP_REFUSED)
    assert refused(c.store.add_participants, c.andy['id'], room, [sam['id'], willa]) == (409, REMOTE_REFUSED)


def test_the_quiet_day_is_per_room(city):
    c = city
    other = c.store.create_room(c.andy['id'], 'Ops', [c.jenn['id'], c.rio['id']])['id']
    refused(c.store.mark_room, c.jenn['id'], c.room)
    refused(c.store.mark_room, c.jenn['id'], other)
    assert len(notices(c.store, c.room, 'cloud-ask-')) == 1 and len(notices(c.store, other, 'cloud-ask-')) == 1
