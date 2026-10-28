"""Imprint tables, receipts and their chain (store-copy spec I 12, D19; plan Task 23, R2, R25)."""
import subprocess
import sys
from pathlib import Path

import pytest

from imprint_support import only_signed_imprint_record, permission_of, seed_imprint, sha256_canonical, station
from superyak_peer.db import Store

PEER = Path(__file__).resolve().parent.parent
CHILD = '''
import sys
from superyak_peer.db import Store
store = Store(sys.argv[1], signing=False)
for _ in range(int(sys.argv[3])):
    with store.transaction() as db:
        store._append_imprint_receipt(db, sys.argv[2], "refused", None,
                                      {"use": "u", "actions": ["read"], "purpose": "calibration", "term": "t"}, sign=False)
'''


def run_in_two_processes(data_dir, request_id, each):
    children = [subprocess.Popen([sys.executable, '-c', CHILD, str(data_dir), request_id, str(each)], cwd=PEER)
                for _ in range(2)]
    assert [child.wait(timeout=300) for child in children] == [0, 0]


def table_columns(store, table):
    with store.transaction() as db:
        return {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}


def test_receipts_chain_from_the_permission(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="received")
    with st.store.transaction() as db:
        a = st.store._append_imprint_receipt(db, rid, "approved", st.andy_id, {}, sign=False)
        b = st.store._append_imprint_receipt(db, rid, "failed", None, {"step": 2, "message": "m"}, sign=False)
    assert a["previous"] == sha256_canonical(permission_of(st, rid)) and b["previous"] == sha256_canonical(a)
    assert [r["signature"] for r in st.store.imprint_receipts(rid)] == [None, None]


def test_two_processes_appending_at_once_keep_one_chain(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="admitted")
    run_in_two_processes(tmp_path / "peer", rid, each=40)    # Store(signing=False) in each, appending "refused"
    chain = st.store.imprint_receipts(rid)
    assert len(chain) == 80 and all(r2["record"]["previous"] == sha256_canonical(r1["record"]) for r1, r2 in zip(chain, chain[1:]))


def test_a_receipt_holds_no_detail_its_event_does_not_name(tmp_path):
    st = station(tmp_path); rid = seed_imprint(st, status="admitted")
    for event, bad in [("refused", {"content": "x"}), ("refused", {"query": "who"}), ("refused", {"memory_ids": ["e1"]}),
                       ("failed", {"check": 2, "message": "m"}), ("failed", {"step": 2, "term": "end"})]:
        with pytest.raises(ValueError), st.store.transaction() as db:
            st.store._append_imprint_receipt(db, rid, event, None, bad, sign=False)
    assert st.store.imprint_receipts(rid) == []


def test_the_request_row_holds_no_scope_counts_or_terms(tmp_path):
    columns = table_columns(station(tmp_path).store, "imprint_requests")
    assert not columns & {"scope", "contents", "terms", "lanes", "layers", "since", "until", "episodes"}


@pytest.mark.parametrize("signed", ["permission", "receipt"])
def test_a_lost_identity_is_refused_while_an_imprint_record_is_signed(tmp_path, signed):
    st = station(tmp_path); only_signed_imprint_record(st, signed)    # no grant or revision signature on this station
    (st.store.data_dir / "identity.json").unlink()
    with pytest.raises(ValueError, match="identity.json.*station-new-identity"):
        Store(st.store.data_dir)                                     # as test_signatures.py's G4b test 4b does
    Store(st.store.data_dir, signing=False)


def test_a_signed_receipt_verifies_and_every_allowed_detail_is_accepted(tmp_path):
    from superyak_peer.identity import verify_station_record
    from superyak_peer.imprints import DETAIL_KEYS, EVENTS
    import base64
    st = station(tmp_path); rid = seed_imprint(st, status="admitted")
    assert set(DETAIL_KEYS) == set(EVENTS)
    with st.store.transaction() as db:
        for event, sets in DETAIL_KEYS.items():
            for keys in sets:
                st.store._append_imprint_receipt(db, rid, event, None, {k: 1 for k in keys}, sign=(event == "approved"))
        key = base64.b64encode(st.store._station_identity(db).public_key).decode()
    chain = st.store.imprint_receipts(rid)
    assert sum(len(s) for s in DETAIL_KEYS.values()) == len(chain)
    first = next(r for r in chain if r["record"]["event"] == "approved")
    assert verify_station_record(key, first["record"], first["signature"])


# Task 41: the lighthouse signs the receipts a key-less command wrote (I 12, D19)

import json
import time

from fastapi.testclient import TestClient

from superyak_peer import imprints
from superyak_peer.app import create_app
from superyak_peer.identity import verify_station_record
from test_imprint_admission import approved, begin, receipts, row as request_row_of, state_of, write_result


def admitted_keyless(tmp_path):
    """Sam's imprint admitted by Store(signing=False), so its `approved` and `admitted` receipts are unsigned; the
    calibration report sits where admission leaves it."""
    st = approved(tmp_path)
    begin(st)
    write_result(st, status="admitted")
    (state_of(st) / "calibration").mkdir()
    (state_of(st) / "calibration" / "report.json").write_text(json.dumps({"analyses": {"recall": {"n": 3}}}))
    Store(st.store.data_dir, signing=False).station_imprint_sync(root=st.root)
    assert request_row_of(st)["status"] == "admitted"
    return st


def lighthouse_app(tmp_path):
    return create_app(tmp_path / "peer", allowed_origins=["http://testserver"], imprints_dir=tmp_path / "imprints")


def unsigned_count(tmp_path):
    store = Store(tmp_path / "peer", signing=False)
    with store.transaction() as db:
        return db.execute("SELECT COUNT(*) FROM imprint_receipts WHERE signature IS NULL").fetchone()[0]


def wait_until(check, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.02)
    assert check()


def station_key(st):
    return request_row_of(st)["station_key"]


def last_receipt_with_signature(st):
    last = st.store.imprint_receipts(st.request_id)[-1]
    return last["record"], last["signature"]


def describe_station_imprints(st):
    return "\n".join(item["line"] for item in st.store.station_imprints(root=st.root))


def has_key(value, key):
    if isinstance(value, dict):
        return key in value or any(has_key(v, key) for v in value.values())
    return isinstance(value, list) and any(has_key(v, key) for v in value)


def fail_first(calls, error):
    def sign(self):
        calls.append(1)
        if len(calls) == 1:
            raise error
        return 0
    return sign


def test_a_receipt_from_a_keyless_command_is_signed_within_the_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(imprints, "SIGN_INTERVAL", 0.05)
    st = admitted_keyless(tmp_path)
    assert unsigned_count(tmp_path) > 0
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver"):
        wait_until(lambda: unsigned_count(tmp_path) == 0, seconds=2)
    assert verify_station_record(station_key(st), *last_receipt_with_signature(st))


def test_receipts_wait_while_the_lighthouse_is_down_and_are_signed_at_its_start(tmp_path):
    st = admitted_keyless(tmp_path)
    assert "receipts not yet signed" in describe_station_imprints(st)
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver"):
        pass
    assert unsigned_count(tmp_path) == 0 and "receipts signed" in describe_station_imprints(st)


def test_an_imprint_read_signs_first(tmp_path):
    st = admitted_keyless(tmp_path)
    body = st.voyager.get(f"/api/imprints/{st.request_id}").json()
    assert body["status"] == "admitted" and all(r["signature"] for r in body["receipts"])
    assert body["permission"]["record"]["id"] == st.request_id and body["permission"]["signature"]
    assert body["permission"]["station_key"] == station_key(st)
    assert body["calibration_report"] == {"analyses": {"recall": {"n": 3}}} and body["use_reports"] == []
    assert not has_key(body["calibration_report"], "content") and "400 days after" in body["keeps"]["text"]
    assert set(body["keeps"]["removed_on"]) == {"row", "permission", "receipts", "tombstone"}
    listed = st.sam.get("/api/imprints").json()
    assert listed["imprints"] and unsigned_count(tmp_path) == 0


def test_the_lighthouses_own_receipts_are_signed_when_written(tmp_path):
    st = admitted_keyless(tmp_path)
    assert st.voyager.post(f"/api/imprints/{st.request_id}/withdraw").status_code == 200
    by_event = {r["record"]["event"]: r["signature"] for r in receipts(st)}
    assert by_event["withdrawn"] and by_event["deleted"]


def test_a_signing_error_is_logged_and_the_loop_goes_on(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(imprints, "SIGN_INTERVAL", 0.05); calls = []
    monkeypatch.setattr(Store, "sign_imprint_receipts", fail_first(calls, ValueError("identity.json is missing")))
    with TestClient(lighthouse_app(tmp_path), base_url="http://testserver") as client:
        wait_until(lambda: len(calls) >= 2, seconds=2)               # it ran again after the error
        assert client.get("/api/health").status_code == 200
    assert "ValueError" in caplog.text


def test_a_read_answers_with_unsigned_receipts_when_signing_fails(tmp_path, monkeypatch):
    st = admitted_keyless(tmp_path)
    monkeypatch.setattr(Store, "sign_imprint_receipts", fail_first([], RuntimeError("boom")))
    body = st.voyager.get(f"/api/imprints/{st.request_id}")
    assert body.status_code == 200 and any(r["signature"] is None for r in body.json()["receipts"])
