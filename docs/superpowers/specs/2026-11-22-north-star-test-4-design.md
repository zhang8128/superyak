# Agents that get stuck: fixed, random and adaptive exploration against four traps (north-star test 4)

Draft 2, 2026-11-22. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). Under station law section 3, a
fresh reviewer approves it in Andy's place, and Andy can veto. The shape was agreed in all hands (Tardis 816233f1;
Serenity f60bbed1, 51f449fe and 49bf4b90; Tardis eadcff61).

- **Draft 1 (53ac83f5, dc4a6add)** was read whole by Serenity as the world builder (all hands 4c600201): sound in
  structure, with three required changes, R1 to R3. Serenity's watcher run added the ceiling point, R4 (d9e5c80d).
- **Draft 2** makes all four and closes the three open questions as Serenity answered them: Thompson stays, seeded;
  `premise` drops counts; 20 seeds, with the number of worlds per trap fixed in "The worlds".

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

**Twins and the oracle (R2):** each trapped world has an untrapped twin: the same seed, states and approaches, with
only the trap removed. The world half's own tests include an **oracle policy** that knows the solution, and they show
that the oracle recovers within `budget` in both twins. A world where the oracle can't recover is a broken world, not
a stuck agent, and is fixed before any policy runs.

**A run** is one policy in one world for at most `budget` turns. It stops at the first turn whose state passes
`recovered`. It's scored on recovered (yes or no), turns to recovery, and trap named (yes or no, by the naming rule in "The
worlds"). Each policy runs in both twins, so a recovery lost to a trap shows as the difference between them.
Turns used and distinct contents tried are reported as activity, never scored.

## The policies: what each computes, said before any world exists

- **Fixed:** the options in the order the world lists them, the first not yet tried by name, then from the top again.
  It reads nothing else in the record and raises no flags.
- **Random:** a uniform draw over the options, from `numpy.random.default_rng(seed)`, with no memory and no flags.
- **Adaptive by name:** Thompson sampling, seeded from the run's seed, with a Beta(1, 1) prior per approach
  **name**. Successes and failures are
  counted from `verdict` only, never from `summary`. It raises `cycle` on a revisited state, `contradiction` when a
  summary disagrees with its verdict, and `premise` on an observation, after which it drops the counts of the named
  contents.
- **Adaptive by content:** the same, keyed by **content**. It also raises `repeat` when an option's content has been
  tried under another name.

**What follows from this, argued before any run:**
- The renamed-idea trap separates the two adaptive keys by construction: by name, a renamed failed idea is a fresh
  arm, and by content, it isn't. It tests the key choice, which the spec says openly, not adaptivity as such.
- Neither adaptive policy reads `summary` for its counts. So in stage A the misleading-summary trap can move only
  their flags, not their choices. Whether it misleads anyone is a stage B question, since there a real turn reads
  the summary text.
- A cycle hurts fixed only if the world's order revisits the state, and random in expectation by the share of its
  draws that do. Whether adaptive escapes depends on whether the cycle's approaches fail their checks.

## Stage A: argued, checked

Stage A has row 6's property: with planted tables and no model, each policy's behaviour at each trap follows from how
it keys its record. So it's labelled **"argued, checked"**, and it serves three ends:
1. **The ceiling, measured first (R4):** per trap, the share of worlds where the pair that matters differs **in
   outcome**, meaning recovery or a counted naming flag, over 20 seeds per world. Two policies picking different
   approaches doesn't count. The pairs that matter are each adaptive policy against fixed and against random, and for
   the renamed idea, adaptive by name against adaptive by content. Thompson's seeds add spread, so the ceiling is
   reported per seed as well as pooled.
2. **The scorer's test:** every world's recovery check and naming rule, run against every policy.
3. **Choosing B's traps:** a trap goes to stage B only if its ceiling is above zero, or if its effect is on what a
   real turn reads (the summary trap), which stage A can't see. The spec names which applies to each trap before A
   runs.

## Stage B: the measurement (sketched here, pre-registered later)

- **What runs:** real turns in v2's room, with each turn a fresh worker reading only the record. The policy chooses
  which open approach the next turn works on. The turn's frozen check writes `verdict`, and the turn writes
  `summary` and any `observation` in the record's structured form. A planted trap may overwrite them, as the world
  says.
- **The budget is turns,** meaning model calls. Tokens and wall time are recorded beside them, never scored.
- **The size** comes from stage A's separations, so B is sized before it runs. v2's stage 2 pilot needed 481 items
  against a ceiling of 40, and B stops by the same rule if it can't be afforded.
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

## The worlds (Serenity writes this section; R1, R2, R3)

For each trap, its generation rule, its untrapped twin, its recovery check, its **naming rule** (R3: which flag,
raised by which turn, counts as naming it), and the number of worlds. Serenity's example of a naming rule: a cycle is
named if a `cycle` flag for that state is raised by its second visit. This section is the fresh implementer's whole
brief, beside "The contract", and the reviewer checks it for fitting to "The policies".

*(To be written by Serenity.)*

## Decided in draft 2

1. **Thompson sampling stays,** seeded. A deterministic UCB1 can tie and loop in a cycle world, which would confound
   the trap with the tie-break (Serenity, 4c600201).
2. **`premise` drops the counts it invalidates.** An invalidated verdict is no longer evidence, and down-weighting
   would add a weight to tune. The observation names the contents it invalidates, so the drop can be checked.
3. **Twenty seeds per world** is enough to show whether the pairs that matter can differ at all. The number of worlds
   per trap is fixed in "The worlds".
