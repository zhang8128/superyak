import json
from urllib.parse import urlsplit
from superyak_agent.station import StationClient, StationError
import pytest


def client_for(fake, seen=None):
    def transport(method, url, headers, data):
        if seen is not None:
            seen.append((method, url))
        return fake(method, url, headers, data)
    return StationClient('http://station.test', 'serenity-key', transport=transport)


def thirty(station):
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, serenity)
    for i in range(30):
        fake.say(room, andy, f'message {i}')
    return fake, room, [m['id'] for m in fake.rooms[room]['messages']]


def test_room_without_page_sends_todays_request(station):
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, serenity)
    seen = []
    client_for(fake, seen).room(room)
    assert seen == [('GET', f'http://station.test/api/chats/{room}')]


def test_room_with_page_sends_the_parameters(station):
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, serenity)
    fake.say(room, andy, 'hi')
    seen = []
    client_for(fake, seen).room(room, start='m1', limit=1, before=None)
    assert seen[0][1].endswith(f'/api/chats/{room}?start=m1&limit=1')


def test_fake_station_pages_like_the_server(station):
    fake, room, ids = thirty(station)
    client = client_for(fake)

    def read(**page):
        got = client.room(room, **page)
        return [m['id'] for m in got['messages']], got
    seq = 30
    got_ids, got = read(limit=10)
    assert (got_ids, got['paged'], got['total'], got['first_position'], got['seq']) == (ids[20:], True, 30, 20, seq)
    assert 'more' not in got
    got_ids, got = read(before=20, limit=5)
    assert (got_ids, got['first_position']) == (ids[15:20], 15)
    got_ids, got = read(before=0)
    assert (got_ids, got['first_position']) == ([], 0)
    got_ids, got = read(at=25)
    assert (got_ids, got['first_position']) == (ids[25:], 25)
    got_ids, got = read(start=ids[4], limit=3)
    assert (got_ids, got['first_position']) == (ids[4:7], 4)
    got_ids, got = read(after=ids[4], limit=3)
    assert (got_ids, got['first_position']) == (ids[5:8], 5)
    got_ids, got = read(since=0, limit=10)
    assert (got_ids, got['first_position'], got['more'], got['seq']) == (ids[:10], 0, True, 10)
    got_ids, got = read(since=25)
    assert (got_ids, got['first_position'], got['more'], got['seq']) == (ids[25:], 25, False, 30)
    got_ids, got = read(since=30)
    assert (got_ids, got['first_position'], got['more'], got['seq']) == ([], 30, False, 30)


@pytest.mark.parametrize('page, status, error', [
    ({'start': 'nope'}, 404, 'No message in this room'),
    ({'after': 'nope'}, 404, 'No message in this room'),
    ({'at': 30}, 400, 'at must be between 0 and 29'),
    ({'before': 31}, 400, 'before must be between 0 and 30'),
    ({'at': 'x'}, 400, 'at must be a whole number, 0 or more'),
    ({'since': -1}, 400, 'since must be a whole number, 0 or more'),
    ({'at': 1, 'since': 2}, 400, 'Give at most one of before, at, start, after and since'),
    ({'limit': 0}, 400, 'limit must be between 1 and 500'),
    ({'limit': 501}, 400, 'limit must be between 1 and 500'),
])
def test_fake_station_refuses_like_the_server(station, page, status, error):
    fake, room, _ = thirty(station)
    with pytest.raises(StationError) as refused:
        client_for(fake).room(room, **page)
    assert error in str(refused.value)
    assert refused.value.status == status


def test_fake_station_seq_is_one_counter_across_rooms(station):
    fake, andy, jenn, serenity = station
    one, two = fake.room('One', andy, serenity), fake.room('Two', andy, serenity)
    fake.say(one, andy, 'a')
    fake.say(two, andy, 'b')
    fake.say(one, andy, 'c')
    got = client_for(fake).room(one, limit=5)
    assert got['seq'] == 3
    assert client_for(fake).room(one, since=1)['seq'] == 3
    assert client_for(fake).room(two, limit=5)['seq'] == 2


def test_fake_station_as_an_older_station_ignores_parameters(station):
    fake, room, ids = thirty(station)
    fake.pages = False
    got = client_for(fake).room(room, limit=1)
    assert [m['id'] for m in got['messages']] == ids
    assert 'paged' not in got
