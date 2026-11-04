"""Station backups and the restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S2-S5, S7,
S14, S16). Trusted local commands, standard library only. station-backup never constructs Store and never takes the
dispatch gate: it reads the live file through a read-only connection, and SQLite's backup API copies a consistent
snapshot of committed data on its own (S2)."""
import calendar
from contextlib import closing, contextmanager, nullcontext
import datetime
import errno
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from .auth import account_role, token_hash
from .journal_mode import header_mode
from .ships import safe_line

STAMP = '%Y%m%dT%H%M%SZ'
COPY_NAME = re.compile(r'peer-(\d{8}T\d{6}Z)\.sqlite3')
TEMP_NAME = re.compile(r'\.peer-.+\.tmp(?:-journal|-wal|-shm)?')
KEEP_DAYS, KEEP_WEEKS = 14, 8
TEMP_MAX_AGE = 86400
STALE_AFTER = 36 * 3600
MIN_FREE = 1 << 30
RETRY_SECONDS = 60
SCRATCH_PREFIX = 'superyak-restore-test-'
START_WAIT, START_TRIES, STOP_WAIT = 60, 3, 10
SEE_LOG = 'see the log'
REASONS = {  # spec, Error handling: the words the CLI prints and the Ops line carries
    10: 'not enough disk space',
    11: "the copy failed its check; tomorrow's run tries again",
    12: "the live database may be damaged: don't restart or deploy before reading docs/station-restore.md",
    13: 'the copy off the Pi failed',
    20: 'there is no backup to test',
    21: 'the newest copy failed its check',
    22: 'the restored station did not start',
    23: 'the restored station is missing data',
    24: "the restore's reconcile step failed",
}


class BackupError(Exception):
    """A failure with its exit code (spec, Error handling). The CLI prints the reason and exits with the code."""
    def __init__(self, code, reason=None):
        self.code, self.reason = code, reason or REASONS.get(code, SEE_LOG)
        super().__init__(self.reason)


def default_backup_dir(data_dir):
    """S14: backups/station beside the data dir, so ~/.local/share/superyak/backups/station for the lighthouse."""
    return Path(data_dir).absolute().parent / 'backups' / 'station'


def copy_stamp(now):
    return time.strftime(STAMP, time.gmtime(now))


def copy_time(path):
    """A copy's UTC time, from its name."""
    return calendar.timegm(time.strptime(COPY_NAME.fullmatch(Path(path).name)[1], STAMP))


def _stamp_ok(name):
    """A name that matches COPY_NAME and holds a real UTC time; peer-20261399T000000Z.sqlite3 only looks like one. A
    stray one would otherwise sort newest: every backup would fail on the clock check and station-notices would crash."""
    try:
        time.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
    except (TypeError, ValueError):
        return False
    return True


def rotation(directory):
    """The copies with a final name, oldest first. Symlinks and every other name are never read, moved or pruned."""
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    return sorted((Path(entry.path) for entry in entries
                   if _stamp_ok(entry.name) and entry.is_file(follow_symlinks=False)), key=lambda path: path.name)


def newest_copy(directory):
    copies = rotation(directory)
    return copies[-1] if copies else None


def stale_notice(backup_dir, now):
    """S14: one notice while the newest copy is more than 36 hours old. Its id names that copy, so it changes as soon as
    a new copy appears; no rotation, or an empty one, gives none."""
    newest = newest_copy(backup_dir)
    if newest is None or now - copy_time(newest) <= STALE_AFTER:
        return None
    taken = time.strftime('%Y-%m-%d %H:%M', time.localtime(copy_time(newest)))
    return {'id': f'backup-stale-{newest.name}',
            'text': f'Station alert: the newest station backup is from {taken}, more than 36 hours ago. The nightly timer '
                    'may have stopped. On the Pi: systemctl --user list-timers superyak-backup.timer.'}


def keep(names):
    """S3: the newest copy of each of the 14 most recent UTC days that have a copy, and of each of the 8 most recent ISO
    weeks that have one. Only days and weeks with a copy count, so a Pi that was off never ages out its last copies."""
    days, weeks = {}, {}
    for name in sorted(names, reverse=True):
        when = datetime.datetime.strptime(COPY_NAME.fullmatch(name)[1], STAMP)
        days.setdefault(when.date(), name)
        weeks.setdefault(when.isocalendar()[:2], name)
    return ({days[day] for day in sorted(days, reverse=True)[:KEEP_DAYS]}
            | {weeks[week] for week in sorted(weeks, reverse=True)[:KEEP_WEEKS]})


def prune(directory, now):
    """S3, R3: run only once a new checked copy is in place. Deletes the copies S3 doesn't keep, and temporary files
    (.tmp and .tmp-journal) over a day old. Nothing else in the directory is touched. A file that can't be removed
    doesn't stop the rest: the failures come back as (name, error) pairs, empty when all went well."""
    failures = []
    if not os.path.isdir(directory):  # nothing there, nothing to prune; rotation() reads a missing folder as empty too
        return failures
    copies = rotation(directory)
    kept = keep([path.name for path in copies])
    for path in copies:
        if path.name not in kept:
            try:
                path.unlink()
            except OSError as error:
                failures.append((path.name, error))
    for entry in list(os.scandir(directory)):
        try:
            if (TEMP_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)
                    and now - entry.stat(follow_symlinks=False).st_mtime > TEMP_MAX_AGE):
                os.unlink(entry.path)
        except OSError as error:
            failures.append((entry.name, error))
    return failures


def _read_only(path):
    """S2: the URI is built as validate_demo builds it (__main__.py:125); a hand-built file: URI breaks on ?, # or %."""
    return sqlite3.connect(Path(path).absolute().as_uri() + '?mode=ro', uri=True, timeout=30)


def _check(db, pragma):
    """True when PRAGMA integrity_check or quick_check returns exactly one row, 'ok'. Raising counts as failing."""
    try:
        return [tuple(row) for row in db.execute(f'PRAGMA {pragma}')] == [('ok',)]
    except sqlite3.DatabaseError:
        return False


def _fsync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _live_database(data_dir):
    """S2: refuse a symlinked data dir or database, as Store._check_paths does, and a missing database."""
    data_dir = Path(data_dir).absolute()
    names = ('peer.sqlite3', 'peer.sqlite3-wal', 'peer.sqlite3-shm', 'peer.sqlite3-journal')
    if data_dir.is_symlink() or any((data_dir / name).is_symlink() for name in names):
        raise ValueError('Symlinked state is not allowed')
    database = data_dir / 'peer.sqlite3'
    if not database.is_file():
        raise ValueError(f'There is no station database at {database}')
    return database


def _rotation_dir(backup_dir):
    backup_dir = Path(backup_dir).absolute()
    if backup_dir.is_symlink():
        raise ValueError('A symlinked backup directory is not allowed')
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    return backup_dir


@contextmanager
def rotation_lock(directory):
    """S2: one run at a time. The restore test copies under it too, so pruning can't remove its file mid-copy (S7)."""
    fd = os.open(Path(directory) / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _remove_temporary(tmp):
    for path in (Path(tmp), Path(f'{tmp}-journal'), Path(f'{tmp}-wal'), Path(f'{tmp}-shm')):
        path.unlink(missing_ok=True)


def _as_single_file(copy):
    """Store-wal-mode D4: a copy is one self-contained rollback-mode file, whatever the live store's mode. The backup
    API copies the source's WAL flag; journal_mode=DELETE clears it, and SQLite's answer is checked."""
    answer = copy.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
    if answer != 'delete':
        raise BackupError(1, f'the copy could not be made a single file (journal_mode={answer})')


def free_bytes(path):
    return shutil.disk_usage(path).free


def _checked_copy(database, tmp, clock, sleep):
    """S2 steps 1-3 and S4: a new 0600 file, SQLite's backup API in one step from a read-only connection, then
    integrity_check. A busy database or a hot journal is retried for 60 s (S8: after a power cut the read-only open
    succeeds and the first read fails with SQLITE_READONLY_ROLLBACK). Every failure removes the file."""
    try:
        os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    except OSError as error:  # not removed: a file that already exists there isn't ours
        if error.errno == errno.ENOSPC:
            raise BackupError(10) from error
        raise
    try:
        deadline = clock() + RETRY_SECONDS
        while True:
            try:
                with closing(_read_only(database)) as source:
                    size = source.execute('PRAGMA page_count').fetchone()[0] * source.execute('PRAGMA page_size').fetchone()[0]
                    if free_bytes(tmp.parent) - size < MIN_FREE:  # S4: at least 1 GiB left after the copy
                        raise BackupError(10)
                    with closing(sqlite3.connect(tmp)) as copy:
                        source.backup(copy, pages=-1)
                        _as_single_file(copy)
                        sound = _check(copy, 'integrity_check')
                break
            except sqlite3.OperationalError as error:
                if getattr(error, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL:
                    raise BackupError(10) from error
                if clock() >= deadline:
                    raise BackupError(1, f'the station database could not be copied for {RETRY_SECONDS} s: {error}') from error
                sleep(1)
            except sqlite3.DatabaseError:
                sound = False  # a copy that raised is a copy that failed its check
                break
        if not sound:
            with closing(_read_only(database)) as live:  # S4: tell a bad copy from a damaged station
                raise BackupError(11 if _check(live, 'quick_check') else 12)
        _fsync(tmp)
    except OSError as error:
        _remove_temporary(tmp)
        if error.errno == errno.ENOSPC:
            raise BackupError(10) from error
        raise
    except BaseException:
        _remove_temporary(tmp)
        raise


def _publish(tmp, final):
    """S2 step 4: the rename, then the directory's fsync. A file with a final name is always a checked copy."""
    os.replace(tmp, final)
    _fsync(final.parent)


def _write_output(database, output, clock, sleep):
    """S2 --output FILE: one checked copy at a new path, outside the rotation. It publishes with os.link, so an existing
    FILE is never replaced, even one created after the check (R4)."""
    if os.path.lexists(output):
        raise BackupError(1, f'{output} exists; --output never replaces a file')
    tmp = output.parent / f'.peer-{copy_stamp(clock())}-{os.getpid()}.tmp'
    _checked_copy(database, tmp, clock, sleep)
    try:
        try:
            os.link(tmp, output)
        except FileExistsError as error:
            raise BackupError(1, f'{output} exists; --output never replaces a file') from error
        except OSError as error:
            raise BackupError(1, f'could not publish {output} with a hard link (does its filesystem support them?): {error}') from error
        try:
            _fsync(output.parent)
        except OSError as error:
            raise BackupError(1, f'the copy is in place ({output}), but syncing its folder failed: {error}') from error
    finally:
        _remove_temporary(tmp)
    return output


def _device(path):
    return os.stat(path).st_dev


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_off(final, target, backup_dir, now):
    """S5, 1.2's switch: the checked copy to a mounted directory on another disk, atomically at 0600, its sha256
    compared, and S3 applied there. A share that isn't mounted is the Pi's own disk, so it is refused rather than
    silently filled. Any failure is exit 13; the local copy stays, and the rotation is already pruned."""
    target = Path(target).absolute()
    tmp = target / f'.peer-{COPY_NAME.fullmatch(final.name)[1]}-{os.getpid()}.tmp'
    made = False
    try:
        if target.is_symlink() or not target.is_dir():
            raise ValueError(f'{target} is not a directory')
        if _device(target) == _device(backup_dir):
            raise ValueError(f"{target} is on the rotation's own disk; is the share mounted?")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        made = True
        with os.fdopen(fd, 'wb') as out, open(final, 'rb') as source:
            shutil.copyfileobj(source, out, 1 << 20)
            out.flush()
            os.fsync(out.fileno())
        if _sha256(tmp) != _sha256(final):
            raise ValueError('the copy off the Pi does not match the checked copy')
        os.replace(tmp, target / final.name)
        made = False
        _fsync(target)
        failures = prune(target, now)
        if failures:
            raise ValueError('pruning there could not remove: '
                             + '; '.join(f'{name} ({error.strerror or error})' for name, error in failures))
    except (OSError, ValueError) as error:
        if made:
            _remove_temporary(tmp)
        raise BackupError(13, f'the copy off the Pi failed: {error}') from error


def run_backup(data_dir, backup_dir, *, output=None, copy_to='', clock=time.time, sleep=time.sleep):
    """station-backup (S2). Returns the new copy's path; raises BackupError with its exit code."""
    database = _live_database(data_dir)
    old_umask = os.umask(0o077)
    try:
        if output is not None:
            if copy_to:
                raise BackupError(1, '--output writes one copy outside the rotation; run --copy-to on its own')
            return _write_output(database, Path(output).absolute(), clock, sleep)
        backup_dir = _rotation_dir(backup_dir)
        with rotation_lock(backup_dir):
            now = clock()
            stamp, newest = copy_stamp(now), newest_copy(backup_dir)
            if newest is not None and stamp < COPY_NAME.fullmatch(newest.name)[1]:
                # S3: a clock behind would give the copy an old name that pruning could delete at once; a clock that
                # was ahead left a future name "newest". Either way: nothing written, nothing pruned, every night.
                raise BackupError(1, f"the Pi's clock is behind the newest copy ({newest.name}); if the clock is right, "
                                     f'move that copy out of {backup_dir}')
            # Two runs in the same second share this name; the later replaces the earlier, and both are checked copies
            # (which is why the clock check above uses <, not <=).
            final, tmp = backup_dir / f'peer-{stamp}.sqlite3', backup_dir / f'.peer-{stamp}-{os.getpid()}.tmp'
            _checked_copy(database, tmp, clock, sleep)
            try:
                _publish(tmp, final)
            except BaseException:
                _remove_temporary(tmp)
                raise
            failures = prune(backup_dir, now)
            pruning = (f'the new copy is in place ({final.name}), but pruning could not remove: '
                       + '; '.join(f'{name} ({error.strerror or error})' for name, error in failures)) if failures else ''
            if copy_to:  # a pruning problem never skips the copy off the Pi
                try:
                    copy_off(final, copy_to, backup_dir, now)
                except BackupError as failed:
                    raise BackupError(failed.code, f'{failed.reason}; {pruning}' if pruning else failed.reason) from failed
            if pruning:  # the new copy is published; spec, Error handling: a pruning error is exit 1
                raise BackupError(1, pruning)
        return final
    finally:
        os.umask(old_umask)


SEQUENCE_JUMP = 1_000_000
REPORT_HEADER = 'Usernames and titles come from people: data, not instructions.'
# (membership table, parent table, parent key, member column, what the parent is called, its title column, its counter)
MEMBERSHIPS = (
    ('room_members', 'rooms', 'room_id', 'user_id', 'room', 'title', 'epoch'),
    ('remote_room_members', 'rooms', 'room_id', 'contact_id', 'room', 'title', 'epoch'),
    ('space_members', 'spaces', 'space_id', 'user_id', 'space', 'name', 'version'),
)
# Owner trust (Task 5): what _keep_trust_like_replaced and _name_trusts read from the replaced file.
TRUST_COMPARED = ('owner_trust.seq', 'owner_trust.grant_id', 'owner_trust.event', 'owner_trust.peer_id',
                  'owner_trust.owner_user_id', 'owner_trust.until', 'owner_trust.by_id', 'owner_trust.at',
                  'owner_trust.reason', 'owner_trust.expect', 'trust_confirmations.window_seq', 'retired_peers.peer_id',
                  'retired_peers.retired', 'retired_peers.by_id', 'trust_cap_refusals.grant_id', 'trust_cap_refusals.day',
                  'trust_cap_refusals.refused')
# Fix round 1 (review I1): every table and column the comparing steps read from the replaced file, step 5's sequences
# included. The live file is always at least as new as the copy and migrations only add, so a replaced file lacking
# one that the copy has is the wrong file or a damaged one.
COMPARED = ('users.id', 'users.is_admin', 'users.is_super_admin', 'users.salt', 'users.password_hash', 'ship_keys.id',
            'ship_keys.revoked', 'rooms.id', 'rooms.title', 'spaces.id', 'spaces.name',
            *(f'{table}.{column}' for table, _, key, member, *_ in MEMBERSHIPS for column in (key, member)),
            'breakouts.room_id', 'breakouts.closed', 'layers.id', 'layers.active_revision', 'layers.draft',
            'peers.peer_id', 'peers.paired', 'mentions', 'events',
            # spec A step 3, G13: what the grants steps read from the replaced file
            'grants.id', 'grants.revoked', 'grants.revoked_by', 'grants.revoke_reason', 'budget_uses.grant_id',
            'budget_uses.ticket_id', 'budget_uses.created',
            # room moderators, M20: the act log the member-changes step reads
            'member_changes.id', 'member_changes.grant_id', 'member_changes.change', 'member_changes.actor_id',
            'member_changes.room_id', 'member_changes.new_room_id', 'member_changes.created',
            # fix:restore-keeps-connector-revocations, the section 2's M1: a replaced file damaged in a connection column
            # is treated as absent, so every connection is revoked, never one left open as only "not compared"
            'connector_grants.id', 'connector_grants.person_id', 'connector_grants.client_id',
            'connector_grants.redirect_host', 'connector_grants.rooms', 'connector_grants.ends', 'connector_grants.revoked',
            'connector_tokens.hash', 'connector_tokens.expires', 'connector_tokens.used',  # Task 6's tokens, the same way
            # Task 8's read receipts: a replaced file lacking a column is absent, so the copy's stay and the loss is said
            'connector_reads.id', 'connector_reads.grant_id', 'connector_reads.person_id', 'connector_reads.app',
            'connector_reads.at', 'connector_reads.tool', 'connector_reads.rooms_read', 'connector_reads.rooms_refused',
            'connector_reads.size', 'connector_reads.outcome',
            # owner trust (spec item 7): a replaced file lacking one is absent, so every trust is revoked, never one whose
            # revocation or retirement it may have lost left live
            # lessons room adds (Task 1): who typed a code, whether the line was shown, a change's reason, the addable list
            'pairing_confirmations.typed_by', 'pairing_confirmations.lessons_line', 'member_changes.reason',
            'lessons_addable.contact_id', 'lessons_addable.code_digest', 'lessons_addable.typed_by', 'lessons_addable.listed',
            *TRUST_COMPARED)


class ReconcileRefused(ValueError):
    """S16: a FILE the reconcile won't touch. The CLI exits 1, and the file is unchanged."""


class UnpairRefused(ReconcileRefused):
    """--unpair named no peer, or more than one: the CLI exits 2, and the file is unchanged."""


def _has(db, *needs):
    """Each need is 'table' or 'table.column'."""
    for need in needs:
        table, _, column = need.partition('.')
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        if not columns or (column and column not in columns):
            return False
    return True


def _usable(db, old, report, *needs):
    """S16 'An older copy': a step whose table or column the staged copy lacks is skipped and named (migrations only
    add, so there is nothing there to take back); what the replaced file lacks is not compared. Neither is an error.
    A replaced file lacking anything in COMPARED is treated as absent before any step runs (fix round 1), so for the
    replaced file this is a backstop, reached only if a step reads something COMPARED doesn't list."""
    missing = [need for need in needs if not _has(db, need)]
    report['skipped'] += [need for need in missing if need not in report['skipped']]
    absent = [need for need in needs if old is not None and not missing and not _has(old, need)]
    report['not_compared'] += [need for need in absent if need not in report['not_compared']]
    return not missing and not absent


def _end_sessions(db, old, now, report):
    """Step 1: delete every session."""
    if _usable(db, None, report, 'sessions'):
        report['counts']['sessions deleted'] = db.execute('DELETE FROM sessions').rowcount


def _use_invitations(db, old, now, report):
    """Step 2: mark every unused invitation and account activation used."""
    for table, label in (('invitations', 'invitations marked used'), ('account_activations', 'account activations marked used')):
        if _usable(db, None, report, f'{table}.used'):
            report['counts'][label] = db.execute(f'UPDATE {table} SET used=1 WHERE used=0').rowcount


def _revoke_held_keys(db, old, now, report):
    """Step 3, dockings: a docking that still holds its plaintext key has that key revoked and is expired, as
    Ships._expire_uncollected does (ships.py:109-110)."""
    if not _usable(db, None, report, 'dockings.key', 'ship_keys.revoked'):
        return
    held = db.execute('SELECT id, ship_name, key FROM dockings WHERE key IS NOT NULL').fetchall()
    for row in held:
        if db.execute('UPDATE ship_keys SET revoked=? WHERE key_hash=? AND revoked IS NULL', (now, token_hash(row['key']))).rowcount:
            report['revoked'].append(row['ship_name'])
        db.execute("UPDATE dockings SET key=NULL,status='expired' WHERE id=?", (row['id'],))
    report['counts']['uncollected docking keys revoked'] = len(held)


def _clear_uncollected(db, old, now, report):
    """Step 3, requests: clear every access request's uncollected invitation token and share link."""
    for column, label in (('token', 'uncollected invitation tokens cleared'), ('share_url', 'uncollected share links cleared')):
        if _usable(db, None, report, f'access_requests.{column}'):
            report['counts'][label] = db.execute(f'UPDATE access_requests SET {column}=NULL WHERE {column} IS NOT NULL').rowcount


ENDED = 0.0  # an end written as a fixed past time: one written as now comes undone when the clock steps back


def _expire_waiting(db, old, now, report):
    """Step 4: every pending access request and waiting docking ends, so requesters ask again. All of them end at
    ENDED, not now, and so do the ones whose own lifetime ran out just before (the section 2 review's S1): a clock
    that steps back after the restore can make none approvable again. The report counts the ones still live."""
    for table, status, label in (('access_requests', 'pending', 'pending access requests expired'),
                                 ('dockings', 'waiting', 'waiting dockings expired')):
        if _usable(db, None, report, f'{table}.expires', f'{table}.status'):
            report['counts'][label] = db.execute(f'SELECT count(*) FROM {table} WHERE status=? AND expires>?', (status, now)).fetchone()[0]
            db.execute(f'UPDATE {table} SET expires=? WHERE status=? AND expires>?', (ENDED, status, ENDED))


IMPRINT_NEEDS = ('imprint_requests.id', 'imprint_requests.imprint_id', 'imprint_requests.status',
                 'imprint_requests.imprints_root', 'imprint_requests.ended_at', 'imprint_requests.delete_reason',
                 'imprint_receipts.id', 'imprint_receipts.request_id', 'imprint_receipts.record',
                 'imprint_receipts.signature')


def _tombstone_receipts(root, imprint_id):
    """The receipts a tombstone holds, or None when the root records none or no tombstone exists. A tombstone that
    cannot be read still counts: its existence is what stops a restore, so it returns an empty list."""
    if not root:
        return None
    path = Path(root) / 'tombstones' / f'{imprint_id}.json'
    if not os.path.lexists(path):
        return None
    try:
        held = json.loads(path.read_bytes())['receipts']
        return [r for r in held if isinstance(r, dict) and isinstance(r.get('record'), dict) and isinstance(r['record'].get('id'), str)]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _hold_imprints(db, old, now, report):
    """Step 6, imprints (D15): a withdrawn or deleted imprint never comes back from a backup. A row the copy still holds
    live closes to what the replaced file says (`deleting`, `deleted`, `declined` or `expired`), and to `deleted` when a
    tombstone exists under the root the row records. The receipts the copy lacks, the replaced file's and the
    tombstone's, are added so the reason is in the chain. The sweep removes any files and finishes a `deleting` row."""
    if not _usable(db, None, report, *IMPRINT_NEEDS):
        return
    comparing = old is not None and _has(old, *IMPRINT_NEEDS)
    held = 0
    rows = db.execute("SELECT id, imprint_id, imprints_root FROM imprint_requests "
                      "WHERE status NOT IN ('deleted', 'declined', 'expired')").fetchall()
    for row in rows:
        target, receipts, ended, reason = None, [], None, None
        if comparing:
            there = old.execute('SELECT status, ended_at, delete_reason FROM imprint_requests WHERE id=?', (row['id'],)).fetchone()
            if there is not None and there[0] in ('deleting', 'deleted', 'declined', 'expired'):
                target, ended, reason = there[0], there[1], there[2]
                receipts = [{'record': json.loads(r[0]), 'signature': r[1]} for r in old.execute(
                    'SELECT record, signature FROM imprint_receipts WHERE request_id=? ORDER BY seq', (row['id'],))]
        tombstoned = _tombstone_receipts(row['imprints_root'], row['imprint_id'])
        if tombstoned is not None:
            target = 'deleted'
            receipts += tombstoned
        if target is None:
            continue
        have = {r[0] for r in db.execute('SELECT id FROM imprint_receipts WHERE request_id=?', (row['id'],))}
        for receipt in receipts:
            if receipt['record']['id'] not in have:
                have.add(receipt['record']['id'])
                db.execute('INSERT INTO imprint_receipts(id, request_id, record, signature) VALUES(?,?,?,?)',
                           (receipt['record']['id'], row['id'], json.dumps(receipt['record'], sort_keys=True, separators=(',', ':'), ensure_ascii=False),
                            receipt.get('signature')))
        db.execute('UPDATE imprint_requests SET status=?, ended_at=COALESCE(?, ended_at, ?), delete_reason=COALESCE(?, delete_reason) '
                   'WHERE id=?', (target, ended, int(now), reason, row['id']))
        held += 1
    report['counts']['imprints kept deleted'] = held


def _sequence(db, table):
    row = db.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (table,)).fetchone() if _has(db, 'sqlite_sequence') else None
    return max(row[0] if row else 0, db.execute(f'SELECT COALESCE(MAX(rowid), 0) FROM "{table}"').fetchone()[0])


def _raise_sequences(db, old, now, report):
    """Step 5: no watcher's saved cursor may hide a new mention: each sequence becomes the replaced file's where that is
    higher, or 1,000,000 more without a usable replaced file (or one that lacks the table: fail closed)."""
    for table in ('mentions', 'events'):
        if not _usable(db, None, report, table):
            continue
        current = _sequence(db, table)
        target = max(current, _sequence(old, table)) if old is not None and _has(old, table) else current + SEQUENCE_JUMP
        if target > current and not db.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?', (target, table)).rowcount:
            db.execute('INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)', (table, target))
        report['sequences'][table] = (current, target)


def _revoke_owned_ship_keys(db, old, now, report):
    """Without a usable replaced file: every key of every ship that has an owner; those machines dock again. The
    station's own ships, which have no owner (Odo, Wormhole), keep their keys."""
    if not _usable(db, None, report, 'users.kind', 'users.owner_id', 'ship_keys.revoked'):
        return
    owned = "SELECT id FROM users WHERE kind='ship' AND owner_id IS NOT NULL"
    report['revoked'] += [row[0] for row in db.execute(
        f'SELECT DISTINCT users.username FROM ship_keys JOIN users ON users.id=ship_keys.ship_id '
        f'WHERE ship_keys.revoked IS NULL AND ship_keys.ship_id IN ({owned}) ORDER BY users.username')]
    report['counts']['ship keys revoked'] = db.execute(f'UPDATE ship_keys SET revoked=? WHERE revoked IS NULL AND ship_id IN ({owned})', (now,)).rowcount


def _revoke_like_replaced(db, old, now, report):
    """With a usable replaced file: every ship key revoked there is revoked here."""
    if not _usable(db, old, report, 'ship_keys.revoked'):
        return
    count = 0
    for key_id, revoked in old.execute('SELECT id, revoked FROM ship_keys WHERE revoked IS NOT NULL').fetchall():
        ship = db.execute('SELECT users.username FROM ship_keys JOIN users ON users.id=ship_keys.ship_id '
                          'WHERE ship_keys.id=? AND ship_keys.revoked IS NULL', (key_id,)).fetchone()
        if ship:
            db.execute('UPDATE ship_keys SET revoked=? WHERE id=?', (revoked, key_id))
            report['revoked'].append(ship[0])
            count += 1
    report['counts']['ship keys revoked as in the replaced file'] = count


GRANT_COMPARED = ('grants.id', 'grants.revoked', 'grants.revoked_by', 'grants.revoke_reason')
GRANT_NAMED = ('grants.issuer_id', 'grants.grantee_id', 'grants.created')  # read from the copy only, for the report


def _grant_line(db, row, how):
    """G13: how the report names a revoked grant: its short id, its issuer's and grantee's usernames, and why."""
    def username(user_id):
        found = db.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
        return found[0] if found else user_id[:6]
    return ('#' + row['id'][:4], username(row['issuer_id']), username(row['grantee_id']), how)


def _revoke_every_grant(db, old, now, report):
    """G13, without a usable replaced file: every grant not yet revoked is revoked now, with reason `restored` and no
    person. The station signs each of these revocations at its next start (signatures.py): the reconcile works on a
    staged file and holds no key."""
    if not _usable(db, None, report, *GRANT_COMPARED, *GRANT_NAMED):
        return
    for row in db.execute('SELECT id, issuer_id, grantee_id FROM grants WHERE revoked IS NULL ORDER BY created, id').fetchall():
        db.execute("UPDATE grants SET revoked=?, revoked_by=NULL, revoke_reason='restored' WHERE id=?", (now, row['id']))
        report['grants'].append(_grant_line(db, row, 'no usable replaced file'))
    report['counts']['grants revoked'] = len(report['grants'])


def _revoke_grants_like_replaced(db, old, now, report):
    """G13, with a usable replaced file: a grant revoked there is revoked here with the same time, person and reason; a
    grant the replaced file lacks is revoked now with reason `restored` and no person (grants are never deleted, so a
    missing one means damage). Signed at the station's next start, as above."""
    if not (_usable(db, old, report, *GRANT_COMPARED) and _usable(db, None, report, *GRANT_NAMED)):
        return
    there = {row[0]: row[1:] for row in old.execute('SELECT id, revoked, revoked_by, revoke_reason FROM grants')}
    for row in db.execute('SELECT id, issuer_id, grantee_id FROM grants WHERE revoked IS NULL ORDER BY created, id').fetchall():
        if row['id'] not in there:
            values, how = (now, None, 'restored'), 'missing from the replaced file'
        elif there[row['id']][0] is not None:
            values, how = there[row['id']], 'as in the replaced file'
        else:
            continue
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?', (*values, row['id']))
        report['grants'].append(_grant_line(db, row, how))
    report['counts']['grants revoked'] = len(report['grants'])


def _add_budget_uses_like_replaced(db, old, now, report):
    """G13: each budget use recorded there, for a grant in both files, is added here unless one with its (grant_id,
    ticket_id) is here already, so a grant's spent budget comes back and a second run adds none."""
    if not _usable(db, old, report, 'grants.id', 'budget_uses.grant_id', 'budget_uses.ticket_id', 'budget_uses.created'):
        return
    both = {row[0] for row in db.execute('SELECT id FROM grants')} & {row[0] for row in old.execute('SELECT id FROM grants')}
    here = {(row[0], row[1]) for row in db.execute('SELECT grant_id, ticket_id FROM budget_uses')}
    added = 0
    for grant_id, ticket_id, created in old.execute('SELECT grant_id, ticket_id, created FROM budget_uses ORDER BY created').fetchall():
        if grant_id in both and (grant_id, ticket_id) not in here:
            db.execute('INSERT INTO budget_uses(grant_id, ticket_id, created) VALUES(?, ?, ?)', (grant_id, ticket_id, created))
            here.add((grant_id, ticket_id))
            added += 1
    report['counts']['budget uses added'] = added


def _add_member_changes_like_replaced(db, old, now, report):
    """M20, G13: each row of the replaced file's act log that this file lacks is copied here, in the replaced file's
    `created, rowid` order, when its grant (if any) is in both files and its room, new room and actor (if any) are here,
    so a moderator's budget and the owner's removals survive and a second run adds none. A row with no grant is copied
    only when it is a removal (Ruling 15 only takes power away); so only removals carry a day's budget across a restore."""
    if not _usable(db, old, report, 'grants.id', 'rooms.id', 'users.id', 'member_changes.id', 'member_changes.grant_id', 'member_changes.change',
                   'member_changes.actor_id', 'member_changes.room_id', 'member_changes.new_room_id', 'member_changes.created'):
        return
    if _has(old, 'member_changes.reason') and not _has(db, 'member_changes.reason'):
        # A copy from before lessons room adds gains the column (as the store's migration adds it) before the carry, so
        # a hold's removal keeps its 'held' and never reads as the owner's own (_owner_removed: no actor, no grant).
        db.execute('ALTER TABLE member_changes ADD COLUMN reason TEXT')
    have = {row[0] for row in db.execute('SELECT id FROM member_changes')}
    grants = {row[0] for row in db.execute('SELECT id FROM grants')} & {row[0] for row in old.execute('SELECT id FROM grants')}
    rooms = {row[0] for row in db.execute('SELECT id FROM rooms')}
    users = {row[0] for row in db.execute('SELECT id FROM users')}
    columns = [row[1] for row in old.execute('PRAGMA table_info(member_changes)')]
    here = {row[1] for row in db.execute('PRAGMA table_info(member_changes)')}
    columns = [name for name in columns if name in here]
    names = ','.join(f'"{name}"' for name in columns)
    added = 0
    for row in old.execute(f'SELECT {names} FROM member_changes ORDER BY created, rowid').fetchall():
        values = dict(zip(columns, row))
        if (values['id'] in have or (values['grant_id'] is not None and values['grant_id'] not in grants)
                or (values['grant_id'] is None and values['change'] != 'remove')
                or values['room_id'] not in rooms or (values['new_room_id'] is not None and values['new_room_id'] not in rooms)
                or (values['actor_id'] is not None and values['actor_id'] not in users)):
            continue
        db.execute(f'INSERT INTO member_changes({names}) VALUES({",".join("?" * len(columns))})', row)
        have.add(values['id'])
        added += 1
    report['counts']['member changes added'] = added


# Owner trust (Task 6): the report names a remote contact as every display does, by contact_labels' label, so a ship
# reads "ship of <owner>: <name>". A file from before owner trust has no view and no trust confirmation either (one
# schema batch makes both), so each of its contacts is a person, whose name is its label. The tables are checked before
# the view, whose columns can't be read without them.
LABELLED = 'SELECT c.id, c.peer_id, c.user_id, l.label FROM remote_contacts c JOIN contact_labels l ON l.id=c.id'
UNLABELLED = 'SELECT id, peer_id, user_id, name AS label FROM remote_contacts'


def _labelled(db):
    """The file's remote contacts, as (id, peer_id, user_id, label) rows to select from."""
    return LABELLED if _has(db, 'trust_confirmations.contact_id', 'owner_trust.grant_id', 'contact_labels') else UNLABELLED


def _member_name(db, table, member):
    if table == 'remote_room_members':
        row = db.execute(f'SELECT label FROM ({_labelled(db)}) WHERE id=?', (member,)).fetchone() \
            if _has(db, 'remote_contacts.name') else None
        return f'remote contact {row[0]}' if row else f'remote contact {member[:6]}'
    row = db.execute('SELECT username FROM users WHERE id=?', (member,)).fetchone()
    return row[0] if row else member[:6]


def _remove_members_like_replaced(db, old, now, report):
    """With a usable replaced file: for rooms and spaces in both files, each room, remote-room or space membership that
    isn't there is removed here (Wormhole included, so a room Andy unbridged stays unbridged). A room or space that loses
    a member has its epoch or version raised once, as remove_participant and change_space_member do, so a delivery
    queued under the old epoch is refused."""
    raised = set()
    for table, parent, key, member, kind, title, counter in MEMBERSHIPS:
        if not _usable(db, old, report, table, f'{parent}.{title}'):
            continue
        both = ({row[0] for row in db.execute(f'SELECT id FROM {parent}')}
                & {row[0] for row in old.execute(f'SELECT id FROM {parent}')})
        there = set(old.execute(f'SELECT {key}, {member} FROM {table}').fetchall())
        for place, who in db.execute(f'SELECT {key}, {member} FROM {table} ORDER BY {key}, {member}').fetchall():
            if place in both and (place, who) not in there:
                db.execute(f'DELETE FROM {table} WHERE {key}=? AND {member}=?', (place, who))
                if (parent, place) not in raised and _has(db, f'{parent}.{counter}'):
                    db.execute(f'UPDATE {parent} SET {counter}={counter}+1 WHERE id=?', (place,))
                    raised.add((parent, place))
                name = db.execute(f'SELECT {title} FROM {parent} WHERE id=?', (place,)).fetchone()[0]
                report['removed'].append((_member_name(db, table, who), kind, place[:6], name))


def _lower_roles_like_replaced(db, old, now, report):
    """With a usable replaced file: is_admin and is_super_admin come down to the replaced file's value where that is
    lower. Never up. When that leaves no active super admin, the report says so. Each account lowered is recorded as the
    station records a role change (auth.py change_account_role): its role_version goes up, to one past the higher of the
    two files' (so a tab holding a version either file issued is refused), and one account_role_changes row names the old
    and new role, with the system author as actor (the account itself in a copy that has none). A copy lacking either
    column or table still has its roles lowered, and the report names what it skipped."""
    wanted = {}
    for column in ('is_admin', 'is_super_admin'):
        if not _usable(db, old, report, f'users.{column}'):
            continue
        there = dict(old.execute(f'SELECT id, {column} FROM users').fetchall())
        for row in db.execute(f'SELECT id, {column} FROM users ORDER BY username').fetchall():
            if row['id'] in there and there[row['id']] < row[column]:
                wanted.setdefault(row['id'], {})[column] = there[row['id']]
    trace = _usable(db, None, report, 'users.role_version', 'users.is_admin', 'users.is_super_admin', 'account_role_changes')
    versions = dict(old.execute('SELECT id, role_version FROM users').fetchall()) if _has(old, 'users.role_version') else {}
    system = db.execute("SELECT value FROM system_meta WHERE key='system_author'").fetchone() if _has(db, 'system_meta.value') else None
    system = system[0] if system and db.execute('SELECT 1 FROM users WHERE id=?', (system[0],)).fetchone() else None
    lowered_super = False
    for user_id, columns in wanted.items():
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        for column, value in columns.items():
            db.execute(f'UPDATE users SET {column}=? WHERE id=?', (value, user_id))
        lowered_super = lowered_super or 'is_super_admin' in columns
        report['lowered'].append(user['username'])
        if trace:
            version = max(user['role_version'] or 0, versions.get(user_id) or 0) + 1
            after = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            db.execute('UPDATE users SET role_version=? WHERE id=?', (version, user_id))
            db.execute('INSERT INTO account_role_changes(user_id,actor_id,old_role,new_role,role_version,created) VALUES(?,?,?,?,?,?)',
                       (user_id, system or user_id, account_role(user), account_role(after), version, now))
    report['lowered'].sort()
    if lowered_super and _has(db, 'users.activation_pending'):
        report['no_super_admin'] = db.execute('SELECT 1 FROM users WHERE is_super_admin=1 AND activation_pending=0').fetchone() is None


def _close_breakouts_like_replaced(db, old, now, report):
    """With a usable replaced file (Rio Grande's ruling on the plan review's Q1): a breakout closed there and still open
    here is closed here, at the same time, so its members can't post or record mentions in it again. Its deferrals are
    dropped too, as Breakouts._close_breakout drops them (breakouts.py), so no session stays deferred for a mention
    nobody can answer now."""
    if not _usable(db, old, report, 'breakouts.closed', 'rooms.title'):
        return
    deferrals = _usable(db, None, report, 'deferrals.message_id', 'messages.room_id')
    for room_id, closed in old.execute('SELECT room_id, closed FROM breakouts WHERE closed IS NOT NULL ORDER BY room_id').fetchall():
        if db.execute('UPDATE breakouts SET closed=? WHERE room_id=? AND closed IS NULL', (closed, room_id)).rowcount:
            if deferrals:
                db.execute('DELETE FROM deferrals WHERE message_id IN (SELECT id FROM messages WHERE room_id=?)', (room_id,))
            title = db.execute('SELECT title FROM rooms WHERE id=?', (room_id,)).fetchone()
            report['closed'].append((room_id[:6], title[0] if title else ''))


PEER_NEEDS = ('peers.paired', 'remote_contacts.peer_id', 'remote_contacts.name', 'outbox.status', 'outbox.contact_id',
              'inbox.origin', 'inbox.payload')


def _shown(db, old, peer):
    """Follow-up 5: how a report line names a peer. The 12-character short id, unless another peer of the copy or the
    replaced file shares it, when UNPAIR= would refuse the short id: then the full id."""
    ids = set()
    for connection in (db, old):
        if connection is not None and _has(connection, 'peers.peer_id'):
            ids |= {row[0] for row in connection.execute('SELECT peer_id FROM peers')}
    return peer if sum(other[:12] == peer[:12] for other in ids | {peer}) > 1 else peer[:12]


def _unpair(db, old, peer, now, report):
    """Exactly Federation.unpair on the staged copy: every contact of the peer held and its confirmation gone, so
    pairing one participant again reconnects that one only (fix:pairing-code, review SF3); paired=0, that peer's
    contacts' pending and failed outbox rows withdrawn (delivered and sent rows stay), its inbox payloads nulled. A
    copy from before contact holds gains the table here, so the hold isn't lost on restore. Its trust-made members leave
    the lessons room (drop_held_from_lessons), read before their codes go; for a retired peer (a retirement
    _keep_retirements keeps is a retire) every contact of it does."""
    from .lessons import drop_held_from_lessons
    names = [row[0] for row in db.execute(f'SELECT label FROM ({_labelled(db)}) WHERE peer_id=? ORDER BY label', (peer,))]
    db.execute('CREATE TABLE IF NOT EXISTS contact_holds(contact_id TEXT PRIMARY KEY, held REAL NOT NULL)')
    held = now  # the restore's one time, so every hold of a restore shares one `created` and posts one notice
    db.execute('INSERT OR REPLACE INTO contact_holds SELECT id, ? FROM remote_contacts WHERE peer_id=?', (held, peer))
    retired = _has(db, 'retired_peers.peer_id') and db.execute('SELECT 1 FROM retired_peers WHERE peer_id=?', (peer,)).fetchone()
    drop_held_from_lessons(db, [row[0] for row in db.execute('SELECT id FROM remote_contacts WHERE peer_id=?', (peer,))],
                           held, every_contact=bool(retired))
    if _has(db, 'pairing_confirmations.contact_id'):
        db.execute('DELETE FROM pairing_confirmations WHERE contact_id IN (SELECT id FROM remote_contacts WHERE peer_id=?)',
                   (peer,))
    db.execute('UPDATE peers SET paired=0 WHERE peer_id=?', (peer,))
    withdrawn = db.execute("UPDATE outbox SET status='withdrawn' WHERE contact_id IN "
                           "(SELECT id FROM remote_contacts WHERE peer_id=?) AND status IN ('pending','failed')", (peer,)).rowcount
    nulled = db.execute('UPDATE inbox SET payload=NULL WHERE origin=? AND payload IS NOT NULL', (peer,)).rowcount
    report['unpaired'].append((_shown(db, old, peer), names))
    report['unpaired_full'].append(peer)
    report['unpaired_counts'] = [sum(pair) for pair in zip(report['unpaired_counts'], (withdrawn, nulled))]


def _unpair_like_replaced(db, old, now, report):
    """With a usable replaced file (revision 4, Task 11 review C1): a peer paired here whose row there has paired=0 is
    unpaired here. A peer the replaced file lacks is not (a damaged file must not cut off a peer it merely doesn't
    list); it is reported. 'Check delivery now' and /federation/events work on any paired peer, so leaving the pairing
    would be a real window. Only takes away."""
    if not _usable(db, old, report, *PEER_NEEDS):
        return
    there = dict(old.execute('SELECT peer_id, paired FROM peers').fetchall())
    for peer, paired in db.execute('SELECT peer_id, paired FROM peers ORDER BY peer_id').fetchall():
        if paired and peer in there and not there[peer]:
            _unpair(db, old, peer, now, report)


def _hold_like_replaced(db, old, now, report):
    """fix:pairing-code, Serenity's review MF1: a contact held in the replaced file is held here too, when the copy has it.
    Copying the older copy's holds as they are would replace the newer live ones: cut a peer off, pair one participant
    again, restore an older copy, and every sibling would be active again with no code typed. So each is held as
    Federation.unpair holds it: its confirmation gone, its pending and failed outbox rows withdrawn, and the received
    payloads it authored cleared, and, a trust-made member of the lessons room, out of its chain (drop_held_from_lessons,
    read before its confirmation goes). It runs after _unpair_like_replaced, whose peers are already held whole. A
    replaced file from before holds has none to compare. Only takes away."""
    from .lessons import drop_held_from_lessons
    if not _usable(db, old, report, *PEER_NEEDS, 'remote_contacts.user_id', 'inbox.actor') \
            or not _has(old, 'contact_holds.contact_id'):
        return
    held_there = {row[0] for row in old.execute('SELECT contact_id FROM contact_holds')}
    db.execute('CREATE TABLE IF NOT EXISTS contact_holds(contact_id TEXT PRIMARY KEY, held REAL NOT NULL)')
    held_here = {row[0] for row in db.execute('SELECT contact_id FROM contact_holds')}
    for contact in db.execute(f'SELECT id, peer_id, user_id, label FROM ({_labelled(db)}) ORDER BY peer_id, label, id').fetchall():
        if contact['id'] not in held_there or contact['id'] in held_here:
            continue
        db.execute('INSERT INTO contact_holds VALUES(?, ?)', (contact['id'], now))
        drop_held_from_lessons(db, [contact['id']], now)
        if _has(db, 'pairing_confirmations.contact_id'):
            db.execute('DELETE FROM pairing_confirmations WHERE contact_id=?', (contact['id'],))
        withdrawn = db.execute("UPDATE outbox SET status='withdrawn' WHERE contact_id=? AND status IN ('pending','failed')",
                               (contact['id'],)).rowcount
        nulled = db.execute('UPDATE inbox SET payload=NULL WHERE origin=? AND actor=? AND payload IS NOT NULL',
                            (contact['peer_id'], contact['user_id'])).rowcount
        report['held'].append((_shown(db, old, contact['peer_id']), contact['label']))
        report['held_counts'] = [sum(pair) for pair in zip(report['held_counts'], (withdrawn, nulled))]


# Owner trust (Task 5; spec items 4a, 6 and 7): a restore never brings back a revoked trust, a retirement or a paused
# trust. owner_trust and trust_confirmations are append-only, so the copy's rows are the replaced file's first ones, and
# what the replaced file has more happened since the copy.
TRUST_RETIREMENTS_NOT_KEPT = ('Peers retired since the copy were not kept: unpair them as retired again before anything '
                              'pairs.')
TRUSTS_RESTORED = ('Every owner trust was revoked as restored: grant each machine its trust again in the browser (one '
                   'password click each, with its expected count); then each held ship pairs again from a fresh '
                   'export-ship.')
UNREVOKED_TRUSTS = ("SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE event='grant' AND grant_id NOT IN "
                    "(SELECT grant_id FROM owner_trust WHERE event='revoke') ORDER BY seq")
WINDOWS = "SELECT grant_id, event, until, at, expect FROM owner_trust WHERE event IN ('grant','renew')"
# owner_trust.trust_window's rule, on either file (the replaced file's connection gives tuples): each grant's latest
# grant-or-renewal row, its window, as (seq, event, until, at, expect), and how many trust_confirmations rows name it.
LATEST_WINDOWS = ("SELECT w.grant_id, w.seq, w.event, w.until, w.at, w.expect, (SELECT COUNT(*) FROM trust_confirmations "
                  "WHERE window_seq=w.seq) FROM owner_trust w WHERE w.seq=(SELECT MAX(seq) FROM owner_trust WHERE "
                  "grant_id=w.grant_id AND event IN ('grant','renew'))")


def _windows(connection):
    """{grant_id: (window row, its count)}; a trust is paused when the count reached the row's expect (row[4])."""
    return {row[0]: (tuple(row[1:6]), row[6]) for row in connection.execute(LATEST_WINDOWS)}


def _paused_whole(here, there, grant_id):
    """Spec item 4a, Restore (the Task 5 review's ruling): None when the trust isn't paused in the replaced file; else
    whether the copy holds that paused window whole, its very row with as many pairings. A count never passes its
    expect, so then nothing was lost since the copy: the trust is paused here too. A NULL expect, which the table's
    CHECK forbids so only damage writes, reads as paused there, failing closed."""
    if grant_id not in there or (there[grant_id][0][4] is not None and there[grant_id][1] < there[grant_id][0][4]):
        return None
    return grant_id in here and here[grant_id][0] == there[grant_id][0] and here[grant_id][1] >= there[grant_id][1]


def _trust_tables(db, old):
    """Whether the copy has the owner trust tables, after making them when it lacks them and a usable replaced file has
    them (its revocations and retirements are then copied in). With neither, there is no trust, and the station's start
    makes the tables; made here, they would be ones the copy has and the replaced file lacks, so a second run (runbook
    step 5's UNPAIR=) would treat the replaced file as absent (COMPARED) and take back everything. They are made one
    statement at a time, since executescript would commit the reconcile's transaction (as for room_cloud below), and
    imported here, not at the top, as room_cloud is: owner_trust reaches identity and its cryptography."""
    if not _has(db, 'owner_trust') and (old is None or not _has(old, *TRUST_COMPARED)):
        return False
    from .owner_trust import OWNER_TRUST_STATEMENTS
    for statement in OWNER_TRUST_STATEMENTS:
        db.execute(statement)
    return True


def _revoke_trust(db, grant, by_id, at, reason):
    """A revocation row for the grant (grant_id, peer_id, owner_user_id), its seq left to SQLite: owner_trust is
    append-only, and its triggers refuse a row that names a seq already used."""
    db.execute("INSERT INTO owner_trust(grant_id,event,peer_id,owner_user_id,until,by_id,at,reason) "
               "VALUES (?,'revoke',?,?,NULL,?,?,?)", (grant[0], grant[1], grant[2], by_id, at, reason))


def _trust_line(db, old, grant, how):
    """How the report names an owner trust: its grant's short id (6 characters), its owner's name as the copy has the
    contact, else as the replaced file has it, and what happened to it."""
    for connection in (db, old):
        if connection is not None and _has(connection, 'remote_contacts.name', 'remote_contacts.user_id'):
            row = connection.execute(f'SELECT label FROM ({_labelled(connection)}) WHERE peer_id=? AND user_id=?',
                                     (grant[1], grant[2])).fetchone()
            if row:
                return (grant[0][:6], row[0], how)
    return (grant[0][:6], 'an unknown owner', how)


def _revoke_every_trust(db, old, now, report):
    """Spec item 7, without a usable replaced file: the revocations and retirements since the copy can't be known, so
    every trust not yet revoked, an expired one too, is revoked now with reason `restored` and no person, and
    _settle_trust holds its ships. The report says so, that each machine is granted again (TRUSTS_RESTORED), and that
    retirements since the copy are gone (TRUST_RETIREMENTS_NOT_KEPT). A copy from before owner trust has none."""
    if not _trust_tables(db, old):
        return
    for grant in db.execute(UNREVOKED_TRUSTS).fetchall():
        _revoke_trust(db, grant, None, now, 'restored')
        report['trusts'].append(_trust_line(db, old, grant, 'revoked: no usable replaced file'))


def _keep_trust_like_replaced(db, old, now, report):
    """Spec items 4a, 6 and 7, with a usable replaced file; it only takes power away. Each trust the copy has unrevoked
    is revoked here when the replaced file revoked it (with that revocation's time, person and reason); when the
    replaced file lacks one of its grant or renewal rows (rows are never deleted, so that is damage; reason `restored`);
    or when it is paused there and the copy doesn't hold that window whole (the pairings that paused it are lost with
    the copy, so it would come back live with its notice posted; reason `paused at restore`). One paused in both with
    nothing lost is paused here too, and _name_trusts names it. Each retirement there that the copy lacks is added,
    and its peer unpaired as Federation.unpair does when the copy has it paired. The
    owner_trust sequence is first raised to the replaced file's, so no row written from now on takes a seq it used: a
    pause notice's id names its window's seq, and one posted for a window lost with the copy must not stand for a new
    one. _settle_trust then holds the ships. A replaced file lacking these tables, when the copy has them, was treated
    as absent (COMPARED); when the copy lacks them too there is nothing to keep, and no table is made."""
    if not _has(old, *TRUST_COMPARED):
        return
    _trust_tables(db, old)
    used = _sequence(old, 'owner_trust')
    if used > _sequence(db, 'owner_trust') and not db.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name='owner_trust'", (used,)).rowcount:
        db.execute("INSERT INTO sqlite_sequence(name, seq) VALUES('owner_trust', ?)", (used,))
    there = set(old.execute(WINDOWS).fetchall())
    missing = {row[0] for row in db.execute(WINDOWS) if tuple(row) not in there}
    revoked_there = {}
    for grant_id, by_id, at, reason in old.execute("SELECT grant_id, by_id, at, reason FROM owner_trust "
                                                   "WHERE event='revoke' ORDER BY seq").fetchall():
        revoked_there.setdefault(grant_id, (by_id, at, reason))
    here, there = _windows(db), _windows(old)
    for grant in db.execute(UNREVOKED_TRUSTS).fetchall():
        if grant['grant_id'] in revoked_there:
            values, how = revoked_there[grant['grant_id']], 'revoked as in the replaced file'
        elif grant['grant_id'] in missing:
            values, how = (None, now, 'restored'), 'revoked: missing from the replaced file'
        elif _paused_whole(here, there, grant['grant_id']) is False:
            values, how = (None, now, 'paused at restore'), 'revoked: paused in the replaced file; ' + PAUSE_LOST
        else:
            continue
        _revoke_trust(db, grant, *values)
        report['trusts'].append(_trust_line(db, old, grant, how))
    _keep_retirements(db, old, now, report)


# The pause notice's own advice (owner_trust.PAUSE_TEXT), for a pause whose alarm the restore has lost
PAUSE_LOST = "its pairings since the copy are lost; if you didn't expect them, unpair that peer as retired before granting again"
RETIRED_NEEDS = ('retired_peers.peer_id', 'retired_peers.retired', 'retired_peers.by_id')


def _keep_retirements(db, old, now, report):
    """Each retirement in the replaced file that the copy lacks is added, and its peer unpaired as Federation.unpair does
    when the copy has it paired. Reached with a usable replaced file, and also (Task 5's parked item) with one treated as
    absent because it lacks some other trust table, so a retirement it holds is never silently lost: retired_peers is
    append-only, and a peer once retired must never pair again."""
    if not _has(old, *RETIRED_NEEDS):
        return
    report['retirements_kept'] = True
    if not _has(db, 'retired_peers'):
        from .owner_trust import OWNER_TRUST_STATEMENTS
        for statement in OWNER_TRUST_STATEMENTS:
            if 'TABLE IF NOT EXISTS retired_peers' in statement:
                db.execute(statement)
    kept = 0
    for peer, retired, by_id in old.execute('SELECT peer_id, retired, by_id FROM retired_peers '
                                            'ORDER BY retired, peer_id').fetchall():
        if not db.execute('INSERT OR IGNORE INTO retired_peers(peer_id, retired, by_id) VALUES (?,?,?)',
                          (peer, retired, by_id)).rowcount:
            continue
        kept += 1
        if _has(db, *PEER_NEEDS) and peer not in report['unpaired_full'] \
                and db.execute('SELECT 1 FROM peers WHERE peer_id=? AND paired', (peer,)).fetchone():
            _unpair(db, old, peer, now, report)
    report['counts']['peer retirements kept'] = kept


def _name_trusts(db, old, report):
    """Spec item 4a, Restore, last of the owner trust steps (after both settles), with a usable replaced file; it only
    reports. Of the trusts revoked neither there nor here, it names each whose grant or renewal row there is missing
    here (lost with the copy, so it comes back shorter, or paused again under a window whose notice has posted, failing
    closed but silently), saying when a lost grant had paused there; and each paused in both with nothing lost, for the
    admin to check its ships. Then, revoked or not, each trust refused at the cap more often there than here: a burst
    at the cap is a sign of a compromised host, which the restore would otherwise erase."""
    if old is None or not _has(old, *TRUST_COMPARED) or not _has(db, 'owner_trust'):
        return
    rows_here = {tuple(row) for row in db.execute(WINDOWS)}
    granted = {row[0] for row in rows_here if row[1] == 'grant'}
    revoked = {row[0] for connection in (db, old)
               for row in connection.execute("SELECT grant_id FROM owner_trust WHERE event='revoke'")}
    here, there = _windows(db), _windows(old)
    grants = {row[0]: row for row in old.execute("SELECT grant_id, peer_id, owner_user_id FROM owner_trust "
                                                 "WHERE event='grant' ORDER BY seq").fetchall()}
    named = {}
    for row in old.execute(f'{WINDOWS} ORDER BY seq').fetchall():
        grant_id = row[0]
        if grant_id in revoked or grant_id in named or row in rows_here:
            continue
        if grant_id in granted:
            named[grant_id] = 'renewed since the copy, and the renewal was lost: renew it again'
        else:
            named[grant_id] = 'granted since the copy, and the grant was lost: grant it again'
            if _paused_whole(here, there, grant_id) is not None:
                named[grant_id] += f'; it had paused there after {there[grant_id][1]} pairings, and ' + PAUSE_LOST
    lines = list(named.items())
    lines += [(grant_id, 'paused, as in the replaced file: check its ships, then renew or revoke') for grant_id in grants
              if grant_id not in revoked and grant_id not in named and _paused_whole(here, there, grant_id)]
    refused_here = {(row[0], row[1]): row[2] for row in db.execute('SELECT grant_id, day, refused FROM trust_cap_refusals')}
    refused = {}
    for grant_id, day, count in old.execute('SELECT grant_id, day, refused FROM trust_cap_refusals ORDER BY grant_id, day'):
        refused[grant_id] = refused.get(grant_id, 0) + max(0, count - refused_here.get((grant_id, day), 0))
    lines += [(grant_id, f'refused at the cap since the copy: {count}') for grant_id, count in refused.items() if count]
    report['trusts'] += [_trust_line(db, old, grants.get(grant_id, (grant_id, None, None)), how) for grant_id, how in lines]


def _settle_trust(db, old, now, report):
    """With or without a replaced file, after both lists and again after _unpair_named (it is idempotent):
    settle_owner_trust ends each trust whose owner a step held, unpaired or retired, UNPAIR= included (reason `owner
    held`, so every hold of an owner has a date, S10 and N13), and holds every ship of a trust ended, as a revoke holds
    them (spec items 6 and 7). A copy without the trust tables has no trust; one without contact holds is from before
    owner trust, so its trust tables were made just now from the replaced file and hold no trust to settle."""
    from .owner_trust import settle_owner_trust
    if not _trust_tables(db, old):
        return
    if _has(db, 'remote_contacts.user_id', 'contact_holds.contact_id'):
        held = db.execute('SELECT COUNT(*) FROM contact_holds').fetchone()[0]
        for grant_id in settle_owner_trust(db, now):
            grant = db.execute("SELECT grant_id, peer_id, owner_user_id FROM owner_trust WHERE grant_id=? AND event='grant'",
                               (grant_id,)).fetchone()
            report['trusts'].append(_trust_line(db, old, grant, 'revoked: its owner is held'))
        label = 'ships held as their owner trust ended'
        report['counts'][label] = report['counts'].get(label, 0) + db.execute(
            'SELECT COUNT(*) FROM contact_holds').fetchone()[0] - held
    report['counts']['owner trusts revoked'] = sum(how.startswith('revoked') for *_, how in report['trusts'])


MARKS_NOT_KEPT = ('Marks set since the copy to keep rooms away from cloud models were not kept: ask the members of the '
                  'rooms that matter to check their marks before any ship is added.')


def _keep_marks_like_replaced(db, old, now, report):
    """Never to a cloud model (Rio Grande's section 2 of room-cloud, M2): a mark is a restriction, like a hold, so every
    mark the replaced file holds is kept here, for a room and member this copy has, with its set_at. Otherwise a mark
    made after the copy would be lost, and its room could take a ship; one cleared after the copy stays, failing closed.
    A replaced file from before the marks has none to keep and is named as not compared; a copy from before them gains
    the table. It only adds marks, so it only takes power away. Without a usable replaced file it doesn't run, and the
    report says later marks are gone (MARKS_NOT_KEPT)."""
    if not _has(old, 'room_cloud.member_id'):
        if _has(db, 'room_cloud.member_id') and 'room_cloud.member_id' not in report['not_compared']:
            report['not_compared'].append('room_cloud.member_id')
        return
    if not _has(db, 'room_cloud.member_id'):
        from .room_cloud import ROOM_CLOUD_TABLE
        db.execute(ROOM_CLOUD_TABLE)  # one statement, not executescript: that would commit the reconcile's transaction
    kept = 0
    marks = old.execute('SELECT room_id, member_id, set_at FROM room_cloud ORDER BY set_at').fetchall()
    for room_id, member_id, set_at in marks:
        if db.execute('SELECT 1 FROM rooms WHERE id=?', (room_id,)).fetchone() \
                and db.execute('SELECT 1 FROM users WHERE id=?', (member_id,)).fetchone():
            kept += db.execute('INSERT OR IGNORE INTO room_cloud VALUES(?,?,?)', (room_id, member_id, set_at)).rowcount
    report['counts']['cloud marks kept'] = kept


CONNECTIONS_NOT_KEPT = ('Every connection to Claude or another app was revoked and the connector key made new, since there '
                        'was no replaced file to compare with: each person connects again from their app.')
CONNECTION_COMPARED = ('connector_grants.id', 'connector_grants.person_id', 'connector_grants.client_id',
                       'connector_grants.redirect_host', 'connector_grants.rooms', 'connector_grants.ends',
                       'connector_grants.revoked')  # in COMPARED too, so a replaced file lacking one is absent
CONNECTION_NAMED = ('connector_grants.created',)  # read from the copy only
DAMAGED = 'a value one of the two files can\'t read'


def _connection_line(db, row, how):
    found = db.execute('SELECT username FROM users WHERE id=?', (row['person_id'],)).fetchone()
    return '#' + row['id'][:4], found[0] if found else row['person_id'][:6], how


def _room_list(value):
    """A connection's rooms as the reconcile reads them: None for "*", else its JSON list of room ids. Anything else (not
    JSON, not a list, empty, or holding anything but a string) raises ValueError: the connection is revoked, never the
    restore stopped (the section 2's S3)."""
    if value == '*':
        return None
    try:
        rooms = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError('rooms') from None
    if not isinstance(rooms, list) or not rooms or not all(isinstance(room, str) for room in rooms):
        raise ValueError('rooms')
    return rooms


def _finite(value):
    """A number that compares: an int or a float, neither infinite nor NaN."""
    return type(value) in (int, float) and math.isfinite(value)


def _end(value):
    """A connection's end as the reconcile reads it: a finite number, else ValueError (Tardis: two infinite ends would keep
    a connection with no end, and a NaN never compares)."""
    if not _finite(value):
        raise ValueError('ends')
    return value


def _keep_connector_key_like_replaced(db, old, report):
    """Rio Grande, on the design: a connector key rotated after the copy revoked every unused client id and pending
    request (perhaps because a backup leaked it), so the replaced file's key, when it differs, is kept. Connected clients
    are known by their oauth_clients rows (spec D18), so they keep working."""
    import secrets
    from .connector import KEY_NAME
    if not _has(db, 'system_meta'):
        return
    theirs = old.execute('SELECT value FROM system_meta WHERE key=?', (KEY_NAME,)).fetchone() \
        if _has(old, 'system_meta') else None
    if theirs is not None and not (isinstance(theirs[0], str) and re.fullmatch(r'[0-9a-fA-F]{64}', theirs[0])):
        theirs = None  # the re-check's nit 2: not a key, so as if missing, rather than stop go-live in fromhex
    here = db.execute('SELECT value FROM system_meta WHERE key=?', (KEY_NAME,)).fetchone()
    if theirs is None:
        if here is not None:  # the section 2's M1, the key's half: nothing to keep from, so the copy's isn't trusted
            db.execute('INSERT OR REPLACE INTO system_meta VALUES(?, ?)', (KEY_NAME, secrets.token_hex(32)))
            report['counts']['connector key made new'] = 1
        return
    if here is not None and here[0] == theirs[0]:
        return
    db.execute('INSERT OR REPLACE INTO system_meta VALUES(?, ?)', (KEY_NAME, theirs[0]))
    report['counts']['connector key kept from the replaced file'] = 1


def _reason_column(db):
    """Task 9a's N2: a copy taken before revoked_why existed gains it here, as _keep_receipts_like_replaced gives a copy
    its table, so the replaced file's reasons come across (serve would add it later, empty)."""
    if _has(db, 'connector_grants') and not _has(db, 'connector_grants.revoked_why'):
        db.execute('ALTER TABLE connector_grants ADD COLUMN revoked_why TEXT')


def _keep_connections_like_replaced(db, old, now, report):
    """fix:restore-keeps-connector-revocations, with a usable replaced file: a connection is access, so each one the copy
    has takes the replaced file's restrictions, matched by grant id. Its revoke, with the same time; a revoke now when
    the replaced file lacks it; the earlier of the two ends; the narrower of the two room sets ("*" against a list gives
    the list, two lists their intersection), and a revoke when they share no room. It only takes power away. Whether the
    person is still active, still a member of each room, and whether a room is marked are not copied into a connection:
    the reads check each at read time (Task 7, Tardis), so the account, membership and mark reconciles already cover
    them."""
    _keep_connector_key_like_replaced(db, old, report)
    if not (_usable(db, old, report, *CONNECTION_COMPARED) and _usable(db, None, report, *CONNECTION_NAMED)):
        return
    there = {row[0]: row[1:] for row in old.execute(
        'SELECT id, person_id, client_id, redirect_host, rooms, ends, revoked FROM connector_grants')}
    _reason_column(db)
    whys = (dict(old.execute('SELECT id, revoked_why FROM connector_grants'))  # read when the replaced file has it
            if _has(old, 'connector_grants.revoked_why') else {})
    revoked = narrowed = shortened = 0
    for row in db.execute('SELECT id, person_id, client_id, redirect_host, rooms, ends FROM connector_grants '
                          'WHERE revoked IS NULL ORDER BY created, id').fetchall():
        theirs = there.get(row['id'])
        if theirs is None:
            when, how = now, 'missing from the replaced file'
        elif theirs[5] is not None:
            when, how = theirs[5], 'as in the replaced file'
        elif tuple(theirs[:3]) != (row['person_id'], row['client_id'], row['redirect_host']):
            when, how = now, 'another connection in the replaced file'  # fails closed, as _not_this_station does
        else:
            try:
                here_rooms, there_rooms = _room_list(row['rooms']), _room_list(theirs[3])
                here_ends, there_ends = _end(row['ends']), _end(theirs[4])
            except ValueError:
                when, how = now, DAMAGED
            else:
                if here_rooms is None:  # "*" here: the replaced file's set, in its order
                    rooms = there_rooms
                elif there_rooms is None:
                    rooms = here_rooms
                else:  # the intersection, in the order the person chose them in the copy
                    rooms = [room for room in here_rooms if room in set(there_rooms)]
                if rooms is None or rooms:
                    if rooms != here_rooms:
                        db.execute('UPDATE connector_grants SET rooms=? WHERE id=?', (json.dumps(rooms), row['id']))
                        narrowed += 1
                    if there_ends < here_ends:
                        db.execute('UPDATE connector_grants SET ends=? WHERE id=?', (there_ends, row['id']))
                        shortened += 1
                    continue
                when, how = now, 'no room in both files, so a room it named may continue in a newer room'
        db.execute('UPDATE connector_grants SET revoked=? WHERE id=?', (when, row['id']))
        if _has(db, 'connector_grants.revoked_why'):  # Task 9a: as the replaced file said, or the restore's own
            why = whys.get(row['id']) if how == 'as in the replaced file' else None
            db.execute('UPDATE connector_grants SET revoked_why=? WHERE id=?', (why or 'restore', row['id']))
        report['connections'].append(_connection_line(db, row, how))
        revoked += 1
    report['counts'].update({'connections revoked': revoked, 'connections narrowed': narrowed,
                             'connections shortened': shortened})


def _clear_connector_sign_ins(db, old, now, report):
    """Tardis, on the review of fix:restore-keeps-connector-revocations: every pending connector sign-in is cleared, with
    a replaced file or without. A restore soon after a backup would otherwise bring back, within its ten minutes, a
    request decided since the copy, undecided, and a code redeemed since, unredeemed. Someone mid-consent starts over,
    which a restore causes anyway. Nothing here rests on how long a restore takes."""
    if _usable(db, None, report, 'oauth_pending'):
        report['counts']['connector sign-ins cleared'] = db.execute('DELETE FROM oauth_pending').rowcount


ADDABLE_CLEARED = "The lessons listing's addable accounts were cleared; a CONFIRM rerun records them again."


def _clear_lessons_addable(db, old, now, report):
    """Lessons room adds (Task 5 fix round 1, ruling 1): lessons_addable is access, since a row vouches for an account
    the lessons room's ship may add, so every row is cleared, with a replaced file or without. A restored older listing
    must never vouch for an account a newer CONFIRM dropped. A CONFIRM rerun of make station-lessons-room records the
    listing again against the restored pairings. The report says so (ADDABLE_CLEARED) when either file listed one."""
    if not _usable(db, None, report, 'lessons_addable'):
        return
    cleared = db.execute('DELETE FROM lessons_addable').rowcount
    there = old is not None and _has(old, 'lessons_addable') \
        and old.execute('SELECT 1 FROM lessons_addable LIMIT 1').fetchone() is not None
    report['addable_cleared'] = bool(cleared or there)


TOKEN_COMPARED = ('connector_tokens.hash', 'connector_tokens.expires', 'connector_tokens.used')


def _keep_tokens_like_replaced(db, old, now, report):
    """Task 6, with a usable replaced file (Rio Grande, on the restore design): a refresh token rotated since the copy
    must not come back unrotated, nor one revoked since come back live. Each token the copy has takes the replaced
    file's earlier expiry and any use it records; one the replaced file lacks (an access token swept after it ended, or
    any token of a connection that ended) is revoked. A revoke writes REVOKED, never now (the section 2's S1), and it
    reaches the tokens that ran out on their own just before too, as step 4 does (Rio Grande's restore reader's S1): a
    clock that steps back would make one live again. The count is of the live ones. It only takes power away."""
    from .connector import REVOKED
    if not _usable(db, old, report, *TOKEN_COMPARED):
        return
    there = {row[0]: row[1:] for row in old.execute('SELECT hash, expires, used FROM connector_tokens')}
    taken = 0
    for row in db.execute('SELECT hash, expires, used FROM connector_tokens WHERE expires>?', (REVOKED,)).fetchall():
        theirs = there.get(row['hash'])
        expires, used = (REVOKED, row['used']) if theirs is None else (theirs[0], theirs[1] if row['used'] is None else row['used'])
        if not _finite(expires) or used is not None and not _finite(used):
            expires, used = REVOKED, row['used']  # a value the replaced file can't give: fail closed, never a 500 later
        if expires < row['expires'] or used != row['used']:
            db.execute('UPDATE connector_tokens SET expires=?, used=? WHERE hash=?',
                       (min(expires, row['expires']), used, row['hash']))
            taken += row['expires'] > now
    report['counts']['connector tokens taken back'] = taken


RECEIPT_COLUMNS = ('id', 'grant_id', 'person_id', 'app', 'at', 'tool', 'rooms_read', 'rooms_refused', 'size', 'outcome')
RECEIPTS_NOT_KEPT = ("Read receipts made since the copy could not be kept, since there was no usable replaced file to "
                     "take them from: tell the people with connections that Connected apps no longer shows what was "
                     "read between the copy and this restore.")


def _keep_receipts_like_replaced(db, old, now, report):
    """Task 8 (Rio Grande and Tardis, on the restore design): a receipt grants nothing, so the replaced file, the newer
    and whole record, wins whole. Its receipts replace the copy's: one made since the copy comes back, and one a person
    cleared since stays cleared, whatever Task 9 lets a person delete. A copy from before Task 8 has no table; it gains
    one, or the receipts made since the deploy would be lost. Without a usable replaced file the copy's stay, and the
    report says what was lost (RECEIPTS_NOT_KEPT)."""
    from .connector_reads import READS_SCHEMA
    if not _has(old, 'connector_reads'):
        return
    if not _has(db, 'connector_reads'):
        for statement in filter(str.strip, READS_SCHEMA.split(';')):
            db.execute(statement)  # one by one: executescript would commit the reconcile's transaction
    if not _usable(db, old, report, *(f'connector_reads.{column}' for column in RECEIPT_COLUMNS)):
        return
    columns = ', '.join(RECEIPT_COLUMNS)
    rows = old.execute(f'SELECT {columns} FROM connector_reads').fetchall()
    db.execute('DELETE FROM connector_reads')
    db.executemany(f'INSERT INTO connector_reads({columns}) VALUES({", ".join("?" * len(RECEIPT_COLUMNS))})',
                   [tuple(row) for row in rows])
    report['counts']['read receipts as in the replaced file'] = len(rows)


def _revoke_every_token(db, old, now, report):
    """Task 6, without a usable replaced file: every token is revoked, as every connection is, the ones that ran out on
    their own just before included. The count is of the live ones."""
    from .connector import REVOKED
    if _usable(db, None, report, *TOKEN_COMPARED):
        report['counts']['connector tokens taken back'] = db.execute(
            'SELECT count(*) FROM connector_tokens WHERE expires>?', (now,)).fetchone()[0]
        db.execute('UPDATE connector_tokens SET expires=? WHERE expires>?', (REVOKED, REVOKED))


def _revoke_every_connection(db, old, now, report):
    """fix:restore-keeps-connector-revocations, without a usable replaced file: fail closed, as _revoke_every_grant
    does. Every connection is revoked, and the connector key is made new, since the copy's key may be the one that leaked
    (Rio Grande took this over keeping it). A new key voids unused client ids and consent links nobody has signed into;
    pending sign-ins are cleared by _clear_connector_sign_ins, since a client known by its row would outlive the key."""
    import secrets
    from .connector import KEY_NAME
    if _has(db, 'system_meta'):
        db.execute('INSERT OR REPLACE INTO system_meta VALUES(?, ?)', (KEY_NAME, secrets.token_hex(32)))
        report['counts']['connector key made new'] = 1
    if not _usable(db, None, report, *CONNECTION_COMPARED, *CONNECTION_NAMED):
        return
    _reason_column(db)  # each revoke below records the restore as its reason, a copy from before 9a included
    rows = db.execute('SELECT id, person_id FROM connector_grants WHERE revoked IS NULL ORDER BY created, id').fetchall()
    for row in rows:
        db.execute('UPDATE connector_grants SET revoked=? WHERE id=?', (now, row['id']))
        if _has(db, 'connector_grants.revoked_why'):
            db.execute("UPDATE connector_grants SET revoked_why='restore' WHERE id=?", (row['id'],))
        report['connections'].append(_connection_line(db, row, 'no usable replaced file'))
    report['counts']['connections revoked'] = len(rows)


def _unpair_named(db, old, named, now, report):
    """--unpair PEER (revision 4): the same, for the peers a person names (the only way without a usable replaced file)."""
    if not named:
        return
    if not _usable(db, None, report, *PEER_NEEDS):
        raise UnpairRefused('Refused: this copy lacks the peer tables, so there is nothing to unpair.')
    for peer in named:
        if peer not in report['unpaired_full']:
            _unpair(db, old, peer, now, report)
    # a peer named here is no longer one the report calls left paired (N3)
    report['lacked'] = [item for item in report['lacked'] if item[2] not in report['unpaired_full']]


def _resolve_peers(db, names):
    """Each name is a peer's 12-character short id or its full id, matching exactly one peers row; otherwise refused."""
    found = []
    ids = [row[0] for row in db.execute('SELECT peer_id FROM peers')] if _has(db, 'peers.peer_id') else []
    for name in names:
        matches = [peer for peer in ids if peer == name or (len(name) == 12 and peer[:12] == name)]
        if len(matches) != 1:
            raise UnpairRefused(f'Refused: --unpair {safe_line(name, 80)} matches {len(matches)} peers in the copy; '
                                'give a peer\'s 12-character id or its full id, as exactly one peer has it.')
        found.append(matches[0])
    return found


MARK_KEY = 'restore_reconcile'


class CarryRefused(ValueError):
    """station-carry-nonces won't touch these files; nothing was changed."""


class CarryUnmarked(Exception):
    """The nonces were carried, but $ASIDE/carried, which step 8 reads, could not be written."""


CARRIED_NAME = 'carried'


def _lstat(path):
    """os.lstat(path), or None when nothing is there: only a missing name, or a file where a directory should be, reads
    as absent. Any other OSError, an unsearchable directory's EACCES above all, is raised, so the carry names the right
    cause on every Python (the F1 reader's finding 2: from 3.14, is_file() and is_symlink() return False on it)."""
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _symlinked(path):
    """The database or one of its sidecars is a symlink, as _refuse and Store._check_paths refuse."""
    return any((found := _lstat(f'{path}{end}')) is not None and stat.S_ISLNK(found.st_mode)
               for end in ('', '-journal', '-wal', '-shm'))


def _regular(path):
    """A regular file is at path. Not followed: _symlinked has refused a link there already."""
    found = _lstat(path)
    return found is not None and stat.S_ISREG(found.st_mode)


def _has_table(db, name, schema='main'):
    return db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _marked_path(db, schema):
    """The staged file's path in the schema's restore mark (_write_mark), or None when there is no usable mark."""
    if not _has_table(db, 'system_meta', schema):
        return None
    row = db.execute(f'SELECT value FROM {schema}.system_meta WHERE key=?', (MARK_KEY,)).fetchone()
    try:
        path = json.loads(row[0])['path']
    except (TypeError, ValueError, KeyError):
        return None
    return path if isinstance(path, str) and '\0' not in path else None  # realpath raises on a NUL


REPLACED_DIR = re.compile(r'replaced-\d{8}-\d{6}')


def _newest_replaced(backups):
    """The newest restore directory's name: they are named by step 1's local time, all one width, so it sorts last.
    Listed, not globbed, so a backups directory that can't be listed is refused under its own cause, not read as one
    with no restore in it (the F1 reader's second "for later")."""
    try:
        names = os.listdir(backups)
    except OSError as error:
        raise CarryRefused(f'{backups} could not be listed ({error.strerror or type(error).__name__})') from None
    return max((name for name in names if REPLACED_DIR.fullmatch(name)), default=None)


def _source_uri(source):
    """The URI the carry attaches the restored station by, so it leaves no file beside it that it didn't find there
    (store-wal-mode Task 7: a WAL source attached `mode=ro` gained a -wal and a -shm, which a read-only connection can't
    remove). Rollback mode: `mode=ro`. WAL mode with no -wal: `immutable=1`, which reads the file alone and makes no
    sidecar; with no -wal, the last connection's close checkpointed every commit into it. WAL mode with a -wal, which a
    listener killed mid-run leaves: `mode=ro` through it and its -shm, so a commit made only there is carried too. A -wal
    without its -shm is refused, since reading it would create one. The header is read with header_mode, before any
    connection opens the source; a source it can't read is refused, saying nothing was changed (Task 7 reader's B-3: the
    OSError reached the person as a bare errno line, with no "nothing was changed" and no cause). A WAL header with a
    -journal beside it, which only a journal mode switch cut short leaves, is refused too: immutable=1 would read past a
    journal that rollback mode's mode=ro refuses (B-2). So is its mirror, a rollback header with a -wal beside it, which
    only a mismatched copy leaves: mode=ro would read that -wal and create a -shm beside the source (the B-2 reader's
    note)."""
    uri = source.absolute().as_uri()
    try:
        mode = header_mode(source)
    except OSError as error:
        raise CarryRefused(f'{source} could not be read ({error.strerror or type(error).__name__})') from None
    if mode != 'wal':
        if Path(f'{source}-wal').exists():
            raise CarryRefused(f'{source} is in rollback mode with a -wal beside it, which only a mismatched copy leaves')
        return uri + '?mode=ro'
    if Path(f'{source}-journal').exists():
        raise CarryRefused(f'{source} is in WAL mode with a -journal beside it, which a cut-short journal mode switch leaves')
    wal, shm = (Path(f'{source}{end}').exists() for end in ('-wal', '-shm'))
    if not wal:
        return uri + '?mode=ro&immutable=1'
    if not shm:
        raise CarryRefused(f'{source} has a -wal without its -shm, and reading it would create one beside it')
    return uri + '?mode=ro'


def carry_pull_nonces(data_dir, aside):
    """Runbook 10.3, after a rollback (fix:pull-floor-after-rollback, Rio Grande's reader's better way): the file put back
    lacks the pull nonces the restored station recorded while it was live, so a pull it served could be replayed. This
    copies them in from that station's file, which 10.2 moved to $ASIDE/restored-live, `INSERT OR IGNORE` from a
    read-only attach: exact, depending on no clock, and a second run adds nothing. Run with the station stopped (10.1).
    The source is named by this restore's directory, never by a file name a typo could change, and must be the station
    restored from it: its restore mark names $ASIDE/restored.sqlite3 (re-check SF1: restored.sqlite3 itself, a rotation
    copy or chosen.sqlite3 carried 0 and said all was well). Refused, with nothing changed: a live file that is missing,
    has no pull_nonces, or is a symlink or has one among its sidecars; a $ASIDE that still holds peer.sqlite3 (10.3's
    move hasn't run, so the live file is not the one put back); a source that is missing, symlinked the same way, the
    live file, unreadable, with sidecars that don't match its journal mode (_source_uri), without pull_nonces, damaged,
    or not marked as restored from $ASIDE; a restored-live that is itself a symlink, which would carry from a directory
    elsewhere (the F1 reader's first "for later"); a path among these that can't be checked, on any Python, such as an
    unsearchable directory or an $ASIDE or backups directory that can't be listed (_lstat, os.listdir); and a $ASIDE
    that isn't the newest replaced-<time> directory, as the runbook's ASIDE line names it (the re-check's nit 2: an
    earlier restore that was also rolled back passed everything else). After the commit it writes $ASIDE/carried, without which step 8 leaves
    the federation units off after a rollback (CarryUnmarked if it can't). Returns (nonces added, nonces in the
    source)."""
    aside = Path(aside)
    live, source = Path(data_dir) / LIVE_NAME, aside / 'restored-live' / LIVE_NAME
    try:
        if _symlinked(live) or not _regular(live):
            raise CarryRefused(f'No peer database at {live} (or it or a sidecar is a symlink): nothing to carry into')
        try:  # listed, not globbed: glob swallows a PermissionError and would hide a stray file (finding 3)
            names = os.listdir(aside)
        except (FileNotFoundError, NotADirectoryError):
            names = []   # no $ASIDE: the source check below says so
        if any(name == LIVE_NAME or name.startswith(LIVE_NAME + '-') for name in names):
            raise CarryRefused(f"{aside} still holds a {LIVE_NAME} file, so 10.3's move hasn't run and {live} is not the file put back")
        found = _lstat(source.parent)
        if found is not None and stat.S_ISLNK(found.st_mode):  # 10.2 makes restored-live with install -d, never a link
            raise CarryRefused(f'{source.parent} is a symlink, so the station in it is not the one 10.2 moved aside')
        if _symlinked(source) or not _regular(source):
            raise CarryRefused(f'No restored station at {source} (or it or a sidecar is a symlink): nothing to carry from '
                               '(10.2 moves it there)')
        if source.samefile(live):  # also a hard link to it
            raise CarryRefused('The source is the live database itself')
    except OSError as error:  # F1: a CarryRefused raised above isn't an OSError, so only a failed check lands here
        raise CarryRefused(f'{error.filename or source} could not be checked ({error.strerror or type(error).__name__})') from None
    attach = _source_uri(source)  # before anything here opens the source in SQLite (header_mode's rule)
    # URIs: the live file opened `mode=rw` is never created, and the source is never changed and gains no file beside it
    # (_source_uri; in rollback mode a hot journal, from a listener killed mid-transaction, is refused rather than rolled
    # back into it)
    with closing(sqlite3.connect(live.absolute().as_uri() + '?mode=rw', uri=True, timeout=30, isolation_level=None)) as db:
        if not _has_table(db, 'pull_nonces'):
            raise CarryRefused(f'{live} has no pull_nonces table, so it is not a station database')
        db.execute('ATTACH DATABASE ? AS restored', (attach,))
        try:
            if not _has_table(db, 'pull_nonces', 'restored'):
                raise CarryRefused(f'{source} has no pull_nonces table, so it is not a station database')
            checked = [row[0] for row in db.execute('PRAGMA restored.integrity_check(pull_nonces)')]
            if checked != ['ok']:
                raise CarryRefused(f'{source} fails its integrity check: {safe_line(checked[0], 120)}')
            marked = _marked_path(db, 'restored')
            if marked is None or os.path.realpath(marked) != os.path.realpath(aside / STAGED_NAME):
                raise CarryRefused(f'{source} is not marked as the station restored from {aside / STAGED_NAME}')
            newest = _newest_replaced(aside.resolve().parent)  # last, so each refusal above still names its own cause
            if aside.resolve().name != newest:
                raise CarryRefused(f"{aside} is not the newest replaced-<time> directory, which the runbook's ASIDE line "
                                   f'names ({newest}), so it is not this restore')
            total = db.execute('SELECT count(*) FROM restored.pull_nonces').fetchone()[0]
            db.execute('BEGIN IMMEDIATE')
            added = db.execute('INSERT OR IGNORE INTO main.pull_nonces(origin, nonce, at) '
                               'SELECT origin, nonce, at FROM restored.pull_nonces').rowcount
            db.execute('COMMIT')
        finally:
            if db.in_transaction:
                db.execute('ROLLBACK')
            db.execute('DETACH DATABASE restored')
    try:  # step 8 starts the federation units after a rollback only when this is there (the third re-check's SF1)
        fd = os.open(aside / CARRIED_NAME, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(f'{added} of {total}\n')
    except OSError as error:
        raise CarryUnmarked(f'the nonces were carried ({added} of {total}), but {aside / CARRIED_NAME} could not be '
                            f'written ({error.strerror}), so step 8 leaves the federation units off: start them with '
                            "10.4's line") from error
    return added, total


def _write_mark(db, old, now, path):
    """Follow-up 1: the proof, inside the staged copy, that the reconcile ran on it. It is a system_meta row (the station's
    own key/value table, which a copy from before the system author lacks, so it is created here), written in the
    reconcile's transaction: a rolled-back run leaves none. Runbook step 6 reads it before it installs. It records when
    the reconcile ran, the staged file's absolute path and whether a replaced file was compared; it holds no account, key or token."""
    db.execute('CREATE TABLE IF NOT EXISTS system_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('INSERT OR REPLACE INTO system_meta(key, value) VALUES(?, ?)',
               (MARK_KEY, json.dumps({'at': now, 'replaced': old is not None, 'path': os.path.abspath(path)})))


def _title(draft):
    try:
        return json.loads(draft).get('title') or 'Untitled'
    except (TypeError, ValueError, AttributeError):
        return 'Untitled'


def _report_differences(db, old, now, report):
    """Reported, never applied, since a bad replaced file may be the reason for the restore: users whose password
    differs, instruction layers whose active revision differs, and peers paired there but not here (a pairing taken away is applied)."""
    if _usable(db, old, report, 'users.salt', 'users.password_hash'):
        there = {row[0]: (row[1], row[2]) for row in old.execute('SELECT id, salt, password_hash FROM users')}
        report['passwords'] = [row['username'] for row in db.execute('SELECT id, username, salt, password_hash FROM users ORDER BY username')
                               if row['id'] in there and there[row['id']] != (row['salt'], row['password_hash'])]
    if _usable(db, old, report, 'layers.active_revision', 'layers.draft'):
        here = {row['id']: row['active_revision'] for row in db.execute('SELECT id, active_revision FROM layers')}
        for layer_id, active, draft in old.execute('SELECT id, active_revision, draft FROM layers ORDER BY id').fetchall():
            if (layer_id in here and here[layer_id] != active) or (layer_id not in here and active is not None):
                report['layers'].append((layer_id[:6], _title(draft), here.get(layer_id), active))
    if _usable(db, old, report, 'room_briefs.revision', 'room_briefs.body', 'rooms.title'):
        # Follow-up 4: a restore brings back a brief the owner changed or removed since the copy (or loses one written since).
        # By room, for rooms in both files; the text is compared and never printed.
        def briefs(connection):
            return {row[0]: (row[1], row[2]) for row in connection.execute('SELECT room_id, revision, body FROM room_briefs')}
        here, there = briefs(db), briefs(old)
        both = ({row[0] for row in db.execute('SELECT id FROM rooms')} & {row[0] for row in old.execute('SELECT id FROM rooms')})
        for room_id in sorted(both):
            if here.get(room_id) != there.get(room_id):
                title = db.execute('SELECT title FROM rooms WHERE id=?', (room_id,)).fetchone()[0]
                report['briefs'].append((room_id[:6], title, here.get(room_id), there.get(room_id)))
    if _usable(db, old, report, 'peers.paired'):  # revision 4: paired here and unpaired there was applied above
        here = dict(db.execute('SELECT peer_id, paired FROM peers').fetchall())
        there = dict(old.execute('SELECT peer_id, paired FROM peers').fetchall())
        def known(peer):
            names = [row[0] for row in db.execute(f'SELECT label FROM ({_labelled(db)}) WHERE peer_id=? ORDER BY label', (peer,))] \
                if _has(db, 'remote_contacts.name') else []
            return (_shown(db, old, peer), names, peer)
        report['peers'] = [known(peer) for peer in sorted(there) if there[peer] and not here.get(peer)]
        report['lacked'] = [known(peer) for peer in sorted(here) if here[peer] and peer not in there]


def _refuse(db_path, live_data_dir):
    """S16: never a file in the live data dir (the one --live-data-dir names, or any directory holding a dispatch.lock,
    which every directory a station has opened holds), never a symlink. The check runs on the file's real directory,
    so a path, a symlinked parent or '..' can't fool it. A file with a second name (a hard link) is refused too, since
    the other name could be the live file (plan review M2). Nor a copy in the backups rotation (fix round 1): any
    directory holding the rotation's .lock, which every rotation a backup has written holds, and backups/station beside
    the --live-data-dir. A copy there is a checked copy, and reconciling it in place would change it."""
    if db_path.is_symlink() or any(Path(f'{db_path}{end}').is_symlink() for end in ('-journal', '-wal', '-shm')):
        raise ReconcileRefused('Refused: the copy is a symlink. Stage a real file (runbook step 5).')
    if not db_path.is_file():
        raise ReconcileRefused(f'Refused: there is no file at {db_path}')
    if db_path.stat().st_nlink > 1:
        raise ReconcileRefused('Refused: the copy has another name (a hard link), so writing it could write another file. '
                               'Stage a real copy with install (runbook step 5).')
    home = db_path.resolve().parent
    if os.path.lexists(home / 'dispatch.lock') or (live_data_dir is not None and home == Path(live_data_dir).resolve()):
        raise ReconcileRefused('Refused: that file is in a live data directory. Stage the copy in the replaced directory (runbook step 5).')
    if os.path.lexists(home / '.lock') or (live_data_dir is not None and home == default_backup_dir(live_data_dir).resolve()):
        raise ReconcileRefused('Refused: that file is in the backups rotation, a checked copy that reconciling would change. '
                               'Stage a copy of it in the replaced directory (runbook step 5).')


def _replaced(path):
    """(read-only connection, None) when the replaced file is usable, else (None, why). A replaced file that won't open
    or fails quick_check is treated as absent, and the reconcile fails closed; the report says why."""
    if path is None:
        return None, 'not given'
    path = Path(path).absolute()
    if path.is_symlink():
        return None, 'treated as absent (it is a symlink)'
    if not path.is_file():
        return None, 'treated as absent (there is no such file)'
    old = None
    try:
        old = _read_only(path)
        if _check(old, 'quick_check'):
            return old, None
    except sqlite3.Error:
        pass
    if old is not None:
        old.close()
    journal = Path(f'{path}-journal')
    return None, f'treated as absent ({"a hot journal beside it, " + journal.name if _hot(journal) else "it failed its check"})'


def _hot(journal):
    """SQLite's own rule for a hot journal: a file whose first byte isn't zero. An empty journal isn't hot, nor is one
    whose header is still zero because its write never synced; neither is why a replaced file failed its check."""
    if not journal.is_file():
        return False
    try:
        with open(journal, 'rb') as stream:
            return stream.read(1) not in (b'', b'\x00')
    except OSError:
        return False


def _not_this_station(db, old):
    """Fix round 1 (review I1): why a replaced file that passed quick_check still can't be compared, or None. It lacks
    a table or column in COMPARED that the copy has (a 0-byte file is a valid empty database), or an account or ship key
    the copy has (neither is ever deleted, so that is another station's file or a damaged one). Names no id."""
    lacking = [need for need in COMPARED if _has(db, need) and not _has(old, need)]
    if lacking:
        more = f' and {len(lacking) - 3} more' if len(lacking) > 3 else ''
        return f'it lacks tables or columns the copy has: {", ".join(lacking[:3])}{more}'
    for table in ('users', 'ship_keys'):
        if _has(db, f'{table}.id') and _has(old, f'{table}.id'):
            there = {row[0] for row in old.execute(f'SELECT id FROM {table}')}
            if any(row[0] not in there for row in db.execute(f'SELECT id FROM {table}')):
                return "it lacks accounts or ship keys the copy has, so it is another station's file or a damaged one"
    return None


LIVE_NAME, STAGED_NAME = 'peer.sqlite3', 'restored.sqlite3'
STEP_5 = 'Step 5 runs DB="$ASIDE/restored.sqlite3" REPLACED="$ASIDE/peer.sqlite3".'


def refuse_unstaged_db(db_path):
    """The coordinator's ruling on the re-review's probe (f), which folds in final review I1's peer.sqlite3 check: the CLI
    calls this before reconcile(), so before any file is opened. DB= is always the restored.sqlite3 runbook step 5
    staged. DB="$ASIDE/chosen.sqlite3" rewrote chosen.sqlite3 with exit 0 and left restored.sqlite3 unreconciled for
    step 6; DB="$ASIDE/peer.sqlite3" (the original, or DB= and REPLACED= swapped) rewrote the rollback target. The
    restore test calls reconcile() directly on its scratch peer.sqlite3, so it is unaffected."""
    name = Path(db_path).name
    if name != STAGED_NAME:
        swapped = (f" {LIVE_NAME} is the live file's name and the original's that step 4 set aside: are DB= and REPLACED= "
                   'swapped? Refusing so the set-aside original is never rewritten.') if name == LIVE_NAME else ''
        raise ReconcileRefused(f'Refused: DB= must be the {STAGED_NAME} that runbook step 5 staged; this file is named '
                               f'{safe_line(name, 80)}.{swapped} {STEP_5} Nothing was changed.')


def refuse_misnamed_replaced(replaced):
    """The coordinator's ruling on the final fix round's finding: the CLI calls this before reconcile(), so before any
    file is opened. REPLACED= is always the peer.sqlite3 runbook step 4 set aside. A typo naming chosen.sqlite3 (the
    same content as the staged copy) compared the copy with itself, exited 0 and left every key revoked since the copy
    working. restored.sqlite3 or a rotation copy is the wrong file in the same way: never what the restore replaced."""
    if replaced is not None and Path(replaced).name != LIVE_NAME:
        raise ReconcileRefused(f'Refused: REPLACED= must be the {LIVE_NAME} that runbook step 4 set aside; this file is named '
                               f'{safe_line(Path(replaced).name, 80)}. {STEP_5} Nothing was changed.')


def reconcile(db_path, *, replaced=None, live_data_dir=None, unpair=(), clock=time.time):
    """station-restore-reconcile (S16): on a staged copy, take back what a restore revives. Every step only takes access
    away, all in one transaction: if any step fails it rolls back and the copy is unchanged. Returns the report. The CLI
    first refuses a DB not named restored.sqlite3 and a REPLACED not named peer.sqlite3 (refuse_unstaged_db,
    refuse_misnamed_replaced); the restore test calls this directly on its scratch peer.sqlite3."""
    db_path = Path(db_path).absolute()
    _refuse(db_path, live_data_dir)
    if header_mode(db_path) == 'wal':  # store-wal-mode D4: every backup copy is a rollback-mode file
        raise ReconcileRefused(f'{db_path} is in WAL mode, so step 6 would install its main file alone; stage a copy '
                               'made by station-backup or station-restore-test, which are single files')
    old, why = _replaced(replaced)
    report = {'replaced': why or 'compared', 'counts': {}, 'sequences': {}, 'revoked': [], 'removed': [], 'lowered': [],
              'no_super_admin': False, 'closed': [], 'unpaired': [], 'unpaired_full': [], 'unpaired_counts': [0, 0],
              'held': [], 'held_counts': [0, 0], 'lacked': [], 'passwords': [], 'layers': [], 'briefs': [], 'peers': [], 'skipped': [],
              'not_compared': [], 'grants': [], 'connections': [], 'trusts': [], 'addable_cleared': False}
    salvage = None
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        if not _check(db, 'integrity_check'):
            raise ReconcileRefused('Refused: the copy failed its integrity check.')
        if not _has(db, 'users'):  # final review M5: a 0-byte file is a valid empty database; step 6 must not install it
            raise ReconcileRefused('Refused: the copy has no users table, so it is not a station database (an empty file '
                                   'is a valid empty one). Stage it again from chosen.sqlite3 (runbook step 5).')
        # Plan review M2: the likeliest slips at runbook step 5.
        if old is not None and os.path.samefile(Path(replaced).absolute(), db_path):
            raise ReconcileRefused('Refused: --replaced is the staged copy itself. REPLACED= is the peer.sqlite3 set aside in runbook step 4.')
        why = _not_this_station(db, old) if old is not None else None
        if why:  # review I1: compared, it would take back nothing and revoke no key; fail closed, as for one that fails its check
            if _has(old, *RETIRED_NEEDS):
                salvage = old  # its retirements are kept below (_keep_retirements); everything else is treated as absent
            else:
                old.close()
            old, report['replaced'] = None, f'treated as absent ({why})'
        # The live file always holds the copy's history and more, so its events sequence is never lower; a lower one
        # means DB= and REPLACED= were swapped. Final review M1: only a replaced file that is this station's is checked.
        # One treated as absent left the copy's sequences 1,000,000 higher, so a second run (UNPAIR=) would read as
        # swapped when it isn't. A real swap names the set-aside peer.sqlite3 as DB=, which the CLI refuses by name.
        if old is not None and _has(old, 'events') and _has(db, 'events') and _sequence(old, 'events') < _sequence(db, 'events'):
            raise ReconcileRefused('Refused: the replaced file is older than the staged copy. Are DB= and REPLACED= swapped? '
                                   'DB= is the staged restored.sqlite3; REPLACED= is the peer.sqlite3 set aside in runbook step 4.')
        named = _resolve_peers(db, list(unpair))
        db.execute('BEGIN IMMEDIATE')
        try:
            now = clock()
            for step in (_end_sessions, _use_invitations, _revoke_held_keys, _clear_uncollected, _expire_waiting, _raise_sequences,
                         _hold_imprints, _clear_connector_sign_ins, _clear_lessons_addable):
                step(db, old, now, report)
            if old is None:
                _revoke_owned_ship_keys(db, old, now, report)
                _revoke_every_grant(db, old, now, report)
                _revoke_every_connection(db, old, now, report)
                _revoke_every_token(db, old, now, report)
                _revoke_every_trust(db, old, now, report)
                if salvage is not None:
                    _keep_retirements(db, salvage, now, report)
            else:
                for step in (_revoke_like_replaced, _remove_members_like_replaced, _lower_roles_like_replaced,
                             _close_breakouts_like_replaced, _revoke_grants_like_replaced, _add_budget_uses_like_replaced,
                             _add_member_changes_like_replaced,
                             _unpair_like_replaced, _hold_like_replaced, _keep_trust_like_replaced,
                             _keep_marks_like_replaced,
                             _keep_connections_like_replaced, _keep_tokens_like_replaced, _keep_receipts_like_replaced,
                             _report_differences):
                    step(db, old, now, report)
            _settle_trust(db, old, now, report)
            _unpair_named(db, old, named, now, report)
            _settle_trust(db, old, now, report)  # again: an owner UNPAIR= held gets its dated revocation (S10, N13)
            _name_trusts(db, old, report)
            _write_mark(db, old, now, db_path)
            db.execute('COMMIT')
        except BaseException:
            if db.in_transaction:  # SQLite rolls back by itself on some errors (SQLITE_FULL, IOERR); the CLI reports those
                db.execute('ROLLBACK')
            raise
    finally:
        db.close()
        for handle in (old, salvage):
            if handle is not None:
                handle.close()
    return report


def _revision(value):
    return 'none' if value is None else f'revision {value}'


def describe_reconcile(report):
    """What Andy reads at runbook step 5 (S16): counts, then usernames, short ids and titles under the header that they
    come from people. Never a hash, a key or a token."""
    def people(values):
        return ', '.join(safe_line(value) for value in values)
    lines = [REPORT_HEADER]
    if report['replaced'] == 'compared':
        lines.append('Compared with the replaced file.')
    else:
        lines.append(f"The replaced file was {report['replaced']}. Room and space members, admins and law layers were not "
                     "compared: check them by hand in runbook step 8. Peer pairings were not compared either, and nothing was "
                     'unpaired: before the copy goes live (runbook step 5), peer pairings: list them and name any you had cut '
                     "off in UNPAIR=. Every owned ship's keys were revoked, so those machines dock again. " + MARKS_NOT_KEPT
                     + ' ' + CONNECTIONS_NOT_KEPT + ' ' + RECEIPTS_NOT_KEPT + ' ' + TRUSTS_RESTORED
                     + ('' if report.get('retirements_kept') else ' ' + TRUST_RETIREMENTS_NOT_KEPT))
    lines.append('Taken back: ' + ', '.join(f'{label} ({count})' for label, count in report['counts'].items()) + '.')
    for table, (before, after) in report['sequences'].items():
        if after != before:
            lines.append(f"The {table} sequence was raised from {before} to {after}, so no watcher's saved cursor hides what comes next.")
    if report['revoked']:
        lines.append(f'Ship keys revoked for: {people(sorted(set(report["revoked"])))}.')
    if report['grants']:
        lines.append('Grants revoked: ' + '; '.join(f'{short} ({safe_line(issuer)} to {safe_line(grantee)}, {how})'
                                                   for short, issuer, grantee, how in report['grants']) + '.')
    if report['connections']:
        lines.append('Connections revoked: ' + '; '.join(f'{short} ({safe_line(person)}, {how})'
                                                         for short, person, how in report['connections']) + '.')
    if report['removed']:
        lines.append('Removed: ' + '; '.join(f'{safe_line(who)} from {kind} {short} {safe_line(title)}'
                                             for who, kind, short, title in report['removed']) + '.')
    if report['lowered']:
        lines.append(f'Roles lowered for: {people(report["lowered"])}.')
    if report['no_super_admin']:
        lines.append('No active super admin remains after lowering roles: renew a pending one with bootstrap-super-admin '
                     '--renew-activation, or reserve one with bootstrap-super-admin (runbook step 7).')
    if report['closed']:
        lines.append('Breakouts closed as in the replaced file: '
                     + '; '.join(f'{short} {safe_line(title)}' for short, title in report['closed']) + '.')
    if report['unpaired']:
        withdrawn, cleared = report['unpaired_counts']
        lines.append('Unpaired again: ' + '; '.join(f'{peer} ({people(names)})' if names else peer for peer, names in report['unpaired'])
                     + f'. Withdrew {withdrawn} pending and failed deliveries and cleared {cleared} received payloads.')
    if report['held']:
        withdrawn, cleared = report['held_counts']
        lines.append('Held again, as in the replaced file, each until its own code is typed: '
                     + '; '.join(f'{peer} ({safe_line(name)})' for peer, name in report['held'])
                     + f'. Withdrew {withdrawn} pending and failed deliveries and cleared {cleared} received payloads.')
    if report['trusts']:
        lines.append('Owner trusts: ' + '; '.join(f'{short} ({safe_line(owner)}, {how})'
                                                  for short, owner, how in report['trusts']) + '.')
    if report['addable_cleared']:
        lines.append(ADDABLE_CLEARED)
    if report['passwords']:
        lines.append(f'Reported, not applied: these passwords differ from the replaced file: {people(report["passwords"])}. '
                     'Change again any that was changed for a reason.')
    if report['layers']:
        lines.append('Reported, not applied: law layers whose active revision differs: ' + '; '.join(
            f'{short} {safe_line(title)} (here {_revision(here)}, in the replaced file {_revision(there)})'
            for short, title, here, there in report['layers']) + '. Set them in the browser before the ships start.')
    if report['briefs']:
        def brief_state(state):
            return 'none' if state is None else f'revision {state[0]}' + (', removed' if not state[1] else '')
        lines.append('Reported, not applied: room briefs that differ from the replaced file: ' + '; '.join(
            f'{short} {safe_line(title)} (here {brief_state(here)}, in the replaced file {brief_state(there)})'
            for short, title, here, there in report['briefs']) + '. Their text is not shown. Read them in the browser and '
            'save again the one you want before the ships start.')
    if report['peers'] or report['lacked']:
        def listed(items):
            return ', '.join(f'{short} ({people(names)})' if names else short for short, names, _ in items)
        parts = ([f'paired in the replaced file but not here: {listed(report["peers"])}'] if report['peers'] else []) \
            + ([f'paired here and absent from the replaced file, so left paired: {listed(report["lacked"])}'] if report['lacked'] else [])
        lines.append('Reported, not applied: peers: ' + '; '.join(parts) + '.')
    if report['skipped']:
        lines.append(f'Skipped, because this copy lacks them: {", ".join(report["skipped"])}.')
    if report['not_compared']:
        lines.append(f'Not compared, because the replaced file lacks them: {", ".join(report["not_compared"])}.')
    return '\n'.join(lines)


def counts(db):
    """S7: users that aren't the system author, rooms and messages. A copy from before the system author counts every
    user, which is the same number once the server's start has added it."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    users = ("SELECT count(*) FROM users WHERE id NOT IN (SELECT value FROM system_meta WHERE key='system_author')"
             if 'system_meta' in tables else 'SELECT count(*) FROM users')
    return tuple(db.execute(sql).fetchone()[0] for sql in (users, 'SELECT count(*) FROM rooms', 'SELECT count(*) FROM messages'))


def server_command(scratch, port):
    """S7 step 5: today's code serving the copy on loopback: no proxy headers, no sync, no share link, no Odo."""
    return [sys.executable, '-I', '-m', 'superyak_peer', 'serve', '--data-dir', str(scratch), '--host', '127.0.0.1', '--port', str(port)]


def _pick_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


LIVE_PORTS = (7435, 7436)  # serve's and the door's --port defaults: the lighthouse and the door
PORT_TRIES = 20


def _free_port():
    """Final review M8: a free loopback port that is never the live station's, whatever the kernel's ephemeral range."""
    for _ in range(PORT_TRIES):
        port = _pick_port()
        if port not in LIVE_PORTS:
            return port
    raise BackupError(22, 'the restored station did not start: no free loopback port other than 7435 and 7436')


def _answers(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback never goes through a proxy
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=2) as reply:
            return reply.status == 200
    except OSError:
        return False


def _stop(process):
    """S7 step 8: SIGTERM, then SIGKILL after 10 s, then wait()."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(STOP_WAIT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _start(scratch):
    """S7 steps 5-6: serve the scratch copy on a free loopback port until /api/health answers 200, within 60 s. A server
    that exits during start-up (its port taken in the meantime) is started again, up to 3 times."""
    for _ in range(START_TRIES):
        port, process = _free_port(), None
        try:  # final review M7: Popen inside the try, so a signal just after it can't orphan the server
            process = subprocess.Popen(server_command(scratch, port), cwd=scratch, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            deadline = time.monotonic() + START_WAIT
            while process.poll() is None and time.monotonic() < deadline:
                if _answers(port):
                    return process, port
                time.sleep(0.2)
        except BaseException:
            _stop(process)
            raise
        exited = process.poll() is not None
        _stop(process)
        if not exited:
            break  # it ran for 60 s without answering: no second try
    raise BackupError(22)


def _leftovers(parent, now):
    """S7 step 2: scratch directories over a day old, owned by this user; never symlinks (the shared /tmp fallback)."""
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith(SCRATCH_PREFIX):
            continue
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and now - info.st_mtime > TEMP_MAX_AGE:
            shutil.rmtree(entry.path, ignore_errors=True)


def _restored_copy(source, target):
    """S7 step 3: the backup API from a read-only connection into a new 0600 file, then integrity_check. BACKUP=
    pointed at the live file reads it and nothing more."""
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    try:
        with closing(_read_only(source)) as copy_from, closing(sqlite3.connect(target)) as copy:
            copy_from.backup(copy, pages=-1)
            _as_single_file(copy)
            return _check(copy, 'integrity_check')
    except sqlite3.DatabaseError:
        return False


def restore_test(backup_dir, backup=None):
    """station-restore-test (S7). It takes no data dir, so it can't name the live one (R9). Every path tears down: the
    server is stopped and reaped and the scratch directory removed."""
    backup_dir = Path(backup_dir).absolute()
    source = Path(backup).absolute() if backup else newest_copy(backup_dir)
    if source is None or not source.is_file():
        raise BackupError(20)
    parent = Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())
    _leftovers(parent, time.time())
    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=parent))
    server = None
    try:
        target = scratch / 'peer.sqlite3'
        with rotation_lock(backup_dir) if backup_dir.is_dir() else nullcontext():  # pruning can't remove it mid-copy
            sound = _restored_copy(source, target)
        if not sound:
            raise BackupError(21)
        with closing(_read_only(target)) as db:
            before = counts(db)
        try:
            reconcile(target)  # S16 without --replaced, before the server's start: the scratch holds no dispatch.lock yet
        except Exception as error:
            raise BackupError(24) from error
        from .identity import PeerIdentity  # here, as Store is below: backups.py stays standard library when imported
        PeerIdentity.load_or_create(scratch)  # G4b: a throwaway identity, so a copy holding signed records starts; removed with it
        server, port = _start(scratch)
        from .db import Store  # S7 step 7: the trusted local path; the test never mints a session or holds a password
        with Store(scratch).transaction() as db:
            after = counts(db)
        if after != before or after[0] < 1 or after[1] < 1:
            raise BackupError(23)
        return {'backup': source, 'port': port, 'counts': after}
    finally:
        _stop(server)
        shutil.rmtree(scratch, ignore_errors=True)
