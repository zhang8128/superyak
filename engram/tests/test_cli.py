"""Tests for engram CLI — fork, drop, list subcommands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cli import drop_instance, fork_instance, list_instances
from federation import InstanceRegistry


def _make_genome_db(engram_dir: Path) -> Path:
    """Create a minimal genome graph.db with a core episode row."""
    genome_dir = engram_dir / "genome"
    genome_dir.mkdir(parents=True, exist_ok=True)
    db_path = genome_dir / "graph.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS episodes (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT,
            source TEXT,
            core INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute(
        "INSERT INTO episodes (id, content, content_hash, source, core) "
        "VALUES ('ep-genome-1', 'genome seed memory', 'abc123', 'test', 2)"
    )
    conn.commit()
    conn.close()
    return db_path


class TestForkInstance:
    def test_fork_creates_instance_db(self, tmp_path):
        """Forking from genome should create an instance DB."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)

        inst_db = tmp_path / "instances" / "alpha" / "graph.db"
        assert inst_db.exists()

    def test_fork_copies_genome_episode(self, tmp_path):
        """The forked DB should contain the genome episode."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)

        inst_db = tmp_path / "instances" / "alpha" / "graph.db"
        conn = sqlite3.connect(str(inst_db))
        row = conn.execute(
            "SELECT content FROM episodes WHERE id = 'ep-genome-1'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "genome seed memory"

    def test_fork_registers_in_registry(self, tmp_path):
        """Forking should add the instance to instances.json."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)

        reg = InstanceRegistry(tmp_path / "instances.json")
        info = reg.get("alpha")
        assert info is not None
        assert info["forked_from"] == "genome"
        assert "forked_at" in info

    def test_fork_from_another_instance(self, tmp_path):
        """Fork from an existing instance (not genome)."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)
        fork_instance("beta", engram_dir=tmp_path, from_source="alpha")

        inst_db = tmp_path / "instances" / "beta" / "graph.db"
        assert inst_db.exists()

        reg = InstanceRegistry(tmp_path / "instances.json")
        info = reg.get("beta")
        assert info["forked_from"] == "alpha"

    def test_fork_missing_source_exits(self, tmp_path):
        """Fork with no genome should call sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            fork_instance("alpha", engram_dir=tmp_path)
        assert exc_info.value.code == 1

    def test_fork_duplicate_name_exits(self, tmp_path):
        """Forking a name that already exists should sys.exit(1)."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            fork_instance("alpha", engram_dir=tmp_path)
        assert exc_info.value.code == 1


class TestDropInstance:
    def test_drop_removes_directory(self, tmp_path):
        """Dropping an instance should remove its directory."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)

        inst_dir = tmp_path / "instances" / "alpha"
        assert inst_dir.exists()

        drop_instance("alpha", engram_dir=tmp_path)
        assert not inst_dir.exists()

    def test_drop_removes_from_registry(self, tmp_path):
        """Dropping an instance should remove it from instances.json."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)
        drop_instance("alpha", engram_dir=tmp_path)

        reg = InstanceRegistry(tmp_path / "instances.json")
        assert reg.get("alpha") is None

    def test_drop_unknown_instance_exits(self, tmp_path):
        """Dropping a non-existent instance should sys.exit(1)."""
        # Need an instances.json (even empty) so registry loads cleanly
        (tmp_path / "instances.json").write_text("{}")
        with pytest.raises(SystemExit) as exc_info:
            drop_instance("nonexistent", engram_dir=tmp_path)
        assert exc_info.value.code == 1

    def test_drop_cleans_reader_receipts_in_signals(self, tmp_path):
        """Drop should remove the instance's exact reader receipts."""
        from federation import SignalBus

        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)

        # Create a signals.db with a message seen by alpha
        signals_db = tmp_path / "signals.db"
        bus = SignalBus(signals_db)
        msg_id = bus.send("genome", None, "fact", "some content")
        bus.mark_seen(msg_id, "alpha")
        bus.close()

        # Verify alpha has read the message before drop
        bus2 = SignalBus(signals_db)
        row = bus2.conn.execute(
            "SELECT instance FROM reads WHERE message_id = ? AND instance = 'alpha'", (msg_id,)
        ).fetchone()
        assert row[0] == "alpha"
        bus2.close()

        drop_instance("alpha", engram_dir=tmp_path)

        # Verify alpha's receipt is removed
        bus3 = SignalBus(signals_db)
        row = bus3.conn.execute(
            "SELECT instance FROM reads WHERE message_id = ? AND instance = 'alpha'", (msg_id,)
        ).fetchone()
        assert row is None
        bus3.close()


class TestListInstances:
    def test_list_empty(self, tmp_path, capsys):
        """list_instances with no registry prints 'No instances registered.'"""
        list_instances(engram_dir=tmp_path)
        out = capsys.readouterr().out
        assert "No instances registered." in out

    def test_list_shows_instances(self, tmp_path, capsys):
        """list_instances should print forked instance names."""
        _make_genome_db(tmp_path)
        fork_instance("alpha", engram_dir=tmp_path)
        fork_instance("beta", engram_dir=tmp_path, from_source="alpha")

        list_instances(engram_dir=tmp_path)
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" in out
        assert "genome" in out
        assert "alpha" in out  # beta forked_from alpha
