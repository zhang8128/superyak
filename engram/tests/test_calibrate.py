from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

import calibrate
from storage import Storage

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def vec(seed: int, dim: int = 768, noise: float = 0.05) -> list[float]:
    rng = np.random.default_rng(seed)
    base = np.zeros(dim)
    base[seed % 3] = 1.0  # three clusters of directions
    v = base + noise * rng.standard_normal(dim)
    return (v / np.linalg.norm(v)).tolist()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_store(path: Path) -> dict:
    """Fresh, stale and core episodes, and one conflated semantic."""
    store = Storage(str(path))
    ids = []
    for i in range(12):
        eid = str(uuid.uuid4())
        store.add_episode(eid, f"s{i % 2}", f"episode {i}", embedding=vec(i))
        ids.append(eid)
    old = (NOW - timedelta(days=200)).isoformat()
    fresh = (NOW - timedelta(hours=1)).isoformat()
    store.conn.execute("UPDATE episodes SET last_accessed = ?, compressed = 1", (old,))
    store.conn.execute("UPDATE episodes SET last_accessed = ? WHERE id = ?", (fresh, ids[0]))
    store.conn.execute("UPDATE episodes SET core = 1 WHERE id = ?", (ids[1],))
    store.conn.commit()
    # Sources drawn from two orthogonal clusters: a conflated semantic.
    store.add_semantic(str(uuid.uuid4()), "rivers and also cheese", "fact", 0.8,
                       vec(0), [ids[i] for i in (0, 3, 6, 9, 1, 4, 7, 10)])
    store.close()
    return {"fresh": ids[0], "core": ids[1], "stale": ids[2:]}


def test_calibration_leaves_source_untouched_and_reports(tmp_path):
    src = tmp_path / "src" / "graph.db"
    src.parent.mkdir()
    build_store(src)
    before = sha(src)

    report = calibrate.calibrate(src, tmp_path / "out", now=NOW)

    assert report["source_unchanged"] is True
    assert sha(src) == before
    assert report["source"]["sha256"] == before
    assert report["source_side_files_created"] == []
    assert sorted(p.name for p in src.parent.iterdir()) == ["graph.db"]
    a = report["analyses"]
    assert "error" not in a["first_open"], a["first_open"]
    assert "error" not in a["cohesion"], a["cohesion"]
    assert "error" not in a["persistence"], a["persistence"]
    assert a["cohesion"]["measured"] == 1
    assert "error" not in a["paths"], a["paths"]
    assert a["paths"]["sessions_with_paths"] == 2 and a["paths"]["changes"] == 0
    assert a["cohesion"]["hottest"][0]["energy"] > 0.5
    out = tmp_path / "out"
    assert json.loads((out / "report.json").read_text())["source_unchanged"] is True
    assert "Calibration report" in (out / "report.md").read_text()
    assert not (out / "snapshot.db").stat().st_mode & 0o222  # snapshot is read-only


def test_first_open_preview_prunes_only_stale_non_core(tmp_path):
    src = tmp_path / "graph.db"
    ids = build_store(src)
    ro = Storage.open_read_only(src)
    preview = calibrate.first_open_preview(ro.conn, NOW)
    ro.close()

    pruned = set(preview["would_prune_ids"])
    assert pruned == set(ids["stale"])
    assert preview["would_prune_to_cold"] == 10


def test_decay_preview_matches_apply_decay(tmp_path):
    """The preview's formula must stay in step with Storage.apply_decay."""
    src = tmp_path / "graph.db"
    build_store(src)
    scratch = tmp_path / "scratch.db"
    shutil.copyfile(src, scratch)

    now = datetime.now(timezone.utc)
    ro = Storage.open_read_only(src)
    rows = ro.conn.execute(
        "SELECT id, accessed_count, last_accessed, created_at FROM episodes WHERE core = 0"
    ).fetchall()
    expected = {r["id"]: calibrate.decay_strength(
        r["accessed_count"], r["last_accessed"] or r["created_at"], now) for r in rows}
    ro.close()

    store = Storage(str(scratch))
    store.apply_decay(decay_exponent=calibrate.DECAY_EXPONENT, min_interval_minutes=0)
    actual = dict(store.conn.execute(
        "SELECT id, decay_strength FROM episodes WHERE core = 0").fetchall())
    store.close()

    for eid, strength in expected.items():
        assert actual[eid] == pytest.approx(strength, abs=0.002)


def build_migration_001_store(path: Path, tmp_path: Path) -> None:
    """A store exactly as migration 001 left it, holding one episode."""
    mig = tmp_path / "mig001"
    mig.mkdir()
    shutil.copy(next(Path("migrations").glob("001_*.sql")), mig)
    Storage(str(path), migrations_dir=str(mig)).close()
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO episodes (id, session_id, content, episode_type, created_at)"
                 " VALUES ('a', 's', 'reading begins', 'note', '2026-03-20T00:00:00')")
    conn.commit()
    conn.close()


def test_old_schema_store_migrates_only_the_working_copy(tmp_path):
    src = tmp_path / "graph.db"
    build_migration_001_store(src, tmp_path)
    before = sha(src)

    report = calibrate.calibrate(src, tmp_path / "out", now=NOW)

    assert sha(src) == before and report["source_unchanged"]
    assert report["snapshot"]["schema"]["applied"] == [1]
    assert 27 in report["migration"]["applied"]
    working = tmp_path / "out" / "working.db"
    assert 27 in store_schema(working)
    assert store_schema(tmp_path / "out" / "snapshot.db") == [1]
    conn = sqlite3.connect(f"file:{working}?mode=ro", uri=True)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    hits = conn.execute("SELECT rowid FROM episode_fts WHERE episode_fts MATCH 'reading'").fetchall()
    conn.close()
    assert len(hits) == 1  # pre-002 episodes are indexed, so updates stay valid


def test_pending_wal_pages_are_included_in_snapshot(tmp_path):
    src = tmp_path / "graph.db"
    build_store(src)
    live = sqlite3.connect(src)  # an open writer keeps its pages in -wal
    live.execute("PRAGMA wal_autocheckpoint=0")
    live.execute("UPDATE episodes SET content = 'written after checkpoint' WHERE core = 1")
    live.commit()
    assert src.with_name("graph.db-wal").stat().st_size > 0

    report = calibrate.calibrate(src, tmp_path / "out", now=NOW)
    live.close()

    snap = sqlite3.connect(f"file:{tmp_path / 'out' / 'snapshot.db'}?mode=ro", uri=True)
    content = snap.execute("SELECT content FROM episodes WHERE core = 1").fetchone()[0]
    snap.close()
    assert content == "written after checkpoint"
    assert report["source_unchanged"]


def store_schema(path: Path) -> list[int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return sorted(r[0] for r in conn.execute("SELECT version FROM schema_version"))
    finally:
        conn.close()


def test_no_migrate_records_analysis_errors_without_failing(tmp_path):
    src = tmp_path / "graph.db"
    conn = sqlite3.connect(src)
    conn.executescript(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT,"
        " content TEXT NOT NULL, episode_type TEXT, created_at TEXT NOT NULL);"
    )
    conn.close()

    report = calibrate.calibrate(src, tmp_path / "out", migrate=False, now=NOW)

    assert report["migration"]["applied"] == []
    assert "error" in report["analyses"]["first_open"]  # no decay columns yet
    assert report["source_unchanged"]


def test_existing_output_directory_is_refused(tmp_path):
    src = tmp_path / "graph.db"
    build_store(src)
    (tmp_path / "out").mkdir()
    assert calibrate.main([str(src), "--out", str(tmp_path / "out")]) == 1
