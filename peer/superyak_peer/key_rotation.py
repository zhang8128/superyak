"""station-connector-rotate-key (spec 2026-10-30-connector-key-rotation-design): the connector's key replaced, with every
station unit stopped, since a running one would keep signing with the old key.

It works on the file through one raw connection, as station-journal does, and never through a Store: a Store won't start on a
bad key row, and this command is how that row gets fixed. Any Store it needs comes after the new key has committed. Nothing it
prints or logs holds a key."""
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
import time

from .connector import KEY_NAME, key_is_good
from .dispatch import DispatchGate
from .journal_mode import _store_path, units_active

COMMAND = 'station-connector-rotate-key'
BUSY_SECONDS = 10.0


def _replace_key(database, clock, busy_seconds):
    """In one transaction: a new key, and the undecided sign-ins gone. Past its sign-in, `pending_decide` checks no signature,
    so the delete is what ends one in progress. A decided row stays, since its code still exchanges. Returns what it found."""
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=busy_seconds,
                                     isolation_level=None)) as db:
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'system_meta' not in tables:
                raise ValueError(f'{database} holds no system_meta table, so it is no station store; nothing was changed')
            row = db.execute('SELECT value FROM system_meta WHERE key=?', (KEY_NAME,)).fetchone()
            key_was = 'absent' if row is None else 'good' if key_is_good(row[0]) else 'bad'
            db.execute('INSERT OR REPLACE INTO system_meta VALUES(?, ?)', (KEY_NAME, secrets.token_hex(32)))
            removed = (db.execute('DELETE FROM oauth_pending WHERE decided IS NULL').rowcount
                       if 'oauth_pending' in tables else 0)
            live = (db.execute("SELECT COUNT(*) FROM connector_grants WHERE revoked IS NULL AND ends > ? "
                               "AND typeof(ends) IN ('integer', 'real')", (clock(),)).fetchone()[0]
                    if 'connector_grants' in tables else 0)
            db.execute('COMMIT')
    except sqlite3.Error as error:
        raise ValueError(f'SQLite refused the rotation: {error}; nothing was changed') from None
    return dict(key_was=key_was, pending_removed=removed, live=live)


def rotate(data_dir, *, end_connections=False, active=None, clock=time.time, busy_seconds=BUSY_SECONDS):
    """Replace the key in the store in `data_dir`. By default it ends no connection: a client its person allowed is known by
    its stored row, and a leaked key yields no code or token. `end_connections` is for a person who thinks more than the key
    left. Returns key_was ('good', 'absent' or 'bad'), pending_removed, connections_kept and connections_ended."""
    database = _store_path(data_dir, COMMAND)
    running = (active or units_active)()
    if running:
        raise ValueError(f'Stop every station unit first; still running: {", ".join(running)}')
    with DispatchGate(Path(data_dir).absolute() / 'dispatch.lock'):
        found = _replace_key(database, clock, busy_seconds)
    ended = 0
    if end_connections and found['live']:
        from .db import Store                # only now: the key it reads at its start has just been made good
        store = Store(Path(data_dir), clock=clock)
        try:
            ended = store.end_every_connection('key_rotated')
        finally:
            store.close_keeper()
    return dict(key_was=found['key_was'], pending_removed=found['pending_removed'],
                connections_kept=0 if end_connections else found['live'], connections_ended=ended)


def report_lines(report, *, end_connections):
    lines = [{'good': 'The connector key was replaced.',
              'absent': 'The store had no connector key, so it has a new one.',
              'bad': "The store's connector key wasn't one, so it has a new one."}[report['key_was']],
             f'Pending sign-ins removed: {report["pending_removed"]}']
    if end_connections:
        return [*lines, f'Connections ended: {report["connections_ended"]}']
    return [*lines, f'{report["connections_kept"]} connections stay. If more than this key may have left, run it again '
                    'with --end-connections.']
