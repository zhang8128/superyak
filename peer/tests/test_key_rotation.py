"""Rotating the connector's key (docs/superpowers/specs/2026-10-30-connector-key-rotation-design.md).

A process holds the key in memory, so each test's "restart" is a new app on the same data directory, which is what the
station's units do after the command has run with them stopped."""
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from connector_support import (CALLBACK, PUBLIC_ORIGIN, a_fragment, allowed, authorize, bearer, connected, decide, exchange,  # noqa: F401
                               home, person, refresh, register, sign_in, signed_in)
from superyak_peer import journal_mode, key_rotation
from superyak_peer.__main__ import main
from superyak_peer.app import create_app
from superyak_peer.backups import _keep_connector_key_like_replaced
from superyak_peer.connector import KEY_NAME
from superyak_peer.db import Store


def data_dir(home):
    return Path(home.store.data_dir)


def rotate(home, **options):
    return key_rotation.rotate(data_dir(home), active=lambda: [], clock=lambda: home.clock[0], **options)


def restarted(home):
    clock = home.clock
    app = create_app(data_dir(home), clock=lambda: clock[0], allowed_origins=['http://testserver', PUBLIC_ORIGIN],
                     public_origin=PUBLIC_ORIGIN)
    return SimpleNamespace(app=app, store=app.state.store, clock=clock)


def raw(home):
    return sqlite3.connect(data_dir(home) / 'peer.sqlite3', isolation_level=None)


def meta(home):
    with raw(home) as db:
        return dict(db.execute('SELECT key, value FROM system_meta'))


def set_key(home, value):
    with raw(home) as db:
        if value is None:
            db.execute('DELETE FROM system_meta WHERE key=?', (KEY_NAME,))
        else:
            db.execute('UPDATE system_meta SET value=? WHERE key=?', (value, KEY_NAME))


def pending_rows(home):
    with raw(home) as db:
        return db.execute('SELECT COUNT(*) FROM oauth_pending').fetchone()[0]


# ---------------------------------------------------------------- when it refuses

def test_it_refuses_while_a_unit_runs_and_writes_nothing(home):
    signed_in_at_all = person(home) and signed_in(home)
    assert signed_in_at_all
    before, rows = meta(home), pending_rows(home)
    with pytest.raises(ValueError, match='superyak-lighthouse.service'):
        key_rotation.rotate(data_dir(home), active=lambda: ['superyak-lighthouse.service'])
    assert meta(home) == before and pending_rows(home) == rows == 1


def test_a_check_that_cant_answer_refuses_too(home):
    before = meta(home)

    def no_answer():
        raise ValueError('systemctl could not say')
    with pytest.raises(ValueError, match='systemctl could not say'):
        key_rotation.rotate(data_dir(home), active=no_answer)
    assert meta(home) == before


def test_it_uses_the_stations_own_check_by_default(home, monkeypatch):
    monkeypatch.setattr(journal_mode, 'units_active', lambda: ['superyak-door.service'])
    monkeypatch.setattr(key_rotation, 'units_active', journal_mode.units_active)
    with pytest.raises(ValueError, match='superyak-door.service'):
        key_rotation.rotate(data_dir(home))


def test_a_store_held_locked_changes_nothing_and_says_so(home):
    before = meta(home)
    holder = raw(home)
    holder.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(ValueError, match='nothing was changed'):
            key_rotation.rotate(data_dir(home), active=lambda: [], busy_seconds=0.05)
    finally:
        holder.execute('ROLLBACK')
        holder.close()
    assert meta(home) == before


def test_it_makes_no_store_where_none_is(tmp_path):
    with pytest.raises(ValueError, match='no station database'):
        key_rotation.rotate(tmp_path / 'nowhere', active=lambda: [])
    assert not (tmp_path / 'nowhere').exists()


# ---------------------------------------------------------------- what changes

def test_the_key_changes_and_nothing_else_in_system_meta(home):
    before = meta(home)
    report = rotate(home)
    after = meta(home)
    assert re.fullmatch(r'[0-9a-f]{64}', after[KEY_NAME]) and after[KEY_NAME] != before[KEY_NAME]
    assert {k: v for k, v in after.items() if k != KEY_NAME} == {k: v for k, v in before.items() if k != KEY_NAME}
    assert report['key_was'] == 'good'


def test_a_registration_never_allowed_is_unknown_and_its_app_can_register_again(home):
    client = register(home.app).json()['client_id']
    assert authorize(home, client).status_code == 303, 'a good client, before the rotation'
    rotate(home)
    fresh = restarted(home)
    assert authorize(fresh, client).status_code != 303
    again = register(fresh.app).json()['client_id']
    assert authorize(fresh, again).status_code == 303


def test_a_sign_in_not_started_fails_by_its_signature(home):
    person(home)
    client = register(home.app).json()['client_id']
    fragment = a_fragment(home, client)
    assert sign_in(home, a_fragment(home, client)).status_code == 200, 'a good fragment, before the rotation'
    rotate(home)
    assert sign_in(restarted(home), fragment).status_code != 200


def test_a_sign_in_past_its_first_step_has_to_start_again(home):
    person(home)
    _, view = signed_in(home)
    report = rotate(home)
    assert report['pending_removed'] == 1 and pending_rows(home) == 0
    assert decide(restarted(home), view).status_code != 303


def test_a_decided_code_still_exchanges(home):
    client, code = allowed(home)
    assert pending_rows(home) == 1
    report = rotate(home)
    assert report['pending_removed'] == 0 and pending_rows(home) == 1
    answer = exchange(restarted(home), client, code)
    assert answer.status_code == 200, answer.text


# ---------------------------------------------------------------- connections

def test_by_default_a_connection_stays_and_still_refreshes(connected):
    report = rotate(connected)
    assert report['connections_kept'] == 1 and report['connections_ended'] == 0
    fresh = restarted(connected)
    assert bearer(fresh, connected.tokens['access_token']) is not None
    answer = refresh(fresh, connected.client, connected.tokens['refresh_token'])
    assert answer.status_code == 200, answer.text


def app_entries(home, person_id):
    return home.store.connected_apps(person_id)


def test_end_connections_ends_every_live_one_and_says_why(connected):
    report = rotate(connected, end_connections=True)
    assert report['connections_ended'] == 1 and report['connections_kept'] == 0
    fresh = restarted(connected)
    assert refresh(fresh, connected.client, connected.tokens['refresh_token']).status_code != 200
    assert bearer(fresh, connected.tokens['access_token']) is None
    [entry] = app_entries(fresh, connected.person['id'])
    assert entry['ended']['why'] == 'key_rotated'


def test_a_connection_already_ended_keeps_its_reason(connected):
    [entry] = app_entries(connected, connected.person['id'])
    connected.store.connected_app_revoke(connected.person['id'], entry['id'])
    report = rotate(connected, end_connections=True)
    assert report['connections_ended'] == 0
    [entry] = app_entries(restarted(connected), connected.person['id'])
    assert entry['ended']['why'] == 'you'


def test_a_connection_past_its_end_date_keeps_its_reason_and_isnt_counted_kept(connected):
    connected.clock[0] += 400 * 86400
    assert rotate(connected)['connections_kept'] == 0
    report = rotate(connected, end_connections=True)
    assert report['connections_ended'] == 0
    [entry] = app_entries(restarted(connected), connected.person['id'])
    assert entry['ended']['why'] == 'ended'


def test_a_second_run_is_harmless(connected):
    rotate(connected, end_connections=True)
    report = rotate(connected, end_connections=True)
    assert report['connections_ended'] == 0 and report['key_was'] == 'good'


def test_the_page_says_why_it_ended():
    source = Path(__file__).resolve().parent.parent / 'superyak_peer' / 'static' / 'app.js'
    assert ('["key_rotated", "The home\'s connector key was changed, so this connection ended. '
            'Connect again if you still want it."]') in source.read_text()


# ---------------------------------------------------------------- a bad key row

BAD_KEYS = ['not hex at all', 'deadbeef', 'z' * 64, 'a' * 63, 'a' * 65, '']


@pytest.mark.parametrize('value', BAD_KEYS)
def test_a_store_wont_start_on_a_bad_key_and_names_the_command(home, value):
    set_key(home, value)
    with pytest.raises(ValueError, match='make station-connector-rotate-key') as refused:
        Store(data_dir(home))
    assert value == '' or value not in str(refused.value), 'never the value'


def test_a_store_with_no_key_row_still_makes_one_silently(home):
    set_key(home, None)
    Store(data_dir(home))
    assert re.fullmatch(r'[0-9a-f]{64}', meta(home)[KEY_NAME])


def test_a_good_key_in_capitals_still_starts(home):
    set_key(home, 'A' * 64)
    Store(data_dir(home))
    assert meta(home)[KEY_NAME] == 'A' * 64


@pytest.mark.parametrize('value', BAD_KEYS + [None])
@pytest.mark.parametrize('end_connections', [False, True])
def test_the_command_works_on_a_bad_row_and_says_what_it_found(home, value, end_connections):
    set_key(home, value)
    report = rotate(home, end_connections=end_connections)
    assert report['key_was'] == ('absent' if value is None else 'bad')
    assert re.fullmatch(r'[0-9a-f]{64}', meta(home)[KEY_NAME])
    Store(data_dir(home))


def test_the_default_run_builds_no_store_at_all(home, monkeypatch):
    def no_store(*a, **kw):
        raise AssertionError('a Store can\'t start on a bad row, so this path never builds one')
    set_key(home, 'bad')
    monkeypatch.setattr('superyak_peer.db.Store', no_store)
    assert rotate(home)['key_was'] == 'bad'


def test_a_store_with_no_system_meta_changes_nothing_and_says_so(home):
    with raw(home) as db:
        db.execute('DROP TABLE system_meta')
    with pytest.raises(ValueError, match='system_meta'):
        rotate(home)


def test_a_store_from_before_the_connector_has_no_pending_rows_to_remove(home):
    with raw(home) as db:
        db.execute('DROP TABLE oauth_pending')
        db.execute('DROP TABLE connector_tokens')
        db.execute('DROP TABLE connector_grants')
    report = rotate(home)
    assert report['pending_removed'] == 0 and report['connections_kept'] == 0


# ---------------------------------------------------------------- what it says, and restore

@pytest.mark.parametrize('flag, expected', [([], 'stay'), (['--end-connections'], 'ended')])
def test_the_command_prints_counts_and_never_a_key(connected, monkeypatch, capsys, caplog, flag, expected):
    old = meta(connected)[KEY_NAME]
    monkeypatch.setattr(key_rotation, 'units_active', lambda: [])
    main(['station-connector-rotate-key', '--data-dir', str(data_dir(connected)), *flag])
    new = meta(connected)[KEY_NAME]
    out, err = capsys.readouterr()
    assert new != old
    for text in (out, err, caplog.text):
        assert old not in text and new not in text
    assert expected in out and 'Pending sign-ins removed: 0' in out


def test_the_default_says_what_it_did_not_do(connected, monkeypatch, capsys):
    monkeypatch.setattr(key_rotation, 'units_active', lambda: [])
    main(['station-connector-rotate-key', '--data-dir', str(data_dir(connected))])
    assert '--end-connections' in capsys.readouterr().out


def test_end_connections_doesnt_tell_you_to_run_it_again(connected, monkeypatch, capsys):
    monkeypatch.setattr(key_rotation, 'units_active', lambda: [])
    main(['station-connector-rotate-key', '--data-dir', str(data_dir(connected)), '--end-connections'])
    assert 'run it again' not in capsys.readouterr().out


def test_a_refusal_reaches_the_person_as_an_error(home, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(['station-connector-rotate-key', '--data-dir', str(data_dir(home) / 'absent')])
    assert stopped.value.code != 0 and 'no station database' in capsys.readouterr().err


def test_restoring_a_copy_from_before_the_rotation_keeps_the_rotated_key(home, tmp_path):
    copy = sqlite3.connect(tmp_path / 'copy.sqlite3')
    with raw(home) as live:
        live.backup(copy)
    old = meta(home)[KEY_NAME]
    rotate(home)
    rotated = meta(home)[KEY_NAME]
    assert rotated != old
    report = {'counts': {}}
    with raw(home) as replaced:
        _keep_connector_key_like_replaced(copy, replaced, report)
    assert copy.execute('SELECT value FROM system_meta WHERE key=?', (KEY_NAME,)).fetchone()[0] == rotated


def test_make_runs_the_command_with_the_stations_data():
    makefile = (Path(__file__).resolve().parents[2] / 'Makefile').read_text()
    target = re.search(r'^station-connector-rotate-key:\n((?:\t.*\n)+)', makefile, re.M)
    assert target and 'superyak_peer station-connector-rotate-key' in target.group(1)
    assert '--data-dir "$(STATION_DATA)"' in target.group(1)
    assert re.search(r'\.PHONY:.*\bstation-connector-rotate-key\b', makefile)
