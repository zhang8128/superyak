# Final whole-branch review: permissions by place, step 1

Branch `permissions-core`, `25ca91e..9155015` (96 commits), worktree `/home/andy/superyak/.worktrees/permissions-core`.
Reviewed 2026-10-27 on the station Pi against spec revision 8 (binding), the plan, the vision, `perf-design.md` and
the build ledger (`progress.md`). Read-only: the tree is unchanged. Two probes ran from the scratchpad (one pytest
file importing the test fixtures, one script), and plan verification steps 1, 2 and 6 were run read-only.

## 1. Strengths

- **The decision core follows the spec closely, and the speed work kept it exact.** `decide` runs 6.5's steps in
  order (`permissions.py:2230-2247`). Matching with history reads allows narrowly and denies widely: lanes
  (`lane_held`, `lane_touched`), memberships (`_membership_counts`, `_meets`), groups and agent places
  (`_audience_entry`). Rules 4 and 5 run on every match (`_chain_ok`, `_grant_ok`). The P2/P3 fast paths are
  sound: `_STATIC` and `_LANES` are taken only for live, person-backed records with no `replaces`, where
  `_chain_ok` and `_grant_ok` are true anyway. P0's frozen a083a96 reference and its all-fields equality test
  guard everything after.
- **Grouping meets revision 8's M1.** `_share_key` (`permissions.py:2358-2393`) returns None, so the object is
  decided alone, for any grant-backed membership row (removed rows included) and whenever any grant's envelope
  lists memories (revoked and expired grants included). Every attribute a decision reads of an object is in the
  key: kind, store, layer, subjects through `copies`, the records that list it, and lane-note and membership
  times placed among Θ, which holds t and every record's anchor and `valid_from`. The bulk path's `group_key`
  takes another route that is also safe: a membership row holds the object's own ref, so any object with a
  membership is never grouped, and an object an envelope lists is keyed by its ref.
- **P36 is narrow, as written.** `qualifies` (`permissions.py:1260-1279`) needs the requester to act for the
  store's owner, `place:home/<owner>` to dominate both P and H, and either a bulk use or an `imprint` whose
  `keeps` store is held at home. In a qualifying use the owner's home is always in `anc(P)`, so it stays a consent
  layer, and so does any place co-subject in `anc(P)` or `anc(H)` (`_required_layers`, `fixed`). The
  `required_layers` memo key holds every input that `qualifies` reads.
- **Agents cannot widen through the tools.** `authorize` turns every `WIDENING_ACTS` "do" on the `tool` channel,
  or by an agent without a covering grant, into a proposal (`permissions.py:3717-3719`). `sign` and `decline` on
  the tool channel are refused, and agents can never sign. Narrowing replacements keep the replaced record's
  backing (`keeps = rec.backing`, 7.3). A deny an agent writes under a grant is person-backed. `permit` builds
  `collect` lanes from the store row, never from the agent's arguments.
- **Under `enforce` no content leaves without a receipt.** `read_item` delivers only when the receipt is written.
  `_rank_recall` returns nothing when its recall receipt fails. Every unreadable or undecidable path serves
  nothing. Refused copies are filtered before ranking (P23). The agent's views show no code, layer or filtered
  count.
- **The background build is careful.** One build runs per key. The cache lookup and the build registration
  happen under one lock. The build checks the change counter on its own connection (4beae37) and re-reads the
  ledger's seq. Entries carry seq, ledger id, change count, copy and `at <= t < horizon`. Legacy layers are met
  afresh on every frame (`meet_legacy`). A build and the frame that started it share one turn of
  `FRAMES_AT_ONCE` (`_Turn`).
- **Memory discipline:** a lazy State with bounded row and log-time caches, per-State memos, streaming
  `rebuild`, a fold of one receipt at a time, one State per `perform`, the records bound counted inside
  `BEGIN IMMEDIATE`, and measured peaks with real margins.
- **Hygiene.** Every SQL statement built from strings uses fixed table and column names, or names checked against
  `_COLUMNS`; the values are bound. CLI text an agent supplied goes through `_clean`, and the `needs-allow` command
  line goes through `shlex.quote`. The terminal yes uses `os.urandom` with rejection sampling and
  `hmac.compare_digest`.

## 2. Issues

### Critical

None found. I found no path in normal operation where grouping, caching, P36, grants, expiry or the gate widens
a decision, or where content is delivered under `enforce` without a receipt.

### Important

**I1. Proposals, and agents' child grants, are unbounded, and every State holds them whole (P37; 15 "Memory"; 5.6).**
`permission_ledger.py:720-736` (`_file`), `:519-558` (`state()` loads every table not in `_PER_OBJECT`, `:97`),
`server.py:2414-2470` (`permit`), `permissions.py:3546-3562` (a child grant).

- **What's wrong.** Any registered agent of the owner can file a proposal through `permit` with no yes. No limit
  applies: there is no cap per agent, no de-duplication, and expired or declined rows are never pruned. Each
  proposal keeps its whole act body, a selector of up to 512 refs included. `state()` loads `proposals`, with
  bodies, and `permission_grants` whole into every State: the daemon's frames and builds (2 at once),
  `perform`, the server's `permit` and `permissions`, and the guard.
- **Measured.** The probe filed 300 tool-channel `allow` proposals, each with a 512-memory selector. A State then
  held 4.1 MB more (about 14 KB a proposal), and filing took 5 s, each `perform` slower than the last.
- **Why it matters.** The budget in spec 15 counts records, caches and sets, not proposals. At the records bound
  the daemon's margin is 40.3 MB. About 1,500 such proposals in each of its two States uses that up. An agent in a
  retry loop, the "agent's mistake" case, would push the daemon on a 2 GB Pi past 512 MB. Each proposal is also a
  ledger write, so it also invalidates the eligible-set cache. A grantee with depth left can issue child grants
  without limit in the same way.
- **Fix.** Bound open proposals in `_file`, inside the write's `BEGIN IMMEDIATE` as the records bound is: for
  example 64 pending per agent and 1,024 in the ledger, refused with the bound in the reason. Bound child grants
  per parent. Better still, have `state()` leave proposal bodies out (read them on demand: no decision reads a
  proposal) and skip decided and expired proposals. Add a U24-style probe that holds the bound. This can wait
  until just before `gate shadow` (G3), because no State is built while the gate is `off`. It is small enough to
  fix before the merge.

**I2. SH-13: a chunked `collection add` or `remove` writes part of one yes, then says "refused".** Confirmed.
`permission_cli.py:456-490` (`_collection`), `:262-296` (`_perform`, the act loop at `:272`).

- **Reproduced.** With `MAX_ACT_OBJECTS` set to 3, m3 to m5 are already members, and
  `collection add c m0 ... m8` is run. The first act commits m0 to m2. The second act holds only members, and
  `_prep_collect` raises. The third act is never written. The command exits 1 with
  `refused: ... every one is already in collection:andy/c`, and nothing says m0 to m2 were added.
- **What `remove` does.** `remove` has the same shape: `_prep_uncollect` refuses any ref that is not a member, at
  whichever act holds it.
- **Rerunning fails too.** The first act of a rerun now holds only members, so it is refused again.
- **Why it matters.** The person is told a write was refused when part of it took effect. A collection reaches
  every allow that names it. They may believe nothing moved while 10,000 memories now flow to a place, or, for
  `remove`, believe a narrowing is done when it is partial. Nothing widens beyond the yes, but the person's view
  of what moved is wrong. That fails the transparency the vision asks for.
- **Fix (the decision the ledger left to this review).** Filter against the State before chunking:
  - `add`: drop refs already held, and refuse before the yes if none is new;
  - `remove`: refuse before the yes any ref that is not a member, and name it.

  Then every act is valid at the yes. A concurrent writer can still make a later act fail, so `_perform` should
  print each act it completed before it re-raises: "acts 1 of 3 done (log n); the rest were not written". An
  all-or-nothing batch would need `perform` to take several acts in one transaction. That is a larger change
  and not needed for step 1.

**I3. Plan "Verification before merge" fails as written.**

- **Step 2, `git diff --name-only --diff-filter=MDR main...HEAD -- engram/tests/`.** It prints
  `engram/tests/conftest.py` as well as `test_packaging.py`. That change is Task 19's autouse fixture restoring
  `LEDGER_BUSY_MS` (`conftest.py:114-126`), and it breaks R29's "the only existing test file this plan changes".
- **Step 2, `git diff --check main...HEAD`.** It prints `engram/tests/test_permissions_boxes.py:152: new blank
  line at EOF.`
- **Step 2, the stat check.** `git diff --stat main...HEAD` lists files outside "File Structure":
  - test support files: `permissions_reference.py`, `permissions_budget_core.py`, `permissions_budget_ledger.py`,
    `permissions_memory_support.py`, `pi_budget_probe.py`, `test_store_digest_chunks.py`;
  - the specs, plans and reviews merged in from `trail-arrows-spec` (8e2a075).
- **Step 4.** It expects "2 passed" with two durations. Revision 8's U24 file holds 16 gated tests: three timed,
  11 memory and two daemon peaks, under five time budgets.

Why it matters: the merge reviewer runs these literally, and they will fail or mislead.

Fix:

- Move the fixture into a `test_permissions_*` module or a permissions-only `conftest.py` under a new directory,
  or record a ruling amending R29.
- Strip the blank line at the end of `test_permissions_boxes.py`.
- Add a plan note (or ruling) listing the SH and P tasks' files and the docs the rev-8 merge brought in.
- Update step 4's expected count and budgets.

**I4. The embedder deploy gate (12.2) is in no merge check or gate, and the daemon's refusal is not behind the
permissions gate.**

- **What's wrong.** `lighthouse_daemon.py:1074-1080` returns 2 when `ENGRAM_EMBEDDER_SOCKET` is unset, under
  every gate, `off` included. `superyak-runtime` sets it only when `runtime.json` has `embedder_socket`
  (`scripts/runtime.py:653-655`). Spec 12.2 says "before the daemon's refusal ships, every machine that runs the
  daemon has that key and runs the embedder unit".
- **Not tracked.** The plan's Verification and Gates tables (G1 to G11) do not carry this. It survives only as
  SH-7's cannot-verify line. `engram/CLAUDE.md` also says that with the gate `off` engram behaves as before
  "apart from two fail-closed changes". This is a third, and it is not fail-closed: it is an outage.
- **Why it matters.** On the next start (G2), any of Andy's machines whose daemon runs without that key, the Mac
  for instance, stops serving neighbors.
- **Fix.** Add a gate before G1 or G2: check `runtime.json` and `superyak-embedder.service` on every daemon
  machine. Also correct the CLAUDE.md sentence to name the embedder requirement.

### Minor

**M1. A second revocation overwrites the first.**

- **Where.** `permission_ledger.py:1561-1564` (`_make_revoke`), `:1606-1618` (`_make_replacement`'s update),
  `:1680-1683` (`_make_end_grant`), `:640-650` (`_project`'s update).
- **What's wrong.** Each update matches `{"id": ...}` only. `perform` checks "not already revoked" against its
  State and then opens its own `BEGIN IMMEDIATE` (`:665-687`). Two writers can both pass: the owner's CLI and an
  agent's `withdraw` or `narrow` under a grant. The second then overwrites `revoked`, `revoked_by`,
  `revoke_reason` and `revoked_seq`.
- **Why it matters.** "Filled once, by a revocation. Nothing else in a row ever changes" (5.1) is broken. A
  historic `state(seq)` between the two writes reads the record as live, since `_UNDONE` clears a
  `revoked_seq` past its seq. That misstates audits of receipts made in that window (PT10's replay claim). No
  current decision widens. A concurrent replacement also leaves two live replacements, both inside R by rule 4.
- **Fix.** Add `"revoked_seq": None` to those `where` clauses (as `uncollect` does with `removed_seq`), so the
  second write matches no row and is refused.

**M2. A backward clock step lets a cached decision outlive a just-written membership or co-subject.**

- **Where.** `permissions.py:881-892` (`_span`, `_in_force`), `:1183-1197` (`_own_subjects`), `:1937-1952`
  (`_horizon`).
- **What's wrong.** Membership, agent-place and subject rows count from their log row's `at`. A row whose `at` is
  after the decision's t is not yet in force. If the wall clock steps back (NTP), a deny-membership or co-subject
  written just before a frame has `at` > the daemon's t. It does not count, and the decision is cached. The
  horizon holds only record and grant times, so the entry keeps serving after real time passes that `at`, until
  the next ledger write.
- **Why it matters.** "Deny wins" and "adding a subject narrows" fail for a while after a clock step. That is
  rare on one machine.
- **Fix.** Add each read row's `lo`/`hi` that falls after t to the horizon, or, simpler and fail-closed, treat a
  row with `at` > t as in force for denies and for subjects.

**M3. A read and a recall decide a copy with a sourceless placement differently.** `lighthouse_daemon.py:555-558`
against `:494-499`. `recall_set` refuses a memory any of whose placements has no object. `read_item` drops
sourceless rows (`if o`) and decides on the rest. So under `enforce` an agent that already holds the id can read
a copy that recall would filter, with its legacy audience coming from the unmatched row. Make `read_item` refuse
the item when any row has no object, as 12.2 says ("a row with no `source_instance_id` has no object, so under
`enforce` it is refused").

**M4. The `remember` guard records only the first matching delivery as the kept copy's source.**
`server.py:2104-2109`, `:2135`. When the content matches deliveries of two objects, such as two memories with
identical text, only `decided[0]`'s subjects are carried (P25). Carry the union, by adding each other source's
subjects as `subjects` rows with `added_by=copy:<ref>`. `copies` keeps one source.

**M5. A place's display name can hold control characters, and later yes prompts print it raw.**
`permission_ledger.py:1108-1125` checks only for non-empty text of at most 255 characters. `proposal_words` and
`allow_words` print it through `_name`, and `confirm` (`permission_cli.py:82-101`) prints `words` unescaped. An
agent-filed `register-place` shows the name `_clean`ed at signing. Once signed, an escape sequence in it could
rewrite the terminal in every later yes that names the place. Refuse non-printable characters at write time, and
`_clean` the words in `confirm`.

**M6. `Ledger.cosubjects` does not follow `copies`.** `permission_ledger.py:915-919`. It is the API the
imprints plan names for `cosubjects(m)` ("What the other plans use"). Spec 19 already records that this misses a
source's later subjects and puts the fix in the imprints revision. To make misuse impossible, return
`subjects_of(state, ref, now)` less the owner, or rename it and say so in its docstring.

**M7. Frames on one house share one read connection** (logged item 6; `PublisherStore.open`, `_eligible` `:630`,
`_start_build` `:657-662`). See the triage below: the effects are fail-closed, but a partial `_start_build` read
leaves placements refused until the next change. Give each frame its own read-only connection when convenient.

**M8. Shadow receipts mix two refusals** (logged item 5; `lighthouse_daemon.py:563-571`). When both refuse,
LEGACY_DENY replaces the ledger's own code. When the ledger allows and the audience check refuses, the receipt
holds `allowed=1` with a refusal, and the owner's list shows "allowed" for an item never delivered (marked
`shadow`). Record the audience refusal in a field or `cited` entry of its own, and keep `refusal` as the ledger's.

**M9. `sweep` prints "Placement sweep: nothing to change." after a failed sweep.** This is deferred minor Task 27
(`permission_cli.py:729-736`): `run_sweep` returns None on failure as well as when the gate is `off`. Say that it
failed.

**M10. The record of the U24 measurements overstates the cap.**

- **What's wrong.** Spec 15 ("Measured", "each in a fresh process under `MemoryMax=512M`") and
  `permissions_budget_ledger.py:297-305` imply an enforced cap. This Pi has no memory controller
  (`cgroup.controllers`: cpuset, cpu, io, pids), so it is not enforced.
- **What still holds.** The assertions read VmHWM, so the figures stand.
- **Fix.** Have the probe also record `VmSwap`, so a swapped run can't understate a peak; 401 MB of swap is in use
  on this Pi. Have the spec's next revision say the cap was not enforced here.

## 3. Triage of the logged items and the deferred minors

1. **SH-13: fix before merge.** See I2: filter against the State, and report the acts done when one fails.
2. **P8, a second build for one key: harmless, and in fact not reachable at 9155015.**
   - `_eligible` looks up the cache and `_builds`, and registers a new build, under one acquisition of
     `_cache_lock`.
   - `_build` inserts its entry under the lock before its `finally` pops `_builds`.
   - So a frame that finds no build either finds the finished entry or the first build left none that serves:
     the ledger moved, the set was too large to keep, it was evicted, or it was built for another seq. Starting
     a new build then is 12.2 item 5's "the next frame builds again".
   - Two builds never run at once for a key. Close the item.
3. **The P8 rulings against 12.2.**
   - **(a) Under `shadow`, a frame past the wait writes no receipt.** This matches 12.2 item 2 as revised (M2 of
     the rev-8 check). Keep it. A caution: Andy's builds measured 0.30 to 0.83 s against a 1.0 s wait, and the
     Pi was seen at load average 7. Under load, `report shadow` silently loses those frames (logs only).
     Consider counting them in the report.
   - **(b) A build whose ledger moved still serves its own frame.** This is consistent with the spec.
     - What `serves` checks: a cache entry is valid for frames whose State is at the same seq, not for the
       live ledger's seq.
     - What item 5 drops: the entry, and "the next frame builds again".
     - Why serving is safe: the frame is served exactly what its own State decides, as a synchronous decision
       would have been. The window is at most the 1.0 s wait, shorter than the pre-P8 synchronous rebuild.
     - What the receipt shows: the frame's seq, so the use stays auditable.

     Ask Rio Grande to word 12.2 so that "a finished set that still holds" plainly means "holds at the frame's
     own seq".
   - **(c) A build counts as one of the 2 frames.** It counts by sharing its starter frame's turn. That holds the
     memory budget (at most 2 States), which is what item 3 is for. Keep it.
4. **P7, rev 8 check M1: verified.** `_share_key` decides alone every object with a grant-backed membership row
   (removed rows included), and every object while any grant (revoked or expired included) lists memories.
   `decide_bulk`'s `group_key` reaches the same result by another route (Strengths). Nothing to fix.
5. **Task 30B/30C shadow receipts: fine for merge, Minor M8.** Old both-refused receipts listed as disagreements
   affect only receipts written before faebdae. No live ledger exists yet (G3 has not run), so there are none in
   the wild. Leave it.
6. **One sqlite connection across frames' threads: not a widening, fix later (M7).**
   - The house connection is a read-only `Storage.open_read_only` with `check_same_thread=False`.
   - The build thread now uses its own connection for the change counter, and it never touches the house
     connection.
   - The ledger State's lazy readers lock their own connections.
   - A glitch on the shared connection gives an empty or short read. That makes `_house_lacks_029` serve
     nothing, or drops an object, which is then refused.
   - The one widening shape is a house copy whose placements name two different source objects, where a partial
     read drops the refused one. In practice `share` cannot make it: a copy is keyed by
     (`source_instance`, `source_id`) with a verified digest.
7. **MemoryMax not enforced on this Pi: nothing in the branch relies on it.** Step 1 adds no unit (15). U24
   asserts `VmHWM < 512 MiB` directly (`test_permissions_pi_budget.py:94`). The daemon's 257.6 and 273.3 MB and the
   other peaks are real resident figures. This Pi has 16 GB, so a probe was not under memory pressure. See M10
   for recording `VmSwap` and correcting the spec's wording.

**The deferred minors (351, plus 215 cannot-verify lines).**

- **Fix before merge:** only SH-13 (`progress.md:1079`, I2).
- **Fix soon, not blocking:**
  - Task 11 (`:624`): `perform`'s check-then-write. It overlaps M1. The other races it names (last steward,
    P31, copy chain) are caught by a unique index, need two concurrent owner commands, or cannot be raced, since
    a copy is recorded before its store write.
  - Task 27 (`:886`): M9.
  - Task 15 (`:693`): the subject view lists other homes' record ids. This only becomes reachable in step 2.
  - Task 24 and P5 (`:831`): lane settling is not bounded per pass.
- **Fine to leave:**
  - **Cosmetic and test quality:** wrapping, import order, docstrings, dead scaffolding, leaked test
    connections.
  - **Thin TDD evidence**, disclosed in the reports.
  - **Shapes later tasks superseded:** Task 20 `:758` by 30C; Task 21 `:771` by P8; Task 10 `:613` by 13B.
  - **Fail-closed edges:** SH-2 `:965`, Task 23 `:813`, Task 25 `:844`.
  - **Defensible choices:** Task 9's `_OWN` identity marker `:581` (fragile but correct); Task 1's duplicate
    JSON keys `:361` (the person's own CLI text only); Task 28 `:903` (an empty group is accepted by
    `_prep_group`, so `migrate` does not roll back).
- **Cannot-verify lines still open that matter:**
  - **SH-7's deploy gate:** I4.
  - **The P6 and P7 gated timings under load:** P9 re-measured them: 18.1 of 30 s, 192.5 and 214.6 of 300 s,
    3.49 of 6 s.
  - **P8's U24 cache fill:** P9 covered it with 24 keys, 118.6e6 B added and 4 evicted.
  - **Everything else:** the controller's whole-suite run at a6f799a covers it (3,392 passed; the 3 Kuzu
    baseline failures).

## 4. Declined to judge

- **Agents faking a terminal, forging receipts or editing the ledger file under the same Unix account:** spec
  7.6's stated known limit.
- **No signature, and no table-against-log verification on read:** step 1 has hash chains only (5.6), and
  signatures are step 2.
- **The P36 widening itself:** Andy's decision A6. Only its form was checked.
- **The `sweep` command and the post-command receipt fold writing without the yes:** the system following the
  ledger (narrowing removals, settling notes, folding). Spec 10 gives the sweep to the servers without a yes.
- **Frames waiting for a turn with no deadline, and slots held by builds for up to 30 s:** spec 12.2's stated
  known limits.
- **The 1.0 s rebuild wait and the five time budgets:** Rio Grande's calibration calls (15).
- **The legacy publisher layer using the read frame's one decision for `recall`, `read` and `inject_context`:**
  legacy semantics, decided afresh on each request as 6.3 item 4 says.
- **The per-layer bound of 256 records passed by one under two concurrent writers:** harmless, since only the
  per-ledger bound must hold under concurrency (5.4).
- **`share` under `shadow` placing copies with no covering record:** 12.3's table says "as today".
- **Pseudonyms computable by whoever holds the ledger:** 9.2 calls them a display convention.
- **The `remember` guard's 24-hour, 200-receipt window, and paraphrases:** section 10's known limits.
- **Annotations naming every allowing home:** a step 2 matter (BS3).
- **A sub-second race between the sweep settling a pending note and an in-flight re-lane:** it needs an allow
  written inside that window, and 5.3's pending reading accepts it.
- **Thread build-up in `ThreadingUnixStreamServer` while turns are held:** a cost, not correctness.
- **Read frames taking a turn and a State even when the legacy frame decision refuses:** a cost only.
- **Step 2 concerns:** the subject view across homes, self-claims held whole in a State, station ceilings and
  imported receipts at runtime. They are not reachable in step 1.

## 5. Assessment

**Ready to merge: With fixes.** No widening path, lost receipt or skippable yes was found. The decision core,
P36, grouping, the cache and the background build hold. Before the merge:

- bound and slim the proposals and child grants that agents can add to every State (I1);
- make SH-13's chunked collect honest (I2);
- bring the plan's verification steps in line with what was built (I3);
- add the embedder deploy gate (I4).
