from __future__ import annotations

import sqlite3
import struct
import json
import os
from pathlib import Path
import select
import threading
import time

import pytest

from categories import Boundary, CellDraft, EvolvingCategoryStore, WeightVector
from category_compile import (
    CategoryCompiler,
    CompileBudget,
    CompiledCell,
    estimate_tokens,
    valuation_v1,
)
from category_evolution import EvolutionEngine, RewriteEvidence, RewriteProposal


@pytest.fixture
def store(tmp_path):
    category_store = EvolvingCategoryStore(sqlite3.connect(tmp_path / "compile.db"))
    yield category_store
    category_store.close()


def _root(store, *drafts, epoch_id="root"):
    for draft in drafts:
        store.create_cell(draft)
    EvolutionEngine(store).create_root_epoch(epoch_id, (draft.id for draft in drafts))
    return epoch_id


def _observe(store, cell_id, *, context_id=None, relevance=0.0, evidence=0.0,
             recency=0.0, affect=0.0, adoption=0.0, novelty=0.0, cost=0.0):
    store.observe_weight(
        cell_id,
        context_id,
        WeightVector(relevance, evidence, recency, affect, adoption, novelty, cost),
    )


def _observe_dedicated_connections(monkeypatch):
    """Capture SQL and cleanup state from compiler-owned connections."""
    real_connect = sqlite3.connect
    traced_sql = []
    close_states = []

    class ObservedConnection(sqlite3.Connection):
        def close(self):
            temp_names = tuple(
                row[0]
                for row in super().execute(
                    "SELECT name FROM sqlite_temp_master "
                    "WHERE name LIKE 'category_compile_active_%' ORDER BY name"
                )
            )
            close_states.append((temp_names, self.in_transaction))
            return super().close()

    def connect_observed(*args, **kwargs):
        kwargs["factory"] = ObservedConnection
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(traced_sql.append)
        return connection

    monkeypatch.setattr("category_compile.sqlite3.connect", connect_observed)
    return traced_sql, close_states


def test_compiler_close_retries_failed_pool_member_without_losing_other_handles(
    store, monkeypatch
):
    """A partial pool close retains only failed ownership and blocks new leases."""
    real_connect = sqlite3.connect
    members = []

    class RetryConnection(sqlite3.Connection):
        def close(self):
            self.close_attempts += 1
            if self.fail_once:
                self.fail_once = False
                raise sqlite3.OperationalError("private close detail")
            return super().close()

    def connect_retry(*args, **kwargs):
        kwargs["factory"] = RetryConnection
        connection = real_connect(*args, **kwargs)
        connection.close_attempts = 0
        connection.fail_once = False
        members.append(connection)
        return connection

    monkeypatch.setattr("category_compile.sqlite3.connect", connect_retry)
    compiler = CategoryCompiler(store)
    failed = compiler._available_connections[1]
    failed.fail_once = True

    with pytest.raises(sqlite3.OperationalError):
        compiler.close()

    assert [member.close_attempts for member in members] == [1, 1, 1, 1]
    assert compiler._available_connections == [failed]
    assert compiler._closed is False
    with pytest.raises(RuntimeError, match="closed"):
        compiler._acquire_compile_connection(10**30)

    compiler.close()

    assert failed.close_attempts == 2
    assert [member.close_attempts for member in members if member is not failed] == [1, 1, 1]
    assert compiler._available_connections == []
    assert compiler._closed is True


def test_waiter_cannot_lease_handle_retained_after_partial_close(store, monkeypatch):
    """A pre-existing waiter rejects shutdown before borrowed leases return."""
    real_connect = sqlite3.connect

    class RetryConnection(sqlite3.Connection):
        def close(self):
            if self.fail_once:
                self.fail_once = False
                raise sqlite3.OperationalError("private close detail")
            return super().close()

    def connect_retry(*args, **kwargs):
        kwargs["factory"] = RetryConnection
        connection = real_connect(*args, **kwargs)
        connection.fail_once = False
        return connection

    monkeypatch.setattr("category_compile.sqlite3.connect", connect_retry)
    compiler = CategoryCompiler(store)
    leased = [compiler._acquire_compile_connection(10**30) for _ in range(4)]
    failed = leased[0]
    failed.fail_once = True

    class ObservedCondition(threading.Condition):
        def __init__(self):
            super().__init__()
            self.waiter_ident = None
            self.wait_count = 0
            self.first_wait = threading.Event()
            self.second_wait = threading.Event()
            self.close_notification = threading.Event()

        def wait(self, timeout=None):
            if threading.get_ident() == self.waiter_ident:
                self.wait_count += 1
                if self.wait_count == 1:
                    self.first_wait.set()
                elif self.wait_count == 2:
                    self.second_wait.set()
            return super().wait(timeout)

        def notify_all(self):
            if compiler._closing:
                self.close_notification.set()
            return super().notify_all()

    compiler._pool_condition = ObservedCondition()
    waiter_finished = threading.Event()
    acquired = []
    errors = []

    def wait_for_connection():
        compiler._pool_condition.waiter_ident = threading.get_ident()
        try:
            acquired.append(
                compiler._acquire_compile_connection(
                    time.monotonic_ns() + 500_000_000
                )
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            waiter_finished.set()

    waiter = threading.Thread(target=wait_for_connection)
    waiter.start()
    assert compiler._pool_condition.first_wait.wait(timeout=5)

    # A spurious wakeup must continue waiting while the compiler remains open.
    with compiler._pool_condition:
        compiler._pool_condition.notify_all()
    assert compiler._pool_condition.second_wait.wait(timeout=5)
    assert waiter_finished.is_set() is False

    close_errors = []
    close_finished = threading.Event()

    def close_pool():
        try:
            compiler.close()
        except Exception as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    closing = threading.Thread(target=close_pool)
    closing.start()

    try:
        assert compiler._pool_condition.close_notification.wait(timeout=5)
        assert waiter_finished.wait(timeout=0.25)
        assert close_finished.is_set() is False
        assert acquired == []
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

        for connection in leased:
            compiler._release_compile_connection(connection)
        assert close_finished.wait(timeout=5)
        closing.join(timeout=5)
        assert len(close_errors) == 1
        assert isinstance(close_errors[0], sqlite3.OperationalError)
        assert compiler._available_connections == [failed]

        compiler.close()
        assert compiler._available_connections == []
        assert compiler._closed is True
    finally:
        with compiler._pool_condition:
            still_leased = tuple(compiler._leased_connections)
        for connection in still_leased:
            compiler._release_compile_connection(connection)
        close_finished.wait(timeout=5)
        closing.join(timeout=5)
        waiter.join(timeout=5)
        if not compiler._closed:
            compiler.close()


def test_close_retains_borrowed_handle_that_fails_release_during_pool_shutdown(
    store, monkeypatch
):
    """Shutdown waits for a borrowed member and owns its late close failure."""
    real_connect = sqlite3.connect
    available_closed = threading.Event()
    members = []
    close_count_lock = threading.Lock()
    available_close_count = 0

    class InterleavedConnection(sqlite3.Connection):
        def close(self):
            nonlocal available_close_count
            self.close_attempts += 1
            if self.fail_once:
                self.fail_once = False
                raise sqlite3.OperationalError("private borrowed close detail")
            result = super().close()
            if self is not borrowed:
                with close_count_lock:
                    available_close_count += 1
                    if available_close_count == 3:
                        available_closed.set()
            return result

    def connect_interleaved(*args, **kwargs):
        kwargs["factory"] = InterleavedConnection
        connection = real_connect(*args, **kwargs)
        connection.close_attempts = 0
        connection.fail_once = False
        members.append(connection)
        return connection

    monkeypatch.setattr("category_compile.sqlite3.connect", connect_interleaved)
    compiler = CategoryCompiler(store)
    borrowed = compiler._acquire_compile_connection(10**30)
    borrowed.fail_once = True
    close_errors = []
    close_finished = threading.Event()

    def close_pool():
        try:
            compiler.close()
        except Exception as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    closing = threading.Thread(target=close_pool)
    closing.start()
    assert available_closed.wait(timeout=5)
    assert close_finished.wait(timeout=0.1) is False

    compiler._release_compile_connection(borrowed)
    assert close_finished.wait(timeout=5)
    closing.join(timeout=5)

    assert not closing.is_alive()
    assert len(close_errors) == 1
    assert isinstance(close_errors[0], sqlite3.OperationalError)
    assert compiler._available_connections == [borrowed]
    assert compiler._closed is False
    assert compiler._closing is True

    compiler.close()

    assert borrowed.close_attempts == 2
    assert compiler._available_connections == []
    assert compiler._closed is True


def test_close_waits_for_all_concurrent_borrowed_successes(store):
    """Shutdown cannot complete until every successful late release is closed."""
    compiler = CategoryCompiler(store)
    borrowed = [compiler._acquire_compile_connection(10**30) for _ in range(2)]
    close_errors = []
    close_finished = threading.Event()

    def close_pool():
        try:
            compiler.close()
        except Exception as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    closing = threading.Thread(target=close_pool)
    closing.start()
    deadline = time.monotonic() + 5
    with compiler._pool_condition:
        while not compiler._close_in_progress:
            remaining = deadline - time.monotonic()
            assert remaining > 0
            compiler._pool_condition.wait(timeout=remaining)
    assert close_finished.wait(timeout=0.1) is False

    compiler._release_compile_connection(borrowed[0])
    assert close_finished.wait(timeout=0.1) is False
    compiler._release_compile_connection(borrowed[1])
    assert close_finished.wait(timeout=5)
    closing.join(timeout=5)

    assert close_errors == []
    assert compiler._leased_connections == {}
    assert compiler._available_connections == []
    assert compiler._closed is True


def test_close_from_thread_owning_lease_fails_without_self_deadlock(store):
    """A lease owner cannot wait for itself while leading pool shutdown."""
    compiler = CategoryCompiler(store)
    leased = threading.Event()
    finished = threading.Event()
    externally_released = threading.Event()
    borrowed = []
    errors = []

    def borrow_then_close():
        connection = compiler._acquire_compile_connection(10**30)
        borrowed.append(connection)
        leased.set()
        try:
            compiler.close()
        except Exception as exc:
            errors.append(exc)
        finally:
            if not externally_released.is_set():
                compiler._release_compile_connection(connection)
            finished.set()

    owner = threading.Thread(target=borrow_then_close)
    owner.start()
    assert leased.wait(timeout=5)
    completed_without_help = finished.wait(timeout=0.1)
    if not completed_without_help:
        externally_released.set()
        compiler._release_compile_connection(borrowed[0])
        assert finished.wait(timeout=5)
    owner.join(timeout=5)
    try:
        assert completed_without_help is True
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        assert compiler._closing is False
    finally:
        compiler.close()


def _observe_compile_boundary_calls(compiler, monkeypatch):
    """Record lease/staging calls while retaining their real side effects."""
    calls = []
    original_acquire = compiler._acquire_compile_connection
    original_stage = compiler._stage_active_membership

    def observe_acquire(deadline):
        calls.append("lease")
        return original_acquire(deadline)

    def observe_stage(epoch_id, active_table, deadline):
        calls.append("stage")
        return original_stage(epoch_id, active_table, deadline)

    monkeypatch.setattr(compiler, "_acquire_compile_connection", observe_acquire)
    monkeypatch.setattr(compiler, "_stage_active_membership", observe_stage)
    return calls


def test_weight_channels_remain_separate():
    weights = WeightVector(0.8, 0.9, 0.5, -0.7, 0.2, 0.6, 0.4)

    score, parts = valuation_v1(weights)

    assert parts == {
        "relevance": 0.24,
        "evidence": 0.18,
        "recency": 0.05,
        "affect_salience": 0.07,
        "adoption": 0.02,
        "novelty": 0.09,
        "cost": -0.02,
    }
    assert score == pytest.approx(sum(parts.values()))
    assert weights.affect == -0.7


def test_valuation_channels_cannot_masquerade_as_each_other():
    _, relevance = valuation_v1(WeightVector(1, 0, 0, -1, 0, 0, 0))
    _, evidence = valuation_v1(WeightVector(0, 1, 0, 0, 1, 0, 0))
    _, positive_affect = valuation_v1(WeightVector(0, 1, 0, 1, 0, 0, 0))

    assert relevance["relevance"] == 0.30
    assert relevance["evidence"] == 0.0
    assert relevance["affect_salience"] == 0.10
    assert evidence["relevance"] == 0.0
    assert evidence["evidence"] == positive_affect["evidence"] == 0.20
    assert evidence["adoption"] == 0.10
    assert positive_affect["adoption"] == 0.0


def test_budget_defaults_and_utf8_token_estimator_are_exact():
    assert CompileBudget() == CompileBudget(
        normal_target=36_000,
        rotation_watermark=40_000,
        hard_ceiling=65_536,
        base_tokens=0,
        max_depth=4,
        max_neighbors=64,
        max_candidates=50_000,
        wall_time_ms=500,
    )
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("éé") == 1
    assert estimate_tokens("ééé") == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("normal_target", True),
        ("rotation_watermark", 1.5),
        ("hard_ceiling", float("nan")),
        ("base_tokens", False),
        ("max_depth", 4.0),
        ("max_neighbors", True),
        ("max_candidates", 2.5),
        ("wall_time_ms", False),
        ("hard_ceiling", 65_537),
        ("max_depth", 5),
        ("max_neighbors", 65),
        ("max_candidates", 50_001),
        ("wall_time_ms", 0),
        ("wall_time_ms", 501),
    ],
)
def test_budget_rejects_non_integer_oversized_and_nonpositive_limits(field, value):
    with pytest.raises((TypeError, ValueError)):
        CompileBudget(**{field: value})


@pytest.mark.parametrize(
    "values",
    [
        {"normal_target": -1},
        {"normal_target": 10, "rotation_watermark": 9},
        {"rotation_watermark": 11, "hard_ceiling": 10},
        {"hard_ceiling": 10, "base_tokens": 11},
        {"max_depth": -1},
        {"max_neighbors": -1},
        {"max_candidates": -1},
    ],
)
def test_budget_rejects_incoherent_or_negative_values(values):
    with pytest.raises(ValueError):
        CompileBudget(**values)


def test_budget_allows_equal_token_boundaries():
    assert CompileBudget(
        normal_target=0,
        rotation_watermark=0,
        hard_ceiling=0,
        base_tokens=0,
        wall_time_ms=1,
    ).hard_ceiling == 0
    assert CompileBudget(wall_time_ms=500).wall_time_ms == 500


def test_traversal_stops_at_depth_four_without_marking_graph_exhaustion(store):
    drafts = [CellDraft(f"node-{index}", 0, f"node {index}") for index in range(6)]
    for draft in drafts:
        store.create_cell(draft)
    arrows = []
    for index in range(5):
        arrow = CellDraft(
            f"edge-{index}",
            1,
            f"edge {index}",
            (
                Boundary("source", 0, f"node-{index}"),
                Boundary("target", 0, f"node-{index + 1}"),
            ),
        )
        store.create_cell(arrow)
        arrows.append(arrow)
    EvolutionEngine(store).create_root_epoch(
        "chain", [draft.id for draft in drafts] + [arrow.id for arrow in arrows]
    )

    result = CategoryCompiler(store).compile("chain", None, ("node-0",), 0)

    hops = {cell.id: cell.hops for cell in result.cells}
    assert {cell_id: hops[cell_id] for cell_id in (
        "node-0", "edge-0", "node-1", "edge-1", "node-2"
    )} == {
        "node-0": 0,
        "edge-0": 1,
        "node-1": 2,
        "edge-1": 3,
        "node-2": 4,
    }
    assert "edge-2" not in {cell.id for cell in result.cells}
    assert result.truncated

    exhausted = CategoryCompiler(store).compile("chain", None, ("node-5",), 0)
    assert exhausted.truncated

    isolated_epoch = _root(store, CellDraft("isolated", 0, "alone"), epoch_id="isolated-root")
    isolated = CategoryCompiler(store).compile(isolated_epoch, None, ("isolated",), 0)
    assert not isolated.truncated


def test_neighbor_and_candidate_caps_are_deterministic_and_mark_truncation(store):
    hub = CellDraft("hub", 0, "hub")
    store.create_cell(hub)
    drafts = [hub]
    for index in range(65):
        leaf = CellDraft(f"leaf-{index:02d}", 0, f"leaf {index}")
        edge = CellDraft(
            f"edge-{index:02d}",
            1,
            f"edge {index}",
            (Boundary("source", 0, "hub"), Boundary("target", 0, leaf.id)),
        )
        store.create_cell(leaf)
        store.create_cell(edge)
        drafts.extend((leaf, edge))
    EvolutionEngine(store).create_root_epoch("dense", (draft.id for draft in drafts))

    bounded = CategoryCompiler(store).compile("dense", None, ("hub",), 0)
    bounded_ids = {cell.id for cell in bounded.cells}
    assert "edge-63" in bounded_ids
    assert "edge-64" not in bounded_ids
    assert bounded.truncated

    candidate_limited = CategoryCompiler(
        store, CompileBudget(max_candidates=3)
    ).compile("dense", None, ("hub",), 0)
    assert candidate_limited.candidate_count == 3
    assert candidate_limited.truncated


def test_opaque_neighbors_cannot_starve_or_bridge_interpretable_cells(store):
    store.create_cell(CellDraft("hub", 0, "hub"))
    active = ["hub"]
    for index in range(3):
        opaque = CellDraft(
            f"a-opaque-{index}",
            3,
            "opaque",
            (Boundary("source", 0, "hub"),),
        )
        store.create_cell(opaque)
        active.append(opaque.id)
    store.create_cell(CellDraft("useful", 0, "useful distant content"))
    store.create_cell(
        CellDraft(
            "z-useful-edge",
            1,
            "useful relation",
            (Boundary("source", 0, "hub"), Boundary("target", 0, "useful")),
        )
    )
    active.extend(("useful", "z-useful-edge"))
    EvolutionEngine(store).create_root_epoch("opaque-dense", active)

    result = CategoryCompiler(
        store, CompileBudget(max_neighbors=1)
    ).compile("opaque-dense", None, ("hub",), 0)

    assert "z-useful-edge" in {cell.id for cell in result.cells}
    assert not {cell.id for cell in result.cells} & {
        "a-opaque-0", "a-opaque-1", "a-opaque-2"
    }


def test_historical_seed_translates_only_to_active_interpretable_descendants(store):
    old = CellDraft("old", 0, "old category")
    opaque = CellDraft("opaque", 3, "opaque implementation")
    _root(store, old, opaque)
    engine = EvolutionEngine(store)
    outputs = (CellDraft("new-a", 0, "new alpha"), CellDraft("new-b", 0, "new beta"))
    engine.propose(
        RewriteProposal(
            "split-old",
            "split",
            "locus",
            None,
            ("old",),
            outputs,
            (),
            RewriteEvidence((), 0.8, 0.5, 0.2),
        )
    )
    assert engine.commit("split-old", ("root",), epoch_id="current") == "current"

    result = CategoryCompiler(store).compile("current", None, ("old", "opaque"), 0)

    assert tuple(cell.id for cell in result.cells) == ("new-a", "new-b")
    assert all(cell.dimension <= 2 for cell in result.cells)
    assert CategoryCompiler(store).compile("current", None, ("missing",), 0).cells == ()


def test_mmr_keeps_distant_useful_content_and_breaks_ties_by_id(store):
    drafts = (
        CellDraft("a-copy", 0, "shared repeated concept"),
        CellDraft("b-copy", 0, "shared repeated concept"),
        CellDraft("c-distant", 0, "remote orthogonal signal"),
    )
    _root(store, *drafts)
    for cell_id in ("a-copy", "b-copy"):
        _observe(store, cell_id, relevance=1.0, evidence=1.0, recency=1.0,
                 affect=1.0, adoption=1.0, novelty=1.0, cost=0.0)
    _observe(store, "c-distant", relevance=1.0, evidence=1.0, recency=1.0,
             affect=0.0, adoption=0.0, novelty=2 / 3, cost=0.0)
    per_cell = estimate_tokens(drafts[0].content)
    budget = CompileBudget(
        normal_target=per_cell * 2,
        rotation_watermark=100,
        hard_ceiling=100,
    )
    compiler = CategoryCompiler(store, budget)

    first = compiler.compile("root", None, tuple(draft.id for draft in drafts), 0)
    second = compiler.compile("root", None, tuple(reversed([d.id for d in drafts])), 0)

    assert tuple(cell.id for cell in first.cells) == ("a-copy", "c-distant")
    assert first.cells == second.cells
    assert first.token_count == per_cell * 2
    assert first.truncated


def test_token_packing_never_crosses_hard_ceiling_and_rotation_is_exact(store):
    _root(
        store,
        CellDraft("a", 0, "a" * 80),
        CellDraft("b", 0, "b" * 80),
    )
    for cell_id in ("a", "b"):
        _observe(store, cell_id, relevance=1.0)

    near_hard = CategoryCompiler(
        store,
        CompileBudget(normal_target=65_536, rotation_watermark=65_536),
    ).compile("root", None, ("a", "b"), 65_510)
    assert 65_510 + near_hard.token_count <= 65_536
    assert near_hard.truncated

    at_rotation = CategoryCompiler(store).compile("root", None, ("a",), 40_000)
    assert at_rotation.rotation_required
    assert at_rotation.cells == ()
    assert at_rotation.truncated

    at_hard = CategoryCompiler(store).compile("missing-epoch", None, ("a",), 65_536)
    assert at_hard.cells == ()
    assert at_hard.token_count == 0
    assert at_hard.rotation_required
    assert at_hard.truncated

    at_hard_empty = CategoryCompiler(store).compile(
        "missing-epoch", None, (cell_id for cell_id in ()), 65_536
    )
    assert at_hard_empty.cells == ()
    assert at_hard_empty.token_count == 0
    assert at_hard_empty.rotation_required
    assert not at_hard_empty.truncated

    peeked = False

    def seeds_for_invalid_base():
        nonlocal peeked
        peeked = True
        yield "a"

    with pytest.raises(ValueError, match="base tokens"):
        CategoryCompiler(store).compile(
            "root", None, seeds_for_invalid_base(), 65_537
        )
    assert not peeked
    with pytest.raises(TypeError, match="base tokens"):
        CategoryCompiler(store).compile("root", None, ("a",), True)


def test_context_weights_and_output_order_are_stable_and_hashable(store):
    context_id = store.create_context({"task": "compiler"})
    _root(store, CellDraft("b", 0, "beta"), CellDraft("a", 0, "alpha"))
    _observe(store, "a", context_id=context_id, relevance=0.5, affect=-0.8)
    _observe(store, "b", context_id=context_id, relevance=0.5, affect=-0.8)

    result = CategoryCompiler(store).compile("root", context_id, ("b", "a"), 0)

    assert tuple(cell.id for cell in result.cells) == ("a", "b")
    assert result.cells[0].contributions["affect_salience"] == 0.08
    assert result.cells[0].affect == -0.8
    assert hash(result.cells[0]) == hash(result.cells[0])


def test_sql_deadline_interrupt_cleans_progress_handler_and_temp_state(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    large_active = json.dumps([f"missing-{index}" for index in range(20_000)])
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (large_active,),
    )
    store.connection.commit()
    persistent_before = tuple(
        store.connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )
    )
    clock_calls = 0

    def expires_during_staging():
        nonlocal clock_calls
        clock_calls += 1
        return 0 if clock_calls < 8 else 2_000_000

    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        expires_during_staging,
    )
    monkeypatch.setattr(
        CategoryCompiler,
        "_compile_active",
        lambda *_args, **_kwargs: pytest.fail("staging was not interrupted"),
    )

    compiler = CategoryCompiler(store, CompileBudget(wall_time_ms=1))
    result = compiler.compile("root", None, ("seed",), 0)
    compiler.close()

    assert result.cells == ()
    assert result.truncated
    assert close_states == [((), False)] * 4
    assert tuple(
        store.connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )
    ) == persistent_before
    # An expired callback would interrupt this if the compiler leaked it.
    assert store.connection.execute(
        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<10000) "
        "SELECT MAX(x) FROM n"
    ).fetchone()[0] == 10_000


def test_dedicated_connection_preserves_caller_transaction_and_progress_handler(
    store, monkeypatch
):
    _root(store, CellDraft("seed", 0, "seed"))
    large_active = json.dumps([f"missing-{index}" for index in range(20_000)])
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (large_active,),
    )
    store.connection.commit()
    progress_calls = 0

    def caller_progress():
        nonlocal progress_calls
        progress_calls += 1
        return 0

    store.connection.set_progress_handler(caller_progress, 1)
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('caller-pending', 'test', '{}', 'now')"
    )
    clock_calls = 0

    def expires_during_staging():
        nonlocal clock_calls
        clock_calls += 1
        return 0 if clock_calls < 8 else 2_000_000


    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        expires_during_staging,
    )
    monkeypatch.setattr(
        CategoryCompiler,
        "_compile_active",
        lambda *_args, **_kwargs: pytest.fail("staging was not interrupted"),
    )
    try:
        result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
            "root", None, ("seed",), 0
        )
        calls_after_compile = progress_calls
        assert store.connection.execute("SELECT COUNT(*) FROM cat_cells").fetchone()[0] == 1
        assert progress_calls > calls_after_compile
    finally:
        store.connection.set_progress_handler(None, 0)

    assert result.cells == ()
    assert result.truncated
    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-pending'"
    ).fetchone()[0] == "test"
    store.connection.rollback()


def test_file_compile_reads_committed_snapshot_without_touching_caller_write(store):
    _root(store, CellDraft("seed", 0, "seed"))
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('pending', 'test', '{}', 'now')"
    )

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert tuple(cell.id for cell in result.cells) == ("seed",)
    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'pending'"
    ).fetchone()[0] == "test"
    store.connection.rollback()


def test_snapshot_size_check_and_staging_share_one_pinned_read_snapshot(
    store, monkeypatch
):
    store.connection.execute("PRAGMA journal_mode = WAL")
    _root(store, CellDraft("seed", 0, "seed"))
    database_path = store.connection.execute("PRAGMA database_list").fetchone()[2]
    real_connect = sqlite3.connect
    size_checked = threading.Event()
    resume_staging = threading.Event()
    paused = False

    class PausingCursor(sqlite3.Cursor):
        pause_after_fetch = False

        def execute(self, sql, parameters=()):
            self.pause_after_fetch = (
                "length(cast(active_cell_ids_json as blob))" in sql.lower()
            )
            return super().execute(sql, parameters)

        def fetchone(self):
            nonlocal paused
            row = super().fetchone()
            if self.pause_after_fetch and not paused:
                paused = True
                size_checked.set()
                assert resume_staging.wait(5)
            return row

    class PausingConnection(sqlite3.Connection):
        def cursor(self, factory=PausingCursor):
            return super().cursor(factory)

        def execute(self, sql, parameters=()):
            return self.cursor().execute(sql, parameters)

    def connect_compile(*args, **kwargs):
        kwargs["factory"] = PausingConnection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("category_compile.sqlite3.connect", connect_compile)
    monkeypatch.setattr(
        "category_compile._MAX_ACTIVE_SNAPSHOT_BYTES", 64, raising=False
    )
    compiler = CategoryCompiler(store)
    writer_errors = []

    def replace_snapshot():
        assert size_checked.wait(5)
        writer = real_connect(database_path)
        try:
            writer.execute(
                "INSERT INTO cat_snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    "new-snapshot",
                    "root",
                    json.dumps(["replacement-" + "x" * 128]),
                    "replacement-hash",
                    "later",
                ),
            )
            writer.commit()
        except BaseException as exc:
            writer_errors.append(exc)
        finally:
            writer.close()
            resume_staging.set()

    thread = threading.Thread(target=replace_snapshot)
    thread.start()
    result = compiler.compile("root", None, ("seed",), 0)
    thread.join(5)

    assert not thread.is_alive()
    assert writer_errors == []
    assert tuple(cell.id for cell in result.cells) == ("seed",)
    assert not result.truncated

    future = compiler.compile("root", None, ("seed",), 0)
    assert future.cells == ()
    assert future.truncated
    compiler.close()


def test_reentrant_seed_iteration_keeps_each_compile_connection_isolated(
    store, monkeypatch
):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    compiler = CategoryCompiler(store)
    nested_results = []

    def reentrant_seeds():
        nested_results.append(compiler.compile("root", None, ("seed",), 0))
        yield "seed"

    outer = compiler.compile("root", None, reentrant_seeds(), 0)

    assert tuple(cell.id for cell in outer.cells) == ("seed",)
    assert tuple(cell.id for cell in nested_results[0].cells) == ("seed",)
    assert not store.connection.in_transaction
    compiler.close()
    assert sorted(close_states) == [((), False)] * 4


def test_database_file_replacement_after_construction_is_rejected(store, tmp_path):
    _root(store, CellDraft("seed", 0, "original"))
    compiler = CategoryCompiler(store)
    database_path = store.connection.execute("PRAGMA database_list").fetchone()[2]
    replacement_path = tmp_path / "replacement.db"
    replacement = EvolvingCategoryStore(sqlite3.connect(replacement_path))
    try:
        _root(replacement, CellDraft("seed", 0, "replacement"))
    finally:
        replacement.close()

    os.replace(replacement_path, database_path)

    with pytest.raises(ValueError, match="database file identity changed"):
        compiler.compile("root", None, ("seed",), 0)
    compiler.close()
    assert list(Path(database_path).parent.glob(".category-compile-*")) == []


def test_database_file_replacement_during_read_connection_open_is_rejected(
    store, tmp_path, monkeypatch
):
    _root(store, CellDraft("seed", 0, "original"))
    database_path = store.connection.execute("PRAGMA database_list").fetchone()[2]
    replacement_path = tmp_path / "racing-replacement.db"
    replacement = EvolvingCategoryStore(sqlite3.connect(replacement_path))
    try:
        _root(replacement, CellDraft("seed", 0, "replacement"))
    finally:
        replacement.close()
    real_connect = sqlite3.connect
    replaced = False

    def replace_during_open(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            os.replace(replacement_path, database_path)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("category_compile.sqlite3.connect", replace_during_open)

    with pytest.raises(ValueError, match="database file identity changed"):
        CategoryCompiler(store)
    assert replaced
    assert list(Path(database_path).parent.glob(".category-compile-*")) == []


def test_database_aba_swap_during_open_cannot_redirect_compile(
    store, tmp_path
):
    _root(store, CellDraft("seed", 0, "ORIGINAL"))
    compiler = CategoryCompiler(store)
    database_path = store.connection.execute("PRAGMA database_list").fetchone()[2]
    replacement_path = tmp_path / "aba-replacement.db"
    original_away = tmp_path / "original-away.db"
    replacement = EvolvingCategoryStore(sqlite3.connect(replacement_path))
    try:
        _root(replacement, CellDraft("seed", 0, "REPLACEMENT"))
    finally:
        replacement.close()
    swapped = False

    def swap_during_seed_iteration():
        nonlocal swapped
        swapped = True
        os.replace(database_path, original_away)
        os.replace(replacement_path, database_path)
        try:
            pass
        finally:
            os.replace(database_path, replacement_path)
            os.replace(original_away, database_path)
        yield "seed"

    result = compiler.compile("root", None, swap_during_seed_iteration(), 0)

    assert swapped
    assert tuple(cell.content for cell in result.cells) == ("ORIGINAL",)
    compiler.close()


@pytest.mark.skipif(
    not hasattr(select, "kqueue"),
    reason="constructor ABA latching is a macOS kqueue guarantee",
)
def test_constructor_rejects_aba_swap_around_each_pooled_connection_open(
    store, tmp_path, monkeypatch
):
    _root(store, CellDraft("seed", 0, "ORIGINAL"))
    database_path = store.connection.execute("PRAGMA database_list").fetchone()[2]
    replacement_path = tmp_path / "constructor-aba-replacement.db"
    original_away = tmp_path / "constructor-original-away.db"
    replacement = EvolvingCategoryStore(sqlite3.connect(replacement_path))
    try:
        _root(replacement, CellDraft("seed", 0, "REPLACEMENT"))
    finally:
        replacement.close()
    real_connect = sqlite3.connect
    connect_calls = 0

    def swap_while_pooled_connection_opens(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        os.replace(database_path, original_away)
        os.replace(replacement_path, database_path)
        try:
            return real_connect(*args, **kwargs)
        finally:
            os.replace(database_path, replacement_path)
            os.replace(original_away, database_path)

    monkeypatch.setattr(
        "category_compile.sqlite3.connect", swap_while_pooled_connection_opens
    )

    with pytest.raises(ValueError, match="database file identity changed"):
        CategoryCompiler(store)
    assert connect_calls == 1


@pytest.mark.skipif(
    not hasattr(select, "kqueue"),
    reason="constructor ABA latching is a macOS kqueue guarantee",
)
def test_constructor_rechecks_identity_before_open_and_polls_watcher_last(
    store, tmp_path, monkeypatch
):
    _root(store, CellDraft("seed", 0, "ORIGINAL"))
    database_path = Path(
        store.connection.execute("PRAGMA database_list").fetchone()[2]
    )
    replacement_path = tmp_path / "pre-registration-replacement.db"
    original_away = tmp_path / "pre-registration-original-away.db"
    replacement = EvolvingCategoryStore(sqlite3.connect(replacement_path))
    try:
        _root(replacement, CellDraft("seed", 0, "REPLACEMENT"))
    finally:
        replacement.close()

    real_kqueue = select.kqueue
    real_connect = sqlite3.connect
    swapped = False
    restored = False
    opened_connections = []

    def restore_original():
        nonlocal restored
        if not swapped or restored:
            return
        os.replace(database_path, replacement_path)
        os.replace(original_away, database_path)
        restored = True

    class SwapBeforeRegistrationQueue:
        def __init__(self):
            self.queue = real_kqueue()

        def control(self, changelist, max_events, timeout=None):
            nonlocal swapped
            if changelist is not None and not swapped:
                os.replace(database_path, original_away)
                os.replace(replacement_path, database_path)
                swapped = True
            if timeout is None:
                events = self.queue.control(changelist, max_events)
            else:
                events = self.queue.control(changelist, max_events, timeout)
            if changelist is None:
                # Restore just after the old, prematurely placed watcher poll.
                restore_original()
            return events

        def close(self):
            self.queue.close()

    def observe_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened_connections.append(connection)
        return connection

    monkeypatch.setattr("category_compile.select.kqueue", SwapBeforeRegistrationQueue)
    monkeypatch.setattr("category_compile.sqlite3.connect", observe_connect)
    compiler = None
    try:
        with pytest.raises(ValueError, match="database file identity changed"):
            compiler = CategoryCompiler(store)
    finally:
        if compiler is not None:
            compiler.close()
        restore_original()

    assert swapped
    assert restored
    assert opened_connections == []


def test_symlinked_wal_database_supports_two_concurrent_compile_threads(tmp_path):
    database_path = tmp_path / "threaded.db"
    symlink_path = tmp_path / "threaded-link.db"
    os.symlink(database_path, symlink_path)
    category_store = EvolvingCategoryStore(sqlite3.connect(symlink_path))
    try:
        category_store.connection.execute("PRAGMA journal_mode = WAL")
        _root(category_store, CellDraft("seed", 0, "committed seed"))
        compiler = CategoryCompiler(category_store)
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def concurrent_seeds():
            barrier.wait(timeout=5)
            yield "seed"

        def run_compile():
            try:
                results.append(
                    compiler.compile("root", None, concurrent_seeds(), 0)
                )
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run_compile) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert sorted(tuple(cell.id for cell in result.cells) for result in results) == [
            ("seed",),
            ("seed",),
        ]
        assert compiler.connection is category_store.connection
        compiler.close()
    finally:
        category_store.close()


def test_connection_pool_acquisition_obeys_compile_deadline(store):
    _root(store, CellDraft("seed", 0, "seed"))
    compiler = CategoryCompiler(store, CompileBudget(wall_time_ms=100))
    all_leases_held = threading.Event()
    release_leases = threading.Event()
    entered = 0
    entered_lock = threading.Lock()
    worker_results = []

    def holding_seeds():
        nonlocal entered
        yield "seed"
        with entered_lock:
            entered += 1
            if entered == 4:
                all_leases_held.set()
        assert release_leases.wait(5)

    def hold_connection():
        worker_results.append(
            compiler.compile("root", None, holding_seeds(), 0)
        )

    workers = [threading.Thread(target=hold_connection) for _ in range(4)]
    for worker in workers:
        worker.start()
    assert all_leases_held.wait(5)

    timed_out = compiler.compile("root", None, ("seed",), 0)

    assert timed_out.cells == ()
    assert timed_out.truncated
    release_leases.set()
    for worker in workers:
        worker.join(5)
    assert all(not worker.is_alive() for worker in workers)
    assert len(worker_results) == 4
    compiler.close()


def test_empty_tuple_skips_oversized_snapshot_pool_lease_and_staging(
    store, monkeypatch
):
    _root(store, CellDraft("seed", 0, "seed"))
    compiler = CategoryCompiler(store)
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (json.dumps(["seed"]),),
    )
    store.connection.commit()
    monkeypatch.setattr(
        "category_compile._MAX_ACTIVE_SNAPSHOT_BYTES", 1, raising=False
    )
    calls = _observe_compile_boundary_calls(compiler, monkeypatch)
    try:
        result = compiler.compile("root", "context", (), 0)
    finally:
        compiler.close()

    assert result.epoch_id == "root"
    assert result.context_id == "context"
    assert result.cells == ()
    assert result.token_count == 0
    assert result.candidate_count == 0
    assert not result.truncated
    assert not result.rotation_required
    assert calls == []


def test_empty_generator_skips_malformed_snapshot_pool_lease_and_staging(
    store, monkeypatch
):
    _root(store, CellDraft("seed", 0, "seed"))
    compiler = CategoryCompiler(store)
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        ("not valid JSON",),
    )
    store.connection.commit()
    calls = _observe_compile_boundary_calls(compiler, monkeypatch)
    try:
        result = compiler.compile(
            "root", None, (cell_id for cell_id in ()), 0
        )
    finally:
        compiler.close()

    assert result.cells == ()
    assert result.token_count == 0
    assert result.candidate_count == 0
    assert not result.truncated
    assert not result.rotation_required
    assert calls == []


def test_empty_generator_ignores_closed_connection_pool(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    compiler = CategoryCompiler(store)
    compiler.close()
    calls = _observe_compile_boundary_calls(compiler, monkeypatch)

    result = compiler.compile("root", None, (cell_id for cell_id in ()), 0)

    assert result.cells == ()
    assert not result.truncated
    assert calls == []


def test_empty_tuple_does_not_wait_for_saturated_connection_pool(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    compiler = CategoryCompiler(store, CompileBudget(wall_time_ms=1))
    leases = [
        compiler._acquire_compile_connection(10**30)
        for _index in range(4)
    ]
    calls = _observe_compile_boundary_calls(compiler, monkeypatch)
    try:
        result = compiler.compile("root", None, (), 0)
    finally:
        for connection in leases:
            compiler._release_compile_connection(connection)
        compiler.close()

    assert result.cells == ()
    assert not result.truncated
    assert calls == []


def test_seed_peek_precedes_pool_lease_without_eagerly_consuming_tail(
    store, monkeypatch
):
    _root(
        store,
        CellDraft("first", 0, "first"),
        CellDraft("second", 0, "second"),
    )
    compiler = CategoryCompiler(store)
    events = []
    original_acquire = compiler._acquire_compile_connection

    def seeds():
        events.append("first")
        yield "first"
        events.append("tail")
        yield "second"

    def observe_acquire(deadline):
        events.append("lease")
        return original_acquire(deadline)

    monkeypatch.setattr(compiler, "_acquire_compile_connection", observe_acquire)
    try:
        result = compiler.compile("root", None, seeds(), 0)
    finally:
        compiler.close()

    assert events == ["first", "lease", "tail"]
    assert tuple(cell.id for cell in result.cells) == ("first", "second")


def test_in_memory_store_is_rejected_without_mutation():
    memory_store = EvolvingCategoryStore(sqlite3.connect(":memory:"))
    try:
        with pytest.raises(ValueError, match="file-backed"):
            CategoryCompiler(memory_store).compile("root", None, (), 0)
        assert not memory_store.connection.in_transaction
    finally:
        memory_store.close()


def test_temp_membership_preserves_caller_transaction(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('caller-pending', 'test', '{}', 'now')"
    )

    compiler = CategoryCompiler(store)
    result = compiler.compile("root", None, ("seed",), 0)

    assert result.cells[0].id == "seed"
    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-pending'"
    ).fetchone()[0] == "test"
    compiler.close()
    assert close_states == [((), False)] * 4
    store.connection.rollback()
    assert store.connection.execute(
        "SELECT 1 FROM cat_events WHERE id = 'caller-pending'"
    ).fetchone() is None


def test_temp_membership_does_not_leave_an_idle_connection_in_transaction(store):
    _root(store, CellDraft("seed", 0, "seed"))
    assert not store.connection.in_transaction

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert result.cells[0].id == "seed"
    assert not store.connection.in_transaction


def test_non_interrupt_sql_errors_propagate_and_temp_state_is_clean(
    store, monkeypatch
):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    store.connection.execute("DROP TABLE cat_snapshots")
    store.connection.commit()

    compiler = CategoryCompiler(store)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        compiler.compile("missing", None, ("seed",), 0)
    compiler.close()

    assert close_states == [((), False)] * 4
    assert not store.connection.in_transaction


def test_non_interrupt_embedding_schema_errors_propagate(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, wrong_column BLOB)"
    )
    store.connection.commit()
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('caller-error', 'test', '{}', 'now')"
    )

    compiler = CategoryCompiler(store)
    with pytest.raises(sqlite3.OperationalError, match="no column named|no such column"):
        compiler.compile("root", None, ("seed",), 0)

    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-error'"
    ).fetchone()[0] == "test"
    compiler.close()
    assert close_states == [((), False)] * 4
    store.connection.rollback()


def test_historical_translation_excludes_proposed_and_nonancestor_rewrites(store):
    store.create_cell(CellDraft("selected", 0, "selected"))
    store.create_cell(CellDraft("historical", 0, "historical"))
    engine = EvolutionEngine(store)
    engine.create_root_epoch("selected-root", ("selected",))
    engine.create_root_epoch("other-root", ("historical",))
    proposal = RewriteProposal(
        "other-rewrite",
        "retype",
        "locus",
        None,
        ("historical",),
        (CellDraft("other-output", 0, "other output"),),
        (),
        RewriteEvidence((), 0.8, 0.5, 0.2),
    )
    engine.propose(proposal)

    proposed = CategoryCompiler(store).compile(
        "selected-root", None, ("historical",), 0
    )
    assert proposed.cells == ()

    assert engine.commit(
        "other-rewrite", ("other-root",), epoch_id="other-current"
    ) == "other-current"
    nonancestor = CategoryCompiler(store).compile(
        "selected-root", None, ("historical",), 0
    )
    assert nonancestor.cells == ()


def test_deep_ancestry_is_iterative_bounded_and_marks_truncation(
    store, monkeypatch
):
    store.create_cell(CellDraft("cell-0", 0, "cell 0"))
    engine = EvolutionEngine(store)
    engine.create_root_epoch("epoch-0", ("cell-0",))
    parent = "epoch-0"
    for index in range(1, 9):
        rewrite_id = f"rewrite-{index}"
        engine.propose(
            RewriteProposal(
                rewrite_id,
                "retype",
                "locus",
                None,
                (f"cell-{index - 1}",),
                (CellDraft(f"cell-{index}", 0, f"cell {index}"),),
                (),
                RewriteEvidence((), 0.8, 0.5, 0.2),
            )
        )
        parent = engine.commit(
            rewrite_id, (parent,), epoch_id=f"epoch-{index}"
        )
        assert parent == f"epoch-{index}"
    traced_sql, _close_states = _observe_dedicated_connections(monkeypatch)
    result = CategoryCompiler(
        store, CompileBudget(max_candidates=4)
    ).compile("epoch-8", None, ("cell-0",), 0)

    assert result.cells == ()
    assert result.candidate_count <= 4
    assert result.truncated
    assert not any("WITH RECURSIVE ancestors" in sql for sql in traced_sql)

    empty = CategoryCompiler(
        store, CompileBudget(max_candidates=4)
    ).compile("epoch-8", None, (), 0)
    active = CategoryCompiler(
        store, CompileBudget(max_candidates=4)
    ).compile("epoch-8", None, ("cell-8",), 0)
    assert empty.cells == ()
    assert not empty.truncated
    assert tuple(cell.id for cell in active.cells) == ("cell-8",)
    assert not active.truncated


def test_multi_parent_ancestry_translates_both_inputs_once(store):
    store.create_cell(CellDraft("left", 0, "left"))
    store.create_cell(CellDraft("right", 0, "right"))
    engine = EvolutionEngine(store)
    engine.create_root_epoch("left-root", ("left",))
    engine.create_root_epoch("right-root", ("right",))
    engine.propose(
        RewriteProposal(
            "join",
            "merge",
            "locus",
            None,
            ("left", "right"),
            (CellDraft("joined", 0, "joined"),),
            (),
            RewriteEvidence((), 0.8, 0.5, 0.2),
        )
    )
    assert engine.commit(
        "join", ("left-root", "right-root"), epoch_id="joined-epoch"
    ) == "joined-epoch"

    result = CategoryCompiler(store).compile(
        "joined-epoch", None, ("right", "left"), 0
    )

    assert tuple(cell.id for cell in result.cells) == ("joined",)


def test_invalid_raw_seeds_do_not_consume_candidate_cap_before_useful_seed(store):
    _root(
        store,
        CellDraft("b-opaque", 3, "opaque"),
        CellDraft("c-malformed", 2, "path without boundaries"),
        CellDraft("d-oversized", 0, "x" * (2 * 1024 * 1024)),
        CellDraft("z-useful", 0, "useful"),
    )
    compiler = CategoryCompiler(store, CompileBudget(max_candidates=1))

    result = compiler.compile(
        "root",
        None,
        ("a-missing", "b-opaque", "c-malformed", "d-oversized", "z-useful"),
        0,
    )

    assert tuple(cell.id for cell in result.cells) == ("z-useful",)
    assert result.candidate_count == 1
    assert result.truncated


def test_opaque_rewrite_output_does_not_consume_cap_before_active_descendant(store):
    store.create_cell(CellDraft("historical", 0, "historical"))
    engine = EvolutionEngine(store)
    engine.create_root_epoch("historical-root", ("historical",))
    engine.propose(
        RewriteProposal(
            "filtered-output-rewrite",
            "split",
            "locus",
            None,
            ("historical",),
            (
                CellDraft("a-opaque-output", 3, "opaque output"),
                CellDraft("z-valid-output", 0, "valid output"),
            ),
            (),
            RewriteEvidence((), 0.8, 0.5, 0.2),
        )
    )
    assert engine.commit(
        "filtered-output-rewrite",
        ("historical-root",),
        epoch_id="filtered-output-epoch",
    ) == "filtered-output-epoch"

    result = CategoryCompiler(
        store, CompileBudget(max_candidates=2)
    ).compile("filtered-output-epoch", None, ("historical",), 0)

    assert tuple(cell.id for cell in result.cells) == ("z-valid-output",)
    assert result.candidate_count == 1
    assert not result.truncated


def test_oversized_content_is_not_retained_as_a_candidate(store):
    _root(store, CellDraft("huge", 0, "x" * (2 * 1024 * 1024)))

    result = CategoryCompiler(store).compile("root", None, ("huge",), 0)

    assert result.cells == ()
    assert result.candidate_count == 0
    assert result.truncated


def test_oversized_content_does_not_stop_valid_sibling(store):
    _root(
        store,
        CellDraft("a-huge", 0, "x" * (2 * 1024 * 1024)),
        CellDraft("b-valid", 0, "valid sibling"),
    )

    result = CategoryCompiler(store).compile(
        "root", None, ("a-huge", "b-valid"), 0
    )

    assert tuple(cell.id for cell in result.cells) == ("b-valid",)
    assert result.truncated


def test_lexically_first_oversized_embedding_keeps_valid_sibling_eligible(store):
    _root(
        store,
        CellDraft("a-oversized", 0, "oversized vector"),
        CellDraft("b-valid", 0, "valid vector"),
    )
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding BLOB)"
    )
    store.connection.executemany(
        "INSERT INTO cat_vectors VALUES (?, ?)",
        (
            ("a-oversized", b"x" * (64 * 1024 + 1)),
            ("b-valid", struct.pack("<2f", 1.0, 0.0)),
        ),
    )
    store.connection.commit()

    result = CategoryCompiler(store).compile(
        "root", None, ("a-oversized", "b-valid"), 0
    )

    assert tuple(cell.id for cell in result.cells) == ("a-oversized", "b-valid")
    assert result.candidate_count == 2
    assert result.truncated


@pytest.mark.parametrize(
    "embedding",
    [
        struct.pack("<3f", 1.0, float("nan"), 0.0),
        struct.pack("<4097f", *([1.0] * 4097)),
        b"malformed",
    ],
)
def test_invalid_embedding_falls_back_without_excluding_cell(store, embedding):
    _root(store, CellDraft("seed", 0, "seed words"))
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding BLOB)"
    )
    store.connection.execute(
        "INSERT INTO cat_vectors VALUES ('seed', ?)", (embedding,)
    )
    store.connection.commit()

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert tuple(cell.id for cell in result.cells) == ("seed",)
    assert result.candidate_count == 1
    assert result.truncated


@pytest.mark.parametrize(
    "embedding",
    [
        "[" + "9" * 400 + "]",
        "[" * 2_000 + "0" + "]" * 2_000,
    ],
)
def test_overflowing_or_deep_json_embedding_falls_back_to_words(store, embedding):
    _root(store, CellDraft("seed", 0, "word fallback"))
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding TEXT)"
    )
    store.connection.execute(
        "INSERT INTO cat_vectors VALUES ('seed', ?)", (embedding,)
    )
    store.connection.commit()

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert tuple(cell.id for cell in result.cells) == ("seed",)
    assert result.candidate_count == 1
    assert result.truncated


def test_cosine_mmr_uses_lambda_point_seven_five(store):
    drafts = (
        CellDraft("a", 0, "a"),
        CellDraft("b", 0, "b"),
        CellDraft("c", 0, "c"),
    )
    _root(store, *drafts)
    _observe(store, "a", relevance=1, evidence=1, recency=1,
             affect=1, adoption=1, novelty=1)
    _observe(store, "b", relevance=1, evidence=1, recency=1,
             affect=1, adoption=0, novelty=1)
    _observe(store, "c", relevance=1, evidence=1, novelty=7 / 15)
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding BLOB)"
    )
    store.connection.executemany(
        "INSERT INTO cat_vectors VALUES (?, ?)",
        (
            ("a", struct.pack("<2f", 1.0, 0.0)),
            ("b", struct.pack("<2f", 1.0, 0.0)),
            ("c", struct.pack("<2f", 0.0, 1.0)),
        ),
    )
    store.connection.commit()
    budget = CompileBudget(normal_target=2, rotation_watermark=3, hard_ceiling=3)

    result = CategoryCompiler(store, budget).compile("root", None, ("c", "b", "a"), 0)

    assert tuple(cell.id for cell in result.cells) == ("a", "c")


def test_cosine_is_stable_for_huge_finite_components(store):
    drafts = (
        CellDraft("a", 0, "alpha"),
        CellDraft("b", 0, "beta"),
        CellDraft("c", 0, "gamma"),
    )
    _root(store, *drafts)
    _observe(store, "a", relevance=1, evidence=1, recency=1,
             affect=1, adoption=1, novelty=1)
    _observe(store, "b", relevance=1, evidence=1, recency=1,
             affect=1, adoption=0, novelty=1)
    _observe(store, "c", relevance=1, evidence=1, novelty=7 / 15)
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding TEXT)"
    )
    store.connection.executemany(
        "INSERT INTO cat_vectors VALUES (?, ?)",
        (
            ("a", json.dumps([1e308, 0.0])),
            ("b", json.dumps([1e308, 0.0])),
            ("c", json.dumps([0.0, 1e308])),
        ),
    )
    store.connection.commit()
    budget = CompileBudget(normal_target=4, rotation_watermark=5, hard_ceiling=5)

    result = CategoryCompiler(store, budget).compile("root", None, ("a", "b", "c"), 0)

    assert tuple(cell.id for cell in result.cells[:2]) == ("a", "c")


def test_active_snapshot_byte_and_cardinality_bounds_truncate_safely(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))
    _traced_sql, close_states = _observe_dedicated_connections(monkeypatch)
    compiler = CategoryCompiler(store)
    monkeypatch.setattr("category_compile._MAX_ACTIVE_SNAPSHOT_BYTES", 32, raising=False)
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (json.dumps(["seed", "a-long-missing-id", "b-long-missing-id"]),),
    )
    store.connection.commit()

    too_many_bytes = compiler.compile("root", None, ("seed",), 0)
    assert too_many_bytes.cells == ()
    assert too_many_bytes.truncated

    monkeypatch.setattr("category_compile._MAX_ACTIVE_SNAPSHOT_BYTES", 1024, raising=False)
    monkeypatch.setattr("category_compile._MAX_ACTIVE_MEMBERS", 2, raising=False)
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (json.dumps(["seed", "missing-a", "missing-b"]),),
    )
    store.connection.commit()

    too_many_members = compiler.compile("root", None, ("seed",), 0)
    assert too_many_members.cells == ()
    assert too_many_members.truncated
    compiler.close()
    assert close_states == [((), False)] * 4


def test_equal_contribution_mappings_have_equal_hashes():
    first = CompiledCell("cell", "content", 0, 0.1, {"a": 1.0, "b": 2.0}, 0, 2)
    second = CompiledCell("cell", "content", 0, 0.1, {"b": 2.0, "a": 1.0}, 0, 2)

    assert first == second
    assert hash(first) == hash(second)


def test_wall_time_is_checked_before_translated_seed_admission(store, monkeypatch):
    store.create_cell(CellDraft("historical", 0, "historical"))
    engine = EvolutionEngine(store)
    engine.create_root_epoch("historical-root", ("historical",))
    engine.propose(
        RewriteProposal(
            "deadline-rewrite",
            "retype",
            "locus",
            None,
            ("historical",),
            (CellDraft("active", 0, "active"),),
            (),
            RewriteEvidence((), 0.8, 0.5, 0.2),
        )
    )
    engine.commit(
        "deadline-rewrite", ("historical-root",), epoch_id="deadline-epoch"
    )
    translation_finished = False
    original_translate = CategoryCompiler._translate_seeds

    def translate_then_expire(compiler, *args, **kwargs):
        nonlocal translation_finished
        translated = original_translate(compiler, *args, **kwargs)
        translation_finished = True
        return translated

    monkeypatch.setattr(CategoryCompiler, "_translate_seeds", translate_then_expire)
    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        lambda: 2_000_000 if translation_finished else 0,
    )

    result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
        "deadline-epoch", None, ("historical",), 0
    )

    assert translation_finished
    assert result.cells == ()
    assert result.candidate_count == 0
    assert result.truncated


def test_wall_time_is_checked_while_consuming_seed_iterable(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "seed"))

    class ExpiringSeeds:
        expired = False

        def __iter__(self):
            self.expired = True
            yield "seed"

    seeds = ExpiringSeeds()
    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        lambda: 2_000_000 if seeds.expired else 0,
    )

    result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
        "root", None, seeds, 0
    )

    assert result.cells == ()
    assert result.candidate_count == 0
    assert result.truncated


def test_wall_time_is_checked_during_word_tokenization(store, monkeypatch):
    _root(store, CellDraft("seed", 0, "word " * 10_000))
    entered_tokenization = False
    token_checks = 0
    original = CategoryCompiler._word_counts

    def observed_word_counts(self, content, deadline):
        nonlocal entered_tokenization
        entered_tokenization = True
        return original(self, content, deadline)

    monkeypatch.setattr(CategoryCompiler, "_word_counts", observed_word_counts)

    def clock():
        nonlocal token_checks
        if not entered_tokenization:
            return 0
        token_checks += 1
        return 2_000_000 if token_checks >= 2 else 0

    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        clock,
    )

    result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
        "root", None, ("seed",), 0
    )

    assert entered_tokenization
    assert token_checks >= 2
    assert result.cells == ()
    assert result.truncated
