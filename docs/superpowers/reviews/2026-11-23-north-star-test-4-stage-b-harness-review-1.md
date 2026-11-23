# Test 4, stage B, the harness's review 1: the fresh reviewer's verdict on 3355c8c0, verbatim

The reviewer who approved stage B's spec, and who took no part in writing the harness, read the harness and the worlds
half's naming, firing and open-patch code. It grepped the init event in the Claude Code 2.1.330 binary, ran the
harness's 42 tests with the stub (42 passed), and ran a stub check of `named` after a stall. Its files are in Tardis's
scratchpad `t4b-review/`. It wrote nothing in the worktree and ran no model.

---

**Harness review (3355c8c0, `test4b_harness.py` 872b01d9…, its test 4f753bdc…): APPROVED WITH REQUIRED CHANGES.** There
is one required change. The rest is sound.

**Required**

1. **Trap 4 loses "named" when the first run turn stalls.** I checked this with a stub run.
   - A correct `repeat` gives named True with no stall, and named False after a stalled first turn. Raised is True both
     times, and trap 1 isn't affected.
   - The cause: the worlds' rule accepts the planted keys, plus the keys offered at `i = 1`. But `map_flags` maps the
     number to its key at the first read call, here on `bases[2]`.
   - Fix: for the naming rule's call, map a `repeat` number to that patch's key on `bases[0]`, its key "as recorded".
     The hashed rule accepts that for traps 1 and 4 whatever `i` is. Keep the at-that-call mapping in the logged flags,
     and add a test with a stalled first turn.

**The author's flags**

1. **`firing` by position: correct.** Mapping a position back through `turn − n` gives `i`. Trap 4's `_fires` compares
   bases by position, but positions and `i` both rise strictly and `i ≤ 7`, so the order is the same and stalls don't
   change firing.
2. **Integer-only turn values: acceptable.** The prompt shows `contradiction` and `premise` values unquoted. A string
   fails named but passes raised, as the spec allows. Advisory: report how many such values were strings.
3. **Raised becomes None when no reply was read: right.** It matches `named`'s None.
4. **The author's own choices, each sound:**
   - **Rerun limit of 3, then `MachineDown`:** stopping rather than dropping keeps the selection fix intact.
   - **A fault and its retry are one run turn:** that matches (c2).
   - **The pause only before a retry:** fine. A rate-limit window ends in a stop, never in silent drops.
   - **An init event without its lists is a fault:** conservative, and it shouldn't arise. The 2.1.330 binary builds
     init with both `tools:` and `mcp_servers:`.
   - **Exit codes other than 0 or 1 stop the harness:** correct.
   - **Fresh `home/` and `uv-cache/` per turn:** stricter than the spec.
   - **The uv binds:** they match the frozen wrapper.
   - **Order repeat, then world, then arm:** fine. Advisory below.
   - **One matrix per trap shared by the six:** as stage A has it.
   - **"Underpowered" when any of the six is wider:** the conservative reading.
   - **`/var/tmp/t4b-config`:** fine.
5. **Printing the arms' templates:** this broke the letter of the brief, but it isn't fitting. Both halves were already
   hashed, and no harness choice depends on the templates' wording; the only flag reading, `map_flags`, follows W3's
   text. Disclose it with the result.

**The frozen argv** matches the visitor's invocation:
- `systemd-run` scope with a random unit name, so nothing leaks through it;
- `timeout 120`;
- `--tmpfs /home/doctor`, `--unshare-pid`, `--chdir /var/tmp/t4b-turn`, and `env -i` with the walk's variables;
- `--tools ""` passed as an empty argv element, and `--strict-mcp-config --mcp-config '{"mcpServers":{}}'`;
- no `--allowedTools` and no permission mode.

`home/` and `uv-cache/` sit outside the working directory. A kill is read from exit 124, with a backstop timeout, and the
scope is stopped after every call.

**Scoring, checked:**
- Recovery is any run turn passing.
- The trap effect is trapped minus twin, per world, over the repeats.
- The six differences have the spec's signs.
- The bootstrap is `default_rng(20261130)` fresh per trap, 10,000 resamples, with the linear quantile.
- N is the formula, using the largest of the six ddof-1 SDs, floored at 0.30, capped at 20.
- Naming uses `raised` for trap 3, and false names cover every arm's twins.
- Activity is distinct indices in runs that don't recover.
- Stalls, faults, reruns, tokens and seconds are reported per arm.
- Every world must have balanced cells, or scoring refuses.

**Stalls and faults** follow (c) and (c2):
- `api_retry` before a kill is a fault, and a kill without one is a stall;
- an exit with no result, or a result with `is_error`, is a fault;
- a stall on the retry counts as a stall;
- a void reruns from its start with the same seed;
- reruns are reported.

**Bias and leaks:** none found. The prompt comes only from the world and the arm. The working directory is fixed, the
sign-in directory is reset and the instruction files are checked before every turn, and the R2 seed is the same in both
forms.

**Advisory**
- Report stalls per arm and form, since a stall rate that depends on the form moves a trap effect.
- R0, R1 and R2 always run in that order within a world. Rotate or seed the order so effects of time-adjacent runs don't
  always fall on the same arm.
- Say whether a series stopped by `MachineDown` restarts whole, rather than resuming with chosen runs.

**What I read and ran**
- Read: the whole harness; the worlds half's naming, firing and open-patch code.
- Grepped: the init event in the 2.1.330 binary.
- Ran the tests with the stub: 42 passed in 58 s, exit 0.
- Ran a stub check of named after a stall, outside the worktree.
- Files: the test log is `harness-tests.log`, and the stall check is `stall_named.py`, in Tardis's scratchpad
  `t4b-review/`.

No files in the worktree were written, and no model was run.
