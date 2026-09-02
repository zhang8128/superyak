"""Session-end auto-capture of positive recall outcomes."""

from __future__ import annotations

import json
import sqlite3

import pytest

from tests.test_nudge_harness import _load, _seed_episodes


def _conn(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _log_recall(conn, recall_id, session_id, targets, timestamp, outcome=None):
    conn.execute(
        "INSERT INTO memory_log "
        "(id, timestamp, event_type, layer, target_ids, context, outcome) "
        "VALUES (?, ?, 'recall', 'all', ?, ?, ?)",
        (
            f"log-{recall_id}",
            timestamp,
            json.dumps(targets),
            json.dumps(
                {
                    "recall_id": recall_id,
                    "query": "q",
                    "session_id": session_id,
                }
            ),
            outcome,
        ),
    )


def _cite_by_episode(conn, session_id, text, timestamp, context=None):
    conn.execute(
        "INSERT INTO episodes "
        "(id, session_id, content, context, created_at, core, dormant, lane) "
        "VALUES (?, ?, ?, ?, ?, 0, 0, 'personal')",
        (
            f"cite-{timestamp}",
            session_id,
            text,
            json.dumps(context) if context is not None else None,
            timestamp,
        ),
    )


def _cite_by_operation(conn, session_id, operation, targets, timestamp):
    conn.execute(
        "INSERT INTO operation_log "
        "(id, timestamp, operation, session_id, target_ids, details, outcome) "
        "VALUES (?, ?, ?, ?, ?, '{}', 'success')",
        (
            f"op-{timestamp}",
            timestamp,
            operation,
            session_id,
            json.dumps(targets),
        ),
    )


def _outcome(conn, recall_id):
    return conn.execute(
        "SELECT outcome FROM memory_log "
        "WHERE json_extract(context, '$.recall_id') = ?",
        (recall_id,),
    ).fetchone()["outcome"]


@pytest.fixture
def db(tmp_path):
    return _seed_episodes(tmp_path, n=3)


def test_recall_cited_by_later_episode_content_is_marked_used(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(
        conn,
        "r1",
        "s1",
        ["ep-0", "ep-1"],
        "2026-09-01T10:00:00+00:00",
    )
    _cite_by_episode(
        conn,
        "s1",
        "building on ep-0 from the earlier recall",
        "2026-09-01T10:05:00+00:00",
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 1
    assert _outcome(conn, "r1") == sleep.AUTO_OUTCOME


def test_recall_cited_by_later_episode_context_is_marked_used(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r2", "s1", ["ep-1"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(
        conn,
        "s1",
        "building on the earlier recall",
        "2026-09-01T10:05:00+00:00",
        context={"source_id": "ep-1"},
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 1
    assert _outcome(conn, "r2") == sleep.AUTO_OUTCOME


@pytest.mark.parametrize(
    "operation", ["mark_core", "instinct_feedback", "dream_react"]
)
def test_recall_cited_by_supported_operation_is_marked_used(db, operation):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r3", "s1", ["ep-2"], "2026-09-01T10:00:00+00:00")
    _cite_by_operation(
        conn,
        "s1",
        operation,
        ["ep-2"],
        "2026-09-01T10:01:00+00:00",
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 1
    assert _outcome(conn, "r3") == sleep.AUTO_OUTCOME


def test_uncited_recall_stays_unlabeled(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r4", "s1", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(
        conn,
        "s1",
        "nothing to do with that",
        "2026-09-01T10:05:00+00:00",
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r4") is None


def test_citation_before_recall_does_not_count(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r5", "s1", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(
        conn,
        "s1",
        "mentions ep-0 earlier",
        "2026-09-01T09:00:00+00:00",
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 0


def test_existing_outcome_is_never_overwritten(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(
        conn,
        "r6",
        "s1",
        ["ep-0"],
        "2026-09-01T10:00:00+00:00",
        outcome="not_used: wrong",
    )
    _cite_by_episode(
        conn, "s1", "ep-0 again", "2026-09-01T10:05:00+00:00"
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r6") == "not_used: wrong"


def test_other_sessions_are_untouched(db):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r7", "s2", ["ep-0"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(
        conn,
        "s1",
        "ep-0 cited by a different session",
        "2026-09-01T10:05:00+00:00",
    )
    conn.commit()

    assert sleep.auto_capture_outcomes(conn, "s1") == 0
    assert _outcome(conn, "r7") is None


def test_no_session_id_is_noop(db):
    sleep = _load("sleep")
    conn = _conn(db)
    assert sleep.auto_capture_outcomes(conn, None) == 0


def test_sleep_runs_auto_capture(db, monkeypatch, capsys):
    sleep = _load("sleep")
    conn = _conn(db)
    _log_recall(conn, "r8", "s1", ["ep-1"], "2026-09-01T10:00:00+00:00")
    _cite_by_episode(
        conn, "s1", "ep-1 was the one", "2026-09-01T10:05:00+00:00"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(sleep, "DB_PATH", db)
    monkeypatch.setattr(sleep, "_load_instance_config", lambda: None)
    monkeypatch.setattr(
        sleep, "read_context", lambda: {"skip": False, "session_id": "s1"}
    )
    monkeypatch.setattr(sleep, "clear_session_binding", lambda conn, ctx: None)

    sleep.sleep()

    assert "auto-captured 1" in capsys.readouterr().err
    assert _outcome(_conn(db), "r8") == sleep.AUTO_OUTCOME
