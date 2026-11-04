"""Ship home and crossing plan, Tasks 2 to 4: the publisher's side of a crossing. Task 2: the `crossings` table and
crossings.toml (P2). Task 3: the checks, in spec 2.3's order, each before any Engram store, policy, ledger or sidecar is
opened. Task 4: the daemon call, the answer and the `crossings` row (P7)."""
import os
from pathlib import Path

import pytest

from superyak_peer.crossing import SettingsInvalid, hosted_store, load_settings, published_house

from conftest import lesson_ship
from test_federation_outcomes import Clock, station


def write_settings(data_dir, text, *, mtime=None):
    path = Path(data_dir) / 'crossings.toml'
    path.write_text(text)
    if mtime is not None:
        os.utime(path, ns=(mtime, mtime))
    return path


def published(ship='rio-grande', publisher='rio-grande', socket='/run/engram/lighthouse.sock',
              sidecar='/srv/engram/disclosures.db', **more):
    lines = [f'ship = "{ship}"', f'publisher = "{publisher}"', f'daemon_socket = "{socket}"', f'sidecar = "{sidecar}"']
    lines += [f'{key} = "{value}"' for key, value in more.items()]
    return '[[published]]\n' + '\n'.join(lines) + '\n'


INSTANCE = '2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d'


def test_a_store_opened_today_has_the_crossings_table(tmp_path):
    store = station(tmp_path / 'a', 'alice', Clock())[0]
    with store.transaction() as db:
        columns = [(r['name'], r['type'], r['notnull'], r['pk']) for r in db.execute('PRAGMA table_info(crossings)')]
    assert columns == [('disclosure_id', 'TEXT', 0, 1), ('origin_peer', 'TEXT', 1, 0), ('receiver_ref', 'TEXT', 1, 0),
                       ('request_digest', 'TEXT', 1, 0), ('nonce', 'TEXT', 1, 0), ('at', 'INTEGER', 1, 0)]


def test_no_settings_file_publishes_and_hosts_nothing(tmp_path):
    assert load_settings(tmp_path) == {'published': [], 'hosted': []}


def test_settings_are_read(tmp_path):
    write_settings(tmp_path, published() + f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\n')
    assert load_settings(tmp_path) == {
        'published': [{'ship': 'rio-grande', 'publisher': 'rio-grande', 'daemon_socket': '/run/engram/lighthouse.sock',
                       'sidecar': '/srv/engram/disclosures.db'}],
        'hosted': [{'ship': 'tardis', 'instance_id': INSTANCE}]}


@pytest.mark.parametrize('text, words', [
    ('station = "x"\n', 'unknown'),
    (published(colour='red'), 'unknown'),
    (f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\nwhere = "x"\n', 'unknown'),
    (published(socket='/run/engram/host.sock'), 'host.sock'),
    (published(socket='run/lighthouse.sock'), 'absolute'),
    (published(sidecar='disclosures.db'), 'absolute'),
    (published() + published(publisher='other'), 'twice'),
    (f'[[hosted]]\nship = "tardis"\ninstance_id = "{INSTANCE}"\n' * 2, 'twice'),
    ('[[hosted]]\nship = "tardis"\ninstance_id = "NOT-A-UUID"\n', 'instance_id'),
    ('[[published]]\nship = "rio-grande"\n', 'missing'),
    (published(ship='has space'), 'ship'),
    (published(publisher='no:colons'), 'publisher'),
    ('published = 3\n', 'list'),
    ('[[published\n', 'TOML')])
def test_a_bad_settings_file_is_refused(tmp_path, text, words):
    write_settings(tmp_path, text)
    with pytest.raises(SettingsInvalid) as refused:
        load_settings(tmp_path)
    assert words in str(refused.value)


def test_a_symlinked_settings_file_is_refused(tmp_path):
    real = tmp_path / 'elsewhere.toml'
    real.write_text(published())
    (tmp_path / 'crossings.toml').symlink_to(real)
    with pytest.raises(SettingsInvalid):
        load_settings(tmp_path)


def test_an_edit_is_picked_up_without_a_restart(tmp_path):
    write_settings(tmp_path, published(), mtime=1_000_000_000_000_000_000)
    assert load_settings(tmp_path)['published'][0]['publisher'] == 'rio-grande'
    write_settings(tmp_path, published(publisher='the-house'), mtime=1_000_000_001_000_000_000)
    assert load_settings(tmp_path)['published'][0]['publisher'] == 'the-house'
    write_settings(tmp_path, 'station = 1\n', mtime=1_000_000_002_000_000_000)
    with pytest.raises(SettingsInvalid):
        load_settings(tmp_path)


def test_ships_resolve_to_users_of_kind_ship_only(tmp_path):
    """B2: both tables name a ship by username, resolved per request to a users.id of kind `ship`. A person's username
    resolves to nothing, so it publishes nothing and hosts nothing."""
    store, alice, _ = station(tmp_path / 'a', 'alice', Clock())
    rio = lesson_ship(store, alice, 'rio-grande')
    bob = store.create_user('bob', 'Bob', 'a-long-password', is_admin=False)['id']
    write_settings(store.data_dir, published() + published(ship='bob', publisher='bobs')
                   + f'[[hosted]]\nship = "rio-grande"\ninstance_id = "{INSTANCE}"\n'
                   + '[[hosted]]\nship = "bob"\ninstance_id = "00000000-0000-4000-8000-000000000000"\n')
    settings = load_settings(store.data_dir)
    assert published_house(store, settings, rio['id'])['publisher'] == 'rio-grande'
    assert published_house(store, settings, bob) is None
    assert published_house(store, settings, 'nobody') is None
    assert hosted_store(store, settings, rio['id'], INSTANCE)
    assert not hosted_store(store, settings, rio['id'], '00000000-0000-4000-8000-000000000000')
    assert not hosted_store(store, settings, bob, '00000000-0000-4000-8000-000000000000')

