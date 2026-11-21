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

## The same harness on 100 questions (2026-11-21, on the Mac, 415 s)

The same seed draws 100 questions (88 bridge, 12 comparison), whose first 10 are the 10 above. The models, prompt and
scoring are unchanged. Each answer is in `results/smoke100-2026-11-21.jsonl`.

| Exact matches out of 100 (mean F1) | No evidence | BM25 | Hop | Gold | Model time |
|---|---|---|---|---|---|
| nemotron-mini (about 4B) | 26 (0.37) | 47 (0.57) | 50 (0.64) | 68 (0.83) | 43 s |
| qwen3.6:27b-mlx | 24 (0.38) | 38 (0.51) | 44 (0.58) | 65 (0.84) | 371 s |

**Paired differences in exact match, 95% CI:**

| Comparison | Difference |
|---|---|
| Hop against BM25, small model | +3 (-4.1 to +10.1); F1 +6.4 (+0.1 to +12.7) |
| Hop against BM25, large model | +6 (+0.6 to +11.4) |
| Small with the hop against large with BM25 | +12 (+4.0 to +20.0) |
| Small against large, both given the gold paragraphs | +3 (-4.6 to +10.6); F1 -0.2 (-4.8 to +4.4) |

**How to read it:**
- **Evidence matters most:** about 25 correct with none, about 66 with the gold paragraphs, for either model.
- **The hop beats BM25 modestly for both models,** clearly for the large one, and on F1 for the small one. Its
  retrieval gain (+24 points of both-gold) shrinks to 3 to 6 points of answers.
- **Small with the hop beats large with BM25, but don't read it as "the graph makes up for size".** Given the gold
  paragraphs, the large model is no better than the small one here. It also answered "No" to non-yes/no questions 9
  times with BM25's evidence and 7 with the hop's, against 1 each for the small model: my prompt lists "yes or no" as an
  answer form. This setup doesn't show the large model's strength. A prompt that allows "unknown", and thinking on, are
  the next controls.
- **Cost:** the large model took 8.6 times as long for the same calls.
- **Still the distractor setting:** both arms choose among 10 paragraphs. #8's corpus v0 is the open test.

## Control: the prompt fixed, and a second large model (2026-11-21, on the Mac, 1,094 s)

Prompt `v2` allows yes or no only for a yes/no question, and asks for a best answer when the paragraphs fall short.
The questions, seed and scoring are the same; gemma4:31b is added. Each answer is in
`results/smoke100-v2-2026-11-21.jsonl`.

| Exact matches out of 100 (mean F1) | No evidence | BM25 | Hop | Gold | Model time |
|---|---|---|---|---|---|
| nemotron-mini (about 4B) | 23 (0.34) | 46 (0.55) | 50 (0.63) | 68 (0.83) | 44 s |
| qwen3.6:27b-mlx | 22 (0.34) | 38 (0.53) | 45 (0.61) | 64 (0.83) | 381 s |
| gemma4:31b | 19 (0.34) | 37 (0.50) | 41 (0.57) | 63 (0.80) | 668 s |

**Paired, exact match, 95% CI:**

| Comparison | Difference |
|---|---|
| Hop against BM25, small / qwen / gemma | +4 (-3.8 to +11.8) / +7 (+1.3 to +12.7) / +4 (-1.5 to +9.5) |
| Small with the hop against qwen with BM25 | +12 (+4.0 to +20.0) |
| Small with the hop against gemma with BM25 | +13 (+5.3 to +20.7) |
| Small against qwen / gemma, all given the gold paragraphs | +4 (-3.8 to +11.8) / +5 (-3.1 to +13.1) |

**How to read it:**
- **The prompt fix worked and changed nothing that mattered.** qwen's "No" to wh-questions fell from 9 to 1 with BM25's
  evidence, but its score stayed at 38, so those answers were wrong either way.
- **A second large model gives the same picture.** Given the gold paragraphs, neither 27-31B model beats the 4B one,
  and all three sit near F1 0.83. On this task, with two paragraphs to read, reading isn't what limits the answer.
  Retrieval is.
- **So small with the hop beating large with BM25 holds up here (+12, +13).** It's a statement about this setting:
  short answers, two paragraphs, thinking off, lexical scoring. It isn't evidence that a graph makes up for model size
  on harder reading. Thinking on, and a corpus where both arms search, are the next tests.
