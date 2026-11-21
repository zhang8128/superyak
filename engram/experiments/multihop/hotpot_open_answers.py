"""Issue #8's open test, with models: each arm's 2 picked articles from the whole corpus go to a model as evidence.

The picks come from a ``hotpot_open`` run's saved rows, so nothing is searched again. Each article's text is read
from the frozen corpus, opened with its expected digest. The prompt, Ollama settings and scoring are
``hotpot_smoke``'s (prompt ``v2``, thinking off), so the numbers sit beside the distractor setting's.

Usage: ``PYTHONPATH=engram:atlas python -m experiments.multihop.hotpot_open_answers --corpus C --digest D
--picks open100.jsonl --parquet P --models M [M ...] --out answers.jsonl``
"""
from __future__ import annotations

import argparse
import json
import sys

try:
    from experiments.multihop.hotpot_retrieval import Question
    from experiments.multihop.hotpot_smoke import PROMPTS, ask, exact, f1, prompt
except ImportError:  # pragma: no cover
    from hotpot_retrieval import Question
    from hotpot_smoke import PROMPTS, ask, exact, f1, prompt


def evidence(corpus, titles: list[str]) -> tuple[tuple[str, str], ...]:
    """The picked articles' texts, in pick order; a title the corpus lacks is left out."""
    out = []
    for title in titles:
        found = corpus.rank(title, [title], limit=1)
        if found:
            out.append((title, found[0]["abstract"]))
    return tuple(out)


def question_for(row: dict, item: dict, paragraphs) -> Question:
    return Question(qid=item["id"], question=row["question"], kind=item["type"], gold=frozenset(item["gold"]),
                    paragraphs=paragraphs)


def main(argv: list[str] | None = None) -> int:
    from workbench.research_corpus import FrozenCorpus
    parser = argparse.ArgumentParser(description="Issue #8: models answer from each open-corpus arm's picks")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--picks", required=True)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="v2")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    rows = {r["id"]: r for r in pq.read_table(args.parquet).to_pylist()}
    corpus = FrozenCorpus(args.corpus, digest=args.digest)
    items = [json.loads(line) for line in open(args.picks)]
    totals: dict = {}
    with open(args.out, "w") as out:
        for model in args.models:
            for item in items:
                row = rows[item["id"]]
                for arm in ("bm25", "hop"):
                    paragraphs = evidence(corpus, item[arm])
                    q = question_for(row, item, paragraphs)
                    answer, took, usage = ask(model, prompt(q, list(range(len(paragraphs)))),
                                              system=PROMPTS[args.prompt])
                    record = {"model": model, "prompt": args.prompt, "arm": arm, "id": item["id"],
                              "type": item["type"], "gold": row["answer"], "answer": answer,
                              "em": exact(answer, row["answer"]), "f1": round(f1(answer, row["answer"]), 4),
                              "seconds": round(took, 2), "picks": item[arm]} | usage
                    out.write(json.dumps(record) + "\n")
                    out.flush()
                    cell = totals.setdefault(model, {}).setdefault(arm, {"em": 0, "f1": 0.0})
                    cell["em"] += record["em"]
                    cell["f1"] += record["f1"]
    n = len(items)
    print(json.dumps({"questions": n, "corpus": corpus.manifest["id"], "verified": corpus.verified,
                      "per_model": {m: {a: {"em": c["em"], "f1": round(c["f1"] / n, 3)} for a, c in arms.items()}
                                    for m, arms in totals.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
