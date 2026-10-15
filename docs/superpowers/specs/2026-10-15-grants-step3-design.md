# Spec A step 3: grants a person can spend, and station signatures

Status: draft for review. Under the station law (section 3, D8), a fresh reviewer agent approves this spec in Andy's
place, and its summary and decisions are posted in "Superyak: city of AI". Andy can veto anything.
Base: `main` (6623845). Roadmap item 2.2 (`docs/superpowers/plans/2026-10-12-station-roadmap.md`), claimed by
Serenity as `build:grants`; Rio Grande reviews each merge under section 2.
Amends: [spec A](2026-10-08-instruction-layers-and-grants-design.md) (approved 2026-10-08), its build order step 3
("Grants and chains") and the parts of its sections 2, 4 and Plurality that step 3 builds. Where this spec is
silent, spec A holds.
Evidence: [the survey](2026-10-15-grants-step3-survey.md), which maps spec A's step 3 onto the code at 7094b5b with
file and line references. This spec cites it as "survey 3.2" and so on.

## Goal

Today only a ship's owner can make it build: Andy's own mention of Rio Grande runs as builder, and every other
mention runs read-only (`tickets.py` `_mode_for`). The station law Andy signed already expects the next step: "Your
owner's own mention runs as builder ... (once grants exist, so may a person's mention under a valid direct grant)"
(`docs/station-law.md`, section 1).

Step 3 builds that next step and nothing that would sit unused:

- Andy grants another person, for example Jenn or Stanley, the right to direct some of his ships in some rooms, for
  some hours, with a daily budget of builds.
- That person's mention of one of those ships then runs as builder, with a footer that says so: `Builder for Andy,
  via Jenn · grant #a1b2`.
- Andy sees his grants on a page, and revokes one at any time. A revoke takes effect at the next ticket.
- The station signs every grant, every revocation and every instructions revision with its Ed25519 key, so each
  record can be checked against the station's card. The active station law is signed too.

## Why the scope is narrower than spec A's step 3 (measured)

Spec A's build order puts all of these in step 3: browser roots, delegation, validity under the policy defaults,
budgets, `instruct` grants between people, signatures and the grants page. The survey (section 4) checked what each
part does if step 3 ships alone, before the charter (step 4) and directs (step 5) exist:

| Part | Alone in step 3 | Moved to |
| --- | --- | --- |
| `direct` roots to a person, spent by a ticket (spec A's basis 3), budgets, revoke, the page | The one part a person can use: someone else's mention builds your ship, within scope and budget. | stays in step 3 |
| Signatures over grants and instructions revisions | Provenance with no reader yet. Cheap, and grant rows need a signature anyway. | stays in step 3 |
| `direct` grants to a ship | A ship spends a `direct` grant only through directs (spec A section 3). Ship text never builds. | step 5 |
| Delegation (`POST /api/grants/delegate`), acceptance by another owner, the `ticket_id` rule, `confirm: each`, the ship routes `/api/ships/me/grants*`, the tools `station_grant` and `station_grants`, the status line, a session label on grants | Each acts on grants held by ships, so each would be untested by use until directs exist. | step 5 |
| `instruct` grants between people, `grant_pins`, pins and follow, pending revisions, line diffs, caps checked at grant creation, bracketed titles | Useful, but it is most of the machinery step 4's charter acceptance needs (an acceptance is itself an `instruct` grant, spec A section 1). Building it twice costs more than building it once. | step 4 |

So step 3's grantee is always a person, and every grant in step 3 is a root that a person makes in the browser.

## Decisions

Each line is this spec's ruling. A fresh reviewer checks it; Andy can veto any of them.

| # | Topic | Ruling | Why |
| --- | --- | --- | --- |
| S1 | Scope | Step 3 delivers `direct` roots from a person over that person's own ships to another person, spent by ticket basis `grant`, with budgets, revoke, the grants page and station signatures. | The one part useful before steps 4 and 5 (table above). The active law expects it. |
| S2 | Ships as grantees | Moved to step 5 with delegation, acceptance, `confirm: each`, the `ticket_id` rule, the ship routes, the tools, the status line and the session label. | First spent by directs. |
| S3 | `instruct` grants | Moved to step 4 with pins, follow, pending revisions, diffs, caps at grant creation and bracketed titles. | Shares its machinery with charter acceptance. |
| S4 | Room-scoped grants | Not in step 3, and not in spec A. A grant such as `board` or `brief` (work board spec, ship room briefs spec) scopes a room the issuer owns, not ships, so it needs its own spec. | Different shape. |
| S5 | A room replaced by a new linked room | A grant that names room X covers the current room that replaced X, following `linked_room_id` forward. It never covers a replaced room, X included. | Adding a member or bridging makes a new room id (`chats.py` `add_participants`; survey 3.2). Briefs, open board items and claims already carry forward. Without this, Andy bridging a room would silently end every grant in it. |
| S6 | Old and answered mentions | A grant build needs a mention posted no earlier than the grant was created, at most 24 hours before the ticket, and not yet answered by the ship. Otherwise the ticket is `read`. Owner builds are unchanged. | HANDOFF's parked note: once acts spend build tickets, the station must refuse old or answered messages (survey 3.13). A grant must not reach back to words written before it. |
| S7 | What the station signs | Grant records, revocations and instructions revisions, each with the station's peer id inside the record. A revision's record also carries its audience. A revocation's signature gets its own column. | Spec A's records name no station for grants and no audience for revisions (survey 3.8). Rows never change except the revocation fields, so the revocation signature needs somewhere to go. |
| S8 | Policy with no charter | One function returns spec A's no-charter defaults. Step 3 reads two of them: 720 hours at most for a grant, and 20 grant builds per ship per day. A root's budget is 1 to 500 builds a day, and its depth is 0. | Step 4 swaps the charter in behind the same function. A budget of 0 could never be spent. Depth only matters once delegation exists. |
| S9 | Restoring a backup | With a usable replaced file, the reconcile revokes every grant revoked there and adds the budget uses recorded there. Without one, it revokes every grant, with reason `restored`. | A restored copy must not bring back a revoked grant or a spent budget (backups spec S16, survey 3.14). |

## 1. Signed instructions revisions (merge 3a)

The station already has an Ed25519 identity per data directory (`identity.py`), and today it signs only federation
envelopes. This merge gives the store a signer and signs instructions revisions. It has no grants.

- **G1.** `revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL,
  PRIMARY KEY(layer_id, revision))`.
- **G2.** When a layer of `kind: "instructions"` gets a new revision (activation, or the narrowing that makes a new
  revision), the station signs the revision record in the same transaction:
  `{station, layer_id, revision, owner_id, title, body, audience_users, policy, created}`. `title`, `body` and
  `audience_users` come from the revision's stored snapshot, `created` from `layer_revisions.created`, `station` is
  this station's peer id, and `policy` is `null` until step 4. Other kinds of layer are not signed.
- **G3.** The signature is over `identity.canonical(record)`, as federation envelopes are. `PeerIdentity` gains
  `sign_record(record)`, and the module gains `verify_record(card, record, signature)`, which checks against a
  station card and returns a bool. It never raises on bad input.
- **G4.** The store loads the identity from its own data directory, once, as `_own_peer_id` already does
  (`peer_store.py`). A load that fails is not cached.
- **G5.** At startup, every instructions revision without a signature is signed once, from its stored snapshot.
  The active station law (layer c879372542444e4c8f95f2c0db69f8fb) is one of them. A second start signs nothing.
- **G6.** `GET /api/layers/{id}/revisions/{n}/signed` (person) returns `{station, record, signature}` to the layer's
  owner, or to a person who owns a ship in that revision's `audience_users`. Anyone else gets 404, so the route
  never says whether a layer exists. A ship key gets 403.

## 2. Grants: making, checking, revoking, reading (merge 3b)

```sql
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES users(id),
  grantee_id TEXT NOT NULL REFERENCES users(id), actions TEXT NOT NULL, targets TEXT NOT NULL, rooms TEXT NOT NULL,
  expires REAL NOT NULL, budget INTEGER NOT NULL, depth INTEGER NOT NULL, confirm TEXT NOT NULL,
  parent_id TEXT REFERENCES grants(id), charter_layer_id TEXT, charter_revision INTEGER, follow INTEGER NOT NULL DEFAULT 0,
  created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL,
  revocation_signature TEXT);
CREATE TABLE IF NOT EXISTS budget_uses(grant_id TEXT NOT NULL REFERENCES grants(id), ticket_id TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS budget_uses_by_grant ON budget_uses(grant_id, created);
```

This is spec A's table with one added column, `revocation_signature` (S7). The columns steps 4 and 5 use
(`parent_id`, the charter columns, `follow`) are there now, so those steps add no migration. In step 3, `actions` is
`["direct"]`, `depth` is 0, `confirm` is `none`, and `parent_id`, the charter columns and `follow` are empty.
Rows never change, except that revoking fills `revoked`, `revoked_by`, `revoke_reason` and `revocation_signature`.

- **G7. The policy.** `_grant_policy(db)` returns spec A's no-charter defaults: `max_depth` 3, `max_expiry_hours`
  720, `agent_grant_default_hours` 24, `builds_per_ship_per_day` 20, `delegable` `["direct"]`, and an unrestricted
  grantee set. Every check below reads the policy through this one function.
- **G8. Making a grant.** `POST /api/grants {grantee, targets, rooms, hours, budget}` (person, CSRF). The caller is
  the issuer. The station refuses it with a plain reason unless all of these hold:
  - `grantee` is a person on this station (not a ship, the system author or an account awaiting activation), and
    not the caller (400);
  - `targets` lists 1 to 20 distinct ships whose owner is the caller (400; a resident ship has no owner, so it never
    qualifies);
  - `rooms` is `"*"`, or a list of 1 to 20 distinct room ids. Each must be a local room (no `:` in its id) that is
    not a breakout and not replaced, and the caller must be a member. A room the caller is not in gets 404, so a
    grant never confirms that a room exists;
  - `hours` is a whole number from 1 to `max_expiry_hours`; `expires` is now plus that many hours;
  - `budget` is a whole number from 1 to 500.

  The station then inserts the row, signs it (G12) and returns the grant as G11 shows it.
- **G9. Validity** of a grant at time t is a walk from the grant to its root, so step 5 only adds links. In step 3
  every grant is its own root. A link is valid when all of these hold, and the first that fails is the reason:
  - it is not revoked: "Grant #a1b2 was revoked by Andy";
  - it has not expired: "Grant #a1b2 expired 2026-10-20 14:00 UTC";
  - its lifetime fits the policy in force now (`expires − created ≤ max_expiry_hours`), so narrowing the policy
    later takes effect at the next check: "Grant #a1b2 lasts longer than the station now allows";
  - fewer than `budget` builds were charged to it in the last 24 hours: "Grant #a1b2 has used its 5 builds for
    today";
  - the root's issuer still owns every target: "Andy no longer owns Rio Grande". Ownership never changes today, but
    a restored or hand-edited database could change it.

  A grant's short id is `#` followed by the first 4 characters of its id, as in spec A's footers. Names in reasons
  are the station's own, made safe as in `safe_line`.
- **G10. Revoking.** `POST /api/grants/{id}/revoke {reason}` (person, CSRF). Allowed for the issuer, for the issuer
  of any grant above it (none in step 3, but the walk is the same), and for the owner of any target ship. Being an
  admin gives no power over other people's grants. A person who may not see the grant gets 404; one who may see it
  but not revoke it gets 403; a grant already revoked gets 409. `reason` is optional, one line, at most 200
  characters, and defaults to `revoked`. The station signs the revocation (G12).
- **G11. Reading.** `GET /api/grants` (person) lists the grants the caller issued, holds, or that cover their ships,
  newest first. Each shows: `id`, `short`, the issuer and grantee (id and name), the targets (id and name), the rooms
  (`"*"`, or id and title for each), `expires`, `budget`, `budget_left`, `created`, the revocation fields, `valid`,
  and `reason` when it is not valid. Room titles and names come from people, so the web app escapes them.
- **G12. Signatures.** A grant's record is every column except `signature` and the four revocation columns, with
  `station` added. A revocation's record is `{station, grant, revoked, revoked_by, reason}`. Both are signed as G3
  says. `GET /api/grants/{id}/signed` (person; anyone G11 shows it to) returns `{station, record, signature}`, plus
  `revocation: {record, signature}` once it is revoked. At startup, a revocation without a signature is signed once
  (the reconcile in G13 writes revocations without one).
- **G13. Restoring.** `station-restore-reconcile` gains grants:
  - with a usable replaced file, every grant revoked there is revoked here with the same time, person and reason,
    and every `budget_uses` row there for a grant in both files is added here if missing;
  - without one, every grant not yet revoked is revoked, with reason `restored` and no person;
  - `grants.id`, `grants.revoked` and `budget_uses.grant_id` join `COMPARED`.

  The report counts both. A grant made after the copy was taken is gone after a restore, and its issuer makes it
  again.
- **G14. Ship keys.** Every `/api/grants` route takes a person session only, so a ship key gets 403 on each of them
  (spec A Testing 3, "create a root grant").

## 3. Spending a grant: tickets, budgets and the page (merge 3c)

### Tickets

Spec A section 4 orders the station's decision. Step 3 adds basis `grant` between `owner` and `read`; basis
`direct` waits for step 5.

- **G15.** A ticket's decision is `build` with basis `grant` when the ship is mentioned in the message, the ship has
  an owner, and the author is a person other than that owner, and a grant G meets all of these:
  - G's grantee is the author, G's targets include the ship, and `direct` is in G's actions;
  - G covers the message's room: the room is listed (S5: either the room itself or a room it replaced, following
    `linked_room_id` back from the message's room), or G's rooms are `"*"`. The room must be current (not replaced),
    local and not a breakout, and both the author and the ship must be members of it when the ticket is issued;
  - G is valid now (G9), and no link in its chain says `confirm: each`;
  - G was created no later than the message, the message was posted at most 24 hours before the ticket, and the
    ship has not answered it (S6; `_answered`, whether or not the watcher asked for decisions);
  - the ship has had fewer than `builds_per_ship_per_day` grant build tickets in the last 24 hours. Owner builds are
    not counted, as in spec A.

  When several grants qualify, the oldest one is used (by `created`, then `id`), so the choice never depends on the
  database's row order.
- **G16.** The ticket records basis `grant`, `root_id` as the root's issuer, and `chain` as the grant ids, root
  first. The station inserts one `budget_uses` row per link in the same transaction. A retried request for a running
  ticket returns the same ticket and charges nothing more, as spec A says.
- **G17.** The ticket's footer is `Builder for <root>, via <grantee> · grant #a1b2`. Its names are the station's own,
  made safe with `safe_line`, and its form follows spec A (a chain of several links, in step 5, reads
  `grants #a1b2 > #c3d4`). A message posted with such a ticket gets `source: {kind: "run", mode: "build", basis:
  "grant", root_name, via_name, answering}`, and the web app labels it "builder for Andy, via Jenn".
- **G18.** A grant `build` is never deferred, because only `read` decisions are (ship status spec S10). A run that
  has started keeps going after its grant is revoked, until it finishes (at most two hours). Step 5 adds the refusal
  of acts that carry a revoked chain's `ticket_id`.
- **G19.** The read-only run prompt (`agent/superyak_agent/runs.py`) says the author "can ask the ship's owner". It
  now says the author can ask the ship's owner for a grant. The watcher otherwise needs no change: it already runs in
  the ticket's mode and posts the ticket's footer. An old watcher without tickets keeps its local rule, under which
  only the owner builds, so nothing widens there.

### The grants page

- **G20.** A "Grants" page (`#grants`, with a link in the sidebar) shows two lists, "Given by you" and "Held by you",
  from G11. Each grant shows its short id, the other person, the ships, the rooms, when it expires, the builds left
  today out of its budget, and whether it is valid, with the reason when it is not.
- **G21.** A form, "Let someone build your ships", makes a grant (G8):
  - the person: a choice of this station's people, from the contacts the page already reads;
  - the ships: a checkbox for each of the caller's own ships;
  - the rooms: "Any room you share with them", or a checkbox for each of the caller's current rooms;
  - how long: 1 day, 3 days, 7 days or 30 days, with 7 days chosen first;
  - builds a day: 1 to 500, with 5 filled in.
- **G22.** "Revoke" asks first, in place, like the board's Drop, with an optional reason. One write at a time.
  Every value on the page is escaped, and names and titles are shown as data.
- **G23.** `peer/API.md` gains "Grants" (G7 to G14), the signed records (G6, G12) and basis `grant` (G15 to G17). Its
  line "a label, not a cryptographic signature; that comes in a later step" changes to say the station signs each
  revision.

## Security

- Authority still starts with a person. In step 3 only a person makes a grant, only over that person's own ships,
  and only to another person. Every `/api/grants` route refuses ship keys.
- Text still never carries authority. A grantee's mention builds only while their grant is valid when the ticket is
  issued, and only within its ships, rooms, hours and budget. A ship's text never builds, whoever owns the ship.
- A grantee's builder run has the powers an owner's builder run has today: a sandboxed run in a fresh worktree,
  whose work the watcher commits to its own branch. Merges stay under section 2 of the law.
- The station's key signs. Whoever controls the Pi's data directory controls both the database and the key, so a
  signature says "this station recorded this", not "this person signed with their own key". Personal signing keys
  stay out of scope, as in spec A.
- Many ships on one machine (many-ships spec S11): in step 3 ships hold no grants, so a ship cannot borrow another
  ship's grant. Step 5 must say how that limit applies to grants held by ships.

## Known limits

- A run that started under a grant finishes even after the grant is revoked (G18).
- `canonical()` writes floats in Python's shortest form. Another implementation that verifies a record must write
  `created` and `expires` the same way.
- The 24-hour bound on mentions (S6) means a grantee's mention that waits a day for an offline watcher runs
  read-only.

## Testing

Each test is named, written first, and seen failing first.

**Merge 3a**

1. A revision's signature verifies against the station's card. Changing one byte of the record, or of the
   signature, fails. `verify_record` returns False for a malformed signature or card, and never raises.
2. A narrowing's new revision is signed with its narrower `audience_users`.
3. Startup signs each unsigned instructions revision once. A second start changes nothing. A note layer is never
   signed.
4. The `/signed` route answers the layer's owner and the owner of an audience ship, gives 404 to anyone else
   (including an unknown layer), and gives 403 to a ship key.

**Merge 3b**

5. Making a grant, as a table of refusals: grantee is the caller, a ship, the system author or awaiting activation;
   a target is another person's ship, a resident ship or unknown; 21 targets; a room is a breakout, remote, replaced,
   or one the caller is not in (404); 21 rooms; `hours` is 0 or 721; `budget` is 0 or 501. A ship key gets 403.
6. Validity gives the right first reason for: revoked, expired, a lifetime longer than a narrowed policy (the test
   replaces `_grant_policy`), budget used up in the last 24 hours, and an issuer who no longer owns a target (set by
   hand). A budget use 24 hours old no longer counts.
7. Revoking: the issuer and a target's owner may; the grantee gets 403; an admin with no other tie gets 404; a second
   revoke gets 409.
8. A grant's signature and its revocation's signature verify. Changing one byte fails. The record carries
   `station`.
9. `GET /api/grants` shows each person the grants they issued, hold or that cover their ships, and no others.
10. The reconcile: with a replaced file, a grant revoked there is revoked here and its budget uses are added; without
    one, every grant is revoked with reason `restored`. Startup then signs those revocations.

**Merge 3c**

11. Spec A Testing 1 without directs, as one table. Authors: the owner, a person grantee, another person, a ship,
    and a mention of a resident ship. Grant states: none, valid, expired, revoked, another ship, another room,
    budget used up, made after the message, the message older than 24 hours, already answered, the author no
    longer in the room. Only the owner's mentions and the valid grantee's mentions give `build`.
12. Revoking between the mention and the ticket gives `read`.
13. A retried request reuses one ticket and charges one budget use. After `budget` builds the next mention gets
    `read`, and 24 hours later it builds again.
14. The 21st grant build for one ship in 24 hours gets `read`, across two grants. Owner builds do not count.
15. Two valid grants: the oldest is charged, and only it.
16. A grant naming room X still builds after a member is added (the new linked room X'); a mention in X itself,
    now replaced, gets `read`.
17. The footer and the message's `source` match the ticket's root, grantee and grant. The web app shows "builder
    for Andy, via Jenn".
18. A grant build is not deferred while the ship's session holds a writable watch; another person's mention still
    is.
19. The browser: Andy makes a grant on the page, sees it under "Given by you", and revokes it after the ask; Jenn
    sees it under "Held by you". A grantee name and a room title written as HTML show as text.

## Review Focus

The inputs most likely to bite a person, beyond the tests above:

1. Two grants for the same person and ship, one used up: the other must still qualify, and only the one charged
   loses budget.
2. A mention posted in the same second the grant was made: "no later than" includes equal times.
3. Andy adds a member, so room X becomes X', then adds another, so X' becomes X'': a grant naming X covers X''.
4. A grant over two ships, where one ship's mention is charged: the grant's daily budget is shared across its
   ships, as spec A counts uses per grant.
5. One message from a grantee that mentions two ships covered by the same grant: each ship's ticket charges the
   grant once, so the message uses two of its builds, and the second ship gets `read` if only one build was left.

## Build order

Three merges, each under section 2 of the law with its own tests: 3a (section 1), then 3b (section 2), then 3c
(section 3). Each gets its own plan, reviewed by a fresh reviewer agent before it is built, as spec A asks. 3c is the
first a person can see.
