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

## Control: thinking on, given the gold paragraphs (2026-11-21, on the Mac, 2,340 s)

This run asks the question the earlier tables left open: if the large model reasons before answering, does it beat the
small one once both have the right evidence? qwen3.6:27b-mlx, with thinking on (`--think`, up to 8,192 tokens) and
prompt v2, answered the same 100 questions given the 2 gold paragraphs. Its answers are in
`results/think-gold100-2026-11-21.jsonl`.

| Against thinking qwen (69 exact, F1 0.845) | Exact match, 95% CI | F1, 95% CI |
|---|---|---|
| qwen, thinking off (64) | +5 (-0.1 to +10.1) | +1.3 (-1.4 to +3.9) |
| nemotron-mini, thinking off (68) | +1 (-4.9 to +6.9) | +1.2 (-2.7 to +5.0) |
| gemma4:31b, thinking off (63) | +6 (+0.6 to +11.4) | +4.1 (+0.1 to +8.2) |

- **No clear separation.** Thinking adds a few points for the 27B, but doesn't separate it from the 4B. Given the right two
  paragraphs, every model and mode tried sits between 63 and 69 exact and near F1 0.83.
- **The cost:** 546 thinking tokens on average and 23 s a question, against 0.4 s for the 4B.
- **So in this setting retrieval is the limit, not the reader.** That's why better retrieval (the hop) helps a small
  model more than a large model helps itself. Whether that holds where reading is harder, with a corpus to search
  rather than 10 paragraphs, is #8's corpus v0.

## The open test: each arm searches all of Wikipedia (2026-11-21, on the Mac)

**Corpus v0** (`build_corpus.py`): `enwiki-20261101`, the dump's own sha1s checked; 25,991,252 pages read; 7,245,115
article lead sections; 43,921,329 links between articles both in the corpus (709,056 dropped); 12,097,295 redirects
resolved; 3 duplicate titles (pages moved while the dump was written) kept at their newest revision. 9.4 GB, digest
`adb91dafb82dab98dac7e20062c4b4197955240c5dbd647102e06c8a5e7c8c43`, built in 29 minutes with 12 workers.

**The test** (`hotpot_open.py`): the same 100 seeded questions. BM25 picks the corpus's top 2; the hop picks the top 1
and the article it links to that ranks best against the question. Gold titles are 2017's, mapped through the dump's
redirects. The first run didn't unescape HotpotQA's HTML titles ("Merck &amp; Co."), which left 7 questions
uncovered; the picks don't depend on the gold, so the counts below are recomputed from the saved picks with the fix.

| Both gold articles among the 2 picked | BM25 | Hop |
|---|---|---|
| All 96 covered questions | 7 (7.3%) | 17 (17.7%) |
| Bridge (85) | 6 | 17 |
| Comparison (11) | 1 | 0 |

Paired, hop against BM25: 13 hop-only, 3 BM25-only, **+10.4 points (95% CI +2.5 to +18.3)**. Four questions stay
uncovered: their gold articles appear to have been deleted or renamed since 2017.

**How to read it:**
- **Open retrieval is hard for both arms.** With 7.2 million candidates and 2 picks, the distractor setting's 24% and
  48% fall to 7% and 18%. The hop's lead holds, at about 2.4 times BM25's rate.
- **The distractor construction is gone; the bridge construction is not.** HotpotQA built bridge questions from linked
  article pairs, and the hop follows Wikipedia's links. That favours the hop by design here too.
- **Cost:** a full-question BM25 query over the whole corpus took about 19 s (common words have huge posting lists;
  2.5 s without them). The hop adds almost nothing on top: its link ranking is restricted to a few hundred titles.
- **Next:** the same arms with models answering, then a corpus whose questions weren't built from its links.

## The open test, with models answering (2026-11-21, on the Mac)

`hotpot_open_answers.py` gives each model the 2 articles each arm picked from the whole corpus, read from corpus v0
by digest, with prompt v2 and thinking off, as in the distractor runs. The 100 questions are the same; every answer
is in `results/open100-answers-2026-11-21.jsonl`. "No evidence" is the v2 closed-book run above.

| Exact matches out of 100 (mean F1) | No evidence | BM25's picks | Hop's picks |
|---|---|---|---|
| nemotron-mini (about 4B) | 23 | 32 (0.43) | 34 (0.43) |
| qwen3.6:27b-mlx | 22 | 25 (0.40) | 29 (0.45) |

**Paired, exact match, 95% CI:**

| Comparison | Difference |
|---|---|
| Hop against BM25, small model | +2 (-4.8 to +8.8) |
| Hop against BM25, large model | +4 (-0.8 to +8.8) |
| Hop against no evidence, small model | +11 (+1.8 to +20.2) |
| Small with the hop against large with BM25 | +9 (+0.6 to +17.4) |

**How to read it:**
- **Retrieval's gain shrinks again at the answer.** The hop's +10.4 points of both-gold becomes 2 to 4 answers within
  a model, and neither difference clears zero. With 2 picks from 7.2 million, an arm often brings one useful article,
  not both.
- **Small with the hop still beats large with BM25** here, just: +9 (CI +0.6 to +17.4). As in the distractor runs, the
  27B scores below the 4B with the same evidence in this setup (25 against 32 with BM25), so it's not a test of size.
- **Evidence still helps a small model clearly** (+11 over closed-book).

## The first approach-by-kind router (issue #12's smallest adapter, 2026-11-21, on the Mac, 8 s)

`hotpot_router.py` gives each question a predicted kind from a word rule fixed before scoring, splits HotpotQA's
7,405 dev questions 50/50 by seed, picks on the development half the better arm for each predicted kind (it chose
the hop for bridge and BM25 for comparison), and scores once on the held-out half. Verifier: HotpotQA's gold
paragraphs. Rows are in `results/router-2026-11-21.json`.

| Held-out (3,703), both gold among 2 picked | Count | Against the hop alone, 95% CI |
|---|---|---|
| BM25 alone | 918 | |
| Hop alone | 1,808 | |
| Router by the word rule | 1,835 | +0.73 points (-0.07 to +1.53) |
| Router that knows the true type | 1,938 | +3.51 points (+2.92 to +4.10) |

**How to read it:**
- **The weight is real; the classifier isn't good enough yet.** Knowing the kind is worth +3.5 points over the best single
  arm. The rule matches HotpotQA's label on 89% of held-out questions, but only 659 of the 991 it calls comparisons
  are comparisons. The 332 misrouted bridge questions give back most of the gain.
- **This holdout is now spent.** A better classifier (a small model, say) is fixed first and scored on fresh held-out
  questions, from HotpotQA's train split, never on this half again.

## The router on fresh held-out questions (2026-11-21, on the Mac)

`hotpot_router_fresh.py` draws 2,000 questions by seed from HotpotQA's train split (train-00000 at revision 1908d6af,
sha256 `76d3bb30...2e68`), which nothing here had looked at, and routes with the dev half's fitted choice (bridge to
the hop, comparison to BM25). The classifiers: the word rule, and nemotron-mini zero-shot.

- **Run 1** (seed 20261121, prompt c1, the instruction as system prompt): the 4B model answered the questions instead
  of classifying them ("no", "yes", "American"), so the model router equalled the hop. A failure to follow the
  instruction, not a measure of classifying. Rule router: +0.95 points (95% CI -0.14 to +2.04). Oracle router: +3.80
  (+2.96 to +4.64).
- **Run 2** (seed 20261122, a new unseen sample; prompt c2, the instruction in the user message, declared as a retry
  of the prompt's form only):

| 2,000 fresh questions, both gold among 2 picked | Count | Against the hop alone, 95% CI |
|---|---|---|
| BM25 alone | 519 | |
| Hop alone | 1,044 | |
| Router by the model (85% agree with the label) | 1,015 | -1.45 points (-2.34 to -0.56) |
| Router by the word rule (88% agree) | 1,021 | -1.15 points (-2.15 to -0.15) |
| Router that knows the true type | 1,082 | +1.90 points (+1.30 to +2.50) |

**How to read it, across the three held-out samples:**
- **The weight per approach and kind is real but small.** Knowing the kind is worth +1.9 to +3.8 points over the hop
  alone.
- **With classifiers right 85 to 88% of the time, routing doesn't pay, and it can cost.** A bridge question sent to BM25
  loses more than a comparison sent there gains.
- **So by the rule written before the run,** the approach-by-kind graph adds nothing yet over the single best approach.
  It would need a classifier above about 95%, or kinds whose arms differ more than these two do.
