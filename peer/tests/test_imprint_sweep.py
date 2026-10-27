"""The sweep: ends, windows, retries, restore reconciliation and retention (spec I 12, D32, D42; plan Task 42a)."""
from contextlib import closing
import fcntl
import hashlib
import json
import sqlite3
import uuid

import pytest

from superyak_peer import backups, imprints
from superyak_peer.__main__ import main as cli
from superyak_peer.imprints import KNOWN_LIMITS
from imprint_support import NOW, seed_imprint, station
from test_imprint_approval import received

DAY = 86400
CANARY = "CANARY-memory-text-that-must-not-reach-a-backup"


def ids_of(name):
    return hashlib.md5(name.encode()).hexdigest(), str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


def row(st, name):
    with st.store.transaction() as db:
        found = db.execute("SELECT * FROM imprint_requests WHERE id=?", (ids_of(name)[0],)).fetchone()
        return None if found is None else dict(found)


def status_of(st, name):
    return row(st, name)["status"]


def imprint_dir(st, name):
    return st.root / ids_of(name)[1]


def state_dir(st, name):
    return st.root / f"{ids_of(name)[1]}.state"


def staging_of(st, name):
    return st.store.data_dir / "imprints" / ids_of(name)[0]


def tombstone_of(st, name):
    return st.root / "tombstones" / f"{ids_of(name)[1]}.json"


def events_of(st, name):
    return [r["record"] for r in st.store.imprint_receipts(ids_of(name)[0])]


def last_event_of(st, name):
    last = events_of(st, name)[-1]
    return last["event"], last["detail"].get("reason")


def make_files(st, name):
    folder = imprint_dir(st, name)
    folder.mkdir(mode=0o700)
    (folder / "imprint.db").write_bytes(b"package")
    (folder / "approved.json").write_text("{}")
    state_dir(st, name).mkdir(mode=0o700)
    (state_dir(st, name) / "admission.json").write_text("{}")


def make_staging(st, name):
    staging_of(st, name).mkdir(parents=True)
    (staging_of(st, name) / "request.json").write_text("{}")


def seed(st, name, status, *, files=None, end=None, permission=True, **over):
    """A row in `status` with the files that status holds (`files`: 'staging', 'imprint' or 'none'); `end` moves the
    permission's valid_until."""
    request_id, imprint_id = ids_of(name)
    request_id = seed_imprint(st, status=status, id=request_id, imprint_id=imprint_id, **over)
    if not permission or end is not None:
        with st.store.transaction() as db:
            if not permission:
                db.execute("UPDATE imprint_requests SET permission=NULL, permission_signature=NULL WHERE id=?", (request_id,))
            else:
                doc = json.loads(db.execute("SELECT permission FROM imprint_requests WHERE id=?", (request_id,)).fetchone()[0])
                doc["records"][0]["valid_until"] = end
                db.execute("UPDATE imprint_requests SET permission=? WHERE id=?",
                           (json.dumps(doc, sort_keys=True), request_id))
    if files is None:
        files = "imprint" if status in ("approved", "admitted", "deleting") else \
            "staging" if status in ("requested", "allowed", "received") else "none"
    if files == "staging":
        make_staging(st, name)
    elif files == "imprint":
        make_files(st, name)
    return request_id


def several(tmp_path, names):
    st = station(tmp_path)
    old = dict(created=NOW - 8 * DAY, expires=NOW - DAY)
    for name in names:
        if name == "admitted-past-end":
            seed(st, name, "admitted", end=NOW - 1)
        elif name == "allowed-8-days":
            seed(st, name, "allowed", **old)
        elif name == "received-8-days":
            seed(st, name, "received", **old)
        elif name == "requested-11-minutes":
            seed(st, name, "requested", permission=False, created=NOW - 660, expires=NOW - 60)
        elif name == "approved-past-end":
            seed(st, name, "approved", end=NOW - 1, decided_at=NOW - 3600)
        elif name == "admitted-live":
            seed(st, name, "admitted")
        else:
            raise KeyError(name)
    return st


def reasons(st):
    with st.store.transaction() as db:
        by_id = {r["id"]: r["delete_reason"] for r in
                 db.execute("SELECT id, delete_reason FROM imprint_requests WHERE status='deleted'")}
    return {name: by_id[ids_of(name)[0]] for name in
            ("admitted-past-end", "allowed-8-days", "received-8-days", "approved-past-end", "admitted-live")
            if ids_of(name)[0] in by_id}


def test_end_dates_and_windows_delete(tmp_path):
    st = several(tmp_path, ["admitted-past-end", "allowed-8-days", "received-8-days", "requested-11-minutes"])
    st.store.station_imprint_sweep(root=st.root)
    assert reasons(st) == {"admitted-past-end": "ended", "allowed-8-days": "upload-expired",
                           "received-8-days": "review-expired"}
    assert status_of(st, "requested-11-minutes") == "expired" and not staging_of(st, "requested-11-minutes").exists()
    names = [e["event"] for e in events_of(st, "admitted-past-end")]
    assert names[-2:] == ["ended", "deleted"] and names.count("ended") == 1
    assert not imprint_dir(st, "admitted-past-end").exists() and tombstone_of(st, "admitted-past-end").is_file()
    assert [e["event"] for e in events_of(st, "allowed-8-days")][-1] == "deleted"
    assert not staging_of(st, "allowed-8-days").exists()


def test_a_live_imprint_before_its_end_is_left_alone(tmp_path):
    st = several(tmp_path, ["admitted-live"])
    st.store.station_imprint_sweep(root=st.root)
    assert status_of(st, "admitted-live") == "admitted" and imprint_dir(st, "admitted-live").is_dir()


def test_an_approved_imprint_past_its_end_is_ended_by_the_sync(tmp_path):
    st = several(tmp_path, ["approved-past-end"])
    st.store.station_imprint_sweep(root=st.root)
    assert reasons(st) == {"approved-past-end": "ended"}
    events = events_of(st, "approved-past-end")
    assert [e["event"] for e in events if e["event"] in ("failed", "ended")] == ["failed"]
    assert [e["detail"] for e in events if e["event"] == "failed"] == [{"term": "end"}]


def test_a_failed_removal_is_retried(tmp_path, monkeypatch):
    st = several(tmp_path, ["admitted-live"])
    real, seen = imprints._unlink, []

    def unlink(path):
        if not seen:
            seen.append(path)
            raise PermissionError("busy")
        return real(path)
    monkeypatch.setattr(imprints, "_unlink", unlink)
    prefix = ids_of("admitted-live")[1][:8]
    assert st.store.station_imprint_delete("andy", prefix, root=st.root)["status"] == "deleting"
    monkeypatch.undo()
    st.store.station_imprint_sweep(root=st.root)
    assert row(st, "admitted-live")["status"] == "deleted" and row(st, "admitted-live")["delete_reason"] == "station"
    assert not imprint_dir(st, "admitted-live").exists() and tombstone_of(st, "admitted-live").is_file()


def restored(tmp_path):
    st = station(tmp_path)
    old = NOW - 3600
    seed(st, "approved-gone", "approved", files="none", decided_at=old)
    seed(st, "received-gone", "received", files="none")
    seed(st, "requested-gone", "requested", files="none", permission=False)
    seed(st, "tombstoned", "admitted", files="none")
    tombstone_of(st, "tombstoned").parent.mkdir()
    tombstone_of(st, "tombstoned").write_text("{}")
    seed(st, "orphan", "deleted", files="none", ended_at=NOW - 10, delete_reason="withdrawn")
    with st.store.transaction() as db:
        st.store._append_imprint_receipt(db, ids_of("orphan")[0], "deleted", None,
                                         {"reason": "withdrawn", "files": [], "limits": KNOWN_LIMITS}, sign=False)
    make_files(st, "orphan")
    return st


def status_reasons(st):
    return {name: (row(st, name)["status"], row(st, name)["delete_reason"] if name != "tombstoned" else None)
            for name in ("approved-gone", "received-gone", "requested-gone", "tombstoned")}


def test_restore_reconciliation(tmp_path):
    st = restored(tmp_path)
    st.store.station_imprint_sweep(root=st.root)
    assert status_reasons(st) == {"approved-gone": ("deleted", "missing"), "received-gone": ("deleted", "missing"),
                                  "requested-gone": ("expired", None), "tombstoned": ("deleted", None)}
    assert row(st, "tombstoned")["delete_reason"] == "restore"           # an unreadable tombstone: no reason of its own
    assert last_event_of(st, "tombstoned") == ("deleted", "restore")     # but a receipt in the chain (review M2)
    assert not imprint_dir(st, "orphan").exists() and not state_dir(st, "orphan").exists()
    assert last_event_of(st, "orphan") == ("deleted", "restore")
    assert last_event_of(st, "approved-gone") == ("deleted", "missing")
    assert events_of(st, "requested-gone") == []


def test_an_approved_row_whose_hand_off_is_still_running_is_not_missing(tmp_path):
    st = station(tmp_path)
    seed(st, "just-approved", "approved", files="none", decided_at=NOW - 5)
    st.store.station_imprint_sweep(root=st.root)
    assert status_of(st, "just-approved") == "approved"


def test_a_directory_that_is_not_an_imprint_is_left_alone(tmp_path):
    st = station(tmp_path)
    (st.root / "notes").mkdir()
    (st.root / "keep.txt").write_text("mine")
    st.store.station_imprint_sweep(root=st.root)
    assert (st.root / "notes").is_dir() and (st.root / "keep.txt").is_file()


def deleted_and_declined(tmp_path):
    st = station(tmp_path)
    seed(st, "declined", "declined", files="none", permission=False, ended_at=NOW)
    seed(st, "expired", "expired", files="none", permission=False, ended_at=NOW)
    seed(st, "deleted", "deleted", files="none", ended_at=NOW, delete_reason="withdrawn")
    with st.store.transaction() as db:
        st.store._append_imprint_receipt(db, ids_of("deleted")[0], "deleted", None,
                                         {"reason": "withdrawn", "files": [], "limits": KNOWN_LIMITS}, sign=False)
    tombstone_of(st, "deleted").parent.mkdir()
    tombstone_of(st, "deleted").write_text("{}")
    st.deleted_id = ids_of("deleted")[0]
    return st


def count_rows(st, table):
    with st.store.transaction() as db:
        return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_nothing_is_kept_past_its_end(tmp_path):
    st = deleted_and_declined(tmp_path)
    st.clock[0] += 30 * DAY + 1
    st.store.station_imprint_sweep(root=st.root)
    with st.store.transaction() as db:
        kept = {r[0] for r in db.execute("SELECT id FROM imprint_requests")}
        permission = db.execute("SELECT permission FROM imprint_requests WHERE id=?", (st.deleted_id,)).fetchone()[0]
    assert kept == {st.deleted_id} and permission
    assert st.store.imprint_receipts(st.deleted_id) and tombstone_of(st, "deleted").is_file()
    st.clock[0] += 370 * DAY
    st.store.station_imprint_sweep(root=st.root)
    assert count_rows(st, "imprint_requests") == count_rows(st, "imprint_receipts") == 0
    assert not list((st.root / "tombstones").iterdir())


def test_a_leftover_after_a_withdrawal_during_admission_is_removed(tmp_path):
    st = station(tmp_path)
    seed(st, "withdrawn", "deleted", files="none", ended_at=NOW - 60, delete_reason="withdrawn")
    state_dir(st, "withdrawn").mkdir()
    (state_dir(st, "withdrawn") / "result.json").write_text("{}")
    st.store.station_imprint_sweep(root=st.root)
    assert not state_dir(st, "withdrawn").exists()


def test_a_station_backup_holds_no_imprint_file_and_no_request_contents(tmp_path):
    st = received(tmp_path)
    st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    package = st.root / st.imprint_id / "imprint.db"
    package.chmod(0o600)
    canary = CANARY.encode()
    package.write_bytes(canary + package.read_bytes())
    st.store.create_room(st.ids["andy"], "Ops", [])        # the restore test wants a room to find again
    rotation = tmp_path / "rotation"
    copy = backups.run_backup(st.store.data_dir, rotation)
    raw = copy.read_bytes()
    assert [p.name for p in rotation.iterdir() if p.is_file() and p.suffix == ".sqlite3"] == [copy.name]
    assert canary not in raw and b'"scope"' not in raw and b'"contents"' not in raw
    assert backups.restore_test(rotation)["backup"] == copy


def test_the_lock_file_and_tombstones_are_never_swept(tmp_path):
    st = several(tmp_path, ["admitted-past-end"])
    lock = st.root / ".jobs.lock"
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        st.store.station_imprint_sweep(root=st.root)            # the sweep never waits for the lock
    assert lock.exists() and (st.root / "tombstones").is_dir() and tombstone_of(st, "admitted-past-end").is_file()


def test_one_failing_step_does_not_stop_the_others(tmp_path, monkeypatch):
    st = several(tmp_path, ["admitted-past-end", "requested-11-minutes"])

    def broken(*args, **kwargs):
        raise OSError("disk")
    monkeypatch.setattr(st.store, "station_imprint_sync", broken)
    result = st.store.station_imprint_sweep(root=st.root)
    assert status_of(st, "requested-11-minutes") == "expired" and status_of(st, "admitted-past-end") == "deleted"
    assert result["errors"] == ["sync"]


def test_the_command_runs_the_sweep(tmp_path, capsys):
    st = several(tmp_path, ["requested-11-minutes"])
    cli(["station-imprint-sweep", "--data-dir", str(st.store.data_dir), "--imprints-dir", str(st.root)])
    assert "Imprint sweep" in capsys.readouterr().out


def staged_copy(tmp_path, st):
    aside = tmp_path / "aside"
    aside.mkdir(mode=0o700)
    return backups.run_backup(st.store.data_dir, None, output=aside / "restored.sqlite3")


def copy_state(copy, name):
    with closing(sqlite3.connect(copy)) as db:
        status, = db.execute("SELECT status FROM imprint_requests WHERE id=?", (ids_of(name)[0],)).fetchone()
        events = [json.loads(r[0])["event"] for r in db.execute(
            "SELECT record FROM imprint_receipts WHERE request_id=? ORDER BY seq", (ids_of(name)[0],))]
    return status, events


@pytest.mark.parametrize("replaced", [False, True])
def test_a_restore_does_not_bring_a_deleted_imprint_back(tmp_path, replaced):
    st = several(tmp_path, ["admitted-live"])
    copy = staged_copy(tmp_path, st)                     # the backup: the imprint still admitted
    st.store.station_imprint_delete("andy", ids_of("admitted-live")[1][:8], root=st.root)
    backups.reconcile(copy, replaced=st.store.db_path if replaced else None)
    status, events = copy_state(copy, "admitted-live")
    assert status == "deleted" and events[-1] == "deleted"


def test_a_restore_keeps_a_removal_that_was_still_failing(tmp_path, monkeypatch):
    st = several(tmp_path, ["admitted-live"])
    copy = staged_copy(tmp_path, st)

    def refuse(path):
        raise PermissionError("busy")
    monkeypatch.setattr(imprints, "_unlink", refuse)
    st.store.station_imprint_delete("andy", ids_of("admitted-live")[1][:8], root=st.root)
    backups.reconcile(copy, replaced=st.store.db_path)
    assert copy_state(copy, "admitted-live")[0] == "deleting"


def test_a_restore_reports_what_it_held(tmp_path):
    st = several(tmp_path, ["admitted-live"])
    copy = staged_copy(tmp_path, st)
    st.store.station_imprint_delete("andy", ids_of("admitted-live")[1][:8], root=st.root)
    report = backups.reconcile(copy)
    assert report["counts"]["imprints kept deleted"] == 1
