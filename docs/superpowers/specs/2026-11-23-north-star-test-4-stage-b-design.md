# Test 4, stage B: do real turns fall into the traps, and does the record get them out? (a proposal)

Draft 2, 2026-11-23. Tardis, with Serenity (goals.md T3; docs/north-star.md row 4). Under station law section 3, a
fresh reviewer approves it in Andy's place, and Andy can veto.

- **Draft 1 (c2edc48b)** was a proposal on Tardis's own recommendation (978741ec), "the turn chooses".
- **Serenity's answer (all hands 004065cf)** says yes to the turn choosing and yes to patch worlds. It asks that the
  content key be frozen, sets `k = 5` with a budget of 7 turns, and asks for each trap's ceiling to be counted before
  the pilot. Serenity defined the three new traps there, and writes their rules into "The worlds" as the world
  builder. Draft 2 makes the rest.

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
  description, which is its name, and a diff. **Its content is frozen as the sha256 of the patched target file,
  normalized:** CRLF becomes LF, trailing whitespace is stripped from each line, and trailing blank lines are dropped.
  So whitespace and hunk order can't split one idea into two keys. "The same idea" is exact against a given base,
  and B needs no rule for when two written descriptions are one idea. When the base file moves (the state-varying
  trap), the same idea gets a new key, as that trap intends.
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
| **R1** | The record as it is: each earlier turn's patch description, its diff, its verdict and its summary. It holds no content key, so noticing a repeat is the turn's own work |
| **R2** | R1, plus stage A's adaptive-by-content policy's choice and flags, computed from the content keys and shown as advice the turn may ignore. That's the structure R2 adds |

- **A turn's output** is one JSON object: `{"choice": <index>, "summary": <text>, "flags": [...]}`, with the flags
  from stage A's contract. Malformed output is a stall, and that turn is spent.
- **The budget:** with `k = 5` (one passing patch and four failing), 7 turns per world, counted in model calls. Tokens and wall time are recorded beside them, never
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

- **Before the pilot, each trap's ceiling is counted without running anything:** the share of worlds in which the
  trap can fire within 7 turns. A trap that can't fire within the budget is changed by its builder before any turn
  runs, never after.
- **The pilot** is 3 worlds per trap, in both forms, in all three arms, with one repeat. That's 5 × 3 × 2 × 3 = 90
  runs, at most 90 × 7 = 630 turns.
- It fixes three things: the turn's cost, the variance of the trap effect, and the number of worlds B needs.
- **The stop rule:** if B's size passes a ceiling fixed with Andy's budget in the pre-registration, B stops, as v2's
  stage 2 pilot did.

## What this can't show, said before the run

- **Patch worlds are authored.** A real research or coding task rarely has `k` named candidates and one frozen test.
- **R2's advice comes from stage A's policy,** so R2 tests that policy's advice to a real agent, not structure in
  general.
- **The turn is Sonnet 5.5,** and other models may fall into the traps differently.

## Decided in draft 2, from Serenity's answer

1. **The turn chooses.** R2 tests the policy, as advice.
2. **Patch worlds for B.** v2's room items can be a later stage.
3. **The three new traps** are Serenity's, written into "The worlds" (still to come):
   - **a long cycle:** failing patches whose summaries lead into one another and back. The record leads into it, and
     exposure is reported, so a null can't pass for an escape;
   - **a state-varying key:** the base moves, so the same idea makes a new key;
   - **a change without an observation:** the passing patch's record entry has no verdict, because its turn timed
     out.
4. **`k = 5` and 7 turns.** Each trap's ceiling is counted before the pilot.

## The worlds (Serenity writes this section)

*(To be written by Serenity, from the definitions in all hands 004065cf.)*
