# Review: room moderators plan, merge 1

Plan: `docs/superpowers/plans/2026-10-27-room-moderators.md` at 9a682673 on branch `room-moderators` (12 tasks, Rulings
1–20). Spec: `docs/superpowers/specs/2026-10-27-room-moderators-design.md`, approved at 46882b51, with its review and
re-check in `docs/superpowers/reviews/2026-10-27-room-moderators-review.md`. Code: the same worktree, `main` f5368629
plus the spec. Reviewer: a fresh reviewer agent. I took no part in writing the spec or the plan. This review is
read-only: I ran no tests, posted nothing and changed no file except this one.

Read against the code: `grants.py`, `chats.py`, `ships.py` (`_owned_room`, `_station_add`, `station_bridge`,
`station_add_ship`, `_earlier_bridged`, `safe_line`), `common.py`, `db.py` (the transaction, `BEGIN IMMEDIATE`),
`system_author.py`, `briefs.py` (`_brief_to_carry`, `_write_brief`), `room_board.py` (`_carry_board`),
`room_claims.py`, `tickets.py` (`_spendable_grant`), `federation.py` (the event collector), `backups.py` (`COMPARED`,
`_usable`, `_not_this_station`, the reconcile's steps, `describe_reconcile`), `signatures.py`, `agent_version.py`,
`app.py`, `__main__.py`, the `Makefile` and `static/app.js`; on the agent side `mcp.py` (`resolve_room`, `handle`,
`TOOLS`), `station.py` (`StationError`, `label`), `install.py`, `runs.py`, `wormhole.py` and `tests/conftest.py`
(`FakeStation`). I traced every existing peer test that adds or removes a member, and the tests that compare grant
views, room views, the reconcile's report and the schema. I checked the Pi's user units' `ExecStart` lines.

**A note on numbering.** The brief names "Ruling 2" (every `_station_add` caller in one transaction), "Ruling 7" (409
instead of 403 for a non-owner on a replaced room) and "Ruling 13" (restore copies the owner's removal rows). In the
plan at 9a682673 these are Rulings **1**, **9** and **15**. I judged them by content and use the plan's numbers below.

## Verdict

**APPROVE WITH CHANGES.** 4 must-fix, 9 should-fix, 10 nits.

The plan is careful and close to buildable. It maps every spec section and every spec test to a task, pins its texts,
keeps every act in one transaction, and builds nothing that lets a moderator, a ship or a watcher run exceed the owner
or the spec. The must-fixes are mechanical: three existing tests break that the plan doesn't name, one agent test
expects an error string the tool can't produce, one spec test case (T3's "the reverse") and its refusal text are
missing, and Task 12 restarts only two of the five units the merge changes.

## 1. Spec coverage

The pre-flight list is accurate. Section by section:

- **§1 (M1–M5)** Tasks 1 and 2. Shape, depth 0, `delegable` unchanged, signing, coverage forward (`_covered_room`),
  check 4 over `member_changes`, check 5's three reasons plus "covers no current room" for a fork (needed by M4).
- **§2 (checks 1–5, M7, M8, schema)** Tasks 1 and 3–6. Check order, one member per act, default `grant_id`, M7's
  refusals in order, `_owned_room`/`_station_add` as the owner, one transaction (R-S1), `carry_brief` ignored (R-S3),
  M8's one removal for every path with chain walk, epochs, revocation, deferrals, silent claim release, row and notice,
  self-removal under either action (R-S4). The SQL is the spec's, verbatim.
- **§3 (M9–M13)** Tasks 2, 5, 6. No owner removal, no G10 or brief power, no Wormhole, `_station`, ownerless ships or
  remote contacts, existing accounts only, no `depth`.
- **§4 (M14, M15, M19–M21)** Tasks 2–8 and 11. Notices for every add and remove by anyone, with the bridged sentence;
  `moderators` and `moderating`; appointment and end notices through `safe_line`; the act log, `actions`, `made_via`,
  `changes`; G13's copy; notices never cross the bridge.
- **§5 (M16–M18)** Task 10. Sessions-only tools, run settings and `run-mcp.json` unchanged.
- **§6** Tasks 2, 3–10. Routes, ship routes, tools with the spec's descriptions (I checked both character for
  character: they match), title resolution, make targets, the CLAUDE.md paragraph and the bridging sentence. The
  browser half of M15 and §6 is merge 2, as the spec's build order says.
- **§7, §9, §10** Task 12's gate, R-S2's listing, Task 11's pin.
- **§8** Every T1–T12 has a test, with two gaps: T3's "and the reverse" (must-fix P3) and T6's "never yields a build
  ticket", which passes for the wrong reason (should-fix S6).

**Built beyond the spec's text** (each narrows or is cosmetic unless noted): the owner's `NO_ONE_NEW` 409 and 404
`NOT_A_MEMBER` (Ruling 10), `made_via` on direct grants (16), spent grants shown in `moderating` (14, a deviation
from "valid"), grant-less rows in G13's copy (15), the ship route's name normalization (17), `moderators: []` for a
received room, the extra notice wordings (13), and the `station-rooms` column showing grant short ids. None widens
authority. 14, 15 and 16 should be named to Serenity (S9).

## 2. The rulings

- **1 (R-S1 everywhere; the brief's "Ruling 2"): right; keep it.** The spec already forces it: M7 has `_station_add`
  take `db`, and M14 puts the bridge's and add-ship's notices "in the act's transaction", so their callers must hold
  one. Putting `_owned_room`'s read, the checks and the add in one `BEGIN IMMEDIATE` transaction also closes the
  check-then-add gap those operator commands have today (a concurrent add or removal between station-add-ship's
  "already a member" check and its add), and the unbridge's earlier-room removals stop being separate transactions.
  The "brief changed while …" 409 becomes a defence that only an injected race reaches; the rewritten tests inject it
  inside the transaction through `race`, still exercise the translation, and add that the competing save rolled back.
  That is stronger, not weaker. No need to go back to the ships.
- **2 (R-S2, option (b)): right,** with the listing step. Option (b) also asked that the limit be stated; see S4,
  because merge 1 changes who can remove such a leftover.
- **3, 4 (R-S3, R-S4): right.** Both are the re-check's text.
- **5 (N4): right.** One predicate for the 403 and both lists; the removal still revokes an expired grant it finds.
- **6, 7, 8: right.** Moderate grants only for `station-unmoderate`; the forward test is T4's; breakouts and the
  reconcile keep their own paths.
- **9 (the brief's "Ruling 7"): right, and required by the spec; no need to go back to the ships.** §2 says "The checks
  run in this order, and the first failure answers", and check 3's "Otherwise 403" covers every caller, so check 2's
  409 comes first for a non-owner too. The property it overrides ("only the owner learns the room was replaced") no
  longer holds elsewhere: the board answers 409 `REPLACED` to any member who writes to a replaced room
  (`room_board.py:100`), the ship brief route answers 409 to member ships (`test_ship_agent.py`, "change the brief
  there"), and the person Board view lists only current rooms. Two corrections for the record (S9): the quoted line is
  the docstring of `test_adding_members_to_a_replaced_room_is_refused` (Serenity's work-board final review F2), not work
  board 8.4's text; and "every member of a replaced room is in its replacement" is false for pre-merge leftovers, who
  will now learn that a newer room exists (not its id). That is low-value information and acceptable.
- **10, 11, 12, 13: right.** 10 narrows the owner's path; 12 never says whether a grant exists.
- **14: acceptable deviation, built wrong.** Showing a spent grant with `budget_left: 0` helps the ship, and it is the
  caller's own grant. But Task 7 implements "unrevoked, unexpired", which also shows a grant check 5 has paused. S2.
- **15 (the brief's "Ruling 13"): right in effect; make it explicit; no need to go back to the ships.** It copies the
  owner's grant-less rows so M7's "Andy removed X" survives a restore. Its stated reason, "It only takes power away",
  is true only because of a side effect: an `add` row and the room it makes are written in one transaction, so a copy
  holds both or neither, and the `new_room_id is empty or here` rule skips every add made after the copy. A grant-less
  add copied would clear a removal the copy records and hand a moderator an add back. Say "remove rows" and filter on
  it (S1). The same rule, from the spec's own "whose rooms are here", means a moderator's adds after the copy are never
  copied, so only removals carry a day's budget across a restore; that is consistent (the add's room is gone), but T11
  and Task 8's docstring should say so.
- **16, 17, 18, 19, 20: right.**

## 3. Buildability

Each task can be built in order. Tests that **can't pass after the code as written**:

- Task 10, `test_add_and_remove_report_what_the_station_did`: the refusal string lacks the status (P2).
- Task 2's own Step 4 run (`tests/test_grants.py`) and Task 4's and Task 8's (`tests/test_restore.py`): three
  existing tests the plan doesn't name now fail (P1).

Tests that **can't fail before the code** (acceptable as pins, but Step 2 says FAIL; S8):

- Task 5: `test_moderating_adds_no_brief_or_grant_power` (existing behaviour once Task 2 exists), and the `replaced`,
  `none`, `direct`, `elsewhere` and `named` cases of `test_a_moderators_add_is_refused_by_its_grant_and_writes_nothing`
  (Task 3 already answers `REPLACED_ADD` and `NOT_A_MODERATOR`).
- Task 10: `test_watcher_runs_have_no_member_tools`. Every assertion is true today; its last one is vacuous, since the
  watcher never calls tools. It is still a useful pin of the run settings.
- Task 11: written to pass, with a mutation check instead. Fine as stated.

I traced the rest against the code: fixture helpers (`docked`, `ship_client`, `card_of`, `_revocation_record`,
`_grant_record`, `staged`, the CLI's `ValueError` exit), table columns the tests insert into (`deferrals`,
`remote_contacts`, `peers`, `rooms`), `safe_line`'s output for `'@venus\nhello'`, ship display names (`Rio Grande`),
the `FakeStation`'s `linked_room_id`, the `Wormhole` constructor, and the uid monkeypatch in Task 9. They hold.

## 4. Authority

Nothing lets a moderator, a ship or a watcher run do more than the owner, or more than the spec allows. I checked:

- the moderator's add runs `_add_members` as the owner, with M7's narrower refusals, in one transaction with the grant
  check, `_owner_removed` and the budget; `carry_brief` is ignored, so the brief can't be dropped;
- the removal path refuses the owner, Wormhole, ownerless ships, other moderators and remote contacts; it revokes the
  removed account's moderate grants (never `direct` ones) for good, signed, outside G10; self-removal skips only
  check 4;
- `_acting_grant` filters on the caller's own grants that cover the room, and a named foreign `grant_id` answers as if
  none were held;
- the ship routes take `ship_member`, the person routes `current_user`; a ship never owns a person's room, so the ship
  routes have no owner branch; `/api/grants` still refuses ship keys;
- runs get neither tool (`RUN_MCP_DENY`, `run_mcp_config`); conftest sets `HOME` per test, so Task 10's `install_all`
  touches no real config;
- `station-moderate` needs `_owned_room` for `APPROVER` and a signing store; `station-unmoderate` matches only that
  person's moderate grants;
- `moderators` and `moderating` can't be forged by a paired peer: received snapshots keep only known keys, `get_room`
  sets `moderators: []` for a received room, and `_moderating` keys on local ids (N6 pins it).

## 5. Breakage

The changes the plan names are faithful: each keeps its test's point or tightens it, and the by-hand removals in
`test_breakouts` and `test_room_board` keep "only in a superseded room" and "removed and added back" meaningful under
M8. One loses a pin (N4). The 409 for the doctor in `test_adding_members_to_a_replaced_room_is_refused` is Ruling 9,
not a weakening.

Three more tests break and are not named (P1): two exact grant-view comparisons in `test_grants.py`, and the schema
classification in `test_restore.py`. I found no other unnamed breakage in the Python suites: the federation,
grant-ticket, breakout, inbox, mention, brief and wormhole tests that change membership assert nothing the notices or
the chain walk change, and the reconcile's report is matched by substring. `test_browser.py` runs on the Pi (Playwright
is locked and its Chromium is cached) and drives both routes; I couldn't run it, and the plan first runs it in Task 12
(S5).

## 6. Merge and deploy (Task 12)

The order is right under law section 2: suites on the Pi, one push, Serenity's verdict in the room, a checked backup
outside the rotation, a read-only listing from the backup, the merge and push, restart, check, revert on failure, and
an announcement; the first use waits for Andy at Rio Grande's terminal. Three gaps:

- **The restart is too small (P4).** The merge changes `agent/superyak_agent`. `superyak-ship`, `superyak-odo` and
  `superyak-wormhole` run `agent/run_agent.py` from `/home/andy/superyak` (their `ExecStart` lines), and the version
  check counts `agent/superyak_agent` (`RUNTIME_PATHS`), so they are "affected Pi services" in the law's words. The
  ship-room-briefs and version-check deploys restarted all five units and the `superyak-ship-*` units.
- **Main can move after Step 1 (S3).** Step 7's `git pull --ff-only` then merges a head no suite ran on.
- **The announcement should state R-S2 (b)'s limit (S4).**

The health URL and data paths match the units on the Pi (`--host 127.0.0.1 --port 7435`, `STATION_DATA`).

## Must-fix

**P1. Name and fix the three existing tests that break (Tasks 1, 2, 8).**

- `peer/tests/test_grants.py::test_a_grant_shows_its_people_ships_rooms_budget_and_validity` (line 276) and
  `::test_a_grant_made_in_the_browser_is_stored_signed_and_shown` (line 481) compare whole grant views with `==`. Task
  2 adds `actions` and `made_via` to `_grant_view`, so both fail in Task 2's own Step 4. Add them to Task 2's "Modify
  tests": the first expected view gains `'actions': ['direct'], 'made_via': None` (its grant is made by
  `_insert_grant`, so it has no origin row); the second gains `'actions': ['direct'], 'made_via': 'browser'` (Ruling
  16). Add `peer/tests/test_grants.py` to Task 2's `git add`.
- `peer/tests/test_restore.py::test_every_table_is_either_reconciled_or_named_coordination` (line 1399) asserts that
  every table of a fresh station is in `RECONCILED_TABLES` or `COORDINATION_TABLES` (lines 1387–1396). Task 1 creates
  `member_changes` and `grant_origins`, so it fails from Task 1 on, first seen in Task 4's Step 4. Task 1 adds
  `'member_changes'` and `'grant_origins'` to `COORDINATION_TABLES`, and adds `tests/test_restore.py` to its Step 4 run
  and `git add`. Task 8, whose step reads `member_changes`, moves `'member_changes'` to `RECONCILED_TABLES` and lists
  `peer/tests/test_restore.py` in its files.

**P2. Task 10: the refusal assertion can't pass.** `handle` returns `f'station error: {exc}'`, and `StationError`
renders as `f'{status}: {message}'` (`agent/superyak_agent/station.py:73`); every other tool test expects the status
(`test_breakout_tools.py:92`, `test_board_tools.py:159`). In `test_add_and_remove_report_what_the_station_did`, the last
assertion becomes:

```python
    assert call(tools_for(fake), 'station_remove_member', room=new, member='jenn') == (
        'station error: 403: Jenn moderates this room too; only Andy can remove a moderator', True)
```

**P3. Task 6: add T3's "the reverse" and pin `NO_ACTION`'s remove text.** T3 lists "an add under a remove-only grant,
and the reverse", and the self-review table maps T3 to Tasks 5 and 6, but no test makes a non-self removal under an
add-only grant. `Grant #a1b2 doesn't let you remove members` is then pinned nowhere, against Global Constraints. Append
to Task 6 Step 1:

```python
def test_a_removal_under_an_add_only_grant_is_refused_and_writes_nothing(city):
    """T3, the reverse of Task 5's remove-only case: only self-removal ignores the grant's actions (R-S4)."""
    c = city
    grant = moderate(c.store, c.andy, c.jenn, c.room, actions=['add_member'])
    jenn, before = login(c.app, 'jenn'), snapshot(c.store)
    refused = drop(jenn, c.room, c.doctor['id'])
    assert (refused.status_code, refused.json()['error']) == (403, f"Grant #{grant[:4]} doesn't let you remove members")
    assert snapshot(c.store) == before
```

**P4. Task 12 Step 8: restart every affected unit.** Replace the restart and check with:

```bash
for unit in lighthouse door ship odo wormhole; do systemctl --user restart superyak-$unit; done
sleep 5
for unit in lighthouse door ship odo wormhole; do printf '%s ' superyak-$unit; systemctl --user is-active superyak-$unit; done
for unit in $(systemctl --user list-units --plain --no-legend 'superyak-ship-*' | awk '{print $1}'); do systemctl --user restart "$unit"; done
systemctl --user list-units --plain --no-legend 'superyak-ship-*'   # each active running; none is fine
curl -fsS http://127.0.0.1:7435/api/health && journalctl --user-unit superyak-lighthouse -n 30 --no-pager
```

Expected: five lines ending in `active`, `{"ok":true}`, no traceback. If a unit isn't active, show
`journalctl --user-unit <unit> -n 50 --no-pager`, then revert as the step says. Keep the `make station-rooms` and table
checks that follow.

## Should-fix

**S1. Ruling 15 and Task 8: say "remove rows" and filter on them.** Ruling 15 becomes: "G13 also copies the owner's
and the station's `remove` rows (no grant) whose room and actor are in the copy, so M7's 'Andy removed X' refusal
survives a restore. It only takes power away: a grant-less add is never copied, since it would clear a removal the copy
records." Task 8 Step 3: a row with an empty `grant_id` is copied only when `change='remove'`. Task 8's test docstring
adds: a moderator's add made after the copy isn't copied, because its new room isn't in the copy (the spec's "whose
rooms are here"), so only removals carry a day's budget across a restore.

**S2. Task 7: build `moderating` as Ruling 14 says.** `_moderating` keeps the oldest covering grant for which
`_grant_validity(db, grant, budget=False)[0]` is true, not "unrevoked, unexpired", which also shows a grant check 5
paused. Append to `test_moderating_shows_only_the_callers_own_grant`:

```python
    contact = remote_contact(c.store)  # its own transaction, so before the one below
    with c.store.transaction() as db:  # check 5 pauses every grant on the room: no longer shown
        db.execute('INSERT INTO remote_room_members VALUES(?,?)', (c.room, contact))
    assert mark(login(c.app, 'jenn')) is None
```

**S3. Task 12 Step 7: check main again before merging.** Start the step with
`git -C /home/andy/superyak/.worktrees/room-moderators fetch origin && git -C /home/andy/superyak/.worktrees/room-moderators log --oneline room-moderators..origin/main`.
Expected: nothing. Otherwise go back to Step 1, rerun Steps 2–3, and post the new head for Serenity before merging.

**S4. Task 12 Steps 6 and 9: state option (b)'s limit.** With the count, post: each listed account can still read and
post in those earlier rooms until it is removed again. In merge 1 the owner's browser can't remove it, because it shows
only on replaced rooms, whose Remove now answers 409 `REPLACED_REMOVE`. `DELETE /api/chats/<current room>/participants/<id>`
by the owner, or a moderator's `station_remove_member`, takes it out of the whole chain. A sweep is Andy's call.

**S5. Tasks 3 and 4 Step 4: run the browser tests that drive these routes.** Add
`tests/test_browser.py -k "participant or remove or replaced or carry"`. The browser suite runs on the Pi, posts to
both routes and renders the room's messages, which now include the station's notice; today it first runs in Task 12.

**S6. Task 1: make T6's build check bite.** The moderate grant's `targets` is `[]`, so `_spendable_grant` skips it
before reaching `'direct' not in actions`. In `test_a_moderate_grant_is_a_depth_0_root_that_never_builds`, before
`issue_ticket`, set its targets by hand (validity doesn't check the signature):

```python
    with c.store.transaction() as db:  # by hand: only the action keeps it from building
        db.execute('UPDATE grants SET targets=? WHERE id=?', (json.dumps([c.rio['id']]), grant))
```

**S7. Pin the Fixed texts that no test pins.** ADDED with three names (Task 3: the owner adds Tardis, Kestrel and the
pending Root, `Andy added Tardis, Kestrel and Root to this room. It continues room {c.room[:6]}.`); the notice's
`1 claim was released.` (Task 4: a removal releasing one claim); and Task 9's
`Ended grant #a1b2. It covers no current room, so no room was told.` (fork the chain by hand before
`station-unmoderate`, as Task 1's fork test does).

**S8. Step 2 of Tasks 5 and 10: name the tests that already pass.** Task 5: `test_moderating_adds_no_brief_or_grant_power`
and the `replaced`, `none`, `direct`, `elsewhere` and `named` cases. Task 10: `test_watcher_runs_have_no_member_tools`.
Each is a pin, so a green there is expected, not a wrong test.

**S9. Task 12 Step 4: name the behaviour changes for Serenity.** Besides the link to Rulings 1–20, list the rulings
that change merged behaviour beyond the spec's text: 1 (station-bridge and station-add-ship in one transaction), 9
(a non-owner's 409 before the 403; it overrides the docstring of `test_adding_members_to_a_replaced_room_is_refused`,
her work-board final review F2, and pre-merge leftovers now learn a room was replaced), 10 (the owner's `NO_ONE_NEW`
and 404), 14 (spent grants in `moderating`), 15 (removal rows without a grant in G13's copy) and 16 (`made_via` on
direct grants). Correct Ruling 9's text to cite that docstring rather than work board 8.4.

## Nits

1. **Ruling numbers.** The brief that commissioned this review cited Rulings 2, 7 and 13 for what the plan numbers 1,
   9 and 15. Cite rulings by number and title in the Step 4 post.
2. **Task 5 `_moderator_add`:** "look the account up by username or id" gives one route two meanings. Look up by id
   only on the person route and by username only on the ship route, as `ship_remove_member` already does.
3. **Task 7 `_grant_changes`:** say `ORDER BY created DESC, rowid DESC`; rows at one clock tick are common.
4. **Task 4, `test_adding_members_carries_open_items_and_leaves_the_record`:** the change to `claims(...) == []` drops
   the pin "a claim whose holder isn't in the new room stays behind" (work board mutation check 13), still reachable
   for pre-merge claims. Remove Defiant by hand there too, as the next test does, and keep `== ['build:left']`; Task 4's
   own chain test pins M8's release.
5. **Task 3 `_station_add`:** it turns "any 409 but `REPLACED_ADD`" into the brief's message. With `_add_members` now
   raising `NO_ONE_NEW` 409, match `_brief_to_carry`'s own message instead.
6. **Task 7:** add forged `moderators` and `moderating` to `extra` in
   `test_federation.py::test_a_paired_peer_cannot_send_a_station_author_claims_or_extra_fields`.
7. **Task 2 actions check:** test membership before duplicates, so an unhashable item (`[['add_member']]`) is a 400,
   not a 500; add it to the actions cases.
8. **Task 12 Step 6:** the query reads `room_members` only. Say remote contacts aren't listed, or union
   `remote_room_members`.
9. **Task 10 add result:** "a new room that continues {old} with the same title, owner and members" — it has one more
   member. Say "with the same title and owner".
10. **For merge 2's plan and Step 9:** until merge 2, the Grants page shows a moderate grant as a grant with no ships,
    and its Revoke ask talks about builder runs; the add dialog still says "The new room starts with no messages."
    Mention the first in the announcement.

## Declined to judge

- Section 10's question (membership notices crossing the bridge) is Andy's.
- Law section 5's intent for ship moderators pairing sibling ships, as the spec's section 9 says.
- Merge 2 (the browser), which gets its own plan.
- Whether the Pi's test runs pass: I ran no tests.
