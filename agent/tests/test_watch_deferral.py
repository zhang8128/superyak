"""Ship status, build step 5: the watcher asks the station for decisions, keeps a deferred list and moves on, stays
silent on claim and notice messages, answers with reply_to, and says first when a mention run was read-only (spec S5,
S6, R10, R12, R20, R22, R23, R32)."""
import json

import pytest
from superyak_agent.runs import RunTimeout
from superyak_agent.watch import DEFERRED_PER_CYCLE, FALLBACK, READ_ONLY_LINE, TIMEOUT_NOTE
from test_watch import FakeRunner, bodies, watcher


def defer(fake, *messages):
    for m in messages:
        fake.decide[m['id']] = {'decision': 'defer', 'message_id': m['id'], 'first_deferred': fake.clock}


def test_the_watcher_skips_deferred_mentions_and_keeps_going(station, ship_config, tmp_path):
    """R10: a deferred mention runs nothing and the mention cursor moves past it, so a later mention runs at once;
    each cycle re-asks at most 20 deferred mentions, oldest first; re-asking a deferred mention from another ship
    spends nothing of the five-an-hour budget for ship exchanges."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    held = [fake.say(room, defiant, '@serenity a question from a ship')] + [fake.say(room, jenn, f'@serenity question {n}') for n in range(23)]
    later = fake.say(room, jenn, '@serenity a later question')
    defer(fake, *held)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 1 and [mid for _, mid, _ in runner.calls] == [later['id']]
    assert w.state['mention_seq'] == fake.mention_rows[-1]['seq']
    assert [d['message_id'] for d in w.state['deferred']] == [m['id'] for m in held]
    fake.ticket_bodies.clear()
    for _ in range(6):
        assert w.cycle() == 0
    assert [b['message_id'] for b in fake.ticket_bodies] == [m['id'] for m in held[:20]] * 6
    assert not any('Pausing my replies' in b for b in bodies(fake, room)) and len(runner.calls) == 1


def test_a_mention_arriving_with_the_deferred_list_full_gets_todays_ticket(station, ship_config, tmp_path):
    """R10 (96d55368, edit 2): with 100 deferred, mention 101's request carries no `decisions`, so it gets today's
    ticket and a read-only run, never a deferral the watcher couldn't keep."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    held = [fake.say(room, jenn, f'@serenity question {n}') for n in range(100)]
    defer(fake, *held)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    for _ in range(2):                                     # mentions come 50 to a page
        assert w.cycle() == 0
    assert len(w.state['deferred']) == 100
    extra = fake.say(room, jenn, '@serenity question 101')
    defer(fake, extra)
    fake.ticket_bodies.clear()
    assert w.cycle() == 1 and [mid for _, mid, _ in runner.calls] == [extra['id']]
    sent = {b['message_id']: b for b in fake.ticket_bodies}
    assert 'decisions' not in sent[extra['id']] and sent[held[0]['id']]['decisions'] == ['defer', 'answered']
    assert len(w.state['deferred']) == 100 and bodies(fake, room)[-1].startswith(READ_ONLY_LINE)


def test_an_old_watcher_never_sees_defer_and_a_new_watcher_reads_no_decision_as_run(station, ship_config, tmp_path):
    """R23, agent half: the watcher asks for decisions, and a ticket without `decision` (an older station) runs, as
    today. The station half is Task 5's test_an_old_watcher_never_sees_defer."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity what is this?')
    fake.ticket_override[asked['id']] = (200, {'id': 'tx', 'mode': 'read', 'basis': 'none', 'footer': '', 'status': 'running'})
    runner = FakeRunner()
    assert watcher(fake, ship_config, tmp_path, runner).cycle() == 1 and [mid for _, mid, _ in runner.calls] == [asked['id']]
    assert fake.ticket_bodies == [{'message_id': asked['id'], 'decisions': ['defer', 'answered']}]


def test_a_ticket_for_a_claim_or_notice_is_422_and_the_watcher_stays_silent(station, ship_config, tmp_path):
    """R20, agent half: a 422 is done at once: no run, no FALLBACK, no failure counted, and the cursor moves on. The
    station half is Task 5's test_a_system_message_never_starts_a_run_or_counts_as_answered."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    claimed = fake.say(room, jenn, 'Claimed `spec:d7` until 18:00 UTC: ask @serenity')
    fake.ticket_override[claimed['id']] = (422, {'error': 'Station notices and claim messages are never answered'})
    later = fake.say(room, jenn, '@serenity a real question')
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 1 and [mid for _, mid, _ in runner.calls] == [later['id']]
    assert FALLBACK not in bodies(fake, room) and w.state['failures'] == {} and claimed['id'] in w.state['answered']


def test_the_read_only_line_follows_the_mode_the_run_used(station, ship_config, tmp_path):
    """R12: a read run's reply starts with the line, and so does a resident's run on a build ticket (downgraded,
    watch.py:116); a build run's reply, a resident's DM reply, FALLBACK and the timeout note don't."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    built = fake.say(room, andy, '@serenity add a NOTES file')
    read = fake.say(room, jenn, '@serenity what is this repo?')
    watcher(fake, ship_config, tmp_path / 'serenity', FakeRunner()).cycle()
    replies = {m['client_message_id']: m['body'] for m in fake.rooms[room]['messages']}
    assert replies[f'reply-{read["id"]}'] == f'{READ_ONLY_LINE}\n\nread answer to {read["id"]}'
    assert replies[f'reply-{built["id"]}'].startswith('Added notes')

    odo = fake.user('odo', 'Odo', 'ship', None, key='odo-key')
    ops, dm = fake.room('Ops', andy, jenn, odo), fake.room('Ask Odo', jenn, odo)
    asked = fake.say(ops, andy, '@odo fix it')
    fake.ticket_override[asked['id']] = (200, {'id': 'tx', 'mode': 'build', 'basis': 'owner', 'footer': '', 'status': 'running'})
    door = fake.say(dm, jenn, 'where is the door?')
    odo_config = {'station': 'http://station.test', 'ship': 'odo', 'ship_name': 'Odo', 'owner_id': None, 'key': 'odo-key', 'workspace': str(tmp_path)}
    watcher(fake, odo_config, tmp_path / 'odo', FakeRunner(), key='odo-key', resident=True).cycle()
    assert bodies(fake, ops)[-1] == f'{READ_ONLY_LINE}\n\nread answer to {asked["id"]}'
    assert bodies(fake, dm)[-1] == f'read answer to {door["id"]}'

    lab = fake.room('Lab', andy, jenn, serenity)
    finished = fake.say(lab, jenn, '@serenity this one was answered before')
    fake.ticket_override[finished['id']] = (409, {'error': 'This message has already been answered'})
    fake.say(lab, jenn, '@serenity this one is slow')
    watcher(fake, ship_config, tmp_path / 'lab', FakeRunner(error=RunTimeout('read run exceeded 1200 seconds'))).cycle()
    assert bodies(fake, lab)[-2:] == [FALLBACK, TIMEOUT_NOTE]


@pytest.mark.parametrize('kind', ['notice', 'claim'])
def test_a_system_message_never_starts_a_run_or_counts_as_answered(station, tmp_path, kind):
    """R32, R20, resident half: in a person's DM with Odo, a notice or a person's claim message, even quoting @odo,
    starts no run, and the person's next message is answered. The station half is Task 5's test of the same name."""
    fake, andy, jenn, serenity = station
    odo = fake.user('odo', 'Odo', 'ship', None, key='odo-key')
    system = fake.user('_station', 'Station', 'system')
    dm = fake.room('Ask Odo', jenn, odo)
    marked = fake.say(dm, system if kind == 'notice' else jenn, 'Claimed `spec:d7`: @odo please build it now')
    fake.kinds[marked['id']] = kind
    fake.mention_rows = [r for r in fake.mention_rows if r['message_id'] != marked['id']]  # the station records none (Task 4)
    runner = FakeRunner()
    config = {'station': 'http://station.test', 'ship': 'odo', 'ship_name': 'Odo', 'owner_id': None, 'key': 'odo-key', 'workspace': str(tmp_path)}
    w = watcher(fake, config, tmp_path, runner, key='odo-key', resident=True)
    assert w.cycle() == 0 and runner.calls == []
    asked = fake.say(dm, jenn, 'where is the door?')
    assert w.cycle() == 1 and [mid for _, mid, _ in runner.calls] == [asked['id']]


def test_a_restarted_watcher_re_asks_every_mention_it_deferred(station, ship_config, tmp_path):
    """R21: deferrals live in the saved state, so a watcher re-created from it (a restart) re-asks each pending one
    and drops none, though the mention cursor has moved past them; each answer still says first that it read only,
    since the saved record keeps the station's seq (R38)."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    held = [fake.say(room, jenn, f'@serenity question {n}') for n in range(3)]
    defer(fake, *held)
    assert watcher(fake, ship_config, tmp_path, FakeRunner()).cycle() == 0
    fake.ticket_bodies.clear()
    runner = FakeRunner()
    again = watcher(fake, ship_config, tmp_path, runner)
    assert again.cycle() == 0 and [b['message_id'] for b in fake.ticket_bodies] == [m['id'] for m in held]
    assert [d['message_id'] for d in again.state['deferred']] == [m['id'] for m in held] and runner.calls == []
    for m in held:
        del fake.decide[m['id']]                           # the watch ended: the station now decides `run`
    assert watcher(fake, ship_config, tmp_path, runner).cycle() == 3
    assert [mid for _, mid, _ in runner.calls] == [m['id'] for m in held]
    assert bodies(fake, room)[-3:] == [f'{READ_ONLY_LINE}\n\nread answer to {m["id"]}' for m in held]


@pytest.mark.parametrize('ending', ['run', 'answered', '422'])
def test_a_deferred_mention_leaves_the_list_however_it_ends(station, ship_config, tmp_path, ending):
    """R10, R21: a re-ask that ends a deferral, by a run, by `answered` or by a 422 (a claim or a notice), takes the
    mention off the deferred list for good, so stale entries can never fill it to 100. The station's 120-minute bound
    comes back as a run: test_ship_agent's `bound` ending checks it against the real station."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 0 and [d['message_id'] for d in w.state['deferred']] == [asked['id']]
    if ending == 'run':
        del fake.decide[asked['id']]
    elif ending == 'answered':
        fake.decide[asked['id']] = {'decision': 'answered', 'message_id': asked['id']}
    else:
        fake.ticket_override[asked['id']] = (422, {'error': 'Claims and notices are never answered'})
    assert w.cycle() == int(ending == 'run')
    assert w.state['deferred'] == [] and json.loads((tmp_path / 'state.json').read_text())['deferred'] == []
    fake.ticket_bodies.clear()
    assert w.cycle() == 0 and fake.ticket_bodies == [] and len(runner.calls) == int(ending == 'run')


def test_a_labelled_reply_names_the_mention_it_answers(station, ship_config, tmp_path):
    """R22, at the agent level (Rio Grande, eded14c9): the watcher's labelled reply, posted with its run ticket,
    carries reply_to set to the mention, so a later cycle reads the mention as answered."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity what is this repo?')
    watcher(fake, ship_config, tmp_path / 'serenity', FakeRunner()).cycle()
    reply = next(m for m in fake.rooms[room]['messages'] if m['client_message_id'] == f'reply-{asked["id"]}')
    assert fake.sources.get(reply['id']) and fake.replies.get(reply['id']) == asked['id']  # labelled, and answering


def _listed(w, fake, *messages):
    """Put mentions on the watcher's deferred list from its state alone, past the mention cursor, as a restart or a
    hand-edited state file could: the station holds no deferral for them."""
    rows = {r['message_id']: r for r in w.client.mentions(0)}
    w.state['mention_seq'] = max(r['seq'] for r in rows.values())
    w.state['deferred'] = [{k: rows[m['id']][k] for k in ('message_id', 'room_id', 'author', 'seq')} for m in messages]
    w.save()


def test_a_reask_without_a_station_deferral_is_charged(station, ship_config, tmp_path):
    """R37 (whole-branch review 137f0a38): only the station's answer spares the five-an-hour ship budget. A listed
    mention whose run comes back without `first_deferred` is charged as a new mention, so state alone can't bypass
    the budget; the over-budget ones get the pause note and their tickets are finished, never left running."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = [fake.say(room, defiant, f'@serenity ship question {n}') for n in range(8)]
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, *asked)
    w.cycle()
    assert len(runner.calls) == 5 and sum('Pausing my replies' in b for b in bodies(fake, room)) == 1
    assert all(t['status'] == 'finished' for t in fake.tickets.values() if t['message_id'] in {m['id'] for m in asked[5:]})
    assert w.state['deferred'] == []


def test_a_reask_the_station_held_spends_no_budget(station, ship_config, tmp_path):
    """R37: a run that carries the station's `first_deferred` resolves a deferral the station held, so it is not
    charged, however many there are."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = [fake.say(room, defiant, f'@serenity ship question {n}') for n in range(8)]
    for n, m in enumerate(asked):
        fake.decide[m['id']] = {'id': f'held-{n}', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '',
                                'status': 'running', 'decision': 'run', 'first_deferred': 1.0}
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, *asked)
    w.cycle()
    assert len(runner.calls) == 8 and not any('Pausing my replies' in b for b in bodies(fake, room))


def test_a_reask_asks_for_the_ticket_first_and_fetches_the_room_only_to_run(station, ship_config, tmp_path):
    """Review minor 2: a listed mention is re-asked without fetching its room; the room is fetched only for a run."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a question')
    defer(fake, asked)
    gets = []

    def counting(method, url, headers, data):
        if method == 'GET' and url.endswith(f'/api/chats/{room}'):
            gets.append(url)
        return fake(method, url, headers, data)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.client = type(w.client)('http://station.test', 'serenity-key', transport=counting)
    w.me = w.client.me()
    _listed(w, fake, asked)
    gets.clear()
    for _ in range(3):
        assert w.cycle() == 0
    assert gets == []
    del fake.decide[asked['id']]
    assert w.cycle() == 1 and len(gets) == 1 and [mid for _, mid, _ in runner.calls] == [asked['id']]


def test_answered_finishes_an_earlier_ticket(station, ship_config, tmp_path):
    """Review minor 3: a run that failed leaves its ticket running; when the station then says `answered` (a session
    replied with reply_to), the watcher finishes that ticket and forgets it, so no phantom live run stays."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a question')
    runner = FakeRunner(error=RuntimeError('the run broke'))
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 0 and asked['id'] in w.state['tickets']
    earlier = w.state['tickets'][asked['id']]
    assert fake.tickets[earlier]['status'] == 'running'
    fake.decide[asked['id']] = {'decision': 'answered', 'message_id': asked['id']}
    w.cycle()
    assert fake.tickets[earlier]['status'] == 'finished' and asked['id'] not in w.state['tickets']


def test_a_retry_of_a_held_reask_is_not_charged_again(station, ship_config, tmp_path):
    """R37: the station drops its deferral row when it issues the run's ticket, so a retry after a failed run gets the
    same running ticket back without `first_deferred`. That ticket was spared when the station issued it, so the
    retry is not charged as a new mention."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    issued = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '', 'status': 'running',
              'decision': 'run'}
    fake.decide[asked['id']] = dict(issued, first_deferred=1.0)
    runner = FakeRunner(error=RuntimeError('the run broke'))
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    w.state['ship_exchanges'][f'{room}:{defiant["id"]}'] = [w.clock()] * 5  # the hour's budget is spent
    w.cycle()
    assert w.state['tickets'] == {asked['id']: 'held-1'}
    fake.decide[asked['id']] = issued
    runner.error = None
    w.cycle()
    assert len(runner.calls) == 2 and not any('Pausing my replies' in b for b in bodies(fake, room))
    assert f'read answer to {asked["id"]}' in '\n'.join(bodies(fake, room))


def test_a_retry_with_a_different_ticket_id_is_charged(station, ship_config, tmp_path):
    """R37 (Rio Grande, 7d9dad84): only the exact ticket id the station issued for this same mention spares a retry.
    A `run` under a new ticket id, without `first_deferred`, is a new decision and is charged like a new mention."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    issued = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '', 'status': 'running',
              'decision': 'run'}
    fake.decide[asked['id']] = dict(issued, first_deferred=1.0)
    runner = FakeRunner(error=RuntimeError('the run broke'))
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    w.state['ship_exchanges'][f'{room}:{defiant["id"]}'] = [w.clock()] * 5  # the hour's budget is spent
    w.cycle()
    assert w.state['tickets'] == {asked['id']: 'held-1'}
    fake.decide[asked['id']] = dict(issued, id='other-2')  # a different ticket, no first_deferred
    runner.error = None
    w.cycle()
    assert len(runner.calls) == 1 and any('Pausing my replies' in b for b in bodies(fake, room))


def _siblings(fake, andy, serenity):
    rio = fake.user('rio-grande', 'Rio Grande', 'ship', andy['id'], key='rio-key')
    tardis = fake.user('tardis', 'Tardis', 'ship', andy['id'], key='tardis-key')
    fake.room('Superyak: all hands', andy, serenity, rio, tardis)
    return rio, tardis


def test_a_deferred_breakout_mention_keeps_its_mark_and_its_budget(station, ship_config, tmp_path):
    """Breakouts R12: a breakout mention on the deferred list keeps its mark, so a re-ask the station didn't hold is
    charged to the mentioning ship's budget across breakouts, never to a room's."""
    fake, andy, jenn, serenity = station
    rio, tardis = _siblings(fake, andy, serenity)
    room = fake.breakout('Sync', rio, serenity)
    asked = fake.say(room, rio, '@serenity can you check?')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 0 and w.state['deferred'] == [
        {'message_id': asked['id'], 'room_id': room, 'author': rio, 'seq': 1, 'breakout': True,
         'first_deferred': fake.decide[asked['id']]['first_deferred']}]
    del fake.decide[asked['id']]                       # the station decides `run`, holding no deferral: charged
    w.state['ship_exchanges'][f'breakouts:{rio["id"]}'] = [w.clock()] * 5
    assert w.cycle() == 1 and runner.calls == [] and w.state['deferred'] == []
    assert bodies(fake, room)[-1] == 'Pausing my replies to @rio-grande for the rest of the hour in breakouts, so we do not loop.'


def test_membership_is_fixed_and_leaving_works(station, ship_config, tmp_path):
    """R5, the watcher's half (breakouts S3): once this ship has left a breakout, a ticket for a mention there gets 404,
    and the watcher treats it as a 422: done, silently, with no run, no post and no failure counted, and off the
    deferred list for good."""
    fake, andy, jenn, serenity = station
    rio, tardis = _siblings(fake, andy, serenity)
    room = fake.breakout('Sync', rio, serenity, tardis)
    asked = fake.say(room, rio, '@serenity @tardis can you check?')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    assert w.cycle() == 0 and [d['message_id'] for d in w.state['deferred']] == [asked['id']]
    del fake.decide[asked['id']]
    w.client.leave_room(room)
    said = len(fake.rooms[room]['messages'])
    assert w.cycle() == 0 and runner.calls == [] and len(fake.rooms[room]['messages']) == said
    assert w.state['deferred'] == [] and w.state['failures'] == {} and asked['id'] in w.state['answered']
    fake.ticket_bodies.clear()
    assert w.cycle() == 0 and fake.ticket_bodies == []


def test_a_ticket_404_outside_a_breakout_is_still_a_failure(station, ship_config, tmp_path):
    """Breakouts R5 changes nothing elsewhere: a mention in a person's room whose ticket gets 404 (the ship was taken
    out of the room) is a failure, retried on later cycles, as before."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a question')
    defer(fake, asked)
    w = watcher(fake, ship_config, tmp_path, FakeRunner())
    assert w.cycle() == 0
    del fake.decide[asked['id']]
    fake.rooms[room]['member_ids'].remove(serenity['id'])
    assert w.cycle() == 0 and w.state['failures'] == {asked['id']: 1}
    assert [d['message_id'] for d in w.state['deferred']] == [asked['id']]


def test_a_hand_listed_entry_the_station_then_defers_is_charged_once(station, ship_config, tmp_path):
    """Ship-status re-review of 5374784, follow-up 1: an entry on the deferred list that the station never deferred
    for this watcher (hand-listed) skips the charge at entry. If the station's first answer is then `defer` and its
    run later carries `first_deferred`, the mention was never charged at all. It must be charged exactly once."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    assert w.cycle() == 0  # the station's first answer: defer
    fake.decide[asked['id']] = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '',
                                'status': 'running', 'decision': 'run', 'first_deferred': 1.0}
    w.cycle()
    assert len(runner.calls) == 1
    assert len(w.state['ship_exchanges'].get(f'{room}:{defiant["id"]}', [])) == 1


def test_a_lost_run_response_for_a_deferral_the_station_held_is_not_charged_again(station, ship_config, tmp_path):
    """Follow-up 2: a ship's mention is charged once at entry, then deferred by the station. The station issues its
    run, but the response is lost; the retry gets the same running ticket back without `first_deferred` (the station
    dropped its deferral row on issue), and the watcher never recorded that ticket's id. With the hour's budget spent
    meanwhile, today's code charges it again and drops it with a pause note. It must run, uncharged."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    key = f'{room}:{defiant["id"]}'
    assert w.cycle() == 0 and len(w.state['ship_exchanges'][key]) == 1  # charged at entry, then deferred
    issued = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '', 'status': 'running',
              'decision': 'run'}
    fake.decide[asked['id']] = dict(issued, first_deferred=1.0)
    lost = []

    def losing(method, url, headers, data):
        if method == 'POST' and url.endswith('/api/ships/me/tickets') and not lost:
            fake(method, url, headers, data)  # the station issues the run ...
            lost.append(url)
            raise OSError('connection reset')  # ... and its answer never arrives
        return fake(method, url, headers, data)
    w.client = type(w.client)('http://station.test', 'serenity-key', transport=losing)
    assert w.cycle() == 0 and lost and runner.calls == []
    fake.decide[asked['id']] = dict(issued, first_deferred=1.0)  # the fixed station echoes it on the re-send (F3)
    w.state['ship_exchanges'][key] = [w.clock()] * 5  # the hour's budget is spent meanwhile
    w.cycle()
    assert len(runner.calls) == 1 and not any('Pausing my replies' in b for b in bodies(fake, room))
    assert len(w.state['ship_exchanges'][key]) == 5


def test_a_normally_deferred_ship_mention_is_charged_once_across_defers(station, ship_config, tmp_path):
    """F2: a ship's mention charged at entry and then deferred records the station's first_deferred, so later defers
    and the run that resolves the deferral never charge it again."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    for _ in range(3):
        assert w.cycle() == 0
    first = fake.decide[asked['id']]['first_deferred']
    assert w.state['deferred'][0]['first_deferred'] == first
    fake.decide[asked['id']] = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '',
                                'status': 'running', 'decision': 'run', 'first_deferred': first}
    w.cycle()
    assert len(runner.calls) == 1 and len(w.state['ship_exchanges'][f'{room}:{defiant["id"]}']) == 1


def test_an_over_budget_hand_listed_entry_gets_the_pause_note_at_its_defer(station, ship_config, tmp_path):
    """F2: charged at its first defer and over the hour's budget, the hand-listed entry gets the pause note and
    leaves the list, as an over-budget new mention does."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    w.state['ship_exchanges'][f'{room}:{defiant["id"]}'] = [w.clock()] * 5
    w.cycle()
    assert runner.calls == [] and w.state['deferred'] == []
    assert sum('Pausing my replies' in b for b in bodies(fake, room)) == 1


def test_a_persons_hand_listed_entry_is_never_charged(station, ship_config, tmp_path):
    """F2 (plan review of 4fa215b, should-fix 1): the hour's budget is for ships only (R12). A person's hand-listed
    entry, deferred again and again with that key's budget already spent, is never charged and never paused."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a person question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    key, spent = f'{room}:{jenn["id"]}', [w.clock()] * 5
    w.state['ship_exchanges'][key] = list(spent)  # a guard that counted people would pause here
    for _ in range(3):
        assert w.cycle() == 0
    assert runner.calls == [] and len(w.state['deferred']) == 1
    assert not any('Pausing my replies' in b for b in bodies(fake, room))
    assert w.state['ship_exchanges'][key] == spent


def test_a_hand_listed_entry_deferred_again_and_again_is_charged_once(station, ship_config, tmp_path):
    """F2: the first defer charges a hand-listed ship entry and records the station's first_deferred on it, so the
    defers after it charge nothing more."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    for _ in range(3):
        assert w.cycle() == 0
    assert len(w.state['ship_exchanges'][f'{room}:{defiant["id"]}']) == 1
    assert len(w.state['deferred']) == 1 and runner.calls == []
    assert not any('Pausing my replies' in b for b in bodies(fake, room))


def test_an_upgraded_watcher_charges_none_of_its_carried_over_entries(station, ship_config, tmp_path):
    """Ship-status fixes S1: every released watcher charged a ship's mention at entry, before listing it, so the
    entries an older watcher carried over were charged already. The upgraded watcher stamps them at its first start
    and charges none of them again, nor drops any over the budget."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = [fake.say(room, defiant, f'@serenity ship question {n}') for n in range(5)]
    defer(fake, *asked)
    runner = FakeRunner()
    w0 = watcher(fake, ship_config, tmp_path, runner)
    w0.me = w0.client.me()
    _listed(w0, fake, *asked)
    w0.state.pop('listed_charged', None)  # a file written by main's watcher: no flag, no first_deferred
    w0.save()
    w = watcher(fake, ship_config, tmp_path, runner)
    for _ in range(-(-len(asked) // DEFERRED_PER_CYCLE) + 1):
        assert w.cycle() == 0
    assert not w.state['ship_exchanges'].get(f'{room}:{defiant["id"]}')
    assert not any('Pausing my replies' in b for b in bodies(fake, room))
    assert runner.calls == [] and len(w.state['deferred']) == 5


def test_an_entry_hand_added_after_the_first_start_is_still_charged_once(station, ship_config, tmp_path):
    """S1: the stamp is for the first start only. An entry the owner lists by hand later is charged once, across a
    restart."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    w = watcher(fake, ship_config, tmp_path, runner)  # a restart: the flag is on the file now, so nothing is stamped
    for _ in range(3):
        assert w.cycle() == 0
    assert len(w.state['ship_exchanges'][f'{room}:{defiant["id"]}']) == 1
    assert len(w.state['deferred']) == 1 and runner.calls == []
    assert not any('Pausing my replies' in b for b in bodies(fake, room))


def test_a_full_deferred_list_watcher_gets_answered_and_tells_the_run(station, ship_config, tmp_path):
    """Fresh owner mentions, R8: with 100 deferred, the next mention asks without `decisions`, so the station's
    `answered` basis reaches the watcher, and the read-only run is told why."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    held = [fake.say(room, jenn, f'@serenity question {n}') for n in range(100)]
    defer(fake, *held)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    for _ in range(2):
        assert w.cycle() == 0
    assert len(w.state['deferred']) == 100
    extra = fake.say(room, andy, '@serenity question 101')
    defer(fake, extra)
    fake.ticket_override[extra['id']] = (200, {'id': 'tx', 'mode': 'read', 'basis': 'answered', 'footer': '', 'status': 'running'})
    fake.ticket_bodies.clear()
    assert w.cycle() == 1 and [mid for _, mid, _ in runner.calls] == [extra['id']]
    sent = {b['message_id']: b for b in fake.ticket_bodies}
    assert 'decisions' not in sent[extra['id']]
    assert 'already answered this mention in this room' in runner.calls[0][2]
