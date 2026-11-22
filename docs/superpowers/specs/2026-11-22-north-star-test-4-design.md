# Agents that get stuck: fixed, random and adaptive exploration against four traps (north-star test 4)

Draft 3, 2026-11-22. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). Under station law section 3, a
fresh reviewer approves it in Andy's place, and Andy can veto. The shape was agreed in all hands (Tardis 816233f1;
Serenity f60bbed1, 51f449fe and 49bf4b90; Tardis eadcff61).

- **Draft 1 (53ac83f5, dc4a6add)** was read whole by Serenity as the world builder (all hands 4c600201): sound in
  structure, with three required changes, R1 to R3. Serenity's watcher run added the ceiling point, R4 (d9e5c80d).
- **Draft 2** makes all four and closes the three open questions as Serenity answered them: Thompson stays, seeded;
  `premise` drops counts; 20 seeds, with the number of worlds per trap fixed in "The worlds".
- **Draft 2 with "The worlds" (bdf0eba5)** went to a fresh reviewer: REVISE, with nine required changes, V1 to V9
  (`docs/superpowers/reviews/2026-11-22-north-star-test-4-review-1.md`, 8180d090; all hands 9f2fda21).
- **Draft 3** makes exactly those nine, in the reviewer's words wherever it gave them. **V2 to V5 change "The
  policies",** which draft 2 fixed by hash (8b56bd8e…b48b1d). Each change is a reading the reviewer showed the text
  already forced, or one it required, never a choice made from a world rule or from its numbers. The re-check reads
  that section's diff for exactly this. "The worlds" is unchanged.

## The question

Row 4: long cycles, a failed idea back under a new name, a misleading summary, an observation that invalidates a map.
Under one budget of turns, does the system recover, or does it only generate activity?

Here "the system" is turns that forget plus a durable record: each turn starts with no memory of the last and reads
only the record. That's the time-loop room, and v2's room is its harness (row 4's "the rail and v2's room").

## Who does what, and what neither reads (R1)

Serenity has read the policies section, so a world Serenity wrote could be fitted to it, even unawares. The blinding
therefore moves from Serenity to a fresh implementer, and Serenity's rules become visible to the reviewer.
- **Serenity writes the world rules** into this spec, in "The worlds": the trap list, each trap's generation rule,
  its untrapped twin, the recovery check, the naming rule and the number of worlds per trap. The fresh reviewer checks
  that section for fitting to the policies.
- **A fresh agent implements the worlds** from "The contract" and "The worlds" alone, given verbatim. It's never given
  the policies section, the policy code or this spec's other sections, as with Measure 3's labeller.
- **Tardis implements the policies** from "The contract" and "The policies" alone.
- **The policies section is fixed at draft 2,** before any world rule exists. A later revision that changes it is a
  fitting risk, and the reviewer checks every revision for one.
- **The hashes:** each half's code is committed, and its sha256 posted in all hands, before either side reads the
  other's code.
- **Each half's own tests** stay inside it. A world's tests may use the oracle below and a trivial policy, and a
  policy's tests may use a trivial world, never the other half's code.

## The contract (stage A)

**A world** is a deterministic object built from a seed:
- `options(state)` is the list of approaches open in a state. Each has a `name` (a string) and a `content` (a string
  digest of what the approach does). Two approaches with one content are the same idea, whatever their names.
- `step(state, approach)` returns the next state and an entry for the record.
- `recovered(state)` is the world's frozen recovery check.
- `budget` is the number of turns the world allows.

**The record** is an append-only list of entries, one per turn, each with:
- `turn`, `state` (an opaque id), `name`, `content`;
- `verdict`: the frozen check's pass or fail for that turn, written by the world and trusted;
- `summary`: a short structured claim about the approach, `{"approach": content, "says": "worked" | "failed"}`,
  written by the world. A trap may make it disagree with `verdict`;
- `observation`: `None`, or `{"invalidates": [content, ...]}`, which says that earlier verdicts on those contents no
  longer hold.

**A policy** is a function of `(record, options, seed)` alone. It returns one approach from `options`, and a list of
**flags**, each one of:
- `{"repeat": content}`, an idea already tried under another name;
- `{"cycle": state}`, a state already visited;
- `{"contradiction": turn}`, a summary that disagrees with its verdict;
- `{"premise": turn}`, an observation that invalidated earlier verdicts.

Flags change nothing in the world. Whether a flag counts as naming the trap is the world's frozen naming rule.

**The exact forms (V1, V2):**
- **An entry's `state`** is the state's id after the step. A run starts at `"L0"`, and the start counts as the first
  arrival there.
- **`turn`** counts from 1, and the runner writes it.
- **`verdict`** is `"pass"` or `"fail"`.
- **An option** is a dict `{"name": str, "content": str}`. A policy returns `(index, flags)`, where `index` points into
  `options` and `flags` is a list of one-key dicts as above. The values of `repeat` are content strings, of `cycle`
  state ids, and of `contradiction` and `premise` turn numbers.
- **What the policy is given:** the runner calls the policy with the record so far, the options of the current state
  (the state of the record's last entry, or `"L0"` for an empty record), and the run's seed.
- **An arrival** is an entry whose state differs from the state before it: the previous entry's, or `"L0"` for the
  first entry.
- **"The call just after turn t"** is the call made with a record of length t. **"The call on an arrival"** is the
  one whose record ends with that arrival.
- **A naming rule** is `named(world, record, flags_per_call) -> True | False | None`, where `flags_per_call[i]` is the
  flags of the call made with a record of length i. None means the run wasn't exposed, or the call the rule names
  doesn't exist.
- **A false name (V2)** is the trap's flag raised at any call of a twin run, for all four traps. It's reported beside
  each naming rule.
- **The runner and the scorer** are written by a third fresh agent, from "The contract" and "Stage A" alone. It reads
  neither half's code nor the other sections. The runner calls a world and a policy, logs every call's flags, and
  applies `recovered`, the budget and the naming rules.

**Twins and the oracle (R2):** each trapped world has an untrapped twin: the same seed, states and approaches, with
only the trap removed. The world half's own tests include an **oracle policy** that knows the solution, and they show
that the oracle recovers within `budget` in both twins. A world where the oracle can't recover is a broken world, not
a stuck agent, and is fixed before any policy runs.

**A run** is one policy in one world for at most `budget` turns. It stops at the first turn whose state passes
`recovered`. It's scored on recovered (yes or no), turns to recovery, and trap named (yes or no, by the naming rule in "The
worlds"). Each policy runs in both twins, so a recovery lost to a trap shows as the difference between them.
Activity is reported beside them, never scored: turns used, and distinct contents tried, in runs that recover and in
runs that don't. So "only generates activity" reads as many distinct contents tried in a run that doesn't recover.

## The policies: what each computes, said before any world exists

- **Fixed (V4):** the first option, in the world's order, with the fewest tries by name in the whole record. That's a
  round robin by name. It reads nothing else in the record and raises no flags.
- **Random (V3):** each call builds its own generator, `numpy.random.default_rng([seed, len(record)])`, and draws one
  index uniformly over the options. It has no memory and raises no flags.
- **Adaptive by name:** Thompson sampling with a Beta(1, 1) prior per approach **name**. Successes and failures are
  counted from `verdict` only, never from `summary`. **Each call (V3)** builds its own generator,
  `numpy.random.default_rng([seed, len(record), 1])`, takes one Beta(1 + passes, 1 + fails) draw per option in
  `options` order, and picks the largest.
- **Its flags (V2, V5):**
  - `cycle` is raised at the call on any arrival at a state after the first arrival there;
  - `contradiction` is raised once, at the call just after the turn whose `summary.says` disagrees with its
    `verdict`;
  - `premise` is raised once, at the call just after the turn whose entry carries an observation.
- **The `premise` drop (V5):** from that call on, every entry whose content the observation names is dropped from the
  counts, the observation's own turn included. By name, those entries leave their names' counts.
- **Adaptive by content:** the same, keyed by **content**. It also raises `repeat` at every call for each option whose
  content has been tried under a different name from the one it's offered under now.
- **Seeds (V3):** the policy seeds are 0 to 19, and a world and its twin run with the same seed.

**What follows from this, argued before any run:**
- The renamed-idea trap separates the two adaptive keys by construction: by name, a renamed failed idea is a fresh
  arm, and by content, it isn't. It tests the key choice, which the spec says openly, not adaptivity as such.
- Neither adaptive policy reads `summary` for its counts. So in stage A the misleading-summary trap can move only
  their flags, not their choices. Whether it misleads anyone is a stage B question, since there a real turn reads
  the summary text.
- A cycle hurts fixed only if the world's order revisits the state, and random in expectation by the share of its
  draws that do. Whether adaptive escapes depends on whether the cycle's approaches fail their checks.
- **Fixed keys by name too (V4),** so a renamed failed idea is untried to it. The reviewer's simulation of the spec as
  written found fixed recovering in 52 of 100 renamed worlds, against 100 of their twins. That's the reviewer's
  figure, not stage A's.

## Stage A: argued, checked

Stage A has row 6's property: with planted tables and no model, each policy's behaviour at each trap follows from how
it keys its record. So it's labelled **"argued, checked"**, and it serves three ends:
1. **The ceiling, measured first (V6):**
   - **The trap effect:** per policy and world, the recovery rate in the trapped world minus the rate in its twin, over
     the 20 paired seeds.
   - **Per pair:** the mean over the trap's 100 worlds of the difference between the two policies' trap effects, with a
     95% bootstrap CI over worlds: 10,000 resamples, `numpy.random.default_rng(20261130)`, percentile interval.
   - **The pairs:** each adaptive policy against fixed and against random, and adaptive by name against adaptive by
     content.
   - **Naming is reported beside the ceiling, never inside it:** per trap and policy, named on exposure, the false-name
     rate in the twins, and the runs not exposed.
   - Two policies picking different approaches doesn't count.
2. **The scorer's test:** every world's recovery check and naming rule, run against every policy.
3. **Choosing B's traps (V7):** a trap goes to stage B if any pair's CI from point 1 excludes zero. The summary trap
   goes by the reads clause instead: its effect is on what a real turn reads, which stage A can't see. Named now:
   the cycle, the renamed idea and the map-breaking observation go by the CI rule, and the summary trap goes to B by
   the reads clause.

## Stage B: the measurement (sketched here, pre-registered later)

- **What runs:** real turns in v2's room, with each turn a fresh worker reading only the record. The policy chooses
  which open approach the next turn works on. The turn's frozen check writes `verdict`, and the turn writes
  `summary` and any `observation` in the record's structured form. A planted trap may overwrite them, as the world
  says.
- **The budget is turns,** meaning model calls. Tokens and wall time are recorded beside them, never scored.
- **The size (V8):** B's size is fixed in its pre-registration, from a pilot. A's separations come from planted tables
  and don't bound B. v2's stage 2 pilot needed 481 items against a ceiling of 40, and B stops by the same rule if it
  can't be afforded.
- **What a real turn works on** when the approaches are planted digests, and what its frozen check checks, are fixed in
  B's pre-registration. This sketch doesn't decide them.
- **Content-keying on real text** needs a rule for when two written approaches are one idea. B's pre-registration
  fixes it, and it isn't decided here.
- **Where B runs:** on the Pi or on Tardis. v2's whole suite passes on both: on Tardis at v2 7a78136e, on 2026-11-22,
  `scripts/whole-suite.sh --offline` passed 532 tests in 35 programs, with none ignored or filtered, in 270 s, on
  x86-64 kernel 7.0.0-38. That includes the jail's seqpacket test, which failed on this kernel at 44447ae1 on 11-17.

## What this can't show, said before the run

- Stage A shows what each policy does by construction, not that real agents get stuck.
- The worlds are authored. Blinding stops either half from being fitted to the other, not the traps from being
  unlike real work.
- Stage B's agents read the record's text, so its results depend on how a summary is written, not only on the
  policy.
- **(V9a)** In A, "trap named" is fixed by the definitions: every exposed adaptive run names the trap, and fixed and
  random never do.
- **(V9b)** The base world uses one key at every level. That rewards keying that ignores the state, which is how all
  four policies key.
- **(V9c)** The cycle is a three-state detour, and every loop state offers the key. So it doesn't test long cycles.
- **(V9d)** The renamed trap's only effect on recovery falls on fixed, which also keys by name. So the trap separates
  the two adaptive keys only through the `repeat` flag.
- **(V9e)** Trap 4's twin removes both the change and the observation, so no form shows whether the observation
  itself helps.
- **A disclosed coupling (the reviewer's advisory 1):** Serenity answered the `premise` question before writing trap
  4, and trap 4's observation names exactly what `premise` drops. The flags map one-to-one onto row 4's traps by
  design, which is why naming is fixed by the definitions.

## The worlds (Serenity writes this section; R1, R2, R3)

For each trap, its generation rule, its untrapped twin, its recovery check, its **naming rule** (R3: which flag,
raised by which turn, counts as naming it), and the number of worlds. Serenity's example of a naming rule: a cycle is
named if a `cycle` flag for that state is raised by its second visit. This section is the fresh implementer's whole
brief, beside "The contract", and the reviewer checks it for fitting to "The policies".

*Written by Serenity from the four traps as row 4 states them. Each trap changes one mechanic of a shared base world,
and its twin undoes exactly that change. No rule reads a policy's state, flags or choices beyond the approach a turn
took; a world never reads flags.*

**Seeds.** A world is built from `numpy.random.SeedSequence([20261129, trap, D, k, w])`, where `trap` is 1 to 4 in the
order below and `w` is the world's index. A world and its twin come from one seed. These seeds are disjoint from the
policies' seeds.

**The base world** (shared by every trap and every twin), with depth `D` and `k` options per state:
- **The pool:** `P = 2k` ideas. Each has a `content`, the first 16 hex digits of sha256 of `f"{seed}:{i}"`, and a
  canonical `name`, drawn without replacement from this fixed list of 64 neutral words, in this order: amber, basin,
  cedar, delta, ember, fjord, garnet, harbor, iris, jasper, kestrel, lantern, meadow, nectar, onyx, pepper, quarry,
  raven, saffron, timber, umber, velvet, willow, xenon, yarrow, zephyr, acorn, birch, cobalt, dune, elm, flint, grove,
  heron, indigo, juniper, kelp, lichen, maple, nickel, oak, pine, quartz, reed, slate, thistle, upland, vale, walnut,
  yew, zinc, alder, bramble, clover, dahlia, egret, fern, gorse, hazel, ivy, jade, kiln, lupin, moss.
- **The key:** one pool idea, drawn by the seed. It's the idea that advances.
- **States:** levels `L0` to `L{D-1}`, and the goal `G`. The run starts at `L0`.
- **Options at a level:** the key plus `k − 1` other pool ideas drawn without replacement, in a seeded random order, each
  under its canonical name. A level's options are fixed when the world is built, not when it's reached.
- **`step(Li, key)`** moves to the next level, or to `G` from the last, with verdict pass. **`step(Li, other)`** stays
  at `Li` with verdict fail. Every entry's `summary` says "worked" on a pass and "failed" on a fail. `observation` is
  `None`.
- **`recovered(state)`** is `state == "G"`.
- **`budget`** is `2·D·k` turns, about twice what a blind search needs, chosen without reference to any policy.

**The four traps,** each with its twin and its naming rule:

1. **Cycle (long cycles).** At a level `c`, drawn from 1 to `D − 2`, one non-key option there is the lure, drawn by the
   seed.
   - `step(Lc, lure)` passes and moves into a loop of three states `C1`, `C2`, `C3`. Each offers `Lc`'s option set in
     a fresh seeded order.
   - At a loop state, the lure passes and moves to the next loop state, and from `C3` back to `Lc`. The key passes and
     moves to `L{c+1}`. Any other option fails and stays.
   - So the lure looks like progress at every step and returns to where it began.
   - **Twin:** identical, except that `step(C3, lure)` moves to `L{c+1}`, so the lure's route is real, if longer.
   - **The budget,** in both twins, is `2·D·k + 3`.
   - **Named** if a `cycle` flag naming `Lc` is raised by the policy call made on the run's second arrival at `Lc`.
2. **A failed idea back under a new name.** One non-key idea, the returner, is drawn from level 0's options. It's placed
   in every level's options, replacing one other non-key idea where it isn't already there. It fails everywhere.
   - **In the trapped world,** from level 1 on, the returner appears under a new name at each level, taken from the
     unused words of the list in order, with its content unchanged.
   - **Twin:** the returner keeps its canonical name at every level.
   - **Named** if, once the run has tried the returner, a `repeat` flag naming its content is raised by the first policy
     call at which it's offered under a different name. A run that never tries it isn't exposed, and is counted apart.
3. **A misleading summary.** Half the pool's `2k − 1` non-key ideas, rounded down (at least one), drawn by the seed,
   are the misled ideas.
   - Any turn that takes a misled idea has verdict fail, as in the base, but `summary.says` is "worked".
   - **Twin:** summaries agree with verdicts.
   - **Named** if, for the first turn `t` whose summary disagrees with its verdict, a `contradiction` flag naming `t` is
     raised by the policy call just after turn `t`.
4. **An observation that invalidates a map.** At a break level `m`, drawn from 2 to `D − 2`, a second idea, the new key,
   is drawn from the non-key pool. It's placed in the options of every level from `m` on, replacing one other non-key
   idea where it isn't already there.
   - **In the trapped world,** the entry of the turn that first arrives at `Lm` carries
     `observation = {"invalidates": [key content]}`. From then on, at levels `m` and above, the old key fails and stays,
     and the new key passes and advances.
   - **Twin:** no observation. The old key keeps advancing, and the new key is an ordinary failing option.
   - **Named** if a `premise` flag naming that turn is raised by the policy call just after it.

**How many:** `D` of 4 and 8, `k` of 3 and 5, and 25 worlds per combination. That's 100 worlds per trap, each in
trapped and twin form, so 800 worlds in all, each run with every policy at 20 policy seeds.

**What the world half's own tests must show** (with a trivial policy and an oracle written for them, never Tardis's):
- **the oracle,** which knows the key, the lure, the returner and the break, recovers within `budget` in both twins of
  every world;
- each twin differs from its trapped world only in the mechanic its trap names;
- a world is identical when rebuilt from its seed;
- every naming rule fires on a hand-built run that raises the right flag at the right call, and doesn't fire one call
  later.

**Scored beside each naming rule:** the same flag raised in the twin counts as a false name, and is reported.

## Decided in draft 2

1. **Thompson sampling stays,** seeded. A deterministic UCB1 can tie and loop in a cycle world, which would confound
   the trap with the tie-break (Serenity, 4c600201).
2. **`premise` drops the counts it invalidates.** An invalidated verdict is no longer evidence, and down-weighting
   would add a weight to tune. The observation names the contents it invalidates, so the drop can be checked.
3. **Twenty seeds per world** is enough to show whether the pairs that matter can differ at all. The number of worlds
   per trap is fixed in "The worlds".
