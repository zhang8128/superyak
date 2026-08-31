"""Read-only projection of Engram recall history into Lighthouse's portable profile."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


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


def _open_readonly(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise ExportError("DATABASE_NOT_FOUND")
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
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
        rows = connection.execute(
            f"SELECT id, content, content_hash FROM {table} WHERE lane = ?",
            ("work",),
        ).fetchall()
        for row in rows:
            memory_id = row["id"]
            if not isinstance(memory_id, str) or not memory_id:
                raise ExportError("INVALID_MEMORY_ID")
            if memory_id in seen_ids:
                raise ExportError("DUPLICATE_MEMORY_ID")
            seen_ids.add(memory_id)
            memories.append(
                {
                    "id": memory_id,
                    "layer": layer,
                    "contentDigest": {
                        "algorithm": "sha256",
                        "value": _content_digest(row["content"], row["content_hash"]),
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
        if connection.total_changes != 0:
            raise ExportError("SOURCE_MUTATED")
        document: dict[str, object] = {
            "formatVersion": "1.0",
            "instance": instance,
            "context": {
                "id": TECHNICAL_CONTEXT["id"],
                "path": list(TECHNICAL_CONTEXT["path"]),
            },
            "memories": memories,
            "edges": [],
            "recallTraces": [],
        }
        return document, ExportAudit(
            work_episodes=work_episodes,
            work_semantics=work_semantics,
            provenance_edges=0,
            omitted_provenance_edges=0,
            eligible_traces=0,
            excluded_empty=0,
            excluded_malformed=0,
            excluded_duplicate_candidates=0,
            excluded_outside_work_set=0,
        )
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
