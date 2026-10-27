"""Withdrawal in every status and the station's delete (spec I 12, D17; plan Task 30)."""
import os
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
