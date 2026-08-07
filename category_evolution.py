"""Deterministic, read-only replay from the legacy category SQLite store."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Iterable, Mapping, Sequence
import uuid

from categories import Boundary, CellDraft, EvolvingCategoryStore


LEGACY_NAMESPACE = uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223")
_V2_TABLES = frozenset(
    {
        "cat_schema_version",
        "cat_events",
        "cat_contexts",
        "cat_cells",
        "cat_boundaries",
        "cat_weight_observations",
        "cat_rewrites",
        "cat_rewrite_members",
        "cat_epochs",
        "cat_epoch_parents",
        "cat_snapshots",
    }
)
_REPLAY_STATE_TABLES = (
    "cat_schema_version",
    "cat_events",
    "cat_contexts",
    "cat_cells",
    "cat_boundaries",
    "cat_weight_observations",
    "cat_rewrites",
    "cat_rewrite_members",
    "cat_epochs",
    "cat_epoch_parents",
    "cat_snapshots",
)
_IMMUTABLE_V2_TABLES = _V2_TABLES - {"cat_snapshots"}
_EXPECTED_IMMUTABILITY_TRIGGERS = frozenset(
    f"{table}_{operation}"
    for table in _IMMUTABLE_V2_TABLES
    for operation in ("no_update", "no_delete")
)
_VEC_SHADOW_TABLES = frozenset(
    {
        "cat_vectors_chunks",
        "cat_vectors_info",
        "cat_vectors_rowids",
        "cat_vectors_vector_chunks00",
        "sqlite_sequence",
    }
)
_SUPPORTED_VEC0_DDL = (
    "create virtual table cat_vectors using vec0(cell_id text primary key, embedding float[768])"
)


@dataclass(frozen=True)
class LegacyImportReport:
    legacy_total: int
    proxy_zero_cells: int
    imported_one_cells: int
    imported_two_cells: int
    opaque_cells: int
    unexplained_loss: int
    root_epoch_id: str
    snapshot_hash: str


@dataclass(frozen=True)
class _LegacyCell:
    id: str
    level: int
    source_id: str | None
    target_id: str | None
    content: str
    context: object
    created_at: object
    accessed_at: object
    access_count: object


@dataclass(frozen=True)
class _ReplayPlan:
    drafts: tuple[CellDraft, ...]
    proxy_zero_cells: int
    imported_one_cells: int
    imported_two_cells: int
    opaque_cells: int
    unexplained_loss: int


def legacy_proxy_id(memory_id: str) -> str:
    """Return the stable v2 zero-cell identity for one external memory."""
    return str(uuid.uuid5(LEGACY_NAMESPACE, f"memory:{memory_id}"))


def canonical_snapshot_hash(cell_ids: Iterable[str]) -> str:
    """Hash a snapshot's active identities independently of insertion order."""
    payload = json.dumps(sorted(set(cell_ids)), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _stable_id(kind: str, content_hash: str) -> str:
    return str(uuid.uuid5(LEGACY_NAMESPACE, f"{kind}:{content_hash}"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _type_tagged_sqlite_value(value: object) -> list[str]:
    """Encode SQLite values without collapsing distinct source representations."""
    if value is None:
        return ["null", ""]
    if isinstance(value, bool):
        return ["bool", "true" if value else "false"]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("legacy source contains a non-finite floating-point value")
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ["blob", bytes(value).hex()]
    raise ValueError(f"unsupported SQLite value type: {type(value).__name__}")


def _raw_source_fingerprint(rows: Sequence[_LegacyCell]) -> str:
    """Fingerprint every selected legacy field, including rows that become loss."""
    payload = {
        "columns": [
            "id",
            "level",
            "source_id",
            "target_id",
            "content",
            "context",
            "created_at",
            "accessed_at",
            "access_count",
        ],
        "rows": [
            [
                _type_tagged_sqlite_value(value)
                for value in (
                    row.id,
                    row.level,
                    row.source_id,
                    row.target_id,
                    row.content,
                    row.context,
                    row.created_at,
                    row.accessed_at,
                    row.access_count,
                )
            ]
            for row in rows
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _read_legacy_rows(legacy_path: Path) -> list[_LegacyCell]:
    """Read the legacy table via SQLite's read-only URI mode."""
    connection = sqlite3.connect(f"{legacy_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT id, level, source_id, target_id, content, context,
                   created_at, accessed_at, access_count
            FROM cells
            ORDER BY level, id
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        _LegacyCell(
            id=row["id"],
            level=row["level"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            content=row["content"],
            context=row["context"],
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"],
        )
        for row in rows
    ]


def _is_valid_row(row: _LegacyCell) -> bool:
    basic_fields_valid = (
        isinstance(row.id, str)
        and bool(row.id)
        and isinstance(row.level, int)
        and not isinstance(row.level, bool)
        and row.level >= 0
        and isinstance(row.content, str)
    )
    if not basic_fields_valid:
        return False
    try:
        _canonical_json(_legacy_payload(row))
    except (TypeError, ValueError):
        return False
    return True


def _has_pair_of_references(row: _LegacyCell) -> bool:
    return (
        isinstance(row.source_id, str)
        and bool(row.source_id)
        and isinstance(row.target_id, str)
        and bool(row.target_id)
    )


def _legacy_payload(row: _LegacyCell) -> Mapping[str, object]:
    """Keep legacy metadata as opaque data instead of interpreting or repairing it."""
    return {
        "legacy": {
            "level": row.level,
            "source_id": row.source_id,
            "target_id": row.target_id,
            "context": row.context,
            "created_at": row.created_at,
            "accessed_at": row.accessed_at,
            "access_count": row.access_count,
        }
    }


def _plan_cells(cells: Sequence[_LegacyCell]) -> _ReplayPlan:
    """Prepare dependency-ordered v2 drafts without mutating either database."""
    valid_rows = [row for row in cells if _is_valid_row(row)]
    loss = len(cells) - len(valid_rows)
    drafts: list[CellDraft] = []
    known_ids: set[str] = set()
    legacy_ids = {row.id for row in valid_rows}

    level_one = [row for row in valid_rows if row.level == 1]
    usable_one = [row for row in level_one if _has_pair_of_references(row)]
    loss += len(level_one) - len(usable_one)

    proxy_ids = {
        legacy_proxy_id(memory_id)
        for row in usable_one
        for memory_id in (row.source_id, row.target_id)
        if memory_id is not None
    }
    # A collision would overwrite an isolated legacy identity, so reject the
    # affected dependent rows rather than creating a replacement identity.
    colliding_proxies = proxy_ids & legacy_ids
    if colliding_proxies:
        usable_before_collision = len(usable_one)
        usable_one = [
            row
            for row in usable_one
            if legacy_proxy_id(row.source_id or "") not in colliding_proxies
            and legacy_proxy_id(row.target_id or "") not in colliding_proxies
        ]
        loss += usable_before_collision - len(usable_one)
        proxy_ids = {
            legacy_proxy_id(memory_id)
            for row in usable_one
            for memory_id in (row.source_id, row.target_id)
            if memory_id is not None
    }

    for proxy_id in sorted(proxy_ids):
        drafts.append(
            CellDraft(proxy_id, 0, "legacy memory proxy", payload={"legacy_proxy": True})
        )
        known_ids.add(proxy_id)

    # Legacy zero-cells have no v1 boundary semantics.  Preserve their ID and
    # metadata as a v2 zero-cell, while malformed rows remain explicit loss.
    for row in (row for row in valid_rows if row.level == 0):
        if row.id in known_ids:
            loss += 1
            continue
        drafts.append(CellDraft(row.id, 0, row.content, payload=_legacy_payload(row)))
        known_ids.add(row.id)

    imported_one = 0
    imported_one_ids: set[str] = set()
    for row in usable_one:
        source_id = legacy_proxy_id(row.source_id or "")
        target_id = legacy_proxy_id(row.target_id or "")
        if row.id in known_ids:
            loss += 1
            continue
        drafts.append(
            CellDraft(
                row.id,
                1,
                row.content,
                (Boundary("source", 0, source_id), Boundary("target", 0, target_id)),
                payload=_legacy_payload(row),
            )
        )
        known_ids.add(row.id)
        imported_one_ids.add(row.id)
        imported_one += 1

    imported_two = 0
    for row in (row for row in valid_rows if row.level == 2):
        if (
            not _has_pair_of_references(row)
            or row.source_id not in imported_one_ids
            or row.target_id not in imported_one_ids
        ):
            loss += 1
            continue
        if row.id in known_ids:
            loss += 1
            continue
        drafts.append(
            CellDraft(
                row.id,
                2,
                row.content,
                (Boundary("source", 0, row.source_id), Boundary("target", 0, row.target_id)),
                payload=_legacy_payload(row),
            )
        )
        known_ids.add(row.id)
        imported_two += 1

    opaque = 0
    for row in (row for row in valid_rows if row.level > 2):
        if row.id in known_ids:
            loss += 1
            continue
        drafts.append(
            CellDraft(row.id, row.level, row.content, payload=_legacy_payload(row))
        )
        known_ids.add(row.id)
        opaque += 1

    return _ReplayPlan(
        drafts=tuple(drafts),
        proxy_zero_cells=len(proxy_ids),
        imported_one_cells=imported_one,
        imported_two_cells=imported_two,
        opaque_cells=opaque,
        unexplained_loss=loss,
    )


def _ordered_boundaries(draft: CellDraft) -> list[dict[str, object]]:
    return [
        {"side": boundary.side, "position": boundary.position, "cell_id": boundary.cell_id}
        for boundary in sorted(
            draft.boundaries,
            key=lambda boundary: (0 if boundary.side == "source" else 1, boundary.position),
        )
    ]


def _replay_manifest(
    plan: _ReplayPlan,
    *,
    legacy_total: int,
    raw_source_fingerprint: str,
    snapshot_id: str,
    root_epoch_id: str,
    snapshot_hash: str,
) -> dict[str, object]:
    """Describe every persisted replay artifact that must match on re-run."""
    return {
        "raw_source_fingerprint": raw_source_fingerprint,
        "cells": [
            {
                "id": draft.id,
                "dimension": draft.dimension,
                "content": draft.content,
                "payload": draft.payload,
                "boundaries": _ordered_boundaries(draft),
            }
            for draft in sorted(plan.drafts, key=lambda draft: draft.id)
        ],
        "event": {"kind": "legacy_import_summary"},
        "epoch": {"id": root_epoch_id, "rewrite_id": None, "parents": []},
        "snapshot": {
            "id": snapshot_id,
            "epoch_id": root_epoch_id,
            "active_cell_ids": sorted(draft.id for draft in plan.drafts),
            "content_hash": snapshot_hash,
        },
        "report": {
            "legacy_total": legacy_total,
            "proxy_zero_cells": plan.proxy_zero_cells,
            "imported_one_cells": plan.imported_one_cells,
            "imported_two_cells": plan.imported_two_cells,
            "opaque_cells": plan.opaque_cells,
            "unexplained_loss": plan.unexplained_loss,
        },
    }


def _manifest_fingerprint(manifest: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(manifest).encode()).hexdigest()


def _canonical_ddl(sql: str) -> str:
    """Normalize only unquoted SQL syntax while preserving literal semantics."""
    result: list[str] = []
    quote: str | None = None
    pending_space = False
    index = 0
    while index < len(sql):
        character = sql[index]
        if quote is None:
            if character.isspace():
                pending_space = bool(result)
            else:
                if pending_space:
                    result.append(" ")
                    pending_space = False
                result.append(character if character in "'\"`[" else character.lower())
                if character == "'":
                    quote = "'"
                elif character == '"':
                    quote = '"'
                elif character == "`":
                    quote = "`"
                elif character == "[":
                    quote = "]"
            index += 1
            continue

        result.append(character)
        if character == quote:
            escaped_quote = quote in ("'", '"') and index + 1 < len(sql) and sql[index + 1] == quote
            escaped_bracket = quote == "]" and index + 1 < len(sql) and sql[index + 1] == "]"
            if escaped_quote or escaped_bracket:
                result.append(sql[index + 1])
                index += 1
            else:
                quote = None
        index += 1
    return "".join(result).strip()


def _schema_definitions(connection: sqlite3.Connection) -> tuple[tuple[str, str, str], ...]:
    """Return all non-vector schema objects whose definitions affect replay safety."""
    definitions = []
    for row in connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"
    ):
        object_type, name, sql = row
        if (
            (object_type == "table" and name in _V2_TABLES)
            or object_type == "index"
            or object_type == "trigger"
        ):
            definitions.append((object_type, name, _canonical_ddl(sql)))
    return tuple(sorted(definitions))


@lru_cache(maxsize=1)
def _supported_schema_definitions() -> tuple[tuple[str, str, str], ...]:
    """Build the exact supported core schema from the v2 store itself."""
    connection = sqlite3.connect(":memory:")
    try:
        EvolvingCategoryStore(connection)
        return _schema_definitions(connection)
    finally:
        connection.close()


def _validate_schema_definitions(connection: sqlite3.Connection) -> None:
    if _schema_definitions(connection) != _supported_schema_definitions():
        raise ValueError("output is incompatible with legacy replay")


def _validate_completed_replay(
    connection: sqlite3.Connection,
    plan: _ReplayPlan,
    *,
    event_id: str,
    event_payload_json: str,
    root_epoch_id: str,
    snapshot_id: str,
    active_cell_ids_json: str,
    snapshot_hash: str,
) -> bool:
    """Return true only when an existing output is the exact expected replay."""
    snapshot = connection.execute(
        """
        SELECT epoch_id, active_cell_ids_json, content_hash
        FROM cat_snapshots WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    expected_counts = {
        "cat_schema_version": 1,
        "cat_events": 1,
        "cat_contexts": 0,
        "cat_cells": len(plan.drafts),
        "cat_boundaries": sum(len(draft.boundaries) for draft in plan.drafts),
        "cat_weight_observations": 0,
        "cat_rewrites": 0,
        "cat_rewrite_members": 0,
        "cat_epochs": 1,
        "cat_epoch_parents": 0,
        "cat_snapshots": 1,
    }
    actual_counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _REPLAY_STATE_TABLES
    }
    schema_versions = [
        row[0]
        for row in connection.execute(
            "SELECT version FROM cat_schema_version ORDER BY version"
        )
    ]
    trigger_names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    if (
        schema_versions != [1]
        or trigger_names != _EXPECTED_IMMUTABILITY_TRIGGERS
    ):
        raise ValueError("output is incompatible with legacy replay")
    if snapshot is None:
        if any(
            count
            for table, count in actual_counts.items()
            if table != "cat_schema_version"
        ):
            raise ValueError("output contains conflicting legacy replay state")
        return False
    if (
        snapshot["epoch_id"] != root_epoch_id
        or snapshot["active_cell_ids_json"] != active_cell_ids_json
        or snapshot["content_hash"] != snapshot_hash
        or actual_counts != expected_counts
    ):
        raise ValueError("existing legacy replay snapshot does not match source")

    event = connection.execute(
        "SELECT kind, payload_json FROM cat_events WHERE id = ?", (event_id,)
    ).fetchone()
    epoch = connection.execute(
        "SELECT rewrite_id, created_event_id FROM cat_epochs WHERE id = ?", (root_epoch_id,)
    ).fetchone()
    if (
        event is None
        or event["kind"] != "legacy_import_summary"
        or event["payload_json"] != event_payload_json
        or epoch is None
        or epoch["rewrite_id"] is not None
        or epoch["created_event_id"] != event_id
        or connection.execute(
            "SELECT COUNT(*) FROM cat_epoch_parents WHERE epoch_id = ?", (root_epoch_id,)
        ).fetchone()[0]
        != 0
        or connection.execute(
            "SELECT COUNT(*) FROM cat_events WHERE kind = 'legacy_import_summary'"
        ).fetchone()[0]
        != 1
    ):
        raise ValueError("existing legacy replay state does not match source")

    for draft in plan.drafts:
        cell = connection.execute(
            """
            SELECT dimension, content, context_id, payload_json, content_hash, created_event_id
            FROM cat_cells WHERE id = ?
            """,
            (draft.id,),
        ).fetchone()
        if (
            cell is None
            or cell["dimension"] != draft.dimension
            or cell["content"] != draft.content
            or cell["context_id"] != draft.context_id
            or cell["payload_json"] != _canonical_json(draft.payload)
            or cell["content_hash"] != _content_hash(draft.content)
            or cell["created_event_id"] != event_id
        ):
            raise ValueError("existing legacy replay cells do not match source")
        boundaries = connection.execute(
            """
            SELECT side, position, boundary_id FROM cat_boundaries WHERE cell_id = ?
            ORDER BY CASE side WHEN 'source' THEN 0 ELSE 1 END, position
            """,
            (draft.id,),
        ).fetchall()
        expected_boundaries = [
            (boundary["side"], boundary["position"], boundary["cell_id"])
            for boundary in _ordered_boundaries(draft)
        ]
        if [tuple(boundary) for boundary in boundaries] != expected_boundaries:
            raise ValueError("existing legacy replay boundaries do not match source")
    return True


def _preflight_existing_output(
    output: Path,
    plan: _ReplayPlan,
    *,
    event_id: str,
    event_payload_json: str,
    root_epoch_id: str,
    snapshot_id: str,
    active_cell_ids_json: str,
    snapshot_hash: str,
) -> bool:
    """Inspect an existing output read-only before v2 schema initialization."""
    if not output.exists():
        return False
    connection = sqlite3.connect(f"{output.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not tables:
            return False
        if not _V2_TABLES <= tables:
            raise ValueError("output is incompatible with legacy replay")
        try:
            _validate_schema_definitions(connection)
            if "cat_vectors" in tables:
                permitted_tables = _V2_TABLES | {"cat_vectors"} | _VEC_SHADOW_TABLES
                if not _VEC_SHADOW_TABLES <= tables or not tables <= permitted_tables:
                    raise ValueError("output is incompatible with legacy replay")
                vector_sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cat_vectors'"
                ).fetchone()["sql"]
                normalized_vector_sql = _canonical_ddl(vector_sql or "")
                if (
                    normalized_vector_sql != _SUPPORTED_VEC0_DDL
                    or connection.execute(
                        "SELECT COUNT(*) FROM cat_vectors_chunks"
                    ).fetchone()[0]
                    != 0
                    or connection.execute(
                        "SELECT COUNT(*) FROM cat_vectors_rowids"
                    ).fetchone()[0]
                    != 0
                    or connection.execute(
                        "SELECT COUNT(*) FROM cat_vectors_vector_chunks00"
                    ).fetchone()[0]
                    != 0
                    or connection.execute(
                        "SELECT COUNT(*) FROM cat_vectors_info"
                    ).fetchone()[0]
                    != 4
                ):
                    raise ValueError("output is incompatible with legacy replay")
            elif not tables <= _V2_TABLES:
                raise ValueError("output is incompatible with legacy replay")
            return _validate_completed_replay(
                connection,
                plan,
                event_id=event_id,
                event_payload_json=event_payload_json,
                root_epoch_id=root_epoch_id,
                snapshot_id=snapshot_id,
                active_cell_ids_json=active_cell_ids_json,
                snapshot_hash=snapshot_hash,
            )
        except sqlite3.Error as exc:
            raise ValueError("output is incompatible with legacy replay") from exc
    finally:
        connection.close()


def _report(
    plan: _ReplayPlan,
    legacy_total: int,
    root_epoch_id: str,
    snapshot_hash: str,
) -> LegacyImportReport:
    return LegacyImportReport(
        legacy_total=legacy_total,
        proxy_zero_cells=plan.proxy_zero_cells,
        imported_one_cells=plan.imported_one_cells,
        imported_two_cells=plan.imported_two_cells,
        opaque_cells=plan.opaque_cells,
        unexplained_loss=plan.unexplained_loss,
        root_epoch_id=root_epoch_id,
        snapshot_hash=snapshot_hash,
    )


def _remove_staged_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _fsync_file(path: Path) -> None:
    with path.open("rb") as database:
        os.fsync(database.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _publish_staged_output(staged_output: Path, output: Path) -> None:
    _fsync_file(staged_output)
    os.replace(staged_output, output)
    _fsync_directory(output.parent)


def _bootstrap_staged_output(
    staged_output: Path,
    plan: _ReplayPlan,
    *,
    event_id: str,
    event_payload: Mapping[str, object],
    root_epoch_id: str,
    snapshot_id: str,
    active_cell_ids_json: str,
    snapshot_hash: str,
) -> None:
    connection = sqlite3.connect(staged_output)
    store: EvolvingCategoryStore | None = None
    try:
        store = EvolvingCategoryStore(connection)
        with store.transaction() as transaction:
            store.append_event(
                "legacy_import_summary", event_payload, event_id=event_id
            )
            for draft in plan.drafts:
                store.create_cell(draft, created_event_id=event_id)
            transaction.execute(
                """
                INSERT INTO cat_epochs (id, created_event_id, created_at)
                VALUES (?, ?, datetime('now'))
                """,
                (root_epoch_id, event_id),
            )
            transaction.execute(
                """
                INSERT INTO cat_snapshots (id, epoch_id, active_cell_ids_json, content_hash, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (
                    snapshot_id,
                    root_epoch_id,
                    active_cell_ids_json,
                    snapshot_hash,
                ),
            )
    finally:
        if store is None:
            connection.close()
        else:
            store.close()


def import_legacy_category(
    legacy_path: str | Path, output_path: str | Path
) -> LegacyImportReport:
    """Copy one legacy category history into an isolated v2 database.

    The source is always opened read-only.  Missing or malformed references
    are reported as loss; this routine never creates category cells for them.
    """
    legacy = Path(legacy_path).resolve()
    output = Path(output_path).resolve()
    if legacy == output or (output.exists() and os.path.samefile(legacy, output)):
        raise ValueError("legacy input and v2 output must resolve to different paths")

    rows = _read_legacy_rows(legacy)
    raw_source_fingerprint = _raw_source_fingerprint(rows)
    plan = _plan_cells(rows)
    active_cell_ids_json = json.dumps(
        sorted(draft.id for draft in plan.drafts), separators=(",", ":")
    )
    snapshot_hash = canonical_snapshot_hash(draft.id for draft in plan.drafts)
    root_epoch_id = _stable_id("legacy-root-epoch", snapshot_hash)
    snapshot_id = _stable_id("legacy-snapshot", snapshot_hash)
    manifest = _replay_manifest(
        plan,
        legacy_total=len(rows),
        raw_source_fingerprint=raw_source_fingerprint,
        snapshot_id=snapshot_id,
        root_epoch_id=root_epoch_id,
        snapshot_hash=snapshot_hash,
    )
    manifest_fingerprint = _manifest_fingerprint(manifest)
    event_id = _stable_id("legacy-import-summary", manifest_fingerprint)
    event_payload = {
        "manifest_fingerprint": manifest_fingerprint,
        "raw_source_fingerprint": raw_source_fingerprint,
    }
    event_payload_json = _canonical_json(event_payload)
    if output.exists() and output.stat().st_size == 0:
        preflight_matches = False
    else:
        preflight_matches = _preflight_existing_output(
            output,
            plan,
            event_id=event_id,
            event_payload_json=event_payload_json,
            root_epoch_id=root_epoch_id,
            snapshot_id=snapshot_id,
            active_cell_ids_json=active_cell_ids_json,
            snapshot_hash=snapshot_hash,
        )
    if preflight_matches:
        return _report(plan, len(rows), root_epoch_id, snapshot_hash)

    descriptor, staged_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".replay.tmp",
    )
    os.close(descriptor)
    staged_output = Path(staged_name)
    try:
        _bootstrap_staged_output(
            staged_output,
            plan,
            event_id=event_id,
            event_payload=event_payload,
            root_epoch_id=root_epoch_id,
            snapshot_id=snapshot_id,
            active_cell_ids_json=active_cell_ids_json,
            snapshot_hash=snapshot_hash,
        )
        if not _preflight_existing_output(
            staged_output,
            plan,
            event_id=event_id,
            event_payload_json=event_payload_json,
            root_epoch_id=root_epoch_id,
            snapshot_id=snapshot_id,
            active_cell_ids_json=active_cell_ids_json,
            snapshot_hash=snapshot_hash,
        ):
            raise RuntimeError("staged legacy replay did not validate")
        _publish_staged_output(staged_output, output)
        return _report(plan, len(rows), root_epoch_id, snapshot_hash)
    finally:
        _remove_staged_sqlite_files(staged_output)


def _build_parser() -> argparse.ArgumentParser:
    class _ReplayArgumentParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            raise ValueError(message)

    parser = _ReplayArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    replay = subcommands.add_parser("replay", help="replay a legacy category database")
    replay.add_argument("--legacy", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    replay.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command != "replay":
            raise ValueError("a command is required")
        report = import_legacy_category(args.legacy, args.output)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(asdict(report), sort_keys=True))
    else:
        print(report)
    return 2 if report.unexplained_loss else 0


if __name__ == "__main__":
    raise SystemExit(main())
