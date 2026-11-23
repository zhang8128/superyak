# North-star test 1: results

The question, from [docs/north-star.md](../../../docs/north-star.md): when a source is corrected, can an environment
that keeps provenance revise exactly the answers that rested on it, keep the earlier belief, and spend less doing so
than a strong conventional pipeline? The spec is
[2026-11-22-north-star-test-1-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-1-design.md),
revision 4, approved by a fresh reviewer after four rounds. Everything the run used was fixed in
[PREREG-test1.md](PREREG-test1.md) and pushed (03efe463, 07:03:55 UTC) before the run started.

## The run (2026-11-22, on the Mac)

- **Attempt 1** (07:04 to 07:06 UTC) died on its first dense rerank: `No module named 'numpy'`. It was launched in a
  bare uv environment, not engram's. No answer was scored. Its directory is kept as `test1-attempt1-no-numpy`.
- **Attempt 2** (07:07 to 08:54 UTC, exit 0, peak 7.4 GB under a 24 GB cap) ran in engram's environment. The plan,
  code, index, model and measures were all as pre-registered.
  - The corrected index: 7,245,115 docs, 3,585,602 terms, built in 312 s.
  - Calls after the correction: E 137 on the corrected half (139 in all), E-all 800, B-all 1,600, closed book 400.

## A scoring bug, found before any result was posted

The harness scored every answer given after the correction against the question's *original* answer. The spec says
the expected answer after a correction is the *substitute*. So the run's own summary measured staleness on the
corrected half, the opposite of the pre-registered measure. The tell was B-cache, which never re-asks: its "exact
match after" equalled B-all's exact match before (161 of 400).

- The answers themselves are unaffected and all saved. The pre-registered measure was applied to them with no new
  model calls: `score_after` now scores a corrected question against its substitute and a control against its
  original, and a test that failed before the fix holds it (a61b9868, 105 tests).
- `test1.py rescore` recomputes the whole summary from the saved answers.
- The lead computed the numbers below independently first; the fixed code's `rescore`, run blind, gave the same
  numbers on every arm, class and count.
- The per-question rows are in `results/test1-run-2026-11-22.json` (sha256 `d44eee13…6de62`). The run's original
  summary, with the bug, stays in the run directory beside them.

## Results

After the correction, on the 400 corrected questions. **Right** means it gives the substitute; **stale** means it
gives the old answer.

| Arm | Right | Stale | Calls after the correction |
| --- | --- | --- | --- |
| E: BM25 and one hop, re-asks only what `retraction_impact` names | 73 (18.2%) | 75 | 137 |
| E-all: E's retrieval, re-asks every question | 73 (18.2%) | 75 | 400 |
| B-all: BM25 top 100 with dense rerank, re-asks every question | 66 (16.5%) | 72 | 400 |
| B-cache: B's earlier answers, never re-asked | 0 | 161 | 0 |
| Closed book: no evidence | 0 | 69 | 400 |

- **Primary, as pre-registered: succeeds.**
  - E against B-all: +1.75 points of exact match (95% CI −1.95 to +5.45), within the 5-point margin.
  - E used 137 calls, 34% of B-all's 400, under the 60% bar.
- **Provenance alone, E against E-all: identical on every one of the 400** (CI 0.0 to 0.0).
  - Asking again the 263 corrected questions whose cited sources hadn't changed recovered no right answer.
  - So on corrections to cited sources, targeting by provenance lost nothing and saved two-thirds of the calls.
  - **Scope (Rio Grande, all hands 230fbbc3):** every correction here changes a document a question already cites. A
    question citing none of them could change only if its retrieval moved, so "identical" largely follows from how
    the corrections were planted. The corrected index did shift BM25's statistics, and no answer changed, but that
    is weak evidence. Targeting's real failure mode is a correction that makes a document relevant to a question that
    never cited it, and this test doesn't exercise it. The real-retractions test should.
- **By class:**
  - **year, 67 questions:** +4.48 (CI −6.09 to +15.05), borderline;
  - **person, 100 questions:** 0.0 (CI −8.36 to +8.36), borderline;
  - **other name, 233 questions:** +1.72 (CI −2.58 to +6.01), succeeds;
  - **clean classes (year and person, the substitutions that keep their kind), 167 questions:** +1.80 (CI −4.75
    to +8.34), succeeds.
  - Each class alone is too small for a tight interval, as the spec's power note warned.
- **Controls:** none of the 400 changed. All 173 that were right before stayed right.
- **Targeting:** E asked again 137 corrected questions and 2 controls. The 2 controls' answers had cited a page that
  was corrected for another question, so their evidence did change, and asking again was right; their answers didn't
  change. The spec's "controls asked again: should be none" was too narrow.
- **History:** for every corrected question E asked again, `history_as_of` just before the correction returns the
  earlier claim. The claim was withdrawn, not deleted.
- **The retrieval gap before the correction** (all 800, exact match against the original answer):
  - E 359 (44.9%) and B-all 334 (41.8%);
  - both gold leads among the two used: E 22.8%, B-all 15.5%;
  - at least one: E 69.4%, B-all 79.9%.
  - The re-check feared B's dense rerank would out-retrieve E and confound the primary; it didn't.

## How to read it

- **What it shows:** on corrections to cited sources, provenance makes updating cheaper at no loss.
  - Knowing which answers rest on a corrected source let E ask again a third of the questions and match both
    re-asking everything with its own retrieval and a stronger conventional pipeline.
  - That's the efficiency half of the north star's claim, measured at 400 corrections.
- **What it doesn't show:** that the environment makes the model better at absorbing corrections. Every arm gives
  the corrected fact for only about 18% of corrected questions. The reason is mostly retrieval: the answer-bearing
  lead was among E's two for 137 of 400 (34%), and among B-all's for 132 (33%).
  - When the corrected lead was in front of it, E gave the substitute 73 times in 137 (53%).
  - The closed-book arm gave no substitute, so memory doesn't supply the new fact. It gave the old answer for 69,
    a floor on how much staleness memory explains.
- **The stated limits held, and one was worse than the sample read.** Inside "other name" a substitute can change
  kind. The overlay holds, for example, "Alan Mathison Turing … was an Miss Russia mathematician", where the answer
  "English" took a name. That may cost the model's uptake; it costs every arm alike.
- **So the next tests aim at the bottleneck:**
  - retrieval of the answer-bearing evidence (test 2's stronger baselines);
  - a cleaner substitute rule (demonyms out);
  - real retractions, where nobody planted the change.

## Reproduce

`test1.py plan` (no model calls) gives the plan byte for byte. `test1.py run --plan … --full` is the run.
`test1.py rescore --results … --plan …` gives this page's numbers from the saved answers.
