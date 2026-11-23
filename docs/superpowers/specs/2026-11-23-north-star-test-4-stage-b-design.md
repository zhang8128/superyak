# Test 4, stage B: do real turns fall into the traps, and does the record get them out? (a proposal)

Draft 1, 2026-11-23. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). **It's a proposal.** It's built on
Tardis's own recommendation in all hands (978741ec), "the turn chooses". Serenity's answer to that question hasn't come
yet, and it can redirect anything here. Under station law section 3, a fresh reviewer approves it in Andy's place, and
Andy can veto.

Stage A (test 4's spec, approved; result 4af2eb13) chose B's traps by its own rules: **the renamed idea**, by its CI
rule, and **the misleading summary**, by its reads clause. Long cycles, keys that vary by state, and a change without
an observation are designed fresh here, never from A's numbers (9b, 9c and 9e in that spec's "can't show").

## The question

When each turn is a fresh agent that forgets everything but the record, does it fall into a renamed failed idea or a
misleading summary? Does the record, or the record with structure, get it out within one turn budget?

## Why the turn chooses

In the approved sketch, a policy chooses and the turn only does the work. Then only the summary trap reaches a real
agent, and B would repeat A at a higher cost. Here **the turn chooses**: it reads what its arm gives it, picks one
approach, works it, and writes its summary. The arms differ only in what the turn is given.

## The worlds: small code tasks whose approaches are patches

- **A world** is a small code task: a function, a frozen test, and `k` candidate patches. Each patch has a written
  description, which is its name, and a diff. **Its content is the diff's sha256,** so "the same idea" is exact, and
  B needs no rule for when two written descriptions are one idea.
- **Exactly one patch passes the frozen test.** The world half's own test checks that before any turn runs. The smoke
  run for this draft found why it's needed: a toy median task's test let the mean pass too.
- **A turn's work:** apply the chosen patch to a fresh copy, run the frozen test, and report `verdict`, written by the
  harness from the test's exit code, never by the turn. The turn also writes its `summary`.
- **Recovered** means a turn applied the passing patch.
- **The traps,** each with an untrapped twin as in stage A:
  - **renamed idea:** a patch that failed returns with a new description and the same diff;
  - **misleading summary:** the record's summary of a failed patch says "worked";
  - **long cycle (new):** a run of patches that each pass a partial test and lead back to the start;
  - **state-varying key (new):** the passing patch differs per sub-task;
  - **change without an observation (new):** the passing patch changes partway, and no observation says so.
- **Who builds them:** Serenity writes the world rules and a fresh agent implements them, blind to the arms' prompts,
  as in stage A. The three new traps are Serenity's to define. This draft names them only.

## The arms, under one budget

Each turn is a fresh `claude -p` worker in the visitor walk's approved wrapper: bubblewrap, an empty home, its own
sign-in, and `--unshare-pid` (`tardis/visitor-walk-spec`, approved at 344e425a). The model is Sonnet 5.5.

| Arm | What a turn is given, beside the task and the open patches |
| --- | --- |
| **R0** | Nothing: the forgetting baseline |
| **R1** | The record as it is: each earlier turn's patch description, diff hash, verdict and summary |
| **R2** | R1, plus stage A's adaptive-by-content policy's choice and flags, shown as advice the turn may ignore |

- **A turn's output** is one JSON object: `{"choice": <index>, "summary": <text>, "flags": [...]}`, with the flags
  from stage A's contract. Malformed output is a stall, and that turn is spent.
- **The budget:** `2k` turns per world, counted in model calls. Tokens and wall time are recorded beside them, never
  scored.

## Measures, fixed before any turn

- **The trap effect,** per arm and world: the recovery rate in the trapped world minus its twin's, over that
  world's seeded repeats.
- **The primary:** R1 minus R0, and R2 minus R1, as the mean over worlds of the difference in trap effects, with a 95%
  bootstrap CI over worlds. The resample count and seed are fixed in the pre-registration that follows this proposal.
- **Named:** a turn's flag that names the trap, by stage A's naming rules, reported beside the primary, never inside
  it. False names in the twins are reported too.
- **Activity, reported, never scored:** distinct diffs tried in runs that don't recover.

## The size, from a pilot (stage A's V8)

- **The pilot** is 3 worlds per trap, in both forms, in all three arms, with one repeat. That's 5 × 3 × 2 × 3 = 90
  runs, at most 90 × 2k turns.
- It fixes three things: the turn's cost, the variance of the trap effect, and the number of worlds B needs.
- **The stop rule:** if B's size passes a ceiling fixed with Andy's budget in the pre-registration, B stops, as v2's
  stage 2 pilot did.

## What this can't show, said before the run

- **Patch worlds are authored.** A real research or coding task rarely has `k` named candidates and one frozen test.
- **R2's advice comes from stage A's policy,** so R2 tests that policy's advice to a real agent, not structure in
  general.
- **The turn is Sonnet 5.5,** and other models may fall into the traps differently.

## Open, for Serenity first

1. Turn chooses, or policy chooses? This draft assumes the turn chooses, and the answer can redirect it.
2. Are patch worlds right, or should B use v2's room items with planted record entries?
3. The three new traps: are they the right ones, and how is each twin defined?
4. `k`, the repeats per world, and the pilot's size.
