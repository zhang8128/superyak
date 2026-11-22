# North-star test 7: the pre-registration

Committed before the run, 2026-11-22. The spec is
[docs/superpowers/specs/2026-11-22-north-star-test-7-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-7-design.md),
revision 3, approved by a fresh reviewer after three checks (79ebcd91), with amendment 1 approved after a fourth (21d7521d). It is built on Tardis's graded-blame fixture
spec (93e08797) and generator (867614fa, read by Serenity in all hands 0b0c4b61). Tardis read this harness before
this commit, as the spec asks: all hands f7aebc90, read at 7bca8635, with its six required changes confirmed at 9c66d32c in 0d152560. Nothing below changes after the run starts. A finding during the run is
reported; it doesn't change this page.

## Inputs, fixed

| What | Value |
| --- | --- |
| Code | `engram/experiments/northstar/test7.py` at 9c66d32c (124 tests; 324 with the fixture's and test 1's) |
| Fixture | `engram/experiments/northstar/graded_fixture.py` at 867614fa: σ = 0.05, seed root 20261123, C and D with identical reports |
| Plan | `results/test7-plan-2026-11-22.json`, sha256 `1bc35b361dbfe1ffde674c9aa18ee78fa94fdc5b4369893c9eb926d3d4b8be6a`, 423,963 bytes |
| Seeds | calibration 2026112208, pilot 2026112209, run 2026112210; bootstrap 2026112207 |
| Grid | K 4, 5, 6; M 20, 60; ρ 0.5, 0.9; b 2, 4, 8; s 0.25, 0.5; and in C and D, τ 0.5, 1, 1.5 and q 0.25, 0.5 |
| The primary's population (amendment 1) | every C/D cell whose pilot N − O ≥ 0.1σ: all 432 of 432 (the smallest 0.1009σ), so the composition is exactly uniform over K, b, s, τ and q |
| Sensitivity set | the fixture's cut, 100 pilot instances per cell kept between 1.5 times chance and 0.9: 158 C/D cells (τ 0.5: 105, τ 1: 52, τ 1.5: 1) |
| Do-no-harm cells | A on the primary's 70 base cells plus the high-bias corner (K6, M60, ρ0.9, b8, both s): all 72 |
| N | 500 instances per kept cell, per condition |
| θ | per (K, M, ρ), from 500 calibration A instances, balanced across (b, s): 0.0100 (K6, M20, ρ0.5) to 0.1885 (K6, M60, ρ0.9) |

## Seen before this commit, not results

- **Calibration false flags per (b, s):** from 0 to 14.5%, with a mean of 5.0%, highest at s = 0.5. This is the bias
  dependence the spec's first reviewer predicted (R3). Each figure comes from about 83 instances, and do-no-harm in A
  guards it.
- **The ceiling, on the pilot seeds:** pooled N − O is 1.111σ over all 432 cells (per cell, 0.10σ to 3.49σ), and
  1.110σ over the sensitivity set. So the ceiling rule doesn't stop the test.
- **The auditor on the pilot seeds,** over the sensitivity set's 158 cells: it flags the true copier pair in a median of
  2% of instances per cell (mean 4%, best cell 40%), and an honest pair in a median of 3% (worst cell 10%). The full
  grid adds the cells the cut dropped as too easy, where it may do better.
- **So the expected reading** was "the record can't be replaced by this inference", as the spec stated. With the full
  grid's easy cells in, the run decides it. No pilot number is read as a result.

## Arms and measures

As the spec fixes them, unchanged:
- **The arms:** N, P (kept provenance, equal to O by construction), P½ (half the chains missing), I (the auditor) and O
  (the oracle).
- **Primary:** S_I = (N − I) / (N − O) on D, over the primary's population (all 432 C/D cells), each cell weighted equally. The readings:
  - "inference substitutes for the record" if the interval's lower end is 0.8 or more;
  - "the record can't be replaced by this inference" if its upper end is under 0.5;
  - "inference recovers part" otherwise.

  The gap Δ = I_D − P_C is always read beside it, never alone.
- **Do no harm:** in A, I against N within ±0.05σ, pooled and at the high-bias corner.
- **Secondary:** S_P½; inference at all; detection; blame; "rests on dependent reports"; and every measure by τ and q.

## The command

On the Mac, from `engram/`, about 21 minutes plus writing the output:

```
uv run --locked --extra dev python -m experiments.northstar.test7 run \
  --plan experiments/northstar/results/test7-plan-2026-11-22.json \
  --out ~/Projects/superyak-data/northstar/test7/results.json
```

The result goes into RESULTS-test7.md and onto the north-star page, whatever it is.
