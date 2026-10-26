# Permissions by place: review of the step 1 plan

Date: 2026-10-25. Reviewer: a fresh agent on the Pi (`smart`). I took no part in writing the plan or its spec.

- Plan: `docs/superpowers/plans/2026-10-25-permissions-by-place.md` (untracked, 2,854 lines, read whole).
- Spec: `docs/superpowers/specs/2026-10-25-permissions-by-place-design.md`, revision 6 at `e737e02` (read whole).
- Also read: the vision, the interface table, the consolidation log, and the parts of the imprints and trails plans
  that use this plan's names.

I edited no file but this one. I changed no code. I ran no engram tests. I committed, pushed, merged, deployed and
posted nothing.

## Verdict

**Approve with changes.** It is not approved as written, because two must-fix items remain (MF1, MF2). Each one is
a local design fix in one task. Once both are fixed, nothing I found blocks the build. The should-fix items are
worth doing before the build starts.

Coverage is good. Every step-1 component of P 16, and every test of P 17 (PT1 to PT12, U1 to U28, E1, F1), maps to a
task. The order works, with one exception (SF7). Names match the spec and the other two plans. Nothing touches the
live station. The commands run on this Pi.

## Must-fix

**MF1. The context runtime would drop every Lighthouse item under `shadow` and `enforce`** (Task 22).

- **What the plan says.** `_evidence` copies `permission` when the item has it. `neighbor_arm` turns the
  `permission` object into its one-line string. `validate_read` keeps the object as it is.
- **Why it breaks.** The context runtime checks each item again before dispatch. `_read_entries` reads the item from
  the daemon again through `validate_read` (`engram/context_lighthouse.py:170`). It keeps an item only when
  `_version(item)` equals the version from search (`:185-186`). `prepare_dispatch` drops any key whose version
  differs (`:204-206`). `_version` hashes `_evidence` (`:33-34`).
  - Search items carry the line, a string, because they came through `neighbor_arm`.
  - Re-read items carry the object, a dict.
  - Each read also writes a new receipt (P 9.1), so even the line would differ: `receipt #…` changes every read.
- **The result.** Under `shadow` and `enforce` (R9 adds the annotation in both), every Lighthouse candidate fails the
  dispatch check. The runtime delivers none of them. `shadow` is meant to deliver by the legacy path as today. No
  test in the plan runs `prepare_dispatch`: `test_u10_the_context_runtime_evidence_carries_it` checks only
  `_evidence`. The existing context tests run with no ledger, so they can't catch it either.
- **Fix.** Leave `permission` out of what `_version` hashes, or out of the dispatch comparison. Keep it in what the
  model sees. Add a test: a context-runtime candidate that carries a `permission` line survives `prepare_dispatch`,
  even though the re-read carries a new receipt id.

**MF2. The settling lane note is written before the re-lane commits** (Task 17; P 5.3, L5).

- **What the plan says.** `set_episode_lanes` runs the `UPDATE` and `_commit`, then calls the listener with
  `"after"`.
- **Why that is wrong here.** The one real re-lane is compression's (`engram/compress.py:510`). It runs inside
  `with self._storage.transaction():` (`:466`). Inside an outer transaction, `Storage._commit` does nothing
  (`engram/storage.py:182-187`). So the `"after"` note, which names the new lane, lands in the ledger while the
  store's `UPDATE` is still uncommitted. If `_commit_state` then raises, the store rolls back to `personal`, while
  the ledger's latest note says `work`. The same happens if the process dies before the commit.
- **The result.** A work-lane allow anchored after that note matches a memory that is still personal. One example
  is an inside-home allow by lane. Another is a collection allow narrowed to `lanes: ["work"]`. P 5.3 orders the
  notes to prevent exactly this: "a note that claimed a move before it happened would let a work-lane allow match a
  memory that is still personal." The sweep doesn't repair it, because the latest note isn't `pending`. U25's tests
  call `set_episode_lanes` with no outer transaction, so none of them sees this.
- **Fix.** Write the `"after"` note only once the outermost storage transaction has committed, and the `"failed"`
  note on its rollback. For example, `Storage.transaction()` could run queued after-commit and after-rollback calls.
  Add a test: a re-lane inside `transaction()`, followed by an exception, leaves the old lane, or `pending`, as the
  latest note. A later work-lane allow must not match the memory.

## Should-fix

**SF1. Say what `outside` replaces** (Tasks 5 and 7; XM1).

- The imprints plan's Task 28 puts every inner record in its owner's home layer, and passes
  `outside={"place:home/andy": ceiling}`.
- XM1's fix makes that one layer the ceiling ⟦c⟧ itself. If `decide` meets Andy's ledger records with the callable,
  sam's imprint is refused: the XM1 failure again.
- Task 5's interface should say that, for a place id in `outside`, the callable is that layer's whole verdict, and
  no ledger record in that layer is read. Task 7's two-owner test would catch the mistake, but the interface should
  not leave it open.

**SF2. Compute the daemon's gate over every house it serves** (Task 19).

- The plan computes it "over the publisher's house". P 12.3 says "the daemon over the houses it serves". Under P 12.3
  rule 2, one unmarked served house makes the daemon read `closed` for every frame.
- Either follow the spec and pass every publisher's `db_path`, or add a ruling that says why per-house is enough.
- Then fix `test_u16_a_publisher_house_added_without_the_id_reads_closed_until_gate_marks_it` to match: under the
  spec, `recall(pub)` is empty too.

**SF3. Review Focus 2 holds the wrong lock** (Task 19, `test_rf2_locked_ledger_reads_closed`).

- With R1's rollback journal, a writer's `BEGIN IMMEDIATE` takes a RESERVED lock. Readers still read the last
  committed state. I checked on this Pi in the scratchpad: with `BEGIN IMMEDIATE` held, a `mode=ro` reader with
  `busy_timeout=50` read the old row. With `BEGIN EXCLUSIVE` held, it got "database is locked".
- So the test as described would fail, or tempt a builder to treat a RESERVED lock as `closed`.
- Hold `BEGIN EXCLUSIVE` in `hold_ledger_write_lock`, the lock a commit or a cache spill takes. Reword Review Focus 2
  to match.

**SF4. Houses made before migration 029** (Tasks 20, 21 and 28).

- Every real house on Andy's machines predates 029.
  - The raise marks houses through plain `sqlite3` and runs no migration (R17).
  - The daemon opens houses read-only and never migrates (`engram/lighthouse_daemon.py:82-113`).
- Task 28 fills `source_instance_id` and `record_id` in the published house. It doesn't say it opens that house with
  `Storage`, so 029's columns may not exist yet. Under `shadow` and `enforce`, the daemon's `placement_changes()`
  needs 029's counter table.
- Say that `migrate` opens the published house with `Storage`, so 029 runs.
- Say that the daemon serves nothing, and warns, from a house that lacks 029's columns or counter.
- Test both on a house built from migrations 001 to 028 only.

**SF5. `permit` can't carry most of P 7.6's acts** (Task 23, U18).

- `permit` takes "one of the seven grant ops", with selector, record, collection and memory arguments.
- `test_u18_each_widening_act_through_the_mcp_tools_is_filed_as_a_proposal` sends "a root grant" through it. P 7.6
  says an agent's tool call for any act in that table files a proposal. That includes a root grant, registering an
  agent or a store, the gate and `migrate`.
- Decide which acts the tool accepts, and give them arguments. Say which proposal kinds `sign` can complete. Or test
  that the other acts are refused, and say why that meets P 7.6.

**SF6. What the `permissions` tool gives an agent that doesn't act for the owner** (Task 23; P 9.2, AS2).

- `keep_world` (Task 25) runs a server as `agent:ph-coordinator`. If `permissions(focus="uses")` returns the owner's
  list, that agent sees refusal layers, such as "m3: needs Jenn's yes". P 9.2 forbids that.
- Say what such an agent gets: its own `agent_view`, or a refusal. Test it with that server.

**SF7. Task 11 uses an act that Task 12 builds** (`test_u5_co_subjects`).

- The test's first assertion expects `NO_ALLOW` at `place:home/jenn`. Subjects come first by id, so that refusal
  needs Andy's home layer to allow first, through R1. Without R1, the refusal is `NO_ALLOW` at `place:home/andy`.
- R1 is an `allow`, and `allow` is Task 12's act. G1 is Task 12's too.
- Say that `e1_ledger_through_andys_side` writes R1 and G1 through `_append`, or move that assertion to Task 12.

**SF8. Sharing an unmigrated row again changes nothing** (Task 23; P 12.3 step 2: "Andy can share it again").

- `sharing.share` returns an existing `(source_instance, source_id, audience)` row unchanged
  (`engram/sharing.py:118-129`). A row that `migrate` left unmatched keeps a null `source_instance_id` when Andy
  shares it again. So it stays refused under `enforce`.
- Say that the existing-row path fills a null `source_instance_id` and `record_id`. Test it.

**SF9. Keep legacy verdicts out of the cache** (Task 21; P 6.3 item 4).

- `eligible_set(..., legacy=())` takes legacy layers. The cache key doesn't say they stay out. Receipts cite legacy
  verdicts (Task 20's shadow test).
- Say that the cached set holds ledger decisions only. The frame's legacy decision and its audience check run on
  every request. Add to the cache test: a policy change between two cached recalls takes effect with no rebuild.

**SF10. U24's fixture and the bulk path** (Tasks 7 and 31).

- **The fixture.** Every one of the 256 records passes the pre-filter. That removes the pre-filter that P 12.2's 2 s
  budget assumes ("With the pre-filter of 6.5"). The result then says little about the spec's case. Pin the fixture:
  which audiences, purposes and objects the records name, and how many match each object.
- **The bulk path.** Task 7 decides each object "by `decide`'s per-object path". `need(U)` is a union (P 6.4). Say
  that `decide_bulk` decides each (memory, action) once across U, keeping the refusal order by object. If not, Task
  31 makes 51.2 million memory decisions instead of at most 100,000.

**SF11. Placeholder tests** (most tasks).

- About forty tests are a name and `...`. Several guard safety rules:
  - U13's shadow equivalence;
  - U12's relink;
  - U17's co-subject added after keeping;
  - the guard's 24-hour and 200-receipt window;
  - `test_off_has_no_guard`;
  - `test_u8_a_subject_sees_only_receipts_naming_them_at_the_time`;
  - `test_u9_refused_copies_never_appear_among_candidates`;
  - `test_u25_pending_reads_as_neither_lane_for_an_allow_and_both_for_a_deny`.
- Give at least these their assertions. The fixture builders behind E1 also need their contents named:
  `e1_ledger_through_andys_side`, `county_ledger`, `keep_world` and `enforce_server`.

**SF12. Split the two largest tasks.**

- Task 5 holds `needs`, subjects, `Req`, `decide` with every code, the brute-force oracle, `random_world` and six
  property tests. Split the oracle, `random_world` and the property tests into a task of their own.
- Task 26 holds about 25 subcommands. Split it into registry commands and record or grant commands.

**SF13. One U16 test can't fail** (Task 18, `test_u16_a_config_that_fails_to_parse_changes_no_mode`).

- The test calls only `effective_gate`, which never reads config. So it passes before any change, against the plan's
  "Expected: FAIL on all four".
- Run it through a reader that loads config: for example the server's `_init` with the broken file, then
  `_permission_gate()`. That test could move to Task 23.

**SF14. Where the receiver's legacy layer comes from** (Task 20).

- P 6.3 item 4 and E1's `Req` hold both the publisher's and the receiver's ConnectionPolicy. Today the daemon loads
  only the publisher's policy (`engram/lighthouse_daemon.py:342`).
- Say how the daemon reads the receiver's policy, for example through `instances/<receiver>/lighthouse-receiver.toml`
  under R19's `engram_home`, so that E1's `cited` holds both.
- Say also whether the `remember` guard's `imprint` decision reads legacy layers (R10).

## Nits

- **Python.** "Python 3.13 (engram's `uv.lock`)": `uv.lock` says `requires-python >=3.12`, and there is no
  `.python-version`. On this Pi the only interpreter that fits is uv's 3.14.8, which another engram worktree's
  `.venv` already uses.
- **Task 6.** Its expected failure `None != 1806451200` is 2027-03-31. `T("2027-01-31")` is 1801353600.
- **Task 16.** Its tests open `Storage` under `.engram/instances/<name>/` with no `mkdir`. `sqlite3` can't make the
  directory, so the first failure is "unable to open database file", not the column assertion.
- **Task 3.** It repeats the `remove_steward` sentence. It calls `county_world` "Task 4's builder", though Task 3
  adds it.
- **Task 9.** `U4_TABLE` says "six actors" but lists eight.
- **Task 15.** `UseList` has `imported_counts`, but `test_yn6_…` reads `counts["imported"]`. Pick one.
- **The shared interface list.** "What the other plans use" leaves out names they use:
  - the trails plan's fixtures use `Ledger.create`, `ledger_path`, `Ledger.close`, `Ledger.perform` and `Act`;
  - the imprints plan uses `State.from_tables`, `World`, `UseRow` and `Uses.open`;
  - both depend on R15's digest encoding.
  List these as stable too.
- **The server fixture.** `engram_server_env` isn't in `conftest.py`. Say that new files import it from
  `tests.test_recall_margins`, as `tests/test_share_tools.py:5` does.
- **`init` and `migrate`.** Say where `init` gets the owner's handle (P 7.6: no argument names who acts). Say what
  `migrate` does when a ledger already exists.
- **`collect`.** It writes a first lane note "at `created_at` with its current lane". The ledger can't read the
  store, so say who passes the lane and `created_at`.
- **Task 1's selector rule.** For `kinds: "*"` it refuses a finite `layers`, `lanes`, `collections` or `memories`.
  That is stricter than P 5.2's "for a road or trail". Mark it as a ruling, and say that `migrate`'s legacy allows use
  `kinds: ["memory"]`.
- **R20.** Say which lane compression gives the new semantic when the evidence's re-lane is refused.
- **The `remember` guard.** It hashes the stripped content (`engram/server.py:1849`). A delivered item with
  surrounding whitespace escapes it. Consider checking the unstripped digest too.
- **Exit codes.** Exit code 2 means both "no terminal or wrong code" (R12) and argparse's usage error.
- **`report shadow`.** Say how it finds "the shares that would have needed a proposal".
- **`uses --place P`.** For a place the owner stewards, it should show that place's view (P 9.3). Task 27 doesn't
  say so.
- **Review Focus 1.** It covers reads only. Say what a recall does under `enforce` when its receipt can't be written.
- **Line citation.** `engram/config.py:316-357` is cited for `load_config`, which starts at `:301`.

## Carried items for this spec

The plan's "Carried items" table matches the consolidation log:

- **YN6:** Task 15 counts rows per (action, purpose) and tests an admission with `route`. Gate G8 holds the wording.
- **XS2, P's side:** `append_imported` accepts a null `returned`, and the list shows it as "not counted" (Tasks 14
  and 15).
- **XM1, P's side:** Task 7 tests two owners, one of them the operator. See SF1.
- **XN3:** Task 31 uses 512-touch trails. See SF10.
- **XN6:** left to P 14 step 2 (Gate G9).
- **The rest of P's items:** BS1, BS2, BS3, BN3, BN4, AN4 and AN5 are each in the task named.
- **Not this spec's:** YS1, YN1 to YN5, YN7, XN2, I's CN7 (second half) and CN8, and T's FS1 and FN1 to FN3. The
  plan lists them so none is lost here.

## Nothing live

- Every test uses `tmp_path`.
- Deploys, `migrate`, `gate` and the merge are gates G1 to G10. No task runs one.
- The room post and `git merge` in "Verification before merge" belong to G1, under station law section 2.
- `superyak-lighthouse` on this Pi runs `peer/`, not engram (I read its unit). So the claim "no Pi service restarts"
  holds.

## Code and system claims I checked

**Engram code, read today:**

- `engram/storage.py`:
  - the migration loop and `_assign_instance_id` at 028 (`:226-235`);
  - `_skip_existing_columns` (`:35-52`);
  - `open_read_only` (`:128-160`);
  - `_commit` under an outer transaction (`:182-187`);
  - `set_episode_lanes` (`:598-610`);
  - `Storage` doesn't create directories (`:93`).
- `engram/compress.py:466`, `:508-510`.
- `engram/server.py`:
  - `ENGRAM_HOME` (`:160`) and the storage open (`:1315`);
  - genome sync (`:1446-1452`);
  - `remember`'s checks (`:1826-1856`);
  - `_published_house_storage` (`:1934-1946`), `share` and `unshare` (`:1949-1998`);
  - `attach_neighbors` with `receiver=_instance_name` (`:2610-2613`).
- `engram/sharing.py:99-204`.
- `engram/lighthouse_daemon.py`:
  - `PublisherStore.open`, read-only (`:82-113`);
  - `_allowed_audiences` (`:156-170`);
  - retrieval (`:204-291`);
  - `PublisherDaemon` and its frames (`:294-453`);
  - `main` (`:521-550`).
- `engram/lighthouse_client.py:286-337`, with the strict keys at `:315`.
- `engram/neighbors.py:24-172`.
- `engram/context_lighthouse.py:28-34`, `:106-210`.
- `engram/config.py:301-357`, `:385-409`.
- `engram/policy_gen.py:13-44`.
- `engram/federation.py:154-209`.
- The receipt schema's namespaced `extensions`.
- `engram/lighthouse_receiver_config.py:13`.
- `peer/superyak_peer/grants.py:95`, `:284`.

**Tests and fixtures:**

- Every existing test file the plan names exists.
- `test_wheel_contains_runtime_modules_and_assets` requires every `engram/*.py` in the wheel.
- `test_lockfile_matches_project_metadata` runs `uv lock --check`.
- `tmp_db` is in `conftest.py`. `engram_server_env` lives in three test files.

**The other plans:** the imprints plan's Task 28 calls `decide_bulk(..., outside=...)`. The trails plan's Task 16
calls `Ledger.create`, `perform(Act("register-store", ...))` and `store_row`. Both match this plan's interfaces.

**On this Pi:**

- `/tmp` and `/var/tmp` are on the NVMe disk, and the Pi has 16 GB.
- It is a Raspberry Pi 5.
- `uv` 0.12.23 and `systemd-run` are present.
- The installed Pythons are 3.11.2 and uv's 3.14.8.
- Node is 18.20.4, with no pnpm.
- The user units are `superyak-door`, `-lighthouse`, `-odo`, `-ship` and `-wormhole`.
- The SQLite lock behaviour of SF3, run in the scratchpad.

## Response

Date: 2026-10-25. By the plan's author, in a later session. I edited only the plan and this section, with targeted
edits. I changed no code, ran no engram tests, and committed, pushed, merged, deployed and posted nothing.

Every must-fix, every should-fix and every nit is applied. I declined none. Where the review offered two fixes, I
say which one I took. Task numbers stay as they were, because the imprints and trails plans cite them. So the two
split tasks are **5A** and **26A**. New rulings are R23 to R28.

I checked these claims again in this tree before fixing them: `_version` and the two checks
(`engram/context_lighthouse.py:33`, `:181`, `:210`; the same on `main`); `transaction()` and `_commit`
(`engram/storage.py:162-187`); compression's re-lane inside `transaction()` (`engram/compress.py:466`, `:510`) and
the new semantic's `lane` (`:563`); `share`'s existing-row return (`engram/sharing.py:118-129`); `load_config` at
`engram/config.py:301`, which raises on bad TOML while the store resolver falls back (`:389-398`); the receiver's
settings path (`engram/neighbors.py:183-184`); `engram_server_env` imported at `tests/test_share_tools.py:4`; and the
two timestamps of the Task 6 nit.

### Must-fix

- **MF1. Applied** (Task 22). I took the first fix. `_version` hashes `_evidence` of the item without its
  `permission` member. `_evidence` still gives the model the one line. The task says why, with the line numbers.
  Three tests:
  - a candidate with a `permission` line survives `prepare_dispatch` under `shadow` and `enforce`, while the re-read
    writes a new receipt;
  - a re-read that is now refused (`content: null`) still drops the candidate;
  - the candidate's version equals `_version` of the item without `permission`.
  The checks sit at `:180-181` and `:208-210` in this tree and on `main`, not `:185-186` and `:204-206`. The finding
  holds either way.
- **MF2. Applied** (Task 17). `Storage.after_outcome(on_commit, on_rollback)` queues both calls on the outermost
  `transaction()`. Outside any transaction it runs `on_commit` at once. `transaction()` runs the queue after its own
  `commit()` or `rollback()`, including a rollback caused by a failed commit. `set_episode_lanes` hands it the
  `"after"` and `"failed"` notes. A callback's `Exception` is logged, since the store's outcome is already final. The
  note left `pending` is settled by the sweep. Three new tests:
  - the settling note waits for the outer commit;
  - a re-lane inside a transaction that then raises leaves `personal`, `pending`, `personal`, and a later work-lane
    allow does not match;
  - a compression commit whose `add_semantic` raises leaves no `work` note.

### Should-fix

- **SF1. Applied** (Tasks 5 and 7). For a place id in `outside`, the callable is the whole verdict of that layer. No
  ledger record there is read or cited, and the layer adds nothing to `until` or the horizon. A new test in Task 5
  shows that a ledger deny in that layer is not read.
- **SF2. Applied, following the spec** (Task 19). The gate is computed at every frame over every served house. The
  renamed test asserts that `recall(pub)` is empty too until `gate` marks the late house. Its builder restores a copy
  of a pre-raise house, since a house *made* after the raise gets the id from 029.
- **SF3. Applied** (Task 19 and Review Focus 2). `hold_ledger_lock(root, kind)`: under `IMMEDIATE` the daemon still
  serves the last commit, and under `EXCLUSIVE` it reads `closed`. Review Focus 2 now says which lock blocks readers.
- **SF4. Applied** (R27; Tasks 16, 20, 21, 27 and 28; gate G3).
  - Under `shadow` and `enforce`, a house without 029's columns or counter serves nothing, gets no cache entry, and
    the daemon warns. Under `off` it serves as today.
  - `migrate` opens the published house with `Storage`, so 029 runs before it fills the columns.
  - `gate` and `migrate` list the other houses that lack 029 before the yes.
  - Task 16 adds the `house_before_029` builder (migrations 001 to 028 only) and a test that 029 upgrades such a
    house. Tasks 20 and 28 test on it.
  - This narrows `shadow` for an unmigrated house. R27 says why: failing closed shows the house in the report.
- **SF5. Applied, by defining the acts** (R26; Tasks 12, 13, 23 and 26A).
  - `permit` takes the seven grant ops, plus ten act kinds through `args`: `grant`, `group`, `register-agent`,
    `put-agent`, `add-steward`, `register-place`, `add-parent`, `register-store`, `remove-subject` and `gate`. Each
    widening act from an agent is filed as a proposal for the owner, with the full `Act` in its body.
  - `sign`, with the yes, completes every kind.
  - `migrate` is not an op. `permit(op="migrate")` returns an error naming the CLI command and writes nothing. A
    proposal can't hold its change, since the change is computed from files at the time of the yes, and a refusal
    makes nothing either.
  - The U18 test now lists every row of P 7.6's table that is one `Act`.
- **SF6. Applied** (R28; Task 23). An agent whose principal isn't `meta.owner` gets its own `agent_view` for
  `focus="uses"`, and an error for the other focuses. The test runs on `keep_world`'s `ph-coordinator` server.
  `keep_world` moves to Task 23 for that reason. P 9.2's subject row is not offered through the tool in step 1. That
  is narrower than the spec allows, and a later step can add it.
- **SF7. Applied, with `_append`** (Tasks 10 and 11).
  - R1 and G1 are written through `_append`, and so are E1's county records in `e1_county_ledger`: Task 11's U15 test
    needed them for the same reason. Task 10 says its projection covers every log kind.
  - `test_u2_one_place_per_agent_and_retiring_a_person` now uses `e1_ledger_through_andys_side`. Its `RETIRED`
    assertion needs Jenn as m3's co-subject, which `county_ledger` doesn't have.
- **SF8. Applied** (Task 23). The existing-row path fills a null `source_instance_id` and `record_id` and never
  overwrites a set value. A test covers both.
- **SF9. Applied** (Task 21).
  - `eligible_set` takes no legacy layer.
  - A new `meet_legacy` meets the cached decision with this frame's legacy verdicts, in step 2's order. A property
    test checks that it equals `decide` with the legacy layers.
  - The new cache test changes the publisher's policy, the receiver's policy and `engram:audiences` between cached
    recalls, each with no rebuild.
- **SF10. Applied** (R23; Tasks 7 and 31).
  - The record mix is pinned. In each layer, 32 of the 256 records pass the pre-filter, 8 each of four kinds. Every
    memory meets 43 layers, and no decision stops early.
  - A default-suite test checks those counts on a small copy.
  - `decide_bulk` decides each (memory, action) once through a memo and keeps the refusal order by object. A test
    counts the calls.
- **SF11. Applied.**
  - The eight tests named have assertions. So do `test_u10_the_context_runtime_evidence_carries_it`,
    `test_029_with_no_ledger_writes_no_mark`, the two Task 17 server tests, `test_u16_closed_refuses_share_and_permit`,
    `test_u12_the_sweep_settles_pending_lane_notes` and `test_shadow_only_reports_what_it_would_remove`.
  - These fixture contents are now named:
    - Task 11: `county_ledger`, `e1_ledger_through_andys_side`, `e1_county_ledger`, `copies_ledger`;
    - Task 23: `enforce_server`, `WIDENING_THROUGH_PERMIT`;
    - Task 25: `keep_world`, `keep_world_with_imprint_allowed`;
    - Task 17: `shadow_server`, `closed_server`.
  - About 25 placeholders remain. None is one this review named. Each has a name that says what it checks.
- **SF12. Applied.** Task 5 keeps `decide` and its hand-written cases. Task 5A holds the oracle, `random_world` and
  the six property tests, plus a check that the oracle agrees with Task 5's cases and one that `random_world` reaches
  every feature. Task 26 holds the yes, `init` and the registry commands. Task 26A holds the record, grant and
  proposal commands.
- **SF13. Applied, moved to Task 23.** `load_config` has no fallback: it raises on bad TOML. So the test asserts
  three things: the store resolver warns and falls back, as today; the server's `_init` raises, as today; and
  `_permission_gate()` still reads `enforce`. Task 18 now expects three failures, not four.
- **SF14. Applied** (Task 20 and R10).
  - The daemon reads the receiver's policy at every frame through
    `instances/<receiver>/lighthouse-receiver.toml` under R19's `engram_home`, as the receiver itself does. It
    decides the same request the receiver makes. A missing or bad file refuses (`LEGACY_DENY`). A new test checks
    that E1's `cited` holds both legacy layers.
  - R10 now says the guard's `imprint` decision reads ledger layers only. Today's ConnectionPolicy files have no
    `imprint` rule, so with them every verbatim keep would be refused and P25 never reached. **For Andy or the next
    reviewer:** this departs from "legacy layers while they exist" (P 6.3 item 4) for the guard alone. It is still
    stricter than today, which has no guard.

### Nits

All applied:

- Python 3.12 or later, with uv's 3.14.8 on this Pi.
- Task 6's `1801353600`.
- `house_dir` in Task 16.
- Task 3's duplicate sentence and "Task 4's builder".
- "eight actors".
- `UseList(counts, rows)` with `counts["imported"]`. I also unified Task 15's `note` and `notes` into `notes`.
- The added stable names, including R15's digest encoding.
- `engram_server_env` from `tests.test_recall_margins`.
- `init` and `migrate` take the owner's handle from the Unix login (R24). `migrate` refuses when a ledger exists.
- `collect` gets `lanes` from its caller.
- R25 marks the stricter `kinds: "*"` rule. `migrate`'s allows use `kinds: ["memory"]`.
- R20's new semantic keeps the old lane.
- The guard compares the raw and the stripped digests, with a test.
- Exit code 3 for no terminal or a wrong code.
- `report shadow` finds the shares through a new pure `share_cover` (Task 23), with a test.
- `uses --place` shows the place view for a place the owner stewards.
- Review Focus 1 covers recall.
- `config.py:301`.

### Found while applying

- `register-place` gains a `stewards` argument. Without it no one could steward a new root place, since only a
  steward may add one (P 4.4). The fixtures need it.
- The guard's window is half-open, `now - 24 h < at <= now`, in line with every other interval in the plan.
