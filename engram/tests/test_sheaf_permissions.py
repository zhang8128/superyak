"""The permission check and the sheaf core give one answer (docs/standard/sheaf.md, section 3).

The standard says the permission check is a sheaf of sets: a stalk is a set of allowed uses, and restriction is
intersection. This file builds that sheaf at a joint place and holds the two pieces of code to it:

- the nodes are the joint's parents. Each one's stalk is every subset of a few sampled uses: some at the parent's own
  place, some at the joint;
- an edge joins each pair of parents. Its stalk is every subset of the sampled uses the joint's own layer allows,
  which is where the parents have to agree, and both maps intersect with that set;
- each parent's local data is what its chain of places allows, read by the brute-force oracle one use at a time.

`glue_sets` then says whether the parents agree, and on which pairs. `permissions.gluing` reaches its Δ(J) by box
algebra, without the sheaf core or the oracle. The two must name the same uses.
"""
from __future__ import annotations

import itertools
import random

import sheaf_core as sc
from permissions import box_contains, gluing
from tests.permissions_oracle import _glue_view, _layer_set, _sections_at
from tests.permissions_support import SEED, World, random_world
from tests.test_permissions_properties import _glue_points, _guided      # the samplers PT11 uses

AT_JOINT = 8        # sampled uses at the joint: a parent's stalk has 2 ** (AT_JOINT + AT_PARENT) elements
AT_PARENT = 2       # sampled uses at each parent's own place, which restriction forgets


def _name(indices) -> str:
    """A subset of the sampled uses, as the string the sheaf's stalks hold."""
    return ".".join(str(i) for i in sorted(indices))


def _members(name: str) -> frozenset:
    return frozenset(int(i) for i in name.split(".")) if name else frozenset()


def _subsets(indices):
    indices = sorted(indices)
    return [frozenset(c) for r in range(len(indices) + 1) for c in itertools.combinations(indices, r)]


def permission_sheaf(state, joint, at_joint, at_parent, *, restrict_to_own=True):
    """(the sheaf, each parent's local data, the sampled uses in index order).

    `at_joint` is a list of uses at the joint, `at_parent` maps each parent to uses at its own place. With
    `restrict_to_own` off the edges keep every use at the joint. That is the wrong sheaf, and the tests show it is
    told apart from the right one."""
    view = _glue_view(state.to_tables(), state.seq_at, state.seq)
    parents, chains = _sections_at(view, joint)
    points = list(at_joint)
    joint_ix = frozenset(range(len(points)))
    own_ix = frozenset(i for i in joint_ix if _layer_set(view, [joint], points[i])) if restrict_to_own else joint_ix
    node_ix = {}
    for q in parents:
        first = len(points)
        points.extend(at_parent.get(q, ()))
        node_ix[q] = joint_ix | frozenset(range(first, len(points)))
    edges = tuple(itertools.combinations(parents, 2))
    overlap = tuple(_name(s) for s in _subsets(own_ix))
    restrict = {q: {_name(s): _name(s & own_ix) for s in _subsets(node_ix[q])} for q in parents}
    sheaf = sc.SetSheaf(
        sc.Base(tuple(parents), edges),
        {q: tuple(restrict[q]) for q in parents},
        tuple(overlap for _ in edges),
        tuple(restrict[tail] for tail, _ in edges),
        tuple(restrict[head] for _, head in edges))
    local = {q: _name(i for i in node_ix[q] if _layer_set(view, chain, points[i]))
             for q, chain in zip(parents, chains)}
    return sheaf, local, points


def disagreements(sheaf, local, glued) -> frozenset:
    """The sampled uses some pair of parents disagrees on, read off the edges that did not glue."""
    out = set()
    for e in glued.residual_edges:
        tail, head = sheaf.base.edges[e]
        out |= _members(sheaf.tail_maps[e][local[tail]]) ^ _members(sheaf.head_maps[e][local[head]])
    return frozenset(out)


def _in_delta(report, points, indices) -> frozenset:
    return frozenset(i for i in indices if any(box_contains(b, points[i]) for b in report.delta))


def _pick(view, joint, chains, candidates, n):
    """Up to n of the candidates, one for each way the joint's own layer and the parents' chains can answer, with
    the uses the parents disagree on first. So a disagreement that was sampled at all reaches the sheaf."""
    seen = {}
    for p in candidates:
        got = tuple(_layer_set(view, chain, p) for chain in chains)
        seen.setdefault((_layer_set(view, [joint], p), got), p)
    order = sorted(seen, key=lambda sig: (all(sig[1]) or not any(sig[1]), not sig[0], sig[1]))
    return [seen[sig] for sig in order[:n]]


def test_the_permission_check_and_glue_sets_agree_on_random_place_dags():
    rng = random.Random(SEED + 2026_11_09)
    seen = {"joints": 0, "glued": 0, "disagree": 0, "forgotten": 0}
    for _ in range(60):
        w = random_world(rng)
        state = w.state()
        view = _glue_view(state.to_tables(), state.seq_at, state.seq)
        for joint in sorted(state.place_parents):
            parents, chains = _sections_at(view, joint)
            if len(parents) < 2:
                continue
            report = gluing(state, joint)
            if report.too_complex:
                continue
            base = _glue_points(rng, state, w, joint, 150)
            at_joint = _pick(view, joint, chains, base + _guided(rng, report.delta[:6], base, 3), AT_JOINT)
            at_parent = {q: _glue_points(rng, state, w, q, AT_PARENT) for q in parents}
            sheaf, local, points = permission_sheaf(state, joint, at_joint, at_parent)
            glued = sc.glue_sets(sheaf, local)
            want = _in_delta(report, points, range(len(at_joint)))
            assert disagreements(sheaf, local, glued) == want, (joint, sorted(want))
            assert glued.glued == (not want), joint
            seen["joints"] += 1
            seen["glued" if glued.glued else "disagree"] += 1
            # the parents disagree on a use the joint's own layer does not allow: the restriction forgets it
            every, every_local, _ = permission_sheaf(state, joint, at_joint, at_parent, restrict_to_own=False)
            seen["forgotten"] += disagreements(every, every_local, sc.glue_sets(every, every_local)) != want
    # both answers are reached often, and so is the case that tells the joint's own layer apart from every use there
    # (312 joints on 2026-11-09: 141 glued, 171 disagreed, 52 with a disagreement the restriction forgot)
    assert seen["glued"] >= 50 and seen["disagree"] >= 50 and seen["forgotten"] >= 20, seen


def _two_parents(own_allows: bool):
    """PT11's fixture: parents a and b under one steward, and the joint j. a allows m1, b allows m9, and j's own
    layer allows m1 when `own_allows`."""
    w = World()
    w.person("st")
    for p in ("place:a", "place:b"):
        w.place(p, stewards=["st"])
    w.place("place:j", parents=["place:a", "place:b"], stewards=["st"])
    w.agent("x", "place:j", at="place:j")
    m1, m9 = "mem:S/episode/m1", "mem:S/episode/m9"
    w.collect("collection:andy/c1", [m1])
    w.collect("collection:andy/c2", [m1])
    w.collect("collection:andy/c3", [m9])
    if own_allows:
        w.allow("place:j", audience=["commons"], collections=["collection:andy/c1"])
    w.allow("place:a", audience=["commons"], collections=["collection:andy/c2"])
    w.allow("place:b", audience=["commons"], collections=["collection:andy/c3"])
    at = w.start + 10
    use_m1 = ("place:j", "agent:x", "memory", "S", "episode", "none", m1, "recall", "any", at)
    use_m9 = use_m1[:6] + (m9,) + use_m1[7:]
    at_a = ("place:a",) + use_m1[1:]
    return w.state(), [use_m1, use_m9], {"place:a": [at_a], "place:b": []}


def test_a_known_disagreement_shows_on_its_edge_and_names_its_use():
    state, at_joint, at_parent = _two_parents(own_allows=True)
    sheaf, local, points = permission_sheaf(state, "place:j", at_joint, at_parent)
    # a's chain allows m1 at the joint and at a itself; b's allows m9. The joint's own layer allows only m1.
    assert local == {"place:a": "0.2", "place:b": "1"}
    assert sheaf.edge_stalk == (("", "0"),)
    assert sheaf.tail_maps[0]["0.2"] == "0" and sheaf.head_maps[0]["1"] == ""
    glued = sc.glue_sets(sheaf, local)
    assert glued == sc.GluedSets(False, (0,))
    assert disagreements(sheaf, local, glued) == {0}
    report = gluing(state, "place:j")
    assert _in_delta(report, points, range(2)) == {0}
    # without the joint's own layer in the restriction, m9 counts too, which the permission check does not say
    every, every_local, _ = permission_sheaf(state, "place:j", at_joint, at_parent, restrict_to_own=False)
    assert disagreements(every, every_local, sc.glue_sets(every, every_local)) == {0, 1}


def test_parents_that_disagree_only_outside_the_joints_own_rules_glue():
    state, at_joint, at_parent = _two_parents(own_allows=False)
    sheaf, local, points = permission_sheaf(state, "place:j", at_joint, at_parent)
    assert local == {"place:a": "0.2", "place:b": "1"}          # the parents are as far apart as before
    assert sheaf.edge_stalk == (("",),)                          # and the joint allows nothing to disagree on
    assert sc.glue_sets(sheaf, local) == sc.GluedSets(True, ())
    assert gluing(state, "place:j").delta == ()
