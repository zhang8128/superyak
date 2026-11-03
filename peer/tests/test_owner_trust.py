import json
import re
import sqlite3
import subprocess
import sys

import pytest
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import canonical, check_ship_assertion, make_ship_assertion, pairing_code
from superyak_peer.owner_trust import OWNER_TRUST_STATEMENTS, OWNER_TRUST_SCHEMA, live_trust

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


def grant(paired, days=90, password=PASSWORD):
    station, admin, contact, card = paired
    return station.grant_owner_trust(admin['id'], contact['id'], days=days, password=password, source='127.0.0.1')


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
    renewed = station.renew_owner_trust(admin['id'], done['grant_id'], days=60, password=PASSWORD, source='127.0.0.1')
    assert renewed['grant_id'] == done['grant_id'] and renewed['until'] == NOW + 60 * 86400 > done['until']
    assert [r['event'] for r in rows(station)] == ['grant', 'renew']
    with pytest.raises(Problem) as caught:
        station.renew_owner_trust(admin['id'], done['grant_id'], days=5, password=PASSWORD, source='127.0.0.1')
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


def renew(paired, grant_id, days=30, password=PASSWORD):
    station, admin = paired[:2]
    return station.renew_owner_trust(admin['id'], grant_id, days=days, password=password, source='127.0.0.1')


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
        db.execute('INSERT INTO trust_confirmations VALUES (?,?,?,?,?,?,?)', ('t', contact['id'], 'g', '{}', 's', NOW, '2027-01-15'))
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
