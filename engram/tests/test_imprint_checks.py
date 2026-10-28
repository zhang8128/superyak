"""Admission checks 1 to 17 on a handed-off package (store-copy spec I 10, R9, R11)."""
import pytest

import store_reader
from imprint_checks import CHECK_MESSAGES, CheckFailure, check_12, check_13, verify
from tests.imprint_support import (FAR, MIGRATIONS, built_package, handed_off, open_checked, stub_verify,
                                   tampered)


@pytest.mark.parametrize("change,step", [
    ("extra_file", 1), ("symlinked_manifest", 1), ("changed_byte", 2), ("permission_fails_verify", 3),
    ("request_sha256_differs", 3), ("wal_header", 4), ("corrupt_page", 5), ("unknown_migration", 6),
    ("planted_trigger", 7), ("extra_table", 7), ("other_vec_info", 7), ("changed_meta", 8), ("non_empty_dropped_table", 9)])
def test_each_check_fails(tmp_path, change, step):
    root, imprint_id = tampered(tmp_path, change)
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=change != "permission_fails_verify"),
                     migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert failure is not None and failure.step == step and failure.message == CHECK_MESSAGES[step]


def test_vec0_reading_is_immutable_and_makes_no_side_file(tmp_path):
    root, imprint_id = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
    conn = store_reader.connect(root / imprint_id / "imprint.db", immutable=True, vec=True)
    assert conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] > 0
    assert sorted(p.name for p in (root / imprint_id).iterdir()) == ["approved.json", "imprint.db", "manifest.json", "permission.json"]


def test_a_clean_package_passes_checks_1_to_9(tmp_path):
    root, imprint_id = handed_off(tmp_path, built_package(tmp_path), route=True, valid_until=FAR)
    assert verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s") is None
    assert sorted(p.name for p in (root / imprint_id).iterdir()) == ["approved.json", "imprint.db", "manifest.json", "permission.json"]


def test_a_vec_mismatch_names_the_remedy(tmp_path):
    root, imprint_id = tampered(tmp_path, "extra_table")
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert isinstance(failure, CheckFailure) and "one commit" in failure.message


@pytest.mark.parametrize("change,step", [
    ("dangling_target", 10), ("unscrubbed_context", 11), ("instinct_id_in_recall", 10), ("lane_outside_scope", 12),
    ("time_outside_scope", 12), ("session_id_without_route", 12), ("digest_mismatch", 13), ("free_page", 14),
    ("rowid_gap", 15), ("fts_orphan", 16), ("non_zero_invalid_vec0_slot", 17),
    ("subject_row_for_a_missing_memory", 10), ("subject_row_naming_the_owner", 10),
    ("subject_row_in_a_copy_leaving_home", 12), ("others_disagree_with_the_rows", 13)])
def test_each_later_check_fails(tmp_path, change, step, route_open):        # P33: not test_each_check_fails, which checks 1 to 9 own
    root, imprint_id = tampered(tmp_path, change)
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert failure is not None and failure.step == step and failure.message == CHECK_MESSAGES[step]


def test_a_session_id_set_by_hand_also_fails_the_digest(tmp_path):
    root, imprint_id = tampered(tmp_path, "session_id_without_route")
    conn, manifest = open_checked(root / imprint_id)
    assert check_12(conn, manifest) is not None and check_13(conn, manifest) is not None


def test_a_clean_package_passes_all_17(tmp_path, route_open):
    for route, cos in ((False, None), (True, None), (True, {"e1": "person:jenn"})):     # the last: andy's copy at home
        d = tmp_path / f"{route}-{bool(cos)}"
        built = built_package(d, route=route, owner="andy" if cos else "sam", cosubjects=cos)
        root, imprint_id = handed_off(d, built, route=route, valid_until=FAR, owner="andy" if cos else "sam")
        assert verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=d / "s") is None


def test_log_rows_under_a_permission_without_route_fail_the_scope(tmp_path, route_open):
    built = built_package(tmp_path, route=True)
    root, imprint_id = handed_off(tmp_path, built, route=False, valid_until=FAR, owner="sam")
    failure = verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s")
    assert failure is not None and failure.step == 12


def test_admission_leaves_nothing_in_its_scratch_directory(tmp_path, route_open):
    built = built_package(tmp_path, route=True)
    root, imprint_id = handed_off(tmp_path, built, route=True, valid_until=FAR, owner="sam")
    assert verify(root / imprint_id, verify_cmd=stub_verify(ok=True), migrations_dir=MIGRATIONS, scratch=tmp_path / "s") is None
    assert list((tmp_path / "s").iterdir()) == []
