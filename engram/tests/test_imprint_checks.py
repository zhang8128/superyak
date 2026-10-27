"""Admission checks 1 to 9 on a handed-off package (store-copy spec I 10, R9, R11)."""
import pytest

import store_reader
from imprint_checks import CHECK_MESSAGES, CheckFailure, verify
from tests.imprint_support import FAR, MIGRATIONS, built_package, handed_off, stub_verify, tampered


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
