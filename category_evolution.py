"""Deterministic, read-only replay from the legacy category SQLite store."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping, Sequence
import uuid

from categories import Boundary, CellDraft, EvolvingCategoryStore


LEGACY_NAMESPACE = uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223")


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
    return (
        isinstance(row.id, str)
        and bool(row.id)
        and isinstance(row.level, int)
        and not isinstance(row.level, bool)
        and row.level >= 0
        and isinstance(row.content, str)
    )


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
        imported_one += 1

    imported_two = 0
    for row in (row for row in valid_rows if row.level == 2):
        if not _has_pair_of_references(row) or row.source_id not in known_ids or row.target_id not in known_ids:
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
    plan = _plan_cells(rows)
    active_cell_ids_json = json.dumps(
        sorted(draft.id for draft in plan.drafts), separators=(",", ":")
    )
    snapshot_hash = canonical_snapshot_hash(draft.id for draft in plan.drafts)
    root_epoch_id = _stable_id("legacy-root-epoch", snapshot_hash)
    snapshot_id = _stable_id("legacy-snapshot", snapshot_hash)
    output_connection = sqlite3.connect(output)
    store = EvolvingCategoryStore(output_connection)
    try:
        # The contents of this event are deliberately only source-derived.
        # It is the sole event emitted for the bootstrap, regardless of size.
        source_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    (row.id, row.level, row.source_id, row.target_id, row.content)
                    for row in rows
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        event_id = _stable_id("legacy-import-summary", source_fingerprint)
        existing_snapshot = store.connection.execute(
            """
            SELECT epoch_id, active_cell_ids_json, content_hash
            FROM cat_snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if existing_snapshot is not None:
            if (
                existing_snapshot["epoch_id"] != root_epoch_id
                or existing_snapshot["active_cell_ids_json"] != active_cell_ids_json
                or existing_snapshot["content_hash"] != snapshot_hash
            ):
                raise ValueError("existing legacy replay snapshot does not match source")
            return _report(plan, len(rows), root_epoch_id, snapshot_hash)
        if store.connection.execute(
            "SELECT 1 FROM cat_events WHERE id = ?", (event_id,)
        ).fetchone() is not None:
            raise ValueError("incomplete legacy replay already exists in output")
        store.append_event(
            "legacy_import_summary",
            {"source_fingerprint": source_fingerprint},
            event_id=event_id,
        )
        for draft in plan.drafts:
            store.create_cell(draft, created_event_id=event_id)
        with store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO cat_epochs (id, created_event_id, created_at)
                VALUES (?, ?, datetime('now'))
                """,
                (root_epoch_id, event_id),
            )
            connection.execute(
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
        return _report(plan, len(rows), root_epoch_id, snapshot_hash)
    finally:
        store.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    replay = subcommands.add_parser("replay", help="replay a legacy category database")
    replay.add_argument("--legacy", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    replay.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "replay":
        parser.error("a command is required")
    try:
        report = import_legacy_category(args.legacy, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    if args.as_json:
        print(json.dumps(asdict(report), sort_keys=True))
    else:
        print(report)
    return 2 if report.unexplained_loss else 0


if __name__ == "__main__":
    raise SystemExit(main())
