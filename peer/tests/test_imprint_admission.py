"""Admission runs on the station: the decision again at each run, the sync that records results, the listing
(spec I 10, D16, D39, R24, R25; plan Task 36)."""
import json
import os
import stat

import pytest

from superyak_peer import imprints
from superyak_peer.__main__ import main as cli
from superyak_peer.common import Problem
from superyak_peer.imprints import ADMISSION_BOUND, ADMISSION_STOPPED
from imprint_support import ship_shortens
from test_imprint_confirm import row as request_row
from test_imprint_upload import allowed_with_all_parts

CHECK_13 = "Check 13: the package does not match its manifest."


def approved(tmp_path, route=False):
    """A station holding Sam's imprint in status `approved` (through `station_decide`), without a state result."""
    st, made, _ = allowed_with_all_parts(tmp_path, nbytes=100, route=route)
    assert st.voyager.post(f"/api/imprints/{made['id']}/complete").json()["status"] == "received"
    st.request_id = made["id"]
    st.imprint_id = request_row(st, made["id"])["imprint_id"]
    st.store.station_decide("andy", st.request_id[:4], True, imprints_root=st.root)
    assert row(st)["status"] == "approved"
    return st


def row(st):
    return request_row(st, st.request_id)


def receipts(st):
    return st.store.imprint_receipts(st.request_id)


def state_of(st):
    return st.root / f"{st.imprint_id}.state"


def begin(st):
    out = st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")
    assert out["allowed"] is True, out
    return out


def admission_json_bytes(st):
    return (state_of(st) / "admission.json").read_bytes()


def decided_at_of(st):
    return json.loads(admission_json_bytes(st))["decided_at"]


def effective_end_of(st):
    return imprints.effective_end(json.loads(row(st)["permission"]), [r["record"] for r in receipts(st)])


def write_result(st, *, status, **fields):
    doc = {"status": status, "ended_at": int(st.clock[0])}
    if status == "admitted":
        doc |= {"checks": 17, "report_sha256": "ab" * 32, "skipped": [], "roads_and_trails": 0, "sessions_too_large": 0}
    doc |= fields
    (state_of(st) / "result.json").write_text(json.dumps(doc))


def withdraw(st, who):
    client = st.sam if who == "owner" else st.voyager
    assert client.post(f"/api/imprints/{st.request_id}/withdraw").status_code == 200


def leftover_result(st):
    state_of(st).mkdir(exist_ok=True)
    (state_of(st) / "result.json").write_text(json.dumps({"status": "admitted", "checks": 17,
        "report_sha256": "ab" * 32, "skipped": [], "roads_and_trails": 0, "sessions_too_large": 0}))


def events(st):
    return [r["record"]["event"] for r in receipts(st)]


def test_admission_after_the_end_is_refused_and_deleted_before_any_sweep(tmp_path):
    st = approved(tmp_path); st.clock[0] = effective_end_of(st) + 1
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")["allowed"] is False
    assert not (st.root / f"{st.imprint_id}.state" / "admission.json").exists()
    st.store.station_imprint_sync(root=st.root)
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["failed", "deleted"]
    assert receipts(st)[-2]["record"]["detail"]["term"] == "end" and receipts(st)[-1]["record"]["detail"]["reason"] == "ended"


def test_the_same_when_the_ship_shortened_to_a_time_that_passed(tmp_path):
    st = approved(tmp_path); ship_shortens(st, to=st.clock[0] + 5); st.clock[0] += 10
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")["term"] == "end"


def test_sync_records_an_admitted_result_with_its_count(tmp_path):
    st = approved(tmp_path, route=True); begin(st)
    write_result(st, status="admitted", roads_and_trails=150_000, sessions_too_large=2)
    st.store.station_imprint_sync(root=st.root)
    admitted = receipts(st)[-1]["record"]
    assert admitted["event"] == "admitted" and admitted["detail"]["roads_and_trails"] == 150_000 and row(st)["status"] == "admitted"
    assert admitted["detail"]["sessions_too_large"] == 2                                   # the re-check's S4
    shown, = [r for r in st.store.station_imprints(root=st.root) if r["imprint_id"] == st.imprint_id]
    assert (shown["roads_and_trails"], shown["sessions_too_large"]) == (150_000, 2)


def test_sync_never_moves_a_withdrawn_imprint_to_admitted(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="admitted", roads_and_trails=0)
    withdraw(st, "owner"); leftover_result(st)                    # a write that landed after the removal
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "deleted" and "admitted" not in [r["record"]["event"] for r in receipts(st)]


def test_a_failed_result_deletes_the_package(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="failed", step=13, message=CHECK_13)
    st.store.station_imprint_sync(root=st.root)
    assert [r["record"]["event"] for r in receipts(st)][-2:] == ["failed", "deleted"] and not (st.root / st.imprint_id).exists()
    assert receipts(st)[-2]["record"]["detail"] == {"step": 13, "message": CHECK_13}


def test_ended_during_admission_writes_failed_then_deleted(tmp_path):
    st = approved(tmp_path); begin(st)                       # imprint.py admit then exits 5 and writes no result
    st.clock[0] = effective_end_of(st) + 1; st.store.station_imprint_sync(root=st.root)
    failed, deleted = [r["record"] for r in receipts(st)][-2:]
    assert (failed["event"], failed["detail"]) == ("failed", {"term": "end"})
    assert (deleted["event"], deleted["detail"]["reason"], row(st)["status"]) == ("deleted", "ended", "deleted")


def test_a_begun_admission_with_no_result_fails_once_its_bound_passes(tmp_path):
    st = approved(tmp_path); begin(st)                       # the unit was killed at MemoryMax or RuntimeMaxSec
    st.clock[0] = decided_at_of(st) + ADMISSION_BOUND; st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "approved"                    # the unit may still be stopping
    st.clock[0] += 1; st.store.station_imprint_sync(root=st.root)
    failed, deleted = [r["record"] for r in receipts(st)][-2:]
    assert (failed["event"], failed["detail"]) == ("failed", {"step": "calibration", "message": ADMISSION_STOPPED})
    assert (deleted["event"], deleted["detail"]["reason"]) == ("deleted", "failed") and not (st.root / st.imprint_id).exists()


def test_only_an_admission_never_begun_awaits_and_a_begun_one_never_begins_again(tmp_path):
    st = approved(tmp_path)
    assert [r["imprint_id"] for r in st.store.station_imprints(root=st.root, awaiting=True)] == [st.imprint_id]
    begin(st); before = admission_json_bytes(st); events_before = [r["record"]["event"] for r in receipts(st)]
    assert st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy") == {"allowed": False, "begun": True}
    assert admission_json_bytes(st) == before and [r["record"]["event"] for r in receipts(st)] == events_before
    assert st.store.station_imprints(root=st.root, awaiting=True) == []


# Added by the task: what the brief's eight tests leave open.

def test_admission_json_is_0400_with_the_stores_clock_and_the_effective_end(tmp_path):
    st = approved(tmp_path); out = begin(st)
    path = state_of(st) / "admission.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert json.loads(path.read_text()) == {"kind": "imprint-admission-allow", "instance_id": st.imprint_id,
                                            "decided_at": int(st.clock[0]), "valid_until": effective_end_of(st)}
    assert out["valid_until"] == effective_end_of(st)


def test_a_refused_begin_for_a_row_that_is_not_approved_writes_no_receipt(tmp_path):
    st = approved(tmp_path); withdraw(st, "owner"); before = events(st)
    out = st.store.station_imprint_admit_begin(st.imprint_id, root=st.root, operator="andy")
    assert out["allowed"] is False and out["term"] == "status" and events(st) == before
    with pytest.raises(Problem):
        st.store.station_imprint_admit_begin("no-such-imprint", root=st.root, operator="andy")


def test_a_refusal_at_a_run_start_for_another_term_deletes_as_failed(tmp_path):
    st = approved(tmp_path)
    with st.store.transaction() as db:                       # the effective end is not what refuses here: a withdrawal
        st.store._append_imprint_receipt(db, st.request_id, "failed", None, {"term": "ceiling"}, sign=False)
    st.store.station_imprint_sync(root=st.root)
    assert events(st)[-2:] == ["failed", "deleted"] and receipts(st)[-1]["record"]["detail"]["reason"] == "failed"


def test_a_sync_run_twice_writes_nothing_more_and_a_waiting_admission_waits(tmp_path):
    st = approved(tmp_path); begin(st)
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "approved" and events(st)[-1] == "approved"
    write_result(st, status="failed", step=13, message=CHECK_13)
    st.store.station_imprint_sync(root=st.root); st.store.station_imprint_sync(root=st.root)
    assert events(st).count("failed") == 1 and events(st).count("deleted") == 1


def test_a_malformed_result_is_not_taken_as_a_result(tmp_path):
    st = approved(tmp_path); begin(st)
    (state_of(st) / "result.json").write_text('{"status": "admitted", "roads_and_trails": "many"}')
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "approved"


def test_the_listing_says_what_admission_found(tmp_path):
    st = approved(tmp_path, route=True)
    shown, = st.store.station_imprints(root=st.root)
    assert "waiting: not begun" in shown["line"] and "receipts not yet signed" in shown["line"]
    begin(st); write_result(st, status="admitted", roads_and_trails=412, sessions_too_large=2)
    st.store.station_imprint_sync(root=st.root)
    shown, = st.store.station_imprints(root=st.root)
    assert "admitted" in shown["line"] and "412 roads and trails counted" in shown["line"]
    assert "(2 sessions too large to count)" in shown["line"]
    st.sam.get("/api/imprints")                              # nothing to sign here: the lighthouse signs, not the sync


def test_the_listing_leaves_out_a_count_without_route(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="admitted")
    st.store.station_imprint_sync(root=st.root)
    shown, = st.store.station_imprints(root=st.root)
    assert "roads and trails" not in shown["line"] and "sessions too large" not in shown["line"]


def test_the_commands(tmp_path, capsys):
    st = approved(tmp_path)
    base = ["--data-dir", str(st.store.data_dir), "--imprints-dir", str(st.root)]
    cli(["station-imprints", "--resolve", st.imprint_id[:4], *base])
    assert capsys.readouterr().out.strip() == st.imprint_id
    cli(["station-imprints", "--awaiting-admission", *base])
    assert capsys.readouterr().out.split() == [st.imprint_id]
    with pytest.raises(SystemExit) as stopped:
        cli(["station-imprints", "--resolve", "ffff", *base])
    assert stopped.value.code == 2
    cli(["station-imprint-admit-begin", "--id", st.imprint_id, "--as", "andy", *base])
    assert (state_of(st) / "admission.json").exists()
    with pytest.raises(SystemExit) as stopped:
        cli(["station-imprint-admit-begin", "--id", st.imprint_id, "--as", "andy", *base])
    assert stopped.value.code == 3
    cli(["station-imprint-sync", *base])
    cli(["station-imprints", *base])
    assert st.imprint_id[:4] in capsys.readouterr().out


# ---- `skipped` names kinds, never a memory (final review I1; spec section 12) ----

SKIPS_OK = [{"set": "lane:work", "n": 16_001, "bound": 16_000}, {"set": "core", "n": 16_001, "bound": 16_000},
            {"set": "hub", "n": 1_025, "bound": 1_024}, {"set": "cohesion", "n": 1_025, "bound": 1_024},
            {"set": "event", "n": 1_025, "bound": 1_024}]


def test_an_admitted_receipt_carries_content_free_skips(tmp_path):
    st = approved(tmp_path); begin(st); write_result(st, status="admitted", skipped=SKIPS_OK)
    st.store.station_imprint_sync(root=st.root)
    assert receipts(st)[-1]["record"]["detail"]["skipped"] == SKIPS_OK and row(st)["status"] == "admitted"


@pytest.mark.parametrize("skip", [
    {"set": "hub:0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d", "n": 1_025, "bound": 1_024},
    {"set": "cohesion:0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d", "n": 1_025, "bound": 1_024},
    {"set": "event:ev1", "n": 1_025, "bound": 1_024},
    {"set": "lane:jenn", "n": 1, "bound": 0},
    {"set": "hub", "n": 1_025, "bound": 1_024, "id": "s1"},
    {"set": "hub", "n": "1025", "bound": 1_024},
    {"set": "hub", "n": True, "bound": 1_024},
    "hub",
])
def test_a_result_whose_skips_could_name_a_memory_is_not_a_result(tmp_path, skip):
    st = approved(tmp_path); begin(st); write_result(st, status="admitted", skipped=[skip])
    assert imprints._read_result(state_of(st) / "result.json") is None
    st.store.station_imprint_sync(root=st.root)
    assert "admitted" not in events(st) and row(st)["status"] == "approved"
