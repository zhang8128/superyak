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
from typing import Iterable, Literal, Mapping, Sequence
import uuid

from categories import Boundary, CellDraft, EvolvingCategoryStore, _now_iso


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
class RewriteEvidence:
    evidence_event_ids: tuple[str, ...]
    cohesion_gain: float
    persistence_score: float
    complexity_cost: float
    explicit_correction: bool = False


@dataclass(frozen=True)
class RewriteProposal:
    id: str
    kind: Literal["create", "retire", "retype", "split", "merge"]
    locus_id: str
    context_id: str | None
    input_ids: tuple[str, ...]
    outputs: tuple[CellDraft, ...]
    witness_ids: tuple[str, ...]
    evidence: RewriteEvidence


@dataclass(frozen=True)
class EvolutionPolicy:
    min_persistence_score: float = 0.10
    rewrite_budget: int = 32
    max_members: int = 32
    max_active_branches: int = 4


def is_eligible(evidence: RewriteEvidence, policy: EvolutionPolicy) -> bool:
    """Apply the non-bypassable rewrite eligibility rule."""
    if evidence.explicit_correction:
        return True
    return (
        evidence.cohesion_gain > evidence.complexity_cost
        and evidence.persistence_score >= policy.min_persistence_score
    )


_REWRITE_KINDS = frozenset({"create", "retire", "retype", "split", "merge"})
_DISPOSITION_KINDS = {
    "rewrite_proposed": "proposed",
    "rewrite_committed": "committed",
    "rewrite_rejected": "rejected",
    "rewrite_superseded": "superseded",
}
EVOLUTION_NAMESPACE = uuid.UUID("30406ca9-f69f-5d0c-a3c1-c955de79d194")


class EvolutionEngine:
    """Validate and publish structural rewrites through immutable history."""

    def __init__(
        self,
        store: EvolvingCategoryStore,
        policy: EvolutionPolicy | None = None,
    ):
        self.store = store
        self.policy = policy or EvolutionPolicy()
        if (
            self.policy.rewrite_budget < 0
            or self.policy.max_members < 0
            or self.policy.max_active_branches < 1
        ):
            raise ValueError("evolution policy limits must be non-negative")

    @property
    def connection(self) -> sqlite3.Connection:
        return self.store.connection

    def propose(self, proposal: RewriteProposal) -> str:
        """Archive a proposal and its inactive outputs in one transaction."""
        self._validate_proposal(proposal)
        payload = {
            "rewrite_id": proposal.id,
            "kind": proposal.kind,
            "locus_id": proposal.locus_id,
            "context_id": proposal.context_id,
            "evidence": asdict(proposal.evidence),
        }
        with self.store.transaction() as connection:
            event_id = self.store.append_event("rewrite_proposed", payload)
            connection.execute(
                """
                INSERT INTO cat_rewrites
                    (id, context_id, created_event_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    proposal.id,
                    proposal.context_id,
                    event_id,
                    _canonical_json(payload),
                    _now_iso(),
                ),
            )
            for draft in sorted(proposal.outputs, key=lambda item: (item.dimension, item.id)):
                self.store.create_cell(draft, created_event_id=event_id)
            self._insert_members(connection, proposal)
        return proposal.id

    propose_rewrite = propose

    def _validate_proposal(self, proposal: RewriteProposal) -> None:
        if not proposal.id or proposal.kind not in _REWRITE_KINDS:
            raise ValueError("rewrite proposal requires an id and supported kind")
        if self.connection.execute(
            "SELECT 1 FROM cat_rewrites WHERE id = ?", (proposal.id,)
        ).fetchone():
            raise ValueError("rewrite proposal id already exists")
        groups = (
            proposal.input_ids,
            tuple(draft.id for draft in proposal.outputs),
            proposal.witness_ids,
            proposal.evidence.evidence_event_ids,
        )
        total_members = sum(len(group) for group in groups)
        if total_members > self.policy.max_members:
            raise ValueError("rewrite member limit exceeded")
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("rewrite member roles cannot contain duplicates")
        if any(not math.isfinite(value) for value in (
            proposal.evidence.cohesion_gain,
            proposal.evidence.persistence_score,
            proposal.evidence.complexity_cost,
        )):
            raise ValueError("rewrite evidence values must be finite")
        shapes = {
            "create": (len(proposal.input_ids) == 0 and len(proposal.outputs) >= 1),
            "retire": (len(proposal.input_ids) >= 1 and len(proposal.outputs) == 0),
            "retype": (len(proposal.input_ids) == 1 and len(proposal.outputs) == 1),
            "split": (len(proposal.input_ids) == 1 and len(proposal.outputs) >= 2),
            "merge": (len(proposal.input_ids) >= 2 and len(proposal.outputs) == 1),
        }
        if not shapes[proposal.kind]:
            raise ValueError(f"invalid {proposal.kind} rewrite lineage")
        for cell_id in (*proposal.input_ids, *proposal.witness_ids):
            if self.store.get_cell(cell_id) is None:
                raise ValueError(f"rewrite member cell does not exist: {cell_id}")
        for event_id in proposal.evidence.evidence_event_ids:
            if self.connection.execute(
                "SELECT 1 FROM cat_events WHERE id = ?", (event_id,)
            ).fetchone() is None:
                raise ValueError(f"rewrite evidence event does not exist: {event_id}")
        output_ids = {draft.id for draft in proposal.outputs}
        if any(self.store.get_cell(cell_id) is not None for cell_id in output_ids):
            raise ValueError("rewrite output cell already exists")

    @staticmethod
    def _insert_members(
        connection: sqlite3.Connection, proposal: RewriteProposal
    ) -> None:
        member_groups = (
            ("input", proposal.input_ids, True),
            ("output", tuple(draft.id for draft in proposal.outputs), True),
            ("witness", proposal.witness_ids, True),
            ("evidence", proposal.evidence.evidence_event_ids, False),
        )
        for role, identifiers, are_cells in member_groups:
            for position, identifier in enumerate(identifiers):
                connection.execute(
                    """
                    INSERT INTO cat_rewrite_members
                        (rewrite_id, role, position, cell_id, external_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.id,
                        role,
                        position,
                        identifier if are_cells else None,
                        None if are_cells else identifier,
                    ),
                )

    def latest_disposition(self, rewrite_id: str) -> str | None:
        """Derive status from the newest immutable disposition event."""
        rows = self.connection.execute(
            """
            SELECT kind, payload_json FROM cat_events
            WHERE kind IN ('rewrite_proposed','rewrite_committed',
                           'rewrite_rejected','rewrite_superseded')
            ORDER BY rowid DESC
            """
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("rewrite_id") == rewrite_id:
                return _DISPOSITION_KINDS[row["kind"]]
        return None

    rewrite_disposition = latest_disposition

    def lineage(self, rewrite_id: str) -> dict[str, tuple[str, ...]]:
        result: dict[str, tuple[str, ...]] = {}
        for role in ("input", "output", "witness", "evidence"):
            rows = self.connection.execute(
                """
                SELECT cell_id, external_id FROM cat_rewrite_members
                WHERE rewrite_id = ? AND role = ? ORDER BY position
                """,
                (rewrite_id, role),
            ).fetchall()
            result[role] = tuple(row["cell_id"] or row["external_id"] for row in rows)
        return result

    def commit(
        self,
        rewrite_id: str,
        parent_epoch_ids: Sequence[str],
        *,
        epoch_id: str | None = None,
    ) -> str | None:
        """Commit an eligible proposal, or append a rejection without publishing it."""
        parents = tuple(parent_epoch_ids)
        identifier = epoch_id or self._epoch_id(rewrite_id, parents)
        try:
            with self.store.transaction(immediate=True) as connection:
                rewrite = connection.execute(
                    "SELECT payload_json FROM cat_rewrites WHERE id = ?", (rewrite_id,)
                ).fetchone()
                if rewrite is None:
                    raise ValueError("rewrite proposal does not exist")
                disposition = self.latest_disposition(rewrite_id)
                if disposition == "committed":
                    committed = connection.execute(
                        "SELECT id FROM cat_epochs WHERE rewrite_id = ?",
                        (rewrite_id,),
                    ).fetchone()
                    return str(committed["id"]) if committed else None
                if disposition != "proposed":
                    return None

                try:
                    payload = json.loads(rewrite["payload_json"])
                    evidence = RewriteEvidence(**payload["evidence"])
                    self._validate_commit(
                        rewrite_id, payload["kind"], evidence, parents, identifier
                    )
                    parent_active: set[str] = set()
                    for parent_id in parents:
                        parent_active.update(self.active_cell_ids(parent_id))
                    lineage = self.lineage(rewrite_id)
                    if not set(lineage["input"]) <= parent_active:
                        raise ValueError(
                            "rewrite inputs are not active in the parent epochs"
                        )
                    active_set = parent_active.difference(lineage["input"])
                    active_set.update(lineage["output"])
                    active = tuple(sorted(active_set))
                except (KeyError, TypeError, ValueError) as exc:
                    self.store.append_event(
                        "rewrite_rejected",
                        {"rewrite_id": rewrite_id, "reason": str(exc)},
                    )
                    return None

                content_hash = canonical_snapshot_hash(active)
                event_id = self.store.append_event(
                    "rewrite_committed",
                    {
                        "rewrite_id": rewrite_id,
                        "epoch_id": identifier,
                        "parent_epoch_ids": parents,
                        "active_cell_ids": active,
                        "snapshot_hash": content_hash,
                    },
                )
                connection.execute(
                    """
                    INSERT INTO cat_epochs (id, rewrite_id, created_event_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (identifier, rewrite_id, event_id, _now_iso()),
                )
                for position, parent_id in enumerate(parents):
                    connection.execute(
                        """
                        INSERT INTO cat_epoch_parents (epoch_id, position, parent_id)
                        VALUES (?, ?, ?)
                        """,
                        (identifier, position, parent_id),
                    )
                self._write_snapshot(connection, identifier, active)
                return identifier
        except sqlite3.IntegrityError:
            # The unique rewrite index is the final race backstop.  The failed
            # transaction (including its event) is already rolled back here.
            committed = self.connection.execute(
                "SELECT id FROM cat_epochs WHERE rewrite_id = ?", (rewrite_id,)
            ).fetchone()
            if committed is not None:
                return str(committed["id"])
            raise

    commit_rewrite = commit

    def _validate_commit(
        self,
        rewrite_id: str,
        kind: str,
        evidence: RewriteEvidence,
        parents: tuple[str, ...],
        epoch_id: str,
    ) -> None:
        if not is_eligible(evidence, self.policy):
            raise ValueError("rewrite evidence is not eligible")
        if not parents or len(set(parents)) != len(parents):
            raise ValueError("rewrite commit requires distinct epoch parents")
        if self.connection.execute(
            "SELECT 1 FROM cat_epochs WHERE id = ?", (epoch_id,)
        ).fetchone():
            raise ValueError("epoch id already exists and would violate parent acyclicity")
        for parent_id in parents:
            if self.connection.execute(
                "SELECT 1 FROM cat_epochs WHERE id = ?", (parent_id,)
            ).fetchone() is None:
                raise ValueError("epoch parent does not exist")
        self._assert_epoch_graph_acyclic()
        lineage = self.lineage(rewrite_id)
        member_count = sum(len(members) for members in lineage.values())
        if member_count > self.policy.max_members:
            raise ValueError("rewrite member limit exceeded")
        expected_shapes = {
            "create": (not lineage["input"] and bool(lineage["output"])),
            "retire": (bool(lineage["input"]) and not lineage["output"]),
            "retype": (len(lineage["input"]) == 1 and len(lineage["output"]) == 1),
            "split": (len(lineage["input"]) == 1 and len(lineage["output"]) >= 2),
            "merge": (len(lineage["input"]) >= 2 and len(lineage["output"]) == 1),
        }
        if kind not in expected_shapes or not expected_shapes[kind]:
            raise ValueError("rewrite lineage is invalid")
        for cell_id in (*lineage["input"], *lineage["output"], *lineage["witness"]):
            if self.store.get_cell(cell_id) is None:
                raise ValueError("rewrite lineage references a missing cell")
        leaf_rows = self.connection.execute(
            """
            SELECT id FROM cat_epochs AS epoch
            WHERE NOT EXISTS (
                SELECT 1 FROM cat_epoch_parents AS edge WHERE edge.parent_id = epoch.id
            )
            """
        ).fetchall()
        leaves = {str(row["id"]) for row in leaf_rows}
        future_branch_count = len(leaves.difference(parents)) + 1
        if future_branch_count > self.policy.max_active_branches:
            raise ValueError("active branch limit exceeded")

    def _assert_epoch_graph_acyclic(self) -> None:
        adjacency: dict[str, list[str]] = {}
        for row in self.connection.execute(
            "SELECT epoch_id, parent_id FROM cat_epoch_parents"
        ):
            adjacency.setdefault(str(row["epoch_id"]), []).append(str(row["parent_id"]))
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(epoch_id: str) -> None:
            if epoch_id in visiting:
                raise ValueError("epoch parents must stay acyclic")
            if epoch_id in visited:
                return
            visiting.add(epoch_id)
            for parent_id in adjacency.get(epoch_id, ()):
                visit(parent_id)
            visiting.remove(epoch_id)
            visited.add(epoch_id)

        for epoch_id in tuple(adjacency):
            visit(epoch_id)

    def epoch_parents(self, epoch_id: str) -> tuple[str, ...]:
        return tuple(
            str(row["parent_id"])
            for row in self.connection.execute(
                "SELECT parent_id FROM cat_epoch_parents WHERE epoch_id=? ORDER BY position",
                (epoch_id,),
            )
        )

    def create_root_epoch(
        self,
        epoch_id: str,
        active_cell_ids: Iterable[str],
        *,
        event_id: str | None = None,
    ) -> str:
        """Create a parentless epoch for an imported or newly seeded active set."""
        active = tuple(sorted(set(active_cell_ids)))
        with self.store.transaction(immediate=True) as connection:
            if connection.execute(
                "SELECT 1 FROM cat_epochs WHERE id = ?", (epoch_id,)
            ).fetchone():
                raise ValueError("epoch parent identity already exists")
            leaf_count = connection.execute(
                """
                SELECT COUNT(*) FROM cat_epochs AS epoch
                WHERE NOT EXISTS (
                    SELECT 1 FROM cat_epoch_parents AS edge
                    WHERE edge.parent_id = epoch.id
                )
                """
            ).fetchone()[0]
            if leaf_count + 1 > self.policy.max_active_branches:
                raise ValueError("active branch limit exceeded")
            for cell_id in active:
                if self.store.get_cell(cell_id) is None:
                    raise ValueError("root epoch active cell does not exist")
                if connection.execute(
                    """
                    SELECT 1 FROM cat_rewrite_members
                    WHERE role = 'output' AND cell_id = ? LIMIT 1
                    """,
                    (cell_id,),
                ).fetchone():
                    raise ValueError("root epoch cannot activate a rewrite output")
            if event_id is not None and connection.execute(
                "SELECT 1 FROM cat_events WHERE id = ?", (event_id,)
            ).fetchone() is None:
                raise ValueError("root epoch event does not exist")
            created_event_id = self.store.append_event(
                "epoch_created",
                {
                    "epoch_id": epoch_id,
                    "active_cell_ids": active,
                    "source_event_id": event_id,
                },
            )
            connection.execute(
                "INSERT INTO cat_epochs (id, created_event_id, created_at) VALUES (?, ?, ?)",
                (epoch_id, created_event_id, _now_iso()),
            )
            self._write_snapshot(connection, epoch_id, active)
        return epoch_id

    def active_cell_ids(self, epoch_id: str) -> tuple[str, ...]:
        """Return canonical state, rebuilding a corrupt derived snapshot from history."""
        rebuilt = self._rebuild_active(epoch_id, set())
        canonical_json = json.dumps(rebuilt, separators=(",", ":"))
        content_hash = canonical_snapshot_hash(rebuilt)
        snapshot = self.connection.execute(
            """
            SELECT id, active_cell_ids_json, content_hash FROM cat_snapshots
            WHERE epoch_id = ? ORDER BY rowid DESC LIMIT 1
            """,
            (epoch_id,),
        ).fetchone()
        valid = (
            snapshot is not None
            and snapshot["active_cell_ids_json"] == canonical_json
            and snapshot["content_hash"] == content_hash
        )
        if not valid:
            with self.store.transaction() as connection:
                connection.execute("DELETE FROM cat_snapshots WHERE epoch_id = ?", (epoch_id,))
                self._write_snapshot(connection, epoch_id, rebuilt)
        return rebuilt

    select_epoch = active_cell_ids

    def _rebuild_active(self, epoch_id: str, visiting: set[str]) -> tuple[str, ...]:
        if epoch_id in visiting:
            raise ValueError("epoch parents must stay acyclic")
        epoch = self.connection.execute(
            "SELECT rewrite_id, created_event_id FROM cat_epochs WHERE id = ?", (epoch_id,)
        ).fetchone()
        if epoch is None:
            raise ValueError("epoch does not exist")
        visiting.add(epoch_id)
        try:
            if epoch["rewrite_id"] is None:
                active = self._root_active_ids(epoch_id, epoch["created_event_id"])
            else:
                active_set: set[str] = set()
                for parent_id in self.epoch_parents(epoch_id):
                    active_set.update(self._rebuild_active(parent_id, visiting))
                lineage = self.lineage(str(epoch["rewrite_id"]))
                active_set.difference_update(lineage["input"])
                active_set.update(lineage["output"])
                active = tuple(sorted(active_set))
        finally:
            visiting.remove(epoch_id)
        return active

    def _root_active_ids(self, epoch_id: str, event_id: str | None) -> tuple[str, ...]:
        if event_id is None:
            return ()
        event = self.connection.execute(
            "SELECT payload_json FROM cat_events WHERE id = ?", (event_id,)
        ).fetchone()
        if event is not None:
            try:
                payload = json.loads(event["payload_json"])
                explicit = payload.get("active_cell_ids")
                if isinstance(explicit, list) and all(isinstance(item, str) for item in explicit):
                    return tuple(sorted(set(explicit)))
            except (TypeError, json.JSONDecodeError):
                pass
        return tuple(
            str(row["id"])
            for row in self.connection.execute(
                "SELECT id FROM cat_cells WHERE created_event_id = ? ORDER BY id", (event_id,)
            )
        )

    def _write_snapshot(
        self,
        connection: sqlite3.Connection,
        epoch_id: str,
        active_cell_ids: Iterable[str],
    ) -> None:
        active = tuple(sorted(set(active_cell_ids)))
        snapshot_id = str(uuid.uuid5(EVOLUTION_NAMESPACE, f"snapshot:{epoch_id}"))
        connection.execute(
            """
            INSERT INTO cat_snapshots
                (id, epoch_id, active_cell_ids_json, content_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                epoch_id,
                json.dumps(active, separators=(",", ":")),
                canonical_snapshot_hash(active),
                _now_iso(),
            ),
        )

    @staticmethod
    def _epoch_id(rewrite_id: str, parents: tuple[str, ...]) -> str:
        material = _canonical_json({"rewrite_id": rewrite_id, "parents": parents})
        return str(uuid.uuid5(EVOLUTION_NAMESPACE, f"epoch:{material}"))

    def consolidate(
        self, rewrite_ids: Iterable[str], parent_epoch_id: str
    ) -> tuple[tuple[str, str], ...]:
        """Commit eligible proposals in deterministic policy order and budget."""
        candidates: list[tuple[bool, float, str, str]] = []
        seen: set[str] = set()
        for rewrite_id in rewrite_ids:
            if rewrite_id in seen or self.latest_disposition(rewrite_id) != "proposed":
                continue
            seen.add(rewrite_id)
            row = self.connection.execute(
                "SELECT payload_json, created_at FROM cat_rewrites WHERE id = ?",
                (rewrite_id,),
            ).fetchone()
            if row is None:
                continue
            payload = json.loads(row["payload_json"])
            evidence = RewriteEvidence(**payload["evidence"])
            candidates.append(
                (
                    evidence.explicit_correction,
                    evidence.cohesion_gain - evidence.complexity_cost,
                    str(row["created_at"]),
                    rewrite_id,
                )
            )
        candidates.sort(key=lambda item: (-int(item[0]), -item[1], item[2], item[3]))

        committed: list[tuple[str, str]] = []
        current_parent = parent_epoch_id
        selected = candidates[: self.policy.rewrite_budget]
        for _explicit, _gain, _created, rewrite_id in selected:
            epoch_id = self.commit(rewrite_id, (current_parent,))
            if epoch_id is not None:
                committed.append((rewrite_id, epoch_id))
                current_parent = epoch_id
        for _explicit, _gain, _created, rewrite_id in candidates[self.policy.rewrite_budget :]:
            with self.store.transaction():
                self.store.append_event(
                    "rewrite_superseded",
                    {"rewrite_id": rewrite_id, "reason": "consolidation budget"},
                )
        return tuple(committed)


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
