"""Issue #7's 10-question smoke test: does the evidence each arm retrieves change a model's answer?

Ten dev questions from HotpotQA's distractor setting, drawn by a fixed seed, go to each model four times, with
four kinds of evidence:
- ``closed``: none;
- ``bm25`` and ``hop``: the 2 paragraphs each arm of ``hotpot_retrieval`` picks;
- ``oracle``: the 2 gold paragraphs, the ceiling.

The prompt, the models, the seed and the scoring are fixed before the first run. Answers are scored with HotpotQA's
own exact match and F1 (lowercase, no punctuation or articles, whitespace folded). Ten questions show whether the
harness works end to end and which way the arms lean. They decide nothing on their own.

Usage: ``python hotpot_smoke.py <parquet> --models nemotron-mini:latest qwen3.6:27b-mlx --out smoke.jsonl``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import random
import re
import string
import sys
import time
import urllib.request

try:  # run as a module in the repository, or as a file beside hotpot_retrieval.py
    from experiments.multihop.hotpot_retrieval import BM25, Question, from_row, pick_bm25, pick_hop, pick_oracle
except ImportError:  # pragma: no cover
    from hotpot_retrieval import BM25, Question, from_row, pick_bm25, pick_hop, pick_oracle

SEED = 20261121
COUNT = 10
OLLAMA = "http://127.0.0.1:11434/api/chat"
PROMPTS = {
    # v1, the first runs': it lists "yes or no" among the answer forms, and a 27B model then said "No" to wh-questions.
    "v1": ("Answer the question with a short phrase only: a name, a number, a date, or yes or no. "
           "No explanation. If paragraphs are given, use them."),
    # v2: yes or no only for a yes/no question, and a best answer when the paragraphs fall short.
    "v2": ("Answer with the shortest phrase that answers the question, such as a name, a number or a date. "
           "Answer yes or no only if the question is a yes/no question. No explanation. If paragraphs are given, "
           "use them; if they don't contain the answer, still give your best answer."),
}
SYSTEM = PROMPTS["v1"]


def normalize(text: str) -> str:
    text = text.lower()
    text = "".join(ch for ch in text if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact(prediction: str, gold: str) -> bool:
    return normalize(prediction) == normalize(gold)


def f1(prediction: str, gold: str) -> float:
    p, g = normalize(prediction), normalize(gold)
    if p in {"yes", "no", "noanswer"} or g in {"yes", "no", "noanswer"}:
        return float(p == g)
    common = Counter(p.split()) & Counter(g.split())
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision, recall = same / len(p.split()), same / len(g.split())
    return 2 * precision * recall / (precision + recall)


def prompt(q: Question, picks: list[int] | None) -> str:
    if not picks:
        return f"Question: {q.question}"
    evidence = "\n\n".join(f"[{q.paragraphs[i][0]}] {q.paragraphs[i][1]}" for i in picks)
    return f"Paragraphs:\n{evidence}\n\nQuestion: {q.question}"


def ask(model: str, text: str, timeout: float = 900, system: str = SYSTEM, think: bool = False) -> tuple[str, float, dict]:
    body = json.dumps({"model": model, "stream": False, "think": think,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
                       "options": {"temperature": 0, "seed": SEED, "num_predict": 8192 if think else 64}}).encode()
    request = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        reply = json.load(response)
    took = time.perf_counter() - start
    usage = {k: reply.get(k) for k in ("prompt_eval_count", "eval_count", "total_duration")}
    return reply["message"]["content"].strip().splitlines()[0] if reply["message"]["content"].strip() else "", took, usage


def sample(rows: list[dict], count: int = COUNT) -> list[tuple[Question, str]]:
    chosen = random.Random(SEED).sample(range(len(rows)), count)  # 100 starts with the same 10
    return [(from_row(rows[i]), rows[i]["answer"]) for i in chosen]


def run(rows: list[dict], models: list[str], out, count: int = COUNT, prompt_version: str = "v1",
        think: bool = False, only: list[str] | None = None) -> dict:
    questions = sample(rows, count)
    all_corpus = {t: x for row in rows for t, x in from_row(row).paragraphs}
    bm25 = BM25({t: t + " " + x for t, x in all_corpus.items()})   # the same IDF as hotpot_retrieval
    arms = {"closed": lambda q: None, "bm25": lambda q: pick_bm25(q, bm25),
            "hop": lambda q: pick_hop(q, bm25), "oracle": pick_oracle}
    arms = {name: pick for name, pick in arms.items() if not only or name in only}
    totals: dict = {}
    for model in models:
        for q, gold in questions:
            for arm, pick in arms.items():
                answer, took, usage = ask(model, prompt(q, pick(q)), system=PROMPTS[prompt_version], think=think)
                row = {"model": model, "prompt": prompt_version, "think": think, "arm": arm, "id": q.qid, "type": q.kind, "gold": gold, "answer": answer,
                       "em": exact(answer, gold), "f1": round(f1(answer, gold), 4), "seconds": round(took, 2)} | usage
                out.write(json.dumps(row) + "\n")
                out.flush()
                cell = totals.setdefault(model, {}).setdefault(arm, {"em": 0, "f1": 0.0, "seconds": 0.0})
                cell["em"] += row["em"]
                cell["f1"] += row["f1"]
                cell["seconds"] += took
    return {"questions": [q.qid for q, _ in questions], "types": dict(Counter(q.kind for q, _ in questions)),
            "seed": SEED, "prompt": prompt_version, "think": think, "per_model": {m: {a: {"em": c["em"], "f1": round(c["f1"] / count, 3),
                                                "seconds": round(c["seconds"], 1)} for a, c in arms_.items()}
                                        for m, arms_ in totals.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #7: a 10-question smoke test of four evidence arms")
    parser.add_argument("parquet")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--count", type=int, default=COUNT)
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="v1")
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--arms", nargs="+", choices=["closed", "bm25", "hop", "oracle"])
    args = parser.parse_args(argv)
    import pyarrow.parquet as pq
    rows = pq.read_table(args.parquet).to_pylist()
    with open(args.out, "w") as out:
        summary = run(rows, args.models, out, args.count, args.prompt, args.think, args.arms)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
