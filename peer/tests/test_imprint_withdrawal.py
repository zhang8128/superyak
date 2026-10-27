"""Withdrawal in every status and the station's delete (spec I 12, D17; plan Task 30)."""
import json
import os
import stat
from pathlib import Path

import pytest

from superyak_peer import imprints
from superyak_peer.imprints import KNOWN_LIMITS
from imprint_support import post, request_doc, station
from test_imprint_approval import received
from test_imprint_confirm import row
from test_imprint_upload import allowed_with_all_parts


def at_status(path, status):
    """A station holding Sam's imprint for the voyager in `status`, with the files that status holds."""
    if status == "requested":
        path.mkdir(parents=True, exist_ok=True)
        st = station(path)
        made = post(st, request_doc()).json()
        st.request_id = made["id"]
    elif status == "allowed":
        st, made, _ = allowed_with_all_parts(path, nbytes=100)
        st.request_id = made["id"]
    else:
        st = received(path)
        if status != "received":
            st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
        if status == "admitted":
            with st.store.transaction() as db:
                db.execute("UPDATE imprint_requests SET status='admitted' WHERE id=?", (st.request_id,))
            state = st.root / f"{st.imprint_id}.state"
            (state / "uses").mkdir()
            (state / "report.json").write_text("{}")
            for p in sorted((st.root / st.imprint_id).iterdir()):
                p.chmod(0o400)
            (st.root / st.imprint_id).chmod(0o500)
    st.imprint_id = row(st, st.request_id)["imprint_id"]
    assert row(st, st.request_id)["status"] == status
    return st


def every_file_of(st):
    folders = (st.store.data_dir / "imprints" / st.request_id, st.root / st.imprint_id,
               st.root / f"{st.imprint_id}.state")
    return [p for folder in folders if folder.is_dir() for p in sorted(folder.rglob("*")) if p.is_file()]


def withdraw_as(st, client):
    return client.post(f"/api/imprints/{st.request_id}/withdraw")


def withdraw(st, who):
    return withdraw_as(st, st.sam if who == "owner" else st.voyager)


def receipts(st):
    return st.store.imprint_receipts(st.request_id)


def tombstone(st):
    return st.root / "tombstones" / f"{st.imprint_id}.json"


def owner_principal(st):
    return {"id": st.ids["sam"]}


def raise_once(error):
    real, seen = imprints._unlink, []

    def unlink(path):
        if not seen:
            seen.append(path)
            raise error
        return real(path)
    return unlink


@pytest.mark.parametrize("status", ["allowed", "received", "approved", "admitted"])
@pytest.mark.parametrize("who", ["owner", "ship"])
def test_withdrawal_in_every_status(tmp_path, status, who):
    st = at_status(tmp_path, status)
    files = every_file_of(st)
    assert withdraw(st, who).status_code == 200
    assert not any(p.exists() for p in files) and tombstone(st).is_file()
    deleted = receipts(st)[-1]["record"]
    assert deleted["event"] == "deleted" and deleted["detail"]["reason"] == "withdrawn"
    assert deleted["detail"]["limits"] == KNOWN_LIMITS
    assert {f["path"] for f in deleted["detail"]["files"]} == {str(p) for p in files}       # files, not directories
    assert withdraw(st, who).status_code == 200 and receipts(st)[-1]["record"]["id"] == deleted["id"]


def test_another_person_or_ship_gets_404_and_a_request_is_declined(tmp_path):
    st = at_status(tmp_path, "admitted")
    assert withdraw_as(st, st.jenn).status_code == 404 and withdraw_as(st, st.other_ship).status_code == 404
    early = at_status(tmp_path / "r", "requested"); withdraw(early, "ship")
    assert row(early, early.request_id)["status"] == "declined" and receipts(early) == []


def test_the_ship_narrows_without_editing_the_owners_records(tmp_path):
    st = at_status(tmp_path, "admitted"); before = row(st, st.request_id)["permission"]
    withdraw(st, "ship")
    assert row(st, st.request_id)["permission"] == before
    assert not st.store.station_imprint_use_decision(st.imprint_id, "trail-evaluation").allowed


def test_the_recorded_root_is_used_and_a_mismatch_is_logged(tmp_path, caplog):
    st = at_status(tmp_path, "admitted"); home_imprints = Path(os.environ["HOME"]) / ".engram" / "imprints"
    other = tmp_path / "other-root"
    st.store.withdraw_imprint(owner_principal(st), st.request_id, root=other)
    assert not (st.root / st.imprint_id).exists() and not home_imprints.exists()
    assert "imprints root mismatch" in caplog.text


def test_a_failed_removal_stays_deleting(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted"); monkeypatch.setattr(imprints, "_unlink", raise_once(PermissionError()))
    withdraw(st, "owner")
    assert row(st, st.request_id)["status"] == "deleting"
    assert receipts(st)[-1]["record"]["detail"]["error"] == "PermissionError"


def test_the_station_may_delete(tmp_path):
    st = at_status(tmp_path, "admitted")
    st.store.station_imprint_delete("andy", st.imprint_id[:4], root=st.root)
    assert receipts(st)[-1]["record"]["detail"]["reason"] == "station"


def fail_on_nth(n, error):
    real, count = imprints._unlink, []

    def unlink(path):
        count.append(path)
        if len(count) == n:
            raise error
        return real(path)
    return unlink


def test_a_retry_after_a_part_way_failure_keeps_every_hash(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted")
    before = {str(p): p for p in every_file_of(st)}
    assert len(before) >= 3
    import hashlib
    hashes = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in before.items() if p.name != "imprint.db"}
    monkeypatch.setattr(imprints, "_unlink", fail_on_nth(3, PermissionError()))
    withdraw(st, "owner")
    assert row(st, st.request_id)["status"] == "deleting"
    assert any(not p.exists() for p in before.values())      # the first attempt removed some
    monkeypatch.undo()
    assert withdraw(st, "ship").status_code == 200
    assert row(st, st.request_id)["status"] == "deleted" and tombstone(st).is_file()
    events = [r["record"]["event"] for r in receipts(st)]
    assert events.count("withdrawn") == 1 and events[-1] == "deleted"
    listed = {f["path"]: f["sha256"] for f in receipts(st)[-1]["record"]["detail"]["files"]}
    assert set(listed) == set(before)
    for k, digest in hashes.items():
        assert listed[k] == digest


def test_a_withdrawal_after_a_failed_station_delete_is_recorded(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted")
    monkeypatch.setattr(imprints, "_unlink", raise_once(PermissionError()))
    st.store.station_imprint_delete("andy", st.imprint_id[:4], root=st.root)
    assert row(st, st.request_id)["status"] == "deleting"
    assert "withdrawn" not in [r["record"]["event"] for r in receipts(st)]
    monkeypatch.undo()
    withdraw(st, "owner")
    events = [r["record"]["event"] for r in receipts(st)]
    assert events.count("withdrawn") == 1 and events[-1] == "deleted"
    held = [r["record"]["event"] for r in __import__("json").loads(tombstone(st).read_text())["receipts"]]
    assert held == ["withdrawn", "deleted"]


USE_ID = "use-1"


def current_end(st):
    found = row(st, st.request_id)
    return imprints.effective_end(json.loads(found["permission"]), [r["record"] for r in receipts(st)])


def shorten(st, who, to):
    client = st.sam if who == "owner" else st.voyager
    return client.post(f"/api/imprints/{st.request_id}/shorten", json={"valid_until": to})


def write_atomically(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    path.chmod(0o400)


def write_admission_json(st):
    write_atomically(st.root / f"{st.imprint_id}.state" / "admission.json",
                     {"decided_at": int(st.clock[0]), "valid_until": current_end(st), "kind": "admission"})


def write_allow_file(st, use_id):
    write_atomically(st.root / f"{st.imprint_id}.state" / "uses" / f"{use_id}.allow.json",
                     {"use": use_id, "valid_until": current_end(st)})


def allow_files(st):
    state = st.root / f"{st.imprint_id}.state"
    return [state / "admission.json", *sorted((state / "uses").glob("*.allow.json"))]


def original_permission(st):
    return st.original_permission


def test_shortening_narrows_only(tmp_path):
    st = at_status(tmp_path, "admitted"); end = current_end(st)
    for bad in (end, end + 1, st.clock[0] - 1, st.clock[0]):
        assert shorten(st, "owner", bad).status_code == 400
    assert shorten(st, "ship", end - 100).status_code == 200 and current_end(st) == end - 100
    assert shorten(st, "owner", end - 50).status_code == 400              # later than the effective end now


def test_shortening_replaces_admission_json_and_allow_files_atomically(tmp_path):
    st = at_status(tmp_path, "approved"); st.original_permission = row(st, st.request_id)["permission"]
    write_admission_json(st); write_allow_file(st, USE_ID)
    inodes = {p: p.stat().st_ino for p in allow_files(st)}
    docs = {p: json.loads(p.read_text()) for p in allow_files(st)}
    assert shorten(st, "ship", current_end(st) - 100).status_code == 200
    for p in allow_files(st):
        doc = json.loads(p.read_text())                         # only valid_until moves; decided_at stays (R24)
        assert doc == {**docs[p], "valid_until": current_end(st)} and p.stat().st_ino != inodes[p] and stat.S_IMODE(p.stat().st_mode) == 0o400
    assert row(st, st.request_id)["permission"] == original_permission(st)


# ---- A removal and its receipt are crash-consistent (final review M1; logged item 2) ----

def hashes_of(st):
    import hashlib
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in every_file_of(st) if p.name != "imprint.db"}


def committed_status(st):
    """The row's status as another connection sees it: what is committed, not what a transaction holds."""
    import sqlite3
    with sqlite3.connect(st.store.db_path) as raw:
        return raw.execute("SELECT status FROM imprint_requests WHERE id=?", (st.request_id,)).fetchone()[0]


def test_a_failing_tombstone_leaves_deleting_with_a_receipt_and_the_retry_keeps_every_hash(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted"); hashes = hashes_of(st); paths = {str(p) for p in every_file_of(st)}
    real = imprints.Imprints._write_tombstone
    monkeypatch.setattr(imprints.Imprints, "_write_tombstone", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "full")))
    assert st.store.withdraw_imprint(owner_principal(st), st.request_id, root=st.root)["status"] == "deleting"
    assert row(st, st.request_id)["status"] == "deleting" and not any(os.path.exists(p) for p in paths)
    failed = receipts(st)[-1]["record"]
    assert (failed["event"], failed["detail"]["error"]) == ("delete-failed", "OSError")
    assert failed["detail"]["path"] == str(tombstone(st))
    monkeypatch.setattr(imprints.Imprints, "_write_tombstone", real)
    assert st.store.withdraw_imprint(owner_principal(st), st.request_id, root=st.root)["status"] == "deleted"
    listed = {f["path"]: f["sha256"] for f in receipts(st)[-1]["record"]["detail"]["files"]}
    assert set(listed) == paths and all(listed[k] == v for k, v in hashes.items()) and tombstone(st).is_file()


def test_a_commit_lost_after_the_removal_keeps_every_hash_on_the_retry(tmp_path, monkeypatch):
    st = at_status(tmp_path, "admitted"); hashes = hashes_of(st); paths = {str(p) for p in every_file_of(st)}
    real = imprints.Imprints._write_tombstone

    def crash(*args, **kwargs):                 # anything that rolls the last transaction back: a crash, a full disk
        raise RuntimeError("lost")
    monkeypatch.setattr(imprints.Imprints, "_write_tombstone", crash)
    with pytest.raises(RuntimeError):
        st.store.withdraw_imprint(owner_principal(st), st.request_id, root=st.root)
    assert not any(os.path.exists(p) for p in paths) and "deleted" not in [r["record"]["event"] for r in receipts(st)]
    monkeypatch.setattr(imprints.Imprints, "_write_tombstone", real)
    assert st.store.withdraw_imprint(owner_principal(st), st.request_id, root=st.root)["status"] == "deleted"
    listed = {f["path"]: f["sha256"] for f in receipts(st)[-1]["record"]["detail"]["files"]}
    assert set(listed) == paths and all(listed[k] == v for k, v in hashes.items())


def test_a_denial_removes_the_staged_bytes_only_after_its_receipts_are_committed(tmp_path, monkeypatch):
    st = at_status(tmp_path, "received"); staged = st.store.data_dir / "imprints" / st.request_id
    seen, real = [], imprints.shutil.rmtree

    def rmtree(path, *args, **kwargs):
        if Path(path) == staged:
            seen.append(committed_status(st))
        return real(path, *args, **kwargs)
    monkeypatch.setattr(imprints.shutil, "rmtree", rmtree)
    st.store.station_decide("andy", st.request_id[:4], False, imprints_root=st.root)
    assert seen == ["deleted"] and not staged.exists()


def test_a_denial_that_crashed_before_its_removal_is_finished_by_the_sweep(tmp_path, monkeypatch):
    st = at_status(tmp_path, "received"); staged = st.store.data_dir / "imprints" / st.request_id
    real = imprints.shutil.rmtree

    def crash(path, *args, **kwargs):
        if Path(path) == staged:
            raise OSError("the process died here")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(imprints.shutil, "rmtree", crash)
    st.store.station_decide("andy", st.request_id[:4], False, imprints_root=st.root)
    assert row(st, st.request_id)["status"] == "deleted" and staged.is_dir()
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["denied", "deleted"]
    monkeypatch.undo()
    st.store.station_imprint_sweep(root=st.root)
    assert not staged.exists() and [r["record"]["event"] for r in receipts(st)][-1] == "deleted"


def test_a_station_made_before_removal_files_gains_the_column(tmp_path):
    import sqlite3
    from superyak_peer.db import Store
    tmp_path.mkdir(exist_ok=True)
    with sqlite3.connect(tmp_path / "peer.sqlite3") as raw:          # the imprint tables as this branch first made them
        raw.execute("CREATE TABLE imprint_requests(id TEXT PRIMARY KEY, imprint_id TEXT UNIQUE NOT NULL, ship_id TEXT "
                    "NOT NULL, owner_id TEXT NOT NULL, status TEXT NOT NULL, code_hash TEXT, created INTEGER NOT NULL, "
                    "expires INTEGER NOT NULL, decided_at INTEGER, decided_by TEXT, ended_at INTEGER, request_sha256 "
                    "TEXT NOT NULL, source_instance_id TEXT NOT NULL, imprints_root TEXT, permission TEXT, "
                    "permission_signature TEXT, station_key TEXT, delete_reason TEXT)")
    Store(tmp_path, signing=False)
    with sqlite3.connect(tmp_path / "peer.sqlite3") as raw:
        assert "removal_files" in {r[1] for r in raw.execute("PRAGMA table_info(imprint_requests)")}


# ---- A tombstone found by the sweep leaves its receipts in the chain (final review M2; logged item 3b) ----

def test_a_tombstone_found_by_the_sweep_puts_its_receipts_in_the_chain_and_sets_the_reason(tmp_path):
    st = at_status(tmp_path, "admitted")
    assert withdraw(st, "owner").status_code == 200
    held = [r["record"]["id"] for r in __import__("json").loads(tombstone(st).read_text())["receipts"]]
    with st.store.transaction() as db:                 # a restore from before the withdrawal: the row is live again
        db.execute("DELETE FROM imprint_receipts WHERE request_id=? AND json_extract(record, '$.event') IN "
                   "('withdrawn', 'deleted')", (st.request_id,))
        db.execute("UPDATE imprint_requests SET status='admitted', ended_at=NULL, delete_reason=NULL WHERE id=?",
                   (st.request_id,))
    st.store.station_imprint_sweep(root=st.root)
    found = row(st, st.request_id)
    assert (found["status"], found["delete_reason"]) == ("deleted", "withdrawn")
    chain = receipts(st)
    assert [r["record"]["id"] for r in chain][-2:] == held
    assert chain[-1]["record"]["event"] == "deleted" and chain[-1]["signature"]      # the tombstone's, as signed


def test_an_unreadable_tombstone_still_closes_the_row_with_a_deleted_receipt(tmp_path):
    st = at_status(tmp_path, "admitted")
    tombstone(st).parent.mkdir(exist_ok=True); tombstone(st).write_text("{}")
    st.store.station_imprint_sweep(root=st.root)
    found = row(st, st.request_id)
    assert (found["status"], found["delete_reason"]) == ("deleted", "restore")
    last = receipts(st)[-1]["record"]
    assert (last["event"], last["detail"]["reason"]) == ("deleted", "restore")
