"""Ship status, build step 5: the watcher asks the station for decisions, keeps a deferred list and moves on, stays
silent on claim and notice messages, answers with reply_to, and says first when a mention run was read-only (spec S5,
S6, R10, R12, R20, R22, R23, R32)."""
import json

import pytest
from superyak_agent.runs import RunTimeout
from superyak_agent.watch import FALLBACK, READ_ONLY_LINE, TIMEOUT_NOTE
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
