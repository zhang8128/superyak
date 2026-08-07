"""Behavioral tests for deterministic, read-only legacy category replay."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import uuid

import pytest

from categories import Boundary, CellDraft, EvolvingCategoryStore
from category_evolution import (
    EvolutionEngine,
    EvolutionPolicy,
    RewriteEvidence,
    RewriteProposal,
    canonical_snapshot_hash,
    is_eligible,
)

def _legacy_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cells (
            id TEXT PRIMARY KEY,
            level INTEGER NOT NULL,
            source_id TEXT,
            target_id TEXT,
            content TEXT NOT NULL,
            context TEXT,
            created_at TEXT NOT NULL,
            accessed_at TEXT,
            access_count INTEGER
        );
        """
    )
    return connection


def _insert_legacy_cell(
    connection: sqlite3.Connection,
    cell_id: str,
    level: int,
    source_id: str | None,
    target_id: str | None,
    content: str,
    context: str = '{"origin":"legacy"}',
) -> None:
    connection.execute(
        """
        INSERT INTO cells
            (id, level, source_id, target_id, content, context, created_at, access_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cell_id, level, source_id, target_id, content, context, "2026-08-07T00:00:00+00:00", 0),
    )


def _make_legacy_history(path: Path) -> None:
    connection = _legacy_connection(path)
    _insert_legacy_cell(connection, "arrow-alpha", 1, "memory-alpha", "memory-beta", "alpha to beta")
    _insert_legacy_cell(connection, "arrow-beta", 1, "memory-beta", "memory-alpha", "beta to alpha")
    _insert_legacy_cell(connection, "transfer", 2, "arrow-alpha", "arrow-beta", "transfer")
    connection.commit()
    connection.close()


def _importer():
    return importlib.import_module("category_evolution")


def _v2_cell_count(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT COUNT(*) FROM cat_cells").fetchone()[0]
    finally:
        connection.close()


def _v2_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("cat_events", "cat_cells", "cat_epochs", "cat_snapshots")
        }
    finally:
        connection.close()


@pytest.fixture
def evolution_store(tmp_path):
    store = EvolvingCategoryStore(sqlite3.connect(tmp_path / "evolution.db"))
    yield store
    store.close()


def _evidence(*, explicit=False, persistence=0.5, gain=0.8, cost=0.2, events=()):
    return RewriteEvidence(tuple(events), gain, persistence, cost, explicit)


def _proposal(
    proposal_id,
    kind,
    *,
    inputs=(),
    outputs=(),
    witnesses=(),
    evidence=None,
    locus="locus",
):
    return RewriteProposal(
        proposal_id,
        kind,
        locus,
        None,
        tuple(inputs),
        tuple(outputs),
        tuple(witnesses),
        evidence or _evidence(),
    )


def _root(engine, store, *cell_ids):
    event_id = store.append_event("seed", {}, event_id="seed-event")
    for cell_id in cell_ids:
        store.create_cell(CellDraft(cell_id, 0, cell_id), created_event_id=event_id)
    return engine.create_root_epoch("root", cell_ids, event_id=event_id)


def test_rewrite_proposal_archives_outputs_without_changing_active_cells(evolution_store):
    """Catches proposal-time publication or mutable rewrite status."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    proposal = _proposal(
        "split-1",
        "split",
        inputs=("old",),
        outputs=(CellDraft("new-a", 0, "a"), CellDraft("new-b", 0, "b")),
    )

    assert engine.propose(proposal) == "split-1"
    assert engine.active_cell_ids("root") == ("old",)
    assert evolution_store.get_cell("new-a") is not None
    assert evolution_store.get_cell("new-b") is not None
    assert engine.latest_disposition("split-1") == "proposed"
    columns = {
        row[1]
        for row in evolution_store.connection.execute("PRAGMA table_info(cat_rewrites)")
    }
    assert "status" not in columns and "disposition" not in columns


def test_supported_split_commit_is_atomic_and_replay_hash_is_deterministic(evolution_store):
    """Catches a commit exposing partial active state or nondeterministic snapshots."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old", "kept")
    engine.propose(
        _proposal(
            "split-1",
            "split",
            inputs=("old",),
            outputs=(CellDraft("new-b", 0, "b"), CellDraft("new-a", 0, "a")),
        )
    )

    epoch_id = engine.commit("split-1", ("root",), epoch_id="epoch-1")

    assert epoch_id == "epoch-1"
    assert engine.active_cell_ids("epoch-1") == ("kept", "new-a", "new-b")
    assert engine.latest_disposition("split-1") == "committed"
    snapshot = evolution_store.connection.execute(
        "SELECT active_cell_ids_json, content_hash FROM cat_snapshots WHERE epoch_id='epoch-1'"
    ).fetchone()
    assert snapshot[0] == '["kept","new-a","new-b"]'
    assert snapshot[1] == canonical_snapshot_hash(("new-b", "kept", "new-a"))


def test_failed_proposal_and_rejected_commit_preserve_canonical_state(evolution_store):
    """Catches validation failure leaking cells or policy rejection changing activity."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    with pytest.raises(ValueError, match="member"):
        engine.propose(
            _proposal(
                "too-many",
                "split",
                inputs=("old",),
                outputs=tuple(CellDraft(f"n-{i}", 0, str(i)) for i in range(32)),
            )
        )
    assert engine.active_cell_ids("root") == ("old",)
    assert evolution_store.get_cell("n-0") is None

    engine.propose(
        _proposal(
            "noise",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("noise-output", 0, "noise"),),
            evidence=_evidence(persistence=0.09, gain=1.0, cost=0.0),
        )
    )
    assert engine.commit("noise", ("root",), epoch_id="never") is None
    assert engine.latest_disposition("noise") == "rejected"
    assert engine.active_cell_ids("root") == ("old",)
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='never'"
    ).fetchone()[0] == 0


def test_eligibility_rejects_noise_but_allows_explicit_correction():
    """Catches threshold drift and bypass of the exact explicit-correction rule."""
    policy = EvolutionPolicy()
    assert not is_eligible(_evidence(persistence=0.09, gain=1.0, cost=0.0), policy)
    assert not is_eligible(_evidence(persistence=1.0, gain=0.2, cost=0.2), policy)
    assert is_eligible(_evidence(explicit=True, persistence=0.0, gain=0.0, cost=1.0), policy)


@pytest.mark.parametrize(
    ("kind", "inputs", "outputs", "expected"),
    [
        ("retire", ("a",), (), ("b",)),
        ("retype", ("a",), (CellDraft("typed", 0, "typed"),), ("b", "typed")),
        ("merge", ("a", "b"), (CellDraft("merged", 0, "merged"),), ("merged",)),
    ],
)
def test_rewrite_kinds_preserve_lineage(kind, inputs, outputs, expected, tmp_path):
    """Catches retire/retype/merge losing immutable input/output lineage."""
    store = EvolvingCategoryStore(sqlite3.connect(tmp_path / f"{kind}.db"))
    try:
        engine = EvolutionEngine(store)
        _root(engine, store, "a", "b")
        engine.propose(_proposal(kind, kind, inputs=inputs, outputs=outputs))
        assert engine.commit(kind, ("root",), epoch_id=f"{kind}-epoch") == f"{kind}-epoch"
        assert engine.active_cell_ids(f"{kind}-epoch") == expected
        lineage = engine.lineage(kind)
        assert lineage["input"] == inputs
        assert lineage["output"] == tuple(draft.id for draft in outputs)
    finally:
        store.close()


def test_member_branch_and_epoch_parent_limits_are_exact(evolution_store):
    """Catches off-by-one limits and cyclic or over-wide epoch graphs."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, *(f"c-{i}" for i in range(32)))
    exact = _proposal("exact", "retire", inputs=tuple(f"c-{i}" for i in range(32)))
    assert engine.propose(exact) == "exact"

    for index in range(4):
        proposal_id = f"fork-{index}"
        engine.propose(
            _proposal(
                proposal_id,
                "create",
                outputs=(CellDraft(f"fork-cell-{index}", 0, str(index)),),
            )
        )
        assert engine.commit(proposal_id, ("root",), epoch_id=f"fork-epoch-{index}")
    engine.propose(
        _proposal("fifth", "create", outputs=(CellDraft("fifth-cell", 0, "fifth"),))
    )
    assert engine.commit("fifth", ("root",), epoch_id="fifth-epoch") is None
    assert engine.latest_disposition("fifth") == "rejected"
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='fifth-epoch'"
    ).fetchone()[0] == 0

    with pytest.raises(ValueError, match="parent"):
        engine.create_root_epoch("root", ())
    assert engine.epoch_parents("fork-epoch-0") == ("root",)


def test_old_epoch_selection_is_logical_and_corrupt_snapshot_rebuilds(evolution_store):
    """Catches rollback mutating history and trusting corrupt derived snapshots."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "replace",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("new", 0, "new"),),
        )
    )
    engine.commit("replace", ("root",), epoch_id="next")
    assert engine.select_epoch("root") == ("old",)
    assert engine.select_epoch("next") == ("new",)

    evolution_store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json='[\"bogus\"]', content_hash='bad' "
        "WHERE epoch_id='next'"
    )
    rebuilt = engine.active_cell_ids("next")
    assert rebuilt == ("new",)
    snapshot = evolution_store.connection.execute(
        "SELECT active_cell_ids_json, content_hash FROM cat_snapshots WHERE epoch_id='next'"
    ).fetchone()
    assert snapshot[0] == '["new"]'
    assert snapshot[1] == canonical_snapshot_hash(("new",))


def test_root_snapshot_rebuild_uses_immutable_explicit_active_history(evolution_store):
    """Catches root snapshot repair losing cells created by an earlier event."""
    engine = EvolutionEngine(evolution_store)
    creation_event = evolution_store.append_event("cells-created", {})
    evolution_store.create_cell(
        CellDraft("preexisting", 0, "preexisting"), created_event_id=creation_event
    )
    root_event = evolution_store.append_event("root-requested", {})
    engine.create_root_epoch("explicit-root", ("preexisting",), event_id=root_event)
    evolution_store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json='[]', content_hash='bad' "
        "WHERE epoch_id='explicit-root'"
    )

    assert engine.active_cell_ids("explicit-root") == ("preexisting",)


def test_commit_failure_rolls_back_epoch_snapshot_and_disposition_atomically(
    evolution_store, monkeypatch
):
    """Catches a late snapshot failure publishing any fragment of a commit."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "atomic",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("archived", 0, "archived"),),
        )
    )

    def fail_snapshot(*_args, **_kwargs):
        raise RuntimeError("injected snapshot failure")

    monkeypatch.setattr(engine, "_write_snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="snapshot failure"):
        engine.commit("atomic", ("root",), epoch_id="partial")

    assert engine.latest_disposition("atomic") == "proposed"
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='partial'"
    ).fetchone()[0] == 0
    assert evolution_store.get_cell("archived") is not None
    assert engine.active_cell_ids("root") == ("old",)


def test_commit_respects_caller_transaction_ownership(evolution_store):
    """Catches a nested commit that commits or rolls back its caller's work."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "nested",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("new", 0, "new"),),
        )
    )
    connection = evolution_store.connection
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) "
        "VALUES ('caller', 'caller', '{}', 'now')"
    )

    assert engine.commit("nested", ("root",), epoch_id="nested-epoch") == "nested-epoch"
    assert connection.in_transaction
    connection.rollback()

    assert connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE id='caller'"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='nested-epoch'"
    ).fetchone()[0] == 0
    assert engine.latest_disposition("nested") == "proposed"


def test_concurrent_commit_is_exactly_once_across_two_connections(tmp_path, monkeypatch):
    """Catches two readers both observing proposed state before either publishes."""
    database = tmp_path / "concurrent.db"
    setup = EvolvingCategoryStore(sqlite3.connect(database))
    engine = EvolutionEngine(setup)
    _root(engine, setup, "old")
    engine.propose(
        _proposal(
            "concurrent",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("new", 0, "new"),),
        )
    )
    setup.close()

    disposition_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(2)
    original_disposition = EvolutionEngine.latest_disposition

    def synchronize_pretransaction_read(self, rewrite_id):
        if not self.connection.in_transaction:
            disposition_barrier.wait(timeout=5)
        return original_disposition(self, rewrite_id)

    monkeypatch.setattr(
        EvolutionEngine, "latest_disposition", synchronize_pretransaction_read
    )
    results = []
    errors = []

    def worker():
        connection = sqlite3.connect(database, timeout=5)
        store = EvolvingCategoryStore(connection)
        try:
            start_barrier.wait(timeout=5)
            results.append(EvolutionEngine(store).commit("concurrent", ("root",)))
        except Exception as exc:  # captured for an assertion in the parent thread
            errors.append(exc)
        finally:
            store.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(set(results)) == 1

    connection = sqlite3.connect(database)
    try:
        epoch = connection.execute(
            "SELECT id FROM cat_epochs WHERE rewrite_id='concurrent'"
        ).fetchall()
        committed_events = [
            row[0]
            for row in connection.execute(
                "SELECT payload_json FROM cat_events WHERE kind='rewrite_committed'"
            )
            if json.loads(row[0])["rewrite_id"] == "concurrent"
        ]
        assert epoch == [(results[0],)]
        assert len(committed_events) == 1
    finally:
        connection.close()


@pytest.mark.parametrize("reject_first", [False, True])
def test_root_epoch_cannot_activate_archived_rewrite_outputs(
    evolution_store, reject_first
):
    """Catches root publication bypassing proposal and rejection policy."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "archived-output",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("archived", 0, "archived"),),
            evidence=_evidence(persistence=0.0),
        )
    )
    if reject_first:
        assert engine.commit("archived-output", ("root",)) is None

    before = {
        table: evolution_store.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in ("cat_events", "cat_epochs", "cat_snapshots")
    }
    with pytest.raises(ValueError, match="rewrite output"):
        engine.create_root_epoch("bypass", ("archived",))
    after = {
        table: evolution_store.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in before
    }
    assert after == before


def test_root_epoch_enforces_four_branch_limit_atomically(evolution_store):
    """Catches root creation bypassing the exact leaf-branch policy."""
    engine = EvolutionEngine(evolution_store)
    for index in range(4):
        assert engine.create_root_epoch(f"root-{index}", ()) == f"root-{index}"
    before = {
        table: evolution_store.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in ("cat_events", "cat_epochs", "cat_snapshots")
    }

    with pytest.raises(ValueError, match="branch"):
        engine.create_root_epoch("root-4", ())

    assert {
        table: evolution_store.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in before
    } == before


def test_latest_disposition_uses_append_order_under_backward_clock_skew(evolution_store):
    """Catches a later durable event losing to an earlier wall-clock timestamp."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "clock-skew",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("clock-output", 0, "clock"),),
        )
    )
    evolution_store.connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
        ("later-row", "rewrite_rejected", '{"rewrite_id":"clock-skew"}', "1900-01-01"),
    )

    assert engine.latest_disposition("clock-skew") == "rejected"


def test_multi_parent_commit_preserves_parent_order_and_unions_active_state(tmp_path):
    """Catches multi-parent lineage reordering or dropping one parent's active cells."""
    store = EvolvingCategoryStore(sqlite3.connect(tmp_path / "multi-parent.db"))
    try:
        engine = EvolutionEngine(store)
        store.create_cell(CellDraft("left", 0, "left"))
        store.create_cell(CellDraft("right", 0, "right"))
        engine.create_root_epoch("left-root", ("left",))
        engine.create_root_epoch("right-root", ("right",))
        engine.propose(
            _proposal(
                "join",
                "create",
                outputs=(CellDraft("joined", 0, "joined"),),
            )
        )

        epoch_id = engine.commit(
            "join", ("right-root", "left-root"), epoch_id="joined-epoch"
        )

        assert epoch_id == "joined-epoch"
        assert engine.epoch_parents(epoch_id) == ("right-root", "left-root")
        assert engine.active_cell_ids(epoch_id) == ("joined", "left", "right")
    finally:
        store.close()


def test_corrupt_cyclic_epoch_history_rejects_commit_without_epoch(evolution_store):
    """Catches validation traversing a corrupt parent cycle as if it were a DAG."""
    engine = EvolutionEngine(evolution_store)
    engine.create_root_epoch("cycle-a", ())
    engine.create_root_epoch("cycle-b", ())
    evolution_store.connection.execute(
        "INSERT INTO cat_epoch_parents (epoch_id, position, parent_id) VALUES (?, 0, ?)",
        ("cycle-a", "cycle-b"),
    )
    evolution_store.connection.execute(
        "INSERT INTO cat_epoch_parents (epoch_id, position, parent_id) VALUES (?, 0, ?)",
        ("cycle-b", "cycle-a"),
    )
    engine.propose(
        _proposal("after-cycle", "create", outputs=(CellDraft("cycle-out", 0, "out"),))
    )

    assert engine.commit("after-cycle", ("cycle-a",), epoch_id="must-not-exist") is None
    assert engine.latest_disposition("after-cycle") == "rejected"
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='must-not-exist'"
    ).fetchone()[0] == 0


def test_missing_parent_and_inactive_lineage_reject_without_epoch(evolution_store):
    """Catches commit accepting absent parents or inputs outside parent snapshots."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "active", "inactive")
    engine.create_root_epoch("other-root", ("active",))
    engine.propose(
        _proposal(
            "missing-parent",
            "retype",
            inputs=("active",),
            outputs=(CellDraft("missing-out", 0, "out"),),
        )
    )
    assert engine.commit(
        "missing-parent", ("absent",), epoch_id="missing-epoch"
    ) is None
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='missing-epoch'"
    ).fetchone()[0] == 0

    engine.propose(
        _proposal(
            "inactive-input",
            "retype",
            inputs=("inactive",),
            outputs=(CellDraft("inactive-out", 0, "out"),),
        )
    )
    assert engine.commit(
        "inactive-input", ("other-root",), epoch_id="inactive-epoch"
    ) is None
    assert evolution_store.connection.execute(
        "SELECT COUNT(*) FROM cat_epochs WHERE id='inactive-epoch'"
    ).fetchone()[0] == 0


def test_exact_mixed_role_member_boundary_is_32(evolution_store):
    """Catches per-role counting that lets the aggregate rewrite exceed policy."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, *(f"w-{index}" for index in range(31)))
    evidence_event = evolution_store.append_event("evidence", {})
    exact = _proposal(
        "mixed-32",
        "create",
        outputs=(CellDraft("mixed-output", 0, "out"),),
        witnesses=tuple(f"w-{index}" for index in range(30)),
        evidence=_evidence(events=(evidence_event,)),
    )
    assert engine.propose(exact) == "mixed-32"
    assert sum(len(values) for values in engine.lineage("mixed-32").values()) == 32

    with pytest.raises(ValueError, match="member"):
        engine.propose(
            _proposal(
                "mixed-33",
                "create",
                outputs=(CellDraft("mixed-too-many", 0, "out"),),
                witnesses=tuple(f"w-{index}" for index in range(31)),
                evidence=_evidence(events=(evidence_event,)),
            )
        )
    assert evolution_store.get_cell("mixed-too-many") is None


def test_explicit_correction_proposal_commits_despite_ordinary_ineligibility(
    evolution_store,
):
    """Catches explicit correction being honored only by the helper, not commit."""
    engine = EvolutionEngine(evolution_store)
    _root(engine, evolution_store, "old")
    engine.propose(
        _proposal(
            "explicit",
            "retype",
            inputs=("old",),
            outputs=(CellDraft("corrected", 0, "corrected"),),
            evidence=_evidence(explicit=True, persistence=0.0, gain=0.0, cost=1.0),
        )
    )

    assert engine.commit("explicit", ("root",), epoch_id="corrected-epoch") == "corrected-epoch"
    assert engine.active_cell_ids("corrected-epoch") == ("corrected",)


def test_equal_gain_consolidation_orders_by_creation_time_then_id(
    tmp_path, monkeypatch
):
    """Catches caller order deciding equal-gain consolidation ties."""
    store = EvolvingCategoryStore(sqlite3.connect(tmp_path / "ties.db"))
    try:
        engine = EvolutionEngine(store)
        _root(engine, store)
        created_times = iter(("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-03"))
        monkeypatch.setattr(
            "category_evolution._now_iso", lambda: next(created_times, "2026-01-04")
        )
        for proposal_id in ("z", "a", "c", "b"):
            engine.propose(
                _proposal(
                    proposal_id,
                    "create",
                    outputs=(CellDraft(f"out-{proposal_id}", 0, proposal_id),),
                    evidence=_evidence(gain=0.7, cost=0.2),
                )
            )

        committed = engine.consolidate(("b", "c", "a", "z"), "root")

        assert tuple(rewrite_id for rewrite_id, _epoch_id in committed) == (
            "z",
            "a",
            "b",
            "c",
        )
    finally:
        store.close()


def test_consolidation_order_and_budget_are_deterministic(tmp_path):
    """Catches LLM/input order bypassing deterministic policy or the 32 rewrite budget."""
    store = EvolvingCategoryStore(sqlite3.connect(tmp_path / "consolidate.db"))
    try:
        engine = EvolutionEngine(store)
        _root(engine, store)
        for index in range(34):
            proposal_id = f"p-{index:02d}"
            engine.propose(
                _proposal(
                    proposal_id,
                    "create",
                    outputs=(CellDraft(f"out-{index:02d}", 0, str(index)),),
                    evidence=_evidence(explicit=index == 33, gain=0.5 + index / 100, cost=0.1),
                )
            )
        committed = engine.consolidate(tuple(reversed([f"p-{i:02d}" for i in range(34)])), "root")
        assert len(committed) == 32
        assert committed[0][0] == "p-33"
        assert {proposal_id for proposal_id, _ in committed} == {
            "p-33",
            *(f"p-{i:02d}" for i in range(2, 33)),
        }
        assert engine.latest_disposition("p-00") == "superseded"
        assert engine.latest_disposition("p-01") == "superseded"
    finally:
        store.close()


def test_legacy_importer_module_is_available():
    """Catches removal of the replay entry point required by operators."""
    _importer()


def test_legacy_replay_creates_deterministic_proxies_cells_and_snapshot(tmp_path):
    """Catches replay that changes identity or omits a valid legacy relationship."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    evolution = _importer()
    first = evolution.import_legacy_category(legacy, tmp_path / "first-v2.db")
    second = evolution.import_legacy_category(legacy, tmp_path / "second-v2.db")

    for report in (first, second):
        assert report.legacy_total == 3
        assert report.proxy_zero_cells == 2
        assert report.imported_one_cells == 2
        assert report.imported_two_cells == 1
        assert report.opaque_cells == 0
        assert report.unexplained_loss == 0
        assert _v2_cell_count(tmp_path / ("first-v2.db" if report is first else "second-v2.db")) == 5
    assert first.snapshot_hash == second.snapshot_hash
    assert first.root_epoch_id == second.root_epoch_id
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns

    replayed = evolution.import_legacy_category(legacy, tmp_path / "first-v2.db")
    assert replayed == first
    assert _v2_cell_count(tmp_path / "first-v2.db") == 5
    assert _v2_counts(tmp_path / "first-v2.db") == {
        "cat_events": 1,
        "cat_cells": 5,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


def test_legacy_replay_has_one_snapshot_hash_across_three_independent_outputs(tmp_path):
    """Catches dependence on output database identity, insertion order, or wall-clock time."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)

    evolution = _importer()
    reports = [
        evolution.import_legacy_category(legacy, tmp_path / f"v2-{index}.db")
        for index in range(3)
    ]

    assert {report.snapshot_hash for report in reports} == {reports[0].snapshot_hash}
    assert {report.root_epoch_id for report in reports} == {reports[0].root_epoch_id}
    assert all(_v2_cell_count(tmp_path / f"v2-{index}.db") == 5 for index in range(3))


def test_legacy_replay_counts_missing_level_two_reference_as_loss_without_proxy(tmp_path):
    """Catches a malformed transfer being repaired with an invented category target."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "arrow", 1, "memory-alpha", "memory-beta", "valid arrow")
    _insert_legacy_cell(connection, "broken-transfer", 2, "arrow", "missing-arrow", "broken")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.legacy_total == 2
    assert report.imported_one_cells == 1
    assert report.imported_two_cells == 0
    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 3
    connection = sqlite3.connect(tmp_path / "v2.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM cat_cells WHERE id = 'missing-arrow'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_replay_cli_is_read_only_reports_json_and_returns_two_for_loss(tmp_path):
    """Catches the CLI opening its source database writable or hiding partial replay loss."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "broken", 2, "missing-a", "missing-b", "broken")
    connection.commit()
    connection.close()
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns
    output = tmp_path / "v2.db"
    script = Path(__file__).parents[1] / "category_evolution.py"

    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(legacy), "--output", str(output), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["unexplained_loss"] == 1
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_replay_cli_refuses_the_same_resolved_legacy_and_output_path(tmp_path):
    """Catches a destructive invocation that points v2 output at the legacy source."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns
    script = Path(__file__).parents[1] / "category_evolution.py"

    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(legacy), "--output", str(legacy), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: legacy input and v2 output")
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_legacy_replay_refuses_a_hard_link_to_the_legacy_database(tmp_path):
    """Catches an alias that would make the v2 output write into legacy storage."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    hard_link = tmp_path / "categories-hard-link.db"
    os.link(legacy, hard_link)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    with pytest.raises(ValueError, match="different paths"):
        _importer().import_legacy_category(legacy, hard_link)

    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_legacy_replay_is_atomic_when_an_existing_cell_conflicts(tmp_path):
    """Catches bootstrap rows committing before a later v2 cell conflict aborts."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    connection = sqlite3.connect(output)
    store = EvolvingCategoryStore(connection)
    store.create_cell(CellDraft("arrow-alpha", 0, "conflicting existing cell"))
    store.close()

    with pytest.raises(ValueError, match="conflicting"):
        _importer().import_legacy_category(legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 0,
        "cat_cells": 1,
        "cat_epochs": 0,
        "cat_snapshots": 0,
    }


def test_legacy_replay_publishes_new_output_only_after_schema_stage_succeeds(tmp_path, monkeypatch):
    """Catches schema bootstrap mutating a pre-existing empty output before replay succeeds."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    sqlite3.connect(output).close()
    output_bytes = output.read_bytes()
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    def fail_after_schema(*_args, **_kwargs):
        raise RuntimeError("injected after schema initialization")

    monkeypatch.setattr(EvolvingCategoryStore, "append_event", fail_after_schema)
    with pytest.raises(RuntimeError, match="injected after schema"):
        _importer().import_legacy_category(legacy, output)

    assert output.read_bytes() == output_bytes
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns
    assert not list(tmp_path.glob(".v2.db.*.replay.tmp*"))


def test_legacy_replay_discards_staged_output_after_partial_write_failure(tmp_path, monkeypatch):
    """Catches replay writes publishing a new output after a later staged cell failure."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns
    original_create_cell = EvolvingCategoryStore.create_cell
    calls = 0

    def fail_after_two_cells(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("injected after replay writes")
        return original_create_cell(self, *args, **kwargs)

    monkeypatch.setattr(EvolvingCategoryStore, "create_cell", fail_after_two_cells)
    with pytest.raises(RuntimeError, match="injected after replay writes"):
        _importer().import_legacy_category(legacy, output)

    assert not output.exists()
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns
    assert not list(tmp_path.glob(".v2.db.*.replay.tmp*"))


def test_legacy_replay_rejects_incompatible_output_before_schema_bootstrap(tmp_path):
    """Catches compatibility validation mutating an output it is about to reject."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "incompatible.db"
    _make_legacy_history(legacy)
    connection = sqlite3.connect(output)
    connection.execute("CREATE TABLE cat_events (id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO cat_events VALUES ('unrelated')")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)

    connection = sqlite3.connect(output)
    try:
        assert {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        } == {"cat_events"}
        assert connection.execute("SELECT id FROM cat_events").fetchone()[0] == "unrelated"
    finally:
        connection.close()


def test_legacy_replay_rejects_stale_output_with_same_active_ids(tmp_path):
    """Catches id-only snapshot matching that silently accepts changed source content."""
    first_legacy = tmp_path / "first.db"
    changed_legacy = tmp_path / "changed.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(first_legacy)
    connection = _legacy_connection(changed_legacy)
    _insert_legacy_cell(connection, "arrow-alpha", 1, "memory-alpha", "memory-beta", "changed alpha")
    _insert_legacy_cell(connection, "arrow-beta", 1, "memory-beta", "memory-alpha", "beta to alpha")
    _insert_legacy_cell(connection, "transfer", 2, "arrow-alpha", "arrow-beta", "transfer")
    connection.commit()
    connection.close()

    _importer().import_legacy_category(first_legacy, output)
    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(changed_legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 1,
        "cat_cells": 5,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


@pytest.mark.parametrize("changed_content", ["changed lost content", "other lost content"])
def test_legacy_replay_fingerprints_every_lost_source_row(tmp_path, changed_content):
    """Catches idempotence ignoring raw content from an unimportable legacy row."""
    first_legacy = tmp_path / "first.db"
    changed_legacy = tmp_path / "changed.db"
    output = tmp_path / "v2.db"
    first = _legacy_connection(first_legacy)
    _insert_legacy_cell(first, "lost", 1, "memory-a", None, "original lost content")
    first.commit()
    first.close()
    changed = _legacy_connection(changed_legacy)
    _insert_legacy_cell(changed, "lost", 1, "memory-a", None, changed_content)
    changed.commit()
    changed.close()

    _importer().import_legacy_category(first_legacy, output)
    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(changed_legacy, output)


def test_legacy_replay_fingerprints_loss_row_blob_values(tmp_path):
    """Catches type-erasing raw fingerprints for malformed legacy SQLite values."""
    first_legacy = tmp_path / "first.db"
    changed_legacy = tmp_path / "changed.db"
    output = tmp_path / "v2.db"
    for path, blob in ((first_legacy, b"first"), (changed_legacy, b"second")):
        connection = _legacy_connection(path)
        _insert_legacy_cell(
            connection,
            "lost",
            1,
            "memory-a",
            None,
            "lost",
            sqlite3.Binary(blob),
        )
        connection.commit()
        connection.close()

    _importer().import_legacy_category(first_legacy, output)
    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(changed_legacy, output)


def test_legacy_replay_rejects_a_completed_output_with_unrelated_rows(tmp_path):
    """Catches idempotence blessing a completed replay contaminated by extra rows."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
        ("unrelated-event", "unrelated", "{}", "now"),
    )
    connection.execute(
        """
        INSERT INTO cat_cells
            (id, dimension, content, payload_json, content_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "unrelated-cell",
            0,
            "unrelated",
            "{}",
            hashlib.sha256(b"unrelated").hexdigest(),
            "now",
        ),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="does not match source"):
        _importer().import_legacy_category(legacy, output)

    assert _v2_counts(output) == {
        "cat_events": 2,
        "cat_cells": 6,
        "cat_epochs": 1,
        "cat_snapshots": 1,
    }


def test_legacy_replay_rejects_an_unsupported_output_schema_version(tmp_path):
    """Catches preflight accepting a completed replay with unsupported schema history."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute(
        "INSERT INTO cat_schema_version (version, applied_at) VALUES (2, 'now')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_rejects_a_same_named_noop_immutability_trigger(tmp_path):
    """Catches compatibility checks that trust immutable-trigger names but not bodies."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("DROP TRIGGER cat_cells_no_update")
    connection.execute(
        "CREATE TRIGGER cat_cells_no_update BEFORE UPDATE ON cat_cells BEGIN SELECT 1; END"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_rejects_an_altered_same_named_table_definition(tmp_path):
    """Catches preflight accepting a table whose name matches but constraints differ."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("PRAGMA writable_schema = ON")
    connection.execute(
        """
        UPDATE sqlite_master
        SET sql = REPLACE(sql, 'dimension INTEGER NOT NULL CHECK (dimension >= 0)', 'dimension INTEGER NOT NULL')
        WHERE type = 'table' AND name = 'cat_cells'
        """
    )
    connection.execute("PRAGMA writable_schema = OFF")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_rejects_changed_quoted_check_literals(tmp_path):
    """Catches DDL normalization folding the case of quoted CHECK values."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("PRAGMA writable_schema = ON")
    connection.execute(
        """
        UPDATE sqlite_master
        SET sql = REPLACE(sql, "'source','target'", "'SOURCE','TARGET'")
        WHERE type = 'table' AND name = 'cat_boundaries'
        """
    )
    connection.execute("PRAGMA writable_schema = OFF")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_staged_publication_fsyncs_file_then_replaces_then_syncs_directory(tmp_path, monkeypatch):
    """Catches rename publication that misses the required post-rename directory sync."""
    evolution = _importer()
    staged = tmp_path / "staged.db"
    output = tmp_path / "output.db"
    staged.write_bytes(b"complete replay")
    calls: list[tuple[str, Path]] = []
    real_replace = evolution.os.replace

    def sync_file(path: Path) -> None:
        calls.append(("file", path))

    def replace(source: Path, destination: Path) -> None:
        calls.append(("replace", Path(destination)))
        real_replace(source, destination)

    def sync_directory(path: Path) -> None:
        calls.append(("directory", path))

    monkeypatch.setattr(evolution, "_fsync_file", sync_file)
    monkeypatch.setattr(evolution.os, "replace", replace)
    monkeypatch.setattr(evolution, "_fsync_directory", sync_directory)

    evolution._publish_staged_output(staged, output)

    assert output.read_bytes() == b"complete replay"
    assert calls == [
        ("file", staged),
        ("replace", output),
        ("directory", output.parent),
    ]


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_legacy_replay_rejects_infinite_raw_values_before_creating_output(tmp_path, value):
    """Catches non-finite raw SQLite values being fingerprinted or published ambiguously."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    connection = sqlite3.connect(legacy)
    connection.execute("UPDATE cells SET access_count = ?", (value,))
    connection.commit()
    connection.close()
    legacy_bytes = legacy.read_bytes()
    legacy_mtime_ns = legacy.stat().st_mtime_ns

    with pytest.raises(ValueError, match="non-finite"):
        _importer().import_legacy_category(legacy, output)

    assert not output.exists()
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime_ns


def test_legacy_replay_rejects_contaminated_or_invalid_vector_state(tmp_path):
    """Catches optional vector storage bypassing exact replay preflight checks."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("DROP TABLE IF EXISTS cat_vectors")
    connection.execute("CREATE TABLE cat_vectors (cell_id TEXT)")
    connection.execute("INSERT INTO cat_vectors VALUES ('unrelated')")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_accepts_an_empty_valid_vec0_table(tmp_path):
    """Catches preflight rejecting sqlite-vec's legitimate empty shadow-table layout."""
    import sqlite_vec

    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    first = _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    connection.execute(
        "CREATE VIRTUAL TABLE cat_vectors USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768])"
    )
    connection.commit()
    connection.close()

    assert _importer().import_legacy_category(legacy, output) == first


def test_legacy_replay_rejects_an_altered_empty_vec0_definition(tmp_path):
    """Catches vector preflight accepting changed vec0 ordering or distance semantics."""
    import sqlite_vec

    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    connection.execute(
        """
        CREATE VIRTUAL TABLE cat_vectors
        USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768] distance_metric=cosine)
        """
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible"):
        _importer().import_legacy_category(legacy, output)


def test_legacy_replay_rejects_a_completed_output_with_changed_context_id(tmp_path):
    """Catches exact replay validation overlooking a persisted cell context reference."""
    legacy = tmp_path / "categories.db"
    output = tmp_path / "v2.db"
    _make_legacy_history(legacy)
    _importer().import_legacy_category(legacy, output)
    connection = sqlite3.connect(output)
    connection.execute("DROP TRIGGER cat_cells_no_update")
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        "UPDATE cat_cells SET context_id = 'unrecorded-context' WHERE id = 'arrow-alpha'"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="incompatible|does not match source"):
        _importer().import_legacy_category(legacy, output)


def test_level_two_requires_two_imported_level_one_boundaries(tmp_path):
    """Catches transfers accepting zero-cells or other transfers as boundaries."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "zero", 0, None, None, "legacy zero")
    _insert_legacy_cell(connection, "arrow-a", 1, "memory-a", "memory-b", "a")
    _insert_legacy_cell(connection, "arrow-b", 1, "memory-b", "memory-a", "b")
    _insert_legacy_cell(connection, "transfer-a", 2, "arrow-a", "arrow-b", "valid transfer")
    _insert_legacy_cell(connection, "transfer-b", 2, "arrow-a", "zero", "zero boundary")
    _insert_legacy_cell(connection, "transfer-c", 2, "transfer-a", "arrow-b", "two boundary")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.imported_two_cells == 1
    assert report.unexplained_loss == 2
    connection = sqlite3.connect(tmp_path / "v2.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM cat_cells WHERE id IN ('transfer-b', 'transfer-c')"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_legacy_replay_preserves_full_cell_structure_and_bootstrap_linkage(tmp_path):
    """Catches persistence that changes proxy IDs, cell structure, or bootstrap linkage."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "arrow-a", 1, "memory-a", "memory-b", "a", '{"tag":"a"}')
    _insert_legacy_cell(connection, "arrow-b", 1, "memory-b", "memory-a", "b", '{"tag":"b"}')
    _insert_legacy_cell(connection, "transfer", 2, "arrow-a", "arrow-b", "transfer")
    _insert_legacy_cell(connection, "opaque", 3, "missing-a", "missing-b", "opaque")
    connection.commit()
    connection.close()
    output = tmp_path / "v2.db"

    report = _importer().import_legacy_category(legacy, output)
    expected_a = str(uuid.uuid5(uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223"), "memory:memory-a"))
    expected_b = str(uuid.uuid5(uuid.UUID("f4210ab5-b9e8-53ba-b3ca-261db44a9223"), "memory:memory-b"))
    connection = sqlite3.connect(output)
    try:
        cells = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT id, dimension, content, payload_json FROM cat_cells ORDER BY id"
            )
        }
        assert set(cells) == {expected_a, expected_b, "arrow-a", "arrow-b", "transfer", "opaque"}
        assert cells["arrow-a"][:2] == (1, "a")
        assert json.loads(cells["arrow-a"][2])["legacy"]["context"] == '{"tag":"a"}'
        assert cells["transfer"][:2] == (2, "transfer")
        assert cells["opaque"][:2] == (3, "opaque")
        assert json.loads(cells["opaque"][2])["legacy"]["source_id"] == "missing-a"
        boundaries = connection.execute(
            "SELECT cell_id, side, position, boundary_id FROM cat_boundaries ORDER BY cell_id, side, position"
        ).fetchall()
        assert boundaries == [
            ("arrow-a", "source", 0, expected_a),
            ("arrow-a", "target", 0, expected_b),
            ("arrow-b", "source", 0, expected_b),
            ("arrow-b", "target", 0, expected_a),
            ("transfer", "source", 0, "arrow-a"),
            ("transfer", "target", 0, "arrow-b"),
        ]
        event_id, kind, payload_json = connection.execute(
            "SELECT id, kind, payload_json FROM cat_events"
        ).fetchone()
        assert kind == "legacy_import_summary"
        assert "manifest_fingerprint" in json.loads(payload_json)
        epoch = connection.execute(
            "SELECT id, rewrite_id, created_event_id FROM cat_epochs"
        ).fetchone()
        assert epoch == (report.root_epoch_id, None, event_id)
        snapshot = connection.execute(
            "SELECT epoch_id, active_cell_ids_json, content_hash FROM cat_snapshots"
        ).fetchone()
        assert snapshot[0] == report.root_epoch_id
        assert snapshot[1] == json.dumps(sorted(cells), separators=(",", ":"))
        assert snapshot[2] == report.snapshot_hash
    finally:
        connection.close()


def test_legacy_replay_counts_malformed_level_one_as_loss(tmp_path):
    """Catches malformed level-one rows creating partial proxy relationships."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(connection, "broken-arrow", 1, "memory-a", None, "broken")
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.proxy_zero_cells == 0
    assert report.imported_one_cells == 0
    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 0


def test_legacy_replay_counts_nonserializable_metadata_as_loss(tmp_path):
    """Catches malformed legacy metadata escaping validation into manifest encoding."""
    legacy = tmp_path / "categories.db"
    connection = _legacy_connection(legacy)
    _insert_legacy_cell(
        connection,
        "blob-arrow",
        1,
        "memory-a",
        "memory-b",
        "blob metadata",
        sqlite3.Binary(b"not-json"),
    )
    connection.commit()
    connection.close()

    report = _importer().import_legacy_category(legacy, tmp_path / "v2.db")

    assert report.unexplained_loss == 1
    assert _v2_cell_count(tmp_path / "v2.db") == 0


def test_legacy_replay_refuses_symlink_and_relative_aliases(tmp_path, monkeypatch):
    """Catches path aliases bypassing the legacy-source write protection."""
    legacy = tmp_path / "categories.db"
    _make_legacy_history(legacy)
    alias = tmp_path / "legacy-link.db"
    alias.symlink_to(legacy.name)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="different paths"):
        _importer().import_legacy_category(Path("categories.db"), Path("legacy-link.db"))


def test_replay_cli_reports_database_errors_on_stderr_without_traceback(tmp_path):
    """Catches CLI database errors leaking tracebacks or machine output to stdout."""
    script = Path(__file__).parents[1] / "category_evolution.py"
    result = subprocess.run(
        [sys.executable, str(script), "replay", "--legacy", str(tmp_path / "missing.db"), "--output", str(tmp_path / "v2.db"), "--json"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("arguments", [[], ["replay", "--legacy", "missing.db"]])
def test_replay_cli_reserves_exit_two_for_unexplained_loss(arguments):
    """Catches argument errors using the partial-replay loss exit status."""
    script = Path(__file__).parents[1] / "category_evolution.py"
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(script.parent)},
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")
    assert "usage:" not in result.stderr
