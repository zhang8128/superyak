"""Sheaves on a finite graph: the reference implementation of docs/standard/sheaf.md, version 1.

Pure mathematics. No store, no embedder, no network and no clock: the same input gives the same answer on any
machine. Every call has a byte or step budget and refuses (``SheafBudgetError``) rather than exceed it; nothing
here guesses. A rank decided by a tolerance reports the tolerance it used and the gap around it.

Vector sheaves: ``VectorSheaf``, ``coboundary``, ``cohomology``, ``glue``, ``transport``, ``holonomy``,
``neighbourhood``. Finite-set sheaves: ``SetSheaf``, ``glue_sets``, ``count_sections``. Files in the standard's
format: ``load``, ``check_file``, and the ``engram-sheaf check`` command.

This is the oracle a native core is compared against. It decides ranks by a dense singular value decomposition, so
it is for a neighbourhood of a query, not a whole store.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import scipy.sparse as sp

STANDARD = "superyak-sheaf/1"
DEFAULT_TOL = 1e-9
DEFAULT_GLUE_TOL = 1e-9
DEFAULT_BUDGET_BYTES = 256 << 20
DEFAULT_BUDGET_STEPS = 1_000_000
EXPECT_TOL = 1e-9
# eigh on the Laplacian squares the singular values, so it cannot honour a tolerance below this
LAPLACIAN_TOL_FLOOR = 1e-6

Route = tuple[tuple[int, int], ...]


class SheafError(ValueError):
    """The sheaf, the local data or the file is not well formed."""


class SheafBudgetError(SheafError):
    """The call would exceed its byte or step budget. Nothing was computed."""


# ---------------------------------------------------------------- the base

@dataclass(frozen=True)
class Base:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    faces: tuple[tuple[Route, Route], ...] = ()

    def __post_init__(self):
        if len(set(self.nodes)) != len(self.nodes):
            raise SheafError("node names must be unique")
        for name in self.nodes:
            if not isinstance(name, str) or not name:
                raise SheafError("a node name must be a non-empty string")
        known = set(self.nodes)
        for tail, head in self.edges:
            if tail not in known or head not in known:
                raise SheafError(f"edge ({tail!r}, {head!r}) names a node that is not in the base")
        for a, b in self.faces:
            if self.route_ends(a) != self.route_ends(b):
                raise SheafError("a face's two routes must share their start and their end")

    def route_ends(self, route: Route) -> tuple[str, str]:
        if not route:
            raise SheafError("a route needs at least one step")
        start = at = None
        for step in route:
            if len(step) != 2:
                raise SheafError("a step is [edge number, 1 or -1]")
            e, direction = step
            if isinstance(e, bool) or not isinstance(e, int) or not 0 <= e < len(self.edges):
                raise SheafError(f"a route names edge {e!r}, which is not in the base")
            if isinstance(direction, bool) or direction not in (1, -1):
                raise SheafError("a step's direction is 1 or -1")
            tail, head = self.edges[e]
            src, dst = (tail, head) if direction == 1 else (head, tail)
            if at is None:
                start = src
            elif src != at:
                raise SheafError("each step of a route must start where the last one ended")
            at = dst
        return start, at


def _matrix(value, rows: int, cols: int, what: str) -> np.ndarray:
    if isinstance(value, str):
        if value != "identity":
            raise SheafError(f"{what}: a map is a matrix or the string 'identity'")
        if rows != cols:
            raise SheafError(f"{what}: 'identity' needs equal dimensions, got {rows} and {cols}")
        return np.eye(rows)
    try:
        m = np.array(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SheafError(f"{what}: not a matrix of numbers") from exc
    if rows == 0 or cols == 0:
        m = m.reshape(rows, cols) if m.size == 0 else m
    if m.shape != (rows, cols):
        raise SheafError(f"{what}: expected {rows} rows and {cols} columns, got shape {m.shape}")
    if not np.all(np.isfinite(m)):
        raise SheafError(f"{what}: every number must be finite")
    return m


# ---------------------------------------------------------------- vector sheaves

@dataclass(frozen=True)
class VectorSheaf:
    base: Base
    node_dim: Mapping[str, int]
    edge_dim: tuple[int, ...]
    tail_maps: tuple[np.ndarray, ...]
    head_maps: tuple[np.ndarray, ...]

    def __post_init__(self):
        b = self.base
        if set(self.node_dim) != set(b.nodes):
            raise SheafError("node_dim must give a dimension for every node and nothing else")
        for name, n in self.node_dim.items():
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise SheafError(f"node {name!r}: a dimension is a whole number, 0 or more")
        if not (len(self.edge_dim) == len(self.tail_maps) == len(self.head_maps) == len(b.edges)):
            raise SheafError("edge_dim, tail_maps and head_maps must each have one entry per edge")
        tails, heads = [], []
        for e, (tail, head) in enumerate(b.edges):
            m = self.edge_dim[e]
            if isinstance(m, bool) or not isinstance(m, int) or m < 0:
                raise SheafError(f"edge {e}: a dimension is a whole number, 0 or more")
            tails.append(_matrix(self.tail_maps[e], m, self.node_dim[tail], f"edge {e} tail_map"))
            heads.append(_matrix(self.head_maps[e], m, self.node_dim[head], f"edge {e} head_map"))
        for m in tails + heads:
            m.setflags(write=False)
        object.__setattr__(self, "tail_maps", tuple(tails))
        object.__setattr__(self, "head_maps", tuple(heads))
        object.__setattr__(self, "edge_dim", tuple(self.edge_dim))
        object.__setattr__(self, "node_dim", dict(self.node_dim))

    @property
    def dim_c0(self) -> int:
        return sum(self.node_dim[v] for v in self.base.nodes)

    @property
    def dim_c1(self) -> int:
        return sum(self.edge_dim)

    def offsets(self) -> dict[str, int]:
        out, at = {}, 0
        for v in self.base.nodes:
            out[v] = at
            at += self.node_dim[v]
        return out


def _stored_entries(F: VectorSheaf) -> int:
    return sum(F.edge_dim[e] * (F.node_dim[t] + F.node_dim[h]) for e, (t, h) in enumerate(F.base.edges))


def coboundary(F: VectorSheaf, *, budget_bytes: int = DEFAULT_BUDGET_BYTES) -> sp.csr_matrix:
    """δ: one block row per edge, the head map minus the tail map. Sparse, never dense."""
    if 12 * _stored_entries(F) > budget_bytes:
        raise SheafBudgetError(f"the coboundary needs about {12 * _stored_entries(F)} bytes; "
                               f"the budget is {budget_bytes}. Take a neighbourhood.")
    off = F.offsets()
    rows, cols, vals = [], [], []
    row = 0
    for e, (tail, head) in enumerate(F.base.edges):
        m = F.edge_dim[e]
        for mat, node, sign in ((F.head_maps[e], head, 1.0), (F.tail_maps[e], tail, -1.0)):
            r, c = np.nonzero(mat)
            rows.append(r + row)
            cols.append(c + off[node])
            vals.append(sign * mat[r, c])
        row += m
    if rows:
        rows, cols, vals = np.concatenate(rows), np.concatenate(cols), np.concatenate(vals)
    # duplicates sum, which is what a loop (tail == head) needs
    return sp.coo_matrix((vals, (rows, cols)), shape=(F.dim_c1, F.dim_c0)).tocsr()


@dataclass(frozen=True)
class Cohomology:
    dim_c0: int
    dim_c1: int
    dim_h0: int
    dim_h1: int
    h0_basis: np.ndarray = field(repr=False)     # dim_c0 x dim_h0, orthonormal columns
    tol: float = DEFAULT_TOL                       # the tolerance asked for
    tol_used: float = DEFAULT_TOL                  # the tolerance the rank was decided at
    method: str = "svd"
    sigma_max: float = 0.0
    kept_min: float | None = None                  # smallest singular value kept, over sigma_max
    dropped_max: float | None = None               # largest singular value dropped, over sigma_max


def cohomology(F: VectorSheaf, *, tol: float = DEFAULT_TOL,
               budget_bytes: int = DEFAULT_BUDGET_BYTES) -> Cohomology:
    """dim H0 and dim H1 of the graph, and an orthonormal basis of H0 (the global sections)."""
    if not (isinstance(tol, (int, float)) and math.isfinite(tol) and 0 <= tol < 1):
        raise SheafError("tol must be a number from 0 up to, not including, 1")
    n0, n1 = F.dim_c0, F.dim_c1
    if n0 == 0 or n1 == 0:
        return Cohomology(n0, n1, n0, n1, np.eye(n0), tol, tol, "trivial")
    svd_bytes = 8 * (3 * n0 * n1 + 2 * n0 * n0)
    eigh_bytes = 8 * 4 * n0 * n0
    if svd_bytes <= budget_bytes:
        delta = coboundary(F, budget_bytes=budget_bytes).toarray()
        _, s, vh = np.linalg.svd(delta, full_matrices=True)
        sigma = np.zeros(n0)
        sigma[:len(s)] = s
        basis_rows, used, method = vh, tol, "svd"
    elif eigh_bytes <= budget_bytes:
        delta = coboundary(F, budget_bytes=budget_bytes)
        lam, vec = np.linalg.eigh((delta.T @ delta).toarray())
        order = np.argsort(-lam)
        sigma = np.sqrt(np.clip(lam[order], 0.0, None))
        basis_rows, used, method = vec[:, order].T, max(tol, LAPLACIAN_TOL_FLOOR), "laplacian"
    else:
        raise SheafBudgetError(f"deciding the rank of a {n1} by {n0} coboundary needs about "
                               f"{min(svd_bytes, eigh_bytes)} bytes; the budget is {budget_bytes}. "
                               "Take a neighbourhood.")
    top = float(sigma[0])
    keep = sigma > used * top if top > 0 else np.zeros(n0, dtype=bool)
    rank = int(np.count_nonzero(keep))
    # singular values come sorted, so the kept ones are exactly the first `rank`
    basis = np.ascontiguousarray(basis_rows[rank:].T)
    kept_min = float(sigma[rank - 1] / top) if rank else None
    dropped_max = float(sigma[rank] / top) if rank < n0 and top > 0 else (0.0 if rank < n0 else None)
    return Cohomology(n0, n1, n0 - rank, n1 - rank, basis, tol, used, method, top, kept_min, dropped_max)


def _local_vector(F: VectorSheaf, local: Mapping[str, Sequence[float]]) -> np.ndarray:
    if set(local) != set(F.base.nodes):
        raise SheafError("local data must give a vector for every node and nothing else")
    parts = []
    for v in F.base.nodes:
        try:
            x = np.array(local[v], dtype=np.float64).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise SheafError(f"local data at {v!r} is not a list of numbers") from exc
        if x.shape != (F.node_dim[v],):
            raise SheafError(f"local data at {v!r} has {x.size} numbers; its stalk has {F.node_dim[v]}")
        if not np.all(np.isfinite(x)):
            raise SheafError(f"local data at {v!r}: every number must be finite")
        parts.append(x)
    return np.concatenate(parts) if parts else np.zeros(0)


@dataclass(frozen=True)
class Glued:
    glued: bool
    residuals: tuple[float, ...]                   # one length per edge
    residual_edges: tuple[int, ...]                # edges whose residual is longer than glue_tol
    nearest: Mapping[str, np.ndarray] = field(repr=False)
    distance_squared: float = 0.0
    glue_tol: float = DEFAULT_GLUE_TOL
    cohomology: Cohomology | None = field(default=None, repr=False)


def glue(F: VectorSheaf, local: Mapping[str, Sequence[float]], *, tol: float = DEFAULT_TOL,
         glue_tol: float = DEFAULT_GLUE_TOL, budget_bytes: int = DEFAULT_BUDGET_BYTES) -> Glued:
    """Whether local data glues, each edge's residual, and the nearest global section."""
    if not (isinstance(glue_tol, (int, float)) and math.isfinite(glue_tol) and glue_tol >= 0):
        raise SheafError("glue_tol must be a finite number, 0 or more")
    x = _local_vector(F, local)
    r = coboundary(F, budget_bytes=budget_bytes) @ x
    lengths, at = [], 0
    for m in F.edge_dim:
        lengths.append(float(np.linalg.norm(r[at:at + m])))
        at += m
    bad = tuple(e for e, length in enumerate(lengths) if length > glue_tol)
    H = cohomology(F, tol=tol, budget_bytes=budget_bytes)
    y = H.h0_basis @ (H.h0_basis.T @ x)
    off = F.offsets()
    nearest = {v: y[off[v]:off[v] + F.node_dim[v]].copy() for v in F.base.nodes}
    return Glued(not bad, tuple(lengths), bad, nearest, float(np.dot(x - y, x - y)), glue_tol, H)


def transport(F: VectorSheaf, route: Route) -> np.ndarray:
    """Carry a vector along a route: the product of each step's pinv(far map) @ near map, first step rightmost."""
    start, _ = F.base.route_ends(route)
    T = np.eye(F.node_dim[start])
    for e, direction in route:
        near, far = (F.tail_maps[e], F.head_maps[e]) if direction == 1 else (F.head_maps[e], F.tail_maps[e])
        T = (np.linalg.pinv(far) @ near) @ T
    return T


def holonomy(F: VectorSheaf, face: int | tuple[Route, Route]) -> np.ndarray:
    """Transport along a face's first route minus transport along its second. Zero when the routes agree."""
    if isinstance(face, int):
        if not 0 <= face < len(F.base.faces):
            raise SheafError(f"face {face} is not in the base")
        a, b = F.base.faces[face]
    else:
        a, b = face
        if F.base.route_ends(a) != F.base.route_ends(b):
            raise SheafError("a face's two routes must share their start and their end")
    return transport(F, a) - transport(F, b)


def neighbourhood(F: VectorSheaf, centre: str, radius: int) -> VectorSheaf:
    """The sheaf on the nodes within `radius` steps of `centre` (ignoring direction) and the edges among them.
    Faces are kept when every edge they use is kept."""
    if centre not in F.node_dim:
        raise SheafError(f"{centre!r} is not a node")
    if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
        raise SheafError("radius is a whole number, 0 or more")
    near: dict[str, list[str]] = {v: [] for v in F.base.nodes}
    for tail, head in F.base.edges:
        near[tail].append(head)
        near[head].append(tail)
    dist = {centre: 0}
    queue = deque([centre])
    while queue:
        v = queue.popleft()
        if dist[v] == radius:
            continue
        for w in near[v]:
            if w not in dist:
                dist[w] = dist[v] + 1
                queue.append(w)
    nodes = tuple(v for v in F.base.nodes if v in dist)
    kept = [e for e, (t, h) in enumerate(F.base.edges) if t in dist and h in dist]
    renumber = {e: i for i, e in enumerate(kept)}
    faces = tuple(tuple(tuple((renumber[e], d) for e, d in route) for route in face)
                  for face in F.base.faces if all(e in renumber for route in face for e, _ in route))
    base = Base(nodes, tuple(F.base.edges[e] for e in kept), faces)
    return VectorSheaf(base, {v: F.node_dim[v] for v in nodes}, tuple(F.edge_dim[e] for e in kept),
                       tuple(F.tail_maps[e] for e in kept), tuple(F.head_maps[e] for e in kept))


# ---------------------------------------------------------------- finite-set sheaves

@dataclass(frozen=True)
class SetSheaf:
    base: Base
    node_stalk: Mapping[str, tuple[str, ...]]
    edge_stalk: tuple[tuple[str, ...], ...]
    tail_maps: tuple[Mapping[str, str], ...]
    head_maps: tuple[Mapping[str, str], ...]

    def __post_init__(self):
        b = self.base
        if b.faces:
            raise SheafError("faces are for vector sheaves")
        if set(self.node_stalk) != set(b.nodes):
            raise SheafError("node_stalk must give a stalk for every node and nothing else")
        if not (len(self.edge_stalk) == len(self.tail_maps) == len(self.head_maps) == len(b.edges)):
            raise SheafError("edge_stalk, tail_maps and head_maps must each have one entry per edge")

        def stalk(value, what):
            items = tuple(value)
            if any(not isinstance(s, str) for s in items) or len(set(items)) != len(items):
                raise SheafError(f"{what}: a stalk is a list of distinct strings")
            return items

        nodes = {v: stalk(self.node_stalk[v], f"node {v!r}") for v in b.nodes}
        edges = tuple(stalk(s, f"edge {e}") for e, s in enumerate(self.edge_stalk))
        for e, (tail, head) in enumerate(b.edges):
            for fn, node, side in ((self.tail_maps[e], tail, "tail_map"), (self.head_maps[e], head, "head_map")):
                if not isinstance(fn, Mapping) or set(fn) != set(nodes[node]):
                    raise SheafError(f"edge {e} {side}: must map every element of {node!r}'s stalk and nothing else")
                if any(image not in edges[e] for image in fn.values()):
                    raise SheafError(f"edge {e} {side}: maps outside the edge's stalk")
        object.__setattr__(self, "node_stalk", nodes)
        object.__setattr__(self, "edge_stalk", edges)
        object.__setattr__(self, "tail_maps", tuple(dict(m) for m in self.tail_maps))
        object.__setattr__(self, "head_maps", tuple(dict(m) for m in self.head_maps))


@dataclass(frozen=True)
class GluedSets:
    glued: bool
    residual_edges: tuple[int, ...]


def glue_sets(F: SetSheaf, local: Mapping[str, str]) -> GluedSets:
    """Whether one chosen element per node agrees across every edge. Exact."""
    if set(local) != set(F.base.nodes):
        raise SheafError("local data must pick an element for every node and nothing else")
    for v, x in local.items():
        if x not in F.node_stalk[v]:
            raise SheafError(f"local data at {v!r} is not in its stalk")
    bad = tuple(e for e, (tail, head) in enumerate(F.base.edges)
                if F.tail_maps[e][local[tail]] != F.head_maps[e][local[head]])
    return GluedSets(not bad, bad)


def count_sections(F: SetSheaf, *, budget_steps: int = DEFAULT_BUDGET_STEPS) -> int:
    """The number of global sections, by backtracking. Exact, or it refuses: it never returns a guess."""
    nodes = F.base.nodes
    touching: dict[str, list[int]] = {v: [] for v in nodes}
    for e, (tail, head) in enumerate(F.base.edges):
        touching[tail].append(e)
        if head != tail:
            touching[head].append(e)
    # visit each connected piece in breadth-first order, so a choice is checked against its neighbours early
    order, seen = [], set()
    for root in nodes:
        if root in seen:
            continue
        seen.add(root)
        queue = deque([root])
        while queue:
            v = queue.popleft()
            order.append(v)
            for e in touching[v]:
                tail, head = F.base.edges[e]
                w = head if v == tail else tail
                if w not in seen:
                    seen.add(w)
                    queue.append(w)
    place = {v: i for i, v in enumerate(order)}
    # the edges each node must satisfy when it is chosen: those whose other end was chosen earlier, and its loops
    checks = [[e for e in touching[v]
               if place[F.base.edges[e][0]] <= place[v] and place[F.base.edges[e][1]] <= place[v]]
              for v in order]
    chosen: dict[str, str] = {}
    steps = 0
    total = 0
    depth = 0
    cursors = [0] * (len(order) + 1)
    if not order:
        return 1
    while depth >= 0:
        if depth == len(order):
            total += 1
            depth -= 1
            continue
        v = order[depth]
        stalk = F.node_stalk[v]
        advanced = False
        while cursors[depth] < len(stalk):
            x = stalk[cursors[depth]]
            cursors[depth] += 1
            steps += 1 + len(checks[depth])
            if steps > budget_steps:
                raise SheafBudgetError(f"counting sections passed {budget_steps} steps. Take a smaller sheaf.")
            chosen[v] = x
            if all(F.tail_maps[e][chosen[F.base.edges[e][0]]] == F.head_maps[e][chosen[F.base.edges[e][1]]]
                   for e in checks[depth]):
                advanced = True
                break
        if advanced:
            depth += 1
            cursors[depth] = 0
        else:
            chosen.pop(v, None)
            depth -= 1
    return total


# ---------------------------------------------------------------- files in the standard's format

_COMMON = {"standard", "kind", "nodes", "edges", "local", "why", "expect"}
_KEYS = {"vector": _COMMON | {"faces", "tol", "glue_tol"}, "set": _COMMON}
_EXPECT = {"vector": {"dim_h0", "dim_h1", "glued", "residual_edges", "residuals", "distance_squared",
                      "holonomy_frobenius"},
           "set": {"glued", "residual_edges", "sections"}}


def _only(obj, allowed: set[str], what: str) -> dict:
    if not isinstance(obj, dict):
        raise SheafError(f"{what} must be an object")
    extra = set(obj) - allowed
    if extra:
        raise SheafError(f"{what} has fields the standard does not define: {sorted(extra)}")
    return obj


def _need(obj: dict, key: str, what: str):
    if key not in obj:
        raise SheafError(f"{what} needs {key!r}")
    return obj[key]


def load(doc) -> tuple[VectorSheaf | SetSheaf, dict]:
    """Read a sheaf from a decoded JSON document. Returns it with the document's other fields."""
    if not isinstance(doc, dict):
        raise SheafError("a sheaf file is one JSON object")
    if doc.get("standard") != STANDARD:
        raise SheafError(f"'standard' must be {STANDARD!r}")
    kind = doc.get("kind")
    if kind not in _KEYS:
        raise SheafError("'kind' must be 'vector' or 'set'")
    _only(doc, _KEYS[kind], "the file")
    node_docs, edge_docs = _need(doc, "nodes", "the file"), _need(doc, "edges", "the file")
    if not isinstance(node_docs, list) or not isinstance(edge_docs, list):
        raise SheafError("'nodes' and 'edges' are lists")
    size_key = "dim" if kind == "vector" else "stalk"
    names, sizes = [], {}
    for i, nd in enumerate(node_docs):
        nd = _only(nd, {"id", size_key}, f"node {i}")
        name = _need(nd, "id", f"node {i}")
        if not isinstance(name, str) or name in sizes:
            raise SheafError(f"node {i}: 'id' must be a string no other node uses")
        names.append(name)
        sizes[name] = _need(nd, size_key, f"node {i}")
    pairs, esizes, tmaps, hmaps = [], [], [], []
    for e, ed in enumerate(edge_docs):
        ed = _only(ed, {"tail", "head", size_key, "tail_map", "head_map"}, f"edge {e}")
        tail, head = _need(ed, "tail", f"edge {e}"), _need(ed, "head", f"edge {e}")
        if not isinstance(tail, str) or not isinstance(head, str):
            raise SheafError(f"edge {e}: 'tail' and 'head' are node names")
        pairs.append((tail, head))
        esizes.append(_need(ed, size_key, f"edge {e}"))
        tmaps.append(_need(ed, "tail_map", f"edge {e}"))
        hmaps.append(_need(ed, "head_map", f"edge {e}"))
    faces = []
    for i, fd in enumerate(doc.get("faces", []) if isinstance(doc.get("faces", []), list) else [None]):
        fd = _only(fd, {"a", "b"}, f"face {i}")
        routes = []
        for key in ("a", "b"):
            route = _need(fd, key, f"face {i}")
            if not isinstance(route, list) or any(not isinstance(s, list) for s in route):
                raise SheafError(f"face {i}: a route is a list of [edge number, 1 or -1]")
            routes.append(tuple(tuple(s) for s in route))
        faces.append(tuple(routes))
    base = Base(tuple(names), tuple(pairs), tuple(faces))
    if kind == "vector":
        sheaf = VectorSheaf(base, sizes, tuple(esizes), tuple(tmaps), tuple(hmaps))
    else:
        for value in list(sizes.values()) + esizes:
            if not isinstance(value, list):
                raise SheafError("a stalk is a list of strings")
        sheaf = SetSheaf(base, sizes, tuple(esizes), tuple(tmaps), tuple(hmaps))
    if "expect" in doc:
        _only(doc["expect"], _EXPECT[kind], "'expect'")
    if "local" in doc and not isinstance(doc["local"], dict):
        raise SheafError("'local' is an object from node names to data")
    return sheaf, {k: doc[k] for k in ("local", "tol", "glue_tol", "expect") if k in doc}


def answers(doc, *, budget_bytes: int = DEFAULT_BUDGET_BYTES,
            budget_steps: int = DEFAULT_BUDGET_STEPS) -> dict:
    """Everything the standard defines for one document, as plain JSON values."""
    sheaf, rest = load(doc)
    out: dict = {}
    if isinstance(sheaf, VectorSheaf):
        tol, glue_tol = rest.get("tol", DEFAULT_TOL), rest.get("glue_tol", DEFAULT_GLUE_TOL)
        H = cohomology(sheaf, tol=tol, budget_bytes=budget_bytes)
        out.update(dim_h0=H.dim_h0, dim_h1=H.dim_h1, tol_used=H.tol_used, method=H.method,
                   kept_min=H.kept_min, dropped_max=H.dropped_max)
        if "local" in rest:
            g = glue(sheaf, rest["local"], tol=tol, glue_tol=glue_tol, budget_bytes=budget_bytes)
            out.update(glued=g.glued, residual_edges=list(g.residual_edges), residuals=list(g.residuals),
                       distance_squared=g.distance_squared)
        if sheaf.base.faces:
            out["holonomy_frobenius"] = [float(np.linalg.norm(holonomy(sheaf, i)))
                                         for i in range(len(sheaf.base.faces))]
    else:
        out["sections"] = count_sections(sheaf, budget_steps=budget_steps)
        if "local" in rest:
            g = glue_sets(sheaf, rest["local"])
            out.update(glued=g.glued, residual_edges=list(g.residual_edges))
    return out


def _same(got, want) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return got is want
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return abs(got - want) <= EXPECT_TOL
    if isinstance(want, list) and isinstance(got, list):
        return len(got) == len(want) and all(_same(g, w) for g, w in zip(got, want))
    return False


def check_file(path, **budgets) -> dict:
    """Compute a file's answers and compare them with its 'expect'. Never raises for a bad file: it reports."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        got = answers(doc, **budgets)
    except SheafBudgetError as exc:
        return {"file": str(path), "status": "refused", "reason": str(exc)}
    except (SheafError, OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        return {"file": str(path), "status": "invalid", "reason": str(exc)}
    expect = doc.get("expect", {})
    missing = sorted(k for k in expect if k not in got)
    wrong = {k: {"expected": expect[k], "got": got[k]} for k in expect if k in got and not _same(got[k], expect[k])}
    if missing:
        status = "mismatch"
    else:
        status = "mismatch" if wrong else ("ok" if expect else "computed")
    report = {"file": str(path), "status": status, "answers": got}
    if wrong:
        report["wrong"] = wrong
    if missing:
        report["not_computed"] = missing
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engram-sheaf",
                                     description="Check sheaf files against docs/standard/sheaf.md.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="compute each file's answers and compare them with its 'expect'")
    check.add_argument("files", nargs="+")
    check.add_argument("--json", action="store_true", help="print one JSON report per line")
    check.add_argument("--budget-bytes", type=int, default=DEFAULT_BUDGET_BYTES)
    check.add_argument("--budget-steps", type=int, default=DEFAULT_BUDGET_STEPS)
    args = parser.parse_args(argv)
    worst = 0
    for path in args.files:
        report = check_file(path, budget_bytes=args.budget_bytes, budget_steps=args.budget_steps)
        status = report["status"]
        worst = max(worst, {"ok": 0, "computed": 0, "mismatch": 1}.get(status, 2))
        if args.json:
            print(json.dumps(report, sort_keys=True))
            continue
        line = f"{status:9} {path}"
        if status in ("refused", "invalid"):
            line += f": {report['reason']}"
        elif status == "mismatch":
            parts = [f"{k} expected {v['expected']} got {v['got']}" for k, v in report.get("wrong", {}).items()]
            parts += [f"{k} not computed" for k in report.get("not_computed", [])]
            line += ": " + "; ".join(parts)
        print(line)
    return worst


if __name__ == "__main__":
    sys.exit(main())
