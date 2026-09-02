"""Pure helpers of the replay script (no model, no database)."""

import importlib.util
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "margins_replay.py"


def _load():
    spec = importlib.util.spec_from_file_location("margins_replay", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cand(cid, sim, recency, auto=False):
    return {
        "id": cid,
        "similarity": sim,
        "recency": recency,
        "auto_generated": auto,
    }


def test_rank_reports_winner_gamma_and_near_tie():
    m = _load()
    out = m.rank(
        [cand("a", 0.80, 1.0), cand("b", 0.79, 0.0)],
        mode="additive",
        w_sim=0.6,
        w_rec=0.4,
        cap=0.02,
    )
    assert out["winner"] == "a"
    assert out["gamma"] == pytest.approx((0.80 * 0.6 + 0.4) - (0.79 * 0.6))
    assert out["near_tie"] is False


def test_same_candidates_can_have_different_winners_per_mode():
    m = _load()
    cands = [cand("old-better", 0.84, 0.0), cand("new-worse", 0.80, 1.0)]
    add = m.rank(
        cands, mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    tie = m.rank(
        cands, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert add["winner"] == "new-worse"
    assert tie["winner"] == "old-better"


def test_rank_with_fewer_than_two_candidates_has_no_gamma():
    m = _load()
    out = m.rank(
        [cand("a", 0.8, 0.5)],
        mode="tiebreak",
        w_sim=0.6,
        w_rec=0.4,
        cap=0.02,
    )
    assert out["winner"] == "a"
    assert out["gamma"] is None
    assert out["near_tie"] is False


def test_rank_preserves_search_order_when_scores_tie():
    m = _load()
    out = m.rank(
        [cand("first", 0.8, 0.5), cand("z-last", 0.8, 0.5)],
        mode="tiebreak",
        w_sim=0.6,
        w_rec=0.4,
        cap=0.02,
    )
    assert out["winner"] == "first"


def test_future_candidate_timestamp_is_fully_recent():
    m = _load()
    at = datetime.now(timezone.utc)
    assert m._recency((at + timedelta(days=1)).isoformat(), at) == 1.0


def test_summarize_counts_near_ties_recent_winners_and_changes():
    m = _load()
    rows = [
        {
            "additive": {
                "winner": "x",
                "near_tie": True,
                "winner_age_days": 0.5,
            },
            "tiebreak": {
                "winner": "y",
                "near_tie": False,
                "winner_age_days": 40.0,
            },
        },
        {
            "additive": {
                "winner": "z",
                "near_tie": False,
                "winner_age_days": 3.0,
            },
            "tiebreak": {
                "winner": "z",
                "near_tie": False,
                "winner_age_days": 3.0,
            },
        },
    ]
    s = m.summarize(rows)
    assert s["recalls"] == 2
    assert s["additive"]["near_tie_rate"] == pytest.approx(0.5)
    assert s["additive"]["winner_le_7d"] == 2
    assert s["additive"]["winner_le_1d"] == 1
    assert s["tiebreak"]["winner_le_7d"] == 1
    assert s["tiebreak"]["winner_le_1d"] == 0
    assert s["winner_changed"] == 1


def test_render_reports_recent_winner_counts_as_shares(tmp_path):
    m = _load()
    summary = {
        "recalls": 4,
        "winner_changed": 1,
        "additive": {
            "near_tie_rate": 0.25,
            "winner_le_7d": 3,
            "winner_le_1d": 1,
        },
        "tiebreak": {
            "near_tie_rate": 0.5,
            "winner_le_7d": 2,
            "winner_le_1d": 0,
        },
    }

    report = m.render([], summary, tmp_path / "copy.db", "Before")

    assert "| additive | 0.25 | 3/4 (75.0%) | 1/4 (25.0%) |" in report
    assert "| tiebreak | 0.50 | 2/4 (50.0%) | 0/4 (0.0%) |" in report


def test_refuses_live_instance_paths(tmp_path):
    m = _load()
    live = tmp_path / ".engram" / "instances" / "engram" / "graph.db"
    live.parent.mkdir(parents=True)
    live.touch()
    with pytest.raises(SystemExit):
        m.main([str(live), "--output", str(tmp_path / "r.md")])


def test_refuses_symlink_to_live_instance_path(tmp_path):
    m = _load()
    live = tmp_path / ".engram" / "instances" / "engram" / "graph.db"
    live.parent.mkdir(parents=True)
    live.touch()
    alias = tmp_path / "copy.db"
    alias.symlink_to(live)

    with pytest.raises(SystemExit):
        m.main([str(alias), "--output", str(tmp_path / "r.md")])


def test_replay_connection_is_query_only_and_leaves_source_bytes_unchanged(tmp_path):
    m = _load()
    database = tmp_path / "copy.db"
    writer = sqlite3.connect(database)
    writer.execute("CREATE TABLE sentinel (value TEXT)")
    writer.execute("INSERT INTO sentinel VALUES ('unchanged')")
    writer.commit()
    writer.close()
    before = hashlib.sha256(database.read_bytes()).digest()

    connection = m._open_readonly(database)
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.total_changes == 0
        assert connection.execute("SELECT value FROM sentinel").fetchone()[0] == "unchanged"
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sentinel VALUES ('changed')")
    finally:
        connection.close()

    assert hashlib.sha256(database.read_bytes()).digest() == before
