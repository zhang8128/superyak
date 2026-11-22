# North-star test 1: one environment, end to end, with a correction

Serenity, 2026-11-22. Test 1 of [docs/north-star.md](../../north-star.md), Andy's north star of that day. Needs a fresh
reviewer's approval before any code (station law, section 3). Nothing here runs until its run is fixed in a commit.

## The question

Given a frozen body of evidence, can an agent in an environment that keeps provenance give answers with their
sources, and then, when a source is corrected, revise exactly the answers that rested on it, keep what it believed
before, and spend less doing so, than the same model with a strong conventional retrieval pipeline?

## What exists (all on main after train 1144b, or on its branch)

- Corpus v0: the leads of 7,245,115 English Wikipedia articles of 2026-11-01, frozen with a digest (`atlas/workbench/research_corpus.py`).
- `corpus-index` (Rust): BM25 and the link graph over corpus v0, 0.09 s a question (`engram/native/corpus_index`).
- Atlas's store: claims with evidence citing sources, `retraction_impact(sources)` and `history_as_of(record, at)` (#9).
- Local models through Ollama on the Mac: nemotron-mini (about 4B), qwen3.6:27b-mlx; prompt v2 from `hotpot_smoke`.
- HotpotQA's distractor train split (train-00000, revision 1908d6af), whose fresh draws nothing here has scored for answers.

## Design

### Questions and corrections

- **Questions:** 300 drawn by a new seed from train-00000, excluding the 4,000 ids of the two fresh router samples.
  Bridge questions only, whose answer is a span that occurs in exactly one of the two gold articles' leads in corpus v0
  (a correction must change the answer and nothing else). Comparison and yes/no questions are left out of this run.
- **The ceiling, counted before the run:** how many of the draw qualify, and in how many the gold lead holds the answer
  once. The run stops at this count if fewer than 200 qualify, and the spec is revised.
- **A correction:** in the gold lead that holds the answer, its occurrences are replaced by a substitute, the answer of
  another drawn question of the same answer type (a year for a year, a name for a name, by a fixed rule on the
  string). The corrected lead is the source's new revision; the old one is retracted. Expected answer after: the
  substitute. Half the questions, chosen by seed, are corrected; the other half are controls whose sources don't
  change.

### The two systems, with one model and one evidence budget

- **Environment (E):** the agent searches `corpus-index` (BM25, then one link hop, as in the open test), reads at most
  two leads, answers, and records the answer as an Atlas claim whose evidence cites each lead it used (source id =
  page id plus revision). After the corrections, `retraction_impact(retracted revisions)` names the claims that lost
  support; only those questions are asked again, with the corrected corpus. The earlier claims are withdrawn, not
  deleted, so `history_as_of` before the correction still returns them.
- **Baseline (B):** BM25's top 100 from the same index, reranked by a dense embedder (nomic-embed-text, cosine), top 2
  leads to the same model with the same prompt. After the corrections, B is run two ways and both are reported:
  B-all re-asks every question (fresh, full cost), and B-cache serves its earlier answers unless a question is
  re-asked (what a pipeline without provenance knows to do).
- Same model (nemotron-mini, temperature 0), same prompt, two leads each, same corrected corpus.

### Measures, fixed before the run

- **Before the correction:** exact match and F1 on all 300; source support (both gold leads among those cited).
- **After, on the corrected half:** exact match against the substitute; stale answers (the old answer still given).
- **After, on the controls:** answers unchanged where they were right (a revision must not disturb what didn't depend
  on it).
- **History:** for E, `history_as_of` just before the correction returns the earlier claim for every corrected question.
- **Cost:** model calls and tokens before and after the correction; wall time; and the cost of building E's records
  (Atlas writes), counted in.
- **Primary:** on the corrected half, E's exact match after the correction against B-cache's, paired, with a 95% CI.
  Secondary: E against B-all on the same, and E's after-correction model calls against B-all's.

### What would count against

- E no better than B-cache after the correction means provenance didn't help with this model.
- E needing as many calls as B-all means the targeting saved nothing.
- Controls disturbed in E means the impact rule is too broad.
- Each is reported as found, in RESULTS and on #8 and #9.

## Out of scope for this run

Real retractions (Retraction Watch with PubMed) come next, once this harness works. Strong graph baselines (HippoRAG 2,
LightRAG) are test 2. A large model is test 3. Nothing clinical.

## Code (after approval)

`engram/experiments/northstar/test1.py` with its tests: the qualifying rule, the correction rule, the claim records,
the impact step, both systems' loops on hand-made fixtures, and the scoring. Glue in Python; the index is the Rust
crate. Fixed-seed run, results file in `results/`, RESULTS section, a line on #8 and #9.
