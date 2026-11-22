"""North-star test 6, the graded half: the property check of docs/superpowers/specs/2026-11-22-graded-blame-fixture-design.md
(revision 3, approved, `tardis/graded-blame-spec` 93e08797), section "Test 6's graded half". It checks an argument and
isn't a measurement.

**The argument:** `glue`'s nearest global section is the orthogonal projection onto H⁰ in raw stalk coordinates. So on
identity maps the sheaf's per-source residual is plain least squares (PL), and on unit maps, where a report is `x = k·u`,
it is least squares weighted by k².

Fixed before it runs (this commit):
- **The instances:** 500, the first 250 in condition A (identity maps) and the last 250 in U (units). Seeds come from
  `numpy.random.SeedSequence(20261123)`, keyed by instance.
- **Parameters,** each drawn uniformly per instance: K of 4, 5 and 6; M of 20 and 60; ρ of 0.5 and 0.9; b of 2, 4 and 8;
  s of 0.25 and 0.5. True values are uniform on (0, 1), and the noise σ is 0.05 (the spec leaves σ open; it's fixed here,
  before the run).
- **Reports:** each item is reported by each source with probability ρ, and an item with fewer than two reports is
  redrawn on its own. Then a source with fewer than five reports is added to items it doesn't report until it has five.
- **The bad source** adds b·σ, with one random sign, to ⌈s·n⌉ of its n items.
- **In U,** each source's unit is k of 1 or 1/1000. A report is `x = k·u + noise + bias`, its noise and bias in its own
  unit.
- **The sheaf:** each report is a node with a 1-dimensional stalk. Every pair of an item's reports is an edge, with map
  1/k from each report into an edge stalk in common units.
- **The comparison:**
  - S is each source's mean over its reports of `(x − nearest)²`;
  - PL is each source's mean of `k²·(x/k − u*)²`, where `u* = Σ k·x / Σ k²` per item (`k = 1` in A).
- **The tolerance** is 1e-9 times the largest PL score in the instance. Two sources whose PL scores differ by no more
  than it are a tie, for both methods; otherwise S must order them as PL does. Near-ties are counted and printed."""
from __future__ import annotations

import math

import numpy as np

import sheaf_core as sc

SEED, INSTANCES, SIGMA = 20261123, 500, 0.05


def instance(index):
    rng = np.random.default_rng(np.random.SeedSequence([SEED, index]))
    K, M = int(rng.choice([4, 5, 6])), int(rng.choice([20, 60]))
    rho, b, s = float(rng.choice([0.5, 0.9])), float(rng.choice([2, 4, 8])), float(rng.choice([0.25, 0.5]))
    units = index >= INSTANCES // 2
    sources = list(range(K))
    reports = []
    for _ in range(M):
        while True:
            who = [src for src in sources if rng.random() < rho]
            if len(who) >= 2:
                break
        reports.append(who)
    for src in sources:
        while sum(src in who for who in reports) < 5:
            reports[int(rng.choice([i for i, who in enumerate(reports) if src not in who]))].append(src)
    truth = rng.uniform(0, 1, M)
    k = {src: (float(rng.choice([1.0, 1e-3])) if units else 1.0) for src in sources}
    bad = int(rng.integers(K))
    bad_items = [i for i, who in enumerate(reports) if bad in who]
    biased = set(int(i) for i in rng.choice(bad_items, size=math.ceil(s * len(bad_items)), replace=False))
    sign = float(rng.choice([-1.0, 1.0]))
    x = {}
    for i, who in enumerate(reports):
        for src in who:
            x[(src, i)] = k[src] * truth[i] + rng.normal(0, SIGMA) + (sign * b * SIGMA if src == bad and i in biased else 0.0)
    return sources, reports, k, x


def sheaf_scores(sources, reports, k, x):
    nodes = [f"{src}@{i}" for (src, i) in x]
    edges, tails, heads = [], [], []
    for i, who in enumerate(reports):
        for a in range(len(who)):
            for c in range(a + 1, len(who)):
                edges.append((f"{who[a]}@{i}", f"{who[c]}@{i}"))
                tails.append(np.array([[1.0 / k[who[a]]]]))
                heads.append(np.array([[1.0 / k[who[c]]]]))
    F = sc.VectorSheaf(base=sc.Base(nodes=tuple(nodes), edges=tuple(edges)), node_dim={n: 1 for n in nodes},
                       edge_dim=tuple(1 for _ in edges), tail_maps=tuple(tails), head_maps=tuple(heads))
    glued = sc.glue(F, {f"{src}@{i}": [value] for (src, i), value in x.items()})
    per = {src: [] for src in sources}
    for (src, i), value in x.items():
        per[src].append((value - float(glued.nearest[f"{src}@{i}"][0])) ** 2)
    return {src: float(np.mean(v)) for src, v in per.items()}


def plain_scores(sources, reports, k, x):
    per = {src: [] for src in sources}
    for i, who in enumerate(reports):
        consensus = sum(k[src] * x[(src, i)] for src in who) / sum(k[src] ** 2 for src in who)
        for src in who:
            per[src].append(k[src] ** 2 * (x[(src, i)] / k[src] - consensus) ** 2)
    return {src: float(np.mean(v)) for src, v in per.items()}


def test_the_sheaf_is_least_squares_on_identity_and_unit_maps(capsys):
    worst, near_ties = 0.0, 0
    for index in range(INSTANCES):
        sources, reports, k, x = instance(index)
        S, PL = sheaf_scores(sources, reports, k, x), plain_scores(sources, reports, k, x)
        tol = 1e-9 * max(PL.values())
        for src in sources:
            assert abs(S[src] - PL[src]) <= tol, (index, src, S[src], PL[src])
            worst = max(worst, abs(S[src] - PL[src]) / max(PL.values()))
        for a in sources:
            for c in sources:
                if a < c:
                    if abs(PL[a] - PL[c]) <= tol:
                        near_ties += 1
                        assert abs(S[a] - S[c]) <= 2 * tol, (index, a, c)
                    else:
                        assert (S[a] < S[c]) == (PL[a] < PL[c]), (index, a, c)
    with capsys.disabled():
        print(f"\ntest 6 graded property: {INSTANCES} instances ({INSTANCES // 2} A, {INSTANCES // 2} U), seed {SEED}, "
              f"every score within tolerance; largest relative gap {worst:.1e}; near-ties {near_ties}")
