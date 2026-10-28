"""The pair's regression test for the hold before a Bash command: the hook's lessons provider (agent) and the peer's
words-only query and could_hold (lessons-hold-contract, on main at fd72492c), on one tree, against a real store, index
and query, through the real provider and the real hold entry (hold-saves-provider-entries included). Together they
pass; with main's lessons.py from before the contract, three of these failed (City of AI, 2026-10-28), so each half
needs the other."""
import json
import sys
import time
from pathlib import Path

import pytest

from conftest import lesson_body, lesson_ship

REPO = Path(__file__).resolve().parents[2]
AGENT = REPO / 'agent'
sys.path[:0] = [str(AGENT), str(AGENT.parent / 'team')]
COMMAND = 'git push --force origin main'
SHORT = lesson_body(claim='Short values.', command=('git', 'push'))
LONG = lesson_body(claim='Long value.', command=('push --force',))


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Rio Grande's ship asks; Tardis's lessons are laid in Andy's recorded lessons room and indexed. HOME is the
    test's own, docked, so the entry acts and keeps its session records there."""
    from superyak_peer.db import Store
    from superyak_peer.identity import PeerIdentity
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)
    monkeypatch.delenv('SUPERYAK_RUN', raising=False)
    home = tmp_path / 'home' / '.superyak'
    home.mkdir(parents=True)
    (home / 'station.json').write_text('{}')
    store = Store(tmp_path / 'pi')
    PeerIdentity.load_or_create(store.data_dir)
    andy = store.create_user('andy', 'Andy Example', 'a-long-password', is_admin=True)['id']
    ids = {'rio-grande': lesson_ship(store, andy, 'rio-grande')['id'], 'tardis': lesson_ship(store, andy, 'tardis')['id']}
    room = store.create_room(andy, 'Lessons', [ids['rio-grande'], ids['tardis']])['id']
    with store.transaction() as db:
        db.execute('INSERT INTO lessons_room VALUES(1,?,?,?)', (room, ids['rio-grande'], time.time()))

    def lay(*bodies):
        for n, body in enumerate(bodies):
            store.send_message(ids['tardis'], room, f'c{time.time_ns()}{n}', body)
        store.lessons_index(None)

    from superyak_agent import lessons_hook
    settings = lessons_hook.default_settings()   # where dock puts its copy, which the hold entry reads
    assert settings.parent == home
    settings.write_text(json.dumps({'ship': 'rio-grande', 'data_dir': str(store.data_dir),
                                    'state_dir': str(tmp_path / 'state')}))
    return store, settings, home, tmp_path, lay


def receipted(store):
    """The claims of the receipted lessons, from the index's ids."""
    from superyak_peer import lessons
    index = lessons.read_index(Path(store.data_dir) / lessons.INDEX_FILE)
    claims = {item['id']: item['claim'] for item in index['lessons']}
    with store.transaction() as db:
        return [claims.get(row[0], row[0]) for row in db.execute('SELECT lesson_id FROM lesson_receipts ORDER BY created')]


def queries(store):
    with store.transaction() as db:
        return db.execute('SELECT COUNT(*) FROM lesson_queries').fetchone()[0]


def short_id(store, claim):
    from superyak_peer import lessons
    index = lessons.read_index(Path(store.data_dir) / lessons.INDEX_FILE)
    return next(lessons.short_lesson_id(item['id']) for item in index['lessons'] if item['claim'] == claim)


@pytest.mark.parametrize('limit', [1, 3])
def test_values_under_6_bytes_are_never_held_or_receipted(world, limit):
    """The reviewers' M2/M3: `git` and `push` are in the command, but only `push --force` can hold it. Only that lesson
    comes back, is receipted and is held, at limit 1 (where the short one used to take the only slot) and at 3."""
    from superyak_agent import lessons_hold
    store, settings, _, _, lay = world
    lay(SHORT, LONG)
    held = lessons_hold.candidates(COMMAND, {'session': {'id': f's{limit}', 'transcript': None}}, time.time(), limit,
                                   settings=settings, env={})
    long_id = short_id(store, 'Long value.')   # at limit 1 a checklist leads, so the block has its own Lesson line
    assert len(held) == 1 and long_id in held[0].text and 'claim: Long value.' in held[0].text
    assert 'Short values.' not in held[0].text and receipted(store) == ['Long value.']


def test_a_head_asks_once_and_a_lesson_already_shown_asks_nothing_through_the_entry(world):
    """Rio Grande's four-runs probe, pinned at the entry: the first run of a head holds and receipts; its re-run
    passes; a new head whose only lesson was shown asks could_hold again with `seen` and starts no query; repeats of
    that head start none either, now that the entry keeps the provider's notes."""
    from superyak_agent import hold
    store, _, home, tmp_path, lay = world
    lay(LONG)

    def run(command):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'session_id': 's1', 'cwd': str(tmp_path),
                   'tool_input': {'command': command}}
        return hold.decide(payload, home, time.time(), time.monotonic())

    first = run(COMMAND)
    assert first['hookSpecificOutput']['permissionDecision'] == 'deny' and queries(store) == 1
    assert run(COMMAND) is None                       # the re-run passes
    for _ in range(4):
        assert run('sudo git push --force origin other') is None   # a new head ("sudo git") holding the same value
    assert queries(store) == 1 and receipted(store) == ['Long value.']


def test_the_oldest_of_129_seen_is_held_again_rather_than_receipted_and_dropped(world):
    """Rio Grande's correction: with 129 seen, the oldest isn't among the ids told, so the query answers it and writes a
    receipt; the provider then holds it rather than dropping it."""
    from superyak_agent import lessons_hold
    store, settings, _, tmp_path, lay = world
    lay(LONG)
    long_id = short_id(store, 'Long value.')
    others = [f'{n:08x}-{n:08x}' for n in range(128)]
    transcript = tmp_path / 'transcript.jsonl'
    transcript.write_text(''.join(json.dumps({'type': 'attachment', 'attachment': {'content': [f'Lesson {i} from serenity']}})
                                  + '\n' for i in [long_id] + others))
    held = lessons_hold.candidates(COMMAND, {'session': {'id': 's9', 'transcript': str(transcript)}}, time.time(), 3,
                                   settings=settings, env={})
    assert len(held) == 1 and long_id in held[0].text and receipted(store) == ['Long value.']


def test_the_hold_bytes_agree():
    from superyak_agent import lessons_hold
    from superyak_peer import lessons
    assert lessons_hold.HOLD_BYTES == lessons.HOLD_BYTES == 6
