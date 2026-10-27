from datetime import datetime, timezone

import pytest

from calibrate import PATHS_NOT_MEASURED, calibrate
from tests.imprint_support import calibration_source, has_key, memory_texts

NOW = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)


def test_no_content_leaves_no_content_key_and_no_memory_text(tmp_path):
    src = calibration_source(tmp_path)
    report = calibrate(src, tmp_path / "out", no_content=True, now=NOW)
    files = [(tmp_path / "out" / n).read_text() for n in ("report.json", "report.md")]
    assert not has_key(report, "content") and '"content"' not in files[0]
    for text in memory_texts(src):
        assert all(text[:24] not in f for f in files)
    assert report["source_unchanged"] is True and report["source_side_files_created"] == []


def test_no_paths_writes_only_the_fixed_sentence(tmp_path):
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", no_paths=True, now=NOW)
    assert report["analyses"]["paths"] == PATHS_NOT_MEASURED
    assert PATHS_NOT_MEASURED in (tmp_path / "out" / "report.md").read_text()


def test_notes_sit_beside_their_section_in_both_reports(tmp_path):
    note = "0 sessions and 0 log rows, because route was not chosen"
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", notes={"snapshot": note}, now=NOW)
    md = (tmp_path / "out" / "report.md").read_text()
    assert report["notes"] == {"snapshot": note}
    assert md.index("## Snapshot") < md.index(f"- Note: {note}") < md.index("## Store identity")


def test_create_parents_false_never_recreates_a_removed_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        calibrate(calibration_source(tmp_path), tmp_path / "gone" / "calibration", create_parents=False, now=NOW)
    assert not (tmp_path / "gone").exists()


def test_defaults_keep_todays_report(tmp_path):
    report = calibrate(calibration_source(tmp_path), tmp_path / "out", now=NOW)
    assert "sessions_total" in report["analyses"]["paths"] and has_key(report, "content")
