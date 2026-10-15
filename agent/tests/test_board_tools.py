"""Work board, build step 2 (agent): the five board tools and BOARD, source_label's `board`, station_claim's line and
station_claims' marks (docs/superpowers/specs/2026-10-14-work-board-design.md 5.3, 5.5, 5.6)."""
import re
import sys
from conftest import board_item, held_by
from superyak_agent import install, mcp, runs, station as station_module
from superyak_agent.mcp import Tools, handle
from superyak_agent.station import StationClient, StationError, claims_block, source_label

BOARD_TOOLS = {'station_board', 'station_post_item', 'station_link_item', 'station_done', 'station_drop'}


def tools_for(fake):
    return Tools(StationClient('http://station.test', 'serenity-key', transport=fake))


def call(tools, name, **arguments):
    result = handle(tools, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}})['result']
    return result['content'][0]['text'], result['isError']


def test_board_lines_are_labelled_board(station):
    """4.5, 5.4: source_label gives `board` for a kind-claim body starting Posted, Linked, Done or Dropped, and `claim` for
    Claimed, Renewed and Released. A member's ordinary post starting "Posted " gets no new label. station_read shows it,
    as do the hook and station_unread, which share source_label."""
    def labelled(body, kind='claim'):
        return source_label({'body': body, 'source': {'kind': kind}})
    assert [labelled(b) for b in ('Posted `a` (spec): x', 'Linked `a`: branch:x', 'Done `a`: commit:1ff0efb', 'Dropped `a`')] == ['board'] * 4
    assert [labelled(b) for b in ('Claimed `a` until 10:00 UTC', 'Renewed `a` until 11:00 UTC', 'Released `a`')] == ['claim'] * 3
    assert labelled('Posted the notes', 'post') == 'no run ticket' and source_label({'body': 'Posted the notes', 'source': None}) == ''
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    line = fake.say(room, serenity, 'Posted `spec:a` (spec): Write it')
    fake.kinds[line['id']] = 'claim'
    plain = fake.say(room, jenn, 'Posted the notes')
    text = call(tools_for(fake), 'station_read', room=room)[0]
    assert f'message {line["id"]} (board)\n' in text and f'message {plain["id"]}\n' in text


def test_claims_mark_board_items(station):
    """5.6, tools half: claims_block shows (board item), (board item, done) and (board item, dropped) after the key, in
    station_claims and in station_read; a plain claim's line is today's. (The station half is peer
    tests/test_room_board.py, step 1.)"""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    fake.claims[room] = [dict(held_by(jenn, key), **({'board': state} if state else {}))
                         for key, state in (('build:a', 'open'), ('build:b', 'done'), ('build:c', 'dropped'), ('adhoc:x', None))]
    listed = call(tools_for(fake), 'station_claims', room=room)[0]
    for line in ('- `build:a` (board item) held by Jenn until', '- `build:b` (board item, done) held by Jenn until',
                 '- `build:c` (board item, dropped) held by Jenn until', '- `adhoc:x` held by Jenn until'):
        assert line in listed, line
    assert claims_block({'claims': fake.claims[room]}) in call(tools_for(fake), 'station_read', room=room)[0]


def test_the_client_quotes_the_room_on_every_board_route(station):
    """5.3: each StationClient board method calls its route with the room id quoted, as claim does, and the body 5.1
    names; the count route has no room."""
    fake, andy, jenn, serenity = station
    client = StationClient('http://station.test', 'serenity-key', transport=fake)
    for method in (lambda: client.board('peer:room'), lambda: client.post_item('peer:room', 'k', 't', 'ops'),
                   lambda: client.link_item('peer:room', 'k', 'branch:x'), lambda: client.done_item('peer:room', 'k', 'commit:1ff0efb'),
                   lambda: client.drop_item('peer:room', 'k')):
        try:
            method()
        except StationError:
            pass  # the fake knows no such room; the path is what this checks
    assert [(r['method'], r['path'], r['body']) for r in fake.requests] == [
        ('GET', '/api/chats/peer%3Aroom/board', None),
        ('POST', '/api/chats/peer%3Aroom/board', {'key': 'k', 'title': 't', 'kind': 'ops'}),
        ('POST', '/api/chats/peer%3Aroom/board/link', {'key': 'k', 'link': 'branch:x'}),
        ('POST', '/api/chats/peer%3Aroom/board/done', {'key': 'k', 'outcome': 'commit:1ff0efb'}),
        ('POST', '/api/chats/peer%3Aroom/board/drop', {'key': 'k'})]
    assert client.board_counts() == {'rooms': []} and fake.requests[-1]['path'] == '/api/ships/me/board'
