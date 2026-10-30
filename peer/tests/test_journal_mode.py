"""station-journal (spec 2026-10-29-store-wal-mode D1, plan Task 1): the journal mode is switched under the dispatch
gate, decided by SQLite's own lock, only with every station unit stopped, and never creates a store or a gate file."""
import os
from pathlib import Path
import sqlite3
import stat
import threading
import time

import pytest

from superyak_peer import journal_mode
from superyak_peer.db import Store
from superyak_peer.dispatch import DispatchGate
from superyak_peer.journal_mode import STATION_UNITS_TO_STOP, header_mode, switch_journal, units_active

REPO = Path(__file__).resolve().parents[2]
NAMED = ('superyak-lighthouse', 'superyak-door', 'superyak-ship', 'superyak-odo', 'superyak-wormhole')


def station(tmp_path):
    store = Store(tmp_path / 'station')
    with store.transaction():  # a store that has run holds dispatch.lock, as the live one does
        pass
    return store


def listing(directory):
    return sorted(p.name for p in Path(directory).iterdir())


def none_active():
    return []


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_switches_to_wal_and_back_and_a_second_run_changes_nothing(tmp_path):
    store = station(tmp_path)
    assert switch_journal(store.data_dir, 'wal', active=none_active) == ('delete', 'wal')
    assert header_mode(store.db_path) == 'wal'
    assert switch_journal(store.data_dir, 'wal', active=none_active) == ('wal', 'wal')
    assert switch_journal(store.data_dir, 'delete', active=none_active) == ('wal', 'delete')
    assert header_mode(store.db_path) == 'delete'
    assert not any(name.endswith(('-wal', '-shm')) for name in listing(store.data_dir))


def test_refuses_a_missing_store_and_creates_nothing(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(ValueError, match='peer.sqlite3'):
        switch_journal(empty, 'wal', active=none_active)
    assert listing(empty) == []


def test_refuses_without_dispatch_lock_and_creates_none(tmp_path):
    store = station(tmp_path)
    (store.data_dir / 'dispatch.lock').unlink()
    before = listing(store.data_dir)
    with pytest.raises(ValueError, match='dispatch.lock'):
        switch_journal(store.data_dir, 'wal', active=none_active)
    assert listing(store.data_dir) == before and header_mode(store.db_path) == 'delete'


@pytest.mark.parametrize('name', ['peer.sqlite3', 'peer.sqlite3-journal', 'peer.sqlite3-wal', 'peer.sqlite3-shm'])
def test_refuses_a_symlink_among_the_four_names(tmp_path, name):
    store = station(tmp_path)
    target = tmp_path / 'elsewhere'
    if name == 'peer.sqlite3':
        os.replace(store.db_path, target)
    else:
        target.write_bytes(b'')
    (store.data_dir / name).symlink_to(target)
    before = listing(store.data_dir)
    with pytest.raises(ValueError, match='ymlink'):
        switch_journal(store.data_dir, 'wal', active=none_active)
    assert listing(store.data_dir) == before


def test_refuses_a_symlinked_data_dir_or_gate_file(tmp_path):
    """The data directory itself, or dispatch.lock, as a symlink is refused by name (the review's J6 and N4)."""
    store = station(tmp_path)
    link = tmp_path / 'link'
    link.symlink_to(store.data_dir)
    with pytest.raises(ValueError, match='ymlink'):
        switch_journal(link, 'wal', active=none_active)
    lock = store.data_dir / 'dispatch.lock'
    os.replace(lock, tmp_path / 'lock-elsewhere')
    lock.symlink_to(tmp_path / 'lock-elsewhere')
    with pytest.raises(ValueError, match='ymlink'):
        switch_journal(store.data_dir, 'wal', active=none_active)
    assert header_mode(store.db_path) == 'delete'


def test_a_damaged_store_is_refused_in_words(tmp_path):
    """A file that isn't a database ends as "nothing was changed", not a traceback (the review's N1), and keeps its bytes."""
    store = station(tmp_path)
    store.db_path.write_bytes(b'not a database at all ' * 50)
    before = store.db_path.read_bytes()
    with pytest.raises(ValueError, match='nothing was changed'):
        switch_journal(store.data_dir, 'wal', active=none_active)
    assert store.db_path.read_bytes() == before


def test_refuses_while_a_unit_is_active(tmp_path):
    store = station(tmp_path)
    with pytest.raises(ValueError, match='superyak-odo.service'):
        switch_journal(store.data_dir, 'wal', active=lambda: ['superyak-odo.service'])
    assert header_mode(store.db_path) == 'delete'


# systemd 252's `is-active` (the Pi's) exits 0 only for these; `activating` and `deactivating` exit 3 (the review's S1)
EXIT_0 = ('active', 'reloading', 'refreshing')


def stub_systemctl(tmp_path, monkeypatch, states, code=None):
    """A `systemctl` on PATH that prints each unit's state from `states` (a dict), exiting as systemctl does."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(parents=True)
    script = bin_dir / 'systemctl'
    lines = ['#!/bin/sh', 'unit="$3"', 'case "$unit" in']
    for unit, state in states.items():
        exit_code = code if code is not None else (0 if state in EXIT_0 else 3)
        lines.append(f'  {unit}) {"echo " + state if state else ":"}; exit {exit_code} ;;')
    lines += ['  *) echo inactive; exit 3 ;;', 'esac']
    script.write_text('\n'.join(lines) + '\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv('PATH', f'{bin_dir}{os.pathsep}{os.environ["PATH"]}')


@pytest.mark.parametrize('state', ['active', 'activating', 'deactivating', 'reloading', 'refreshing'])
def test_units_active_counts_every_running_state(tmp_path, monkeypatch, state):
    """By the state printed, with systemctl's own exit codes: a lighthouse in `activating (auto-restart)` exits 3 and is
    still running. Mutation: running decided by exit 0 alone."""
    stub_systemctl(tmp_path, monkeypatch, {'superyak-door.service': state})
    assert units_active() == ['superyak-door.service']


def test_units_active_counts_any_exit_0_as_running(tmp_path, monkeypatch):
    """A state this code doesn't know, from a newer systemd, with exit 0 is counted as running (the review's N3)."""
    stub_systemctl(tmp_path, monkeypatch, {'superyak-door.service': 'maintenance'}, code=0)
    assert units_active() == ['superyak-door.service']


@pytest.mark.parametrize('state', ['inactive', 'failed'])
def test_units_active_leaves_out_a_stopped_unit(tmp_path, monkeypatch, state):
    stub_systemctl(tmp_path, monkeypatch, {'superyak-door.service': state})
    assert units_active() == []


def test_units_active_fails_closed_when_systemctl_cannot_answer(tmp_path, monkeypatch):
    stub_systemctl(tmp_path, monkeypatch, {'superyak-door.service': 'active'}, code=1)
    with pytest.raises(ValueError, match='systemctl'):
        units_active()
    stub_systemctl(tmp_path / 'again', monkeypatch, {'superyak-door.service': ''}, code=0)
    with pytest.raises(ValueError, match='systemctl'):
        units_active()


def test_every_station_service_is_stopped_first():
    units = set(STATION_UNITS_TO_STOP)
    assert {f'{name}.service' for name in NAMED} <= units  # their unit files live outside the repo
    shipped = {p.name for p in (REPO / 'peer' / 'systemd').glob('*.service')} - {'superyak-alert@.service'}
    assert shipped and shipped <= units


def test_retries_locked_to_delete_then_gives_up_unchanged(tmp_path):
    store = station(tmp_path)
    switch_journal(store.data_dir, 'wal', active=none_active)
    clock = Clock()
    idle = sqlite3.connect(store.db_path)  # an idle open connection keeps a WAL store from leaving WAL
    idle.execute('SELECT 1 FROM system_meta').fetchone()
    try:
        with pytest.raises(ValueError, match='locked'):
            switch_journal(store.data_dir, 'delete', active=none_active, clock=clock, sleep=clock.sleep)
        assert clock.now >= 10 and header_mode(store.db_path) == 'wal'
    finally:
        idle.close()


def test_retries_locked_to_wal_then_gives_up_unchanged(tmp_path):
    store = station(tmp_path)
    clock = Clock()
    reader = sqlite3.connect(store.db_path, isolation_level=None)
    reader.execute('BEGIN')
    reader.execute('SELECT * FROM system_meta').fetchall()  # a reader mid-read holds SHARED
    try:
        with pytest.raises(ValueError, match='locked'):
            switch_journal(store.data_dir, 'wal', active=none_active, clock=clock, sleep=clock.sleep)
        assert clock.now >= 10 and header_mode(store.db_path) == 'delete'
    finally:
        reader.execute('ROLLBACK')
        reader.close()


def test_switch_holds_the_gate(tmp_path, monkeypatch):
    """Another thread can't enter the gate while the switch runs: it waits until the switch is done."""
    store = station(tmp_path)
    real, seen = journal_mode._set_mode, {}

    def probe():
        started = time.monotonic()
        with DispatchGate(store.data_dir / 'dispatch.lock'):
            seen['waited'] = time.monotonic() - started
    thread = threading.Thread(target=probe)

    def slow_set_mode(db, mode):
        thread.start()
        time.sleep(0.3)
        return real(db, mode)
    monkeypatch.setattr(journal_mode, '_set_mode', slow_set_mode)
    switch_journal(store.data_dir, 'wal', active=none_active)
    thread.join(5)
    assert seen['waited'] >= 0.25


def test_cli_prints_before_and_after(tmp_path, monkeypatch, capsys):
    from superyak_peer.__main__ import main
    store = station(tmp_path)
    monkeypatch.setattr(journal_mode, 'units_active', none_active)
    main(['station-journal', '--data-dir', str(store.data_dir), '--mode', 'wal'])
    assert 'Journal mode: delete -> wal' in capsys.readouterr().out
    with pytest.raises(SystemExit) as stopped:
        main(['station-journal', '--data-dir', str(tmp_path / 'nowhere'), '--mode', 'wal'])
    assert stopped.value.code == 1


def test_header_mode_reads_the_file_header(tmp_path):
    store = station(tmp_path)
    assert header_mode(store.db_path) == 'delete'
    short = tmp_path / 'short.sqlite3'
    short.write_bytes(b'SQLite')
    assert header_mode(short) == 'delete'  # a short header counts as not WAL


def test_refuses_when_sqlite_answers_another_mode(tmp_path, monkeypatch):
    """SQLite answers the mode it is in; a switch it silently declined is reported, not printed as done."""
    store = station(tmp_path)
    monkeypatch.setattr(journal_mode, '_set_mode', lambda db, mode: 'memory')
    with pytest.raises(ValueError, match='memory'):
        switch_journal(store.data_dir, 'wal', active=none_active)

