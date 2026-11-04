# Plan review: a ship's own home, and lighthouse crossings (plan revision 1, spec revision 5)

**Verdict: APPROVE WITH CHANGES.** The plan is buildable, test-first, and most safety properties have a named test and
mutant. The two Must-fixes are bounded. Applied as written, they need a re-read of the changed parts, not a new round.

## Must-fix

**M1. The guard misses six tools that store text; three write memories. Spec 2.5's list (kept in R5) is wrong.** These store free text with no guard:
- `challenge_instinct` stores `evidence` as an episode (server.py:3450-3460);
- `retire_instinct` stores `reason` as an episode (server.py:3504-3510);
- `compress_commit` stores `summaries[].content` as semantics (compress.py:567);
- `task_focus` stores `content`, a sibling of the guarded `task_update` (server.py:4082-4105);
- `dream_react` stores `reaction` as a residue (server.py:4246-4265);
- `clipboard_remind` stores `text` (server.py:4559-4580).

`wake` injects task contexts, reminders and residues (hooks/wake.py:350, 373-374, 391). So these tools break both of
2.5's rules: remote text kept as memory, and remote text in a later session's wake.
*Fix:* add every one to `_remote_refusal`, run on the raw arguments (`challenge_instinct` wraps its text in "Evidence:
", which defeats the sentence digests), extend Task 12's parametrized test and its mutant, and correct 2.5 as an R5
item.

**M2. P11's safety argument holds only while `place:outside-home` stays a root, and nothing checks that after
registration.**
- P11 relies on "a root place dominates only itself" (permissions.py:593-600), so the home's `self` allows don't reach
  `remote-stores`.
- A later `add-parent place:outside-home <home>` makes dom(outside-home) include the home. Every `self` allow then
  reaches every remote store (permissions.py:971-974), and nothing shows the owner that consequence.
- The daemon checks only the agent's place name.

*Fix:* in `_LedgerSide`, treat the place as `""` when `place:outside-home` has any parent at use time. Add a test (a
`self` allow plus an added parent delivers nothing) and a mutant.

## Should-fix

**S1. Name the ledger records a crossing needs.** An agent at a root place that acts for the home is reached by an
allow's audience only through `commons`. `self`, group and place entries all fail (permissions.py:960-992). Both the
subject's home layer and the `place:outside-home` layer are consent layers that need their own allow
(permissions.py:1443-1444, 2318). Write the records (layer, `audience: ["commons"]`, purposes, memories, at most 366
days) for Task 8, Task 13 and Deploy 5.

**S2. Task order.** Task 11's "interim limit" test asserts `remote_deliveries` rows and "either session's guard
refuses", which Task 12 builds. Move that test to Task 12, or build `remote_deliveries.py` before Task 11.

**S3. Two owners of `crossing.sock`.**
- Both commands accept the flag, and `federation-listen` takes no `federation_lock` (__main__.py:952-982).
- P9's "a stale socket unlinked" lets the second process steal the first's live socket.
- *Fix:* flock a `crossing.lock`, or refuse when `connect()` succeeds. Test it.

**S4. P12 also disarms wildcard denies.**
- `_pattern_score` serves every rule, and a deny wins only a tie (lighthouse_policy.py:146-152).
- *Fix:* refuse wildcard matches of `urn:superyak:` values only for allow rules. Test it.

**S5. Revision 5 makes decisions, so its status line overstates.** "Changes no decision" is false:
- P9 narrows 2.1;
- P10 makes stage 2 need the Pi's whole home at `enforce`;
- P19 changes who asks.

Say so, so each partner's yes covers them. Also, R5's "12 KiB so the request fits 16 KiB" isn't a guarantee: the other
fields can reach about 5 KiB. P17's whole-request measure is the real rule, and P4 doesn't check the 12 KiB at all.
Make the spec say P17's rule.

**S6. Nothing writes a publisher policy in production.**
- `build_publisher_policy` has no caller outside tests, and policy_gen.py has no CLI.
- So P12's validator never sees the Pi's live policy, and Deploy 4 has no tool.
- *Fix:* name an entry point that adds an exact-ref rule and an audience entry, validates, and re-digests.

**S7. `remote-deliveries.db` concurrency, missing from P19's limit.**
- Two session servers write the file.
- "Unreadable refuses in every mode" would refuse `remember` on `SQLITE_BUSY`, and the write prunes each time.
- *Fix:* use WAL and a busy timeout, tell busy from unreadable, and add both to the limit.

**S8. The guard misses the commonest copy.** A Markdown prefix (`- `, `> `, `1. `) changes the normalized sentence. Strip
leading markers before digesting, or add this to 2.5's "doesn't catch" list.

**S9. Deploy 3.** List what `enforce` changes on the Pi beyond local frames: the remember guard's imprint decisions and
genome refusals for every Pi session (server.py:2081-2120). Also confirm that a ledger exists and that the houses have
migration 029, or `enforce` serves nothing (lighthouse_daemon.py:375, 861-865).

## Nits

- The plan's header says it implements revision 4. Say revision 5, and map findings 1 to 11 to the R5 marks.
- Citations that are off:
  - `_keep_decision` also has `_keep_check` as a caller (server.py:2179-2181, used by tests);
  - test_listener.py:55-60 is a 404 list, not a check for exactly two routes;
  - Task 14's file is `peer/tests/test_station_units.py`.
- P10 names `closed`, but Task 8 tests only `off` and `shadow`. Add `closed`.
- The daemon should refuse a local frame whose receiver is `remote-stores`, since an instance directory can appear
  without `fork_instance` (server.py:1351-1355).
- `federation-units` without `FEDERATE_ARGS` must remove `30-federate-args.conf`, or rollback step 8 leaves the flag on.
- Deploy 2: join_plan counts a contact as confirmed when any code row exists (join_plan.py:66-69). That's weaker than
  check 5, so confirm with P5's rule.
- Risks: a hold on one ship trusts the origin peer to name the right ship, since the publisher can't bind instance to
  ship. Unpair is the real cut-off.
- A short delivered item blocks that sentence in local notes for 90 days, a publisher's lever; consider a minimum length.

## What a builder would still invent

- S1's records, and S6's policy tool.
- `[[hosted]].ship`: a username or a participant id? P8 sends an id.
- Where the socket starts, so Task 7 can test the flag. It belongs in `__main__`, not `Federate`.
- How `crossing_check.py` gets both environments.
- What `neighbor_arm` does with only remote publishers configured: `LighthouseClient` is built unconditionally
  (neighbors.py:48), and `attempted` counts local publishers only (:108-109).
- Which houses `agent remote-stores` lists (permission_cli.py:969 globs every instance).
- Deploy 6 must say Tardis's sessions run on a named instance (neighbors.py:191-197).
- Deploy 4 must name the Pi's publishing ship, which P2 requires to be a `ship` user.

## The questions asked

1. **Citations:** every other one checked matches the code, to within a line.
2. **The spec:** every revision 5 decision is implemented, nothing forbidden is added, and R5 is right except 2.5's
   tool list (M1) and the 12 KiB claim (S5).
3. **Order:** test-first throughout, bar characterization tests such as "a paraphrase is kept". One forward use: S2.
4. **Safety properties:**
   - Refusals before any Engram read: Task 3, with mutants.
   - The ref from the verified origin: Task 4.
   - Exact refs only: Task 8, with S4.
   - The reserved agent, and the receiver layer left out: Task 8, with M2.
   - Serving only under `enforce`: Task 8, with `closed` added.
   - Every text-storing tool: **not met** (M1).
   - The opt-in socket on its own thread, with the amended places: Task 7, with S3.
   - The asker behind `ask_crossing`: Task 11, with its mutant.
5. **P19** keeps the guarantees (one asking function, no marker of the asking process, the guard in the same process,
   no open transaction, tested). Its stated limit is incomplete without S7.
6. **Deploy** rightly gives Andy the pairing, the gate, `remote-stores` and the allows. Gaps: S1, S6 and S9.
