from __future__ import annotations

import sqlite3

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
    budget = CompileBudget(normal_target=per_cell * 2, hard_ceiling=100)
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
        CompileBudget(normal_target=100_000, hard_ceiling=65_536),
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


def test_context_weights_and_output_order_are_stable_and_hashable(store):
    context_id = store.create_context({"task": "compiler"})
    _root(store, CellDraft("b", 0, "beta"), CellDraft("a", 0, "alpha"))
    _observe(store, "a", context_id=context_id, relevance=0.5, affect=-0.8)
    _observe(store, "b", context_id=context_id, relevance=0.5, affect=-0.8)

    result = CategoryCompiler(store).compile("root", context_id, ("b", "a"), 0)

    assert tuple(cell.id for cell in result.cells) == ("a", "b")
    assert result.cells[0].contributions["affect_salience"] == 0.08
    assert hash(result.cells[0]) == hash(result.cells[0])


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
