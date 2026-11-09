"""The sheaf core against docs/standard/sheaf.md: the hand-worked known answers, then laws on random sheaves."""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import sheaf_core as sc

ENGRAM = Path(__file__).resolve().parents[1]
KNOWN = sorted((ENGRAM.parent / "docs" / "standard" / "sheaf-known-answers").glob("*.json"))


# ---------------------------------------------------------------- the standard's known answers

def test_known_answers_are_present():
    assert len(KNOWN) >= 16
    assert {json.loads(p.read_text())["kind"] for p in KNOWN} == {"vector", "set"}


@pytest.mark.parametrize("path", KNOWN, ids=lambda p: p.stem)
def test_known_answer(path):
    report = sc.check_file(path)
    assert report["status"] == "ok", report
    expect = json.loads(path.read_text())["expect"]
    assert expect, "a known answer must claim something"
    assert set(expect) <= set(report["answers"])


def test_every_expect_field_is_exercised_by_some_known_answer():
    seen = {"vector": set(), "set": set()}
    for p in KNOWN:
        doc = json.loads(p.read_text())
        seen[doc["kind"]] |= set(doc["expect"])
    assert seen == sc._EXPECT


# ---------------------------------------------------------------- helpers

def random_graph(rng, n_nodes, n_edges, connected=True):
    nodes = tuple(f"v{i}" for i in range(n_nodes))
    edges = []
    if connected:
        for i in range(1, n_nodes):
            edges.append((nodes[int(rng.integers(0, i))], nodes[i]))
    while len(edges) < n_edges:
        a, b = rng.integers(0, n_nodes, size=2)
        edges.append((nodes[int(a)], nodes[int(b)]))
    return nodes, tuple(edges)


def random_sheaf(rng, n_nodes=5, n_edges=7, max_dim=3):
    nodes, edges = random_graph(rng, n_nodes, n_edges)
    node_dim = {v: int(rng.integers(0, max_dim + 1)) for v in nodes}
    edge_dim = tuple(int(rng.integers(0, max_dim + 1)) for _ in edges)
    tails = tuple(rng.standard_normal((m, node_dim[t])) for m, (t, _) in zip(edge_dim, edges))
    heads = tuple(rng.standard_normal((m, node_dim[h])) for m, (_, h) in zip(edge_dim, edges))
    return sc.VectorSheaf(sc.Base(nodes, edges), node_dim, edge_dim, tails, heads)


def constant_sheaf(nodes, edges, k, faces=()):
    eye = tuple("identity" for _ in edges)
    return sc.VectorSheaf(sc.Base(nodes, edges, faces), {v: k for v in nodes}, tuple(k for _ in edges), eye, eye)


def orthogonal(rng, k):
    q, r = np.linalg.qr(rng.standard_normal((k, k)))
    return q * np.sign(np.diag(r))


def flat_sheaf(rng, nodes, edges, k, faces=()):
    """Every map comes from one frame per node, so transport never depends on the route."""
    frame = {v: orthogonal(rng, k) for v in nodes}
    mix = [orthogonal(rng, k) for _ in edges]
    return sc.VectorSheaf(sc.Base(nodes, edges, faces), {v: k for v in nodes}, tuple(k for _ in edges),
                          tuple(g @ frame[t] for g, (t, _) in zip(mix, edges)),
                          tuple(g @ frame[h] for g, (_, h) in zip(mix, edges))), frame


# ---------------------------------------------------------------- laws of cohomology

@pytest.mark.parametrize("seed", range(40))
def test_euler_count_and_h0_basis_are_global_sections(seed):
    rng = np.random.default_rng(seed)
    F = random_sheaf(rng)
    H = sc.cohomology(F)
    assert (H.dim_c0, H.dim_c1) == (F.dim_c0, F.dim_c1)
    assert H.dim_h1 - H.dim_h0 == F.dim_c1 - F.dim_c0
    B = H.h0_basis
    assert B.shape == (F.dim_c0, H.dim_h0)
    assert np.allclose(B.T @ B, np.eye(H.dim_h0), atol=1e-10)
    assert np.allclose(sc.coboundary(F) @ B, 0, atol=1e-9)
    assert H.dim_h0 == F.dim_c0 - np.linalg.matrix_rank(sc.coboundary(F).toarray(), tol=1e-9) or F.dim_c1 == 0


@pytest.mark.parametrize("seed", range(20))
def test_constant_sheaf_counts_pieces_and_loops(seed):
    rng = np.random.default_rng(100 + seed)
    n_nodes, n_edges, k = int(rng.integers(2, 7)), int(rng.integers(1, 10)), int(rng.integers(1, 4))
    nodes, edges = random_graph(rng, n_nodes, n_edges, connected=False)
    parent = {v: v for v in nodes}

    def find(v):
        while parent[v] != v:
            v = parent[v]
        return v
    for a, b in edges:
        parent[find(a)] = find(b)
    pieces = len({find(v) for v in nodes})
    H = sc.cohomology(constant_sheaf(nodes, edges, k))
    assert H.dim_h0 == k * pieces
    assert H.dim_h1 == k * (len(edges) - len(nodes) + pieces)


@pytest.mark.parametrize("seed", range(20))
def test_reversing_an_edge_changes_nothing(seed):
    rng = np.random.default_rng(200 + seed)
    F = random_sheaf(rng)
    e = int(rng.integers(0, len(F.base.edges)))
    edges = list(F.base.edges)
    tails, heads = list(F.tail_maps), list(F.head_maps)
    edges[e] = (edges[e][1], edges[e][0])
    tails[e], heads[e] = heads[e], tails[e]
    G = sc.VectorSheaf(sc.Base(F.base.nodes, tuple(edges)), F.node_dim, F.edge_dim, tuple(tails), tuple(heads))
    a, b = sc.cohomology(F), sc.cohomology(G)
    assert (a.dim_h0, a.dim_h1) == (b.dim_h0, b.dim_h1)


@pytest.mark.parametrize("seed", range(20))
def test_a_change_of_basis_at_a_node_changes_no_dimension(seed):
    rng = np.random.default_rng(300 + seed)
    F = random_sheaf(rng, max_dim=3)
    v = F.base.nodes[int(rng.integers(0, len(F.base.nodes)))]
    P = rng.standard_normal((F.node_dim[v], F.node_dim[v])) + 3 * np.eye(F.node_dim[v])
    tails = tuple(m @ P if t == v else m for m, (t, _) in zip(F.tail_maps, F.base.edges))
    heads = tuple(m @ P if h == v else m for m, (_, h) in zip(F.head_maps, F.base.edges))
    G = sc.VectorSheaf(F.base, F.node_dim, F.edge_dim, tails, heads)
    a, b = sc.cohomology(F), sc.cohomology(G)
    assert (a.dim_h0, a.dim_h1) == (b.dim_h0, b.dim_h1)


def test_a_flat_sheaf_on_a_connected_graph_has_k_sections_whatever_the_frames():
    rng = np.random.default_rng(7)
    nodes, edges = random_graph(rng, 6, 9)
    F, frame = flat_sheaf(rng, nodes, edges, 3)
    H = sc.cohomology(F)
    assert (H.dim_h0, H.dim_h1) == (3, 3 * (9 - 6 + 1))


def test_a_loop_edge():
    base = sc.Base(("a",), (("a", "a"),))
    same = sc.VectorSheaf(base, {"a": 2}, (2,), ("identity",), ("identity",))
    assert (sc.cohomology(same).dim_h0, sc.cohomology(same).dim_h1) == (2, 2)
    doubled = sc.VectorSheaf(base, {"a": 2}, (2,), ("identity",), (2 * np.eye(2),))
    assert (sc.cohomology(doubled).dim_h0, sc.cohomology(doubled).dim_h1) == (0, 0)


def test_empty_and_zero_dimensional_cases():
    none = sc.VectorSheaf(sc.Base((), ()), {}, (), (), ())
    assert (sc.cohomology(none).dim_h0, sc.cohomology(none).dim_h1) == (0, 0)
    lone = sc.VectorSheaf(sc.Base(("a", "b"), ()), {"a": 2, "b": 1}, (), (), ())
    H = sc.cohomology(lone)
    assert (H.dim_h0, H.dim_h1, H.method) == (3, 0, "trivial")
    zero_edge = sc.VectorSheaf(sc.Base(("a", "b"), (("a", "b"),)), {"a": 2, "b": 2}, (0,), ([],), ([],))
    assert sc.cohomology(zero_edge).dim_h0 == 4
    zero_maps = sc.VectorSheaf(sc.Base(("a", "b"), (("a", "b"),)), {"a": 1, "b": 1}, (2,),
                               ([[0], [0]],), ([[0], [0]],))
    H = sc.cohomology(zero_maps)
    assert (H.dim_h0, H.dim_h1, H.sigma_max) == (2, 2, 0.0)


# ---------------------------------------------------------------- rounding is part of the answer

def test_the_tolerance_decides_a_near_degenerate_rank_and_the_gap_says_so():
    eps = 1e-12
    nodes, edges = ("a", "b", "c"), (("a", "b"), ("b", "c"), ("c", "a"))
    F = sc.VectorSheaf(sc.Base(nodes, edges), {v: 2 for v in nodes}, (2, 2, 2),
                       ("identity",) * 3, ("identity", "identity", (1 + eps) * np.eye(2)))
    loose = sc.cohomology(F)                      # default 1e-9: the tiny twist counts as zero
    assert (loose.dim_h0, loose.dim_h1) == (2, 2)
    assert 0 < loose.dropped_max < 1e-9 < loose.kept_min
    strict = sc.cohomology(F, tol=1e-15)
    assert (strict.dim_h0, strict.dim_h1) == (0, 0)
    assert strict.dropped_max is None and strict.kept_min < 1e-9
    assert (loose.tol_used, strict.tol_used) == (1e-9, 1e-15)


@pytest.mark.parametrize("bad", [-1e-9, 1.0, float("nan"), float("inf"), "x"])
def test_bad_tolerances_are_refused(bad):
    F = constant_sheaf(("a", "b"), (("a", "b"),), 1)
    with pytest.raises(sc.SheafError):
        sc.cohomology(F, tol=bad)


def test_the_laplacian_path_agrees_and_reports_its_coarser_tolerance():
    rng = np.random.default_rng(11)
    nodes, edges = random_graph(rng, 12, 60)
    F, _ = flat_sheaf(rng, nodes, edges, 4)
    n0, n1 = F.dim_c0, F.dim_c1
    budget = 8 * 4 * n0 * n0 + 1
    assert 8 * (3 * n0 * n1 + 2 * n0 * n0) > budget, "the test must force the Laplacian path"
    lap, svd = sc.cohomology(F, budget_bytes=budget), sc.cohomology(F)
    assert (lap.method, svd.method) == ("laplacian", "svd")
    assert (lap.dim_h0, lap.dim_h1) == (svd.dim_h0, svd.dim_h1) == (4, 4 * (60 - 12 + 1))
    assert lap.tol_used == sc.LAPLACIAN_TOL_FLOOR and lap.tol == sc.DEFAULT_TOL
    assert np.allclose(sc.coboundary(F) @ lap.h0_basis, 0, atol=1e-6)


def test_budgets_refuse_rather_than_guess():
    rng = np.random.default_rng(12)
    nodes, edges = random_graph(rng, 12, 60)
    F, _ = flat_sheaf(rng, nodes, edges, 4)
    with pytest.raises(sc.SheafBudgetError, match="neighbourhood"):
        sc.cohomology(F, budget_bytes=8 * 4 * F.dim_c0 ** 2 - 1)
    with pytest.raises(sc.SheafBudgetError):
        sc.coboundary(F, budget_bytes=100)
    with pytest.raises(sc.SheafBudgetError):
        sc.glue(F, {v: [0.0] * 4 for v in nodes}, budget_bytes=100)


# ---------------------------------------------------------------- gluing

@pytest.mark.parametrize("seed", range(20))
def test_the_nearest_section_is_a_section_and_nothing_is_nearer(seed):
    rng = np.random.default_rng(400 + seed)
    nodes, edges = random_graph(rng, 5, 6)
    F, _ = flat_sheaf(rng, nodes, edges, 2)
    local = {v: rng.standard_normal(2) for v in nodes}
    g = sc.glue(F, local)
    again = sc.glue(F, g.nearest)
    assert again.glued and again.distance_squared < 1e-18
    assert max(again.residuals) < 1e-9
    x = np.concatenate([local[v] for v in nodes])
    for _ in range(10):
        other = g.cohomology.h0_basis @ rng.standard_normal(g.cohomology.dim_h0)
        assert g.distance_squared <= float(np.dot(x - other, x - other)) + 1e-12
    assert len(g.residuals) == len(edges)
    assert g.residual_edges == tuple(e for e, r in enumerate(g.residuals) if r > g.glue_tol)
    assert g.glued == (not g.residual_edges)


def test_a_small_disagreement_is_a_matter_of_the_stated_tolerance():
    F = constant_sheaf(("a", "b"), (("a", "b"),), 2)
    local = {"a": [1.0, 0.0], "b": [1.0, 1e-3]}
    assert not sc.glue(F, local).glued
    assert sc.glue(F, local, glue_tol=1e-2).glued
    assert sc.glue(F, local).residuals == pytest.approx((1e-3,))
    # "at most glue_tol": a residual exactly at the tolerance still glues, zero included
    exact = {"a": [1.0, 0.0], "b": [1.0, 0.0]}
    assert sc.glue(F, exact, glue_tol=0).glued
    half = {"a": [0.0, 0.0], "b": [0.5, 0.0]}
    assert sc.glue(F, half, glue_tol=0.5).glued and not sc.glue(F, half, glue_tol=0.25).glued


def test_false_glue_is_not_reported_for_different_data():
    # the audit's false-glue pair: two orthogonal directions against their average
    F = constant_sheaf(("a", "b", "c"), (("a", "c"), ("b", "c")), 2)
    g = sc.glue(F, {"a": [1, 0], "b": [0, 1], "c": [2 ** -0.5, 2 ** -0.5]})
    assert not g.glued and g.residual_edges == (0, 1)


@pytest.mark.parametrize("local", [{"a": [1, 0]}, {"a": [1, 0], "b": [1]}, {"a": [1, 0], "b": [1, float("nan")]},
                                   {"a": [1, 0], "b": [1, 0], "z": [0, 0]}, {"a": [1, 0], "b": "xy"}])
def test_malformed_local_data_is_refused(local):
    F = constant_sheaf(("a", "b"), (("a", "b"),), 2)
    with pytest.raises(sc.SheafError):
        sc.glue(F, local)


# ---------------------------------------------------------------- routes

def test_transport_on_a_flat_sheaf_ignores_the_route_and_reverses_to_the_inverse():
    rng = np.random.default_rng(21)
    nodes = ("a", "b", "c", "d")
    edges = (("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "a"))
    faces = ((((0, 1), (1, 1)), ((2, 1),)), (((2, 1), (3, 1)), ((4, -1),)))
    F, frame = flat_sheaf(rng, nodes, edges, 3, faces)
    for i in range(2):
        assert np.allclose(sc.holonomy(F, i), 0, atol=1e-10)
    there = sc.transport(F, ((0, 1), (1, 1)))
    back = sc.transport(F, ((1, -1), (0, -1)))
    assert np.allclose(back @ there, np.eye(3), atol=1e-10)
    assert np.allclose(there, frame["c"].T @ frame["a"], atol=1e-10)


def test_a_twist_shows_up_as_holonomy_and_as_missing_sections():
    R = np.array([[0.0, -1.0], [1.0, 0.0]])
    nodes, edges = ("a", "b", "c"), (("a", "b"), ("b", "c"), ("a", "c"))
    face = (((0, 1), (1, 1)), ((2, 1),))
    F = sc.VectorSheaf(sc.Base(nodes, edges, (face,)), {v: 2 for v in nodes}, (2, 2, 2),
                       ("identity",) * 3, ("identity", "identity", R))
    assert np.allclose(sc.holonomy(F, 0), np.eye(2) - R.T)
    assert np.allclose(sc.holonomy(F, face), sc.holonomy(F, 0))
    assert sc.cohomology(F).dim_h0 == 0


@pytest.mark.parametrize("route", [(), ((0, 1), (2, 1)), ((9, 1),), ((0, 2),), ((0, True),), ((True, 1),),
                                   ((0, 1, 1),), ((-1, 1),)])
def test_bad_routes_are_refused(route):
    F = constant_sheaf(("a", "b", "c"), (("a", "b"), ("b", "c"), ("a", "c")), 1)
    with pytest.raises(sc.SheafError):
        sc.transport(F, route)


def test_a_face_must_share_both_ends():
    with pytest.raises(sc.SheafError, match="share"):
        sc.Base(("a", "b", "c"), (("a", "b"), ("b", "c")), ((((0, 1),), ((1, 1),)),))
    F = constant_sheaf(("a", "b", "c"), (("a", "b"), ("b", "c")), 1)
    with pytest.raises(sc.SheafError):
        sc.holonomy(F, 0)
    with pytest.raises(sc.SheafError, match="share"):
        sc.holonomy(F, (((0, 1),), ((1, 1),)))


# ---------------------------------------------------------------- neighbourhoods

def test_neighbourhood_keeps_what_is_near_and_renumbers_faces():
    nodes = ("a", "b", "c", "d", "e")
    edges = (("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "e"))
    face = (((0, 1), (1, 1)), ((2, 1),))
    far_face = (((3, 1), (4, 1)), ((3, 1), (4, 1)))
    F = constant_sheaf(nodes, edges, 2, (far_face, face))
    alone = sc.neighbourhood(F, "e", 0)
    assert (alone.base.nodes, alone.base.edges, alone.base.faces) == (("e",), (), ())
    near = sc.neighbourhood(F, "a", 1)
    assert near.base.nodes == ("a", "b", "c")
    assert near.base.edges == (("a", "b"), ("b", "c"), ("a", "c"))
    assert near.base.faces == (face,)
    from_d = sc.neighbourhood(F, "d", 1)
    assert from_d.base.nodes == ("c", "d", "e") and from_d.base.edges == (("c", "d"), ("d", "e"))
    assert from_d.base.faces == ((((0, 1), (1, 1)), ((0, 1), (1, 1))),)
    whole = sc.neighbourhood(F, "a", 10)
    assert (whole.base, whole.edge_dim) == (F.base, F.edge_dim)
    assert sc.cohomology(near).dim_h1 == 2
    for bad in ("zz", ):
        with pytest.raises(sc.SheafError):
            sc.neighbourhood(F, bad, 1)
    for bad in (-1, 1.5, True):
        with pytest.raises(sc.SheafError):
            sc.neighbourhood(F, "a", bad)


# ---------------------------------------------------------------- finite-set sheaves

def random_set_sheaf(rng, n_nodes=4, n_edges=5, connected=True):
    nodes, edges = random_graph(rng, n_nodes, n_edges, connected)
    node_stalk = {v: tuple(f"{v}{i}" for i in range(int(rng.integers(0, 4)))) for v in nodes}
    edge_stalk = tuple(tuple(f"e{i}" for i in range(int(rng.integers(1, 4)))) for _ in edges)
    tails = tuple({x: s[int(rng.integers(0, len(s)))] for x in node_stalk[t]} for s, (t, _) in zip(edge_stalk, edges))
    heads = tuple({x: s[int(rng.integers(0, len(s)))] for x in node_stalk[h]} for s, (_, h) in zip(edge_stalk, edges))
    return sc.SetSheaf(sc.Base(nodes, edges), node_stalk, edge_stalk, tails, heads)


@pytest.mark.parametrize("seed", range(60))
def test_counting_sections_matches_trying_every_assignment(seed):
    rng = np.random.default_rng(500 + seed)
    F = random_set_sheaf(rng, connected=bool(seed % 2))
    brute = 0
    for choice in itertools.product(*(F.node_stalk[v] for v in F.base.nodes)):
        brute += sc.glue_sets(F, dict(zip(F.base.nodes, choice))).glued
    assert sc.count_sections(F) == brute


def test_set_sheaf_edge_cases():
    assert sc.count_sections(sc.SetSheaf(sc.Base((), ()), {}, (), (), ())) == 1
    empty = sc.SetSheaf(sc.Base(("a", "b"), ()), {"a": (), "b": ("x",)}, (), (), ())
    assert sc.count_sections(empty) == 0
    two = sc.SetSheaf(sc.Base(("a", "b"), ()), {"a": ("x", "y"), "b": ("p", "q", "r")}, (), (), ())
    assert sc.count_sections(two) == 6
    loop = sc.SetSheaf(sc.Base(("a",), (("a", "a"),)), {"a": ("x", "y", "z")}, (("0", "1"),),
                       ({"x": "0", "y": "0", "z": "1"},), ({"x": "0", "y": "1", "z": "1"},))
    assert sc.count_sections(loop) == 2
    assert sc.glue_sets(loop, {"a": "y"}) == sc.GluedSets(False, (0,))


def test_counting_refuses_past_its_budget():
    bit = ("0", "1")
    nodes = tuple(f"n{i}" for i in range(18))
    free = sc.SetSheaf(sc.Base(nodes, ()), {v: bit for v in nodes}, (), (), ())
    with pytest.raises(sc.SheafBudgetError):
        sc.count_sections(free, budget_steps=1000)
    assert sc.count_sections(free, budget_steps=10_000_000) == 2 ** 18


@pytest.mark.parametrize("change", [
    lambda d: d["node_stalk"].update(a=("x", "x")),
    lambda d: d["node_stalk"].update(a=("x", 1)),
    lambda d: d["tail_maps"][0].pop("x"),
    lambda d: d["tail_maps"][0].update(x="nowhere"),
    lambda d: d["head_maps"][0].update(extra="0"),
    lambda d: d.update(edge_stalk=()),
])
def test_malformed_set_sheaves_are_refused(change):
    d = {"node_stalk": {"a": ("x", "y"), "b": ("p",)}, "edge_stalk": (("0", "1"),),
         "tail_maps": [{"x": "0", "y": "1"}], "head_maps": [{"p": "0"}]}
    sc.SetSheaf(sc.Base(("a", "b"), (("a", "b"),)), d["node_stalk"], d["edge_stalk"],
                tuple(d["tail_maps"]), tuple(d["head_maps"]))
    change(d)
    with pytest.raises(sc.SheafError):
        sc.SetSheaf(sc.Base(("a", "b"), (("a", "b"),)), d["node_stalk"], d["edge_stalk"],
                    tuple(d["tail_maps"]), tuple(d["head_maps"]))


def test_set_local_data_is_checked():
    F = sc.SetSheaf(sc.Base(("a",), ()), {"a": ("x",)}, (), (), ())
    for bad in ({}, {"a": "nope"}, {"a": "x", "b": "x"}):
        with pytest.raises(sc.SheafError):
            sc.glue_sets(F, bad)


# ---------------------------------------------------------------- malformed sheaves and files

def good_doc():
    return {"standard": sc.STANDARD, "kind": "vector",
            "nodes": [{"id": "a", "dim": 2}, {"id": "b", "dim": 2}],
            "edges": [{"tail": "a", "head": "b", "dim": 2, "tail_map": "identity", "head_map": [[1, 0], [0, 1]]}],
            "local": {"a": [1, 2], "b": [1, 2]}, "expect": {"dim_h0": 2, "dim_h1": 0, "glued": True}}


def test_a_good_document_loads_and_answers():
    out = sc.answers(good_doc())
    assert (out["dim_h0"], out["dim_h1"], out["glued"]) == (2, 0, True)


@pytest.mark.parametrize("change", [
    lambda d: d.update(standard="superyak-sheaf/2"),
    lambda d: d.pop("standard"),
    lambda d: d.update(kind="module"),
    lambda d: d.update(surprise=1),
    lambda d: d.pop("nodes"),
    lambda d: d.update(edges={}),
    lambda d: d["nodes"].append({"id": "a", "dim": 1}),
    lambda d: d["nodes"][0].update(dim=-1),
    lambda d: d["nodes"][0].update(dim=1.5),
    lambda d: d["nodes"][0].update(dim=True),
    lambda d: d["nodes"][0].update(id=""),
    lambda d: d["nodes"][0].update(colour="red"),
    lambda d: d["nodes"][0].pop("dim"),
    lambda d: d["edges"][0].update(head="nobody"),
    lambda d: d["edges"][0].update(dim=3),
    lambda d: d["edges"][0].update(tail_map="same"),
    lambda d: d["edges"][0].update(head_map=[[1, 0], [0, float("nan")]]),
    lambda d: d["edges"][0].update(head_map=[[1, 0], [0, float("inf")]]),
    lambda d: d["edges"][0].update(head_map=[[1, 0], [0]]),
    lambda d: d["edges"][0].update(head_map=[[1, "x"], [0, 1]]),
    lambda d: d["edges"][0].pop("tail_map"),
    lambda d: d.update(faces=[{"a": [[0, 1]], "b": [[0, -1]]}]),
    lambda d: d.update(faces=[{"a": [[0, 1]]}]),
    lambda d: d.update(faces="all"),
    lambda d: d.update(local=[1, 2]),
    lambda d: d.update(local={"a": [1, 2]}),
    lambda d: d.update(tol=2),
    lambda d: d.update(glue_tol=-1),
    lambda d: d["expect"].update(sections=1),
    lambda d: d.update(expect=[]),
])
def test_malformed_documents_are_refused(change):
    doc = good_doc()
    change(doc)
    with pytest.raises(sc.SheafError):
        sc.answers(doc)


@pytest.mark.parametrize("doc", [None, [], "sheaf", 3])
def test_a_document_must_be_an_object(doc):
    with pytest.raises(sc.SheafError):
        sc.load(doc)


def test_identity_needs_equal_dimensions_and_set_files_take_no_faces_or_tolerances():
    doc = good_doc()
    doc["nodes"][0]["dim"] = 3
    with pytest.raises(sc.SheafError, match="identity"):
        sc.answers(doc)
    set_doc = {"standard": sc.STANDARD, "kind": "set", "nodes": [{"id": "a", "stalk": ["x"]}], "edges": []}
    assert sc.answers(set_doc) == {"sections": 1}
    for extra in ({"faces": []}, {"tol": 1e-9}, {"expect": {"dim_h0": 1}}):
        with pytest.raises(sc.SheafError):
            sc.answers({**set_doc, **extra})
    with pytest.raises(sc.SheafError):
        sc.answers({**set_doc, "nodes": [{"id": "a", "stalk": "xy"}]})


def test_sheaf_data_cannot_be_changed_after_it_is_made():
    F = constant_sheaf(("a", "b"), (("a", "b"),), 2)
    with pytest.raises(ValueError):
        F.tail_maps[0][0, 0] = 5.0
    with pytest.raises(AttributeError):
        F.edge_dim = (3,)


# ---------------------------------------------------------------- the check command

def run_check(*args):
    return subprocess.run([sys.executable, str(ENGRAM / "sheaf_core.py"), "check", *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def test_check_passes_the_known_answers():
    done = run_check(*KNOWN)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("\n") == len(KNOWN) and all(line.startswith("ok") for line in done.stdout.splitlines())


def test_check_reports_mismatch_invalid_and_refused(tmp_path):
    wrong = good_doc()
    wrong["expect"]["dim_h0"] = 5
    (tmp_path / "wrong.json").write_text(json.dumps(wrong))
    (tmp_path / "broken.json").write_text("{not json")
    bare = good_doc()
    del bare["expect"]
    (tmp_path / "bare.json").write_text(json.dumps(bare))
    assert run_check(tmp_path / "wrong.json").returncode == 1
    assert "dim_h0 expected 5 got 2" in run_check(tmp_path / "wrong.json").stdout
    assert run_check(tmp_path / "broken.json").returncode == 2
    assert run_check(tmp_path / "missing.json").returncode == 2
    done = run_check(tmp_path / "bare.json")
    assert done.returncode == 0 and done.stdout.startswith("computed")
    assert run_check(KNOWN[0], tmp_path / "wrong.json", tmp_path / "broken.json").returncode == 2
    refused = run_check("--budget-bytes", "10", tmp_path / "bare.json")
    assert refused.returncode == 2 and refused.stdout.startswith("refused")
    report = json.loads(run_check("--json", tmp_path / "wrong.json").stdout)
    assert report["status"] == "mismatch" and report["wrong"]["dim_h0"] == {"expected": 5, "got": 2}


def test_an_expected_field_the_file_cannot_have_is_a_mismatch_not_a_pass(tmp_path):
    doc = good_doc()
    del doc["local"]
    (tmp_path / "no-local.json").write_text(json.dumps(doc))
    report = sc.check_file(tmp_path / "no-local.json")
    assert report["status"] == "mismatch" and report["not_computed"] == ["glued"]
