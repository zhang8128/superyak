# Final review fixes: permissions by place, step 1

Branch `permissions-core`, worktree `/home/andy/superyak/.worktrees/permissions-core`, on the station Pi, 2026-10-27.
Base `9155015`, head `9695bea` (14 commits). The review is `final-review.md` beside this file. Every new test is in
`engram/tests/test_permissions_review_fixes.py` unless named otherwise.

## Tests run at the head

- `tests/test_permissions_[a-m]*.py` with `tests/test_lighthouse_daemon.py`: 463 passed (4 min 32 s).
- `tests/test_permissions_[n-z]*.py` without the property tests: 366 passed, 29 skipped (the `ENGRAM_PI_BUDGET` ones),
  in 2 min 47 s.
- `tests/test_permissions_properties.py`: 33 passed (7 min 29 s).
- `tests/test_federation.py`: passed at M4 (it calls `record_copy`).
- The whole suite was not run (the controller runs it). U24 (`ENGRAM_PI_BUDGET=1`) was not run, as the rules say.
- One flaky failure, then a pass: `test_more_than_20000_placements_serve_nothing_under_enforce` failed once in the a-m
  batch at load average 4. See "Concerns".

## The reference test (a083a96)

- Every `decide` and `decide_bulk` result and every F1 case is byte-identical to the reference.
- No fix changed a decision. M3 changes what the daemon does with a read item, not what `decide` returns.
- M2 changes one field on purpose: an eligible set's `horizon`.
  - It changed in 149 of the 1,116 eligible-set comparisons, across all 40 random worlds and their lazy variants.
  - Each time it moved earlier, to the time of a row read by its log time that comes into or goes out of force after
    the set's `at`. In random worlds, uses are sampled at times before some rows were written.
  - `same_set` now checks that the live horizon is exactly `min(reference horizon, M2's times)`. It computes M2's
    times from the State with its own code (`m2_terms`), not with the code under test. Every other field must still
    be equal.

## I1. Proposals and child grants are bounded

**What changed**

- I checked first: no decision reads a proposal. The only readers are `_on_proposal` (sign and decline),
  `Ledger.proposals`, the CLI's `_proposal_of` and four tests.
- New constants in `permissions.py`:
  - `MAX_OPEN_PROPOSALS_PER_AGENT = 64`;
  - `MAX_OPEN_PROPOSALS = 1024`;
  - `MAX_CHILD_GRANTS = 64`.
- `Ledger._check_open_bounds` runs inside `_append`'s `BEGIN IMMEDIATE`, next to the records bound:
  - It counts open proposals (`status = 'pending' AND expires > at`) for the filer and for the whole ledger.
  - It counts live child grants of the parent (`revoked_seq IS NULL AND expires > at`).
  - A refusal is a `RuleError` that names the bound, for example "agent:x holds at most 64 open proposals, and holds
    64…" or "a grant has at most 64 live child grants…".
- `state()` no longer loads the `proposals` table. `State.proposals` is a `ProposalMap`:
  - a lazy, read-only Mapping on the State's row reader that holds nothing;
  - it reads a row with its body when asked, and a row decided after the State's seq reads as pending, as before;
  - iteration streams 512 rows at a time.
- `Ledger.proposals(now)` lists open ids through SQL (`open_ids`) and reads only those rows.

**RED → GREEN**

- RED: the three tests failed with `DID NOT RAISE`:
  - `test_i1_an_agent_holds_at_most_64_open_proposals`;
  - `test_i1_a_ledger_holds_at_most_1024_open_proposals_and_a_state_holds_none_of_them`;
  - `test_i1_a_parent_grant_has_at_most_64_live_children`.
- GREEN: 8 passed.
- The probe holds the bound at full size, without `ENGRAM_PI_BUDGET`: 16 agents file 64 allows each, every one
  with a 512-memory selector, and the 1,025th is refused. A State then grew by **1,056 B** for 1,024 proposals,
  against about 14 KB a proposal (14 MB) before the fix. Filing all 1,024 took 18.4 s.
- Both permissions batches passed.

**Commit:** `c3aabde`.

**Rulings**

- Ruling: "open" means pending and not expired, for both proposal bounds — an agent whose 64 proposals all expired
  must be able to ask again, or the bound would lock it out for good — cost if wrong: expired, undecided rows can
  pile up in the ledger. They are never in a State now, so memory is unaffected.
- Ruling: the per-agent bound counts per filer (`by_agent`), so it also caps a person's joint-place proposals at 64
  — the table has one filer column, and 64 open joint proposals per steward is far past use — cost if wrong: a
  steward with more than 64 pending joint places is refused until some are signed or declined.
- Ruling: "live" child grants means not revoked and not expired at the write's time, as the controller said —
  cost if wrong: an agent that keeps issuing and ending child grants still adds rows that every State holds whole.
  See "Concerns".
- Ruling: proposals are left out of `state()` entirely, read on demand through `ProposalMap`, rather than filtered
  at load — this keeps every reader's meaning and every existing test unchanged, and a State holds nothing for
  them — cost if wrong: a read of `state.proposals` after another writer can see a proposal filed after the State's
  seq. The old dict had the same quirk, because proposals have no `created_seq`.

## I2 (SH-13). A chunked `collection add` or `remove` is honest

**What changed** (`permission_cli._collection`, `_perform`)

- Refs are checked against the State before they are split into acts:
  - `add` leaves out refs that are already members and says so before the yes ("note: N of the refs are already
    in …"). If none is new, it refuses before the yes.
  - `remove` refuses before the yes when the collection does not exist, or names each ref that is not a member.
- `_perform` writes one act at a time. When an act fails after others were written, it prints "act 1 of 2 done
  (log 4); the rest were not written." (or "acts 1 to n of m done (logs …)"), runs the sweep, then re-raises.

**RED → GREEN**

- RED: four tests failed. The add exited 1 with "every one is already in"; the two before-the-yes refusals waited for
  the TTY (exit 3); and the partial-write message was missing.
- GREEN: 4 passed. Every test file that imports `permission_cli` passed (137).
- The repro uses `MAX_ACT_OBJECTS` patched to 3 and m3 to m5 already members, as in the review.

**Commit:** `ec1ad0a`.

**Rulings**

- Ruling: after a partial write, `_perform` runs the sweep before it re-raises — R18 says the CLI sweeps after
  every command that writes, and a partial `uncollect` is a narrowing the house must follow — cost if wrong: one
  extra sweep, which only follows the ledger.
- Ruling: `remove` names every missing ref, cleaned with `_clean`, with no cap — the controller said to name each,
  and the refs are the person's own command line — cost if wrong: a very long refusal for a very long command.

## I3. The plan's "Verification before merge" passes as written

**What changed**

- `engram/tests/conftest.py` is main's file again (`git checkout main -- …`).
  - The only test that lowers `LEDGER_BUSY_MS`, `test_rf2_locked_ledger_reads_closed`, now uses `monkeypatch`.
  - `_daemon_over`, `raised_daemon` and `daemon_with_outside_home_placement` lost their `busy_timeout_ms`
    parameter, so nothing sets the global without putting it back.
  - No R29 amendment was needed.
- The blank line at the end of `test_permissions_boxes.py` is gone.
- The plan has a note under "File Structure" listing:
  - the SH and P tasks' support files: `permissions_memory_support.py`, `test_store_digest_chunks.py`,
    `permissions_reference.py`, `permissions_budget_core.py`, `permissions_budget_ledger.py`, `pi_budget_probe.py`;
  - the documents from the branch's start and its two `trail-arrows-spec` merges (`6610215`, `8e2a075`), naming
    the rev-8 review and spec.
  - Step 2 now reads "File Structure" with that note.
- Step 4 now expects revision 8's 16 tests:
  - three timed: 2 s, 30 s and 300 s;
  - eleven per-operation peaks, of which the eligible probe has 6 s and the bulk probe 300 s;
  - two daemon peaks;
  - so five time budgets and 13 peaks, the peaks counted as VmHWM plus VmSwap.
- Also added: rulings R34 (the I1 bounds), R35 (M2) and R36 (M8), and gate G12. G12 carries the spec wording these
  need, M10's included, to the spec's next revision, which needs its own reviewer.

**Evidence: the cheap checks, run at the head**

- Step 1: `git merge-base --is-ancestor main HEAD` succeeds.
- Step 2: every file in `git diff --name-only main...HEAD` matches "File Structure" or its note (a grep against the
  list printed nothing).
- Step 2: `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/` prints only
  `engram/tests/test_packaging.py`.
- Step 2: the `-U0` grep prints exactly the two lines for 43 and 45.
- Step 2: `git diff --check main...HEAD` prints nothing.
- Step 6: prints `Gate(mode='off', cause=None)`.

**Commits:** `aa3c4f1` (tests), `e46cb97` (plan and CLAUDE.md, shared with I4).

## I4. The embedder deploy gate

**What changed**

- The plan has gate **G0**, before G1 and G2: every machine that runs the engram lighthouse daemon has
  `embedder_socket` in `~/.config/superyak/runtime.json` and runs `superyak-embedder` (spec 12.2).
- A new Verification **step 9** gives the per-machine checks:
  - a `python3 -c` one-liner that reads the key;
  - `systemctl --user is-active superyak-embedder`, or the Mac's job that runs `superyak-runtime embedder`;
  - the verdict names each machine and what it showed.
- G2's text now says a daemon starts only where G0 holds.
- `engram/CLAUDE.md` names the two fail-closed changes and the one requirement (the daemon refuses to start without
  `ENGRAM_EMBEDDER_SOCKET`) and points to G0.
- The daemon's refusal is unchanged.

**Evidence:** `grep -n "never run, for the person" engram/CLAUDE.md` still finds its one line.

**Commit:** `e46cb97`.

**Ruling**

- Ruling: step 9 says a machine that fails the check keeps the code from before this branch until it passes — that
  is what "before the refusal ships" means for a machine that pulls the merge — cost if wrong: it is stricter than
  needed if Andy would rather fix runtime.json just after the merge, before any restart.

## M1. A row is revoked once

**What changed:** `"revoked_seq": None` is now in the `where` clause of:

- `_make_revoke`;
- `_make_replacement`'s update, which serves `shorten` and `narrow`;
- `_make_end_grant`, which serves `revoke-grant` and `give-up-grant`.

A second writer's update matches no row. `_project` refuses it ("… update matched no row"), and the write's whole
transaction rolls back, the replacement's insert included.

**RED → GREEN**

- RED: five tests on two connections failed with `DID NOT RAISE`, for revoke, shorten, narrow, revoke-grant and
  give-up-grant. In each, a second writer's revocation runs after the first passed its check and before it writes.
- GREEN: 5 passed.
- The records, grants, ledger and acts tests passed (86).
- The tests also check that the first revocation stands, that no second live replacement exists, and that
  `verify()` is clean.

**Commit:** `eb59ff2`.

## M2. A backward clock step and the cache

**What changed**

- An eligible set's horizon now also holds every time after its `at` at which a row it reads by its log time comes
  into or goes out of force. That covers:
  - the requester's agent places and group memberships (`_requester_times_after`);
  - each placed object's memberships, its subject rows up its `copies` chain, and its lane notes.
- `_share_key` gathers these times in the same pass that builds the key, through a new `later` list that
  `_own_subjects` and `subjects_of` also accept. Objects decided alone go through `_object_times_after`.
- A decision's own `horizon` is unchanged.
- I chose the controller's second option, putting the time in the horizon, over treating such rows as in force. See
  the ruling.

**RED → GREEN**

- RED: three tests failed, with the cache horizon at 2026-12-01 instead of 2026-11-03:
  - `test_m2_a_deny_membership_written_past_the_daemons_clock_ends_the_cached_allow_at_its_time`;
  - `…_a_co_subject_written_past…`;
  - `…_a_requester_moved_out_past…`.
- In each, the ledger's writer is a day ahead of the daemon's clock. The frame at 11-02 is allowed, and its cached
  entry must end at 11-03, after which the use is refused with no ledger write in between.
- GREEN: 3 passed.
- `test_eligible_set_holds_each_placements_ledger_decision_and_the_earliest_horizon` in
  `test_permissions_daemon_cache.py` now adds M2's times, from the reference test's own `m2_terms`.
- The reference test is described above.

**Cost, measured**

- First version, a second pass per object:
  - +0.16 to 0.23 s on a 2.5 s lazy-State build of 20,000 placements;
  - about +20% on the daemon test's 20,000-placement frame.
- Second version, folded into `_share_key`'s pass: 3.10 s against 3.13 s without M2 (median of five, lazy State,
  20,000 placements with 8 subjects each). The fixture world measured 0.80 s both ways.

**Commits:** `81e80a2`, `9695bea`.

**Rulings**

- Ruling: the time goes in the eligible set's horizon (R35), rather than counting a deny membership or subject row
  whose `at` is after t as in force. Counting it as in force:
  - would contradict 5.3's table for every decision at a t before the row: `explain --at`, audits, and every random
    world;
  - would need matching changes to the oracle (`meets`, `own_subjects`), to the gluing check's boxes (`_row_times`
    would have to start a deny membership at the anchor) and to F1, all of which the review found sound;
  - while horizon terms beyond the spec's reading are already allowed by 6.5 step 7 when they are only ever earlier.

  Cost if wrong: while the clock is behind, a deny membership or co-subject written by the faster clock does not
  count at the daemon's t. It is refused once the daemon's clock reaches the row's time, not at once, so "deny
  wins" can lag by up to the size of the clock step. Before this fix it lagged until the next ledger write.
- Ruling: the requester's rows (agent places, groups) and lane notes are included too, although the review named
  only memberships and subjects — a requester moved out of its place during a backward step is the same widening,
  and both read the same way — cost if wrong: an earlier rebuild, only after a clock step.

## M3. A read refuses a copy with a sourceless placement

**What changed:** `Frame.read_item` reads every row of the item. If any row has no object, it returns as for an
item with no object at all: under `enforce` it delivers nothing and writes no receipt; under `shadow` the legacy
path delivers it.

**RED → GREEN**

- RED: `test_m3_under_enforce_a_read_refuses_a_copy_one_of_whose_placements_has_no_object` delivered the content.
  Recall already filtered the item.
- GREEN: 2 passed.
- The guard test under `shadow` passed before and after.
- The daemon tests and `test_lighthouse_daemon.py` passed (207).

**Commit:** `e1c2efb`.

**Ruling**

- Ruling: under `shadow`, such an item gets no receipt, like an item with no object, rather than a receipt for its
  sourced object alone — such a receipt would say "allowed" for an item `enforce` refuses — cost if wrong:
  `report shadow` does not list the item. `report shadow`'s placement list still shows the sourceless placement
  ("no object").

## M4. A kept copy carries every matching source's subjects

**What changed**

- `Ledger.record_copy(…, also=())`: the subjects of the other objects the content matched are carried in the same
  log row, each subject row `added_by` `copy:<that object>`, and they count against `MAX_SUBJECTS`.
- `copies` keeps the one source.
- The guard's `_Keep` carries `also`, the other decided objects.

**RED → GREEN**

- RED: the `also` parameter did not exist (`TypeError`), and in
  `test_m4_the_remember_guard_carries_the_union_of_every_matching_sources_subjects` the kept copy lacked
  `person:amy`. In that test, m1 is the newest delivery and m2, with co-subject Amy, has identical text.
- GREEN: 2 passed.
- The keep, server, e1, lanes, edges, p36, sweep, share, memory-writes and lazy-failures tests and
  `test_federation.py` passed.

**Commit:** `29a269d`.

## M5. A place's name cannot rewrite the terminal

**What changed**

- `_prep_register_place` refuses a name that is not `isprintable()` after stripping: control, format (such as
  U+202E) and line-break characters.
- `confirm` prints its words and change through `_clean_lines`, which runs `_clean` on each line and keeps the line
  breaks.

**RED → GREEN**

- RED: four names (escape, newline, U+202E, BEL) were accepted, and `confirm` printed an escape raw.
- GREEN: 5 passed. The CLI, places, names, acts, records and ledger tests passed (238).

**Commit:** `1424535`.

## M6. `Ledger.cosubjects` follows copies

**What changed:** `Ledger.cosubjects(ref, at=None)` is now `subjects_of(state, ref, at)` less the ref's default
subject, its store's owner (not for an imprint store). No caller depended on the old meaning: the only callers were
two tests, which still pass, and the imprints plan's future `cosubjects(m)`, which the spec says must read this set.

**RED → GREEN**

- RED: a source's subject added after the copy was made was missing from the copy's co-subjects.
- GREEN: 2 passed. `test_permissions_acts.py` passed.

**Commit:** `70104c2`.

## M8. A shadow receipt keeps the ledger's own refusal

**What changed**

- Under `shadow`, when the publisher's audience check refuses a read, the receipt keeps the ledger's `allowed` and
  `refusal`. It cites the audience refusal as an entry of its own:
  `{"layer": "publisher", "kind": "audience", "action": "inject_context", "verdict": "deny", "record": null, "version": null}`.
- Under `enforce`, nothing changed.
- `report shadow` reads the audience refusal from that entry (`_audience_refusal`). It still reads receipts written
  before this fix through their `LEGACY_DENY` refusal, and its listing shows `LEGACY_DENY at publisher` either way.

**RED → GREEN**

- RED: 5 tests failed. Two of them pinned the old receipt shape:
  - `test_permissions_daemon.py::test_shadow_receipt_keeps_the_ledgers_verdict_when_the_audience_path_refuses`;
  - `test_permissions_shadow_audience.py::test_shadow_receipt_records_the_audience_refusal_when_the_ledger_refuses_too`.

  Both are branch-new files. I updated them to the new shape.
- GREEN: 6 passed. The daemon, CLI, views, uses and e1 tests passed (222).
- The old receipts' tests in `test_permissions_cli_read.py` and `test_permissions_shadow_audience.py` pass
  unchanged.

**Commit:** `6c05ae0`.

**Ruling**

- Ruling: a `cited` entry of kind `audience`, not a new column — the receipts schema stays as spec 9.1 fixes it, and
  the steward and owner views already render any cited entry — cost if wrong: a reader that assumes every cited
  kind is consent, restriction, legacy, outside or co-subject meets a new kind. Gate G12 has the spec name it.

## M9. `sweep` says it failed

**What changed:** `run_sweep` wraps `_run_sweep`, which returns (report, failed). The `sweep` command says "The
placement sweep failed (the warning above says why)…" on stderr and exits 1. After other commands the sweep stays a
warning that never changes the exit code (FS1).

**RED → GREEN**

- RED: `sweep` exited 0 and printed "Placement sweep: nothing to change."
- GREEN: 1 passed. The CLI, read and sweep tests passed (88), and the other CLI importers passed (66).

**Commit:** `41a287d`.

**Ruling**

- Ruling: `sweep` exits 1 when its sweep failed — the sweep is that command's whole job, and a script must be able
  to tell — cost if wrong: a script that ran `sweep` and ignored failures now sees exit 1.

## M10. The probe records VmSwap

**What changed**

- `tests/pi_budget_probe.py` prints `swap_kb` (`VmSwap`) beside `peak_kb`.
- `test_permissions_pi_budget.py` records it in `peaks.jsonl` and its printed line, and checks
  `peak_kb + swap_kb < 512 MiB`.
- The spec text is untouched. Gate G12 carries the wording for the spec's next revision.

**RED → GREEN**

- RED: `test_each_probe_runs_and_reports_its_peak[state]` raised `KeyError: 'swap_kb'` once that test required the
  field.
- GREEN: the four budget files gave 20 passed and 29 skipped.

**Commit:** `ee2a02e`.

**Ruling**

- Ruling: the gated peak check counts VmHWM plus VmSwap — a page in swap is not in VmHWM, so the sum can only make
  the check stricter — cost if wrong: a run that swapped could fail U24 where VmHWM alone would pass.

## Not done

- M7 and the P8 items, by the controller's rulings.
- U24 under `ENGRAM_PI_BUDGET=1` and the whole suite: the controller runs them. U24's timed budgets should be
  re-measured on this head. M2 measured within noise on the lazy State, and nothing else touches a timed path.

## Concerns

1. **The 20,000-placement daemon test is close to its wait.**
   - `test_more_than_20000_placements_serve_nothing_under_enforce` failed once in a batch at load average about 4.
     Its frame, build included, measured 0.63 to 0.75 s against `REBUILD_WAIT_S = 1.0`.
   - M2's first version added about 0.15 s there. The folded version measures within noise, and the test passed
     alone and in the next full batch.
   - It is the review's load caution (P8 (a)) showing up in a test.
2. **Child grants are still held whole.** I1 bounds live children per parent, but every State holds revoked and
   expired grants whole. An agent that issues and ends child grants in a loop still grows every State, slowly. A
   bound on all grants, like `MAX_RECORDS`, would close it.
3. **Sign and decline have the same race as M1.** Both update a proposal `where {"id": …}` only, so two concurrent
   terminal signs could run a proposal's act twice. Adding `"status": "pending"` to those `where` clauses is the M1
   fix for proposals. It is not in this wave's list.
4. **M2 leaves one gap.** A deny written during a backward step with an explicit past `valid_from` has its anchor
   after t, and the anchor is not a horizon term. The CLI's default `valid_from` is the write time, which is a
   horizon term.
5. **Two tests now depend on another module.** `test_permissions_daemon_cache.py` imports `m2_terms` from
   `test_permissions_reference.py`, which ties those two test modules together.
6. **The plan's Global Constraints still names only two changes.** Its first bullet does not mention the embedder
   requirement; G0, G2, step 9 and `engram/CLAUDE.md` now carry it.

## Residual follow-up

The scoped re-review's residuals: M2's open part, the fix wave's concern 3, Minors 1 to 7, and the G12 note for
concern 5. Base `9695bea`, head `2809d9a` (9 commits). New tests are in `engram/tests/test_permissions_review_fixes.py`
unless named otherwise.

### Tests run at the head

- `tests/test_permissions_[a-m]*.py` with `tests/test_lighthouse_daemon.py`: 463 passed (4 min 32 s).
- `tests/test_permissions_[n-z]*.py` without the property tests: 415 passed, 29 skipped (the `ENGRAM_PI_BUDGET`
  ones), in 3 min 13 s. That is 49 more than at `9695bea`: 40 before-t0 reference worlds, the M2 count test, the
  fourth M2 test, six concern-3 tests and the `uses` text test.
- `tests/test_permissions_properties.py`: 33 passed (7 min 9 s).
- The whole suite and U24 were not run, as the rules say.

### The reference test (a083a96)

| | From t0 (the 40 random worlds and their lazy variants) | Drawn before t0 (new) | All |
|---|---|---|---|
| Before (`9695bea`) | 149 of 1,116 eligible-set horizons moved by M2 | (none) | 149 of 1,116 |
| After (`2809d9a`) | 149 of 1,116 | 593 of 598 | 742 of 1,714 |

- Every `decide`, `decide_bulk` and F1 result is still byte-identical to the reference. That includes the new
  comparisons at times before t0.
- The "before" count was measured on the new code with `_anchor_after` patched to return None, which is the code at
  `9695bea`. It matched the earlier report's 149 of 1,116.
- The anchor term moved no horizon in the existing worlds, because a random world sets `t0 = max(anchor)`: "no use
  is drawn before every record exists". So `m2_terms`' new term was untested there. See "Item 1".

### Item 1. M2's open part: a record's anchor after t is a horizon term

**What changed**

- `permissions._anchor_after(state, t)` gives the earliest anchor after t of an unrevoked record, or None. It reads
  every record, whatever its layer or effect. It is memoized per (State, t), as a one-tuple, because `_memo` does
  not keep None.
- `eligible_set` adds it to its horizons. `decide`'s own horizons are unchanged.
- The reference test's `m2_terms` adds the same term with code of its own: `r.anchor > t` and
  (`revoked_seq` None or after the State's seq).
- `check_world` takes an optional `when`, which moves each sampled use (every part of a bulk use) to a time it
  draws. The new `test_uses_drawn_before_a_records_anchor_equal_the_reference` (40 cases, 15 uses each, lazy every
  sixth) draws times before t0: half uniform from a day before the first anchor up to t0, half a second either side
  of an anchor.
- The fourth M2 test is `test_m2_a_back_dated_deny_written_past_the_daemons_clock_ends_the_cached_allow_at_its_anchor`.
  It is the re-review's probe:
  - the daemon's clock reads 11-02;
  - m1 has been collected since 11-01;
  - a deny on the collection with `valid_from` 11-01 is written at 11-03.
- `test_permissions_daemon_cache.py` takes the term through `m2_terms` with no edit.
- Ruling R35 in the plan names the term.

**Cost:** 0.87 ms for the first call on a 10,496-record State, then a memo hit. The term is after t only while a
writer's clock is ahead of the daemon's, so in normal running it moves nothing.

**RED → GREEN**

- RED: the fourth M2 test failed, with `cache_horizon()` at 1796083200 (2026-12-01, the allow's end) instead of
  2026-11-03. A probe run showed m1 still allowed from the cache at 11-03 + 60 s.
- RED for the reference: with `_anchor_after` patched to None, the before-t0 test failed on case 0 with
  `1791858032 != 1791855700` (live horizon, then the expected one).
- GREEN:
  - the four M2 tests passed;
  - the reference, daemon-cache and review-fix files passed (144);
  - then all three batches above passed.

**Commit:** `095afc7`. Ruling R35's text is in `2809d9a`.

### Item 2. Concern 3: a proposal is decided once, and a person or place retired once

**What changed**

- Decline updates `where {"id", "status": "pending"}`, and so does `_signed`, which serves both signing paths: the
  owner's sign and the last joint signature.
- `_make_retire_person` updates the person and the home place `where {"id", "retired_seq": None}`.
- `_make_retire_place` does the same for the place.

**RED → GREEN**

- RED: six two-writer tests failed with `DID NOT RAISE`:
  - `test_concern3_a_proposal_one_writer_decided_is_not_decided_again_by_another`, for (sign, sign),
    (decline, sign), (sign, decline) and (decline, decline);
  - `…a_person_one_writer_retired…`;
  - `…a_place_one_writer_retired…`.
- A probe of (sign, sign) at `9695bea`'s code showed that the proposal wrote 2 records.
- GREEN: the six tests passed. The tests also check:
  - the first writer's status stands;
  - the proposal wrote at most one record;
  - `verify()` is clean;
  - `retired_seq` stays at the first writer's seq.
- Then the acts, ledger, memory-rows, places, e1, records, write-rules, p36, CLI, CLI-records, gate and migrate
  files passed (289).

**Commit:** `6eb4518`.

### Item 3. Minor 1: the plan records what `cosubjects` now does

**What changed**

- In "What the other plans use", the imprints bullet now gives `Ledger.cosubjects(ref, at=None)`:
  - it follows copies (`subjects_of` less the default subject, its store's owner, not for an imprint store);
  - it builds a State per call;
  - it raises `RuleError` on a malformed ref. Checked: `cosubjects('not-a-ref')` raises "4.1 object ref: not a
    mem:, road: or trail: ref".
- The bullet also says that the imprints plan's Task 8 test `test_a_copy_carries_what_its_source_gains_after_the_copy`
  (`led.cosubjects(copy) == frozenset()`) changes to `{"person:jenn"}` at the rebase.
- G6 says the same in brief.

**Evidence:** documentation only; `git diff --check` is clean.

**Commit:** `6ee966d`.

### Item 4. Minor 2: `uses` text and shadow receipts

**What changed** (`permission_cli._use_line`)

- An owner's row from a shadow receipt reads `allowed (shadow)` or `refused (shadow)`.
- A cited entry of kind `audience` that denies prints this line: `refused by the publisher's audience check
  (LEGACY_DENY at publisher): the legacy path delivered nothing`.
- `--json` is unchanged. The steward view (P 9.2) carries neither `shadow` nor cited kinds, so its text is as before.

**RED → GREEN**

- RED: `test_minor2_uses_text_marks_a_shadow_row_and_prints_its_audience_refusal` failed. The audience-only receipt
  read as a plain `allowed`.
- GREEN: the test passed. It checks:
  - an audience-only shadow receipt;
  - a shadow receipt that both paths refused, with `refused: DENIED at place:home/andy` and then the audience line;
  - a plain receipt, which is not marked.
- Every file that imports `permission_cli`, with the views tests, passed (184).

**Commit:** `1a10424`.

### Item 5. Minor 3: the reference test asserts that M2 is exercised

**What changed**

- `test_the_random_worlds_keep_exercising_m2` asserts that the uses from t0 on and the uses drawn before t0 each
  moved at least one horizon. It prints `M2 moved N of M eligible-set horizons, K of them in uses drawn before t0`
  through `capsys.disabled()`, so the line shows under `-q`.
- `same_set` counts every comparison (`M2_COMPARED`).
- The two world tests record their cases (`WORLDS_RUN`). The new test runs first any world that a `-k` selection
  left out, so its counts are always all of them.

**RED → GREEN**

- RED: run alone, before it ran the missing worlds, the test failed with 0 changed.
- GREEN: run alone, it passed in 33 s. With the whole file, it passed and printed "M2 moved 742 of 1714
  eligible-set horizons, 593 of them in uses drawn before t0".

**Commit:** `c66a09d`.

### Item 6. Minor 4: the shadow test asserts that no receipt is written

**What changed:** `test_m3_under_shadow_the_legacy_path_still_delivers_it` also checks that the `inject_context`
receipts are unchanged by the read.

**RED → GREEN**

- The test passed at once, because the code already writes no receipt.
- To show that the assertion can fail, I briefly put back the behaviour from before M3 (`if False:` for the guard,
  and `objs` without the sourceless rows) in `lighthouse_daemon.py`. The test then failed: "Left contains one more
  item: {… 'allowed': 1 …}". The file was restored with `git checkout`, and `git diff` was clean.
- GREEN: 2 passed.

**Commit:** `03059cf`.

### Item 7. Minor 5: the `swap_kb` docstring

**What changed:** the docstring now says that `VmSwap` is read at exit, once the operation is done, not at the
moment of the peak. So `peak_kb + swap_kb` is a proxy for the most the run held, not a measure of it.

**Evidence:** the module imports. `test_permissions_pi_budget.py` gave 16 skipped (`ENGRAM_PI_BUDGET` is unset, as
the rules require).

**Commit:** `3f52711`.

### Item 8. Minor 6: a readable refusal for a second writer

**What changed**

- When an update matches no row, `Ledger._unmatched(table, where)` runs. If the where clause names a row by `id`
  and guards it with `revoked_seq`, `retired_seq` or `status`, it reads that row. If the row exists and its guard
  changed, the refusal says so:
  - `r-… is already revoked (by another write)` for a record's revocation and its replacement (shorten, narrow);
  - `g-… has already ended (by another write)` for `revoke-grant` and `give-up-grant`;
  - `p-… is already signed (by another write)`, or `declined`;
  - `person:amy is already retired (by another write)`, and the same for a place.
- Any other unmatched update keeps the raw where clause.
- The rule prefix stays "5.5 storage". `_project` runs only inside `_append`, so "another write" is accurate.

**RED → GREEN**

- RED: the five M1 tests and the six concern-3 tests were tightened to the readable text, anchored with `^…$`. All
  11 failed with "Regex pattern did not match", for example "5.5 storage: persons update matched no row: {'id':
  'person:amy', 'retired_seq': None}".
- GREEN: 11 passed. Then the review-fix, acts, ledger, records, places, CLI-records and grants files passed (154).

**Commit:** `358100a`.

### Item 9. Minor 7: Global Constraints names the embedder requirement

**What changed:** the plan's line 16 now names:

- the two fail-closed changes: the daemon never serves `group:outside-home`, and `share` refuses that name;
- the one requirement: the lighthouse daemon refuses to start, under every gate, without `ENGRAM_EMBEDDER_SOCKET`
  (spec 12.2, gate G0).

This matches `engram/CLAUDE.md`.

**Commit:** `6ee966d`.

### Item 10. The G12 note for concern 5

**What changed:** G12 now also carries a departure from 12.2 "Modes" to the spec's next revision. 12.2 says "both
decisions go to the receipts". Under `shadow`, though:

- an item one of whose placements has no object gets no receipt, as an item with no object at all;
- the legacy path still delivers it;
- `report shadow` lists the placement ("no object").

**Commit:** `6ee966d`.

### Concerns

1. **The random worlds never draw a use before a record's anchor.** That is by design (`t0 = max(anchor)`), so the
   M2 anchor term could not move a horizon there. The new before-t0 test adds 598 eligible-set comparisons, with their `decide`,
   `decide_bulk` and per-object comparisons, at times before some records exist. All are exact against a083a96.
   This is new reference coverage, not only coverage of M2.
2. **The steward view of `uses` is not marked.** P 9.2's rows have no `shadow` and no cited kinds. So a steward
   view of a shadow receipt that only the audience check refused still reads as "allowed". Changing that means
   changing P 9.2's fields, which is the spec's to decide.
3. **The anchor term counts every unrevoked record, of every layer.** A record whose anchor is after the daemon's
   t, from a clock step, ends every cached set at that anchor, even sets that never read the record. This is the
   ruling's "a few more rebuilds under clock skew". It costs nothing without skew.
4. **Two test modules still depend on each other.** `test_permissions_daemon_cache.py` imports `m2_terms` from
   `test_permissions_reference.py`, as before (the earlier concern 5). It now also takes the anchor term from there.
