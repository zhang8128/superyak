# Test 4, stage B, review 2: the re-check of draft 4 (962a89b0) and arms cbfe2fda, verbatim

The same fresh reviewer read both diffs, checked the arms' hashes and the copied word list in code, and rendered its
rebuilt worlds through the new arms. It ran no model and changed no file.

---

**Re-check of draft 4 (962a89b0) and arms cbfe2fda: APPROVED WITH REQUIRED CHANGES.** Six changes, all small text
fixes; no world rule or prompt has to move.

**Required changes**

1. **The stall rule breaks the world's export.** A stall writes no entry, `i` counts stalls, and
   `open_patches(world, record)` sees only the record. So in trap 4, after a stall, the world can't know which base to
   offer. Fix: make it `open_patches(world, record, i)`, a mechanical addition to the exports. Also say what a run
   entry's `turn` is after a stall: `n + i`, leaving a gap, or record length + 1. `firing`'s "run turn numbers" need the
   same answer.
2. **Restore the structure contrast.** Draft 3's R2 − R1 became R2 − R0. "What this can't show" still talks about
   R2 − R1, and the question asks about "the record with structure". Fix: add R2 − R1 on both primaries, per trap, with
   the same CI.
3. **Say which σ sets N.** There are four primary differences per trap, and the formula uses "the primary
   difference". Fix: the largest of the four, with ddof = 1. Otherwise it's a choice made after the pilot.
4. **Separate machine faults from stalls.** Two cases count as faults, not stalls:
   - a result event with `is_error` true (a rate limit, a sign-in or API error);
   - an exit with no result before the 120-second kill.

   Rerun the call or void the run, and report stalls and faults per arm. Otherwise a rate-limited stretch is scored as
   the turns failing.
5. **The harness author's brief is missing pieces.** It needs these from "The worlds":
   - the verdict command (the pytest line exists only there);
   - applying `diff` to `bases[j]` with `patch -p1`;
   - the state rule, which harness item (d) cites;
   - the world's JSON shape.

   It also needs the arms' input shapes, which exist only in code: `patches` as `{description, diff}`, record entries as
   `{turn, description, diff, verdict, summary}`, and `read_reply(text, k)`. Fix: give it "The worlds" whole, which is
   no fitting risk since it chooses nothing, and write the arms' signatures into "The arms".
6. **Two text fixes:**
   - "R0's trap effect is zero in expectation in every trap" holds exactly only in traps 2, 3 and 5. In traps 1 and 4,
     R0's prompt changes (a name word, the revision lines), and that change is exactly what R0 controls for there.
   - "Or the turns run out" can't happen under a 20-world cap. Delete it or define it.

**Your four questions**

1. **The edits to "The worlds" are all mechanical.** The 64 words match stage A's list exactly (checked in code). `i`
   from 1, trap 5's twin with `n = 4`, the default failure summary and the return shapes all match the readings my
   rebuild took. No rule changed. The one problem is change 1.
2. **The arms change is not fitting.** The diff from 587ce392 is exactly the null-summary line, the advice's first
   sentence and one test. The hashes `c1cc0bc3…` and `b6927da7…` match cbfe2fda.
   - The null-summary text adds nothing the verdict line doesn't already say. It appears only in trap 5's trapped
     form, and R1 and R2 see it alike.
   - The advice now describes itself truly. But the change was made after trap 4 was known, and a true description may
     let an R2 turn discount the advice when the base moves. Say in one line that this likely weakens trap 4 for R2.
   - cbfe2fda is still local. Push it or bundle it before the harness author uses it.
3. **The new choices:**
   - **Stall rule:** sound in substance. Reading the naming call as the first call whose reply was read fits indexing
     calls by record length. Changes 1 and 4 still apply.
   - **Working directory:** fine. The visitor wrapper puts `home/` and `uv-cache/` inside its directory, so put them
     outside to keep this one empty.
   - **120-second timeout:** fine for a reply of about 100 tokens.
   - **3 repeats with R2 seeds 0 to 2:** fine.
   - **Sample-size formula:** the arithmetic is right; the floor gives ceil(15.37) = 16. But binomial noise alone can
     put σ at 0.35 to 0.55, so N will often exceed 20, and 20 worlds then reach about ±0.15 to ±0.24. Say before the
     pilot that "underpowered" is the likely label.
   - **The cap:** 12,600 turns is correct for 20 worlds per trap.
   - **Cost estimate:** consistent. 1,890 turns at 1,500 to 3,000 tokens is 2.8 to 5.7 million, and at 10 to 20
     seconds a turn it's 5.3 to 10.5 hours. My rendered prompts run 2,400 to 7,900 characters, which fits. The estimate
     leaves out Claude Code's own system prompt.
4. **The harness author's brief is enough once change 5 is made.** Also say two things in "Measures": the harness turns
   a `repeat` value (an integer from 0 to 4, or a string holding one) into that patch's key before calling `named`, and
   trap 3 is scored with `raised`.

**What I ran**
- The two diffs, and sha256 of both arms files at cbfe2fda.
- A code check that draft 4's word list equals stage A's.
- My rebuild of the worlds rendered through the new arms: the null summary now reads "none (its turn ended before it
  wrote one)", and I measured the prompt sizes.

No files were changed, no model was run, and no git command wrote anything.
