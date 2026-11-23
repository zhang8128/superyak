"""Issue #12, Phase 3: the approach-by-kind router in the open setting, on the fresh held-out questions.

In the distractor setting, routing by kind didn't pay with real classifiers (``hotpot_router_fresh.py``). On all of
Wikipedia's leads the two arms split sharply by kind (RESULTS, the whole dev set): on comparison questions BM25 finds
both gold articles 9.2% of the time and the hop 0.3%; on bridge questions 6.1% against 22.1%. This asks whether
routing by kind pays there.

Fixed before any open scoring (this file's first commit precedes its run):
- **Questions:** the 2,000 fresh train questions of each saved ``hotpot_router_fresh`` run, by id: c1 (seed 20261121)
  and c2 (seed 20261122), from train-00000 at revision 1908d6af.
- **Picks:** ``corpus-index`` over corpus v0, through ``hotpot_open_rs.evaluate``: the same arms, gold mapping and k = 2.
- **Routing:** the dev half's fitted choice, unchanged: bridge to the hop, comparison to BM25.
- **Classifiers:** the labels saved in those runs, the word rule and nemotron-mini. No new model calls.
- **Primary measure:** on c2, the run whose model did classify (in c1 it answered the questions instead), the
  model-routed both-gold count against the hop alone, on covered questions, paired, with a 95% CI.
- **Secondary:** the rule router on both samples, the model router on c1, and the oracle router (true type) as the
  ceiling, each against the hop alone.

Usage: ``PYTHONPATH=engram:atlas python -m experiments.multihop.hotpot_router_open --fresh c1.json c2.json
--parquet train0.parquet --corpus C --index I --redirects R --bin corpus-index --out router-open.json``
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

try:
    from experiments.multihop.hotpot_router_fresh import ROUTE, paired
except ImportError:  # pragma: no cover
    from hotpot_router_fresh import ROUTE, paired


def score(open_rows: list[dict], fresh_rows: list[dict]) -> dict:
    """Routers over one sample: each covered open row joined to its saved labels by id."""
    labels = {r["id"]: r for r in fresh_rows}
    rows = []
    for o in open_rows:
        if o["gold_in_corpus"] != len(o["gold"]):
            continue  # a gold article the corpus lacks can't be picked by any arm
        lab = labels[o["id"]]
        rows.append({"id": o["id"], "type": lab["type"], "rule": lab["rule"], "model": lab["model"],
                     "bm25": bool(o["bm25_both"]), "hop": bool(o["hop_both"])})
    pick = {"router_rule": lambda r: r[ROUTE[r["rule"]]], "router_model": lambda r: r[ROUTE[r["model"]]],
            "router_oracle": lambda r: r[ROUTE[r["type"]]]}
    both_gold = {"bm25": sum(r["bm25"] for r in rows), "hop": sum(r["hop"] for r in rows)}
    both_gold |= {name: sum(f(r) for r in rows) for name, f in pick.items()}
    return {"covered": len(rows), "both_gold": both_gold,
            "against_hop": {name: paired(rows, f, lambda r: r["hop"]) for name, f in pick.items()},
            "label_agreement": {"rule": sum(r["rule"] == r["type"] for r in rows),
                                "model": sum(r["model"] == r["type"] for r in rows)},
            "rows": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #12: the kind router in the open setting, fresh questions")
    parser.add_argument("--fresh", nargs="+", required=True, help="saved hotpot_router_fresh results, by sample")
    parser.add_argument("--parquet", required=True, help="HotpotQA distractor train-00000")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--redirects", required=True)
    parser.add_argument("--bin", required=True, help="the built corpus-index binary")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    try:
        from experiments.multihop.hotpot_open_rs import evaluate
    except ImportError:  # pragma: no cover
        from hotpot_open_rs import evaluate
    by_id = {r["id"]: r for r in pq.read_table(args.parquet).to_pylist()}
    redirects = sqlite3.connect(f"file:{args.redirects}?mode=ro", uri=True)
    result = {"route": ROUTE, "picks": "corpus-index over corpus v0, k = 2", "samples": {}}
    for path in args.fresh:
        fresh = json.load(open(path))
        questions = [by_id[r["id"]] for r in fresh["rows"]]
        summary, open_rows = evaluate(args.bin, args.index, args.corpus, questions, redirects)
        scored = score(open_rows, fresh["rows"])
        name = fresh.get("classify_prompt") or "c1"
        result["samples"][name] = {"seed": fresh["seed"], "source": fresh["source"], "questions": len(questions),
                                   "corpus": summary["corpus"], **scored}
    if args.out:
        with open(args.out, "w") as out:
            json.dump(result, out)
    print(json.dumps({name: {k: v for k, v in s.items() if k != "rows"} for name, s in result["samples"].items()},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
