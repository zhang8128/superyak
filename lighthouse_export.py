"""Read-only projection of Engram recall history into Lighthouse's portable profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

from lighthouse_receipts import ReceiptError, validate_receipt


TECHNICAL_CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
REQUIRED_SCHEMA = {
    "episodes": {"id", "content", "content_hash", "lane"},
    "semantics": {"id", "content", "content_hash", "lane"},
    "semantic_sources": {"semantic_id", "episode_id"},
    "memory_log": {"event_type", "target_ids", "context"},
}


class ExportError(ValueError):
    """A stable, privacy-safe export failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExportAudit:
    work_episodes: int
    work_semantics: int
    provenance_edges: int
    omitted_provenance_edges: int
    eligible_traces: int
    excluded_empty: int
    excluded_malformed: int
    excluded_duplicate_candidates: int
    excluded_outside_work_set: int
    receipts: int = 0
    excluded_invalid_receipts: int = 0


def _open_readonly(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise ExportError("DATABASE_NOT_FOUND")
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
    except BaseException:
        try:
            connection.close()
        except BaseException:
            pass
        raise
    return connection


def _preflight(connection: sqlite3.Connection) -> None:
    for table, required_columns in REQUIRED_SCHEMA.items():
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            raise ExportError("MISSING_TABLE")
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not required_columns.issubset(columns):
            raise ExportError("MISSING_COLUMN")


def _content_digest(content: object, stored: object) -> str:
    if not isinstance(content, str) or not isinstance(stored, str):
        raise ExportError("CONTENT_HASH_MISMATCH")
    actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if stored != actual:
        raise ExportError("CONTENT_HASH_MISMATCH")
    return actual


def _project_memories(
    connection: sqlite3.Connection,
) -> tuple[list[dict[str, object]], int, int]:
    memories: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    counts: dict[str, int] = {"episode": 0, "semantic": 0}
    projections = (
        ("episodes", "episode", "lived"),
        ("semantics", "semantic", "organic"),
    )
    for table, layer, origin in projections:
        for row in connection.execute(
            f"SELECT id, content, content_hash FROM {table} WHERE lane = ?",
            ("work",),
        ):
            memory_id = row["id"]
            if not isinstance(memory_id, str) or not memory_id:
                raise ExportError("INVALID_MEMORY_ID")
            if memory_id in seen_ids:
                raise ExportError("DUPLICATE_MEMORY_ID")
            content_digest = _content_digest(row["content"], row["content_hash"])
            del row
            seen_ids.add(memory_id)
            memories.append(
                {
                    "id": memory_id,
                    "layer": layer,
                    "contentDigest": {
                        "algorithm": "sha256",
                        "value": content_digest,
                    },
                    "contextPath": list(TECHNICAL_CONTEXT["path"]),
                    "lane": "work",
                    "origin": origin,
                }
            )
            counts[layer] += 1
    return sorted(memories, key=lambda memory: str(memory["id"])), counts["episode"], counts[
        "semantic"
    ]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _project_edges(
    connection: sqlite3.Connection,
    memory_ids: set[str],
) -> tuple[list[dict[str, object]], int]:
    edges: list[dict[str, object]] = []
    omitted = 0
    for row in connection.execute(
        "SELECT episode_id, semantic_id FROM semantic_sources"
    ):
        source = row["episode_id"]
        target = row["semantic_id"]
        if source not in memory_ids or target not in memory_ids:
            omitted += 1
            continue
        edges.append(
            {
                "source": source,
                "target": target,
                "type": "provenance",
                "weight": 1.0,
                "directed": True,
            }
        )
    return sorted(edges, key=_canonical_json), omitted


@dataclass(frozen=True)
class _TraceProjection:
    traces: list[dict[str, object]]
    eligible: int
    empty: int
    malformed: int
    duplicate_candidates: int
    outside_work_set: int


def _parse_json(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError
    return json.loads(value)


def _parse_trace_context(value: object) -> tuple[str, str]:
    context = _parse_json(value)
    if not isinstance(context, dict):
        raise ValueError
    turn_id = context.get("recall_id")
    query = context.get("query")
    if (
        not isinstance(turn_id, str)
        or not turn_id.strip()
        or not isinstance(query, str)
        or not query.strip()
    ):
        raise ValueError
    return turn_id, hashlib.sha256(query.encode("utf-8")).hexdigest()


def _project_traces(
    connection: sqlite3.Connection,
    memory_ids: set[str],
) -> _TraceProjection:
    traces: list[dict[str, object]] = []
    seen_turn_ids: set[str] = set()
    empty = 0
    malformed = 0
    duplicate_candidates = 0
    outside_work_set = 0
    for row in connection.execute(
        "SELECT target_ids, context FROM memory_log WHERE event_type = ?",
        ("recall",),
    ):
        raw_target_ids = row["target_ids"]
        raw_context = row["context"]
        del row
        try:
            turn_id, query_digest = _parse_trace_context(raw_context)
        except (json.JSONDecodeError, ValueError, TypeError):
            del raw_target_ids
            malformed += 1
            continue
        finally:
            del raw_context

        if turn_id in seen_turn_ids:
            raise ExportError("DUPLICATE_RECALL_TRACE")
        seen_turn_ids.add(turn_id)

        try:
            target_ids = _parse_json(raw_target_ids)
            if not isinstance(target_ids, list) or any(
                not isinstance(memory_id, str) or not memory_id for memory_id in target_ids
            ):
                raise ValueError
        except (json.JSONDecodeError, ValueError, TypeError):
            malformed += 1
            continue
        finally:
            del raw_target_ids
        if not target_ids:
            empty += 1
            continue
        if len(set(target_ids)) != len(target_ids):
            duplicate_candidates += 1
            continue
        if any(memory_id not in memory_ids for memory_id in target_ids):
            outside_work_set += 1
            continue
        traces.append(
            {
                "turnId": turn_id,
                "queryDigest": {
                    "algorithm": "sha256",
                    "value": query_digest,
                },
                "contextPath": list(TECHNICAL_CONTEXT["path"]),
                "candidates": [
                    {"memoryId": memory_id, "rank": rank}
                    for rank, memory_id in enumerate(target_ids, start=1)
                ],
            }
        )
    traces.sort(key=lambda trace: str(trace["turnId"]))
    return _TraceProjection(
        traces=traces,
        eligible=len(traces),
        empty=empty,
        malformed=malformed,
        duplicate_candidates=duplicate_candidates,
        outside_work_set=outside_work_set,
    )


def _project_receipts(
    connection: sqlite3.Connection,
) -> tuple[list[dict], int]:
    receipts: dict[str, dict] = {}
    invalid = 0
    for row in connection.execute(
        "SELECT context FROM memory_log WHERE event_type = 'lighthouse_receipt'"
    ):
        try:
            context = _parse_json(row["context"])
        except (json.JSONDecodeError, ValueError, TypeError):
            invalid += 1
            continue
        receipt = context.get("receipt") if isinstance(context, dict) else None
        if not isinstance(receipt, dict):
            invalid += 1
            continue
        try:
            validate_receipt(receipt)
        except ReceiptError:
            invalid += 1
            continue
        receipts[str(receipt["id"])] = receipt
    return [receipts[key] for key in sorted(receipts)], invalid


def export_lighthouse_shadow(
    database: Path,
    *,
    instance: str,
) -> tuple[dict[str, object], ExportAudit]:
    """Project an opaque work-lane snapshot without mutating the source database."""
    if not isinstance(instance, str) or not instance.strip():
        raise ExportError("INVALID_INSTANCE")
    connection = _open_readonly(Path(database))
    try:
        _preflight(connection)
        memories, work_episodes, work_semantics = _project_memories(connection)
        memory_ids = {str(memory["id"]) for memory in memories}
        edges, omitted_edges = _project_edges(connection, memory_ids)
        trace_projection = _project_traces(connection, memory_ids)
        receipts, invalid_receipts = _project_receipts(connection)
        if connection.total_changes != 0:
            raise ExportError("SOURCE_MUTATED")
        document: dict[str, object] = {
            "formatVersion": "1.1",
            "instance": instance,
            "context": {
                "id": TECHNICAL_CONTEXT["id"],
                "path": list(TECHNICAL_CONTEXT["path"]),
            },
            "memories": memories,
            "edges": edges,
            "recallTraces": trace_projection.traces,
            "receipts": receipts,
        }
        return document, ExportAudit(
            work_episodes=work_episodes,
            work_semantics=work_semantics,
            provenance_edges=len(edges),
            omitted_provenance_edges=omitted_edges,
            eligible_traces=trace_projection.eligible,
            excluded_empty=trace_projection.empty,
            excluded_malformed=trace_projection.malformed,
            excluded_duplicate_candidates=trace_projection.duplicate_candidates,
            excluded_outside_work_set=trace_projection.outside_work_set,
            receipts=len(receipts),
            excluded_invalid_receipts=invalid_receipts,
        )
    finally:
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()


def write_lighthouse_shadow(output: Path, document: dict[str, object]) -> None:
    """Write one new canonical export without overwriting an existing path."""
    serialized = _canonical_json(document) + "\n"
    destination = Path(output)
    created = False
    try:
        with destination.open("x", encoding="utf-8") as stream:
            created = True
            stream.write(serialized)
    except FileExistsError as error:
        raise ExportError("OUTPUT_EXISTS") from error
    except BaseException as error:
        cleanup_failed = False
        if created:
            try:
                destination.unlink(missing_ok=True)
            except BaseException:
                cleanup_failed = True
        if not isinstance(error, Exception):
            raise
        code = "OUTPUT_CLEANUP_FAILED" if cleanup_failed else "OUTPUT_WRITE_FAILED"
        raise ExportError(code) from error


def _emit(stream: TextIO, value: dict[str, object]) -> None:
    stream.write(_canonical_json(value) + "\n")


class _PrivateArgumentParser(argparse.ArgumentParser):
    """Convert parse failures to a stable code without echoing arguments."""

    def error(self, message: str) -> None:
        _ = message
        raise ExportError("USAGE")


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run the privacy-safe offline exporter CLI."""
    parser = _PrivateArgumentParser(prog="engram-lighthouse-export")
    parser.add_argument("--db", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--output", required=True)
    try:
        args = parser.parse_args(argv)
        document, audit = export_lighthouse_shadow(Path(args.db), instance=args.instance)
        write_lighthouse_shadow(Path(args.output), document)
    except ExportError as error:
        _emit(stderr, {"ok": False, "code": error.code})
        return 1
    except sqlite3.DatabaseError:
        _emit(stderr, {"ok": False, "code": "DATABASE_READ_FAILED"})
        return 1
    except Exception:
        _emit(stderr, {"ok": False, "code": "INTERNAL_ERROR"})
        return 1
    _ = stdout
    _emit(stderr, {"ok": True, "audit": asdict(audit)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
