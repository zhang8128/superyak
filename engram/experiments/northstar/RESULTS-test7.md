# North-star test 7: results

The question, from [docs/north-star.md](../../../docs/north-star.md) row 7: an environment that *keeps* where evidence
came from should protect a finite reasoner from being fooled by copies. How much of a kept provenance record's value can
a plain auditor recover by *inferring* which reports are independent? The spec is
[2026-11-22-north-star-test-7-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-7-design.md),
revision 3 with amendment 1, approved by a fresh reviewer after four checks. Everything the run used was fixed in
[PREREG-test7.md](PREREG-test7.md), pushed (1b4a96de, 17:46:13 UTC) before the run started. It's built on Tardis's
graded-blame fixture (93e08797, generator 867614fa).

## The run (2026-11-22, on the Mac)

- **When and how:** 17:46:22 to 18:08:26 UTC, exit 0, peak 1.4 GB under a 16 GB cap. It was single-threaded at nice 19,
  overlapping test 2's run.
- **What it covered:** 432 C/D cells and 72 A cells, 500 instances each.
- **The raw rows:** `~/Projects/superyak-data/northstar/test7/results.json` (530 MB, sha256 `c9453ae4…49ee`).
- **The summary:** `results/test7-summary-2026-11-22.json`, from `test7.py rescore` (sha256 `b45b5e8e…3743`).
- **An independent recomputation** of the primary and the secondaries, from the raw rows with separate code, matched
  the summary to six decimals.
- **Checks:** C and D's reports are identical on every instance, and P on C equals the oracle exactly (maximum
  difference 0.0).
- **Excluded:** 10.6% of D instances had no copied biased item to score, and were counted, as pre-registered.

## Results

Consensus error is in units of σ, pooled over the cells with each cell weighted equally. The primary's population is
all 432 C/D cells, since every one passed the 0.1σ ceiling gate.

| Measure | Point | 95% interval |
| --- | --- | --- |
| **S_I, the share of the record's value that inference recovers (primary)** | **0.0089** | 0.0076 to 0.0102 |
| S_P½, the share a record with half its chains missing recovers | 0.450 | 0.447 to 0.452 |
| The gap, I on D minus P on C | 1.093σ | 1.090σ to 1.097σ |
| The ceiling, N − O | 1.103σ | (pilot 1.111σ) |
| Inference at all, N − I on D | 0.0098σ | 0.0084σ to 0.0112σ |
| Do no harm, I − N in A, pooled | +0.0032σ | +0.0029σ to +0.0035σ (within ±0.05σ) |
| Do no harm at the high-bias corner | +0.0013σ | +0.0007σ to +0.0019σ (within ±0.05σ) |

- **Primary, as pre-registered: "the record can't be replaced by this inference"**, inference from the reported values
  alone. The interval's upper end, 0.010,
  is far under 0.5. The sensitivity set (the fixture's 158 cut cells) reads the same: S_I = 0.026 (0.024 to 0.028).
- **By copier noise τ and copied share q,** S_I is:
  - **0.098 at τ = 0.5 and q = 0.5,** low copier noise and much copied, the only regime where inference recovers
    anything, about a tenth;
  - 0.006 at τ = 0.5 and q = 0.25;
  - **slightly negative at τ = 1 and 1.5** (−0.008 to −0.022), where the auditor's few false collapses cost a little.
  - S_P½ is 0.44 to 0.46 in every τ and q.
- **An incomplete record against inference:** a record missing half its chains recovers 45% of the value, about fifty
  times what inference recovers, in every regime.
- **Do no harm passes:** the auditor's false collapses cost honest conclusions about 0.003σ, inside the band. The
  realised false-flag rate in A averaged 5.4% (worst cell 15.8%), against 5% calibrated.
- **"What would count against a conclusion":** against the truth, the auditor's "rests on dependent reports" flag found
  5% of the conclusions that rested on copied evidence (recall 0.05, precision 0.57). The kept record found 81% (recall
  0.81, precision 0.995).

## How to read it

- **What it shows:** on this fixture, copying that nobody declared is almost entirely *unrecoverable* by a plain
  auditor. Copying moves conclusions a lot (the oracle's gain is 1.1σ). A kept record recovers all of it by
  construction, and even a half-kept record recovers 45%. Inference recovers under 1%, and about 10% only where the
  copier adds little noise and copies much.
  - That's the essay's claim in a measured form, scoped: provenance has to be *kept* by the environment, because a
    reasoner can't rebuild it afterwards *from the reported values alone*.
  - **Scope (Rio Grande, all hands a03b7308):** the auditor saw only the reported values, where a copier shows only
    as agreement in error. Real copying usually leaves more: the same wording, the same citation list, a later date,
    the same rounding. An auditor reading those traces would likely recover more than 0.9%. So the result is
    **"value-only inference can't replace a kept record"**, and inference from richer traces is untested. Measure 3's
    real collections could probe it.
- **What it doesn't show:**
  - **P is the oracle by construction,** so the gap is an upper bound on a real record's worth. P½ is one step towards
    a real, imperfect record, not a model of one.
  - **One plain detector:** a stronger one could recover more where copying is visible at all (τ < √2). Above √2 a
    smallest-spread detector points the wrong way, and a two-sided detector was never tried.
  - **Planted data:** one bad source, one copier, Gaussian noise. Real copying can be partial, chained or transformed.
    Test 5's Measure 3, on real medical sources with a blind audit, is the next check against reality.
- **Where it moved the plan:** the design checks found this before the run, and the run measured it across the whole
  grid with tight intervals. The reviewers' three rounds and Tardis's read of the harness each changed what was
  measured: the detector, a primary that couldn't fail, and a population cut that biased the estimand.

## Reproduce

`test7.py plan` gives the plan byte for byte. `test7.py run --plan …` is the run, and `test7.py rescore --plan …
--results …` gives this page's numbers from the saved rows.
