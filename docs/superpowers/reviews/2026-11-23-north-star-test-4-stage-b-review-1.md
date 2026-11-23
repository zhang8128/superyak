# Test 4, stage B, review 1: the fresh reviewer's verdict on draft 3 (b3e92d5f), verbatim

A fresh reviewer agent read the spec whole, stage A's spec and policies, the hashed arms half (587ce392) and the
visitor wrapper's invocation. It rebuilt all 1,000 worlds from "The worlds" text and rendered prompts through the
hashed arms (Tardis's scratchpad, `t4b-review/`, not committed). It ran no model and changed no file.

---

**Verdict: APPROVED WITH REQUIRED CHANGES.** A re-check should read the changes before any turn runs.

"The worlds" holds up. I rebuilt all 1,000 worlds from its text, and every structural claim I tested passed. What's
missing is the harness that joins the worlds to the arms, and what the primary measure means.

**Required changes**

1. **Write the harness down:** who writes it, from which sections, and these decisions:
   - (a) **The turn's frozen invocation.** Use the visitor wrapper with `--tools ""` (2.1.330's help text says `"" for
     none`) and `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`. Drop `--allowedTools` and `bypassPermissions`.
     Set a per-turn timeout, and take the reply from stream-json's result event. On every turn, check that the init
     event lists no tools and no MCP servers; if it does, the turn is a machine fault.
   - (b) **Nothing outside the prompt names the trap, form, arm or world.** That covers the turn's working directory
     and its environment. Claude Code's system prompt shows the working directory, so a directory named for the world
     would leak the form.
   - (c) **A stall** (malformed or timed out) is spent. Say whether it writes an entry and whether trap 4's base still
     moves. Without stall entries, "the run's i-th turn" has to be counted from the record's length, and a stall
     breaks that.
   - (d) **Run entries.** `summary` is the turn's text, written before the verdict exists. `says` is null, since
     nothing reads it: the hashed advice rebuilds `says` from `verdict`. `state` follows the "state" rule.
   - (e) **Field mapping and the null summary.** The world's `name` becomes the arms' `description`. Trap 5's null
     summary currently renders as "Its summary: None" in the hashed arms. Choose that or another rendering, and state
     it.
   - (f) **R2's inputs.** `keys` needs one key per record entry, the null entry included. Fix the advice seed per
     repeat (for example, the repeat index).

2. **Correct R2's row (line 67) to what the hashed arms do.** The advice shows the policy's choice and its `repeat`
   flags only:
   - `contradiction` can't fire, because `says` is rebuilt from `verdict`;
   - `cycle` and `premise` aren't shown;
   - entries with a null verdict are dropped.

   Also add a short "what each arm sees of each trap", which I checked:
   - R0's prompt is byte-identical between trapped and twin in traps 2, 3 and 5 (100 of 100 worlds each).
   - R2's advice text is identical between forms in traps 2, 3 and 5 (100 of 100 worlds, seeds 0–19).
   - In trap 4, R1 sees the failed idea offered under its own planted name, with identical changed lines. Only the
     hunk header and the revision lines move. So trap 4 barely reaches R1 and is really aimed at R2's key. At w=0, the
     advice names a failed patch in 34% of seeds, against 17.5% in the twin.

3. **Make "named" reachable.** As written it can never be true for traps 1, 3 and 4, at any arm. Their values are a
   content key or `"S0"`, and no turn sees either. The hashed reply asks for `repeat` as a patch number and `cycle` as
   a free note.
   - **Fix:** the harness reads a `repeat` value as an open patch's number and scores it as that patch's key at that
     call. For trap 3, named equals raised.
   - **Disclose:** the prompt defines `repeat` as "under another description", which trap 4 never shows. It defines
     `premise` as "changed what earlier verdicts mean", which trap 5's turn 5 doesn't do.
   - **Reconcile the signature:** line 260 says `-> bool`, but stage A's `named` returns True, False or None.

4. **Say what the primary measures.** R0 sees the same prompt in both forms of traps 2, 3 and 5, so its trap effect is
   zero in expectation.
   - R1 − R0 therefore measures whether the record's trap catches a reader. Its expected sign is negative, and R0 adds
     only noise.
   - It can't measure "does the record get it out", because R0 was never in the trap.
   - **Fix:** say the primary is per trap, not pooled. State the expected signs. Add trapped-form recovery, R1 − R0 and
     R2 − R0, as the "gets it out" measure, or restate the question.

5. **Leave nothing to tune after the pilot.** As written, the pre-registration comes after the pilot and the pilot sets
   the number of worlds, so the stop ceiling could be chosen knowing it. Fix these before the pilot:
   - the bootstrap count and seed (stage A's would do);
   - repeats per world;
   - R2's seeds;
   - the per-turn timeout;
   - the formula that turns the pilot's variance into a number of worlds: a target CI width or power, with a variance
     floor, since 3 worlds × 1 repeat leaves 2 degrees of freedom per trap;
   - what happens if that number exceeds 97;
   - the stop ceiling, in turns or money.

6. **Text fixes:**
   - Line 106's "(still to come)" is stale.
   - "Works it" (line 29) and "A turn's work: apply…" (line 42) contradict "A turn has no tools" (line 59).
   - The question (line 23) names only two of the five traps.
   - The ceiling has two definitions: "can fire" (line 86) and "cost" (line 242).
   - Copy stage A's 64 words into "The worlds", because the implementer is given only this spec.
   - Say that `i` counts run turns from 1.
   - Trap 5's twin has `n = 4`.
   - A planted failing entry's summary is the plain failure unless its trap says otherwise.
   - Give the return shapes of `open_patches` and `firing`.
   - Activity should count distinct patch indices, not distinct diffs: in trap 4 every diff is distinct by
     construction.

**Advisory**

- **The ceiling is 1.0 in every world by construction** (500 of 500). The follower's bait is always on offer, so the
  count checks the code, not whether a trap can matter. Blind exposure is the informative number: at w=0 it is 0.49,
  0.49, 0.75, 0.70 and 0.80 for traps 1 to 5. Report it.
- **Trap 5 will probably show nothing.** The arms show a null verdict as "none (its turn ended before the test ran)",
  and the opening tells the turn exactly one patch passes. With four fails on record, `p` is the only patch not shown
  failing, in both forms. Say before the run that a null is expected.
- **Trap 2 is its weakest form.** "fail" sits on the same line as "It worked."
- **Trap 3's cycle is three patches,** and with `k = 5` it can be four at most. Stage A's 9c called a three-state
  detour "not long", so say what "long" means here.
- **R2's bandit exploration costs on its own.** In trap 5, in both forms, the advice names a failed patch in 125 of 200
  seeds. R2 − R1 may come out negative from exploration alone.
- **R2's advice misdescribes itself in trap 4.** It says it keys patches "by what they change", but it keys by the
  whole patched file.
- **Say whose sign-in stage B uses,** and the reset rule per turn. The visitor's sign-in is revoked when the walks end.
- **Estimate the pilot's wall time and tokens,** beside its 630 turns.

**Fitting and leaks.** I found none in either direction.
- No world rule uses the arms' wording. Naming rules whose values the turns can't produce are evidence the world
  builder was blind to the arms.
- No arm leaks the keys, the frozen test or the passing patch. The arms' test asserts the keys never appear, and I
  checked the rendered prompts.
- The arms file is unchanged since 587ce392 (sha256 1a59e1fd…). I couldn't compare that hash with the one posted in all
  hands (b6821042).
- The null-verdict wording came from draft 2's story for trap 5, written before any world rule existed. That's a
  disclosure, not fitting.

**Containment.** With no tools and without the test's inputs or digest, a turn can only eliminate patches using the
record. I found no way around a trap beyond the gaps in 1(a) and 1(b).

**The world claims, checked on my rebuild:**
- Exactly one patch passes on every base of all 1,000 worlds, and the base always fails.
- Each base's five keys are distinct, and so are all 40 of trap 4's.
- `patch -p1` reproduces each patched file exactly, and the test's own assert agrees, on a sample.
- Each twin differs from its trapped world in exactly the listed fields.
- The follower costs in 100 of 100 worlds for every trap.
- The record-only reader and the oracle recover in both forms of every world.

**What I read and ran.**
- **Read:** the stage B spec at b3e92d5f, whole; stage A's spec; `test4_policies.py`; `test4b_arms.py` and its test;
  the visitor spec's invocation section.
- **Grepped:** the Claude Code 2.1.330 binary, for the `--tools` help text.
- **Wrote and ran** a rebuild of the worlds from the text, with numpy 2.4.3. Its readings are marked in the code. It
  renders prompts through the hashed arms and checks everything above. My fingerprint for that reading is `015f4ffb…`.
- Files are in Tardis's scratchpad `t4b-review/`: `build.py`, `check.py`, `check2.py` and `check3.py`.
- No files were changed, no `claude` or model was run, and no git command wrote anything.
