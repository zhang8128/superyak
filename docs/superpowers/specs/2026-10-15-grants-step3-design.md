# Spec A step 3: grants a person can spend, and station signatures

Status: approved. Under the station law (section 3, D8), a fresh reviewer agent approves this spec in Andy's place,
and its summary and decisions are posted in "Superyak: city of AI". Andy can veto anything. Revision 1 (6483e3d) was
reviewed: APPROVE WITH CHANGES, 1 must-fix, 10 should-fix and 11 nits, posted whole in the room (message 75396e96).
Revision 2 (113f71a) made every one of them ("Review map" at the end says where), and the same reviewer's re-check
approved it with 3 nits, which this revision 3 makes (G18, Known limits, test 9). Later notes, each narrowing or
aligning, with no new D8 round: G4 (the identity is created at the first signature; plan review of merge 3a, M1);
S6, G15 and G19 (the fresh owner mentions spec, approved under D8 at 1faeff8, bounds owner builds the same way, and
its `_mention_stale` and basis values are shared). G4a, G4b, tests 4a and 4b and the identity Known limit come from
the section 2 review of merge 3a (findings 1 and 4) and are built in merge 3b; the D8 reviewer re-checks them.
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

- Andy grants another person, for example Jenn or Stanley, the right to direct some of his ships in some of the rooms
  they share, for some hours, with a daily budget of builds.
- That person's mention of one of those ships, in a room Andy is in, then runs as builder, with a footer that says
  so: `Builder for Andy, via Jenn · grant #a1b2`.
- Andy sees his grants on a page, and revokes one at any time. A revoke takes effect at the next ticket request,
  including a watcher's retry of a run already started.
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
| `instruct` grants between people, `grant_pins`, pins and follow, pending revisions, line diffs, caps checked at grant creation, bracketed titles, other people's read path to a revision's signature | Useful, but it is most of the machinery step 4's charter acceptance needs (an acceptance is itself an `instruct` grant, spec A section 1). Building it twice costs more than building it once. | step 4 |

So step 3's grantee is always a person, and every grant in step 3 is a root that a person makes in the browser.

## Decisions

Each line is this spec's ruling. A fresh reviewer checks it; Andy can veto any of them.

| # | Topic | Ruling | Why |
| --- | --- | --- | --- |
| S1 | Scope | Step 3 delivers `direct` roots from a person over that person's own ships to another person, spent by ticket basis `grant`, with budgets, revoke, the grants page and station signatures. | The one part useful before steps 4 and 5 (table above). The active law expects it. |
| S2 | Ships as grantees | Moved to step 5 with delegation, acceptance, `confirm: each`, the `ticket_id` rule, the ship routes, the tools, the status line and the session label. | First spent by directs. |
| S3 | `instruct` grants | Moved to step 4 with pins, follow, pending revisions, diffs, caps at grant creation and bracketed titles. | Shares its machinery with charter acceptance. |
| S4 | Room-scoped grants | Not in step 3, and not in spec A. A grant such as `board` or `brief` (work board spec, ship room briefs spec) scopes a room the issuer owns, not ships, so it needs its own spec. | Different shape. |
| S5 | Where a grant builds | Only in a room the issuer is in when the ticket is issued, whatever the grant lists. A grant that names room X covers the current room that replaced X, following `linked_room_id` forward, and never a replaced room, X included. | The issuer keeps sight of every build he granted (review M1: any person can open a room with any ship). Adding a member or bridging makes a new room id (`chats.py` `add_participants`; survey 3.2), and the issuer stays a member of the new room. Briefs, open board items and claims already carry forward. Without following forward, Andy bridging a room would silently end every grant in it. |
| S6 | Old and answered mentions | A grant build needs a mention posted no earlier than the grant was created, at most 24 hours before the ticket, and not yet answered by the ship. Otherwise the ticket is `read`. Owner builds get the same bound from the fresh owner mentions spec (`2026-10-15-owner-mention-fresh-design.md`, approved under D8 at 1faeff8), which amends this line: its `_mention_stale` is the one check both use (G15). | HANDOFF's parked note: once acts spend build tickets, the station must refuse old or answered messages (survey 3.13). A grant must not reach back to words written before it. |
| S7 | What the station signs | Grant records, revocations and instructions revisions. Each record has a fixed set of keys, including a `kind` and the station's peer id. A revision's record carries its audience. A revocation's signature gets its own column. | Spec A's records name no station or kind for grants and no audience for revisions (survey 3.8). A fixed key set keeps old signatures valid when later steps add columns, and a kind keeps one record from passing as another (review S1, S2). Rows never change except the revocation fields, so the revocation signature needs somewhere to go. |
| S8 | Policy with no charter | One function returns spec A's no-charter defaults. Validity reads `max_expiry_hours` (720), `max_depth` (3) and the grantee set (unrestricted); tickets read `builds_per_ship_per_day` (20). A root's budget is 1 to 500 builds a day, and its depth is 0. | Step 4 swaps the charter in behind the same function without changing validity. A budget of 0 could never be spent. Depth only matters once delegation exists. |
| S9 | Restoring a backup | With a usable replaced file, the reconcile revokes every grant revoked there or missing there, and adds the budget uses recorded there. Without one, it revokes every grant, with reason `restored`. | A restored copy must not bring back a revoked grant or a spent budget (backups spec S16, survey 3.14). |

## 1. Signed instructions revisions (merge 3a)

The station already has an Ed25519 identity per data directory (`identity.py`), and today it signs only federation
envelopes. This merge gives the store a signer and signs instructions revisions. It has no grants.

- **G1.** `revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL,
  PRIMARY KEY(layer_id, revision))`.
- **G2.** When a new revision is written whose stored snapshot has `kind: "instructions"` (at activation, or at the
  narrowing that makes a new revision; `layers.py` writes `layer_revisions` only there), the station signs its record
  in the same transaction. The record has exactly these keys:
  `{kind: "instructions-revision", station, layer_id, revision, owner_id, title, body, audience_users, policy,
  created}`. `title`, `body` and `audience_users` come from the revision's stored snapshot, `created` from
  `layer_revisions.created`, `station` is this station's peer id, and `policy` is `null` until step 4. The kind is
  read from the revision's snapshot, never from the layer's current draft, so a layer that was a note at revision 1
  and instructions at revision 2 has only revision 2 signed.
- **G3.** A signature is over `identity.canonical(record)`, as federation envelopes are. `PeerIdentity` gains
  `sign_record(record)`. The module gains `verify_record(card, record, signature)`, which returns True only when all
  of these hold, in this order, and otherwise returns False and never raises:
  - the card passes `validate_card` (its peer id is its key's hash);
  - the record is a JSON object whose `kind` is one of `instructions-revision`, `grant`, `grant-revocation`, and
    whose keys are exactly the set G2 or G12 gives for that kind;
  - `record["station"]` equals the card's peer id;
  - the signature verifies over `canonical(record)` with the card's key.

  So a federation envelope with its signature taken off never verifies as a record: it has no record kind.
- **G4.** The store uses the station's identity file in its own data directory, the one federation uses. At startup
  it loads the file if it exists and keeps it; if the file can't be loaded, the station fails to start rather than
  write unsigned records. A missing file is created, exactly as `PeerIdentity.load_or_create` does today, only when
  the store first signs, inside the transaction that signs. That transaction holds the dispatch gate, so two
  signers can't both create it, and a failed create rolls the signed write back. (Plan review of merge 3a, M1:
  creating the file at every start would fix a new station's certificate before `card --endpoint` can add the
  station's hostname to it.)
- **G4a. Only the lighthouse holds the key at startup (built in merge 3b; section 2 review of 3a, finding 1).**
  `Store` takes `signing=True` by default. With `signing=False` it skips G4's startup load, G4b's check and G5's
  backfill, and holds no key unless something it does signs, in which case `_station_identity()` still loads or
  creates the identity inside the signing transaction, so nothing is ever written unsigned. The door
  (`create_door`) and the station commands that open a store but never sign (`station-pending`, `station-approve`,
  `station-deny`, `station-rooms`, `station-bridge`, `station-unbridge`, `station-notices`) open it with
  `signing=False`. So the internet-facing door never holds the private key, and a damaged `identity.json` stops the
  lighthouse alone: the door keeps taking access requests, and Andy can still list and approve what waits. The
  lighthouse (`create_app`), `init`, `card` and every other opener keep `signing=True`.
- **G4b. A lost identity is not replaced silently (built in merge 3b; section 2 review of 3a, finding 4).** At a
  `signing=True` start, if `identity.json` is missing (not a file, not a symlink) while the station holds signed
  records (a row in `revision_signatures`, or, from merge 3b, in `grants`), the store refuses to start with a
  `ValueError` naming the file: a new identity would void every stored signature. The message says to restore the
  file. A station with no signed records still creates its identity at the first signature (G4), so a new station's
  first `card --endpoint` still names its host. `card` opens the store with `signing=True`, so it refuses too rather
  than make a new key.
- **G5.** At startup, every revision whose snapshot has `kind: "instructions"` and that has no signature is signed
  once, from its stored snapshot. The active station law (layer c879372542444e4c8f95f2c0db69f8fb) is one of them. A
  second start signs nothing.
- **G6.** `GET /api/layers/{id}/revisions/{n}/signed` (person) returns `{station, record, signature}` to the layer's
  owner. Anyone else gets 404, so the route never says whether a layer exists, and a ship key gets 403. In step 3 a
  layer binds only its owner's ships, so no one else needs it. Step 4 adds the owners whose ships a revision binds
  under an `instruct` grant.

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

This is spec A's table with one added column, `revocation_signature` (S7). The columns steps 4 and 5 use from spec
A's table (`parent_id`, the charter columns, `follow`) are here now. What later steps add, such as acceptance or a
session label, stays outside the signed record (G12), so old signatures keep verifying. In step 3, `actions` is
`["direct"]`, `depth` is 0, `confirm` is `none`, and `parent_id`, the charter columns and `follow` are empty. Rows
never change, except that revoking fills `revoked`, `revoked_by`, `revoke_reason` and `revocation_signature`.

- **G7. The policy.** `_grant_policy(db)` returns spec A's no-charter defaults: `max_depth` 3, `max_expiry_hours`
  720, `agent_grant_default_hours` 24, `builds_per_ship_per_day` 20, `delegable` `["direct"]`, and an unrestricted
  grantee set. Every check below reads the policy through this one function.
- **G8. Making a grant.** `POST /api/grants {grantee, targets, rooms, hours, budget}` (person, CSRF). The caller is
  the issuer. The station checks in this order and refuses with a plain reason at the first failure:
  1. rooms first, so no answer says anything about a room the caller is not in: `rooms` is `"*"`, or a list of 1 to
     20 room ids, each of which must be a room the caller is a member of. An unknown id, a remote id (with `:`), a
     breakout or a room the caller is not in gets 404, the same answer for each;
  2. each listed room must be current (not replaced) and must also have the grantee as a member (400);
  3. `grantee` is a person on this station (not a ship, the system author or an account awaiting activation), and
     not the caller (400);
  4. `targets` lists 1 to 20 ships whose owner is the caller (400; a resident ship has no owner, so it never
     qualifies, and an admin's other ships don't either);
  5. `hours` is a whole number from 1 to `max_expiry_hours`; `expires` is now plus that many hours;
  6. `budget` is a whole number from 1 to 500.

  A repeated id in `targets` or `rooms` is refused (400), never merged. The station then inserts the row, signs it
  (G12) and returns the grant as G11 shows it.
- **G9. Validity** of a grant at time t is a walk from the grant to its root, so step 5 only adds links. In step 3
  every grant is its own root. A link is valid when all of these hold, checked in this order, and the first that
  fails is the reason:
  1. it is not revoked: "Grant #a1b2 was revoked by Andy";
  2. it has not expired: "Grant #a1b2 expired 2026-10-20 14:00 UTC";
  3. it fits the policy in force now, so narrowing the policy later takes effect at the next check: its lifetime
     (`expires − created`) is at most `max_expiry_hours` ("Grant #a1b2 lasts longer than the station now allows"),
     the chain is at most `max_depth` links long, and its grantee is in the grantee set ("... is no longer allowed
     by the station's policy");
  4. fewer than `budget` builds were charged to it in the last 24 hours: "Grant #a1b2 has used its 5 builds for the
     last 24 hours";
  5. the root's issuer still owns every target: "Andy no longer owns Rio Grande". Ownership never changes today, but
     a restored or hand-edited database could change it.

  A grant's short id is `#` followed by the first 4 characters of its id, as in spec A's footers. Names in reasons
  are the station's own, made safe as in `safe_line`.
- **G10. Revoking.** `POST /api/grants/{id}/revoke {reason}` (person, CSRF). Allowed for the issuer, for the issuer
  of any grant above it (none in step 3, but the walk is the same), and for the owner of any target ship (in step 3
  that is the issuer, unless ownership was changed by hand). Being an admin gives no power over other people's
  grants. A person G11 doesn't show the grant to gets 404; one who sees it but may not revoke it gets 403; a grant
  already revoked gets 409. `reason` is optional, one line, at most 200 characters, and defaults to `revoked`. The
  station signs the revocation (G12).
- **G11. Reading.** `GET /api/grants` (person) lists the grants the caller issued, holds, or that cover their ships,
  newest first. No one else sees a grant. Each shows:
  - `id`, `short`, the issuer and grantee (id and name), the targets (id and name), `expires`, `budget`, `created`,
    the revocation fields, `valid`, and `reason` when it is not valid;
  - `budget_left`: the budget minus the builds charged to the grant in the last 24 hours, shared by all its ships;
  - for each target ship, `ship_builds_left`: `builds_per_ship_per_day` minus that ship's grant builds in the last 24
    hours, under every grant, so a grantee can see when another grant has used the ship's day;
  - the rooms: `"*"`, or for each listed room its id, its title, and, when it has been replaced, the current room it
    now covers (id and title). A title is shown only to that room's members; anyone else sees "a room you are not
    in".

  Titles and names come from people, so the web app escapes them.
- **G12. Signatures.** A grant's record has exactly these keys: `{kind: "grant", station, id, issuer_id,
  grantee_id, actions, targets, rooms, expires, budget, depth, confirm, parent_id, charter_layer_id,
  charter_revision, follow, created}`, with `actions`, `targets` and `rooms` as parsed JSON values, not their stored
  text. A revocation's record has exactly `{kind: "grant-revocation", station, grant, revoked, revoked_by, reason}`.
  Both are signed as G3 says. `GET /api/grants/{id}/signed` (person) returns `{station, record, signature}`, plus
  `revocation: {record, signature}` once it is revoked, to anyone G11 shows the grant to, and 404 to anyone else. At
  startup, a revocation without a signature is signed once (the reconcile in G13 can't sign: it works on a staged
  file, not a store).
- **G13. Restoring.** `station-restore-reconcile` gains grants:
  - with a usable replaced file, every grant revoked there is revoked here with the same time, person and reason;
    every grant not in the replaced file is revoked with reason `restored` (grants are never deleted, so a missing
    one means damage); and every `budget_uses` row there, matched on `(grant_id, ticket_id)`, for a grant in both
    files is added here if missing;
  - without one, every grant not yet revoked is revoked, with reason `restored` and no person;
  - `grants.id`, `grants.revoked`, `grants.revoked_by`, `grants.revoke_reason`, `budget_uses.grant_id`,
    `budget_uses.ticket_id` and `budget_uses.created` join `COMPARED`;
  - the report lists each revoked grant by short id, issuer and grantee usernames, under the existing header, and
    counts the budget uses added.

  A grant made after the copy was taken is gone after a restore, and its issuer makes it again.
- **G14. Ship keys.** Every `/api/grants` route takes a person session only, so a ship key gets 403 on each of them
  (spec A Testing 3, "create a root grant").

## 3. Spending a grant: tickets, budgets and the page (merge 3c)

### Tickets

Spec A section 4 orders the station's decision. Step 3 adds basis `grant` between `owner` and `read`; basis
`direct` waits for step 5.

- **G15.** A ticket's decision is `build` with basis `grant` when the ship is mentioned in the message, the ship has
  an owner, and the author is a person other than that owner, and a grant G meets all of these:
  - G's grantee is the author, G's targets include the ship, and `direct` is in G's actions;
  - G covers the message's room R. R must be current (not replaced), local and not a breakout. G covers R when G's
    rooms are `"*"`, or when R or a room R replaced is listed: the station walks back from R along `linked_room_id`,
    keeping a set of rooms it has seen so a cycle or an old fork ends the walk;
  - when the ticket is issued, the author, the ship and G's root issuer are all members of R (S5);
  - G is valid now (G9), and no link in its chain says `confirm: each`;
  - G was created no later than the message (equal times count), the message was posted at most 24 hours before the
    ticket (exactly 24 hours still counts), and the ship has not answered it (S6; the age and answered parts are the
    fresh owner mentions spec's `_mention_stale(db, ship_id, message)`, which returns None, `old` or `answered`;
    `_answered`, whether or not the
    watcher asked for decisions);
  - the ship has had fewer than `builds_per_ship_per_day` grant build tickets in the last 24 hours, under any
    grant. Owner builds are not counted, as in spec A.

  When several grants qualify, the oldest one is used (by `created`, then `id`), so the choice never depends on the
  database's row order. A grant that fails a condition, for example one with no budget left, is skipped, and the
  next oldest is tried. When the only thing that keeps a grantee's mention from building is its age or an earlier
  answer (`_mention_stale` returns `old` or `answered` and a grant would otherwise qualify), the `read` ticket's basis
  is that value, as for an owner mention under the fresh owner mentions spec, so the labels agree; any other refusal
  is basis `none`.
- **G16.** The ticket records basis `grant`, `root_id` as the root's issuer, and `chain` as the grant ids, root
  first. The station inserts one `budget_uses` row per link in the same transaction. One message that mentions two
  ships under one grant charges it once per ship's ticket.
- **G17.** The ticket's footer is `Builder for <root>, via <grantee> · grant #a1b2`. Its names are the station's own,
  made safe with `safe_line`, and its form follows spec A (a chain of several links, in step 5, reads
  `grants #a1b2 > #c3d4`). A message posted with such a ticket gets `source: {kind: "run", mode: "build", basis:
  "grant", root_name, via_name, answering}`. The web app labels it "builder for Andy, via Jenn", and so does the
  agent's `source_label` (`agent/superyak_agent/station.py`), which run prompts and hooks use to label room history:
  it appends ", via <via_name>" when the source has one.
- **G18.** A grant `build` is never deferred, because only `read` decisions are (ship status spec S10). A re-sent
  request for a running grant ticket re-checks the grant before it returns the ticket: G9's revocation, expiry,
  policy and ownership checks, and the root issuer's membership of the room. It does not re-check the budget or the
  per-ship cap, which this ticket already paid. If a check fails, the ticket is finished and the request gets 409
  with the reason. The finish is saved with the refusal (the `Problem` keeps what was saved, `keep=True`, as a
  breakout's closure is), so the ticket can never label a post again. The watcher answers a 409 from a ticket request
  by posting the fallback note (`watch.py`), and that note, sent with the finished ticket's id, gets 409 and goes out
  unlabelled (`_post_unlabelled`). So a mention still never goes without a reply, the note never reads as a builder
  run, and a revoke stops the watcher's retries. A run already under way when the grant
  is revoked runs to its end. Step 5 adds the refusal of acts that carry a revoked chain's `ticket_id`.
- **G19.** The read-only run prompt (`agent/superyak_agent/watch.py`) says the author "can ask the ship's owner". It
  now says the author "can ask the ship's owner for a grant, or check the Grants page". The fresh owner mentions spec
  adds a reason line to the same prompt for `old` and `answered` tickets; whichever lands second keeps both, the
  reason line first. `agent/superyak_agent/runs.py`'s
  docstring ("builder for the ship's owner") gains "or a person the owner granted". The watcher otherwise needs no
  change: it already runs in the ticket's mode and posts the ticket's footer. An old watcher without tickets keeps
  its local rule, under which only the owner builds, so nothing widens there.

### The grants page

- **G20.** A "Grants" page (`#grants`, with a link in the sidebar) shows two lists, "Given by you" and "Held by you",
  from G11. Each grant shows its short id, the other person, the ships with each ship's grant builds left, the rooms
  (with the current room for a replaced one), when it expires, the builds left in the last 24 hours out of its
  budget, and whether it is valid, with the reason when it is not.
- **G21.** A form, "Let someone build your ships", makes a grant (G8). It opens with one line on what a grant
  allows: "Their mentions start builder runs of your ships on your machine. A run can read your repository and uses
  your model time, and its reply is posted in the room." Then:
  - the person: a choice of this station's active people other than the caller, from `GET /api/grants/people`
    (person, ship key 403), which returns `[{id, name}]` sorted by name. `/api/contacts` isn't used: it mixes in
    ships, residents, pending accounts and remote contacts;
  - the ships: a checkbox for each ship whose owner is the caller (an admin sees every ship in `/api/ships`, so the
    page filters by `owner_id`);
  - the rooms: a checkbox for each current room that holds both the caller and the chosen person, chosen first, or
    "Any room you share with them" (`"*"`);
  - how long: 1 day, 3 days, 7 days or 30 days, with 7 days chosen first;
  - builds a day: 1 to 500, with 5 filled in.
- **G22.** "Revoke" asks first, in place, like the board's Drop, with an optional reason. One write at a time.
  Every value on the page is escaped, and names and titles are shown as data.
- **G23.** `peer/API.md` gains "Grants" (G7 to G14, and `/api/grants/people`), the signed records (G3, G6, G12) and
  basis `grant` (G15 to G18). Its line "a label, not a cryptographic signature; that comes in a later step" changes
  to say the station signs each revision.

## Security

- Authority still starts with a person. In step 3 only a person makes a grant, only over that person's own ships,
  and only to another person. Every `/api/grants` route refuses ship keys.
- Text still never carries authority. A grantee's mention builds only while their grant is valid when the ticket is
  issued, and only within its ships, rooms, hours and budget, and only in a room where the issuer is present. The
  issuer therefore sees every request and every reply his grant pays for. A ship's text never builds, whoever owns
  the ship.
- A grantee's builder run has the powers an owner's builder run has today: a sandboxed run in a fresh worktree,
  whose work the watcher commits to its own branch. Merges stay under section 2 of the law.
- The station's key signs. Whoever controls the Pi's data directory controls both the database and the key, so a
  signature says "this station recorded this", not "this person signed with their own key". Personal signing keys
  stay out of scope, as in spec A. Each record names its kind and its station, so no record passes as another kind,
  as a federation envelope or as another station's.
- Many ships on one machine (many-ships spec S11): in step 3 ships hold no grants, so a ship cannot borrow another
  ship's grant. Step 5 must say how that limit applies to grants held by ships.

## Known limits

- A run already under way when its grant is revoked runs to its end (G18). Retries stop.
- A read-only answer doesn't say which rule kept the mention from building. The Grants page shows the grant's
  validity, its builds left and each ship's grant builds left.
- `canonical()` writes floats in Python's shortest form. Another implementation that verifies a record must write
  `created` and `expires` the same way.
- The 24-hour bound on mentions (S6) means a grantee's mention that waits a day for an offline watcher runs
  read-only.
- The nightly copies leave out the identity files (backups spec). From merge 3b, a station whose `identity.json` is
  missing while it holds signed records refuses to start (G4b) instead of taking a new key. Someone who deletes the
  file on purpose to get a station up, or rebuilds it on purpose with a new key, voids every stored signature: they
  stop verifying against the new card, and the backfill doesn't sign them again, since they aren't unsigned.
- Checking a signature needs the station's card, which exists only when the station has an HTTPS federation
  endpoint (`identity.py` `validate_card`); the CLI prints one with `--endpoint`. Tests build the card with a
  placeholder endpoint.
- After a restore, the tickets issued since the copy are gone, so the per-ship cap undercounts for up to a day.
  Budget uses are restored from the replaced file (G13), so each grant's own budget does not.

## Testing

Each test is named, written first, and seen failing first.

**Merge 3a**

1. A revision's signature verifies against the station's card. Each of these fails: one changed byte in the record
   or the signature, a record whose `station` is another peer id, a record with a key added or missing, a federation
   envelope with its signature removed, and a card whose peer id isn't its key's hash. `verify_record` returns False
   for a malformed signature or card, and never raises.
2. A narrowing's new revision is signed with its narrower `audience_users`.
3. Startup signs each unsigned instructions revision once, and a second start changes nothing. Activating a note
   writes no signature. A layer whose revision 1 is a note and whose revision 2 is instructions has only revision 2
   signed. A station whose identity file can't be read fails to start. Opening a store on a new directory creates no identity
   file, so the first `card --endpoint` still names the station's host in its certificate; the first signature creates
   it.
4. The `/signed` route answers the layer's owner. It gives 404 to anyone else, including the owner of a ship in the
   audience and a request for an unknown layer, and 403 to a ship key.

**Merge 3b**

4a. The door and the listed station commands start and work with a damaged `identity.json` (not JSON) while the
    lighthouse refuses to start; the door's store holds no key after starting (`_identity` unset), and an access
    request through it still works. A `signing=False` store that signs (an activation through it) still writes a
    signed revision, creating the identity if it is missing.
4b. On a station with a signed revision, removing `identity.json` makes a `signing=True` start refuse with a
    `ValueError` naming the file (`Store`, `create_app` and `card`); a `signing=False` start still opens; a station with
    no signed records and no identity starts and creates none (G4's first-card behavior is unchanged); a dangling
    symlink still refuses as before.
5. Making a grant, as a table of refusals, each with its status: an unknown, remote or breakout room id or a room
   the caller is not in (404, the same body for each); a replaced room or one without the grantee (400); grantee is
   the caller, a ship, the system author or awaiting activation; a target is another person's ship, a resident ship
   or unknown; a repeated target or room; 21 targets or 21 rooms; `hours` 0 or 721; `budget` 0 or 501. A ship key
   gets 403 on every `/api/grants` route: make, list, revoke, signed and people.
6. Validity gives the right reason for: revoked, expired, a lifetime longer than a narrowed policy and a chain longer
   than a narrowed `max_depth` (the test replaces `_grant_policy`), budget used up in the last 24 hours, and an issuer
   who no longer owns a target (set by hand). A budget use exactly 24 hours old no longer counts. A grant that is both
   revoked and expired gives the revoked reason.
7. Revoking: the issuer may, and so may a target's owner (set by hand to someone else, since in step 3 the owner is
   the issuer); the grantee gets 403; an admin with no other tie gets 404; a second revoke gets 409.
8. A grant's signature and its revocation's signature verify. Each of G3's failures applies to them too. The record
   carries `kind` and `station`, holds parsed `targets` and `rooms`, and has exactly G12's keys.
9. `GET /api/grants` shows each person the grants they issued, hold or that cover their ships, and no others;
   `/signed` gives 404 to the others. A grantee whom the room's owner has removed from a listed room sees "a room you are not in" for it.
   A grant whose room was replaced shows the current room. `GET /api/grants/people` lists active people only,
   without the caller, ships, residents, pending accounts or remote contacts.
10. The reconcile: with a replaced file, a grant revoked there is revoked here, a grant missing there is revoked, and
    the budget uses there are added once (a second run adds none); without one, every grant is revoked with reason
    `restored`. The report names each revoked grant. Startup then signs those revocations.

**Merge 3c**

11. Spec A Testing 1 without directs, as one table. Authors: the owner, a person grantee, another person, a ship,
    and a mention of a resident ship. Grant states: none, valid, expired, revoked, another ship, another room, budget
    used up, made after the message, made in the same second as the message (builds), the message exactly 24 hours
    old (builds) and older (`read`), already answered, the author no longer in the room, a `"*"` grant in a room
    without the issuer, and a listed room after its owner removed the issuer. Only the owner's mentions and the valid
    grantee's mentions in a room with the issuer give `build`.
12. Revoking between the mention and the ticket gives `read`. Revoking between a ticket and its re-send gives 409 with
    the reason; the ticket's status then reads finished, and a post carrying its id gets 409, so the watcher's
    fallback note goes out unlabelled (its existing 409 paths, already tested). A re-send of a valid grant ticket, including one that used the grant's last build,
    returns the same ticket and charges nothing more.
13. After `budget` builds the next mention gets `read`, and 24 hours later it builds again. A grant over two ships
    shares one budget: builds of either ship count against it.
14. The 21st grant build for one ship in 24 hours gets `read`, across two grants. Owner builds do not count.
    `ship_builds_left` shows the ship's remaining count on the other grant.
15. Two valid grants: the oldest is charged, and only it. When the oldest has no budget left, the newer one is
    charged.
16. A grant naming room X still builds after a member is added (X becomes X'), and after another is added (X'
    becomes X''); a mention in X or X', now replaced, gets `read`. A `linked_room_id` cycle made by hand ends the walk.
17. The footer and the message's `source` match the ticket's root, grantee and grant. The web app shows "builder
    for Andy, via Jenn", and the agent's `source_label` gives "builder run for Andy, via Jenn".
18. A grant build is not deferred while the ship's session holds a writable watch; another person's mention still
    is.
19. One message from a grantee that mentions two ships under one grant with one build left: the first ticket builds,
    and the second gets `read`.
20. The browser: Andy makes a grant on the page, choosing from a person list without ships, and sees it under "Given
    by you"; it revokes after the ask. Jenn sees it under "Held by you". A grantee name and a room title written as
    HTML show as text.

## Review Focus

The inputs most likely to bite a person, each now pinned by a test:

1. Two grants for the same person and ship, the older one used up: the newer one is charged (test 15).
2. A mention posted in the same second the grant was made, and one exactly 24 hours old (test 11).
3. Andy adds a member twice, so X becomes X' and then X'': a grant naming X covers X'' (test 16).
4. A grant over two ships shares its daily budget (test 13).
5. One message from a grantee that mentions two ships under one grant, with one build left (test 19).

## Build order

Three merges, each under section 2 of the law with its own tests: 3a (section 1), then 3b (section 2), then 3c
(section 3). Each gets its own plan, reviewed by a fresh reviewer agent before it is built, as spec A asks. 3c is the
first a person can see.

## Review map (revision 1's review, message 75396e96)

| Finding | Where it is answered |
| --- | --- |
| M1 issuer's sight | S5; G15 third bullet; G21 rooms (specific rooms first); Security; test 11 |
| S1 record keys and later columns | S7; section 2's paragraph after the SQL; G12; test 8 |
| S2 `verify_record` | G3; S7; Security; tests 1 and 8 |
| S3 kind from the snapshot | G2; G5; test 3 |
| S4 `/signed` read path | G6 (owner only); scope table; test 4 |
| S5 room titles | G8 step 2 (grantee must be in each listed room); G11 (titles only to members); G21; test 9 |
| S6 retries after a revoke | Goal; G18 (re-check on re-send, 409); Known limits; test 12 |
| S7 `source_label` and the file reference | G17; G19; test 17 |
| S8 the person picker | G21 (`GET /api/grants/people`); G14; G23; tests 5 and 9 |
| S9 tests for the Review Focus | tests 13, 15, 16, 19; Review Focus |
| S10 why a mention read, the ship cap | G11 `ship_builds_left`; G19 wording; G20; Known limits; test 14 |
| N1 order and duplicates | G8 |
| N2 `/signed` 404 | G12; test 9 |
| N3 COMPARED, matching, missing grants, report | G13; S9; test 10 |
| N4 cap after a restore | Known limits |
| N5 `budget_left` | G11; G9 reason; G20 |
| N6 walk guard | G15; test 16 |
| N7 current room for a replaced one | G11; G20; test 9 |
| N8 test notes | tests 3, 5, 6, 7, 11 |
| N9 identity at startup | G4; test 3 |
| N10 `max_depth` and grantee set | S8; G9 step 3; test 6 |
| N11 own ships and what a grant allows | G8 step 4; G21 |
| Re-check N1 the finish survives the 409 | G18 (`keep=True`); test 12 |
| Re-check N2 verifying needs a card | Known limits |
| Re-check N3 removed, not left | test 9 |
