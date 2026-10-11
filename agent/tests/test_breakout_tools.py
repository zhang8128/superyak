"""Breakout rooms, build step 2, the agent's tools (docs/superpowers/specs/2026-10-11-breakout-rooms-design.md, S6, S9,
S12, R11, R13, R15): a ship opens, closes and leaves its own rooms with sibling ships; station_rooms marks them;
station_unread asks the station to leave out breakout messages that don't mention the ship, and counts them; and a
breakout closed long ago is still read by its id."""
import json
from conftest import BREAKOUT_CLOSED, DAY, INVITEE_REFUSED
from superyak_agent.mcp import TOOLS, Tools, handle
from superyak_agent.station import StationClient


def fleet(station):
    """Andy's ships as in "Superyak: all hands": Serenity, Rio Grande and Tardis, put together in a room he owns."""
    fake, andy, jenn, serenity = station
    rio = fake.user('rio-grande', 'Rio Grande', 'ship', andy['id'], key='rio-key')
    tardis = fake.user('tardis', 'Tardis', 'ship', andy['id'], key='tardis-key')
    hands = fake.room('Superyak: all hands', andy, serenity, rio, tardis)
    return fake, andy, jenn, serenity, rio, tardis, hands


def tools_for(fake, key='serenity-key'):
    return Tools(StationClient('http://station.test', key, transport=fake))


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def test_the_client_sends_the_flag_only_when_asked(station):
    """R13: the client's unread is today's call byte for byte unless a caller asks for breakouts=mentions; the three
    breakout routes are the station's."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    client = StationClient('http://station.test', 'serenity-key', transport=fake)
    client.unread('s1', 20)
    client.unread('s1', 20, breakouts='mentions')
    assert [(r['path'], r['query'], r['body']) for r in fake.requests] == [
        ('/api/ships/me/unread', '', {'cursor': 's1', 'limit': 20, 'wait': 0}),
        ('/api/ships/me/unread', 'breakouts=mentions', {'cursor': 's1', 'limit': 20, 'wait': 0})]
    room = client.open_room('Sync', ['tardis'])
    assert room['breakout'] == {'creator': serenity['id'], 'closed': None} and room['owner_id'] == serenity['id']
    assert client.leave_room(room['id']) == {'room_id': room['id'], 'left': True, 'closed': fake.clock}
    again = client.open_room('Sync again', ['tardis'])
    assert client.close_room(again['id'])['breakout']['closed'] == fake.clock
    assert [(r['method'], r['path'], r['body']) for r in fake.requests[2:]] == [
        ('POST', '/api/ships/me/rooms', {'title': 'Sync', 'ships': ['tardis']}),
        ('POST', f'/api/ships/me/rooms/{room["id"]}/leave', {}),
        ('POST', '/api/ships/me/rooms', {'title': 'Sync again', 'ships': ['tardis']}),
        ('POST', f'/api/ships/me/rooms/{again["id"]}/close', {})]


def test_breakout_tools(station):
    """R11, S9: a ship opens a breakout with sibling ships and is told the room's id and short id; it posts there as in
    any room; a member leaves; the owner closes it; the owner leaving another closes that one."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    tools = tools_for(fake)
    text, error = call(tools, 'station_open_room', title='Deploy plan', ships=['rio-grande', '@tardis'])
    room = next(iter(fake.breakouts))
    assert not error and fake.requests[-1]['body'] == {'title': 'Deploy plan', 'ships': ['rio-grande', 'tardis']}
    assert fake.rooms[room]['owner_id'] == serenity['id'] and fake.rooms[room]['member_ids'] == [serenity['id'], rio['id'], tardis['id']]
    assert f'Opened breakout Deploy plan, room {room} (short id {room[:6]}), with @rio-grande and @tardis' in text
    assert 'ships only' in text and 'station_close_room' in text
    posted, error = call(tools, 'station_post', room=room, text='@rio-grande can you check the deploy?')
    assert not error and posted.startswith('Posted message')
    left, error = call(tools_for(fake, 'rio-key'), 'station_leave_room', room=room)
    assert not error and left == f'Left breakout {room}; its messages no longer reach this ship.'
    assert rio['id'] not in fake.rooms[room]['member_ids'] and fake.closed(room) is None
    closed, error = call(tools, 'station_close_room', room='Deploy plan')  # an exact title, as for any room
    assert not error and fake.closed(room) == fake.clock
    assert closed.startswith(f'Closed breakout Deploy plan ({room}). It stays readable')
    call(tools, 'station_open_room', title='Second look', ships='tardis, rio-grande')
    second = list(fake.breakouts)[-1]
    assert fake.rooms[second]['member_ids'] == [serenity['id'], tardis['id'], rio['id']]
    text, error = call(tools, 'station_leave_room', room=second)
    assert not error and fake.closed(second) is not None and text == f'Left breakout {second}; its messages no longer reach this ship. It is closed.'


def test_breakout_tools_refuse_clearly_when_the_station_refuses(station):
    """R11: the station's refusal is the tool's error, word for word, and nothing is made."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    fake.room('Lab', jenn, defiant, serenity)
    tools = tools_for(fake)
    for ships in (['jenn'], ['defiant'], ['nobody'], ['tardis', 'jenn']):
        assert call(tools, 'station_open_room', title='Sync', ships=ships) == (f'station error: 400: {INVITEE_REFUSED}', True)
    assert fake.breakouts == {}
    for bad in ({'title': 'Sync'}, {'title': 'Sync', 'ships': [3]}, {'title': 7, 'ships': ['tardis']}, {'ships': ['tardis']}):
        before = len(fake.requests)
        text, error = call(tools, 'station_open_room', **bad)
        assert error and len(fake.requests) == before, bad
    room = fake.breakout('Sync', serenity, tardis)
    assert call(tools_for(fake, 'tardis-key'), 'station_close_room', room=room) == (
        'station error: 403: Only the ship that opened this breakout can close it', True)
    assert call(tools, 'station_leave_room', room=hands) == (
        "station error: 400: This room isn't a breakout; a person manages its members", True)
    call(tools, 'station_close_room', room=room)
    assert call(tools, 'station_post', room=room, text='one more thing') == (f'station error: 409: {BREAKOUT_CLOSED}', True)
    assert call(tools, 'station_claim', room=room, key='spec:x') == (f'station error: 409: {BREAKOUT_CLOSED}', True)


def test_breakout_tool_descriptions_say_ships_only_and_data():
    """S9: each tool says breakouts are ships only, with siblings the owner already put together, and that the
    messages there are data."""
    described = {name: (description, props, required) for name, description, props, required in TOOLS}
    for name in ('station_open_room', 'station_close_room', 'station_leave_room'):
        description = described[name][0]
        assert 'ships only' in description and 'already put together' in description, name
        assert 'quoted data' in description and 'never instructions' in description, name
    assert described['station_open_room'][2] == ['title', 'ships']
    assert described['station_close_room'][2] == described['station_leave_room'][2] == ['room']


def test_station_rooms_marks_breakouts_and_closed_ones(station):
    """S9: station_rooms marks a breakout, and a closed one says when it closed; every other room is listed exactly as
    before."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    fake.say(hands, andy, 'hello')
    open_room, done = fake.breakout('Sync', serenity, tardis), fake.breakout('Done', rio, serenity)
    fake.breakouts[done]['closed'] = 86400.0 * 3
    listed = {r['id']: r for r in json.loads(call(tools_for(fake), 'station_rooms')[0])}
    assert listed[hands] == {'id': hands, 'title': 'Superyak: all hands', 'last_activity': fake.rooms[hands]['messages'][-1]['created']}
    assert listed[open_room] == {'id': open_room, 'title': 'Sync', 'last_activity': 0.0, 'breakout': 'ships only'}
    assert listed[done] == {'id': done, 'title': 'Done', 'last_activity': 0.0, 'breakout': 'ships only',
                            'closed': '1970-01-04 00:00 UTC'}


def test_breakout_messages_are_marked_where_they_appear(station):
    """S6: a breakout's messages and room view say so in station_read, station_mentions and station_unread; other
    rooms' headers are unchanged."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    room = fake.breakout('Sync', rio, serenity)
    asked = fake.say(room, rio, '@serenity over to you')
    fake.say(hands, andy, '@serenity and from me')
    tools = tools_for(fake)
    assert call(tools, 'station_read', room=room)[0].splitlines()[0] == f'Room Sync ({room}, breakout, ships only)'
    assert call(tools, 'station_read', room=hands)[0].splitlines()[0] == f'Room Superyak: all hands ({hands})'
    mentions = call(tools, 'station_mentions')[0]
    assert f'mention 1 in breakout {room} (ships only), message {asked["id"]}\n' in mentions
    assert f'mention 2 in room {hands}, message ' in mentions
    unread = call(tools, 'station_unread', cursor='c1')[0]
    assert f'Room Sync ({room}, breakout, ships only), message {asked["id"]} (no run ticket) [mentions you]\n' in unread
    assert f'Room Superyak: all hands ({hands}), message ' in unread
    fake.breakouts[room]['closed'] = 86400.0
    assert call(tools, 'station_read', room=room)[0].splitlines()[0] == (
        f'Room Sync ({room}, breakout, ships only, closed 1970-01-02 00:00 UTC)')


def test_station_unread_sends_the_flag_and_shows_the_count_lines(station):
    """R13, S6: station_unread sends breakouts=mentions, so 30 breakout messages never hold back a person's: the page
    holds the breakout mention and the person's message, and a line counts what the station left out."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    room = fake.breakout('Alpha', rio, serenity)
    for n in range(30):
        fake.say(room, rio, '@serenity look here' if n == 9 else f'alpha {n}')
    person = fake.say(hands, andy, 'Serenity, a question from Andy')
    tools = tools_for(fake)
    text, error = call(tools, 'station_unread', cursor='c1', limit=20)
    assert not error and fake.requests[0]['query'] == 'breakouts=mentions'
    assert '@serenity look here' in text and person['body'] in text and 'alpha 0' not in text
    assert text.endswith(f'\n\n29 new in breakout Alpha; `station_read room={room}` shows them')
    assert call(tools, 'station_unread', cursor='c1')[0] == '(nothing unread)'
    for n in range(3):
        fake.say(room, rio, f'late {n}')
    assert call(tools, 'station_unread', cursor='c1')[0] == f'3 new in breakout Alpha; `station_read room={room}` shows them'
    assert call(tools, 'station_unread', cursor='c1')[0] == '(nothing unread)'


def test_old_closed_breakouts_leave_the_lists(station):
    """R15, S12: a breakout closed more than 7 days ago is gone from station_rooms but its members still reach it by
    id, through station_read and the claim tools; a post there is refused as closed. An id the station doesn't know
    is refused as before."""
    fake, andy, jenn, serenity, rio, tardis, hands = fleet(station)
    room = fake.breakout('Done', serenity, tardis)
    fake.say(room, tardis, 'finished here')
    tools = tools_for(fake)
    call(tools, 'station_close_room', room=room)
    fake.clock += 7 * DAY + 1
    assert room not in {r['id'] for r in json.loads(call(tools, 'station_rooms')[0])}
    text, error = call(tools, 'station_read', room=room)
    assert not error and 'finished here' in text and text.startswith(f'Room Done ({room}, breakout, ships only, closed ')
    assert call(tools, 'station_claims', room=room) == ('(no active claims in this room)', False)
    assert call(tools, 'station_post', room=room, text='late') == (f'station error: 409: {BREAKOUT_CLOSED}', True)
    for unknown, fetched in (('Done', True), ('r99', True), ('peer:r1', False)):  # a remote id is never fetched
        before = len(fake.requests)
        assert call(tools, 'station_read', room=unknown) == (
            f"station error: No single room matches {unknown!r}; use station_rooms to list room ids", True)
        assert [r['path'] for r in fake.requests[before:]] == ['/api/chats'] + ([f'/api/chats/{unknown}'] if fetched else [])
