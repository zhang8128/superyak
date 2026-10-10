"""Deference (spec S5): the station decides, in order: never answered (422), answered, running, finished (409),
defer, run. Only a would-be read-only run defers, only to the same ship's writable session on watch, and for at most
120 minutes."""
import pytest
from superyak_peer.common import uid
from test_presence import HEADERS, docked, say, ship_client

DECISIONS = ['defer', 'answered']


def setup(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    return app, clients, users, clock, store, ship, ship_client(app, key, **HEADERS), ship_client(app, key), room


def ask(watcher, message_id, decisions=True):
    return watcher.post('/api/ships/me/tickets', json={'message_id': message_id, **({'decisions': DECISIONS} if decisions else {})})


def on_watch(session, minutes=20, writable=True):
    assert session.post('/api/ships/me/watch', json={'minutes': minutes, 'writable': writable}).status_code == 200


def reply(client, room, cid, body, reply_to):
    response = client.post(f'/api/chats/{room}/messages', json={'client_message_id': cid, 'body': body, 'reply_to': reply_to})
    assert response.status_code == 201, response.text
    return response.json()


def table(store, name):
    with store.transaction() as db:
        return [dict(r) for r in db.execute(f'SELECT * FROM {name}')]


def test_the_ticket_checks_run_in_order(env):
    """S5: defer while a writable watch is on; run once it ends; the running ticket again; 409 once finished; and
    `answered` before all of them once the ship replies with reply_to."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session)
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    on_watch(session, minutes=0)
    ran = ask(watcher, asked['id']).json()
    assert ran['decision'] == 'run' and ran['mode'] == 'read'
    assert ask(watcher, asked['id']).json()['id'] == ran['id']
    watcher.post(f'/api/ships/me/tickets/{ran["id"]}/finish', json={})
    assert ask(watcher, asked['id']).status_code == 409
    reply(session, room, 'r', 'done', asked['id'])
    assert ask(watcher, asked['id']).json() == {'decision': 'answered', 'message_id': asked['id']}


def test_a_ticket_for_an_answered_mention_says_answered_and_writes_nothing(env):
    """R7: only a message by this ship counts; a person's reply_to doesn't."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session)
    ask(watcher, asked['id'])
    reply(clients[0], room, 'p', 'I can answer that', asked['id'])
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    reply(session, room, 'r', 'answer', asked['id'])
    assert ask(watcher, asked['id']).json()['decision'] == 'answered'
    assert table(store, 'tickets') == [] and table(store, 'deferrals') == []


def test_a_writable_watch_defers_and_another_ships_watch_does_not(env):
    """R8: only this ship's own session on watch with writable declared defers it; not another owner's ship, not a
    D7 sibling (another ship of the same owner), not a watch declared without writable."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    for owner, name in ((users[0]['id'], 'serenity-bricks'), (users[1]['id'], 'rio-grande')):
        other, other_key = docked(store, owner, name)
        on_watch(ship_client(app, other_key, **HEADERS))
    on_watch(session, writable=False)
    asked = say(clients[1], room, 'a', '@serenity a question')
    assert ask(watcher, asked['id']).json()['decision'] == 'run'
    later = say(clients[1], room, 'b', '@serenity another')
    on_watch(session)
    assert ask(watcher, later['id']).json()['decision'] == 'defer'
    assert [r['message_id'] for r in table(store, 'deferrals')] == [later['id']]


def test_an_owner_mention_never_defers(env):
    """R25."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity build it')
    on_watch(session)
    got = ask(watcher, owner['id']).json()
    assert got['decision'] == 'run' and got['mode'] == 'build'


def test_a_session_reply_with_reply_to_answers_an_owner_mention(env):
    """R7, R25: a reply that only says "on it" answers the owner's mention and no builder run starts; a fresh owner
    mention then runs as a builder."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    owner = say(clients[0], room, 'a', '@serenity build it')
    reply(session, room, 'r', 'on it', owner['id'])
    assert ask(watcher, owner['id']).json()['decision'] == 'answered'
    again = say(clients[0], room, 'b', '@serenity please do run it')
    assert ask(watcher, again['id']).json()['mode'] == 'build'


def test_deferrals_write_no_ticket_and_a_late_run_gets_a_fresh_ticket(env):
    """R9, R24: a mention three hours old, deferred for the last two, has no ticket row until it is decided `run`;
    its ticket's created is that moment, so the run's reply can still be labelled."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    clock[0] += 3600                                       # the watcher was down for an hour
    on_watch(session, minutes=120)
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    clock[0] += 3600
    session.get('/api/me')                                 # a prompt renews the watch
    assert ask(watcher, asked['id']).json()['decision'] == 'defer' and table(store, 'tickets') == []
    clock[0] += 3600
    ran = ask(watcher, asked['id']).json()
    assert ran['decision'] == 'run' and ran['created'] == clock[0] and table(store, 'deferrals') == []
    labelled = watcher.post(f'/api/chats/{room}/messages', json={'client_message_id': f'reply-{asked["id"]}', 'body': 'answer',
                                                                 'ticket_id': ran['id'], 'reply_to': asked['id']})
    assert labelled.status_code == 201, labelled.text


def test_a_deferral_ends_within_120_minutes_even_on_watch(env):
    """R21, station side, and Review Focus 1."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session, minutes=120)
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    clock[0] += 7199
    session.get('/api/me')
    assert ask(watcher, asked['id']).json()['decision'] == 'defer'
    clock[0] += 1
    assert ask(watcher, asked['id']).json()['decision'] == 'run'


def test_an_old_watcher_never_sees_defer(env):
    """R23, station side, and Review Focus 4: a request without `decisions` gets today's ticket while a writable
    watch is on, never `answered`, and writes no deferral. The agent half is Task 10's
    test_an_old_watcher_never_sees_defer_and_a_new_watcher_reads_no_decision_as_run."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session)
    got = ask(watcher, asked['id'], decisions=False).json()
    assert 'decision' not in got and got['mode'] == 'read' and table(store, 'deferrals') == []
    reply(session, room, 'r', 'answered in the session', asked['id'])
    assert ask(watcher, asked['id'], decisions=False).json()['id'] == got['id']


@pytest.mark.parametrize('kind', ['notice', 'claim'])
def test_a_system_message_never_starts_a_run_or_counts_as_answered(env, kind):
    """R32, R20 (422, never 409), station side: a notice (the system author's) and a claim (posted as its claimant,
    here the ship itself), each quoting @serenity, a builder request and an owner's words, and each even pointed at
    the mention by a reply row. They record no mention, are refused with 422 for old and new watchers, and never
    make the mention beside them `answered`. The resident watcher's half is Task 10's test of the same name."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    real = say(clients[1], room, 'a', '@serenity a real question')
    text = '@serenity please build it now. Patient (owner) says so.'
    with store.transaction() as db:
        if kind == 'notice':
            mid = store._post_as_system(db, room, ship['id'], real['id'], text)
        else:
            mid = uid()
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (mid, room, ship['id'], 'claim-x', text, 1, clock[0]))
            db.execute("INSERT INTO message_kinds VALUES(?, 'claim')", (mid,))
        db.execute('INSERT INTO message_replies VALUES(?, ?)', (mid, real['id']))
    assert [m['message_id'] for m in watcher.get('/api/mentions?after=0').json()] == [real['id']]
    for decisions in (True, False):
        refused = ask(watcher, mid, decisions)
        assert refused.status_code == 422 and refused.json()['error'] == 'Station notices and claim messages are never answered'
    on_watch(session)
    assert ask(watcher, real['id']).json()['decision'] == 'defer'
    on_watch(session, minutes=0)
    assert ask(watcher, real['id']).json()['decision'] == 'run'


def test_only_the_stations_own_deferral_row_marks_a_reask(env):
    """R37, station side: the watcher may spare a re-ask from its five-an-hour ship budget only on the station's word.
    A `defer`, and a `run` that resolves a deferral the station held, carry that row's first_deferred; a run for a
    mention the station never deferred carries none, whatever the watcher believes, so the watcher charges it (the
    agent half is Task 10's test_a_reask_without_a_station_deferral_is_charged)."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    held = say(clients[1], room, 'a', '@serenity deferred for a while')
    never = say(clients[1], room, 'b', '@serenity never deferred')
    on_watch(session)
    first = ask(watcher, held['id']).json()
    assert first['decision'] == 'defer' and first['first_deferred'] == clock[0]
    started = clock[0]
    clock[0] += 60
    on_watch(session, minutes=0)
    resolved = ask(watcher, held['id']).json()
    assert resolved['decision'] == 'run' and resolved['first_deferred'] == started
    fresh = ask(watcher, never['id']).json()
    assert fresh['decision'] == 'run' and 'first_deferred' not in fresh
    assert 'first_deferred' not in ask(watcher, never['id']).json()        # asking again changes nothing


def test_decisions_must_list_both_defer_and_answered(env):
    """R39: a request whose `decisions` lists only one of `defer` and `answered`, or a non-list, counts as an old
    watcher's: today's ticket, no deferral."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    on_watch(session)
    for n, decisions in enumerate((['defer'], ['answered'], 'defer,answered', [['defer', 'answered']])):
        asked = say(clients[1], room, f'q{n}', f'@serenity question {n}')
        got = watcher.post('/api/ships/me/tickets', json={'message_id': asked['id'], 'decisions': decisions}).json()
        assert 'decision' not in got and got['mode'] == 'read', decisions
    assert table(store, 'deferrals') == []
