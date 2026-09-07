from __future__ import annotations

import hashlib
import json
import sqlite3
from io import StringIO
from pathlib import Path

import pytest

import lighthouse_export
from lighthouse_export import (
    ExportError,
    export_lighthouse_shadow,
    main,
    write_lighthouse_shadow,
)


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


def add_recall(
    connection: sqlite3.Connection,
    recall_id: str,
    query: str,
    memory_ids: list[str],
) -> None:
    connection.execute(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        (
            "recall",
            json.dumps(memory_ids),
            json.dumps(
                {
                    "recall_id": recall_id,
                    "query": query,
                    "session_id": "must-not-export",
                    "margin": {"must": "not export"},
                }
            ),
        ),
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

    assert document["formatVersion"] == "1.1"
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


def test_streams_sensitive_rows_instead_of_bulk_fetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "graph.db"
    writer = build_database(database)
    add_memory(writer, "episodes", "work", "private memory text", "work")
    add_recall(writer, "turn", "private query text", ["work"])
    writer.commit()
    writer.close()

    real = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    real.row_factory = sqlite3.Row
    real.execute("PRAGMA query_only=ON")
    real.execute("BEGIN")

    class StreamingOnlyCursor:
        def __init__(self, cursor: sqlite3.Cursor):
            self.cursor = cursor

        def __iter__(self):
            return iter(self.cursor)

        def fetchall(self) -> None:
            raise AssertionError("sensitive rows must not be fetched in bulk")

    class StreamingOnlyConnection:
        def __getattr__(self, name: str):
            return getattr(real, name)

        def execute(self, sql: str, parameters: tuple[object, ...] = ()):
            cursor = real.execute(sql, parameters)
            if "content, content_hash" in sql or "target_ids, context" in sql:
                return StreamingOnlyCursor(cursor)
            return cursor

    monkeypatch.setattr(
        lighthouse_export,
        "_open_readonly",
        lambda _database: StreamingOnlyConnection(),
    )

    document, _ = export_lighthouse_shadow(database, instance="test")

    assert len(document["memories"]) == 1
    assert len(document["recallTraces"]) == 1


def test_rejects_missing_schema(tmp_path: Path) -> None:
    database = tmp_path / "missing.db"
    sqlite3.connect(database).close()

    with pytest.raises(ExportError, match="MISSING_TABLE"):
        export_lighthouse_shadow(database, instance="test")


def test_closes_connection_when_readonly_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "graph.db"
    database.touch()

    class SetupFailureConnection:
        row_factory = None
        closed = False

        def execute(self, _sql: str) -> None:
            raise RuntimeError("setup failed")

        def close(self) -> None:
            self.closed = True

    connection = SetupFailureConnection()
    monkeypatch.setattr(
        lighthouse_export.sqlite3,
        "connect",
        lambda *_args, **_kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        export_lighthouse_shadow(database, instance="test")

    assert connection.closed is True


def test_closes_connection_even_when_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "graph.db"
    writer = build_database(database)
    writer.commit()
    writer.close()
    real = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    real.row_factory = sqlite3.Row
    real.execute("PRAGMA query_only=ON")
    real.execute("BEGIN")

    class RollbackFailureConnection:
        closed = False

        def __getattr__(self, name: str):
            return getattr(real, name)

        def rollback(self) -> None:
            raise RuntimeError("rollback failed")

        def close(self) -> None:
            self.closed = True
            real.close()

    connection = RollbackFailureConnection()
    monkeypatch.setattr(lighthouse_export, "_open_readonly", lambda _database: connection)

    with pytest.raises(RuntimeError, match="rollback failed"):
        export_lighthouse_shadow(database, instance="test")

    assert connection.closed is True


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


def test_exports_provenance_and_only_complete_work_traces(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work-episode", "work text", "work")
    add_memory(connection, "episodes", "personal-episode", "personal text", "personal")
    add_memory(connection, "semantics", "work-semantic", "fact text", "work")
    connection.executemany(
        "INSERT INTO semantic_sources VALUES (?, ?)",
        [
            ("work-semantic", "work-episode"),
            ("work-semantic", "personal-episode"),
        ],
    )
    add_recall(
        connection,
        "eligible",
        "technical query",
        ["work-semantic", "work-episode"],
    )
    add_recall(
        connection,
        "mixed",
        "private query",
        ["work-episode", "personal-episode"],
    )
    add_recall(connection, "unknown", "unknown query", ["work-episode", "missing"])
    connection.commit()
    connection.close()

    document, audit = export_lighthouse_shadow(database, instance="test")

    assert document["edges"] == [
        {
            "source": "work-episode",
            "target": "work-semantic",
            "type": "provenance",
            "weight": 1.0,
            "directed": True,
        }
    ]
    assert document["recallTraces"] == [
        {
            "turnId": "eligible",
            "queryDigest": {
                "algorithm": "sha256",
                "value": digest("technical query"),
            },
            "contextPath": ["memory", "technical"],
            "candidates": [
                {"memoryId": "work-semantic", "rank": 1},
                {"memoryId": "work-episode", "rank": 2},
            ],
        }
    ]
    serialized = json.dumps(document)
    for forbidden in (
        "technical query",
        "private query",
        "personal-episode",
        "must-not-export",
    ):
        assert forbidden not in serialized
    assert audit.provenance_edges == 1
    assert audit.omitted_provenance_edges == 1
    assert audit.eligible_traces == 1
    assert audit.excluded_outside_work_set == 2


def test_classifies_malformed_empty_and_duplicate_candidate_logs(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work", "work text", "work")
    connection.executemany(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        [
            ("recall", "not-json", "not-json"),
            (
                "recall",
                "[]",
                json.dumps({"recall_id": "empty", "query": "q"}),
            ),
            (
                "recall",
                json.dumps(["work", "work"]),
                json.dumps({"recall_id": "dupe", "query": "q"}),
            ),
        ],
    )
    connection.commit()
    connection.close()

    _, audit = export_lighthouse_shadow(database, instance="test")

    assert audit.excluded_malformed == 1
    assert audit.excluded_empty == 1
    assert audit.excluded_duplicate_candidates == 1


def test_rejects_duplicate_recall_identity(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work", "work text", "work")
    add_recall(connection, "same", "first secret", ["work"])
    add_recall(connection, "same", "second secret", ["work"])
    connection.commit()
    connection.close()

    with pytest.raises(ExportError, match="DUPLICATE_RECALL_TRACE"):
        export_lighthouse_shadow(database, instance="test")


def populate_deterministic_database(path: Path, *, reversed_order: bool) -> None:
    connection = build_database(path)
    memories = [
        ("episodes", "episode-a", "episode text", "work"),
        ("semantics", "semantic-b", "semantic text", "work"),
    ]
    recalls = [
        ("turn-b", "query b", ["semantic-b"]),
        ("turn-a", "query a", ["episode-a"]),
    ]
    if reversed_order:
        memories.reverse()
        recalls.reverse()
    for memory in memories:
        add_memory(connection, *memory)
    connection.execute(
        "INSERT INTO semantic_sources VALUES (?, ?)",
        ("semantic-b", "episode-a"),
    )
    for recall in recalls:
        add_recall(connection, *recall)
    connection.commit()
    connection.close()


def test_projection_is_independent_of_database_insertion_order(tmp_path: Path) -> None:
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    populate_deterministic_database(first, reversed_order=False)
    populate_deterministic_database(second, reversed_order=True)

    first_document, first_audit = export_lighthouse_shadow(first, instance="test")
    second_document, second_audit = export_lighthouse_shadow(second, instance="test")

    assert first_document == second_document
    assert first_audit == second_audit


def test_cli_writes_canonical_export_and_safe_audit(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    memory_id = "00000000-0000-4000-8000-000000000001"
    recall_id = "00000000-0000-4000-8000-000000000002"
    add_memory(connection, "episodes", memory_id, "raw memory secret", "work")
    add_recall(connection, recall_id, "raw query secret", [memory_id])
    connection.commit()
    connection.close()
    output = tmp_path / "local.engram.json"
    stdout, stderr = StringIO(), StringIO()

    code = main(
        [
            "--db",
            str(database),
            "--instance",
            "engram-test",
            "--output",
            str(output),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == ""
    written = output.read_text(encoding="utf-8")
    assert written.endswith("\n") and not written.endswith("\n\n")
    assert written == (
        json.dumps(
            json.loads(written),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    diagnostics = json.loads(stderr.getvalue())
    assert diagnostics["ok"] is True
    assert diagnostics["audit"]["eligible_traces"] == 1
    assert "raw memory secret" not in written
    assert "raw query secret" not in written
    for secret in ("raw memory secret", "raw query secret", memory_id, recall_id):
        assert secret not in stdout.getvalue() + stderr.getvalue()


def test_cli_refuses_overwrite_without_changing_existing_file(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    connection.commit()
    connection.close()
    output = tmp_path / "existing.engram.json"
    output.write_text("keep-me", encoding="utf-8")
    stderr = StringIO()

    code = main(
        ["--db", str(database), "--instance", "test", "--output", str(output)],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert output.read_text(encoding="utf-8") == "keep-me"
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "OUTPUT_EXISTS"}


def test_writer_removes_a_new_incomplete_file_when_serialization_fails(tmp_path: Path) -> None:
    output = tmp_path / "incomplete.engram.json"

    with pytest.raises(TypeError):
        write_lighthouse_shadow(output, {"invalid": object()})

    assert not output.exists()


def test_writer_removes_incomplete_output_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "interrupted.engram.json"
    original_open = Path.open

    class InterruptingFile:
        def __enter__(self):
            self.stream = original_open(output, "x", encoding="utf-8")
            return self

        def write(self, value: str) -> None:
            self.stream.write(value[:1])
            self.stream.flush()
            raise KeyboardInterrupt

        def __exit__(self, *_args: object) -> None:
            self.stream.close()

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: InterruptingFile())

    with pytest.raises(KeyboardInterrupt):
        write_lighthouse_shadow(output, {"valid": True})

    assert not output.exists()


def test_cli_removes_incomplete_output_after_encoding_failure(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    connection.commit()
    connection.close()
    output = tmp_path / "incomplete.engram.json"
    stderr = StringIO()

    code = main(
        [
            "--db",
            str(database),
            "--instance",
            "invalid-surrogate-\ud800",
            "--output",
            str(output),
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert not output.exists()
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "OUTPUT_WRITE_FAILED"}


def test_cli_normalizes_cleanup_failure_without_leaking_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    connection.commit()
    connection.close()
    output = tmp_path / "private-output-path.engram.json"
    stderr = StringIO()

    def fail_cleanup(_path: Path, *, missing_ok: bool = False) -> None:
        _ = missing_ok
        raise OSError("private cleanup path")

    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    code = main(
        [
            "--db",
            str(database),
            "--instance",
            "invalid-surrogate-\ud800",
            "--output",
            str(output),
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert json.loads(stderr.getvalue()) == {
        "ok": False,
        "code": "OUTPUT_CLEANUP_FAILED",
    }
    assert "private" not in stderr.getvalue()


def test_cli_normalizes_unexpected_failures_without_leaking_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    connection.commit()
    connection.close()
    stderr = StringIO()

    def fail_write(_output: Path, _document: dict[str, object]) -> None:
        raise RuntimeError("private output path and source details")

    monkeypatch.setattr(lighthouse_export, "write_lighthouse_shadow", fail_write)

    code = main(
        [
            "--db",
            str(database),
            "--instance",
            "test",
            "--output",
            "private-output-path",
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "INTERNAL_ERROR"}
    assert "private" not in stderr.getvalue()


def test_cli_reports_corrupt_database_without_leaking_source_bytes(tmp_path: Path) -> None:
    database = tmp_path / "corrupt.db"
    database.write_text("raw database secret", encoding="utf-8")
    stderr = StringIO()

    code = main(
        [
            "--db",
            str(database),
            "--instance",
            "test",
            "--output",
            str(tmp_path / "output.engram.json"),
        ],
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "DATABASE_READ_FAILED"}
    assert "raw database secret" not in stderr.getvalue()


def test_cli_reports_usage_without_echoing_arguments() -> None:
    stdout = StringIO()
    stderr = StringIO()

    code = main(
        ["--db", "private-database-path"],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 1
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "USAGE"}
    assert "private-database-path" not in stderr.getvalue()


def add_receipt_row(connection: sqlite3.Connection, receipt: dict) -> None:
    connection.execute(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        (
            "lighthouse_receipt",
            json.dumps([]),
            json.dumps({"recall_id": "r", "receipt": receipt}),
        ),
    )


def sample_receipt(turn: str = "t1") -> dict:
    from lighthouse_receipts import build_receipt

    return build_receipt(
        receiver="engram",
        turn_id=turn,
        context={
            "id": "memory/technical",
            "path": ["memory", "technical"],
        },
        purpose="session-recall",
        sources=[],
        selected=[],
        delivered=[],
        receiver_rule=None,
        issued_at="2026-09-01T00:00:00+00:00",
    )


def test_export_carries_valid_receipts_and_drops_invalid(tmp_path):
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_receipt_row(connection, sample_receipt("t1"))
    bad = sample_receipt("t2")
    bad["payload"]["injected"] = True
    add_receipt_row(connection, bad)
    connection.commit()
    connection.close()

    document, audit = export_lighthouse_shadow(database, instance="engram-local")

    assert document["formatVersion"] == "1.1"
    assert [
        receipt["payload"]["turnId"] for receipt in document["receipts"]
    ] == ["t1"]
    assert audit.receipts == 1
    assert audit.excluded_invalid_receipts == 1
    assert "query" not in json.dumps(document)


def test_export_without_receipts_has_empty_list(tmp_path):
    database = tmp_path / "graph.db"
    build_database(database).close()

    document, audit = export_lighthouse_shadow(database, instance="engram-local")

    assert document["receipts"] == []
    assert audit.receipts == 0
