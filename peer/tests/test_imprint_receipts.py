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
