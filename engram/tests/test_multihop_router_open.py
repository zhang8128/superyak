"""Issue #12's open-setting router: the scoring, on hand-made rows."""
from experiments.multihop.hotpot_router_open import score


def open_row(qid, bm25, hop, gold=("A", "B"), present=2):
    return {"id": qid, "gold": list(gold), "gold_in_corpus": present, "bm25_both": bm25, "hop_both": hop}


def label(qid, kind, rule, model):
    return {"id": qid, "type": kind, "rule": rule, "model": model}


def test_each_router_takes_the_arm_its_label_names_and_uncovered_questions_are_left_out():
    open_rows = [open_row("b1", False, True), open_row("b2", True, False), open_row("c1", True, False),
                 open_row("c2", False, False), open_row("gone", True, True, present=1)]
    fresh = [label("b1", "bridge", "bridge", "comparison"), label("b2", "bridge", "comparison", "bridge"),
             label("c1", "comparison", "comparison", "comparison"), label("c2", "comparison", "bridge", "bridge"),
             label("gone", "bridge", "bridge", "bridge")]
    got = score(open_rows, fresh)
    assert got["covered"] == 4                                      # "gone" lacks a gold article
    # bridge goes to the hop, comparison to BM25:
    # rule   b1 hop hit,  b2 bm25 hit,  c1 bm25 hit, c2 hop miss  -> 3
    # model  b1 bm25 miss, b2 hop miss, c1 bm25 hit, c2 hop miss  -> 1
    # oracle b1 hop hit,  b2 hop miss,  c1 bm25 hit, c2 bm25 miss -> 2
    assert got["both_gold"] == {"bm25": 2, "hop": 1, "router_rule": 3, "router_model": 1, "router_oracle": 2}
    assert got["label_agreement"] == {"rule": 2, "model": 2}
    assert [r["id"] for r in got["rows"]] == ["b1", "b2", "c1", "c2"]


def test_the_paired_difference_is_against_the_hop_alone():
    open_rows = [open_row(f"q{i}", i % 2 == 0, i % 3 == 0) for i in range(12)]
    fresh = [label(f"q{i}", "comparison", "comparison", "bridge") for i in range(12)]
    got = score(open_rows, fresh)
    # every row is labelled comparison by the rule, so the rule router is BM25 throughout, and the model router is
    # the hop throughout: its difference from the hop alone is exactly zero
    assert got["both_gold"]["router_rule"] == got["both_gold"]["bm25"] == 6
    assert got["against_hop"]["router_model"]["points"] == 0.0
    assert got["against_hop"]["router_rule"]["points"] == round((6 - 4) / 12 * 100, 2)
