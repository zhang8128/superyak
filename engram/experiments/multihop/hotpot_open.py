"""Issue #8's open test: BM25 against one link hop, each searching a whole frozen corpus, not 10 given paragraphs.

The questions are the same seeded HotpotQA dev sample as ``hotpot_smoke`` (100 by default, the first 10 being the
smoke test's). Each arm picks 2 articles from the corpus:
- ``bm25``: the corpus's top 2 for the question;
- ``hop``: the top 1, then the article it links to that ranks best against the question (``FrozenCorpus.rank``).
  With no link that matches, BM25's second.

HotpotQA's gold titles are 2017's, so each is mapped to today's title through the build's redirects table. A
question counts toward ``both_gold`` only when both gold articles are in the corpus. Coverage is reported beside it,
so a thin corpus can't pass for a good arm. The corpus is opened with its expected digest.

Usage: ``PYTHONPATH=engram:atlas python -m experiments.multihop.hotpot_open --corpus C --digest D --redirects R
--parquet P [--count 100] [--out per-question.jsonl]``
"""
from __future__ import annotations

import argparse
import html
import json
import random
import sqlite3
import sys

try:
    from experiments.multihop.wiki_dump import canonical
except ImportError:  # pragma: no cover
    from wiki_dump import canonical

SEED = 20261121


def current_title(title: str, redirects: sqlite3.Connection | None) -> str:
    """HotpotQA writes its titles HTML-escaped ("Merck &amp; Co."); Wikipedia doesn't."""
    name = canonical(html.unescape(title))
    if redirects is None:
        return name
    row = redirects.execute("SELECT target FROM r WHERE title = ?", (name,)).fetchone()
    return row[0] if row else name


def pick_bm25(corpus, question: str) -> list[str]:
    return [p["title"] for p in corpus.search(question, limit=2)["papers"]]


def pick_hop(corpus, question: str) -> list[str]:
    top = corpus.search(question, limit=2)["papers"]
    if not top:
        return []
    first = top[0]["title"]
    linked = corpus.links(first)[:1000]
    best = corpus.rank(question, linked, limit=1) if linked else []
    if best:
        return [first, best[0]["title"]]
    return [p["title"] for p in top]


def evaluate(corpus, questions: list[dict], redirects: sqlite3.Connection | None) -> tuple[dict, list[dict]]:
    in_corpus = lambda title: bool(corpus.rank(title, [title], limit=1)) if title else False
    rows, tally = [], {"bm25": 0, "hop": 0}
    covered = 0
    for q in questions:
        gold = sorted({current_title(t, redirects) for t in q["supporting_facts"]["title"]})
        present = [t for t in gold if in_corpus(t)]
        row = {"id": q["id"], "type": q["type"], "gold": gold, "gold_in_corpus": len(present)}
        both_present = len(present) == len(gold)
        covered += both_present
        for arm, pick in (("bm25", pick_bm25), ("hop", pick_hop)):
            picks = pick(corpus, q["question"])
            hit = set(gold) <= set(picks)   # an arm picks only corpus titles, so a missing gold can't be hit
            row[arm] = picks
            row[arm + "_both"] = hit
            tally[arm] += hit
        rows.append(row)
    summary = {"questions": len(questions), "both_gold_in_corpus": covered,
               "both_gold": {arm: {"hits": n, "of_covered": round(n / covered, 4) if covered else None}
                             for arm, n in tally.items()},
               "corpus": corpus.manifest["id"], "digest": corpus.digest, "verified": corpus.verified, "seed": SEED}
    return summary, rows


def main(argv: list[str] | None = None) -> int:
    from workbench.research_corpus import FrozenCorpus
    parser = argparse.ArgumentParser(description="Issue #8: BM25 against one link hop over a frozen corpus")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--redirects", required=True)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    rows = pq.read_table(args.parquet).to_pylist()
    questions = [rows[i] for i in random.Random(SEED).sample(range(len(rows)), args.count)]
    corpus = FrozenCorpus(args.corpus, digest=args.digest)
    redirects = sqlite3.connect(f"file:{args.redirects}?mode=ro", uri=True)
    summary, per_question = evaluate(corpus, questions, redirects)
    if args.out:
        with open(args.out, "w") as out:
            for row in per_question:
                out.write(json.dumps(row) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
