# Spec A step 4: the charter

Status: revision 1, for review under D8. Rio Grande owns this spec; this draft was written for it. A fresh reviewer
approves it in Andy's place (law section 3, D8), and its summary and decisions are posted in "Superyak: city of AI".
Andy can veto anything.
Base: `main` at c29e91e (grants step 3 complete), plus the survey commit 86d2919. Branch `charter-spec`. Roadmap 2.3.
Amends: [spec A](2026-10-08-instruction-layers-and-grants-design.md), its build order step 4 ("The charter") and the
parts of its sections 1, 2, 4 and Plurality that step 4 builds; the [step 3 spec](2026-10-15-grants-step3-design.md)
where step 4 changes what it built; and the text of the station law, as a proposal Andy signs. Where this spec is
silent, spec A as amended by the step 3 spec holds.
Evidence: [the survey](2026-10-15-charter-survey.md), cited as "survey 3.2 item 7" and so on. "A:n" is spec A's line n.
Rio Grande's seven rulings on the survey are recorded as decisions C1 to C10, each with its reason and cost.
Serenity, who built step 3, listed where step 3's grant code would trip on an acceptance stored as a grant. Each point
was checked against the code at c29e91e before C18 relied on it.

## Goal

Today the law is an ordinary instructions layer (c879372542444e4c8f95f2c0db69f8fb, revision 1). It binds Andy's four
ships through its audience. It binds neither Odo nor Wormhole, and it can't bind another owner's ships. Grants obey
fixed defaults (`grants.py:54-58`). Merging follows the law's section 2, which holds "until the charter exists".

Step 4 makes the law the station's charter, in one act that Andy signs:

- The law layer gets a new revision with `charter: true`, no audience and a policy. The policy's limits (chain depth,
  grant lifetime, builds per ship a day, the grantee set) govern every grant on the station from that moment.
- The charter binds Andy's ships and the resident ships, first among their instructions. Each builder footer names
  its revision: `Builder for Andy (owner) · charter r2`.
- A limit never grows without a checkbox: widenings are confirmed path by path at signing, at withdrawal and at
  acceptance.
- Another person who owns ships accepts the charter, pinned to a revision or following later ones. The station signs
  the acceptance. Their ships are then bound by the revision they accepted.
- D3, the merge rule, stays prose in the charter's text until spec B.

## Decisions

Each line is this spec's ruling. A fresh reviewer checks it; Andy can veto any of them.

| # | Ruling | Why | Cost |
| --- | --- | --- | --- |
| C1 | **Scope** (Rio Grande's ruling 6). In: the charter flag and its rules; `policy` and its schema; widened paths with `confirm_widenings` at activation and acceptance; acceptance by owners (pin or follow), kept apart from step 3's grants (C18); binding with the charter first; residents bound by it; the policy's limits station-wide, where step 3's code reads the policy; `· charter rN` in footers; status; the web views for activation and acceptance; docs. Out: other person-to-person `instruct` grants, charter roots, spec B's acts, directs. | What makes the law the charter, and what the first other owner needs to accept it. | Acceptance by other owners is the largest part and has no user until a second person owns a ship (survey 3.3). It gets its own merge, 4c, and Andy's signature doesn't wait for it (C31). |
| C2 | **No charter roots** (ruling 1, survey Q1). Step 4 materializes no roots. A policy with a `roots` key is refused with 400: the key is reserved for step 5. | A root would name a ship (A:89), and a ship spends a `direct` grant only through step 5's directs (step 3, S2). This is the narrower choice. | The charter hands out no authority in step 4; Andy's browser grants still do. No root widenings, no `superseded` roots, no "still active and accepted" check. Andy can widen this later. |
| C3 | **Only a super admin may activate a charter revision** (ruling 2, survey Q2). This amends spec A's "an admin" (A:49, A:71). | D1: "he signs the charter" (A:30). Any admin could otherwise bind every resident ship at once (survey Q2 A). | One check (`_super_admin`, `auth.py:122-125`). It names the role, not Andy's account (Known limits). |
| C4 | **The law becomes the charter in place** (ruling 3). Layer c879… gets a new revision with `charter: true`, `audience_users: []` and a policy. | One act and one signature (roadmap 2.3). The binding moves from the audience rule to the charter rule in one transaction, so no ticket or fetch sees Andy's ships bound twice or not at all (survey 4.3). | The layer can never be an ordinary layer again (C6). Revision 1 stays as the plain law's signed record. A rollback after the conversion uses a new layer (Deploy). |
| C5 | **The baseline at activation is the policy in force:** the active charter's policy, or the no-charter defaults when no charter is active. So when the previous active revision has no policy, as the law's revision 1 has none, the baseline is the defaults (ruling 3). | Spec A's "the previous active revision, or for a first charter the no-charter defaults" (A:101-102) assumes the previous revision has a policy. A widening grows from what is in force. | With spec A's defaults as the first policy (Q3 A), the conversion has nothing to confirm. |
| C6 | **A charter stays a charter** (ruling 3). Once a layer has a charter revision, saving or activating its draft without `charter: true` is refused with 409. To end a charter, its owner withdraws it (C15). | Clearing the flag would end the charter for the residents and every accepting owner through a draft edit, and change the rule under which the same text binds. Withdrawal says plainly that the charter ends, and checks the limits that return to the defaults. The safe answer. | A charter can't step back to an ordinary layer. Rollback uses a new layer (Deploy). |
| C7 | **The hook's change notice** (ruling 3). The layer id stays the same, so a session sees the existing changed-revision notice: the new block in full, and no "no longer apply" line. The block's header marks the charter (C25). | `hook.py` keys notices by layer id and revision (`:450-491`); only a layer that disappears prints "no longer apply" (`:455-456`). | Codex sessions get no notice and keep what they read until they restart. |
| C8 | **D3 stays prose until spec B** (ruling 4). The first charter revision's text must change the law's "until the charter exists" lines (sections 1 and 2), so that section 2 is the charter's merge rule until spec B gives merging its own acts. "Amendments to the law" proposes the wording. Rio Grande drafts it later as a layer draft. No code reads it. | A charter whose text still says "until the charter exists" ends section 2 when signed, and section 1 then sends every merge to Andy (survey 4.4). Policy version 1 can't express D3: `merge`, `deploy` and `admit` are reserved for spec B (A:94-95). | A fresh reviewer must check the rewording against Andy's words before he signs, as for the law's revision 1 (roadmap 0.2). |
| C9 | **Survey Q3 to Q6 are Andy's choices at activation** (ruling 5), asked one at a time when he is about to sign. They don't block this spec. | They are about the first charter's content, not the code. | Four short questions at signing time. |
| C10 | **The display-name spoof in grant footers** (room message bd2802fa) goes to step 5's spec (ruling 7). | Step 5 adds more names to footers (chains of ships) and fixes them together. | Until then a person's chosen display name can read like another's (Out of scope). |
| C11 | **Policy schema:** spec A's version 1 without `roots` (C2) and without `breaker`, also reserved for step 5. A charter always has a policy: a missing policy, section or key takes the default. The revision stores the full policy, every default filled in; the draft keeps what was written. | Spec A gives no bounds for the breaker's numbers, and step 5 builds the breaker; a checkbox for a number nothing reads confirms nothing. A full stored policy makes the signed record state every limit in force, and marks a charter revision by its policy alone (C12). | Step 5 adds `breaker`; a charter without it reads as the defaults. `agent_grant_default_hours` and `grantees.ships_of` have no reader until step 5 either; they stay because spec A bounds them. |
| C12 | **The signed record keeps its kind and keys.** `instructions-revision`'s `policy` comes from the revision's snapshot: the full policy on a charter revision, `null` on every other. | Step 3 reserved `policy` for this (G2). `verify_record` checks the key set exactly (`identity.py:76-87`). With C11 a non-null policy marks a charter revision. Every signature made so far verifies unchanged. | A reader of a record must know that rule; peer/API.md states it. |
| C13 | **Widened paths.** A widening is a number that grows, a set that gains a member, or a restricted grantee set that becomes unrestricted. The station lists them sorted by path ("Data"). `confirm_widenings` must hold exactly those paths, each once, in any order. | Spec A (A:98-103). Sorting keeps the list stable; set equality lets the browser send ticked boxes in any order. | A client fetches the list first (the preview, or `GET /api/charter`); a stale list gets 409. |
| C14 | **Narrowing is refused on a charter** (`POST /api/layers/{id}/revoke`, 409). | A charter has no audience to narrow. The route writes a new revision even when nothing is removed (`layers.py:143-167`), which would move followers with no widening check (survey 3.2 item 8). | None: a new revision or a withdrawal does what a narrowing could. |
| C15 | **Withdrawal.** The charter's owner withdraws it, whatever his role now. It needs `confirm_widenings` for the paths that widen from its policy to the defaults. A withdrawn charter binds no ship: not the signer's, not a resident, not a pinned owner's. Acceptances stay, and bind again if the same layer is activated again. | Withdrawal is a policy change back to the defaults (A:383), which can widen what the charter narrowed (survey risk 4). Pinned text that outlived its charter would let two charters bind ships on one station (survey risk 3). The signer must always be able to end his charter. | An owner has no charter law while none is active and accepted. A demoted owner's charter stays until he withdraws it. |
| C16 | **The policy in force, station-wide** (A:109-110). `_grant_policy` returns the active charter's policy, flattened as today, or the defaults. Readers: `max_depth` (validity; it counts a chain's links, root included, as step 3 built, so 0 makes every grant invalid), `max_expiry_hours` (making a grant, validity), `builds_per_ship_per_day` (tickets, the grant view), `grantees.people` (making a grant, validity, the person list), `delegable` (validity, for links a ship issued). | One function, as step 3 planned (G7). A narrower limit takes effect at the next check (A:198-202). | `delegable` governs only links a ship issued, and step 4 has none: it is checked, tested on a hand-made row, and has no effect until step 5. |
| C17 | **The signer accepts by signing,** with no acceptance row. The active charter revision binds every ship its owner owns. | "An admin who activates a charter has accepted it" (A:136-137). A row would be the signer accepting from himself (step 3 refuses a grant to oneself, `grants.py:255-256`), and a restore could revoke it and leave Andy's ships unbound (survey risk 6). | The signer can't pin an older revision of his own charter. He controls the active one. |
| C18 | **An acceptance is a row in its own table,** `charter_acceptances`, not in `grants`: one row per act, naming the person, the charter's signer, the layer, the revision and `follow`. It is signed as a record of its own kind, `charter-acceptance`; ending it is signed as `charter-acceptance-revocation`. A new acceptance ends the person's previous one with reason `superseded`, and a partial unique index keeps one in force per person. No `grant_pins` table. This departs from spec A, which records an acceptance "as an `instruct` grant" with `targets: "own"` and no expiry (A:132-136, A:165-166, A:170). | Step 3's grant code assumes a list of ship ids, an expiry within `max_expiry_hours` and a budget of at least 1: validity reads `"own"` as the ids `o`, `w`, `n` (`grants.py:117`) and fails the lifetime check (`:110`); the grant view and the grants page map targets as ships (`:191`, `app.js:743`); NULLs would need a table rebuild, since `expires` and `budget` are NOT NULL (`:11`), and `canonical` refuses infinity (`identity.py:20-23`); the reconcile revokes every grant a replaced file lacks (`backups.py:518-546`). A helper that hides acceptances from every grant reader would keep the rows in `grants` while no grant route used them, and any reader that missed it would show or fail on one. A table of its own leaves every step 3 invariant and reader as it is, needs no rebuild, and makes 4c a self-contained merge. The record could reuse the `grant` kind, since spec A calls an acceptance a grant; a kind of its own is safer, because it keeps an acceptance from passing as a grant something could spend (step 3, S7). The pin is in the signed row, never in an unsigned `grant_pins` row (survey 3.2 item 10). | A departure from spec A, stated in Amendments. The grants page doesn't list acceptances; the Charter page does. `RECORD_KEYS` gains two kinds, and the lost-identity check and the startup revocation backfill gain the table. Spec A's rule 3 (`instruct` grants between people) gets no shared machinery from acceptance (C1 leaves it out). |
| C19 | **An acceptance binds while it is in force** (not revoked) and its layer still exists. It is never a grant: no grant route, validity walk, ticket, budget or grant reconcile reads it, and it carries no expiry, budget or targets. | It has no expiry and no builds (A:134-135), and covers whatever ships its person owns, now or later. | An owner who wants to stop must leave (`POST /api/charter/leave`); nothing ends an acceptance by itself. |
| C20 | **Only the active revision can be accepted.** The baseline at acceptance is the revision that binds the caller's ships now (pinned, or followed to), or the no-charter defaults when none does, as at a first acceptance. | Spec A (A:104-106). The page then has one thing to accept. | No owner can accept an older revision than the active one. |
| C21 | **Follow moves one revision at a time,** each compared with the revision binding the owner then. It stops before the first revision that widens; that revision and every later one show as pending. | Spec A: "the newest without a widening against O's baseline" (A:115-116), and a widening "cannot ride in on a prose-only r5" (A:107-108). Stepping is the narrower reading: after r4 narrows `max_depth` to 2, an r5 that sets it back to 3 is a widening for a follower bound by r4. | A follower stops more often and accepts by hand. |
| C22 | **Binding** (spec A rule 1, amended). For a ship: first the charter revision that binds its owner (C17, C18, C21), or for a resident the active one; then its owner's own active instructions layers that list it, by creation. A withdrawn charter binds nothing. Spec A's rule 3 stays out (C1). | Spec A's order (A:139-140) and residents (A:123-124). | Odo's runs carry the charter from the moment Andy signs, with no consent of their own. |
| C23 | **Caps** (A:75-77). At a charter activation: every ship the new revision would bind (the residents, the signer's ships and, from 4c, followers' ships that would move to it). At an acceptance: every ship the caller owns. An owner's own activation counts the charter. Each refusal is 409 and names the ship. | `_check_instruction_caps` refuses an empty audience and skips ships the activator doesn't own (`instructions.py:94-103`), so it can't serve as it is (survey risk 9). | One owner's own layers can block a charter revision; the 409 says which ship. |
| C24 | **The footer gains `· charter rN`** when the ticket's recorded instructions include a charter revision; N is that recorded revision. | Spec A's footer (A:310-311). The ticket's record, not the charter now, so a footer never changes after its run. | Tickets issued before the conversion keep footers without it. |
| C25 | **Block headers bracket the title,** showing `[` and `]` inside a title as `(` and `)`. A charter's header says `charter revision N`. | HANDOFF: bracket titles "once other signers can bind a ship", and the charter is the first. With no inner brackets, the title's bounds can't be faked. | The block's bytes change at 4a's deploy but its `[layer_id, revision]` pairs don't, so no session sees a spurious change notice. |
| C26 | **Every signed-in person can read the active charter** (`GET /api/charter`) **and the signature of every charter revision.** Other revisions stay owner-only (step 3, G6). An acceptance's signed record goes to its person and the charter's signer. | A person must read what they accept, and the charter binds ships of people other than its signer. | The charter's policy, with the names of any people it lists, is visible to every person on the station. |
| C27 | **Restore treats acceptances by person, not by row.** A person's acceptance in the restored copy is ended when the replaced file holds none in force for that person, and kept otherwise. Without a usable replaced file it is kept. The report lists each one. Grants are reconciled exactly as G13 says. | Ending an acceptance takes law away from that owner's ships, the opposite of the reconcile's purpose (survey risk 6). Row by row, a re-acceptance after the copy would end the copy's row as superseded and leave the owner with none. | Without a usable replaced file, an owner who left after the copy is bound again until they leave again. |
| C28 | **Ships draft charters** (A:126): the drafts route and `station_draft_instructions` take `charter` and `policy`. A charter draft has no audience. | Rio Grande drafts the charter's text (C8). | A non-super-admin owner can hold a charter draft he can't sign; it binds nothing. |
| C29 | **Status.** `GET /api/ships/me/instructions` marks the charter layer and gains a `charter` field; `superyak-agent status` prints one charter line. The web's Ships section shows the binding layers of the caller's own ships and of resident ships. | Spec A's status (A:360-362). Its grants and breaker parts are step 5's. | An admin isn't shown other owners' ships' layers: they would reveal those owners' layer titles. |
| C30 | **Web.** Line diffs where a person signs or accepts: the draft against the active revision at activation, the pending revision against the binding one at acceptance, computed in the browser. The editor takes the policy as JSON, for super admins only. | A:103, A:154-155. | The editor's per-revision history diff waits (Out of scope). The activation diff shows each revision against the one before it when it is signed. |
| C31 | **Three merges:** 4a the station's charter for its signer and the residents; 4b the signer's web views; 4c acceptance by other owners. No charter is activated before 4b is live. | Andy's conversion needs 4a and 4b only. 4c is the largest part and has no user yet. | Until 4c, the charter binds only the signer's ships and the residents. |

## Amendments

Each amendment is made in place with the note "(charter step 4 spec, Cn)".

**Spec A**

1. A:48-49, Concepts: "signed by an admin" becomes "signed by a super admin (C3)".
2. A:71-72: "Only an admin may activate a charter, and while one charter layer is active, activating a second is refused
   with 409." becomes "Only a super admin may activate a charter revision (C3), and while one charter layer is active,
   activating a second is refused with 409. A layer that has had a charter revision stays a charter (C6)."
3. A:73: "unknown keys are rejected with 400" gains "; `roots` and `breaker` are reserved for step 5 and rejected with
   400 too (C2, C11). A charter always has a policy; missing keys take the defaults, and its revisions store it in full."
4. A:78-79: "Activation, revisions, narrowing and withdrawal are the existing layer routes." gains "Narrowing is refused
   on a charter (C14), and withdrawing one needs `confirm_widenings` (C15)."
5. A:101-102: "the previous active revision, or for a first charter the no-charter defaults" becomes "the policy in
   force: the active charter's policy, or the no-charter defaults when no charter is active, including when the layer's
   previous revision was not a charter (C5)".
6. A:104-108: "and each root that names the owner is also listed for confirmation" is removed (C2). "A 'follow'
   acceptance moves the owner forward only to a revision with no widening against their own baseline." becomes "A
   'follow' acceptance moves the owner forward one revision at a time, each compared with the revision binding the
   owner then, and stops before the first that widens (C21)." Only the active revision can be accepted (C20).
7. A:115-118, binding rule 1, gains: "A withdrawn charter binds no ship (C15). The charter's signer's ships are bound by
   its active revision (C17). Roots: none in step 4 (C2)."
8. A:123-124: "when an admin activates it" becomes "when a super admin activates it".
9. A:132-137, accepting: "records the acceptance as an `instruct` grant from the caller to the charter's signer. Its
   targets are `"own"`, meaning every ship the caller owns now or docks later. It has no expiry (`expires` is the
   maximum value) and stays until revoked. Its pin is that revision, and `follow` is stored." becomes "records the
   acceptance as a row of `charter_acceptances`, signed as a `charter-acceptance` record naming the caller, the
   charter's signer, the revision and `follow`. It covers every ship the caller owns now or docks later, and stays until
   the caller leaves or accepts again; a new acceptance ends the previous one with reason `superseded` (C18, C19)."
   "Accepting also materializes the policy's root clauses whose `owner` is the caller (section 2)." is removed (C2). "An
   admin who activates a charter has accepted it." becomes "A super admin who activates a charter has accepted it; no
   row records that (C17)."
10. A:165-166: the `grant_pins` table is not created; `charter_acceptances` takes its place (C18).
11. A:170: "`targets` may be `"own"` only on a charter acceptance" is removed: no grant has `"own"` targets (C18).
12. A:176-179, charter root clauses, and A:197, "for a charter root the charter revision must still be active and
    accepted": moved to step 5 (C2).
13. A:369-373, Plurality, gains: "It signs each charter acceptance as `{kind: "charter-acceptance", station, id,
    person_id, signer_id, layer_id, revision, follow, created}` and each end of one as `{kind:
    "charter-acceptance-revocation", station, acceptance, revoked, revoked_by, reason}` (C18)."
14. A:143, the block header, becomes `=== Instructions: [<title>] · revision <n> · signed by …` with `charter revision
    <n>` for a charter (C25).
15. A:369-370, the revision record: "`policy`" is the revision's stored policy, non-null exactly on a charter revision
    (C12).

**The step 3 spec**

1. G2: "`policy` is `null` until step 4" becomes "`policy` is the revision's stored policy: the charter's full policy on
   a charter revision, `null` on every other (charter step 4 spec, C12)".
2. G6: "Step 4 adds the owners whose ships a revision binds under an `instruct` grant." becomes "Step 4 serves a
   charter revision's signature to every signed-in person; other revisions stay owner-only (C26)."
3. G7: "`_grant_policy(db)` returns spec A's no-charter defaults" becomes "returns the active charter's policy, or spec
   A's no-charter defaults when no charter is active (C16)".
4. G8 gains step 3a: "with a grantee set in force, the grantee is listed in its `people` (400)" (C16).
5. G9, check 3: "and its grantee is in the grantee set" gains ", and a link a ship issued has every action in
   `delegable` (C16)".
6. G3: "whose `kind` is one of `instructions-revision`, `grant`, `grant-revocation`" gains "`charter-acceptance`,
   `charter-acceptance-revocation`" (C18).
7. G4b: "a row in `revision_signatures`, or, from merge 3b, a row in `grants` whose `signature` is set" gains "or, from
   step 4, a row in `charter_acceptances` whose `signature` is set"; G12's startup signing of unsigned revocations gains
   unsigned acceptance revocations (C18).
8. G13 gains: "Charter acceptances are reconciled by person (charter step 4 spec, C27)." Every grant rule stays as it
   is.

The `grants` table, its readers and the grants page are unchanged by step 4 except as items 3 to 5 say.

**The law** (a proposal for Andy's signature; Rio Grande drafts the text, C8)

1. Section 1, fourth bullet (law:28-31): "When the charter exists, merging, deploying and admitting new ships become
   agent work under its rules; an act it has no rule for waits for Andy. (D2, "Law only") Until then, nothing merges or
   deploys except under section 2, and only Andy admits: …" becomes "This layer is the station's charter. Merging,
   deploying and admitting new ships become agent work under its rules once spec B gives them acts of their own; an act
   it has no rule for waits for Andy. (D2, "Law only") Until spec B, section 2 is the charter's rule for merging and
   deploying, and nothing merges or deploys except under it. Only Andy admits: …" (the rest unchanged).
2. Section 2's heading (law:33): "Merging and deploying Superyak until the charter exists" becomes "Merging and
   deploying Superyak: the charter's rule until spec B gives them acts (D3)". Its bullets stay as they are (Q5 A).
3. The preamble (law:15-16): "binding because Andy activated this layer" becomes "binding because Andy signed this
   charter".
4. Optional, Andy's call: the title "Station law for Andy's ships" becomes "Station charter", since it now binds the
   resident ships and accepting owners' ships too; and section 1 gains "Resident ships (Odo, Wormhole) have no owner;
   this charter is the only law that binds them."

## Data

**Layer drafts.** Two keys join `FIELDS`. Both are stored only when set, so a note or an ordinary instructions draft
stores neither and a rolled-back station still reads it (`layers.py:48-49`).

- `charter`: a JSON boolean; stored only when `true`.
- `policy`: an object, allowed only with `charter: true`; `null` and absent both mean the defaults.
- A charter revision's snapshot holds `charter: true`, `audience_users: []` and the full policy.

**Policy, version 1.** Unknown keys at any level, and a value of the wrong type (a boolean is never a number; `3.0` is
not a whole number), are refused with 400 naming the path, such as `policy.delegation.max_depth`.

| Path | Default | Allowed | Read in step 4 by |
| --- | --- | --- | --- |
| `version` | — | required in a given policy; must be 1 | — |
| `delegation.max_depth` | 3 | whole, 0–5 | validity: a chain has at most this many links, root included |
| `delegation.max_expiry_hours` | 720 | whole, 1–2,160 | making a grant (`hours`), validity (lifetime) |
| `delegation.agent_grant_default_hours` | 24 | whole, 1–2,160, at most `max_expiry_hours` | nothing until step 5 |
| `delegation.delegable` | `["direct"]` | each of `["direct"]` at most once; `merge`, `deploy`, `admit` refused as reserved for spec B | validity, for links a ship issued (none until step 5) |
| `budgets.builds_per_ship_per_day` | 20 | whole, 0–500 | tickets (per-ship cap), the grant view |
| `grantees` | `null` (unrestricted) | `null`, or `{people, ships_of}` | making a grant, validity, `GET /api/grants/people` |
| `grantees.people` | `[]` when `grantees` is an object | ids of local person accounts, each once | as above, for person grantees |
| `grantees.ships_of` | `[]` when `grantees` is an object | ids of local person accounts, each once | nothing until step 5 (ship grantees) |
| `roots`, `breaker` | — | refused: reserved for step 5 | — |

`people` and `ships_of` hold at most 100 ids together. The full policy with every default:

```json
{"version": 1,
 "delegation": {"max_depth": 3, "max_expiry_hours": 720, "agent_grant_default_hours": 24, "delegable": ["direct"]},
 "budgets": {"builds_per_ship_per_day": 20},
 "grantees": null}
```

**Widened paths,** from a baseline policy B to a policy P, sorted by path (code point order):

- `delegation.max_depth`, `delegation.max_expiry_hours`, `delegation.agent_grant_default_hours`,
  `budgets.builds_per_ship_per_day`: P's number is greater than B's;
- `delegation.delegable:<action>`: the action is in P and not in B;
- `grantees`: B's set is restricted and P's is `null`;
- `grantees.people:<id>`, `grantees.ships_of:<id>`: both are restricted, and the id is in P's list and not in B's.

Routes return each as `{path, before, after}`: the two numbers; for a gained member `null` and the member; for
`grantees` the old set and `null`. A `names` map gives each listed person id's name. Prose changes are never widenings:
they are what the diff shows.

**Acceptances** (4c, C18) get a table of their own. It is additive: `CREATE TABLE IF NOT EXISTS` at startup, as
every table is, with no migration of `grants`.

```sql
CREATE TABLE IF NOT EXISTS charter_acceptances(id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES users(id),
  signer_id TEXT NOT NULL REFERENCES users(id), layer_id TEXT NOT NULL REFERENCES layers(id), revision INTEGER NOT NULL,
  follow INTEGER NOT NULL, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id),
  revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS charter_acceptances_in_force ON charter_acceptances(person_id) WHERE revoked IS NULL;
```

`signer_id` is the layer's owner when the person accepted. Rows never change, except that ending one fills `revoked`,
`revoked_by`, `revoke_reason` and `revocation_signature`. Reasons are `superseded` (a newer acceptance), `left` (the
person left) and `restored` (the reconcile, C27). The two signed records:

- `{kind: "charter-acceptance", station, id, person_id, signer_id, layer_id, revision, follow, created}`, with `follow`
  as `true` or `false`;
- `{kind: "charter-acceptance-revocation", station, acceptance, revoked, revoked_by, reason}`.

`identity.RECORD_KEYS` gains both kinds; `verify_record` is otherwise unchanged. An acceptance's short id is `#` and
its first 4 characters, as a grant's is.

**The revision record** keeps G2's keys and kind; `policy` is the snapshot's (C12).

## Routes

Every route below takes a person session unless it says "ship key". On a person route a ship key gets 403, a missing
session 401 and a missing CSRF token on a write 403 (`current_user`, `app.py:88-97`); on a ship-key route a person gets
403 (`ship_member`). A body that is not a JSON object gets 400 (`app.py:72-82`). All of that comes first. After it, the
station refuses in the order listed; the first failure answers.

**`POST /api/layers`, `PUT /api/layers/{id}`** (drafts). As today (404 for a layer the caller doesn't own, 409 for a
stale `version`), then:
1. `charter` not a boolean: 400 "charter is true or false";
2. `charter: true` on a note: 400 "Only instructions can be a charter";
3. `charter: true` with ships in `audience_users`: 400 "A charter names no ships: it binds every ship whose owner
   accepts it";
4. `policy` without `charter: true`: 400 "A policy belongs only on a charter";
5. the policy fails the schema: 400 naming the path; `roots` and `breaker` say "reserved for step 5";
6. every other existing draft check, unchanged;
7. (save only) the layer has a charter revision and the draft isn't a charter: 409 "This layer is the station's
   charter and stays one; withdraw it to end it" (C6).

**`GET /api/layers/{id}/preview`.** As today. For a charter draft it adds `charter: {policy, widenings, names, binds}`:
the full policy, the widened paths against the policy in force (C5), and the ships it would bind (`[{id, name,
owner_name}]`, residents with `owner_name: null`).

**`POST /api/layers/{id}/activate {version, space_versions?, confirm_widenings?}`.**
1. 404: no such layer, or not the caller's;
2. 409 "Draft changed; preview this version again";
3. 400: the stored draft fails any draft check above;
4. 409: the layer has a charter revision and the draft isn't a charter (C6);
5. for a charter, in order:
   - 403 "Only a super admin can sign the station's charter" (C3);
   - 409 "Another charter is active; its owner must withdraw it first";
   - 400 "confirm_widenings is a list of paths" (not a list of at most 100 strings of at most 200 characters);
   - 409 "Confirm exactly these widenings: …", naming them (C13);
   - 409 "<ship> would have more than 10 instruction layers or 48,000 bytes of them" (C23);
6. for any other layer: 400 "Only a charter has widenings to confirm" when `confirm_widenings` is non-empty, then
   today's checks (400 for no ships, 409 caps, 409 space membership).

Then the revision is written and signed in one transaction, as today.

**`POST /api/layers/{id}/withdraw {confirm_widenings?}`.** An empty body counts as `{}`, so old clients still work.
1. 404: no such layer, or not the caller's;
2. for an active charter: 400 for a malformed `confirm_widenings`, then 409 "Confirm exactly these widenings: …",
   against the defaults (C15).

A layer that isn't active returns as today, unchanged.

**`POST /api/layers/{id}/revoke`.** Today's refusals (400 unknown field, 404, 409 stale revision), then 409 "A charter
has no audience to narrow; sign a new revision or withdraw it" (C14). Nothing is written.

**`GET /api/layers/{id}/revisions/{n}/signed`.** A charter revision is served to any signed-in person (C26). Any other
revision: as G6, the owner only, 404 for anyone else and for no such revision.

**`GET /api/charter`** (4c). Never 404. Returns:

```
{"charter": null | {"layer_id", "revision", "title", "body", "policy", "names", "signer": {"id", "name"}, "created"},
 "signer": true | false,
 "acceptance": null | {"id", "short", "revision", "follow", "accepted"},
 "binding": null | {"revision", "title", "body", "policy"},
 "pending": null | {"revision", "widenings", "baseline": "defaults" | <revision>},
 "acceptances": [{"person": {"id", "name"}, "revision", "follow", "accepted"}]}
```

`binding` is the revision that binds the caller's ships now. `pending` is the active revision when it doesn't bind them,
with its widened paths against the baseline (C20). A person sees only their own acceptance. `acceptances` lists the
acceptances in force of the active charter for its signer, and is empty for everyone else.

**`POST /api/charter/accept {layer_id, revision, follow, confirm_widenings}`** (4c).
1. a key other than these four: 400;
2. `layer_id` not a string, `revision` not a whole number, `follow` not a boolean, `confirm_widenings` not a list of
   strings (absent is `[]`): 400;
3. no charter is active, or `layer_id` and `revision` aren't the active charter's: 409 "The charter changed; read it
   again";
4. the caller signed it: 409 "You signed this charter; it binds your ships already" (C17);
5. 409 "Confirm exactly these widenings: …", against the caller's baseline (C20);
6. 409 naming a ship of the caller's that would exceed the caps (C23).

The caller may own no ships yet: the acceptance covers ships docked later. If the caller's acceptance in force already
names this revision with the same `follow`, the answer is 200 with no new row. Otherwise, in one transaction, the
previous acceptance is ended (`superseded`, by the caller, signed), the new row is inserted and signed, and the answer
is 200 with `GET /api/charter`'s shape.

**`POST /api/charter/leave {reason?}`** (4c). 400 for a reason that isn't one line of at most 200 characters; 409 "You
have not accepted a charter" when the caller has no acceptance in force. Otherwise it ends it (`left`, or the reason
given, signed) and answers with `GET /api/charter`'s shape. The caller's ships are no longer bound by it at their next
fetch or ticket.

**`GET /api/charter/acceptances/{id}/signed`** (4c). `{station, record, signature}`, plus `revocation: {record,
signature}` once it ended, for the acceptance's person and its signer; 404 for anyone else and for no such row.

**`POST /api/grants`.** G8's order, with step 3a after step 3: a grantee not in the grantee set's `people` gets 400
"The station's charter doesn't allow grants to this person" (C16). `GET /api/grants/people` lists only those people while
a set is in force.

**`POST /api/ships/me/drafts {title, body, charter?, policy?}`** (ship key). A key other than these four: 400; a ship
with no owner: 403; the rate limits: 429; then the draft checks above. A charter draft has an empty audience; any other
is addressed to the drafting ship, as today.

**`GET /api/ships/me/instructions`** (ship key). Each `layers` item gains `charter: true | false`. The answer gains
`charter: null | {layer_id, revision, binding, accepted}`: the active charter's revision, the revision binding this ship
(or `null`), and whether its owner signed or accepted it (always true for a resident).

**`GET /api/ships`.** Each ship the caller owns, and each resident ship, gains `instructions: [{layer_id, revision,
title, charter}]`, its binding layers in order (C29).

## Binding

For a ship S, computed when a ticket is issued or the instructions are fetched, as today:

1. The active charter is the one layer whose active revision is a charter revision, if any.
2. The charter pair for S:
   - S is a resident (no owner): the active charter's active revision, or none;
   - S's owner O owns the active charter: its active revision (C17);
   - otherwise, O's one acceptance in force A (4c), if any. If A's layer has no active revision, none (C15). If A pins,
     A's revision. If A follows, start at A's revision and step through that layer's later revisions in order, up to
     the active one, moving to each that has no widening against the one O is on; stop at the first that widens (C21).
3. Then, unless S is a resident, O's own active non-charter instructions layers whose audience lists S, by
   `(created, layer_id)`, as today.

A ticket records the pairs in this order, and `_layers_for` renders them in the order recorded, never re-sorted
(`instructions.py:41` today). The caps check (C23) uses the same function with the new revision put in place of the
charter pair for each ship it would bind.

At most one charter binds a ship: one charter layer is active at a time, a withdrawn one binds nothing, and an owner
holds at most one acceptance in force (the partial unique index).

## Requirements

**4a: the station's charter**

- **R1.** A draft's `charter` and `policy` follow "Routes" and "Data", each refusal with its status and reason. A note
  or ordinary draft stores neither key.
- **R2.** A charter revision's snapshot holds the full policy with every default filled in; the draft keeps the policy
  as written. A missing policy and `{"version": 1}` give the same revision policy.
- **R3.** Only a super admin activates a charter revision. An admin who is not one gets 403, and nothing is written.
- **R4.** While one charter layer is active, activating a charter revision of another layer gets 409.
- **R5.** A layer with a charter revision can't be saved or activated as a non-charter (409).
- **R6.** A charter's activation needs `confirm_widenings` equal, as a set, to the widened paths against the policy in
  force: the active charter's, or the defaults (C5). Anything else gets 409 naming the paths.
- **R7.** The widened paths are exactly those in "Data", sorted. A narrowing alone lists nothing, and so does a prose
  change.
- **R8.** Narrowing a charter gets 409 and writes nothing.
- **R9.** Withdrawing an active charter needs `confirm_widenings` equal to the paths that widen from its policy to the
  defaults. An empty body is `{}`.
- **R10.** `_grant_policy` returns the active charter revision's policy, flattened as today, or the defaults. Every
  reader goes through it, so a change takes effect at the next check, and a withdrawal restores the defaults.
- **R11.** With a grantee set in force, a `direct` grant to a person not in `people` is refused at making (400) and is
  invalid at the next check, with step 3's reason "… is no longer allowed by the station's policy".
- **R12.** A link a ship issued is invalid when one of its actions is not in `delegable`. A browser root is never
  checked against `delegable`.
- **R13.** The revision record's `policy` is the snapshot's. Kind, keys and every existing signature are unchanged.
- **R14.** Binding follows "Binding" for residents and for the signer's ships; another owner's ship gets no charter pair
  before 4c. A withdrawn charter binds no ship.
- **R15.** A ticket's blocks render in the order its pairs were recorded.
- **R16.** The caps hold at a charter activation for every ship it would bind, and an owner's own activation counts the
  charter. Each 409 names the ship.
- **R17.** A block header reads `=== Instructions: [<title>] · revision <n> · signed by …`, or `· charter revision <n>
  ·` for a charter, with brackets inside the title shown as parentheses.
- **R18.** A build ticket whose recorded pairs include a charter revision has a footer ending ` · charter r<n>`, n from
  the record. Read tickets keep an empty footer.
- **R19.** Any signed-in person reads a charter revision's signature; other revisions stay owner-only.
- **R20.** `GET /api/ships/me/instructions` carries `layers[].charter` and `charter` as in "Routes".
  `superyak-agent status` prints one line: "Charter: none active", "Charter: revision N binds this ship", "Charter:
  revision N is pending for this ship's owner; revision M binds this ship", or "Charter: revision N is active; this
  ship's owner has not accepted it". With no `charter` field (an older station) it prints no charter line.
- **R21.** Ship drafts and `station_draft_instructions` take `charter` and `policy`. A charter draft has no audience. An
  older station's 400 reaches the tool as an error result.
- **R22.** The hook's short header (`_header`) brackets the title and says `charter revision N` for the charter. The
  conversion reaches a session as the changed-revision notice with the new block, and no "no longer apply" line.
- **R23.** peer/API.md (instruction layers, binding rule, block format, signed records, policy, run tickets' footer, a
  Charter section) and agent/README.md (what binds a ship, status) say what step 4 does.

**4b: the signer's web views**

- **R24.** The editor shows "This is the station's charter" and a policy field (JSON; empty means the defaults) only to
  a super admin. Ticked, it hides the ship list and saves `audience_users: []`.
- **R25.** For a charter, "Sign" shows the line diff of title and body against the active revision (or "new"), the full
  policy, the ships it will bind, and one checkbox per widened path in words (before → after). The button stays
  disabled until every box is ticked.
- **R26.** Withdrawing a charter asks first, says which ships stop being bound, and shows one checkbox per widened path.
- **R27.** The Ships section shows the binding layers (title, revision, charter mark) of the caller's own ships and of
  resident ships.
- **R28.** Every title, name and body on these views is escaped.

**4c: acceptance by other owners**

- **R29.** An acceptance is a `charter_acceptances` row as "Data" gives it, signed as `charter-acceptance`; its end is
  signed as `charter-acceptance-revocation`; both verify. No grant route, validity walk, ticket, budget count or grant
  reconcile reads the table, and the `grants` table is unchanged. A station holding a signed acceptance refuses to
  start without its identity (G4b), and signs an unsigned acceptance revocation at startup.
- **R30.** `POST /api/charter/accept` refuses in "Routes"' order, is idempotent for the same revision and `follow`, and
  supersedes the previous acceptance in the same transaction. `POST /api/charter/leave` ends it. The signed route
  answers only the person and the signer.
- **R31.** A pinned owner stays at their revision through later ones. A follower moves as C21 says.
- **R32.** `GET /api/charter` gives the shape in "Routes", with the baseline of C20. It never shows another person's
  acceptance, except to the active charter's signer, in `acceptances`.
- **R33.** The caps hold at acceptance for each of the caller's ships, and at activation for followers' ships that
  would move.
- **R34.** The restore reconcile treats acceptances by person (C27): `charter_acceptances.id`, `.person_id`,
  `.revoked`, `.revoked_by` and `.revoke_reason` join `COMPARED`, and the report lists each acceptance it ended or kept
  without a replaced file. Grants are reconciled exactly as G13 says.
- **R35.** The web has a Charter page (`#charter`, linked in the sidebar): the text and policy, the caller's acceptance,
  a pending revision with its diff against the binding one, one checkbox per widened path, and a choice between "Keep
  this revision until I accept another" (pin) and "Follow later revisions that don't widen the limits" (follow). It
  says an acceptance covers "all your ships, now and later". "Stop accepting" asks first, then leaves. The signer sees
  "You signed this charter; it binds your ships", and who has accepted it. The grants page is unchanged.

## Testing

Each test is named, written first, and seen failing first. Each names the wrong implementation it catches.

**Merge 4a**

1. Draft checks, as one table: `charter` as `1` or `"yes"`; `charter` on a note; a charter with a ship; a policy
   without `charter`; a nested unknown key; `roots`; `breaker`; `version` missing or 2; each bound one step outside
   (`max_depth` -1 and 6, `max_expiry_hours` 0 and 2,161, `agent_grant_default_hours` above `max_expiry_hours`,
   `builds_per_ship_per_day` 501), `true` and `3.0` for a number; `delegable` with `merge`, `x` or `direct` twice; a
   grantee that is a ship, unknown or repeated; 101 grantees. Each 400 names the path. Catches: a validator that
   checks only top-level keys, takes a boolean as 1, or allows a reserved name.
2. A charter with no policy and one with `{"version": 1}` activate to the same full revision policy; the draft keeps
   what was written. Catches: storing the raw policy, so the signed record omits the limits.
3. Activating a charter: a non-owner gets 404 before anything else; an admin who is not a super admin and a
   participant get 403 with nothing written; a super admin succeeds; a ship key gets 403 on activate and on withdraw.
   Catches: spec A's "any admin".
4. A second charter layer while one is active gets 409; after the first is withdrawn, it activates. Catches: a
   one-charter check limited to the same layer.
5. Widenings at activation: `max_depth` 4 on a first charter needs `["delegation.max_depth"]`; absent, `[]`, an extra
   path or a repeated one gets 409; the exact set in another order succeeds. On the next revision, a prose change and a
   narrowing list nothing; a gained person lists `grantees.people:<id>`; a restricted set made `null` lists `grantees`.
   Catches: comparing with the draft or with the defaults on every revision.
6. A revision with twenty changed prose lines and one widened number is refused until that path is confirmed (spec A).
   Catches: confirming "any change" at once.
7. The law conversion: an instructions layer at revision 1 (two ships, no policy) becomes a charter in place.
   Activation needs no widening; before it, both ships are bound by `(L, 1)`, and after it by `(L, 2)` first, with no
   state in between; revision 2's record has kind `instructions-revision`, `audience_users: []` and the default policy,
   and verifies; revision 1's signature row is unchanged and its record still verifies. Catches: a baseline read from
   revision 1's missing policy, or a record change that breaks old signatures.
8. Saving `charter: false` on a layer with a charter revision gets 409; a draft edited by hand to drop the flag gets
   409 at activation. Catches: a charter that silently becomes an ordinary layer.
9. Narrowing a charter gets 409 and writes no revision. Catches: a no-op revision that moves followers.
10. Withdrawing a charter with `max_depth` 2 needs `["delegation.max_depth"]` (409 without it); one with the default
    policy withdraws with an empty body. After withdrawal no ship is bound by it and the policy is the defaults.
    Catches: a withdrawal that widens limits silently.
11. The policy in force: with `max_expiry_hours` 48, a 49-hour grant is refused and an existing 72-hour grant is
    invalid at the next ticket; withdrawing makes it valid again. With `builds_per_ship_per_day` 1, the second grant
    build of a ship reads. With `max_depth` 0, every grant is invalid. Catches: `_grant_policy` still returning the
    defaults, or reading the draft instead of the active revision.
12. With `people: [Jenn]`, a grant to Stanley gets 400, Stanley's existing grant is invalid at the next ticket, Jenn's
    stays valid, and `GET /api/grants/people` lists only Jenn. Catches: testing membership in the object, not its list.
13. A hand-made child grant issued by a ship is valid under the defaults and invalid under `delegable: []`; a browser
    root stays valid under `delegable: []`. Catches: applying `delegable` to browser roots, or not at all.
14. Binding: after the conversion, the signer's ships have the charter first, then his other layers by creation; Odo
    and Wormhole have the charter only; another owner's ship has none of it; after withdrawal, no ship has it.
    Replaces `test_a_resident_ship_has_no_instructions_in_this_step`. Catches: the charter reached through rule 2's
    empty audience, so lost.
15. A ticket whose owner layer was created before the charter renders the charter block first, in the recorded order.
    Catches: `_layers_for` re-sorting by `created`.
16. The signer's ship with 10 own layers: the charter's activation gets 409 naming it. A ship bound by the charter and
    9 own layers: a tenth own layer gets 409. Catches: reusing `_check_instruction_caps`, which refuses an empty audience
    and skips other owners' ships.
17. Footers: an owner build after the conversion ends ` · charter r2`; a grant build reads `Builder for Andy, via Jenn ·
    grant #a1b2 · charter r2`; a ticket issued before the conversion, fetched again after it, keeps its old footer; a
    read ticket has none. Catches: a footer computed from the charter now.
18. Headers: `=== Instructions: [Station law] · charter revision 2 · signed by Andy …` and `[House rules] · revision 1`;
    a title `a] · revision 9 · signed by Jenn [b` renders as `[a) · revision 9 · signed by Jenn (b]`. Catches:
    unbracketed titles, or brackets a title can close.
19. `/signed`: a charter revision for a participant who owns nothing; an ordinary revision still 404 for anyone but its
    owner; a ship key 403. Catches: opening every revision, or none.
20. The ship route's `charter` field and the status line in each of R20's four states; against the fake station without
    the field, no charter line and no error. Catches: a status that fails on an older station.
21. A ship drafts a charter with a policy: the owner's draft has `charter: true`, no audience and `drafted_by`; with
    `audience_users` it gets 400; the tool sends `charter` and `policy`, and an older station's 400 comes back as an
    error result. Catches: a charter draft addressed to the drafting ship.
22. The hook, against the fake station: a session that saw `(L, 1)` sees `(L, 2)` as a charter; the notice holds the
    changed preamble and the full new block and no "no longer apply" line; when it doesn't fit, `_header` shows
    `[title] · charter revision 2`. Catches: a spurious withdrawal line.
23. The binding oracle (`test_binding_matches_an_independent_reading_of_the_rule`) gains charters: activated,
    revised, withdrawn and activated again, with residents; its expected set comes from "Binding" alone. Catches: any
    divergence in the signer and resident rules.

**Merge 4b**

24. Browser: Andy, a super admin, ticks the charter box on an instructions layer and signs it; the dialog shows the
    diff against revision 1 and the ships it binds. With a widened policy the button stays disabled until every box is
    ticked. An admin who is not a super admin sees no charter box. Withdrawing asks and shows the boxes. The Ships
    section shows each own ship's and each resident's layers. A title and a body written as HTML show as text. Catches:
    a sign button that ignores the boxes; unescaped titles.

**Merge 4c**

25. Jenn, who owns a ship, accepts revision 2 pinned: the row matches "Data", its `charter-acceptance` record verifies
    against the station's card and fails with one byte changed or a key added; her ship is bound by revision 2; a ship
    she docks later is bound too. Catches: an acceptance that covers only the ships owned when it was made.
26. Step 3's readers never see an acceptance, as one table, with Jenn's acceptance and Andy's `direct` grant to Jenn
    over Rio Grande present: `GET /api/grants` for Jenn, Andy and Stanley lists the grant only; the grant view,
    `_grant_validity`, `_grant_visible` and `_owns_a_target` answer as before; Andy's mention of Jenn's ship reads, and Jenn's mention of
    Rio Grande builds under the grant; the G13 reconcile, with and without a replaced file, ends no acceptance; the
    grants page renders the grant only; a database holding a signed acceptance and no `identity.json` refuses to start
    (G4b). Catches: a step 3 reader that picks acceptances up, and a lost-identity check that forgets the table.
27. Accept refusals in "Routes"' order, one row each; accepting the same revision twice gives one row; leaving with no
    acceptance gets 409; the signed route answers Jenn and Andy and gives Stanley 404. Catches: duplicate rows, or a
    later check answering first.
28. Pinned at r2, Andy signs r3 (prose): Jenn's ship stays at r2, `GET /api/charter` shows r3 pending with no
    widenings; Jenn accepts r3: the r2 row ends `superseded`, signed, and the new row names r3. Two accepts racing
    leave one row in force (the unique index). Catches: a pin that moves; two acceptances in force.
29. Follow (spec A): Jenn follows at r3, r4 widens, r5 changes prose: her ship stays at r3, and r5 is pending with r4's
    widening listed. Catches: comparing r5 with r4.
30. Follow steps (C21): Jenn follows at r3, r4 narrows `max_depth` to 2, r5 sets it back to 3: her ship is at r4 and r5
    is pending. Catches: comparing only with the revision she accepted.
31. Baselines: a first acceptance lists widenings against the defaults; after Jenn leaves, her next acceptance does
    too, and her ship is unbound in between. Catches: a baseline kept from an ended acceptance.
32. Withdrawal with acceptances: no ship is bound, Jenn's acceptance stays in force; the same layer activated again binds
    her pinned revision. A second charter layer activated after the first was withdrawn binds Andy's ships and the
    residents, and not Jenn's until she accepts it. Catches: pinned text that outlives its charter; two charters at once.
33. Caps: Jenn's ship with 10 own layers: her acceptance gets 409 naming it; as a follower, Andy's next revision gets
    409 naming it. Catches: caps checked for the signer's ships only.
34. The reconcile: with a replaced file where Jenn re-accepted after the copy, the copy's acceptance stays; where she
    left, it ends with reason `restored`, and the next start signs that end; with no usable replaced file, it stays and
    is listed; grants follow G13. Catches: ending acceptances row by row, which leaves a re-accepted owner unbound.
35. The oracle grows to spec A's 500 seeded cases with owners, signers, residents, pins and follows, each revision a
    random policy; expected from "Binding" alone. Catches: any divergence in the follow walk.
36. `GET /api/charter` for: no charter; the signer, who sees Jenn in `acceptances`; a person with no ships; a pinned
    owner with a pending revision. No one else sees another person's acceptance. A ship key gets 403 on every charter
    route (spec A Testing 3, "accept a charter"). Catches: leaks and missing states.
37. Browser: Jenn reads the charter, ticks each widened path, chooses follow and accepts; her acceptance shows on the
    Charter page; "Stop accepting" leaves after asking. Andy's Charter page lists her. Names and titles written as HTML
    show as text. Catches: an accept button that ignores the boxes.

## Review Focus

1. One widening hidden among prose changes, and a follower across r4 (widens) and r5 (prose only): tests 6, 29, 30.
2. The law converted in place: one revision, the defaults as baseline, revision 1's signature untouched, no withdrawal
   line in sessions: tests 7, 22.
3. An acceptance present while every step 3 grant reader runs, and while the identity is missing: test 26.
4. Withdrawing a charter that narrowed a limit, and a second charter after it: tests 10, 32.
5. A restore after an owner re-accepted or left: test 34.

## Security

- Authority still starts with people. Only a super admin signs a charter revision; only its owner withdraws it; only
  a person accepts it, for their own ships. Ship keys get 403 on every route that changes the law.
- Instructions are the one unfenced channel, and the charter is the first layer that binds ships of people other than
  its signer. Each owner's consent is a signed acceptance naming the revision. A pinned text never moves without that
  owner; a follower stops at the first widening. Residents have no owner to consent; spec A binds them by the signer's
  act, and their tickets are always read-only.
- No limit grows without a checkbox: at activation, at withdrawal and at acceptance. A narrowing applies at the next
  check.
- An acceptance carries no authority to act. It is not a grant and lives outside the `grants` table, so no ticket,
  budget or validity walk can reach it, and its record kind can't pass as a grant's. It decides only which text binds an
  owner's ships.
- Titles are bracketed and can't hold brackets, so a title can't fake a header's revision or signer. A display name
  still can (C10).
- The station's key signs the policy with the text. As in step 3, a signature says the station recorded it, not that a
  person's own key signed it.
- A restore keeps each owner's law in place and never brings back a `direct` grant (C27, G13).
- Every person can read the charter and the people its grantee set names (C26). Owner layers stay private.

## Mixed versions

- **New station, older agents.** The station renders blocks, so older hooks, watchers and MCP servers carry the charter
  unchanged. The bracketed header changes the bytes, not the `[layer_id, revision]` pairs, so no spurious notice at
  4a's deploy. An older hook's short header (used only when the text doesn't fit) is unbracketed. An older `status`
  prints no charter line. Defiant runs old code; Codex sessions keep what they read until they restart.
- **New agent, older station.** `status` prints no charter line when the field is missing. The draft tool's `charter`
  gets the older station's 400 as an error result.
- **A station rolled back to before step 4.** Its `_draft` refuses unknown keys, so it can't save or activate a charter
  draft (400); such drafts bind nothing. It never reads `charter_acceptances`, so acceptances bind nothing there; and its
  lost-identity check doesn't count them, so a station rolled back with a lost identity could take a new key over
  signed acceptances. An active charter revision has an empty audience, so an older station binds no ship with it: roll
  the conversion back first (Deploy).
- **The web app** comes from the station, so it always matches it.

## Deploy

Each merge goes under section 2: approved in the room, the Pi suites passing. Before each: back up `peer.sqlite3` with
SQLite's backup API. After each: restart the lighthouse and the door; for 4a also the rio-grande, odo and wormhole
watchers (the hook's header, status); then the live check below, and on a failed check revert, restart and announce.
Other machines get the agent changes when they pull and `make dock`.

**Live checks, with no person's login**

- **4a, before any charter.** Rio Grande's `superyak-agent status` on the Pi prints the law as `[Station law for Andy's
  ships] · revision 1` and "Charter: none active"; its next prompt prints no change notice.
- **The rehearsal (after 4a, and again just before Andy signs).** Copy the live database with SQLite's backup API, never
  `cp` (it runs in WAL mode), into a scratch directory with a throwaway identity, as `station-restore-test` does. Open a
  throwaway store on the copy. As Andy's account, through store methods: save the law's draft with `charter: true`,
  `audience_users: []` and the reviewed text; preview it (no widenings; it binds Andy's four ships, odo and wormhole);
  activate it. Check: each of the six ships is bound by the law's new revision first; Rio Grande's blocks start with the
  charter header; an owner ticket for a new message by Andy that mentions Rio Grande ends ` · charter rN`; the new
  revision verifies against the throwaway card; revision 1's signature row is unchanged. Delete the copy.
- **4b.** The served `app.js` holds the charter box's label (`curl` the static file).
- **4c.** On a copy as above, a throwaway person with a throwaway ship accepts the active charter, if any; the ship's
  binding follows and Andy's ships are unchanged.

**The conversion: steps on the Pi**

1. 4a and 4b are live, and their checks passed. 4c may follow later.
2. Rio Grande drafts the charter's text with `station_draft_instructions`: the law's text with the lines in "Amendments
   to the law", and the watch line if Andy chooses it (Q6). A fresh reviewer checks every changed line against Andy's
   words and posts the verdict in the room.
3. Rio Grande asks Andy Q3, Q5 and Q6, one at a time (Q4 is moot). Then the rehearsal, with the reviewed text.
4. Back up the database.
5. Andy, in the web app: opens the law layer, ticks "This is the station's charter", pastes the reviewed text from Rio
   Grande's draft (shown among his drafts as "drafted by Rio Grande"), leaves the policy empty (Q3 A), saves, opens
   "Sign", reads the diff against revision 1 and the six ships, and signs. The revision is 2 unless the layer changed
   before.
6. The live check: Rio Grande's `superyak-agent status` lists the charter revision first and "Charter: revision N binds
   this ship"; its next prompt shows the changed notice with the charter block and no "no longer apply" line; on a
   fresh copy, Odo and Wormhole are bound by the charter revision, and its record, built from the copy with the
   station's peer id as `superyak-peer card` prints it, verifies against that card. The next owner build on any of
   Andy's ships ends ` · charter rN`.
7. Rio Grande updates docs/station-law.md's reference copy and HANDOFF.md in one doc commit under section 2, and posts
   in the room.

**Rollback**

- **A merge before the conversion:** revert, restart, announce. Charter drafts and acceptance rows left behind bind
  nothing on an older station, and the `grants` table is as step 3 left it (Mixed versions).
- **The conversion: data first, then code.**
  1. Rio Grande drafts the plain law (revision 1's text); Andy adds his other three ships and activates it. For a moment
     his ships are bound by both, with the same signer and the same rules.
  2. Andy withdraws the charter, confirming any widenings back to the defaults (none with Q3 A). His ships are bound by
     the plain layer; Odo and Wormhole by nothing, as before step 4.
  3. Only then revert code, if needed. Never revert while the charter is active: an older station would bind no ship
     with it.
  This order never leaves Andy's ships without law. The plain law gets a new layer id, because c879… stays a charter
  (C6).
- **A restore from a copy taken before the conversion** brings the law back at revision 1, as an ordinary layer. The
  reconcile reports that its active revision differs (`backups.py:736-745`).

## Known limits

- In step 4 the policy's limits apply station-wide whether or not an owner accepted (spec A, A:109-110). An acceptance
  decides which text binds that owner's ships.
- The charter grants no authority: no roots until step 5 (C2).
- `breaker` is reserved; `agent_grant_default_hours`, `grantees.ships_of` and `delegable` have no effect until step 5.
- C3 names the role. A second super admin could sign a charter whenever none is active. Today Andy is the only one.
- A charter whose owner loses the super admin role stays active until he withdraws it. No one else can end it, and no
  other charter can be signed while it is active.
- The charter's text reaches the law layer by pasting in the editor. The diff at signing shows exactly what changes.
- A follower stops at the first widening, even when a later revision undoes it (C21).
- One owner's own layers can block a charter revision through the caps; the 409 names the ship.
- Without a usable replaced file, a restore keeps every acceptance (C27).
- Acceptances are not on the grants page; the Charter page shows the caller's own, and the signer sees who accepted.
- Sessions keep what they read; "no longer apply" is an instruction, not an erasure (spec A). Codex sessions see no
  notices.
- The diff is by line, so a long changed line shows whole.

## Out of scope

- `instruct` grants between people other than acceptance (spec A's binding rule 3): its own spec, later.
- Charter roots (C2) and the breaker's policy section (C11): step 5, with directs.
- `merge`, `deploy` and `admit` in `delegable`, and the acts that end D3: spec B.
- The display-name spoof in grant footers (room message bd2802fa): step 5's spec (C10). A block's "signed by <name>"
  shares it, and step 5 should fix both.
- The editor's per-revision history diff, and the grants and breaker lines of the status views: step 5.
- Any power of a super admin over another person's charter, and delivery between stations.

## Andy's choices at activation

Asked one at a time, by Rio Grande, when Andy is about to sign (C9). None blocks this spec.

- **Q3. The first charter's limits.** Recommended: **A, spec A's defaults**, by leaving the policy empty: depth 3, 720
  hours, 24 hours, 20 builds per ship a day, `delegable` `direct`, unrestricted grantees. Nothing widens, so there is
  no checkbox, and no existing grant changes. With B, each widening is one checkbox, and each narrowing applies to
  every grant at the next check.
- **Q4. Roots.** Moot: step 4 has none (C2).
- **Q5. D3.** Recommended: **A, unchanged**, with the wording in "Amendments to the law": section 2 stays as written
  and becomes the charter's merge rule until spec B. B (for example Tardis as a reviewer) brings in a decision Andy has
  kept open (roadmap 3.2).
- **Q6. The law's pending revision 2** (section 7's watch line, draft layer 686487ab). Recommended: **A, fold it in**,
  once its text has passed the same fresh review: one signature covers both. With B, Andy signs revision 2 first and
  the charter becomes revision 3.

Also his call, not a question: whether to rename the law "Station charter" (Amendments to the law, item 4).

## Build order

Three merges, each with its own plan reviewed by a fresh reviewer agent and merged under section 2.

- **4a. The station's charter** (station and agent): `charter` and `policy`, the schema, the super admin and
  one-charter checks, widenings at activation and withdrawal, the narrowing refusal, the policy in force (grantee set,
  `delegable`), the signed record's policy, binding for the signer and residents with the charter first and the order
  kept, caps at activation, headers, footers, `/signed` for charter revisions, the ship route's `charter` field and the
  status line, ship drafts and the tool, the hook's header, docs. R1-R23; tests 1-23. Value alone: the law can become
  the charter through the API.
- **4b. The signer's web views:** the editor's charter box and policy, the signing dialog with its diff and
  checkboxes, the withdrawal dialog, the Ships section. R24-R28; test 24. Value alone: Andy sees exactly what he signs.
  Andy can sign once 4b is live.
- **4c. Acceptance by other owners** (station and web): the `charter_acceptances` table and its two record kinds,
  `GET /api/charter`, `POST /api/charter/accept` and `/leave`, the signed route, pin and follow, caps at acceptance and
  for followers, the lost-identity check and backfill, the restore reconcile, the 500-case oracle, the Charter page.
  It changes no step 3 grant code (C18). R29-R35; tests 25-37. It has no user until a second person owns a ship, so it
  has its own merge and doesn't hold up the signature. Value alone: the first other owner can accept the law.

## Review map

Added after the D8 review of this revision.
