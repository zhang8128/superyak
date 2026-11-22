# North-star test 2: results

The question, from [docs/north-star.md](../../../docs/north-star.md) row 2: does the environment's link graph add to a
strong conventional reranker, against the same number of plain keyword candidates? The spec is
[2026-11-22-north-star-test-2-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-2-design.md),
revision 3, approved by a fresh reviewer. Everything the run used was fixed in [PREREG-test2.md](PREREG-test2.md), pushed
(8d07a1c9, 11:49:04 UTC) before the run started.

## The run (2026-11-22, on the Mac)

- **When and how:** 11:49:13 to 21:41:08 UTC, exit 0, peak 13.3 GB under the 24 GB cap, nice 10. Bridge took 7.40 hours
  and the comparison stratum 2.47. It was longer than the smoke's 8.6-hour estimate.
- **The overlap:** test 7's single-threaded run overlapped from 17:46 to 18:08 UTC, so wall-time costs in that window are
  slightly inflated.
- **The saved rows:** `results/test2-run-2026-11-22.json` (sha256 `cb8a0f2e…3b2c`), with every answer, both leads and
  each row's measures.
- **An independent recomputation** of the primary and the key secondaries, from the rows with separate code, matched the
  harness's summary exactly.

## Results, bridge questions (800)

Rates are each arm's share of questions; differences are paired, in points, with 95% intervals.

| Arm | Answer lead in the two | Both gold leads in the two | Pool holds the lead | Exact match | Rerank s/question |
| --- | --- | --- | --- | --- | --- |
| E (test 1's environment) | 33.1% | 23.1% | 33.1% | 44.1% | 0 |
| B-dense (test 1's baseline) | 31.0% | 14.9% | 45.5% | 42.9% | 3.1 |
| W-dense | 31.2% | 15.2% | 47.0% | 42.9% | 3.9 |
| G-dense | 36.0% | 20.4% | 78.6% | 46.0% | 5.0 |
| B-cross | 36.9% | 23.5% | 45.5% | 47.6% | 5.4 |
| W-cross | 37.8% | 24.6% | 47.0% | 47.6% | 7.0 |
| **G-cross** | **47.1%** | **35.1%** | 78.6% | **53.0%** | 7.6 |

- **Primary, as pre-registered: "measured gain under the margin."** G-dense against W-dense on answer-lead recall at two
  is **+4.75 points (3.16 to 6.34)**. The interval is clear of zero, but the point estimate is just under the 5-point
  margin.
  - **It sits on its margin:** in 65 of the 800 questions, by this page's normalisation (a reader counted 68), the other
    gold lead's title is itself the answer. Under an either-lead rule, the primary is +5.0 (3.37 to 6.63), which would
    read "earns its place". The pre-registered rule stands at +4.75. This is how close it is, not a different result.
- **Secondary:**
  - **G-cross against W-cross: +9.38 points (7.21 to 11.54), "earns its place".** With a cross-encoder, the graph's
    candidates gain twice as much.
  - G-dense against W-dense on both-gold at two: +5.12 (3.56 to 6.69).
  - **Recall reaches answers:** G-dense against B-dense on exact match is +3.12 points (1.46 to 4.79). G-cross gives
    53.0% exact match against B-dense's 42.9%.
  - **The reranker matters on the same pool:** cross beats dense, B 36.9% against 31.0%, and G 47.1% against 36.0%.
  - **A cross-encoder alone doesn't win:** W-cross against G-dense is +1.75 (−1.15 to 4.65). So "a better reranker is
    the cheaper path", one of the pre-registered counts against, isn't found. It's the graph with a cross-encoder that
    wins.
- **The pool against the choice:** G's pool holds the answer-bearing lead 78.6% of the time, against W's 47.0% at the
  same size (the pre-spec measure on test 1's questions was 79.8% against 51.6%). Dense reranking turns that 31-point
  pool advantage into 4.75 points at two, and the cross-encoder into 9.4. The loss is still in choosing the two.
- **Cost:**
  - Reranking G-cross takes 7.6 s a question, against 3.1 for B-dense, 2.5 times as long, with about 128 pairs scored
    against 100 embeddings.
  - The reader's calls are about 0.1 to 0.3 s each.
  - The cross-encoder truncated 6.5% of G-cross's pairs, against 1.9% and 2.1% for B-cross and W-cross, since linked
    pages run longer.

## Results, the comparison stratum (300), reported apart

| Arm | Answer lead in the two | Both gold leads in the two | Exact match |
| --- | --- | --- | --- |
| E | 53.3% | 0.7% | 75.7% |
| B-dense | 89.3% | 70.3% | 84.0% |
| W-dense | 90.0% | 72.0% | 84.3% |
| G-dense | 91.3% | 73.0% | 84.7% |
| B-cross | 89.7% | 70.0% | 85.0% |
| W-cross | 90.3% | 71.7% | 84.7% |
| G-cross | 91.3% | 74.0% | 85.7% |

- **The pre-registered ceiling rule passes:** W-dense's both-gold at two is 72%, under 90%.
- **But the graph added almost nothing to compare** (Rio Grande, all hands 37677c19). G's pool holds the answer lead
  94.7% of the time against W's 93.3%, and B's 92.7%, and W-dense's answer-lead recall is already 90.0%. A comparison
  question names both entities, so keyword search finds them, and links add few new candidates. The ceiling rule tested
  the both-gold rate, while the mechanism that matters here is the pool.
- **Both-gold first: no measured difference,** G-dense against W-dense +1.0 (−1.53 to 3.53). On answer-lead recall it's +1.33
  (−0.51 to 3.18), and G-cross against W-cross +1.0 (−0.96 to 2.96).
- **So this stratum can't separate construction from usefulness.** The graph adds little to these pools, so there was
  little for it to help with. It's not evidence that the graph fails where no link was planted. Test 2b, on a set not
  built from links, still has to carry the claim.
- **E** gets only 0.7% both-gold here, since a comparison's second entity isn't reached by a link from the first.

## How to read it

- **What it shows:**
  - On HotpotQA's bridge questions, the link graph's candidates add measurably over the same number of keyword
    candidates: 4.75 points under dense reranking, just short of the pre-registered margin, and 9.4 points under a
    cross-encoder.
  - The best arm, graph candidates with a cross-encoder, raises exact match from test 1's baseline of 42.9% to 53.0%,
    at about 2.5 times the reranking time.
- **What it doesn't show:** whether the graph helps where nothing planted the link.
  - HotpotQA's bridge questions were built by following links, so the bridge gain is open to that construction.
  - The comparison stratum was meant to test it, but there the graph adds almost nothing to the pool (94.7% against
    93.3%), so it can't separate construction from usefulness either way.
  - **Test 2b, on a question set not built from links (2WikiMultihopQA or MuSiQue), has to carry the claim.**
- **Limits a reader noted, not rechecked here:** the draw keeps only answer leads with one supporting sentence, which
  is narrower than the spec's wording; and the tests pinned each scorer but not the summary's pairing (now pinned; see
  the test commit after this one).
- **For test 3 (small against large):** the environment arm should be graph candidates with a cross-encoder, the best
  measured here, with test 2b's caution beside it.

## Reproduce

`test2.py plan` gives the plan byte for byte. `test2.py run --plan … --full` is the run, and `test2.py rescore --results
… --plan …` gives this page's numbers from the saved rows.
