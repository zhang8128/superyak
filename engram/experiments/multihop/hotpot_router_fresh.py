"""Issue #12: the approach-by-kind router on fresh held-out questions, with a model classifier beside the word rule.

The dev holdout was spent on the first router (RESULTS.md). This scores once on 2,000 questions drawn by seed from
HotpotQA's train split, which nothing here has looked at before. All of this is fixed before the run:
- **The routing:** bridge goes to the hop and comparison to BM25, as fitted on the dev half.
- **The classifiers:** the word rule (`hotpot_router.kind_of`), and a small model asked zero-shot (`CLASSIFY` below,
  temperature 0).
- **The primary measure:** the model-routed both-gold count against the hop alone, paired, with a 95% CI.

Usage: ``python hotpot_router_fresh.py <train parquet> --model nemotron-mini:latest --out fresh.json``.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys

try:
    from experiments.multihop.hotpot_retrieval import BM25, both_gold, from_row, pick_bm25, pick_hop
    from experiments.multihop.hotpot_router import kind_of
    from experiments.multihop.hotpot_smoke import ask
except ImportError:  # pragma: no cover
    from hotpot_retrieval import BM25, both_gold, from_row, pick_bm25, pick_hop
    from hotpot_router import kind_of
    from hotpot_smoke import ask

SEED = 20261121
COUNT = 2000
ROUTE = {"bridge": "hop", "comparison": "bm25"}   # fitted on the dev half (results/router-2026-11-21.json)
CLASSIFY = ("Classify the question. Reply with exactly one word. Reply comparison if the question compares two "
            "named things or asks whether both share something. Reply bridge if answering needs one fact to find "
            "another.")


def classify_prompt(question: str, version: str) -> tuple[str, str]:
    """(system, user). c1, the first run's: the instruction as the system prompt; a 4B model answered the question
    instead. c2: the instruction in the user message, with an answer slot."""
    if version == "c1":
        return CLASSIFY, question
    return "You classify questions. You never answer them.", f"{CLASSIFY}\n\nQuestion: {question}\nOne word, comparison or bridge:"


def parse_kind(answer: str) -> str:
    return "comparison" if "comparison" in answer.lower() else "bridge"


def paired(rows, f, g) -> dict:
    d = [float(f(r)) - float(g(r)) for r in rows]
    n = len(d)
    mean = sum(d) / n
    se = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) / math.sqrt(n)
    return {"points": round(mean * 100, 2), "ci95": [round((mean - 1.96 * se) * 100, 2),
                                                      round((mean + 1.96 * se) * 100, 2)]}


def run(rows_in: list[dict], model: str, seed: int = SEED, version: str = "c1") -> dict:
    chosen = random.Random(seed).sample(range(len(rows_in)), COUNT)
    questions = [from_row(rows_in[i]) for i in chosen]
    corpus = {t: x for q in questions for t, x in q.paragraphs}
    bm25 = BM25({t: t + " " + x for t, x in corpus.items()})
    rows = []
    for q in questions:
        system, user = classify_prompt(q.question, version)
        answer, _, _ = ask(model, user, system=system)
        rows.append({"id": q.qid, "type": q.kind, "rule": kind_of(q.question), "model": parse_kind(answer),
                     "model_said": answer[:40], "bm25": both_gold(q, pick_bm25(q, bm25)),
                     "hop": both_gold(q, pick_hop(q, bm25))})
    score = lambda pick: sum(r[pick(r)] for r in rows)
    return {
        "questions": COUNT, "seed": seed, "classify_prompt": version, "source": "hotpotqa/hotpot_qa distractor train-00000, rev 1908d6af",
        "classifier_model": model, "route": ROUTE,
        "label_agreement": {"rule": sum(r["rule"] == r["type"] for r in rows),
                            "model": sum(r["model"] == r["type"] for r in rows)},
        "both_gold": {"bm25": score(lambda r: "bm25"), "hop": score(lambda r: "hop"),
                      "router_rule": score(lambda r: ROUTE[r["rule"]]),
                      "router_model": score(lambda r: ROUTE[r["model"]]),
                      "router_oracle": score(lambda r: ROUTE[r["type"]])},
        "against_hop": {"router_model": paired(rows, lambda r: r[ROUTE[r["model"]]], lambda r: r["hop"]),
                        "router_rule": paired(rows, lambda r: r[ROUTE[r["rule"]]], lambda r: r["hop"]),
                        "router_oracle": paired(rows, lambda r: r[ROUTE[r["type"]]], lambda r: r["hop"])},
        "verifier": "HotpotQA gold supporting paragraphs", "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #12: the router on fresh held-out questions")
    parser.add_argument("parquet")
    parser.add_argument("--model", required=True)
    parser.add_argument("--out")
    parser.add_argument("--seed", type=int, default=SEED, help="a new seed draws a new, unseen sample")
    parser.add_argument("--prompt", choices=["c1", "c2"], default="c1")
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    result = run(pq.read_table(args.parquet).to_pylist(), args.model, args.seed, args.prompt)
    if args.out:
        with open(args.out, "w") as out:
            json.dump(result, out)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
