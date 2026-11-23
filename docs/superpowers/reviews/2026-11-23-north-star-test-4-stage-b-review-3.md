# Test 4, stage B, review 3: the re-check of draft 5 (a347b23c), verbatim

The same fresh reviewer read the diff from 962a89b0 to a347b23c, checked that the arms were unchanged since cbfe2fda,
and grepped the Claude Code 2.1.330 binary for `api_retry`. It changed no file and ran no model.

---

**Re-check of draft 5 (a347b23c): APPROVED WITH REQUIRED CHANGES.** There are two one-line changes, both to the fault
rule. Once they're made as written below, I approve the spec as a whole, with no third re-check.

**Required**

1. **A rate limit usually never reaches `is_error`.** Claude Code 2.1.330 retries rate-limited calls itself and writes
   `system`/`api_retry` events to stream-json; its binary includes one with `error_status:429, error:"rate_limit"`. So a
   throttled call hits the 120-second kill, and (c) scores it as a stall. That is the very case (c2) says never happens.
   Fix: a call killed at 120 seconds after any `api_retry` event in its stream is a fault, not a stall.
2. **Voiding a run and dropping it biases recovery.** A run that doesn't recover makes up to 7 calls, and one that
   recovers makes fewer. So faults void non-recovering runs more often, and more often in the arm that recovers slower
   (R0), which tilts "gets it out" toward the record arms. Fix:
   - rerun a void run from its start, with the same world, form, arm, repeat and seed;
   - retry a faulted call after a pause, for example 60 seconds, not at once;
   - report reruns per arm.

**Your three questions**

1. **X1 to X6 are all made as required.**
   - X1: `open_patches(world, record, i)` and run entry `turn = n + i` are in place. `firing` returns `i`, which it can
     recover as `turn − n`.
   - X2: R2 − R1 is on both primaries.
   - X3: σ is the largest of the six differences' SDs, with `ddof = 1`. Six is right: three contrasts on two primaries.
   - X4: the fault rule is written, but needs the two changes above.
   - X5: "The worlds" is given whole. The arms' signatures match the code at cbfe2fda. A record entry's optional `state`
     isn't listed, which is harmless: only the policy's `cycle` flag reads it, and that flag isn't shown.
   - X6: both text fixes are made.
2. **The edit to "The worlds" is mechanical.** The rule that the run's `i`-th turn uses `bases[min(i, …)]` already
   existed. Passing `i` in and returning `i` from `firing` changes the interface, not any rule.
3. **"Retried once, then void" is not sound as written;** that's changes 1 and 2. One advisory: (c) and (c2) agree,
   since a kill at 120 seconds is a stall and an exit with no result before it is a fault. Say "exits on its own before
   the kill" so no one reads them as overlapping.

**What I checked**
- The diff from 962a89b0 to a347b23c.
- The arms are unchanged since cbfe2fda; the git diff is empty.
- A grep of the 2.1.330 binary for `api_retry`.

No files were changed and no model was run.
