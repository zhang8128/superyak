# Survey: spec A step 4 (the charter) against main at c29e91e

Date: 2026-10-15. Read-only survey, the input for the step 4 spec. Nothing in the repository was changed except this
file.

References:

- "spec A" is `docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`; "A:n" is its line n.
- "step3:n" is the step 3 design, `2026-10-15-grants-step3-design.md`; "survey3:n" is its survey,
  `2026-10-15-grants-step3-survey.md`.
- "law:n" is `docs/station-law.md`; "roadmap:n" is `docs/superpowers/plans/2026-10-12-station-roadmap.md`.
- Code paths are relative to the repository root, at main c29e91e (grants step 3 complete: 3a, 3b and 3c).

---

## 1. What step 4 must deliver, by spec A's own words

Build order item 4 (A:486): "The charter. Policy, widening against baselines, acceptance as grants, charter roots."
Step 2's note (A:481-483) leaves "signatures, diffs and the Ships status view" to steps 3-4. Step 3 built the
signatures only. The step 2 plan put "the charter, policy, widening and acceptance" and "revision diffs and the Ships
status view in the web app" in step 4 (`docs/superpowers/plans/2026-10-08-instruction-layers.md:41-44`).

**1.1 The `charter: true` flag.**
- `FIELDS` gains `kind`, `charter` (bool, default false), `policy` (object or null) and `drafted_by` (A:63-65).
- "`charter: true` requires an empty audience: a charter addresses every ship whose owner accepts it. Only an admin
  may activate a charter, and while one charter layer is active, activating a second is refused with 409" (A:71-72).
- Concepts: "the station's single active instruction layer with `charter: true`, signed by an admin. It has prose
  for agents and a `policy` object that the station enforces" (A:48-49).
- The caps apply to every ship a charter binds: 10 layers, 48 KB of rendered blocks, 409 otherwise (A:75-77, A:123).
- Ships draft charters too: `POST /api/ships/me/drafts {title, body, charter?, policy?}` (A:126).
- Compatibility: "plus four keys in layer drafts" (A:377).

**1.2 `policy` and its schema.**
- "`policy` is allowed only on a charter. It is validated against the schema below; unknown keys are rejected with
  400" (A:73).
- Version 1 (A:84-92): `delegation {max_depth, max_expiry_hours, agent_grant_default_hours, delegable}`, `budgets
  {builds_per_ship_per_day}`, `grantees {people, ships_of}`, `roots [...]`, `breaker {directs_per_ship_hour,
  directs_per_hour, same_task_ships, echo_chars}`.
- Bounds (A:94-96): "depth 0–5, expiry 1–2,160 hours, budget 0–500, at most 50 roots and 100 grantees. `delegable` ⊆
  {`direct`}; `merge`, `deploy` and `admit` are reserved names that spec B adds. A root's `owner` must be the
  charter's signer or a person who accepts that revision, and its targets must be that owner's ships."
- The station signs each instructions revision as `{station, layer_id, revision, owner_id, title, body, policy,
  created}` (A:369-370), so the policy is under the signature.

**1.3 Widening and `confirm_widenings`** (A:98-110).
- "A widening is any numeric limit that grows, any set that gains a member, or a root that is added or widened. The
  station computes the widened paths field by field, always against a named baseline."
- On activation the baseline is "the previous active revision, or for a first charter the no-charter defaults".
  "Activation needs `confirm_widenings` equal to the station's list of widened paths ... (the web app shows one
  checkbox per path)" (A:101-103).
- On acceptance the baseline is "the revision that owner last accepted, never the previous revision". A first
  acceptance compares with the no-charter defaults, "and each root that names the owner is also listed for
  confirmation". "Follow" moves an owner forward only to a revision with no widening against their own baseline;
  otherwise the revision shows as pending (A:104-108).
- "Limits other than roots (delegation, budgets, grantees, the breaker) apply station-wide from activation ... Roots
  apply only to owners who accepted them" (A:109-110).
- Tests: a hidden widening is refused unless confirmed; "Follow" never takes a widening, across several revisions
  (A:463-465).

**1.4 `GET /api/charter`.** "(person) returns the active charter, the caller's acceptance, and any pending revision
with its widened paths" (A:131-132).

**1.5 Acceptance as an `instruct` grant (pin or follow).**
- "`POST /api/charter/accept {layer_id, revision, follow, confirm_widenings}` (person, CSRF) records the acceptance as
  an `instruct` grant from the caller to the charter's signer. Its targets are `"own"`, meaning every ship the caller
  owns now or docks later. It has no expiry (`expires` is the maximum value) and stays until revoked. Its pin is that
  revision, and `follow` is stored" (A:132-136).
- "An admin who activates a charter has accepted it" (A:136-137).
- `grant_pins(grant_id, layer_id, revision, accepted)` (A:165-166). "`targets` may be `"own"` only on a charter
  acceptance" (A:170).
- Binding rule 1 (A:115-118): the revision O accepted, pinned, or with follow "the newest without a widening against
  O's baseline". A pinned revision that is no longer active "keeps binding O's ships (O consented to that text). But
  its roots are superseded".
- Testing 3: a ship key gets 403 when it tries to accept a charter (A:433).

**1.6 Charter roots as grant rows.** "Charter root clauses are materialized as root rows, with `charter_layer_id`
and `charter_revision` set, when the signer activates the revision or an owner accepts it. When a newer revision
replaces them, the old rows are revoked with reason `superseded`" (A:176-179). Validity: "for a charter root the
charter revision must still be active and accepted" (A:197). With no charter, "roots are browser grants only"
(A:383).

**1.7 The grantee set.** Shape `{"people": [...], "ships_of": [...]}` (A:88), at most 100 (A:94). Checked when a
root is made "when a charter is active" (A:175), at delegation (A:189), and at every validity check against the policy
in force now (A:200-201). With no charter it is unrestricted (A:383).

**1.8 `max_depth`, `delegable`, `max_expiry_hours`, `builds_per_ship_per_day`.**
- Validity checks chain length against `max_depth`, ship-issued links against `delegable`, and roots against
  `max_expiry_hours` and the grantee set, using the policy in force now: "So narrowing the charter takes effect at the
  next check" (A:198-202).
- Delegation defaults to `agent_grant_default_hours` (A:187).
- Ticket bases 1 and 3 need the ship "under the charter's `builds_per_ship_per_day`" (A:306-308).
- Test: "Narrowing the charter's `max_depth` or `delegable` invalidates existing longer chains at the next ticket"
  (A:459).

**1.9 Resident ships.** "Resident ships (no owner) are bound only by the charter, which binds them automatically when
an admin activates it" (A:123-124).

**1.10 The footer's charter revision.** "`Builder for Andy (owner) · charter r3` or `Builder for Andy, via Serenity ·
grants #a1b2 > #c3d4 · charter r3`" (A:310-311).

**1.11 Prompt order.** "charter, then owner, then granted instructors by grant age" (A:139-140).

**1.12 Status.** "`superyak-agent status` prints the binding layers and revisions, any pending charter revision, the
grants the ship holds with their budget left, and any breaker on the ship. The web app's Ships section shows the same
for each ship" (A:360-362). Grants held by ships and breakers are step 5.

**1.13 The web views.** One checkbox per widened path at activation (A:103). "The web app shows each revision against
the one before it, and a pending revision against the pinned one, as a line diff computed in the browser" (A:154-155).
The browser tests cover "the charter acceptance with checkboxes for widened paths" (A:472-473).

**1.14 Compatibility: no-charter defaults.** "With no charter active, roots are browser grants only, the grantee set
is unrestricted, and these defaults apply: depth 3, 720 hours, 24 hours for agent-issued grants, 20 builds per ship
per day, 10 directs per ship an hour, a breaker of 30 directs an hour, 3 ships for the same task, and 200 characters
for echoes" (A:383-385).

**1.15 Tests that fall in step 4.** Testing 2's oracle "for random owners, signers, grants, pins and follows ... 500
cases" (A:424-426); Testing 3's "accept a charter" (A:433); Testing 6's narrowing, hidden widening and follow items
(A:459, A:463-465); the browser test (A:472-473).

---

## 2. What already exists on main

### 2.1 Item by item

| Item | Evidence | Today |
| --- | --- | --- |
| `charter`, `policy` fields | `peer/superyak_peer/layers.py:5-7`, `:11-12` | `FIELDS` has `kind`, title, body and the audience fields. Any other key is refused with 400. `drafted_by` and `drafted_at` are server keys. A grep for `charter` over `peer/` and `agent/` finds only the grants columns and docstrings. |
| Instructions checks | `layers.py:25-39` | One-line title of at most 200, body at most 20,000, no NUL, ships only, at most 50 ships. An empty audience passes at draft. |
| Rollback rule | `layers.py:48-49` | A note's `kind` is never stored: "a rolled-back station refuses any key it does not know". |
| Activation | `layers.py:106-132`; `peer/superyak_peer/app.py:467-470` | Owner only (`_owned_layer`, `layers.py:52-53`). Takes `version` and `space_versions`; no `confirm_widenings`. Caps for instructions (`:112-113`). Writes and signs the revision (`:127-129`). No admin check, no one-charter check. |
| Caps | `peer/superyak_peer/instructions.py:94-103` | Refuses an empty audience with 400 (`:95-96`). Checks only ships the activator owns (`:99-100`). Pinned by `peer/tests/test_instructions.py:156-164` and `:166-178`. |
| Withdraw, narrow | `layers.py:134-141`, `:143-167` | Withdraw clears `active_revision` and bumps `resource_version`, so the next activation skips a number. Narrowing writes and signs a new revision (`:162-164`) even when nothing is removed. Neither knows charters. |
| Who can read a layer | `layers.py:169-182`, `:225-228` | Routes are owner, audience person, space, public. A charter (empty audience, not public) is readable by its owner only. Revision history is owner only. |
| Binding | `instructions.py:78-92` | The owner's own active instructions layers whose audience lists the ship. Residents get none (`:80-81`; pinned by `test_instructions.py:256-260`). Sorted by `(created, layer_id)` (`:92`), not charter first. Docstring `:1-3`: "Grants (step 3) and the charter (step 4) add to this rule". |
| Rendering | `instructions.py:19-25`, `:29-41` | `render_one` prints `signed by <owner name>`, from `layers.owner_id` (`:33-40`), so a charter renders with its signer's name. Titles are not bracketed. `_layers_for` re-sorts by `created` (`:41`). |
| Ship read route | `instructions.py:43-49`; `app.py:232-238` | `{instructions, layers, blocks}` plus an optional `agent_update`. No pending-charter field. |
| Ship drafts | `instructions.py:51-76`; `app.py:240-243`; `agent/superyak_agent/mcp.py:534`; `agent/superyak_agent/station.py:239-240` | Title and body only (`instructions.py:53-54`), addressed to the drafting ship (`:71-72`). The tool's text says "Draft instructions for this ship". |
| Policy in force | `peer/superyak_peer/grants.py:54-58` | `_grant_policy(db)` returns the no-charter defaults as a flat dict with `grantees: None`. Readers: validity (`:100-113`), making a grant (`:273-278`), the grant view (`:182`, `:193`), tickets (`peer/superyak_peer/tickets.py:153`). Nothing reads `delegable` or `agent_grant_default_hours` yet. No breaker keys. |
| Grant columns | `grants.py:11` | `parent_id`, `charter_layer_id`, `charter_revision` and `follow` exist. Every row leaves them empty (`_insert_grant`, `:60-70`; `peer/tests/test_grants.py:489-490`). They are in the signed record (`peer/superyak_peer/signatures.py:133-138`; `peer/superyak_peer/identity.py:79-81`). |
| `grant_pins` | `grants.py:10-14` | Not created. No code reads a pin or `follow`. |
| Validity | `grants.py:95-122` | Walks to the root. In order: revoked, expired, lifetime at most `max_expiry_hours` (`:110`), chain length at most `max_depth` and grantee in the set (`:112`), budget (`:114`), the root's issuer owns every target (`:117-121`). No charter check. Narrowing tests replace `_grant_policy` (`test_grants.py:37-39`, `:83-97`, `:124-138`; `peer/tests/test_grant_tickets.py:365`). |
| Making a grant | `grants.py:268-282`; `app.py:493-497` | `direct` only, a person grantee, the caller's own ships, `hours` up to the policy's `max_expiry_hours`, budget 1 to 500. The grantee set is not checked at creation. |
| Signed revisions | `signatures.py:84-101`, `:103-112`; `identity.py:76-78` | The record's keys are fixed and include `policy`, always `None` (`signatures.py:94`). No `charter` key. Unsigned instructions revisions are signed at start. |
| `/signed` for revisions | `signatures.py:114-124` | Owner only (`:118`). Step 3 says "Step 4 adds the owners whose ships a revision binds under an `instruct` grant" (step3:164-165). |
| Ticket footer | `tickets.py:53-64` | `Builder for X (owner)` and the grant form. No charter part. |
| Ticket instructions | `tickets.py:108-110`, `:73` | Stores the binding `[layer_id, revision]` pairs at issue and renders them through `_layers_for`. |
| Residents' tickets | `tickets.py:133-134` | A ship with no owner always reads. |
| Admins | `peer/superyak_peer/auth.py:117-120`, `:157-183` | `_admin` checks `is_admin` and not pending. A super admin can change any role at any time. Nothing ties a layer to a role. |
| Restore | `peer/superyak_peer/backups.py:506-560`, `:736-745`, `:974-977` | Revokes every grant revoked or missing in the replaced file, or every grant when there is none (`:518-527`). Law layers whose active revision differs are reported, not applied. |
| Agent status | `agent/superyak_agent/__main__.py:218-224` | One line per binding layer: title, revision, signer. No pending charter. |
| Hook | `agent/superyak_agent/hook.py:300-301`, `:450-491` | The header line is unbracketed. Change and withdrawal notices are keyed by layer id and revision (`:455-456`, `:471`). |
| MCP `initialize` | `mcp.py:576-597` | Sends the station's `blocks` to clients that aren't Claude Code. |
| Watcher | `agent/superyak_agent/watch.py:195-201`; `agent/superyak_agent/runs.py:127-130` | Runs with the ticket's blocks after the persona, residents included. The footer comes from the ticket. |
| Fake station | `agent/tests/conftest.py:438-443` | Serves instructions and an owner footer. No charter. |
| Web app | `peer/superyak_peer/static/app.js:142`, `:372-400`, `:347-351`, `:1329`, `:685-760`, `:940-943` | No charter route. The editor offers "Instructions for my ships" with own ships only (`:372-375`, `:388`). Activation posts `{version, space_versions}` (`:1329`). No diff code. `:378`: "The Ships status view (what each ship has read, and when) is deferred to step 4." The grants page maps `grant.targets` as a list (`:743`). The Ships section shows no binding (`:940-943`). |
| API.md | `peer/API.md:246-248`, `:279`, `:326-328` | The binding rule is owner only; a revision's `policy` is `null`; "With no charter (step 4)". |

### 2.2 What step 3 built in step 4's direction

- One policy function, `_grant_policy(db)`, read by every check (`grants.py:54-58`). Step 3: "Step 4 swaps the
  charter in behind the same function without changing validity" (step3:78; G7 at step3:186-188).
- Validity reads the policy in force now, so a narrower charter takes effect at the next check (`grants.py:100-113`),
  with tests that narrow it (`test_grants.py:83-97`).
- The grant table carries `charter_layer_id`, `charter_revision`, `follow` and `parent_id`, and they are in the
  signed record, so charter rows sign without changing the record's keys (step3:180-184, G12 at step3:240-243).
- The revision record reserves `policy` ("`null` until step 4", step3:93), so a charter's policy signs without a new
  key set.
- Revisions are signed at activation and narrowing (`layers.py:129`, `:164`), and the law's revision 1 is signed
  (roadmap:31-32).
- The validity walk, visibility and revoke rules already walk a chain (`grants.py:72-82`, `:130-134`, `:284-287`).
- The lost-identity refusal and the restore reconcile for grants (`signatures.py:30-35`; `backups.py:506-560`).

### 2.3 What step 3 deferred to step 4, explicitly

- `instruct` grants between people, `grant_pins`, pins and follow, pending revisions, line diffs, caps checked at
  grant creation, bracketed titles, and other people's read path to a revision's signature (step3:61, S3 at step3:73).
  The reason given: "an acceptance is itself an `instruct` grant ... Building it twice costs more than building it
  once".
- The charter behind `_grant_policy` (S8 at step3:78; G7 at step3:186-188).
- `policy` in the signed revision record (G2 at step3:93).
- Readers of `/signed` beyond the owner (G6 at step3:164-165).
- From step 2: the Ships status view and diffs (`app.js:378`; the step 2 plan's lines 41-44).
- Not deferred to step 4: ship grantees, delegation, acceptance by another owner of a child grant, `confirm: each`,
  the ship grant routes and tools, and the status grants line all moved to step 5 (S2 at step3:72).

---

## 3. Gaps

### 3.1 Changes per file

**`peer/superyak_peer/layers.py`**
- `FIELDS` gains `charter` and `policy`. Store them only when set (`charter: true`, a non-null policy), as a note's
  `kind` is omitted (`:48-49`), so a rolled-back station still reads every other draft.
- `_draft`: `charter` is a bool; `charter: true` needs an empty `audience_users`; `policy` only on a charter,
  validated by the new module.
- `activate_layer` (`:106-132`): the admin check for a charter, 409 while another charter layer is active,
  `confirm_widenings`, caps over every ship the charter binds, the signer's acceptance, root materialization and
  supersession.
- `withdraw_layer` and `revoke_layer_routes` (`:134-167`): say what each does on a charter.
- Reading: `_access_routes` (`:169-182`) gives no one but the owner a route to a charter, so `GET /api/charter` must
  serve its text, and the pinned and pending revisions for the diff.

**A new module** (for example `charter.py`, a mixin on `Store` at `peer/superyak_peer/db.py:50`, its schema joined at
`db.py:64`, listed in `peer/pyproject.toml` beside `grants.py` at `:69` and `:160`, its tests beside `:110`)
- the policy schema, bounds, unknown-key refusal, and how missing keys take the defaults;
- widened paths against a baseline, as a stable list the client echoes back;
- `grant_pins`, the per-owner accepted revision (pin or follow) and pending revisions;
- `GET /api/charter` and `POST /api/charter/accept`;
- root materialization and the `superseded` revocations.

**`peer/superyak_peer/grants.py`**
- `_grant_policy` (`:54-58`) reads the active charter. It maps `delegation.*`, `budgets.*` and `grantees` onto the
  flat keys its readers use, and turns `{people, ships_of}` into a membership test (`:112` tests `in` a set today).
- `_grant_validity` (`:95-122`): for an `instruct` link, the budget check (`:114`) and the lifetime check (`:110`)
  can't hold as written (3.2, items 2 and 3); `"own"` targets (`:117`); the charter root check (A:197).
- `_owns_a_target` (`:124-128`) and `_grant_view` (`:191-193`): `"own"`.
- `make_grant` (`:268-282`): refuse a grantee outside the set (A:175).
- Visibility and revoking for acceptance grants.

**`peer/superyak_peer/instructions.py`**
- `_binding_layers` (`:78-92`): rule 1 (the charter the owner accepted, pinned or followed), residents bound by the
  active charter, and the order charter, owner, instructors.
- `_layers_for` (`:29-41`): keep the order the ticket recorded.
- `_check_instruction_caps` (`:94-103`): count the charter; check every bound ship at a charter activation and at an
  acceptance.
- `render_one` (`:19-21`): bracket the title (HANDOFF.md:111-112: "Bracket layer titles before 'signed by' once
  other signers can bind a ship"; a charter is the first such signer).
- `ship_draft` (`:51-76`): `charter?` and `policy?` (A:126); a charter draft has no audience.
- `ship_instructions` (`:43-49`): a pending-charter field for status.

**`peer/superyak_peer/signatures.py`, `identity.py`**
- `_revision_record` (`signatures.py:84-94`): the snapshot's `policy`. Whether the record marks a charter is open
  (3.2, item 9).
- `revision_signed` (`:114-124`): readers beyond the owner.

**`peer/superyak_peer/tickets.py`**
- `_footer` (`:53-64`): `· charter rN`.
- `_spendable_grant` (`:156-160`): `json.loads(grant['targets'])` on `"own"` gives a string, so `ship['id'] not in`
  becomes a substring test. The `direct` filter skips an `instruct` grant after that test, so it is harmless today but
  fragile.

**`peer/superyak_peer/backups.py`**
- The reconcile (`:518-546`) revokes acceptance grants like any other (risk 6.6).

**`peer/superyak_peer/app.py`**
- Activation passes `confirm_widenings` (`:467-470`). New `/api/charter` routes, person with CSRF; a ship key gets
  403 through `current_user` (`:88-97`).

**`peer/superyak_peer/static/app.js`**
- A charter route (`:142`) and page: the text, the caller's acceptance, the pending revision, its line diff, one
  checkbox per widened path, pin or follow.
- The editor: a charter choice for admins, the policy, no ships for a charter; the copy at `:388` changes.
- The activation dialog (`:347-351`, `:1329`): one checkbox per widened path.
- The Ships status view (`:378`, `:940-943`).
- The grants page: acceptance grants have `"own"` targets (`:743` maps a list).

**Agent**
- `__main__.py:218-224`: a pending-charter line.
- `hook.py:300-301`: the bracketed title.
- `mcp.py:534`, `station.py:239-240`: drafting a charter.
- `agent/tests/conftest.py:438-443`: the fake station.
- `agent/README.md:114`, `:142`: what binds a ship; status.

**`peer/API.md`** — Instruction layers (`:246-248`), Signed records (`:279`), Grants' policy (`:326-328`), Run
tickets' footer (`:1005-1047`), and a new Charter section.

**Tests** — `test_instructions.py:256-260` (residents bound by none) and `:166-178` (an empty audience is refused)
change meaning. The oracle (`:277-315`, 60 cases) grows to spec A's 500 with signers, pins and follows (A:424-426).

### 3.2 Where spec A is silent or contradicts step 3's built behaviour

Stated, not resolved.

1. **Targets `"own"`.** Spec A gives an acceptance `targets: "own"` (A:134, A:170). Step 3's code reads targets as a
   list everywhere: validity iterates it (`grants.py:117`), so `"own"` is read as the ship ids `o`, `w`, `n` and
   fails "no longer owns a ship that is gone"; also `:125-128`, `:191-193`, `tickets.py:159`, `app.js:743`.
2. **No expiry.** An acceptance "has no expiry (`expires` is the maximum value)" (A:134-135). Validity check 3
   refuses any lifetime over `max_expiry_hours` (`grants.py:110`; step3:209-211), and spec A itself says browser roots
   obey `max_expiry_hours` (A:201-202). "The maximum value" is not defined; `_utc` (`grants.py:49-50`) can't format a
   float near `sys.float_info.max`, and the signed record carries it (`canonical` writes floats in Python's form,
   step3:367-368).
3. **Budget.** Spec A's bound is "budget 0–500" (A:94), and every link must have budget left (A:197-198). Step 3 makes
   a root's budget 1 to 500 because 0 "could never be spent" (S8, step3:78; `grants.py:279-280`), and check 4 fails a
   budget of 0 always (`grants.py:114`). An acceptance has no builds. survey3:258-259 flagged this; step 3 left it.
4. **The grantee set's shape and reach.** Spec A's set is `{people, ships_of}` (A:88). The code holds a flat set or
   `None` (`grants.py:58`, `:112`). Validity applies the set to every link (`:112`), so an acceptance, whose grantee is
   the signer, is invalid when the signer is not in `people`. Spec A doesn't say whether the signer is always in.
5. **Self-acceptance.** "An admin who activates a charter has accepted it" (A:136-137), and an acceptance is a grant
   "from the caller to the charter's signer" (A:133-134): for the signer that is a grant to himself. Step 3 refuses a
   grant to oneself (`grants.py:255-256`). Spec A doesn't say whether the signer's acceptance is a row.
6. **Root grantees.** Spec A's example root names a ship (A:89). Step 3 moved ship grantees to step 5 (S2,
   step3:72), and tickets spend only a person grantee's grant (`tickets.py:133-142`). Spec A is silent on whether a
   charter root may name a person (Question 1).
7. **Withdrawing a charter.** A pinned revision that is no longer active "keeps binding O's ships" (A:116-118).
   Withdrawal is "the existing layer route" (A:78-79). Spec A doesn't say whether a withdrawn charter's pinned text
   still binds, while the hook tells sessions a withdrawn layer "no longer appl[ies]" (`hook.py:455-456`). With no
   charter active, the defaults apply (A:383), which can widen limits a charter had narrowed, with no confirmation.
8. **Narrowing a charter.** `POST /api/layers/{id}/revoke` writes a new revision even when nothing is removed
   (`layers.py:143-167`). On a charter, that is a new revision with the same text: followers move to it, pinned
   owners' roots are superseded (A:116-118, A:178-179), and no widening check runs. Spec A is silent.
9. **What the signature says.** The revision record has no `charter` key (A:369-370; `identity.py:77-78`). `policy` may
   be null on a charter (A:63-64), so a charter without a policy signs like an ordinary revision with an empty
   audience. Adding a key to the record would change the kind's key set, which `verify_record` checks exactly
   (step3:100-101), so the law's signed revision 1 must still verify.
10. **Pins aren't signed.** `grant_pins` rows (A:165-166) are outside the grant record (G12 keeps later columns out,
    step3:180-182). The revision an owner consented to then has no station signature, unless the acceptance row's
    `charter_layer_id` and `charter_revision` carry it. Spec A sets those columns only on roots (A:176-177).
11. **Follow on an unchanging row.** `follow` is a grant column (A:163), and "rows never change, except that revoking
    fills ..." (A:171-172). Switching between pin and follow, or pinning a newer revision, is then a new pin row or a
    new grant. Spec A is silent on which.
12. **Matching roots across revisions.** "A root that is added or widened" (A:98-99) needs a root's identity across
    revisions. A root clause has no id (A:89-90). Spec A is silent. It is also silent on whether a root that names
    another owner is a widening for a follower.
13. **When roots are materialized for followers.** Rows are made "when the signer activates the revision or an owner
    accepts it" (A:177-178). A follower moves forward without accepting (A:106-107), so spec A doesn't say when that
    owner's roots in the new revision are made. Nor does it say what renews a charter root after its `expires_hours`
    (at most `max_expiry_hours`) runs out.
14. **`max_depth` 0.** The bound "depth 0–5" (A:94) doesn't say whether it bounds `max_depth`, a root's `depth`, or
    both. Validity counts the chain's links (`grants.py:112`), so `max_depth` 0 invalidates every browser grant
    (`test_grants.py:92`). survey3:262-263 raised the counting question.
15. **Missing keys and "unrestricted".** Spec A doesn't say whether a policy may omit a section (taking the default),
    or how a charter says "unrestricted grantees" once it has listed some, which is a widening (A:98-99).
16. **The ship drafts route.** Spec A takes `charter?` and `policy?` (A:126) and addresses only "a non-charter draft"
    to the drafting ship (A:127-128). The built route refuses both keys (`instructions.py:53-54`) and always addresses
    the draft to the ship (`:71-72`). A gap, not a contradiction.
17. **D3's term.** Spec A's D3 is "Until spec B" (A:32). The law says merging under section 2 holds "until the charter
    exists" (law:28-33). Section 4.4 below.
18. **An admin who stops being one.** Spec A requires an admin to activate (A:71) but says nothing about a charter
    whose signer later loses the role (`auth.py:157-183` lets a super admin change it). Only the layer's owner can
    revise or withdraw it (`layers.py:52-53`).

### 3.3 Useful now, or waiting for a user

Measured against today's station: every ship with an owner is Andy's (rio-grande, serenity, defiant and tardis:
`docs/superpowers/specs/2026-10-11-breakout-rooms-design.md:12-13`; HANDOFF.md:19-27), and the residents are Odo and
Wormhole. The step 4 spec may narrow scope as step 3 did (step3:49-63); that is a scope call, not Andy's.

| Part | Used when step 4 ships? | Why |
| --- | --- | --- |
| Charter flag, policy, widening at activation, the policy in force | Yes | Andy turns the law into the charter; its limits govern grants station-wide. |
| The signer's acceptance, binding Andy's ships and the residents, the footer, bracketed titles | Yes | The law reaches Odo's runs. Every builder footer names the charter revision. |
| Revision diffs at activation, the Ships status view | Yes | Andy sees what he signs and what binds each ship. |
| Acceptance by other owners: `/api/charter`, pins, follow, pending revisions, the acceptance page | Not yet | No other person owns a ship. It is spec A's core of "a charter the owner accepted" (A:28), and the first new owner needs it. |
| Charter roots | Depends on Question 1 | With ship grantees, nothing spends them before step 5's directs. With person grantees, ticket basis `grant` spends them now. |
| `instruct` grants between people (step 3's S3 deferral) | Not yet | No owner but Andy would grant `instruct`. It shares the acceptance's grant shape and pins. |
| Status line for a pending charter | Not yet | Only another owner has a pending revision. |

---

## 4. How the current law fits

### 4.1 Today

The binding law is layer c879372542444e4c8f95f2c0db69f8fb, revision 1, an ordinary instructions layer owned and
activated by Andy (roadmap:14; law:3). Its audience is defiant, rio-grande, serenity and tardis, all Andy's ships, so
they are bound by step 2's owner rule (`instructions.py:78-92`). Odo and Wormhole are bound by nothing (`:80-81`).
Revision 1 is station-signed with `policy: null` (roadmap:31-32; `signatures.py:94`). Its body is about 5.3 KB, well
under the 48 KB cap. The only other instructions layer is the unsigned draft ed4a8c (roadmap:39).

### 4.2 What "the law layer becomes the charter" means mechanically

Under spec A's rules (roadmap:95 for the goal):

1. A draft with `charter: true`, `audience_users: []` and a `policy`, or none.
2. Andy activates it, as an admin. The station checks that no other charter is active, lists the widened paths
   against the no-charter defaults (a first charter, A:101-102), requires `confirm_widenings` equal to that list,
   checks the caps for every ship the charter binds, writes and signs the revision with its policy, records Andy's
   acceptance (A:136-137), and materializes any roots that name him (A:177-178).
3. From then on, Andy's four ships are bound by rule 1, the charter Andy accepted, not by rule 2. Odo and Wormhole are
   bound by the active charter (A:123-124). Another owner's ships are bound only once that owner accepts. The policy's
   limits apply station-wide (A:109-110). Builder footers gain `· charter rN`.
4. Binding is computed and rendered by the station (A:112-113; `tickets.py:108`; `instructions.py:43-49`), so old
   hooks, watchers and MCP servers carry the charter with no agent change.

### 4.3 Converting this layer, or a new charter layer

**Convert in place** (same layer id, revision 2):
- One act, one signature, which fits "Andy signs once" (roadmap:95).
- Sessions see a changed revision of the same layer: the full new block under "These instructions changed since this
  session last looked" (`hook.py:93`, `:471-480`). No "no longer apply" line.
- Revision 1 stays as the plain law's record (signed, audience four ships, `policy: null`). Revision 2 is the first
  charter revision, and the footer reads `charter r2`.
- Spec A doesn't say whether `charter` may change on an existing layer, or change back. Step 3 already handles a kind
  that changes between revisions (step3:93-95). A:101 makes the baseline "the previous active revision"; revision 1
  has no policy, so the spec must say the baseline is the defaults.

**A new charter layer, then withdraw the law:**
- Two acts. Done in either order, the window between Andy's two clicks binds his ships twice (the same text, under
  the preamble's "If two of them conflict, do not choose: ask in the room", `instructions.py:8-9`) or not at all. A
  ticket issued in that window keeps that set (`tickets.py:108`).
- Sessions see the new block and then "Instructions 'Station law for Andy's ships' (signed by Andy) no longer apply to
  this ship. What this session read of them earlier is no longer binding." (`hook.py:455-456`). If the charter keeps
  that title, the line reads as if the law itself stopped binding.
- The charter starts clean at revision 1, and no layer changes its flag.

**The four ships during the switch,** either way:
- Each ticket and each instructions fetch decides the binding at that moment (A:112-113). A run already started keeps
  the revisions its ticket recorded (`test_instructions.py:241`).
- Sessions get the change at their next prompt. Codex sessions get no change notices and keep what they read until
  they restart (`agent/README.md:23`).
- Defiant has not run current code since ship status went live (HANDOFF.md:23-24). Its hook, if any, still prints
  what the station renders.
- Odo starts carrying the charter in every run (`runs.py:127-130` appends the blocks after its persona,
  `runs.py:22-28`). Wormhole runs no model (HANDOFF.md:130), so its binding has no reader.
- The title "Station law for Andy's ships" would also bind Odo and any later owner's ships. Changing it is a draft
  edit, but with a new layer it decides how the withdrawal line reads.

### 4.4 D3 as a charter rule

- Law section 1: "When the charter exists, merging, deploying and admitting new ships become agent work under its
  rules; an act it has no rule for waits for Andy. (D2, "Law only") Until then, nothing merges or deploys except under
  section 2, and only Andy admits" (law:28-31). Section 2's heading: "Merging and deploying Superyak until the charter
  exists" (law:33).
- Spec A's D3 is "Until spec B" (A:32). The roadmap: "D3 becomes a charter rule instead of an interim one"
  (roadmap:95).
- Read literally, a charter whose text still says "until the charter exists" ends section 2 the moment it is active.
  Section 1 then sends merges to "its rules". The charter has no merge rule in its policy, so "an act it has no rule
  for waits for Andy": every merge would wait for Andy. The first charter revision's text must change those lines,
  not only its flag.
- **As charter text,** D3 is section 2 without "until the charter exists", saying it is the charter's merge rule
  until spec B gives merging acts of its own. The rest (approval in the room by the named reviewers, the Pi suites,
  restart, check, revert, announce; law:34-41) stays as it is unless Andy changes it. Admitting stays with Andy
  (law:29-31). Rio Grande drafts it; Andy signs it.
- **As policy,** D3 can't be written in policy version 1. Unknown keys are refused (A:73), and `merge`, `deploy` and
  `admit` are names reserved for spec B (A:94-95). The station doesn't see merges at all: they happen in git on the Pi.
  So in step 4, D3 stays prose that ships obey, as it is today.

### 4.5 What step 4 builds, and what spec B builds

| Step 4 | Spec B (A:8, A:493-496; law:28) |
| --- | --- |
| The charter flag, the policy, one activation by Andy with its widenings confirmed | Review as a structured act the station records |
| Acceptance by other owners (pin or follow), binding charter first, residents bound | `merge`, `deploy` and `admit` in `delegable` and in charter roots |
| The policy's limits station-wide, charter roots for `direct` | Agents merging, deploying and admitting under the charter's rules |
| `· charter rN` in footers, status, the web views | What replaces D3's room approvals with acts |
| D3 carried as charter prose | The end of D3 as prose |

---

## 5. Questions only Andy can answer

One at a time, in this order. Six questions. One blocks the spec. One more blocks it only if Andy narrows spec A's
rule. The other four block only the activation, which is his one signature.

**Q1. May a charter root name a person, or only a ship?** *(Blocks the spec.)*
Spec A's example root names a ship (A:89). Its general rule lets a grant go to "a person or a ship" (A:50) and says
nothing about roots.
- A. Ships only. Cost: charter roots give nothing usable until step 5, since a ship spends a `direct` grant only
  through directs (step3:59, step3:72). Step 4 could then leave roots out, as step 3 left ship grants out.
- B. People too. Cost: the charter itself can let a named person build an owner's ships, once that owner confirms the
  root at acceptance (A:105-106), through today's ticket basis `grant`. Andy's browser grants already do this for his
  own ships, so B matters mainly once other owners accept.

**Q2. Who may activate a charter: any admin, as spec A says, or only Andy?** *(Blocks the spec only if Andy narrows
it; otherwise spec A's rule stands.)*
D1 says "he signs the charter" (A:30). Spec A says "an admin" (A:49, A:71).
- A. Any admin, as written. Cost: another admin could activate a charter whenever none is active, and every resident
  ship would be bound by it at once (A:123-124).
- B. Only super admins, or only Andy's account. Cost: one more check, and a narrower rule than spec A.

**Q3. Should the first charter use spec A's defaults for every limit, the grantee set included?** *(Blocks only the
activation.)*
- A. Yes: depth 3, 720 hours, 24 hours, 20 builds per ship a day, `delegable` `direct`, unrestricted grantees and spec
  A's breaker numbers (A:383-385). Nothing widens, so activation has no checkbox, and no grant changes.
- B. Change some. Cost: each widening is one checkbox at activation (A:102-103). Each narrowing applies station-wide
  at the next check (A:109-110, A:200-201) and can make existing grants invalid at once. A named grantee set must
  account for acceptances, which are grants to the signer (3.2, item 4).

**Q4. Which roots, if any, should the first charter hold?** *(Blocks only the activation.)*
- A. None. Cost: nothing. Browser grants keep working.
- B. Roots from Andy over his ships to his ships, for step 5's directs. Cost: unused until step 5, and each root is a
  widening to confirm.
- C. Roots to people (only with Q1 B). Cost: each one a standing grant, renewed only by a new revision (3.2,
  item 13).

**Q5. When the law becomes the charter, should D3's merge rule carry over unchanged, as the rule until spec B?**
*(Blocks only the activation.)*
- A. Unchanged: the text drops "until the charter exists" and keeps who reviews, the Pi suites, and the restart, check
  and revert. Cost: only the edit.
- B. Changed, for example Tardis as a reviewer (roadmap:102). Cost: it brings in a decision Andy has kept open
  (roadmap:145).
- Without either, the literal text sends every merge to Andy once the charter is active (4.4).

**Q6. Should the charter's first revision also carry the law's pending revision 2, section 7's watch line
(roadmap:117-119)?** *(Blocks only the activation.)*
- A. Yes. Cost: none; one signature covers both.
- B. No: sign revision 2 first, then the conversion. Cost: one more signature.

Not asked, because spec A or the step 4 spec settles them: the residents are bound (A:123-124); converting in place
or making a new layer (4.3) is a spec choice Andy can veto; whether `instruct` grants between people stay in step 4 is
a scope call (3.3).

---

## 6. Risks and Review Focus candidates

The inputs and states most likely to bite a person.

1. **A hidden widening.** The station's list of widened paths must be complete and stable, because activation
   needs `confirm_widenings` equal to it (A:102-103). Root clauses have no id (3.2, item 12), sets gain members, and
   a missing section may mean the default. Test: one widening hidden among prose changes; r4 widens and r5 changes
   only prose, so a follower pinned at r3 stays pending (A:463-465).
2. **A no-op narrowing or a withdraw and re-activate.** A narrowing that removes nothing still writes a new revision
   (`layers.py:143-167`), which on a charter moves followers and supersedes pinned owners' roots with no widening
   check. Withdraw then activate skips a revision number (`layers.py:138-139`), so footers jump.
3. **A second charter.** 409 while one is active (A:72). After the first is withdrawn and a second activated, owners
   pinned to the first may still be bound by its text (3.2, item 7), while residents switch at once. Two different
   charters could then bind ships on one station.
4. **A charter withdrawn while acceptances exist.** Whether pinned text keeps binding is open (3.2, item 7). The
   policy falls back to the defaults (A:383), which can widen station-wide limits the charter had narrowed, such as a
   named grantee set becoming unrestricted, with no checkbox.
5. **Resident ships.** Every Odo run carries the charter from activation (`runs.py:127-130`), with no consent and no
   pin, including any widening. Residents count toward the caps at activation. `test_instructions.py:256-260` flips.
6. **Restore.** Without a usable replaced file, the reconcile revokes every grant (`backups.py:518-527`); with one,
   every grant the replaced file lacks (`:530-546`). Revoking an acceptance removes law from that owner's ships: the
   opposite of what the reconcile is for (taking back access). If the signer's own acceptance is a row, a restore can
   leave Andy's ships bound by nothing. The reconcile reports a law layer whose active revision differs but doesn't
   apply it (`:736-745`, `:974-977`), so pins may name a revision the restored copy lacks.
7. **A lost identity.** A station holding signed records refuses to start without `identity.json` (G4b,
   `signatures.py:30-35`). While it is down, hooks print nothing (A:391), so sessions start without the charter.
   After `station-new-identity`, every charter revision and acceptance signature stops verifying; binding doesn't
   depend on them, but provenance does.
8. **Acceptance rows in step 3's code.** `"own"` targets, the maximum expiry and a budget of 0 each break a step 3
   path (3.2, items 1-3): validity, the grants page (`app.js:743`), and `_utc` formatting a reason. A test should list
   an acceptance through every grants route and the page.
9. **Caps crowded by someone else.** At a charter activation, every bound ship counts. One owner whose own layers are
   near 10 or 48 KB could block a revision that binds everyone, or an acceptance could push that owner's ship over.
   `_check_instruction_caps` today refuses an empty audience (`instructions.py:95-96`) and skips ships the activator
   doesn't own (`:99-100`), so it can't simply be reused.
10. **The withdrawal line with a new layer.** If the law is replaced by a new layer with the same title, sessions read
    the new block and then a line saying instructions with that title "no longer apply" (`hook.py:455-456`).
11. **Mixed versions with the agent.** The station renders the blocks, so old agents carry the charter. Changing
    `render_one` to bracket titles changes the bytes but not the `[layer_id, revision]` pairs the hook compares, so no
    spurious change notice. An old `status` prints no pending line. A new agent must tolerate an older station with no
    pending field (`__main__.py:222-224` already prints "unavailable" on errors). Defiant runs old code.
12. **The signer stops being an admin.** Nothing ties a layer to a role (`auth.py:157-183`; 3.2, item 18).
13. **Order of blocks.** `_layers_for` re-sorts by `created` (`instructions.py:41`), so a ticket's stored order is
    lost and the charter may not render first (A:139-140).

---

## 7. Suggested merge split

Each merge stands alone under section 2 of the law, with its own plan and tests. No charter is activated until the
last merge that the first charter needs is live, so Andy signs once.

**4a. The charter layer and its policy** (station only, API first)
- `charter` and `policy` fields, stored only when set; the policy schema, bounds and unknown-key refusal; the admin
  check; one active charter (409); an empty audience.
- Widened paths against the policy in force; `confirm_widenings` at activation; what narrowing and withdrawal do on a
  charter.
- `_grant_policy` reads the active charter (the grantee set's shape); `make_grant` checks the grantee set.
- The signed revision carries `policy` (and a charter marker if the spec adds one).
- Ship drafts and the drafting tool take `charter` and `policy`.
- Touches: `layers.py`, the new module, `grants.py`, `signatures.py`, `instructions.py` (drafts), `app.py`, `db.py`,
  `pyproject.toml`, `mcp.py`, `station.py`, `API.md`, tests.
- Value alone: a charter's policy governs grants. Nothing binds through it yet.

**4b. Acceptance and binding** (station and agent)
- The acceptance as an `instruct` grant (`"own"` targets, no expiry, no budget) and `grant_pins`, with validity,
  visibility and revoking taught that shape.
- The signer's acceptance at activation; `GET /api/charter`; `POST /api/charter/accept` with pin, follow and
  per-owner baselines; pending revisions.
- Binding: charter first, then owner; residents bound by the active charter; the ticket's order kept; caps at
  activation and at acceptance.
- `· charter rN` in footers; bracketed titles in `render_one` and the hook; the pending-charter field and status line;
  `/signed` readers; the restore's treatment of acceptances.
- Touches: the new module, `grants.py`, `instructions.py`, `tickets.py`, `signatures.py`, `backups.py`, `app.py`,
  `hook.py`, `__main__.py`, `agent/tests/conftest.py`, `agent/README.md`, `API.md`, tests (the oracle's 500 cases).
- Value alone: the law can become the charter and bind Andy's ships and Odo. This is the earliest merge after which
  Andy could sign, if his first charter has no roots.

**4c. The web views** (browser)
- The activation dialog's checkboxes; the charter page with the line diff, the checkboxes and pin or follow; revision
  diffs in the editor; the Ships status view; acceptance grants on the grants page.
- Touches: `app.js`, `app.css`, `test_browser.py`.
- Value alone: the first a person sees. Andy sees exactly what he signs.

**4d. Charter roots** (only if the spec keeps them in step 4; see Q1)
- Root clauses materialized at activation and acceptance; `superseded` revocations; validity's "still active and
  accepted" check; roots in the widened paths; their renewal. With Q1 B, roots to people spend through ticket basis
  `grant`. If step 4 keeps `instruct` grants between people (step 3's S3), they fit here too, since they share 4b's
  grant shape.
- Touches: the new module, `grants.py`, `tickets.py`, `backups.py`, `app.js`, `API.md`, tests.
- Value alone: depends on Q1. With A, it is groundwork for step 5.

4a and 4b could merge as one if the reviewer prefers fewer, larger merges. 4c needs 4b's routes. 4d needs 4b's pins
and baselines.
