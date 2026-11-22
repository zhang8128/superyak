"""North-star test 5, Measure 3, stage 2 (engram/experiments/northstar/PREREG-test5-measure3.md, approved at 64f8a41c):
the baselines, the trivial arms, the truth from the audit file, the cost, the bootstraps and the reading, on stage 1's
answers. No `workbench` import here (the multihop bridge's rule)."""
from __future__ import annotations

import numpy as np
import pytest

from experiments.northstar import measure3 as m


def src(sid, doi=None, url=None, title="t", year=2020, strong=True):
    url = url or f"https://example.org/{sid}"
    return {"id": sid, "title": title, "year": year, "url": url, "strong_url": strong,
            "keys": {"doi": f"doi:{doi}" if doi else None, "url": f"url:{url}", "title": f"title:{title}:{year}"}}


# --- the baselines and the arms (W1, W2, VA2, VA3) ------------------------------------------------------------------

def test_baselines_use_the_truths_wording_for_same_sources():
    """W1: {a1, a2} against {b1, b2}, with a1~b1 and a2~b2, is same sources, as the truth and REL's rule 3 say."""
    t = [src("a1", doi="10.1/x"), src("a2", doi="10.1/y")]
    p = [src("b1", doi="10.1/x"), src("b2", doi="10.1/y")]
    assert m.baseline_answer(t, p, m.match_b1) == "same sources"
    assert m.baseline_answer(t, [src("b1", doi="10.1/x"), src("b3", doi="10.1/z")], m.match_b1) == "overlapping"
    assert m.baseline_answer(t, [src("b3", doi="10.1/z")], m.match_b1) == "independent"
    # a smaller record against a larger one: every source of the smaller matches, but not the other way round
    assert m.baseline_answer([src("a1", doi="10.1/x")], [src("b1", doi="10.1/x"), src("b9", doi="10.1/q")],
                             m.match_b1) == "overlapping"


def test_b2_matches_urls_only_when_strong_and_b3_adds_title_and_year():
    a, b = src("a", url="https://site.org/paper"), src("b", url="https://site.org/paper")
    assert not m.match_b1(a, b) and m.match_b2(a, b)
    weak_a, weak_b = src("a", url="https://site.org", strong=False), src("b", url="https://site.org", strong=False)
    assert not m.match_b2(weak_a, weak_b)
    same_title = src("c", title="RECOVERY", year=2021), src("d", title="RECOVERY", year=2021)
    assert not m.match_b2(*same_title) and m.match_b3(*same_title)
    assert not m.match_b3(src("e", title="RECOVERY", year=2020), src("f", title="RECOVERY", year=2021))


def test_a_record_with_no_sources_is_refused():
    with pytest.raises(ValueError):
        m.baseline_answer([], [src("b")], m.match_b1)


def test_the_trivial_arms():
    assert (m.ARMS["U0"], m.ARMS["O1"], m.ARMS["I1"]) == ("unknown", "overlapping", "independent")


# --- the truth from the audit file (V4, V5, W4) ----------------------------------------------------------------------

def audit(classes, unclear=()):
    return {"format": "measure3-audit", "version": 1,
            "identities": {k: {"class": v, "evidence": "test"} for k, v in classes.items()},
            "unclear_pairs": [list(p) for p in unclear]}


def test_source_labels_are_derived_from_classes():
    a = audit({"T:a": "doi:10.1/x", "P:b": "doi:10.1/x", "P:c": "doi:10.1/y", "P:d": None, "T:e": "doi:10.1/z",
               "P:f": "doi:10.1/w"}, unclear=[("T:e", "P:f")])
    assert m.source_label(a, "a", "b") == "SAME"
    assert m.source_label(a, "a", "c") == "DIFFERENT"
    assert m.source_label(a, "a", "d") == "UNCLEAR"
    assert m.source_label(a, "e", "f") == "UNCLEAR"


def test_claim_truth_follows_the_page():
    a = audit({"T:a1": "doi:x", "T:a2": "doi:y", "P:b1": "doi:x", "P:b2": "doi:y", "P:b3": "doi:z", "P:b4": None})
    t = [src("a1"), src("a2")]
    assert m.claim_truth(a, t, [src("b1"), src("b2")]) == "same sources"
    assert m.claim_truth(a, t, [src("b1"), src("b3")]) == "overlapping"
    assert m.claim_truth(a, t, [src("b3")]) == "independent"
    assert m.claim_truth(a, t, [src("b3"), src("b4")]) == "undecided"      # no SAME, one UNCLEAR
    assert m.claim_truth(a, t, [src("b1"), src("b4")]) == "overlapping"    # any SAME decides it


# --- the cost (V1, RG6) ---------------------------------------------------------------------------------------------

def test_the_cost_counts_dangerous_errors_false_merges_and_abstentions():
    truth = {("t1", "p1"): "overlapping", ("t1", "p2"): "independent", ("t2", "p1"): "independent",
             ("t2", "p2"): "undecided"}
    answers = {("t1", "p1"): "independent", ("t1", "p2"): "overlapping", ("t2", "p1"): "unknown",
               ("t2", "p2"): "independent"}
    got = m.cost(answers, truth)
    assert (got["DE"], got["FM"], got["ABS"]) == (1, 1, 1)
    assert got["cost"] == pytest.approx(1 + 0.5 + 0.25)


def test_o1_would_win_without_the_false_merge_cost():
    """The reviewer's V1: with no FM term, always-overlapping costs 0."""
    truth = {("t", f"p{i}"): ("overlapping" if i < 2 else "independent") for i in range(10)}
    o1 = {pair: "overlapping" for pair in truth}
    assert m.cost(o1, truth, fm=0.0)["cost"] == 0
    assert m.cost(o1, truth)["cost"] == pytest.approx(0.5 * 8)


# --- the bootstraps and the most-shared classes (V6, V7, SW1) --------------------------------------------------------

def test_the_record_bootstrap_counts_pairs_by_the_product_of_draws_and_is_seeded():
    diff = np.array([[1.0, 0.0], [0.0, 2.0]])
    one = m.record_bootstrap(diff, replicates=200)
    assert one == m.record_bootstrap(diff, replicates=200)          # seed 20261126, deterministic
    rng = np.random.default_rng(m.BOOT_SEED)
    kt = np.bincount(rng.integers(0, 2, 2), minlength=2)
    kp = np.bincount(rng.integers(0, 2, 2), minlength=2)
    assert m.record_bootstrap(diff, replicates=1)["totals"][0] == pytest.approx(kt @ diff @ kp)


def test_the_three_most_shared_classes_by_decided_same_pairs_with_ties_to_the_lowest_name():
    shared = {"doi:10.1/b": 5, "doi:10.1/a": 5, "pmid:7": 9, "doi:10.1/c": 1}
    assert m.most_shared(shared) == ["pmid:7", "doi:10.1/a", "doi:10.1/b"]


def test_components_join_records_through_the_classes_they_cite():
    cites = {"T:t1": {"doi:x"}, "P:p1": {"doi:x"}, "T:t2": {"doi:y"}, "P:p2": {"doi:z"}}
    groups = m.components(cites)
    assert sorted(sorted(g) for g in groups) == [["P:p1", "T:t1"], ["P:p2"], ["T:t2"]]


# --- the reading (V8, W2, W6, WA3) ------------------------------------------------------------------------------------

def reading(**kw):
    base = dict(shared_classes=5, not_independent=20, lower=0.5, rel_below_b2=True, drops=[1, 1, 1],
                rel=1.0, u0=9.0, o1=9.0, i1=9.0, b3=2.0)
    base.update(kw)
    return m.reading(**base)


def test_too_little_overlap_is_checked_first():
    assert reading(shared_classes=2).startswith("too little overlap")
    assert reading(not_independent=9, lower=-1).startswith("too little overlap")


def test_helps_needs_all_four_and_keys_and_titles_replaces_it_when_b3_ties():
    assert reading() == "the structure helps on real data"
    assert reading(b3=1.0) == "keys and titles help; the ordered rules aren't shown to"
    assert reading(lower=0.0).startswith("no measured gain")
    assert reading(drops=[1, 0, 1]).startswith("no measured gain")
    assert reading(i1=0.5).startswith("no measured gain")


def test_side_by_side_names_every_methods_answer_and_the_truth():
    rows = m.side_by_side([("t1", "p1")], {"REL": {("t1", "p1"): "unknown"}, "B2": {("t1", "p1"): "independent"}},
                          {("t1", "p1"): "overlapping"})
    assert rows == ["t1 | p1 | truth overlapping | REL unknown | B2 independent"]


# --- evaluate(): the whole analysis from stage 1's file and the audit file -------------------------------------------

def stage1(t_records, p_records, rel):
    pairs = [{"t": t, "p": p, "rel": rel[(t, p)], "reason": None if rel[(t, p)] != "unknown" else "unclear sources",
              "link": None} for t in sorted(t_records) for p in sorted(p_records)]
    return {"format": "measure3-answers", "version": 1, "records": {"T": t_records, "P": p_records}, "pairs": pairs}


def test_evaluate_runs_every_method_and_reads_too_little_overlap_on_a_small_case():
    t = {"T1": [src("a", doi="10.1/x")], "T2": [src("b", doi="10.1/y")]}
    p = {"P1": [src("c", doi="10.1/x")], "P2": [src("d", doi="10.1/z")]}
    rel = {("T1", "P1"): "same sources", ("T1", "P2"): "independent", ("T2", "P1"): "independent",
           ("T2", "P2"): "independent"}
    a = audit({"T:a": "doi:10.1/x", "T:b": "doi:10.1/y", "P:c": "doi:10.1/x", "P:d": "doi:10.1/z"})
    out = m.evaluate(stage1(t, p, rel), a, replicates=50)
    assert set(out["costs"]) == {"REL", "B1", "B2", "B3", "U0", "O1", "I1"}
    assert out["costs"]["REL"]["cost"] == 0 and out["costs"]["U0"]["cost"] == pytest.approx(0.25 * 4)
    assert out["costs"]["I1"]["cost"] == 1 and out["costs"]["O1"]["cost"] == pytest.approx(0.5 * 3)
    assert out["shared_classes"] == 1 and out["reading"] == "too little overlap to test"
    assert out["side_by_side"][0].startswith("T1 | P1 | truth same sources | REL same sources")


def test_evaluate_drops_each_of_the_three_most_shared_classes_in_turn():
    t = {f"T{i}": [src(f"t{i}", doi=f"10.1/{i % 4}")] for i in range(12)}
    p = {f"P{i}": [src(f"p{i}", doi=f"10.1/{i % 4}")] for i in range(12)}
    classes = {**{f"T:t{i}": f"doi:10.1/{i % 4}" for i in range(12)}, **{f"P:p{i}": f"doi:10.1/{i % 4}" for i in range(12)}}
    rel = {(a, b): ("same sources" if int(a[1:]) % 4 == int(b[1:]) % 4 else "independent") for a in t for b in p}
    out = m.evaluate(stage1(t, p, rel), audit(classes), replicates=50)
    assert out["shared_classes"] == 4 and len(out["drops"]) == 3
    assert out["most_shared"] == ["doi:10.1/0", "doi:10.1/1", "doi:10.1/2"]
    assert out["reading"] in ("the structure helps on real data", "keys and titles help; the ordered rules aren't shown to",
                              "no measured gain (with a few hundred pairs, that may mean the run was too small to see one)")
