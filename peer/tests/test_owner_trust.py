import base64
from datetime import datetime, timezone
import json
import re
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import PeerIdentity, canonical, check_ship_assertion, make_ship_assertion, pairing_code
from superyak_peer.owner_trust import (OWNER_TRUST_STATEMENTS, OWNER_TRUST_SCHEMA, code_current, live_trust,
                                       settle_owner_trust)

NOW = 1_800_000_000


def run(*args):
    return subprocess.run([sys.executable, '-m', 'superyak_peer', *map(str, args)], capture_output=True, text=True)


@pytest.fixture
def machine(tmp_path):
    store = Store(tmp_path / 'home')
    person = store.create_user('andy-b', 'Andy B', 'a-long-password', is_admin=True)
    with store.transaction() as db:
        ship = store._new_ship(db, 'tardis', 'Tardis', person['id'])
    fed = Federation(store, endpoint='https://localhost:7435')
    store.claim_federation_mode('push')
    return store, person, ship, fed


def assertion_for(machine, **over):
    store, person, ship, fed = machine
    values = dict(ship_id=ship['id'], ship_name='tardis', owner_id=person['id'], now=NOW)
    values.update(over)
    return make_ship_assertion(fed.identity, **values)


def card_of(machine):
    store, person, ship, fed = machine
    return fed.identity.card('https://localhost:7435', {'id': ship['id'], 'name': 'tardis'})


def refused(card, assertion, now=NOW):
    with pytest.raises(Problem) as caught:
        check_ship_assertion(card, assertion, now)
    assert caught.value.status == 400


def test_an_assertion_verifies_under_its_peers_card(machine):
    record = check_ship_assertion(card_of(machine), assertion_for(machine), NOW)
    assert record['ship_name'] == 'tardis' and record['owner_id'] == machine[1]['id']
    assert set(assertion_for(machine)) == {'record', 'signature'}


def test_an_assertion_signed_by_another_key_or_edited_is_refused(machine, tmp_path):
    other = Federation(Store(tmp_path / 'other'), endpoint='https://localhost:7435')
    other.store.create_user('zed', 'Zed', 'a-long-password', is_admin=True)
    forged = make_ship_assertion(other.identity, ship_id='x', ship_name='tardis', owner_id='y', now=NOW)
    refused(card_of(machine), forged)
    # names this peer's station, but the signature is by another key over the same canonical record
    record = dict(assertion_for(machine)['record'])
    import base64
    wrong_key = base64.b64encode(other.identity.key.sign(canonical(record))).decode()
    refused(card_of(machine), {'record': record, 'signature': wrong_key})
    edited = assertion_for(machine)
    edited['record']['ship_name'] = 'odo'
    refused(card_of(machine), edited)


def test_an_expired_or_long_or_future_assertion_is_refused(machine):
    card = card_of(machine)
    refused(card, assertion_for(machine, now=NOW, days=0))  # expires == issued
    expired = assertion_for(machine, now=NOW - 86400, days=1)  # expires == now
    refused(card, expired)
    long_one = assertion_for(machine)
    long_one['record']['expires'] = NOW + 30 * 86400 + 1
    resign(machine, long_one)
    refused(card, long_one)
    future = assertion_for(machine, now=NOW + 301)
    refused(card, future)
    check_ship_assertion(card, assertion_for(machine, now=NOW + 300), NOW)
    check_ship_assertion(card, assertion_for(machine, now=NOW), NOW)


def signed(machine, **fields):
    record = dict(assertion_for(machine)['record'], **fields)
    return {'record': record, 'signature': machine[3].identity.sign_record(record)}


def test_times_are_checked_by_rule_not_by_luck(machine):
    card = card_of(machine)
    refused(card, signed(machine, issued=float(NOW), expires=NOW + 86400))
    refused(card, signed(machine, issued=True, expires=86401), now=0)
    refused(card, signed(machine, issued=NOW + 100, expires=NOW + 50))
    refused(card, signed(machine, issued=NOW, expires=NOW))
    refused(card, signed(machine, issued=NOW, expires=float(NOW + 86400)))


def resign(machine, assertion):
    if any(v != v for v in assertion['record'].values()):
        return  # NaN has no canonical JSON, so it can't be signed: the old signature stays and fails
    assertion['signature'] = machine[3].identity.sign_record(assertion['record'])


@pytest.mark.parametrize('bad', [True, 1.5, float('nan'), '1'])
def test_assertion_times_must_be_whole_seconds(machine, bad):
    assertion = assertion_for(machine)
    assertion['record']['issued'] = bad
    resign(machine, assertion)
    refused(card_of(machine), assertion)
    assertion = assertion_for(machine)
    assertion['record']['expires'] = bad
    resign(machine, assertion)
    refused(card_of(machine), assertion)


def export(machine, tmp_path, username, out='out'):
    return run('export-ship', '--data-dir', machine[0].data_dir, '--username', username,
               '--endpoint', 'https://localhost:7435', '--out', tmp_path / out)


def test_export_ship_writes_a_card_and_assertion_and_no_code(machine, tmp_path):
    import time
    done = export(machine, tmp_path, 'tardis')
    assert done.returncode == 0, done.stderr
    out = tmp_path / 'out'
    card = json.loads((out / 'tardis.card.json').read_text())
    assertion = json.loads((out / 'tardis.assertion.json').read_text())
    record = check_ship_assertion(card, assertion, time.time())
    assert record['ship_name'] == 'tardis' and card['participant']['name'] == 'tardis'
    _, person, _, fed = machine
    person_card = fed.card(person['id'])
    assert canonical({**card, 'participant': 0}) == canonical({**person_card, 'participant': 0})
    assert str(out / 'tardis.card.json') in done.stdout
    for text in (done.stdout, done.stderr):
        assert not re.search(r'[0-9a-f]{32}', text)
        assert not re.search(r'[0-9a-f]{4}( [0-9a-f]{4}){7}', text)


def test_export_ship_refuses_a_person_and_an_ownerless_ship(machine, tmp_path):
    machine[0].create_station_ship('odo', 'Odo')
    person = export(machine, tmp_path, 'andy-b')
    assert person.returncode == 1 and 'not a ship' in person.stderr
    ownerless = export(machine, tmp_path, 'odo')
    assert ownerless.returncode == 1 and 'owner' in ownerless.stderr
    assert not (tmp_path / 'out').exists() or not list((tmp_path / 'out').iterdir())


def test_export_ship_never_makes_an_identity(tmp_path):
    store = Store(tmp_path / 'home')
    person = store.create_user('andy-b', 'Andy B', 'a-long-password', is_admin=True)
    with store.transaction() as db:
        store._new_ship(db, 'tardis', 'Tardis', person['id'])
    done = run('export-ship', '--data-dir', store.data_dir, '--username', 'tardis',
               '--endpoint', 'https://localhost:7435', '--out', tmp_path / 'out')
    assert done.returncode == 1 and 'identity.json' in done.stderr
    assert not (store.data_dir / 'identity.json').exists()


def test_export_ship_follows_the_stored_mode_not_the_flag(machine, tmp_path):
    pull = run('export-ship', '--data-dir', machine[0].data_dir, '--username', 'tardis', '--pull', '--out', tmp_path / 'p')
    assert pull.returncode == 1 and 'push peer' in pull.stderr and not (tmp_path / 'p').exists()


def test_export_ship_refuses_a_peer_with_no_mode(tmp_path):
    store = Store(tmp_path / 'home')
    person = store.create_user('andy-b', 'Andy B', 'a-long-password', is_admin=True)
    with store.transaction() as db:
        store._new_ship(db, 'tardis', 'Tardis', person['id'])
    Federation(store, endpoint='https://localhost:7435')
    done = export(type('M', (), {'__getitem__': lambda self, i: store})(), tmp_path, 'tardis')
    assert done.returncode == 1 and 'no federation mode' in done.stderr and not (tmp_path / 'out').exists()


# Task 2: the owner trust table, granting and renewing

PASSWORD = 'station-password'


@pytest.fixture
def paired(tmp_path, machine):
    station = Store(tmp_path / 'station', clock=lambda: NOW)
    admin = station.create_user('andy', 'Andy', PASSWORD, is_admin=True)
    fed = Federation(station, endpoint='https://localhost:7436')
    card = machine[3].card(machine[1]['id'])
    contact = fed.pair(admin['id'], card, code=pairing_code(card))
    return station, admin, contact, card


def grant(paired, days=90, password=PASSWORD, expect=50):
    station, admin, contact, card = paired
    return station.grant_owner_trust(admin['id'], contact['id'], days=days, expect=expect, password=password, source='127.0.0.1')


def rows(station):
    with station.transaction() as db:
        return [dict(r) for r in db.execute('SELECT * FROM owner_trust ORDER BY seq')]


def test_a_grant_reads_as_the_spec_says(paired):
    done = grant(paired)
    peer = paired[2]['peer_id']
    assert done['text'] == f"ships owned by Andy B on {peer[:12]} may be paired by this station's ships, until 2027-04-15"
    assert done['until'] == NOW + 90 * 86400 and rows(paired[0])[0]['event'] == 'grant'


def test_a_grant_needs_the_admins_password_and_whole_days_1_to_90(paired):
    with pytest.raises(Problem) as caught:
        grant(paired, password='not-the-password')
    assert caught.value.status == 401
    for days in (0, 91, '90', True):
        with pytest.raises(Problem) as caught:
            grant(paired, days=days)
        assert caught.value.status == 400
    assert rows(paired[0]) == []


def test_a_grant_needs_a_code_typed_for_that_contact(paired):
    station, admin, contact, card = paired
    with station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (contact['id'], NOW))
    with pytest.raises(Problem) as caught:
        grant(paired)
    assert caught.value.status == 409
    with station.transaction() as db:
        db.execute('DELETE FROM contact_holds')
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (contact['id'],))
    with pytest.raises(Problem) as caught:
        grant(paired)
    assert caught.value.status == 409 and rows(station) == []


def test_a_second_grant_while_one_is_live_is_refused(paired):
    grant(paired)
    with pytest.raises(Problem) as caught:
        grant(paired, days=5)
    assert caught.value.status == 409 and 'renew' in caught.value.message and len(rows(paired[0])) == 1


def test_renewing_extends_and_owner_trust_is_append_only(paired):
    station, admin, contact, card = paired
    done = grant(paired, days=10)
    renewed = station.renew_owner_trust(admin['id'], done['grant_id'], days=60, expect=50, seen=window_of(station, done['grant_id']), password=PASSWORD, source='127.0.0.1')
    assert renewed['grant_id'] == done['grant_id'] and renewed['until'] == NOW + 60 * 86400 > done['until']
    assert [r['event'] for r in rows(station)] == ['grant', 'renew']
    with pytest.raises(Problem) as caught:
        station.renew_owner_trust(admin['id'], done['grant_id'], days=5, expect=50, seen=window_of(station, done['grant_id']), password=PASSWORD, source='127.0.0.1')
    assert caught.value.status == 409
    for sql in ('UPDATE owner_trust SET until=0', 'DELETE FROM owner_trust',
                "INSERT OR REPLACE INTO owner_trust(seq,grant_id,event,peer_id,owner_user_id,at) VALUES (1,'x','revoke','p','o',0)"):
        with station.transaction() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    assert len(rows(station)) == 2


def test_the_schema_statements_each_run_alone():
    db = sqlite3.connect(':memory:')
    for statement in OWNER_TRUST_STATEMENTS:
        db.execute(statement)
    assert OWNER_TRUST_SCHEMA.endswith(';') and OWNER_TRUST_SCHEMA.count('CREATE') == len(OWNER_TRUST_STATEMENTS)


def window_of(station, grant_id):
    """What the renewal page shows: the window's seq and how many paired in it."""
    from superyak_peer.owner_trust import trust_window
    with station.transaction() as db:
        try:
            window_seq, _, paired = trust_window(db, grant_id)
        except Problem:
            return (0, 0)
    return (window_seq, paired)


def renew(paired, grant_id, days=30, password=PASSWORD, expect=50, seen=None):
    station, admin = paired[:2]
    seen = window_of(station, grant_id) if seen is None else seen
    return station.renew_owner_trust(admin['id'], grant_id, days=days, expect=expect, seen=seen, password=password, source='127.0.0.1')


def revoke_row(station, grant_id, peer_id, owner):
    with station.transaction() as db:
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,at) VALUES (?,'revoke',?,?,?)",
                   (grant_id, peer_id, owner, NOW))


def test_renewing_needs_the_password_a_known_unrevoked_grant(paired):
    station, admin, contact, card = paired
    done = grant(paired, days=5)
    with pytest.raises(Problem) as caught:
        renew(paired, done['grant_id'], password='not-the-password')
    assert caught.value.status == 401
    with pytest.raises(Problem) as caught:
        renew(paired, 'nope')
    assert caught.value.status == 404
    revoke_row(station, done['grant_id'], contact['peer_id'], contact['user_id'])
    with pytest.raises(Problem) as caught:
        renew(paired, done['grant_id'])
    assert caught.value.status == 409 and len(rows(station)) == 2


def test_renewing_re_checks_the_owner_and_refuses_a_trust_made_contact(paired):
    station, admin, contact, card = paired
    done = grant(paired, days=5)
    with station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (contact['id'], NOW))
    with pytest.raises(Problem) as caught:
        renew(paired, done['grant_id'])
    assert caught.value.status == 409
    with station.transaction() as db:
        db.execute('DELETE FROM contact_holds')
        db.execute('INSERT INTO trust_confirmations VALUES (?,?,?,?,?,?,?,?)', ('t', contact['id'], 'g', '{}', 's', NOW, '2027-01-15', 1))
    for attempt in (lambda: renew(paired, done['grant_id']), lambda: grant(paired)):
        with pytest.raises(Problem) as caught:
            attempt()
        assert caught.value.status == 409
    assert len(rows(station)) == 1


def test_an_expired_grant_cannot_come_back_beside_a_newer_one(paired):
    station, admin, contact, card = paired
    now = [NOW]
    station.clock = lambda: now[0]
    first = grant(paired, days=1)
    now[0] = NOW + 2 * 86400
    second = grant(paired, days=10)
    with pytest.raises(Problem) as caught:
        renew(paired, first['grant_id'])
    assert caught.value.status == 409
    assert len(rows(station)) == 2
    with station.transaction() as db:
        assert live_trust(db, contact['peer_id'], contact['user_id'], now[0])['grant_id'] == second['grant_id']


def test_live_trust_excludes_a_revoked_grant_and_ends_at_until(paired):
    station, admin, contact, card = paired
    done = grant(paired, days=1)
    peer, owner = contact['peer_id'], contact['user_id']
    with station.transaction() as db:
        assert live_trust(db, peer, owner, done['until'] - 1)['grant_id'] == done['grant_id']
        assert live_trust(db, peer, owner, done['until']) is None
    revoke_row(station, done['grant_id'], peer, owner)
    with station.transaction() as db:
        assert live_trust(db, peer, owner, NOW) is None


# Task 3: pair-trusted, every check in one transaction, and the cap of 200 a day

COUNTED = ('remote_contacts', 'trust_confirmations', 'owner_trust', 'contact_holds', 'pairing_confirmations',
           'trust_cap_refusals', 'peers')


@pytest.fixture
def trusted(tmp_path, machine, paired):
    """Task 2's pairing plus a live 90-day trust for Andy B, B's export-ship output for tardis, and the station's ship
    rio-grande (owned by andy) to act. The station's clock stands at the moment B exported, so the real assertion holds
    whatever today's date is."""
    station, admin, owner, _ = paired
    done = export(machine, tmp_path, 'tardis', out='export')
    assert done.returncode == 0, done.stderr
    files = (tmp_path / 'export' / 'tardis.card.json', tmp_path / 'export' / 'tardis.assertion.json')
    card, assertion = (json.loads(path.read_text()) for path in files)
    clock = [assertion['record']['issued']]
    station.clock = lambda: clock[0]
    with station.transaction() as db:
        ship = station._new_ship(db, 'rio-grande', 'Rio Grande', admin['id'])
    return SimpleNamespace(station=station, admin=admin, owner=owner, machine=machine, card=card, assertion=assertion,
                           files=files, clock=clock, ship=ship['id'], trust=grant(paired), tmp=tmp_path,
                           fed=Federation(station, endpoint='https://localhost:7436'))


def counts(station):
    with station.transaction() as db:
        return {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in COUNTED}


def utc_day(at):
    return datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d')


def refuses(t, status, word, card=None, assertion=None, actor=None):
    """One refusal: its status, a word of its message, and nothing written."""
    before = counts(t.station)
    with pytest.raises(Problem) as caught:
        t.fed.pair_trusted(t.ship if actor is None else actor, t.card if card is None else card,
                           t.assertion if assertion is None else assertion)
    assert caught.value.status == status and word in caught.value.message, (caught.value.status, caught.value.message)
    assert counts(t.station) == before
    return caught.value


def pairs(t, card=None, assertion=None):
    return t.fed.pair_trusted(t.ship, t.card if card is None else card, t.assertion if assertion is None else assertion)


def b_ship(t, name, ship_id=None, *, now=None, owner=None):
    """The card and the assertion B signs for a ship of its own: all station A ever sees of it."""
    _, person, _, fed = t.machine
    ship_id = ship_id or f'ship-{name}'
    card = fed.identity.card('https://localhost:7435', {'id': ship_id, 'name': name})
    return card, make_ship_assertion(fed.identity, ship_id=ship_id, ship_name=name, owner_id=owner or person['id'],
                                     now=t.clock[0] if now is None else now)


def third_peer(t, name='Andy C'):
    """Peer C, paired at A with its code, whose person contact shares andy-b's user id (M3), and a maker of its ships."""
    identity = PeerIdentity.load_or_create(t.tmp / 'c')
    person_card = identity.card('https://localhost:7437', {'id': t.owner['user_id'], 'name': name})
    contact = t.fed.pair(t.admin['id'], person_card, code=pairing_code(person_card))

    def ship(ship_name, ship_id):
        card = identity.card('https://localhost:7437', {'id': ship_id, 'name': ship_name})
        return card, make_ship_assertion(identity, ship_id=ship_id, ship_name=ship_name, owner_id=t.owner['user_id'],
                                         now=t.clock[0])
    return contact, ship


def label_of(station, contact_id):
    with station.transaction() as db:
        return db.execute('SELECT label FROM contact_labels WHERE id=?', (contact_id,)).fetchone()[0]


def test_a_ship_pairs_and_shows_its_owner_first(trusted):
    t = trusted
    before = counts(t.station)
    done = pairs(t)
    assert done['confirmed_by'] == 'owner trust' and done['grant_id'] == t.trust['grant_id']
    assert (done['peer_id'], done['user_id'], done['name']) == (t.owner['peer_id'], t.card['participant']['id'], 'tardis')
    assert counts(t.station) == {**before, 'remote_contacts': before['remote_contacts'] + 1,
                                 'trust_confirmations': before['trust_confirmations'] + 1}
    with t.station.transaction() as db:
        assert db.execute('SELECT name FROM remote_contacts WHERE id=?', (done['id'],)).fetchone()[0] == 'tardis'
        row = dict(db.execute('SELECT * FROM trust_confirmations WHERE contact_id=?', (done['id'],)).fetchone())
        assert db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (done['id'],)).fetchone() is None
    assert row['grant_id'] == t.trust['grant_id'] and row['acting_ship_id'] == t.ship
    assert row['assertion'] == canonical(t.assertion).decode()  # the signed assertion itself, as canonical JSON
    assert row['confirmed'] == t.clock[0] and row['day'] == utc_day(t.clock[0])
    assert label_of(t.station, done['id']) == 'ship of Andy B: tardis'
    assert label_of(t.station, t.owner['id']) == 'Andy B'  # a person contact reads as its own name
    revoke_row(t.station, t.trust['grant_id'], t.owner['peer_id'], t.owner['user_id'])
    assert label_of(t.station, done['id']) == 'ship of Andy B: tardis'  # still a ship after a revoke, never a person
    with t.station.transaction() as db:
        db.execute("UPDATE remote_contacts SET name='Andy Bee' WHERE id=?", (t.owner['id'],))
    assert label_of(t.station, done['id']) == 'ship of Andy Bee: tardis'  # the owner's name is read live


def test_only_a_ship_with_an_owner_pairs(trusted):
    t = trusted
    odo = t.station.create_station_ship('odo', 'Odo')
    for actor in (t.admin['id'], odo['id'], 'nobody'):
        refuses(t, 403, 'ship', actor=actor)
        refuses(t, 403, 'ship', card={'not': 'a card'}, assertion={}, actor=actor)  # before any other check


def test_no_trust(trusted):
    t = trusted
    store, _, _, fed = t.machine
    sam = store.create_user('sam', 'Sam', 'a-long-password')
    sam_card = fed.card(sam['id'])
    t.fed.pair(t.admin['id'], sam_card, code=pairing_code(sam_card))  # Sam's code was typed, but no trust was granted
    refuses(t, 403, 'trust', *b_ship(t, 'sams-ship', owner=sam['id']))
    revoke_row(t.station, t.trust['grant_id'], t.owner['peer_id'], t.owner['user_id'])
    refuses(t, 403, 'trust')


def test_an_expired_trust(trusted):
    t = trusted
    tardis = pairs(t)
    t.clock[0] = t.trust['until'] - 1
    serenity = pairs(t, *b_ship(t, 'serenity'))
    t.clock[0] = t.trust['until']
    refuses(t, 403, 'trust', *b_ship(t, 'defiant'))
    with t.station.transaction() as db:
        assert db.execute('SELECT paired FROM peers WHERE peer_id=?', (tardis['peer_id'],)).fetchone()[0] == 1
        for contact in (tardis, serenity):
            assert db.execute('SELECT 1 FROM remote_contacts WHERE id=?', (contact['id'],)).fetchone()
            assert db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (contact['id'],)).fetchone() is None


def test_a_trust_whose_owners_code_was_never_typed(trusted):
    t = trusted
    with t.station.transaction() as db:
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (t.owner['id'],))
    refuses(t, 409, 'code')


def test_a_trust_whose_owners_code_is_stale(trusted):
    t = trusted
    with t.station.transaction() as db:  # a code on record, but not the stored card's code any more
        db.execute("UPDATE pairing_confirmations SET code=? WHERE contact_id=?", ('0' * 32, t.owner['id']))
    refuses(t, 409, 'code')


def test_an_expired_or_future_assertion_through_pair_trusted(trusted):
    t = trusted
    refuses(t, 400, 'expired', *b_ship(t, 'serenity', now=t.clock[0] - 30 * 86400))  # its 30 days ended just now
    card, _ = b_ship(t, 'serenity')
    expired = make_ship_assertion(t.machine[3].identity, ship_id=card['participant']['id'], ship_name='serenity',
                                  owner_id=t.machine[1]['id'], now=t.clock[0] - 86400, days=1)  # expires == now
    refuses(t, 400, 'expired', card, expired)
    refuses(t, 400, 'future', *b_ship(t, 'serenity', now=t.clock[0] + 301))


def test_assertion_ids_and_names_must_be_text(machine):
    for field, bad in (('owner_id', ['x']), ('owner_id', {'id': 'x'}), ('ship_id', 7), ('ship_name', None)):
        refused(card_of(machine), signed(machine, **{field: bad}))


def test_an_assertion_with_a_list_owner_is_refused_not_crashed(trusted):
    t = trusted
    card, _ = b_ship(t, 'serenity')
    odd = make_ship_assertion(t.machine[3].identity, ship_id=card['participant']['id'], ship_name='serenity',
                              owner_id=[t.owner['user_id']], now=t.clock[0])  # the signing peer's own bad data
    refuses(t, 400, 'text', card, odd)


def test_trust_confirmations_are_indexed_for_the_cap_and_the_labels(trusted):
    with trusted.station.transaction() as db:
        cap = ' '.join(r[-1] for r in db.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM trust_confirmations WHERE grant_id='g' AND day='d'"))
        label = ' '.join(r[-1] for r in db.execute("EXPLAIN QUERY PLAN SELECT label FROM contact_labels WHERE id='x'"))
    assert 'trust_confirmations_grant_day' in cap and 'trust_confirmations_contact' in label
    with trusted.station.transaction() as db:
        window = ' '.join(r[-1] for r in db.execute('EXPLAIN QUERY PLAN SELECT COUNT(*) FROM trust_confirmations WHERE window_seq=1'))
    assert 'trust_confirmations_window' in window


def test_a_held_owner(trusted):
    t = trusted
    with t.station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (t.owner['id'], t.clock[0]))
    refuses(t, 409, 'held')


def test_a_card_of_a_peer_not_paired_here(trusted):
    t = trusted
    stranger = PeerIdentity.load_or_create(t.tmp / 'stranger')
    card = stranger.card('https://localhost:7438', {'id': 'ship-x', 'name': 'x-ship'})
    assertion = make_ship_assertion(stranger, ship_id='ship-x', ship_name='x-ship', owner_id=t.owner['user_id'], now=t.clock[0])
    refuses(t, 409, 'paired', card, assertion)
    refuses(t, 400, 'card', {**t.card, 'extra': 1})
    with t.station.transaction() as db:  # as unpair --retire leaves it: unpaired, with a retired row
        db.execute('UPDATE peers SET paired=0')
        db.execute('INSERT INTO retired_peers VALUES (?,?,?)', (t.owner['peer_id'], t.clock[0], t.admin['id']))
    assert 'code' not in refuses(t, 409, 'retired').message  # never told to pair a retired peer with its code
    with t.station.transaction() as db:
        db.execute('UPDATE peers SET paired=1')  # a retired row re-applied by a restore over a paired copy
    refuses(t, 409, 'retired')
    with t.station.transaction() as db:
        db.execute('DELETE FROM retired_peers')
        db.execute('UPDATE peers SET paired=0')
    refuses(t, 409, 'paired')


def test_a_card_whose_other_fields_differ(trusted):
    t = trusted
    refuses(t, 409, 'differs', {**t.card, 'endpoint': 'https://elsewhere.example:7435'})
    refuses(t, 409, 'differs', {**t.card, 'version': 2, 'delivery': 'pull', 'endpoint': None})


def test_a_participant_that_differs_from_the_assertions(trusted):
    t = trusted
    refuses(t, 400, 'participant', {**t.card, 'participant': {**t.card['participant'], 'name': 'serenity'}})
    refuses(t, 400, 'participant', {**t.card, 'participant': {**t.card['participant'], 'id': 'someone-else'}})


def test_a_forged_card_from_a_public_card(trusted, paired):
    t = trusted
    public = paired[3]  # B's person card, the one Andy paired: its key, certificate and endpoint are public
    forged = {**public, 'participant': {'id': 'forged-ship', 'name': 'forged'}}
    refuses(t, 400, 'participant', forged)  # tardis's real assertion names another ship
    refuses(t, 400, 'participant', public)
    record = {**t.assertion['record'], 'ship_id': 'forged-ship', 'ship_name': 'forged'}
    refuses(t, 400, 'verify', forged, {'record': record, 'signature': t.assertion['signature']})
    attacker = PeerIdentity.load_or_create(t.tmp / 'attacker')
    own_key = base64.b64encode(attacker.key.sign(canonical(record))).decode()
    refuses(t, 400, 'verify', forged, {'record': record, 'signature': own_key})


def test_an_owner_on_another_peer(trusted):
    t = trusted
    contact, c_ship = third_peer(t)
    assert contact['user_id'] == t.owner['user_id'] and contact['peer_id'] != t.owner['peer_id']
    refuses(t, 403, 'trust', *c_ship('tardis', 'c-tardis'))  # B's owner is trusted; C's owner of the same id isn't


def test_an_assertion_issued_before_a_revocation(trusted):
    t = trusted
    revoke_row(t.station, t.trust['grant_id'], t.owner['peer_id'], t.owner['user_id'])  # at NOW
    t.clock[0] = max(t.clock[0], NOW) + 60
    later = grant((t.station, t.admin, t.owner, None))  # a new trust, granted after the revocation (S8)
    refuses(t, 403, 'revoked', *b_ship(t, 'serenity', now=NOW))  # issued at the revocation's own second
    pairs(t, *b_ship(t, 'serenity', now=NOW + 1))
    assert later['grant_id'] != t.trust['grant_id']


def test_names_that_fail_ship_name_or_collide(trusted):
    t = trusted
    store, _, _, fed = t.machine
    refuses(t, 400, 'name', *b_ship(t, 'Tardis'))
    refuses(t, 409, 'name', *b_ship(t, 'andy'))  # the station's own username
    refuses(t, 409, 'name', *b_ship(t, 'rio-grande'))  # a local ship's username
    t.station.create_user('deckie', 'Dock-Hand', 'a-long-password')
    refuses(t, 409, 'name', *b_ship(t, 'dock-hand'))  # a local name, by casefold
    sam = store.create_user('sam', 'Sam', 'a-long-password')
    sam_card = fed.card(sam['id'])
    t.fed.pair(t.admin['id'], sam_card, code=pairing_code(sam_card))
    refuses(t, 409, 'name', *b_ship(t, 'sam'))  # a remote person contact's name
    for username, name, ship in (('kim', 'kim ', 'kim'), ('lee', 'ｌｅｅ', 'lee')):  # a trailing space; fullwidth (NFKC)
        person = store.create_user(username, name, 'a-long-password')
        person_card = fed.card(person['id'])
        t.fed.pair(t.admin['id'], person_card, code=pairing_code(person_card))
        refuses(t, 409, 'name', *b_ship(t, ship))


def test_a_ships_name_may_repeat_on_another_host(trusted):
    t = trusted
    first = pairs(t)
    contact, c_ship = third_peer(t)
    t.station.grant_owner_trust(t.admin['id'], contact['id'], days=30, expect=50, password=PASSWORD, source='127.0.0.1')
    second = pairs(t, *c_ship('tardis', 'c-tardis'))
    assert first['name'] == second['name'] == 'tardis' and first['peer_id'] != second['peer_id']
    assert label_of(t.station, first['id']) == 'ship of Andy B: tardis'
    assert label_of(t.station, second['id']) == 'ship of Andy C: tardis'  # the owner is (peer, id), never an id alone


def test_a_contact_that_already_exists(trusted):
    t = trusted
    pairs(t)
    refuses(t, 409, 'already')
    refuses(t, 409, 'already', *b_ship(t, 'andy-bee', ship_id=t.owner['user_id']))  # no trust relabels a person


def expect_more(t, expect):
    """A renewal a minute on that expects `expect` ships, so a test of another limit isn't stopped by the count."""
    t.clock[0] += 60
    renew((t.station, t.admin), t.trust['grant_id'], days=90, expect=expect)


def test_the_cap(trusted):
    from superyak_peer.federation import TRUST_CAP
    t = trusted
    assert TRUST_CAP == 200
    expect_more(t, 300)  # the day's cap is the limit under test, not the window's count
    for i in range(TRUST_CAP):
        pairs(t, *b_ship(t, f'ship-{i}'))
    before = counts(t.station)
    card, assertion = b_ship(t, 'one-too-many')
    for refused in (1, 2):
        with pytest.raises(Problem) as caught:
            pairs(t, card, assertion)
        assert caught.value.status == 429 and '200' in caught.value.message
        assert counts(t.station) == {**before, 'trust_cap_refusals': 1}
        with t.station.transaction() as db:
            assert [tuple(r) for r in db.execute('SELECT grant_id, day, refused FROM trust_cap_refusals')] == \
                [(t.trust['grant_id'], utc_day(t.clock[0]), refused)]
    t.clock[0] += 86400  # the next UTC day counts afresh
    pairs(t, card, assertion)


def test_two_pairings_at_the_cap_pair_one(trusted):
    t = trusted
    expect_more(t, 300)
    seq = window_of(t.station, t.trust['grant_id'])[0]  # seeded under the current window, as a real pairing is
    with t.station.transaction() as db:
        db.executemany('INSERT INTO trust_confirmations VALUES (?,?,?,?,?,?,?,?)',
                       [(f'seed-{i}', f'contact-{i}', t.trust['grant_id'], '{}', t.ship, t.clock[0], utc_day(t.clock[0]), seq)
                        for i in range(199)])
    feds = [Federation(Store(t.station.data_dir, clock=lambda: t.clock[0]), endpoint='https://localhost:7436')
            for _ in range(2)]
    ships = [b_ship(t, name) for name in ('serenity', 'defiant')]
    start, results = threading.Barrier(2), [None, None]

    def attempt(i):
        start.wait()
        try:
            results[i] = feds[i].pair_trusted(t.ship, *ships[i])
        except Problem as problem:
            results[i] = problem
    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(type(r).__name__ for r in results) == ['Problem', 'dict']
    assert next(r for r in results if isinstance(r, Problem)).status == 429
    with t.station.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM trust_confirmations WHERE grant_id=?', (t.trust['grant_id'],)).fetchone()[0] == 200
        assert db.execute('SELECT refused FROM trust_cap_refusals').fetchone()[0] == 1


def at_most_2_gb():
    """An address-space cap where the OS has one, so a reader that never stops (say /dev/zero) fails fast, not the Pi."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
    except (ImportError, ValueError, OSError):
        pass


def pair_trusted_cli(t, card, assertion, as_user='rio-grande'):
    """The CLI as a ship runs it: a new session, so no controlling terminal, and nothing on stdin."""
    return subprocess.run([sys.executable, '-m', 'superyak_peer', 'pair-trusted', '--data-dir', str(t.station.data_dir),
                           '--card', str(card), '--assertion', str(assertion), '--as', as_user],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, start_new_session=True,
                          preexec_fn=at_most_2_gb, timeout=120)


def no_code(text):
    return not re.search(r'[0-9a-f]{32}', text) and not re.search(r'[0-9a-f]{4}( [0-9a-f]{4}){7}', text)


def test_pair_trusted_cli_refuses_bad_files(trusted):
    t = trusted
    card, assertion = t.files
    bad = t.tmp / 'bad'
    bad.mkdir()
    (bad / 'not.json').write_text('not json')
    (bad / 'big.json').write_bytes(b'{"x":"' + b'a' * (7 * 1024 * 1024) + b'"}')
    (bad / 'extra.json').write_text(json.dumps({**t.assertion, 'extra': 1}))
    before = counts(t.station)
    for files, word in [((bad / 'missing.json', assertion), 'No such file'), ((bad, assertion), 'directory'),
                        ((card, bad / 'not.json'), 'JSON'), ((card, bad / 'big.json'), 'too large'),
                        *([((Path('/dev/zero'), assertion), 'too large')] if Path('/dev/zero').exists() else []),
                        ((card, bad / 'extra.json'), 'ship assertion')]:
        done = pair_trusted_cli(t, *files)
        assert done.returncode == 1 and done.stdout == '', (files, done.stdout, done.stderr)
        assert done.stderr.count('\n') == 1 and word in done.stderr and no_code(done.stderr), done.stderr
        assert counts(t.station) == before


def test_pair_trusted_cli_pairs_with_no_terminal_and_no_code(trusted):
    t = trusted
    before = counts(t.station)
    for as_user in ('andy', 'nobody'):  # a person, and no such account
        refused = pair_trusted_cli(t, *t.files, as_user=as_user)
        assert refused.returncode == 1 and refused.stdout == '' and refused.stderr.count('\n') == 1
        assert 'ship' in refused.stderr and no_code(refused.stderr)
    assert counts(t.station) == before
    done = pair_trusted_cli(t, *t.files)
    assert done.returncode == 0, done.stderr
    assert done.stdout == 'Paired ship of Andy B: tardis, confirmed by owner trust.\n' and done.stderr == ''
    assert counts(t.station)['remote_contacts'] == before['remote_contacts'] + 1


def test_the_cli_line_keeps_the_ships_name_after_a_long_owner_name(trusted):
    t = trusted
    store, _, _, fed = t.machine
    long_name = 'Andy\n@rio-grande ' + 'x' * 183  # 200 characters, the most a participant name holds
    assert len(long_name) == 200
    person = store.create_user('long', long_name, 'a-long-password')
    person_card = fed.card(person['id'])
    contact = t.fed.pair(t.admin['id'], person_card, code=pairing_code(person_card))
    t.station.grant_owner_trust(t.admin['id'], contact['id'], days=30, expect=50, password=PASSWORD, source='127.0.0.1')
    card, assertion = b_ship(t, 'longs-ship', owner=person['id'])
    files = (t.tmp / 'longs-ship.card.json', t.tmp / 'longs-ship.assertion.json')
    for path, value in zip(files, (card, assertion)):
        path.write_text(json.dumps(value))
    done = pair_trusted_cli(t, *files)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith('Paired ship of Andy (at)rio-grande x')
    assert done.stdout.endswith(': longs-ship, confirmed by owner trust.\n') and done.stdout.count('\n') == 1
    assert '@' not in done.stdout and len(done.stdout) < 160


# Task 4: ending a trust: revoke, the holds that follow, and a retired peer

def revoke(t, grant_id=None, actor=None):
    return t.station.revoke_owner_trust(t.admin['id'] if actor is None else actor, grant_id or t.trust['grant_id'])


def is_held(station, contact_id):
    with station.transaction() as db:
        return db.execute('SELECT 1 FROM contact_holds WHERE contact_id=?', (contact_id,)).fetchone() is not None


def queue(station, contact_id):
    """One pending outbox row for a contact, by hand."""
    with station.transaction() as db:
        db.execute("INSERT INTO outbox(id,event_seq,contact_id,resource_id,revision,action,metadata,status) "
                   "VALUES (?,1,?,'room-1',1,'room.message','{}','pending')", ('out-' + contact_id, contact_id))


def outbox_of(station, contact_id):
    with station.transaction() as db:
        return [r[0] for r in db.execute('SELECT status FROM outbox WHERE contact_id=?', (contact_id,))]


def revocations(station):
    return [(r['grant_id'], r['reason'], r['by_id'], r['at']) for r in rows(station) if r['event'] == 'revoke']


def test_revoking_holds_every_ship_and_withdraws_their_outbox(trusted):
    t = trusted
    ships = [pairs(t), pairs(t, *b_ship(t, 'serenity'))]
    for contact in (*ships, t.owner):
        queue(t.station, contact['id'])
    with t.station.transaction() as db:  # a payload tardis authored, and one its owner did
        for author in (ships[0]['user_id'], t.owner['user_id']):
            db.execute("INSERT INTO inbox VALUES (?,?,'room',?,1,?,'{}')",
                       (t.owner['peer_id'], 'room-' + author, t.admin['id'], author))
    assert revoke(t) == {'grant_id': t.trust['grant_id'], 'held': 2}
    for ship in ships:
        assert is_held(t.station, ship['id']) and outbox_of(t.station, ship['id']) == ['withdrawn']
    assert not is_held(t.station, t.owner['id']) and outbox_of(t.station, t.owner['id']) == ['pending']  # ends the trust, not the person
    with t.station.transaction() as db:
        assert dict(db.execute('SELECT actor, payload FROM inbox').fetchall()) == \
            {ships[0]['user_id']: None, t.owner['user_id']: '{}'}
    assert revocations(t.station) == [(t.trust['grant_id'], 'revoked', t.admin['id'], t.clock[0])]
    before = counts(t.station)
    with pytest.raises(Problem) as caught:
        revoke(t)
    assert caught.value.status == 409 and counts(t.station) == before and len(revocations(t.station)) == 1


def test_revoking_ends_every_grant_of_the_owner(trusted):
    """Review ruling: ships paired under an owner's earlier, expired grant stay paired until that grant is revoked, so
    revoking the live one revokes it too."""
    t = trusted
    tardis = pairs(t)
    t.clock[0] = t.trust['until'] + 10  # the first grant expires; tardis stays paired under it
    second = grant((t.station, t.admin, t.owner, None), days=30)
    serenity = pairs(t, *b_ship(t, 'serenity'))
    assert revoke(t, second['grant_id']) == {'grant_id': second['grant_id'], 'held': 2}
    assert is_held(t.station, tardis['id']) and is_held(t.station, serenity['id'])
    assert revocations(t.station) == [(g, 'revoked', t.admin['id'], t.clock[0]) for g in (t.trust['grant_id'], second['grant_id'])]
    with pytest.raises(Problem) as caught:
        revoke(t)  # the first one, revoked with it
    assert caught.value.status == 409


def test_held_counts_only_the_ships_the_revoke_held(trusted):
    t = trusted
    tardis, serenity = pairs(t), pairs(t, *b_ship(t, 'serenity'))
    with t.station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (serenity['id'], t.clock[0]))  # held already
    assert revoke(t)['held'] == 1 and is_held(t.station, tardis['id'])


def test_only_an_admin_revokes_and_only_a_known_trust(trusted):
    t = trusted
    pairs(t)
    before = counts(t.station)
    for actor, grant_id, status in ((t.ship, None, 403), (t.admin['id'], 'no-such-grant', 404)):
        with pytest.raises(Problem) as caught:
            revoke(t, grant_id, actor)
        assert caught.value.status == status
    assert counts(t.station) == before


def test_holding_the_owner_holds_its_ships_and_dates_it(trusted):
    t = trusted
    ships = [pairs(t), pairs(t, *b_ship(t, 'serenity'))]
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'])
    assert revocations(t.station) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    assert all(is_held(t.station, ship['id']) for ship in ships)


@pytest.mark.parametrize('how', ['held', 'stale code', 'unpaired', 'retired', 'gone', 'held after expiry'])
def test_settling_ends_a_trust_whose_owner_fails_and_holds_its_ships(trusted, how):
    """Any hold of the owner, as a restore makes one (backups _hold_like_replaced holds a contact alone)."""
    t = trusted
    ships = [pairs(t), pairs(t, *b_ship(t, 'serenity'))]
    queue(t.station, ships[0]['id'])
    with t.station.transaction() as db:
        assert settle_owner_trust(db, t.clock[0]) == []  # nothing to settle yet
    if how == 'held after expiry':
        t.clock[0] = t.trust['until'] + 1  # an expired trust's ships stay paired until a hold of the owner
    sql = {'stale code': ("UPDATE pairing_confirmations SET code=? WHERE contact_id=?", ('0' * 32, t.owner['id'])),
           'unpaired': ('UPDATE peers SET paired=0 WHERE peer_id=?', (t.owner['peer_id'],)),
           'retired': ('INSERT INTO retired_peers VALUES (?,?,NULL)', (t.owner['peer_id'], t.clock[0])),
           'gone': ('DELETE FROM remote_contacts WHERE id=?', (t.owner['id'],))
           }.get(how, ('INSERT INTO contact_holds VALUES (?,?)', (t.owner['id'], t.clock[0])))
    with t.station.transaction() as db:
        db.execute(*sql)
        assert settle_owner_trust(db, t.clock[0]) == [t.trust['grant_id']]
        assert settle_owner_trust(db, t.clock[0]) == []  # settled: a second run changes nothing
    assert revocations(t.station) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    assert all(is_held(t.station, ship['id']) for ship in ships)
    assert outbox_of(t.station, ships[0]['id']) == ['withdrawn']


def test_repairing_the_owners_peer_does_not_bring_the_trust_back(trusted, paired):
    t = trusted
    ships = [pairs(t), pairs(t, *b_ship(t, 'serenity'))]
    t.fed.unpair(t.admin['id'], t.owner['id'])
    t.clock[0] += 60
    person_card = paired[3]
    again = t.fed.pair(t.admin['id'], person_card, code=pairing_code(person_card))
    assert again['id'] == t.owner['id'] and again['confirmed'] and not again['held']
    with t.station.transaction() as db:
        assert code_current(db, t.owner['id'])  # the owner is live again
        assert live_trust(db, t.owner['peer_id'], t.owner['user_id'], t.clock[0]) is None  # the trust is not
    assert len(revocations(t.station)) == 1 and all(is_held(t.station, ship['id']) for ship in ships)
    refuses(t, 403, 'trust')  # the old assertion, with no trust
    grant((t.station, t.admin, t.owner, None))
    refuses(t, 403, 'revoked')  # and under a new trust: it was issued before the unpair
    back = pairs(t, *b_ship(t, 'tardis', t.card['participant']['id']))  # only a new grant and a fresh assertion
    assert back['id'] == ships[0]['id'] and not is_held(t.station, back['id']) and is_held(t.station, ships[1]['id'])


def test_a_peer_unpaired_without_a_revocation_ends_its_trusts_when_it_pairs_again(trusted, paired):
    """As main's unpair leaves a peer (a rollback): unpaired, nothing held, no revoke row. Pairing it again holds every
    contact first (Serenity's MF2), and that hold of the owner ends its trust before the typed one is released."""
    t = trusted
    tardis = pairs(t)
    with t.station.transaction() as db:
        db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (t.owner['peer_id'],))
    queue(t.station, tardis['id'])  # queued while unpaired: collect() skips only held contacts
    t.clock[0] += 60
    t.fed.pair(t.admin['id'], paired[3], code=pairing_code(paired[3]))
    assert revocations(t.station) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    assert is_held(t.station, tardis['id']) and not is_held(t.station, t.owner['id'])
    assert outbox_of(t.station, tardis['id']) == ['withdrawn']  # never delivered after the re-pair


def test_typing_a_held_owners_code_does_not_bring_its_trust_back(trusted, paired):
    """The owner held alone with no revocation beside it, as a restore's _hold_like_replaced leaves it, on a peer that
    stays paired: pairing the owner with its own code settles before it releases the owner."""
    t = trusted
    tardis = pairs(t)
    with t.station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (t.owner['id'], t.clock[0]))
    t.clock[0] += 60
    again = t.fed.pair(t.admin['id'], paired[3], code=pairing_code(paired[3]))
    assert again['confirmed'] and not again['held'] and not is_held(t.station, t.owner['id'])
    with t.station.transaction() as db:
        assert live_trust(db, t.owner['peer_id'], t.owner['user_id'], t.clock[0]) is None
    assert revocations(t.station) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    assert is_held(t.station, tardis['id'])


def test_a_held_ship_repairs_only_under_a_later_trust_and_a_fresh_assertion(trusted):
    t = trusted
    tardis = pairs(t)
    revoked_at = t.clock[0]
    revoke(t)
    t.clock[0] += 60
    later = grant((t.station, t.admin, t.owner, None))
    ship_id = t.card['participant']['id']
    refuses(t, 403, 'revoked')  # its old assertion
    refuses(t, 403, 'revoked', *b_ship(t, 'tardis', ship_id, now=revoked_at - 1))  # signed anew, dated before
    before = counts(t.station)
    done = pairs(t, *b_ship(t, 'tardis', ship_id, now=revoked_at + 1))
    assert done['id'] == tardis['id'] and done['grant_id'] == later['grant_id'] and done['confirmed_by'] == 'owner trust'
    assert not is_held(t.station, tardis['id'])
    assert counts(t.station) == {**before, 'contact_holds': before['contact_holds'] - 1,
                                 'trust_confirmations': before['trust_confirmations'] + 1}
    assert label_of(t.station, tardis['id']) == 'ship of Andy B: tardis'
    refuses(t, 409, 'already', *b_ship(t, 'tardis', ship_id))  # back, so a contact again


def test_a_held_ship_does_not_come_back_under_a_trust_granted_before_its_revocation(trusted):
    """A revoke ends every grant of the owner, so this state comes only from a revocation recorded for one grant (as a
    restore re-applies one): check 7 still wants the live trust granted after it."""
    t = trusted
    tardis = pairs(t)
    ship_id = t.card['participant']['id']
    t.clock[0] = t.trust['until'] + 10  # the first trust has expired; tardis stays paired under it
    second = grant((t.station, t.admin, t.owner, None), days=30)
    t.clock[0] += 10
    with t.station.transaction() as db:  # the expired trust alone revoked, after the second was granted
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,at,reason) VALUES (?,'revoke',?,?,?,?)",
                   (t.trust['grant_id'], t.owner['peer_id'], t.owner['user_id'], t.clock[0], 'restored'))
        assert settle_owner_trust(db, t.clock[0]) == []  # the second trust's owner is fine
    assert is_held(t.station, tardis['id'])
    t.clock[0] += 10
    refuses(t, 409, 'granted after', *b_ship(t, 'tardis', ship_id))  # fresh, but the live trust predates the revocation
    revoke(t, second['grant_id'])
    t.clock[0] += 10
    grant((t.station, t.admin, t.owner, None), days=30)
    t.clock[0] += 10
    assert pairs(t, *b_ship(t, 'tardis', ship_id))['id'] == tardis['id']


def test_a_held_person_contact_never_becomes_a_ship(trusted):
    t = trusted
    store, _, _, fed = t.machine
    sam = store.create_user('sam', 'Sam', 'a-long-password')
    sam_card = fed.card(sam['id'])
    contact = t.fed.pair(t.admin['id'], sam_card, code=pairing_code(sam_card))
    with t.station.transaction() as db:
        db.execute('INSERT INTO contact_holds VALUES (?,?)', (contact['id'], t.clock[0]))
    from superyak_peer.federation import ALREADY
    assert refuses(t, 409, 'already', *b_ship(t, 'sams-ship', ship_id=sam['id'])).message == ALREADY


def test_a_held_ship_does_not_come_back_under_another_owners_trust(trusted):
    t = trusted
    pairs(t)
    revoke(t)
    t.clock[0] += 60
    store, _, _, fed = t.machine
    sam = store.create_user('sam', 'Sam', 'a-long-password')
    sam_card = fed.card(sam['id'])
    contact = t.fed.pair(t.admin['id'], sam_card, code=pairing_code(sam_card))
    t.station.grant_owner_trust(t.admin['id'], contact['id'], days=30, expect=50, password=PASSWORD, source='127.0.0.1')
    refuses(t, 409, 'granted after', *b_ship(t, 'tardis', t.card['participant']['id'], owner=sam['id']))


def test_a_typed_code_brings_back_a_ship_whose_trust_was_revoked(trusted):
    """A code typed for that one account is a person's act, the stronger proof (ruling on Task 4): it stands."""
    t = trusted
    tardis = pairs(t)
    revoke(t)
    assert is_held(t.station, tardis['id'])
    done = t.fed.pair(t.admin['id'], t.card, code=pairing_code(t.card))
    assert done['id'] == tardis['id'] and done['confirmed'] and not done['held']
    with t.station.transaction() as db:
        assert settle_owner_trust(db, t.clock[0]) == []
    assert not is_held(t.station, tardis['id'])  # a later settle leaves it alone
    assert label_of(t.station, tardis['id']) == 'ship of Andy B: tardis'  # still a ship, never a person


def test_a_ship_with_its_own_typed_code_survives_a_revoke_and_its_sibling_does_not(trusted):
    t = trusted
    tardis, serenity = pairs(t), pairs(t, *b_ship(t, 'serenity'))
    t.fed.pair(t.admin['id'], t.card, code=pairing_code(t.card))  # Andy also types tardis's own code
    assert revoke(t)['held'] == 1
    assert not is_held(t.station, tardis['id']) and is_held(t.station, serenity['id'])
    assert label_of(t.station, tardis['id']) == 'ship of Andy B: tardis'


def test_pair_refuses_a_retired_peer_whatever_code_is_typed(trusted, paired):
    t = trusted
    tardis = pairs(t)
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)
    with t.station.transaction() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM retired_peers')] == \
            [(t.owner['peer_id'], t.clock[0], t.admin['id'])]
    assert is_held(t.station, t.owner['id']) and is_held(t.station, tardis['id'])  # its person contacts too
    assert revocations(t.station) == [(t.trust['grant_id'], 'owner held', None, t.clock[0])]
    person_card = paired[3]
    before = counts(t.station)
    for code in (pairing_code(person_card), '0' * 32, ''):
        with pytest.raises(Problem) as caught:
            t.fed.pair(t.admin['id'], person_card, code=code)
        assert caught.value.status == 409, caught.value.message
        assert caught.value.message == 'This peer was retired; it comes back only as a new identity'
        assert counts(t.station) == before
    retired_at = t.clock[0]
    t.clock[0] += 60
    t.fed.unpair(t.admin['id'], t.owner['id'], retire=True)  # retired again: the first row stays
    with t.station.transaction() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM retired_peers')] == [(t.owner['peer_id'], retired_at, t.admin['id'])]


# Task 4b: the expected count (spec revision 5, item 4a)

PAUSED = 'paused after {} pairings; the admin renews or revokes in the browser'


def window_rows(station):
    with station.transaction() as db:
        return [tuple(r) for r in db.execute('SELECT c.name, t.window_seq FROM trust_confirmations t JOIN remote_contacts c '
                                             'ON c.id=t.contact_id ORDER BY t.rowid')]


def owner_trust_tables(station):
    with station.transaction() as db:
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table}')]
                for table in ('owner_trust', 'trust_confirmations', 'trust_cap_refusals', 'remote_contacts', 'contact_holds')}


def test_the_nth_pairs_and_the_next_is_paused(trusted):
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=2)
    pairs(t, *b_ship(t, 'ship-a'))
    pairs(t, *b_ship(t, 'ship-b'))
    before = owner_trust_tables(t.station)
    card, assertion = b_ship(t, 'ship-c')
    for _ in (1, 2):
        error = refuses(t, 429, PAUSED.format(2), card, assertion)
        assert error.message == PAUSED.format(2)
        assert owner_trust_tables(t.station) == before


def test_a_renewal_opens_a_new_window_up_to_its_own_count(trusted):
    from superyak_peer.owner_trust import trust_window
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=1)
    first = rows(t.station)[-1]['seq']
    pairs(t, *b_ship(t, 'ship-a'))
    refuses(t, 429, PAUSED.format(1), *b_ship(t, 'ship-b'))
    t.clock[0] += 60
    with t.station.transaction() as db:
        assert trust_window(db, t.trust['grant_id']) == (first, 1, 1)
    renew((t.station, t.admin), t.trust['grant_id'], days=90, expect=1)
    second = rows(t.station)[-1]['seq']
    assert second != first
    with t.station.transaction() as db:
        assert trust_window(db, t.trust['grant_id']) == (second, 1, 0)
    pairs(t, *b_ship(t, 'ship-b'))
    refuses(t, 429, PAUSED.format(1), *b_ship(t, 'ship-c'))
    assert window_rows(t.station) == [('ship-a', first), ('ship-b', second)]
    with t.station.transaction() as db:
        assert trust_window(db, t.trust['grant_id']) == (second, 1, 1)


def test_expect_is_required_and_bounded(paired):
    station, admin, contact, card = paired
    bad = (0, 10_001, -1, True, '5', 5.0, None)
    for expect in bad:  # checked before the password, so a wrong password still says 400
        with pytest.raises(Problem) as caught:
            grant(paired, expect=expect, password='not-the-password')
        assert caught.value.status == 400
    assert rows(station) == []
    with pytest.raises(TypeError):
        station.grant_owner_trust(admin['id'], contact['id'], days=90, password=PASSWORD, source='127.0.0.1')
    done = grant(paired, expect=10_000)
    before = rows(station)
    assert before[0]['expect'] == 10_000
    for expect in bad:
        with pytest.raises(Problem) as caught:
            renew(paired, done['grant_id'], days=90, expect=expect, password='not-the-password')
        assert caught.value.status == 400
    assert rows(station) == before
    with pytest.raises(TypeError):
        station.renew_owner_trust(admin['id'], done['grant_id'], days=90, expect=5, password=PASSWORD, source='127.0.0.1')


def test_a_revoke_row_carries_no_expect(trusted):
    t = trusted
    revoke(t)
    assert [r['expect'] for r in rows(t.station)] == [50, None]


def test_a_repaired_held_ship_counts_in_the_new_window(trusted):
    t = trusted
    tardis = pairs(t)
    revoked_at = t.clock[0]
    revoke(t)
    t.clock[0] += 60
    later = grant((t.station, t.admin, t.owner, None), expect=1)
    window = rows(t.station)[-1]['seq']
    pairs(t, *b_ship(t, 'tardis', t.card['participant']['id'], now=revoked_at + 1))
    assert window_rows(t.station)[-1] == ('tardis', window)
    refuses(t, 429, PAUSED.format(1), *b_ship(t, 'ship-b'))
    assert later['grant_id'] != t.trust['grant_id']


def test_a_renewal_refuses_a_page_gone_stale(trusted):
    t = trusted
    seen = window_of(t.station, t.trust['grant_id'])
    pairs(t)
    t.clock[0] += 60
    before = rows(t.station)
    with pytest.raises(Problem) as caught:  # before the password: a wrong one still says 409
        renew((t.station, t.admin), t.trust['grant_id'], days=90, seen=seen, password='not-the-password')
    assert caught.value.status == 409 and 'read the page again' in caught.value.message
    assert rows(t.station) == before
    for bad in (None, [1, 0], (True, 0), (1,)):
        with pytest.raises(Problem) as caught:
            t.station.renew_owner_trust(t.admin['id'], t.trust['grant_id'], days=90, expect=5, seen=bad,
                                        password=PASSWORD, source='127.0.0.1')
        assert caught.value.status == 400
    with pytest.raises(TypeError):
        t.station.renew_owner_trust(t.admin['id'], t.trust['grant_id'], days=90, expect=5, password=PASSWORD,
                                    source='127.0.0.1')
    renew((t.station, t.admin), t.trust['grant_id'], days=90, seen=window_of(t.station, t.trust['grant_id']))
    assert len(rows(t.station)) == 2


def test_the_pause_comes_before_the_cap(trusted):
    t = trusted
    expect_more(t, 200)
    seq = window_of(t.station, t.trust['grant_id'])[0]
    with t.station.transaction() as db:
        db.executemany('INSERT INTO trust_confirmations VALUES (?,?,?,?,?,?,?,?)',
                       [(f'seed-{i}', f'contact-{i}', t.trust['grant_id'], '{}', t.ship, t.clock[0], utc_day(t.clock[0]), seq)
                        for i in range(200)])
    refuses(t, 429, PAUSED.format(200), *b_ship(t, 'one-too-many'))
    with t.station.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM trust_cap_refusals').fetchone()[0] == 0


def test_two_pairings_at_the_last_slot_pair_one(trusted):
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=1)
    feds = [Federation(Store(t.station.data_dir, clock=lambda: t.clock[0]), endpoint='https://localhost:7436')
            for _ in range(2)]
    ships = [b_ship(t, name) for name in ('serenity', 'defiant')]
    start, results = threading.Barrier(2), [None, None]

    def attempt(i):
        start.wait()
        try:
            results[i] = feds[i].pair_trusted(t.ship, *ships[i])
        except Problem as problem:
            results[i] = problem
    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert sorted(type(r).__name__ for r in results) == ['Problem', 'dict']
    lost = next(r for r in results if isinstance(r, Problem))
    assert lost.status == 429 and lost.message == PAUSED.format(1)
    assert window_of(t.station, t.trust['grant_id'])[1] == 1
    assert len(window_rows(t.station)) == 1


def test_trust_confirmations_are_append_only_and_expect_is_checked_by_the_table(trusted):
    t = trusted
    pairs(t)
    for sql in ('UPDATE trust_confirmations SET day=day', 'DELETE FROM trust_confirmations'):
        with t.station.transaction() as db, pytest.raises(sqlite3.IntegrityError, match='append-only'):
            db.execute(sql)
    for event, expect in (('grant', None), ('renew', 0), ('grant', 10_001)):
        with t.station.transaction() as db, pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,at,expect) VALUES (?,?,?,?,?,?)',
                       ('x', event, 'p', 'o', 0, expect))
    with t.station.transaction() as db:
        db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,at) VALUES ('x','revoke','p','o',0)")


def test_a_ship_paired_during_the_password_check_stales_the_renewal(trusted, monkeypatch):
    t = trusted
    seen = window_of(t.station, t.trust['grant_id'])
    real = type(t.station)._trust_password

    def pair_then_check(self, *args):
        pairs(t)  # lands after the first check, before the write
        return real(self, *args)
    monkeypatch.setattr(type(t.station), '_trust_password', pair_then_check)
    t.clock[0] += 60
    before = rows(t.station)
    with pytest.raises(Problem) as caught:
        renew((t.station, t.admin), t.trust['grant_id'], days=90, seen=seen)
    assert caught.value.status == 409 and 'read the page again' in caught.value.message
    assert rows(t.station) == before and len(window_rows(t.station)) == 1


# Task 6: seeing it: connections, the digest and the pause notice in Ops, station-trust-list, and the label everywhere

DIGEST_END = '. Full ids: make station-trust-list on the Pi.'
PAUSE_TEXT = ("Owner trust for {owner} on {peer} paused after {n} pairings. make station-trust-list shows them; if you "
              "didn't expect them, unpair that peer as retired; otherwise renew or revoke it in the browser.")


def notices(station, kind):
    return [notice for notice in station.station_notices() if notice['id'].startswith(f'trust-{kind}-')]


def midnight_after(at):
    return (int(at) // 86400 + 1) * 86400


def test_connections_say_confirmed_by_owner_trust(trusted):
    from superyak_peer.__main__ import describe_connections
    t = trusted
    ship = pairs(t)
    listed = {c['id']: c for c in t.fed.connections(t.admin['id'])}
    mine, owner = listed[ship['id']], listed[t.owner['id']]
    assert (mine['confirmed_by'], mine['confirmed'], mine['pairing_code'], mine['held']) == ('owner trust', True, None, False)
    assert mine['owner_trust'] is None and mine['name'] == 'ship of Andy B: tardis'
    assert mine['card']['participant'] == t.card['participant']  # the card it was paired with, its own name in it
    assert (owner['confirmed_by'], owner['confirmed'], owner['name']) == ('typing', True, 'Andy B')
    assert owner['pairing_code'] is not None
    assert owner['owner_trust'] == {'grant_id': t.trust['grant_id'], 'until': t.trust['until'], 'live': True}
    shown = describe_connections(list(listed.values()), now=t.clock[0]).splitlines()
    assert any(line.startswith('ship of Andy B: tardis (') and ', confirmed by owner trust' in line for line in shown)
    assert any(line.startswith('Andy B (') and ', confirmed by typing' in line for line in shown)
    contacts = {c['id']: c['name'] for c in t.station.contacts(t.admin['id'])}
    assert contacts[ship['id']] == 'ship of Andy B: tardis' and contacts[t.owner['id']] == 'Andy B'
    revoke(t)  # the ship is held, and the owner's trust is no longer live
    listed = {c['id']: c for c in t.fed.connections(t.admin['id'])}
    assert (listed[ship['id']]['confirmed_by'], listed[ship['id']]['confirmed'], listed[ship['id']]['held']) == (None, False, True)
    assert listed[ship['id']]['name'] == 'ship of Andy B: tardis'
    assert listed[t.owner['id']]['owner_trust'] == {'grant_id': t.trust['grant_id'], 'until': t.trust['until'], 'live': False}
    assert 'held until its own code is typed' in describe_connections(list(listed.values()), now=t.clock[0])


def test_a_layer_preview_names_a_ship_by_its_label(trusted):
    t = trusted
    ship = pairs(t)
    layer = t.station.create_layer(t.admin['id'], {'body': 'for a ship and its owner', 'audience_users': [ship['id'], t.owner['id']]})
    preview = t.station.preview_layer(t.admin['id'], layer['id'])
    assert (preview['id'], preview['body'], preview['owner_id']) == (layer['id'], 'for a ship and its owner', t.admin['id'])
    assert preview['people'] == [{'id': ship['id'], 'name': 'ship of Andy B: tardis'}, {'id': t.owner['id'], 'name': 'Andy B'}]


def test_the_digest_comes_once_the_day_ends(trusted):
    t = trusted
    with t.station.transaction() as db:
        defiant = t.station._new_ship(db, 'defiant', 'Defiant', t.admin['id'])['id']
    first = utc_day(t.clock[0])
    pairs(t, *b_ship(t, 'ship-a'))
    pairs(t, *b_ship(t, 'ship-b'))
    t.fed.pair_trusted(defiant, *b_ship(t, 'ship-c'))
    assert notices(t.station, 'digest') == []  # today hasn't ended
    t.clock[0] = midnight_after(t.clock[0]) + 60
    second = utc_day(t.clock[0])
    pairs(t, *b_ship(t, 'ship-d'))
    with t.station.transaction() as db:  # as pair_trusted counts a refusal at the cap
        db.execute('INSERT INTO trust_cap_refusals VALUES (?,?,2)', (t.trust['grant_id'], second))
    g12, peer12 = t.trust['grant_id'][:12], t.owner['peer_id'][:12]
    one = {'id': f'trust-digest-{g12}-{first}',
           'text': f'Owner trust, {first}: 3 ship(s) of Andy B on {peer12} paired by defiant, rio-grande{DIGEST_END}'}
    assert notices(t.station, 'digest') == [one]
    t.clock[0] = midnight_after(t.clock[0]) + 60
    two = {'id': f'trust-digest-{g12}-{second}',
           'text': f'Owner trust, {second}: 1 ship(s) of Andy B on {peer12} paired by rio-grande; 2 refused at the cap '
                   f'of 200{DIGEST_END}'}
    assert notices(t.station, 'digest') == [one, two]
    t.clock[0] = midnight_after(t.clock[0]) + 6 * 86400 - 1  # the first day ended 8 days ago less a second, the second 7
    assert notices(t.station, 'digest') == [two]
    t.clock[0] += 1
    assert notices(t.station, 'digest') == []


def test_the_digest_is_one_safe_line(trusted):
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=1)
    ship = pairs(t, *b_ship(t, 'ship-a'))
    with t.station.transaction() as db:  # longer than a card holds, so by hand
        db.execute('UPDATE remote_contacts SET name=? WHERE id=?', ('Andy\n@rio-grande ' + 'x' * 300, t.owner['id']))
    t.clock[0] = midnight_after(t.clock[0]) + 60
    [digest], [pause] = notices(t.station, 'digest'), notices(t.station, 'paused')
    for text in (digest['text'], pause['text']):
        assert '\n' not in text and '@' not in text and 'Andy (at)rio-grande xxx' in text
    assert digest['text'].endswith(f' on {t.owner["peer_id"][:12]} paired by rio-grande{DIGEST_END}')
    assert pause['text'].endswith(f' on {t.owner["peer_id"][:12]} paused after 1 pairings. make station-trust-list shows '
                                  "them; if you didn't expect them, unpair that peer as retired; otherwise renew or revoke "
                                  'it in the browser.')
    assert len(digest['text']) < 300 and len(pause['text']) < 360
    assert label_of(t.station, ship['id']).startswith('ship of Andy\n@rio-grande x')  # the view keeps it; lines make it safe


def test_a_pause_posts_once_per_window(trusted):
    t = trusted
    revoke(t)
    t.clock[0] += 60
    t.trust = grant((t.station, t.admin, t.owner, None), expect=1)
    assert notices(t.station, 'paused') == []
    pairs(t, *b_ship(t, 'ship-a'))
    first = window_of(t.station, t.trust['grant_id'])[0]
    g12, peer12 = t.trust['grant_id'][:12], t.owner['peer_id'][:12]
    paused = [{'id': f'trust-paused-{g12}-{first}', 'text': PAUSE_TEXT.format(owner='Andy B', peer=peer12, n=1)}]
    assert notices(t.station, 'paused') == paused
    t.clock[0] += 3600
    assert notices(t.station, 'paused') == paused  # the same id and text each cycle, so Odo posts it once
    renew((t.station, t.admin), t.trust['grant_id'], days=90, expect=2)
    assert notices(t.station, 'paused') == []
    pairs(t, *b_ship(t, 'ship-b'))
    assert notices(t.station, 'paused') == []
    pairs(t, *b_ship(t, 'ship-c'))
    second = window_of(t.station, t.trust['grant_id'])[0]
    assert second != first
    assert notices(t.station, 'paused') == [{'id': f'trust-paused-{g12}-{second}',
                                              'text': PAUSE_TEXT.format(owner='Andy B', peer=peer12, n=2)}]
    revoke(t)  # a revoked trust is the admin's answer: nothing more to raise
    assert notices(t.station, 'paused') == []


def test_an_assertion_naming_another_station_is_refused(trusted):
    """Tardis's read of the plan: the assertion's station is bound to the presented card's peer, by verify_record under
    the stored card. B's key signs, by hand, a record naming peer C, where the same owner id is a contact under a live
    trust of its own; presented with B's card it is refused at check 3, and nothing is written."""
    t = trusted
    andy_c, _ = third_peer(t)
    t.station.grant_owner_trust(t.admin['id'], andy_c['id'], days=30, expect=50, password=PASSWORD, source='127.0.0.1')
    card, honest = b_ship(t, 'ship-x')
    record = {**honest['record'], 'station': andy_c['peer_id']}
    signature = base64.b64encode(t.machine[3].identity.key.sign(canonical(record))).decode()
    refuses(t, 400, "does not verify under this peer's card", card, {'record': record, 'signature': signature})
    assert pairs(t, card, honest)['grant_id'] == t.trust['grant_id']  # the same ship, naming B, pairs under B's trust


def test_station_trust_list_names_full_ids(trusted):
    t = trusted
    ship = pairs(t)
    done = run('station-trust-list', '--data-dir', t.station.data_dir)
    assert done.returncode == 0 and done.stderr == '', done.stderr
    lines = done.stdout.splitlines()
    until = datetime.fromtimestamp(t.trust['until'], timezone.utc).strftime('%Y-%m-%d')
    assert lines[1] == f'{t.trust["grant_id"][:6]}  Andy B on {t.owner["peer_id"][:12]}, until {until}: live, 1 of 50 paired in this window'
    assert lines[2].startswith(f'  ship of Andy B: tardis  participant {t.card["participant"]["id"]}, paired by rio-grande ')
    assert lines[2].endswith(' UTC, in this window') and len(lines) == 3
    from superyak_peer.identity import show_code
    for card in (t.card, t.machine[3].card(t.machine[1]['id'])):  # no pairing code, whole or shown
        assert pairing_code(card) not in done.stdout and show_code(pairing_code(card)) not in done.stdout
    assert not re.search(r'[0-9a-f]{4}( [0-9a-f]{4}){7}', done.stdout)
    revoke(t)
    done = run('station-trust-list', '--data-dir', t.station.data_dir)
    lines = done.stdout.splitlines()
    assert ': revoked ' in lines[1] and lines[1].endswith('(by andy)') and lines[2].endswith(' UTC, in this window, held')
    assert ship['id'] not in done.stdout  # the local contact id isn't the participant id


# The display-read check: every SQL text in superyak_peer that reads remote_contacts.name raw (a column, an alias's
# .name, a bare name beside the table, or *), apart from these, each by (module, a piece of its text) and why.
RAW_NAME_READS = {
    ('federation.py', 'SELECT username, name FROM users UNION ALL SELECT name, name FROM remote_contacts'):
        "_name_taken, the collision check: a ship's name against every person's raw name",
    ('federation.py', 'ON CONFLICT(peer_id,user_id) DO UPDATE SET name=excluded.name'):
        "a write: pair() stores the card's participant name",
    ('federation.py', 'UPDATE remote_contacts SET name=? WHERE id=?'):
        "a write: pair_trusted stores the assertion's ship name",
    ('federation.py', 'remote_contacts.name AS card_name'):
        "connections() rebuilds the card it was paired with, as code_current does; it shows the label",
    ('owner_trust.py', 'CREATE VIEW IF NOT EXISTS contact_labels'):
        'the view itself, which makes every label from the raw name',
    ('owner_trust.py', 'SELECT remote_contacts.user_id,remote_contacts.name,peers.card'):
        "code_current rebuilds the paired card with its participant's name, to check the typed code",
    ('backups.py', 'SELECT id, peer_id, user_id, name AS label FROM remote_contacts'):
        'a restore file from before owner trust: no view and no trust confirmation (one schema batch makes both), '
        'so every contact there is a person, whose name is its label',
}
SQL_WORD = re.compile(r'\b(SELECT|INSERT|UPDATE|DELETE|CREATE|WITH)\b', re.IGNORECASE)
NOT_ALIASES = {'join', 'where', 'on', 'using', 'left', 'inner', 'cross', 'outer', 'natural', 'order', 'group', 'having',
               'values', 'set', 'limit', 'as', 'union', 'except', 'intersect', 'and', 'or', 'not', 'returning', 'window'}


def strings_of(source):
    """(qualified function, line, text) for each string the code holds: constants, f-strings (each {...} as '{}') and
    strings joined by +. Docstrings and other bare string statements are left out."""
    import ast
    found = []

    def text_of(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return ''.join(part.value if isinstance(part, ast.Constant) else '{}' for part in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = text_of(node.left), text_of(node.right)
            return left + right if left is not None and right is not None else None
        return None

    def visit(node, where):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            where = f'{where}.{node.name}' if where else node.name
        if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            return
        text = text_of(node)
        if text is not None:
            found.append((where or '<module>', node.lineno, text))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, where)
    visit(ast.parse(source), '')
    return found


def reads_contact_name(sql):
    """Whether one SQL statement reads remote_contacts' raw name. A table's own definition is not a read."""
    if not re.search(r'\bremote_contacts\b', sql) or not SQL_WORD.search(sql):
        return False
    if re.match(r'\s*CREATE\s+(TABLE|INDEX|UNIQUE)\b', sql, re.IGNORECASE) and not re.search(r'\bSELECT\b', sql, re.IGNORECASE):
        return False
    aliases = {m.group(1) for m in re.finditer(r'\bremote_contacts\s+(?:AS\s+)?([A-Za-z_]\w*)', sql, re.IGNORECASE)
               if m.group(1).lower() not in NOT_ALIASES}
    if any(re.search(rf'\b{re.escape(alias)}\.(name\b|\*)', sql) for alias in ('remote_contacts', *aliases)):
        return True
    if re.search(r'(?<![\w.])(?<!AS )name\b', sql, re.IGNORECASE):  # a bare name; `AS name` names a result instead
        return True
    return bool(re.search(r'\bSELECT\s+\*\s+FROM\s+remote_contacts\b', sql, re.IGNORECASE))


def contact_name_reads(root):
    """(module path under root, function, line, statement) for each statement that reads the raw name."""
    return [(path.relative_to(root).as_posix(), where, line, statement.strip())
            for path in sorted(root.rglob('*.py'))
            for where, line, text in strings_of(path.read_text())
            for statement in text.split(';') if reads_contact_name(statement)]


def explained(read):
    return any(read[0] == module and piece in read[3] for module, piece in RAW_NAME_READS)


def test_display_reads_go_through_contact_labels():
    """Tardis's ruling: every display of a remote contact's name (contacts(), connections(), room members, message
    authors, the notices, trust_list) reads contact_labels.label, so a ship reads "ship of <owner>: <name>" wherever it
    shows. Only the reads RAW_NAME_READS names, each with its reason, take the raw name; each of those still exists."""
    import superyak_peer
    root = Path(superyak_peer.__file__).parent
    found = contact_name_reads(root)
    assert [read for read in found if not explained(read)] == []
    assert [key for key in RAW_NAME_READS if not any(read[0] == key[0] and key[1] in read[3] for read in found)] == []


def test_the_display_read_check_finds_a_planted_read(tmp_path):
    (tmp_path / 'planted.py').write_text('''
def shown(db, contact_id, table):
    db.execute('SELECT name FROM remote_contacts WHERE id=?', (contact_id,))
    db.execute("SELECT c.name, rooms.title FROM rooms JOIN remote_contacts AS c ON c.id=rooms.owner_id")
    db.execute(f'SELECT remote_contacts.name FROM remote_contacts WHERE id={contact_id}')
    db.execute('SELECT * FROM remote_contacts WHERE id=?', (contact_id,))
    db.execute('SELECT x.* FROM remote_contacts x' + ' WHERE x.id=?', (contact_id,))
    db.execute('SELECT group_concat(name) FROM (SELECT name FROM remote_contacts ORDER BY name)')
    db.execute('SELECT label FROM contact_labels WHERE id=?', (contact_id,))
    db.execute('SELECT c.id, l.label AS name FROM remote_contacts c JOIN contact_labels l ON l.id=c.id')
    db.execute('SELECT username, name FROM users WHERE id=?', (contact_id,))
    _has(db, 'remote_contacts.name')
    """A docstring may say SELECT name FROM remote_contacts."""
''')
    assert [(where, line) for _, where, line, _ in contact_name_reads(tmp_path)] == [('shown', n) for n in range(3, 9)]
