"""Issue #8's open test, Rust-backed: the same two arms as ``hotpot_open.py`` (BM25's top 2, and
BM25's top 1 plus one link hop), scored the same way (same seed, same gold-title mapping through
redirects, same ``both_gold``/coverage accounting) -- but every question's picks come from one
``corpus-index query`` process, fed the whole batch over stdin at once, instead of one SQLite
FTS5 ``search``/``rank`` call per question. That is the ~19 s-per-question path's replacement:
milliseconds per question once the index is loaded.

The corpus SQLite is still opened directly (read-only), but only for the cheap part: resolving
each gold title to a page id (and back), to check whether it's in the corpus and whether an arm's
picked page ids cover it. It is *not* reopened through ``research_corpus.FrozenCorpus`` and its
digest is not reverified by rehashing every passage; that integrity check belongs to the
record-of-truth run (``hotpot_open.py``), not to this speed variant, and the summary says so with
``"digest_verified": false`` rather than implying a check that didn't happen.

Usage: ``PYTHONPATH=engram python -m experiments.multihop.hotpot_open_rs --corpus C.sqlite3
--index index.bin --redirects R.sqlite3 --parquet P [--count 100 | --all] [--bin corpus-index]
[--out per-question.jsonl]``
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import sqlite3
import subprocess
import sys

try:
    from experiments.multihop.hotpot_open import SEED, current_title
except ImportError:  # pragma: no cover
    from hotpot_open import SEED, current_title

# engram/native/corpus_index/target/release/corpus-index, relative to this file.
DEFAULT_BIN = Path(__file__).resolve().parents[2] / "native" / "corpus_index" / "target" / "release" / "corpus-index"


def load_corpus_title_maps(corpus_path) -> tuple[dict[str, int], dict[int, str], dict | None, str | None]:
    """Title<->page id maps for every passage, plus the manifest and digest `corpus-index build`
    read from the same file -- read straight from the corpus's own tables, no FTS, no rehash."""
    db = sqlite3.connect(f"file:{corpus_path}?mode=ro", uri=True)
    try:
        meta = dict(db.execute("SELECT key, value FROM meta"))
        manifest = json.loads(meta["manifest"]) if "manifest" in meta else None
        digest = meta.get("digest")
        title_to_id: dict[str, int] = {}
        id_to_title: dict[int, str] = {}
        for page_id, title in db.execute("SELECT page_id, title FROM passages"):
            title_to_id[title] = page_id
            id_to_title[page_id] = title
    finally:
        db.close()
    return title_to_id, id_to_title, manifest, digest


def run_queries(bin_path, index_path, items: list[tuple[str, str]], k: int) -> dict[str, tuple[list[int], list[int]]]:
    """Feed every ``(qid, question)`` to one ``corpus-index query`` process over stdin, and parse
    its ``qid\\tbm25 ids\\thop ids`` stdout lines back into page id lists."""
    stdin = "".join(f"{qid}\t{text}\n" for qid, text in items)
    proc = subprocess.run(
        [str(bin_path), "query", "--index", str(index_path), "--k", str(k)],
        input=stdin, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"corpus-index query failed (exit {proc.returncode}): {proc.stderr.strip()}")
    picks: dict[str, tuple[list[int], list[int]]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        qid, bm25_field, hop_field = parts
        bm25_ids = [int(x) for x in bm25_field.split(",") if x]
        hop_ids = [int(x) for x in hop_field.split(",") if x]
        picks[qid] = (bm25_ids, hop_ids)
    return picks


def evaluate(bin_path, index_path, corpus_path, questions: list[dict],
             redirects: sqlite3.Connection | None, k: int = 2) -> tuple[dict, list[dict]]:
    title_to_id, id_to_title, manifest, digest = load_corpus_title_maps(corpus_path)
    items = [(q["id"], q["question"]) for q in questions]
    picks = run_queries(bin_path, index_path, items, k)

    rows, tally = [], {"bm25": 0, "hop": 0}
    covered = 0
    for q in questions:
        gold = sorted({current_title(t, redirects) for t in q["supporting_facts"]["title"]})
        present = [t for t in gold if t in title_to_id]
        row = {"id": q["id"], "type": q["type"], "gold": gold, "gold_in_corpus": len(present)}
        both_present = len(present) == len(gold)
        covered += both_present
        bm25_ids, hop_ids = picks.get(q["id"], ([], []))
        for arm, ids in (("bm25", bm25_ids), ("hop", hop_ids)):
            titles = [id_to_title[i] for i in ids if i in id_to_title]
            hit = set(gold) <= set(titles)  # an arm picks only corpus titles, so a missing gold can't be hit
            row[arm] = titles
            row[arm + "_both"] = hit
            tally[arm] += hit
        rows.append(row)

    summary = {"questions": len(questions), "both_gold_in_corpus": covered,
               "both_gold": {arm: {"hits": n, "of_covered": round(n / covered, 4) if covered else None}
                             for arm, n in tally.items()},
               "corpus": manifest["id"] if manifest else None, "digest": digest,
               "digest_verified": False, "seed": SEED}
    return summary, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #8's open test, picks from corpus-index query")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--redirects", required=True)
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--all", action="store_true", help="score every question in the parquet, not a sample")
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--bin", default=str(DEFAULT_BIN), help="path to the built corpus-index binary")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    import pyarrow.parquet as pq
    all_rows = pq.read_table(args.parquet).to_pylist()
    if args.all:
        questions = all_rows
    else:
        questions = [all_rows[i] for i in random.Random(SEED).sample(range(len(all_rows)), args.count)]

    redirects = sqlite3.connect(f"file:{args.redirects}?mode=ro", uri=True)
    summary, per_question = evaluate(args.bin, args.index, args.corpus, questions, redirects, k=args.k)
    if args.out:
        with open(args.out, "w") as out:
            for row in per_question:
                out.write(json.dumps(row) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
