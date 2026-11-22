# Graded blame: one planted fixture for north-star tests 6 and 7

Revision 1, 2026-11-22. Tardis, goal line T2 (test 6), board item `north:6-structure-earns-its-place`. Serenity's design
read is in all hands e29b0698 (the design) and d8c84d6f (her three changes, all taken here). Under station law
section 3, a fresh reviewer approves it in Andy's place, and Andy can veto. Test 7's auditor, and its "what would count
against a conclusion", is Serenity's to spec on this fixture.

## Why

- **Row 6 of `docs/north-star.md`** (66ae28e5): on identity data the sheaf line stops. A set sheaf ties exact
  enumeration, checked on 500 instances (`tardis/test6-identity-property` 3233e6da).
- **What's left open** is graded disagreement and blame: which source to doubt when reported values differ.
- **No real data can test it:**
  - the Mac has one Atlas store, overlapping nothing;
  - the Pi and Tardis have none;
  - test 5's planted stores have 26 matched source pairs, none disagreeing on year (all hands a705ead8).

  So the fixture is planted, and its known answers are its point.

## What each method computes, by mechanism, before any run

- **The vector sheaf with identity maps.** The base is one node per report (a source's value for an item), and an
  edge joins two reports of one item from overlapping sources. `glue`'s nearest global section is the orthogonal
  projection onto H⁰: on each item's connected reports, their mean. A source's residual is then its squared deviations
  from those means, which is least squares.
  - So, on identity maps, the sheaf against plain B is the mean against the median.
  - One biased source pulls a mean toward it and doesn't move a median, so B should tie or win. This revision runs it
    only as a cheap confirmation (Serenity's judgement, and mine, not a measurement).
- **The vector sheaf with non-identity maps** is the one input a plain method lacks unless it normalises first:
  - **The linear case:** reports in different units, related by known linear maps (a figure in units against one in
    thousands, ×1000; millimetres against centimetres, ×10). The sheaf's restriction maps carry them, against plain B'
    (normalise each report by the same known map, then the median). If B' ties, the maps are only a normalisation.
  - **The affine case:** a preprint year is the journal year minus 1, and a page end is its start plus the stated length
    minus 1. These are affine, and `sheaf_core`'s restrictions are linear. They'd need homogeneous stalks `(x, 1)`, and
    a projection that doesn't hold the 1 fixed. So they're out of this revision and named as such.

## The fixture

A generator with a seed. Per instance:
- **K sources:** K is 3 to 6.
- **M items:** 20 to 60, each reported by a random subset of sources at overlap density ρ. Every item has at least two
  reports.
- **Values:** true values; honest reports add Gaussian noise σ; the one bad source adds a bias b·σ to a share s of its
  items, with its sign random.

**Conditions:**
- **A:** one bad source.
- **C:** A plus a declared copier. It repeats the bad source's values, errors included, and names the bad source in
  its chain, so `relation()` answers copied.
- **D:** A plus an undeclared copier. It repeats them the same way, but names nothing. The auditor must infer
  dependence from agreement in error beyond what independent noise allows (Serenity's change 1).
- **U:** A, with each source reporting in one of two units, its unit recorded per report, related by a known linear
  map.

Each instance records its truth: the bad source and the copier. The generator and its seeds are in the run's commit.

## Methods, each ranking the K sources

- **S, the sheaf:** each source's residual from `glue`'s nearest global section on `sheaf_core.VectorSheaf`. That's
  identity maps in A, C and D, and the unit maps in U.
- **PA:** a source's disagreements over its overlaps, where disagreeing means a difference over 2σ.
- **PB:** its mean absolute deviation from each item's median. In U, it's PB' (normalised first).
- **In C:** each of S, PA and PB again, after collapsing declared copies through `relation()`'s copied answer, so a
  copier counts once.
- **In D:** the fixture gives the inputs and the truth. The auditor that infers the collapse is test 7's, specified by
  Serenity on this fixture.

## Measures, fixed before any run

- **Test 6, A and U:** the share of instances where the bad source ranks first. The comparison is S against the
  better of PA and PB (PB' in U), paired per instance. The 95% interval comes from a bootstrap over instances,
  stratified by grid cell.
  - **The primary** is pooled over the grid. Each cell is also reported.
  - S earns its place only if the primary interval excludes 0 in its favour. Otherwise row 6 adds "stops for graded
    data too, on identity and linear maps".
- **Test 7 hooks, C and D:**
  - **In C:** the first-rank share with and without collapse.
  - **In D:** whether the copier is flagged, how many honest pairs are flagged falsely, and the ranking with the
    inferred collapse. Serenity's spec fixes test 7's own measure.

## The ceiling first: a pilot of plain B only

Before the grid is fixed, PB alone runs on a pilot grid, with seed 1 and 100 instances per cell, and no sheaf.
- **The pilot grid:**
  - bias b of 2, 4 and 8;
  - share s of 0.25 and 0.5;
  - density ρ of 0.5 and 0.9;
  - K of 3, 4 and 6.
- **The cells kept** are those where PB's first-rank share is between 0.2 and 0.9, so none sits at a floor or a
  ceiling (Serenity's change 3).
- **Then the run's commit** fixes the kept cells, the seeds (one per cell, from 20261123) and N = 500 per cell, and
  only then does S run.

## What this spec does not do

- **Real crossings.** Their graded fields are counted when Measure 3 runs.
- **Test 7's auditor,** which is Serenity's, and its "what would count against a conclusion".
- **`ncat`'s half of test 6:** that's #2's stop test, on the Pi's recall log.
- **Affine maps,** as above.
