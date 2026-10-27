"""``imprint.py admit``: decided again, checked before each write, calibrated content-free (store-copy spec I 10, D39)."""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import calibrate
from calibrate import PATHS_NOT_MEASURED
from imprint import CALIBRATION_FAILED, NEED_ADMISSION, RERUN_REFUSED, _still_allowed, admit, list_imprints
from permissions import decide_bulk
from tests.imprint_support import (FAR, ENGRAM_DIR, T, admitted_report, as_bulk, built_package, built_texts, dense_source,
                                   ceiling_world, counting_stub, fixture_for, handed_off, has_key, hooked_calibrate,
                                   hooked_verify, mentions_any, must_not_be_called, no_memory_text, per_lane_stub,
                                   raise_, recording_stub, remove_like_withdrawal, roads_and_trails_by_hand,
                                   session_ids, shorten_admission_json, stub_verify, survey_minus, tampered,
                                   trail_rich_store)

T1 = T("2026-10-25T18:00:00Z")
CAL_NOW = datetime(2026, 10, 25, 19, 30, tzinfo=timezone.utc)
OK = stub_verify(ok=True)
must_not_run = stub_verify(ok=False)


def test_calibration_at_admission_is_content_free_and_leaves_no_copies(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibration_now=CAL_NOW) == 0
    cal = root / f"{iid_}.state" / "calibration"
    report = json.loads((cal / "report.json").read_text())
    assert not has_key(report, "content") and no_memory_text(report, built_texts(tmp_path))
    assert report["source_unchanged"] and report["source_side_files_created"] == []
    assert sorted(p.name for p in cal.iterdir()) == ["report.json", "report.md"]
    assert sorted(p.name for p in (root / iid_).iterdir()) == ["approved.json", "imprint.db", "imprint.json", "manifest.json", "permission.json"]


def test_calibration_with_and_without_route_agree_where_they_must(tmp_path):
    a = admitted_report(tmp_path / "a", route=False, now=CAL_NOW); b = admitted_report(tmp_path / "b", route=True, now=CAL_NOW)
    for name in ("first_open", "persistence_scores", "cohesion", "persistence"):
        assert a["analyses"].get(name) == b["analyses"].get(name), name
    assert survey_minus(a) == survey_minus(b)    # less episodes.sessions, memory_log, operation_log, file, identity
    assert a["snapshot"]["episodes"]["sessions"] == 0 and a["snapshot"]["row_counts"]["memory_log"] == 0
    assert a["notes"] == {"snapshot": "0 sessions and 0 log rows, because route was not chosen"} and "notes" not in b
    assert a["analyses"]["paths"] == b["analyses"]["paths"] == PATHS_NOT_MEASURED
    assert not mentions_any(a, session_ids(tmp_path / "b")) and not mentions_any(b, session_ids(tmp_path / "b"))


@pytest.mark.parametrize("when", ["checking", "calibrating"])
def test_a_withdrawal_during_admission_stops_it(tmp_path, when):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    hook = remove_like_withdrawal(root, iid_)                    # removes both directories, writes the tombstone
    code = admit(iid_, root=root, verify_cmd=OK if when == "calibrating" else hooked_verify(hook),
                 calibrate_fn=hooked_calibrate(hook) if when == "calibrating" else calibrate.calibrate)
    assert code == 4 and not (root / iid_).exists() and not (root / f"{iid_}.state").exists()


def test_an_end_reached_during_calibration_stops_it_before_the_report(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    code = admit(iid_, root=root, verify_cmd=OK, calibrate_fn=hooked_calibrate(lambda: shorten_admission_json(root, iid_, to=1)))
    assert code == 5 and not (root / f"{iid_}.state" / "result.json").exists()


def test_rf1_a_dead_runs_calibration_fails_the_rerun(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    (root / f"{iid_}.state" / "calibration").mkdir(); (root / f"{iid_}.state" / "calibration" / "snapshot.db").write_bytes(b"x")
    assert admit(iid_, root=root, verify_cmd=must_not_run, calibrate_fn=must_not_be_called) == 1
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["step"], result["message"]) == ("calibration", RERUN_REFUSED) and not (root / iid_ / "imprint.json").exists()
    assert (root / f"{iid_}.state" / "calibration" / "snapshot.db").read_bytes() == b"x"


def test_a_calibration_that_raises_fails_with_step_calibration(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibrate_fn=raise_(MemoryError("/home/sam/secret path"))) == 1
    text = (root / f"{iid_}.state" / "result.json").read_text()
    assert (json.loads(text)["step"], json.loads(text)["message"]) == ("calibration", CALIBRATION_FAILED) and "secret" not in text


def test_a_failed_check_writes_a_failed_result(tmp_path):
    root, iid_ = tampered(tmp_path, "changed_byte")
    assert admit(iid_, root=root, verify_cmd=OK) == 1
    assert json.loads((root / f"{iid_}.state" / "result.json").read_text())["step"] == 2


def test_admission_registers_co_subjects_and_leaves_no_scratch(tmp_path):
    built = built_package(tmp_path, owner="andy", cosubjects={"e1": "person:jenn", "e2": ["person:jenn", "person:lee"]})
    root, iid_ = handed_off(tmp_path, built, route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibration_now=CAL_NOW) == 0
    reg = json.loads((root / iid_ / "imprint.json").read_text())
    assert reg["others"] == {"memories": 2, "people": 2} and reg["imprint_subjects"] == 3
    assert not (root / f"{iid_}.state" / "scratch").exists()


def test_an_admitted_imprint_is_read_only_and_listed(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibration_now=CAL_NOW) == 0
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["status"], result["checks"], result["roads_and_trails"], result["sessions_too_large"]) == ("admitted", 17, 0, 0)
    assert result["report_sha256"] == json.loads((root / iid_ / "imprint.json").read_text())["report_sha256"]
    assert (root / iid_).stat().st_mode & 0o777 == 0o555
    assert all(p.stat().st_mode & 0o777 == 0o444 for p in (root / iid_).iterdir())
    assert [row["imprint_id"] for row in list_imprints(root)] == [iid_]


def test_still_allowed_names_what_changed(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=1000)
    assert _still_allowed(root, iid_, 999) is None and _still_allowed(root, iid_, 1000) == "ended"
    (root / iid_ / "approved.json").unlink()
    assert _still_allowed(root, iid_, 1) == "withdrawn"


def test_importing_imprint_loads_no_numpy():
    code = "import sys; sys.path.insert(0, %r); import imprint; sys.exit(1 if 'numpy' in sys.modules else 0)" % str(ENGRAM_DIR)
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# ---- Counting R(I) (Task 35) ----

def test_the_count_reaches_result_json_and_is_zero_without_route(tmp_path):
    for route, expected in ((True, 3), (False, 0)):
        root, iid_ = handed_off(tmp_path / str(route), built_package(tmp_path / str(route), route=route), route=route, valid_until=FAR)
        derive = counting_stub(3) if route else must_not_be_called
        assert admit(iid_, root=root, verify_cmd=OK, derive=derive) == 0
        assert json.loads((root / f"{iid_}.state" / "result.json").read_text())["roads_and_trails"] == expected


def test_admission_with_route_fails_closed_without_the_trail_functions(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "trails", None)
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True), route=True, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK) == 1
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["step"], result["message"]) == ("count", "roads and trails can't be counted: trails.py is not installed")


def test_counting_reads_the_package_at_t1(tmp_path):
    seen = []
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True, until=T1, lanes=("personal", "work")), route=True, valid_until=FAR)
    admit(iid_, root=root, verify_cmd=OK, derive=recording_stub(seen))
    assert sorted((s["lane"], s["as_of"]) for s in seen) == [("personal", T1), ("work", T1)]   # one call per lane


def test_the_count_is_the_sum_of_the_trail_specs_lane_counts(tmp_path):     # R10; the check's S8
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True, until=T1, lanes=("personal", "work")), route=True, valid_until=FAR)
    stub = per_lane_stub({"personal": 2, "work": 3}, too_large={"personal": 1, "work": 1})   # one session, seen in both lanes
    assert admit(iid_, root=root, verify_cmd=OK, derive=stub) == 0
    result = json.loads((root / f"{iid_}.state" / "result.json").read_text())
    assert (result["roads_and_trails"], result["sessions_too_large"]) == (5, 1)    # K beside N, counted once (the re-check's S4)
    assert not (root / f"{iid_}.state" / "scratch").exists()


def test_admission_stays_inside_its_need(tmp_path):
    recorded = []
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True), route=True, valid_until=FAR)
    admit(iid_, root=root, verify_cmd=OK, derive=counting_stub(2), record_use=recorded.append)
    assert {(u.object_kind, u.action, u.purpose) for u in recorded} <= NEED_ADMISSION(route=True)
    assert not [u for u in recorded if u.object_kind == "road-or-trail" and u.purpose == "calibration"]
    state, ceiling = ceiling_world(fixture_for(root, iid_))
    assert all(decide_bulk(state, as_bulk(u, root, iid_), outside={"place:home/andy": ceiling}).allowed for u in recorded)


def test_count_matches_the_trail_functions(tmp_path):
    trails = pytest.importorskip("trails", reason="trails.py comes with the trails plan (gate G13)")
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True, store=trail_rich_store, until=T1), route=True, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK) == 0
    n = json.loads((root / f"{iid_}.state" / "result.json").read_text())["roads_and_trails"]
    assert n == roads_and_trails_by_hand(trails, root / iid_ / "imprint.db", as_of=T1) == roads_and_trails_by_hand(
        trails, root / iid_ / "imprint.db", as_of=T1 + 86_400)


# ---- The `admitted` receipt names no memory (final review I1; spec section 12) ----

def every_set_over_its_bound(*args, **kwargs):
    """A ``calibrate_fn`` whose bounds are 1, so every lane, the core set, each hub, cohesion set and event is skipped."""
    return calibrate.calibrate(*args, **(kwargs | {"max_lane_episodes": 1, "max_semantic_episodes": 1}))


def small_dense_store(tmp_path):
    """A work lane of 24 episodes, 4 of them cores, a hub on 12 sources and a subdivision event on 4."""
    from storage import Storage

    store = Storage(str(dense_source(tmp_path, 24, cores=4, hub_sources=12, event_sources=4)))
    store.add_semantic("parent", "semantic parent", "fact", 0.8, [0.03] * 768, ["w0", "w1"], lane="work")  # the event's parent
    store.conn.execute("UPDATE semantics SET created_at='2026-01-02T00:00:00+00:00'")   # inside the plan's window
    store.conn.commit()
    return store


def test_result_json_skips_name_kinds_and_lanes_never_a_memory_id(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, store=small_dense_store), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibrate_fn=every_set_over_its_bound, calibration_now=CAL_NOW) == 0
    report = json.loads((root / f"{iid_}.state" / "calibration" / "report.json").read_text())
    named = [s["set"] for s in report["analyses"]["skipped_dense_sets"]]
    with_ids = [s for s in named if s.split(":", 1)[0] in ("hub", "cohesion", "event")]
    assert {s.split(":")[0] for s in with_ids} == {"hub", "cohesion", "event"}   # the report keeps the ids; it goes with the copy
    text = (root / f"{iid_}.state" / "result.json").read_text()
    skipped = json.loads(text)["skipped"]
    assert not [i for i in with_ids if i in text]
    assert {s["set"] for s in skipped} <= {"core", "hub", "cohesion", "event", "lane:personal", "lane:work"}
    assert all(sorted(s) == ["bound", "n", "set"] and type(s["n"]) is int and type(s["bound"]) is int for s in skipped)
    assert len(skipped) == len(named)


def test_a_withdrawal_after_calibration_stops_admission_before_the_count(tmp_path):     # final review M7
    seen = []
    root, iid_ = handed_off(tmp_path, built_package(tmp_path, route=True), route=True, valid_until=FAR)

    def withdrawn_after_calibration(use):     # the count's own reads are recorded after the calibration gate
        if use.purpose == "trail-evaluation":
            (root / "tombstones").mkdir(exist_ok=True)
            (root / "tombstones" / f"{iid_}.json").write_text("{}")
    assert admit(iid_, root=root, verify_cmd=OK, derive=recording_stub(seen), record_use=withdrawn_after_calibration) == 4
    assert seen == [] and not (root / f"{iid_}.state" / "result.json").exists()


def test_an_unknown_skip_kind_fails_before_anything_is_marked_admitted(tmp_path):
    def odd_kind(*args, **kwargs):
        report = every_set_over_its_bound(*args, **kwargs)
        report["analyses"]["skipped_dense_sets"].append({"set": "mystery:abc", "n": 5, "bound": 1})
        return report

    root, iid_ = handed_off(tmp_path, built_package(tmp_path, store=small_dense_store), route=False, valid_until=FAR)
    try:
        code = admit(iid_, root=root, verify_cmd=OK, calibrate_fn=odd_kind, calibration_now=CAL_NOW)
    except ValueError:
        code = None
    assert code != 0
    path = root / iid_ / "imprint.json"
    assert not path.exists() or json.loads(path.read_text()).get("status") != "admitted"
    assert not (root / f"{iid_}.state" / "result.json").exists() or \
        json.loads((root / f"{iid_}.state" / "result.json").read_text()).get("status") != "admitted"


# ---- G18 RC1: when other people are carried, the calibration report names no memory id ----

def _ids_of(db_path):
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [r[0] for t in ("episodes", "semantics") for r in conn.execute(f"SELECT id FROM {t}")]
    finally:
        conn.close()


def test_a_carried_co_subject_gives_a_report_with_no_memory_id(tmp_path):
    built = built_package(tmp_path, store=small_dense_store, owner="andy", cosubjects={"w1": "person:jenn"})
    root, iid_ = handed_off(tmp_path, built, route=False, valid_until=FAR)
    ids = [i for i in _ids_of(root / iid_ / "imprint.db") if i not in ("hub", "core", "event", "cohesion")]  # kind words stay
    assert admit(iid_, root=root, verify_cmd=OK, calibrate_fn=every_set_over_its_bound, calibration_now=CAL_NOW) == 0
    cal = root / f"{iid_}.state" / "calibration"
    assert ids and json.loads((root / iid_ / "imprint.json").read_text())["others"]["memories"] > 0
    for name in ("report.json", "report.md"):
        text = (cal / name).read_text()
        assert not re.search(r"(hub|cohesion|event):[\w-]", text)           # a skipped set's name carries its id
        for i in ids + ["ev1"]:
            assert not re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", text), (name, i)   # whole tokens: ids can be short


def test_with_no_carried_co_subject_the_report_keeps_its_ids(tmp_path):
    root, iid_ = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, calibration_now=CAL_NOW) == 0
    assert "would_prune_ids" in (root / f"{iid_}.state" / "calibration" / "report.json").read_text()
    assert isinstance(json.loads((root / f"{iid_}.state" / "calibration" / "report.json").read_text())
                      ["analyses"]["first_open"]["would_prune_ids"], list)
