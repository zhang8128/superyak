import json
import re
import subprocess
import sys

import pytest
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.federation import Federation
from superyak_peer.identity import check_ship_assertion, make_ship_assertion

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
