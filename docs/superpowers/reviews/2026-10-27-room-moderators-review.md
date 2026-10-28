# Review: room moderators spec, revision 1

Spec: `docs/superpowers/specs/2026-10-27-room-moderators-design.md`, branch `room-moderators-spec` at 417b4d31, built on
`main` 60dd851. Reviewer: a fresh reviewer agent under station law section 3 (D8). I took no part in writing the spec.
This review is read-only. I ran no tests and changed no file except this one.

Read against: `docs/station-law.md`; CLAUDE.md's bridging and approval rules; spec A
(`2026-10-08-instruction-layers-and-grants-design.md`); grants step 3 (`2026-10-15-grants-step3-design.md`); and, in
this worktree, `peer/superyak_peer/grants.py`, `ships.py` (`station_bridge`, `_earlier_bridged`), `chats.py`
(`add_participants`, `remove_participant`, `send_message`, `list_rooms`), `breakouts.py` (`leave_breakout`,
`close_breakout`, `_shares_current_room`), `briefs.py` (`_brief_to_carry`), `room_board.py` (`_carry_board`),
`room_claims.py` (`release`), `system_author.py`, `tickets.py` (`_spendable_grant`), `agent/superyak_agent/mcp.py`,
`runs.py`, `install.py` (`run_mcp_config`), `wormhole.py`, and `team/superyak_team/workers.py`
(`claude_sandbox_settings`).

## Verdict

**APPROVE WITH CHANGES.** There are 3 must-fix findings, 12 should-fix findings and 12 nits.

The core design matches what Andy asked for, and it is safe:

- the grant is a signed, expiring, revocable `grants` row that never builds;
- the room's owner stays the owner of every room that follows;
- acts go one account at a time, with a budget and a notice for each;
- Wormhole, remote contacts and new accounts stay out of a moderator's reach;
- ships act only through structured tools in sessions.

I checked M18's claims against the code, and they hold. Watcher runs get no station server, both run settings deny
`mcp__station`, read-only runs have no Bash, and the builder sandbox denies reading `$HOME` outside its scopes.

Three gaps block approval:

- the owner's removal does not clearly revoke a moderator's grant, so another moderator's re-add revives it;
- passing the grant on (M6) widens authority as written, and the spec A rules it cites refuse it;
- a removed member stays a full member of every earlier room in the chain.

## 1. Does it give Andy what he asked for?

Mostly. Andy said: "make it so that you can assign someone like I assign you to also have permissions to add or remove
people. like mods."

- **Adding:** fully delivered. M7 follows the station's add-member rule, always carries the brief and the board, keeps
  the owner as owner, and the grant follows the new room (M4).
- **Removing:** delivered only in part. The removal works in place, as the owner's does today. But the removed person
  stays a member of every earlier room in the chain. There they can still post to the same people and mention their
  ships (must-fix 3).
- **"Like I assign you":** M3 and section 7 cover this. The first use gives Rio Grande the grant, and Rio Grande acts at
  Andy's terminal.
- **A person moderator:** a person like Jenn has only the API until merge 2 adds the browser. The build order says so;
  Andy should know that Jenn can't use it in practice until merge 2.

## 2. Can it widen authority beyond the owner's?

- **Delegation chains: yes, as written.** M5's budget check counts only a grant's own `moderations` rows. A
  moderator with `depth` 1 can therefore pass several children on, each with a full budget, and the parent is never
  charged for them. M6's "another member" also admits other people's ships, against M3's own reason. Must-fix 2.
- **Text from another agent, or a watcher run: no, within the stated limits.** Runs have no station tools. I checked
  `run_mcp_config`, `RUN_MCP_DENY` in both settings and the sandbox `denyRead`. Nothing in the code parses text into an
  act. The remaining bar is the session's tool descriptions, which the spec doesn't write out (should-fix 5).
  Separately, spec A step 5 gives builder runs a `station_grant` tool, which could pass a moderate grant on from a run
  once `delegable` includes it (folded into must-fix 2).
- **A removed moderator who keeps acting: yes, through the owner's path.** M8 revokes on "removing someone", but only
  in the moderator's section. If the owner's own removal doesn't revoke, M5 check 5 only pauses the grant, and any
  moderator's later re-add revives it. Must-fix 1.
- **Room replacements: correct.** M4 uses `_current_room` (forward walk, `None` at a fork), and M5 requires the root's
  issuer to own the current room. T4 pins both. One builder note: `_current_room` returns `None` for a room that is
  already current, so coverage is "the room itself if current, else `_current_room`".
- **Removing the owner, bridging, making public: no.** M8, M9, M10 and M11 hold, and Wormhole is refused both ways.
  There is one gap: "no remote members" is checked only when the grant is made (should-fix 2).
- **The owner's other powers: no.** A moderator can't read the brief's history, revoke grants or change the brief
  through this grant.

## 3. The station's add-member rule, and removal

Adding fits the rule exactly:

- a new linked room, owned by the owner;
- the brief, read in the same transaction (`_brief_to_carry` with the current revision, so there is no race);
- the open board items through `_carry_board`, whose claims follow because every old member is in the new room;
- the old room takes no more adds.

Removal in place is today's behaviour, but it isn't sensible as a moderator's tool. `send_message` has no check for a
replaced room, and `list_rooms` still lists replaced rooms to every member. So the removed member keeps posting in
room X, every remaining member still sees X in their list, and ships there still answer the removed member's mentions
with read-only runs. The precedent for a fix already exists: `station-unbridge` takes Wormhole out of the earlier rooms
for exactly this reason (`_earlier_bridged`). Must-fix 3.

## 4. Transparency and the record

These are good:

- each act posts one notice, through `safe_line`, in the act's transaction;
- moderators are listed for members by name;
- grants are signed;
- the owner sees every grant in the chain (G11, root issuer).

These are missing (should-fix 4):

- nothing tells the room when someone is made a moderator or stops being one;
- the `moderations` table has no read path, not even for the owner;
- a grant made by `make station-moderate` is recorded with Andy as issuer and no sign that a ship's session ran the
  command on the Pi. Rio Grande can be both the operator and the grantee.

## 5. Can a builder build it as written?

Merge 1 can be built once the must-fixes and should-fixes 2, 5, 6, 8 and 9 are answered. Merge 3 (M6) can't be built
as written: it names no route, and spec A's rules refuse it (must-fix 2). The details a builder will trip on are listed
below.

## Must-fix

**MF1. Every removal must revoke the removed account's moderate grants, including the owner's removal (M8, M5, T5).**

- The spec says (M8, under "What a moderator can do"): "Removing someone revokes their `moderate` grants on the room
  (signed, reason `removed from the room`)."
- M5 says: "Check 5 asks that the root's issuer still owns the current room and the holder is still in it."
- T5 says: "Removing a moderator revokes their grant, signed; grants below it then fail."
- The problem: today's owner path (`remove_participant`) never touches grants. If it stays that way, Andy removing Jenn
  only pauses her grant. Rio Grande, as a peer moderator, can then add Jenn back (M7 allows any active person). The new
  room is covered through M4, Jenn is in it again, and her grant is valid again. This is the case M8 itself rules out:
  "otherwise one moderator could undo the owner's choice of another."
- Fix: state that every removal path revokes, signed, the removed account's moderate grants that cover the room. That
  means the owner's browser route, the moderator's routes and any later route. `revoked_by` is the remover. Add tests:
  the owner removes a moderator and the grant is revoked; a re-add by another moderator doesn't revive it.

**MF2. Passing it on (M6) widens authority as written, and the rules it cites refuse it (M6, M5, M1, section 6).**

- The spec says (M6): "under spec A's child rules: same room, an end no later, a lower depth, a budget no larger. A
  person passes it to another member or to her own ship."
- It also says (M5): "Check 4 counts the grant's `moderations` rows in the last 24 hours."
- The problems:
  - (a) A `moderations` row names one grant, so a parent's count never includes its children's acts. Spec A's
    invariant is "N builds under a child also count against the parent", met by "one `budget_uses` row for every
    link". Here, a depth-1 moderator with a budget of 10 who makes five children of 10 each gets 60 changes a day.
  - (b) "another member" includes other people's ships and residents. M3 refuses those as root holders: "a grant in
    Jenn's ship is power for Jenn".
  - (c) Spec A's child rules refuse a moderate child. G7's `delegable` is `["direct"]`, and spec A bounds `delegable` to
    a subset of `{direct}`. G9 check 3 requires "its actions must be in `delegable` (for links issued by ships)". Spec
    A's children are issued only by ships, through `POST /api/grants/delegate`. Section 6 names no route that a person
    or a ship would use to pass the grant on.
  - (d) Once `delegable` includes moderate, step 5's builder-run tool `mcp__ticket__station_grant` would let a run pass
    the grant on. That contradicts M18 and the ships' answer to open question 1.
- Fix, either way:
  - **Specify M6 fully:**
    - charge every link (count `moderations` rows under any descendant, or write one use row per link);
    - restrict grantees as M3 does (a person who is a member, or the passer's own member ship);
    - amend G7 and spec A's `delegable` bound for the moderate action;
    - name the route for people and for ships;
    - say that run tools never pass on a moderate grant;
    - add spec A's property test (a child is never wider, field by field) and a chain-budget test.
  - **Or cut M6:** fix `depth` at 0, drop it from `POST /api/grants/moderate`, and leave passing on to a follow-up spec.
    Merge 1 doesn't need it.

**MF3. A removal must actually take the member out of the room's conversation (M8, section 9).**

- The spec says (M8): "Remove in place, exactly as the owner's removal does; no new room." Section 9 says: "Removal
  isn't erasure: earlier rooms' history and copies stay".
- The problem: the removed member stays a full member of every earlier room in the chain. In City of AI that is many
  rooms. `send_message` accepts their posts there, `list_rooms` shows those rooms to every remaining member, and
  `issue_ticket` runs read-only answers to their mentions of member ships, at those ships' owners' model cost. "Like
  mods" removal that leaves a working side channel to the same people isn't removal. The spec's limit line describes
  history, not continued posting.
- Fix: pick one, and test it.
  - (a) A removal also takes the member out of the earlier rooms in the chain that have the same owner, as
    `station-unbridge` does for Wormhole (`_earlier_bridged`).
  - (b) Replaced rooms take no new posts from anyone, matching the board's existing rule that "a replaced room takes no
    changes". History stays readable, so removal still isn't erasure. This is simpler and covers the owner's removals
    too.
  - If the ships keep today's behaviour instead, section 9 must say plainly that a removed member can keep posting to
    the same members in earlier rooms. That has to be posted to Andy as a choice, because it changes what "remove"
    means to him.

## Should-fix

**S1. A moderator can undo the owner's removal of an ordinary member (M7, section 9).**

- The spec says (M7): "Add a person or ship already on this station."
- Once MF1 is fixed, a moderator's grant can't be revived. But a person Andy removed can still be re-added by any
  moderator the next minute. M8 reasons against one moderator undoing the owner's choice, and the same reasoning
  applies here.
- Fix: either refuse a moderator re-adding an account that the owner removed from this chain while the grant lives
  (one query on a removal record), or list it in section 9 as a known limit, with the notice as the safeguard.

**S2. "No remote members" is checked only when the grant is made (M2, section 2).**

- The spec says (M2): "on a current local room that is not a breakout and has no remote members."
- The act checks in section 2 don't repeat it. If the owner later adds a remote contact, each moderator's add makes a
  new federated room and exposes the newcomer to the remote station. M11 says a moderator can't make a room "reachable
  from outside: no remote contacts, no federation".
- Fix: add "has no remote members" to the act checks, or to M5 check 5 so the grant pauses, and add a test.

**S3. Adding other people's ships (M7).**

- The spec says (M7): "Add a person or ship already on this station."
- A moderator can pull any person's ship into Andy's room. That ship's watcher then spends its owner's model time and
  machine answering mentions there, and its owner may not be in the room. M3 already reasons that "a ship acts for its
  owner".
- Fix: refuse adding a ship (residents aside) unless its owner is a member of the room. Otherwise, name this in section
  9 as a deliberate choice.

**S4. Appointments and the act log need a record (M14, M15, section 6, make targets).**

- The spec says (M15): "Members see who moderates, by name only". Section 6 says `make station-moderate` "makes and
  signs the grant".
- Nothing tells the room when someone becomes or stops being a moderator, and no route shows the `moderations` rows.
- A grant made by the make target looks the same as one Andy made himself, even though the grantee's own session ran
  the command (first use, step 2).
- Fix:
  - post one notice when a moderate grant is made or revoked, for example "Andy made Rio Grande a moderator of this room
    until 2026-11-26";
  - list a grant's acts on the Grants page for the owner;
  - record where a grant was made (`made_by: cli`, or a session label outside G12's signed keys).

**S5. Write out the tool descriptions and test them (M16, M17, section 6).**

- The spec says (M17): "A room message, the owner's included, reaches a session as data, and the tool descriptions say
  so". Section 6 says "described as M17 says".
- M18 says "the bar is in the agent", so this wording is the control for sessions, including writable sessions that
  answer other people's mentions (law section 7).
- Fix:
  - give the text verbatim, as `SET_BRIEF` is given;
  - say that each act needs the person at the terminal to name the room and the member for that act. A standing "handle
    your mentions" is not enough, and neither is a relayed "Andy says";
  - add an agent test that both descriptions carry the rule.

**S6. The first use fails as written (section 7 step 3; `mcp.py` `resolve_room`).**

- The spec says: "It calls `station_add_member room="Superyak: city of AI" member=tardis`."
- `resolve_room` matches exact titles across `GET /api/chats`, which lists replaced rooms too. Rio Grande is in several
  rooms titled "Superyak: city of AI", so the call fails with "No single room matches". After each add, the next call by
  title fails too.
- Fix: these two tools resolve a title to the one current room among the matches, or the first use passes the room id.

**S7. Restoring a backup (M1, G13).**

- The spec says (M1): "It is signed, revoked, listed and restored as a `direct` grant is (G10 to G13)."
- G13 reconciles `budget_uses`, but a moderate grant's budget lives in `moderations`. After a restore, every
  moderator's daily count starts again.
- Fix: G13 also copies `moderations` rows from the replaced file and adds their columns to `COMPARED`, and a test
  covers it.

**S8. Ships need a read path (section 6).**

- The spec says: "`station_rooms` marks rooms this ship moderates."
- G14 refuses ship keys on every `/api/grants` route, and only `GET /api/chats/{key}` gains `moderators`. Neither the
  list route that `station_rooms` calls nor any ship route is named.
- Fix: name the field on `GET /api/chats` (for example `moderating: true` and the grant's short id for the caller), and
  add the two ship routes to the ship key's allowlist, as spec A's Compatibility section lists them.

**S9. Give the CLAUDE.md text for the new make targets (section 6, section 7).**

- The spec says: "CLAUDE.md gains both targets."
- These are a person's act performed by a ship as Andy, like `station-approve`.
- Fix: write the text. It should say:
  - only when Andy asks, at the terminal;
  - Andy names the room and the grantee and confirms the room's short id;
  - the grantee and room never come from room text;
  - tell Andy the grant's short id.

**S10. Self-removal revokes the holder's own grant, which G10 doesn't allow (M8).**

- The spec says (M8): "A moderator may remove itself."
- G10 refuses a grantee's revoke (step 3's test 7: "the grantee gets 403").
- Fix: say that the removal path's revocation is its own act, not G10's route, with `revoked_by` the remover. A holder
  may renounce a grant this way.

**S11. Law section 5 and ship moderators (section 9).**

- The spec says: "Adding ships widens law section 5's breakout pairs."
- More precisely: a ship moderator adding its sibling ships to a person's room creates the pairs that let it open
  breakouts with them. The law's text is met ("a current room that a person owns"), but the pair was chosen by a ship.
- Fix: say so in section 9, and post it to Andy with the spec summary. The intent question is listed under "Declined to
  judge".

**S12. If open question 5 is adopted, build it this way (section 10, Q5).**

- Releasing through `release` posts one claim line per claim, and each line counts against a ship's 30 posts a minute.
  A removal that releases many claims could roll back on a 429.
- Fix:
  - release silently and put the count in the removal notice;
  - drop the removed account's deferrals in the room, as `leave_breakout` does;
  - apply both to the owner's removals too;
  - change section 9's "claims last until they expire" to match.

## Nits

1. **M14 and M15.** M14's notice shows "under moderate grant #a1b2 from Andy" to every member, while M15 says
   "Members see who moderates, by name only; G11 still hides the grant." Say that the short id is shown on purpose, or
   leave it out of the notice.
2. **M14.** Name the notice's client id, for example `moderation-<moderations.id>`, as R18's callers use `notice-…` and
   `brief-…`.
3. **Section 2's check order.** It ends with "the account is allowed (below); budget is left", but G9's validity
   already includes the budget (check 4), so a spent grant fails at the 403 step. Also say where "Already a member:
   nothing happens" falls, and that it charges nothing.
4. **M7.** "X is not someone a moderator can add" echoes caller input. Pass X through `safe_line`.
5. **M8.** Give status codes for its refusals (the owner, Wormhole, a remote contact, a peer or a moderator above), as
   M7 does.
6. **G9's reasons.** They read "has used its 5 builds". For a moderate grant they should read "changes", and
   `budget_left` should count `moderations`.
7. **M3.** Say "not the owner himself", as G8 step 3 does ("not the caller").
8. **Section 6 API.** `POST /api/grants/moderate {grantee, room, hours, budget, depth}` needs defaults and ranges for
   `hours` and `depth`. Unless MF2 cuts it, `depth` is at most `max_depth` − 1.
9. **`make station-unmoderate GRANT=<short id>`.** Four hex characters can collide. Require at least 4 characters and
   refuse an ambiguous match with 409, as `station-bridge` does.
10. **The optional `grant_id`.** Say which grant is used when it is left out: the oldest valid one covering the room, by
    `created` then `id`, as in G15.
11. **M9 and section 9.** M9 says "or edit the brief (its rules are unchanged)", and section 9 says a moderator "can't
    ... edit the brief". An owner's ship that moderates can still edit the brief under ship briefs. Say "moderating adds
    no brief power".
12. **T6.** `_post_as_system` never records mentions, so "records no mention" passes trivially. Also check that the
    stored text has `(at)` where the name had `@`.

## Open questions

1. **Sessions only, not builder runs: agree.** Builder runs read the room's text and have no person at the terminal
   (law section 7). Keep it that way when step 5 arrives, including for passing the grant on (MF2 (d)).
2. **The owner's changes post the same notice: agree.** One record for every membership change. Use the same text
   without the grant clause. Post it only in the current room: `station-unbridge` also removes Wormhole from earlier
   rooms, and those rooms need no notice. `station-bridge` then announces itself too, which is welcome. Expect some
   tests that count messages after an add to change.
3. **10 a day by default, 50 at most: agree.** It is per grant. Several moderators multiply it, so a total per room (for
   example 50 a day across all moderators) is worth a line, but it is optional.
4. **A moderator may add in a bridged room: agree, with one condition.** The owner bridged the room, and the newcomer is
   an existing station account. Wormhole relays only messages that address a lattice persona, and notices never do.
   The condition: the tool's result and the notice say the room is bridged, so the moderator and the room see that the
   newcomer's addressed posts will reach Stanley's lattice. If Andy counts the lattice as "other people's repos" under
   law section 3, this question is his, not the ships' (see "Declined to judge").
5. **A removal drops deferrals and releases claims: agree,** built as S12 says, for the owner's removals as well.
6. **Separate add and remove scopes, both on by default: agree.** Store them as two action names from merge 1,
   because `actions` is in the signed record (G12) and the child subset rule then narrows by itself. The make target
   and the browser grant both by default. Removing oneself is allowed under either scope. If MF2 is met by cutting
   M6, the split still has its own use (an add-only grant for someone who only invites), so keep it.

## Declined to judge

- **Law section 5's intent.** Whether a ship moderator putting Andy's ships together at his terminal meets the purpose
  of "ones a person already put together" is Andy's to say. The letter of the law is met (S11).
- **Law section 3 and the lattice.** Whether Stanley's aDNA lattice counts as "other people's repos" under section 3.
  If it does, open question 4 stays with Andy.
- **The 720-hour maximum.** Whether it suits moderation is policy. It is spec A's bound, and I didn't question it.
- **Browser copy and layout** for merge 2.
- **Plans and code** for merges 1 to 3, which don't exist yet. Each needs its own plan review, as spec A asks.
- **Membership after a restore.** How room membership itself behaves after a restore belongs to the backups spec.

## Re-check: revision 2 at c71cc09b

Re-checker: a fresh agent under station law section 3. I took no part in writing the spec or in the review above. This
re-check is read-only. I ran no tests and changed no file except this one.

Read against: the spec at c71cc09b, with the diffs 417b4d3..6af7eb3..c71cc09b; the review above; and `main` at
f5368629. On `main` I read `ships.py` (`_owned_room`, `_station_add`, `station_add_ship`, `_earlier_bridged`),
`chats.py` (`add_participants`, `remove_participant`, `_create_room`), `grants.py` (`_grant_policy`,
`_grant_validity`, `_rooms_back`, `_current_room`, `revoke_grant`), `signatures.py`, `system_author.py`, the brief and
ticket notices, `breakouts.py`, `room_claims.py` and `app.py` (`current_user`, `ship_member`, the participants routes).
I also read `agent/superyak_agent/wormhole.py` (`_relay_out`, `SKIP_AUTHORS`), `memos.mentioned`, `mcp.py`
(`resolve_room`), `runs.py`, `team/superyak_team/workers.py` (the builder sandbox) and `test_signatures.py`'s
damaged-identity test. `git diff 3d6d2a4 f5368629 -- peer/` is empty, so the helpers that the spec cites from branch
`station-add-ship` are the ones now on `main`.

### Verdict

**REVISE.** One must-fix remains (R1): one sentence in M19 and one test line. MF1, MF2 and MF3 are closed. With R1
applied, a check of R1 alone is enough. The four should-fixes can be settled in the spec or in merge 1's plan.

### 1. The must-fixes, and whether anything widens a moderator's authority

- **MF1: closed.** M8 is one helper for every removal path. It revokes, signed, every unrevoked moderate grant that the
  removed account holds on the room, with reason `removed from the room` and `revoked_by` the remover. The grant stays
  revoked after any re-add. T5 pins the owner's removal, a self-removal, a re-add by another moderator and a rolled-back
  removal. The review's case (Andy removes Jenn, and Rio Grande adds her back) is now blocked twice: M7 refuses the
  re-add, and her grant is revoked anyway. The revocation is the removal's own act, so G10's `_may_revoke` (issuer or
  target owner only) is untouched. A `revoked_by` left empty signs as `None` in the revocation record.
- **MF2: closed.** `depth` is 0, the route takes no depth, and the policy's `delegable` stays `['direct']`
  (`_grant_policy`). Spec A's delegate rule needs the parent's depth to be above 0 and every action to be in
  `delegable`, so a child is refused twice, step 5's `station_grant` included. G8's `_insert_grant` fixes `actions` to
  `direct`, so the new route is the only way to make a moderate grant.
- **MF3: closed for every removal from merge 1 on.** M8 walks back along `linked_room_id`, as `_earlier_bridged` does.
  That helper already takes any member's id. M8 takes the member out of each earlier room the owner owns and raises its
  epoch, in one transaction with the current room, and posts one notice. T2a pins it. One gap remains: accounts
  removed before merge 1 (R-S2).

What I checked, as the brief asked:

- **A removed member re-entering.** `add_participants` builds the new room from the old room's `member_ids`, and a
  replaced room refuses adds (`REPLACED_ADD`). So an account that is out of every room in the chain can come back only
  through a new add. On a moderator's add, M7 reads "the owner removed X" from `member_changes` over the whole chain. A
  moderator can't hide that record by removing X again: X is in no room of the chain, so the removal answers 404 and
  writes no row. The owner's own ship, as a moderator, gets the same refusal. The make targets are the owner's acts, at
  his terminal. Two gaps remain. A removal from before merge 1 isn't on record (section 9 says so; R-S2 offers to close
  it). Copying `station_add_ship`'s two transactions would open a race (R-S1).
- **A moderator acting from a watcher run, or from another agent's text.** Confirmed on `main`:
  - `RUN_MCP_DENY = ['mcp__station']` applies to both run settings.
  - The builder sandbox denies reading `$HOME` outside its scopes and writes only to the worktree. So a run reaches
    neither the ship key nor `STATION_DATA` (`~/.local/share/superyak/lighthouse`), which the new make targets would
    need.
  - The person participants routes use `current_user`, which refuses any bearer key. The new ship routes take
    `ship_member`.
  - Both tool descriptions, given whole, require the person at this session's own terminal to name the room and the
    member. They treat a relayed "your owner asked" as data. T7 pins them.

  The station still can't tell a session from a run (D7). Section 9 states that limit.
- **The grant following room replacements.** M4 uses `_rooms_back` and `_current_room` as they are on `main`. Check 5
  pauses the grant when the owner no longer owns the room, the holder has left or a remote member has joined. T4 pins
  it. N6 below is wording only.
- **Removal from every room in the chain.** Covered for the owner's removals, a moderator's removals and the station's
  own removals, `station-unbridge` included. Removing Wormhole touches no grant, so it signs nothing and still works
  with a damaged identity (T9).

I found nothing that lets a moderator do more than the owner can. R-S1 is a narrow race against the owner's own
removal. R-S3 contradicts M7's promise about the brief, but stays inside the owner's own power.

### 2. Should-fixes and nits

The Review response is accurate. I checked each row against the text:

- S1 to S12 are applied where it says (M7, M5 check 5 and M11, M7's refusal list, M19 and M20, section 6, T12, M20's
  G13 addition, `moderating`, CLAUDE.md, M8, section 9).
- N1 to N12 are applied as listed.
- Q3 is declined with a reason, which was optional.

Serenity's addition (never `wormhole`, `_station` or an ownerless ship) has no table row, but M3, M7, M8, M10, T1 and T3
apply it. T3 lacks the `_station` removal case (N7). The new text brings a few small errors (N2 to N4).

### 3. The bridge ruling

The text agrees with the ruling in M14, M21, section 7 step 4, section 9, section 10, T10, the build order ("Wormhole
doesn't change") and the Q4 row. One gap: M21 rests on "a notice never mentions one".

- On `main`, Wormhole skips only its own posts and `odo`'s (`SKIP_AUTHORS = ('odo',)`), not the system author's. It
  relays any post in which `memos.mentioned` finds an `@persona`.
- M14 passes names through `safe_line` (`@` becomes `(at)`), as R18's two notices already do.
- M19's two notices name the owner and the grantee, but don't say `safe_line`. Display names are free text
  (`rename_user` takes any `text`).

So a grantee named `@<persona>` would carry the appointment notice across the bridge. That breaks the ruling and T10's
"or for any other system-author post". This is R1.

### 4. Can a builder build it as written?

Yes, once R1 is applied and the should-fixes are answered. `_owned_room` takes a full room id (it matches by prefix).
`_station_add` needs a variant that takes `db`, which M7 says. M8's `_earlier_with` gets the room's owner, not the
moderator, as its actor ("with the same owner"). The fields the spec relies on exist (`grants.revoked_by`,
`claims.released_by`, `linked_room_id` in `GET /api/chats` for T12).

### Must-fix

**R1. M19's notices pass names through `safe_line` (M19, T10).**

- In M19, after "with client id `moderator-<grant id>-revoked`.", insert: "Both notices pass names through
  `safe_line`, as M14's do, so neither mentions anyone or crosses the bridge (M21)."
- Replace T10's second sentence with: "Wormhole writes no memo for a `member-` or `moderator-` notice, or for any other
  system-author post, including an M14 and an M19 notice that name an account whose display name is `@<persona>`; each
  stores `(at)<persona>`."

### Should-fix

**R-S1. Run every check in the act's transaction (M7, section 2).** `station_add_ship` makes its refusals in one
transaction and calls `_station_add` in another. If a builder copies that, an owner's removal that lands between the two
lets the moderator's add put the member back, against M7. Add to M7's transaction paragraph: "Section 2's checks, M7's
refusals included, run in that transaction too. Only `_owned_room`'s read of the brief revision may come before it."

**R-S2. Accounts removed before merge 1 (M8, section 9).** Today such an account is still a member of the earlier rooms.
It can post there until someone removes it again. M7 can't see its removal either. Choose one:

- (a) Merge 1 runs a one-time sweep. For each current person-owned room, every account that is in an earlier room of
  its chain but not in the room itself is taken out through M8's helper, recorded with `actor_id` empty. Only an owner
  could remove a member before merge 1, so M7's "by the station for him" then refuses a moderator's re-add, which also
  closes section 9's limit. The sweep changes live rooms, so it follows the plan's deploy gates.
- (b) Section 9 states the first half: until someone removes such an account again, it keeps posting in the earlier
  rooms.

**R-S3. A moderator's `carry_brief` (section 6, M7).** `POST /api/chats/{key}/participants` lists `carry_brief?` among
the fields that take a moderator, and today's route passes it to `add_participants`. If a builder honours it, a
moderator could drop the brief, against M7's "a moderator can never drop the owner's statement of purpose". Add: "On a
moderator's add the route ignores `carry_brief`; M7 carries the brief at the revision `_owned_room` read."

**R-S4. Self-removal and check 3 (section 2, M8).** As written, check 3 requires "this act's action" and a budget left,
and the first failure answers. That refuses the self-removal that M8 and T3 allow "under either action". Add to check 3:
"A moderator removing itself needs only a grant that covers the room, has either action and is valid as G9 says, with
check 4 skipped (`budget=False`), since the removal ends the grant (M8)."

### Nits

1. **The header, Today and the build order** say `station-add-ship` isn't on `main` yet. It merged at f5368629, so
   the base can name it.
2. **Section 7 is out of date.** The ships' notes say Tardis joined City of AI on 2026-10-27 (room 00bcfc replaced
   39fd79). If so, step 3 now answers 409 "already a member". Name a member who isn't in the room, or write "the
   member Andy names".
3. **M14's third example can't happen.** A moderator can't remove Jenn while she moderates (M8). Make it "Andy removed
   Jenn …", or drop the sentence about the revoked grant.
4. **The "another moderator" refusal in M8 counts an expired grant** that was never revoked. Yet M19 says the moderators
   list stops showing an expired holder. The refusal is safe, since it only narrows, but say which way it goes, so that
   the 403 and the list agree.
5. **`make station-unmoderate` should match moderate grants only.** As written, "more than one of `APPROVER`'s grants"
   also matches `direct` grants, and it posts M19's notice. It signs a revocation, so it needs a signing store, as
   `station-moderate` does.
6. **M4 describes coverage two ways,** and they differ only at a fork. `_rooms_back` from either branch reaches the
   listed room, so both branches would be covered, while `_current_room` covers neither. T4 settles it. Say that the
   forward test is the rule.
7. **T3 lacks the `_station` removal case.** Add `_station` on a removal (404, M8).
8. **Breakouts.** Say that `leave_breakout` and `close_breakout` keep their own paths, with no `member_changes` row and
   no M14 notice. M8's "any later path that deletes a `room_members` row" and M14's "by anyone" otherwise leave that
   open.

### Declined to judge

- Section 10's question is Andy's.
- Whether R-S2 (a)'s sweep needs Andy's word before deploy is for the plan's deploy gates.
