"""The receiver's rule for north-star test 5 (Tardis's half, goal T1): how two sourced Claims relate.

The spec is docs/superpowers/specs/2026-11-22-claim-crossing-design.md, revision 6 with amendment 1, "The answers, in
order". It lives beside sourced.py, not inside it, so the two halves' commits don't collide. The rule reads only the
artifacts the receiver holds: each claim's own Snapshot, and the Claims its `provenance` reaches. It never asks the
other store. Source comparison is sourced.compare_sources, never a second copy of it.

The answers are checked in order, and the first that holds wins:
1. copied: the same digest, one's digest in the other's chain, or a digest both chains share (siblings), resolved or
   not. It names the linking digest.
2. unknown: either has no roots, or an unresolved digest in its chain.
3. same sources: every root of each matches a root of the other.
4. overlapping: some root of one matches a root of the other.
5. independent: every pair of roots is distinct, never merely unclear.
6. unknown: anything else, which is some pair of roots unclear.

Only "unknown" carries a reason: "no roots", "unresolved digest" or "unclear sources". A claim's roots follow its
copies only. A derived record, one that cites or leans on another by an Atlas relation, adds nothing to them (the
spec's stated limit, C10)."""
from __future__ import annotations

from collections import deque

from .sourced import compare_sources


def held_claims(publications):
    """{digest value: (claim, snapshot)} for every Claim the receiver holds: each publication's own claims, with its
    snapshot, and the foreign Claims it carries, with theirs. Each publication is one validate_sourced accepted."""
    held = {}
    for package in publications:
        for claim in package["claims"]:
            held[claim["digest"]["value"]] = (claim, package["snapshot"])
        for entry in package["carried"]:
            held[entry["claim"]["digest"]["value"]] = (entry["claim"], entry["snapshot"])
    return held


def _own_roots(claim, snapshot):
    """The keys of the sources the claim's record cites in its own Snapshot, as (source id, keys) pairs."""
    model = snapshot["payload"]["model"]
    record_id = claim["payload"]["sentence"]["record_id"]
    [item] = [i for i in model["items"] if i["id"] == record_id]
    sources = {s["id"]: s["keys"] for s in model["sources"]}
    cited = dict.fromkeys(e["source_id"] for e in item.get("evidence", []))
    return [(snapshot["digest"]["value"], source_id, sources[source_id]) for source_id in cited]


def _reach(start, held):
    """Walk `provenance` from one held claim: (depth of every chain digest, whether any is unresolved, roots). The
    chain doesn't include the claim itself. A digest seen twice is walked once, so a loop ends."""
    depth, unresolved, roots = {}, False, []
    claim, snapshot = held[start]
    roots += _own_roots(claim, snapshot)
    queue = deque((ref["value"], 1) for ref in claim["payload"]["provenance"])
    while queue:
        value, d = queue.popleft()
        if value in depth or value == start:
            continue
        depth[value] = d
        if value not in held:
            unresolved = True
            continue
        claim, snapshot = held[value]
        roots += _own_roots(claim, snapshot)
        queue.extend((ref["value"], d + 1) for ref in claim["payload"]["provenance"])
    unique = {(snap, source_id): keys for snap, source_id, keys in roots}
    return depth, unresolved, list(unique.values())


def _ref(value):
    return {"algorithm": "sha-256", "value": value}


def _answer(answer, link=None, reason=None):
    return {"answer": answer, "link": None if link is None else _ref(link), "reason": reason}


def relation(a, b, held):
    """How Claim `a` relates to Claim `b`, both digest references the receiver holds (KeyError otherwise)."""
    a, b = a["value"], b["value"]
    if a not in held or b not in held:
        raise KeyError("relation compares claims the receiver holds")
    chain_a, unresolved_a, roots_a = _reach(a, held)
    chain_b, unresolved_b, roots_b = _reach(b, held)
    # 1. copied
    if a == b:
        return _answer("copied", a)
    if a in chain_b:
        return _answer("copied", a)
    if b in chain_a:
        return _answer("copied", b)
    shared = set(chain_a) & set(chain_b)
    if shared:
        return _answer("copied", min(shared, key=lambda v: (chain_a[v] + chain_b[v], v)))
    # 2. unknown, before any source is compared
    if not roots_a or not roots_b:
        return _answer("unknown", reason="no roots")
    if unresolved_a or unresolved_b:
        return _answer("unknown", reason="unresolved digest")
    results = [[compare_sources(x, y) for y in roots_b] for x in roots_a]
    # 3. same sources, and 4. overlapping
    if all("match" in row for row in results) and all(
            any(row[j] == "match" for row in results) for j in range(len(roots_b))):
        return _answer("same sources")
    if any("match" in row for row in results):
        return _answer("overlapping")
    # 5. independent: distinct, never merely unclear
    if all(r == "distinct" for row in results for r in row):
        return _answer("independent")
    # 6. unknown
    return _answer("unknown", reason="unclear sources")
