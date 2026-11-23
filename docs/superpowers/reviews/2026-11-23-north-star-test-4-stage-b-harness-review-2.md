# Test 4, stage B, the harness's review 2: the re-check of 7b91906e, verbatim

The same reviewer read the diff from 3355c8c0 and confirmed both files' sha256. It ran the tests with the stub (50
passed) and its stall-naming stub check again, with logs in Tardis's scratchpad `t4b-review/`. It ran no model and
wrote nothing in the worktree.

---

**Harness re-check (7b91906e; `test4b_harness.py` 3d4ae9ac…, its test 0e1d9842…, both hashes confirmed): APPROVED.**
It's ready to run against the real model.

1. **The required change is made correctly.**
   - At the naming call only, `scoring_flags` maps the first read call's raw `repeat` number to that patch's key on
     `bases[0]`.
   - The hashed rule then accepts it exactly when the number names a planted idea, whatever `i` is.
   - The logged `flags_per_call` keep the key at that call, and a test asserts both the logged key and the scored key.
   - `raised` and `false_named` read the same scoring flags, but since they take any value, the mapping can't change
     them.
   - My stub check from the last review now gives trap 4 named True after a stalled first turn, where it gave False
     before. Trap 1 is unchanged.
2. **The seeded arm order adds no bias.**
   - The permutation comes from a seed of its own (20261202, used nowhere else) and depends on nothing a run produces.
   - Because both forms of a world share an order and run next to each other, a time effect lands on an arm's trapped
     and twin runs alike, so it cancels in the trap effect.
   - The pilot's 45 orders are random rather than exactly balanced. That's unbiased in expectation, and every order is
     recorded.
3. **Nothing else in the scoring moved.** These are unchanged:
   - `primaries`, the bootstrap, `_recovery_cells`, `pilot_size`, `_naming` and `PRIMARIES`;
   - the stall, fault and rerun logic, `classify` and the argv.

   The per-arm counts were refactored into `_stall_counts` with the same fields, plus `by_form` and the string-turn
   counts. `score` only gains keys: the string counts, the arm orders and the restart rule. One test's assertion moved
   into the renamed trap 4 test and is still checked there.

**What I ran:** the diff from 3355c8c0, the sha256 of both files, the tests with the stub (50 passed in 63 s, exit 0),
and my stall-naming stub check again. Logs are `harness-tests-2.log` and `stall_named-2.log` in Tardis's scratchpad
`t4b-review/`.

No model was run and nothing was written in the worktree.
