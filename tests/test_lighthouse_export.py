from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from lighthouse_export import ExportError, export_lighthouse_shadow


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE episodes (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT,
            lane TEXT NOT NULL
        );
        CREATE TABLE semantics (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT,
            lane TEXT NOT NULL
        );
        CREATE TABLE semantic_sources (
            semantic_id TEXT NOT NULL,
            episode_id TEXT NOT NULL
        );
        CREATE TABLE memory_log (
            event_type TEXT NOT NULL,
            target_ids JSON,
            context JSON
        );
        """
    )
    return connection


def add_memory(
    connection: sqlite3.Connection,
    table: str,
    memory_id: str,
    content: str,
    lane: str,
) -> None:
    assert table in {"episodes", "semantics"}
    connection.execute(
        f"INSERT INTO {table} (id, content, content_hash, lane) VALUES (?, ?, ?, ?)",
        (memory_id, content, digest(content), lane),
    )


def test_exports_only_opaque_work_memories_without_mutating_source(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work-episode", "private technical text", "work")
    add_memory(
        connection,
        "episodes",
        "personal-episode",
        "private relationship text",
        "personal",
    )
    add_memory(connection, "semantics", "work-semantic", "private distilled fact", "work")
    connection.commit()
    connection.close()
    before = database.read_bytes()

    document, audit = export_lighthouse_shadow(database, instance="engram-test")

    assert document["formatVersion"] == "1.0"
    assert document["instance"] == "engram-test"
    assert document["context"] == {
        "id": "memory/technical",
        "path": ["memory", "technical"],
    }
    assert [memory["id"] for memory in document["memories"]] == [
        "work-episode",
        "work-semantic",
    ]
    assert document["memories"][0] == {
        "id": "work-episode",
        "layer": "episode",
        "contentDigest": {
            "algorithm": "sha256",
            "value": digest("private technical text"),
        },
        "contextPath": ["memory", "technical"],
        "lane": "work",
        "origin": "lived",
    }
    serialized = json.dumps(document)
    assert "private technical text" not in serialized
    assert "private relationship text" not in serialized
    assert "personal-episode" not in serialized
    assert audit.work_episodes == 1
    assert audit.work_semantics == 1
    assert database.read_bytes() == before


def test_rejects_missing_schema(tmp_path: Path) -> None:
    database = tmp_path / "missing.db"
    sqlite3.connect(database).close()

    with pytest.raises(ExportError, match="MISSING_TABLE"):
        export_lighthouse_shadow(database, instance="test")


def test_rejects_content_hash_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "hash.db"
    connection = build_database(database)
    connection.execute(
        "INSERT INTO episodes VALUES (?, ?, ?, ?)",
        ("work", "source text", "0" * 64, "work"),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ExportError, match="CONTENT_HASH_MISMATCH"):
        export_lighthouse_shadow(database, instance="test")


@pytest.mark.parametrize("instance", ["", "   "])
def test_rejects_blank_instance(tmp_path: Path, instance: str) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    connection.commit()
    connection.close()

    with pytest.raises(ExportError, match="INVALID_INSTANCE"):
        export_lighthouse_shadow(database, instance=instance)
