"""Spending a grant (spec A step 3, merge 3c: G15-G18 of docs/superpowers/specs/2026-10-15-grants-step3-design.md)."""
import json
from superyak_peer import grants as G
from superyak_peer.common import uid
from test_grants import charge, make, revoke_by_hand

DAY = 86400


def ships(store, owner_id, *names):
    """Ships written directly, as test_grants' fleet() writes them (docking allows 20 an hour, and scrypt is slow):
    {username: {id, username}}. owner_id None makes a resident, which has no owner."""
    made = {}
    with store.transaction() as db:
        for name in names:
            key = uid()
            db.execute("INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind,owner_id) "
                       "VALUES(?,?,?,?,?,0,?,'ship',?)",
                       (key, name, name.replace('-', ' ').title(), b'\0' * 16, b'\0' * 32, store.clock(), owner_id))
            made[name] = {'id': key, 'username': name}
    return made


def room(store, owner, title, *members):
    return store.create_room(owner['id'], title, [member['id'] for member in members])['id']


def mention(store, author, room_id, *targets):
    """A message by author that mentions each target ship, posted through the store (a person's login lasts a day, and
    these tests move the clock further)."""
    body = ' '.join(f'@{ship["username"]}' for ship in targets) + ' please fix the notes'
    return store.send_message(author['id'], room_id, uid(), body)


def decide(store, ship, message):
    """The ticket's (mode, basis), as POST /api/ships/me/tickets decides it for a watcher that asks without decisions."""
    got = store.issue_ticket(ship['id'], message['id'])
    return got['mode'], got['basis']


def ticket_row(store, ship, message):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM tickets WHERE ship_id=? AND message_id=?', (ship['id'], message['id'])).fetchone())


def uses(store, grant_id):
    with store.transaction() as db:
        return [dict(row) for row in db.execute('SELECT grant_id, ticket_id, created FROM budget_uses WHERE grant_id=? '
                                                'ORDER BY created, ticket_id', (grant_id,))]


def test_only_the_owner_and_a_valid_grantee_in_a_room_with_the_issuer_build(env):
    """Test 11 and spec Review Focus 2: spec A Testing 1 without directs, as one table, authors first, then grant states
    for one grantee. Each case has its own ship, so each grant names only the ship its case mentions."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    names = ('own', 'valid', 'none', 'other-ship', 'decoy', 'other-room', 'spent', 'expired', 'revoked', 'after', 'same',
             'day', 'older', 'answered', 'left', 'star', 'removed', 'by-ship', 'side', 'far', 'each', 'instruct')
    s = ships(store, patient['id'], *names)
    s.update(ships(store, None, 'odo'))
    defiant = ships(store, doctor['id'], 'defiant')['defiant']
    ops = room(store, patient, 'Ops', doctor, organizer, defiant, s['odo'],
               *[s[name] for name in names if name not in ('left', 'star', 'removed', 'side', 'far')])
    other = room(store, patient, 'Other', doctor, s['other-room'])
    left = room(store, patient, 'Left', doctor, s['left'])
    theirs = room(store, doctor, 'Theirs', s['star'])  # doctor's room with patient's ship, without patient
    shared = room(store, doctor, 'Shared', patient, s['removed'])  # doctor's room; doctor will remove patient
    side = room(store, patient, 'Side', doctor, s['side'])
    far = 'ab' * 32 + ':room-1'  # a remote room's id, written by hand, with its members and a message
    with store.transaction() as db:
        db.execute('INSERT INTO breakouts(room_id, creator_id, created) VALUES(?,?,?)', (side, s['side']['id'], clock[0]))
        db.execute('INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES(?,?,?,1,NULL)', (far, patient['id'], 'Far'))
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)',
                       [(far, patient['id']), (far, doctor['id']), (far, s['far']['id'])])
    grant = {name: make(store, patient, doctor, [s[name]], hours=48)
             for name in ('valid', 'decoy', 'spent', 'revoked', 'day', 'older', 'answered', 'left', 'star', 'side',
                          'far', 'each', 'instruct')}
    grant['other-room'] = make(store, patient, doctor, [s['other-room']], rooms=[other], hours=48)
    grant['removed'] = make(store, patient, doctor, [s['removed']], rooms=[shared], hours=48)
    grant['expired'] = make(store, patient, doctor, [s['expired']], hours=24)  # expired by the time it is asked
    grant['by-ship'] = make(store, patient, defiant, [s['by-ship']], hours=48)  # to a ship, by hand: G8 refuses it
    grant['odo'] = make(store, patient, doctor, [s['odo']], hours=48)  # over a resident, by hand: G8 refuses it
    revoke_by_hand(store, grant['revoked'], patient)
    with store.transaction() as db:  # by hand: step 3 never writes either
        db.execute("UPDATE grants SET confirm='each' WHERE id=?", (grant['each'],))
        db.execute("""UPDATE grants SET actions='["instruct"]' WHERE id=?""", (grant['instruct'],))
    clock[0] += 100
    asked = {'older': mention(store, doctor, ops, s['older'])}  # 86,400.5 s before the tickets
    clock[0] += 0.5
    asked['day'] = mention(store, doctor, ops, s['day'])  # exactly 86,400 s before the tickets
    clock[0] += DAY - 52
    asked['after'] = mention(store, doctor, ops, s['after'])
    clock[0] += 1
    grant['after'] = make(store, patient, doctor, [s['after']], hours=48)  # made a second after the message
    clock[0] += 1
    grant['same'] = make(store, patient, doctor, [s['same']], hours=48)
    asked['same'] = mention(store, doctor, ops, s['same'])  # posted in the second the grant was made
    asked['own'] = mention(store, patient, ops, s['own'])
    asked['other person'] = mention(store, organizer, ops, s['valid'])
    asked['by-ship'] = mention(store, defiant, ops, s['by-ship'])
    asked['odo'] = mention(store, doctor, ops, s['odo'])
    for name in ('valid', 'none', 'spent', 'expired', 'revoked', 'answered', 'each', 'instruct'):
        asked[name] = mention(store, doctor, ops, s[name])
    asked['other-ship'] = mention(store, doctor, ops, s['other-ship'])  # doctor's grant names decoy, not this ship
    asked['other-room'] = mention(store, doctor, ops, s['other-room'])  # its grant lists Other only
    store.send_message(s['answered']['id'], ops, uid(), 'Already on it', None, asked['answered']['id'])
    asked['left'] = mention(store, doctor, left, s['left'])
    store.remove_participant(patient['id'], left, doctor['id'])  # the author no longer in the room
    asked['star'] = mention(store, doctor, theirs, s['star'])
    asked['removed'] = mention(store, doctor, shared, s['removed'])
    store.remove_participant(doctor['id'], shared, patient['id'])  # the room's owner removed the issuer
    asked['side'] = mention(store, doctor, side, s['side'])
    with store.transaction() as db:
        db.execute("INSERT INTO messages(id, room_id, author_id, client_message_id, body, epoch, created) "
                   "VALUES('far-1', ?, ?, 'far-1', '@far please', 1, ?)", (far, doctor['id'], clock[0]))
        db.execute("INSERT INTO mentions(message_id, room_id, user_id) VALUES('far-1', ?, ?)", (far, s['far']['id']))
    asked['far'] = {'id': 'far-1'}
    charge(store, grant['spent'], 1, 2, 3, 4, 5)  # its 5 builds, used in the last minute
    clock[0] += 50  # the tickets: 86,400 s after 'day' was posted
    target = {'other person': s['valid']}
    got = {name: decide(store, target.get(name, s.get(name)), message) for name, message in asked.items()}
    assert got == {
        'own': ('build', 'owner'), 'valid': ('build', 'grant'), 'same': ('build', 'grant'), 'day': ('build', 'grant'),
        'older': ('read', 'old'), 'answered': ('read', 'answered'),
        'other person': ('read', 'none'), 'by-ship': ('read', 'none'), 'odo': ('read', 'none'), 'none': ('read', 'none'),
        'other-ship': ('read', 'none'), 'other-room': ('read', 'none'), 'spent': ('read', 'none'),
        'expired': ('read', 'none'), 'revoked': ('read', 'none'), 'after': ('read', 'none'), 'left': ('read', 'none'),
        'star': ('read', 'none'), 'removed': ('read', 'none'), 'side': ('read', 'none'), 'far': ('read', 'none'),
        'each': ('read', 'none'), 'instruct': ('read', 'none')}


def test_a_grant_build_records_its_grant_and_charges_it_once(env):
    """G16: basis grant, root_id the root's issuer, chain the grant ids root first, and one budget_uses row per link in
    the ticket's transaction, at the ticket's time. An owner build and a read charge nothing."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, organizer, s)
    grant = make(store, patient, doctor, [s], hours=48)
    asked, owners, others = mention(store, doctor, ops, s), mention(store, patient, ops, s), mention(store, organizer, ops, s)
    clock[0] += 5
    assert [decide(store, s, m) for m in (asked, owners, others)] == [('build', 'grant'), ('build', 'owner'), ('read', 'none')]
    row = ticket_row(store, s, asked)
    assert (row['root_id'], json.loads(row['chain'])) == (patient['id'], [grant])
    assert uses(store, grant) == [{'grant_id': grant, 'ticket_id': row['id'], 'created': clock[0]}]
    assert json.loads(ticket_row(store, s, owners)['chain']) == [] and json.loads(ticket_row(store, s, others)['chain']) == []
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM budget_uses').fetchone()[0] == 1


def test_a_spent_budget_reads_until_its_builds_are_a_day_old_and_two_ships_share_it(env):
    """Test 13 and spec Review Focus 4: after `budget` builds the next mention reads; a build exactly 24 hours old no longer
    counts; builds of either ship count against one grant's budget."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    grant = make(store, patient, doctor, [serenity, rio], hours=48, budget=2)
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('build', 'grant')
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('build', 'grant')  # the other ship, the same budget
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('read', 'none')
    clock[0] += DAY - 1
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')  # a second short of a day
    clock[0] += 1
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('build', 'grant')  # the first two are a day old now
    assert next(view for view in store.list_grants(patient['id']) if view['id'] == grant)['budget_left'] == 1


def test_the_21st_grant_build_of_a_ship_in_a_day_reads_across_grants_and_owner_builds_never_count(env):
    """Test 14: builds_per_ship_per_day (20) counts grant build tickets under every grant; the 21st reads though its own
    grant has budget left, and it builds again once those builds are a day old. ship_builds_left shows the ship's
    count on the other grant."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, family, serenity)
    first = make(store, patient, doctor, [serenity], hours=48, budget=12)
    second = make(store, patient, family, [serenity], hours=48, budget=12)
    left = lambda viewer, grant: next(view for view in store.list_grants(viewer['id']) if view['id'] == grant)['targets'][0]['ship_builds_left']
    assert [decide(store, serenity, mention(store, doctor, ops, serenity)) for _ in range(12)] == [('build', 'grant')] * 12
    assert left(family, second) == 8  # the first grant's builds count on the second's ship
    assert [decide(store, serenity, mention(store, patient, ops, serenity)) for _ in range(3)] == [('build', 'owner')] * 3
    assert left(family, second) == 8  # owner builds don't count
    assert [decide(store, serenity, mention(store, family, ops, serenity)) for _ in range(8)] == [('build', 'grant')] * 8
    assert left(family, second) == 0 and left(patient, first) == 0
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('read', 'none')  # the 21st; 4 left on its grant
    clock[0] += DAY - 1
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('read', 'none')
    clock[0] += 1
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('build', 'grant')


def test_the_oldest_grant_is_charged_and_the_next_when_it_has_no_budget(env, monkeypatch):
    """Test 15 and spec Review Focus 1: of two valid grants the oldest (by created, then id) is charged, and only it; once it
    has no budget left, the newer one is."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    older = make(store, patient, doctor, [serenity], hours=48, budget=1)
    clock[0] += 1
    newer = make(store, patient, doctor, [serenity], hours=48, budget=5)
    first, second = mention(store, doctor, ops, serenity), mention(store, doctor, ops, serenity)
    assert decide(store, serenity, first) == ('build', 'grant') and json.loads(ticket_row(store, serenity, first)['chain']) == [older]
    assert (len(uses(store, older)), len(uses(store, newer))) == (1, 0)
    assert decide(store, serenity, second) == ('build', 'grant') and json.loads(ticket_row(store, serenity, second)['chain']) == [newer]
    assert (len(uses(store, older)), len(uses(store, newer))) == (1, 1)
    monkeypatch.setattr(G, 'uid', iter(['f' * 32, '0' * 32]).__next__)  # made in one second: the id decides
    made_first = make(store, patient, doctor, [rio], hours=48)
    made_second = make(store, patient, doctor, [rio], hours=48)
    third = mention(store, doctor, ops, rio)
    assert (made_first, made_second) == ('f' * 32, '0' * 32)
    assert decide(store, rio, third) == ('build', 'grant') and json.loads(ticket_row(store, rio, third)['chain']) == ['0' * 32]


def test_a_grant_naming_a_room_follows_it_forward_and_never_builds_in_a_replaced_room(env):
    """Test 16 and spec Review Focus 3: X becomes X' and then X'' as members are added; a grant naming X builds in each
    current room, and a mention in X or X', once replaced, reads. A linked_room_id cycle made by hand ends the walk."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    x = room(store, patient, 'Plans', doctor, serenity)
    grant = make(store, patient, doctor, [serenity], rooms=[x], hours=48, budget=20)
    early = mention(store, doctor, x, serenity)  # posted while X was current, asked once it is replaced
    x1 = store.add_participants(patient['id'], x, [family['id']])['id']
    assert decide(store, serenity, mention(store, doctor, x1, serenity)) == ('build', 'grant')
    x2 = store.add_participants(patient['id'], x1, [organizer['id']])['id']
    assert decide(store, serenity, mention(store, doctor, x2, serenity)) == ('build', 'grant')
    assert decide(store, serenity, early) == ('read', 'none')
    assert decide(store, serenity, mention(store, doctor, x, serenity)) == ('read', 'none')
    assert decide(store, serenity, mention(store, doctor, x1, serenity)) == ('read', 'none')
    loop_a, loop_b = room(store, patient, 'Loop A', doctor), room(store, patient, 'Loop B', doctor)
    looped = room(store, patient, 'Looped', doctor, serenity)
    with store.transaction() as db:  # Looped replaced Loop A, which replaced Loop B, which replaced Loop A
        for key, replaced in ((looped, loop_a), (loop_a, loop_b), (loop_b, loop_a)):
            db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (replaced, key))
    assert decide(store, serenity, mention(store, doctor, looped, serenity)) == ('read', 'none')  # the walk ends
    make(store, patient, doctor, [serenity], rooms=[loop_b], hours=48)
    assert decide(store, serenity, mention(store, doctor, looped, serenity)) == ('build', 'grant')  # Loop B is on the walk
    assert len(uses(store, grant)) == 2


def test_one_message_naming_two_ships_under_one_grant_with_one_build_left(env):
    """Test 19 and spec Review Focus 5: the first ship's ticket builds and spends the last build; the second reads."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    grant = make(store, patient, doctor, [serenity, rio], hours=48, budget=2)
    charge(store, grant, 10)
    both = mention(store, doctor, ops, serenity, rio)
    assert decide(store, serenity, both) == ('build', 'grant')
    assert decide(store, rio, both) == ('read', 'none')
    assert [use['ticket_id'] for use in uses(store, grant)][1:] == [ticket_row(store, serenity, both)['id']]


def test_a_grantees_mention_with_an_unusable_created_reads_old_and_never_raises(env):
    """G15 with fresh owner mentions R4: a created that is text or infinite can't be compared with the grant's; the
    ticket reads old, as an owner's would, and the request never fails."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, serenity)
    make(store, patient, doctor, [serenity], hours=48)
    for value in (float('inf'), 'abc'):
        asked = mention(store, doctor, ops, serenity)
        with store.transaction() as db:
            db.execute('UPDATE messages SET created=? WHERE id=?', (value, asked['id']))
        assert decide(store, serenity, asked) == ('read', 'old'), value
