"""Tests for the SessionStart wake hook."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).parent.parent / "hooks" / "wake.py"

# Reuse conftest fixtures for storage
MIGRATIONS_DIR = str(Path(__file__).parent.parent / "migrations")


def _run_wake(project_dir: str, project_root: str | None = None) -> dict:
    """Run wake.py as a subprocess and parse JSON output."""
    env = {**os.environ, "ENGRAM_HOME": project_dir}
    if project_root is not None:
        env["ENGRAM_PROJECT_ROOT"] = project_root
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        capture_output=True, text=True, env=env, timeout=10,
    )
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


class TestWake:
    def test_no_database(self, tmp_path):
        """No .engram dir — should produce no output."""
        output = _run_wake(str(tmp_path))
        assert output == {}

    def test_empty_database(self, tmp_path):
        """Empty database — should show zero counts."""
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

        output = _run_wake(str(tmp_path))
        msg = output["systemMessage"]
        assert "0 episodes, 0 semantics, 0 instincts" in msg

    def test_with_instincts(self, tmp_path):
        """Instincts should appear in orientation."""
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        store = Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

        store.add_instinct(
            id=str(uuid.uuid4()),
            trigger="preference",
            action="Be curious about unexpected results",
            source_semantic_ids=[],
            strength=0.7,
        )

        output = _run_wake(str(tmp_path))
        msg = output["systemMessage"]
        assert "1 instincts" in msg
        assert "Be curious about unexpected results" in msg
        assert "strength=0.70" in msg

    def test_deduplicates_instinct_semantics(self, tmp_path):
        """Semantics that match instinct actions should not appear twice."""
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        store = Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

        shared_text = "Always verify before asserting"
        sem_id = str(uuid.uuid4())
        store.add_semantic(
            id=sem_id, content=shared_text, kind="constraint",
            confidence=0.8, embedding=[0.0] * 768, source_episode_ids=[],
        )
        store.add_instinct(
            id=str(uuid.uuid4()),
            trigger="constraint",
            action=shared_text,
            source_semantic_ids=[sem_id],
            strength=0.6,
        )

        output = _run_wake(str(tmp_path))
        msg = output["systemMessage"]
        # Should appear in instincts section but NOT in semantics section
        assert msg.count(shared_text) == 1

    def test_error_resilience(self, tmp_path):
        """Corrupt DB should produce a graceful error message, not crash."""
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        (db_dir / "graph.db").write_text("not a database")

        output = _run_wake(str(tmp_path))
        msg = output.get("systemMessage", "")
        assert "wake failed" in msg.lower() or output == {}

    def test_wake_shows_instance_identity(self, tmp_path):
        """When config.toml has instance = 'agi', header should show Engram (agi)."""
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

        # Create a separate project root dir with config.toml
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".engram").mkdir()
        (project_root / ".engram" / "config.toml").write_text(
            'instance = "agi"\n'
        )

        output = _run_wake(str(tmp_path), project_root=str(project_root))
        msg = output["systemMessage"]
        assert "Engram (agi)" in msg

    def test_wake_shows_inbox_count(self, tmp_path):
        """Unread messages in signals.db should appear in orientation."""
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

        # Create signals.db with an unread message for this instance
        import sqlite3 as _sqlite3
        sig_conn = _sqlite3.connect(str(db_dir / "signals.db"))
        sig_conn.execute(
            "CREATE TABLE messages ("
            "id TEXT PRIMARY KEY, from_instance TEXT, to_instance TEXT, "
            "payload TEXT, seen_by TEXT DEFAULT '[]')"
        )
        sig_conn.execute(
            "INSERT INTO messages (id, from_instance, to_instance, payload, seen_by) "
            "VALUES ('msg1', 'other', 'agi', '{}', '[]')"
        )
        sig_conn.commit()
        sig_conn.close()

        # Config in project root
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".engram").mkdir()
        (project_root / ".engram" / "config.toml").write_text(
            'instance = "agi"\n'
        )

        output = _run_wake(str(tmp_path), project_root=str(project_root))
        msg = output["systemMessage"]
        assert "unread signal" in msg
