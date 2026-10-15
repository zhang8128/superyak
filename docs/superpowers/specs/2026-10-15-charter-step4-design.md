# Spec A step 4: the charter

Status: revision 2, for the D8 re-check. Rio Grande owns this spec; this draft was written for it. A fresh reviewer
approves it in Andy's place (law section 3, D8), and its summary and decisions are posted in "Superyak: city of AI".
Andy can veto anything. Revision 1 (592faa3) was reviewed: APPROVE WITH CHANGES, with 1 must-fix, 9 should-fix and 13
nits, and Serenity's five notes folded in. This revision takes every finding, under Rio Grande's rulings on them;
"Review map" at the end says where each one went.
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
- D3, the merge rule, stays prose in the charter's text until a charter revision Andy signs replaces it (spec B).

## Decisions

Each line is this spec's ruling. A fresh reviewer checks it; Andy can veto any of them.

| # | Ruling | Why | Cost |
| --- | --- | --- | --- |
| C1 | **Scope** (Rio Grande's ruling 6). In: the charter flag and its rules; `policy` and its schema; widened paths with `confirm_widenings` at activation and acceptance; acceptance by owners (pin or follow), kept apart from step 3's grants (C18); binding with the charter first; residents bound by it; the policy's limits station-wide, where step 3's code reads the policy; `· charter rN` in footers; status; the web views for activation and acceptance; docs. Out: other person-to-person `instruct` grants, charter roots, spec B's acts, directs. | What makes the law the charter, and what the first other owner needs to accept it. | Acceptance by other owners is the largest part and has no user until a second person owns a ship (survey 3.3). It gets its own merge, 4c, and Andy's signature doesn't wait for it (C31). |
| C2 | **No charter roots** (ruling 1, survey Q1). Step 4 materializes no roots. A policy with a `roots` key is refused with 400: the key is reserved for step 5. | A root would name a ship (A:89), and a ship spends a `direct` grant only through step 5's directs (step 3, S2). This is the narrower choice. | The charter hands out no authority in step 4; Andy's browser grants still do. No root widenings, no `superseded` roots, no "still active and accepted" check. Andy can widen this later. |
| C3 | **Only a super admin may activate a charter revision** (ruling 2, survey Q2). This amends spec A's "an admin" (A:49, A:71). | D1: "he signs the charter" (A:30). Any admin could otherwise bind every resident ship at once (survey Q2 A). | One check (`_super_admin`, `auth.py:122-125`). It names the role, not Andy's account (Known limits). |
| C4 | **The law becomes the charter in place** (ruling 3). Layer c879… gets a new revision with `charter: true`, `audience_users: []` and a policy. | One act and one signature (roadmap 2.3). The binding moves from the audience rule to the charter rule in one transaction, so no ticket or fetch sees Andy's ships bound twice or not at all (survey 4.3). | The layer can never be an ordinary layer again (C6). Revision 1 stays as the plain law's signed record. A rollback after the conversion uses a new layer (Deploy). |
| C5 | **The baseline at activation is the policy in force:** the active charter's policy, or the no-charter defaults when no charter is active. So when the previous active revision has no policy, as the law's revision 1 has none, the baseline is the defaults (ruling 3). | Spec A's "the previous active revision, or for a first charter the no-charter defaults" (A:101-102) assumes the previous revision has a policy. A widening grows from what is in force. | With spec A's defaults as the first policy (Q3 A), the conversion has nothing to confirm. |
| C6 | **A charter stays a charter** (ruling 3). Once a layer has a charter revision, saving or activating its draft without `charter: true` is refused with 409, before any other check of the draft. To end a charter, its owner withdraws it (C15). | Clearing the flag would end the charter for the residents and every accepting owner through a draft edit, and change the rule under which the same text binds. Withdrawal says plainly that the charter ends, and checks the limits that return to the defaults. The safe answer. | A charter can't step back to an ordinary layer. Rollback uses a new layer (Deploy). |
| C7 | **The hook's change notice** (ruling 3). The layer id stays the same, so a session sees the existing changed-revision notice: the new block in full, and no "no longer apply" line. The block's header marks the charter (C25). | `hook.py` keys notices by layer id and revision (`:450-491`); only a layer that disappears prints "no longer apply" (`:455-456`). | Codex sessions get no notice and keep what they read until they restart. |
| C8 | **D3 stays prose until spec B** (ruling 4). The first charter revision's text must change the law's "until the charter exists" lines (sections 1 and 2), so that section 2 is the charter's merge rule until a charter revision Andy signs gives merging and deploying rules of their own. "Amendments to the law" proposes the wording. Rio Grande drafts it later as a layer draft. No code reads it. | A charter whose text still says "until the charter exists" ends section 2 when signed, and section 1 then sends every merge to Andy (survey 4.4). Policy version 1 can't express D3: `merge`, `deploy` and `admit` are reserved for spec B (A:94-95). Tying the end of section 2 to a revision Andy signs, not to spec B's approval, keeps it in his hands (review S4). | A fresh reviewer must check the rewording against Andy's words before he signs, as for the law's revision 1 (roadmap 0.2). |
| C9 | **Andy's choices** (ruling 5, as amended by review S1). Q5, Q6 and the rename change the charter's text, so Rio Grande asks them first, one at a time, before the text is drafted and reviewed. Q3 changes only the policy and is asked at signing. None blocks this spec. | They are about the first charter's content, not the code. A text reviewed before Andy answers could turn out wrong and need a second review. | Andy answers three questions before the drafting starts, and one at signing. |
| C10 | **The display-name spoof in grant footers** (room message bd2802fa) goes to step 5's spec (ruling 7). | Step 5 adds more names to footers (chains of ships) and fixes them together. | Until then a person's chosen display name can read like another's (Out of scope). |
| C11 | **Policy schema:** spec A's version 1 without `roots` (C2) and without `breaker`, also reserved for step 5. A charter always has a policy: a missing policy, section or key takes the default; a missing `agent_grant_default_hours` defaults to 24 or `max_expiry_hours`, whichever is smaller. Cross-checks run after the defaults are filled. The revision stores the full policy; the draft keeps what was written. | Spec A gives no bounds for the breaker's numbers, and step 5 builds the breaker; a checkbox for a number nothing reads confirms nothing. A full stored policy makes the signed record state every limit in force, and marks a charter revision by its policy alone (C12). A fixed default of 24 would make every policy with `max_expiry_hours` under 24 fail its own cross-check (review N7). | Step 5 adds `breaker`; a charter without it reads as the defaults. `agent_grant_default_hours` and `grantees.ships_of` have no reader until step 5 either; they stay because spec A bounds them. |
| C12 | **The signed record keeps its kind and keys.** `instructions-revision`'s `policy` comes from the revision's snapshot: the full policy on a charter revision, `null` on every other. | Step 3 reserved `policy` for this (G2). `verify_record` checks the key set exactly (`identity.py:76-87`). With C11 a non-null policy marks a charter revision. Every signature made so far verifies unchanged. | A reader of a record must know that rule; peer/API.md states it. |
| C13 | **Widened paths.** A widening is a number that grows, a set that gains a member, or a restricted grantee set that becomes unrestricted. The station lists them sorted by path ("Data"). `confirm_widenings` must hold exactly those paths, each once, in any order: at most 105, the most the schema allows. | Spec A (A:98-103). Sorting keeps the list stable; set equality lets the browser send ticked boxes in any order. A lower cap would make some revisions impossible to sign (review N2). | A client fetches the list first (the preview, or `GET /api/charter`); a stale list gets 409. |
| C14 | **Narrowing is refused on a charter** (`POST /api/layers/{id}/revoke`, 409). | A charter has no audience to narrow. The route writes a new revision even when nothing is removed (`layers.py:143-167`), which would move followers with no widening check (survey 3.2 item 8). | None: a new revision or a withdrawal does what a narrowing could. |
| C15 | **Withdrawal.** The charter's owner withdraws it, whatever their role now. It needs `confirm_widenings` for the paths that widen from its policy to the defaults. A withdrawn charter binds no ship: not the signer's, not a resident, not a pinned owner's. Acceptances stay, and bind again if the same layer is activated again (C21 and C23 say how). | Withdrawal is a policy change back to the defaults (A:383), which can widen what the charter narrowed (survey risk 4). Pinned text that outlived its charter would let two charters bind ships on one station (survey risk 3). A signer must always be able to end their charter. | An owner has no charter law while none is active and accepted. A charter whose owner loses the super admin role stays until they withdraw it. |
| C16 | **The policy in force, station-wide** (A:109-110). `_grant_policy` returns the active charter's policy, flattened as today, or the defaults. The flattened `grantees` is the `people` list, or None when unrestricted. Readers: `max_depth` (validity, counting a chain's links, root included, as step 3 built; and making a grant, refused while it is 0), `max_expiry_hours` (making a grant, validity, and the grants form's durations through `GET /api/grants/policy`), `builds_per_ship_per_day` (tickets, the grant view), `grantees.people` (making a grant, validity, the person list) and `delegable` (validity, for links a ship issued). | One function, as step 3 planned (G7). A narrower limit takes effect at the next check (A:198-202). A grant made under `max_depth` 0 would be invalid from its first moment, and a form that offers durations the station refuses fails on its first choice (review S9). | `delegable` governs only links a ship issued, and step 4 has none: it is checked, tested on a hand-made row, and has no effect until step 5. Under a restricted set, validity refuses every ship grantee, even one whose owner is in `ships_of`: narrower, and right while no ship holds a grant; step 5 must change it (review N13). |
| C17 | **The signer accepts by signing,** with no acceptance row. The active charter revision binds every ship its owner owns. | "An admin who activates a charter has accepted it" (A:136-137). A row would record the signer accepting from themselves (step 3 refuses a grant to oneself, `grants.py:255-256`), and a restore could end it and leave the signer's ships unbound (survey risk 6). | A signer can't pin an older revision of their own charter. They control the active one. |
| C18 | **An acceptance is a row in its own table,** `charter_acceptances`, not in `grants`: one row per act, naming the person, the charter's signer, the layer, the revision and `follow`. It is signed as a record of its own kind, `charter-acceptance`; ending it is signed as `charter-acceptance-revocation`. A new acceptance ends the person's previous one with reason `superseded`, and a partial unique index keeps one in force per person. No `grant_pins` table. This departs from spec A, which records an acceptance "as an `instruct` grant" with `targets: "own"` and no expiry (A:132-136, A:165-166, A:170). | Step 3's grant code assumes a list of ship ids, an expiry within `max_expiry_hours` and a budget of at least 1: validity reads `"own"` as the ids `o`, `w`, `n` (`grants.py:117`) and fails the lifetime check (`:110`); the grant view and the grants page map targets as ships (`:191`, `app.js:743`); NULLs would need a table rebuild, since `expires` and `budget` are NOT NULL (`:11`), and `canonical` refuses infinity (`identity.py:20-23`); the reconcile revokes every grant a replaced file lacks (`backups.py:518-546`). A helper that hides acceptances from every grant reader would keep the rows in `grants` while no grant route used them, and any reader that missed it would show or fail on one. A table of its own leaves every step 3 invariant and reader as it is, needs no rebuild, and makes 4c a self-contained merge. The record could reuse the `grant` kind, since spec A calls an acceptance a grant; a kind of its own is safer, because it keeps an acceptance from passing as a grant something could spend (step 3, S7). The pin is in the signed row, never in an unsigned `grant_pins` row (survey 3.2 item 10). | A departure from spec A, stated in Amendments. The grants page doesn't list acceptances; the Charter page does. `RECORD_KEYS` gains two kinds, and the lost-identity check and the startup revocation backfill gain the table. Spec A's rule 3 (`instruct` grants between people) gets no shared machinery from acceptance (C1 leaves it out). |
| C19 | **An acceptance binds while it is in force** (not revoked) and its layer still exists. It is never a grant: no grant route, validity walk, ticket, budget or grant reconcile reads it, and it carries no expiry, budget or targets. | It has no expiry and no builds (A:134-135), and covers whatever ships its person owns, now or later. | An owner who wants to stop must leave (`POST /api/charter/leave`); nothing ends an acceptance by itself. |
| C20 | **Only the active revision can be accepted.** The baseline at acceptance is the revision that binds the caller's ships now (pinned, or followed to), or the no-charter defaults when none does, as at a first acceptance. | Spec A (A:104-106). The page then has one thing to accept. | No owner can accept an older revision than the active one. |
| C21 | **Follow moves one revision at a time** over the layer's existing revisions, each compared with the revision binding the owner then. It stops before the first revision that widens, before one that would put one of the owner's ships over the caps (C23), and at a withdrawal. A skipped revision number marks a withdrawal: only `withdraw_layer` advances `resource_version` without writing a revision (`layers.py:127-139`). The revision it stops before, and every later one, show as pending. | Spec A: "the newest without a widening against O's baseline" (A:115-116), and a widening "cannot ride in on a prose-only r5" (A:107-108). Stepping is the narrower reading: after r4 narrows `max_depth` to 2, an r5 that sets it back to 3 is a widening for a follower bound by r4. A follower carried across a withdrawal would be bound by a re-activated charter's new text without having seen any of it (review N12). A follower's own layers must not let them block every later revision for everyone (review S6). | A follower stops more often and accepts by hand. If later code advanced `resource_version` for another reason, followers would stop more often, never less. |
| C22 | **Binding** (spec A rule 1, amended). For a ship: first the charter revision that binds its owner (C17, C18, C21), or for a resident the active one; then its owner's own active instructions layers that list it, by creation. A withdrawn charter binds nothing. Spec A's rule 3 stays out (C1). | Spec A's order (A:139-140) and residents (A:123-124). | Odo's runs carry the charter from the moment Andy signs, with no consent of their own. |
| C23 | **Caps** (A:75-77). At a charter activation, every ship whose binding the activation changes is checked with its new binding: the residents and the signer's ships, and from 4c, the ships of owners whose acceptance binds again after a withdrawal. Any of them over 10 layers or 48 KB gets 409 naming the ship. A follower's ships are never refused this way: a revision that would put one of them over the caps stops that follower, as a widening does (C21). At an acceptance: every ship the caller owns, 409. An owner's own activation counts the charter. | `_check_instruction_caps` refuses an empty audience and skips ships the activator doesn't own (`instructions.py:94-103`), so it can't serve as it is (survey risk 9). A ship re-bound after a withdrawal can have gained layers meanwhile, and spec A drops nothing silently (review S5). One follower's layers would otherwise refuse every later revision, and the signer can't end their acceptance (review S6). | A pinned owner's own layers can block re-activating a withdrawn charter; the 409 says which ship. A follower near the caps stops and accepts by hand. |
| C24 | **The footer gains `· charter rN`** when the ticket's recorded instructions include a charter revision; N is that recorded revision. | Spec A's footer (A:310-311). The ticket's record, not the charter now, so a footer never changes after its run. | Tickets issued before the conversion keep footers without it. |
| C25 | **Titles are bracketed** in block headers, in the hook's short header and in `superyak-agent status`, with `[` and `]` inside a title shown as `(` and `)`. A charter says `charter revision N`. | HANDOFF: bracket titles "once other signers can bind a ship", and the charter is the first. With no inner brackets, the title's bounds can't be faked. Status shows the same titles, so it gets the same form (review S2). | The block's bytes change at 4a's deploy but its `[layer_id, revision]` pairs don't, so no session sees a spurious change notice. |
| C26 | **Who reads a charter revision** (review M1, Rio Grande's ruling). Every signed-in person reads the active charter revision: its text (`GET /api/charter`, as spec A gives it) and its signature. Any other charter revision, withdrawn or superseded, goes, text and signature, only to its signer and to a person whose acceptance names it now or did before. A follower's acceptance names the revision its walk binds now as well as the one it was made at. Other revisions stay owner-only (step 3, G6). An acceptance's signed record goes to its person and the charter's signer. | Spec A gives every person the active charter (A:131-132), and step 3's G6 planned to add only "the owners whose ships a revision binds". A past revision reaches only people who signed it, accepted it or are bound by it. | A person who never accepted can't read a past revision, even one that was once in Odo's prompt. The active charter's policy, with the names of any people it lists, is visible to every person on the station. |
| C27 | **Restore treats acceptances by person, not by row,** and never adds one. A person's acceptance in the restored copy is ended when the replaced file holds none in force for that person, and kept otherwise. Without a usable replaced file it is kept. The report lists each acceptance it ended or kept, and also each person whose acceptance in the replaced file is lost: one who accepted only after the copy (now bound by none), and one who re-accepted after it (now back at the copy's revision and `follow`), each with the revision they had. Grants are reconciled exactly as G13 says. | Ending an acceptance takes law away from that owner's ships, the opposite of the reconcile's purpose (survey risk 6). Row by row, a re-acceptance after the copy would end the copy's row as superseded and leave the owner with none. The two lost cases would otherwise pass in silence, and Andy needs them to ask those people to accept again (review S8). | Without a usable replaced file, an owner who left after the copy is bound again until they leave again. |
| C28 | **Ships draft charters** (A:126): the drafts route and `station_draft_instructions` take `charter` and `policy`. A charter draft has no audience. For the conversion, though, Rio Grande drafts the text as an ordinary draft. | Rio Grande drafts the charter's text (C8). An ordinary draft can't be signed as a charter by mistake: signing a charter draft layer instead of converting c879… would make it a charter for good and block the conversion while it is active (review N6). | A non-super-admin owner can hold a charter draft they can't sign; it binds nothing. |
| C29 | **Status.** `GET /api/ships/me/instructions` marks the charter layer and gains a `charter` field; `superyak-agent status` prints one charter line. The web's Ships section shows the binding layers of the caller's own ships and of resident ships, from a field 4b adds to `GET /api/ships`. | Spec A's status (A:360-362). Its grants and breaker parts are step 5's. | An admin isn't shown other owners' ships' layers: they would reveal those owners' layer titles. |
| C30 | **Web.** Line diffs where a person signs or accepts: the draft against the active revision at activation, the pending revision against the binding one at acceptance, computed in the browser. The editor takes the policy as JSON, for super admins only. Narrowings need no checkbox, so the signing dialog states their effect in words. | A:103, A:154-155. Some narrowings are drastic, such as an empty grantee set or `max_depth` 0 (review N11). | The editor's per-revision history diff waits (Out of scope). The activation diff shows each revision against the one before it when it is signed. |
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
4. A:75-77, the caps: "Activation is refused with 409 if it would bind more than 10 layers to any ship in its audience"
   gains "; for a charter, any ship whose binding the activation changes, except a follower's, whose walk stops before
   that revision instead (C23)".
5. A:78-79: "Activation, revisions, narrowing and withdrawal are the existing layer routes." gains "Narrowing is refused
   on a charter (C14), and withdrawing one needs `confirm_widenings` (C15)."
6. A:101-102: "the previous active revision, or for a first charter the no-charter defaults" becomes "the policy in
   force: the active charter's policy, or the no-charter defaults when no charter is active, including when the layer's
   previous revision was not a charter (C5)".
7. A:104-108: "and each root that names the owner is also listed for confirmation" is removed (C2). "A 'follow'
   acceptance moves the owner forward only to a revision with no widening against their own baseline." becomes "A
   'follow' acceptance moves the owner forward one revision at a time over the layer's existing revisions, each compared
   with the revision binding the owner then; it stops before the first that widens or that would put one of the owner's
   ships over the caps, and at a withdrawal (C21)." Only the active revision can be accepted (C20).
8. A:115-118, binding rule 1, gains: "A withdrawn charter binds no ship (C15). The charter's signer's ships are bound by
   its active revision (C17). Roots: none in step 4 (C2)."
9. A:123-124: "when an admin activates it" becomes "when a super admin activates it".
10. A:132-137, accepting: "records the acceptance as an `instruct` grant from the caller to the charter's signer. Its
    targets are `"own"`, meaning every ship the caller owns now or docks later. It has no expiry (`expires` is the
    maximum value) and stays until revoked. Its pin is that revision, and `follow` is stored." becomes "records the
    acceptance as a row of `charter_acceptances`, signed as a `charter-acceptance` record naming the caller, the
    charter's signer, the revision and `follow`. It covers every ship the caller owns now or docks later, and stays until
    the caller leaves or accepts again; a new acceptance ends the previous one with reason `superseded` (C18, C19)."
    "Accepting also materializes the policy's root clauses whose `owner` is the caller (section 2)." is removed (C2). "An
    admin who activates a charter has accepted it." becomes "A super admin who activates a charter has accepted it; no
    row records that (C17)."
11. A:143, the block header, becomes `=== Instructions: [<title>] · revision <n> · signed by …`, with `charter revision
    <n>` for a charter (C25).
12. A:165-166: the `grant_pins` table is not created; `charter_acceptances` takes its place (C18).
13. A:170: "`targets` may be `"own"` only on a charter acceptance" is removed: no grant has `"own"` targets (C18).
14. A:176-179, charter root clauses, and A:197, "for a charter root the charter revision must still be active and
    accepted": moved to step 5 (C2).
15. A:369-373, Plurality: the revision record's `policy` is the revision's stored policy, non-null exactly on a charter
    revision (C12). It gains: "It signs each charter acceptance as `{kind: "charter-acceptance", station, id, person_id,
    signer_id, layer_id, revision, follow, created}` and each end of one as `{kind: "charter-acceptance-revocation",
    station, acceptance, revoked, revoked_by, reason}` (C18)."

**The step 3 spec**

1. G2: "`policy` is `null` until step 4" becomes "`policy` is the revision's stored policy: the charter's full policy on
   a charter revision, `null` on every other (charter step 4 spec, C12)".
2. G3: "whose `kind` is one of `instructions-revision`, `grant`, `grant-revocation`" gains "`charter-acceptance`,
   `charter-acceptance-revocation`" (C18).
3. G4b: "a row in `revision_signatures`, or, from merge 3b, a row in `grants` whose `signature` is set" gains "or, from
   step 4, a row in `charter_acceptances` whose `signature` is set (`SELECT 1 FROM charter_acceptances WHERE
   signature!='' LIMIT 1`, so a row being signed in its own transaction doesn't count itself)". G12's startup signing
   of unsigned revocations gains unsigned acceptance revocations (C18).
4. G6: "Step 4 adds the owners whose ships a revision binds under an `instruct` grant." becomes "Step 4 serves the
   active charter revision's signature to every signed-in person, and any other charter revision's to its signer and
   to a person whose acceptance names it now or did before (C26)."
5. G7: "`_grant_policy(db)` returns spec A's no-charter defaults" becomes "returns the active charter's policy, with
   `grantees` flattened to the `people` list or None, or spec A's no-charter defaults when no charter is active (C16)".
6. G8 gains step 0, "while `max_depth` is 0: 400 'The station's charter allows no grants'", and step 3a, "with a
   grantee set in force, the grantee is listed in its `people` (400)" (C16).
7. G9, check 3: "and its grantee is in the grantee set" gains ", and a link a ship issued has every action in
   `delegable` (C16)".
8. G21: "how long: 1 day, 3 days, 7 days or 30 days, with 7 days chosen first" becomes "how long: those of 1, 3, 7 and
   30 days that fit within the policy's `max_expiry_hours`, plus `max_expiry_hours` itself when it is not one of them,
   with 7 days chosen first when it fits and the longest choice otherwise; the page reads the limit from
   `GET /api/grants/policy` (C16)".
9. G13 gains: "Charter acceptances are reconciled by person (charter step 4 spec, C27)." Every grant rule stays as it
   is.

The `grants` table and its readers are unchanged by step 4 except as items 5 to 7 say, and the grants page except as
item 8 says.

**The law** (a proposal for Andy's signature; Rio Grande drafts the text, C8)

1. Section 1, fourth bullet (law:28-31): "When the charter exists, merging, deploying and admitting new ships become
   agent work under its rules; an act it has no rule for waits for Andy. (D2, "Law only") Until then, nothing merges or
   deploys except under section 2, and only Andy admits: …" becomes "This layer is the station's charter. Merging,
   deploying and admitting new ships become agent work under its rules once a charter revision Andy signs holds those
   rules; an act it has no rule for waits for Andy. (D2, "Law only") Until a charter revision Andy signs gives merging
   and deploying rules of their own (spec B), section 2 is the charter's rule for merging and deploying, and nothing
   merges or deploys except under it. Only Andy admits: …" (the rest unchanged).
2. Section 2's heading (law:33): "Merging and deploying Superyak until the charter exists" becomes "Merging and
   deploying Superyak: the charter's rule until a charter revision Andy signs replaces it (spec B, D3)". Its bullets stay
   as they are (Q5 A).
3. The preamble (law:15-16): "Sections 1 to 6 are Andy's decisions as of 2026-10-12." gains "Sections 1 and 2 were
   reworded for the charter, which Andy signed on <the date he signs>." "binding because Andy activated this layer"
   becomes "binding because Andy signed this charter".
4. Andy's choice, asked before drafting (C9): the title "Station law for Andy's ships" becomes "Station charter", since
   it now binds the resident ships and accepting owners' ships too. Recommended either way: section 1 gains "Resident
   ships (Odo, Wormhole) have no owner; this charter is the only law that binds them, and their runs are read-only."
   Odo would otherwise read "your owner" with no owner to apply it to.

## Data

**Layer drafts.** Two keys join `FIELDS`. Both are stored only when set, so a note or an ordinary instructions draft
stores neither and a rolled-back station still reads it (`layers.py:48-49`).

- `charter`: a JSON boolean; stored only when `true`.
- `policy`: an object, allowed only with `charter: true`; `null` and absent both mean the defaults.
- A charter revision's snapshot holds `charter: true`, `audience_users: []` and the full policy.

**Policy, version 1.** Unknown keys at any level, and a value of the wrong type (a boolean is never a number; `3.0` is
not a whole number), are refused with 400 naming the path, such as `policy.delegation.max_depth`. The defaults are
filled first; then every bound and cross-check runs on the full policy.

| Path | Default | Allowed | Read in step 4 by |
| --- | --- | --- | --- |
| `version` | — | required in a given policy; must be 1 | — |
| `delegation.max_depth` | 3 | whole, 0–5 | validity (a chain has at most this many links, root included); making a grant (refused at 0) |
| `delegation.max_expiry_hours` | 720 | whole, 1–2,160 | making a grant (`hours`), validity (lifetime), `GET /api/grants/policy` |
| `delegation.agent_grant_default_hours` | 24, or `max_expiry_hours` if smaller | whole, 1–2,160, at most `max_expiry_hours` | nothing until step 5 |
| `delegation.delegable` | `["direct"]` | each of `["direct"]` at most once; `merge`, `deploy`, `admit` refused as reserved for spec B | validity, for links a ship issued (none until step 5) |
| `budgets.builds_per_ship_per_day` | 20 | whole, 0–500 | tickets (per-ship cap), the grant view, `GET /api/grants/policy` |
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

So a list holds at most 105 paths: four numbers, one action and 100 ids. Routes return each as `{path, before,
after}`: the two numbers; for a gained member `null` and the member; for `grantees` the old set and `null`. A `names`
map gives each listed person id's name. Prose changes are never widenings: they are what the diff shows.

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
person left) and `restored` (the reconcile, C27). A row holds an empty signature only inside the transaction that
inserts and signs it. The two signed records:

- `{kind: "charter-acceptance", station, id, person_id, signer_id, layer_id, revision, follow, created}`, with `follow`
  as `true` or `false`;
- `{kind: "charter-acceptance-revocation", station, acceptance, revoked, revoked_by, reason}`.

`identity.RECORD_KEYS` gains both kinds; `verify_record` is otherwise unchanged. `signatures.SIGNED_RECORDS` gains
`('charter_acceptances', "SELECT 1 FROM charter_acceptances WHERE signature!='' LIMIT 1")`; like the others, it counts
nothing on a database that lacks the table. An acceptance's short id is `#` and its first 4 characters, as a grant's is.

**The revision record** keeps G2's keys and kind; `policy` is the snapshot's (C12).

## Routes

Every route below takes a person session unless it says "ship key". On a person route a ship key gets 403, a missing
session 401 and a missing CSRF token on a write 403 (`current_user`, `app.py:88-97`); on a ship-key route a person gets
403 (`ship_member`). A body that is not a JSON object gets 400 (`app.py:72-82`). All of that comes first. After it, the
station refuses in the order listed; the first failure answers.

**`POST /api/layers`, `PUT /api/layers/{id}`** (drafts). As today (404 for a layer the caller doesn't own, 409 for a
stale `version`), then:
1. `charter` not a boolean: 400 "charter is true or false";
2. (save only) the layer has a charter revision and the draft isn't a charter: 409 "This layer is the station's
   charter and stays one; withdraw it to end it" (C6), whatever else the draft holds;
3. `charter: true` on a note: 400 "Only instructions can be a charter";
4. `charter: true` with ships in `audience_users`: 400 "A charter names no ships: it binds every ship whose owner
   accepts it";
5. `policy` without `charter: true`: 400 "A policy belongs only on a charter";
6. the policy fails the schema: 400 naming the path; `roots` and `breaker` say "reserved for step 5";
7. every other existing draft check, unchanged.

**`GET /api/layers/{id}/preview`.** As today. For a charter draft it adds `charter: {policy, widenings, narrowings,
names, binds}`: the full policy, the widened paths against the policy in force (C5), the narrowed paths (the same
paths where P is smaller or lacks a member), and the ships it would bind (`[{id, name, owner_name}]`, residents with
`owner_name: null`).

**`POST /api/layers/{id}/activate {version, space_versions?, confirm_widenings?}`.**
1. 404: no such layer, or not the caller's;
2. 409 "Draft changed; preview this version again";
3. 409: the layer has a charter revision and the draft isn't a charter (C6);
4. 400: the stored draft fails any other draft check above;
5. for a charter, in order:
   - 403 "Only a super admin can sign the station's charter" (C3);
   - 409 "Another charter is active; its owner must withdraw it first";
   - 400 "confirm_widenings is a list of paths" (not a list of at most 105 strings of at most 200 characters);
   - 409 "Confirm exactly these widenings: …", naming them (C13);
   - 409 "<ship> would have more than 10 instruction layers or 48,000 bytes of them", for any ship C23 checks;
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

**`GET /api/layers/{id}/revisions/{n}/signed`** (C26).
1. 404 for no such layer or revision, as G6;
2. the active charter revision: served to any signed-in person;
3. any other charter revision: served to the layer's owner, and to a person whose acceptance names it now or did
   before (a follower's acceptance names the revision its walk binds now too); 404 for anyone else;
4. any other revision: as G6, the owner only, 404 for anyone else.

The same 404 answers every refusal, so the route never says whether a revision exists.

**`GET /api/charter`** (4c). Never 404. Returns:

```
{"charter": null | {"layer_id", "revision", "title", "body", "policy", "names", "signer": {"id", "name"}, "created"},
 "signer": true | false,
 "acceptance": null | {"id", "short", "layer_id", "revision", "follow", "accepted"},
 "binding": null | {"layer_id", "revision", "title", "body", "policy"},
 "pending": null | {"revision", "widenings", "narrowings", "too_large": [ship names], "baseline": "defaults" | <revision>},
 "acceptances": [{"person": {"id", "name"}, "revision", "follow", "accepted"}]}
```

`binding` is the revision that binds the caller's ships now. `pending` is the active revision when it doesn't bind them,
with its widened and narrowed paths against the baseline (C20), and the caller's ships it would put over the caps.
A person sees only their own acceptance. `acceptances` lists the acceptances in force of the active charter for its
signer, and is empty for everyone else.

**`POST /api/charter/accept {layer_id, revision, follow, confirm_widenings}`** (4c).
1. a key other than these four: 400;
2. `layer_id` not a string, `revision` not a whole number, `follow` not a boolean, `confirm_widenings` not a list of at
   most 105 strings (absent is `[]`): 400;
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

**`POST /api/grants`** (4a). G8's order, with step 0 first: while `max_depth` is 0, 400 "The station's charter allows
no grants". Step 3a after step 3: a grantee not in the grantee set's `people` gets 400 "The station's charter doesn't
allow grants to this person" (C16). `GET /api/grants/people` lists only those people while a set is in force; its list
shape is unchanged.

**`GET /api/grants/policy`** (4a). `{max_depth, max_expiry_hours, builds_per_ship_per_day}` from the policy in force.
The grants form reads it (step 3 amendment 8).

**`POST /api/ships/me/drafts {title, body, charter?, policy?}`** (ship key). A key other than these four: 400; a ship
with no owner: 403; the rate limits: 429; then the draft checks above. A charter draft has an empty audience; any other
is addressed to the drafting ship, as today.

**`GET /api/ships/me/instructions`** (ship key). Each `layers` item gains `charter: true | false`. The answer gains
`charter: null | {layer_id, revision, binding, accepted}`: the active charter's revision, the revision binding this ship
(or `null`), and whether its owner signed or accepted it (always true for a resident).

**`GET /api/ships`** (4b). Each ship the caller owns, and each resident ship, gains `instructions: [{layer_id, revision,
title, charter}]`, its binding layers in order (C29). Other ships have no such field.

## Binding

For a ship S, computed when a ticket is issued or the instructions are fetched, as today:

1. The active charter is the one layer whose active revision is a charter revision, if any.
2. The charter pair for S:
   - S is a resident (no owner): the active charter's active revision, or none;
   - S's owner O owns the active charter: its active revision (C17);
   - otherwise, O's one acceptance in force A (4c), if any. If A's layer has no active revision, none (C15). If A pins,
     A's revision. If A follows, start at A's revision and step through the layer's existing revision rows in order,
     up to the active one. Move to the next row only when its number is exactly one more than the current one (no
     withdrawal in between), it has no widening against the current one, and it would put none of O's ships over the
     caps with O's other binding layers. Stop at the first row that fails (C21).
3. Then, unless S is a resident, O's own active non-charter instructions layers whose audience lists S, by
   `(created, layer_id)`, as today.

A ticket records the pairs in this order, and `_layers_for` renders them in the order recorded, never re-sorted
(`instructions.py:41` today). The caps check (C23) uses the same function, with the new revision active, for every ship
whose binding the activation changes. A layer that becomes a charter is counted once, as the charter pair: its old
revision no longer binds through the audience rule.

At most one charter binds a ship: one charter layer is active at a time, a withdrawn one binds nothing, and an owner
holds at most one acceptance in force (the partial unique index).

## Requirements

**4a: the station's charter**

- **R1.** A draft's `charter` and `policy` follow "Routes" and "Data", each refusal with its status and reason, in
  that order. A note or ordinary draft stores neither key.
- **R2.** A charter revision's snapshot holds the full policy with every default filled in, cross-checked after the
  filling; the draft keeps the policy as written. A missing policy and `{"version": 1}` give the same revision policy.
- **R3.** Only a super admin activates a charter revision. An admin who is not one gets 403, and nothing is written.
- **R4.** While one charter layer is active, activating a charter revision of another layer gets 409.
- **R5.** A layer with a charter revision can't be saved or activated as a non-charter: 409, before any other draft
  check.
- **R6.** A charter's activation needs `confirm_widenings` equal, as a set, to the widened paths against the policy in
  force: the active charter's, or the defaults (C5). Anything else gets 409 naming the paths. Up to 105 paths are
  accepted.
- **R7.** The widened paths are exactly those in "Data", sorted. A narrowing alone lists nothing, and so does a prose
  change.
- **R8.** Narrowing a charter gets 409 and writes nothing.
- **R9.** Withdrawing an active charter needs `confirm_widenings` equal to the paths that widen from its policy to the
  defaults. An empty body is `{}`.
- **R10.** `_grant_policy` returns the active charter revision's policy, flattened as today with `grantees` as the
  `people` list or None, or the defaults. Every reader goes through it, so a change takes effect at the next check, and
  a withdrawal restores the defaults. `GET /api/grants/policy` returns its `max_depth`, `max_expiry_hours` and
  `builds_per_ship_per_day`.
- **R11.** With a grantee set in force, a `direct` grant to a person not in `people` is refused at making (400) and is
  invalid at the next check, with step 3's reason "… is no longer allowed by the station's policy". While `max_depth`
  is 0, making any grant gets 400 "The station's charter allows no grants".
- **R12.** A link a ship issued is invalid when one of its actions is not in `delegable`. A browser root is never
  checked against `delegable`.
- **R13.** The revision record's `policy` is the snapshot's. Kind, keys and every existing signature are unchanged.
- **R14.** Binding follows "Binding" for residents and for the signer's ships; another owner's ship gets no charter pair
  before 4c. A withdrawn charter binds no ship.
- **R15.** A ticket's blocks render in the order its pairs were recorded.
- **R16.** The caps hold at a charter activation for every ship whose binding it changes (in 4a: the residents and the
  signer's ships), and an owner's own activation counts the charter. A layer converted to a charter is counted once.
  Each 409 names the ship.
- **R17.** A block header reads `=== Instructions: [<title>] · revision <n> · signed by …`, or `· charter revision <n>
  ·` for a charter, with brackets inside the title shown as parentheses.
- **R18.** A build ticket whose recorded pairs include a charter revision has a footer ending ` · charter r<n>`, n from
  the record. Read tickets keep an empty footer.
- **R19.** Any signed-in person reads the active charter revision's signature. Any other charter revision's signature
  goes only to its signer and to a person whose acceptance names it now or did before (a follower's names the revision
  its walk binds now too); anyone else gets 404. Other revisions stay owner-only.
- **R20.** `GET /api/ships/me/instructions` carries `layers[].charter` and `charter` as in "Routes".
  `superyak-agent status` prints each binding layer as `[<title>] · revision <n> · signed by <name>`, or `· charter
  revision <n> ·` for the charter, with C25's brackets, then one line: "Charter: none active", "Charter: revision N
  binds this ship", "Charter: revision N is pending for this ship's owner; revision M binds this ship", or "Charter:
  revision N is active; this ship's owner has not accepted it". With no `charter` field (an older station) it prints no
  charter line.
- **R21.** Ship drafts and `station_draft_instructions` take `charter` and `policy`. A charter draft has no audience. An
  older station's 400 reaches the tool as an error result.
- **R22.** The hook's short header (`_header`) brackets the title and says `charter revision N` for the charter. The
  conversion reaches a session as the changed-revision notice with the new block, and no "no longer apply" line.
- **R23.** peer/API.md (instruction layers, binding rule, block format, signed records, policy, `GET
  /api/grants/policy`, run tickets' footer, a Charter section) and agent/README.md (what binds a ship, status) say what
  step 4 does.

**4b: the signer's web views**

- **R24.** The editor shows "This is the station's charter" and a policy field (JSON; empty means the defaults) only to
  a super admin. Ticked, it hides the ship list and saves `audience_users: []`.
- **R25.** For a charter, "Sign" shows the line diff of title and body against the active revision (or "new"), the full
  policy, the ships it will bind, and one checkbox per widened path in words (before → after). The button stays
  disabled until every box is ticked. Each narrowed path is stated in words too, with its effect: for example, an empty
  grantee set means no one can receive a grant, and `max_depth` 0 means no grant is valid and none can be made.
- **R26.** Withdrawing a charter asks first, says which ships stop being bound, and shows one checkbox per widened path.
- **R27.** `GET /api/ships` gains the `instructions` field for the caller's own ships and resident ships only, and the
  Ships section shows them (title, revision, charter mark).
- **R28.** The grants form offers only durations within the policy in force, as step 3 amendment 8 says. Every title,
  name and body on these views is escaped.

**4c: acceptance by other owners**

- **R29.** An acceptance is a `charter_acceptances` row as "Data" gives it, signed as `charter-acceptance`; its end is
  signed as `charter-acceptance-revocation`; both verify. No grant route, validity walk, ticket, budget count or grant
  reconcile reads the table, and the `grants` table is unchanged. A station whose only signed record is an acceptance
  refuses to start without its identity (G4b, with "Data"'s query), and signs an unsigned acceptance revocation at
  startup.
- **R30.** `POST /api/charter/accept` refuses in "Routes"' order, is idempotent for the same revision and `follow`, and
  supersedes the previous acceptance in the same transaction. `POST /api/charter/leave` ends it. The signed route
  answers only the person and the signer.
- **R31.** A pinned owner stays at their revision through later ones. A follower moves as "Binding" says: over existing
  rows, never across a withdrawal, a widening or a revision too large for their ships.
- **R32.** `GET /api/charter` gives the shape in "Routes", with the baseline of C20. It never shows another person's
  acceptance, except to the active charter's signer, in `acceptances`.
- **R33.** The caps hold at acceptance for each of the caller's ships, and at activation for ships re-bound after a
  withdrawal (409). A follower's ships never cause a 409: the revision stops the follower instead.
- **R34.** The restore reconcile treats acceptances by person (C27): `charter_acceptances.id`, `.person_id`,
  `.revision`, `.follow`, `.revoked`, `.revoked_by` and `.revoke_reason` join `COMPARED`. It never adds a row. Its
  report lists each acceptance it ended or kept without a replaced file, and each person whose acceptance in the
  replaced file was lost (accepted only after the copy, or re-accepted after it), with the revision they had. Grants are
  reconciled exactly as G13 says.
- **R35.** The web has a Charter page (`#charter`, linked in the sidebar): the text and policy, the caller's acceptance,
  a pending revision with its diff against the binding one, one checkbox per widened path, any of the caller's ships it
  is too large for, and a choice between "Keep this revision until I accept another" (pin) and "Follow later revisions
  that don't widen the limits" (follow). It says an acceptance covers "all your ships, now and later". "Stop accepting"
  asks first, then leaves. The signer sees "You signed this charter; it binds your ships", and who has accepted it.

## Testing

Each test is named, written first, and seen failing first. Each names the wrong implementation it catches.

**Merge 4a**

1. Draft checks, as one table: `charter` as `1` or `"yes"`; `charter` on a note; a charter with a ship; a policy
   without `charter`; a nested unknown key; `roots`; `breaker`; `version` missing or 2; each bound one step outside
   (`max_depth` -1 and 6, `max_expiry_hours` 0 and 2,161, `agent_grant_default_hours` 25 with `max_expiry_hours` 24,
   `builds_per_ship_per_day` 501), `true` and `3.0` for a number; `delegable` with `merge`, `x` or `direct` twice; a
   grantee that is a ship, unknown or repeated; 101 grantees. Each 400 names the path. A policy of only
   `max_expiry_hours` 12 is accepted, and its revision holds `agent_grant_default_hours` 12. Catches: a validator that
   checks only top-level keys, takes a boolean as 1, allows a reserved name, or cross-checks before filling defaults.
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
   A revision that widens all four numbers and `delegable` and adds 100 ids lists 105 paths and signs with all 105
   confirmed. Catches: comparing with the draft or with the defaults on every revision; a cap below the schema's most.
6. A revision with twenty changed prose lines and one widened number is refused until that path is confirmed (spec A).
   Catches: confirming "any change" at once.
7. The law conversion: an instructions layer at revision 1 (two ships, no policy) becomes a charter in place.
   Activation needs no widening. With a failure injected after the revision is written (the signing raises), the
   activation rolls back and both ships are still bound by `(L, 1)`. Without it, both are bound by `(L, 2)` first;
   revision 2's record has kind `instructions-revision`, `audience_users: []` and the default policy, and verifies;
   revision 1's signature row is unchanged and its record still verifies. Catches: a baseline read from revision 1's
   missing policy; a write outside the activation's transaction; a record change that breaks old signatures.
8. Saving `charter: false` with the stored policy still in the draft, on a layer with a charter revision, gets 409, not
   the 400 for a policy without a charter; a draft edited by hand to drop the flag gets 409 at activation. Catches: a
   charter that silently becomes an ordinary layer, or a check order that answers 400 first.
9. Narrowing a charter gets 409 and writes no revision. Catches: a no-op revision that moves followers.
10. Withdrawing a charter with `max_depth` 2 needs `["delegation.max_depth"]` (409 without it); one with the default
    policy withdraws with an empty body. After withdrawal no ship is bound by it and the policy is the defaults.
    Catches: a withdrawal that widens limits silently.
11. The policy in force: with `max_expiry_hours` 48, a 49-hour grant is refused, an existing 72-hour grant is invalid
    at the next ticket, and `GET /api/grants/policy` says 48; withdrawing makes the grant valid again. With
    `builds_per_ship_per_day` 1, the second grant build of a ship reads. With `max_depth` 0, every grant is invalid and
    making one gets 400 "The station's charter allows no grants", with nothing signed. Catches: `_grant_policy` still
    returning the defaults, reading the draft instead of the active revision, or signing a grant invalid from birth.
12. With `people: [Jenn]`, a grant to Stanley gets 400, Stanley's existing grant is invalid at the next ticket, Jenn's
    stays valid, and `GET /api/grants/people` lists only Jenn, still as a list. Catches: testing membership in the
    object, not its list.
13. A hand-made child grant issued by a ship is valid under the defaults and invalid under `delegable: []`; a browser
    root stays valid under `delegable: []`. Catches: applying `delegable` to browser roots, or not at all.
14. Binding: after the conversion, the signer's ships have the charter first, then the signer's other layers by
    creation; Odo and Wormhole have the charter only; another owner's ship has none of it; after withdrawal, no ship has
    it. Replaces `test_a_resident_ship_has_no_instructions_in_this_step`. Catches: the charter reached through rule 2's
    empty audience, so lost.
15. A ticket whose owner layer was created before the charter renders the charter block first, in the recorded order.
    Catches: `_layers_for` re-sorting by `created`.
16. Caps: the signer's ship with 10 own layers: the charter's activation gets 409 naming it. A ship bound by the
    charter and 9 own layers: a tenth own layer gets 409. Converting a layer whose ships sit at exactly 10 layers
    succeeds, because the converted layer counts once. Catches: reusing `_check_instruction_caps`, which refuses an
    empty audience and skips other owners' ships; counting a converted layer as both its old and its new revision.
17. Footers: an owner build after the conversion ends ` · charter r2`; a grant build reads `Builder for Andy, via Jenn ·
    grant #a1b2 · charter r2`; a ticket issued before the conversion, fetched again after it, keeps its old footer; a
    read ticket has none. Catches: a footer computed from the charter now.
18. Headers: `=== Instructions: [Station law] · charter revision 2 · signed by Andy …` and `[House rules] · revision 1`;
    a title `a] · revision 9 · signed by Jenn [b` renders as `[a) · revision 9 · signed by Jenn (b]`. Catches:
    unbracketed titles, or brackets a title can close.
19. `/signed` (C26): the active charter revision for a participant who owns nothing; after Andy signs r3, r2 for Andy;
    r2 for a participant with no acceptance gets 404, the same answer as for a revision that doesn't exist; an ordinary
    revision still 404 for anyone but its owner; a ship key 403. 4c adds: r2 for Jenn, who accepted r2 and has since
    accepted r3, and for a follower whose walk stopped at r2. Catches: opening every past revision, or the active one to
    no one.
20. The ship route's `charter` field and the status output, against the fake station: titles bracketed, the charter's
    line `[Station law] · charter revision 2 · signed by Andy`, and the charter line in each of R20's four states
    (the pending one exists only on a 4c station, so here it is the fake station's; test 28 has it on the station);
    without the field, no charter line and no error. Catches: a status that fails on an older station, or shows titles
    unbracketed.
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
    ticked; with `max_depth` 0 the dialog says no grant will be valid or can be made. An admin who is not a super admin
    sees no charter box. Withdrawing asks and shows the boxes. `GET /api/ships` gives `instructions` for own ships and
    residents only, and the Ships section shows them. Under `max_expiry_hours` 48 the grants form offers 1 day and 48
    hours, with 1 day chosen; under 2,160 it offers 1, 3, 7 and 30 days and 2,160 hours. A title and a body written as
    HTML show as text. Catches: a sign button that ignores the boxes; a form that offers what the station refuses;
    unescaped titles.

**Merge 4c**

25. Jenn, who owns a ship, accepts revision 2 pinned: the row matches "Data", its `charter-acceptance` record verifies
    against the station's card and fails with one byte changed or a key added; her ship is bound by revision 2; a ship
    she docks later is bound too. Catches: an acceptance that covers only the ships owned when it was made.
26. Step 3's readers never see an acceptance, as one table, with Jenn's acceptance and Andy's `direct` grant to Jenn
    over Rio Grande present: `GET /api/grants` for Jenn, Andy and Stanley lists the grant only; the grant view,
    `_grant_validity`, `_grant_visible` and `_owns_a_target` answer as before; Andy's mention of Jenn's ship reads, and
    Jenn's mention of Rio Grande builds under the grant; the G13 reconcile, with and without a replaced file, ends no
    acceptance; the grants page renders the grant only. The lost identity: on a database whose only signed record is an
    acceptance (its `revision_signatures` rows deleted, no grants), removing `identity.json` makes `Store` and
    `serve --peer-tls`'s read-only check refuse; a database from before 4c (no `charter_acceptances` table) passes the
    read-only check and the reconcile without error. Catches: a step 3 reader that picks acceptances up; a lost-identity
    check that forgets the table or chokes on its absence.
27. Accept refusals in "Routes"' order, one row each; accepting the same revision twice gives one row; leaving with no
    acceptance gets 409; the signed route answers Jenn and Andy and gives Stanley 404. Catches: duplicate rows, or a
    later check answering first.
28. Pinned at r2, Andy signs r3 (prose): Jenn's ship stays at r2, `GET /api/charter` shows r3 pending with no
    widenings, and her ship's status line says "revision 3 is pending for this ship's owner; revision 2 binds this
    ship"; Jenn accepts r3: the r2 row ends `superseded`, signed, and the new row names r3. A direct insert of a second
    row in force for Jenn fails on the unique index. Catches: a pin that moves; two acceptances in force.
29. Follow (spec A): Jenn follows at r3, r4 widens, r5 changes prose: her ship stays at r3, and r5 is pending with r4's
    widening listed. Catches: comparing r5 with r4.
30. Follow steps (C21), two sequences. First: Jenn follows at r3, r4 narrows `max_depth` to 2, r5 sets it back to 3:
    her ship is at r4 and r5 is pending. Second: Jenn follows at r3, r4 changes prose, Andy withdraws (number 5 is
    skipped) and activates r6, prose only: her ship is at r4, r6 is pending, and no error comes from the missing r5.
    Catches: comparing only with the revision she accepted; a walk over numbers instead of rows; a follower carried
    across a withdrawal.
31. Baselines: a first acceptance lists widenings against the defaults; after Jenn leaves, her next acceptance does
    too, and her ship is unbound in between. Catches: a baseline kept from an ended acceptance.
32. Withdrawal with acceptances: no ship is bound, Jenn's acceptance stays in force; the same layer activated again binds
    her pinned revision. A second charter layer activated after the first was withdrawn binds Andy's ships and the
    residents, and not Jenn's until she accepts it. Catches: pinned text that outlives its charter; two charters at once.
33. Caps: Jenn's ship with 10 own layers: her acceptance gets 409 naming it. Jenn pins r2, Andy withdraws, Jenn
    activates layers up to 10 while unbound, and Andy's re-activation gets 409 naming her ship. Jenn follows with 47 KB
    of her own layers: Andy's larger next revision activates, her ship stays at the earlier one, and `GET /api/charter`
    shows it pending as too large for that ship. Catches: caps checked only for the signer's ships; re-bound ships left
    unchecked; one follower blocking every revision.
34. The reconcile: with a replaced file where Jenn re-accepted after the copy, the copy's acceptance stays and the
    report names her with the revision she had; where she left, it ends with reason `restored`, and the next start signs
    that end; where Stanley accepted only after the copy, no row is added and the report names him; with no usable
    replaced file, every acceptance stays and is listed; grants follow G13. Catches: ending acceptances row by row, which
    leaves a re-accepted owner unbound; a lost acceptance that passes in silence.
35. The oracle grows to spec A's 500 seeded cases with owners, signers, residents, pins, follows, withdrawals and
    owners' own layers near the caps, each revision a random policy; expected from "Binding" alone. Catches: any
    divergence in the follow walk.
36. `GET /api/charter` for: no charter; the signer, who sees Jenn in `acceptances`; a person with no ships; a pinned
    owner with a pending revision; an owner whose acceptance names a withdrawn layer while another charter is active
    (its `layer_id` tells them apart). No one else sees another person's acceptance. A ship key gets 403 on every
    charter route (spec A Testing 3, "accept a charter"). Catches: leaks, missing states and an ambiguous revision.
37. Browser: Jenn reads the charter, ticks each widened path, chooses follow and accepts; her acceptance shows on the
    Charter page; "Stop accepting" leaves after asking. Andy's Charter page lists her. Names and titles written as HTML
    show as text. Catches: an accept button that ignores the boxes.

## Review Focus

1. One widening hidden among prose changes, and a follower across r4 (widens), r5 (prose) and a withdrawal: tests 6,
   29, 30.
2. The law converted in place, at the caps, with a failure injected and without: tests 7, 16, 22.
3. An acceptance present while every step 3 grant reader runs, and as the only signed record when the identity is
   lost: test 26.
4. Withdrawing a charter, then re-activating it with a pinned owner and a follower near the caps: tests 10, 32, 33.
5. A restore after an owner re-accepted, left, or accepted only after the copy: test 34.

## Security

- Authority still starts with people. Only a super admin signs a charter revision; only its owner withdraws it; only
  a person accepts it, for their own ships. Ship keys get 403 on every route that changes the law.
- Instructions are the one unfenced channel, and the charter is the first layer that binds ships of people other than
  its signer. Each owner's consent is a signed acceptance naming the revision. A pinned text never moves without that
  owner; a follower stops at the first widening, at a revision too large for their ships, and at a withdrawal.
  Residents have no owner to consent; spec A binds them by the signer's act, and their tickets are always read-only.
- No limit grows without a checkbox: at activation, at withdrawal and at acceptance. A narrowing applies at the next
  check, and the signing dialog says what it does.
- An acceptance carries no authority to act. It is not a grant and lives outside the `grants` table, so no ticket,
  budget or validity walk can reach it, and its record kind can't pass as a grant's. It decides only which text binds an
  owner's ships.
- Titles are bracketed and can't hold brackets, so a title can't fake a header's revision or signer. A display name
  still can (C10).
- The station's key signs the policy with the text. As in step 3, a signature says the station recorded it, not that a
  person's own key signed it.
- A restore keeps each owner's law in place, never brings back a `direct` grant, and names every acceptance it couldn't
  keep (C27, G13).
- Every person can read the active charter and the people its grantee set names. A past revision reaches only its
  signer and the people who accepted it or are bound by it (C26). Owner layers stay private.

## Mixed versions

- **New station, older agents.** The station renders blocks, so older hooks, watchers and MCP servers carry the charter
  unchanged. The bracketed header changes the bytes, not the `[layer_id, revision]` pairs, so no spurious notice at
  4a's deploy. An older hook's short header (used only when the text doesn't fit) is unbracketed. An older `status`
  prints titles unbracketed and no charter line. Defiant runs old code; Codex sessions keep what they read until they
  restart.
- **New agent, older station.** `status` prints no charter line when the field is missing. The draft tool's `charter`
  gets the older station's 400 as an error result.
- **A station rolled back to before step 4.** It can still save a charter draft through `PUT`, since its `_draft`
  checks only the keys sent and the stored ones carry over, but it can't activate one (400 for the unknown key); such
  drafts bind nothing. Its `/signed` rebuilds charter revision records with `policy: null` (`signatures.py:94`), so they
  don't verify there. It never reads `charter_acceptances`, so acceptances bind nothing there; and its lost-identity
  check doesn't count them, so a station rolled back with a lost identity could take a new key over signed acceptances.
  An active charter revision has an empty audience, so an older station binds no ship with it: roll the conversion back
  first (Deploy).
- **The web app** comes from the station, so it always matches it.

## Deploy

Each merge goes under section 2: approved in the room, the Pi suites passing. Before each: back up `peer.sqlite3` with
SQLite's backup API. After each: restart the lighthouse and the door; for 4a also the rio-grande, odo and wormhole
watchers (the hook's header, status); then the live check below, and on a failed check revert, restart and announce.
Other machines get the agent changes when they pull and `make dock`.

**Live checks, with no person's login**

- **4a, before any charter.** Rio Grande's `superyak-agent status` on the Pi prints the law as `[Station law for Andy's
  ships] · revision 1 · signed by Andy` and "Charter: none active"; its next prompt prints no change notice.
- **The rehearsal (after 4a, and again with the reviewed text just before Andy signs).**
  - Copy the live database with SQLite's backup API, never `cp` (it runs in WAL mode), into a scratch directory. Create
    a throwaway identity there, as `station-restore-test` does, but don't run that command or its reconcile: grants and
    ship keys on the copy stay as they are live.
  - Open a throwaway store on the copy. As Andy's account, through store methods: save the law's draft with
    `charter: true`, `audience_users: []` and the reviewed text; preview it (no widenings; it binds Andy's four ships,
    odo and wormhole); activate it.
  - Check: each of the six ships is bound by the law's new revision first; Rio Grande's blocks start with the charter
    header; an owner ticket ends ` · charter rN`, for a message by Andy that mentions Rio Grande, made by a store call
    on the copy (never a post, so law section 7's "post only as yourself" isn't engaged); the new revision verifies
    against the throwaway card; revision 1's signature row is unchanged.
  - With Q3 B: list every grant on the copy that a narrowing makes invalid, so Andy knows before he signs.
  - Delete the copy.
- **4b.** The served `app.js` holds the charter box's label (`curl` the static file).
- **4c.** On a copy as above, a throwaway person with a throwaway ship accepts the active charter, if any; the ship's
  binding follows and Andy's ships are unchanged.

**The conversion: steps on the Pi**

1. 4a and 4b are live, and their checks passed. 4c may follow later.
2. Rio Grande asks Andy Q5, Q6 and the rename, one at a time (C9). Q4 is moot.
3. Rio Grande drafts the charter's text with `station_draft_instructions`, as an ordinary draft without `charter`
   (C28): the law's text with the lines in "Amendments to the law" and Andy's answers. A fresh reviewer checks every
   changed line against Andy's words and posts the verdict in the room, quoting the sha256 of the draft's title and of
   its body (UTF-8).
4. The rehearsal, with the reviewed text. Then Rio Grande asks Q3.
5. Back up the database.
6. Andy, in the web app: opens the law layer itself (c879…, not Rio Grande's draft, which he leaves unsigned), ticks
   "This is the station's charter", pastes the reviewed title and text from Rio Grande's draft (shown among his drafts
   as "drafted by Rio Grande"), sets the policy from his Q3 answer (empty for A), saves, opens "Sign", reads the diff
   against revision 1 and the six ships, and signs. The revision is 2 unless the layer changed before.
7. The live check:
   - on a fresh copy, the sha256 of the new revision's title and body equal the reviewed draft's. A mismatch is a
     failed check: Rio Grande tells Andy at once, no merge proceeds under the charter, and Andy signs a corrected
     revision pasted again from the reviewed draft;
   - Rio Grande's `superyak-agent status` lists `[<title>] · charter revision N · signed by Andy` first and "Charter:
     revision N binds this ship"; its next prompt shows the changed notice with the charter block and no "no longer
     apply" line;
   - on the same copy, Odo and Wormhole are bound by the charter revision, and its record, built from the copy with
     the station's peer id as `superyak-peer card` prints it, verifies against that card;
   - the next owner build on any of Andy's ships ends ` · charter rN`.
8. Rio Grande updates docs/station-law.md's reference copy and HANDOFF.md in one doc commit under section 2, and posts
   in the room.

**Rollback**

- **A merge before the conversion:** revert, restart, announce. Charter drafts and acceptance rows left behind bind
  nothing on an older station, and the `grants` table is as step 3 left it (Mixed versions).
- **The conversion: data first, then code.**
  1. Rio Grande drafts the plain law (revision 1's text) under a title different from the charter's, for example
     "Station law for Andy's ships (restored)"; Andy adds his other three ships and activates it. For a moment his
     ships are bound by both, with the same signer and the same rules.
  2. Andy withdraws the charter, confirming any widenings back to the defaults (none with Q3 A). Sessions read "no
     longer apply" under the charter's title, which the different title keeps from reading as the plain law's (survey
     risk 10). His ships are bound by the plain layer; Odo and Wormhole by nothing, as before step 4.
  3. Then revert code, if needed.

  This order never leaves Andy's ships without law. If the release's own withdrawal is broken, step 3 may come before
  step 2 once step 1 holds: an older station then binds Andy's ships by the plain layer and ignores the charter (its
  audience is empty), so only Odo and Wormhole lose it. Never revert while the charter is active and step 1 doesn't
  hold: an older station would bind Andy's ships with nothing. The plain law gets a new layer id, because c879… stays a
  charter (C6).
- **A restore from a copy taken before the conversion** brings the law back at revision 1, as an ordinary layer. The
  reconcile reports that its active revision differs (`backups.py:736-745`).

## Known limits

- In step 4 the policy's limits apply station-wide whether or not an owner accepted (spec A, A:109-110). An acceptance
  decides which text binds that owner's ships.
- The charter grants no authority: no roots until step 5 (C2).
- `breaker` is reserved; `agent_grant_default_hours`, `grantees.ships_of` and `delegable` have no effect until step 5.
  Under a restricted grantee set, no ship can be a grantee (C16).
- C3 names the role. A second super admin could sign a charter whenever none is active. Today Andy is the only one.
- A charter whose owner loses the super admin role stays active until they withdraw it. No one else can end it, and no
  other charter can be signed while it is active.
- The charter's text reaches the law layer by pasting in the editor. The sha256 check after signing catches a paste
  that differs from the reviewed draft.
- A follower stops at the first widening, at a revision too large for their ships, and at a withdrawal, even when a
  later revision would have suited them (C21).
- The signer's own layers, and a pinned owner's re-bound after a withdrawal, can block a charter revision through the
  caps; the 409 names the ship (C23).
- Without a usable replaced file, a restore keeps every acceptance (C27).
- Acceptances are not on the grants page; the Charter page shows the caller's own, and the signer sees who accepted.
- A person who never accepted can't read a past charter revision (C26).
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
- Any power of a super admin over another person's charter, such as withdrawing one whose signer lost the role: it would
  widen, so it is Andy's call. Also out: delivery between stations.

## Andy's choices

Asked one at a time, by Rio Grande (C9). None blocks this spec.

Before the text is drafted and reviewed:

- **Q5. D3.** Recommended: **A, unchanged**, with the wording in "Amendments to the law": section 2 stays as written
  and becomes the charter's merge rule until a charter revision Andy signs replaces it. B (for example Tardis as a
  reviewer) brings in a decision Andy has kept open (roadmap 3.2).
- **Q6. The law's pending revision 2** (section 7's watch line, draft layer 686487ab). Recommended: **A, fold it in**,
  under the same fresh review: one signature covers both. With B, Andy signs revision 2 first and the charter becomes
  revision 3.
- **The rename.** Whether the law becomes "Station charter" (Amendments to the law, item 4). Recommended: rename, since
  it will bind the residents and other owners' ships. The resident line is recommended either way.

At signing:

- **Q3. The first charter's limits.** Recommended: **A, spec A's defaults**, by leaving the policy empty: depth 3, 720
  hours, 24 hours, 20 builds per ship a day, `delegable` `direct`, unrestricted grantees. Nothing widens, so there is
  no checkbox, and no existing grant changes. With B, each widening is one checkbox, each narrowing applies to every
  grant at the next check, and the rehearsal lists the grants a narrowing makes invalid.
- **Q4. Roots.** Moot: step 4 has none (C2).

## Build order

Three merges, each with its own plan reviewed by a fresh reviewer agent and merged under section 2.

- **4a. The station's charter** (station and agent): `charter` and `policy`, the schema, the super admin and
  one-charter checks, widenings at activation and withdrawal, the narrowing refusal, the policy in force (grantee set,
  `delegable`, `max_depth` 0 at making, `GET /api/grants/policy`), the signed record's policy, binding for the signer
  and residents with the charter first and the order kept, caps at activation, headers, footers, `/signed` for charter
  revisions, the ship route's `charter` field and the status output, ship drafts and the tool, the hook's header, docs.
  R1-R23; tests 1-23. Value alone: the law can become the charter through the API.
- **4b. The signer's web views** (web, and `GET /api/ships`' field): the editor's charter box and policy, the signing
  dialog with its diff, checkboxes and narrowings in words, the withdrawal dialog, the Ships section, the grants form's
  durations. R24-R28; test 24. Value alone: Andy sees exactly what he signs. Andy can sign once 4b is live.
- **4c. Acceptance by other owners** (station and web): the `charter_acceptances` table and its two record kinds,
  `GET /api/charter`, `POST /api/charter/accept` and `/leave`, the signed route, pin and follow, caps at acceptance and
  for re-bound and following owners, the lost-identity check and backfill, the restore reconcile, the 500-case oracle,
  the Charter page. It changes no step 3 grant code (C18). R29-R35; tests 25-37. It has no user until a second person
  owns a ship, so it has its own merge and doesn't hold up the signature. Value alone: the first other owner can accept
  the law.

## Review map (revision 1's D8 review)

| Finding | Change | Where |
| --- | --- | --- |
| M1 past revisions readable by everyone | Narrowed, per Rio Grande's ruling: the active revision to every person; any other only to its signer and to people whose acceptance names it now or did before. A follower's acceptance counts as naming the revision its walk binds now, since `GET /api/charter` already gives them that text (step 3's G6 planned the same) | C26; Routes `/signed`; step 3 amendment 4; R19; test 19 (404 for a non-signer with no acceptance); Security; Known limits |
| S1 questions after the drafting | Q5, Q6 and the rename are asked before drafting and review; Q3 at signing | C9; Deploy conversion steps 2-4; Andy's choices |
| S2 status has no brackets | Status gains C25's brackets (chosen over correcting the expected line, so status and headers read alike) | C25; R20; test 20; Deploy live checks |
| S3 the pasted text is unchecked | sha256 of title and body, quoted in the verdict and compared on a copy after signing; a mismatch is a failed check | Deploy conversion steps 3 and 7; Known limits |
| S4 "until spec B" | The reviewer's wording: "until a charter revision Andy signs gives merging and deploying rules of their own (spec B)" | C8; Amendments to the law, items 1-2; Goal; Andy's choices Q5 |
| S5 re-bound ships unchecked | Every ship whose binding an activation changes is checked, re-bound ones included | C23; C15; Binding; spec A amendment 4; R16; R33; test 33 |
| S6 one follower blocks every revision | A revision too large for a follower's ships stops that follower, as a widening does; the 409 stays for the signer's ships, residents and re-bound pinned owners | C21; C23; Binding; `GET /api/charter` `too_large`; R31; R33; R35; test 33 |
| S7 the lost-identity test couldn't fail | Test on a database whose only signed record is an acceptance, through `Store` and `serve --peer-tls`; the `signature!=''` query given; a database from before 4c too | Data; step 3 amendment 3; R29; test 26 |
| S8 two silent restore cases | Both reported with the person and revision; the reconcile never adds rows | C27; R34; test 34 |
| S9 grants form durations, `max_depth` 0 at making | `GET /api/grants/policy`; the form offers only durations within the limit; making a grant refused while `max_depth` is 0 | C16; Routes; step 3 amendments 6 and 8; R10; R11; R28; tests 11 and 24 (the form is a browser test) |
| N1 gendered pronouns | "they" and "their" for generic people | C15; C17; C28; test 14; Known limits |
| N2 105 paths, cap 100 | Cap 105, derived from the schema | C13; Data; Routes; R6; test 5 |
| N3 `acceptance` without `layer_id` | `layer_id` added to `acceptance` and `binding` | Routes `GET /api/charter`; test 36 |
| N4 the rehearsal | No reconcile on the copy; the message is a store call, never a post; with Q3 B, the grants made invalid are listed | Deploy, the rehearsal; Andy's choices Q3 |
| N5 rollback order | Reverting with the charter active is safe once the plain layer holds; the plain layer takes a different title | Deploy, Rollback |
| N6 Rio Grande's charter draft could be signed | The text is drafted as an ordinary draft; step 6 says to open c879… itself | C28; Deploy conversion steps 3 and 6 |
| N7 defaults before the cross-check; check order | `agent_grant_default_hours` defaults to at most `max_expiry_hours`; cross-checks after filling; C6's 409 comes before the field checks | C6; C11; Data; Routes (drafts, activation); R1; R2; R5; tests 1 and 8 |
| N8 tests 7, 16, 20, 28 | 7 injects a failure; 16 converts at the caps; 20's pending state against the fake station, 28 on the station; 28 tests the index by a direct insert | Binding; R16; tests 7, 16, 20, 28 |
| N9 the preamble's date; the resident line | The preamble gains the date of the rewording; the resident line is recommended | Amendments to the law, items 3-4; Andy's choices |
| N10 a rolled-back station saves charter drafts | Says it can save but not activate one, and its `/signed` doesn't verify charter records | Mixed versions |
| N11 narrowings in words; which merge adds the field | The signing dialog states each narrowing's effect; `GET /api/ships`' field is 4b's | C29; C30; Routes; R25; R27; test 24; Build order |
| N12 skipped numbers; follow across a withdrawal | The walk goes over existing rows and stops at a withdrawal (a skipped number) | C21; C15; Binding; spec A amendment 7; R31; test 30 |
| N13 flattened `grantees` | `people` or None; ship grantees refused under a restricted set until step 5 | C16; step 3 amendment 5; R10; Known limits |
