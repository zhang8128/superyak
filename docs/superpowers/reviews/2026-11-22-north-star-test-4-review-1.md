# Test 4's spec, review 1: the fresh reviewer's verdict on bdf0eba5, verbatim

A fresh reviewer agent started on Tardis read `docs/superpowers/specs/2026-11-22-north-star-test-4-design.md` at
bdf0eba5 whole. It had the spec, docs/north-star.md row 4 and docs/goals.md, and none of the room's posts or either
author's views. Its scripts and logs are in Tardis's session scratchpad (`t4/`). They aren't committed, and its numbers
come from its own simulation of the spec as written, not from stage A.

---

**Verdict: REVISE.** The blinding is sound, and no world rule is fitted to make a policy win or lose. But two blind
implementers couldn't produce interoperable code from this contract. Two policies have readings that change their
results wholesale, and the ceiling and the rule for choosing B's traps are vacuous. Each reason below carries a concrete
fix. A draft 3 that makes exactly these fixes, checked by diff, would have my approval. Don't change the world rules in
response to my numbers: that would be fitting by the reviewer.

**Reasons (required changes)**

1. **The contract can't be implemented blind (lines 39–61).** It doesn't say whether an entry's `state` is the state
   before or after its step. The policy never receives the current state, so only "after" lets it raise `cycle` on
   arrival, or lets the oracle know where it is. It also leaves out:
   - where `turn` starts, and who writes it (`step` can't know it);
   - the type of `verdict`;
   - the shape of an option and of the policy's return;
   - the types of the flag values;
   - who writes the runner that calls both halves and logs flags per call;
   - the naming rule's interface.

   Fix: one contract paragraph saying:
   - `state` is the id after the step, and a run starts at `"L0"`;
   - turns count from 1 and the runner writes them;
   - `verdict` is `"pass"|"fail"`;
   - options are `{"name","content"}` dicts, and the policy returns an index;
   - "the call just after turn t" is the call made with a record of length t;
   - "the call on an arrival" is the one whose record ends with that arrival;
   - `named(world, record, flags_per_call) -> True|False|None`, where None means not exposed or the call doesn't
     exist;
   - the runner's author, who writes it from the contract alone.

2. **"Revisited" (line 80) and "arrival" (line 175) are undefined.** A failed step stays put. So under the literal
   reading, adaptive raises `cycle` on 35% of its calls in worlds with no cycle, and falsely names the trap in 23% of
   cycle-twin runs. Under an arrival reading the false-name rate is 0, and named-on-exposure is 100% either way. The
   false-name rule (line 209) can't apply to the cycle as written, because the twin has no second arrival at `Lc`. Fix:
   in the contract, an arrival is an entry whose state differs from the state before it, and `cycle` is raised on any
   arrival after the first. A false name is the trap's flag at any call of a twin run, for all four traps.

3. **Random, read literally, breaks (line 77).** A policy that depends only on `(record, options, seed)` and draws from
   `default_rng(seed)` makes the same draw every turn. In my run it recovered in 0.0–0.7% of worlds. Thompson has the
   same gap (line 78). Fix:
   - each call builds its own generator: `default_rng([seed, len(record)])` for Random,
     `default_rng([seed, len(record), 1])` for Thompson;
   - Thompson takes one Beta draw per option and picks the largest;
   - seeds are 0–19, and a world and its twin run with the same seed.

4. **Fixed's reading must be stated (line 75).** "Reads nothing else" rules out counting per state, and "from the top
   again" means round robin. So the text forces this: the first option, in the world's order, with the fewest tries by
   name in the whole record. Say so, and state its consequence: fixed recovers in only 52 of 100 renamed worlds,
   against 100 of their twins. The other reading, "`options[0]` once all are tried", fails 96–100% of every twin.

5. **`premise` is underspecified (lines 81–82).** Say whether the observation's own turn's verdict is dropped, and that
   by-name removes those entries from their names' counts. Say whether `contradiction` and `premise` are raised once,
   or again at every later call.

6. **The ceiling is vacuous (lines 99–103).** Fixed and random raise no flags by definition, and each adaptive policy
   raises exactly the flag that each naming rule counts. So "differs in recovery or a counted naming flag" is above
   zero for every trap and pair: 0.31–1.00 in my run. It is 1.00 for the summary trap, whose choices provably don't
   move. Raw recovery differences are noise too: 0.16–0.21 of worlds against random, in traps with no effect, which is
   just random's base failures. Pairing Thompson's seed s with random's seed s pairs nothing. Fix:
   - define the ceiling on recovery's trap effect: per policy and world, the recovery rate trapped minus the rate in
     the twin, over the 20 paired seeds;
   - per pair, take the mean over the 100 worlds of the difference between the two policies' trap effects, with a 95%
     bootstrap CI over worlds (fixed resample count and seed);
   - report naming beside the ceiling, never inside it.

7. **The selection rule (lines 105–107) inherits the vacuous ceiling.** Line 106 also promises that "the spec names
   which applies to each trap before A runs", and the spec doesn't yet name them. Fix: a trap goes to B if any pair's
   CI from change 6 excludes zero, and the summary trap goes by the reads clause. Write both rules now.

8. **B's sizing claim is unsupported (lines 116–117).** A's separations come from a planted table. B's verdicts come
   from real turns' frozen checks, so A doesn't bound B, and for the summary trap A's separation is zero by
   construction. Fix: "B's size is fixed in its pre-registration, from a pilot."

9. **"What this can't show" (lines 124–130) misses five things:**
   - (a) In A, "trap named" is fixed by the definitions: 100% of exposed adaptive runs name the trap, and fixed and
     random never do.
   - (b) The base world uses one key at every level. That rewards keying that ignores the state, which is how all four
     policies key.
   - (c) The cycle is a three-state detour, and every loop state offers the key. Adaptive reached `Lc` a second time
     in 43 of 2,000 runs, and no policy's recovery moved by more than 0.2 points. It doesn't test long cycles.
   - (d) The renamed trap's only recovery effect falls on fixed, which also keys by name. By-name and by-content
     recovered identically, at 10.8 against 10.2 mean turns. So that trap separates the two adaptive keys only through
     the `repeat` flag.
   - (e) Trap 4's twin removes both the change and the observation, so no form shows whether the observation helps.

**Advisory**

1. **Fitting, both ways.** The policies section didn't change from 76a05573 to bdf0eba5: the diff deletes only the
   placeholder line. I found no world rule shaped to a policy's exact behaviour, and the traps barely touch any
   policy's recovery. One coupling should be disclosed: Serenity answered the `premise` question before writing trap
   4, and trap 4's observation names exactly what `premise` drops. The flag vocabulary maps one-to-one onto row 4's
   traps by design, which is why naming is fixed by the definitions.
2. **How each trap fares against row 4:**
   - cycle: a detour, not a long cycle (point 9c);
   - renamed idea: it tests the name key, openly;
   - summary: in stage A it reaches only the scorer;
   - map: it is what row 4 names. It costs adaptive about 3 turns (13.2 against 10.3) and no recoveries, and it helps
     fixed (26.6 against 34.6 turns), because fixed prefers names it hasn't tried.
3. **Making the worlds reproducible from the spec.** A SeedSequence has no single natural `f"{seed}"` string. Where
   `w` starts isn't stated. "Drawn without replacement … in this order" could mean the first 2k words or a seeded draw.
   The order of the random draws isn't fixed. Only one agent implements the worlds, so this isn't an interoperability
   gap, but post a fingerprint of all 800 worlds alongside the hash.
4. **The oracle check is trivial,** since the oracle needs only D turns. Add a trivial policy that reads only the
   record, round robin per state. In my run it recovered in both forms of every trap, which shows each world can be
   recovered from the record alone.
5. **Naming tests should also show** that a rule doesn't fire one call early, and doesn't fire in the twin.
6. **Trap 2:** also count apart the runs that tried the returner but were never offered it under a new name again,
   because it was tried at the last level or the budget ran out.
7. **Stage B's sketch** should say what a real turn works on when the approaches are planted digests, and what its
   frozen check checks.
8. **Row 4's "only generate activity":** say what activity is compared against, for example distinct contents tried
   in runs that don't recover.
9. **The suite result at lines 120–122** wasn't checked by me.

**What I ran**

Scripts are in Tardis's scratchpad `t4/`: `sim.py`, `drive.py`, `ceiling.py` and `extra.py`, with output in
`drive.log`, `ceiling.log` and `extra.log`.

They build the worlds and policies as specified, with these readings: `state` is the state after the step, turns count
from 1, and each call builds its own generator except in the literal variants. The run covered 100 world pairs per
trap, 7 policy variants and 20 seeds, about 112,000 runs in all.

- **Oracle:** recovered in all 800 worlds.
- **Recovery, trapped against twin:**

| Trap | Adaptive by name | Adaptive by content | Fixed (fewest tries) | Random |
|---|---|---|---|---|
| Cycle | 99.9 / 100 | 99.9 / 100 | 100 / 100 | 99.5 / 99.7 |
| Renamed | 100 / 100 | 100 / 100 | 52 / 100 | 98.9 / 98.9 |
| Summary | 100 / 100 | 100 / 100 | 100 / 100 | 99.0 / 99.0 |
| Map | 100 / 100 | 100 / 100 | 100 / 100 | 99.1 / 99.1 |

  On the summary trap every policy's choices were identical in both forms, which confirms line 89.
- **Budget:** random averages 24 turns against a mean budget of 48 and recovers 99% of the time, so "about twice a
  blind search" holds.
- **Ceiling as written:** 0.31–1.00. Raw recovery only: 0.00–0.48. Trap effect: 0.48 for adaptive against fixed on the
  renamed trap, 0.21 against random on the map, which is noise, and 0.00–0.06 elsewhere.
- **Literal Random:** 0.0–0.7% recovery. Fixed reading "`options[0]` once all are tried": 0–4% in twins. Fixed
  counting per state: 100% in both forms.
- **Cycle flags, literal reading:** 7,243 of 20,727 adaptive calls raise one in worlds with no cycle, and 23% of
  cycle-twin runs get a false name. Under the arrival reading: 0%.
