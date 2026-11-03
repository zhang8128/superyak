# E1′ smoke runs: the script on planted logs and on the Pi's own store

2026-11-03. Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e, as
amended on 2026-11-03).
- **The amendments:**
  - the fourth outcome, "negligible";
  - training collapsed once, with the shuffled arm permuting the collapsed runs;
  - δ_order as a permutation threshold.
- **Script:** `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d…`.
- **What section 6′ asks:** (ii) must **hold** on a planted order effect and must **not hold** on a no-order one. The
  Pi's store shows the floor working on a real schema.

The script has **not** run on Andy's store or on any Mac. That run is his decision, made after he reads the script and
this report. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

## First: how big the store must be

In plain words: to show a modest order effect, the store needs about **600 test steps in about 45 test sessions**.
That's roughly **230 sessions and 4,600 recalls since 2026-09-02**, because the test is the last fifth of that time.

- **The evidence.** On a realistic test log with a modest planted order effect, the script tried two sizes.
  - With about 300 test steps (about 23 test sessions) it reached "holds" in 3 of 6 tries. The other 3 were
    "inconclusive".
  - With about 600 test steps (about 46 test sessions) it reached "holds" in 6 of 6.
- **A smaller store will most likely say "inconclusive", not "fails".** That means too little data, not "no effect".
  Section 7's answer is to rerun once the test steps have doubled.
- **Below the floor** (200 test steps or 20 test sessions), it says "insufficient" and claims nothing.
- **More data helps twice.** It narrows the interval, and it sharpens (ii)'s counts. In the test log, the same effect
  measured D = +0.138 at about 300 steps and +0.241 at about 600.
- **To see where the store stands first,** count its recalls and sessions since the primary period began. This is
  read-only and prints two numbers:

  ```
  sqlite3 -readonly <store> "SELECT count(*), count(DISTINCT json_extract(context, '\$.session_id')) FROM memory_log WHERE event_type = 'recall' AND layer != 'instinct' AND timestamp >= '2026-09-02T03:08:04'"
  ```

## For the real run: three facts

1. **The command.** Run it from a checkout of `rail-mathematics` at this commit, with Engram's own Python:

   ```
   <engram>/.venv/bin/python -I scripts/rail_e1_prime.py \
     --store <ENGRAM_HOME>/.engram/instances/<instance>/graph.db \
     --config <project>/.engram/config.toml [--config <another project>/.engram/config.toml ...] \
     --report docs/reports/2026-11-03-rail-e1-prime.md
   ```

   - **The store** is the one Engram's server uses: `<ENGRAM_HOME>/.engram/instances/<instance>/graph.db`, where
     the instance is the project config's `instance =` or `ENGRAM_DEFAULT_INSTANCE`. With no instance it's
     `<ENGRAM_HOME>/.engram/graph.db`. On the Pi that's `/home/andy/.engram/instances/rio-grande/graph.db`.
   - **What the run does.** It checks the outcome classifier first, opens the store read-only (`mode=ro`,
     `query_only`, one read transaction, no copy), and writes nothing but the report. Its first stderr line is the
     outcome. `--self-check` runs only the classifier check.

2. **Every project's `.engram/config.toml` goes in with `--config`.** Engram's server reads the config in each
   session's working directory (its project root), not beside the store. So the script can't find those files by
   itself. It also checks the store's directory and every `.engram` directory above the store.
   - **When it stops.** It stops if any config sets `[memory] recency_mode` to anything but `tiebreak`, or can't be
     read.
   - **To list them** (macOS's zsh or bash; `2>/dev/null` hides folders macOS won't let `find` read):

     ```
     find ~ -maxdepth 6 -path '*/.engram/config.toml' -not -path '*/Library/*' 2>/dev/null
     ```

   - **To pass them all**, quoting paths that hold spaces:

     ```
     configs=(); while IFS= read -r f; do configs+=(--config "$f"); done < <(find ~ -maxdepth 6 -path '*/.engram/config.toml' -not -path '*/Library/*' 2>/dev/null)
     <engram>/.venv/bin/python -I scripts/rail_e1_prime.py --store <store> "${configs[@]}" --report docs/reports/2026-11-03-rail-e1-prime.md
     ```

3. **The vector cap.** The run stops before analysis if the vectors alone would pass 256 MiB. At 768 dimensions
   that's about 87,000 memories (87,381). To check beforehand, count the episode and semantic rows, an upper bound
   on the vectors, read-only:

   ```
   sqlite3 -readonly <store> 'SELECT (SELECT count(*) FROM episodes) + (SELECT count(*) FROM semantics);'
   ```

   The whole run is also held under 512 MiB. macOS may not enforce RLIMIT_DATA, so the script checks its peak RSS
   after each stage and stops if the peak passes 512 MiB.

## Summary

- **The outcome classifier** passed 48 boundary checks before every run. They cover:
  - the four outcomes at and around 0 and δ;
  - the session/day agreement;
  - the permutation threshold (floor, interpolation, no shuffles);
  - the order verdict at δ_order's floor and above it.
- **What the columns mean:**
  - **δ_order** is the larger of 0.02 and the permutation threshold in brackets. The threshold is the 95th
    percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average.
  - **D_null** compares the two shuffle sets' averages. It's descriptive.

| run | primary steps / test sessions | C1′ | D@10 [session BCa] | D@10 [day BCa] | order | D_order [session BCa] | D_order [day BCa] | δ_order [threshold] | D_null [session BCa] | met |
|---|---|---|---|---|---|---|---|---|---|---|
| 1. simple order | 453 / 31 | holds | +0.256 [+0.232, +0.281] | +0.256 [+0.232, +0.283] | carries information | +0.442 [+0.432, +0.455] | +0.442 [+0.432, +0.455] | 0.034 [+0.034] | +0.006 [−0.000, +0.013] | yes |
| 2. simple noorder (the draw that claimed order) | 343 / 32 | fails | −0.440 [−0.509, −0.371] | −0.440 [−0.491, −0.398] | ties | +0.027 [+0.004, +0.051] | +0.027 [+0.003, +0.047] | 0.031 [+0.031] | −0.008 [−0.018, +0.006] | yes |
| 3. realistic order, about 300 test steps | 298 / 21 | inconclusive | +0.138 [−0.006, +0.245] | +0.138 [−0.027, +0.257] | carries information | +0.223 [+0.157, +0.301] | +0.223 [+0.154, +0.312] | 0.033 [+0.033] | +0.011 [+0.006, +0.016] | **no**: too small (see "First") |
| 4. realistic noorder, about 300 test steps | 396 / 21 | fails | −0.063 [−0.112, −0.033] | −0.063 [−0.116, −0.031] | ties | −0.002 [−0.027, +0.017] | −0.002 [−0.017, +0.017] | 0.023 [+0.023] | +0.004 [−0.002, +0.008] | yes |
| 5. realistic order, about 600 test steps | 609 / 44 | holds | +0.241 [+0.153, +0.313] | +0.241 [+0.181, +0.295] | carries information | +0.247 [+0.201, +0.294] | +0.247 [+0.216, +0.297] | 0.025 [+0.025] | −0.005 [−0.013, +0.002] | yes |
| 6. realistic noorder, about 600 test steps | 830 / 44 | fails | −0.034 [−0.061, −0.007] | −0.034 [−0.056, −0.019] | ties | −0.007 [−0.022, +0.009] | −0.007 [−0.023, +0.007] | 0.020 [+0.011] | +0.001 [−0.002, +0.005] | yes |
| 7. the Pi's store | 0 / 0 | insufficient | not computed | | | | | | | yes |
| 8. permuted check: simple order, real order replaced by a shuffle | 479 / 31 | fails | −0.121 [−0.159, −0.083] | −0.121 [−0.154, −0.094] | ties | +0.011 [−0.020, +0.045] | +0.011 [−0.014, +0.048] | 0.020 [+0.019] | +0.003 [−0.007, +0.013] | yes |
| 9. permuted check: simple noorder | 361 / 32 | fails | −0.438 [−0.510, −0.371] | −0.438 [−0.511, −0.355] | ties | +0.015 [−0.023, +0.044] | +0.015 [−0.029, +0.041] | 0.026 [+0.026] | −0.001 [−0.015, +0.017] | yes |
| 10. permuted check: realistic order, about 600 test steps | 826 / 44 | fails | −0.052 [−0.077, −0.025] | −0.052 [−0.066, −0.037] | ties | +0.002 [−0.010, +0.013] | +0.002 [−0.009, +0.012] | 0.020 [+0.003] | −0.001 [−0.004, +0.003] | yes |

**What's required.**
- **The order logs** (runs 1, 3 and 5) must reach "holds" with order carrying information.
- **The no-order logs** (runs 2, 4 and 6) must not reach "holds", and order must tie.
- **The permuted checks** (runs 8 to 10) must say order ties.

Every requirement is met except run 3's, at about 300 test steps. That's the sample-size finding at the top.

- **Peak RSS** was under 193 MiB in every run, against the 512 MiB cap.
- **No scratch file was written**, and vectors stayed in memory.
- **Reruns** give the same numbers: every generator and resample is seeded.

## How the order bias was found and fixed, in plain words

The order check asks one question: does the real order of a session's recalls predict the next recall better than the
same recalls shuffled? To answer it, (ii) is trained once on real order and 20 times on shuffled orders, and the
scores are compared.

**What went wrong.** On logs built to have no order at all, the first smoke runs found real order scoring slightly
better than the shuffles, by about 1 point in 100. One of them cleared the bar and claimed order that wasn't there.
Two things were behind it.

- **A small unfairness in the shuffles.**
  - **The cause.** Repeated recalls were merged before real order was scored, but a shuffle split them apart and
    merged again. So the shuffled versions trained on slightly different, noisier data.
  - **Its size.** It was worth about 0.4 points in 100.
  - **The fix.** Both now use the same merged recalls, merged once, from real order.
- **Luck in a single ordering, which the old bar didn't measure.**
  - **The comparison.** Real order is one ordering, and it's compared with the average of 20 shuffles.
  - **How much luck.** One ordering on its own can land 2 or 3 points above that average by chance. On the log that
    claimed order, single shuffles scattered with a spread of about 2 points, and real order sat 2.9 points above
    the average.
  - **Why the old bar missed it.** The error bars resample the test sessions with the training held fixed, so they
    never saw this.
  - **The fix: measure the bar from the shuffles.** For each of 20 fresh shuffles, take how far that one shuffle
    alone sits from the average. Order now counts only if real order clears the 95th percentile of those distances,
    and never by less than 2 points.

**How it was checked.**
- **No-order logs.** Over many fresh logs with no order, the corrected comparison averages about 0.
- **Every rerun.** In the reruns below, every no-order log says order ties, and so does every log whose real order
  was replaced by one more shuffle. The logs with a planted order still say order carries information, well past
  the bar.

### The technical record of the bias hunt

- **The theory.** When a session's order is exchangeable, real order is distributed as one more shuffle. So the
  expected D_order is exactly 0 whenever real and shuffled training go through the same code.
  - **Not tested separately:** the Jaccard filter, and ties broken by (i)'s order. Both treat real and shuffled
    sequences alike.
  - **Tested:** the permuted checks (runs 8 to 10), which make real order one more shuffle. All three tie.
- **Re-collapsing after a shuffle was a real asymmetry, about +0.004.** It was measured paired on 6 seeds: the old
  design's D_order minus the collapse-once design's, positive in 4 of 6. Collapse-once removes it.
- **The rest was the training arrangement's variance.**
  - **The size.** Under no order, D_order's spread across fresh logs is about 0.024. With collapse-once, its mean is
    −0.007 over 14 simple logs (SE 0.006) and −0.002 over 4 realistic ones.
  - **What a single shuffle does.** On run 2's log, a single shuffle's hit@10 varies with SD 0.019 around the
    average, and real order sat +0.029 above it.
  - **What the bootstrap misses.** The session bootstrap holds the trained tables fixed, so neither D_order's interval
    nor D_null's sees that variance. D_null's interval in run 3, [+0.006, +0.016], excludes 0 although its
    expectation is 0.
- **So δ_order is now a permutation threshold.**
  - **The calibration this replaces.** The one from D_null's bootstrap left δ_order at its 0.02 floor in every
    run.
  - **The new values.** The threshold gives 0.020 to 0.034 across these runs. On run 2 it's 0.031, so run 2 ties on
    the measured threshold, not just the floor.
  - **Its cost.** None: set B was already computed.

## The realistic pair

**What makes it realistic.** Runs 3 to 6 and 10 use a log shaped like Engram's (planted structure under each run):
- 80 topics of 40 memories, each topic graded along its own low-dimensional subspace.
- Every recall is the 15 to 20 memories nearest its query, so meaning makes every set.
- Consecutive recalls overlap. The rule drops 29–30% of steps above Jaccard 0.5 in the order log, and 4–6% in the
  no-order log, where permuting breaks adjacency.
- About a quarter of sessions interleave two footpaths under one session id.
- About 10% of memories have no vector now, and about 10% are created during the log.

**The plant.** After a topic, a jump goes with p = 0.6 to that topic's fixed next set. The no-order log holds the same
sessions, queries and times, each session's queries permuted over its times. That keeps co-retrieval and who shares a
session, and removes order. The plant was sized so D@10 sits near 0.10 to 0.15 at about 300 test steps.

**The seed study behind "First".** It has 1 shuffle per run, since D doesn't depend on the shuffles. Runs 3 and 5 are
added to their rows.

| planted sessions | test steps | test sessions | D@10 per seed [session BCa], outcome | holds |
|---|---|---|---|---|
| 120 | 292–321 | 21–25 | +0.226 [+0.153, +0.325] H; +0.238 [+0.157, +0.314] H; +0.121 [−0.038, +0.232] I; +0.164 [+0.078, +0.253] H; +0.128 [+0.006, +0.227] I (day disagreed); run 3: +0.138 [−0.006, +0.245] I | 3 of 6 |
| 240 | 608–638 | 44–48 | +0.216 [+0.128, +0.295] H; +0.252 [+0.189, +0.315] H; +0.210 [+0.134, +0.277] H; +0.118 [+0.028, +0.204] H; +0.124 [+0.027, +0.205] H; run 5: +0.241 [+0.153, +0.313] H | 6 of 6 |

## Reading

This section is written by hand. Everything from "Run 1" on is the script's output.

- **The planted order effects are found, and order is what finds them.**
  - The simple order log holds with D = +0.256, and the realistic one holds at about 600 test steps with D = +0.241.
  - Both carry order far past their δ_order: D_order +0.442 against 0.034, and +0.247 against 0.025.
  - With their real order replaced by a shuffle (runs 8 and 10), both fail and order ties.
- **Logs with co-retrieval and no order don't hold, and order ties.** The realistic no-order log fails at both sizes.
  It holds the order log's very sessions, permuted, so the difference between runs 5 and 6 is order alone.
- **The draw that claimed order now ties on a measured threshold.**
  - **Its D_order.** It's +0.027 [+0.004, +0.051], against δ_order 0.031, the 95th percentile of single shuffles on
    that very log.
- **The Pi's store shows the floor on a real schema.**
  - **What it holds.** 5 recalls in one session, so `T` falls inside that session. No session starts after `T`, so
    there are 0 test steps: "insufficient".
  - **What the run touched.** It read the live file with `mode=ro` in one read transaction:
    - the recall projections;
    - 45 vectors, with every logged id found among them;
    - the project's `config.toml`, which sets `tiebreak`.

## Concerns for the reviewer and for Andy

1. **(ii) needs a large store to show a modest effect.**
   - **Why.** It fills its top 10 by count, so meaning wins the steps that stay in a topic for free.
   - **How large.** A realistic effect of D ≈ 0.13 is inconclusive at about 300 test steps, and holds at about 600 in
     about 45 test sessions.
   - **What that means.** A store between the floor and that size will most likely say "inconclusive": too little
     data, not "no effect".
2. **The threshold comes from 20 shuffles.** Its 95th percentile interpolates between the two largest of 20
   differences, so it moves from log to log: 0.003 to 0.034 here.
   - **What protects it.** The 0.02 floor covers the low draws.
   - **What the order claim demands.** D_order's own lower bound has to clear the threshold, which adds the test-side
     uncertainty on top. Read together, the bar is conservative.
3. **The config check can't find every config by itself.** The fix is the second fact above. It also sees today's
   files only, not what a config said in the past.
4. **Day clusters use UTC days.** On Andy's Pacific clock, a UTC day ends at 4 or 5 pm.
5. **What the smoke can't settle.** The realistic plant is one model of trails: fixed next sets after topics. Real
   trails may be weaker or more spread out. The smoke shows that the script finds order when it's there and doesn't
   claim it when it's not, at these sizes. It can't promise the real store has order.

## Run 1: simple order

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ holds; order carries information.** D@10 = +0.256 [+0.232, +0.281] (session BCa), D_order = +0.442 [+0.432, +0.455]. Section 7: E1′ holds, and order carries information: build trails from recall logs, smallest first.

### Planted structure

128 groups of 12 memories (768-d, each group tight in meaning). There are 120 regular groups and 8 hub groups, and each regular group has a fixed hub. A session takes one regular group per hub, in random order, and recalls each group and then its hub, 16 recalls of 6 random members each. A memory is followed by a specific next set, and every hub sits in every session, so only order says which hub follows.

**Required:** C1′ holds, and D_order's lower bound is above δ_order.

Both simple logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), and empty recalls (2%).
Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ holds, order carries information).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 1836 memories with a vector (episode 1452, semantic 384), dimension 768. Left out: 10 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 7 distinct ids.
- **Recall rows:** 3007. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2737 in the primary period (from 2026-09-02, engram 548c97dd) and 210 in the additive period before it.
- **Recall days:** the analysed recalls span 71 days.

### The primary period

- **Recalls analysed:** 2737 in 160 sessions.
- **Split:** `T` falls on 2026-10-19 (80th percentile of recall times, rounded to the day).
- **Training:** 129 sessions with recalls before `T`, 2189 recalls, 2089 after collapse, and 1960 pairs passing the Jaccard rule. (ii) has 43265 distinct edges and (iv) has 14670.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 31, with 539 recalls; collapse merged 31 of them. That leaves 477 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 477 | 12 (2.5%) | 12 (2.5%) | 453 (95.0%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 453 in 31 sessions over 8 days. The largest session holds 3.3% of them.

- **Uptake marks** (descriptive): training recalls 2189, of which 537 were marked used (210 by `auto`). Test recalls 539, of which 137 were marked used (52 by `auto`).

#### Outcome

- **C1′ holds.** D@10 = +0.256 [+0.232, +0.281] by session (31 clusters), +0.256 [+0.232, +0.283] by day (8 clusters). δ = 0.05.
- **Order carries information.** D_order = +0.442 [+0.432, +0.455] by session, +0.442 [+0.432, +0.455] by day.
- **δ_order = 0.034**, the larger of the floor 0.02 and the permutation threshold +0.034: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.017.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = +0.006 [-0.000, +0.013] by session, +0.006 [-0.001, +0.012] by day.
- **Section 7:** E1′ holds, and order carries information: build trails from recall logs, smallest first.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.000 | 0.000 | 0.298 | 0.031 | 0.031 | 0.000 | 0.000 | +0.267 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.000 | 0.000 | 0.528 | 0.179 | 0.179 | 0.000 | 0.000 | +0.349 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.009 | 0.009 | 0.534 | 0.278 | 0.278 | 0.009 | 0.000 | 0.092 | +0.256 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | +0.267 [+0.232, +0.303] | +0.267 [+0.245, +0.313] |
| 5 | +0.349 [+0.319, +0.377] | +0.349 [+0.315, +0.377] |
| 10 | +0.256 [+0.232, +0.281] | +0.256 [+0.232, +0.283] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.525 [+0.513, +0.539] |
| (i′) nearest | +0.525 [+0.513, +0.538] |
| (iii) popularity | +0.256 [+0.232, +0.281] |
| (iii-m) popularity, matched | +0.256 [+0.232, +0.281] |
| (iv) co-retrieval | +0.525 [+0.513, +0.539] |
| (v) history | +0.534 [+0.525, +0.546] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 453 primary steps (0.0%); there it equals (i).
On the 453 steps with counts, D@10 = +0.256 [+0.232, +0.280] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 453 | 0.009 | 0.009 | 0.534 | 0.278 | 0.278 | 0.009 | 0.000 | +0.256 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 453 | 0.009 | 0.009 | 0.534 | 0.278 | 0.278 | 0.009 | 0.000 | +0.256 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 453 | 0.009 | 0.009 | 0.534 | 0.278 | 0.278 | 0.009 | 0.000 | +0.256 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 2 | 21 | 525 | 0.190 | 0.000 | 0.000 | 0.238 | 0.000 | 0.143 |
| 3–4 | 274 | 500 | 0.153 | 0.000 | 0.015 | 0.288 | 0.004 | 0.168 |
| 5–9 | 156 | 12 | 0.558 | 0.000 | 0.064 | 1.000 | 0.019 | 0.481 |
| 10+ | 2 | 12 | 1.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 121, of which 78 explicit and 43 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 121 | 0.008 | 0.017 | 0.562 | 0.264 | 0.264 | 0.008 | 0.000 | +0.298 |

### The additive period (reported apart)

- **Recalls analysed:** 210 in 12 sessions.
- **Split:** `T` falls on 2026-08-29 (80th percentile of recall times, rounded to the day).
- **Training:** 10 sessions with recalls before `T`, 168 recalls, 158 after collapse, and 148 pairs passing the Jaccard rule. (ii) has 4901 distinct edges and (iv) has 3170.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 2, with 36 recalls; collapse merged 2 of them. That leaves 32 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 32 | 2 (6.2%) | 2 (6.2%) | 28 (87.5%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 28 in 2 sessions over 2 days. The largest session holds 53.6% of them.

- **Uptake marks** (descriptive): training recalls 168, of which 51 were marked used (22 by `auto`). Test recalls 36, of which 3 were marked used (0 by `auto`).

#### Outcome (secondary, decides nothing)

**Insufficient:** 28 test steps (needs 200); 2 test sessions (needs 20); one session holds 54% of the steps (at most 15%). The run claims nothing and computes no interval.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 28 | 0.000 | 0.000 | 0.143 | 0.071 | 0.071 | 0.000 | 0.000 | +0.071 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 28 | 0.000 | 0.000 | 0.286 | 0.286 | 0.179 | 0.000 | 0.000 | +0.000 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.179 | 0.000 | 0.000 | 0.029 | -0.036 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 6 of 28 primary steps (21.4%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 22 | 0.000 | 0.000 | 0.364 | 0.227 | 0.227 | 0.000 | 0.000 | +0.136 |
| without counts | 6 | 0.000 | 0.000 | 0.000 | 0.667 | 0.000 | 0.000 | 0.000 | -0.667 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.179 | 0.000 | 0.000 | -0.036 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.179 | 0.000 | 0.000 | -0.036 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| 1 | 20 | 46 | 0.150 | 0.000 | 0.100 | 0.350 | 0.000 | 0.200 |
| 2 | 2 | 26 | 0.500 | 0.000 | 0.000 | 0.500 | 0.000 | 0.500 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 3, of which 3 explicit and 0 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 3 | 0.000 | 0.000 | 0.333 | 0.333 | 0.333 | 0.000 | 0.000 | +0.000 |

### Resources

- **Peak RSS:** 76.9 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 16 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 2: simple noorder (the draw that claimed order)

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.440 [-0.509, -0.371] (session BCa), D_order = +0.027 [+0.004, +0.051]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

150 groups of 12 memories (768-d, each group tight in meaning). A session takes 2 groups and makes 12 recalls, each drawing 6 random members from one of the two at random. Memories are co-retrieved within a group, and order within a session is exchangeable.

**Required:** C1′ does not hold, and D_order ties.

Both simple logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), and empty recalls (2%).
Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2100 memories with a vector (episode 1656, semantic 444), dimension 768. Left out: 10 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 7 distinct ids.
- **Recall rows:** 2262. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2047 in the primary period (from 2026-09-02, engram 548c97dd) and 155 in the additive period before it.
- **Recall days:** the analysed recalls span 71 days.

### The primary period

- **Recalls analysed:** 2047 in 160 sessions.
- **Split:** `T` falls on 2026-10-15 (80th percentile of recall times, rounded to the day).
- **Training:** 128 sessions with recalls before `T`, 1637 recalls, 1563 after collapse, and 1406 pairs passing the Jaccard rule. (ii) has 27596 distinct edges and (iv) has 14998.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 32, with 409 recalls; collapse merged 20 of them. That leaves 357 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 353 | 5 (1.4%) | 5 (1.4%) | 343 (97.2%) |
| > 0.5 (excluded; descriptive) | 4 | 0 (0.0%) | 0 (0.0%) | 4 (100.0%) |

- **Primary steps:** 343 in 32 sessions over 12 days. The largest session holds 3.2% of them.

- **Uptake marks** (descriptive): training recalls 1637, of which 388 were marked used (162 by `auto`). Test recalls 409, of which 103 were marked used (42 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.440 [-0.509, -0.371] by session (32 clusters), -0.440 [-0.491, -0.398] by day (12 clusters). δ = 0.05.
- **Order ties.** D_order = +0.027 [+0.004, +0.051] by session, +0.027 [+0.003, +0.047] by day.
- **δ_order = 0.031**, the larger of the floor 0.02 and the permutation threshold +0.031: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.021.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = -0.008 [-0.018, +0.006] by session, -0.008 [-0.020, +0.007] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 343 | 0.236 | 0.230 | 0.149 | 0.000 | 0.020 | 0.230 | 0.251 | -0.102 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 343 | 0.484 | 0.484 | 0.303 | 0.009 | 0.064 | 0.484 | 0.592 | -0.289 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 343 | 0.490 | 0.490 | 0.382 | 0.009 | 0.064 | 0.490 | 0.822 | 0.355 | -0.440 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.102 [-0.149, -0.041] | -0.102 [-0.142, -0.054] |
| 5 | -0.289 [-0.364, -0.211] | -0.289 [-0.344, -0.229] |
| 10 | -0.440 [-0.509, -0.371] | -0.440 [-0.491, -0.398] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | -0.108 [-0.159, -0.072] |
| (i′) nearest | -0.108 [-0.161, -0.073] |
| (iii) popularity | +0.373 [+0.307, +0.438] |
| (iii-m) popularity, matched | +0.318 [+0.257, +0.384] |
| (iv) co-retrieval | -0.108 [-0.158, -0.073] |
| (v) history | -0.440 [-0.507, -0.369] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 43 of 343 primary steps (12.5%); there it equals (i).
On the 300 steps with counts, D@10 = -0.457 [-0.527, -0.379] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 300 | 0.497 | 0.497 | 0.373 | 0.010 | 0.010 | 0.497 | 0.830 | -0.457 |
| without counts | 43 | 0.442 | 0.442 | 0.442 | 0.000 | 0.442 | 0.442 | 0.767 | -0.326 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 124 | 1.000 | 1.000 | 0.766 | 0.008 | 0.137 | 1.000 | 0.790 | -0.234 |
| |b ∖ a| = 4–7 | 219 | 0.201 | 0.201 | 0.164 | 0.009 | 0.023 | 0.201 | 0.840 | -0.676 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 177 | 0.011 | 0.011 | 0.000 | 0.011 | 0.011 | 0.011 | 0.819 | -0.819 |
| Jaccard (0, 0.25] | 42 | 1.000 | 1.000 | 0.857 | 0.000 | 0.071 | 1.000 | 0.929 | -0.143 |
| Jaccard (0.25, 0.5] | 124 | 1.000 | 1.000 | 0.766 | 0.008 | 0.137 | 1.000 | 0.790 | -0.234 |
| Jaccard > 0.5 (not primary) | 4 | 1.000 | 1.000 | 0.250 | 0.000 | 0.000 | 1.000 | 0.750 | -0.750 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 43 | 0 | 0.163 | 0.163 | 0.000 | 0.442 | 0.442 | 0.000 |
| 1 | 197 | 16 | 0.076 | 0.244 | 0.000 | 0.299 | 0.457 | 0.010 |
| 2 | 84 | 25 | 0.298 | 0.274 | 0.000 | 0.524 | 0.595 | 0.000 |
| 3–4 | 19 | 45 | 0.211 | 0.158 | 0.000 | 0.474 | 0.474 | 0.053 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 94, of which 57 explicit and 37 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 94 | 0.500 | 0.489 | 0.383 | 0.011 | 0.032 | 0.500 | 0.745 | -0.362 |

### The additive period (reported apart)

- **Recalls analysed:** 155 in 12 sessions.
- **Split:** `T` falls on 2026-08-29 (80th percentile of recall times, rounded to the day).
- **Training:** 10 sessions with recalls before `T`, 124 recalls, 120 after collapse, and 107 pairs passing the Jaccard rule. (ii) has 2158 distinct edges and (iv) has 1664.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 2, with 25 recalls; collapse merged 0 of them. That leaves 23 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 23 | 1 (4.3%) | 1 (4.3%) | 21 (91.3%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 21 in 2 sessions over 2 days. The largest session holds 52.4% of them.

- **Uptake marks** (descriptive): training recalls 124, of which 30 were marked used (8 by `auto`). Test recalls 25, of which 8 were marked used (2 by `auto`).

#### Outcome (secondary, decides nothing)

**Insufficient:** 21 test steps (needs 200); 2 test sessions (needs 20); one session holds 52% of the steps (at most 15%). The run claims nothing and computes no interval.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.286 | 0.333 | 0.286 | 0.000 | 0.286 | 0.286 | 0.286 | -0.048 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.476 | +0.000 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.762 | 0.524 | -0.238 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 21 of 21 primary steps (100.0%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 0 | | | | | | | | |
| without counts | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.762 | -0.238 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 8 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.750 | +0.000 |
| |b ∖ a| = 4–7 | 13 | 0.231 | 0.231 | 0.231 | 0.000 | 0.231 | 0.231 | 0.769 | -0.538 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 10 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.800 | -0.800 |
| Jaccard (0, 0.25] | 3 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.667 | +0.000 |
| Jaccard (0.25, 0.5] | 8 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.750 | +0.000 |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 21 | 0 | 0.286 | 0.286 | 0.000 | 0.524 | 0.524 | 0.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 6, of which 4 explicit and 2 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 6 | 0.333 | 0.333 | 0.333 | 0.000 | 0.333 | 0.333 | 0.667 | -0.333 |

### Resources

- **Peak RSS:** 73.8 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 13 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 3: realistic order, 120 sessions (about 300 test steps)

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ inconclusive; order carries information.** D@10 = +0.138 [-0.006, +0.245] (session BCa), D_order = +0.223 [+0.157, +0.301]. Section 7: E1′ is inconclusive or insufficient: build nothing for trails; rerun once the test steps have doubled.

### Planted structure

A log shaped like Engram's: 80 topics of 40 memories (768-d). Each topic's members vary along a 4-dimensional subspace of their own, so similarity within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, in rank order, so meaning makes every set. A footpath queries near an anchor point and then:

- stays at the anchor (p = 0.35), a re-query with large overlap, mostly Jaccard above 0.5;
- shifts to a new anchor in the same topic (p = 0.15), with partial overlap;
- jumps (p = 0.50). With p = 0.6 it goes to its topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. Otherwise it goes to a random point in a random other topic.

A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by time under one session id, as subagents do (29 of 120 sessions). 301 memories are created during the log, and 318 have no vector now (decay, about 10%).

**Required:** C1′ holds, and D_order's lower bound is above δ_order.

Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: not met** (C1′ inconclusive, order carries information).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2882 memories with a vector (episode 2156, semantic 726), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 322 distinct ids.
- **Recall rows:** 2329. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2269 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 50 days.

### The primary period

- **Recalls analysed:** 2269 in 120 sessions.
- **Split:** `T` falls on 2026-10-20 (80th percentile of recall times, rounded to the day).
- **Training:** 99 sessions with recalls before `T`, 1815 recalls, 1809 after collapse, and 1182 pairs passing the Jaccard rule. (ii) has 237702 distinct edges and (iv) has 100192.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 21, with 441 recalls; collapse merged 2 of them. That leaves 418 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 298 | 0 (0.0%) | 0 (0.0%) | 298 (100.0%) |
| > 0.5 (excluded; descriptive) | 120 | 0 (0.0%) | 23 (19.2%) | 97 (80.8%) |

- **Primary steps:** 298 in 21 sessions over 9 days. The largest session holds 8.1% of them.

- **Uptake marks** (descriptive): training recalls 1815, of which 460 were marked used (177 by `auto`). Test recalls 441, of which 110 were marked used (47 by `auto`).

#### Outcome

- **C1′ inconclusive.** D@10 = +0.138 [-0.006, +0.245] by session (21 clusters), +0.138 [-0.027, +0.257] by day (9 clusters). δ = 0.05.
- **Order carries information.** D_order = +0.223 [+0.157, +0.301] by session, +0.223 [+0.154, +0.312] by day.
- **δ_order = 0.033**, the larger of the floor 0.02 and the permutation threshold +0.033: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.017.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = +0.011 [+0.006, +0.016] by session, +0.011 [+0.004, +0.017] by day.
- **Section 7:** E1′ is inconclusive or insufficient: build nothing for trails; rerun once the test steps have doubled.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 298 | 0.057 | 0.060 | 0.245 | 0.000 | 0.000 | 0.064 | 0.104 | +0.141 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 298 | 0.101 | 0.114 | 0.275 | 0.017 | 0.017 | 0.101 | 0.138 | +0.138 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 298 | 0.124 | 0.124 | 0.292 | 0.017 | 0.017 | 0.121 | 0.154 | 0.068 | +0.138 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | +0.141 [+0.018, +0.236] | +0.141 [+0.012, +0.235] |
| 5 | +0.138 [+0.012, +0.242] | +0.138 [-0.009, +0.248] |
| 10 | +0.138 [-0.006, +0.245] | +0.138 [-0.027, +0.257] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.168 [+0.088, +0.265] |
| (i′) nearest | +0.168 [+0.089, +0.265] |
| (iii) popularity | +0.275 [+0.198, +0.369] |
| (iii-m) popularity, matched | +0.275 [+0.198, +0.368] |
| (iv) co-retrieval | +0.171 [+0.092, +0.272] |
| (v) history | +0.138 [-0.013, +0.272] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 298 primary steps (0.0%); there it equals (i).
On the 298 steps with counts, D@10 = +0.138 [-0.006, +0.249] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 298 | 0.124 | 0.124 | 0.292 | 0.017 | 0.017 | 0.121 | 0.154 | +0.138 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 11 | 1.000 | 1.000 | 0.091 | 0.091 | 0.091 | 0.909 | 0.273 | -0.909 |
| |b ∖ a| = 8+ | 287 | 0.091 | 0.091 | 0.300 | 0.014 | 0.014 | 0.091 | 0.150 | +0.150 |
| Jaccard 0 | 261 | 0.000 | 0.000 | 0.322 | 0.015 | 0.015 | 0.000 | 0.123 | +0.199 |
| Jaccard (0, 0.25] | 20 | 1.000 | 1.000 | 0.050 | 0.000 | 0.000 | 1.000 | 0.450 | -0.950 |
| Jaccard (0.25, 0.5] | 17 | 1.000 | 1.000 | 0.118 | 0.059 | 0.059 | 0.941 | 0.294 | -0.882 |
| Jaccard > 0.5 (not primary) | 97 | 0.959 | 0.928 | 0.021 | 0.021 | 0.021 | 0.784 | 0.464 | -0.938 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 15 | 137 | 0.000 | 0.067 | 0.000 | 0.133 | 0.067 | 0.000 |
| 2 | 26 | 97 | 0.115 | 0.077 | 0.000 | 0.154 | 0.154 | 0.000 |
| 3–4 | 120 | 114 | 0.275 | 0.067 | 0.000 | 0.350 | 0.133 | 0.025 |
| 5–9 | 131 | 122 | 0.275 | 0.046 | 0.000 | 0.290 | 0.107 | 0.015 |
| 10+ | 6 | 114 | 0.167 | 0.000 | 0.000 | 0.167 | 0.333 | 0.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 77, of which 49 explicit and 28 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 77 | 0.091 | 0.091 | 0.325 | 0.026 | 0.026 | 0.091 | 0.130 | +0.195 |

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 113.0 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 36 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 4: realistic noorder, 120 sessions

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.063 [-0.112, -0.033] (session BCa), D_order = -0.002 [-0.027, +0.017]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

A log shaped like Engram's: 80 topics of 40 memories (768-d). Each topic's members vary along a 4-dimensional subspace of their own, so similarity within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, in rank order, so meaning makes every set. A footpath queries near an anchor point and then:

- stays at the anchor (p = 0.35), a re-query with large overlap, mostly Jaccard above 0.5;
- shifts to a new anchor in the same topic (p = 0.15), with partial overlap;
- jumps (p = 0.50). With p = 0.6 it goes to its topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. Otherwise it goes to a random point in a random other topic.

A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by time under one session id, as subagents do (29 of 120 sessions). 301 memories are created during the log, and 318 have no vector now (decay, about 10%).

This log holds the same sessions, queries and times as realistic-order. Each session's queries are then permuted over its times. That keeps co-retrieval and who shares a session, and removes order.

**Required:** C1′ does not hold, and D_order ties.

Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2882 memories with a vector (episode 2156, semantic 726), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 322 distinct ids.
- **Recall rows:** 2329. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2269 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 50 days.

### The primary period

- **Recalls analysed:** 2269 in 120 sessions.
- **Split:** `T` falls on 2026-10-20 (80th percentile of recall times, rounded to the day).
- **Training:** 99 sessions with recalls before `T`, 1815 recalls, 1813 after collapse, and 1612 pairs passing the Jaccard rule. (ii) has 434645 distinct edges and (iv) has 100180.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 21, with 441 recalls; collapse merged 1 of them. That leaves 419 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 396 | 0 (0.0%) | 0 (0.0%) | 396 (100.0%) |
| > 0.5 (excluded; descriptive) | 23 | 0 (0.0%) | 4 (17.4%) | 19 (82.6%) |

- **Primary steps:** 396 in 21 sessions over 9 days. The largest session holds 6.3% of them.

- **Uptake marks** (descriptive): training recalls 1815, of which 462 were marked used (166 by `auto`). Test recalls 441, of which 98 were marked used (45 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.063 [-0.112, -0.033] by session (21 clusters), -0.063 [-0.116, -0.031] by day (9 clusters). δ = 0.05.
- **Order ties.** D_order = -0.002 [-0.027, +0.017] by session, -0.002 [-0.017, +0.017] by day.
- **δ_order = 0.023**, the larger of the floor 0.02 and the permutation threshold +0.023: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.010.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = +0.004 [-0.002, +0.008] by session, +0.004 [-0.002, +0.008] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 396 | 0.020 | 0.015 | 0.010 | 0.003 | 0.003 | 0.023 | 0.073 | -0.063 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 396 | 0.030 | 0.035 | 0.033 | 0.018 | 0.018 | 0.033 | 0.096 | -0.063 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 396 | 0.035 | 0.035 | 0.038 | 0.023 | 0.023 | 0.035 | 0.101 | 0.040 | -0.063 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.063 [-0.092, -0.041] | -0.063 [-0.094, -0.039] |
| 5 | -0.063 [-0.109, -0.031] | -0.063 [-0.117, -0.030] |
| 10 | -0.063 [-0.112, -0.033] | -0.063 [-0.116, -0.031] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.003 [-0.026, +0.030] |
| (i′) nearest | +0.003 [-0.026, +0.029] |
| (iii) popularity | +0.015 [-0.023, +0.042] |
| (iii-m) popularity, matched | +0.015 [-0.023, +0.042] |
| (iv) co-retrieval | +0.003 [-0.027, +0.030] |
| (v) history | -0.063 [-0.111, -0.032] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 396 primary steps (0.0%); there it equals (i).
On the 396 steps with counts, D@10 = -0.063 [-0.109, -0.032] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 396 | 0.035 | 0.035 | 0.038 | 0.023 | 0.023 | 0.035 | 0.101 | -0.063 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 2 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | -1.000 |
| |b ∖ a| = 8+ | 394 | 0.030 | 0.030 | 0.038 | 0.023 | 0.023 | 0.030 | 0.102 | -0.063 |
| Jaccard 0 | 382 | 0.000 | 0.000 | 0.039 | 0.024 | 0.024 | 0.000 | 0.099 | -0.060 |
| Jaccard (0, 0.25] | 9 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.111 | -1.000 |
| Jaccard (0.25, 0.5] | 5 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.200 | -1.000 |
| Jaccard > 0.5 (not primary) | 19 | 1.000 | 0.947 | 0.000 | 0.000 | 0.000 | 0.842 | 0.263 | -1.000 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 125 | 202 | 0.008 | 0.016 | 0.000 | 0.008 | 0.032 | 0.024 |
| 2 | 148 | 286 | 0.007 | 0.014 | 0.000 | 0.061 | 0.027 | 0.014 |
| 3–4 | 110 | 268 | 0.018 | 0.036 | 0.000 | 0.045 | 0.055 | 0.027 |
| 5–9 | 13 | 371 | 0.000 | 0.000 | 0.077 | 0.000 | 0.000 | 0.077 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 95, of which 50 explicit and 45 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 95 | 0.011 | 0.011 | 0.032 | 0.011 | 0.011 | 0.011 | 0.095 | -0.063 |

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 122.7 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 35 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 5: realistic order, 240 sessions (about 600 test steps)

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ holds; order carries information.** D@10 = +0.241 [+0.153, +0.313] (session BCa), D_order = +0.247 [+0.201, +0.294]. Section 7: E1′ holds, and order carries information: build trails from recall logs, smallest first.

### Planted structure

A log shaped like Engram's: 80 topics of 40 memories (768-d). Each topic's members vary along a 4-dimensional subspace of their own, so similarity within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, in rank order, so meaning makes every set. A footpath queries near an anchor point and then:

- stays at the anchor (p = 0.35), a re-query with large overlap, mostly Jaccard above 0.5;
- shifts to a new anchor in the same topic (p = 0.15), with partial overlap;
- jumps (p = 0.50). With p = 0.6 it goes to its topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. Otherwise it goes to a random point in a random other topic.

A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by time under one session id, as subagents do (74 of 240 sessions). 301 memories are created during the log, and 318 have no vector now (decay, about 10%).

**Required:** C1′ holds, and D_order's lower bound is above δ_order.

Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ holds, order carries information).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2882 memories with a vector (episode 2156, semantic 726), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 324 distinct ids.
- **Recall rows:** 4667. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 4607 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 50 days.

### The primary period

- **Recalls analysed:** 4607 in 240 sessions.
- **Split:** `T` falls on 2026-10-21 (80th percentile of recall times, rounded to the day).
- **Training:** 196 sessions with recalls before `T`, 3685 recalls, 3672 after collapse, and 2465 pairs passing the Jaccard rule. (ii) has 458446 distinct edges and (iv) has 112120.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 44, with 912 recalls; collapse merged 3 of them. That leaves 865 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 609 | 0 (0.0%) | 0 (0.0%) | 609 (100.0%) |
| > 0.5 (excluded; descriptive) | 256 | 0 (0.0%) | 37 (14.5%) | 219 (85.5%) |

- **Primary steps:** 609 in 44 sessions over 8 days. The largest session holds 3.9% of them.

- **Uptake marks** (descriptive): training recalls 3685, of which 962 were marked used (363 by `auto`). Test recalls 912, of which 228 were marked used (94 by `auto`).

#### Outcome

- **C1′ holds.** D@10 = +0.241 [+0.153, +0.313] by session (44 clusters), +0.241 [+0.181, +0.295] by day (8 clusters). δ = 0.05.
- **Order carries information.** D_order = +0.247 [+0.201, +0.294] by session, +0.247 [+0.216, +0.297] by day.
- **δ_order = 0.025**, the larger of the floor 0.02 and the permutation threshold +0.025: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.021.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = -0.005 [-0.013, +0.002] by session, -0.005 [-0.011, +0.001] by day.
- **Section 7:** E1′ holds, and order carries information: build trails from recall logs, smallest first.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 609 | 0.061 | 0.056 | 0.355 | 0.011 | 0.011 | 0.067 | 0.094 | +0.261 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 609 | 0.107 | 0.122 | 0.373 | 0.020 | 0.020 | 0.112 | 0.123 | +0.250 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 609 | 0.125 | 0.128 | 0.378 | 0.028 | 0.028 | 0.126 | 0.136 | 0.131 | +0.241 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | +0.261 [+0.171, +0.336] | +0.261 [+0.182, +0.330] |
| 5 | +0.250 [+0.173, +0.323] | +0.250 [+0.201, +0.301] |
| 10 | +0.241 [+0.153, +0.313] | +0.241 [+0.181, +0.295] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.253 [+0.195, +0.314] |
| (i′) nearest | +0.250 [+0.191, +0.312] |
| (iii) popularity | +0.350 [+0.285, +0.415] |
| (iii-m) popularity, matched | +0.350 [+0.288, +0.417] |
| (iv) co-retrieval | +0.251 [+0.192, +0.314] |
| (v) history | +0.241 [+0.142, +0.333] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 609 primary steps (0.0%); there it equals (i).
On the 609 steps with counts, D@10 = +0.241 [+0.151, +0.313] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 609 | 0.125 | 0.128 | 0.378 | 0.028 | 0.028 | 0.126 | 0.136 | +0.241 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 25 | 0.920 | 1.000 | 0.000 | 0.080 | 0.080 | 0.960 | 0.360 | -1.000 |
| |b ∖ a| = 8+ | 584 | 0.091 | 0.091 | 0.394 | 0.026 | 0.026 | 0.091 | 0.127 | +0.267 |
| Jaccard 0 | 531 | 0.000 | 0.000 | 0.429 | 0.028 | 0.028 | 0.000 | 0.100 | +0.330 |
| Jaccard (0, 0.25] | 43 | 1.000 | 1.000 | 0.023 | 0.000 | 0.000 | 1.000 | 0.442 | -0.977 |
| Jaccard (0.25, 0.5] | 35 | 0.943 | 1.000 | 0.029 | 0.057 | 0.057 | 0.971 | 0.314 | -0.971 |
| Jaccard > 0.5 (not primary) | 219 | 0.968 | 0.936 | 0.018 | 0.018 | 0.018 | 0.881 | 0.388 | -0.950 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 2 | 183 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 2 | 11 | 200 | 0.273 | 0.091 | 0.091 | 0.364 | 0.182 | 0.091 |
| 3–4 | 26 | 213 | 0.346 | 0.077 | 0.038 | 0.385 | 0.154 | 0.038 |
| 5–9 | 379 | 243 | 0.354 | 0.066 | 0.011 | 0.385 | 0.124 | 0.026 |
| 10+ | 191 | 232 | 0.366 | 0.047 | 0.005 | 0.366 | 0.120 | 0.026 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 163, of which 95 explicit and 68 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 163 | 0.086 | 0.086 | 0.387 | 0.043 | 0.043 | 0.086 | 0.117 | +0.270 |

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 161.5 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 90 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 6: realistic noorder, 240 sessions

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.034 [-0.061, -0.007] (session BCa), D_order = -0.007 [-0.022, +0.009]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

A log shaped like Engram's: 80 topics of 40 memories (768-d). Each topic's members vary along a 4-dimensional subspace of their own, so similarity within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, in rank order, so meaning makes every set. A footpath queries near an anchor point and then:

- stays at the anchor (p = 0.35), a re-query with large overlap, mostly Jaccard above 0.5;
- shifts to a new anchor in the same topic (p = 0.15), with partial overlap;
- jumps (p = 0.50). With p = 0.6 it goes to its topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. Otherwise it goes to a random point in a random other topic.

A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by time under one session id, as subagents do (74 of 240 sessions). 301 memories are created during the log, and 318 have no vector now (decay, about 10%).

This log holds the same sessions, queries and times as realistic-order. Each session's queries are then permuted over its times. That keeps co-retrieval and who shares a session, and removes order.

**Required:** C1′ does not hold, and D_order ties.

Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2882 memories with a vector (episode 2156, semantic 726), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 324 distinct ids.
- **Recall rows:** 4667. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 4607 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 50 days.

### The primary period

- **Recalls analysed:** 4607 in 240 sessions.
- **Split:** `T` falls on 2026-10-21 (80th percentile of recall times, rounded to the day).
- **Training:** 196 sessions with recalls before `T`, 3685 recalls, 3682 after collapse, and 3278 pairs passing the Jaccard rule. (ii) has 845387 distinct edges and (iv) has 112112.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 44, with 912 recalls; collapse merged 1 of them. That leaves 867 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 830 | 0 (0.0%) | 0 (0.0%) | 830 (100.0%) |
| > 0.5 (excluded; descriptive) | 37 | 0 (0.0%) | 8 (21.6%) | 29 (78.4%) |

- **Primary steps:** 830 in 44 sessions over 8 days. The largest session holds 3.0% of them.

- **Uptake marks** (descriptive): training recalls 3685, of which 915 were marked used (368 by `auto`). Test recalls 912, of which 213 were marked used (94 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.034 [-0.061, -0.007] by session (44 clusters), -0.034 [-0.056, -0.019] by day (8 clusters). δ = 0.05.
- **Order ties.** D_order = -0.007 [-0.022, +0.009] by session, -0.007 [-0.023, +0.007] by day.
- **δ_order = 0.020**, the larger of the floor 0.02 and the permutation threshold +0.011: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.007.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = +0.001 [-0.002, +0.005] by session, +0.001 [-0.002, +0.005] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 830 | 0.020 | 0.022 | 0.019 | 0.012 | 0.012 | 0.027 | 0.066 | -0.047 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 830 | 0.040 | 0.042 | 0.037 | 0.023 | 0.023 | 0.039 | 0.084 | -0.047 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 830 | 0.042 | 0.043 | 0.053 | 0.043 | 0.043 | 0.043 | 0.087 | 0.060 | -0.034 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.047 [-0.067, -0.026] | -0.047 [-0.058, -0.041] |
| 5 | -0.047 [-0.074, -0.024] | -0.047 [-0.078, -0.033] |
| 10 | -0.034 [-0.061, -0.007] | -0.034 [-0.056, -0.019] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.011 [-0.011, +0.032] |
| (i′) nearest | +0.010 [-0.012, +0.031] |
| (iii) popularity | +0.010 [-0.022, +0.039] |
| (iii-m) popularity, matched | +0.010 [-0.020, +0.039] |
| (iv) co-retrieval | +0.010 [-0.012, +0.031] |
| (v) history | -0.034 [-0.061, -0.007] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 830 primary steps (0.0%); there it equals (i).
On the 830 steps with counts, D@10 = -0.034 [-0.061, -0.008] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 830 | 0.042 | 0.043 | 0.053 | 0.043 | 0.043 | 0.043 | 0.087 | -0.034 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 10 | 0.900 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.100 | -1.000 |
| |b ∖ a| = 8+ | 820 | 0.032 | 0.032 | 0.054 | 0.044 | 0.044 | 0.032 | 0.087 | -0.033 |
| Jaccard 0 | 794 | 0.000 | 0.000 | 0.055 | 0.045 | 0.045 | 0.000 | 0.082 | -0.026 |
| Jaccard (0, 0.25] | 21 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.190 | -1.000 |
| Jaccard (0.25, 0.5] | 15 | 0.933 | 1.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.200 | -1.000 |
| Jaccard > 0.5 (not primary) | 29 | 0.931 | 0.966 | 0.034 | 0.000 | 0.000 | 0.931 | 0.138 | -0.931 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 83 | 438 | 0.000 | 0.036 | 0.012 | 0.012 | 0.048 | 0.036 |
| 2 | 198 | 453 | 0.040 | 0.020 | 0.025 | 0.086 | 0.040 | 0.045 |
| 3–4 | 407 | 502 | 0.017 | 0.012 | 0.007 | 0.052 | 0.037 | 0.044 |
| 5–9 | 142 | 460 | 0.007 | 0.035 | 0.007 | 0.035 | 0.056 | 0.042 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 199, of which 111 explicit and 88 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 199 | 0.030 | 0.030 | 0.045 | 0.065 | 0.065 | 0.030 | 0.095 | -0.050 |

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 192.3 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 83 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 7: the Pi's own store (rio-grande), read-only

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**Insufficient: 0 test steps (needs 200); 0 test sessions (needs 20).** The run claims nothing.

### The store as read

- **Source:** the live store file, opened with a `mode=ro` URI and `query_only`, and read in one read transaction. No copy was made.
- **Config check:** 3 places looked at (1 named with `--config`). 1 `config.toml` found, with recency_mode: tiebreak. Nothing overrides `tiebreak`.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 45 memories with a vector (episode 33, semantic 12), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 0 distinct ids.
- **Recall rows:** 5. Unparseable: 0. With no session id: 0. Instinct layer: 0 in the primary period and 0 before it (left out and reported apart). Analysed: 5 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 1 day.

### The primary period

- **Recalls analysed:** 5 in 1 session.
- **Split:** `T` falls on 2026-11-03 (80th percentile of recall times, rounded to the day).
- **Training:** 1 session with recalls before `T`, 4 recalls, 3 after collapse, and 2 pairs passing the Jaccard rule. (ii) has 5 distinct edges and (iv) has 12.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 0, with 0 recalls; collapse merged 0 of them. That leaves 0 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 0 | 0 | 0 | 0 |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 0 in 0 sessions over 0 days. The largest session holds 0.0% of them.

- **Uptake marks** (descriptive): training recalls 4, of which 0 were marked used (0 by `auto`). Test recalls 0, of which 0 were marked used (0 by `auto`).

#### Outcome

**Insufficient:** 0 test steps (needs 200); 0 test sessions (needs 20). The run claims nothing and computes no interval.

No primary steps, so no hit rates.

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 48.2 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 0 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 8: permuted check: simple order, real order replaced by a shuffle

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.121 [-0.159, -0.083] (session BCa), D_order = +0.011 [-0.020, +0.045]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

128 groups of 12 memories (768-d, each group tight in meaning). There are 120 regular groups and 8 hub groups, and each regular group has a fixed hub. A session takes one regular group per hub, in random order, and recalls each group and then its hub, 16 recalls of 6 random members each. A memory is followed by a specific next set, and every hub sits in every session, so only order says which hub follows.

**The permuted check.** Before anything was computed, each session's real order was replaced by one more seeded shuffle of its recalls over their times (`--permute-real`). Real order is then just another shuffle.

**Required:** D_order ties.

Both simple logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), and empty recalls (2%).
Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 1836 memories with a vector (episode 1452, semantic 384), dimension 768. Left out: 10 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 7 distinct ids.
- **Recall rows:** 3007. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2737 in the primary period (from 2026-09-02, engram 548c97dd) and 210 in the additive period before it.
- **Recall days:** the analysed recalls span 71 days.

### The primary period

- **Recalls analysed:** 2737 in 160 sessions.
- **Split:** `T` falls on 2026-10-19 (80th percentile of recall times, rounded to the day).
- **Training:** 129 sessions with recalls before `T`, 2189 recalls, 2180 after collapse, and 2051 pairs passing the Jaccard rule. (ii) has 59794 distinct edges and (iv) has 14690.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 31, with 539 recalls; collapse merged 6 of them. That leaves 502 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 502 | 11 (2.2%) | 12 (2.4%) | 479 (95.4%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 479 in 31 sessions over 8 days. The largest session holds 3.8% of them.

- **Uptake marks** (descriptive): training recalls 2189, of which 536 were marked used (209 by `auto`). Test recalls 539, of which 137 were marked used (52 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.121 [-0.159, -0.083] by session (31 clusters), -0.121 [-0.154, -0.094] by day (8 clusters). δ = 0.05.
- **Order ties.** D_order = +0.011 [-0.020, +0.045] by session, +0.011 [-0.014, +0.048] by day.
- **δ_order = 0.020**, the larger of the floor 0.02 and the permutation threshold +0.019: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.011.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = +0.003 [-0.007, +0.013] by session, +0.003 [-0.006, +0.012] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 479 | 0.000 | 0.000 | 0.033 | 0.029 | 0.029 | 0.000 | 0.006 | +0.004 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 479 | 0.000 | 0.000 | 0.104 | 0.171 | 0.171 | 0.000 | 0.006 | -0.067 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 479 | 0.013 | 0.013 | 0.150 | 0.271 | 0.271 | 0.013 | 0.019 | 0.140 | -0.121 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | +0.004 [-0.015, +0.021] | +0.004 [-0.020, +0.020] |
| 5 | -0.067 [-0.100, -0.032] | -0.067 [-0.086, -0.041] |
| 10 | -0.121 [-0.159, -0.083] | -0.121 [-0.154, -0.094] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.138 [+0.106, +0.173] |
| (i′) nearest | +0.138 [+0.105, +0.172] |
| (iii) popularity | -0.121 [-0.160, -0.084] |
| (iii-m) popularity, matched | -0.121 [-0.160, -0.083] |
| (iv) co-retrieval | +0.138 [+0.106, +0.172] |
| (v) history | +0.132 [+0.101, +0.167] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 479 primary steps (0.0%); there it equals (i).
On the 479 steps with counts, D@10 = -0.121 [-0.159, -0.082] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 479 | 0.013 | 0.013 | 0.150 | 0.271 | 0.271 | 0.013 | 0.019 | -0.121 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 479 | 0.013 | 0.013 | 0.150 | 0.271 | 0.271 | 0.013 | 0.019 | -0.121 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 479 | 0.013 | 0.013 | 0.150 | 0.271 | 0.271 | 0.013 | 0.019 | -0.121 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 93 | 40 | 0.000 | 0.000 | 0.011 | 0.075 | 0.022 | 0.258 |
| 2 | 130 | 48 | 0.023 | 0.000 | 0.031 | 0.108 | 0.000 | 0.292 |
| 3–4 | 17 | 62 | 0.000 | 0.000 | 0.059 | 0.000 | 0.000 | 0.294 |
| 5–9 | 239 | 440 | 0.054 | 0.000 | 0.033 | 0.213 | 0.017 | 0.264 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 128, of which 80 explicit and 48 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 128 | 0.000 | 0.008 | 0.188 | 0.234 | 0.234 | 0.000 | 0.016 | -0.047 |

### The additive period (reported apart)

- **Recalls analysed:** 210 in 12 sessions.
- **Split:** `T` falls on 2026-08-29 (80th percentile of recall times, rounded to the day).
- **Training:** 10 sessions with recalls before `T`, 168 recalls, 167 after collapse, and 157 pairs passing the Jaccard rule. (ii) has 5321 distinct edges and (iv) has 3142.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 2, with 36 recalls; collapse merged 1 of them. That leaves 33 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 33 | 2 (6.1%) | 2 (6.1%) | 29 (87.9%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 29 in 2 sessions over 2 days. The largest session holds 51.7% of them.

- **Uptake marks** (descriptive): training recalls 168, of which 51 were marked used (22 by `auto`). Test recalls 36, of which 3 were marked used (0 by `auto`).

#### Outcome (secondary, decides nothing)

**Insufficient:** 29 test steps (needs 200); 2 test sessions (needs 20); one session holds 52% of the steps (at most 15%). The run claims nothing and computes no interval.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 29 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | +0.000 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 29 | 0.000 | 0.000 | 0.034 | 0.207 | 0.103 | 0.000 | 0.000 | -0.172 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 29 | 0.000 | 0.000 | 0.069 | 0.310 | 0.207 | 0.000 | 0.000 | 0.033 | -0.241 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 5 of 29 primary steps (17.2%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 24 | 0.000 | 0.000 | 0.083 | 0.250 | 0.250 | 0.000 | 0.000 | -0.167 |
| without counts | 5 | 0.000 | 0.000 | 0.000 | 0.600 | 0.000 | 0.000 | 0.000 | -0.600 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 29 | 0.000 | 0.000 | 0.069 | 0.310 | 0.207 | 0.000 | 0.000 | -0.241 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 29 | 0.000 | 0.000 | 0.069 | 0.310 | 0.207 | 0.000 | 0.000 | -0.241 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 5 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.600 |
| 1 | 13 | 12 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.231 |
| 2 | 11 | 51 | 0.000 | 0.000 | 0.000 | 0.182 | 0.000 | 0.273 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 3, of which 3 explicit and 0 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 3 | 0.000 | 0.000 | 0.000 | 0.333 | 0.333 | 0.000 | 0.000 | -0.333 |

### Resources

- **Peak RSS:** 76.2 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 22 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 9: permuted check: simple noorder, real order replaced by a shuffle

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.438 [-0.510, -0.371] (session BCa), D_order = +0.015 [-0.023, +0.044]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

150 groups of 12 memories (768-d, each group tight in meaning). A session takes 2 groups and makes 12 recalls, each drawing 6 random members from one of the two at random. Memories are co-retrieved within a group, and order within a session is exchangeable.

**The permuted check.** Before anything was computed, each session's real order was replaced by one more seeded shuffle of its recalls over their times (`--permute-real`). Real order is then just another shuffle.

**Required:** D_order ties.

Both simple logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), and empty recalls (2%).
Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2100 memories with a vector (episode 1656, semantic 444), dimension 768. Left out: 10 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 7 distinct ids.
- **Recall rows:** 2262. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2047 in the primary period (from 2026-09-02, engram 548c97dd) and 155 in the additive period before it.
- **Recall days:** the analysed recalls span 71 days.

### The primary period

- **Recalls analysed:** 2047 in 160 sessions.
- **Split:** `T` falls on 2026-10-15 (80th percentile of recall times, rounded to the day).
- **Training:** 128 sessions with recalls before `T`, 1637 recalls, 1627 after collapse, and 1474 pairs passing the Jaccard rule. (ii) has 28319 distinct edges and (iv) has 15002.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 32, with 409 recalls; collapse merged 2 of them. That leaves 375 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 369 | 5 (1.4%) | 3 (0.8%) | 361 (97.8%) |
| > 0.5 (excluded; descriptive) | 6 | 0 (0.0%) | 0 (0.0%) | 6 (100.0%) |

- **Primary steps:** 361 in 32 sessions over 12 days. The largest session holds 3.9% of them.

- **Uptake marks** (descriptive): training recalls 1637, of which 387 were marked used (161 by `auto`). Test recalls 409, of which 103 were marked used (42 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.438 [-0.510, -0.371] by session (32 clusters), -0.438 [-0.511, -0.355] by day (12 clusters). δ = 0.05.
- **Order ties.** D_order = +0.015 [-0.023, +0.044] by session, +0.015 [-0.029, +0.041] by day.
- **δ_order = 0.026**, the larger of the floor 0.02 and the permutation threshold +0.026: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.025.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = -0.001 [-0.015, +0.017] by session, -0.001 [-0.017, +0.014] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 361 | 0.260 | 0.258 | 0.089 | 0.000 | 0.025 | 0.269 | 0.244 | -0.180 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 361 | 0.507 | 0.507 | 0.227 | 0.006 | 0.050 | 0.507 | 0.579 | -0.352 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 361 | 0.512 | 0.510 | 0.382 | 0.006 | 0.050 | 0.512 | 0.820 | 0.367 | -0.438 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.180 [-0.221, -0.130] | -0.180 [-0.215, -0.119] |
| 5 | -0.352 [-0.425, -0.270] | -0.352 [-0.452, -0.252] |
| 10 | -0.438 [-0.510, -0.371] | -0.438 [-0.511, -0.355] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | -0.130 [-0.181, -0.089] |
| (i′) nearest | -0.127 [-0.180, -0.089] |
| (iii) popularity | +0.377 [+0.320, +0.443] |
| (iii-m) popularity, matched | +0.332 [+0.272, +0.405] |
| (iv) co-retrieval | -0.130 [-0.182, -0.089] |
| (v) history | -0.438 [-0.508, -0.372] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 46 of 361 primary steps (12.7%); there it equals (i).
On the 315 steps with counts, D@10 = -0.422 [-0.495, -0.353] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 315 | 0.537 | 0.533 | 0.387 | 0.006 | 0.006 | 0.537 | 0.810 | -0.422 |
| without counts | 46 | 0.348 | 0.348 | 0.348 | 0.000 | 0.348 | 0.348 | 0.891 | -0.543 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 138 | 1.000 | 1.000 | 0.710 | 0.000 | 0.087 | 1.000 | 0.804 | -0.290 |
| |b ∖ a| = 4–7 | 223 | 0.211 | 0.206 | 0.179 | 0.009 | 0.027 | 0.211 | 0.830 | -0.650 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 178 | 0.011 | 0.006 | 0.000 | 0.011 | 0.011 | 0.011 | 0.831 | -0.831 |
| Jaccard (0, 0.25] | 45 | 1.000 | 1.000 | 0.889 | 0.000 | 0.089 | 1.000 | 0.822 | -0.111 |
| Jaccard (0.25, 0.5] | 138 | 1.000 | 1.000 | 0.710 | 0.000 | 0.087 | 1.000 | 0.804 | -0.290 |
| Jaccard > 0.5 (not primary) | 6 | 1.000 | 1.000 | 0.667 | 0.000 | 0.000 | 1.000 | 0.500 | -0.333 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 46 | 0 | 0.196 | 0.196 | 0.000 | 0.348 | 0.348 | 0.000 |
| 1 | 233 | 23 | 0.021 | 0.288 | 0.000 | 0.361 | 0.562 | 0.009 |
| 2 | 56 | 23 | 0.232 | 0.196 | 0.000 | 0.482 | 0.482 | 0.000 |
| 3–4 | 26 | 36 | 0.192 | 0.269 | 0.000 | 0.423 | 0.423 | 0.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 94, of which 54 explicit and 40 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 94 | 0.543 | 0.543 | 0.383 | 0.000 | 0.021 | 0.543 | 0.787 | -0.404 |

### The additive period (reported apart)

- **Recalls analysed:** 155 in 12 sessions.
- **Split:** `T` falls on 2026-08-29 (80th percentile of recall times, rounded to the day).
- **Training:** 10 sessions with recalls before `T`, 124 recalls, 123 after collapse, and 111 pairs passing the Jaccard rule. (ii) has 2271 distinct edges and (iv) has 1710.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 2, with 25 recalls; collapse merged 0 of them. That leaves 23 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 23 | 1 (4.3%) | 1 (4.3%) | 21 (91.3%) |
| > 0.5 (excluded; descriptive) | 0 | 0 | 0 | 0 |

- **Primary steps:** 21 in 2 sessions over 2 days. The largest session holds 52.4% of them.

- **Uptake marks** (descriptive): training recalls 124, of which 31 were marked used (9 by `auto`). Test recalls 25, of which 8 were marked used (2 by `auto`).

#### Outcome (secondary, decides nothing)

**Insufficient:** 21 test steps (needs 200); 2 test sessions (needs 20); one session holds 52% of the steps (at most 15%). The run claims nothing and computes no interval.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.333 | 0.238 | 0.333 | 0.000 | 0.333 | 0.333 | 0.143 | +0.000 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.381 | +0.000 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.714 | 0.524 | -0.190 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 21 of 21 primary steps (100.0%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 0 | | | | | | | | |
| without counts | 21 | 0.524 | 0.524 | 0.524 | 0.000 | 0.524 | 0.524 | 0.714 | -0.190 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 8 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.750 | +0.000 |
| |b ∖ a| = 4–7 | 13 | 0.231 | 0.231 | 0.231 | 0.000 | 0.231 | 0.231 | 0.692 | -0.462 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 10 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.800 | -0.800 |
| Jaccard (0, 0.25] | 3 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.333 | +0.000 |
| Jaccard (0.25, 0.5] | 8 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.750 | +0.000 |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 21 | 0 | 0.333 | 0.333 | 0.000 | 0.524 | 0.524 | 0.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 7, of which 6 explicit and 1 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 7 | 0.571 | 0.571 | 0.571 | 0.000 | 0.571 | 0.571 | 0.571 | +0.000 |

### Resources

- **Peak RSS:** 73.3 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 15 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 10: permuted check: realistic order, 240 sessions, real order replaced by a shuffle

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `e0e8b5a6a23f506d`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.052 [-0.077, -0.025] (session BCa), D_order = +0.002 [-0.010, +0.013]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

A log shaped like Engram's: 80 topics of 40 memories (768-d). Each topic's members vary along a 4-dimensional subspace of their own, so similarity within a topic is graded, as in real embeddings. A recall returns the {lo_m} to {hi_m} memories nearest its query among those created by then, in rank order, so meaning makes every set. A footpath queries near an anchor point and then:

- stays at the anchor (p = 0.35), a re-query with large overlap, mostly Jaccard above 0.5;
- shifts to a new anchor in the same topic (p = 0.15), with partial overlap;
- jumps (p = 0.50). With p = 0.6 it goes to its topic's fixed next set, a fixed anchor in a fixed other topic: the planted order effect. Otherwise it goes to a random point in a random other topic.

A session is one footpath of 12 to 24 recalls, or two footpaths of 8 to 14 recalls interleaved by time under one session id, as subagents do (74 of 240 sessions). 301 memories are created during the log, and 318 have no vector now (decay, about 10%).

**The permuted check.** Before anything was computed, each session's real order was replaced by one more seeded shuffle of its recalls over their times (`--permute-real`). Real order is then just another shuffle.

**Required:** D_order ties.

Every synthetic log also carries 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed** (C1′ fails, order ties).

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Classifier:** 48 boundary checks of the four outcomes passed before the store was read.
- **Universe:** 2882 memories with a vector (episode 2156, semantic 726), dimension 768. Left out: 0 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 324 distinct ids.
- **Recall rows:** 4667. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 4607 in the primary period (from 2026-09-02, engram 548c97dd) and 0 in the additive period before it.
- **Recall days:** the analysed recalls span 50 days.

### The primary period

- **Recalls analysed:** 4607 in 240 sessions.
- **Split:** `T` falls on 2026-10-21 (80th percentile of recall times, rounded to the day).
- **Training:** 196 sessions with recalls before `T`, 3685 recalls, 3683 after collapse, and 3272 pairs passing the Jaccard rule. (ii) has 852449 distinct edges and (iv) has 112124.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 44, with 912 recalls; collapse merged 0 of them. That leaves 868 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 826 | 0 (0.0%) | 0 (0.0%) | 826 (100.0%) |
| > 0.5 (excluded; descriptive) | 42 | 0 (0.0%) | 4 (9.5%) | 38 (90.5%) |

- **Primary steps:** 826 in 44 sessions over 8 days. The largest session holds 3.0% of them.

- **Uptake marks** (descriptive): training recalls 3685, of which 962 were marked used (364 by `auto`). Test recalls 912, of which 228 were marked used (94 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.052 [-0.077, -0.025] by session (44 clusters), -0.052 [-0.066, -0.037] by day (8 clusters). δ = 0.05.
- **Order ties.** D_order = +0.002 [-0.010, +0.013] by session, +0.002 [-0.009, +0.012] by day.
- **δ_order = 0.020**, the larger of the floor 0.02 and the permutation threshold +0.003: the 95th percentile, over set B's 20 shuffles, of one shuffle's hit@10 minus set A's average. One shuffle's hit@10 varies with SD 0.004.
- **Null of the null** (descriptive): D_null = hit@10(set B's average) − hit@10(set A's average) = -0.001 [-0.004, +0.003] by session, -0.001 [-0.003, +0.002] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 826 | 0.011 | 0.015 | 0.022 | 0.011 | 0.011 | 0.015 | 0.077 | -0.056 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 826 | 0.027 | 0.025 | 0.044 | 0.022 | 0.022 | 0.027 | 0.097 | -0.053 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 826 | 0.029 | 0.030 | 0.054 | 0.041 | 0.041 | 0.029 | 0.107 | 0.053 | -0.052 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.056 [-0.077, -0.037] | -0.056 [-0.080, -0.038] |
| 5 | -0.053 [-0.076, -0.029] | -0.053 [-0.068, -0.039] |
| 10 | -0.052 [-0.077, -0.025] | -0.052 [-0.066, -0.037] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.025 [+0.006, +0.045] |
| (i′) nearest | +0.024 [+0.005, +0.043] |
| (iii) popularity | +0.013 [-0.013, +0.039] |
| (iii-m) popularity, matched | +0.013 [-0.014, +0.039] |
| (iv) co-retrieval | +0.025 [+0.007, +0.044] |
| (v) history | -0.052 [-0.077, -0.025] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 826 primary steps (0.0%); there it equals (i).
On the 826 steps with counts, D@10 = -0.052 [-0.077, -0.025] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 826 | 0.029 | 0.030 | 0.054 | 0.041 | 0.041 | 0.029 | 0.107 | -0.052 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 1 | 1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | -1.000 |
| |b ∖ a| = 4–7 | 7 | 0.857 | 1.000 | 0.286 | 0.000 | 0.000 | 1.000 | 0.429 | -0.714 |
| |b ∖ a| = 8+ | 818 | 0.021 | 0.021 | 0.053 | 0.042 | 0.042 | 0.021 | 0.104 | -0.051 |
| Jaccard 0 | 801 | 0.000 | 0.000 | 0.050 | 0.041 | 0.041 | 0.000 | 0.101 | -0.051 |
| Jaccard (0, 0.25] | 13 | 1.000 | 1.000 | 0.231 | 0.077 | 0.077 | 1.000 | 0.231 | -0.769 |
| Jaccard (0.25, 0.5] | 12 | 0.917 | 1.000 | 0.167 | 0.000 | 0.000 | 0.917 | 0.333 | -0.833 |
| Jaccard > 0.5 (not primary) | 38 | 0.895 | 0.947 | 0.000 | 0.000 | 0.000 | 0.895 | 0.237 | -0.947 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 1 | 100 | 425 | 0.000 | 0.010 | 0.010 | 0.010 | 0.020 | 0.040 |
| 2 | 253 | 480 | 0.020 | 0.012 | 0.016 | 0.059 | 0.032 | 0.047 |
| 3–4 | 404 | 516 | 0.025 | 0.012 | 0.007 | 0.057 | 0.035 | 0.037 |
| 5–9 | 69 | 551 | 0.043 | 0.000 | 0.014 | 0.087 | 0.000 | 0.043 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 206, of which 126 explicit and 80 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 206 | 0.029 | 0.029 | 0.044 | 0.058 | 0.058 | 0.029 | 0.097 | -0.053 |

### The additive period (reported apart)

No analysed recalls in the additive period.

### Resources

- **Peak RSS:** 192.3 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 96 s.
- **Scratch:** none. Vectors stayed in memory.

## What all the runs share

### Pre-registered rules (section 6′, implemented as written)

- **Steps:** recalls in time order per session, with consecutive repeats of an id set collapsed. A step `a → b` counts when Jaccard(a, b) ≤ 0.5. The target is `b ∖ a` within the universe (a vector now, `created_at` ≤ `b`'s time). A step is dropped when `a` has no vectors or its target is empty.
- **Period and split:** the primary period starts at the `tiebreak` default's commit. `T` is the 80th percentile of recall times in the period. Training is pairs wholly before `T` inside the period, and test is sessions whose first recall is after `T`. Instinct recalls are excluded.
- **Arms:** (i), (i′), (ii), (iii) pure, (iii) matched, (iv) and (v), each a ranking of 10 memories excluding `a`'s ids, each backfilled by (i).
- **Outcome:** D = hit@10(ii) − max(i, i′, iii, iii-m, iv, v), with the max inside each resample, and a bootstrap clustered by session (10,000 resamples, BCa, jackknife acceleration), δ = 0.05. **Holds:** the lower bound is above 0 and the upper bound is at least δ. **Negligible:** the lower bound is above 0 and the upper bound is below δ (real, but it builds nothing). **Fails:** the upper bound is below δ and the lower bound isn't above 0. **Inconclusive:** anything else, or when the day-clustered bootstrap's outcome differs. The classifier is checked at each boundary before every run.
- **Insufficient:** fewer than 200 test steps, fewer than 20 test sessions, or one session above 15% of the steps.
- **Order:** (ii) retrained on each training session in shuffled order (20 seeded shuffles, averaged). The training sequence is collapsed once, from real order. The shuffles permute those runs, and pairs then follow the Jaccard rule and the mirroring, with no re-collapse. Evaluation steps are the same in every arm. D_order = hit@10(ii) − hit@10(ii-s). A second, independent set of 20 shuffles against the first gives the null of the null, D_null (descriptive). Order carries information only if D_order's lower bound is above δ_order = max(0.02, the 95th percentile over set B's 20 shuffles of that single shuffle's hit@10 minus set A's average): a permutation threshold. The day bootstrap must agree.

### Choices this script made where the plan leaves one

1. **Primary period.** It starts at the commit time of engram `548c97dd` (2026-09-02 03:08 UTC), the commit that made `tiebreak` the default. Recalls at or after it are primary; earlier ones form the additive period.
2. **Config check.** It looks at `config.toml` in the store's directory, in every `.engram` directory above the store, and in each `--config` file. The run stops if any sets `[memory] recency_mode` to anything but `tiebreak`, or can't be read. Engram's server reads the config of the session's project root, which the script can't find by itself, so a real run names each project's `.engram/config.toml` with `--config`.
3. **Left out and counted.** Recalls with no session id (or a `context` that isn't valid JSON), and rows whose time or `target_ids` can't be parsed.
4. **Instinct recalls.** They're removed before footpaths are built, so they don't split a session's sequence, and counted apart. No arm can rank them: instincts have no vectors in the universe.
5. **Order and collapse.** Recalls are ordered by time, then by recall id for equal times. Consecutive recalls with the same id set (as a set) merge into one run, which takes its first recall's time. The run counts as used if any member was used, and as explicit if any member was used without `auto`.
6. **Jaccard.** Jaccard and collapse use the logged id sets, instinct ids included. Jaccard(∅, ∅) = 1.
7. **Cutoff.** `T` is numpy's linearly interpolated 80th percentile of the times of the period's analysed recalls (not instinct, with a session id), taken before collapse.
8. **Training and test.** A session's training sequence is its recalls before `T`, collapsed. A test session's first recall is strictly after `T`. A session that spans `T` gives training pairs before `T` and no test steps.
9. **Training pairs.** They follow the Jaccard rule but not the test's vector and target rules. A pair with nothing new in `b` adds no counts.
10. **Popularity and co-retrieval.** Both count the collapsed training recalls, each run once.
11. **Which ids count.** (ii) and (iv) sum counts over all of `a`'s logged ids, with or without a vector. The meaning arms use `a`'s ids that are in the universe at `b`'s time.
12. **hit@k.** A step hits when any target id is among the arm's first k.
13. **Ties.** Count arms order by count, then by (i)'s order (dot with `a`'s centroid), then by code (`created_at` order). (i) and (i′) break exact ties by code.
14. **History (v).** It walks back through the session's collapsed recalls before `a`, newest first, taking ids in each recall's logged order and skipping `a`'s ids and ids outside the universe.
15. **Matched popularity.** Slots = min(10, the number of candidates with a positive (ii) score). The slots fill by popularity, then the rest by (i).
16. **Shuffles.** As section 6′ now says, each training session's pre-`T` recalls are collapsed once, from real order. Each shuffle permutes those runs with a seeded generator, then forms consecutive pairs and applies the Jaccard rule and the `b ∖ a` mirroring. It never re-collapses. Per-step hit@10 is averaged over the 20 shuffles.
17. **Day clusters.** The UTC day of the session's first recall, so each session sits in one day.
18. **BCa.** 10,000 multinomial cluster resamples, seeded. `z0` comes from the share of resamples below the estimate, with ties counting half, clipped to [0.5/B, 1 − 0.5/B]. The acceleration comes from the leave-one-cluster-out jackknife.
19. **Shuffle sets.** Set A uses seed streams (seed, period, j) and set B uses (seed, period, 1, j), for j = 0 to 19. Set A's average gives D_order. D_null = hit@10(set B's average) − hit@10(set A's average) is reported beside it (descriptive), with the very resample draws of D_order's bootstraps.
20. **Order.** δ_order = max(0.02, the permutation threshold), where the threshold is numpy's linear 95th percentile, over set B's 20 shuffles, of (that shuffle's hit@10 − set A's average) on the primary steps. "Order carries information" needs D_order's session BCa lower bound above δ_order and its day BCa lower bound above the same δ_order.
21. **Permuted check.** `--permute-real` (synthetic logs only) replaces each session's real order with one more seeded shuffle of its recalls over their times before anything is computed. Order must then tie.
22. **Insufficient.** Test sessions are those with at least one primary step. When the data are insufficient, no interval is computed: only counts and point hit rates appear.
23. **Additive period.** It runs the same pipeline on its own: its own `T`, with training inside it. It's secondary and decides nothing.
24. **Universe.** A vector with no `created_at` row, or a zero norm, is left out and counted. An id in both vector tables is kept once.
25. **C2 analogue.** `y*` is (ii)'s top memory and `x*` the id in `a` with the largest c(x, y*). Support is the number of distinct training sessions with a pair carrying x* → y*.

### Named, not modelled

- **Meaning made the targets.** Returned ids are ranked by similarity to each query, so meaning starts ahead by construction. A use win is strong evidence, and a tie says little.
- **Dream and instinct biases** are blended into the query vector, and aren't modelled.
- **Interleaved footpaths.** Claude Code subagents share their parent's Engram server, so their recalls interleave under one session id. This blurs order.
- **Access-driven decay** removes rarely used episodes' vectors. The universe uses vectors present now.
- **The config check sees today's files.** It can't show what a config said in the past.
