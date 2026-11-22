"""North-star test 5, Measure 3, stage 2 (engram/experiments/northstar/PREREG-test5-measure3.md, approved at 64f8a41c).

Stage 1, `atlas/workbench/measure3_answers.py`, writes REL's answer for every T1 × P1 claim pair, and each record's
sources with their keys. This module reads that file and the sealed audit, `measure3-audit.json`. It computes the
baselines B1 to B3, the trivial arms U0, O1 and I1, the derived truth, the cost, both bootstraps, the most-shared
classes and the reading, exactly as the page fixes them. It never imports Atlas, so engram's tests stay clear of
`workbench` (the multihop bridge's rule)."""
from __future__ import annotations

import numpy as np

FM_WEIGHT, ABS_WEIGHT = 0.5, 0.25
BOOT_SEED, COMPONENT_SEED = 20261126, 20261127
REPLICATES = 10_000
ARMS = {"U0": "unknown", "O1": "overlapping", "I1": "independent"}
NOT_INDEPENDENT = {"same sources", "overlapping", "copied"}


# --- the baselines (B1 to B3, W1, VA2, VA3) ---------------------------------------------------------------------------

def match_b1(a, b):
    """Exact DOI: two sources match only on equal DOI keys."""
    return a["keys"]["doi"] is not None and a["keys"]["doi"] == b["keys"]["doi"]


def match_b2(a, b):
    """Exact DOI, or an equal url key where `strong_url` holds for both (VA3)."""
    return match_b1(a, b) or (a["strong_url"] and b["strong_url"] and a["keys"]["url"] == b["keys"]["url"])


def match_b3(a, b):
    """B2, or equal title and year (the title key holds both). No DOI-decides rule, and no unclear (VA2)."""
    return match_b2(a, b) or (a["keys"]["title"] is not None and a["keys"]["title"] == b["keys"]["title"])


def _shape(matrix, rows, cols):
    """same sources, overlapping or independent, in the truth's wording (W1): same sources when every source of each
    record matches one of the other's."""
    if all(any(matrix[i][j] for j in range(cols)) for i in range(rows)) and all(
            any(matrix[i][j] for i in range(rows)) for j in range(cols)):
        return "same sources"
    if any(matrix[i][j] for i in range(rows) for j in range(cols)):
        return "overlapping"
    return "independent"


def baseline_answer(t_sources, p_sources, match):
    if not t_sources or not p_sources:
        raise ValueError("Every record cites at least one source (V4)")
    return _shape([[match(a, b) for b in p_sources] for a in t_sources], len(t_sources), len(p_sources))


# --- the truth, from the sealed audit file (V4, V5, W4) --------------------------------------------------------------

def source_label(audit, t_id, p_id):
    """SAME, DIFFERENT or UNCLEAR for one cross source pair, from the two version classes and the audit's unclear
    pairs (same title and first author, or a shared trial registration)."""
    a, b = audit["identities"][f"T:{t_id}"]["class"], audit["identities"][f"P:{p_id}"]["class"]
    if a is None or b is None or [f"T:{t_id}", f"P:{p_id}"] in audit["unclear_pairs"]:
        return "UNCLEAR"
    return "SAME" if a == b else "DIFFERENT"


def claim_truth(audit, t_sources, p_sources):
    labels = [[source_label(audit, a["id"], b["id"]) for b in p_sources] for a in t_sources]
    same = [[label == "SAME" for label in row] for row in labels]
    if any(any(row) for row in same):
        return _shape(same, len(t_sources), len(p_sources))
    if any(label == "UNCLEAR" for row in labels for label in row):
        return "undecided"
    return "independent"


# --- the cost (V1, RG6) ---------------------------------------------------------------------------------------------

def pair_cost(answer, truth, *, fm=FM_WEIGHT, abstain=ABS_WEIGHT):
    """One decided pair's cost: 1 for a dangerous error, fm for a false merge, abstain for an unknown."""
    if truth == "undecided":
        return 0.0
    if answer == "unknown":
        return abstain
    if answer == "independent" and truth in NOT_INDEPENDENT:
        return 1.0
    if answer in NOT_INDEPENDENT and truth == "independent":
        return fm
    return 0.0


def cost(answers, truth, *, fm=FM_WEIGHT, abstain=ABS_WEIGHT):
    out = {"DE": 0, "FM": 0, "ABS": 0, "decided": 0}
    for pair, t in truth.items():
        if t == "undecided":
            continue
        out["decided"] += 1
        a = answers[pair]
        if a == "unknown":
            out["ABS"] += 1
        elif a == "independent" and t in NOT_INDEPENDENT:
            out["DE"] += 1
        elif a in NOT_INDEPENDENT and t == "independent":
            out["FM"] += 1
    out["cost"] = out["DE"] + fm * out["FM"] + abstain * out["ABS"]
    return out


# --- the bootstraps (V6, WA1, SW1) ------------------------------------------------------------------------------------

def record_bootstrap(diff, *, replicates=REPLICATES, seed=BOOT_SEED):
    """`diff[i, j]` is cost(B2) − cost(REL) for T record i and P record j, in sorted id order (0 where undecided). Each
    replicate draws T's records, then P's, with replacement to their own sizes. A pair counts the product of its
    records' draws, and the interval is numpy.quantile's 2.5% and 97.5%."""
    rng = np.random.default_rng(seed)
    n_t, n_p = diff.shape
    totals = np.empty(replicates)
    for r in range(replicates):
        k_t = np.bincount(rng.integers(0, n_t, n_t), minlength=n_t)
        k_p = np.bincount(rng.integers(0, n_p, n_p), minlength=n_p)
        totals[r] = k_t @ diff @ k_p
    return {"point": float(diff.sum()), "lower": float(np.quantile(totals, 0.025)),
            "upper": float(np.quantile(totals, 0.975)), "totals": totals.tolist()}


def components(cites):
    """Connected components of the graph whose nodes are both sides' records and the version classes they cite."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for record, classes in cites.items():
        find(record)
        for c in classes:
            parent[find(("class", c))] = find(record)
    groups = {}
    for record in cites:
        groups.setdefault(find(record), set()).add(record)
    return list(groups.values())


def component_bootstrap(diff, t_ids, p_ids, groups, *, replicates=REPLICATES, seed=COMPONENT_SEED):
    """The secondary when there are at least 10 components: components drawn with replacement to their count, a pair
    counted by the product of its two records' draws. None when there are fewer than 10."""
    if len(groups) < 10:
        return None
    rng = np.random.default_rng(seed)
    order = [sorted(g) for g in sorted(groups, key=lambda g: sorted(g))]
    where = {record: g for g, members in enumerate(order) for record in members}
    totals = np.empty(replicates)
    for r in range(replicates):
        k = np.bincount(rng.integers(0, len(order), len(order)), minlength=len(order))
        k_t = np.array([k[where[f"T:{t}"]] for t in t_ids])
        k_p = np.array([k[where[f"P:{p}"]] for p in p_ids])
        totals[r] = k_t @ diff @ k_p
    return {"lower": float(np.quantile(totals, 0.025)), "upper": float(np.quantile(totals, 0.975))}


def most_shared(counts, n=3):
    """The n version classes in the most decided pairs where they hold a SAME, ties to the lowest name (V7, SW1)."""
    return [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


# --- the reading (V8, W2, W6, WA3) ------------------------------------------------------------------------------------

def reading(*, shared_classes, not_independent, lower, rel_below_b2, drops, rel, u0, o1, i1, b3):
    """The page's reading, with too little overlap checked first."""
    if shared_classes < 3 or not_independent < 10:
        return "too little overlap to test"
    conditions = (rel_below_b2 and lower > 0, all(d > 0 for d in drops), rel < min(u0, o1, i1))
    if all(conditions):
        return ("the structure helps on real data" if rel < b3
                else "keys and titles help; the ordered rules aren't shown to")
    return "no measured gain (with a few hundred pairs, that may mean the run was too small to see one)"


def side_by_side(pairs, answers_by_method, truth):
    """Item 3's view: each pair, its truth and every method's answer, one line each."""
    return [" | ".join([t, p, f"truth {truth[(t, p)]}"] +
                       [f"{name} {answers[(t, p)]}" for name, answers in answers_by_method.items()])
            for t, p in pairs]


# --- the whole analysis -----------------------------------------------------------------------------------------------

def evaluate(stage1, audit, *, replicates=REPLICATES):
    """Every method's answers and costs, the record bootstrap, the three drops, the component secondary, the matrices,
    the break-even weight, item 3's side-by-side view, and the reading, from stage 1's file and the sealed audit."""
    rec = stage1["records"]
    t_ids, p_ids = sorted(rec["T"]), sorted(rec["P"])
    pairs = [(r["t"], r["p"]) for r in stage1["pairs"]]
    rel = {(r["t"], r["p"]): r["rel"] for r in stage1["pairs"]}
    truth = {(t, p): claim_truth(audit, rec["T"][t], rec["P"][p]) for t, p in pairs}
    answers = {"REL": rel}
    for name, match in (("B1", match_b1), ("B2", match_b2), ("B3", match_b3)):
        answers[name] = {(t, p): baseline_answer(rec["T"][t], rec["P"][p], match) for t, p in pairs}
    for name, answer in ARMS.items():
        answers[name] = {pair: answer for pair in pairs}
    costs = {name: cost(a, truth) for name, a in answers.items()}

    def gap(pair):
        return pair_cost(answers["B2"][pair], truth[pair]) - pair_cost(rel[pair], truth[pair])
    diff = np.array([[gap((t, p)) for p in p_ids] for t in t_ids], dtype=float)
    boot = record_bootstrap(diff, replicates=replicates)

    def cls(side, sid):
        return audit["identities"][f"{side}:{sid}"]["class"]
    counts = {}
    for t, p in pairs:
        if truth[(t, p)] == "undecided":
            continue
        held = {cls("T", a["id"]) for a in rec["T"][t] for b in rec["P"][p]
                if source_label(audit, a["id"], b["id"]) == "SAME"}
        for c in held:
            counts[c] = counts.get(c, 0) + 1
    top = most_shared(counts)
    drops = []
    for c in top:
        kept = [(t, p) for t, p in pairs if c not in {cls("T", s["id"]) for s in rec["T"][t]}
                and c not in {cls("P", s["id"]) for s in rec["P"][p]}]
        drops.append(float(sum(gap(q) for q in kept)))
    cites = {f"T:{t}": {cls("T", s["id"]) for s in rec["T"][t]} - {None} for t in t_ids}
    cites.update({f"P:{p}": {cls("P", s["id"]) for s in rec["P"][p]} - {None} for p in p_ids})
    component = component_bootstrap(diff, t_ids, p_ids, components(cites), replicates=replicates)
    not_independent = sum(1 for v in truth.values() if v in ("same sources", "overlapping"))
    c = {name: costs[name]["cost"] for name in costs}
    read = reading(shared_classes=len(counts), not_independent=not_independent, lower=boot["lower"],
                   rel_below_b2=c["REL"] < c["B2"], drops=drops if len(drops) == 3 else [0.0], rel=c["REL"],
                   u0=c["U0"], o1=c["O1"], i1=c["I1"], b3=c["B3"])
    matrices = {name: {} for name in answers}
    for name, a in answers.items():
        for pair in pairs:
            key = f"{a[pair]} / {truth[pair]}"
            matrices[name][key] = matrices[name].get(key, 0) + 1
    abs_rel = costs["REL"]["ABS"]
    break_even = None if abs_rel == 0 else (
        (costs["B2"]["DE"] + FM_WEIGHT * costs["B2"]["FM"] - costs["REL"]["DE"] - FM_WEIGHT * costs["REL"]["FM"]) / abs_rel)
    return {"costs": costs, "bootstrap": {k: boot[k] for k in ("point", "lower", "upper")}, "most_shared": top,
            "drops": drops, "component_bootstrap": component, "shared_classes": len(counts),
            "not_independent": not_independent, "undecided": sum(1 for v in truth.values() if v == "undecided"),
            "matrices": matrices, "break_even_abstention_weight": break_even, "reading": read,
            "side_by_side": side_by_side(pairs, {n: answers[n] for n in ("REL", "B1", "B2", "B3")}, truth)}
