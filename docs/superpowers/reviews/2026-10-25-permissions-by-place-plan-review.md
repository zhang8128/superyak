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

## Re-check

Date: 2026-10-26. Reviewer: a fresh agent on the Pi (`smart`), acting in Andy's place. I took no part in writing,
reviewing or revising the plan.

- I read the plan whole (3,531 lines, at `85595ed`, unchanged since). From the spec I read sections 4.4, 5.2 to 5.4,
  6, 7, 9 to 13 and 17. I also read the review and response above, the parts of the imprints and trails plans that
  use this plan's names, the vision's principles and the interface table's rows 6, 8, 21 and 29.
- I read the code behind every claim below.
- I edited no file but this one. I changed no code and ran no engram tests. I committed, pushed, merged, deployed and
  posted nothing.

### Verdict

**Approve with changes.** It is not approved as written, because three must-fix items remain (RM1 to RM3).

- The review's MF1 and MF2 are resolved.
- Every should-fix and nit of the review is applied, except SF11, which is met only in part.
- RM1 is new. Nobody had checked it, though the trails plan pointed at it. RM3 is new too.
- Once RM1 to RM3 are fixed, nothing I found blocks the build.

### The review's must-fix items

**MF1. Resolved** (Task 22). I checked it against `engram/context_lighthouse.py`:

- `_evidence` (`:28-30`) copies a fixed set of keys, and `_version` (`:33-34`) hashes it.
- `_read_entries` reads the item again through `validate_read` (`:170`). It keeps the item only when the two versions
  agree (`:181`). `prepare_dispatch` drops a candidate whose version changed (`:209-210`).
- With `permission` left out of `_version`, a search item (holding the line) and a re-read item (holding the
  object) hash the same, and the model still sees the line.
- A refused re-read is still dropped. `validate_read` skips an item whose content is null
  (`engram/lighthouse_client.py:324-325`), so its key is missing from `verified`.
- The three new tests assert all of this.

**MF2. Resolved** (Task 17). I checked it against the code:

- `Storage.transaction()` (`engram/storage.py:162-180`) commits or rolls back only at the outermost level.
  `_commit` (`:182-187`) does nothing inside a transaction.
- Compression's re-lane (`engram/compress.py:510`) runs inside `transaction()` (`:466`), with `add_semantic`
  (`:555-564`) after it in the same block.
- `after_outcome` queues the two calls on the outermost block, so the `"after"` note follows the store's commit and
  the `"failed"` note follows its rollback.
- The three new tests cover the outer commit, a raise inside the block, and a compression commit whose
  `add_semantic` fails. Two edge cases are left as nits below.

### Must-fix

**RM1. Adding `permit` and `permissions` breaks an existing test that the plan may not edit** (Tasks 23 and 32;
Global Constraints; Verification step 2).

- **The test.** `tests/test_packaging.py:225`, in `test_installed_wheel_starts_outside_checkout`, asserts
  `len(server.mcp._tool_manager.list_tools()) == 43`. `server.py` has 43 `@_server_tool()` today. Task 23 decorates
  two more, so the count becomes 45 and the test fails.
- **The conflict.** Three of the plan's own rules can't all hold:
  - Global Constraints says "No task edits an existing test file".
  - Task 32 step 3 expects `tests/test_packaging.py` to pass.
  - Verification step 2 requires `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/` to print
    nothing.
- **Who saw it.** The trails plan names it ("that plan should check it", in its "What this plan uses from the other
  plans"). This plan doesn't mention it.
- **Fix.** Add a ruling that allows exactly this one-line change, `43` to `45`, in Task 23. Put the file in Task 23's
  `git add`, and run that test in its step 4. Name it as the one exception in Global Constraints and in Verification
  step 2's check.

**RM2. Eleven tests that P 17 names are still placeholders, and two more of its clauses are only comments** (SF11).

The response kept "about 25" placeholders and said none of them was one the review named. I count 26. These eleven
are tests that the spec's section 17 names, so each one needs real assertions in the plan:

| P 17 | Task | Test |
|---|---|---|
| U8: "the hash chains verify and one changed byte fails". This is the receipts chain; Task 10's test covers only the log. | 14 | `test_u8_the_chain_verifies_and_one_changed_byte_fails` |
| U22: "an answer that walks 5 roads is 5 `route` uses with 5 receipts" | 14 | `test_u22_five_roads_are_five_route_uses_with_five_receipts` |
| U8: "pseudonyms are stable in a place and differ across places" | 15 | `test_u8_pseudonyms_are_stable_in_a_place_and_differ_across_places` |
| U8: "agents in a place see no filtered counts" | 15 | `test_u8_agents_in_a_place_see_no_filtered_counts` |
| U11: "`permit` inside a grant's envelope writes a grant-backed record, and outside it files a proposal" | 23 | `test_u11_permit_inside_the_envelope_is_grant_backed_and_outside_is_a_proposal` |
| U11: "`unshare` always works" | 23 | `test_u11_unshare_always_works` |
| U9: "the 20,001st placement is refused" | 23 | `test_u9_the_20001st_placement_is_refused` |
| U12: "the copy goes with its last share row" | 24 | `test_u12_the_copy_goes_with_its_last_share_row` |
| U13: "a fixture with more than 256 shares migrates" | 28 | `test_u13_more_than_256_shares_migrate` |
| U13: "each source store's bytes are unchanged while `source_instance_id` is filled" | 28 | `test_u13_each_source_store_is_byte_identical_while_source_instance_id_is_filled` |
| U13: "every house, the published house among them, and each source store are registered with Andy's home as their place, and use 1's holding place resolves" | 28 | `test_u13_every_house_and_source_store_is_registered_at_andys_home_and_use_1s_holding_place_resolves` |

Two more clauses of P 17 are held only in comments:

- U6, "one moved from work to personal stops being covered", is a comment at the end of `test_u6_lanes_after_a_move`
  (Task 4).
- U2, "depth and count limits", is a comment in `test_u2_name_rule_cycles_roots_and_bounds` (Task 2), covering the
  17th ancestor and the 1,025th place.

**Fix.** Write assertions for these thirteen, at the level of the tests around them: the call, the expected value,
and what the fixture holds where it isn't one the plan already names.

**RM3. A U17 test expects the code the spec gives only to a registered person** (Task 25,
`test_u17_a_co_subject_added_to_the_source_afterwards_refuses_the_kept_copys_next_use`).

- **The test.** It asserts `Refusal("NO_ALLOW", "place:home/amy", "recall")` after `add_subject(M1, "person:amy")`.
- **The fixtures.** No fixture registers `person:amy`. `county_ledger` registers `county-steward`, `ph-steward`,
  `pr-steward`, `sw-steward`, `sw2` and `jenn`, and `keep_world` adds no person.
- **The rule.** P 7.4: "A co-subject who can't say yes on this ledger refuses: `NO_ALLOW` if they are registered with
  an empty home layer, `NO_LAYER` if not." Task 5 says the same: "an unregistered subject is `missing` and refuses
  with `NO_LAYER`".
- **The result.** A correct build fails this test. A builder who makes it pass by changing `decide` breaks P 7.4, and
  no other test would catch that. U28's `NO_LAYER` case is an object with no subject, and the oracle returns only
  `allowed`.
- **Fix.**
  - Register `person:amy`, as Andy, with an empty home. Do it in `keep_world`, or in `county_ledger`, so that Task 11's
    U5 test uses the same Amy.
  - Add a U28 case for an unregistered co-subject (`NO_LAYER`) beside the registered one (`NO_ALLOW`).

### R10: confirmed

R10 makes the `remember` guard decide `imprint` from ledger layers only, leaving out the legacy layers of P 6.3
item 4. Acting in Andy's place, I confirm it, for four reasons.

1. **Today's legacy files can't give this yes.**
   - `policy_gen.py:75` writes publisher rules with `actions: ["recall", "read"]`.
   - E1's hand-written files allow `recall` and `read` for the publisher, and `recall`, `read` and
     `inject_context` for the receiver (P 13).
   - ConnectionPolicy denies by default. So with legacy layers in the guard's `Req`, every verbatim keep of a
     delivered item would be refused, whatever the ledger says.
   - U17's "when allowed, the kept memory carries its source's subjects" (P25) would then never be reached.
2. **The part the legacy files can express was already decided.**
   - `need(imprint)` is `recall`, `read` and `imprint` on the item.
   - The guard acts only on an allowed `inject_context` delivery from the last 24 hours. Under `enforce`, both legacy
     layers allowed that delivery, since both paths must allow (P 12.2).
   - So the guard leaves out only the legacy files' say on `imprint` itself, which no legacy file gives today.
3. **Principle 1 still holds.**
   - Every subject's home layer, the requester's places, the holding place and the agent's restriction layer must
     still allow `imprint`. Each person the memory is about still says yes, in the ledger.
   - The ConnectionPolicy files are Andy's own. So R10 removes a second yes from the same person, not anyone's only
     yes.
4. **It is stricter than today**, when there is no guard at all. Under `closed` it still fails closed (R11).

R10 is confirmed on two conditions, which RS6 below lists:

- **Its reason says too much.** The ConnectionPolicy schema accepts any action string
  (`engram/schemas/lighthouse/connection-policy.schema.json`, `actions`), so a hand-written legacy `imprint` rule is
  possible. R10 should say "today's generated files and E1's", and should say that the guard ignores a legacy
  `imprint` rule, allow or deny.
- **The spec should record it.** This plan edits no spec, so add a gate beside G8. In its next revision, the spec
  says in 6.3 item 4 and section 10 that the guard's `imprint` decision reads ledger layers only, and why.

### Should-fix

**RS1. Say what the publisher's legacy layer answers for each action** (Task 20).

- **The gap.** The plan decides a read frame per item as `inject_context`. It says "legacy layers are the publisher's
  and receiver's policy decisions of this frame", but not what the publisher's `LegacyLayer` answers for
  `inject_context`.
- **Today.** The daemon decides the publisher policy once per frame, for `recall`
  (`engram/lighthouse_daemon.py:362`) or for `read` (`:402`). Both `policy_gen.py:75` and E1's publisher policy
  allow only `recall` and `read`.
- **The risk.** If the builder asks the publisher policy about each action of `need`, `inject_context` is refused.
  - Under `enforce`, every delivery is refused, E1's use 1 among them.
  - Under `shadow`, every receipt reads as refused by the legacy path, so `report shadow` lists no disagreement.
- **Fix.** The publisher's layer answers every action with this frame's one decision (P 12.2: "made once per
  frame"). The receiver's layer answers each action with its own `PolicyRequest`, as `engram/neighbors.py:53-60`
  does.

**RS2. A gate proposal takes its houses from the agent** (R26; Tasks 12, 13 and 23).

- **The gap.** The `gate` act's arguments are `mode`, `published_house` and `houses`.
  - Through `permit(op="gate", args=...)`, the agent writes them, and `sign` runs the `Act` from the proposal's body.
  - So the agent names the path the raise checks for the published house, and the houses to mark, as they stood
    when it asked.
- **The plan's own reason.** R26 refuses `migrate` as a proposal because "the change is computed from files at the
  time of the yes". Marking houses is that kind of change.
- **Fix.**
  - Drop `published_house` and `houses` from the act's arguments. `perform` computes
    `ENGRAM_HOME/.engram/instances/lighthouse/graph.db` and `houses(engram_home)` when it applies the act.
  - `sign` of a gate proposal prints R27's list of houses that lack 029 before the yes, as Task 27's `gate` does.

**RS3. Key the eligible-set cache by house too** (Task 21).

- **The gap.** One daemon serves several publishers. A recall on house A and a recall on house B have the same key,
  (agent, place, purpose, action). But an entry's validity reads "the house's `placement_changes()`".
- **The result.** An entry built for A can be checked against B's counter.
  - When the two counts differ, the cache rebuilds every time.
  - When they agree, it serves A's set for B. That set holds none of B's memory ids, so B returns nothing.
- R27's "a house without 029's counter never gets an entry" already treats entries as belonging to one house.
- **Fix.** Key by (house, agent, place, purpose, action). Add a case with two publishers and one agent to
  `test_u9_the_cache_recomputes_on_a_new_seq_a_new_change_count_and_at_the_horizon`.

**RS4. Migration 029 should mark only a house it creates** (Task 16; P 12.3).

- **The gap.** `_mark_house_for_ledger()` runs whenever 029 runs.
  - Take a house restored from a backup made before 029 and before the raise. It carries no id, so P 12.3 rule 2
    makes it read closed until `gate` marks it again, with the yes.
  - Under Task 16, the first engram server that opens it runs 029 and marks it, with no yes.
- **The rule.** P 12.3 says "A house created while a ledger exists gets the id when it is created", "as migration 028
  gives a new store its `instance_id`". 028's step takes `created_now` (`engram/storage.py:224`, `:230`).
- **Fix.**
  - Pass `created_now` to `_mark_house_for_ledger`, and mark the house only then.
  - The raise already marks every house that exists when it runs (R17), so G3's order still works.
  - Add a test: a pre-029 house restored after the raise still reads closed after an engram server opens it.

**RS5. A configured publisher with no store** (Task 19; SF2's fix).

- **The gap.** The gate is now computed over every served house, `[p.db_path for p in self.publishers.values()]`.
  - Today, a configured publisher whose `graph.db` doesn't exist yet gets `PUBLISHER_UNAVAILABLE`
    (`engram/lighthouse_daemon.py:332-337`).
  - If `effective_gate` reads a missing path as a house with no id, P 12.3 rule 2 closes every frame, for every
    publisher.
- **Fix.** Leave a served path with no file out of the gate, since it serves nothing. Test it.

**RS6. R10's two conditions.** Correct the reason, and add the spec gate (see "R10: confirmed").

**RS7. Four other placeholders guard a spec rule.** P 17 doesn't name them, but each is the only test of its rule.
Give them assertions too:

- `test_more_than_20000_placements_serve_nothing_under_enforce` (P 12.2, "Bounds");
- `test_genome_sync_records_kept_copy_subjects_under_shadow` (P 12.1's genome sync row; P25);
- `test_an_agents_try_on_a_consent_deny_is_a_proposal` (P27; E1 use 9);
- `test_shortening_and_narrowing_write_a_replacement_inside_the_original` (P 7.3; P 5.3 rule 4; E1 use 8).

### Nits

- **MF2's edges.**
  - `transaction()` rolls back only `if outermost and self.conn.in_transaction` (`engram/storage.py:176-177`), and
    SQLite rolls back on its own after some errors. Run `on_rollback` on every exceptional exit from the outermost
    block, whether or not `rollback()` ran. A call left unrun leaves the note `pending`, which is safe, so this is
    only a nit.
  - At depth 0, a `COMMIT` that fails with `SQLITE_BUSY` leaves the transaction open. A later `_commit` on that
    connection would then commit the new lane after a settled note that names the old one. Roll back before writing
    `"failed"`.
- **Task 22's wording.** "A re-read whose decision now refuses has `content: null`, so its version differs." In fact
  it is dropped because `validate_read` skips it (`engram/lighthouse_client.py:324-325`), so its key is missing from
  `verified` (`engram/context_lighthouse.py:209-210`). The outcome is the same.
- **R1 and a hot journal.** With a rollback journal, a writer that dies mid-commit leaves a hot journal. A `mode=ro`
  reader can't roll it back (`SQLITE_READONLY_ROLLBACK`), so every reader reads `closed` until a writer opens the
  file. That fails closed. Say so in the cause text, and name a command that clears it: any writing open, such as
  `engram-permissions sweep`.
- **R24.** On a machine where Andy's login isn't `andy`, the owner becomes `person:<login>`, and he can't choose
  otherwise. Say which machine holds the ledger (G3). Write the legacy collections as
  `collection:<owner handle>/legacy-…`, since Global Constraints and Task 28 write `andy`.
- **`effective_gate`'s busy timeout.** `LEDGER_BUSY_MS` is a daemon constant (Task 19). But `effective_gate` opens the
  ledger through `Ledger.open_read_only`, which R1 gives 5,000 ms. Give `effective_gate` a `busy_ms` argument, or
  `test_rf2_locked_ledger_reads_closed` waits 5 s for each locked frame.
- **`keep_world`'s store.**
  - `_init_unlocked` uses `instances/<name>/graph.db` only when that file exists (`engram/server.py:1309`), and
    `house_dir` makes only the directory.
  - Without the file, the server falls back to the default store. Then `attach_neighbors` refuses with
    `RECEIVER_STORE_MISMATCH` (`engram/neighbors.py:188-189`).
  - Say that `keep_world` opens a `Storage` there before `_init`.
- **`World`'s default `kinds`.** Under R25, every allow that names a collection, a lane, a layer or memories lists
  `kinds: ["memory"]`. But Task 4's fixtures leave `kinds` out. Say that `World` defaults it to `["memory"]`. `World`
  checks nothing, so otherwise the oracle and `decide` would read selectors that the write rules refuse.
- **`HAND_WRITTEN_CASES`** (Task 5A). Task 5's builders return `(s, u, legacy)`, `(s, u)` or `(s, at_home, at_clinic)`.
  Say how the agreement test unpacks each shape.
- **R11 under `enforce`.** Say what the guard does when `permission-uses.db` exists but can't be read under `enforce`,
  not only under `closed`.
- **"What the other plans use."** The imprints plan's Task 45 adds `copies=` to `Uses.owner_list` and changes the
  `uses` command. List that, since the list is what "kept stable" means.

### Rulings

Each ruling where the plan departs from the spec or adds to it, confirmed or vetoed. I vetoed none.

- **R1** (rollback journal): confirmed. A crash mid-commit fails closed (nit above).
- **R2** (`State.from_tables` as F1's form): confirmed. The imprints plan uses it.
- **R3** (one `perform`): confirmed.
- **R4** (display names in `register-place` bodies): confirmed. The log is the source of truth (P 5.6).
- **R5** (gluing reports computed, never stored): confirmed.
- **R6** (a joint place as a proposal): confirmed. P 4.4 says it "waits as a proposal".
- **R7** (legacy and outside layers as callables, outside `until` and the horizon): confirmed. P 6.5 steps 6 and 7
  cover ledger layers only.
- **R8** (`record` or `records`): confirmed. F1's fixtures must use the same keys.
- **R9** (under `shadow`, the annotation only when both paths allow): confirmed. Only an allowed item has one (P 11).
- **R10**: confirmed, with RS6.
- **R11** (the guard under `closed`): confirmed, with the nit for `enforce`.
- **R12** (the code's alphabet; exit code 3): confirmed.
- **R13** (`agent:<instance>` or `agent:default`): confirmed. It matches how `share` names its source
  (`engram/server.py:1976`).
- **R14** (an imported row is one whose `ledger_id` differs): confirmed.
- **R15** (the encoding of `returned`): confirmed. Both other plans depend on it.
- **R16** (salts from `os.urandom`): confirmed.
- **R17** (the raise marks houses through plain `sqlite3`): confirmed. Houses use WAL (`engram/storage.py:122`),
  which plain `sqlite3` handles.
- **R18** (the sweep lives in `sharing.py`): confirmed.
- **R19** (`engram_home` on the daemon): confirmed.
- **R20** (compression keeps the old lane): confirmed. P 5.3 refuses the re-lane, not the whole compression.
- **R21** and **R22** (U24 runs only on the Pi; `group`): confirmed.
- **R23** (U24's record mix): confirmed. Its arithmetic holds: 8 + 16 + 16 + 2 + 1 = 43 layers, 41 of them ledger
  layers; 4 × 56 = 224 and 4 × 8 = 32.
- **R24** (the owner from the login): confirmed, with the nit above.
- **R25** (`kinds: "*"` refuses memory-only dimensions): confirmed. A `"*"` covers roads and trails, so P 5.2's "for a
  road or trail" applies to it. I read this as the spec's rule, not a stricter one.
- **R26** (`permit` carries every row of P 7.6 that is one `Act`): confirmed, with RS2.
- **R27** (a house without 029 serves nothing under `shadow` and `enforce`): confirmed. It narrows `shadow` for such a
  house, and G3 has each one opened before `gate shadow`.
- **R28** (what the `permissions` tool gives other agents): confirmed. It is narrower than P 9.2 allows.
- **Departures with no ruling.**
  - Task 16 marks any house that runs 029, where the spec marks only new ones (RS4).
  - Task 20 leaves the publisher's legacy verdict per action unstated (RS1).

### Names and task numbers across the three plans

- **The imprints plan** cites this plan's Tasks 1 (`parse_copy_ref`), 2 (`World`), 7 (`decide_bulk`, `BulkUse`),
  10 (`Ledger.open_read_only`), 11 (`store_row`, `cosubjects`), 14 (`Uses.open`, `UseRow`, `append_imported`),
  15 (`owner_list`), 16 (migration 029), 17 (`latest_lane_note`), 27 (`uses`) and R2 (`State.from_tables`).
  - Each is in the task named, with the same signature.
  - Its Task 28 passes `outside={"place:home/andy": ceiling}` to `decide_bulk`. SF1's interface now defines that as
    the layer's whole verdict, which is what XM1 needs.
- **The trails plan** cites Tasks 9 (`Act`), 10 (`ledger_path`, `Ledger.create`, `open_read_only`, `close`), 11
  (`perform`; `register-store` with `instance_id`, `name`, `owner`, `place` and `imprint_of`; `store_row`) and 23
  (the two tools, RM1). All of them match.
- **Tasks 5A and 26A** are new numbers that neither plan cites, so every existing reference still holds.
- **The interface table.** Rows 6, 8, 21 and 29 agree with the plan's `outside` layer, bulk uses, imported receipts
  and Pi budget.

### Code and system claims I checked

Read today, in this tree:

- `engram/context_lighthouse.py:24-34`, `:74-82`, `:106-130`, `:150-212`; `engram/lighthouse_client.py:286-332`;
  `engram/context_compile.py:37-47`; `engram/context_cli.py:67-69`, `:89-92`.
- `engram/storage.py:30-52`, `:91-98`, `:122`, `:162-187`, `:209-235`, `:598-610`.
- `engram/compress.py:439-470`, `:500-515`, `:555-565`.
- `engram/server.py`:
  - `ENGRAM_HOME`, `PROJECT_ROOT`, `_compressor` and `_initialized` (`:160-174`);
  - `_init_unlocked` (`:1293-1316`) and the genome sync call (`:1443-1452`);
  - `remember` (`:1826-1856`, `:1915`);
  - `_published_house_storage`, `share` and `unshare` (`:1934-2000`);
  - the 43 `@_server_tool()` decorators.
- `engram/sharing.py:19`, `:28-65`, `:99-173`.
- `engram/lighthouse_daemon.py:156-240`, `:294-453`.
- `engram/neighbors.py:45-65`, `:78-140`, `:175-200`.
- `engram/config.py:301-332`, `:373-409`; `engram/policy_gen.py:57-105`; `engram/lighthouse_policy.py:17-67`; the
  ConnectionPolicy schema's `actions`.
- `engram/federation.py:155`.
- Tests:
  - `tests/test_recall_margins.py:45-85` (`engram_server_env` sets `PROJECT_ROOT` to `tmp_path`, so the SF13 test's
    `_init()` reads the broken file);
  - `tests/test_share_tools.py:4`;
  - `tests/test_packaging.py:179-245`;
  - every existing test file that the plan's run commands name exists.
- Facts: `T("2027-01-31")` is 1801353600. uv's 3.14.8 is installed. `engram/pyproject.toml` says
  `requires-python = ">=3.12"`.

## Re-check response

Date: 2026-10-26. By an agent on the Pi (`smart`) revising the plan; I took no part in the re-check. I edited only the
plan and this section, with targeted edits, and checked afterwards that all 43 of the plan's `## ` and `### Task`
headings are still there. I changed no code, ran no engram tests, and committed, pushed, merged, deployed and posted
nothing.

Every must-fix and should-fix is applied, and so is every nit. I declined none, and there were no vetoes to undo. Task
numbers are unchanged. The new rulings are R29 to R33.

I checked these claims again in this tree before fixing them:

- `tests/test_packaging.py:225` asserts `== 43`, and `server.py` has 43 `@_server_tool()`. No other test counts the
  server's tools (`tests/test_session_cli.py:58` lists `session_cli`'s own three).
- `created_now` at `engram/storage.py:224` and `:230`.
- The publisher check at `engram/lighthouse_daemon.py:331-337`, and the one publisher decision per frame at `:362`
  and `:402`.
- The receiver's per-action requests at `engram/neighbors.py:53-60`, asked for `recall`, `read` and `inject_context`
  at `:120` and `:138`. `policy_gen.py:75`'s `["recall", "read"]`.
- The ConnectionPolicy schema's `actions`, any non-empty string.
- `sharing.unshare` returns `True`, and the tool returns `{"removed": ...}`. `sync_genome`'s signature at
  `engram/federation.py:155`. `Storage.transaction()` at `engram/storage.py:162-180`.

### Must-fix

- **RM1. Applied, as the re-check asked** (R29; Tasks 23 and 32; Global Constraints; File Structure; Verification
  step 2).
  - R29 allows exactly one line: `tests/test_packaging.py:225` goes from `== 43` to `== 45`.
  - Global Constraints names it as the one exception, and File Structure lists the file.
  - Task 23 makes the change in step 3, puts the file in its `git add`, and runs
    `test_installed_wheel_starts_outside_checkout` in step 4, with a `git diff -U0` check that only that line moved.
  - Verification step 2 now expects `--diff-filter=MDR` on `engram/tests/` to print exactly that file, and checks
    that its diff is the one line.
  - "What the other plans use" says both later plans start from 45.
- **RM2. Applied.** All thirteen now have assertions, with their fixtures named.
  - Task 2, U2's depth and count limits:
    - 16 ancestors allowed and 17 refused, at registration and through a parent edge that would push a place below
      past 16;
    - the 1,024th place allowed and the 1,025th refused.
  - Task 4, U6: a memory in `work` is covered by the work-lane allow, and after its move to `personal` it is not.
  - Task 14:
    - the receipts chain: ten rows verify, and one flipped byte in seq 4's `cited` gives 4;
    - five roads give five `route` receipts, each with its road as `object` and its named memories in `returned`.
      R15 now states this encoding for an answer use on one road or trail, which P 9.1 asked for and R15 lacked.
  - Task 15:
    - pseudonyms: stable across calls and views, different for another place or person, and 16 hex;
    - no filtered counts: the stewards' views count 1 and 3, and no agent view holds a filtered count. Parks-planner's
      view is empty.
    - R33 fixes which salt a place view uses, which "differ across places" needed.
    - `e1_receipts`'s contents are now named.
  - Task 23:
    - `permit` inside a grant's envelope is `done`, backed by `grant:<id>`; outside it is a proposal for Andy;
    - `unshare` works after the covering allow is revoked, with no record or proposal, and works under `closed`;
    - the 20,001st placement is refused in every mode. Re-sharing an existing row is not a new placement, and after an
      `unshare` a new share fits again.
  - Task 24: the copy and its vector stay while a second share row holds it, and go with the last row.
  - Task 28:
    - 300 `commons` shares become 300 person-backed memberships under one allow, and every row is linked;
    - the source stores' bytes and directory listings are unchanged, while every row gets its source's
      `instance_id`;
    - every house and source store is registered as Andy's, at `place:home/andy`. A use through h =
      `store:<house id>` has the holding layer and is allowed.
- **RM3. Applied** (Tasks 5, 11 and 25). I took the second place the re-check offered:
  - `county_ledger` registers `person:amy` with an empty home. So `keep_world`, which builds on it, and Task 11's U5
    test use the same Amy.
  - Task 25's assertion stays `NO_ALLOW` at `place:home/amy`, now with a comment citing P 7.4. `KEPT_USE`'s allows
    are named as Andy's and ph-steward's homes, with Amy's left empty.
  - Task 5 gains `test_u28_a_co_subject_is_no_allow_when_registered_with_an_empty_home_and_no_layer_when_not`, on a
    pure `co_subject_world`. It expects `NO_ALLOW` and `NO_LAYER`, both at `place:home/amy`, `recall`, since P 6.5
    step 8 names the missing layer. Task 5 now expects 8 passed, and Task 5A expects 8 + 8.

### Should-fix

- **RS1. Applied** (R30; Task 20).
  - The publisher's `LegacyLayer` answers every action of `need` with this frame's one decision.
  - The receiver's layer decides each action with its own `PolicyRequest`, as `neighbors.py` does.
  - New test `test_rs1_the_publishers_layer_answers_each_action_with_the_frames_one_decision`:
    - E1's use 1 is delivered under `enforce`;
    - the publisher's `cited` allows all three actions;
    - a receiver policy without `inject_context` refuses with `LEGACY_DENY` at `receiver`, `inject_context`.
- **RS2. Applied** (R26; Tasks 13, 23, 26A and 27).
  - The `gate` act takes `mode` only, and any other argument is refused. `perform` computes the published house and
    `houses(root)` when it applies the act, from the ledger's own root.
  - A new `Ledger.gate_plan()` gives what the act would use now. The CLI's `gate` and its `sign` of a gate proposal
    both print it, with R27's list of houses lacking 029, before the yes.
  - Tests:
    - Task 13: a proposal's body holds `{"mode": "shadow"}` alone, and a house made after the agent asked is marked
      at the yes. Task 13 now expects 8 passed.
    - Task 26A: `sign` prints the houses and an old house lacking 029 before `code:`.
  - Task 23's `enforce_server` and `WIDENING_THROUGH_PERMIT` now pass `{"mode": ...}` alone.
- **RS3. Applied** (R31; Task 21).
  - The key is (house, agent, place, purpose, action), with 64 entries over all houses.
  - The cache test gains two publishers and one agent: one rebuild each, no cross-talk, and a change on B rebuilds
    only B.
- **RS4. Applied** (Task 16).
  - `_mark_house_for_ledger(created_now)` returns at once for a house 029 upgrades. The raise still marks every house
    that exists (R17), so G3's order holds.
  - New test: a pre-029 house restored after the raise has no mark once `Storage` opens it, reads `closed`, and reads
    `shadow` after `gate` runs again.
- **RS5. Applied** (R32; Tasks 13 and 19).
  - `effective_gate` leaves out a served path that is not a file. The daemon computes the gate after today's
    publisher check, so the frame's own house is always in it.
  - Tests:
    - Task 13: an absent path changes nothing.
    - Task 19: a configured publisher with no store leaves `enforce` serving, and itself gets
      `PUBLISHER_UNAVAILABLE`. Once its house is made, 029 marks it.
- **RS6. Applied.**
  - (a) R10 now says "today's generated files (`policy_gen.py:75`) and E1's", cites the schema, and says the guard
    ignores a legacy `imprint` rule, allow or deny.
  - (b) Gate G11 has the spec's next revision record the departure in P 6.3 item 4 and section 10.
- **RS7. Applied.** All four have assertions.
  - The 20,000-placement bound (Task 20): over the bound serves nothing and warns under `enforce`; at the bound it
    serves; over it under `shadow`, the legacy path serves. `raised_daemon(..., placements=n)` is named.
  - Genome sync (Task 25):
    - the `copies` row, the subjects carried with `added_by` `copy:<source>`, a second sync adding nothing, and no
      ledger file without a ledger;
    - `genome_world` is named.
  - The consent deny (Task 12): an agent's `revoke`, `shorten` and `narrow` of D1 are proposals for Andy that leave
    D1 refusing. Its own restriction deny it writes and revokes with no one.
  - Shortening and narrowing (Task 12):
    - R1′ has `replaces` R1, the same anchor, a person backing and G1 as `under_grant`;
    - R1″ narrows R1′'s actions;
    - a lengthening shorten and a widening narrow are refused and write nothing.

### Nits

All applied:

- **MF2's edges** (Task 17). `on_rollback` runs on every exceptional exit from the outermost block, whether or not
  `rollback()` ran. At depth 0, `set_episode_lanes` rolls back an open transaction before writing `"failed"`.
- **Task 22's wording** now says that `validate_read` skips the item and `prepare_dispatch` drops it, with the lines.
- **R1's hot journal.** It fails closed, and the cause names `engram-permissions sweep`. Task 13 has the cause text.
- **R24.** It says what happens on a login other than `andy`. G3 names the machine by what it holds, the published
  house the daemon serves, and has Andy check the words of the yes. I did not guess which of his machines that is.
  The legacy collections are `collection:<owner handle>/legacy-…`, in Global Constraints and Task 28.
- **`busy_ms`.** `effective_gate` takes `busy_ms` (default 5,000), and the daemon passes `LEDGER_BUSY_MS`.
- **`keep_world`'s store.** It opens a `Storage` there before `_init`, and the plan gives the reason with the lines.
- **`World`'s `kinds`.** `allow` and `deny` default it to `["memory"]`.
- **`HAND_WRITTEN_CASES`.** Each entry yields (state, use, legacy) triples. The plan says how each of the three
  shapes is adapted.
- **R11 under `enforce`.** An unreadable receipts file refuses every `remember` under `enforce` and `closed`. Under
  `shadow` it logs and adds `would_refuse`. Task 25 gains `test_r11_an_unreadable_receipts_file_refuses_every_remember_under_enforce`.
- **"What the other plans use"** lists the imprints plan's Task 45 change to `owner_list` and `uses`.

### New rulings

- **R29**: the one existing test line (RM1).
- **R30**: the legacy layers per action (RS1).
- **R31**: the cache key with the house (RS3).
- **R32**: a served path with no file is no house (RS5).
- **R33**: a place view covers the places that place dominates, and uses its own salt (RM2's pseudonym test).

R15 gains the encoding of an answer use on one road or trail.

### Found while applying

- `test_r26_sign_completes_each_kind_the_tool_files` (Task 26A) ran on `cli_home`, which has no published house. So
  its `gate` proposal's `sign` would have been refused. It now runs on `cli_home_with_house`, which Task 26A now
  defines; Task 27 already used it without defining it.
- The 20,001st-placement bound is checked after `share`'s existing-row path, since re-sharing an existing row adds no
  placement. Task 23 says so and tests it.
- I checked the 11 placeholders left after RM2 and RS7 against RS7's test, the only test of a spec rule. Two failed
  it, and I gave them assertions too:
  - `test_server_startup_folds_old_receipts` (Task 24). Nothing else shows that a fold ever runs (P 9.1,
    "Retention"). Task 24 now says the fold runs at startup under `shadow` and `enforce`, and adds a
    `server._permission_now()` seam for the test.
  - `test_explain_agrees_with_decide_for_a_single_and_a_bulk_use` (Task 27). It was the only test of `explain`
    (P 14).
- That leaves 9. Each has another test of its rule:
  - the two Task 4 membership cases: U28's use 10, U7, U19, PT3 and PT5;
  - the older-`seq` state: PT10's replay;
  - the grantee giving its grant up: U4's table;
  - XS2's null row: Task 15's listing test, which needs it;
  - the annotation's truncation: Task 22's U10 test;
  - `place show`: U8's home-rules test;
  - `rebuild`: Task 10;
  - `uses --json`: Task 15's list tests.

## Final check

Date: 2026-10-26. Reviewer: a fresh agent on the Pi (`smart`), acting in Andy's place. I took no part in writing,
reviewing or revising the plan.

- I read the plan's Global Constraints, Rulings, File Structure, "What the other plans use", Verification and
  self-review table. I read Tasks 2, 4, 5, 5A, 11 to 16, 19 to 21, 23 to 25 and 28 whole.
- The plan is 3,977 lines, uncommitted on top of `85595ed`. Its checksum was the same before and after this check.
- From the spec I read 4.2 to 4.4, 5.3, 5.5's tables, 6.5, 7.4, 9.2, 12.3's house rule, 13's uses 1 to 3 and the U
  list of 17. I also read the review history above.
- I read the code behind every claim below. I ran one check outside the repo, in a scratch directory: a SQLite file
  opened `mode=ro`, on the system Python (SQLite 3.40.1) and on uv's 3.14 (SQLite 3.53.1).
- I edited no file but this one. I changed no code and ran no engram tests. I committed, pushed, merged, deployed and
  posted nothing.

### Verdict

**Approve with changes.** It is not approved as written, because one must-fix remains (FM1). The RM2 fix brought it
in.

- RM1, RM2 and RM3 are resolved.
- The fixes for RS1 to RS7 and the nits add no other must-fix.
- Once FM1 is fixed, nothing I found blocks the build.

### The re-check's must-fix items

**RM1. Resolved.**

- **The plan.**
  - R29 allows the one line and calls it the only edit to an existing test file. Global Constraints (`:95-98`), File
    Structure and "What the other plans use" say the same.
  - Task 23 changes the line in step 3, adds `engram/tests/test_packaging.py` to its `git add`, and runs
    `test_installed_wheel_starts_outside_checkout` in step 4. Task 32 step 3 expects 45 tools.
  - Verification step 2 expects `--diff-filter=MDR` on `engram/tests/` to print only that file, and checks that its
    diff is the one line. The grep `'^[-+][^-+]'` skips the `---`, `+++` and `@@` lines. The line sits at column 0
    inside the test's script string, so the two lines the plan expects are exact.
  - No other task modifies or stages an existing test file, and none touches `conftest.py`.
- **Today.** `tests/test_packaging.py:225` asserts `== 43`, and `engram/server.py` has 43 `@_server_tool()`. Only
  Task 23 adds tools.
- **The other plans.** The count stays 45 through them:
  - the imprints plan adds no `@_server_tool`;
  - the trails plan registers its tools in `_initialize_pre_serving` (its TR14), and the packaging test's script
    calls only `server._init()`.

**RM2. Resolved.** All thirteen have assertions. Each one tests the clause it names, by the spec's reading:

| Clause | Task | What I checked |
|---|---|---|
| U2, depth | 2 | `anc` includes the place itself (P 4.2). The counts are right: j0 has 6 ancestors; k16, under j0, j1 and j3, has 1 + 3 + 11 + 1 = 16; k17, under j0, j1 and j2, has 17; adding p11 to j3 gives k16 17. `World.place` must default to the prefix parent, which `test_u2_joint_place_dominance` already needs. |
| U2, count | 2 | 1,023 places, then the 1,024th is allowed and the 1,025th refused (P 4.4). |
| U6, work to personal | 4 | M1 is in `work` since 2026-10-01, so the allow anchored 2026-11-01 covers it on 11-02. After `pending` and `personal` on 11-03, it doesn't. That is P 5.3's reading for an allow. |
| U8, receipts chain | 14 | Ten rows verify, and a changed `cited` at seq 4 gives 4. |
| U22, five roads | 14 | Five `route` receipts in road order, each with `returned` equal to `sorted([A, B])` (R15). The test makes the five uses itself. The walker that makes them belongs to the trails plan, so this level is right here. |
| U8, pseudonyms | 15 | Under R33, clinic-3's view holds Jenn's clinic-3 pseudonym and public health's view holds her public-health one. Both come from use 2, at clinic-3. |
| U8, no filtered counts | 15 | Steward views count 1 at clinic-3 (use 1's m3) and 3 at parks (use 3), as P 13 says. `parks-planner`'s agent view is empty. P 9.2's agents row gives that: "allowed items ... and refusals of ids they named", and use 3 has neither. |
| U11, `permit` | 23 | Inside the envelope: `done`, with backing `grant:<id>`, `set_by` `agent:default` and channel `tool`. Outside it: a proposal for `person:andy`. The column names match P 5.5. |
| U11, `unshare` | 23 | It works after the covering allow is revoked and again under `closed`, and changes no record or proposal. See FS1. |
| U9, the 20,001st | 23 | It fits today's `sharing.share` (`engram/sharing.py:99`, with the existing-row path from `:118`). `shared_memories` has no foreign key (`027_shared_memories.sql`), so the plain-SQL rows work. |
| U12, the last share row | 24 | The copy and its vector stay while a second row holds them, and go with the last row, as `unshare` does (`engram/sharing.py:176-204`). See FN3. |
| U13, more than 256 | 28 | 300 person-backed members, one allow, and every row linked. See FN1. |
| U13, bytes unchanged | 28 | It fails on a correct build: FM1. |
| U13, registered at home | 28 | Every house and source store is Andy's, at his home. `decide(...).allowed` carries the holding-place clause, since an unregistered house refuses every use with `NO_LAYER` (P 12.3). See FN2. |

I agree with the response about the nine placeholders left: each has another test of its rule. The grantee giving up
its own grant is in Task 9's pure U4 table (`:1264`).

**RM3. Resolved.**

- **The fixtures.** `county_ledger` (Task 11) registers `person:amy` with an empty home. `keep_world` builds on
  `e1_county_ledger`, so Task 25's Amy is this one.
- **Task 25** still expects `Refusal("NO_ALLOW", "place:home/amy", "recall")`, which P 7.4 now gives.
- **Task 5's new U28 case** expects `NO_ALLOW` when Amy is registered and `NO_LAYER` when she isn't, both at
  `place:home/amy`, `recall`. That follows P 6.5:
  - step 1 doesn't catch her: she is a subject, and her home is unknown, not retired;
  - step 3 gives her layer `missing`;
  - step 8 makes `missing` `NO_LAYER` at the first failing layer;
  - subjects sort first, and `place:home/amy` comes before `place:home/andy`. So the case holds even if
    `co_subject_world` left m1 out of the collection.
- **The counts.** Task 5 expects 8 passed and Task 5A 8 + 8. I counted both.
- **Nothing else breaks.**
  - No test counts the persons or places that `county_ledger` makes.
  - Task 11's U5 test adds and removes Amy as a co-subject, which works whether or not she is registered.
  - Task 15's `subject_view("person:amy") == []` reads receipts only.

### Must-fix

**FM1. Task 28's source-store test fails on a correct build**
(`test_u13_each_source_store_is_byte_identical_while_source_instance_id_is_filled`, from RM2's fix).

- **The test.** For each source store, it compares the file's bytes and `sorted(q.name for q in p.parent.iterdir())`
  before and after `migrate`.
- **The default store's directory.** `source_store_paths` gives `.engram/graph.db`, whose parent is
  `ENGRAM_HOME/.engram/`. `migrate` creates `ENGRAM_HOME/.engram/permissions.db` there (Global Constraints) and
  writes `ENGRAM_HOME/.engram/permissions-migrate-<at>.json` (Task 28's interface). So that listing always changes.
- **The instance store's directory.**
  - `migrate` opens sources with `Storage.open_read_only`. That is `mode=ro`, deliberately without `immutable=1`
    (`engram/storage.py:136-137`), and engram stores use WAL (`:122`).
  - I checked on this Pi: a `mode=ro` reader of a cleanly closed WAL file leaves `graph.db-shm` (32 KB) and an empty
    `graph.db-wal` beside it, and the main file's bytes are unchanged. Both interpreters behave the same.
  - So `instances/why/`'s listing changes too, unless the fixture leaves those files in place.
- **The result.** A correct build fails this test. To make it pass, a builder would have to move a file whose path the
  spec fixes, or open sources `immutable=1`, which `Storage.open_read_only` avoids for good reason.
- **Fix.**
  - Keep U13's clause, the bytes of each source's `graph.db`, and drop the parent-directory listing.
  - If the test should also show that nothing was written beside the store, check only names that start with the
    store's own file name. Nothing may appear but `-wal` and `-shm`, and the `-wal` must hold no frames: 0 bytes, or
    byte-identical if it was there before.

### Should-fix

**FS1. Say what the server's sweep does under `closed`, and rerun Task 23's tests in Task 24** (Tasks 23 and 24).

- **The gap.**
  - Task 24 has the server run `sweep_placements` at startup, in `_after_share` and after `unshare`.
  - It doesn't say what the server does when the gate reads `off` or `closed`, and P 10 doesn't either.
  - `sweep_placements` takes a `ledger`, which can't be opened while the ledger is unreadable.
- **Why it matters now.**
  - RM2 made `test_u11_unshare_always_works` real. It calls `unshare` with the ledger unreadable and expects
    `{"removed": True}`.
  - Task 23 passes it while `_after_share` is still a no-op.
  - Task 24's step 4 doesn't run `tests/test_permissions_server.py`. So a sweep that raises there shows up only at
    Task 32.
- **Fix.**
  - In Task 24, the server runs the sweep only under `shadow` and `enforce`.
  - A sweep that fails logs its cause. It never changes the reply of `share` or `unshare`, and never stops startup.
  - Add `tests/test_permissions_server.py` to Task 24's step 4.

### Nits

- **FN1.** `legacy_home_with_300_commons_shares` is described as "the same with 300 `commons` rows". The test needs
  only those rows: it expects one legacy allow and 300 house rows. Say "and no other share rows".
- **FN2.** In Task 28's holding-place test, `Layer("place:home/andy", "consent") in required_layers(s, u)` holds even
  when the house is unregistered, because Andy's home is required anyway, as subject and as requester place.
  `decide(s, u).allowed` carries the clause. Drop that line, or add the converse: the same use, on a `State` without
  the house's `stores` row, refuses with `NO_LAYER`.
- **FN3.** Task 24 uses `enforce_house_with_placements` and `copies_left` but never describes them. The new U12 test
  needs `vectors_left(house) == 1`, and a copy carries a vector only when its source has one
  (`engram/sharing.py:145`). Say that the fixture's source episodes carry vectors.
- **FN4.** Task 23 step 4's `git diff -U0 -- engram/tests/test_packaging.py` names the file from the worktree root,
  but the line before it starts with `cd engram`. Run from `engram/`, the diff prints nothing and the check reads as
  failing. Say that it runs from the worktree root.
- **FN5.** Task 23 defines a tool function named `permissions` in `server.py`, since the tests call
  `server.permissions(...)`. `mcp.tool()` returns that function (`_server_tool`, `engram/server.py:690-697`), so it
  would shadow an `import permissions` in the same module. Say that `server.py` imports the model by name, or under an
  alias, as it does `sharing` (`:29`).
- **FN6.** `HAND_WRITTEN_CASES` (Task 5A): say that the `co_subject_world` entry runs it with `register_amy` both
  true and false.

### Rulings

These are the rulings added or changed since the re-check, each confirmed or vetoed. I vetoed none.

- **R29** (the one test line): confirmed, as above.
- **R30** (the legacy layers per action): confirmed.
  - It is today's daemon, which decides the publisher's policy once per frame (`engram/lighthouse_daemon.py:362`,
    `:402`).
  - Task 20's RS1 test shows that the receiver's layer still refuses on its own.
- **R31** (the cache key with the house): confirmed. The case with two publishers tests it.
- **R32** (a served path with no file is no house): confirmed.
  - The frame's own house passes today's check first (`engram/lighthouse_daemon.py:331-337`), so the gate never
    leaves it out.
  - A missing path serves nothing, so leaving it out opens nothing.
  - RS5's test reads `["code"]`, and `error_frame` puts `code` at the top level (`engram/lighthouse_protocol.py:417-418`).
- **R33** (a place view covers the places it dominates, with its own salt): confirmed. P 9.2's stewards row gives a
  place's receipts to the stewards of every place that dominates it, and E1 use 14 has public health see clinic-3's
  uses.
- **R26's change** (the `gate` act takes `mode` only): confirmed. Task 13's test shows that a house made after the
  agent asked is marked at the yes.
- **R10's corrected reason and gate G11**: confirmed. RS6's two conditions are met.
- **R15's addition** (an answer use on one road or trail): confirmed. Both other plans read R15.
- **RM3's placement** (Amy in `county_ledger`, not `keep_world`): confirmed, for the reasons above.

### Code and system claims I checked

Read today, in this tree:

- `engram/tests/test_packaging.py:215-232`.
- `engram/server.py`: the 43 `@_server_tool()`, `_server_tool` (`:690-697`) and the imports (`:2-32`).
- `engram/sharing.py:99-200`; `engram/migrations/027_shared_memories.sql`.
- `engram/storage.py:122`, `:128-153` (`open_read_only`), `:224` and `:230`.
- `engram/lighthouse_daemon.py:325-340`; `engram/lighthouse_protocol.py:417-418`.
- The trails plan's note on this plan and its TR14. The imprints plan, for `@_server_tool` and MCP tools: it adds
  none.
- In the spec: 4.2 to 4.4, 5.3, 5.5's tables, 6.5, 7.4, 9.2, the U list of 17, 12.3's unregistered house
  (`NO_LAYER`), and 13's uses 1 to 3.
- The SQLite check described above.
