# North-star test 7: an evidence auditor that knows which observations are independent

Serenity, 2026-11-22, revision 1. Test 7 of [docs/north-star.md](../../north-star.md), board item for test 7. It
needs a fresh reviewer's approval before any code (station law, section 3), and nothing runs until its plan is fixed
in a commit. It is built on Tardis's graded-blame fixture,
[2026-11-22-graded-blame-fixture-design.md](2026-11-22-graded-blame-fixture-design.md), revision 3 (93e08797),
approved after three checks. That spec fixes the fixture, its grid, its pilots, its seeds and its scoring rules, and
leaves test 7's auditor, comparator, margin, bootstrap and primary to this spec.

## Why this test

Row 7 asks for "different routes through the same evidence, and an evidence auditor that asks which observations are
independent and what would count against a conclusion".
- **Routes:** routing questions by kind has already been measured, and it didn't pay, on three samples (#12). This
  spec doesn't reopen it.
- **The auditor is the open half.** The essay's claim is that an environment which knows where evidence came from
  keeps a finite reasoner from being fooled by copies: two reports that agree because one copied the other count as
  one. Test 5 built the declared form of that (`relation()`'s copied answer). Test 7 asks whether it changes a
  conclusion, and whether an auditor can find copying that nobody declared.

## The mechanism, worked first

- **Why copying moves a conclusion:** take K = 4 on an item all four report. The naive median of [honest, honest,
  bad, copy of bad] is the mean of one honest report and one biased one, so it moves about halfway to the bias.
  Counting the copied pair once gives the median of [honest, honest, bad], which is honest. So the auditor's value
  shows in the consensus on items that are both biased and copied, and hardly anywhere else.
- **Why an undeclared copier can be found:** the copier repeats the bad source's report plus its own noise τ·σ. For
  that pair, the bias cancels in their squared difference, leaving about τ²σ². For any pair with one honest member,
  the squared difference carries the bias and both noises. So agreement in error shows as a pair difference far
  below the instance's typical one, with no σ needed.
- **What no auditor can beat:** collapse from the truth labels (the oracle) sets the ceiling. If the oracle's gain is
  small, no auditor can matter, and the test stops there (below).

## Design

### The fixture

As 93e08797 fixes it: conditions A (no copier), C (a declared copier) and D (an undeclared copier), from shared base
instances; the grid axes, the pilots and the cut; N = 500 instances per kept cell; and seeds from
`numpy.random.SeedSequence` keyed by cell and instance. This spec narrows nothing further.

**Who builds it:** the fixture's generator follows 93e08797, and Tardis builds it, since that spec is Tardis's. This
spec's code (the auditor, the arms and the scoring) is Serenity's, written in Python against the generator's output.
Each reads the other's code before the plan is fixed. Python, not Rust: it's an experiment harness on a numpy
fixture, and a new native component would add nothing here.

### The consensus

Every arm takes each item's consensus as the median of the reports it counts. The median is the fixture's pilot
method, and it's robust to one biased report, so double counting is what breaks it.

### The auditor

- **Its statistic:** for each pair of sources sharing at least 3 items, d(i, j) is the median over those items of
  (x_i − x_j)², the fixture's plain pilot detector. The pair's ratio is r(i, j) = d(i, j) / the median of d over all
  of the instance's eligible pairs. It's scale-free, needs no σ, and uses no truth.
- **Its flag:** every pair with r below a threshold θ is marked dependent.
- **θ is fixed on calibration instances,** from a seed disjoint from the pilots' and the run's: 500 instances of
  condition A for each combination of K, M and ρ, which a real auditor can count. θ is the 5th percentile of the
  smallest r per instance, so 5% of A instances flag a pair. It is pooled over b and s, which an auditor can't
  observe. The θ values go in the plan.
- **Its collapse:** on the items both members of a flagged pair report, their two reports become one, their mean. The
  pair counts once, and every other report is kept. This follows 93e08797's rule that collapse uses the method's own
  answer and never the truth.
- **"What would count against a conclusion":** for each item, the auditor reports its consensus, the number of
  independent reports supporting it after collapse, and whether the conclusion *rests on dependent reports*: whether
  undoing the collapse moves the consensus by more than half its own scale, ŝ = √(median pair d / 2). (For two honest
  sources, d is about 2σ², so ŝ estimates σ.)

### The arms

| Arm | What it counts | In |
| --- | --- | --- |
| N, naive | every report | A, C, D |
| P, provenance | every report, with pairs `relation()` answers copied collapsed (declared chains) | C, and D, where it finds nothing |
| I, the auditor | every report, with the auditor's flagged pairs collapsed | A, C, D |
| O, the oracle | every report, with the truth's copier pair collapsed on its copied items | C, D |

### Measures, fixed before the run

- **The scored items:** in C and D, the *copied biased items*: those where the bad source's report carries the bias
  and the copier copied it, as the truth records. The truth only selects and scores, and is never an input.
- **Consensus error:** |consensus − true value| / σ, averaged per instance over its scored items. An instance with
  none is excluded and counted.
- **Primary, condition D:** I against N, consensus error on the copied biased items, paired by instance, pooled over
  the kept D cells, each cell weighted equally.
  - The bootstrap resamples instances within cells, 10,000 replicates, seed 2026112207, with percentile 95% intervals.
  - **The auditor earns its place** if the interval for N − I excludes 0 in I's favour, and I recovers at least half
  the oracle's gain: (N − I) / (N − O) ≥ 0.5 as a point estimate, its interval reported.
  - An interval excluding 0 with a ratio under 0.5 is "helps, under half the ceiling". An interval straddling 0 is "no
  measured gain".
- **Do no harm, condition A (with no copier):** I against N, consensus error over all items the bad source reports.
  The interval for I − N must lie within ±0.05σ, the tie band. If it doesn't, false collapses cost honest
  conclusions, and that's reported as a failure whatever D shows.
- **Secondary:**
  - **C:** P against N and against O. Declared provenance should recover nearly all of the ceiling: a check that test
    5's `relation()` changes a conclusion. Also I against P in C: inference against declaration.
  - **Detection, in D:** the share of instances with the copier pair flagged; the share with an honest pair flagged;
    and in A, the realised false-flag rate on the run's seeds, against the 5% fixed on calibration.
  - **Blame,** with 93e08797's rules: the bad source ranked first by mean absolute deviation from each arm's
    consensus, ties as 1/t, and a copier first scored apart.
  - **"What would count against":** against the truth, where the oracle's collapse moves the consensus by more than
    0.5σ, the auditor's "rests on dependent reports" flag gives a recall and a precision, in D.
  - Per-cell results, descriptive only.

### The ceiling, counted before the plan is fixed

On the fixture's pilot seeds, with no auditor run: the oracle's gain N − O on copied biased items in each kept D cell,
and the share of those items whose naive consensus is off by more than 0.5σ at all.
- **If the pooled N − O is under 0.1σ,** double counting barely moves these conclusions, no auditor can matter, and
  the test stops with that as its result. The cells are not changed to make it matter.
- The counts go in the plan, beside the θ values.

### What would count against

- I no better than N in D: the auditor can't find undeclared copying well enough to change a conclusion.
- I worse than N in A: it collapses honest pairs and costs honest conclusions.
- P short of O in C: declared provenance doesn't carry into the conclusion.

Each is reported as found.

### Known limits, stated before the run

- **Planted data:** one bad source, one copier, Gaussian noise. Real copying can be partial, chained or transformed,
  and real crossings are counted when test 5's Measure 3 runs.
- **One detector:** the plain pair statistic. A stronger detector could do better. This tests whether a plain auditor
  pays, not the best possible one.
- **The median consensus only.** The mean is worse under double counting, so the median is the harder test for the
  auditor.
- **Routes,** the row's other half, stay with #12's result.

## Code (after approval)

`engram/experiments/northstar/test7.py` and its tests: the auditor's statistic, flag, calibration and collapse; the
four arms; the scoring, tested against hand-made instances that pin which items each measure scores and which answer
it compares against; and `plan` (the ceiling counts, θ, the kept cells, seeds), `run` and `rescore`, as tests 1 and 2.
