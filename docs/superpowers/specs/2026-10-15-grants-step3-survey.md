# Survey: spec A step 3 (grants and chains) against the code at 7094b5b

Date: 2026-10-14 (for a plan dated 2026-10-15). Read-only survey. Nothing in the repository was changed.

Spec: `docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md` (called "spec A" below; line
numbers are spec lines). Code paths are relative to the repository root.

Committed beside the step 3 design ([2026-10-15-grants-step3-design.md](2026-10-15-grants-step3-design.md)) as its evidence.

---

## 0. What step 3 must deliver, by the spec's own words

Build order, spec A:483-484: "Grants and chains. Browser roots, delegation, validity under the policy defaults,
budgets, `instruct` grants between people, signatures, the grants page." Step 2's note (481-482) adds that
"signatures, diffs and the Ships status view come with steps 3–4".

Pieces of the spec that step 3 owns or touches:

- **Tables** `grants`, `grant_pins`, `budget_uses` (159-168). JSON `actions`, `targets`, `rooms`; `targets: "own"`
  only on a charter acceptance; `rooms` is a list or `"*"` = "any room the acting ship and target share"; `confirm`
  is `none` | `each`; rows never change except the three revocation fields (170-172).
- **Roots** `POST /api/grants` (person, CSRF): targets must be the caller's own ships; grantee in the charter's
  grantee set "when a charter is active"; `expires` ≤ `max_expiry_hours`; an `instruct` root takes a pin or
  `follow` (174-179). Charter root rows are step 4.
- **Children** `POST /api/grants/delegate` (ship key) with six refusal rules: chain valid, depth > 0 and actions in
  `delegable`, child ⊆ parent in every field (default expiry `agent_grant_default_hours`), grantee in set, another
  owner's ship must accept (`POST /api/grants/{id}/accept`), optional `ticket_id` confused-deputy rule (181-193).
- **Validity** walk to the root, checked against the policy in force now (195-203).
- **Revoking**: person route for issuer, any issuer above, or any target's owner; ship route
  `POST /api/ships/me/grants/{id}/revoke` for grants it issued; admin gives no power (205-207).
- **Reading**: `GET /api/grants` (person) and `GET /api/ships/me/grants` (ship) with validity and budget left
  (209-211).
- **`instruct` grants between people**: binding rule 3 (120-121), "Ships never receive `instruct`" (123), block
  order "charter, then owner, then granted instructors by grant age" (139-140), caps of 10 layers / 48 KB (75-77,
  123).
- **Budgets**: a build under a chain inserts one `budget_uses` row per link (307-308); validity needs fewer uses in
  24 h than `budget` at every link (197-198); `builds_per_ship_per_day` counts `direct` and `grant` build tickets
  (305-307). The only spending path that does not need directs is ticket basis 3, "`build`, `grant`: the author is
  a person holding a valid `direct` chain for this ship and room ... no link says `confirm: each`" (300-302).
- **Signatures** (Plurality, 363-372): the station signs each grant record and each revocation with its Ed25519
  identity key, and each instructions-layer revision into `revision_signatures`; `GET /api/grants/{id}/signed`,
  `GET /api/layers/{id}/revisions/{n}/signed`; `identity.verify_record`. Exported ids are `<peer id>:<id>`.
- **Policy defaults** with no charter (382-384) and bounds (94-95). See section 3.9.
- **Ship-key allowlist** grows by "grants delegate, `ships/me/grants` (list, revoke)" (378-379).
- **Agent**: `station_grant`, `station_grants` (273-275); `superyak-agent status` prints grants held with budget
  left, and the web app's Ships section shows the same (359-361).
- **Errors**: every refusal a 4xx with a plain reason, e.g. "Grant #c3d4 expired 2026-10-09 14:00" (388-389).
- **Tests** that fall in step 3: Testing 1 (author × grant state × act table, minus directs), 2 (oracle over
  "owners, signers, grants, pins and follows", 500 cases), 3 (ship key 403 on root grant), 5 (plurality), 6
  (subset property, budget across chain, depth, revoke above, different root, grantee set, acceptance), and the
  browser test for "the grants page" (470-472).
- **Session label** (D7, line 36; Concepts 57-59): "Every act also records a session label".

---

## 1. What exists today, even partially

| Item | Evidence | What it does today |
| --- | --- | --- |
| Ticket columns for chains | `peer/superyak_peer/tickets.py:17` | `tickets` has `direct_id TEXT` (no FK; there is no `directs` table), `root_id`, `chain TEXT DEFAULT '[]'`, `hops DEFAULT 0`, `instructions`. Insert at :71 never sets `chain`, `hops` or `direct_id`, so they stay at defaults. `root_id` is the owner for basis `owner`. |
| Ticket decision | `tickets.py:84-91` | `_mode_for` is step 1's rule only: owner's own mention → `build`/`owner`, else `read`/`none`. Docstring :1-3 says "Later steps add grants and directs to the same decision." |
| Footer and source label | `tickets.py:36`, `:152-165` | Footer only for basis `owner` ("Builder for X (owner)"). `_sources` already returns `basis` and `root_name` from the ticket, so a `grant` basis would label correctly with no change. |
| Deferral fits grants | `tickets.py:63` | `defer` applies only when the decision is `read`. Ship-status spec S10 (2026-10-10, lines 284-286) already rules that step 3's rules apply unchanged when a mention becomes `run`. |
| Watcher obeys the ticket | `agent/superyak_agent/watch.py:183,186` | Runs in the ticket's mode, never higher; footer comes from the ticket. A station that returns `build`/`grant` would get a builder run with no agent change. |
| Binding layers (step 2) | `peer/superyak_peer/instructions.py:78-92` | Owner's own active instructions layers whose audience lists the ship. Docstring :1-3: "Grants (step 3) and the charter (step 4) add to this rule." Sorted by `(created, layer_id)`, not by the spec's order. |
| Caps | `instructions.py:94-103` | Checked only for ships the activator owns; :99-100 skips others ("it does not bind a ship the activator does not own"). Pinned by `peer/tests/test_instructions.py:156` `test_someone_else_cannot_use_up_my_ships_caps`. |
| Rendering with signer | `instructions.py:19-25`, `:29-41` | `render_one` prints `signed by <owner name>`; `_layers_for` already joins `layers.owner_id` → signer, so a layer by another person renders with that person's name. Title is not bracketed. |
| Independent oracle test | `test_instructions.py:277-315` | 60 seeded cases for owners, audiences, kinds, withdrawals, narrowings. No grants, pins or follows. |
| Ship drafts | `instructions.py:51-76`, `peer/superyak_peer/app.py:240-243`, `agent/superyak_agent/mcp.py:192,530` | Done in step 2: `POST /api/ships/me/drafts` and `station_draft_instructions`. |
| "grants" in layers.py | `peer/superyak_peer/layers.py:142-165` | `revoke_layer_routes` "Narrow[s] active grants": these are a layer's **audience access routes** (person, space, public), not spec A grants. No overlap. |
| "grants" in interchange.py | `peer/superyak_peer/interchange.py:1,44` | Docstrings say imported origins and audiences are "never grants". Unrelated to spec A. |
| Layer `kind` | `layers.py:5-50` | `kind` exists; `charter`, `policy` are not in `FIELDS` (step 4). `drafted_by` is a server key (:7). |
| Station identity | `peer/superyak_peer/identity.py:74-138` | Ed25519 key per station; `canonical()` at :20-25; signs only federation envelopes (:132-138); `verify_envelope` at :140-166. No record signing, no `verify_record`. |
| Identity owner | `peer/superyak_peer/federation.py:16`, `app.py:139` | `Federation(store)` loads the identity from `store.data_dir`. The `Store` has no handle on it; routes pass `app.state.federation.identity.peer_id` into store calls (`app.py:234,258,313`). |
| Person auth + CSRF | `app.py:88-97` | `current_user`: 403 for any bearer key, session cookie required, `x-csrf-token` checked on every non-GET. `actor()` at :111. |
| Ship-key auth | `app.py:99-109` | `member()` takes either; `ship_member()` takes only a key and records presence. The "allowlist" is per-route dependency choice, not a central list. `peer/tests/test_ships.py:29-46` samples routes that must 403. |
| Session label source | `peer/superyak_peer/presence.py:15,28-38` | `X-Superyak-Session` header, `[A-Za-z0-9._:-]{1,100}`, parsed on every ship call. Exactly the spec's "session label" shape, already sent by the agent (`agent/superyak_agent/station.py:29`). |
| Ship ownership | `ships.py:49-53`, `ships.py:164-176`, `auth.py:19` | `users.kind='ship'`, `users.owner_id`. Ownership is set once at docking and never updated (only write is `ships.py:52`); a re-dock by another person is refused 409 (:167-168). `revoke_ship` (:371-378) revokes keys only; the ship row stays. Residents (`odo`, `wormhole`) have `owner_id NULL`. |
| Person check | `ships.py:111-115` | `_person()` refuses ships and pending activations. Reusable for grant routes. |
| Status command | `agent/superyak_agent/__main__.py:188-225` | Prints binding layers; no grants line. |
| Browser Ships list | `peer/superyak_peer/static/app.js:681-685` | Name, owner, machine, last seen, revoke key. No grants. |

**Nothing else exists.** `grep -i grant` over `peer/`, `agent/` and their tests finds no grant table, route, helper,
tool or UI (only the unrelated layer-audience and role wording above).

---

## 2. What step 3 needs that does not exist at all

Station:

1. Tables `grants`, `grant_pins`, `budget_uses` (and, see 3.12, somewhere to store acceptances and revocation
   signatures; `revision_signatures`). A new `GRANT_SCHEMA` joined at `db.py:62` and a new mixin on `Store`
   (`db.py:48`).
2. A policy-in-force function returning the no-charter defaults (nothing like it exists).
3. Chain walk and validity check with plain reasons; room matching for lists and `"*"`; subset check.
4. Root creation, delegation, acceptance, revocation (person and ship), listing (person and ship).
5. Ticket basis 3 (`build`/`grant`), `budget_uses` inserts per link, the per-ship 24 h build cap, footer for a chain.
6. `instruct` binding (rule 3), pin/follow, pending revisions, owner-first-then-instructors ordering, caps checked
   for granted ships, and a way for an owner to read another person's layer addressed to the owner's ship (today
   `_access_routes`, `layers.py:167-180`, gives the ship's owner no route to it).
7. Signing: give the store the identity; sign grants, revocations and instructions revisions; backfill signatures
   for revisions activated before this step (the station law layer c879372542444e4c8f95f2c0db69f8fb is one);
   `identity.verify_record`; two `/signed` routes; `<peer id>:<id>` export form.
8. Restore reconcile for grants (section 3.14).
9. API.md sections: grants, signed records, ticket basis `grant`; replace "a label, not a cryptographic signature;
   that comes in a later step" (`peer/API.md:238`); update the binding rule (`API.md:244-246`) and Run tickets
   (`API.md:887-907`).
10. Release inventory: a new module and new test files must be listed in `peer/pyproject.toml` (explicit file
    lists, e.g. :81, :128, :167).

Browser (`app.js`, one 1,838-line file):

11. A grants page: route, nav link, loader, view, forms, actions.
12. Grants per ship in the Ships section; pending acceptances; pending instruct revisions with a line diff
    (no diff code exists: `grep -i diff app.js` is empty).
13. The instructions editor must offer ships the author holds `instruct` over (today `shipChoices`,
    `app.js:370-374`, offers only the author's own ships, and the copy says "Only your own ships can read
    instructions").

Agent:

14. `StationClient` methods and MCP tools `station_grant`, `station_grants` (`mcp.py:507` TOOLS has neither);
    a grants line in `superyak-agent status`; fake-station routes in `agent/tests/conftest.py` (it 403s every
    unknown route at :470).
15. Bracketed titles in the hook's list line (`agent/superyak_agent/hook.py:301`) and in `render_one`, per HANDOFF
    (below).

---

## 3. Conflicts and drift since 2026-10-08

### 3.1 Ship ownership

Matches the spec. `users.kind='ship'` plus `users.owner_id` (`ships.py:52`). Ownership never changes, so "the
root's issuer must still own every target" (spec 199) is always true in practice; keep the check for restored or
hand-edited databases. Residents have no owner, so they can never be root targets. The system author is a
`users` row with `kind='system'` (`system_author.py:23-24`); grant code must refuse it as grantee or target.

### 3.2 Rooms change id when members are added (largest drift)

`add_participants` makes a **new linked room** with a new id (`chats.py:111-126`, new id at :121). Since
2026-10-08 this became routine: `make station-bridge` adds Wormhole this way (`ships.py:241-272`), and briefs and
open board items now carry into the new room (`chats.py:122-125`). A grant whose `rooms` lists the old id stops
covering the current room the moment Andy adds anyone or bridges. Spec A does not mention replacement. The current
room test already exists as one shared subquery, `REPLACED_ROOMS` (`common.py:9`).

Decision needed: follow the `linked_room_id` chain forward (covers the replacement, which may have more members),
or stop and let the owner re-grant. (Question 2.)

### 3.3 `"*"` and breakouts

Breakouts landed (2026-10-11). They are ship-owned, ships-only rooms of one owner's ships
(`breakouts.py:1-3,78-93`). The breakouts spec already writes step 3's rule: "A grant's `rooms: "*"` never includes
breakouts" (S11, breakouts spec 142-143) and "R14 ... once spec A step 3 exists. The requirement is written now so
step 3 inherits it" (175-176). Also needed, by the same logic: refuse a breakout id in an explicit `rooms` list,
refuse remote room ids (`:` in the id; tickets only exist for local messages, `tickets.py:49`), and decide whether a
replaced room counts as "shared" (`send_message` still accepts posts there, `chats.py:69-109`). For basis 3 the
grantee is a person, who is never in a breakout, so this only bites for ship grantees (step 5) and for delegation's
subset check. Spec 171 says "the acting ship"; for a person grantee it should read "the grantee".

### 3.4 Later specs expect new grant actions

- Work board (2026-10-14, 527-529): "When spec A step 3 lands, a grant such as "board" from the room's owner can
  widen who writes." Today a board writer is the room owner or the owner's ships (`room_board.py:104-110`).
- Ship room briefs (2026-10-14, 93-94 and 588): "Letting another owner's ships write waits for grants (spec A step
  3)." Today `save_ship_brief` allows only the room owner's ships (`briefs.py:166-168`).

Spec A allows only `direct` (and `instruct`); `delegable ⊆ {direct}` and `merge`, `deploy`, `admit` are reserved
(94-95). A `board` or `brief` grant is also a different shape: its scope is a room the issuer owns, not ships the
issuer owns. This needs a spec amendment or an explicit "not in step 3". (Question 9.)

### 3.5 Work board claims and ship-status claims vs grant budgets

No conflict. Claims (`room_claims.py`, board claims) are advisory coordination; their caps are counts of active
claims. Grant budgets are build tickets per 24 h. Only the word "budget" is shared (also the watcher's
five-an-hour ship budget and the 30-a-minute post budget, `ships.py:332-337`). The plan should name the new one
"grant budget" in messages to avoid confusion.

### 3.6 Ship status and deferrals

Compatible. Deferral only applies to `read` decisions (`tickets.py:63`). A `build`/`grant` decision is never
deferred and spends its budget once, at ticket insert; the watcher's retries reuse the running ticket
(`tickets.py:57-61`). The directory already counts running tickets as live runs (`presence.py:127-133`), so grant
builds show up there with no change.

### 3.7 Many ships on one machine

The many-ships spec S11 (288-290) says per-ship keys "separate provenance, not authority: an unsandboxed session of
either ship can read both homes, so spec A's per-ship grants must not assume one ship can't use another's key."
D7 ("Grants, budgets and keys are per ship") still holds for accounting, but a grant to `serenity-bricks` is
effectively usable by `serenity` on the same Mac. The plan's security text should say so; it does not change the
design.

### 3.8 Signatures today, and what spec A signs

- Today the station key signs only federation envelopes (`identity.py:132-138`). Activation "labels it with its
  owner's name (a label, not a cryptographic signature; that comes in a later step)" (`API.md:238`).
- Spec A: "The station signs the canonical JSON (identity.canonical) of each grant record (all columns except
  `signature` and the revocation fields) with its Ed25519 identity key, and signs each revocation as `{grant,
  revoked, revoked_by, reason}`. It signs each instructions-layer revision as `{station, layer_id, revision,
  owner_id, title, body, policy, created}`, stored in `revision_signatures(layer_id, revision, signature)`" (365-370).
  Personal signing keys are out of scope (494). So a grant's `signature` column is the **station's** Ed25519
  signature. It attests "this station recorded this grant from this authenticated person or ship", not a
  person's own key.
- Plumbing gap: the identity lives on `app.state.federation`, not on `Store` (`federation.py:16`). Store methods that
  insert grants inside a transaction need a signer. Simplest: pass the identity into the store in `create_app`, or
  have the store load it from `data_dir` the same way. CLI paths construct `Store(args.data_dir)` without
  `Federation` (`__main__.py:158,261-305`); none creates grants, but a reconcile that revokes grants would need to
  sign revocations or leave them unsigned (decide).
- Gaps in the spec text: the `grants` table has no column for the revocation signature (3.12). The revision record
  omits the audience, so a signature does not say which ships a revision bound (narrowing makes a new revision with
  the same signed fields except `revision`). `created` and `expires` are floats; `canonical()` uses Python float
  repr, which another implementation may not reproduce. Neither blocks step 3.
- Backfill: revisions activated before step 3 (including the station law) have no signature. Sign them once at
  startup, from the stored snapshot and `layer_revisions.created`.

### 3.9 Policy defaults with no charter

Spec A, Compatibility (382-384): "With no charter active, roots are browser grants only, the grantee set is
unrestricted, and these defaults apply: depth 3, 720 hours, 24 hours for agent-issued grants, 20 builds per ship
per day, 10 directs per ship an hour, a breaker of 30 directs an hour, 3 ships for the same task, and 200
characters for echoes."

So for step 3: `max_depth` 3, `max_expiry_hours` 720, `agent_grant_default_hours` 24,
`builds_per_ship_per_day` 20, grantee set unrestricted. `delegable` is **not** listed; the policy example (86) and
the bound "`delegable` ⊆ {`direct`}" (94) make `["direct"]` the only possible value. Bounds (94): depth 0–5, expiry
1–2,160 h, budget 0–500. No default root budget or root depth is given; the grants page needs defaults (plan
choice). "Unrestricted" literally includes ownerless ships (Wormhole relays lattice text) as grantees; the system
author must be excluded regardless.

### 3.10 Person endpoints, CSRF, ship endpoints

Ready. Person routes use `actor()`/`current_user()` (`app.py:88-112`): ship keys get 403, CSRF is checked on every
write, and `BrowserBoundary` enforces same-origin writes (`app.py:40-43`). Ship routes use `ship_member()`
(`app.py:104-109`). Spec Testing 3 ("a ship key gets 403 when it tries to create a root grant") follows from using
`actor()`. New `/api/ships/me/grants*` routes must use `ship_member()`; `/api/grants*` must use `actor()`.

### 3.11 Browser structure for a new page

`app.js` is one file with a hash router. To add a page: add the route name to the whitelist in `routeParts`
(`app.js:139-143`), a `navLink` in `layout` (:160-168), a view function in the map in `render` (:853) and a title
(:873), a loader in `loadRoute` (:805) or `loadData` (:770-800), and `data-action` handlers in the click dispatcher
(e.g. `revoke-ship` at :1626). `api()` adds the CSRF header for writes (:120-122). Browser tests are Playwright in
`peer/tests/test_browser.py` (2,282 lines; e.g. :1580 for instructions). `/api/board` exists as a person route
(`app.py:574-576`) but no page uses it yet, so there is no recent page to copy; the Ships section on Connections
(:729-736) is the nearest pattern.

### 3.12 Gaps inside spec A's step 3 text (found while mapping it to code)

- **Acceptance has no storage.** Children to another owner's ship need `POST /api/grants/{id}/accept` (190-191),
  validity needs "accepted where acceptance is required" (196), but `grants` has no `accepted` column and "rows
  never change" (171-172).
- **Revocation signature has no column** (signed per 367-368; table at 160-164 has only `signature`).
- **Session label has no column.** D7 (36) and Concepts (57-59) say every act records one; `grants` lacks it. The
  `X-Superyak-Session` header already supplies it for ship calls.
- **Budget on `instruct` grants.** Validity says every link needs budget left (197-198). An `instruct` grant has no
  builds, so a budget of 0 would make it invalid. Validity for `instruct` must skip budget (and depth).
- **Root acceptance.** The acceptance rule is stated for children only. A root from Andy to Jenn's ship is not
  covered.
- **Depth counting.** "Its length must be at most `max_depth`" (199-200), "its depth is lower" (188). Whether the root
  counts as one link (root depth ≤ max_depth − 1) is open.
- **Caps without activation.** Caps are enforced "by activation" (75-77, 123), but creating an `instruct` grant, or
  accepting a pinned revision, binds already-active layers with no activation. It can push a ship past 10 layers or
  48 KB unless refused there too.
- **Pinned person layers.** For the charter, a pinned old revision keeps binding (115-118). For an `instruct` grant
  pinned at r1, the spec does not say what binds after the instructor activates r2, narrows the audience, or
  withdraws.
- **Expiry of `instruct` roots.** "Browser roots obey ... `max_expiry_hours`" (201-202), so a person-to-person
  `instruct` grant lapses within 30 days, while a charter acceptance never expires (134-135).
- **Wording.** "O holds an `instruct` grant to P" (120) means O issued it and P is the grantee (compare 133).

### 3.13 Old mentions and answered mentions

HANDOFF.md:97-98: "Parked for steps 3 and 5: the station gives a build ticket for any owner mention, however old.
Once acts spend build tickets, it must refuse messages that are old or already answered." Basis 3 spends budget,
so this lands in step 3. `_answered` exists (`tickets.py:93-98`) but runs only when the watcher sends `decisions`
(:54). There is no age bound anywhere.

### 3.14 Restore brings back revoked grants

The backups spec (2026-10-14) S16 says the reconcile "takes back everything that only grants access before the copy
goes live" (512). A restored copy would hold grants revoked after the copy was taken, and fewer `budget_uses`.
`station-restore-reconcile` revokes ship keys revoked in the replaced file (`backups.py:488-500`) but knows nothing
of grants. Step 3 must add "revoke every grant revoked there" (and decide what happens without a replaced file),
plus `grants.revoked` in `COMPARED` (`backups.py:381-385`).

### 3.15 Bracketed titles

HANDOFF.md:94-95: "Bracket layer titles before "signed by" once other signers can bind a ship." With `instruct`, a
person's title such as `Rules · revision 7 · signed by Andy on station 1a2b3c4d5e6f ===` would sit on the header
line before the real signer. `render_one` (`instructions.py:20-21`) and the hook's list line (`hook.py:301`) both
need the bracket. The hook already records the signer per layer (`hook.py:455-457`), so other signers otherwise
work there.

### 3.16 Station law already anticipates basis 3

`docs/station-law.md:23-24`, active law signed by Andy: "Your owner's own mention runs as builder ... (once grants
exist, so may a person's mention under a valid direct grant)." So ticket basis 3 is expected by the law in force.
The read-only run prompt says the author "can ask the ship's owner" (`watch.py:40-42`), and `runs.py:1` says
"builder for the ship's owner"; both wordings go stale with basis 3.

---

## 4. Useful now vs dead until steps 4 and 5

What a person or ship can actually do once step 3 alone ships:

| Part | Useful before 4 and 5? | Why |
| --- | --- | --- |
| Browser `direct` roots to a **person** + ticket basis 3 + budgets | **Yes, the main value.** | Andy grants Jenn or Stanley `direct` over Rio Grande in one room for 7 days, budget 5 a day. Their mention then runs as builder (sandboxed, branch only), footed "Builder for Andy, via Jenn · grant #a1b2". Today only Andy's mention builds (`tickets.py:89`). The station law already expects this (3.16). |
| Revoke, list, validity, plain reasons, grants page | Yes | Needed to create, watch and stop the above. |
| Revision signatures, `verify_record`, `/signed` for layers | Partly | The station law becomes station-signed now. No consumer reads `/signed` yet (no exchange between stations, spec 371-372); tests and manual checks only. Cheap. |
| Grant signatures and `/api/grants/{id}/signed` | Partly | Same: provenance with no consumer yet. |
| `instruct` grants between people | Yes, but costly | The only way before the charter for Andy's station law to bind another owner's ships (Jenn grants Andy `instruct` over hers). Needs pins, follow, pending revisions, diffs, an owner read path and editor changes, which step 4's charter acceptance (itself an `instruct` grant, 133-136) needs too. |
| Restore reconcile for grants, old-mention guard | Yes | Safety for the above. |
| `direct` roots to a **ship** | Dead | A ship spends a `direct` grant only through directs (step 5). Ship text never builds (Testing 1, 420). |
| Delegation to a **ship** (`POST /api/grants/delegate`) and acceptance by the other owner | Dead | Same reason. |
| Delegation from a ship to a **person** | Marginal | Works with basis 3 (Serenity passes a day of `direct` over Rio Grande to Stanley), but no one has asked for it. |
| `confirm: each` | Nearly dead | Its only step-3 effect is that basis 3 refuses chains containing it (302). Confirmation is a directs feature. |
| `ticket_id` confused-deputy rule on delegate | Dead | Builder runs get the `ticket` MCP server in step 5 (276-279). |
| `station_grant` tool | Dead-ish | Only delegation; see above. |
| `station_grants` tool, status grants line | Small | Lets a session see what its ship holds. |
| Hops, breaker, directs, `direct_id` on mentions | Not step 3 | Step 5. |
| Narrowing via charter, charter roots, widening | Not step 3 | Step 4. Step 3's validity must still read the policy through one function so step 4 can swap it in. |

---

## 5. Suggested split (dependency order)

Each piece merges on its own under the interim rule, with its own tests. Sizes are rough and include tests.

**Piece 1. Station-signed instruction revisions.** (No grants.)
- Give `Store` the station identity (or a signer); `revision_signatures` table; sign each instructions revision at
  activate and narrow (`layers.py:106-165`); backfill at startup for active revisions without one;
  `identity.verify_record`; `GET /api/layers/{id}/revisions/{n}/signed` (person; owner, and later instructors' bound
  owners); bracketed titles in `render_one` and `hook.py:301` (harmless now, required before piece 5).
- Tests: verify against the card; one changed byte in record or signature fails; backfill signs once and is
  idempotent; ship key 403; a title imitating a header stays inside the bracket.
- Files: `identity.py`, `layers.py`, `instructions.py`, `db.py`, `app.py`, `hook.py`, `API.md`,
  `pyproject.toml`, two test files. About 8-10 files, 300-400 lines.
- Value alone: the active station law is signed.

**Piece 2. Grants core: browser `direct` roots, validity, revoke, read, signatures.** (Depends on 1 for the signer.)
- New `grants.py` mixin: schema (grants, budget_uses, acceptances, revocation signature, session label), policy
  defaults behind one `_policy(db)` function, chain walk, validity with plain reasons, room matching (lists and
  `"*"` minus breakouts, remote and system rooms, per 3.2-3.3), subset helper (used by piece 4), root creation,
  person revoke with reason, `GET /api/grants`, `GET /api/grants/{id}/signed`; restore reconcile revokes grants
  revoked in the replaced file (`backups.py`).
- Tests: root rules (own ships only, residents and system author refused, expiry ≤ 720 h, depth ≤ max, budget
  0–500, breakout and remote room ids refused); validity walk (expired, revoked above, owner changed by hand);
  revoke permissions (issuer, above, target owner; admin 403); ship key 403 on every person route; signatures verify
  and tamper fails; reconcile revokes.
- Files: `grants.py` (new), `db.py`, `app.py`, `backups.py`, `API.md`, `pyproject.toml`, 1-2 test files. About 7
  files, 800-900 lines.
- Value alone: none visible yet; a foundation with an API.

**Piece 3. Spending: ticket basis `grant`, budgets, and the grants page.** (Depends on 2.)
- `_mode_for` basis 3 (person grantee, valid chain for this ship and room, no `each` link, budget at every link,
  ship under 20 grant builds a day); one `budget_uses` row per link at insert; `chain` and `root_id` on the ticket;
  footer "Builder for <root>, via <grantee> · grant #xxxx"; old/answered guard for grant builds (3.13); stale
  wording in `watch.py:40-42`.
- Browser: `#grants` page (issued, held, covering my ships, each with validity and budget left; create a `direct`
  root to a person or ship with targets, rooms, hours, budget, depth; revoke with reason); grants per ship in the
  Ships section.
- Tests: Testing 1's table without directs (author × none/valid/expired/revoked above/out of scope/over budget);
  revoke between mention and ticket gives `read`; retries reuse one ticket and one budget use; budget holds across a
  chain; builds-per-day cap; footer and `source` match the ticket; a `read` grantee mention still defers on watch;
  browser test for the page.
- Files: `tickets.py`, `grants.py`, `app.js`, `app.css`, `watch.py`, `API.md`, `test_tickets.py` or a new test,
  `test_browser.py`. About 8 files, 700-900 lines.
- Value alone: **the first user-visible grant**: another person's mention builds your ship, within scope and budget.

**Piece 4. Delegation and ship-side reading.** (Depends on 2; uses 3's budget display.)
- `POST /api/grants/delegate` (ship key, subset rules, default 24 h, depth lower, budget no larger, grantee rules,
  session label from `X-Superyak-Session`); acceptance by another owner (`POST /api/grants/{id}/accept`, person) and
  its browser control; `GET /api/ships/me/grants`; `POST /api/ships/me/grants/{id}/revoke`; agent client methods,
  `station_grant`, `station_grants`, status line; fake-station routes. `ticket_id` may be accepted and checked, or
  left for step 5.
- Tests: property test "a child is never wider than its parent, field by field"; depth limit; another owner's ship
  invalid until accepted; ship revokes only what it issued; agent tool refusals print the station's reason.
- Files: `grants.py`, `app.py`, `app.js`, `agent/superyak_agent/station.py`, `mcp.py`, `__main__.py`,
  `agent/tests/conftest.py`, `API.md`, 2-3 test files. About 10 files, 600-800 lines.
- Value alone: small (ship → person children); mostly groundwork for step 5. Could move to step 5.

**Piece 5. `instruct` grants between people.** (Depends on 1 and 2; independent of 3 and 4.)
- `instruct` roots (person to person, targets the owner's ships, pin or follow, `grant_pins`); binding rule 3 in
  `_binding_layers` with order owner then instructors by grant age, and the same order in `_layers_for`; caps checked
  for granted ships at activation and at grant creation and pin acceptance; owner read path for an instructor's
  layer addressed to the owner's ship; editor offers granted ships; pending revisions with a browser line diff and
  per-revision accept.
- Tests: extend the oracle to grants, pins and follows (500 seeded cases, spec Testing 2); an unauthorized signer's
  layer never binds; revoke or expiry unbinds at once; caps refuse an 11th layer from a new grant; bracketed titles.
- Files: `grants.py`, `instructions.py`, `layers.py`, `app.py`, `app.js`, `API.md`, `test_instructions.py`,
  `test_browser.py`. About 8 files, 800-1,000 lines.
- Value alone: law reaches other owners' ships before the charter. Shares most of its machinery with step 4.

Totals: about 3,200-4,000 lines over the five pieces. Pieces 1, 2, 3 are the minimum that makes step 3 useful.

---

## 6. Open questions (Andy's decision or a spec amendment)

Andy's decisions:

1. Does step 3 include ticket basis 3 (a person grantee's mention builds the owner's ship), as the station law
   already expects, or does all grant spending wait for directs in step 5?
2. Should a grant naming a room keep covering the room that replaces it when members are added or it is bridged (as
   briefs and board items carry), or stop until the owner grants again?
3. Should `instruct` grants between people be built in step 3 as the build order says, or move to step 4, where
   charter acceptance needs the same pins, follow, pending revisions and diffs?
4. Should a browser `instruct` grant lapse at 720 hours like a `direct` root, or never expire like a charter
   acceptance?
5. Should step 3 add room-scoped actions such as `board` and `brief`, which the work-board and ship-briefs specs say
   will come "through grants", or leave them for a later spec?
6. How old may a mention be and still get a grant build ticket (and should the same bound apply to owner builds)?
7. With no charter, may ownerless ships (Wormhole, Odo) hold grants, given "the grantee set is unrestricted"?
8. Should delegation by ships (piece 4) ship in step 3, given that before directs it only lets a ship pass a grant to
   a person?

Spec amendments (the spec text is silent or inconsistent):

9. Add storage for acceptances and for revocation signatures, since "rows never change" and the table has neither.
10. Add a `session_label` column to grants (D7 says every act records one), filled from `X-Superyak-Session`.
11. Say whether a root grant to another owner's ship needs that owner's acceptance, as children do.
12. Say whether chain length counts the root as a link.
13. Say that budget and depth checks skip `instruct` grants, so a budget of 0 does not invalidate them.
14. Say what binds when an instructor activates r2, narrows or withdraws a layer the owner pinned at r1.
15. Refuse (409) an `instruct` grant or a pin acceptance that would push a covered ship past 10 layers or 48 KB, since
    no activation happens then.
16. Say whether `"*"` excludes replaced rooms and remote rooms, and refuse breakout ids in explicit room lists (R14
    covers only `"*"`).
17. Say whether the revision signature should cover the audience, which today it omits.
18. Say what the restore reconcile does with grants when there is no usable replaced file.
