"""``imprint.py admit``: decided again, checked before each write, calibrated content-free (store-copy spec I 10, D39)."""
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import calibrate
from calibrate import PATHS_NOT_MEASURED
from imprint import CALIBRATION_FAILED, RERUN_REFUSED, _still_allowed, admit, list_imprints
from tests.imprint_support import (FAR, ENGRAM_DIR, admitted_report, built_package, built_texts, handed_off,
                                   has_key, hooked_calibrate, hooked_verify, mentions_any, must_not_be_called,
                                   no_memory_text, raise_, remove_like_withdrawal, session_ids,
                                   shorten_admission_json, stub_verify, survey_minus, tampered)

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
