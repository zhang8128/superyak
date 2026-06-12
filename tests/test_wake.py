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


def _run_wake(project_dir: str, project_root: str | None = None,
              extra_env: dict | None = None) -> dict:
    """Run wake.py as a subprocess and parse JSON output."""
    env = {**os.environ, "ENGRAM_HOME": project_dir}
    env.pop("ENGRAM_ASSESSMENT", None)  # never inherit from the outer shell
    if project_root is not None:
        env["ENGRAM_PROJECT_ROOT"] = project_root
    if extra_env:
        env.update(extra_env)
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

    def test_wake_displays_notice_implication(self, tmp_path):
        """Wake output should show perceptual format when notice/implication present."""
        from storage import Storage
        db_path = tmp_path / ".engram" / "graph.db"
        db_path.parent.mkdir(parents=True)
        store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
        sem_id = str(uuid.uuid4())
        store.add_semantic(id=sem_id, content="test", kind="preference",
                           confidence=0.5, embedding=[0.1]*768, source_episode_ids=[])
        store.add_instinct(
            id="inst-1", trigger="preference", action="be terse",
            source_semantic_ids=[sem_id],
            notice="when building code and implementing features",
            implication="keep communication focused and direct",
        )
        store.close()

        output = _run_wake(str(tmp_path))
        msg = output.get("systemMessage", "")
        # Should display perceptual format
        assert "Attend to:" in msg
        assert "when building code" in msg


class TestWakeAssessment:
    def _make_store(self, tmp_path):
        from storage import Storage
        db_dir = tmp_path / ".engram"
        db_dir.mkdir()
        return Storage(str(db_dir / "graph.db"), migrations_dir=MIGRATIONS_DIR)

    def test_scheduled_assessment_emits_marker_only(self, tmp_path):
        store = self._make_store(tmp_path)
        store.add_instinct(
            id=str(uuid.uuid4()), trigger="preference",
            action="Be curious about unexpected results",
            source_semantic_ids=[], strength=0.7,
        )
        store.schedule_assessment(id="a-1", scheduled_by="self", reason="baseline")
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"CLAUDE_SESSION_ID": "s-99"})
        msg = output["systemMessage"]
        assert "Assessment Session" in msg
        assert "assessment_report" in msg
        # The device is off: no instinct content, no orientation sections
        assert "Be curious about unexpected results" not in msg
        assert "Your instincts" not in msg
        assert "What you know" not in msg

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assessments WHERE id = 'a-1'").fetchone()
        assert row["status"] == "active"
        assert row["session_id"] == "s-99"
        assert row["started_at"] is not None
        conn.close()

    def test_no_scheduled_assessment_normal_wake(self, tmp_path):
        store = self._make_store(tmp_path)
        store.close()
        output = _run_wake(str(tmp_path))
        assert "Assessment Session" not in output["systemMessage"]
        assert "0 episodes" in output["systemMessage"]

    def test_env_skip_cancels_scheduled(self, tmp_path):
        store = self._make_store(tmp_path)
        store.schedule_assessment(id="a-1", scheduled_by="self")
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"ENGRAM_ASSESSMENT": "skip"})
        assert "Assessment Session" not in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM assessments WHERE id = 'a-1'").fetchone()
        assert row["status"] == "skipped"
        conn.close()

    def test_env_next_creates_and_activates(self, tmp_path):
        store = self._make_store(tmp_path)
        store.close()

        output = _run_wake(
            str(tmp_path),
            extra_env={"ENGRAM_ASSESSMENT": "next", "CLAUDE_SESSION_ID": "s-7"},
        )
        assert "Assessment Session" in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM assessments").fetchone()
        assert row["status"] == "active"
        assert row["scheduled_by"] == "user"
        conn.close()

    def test_stale_active_marked_abandoned(self, tmp_path):
        store = self._make_store(tmp_path)
        store.schedule_assessment(id="a-old", scheduled_by="self")
        store.conn.execute(
            "UPDATE assessments SET status = 'active', session_id = 's-old' "
            "WHERE id = 'a-old'"
        )
        store.conn.commit()
        store.close()

        output = _run_wake(str(tmp_path), extra_env={"CLAUDE_SESSION_ID": "s-new"})
        # Stale active row abandoned; no scheduled row left, so normal wake
        assert "Assessment Session" not in output["systemMessage"]

        import sqlite3
        conn = sqlite3.connect(str(tmp_path / ".engram" / "graph.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM assessments WHERE id = 'a-old'").fetchone()
        assert row["status"] == "abandoned"
        conn.close()
