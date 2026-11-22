"""Issue #12's smallest adapter: route each question to BM25 or the link hop by its kind, fitted on one half, scored once
on the other.

Fixed before any scoring:
- ``kind_of`` is a rule over the question's words that says "comparison" or "bridge". It never sees the label.
- HotpotQA's dev questions split 50/50 by a seed into development and holdout.
- On development, each predicted kind takes the arm with more both-gold picks. That's the only fitting.
- On holdout, the router is scored once against BM25 alone and the hop alone. A router that knows the true type
  (``oracle``) is the ceiling.

Outcomes come from HotpotQA's gold paragraphs (the verifier), and each result row names its cohort.
Usage: ``python hotpot_router.py <parquet> --out router.json``.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys

try:
    from experiments.multihop.hotpot_retrieval import BM25, both_gold, from_row, pick_bm25, pick_hop
except ImportError:  # pragma: no cover
    from hotpot_retrieval import BM25, both_gold, from_row, pick_bm25, pick_hop

SEED = 20261121
_COMPARE = re.compile(
    r"\b(both|same|either|older|younger|oldest|youngest|earlier|later|first|last|longer|shorter|larger|smaller|"
    r"bigger|higher|lower|more|less|fewer|greater|further|closer|farther|taller|faster|slower)\b", re.I)
_YES_NO = re.compile(r"^\s*(are|were|is|was|do|does|did|can|could|has|have|had|will|would)\b", re.I)


def kind_of(question: str) -> str:
    """'comparison' when the question weighs two things against each other, else 'bridge'."""
    if _YES_NO.match(question) or (" or " in question and question.rstrip().endswith("?")):
        return "comparison"
    return "comparison" if _COMPARE.search(question) else "bridge"


def split(n: int) -> tuple[set[int], set[int]]:
    order = list(range(n))
    random.Random(SEED).shuffle(order)
    return set(order[: n // 2]), set(order[n // 2:])


def run(questions) -> dict:
    corpus = {t: x for q in questions for t, x in q.paragraphs}
    bm25 = BM25({t: t + " " + x for t, x in corpus.items()})
    rows = []
    for i, q in enumerate(questions):
        rows.append({"i": i, "type": q.kind, "predicted": kind_of(q.question),
                     "bm25": both_gold(q, pick_bm25(q, bm25)), "hop": both_gold(q, pick_hop(q, bm25))})
    development, holdout = split(len(rows))
    choice = {}
    for kind in ("bridge", "comparison"):
        dev = [r for r in rows if r["i"] in development and r["predicted"] == kind]
        choice[kind] = "hop" if sum(r["hop"] for r in dev) >= sum(r["bm25"] for r in dev) else "bm25"
    held = [r for r in rows if r["i"] in holdout]
    oracle = {"bridge": "hop", "comparison": "bm25"}
    score = lambda pick: sum(r[pick(r)] for r in held)
    rule_right = sum(r["predicted"] == r["type"] for r in held)
    return {"questions": len(rows), "holdout": len(held), "development": len(development), "seed": SEED,
            "fitted_choice": choice, "rule_matches_label_on_holdout": rule_right,
            "holdout_both_gold": {"bm25": score(lambda r: "bm25"), "hop": score(lambda r: "hop"),
                                  "router": score(lambda r: choice[r["predicted"]]),
                                  "oracle_router": score(lambda r: oracle[r["type"]])},
            "verifier": "HotpotQA gold supporting paragraphs", "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #12: route by question kind, fitted on half, scored on half")
    parser.add_argument("parquet")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    result = run([from_row(r) for r in pq.read_table(args.parquet).to_pylist()])
    if args.out:
        with open(args.out, "w") as out:
            json.dump(result, out)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
