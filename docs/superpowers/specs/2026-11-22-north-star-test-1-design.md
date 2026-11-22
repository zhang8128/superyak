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

## Design (revision 3: the fresh reviewer's six findings, R1 to R6, power, and the re-check's three changes)

### Questions and corrections

- **Pool:** HotpotQA train-00000 less the 3,926 ids of the two fresh router samples (41,298 questions).
- **Qualifying rule:** a bridge question whose two gold leads are both in corpus v0, whose answer occurs, as a whole
  word, in exactly one of them, and whose answer is a bare four-digit year or name-shaped (every word capitalised,
  letters, spaces, periods, hyphens and apostrophes only). The re-check found a third of otherwise qualifying answers
  are dates, amounts, counts or common-noun phrases, which a year-or-name substitute would garble. Those are left out,
  not mis-substituted. Of the reviewer's 200 fresh draws, 59 qualify this way (about 30%).
- **Draw:** the pool in an order fixed by a new seed, taking the first **800 that qualify**, about 2,700 draws. The count
  of draws needed is reported. The run needs at least 500 qualifying; below that it stops and the spec is revised.
- **Power:** half are corrected, so about 400 paired questions. With 20% discordant pairs that gives a 95% interval
  about ±4.4 points on a paired difference. That's close to the 5-point margin, so an interval that straddles the
  margin is reported as borderline, not as a pass or a fail, and the follow-up run doubles N. That's stated before the
  run, not tuned after it.
- **A correction:** in the gold lead that holds the answer, each whole-word occurrence is replaced by a substitute: the
  answer of another qualifying question of the same class (a year for a year, a name-shaped answer for a name-shaped
  one), never equal to the original. Half the 600, chosen by seed, are corrected; the others are controls.
- **The corrected corpus (R5):** corpus v0 stays frozen. The corrections are an overlay file, one row per corrected page
  with its old and new text, digested. A second `corpus-index` is built from corpus v0's export with the overlay
  applied, and its sha256 is recorded. Reading a lead after the correction goes through the overlay.

### One revision, one source (R4)

Atlas's sources are immutable, and `retraction_impact` only reads. So test1.py holds a convention, and its tests check it.
- Each lead revision is its own source, `wiki:<page id>@<revision>`.
- A correction adds the new revision as a new source.
- The questions to ask again are exactly the claims `retraction_impact([old revisions])` names. Each is then withdrawn
  with `set_status(..., "withdrawn", reason, "test1")`, never deleted.
- A test fails if a correction ever edits a source in place.

### The arms, with one model and one evidence budget

- **Environment (E):** the agent searches `corpus-index` (BM25, then one link hop, as in the open test), reads at most
  two leads, answers, and records the answer as an Atlas claim citing each lead it used. After the corrections it asks
  again only what `retraction_impact` names, on the corrected index.
- **B-all:** BM25's top 100 from the same index, reranked by a dense embedder (nomic-embed-text, cosine). The top two
  leads go to the same model with the same prompt. After the corrections every question is asked again on the
  corrected index.
- **B-cache, a floor only:** B's earlier answers, never asked again. It shows what a pipeline without provenance gives
  if nothing triggers a re-ask (R2).
- **Closed book (R3):** after the corrections, the corrected half asked with no evidence. This counts what the model
  answers from memory, so a stale answer from memory isn't read as a failure of provenance.
- **No leakage (R6):** a re-ask prompt holds the question and the retrieved leads only. It never holds an earlier
  answer or a withdrawn claim, and a test asserts that.
- Same model (nemotron-mini, temperature 0), same prompt, two leads each.

### Measures, fixed before the run

- **Primary (R2), two parts, on the corrected half:**
  1. Exact match after the correction, E against B-all, paired, with a 95% CI.
  2. After-correction model calls, E's against B-all's.

  E succeeds if it is within 5 points of B-all's exact match while using under 60% of its calls. The interval is
  reported either way.
- **Read beside the primary:** the retrieval gap before the correction, meaning each arm's source support and exact
  match on all 800. E's evidence path (BM25 and one hop) may simply retrieve less than B's dense rerank. Then a miss
  reads as a retrieval gap, not as provenance failing, and the two are reported apart.
- **Targeting:** of the corrected questions, how many E asks again (its claim cited the corrected lead); of the
  controls, how many it asks again (should be none).
- **Before the correction:** exact match and F1 on all 800; source support (both gold leads among those cited).
- **Stale answers:** after the correction, how often each arm still gives the old answer, read beside the closed-book
  arm's.
- **Controls:** answers unchanged where they were right.
- **History:** for E, `history_as_of` just before the correction returns the earlier claim for every corrected question.
- **Cost:** model calls, tokens and wall time per arm, plus the cost of building E's records and the corrected index.

### What would count against

- E more than 5 points under B-all on the corrected half.
- E needing about as many calls as B-all.
- Controls asked again or disturbed.
- Most stale answers matching the closed-book arm, meaning memory rather than context decides.

Each is reported as found, in RESULTS and on #8 and #9.

## Out of scope for this run

Real retractions (Retraction Watch with PubMed) come next, once this harness works. Strong graph baselines (HippoRAG 2,
LightRAG) are test 2. A large model is test 3. Nothing clinical.

## Code (after approval)

`engram/experiments/northstar/test1.py` with its tests: the qualifying rule, the correction rule, the claim records,
the impact step, both systems' loops on hand-made fixtures, and the scoring. Glue in Python; the index is the Rust
crate. Fixed-seed run, results file in `results/`, RESULTS section, a line on #8 and #9.
