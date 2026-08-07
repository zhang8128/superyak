from __future__ import annotations

import sqlite3
import struct
import json

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
        ("wall_time_ms", 60_001),
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

    with pytest.raises(ValueError, match="base tokens"):
        CategoryCompiler(store).compile("root", None, ("a",), 65_537)
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
    large_active = json.dumps([f"missing-{index}" for index in range(20_000)])
    store.connection.execute(
        "UPDATE cat_snapshots SET active_cell_ids_json = ? WHERE epoch_id = 'root'",
        (large_active,),
    )
    persistent_before = tuple(
        store.connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        )
    )
    readings = iter((0, 0, 2_000_000))
    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        lambda: next(readings, 2_000_000),
    )

    result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
        "root", None, (), 0
    )

    assert result.cells == ()
    assert result.truncated
    assert store.connection.execute(
        "SELECT name FROM sqlite_temp_master "
        "WHERE name LIKE 'category_compile_active_%'"
    ).fetchall() == []
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


def test_temp_membership_preserves_caller_transaction(store):
    _root(store, CellDraft("seed", 0, "seed"))
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('caller-pending', 'test', '{}', 'now')"
    )

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert result.cells[0].id == "seed"
    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-pending'"
    ).fetchone()[0] == "test"
    assert store.connection.execute(
        "SELECT name FROM sqlite_temp_master "
        "WHERE name LIKE 'category_compile_active_%'"
    ).fetchall() == []
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


def test_non_interrupt_sql_errors_propagate_and_temp_state_is_clean(store):
    store.connection.execute("DROP TABLE cat_snapshots")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        CategoryCompiler(store).compile("missing", None, (), 0)

    assert store.connection.execute(
        "SELECT name FROM sqlite_temp_master "
        "WHERE name LIKE 'category_compile_active_%'"
    ).fetchall() == []
    assert not store.connection.in_transaction


def test_non_interrupt_embedding_schema_errors_propagate(store):
    _root(store, CellDraft("seed", 0, "seed"))
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, wrong_column BLOB)"
    )
    store.connection.commit()
    store.connection.execute("BEGIN")
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('caller-error', 'test', '{}', 'now')"
    )

    with pytest.raises(sqlite3.OperationalError, match="no column named|no such column"):
        CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert store.connection.in_transaction
    assert store.connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-error'"
    ).fetchone()[0] == "test"
    assert store.connection.execute(
        "SELECT name FROM sqlite_temp_master "
        "WHERE name LIKE 'category_compile_active_%'"
    ).fetchall() == []
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


def test_deep_ancestry_is_iterative_bounded_and_marks_truncation(store):
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
    traced_sql = []
    store.connection.set_trace_callback(traced_sql.append)
    try:
        result = CategoryCompiler(
            store, CompileBudget(max_candidates=4)
        ).compile("epoch-8", None, ("cell-0",), 0)
    finally:
        store.connection.set_trace_callback(None)

    assert result.cells == ()
    assert result.candidate_count <= 4
    assert result.truncated
    assert not any("WITH RECURSIVE ancestors" in sql for sql in traced_sql)


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


def test_oversized_content_is_not_retained_as_a_candidate(store):
    _root(store, CellDraft("huge", 0, "x" * (2 * 1024 * 1024)))

    result = CategoryCompiler(store).compile("root", None, ("huge",), 0)

    assert result.cells == ()
    assert result.candidate_count == 0
    assert result.truncated


def test_oversized_embedding_is_not_retained_as_a_candidate(store):
    _root(store, CellDraft("seed", 0, "seed"))
    store.connection.execute("DROP TABLE IF EXISTS cat_vectors")
    store.connection.execute(
        "CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding BLOB)"
    )
    store.connection.execute(
        "INSERT INTO cat_vectors VALUES ('seed', ?)", (b"x" * (64 * 1024 + 1),)
    )

    result = CategoryCompiler(store).compile("root", None, ("seed",), 0)

    assert result.cells == ()
    assert result.candidate_count == 0
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
    budget = CompileBudget(normal_target=2, rotation_watermark=3, hard_ceiling=3)

    result = CategoryCompiler(store, budget).compile("root", None, ("c", "b", "a"), 0)

    assert tuple(cell.id for cell in result.cells) == ("a", "c")


def test_equal_contribution_mappings_have_equal_hashes():
    first = CompiledCell("cell", "content", 0, 0.1, {"a": 1.0, "b": 2.0}, 0, 2)
    second = CompiledCell("cell", "content", 0, 0.1, {"b": 2.0, "a": 1.0}, 0, 2)

    assert first == second
    assert hash(first) == hash(second)


def test_wall_time_is_checked_before_translated_seed_admission(store, monkeypatch):
    _root(store, CellDraft("a", 0, "alpha"), CellDraft("b", 0, "beta"))
    readings = iter((0, 0, 2_000_000))
    monkeypatch.setattr(
        "category_compile.time.monotonic_ns",
        lambda: next(readings, 2_000_000),
    )

    result = CategoryCompiler(store, CompileBudget(wall_time_ms=1)).compile(
        "root", None, ("a", "b"), 0
    )

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
