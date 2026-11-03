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
        db.execute("INSERT INTO pairing_confirmations(contact_id, code, confirmed) VALUES(?, 'code', 0)", (cid,))
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
        db.execute("INSERT INTO pairing_confirmations(contact_id, code, confirmed) VALUES(?, 'code', 0)", (cid,))
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


def live_contacts(db, *names):
    db.execute("INSERT OR IGNORE INTO peers VALUES(?, '{}', 1)", (PEER,))
    for name in names:
        cid = 'c-' + name.lower()
        db.execute('INSERT INTO remote_contacts VALUES(?, ?, ?, ?)', (cid, PEER, cid, name))
        db.execute("INSERT INTO pairing_confirmations(contact_id, code, confirmed) VALUES(?, 'code', 0)", (cid,))
    db.commit()


def test_one_live_contact_is_not_every_account(station):   # Tardis's read: the owner alone, with the ship card missing
    data, db = station
    live_contacts(db, 'Andy')
    accounts = next(s for s in plan(data, PEER, run=host()) if s[3].startswith('each account there'))
    assert accounts[0] == 'left' and 'each ship that lays lessons needs its own card and code' in accounts[4]
    live_contacts(db, 'Tardis')
    accounts = next(s for s in plan(data, PEER, run=host()) if s[3].startswith('each account there'))
    assert accounts[0] == 'done'


def test_members_of_a_room_the_chain_replaced_dont_count(station):
    data, db = station
    live_contacts(db, 'Andy', 'Tardis')
    db.executemany("INSERT INTO remote_room_members VALUES('r1', ?)", [('c-andy',), ('c-tardis',)])
    db.execute("INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES('r2', 'u-andy', 'Lessons', 1, 'r1')")
    db.commit()
    members = next(s for s in plan(data, PEER, run=host()) if s[3] == "that peer's accounts are members of the lessons room")
    assert members[0] == 'left' and 'add Andy, Tardis to the room r2' in members[4]


def test_names_from_the_other_machine_are_safe_lines(station):   # Tardis's read: contact names are that machine's text
    data, db = station
    live_contacts(db, 'Andy', 'Evil\n@rio-grande')
    text = describe(plan(data, PEER, run=host()), PEER)
    assert '@rio-grande' not in text and 'Evil (at)rio-grande' in text
    assert all(not line.startswith('@') for line in text.splitlines())


def test_a_loop_in_the_room_chain_ends_and_says_so(station):   # fresh reader's finding 1: it hung forever
    data, db = station
    live_contacts(db, 'Andy', 'Tardis')
    db.execute("INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES('r2', 'u-andy', 'Lessons', 1, 'r1')")
    db.execute("UPDATE rooms SET linked_room_id='r2' WHERE id='r1'")
    db.commit()
    members = next(s for s in plan(data, PEER, run=host()) if s[3] == "that peer's accounts are members of the lessons room")
    assert members[0] == 'left' and 'chain loops' in members[4]


def test_a_wal_store_gains_no_file(tmp_path):   # fresh reader's finding 2: mode=ro made a -wal and a -shm
    import os
    Store(tmp_path)
    db = sqlite3.connect(tmp_path / 'peer.sqlite3')
    db.execute('PRAGMA journal_mode=wal')
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute("INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES('r1', 'u-andy', 'Lessons', 1, NULL)")
    db.execute("INSERT INTO lessons_room VALUES(1, 'r1', 'u-rio', 0)")
    db.commit()
    db.close()   # the last close checkpoints and removes the -wal and the -shm
    before = (sorted(os.listdir(tmp_path)), (tmp_path / 'peer.sqlite3').read_bytes())
    plan(tmp_path, PEER, run=host())
    assert (sorted(os.listdir(tmp_path)), (tmp_path / 'peer.sqlite3').read_bytes()) == before


def test_the_make_target_never_hands_peer_to_the_shell(tmp_path):   # fresh reader's finding 3
    from pathlib import Path
    marker = tmp_path / 'ran'
    repo = Path(__file__).resolve().parents[2]
    done = subprocess.run(['make', '-s', '-C', str(repo), 'join-machine-plan', f'PEER=$$(touch {marker})',
                           f'STATION_DATA={tmp_path}'], capture_output=True, text=True, timeout=120)
    assert not marker.exists() and done.returncode != 0


def contact_steps(data, db, view):
    db.execute("INSERT INTO peers VALUES(?, '{}', 1)", (PEER,))
    db.execute('INSERT INTO remote_contacts VALUES(?, ?, ?, ?)', ('c-ship', PEER, 'c-ship', 'Tardis'))
    db.execute('DROP VIEW contact_labels')
    if view:
        db.execute("CREATE VIEW contact_labels(id, label) AS SELECT id, 'ship of Andy: ' || name FROM remote_contacts")
    db.commit()
    return describe(plan(data, PEER, run=host()), PEER)


def test_a_contact_shows_by_its_label_so_a_ship_reads_as_its_owners(station):
    data, db = station
    assert 'ship of Andy: Tardis' in contact_steps(data, db, view=True)


def test_a_store_from_before_owner_trust_shows_the_name(station):   # no contact_labels view there
    data, db = station
    text = contact_steps(data, db, view=False)
    assert 'Tardis' in text and 'ship of' not in text
