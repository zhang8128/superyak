# Lesson outcomes: final whole-branch review and its re-check

Saved whole from the SDD workspace, 2026-11-04. Both by fresh reviewers on the Pi.

## Final review (bb90cb4d..a25aa9b7)

Verdict: APPROVE WITH CHANGES

Final whole-branch review of build-lesson-outcomes, bb90cb4d..a25aa9b7 (8 commits), against the plan
2026-11-04-lesson-outcomes.md and spec rev 3. Fresh reviewer on the Pi; it took no part in writing the branch.
Critical 0, Important 2, Minor 4.

## Strengths

- The table matches the spec word for word, and nothing typed reaches it: `receipt_id` is the matched row's id, never
  the typed prefix; `outcome` is checked twice (OUTCOMES and CHECK) (lessons.py:1440-1469).
- The receipt key is drawn before the fit (:1313-1314), so the answer and the rows always agree.
- The receipt works end to end. The answer carries uid()'s first 8 lowercase hex; the hook keeps only a full
  `[0-9a-f]{8}`; the verb takes 6 to 32, among the derived ship's receipts only. The query writes receipts only for a
  local ship member, and the derivation names that same user id. The peer test runs the real query, then the verb by
  full id, 6 and 8.
- Refusals are fixed constants, raised in the transaction before any insert, and echo nothing. The race becomes
  OUTCOME_TWICE.
- lessons.py still imports no sqlite3 at module level (the sys.modules tests in test_lessons_index.py pass).
- In the hook, a malformed receipt is dropped and the lesson still shown. A lesson without one renders as before, and
  old and new hooks and peers work together.

## Issues

### Important

**I1. Two peer-suite guard tests fail at a25aa9b7.** The implementers' file list didn't include them. I ran each one
once:
- `tests/test_restore.py::test_every_table_is_either_reconciled_or_named_coordination` fails with "Extra items in the
  left set: 'lesson_outcomes'". Fix: add `'lesson_outcomes',  # lesson outcomes: a local record beside the receipts,
  never federated` to COORDINATION_TABLES (peer/tests/test_restore.py:2546). Coordination is the right class: a restore
  keeps the copy's rows as they are, like `lesson_repeats`.
- `tests/test_packaging.py::test_the_sdist_list_names_every_test_file_and_only_paths_that_exist` fails with
  "tests/test_lessons_outcomes.py" missing from the sdist list. Fix: add it to peer/pyproject.toml's only-include list
  beside `tests/test_lessons_index.py` (:181).

These must be fixed before the train: the plan's after-tasks gate says the peer suite passes, and CI runs it.

**I2. The receipt line is wrong on every peer but the Pi.** This is a plan issue, not an implementer's:
`receipt_line` is the plan's exact text (agent/superyak_agent/lessons_hook.py:224-226). The line is `make
lesson-outcome RECEIPT=r OUTCOME=…` with no `LESSONS_DATA`, and the Makefile defaults `LESSONS_DATA` to
`STATION_DATA` (`~/.local/share/superyak/lighthouse`, Makefile:26,56). Other peers keep their data elsewhere: the
checklist has them pass `LESSONS_DATA=<that peer's data dir>` (docs/checklists.md:527), and `make home` uses
`.engram/home`.

So a ship on Tardis or Serenity that runs the shown line gets a misleading refusal: the verb runs against the wrong
directory. I reproduced it in the scratchpad: the verb against a missing directory creates `peer.sqlite3` and
`dispatch.lock` there, then exits 1 with "No lessons room is recorded on this peer". It also runs only from the
superyak checkout.

This matters because Tardis's T1 blind test runs on a non-origin peer, and coverage is section 5's measure. The hook
already knows the data directory (`settings['data_dir']`) and the checkout (CHECKOUT). Fix: have the line name both,
for example `make -C <checkout> lesson-outcome … LESSONS_DATA=<data_dir>` with shell quoting. Another option is a
Makefile default read from that peer's settings. Pin the new text in the hook tests. Then recheck the hold bound below,
since a long path adds bytes.

### Minor

- **M1. A verbatim paste of the line can record `helped`.** In a shell, `OUTCOME=helped|misled|unused` is a pipeline
  (lessons_hook.py:226). My scratch probe ran it three ways. With `make -s` it recorded `helped` 3 of 3 times. With
  plain make, the recipe echo hit SIGPIPE before the command ran (6 of 6 in bash, 3 of 3 in zsh), so nothing was
  recorded. One outcome per receipt is irrevocable, so make the paste fail closed: `OUTCOME=<helped|misled|unused>` is
  a syntax error before anything runs. Fold this into I2's new text.
- **M2. The section labels point at the wrong spec.** Inside lessons.py, "Section 3" and "section 5" mean the first
  rail's sections (3 is the lessons room). The new labels mean the outcomes spec's. Affected: lessons.py:70, 113, 907,
  1441, 1694 and 1703; the verb's `--help`; Makefile:517 ("First rail section 3"); and test_lessons_outcomes.py:1
  ("First rail, section 3"). Name the lesson-outcomes spec.
- **M3. The new make targets aren't in the targets table** in `test_lessons_targets_run_the_lessons_command`
  (peer/tests/test_station_units.py:288-306). Add two rows. I checked both with `make -n` by hand, and they expand
  correctly.
- **M4. Coverage is all-time** (lessons.py:1481). Its denominator includes receipts written before answers carried a
  short id, which can never take an outcome, so coverage reads low for good. It is fine to leave now. Section 4's
  revision needs windowed counts for section 5's ±20% band. The prefix lookup's full scan by `substr` (:1452) is fine
  at today's scale; a range on the primary key would help at cluster scale.

## Deferred minors (ledger)

All eight are fine to leave:
- T1, the snapshot read twice in lesson_repeat: a rare manual verb.
- T1, ship-derivation refusals not asserting the table unchanged: they raise before any receipt read.
- T1, "1 outcomes on 1 receipts": the plan's wording.
- T1, a future-dated receipt passing the late check: a clock stepped back (the Pi has no RTC) only lengthens one
  window.
- T2, the fit-drop test hard-coding 2: it also asserts the 2,000-byte bound.
- T2, the mixed query: the second query is Near only, so both shapes are covered.
- T3, no test of a hold pushed over LESSON_BYTES by the receipt line: it can't happen. The worst hold block with a
  receipt (32-character ship; claim and why at their caps, all backticks, which `_spaced_ticks` doubles) is 1,368
  bytes against 2,000. Recheck after I2 adds a path.
- T3, the hold-with-receipt test standing alone: stylistic.

I agree with both rulings: the pre-flight one (the branch kept both tests of another ship's receipt) and the venv one
(test_lessons_hold_contract.py passed in my run).

## The section 4 ruling

It is right, and the branch keeps to it. Nothing reads outcomes into ranking. `lesson_queries` gains no
`reordered`/`displaced` columns, the query path reads no outcomes, and section 7's counting, weight, shadow and
falling-out tests are rightly absent. The cost-if-wrong claim holds: the table is exactly the spec's, so section 4
builds on it with nothing undone.

Two nuances for the revision:
- n ≤ 1 is not quite an invariant. On a non-origin peer the derived ship can change within 30 days (one ship removed,
  another added), which gives two judges on one peer. This is rare, and a shadow would still read about 0.
- The cluster case needs more than a second-judge source. The derivation itself refuses a second ship
  (OUTCOME_SHIPS), so the revision should name both.

## Cross-task questions

- Free text in `lesson_outcomes`: none.
- An outcome for a receipt the ship was never shown: effectively no. Receipts are written only for lessons the fit
  kept, and no listing prints receipt ids. The one exception is `lesson-repeat(s)`, which prints the receipt of a lesson
  the ship declared seen. Receipts the hook drops after the answer (hard stop, hold filter) were already possible, and
  the ship never sees their ids.

## Declined to judge

- Section 4 and its section 7 tests: the plan's ruling, judged above.
- Lessons shown at a prompt never take outcomes (no receipts there): the spec's intent; it lowers coverage.
- Whether an outcome line in a hold's deny invites an early judgement: the spec's and plan's design.
- An 8-hex short id colliding with an older receipt of the same ship: about N/2^32 per receipt.
- Makefile quoting of `RECEIPT`/`OUTCOME`: `lesson-repeat`'s pattern, in the ship's own invocation.

## Tests run at a25aa9b7

- Peer (worktree `peer/.venv`): test_lessons_outcomes, _repeats, test_lessons, _index, _room, _hold_contract:
  `186 passed, 1 warning in 154.12s (0:02:34)`.
- Agent: test_lessons_hook, test_lessons_hold, test_hold, test_install_hold: `346 passed in 40.04s`.
- I1's two guard tests, each run once alone: `1 failed, 1 warning in 2.06s` (restore) and `1 failed, 1 warning in
  0.44s` (packaging).

## Re-review of the fix wave (a25aa9b7..6bb6a5b8)

I1: ADDRESSED. `'lesson_outcomes'` is now in COORDINATION_TABLES at peer/tests/test_restore.py:2540 (diff hunk @@ -2537). `tests/test_lessons_outcomes.py` is in the sdist list at peer/pyproject.toml:182.

I2: ADDRESSED.
- agent/superyak_agent/lessons_hook.py:224-229: `receipt_line(r, data_dir, checkout=CHECKOUT)` shell-quotes both with `shlex.quote`. `shlex` is imported at line 18 and `CHECKOUT` is defined at line 57.
- Line 236 (`_shown`): the line appears only when the lesson has a receipt and `data_dir` is truthy. Otherwise there is no receipt line at all.
- All callers pass the data dir:
  - `render`, line 241.
  - `hold_reason`, line 249.
  - `_output`, line 435, called from lines 515 and 553 with `settings['data_dir']`.
  - agent/superyak_agent/lessons_hold.py:176, `data_dir=settings['data_dir']`.
- `settings['data_dir']` is a validated key (lessons_hook.py:301-307).
- Tests cover the exact line, quoting of paths with spaces, and no line when there is no data dir.

M1: ADDRESSED. The line uses `OUTCOME=(helped|misled|unused)`. The `bash -n` test is at agent/tests/test_lessons_hook.py, test `test_the_line_pasted_verbatim_into_a_shell_is_a_syntax_error_so_nothing_is_recorded`. I ran the line myself: `bash -n` gives "syntax error near unexpected token `('" and exit 2. zsh is not installed here, so I did not check zsh. The zsh no-match error is the implementer's claim, and I could not confirm it.

M2: ADDRESSED.
- The new labels now say "Lesson outcomes spec, section 3" in the Makefile comment above `lesson-outcome`.
- Same in peer/superyak_peer/lessons.py:
  - the OUTCOMES comment (about line 63);
  - the refusals comment (about line 114);
  - the `describe_outcomes` and `lesson_outcome` docstrings;
  - the `outcome` and `outcomes` verb help strings.
- peer/tests/test_lessons_outcomes.py:1-2 docstring now names the spec.
- First-rail labels such as the `REPEAT_*` comments and the lesson-repeat Makefile comment are untouched.
- Two nits: the `describe_outcomes` docstring's first line is now over-long, and the Makefile `lesson-outcome` usage string still shows `OUTCOME=helped|misled|unused`. That is only an echoed usage message, not the hook line.

M3: ADDRESSED. Rows for `lesson-outcome` and `lesson-outcomes` are added to the targets table in peer/tests/test_station_units.py (around lines 307-308).

Deferred test: ADDRESSED. `test_a_lesson_only_the_receipt_line_pushes_past_lesson_bytes_is_skipped_not_cut` is in agent/tests/test_lessons_hold.py. `LESSON_BYTES` is set to the plain hold's length. The test asserts the receipt version is over that size, then asserts the hold list is empty. It matches the `continue` path at lessons_hold.py:177-178. A second new test checks that a hold with a receipt carries the data-dir line.

New breakage in the fix diff: none.

Out of scope:
- `receipt_line`'s `data_dir` has no default, while `_shown` guards for a missing one. Harmless.

Verdict: all findings addressed
