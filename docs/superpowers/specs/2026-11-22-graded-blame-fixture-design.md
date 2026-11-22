# Graded blame: test 6's graded half, and one planted fixture for test 7

Revision 2, 2026-11-22. Tardis, goal line T2 (test 6), board item `north:6-structure-earns-its-place`. Serenity's
design read is in all hands e29b0698 and d8c84d6f. Under station law section 3, a fresh reviewer approves it in Andy's
place, and Andy can veto.

- **Revision 1 (a889f48b)** went to a fresh reviewer, who asked for a revision with seven required findings and six
  advisory ones (all hands 0052fc00).
- **This revision makes them,** named R1 to R7 and A1 to A6. Its main change follows from R1, R2 and A5: test 6's
  graded half is closed by argument and a property check, and the fixture is for test 7.

## Why

- **Row 6 of `docs/north-star.md`** (66ae28e5): on identity data the sheaf line stops. A set sheaf ties exact
  enumeration, checked on 500 instances (`tardis/test6-identity-property` 3233e6da).
- **What's left open** is graded disagreement and blame: which source to doubt when reported values differ.
- **No real data can test it:**
  - the Mac has one Atlas store, overlapping nothing;
  - the Pi and Tardis have none;
  - test 5's planted stores have 26 matched source pairs, none disagreeing on year (all hands a705ead8).

## Test 6's graded half: closed by argument, then checked

**The argument (the reviewer's R1, R2 and A5).** `sheaf_core.glue`'s nearest global section is the orthogonal
projection onto H⁰, `y = B Bᵀ x` in raw stalk coordinates, and the C kernel's `sheaf_sections` projects onto ker L. So:
- **On identity maps,** each item's consensus is the mean of its reports, and a source's residual is its squared
  deviations from those means. S *is* plain least squares (PL). It can beat an absolute-loss or threshold method by its
  loss function alone, which says nothing about structure.
- **On linear unit maps,** report x in a unit k times the common one, the consensus is `u* = Σ k·x / Σ k²`, and each
  squared residual is weighted by k². That's least squares weighted by k². Edge weights don't change ker L. So with
  unit maps S is a weighted least-squares method fixed by the coordinates, and a normalisation with the matching weights
  is the same method.
- **Known affine offsets,** such as a preprint year minus 1 or a page end, are a translation. Normalising first loses
  nothing, so excluding them loses nothing (A4). (The kernel's maps are linear, and a homogeneous stalk `(x, 1)` doesn't
  hold its 1: in the reviewer's toy it moved to 0.333.)
- **Non-invertible maps,** such as a source reporting only totals, make a plain normalisation undefined. But `glue` is
  still a constrained least-squares solve, and a plain constrained solve ties it exactly.

So no planted accuracy test can show the sheaf a gain on graded data. A gain could only be in generality or cost (one
mechanism instead of code written per schema), which needs a different measure, and isn't this spec.

**The check, fixed before it runs.** It's a property test on 500 instances, from seeds derived with
`numpy.random.SeedSequence(20261123)` keyed by instance (A2). Each instance follows the fixture's condition A or U,
below. The test asserts:
- **On identity maps:** S's per-source residuals equal PL's (the per-item mean, then the mean squared deviation per
  report) to 1e-9.
- **On unit maps:** they equal least squares weighted by k², after normalising.
- **The ranking:** each pair ranks the sources identically, ties included.

If it holds, row 6 adds: "stops for graded data too, by argument, checked; a gain could only be in generality or cost,
which needs another measure". This is a check of the argument, not a measurement.

## The fixture, for test 7

Test 7's auditor and its measures are Serenity's, in her spec. This fixture gives them planted dependence with known
answers. It's built so every condition shares a base instance (A2).

**One base instance, from a seed keyed by cell and instance:**
- **K sources:** K is 4, 5 or 6 (R6: C and D need K ≥ 4, so a copier and the bad source aren't a majority).
- **M items:** M is a grid axis (R7), 20 or 60.
- **Overlaps:** each item is reported by each source with probability ρ. An item with fewer than two reports is redrawn
  on its own, never the whole instance (R7), and the realised density is recorded.
- **Minimums:** every source has at least 5 reports, and a source with fewer is redrawn.
- **Values:** true values are uniform, and each honest report adds Gaussian noise σ, in common units. The noise model
  is stated, for R2.
- **The bad source:** one source adds a bias b·σ to ⌈s·n⌉ of its n items, at least one, with one random sign for the
  source (R7).

**Conditions, each from the same base instance:**
- **A:** the base instance.
- **C, a declared copier:** a further source repeats the bad source's report plus its own noise τ·σ, on a copied share
  q of the items they share, and reports honestly elsewhere. It names the bad source in its chain. As Claim packages
  that `validate_sourced` accepts, each copied report's claim names the bad source's claim digest in its `provenance`,
  so `relation()` answers copied (A3).
- **D, an undeclared copier:** the same as C, but naming nothing (R6). With τ > 0, an equality test can't find it, and
  dependence must be inferred from agreement in error beyond what independent noise allows.
- **U, units:** A with each source reporting in a unit k of 1 or 1000, recorded per report, its noise in its own unit,
  as the noise model states.

**Truth recorded per instance:**
- the bad source, the copier, and which items were copied;
- the realised density;
- the seeds.

**Scoring rules the fixture fixes, for whoever ranks sources:**
- **A score per source** is a mean per report, never a sum (R7).
- **Ties** for first get fractional credit, 1/t (R7).
- **A copier ranking first** is scored apart from the bad source ranking first. It's not a hit for "the bad source
  first" (R6).
- **Collapse, where a method uses it,** drops the copier's reports on the items marked copied, and keeps the rest
  (R6).

**The grid, after a pilot (R7, A1):**
- **The axes:** b of 2, 4 and 8; s of 0.25 and 0.5; ρ of 0.5 and 0.9; K of 4, 5 and 6; M of 20 and 60; and, in C and
  D, τ of 0.1 and 0.5 and q of 0.5 and 1.0.
- **The pilot:** the plain median, scored by mean absolute deviation, runs alone on condition A, 100 instances per
  cell, from a seed disjoint from the run's.
- **The cut:** cells are kept where its first-rank share is between 1.5/K and 0.9, a floor relative to chance at 1/K.
- **The estimand is the kept cells,** and the dropped cells are reported as a sensitivity check (A1).
- **The commit:** the kept grid, the seeds and N = 500 per cell are fixed in a commit before any method runs on the
  run's seeds.

## Measures

- **Test 6:** only the property check above. With no accuracy run, R3's comparator, R4's margin and R5's primary
  don't arise.
- **Test 7:** Serenity's spec fixes its comparator, its margin (a minimum gain and a tie band), its bootstrap
  (replicates, seed and interval) and its primary, by R3 to R5. Per-cell intervals are descriptive only (A6).

## What this spec does not do

- **Real crossings.** Their graded fields are counted when Measure 3 runs.
- **Test 7's auditor,** its measures and its "what would count against a conclusion". Those are Serenity's.
- **A measure of generality or cost** for the sheaf, the one place a gain could lie. That needs its own spec, if anyone
  thinks it worth one.
- **`ncat`'s half of test 6:** that's #2's stop test, on the Pi's recall log.
