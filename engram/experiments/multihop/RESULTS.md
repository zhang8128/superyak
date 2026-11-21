# Multi-hop retrieval, first measure (issue #7)

**Run:** 2026-11-21 04:5x UTC, on the Pi 5, in 30 s. Script `hotpot_retrieval.py` at this commit, seed 20261121.

**Data:** HotpotQA dev, distractor setting: 7,405 questions (5,918 bridge, 1,487 comparison). Source:
- the Hugging Face copy `hotpotqa/hotpot_qa` at revision `1908d6afbbead072334abe2965f91bd2709910ab`;
- file `distractor/validation-00000-of-00001.parquet`, sha256
  `c20b638ca82b21d04fe12e14ff417ad05153d4d215a65de54497fca4e972f7c6`;
- license CC BY-SA 4.0.

The original host, curtis.ml.cmu.edu, no longer resolves.

## What was measured

Every arm picks 2 of each question's 10 paragraphs, so the evidence budget is the same. The score is the share of
questions with both gold paragraphs picked. The arms are in the script's docstring, fixed before the first run. No
model is involved.

| Arm | Bridge | Comparison | All |
|---|---|---|---|
| random (control) | 2.5% | 3.0% | 2.6% |
| oracle (control) | 100% | 100% | 100% |
| BM25, top 2 | 22.3% | 31.6% | 24.1% |
| BM25's first pick, then one link hop | **56.4%** | 15.5% | **48.2%** |

**Paired, hop against BM25:**

| Questions | Hop only | BM25 only | Difference (95% CI) |
|---|---|---|---|
| Bridge | 2,141 | 120 | +34.2 points (+32.8 to +35.5) |
| Comparison | 0 | 240 | -16.1 points (-18.0 to -14.3) |
| All | 2,141 | 360 | +24.1 points (+22.8 to +25.3) |

Random sits a little above 1 in 45 (2.2%). Some questions may have fewer than 10 paragraphs; that's unchecked.

## How to read it

- **The mechanism is real on bridge questions.** Once the first paragraph is found, following the link it carries finds
  the second gold paragraph far more often than keywords do.
- **It hurts on comparison questions.** Those name both entities, so the second paragraph is a keyword match, not a link.
  A router would choose between the two by question type. That router isn't built.
- **Both arms are helped or hurt by the dataset's construction, so this is a floor test of the mechanism, not a claim
  about SuperYak:**
  - HotpotQA chose its 8 distractors by TF-IDF similarity to the question, which handicaps a keyword arm.
  - HotpotQA built its bridge questions from article pairs where the first links to the second. Following a link
    partly recovers that construction.
- **Not measured yet:** answers from a model (the 10-question smoke test), a corpus beyond each question's 10 paragraphs
  (#8's corpus v0), and dense retrieval.

## The 10-question smoke test, with models (2026-11-21, on the Mac, 63 s)

`hotpot_smoke.py` asks each model the same 10 dev questions (9 bridge, 1 comparison, seed 20261121) four times, with
no evidence, BM25's 2 paragraphs, the hop's 2, and the 2 gold paragraphs. Ollama on the Mac, temperature 0, thinking
off. Each answer, with its gold and timing, is in `results/smoke-2026-11-21.jsonl`.

| Exact matches out of 10 (mean F1) | No evidence | BM25 | Hop | Gold |
|---|---|---|---|---|
| nemotron-mini (about 4B) | 1 (0.33) | 3 (0.42) | 5 (0.57) | 7 (0.83) |
| qwen3.6:27b-mlx | 1 (0.22) | 2 (0.33) | 3 (0.43) | 7 (0.83) |

**How to read it:**
- **The harness works end to end.** Both models order the arms the same way, as the retrieval measure predicts.
- **Ten questions decide nothing.** That the small model with the hop beat the large one with BM25 (5 against 2) is a
  direction to test at 100 questions, not a result.
- **Some misses are scoring, not reasoning.** "Belleville, Michigan" against "Belleville", for example, scores 0 exact
  and partial F1.
- **The large model answered "No" to some wh-questions** when its evidence lacked the answer. It's untested whether a
  prompt that allows "unknown" changes that.
