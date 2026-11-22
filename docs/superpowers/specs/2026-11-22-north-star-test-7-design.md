# North-star test 7: kept provenance against inferred independence

Serenity, 2026-11-22, revision 3. Test 7 of [docs/north-star.md](../../north-star.md). It needs a fresh reviewer's
approval before any code (station law, section 3), and nothing runs until its plan is fixed in a commit. It is built on
Tardis's graded-blame fixture,
[2026-11-22-graded-blame-fixture-design.md](2026-11-22-graded-blame-fixture-design.md), revision 3 (93e08797),
approved after three checks. That spec fixes the fixture, its grid, its pilots, its seeds and its scoring rules, and
leaves test 7's auditor, comparator, margin, bootstrap and primary to this spec.

- **Revision 1 (d639aecb)** went to a fresh reviewer, who asked for a revision (R1 to R5, A1 to A4).
  - Its auditor took a median over all of a pair's shared items, so at copied shares of 0.25 and 0.5 the copying was
    outvoted (R1), and the auditor flagged the true copier in at most 4% of the reviewer's instances (R2).
  - The bias inflated the instance median it divided by (R5). So the false-flag rate in A swung from 1.3% to 10.2%
    with the unobservable bias (R3).
  - Its scale estimate confused a median with a mean (R4).
- **Revision 2 (c6c827f5)** fixed the statistic and the scale and reframed the primary. The same reviewer's re-check
  approved it with named changes. Its R1: P on C is the oracle by construction (93e08797's A3 makes `relation()`
  exact in C), so a primary of I_D − P_C is the ceiling minus the auditor's small gain, and would fire in nearly
  every kept cell before inference did anything.
- **This revision** makes the primary the share of the record's value that inference recovers, read with the gap
  beside it. It narrows the symmetry claim (A1), reports do-no-harm at the high-bias corner (A2), and adds an
  incomplete record.

## Why this test

Row 7 asks for "different routes through the same evidence, and an evidence auditor that asks which observations are
independent and what would count against a conclusion".
- **Routes:** routing questions by kind has already been measured, and it didn't pay, on three samples (#12). This
  spec doesn't reopen it.
- **The essay's claim** is that an environment which *keeps* where evidence came from protects a finite reasoner from
  being fooled by copies. Two reports that agree because one copied the other count as one. The alternative is a
  reasoner that has to *infer* independence after the fact. Test 5 built the kept form (`relation()`'s copied
  answer). Test 7 asks how much kept provenance is worth against the best plain inference, on the same reports.

## The mechanism, worked first

- **Why copying moves a conclusion:** take K = 4 on an item all four report. The median of [honest, honest, bad, copy
  of bad] is the mean of one honest report and one biased one, so it moves about halfway to the bias. Counting the
  pair once gives the median of [honest, honest, bad], which is honest. So kept or inferred independence shows in
  the consensus on items that are both biased and copied.
- **When undeclared copying can be seen at all:**
  - On a copied item, the pair's difference has noise τσ, against √2·σ for two independent reports. So with τ well
    under √2, copying shows on every copied item as unusually close agreement.
  - At τ = √2 the copied pair's differences have exactly an honest pair's spread (the re-check: medians 0.911 and
    0.910 over 2,000,000 draws). Copying then shows only on biased copied items, where the bias cancels within the
    pair, and at K = 4 an item all four report is symmetric: [honest, honest] against [bad, copy]. Nothing in the
    reports says which pair is the copy.
  - Above √2 the copied pair spreads *more* than an honest pair. So information exists, but a smallest-spread
    detector, this auditor's family, points the wrong way (the re-check's A1). A two-sided anomaly detector could
    flag the pair; this spec doesn't test one.
  - So in part of the grid this auditor can't recover what a kept record says.
- **Design-time checks** (not a run; design seeds, disjoint from any plan's; scripts in
  `engram/experiments/northstar/design/test7/`; `sim.py` is the first reviewer's toy fixture):
  - **The reviewer's statistic** (median over shared items) found the copier in 0% to 4% of instances. A residual
    correlation against the median of the other reports did no better, and flagged honest pairs in up to 100% of
    instances at b = 8, because the bad report shifts the others' consensus that both honest residuals are measured
    from.
  - **The statistic chosen below**, a pair's lower quartile, kept A's false-flag rate at 2% to 10% across b of 2 and
    8, against 0% to 35% for the median statistic. It found the copier in 20% to 32% of instances at τ = 0.5, q = 0.5
    and M = 60 with ρ = 0.9, and in at most 8% elsewhere. At τ = 1 or q = 0.25 it found it in at most 3%.
  - So inference recovers copying only where the copier adds little noise, copies much and shares many items. That
    shapes the primary.

## Design

### The fixture

As 93e08797 fixes it: conditions A (no copier), C (a declared copier) and D (the same copying, undeclared), from
shared base instances; its grid axes, pilots and cut; N = 500 instances per kept cell; and seeds from
`numpy.random.SeedSequence` keyed by cell and instance. **C and D have identical reports on every base instance**, and
differ only in whether each copied report names its source. That pairing is what the primary uses. This spec narrows
no cell: where inference fails is part of the result.

**Who builds it:** the fixture's generator follows 93e08797, and Tardis builds it. This spec's code (the auditor, the
arms and the scoring) is Serenity's, in Python against the generator's output. Each reads the other's before the plan
is fixed. Python, not Rust: it's an experiment harness on a numpy fixture.

### The consensus

Every arm takes each item's consensus as the median of the reports it counts.

### The auditor (inferred independence)

- **Its statistic:** for each pair of sources sharing at least 4 items, ℓ(i, j) is the 25th percentile over those items
  of (x_i − x_j)². The reference is ℓ̄, the median of ℓ over the instance's eligible pairs, and the pair's ratio is
  r(i, j) = ℓ(i, j) / ℓ̄.
  - A lower quartile reads a copied share of 0.25 or more, where a median is outvoted (R1).
  - Every pair's lower quartile comes mostly from unbiased items when s ≤ 0.5. So ℓ̄ is close to the honest level,
    and the bias barely moves the reference (R5).
  - It is scale-free, needs no σ, and uses no truth.
- **Its flag:** every pair with r below θ is marked dependent.
- **θ:** fixed on calibration instances of A, from a seed disjoint from the pilots' and the run's. That's 500 per
  combination of K, M and ρ, which an auditor can count, pooled over b and s, which it can't. θ is the 5th percentile
  of the smallest r per instance.
  - The plan records θ, and on the calibration seeds, the false-flag rate per (b, s) (R3).
  - The design check's spread was 2% to 10%. The realised rate on the run's A instances is reported per cell.
- **Its collapse:** on the items both members of a flagged pair report, their two reports become one, their mean.
  Every other report is kept. That follows 93e08797's rule that collapse uses the method's own answer, never the
  truth.
- **"What would count against a conclusion":** for each item, the auditor reports:
  - its consensus;
  - the number of independent reports supporting it after collapse;
  - whether the conclusion *rests on dependent reports*: whether undoing the collapse moves the consensus by more than
    0.5ŝ.

  ŝ = √(ℓ̄ / (2 × 0.1015)), since for two independent reports with noise σ, the 25th percentile of (x_i − x_j)² is
  2σ² × 0.1015, the χ²₁ lower quartile (R4).

### The arms

| Arm | What it counts | Run on |
| --- | --- | --- |
| N, naive | every report | A, C, D (N on C equals N on D, the reports being identical) |
| P, kept provenance | every report, with pairs `relation()` answers copied collapsed on their copied items. Equal to O by construction | C |
| P½, an incomplete record | as P, but a seeded half of the copied reports carry no chain, so only the rest collapse | C |
| I, inferred | every report, with the auditor's flagged pairs collapsed | A, C, D |
| O, the oracle | every report, with the truth's copier pair collapsed on its copied items | C and D (equal) |

### Measures, fixed before the run

- **The scored items:** in C and D, the *copied biased items*, those where the bad source's report carries the bias
  and the copier copied it, per the truth. The truth only selects and scores. An instance with no scored item is
  excluded and counted.
- **Consensus error:** |consensus − true value| / σ, averaged per instance over its scored items.
- **Primary, the share inference recovers:** on D, S_I = (N − I) / (N − O), as a ratio of the kept cells' pooled mean
  gains, each cell weighted equally. It's the share of a kept record's value that the auditor gets back without one.
  P on C equals O by construction, so S_I is also inference's share of what the record gives.
  - The bootstrap resamples base instances within cells: 10,000 replicates, seed 2026112207, percentile 95%
    intervals. The ceiling rule keeps the denominator at 0.1σ or more.
  - **The readings, fixed now:**
    - **"Inference substitutes for the record"** if the interval's lower end is 0.8 or more.
    - **"The record can't be replaced by this inference"** if the upper end is under 0.5.
    - **"Inference recovers part"** otherwise, with the interval stated.
  - **Beside it, every time it's read:** the gap Δ = I_D − P_C in σ, with its interval. Δ is mostly the ceiling the
    cut already guaranteed, so it's never read alone as evidence the auditor was tested hard (the re-check's R1).
  - **Expected, from the design-time checks:** S_I is small, under about 0.2, in most kept cells. The run measures it
    over the fixture's real kept grid, with intervals. If inference does better than the toy suggested, the readings
    say so.
- **Do no harm, A (no copier):** I against N, consensus error over all items the bad source reports. The interval
  for I − N must lie within ±0.05σ. If it doesn't, false collapses cost honest conclusions, and that's reported as a
  failure.
  - It's reported pooled and again at the high-bias corner (K = 6, M = 60, ρ = 0.9, b = 8), where the design check's
    false-flag rate reached 10% (the re-check's A2).
- **Secondary:**
  - **An incomplete record against inference:** S_P½ = (N − P½) / (N − O) on C, beside S_I, paired by base
    instance. It shows whether a record half missing still beats inference.
  - **Per cell:** S_I and S_P½ where that cell's N − O is at least 0.1σ, descriptive only.
  - **Inference at all:** I against N on D, paired, with its interval. "The auditor helps" if it excludes 0 in I's
    favour.
  - **Detection, D:** the share of instances with the copier pair flagged; the share with an honest pair flagged; and
    the number of honest pairs flagged per such instance (A4). In A: the realised false-flag rate per cell, against
    the 5% fixed on calibration (A1).
  - **Blame,** with 93e08797's rules: the bad source ranked first by mean absolute deviation from each arm's
    consensus, ties as 1/t, and a copier first scored apart.
  - **"What would count against":** against the truth, where the oracle's collapse moves the consensus by more than
    0.5σ, the "rests on dependent reports" flag's recall and precision in D, and P's equivalent in C.
  - **Where inference fails:** every measure by τ and q, so the regime where kept provenance is the only way is
    visible.

### The ceiling, counted before the plan is fixed

On the fixture's pilot seeds, with no auditor run: the oracle's gain N − O on copied biased items in each kept cell,
and the share of those items whose naive consensus is off by more than 0.5σ.
- **If the pooled N − O is under 0.1σ,** double counting barely moves these conclusions, neither kept nor inferred
  provenance can matter, and the test stops with that as its result.
- The counts go in the plan, beside θ, the calibration false-flag rates and the auditor's pilot detection rates per
  kept cell.

### What would count against

- **Kept provenance against inference:** S_I's lower end at 0.8 or more. Then inference substitutes for the record,
  and keeping provenance isn't worth its cost on this kind of data.
- **Kept provenance against the ceiling:** P short of O in C. Then the record doesn't carry into the conclusion.
- **Do no harm:** I worse than N in A. Then the auditor costs honest conclusions.

Each is reported as found.

### Known limits, stated before the run

- **Planted data:** one bad source, one copier, Gaussian noise. Real copying can be partial, chained or transformed.
  Real crossings are counted when test 5's Measure 3 runs.
- **One plain detector:** the lower-quartile pair statistic. A stronger one could narrow Δ where copying is visible
  at all. Where τ ≥ √2 at K = 4, the symmetry argument above says no detector can.
- **P is the oracle by construction:** declared chains are exact in C. Real records can be wrong or missing. So Δ is
  an upper bound on what kept provenance is worth. P½ is one step towards a real record, not a model of one.
- **The median consensus only.**
- **Routes,** the row's other half, stay with #12's result.

## Code (after approval)

`engram/experiments/northstar/test7.py` and its tests:
- the auditor's statistic, flag, calibration, collapse and ŝ;
- the five arms, P½'s missing chains drawn from the instance seed;
- the scoring, tested against hand-made instances that pin which items each measure scores and which answer it
  compares against;
- `plan` (the ceiling counts, θ, calibration rates, the kept cells and seeds), `run` and `rescore`, as tests 1 and 2.
