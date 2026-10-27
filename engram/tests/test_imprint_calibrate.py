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


# --- Task 5: every dense set bounded, lane and core sets in blocks ---------------------------------------

import math  # noqa: E402
import os  # noqa: E402

import numpy as np  # noqa: E402

import calibrate as calibrate_module  # noqa: E402
import persistence  # noqa: E402
import sheaf  # noqa: E402
from calibrate import MAX_LANE_EPISODES, MAX_SEMANTIC_EPISODES  # noqa: E402
from storage import Storage  # noqa: E402
from tests.imprint_support import (  # noqa: E402
    GROWING_TABLES, PEAK_BUDGET, base_peak, child_peak_rss, dense_source, heights, random_unit_vectors,
    refuse_over, refusing_fetchall, spy, unit_rows)


def test_every_dense_set_over_the_bound_records_a_skip(tmp_path, monkeypatch):
    src = dense_source(tmp_path, lane_n=13, cores=13, hub_sources=13, event_sources=13)   # an unchecked subdivision event
    built = []                                       # whose two peers hold 13 vectored sources together
    monkeypatch.setattr(persistence, "distance_matrix", spy(persistence.distance_matrix, built, size=len))
    monkeypatch.setattr(sheaf, "build_local_sheaf", spy(sheaf.build_local_sheaf, built, size=lambda sid, ids, *a: len(ids)))
    report = calibrate(src, tmp_path / "out", max_lane_episodes=12, max_semantic_episodes=12, now=NOW)
    sets = {s["set"].split(":")[0] for s in report["analyses"]["skipped_dense_sets"]}
    assert sets == {"lane", "core", "hub", "cohesion", "event"} and max(built, default=0) <= 12


def test_lane_and_hub_over_their_bounds_are_skipped_and_named(tmp_path, monkeypatch):
    src = dense_source(tmp_path, lane_n=16_001, cores=0, hub_sources=1_025)
    monkeypatch.setattr(persistence, "build_filtration_blocked", refuse_over(16_000))
    monkeypatch.setattr(persistence, "distance_matrix", refuse_over(1_024, size=len))
    report = calibrate(src, tmp_path / "out", max_lane_episodes=MAX_LANE_EPISODES,
                       max_semantic_episodes=MAX_SEMANTIC_EPISODES, now=NOW)
    skipped = report["analyses"]["skipped_dense_sets"]
    assert {"set": "lane:work", "n": 16_001, "bound": 16_000} in skipped
    assert any(s["set"].startswith("hub:") and s["n"] == 1_025 and s["bound"] == 1_024 for s in skipped)


@pytest.mark.parametrize("n,dupes", [(40, 0), (300, 0), (300, 12)])
def test_the_blocked_filtration_equals_the_dense_one(n, dupes):
    X = random_unit_vectors(n, 768, seed=n, duplicate_rows=dupes)
    a, b = persistence.build_filtration(X), persistence.build_filtration_blocked(X, block_rows=7)
    assert np.allclose(a.nn_dist, b.nn_dist, atol=1e-9) and math.isclose(a.max_height, b.max_height, abs_tol=1e-9)
    assert sorted(np.round(heights(a), 9)) == sorted(np.round(heights(b), 9))     # the tree's heights, as a multiset
    assert all(i < j for _, i, j in persistence._prim_edges(unit_rows(X)))        # (h, min, max), R28; the check's S2
    if dupes == 0:
        assert np.allclose(a.death, b.death, atol=1e-9)        # (parent, child) or (max, min) edges fail here


def test_calibration_reads_no_whole_table(tmp_path, monkeypatch):
    src = calibration_source(tmp_path, resonances=50, decayed=20)
    monkeypatch.setattr(calibrate_module, "_connect_read_only", refusing_fetchall(GROWING_TABLES))   # a proxy connection
    report = calibrate(src, tmp_path / "out", max_lane_episodes=MAX_LANE_EPISODES,
                       max_semantic_episodes=MAX_SEMANTIC_EPISODES, now=NOW)
    assert not [a for a in report["analyses"].values() if isinstance(a, dict) and "error" in a]


def test_cohesion_keeps_only_its_summary(tmp_path):
    src = dense_source(tmp_path, lane_n=60, semantics=40, sources_each=3)
    report = calibrate(src, tmp_path / "out", max_semantic_episodes=MAX_SEMANTIC_EPISODES, now=NOW)
    c = report["analyses"]["cohesion"]
    assert c["measured"] == 40 and len(c["hottest"]) == 15 and len(c["coolest"]) == 5 and sum(c["energy_histogram"]) == 40


@pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1", reason="Pi measurement (R16, R27)")
def test_pi_budget_a_16000_episode_lane_in_blocks(tmp_path):
    src = dense_source(tmp_path, lane_n=16_000, cores=0, hub_sources=0, dim=768)   # random unit vectors
    peak, seconds = child_peak_rss("calibrate.persistence_scores(Storage.open_read_only(SRC).conn, "
                                   "max_episodes=16_000)", src=src, timed=True)
    assert peak < PEAK_BUDGET and seconds < 600


RATIO_BOUND = {"cohesion_energy": 16, "classify_hubs": 20, "split_band": 16}   # I 10; classify_hubs revised (Task 50)


@pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1", reason="Pi measurement (R16, R27)")
@pytest.mark.parametrize("analysis", ["cohesion_energy", "classify_hubs", "split_band"])
def test_pi_budget_a_1024_source_semantic(tmp_path, analysis):
    src = dense_source(tmp_path, lane_n=1_024, cores=0, hub_sources=1_024, dim=768)
    peak = child_peak_rss(f"run_one({analysis!r}, SRC)", src=src)
    assert peak < PEAK_BUDGET
    ratio = (peak - base_peak()) / (1_024**2 * 8)
    print(f"{analysis}: ratio {ratio:.2f} (I 10: at most {RATIO_BOUND[analysis]})")
    assert ratio <= RATIO_BOUND[analysis], (analysis, ratio)
