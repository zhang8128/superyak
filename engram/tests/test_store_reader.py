from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

import store_reader
from storage import Storage


def unit(seed: int, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[seed % dim] = 1.0
    return vec


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_current_store(path: Path) -> None:
    store = Storage(str(path))
    for i, (session, content) in enumerate(
        [("s2", "later thought"), ("s1", "first thought"), ("s1", "second thought")]
    ):
        store.add_episode(str(uuid.uuid4()), session, content, embedding=unit(i))
    store.conn.execute(
        "UPDATE episodes SET created_at = CASE content"
        " WHEN 'first thought' THEN '2026-01-01T00:00:00'"
        " WHEN 'second thought' THEN '2026-01-02T00:00:00'"
        " ELSE '2026-02-01T00:00:00' END"
    )
    store.conn.commit()
    store.close()


def build_old_store(path: Path) -> None:
    """A store as migration 001 left it, before most episode columns existed."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT);
        INSERT INTO schema_version VALUES (1, '2026-03-20T00:00:00');
        CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT,
            content TEXT NOT NULL, episode_type TEXT, created_at TEXT NOT NULL);
        INSERT INTO episodes VALUES ('b', 's', 'wings do not flap', 'note', '2026-03-21');
        INSERT INTO episodes VALUES ('a', 's', 'reading begins', 'note', '2026-03-20');
        """
    )
    conn.commit()
    conn.close()


def build_reader(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE reactions (session_id TEXT, position INTEGER,
            passage TEXT, reaction TEXT, created_at TEXT);
        INSERT INTO reactions VALUES ('late', 0, 'p3', 'r3', '2026-05-01');
        INSERT INTO reactions VALUES ('early', 1, 'p2', 'r2', '2026-04-01');
        INSERT INTO reactions VALUES ('early', 0, 'p1', 'r1', '2026-04-01');
        """
    )
    conn.commit()
    conn.close()


def test_survey_reports_schema_and_changes_nothing(tmp_path):
    db = tmp_path / "graph.db"
    build_current_store(db)
    before = sha(db)

    report = store_reader.survey(db)

    assert report["kind"] == "engram"
    assert report["schema"]["pending"] == []
    assert report["file"]["sha256"] == before
    assert report["row_counts"]["episodes"] == 3
    assert report["episodes"]["sessions"] == 2
    assert report["episodes"]["first"] == "2026-01-01T00:00:00"
    assert "episode_vectors" in report["virtual_tables"]
    assert report["changes"] == 0
    assert sha(db) == before


def test_old_schema_is_read_without_migrating(tmp_path):
    db = tmp_path / "graph.db"
    build_old_store(db)
    before = sha(db)

    report = store_reader.survey(db)
    conn = store_reader.connect(db)
    episodes = store_reader.read_episodes(conn, limit=10)
    conn.close()

    assert report["schema"]["applied"] == [1]
    assert 2 in report["schema"]["pending"] and 27 in report["schema"]["pending"]
    assert [e["id"] for e in episodes] == ["a", "b"]
    assert "source" not in episodes[0]
    assert sha(db) == before


def test_read_pages_chronologically_by_session(tmp_path):
    db = tmp_path / "graph.db"
    build_current_store(db)
    conn = store_reader.connect(db)

    first = store_reader.read_episodes(conn)
    second = store_reader.read_episodes(conn, start=1)
    session = store_reader.read_episodes(conn, session="s2", limit=5)
    listed = store_reader.sessions(conn)
    conn.close()

    assert [e["content"] for e in first] == ["first thought"]
    assert second[0]["content"] == "second thought" and second[0]["position"] == 1
    assert [e["content"] for e in session] == ["later thought"]
    assert [s["session_id"] for s in listed] == ["s1", "s2"]


def test_passages_follow_session_start_then_position(tmp_path):
    db = tmp_path / "reader.db"
    build_reader(db)
    before = sha(db)

    report = store_reader.survey(db)
    conn = store_reader.connect(db)
    passages = store_reader.read_passages(conn, limit=10)
    conn.close()

    assert report["kind"] == "reader"
    assert report["reactions"]["sessions"] == 2
    assert [p["passage"] for p in passages] == ["p1", "p2", "p3"]
    assert sha(db) == before


def test_connection_refuses_writes(tmp_path):
    db = tmp_path / "graph.db"
    build_old_store(db)
    conn = store_reader.connect(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM episodes")
    conn.close()


def test_missing_store_is_not_created(tmp_path):
    missing = tmp_path / "absent.db"
    assert store_reader.main(["survey", str(missing)]) == 1
    assert not missing.exists()


def test_cli_immutable_read_and_json(tmp_path, capsys):
    db = tmp_path / "graph.db"
    build_old_store(db)

    assert store_reader.main(["--immutable", "--json", "read", str(db), "--limit", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["content"] for e in out] == ["reading begins", "wings do not flap"]
    assert not db.with_name("graph.db-shm").exists()
