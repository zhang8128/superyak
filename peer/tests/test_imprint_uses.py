"""A use begins on the station: decided, given a uuid4, a use-started receipt and an allow file (spec I 12, D41, R23;
plan Task 37)."""
import json
import re
import stat
from types import SimpleNamespace

import pytest

from superyak_peer.__main__ import main as cli
from superyak_peer.identity import canonical
from imprint_support import NOW, seed_imprint
from test_imprint_admission import effective_end_of, approved, begin, receipts, row, state_of, write_result

USE_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ALLOW_KEYS = {"kind", "use_id", "instance_id", "use", "actions", "purpose", "requester", "acting_for", "place",
              "records", "decided_at", "valid_until"}


def admitted(tmp_path, route=True, n=4):
    """A station holding Sam's imprint in status `admitted`, with N roads and trails in its `admitted` receipt."""
    st = approved(tmp_path, route=route)
    begin(st)
    write_result(st, status="admitted", roads_and_trails=n if route else 0)
    st.store.station_imprint_sync(root=st.root)
    assert row(st)["status"] == "admitted"
    contents = json.loads((st.root / st.imprint_id / "manifest.json").read_text())["contents"]
    st.count = contents.get("episodes", 0) + contents.get("semantics", 0)
    return st


def lets_sam_route(st):
    """A second live imprint of Sam's that allows route, so his layer permits it while the first copy's ceiling doesn't."""
    other = seed_imprint(st, status="admitted", id="b" * 32, imprint_id="feed0001",
                         source_instance_id=row(st)["source_instance_id"])
    with st.store.transaction() as db:
        permission = json.loads(db.execute("SELECT permission FROM imprint_requests WHERE id=?", (other,)).fetchone()[0])
        selector = permission["records"][0]["selector"]
        selector["actions"] = ["imprint", "read", "recall", "route"]
        selector["purposes"] = ["calibration", "trail-evaluation"]
        selector["objects"]["kinds"] = ["memory", "road", "trail"]
        db.execute("UPDATE imprint_requests SET permission=? WHERE id=?", (canonical(permission).decode(), other))


def admitted_with_fault(tmp_path, fault):
    if fault == "not_admitted":
        return approved(tmp_path, route=True)
    st = admitted(tmp_path, route=fault != "no_route", n=4)
    if fault == "withdrawn":
        with st.store.transaction() as db:
            st.store._append_imprint_receipt(db, st.request_id, "withdrawn", st.ids["sam"], {}, sign=False)
    elif fault == "ended":
        st.clock[0] = effective_end_of(st) + 1
    elif fault == "no_route":
        lets_sam_route(st)
    return st


def operator_for(fault):
    return "jenn" if fault == "other_operator" else "andy"


def run_peer_cli(st, argv):
    base = ["--data-dir", str(st.store.data_dir), "--imprints-dir", str(st.root)]
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli([*argv, *base])
        except SystemExit as stopped:
            code = stopped.code or 0
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def test_an_allowed_use_writes_its_receipt_then_its_allow_file(tmp_path):
    st = admitted(tmp_path, route=True, n=4)
    out = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    path = st.root / f"{st.imprint_id}.state" / "uses" / f"{out['use_id']}.allow.json"
    allow = json.loads(path.read_text())
    assert USE_ID.fullmatch(out["use_id"]) and set(allow) == ALLOW_KEYS and allow["actions"] == ["read", "recall", "route"]
    assert (allow["requester"], allow["acting_for"], allow["place"]) == ("agent:station-imprints", "person:andy", "place:home/andy")
    started = receipts(st)[-1]["record"]
    assert started["event"] == "use-started" and started["detail"]["objects"] == {"imprint": st.imprint_id, "count": st.count, "roads_and_trails": 4}
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert (allow["kind"], allow["use_id"], allow["instance_id"], allow["use"], allow["purpose"]) == (
        "imprint-use-allow", out["use_id"], st.imprint_id, "trail-evaluation", "trail-evaluation")
    assert allow["decided_at"] == NOW and allow["valid_until"] == effective_end_of(st) and allow["records"]
    assert started["detail"] == {"use": "trail-evaluation", "use_id": out["use_id"], "actions": ["read", "recall", "route"],
                                 "purpose": "trail-evaluation", "objects": started["detail"]["objects"]}


@pytest.mark.parametrize("fault,term", [("not_admitted", "status"), ("withdrawn", "withdrawal"), ("ended", "end"),
                                        ("other_operator", "audience"), ("no_route", "ceiling")])
def test_a_refused_use_writes_a_refused_receipt_and_nothing_else(tmp_path, fault, term):
    st = admitted_with_fault(tmp_path, fault)
    out = st.store.station_imprint_use_begin(operator_for(fault), st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert out == {"allowed": False, "term": term} and not list((st.root / f"{st.imprint_id}.state").glob("uses/*"))
    assert receipts(st)[-1]["record"]["event"] == "refused" and receipts(st)[-1]["record"]["detail"]["term"] == term


def test_the_command_prints_only_the_use_id(tmp_path):
    st = admitted(tmp_path, route=True, n=0)
    done = run_peer_cli(st, ["station-imprint-use-begin", "--id", st.imprint_id[:4], "--use", "trail-evaluation", "--as", "andy"])
    assert done.returncode == 0 and USE_ID.fullmatch(done.stdout.strip()) and len(done.stdout.splitlines()) == 1


# Added by the task: what the brief's seven tests leave open.

def test_the_command_exits_3_when_refused_and_prints_no_use_id(tmp_path):
    st = admitted(tmp_path, route=True, n=1)               # the command runs on the real clock, so refuse by audience
    done = run_peer_cli(st, ["station-imprint-use-begin", "--id", st.imprint_id[:4], "--use", "trail-evaluation", "--as", "jenn"])
    assert done.returncode == 3 and done.stdout == "" and "audience" in done.stderr


def test_a_refused_receipt_after_admission_carries_the_count_and_before_it_does_not(tmp_path):
    st = admitted_with_fault(tmp_path, "withdrawn")
    st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert receipts(st)[-1]["record"]["detail"] == {"use": "trail-evaluation", "actions": ["read", "recall", "route"],
                                                    "purpose": "trail-evaluation", "term": "withdrawal", "roads_and_trails": 4}
    st = admitted_with_fault(tmp_path / "again", "not_admitted")
    st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert "roads_and_trails" not in receipts(st)[-1]["record"]["detail"]


def test_two_uses_get_two_ids_and_a_removed_state_directory_is_never_recreated(tmp_path):
    st = admitted(tmp_path, route=True, n=1)
    a = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    b = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert a["use_id"] != b["use_id"] and len(list((state_of(st) / "uses").glob("*.allow.json"))) == 2
    import shutil
    shutil.rmtree(state_of(st))
    from superyak_peer.common import Problem
    before = [r["record"]["event"] for r in receipts(st)]
    with pytest.raises(Problem):
        st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    assert not state_of(st).exists() and [r["record"]["event"] for r in receipts(st)] == before


def test_an_unknown_use_a_short_prefix_and_an_unknown_imprint_are_problems(tmp_path):
    from superyak_peer.common import Problem
    st = admitted(tmp_path, route=True, n=1)
    for prefix, use in ((st.imprint_id[:4], "calibration"), (st.imprint_id[:3], "trail-evaluation"), ("ffff", "trail-evaluation")):
        with pytest.raises(Problem):
            st.store.station_imprint_use_begin("andy", prefix, use, root=st.root)


# Task 39: the sync finishes uses (spec I 12, D41, CN7).

import hashlib
import multiprocessing

from test_imprint_withdrawal import withdraw

REPORT_BYTES = json.dumps({"sessions": ["sess-aaaa-1111", "sess-bbbb-2222"], "trails": ["trail-key-7f3", "trail-key-9c1"],
                           "steps": ["step-id-42"]}).encode()
SHA_OF_STUB_REPORT = hashlib.sha256(REPORT_BYTES).hexdigest()


def package_session_ids(st):
    return ["sess-aaaa-1111", "sess-bbbb-2222", "step-id-42"]


def stub_report_trail_keys():
    return ["trail-key-7f3", "trail-key-9c1"]


def allow_file(st, use_id):
    return state_of(st) / "uses" / f"{use_id}.allow.json"


def use_dir(st, use_id):
    path = state_of(st) / "uses" / use_id
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def write_report(st, use_id):
    (use_dir(st, use_id) / "report.json").write_bytes(REPORT_BYTES)


def write_use_result(st, use_id, *, exit=0, error=None, report=None, ended_at=None):
    doc = {"kind": "imprint-use-result", "use_id": use_id, "exit": exit, "error": error,
           "report": exit == 0 if report is None else report,
           "ended_at": int(st.clock[0]) if ended_at is None else ended_at}
    (use_dir(st, use_id) / "result.json").write_text(json.dumps(doc))


def started_without_result(tmp_path, route=True):
    st = admitted(tmp_path, route=route, n=4 if route else 0)
    out = st.store.station_imprint_use_begin("andy", st.imprint_id[:4], "trail-evaluation", root=st.root)
    return st, out["use_id"]


def started_at(st, use_id):
    return next(r["record"]["at"] for r in receipts(st) if r["record"]["event"] == "use-started"
                and r["record"]["detail"]["use_id"] == use_id)


def finished(st, use_id):
    found = [r["record"] for r in receipts(st) if r["record"]["event"] == "use-finished"
             and r["record"]["detail"]["use_id"] == use_id]
    return found[0] if found else None


def force_status(st, status):
    with st.store.transaction() as db:
        db.execute("UPDATE imprint_requests SET status=? WHERE id=?", (status, st.request_id))


def run_ending(tmp_path, ending, route=True):
    st, use_id = started_without_result(tmp_path, route=route)
    st.clock[0] += 10
    if ending == "report":
        write_report(st, use_id)
        write_use_result(st, use_id, exit=0, report=True)
    elif ending == "report_written_result_not_yet":
        write_report(st, use_id)
    elif ending == "withdrawn_during_run":
        assert withdraw(st, "owner").status_code == 200
    elif ending == "ended_during_run":
        end = effective_end_of(st)
        st.clock[0] = end + 1
        write_use_result(st, use_id, exit=3, ended_at=end)
    elif ending == "station_deleted_during_run":
        st.store.station_imprint_delete("andy", st.imprint_id[:4], root=st.root)
    elif ending == "shortened_still_ahead":
        write_use_result(st, use_id, exit=3, report=False)
    elif ending == "killed_by_signal":
        write_use_result(st, use_id, exit=-9, report=False)
    elif ending == "trails_exit_1":
        write_use_result(st, use_id, exit=1, report=False)
    elif ending == "use_raised":
        write_use_result(st, use_id, exit=None, error="ValueError", report=False)
    else:
        raise AssertionError(ending)
    return st, use_id


def sync_once(data_dir, root):
    from superyak_peer.db import Store
    Store(data_dir, signing=False, clock=lambda: float(NOW) + 10).station_imprint_sync(root=root)


def sync_in_two_processes(st):
    context = multiprocessing.get_context("fork")
    procs = [context.Process(target=sync_once, args=(st.store.data_dir, st.root)) for _ in range(2)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(60)
        assert proc.exitcode == 0


@pytest.mark.parametrize("ending,expected", [
    ("report", {"end": "report", "report_sha256": SHA_OF_STUB_REPORT}),
    ("withdrawn_during_run", {"end": "withdrawn"}), ("ended_during_run", {"end": "ended"}),
    ("station_deleted_during_run", {"end": "deleted", "reason": "station"}),
    ("shortened_still_ahead", {"end": "allow changed"}), ("killed_by_signal", {"end": "not evaluable: limit"}),
    ("trails_exit_1", {"end": "failed", "exit": 1}), ("use_raised", {"end": "failed", "error": "ValueError"})])
def test_use_finished_records_how_the_run_ended(tmp_path, ending, expected):
    st, use_id = run_ending(tmp_path, ending)
    st.store.station_imprint_sync(root=st.root)
    finished_ = [r["record"] for r in receipts(st) if r["record"]["event"] == "use-finished"]
    assert len(finished_) == 1 and expected.items() <= finished_[0]["detail"].items()
    assert not allow_file(st, use_id).exists()


def test_a_stopped_unit_is_finished_by_the_first_sync_after_1860_s(tmp_path):
    st, use_id = started_without_result(tmp_path)
    st.clock[0] = started_at(st, use_id) + 1859
    st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)
    st.clock[0] += 1
    st.store.station_imprint_sync(root=st.root)
    assert finished(st, use_id)["detail"]["end"] == "not evaluable: limit"


def test_two_syncs_at_once_write_one_use_finished(tmp_path):
    st, use_id = run_ending(tmp_path, "report")
    sync_in_two_processes(st)
    assert len([r for r in receipts(st) if r["record"]["event"] == "use-finished"]) == 1


def test_a_sync_between_the_two_writes_finishes_nothing(tmp_path):
    st, use_id = run_ending(tmp_path, "report_written_result_not_yet")
    st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)
    write_use_result(st, use_id, exit=0)
    st.store.station_imprint_sync(root=st.root)
    assert finished(st, use_id)["detail"]["end"] == "report"


def test_no_use_is_finished_while_deleting(tmp_path):
    st, use_id = run_ending(tmp_path, "report")
    force_status(st, "deleting")
    st.store.station_imprint_sync(root=st.root)
    assert not finished(st, use_id)


def test_no_receipt_names_a_road_a_trail_or_a_session(tmp_path):
    st, use_id = run_ending(tmp_path, "report", route=True)
    st.store.station_imprint_sync(root=st.root)
    text = json.dumps([r["record"] for r in receipts(st)])
    assert not any(s in text for s in package_session_ids(st) + stub_report_trail_keys())
    assert {tuple(sorted(r["record"]["detail"]["objects"])) for r in receipts(st) if "objects" in r["record"]["detail"]} == {
        ("count", "imprint", "roads_and_trails")}


# Added by the task: what the brief's seven tests leave open.

def test_a_missing_allow_file_is_no_error_and_a_finished_use_is_not_finished_again(tmp_path):
    st, use_id = run_ending(tmp_path, "report")
    allow_file(st, use_id).unlink()
    st.store.station_imprint_sync(root=st.root)
    st.store.station_imprint_sync(root=st.root)
    assert len([r for r in receipts(st) if r["record"]["event"] == "use-finished"]) == 1


def test_the_finish_keeps_the_start_terms_and_objects(tmp_path):
    st, use_id = run_ending(tmp_path, "report", route=True)
    st.store.station_imprint_sync(root=st.root)
    started = next(r["record"]["detail"] for r in receipts(st) if r["record"]["event"] == "use-started")
    done = finished(st, use_id)["detail"]
    assert {k: done[k] for k in started} == started and done["objects"]["roads_and_trails"] == 4


def test_a_report_without_a_result_still_ends_as_a_report_after_1860_s(tmp_path):
    st, use_id = run_ending(tmp_path, "report_written_result_not_yet")
    st.clock[0] = started_at(st, use_id) + 1860
    st.store.station_imprint_sync(root=st.root)
    assert finished(st, use_id)["detail"]["end"] == "report"
