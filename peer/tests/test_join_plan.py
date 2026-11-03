"""make join-machine-plan (superyak_peer.join_plan): each step read from a real station store's tables, nothing changed."""
import sqlite3
import subprocess
import sys

import pytest

from superyak_peer.db import Store
from superyak_peer.join_plan import describe, plan

PEER = '4d' * 32


class Ran:
    def __init__(self, stdout):
        self.stdout = stdout


def host(listening=True, served=True):
    def run(argv, **_):
        if argv[0] == 'systemctl':
            return Ran('active\n' if listening else 'inactive\n')
        return Ran('|-- tcp://smart:7437 (tailnet only)\n' if served else '')
    return run


@pytest.fixture
def station(tmp_path):
    Store(tmp_path)
    db = sqlite3.connect(tmp_path / 'peer.sqlite3')
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute("INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES('r1', 'u-andy', 'Lessons', 1, NULL)")
    db.execute("INSERT INTO lessons_room VALUES(1, 'r1', 'u-rio', 0)")
    db.commit()
    return tmp_path, db


def steps_by_name(steps):
    return {step: (state, who) for state, who, _, step, _ in steps}


def test_a_fresh_machine_shows_every_step_left_with_the_persons_together(station):
    data, _ = station
    steps = steps_by_name(plan(data, PEER, run=host(listening=False, served=False)))
    assert steps["the peer's card paired here"] == ('left', 'Andy')
    assert steps['this station listens for peers'] == ('left', 'Andy')
    assert steps['each account there paired here, with its own code'] == ('left', 'Andy')
    assert steps['the lessons room lists that peer'] == ('left', 'a ship')
    assert steps["that peer's accounts are members of the lessons room"] == ('left', 'Andy')
    text = describe(plan(data, PEER, run=host(listening=False, served=False)), PEER)
    assert text.index('Left for Andy, in one sitting') < text.index('Left for ships') < text.index('To check on that machine')


def test_a_joined_machine_has_nothing_left_here_and_follows_the_chain(station):
    data, db = station
    db.execute("INSERT INTO peers VALUES(?, '{}', 1)", (PEER,))
    for cid, name in (('c-andy', 'Andy'), ('c-ship', 'Tardis')):
        db.execute('INSERT INTO remote_contacts VALUES(?, ?, ?, ?)', (cid, PEER, cid, name))
        db.execute("INSERT INTO pairing_confirmations VALUES(?, 'code', 0)", (cid,))
    db.execute('INSERT INTO lessons_peers VALUES(?, 0)', (PEER,))
    db.execute("INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES('r2', 'u-andy', 'Lessons', 1, 'r1')")
    db.executemany("INSERT INTO remote_room_members VALUES('r2', ?)", [('c-andy',), ('c-ship',)])  # the chain's next room
    db.commit()
    steps = plan(data, PEER, run=host())
    assert [s for s in steps if s[0] == 'left'] == []
    assert 'Left for Andy' not in describe(steps, PEER)


def test_members_missing_from_the_current_room_are_named_and_a_held_contact_isnt_live(station):
    data, db = station
    db.execute("INSERT INTO peers VALUES(?, '{}', 1)", (PEER,))
    for cid, name in (('c-andy', 'Andy'), ('c-ship', 'Tardis')):
        db.execute('INSERT INTO remote_contacts VALUES(?, ?, ?, ?)', (cid, PEER, cid, name))
        db.execute("INSERT INTO pairing_confirmations VALUES(?, 'code', 0)", (cid,))
    db.execute("INSERT INTO contact_holds VALUES('c-ship', 0)")
    db.commit()
    steps = plan(data, PEER, run=host())
    members = next(s for s in steps if s[3] == "that peer's accounts are members of the lessons room")
    assert members[0] == 'left' and 'add Andy to the room r1' in members[4]
    accounts = next(s for s in steps if s[3].startswith('each account there'))
    assert 'Tardis (held)' in accounts[4] and 'Andy (confirmed)' in accounts[4]


def test_it_changes_nothing_in_the_store(station):
    data, _ = station
    before = (data / 'peer.sqlite3').read_bytes()
    plan(data, PEER, run=host())
    assert (data / 'peer.sqlite3').read_bytes() == before


def test_the_cli_refuses_anything_but_a_full_peer_id(tmp_path):
    done = subprocess.run([sys.executable, '-m', 'superyak_peer', 'join-plan', '--data-dir', str(tmp_path), '--peer', '4de98e28'],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and '64 lowercase hex' in done.stderr
