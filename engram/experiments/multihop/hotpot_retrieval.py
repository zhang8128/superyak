"""Issue #7's first measure: keyword retrieval against one link hop, on HotpotQA's distractor setting, with no model.

Each dev question comes with 10 paragraphs: its 2 gold paragraphs and 8 distractors. Every arm picks 2 of the 10, so
the evidence budget is the same, and is scored on whether it picked both gold paragraphs.

Arms, fixed before the first run:
- ``random``: 2 paragraphs at random (a control; both gold paragraphs are picked 1 time in 45).
- ``oracle``: the 2 gold paragraphs (a control that the gold titles are read right; must be 100%).
- ``bm25``: the 2 paragraphs with the highest BM25 score against the question.
- ``hop``: BM25's first pick, then the best-scoring paragraph it links to, a paragraph whose title its text mentions.
  With no link out, the best paragraph that links to it; with neither, BM25's second pick.

The primary measure is ``both``, the share of questions with both gold paragraphs picked, split by question type
(bridge and comparison). A caution: HotpotQA chose the distractors by TF-IDF similarity to the question, so a keyword
arm is handicapped by construction, and a gap here is partly that construction, not the graph alone.

BM25 is k1 = 1.5 and b = 0.75, with IDF taken over every paragraph in the file, keyed by title, so no question's own
text sets it. Usage: ``python -m experiments.multihop.hotpot_retrieval <parquet> [--out results.json]``.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass

K1, B = 1.5, 0.75
SEED = 20261121
_TOKEN = re.compile(r"\w+", re.UNICODE)
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bare_title(title: str) -> str:
    """A title as text would mention it: "Lotus (band)" is mentioned as "Lotus"."""
    return _PAREN.sub("", title).strip()


@dataclass(frozen=True)
class Question:
    qid: str
    question: str
    kind: str
    gold: frozenset[str]
    paragraphs: tuple[tuple[str, str], ...]  # (title, text), in the file's order


def from_row(row: dict) -> Question:
    titles = row["context"]["title"]
    texts = ["".join(sentences) for sentences in row["context"]["sentences"]]
    return Question(qid=row["id"], question=row["question"], kind=row["type"],
                    gold=frozenset(row["supporting_facts"]["title"]),
                    paragraphs=tuple(zip(titles, texts)))


class BM25:
    def __init__(self, documents: dict[str, str]):
        self.df: Counter[str] = Counter()
        lengths = []
        for text in documents.values():
            words = tokens(text)
            lengths.append(len(words))
            self.df.update(set(words))
        self.n = len(documents)
        self.avgdl = (sum(lengths) / self.n) if self.n else 0.0

    def idf(self, word: str) -> float:
        df = self.df.get(word, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: str, text: str) -> float:
        words = tokens(text)
        counts = Counter(words)
        norm = K1 * (1 - B + B * len(words) / self.avgdl) if self.avgdl else K1
        return sum(self.idf(w) * counts[w] * (K1 + 1) / (counts[w] + norm) for w in set(tokens(query)) if counts[w])


def links(paragraphs: tuple[tuple[str, str], ...]) -> dict[int, set[int]]:
    """i -> j when paragraph i's text mentions paragraph j's bare title, as whole words, ignoring case."""
    out: dict[int, set[int]] = {i: set() for i in range(len(paragraphs))}
    for j, (title, _) in enumerate(paragraphs):
        name = bare_title(title)
        if not name:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(name.lower()) + r"(?!\w)")
        for i, (_, text) in enumerate(paragraphs):
            if i != j and pattern.search(text.lower()):
                out[i].add(j)
    return out


def ranked(q: Question, bm25: BM25) -> list[int]:
    scores = [bm25.score(q.question, title + " " + text) for title, text in q.paragraphs]
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def pick_bm25(q: Question, bm25: BM25) -> list[int]:
    return ranked(q, bm25)[:2]


def pick_hop(q: Question, bm25: BM25) -> list[int]:
    order = ranked(q, bm25)
    first = order[0]
    graph = links(q.paragraphs)
    rank = {i: r for r, i in enumerate(order)}
    out = sorted(graph[first], key=lambda i: rank[i])
    if out:
        return [first, out[0]]
    into = sorted((i for i, targets in graph.items() if first in targets), key=lambda i: rank[i])
    if into:
        return [first, into[0]]
    return order[:2]


def pick_random(q: Question, rng: random.Random) -> list[int]:
    return rng.sample(range(len(q.paragraphs)), 2)


def pick_oracle(q: Question) -> list[int]:
    return [i for i, (title, _) in enumerate(q.paragraphs) if title in q.gold][:2]


def both_gold(q: Question, picks: list[int]) -> bool:
    return {q.paragraphs[i][0] for i in picks} >= q.gold


def run(questions: list[Question]) -> dict:
    corpus = {title: text for q in questions for title, text in q.paragraphs}
    bm25 = BM25({t: t + " " + x for t, x in corpus.items()})
    rng = random.Random(SEED)
    arms = {"random": lambda q: pick_random(q, rng), "oracle": pick_oracle,
            "bm25": lambda q: pick_bm25(q, bm25), "hop": lambda q: pick_hop(q, bm25)}
    tally = {arm: Counter() for arm in arms}
    per_question = []
    for q in questions:
        row: dict[str, object] = {"id": q.qid, "type": q.kind}
        for arm, pick in arms.items():
            hit = both_gold(q, pick(q))
            tally[arm][q.kind] += hit
            tally[arm]["all"] += hit
            row[arm] = hit
        per_question.append(row)
    kinds = Counter(q.kind for q in questions)
    kinds["all"] = len(questions)
    table = {arm: {k: round(tally[arm][k] / n, 4) for k, n in kinds.items()} for arm in arms}
    return {"questions": len(questions), "by_type": dict(kinds), "both_gold": table,
            "paragraphs_in_idf": len(corpus), "seed": SEED, "per_question": per_question}


def load(path: str) -> list[Question]:
    import pyarrow.parquet as pq  # only the runner needs it, not the tests
    return [from_row(row) for row in pq.read_table(path).to_pylist()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #7: BM25 against one link hop on HotpotQA's distractor setting")
    parser.add_argument("parquet")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(load(args.parquet))
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(result, handle, indent=1)
    summary = {k: v for k, v in result.items() if k != "per_question"}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
