# Spec A step 4, merge 4c: acceptance by other owners — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person who owns ships, or will, reads the station's charter, accepts its active revision pinned or
following later ones, and can stop accepting; their ships, now and docked later, are then bound by the revision that
acceptance binds, first among their instructions. Each acceptance and its end is a station-signed record of its own
kind, kept apart from grants; the caps hold at acceptance, at re-activation and at an owner's own activation; a
restore treats acceptances by person; and a Charter page shows it all.

**Architecture:** A new `acceptances.py` mixin owns the `charter_acceptances` table, the binding an acceptance gives
(`_accepted_pair` and the follow walk), `GET /api/charter`, accepting, leaving, and the caps checks 4c adds.
`signatures.py` signs the two new record kinds and serves their signed route, beside the grants'; `identity.RECORD_KEYS`
and `signatures.SIGNED_RECORDS` gain them. 4c reaches 4a's binding through one line in 4a's `_charter_pair`, and adds
one call to each of 4a's two activation paths and one clause each to 4a's `/signed` rule and status field. `backups.py`
reconciles acceptances by person. The web app gains a Charter page. No step 3 grant code changes (C18, R29).

**Tech Stack:** Python 3.13, FastAPI, SQLite (`sqlite3`, JSON1), `cryptography` (Ed25519), pytest with FastAPI's
`TestClient`, Playwright (`peer/tests/test_browser.py`), plain JavaScript and CSS. Tests run from `peer/` with
`uv run --locked python -m pytest -q <files>`; the whole peer suite is `uv run --locked python -m pytest -q -ra --tb=short`.
No agent file changes in 4c, so the agent suite isn't run.

**Spec:** `docs/superpowers/specs/2026-10-15-charter-step4-design.md`, revision 3 (approved under D8; merged into
charter-4c at `9e0aac8`). This plan builds merge 4c: R29-R35 and tests 25-37, and every part of the spec's Decisions
(C17-C23, C26, C27), Data, Routes, Binding, Security, Mixed versions, Deploy, Known limits and Amendments that concerns
acceptances, with the spec's own Review Focus items 1, 3, 4 and 5 (tests 26, 29, 30, 32, 33, 34). Spec A
(`docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`) as amended by the step 3 spec
(`docs/superpowers/specs/2026-10-15-grants-step3-design.md`) holds where it is silent.

**Base:** charter-4c at `9e0aac8` (main `25ca91e` plus the spec). 4c is built only after merge 4a (the station's
charter) has merged: first merge main, with 4a, into this branch, then reconcile the section below. When this plan was
written, Rio Grande was planning 4a and `git fetch https://github.com/zhang8128/superyak.git charter-4a` found no such
branch on GitHub (2026-10-15), so 4c's code sits behind a few named 4a behaviours, listed below with the signature this
plan assumes. Every edit below names its anchor text exactly, so an anchor that moved fails loudly instead of landing in
the wrong place.

**Dry run.** Every task was dry-run in a scratch clone of `9e0aac8` on top of Appendix A, a stand-in for the 4a
interfaces below, written for the dry run only and never committed. Each RED below is the one seen, each GREEN ran, and
each Step 5 mutation was applied alone and failed the test it names, except where a step says otherwise. The code blocks
are the dry run's own text: Appendix A and then every task in order reproduce its tree. At the end the peer suite ran
973 passed and 1 skipped, this plan's 32 new tests among them. On the real 4a, the counts in Steps 2 and
4 grow by 4a's own tests, and a RED message that 4a's code writes may read differently; each such place says so.

Tasks: 1 the table and its two signed records (R29: records, G4b, the backfill, the signed route); 2 a pinned acceptance
binds its owner's ships (R29, R31; C15, C19, C22); 3 reading, accepting and leaving (R30, R32; C17, C18, C20); 4 follow
(R31, C21); 5 caps at re-activation, at a follower's next revision and at an owner's own activation
(R33, C23); 6 past charter revisions for the people who accepted them (C26); 7 the restore reconcile by person (R34, C27); 8 the
500-step binding oracle (test 35); 9 the Charter page (R35); 10 API.md, the restore runbook and the whole suite.

## Interfaces 4c consumes from 4a (to reconcile with 4a's plan before building)

4c needs these 4a behaviours. Each row gives the name and signature this plan assumes, the spec section that defines
the behaviour, and where 4c uses it. Appendix A implements each one with the spec's semantics; it is the reference for
what a row means, not for how 4a writes it.

| # | 4a behaviour | Assumed name and signature | Spec | Used by |
| --- | --- | --- | --- | --- |
| I1 | The full no-charter policy | `charter.DEFAULT_POLICY: dict`, spec Data's JSON with every default | Data; C5, C11 | Tasks 3, 5 (`acceptances.py`) |
| I2 | Widened paths from a baseline policy to a policy, both full | `charter.widened_paths(baseline: dict, policy: dict) -> list[dict]`, items `{path, before, after}`, sorted by path | Data "Widened paths"; C13 | Tasks 3, 4, 5 |
| I3 | Narrowed paths, the same paths where the policy is smaller or lacks a member | `charter.narrowed_paths(baseline: dict, policy: dict) -> list[dict]`, same shape | Routes, preview | Task 3 (`pending.narrowings`) |
| I4 | `confirm_widenings`' shape check | `charter.confirm_paths(value) -> list[str]`: `None` gives `[]`; anything but a list of at most 105 strings of at most 200 characters raises `Problem(400, 'confirm_widenings is a list of paths')` | Routes, activation step 5 | Task 3 (accept step 2) |
| I5 | The exact-set check | `charter.require_confirmed(paths: list[str], widenings: list[dict]) -> None`: raises `Problem(409, 'Confirm exactly these widenings: …')` unless the paths equal the widened paths as a set, each once | C13; R6 | Task 3 (accept step 5) |
| I6 | The caps predicate and its refusal | `instructions.over_caps(layers: list[dict]) -> bool` (more than `MAX_LAYERS` layers, or more than `MAX_BYTES` of `render_blocks(layers, 'x' * 12)`); `instructions.CAPS_REFUSAL = '{ship} would have more than 10 instruction layers or 48,000 bytes of them'` | Routes, activation step 5; C23; R16 | Tasks 3, 5 |
| I7 | The layers at recorded pairs, in the recorded order | `Instructions._layers_for(db, pairs) -> list[dict]`, not re-sorted, each dict as `_binding_layers` returns it (so a charter block is measured as a ticket renders it) | Binding; R15 | Tasks 3, 5 |
| I8 | An owner's own layers for one ship | `Instructions._own_layers(db, ship: sqlite3.Row, replace: dict \| None = None) -> list[dict]`: the owner's own active non-charter instructions layers whose audience lists the ship, by `(created, layer_id)`; `replace` is today's `_binding_layers` `replace`, `{layer_id, snapshot, created, revision}` | Binding 3 | Tasks 3, 5 |
| I9 | The charter pair for a ship, and the binding built on it | `Instructions._charter_pair(db, ship: sqlite3.Row) -> tuple[str, int] \| None` (a resident, or a ship whose owner signed the active charter: its active revision; any other ship: `None` in 4a), and `Instructions._binding_layers(db, ship_id, replace=None)` = `_layers_for(db, [pair])` + `_own_layers(...)`, the one function tickets, `GET /api/ships/me/instructions`, `GET /api/ships` and every caps check read | Binding 2; C22 | Task 2 changes `_charter_pair`'s last case |
| I10 | `GET /api/ships/me/instructions`' `charter` field | `Instructions._charter_status(db, ship: sqlite3.Row) -> dict \| None`, `{layer_id, revision, binding, accepted}`, `accepted` true for a resident or the signer's ship in 4a | Routes, ship route; R20 | Task 2 adds the acceptance to `accepted` |
| I11 | The active charter | `Layers._active_charter(db) -> sqlite3.Row \| None`, the layers row (with at least `id`, `owner_id`, `active_revision`) whose active revision is a charter revision | Binding 1 | Tasks 2, 3, 5 |
| I12 | The charter activation path | in 4a's charter activation, the point after `require_confirmed` and before the new revision row is written | Routes, activation step 5, its last bullet; C23 | Task 5 adds `self._check_rebound_caps(db, key)` |
| I13 | The ordinary instructions activation path | 4a's activation of a non-charter instructions layer, right after its `self._check_instruction_caps(db, actor, key, snapshot)` | C23, its last sentence; Binding, its last paragraph | Task 5 adds `self._refuse_a_moved_charter(db, actor, key, snapshot)` |
| I14 | Who reads a non-owned charter revision's signature | `Signatures._may_read_charter_revision(db, actor, layer: sqlite3.Row, revision: int) -> bool`, true in 4a for the active revision; `revision_signed` asks it only for a charter revision and a caller who isn't the owner | C26; Routes `/signed` 2-3 | Task 6 adds the acceptance clause |
| I15 | Spec-defined data and routes, read directly | a charter revision's snapshot holds `charter: true`, `audience_users: []` and the full `policy`; `POST/PUT /api/layers` take `charter` and `policy`; `POST /api/layers/{id}/activate` takes `confirm_widenings`; `POST /api/layers/{id}/withdraw` takes `{confirm_widenings}` | Data; Routes | `acceptances.py` reads snapshots; every test helper uses these routes |
| I16 | The agent's charter line | `superyak_agent.station.charter_line(charter: dict \| None) -> str \| None`, R20's line from the ship route's field | R20 | Task 2's status test only |

**Reconciling.** Before Task 1, read 4a's plan and its merged code. For each row, find 4a's name: either rename the
uses this plan lists (the last column) or give 4a's module a one-line alias. Rows I12 to I14 are edits inside 4a's
functions; their anchors are 4a's code, shown here as Appendix A writes it. If 4a computes a row differently (say
`_charter_pair` takes `replace`), keep 4c's code behind the same name and adjust only the call. If 4a's `status` prints
the charter line inline rather than through a function (I16), Task 2's status test calls the function 4a's own test 20
calls, or runs `superyak-agent status` against the station as `test_ship_agent.py` runs the hook. Tests reach 4a only
through spec routes and I6 to I11 and I16, so reconciling renames, it doesn't redesign.

**Not from 4a.** 4b's signing dialog also has a line diff and widened paths in words (C30, R25). If 4b merged before
4c with helpers for both, Task 9 uses 4b's helpers in place of `lineDiff` and `wideningWords`; Task 9's tests read the
page, not the helpers, so they stay as they are.

## Rulings

Decisions this plan makes where the spec leaves a choice. A fresh reviewer checks each; Andy can veto any.

| # | Ruling | Why |
| --- | --- | --- |
| R1 | `peer/superyak_peer/acceptances.py` holds the `Acceptances` mixin and `ACCEPTANCE_SCHEMA`: rows, the binding an acceptance gives, `GET /api/charter`, accepting, leaving, and 4c's caps checks. Signing stays in `signatures.py`, beside the grants' (`_acceptance_record`, `_sign_acceptance`, `_acceptance_revocation_record`, `_sign_acceptance_revocation`, `_backfill_acceptance_revocation_signatures`, `acceptance_signed`); the reconcile in `backups.py`. | As 3b's R1: `signatures.py` owns the station's signatures and their routes. |
| R2 | An acceptance row is inserted with an empty `signature`, which `_sign_acceptance` fills from the stored row before the transaction commits; an end is signed the same way. | Spec Data ("a row holds an empty signature only inside the transaction that inserts and signs it"), and 3b's R2: one record builder serves signing and the signed route. |
| R3 | Acceptance ends get their own startup backfill, called beside the grants' in `Store.__init__`'s signing block. `_backfill_revocation_signatures` is not changed. | Step 3 amendment 3 asks for the backfill; C18 and R29 say 4c changes no step 3 grant code. |
| R4 | Accept's first four 400s have no words in the spec. This plan's: `An acceptance takes only layer_id, revision, follow and confirm_widenings`; `layer_id is the id of the charter layer`; `revision is a whole number`; `follow is true or false`. A bad `confirm_widenings` gets 4a's activation message (I4). | One message per check, so the order test can tell which answered (3b's R14). |
| R5 | "Already accepted with the same `follow`" is checked after steps 3 and 4 and before steps 5 and 6. | A retry of an acceptance that needed a widening carries the same `confirm_widenings`; by then the baseline is the accepted revision, so step 5 read first would refuse the retry with 409. R30's idempotence needs the retry to answer 200; it changes nothing either way. |
| R6 | Leaving takes `reason` as grants' revoke does: missing, null or blank is `left`; other keys are ignored. | The spec gives only the reason's 400. |
| R7 | `acceptances[].revision` is the revision the acceptance names, as `acceptance.revision` is the caller's. `charter.names` names the person ids of the active revision's grantee set and of the caller's binding revision's. | The spec's shape names the keys only. The binding revision is the caller's own text, and the active revision's people are visible to everyone (C26's cost). |
| R8 | The follow walk also stops before a revision that isn't a charter revision. | C6 makes it unreachable; a hand-edited database can't make the walk read a policy that isn't there. |
| R9 | `_too_large` answers for every caps question 4c asks (accept step 6, `pending.too_large`, the re-bound check): the person's ships, by name, that the revision with each ship's own layers puts over the caps. A 409 names the first. | C23: one rule, one function, as the spec's Binding says ("the caps check uses the same function"). |
| R10 | The re-bound check runs only when the layer has no active revision at activation, and checks each acceptance's own revision, pinned or following. | C23 and Binding: a follower re-bound after a withdrawal "starts its walk at a revision it can't stop before"; a layer active now binds no one again. |
| R11 | An owner's own activation that would change their charter pair, either way, gets 409 `<ship> would be bound by charter revision <after> instead of revision <before>`, naming the ship whose caps made the difference. It runs after 4a's caps check (I13), which already refuses a move back (the revision binding now, with the new layer, is over the caps); this check is what refuses a move forward, when shrinking an own layer would let a follower take a revision they haven't seen. | Binding: "if any pair differs, the activation gets 409 naming the ship". The spec gives no words. |
| R12 | The reconcile's report: `Charter acceptances ended, as the replaced file holds none in force for them: …`, `Charter acceptances kept: …`, `Charter acceptances lost: in the replaced file, not in this copy, and a restore never adds one: … Ask them to accept again on the Charter page.`, by username. A copy from before 4c (no table) is skipped as any step is, and every acceptance in force in the replaced file is listed as lost. No count joins "Taken back:". | C27 and Security ("names every acceptance it couldn't keep"). Ending an acceptance takes law away, not access. |
| R13 | Test 35 is a new 500-step test beside 4a's oracle (test 23), not a rewrite of it. | 4a owns test 23. Caps need layer sizes, which the 60-case oracle doesn't have. |
| R14 | The Charter page states the limits in words, shows the line diff, one checkbox per widened path, the ships a revision is too large for, and pin or follow; its button stays disabled until every box is ticked and while a ship is too large; one write at a time; "Stop accepting" asks in place, Cancel focused. Narrowings aren't listed: the limits list shows the new values. | R35; 3c's R17 and R18 for the ask and the one write. |
| R15 | Tests are split where their parts land: test 25 (Tasks 1, 2, 3), 26 (1, 3, 7, 9), 27 (1, 3), 28 (2, 3), 33 (3, 5); test 19's 4c addition is Task 6. | Each part is written with the code it tests. |
| R16 | Tests reach 4a only through spec routes and the names in I6 to I11 and I16; their helpers (`super_admin`, `new_charter`, `sign`, `withdraw`) are this plan's. | Reconciling with 4a renames nothing in the tests unless 4a changed a route the spec defines. |

## Global Constraints

- Spec values, verbatim:
  - `CREATE TABLE IF NOT EXISTS charter_acceptances(id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES users(id), signer_id TEXT NOT NULL REFERENCES users(id), layer_id TEXT NOT NULL REFERENCES layers(id), revision INTEGER NOT NULL, follow INTEGER NOT NULL, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);`
  - `CREATE UNIQUE INDEX IF NOT EXISTS charter_acceptances_in_force ON charter_acceptances(person_id) WHERE revoked IS NULL;`
  - Records: `{kind: "charter-acceptance", station, id, person_id, signer_id, layer_id, revision, follow, created}`, `follow` `true` or `false`; `{kind: "charter-acceptance-revocation", station, acceptance, revoked, revoked_by, reason}`. Reasons `superseded`, `left`, `restored`. A short id is `#` and the id's first 4 characters.
  - `signatures.SIGNED_RECORDS` gains `('charter_acceptances', "SELECT 1 FROM charter_acceptances WHERE signature!='' LIMIT 1")`; a database that lacks the table holds none.
  - Accept's order: 1 a key other than the four (400); 2 `layer_id` not a string, `revision` not a whole number, `follow` not a boolean, `confirm_widenings` not a list of at most 105 strings (400; absent is `[]`); 3 409 "The charter changed; read it again"; 4 409 "You signed this charter; it binds your ships already"; 5 409 "Confirm exactly these widenings: …"; 6 409 naming a ship over the caps. Leave: 400 for a reason that isn't one line of at most 200 characters; 409 "You have not accepted a charter".
  - `COMPARED` gains `charter_acceptances.id`, `.person_id`, `.revision`, `.follow`, `.revoked`, `.revoked_by`, `.revoke_reason`.
  - The page's words: "Keep this revision until I accept another" (pin), "Follow later revisions that don't widen the limits" (follow), "all your ships, now and later", "Stop accepting", "You signed this charter; it binds your ships".
- 4c changes no step 3 grant code (C18, R29): `grants.py`, `tickets.py`, the grant functions of `signatures.py`, the G13 functions of `backups.py` and the Grants page in `app.js` stay as they are. Task 10 checks the first two with `git diff`.
- Production SQL names its columns (`INSERT INTO charter_acceptances(id,person_id,...)`).
- No test, and no code path, runs a request inside `with store.transaction()`: the TestClient's request would wait on the same dispatch gate (Task 3's grant-reader test reads the lists before it opens one).
- Every test is named, written first and seen failing first; where a test guards behaviour that already holds, the step says so and Step 5's mutation shows it bites.
- Repo norms: the new module goes in both `only-include` lists of `peer/pyproject.toml`, the new test file in the sdist one.
- No pushes. No servers on ports 7435 or 7436 (the browser tests pick a free port). Nothing read under `~/.superyak`.
- The merge goes through section 2 of the station law: approved in the room, the Pi suites passing.

## Review Focus

Inputs no spec test names, most likely to bite a person first. Each is pinned by a test in its task.

1. A retried or double-clicked acceptance carries the `confirm_widenings` the first one needed: it must answer 200 with
   one row, never "Confirm exactly these widenings" against the baseline the first one just moved (Task 3,
   `test_accepting_refuses_in_the_spec_order_and_the_same_acceptance_twice_is_one_row`, the retry).
2. An owner whose acceptance names a withdrawn charter accepts the new one (a rollback signs a new layer, spec Deploy):
   compared with the defaults, and the old acceptance ends `superseded` in the same transaction, so the unique index
   holds (Task 3, `test_get_charter_shows_each_state_and_never_another_persons_acceptance`, its end).
3. A `revision` past SQLite's integers (`2 ** 70`): 409 "The charter changed; read it again", never a 500 (Task 3, the
   order test's row).
4. An owner whose ship is already at the caps opens the Charter page: it says which ship and why, and the button stays
   disabled even with every box ticked (Task 9,
   `test_a_revision_too_large_for_a_ship_says_which_and_cannot_be_accepted`).
5. Andy signs a new revision while an owner reads the page: her accept gets 409, and the page reads the charter again
   and shows the new revision waiting, nothing accepted (Task 9,
   `test_a_charter_signed_while_the_page_is_open_is_read_again_when_accepting`).

## Known limits (beyond the spec's)

- The follow walk runs at every binding computation (tickets, the ship route, `GET /api/ships`, `GET /api/charter`):
  each step renders the candidate revision with each of the owner's ships' own layers. A station holds a handful of
  revisions and ships.
- Which 409 answers an own activation that would move a follower back depends on 4a (R11): 4a's caps check names the
  ship with the caps message; were 4a to compute the pair with the new layer, R11's check would answer instead. Tests
  assert the status and the ship's name only.
- A pinned owner whose binding grows over the caps while bound (only a longer display name in a block header can do it)
  isn't checked at the signer's next revision, which doesn't change their binding (C23 checks only ships whose binding
  changes). No test can tell that rule from checking them, so Task 5 lists no mutation for it.
- The restore report names people by username, as the grants' lines do.
- Test 35's seed reaches each event its last assertion lists; "own refused: moved" occurs once in 500 steps.
- Task 9's RED takes about a minute and a half: three tests wait 30 s for the Charter link.

## File Structure

- Create `peer/superyak_peer/acceptances.py`: `ACCEPTANCE_SCHEMA`, the refusal messages, `acceptance_short`, and the
  `Acceptances` mixin (Tasks 1-6).
- Modify `peer/superyak_peer/identity.py` (`RECORD_KEYS`), `peer/superyak_peer/signatures.py` (`SIGNED_RECORDS`, the
  records, their signatures, backfill and signed route), `peer/superyak_peer/db.py` (the schema, the mixin, the backfill
  call), `peer/superyak_peer/app.py` (four routes) and `peer/pyproject.toml` (Task 1; app.py again in Task 3).
- Modify 4a's code at four points: `_charter_pair` and `_charter_status` (Task 2), the two activation paths (Task 5),
  `_may_read_charter_revision` (Task 6). With Appendix A these are in `instructions.py`, `layers.py` and `signatures.py`.
- Modify `peer/superyak_peer/backups.py`: `COMPARED`, the acceptances steps, the report (Task 7).
- Modify `peer/superyak_peer/static/app.js` and `app.css`: the Charter page (Task 9).
- Modify `peer/API.md` and `docs/station-restore.md` (Task 10).
- Create `peer/tests/test_acceptances.py` (Tasks 1-8). Modify `peer/tests/test_signatures.py` and
  `peer/tests/test_restore.py` (Task 1), `peer/tests/test_ship_agent.py` (Task 2), `peer/tests/test_browser.py`
  (Task 9).

## Spec coverage

| Spec item | Task(s) | Test(s) |
| --- | --- | --- |
| R29 records, both verify; G4b with Data's query; startup signing of ends | 1 | `test_an_acceptance_and_its_end_are_signed_records_of_their_own_kinds`, `test_a_station_whose_only_signed_record_is_an_acceptance_does_not_start_without_its_identity`, `test_the_lost_identity_check_reads_a_database_from_before_4c`, `test_startup_signs_each_unsigned_acceptance_end_once` |
| R29 no grant reader reads the table; `grants` unchanged | 3, 7, 9, 10 | `test_step_3s_grant_readers_never_see_an_acceptance`, the reconcile tests, `test_the_grants_page_lists_the_grant_and_never_the_acceptance`, Task 10's `git diff` |
| R30 accept's order, idempotence, supersede; leave; the signed route | 3, 1 | `test_accepting_refuses_in_the_spec_order_and_the_same_acceptance_twice_is_one_row`, `test_accepting_a_newer_revision_supersedes_the_old_one_in_one_transaction`, `test_an_acceptances_signed_record_goes_to_its_person_and_its_signer_only` |
| R31 pin; follow over rows, never across a withdrawal, a widening or a revision too large | 2, 4, 5 | `test_a_pin_stays_at_its_revision_through_later_ones`, the three follow tests, `test_a_revision_too_large_for_a_followers_ship_stops_the_follower_and_is_never_refused` |
| R32 `GET /api/charter`'s shape and baseline; no one else's acceptance | 3 | `test_get_charter_shows_each_state_and_never_another_persons_acceptance`, `test_a_first_acceptance_and_one_after_leaving_compare_with_the_defaults` |
| R33 caps at acceptance, at re-activation (pinned and following), a follower's next revision, an owner's own activation | 3, 5 | the order test's caps row; `test_a_charter_activated_again_checks_the_caps_of_every_owner_it_binds_again[False/True]`, the follower test, `test_an_owners_own_activation_never_moves_their_ships_to_another_charter_revision` |
| R34 reconcile by person, `COMPARED`, the report | 7 | the three reconcile tests |
| R35 the Charter page | 9 | `test_an_owner_accepts_the_charter_on_its_page_and_stops_accepting_after_the_ask` and the Review Focus tests |
| Test 25 | 1, 2, 3 | record; `test_a_pinned_acceptance_binds_every_ship_its_owner_has_and_docks_later`; the row through the route (supersede test) |
| Test 26 | 1, 3, 7, 9 | lost identity and a database from before 4c; grant readers and mentions; the reconcile, with and without a replaced file, and a copy from before 4c; the grants page |
| Test 27 | 3, 1 | the order test; the signed route test |
| Test 28 | 2, 3 | the pin test and `test_a_pinned_owners_ship_says_the_active_charter_revision_is_pending` (test_ship_agent.py); the supersede test |
| Test 29 | 4 | `test_a_follower_never_takes_a_widening_even_behind_a_prose_revision` |
| Test 30 | 4 | `test_a_follower_compares_each_revision_with_the_one_binding_them_then`, `test_a_follower_is_never_carried_across_a_withdrawal` |
| Test 31 | 3 | `test_a_first_acceptance_and_one_after_leaving_compare_with_the_defaults` |
| Test 32 | 2 | `test_a_withdrawn_charter_binds_no_one_and_binds_a_pin_again_when_activated_again` |
| Test 33 | 3, 5 | the order test's caps row; the three caps tests |
| Test 34 | 7 | `test_the_reconcile_treats_acceptances_by_person_and_never_adds_one`, `test_without_a_usable_replaced_file_the_reconcile_keeps_every_acceptance` |
| Test 35 | 8 | `test_charter_binding_matches_an_independent_reading_over_500_seeded_steps` |
| Test 36 | 3 | the `GET /api/charter` test, `test_a_ship_key_gets_403_on_every_charter_route` |
| Test 37 | 9 | the page test |
| Test 19's 4c part (R19, C26) | 6 | `test_a_past_charter_revision_goes_to_its_signer_and_to_people_whose_acceptance_names_it` |
| R20's pending state on the station | 2 | the test_ship_agent.py test |
| C17 (the signer accepts by signing) | 3 (step 4), 2 (signer's ships through I9) | the order test; the binding test |
| C18 (own table, own kinds, supersede, unique index) | 1, 3 | records; supersede test |
| C19 (binds while in force and its layer exists; never a grant) | 2, 3 | binding tests; grant readers |
| C20 (only the active revision; baseline) | 3 | order test; baseline test |
| C21 (the walk) | 4, 5, 8 | follow tests; caps test; oracle |
| C22 (binding order) | 2 | binding test (charter first, then own layers) |
| C23 (caps) | 3, 5, 8 | caps tests; oracle |
| C26 (who reads a past revision) | 6 | the `/signed` test |
| C27 (restore by person) | 7 | reconcile tests |
| Data (table, index, records, `SIGNED_RECORDS`, short id) | 1, 3 | Task 1's tests; the supersede test (`short`) |
| Routes: `GET /api/charter`, accept, leave, the acceptance's signed route, `/signed` step 3, the ship route's `accepted` | 3, 1, 6, 2 | as above |
| Binding 2's last case; "the caps check uses the same function" | 2, 4, 5 | as above |
| Security (ship keys 403; an acceptance carries no authority; a restore names what it couldn't keep) | 1, 3, 7, 9 | 403 tests; grant readers and mentions; the reconcile report |
| Mixed versions (a rolled-back station ignores the table; its lost-identity check doesn't count it) | 10 | documented in API.md; nothing to build |
| Deploy (4c's live check) | after the merge | "Deploy" below |
| Known limits (acceptances off the grants page; a follower stops; caps can block; restore without a replaced file) | 9, 4, 5, 7 | as above |
| Amendments: spec A 10, 12, 13, 15 and step 3 amendments 2, 3, 4, 9 | 1, 3, 6, 7, 10 | as above |

---

### Task 1: The acceptances table and its two signed records (R29, G4b, the backfill, the signed route)

**Files:**
- Create: `peer/superyak_peer/acceptances.py`
- Modify: `peer/superyak_peer/identity.py` (`RECORD_KEYS` and the comment above it, `:74-83`)
- Modify: `peer/superyak_peer/signatures.py` (`SIGNED_RECORDS`, `:16-19`; six methods after `grant_signed`, `:168-178`)
- Modify: `peer/superyak_peer/db.py` (an import, the `Store` bases `:50`, the schema `:64`, the signing block `:86-89`)
- Modify: `peer/superyak_peer/app.py` (one route after `grant_signed`, `:508-510`)
- Modify: `peer/pyproject.toml` (both `only-include` lists)
- Create: `peer/tests/test_acceptances.py`
- Modify: `peer/tests/test_signatures.py` (`test_each_record_kind_signs_and_verifies_with_exactly_its_keys`, `:77-89`),
  `peer/tests/test_restore.py` (`RECONCILED_TABLES`, `:1387-1391`)

**Interfaces:**
- Consumes: `Signatures._station_identity(db)`, `refuse_a_lost_identity_before_the_store`, `holds_signed_records` (3b);
  test helpers `docked`, `ship_client` (`test_instructions.py`), `card_of`, `raw_sign`, `run_cli`
  (`test_signatures.py`). Nothing from 4a.
- Produces:
  - `ACCEPTANCE_SCHEMA` (the spec's table and index); `Acceptances._insert_acceptance(db, person_id, signer_id,
    layer_id, revision, follow) -> str` (the id; stored and signed in the caller's transaction);
    `Acceptances._end_acceptance(db, acceptance_id, by, reason) -> None` (ended and signed in the caller's transaction).
  - `Signatures._acceptance_record(db, acceptance_id) -> dict | None`, `_sign_acceptance(db, acceptance_id)`,
    `_acceptance_revocation_record(db, acceptance_id) -> dict | None`, `_sign_acceptance_revocation(db, acceptance_id)`,
    `_backfill_acceptance_revocation_signatures()`, `acceptance_signed(actor, acceptance_id) -> dict`.
  - `GET /api/charter/acceptances/{id}/signed`.
  - Test helpers in `test_acceptances.py`: `by_hand(store, person, signer, layer_id, revision, follow=False) -> str`,
    `end_by_hand(store, acceptance_id, by, reason='left')`, `acceptance_row(store, acceptance_id) -> dict`,
    `records(store, acceptance_id) -> (dict, dict | None)`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_acceptances.py`:

```python
"""Charter acceptances (charter step 4, merge 4c: R29-R35 and tests 25-37 of
docs/superpowers/specs/2026-10-15-charter-step4-design.md)."""
import base64
import pytest
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_record
from test_instructions import docked, ship_client
from test_signatures import card_of, raw_sign, run_cli


def by_hand(store, person, signer, layer_id, revision, follow=False):
    """An acceptance stored and signed by the helper POST /api/charter/accept uses once its checks pass: its id."""
    with store.transaction() as db:
        return store._insert_acceptance(db, person['id'], signer['id'], layer_id, revision, follow)


def end_by_hand(store, acceptance_id, by, reason='left'):
    with store.transaction() as db:
        store._end_acceptance(db, acceptance_id, by and by['id'], reason)


def acceptance_row(store, acceptance_id):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM charter_acceptances WHERE id=?', (acceptance_id,)).fetchone())


def records(store, acceptance_id):
    """(the acceptance's record, its end's record or None), as signatures.py builds them from the row."""
    with store.transaction() as db:
        return store._acceptance_record(db, acceptance_id), store._acceptance_revocation_record(db, acceptance_id)


def test_an_acceptance_and_its_end_are_signed_records_of_their_own_kinds(env, tmp_path):
    """R29, test 25's record: the row's signature verifies against the station's card, as a charter-acceptance with
    exactly its keys and `follow` a JSON boolean; one changed value, a key added or removed, another station, or a
    flipped byte fails. Its end is a charter-acceptance-revocation that verifies too, and neither signature passes for
    the other record."""
    app, clients, users, clock = env
    store = app.state.store
    andy, jenn = users[0], users[1]
    law = store.create_layer(andy['id'], {'title': 'Station law'})  # any layer row: the record names its id only
    key = by_hand(store, jenn, andy, law['id'], 2)
    identity = store._station_identity()
    card, (record, ended) = card_of(identity), records(store, key)
    row = acceptance_row(store, key)
    assert set(record) == RECORD_KEYS['charter-acceptance'] and ended is None
    assert record == {'kind': 'charter-acceptance', 'station': identity.peer_id, 'id': key, 'person_id': jenn['id'],
                      'signer_id': andy['id'], 'layer_id': law['id'], 'revision': 2, 'follow': False,
                      'created': 1000000.0}
    assert (row['follow'], row['revoked'], row['revocation_signature']) == (0, None, None)
    assert verify_record(card, record, row['signature'])
    assert not verify_record(card, {**record, 'revision': 3}, row['signature'])  # one changed value
    assert not verify_record(card, {**record, 'follow': 0}, row['signature'])  # 0 is not false in canonical JSON
    flipped = bytearray(base64.b64decode(row['signature']))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())
    added = {**record, 'targets': 'own'}
    assert not verify_record(card, added, raw_sign(identity, added))  # spec A's grant shape doesn't pass
    missing = {name: value for name, value in record.items() if name != 'follow'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))
    clock[0] += 60
    end_by_hand(store, key, jenn)
    record, ended = records(store, key)
    row = acceptance_row(store, key)
    assert set(ended) == RECORD_KEYS['charter-acceptance-revocation']
    assert ended == {'kind': 'charter-acceptance-revocation', 'station': identity.peer_id, 'acceptance': key,
                     'revoked': 1000060.0, 'revoked_by': jenn['id'], 'reason': 'left'}
    assert verify_record(card, ended, row['revocation_signature'])
    assert verify_record(card, record, row['signature'])  # the acceptance's own signature still verifies
    assert not verify_record(card, record, row['revocation_signature']) and not verify_record(card, ended, row['signature'])
    following = by_hand(store, jenn, andy, law['id'], 3, follow=True)
    assert records(store, following)[0]['follow'] is True and acceptance_row(store, following)['follow'] == 1


def test_an_acceptance_whose_signing_fails_is_not_stored(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    law = store.create_layer(users[0]['id'], {'title': 'Station law'})

    def refuse(self, record):
        raise ValueError('no key')

    monkeypatch.setattr(PeerIdentity, 'sign_record', refuse)
    with pytest.raises(ValueError):
        by_hand(store, users[1], users[0], law['id'], 1)
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM charter_acceptances').fetchone()[0] == 0  # signed in its insert, or not at all


def test_a_station_whose_only_signed_record_is_an_acceptance_does_not_start_without_its_identity(tmp_path, capsys, monkeypatch):
    """R29, test 26's lost identity (G4b with spec Data's query): a new station's first acceptance creates the identity
    (the row being signed doesn't count itself); with every revision signature deleted and no grants, the acceptance
    alone makes Store, the read-only check and `serve --peer-tls` refuse once identity.json is gone."""
    import uvicorn
    from superyak_peer.db import Store
    from superyak_peer.signatures import refuse_a_lost_identity_before_the_store
    store = Store(tmp_path / 'station')
    andy, jenn = store.create_user('andy', 'Andy', 'long-password-andy'), store.create_user('jenn', 'Jenn', 'long-password-jenn')
    ship, _ = docked(store, andy['id'], 'serenity')
    law = store.create_layer(andy['id'], {'kind': 'instructions', 'title': 'Station law', 'body': 'Be kind.', 'audience_users': [ship['id']]})
    assert not (store.data_dir / 'identity.json').exists()
    key = by_hand(store, jenn, andy, law['id'], 1)  # the station's first signature
    assert verify_record(card_of(PeerIdentity.load_or_create(store.data_dir)), records(store, key)[0], acceptance_row(store, key)['signature'])
    store.activate_layer(andy['id'], law['id'], law['version'])
    with store.transaction() as db:
        db.execute('DELETE FROM revision_signatures')
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0  # the acceptance is the only signed record
    (store.data_dir / 'identity.json').unlink()
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)
    with pytest.raises(ValueError, match='identity.json'):
        refuse_a_lost_identity_before_the_store(store.data_dir)
    served = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: served.append(args))
    code, out, err = run_cli(capsys, 'serve', '--data-dir', store.data_dir, '--peer-tls')
    assert code == 1 and 'identity.json' in err and served == []
    assert not (store.data_dir / 'identity.json').exists()


def test_the_lost_identity_check_reads_a_database_from_before_4c(tmp_path):
    """Test 26: a database with step 3's tables and no charter_acceptances table holds no acceptance: the read-only check
    passes, and changes nothing."""
    import sqlite3
    from contextlib import closing
    from superyak_peer.signatures import refuse_a_lost_identity_before_the_store
    old = tmp_path / 'old'
    old.mkdir(mode=0o700)
    with closing(sqlite3.connect(old / 'peer.sqlite3')) as db:
        db.execute('CREATE TABLE revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL)')
        db.execute("CREATE TABLE grants(id TEXT PRIMARY KEY, signature TEXT NOT NULL)")
        db.commit()
    before = (old / 'peer.sqlite3').read_bytes()
    refuse_a_lost_identity_before_the_store(old)
    assert (old / 'peer.sqlite3').read_bytes() == before and sorted(p.name for p in old.iterdir()) == ['peer.sqlite3']


def test_startup_signs_each_unsigned_acceptance_end_once(env, monkeypatch):
    """R29: an end the restore reconcile wrote has no signature (it holds no key); the next signing start signs it once,
    a store opened without signing doesn't (G4a), and a second start signs nothing."""
    app, clients, users, clock = env
    store = app.state.store
    law = store.create_layer(users[0]['id'], {'title': 'Station law'})
    ended = by_hand(store, users[1], users[0], law['id'], 1)
    end_by_hand(store, ended, None, 'restored')
    kept = by_hand(store, users[1], users[0], law['id'], 2)
    with store.transaction() as db:  # as the restore reconcile leaves an end (C27)
        db.execute('UPDATE charter_acceptances SET revocation_signature=NULL WHERE id=?', (ended,))
    from superyak_peer.db import Store
    assert acceptance_row(Store(store.data_dir, signing=False), ended)['revocation_signature'] is None
    restarted = Store(store.data_dir)
    signature = acceptance_row(restarted, ended)['revocation_signature']
    assert acceptance_row(restarted, kept)['revocation_signature'] is None  # nothing to sign while it is in force
    assert verify_record(card_of(restarted._station_identity()), records(restarted, ended)[1], signature)
    signed, real = [], PeerIdentity.sign_record
    monkeypatch.setattr(PeerIdentity, 'sign_record', lambda self, record: signed.append(record) or real(self, record))
    Store(store.data_dir)
    assert signed == [] and acceptance_row(restarted, ended)['revocation_signature'] == signature


def test_an_acceptances_signed_record_goes_to_its_person_and_its_signer_only(env):
    """R30's signed route (test 27): {station, record, signature} for the acceptance's person and its signer, plus
    revocation once it ended; anyone else, an admin included, and an unknown id get 404; a ship key gets 403."""
    app, clients, users, clock = env
    store = app.state.store
    andy, jenn = users[0], users[1]
    ship, key = docked(store, andy['id'], 'serenity')
    law = store.create_layer(andy['id'], {'title': 'Station law'})
    accepted = by_hand(store, jenn, andy, law['id'], 1)
    card = card_of(store._station_identity())
    path = f'/api/charter/acceptances/{accepted}/signed'
    for client in (clients[1], clients[0]):
        answer = client.get(path)
        assert answer.status_code == 200, answer.text
        assert set(answer.json()) == {'station', 'record', 'signature'} and answer.json()['record']['id'] == accepted
        assert verify_record(card, answer.json()['record'], answer.json()['signature'])
    for client, target in ((clients[2], accepted), (clients[3], accepted), (clients[1], 'no-such-acceptance')):
        assert client.get(f'/api/charter/acceptances/{target}/signed').status_code == 404
    assert ship_client(app, key).get(path).status_code == 403
    end_by_hand(store, accepted, jenn)
    answer = clients[0].get(path).json()
    assert set(answer['revocation']) == {'record', 'signature'} and answer['revocation']['record']['reason'] == 'left'
    assert verify_record(card, answer['revocation']['record'], answer['revocation']['signature'])
```

In `peer/tests/test_signatures.py`, replace

```python
    assert set(RECORD_KEYS) == {'instructions-revision', 'grant', 'grant-revocation'}
```

with

```python
    assert set(RECORD_KEYS) == {'instructions-revision', 'grant', 'grant-revocation', 'charter-acceptance',
                                'charter-acceptance-revocation'}
```

and, in the same test, replace

```python
                                    'charter_revision', 'follow', 'created'}
```

with

```python
                                    'charter_revision', 'follow', 'created'}
    assert RECORD_KEYS['charter-acceptance'] == {'kind', 'station', 'id', 'person_id', 'signer_id', 'layer_id',
                                                 'revision', 'follow', 'created'}
    assert RECORD_KEYS['charter-acceptance-revocation'] == {'kind', 'station', 'acceptance', 'revoked', 'revoked_by',
                                                            'reason'}
```

`test_the_lost_identity_check_reads_a_database_from_before_4c` passes before this task: 3b's `holds_signed_records`
already skips a table the database lacks. It guards that skip, which `SIGNED_RECORDS`' new entry relies on, and Step 5's
mutation shows it bites.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_signatures.py tests/test_restore.py`
Expected: `6 failed, 84 passed` on Appendix A (more passed on the real 4a). Five tests in `test_acceptances.py` fail with
`AttributeError: 'Store' object has no attribute '_insert_acceptance'`; `test_each_record_kind_signs_and_verifies_with_exactly_its_keys`
fails with `Extra items in the right set: 'charter-acceptance' 'charter-acceptance-revocation'`. The before-4c test
passes (see above).

- [ ] **Step 3: Write the implementation**

Create `peer/superyak_peer/acceptances.py`:

```python
"""Charter acceptances (charter step 4, merge 4c; docs/superpowers/specs/2026-10-15-charter-step4-design.md, C17-C23,
C26 and C27): a person who owns ships accepts the station's charter, pinned to its revision or following later ones,
and their ships are bound by the revision that acceptance names. An acceptance is a row of its own table, never a
grant (C18): no grant route, validity walk, ticket, budget or grant reconcile reads it. The station's signatures over
acceptances and their ends live in signatures.py, beside the revisions' and the grants'."""
from .common import uid

ACCEPTANCE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS charter_acceptances(id TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES users(id), signer_id TEXT NOT NULL REFERENCES users(id), layer_id TEXT NOT NULL REFERENCES layers(id), revision INTEGER NOT NULL, follow INTEGER NOT NULL, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS charter_acceptances_in_force ON charter_acceptances(person_id) WHERE revoked IS NULL;
'''


class Acceptances:
    def _insert_acceptance(self, db, person_id, signer_id, layer_id, revision, follow):
        """One acceptance, stored and signed in the caller's transaction; the caller has checked everything. The row
        holds an empty signature only until _sign_acceptance fills it, in this transaction (spec Data). Its id."""
        key = uid()
        db.execute('INSERT INTO charter_acceptances(id,person_id,signer_id,layer_id,revision,follow,created,signature) '
                   "VALUES(?,?,?,?,?,?,?,'')", (key, person_id, signer_id, layer_id, revision, int(follow), self.clock()))
        self._sign_acceptance(db, key)
        return key

    def _end_acceptance(self, db, acceptance_id, by, reason):
        """Ends an acceptance in force (`superseded`, `left` or the reason given) and signs the end, in the caller's
        transaction. Rows never change otherwise (spec Data)."""
        db.execute('UPDATE charter_acceptances SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                   (self.clock(), by, reason, acceptance_id))
        self._sign_acceptance_revocation(db, acceptance_id)
```

In `peer/superyak_peer/identity.py`, replace

```python
# Spec A step 3 (G3, G12): a signed record has exactly its kind's keys and names its station, so no record passes
# as another kind, as a federation envelope (which has no record kind), or as another station's.
```

with

```python
# Spec A step 3 (G3, G12) and charter step 4 (C18): a signed record has exactly its kind's keys and names its station,
# so no record passes as another kind (an acceptance never as a grant), as a federation envelope (which has no record
# kind), or as another station's.
```

and replace

```python
    'grant-revocation': frozenset({'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}),
}
```

with

```python
    'grant-revocation': frozenset({'kind', 'station', 'grant', 'revoked', 'revoked_by', 'reason'}),
    'charter-acceptance': frozenset({'kind', 'station', 'id', 'person_id', 'signer_id', 'layer_id', 'revision', 'follow',
                                     'created'}),
    'charter-acceptance-revocation': frozenset({'kind', 'station', 'acceptance', 'revoked', 'revoked_by', 'reason'}),
}
```

In `peer/superyak_peer/signatures.py`, replace

```python
                  ('grants', "SELECT 1 FROM grants WHERE signature!='' LIMIT 1"))
```

with

```python
                  ('grants', "SELECT 1 FROM grants WHERE signature!='' LIMIT 1"),
                  # charter 4c (spec Data): an acceptance's row is signed in its own insert's transaction, as a grant's is
                  ('charter_acceptances', "SELECT 1 FROM charter_acceptances WHERE signature!='' LIMIT 1"))
```

and append to the `Signatures` class, after `grant_signed` (the file's last method), with a blank line before:

```python
    def _acceptance_record(self, db, acceptance_id):
        """Charter 4c (spec Data, C18): an acceptance's record, with exactly RECORD_KEYS['charter-acceptance'], from its
        stored row; `follow` is a JSON boolean. None for no such row."""
        row = db.execute('SELECT * FROM charter_acceptances WHERE id=?', (acceptance_id,)).fetchone()
        if row is None:
            return None
        return {'kind': 'charter-acceptance', 'station': self._station_identity(db).peer_id, 'id': row['id'],
                'person_id': row['person_id'], 'signer_id': row['signer_id'], 'layer_id': row['layer_id'],
                'revision': row['revision'], 'follow': bool(row['follow']), 'created': row['created']}

    def _sign_acceptance(self, db, acceptance_id):
        """In the transaction that inserts the acceptance, from the stored row acceptance_signed serves."""
        db.execute('UPDATE charter_acceptances SET signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._acceptance_record(db, acceptance_id)), acceptance_id))

    def _acceptance_revocation_record(self, db, acceptance_id):
        """The record of an acceptance's end, with exactly RECORD_KEYS['charter-acceptance-revocation']; None while it
        is in force."""
        row = db.execute('SELECT id, revoked, revoked_by, revoke_reason FROM charter_acceptances WHERE id=?',
                         (acceptance_id,)).fetchone()
        if row is None or row['revoked'] is None:
            return None
        return {'kind': 'charter-acceptance-revocation', 'station': self._station_identity(db).peer_id,
                'acceptance': row['id'], 'revoked': row['revoked'], 'revoked_by': row['revoked_by'],
                'reason': row['revoke_reason']}

    def _sign_acceptance_revocation(self, db, acceptance_id):
        """In the transaction that ends the acceptance, or at the next start for an end the restore reconcile wrote."""
        db.execute('UPDATE charter_acceptances SET revocation_signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._acceptance_revocation_record(db, acceptance_id)),
                    acceptance_id))

    def _backfill_acceptance_revocation_signatures(self):
        """At every signing start, each acceptance's end without a signature is signed once (spec step 3 amendment 3).
        Only the restore reconcile writes one (C27). With none to sign, the identity is never touched (G4)."""
        with self.transaction() as db:
            for row in db.execute('SELECT id FROM charter_acceptances WHERE revoked IS NOT NULL AND '
                                  'revocation_signature IS NULL ORDER BY id').fetchall():
                self._sign_acceptance_revocation(db, row['id'])

    def acceptance_signed(self, actor, acceptance_id):
        """GET /api/charter/acceptances/{id}/signed: {station, record, signature}, plus revocation: {record, signature}
        once it ended, for the acceptance's person and its signer; anyone else, and an unknown id, gets 404."""
        with self.transaction() as db:
            row = db.execute('SELECT * FROM charter_acceptances WHERE id=?', (acceptance_id,)).fetchone()
            if row is None or actor not in (row['person_id'], row['signer_id']):
                raise Problem(404, 'Not found')
            signed = {'station': self._station_identity(db).peer_id, 'record': self._acceptance_record(db, row['id']),
                      'signature': row['signature']}
            if row['revoked'] is not None:
                signed['revocation'] = {'record': self._acceptance_revocation_record(db, row['id']),
                                        'signature': row['revocation_signature']}
            return signed
```

(`grant_signed` also ends with `return signed`: the block above goes after it, so the file ends with `acceptance_signed`.)

In `peer/superyak_peer/db.py`, after `from .grants import Grants, GRANT_SCHEMA` add

```python
from .acceptances import Acceptances, ACCEPTANCE_SCHEMA
```

then add `, Acceptances` after `Grants` at the end of the `class Store(...)` bases, and `+ ACCEPTANCE_SCHEMA` after
`+ GRANT_SCHEMA` in the `db.executescript(...)` line, and after

```python
            self._backfill_revocation_signatures()  # spec A step 3, G12: what the restore reconcile revoked
```

add, at the same indentation:

```python
            self._backfill_acceptance_revocation_signatures()  # charter 4c: the acceptances the restore reconcile ended
```

In `peer/superyak_peer/app.py`, between the `grant_signed` route and `@app.get('/api/shared/layers')`, add:

```python
    @app.get('/api/charter/acceptances/{key}/signed')
    def acceptance_signed(key: str, request: Request):
        return store.acceptance_signed(actor(request), key)  # charter 4c: the person and the signer; a ship key gets 403

```

In `peer/pyproject.toml`, add `    "superyak_peer/acceptances.py",` after each of the two `    "superyak_peer/__main__.py",`
lines (sdist and wheel), and `    "tests/test_acceptances.py",` after `    "tests/conftest.py",`.

In `peer/tests/test_restore.py`, `RECONCILED_TABLES`' last line becomes:

```python
    'account_role_changes', 'room_briefs', 'grants', 'budget_uses', 'charter_acceptances'}
```

(`test_every_table_is_either_reconciled_or_named_coordination` fails the moment the schema has a table in neither list;
Task 7 adds the step that reconciles it, as 3b's R9 did for grants.)

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_signatures.py tests/test_restore.py tests/test_grants.py tests/test_packaging.py`
Expected: `121 passed` on Appendix A.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- drop `SIGNED_RECORDS`' `charter_acceptances` entry → `test_a_station_whose_only_signed_record_is_an_acceptance_does_not_start_without_its_identity`
  (Store starts);
- its query without `WHERE signature!=''` → the same test (the first acceptance on a new station counts its own row
  and refuses as a lost identity);
- `'follow': row['follow']` for `'follow': bool(row['follow'])` in `_acceptance_record` →
  `test_an_acceptance_and_its_end_are_signed_records_of_their_own_kinds` (`0` signs as `0`, not `false`);
- drop the `_backfill_acceptance_revocation_signatures()` line in `Store.__init__` → `test_startup_signs_each_unsigned_acceptance_end_once`;
- `if row is None or actor != row['person_id']:` in `acceptance_signed` (the signer left out), and `if row is None:`
  (anyone) → `test_an_acceptances_signed_record_goes_to_its_person_and_its_signer_only`;
- wrap `self._sign_acceptance(db, key)` in `_insert_acceptance` in `try: ... except ValueError: pass` →
  `test_an_acceptance_whose_signing_fails_is_not_stored` (an unsigned row is stored);
- `holds_signed_records` querying every `SIGNED_RECORDS` entry without the `table in tables` test →
  `test_the_lost_identity_check_reads_a_database_from_before_4c` (`no such table: charter_acceptances`).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/superyak_peer/identity.py peer/superyak_peer/signatures.py peer/superyak_peer/db.py peer/superyak_peer/app.py peer/pyproject.toml peer/tests/test_acceptances.py peer/tests/test_signatures.py peer/tests/test_restore.py
git commit -m "Charter 4c: the charter_acceptances table and its two signed records (R29)"
```

---

### Task 2: A pinned acceptance binds its owner's ships (R29, R31; C15, C19, C22)

**Files:**
- Modify: `peer/superyak_peer/acceptances.py` (three methods after `_end_acceptance`)
- Modify: 4a's `Instructions._charter_pair` (its last statement) and `Instructions._charter_status` (its `accepted`)
  (I9, I10; `instructions.py` with Appendix A)
- Test: `peer/tests/test_acceptances.py`, `peer/tests/test_ship_agent.py`

**Interfaces:**
- Consumes: Task 1's `_insert_acceptance` and test helpers; 4a's I9 (`_charter_pair`, `_binding_layers`), I10
  (`_charter_status`), I11 (`_active_charter`), I15 (the charter routes), I16 (`charter_line`).
- Produces:
  - `Acceptances._acceptance_in_force(db, person_id) -> sqlite3.Row | None`; `Acceptances._accepts(db, person_id,
    layer_id) -> bool`; `Acceptances._accepted_pair(db, owner_id) -> tuple[str, int] | None` (a pin binds its
    revision; Task 4 adds follow, Task 5 a `replace` argument).
  - 4a's `_charter_pair` answers an accepting owner's ships with `_accepted_pair`, so every binding reader (tickets,
    `GET /api/ships/me/instructions`, `GET /api/ships`, the caps checks) carries the acceptance.
  - Test helpers: `super_admin(store, user)`, `new_charter(client, title='Station law', body='Be kind.', policy=None)
    -> dict`, `sign(client, layer_id, confirm=(), **changes) -> int` (the new revision), `withdraw(client, layer_id,
    confirm=())`, `bound(store, ship) -> list[tuple[str, int]]`, `charter_field(store, ship) -> dict | None`, and the
    `station` fixture: a dict with `app`, `store`, `clock`, the people `andy` (a super admin), `jenn`, `organizer`,
    `stanley`, their clients `a`, `j`, `o`, `s`, the ships `rio` (Andy's), `defiant` (Jenn's), `enterprise`
    (Stanley's) and `odo` (a resident) with `rio_key`, `defiant_key`, `enterprise_key`, and `law`, the id of Andy's
    charter draft.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_acceptances.py`:

```python
def super_admin(store, user):
    """Only a super admin signs a charter (C3); the conftest's people are not."""
    with store.transaction() as db:
        db.execute('UPDATE users SET is_admin=1, is_super_admin=1 WHERE id=?', (user['id'],))


def new_charter(client, title='Station law', body='Be kind.', policy=None):
    """A charter draft through 4a's draft route (spec Routes): its layer."""
    fields = {'kind': 'instructions', 'title': title, 'body': body, 'charter': True, 'audience_users': []}
    if policy is not None:
        fields['policy'] = policy
    response = client.post('/api/layers', json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def sign(client, layer_id, confirm=(), **changes):
    """Saves changes to a charter's draft, if any, and activates it with confirm_widenings (4a's routes): the new
    revision's number."""
    layer = client.get(f'/api/layers/{layer_id}').json()
    if changes:
        saved = client.put(f'/api/layers/{layer_id}', json={'version': layer['version'], **changes})
        assert saved.status_code == 200, saved.text
        layer = saved.json()
    response = client.post(f'/api/layers/{layer_id}/activate', json={'version': layer['version'], 'confirm_widenings': list(confirm)})
    assert response.status_code == 200, response.text
    return response.json()['revision']


def withdraw(client, layer_id, confirm=()):
    response = client.post(f'/api/layers/{layer_id}/withdraw', json={'confirm_widenings': list(confirm)})
    assert response.status_code == 200, response.text


def bound(store, ship):
    """The (layer_id, revision) pairs that bind a ship now, charter pair first, as tickets record them."""
    with store.transaction() as db:
        return [(layer['layer_id'], layer['revision']) for layer in store._binding_layers(db, ship['id'])]


def charter_field(store, ship):
    """GET /api/ships/me/instructions' charter field for this ship (4a's route; 4c fills `accepted`)."""
    with store.transaction() as db:
        return store._charter_status(db, db.execute('SELECT * FROM users WHERE id=?', (ship['id'],)).fetchone())


@pytest.fixture
def station(env):
    """Andy, a super admin, owns rio-grande and drafts the charter; Jenn owns defiant and Stanley enterprise; the
    organizer is an admin who owns nothing; Odo is a resident."""
    app, clients, users, clock = env
    store = app.state.store
    andy, jenn, organizer, stanley = users
    for user, name in ((andy, 'Andy'), (jenn, 'Jenn'), (stanley, 'Stanley')):
        store.rename_user(user['id'], name)
    super_admin(store, andy)
    rio, rio_key = docked(store, andy['id'], 'rio-grande')
    defiant, defiant_key = docked(store, jenn['id'], 'defiant')
    enterprise, enterprise_key = docked(store, stanley['id'], 'enterprise')
    odo = store.create_station_ship('odo', 'Odo')
    law = new_charter(clients[0])
    return dict(app=app, store=store, clock=clock, andy=andy, jenn=jenn, organizer=organizer, stanley=stanley,
                a=clients[0], j=clients[1], o=clients[2], s=clients[3], rio=rio, rio_key=rio_key, defiant=defiant,
                defiant_key=defiant_key, enterprise=enterprise, enterprise_key=enterprise_key, odo=odo, law=law['id'])


def test_a_pinned_acceptance_binds_every_ship_its_owner_has_and_docks_later(station):
    """Test 25's binding (R29, C22): Jenn accepts revision 2 pinned, so defiant is bound by it, first; a ship she docks
    afterwards is bound too; Stanley, who accepted nothing, isn't; Andy's ship and Odo carry the active revision."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    assert sign(s['a'], law, body='Be kind. Run the tests.') == 2
    by_hand(store, s['jenn'], s['andy'], law, 2)
    own = s['j'].post('/api/layers', json={'kind': 'instructions', 'title': 'House rules', 'body': 'x',
                                           'audience_users': [s['defiant']['id']]}).json()
    s['j'].post(f'/api/layers/{own["id"]}/activate', json={'version': own['version']})
    assert bound(store, s['defiant']) == [(law, 2), (own['id'], 1)]
    voyager, _ = docked(store, s['jenn']['id'], 'voyager')
    assert bound(store, voyager) == [(law, 2)]
    assert bound(store, s['enterprise']) == []
    assert bound(store, s['rio']) == [(law, 2)] and bound(store, s['odo']) == [(law, 2)]
    assert charter_field(store, s['defiant']) == {'layer_id': law, 'revision': 2, 'binding': 2, 'accepted': True}
    assert charter_field(store, s['enterprise']) == {'layer_id': law, 'revision': 2, 'binding': None, 'accepted': False}


def test_a_pin_stays_at_its_revision_through_later_ones(station):
    """Test 28's pin (R31): Andy signs revision 3, prose only; Jenn's ship stays at revision 2, and the ship's charter
    field says revision 3 is active and revision 2 binds it."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    by_hand(store, s['jenn'], s['andy'], law, 2)
    assert sign(s['a'], law, body='Third.') == 3
    assert bound(store, s['defiant']) == [(law, 2)] and bound(store, s['rio']) == [(law, 3)]
    assert charter_field(store, s['defiant']) == {'layer_id': law, 'revision': 3, 'binding': 2, 'accepted': True}


def test_a_withdrawn_charter_binds_no_one_and_binds_a_pin_again_when_activated_again(station):
    """Test 32 (C15, C22): withdrawn, the charter binds no ship and Jenn's acceptance stays in force; the same layer
    activated again binds her pinned revision. A second charter layer activated after the first was withdrawn binds
    Andy's ship and Odo, and not Jenn's until she accepts it."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    accepted = by_hand(store, s['jenn'], s['andy'], law, 2)
    withdraw(s['a'], law)
    assert [bound(store, ship) for ship in (s['rio'], s['defiant'], s['odo'])] == [[], [], []]
    assert acceptance_row(store, accepted)['revoked'] is None
    assert charter_field(store, s['defiant']) is None
    assert sign(s['a'], law, body='Fourth.') == 4  # number 3 went to the withdrawal
    assert bound(store, s['defiant']) == [(law, 2)] and bound(store, s['rio']) == [(law, 4)]
    withdraw(s['a'], law)
    other = new_charter(s['a'], title='Station charter')['id']
    assert sign(s['a'], other) == 1
    assert bound(store, s['rio']) == [(other, 1)] and bound(store, s['odo']) == [(other, 1)]
    assert bound(store, s['defiant']) == []
    assert charter_field(store, s['defiant']) == {'layer_id': other, 'revision': 1, 'binding': None, 'accepted': False}
```

Append to `peer/tests/test_ship_agent.py`:

```python
def test_a_pinned_owners_ship_says_the_active_charter_revision_is_pending(env):
    """Charter 4c, test 28's status line on the station (R20; 4a's test 20 has it only against the fake station): Jenn
    pinned revision 2 and Andy signed revision 3, so her ship's charter line names both; Stanley's ship, whose owner
    accepted nothing, says so."""
    from superyak_agent.station import charter_line
    from test_acceptances import by_hand, new_charter, sign, super_admin
    from test_instructions import docked, ship_client
    app, clients, users, clock = env
    store = app.state.store
    andy, jenn, organizer, stanley = users
    super_admin(store, andy)
    defiant, defiant_key = docked(store, jenn['id'], 'defiant')
    enterprise, enterprise_key = docked(store, stanley['id'], 'enterprise')
    law = new_charter(clients[0])['id']
    sign(clients[0], law)
    sign(clients[0], law, body='Second.')
    by_hand(store, jenn, andy, law, 2)
    assert charter_line(ship_client(app, defiant_key).get('/api/ships/me/instructions').json()['charter']) == (
        'Charter: revision 2 binds this ship')
    sign(clients[0], law, body='Third.')
    assert charter_line(ship_client(app, defiant_key).get('/api/ships/me/instructions').json()['charter']) == (
        "Charter: revision 3 is pending for this ship's owner; revision 2 binds this ship")
    assert charter_line(ship_client(app, enterprise_key).get('/api/ships/me/instructions').json()['charter']) == (
        "Charter: revision 3 is active; this ship's owner has not accepted it")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_ship_agent.py tests/test_instructions.py`
Expected: `4 failed, 53 passed` on Appendix A. The three binding tests fail at their first `bound(...)` for Jenn's ship
(`assert [('…', 1)] == [('…', 2), ('…', 1)]` for the first: her own layer alone, no charter pair; `[] == [('…', 2)]` for
the others); the status test with `- Charter: revision 2 binds this ship` / `+ Charter: revision 2 is active; this
ship's owner has not accepted it`. (The words come from 4a's `charter_line`, I16.)

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/acceptances.py`, append to the `Acceptances` class, after `_end_acceptance`:

```python
    def _acceptance_in_force(self, db, person_id):
        """The person's one acceptance in force (the partial unique index keeps at most one), or None."""
        return db.execute('SELECT * FROM charter_acceptances WHERE person_id=? AND revoked IS NULL', (person_id,)).fetchone()

    def _accepts(self, db, person_id, layer_id):
        """Whether the person's acceptance in force names this charter layer."""
        held = self._acceptance_in_force(db, person_id)
        return held is not None and held['layer_id'] == layer_id

    def _accepted_pair(self, db, owner_id):
        """Spec Binding 2, the owner who neither signed the active charter nor is absent: the (layer_id, revision) their
        acceptance in force binds, or None. None while the acceptance's layer has no active revision: a withdrawn
        charter binds no ship, and the acceptance binds again if that layer is activated again (C15). A pin binds its
        revision."""
        held = self._acceptance_in_force(db, owner_id)
        if held is None:
            return None
        layer = db.execute('SELECT active_revision FROM layers WHERE id=?', (held['layer_id'],)).fetchone()
        if layer is None or layer['active_revision'] is None:
            return None
        return held['layer_id'], held['revision']
```

In 4a's `Instructions._charter_pair` (I9), the last statement, which answers `None` for a ship whose owner is neither
absent nor the active charter's signer, becomes:

```python
        return self._accepted_pair(db, ship['owner_id'])  # charter 4c: the revision the owner's acceptance binds
```

With Appendix A that replaces the method's last line, `        return None`.

In 4a's `Instructions._charter_status` (I10), `accepted` gains the acceptance. With Appendix A, replace

```python
        accepted = not ship['owner_id'] or ship['owner_id'] == active['owner_id']
```

with

```python
        accepted = (not ship['owner_id'] or ship['owner_id'] == active['owner_id']
                    or self._accepts(db, ship['owner_id'], active['id']))  # charter 4c: an acceptance of this charter
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_ship_agent.py tests/test_instructions.py`
Expected: `57 passed` on Appendix A.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- `_charter_pair`'s last statement back to `return None` → `test_a_pinned_acceptance_binds_every_ship_its_owner_has_and_docks_later`;
- `_accepted_pair` without its `if layer is None or layer['active_revision'] is None: return None` →
  `test_a_withdrawn_charter_binds_no_one_and_binds_a_pin_again_when_activated_again` (pinned text outlives its charter);
- `return held['layer_id'], layer['active_revision']` (a pin that moves) → `test_a_pin_stays_at_its_revision_through_later_ones`;
- `_charter_status` without the `_accepts` clause → `test_a_pinned_acceptance_binds_every_ship_its_owner_has_and_docks_later`
  (`accepted` false for Jenn's ship);
- `_accepts` without `and held['layer_id'] == layer_id` → `test_a_withdrawn_charter_binds_no_one_and_binds_a_pin_again_when_activated_again`
  (an acceptance of the withdrawn layer reads as accepting the new charter).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/superyak_peer/instructions.py peer/tests/test_acceptances.py peer/tests/test_ship_agent.py
git commit -m "Charter 4c: a pinned acceptance binds its owner's ships, now and docked later (R29, R31, C22)"
```

(Add whichever file holds 4a's `_charter_pair` and `_charter_status`, if not `instructions.py`.)

---

### Task 3: Reading, accepting and leaving (R30, R32; C17, C18, C20; the acceptance's caps)

**Files:**
- Modify: `peer/superyak_peer/acceptances.py` (imports, the refusal messages and `acceptance_short` after the schema,
  nine methods at the end of the class)
- Modify: `peer/superyak_peer/app.py` (three routes before the acceptance's signed route)
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: Tasks 1-2 (`_insert_acceptance`, `_end_acceptance`, `_acceptance_in_force`, `_accepted_pair`, the
  `station` fixture and helpers); 4a's I1-I7 (`DEFAULT_POLICY`, `widened_paths`, `narrowed_paths`, `confirm_paths`,
  `require_confirmed`, `over_caps`, `CAPS_REFUSAL`, `_layers_for`), I8 (`_own_layers`), I11 (`_active_charter`).
  `make_grant`, `_grant_view`, `_grant_validity`, `_grant_visible`, `_owns_a_target`, `issue_ticket` (step 3), read only.
- Produces:
  - `Acceptances.charter_view(actor) -> dict` (`GET /api/charter`); `accept_charter(actor, data: dict) -> dict`;
    `leave_charter(actor, reason=None) -> dict`; both writes answer with `charter_view`'s shape.
  - Helpers later tasks use: `_binding_pair(db, actor, active) -> tuple | None`, `_charter_revision(db, layer_id,
    revision) -> {layer_id, revision, title, body, policy}`, `_owned_ships(db, person_id) -> list[Row]` (by name, id),
    `_too_large(db, person_id, layer_id, revision) -> list[str]` (ship names), `_person_names(db, *policies) -> dict`.
  - Constants `ACCEPT_KEYS`, `LAYER_SHAPE`, `REVISION_SHAPE`, `FOLLOW_SHAPE`, `CHANGED`, `SIGNED_IT`, `NOT_ACCEPTED`,
    `REASON_SHAPE`; `acceptance_short(acceptance_id) -> str`.
  - Routes `GET /api/charter`, `POST /api/charter/accept`, `POST /api/charter/leave`.
  - Test helpers: `accept(client, layer_id, revision, follow=False, confirm=(), **raw) -> (status, body)` (`body=`
    sends a body as it is), `read(client) -> dict`, `own_layers(client, ship, count, body='x') -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_acceptances.py`:

```python
def accept(client, layer_id, revision, follow=False, confirm=(), **raw):
    """POST /api/charter/accept: (status, body). raw replaces the body outright, for malformed requests."""
    body = raw.get('body', {'layer_id': layer_id, 'revision': revision, 'follow': follow, 'confirm_widenings': list(confirm)})
    response = client.post('/api/charter/accept', json=body)
    return response.status_code, response.json()


def read(client):
    response = client.get('/api/charter')
    assert response.status_code == 200, response.text
    return response.json()


def own_layers(client, ship, count, body='x'):
    """count instructions layers of the caller's own, each activated for ship: their ids."""
    made = []
    for n in range(count):
        layer = client.post('/api/layers', json={'kind': 'instructions', 'title': f'Own {n}', 'body': body,
                                                 'audience_users': [ship['id']]}).json()
        response = client.post(f'/api/layers/{layer["id"]}/activate', json={'version': layer['version']})
        assert response.status_code == 200, response.text
        made.append(layer['id'])
    return made


def test_accepting_refuses_in_the_spec_order_and_the_same_acceptance_twice_is_one_row(station):
    """Test 27 (R30): each refusal in spec Routes' order, one row each, then a request failing two checks gets the
    earlier one; accepting the same revision with the same follow again answers 200 and adds no row; leaving with no
    acceptance gets 409."""
    s = station
    store, law = s['store'], s['law']
    assert accept(s['j'], law, 1) == (409, {'error': 'The charter changed; read it again'})  # no charter is active
    sign(s['a'], law, policy={'version': 1, 'delegation': {'max_depth': 4}}, confirm=['delegation.max_depth'])
    good = {'layer_id': law, 'revision': 1, 'follow': False, 'confirm_widenings': ['delegation.max_depth']}
    for body, status, error in (
            ({**good, 'extra': 1}, 400, 'An acceptance takes only layer_id, revision, follow and confirm_widenings'),
            ({**good, 'layer_id': 5}, 400, 'layer_id is the id of the charter layer'),
            ({**good, 'revision': '1'}, 400, 'revision is a whole number'),
            ({**good, 'revision': True}, 400, 'revision is a whole number'),
            ({**good, 'revision': 1.0}, 400, 'revision is a whole number'),
            ({**good, 'follow': 1}, 400, 'follow is true or false'),
            ({**good, 'confirm_widenings': 'delegation.max_depth'}, 400, 'confirm_widenings is a list of paths'),
            ({**good, 'confirm_widenings': ['x'] * 106}, 400, 'confirm_widenings is a list of paths'),
            ({**good, 'layer_id': 'no-such-layer'}, 409, 'The charter changed; read it again'),
            ({**good, 'revision': 2}, 409, 'The charter changed; read it again'),
            ({**good, 'revision': 2 ** 70}, 409, 'The charter changed; read it again'),  # past SQLite's integers: never a 500
            ({**good, 'confirm_widenings': []}, 409, 'Confirm exactly these widenings: delegation.max_depth'),
            ({**good, 'confirm_widenings': ['delegation.max_depth'] * 2}, 409, 'Confirm exactly these widenings: delegation.max_depth')):
        assert accept(s['j'], None, None, body=body) == (status, {'error': error}), body
    assert accept(s['a'], None, None, body=good) == (409, {'error': 'You signed this charter; it binds your ships already'})
    own_layers(s['s'], s['enterprise'], 10)
    assert accept(s['s'], None, None, body=good) == (409, {'error': 'Enterprise would have more than 10 instruction layers or 48,000 bytes of them'})
    for body, status, error in (  # each fails two checks; the earlier answers
            ({**good, 'extra': 1, 'revision': 'x'}, 400, 'An acceptance takes only layer_id, revision, follow and confirm_widenings'),
            ({**good, 'follow': None, 'confirm_widenings': 5}, 400, 'follow is true or false'),
            ({**good, 'revision': 2, 'confirm_widenings': 5}, 400, 'confirm_widenings is a list of paths'),
            ({**good, 'revision': 2, 'confirm_widenings': []}, 409, 'The charter changed; read it again')):
        assert accept(s['j'], None, None, body=body) == (status, {'error': error}), body
    assert accept(s['a'], None, None, body={**good, 'revision': 2})[1] == {'error': 'The charter changed; read it again'}  # 3 before 4
    assert accept(s['a'], None, None, body={**good, 'confirm_widenings': []})[1] == {'error': 'You signed this charter; it binds your ships already'}  # 4 before 5
    assert accept(s['s'], None, None, body={**good, 'confirm_widenings': []})[1] == {'error': 'Confirm exactly these widenings: delegation.max_depth'}  # 5 before 6
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM charter_acceptances').fetchone()[0] == 0
    assert accept(s['j'], None, None, body=good)[0] == 200
    again = accept(s['j'], None, None, body=good)  # a retry of the same request
    assert again[0] == 200 and again[1]['acceptance']['revision'] == 1
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM charter_acceptances').fetchone()[0] == 1
    left = s['o'].post('/api/charter/leave', json={})
    assert (left.status_code, left.json()) == (409, {'error': 'You have not accepted a charter'})


def test_accepting_a_newer_revision_supersedes_the_old_one_in_one_transaction(station):
    """Test 28 (R30, C18): Jenn accepts revision 2 pinned, and the row is spec Data's; Andy signs revision 3, prose only,
    which shows pending with no widenings while her ship stays at 2; she accepts 3: the old row ends `superseded`, by
    her, signed, and the new row names 3. A second row in force for her, inserted by hand, fails on the unique index."""
    import sqlite3
    s = station
    store, law, clock = s['store'], s['law'], s['clock']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    status, view = accept(s['j'], law, 2)
    assert status == 200, view
    first = view['acceptance']
    row = acceptance_row(store, first['id'])
    assert {name: row[name] for name in ('person_id', 'signer_id', 'layer_id', 'revision', 'follow', 'created', 'revoked')} == {
        'person_id': s['jenn']['id'], 'signer_id': s['andy']['id'], 'layer_id': law, 'revision': 2, 'follow': 0,
        'created': 1000000.0, 'revoked': None}
    assert first == {'id': row['id'], 'short': '#' + row['id'][:4], 'layer_id': law, 'revision': 2, 'follow': False,
                     'accepted': 1000000.0}
    sign(s['a'], law, body='Third.')
    view = read(s['j'])
    assert view['pending'] == {'revision': 3, 'widenings': [], 'narrowings': [], 'too_large': [], 'baseline': 2}
    assert view['binding']['revision'] == 2 and bound(store, s['defiant']) == [(law, 2)]
    clock[0] += 60
    status, view = accept(s['j'], law, 3)
    assert status == 200 and view['acceptance']['revision'] == 3 and view['pending'] is None
    old = acceptance_row(store, first['id'])
    assert (old['revoked'], old['revoked_by'], old['revoke_reason']) == (1000060.0, s['jenn']['id'], 'superseded')
    assert verify_record(card_of(store._station_identity()), records(store, first['id'])[1], old['revocation_signature'])
    assert bound(store, s['defiant']) == [(law, 3)]
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as db:
            db.execute("INSERT INTO charter_acceptances(id,person_id,signer_id,layer_id,revision,follow,created,signature) "
                       "VALUES('x', ?, ?, ?, 3, 0, 1.0, 'y')", (s['jenn']['id'], s['andy']['id'], law))


def test_a_first_acceptance_and_one_after_leaving_compare_with_the_defaults(station):
    """Test 31 (C20): with max_depth 4, Jenn's first acceptance must confirm that widening against the no-charter
    defaults; she leaves, her ship is unbound, and accepting again must confirm it again: an ended acceptance is no
    baseline. Leaving takes an optional reason of one line."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law, policy={'version': 1, 'delegation': {'max_depth': 4}}, confirm=['delegation.max_depth'])
    view = read(s['j'])
    assert view['pending']['baseline'] == 'defaults'
    assert view['pending']['widenings'] == [{'path': 'delegation.max_depth', 'before': 3, 'after': 4}]
    assert accept(s['j'], law, 1)[0] == 409
    assert accept(s['j'], law, 1, confirm=['delegation.max_depth'])[0] == 200
    assert bound(store, s['defiant']) == [(law, 1)]
    for reason in ('two\nlines', 'x' * 201, 5):
        assert s['j'].post('/api/charter/leave', json={'reason': reason}).json() == {'error': 'A reason is one line of at most 200 characters'}
    left = s['j'].post('/api/charter/leave', json={'reason': '  '})
    assert left.status_code == 200 and left.json()['acceptance'] is None and left.json()['pending']['baseline'] == 'defaults'
    with store.transaction() as db:
        assert db.execute('SELECT revoke_reason FROM charter_acceptances').fetchone()[0] == 'left'
    assert bound(store, s['defiant']) == []
    assert accept(s['j'], law, 1)[1] == {'error': 'Confirm exactly these widenings: delegation.max_depth'}
    assert accept(s['j'], law, 1, confirm=['delegation.max_depth'])[0] == 200
    sign(s['a'], law, body='Prose only.')
    assert accept(s['j'], law, 2)[0] == 200  # against revision 1, which binds her now: nothing widens
    assert s['j'].post('/api/charter/leave', json={'reason': 'Moving on'}).status_code == 200
    with store.transaction() as db:
        assert sorted(row[0] for row in db.execute('SELECT revoke_reason FROM charter_acceptances')) == ['Moving on', 'left', 'superseded']


def test_get_charter_shows_each_state_and_never_another_persons_acceptance(station):
    """Test 36 (R32): no charter; the signer, who sees Jenn in `acceptances`; a person who owns no ships; a pinned owner
    with a pending revision; an owner whose acceptance names a withdrawn layer while another charter is active, told
    apart by layer_id. No one but the signer sees another person's acceptance."""
    s = station
    store, law, clock = s['store'], s['law'], s['clock']
    empty = {'charter': None, 'signer': False, 'acceptance': None, 'binding': None, 'pending': None, 'acceptances': []}
    assert read(s['j']) == empty and read(s['a']) == empty
    policy = {'version': 1, 'grantees': {'people': [s['jenn']['id']]}}
    sign(s['a'], law, policy=policy)
    accepted = accept(s['j'], law, 1)[1]['acceptance']
    clock[0] += 60
    sign(s['a'], law, body='Second.')
    signer = read(s['a'])
    current = signer['charter']
    assert current == {'layer_id': law, 'revision': 2, 'title': 'Station law', 'body': 'Second.', 'policy': current['policy'],
                       'names': {s['jenn']['id']: 'Jenn'}, 'signer': {'id': s['andy']['id'], 'name': 'Andy'},
                       'created': 1000060.0}
    assert current['policy']['grantees'] == {'people': [s['jenn']['id']], 'ships_of': []}
    assert signer['signer'] is True and signer['acceptance'] is None and signer['pending'] is None
    assert signer['binding'] == {'layer_id': law, 'revision': 2, 'title': 'Station law', 'body': 'Second.', 'policy': current['policy']}
    assert signer['acceptances'] == [{'person': {'id': s['jenn']['id'], 'name': 'Jenn'}, 'revision': 1, 'follow': False,
                                      'accepted': 1000000.0}]
    nobody = read(s['o'])  # owns no ships: the acceptance would cover ships docked later
    assert (nobody['signer'], nobody['acceptance'], nobody['binding'], nobody['acceptances']) == (False, None, None, [])
    assert nobody['pending'] == {'revision': 2, 'widenings': [], 'narrowings': [{'path': 'grantees', 'before': None,
                                 'after': {'people': [s['jenn']['id']], 'ships_of': []}}], 'too_large': [], 'baseline': 'defaults'}
    pinned = read(s['j'])
    assert pinned['acceptance'] == accepted and pinned['acceptances'] == []
    assert pinned['binding'] == {'layer_id': law, 'revision': 1, 'title': 'Station law', 'body': 'Be kind.', 'policy': current['policy']}
    assert pinned['pending'] == {'revision': 2, 'widenings': [], 'narrowings': [], 'too_large': [], 'baseline': 1}
    assert read(s['s'])['acceptance'] is None and read(s['s'])['acceptances'] == []
    withdraw(s['a'], law, confirm=['grantees'])
    other = new_charter(s['a'], title='Station charter')['id']
    sign(s['a'], other)
    moved = read(s['j'])
    assert moved['acceptance']['layer_id'] == law and moved['charter']['layer_id'] == other
    assert moved['binding'] is None and moved['pending']['baseline'] == 'defaults' and moved['pending']['revision'] == 1
    assert read(s['a'])['acceptances'] == []  # Jenn's acceptance names the withdrawn layer, not this charter
    status, view = accept(s['j'], other, 1)  # plan Review Focus 2: against the defaults, and the old one ends
    assert status == 200 and view['acceptance']['layer_id'] == other and view['pending'] is None
    with store.transaction() as db:
        assert db.execute('SELECT revoke_reason FROM charter_acceptances WHERE id=?', (accepted['id'],)).fetchone()[0] == 'superseded'
    assert bound(store, s['defiant']) == [(other, 1)]


def test_a_ship_key_gets_403_on_every_charter_route(station):
    """Test 36, spec A Testing 3: a ship can't read, accept or leave a charter, nor read an acceptance's record."""
    s = station
    ship = ship_client(s['app'], s['defiant_key'])
    for method, path in (('GET', '/api/charter'), ('POST', '/api/charter/accept'), ('POST', '/api/charter/leave'),
                         ('GET', '/api/charter/acceptances/x/signed')):
        response = ship.request(method, path, json={})
        assert (response.status_code, response.json()) == (403, {'error': 'Ship keys cannot use this route'}), path


def test_step_3s_grant_readers_never_see_an_acceptance(station):
    """Test 26 (R29, C18), as one table: with Andy's direct grant to Jenn over Rio Grande, every grant reader answers
    the same before and after Jenn accepts Andy's charter; Andy's mention of Jenn's ship reads, and Jenn's mention of
    Rio Grande builds under the grant."""
    s = station
    store, law = s['store'], s['law']
    room = store.create_room(s['andy']['id'], 'Ops', [s['jenn']['id'], s['rio']['id'], s['defiant']['id']])
    grant = store.make_grant(s['andy']['id'], s['jenn']['id'], [s['rio']['id']], [room['id']], 24, 5)['id']
    sign(s['a'], law)

    def answers():
        lists = [client.get('/api/grants').json() for client in (s['j'], s['a'], s['s'])]  # never inside a transaction
        with store.transaction() as db:
            row = db.execute('SELECT * FROM grants WHERE id=?', (grant,)).fetchone()
            return {'lists': lists, 'view': store._grant_view(db, s['andy']['id'], row), 'validity': store._grant_validity(db, row),
                    'visible': [store._grant_visible(db, user['id'], row) for user in (s['jenn'], s['andy'], s['stanley'])],
                    'owns': [store._owns_a_target(db, user['id'], row) for user in (s['jenn'], s['andy'], s['stanley'])]}
    before = answers()
    assert [len(listed) for listed in before['lists']] == [1, 1, 0] and before['validity'] == (True, None)
    assert accept(s['j'], law, 1)[0] == 200
    assert answers() == before
    asked = store.send_message(s['andy']['id'], room['id'], 'a1', '@defiant please fix the notes')
    assert store.issue_ticket(s['defiant']['id'], asked['id'])['mode'] == 'read'  # an acceptance gives Andy nothing over her ship
    spent = store.send_message(s['jenn']['id'], room['id'], 'j1', '@rio-grande please fix the notes')
    ticket = store.issue_ticket(s['rio']['id'], spent['id'])
    assert (ticket['mode'], ticket['basis'], ticket['chain']) == ('build', 'grant', [grant])
```

The order test carries plan Review Focus 1 (the retry) and 3 (`2 ** 70`); the `GET /api/charter` test's end carries
Review Focus 2.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py`
Expected: `6 failed, 9 passed`. Every new test meets a route that doesn't exist yet: `(404, {'detail': 'Not Found'})`
where the test expects 409, 200 or 403 (FastAPI's own 404 for an unknown path).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/acceptances.py`, replace the import line

```python
from .common import uid
```

with

```python
import json
from .charter import DEFAULT_POLICY, confirm_paths, narrowed_paths, require_confirmed, widened_paths
from .common import Problem, uid
from .instructions import CAPS_REFUSAL, over_caps
from .ships import safe_line
```

(The first and fourth import lines are 4a's names, I1-I6.) Between the schema's closing `'''` and `class Acceptances:`
insert, right after the `'''` line, keeping two blank lines before the class:

```python
ACCEPT_FIELDS = {'layer_id', 'revision', 'follow', 'confirm_widenings'}
# Spec Routes' refusals, one message per check, so a test can tell which check answered. The first four 400s have no
# words in the spec; the rest are the spec's own.
ACCEPT_KEYS = 'An acceptance takes only layer_id, revision, follow and confirm_widenings'
LAYER_SHAPE = 'layer_id is the id of the charter layer'
REVISION_SHAPE = 'revision is a whole number'
FOLLOW_SHAPE = 'follow is true or false'
CHANGED = 'The charter changed; read it again'
SIGNED_IT = 'You signed this charter; it binds your ships already'
NOT_ACCEPTED = 'You have not accepted a charter'
REASON_SHAPE = 'A reason is one line of at most 200 characters'


def acceptance_short(acceptance_id):
    """'#' and the first 4 characters of the id, as a grant's short id is (spec Data)."""
    return '#' + acceptance_id[:4]
```

Append to the end of the `Acceptances` class, after `_accepted_pair`:

```python
    def _binding_pair(self, db, actor, active):
        """The (layer_id, revision) binding the person's ships now, owned or docked later: the active revision for its
        signer (C17), else what their acceptance binds (spec Binding 2), or None."""
        if active is not None and active['owner_id'] == actor:
            return active['id'], active['active_revision']
        return self._accepted_pair(db, actor)

    def _charter_revision(self, db, layer_id, revision):
        """A charter revision as GET /api/charter shows it, from its snapshot: {layer_id, revision, title, body,
        policy}, the policy in full (C11)."""
        snapshot = json.loads(db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?',
                                         (layer_id, revision)).fetchone()['snapshot'])
        return {'layer_id': layer_id, 'revision': revision, 'title': snapshot['title'], 'body': snapshot['body'],
                'policy': snapshot['policy']}

    def _person_names(self, db, *policies):
        """The `names` map: each person id a policy's grantee set lists, with that person's name."""
        listed = sorted({member for policy in policies if policy and policy.get('grantees')
                         for field in ('people', 'ships_of') for member in policy['grantees'][field]})
        rows = [db.execute('SELECT id, name FROM users WHERE id=?', (key,)).fetchone() for key in listed]
        return {row['id']: row['name'] for row in rows if row is not None}

    def _owned_ships(self, db, person_id):
        return db.execute("SELECT * FROM users WHERE kind='ship' AND owner_id=? ORDER BY name, id", (person_id,)).fetchall()

    def _too_large(self, db, person_id, layer_id, revision):
        """C23: the names of the person's ships that this charter revision, with each ship's own layers, would put over
        the caps, by name."""
        charter = self._layers_for(db, [(layer_id, revision)])
        return [safe_line(ship['name']) for ship in self._owned_ships(db, person_id)
                if over_caps(charter + self._own_layers(db, ship))]

    def charter_view(self, actor):
        """GET /api/charter (spec Routes, R32). Never 404."""
        with self.transaction() as db:
            return self._charter_view(db, actor)

    def _charter_view(self, db, actor):
        active = self._active_charter(db)
        held = self._acceptance_in_force(db, actor)
        pair = self._binding_pair(db, actor, active)
        binding = self._charter_revision(db, *pair) if pair else None
        view = {'charter': None, 'signer': active is not None and active['owner_id'] == actor, 'acceptance': None,
                'binding': binding, 'pending': None, 'acceptances': []}
        if held is not None:  # a person sees only their own acceptance
            view['acceptance'] = {'id': held['id'], 'short': acceptance_short(held['id']), 'layer_id': held['layer_id'],
                                  'revision': held['revision'], 'follow': bool(held['follow']), 'accepted': held['created']}
        if active is None:
            return view
        current = self._charter_revision(db, active['id'], active['active_revision'])
        signer = db.execute('SELECT name FROM users WHERE id=?', (active['owner_id'],)).fetchone()
        created = db.execute('SELECT created FROM layer_revisions WHERE layer_id=? AND revision=?',
                             (active['id'], active['active_revision'])).fetchone()['created']
        view['charter'] = {**current, 'names': self._person_names(db, current['policy'], binding and binding['policy']),
                           'signer': {'id': active['owner_id'], 'name': signer['name']}, 'created': created}
        if view['signer']:  # who has accepted the active charter, for its signer only
            view['acceptances'] = [
                {'person': {'id': row['person_id'], 'name': row['name']}, 'revision': row['revision'],
                 'follow': bool(row['follow']), 'accepted': row['created']}
                for row in db.execute('SELECT charter_acceptances.*, users.name FROM charter_acceptances JOIN users ON '
                                      'users.id=charter_acceptances.person_id WHERE charter_acceptances.layer_id=? AND '
                                      'charter_acceptances.revoked IS NULL ORDER BY charter_acceptances.created, '
                                      'charter_acceptances.id', (active['id'],))]
        elif pair != (active['id'], active['active_revision']):  # C20: against the revision binding them now, or the defaults
            baseline = binding['policy'] if binding else DEFAULT_POLICY
            view['pending'] = {'revision': active['active_revision'],
                               'widenings': widened_paths(baseline, current['policy']),
                               'narrowings': narrowed_paths(baseline, current['policy']),
                               'too_large': self._too_large(db, actor, active['id'], active['active_revision']),
                               'baseline': binding['revision'] if binding else 'defaults'}
        return view

    def accept_charter(self, actor, data):
        """POST /api/charter/accept (spec Routes, R30), refusing in the spec's order; the first failure answers. The
        same revision with the same follow again is 200 with no new row; otherwise the previous acceptance ends
        (`superseded`, by the caller, signed) and the new one is stored and signed, in one transaction."""
        if set(data) - ACCEPT_FIELDS:
            raise Problem(400, ACCEPT_KEYS)
        layer_id, revision, follow = data.get('layer_id'), data.get('revision'), data.get('follow')
        if not isinstance(layer_id, str):
            raise Problem(400, LAYER_SHAPE)
        if type(revision) is not int:  # bool is an int in Python, and 1.0 is not a whole number in JSON's sense here
            raise Problem(400, REVISION_SHAPE)
        if type(follow) is not bool:
            raise Problem(400, FOLLOW_SHAPE)
        paths = confirm_paths(data.get('confirm_widenings'))
        with self.transaction() as db:
            active = self._active_charter(db)
            if active is None or active['id'] != layer_id or active['active_revision'] != revision:
                raise Problem(409, CHANGED)
            if active['owner_id'] == actor:
                raise Problem(409, SIGNED_IT)
            held = self._acceptance_in_force(db, actor)
            if (held is not None and held['layer_id'] == layer_id and held['revision'] == revision
                    and bool(held['follow']) == follow):
                return self._charter_view(db, actor)  # a retried request: nothing changes, and no new row
            pair = self._accepted_pair(db, actor)
            baseline = self._charter_revision(db, *pair)['policy'] if pair else DEFAULT_POLICY
            require_confirmed(paths, widened_paths(baseline, self._charter_revision(db, layer_id, revision)['policy']))
            too_large = self._too_large(db, actor, layer_id, revision)
            if too_large:
                raise Problem(409, CAPS_REFUSAL.format(ship=too_large[0]))
            if held is not None:
                self._end_acceptance(db, held['id'], actor, 'superseded')
            self._insert_acceptance(db, actor, active['owner_id'], layer_id, revision, follow)
            return self._charter_view(db, actor)

    def leave_charter(self, actor, reason=None):
        """POST /api/charter/leave (spec Routes): ends the caller's acceptance in force, with `left` or the reason
        given, signed. A missing, null or blank reason is `left`."""
        if reason is None or (isinstance(reason, str) and not reason.strip()):
            reason = 'left'
        if not isinstance(reason, str) or len(reason) > 200 or reason.splitlines() != [reason] or '\x00' in reason:
            raise Problem(400, REASON_SHAPE)
        with self.transaction() as db:
            held = self._acceptance_in_force(db, actor)
            if held is None:
                raise Problem(409, NOT_ACCEPTED)
            self._end_acceptance(db, held['id'], actor, reason)
            return self._charter_view(db, actor)
```

In `peer/superyak_peer/app.py`, before `    @app.get('/api/charter/acceptances/{key}/signed')` insert:

```python
    @app.get('/api/charter')
    def charter(request: Request):
        return store.charter_view(actor(request))  # charter 4c: a person session; a ship key gets 403

    @app.post('/api/charter/accept')
    async def charter_accept(request: Request):
        who, data = actor(request), await body(request)  # a person with CSRF
        return store.accept_charter(who, data)

    @app.post('/api/charter/leave')
    async def charter_leave(request: Request):
        who, data = actor(request), await body(request)
        return store.leave_charter(who, data.get('reason'))

```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py`
Expected: `15 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- the same-acceptance `return` replaced by `pass` (no idempotence) →
  `test_accepting_refuses_in_the_spec_order_and_the_same_acceptance_twice_is_one_row` (the retry gets 409);
- `baseline = DEFAULT_POLICY` for the line computing `baseline` in `accept_charter` →
  `test_a_first_acceptance_and_one_after_leaving_compare_with_the_defaults` (revision 2 asks again for revision 1's
  widening);
- drop `if held is not None: self._end_acceptance(db, held['id'], actor, 'superseded')` →
  `test_accepting_a_newer_revision_supersedes_the_old_one_in_one_transaction` (`UNIQUE constraint failed`);
- drop the `SIGNED_IT` check → the order test;
- `if True:` for `if view['signer']:` in `_charter_view` → `test_get_charter_shows_each_state_and_never_another_persons_acceptance`
  (Jenn sees `acceptances`);
- `'baseline': 'defaults'` always → the supersede test (`baseline` 2);
- `reason = 'revoked'` for `reason = 'left'` in `leave_charter` → the baseline test;
- `if over_caps(charter)]` in `_too_large` (own layers left out) → the order test (Enterprise's 409);
- drop the unknown-key check → the order test;
- `if not isinstance(revision, int):` for `if type(revision) is not int:` → the order test (`True` passes as 1);
- drop the caps check in `accept_charter` → the order test;
- in `accept_charter`, `db.execute('SELECT 1 FROM layer_revisions WHERE revision=?', (revision,))` as the
  transaction's first statement (an integer that reaches SQL) → the order test (`OverflowError`, a 500 for `2 ** 70`);
- in `_insert_acceptance`, also `self._insert_grant(db, person_id, signer_id, [], '*', 720, 1)` after signing (spec A's
  acceptance stored as a grant) → `test_step_3s_grant_readers_never_see_an_acceptance` (Jenn's grant list gains it).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/superyak_peer/app.py peer/tests/test_acceptances.py
git commit -m "Charter 4c: GET /api/charter, accepting and leaving, in the spec's order (R30, R32)"
```

---

### Task 4: Follow (R31, C21)

**Files:**
- Modify: `peer/superyak_peer/acceptances.py` (`_accepted_pair`; `_follow_walk` after it)
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: Tasks 2-3 (`_acceptance_in_force`, `_charter_revision`, the helpers); 4a's I2 (`widened_paths`), I15
  (snapshots: `charter`, `policy`).
- Produces: `Acceptances._follow_walk(db, held: sqlite3.Row) -> int`, the revision a follow acceptance's walk stops at
  (Task 5 makes it return a pair and take `replace`); `_accepted_pair` answers a follow acceptance with it. Test helper:
  `DEPTH`, a policy whose only widening against the defaults is `delegation.max_depth` 3 → 4.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_acceptances.py`:

```python
DEPTH = {'version': 1, 'delegation': {'max_depth': 4}}  # one widening against the defaults: delegation.max_depth 3 -> 4


def test_a_follower_never_takes_a_widening_even_behind_a_prose_revision(station):
    """Test 29 (spec A, R31): Jenn follows at revision 3; revision 4 widens max_depth and revision 5 changes only prose.
    Her ship stays at 3, and revision 5 is pending with revision 4's widening listed against 3."""
    s = station
    store, law = s['store'], s['law']
    for body in ('One.', 'Two.', 'Three.'):
        sign(s['a'], law, body=body)
    assert accept(s['j'], law, 3, follow=True)[0] == 200
    assert sign(s['a'], law, policy=DEPTH, confirm=['delegation.max_depth']) == 4
    assert sign(s['a'], law, body='Five.') == 5
    assert bound(store, s['defiant']) == [(law, 3)]
    view = read(s['j'])
    assert view['acceptance']['revision'] == 3 and view['acceptance']['follow'] is True and view['binding']['revision'] == 3
    assert view['pending'] == {'revision': 5, 'widenings': [{'path': 'delegation.max_depth', 'before': 3, 'after': 4}],
                               'narrowings': [], 'too_large': [], 'baseline': 3}


def test_a_follower_compares_each_revision_with_the_one_binding_them_then(station):
    """Test 30, first sequence (C21): Jenn follows at revision 3; revision 4 narrows max_depth to 2, which she follows;
    revision 5 sets it back to 3, a widening against 4, so she stops at 4 and 5 is pending."""
    s = station
    store, law = s['store'], s['law']
    for body in ('One.', 'Two.', 'Three.'):
        sign(s['a'], law, body=body)
    assert accept(s['j'], law, 3, follow=True)[0] == 200
    sign(s['a'], law, policy={'version': 1, 'delegation': {'max_depth': 2}})
    assert bound(store, s['defiant']) == [(law, 4)]
    sign(s['a'], law, policy={'version': 1}, confirm=['delegation.max_depth'])
    assert bound(store, s['defiant']) == [(law, 4)] and bound(store, s['rio']) == [(law, 5)]
    assert read(s['j'])['pending']['widenings'] == [{'path': 'delegation.max_depth', 'before': 2, 'after': 3}]


def test_a_follower_is_never_carried_across_a_withdrawal(station):
    """Test 30, second sequence (C21, R31): Jenn follows at revision 3 and moves to 4 (prose); Andy withdraws (number 5
    is skipped) and activates 6, prose only. Her ship is at 4 and 6 is pending; the missing 5 raises nothing."""
    s = station
    store, law = s['store'], s['law']
    for body in ('One.', 'Two.', 'Three.'):
        sign(s['a'], law, body=body)
    assert accept(s['j'], law, 3, follow=True)[0] == 200
    sign(s['a'], law, body='Four.')
    assert bound(store, s['defiant']) == [(law, 4)]
    withdraw(s['a'], law)
    assert bound(store, s['defiant']) == []
    assert sign(s['a'], law, body='Six.') == 6
    with store.transaction() as db:
        assert [row[0] for row in db.execute('SELECT revision FROM layer_revisions WHERE layer_id=? ORDER BY revision', (law,))] == [1, 2, 3, 4, 6]
    assert bound(store, s['defiant']) == [(law, 4)]
    assert read(s['j'])['pending'] == {'revision': 6, 'widenings': [], 'narrowings': [], 'too_large': [], 'baseline': 4}
```

`test_a_follower_never_takes_a_widening_even_behind_a_prose_revision` passes before this task: a follow acceptance
binds its own revision, as a pin does, until the walk exists. It guards the walk's widening stop, and Step 5's mutation
shows it bites.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py`
Expected: `2 failed, 16 passed`. Both fail at `assert bound(store, s['defiant']) == [(law, 4)]` with
`At index 0 diff: ('…', 3) != ('…', 4)`: the follower stays at revision 3. Test 29 passes (see above).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/acceptances.py`, replace `_accepted_pair` with:

```python
    def _accepted_pair(self, db, owner_id):
        """Spec Binding 2, the owner who neither signed the active charter nor is absent: the (layer_id, revision) their
        acceptance in force binds, or None. None while the acceptance's layer has no active revision: a withdrawn
        charter binds no ship, and the acceptance binds again if that layer is activated again (C15). A pin binds its
        revision; a follow binds where its walk stops (C21)."""
        held = self._acceptance_in_force(db, owner_id)
        if held is None:
            return None
        layer = db.execute('SELECT active_revision FROM layers WHERE id=?', (held['layer_id'],)).fetchone()
        if layer is None or layer['active_revision'] is None:
            return None
        if not held['follow']:
            return held['layer_id'], held['revision']
        return held['layer_id'], self._follow_walk(db, held)
```

and add after it:

```python
    def _follow_walk(self, db, held):
        """C21: from the revision a follow acceptance names, step through the layer's existing revision rows in order,
        one at a time, each compared with the revision binding the owner then. Stop before a row whose number is not
        exactly one more (only withdraw_layer advances resource_version without writing a revision, so a skipped number
        is a withdrawal), and before one that widens. The revision it stops at."""
        revision = held['revision']
        policy = self._charter_revision(db, held['layer_id'], revision)['policy']
        for row in db.execute('SELECT revision, snapshot FROM layer_revisions WHERE layer_id=? AND revision>? '
                              'ORDER BY revision', (held['layer_id'], revision)).fetchall():
            snapshot = json.loads(row['snapshot'])
            if row['revision'] != revision + 1 or snapshot.get('charter') is not True:
                break
            if widened_paths(policy, snapshot['policy']):
                break
            revision, policy = row['revision'], snapshot['policy']
        return revision
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py`
Expected: `18 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- drop `if widened_paths(policy, snapshot['policy']): break` → `test_a_follower_never_takes_a_widening_even_behind_a_prose_revision`
  (the widening rides in on revision 5);
- `revision = row['revision']` for `revision, policy = row['revision'], snapshot['policy']` (every revision compared
  with the one she accepted) → `test_a_follower_compares_each_revision_with_the_one_binding_them_then`;
- `if snapshot.get('charter') is not True:` for the line that also checks `row['revision'] != revision + 1` →
  `test_a_follower_is_never_carried_across_a_withdrawal`.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/tests/test_acceptances.py
git commit -m "Charter 4c: a follower steps one existing revision at a time, never across a widening or a withdrawal (R31, C21)"
```

---

### Task 5: Caps at re-activation, at a follower's next revision and at an owner's own activation (R33, C21, C23)

**Files:**
- Modify: `peer/superyak_peer/acceptances.py` (`MOVED`; `_accepted_pair`, `_follow_walk`; two methods after it)
- Modify: 4a's charter activation path (I12) and ordinary instructions activation path (I13); `layers.py` with
  Appendix A
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: Tasks 3-4 (`_owned_ships`, `_too_large`, `_follow_walk`); 4a's I6 (`over_caps`, `CAPS_REFUSAL`), I7
  (`_layers_for`), I8 (`_own_layers` with `replace`), I12, I13.
- Produces:
  - `Acceptances._accepted_pair(db, owner_id, replace=None)`; `Acceptances._follow_walk(db, held, replace=None) ->
    (revision, blocker_name | None)`, which also stops before a revision that would put one of the owner's ships over
    the caps.
  - `Acceptances._check_rebound_caps(db, layer_id) -> None` (409 `CAPS_REFUSAL` naming a ship) and
    `Acceptances._refuse_a_moved_charter(db, actor, key, snapshot) -> None` (409 `MOVED`), called from 4a's two
    activation paths.
  - Test helper: `own_layer(client, ship, body, title='Big') -> (layer_id, activation response)`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_acceptances.py`:

```python
def own_layer(client, ship, body, title='Big'):
    """One instructions layer of the caller's own for ship, activated: (its id, the activation's response)."""
    layer = client.post('/api/layers', json={'kind': 'instructions', 'title': title, 'body': body,
                                             'audience_users': [ship['id']]}).json()
    return layer['id'], client.post(f'/api/layers/{layer["id"]}/activate', json={'version': layer['version']})


@pytest.mark.parametrize('follow', [False, True])
def test_a_charter_activated_again_checks_the_caps_of_every_owner_it_binds_again(station, follow):
    """Test 33 (C23, R33): Jenn accepts revision 2, pinned or following; Andy withdraws; Jenn activates ten own layers
    while unbound; Andy's activation of the same layer would bind her again at revision 2, which her walk can't stop
    before, so it gets 409 naming her ship, and nothing is written."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    assert accept(s['j'], law, 2, follow=follow)[0] == 200
    withdraw(s['a'], law)
    own_layers(s['j'], s['defiant'], 10)
    layer = s['a'].get(f'/api/layers/{law}').json()
    refused = s['a'].post(f'/api/layers/{law}/activate', json={'version': layer['version'], 'confirm_widenings': []})
    assert (refused.status_code, refused.json()) == (409, {'error': 'Defiant would have more than 10 instruction layers or 48,000 bytes of them'})
    assert bound(store, s['rio']) == [] and s['a'].get(f'/api/layers/{law}').json()['active_revision'] is None


def test_a_revision_too_large_for_a_followers_ship_stops_the_follower_and_is_never_refused(station):
    """Test 33 (C21, C23): Jenn follows from revision 2 with about 47 KB of her own layers; Andy's larger revision 3
    activates, her ship stays at 2, and GET /api/charter shows 3 pending as too large for Defiant."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    assert accept(s['j'], law, 2, follow=True)[0] == 200
    for n in range(3):
        assert own_layer(s['j'], s['defiant'], 'b' * 15500, f'Big {n}')[1].status_code == 200
    assert sign(s['a'], law, body='c' * 1500) == 3
    assert bound(store, s['defiant'])[0] == (law, 2) and bound(store, s['rio']) == [(law, 3)]
    assert read(s['j'])['pending'] == {'revision': 3, 'widenings': [], 'narrowings': [], 'too_large': ['Defiant'], 'baseline': 2}


def test_an_owners_own_activation_never_moves_their_ships_to_another_charter_revision(station):
    """Test 33's last sentence (C23, R33), both ways. Back: Jenn's walk is at revision 3, near 48 KB with her own layers;
    one more own layer would leave 3 too large and move her ship back to 2, so it gets 409 naming the ship, and her ship
    stays at 3. Forward: with revision 4 too large for her, shrinking an own layer would move her ship to 4 without her
    accepting it, so that activation gets 409 too, and her ship stays at 3."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    assert accept(s['j'], law, 2, follow=True)[0] == 200
    sign(s['a'], law, body='c' * 2000)
    for n in range(3):
        assert own_layer(s['j'], s['defiant'], 'b' * 15000, f'Big {n}')[1].status_code == 200
    assert bound(store, s['defiant'])[0] == (law, 3)
    refused = own_layer(s['j'], s['defiant'], 'd' * 1000, 'One more')[1]
    assert refused.status_code == 409 and 'Defiant' in refused.json()['error']
    assert bound(store, s['defiant'])[0] == (law, 3) and len(bound(store, s['defiant'])) == 4
    big = bound(store, s['defiant'])[1][0]
    sign(s['a'], law, body='c' * 5000)  # revision 4: too large for Defiant with her 45 KB, so her walk stays at 3
    assert bound(store, s['defiant'])[0] == (law, 3)
    layer = s['j'].get(f'/api/layers/{big}').json()
    smaller = s['j'].put(f'/api/layers/{big}', json={'version': layer['version'], 'body': 'small'}).json()
    refused = s['j'].post(f'/api/layers/{big}/activate', json={'version': smaller['version']})
    assert (refused.status_code, refused.json()) == (409, {'error': 'Defiant would be bound by charter revision 4 instead of revision 3'})
    assert bound(store, s['defiant'])[0] == (law, 3)
```

The sizes: three own layers of 15,500 characters with a short charter block render to about 47,000 bytes, and a
revision 1,500 characters longer passes 48,000; three of 15,000 with a 2,000-character revision render to about 47,400,
and one more layer of 1,000 passes it, as does a 5,000-character revision.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_instructions.py`
Expected: `4 failed, 41 passed` on Appendix A. Both re-activation cases with `assert (200, {…}) == (409, {'error': …})`
(the activation goes through); the too-large test at `assert bound(store, s['defiant'])[0] == (law, 2)` with `3 != 2`
(the follower moved onto the revision too large for her); the own-activation test at the line after revision 4 with
`4 != 3` (the walk took revision 4, which is too large). Its backward half already passes on Appendix A: 4a's caps check
refuses one more own layer, naming Defiant.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/acceptances.py`, after `REASON_SHAPE = 'A reason is one line of at most 200 characters'` add:

```python
MOVED = '{ship} would be bound by charter revision {after} instead of revision {before}'
```

Replace `_accepted_pair` with:

```python
    def _accepted_pair(self, db, owner_id, replace=None):
        """Spec Binding 2, the owner who neither signed the active charter nor is absent: the (layer_id, revision) their
        acceptance in force binds, or None. None while the acceptance's layer has no active revision: a withdrawn
        charter binds no ship, and the acceptance binds again if that layer is activated again (C15). A pin binds its
        revision; a follow binds where its walk stops (C21). replace is _own_layers' (an own activation being checked)."""
        held = self._acceptance_in_force(db, owner_id)
        if held is None:
            return None
        layer = db.execute('SELECT active_revision FROM layers WHERE id=?', (held['layer_id'],)).fetchone()
        if layer is None or layer['active_revision'] is None:
            return None
        if not held['follow']:
            return held['layer_id'], held['revision']
        return held['layer_id'], self._follow_walk(db, held, replace)[0]
```

Replace `_follow_walk` with:

```python
    def _follow_walk(self, db, held, replace=None):
        """C21: from the revision a follow acceptance names, step through the layer's existing revision rows in order,
        one at a time, each compared with the revision binding the owner then. Stop before a row whose number is not
        exactly one more (only withdraw_layer advances resource_version without writing a revision, so a skipped number
        is a withdrawal), before one that widens, and before one that would put one of the owner's ships over the caps
        with that ship's own layers (C23). (the revision it stops at, the name of the ship that stopped it at the caps
        or None)."""
        revision = held['revision']
        policy = self._charter_revision(db, held['layer_id'], revision)['policy']
        ships = self._owned_ships(db, held['person_id'])
        for row in db.execute('SELECT revision, snapshot FROM layer_revisions WHERE layer_id=? AND revision>? '
                              'ORDER BY revision', (held['layer_id'], revision)).fetchall():
            snapshot = json.loads(row['snapshot'])
            if row['revision'] != revision + 1 or snapshot.get('charter') is not True:
                break
            if widened_paths(policy, snapshot['policy']):
                break
            charter = self._layers_for(db, [(held['layer_id'], row['revision'])])
            blocker = next((ship for ship in ships if over_caps(charter + self._own_layers(db, ship, replace))), None)
            if blocker is not None:
                return revision, safe_line(blocker['name'])
            revision, policy = row['revision'], snapshot['policy']
        return revision, None
```

and add after it:

```python
    def _check_rebound_caps(self, db, layer_id):
        """C23 from 4c, at a charter activation, before the new revision is written: activating a layer that is
        withdrawn now binds again every owner whose acceptance in force names it, pinned or following, at that
        acceptance's own revision, which a follower's walk can't stop before. Each of their ships must fit it with its
        own layers, or 409 naming the ship. A layer that is active now binds no one again: a pin stays where it is, and
        a revision a follower would move to stops that follower instead (C21)."""
        layer = db.execute('SELECT active_revision FROM layers WHERE id=?', (layer_id,)).fetchone()
        if layer is None or layer['active_revision'] is not None:
            return
        for held in db.execute('SELECT * FROM charter_acceptances WHERE layer_id=? AND revoked IS NULL ORDER BY created, id',
                               (layer_id,)).fetchall():
            too_large = self._too_large(db, held['person_id'], layer_id, held['revision'])
            if too_large:
                raise Problem(409, CAPS_REFUSAL.format(ship=too_large[0]))

    def _refuse_a_moved_charter(self, db, actor, key, snapshot):
        """C23's last check, at an owner's own activation of an instructions layer: their follow walk, which reads
        their own layers, must stop at the same revision with the new snapshot as without it, or 409 naming the ship
        whose caps made the difference. A pin, a withdrawn charter and the signer's own ships never move."""
        held = self._acceptance_in_force(db, actor)
        if held is None or not held['follow']:
            return
        layer = db.execute('SELECT active_revision FROM layers WHERE id=?', (held['layer_id'],)).fetchone()
        if layer is None or layer['active_revision'] is None:
            return
        replace = {'layer_id': key, 'snapshot': snapshot, 'created': self.clock(), 'revision': 0}
        (before, held_back), (after, stopped) = self._follow_walk(db, held), self._follow_walk(db, held, replace)
        if before != after:
            raise Problem(409, MOVED.format(ship=stopped or held_back, after=after, before=before))
```

In 4a's charter activation (I12), after `require_confirmed(...)` and before the new revision row is written, while the
layer's `active_revision` is still the one before this activation, add:

```python
        self._check_rebound_caps(db, key)  # charter 4c (C23): owners whose acceptance binds again, before the write
```

With Appendix A that is in `Layers._activate_charter`, between `snapshot['resolved_space_users'], snapshot['audience_notes'] = {}, []`
and `revision = row['resource_version'] + 1`.

In 4a's ordinary instructions activation (I13), right after `self._check_instruction_caps(db, actor, key, snapshot)`,
at its indentation, add:

```python
                self._refuse_a_moved_charter(db, actor, key, snapshot)  # charter 4c (C23): never another charter revision
```

With Appendix A that is in `Layers.activate_layer`, inside `if snapshot.get('kind') == 'instructions':`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_instructions.py`
Expected: `45 passed` on Appendix A.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- drop the `_check_rebound_caps` call → `test_a_charter_activated_again_checks_the_caps_of_every_owner_it_binds_again[False]`
  (and `[True]`): re-bound ships left unchecked;
- `... AND revoked IS NULL AND follow=0 ORDER BY ...` in `_check_rebound_caps` (pins only) → `[True]`: a re-bound
  follower left unchecked;
- drop `if blocker is not None: return revision, safe_line(blocker['name'])` → `test_a_revision_too_large_for_a_followers_ship_stops_the_follower_and_is_never_refused`;
- drop the `_refuse_a_moved_charter` call → `test_an_owners_own_activation_never_moves_their_ships_to_another_charter_revision`
  (the forward half: shrinking a layer moves her to revision 4 in silence);
- `self._own_layers(db, ship)` for `self._own_layers(db, ship, replace)` in `_follow_walk` → the same test (the walk
  can't see the activation being checked).

(Dropping `_check_rebound_caps`' early return for a layer that is active survives: see Known limits.)

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/superyak_peer/layers.py peer/tests/test_acceptances.py
git commit -m "Charter 4c: caps for owners bound again, a follower's next revision, and an owner's own layers (R33, C23)"
```

(Add whichever file holds 4a's activation paths, if not `layers.py`.)

---

### Task 6: Past charter revisions for the people who accepted them (C26, R19's 4c part, test 19's 4c part)

**Files:**
- Modify: `peer/superyak_peer/acceptances.py` (`_acceptance_names` before `_accepted_pair`)
- Modify: 4a's `Signatures._may_read_charter_revision` (I14; `signatures.py` with Appendix A)
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: Task 5's `_accepted_pair`; 4a's I14.
- Produces: `Acceptances._acceptance_names(db, person_id, layer_id, revision) -> bool`: one of the person's acceptances,
  in force or ended, was made at that revision, or their acceptance in force binds it now through its walk.

- [ ] **Step 1: Write the failing test**

Append to `peer/tests/test_acceptances.py`:

```python
def test_a_past_charter_revision_goes_to_its_signer_and_to_people_whose_acceptance_names_it(station):
    """Test 19's 4c part (C26, R19): revision 2 for Jenn, who accepted it and has since accepted 3; revision 5 for
    Stanley, a follower whose walk stopped there while his acceptance names 4; the active revision for anyone. Everyone
    else gets 404, the answer a revision that doesn't exist gets."""
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    sign(s['a'], law, body='Second.')
    assert accept(s['j'], law, 2)[0] == 200
    sign(s['a'], law, body='Third.')
    assert accept(s['j'], law, 3)[0] == 200
    sign(s['a'], law, body='Fourth.')
    assert accept(s['s'], law, 4, follow=True)[0] == 200
    sign(s['a'], law, body='Fifth.')
    sign(s['a'], law, policy=DEPTH, confirm=['delegation.max_depth'])  # revision 6 widens: Stanley's walk stays at 5
    assert bound(store, s['enterprise']) == [(law, 5)]

    def status(client, revision):
        return client.get(f'/api/layers/{law}/revisions/{revision}/signed').status_code
    expected = {  # revision: (Andy, Jenn, Stanley, the organizer)
        1: (200, 404, 404, 404), 2: (200, 200, 404, 404), 3: (200, 200, 404, 404), 4: (200, 404, 200, 404),
        5: (200, 404, 200, 404), 6: (200, 200, 200, 200), 9: (404, 404, 404, 404)}
    for revision, statuses in expected.items():
        assert tuple(status(client, revision) for client in (s['a'], s['j'], s['s'], s['o'])) == statuses, revision
    signed = s['j'].get(f'/api/layers/{law}/revisions/2/signed').json()
    assert signed['record']['body'] == 'Second.' and signed['record']['policy'] is not None
    assert verify_record(card_of(store._station_identity()), signed['record'], signed['signature'])
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_signatures.py`
Expected: `1 failed, 50 passed` on Appendix A: `AssertionError: 2` with `(200, 404, 404, 404) == (200, 200, 404, 404)`
(Jenn can't read the revision she accepted).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/acceptances.py`, insert before `_accepted_pair`:

```python
    def _acceptance_names(self, db, person_id, layer_id, revision):
        """C26: whether the person's acceptance names this charter revision now or did before: one of their acceptances,
        in force or ended, was made at it, or their acceptance in force binds it now through its follow walk."""
        if db.execute('SELECT 1 FROM charter_acceptances WHERE person_id=? AND layer_id=? AND revision=?',
                      (person_id, layer_id, revision)).fetchone():
            return True
        return self._accepted_pair(db, person_id) == (layer_id, revision)
```

In 4a's `Signatures._may_read_charter_revision` (I14), the answer gains the acceptance. With Appendix A, replace

```python
        return layer['active_revision'] == revision
```

with

```python
        return layer['active_revision'] == revision or self._acceptance_names(db, actor, layer['id'], revision)  # charter 4c
```

`revision_signed` asks it only for a charter revision and a caller who isn't the owner, and answers 404 when it says
no, the same 404 a revision that doesn't exist gets (Routes `/signed`).

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_signatures.py`
Expected: `51 passed` on Appendix A.

- [ ] **Step 5: Check the test bites**

Apply each alone, run `tests/test_acceptances.py`, see `test_a_past_charter_revision_goes_to_its_signer_and_to_people_whose_acceptance_names_it`
fail, restore:
- `return False` for the last line of `_acceptance_names` (a follower's walk not counted: Stanley can't read 5);
- `... AND revision=? AND revoked IS NULL` (an ended acceptance not counted: Jenn can't read 2);
- `WHERE (person_id=? OR 1) AND ...` (anyone's acceptance counts: the organizer reads 2).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/acceptances.py peer/superyak_peer/signatures.py peer/tests/test_acceptances.py
git commit -m "Charter 4c: a past charter revision's signature goes to the people whose acceptance names it (C26)"
```

---

### Task 7: The restore reconcile treats acceptances by person (R34, C27, test 26's reconcile)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`COMPARED`, `:380-387`; four functions before `_member_name`; the report's
  keys and two steps in `reconcile`, `:879`, `:910`, `:913`; three report lines in `describe_reconcile`, before
  `if report['removed']:`, `:956`)
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: `_has`, `_usable`, the step signature `(db, old, now, report)`, `describe_reconcile` (backups.py); Task 1's
  backfill (it signs the `restored` ends at the next start); test helpers `staged`, `reconcile` (`test_restore.py`),
  `report_line` (`test_grants.py`). Nothing from 4a beyond the routes the tests use.
- Produces: `backups.ACCEPTANCE_COMPARED`; steps `_keep_every_acceptance` (no usable replaced file) and
  `_reconcile_acceptances_like_replaced` (with one); `report['acceptances'] = {'ended': [(username, revision,
  follow)], 'kept': [...], 'lost': [(username, revision, follow, None | (revision, follow))]}` and its three report
  lines. Test helper `in_force(path) -> dict`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_acceptances.py`:

```python
def in_force(path):
    """{acceptance id: (person_id, revision, follow, revoked, revoked_by, revoke_reason, revocation_signature)}."""
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(path)) as db:
        return {row[0]: row[1:] for row in db.execute('SELECT id, person_id, revision, follow, revoked, revoked_by, '
                                                      'revoke_reason, revocation_signature FROM charter_acceptances')}


def test_the_reconcile_treats_acceptances_by_person_and_never_adds_one(station, tmp_path, capsys):
    """Test 34 (C27, R34), with a replaced file: Jenn re-accepted after the copy, so the copy's acceptance stays and the
    report names her with the revision she had; the organizer left after it, so the copy's acceptance ends with reason
    `restored` and no person, and the next start signs that end; Stanley accepted only after the copy, so no row is
    added and the report names him. A grant revoked after the copy is revoked as G13 says."""
    import shutil
    from test_grants import report_line
    from test_restore import reconcile as run_reconcile, staged
    s = station
    store, law, clock = s['store'], s['law'], s['clock']
    room = store.create_room(s['andy']['id'], 'Ops', [s['jenn']['id']])
    grant = store.make_grant(s['andy']['id'], s['jenn']['id'], [s['rio']['id']], [room['id']], 24, 5)['id']
    sign(s['a'], law)
    jenn_then = accept(s['j'], law, 1)[1]['acceptance']['id']
    organizer_then = accept(s['o'], law, 1)[1]['acceptance']['id']
    copy = staged(tmp_path, store)
    clock[0] += 60  # the station moves on after the copy
    sign(s['a'], law, body='Second.')
    assert accept(s['j'], law, 2, follow=True)[0] == 200
    assert s['o'].post('/api/charter/leave', json={}).status_code == 200
    assert accept(s['s'], law, 2)[0] == 200
    store.revoke_grant(s['andy']['id'], grant, 'Not this week')
    before = in_force(copy)
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    after = in_force(copy)
    assert set(after) == set(before) == {jenn_then, organizer_then}  # no row added, none removed
    assert after[jenn_then] == before[jenn_then] and after[jenn_then][3] is None  # kept, in force
    assert after[organizer_then][3] is not None and after[organizer_then][4:] == (None, 'restored', None)
    assert report_line(out, 'Charter acceptances ended') == 'Charter acceptances ended, as the replaced file holds none in force for them: organizer (revision 1, pinned).'
    assert report_line(out, 'Charter acceptances kept') == 'Charter acceptances kept: doctor (revision 1, pinned).'
    assert report_line(out, 'Charter acceptances lost') == (
        'Charter acceptances lost: in the replaced file, not in this copy, and a restore never adds one: doctor had '
        'revision 2, following, and is back at revision 1, pinned; family had revision 2, pinned, and is bound by none. '
        'Ask them to accept again on the Charter page.')
    assert report_line(out, 'Grants revoked: ').startswith(f'Grants revoked: #{grant[:4]} (patient to doctor, as in the replaced file)')
    live = tmp_path / 'live'
    live.mkdir(mode=0o700)
    shutil.copyfile(store.data_dir / 'identity.json', live / 'identity.json')  # the identity stays put (runbook step 6)
    shutil.copyfile(copy, live / 'peer.sqlite3')
    from superyak_peer.db import Store
    started = Store(live)
    signature = in_force(live / 'peer.sqlite3')[organizer_then][6]
    assert verify_record(card_of(started._station_identity()), records(started, organizer_then)[1], signature)


def test_without_a_usable_replaced_file_the_reconcile_keeps_every_acceptance(station, tmp_path, capsys):
    """Test 34 and test 26 (C27): with no replaced file the reconcile ends no acceptance, and lists each one it kept."""
    from test_grants import report_line
    from test_restore import reconcile as run_reconcile, staged
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    assert accept(s['j'], law, 1)[0] == 200 and accept(s['s'], law, 1, follow=True)[0] == 200
    copy = staged(tmp_path, store)
    before = in_force(copy)
    code, out, err = run_reconcile(capsys, '--db', copy)
    assert code == 0, err
    assert in_force(copy) == before
    assert report_line(out, 'Charter acceptances kept') == 'Charter acceptances kept: doctor (revision 1, pinned); family (revision 1, following).'
    assert report_line(out, 'Charter acceptances ended') is None and report_line(out, 'Charter acceptances lost') is None


def test_a_copy_from_before_4c_reconciles_and_names_every_acceptance_it_lost(station, tmp_path, capsys):
    """Test 26 (R34): a copy without the charter_acceptances table reconciles without error, says it skipped the table,
    and names each acceptance in force in the replaced file, which the restore loses. A replaced file without the table
    is treated as absent, as for any table COMPARED lists."""
    import shutil
    import sqlite3
    from contextlib import closing
    from test_grants import report_line
    from test_restore import reconcile as run_reconcile, staged
    s = station
    store, law = s['store'], s['law']
    sign(s['a'], law)
    assert accept(s['j'], law, 1)[0] == 200
    copy = staged(tmp_path, store)
    with closing(sqlite3.connect(copy)) as db:
        db.execute('DROP TABLE charter_acceptances')
        db.commit()
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    assert 'Skipped, because this copy lacks them: charter_acceptances.id' in out
    assert report_line(out, 'Charter acceptances lost') == (
        'Charter acceptances lost: in the replaced file, not in this copy, and a restore never adds one: doctor had '
        'revision 1, pinned, and is bound by none. Ask them to accept again on the Charter page.')
    second = staged(tmp_path, store, 'replaced-20261018-120000')
    replaced = second.parent / 'peer.sqlite3'
    shutil.copyfile(store.db_path, replaced)
    with closing(sqlite3.connect(replaced)) as db:
        db.execute('DROP TABLE charter_acceptances')
        db.commit()
    code, out, err = run_reconcile(capsys, '--db', second, '--replaced', replaced)
    assert code == 0, err
    assert 'The replaced file was treated as absent (it lacks tables or columns the copy has: ' in out
    assert report_line(out, 'Charter acceptances kept') == 'Charter acceptances kept: doctor (revision 1, pinned).'
```

The usernames in the expected lines are the conftest's: `doctor` is Jenn, `family` is Stanley, `patient` is Andy.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_restore.py tests/test_grants.py`
Expected: `3 failed, 107 passed` on Appendix A. The first fails at `assert after[organizer_then][3] is not None` (`assert
(None is not None)`: nothing ended); the second at its kept line (`assert None == 'Charter acceptances kept: doctor
(revision 1, pinned); family (revision 1, following).'`); the third at `'Skipped, because this copy lacks them:
charter_acceptances.id' in out` (no step reads the table yet).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/backups.py`, `COMPARED`'s last line,

```python
            'budget_uses.ticket_id', 'budget_uses.created')
```

becomes

```python
            'budget_uses.ticket_id', 'budget_uses.created',
            # charter step 4, C27 and R34: what the acceptances step reads from the replaced file
            'charter_acceptances.id', 'charter_acceptances.person_id', 'charter_acceptances.revision',
            'charter_acceptances.follow', 'charter_acceptances.revoked', 'charter_acceptances.revoked_by',
            'charter_acceptances.revoke_reason')
```

Before `def _member_name(db, table, member):` (after `_add_budget_uses_like_replaced`, with two blank lines on each
side) insert:

```python
ACCEPTANCE_COMPARED = ('charter_acceptances.id', 'charter_acceptances.person_id', 'charter_acceptances.revision',
                       'charter_acceptances.follow', 'charter_acceptances.revoked', 'charter_acceptances.revoked_by',
                       'charter_acceptances.revoke_reason')


def _acceptances_in_force(connection):
    """C27: each person's acceptance in force, {person_id: (id, revision, follow)}."""
    return {row[0]: (row[1], row[2], bool(row[3])) for row in connection.execute(
        'SELECT person_id, id, revision, follow FROM charter_acceptances WHERE revoked IS NULL')}


def _username(db, old, user_id):
    """A person's username from the copy, or from the replaced file for an account made after the copy."""
    for connection in (db, old):
        if connection is not None and _has(connection, 'users.username'):
            row = connection.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
            if row:
                return row[0]
    return user_id[:6]


def _keep_every_acceptance(db, old, now, report):
    """C27, without a usable replaced file: every acceptance in force is kept (ending one takes law away from that
    owner's ships, the opposite of the reconcile's purpose), and the report lists each."""
    if not _usable(db, None, report, *ACCEPTANCE_COMPARED):
        return
    here = _acceptances_in_force(db)
    report['acceptances']['kept'] = sorted((_username(db, None, person), revision, follow)
                                           for person, (_, revision, follow) in here.items())


def _reconcile_acceptances_like_replaced(db, old, now, report):
    """C27, with a usable replaced file: by person, never by row, and never adding one. A person's acceptance in
    force here is ended now, with reason `restored` and no person, when the replaced file holds none in force for that
    person, and kept otherwise. Each person whose acceptance in force there is not the one here is listed as lost: one
    with none here (they accepted only after the copy, and are bound by none) and one whose row here is another (they
    accepted again after it, and are back at the copy's revision and follow). The station signs those ends at its next
    start (signatures.py), as it does the grants' revocations. A copy from before 4c has no table: it is skipped, and
    every acceptance in force in the replaced file is listed as lost."""
    there = _acceptances_in_force(old) if _has(old, *ACCEPTANCE_COMPARED) else {}
    here = _acceptances_in_force(db) if _usable(db, old, report, *ACCEPTANCE_COMPARED) else {}
    for person, (key, revision, follow) in sorted(here.items(), key=lambda item: _username(db, old, item[0])):
        line = (_username(db, old, person), revision, follow)
        if person in there:
            report['acceptances']['kept'].append(line)
        else:
            db.execute("UPDATE charter_acceptances SET revoked=?, revoked_by=NULL, revoke_reason='restored' WHERE id=?",
                       (now, key))
            report['acceptances']['ended'].append(line)
    for person, (key, revision, follow) in sorted(there.items(), key=lambda item: _username(db, old, item[0])):
        if person not in here:
            report['acceptances']['lost'].append((_username(db, old, person), revision, follow, None))
        elif here[person][0] != key:
            report['acceptances']['lost'].append((_username(db, old, person), revision, follow, here[person][1:]))
```

In `reconcile`, the report's last line,

```python
              'not_compared': [], 'grants': []}
```

becomes

```python
              'not_compared': [], 'grants': [], 'acceptances': {'ended': [], 'kept': [], 'lost': []}}
```

after `                _revoke_every_grant(db, old, now, report)` add, at its indentation,

```python
                _keep_every_acceptance(db, old, now, report)
```

and in the steps run with a replaced file, `_unpair_like_replaced, _report_differences):` becomes
`_reconcile_acceptances_like_replaced, _unpair_like_replaced, _report_differences):`.

In `describe_reconcile`, before `    if report['removed']:` insert:

```python
    def accepted(name, revision, follow):
        return f'{safe_line(name)} (revision {revision}, {"following" if follow else "pinned"})'

    def lost(name, revision, follow, now):
        return (f'{safe_line(name)} had revision {revision}, {"following" if follow else "pinned"}, and is '
                + ('bound by none' if now is None else f'back at revision {now[0]}, {"following" if now[1] else "pinned"}'))
    acceptances = report['acceptances']
    if acceptances['ended']:
        lines.append('Charter acceptances ended, as the replaced file holds none in force for them: '
                     + '; '.join(accepted(*item) for item in acceptances['ended']) + '.')
    if acceptances['kept']:
        lines.append('Charter acceptances kept: ' + '; '.join(accepted(*item) for item in acceptances['kept']) + '.')
    if acceptances['lost']:
        lines.append('Charter acceptances lost: in the replaced file, not in this copy, and a restore never adds one: '
                     + '; '.join(lost(*item) for item in acceptances['lost']) + '. Ask them to accept again on the Charter page.')
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py tests/test_restore.py tests/test_grants.py`
Expected: `110 passed` on Appendix A. `test_every_table_is_either_reconciled_or_named_coordination` still reports no
"Skipped" or "Not compared" line: a station started today has the table in both files.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_acceptances.py`, see the named test fail, restore:
- `if key in {row[0] for row in there.values()}:` for `if person in there:` (by row, not by person) →
  `test_the_reconcile_treats_acceptances_by_person_and_never_adds_one` (Jenn's copy row ends, leaving her unbound);
- drop the `elif here[person][0] != key:` branch → the same test (her lost re-acceptance passes in silence);
- `revoked_by=person_id` for `revoked_by=NULL` → the same test;
- drop the `_keep_every_acceptance(db, old, now, report)` line → `test_without_a_usable_replaced_file_the_reconcile_keeps_every_acceptance`;
- `COMPARED` without its seven `charter_acceptances` entries → `test_a_copy_from_before_4c_reconciles_and_names_every_acceptance_it_lost`
  (a replaced file without the table is compared, not treated as absent);
- `if not _usable(db, old, report, *ACCEPTANCE_COMPARED): return` before reading `here` (a copy from before 4c lists no
  one) → the same test.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/backups.py peer/tests/test_acceptances.py
git commit -m "Charter 4c: the restore reconcile keeps or ends acceptances by person and names those it lost (R34, C27)"
```

---

### Task 8: The 500-step binding oracle (test 35)

**Files:**
- Test: `peer/tests/test_acceptances.py`

**Interfaces:**
- Consumes: everything Tasks 1-5 built, through the routes only, and `_binding_layers` (I9) to read each ship's binding;
  the `env` fixture's four people (`patient` and `organizer` sign; `doctor` and `family` own ships and accept; every one
  of them can accept the other signer's charter); test helpers `super_admin`, `new_charter`, `docked`.
- Produces: `oracle_widenings(before, after) -> list[str]` and `as_policy(policy) -> dict` (the oracle's own policies:
  `max_depth`, `builds`, `direct`, `people`), `BIG`, `DEFAULTS`.

The oracle is the spec's Binding, written again without the station's code: the charter pair (a resident or the active
charter's signer: its active revision; an owner who accepted: the pin, or the walk over existing revision numbers that
stops at a gap, a widening, or caps), then the owner's own layers by creation; caps are more than 10 layers or 4 `BIG`
bodies (four of 12,000 characters pass 48,000 bytes; three with seven small layers don't). Each step is one random act:
a signer signs (often prose only, so followers move; sometimes the signer whose charter isn't active, for the 409), the
active charter is withdrawn, someone accepts (pinned or following) or leaves, an owner activates a new own layer,
activates one again with the other size, or withdraws one. The oracle predicts each answer's status and every ship's
binding after it, and its last assertion checks that each kind of event happened at least once, so no comparison is
vacuous.

- [ ] **Step 1: Write the test**

Append to `peer/tests/test_acceptances.py`:

```python
BIG = 'B' * 12000  # four of these in one ship's blocks pass 48,000 bytes; three with seven small layers stay under
DEFAULTS = {'max_depth': 3, 'builds': 20, 'direct': True, 'people': None}  # the oracle's view of spec A's defaults


def oracle_widenings(before, after):
    """Spec Data's widened paths for the oracle's policies, computed without the station's code."""
    paths = []
    if after['max_depth'] > before['max_depth']:
        paths.append('delegation.max_depth')
    if after['builds'] > before['builds']:
        paths.append('budgets.builds_per_ship_per_day')
    if after['direct'] and not before['direct']:
        paths.append('delegation.delegable:direct')
    if before['people'] is not None and after['people'] is None:
        paths.append('grantees')
    if before['people'] is not None and after['people'] is not None:
        paths += [f'grantees.people:{person}' for person in sorted(set(after['people']) - set(before['people']))]
    return sorted(paths)


def as_policy(policy):
    return {'version': 1, 'delegation': {'max_depth': policy['max_depth'], 'delegable': ['direct'] if policy['direct'] else []},
            'budgets': {'builds_per_ship_per_day': policy['builds']},
            'grantees': None if policy['people'] is None else {'people': list(policy['people'])}}


def test_charter_binding_matches_an_independent_reading_over_500_seeded_steps(env):
    """Test 35 (spec A Testing 2's 500 cases; C17, C21-C23): two signers, two other owners, a resident, pins, follows,
    leaving, withdrawals, re-activations, and owners' own layers near the caps, each charter revision a random policy.
    After every step each ship's binding is exactly what spec Binding says, computed here without the station's code,
    and every step answers 409 exactly when this reading says so: an own activation that would break the caps or move a
    ship's charter pair, an acceptance too large for one of the person's ships, a charter activation too large for a
    ship it binds (the signer's, a resident, or one bound again after a withdrawal)."""
    import random
    from collections import Counter
    app, clients, users, clock = env
    store, rng = app.state.store, random.Random(20261015)
    andy, doctor, organizer, family = (user['id'] for user in users)
    client = dict(zip((andy, doctor, organizer, family), clients))
    super_admin(store, users[0])
    super_admin(store, users[2])
    ships_of, owner_of = {person: [] for person in client}, {}
    for person, name in ((andy, 'a-1'), (doctor, 'd-1'), (doctor, 'd-2'), (organizer, 'o-1'), (family, 'f-1')):
        ship, _ = docked(store, person, name)
        ships_of[person].append(ship['id'])
        owner_of[ship['id']] = person
    odo = store.create_station_ship('odo', 'Odo')['id']
    owner_of[odo] = None
    charters = {}  # layer_id: {owner, revs: {number: (policy, big)}, next, active}
    for person in (andy, organizer):
        charters[new_charter(client[person], title=f'Charter {person[:4]}')['id']] = {'owner': person, 'revs': {}, 'next': 1, 'active': None}
    held = {person: None for person in client}  # person: (layer_id, revision, follow)
    own = {}  # layer_id: {owner, audience, big, active, rev, next, created}
    seen = Counter()

    def active():
        return next(((layer, ch['active']) for layer, ch in charters.items() if ch['active'] is not None), None)

    def big_of(pair):
        return charters[pair[0]]['revs'][pair[1]][1]

    def own_for(ship, layers):
        found = [(entry['created'], layer, entry['rev'], entry['big']) for layer, entry in layers.items()
                 if entry['active'] and ship in entry['audience']]
        return [(layer, rev, big) for created, layer, rev, big in sorted(found)]

    def over(ship, pair, layers):
        mine = own_for(ship, layers)
        count = len(mine) + (pair is not None)
        bigs = sum(big for _, _, big in mine) + (big_of(pair) if pair else 0)
        return count > 10 or bigs >= 4

    def walk(person, layers, note=False):
        layer, revision, follow = held[person]
        ch = charters[layer]
        if ch['active'] is None:
            return None
        if not follow:
            return layer, revision
        for number in sorted(n for n in ch['revs'] if n > revision):
            why = ('withdrawal' if number != revision + 1 else
                   'widening' if oracle_widenings(ch['revs'][revision][0], ch['revs'][number][0]) else
                   'caps' if any(over(ship, (layer, number), layers) for ship in ships_of[person]) else None)
            if why:
                seen['walk stopped at a ' + why] += note
                break
            revision = number
            seen['walk moved'] += note
        return layer, revision

    def pair_for(ship, layers, note=False):
        current, owner = active(), owner_of[ship]
        if owner is None or (current and charters[current[0]]['owner'] == owner):
            return current
        return walk(owner, layers, note) if held[owner] else None

    def binding(ship, note=False):
        pair = pair_for(ship, own, note)
        return ([pair] if pair else []) + [(layer, rev) for layer, rev, _ in own_for(ship, own)]

    def random_policy():
        return {'max_depth': rng.choice([2, 3, 4]), 'builds': rng.choice([10, 20, 30]), 'direct': rng.random() < 0.6,
                'people': rng.choice([None, None, (doctor,), (doctor, family)])}

    def own_step(person, layer, big, audience):
        """The expected answer to an own activation (C23), with the layers as they would be after it."""
        after = {key: dict(entry) for key, entry in own.items()}
        entry = after.setdefault(layer, {'owner': person, 'next': 1})
        entry.update(audience=audience, big=big, active=True, rev=entry['next'], created=clock[0])
        entry['next'] += 1
        caps = any(over(ship, pair_for(ship, own), after) for ship in audience)
        moved = any(pair_for(ship, own) != pair_for(ship, after) for ship in ships_of[person])
        seen['own refused: caps' if caps else 'own refused: moved' if moved else 'own activated'] += 1
        return (409 if caps or moved else 200), after

    for step in range(500):
        clock[0] += 1
        kind = rng.choices(['sign', 'withdraw', 'accept', 'leave', 'own', 'again', 'unown'], [18, 4, 14, 3, 24, 20, 17])[0]
        current = active()
        if kind == 'sign':
            signer = charters[current[0]]['owner'] if current and rng.random() < 0.9 else rng.choice([andy, organizer])
            layer = next(key for key, ch in charters.items() if ch['owner'] == signer)
            baseline = charters[current[0]]['revs'][current[1]][0] if current else DEFAULTS
            ch, big = charters[layer], rng.random() < 0.4
            last = ch['revs'][max(ch['revs'])][0] if ch['revs'] else DEFAULTS
            policy = dict(last) if rng.random() < 0.5 else random_policy()  # often prose only, so a follower may move
            if current and current[0] != layer:
                expected = 409
                seen['sign refused: another charter'] += 1
            else:
                number = ch['next']
                rebound = ch['active'] is None and any(
                    over(ship, (layer, acceptance[1]), own) for person, acceptance in held.items()
                    if acceptance and acceptance[0] == layer for ship in ships_of[person])
                ch['revs'][number], was = (policy, big), ch['active']
                ch['active'] = number
                signers = any(over(ship, (layer, number), own) for ship in ships_of[signer] + [odo])
                expected = 409 if rebound or signers else 200
                seen['sign refused: bound again' if rebound else 'sign refused: caps' if signers else 'signed'] += 1
                if expected == 409:
                    del ch['revs'][number]
                    ch['active'] = was
                else:
                    ch['next'] += 1
            draft = client[signer].get(f'/api/layers/{layer}').json()
            saved = client[signer].put(f'/api/layers/{layer}', json={'version': draft['version'], 'body': BIG if big else f'Rule {step}.',
                                                                    'policy': as_policy(policy)}).json()
            answer = client[signer].post(f'/api/layers/{layer}/activate', json={'version': saved['version'],
                                         'confirm_widenings': oracle_widenings(baseline, policy)})
        elif kind == 'withdraw' and current:
            ch = charters[current[0]]
            confirm = oracle_widenings(ch['revs'][current[1]][0], DEFAULTS)
            ch['active'], expected = None, 200
            ch['next'] += 1
            seen['withdrawn'] += 1
            answer = client[ch['owner']].post(f'/api/layers/{current[0]}/withdraw', json={'confirm_widenings': confirm})
        elif kind == 'accept' and current:
            person = rng.choice([p for p in client if p != charters[current[0]]['owner']])
            follow = rng.random() < 0.75
            mine = walk(person, own) if held[person] else None
            baseline = charters[mine[0]]['revs'][mine[1]][0] if mine else DEFAULTS
            policy = charters[current[0]]['revs'][current[1]][0]
            if held[person] == (current[0], current[1], follow):
                expected = 200
            elif any(over(ship, current, own) for ship in ships_of[person]):
                expected = 409
                seen['accept refused: caps'] += 1
            else:
                expected, held[person] = 200, (current[0], current[1], follow)
                seen['followed' if follow else 'pinned'] += 1
            answer = client[person].post('/api/charter/accept', json={'layer_id': current[0], 'revision': current[1], 'follow': follow,
                                                                      'confirm_widenings': oracle_widenings(baseline, policy)})
        elif kind == 'leave':
            person = rng.choice(list(client))
            expected = 200 if held[person] else 409
            held[person] = None
            answer = client[person].post('/api/charter/leave', json={})
        elif kind in ('own', 'again', 'unown'):
            person = rng.choices([andy, doctor, organizer, family], [1, 3, 1, 3])[0]  # mostly owners who accept
            theirs = [layer for layer, entry in own.items() if entry['owner'] == person]
            if kind == 'own' or not theirs:
                audience = [ship for ship in ships_of[person] if rng.random() < 0.7] or ships_of[person][:1]
                big = rng.random() < 0.45
                made = client[person].post('/api/layers', json={'kind': 'instructions', 'title': f'Own {step}', 'body': BIG if big else 'x',
                                                                 'audience_users': audience}).json()
                expected, after = own_step(person, made['id'], big, audience)
                answer = client[person].post(f'/api/layers/{made["id"]}/activate', json={'version': made['version']})
            elif kind == 'again':
                layer = rng.choice(theirs)
                big = not own[layer]['big']
                draft = client[person].get(f'/api/layers/{layer}').json()
                saved = client[person].put(f'/api/layers/{layer}', json={'version': draft['version'], 'body': BIG if big else 'x'}).json()
                expected, after = own_step(person, layer, big, own[layer]['audience'])
                answer = client[person].post(f'/api/layers/{layer}/activate', json={'version': saved['version']})
            else:
                layer = rng.choice(theirs)
                after = {key: dict(entry) for key, entry in own.items()}
                if after[layer]['active']:
                    after[layer]['active'] = False
                    after[layer]['next'] += 1
                expected = 200
                answer = client[person].post(f'/api/layers/{layer}/withdraw', json={})
            if expected == 200:
                own = after
        else:
            continue
        assert answer.status_code == expected, (step, kind, answer.text)
        for ship in owner_of:
            with store.transaction() as db:
                got = [(layer['layer_id'], layer['revision']) for layer in store._binding_layers(db, ship)]
            assert got == binding(ship, note=True), (step, kind, ship)
    assert min(seen[event] for event in (
        'signed', 'withdrawn', 'pinned', 'followed', 'walk moved', 'walk stopped at a widening', 'walk stopped at a caps',
        'walk stopped at a withdrawal', 'sign refused: caps', 'sign refused: bound again', 'sign refused: another charter',
        'accept refused: caps', 'own activated', 'own refused: caps', 'own refused: moved')) > 0, dict(seen)
```

- [ ] **Step 2: Run it**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_acceptances.py`
Expected: `27 passed`, the oracle in about 5 seconds. It passes as soon as it is written: it guards Tasks 2-5 as a
whole, and Step 4's mutations show it bites.

- [ ] **Step 3: Nothing to implement**

No production code changes in this task.

- [ ] **Step 4: Check the test bites**

Apply each alone, run `tests/test_acceptances.py::test_charter_binding_matches_an_independent_reading_over_500_seeded_steps`,
see it fail (each message names the step, its kind and the ship), restore:
- drop the walk's caps stop (`if blocker is not None: return ...`);
- drop the `_refuse_a_moved_charter` call;
- drop the `_check_rebound_caps` call;
- `if snapshot.get('charter') is not True:` for the walk's line that also checks `row['revision'] != revision + 1`
  (across a withdrawal);
- drop the caps check in `accept_charter`;
- `revision = row['revision']` for `revision, policy = row['revision'], snapshot['policy']`;
- drop `_accepted_pair`'s withdrawn-layer check;
- 4a's `_charter_pair` last statement back to `return None`.

- [ ] **Step 5: Commit**

```bash
git add peer/tests/test_acceptances.py
git commit -m "Charter 4c: the binding oracle over 500 seeded steps with pins, follows, withdrawals and caps (test 35)"
```

---

### Task 9: The Charter page (R35, test 37, test 26's grants page)

**Files:**
- Modify: `peer/superyak_peer/static/app.js` (`bindEditorIdentity` `:112`, `routeParts` `:142`, the sidebar `:165`, the
  page's functions before the board's one-write comment `:803`, `loadRoute` `:1090`, `render`'s view and title maps
  `:1117`, `:1137`, the submit, click and change handlers `:1769`, `:1886`, `:2043`)
- Modify: `peer/superyak_peer/static/app.css` (after `.grant-make form`, `:338`)
- Test: `peer/tests/test_browser.py`

**Interfaces:**
- Consumes: `GET /api/charter`, `POST /api/charter/accept`, `POST /api/charter/leave` (Task 3) and their shapes; the
  page's own helpers (`api`, `escapeHtml`, `formatDate`, `setFlash`, `identityKey`, `render`, `routeParts`, `navLink`,
  `showLogin`); in the tests, `new_charter`, `sign`, `super_admin`, `own_layers` (`test_acceptances.py`).
- Produces: route `#charter` and the sidebar's "Charter" link; `state.charter`, `state.charterAsk`,
  `state.charterSaving`; `loadCharter`, `lineDiff(before, after) -> [{kind, text}]`, `diffMarkup`, `policyMarkup`,
  `wideningWords`, `charterView`, `charterWrite`, `acceptCharter`. Test helpers `signed_in_client(peer, username)` (an
  API session on the browser test's station) and `charter_station(browser_peer)`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_browser.py`:

```python
def signed_in_client(peer, username):
    """A person's API session on the browser test's station, through the same routes the page uses."""
    from fastapi.testclient import TestClient
    client = TestClient(peer["app"], base_url=peer["base_url"])
    client.headers["origin"] = peer["base_url"]
    response = client.post("/api/login", json={"username": username, "password": peer["password"]})
    assert response.status_code == 200, response.text
    client.headers["x-csrf-token"] = response.json()["csrf_token"]
    return client


def charter_station(browser_peer):
    """Charter 4c's page (R35): the patient, a super admin whose display name is HTML, signs a charter whose title is HTML
    and whose policy widens max_depth; the doctor, whose display name is HTML too, owns defiant. (store, users, ship,
    the patient's API client, the charter's layer id)."""
    from test_acceptances import new_charter, sign, super_admin
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    super_admin(store, users["patient"])
    started = store.start_docking("defiant", "jenn-mac")
    ship = store.confirm_docking(users["doctor"]["id"], started["id"], started["code"])
    store.rename_user(users["patient"]["id"], "<i>Andy</i>")
    store.rename_user(users["doctor"]["id"], "<img src=x onerror=alert(3)>")
    andy = signed_in_client(browser_peer, "patient")
    law = new_charter(andy, title="<b>Station</b> law", body="Be kind.\nAsk in the room.",
                      policy={"version": 1, "delegation": {"max_depth": 4}})["id"]
    sign(andy, law, confirm=["delegation.max_depth"])
    return store, users, ship, andy, law


def test_an_owner_accepts_the_charter_on_its_page_and_stops_accepting_after_the_ask(browser_peer):
    """Test 37 (R35): the doctor reads the charter and its limits, sees the whole text as new, can't accept until she
    ticks the widened path, chooses follow and accepts; her acceptance shows. The patient's page says he signed it and
    lists her. A later revision that widens again waits for her with its diff against the one binding her. "Stop
    accepting" asks first, and Cancel changes nothing. Names and titles written as HTML show as text."""
    from test_acceptances import sign
    store, users, ship, andy, law = charter_station(browser_peer)
    doctor = users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Charter", exact=True).click()
            expect(page.get_by_role("heading", name="Charter", level=1)).to_be_visible()
            expect(page.get_by_role("heading", name="<b>Station</b> law")).to_be_visible()
            expect(page.locator(".charter-text")).to_contain_text("Revision 1 · signed by <i>Andy</i>")
            expect(page.locator(".charter-policy")).to_contain_text("Links in a grant chain, at most: 4")
            expect(page.locator(".charter-diff .diff-add")).to_have_text(["+ <b>Station</b> law", "+ Be kind.", "+ Ask in the room."])
            accept_button = page.get_by_role("button", name="Accept revision 1")
            expect(accept_button).to_be_disabled()  # one box to tick first
            page.get_by_label("Links in a grant chain, at most: 3 → 4").check()
            expect(accept_button).to_be_enabled()
            expect(page.get_by_label("Keep this revision until I accept another")).to_be_checked()
            page.get_by_label("Follow later revisions that don't widen the limits").check()
            expect(page.get_by_text("Accepting covers all your ships, now and later.")).to_be_visible()
            accept_button.click()
            expect(page.locator(".notice", has_text="You accepted revision 1.")).to_be_visible()
            mine = page.locator(".charter-mine")
            expect(mine).to_contain_text("You accepted revision 1 on")
            expect(mine).to_contain_text("following later revisions that don't widen the limits")
            expect(mine).to_contain_text("Revision 1 binds your ships.")
            expect(page.locator(".charter-pending")).to_have_count(0)
            assert store.charter_view(doctor)["acceptance"]["follow"] is True
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Charter", exact=True).click()
            expect(page.get_by_role("heading", name="You signed this charter; it binds your ships")).to_be_visible()
            expect(page.locator(".charter-accepted li")).to_have_count(1)
            expect(page.locator(".charter-accepted li")).to_contain_text("<img src=x onerror=alert(3)>: revision 1, following")
            assert page.locator("#main-content img, #main-content b, #main-content i").count() == 0
        sign(andy, law, body="Be kind.\nAsk in the room first.",
             policy={"version": 1, "delegation": {"max_depth": 4}, "budgets": {"builds_per_ship_per_day": 30}},
             confirm=["budgets.builds_per_ship_per_day"])
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Charter", exact=True).click()
            pending = page.locator(".charter-pending")
            expect(pending.get_by_role("heading", name="Revision 2 is waiting for you")).to_be_visible()
            expect(pending).to_contain_text("Changes from revision 1, which binds your ships now:")
            expect(pending.locator(".diff-del")).to_have_text(["- Ask in the room."])
            expect(pending.locator(".diff-add")).to_have_text(["+ Ask in the room first."])
            expect(pending.get_by_label("Grant builds per ship a day: 20 → 30")).not_to_be_checked()
            expect(pending.get_by_role("button", name="Accept revision 2")).to_be_disabled()
            leaves = []
            page.on("request", lambda request: leaves.append(request.url) if request.url.endswith("/api/charter/leave") else None)
            page.get_by_role("button", name="Stop accepting").click()
            ask = page.locator(".charter-ask")
            expect(ask).to_contain_text("Stop accepting the charter?")
            expect(ask.get_by_role("button", name="Cancel")).to_be_focused()
            ask.get_by_role("button", name="Cancel").click()
            expect(page.locator(".charter-ask")).to_have_count(0)
            expect(page.get_by_role("button", name="Stop accepting")).to_be_focused()
            assert leaves == [] and store.charter_view(doctor)["acceptance"] is not None
            page.get_by_role("button", name="Stop accepting").click()
            page.get_by_role("button", name="Yes, stop accepting").click()
            expect(page.locator(".notice", has_text="You no longer accept the charter.")).to_be_visible()
            expect(page.locator(".charter-mine")).to_have_count(0)
            expect(page.locator(".charter-diff .diff-add")).to_have_count(3)  # the whole text is new again
            assert len(leaves) == 1 and store.charter_view(doctor)["acceptance"] is None
            assert page.locator("#main-content img, #main-content b, #main-content i").count() == 0


def test_the_grants_page_lists_the_grant_and_never_the_acceptance(browser_peer):
    """Test 26's grants page (C18): with the doctor's acceptance of the patient's charter and the patient's grant to the
    doctor, each person's Grants page shows the one grant and nothing for the acceptance."""
    store, users, ship, andy, law = charter_station(browser_peer)
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    started = store.start_docking("serenity", "andy-mac")
    serenity = store.confirm_docking(patient, started["id"], started["code"])
    room = store.create_room(patient, "Ops", [doctor, serenity["id"]])
    made = store.make_grant(patient, doctor, [serenity["id"]], [room["id"]], 24, 5)
    jenn = signed_in_client(browser_peer, "doctor")
    assert jenn.post("/api/charter/accept", json={"layer_id": law, "revision": 1, "follow": False,
                                                  "confirm_widenings": ["delegation.max_depth"]}).status_code == 200
    with sync_playwright() as playwright:
        for username, section in (("doctor", ".grants-held"), ("patient", ".grants-given")):
            with signed_in_browser(playwright, browser_peer, username) as (page, _):
                page.get_by_role("link", name="Grants", exact=True).click()
                expect(page.locator(f"{section} .grant-item")).to_have_count(1)
                expect(page.locator(f"{section} .grant-item")).to_contain_text(made["short"])
                expect(page.locator(".grant-item")).to_have_count(1)


def test_a_revision_too_large_for_a_ship_says_which_and_cannot_be_accepted(browser_peer):
    """Plan Review Focus 4 (C23, R35): the doctor's ship has ten instruction layers of her own, so the charter would be
    its eleventh: the page names the ship and why, and the button stays disabled with every box ticked."""
    from test_acceptances import own_layers
    store, users, ship, andy, law = charter_station(browser_peer)
    own_layers(signed_in_client(browser_peer, "doctor"), ship, 10)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Charter", exact=True).click()
            pending = page.locator(".charter-pending")
            expect(pending.locator(".notice.error")).to_contain_text("Too large for Defiant: with that ship's own instruction layers it would pass 10 layers or 48,000 bytes.")
            pending.get_by_label("Links in a grant chain, at most: 3 → 4").check()
            expect(pending.get_by_role("button", name="Accept revision 1")).to_be_disabled()


def test_a_charter_signed_while_the_page_is_open_is_read_again_when_accepting(browser_peer):
    """Plan Review Focus 5 (spec Routes, accept step 3): the patient signs revision 2 while the doctor reads revision 1;
    her accept gets "The charter changed; read it again", and the page then shows revision 2 waiting, with nothing
    accepted."""
    from test_acceptances import sign
    store, users, ship, andy, law = charter_station(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Charter", exact=True).click()
            page.get_by_label("Links in a grant chain, at most: 3 → 4").check()
            sign(andy, law, body="Be kind.\nAsk in the room first.")
            page.get_by_role("button", name="Accept revision 1").click()
            expect(page.locator(".notice.error", has_text="The charter changed; read it again")).to_be_visible()
            expect(page.get_by_role("heading", name="Revision 2 is waiting for you")).to_be_visible()
            assert store.charter_view(users["doctor"]["id"])["acceptance"] is None
```

`test_the_grants_page_lists_the_grant_and_never_the_acceptance` passes before this task: the Grants page reads only
`GET /api/grants`. It guards that, and Step 5's mutation shows it bites. The last two tests are plan Review Focus 4 and 5.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_browser.py::test_an_owner_accepts_the_charter_on_its_page_and_stops_accepting_after_the_ask tests/test_browser.py::test_the_grants_page_lists_the_grant_and_never_the_acceptance tests/test_browser.py::test_a_revision_too_large_for_a_ship_says_which_and_cannot_be_accepted tests/test_browser.py::test_a_charter_signed_while_the_page_is_open_is_read_again_when_accepting`
Expected: `3 failed, 1 passed`, after about a minute and a half: each of the three page tests with
`playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.` waiting for
`get_by_role("link", name="Charter", exact=True)`. The grants page test passes (see above).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/static/app.js`, in `bindEditorIdentity`, replace

```javascript
state.grants = null; state.grantPeople = null; state.grantForm = null; state.grantAsk = null; state.layerEdits = {};
```

with

```javascript
state.grants = null; state.grantPeople = null; state.grantForm = null; state.grantAsk = null; state.charter = null; state.charterAsk = false; state.layerEdits = {};
```

In `routeParts`, replace `"grants", "layers"` with `"grants", "charter", "layers"`. In `layout`, after

```javascript
        ${navLink("grants", "Grants", "✧")}
```

add

```javascript
        ${navLink("charter", "Charter", "§")}
```

Before the comment line `// One board write at a time: a second click while one is on its way would get 409 for the first one's own work and`
insert, followed by a blank line:

```javascript
// Charter 4c (R35): the station's charter and its limits, the caller's acceptance, a pending revision with its line diff
// against the one binding them, one checkbox per widened path, pin or follow, and "Stop accepting", which asks first.
// Every title, name and body is people's text, escaped where shown.
const POLICY_NUMBERS = [["delegation", "max_depth", "Links in a grant chain, at most"], ["delegation", "max_expiry_hours", "Longest grant, in hours"],
  ["delegation", "agent_grant_default_hours", "An agent's grant by default, in hours"], ["budgets", "builds_per_ship_per_day", "Grant builds per ship a day"]];

async function loadCharter() {
  const who = identityKey(state.me);
  try {
    const charter = await api("/api/charter");
    if (identityKey(state.me) === who) state.charter = charter;
  } catch (error) {
    if (error.status === 401) throw error;
    if (identityKey(state.me) === who) state.charter = null;
  }
}

// C30: a line diff, computed in the browser, by the longest common subsequence of lines: [{kind, text}], kind being
// "same", "del" or "add".
function lineDiff(before, after) {
  const a = before === "" ? [] : before.split("\n"), b = after.split("\n"), n = a.length, m = b.length;
  const common = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) common[i][j] = a[i] === b[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
  const lines = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { lines.push({ kind: "same", text: a[i] }); i++; j++; }
    else if (common[i + 1][j] >= common[i][j + 1]) lines.push({ kind: "del", text: a[i++] });
    else lines.push({ kind: "add", text: b[j++] });
  }
  while (i < n) lines.push({ kind: "del", text: a[i++] });
  while (j < m) lines.push({ kind: "add", text: b[j++] });
  return lines;
}

function diffMarkup(before, after) {
  const mark = { same: " ", del: "-", add: "+" };
  return `<pre class="charter-diff">${lineDiff(before, after).map((line) => `<span class="diff-${line.kind}">${mark[line.kind]} ${escapeHtml(line.text)}</span>`).join("")}</pre>`;
}

function personName(names, id) {
  return names?.[id] || "an unknown person";
}

function policyMarkup(policy, names) {
  const items = POLICY_NUMBERS.map(([section, key, label]) => `${label}: ${policy[section][key]}`);
  items.push(`Ships may pass on: ${policy.delegation.delegable.join(", ") || "nothing"}`);
  items.push(policy.grantees === null ? "Grants may go to anyone" : `Grants may go only to: ${policy.grantees.people.map((id) => personName(names, id)).join(", ") || "no one"}`);
  return `<ul class="charter-policy">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

// A widened path in words (spec Data's paths): numbers say before → after, a gained member says what it gains.
function wideningWords(item, names) {
  const number = POLICY_NUMBERS.find(([section, key]) => item.path === `${section}.${key}`);
  if (number) return `${number[2]}: ${item.before} → ${item.after}`;
  if (item.path === "grantees") return "Grants may go to anyone, not only to the people listed";
  const [field, member] = item.path.split(":");
  if (field === "delegation.delegable") return `Ships may pass on: ${member}`;
  if (field === "grantees.people") return `Grants may go to ${personName(names, member)}`;
  if (field === "grantees.ships_of") return `Grants may go to ships of ${personName(names, member)}`;
  return item.path;
}

function charterLeaveMarkup() {
  if (!state.charterAsk) return `<div class="button-row"><button class="button danger secondary" type="button" data-action="charter-leave">Stop accepting</button></div>`;
  return `<div class="board-ask charter-ask" role="group" aria-label="Stop accepting the charter?"><p>Stop accepting the charter? Your ships stop being bound by it at their next run; to accept again, you confirm any limit it widens again.</p><div class="button-row"><button class="button secondary" type="button" data-action="charter-leave-cancel">Cancel</button><button class="button danger" type="button" data-action="charter-leave-confirm">Yes, stop accepting</button></div></div>`;
}

function charterMineMarkup(view) {
  const held = view.acceptance;
  if (!held) return "";
  const how = held.follow ? "following later revisions that don't widen the limits" : "kept at that revision until you accept another";
  const withdrawn = held.layer_id !== view.charter?.layer_id ? `<p class="meta">It names a charter that was withdrawn, so it binds nothing unless that charter is signed again.</p>` : "";
  const binding = view.binding ? `<p>${escapeHtml(`Revision ${view.binding.revision} binds your ships.`)}</p>` : "";
  return `<section class="section charter-mine" aria-labelledby="charter-mine-title"><h2 id="charter-mine-title">Your acceptance</h2><p>${escapeHtml(`You accepted revision ${held.revision} on ${formatDate(held.accepted)}, ${how}.`)} It covers all your ships, now and later.</p>${withdrawn}${binding}${charterLeaveMarkup()}</section>`;
}

function charterPendingMarkup(view) {
  const pending = view.pending, charter = view.charter, names = charter.names || {};
  const before = view.binding ? `${view.binding.title}\n${view.binding.body}` : "";
  const intro = view.binding ? `Changes from revision ${view.binding.revision}, which binds your ships now:` : "The whole text is new to you:";
  const boxes = pending.widenings.map((item) => `<label class="choice"><input type="checkbox" name="charter-widening" value="${escapeHtml(item.path)}"><span class="choice-copy"><strong>${escapeHtml(wideningWords(item, names))}</strong></span></label>`).join("");
  const widened = pending.widenings.length ? `<fieldset class="field"><legend>These limits grow. Tick each one to accept it.</legend><div class="choices">${boxes}</div></fieldset>` : "";
  const tooLarge = pending.too_large.length ? `<p class="notice error">${escapeHtml(`Too large for ${pending.too_large.join(", ")}: with that ship's own instruction layers it would pass 10 layers or 48,000 bytes. Withdraw one of its layers first.`)}</p>` : "";
  const blocked = pending.widenings.length || pending.too_large.length;
  return `<section class="section charter-pending" aria-labelledby="charter-pending-title"><h2 id="charter-pending-title">${escapeHtml(`Revision ${pending.revision} is waiting for you`)}</h2><p class="meta">${escapeHtml(intro)}</p>${diffMarkup(before, `${charter.title}\n${charter.body}`)}<form id="charter-accept-form">${widened}${tooLarge}<fieldset class="field"><legend>Later revisions</legend><label class="choice"><input type="radio" name="charter-follow" value="pin" checked><span class="choice-copy"><strong>Keep this revision until I accept another</strong></span></label><label class="choice"><input type="radio" name="charter-follow" value="follow"><span class="choice-copy"><strong>Follow later revisions that don't widen the limits</strong></span></label></fieldset><p>Accepting covers all your ships, now and later.</p><button class="button" type="submit"${blocked ? " disabled" : ""}>${escapeHtml(`Accept revision ${pending.revision}`)}</button></form></section>`;
}

function charterSignerMarkup(view) {
  const list = view.acceptances.length ? `<ul class="grant-list charter-accepted">${view.acceptances.map((item) => `<li class="grant-item">${escapeHtml(`${item.person.name}: revision ${item.revision}, ${item.follow ? "following" : "pinned"} · ${formatDate(item.accepted)}`)}</li>`).join("")}</ul>`
    : `<p class="meta">No one else has accepted it yet.</p>`;
  return `<section class="section charter-signer" aria-labelledby="charter-signer-title"><h2 id="charter-signer-title">You signed this charter; it binds your ships</h2><h3>Accepted by</h3>${list}</section>`;
}

function charterView() {
  const head = `<header class="page-head"><div><p class="eyebrow">The station</p><h1>Charter</h1><p class="lede">The station's charter binds the ships of everyone who accepts it, first among their instructions.</p></div></header>`;
  const view = state.charter;
  if (!view) return `${head}<p class="meta">The charter could not be read. Refresh to try again.</p>`;
  const charter = view.charter;
  const text = charter ? `<section class="section charter-text" aria-labelledby="charter-text-title"><h2 id="charter-text-title" tabindex="-1">${escapeHtml(charter.title)}</h2><p class="meta">${escapeHtml(`Revision ${charter.revision} · signed by ${charter.signer.name} · ${formatDate(charter.created)}`)}</p><div class="shared-body">${escapeHtml(charter.body)}</div><h3>Limits</h3>${policyMarkup(charter.policy, charter.names)}</section>`
    : `<section class="section charter-text"><h2 id="charter-text-title" tabindex="-1">No charter is active</h2></section>`;
  return `${head}${text}${view.signer ? charterSignerMarkup(view) : `${charterMineMarkup(view)}${view.pending ? charterPendingMarkup(view) : ""}`}`;
}

// One charter write at a time. Accepting and leaving both answer with GET /api/charter's shape; a refusal (the charter
// changed meanwhile, say) reads it again, so the page shows what the station holds.
async function charterWrite(path, json, message) {
  if (state.charterSaving) return false;
  let done = false;
  state.charterSaving = true;
  const who = identityKey(state.me);
  try {
    const answer = await api(path, { method: "POST", json });
    if (identityKey(state.me) !== who) return false;
    state.charter = answer;
    state.charterAsk = false;
    setFlash(message(answer));
    done = true;
  } catch (error) {
    if (error.status === 401) { showLogin("Your session ended. Sign in again."); return false; }
    if (identityKey(state.me) === who) {
      setFlash(error.message, true);
      try { await loadCharter(); } catch (_) { /* the page says it could not be read */ }
    }
  } finally {
    state.charterSaving = false;
    if (state.me && identityKey(state.me) === who && routeParts().route === "charter") render();
  }
  return done;
}

async function acceptCharter(form) {
  const view = state.charter, pending = view?.pending;
  if (!pending || state.charterSaving) return;
  const ticked = [...form.querySelectorAll('[name="charter-widening"]:checked')].map((input) => input.value);
  if (ticked.length !== pending.widenings.length || pending.too_large.length) return;  // its button stays disabled until then
  const follow = form.querySelector('[name="charter-follow"]:checked')?.value === "follow";
  await charterWrite("/api/charter/accept", { layer_id: view.charter.layer_id, revision: view.charter.revision, follow, confirm_widenings: ticked },
                     () => `You accepted revision ${view.charter.revision}.`);
}
```

In `loadRoute`, after

```javascript
  if (route === "grants") { try { await loadData(); } catch (_) { /* the view below reads what it can */ } await loadGrants(); }
```

add

```javascript
  if (route === "charter") await loadCharter();
```

In `render`, replace `grants: grantsView, layers: layersView` with `grants: grantsView, charter: charterView, layers: layersView`,
and `grants: "Grants", layers: "My sharing layers"` with `grants: "Grants", charter: "Charter", layers: "My sharing layers"`.

In the submit handler, after `  if (form.id === "grant-form") await makeGrant(form);` add

```javascript
  if (form.id === "charter-accept-form") await acceptCharter(form);
```

In the click handler, before `  if (action === "remove-participant") await removeParticipant(target.dataset.id);` insert:

```javascript
  if (action === "charter-leave") {
    state.charterAsk = true;
    render();
    document.querySelector('.charter-ask [data-action="charter-leave-cancel"]')?.focus();  // the safe choice
  }
  if (action === "charter-leave-cancel") {
    state.charterAsk = false;
    render();
    document.querySelector('[data-action="charter-leave"]')?.focus();
  }
  if (action === "charter-leave-confirm" && state.charterAsk) {
    if (await charterWrite("/api/charter/leave", {}, () => "You no longer accept the charter.")) document.querySelector("#charter-text-title")?.focus();
  }
```

In the change handler, before `  if (event.target.id === "grant-person") {` insert:

```javascript
  if (event.target.closest("#charter-accept-form")) {  // the button waits for every widened path's box (R35)
    const form = event.target.form, pending = state.charter?.pending;
    form.querySelector('button[type="submit"]').disabled = ![...form.querySelectorAll('[name="charter-widening"]')].every((box) => box.checked)
      || !!pending?.too_large?.length;
  }
```

In `peer/superyak_peer/static/app.css`, after `.grant-make form { display: grid; gap: 12px; max-width: 720px; }` add:

```css
.charter-diff { margin: 8px 0 14px; padding: 12px 14px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; background: #fff; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.charter-diff span { display: block; }
.charter-diff .diff-add { background: #e7f4ea; }
.charter-diff .diff-del { background: #fbe9e7; }
.charter-policy { margin: 6px 0 0; padding-left: 18px; }
#charter-accept-form { display: grid; gap: 12px; max-width: 720px; }
```

- [ ] **Step 4: Run the tests to see them pass**

Run: the Step 2 command.
Expected: `4 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run the test named, see it fail, restore:
- `<button class="button" type="submit">` for the one with `${blocked ? " disabled" : ""}` → the page test (the button
  ignores the boxes);
- `if (false) {` for the change handler's `if (event.target.closest("#charter-accept-form")) {` → the page test (ticking
  never enables it);
- `${charter.title}` for `${escapeHtml(charter.title)}` in `charterView` → the page test (an element comes out of the
  title);
- the `charter-leave` handler calling `charterWrite("/api/charter/leave", ...)` at once → the page test (no ask);
- `const before = "";` in `charterPendingMarkup` (no diff against the binding revision) → the page test;
- `${(` for `${escapeHtml(` in `charterSignerMarkup`'s list item → the page test (the patient's list);
- drop `|| !!pending?.too_large?.length` → `test_a_revision_too_large_for_a_ship_says_which_and_cannot_be_accepted`;
- drop `try { await loadCharter(); } catch (_) { ... }` in `charterWrite` → `test_a_charter_signed_while_the_page_is_open_is_read_again_when_accepting`;
- in `_insert_acceptance`, also `self._insert_grant(db, person_id, signer_id, [], '*', 720, 1)` after signing →
  `test_the_grants_page_lists_the_grant_and_never_the_acceptance`.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/static/app.js peer/superyak_peer/static/app.css peer/tests/test_browser.py
git commit -m "Charter 4c: the Charter page: read, accept pinned or following with each widening ticked, stop accepting (R35)"
```

---

### Task 10: API.md, the restore runbook, and the whole suite

**Files:**
- Modify: `peer/API.md` ("## Signed records", `:267-308`; a new "## Charter acceptances" before "## Grants", `:310`)
- Modify: `docs/station-restore.md` (the "brings back" paragraph, `:10-15`; step 7, `:170-171`)

**Interfaces:**
- Consumes: everything above. Produces: documentation only.

API.md's "Charter" section, binding rule and block format are 4a's (its R23). This task adds 4c's own section beside
them and the two record kinds; if 4a reworded a line anchored below, reconcile the anchor, not the text 4c adds.

- [ ] **Step 1: Write the docs**

In `peer/API.md`, replace `don't (see below). It signs three kinds:` with `don't (see below). It signs five kinds:`.
After the `grant-revocation` bullet,

```markdown
- `grant-revocation`: `{kind, station, grant, revoked, revoked_by, reason}`, signed in the transaction that revokes.
  A revocation the restore reconcile wrote is signed once at the next start.
```

add

```markdown
- `charter-acceptance`: `{kind, station, id, person_id, signer_id, layer_id, revision, follow, created}`, with `follow`
  a JSON boolean, signed in the transaction that stores the acceptance (see Charter acceptances).
- `charter-acceptance-revocation`: `{kind, station, acceptance, revoked, revoked_by, reason}`, signed in the transaction
  that ends the acceptance. An end the restore reconcile wrote is signed once at the next start.
```

Replace the line

```markdown
kind's keys (`instructions-revision`, `grant` or `grant-revocation`), its `station` is the card's peer id, and the
```

with

```markdown
kind's keys (`instructions-revision`, `grant`, `grant-revocation`, `charter-acceptance` or
`charter-acceptance-revocation`), its `station` is the card's peer id, and the
```

and the line

```markdown
card export still names its host; but a station that holds signed records (a revision signature or a grant) and has
```

with

```markdown
card export still names its host; but a station that holds signed records (a revision signature, a grant or a charter
acceptance) and has
```

Before `## Grants` insert, followed by a blank line:

```markdown
## Charter acceptances

A person who owns ships, or will, accepts the station's charter, pinned to its active revision or following later
ones; their ships, now and docked later, are then bound by the revision their acceptance binds, first among their
instructions (charter step 4, merge 4c: `docs/superpowers/specs/2026-10-15-charter-step4-design.md`, C17-C23, C26,
C27). The charter's signer accepts by signing, with no row. An acceptance is a row of `charter_acceptances`, never a
grant: no grant route, validity check, ticket, budget or grant reconcile reads it, and the Grants page doesn't list it.
The web app's Charter page (`#charter`) reads, accepts and leaves. Every route below takes a person session (CSRF on
writes), and a ship key gets 403 on each.

| Method/path | Body | Behavior |
|---|---|---|
| GET `/api/charter` | — | `{charter, signer, acceptance, binding, pending, acceptances}`; never 404 |
| POST `/api/charter/accept` | `{layer_id, revision, follow, confirm_widenings}` | 200 with `GET /api/charter`'s shape |
| POST `/api/charter/leave` | `{reason?}` | 200 with `GET /api/charter`'s shape |
| GET `/api/charter/acceptances/{id}/signed` | — | `{station, record, signature}`, plus `revocation: {record, signature}` once it ended |

**Reading.** `charter` is the active charter revision, `{layer_id, revision, title, body, policy, names, signer: {id,
name}, created}`, or null; `names` gives the name of each person id that its grantee set, or that of the revision
binding the caller, lists. `signer` says whether the caller signed it. `acceptance` is the caller's own acceptance in
force, `{id, short, layer_id, revision, follow, accepted}`, or null; its `layer_id` tells an acceptance of a withdrawn
charter from one of the active charter. `binding` is the revision binding the caller's ships now, `{layer_id,
revision, title, body, policy}`, or null. `pending` is the active revision when it doesn't bind them: `{revision,
widenings, narrowings, too_large, baseline}`, with the widened and narrowed paths against `baseline` (the binding
revision's number, or `"defaults"`) and the names of the caller's ships it would put over the caps. `acceptances` lists,
for the active charter's signer only, each acceptance in force of that charter, `{person: {id, name}, revision, follow,
accepted}`, `revision` being the one the acceptance names; it is empty for everyone else.

**Accepting.** Checked in this order; the first failure answers: a key other than the four (400); `layer_id` not a
string, `revision` not a JSON integer, `follow` not a boolean, `confirm_widenings` not a list of at most 105 strings of
at most 200 characters (400 each; absent is `[]`); no charter active, or `layer_id` and `revision` not the active
charter's (409 "The charter changed; read it again"); the caller signed it (409 "You signed this charter; it binds your
ships already"); `confirm_widenings` not exactly the paths that widen from the caller's baseline, each once (409
"Confirm exactly these widenings: …"); a ship of the caller's that the revision, with that ship's own layers, would put
over 10 layers or 48,000 bytes (409 naming the ship). The baseline is the revision binding the caller's ships now, or the
no-charter defaults when none does (a first acceptance, or one after leaving). The caller may own no ships yet. An
acceptance in force that already names this revision with the same `follow` answers 200 and adds no row (checked after
the signer check, so a retried request is never refused). Otherwise, in one transaction, the acceptance in force ends
with reason `superseded` (by the caller, signed) and the new one is stored and signed. A person holds at most one
acceptance in force (a partial unique index).

**Binding.** A pinned acceptance binds its revision. A following one starts at its revision and steps through the
layer's existing revisions one at a time, each compared with the one binding the owner then; it stops before a revision
whose number is not exactly one more (a withdrawal came between), before one that widens, and before one that would put
one of the owner's ships over the caps. A withdrawn charter binds no ship; its acceptances stay in force and bind again
when the same layer is activated again, and that activation gets 409 naming a ship when an acceptance's own revision,
with that ship's own layers, would pass the caps. An owner's own activation of an instructions layer gets 409 naming a
ship when it would change which charter revision binds their ships (`<ship> would be bound by charter revision <n>
instead of revision <m>`), or when the revision binding them, with the new layer, would pass the caps.

**Leaving.** `reason` is one line of at most 200 characters (400 otherwise); missing, null or blank, it is `left`. 409
"You have not accepted a charter" when the caller has none in force. The end is signed in the same transaction, and the
caller's ships are no longer bound by it at their next fetch or ticket.

**Signed records.** An acceptance is signed as `charter-acceptance` and its end as `charter-acceptance-revocation` (see
Signed records). `GET /api/charter/acceptances/{id}/signed` answers the acceptance's person and its signer; anyone else,
and an unknown id, gets 404. A charter revision's signature (`GET /api/layers/{id}/revisions/{n}/signed`) goes, besides
its signer and, for the active revision, every signed-in person, to each person whose acceptance names it now or did
before, a follower's naming the revision its walk binds now too; anyone else gets 404.

**Restoring.** `station-restore-reconcile` treats acceptances by person and never adds one: an acceptance in force in
the staged copy is kept when the replaced file holds one in force for that person, and otherwise ends with reason
`restored` and no person; the station signs that end at its next start. Without a usable replaced file every
acceptance is kept. The report lists each acceptance it ended or kept, and each person whose acceptance in force in the
replaced file the copy lost (they accepted only after the copy, and are bound by none, or accepted again after it, and
are back at the copy's revision and follow), with the revision they had. A copy from before 4c has no
`charter_acceptances` table: the step is skipped, and every acceptance in force in the replaced file is listed as lost.

**Older stations.** A station rolled back to before 4c never reads `charter_acceptances`: acceptances bind nothing
there, and its lost-identity check doesn't count them, so such a station with a lost `identity.json` could start with a
new key over signed acceptances.
```

In `docs/station-restore.md`, replace

```markdown
  Step 5 takes back everything that only grants access (a peer's pairing included) before the copy goes live, and lists
  the rest for you.
```

with

```markdown
  Step 5 takes back everything that only grants access (a peer's pairing included) before the copy goes live, and lists
  the rest for you. Charter acceptances are law for their owners' ships, not access: step 5 keeps each one unless the
  replaced file shows its person left, and lists the people whose later acceptance the copy lost.
```

and in step 7, after the sentence that ends `a grant made after the copy is gone too.`, add on the same line:

```markdown
 Ask each person the report lists under "Charter acceptances lost" to accept the charter again on its Charter page.
```

(with its leading space, so the sentence joins the line as the step's other sentences do).

- [ ] **Step 2: Run the whole suite**

Run: `cd peer && uv run --locked python -m pytest -q -ra --tb=short`
Expected: `973 passed, 1 skipped` on Appendix A, this plan's 32 new tests among them, in about 7 minutes; on the real
4a, the suite's count before Task 1 plus 32. The skip is `test_station_units.py:73`'s, away from the station host. `test_restore.py` reads
`docs/station-restore.md`'s commands and still passes: no command changed.

- [ ] **Step 3: Check that no step 3 grant code changed**

Run: `git diff 9e0aac8 -- peer/superyak_peer/grants.py peer/superyak_peer/tickets.py`
Expected: no output (C18, R29). Then read `git diff 9e0aac8 -- peer/superyak_peer/signatures.py peer/superyak_peer/backups.py peer/superyak_peer/static/app.js`
and see that every line 4c added is new code beside the grants' (the acceptance methods, the acceptances steps, the
Charter page), with no grant function, the grants reconcile or the Grants page touched. (Run both against the commit
where 4a merged into this branch, if later than `9e0aac8`.)

- [ ] **Step 4: Commit**

```bash
git add peer/API.md docs/station-restore.md
git commit -m "Charter 4c: API.md's charter acceptances and signed records, and the restore runbook's report lines"
```

---

## Deploy (after the merge, from the spec)

4c goes under section 2: approved in the room, the Pi suites passing. Before it, back up `peer.sqlite3` with SQLite's
backup API; after it, restart the lighthouse and the door (no watcher restarts: 4c changes no agent file). The live
check, with no person's login: on a copy made with the backup API, never `cp`, in a scratch directory, with a throwaway
identity as the rehearsal makes one, a throwaway person with a throwaway ship accepts the active charter, if any, through
`Store.accept_charter`; the ship's binding (`_binding_layers`) follows, and Andy's ships' bindings are unchanged. Delete
the copy. On a failed check: revert, restart, announce. Acceptance rows left behind bind nothing on an older station
(spec Mixed versions), and the `grants` table is as step 3 left it.

---

## Appendix A: the 4a stand-in, for dry runs only

Never commit this. It implements I1 to I16 with the spec's semantics and nothing else (no policy validation, no
footers, no brackets in headers, no `GET /api/grants/policy`), so 4c's tasks can be dry-run before 4a exists. Save it as
`standin.diff` in a scratch clone of `9e0aac8` and run `git apply standin.diff`; then apply the tasks in order. Its one
change to an existing test (the ship route's answer gains `charter: None`) is 4a's to make for real.

```diff
diff --git a/agent/superyak_agent/station.py b/agent/superyak_agent/station.py
index 9c809e7..dc4790d 100644
--- a/agent/superyak_agent/station.py
+++ b/agent/superyak_agent/station.py
@@ -523,3 +523,18 @@ def board_block(title, room_id, items, budget):
     text = '\n'.join([head, fence_external(BOARD_SENDER, body, limit=len(body)), tail])
     left = len(items) - len(shown)
     return text + (f'\n[{left} more board item{"s" if left > 1 else ""} not shown]' if left else '')
+
+
+def charter_line(charter):
+    """4a STAND-IN (R20): the status command's one charter line from GET /api/ships/me/instructions' charter field; None
+    when the station sent no such field."""
+    if charter is None:
+        return 'Charter: none active'
+    if not isinstance(charter, dict):
+        return None
+    revision, binding = charter.get('revision'), charter.get('binding')
+    if binding == revision:
+        return f'Charter: revision {revision} binds this ship'
+    if binding is not None:
+        return f"Charter: revision {revision} is pending for this ship's owner; revision {binding} binds this ship"
+    return f"Charter: revision {revision} is active; this ship's owner has not accepted it"
diff --git a/peer/pyproject.toml b/peer/pyproject.toml
index 58295e8..6e8b6d9 100644
--- a/peer/pyproject.toml
+++ b/peer/pyproject.toml
@@ -58,6 +58,7 @@ only-include = [
     "superyak_peer/backups.py",
     "superyak_peer/breakouts.py",
     "superyak_peer/briefs.py",
+    "superyak_peer/charter.py",
     "superyak_peer/chats.py",
     "superyak_peer/common.py",
     "superyak_peer/db.py",
@@ -149,6 +150,7 @@ only-include = [
     "superyak_peer/backups.py",
     "superyak_peer/breakouts.py",
     "superyak_peer/briefs.py",
+    "superyak_peer/charter.py",
     "superyak_peer/chats.py",
     "superyak_peer/common.py",
     "superyak_peer/db.py",
diff --git a/peer/superyak_peer/app.py b/peer/superyak_peer/app.py
index 4296dd2..eadae5c 100644
--- a/peer/superyak_peer/app.py
+++ b/peer/superyak_peer/app.py
@@ -467,11 +467,13 @@ def create_app(data_dir: Path, *, clock=time.time, allowed_origins=DEFAULT_ORIGI
     @app.post('/api/layers/{key}/activate')
     async def layer_activate(key: str, request: Request):
         who, data = actor(request), await body(request)
-        return store.activate_layer(who, key, data.get('version'), data.get('space_versions'))
+        return store.activate_layer(who, key, data.get('version'), data.get('space_versions'), data.get('confirm_widenings'))
 
     @app.post('/api/layers/{key}/withdraw')
-    def layer_withdraw(key: str, request: Request):
-        return store.withdraw_layer(actor(request), key)
+    async def layer_withdraw(key: str, request: Request):
+        who = actor(request)
+        data = await body(request) if (await request.body()).strip() else {}  # 4a stand-in: an empty body is {}
+        return store.withdraw_layer(who, key, data.get('confirm_widenings'))
 
     @app.post('/api/layers/{key}/revoke')
     async def layer_revoke(key: str, request: Request):
diff --git a/peer/superyak_peer/charter.py b/peer/superyak_peer/charter.py
new file mode 100644
index 0000000..12e1fed
--- /dev/null
+++ b/peer/superyak_peer/charter.py
@@ -0,0 +1,79 @@
+"""STAND-IN for merge 4a's policy module, for dry runs of the 4c plan only. It implements the interfaces the 4c plan
+consumes, with the spec's semantics and no schema validation; 4a's real module replaces it."""
+import copy
+from .common import Problem
+
+DEFAULT_POLICY = {'version': 1,
+                  'delegation': {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24,
+                                 'delegable': ['direct']},
+                  'budgets': {'builds_per_ship_per_day': 20},
+                  'grantees': None}
+MAX_WIDENINGS = 105
+NUMBERS = (('delegation', 'max_depth'), ('delegation', 'max_expiry_hours'),
+           ('delegation', 'agent_grant_default_hours'), ('budgets', 'builds_per_ship_per_day'))
+
+
+def full_policy(policy):
+    """Every default filled in (spec Data, C11). The stand-in does not validate."""
+    given = policy or {}
+    full = copy.deepcopy(DEFAULT_POLICY)
+    for section in ('delegation', 'budgets'):
+        full[section].update(given.get(section) or {})
+    if 'agent_grant_default_hours' not in (given.get('delegation') or {}):
+        full['delegation']['agent_grant_default_hours'] = min(24, full['delegation']['max_expiry_hours'])
+    if given.get('grantees') is not None:
+        full['grantees'] = {'people': list(given['grantees'].get('people', [])),
+                            'ships_of': list(given['grantees'].get('ships_of', []))}
+    return full
+
+
+def _compare(old, new, grows):
+    found = []
+    for section, key in NUMBERS:
+        before, after = old[section][key], new[section][key]
+        if (after > before) if grows else (after < before):
+            found.append({'path': f'{section}.{key}', 'before': before, 'after': after})
+    gained = set(new['delegation']['delegable']) - set(old['delegation']['delegable'])
+    lost = set(old['delegation']['delegable']) - set(new['delegation']['delegable'])
+    for action in sorted(gained if grows else lost):
+        found.append({'path': f'delegation.delegable:{action}', 'before': None if grows else action,
+                      'after': action if grows else None})
+    if grows and old['grantees'] is not None and new['grantees'] is None:
+        found.append({'path': 'grantees', 'before': old['grantees'], 'after': None})
+    if not grows and old['grantees'] is None and new['grantees'] is not None:
+        found.append({'path': 'grantees', 'before': None, 'after': new['grantees']})
+    if old['grantees'] is not None and new['grantees'] is not None:
+        for field in ('people', 'ships_of'):
+            changed = (set(new['grantees'][field]) - set(old['grantees'][field]) if grows
+                       else set(old['grantees'][field]) - set(new['grantees'][field]))
+            for member in sorted(changed):
+                found.append({'path': f'grantees.{field}:{member}', 'before': None if grows else member,
+                              'after': member if grows else None})
+    return sorted(found, key=lambda item: item['path'])
+
+
+def widened_paths(baseline, policy):
+    """Spec Data: the paths that widen from baseline to policy, as [{path, before, after}], sorted by path."""
+    return _compare(baseline, policy, True)
+
+
+def narrowed_paths(baseline, policy):
+    """Spec Routes (preview): the same paths where policy is smaller or lacks a member."""
+    return _compare(baseline, policy, False)
+
+
+def confirm_paths(value):
+    """confirm_widenings as a list of paths; absent is []. 400 otherwise (spec Routes, activation step 5)."""
+    if value is None:
+        return []
+    if (not isinstance(value, list) or len(value) > MAX_WIDENINGS
+            or not all(isinstance(path, str) and len(path) <= 200 for path in value)):
+        raise Problem(400, 'confirm_widenings is a list of paths')
+    return value
+
+
+def require_confirmed(paths, widenings):
+    """C13: exactly the widened paths, each once, in any order; 409 naming them otherwise."""
+    wanted = [item['path'] for item in widenings]
+    if len(paths) != len(set(paths)) or set(paths) != set(wanted):
+        raise Problem(409, 'Confirm exactly these widenings: ' + (', '.join(wanted) or 'none'))
diff --git a/peer/superyak_peer/instructions.py b/peer/superyak_peer/instructions.py
index cae93a8..17b1396 100644
--- a/peer/superyak_peer/instructions.py
+++ b/peer/superyak_peer/instructions.py
@@ -8,6 +8,7 @@ from .ships import safe_line
 PREAMBLE = ('These instructions were signed by people and bind this ship. If two of them conflict, do not choose: '
             'ask in the room.')
 MAX_LAYERS, MAX_BYTES = 10, 48000
+CAPS_REFUSAL = '{ship} would have more than 10 instruction layers or 48,000 bytes of them'  # 4a stand-in (R16)
 DRAFTS_PER_HOUR = 10
 WAITING_DRAFTS, WAITING_DAYS = 20, 7  # a rolling window: layers cannot be deleted, so a lifetime cap could lock a ship out
 
@@ -16,11 +17,17 @@ def defuse_body(text):
     return '\n'.join(' ' + line if line.startswith(('===', "Instructions '")) else line for line in str(text).splitlines())
 
 
-def render_one(layer, station):
-    return (f'=== Instructions: {safe_line(layer["title"], 200)} · revision {layer["revision"]} · signed by '
+def render_one(layer, station):  # 4a stand-in: C25's charter word, without its brackets (4c's tests read neither)
+    kind = 'charter revision' if layer.get('charter') else 'revision'
+    return (f'=== Instructions: {safe_line(layer["title"], 200)} · {kind} {layer["revision"]} · signed by '
             f'{safe_line(layer["signer_name"])} on station {str(station)[:12]} ===\n{defuse_body(layer["body"])}')
 
 
+def over_caps(layers):
+    """4a stand-in: spec A's caps, 10 layers and 48,000 bytes of rendered blocks."""
+    return len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES
+
+
 def render_blocks(layers, station):
     return PREAMBLE + '\n\n' + '\n\n'.join(render_one(l, station) for l in layers) if layers else ''
 
@@ -37,16 +44,55 @@ class Instructions:
             if row:
                 snap = json.loads(row['snapshot'])
                 found.append({'layer_id': layer_id, 'revision': revision, 'title': snap['title'], 'body': snap['body'],
-                              'signer_id': row['owner_id'], 'signer_name': row['signer'], 'created': row['created']})
-        return sorted(found, key=lambda l: (l['created'], l['layer_id']))
+                              'signer_id': row['owner_id'], 'signer_name': row['signer'], 'created': row['created'],
+                              'charter': snap.get('charter') is True})
+        return found  # 4a stand-in (R15): in the order recorded
 
     def ship_instructions(self, actor, station):
         with self.transaction() as db:
             layers = self._binding_layers(db, actor)
+            charter = self._charter_status(db, require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()))
         return {'instructions': [[l['layer_id'], l['revision']] for l in layers],
                 'layers': [{'layer_id': l['layer_id'], 'revision': l['revision'], 'title': safe_line(l['title'], 200),
-                            'signer_name': safe_line(l['signer_name']), 'block': render_one(l, station)} for l in layers],
-                'blocks': render_blocks(layers, station)}
+                            'signer_name': safe_line(l['signer_name']), 'block': render_one(l, station),
+                            'charter': l['charter']} for l in layers],
+                'blocks': render_blocks(layers, station), 'charter': charter}
+
+    def _charter_status(self, db, ship):
+        """4a stand-in: GET /api/ships/me/instructions' charter field."""
+        active = self._active_charter(db)
+        if active is None:
+            return None
+        pair = self._charter_pair(db, ship)
+        accepted = not ship['owner_id'] or ship['owner_id'] == active['owner_id']
+        return {'layer_id': active['id'], 'revision': active['active_revision'],
+                'binding': pair[1] if pair and pair[0] == active['id'] else None, 'accepted': accepted}
+
+    def _charter_pair(self, db, ship):
+        """4a stand-in, spec Binding 2: a resident gets the active charter's active revision; the signer's ships too
+        (C17); any other owner's ship, none before 4c."""
+        active = self._active_charter(db)
+        if not ship['owner_id'] or (active is not None and ship['owner_id'] == active['owner_id']):
+            return (active['id'], active['active_revision']) if active is not None else None
+        return None
+
+    def _own_layers(self, db, ship, replace=None):
+        """4a stand-in, spec Binding 3: the owner's own active non-charter instructions layers that list the ship, by
+        (created, layer_id). replace substitutes one layer's snapshot, for an activation being checked."""
+        if not ship['owner_id']:
+            return []
+        signer = db.execute('SELECT name FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['name']
+        rows = [(r['layer_id'], r['revision'], json.loads(r['snapshot']), r['created']) for r in db.execute(
+            'SELECT layers.id AS layer_id, layer_revisions.revision, layer_revisions.snapshot, layer_revisions.created '
+            'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
+            'WHERE layers.owner_id=?', (ship['owner_id'],))]
+        if replace is not None:
+            rows = [r for r in rows if r[0] != replace['layer_id']] + [(replace['layer_id'], replace.get('revision', 0), replace['snapshot'], replace['created'])]
+        found = [{'layer_id': lid, 'revision': rev, 'title': snap['title'], 'body': snap['body'], 'signer_id': ship['owner_id'],
+                  'signer_name': signer, 'created': created, 'charter': False}
+                 for lid, rev, snap, created in rows
+                 if snap.get('kind') == 'instructions' and not snap.get('charter') and ship['id'] in snap.get('audience_users', [])]
+        return sorted(found, key=lambda l: (l['created'], l['layer_id']))
 
     def ship_draft(self, actor, data):
         """A ship drafts an instructions layer in its owner's name, addressed to itself. Only the owner can activate it."""
@@ -76,20 +122,12 @@ class Instructions:
             return {'id': key, 'title': draft['title'], 'version': 1, 'state': 'draft', 'drafted_by': actor}
 
     def _binding_layers(self, db, ship_id, replace=None):
+        """4a stand-in, spec Binding: the charter pair first, then the owner's own layers."""
         ship = require(db.execute('SELECT * FROM users WHERE id=?', (ship_id,)).fetchone())
-        if ship['kind'] != 'ship' or not ship['owner_id']:
+        if ship['kind'] != 'ship':
             return []
-        signer = db.execute('SELECT name FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['name']
-        rows = [(r['layer_id'], r['revision'], json.loads(r['snapshot']), r['created']) for r in db.execute(
-            'SELECT layers.id AS layer_id, layer_revisions.revision, layer_revisions.snapshot, layer_revisions.created '
-            'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
-            'WHERE layers.owner_id=?', (ship['owner_id'],))]
-        if replace is not None:
-            rows = [r for r in rows if r[0] != replace['layer_id']] + [(replace['layer_id'], replace.get('revision', 0), replace['snapshot'], replace['created'])]
-        found = [{'layer_id': lid, 'revision': rev, 'title': snap['title'], 'body': snap['body'], 'signer_id': ship['owner_id'],
-                  'signer_name': signer, 'created': created}
-                 for lid, rev, snap, created in rows if snap.get('kind') == 'instructions' and ship_id in snap.get('audience_users', [])]
-        return sorted(found, key=lambda l: (l['created'], l['layer_id']))
+        pair = self._charter_pair(db, ship)
+        return self._layers_for(db, [pair] if pair else []) + self._own_layers(db, ship, replace)
 
     def _check_instruction_caps(self, db, actor, key, snapshot):
         if not snapshot['audience_users']:
@@ -99,5 +137,13 @@ class Instructions:
             if not row or row['owner_id'] != actor:
                 continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
             layers = self._binding_layers(db, ship_id, replace={'layer_id': key, 'snapshot': snapshot, 'created': self.clock(), 'revision': 0})
-            if len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES:
-                raise Problem(409, 'That ship would have more than 10 instruction layers or 48,000 bytes of them')
+            if over_caps(layers):  # 4a stand-in (R16): each 409 names the ship
+                ship = db.execute('SELECT name FROM users WHERE id=?', (ship_id,)).fetchone()
+                raise Problem(409, CAPS_REFUSAL.format(ship=safe_line(ship['name'])))
+
+    def _check_charter_caps(self, db, signer_id):
+        """4a stand-in (C23 in 4a): with the new revision active, the residents and the signer's ships."""
+        for ship in db.execute("SELECT * FROM users WHERE kind='ship' AND (owner_id IS NULL OR owner_id=?) ORDER BY name, id",
+                               (signer_id,)).fetchall():
+            if over_caps(self._binding_layers(db, ship['id'])):
+                raise Problem(409, CAPS_REFUSAL.format(ship=safe_line(ship['name'])))
diff --git a/peer/superyak_peer/layers.py b/peer/superyak_peer/layers.py
index c9e13b8..654e0a4 100644
--- a/peer/superyak_peer/layers.py
+++ b/peer/superyak_peer/layers.py
@@ -1,8 +1,9 @@
 """Owner-only drafts and immutable, explicitly activated release snapshots."""
 import json
 from .common import Problem, text, ids, uid, require, encode
+from .charter import DEFAULT_POLICY, confirm_paths, full_policy, require_confirmed, widened_paths  # 4a stand-in
 
-FIELDS = {'kind', 'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids'}
+FIELDS = {'kind', 'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids', 'charter', 'policy'}
 DEFAULT = {'kind': 'note', 'title': 'Untitled', 'body': '', 'audience_users': [], 'audience_spaces': [], 'public': False, 'attachment_ids': []}
 SERVER_KEYS = {'drafted_by', 'drafted_at'}
 
@@ -45,10 +46,28 @@ class Layers:
             attachment_size += require(db.execute('SELECT size FROM files WHERE id=? AND owner_id=?', (key, actor)).fetchone())[0]
         if any(u.startswith('remote_') for u in draft['audience_users']) and attachment_size > 4 * 1024 * 1024:
             raise Problem(400, 'Remote release attachments exceed 4 MiB')
+        if draft.get('charter') is True:  # 4a stand-in: a charter is instructions with no audience
+            if draft['kind'] != 'instructions' or draft['audience_users']:
+                raise Problem(400, 'A charter names no ships: it binds every ship whose owner accepts it')
+        else:
+            draft.pop('charter', None)
+            draft.pop('policy', None)
         if draft['kind'] == 'note':
             del draft['kind']  # never stored for a note: a rolled-back station refuses any key it does not know
         return draft
 
+    def _active_charter(self, db):
+        """4a stand-in: the one layer whose active revision is a charter revision, or None."""
+        for row in db.execute('SELECT layers.*, layer_revisions.snapshot FROM layers JOIN layer_revisions ON '
+                              'layer_revisions.layer_id=layers.id AND layer_revisions.revision=layers.active_revision').fetchall():
+            if json.loads(row['snapshot']).get('charter') is True:
+                return row
+        return None
+
+    def _policy_in_force(self, db):
+        active = self._active_charter(db)
+        return json.loads(active['snapshot'])['policy'] if active else DEFAULT_POLICY
+
     def _owned_layer(self, db, actor, key):
         return require(db.execute('SELECT * FROM layers WHERE id=? AND owner_id=?', (key, actor)).fetchone())
 
@@ -103,12 +122,14 @@ class Layers:
             return {**self._layer_json(row), 'files':files, 'people':people, 'audience_details':details,
                     'space_versions':{space['id']:space['version'] for space in details}}
 
-    def activate_layer(self, actor, key, version, space_versions=None):
+    def activate_layer(self, actor, key, version, space_versions=None, confirm_widenings=None):
         with self.transaction() as db:
             row = self._owned_layer(db, actor, key)
             if type(version) is not int or version != row['version']:
                 raise Problem(409, 'Draft changed; preview this version again')
             snapshot = self._draft(db, actor, json.loads(row['draft']), stored=True)
+            if snapshot.get('charter') is True:  # 4a stand-in
+                return self._activate_charter(db, actor, key, row, version, snapshot, confirm_widenings)
             if snapshot.get('kind') == 'instructions':
                 self._check_instruction_caps(db, actor, key, snapshot)
             if space_versions is not None:
@@ -131,9 +152,38 @@ class Layers:
             self.emit(db, 'layer.activated', key, revision, {'owner_id': actor, 'draft_version': version})
             return self._active_layer(db, key, actor)
 
-    def withdraw_layer(self, actor, key):
+    def _activate_charter(self, db, actor, key, row, version, snapshot, confirm_widenings):
+        """4a stand-in: C3, the one-charter check, C13's widenings against the policy in force, caps for the signer's
+        ships and the residents with the new revision active, then the revision written and signed."""
+        self._super_admin_signs(db, actor)
+        active = self._active_charter(db)
+        if active is not None and active['id'] != key:
+            raise Problem(409, 'Another charter is active; its owner must withdraw it first')
+        paths = confirm_paths(confirm_widenings)
+        snapshot['policy'] = full_policy(snapshot.get('policy'))
+        require_confirmed(paths, widened_paths(self._policy_in_force(db), snapshot['policy']))
+        snapshot['audience_users'] = []
+        snapshot['resolved_space_users'], snapshot['audience_notes'] = {}, []
+        revision = row['resource_version'] + 1
+        db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
+        db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
+        self._check_charter_caps(db, actor)
+        self._sign_revision(db, key, revision)
+        self.emit(db, 'layer.activated', key, revision, {'owner_id': actor, 'draft_version': version})
+        return self._active_layer(db, key, actor)
+
+    def _super_admin_signs(self, db, actor):
+        row = require(db.execute('SELECT is_super_admin, activation_pending FROM users WHERE id=?', (actor,)).fetchone())
+        if not row['is_super_admin'] or row['activation_pending']:
+            raise Problem(403, "Only a super admin can sign the station's charter")
+
+    def withdraw_layer(self, actor, key, confirm_widenings=None):
         with self.transaction() as db:
             row = self._owned_layer(db, actor, key)
+            active = self._active_charter(db)
+            if active is not None and active['id'] == key:  # 4a stand-in, C15
+                paths = confirm_paths(confirm_widenings)
+                require_confirmed(paths, widened_paths(json.loads(active['snapshot'])['policy'], DEFAULT_POLICY))
             if row['active_revision'] is not None:
                 revision = row['resource_version'] + 1
                 db.execute('UPDATE layers SET active_revision=NULL,resource_version=? WHERE id=?', (revision, key))
diff --git a/peer/superyak_peer/signatures.py b/peer/superyak_peer/signatures.py
index f8a545f..2d4a806 100644
--- a/peer/superyak_peer/signatures.py
+++ b/peer/superyak_peer/signatures.py
@@ -91,7 +91,9 @@ class Signatures:
             return None
         return {'kind': 'instructions-revision', 'station': self._station_identity(db).peer_id, 'layer_id': layer_id,
                 'revision': revision, 'owner_id': row['owner_id'], 'title': snapshot['title'], 'body': snapshot['body'],
-                'audience_users': snapshot['audience_users'], 'policy': None, 'created': row['created']}
+                'audience_users': snapshot['audience_users'],
+                'policy': snapshot.get('policy') if snapshot.get('charter') is True else None,  # 4a stand-in (C12)
+                'created': row['created']}
 
     def _sign_revision(self, db, layer_id, revision):
         """G2: in the transaction that writes the revision. A note's revision is not signed."""
@@ -112,17 +114,25 @@ class Signatures:
                 self._sign_revision(db, row['layer_id'], row['revision'])
 
     def revision_signed(self, actor, layer_id, revision):
-        """G6: {station, record, signature} for the layer's owner. Anyone else, and any revision without a signature
-        (a note's, or one that doesn't exist), gets 404, so the route never says whether a layer exists."""
+        """G6 as C26 widens it (4a stand-in): the owner; for a charter revision, also the readers C26 names."""
         with self.transaction() as db:
-            self._owned_layer(db, actor, layer_id)
             if not 1 <= revision <= 2 ** 63 - 1:  # past SQLite's integers sqlite3 raises OverflowError; no such revision
                 raise Problem(404, 'Not found')
+            layer = db.execute('SELECT * FROM layers WHERE id=?', (layer_id,)).fetchone()
             row = require(db.execute('SELECT signature FROM revision_signatures WHERE layer_id=? AND revision=?',
-                                     (layer_id, revision)).fetchone())
+                                     (layer_id, revision)).fetchone() if layer else None)
+            if layer['owner_id'] != actor:
+                snapshot = json.loads(db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?',
+                                                 (layer_id, revision)).fetchone()['snapshot'])
+                if snapshot.get('charter') is not True or not self._may_read_charter_revision(db, actor, layer, revision):
+                    raise Problem(404, 'Not found')
             return {'station': self._station_identity(db).peer_id, 'record': self._revision_record(db, layer_id, revision),
                     'signature': row['signature']}
 
+    def _may_read_charter_revision(self, db, actor, layer, revision):
+        """4a stand-in (C26): any person reads the active charter revision; other charter revisions only the signer."""
+        return layer['active_revision'] == revision
+
     def _grant_record(self, db, grant_id):
         """G12: a grant's record, with exactly RECORD_KEYS['grant'], from its stored row: actions, targets and rooms as
         parsed JSON values, not their stored text. Columns a later step adds stay out, so old signatures keep verifying.
diff --git a/peer/tests/test_instructions.py b/peer/tests/test_instructions.py
index 6e2531d..dfb3733 100644
--- a/peer/tests/test_instructions.py
+++ b/peer/tests/test_instructions.py
@@ -222,7 +222,7 @@ def test_a_ship_reads_its_binding_instructions_with_each_block(env):
     assert got['instructions'] == [[layer['id'], 1]]
     assert got['layers'][0]['block'] == f'=== Instructions: House rules · revision 1 · signed by Patient on station {peer_id[:12]} ===\nRun the tests first.'
     assert got['blocks'] == 'These instructions were signed by people and bind this ship. If two of them conflict, do not choose: ask in the room.\n\n' + got['layers'][0]['block']
-    assert instructions_of(app, docked(app.state.store, users[1]['id'], 'defiant')[1]) == {'instructions': [], 'layers': [], 'blocks': ''}
+    assert instructions_of(app, docked(app.state.store, users[1]['id'], 'defiant')[1]) == {'instructions': [], 'layers': [], 'blocks': '', 'charter': None}
 
 
 def test_withdrawing_or_narrowing_takes_effect_at_once(env):
```
