# North-star test 2: retrieving the evidence that holds the answer, against strong baselines

Serenity, 2026-11-22. Test 2 of [docs/north-star.md](../../north-star.md). It needs a fresh reviewer's approval
before any code (station law, section 3), and nothing runs until its plan is fixed in a commit.

## Why this test, now

Test 1 found the bottleneck. When a source was corrected, each arm gave the corrected fact for only about 18% of
corrected questions, because the lead holding the answer reached the model for about 34% (E 137 of 400, B 132). Given
that lead, the model used it 53% of the time.

A ceiling measured before this spec, on test 1's 800 questions with no model calls, shows where the lead sits:

| Candidates | Holds the answer-bearing lead |
| --- | --- |
| BM25 top 2 | 20.4% |
| BM25 top 10 | 34.2% |
| BM25 top 100 | 50.4% |
| BM25 top 1,000 | 64.1% |
| One link hop from BM25's top 5 | 60.8% |
| BM25 top 100 plus one hop from the top 5 | 79.8% (median 126 candidates) |

So the lead is usually in reach; the loss is in choosing the two. Here the north star's question becomes concrete:
does the environment's structure, its link graph, add to a strong conventional reranker, or does the reranker alone
do as well?

## Design

### Questions

- **The draw:** 800 qualifying questions from HotpotQA's distractor train split (train-00000, revision 1908d6af), with
  test 1's qualifying rule.
  - Each is a bridge question whose two distinct gold leads are in corpus v0.
  - Its answer occurs, as a whole word, in exactly one of them, the answer-bearing lead.
  - Its answer is a year or name-shaped.
- **Held out:** the pool excludes the 3,926 fresh-router ids and test 1's 800, drawn in a new seeded order.
- **No corrections:** this test is about retrieval and answering before any correction.

### The arms

All arms give the same reader (nemotron-mini, temperature 0, prompt v2) two leads from corpus v0.

| Arm | Candidates | Choice of two |
| --- | --- | --- |
| E | BM25, then one hop | BM25's top 1, then its out-link with the best BM25 score (test 1's E) |
| B-dense | BM25 top 100 | dense rerank, nomic-embed-text v1.5, cosine (test 1's B) |
| G-dense | BM25 top 100 plus the out-links of BM25's top 5 | the same dense rerank |
| B-cross | BM25 top 100 | cross-encoder rerank, BAAI/bge-reranker-base (fastembed) |
| G-cross | BM25 top 100 plus the out-links of BM25's top 5 | the same cross-encoder |
| W-dense | BM25's top N, N being that question's G pool size (revision 2) | the same dense rerank |
| W-cross | BM25's top N, as for W-dense | the same cross-encoder |

**What each pair isolates:**
- G against W, under the same reranker and with pools of the same size per question, isolates what the link graph
  adds over more BM25 candidates (revision 2, the fresh reviewer's finding 1). Before the run, on test 1's 800, BM25's
  top 126 held the answer-bearing lead for 51.6%, against the graph pool's 79.8%.
- G against B, under the same reranker, shows the graph pool against today's B, size difference included.
- Cross against dense, on the same pool, isolates the reranker.
- E is test 1's environment, kept for continuity.

### Measures, fixed before the run

- **Primary (revision 2):** answer-lead recall at two (the answer-bearing lead among the two leads given to the
  reader), G-dense against W-dense (size-matched), paired, with a 95% CI.
  - The graph earns its place here if the CI's lower end is above 0 and the point estimate is at least 5 points.
  - A CI straddling 0 is "no measured gain".
- **Power, stated before the run:** about ±3.7 points was test 1's paired half-width at n = 400. At n = 800 the
  standard error is about 1.3 to 1.9 points if G and W are positively correlated (they share BM25 and the reranker),
  and about 2.4 if independent. So a true gain of about 4 to 6.7 points is needed for 80% power to clear a lower end
  above 0. A smaller true gain may well read as "no measured gain".
- **Secondary:**
  - G-cross against W-cross, and G against B under each reranker;
  - each arm's answer-lead recall at two, both-gold at two, and pool recall (the lead anywhere in its candidates);
  - the reader's exact match and F1 on all 800, by arm, with paired CIs for G against B under each reranker;
  - whether recall gains reach exact match;
  - cost: candidates scored per question, embeddings and cross-encoder pairs computed, wall time, and model calls
    and tokens.
- **Read beside the results:** the arms' oracle ceiling, the share of questions whose pool holds the lead at all.

### What would count against

- G no better than W (size-matched) under either reranker, meaning the graph adds nothing more BM25 candidates don't.
- Recall gains that don't move exact match, meaning the reader, not retrieval, is the limit.
- A cross-encoder that wins alone, meaning a better reranker is the cheaper path.

Each is reported as found.

### Known limits, stated before the run

- **Construction bias:** HotpotQA built its bridge questions from linked article pairs, so a link hop is favoured by
  construction. A second question set not built from links (2WikiMultihopQA or MuSiQue) is test 2b.
- **Fixed pool rule:** the graph pool's out-links come from five seeds only. Wider expansions are not tried, so the
  result can't be tuned after it.
- **Cross-encoder truncation:** BAAI/bge-reranker-base reads 512 tokens, and about 10% of answer-bearing leads are
  longer (by word count, before the question is added). Nomic reads 8,192, so truncation biases cross against dense
  comparisons, but not G-cross against W-cross. The model is downloaded and its truncation settings read before the
  plan is fixed. The share of pairs truncated per arm is reported.
- **No strong graph baselines:** HippoRAG 2 and LightRAG need an LLM extraction pass over the corpus. That is out of
  reach for 7.2 million leads on this hardware, so they're left to a sub-corpus comparison, named here so the gap is
  visible.

## Code (after approval)

Test 1's exclusion reader expects a `rows` key, and test 1's plan file holds `questions`, so test 2 reads both (the
reviewer's finding 4).


The code extends `engram/experiments/northstar/` with `test2.py` and its tests: the draw, the five arms' candidate and
choice functions, the scoring, and `plan`/`run`/`rescore` as in test 1. Every run's answers are saved before
scoring, and scoring is tested against hand-made rows, including what each measure compares against, the check
test 1 lacked.
