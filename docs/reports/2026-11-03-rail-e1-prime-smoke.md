# E1′ smoke runs: the script on planted logs and on the Pi's own store

2026-11-03. Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e).
Script: `scripts/rail_e1_prime.py`, sha256 `9d5590be37150ffb…`. Section 6′ asks for these runs before Andy's store.
(ii) must **hold** on a planted order effect and must **not hold** on a no-order one. The Pi's store shows the floor
working on a real schema.

The script has **not** run on Andy's store or on any Mac. That run is his decision, made after he reads the script and
this report. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

## Summary

| run | primary steps / sessions | C1′ | D@10, session BCa | D@10, day BCa | D_order, session BCa | D_order, day BCa | required | met |
|---|---|---|---|---|---|---|---|---|
| synthetic order | 453 / 31 | holds | +0.241 [+0.211, +0.270] | +0.241 [+0.205, +0.272] | +0.441 [+0.431, +0.453] | +0.441 [+0.431, +0.458] | holds; D_order's lower bound above 0 | yes |
| synthetic noorder | 339 / 32 | fails | −0.425 [−0.513, −0.327] | −0.425 [−0.531, −0.313] | −0.036 [−0.080, +0.002] | −0.036 [−0.072, +0.007] | doesn't hold; D_order ties | yes |
| the Pi's store | 0 / 0 | insufficient | not computed | not computed | not computed | not computed | insufficient | yes |

Peak RSS was 75.3, 76.3 and 46.6 MiB, under the 512 MiB cap (RLIMIT_DATA set, and peak RSS checked after each stage).
Wall times were 14, 10 and under 1 s. No scratch file was written, and vectors stayed in memory. Rerunning gives the
same numbers: every generator and resample is seeded.

## Reading

This section is written by hand. Everything from "Run 1" on is the script's output.

**The planted order effect is found, and order is what finds it.**
- **The plant.** Each regular group has a fixed hub that follows it, and every hub sits in every session. Only order
  says which hub comes next.
- **(ii) against the other arms.** (ii) puts a member of the next recall in its top 10 on 53.6% of steps. The best
  other arm is popularity at 29.6%, since hubs are common, but it can't tell which hub follows.
- **Where (ii) hits.** From a regular group to its hub, (ii) hits every time (the C2 table's support 5–9 row, hit@10
  1.000).
- **The shuffled null.** Trained on shuffled sessions, (ii) falls to 9.6%: sharing a session says nothing here.
- **The intervals.** Both of the plan's checks pass, and the day bootstrap agrees with the session one.

**With co-retrieval and no order, (ii) doesn't hold, and order ties.**
- **The arms.** Meaning, nearest-to-any and co-retrieval each reach 0.531, and session history reaches 0.805. So
  D = −0.425, and C1′ fails, which isn't "holds", as required.
- **Order.** Shuffled (ii) reaches 0.416 against real order's 0.381, so D_order = −0.036 [−0.080, +0.002]: order
  ties, as it must when order within a session is exchangeable.
- **Why (ii) trails its twin (iv).** (ii) is 0.150 below co-retrieval, its no-order twin. A group sits in about 1.7
  training sessions, and the session's other group adds counts as large as the group's own. On the steps that stay in
  one group (Jaccard above 0), meaning and co-retrieval hit every time and (ii) hits 70%.

**The Pi's store shows the floor on a real schema.**
- **What it holds.** 5 recalls, all in one session, so `T` falls inside that session. That session gives training 2
  pairs, and no session starts after `T`: 0 test steps, so the run is insufficient and claims nothing.
- **What the run touched.** It read the live file with `mode=ro` in one read transaction:
  - the recall projections;
  - 45 vectors from the vec0 tables (33 episode, 12 semantic), with every logged id found among them;
  - the project's `config.toml`, which sets `tiebreak`.

**What the smoke runs don't exercise.**
- Real recall sets run up to 20 ids and overlap more. The order log's steps all had Jaccard 0.
- Footpaths interleave when subagents share a session id.
- Decay removes vectors partway through a log.
- A real universe holds thousands of memories. On the Mac, the run's time grows with test steps times universe size,
  mostly from (i′).

## Concerns for the reviewer and for Andy

1. **The shuffled null trains on more pairs than real order.** The plan rebuilds collapse after each shuffle, and a
   shuffle separates immediate repeats of one id set, so they stop collapsing.
   - **Measured.** Shuffled training has +4.6% pairs on the no-order log (1,470 against 1,406) and +4.5% on the order
     log.
   - **The effect.** It biases D_order down, which is the conservative direction. It's likely part of the no-order
     log's −0.036.
   - **On Andy's store.** Re-run queries may be common there, so the share is worth reading. Shuffling the collapsed
     runs instead would remove it, but that's a design change, so it isn't made here.
2. **"Holds" and "fails" can both be met.** An interval with its lower bound above 0 and its upper bound below δ meets
   both rules. The script calls it "fails" (choice 19) and says so in the report. The reviewer may prefer the other
   reading, or a fourth label.
3. **The config check can't find every config by itself.** Engram's server reads `config.toml` from each session's
   project root, not from beside the store.
   - **What Andy does.** He names each project's `.engram/config.toml` with `--config` (repeatable).
   - **What it can't show.** The check sees today's files only, not what a config said in the past.
4. **The memory cap on the Mac.** macOS may not enforce RLIMIT_DATA, so there the cap is the peak-RSS check after each
   stage. The script reads `ru_maxrss` in bytes on macOS and in KiB on Linux.
   - The run stops if the vectors alone would pass 256 MiB, about 87,000 memories at 768 dimensions.
5. **Day clusters use UTC days.** On Andy's Pacific clock, a UTC day ends at 4 or 5 pm.
6. **Running the real store.** It's one command, with his yes:
   `/path/to/engram/.venv/bin/python -I scripts/rail_e1_prime.py --store ~/.engram/instances/NAME/graph.db --config PROJECT/.engram/config.toml --report PATH`
   - It writes nothing but the report.
   - Its first line on stderr is the outcome.

## Run 1: synthetic order

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `9d5590be37150ffb`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ holds; order carries information.** D@10 = +0.241 [+0.211, +0.270] (session BCa), D_order = +0.441 [+0.431, +0.453]. Section 7: E1′ holds, and order carries information: build trails from recall logs, smallest first.

### Planted structure

128 groups of 12 memories (768-d, each group tight in meaning). There are 120 regular groups and 8 hub groups, and each regular group has a fixed hub. A session takes one regular group per hub, in random order, and recalls each group and then its hub, 16 recalls of 6 random members each. A memory is followed by a specific next set, and every hub sits in every session, so only order says which hub follows.

**Required:** C1′ holds, and D_order's lower bound is above 0.

Both logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), empty recalls (2%), 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed.**

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
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

- **C1′ holds.** D@10 = +0.241 [+0.211, +0.270] by session (31 clusters), +0.241 [+0.205, +0.272] by day (8 clusters). δ = 0.05.
- **Order carries information.** D_order = +0.441 [+0.431, +0.453] by session, +0.441 [+0.431, +0.458] by day.
- **Section 7:** E1′ holds, and order carries information: build trails from recall logs, smallest first.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.000 | 0.000 | 0.296 | 0.031 | 0.031 | 0.000 | 0.000 | +0.265 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.000 | 0.000 | 0.528 | 0.185 | 0.185 | 0.000 | 0.000 | +0.342 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 453 | 0.000 | 0.000 | 0.536 | 0.296 | 0.296 | 0.000 | 0.000 | 0.096 | +0.241 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | +0.265 [+0.230, +0.299] | +0.265 [+0.237, +0.306] |
| 5 | +0.342 [+0.309, +0.374] | +0.342 [+0.308, +0.374] |
| 10 | +0.241 [+0.211, +0.270] | +0.241 [+0.205, +0.272] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | +0.536 [+0.527, +0.549] |
| (i′) nearest | +0.536 [+0.527, +0.549] |
| (iii) popularity | +0.241 [+0.211, +0.271] |
| (iii-m) popularity, matched | +0.241 [+0.211, +0.270] |
| (iv) co-retrieval | +0.536 [+0.527, +0.549] |
| (v) history | +0.536 [+0.527, +0.549] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 0 of 453 primary steps (0.0%); there it equals (i).
On the 453 steps with counts, D@10 = +0.241 [+0.211, +0.270] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 453 | 0.000 | 0.000 | 0.536 | 0.296 | 0.296 | 0.000 | 0.000 | +0.241 |
| without counts | 0 | | | | | | | | |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 453 | 0.000 | 0.000 | 0.536 | 0.296 | 0.296 | 0.000 | 0.000 | +0.241 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 453 | 0.000 | 0.000 | 0.536 | 0.296 | 0.296 | 0.000 | 0.000 | +0.241 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 2 | 23 | 525 | 0.087 | 0.000 | 0.000 | 0.217 | 0.000 | 0.174 |
| 3–4 | 272 | 500 | 0.158 | 0.000 | 0.011 | 0.294 | 0.000 | 0.154 |
| 5–9 | 156 | 12 | 0.558 | 0.000 | 0.071 | 1.000 | 0.000 | 0.551 |
| 10+ | 2 | 12 | 1.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 121, of which 78 explicit and 43 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 121 | 0.000 | 0.000 | 0.562 | 0.281 | 0.281 | 0.000 | 0.000 | +0.281 |

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
| primary | 28 | 0.000 | 0.000 | 0.179 | 0.071 | 0.071 | 0.000 | 0.000 | +0.107 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 28 | 0.000 | 0.000 | 0.286 | 0.214 | 0.143 | 0.000 | 0.000 | +0.071 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.143 | 0.000 | 0.000 | 0.032 | -0.036 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 6 of 28 primary steps (21.4%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 22 | 0.000 | 0.000 | 0.364 | 0.227 | 0.182 | 0.000 | 0.000 | +0.136 |
| without counts | 6 | 0.000 | 0.000 | 0.000 | 0.667 | 0.000 | 0.000 | 0.000 | -0.667 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 0 | | | | | | | | |
| |b ∖ a| = 4–7 | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.143 | 0.000 | 0.000 | -0.036 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 28 | 0.000 | 0.000 | 0.286 | 0.321 | 0.143 | 0.000 | 0.000 | -0.036 |
| Jaccard (0, 0.25] | 0 | | | | | | | | |
| Jaccard (0.25, 0.5] | 0 | | | | | | | | |
| Jaccard > 0.5 (not primary) | 0 | | | | | | | | |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.667 |
| 1 | 20 | 46 | 0.200 | 0.000 | 0.100 | 0.350 | 0.000 | 0.200 |
| 2 | 2 | 26 | 0.500 | 0.000 | 0.000 | 0.500 | 0.000 | 0.500 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 3, of which 3 explicit and 0 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 3 | 0.000 | 0.000 | 0.333 | 0.333 | 0.333 | 0.000 | 0.000 | +0.000 |

### Resources

- **Peak RSS:** 75.3 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 14 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 2: synthetic noorder

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `9d5590be37150ffb`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**C1′ fails; order ties.** D@10 = -0.425 [-0.513, -0.327] (session BCa), D_order = -0.036 [-0.080, +0.002]. Section 7: E1′ fails: the trails part of the rail stops for Engram too.

### Planted structure

150 groups of 12 memories (768-d, each group tight in meaning). A session takes 2 groups and makes 12 recalls, each drawing 6 random members from one of the two at random. Memories are co-retrieved within a group, and order within a session is exchangeable.

**Required:** C1′ does not hold, and D_order ties.

Both logs also carry 160 primary-period sessions, 12 additive-period sessions, 300 never-recalled distractor memories created during the log, 10 vectors with no `created_at` row, immediate repeats (5%), empty recalls (2%), 40 instinct recalls, 20 recalls with no session id, and non-recall log rows. These exercise each filter.

**Smoke check: passed.**

### The store as read

- **Source:** a synthetic log in a shared-cache in-memory SQLite database (no file), read through the same reader (an in-memory URI in place of `mode=ro`, with `query_only`), in one read transaction.
- **Universe:** 2100 memories with a vector (episode 1656, semantic 444), dimension 768. Left out: 10 with no `created_at` row, 0 with zero norm, 0 of the wrong size, 0 already seen in the other table.
- **Logged ids with no vector now:** 7 distinct ids.
- **Recall rows:** 2254. Unparseable: 0. With no session id: 20. Instinct layer: 40 in the primary period and 0 before it (left out and reported apart). Analysed: 2042 in the primary period (from 2026-09-02, engram 548c97dd) and 152 in the additive period before it.
- **Recall days:** the analysed recalls span 71 days.

### The primary period

- **Recalls analysed:** 2042 in 160 sessions.
- **Split:** `T` falls on 2026-10-20 (80th percentile of recall times, rounded to the day).
- **Training:** 128 sessions with recalls before `T`, 1633 recalls, 1560 after collapse, and 1406 pairs passing the Jaccard rule. (ii) has 28100 distinct edges and (iv) has 14042.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 1. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 32, with 406 recalls; collapse merged 17 of them. That leaves 357 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 348 | 4 (1.1%) | 5 (1.4%) | 339 (97.4%) |
| > 0.5 (excluded; descriptive) | 9 | 0 (0.0%) | 0 (0.0%) | 9 (100.0%) |

- **Primary steps:** 339 in 32 sessions over 10 days. The largest session holds 3.2% of them.

- **Uptake marks** (descriptive): training recalls 1633, of which 403 were marked used (163 by `auto`). Test recalls 406, of which 101 were marked used (45 by `auto`).

#### Outcome

- **C1′ fails.** D@10 = -0.425 [-0.513, -0.327] by session (32 clusters), -0.425 [-0.531, -0.313] by day (10 clusters). δ = 0.05.
- **Order ties.** D_order = -0.036 [-0.080, +0.002] by session, -0.036 [-0.072, +0.007] by day.
- **Section 7:** E1′ fails: the trails part of the rail stops for Engram too.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 339 | 0.251 | 0.245 | 0.142 | 0.009 | 0.068 | 0.242 | 0.239 | -0.109 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 339 | 0.528 | 0.528 | 0.310 | 0.024 | 0.153 | 0.528 | 0.572 | -0.263 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 339 | 0.531 | 0.531 | 0.381 | 0.024 | 0.162 | 0.531 | 0.805 | 0.416 | -0.425 |

#### D at every k, and (ii) against each arm

| k | D by session [BCa 95%] | D by day [BCa 95%] |
|---|---|---|
| 1 | -0.109 [-0.139, -0.060] | -0.109 [-0.141, -0.059] |
| 5 | -0.263 [-0.338, -0.177] | -0.263 [-0.341, -0.170] |
| 10 | -0.425 [-0.513, -0.327] | -0.425 [-0.531, -0.313] |

| (ii) − arm at @10 | by session [BCa 95%] |
|---|---|
| (i) meaning | -0.150 [-0.235, -0.086] |
| (i′) nearest | -0.150 [-0.235, -0.083] |
| (iii) popularity | +0.357 [+0.275, +0.444] |
| (iii-m) popularity, matched | +0.218 [+0.143, +0.318] |
| (iv) co-retrieval | -0.150 [-0.235, -0.083] |
| (v) history | -0.425 [-0.515, -0.329] |

#### Steps where (ii) had counts

(ii) had no counted candidate on 92 of 339 primary steps (27.1%); there it equals (i).
On the 247 steps with counts, D@10 = -0.449 [-0.559, -0.328] by session.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 247 | 0.547 | 0.547 | 0.340 | 0.032 | 0.040 | 0.547 | 0.789 | -0.449 |
| without counts | 92 | 0.489 | 0.489 | 0.489 | 0.000 | 0.489 | 0.489 | 0.848 | -0.359 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 129 | 1.000 | 1.000 | 0.698 | 0.016 | 0.279 | 1.000 | 0.798 | -0.302 |
| |b ∖ a| = 4–7 | 210 | 0.243 | 0.243 | 0.186 | 0.029 | 0.090 | 0.243 | 0.810 | -0.624 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 160 | 0.006 | 0.006 | 0.025 | 0.013 | 0.019 | 0.006 | 0.800 | -0.775 |
| Jaccard (0, 0.25] | 50 | 1.000 | 1.000 | 0.700 | 0.080 | 0.320 | 1.000 | 0.840 | -0.300 |
| Jaccard (0.25, 0.5] | 129 | 1.000 | 1.000 | 0.698 | 0.016 | 0.279 | 1.000 | 0.798 | -0.302 |
| Jaccard > 0.5 (not primary) | 9 | 1.000 | 1.000 | 0.667 | 0.000 | 0.333 | 1.000 | 0.667 | -0.333 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 92 | 0 | 0.217 | 0.217 | 0.000 | 0.489 | 0.489 | 0.000 |
| 1 | 168 | 22 | 0.024 | 0.256 | 0.006 | 0.232 | 0.536 | 0.018 |
| 2 | 51 | 27 | 0.314 | 0.275 | 0.000 | 0.627 | 0.608 | 0.000 |
| 3–4 | 27 | 44 | 0.259 | 0.259 | 0.074 | 0.444 | 0.481 | 0.148 |
| 5–9 | 1 | 69 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 85, of which 45 explicit and 40 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 85 | 0.518 | 0.518 | 0.400 | 0.047 | 0.212 | 0.518 | 0.776 | -0.376 |

### The additive period (reported apart)

- **Recalls analysed:** 152 in 12 sessions.
- **Split:** `T` falls on 2026-08-30 (80th percentile of recall times, rounded to the day).
- **Training:** 11 sessions with recalls before `T`, 121 recalls, 118 after collapse, and 105 pairs passing the Jaccard rule. (ii) has 2053 distinct edges and (iv) has 1816.
- **Training steps after the cutoff:** 0 (must be 0). Test-session recalls before `T`: 0 (must be 0).
- **Sessions spanning `T`:** 2. They give training pairs before `T` and no test steps.
- **Test:** sessions starting after `T`: 1, with 13 recalls; collapse merged 1 of them. That leaves 11 candidate steps.

| Jaccard | candidate steps | a has no vectors | target empty | kept |
|---|---|---|---|---|
| ≤ 0.5 (primary) | 10 | 0 (0.0%) | 0 (0.0%) | 10 (100.0%) |
| > 0.5 (excluded; descriptive) | 1 | 0 (0.0%) | 0 (0.0%) | 1 (100.0%) |

- **Primary steps:** 10 in 1 session over 1 day. The largest session holds 100.0% of them.

- **Uptake marks** (descriptive): training recalls 121, of which 27 were marked used (9 by `auto`). Test recalls 13, of which 1 were marked used (0 by `auto`).

#### Outcome (secondary, decides nothing)

**Insufficient:** 10 test steps (needs 200); 1 test sessions (needs 20); one session holds 100% of the steps (at most 15%). The run claims nothing and computes no interval.

#### Hit rates on the primary steps

hit@1:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 10 | 0.100 | 0.300 | 0.100 | 0.000 | 0.100 | 0.100 | 0.100 | -0.200 |

hit@5:

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| primary | 10 | 0.600 | 0.600 | 0.600 | 0.000 | 0.600 | 0.600 | 0.400 | +0.000 |

hit@10 (the shuffled arm is reported at 10 only):

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | (ii-s) use, shuffled | D |
|---|---|---|---|---|---|---|---|---|---|---|
| primary | 10 | 0.600 | 0.600 | 0.600 | 0.000 | 0.600 | 0.600 | 0.800 | 0.600 | -0.200 |

#### Steps where (ii) had counts

(ii) had no counted candidate on 10 of 10 primary steps (100.0%); there it equals (i).

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| with counts | 0 | | | | | | | | |
| without counts | 10 | 0.600 | 0.600 | 0.600 | 0.000 | 0.600 | 0.600 | 0.800 | -0.200 |

#### By |b ∖ a| and by Jaccard band (hit@10, descriptive)

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| |b ∖ a| = 1 | 0 | | | | | | | | |
| |b ∖ a| = 2–3 | 5 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | +0.000 |
| |b ∖ a| = 4–7 | 5 | 0.200 | 0.200 | 0.200 | 0.000 | 0.200 | 0.200 | 0.600 | -0.400 |
| |b ∖ a| = 8+ | 0 | | | | | | | | |
| Jaccard 0 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.750 | -0.750 |
| Jaccard (0, 0.25] | 1 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | +0.000 |
| Jaccard (0.25, 0.5] | 5 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | +0.000 |
| Jaccard > 0.5 (not primary) | 1 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 0.000 | +0.000 |

#### C2 analogue: (ii)'s hit rate by the support of its top edge

Support is the number of distinct training sessions with a pair carrying `x* → y*`, where `y*` is (ii)'s top memory and `x*` the id in `a` with the largest count to it. 0 means (ii) had no counts.

| support | n | median counted candidates | (ii) @1 | (i) @1 | (iii) @1 | (ii) @10 | (i) @10 | (iii) @10 |
|---|---|---|---|---|---|---|---|---|
| 0 | 10 | 0 | 0.100 | 0.100 | 0.000 | 0.600 | 0.600 | 0.000 |

#### Uptake subset (descriptive only)

Primary steps whose `b` was marked used: 1, of which 1 explicit and 0 by `auto` only.

| population | n | (i) meaning | (i′) nearest | (ii) use | (iii) popularity | (iii-m) popularity, matched | (iv) co-retrieval | (v) history | D |
|---|---|---|---|---|---|---|---|---|---|
| b marked used | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | -1.000 |

### Resources

- **Peak RSS:** 76.3 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 10 s.
- **Scratch:** none. Vectors stayed in memory.

## Run 3: the Pi's own store (rio-grande), read-only

Run on 2026-11-03 (UTC). Plan: `docs/superpowers/specs/2026-11-03-rail-mathematics.md`, section 6′ (revision 3, e2ba0a3e). Script: `scripts/rail_e1_prime.py`, sha256 `9d5590be37150ffb`. Numbers only: no memory text, query, id or outcome text appears here, and no time finer than a day.

### Result

**Insufficient: 0 test steps (needs 200); 0 test sessions (needs 20).** The run claims nothing.

### The store as read

- **Source:** the live store file, opened with a `mode=ro` URI and `query_only`, and read in one read transaction. No copy was made.
- **Config check:** 3 places looked at (1 named with `--config`). 1 `config.toml` found, with recency_mode: tiebreak. Nothing overrides `tiebreak`.
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

- **Peak RSS:** 46.6 MiB. The cap is 512 MiB: RLIMIT_DATA was set, and peak RSS was checked after each stage.
- **Wall time:** 0 s.
- **Scratch:** none. Vectors stayed in memory.

## What all three runs share

### Pre-registered rules (section 6′, implemented as written)

- **Steps:** recalls in time order per session, with consecutive repeats of an id set collapsed. A step `a → b` counts when Jaccard(a, b) ≤ 0.5. The target is `b ∖ a` within the universe (a vector now, `created_at` ≤ `b`'s time). A step is dropped when `a` has no vectors or its target is empty.
- **Period and split:** the primary period starts at the `tiebreak` default's commit. `T` is the 80th percentile of recall times in the period. Training is pairs wholly before `T` inside the period, and test is sessions whose first recall is after `T`. Instinct recalls are excluded.
- **Arms:** (i), (i′), (ii), (iii) pure, (iii) matched, (iv) and (v), each a ranking of 10 memories excluding `a`'s ids, each backfilled by (i).
- **Outcome:** D = hit@10(ii) − max(i, i′, iii, iii-m, iv, v), with the max inside each resample, and a bootstrap clustered by session (10,000 resamples, BCa, jackknife acceleration). **Holds:** the lower bound is above 0. **Fails:** the upper bound is below δ = 0.05. **Inconclusive:** anything else, or when the day-clustered bootstrap's outcome differs.
- **Insufficient:** fewer than 200 test steps, fewer than 20 test sessions, or one session above 15% of the steps.
- **Order:** (ii) retrained on each training session in shuffled order (20 seeded shuffles, averaged), with collapse, Jaccard and mirroring rebuilt. D_order = hit@10(ii) − hit@10(ii-s). Order carries information only if D_order's lower bound is above 0.

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
16. **Shuffles.** Each shuffle permutes every training session's pre-`T` recalls with a seeded generator, then collapses, applies the Jaccard rule and mirrors `b ∖ a` as for real order. Per-step hit@10 is averaged over the 20 shuffles.
17. **Day clusters.** The UTC day of the session's first recall, so each session sits in one day.
18. **BCa.** 10,000 multinomial cluster resamples, seeded. `z0` comes from the share of resamples below the estimate, with ties counting half, clipped to [0.5/B, 1 − 0.5/B]. The acceleration comes from the leave-one-cluster-out jackknife.
19. **Holds and fails at once.** An interval with its lower bound above 0 and its upper bound below δ meets both. This script calls it **fails** (the effect is surely below the smallest effect of interest), and the report says so when it happens.
20. **Order.** `D_order` says "order carries information" only if its lower bound is above 0 under both the session bootstrap and the day bootstrap.
21. **Insufficient.** Test sessions are those with at least one primary step. When the data are insufficient, no interval is computed: only counts and point hit rates appear.
22. **Additive period.** It runs the same pipeline on its own: its own `T`, with training inside it. It's secondary and decides nothing.
23. **Universe.** A vector with no `created_at` row, or a zero norm, is left out and counted. An id in both vector tables is kept once.
24. **C2 analogue.** `y*` is (ii)'s top memory and `x*` the id in `a` with the largest c(x, y*). Support is the number of distinct training sessions with a pair carrying x* → y*.

### Named, not modelled

- **Meaning made the targets.** Returned ids are ranked by similarity to each query, so meaning starts ahead by construction. A use win is strong evidence, and a tie says little.
- **Dream and instinct biases** are blended into the query vector, and aren't modelled.
- **Interleaved footpaths.** Claude Code subagents share their parent's Engram server, so their recalls interleave under one session id. This blurs order.
- **Access-driven decay** removes rarely used episodes' vectors. The universe uses vectors present now.
- **The config check sees today's files.** It can't show what a config said in the past.
