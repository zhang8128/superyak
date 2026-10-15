# Spec A step 4, merge 4a: the station's charter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The law can become the station's charter through the API. An instructions layer can be drafted and signed
as a charter, only by a super admin and one at a time. Its policy (version 1, with defaults) is checked, stored in full,
signed with the revision, and governs every grant on the station. Every widened limit is confirmed path by path at
signing and at withdrawal. The active charter binds its signer's ships and the resident ships first, counted once in
the caps. Headers bracket titles and mark the charter, build footers name the charter revision a ticket recorded,
everyone reads the active charter's signed record, and the agent's status, draft tool and hook show it. No charter is
activated in 4a; 4b (the signer's web views) and 4c (acceptance by other owners) are later merges.

**Architecture:** A new module, `peer/superyak_peer/charter.py`, holds the policy schema (`full_policy`), the widened
and narrowed paths (`widened_paths`, `narrowed_paths`, `confirm_paths`, `require_confirmed`), the draft checks (`check_draft`), `flat_policy`, and a `Charter`
mixin on `Store` that finds the active charter (a layer whose active revision's snapshot has `charter: true`), checks a
charter's activation, previews it, and gives the policy in force. `layers.py` runs the charter checks first in
`_draft`, keeps a charter a charter (C6), and checks activation, withdrawal and narrowing. `instructions.py` puts the
charter pair first in `_binding_layers`, keeps `_layers_for` in recorded order, counts the charter in the caps,
brackets block headers, and adds the ship route's `charter` field and charter drafts. `grants.py`'s `_grant_policy`
reads the policy in force, and making a grant gains G8's steps 0 and 3a. `signatures.py` signs the snapshot's policy
and serves the active charter revision to every person. `tickets.py` appends ` · charter rN` to a build footer from the
ticket's record. The agent brackets titles in `status` and the hook's short header, prints one charter line, and its
draft tool sends `charter` and `policy`. There is no schema change: a charter is a layer revision whose snapshot holds
`charter: true`, `audience_users: []` and the full policy.

**Tech Stack:** Python 3.11 (the Pi's venvs), FastAPI, SQLite (`json_extract`), pytest with FastAPI's
`TestClient` (peer), the agent suite's fake station (`agent/tests/conftest.py`). Peer tests run from `peer/` with
`PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider <files>`; agent tests from `agent/`
with `PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <files>`.

**Spec:** `docs/superpowers/specs/2026-10-15-charter-step4-design.md`, revision 3, approved under D8: its "Build order"
4a, R1-R23 and Testing 1-23, with C1-C31, "Routes", "Data", "Binding" and its Deploy. Spec A
(`docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`) and the step 3 spec
(`docs/superpowers/specs/2026-10-15-grants-step3-design.md`) hold where it is silent.

**Base:** branch `charter-4a` at `9f9683e`: main `c29e91e` (grants step 3 complete) plus the survey (`86d2919`) and the
spec's three revisions (`592faa3`, `a30e8fe`, `9f9683e`), all docs. Every anchor below applies at `9f9683e`, in task
order. If main moves before building, merge it and re-check the anchors first: every edit names its text exactly, so a
moved anchor fails loudly instead of landing in the wrong place.

**Dry run.** Every task was applied in order in a scratch worktree at `9f9683e`, each RED and GREEN run on the files
named, and each mutation applied alone, seen failing the test it names, and restored with `git checkout`. At the end of
that first pass the agent suite ran `758 passed` (755 at the base, plus this plan's 3 tests) and the peer suite `961
passed` (936 at the base, plus 25; test 14 replaces one old test). This revision then adopted merge 4c's interface names
and seams (see Interfaces for 4c): `widened_paths`, `narrowed_paths`, `confirm_paths` and `require_confirmed` (Task 4),
`_active_charter` as the layers row (Task 3), `_charter_pair` and `_own_layers` under `_binding_layers` (Task 7),
`over_caps`, `CAPS_REFUSAL` and the charter caps checked once the revision is active (Task 8, ruling P14),
`_may_read_charter_revision` (Task 10), `_charter_status` (Task 11) and `charter_line(charter)` (Task 12); it also
renamed a local in `activate_layer` and added one assertion to test 11. A clean replay of all fourteen tasks then
applied this file's own code blocks (the plan is rendered from the edits the replay applied, so its code is the code
that ran): every RED and GREEN count below is unchanged from the first pass, all 78 mutations failed, and the fourteen
peer test files the changes touch (`test_charter`, `test_instructions`, `test_layers`, `test_signatures`,
`test_tickets`, `test_grant_tickets`, `test_grants`, `test_ship_agent`, `test_deferrals`, `test_breakouts`,
`test_federation`, `test_restore`, `test_key_refusal`, `test_auth`) ran `409 passed` on the replayed tree. The whole
suites were not run again; Task 14's step runs them.

Tasks: 1 the policy schema; 2 charter drafts; 3 signing a charter (super admin, one at a time, a charter stays one, the
full policy stored and signed); 4 widened paths confirmed at activation, and the preview; 5 withdrawal and narrowing;
6 the policy in force for grants; 7 binding, the law converted in place, the oracle; 8 the caps; 9 headers and footers;
10 the signed record's readers; 11 the ship routes; 12 the agent's status and hook header; 13 the agent's draft tool;
14 the docs and the whole suites.

## Global Constraints

- Policy version 1 defaults: `{"version": 1, "delegation": {"max_depth": 3, "max_expiry_hours": 720, "agent_grant_default_hours": 24, "delegable": ["direct"]}, "budgets": {"builds_per_ship_per_day": 20}, "grantees": null}`.
- `delegation.max_depth`: whole, 0–5. `delegation.max_expiry_hours`: whole, 1–2,160. `budgets.builds_per_ship_per_day`: whole, 0–500.
- `delegation.agent_grant_default_hours`: whole, 1–2,160, at most `max_expiry_hours`; missing, it is 24 or `max_expiry_hours`, whichever is smaller.
- `delegation.delegable`: each of `["direct"]` at most once; `merge`, `deploy`, `admit` refused as reserved for spec B.
- `grantees`: `null`, or `{people, ships_of}`, each a list of ids of local person accounts, each once; `[]` when missing from an object; at most 100 ids together.
- `roots` and `breaker` are refused with 400: reserved for step 5. Unknown keys at any level and wrong types are refused with 400 naming the path (a boolean is never a number; `3.0` is not a whole number).
- The defaults are filled first; then every bound and cross-check runs on the full policy. The revision stores the full policy; the draft keeps what was written.
- Widened paths: `delegation.max_depth`, `delegation.max_expiry_hours`, `delegation.agent_grant_default_hours`, `budgets.builds_per_ship_per_day` (grows); `delegation.delegable:<action>` (gained); `grantees` (restricted to null); `grantees.people:<id>`, `grantees.ships_of:<id>` (both restricted, id gained). Sorted by path, code point order; each `{path, before, after}`.
- `confirm_widenings`: exactly the widened paths, each once, any order; at most 105 strings of at most 200 characters; absent is `[]`.
- Draft refusals, in order: 400 "charter is true or false"; (save) 409 "This layer is the station's charter and stays one; withdraw it to end it"; 400 "Only instructions can be a charter"; 400 "A charter names no ships: it binds every ship whose owner accepts it"; 400 "A policy belongs only on a charter"; 400 naming the path.
- Charter activation refusals, in order: 403 "Only a super admin can sign the station's charter"; 409 "Another charter is active; its owner must withdraw it first"; 400 "confirm_widenings is a list of paths"; 409 "Confirm exactly these widenings: …"; 409 "<ship> would have more than 10 instruction layers or 48,000 bytes of them".
- Any other layer: 400 "Only a charter has widenings to confirm" when `confirm_widenings` is non-empty.
- Narrowing a charter: 409 "A charter has no audience to narrow; sign a new revision or withdraw it"; nothing written.
- Withdrawal: an empty body is `{}`; an active charter needs `confirm_widenings` for the paths that widen from its policy to the defaults.
- Grants: while `max_depth` is 0, 400 "The station's charter allows no grants" (step 0); a grantee outside `people`, 400 "The station's charter doesn't allow grants to this person" (step 3a); validity's reason stays "… is no longer allowed by the station's policy".
- `GET /api/grants/policy`: `{max_depth, max_expiry_hours, builds_per_ship_per_day}` from the policy in force.
- Caps: 10 layers and 48,000 bytes per ship (`MAX_LAYERS`, `MAX_BYTES`), the charter counted once.
- Header: `=== Instructions: [<title>] · revision <n> · signed by …`, or `· charter revision <n> ·`; `[` and `]` inside a title shown as `(` and `)`.
- Build footer ending ` · charter r<n>`, n from the ticket's record; read tickets keep an empty footer.
- Status: `[<title>] · revision <n> · signed by <name>` (or `· charter revision <n> ·`), then one of "Charter: none active", "Charter: revision N binds this ship", "Charter: revision N is pending for this ship's owner; revision M binds this ship", "Charter: revision N is active; this ship's owner has not accepted it"; no charter line without the field.
- `GET /api/ships/me/instructions`: `layers[].charter: true | false`, and `charter: null | {layer_id, revision, binding, accepted}`.
- `POST /api/ships/me/drafts {title, body, charter?, policy?}`: a key other than these four, 400; a charter draft has an empty audience.
- The signed record keeps kind `instructions-revision` and its keys; `policy` is the full policy on a charter revision, `null` on every other.
- Production SQL names its columns; each new module and test file joins `peer/pyproject.toml`'s lists.
- No charter is activated in 4a. The merge goes under section 2 of the station law: approved in the room, the Pi suites passing.

## Review Focus

The inputs most likely to bite a person first. Each is pinned by a test in its task.

1. One widened number hidden among twenty changed prose lines, or a confirmation of "anything": Andy would sign a wider
   limit without its checkbox. Refused until that exact path is confirmed (Task 4,
   `test_one_widened_number_among_twenty_changed_lines_is_refused_until_confirmed`).
2. The law converted in place while the signing fails half-way: Andy's ships must stay bound by the plain law, never by
   nothing (Task 7, `test_the_law_becomes_the_charter_in_place_in_one_transaction`).
3. A ship already at 10 layers when its law is converted: the converted layer must count once, or Andy can't sign at all
   (Task 8, `test_the_caps_count_the_charter_once_for_every_ship_it_binds`).
4. Withdrawing a charter that narrowed a limit: the defaults come back wider, so the withdrawal must confirm them, or a
   limit grows with no checkbox (Task 5, `test_withdrawing_a_charter_confirms_what_returns_to_the_defaults`).
5. A layer titled `a] · revision 9 · signed by Jenn [b`: an unbracketed or closable title could forge a header's
   revision and signer in a ship's prompt (Task 9, `test_a_block_header_brackets_its_title_and_marks_the_charter`;
   Task 12 pins `status`, `test_status_brackets_titles_and_prints_one_charter_line`).

## Rulings

Where the spec leaves a choice open, this plan decides; a fresh reviewer checks each, and Andy can veto any.

| # | Ruling | Why |
| --- | --- | --- |
| P1 | The charter checks run before the old "Unknown layer field" check, which "Routes" counts among "every other existing draft check" (step 7). A request with both an unknown field and a bad policy gets the policy's 400. | R1's order, read literally; nothing is written either way. Test 1's route rows pin it. |
| P2 | C6 at a save is `check_draft`'s second check (after the flag's type); at activation it is a pre-check on the stored draft before `_draft`, so a hand-edited draft that lost its flag but kept its policy gets 409, not the 400 for a policy without a charter. | "Routes": the save's step 2 and the activation's step 3 come before the other draft checks. Test 8. |
| P3 | A charter is found by `json_extract(snapshot, '$.charter')=1` on the active revision; a layer "has a charter revision" when any of its revisions has it. | No schema change; C12 marks a charter revision by its snapshot. |
| P4 | In 4a, the ship route's `accepted` is true exactly when the charter binds the ship (a resident, or the signer's ship). 4c adds owners who accepted it. | "Routes": "whether its owner signed or accepted it (always true for a resident)"; in 4a only signing exists. |
| P5 | The preview's `charter` object takes the place of the draft's boolean `charter` in the preview's answer, which spreads the draft: a charter draft's preview has the object, any other draft's has no `charter` key. | "Routes" names both `charter`; one key can hold one value. Reported as a spec collision. |
| P6 | `binds` and the charter caps visit the residents and the signer's ships by name (case-insensitive), then id; the first ship over the caps is named. `names` covers the ids in the baseline's and the new policy's grantee sets. | Stable output; the spec gives no order. |
| P7 | C23's last sentence (an owner's own activation that would change which charter revision binds their ships) has nothing to check in 4a: only the signer's ships and residents are bound, and own layers never move a charter pair. 4c adds the check with the follow walk. R16's "an owner's own activation counts the charter" holds through `_binding_layers`. | It can't happen before acceptances exist. |
| P8 | `delegable` is checked for a link whose issuer's `users.kind` is `ship`; a browser root's issuer is a person. | R12; step 3 makes only browser roots. Test 13 hand-makes a ship-issued child. |
| P9 | The withdraw route reads a body only when one is sent and ignores keys other than `confirm_widenings`. | "An empty body counts as `{}`, so old clients still work"; the spec lists no other key. |
| P10 | The policy's refusal texts are this plan's (each starts with its path); an unknown key's name passes through `safe_line(key, 40)`. | The spec fixes only "naming the path"; a key is caller text. |
| P11 | `status` brackets `label(title)` (80 characters, as today); the hook's `_header` brackets the station's title as sent (up to 200, as today). | Each keeps its existing length limit; only the brackets and the charter mark change. |
| P12 | `GET /api/grants/policy` takes a person session, like every `/api/grants` route; a ship key gets 403. | Step 3's G14. |
| P13 | A ship's charter draft answers with the same `{id, title, version, state, drafted_by}` as any draft; the tool's text says it is a charter. | "Routes" changes the request only. |
| P14 | A charter's activation writes its revision and makes it active, then checks the caps (`_check_charter_caps`), then signs it, all in one transaction: a 409 rolls the write back before anything is signed. Every binding the caps measure is then the one tickets will read, and a converted layer counts once, its old revision no longer active. | It keeps one binding function with no stand-in for the charter, which is what merge 4c's `_charter_pair` builds on (its I9). The refusals' order is unchanged: nothing else can refuse a charter after step 5. |

## Interfaces for 4c

Merge 4c's plan (`origin/charter-4c` at `446e013`, "Interfaces 4c consumes from 4a") names the 4a functions it builds on.
This plan adopts its names and signatures, and builds its four seams (I8, I10, I14, I16) as separately callable
functions with no behaviour of their own. Two rows keep 4a's form, for the reasons given.

| # | 4c's name | 4a's name and signature | Task |
| --- | --- | --- | --- |
| I1 | `charter.DEFAULT_POLICY` | the same | 1 |
| I2 | `charter.widened_paths(baseline, policy)` | the same: `-> list[dict]`, `{path, before, after}`, sorted by path | 4 |
| I3 | `charter.narrowed_paths(baseline, policy)` | the same | 4 |
| I4 | `charter.confirm_paths(value)` | the same: `None` is `[]`, else 400 "confirm_widenings is a list of paths" | 4 |
| I5 | `charter.require_confirmed(paths, widenings)` | the same: 409 "Confirm exactly these widenings: …" | 4 |
| I6 | `instructions.over_caps(layers)`, `instructions.CAPS_REFUSAL` | the same; `CAPS_REFUSAL.format(ship=...)` | 8 |
| I7 | `Instructions._layers_for(db, pairs)` | the same: recorded order, each dict with `charter` | 7 |
| I8 | `Instructions._own_layers(db, ship, replace=None)` | the same; `replace` is `{layer_id, revision, snapshot, created}`, `revision` the next revision number | 7 |
| I9 | `Instructions._charter_pair(db, ship)`, `_binding_layers` built on it | the same: `-> (layer_id, revision) \| None`; `_binding_layers(db, ship_id, replace=None)` = `_layers_for(db, [pair])` + `_own_layers(db, ship, replace)` | 7 |
| I10 | `Instructions._charter_status(db, ship)` | the same: `-> {layer_id, revision, binding, accepted} \| None` | 11 |
| I11 | `Layers._active_charter(db) -> sqlite3.Row \| None` | `_active_charter(db) -> sqlite3.Row \| None`, the layers row (`id`, `owner_id`, `active_revision`, ...) plus its active revision's `snapshot` as JSON text. Kept on the `Charter` mixin in `charter.py`, with the other charter rules: callers use `self._active_charter`, which `Store` resolves either way | 3 |
| I12 | The charter activation, after `require_confirmed`, before the revision row is written | the end of `Charter._check_charter_activation(db, actor, key, snapshot, confirm=None)`, before `return policy`. 4a's own charter caps (`_check_charter_caps(db, signer_id)`) run later, once the revision is written and active (P14) | 4, 8 |
| I13 | The ordinary activation, right after `self._check_instruction_caps(db, actor, key, snapshot)` | right after `self._check_instruction_caps(db, actor, key, snapshot, row['resource_version'] + 1)` in `Layers.activate_layer`. Kept with its `revision` argument: the caps measure the text the revision will render, its number included | 7 |
| I14 | `Signatures._may_read_charter_revision(db, actor, layer, revision)` | the same: `-> bool`; `revision_signed` asks it only for a charter revision and a caller who doesn't own the layer | 10 |
| I15 | Spec data and routes | as the spec gives them: the snapshot's `charter`, `audience_users: []` and full `policy`; `charter` and `policy` on drafts; `confirm_widenings` on activate and withdraw | 2-5 |
| I16 | `superyak_agent.station.charter_line(charter)` | the same: `-> str \| None`, from the field's value; `status` calls it only when the answer has the field | 12 |

Also in 4a, not in 4c's table: `charter.full_policy(db, raw)` takes `db`, since it checks that grantee ids are people
(4c's stand-in has `full_policy(policy)`); `Charter._policy_in_force(db)` (Task 4) returns the full policy in force;
`Instructions._check_charter_caps(db, signer_id)` (Task 8) has the stand-in's name and arguments.

## Known limits (beyond the spec's)

- The resident caps test needs a body of 20,000 three-byte characters: one layer can't otherwise pass 48,000 bytes.
- The oracle (test 23) compares the full ordered list for 80 seeded steps (seed 20261015), 25% of them charter steps;
  it asserts each charter event (activated, revised, withdrawn, activated again, a second refused) happened at least
  once. Spec A's 500 cases with pins and follows are 4c's test 35.
- Test 22's first half (the changed block, no "no longer apply" line) passes before Task 12: the hook already keys
  notices by layer id. Its RED is the short header, and mutation 8 of Task 12 shows the first half bites.
- Test 3's ship-key rows and test 9's first two rows pass before their tasks (`current_user` and today's narrowing
  refusals answer first); they guard that order.

## File Structure

- Create `peer/superyak_peer/charter.py` (Tasks 1-6, 8): the schema, the paths, the draft checks, `flat_policy`, the
  `Charter` mixin.
- Modify `peer/superyak_peer/layers.py` (Tasks 2-5, 7, 8): `FIELDS`, `_draft`, `save_layer`, `preview_layer`,
  `activate_layer`, `withdraw_layer`, `revoke_layer_routes`.
- Modify `peer/superyak_peer/instructions.py` (Tasks 7-9, 11): the module docstring, `binding_entry`, `bracketed`,
  `render_one`, `over_caps`, `CAPS_REFUSAL`, `_layers_for`, `_charter_pair`, `_own_layers`, `_binding_layers`, the caps,
  `_charter_status`, `ship_instructions`, `ship_draft`.
- Modify `peer/superyak_peer/grants.py` (Task 6), `signatures.py` (Tasks 3, 10), `tickets.py` (Task 9), `db.py`
  (Task 3), `app.py` (Tasks 4-6), `peer/pyproject.toml` (Task 1), `peer/API.md` (Task 14).
- Modify `agent/superyak_agent/station.py` (Tasks 12, 13), `__main__.py` and `hook.py` (Task 12), `mcp.py` (Task 13),
  `agent/README.md` (Task 14).
- Create `peer/tests/test_charter.py` (tests 1-13, 16, 17, 19, 7, and the station parts of 20 and 21). Modify
  `peer/tests/test_instructions.py` (`crown`; tests 14, 15, 18, 23; headers; the route's `charter`),
  `agent/tests/test_status.py` (test 20), `agent/tests/test_hook.py` (test 22), `agent/tests/test_mcp.py` and
  `agent/tests/conftest.py` (test 21).

---

### Task 1: The policy schema, version 1 (C11, "Data")

**Files:**
- Create: `peer/superyak_peer/charter.py` (about 95 lines)
- Create: `peer/tests/test_charter.py` (about 95 lines)
- Modify: `peer/pyproject.toml` (the sdist and wheel lists, 3 lines)

**Interfaces:**
- Consumes: `common.Problem`; `ships.safe_line(value, limit)`.
- Produces: `charter.DEFAULT_POLICY`; `charter.full_policy(db, raw) -> dict` (a new full policy; `Problem(400, "<path> …")` otherwise; `raw` None is the defaults); constants `SECTIONS`, `NUMBERS`, `ACTIONS`, `RESERVED_ACTIONS`, `RESERVED_KEYS`, `MAX_GRANTEES`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_charter.py` with:

```python
"""The station's charter (spec A step 4, merge 4a: docs/superpowers/specs/2026-10-15-charter-step4-design.md, R1-R23
and tests 1-23)."""
import copy
from superyak_peer.charter import DEFAULT_POLICY, full_policy
from superyak_peer.common import Problem, uid
from test_instructions import docked


def people(store, count):
    """count person accounts, written directly (scrypt is slow): their ids, in order."""
    with store.transaction() as db:
        made = [uid() for _ in range(count)]
        db.executemany("INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind) "
                       "VALUES(?,?,?,?,?,0,?,'person')",
                       [(key, f'person-{n:03d}', f'Person {n:03d}', b'\0' * 16, b'\0' * 32, store.clock())
                        for n, key in enumerate(made)])
    return made


def checked(store, raw):
    """full_policy's answer: the full policy, or (status, error)."""
    with store.transaction() as db:
        try:
            return full_policy(db, raw)
        except Problem as refused:
            return refused.status, refused.message


def test_a_policy_refuses_each_bad_value_and_names_its_path(env):
    """Test 1, the policy's rows (C11, "Data"): unknown keys at any level, reserved names, a wrong type (a boolean is
    never a number; 3.0 is not a whole number), each bound one step outside, and bad grantees; each 400 names the path.
    Catches a validator that checks only top-level keys, takes a boolean as 1 or allows a reserved name."""
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    many = people(store, 101)

    def delegation(**fields):
        return {'version': 1, 'delegation': fields}
    for raw, path in (
            ('strict', 'policy'), ({'version': 1, 'colour': 'red'}, 'policy.colour'),
            (delegation(max_depth=3, colour='red'), 'policy.delegation.colour'),
            ({'version': 1, 'budgets': {'colour': 1}}, 'policy.budgets.colour'),
            ({'version': 1, 'grantees': {'people': [], 'colour': []}}, 'policy.grantees.colour'),
            ({'version': 1, 'delegation': [3]}, 'policy.delegation'), ({'version': 1, 'budgets': 20}, 'policy.budgets'),
            ({}, 'policy.version'), ({'version': 2}, 'policy.version'), ({'version': True}, 'policy.version'),
            ({'version': 1.0}, 'policy.version'),
            (delegation(max_depth=-1), 'policy.delegation.max_depth'), (delegation(max_depth=6), 'policy.delegation.max_depth'),
            (delegation(max_depth=True), 'policy.delegation.max_depth'), (delegation(max_depth=3.0), 'policy.delegation.max_depth'),
            (delegation(max_expiry_hours=0), 'policy.delegation.max_expiry_hours'),
            (delegation(max_expiry_hours=2161), 'policy.delegation.max_expiry_hours'),
            (delegation(max_expiry_hours='720'), 'policy.delegation.max_expiry_hours'),
            (delegation(max_expiry_hours=24, agent_grant_default_hours=25), 'policy.delegation.agent_grant_default_hours'),
            (delegation(agent_grant_default_hours=0), 'policy.delegation.agent_grant_default_hours'),
            ({'version': 1, 'budgets': {'builds_per_ship_per_day': 501}}, 'policy.budgets.builds_per_ship_per_day'),
            ({'version': 1, 'budgets': {'builds_per_ship_per_day': -1}}, 'policy.budgets.builds_per_ship_per_day'),
            ({'version': 1, 'budgets': {'builds_per_ship_per_day': True}}, 'policy.budgets.builds_per_ship_per_day'),
            (delegation(delegable=['x']), 'policy.delegation.delegable'),
            (delegation(delegable=['direct', 'direct']), 'policy.delegation.delegable'),
            (delegation(delegable='direct'), 'policy.delegation.delegable'),
            ({'version': 1, 'grantees': []}, 'policy.grantees'),
            ({'version': 1, 'grantees': {'people': [ship['id']]}}, 'policy.grantees.people'),
            ({'version': 1, 'grantees': {'ships_of': ['no-such-person']}}, 'policy.grantees.ships_of'),
            ({'version': 1, 'grantees': {'people': [users[1]['id'], users[1]['id']]}}, 'policy.grantees.people'),
            ({'version': 1, 'grantees': {'people': users[1]['id']}}, 'policy.grantees.people'),
            ({'version': 1, 'grantees': {'people': many[:51], 'ships_of': many[51:]}}, 'policy.grantees')):
        status, error = checked(store, raw)
        assert status == 400 and error.split(' ', 1)[0].rstrip(':') == path, (raw, error)
    for key in ('roots', 'breaker'):
        assert checked(store, {'version': 1, key: {}}) == (400, f'policy.{key} is reserved for step 5')
    for action in ('merge', 'deploy', 'admit'):
        assert checked(store, delegation(delegable=[action])) == (400, f'policy.delegation.delegable: {action} is reserved for spec B')


def test_a_policy_fills_its_defaults_before_its_cross_check(env):
    """Test 1's accepted rows and R2's filling: a missing policy, section or key takes the default; a missing
    agent_grant_default_hours is 24 or max_expiry_hours, whichever is smaller, filled before the cross-check runs; each
    bound itself is allowed; the given policy is never changed. Catches a cross-check run before the filling."""
    app, clients, users, clock = env
    store = app.state.store
    many = people(store, 100)
    assert checked(store, None) == DEFAULT_POLICY and checked(store, {'version': 1}) == DEFAULT_POLICY
    assert DEFAULT_POLICY == {'version': 1, 'delegation': {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24,
                                                           'delegable': ['direct']},
                              'budgets': {'builds_per_ship_per_day': 20}, 'grantees': None}
    short = {'version': 1, 'delegation': {'max_expiry_hours': 12}}
    assert checked(store, short)['delegation'] == {'max_depth': 3, 'max_expiry_hours': 12, 'agent_grant_default_hours': 12,
                                                   'delegable': ['direct']}
    assert short == {'version': 1, 'delegation': {'max_expiry_hours': 12}}  # the draft keeps what was written
    edges = {'version': 1, 'delegation': {'max_depth': 0, 'max_expiry_hours': 2160, 'agent_grant_default_hours': 2160,
                                          'delegable': []},
             'budgets': {'builds_per_ship_per_day': 500}, 'grantees': {'people': many[:50], 'ships_of': many[50:]}}
    assert checked(store, copy.deepcopy(edges)) == edges
    lowest = {'version': 1, 'delegation': {'max_depth': 5, 'max_expiry_hours': 1}, 'budgets': {'builds_per_ship_per_day': 0},
              'grantees': {}}
    assert checked(store, lowest) == {'version': 1, 'delegation': {'max_depth': 5, 'max_expiry_hours': 1,
                                                                   'agent_grant_default_hours': 1, 'delegable': ['direct']},
                                      'budgets': {'builds_per_ship_per_day': 0}, 'grantees': {'people': [], 'ships_of': []}}
    assert checked(store, {'version': 1, 'grantees': None})['grantees'] is None
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `1 error`. The collection fails: `ModuleNotFoundError: No module named 'superyak_peer.charter'`.

- [ ] **Step 3: Write the implementation**

Create `peer/superyak_peer/charter.py` with:

```python
"""The station's charter (spec A step 4, docs/superpowers/specs/2026-10-15-charter-step4-design.md): the law layer
signed by a super admin, whose policy sets the limits every grant on the station obeys. This module holds the policy's
schema, version 1, with its defaults (C11, "Data"). Merge 4a builds the charter for its signer and the residents;
merge 4c adds acceptance by other owners."""
import copy
from .common import Problem
from .ships import safe_line

DEFAULT_POLICY = {'version': 1,
                  'delegation': {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24,
                                 'delegable': ['direct']},
                  'budgets': {'builds_per_ship_per_day': 20},
                  'grantees': None}
# Each section's keys, and each number's bounds ("Data"); `delegable` is a list, checked on its own.
SECTIONS = {'delegation': {'max_depth': (0, 5), 'max_expiry_hours': (1, 2160), 'agent_grant_default_hours': (1, 2160),
                           'delegable': None},
            'budgets': {'builds_per_ship_per_day': (0, 500)}}
NUMBERS = ('delegation.max_depth', 'delegation.max_expiry_hours', 'delegation.agent_grant_default_hours',
           'budgets.builds_per_ship_per_day')
ACTIONS = ('direct',)
RESERVED_ACTIONS = ('merge', 'deploy', 'admit')  # spec B's
RESERVED_KEYS = ('roots', 'breaker')  # step 5's (C2, C11)
MAX_GRANTEES = 100  # `people` and `ships_of` together


def _refuse(message):
    raise Problem(400, message)


def _person_ids(db, listed, path):
    """A grantee list: ids of local person accounts, each listed once."""
    if (not isinstance(listed, list) or any(not isinstance(item, str) or not 0 < len(item) <= 100 for item in listed)
            or len(set(listed)) != len(listed)):
        _refuse(f'{path} is a list of person ids, each listed once')
    for person in listed:
        if db.execute("SELECT 1 FROM users WHERE id=? AND kind='person'", (person,)).fetchone() is None:
            _refuse(f'{path}: each id must be a person on this station')
    return list(listed)


def full_policy(db, raw):
    """C11: a given policy, checked and filled; None is the defaults. Unknown keys at any level and a value of the wrong
    type are refused with 400 naming the path (a boolean is never a number, and 3.0 is not a whole number). The defaults
    are filled first; then every bound and cross-check runs on the full policy. Returns a new dict and never changes
    `raw`, so a draft keeps what was written and its revision stores the full policy (R2)."""
    if raw is None:
        return copy.deepcopy(DEFAULT_POLICY)
    if not isinstance(raw, dict):
        _refuse('policy is an object')
    for key in raw:
        if key in RESERVED_KEYS:
            _refuse(f'policy.{key} is reserved for step 5')
        if key not in ('version', 'delegation', 'budgets', 'grantees'):
            _refuse(f'policy.{safe_line(key, 40)} is not a policy key')
    if type(raw.get('version')) is not int or raw['version'] != 1:
        _refuse('policy.version must be 1')
    policy = {'version': 1}
    for section, fields in SECTIONS.items():
        given = raw.get(section, {})
        if not isinstance(given, dict):
            _refuse(f'policy.{section} is an object')
        for key in given:
            if key not in fields:
                _refuse(f'policy.{section}.{safe_line(key, 40)} is not a policy key')
        policy[section] = {**copy.deepcopy(DEFAULT_POLICY[section]), **copy.deepcopy(given)}
    delegation = policy['delegation']
    if 'agent_grant_default_hours' not in raw.get('delegation', {}):
        hours = delegation['max_expiry_hours']  # 24, or max_expiry_hours when smaller (C11)
        delegation['agent_grant_default_hours'] = min(24, hours) if type(hours) is int else 24
    for path in NUMBERS:
        section, key = path.split('.')
        low, high = SECTIONS[section][key]
        value = policy[section][key]
        if type(value) is not int or not low <= value <= high:
            _refuse(f'policy.{path} is a whole number from {low:,} to {high:,}')
    if delegation['agent_grant_default_hours'] > delegation['max_expiry_hours']:
        _refuse('policy.delegation.agent_grant_default_hours is at most policy.delegation.max_expiry_hours')
    delegable = delegation['delegable']
    if (not isinstance(delegable, list) or any(not isinstance(action, str) for action in delegable)
            or len(set(delegable)) != len(delegable)):
        _refuse('policy.delegation.delegable is a list of actions, each listed once')
    for action in delegable:
        if action in RESERVED_ACTIONS:
            _refuse(f'policy.delegation.delegable: {action} is reserved for spec B')
        if action not in ACTIONS:
            _refuse('policy.delegation.delegable holds only direct')
    grantees = raw.get('grantees')
    if grantees is not None:
        if not isinstance(grantees, dict):
            _refuse('policy.grantees is null or an object')
        for key in grantees:
            if key not in ('people', 'ships_of'):
                _refuse(f'policy.grantees.{safe_line(key, 40)} is not a policy key')
        grantees = {key: _person_ids(db, grantees.get(key, []), f'policy.grantees.{key}') for key in ('people', 'ships_of')}
        if len(grantees['people']) + len(grantees['ships_of']) > MAX_GRANTEES:
            _refuse(f'policy.grantees holds at most {MAX_GRANTEES} ids')
    policy['grantees'] = grantees
    return policy
```

In `peer/pyproject.toml`, insert after

```toml
    "systemd/superyak-restore-test.timer",
    "superyak_peer/__init__.py",
    "superyak_peer/__main__.py",
    "superyak_peer/access_requests.py",
    "superyak_peer/alerts.py",
    "superyak_peer/agent_version.py",
    "superyak_peer/app.py",
    "superyak_peer/auth.py",
    "superyak_peer/backups.py",
    "superyak_peer/breakouts.py",
    "superyak_peer/briefs.py",
```

this:

```toml
    "superyak_peer/charter.py",
```

In `peer/pyproject.toml`, insert after

```toml
    "tests/test_browser.py",
```

this:

```toml
    "tests/test_charter.py",
```

In `peer/pyproject.toml`, insert after

```toml
[tool.hatch.build.targets.wheel]
only-include = [
    "superyak_peer/__init__.py",
    "superyak_peer/__main__.py",
    "superyak_peer/access_requests.py",
    "superyak_peer/alerts.py",
    "superyak_peer/agent_version.py",
    "superyak_peer/app.py",
    "superyak_peer/auth.py",
    "superyak_peer/backups.py",
    "superyak_peer/breakouts.py",
    "superyak_peer/briefs.py",
```

this:

```toml
    "superyak_peer/charter.py",
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/charter.py peer/pyproject.toml peer/tests/test_charter.py
git commit -m "Charter 4a: the policy schema, version 1, with its defaults (C11)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Nested keys unchecked (a validator that checks only top-level keys). In `peer/superyak_peer/charter.py`, replace

   ```python
                   _refuse(f'policy.{section}.{safe_line(key, 40)} is not a policy key')
   ```

   with

   ```python
                   pass
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

2. A boolean taken as 1. In `peer/superyak_peer/charter.py`, replace

   ```python
           if type(value) is not int or not low <= value <= high:
   ```

   with

   ```python
           if not isinstance(value, int) or not low <= value <= high:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

3. `breaker` not reserved: it reads as an unknown key, not "reserved for step 5". In `peer/superyak_peer/charter.py`, replace

   ```python
   RESERVED_KEYS = ('roots', 'breaker')
   ```

   with

   ```python
   RESERVED_KEYS = ('roots',)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

4. `admit` not reserved for spec B. In `peer/superyak_peer/charter.py`, replace

   ```python
   RESERVED_ACTIONS = ('merge', 'deploy', 'admit')
   ```

   with

   ```python
   RESERVED_ACTIONS = ('merge', 'deploy')
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

5. A fixed default of 24: `max_expiry_hours` 12 fails its own cross-check. In `peer/superyak_peer/charter.py`, replace

   ```python
           delegation['agent_grant_default_hours'] = min(24, hours) if type(hours) is int else 24
   ```

   with

   ```python
           delegation['agent_grant_default_hours'] = 24
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_fills_its_defaults_before_its_cross_check` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

6. A bound one step wide. In `peer/superyak_peer/charter.py`, replace

   ```python
   SECTIONS = {'delegation': {'max_depth': (0, 5),
   ```

   with

   ```python
   SECTIONS = {'delegation': {'max_depth': (0, 6),
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

7. A ship accepted as a grantee. In `peer/superyak_peer/charter.py`, replace

   ```python
           if db.execute("SELECT 1 FROM users WHERE id=? AND kind='person'", (person,)).fetchone() is None:
   ```

   with

   ```python
           if db.execute("SELECT 1 FROM users WHERE id=?", (person,)).fetchone() is None:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

8. 101 grantees accepted. In `peer/superyak_peer/charter.py`, replace

   ```python
   MAX_GRANTEES = 100  #
   ```

   with

   ```python
   MAX_GRANTEES = 101  #
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_policy_refuses_each_bad_value_and_names_its_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

---

### Task 2: Charter drafts: `charter` and `policy`, checked first (R1)

**Files:**
- Modify: `peer/superyak_peer/charter.py` (append `check_draft`, about 17 lines)
- Modify: `peer/superyak_peer/layers.py` (`FIELDS`, the import, `_draft`: about 8 lines)
- Test: `peer/tests/test_charter.py` (about 75 lines)

**Interfaces:**
- Consumes: `charter.full_policy` (Task 1); `test_instructions.OLD_FIELDS`, `docked`, `new_layer`, `stored`.
- Produces: `charter.check_draft(db, draft)`; `layers.FIELDS` gains `charter` and `policy`; `Layers._draft` runs `check_draft` before every older check and stores `charter` only when true and `policy` only when set.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_charter.py`, replace

```python
from test_instructions import docked
```

with

```python
from test_instructions import OLD_FIELDS, docked, new_layer, stored
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
RULES = {'kind': 'instructions', 'title': 'Station law', 'body': 'Be kind.'}


def refusal(response):
    return response.status_code, response.json().get('error')


def test_a_draft_checks_charter_and_policy_first_in_the_spec_order(env):
    """Test 1, the draft's rows (R1, "Routes", drafts): each refusal with its status and reason, at create and at save;
    with two faults the earlier check answers, and the schema's check comes before every older draft check (an unknown
    field, a two-line title). Catches a check that answers out of the spec's order."""
    app, clients, users, clock = env
    ship, _ = docked(app.state.store, users[0]['id'], 'serenity')
    plain = new_layer(clients[0], **RULES, audience_users=[ship['id']])
    no_ships = 'A charter names no ships: it binds every ship whose owner accepts it'
    charter = {**RULES, 'charter': True, 'audience_users': []}  # a save keeps the stored audience unless it is sent
    for fields, answer in (
            ({**RULES, 'charter': 1}, (400, 'charter is true or false')),
            ({**RULES, 'charter': 'yes'}, (400, 'charter is true or false')),
            ({'kind': 'note', 'title': 'A note', 'charter': True}, (400, 'Only instructions can be a charter')),
            ({**charter, 'audience_users': [ship['id']]}, (400, no_ships)),
            ({**RULES, 'policy': {'version': 1}}, (400, 'A policy belongs only on a charter')),
            ({**charter, 'policy': {'version': 1, 'roots': []}}, (400, 'policy.roots is reserved for step 5')),
            ({**charter, 'policy': {'version': 1, 'delegation': {'max_depth': 6}}},
             (400, 'policy.delegation.max_depth is a whole number from 0 to 5')),
            ({'kind': 'note', 'title': 'A note', 'charter': 'yes', 'policy': {'version': 2}}, (400, 'charter is true or false')),
            ({'kind': 'note', 'title': 'A note', 'charter': True, 'audience_users': [ship['id']]},
             (400, 'Only instructions can be a charter')),
            ({**charter, 'audience_users': [ship['id']], 'policy': {'version': 2}}, (400, no_ships)),
            ({**RULES, 'policy': {'version': 2}}, (400, 'A policy belongs only on a charter')),
            ({**charter, 'policy': {'version': 2}, 'colour': 'red'}, (400, 'policy.version must be 1')),
            ({**charter, 'colour': 'red'}, (400, 'Unknown layer field')),
            ({**charter, 'title': 'two\nlines'}, (400, 'An instructions title is one line of at most 200 characters'))):
        assert refusal(clients[0].post('/api/layers', json=fields)) == answer, fields
        saved = clients[0].put(f'/api/layers/{plain["id"]}', json={'version': plain['version'], **fields})
        assert refusal(saved) == answer, fields
    assert stored(app, plain['id']) == {**RULES, 'audience_users': [ship['id']], 'audience_spaces': [], 'public': False,
                                        'attachment_ids': []}  # nothing refused was saved


def test_a_draft_stores_charter_and_policy_only_when_set(env):
    """R1 and "Data": a charter draft keeps its policy as written and has no audience; a note or ordinary draft stores
    neither key, so a station rolled back to before step 4 still reads it. Catches storing `charter: false` or a null
    policy."""
    app, clients, users, clock = env
    ship, _ = docked(app.state.store, users[0]['id'], 'serenity')
    written = {'version': 1, 'delegation': {'max_expiry_hours': 12}}
    made = new_layer(clients[0], **RULES, charter=True, policy=written)
    assert (made['charter'], made['policy'], made['audience_users']) == (True, written, [])
    assert stored(app, made['id'])['policy'] == written and stored(app, made['id'])['charter'] is True
    defaults = new_layer(clients[0], **RULES, charter=True, policy=None)
    assert stored(app, defaults['id'])['charter'] is True and 'policy' not in stored(app, defaults['id'])
    ordinary = new_layer(clients[0], **RULES, audience_users=[ship['id']], charter=False, policy=None)
    assert 'charter' not in stored(app, ordinary['id']) and 'policy' not in stored(app, ordinary['id'])
    note = new_layer(clients[0], title='A note', charter=False)
    assert set(stored(app, note['id'])) <= OLD_FIELDS
    kept = clients[0].put(f'/api/layers/{made["id"]}', json={'version': made['version'], 'charter': False,
                                                              'audience_users': [ship['id']]})
    assert refusal(kept) == (400, 'A policy belongs only on a charter')  # the stored policy carries over
    back = clients[0].put(f'/api/layers/{made["id"]}', json={'version': made['version'], 'charter': False, 'policy': None,
                                                              'audience_users': [ship['id']]})
    assert back.status_code == 200, back.text
    assert 'charter' not in stored(app, made['id']) and 'policy' not in stored(app, made['id'])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `2 failed, 2 passed`. The failures are `test_a_draft_checks_charter_and_policy_first_in_the_spec_order` (`(400, 'Unknown layer field') == (400, 'charter is true or false')`: today's `_draft` knows neither key) and `test_a_draft_stores_charter_and_policy_only_when_set` (`400 == 201`).

- [ ] **Step 3: Write the implementation**

Append to the end of `peer/superyak_peer/charter.py`, leaving two blank lines after the current last line:

```python
def check_draft(db, draft):
    """Charter step 4's draft checks, before every other draft check, in the spec's order ("Routes", drafts; R1): the
    flag's type, instructions only, no ships, a policy only on a charter, then the policy's schema. A draft keeps its
    policy as written; Layers._draft stores `charter` only when true and `policy` only when set."""
    charter = draft.get('charter', False)
    if type(charter) is not bool:
        _refuse('charter is true or false')
    if charter and draft.get('kind') != 'instructions':
        _refuse('Only instructions can be a charter')
    if charter and draft.get('audience_users'):
        _refuse('A charter names no ships: it binds every ship whose owner accepts it')
    if draft.get('policy') is not None:
        if not charter:
            _refuse('A policy belongs only on a charter')
        full_policy(db, draft['policy'])
```

In `peer/superyak_peer/layers.py`, replace

```python
import json
from .common import Problem, text, ids, uid, require, encode

FIELDS = {'kind', 'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids'}
```

with

```python
import json
from .charter import check_draft
from .common import Problem, text, ids, uid, require, encode

FIELDS = {'kind', 'title', 'body', 'audience_users', 'audience_spaces', 'public', 'attachment_ids', 'charter', 'policy'}
```

In `peer/superyak_peer/layers.py`, replace

```python
    def _draft(self, db, actor, data, previous=None, stored=False):
        if set(data) - (FIELDS | {'version'} | (SERVER_KEYS if stored else set())):
            raise Problem(400, 'Unknown layer field')
        draft = {**DEFAULT, **(previous or {}), **{k: v for k, v in data.items() if k in FIELDS or (stored and k in SERVER_KEYS)}}
```

with

```python
    def _draft(self, db, actor, data, previous=None, stored=False):
        draft = {**DEFAULT, **(previous or {}), **{k: v for k, v in data.items() if k in FIELDS or (stored and k in SERVER_KEYS)}}
        check_draft(db, draft)  # charter step 4: its checks come before every other draft check (R1)
        if set(data) - (FIELDS | {'version'} | (SERVER_KEYS if stored else set())):
            raise Problem(400, 'Unknown layer field')
```

In `peer/superyak_peer/layers.py`, replace

```python
        if draft['kind'] == 'note':
            del draft['kind']  # never stored for a note: a rolled-back station refuses any key it does not know
        return draft
```

with

```python
        if draft['kind'] == 'note':
            del draft['kind']  # never stored for a note: a rolled-back station refuses any key it does not know
        if draft.get('charter') is not True:
            draft.pop('charter', None)  # charter step 4, "Data": each is stored only when set, for the same reason
        if draft.get('policy') is None:
            draft.pop('policy', None)
        return draft
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_layers.py tests/test_instructions.py`
Expected: `37 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/charter.py peer/superyak_peer/layers.py peer/tests/test_charter.py
git commit -m "Charter 4a: charter drafts take charter and policy, checked before every other draft check (R1)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. The unknown-field check first: `colour` answers before the policy's version. In `peer/superyak_peer/layers.py`, replace

   ```python
           check_draft(db, draft)  # charter step 4: its checks come before every other draft check (R1)
           if set(data) - (FIELDS | {'version'} | (SERVER_KEYS if stored else set())):
               raise Problem(400, 'Unknown layer field')
   ```

   with

   ```python
           if set(data) - (FIELDS | {'version'} | (SERVER_KEYS if stored else set())):
               raise Problem(400, 'Unknown layer field')
           check_draft(db, draft)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_checks_charter_and_policy_first_in_the_spec_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

2. `charter: false` stored. In `peer/superyak_peer/layers.py`, replace

   ```python
           if draft.get('charter') is not True:
               draft.pop('charter', None)
   ```

   with

   ```python
           if draft.get('charter') is None:
               draft.pop('charter', None)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_stores_charter_and_policy_only_when_set` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

3. `1` taken as true. In `peer/superyak_peer/charter.py`, replace

   ```python
       if type(charter) is not bool:
           _refuse('charter is true or false')
   ```

   with

   ```python
       if charter not in (True, False):
           _refuse('charter is true or false')
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_checks_charter_and_policy_first_in_the_spec_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

4. A charter with a ship. In `peer/superyak_peer/charter.py`, replace

   ```python
       if charter and draft.get('audience_users'):
   ```

   with

   ```python
       if False:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_checks_charter_and_policy_first_in_the_spec_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

5. A policy without a charter. In `peer/superyak_peer/charter.py`, replace

   ```python
           if not charter:
               _refuse('A policy belongs only on a charter')
   ```

   with

   ```python
           if False:
               _refuse('A policy belongs only on a charter')
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_checks_charter_and_policy_first_in_the_spec_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

6. A charter on a note. In `peer/superyak_peer/charter.py`, replace

   ```python
       if charter and draft.get('kind') != 'instructions':
   ```

   with

   ```python
       if False:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_draft_checks_charter_and_policy_first_in_the_spec_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

---

### Task 3: Signing a charter: a super admin, one at a time, a charter stays one, the full policy stored and signed (R2-R5, R13)

**Files:**
- Modify: `peer/superyak_peer/charter.py` (`check_draft`'s `sealed`, append `STAYS_A_CHARTER` and the `Charter` mixin: about 35 lines)
- Modify: `peer/superyak_peer/layers.py` (the import, `_draft`, `save_layer`, `activate_layer`: about 12 lines)
- Modify: `peer/superyak_peer/signatures.py` (`_revision_record`, 3 lines)
- Modify: `peer/superyak_peer/db.py` (the import and `Store`'s bases, 2 lines)
- Test: `peer/tests/test_instructions.py` (`crown`, 6 lines); `peer/tests/test_charter.py` (about 110 lines)

**Interfaces:**
- Consumes: `check_draft`, `full_policy`; `users.is_super_admin` and `activation_pending` (`auth.py`); `test_signatures.card_of`, `signature_rows`, `stored_record`.
- Produces: `charter.STAYS_A_CHARTER`; `check_draft(db, draft, sealed=False)`; `class Charter` on `Store`: `_active_charter(db) -> sqlite3.Row | None` (the layers row, with its active revision's `snapshot` as JSON text), `_was_charter(db, layer_id) -> bool`, `_check_charter_activation(db, actor, key, snapshot) -> dict` (the full policy); `Layers._draft(db, actor, data, previous=None, stored=False, sealed=False)`; a charter revision's snapshot holds `charter: true`, `audience_users: []` and the full policy; `_revision_record`'s `policy`; test helper `crown(store, user)`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_instructions.py`, insert after

```python
def binding(app, ship_id):
    with app.state.store.transaction() as db:
        return [(l['layer_id'], l['revision']) for l in app.state.store._binding_layers(db, ship_id)]
```

this, leaving two blank lines between them:

```python
def crown(store, user):
    """Makes user a super admin by hand (the env fixture has none), as only a super admin signs a charter (C3)."""
    with store.transaction() as db:
        db.execute('UPDATE users SET is_admin=1, is_super_admin=1 WHERE id=?', (user['id'],))
```

In `peer/tests/test_charter.py`, replace

```python
import copy
from superyak_peer.charter import DEFAULT_POLICY, full_policy
from superyak_peer.common import Problem, uid
from test_instructions import OLD_FIELDS, docked, new_layer, stored
```

with

```python
import copy
import json
from superyak_peer.charter import DEFAULT_POLICY, full_policy
from superyak_peer.common import Problem, uid
from superyak_peer.identity import verify_record
from test_instructions import OLD_FIELDS, activate, crown, docked, new_layer, ship_client, stored
from test_signatures import card_of, signature_rows, stored_record
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
STAYS = "This layer is the station's charter and stays one; withdraw it to end it"


def snapshot(app, layer_id, revision):
    with app.state.store.transaction() as db:
        row = db.execute('SELECT snapshot FROM layer_revisions WHERE layer_id=? AND revision=?', (layer_id, revision)).fetchone()
        return json.loads(row['snapshot']) if row else None


def revision_count(app, layer_id):
    with app.state.store.transaction() as db:
        return db.execute('SELECT count(*) FROM layer_revisions WHERE layer_id=?', (layer_id,)).fetchone()[0]


def test_a_charter_revision_stores_the_full_policy_and_the_draft_keeps_what_was_written(env):
    """Test 2, R2 and R13: a charter with no policy and one with {"version": 1} activate to the same full revision
    policy, with `charter: true` and no audience; the draft keeps what was written; the signed record's policy is the
    revision's, and verifies. A policy of only max_expiry_hours 12 gives agent_grant_default_hours 12. Catches storing
    the raw policy, so the signed record omits the limits."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    card = card_of(store._station_identity())
    for policy in (None, {'version': 1}):
        layer = new_layer(clients[0], **RULES, charter=True, policy=policy)
        assert activate(clients[0], layer).status_code == 200
        kept = snapshot(app, layer['id'], 1)
        assert (kept['charter'], kept['audience_users'], kept['policy']) == (True, [], DEFAULT_POLICY)
        assert stored(app, layer['id']).get('policy') == policy
        record = stored_record(store, layer['id'], 1)
        assert record['kind'] == 'instructions-revision' and record['policy'] == DEFAULT_POLICY
        assert verify_record(card, record, signature_rows(store)[(layer['id'], 1)])
        assert clients[0].post(f'/api/layers/{layer["id"]}/withdraw').status_code == 200
    short = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'delegation': {'max_expiry_hours': 12}})
    assert activate(clients[0], short).status_code == 200
    assert snapshot(app, short['id'], 1)['policy']['delegation'] == {
        'max_depth': 3, 'max_expiry_hours': 12, 'agent_grant_default_hours': 12, 'delegable': ['direct']}
    assert stored_record(store, short['id'], 1)['policy'] == snapshot(app, short['id'], 1)['policy']


def test_only_a_super_admin_signs_a_charter(env):
    """Test 3 (R3, C3): a non-owner gets 404 before anything else; an admin who is not a super admin and a participant
    each get 403, with nothing written; a super admin signs; a ship key gets 403 on activate and on withdraw. Catches
    spec A's "any admin"."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    crown(store, users[3])
    for client in (clients[2], clients[1]):  # organizer, an admin; doctor, a participant
        layer = new_layer(client, **RULES, charter=True)
        assert refusal(activate(client, layer)) == (403, "Only a super admin can sign the station's charter")
        assert revision_count(app, layer['id']) == 0 and client.get(f'/api/layers/{layer["id"]}').json()['state'] == 'draft'
    theirs = new_layer(clients[3], **RULES, charter=True)
    for client in (clients[1], clients[2]):
        assert refusal(activate(client, theirs)) == (404, 'Not found')
    for path in ('activate', 'withdraw'):
        assert refusal(ship_client(app, key).post(f'/api/layers/{theirs["id"]}/{path}', json={'version': 1})) == (
            403, 'Ship keys cannot use this route')
    assert activate(clients[3], theirs).status_code == 200
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 1  # only the super admin's


def test_one_charter_layer_is_active_at_a_time(env):
    """Test 4 (R4): while one charter layer is active, a charter revision of another layer gets 409, whoever owns it;
    a new revision of the active one is fine; after the first is withdrawn, the second activates. Catches a one-charter
    check limited to the same layer or the same signer."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    crown(store, users[3])
    first = new_layer(clients[0], **RULES, charter=True)
    assert activate(clients[0], first).status_code == 200
    another = 'Another charter is active; its owner must withdraw it first'
    theirs = new_layer(clients[3], **RULES, charter=True)
    mine = new_layer(clients[0], **RULES, charter=True)
    for client, layer in ((clients[3], theirs), (clients[0], mine)):
        assert refusal(activate(client, layer)) == (409, another)
        assert revision_count(app, layer['id']) == 0
    revised = clients[0].put(f'/api/layers/{first["id"]}', json={'version': first['version'], 'body': 'Be kinder.'}).json()
    assert activate(clients[0], revised).json()['revision'] == 2
    assert clients[0].post(f'/api/layers/{first["id"]}/withdraw').status_code == 200
    assert activate(clients[3], theirs).status_code == 200


def test_a_charter_stays_a_charter(env):
    """Test 8 (R5, C6): on a layer with a charter revision, saving `charter: false` with the stored policy still in the
    draft gets 409, not the 400 for a policy without a charter, whatever else the draft holds; a draft edited by hand to
    drop the flag gets 409 at activation; it holds after a withdrawal too. Catches a charter that silently becomes an
    ordinary layer, or a check order that answers 400 first."""
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    crown(store, users[0])
    law = new_layer(clients[0], **RULES, charter=True, policy={'version': 1})
    assert activate(clients[0], law).status_code == 200
    for fields in ({'charter': False, 'audience_users': [ship['id']]}, {'charter': False, 'policy': None},
                   {'charter': False, 'colour': 'red'}, {'charter': False, 'kind': 'note'}):
        assert refusal(clients[0].put(f'/api/layers/{law["id"]}', json={'version': law['version'], **fields})) == (409, STAYS), fields
    assert clients[0].put(f'/api/layers/{law["id"]}', json={'version': law['version'], 'body': 'Be kinder.'}).status_code == 200
    edited = {key: value for key, value in stored(app, law['id']).items() if key != 'charter'}
    with store.transaction() as db:  # by hand: the draft loses its flag but keeps its policy
        db.execute('UPDATE layers SET draft=? WHERE id=?', (json.dumps(edited), law['id']))
    version = clients[0].get(f'/api/layers/{law["id"]}').json()['version']
    assert refusal(clients[0].post(f'/api/layers/{law["id"]}/activate', json={'version': version})) == (409, STAYS)
    assert revision_count(app, law['id']) == 1
    plain = new_layer(clients[0], **RULES, charter=True)
    assert activate(clients[0], plain).status_code == 409  # the first is still active
    other = clients[0].get(f'/api/layers/{law["id"]}').json()
    with store.transaction() as db:  # the flag back, so the layer can be withdrawn and the next one signed
        db.execute('UPDATE layers SET draft=? WHERE id=?', (json.dumps({**edited, 'charter': True}), law['id']))
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    assert refusal(clients[0].put(f'/api/layers/{law["id"]}', json={'version': other['version'], 'charter': False,
                                                                    'policy': None})) == (409, STAYS)
    assert activate(clients[0], plain).status_code == 200
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `4 failed, 4 passed`. The four new tests fail: each charter activation gets today's `400 'Choose at least one ship for these instructions'` (for example `assert (400, 'Choose...instructions') == (403, "Only a...on's charter")`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/charter.py`, replace

```python
def check_draft(db, draft):
    """Charter step 4's draft checks, before every other draft check, in the spec's order ("Routes", drafts; R1): the
    flag's type, instructions only, no ships, a policy only on a charter, then the policy's schema. A draft keeps its
    policy as written; Layers._draft stores `charter` only when true and `policy` only when set."""
    charter = draft.get('charter', False)
    if type(charter) is not bool:
        _refuse('charter is true or false')
```

with

```python
def check_draft(db, draft, sealed=False):
    """Charter step 4's draft checks, before every other draft check, in the spec's order ("Routes", drafts; R1): the
    flag's type, a sealed layer (one with a charter revision) stays a charter (C6, 409 whatever else the draft holds),
    instructions only, no ships, a policy only on a charter, then the policy's schema. A draft keeps its policy as
    written; Layers._draft stores `charter` only when true and `policy` only when set."""
    charter = draft.get('charter', False)
    if type(charter) is not bool:
        _refuse('charter is true or false')
    if sealed and not charter:
        raise Problem(409, STAYS_A_CHARTER)
```

Append to the end of `peer/superyak_peer/charter.py`, leaving two blank lines after the current last line:

```python
STAYS_A_CHARTER = "This layer is the station's charter and stays one; withdraw it to end it"


class Charter:
    """The active charter, read from the layers' revisions: a charter revision's snapshot holds `charter: true`."""

    def _active_charter(self, db):
        """Binding step 1: the layers row whose active revision is a charter revision, with that revision's `snapshot`
        (JSON text), or None. Activation lets only one be active (R4). Merge 4c reads `id`, `owner_id` and
        `active_revision` from it (its I11)."""
        return db.execute('SELECT layers.*, layer_revisions.snapshot FROM layers JOIN layer_revisions '
                          'ON layer_revisions.layer_id=layers.id AND layer_revisions.revision=layers.active_revision '
                          "WHERE json_extract(layer_revisions.snapshot, '$.charter')=1 "
                          'ORDER BY layer_revisions.created, layers.id LIMIT 1').fetchone()

    def _was_charter(self, db, layer_id):
        """C6: whether the layer has a charter revision, active or not; such a layer stays a charter."""
        return db.execute("SELECT 1 FROM layer_revisions WHERE layer_id=? AND json_extract(snapshot, '$.charter')=1 LIMIT 1",
                          (layer_id,)).fetchone() is not None

    def _check_charter_activation(self, db, actor, key, snapshot):
        """Activation step 5 for a charter, in the spec's order ("Routes"): 403 unless the caller is a super admin (C3),
        then 409 while another charter layer is active (R4). Returns the full policy the revision stores (C11, R2)."""
        user = db.execute('SELECT is_super_admin, activation_pending FROM users WHERE id=?', (actor,)).fetchone()
        if user is None or not user['is_super_admin'] or user['activation_pending']:
            raise Problem(403, "Only a super admin can sign the station's charter")
        active = self._active_charter(db)
        if active is not None and active['id'] != key:
            raise Problem(409, 'Another charter is active; its owner must withdraw it first')
        return full_policy(db, snapshot.get('policy'))
```

In `peer/superyak_peer/layers.py`, replace

```python
from .charter import check_draft
```

with

```python
from .charter import STAYS_A_CHARTER, check_draft
```

In `peer/superyak_peer/layers.py`, replace

```python
    def _draft(self, db, actor, data, previous=None, stored=False):
        draft = {**DEFAULT, **(previous or {}), **{k: v for k, v in data.items() if k in FIELDS or (stored and k in SERVER_KEYS)}}
        check_draft(db, draft)  # charter step 4: its checks come before every other draft check (R1)
```

with

```python
    def _draft(self, db, actor, data, previous=None, stored=False, sealed=False):
        draft = {**DEFAULT, **(previous or {}), **{k: v for k, v in data.items() if k in FIELDS or (stored and k in SERVER_KEYS)}}
        check_draft(db, draft, sealed)  # charter step 4: its checks come before every other draft check (R1)
```

In `peer/superyak_peer/layers.py`, replace

```python
            draft = self._draft(db, actor, data, json.loads(row['draft']))
            db.execute('UPDATE layers SET draft=?,version=version+1 WHERE id=?', (encode(draft), key))
```

with

```python
            draft = self._draft(db, actor, data, json.loads(row['draft']), sealed=self._was_charter(db, key))
            db.execute('UPDATE layers SET draft=?,version=version+1 WHERE id=?', (encode(draft), key))
```

In `peer/superyak_peer/layers.py`, replace

```python
            snapshot = self._draft(db, actor, json.loads(row['draft']), stored=True)
            if snapshot.get('kind') == 'instructions':
                self._check_instruction_caps(db, actor, key, snapshot)
```

with

```python
            saved = json.loads(row['draft'])
            if saved.get('charter') is not True and self._was_charter(db, key):
                raise Problem(409, STAYS_A_CHARTER)  # C6, before any other draft check (R5)
            snapshot = self._draft(db, actor, saved, stored=True)
            if snapshot.get('charter') is True:
                snapshot['policy'] = self._check_charter_activation(db, actor, key, snapshot)  # stored in full (R2)
            elif snapshot.get('kind') == 'instructions':
                self._check_instruction_caps(db, actor, key, snapshot)
```

In `peer/superyak_peer/signatures.py`, replace

```python
                'audience_users': snapshot['audience_users'], 'policy': None, 'created': row['created']}
```

with

```python
                'audience_users': snapshot['audience_users'],
                'policy': snapshot.get('policy') if snapshot.get('charter') is True else None,  # C12: null off a charter
                'created': row['created']}
```

In `peer/superyak_peer/db.py`, replace

```python
from .grants import Grants, GRANT_SCHEMA
```

with

```python
from .grants import Grants, GRANT_SCHEMA
from .charter import Charter
```

In `peer/superyak_peer/db.py`, replace

```python
Breakouts, Signatures, Grants):
```

with

```python
Breakouts, Signatures, Grants, Charter):
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_signatures.py tests/test_layers.py tests/test_instructions.py`
Expected: `69 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/charter.py peer/superyak_peer/layers.py peer/superyak_peer/signatures.py peer/superyak_peer/db.py peer/tests/test_instructions.py peer/tests/test_charter.py
git commit -m "Charter 4a: only a super admin signs a charter, one at a time; a charter stays one, its full policy stored and signed (R2-R5, R13)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Spec A's "any admin": the organizer signs. In `peer/superyak_peer/charter.py`, replace

   ```python
           if user is None or not user['is_super_admin'] or user['activation_pending']:
   ```

   with

   ```python
           if user is None or not db.execute('SELECT is_admin FROM users WHERE id=?', (actor,)).fetchone()[0]:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_only_a_super_admin_signs_a_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

2. A one-charter check limited to other signers: the signer's second layer activates. In `peer/superyak_peer/charter.py`, replace

   ```python
           if active is not None and active['id'] != key:
   ```

   with

   ```python
           if active is not None and active['owner_id'] != actor:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_one_charter_layer_is_active_at_a_time` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

3. The raw policy stored. In `peer/superyak_peer/layers.py`, replace

   ```python
                   snapshot['policy'] = self._check_charter_activation(db, actor, key, snapshot)  # stored in full (R2)
   ```

   with

   ```python
                   self._check_charter_activation(db, actor, key, snapshot)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charter_revision_stores_the_full_policy_and_the_draft_keeps_what_was_written` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

4. A record without the policy. In `peer/superyak_peer/signatures.py`, replace

   ```python
                   'policy': snapshot.get('policy') if snapshot.get('charter') is True else None,  # C12: null off a charter
   ```

   with

   ```python
                   'policy': None,
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charter_revision_stores_the_full_policy_and_the_draft_keeps_what_was_written` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/signatures.py`.

5. No C6 at save: the 400 for a policy without a charter answers. In `peer/superyak_peer/layers.py`, replace

   ```python
   sealed=self._was_charter(db, key))
   ```

   with

   ```python
   sealed=False)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charter_stays_a_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

6. No C6 at activation: the hand-edited draft answers 400. In `peer/superyak_peer/layers.py`, replace

   ```python
               if saved.get('charter') is not True and self._was_charter(db, key):
   ```

   with

   ```python
               if False:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charter_stays_a_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

---

### Task 4: Widened paths, confirmed at activation, and the preview (R6, R7)

**Files:**
- Modify: `peer/superyak_peer/charter.py` (`import hashlib`, `import json`; `MAX_CONFIRMED`, `_changes`, `widened_paths`, `narrowed_paths`, `confirm_paths`, `require_confirmed`, `person_names`, `digest`; `_policy_in_force`, `_charter_preview`; the confirmation: about 75 lines)
- Modify: `peer/superyak_peer/layers.py` (`preview_layer`, `activate_layer`: about 10 lines)
- Modify: `peer/superyak_peer/app.py` (the activate route, 1 line)
- Test: `peer/tests/test_charter.py` (about 120 lines)

**Interfaces:**
- Consumes: `full_policy`, `_active_charter`, `_check_charter_activation` (Task 3); `people` (Task 1's test helper).
- Produces: `charter.MAX_CONFIRMED = 105`; `widened_paths(baseline, policy) -> list[dict]` and `narrowed_paths(baseline, policy) -> list[dict]`, each `[{path, before, after}]` sorted by path (both from `_changes`); `confirm_paths(value) -> list[str]` (None is `[]`, else 400 "confirm_widenings is a list of paths"); `require_confirmed(paths, widened) -> None` (409 "Confirm exactly these widenings: …"); `person_names(db, *policies) -> {id: name}`; `digest(text) -> hex`; `Charter._policy_in_force(db) -> dict`; `Charter._charter_preview(db, actor, draft) -> {policy, widenings, narrowings, names, binds, sha256}`; `_check_charter_activation(db, actor, key, snapshot, confirm=None)`; `Layers.activate_layer(actor, key, version, space_versions=None, confirm_widenings=None)`; the preview's `charter`; test helpers `sign(client, layer, *confirm)`, `save(client, layer, **fields)`, `exactly(*paths)`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_charter.py`, replace

```python
import copy
import json
```

with

```python
import copy
import hashlib
import json
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def sign(client, layer, *confirm):
    """Activates layer's draft at its version, confirming these widened paths."""
    return client.post(f'/api/layers/{layer["id"]}/activate', json={'version': layer['version'],
                                                                     'confirm_widenings': list(confirm)})


def save(client, layer, **fields):
    response = client.put(f'/api/layers/{layer["id"]}', json={'version': layer['version'], **fields})
    assert response.status_code == 200, response.text
    return response.json()


def exactly(*paths):
    return 409, 'Confirm exactly these widenings: ' + (', '.join(paths) or 'none')


def test_a_charters_widenings_are_confirmed_path_by_path(env):
    """Test 5 (R6, R7, C5, C13): on a first charter, max_depth 4 needs ["delegation.max_depth"]: absent, [], an extra
    path or a repeated one gets 409, and a malformed list 400. Each later revision is compared with the policy in
    force: a prose change and a narrowing list nothing, a gained person lists grantees.people:<id>, a restricted set made
    null lists grantees. All four numbers, delegable and 100 ids widened at once list 105 paths, sorted, and sign with
    all 105 confirmed in another order. Catches comparing with the defaults on every revision, and a cap below the
    schema's most."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    jenn, stanley = users[1]['id'], users[3]['id']
    law = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'delegation': {'max_depth': 4}})
    for confirm in ((), ('delegation.max_depth', 'budgets.builds_per_ship_per_day'), ('delegation.max_depth', 'delegation.max_depth')):
        assert refusal(sign(clients[0], law, *confirm)) == exactly('delegation.max_depth'), confirm
    assert refusal(clients[0].post(f'/api/layers/{law["id"]}/activate', json={'version': law['version']})) == exactly('delegation.max_depth')
    for malformed in ('delegation.max_depth', [5], ['x' * 201], ['p'] * 106, {'delegation.max_depth': True}):
        response = clients[0].post(f'/api/layers/{law["id"]}/activate', json={'version': law['version'], 'confirm_widenings': malformed})
        assert refusal(response) == (400, 'confirm_widenings is a list of paths'), malformed
    assert revision_count(app, law['id']) == 0
    assert sign(clients[0], law, 'delegation.max_depth').status_code == 200  # r1
    law = save(clients[0], law, body='Be kinder.')
    assert sign(clients[0], law).status_code == 200  # r2, prose: against r1's max_depth 4, not the defaults' 3
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 2}, 'grantees': {'people': [jenn]}})
    assert sign(clients[0], law).status_code == 200  # r3, narrowings only
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 2}, 'grantees': {'people': [jenn, stanley]}})
    assert refusal(sign(clients[0], law)) == exactly(f'grantees.people:{stanley}')
    assert sign(clients[0], law, f'grantees.people:{stanley}').status_code == 200  # r4
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 2}, 'grantees': None})
    assert refusal(sign(clients[0], law)) == exactly('grantees')
    assert sign(clients[0], law, 'grantees').status_code == 200  # r5
    many = people(store, 100)
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 0, 'max_expiry_hours': 1, 'delegable': []},
                                        'budgets': {'builds_per_ship_per_day': 0}, 'grantees': {}})
    assert sign(clients[0], law).status_code == 200  # r6, every limit narrowed: nothing to confirm
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 5, 'max_expiry_hours': 2160,
                                                                      'agent_grant_default_hours': 2160, 'delegable': ['direct']},
                                        'budgets': {'builds_per_ship_per_day': 500},
                                        'grantees': {'people': many[:50], 'ships_of': many[50:]}})
    paths = sorted(['delegation.max_depth', 'delegation.max_expiry_hours', 'delegation.agent_grant_default_hours',
                    'budgets.builds_per_ship_per_day', 'delegation.delegable:direct']
                   + [f'grantees.people:{i}' for i in many[:50]] + [f'grantees.ships_of:{i}' for i in many[50:]])
    assert len(paths) == 105 and refusal(sign(clients[0], law)) == exactly(*paths)
    assert sign(clients[0], law, *reversed(paths)).json()['revision'] == 7
    ship, _ = docked(store, users[0]['id'], 'serenity')
    ordinary = new_layer(clients[0], **RULES, audience_users=[ship['id']])
    assert refusal(sign(clients[0], ordinary, 'delegation.max_depth')) == (400, 'Only a charter has widenings to confirm')
    assert sign(clients[0], ordinary).status_code == 200


def test_one_widened_number_among_twenty_changed_lines_is_refused_until_confirmed(env):
    """Test 6 (spec A): a revision with twenty changed prose lines and one widened number is refused until that path
    is confirmed; a confirmation of anything else confirms nothing. Catches confirming "any change" at once."""
    app, clients, users, clock = env
    crown(app.state.store, users[0])
    law = new_layer(clients[0], **RULES, charter=True)
    assert sign(clients[0], law).status_code == 200
    law = save(clients[0], law, body='\n'.join(f'Rule {n}: be kinder than before.' for n in range(20)),
               policy={'version': 1, 'budgets': {'builds_per_ship_per_day': 21}})
    for confirm in ((), ('body',), ('*',), ('title', 'body')):
        assert refusal(sign(clients[0], law, *confirm)) == exactly('budgets.builds_per_ship_per_day'), confirm
    assert sign(clients[0], law, 'budgets.builds_per_ship_per_day').json()['revision'] == 2


def test_the_preview_shows_a_charters_policy_changes_ships_and_hashes(env):
    """"Routes", the preview (and Deploy's rehearsal): for a charter draft, `charter` holds the full policy, its widened
    and narrowed paths against the policy in force, the names of the people they list, the ships it would bind (the
    residents, owner_name null, and the signer's ships) and the sha256 of the saved title and body. Catches a preview
    against the defaults once a charter is active, or one that lists another owner's ship."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    docked(store, users[1]['id'], 'defiant')
    odo = store.create_station_ship('odo', 'Odo')
    doctor = users[1]['id']
    policy = {'version': 1, 'delegation': {'max_depth': 4, 'max_expiry_hours': 48}, 'grantees': {'people': [doctor]}}
    law = new_layer(clients[0], kind='instructions', title='Station law ✓', body='Be kind.\n', charter=True, policy=policy)
    shown = clients[0].get(f'/api/layers/{law["id"]}/preview').json()['charter']
    assert shown == {
        'policy': {'version': 1, 'delegation': {'max_depth': 4, 'max_expiry_hours': 48, 'agent_grant_default_hours': 24,
                                                'delegable': ['direct']},
                   'budgets': {'builds_per_ship_per_day': 20}, 'grantees': {'people': [doctor], 'ships_of': []}},
        'widenings': [{'path': 'delegation.max_depth', 'before': 3, 'after': 4}],
        'narrowings': [{'path': 'delegation.max_expiry_hours', 'before': 720, 'after': 48},
                       {'path': 'grantees', 'before': None, 'after': {'people': [doctor], 'ships_of': []}}],
        'names': {doctor: 'Doctor'},
        'binds': [{'id': odo['id'], 'name': 'Odo', 'owner_name': None},
                  {'id': serenity['id'], 'name': 'Serenity', 'owner_name': 'Patient'}],
        'sha256': {'title': hashlib.sha256('Station law ✓'.encode()).hexdigest(),
                   'body': hashlib.sha256(b'Be kind.\n').hexdigest()}}
    assert sign(clients[0], law, 'delegation.max_depth').status_code == 200
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 4, 'max_expiry_hours': 48}})
    shown = clients[0].get(f'/api/layers/{law["id"]}/preview').json()['charter']
    assert (shown['widenings'], shown['narrowings']) == ([{'path': 'grantees', 'before': {'people': [doctor], 'ships_of': []},
                                                           'after': None}], [])
    plain = new_layer(clients[0], **RULES, audience_users=[serenity['id']])
    assert 'charter' not in clients[0].get(f'/api/layers/{plain["id"]}/preview').json()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `3 failed, 8 passed`. The failures: test 5 (`(200, None) == (409, 'Confir...on.max_depth')`: nothing asks for a confirmation yet), test 6 (the same for `budgets.builds_per_ship_per_day`), and the preview test (`assert True == {...}`: the preview has only the draft's boolean `charter`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/charter.py`, replace

```python
import copy
from .common import Problem
```

with

```python
import copy
import hashlib
import json
from .common import Problem
```

In `peer/superyak_peer/charter.py`, insert before

```python
def check_draft(db, draft, sealed=False):
```

this, followed by two blank lines:

```python
MAX_CONFIRMED = 105  # four numbers, one action and 100 ids: the most widened paths the schema allows (C13)


def _changes(base, policy):
    """C13, "Data": (widened, narrowed) from a baseline policy to a full policy, each a list of {path, before, after}
    sorted by path in code point order. A number that grows, an action gained, a restricted grantee set made
    unrestricted, and with both restricted an id gained, are widenings; the same paths the other way are narrowings.
    Prose is neither."""
    widened, narrowed = [], []
    for path in NUMBERS:
        section, key = path.split('.')
        before, after = base[section][key], policy[section][key]
        if after != before:
            (widened if after > before else narrowed).append({'path': path, 'before': before, 'after': after})
    was, now = base['delegation']['delegable'], policy['delegation']['delegable']
    widened += [{'path': f'delegation.delegable:{action}', 'before': None, 'after': action} for action in now if action not in was]
    narrowed += [{'path': f'delegation.delegable:{action}', 'before': action, 'after': None} for action in was if action not in now]
    was, now = base['grantees'], policy['grantees']
    if was is not None and now is None:
        widened.append({'path': 'grantees', 'before': was, 'after': None})
    elif was is None and now is not None:
        narrowed.append({'path': 'grantees', 'before': None, 'after': now})
    elif was is not None:
        for key in ('people', 'ships_of'):
            widened += [{'path': f'grantees.{key}:{i}', 'before': None, 'after': i} for i in now[key] if i not in was[key]]
            narrowed += [{'path': f'grantees.{key}:{i}', 'before': i, 'after': None} for i in was[key] if i not in now[key]]
    return sorted(widened, key=lambda change: change['path']), sorted(narrowed, key=lambda change: change['path'])


def widened_paths(baseline, policy):
    """C13: the paths that widen from a baseline policy to a full policy, [{path, before, after}] sorted by path."""
    return _changes(baseline, policy)[0]


def narrowed_paths(baseline, policy):
    """The preview's narrowings ("Routes"): the same paths where the policy is smaller or lacks a member."""
    return _changes(baseline, policy)[1]


def confirm_paths(value):
    """confirm_widenings' shape ("Routes", activation step 5): absent is []; anything but a list of at most 105 strings
    of at most 200 characters is 400."""
    if value is None:
        return []
    if (not isinstance(value, list) or len(value) > MAX_CONFIRMED
            or any(not isinstance(path, str) or len(path) > 200 for path in value)):
        raise Problem(400, 'confirm_widenings is a list of paths')
    return value


def require_confirmed(paths, widened):
    """C13: the confirmed paths are exactly the widened ones, each once, in any order; 409 naming them otherwise."""
    wanted = [change['path'] for change in widened]
    if len(set(paths)) != len(paths) or set(paths) != set(wanted):
        raise Problem(409, 'Confirm exactly these widenings: ' + (', '.join(wanted) or 'none'))


def person_names(db, *policies):
    """The `names` map ("Data"): each person id the policies' grantee sets list, with its name."""
    listed = sorted({person for policy in policies if policy['grantees'] is not None
                     for key in ('people', 'ships_of') for person in policy['grantees'][key]})
    marks = ','.join('?' * len(listed))
    return {row['id']: row['name'] for row in db.execute(f'SELECT id, name FROM users WHERE id IN ({marks})', listed)} if listed else {}


def digest(text):
    """The preview's sha256: hex, of the text in UTF-8."""
    return hashlib.sha256(text.encode()).hexdigest()
```

In `peer/superyak_peer/charter.py`, replace

```python
    def _check_charter_activation(self, db, actor, key, snapshot):
        """Activation step 5 for a charter, in the spec's order ("Routes"): 403 unless the caller is a super admin (C3),
        then 409 while another charter layer is active (R4). Returns the full policy the revision stores (C11, R2)."""
```

with

```python
    def _policy_in_force(self, db):
        """C5, C16: the active charter revision's policy, or the no-charter defaults when none is active."""
        active = self._active_charter(db)
        return copy.deepcopy(DEFAULT_POLICY) if active is None else json.loads(active['snapshot'])['policy']

    def _charter_preview(self, db, actor, draft):
        """The preview's `charter` ("Routes"): the full policy, its widened and narrowed paths against the policy in force
        (C5), the names of the people they list, the ships it would bind (in 4a the residents, with owner_name null, and
        the signer's ships), and the sha256 of the saved title and body."""
        base, policy = self._policy_in_force(db), full_policy(db, draft.get('policy'))
        widened, narrowed = widened_paths(base, policy), narrowed_paths(base, policy)
        binds = [dict(row) for row in db.execute(
            'SELECT ships.id, ships.name, owners.name AS owner_name FROM users AS ships LEFT JOIN users AS owners '
            "ON owners.id=ships.owner_id WHERE ships.kind='ship' AND (ships.owner_id IS NULL OR ships.owner_id=?) "
            'ORDER BY ships.name COLLATE NOCASE, ships.id', (actor,))]
        return {'policy': policy, 'widenings': widened, 'narrowings': narrowed, 'names': person_names(db, base, policy),
                'binds': binds, 'sha256': {'title': digest(draft['title']), 'body': digest(draft['body'])}}

    def _check_charter_activation(self, db, actor, key, snapshot, confirm=None):
        """Activation step 5 for a charter, in the spec's order ("Routes"): 403 unless the caller is a super admin (C3),
        409 while another charter layer is active (R4), 400 for a malformed confirm_widenings, then 409 unless it holds
        exactly the paths that widen from the policy in force (C5, C13). Returns the full policy the revision stores
        (C11, R2)."""
```

In `peer/superyak_peer/charter.py`, replace

```python
            raise Problem(409, 'Another charter is active; its owner must withdraw it first')
        return full_policy(db, snapshot.get('policy'))
```

with

```python
            raise Problem(409, 'Another charter is active; its owner must withdraw it first')
        policy = full_policy(db, snapshot.get('policy'))
        require_confirmed(confirm_paths(confirm), widened_paths(self._policy_in_force(db), policy))
        return policy
```

In `peer/superyak_peer/layers.py`, replace

```python
            return {**self._layer_json(row), 'files':files, 'people':people, 'audience_details':details,
                    'space_versions':{space['id']:space['version'] for space in details}}

    def activate_layer(self, actor, key, version, space_versions=None):
```

with

```python
            charter = {'charter': self._charter_preview(db, actor, draft)} if draft.get('charter') is True else {}
            return {**self._layer_json(row), 'files':files, 'people':people, 'audience_details':details,
                    'space_versions':{space['id']:space['version'] for space in details}, **charter}

    def activate_layer(self, actor, key, version, space_versions=None, confirm_widenings=None):
```

In `peer/superyak_peer/layers.py`, replace

```python
            if snapshot.get('charter') is True:
                snapshot['policy'] = self._check_charter_activation(db, actor, key, snapshot)  # stored in full (R2)
            elif snapshot.get('kind') == 'instructions':
                self._check_instruction_caps(db, actor, key, snapshot)
```

with

```python
            if snapshot.get('charter') is True:
                snapshot['policy'] = self._check_charter_activation(db, actor, key, snapshot, confirm_widenings)  # in full (R2)
            else:
                if confirm_widenings:
                    raise Problem(400, 'Only a charter has widenings to confirm')
                if snapshot.get('kind') == 'instructions':
                    self._check_instruction_caps(db, actor, key, snapshot)
```

In `peer/superyak_peer/app.py`, replace

```python
        return store.activate_layer(who, key, data.get('version'), data.get('space_versions'))
```

with

```python
        return store.activate_layer(who, key, data.get('version'), data.get('space_versions'), data.get('confirm_widenings'))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_layers.py tests/test_instructions.py`
Expected: `44 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/charter.py peer/superyak_peer/layers.py peer/superyak_peer/app.py peer/tests/test_charter.py
git commit -m "Charter 4a: widened paths confirmed path by path against the policy in force, and the charter preview (R6, R7, C13)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Every revision compared with the defaults: r2's prose asks for max_depth again. In `peer/superyak_peer/charter.py`, replace

   ```python
           require_confirmed(confirm_paths(confirm), widened_paths(self._policy_in_force(db), policy))
   ```

   with

   ```python
           require_confirmed(confirm_paths(confirm), widened_paths(full_policy(db, None), policy))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

2. A cap below the schema's most: 105 confirmed paths get 400. In `peer/superyak_peer/charter.py`, replace

   ```python
   MAX_CONFIRMED = 105
   ```

   with

   ```python
   MAX_CONFIRMED = 100
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

3. A repeated path accepted. In `peer/superyak_peer/charter.py`, replace

   ```python
       if len(set(paths)) != len(paths) or set(paths) != set(wanted):
   ```

   with

   ```python
       if set(paths) != set(wanted):
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

4. An unchanged number listed as widened. In `peer/superyak_peer/charter.py`, replace

   ```python
               (widened if after > before else narrowed).append({'path': path, 'before': before, 'after': after})
   ```

   with

   ```python
               (narrowed if after < before else widened).append({'path': path, 'before': before, 'after': after})
           elif path == 'delegation.max_depth':
               widened.append({'path': path, 'before': before, 'after': after})
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

5. A restricted set made null is not a widening. In `peer/superyak_peer/charter.py`, replace

   ```python
       if was is not None and now is None:
           widened.append({'path': 'grantees', 'before': was, 'after': None})
   ```

   with

   ```python
       if was is not None and now is None:
           pass
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

6. Any confirmation confirms every change. In `peer/superyak_peer/charter.py`, replace

   ```python
       if len(set(paths)) != len(paths) or set(paths) != set(wanted):
   ```

   with

   ```python
       if not paths and wanted:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_one_widened_number_among_twenty_changed_lines_is_refused_until_confirmed` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

7. Another owner's ship listed. In `peer/superyak_peer/charter.py`, replace

   ```python
               "ON owners.id=ships.owner_id WHERE ships.kind='ship' AND (ships.owner_id IS NULL OR ships.owner_id=?) "
   ```

   with

   ```python
               "ON owners.id=ships.owner_id WHERE ships.kind='ship' AND (ships.owner_id IS NULL OR ships.owner_id!=?) "
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_preview_shows_a_charters_policy_changes_ships_and_hashes` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

8. A preview against the defaults once a charter is active. In `peer/superyak_peer/charter.py`, replace

   ```python
           base, policy = self._policy_in_force(db), full_policy(db, draft.get('policy'))
   ```

   with

   ```python
           base, policy = full_policy(db, None), full_policy(db, draft.get('policy'))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_preview_shows_a_charters_policy_changes_ships_and_hashes` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

9. An ordinary layer takes confirm_widenings silently. In `peer/superyak_peer/layers.py`, replace

   ```python
                   if confirm_widenings:
                       raise Problem(400, 'Only a charter has widenings to confirm')
   ```

   with

   ```python
                   if False:
                       raise Problem(400, 'Only a charter has widenings to confirm')
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charters_widenings_are_confirmed_path_by_path` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

---

### Task 5: Withdrawal confirms what widens; narrowing a charter is refused (R8, R9)

**Files:**
- Modify: `peer/superyak_peer/layers.py` (the import, `withdraw_layer`, `revoke_layer_routes`: about 8 lines)
- Modify: `peer/superyak_peer/app.py` (the withdraw route, 4 lines)
- Test: `peer/tests/test_charter.py` (about 55 lines)

**Interfaces:**
- Consumes: `DEFAULT_POLICY`, `widened_paths`, `confirm_paths`, `require_confirmed` (Tasks 1, 4); `_active_charter`.
- Produces: `Layers.withdraw_layer(actor, key, confirm_widenings=None)`; `revoke_layer_routes` 409 for a charter; the withdraw route reads an optional JSON body (empty is `{}`); test helper `in_force(store)`.

- [ ] **Step 1: Write the failing tests**

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def in_force(store):
    with store.transaction() as db:
        return store._policy_in_force(db)


def test_narrowing_a_charter_is_refused_and_writes_nothing(env):
    """Test 9 (R8, C14): today's refusals first (an unknown field 400, a stale revision 409), then 409, and no revision
    is written or signed. Catches a no-op revision that would move followers."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    law = new_layer(clients[0], **RULES, charter=True)
    assert sign(clients[0], law).status_code == 200
    path = f'/api/layers/{law["id"]}/revoke'
    assert refusal(clients[0].post(path, json={'revision': 1, 'colour': 'red'})) == (400, 'Unknown revocation field')
    assert refusal(clients[0].post(path, json={'revision': 2})) == (409, 'Active release changed; reload before revoking')
    for body in ({'revision': 1}, {'revision': 1, 'user_ids': []}, {'revision': 1, 'public': True}):
        assert refusal(clients[0].post(path, json=body)) == (
            409, 'A charter has no audience to narrow; sign a new revision or withdraw it'), body
    assert revision_count(app, law['id']) == 1 and set(signature_rows(store)) == {(law['id'], 1)}
    assert clients[0].get(f'/api/layers/{law["id"]}').json()['active_revision'] == 1


def test_withdrawing_a_charter_confirms_what_returns_to_the_defaults(env):
    """Test 10 (R9, C15): withdrawing a charter with max_depth 2 needs ["delegation.max_depth"] (409 without it, 400 for
    a malformed list); afterwards the policy in force is the defaults. One with the default policy withdraws with an
    empty body, and so does an ordinary layer. Catches a withdrawal that widens limits silently."""
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    crown(store, users[0])
    tight = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'delegation': {'max_depth': 2}})
    assert sign(clients[0], tight).status_code == 200  # a narrowing: nothing to confirm
    assert in_force(store)['delegation']['max_depth'] == 2
    path = f'/api/layers/{tight["id"]}/withdraw'
    assert refusal(clients[0].post(path)) == exactly('delegation.max_depth')
    assert refusal(clients[0].post(path, json={'confirm_widenings': []})) == exactly('delegation.max_depth')
    assert refusal(clients[0].post(path, json={'confirm_widenings': 'delegation.max_depth'})) == (400, 'confirm_widenings is a list of paths')
    assert in_force(store)['delegation']['max_depth'] == 2  # nothing was withdrawn
    withdrawn = clients[0].post(path, json={'confirm_widenings': ['delegation.max_depth']})
    assert withdrawn.status_code == 200 and withdrawn.json()['state'] == 'draft'
    assert in_force(store) == DEFAULT_POLICY
    assert clients[0].post(path).status_code == 200  # no longer active: as today, nothing to confirm
    plain = new_layer(clients[0], **RULES, charter=True)
    assert sign(clients[0], plain).status_code == 200
    assert clients[0].post(f'/api/layers/{plain["id"]}/withdraw').json()['state'] == 'draft'  # an empty body is {}
    ordinary = new_layer(clients[0], **RULES, audience_users=[ship['id']])
    assert sign(clients[0], ordinary).status_code == 200
    assert clients[0].post(f'/api/layers/{ordinary["id"]}/withdraw').json()['state'] == 'draft'
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `2 failed, 11 passed`. The failures: test 9 (`(200, None) == (409, 'A char... withdraw it')`: a no-op narrowing revision is written) and test 10 (`(200, None) == (409, 'Confir...on.max_depth')`: the withdrawal widens silently).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/layers.py`, replace

```python
from .charter import STAYS_A_CHARTER, check_draft
```

with

```python
from .charter import DEFAULT_POLICY, STAYS_A_CHARTER, check_draft, confirm_paths, require_confirmed, widened_paths
```

In `peer/superyak_peer/layers.py`, replace

```python
    def withdraw_layer(self, actor, key):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if row['active_revision'] is not None:
```

with

```python
    def withdraw_layer(self, actor, key, confirm_widenings=None):
        with self.transaction() as db:
            row = self._owned_layer(db, actor, key)
            if row['active_revision'] is not None:
                active = self._active_charter(db)
                if active is not None and active['id'] == key:  # C15: its limits return to the defaults (R9)
                    policy = json.loads(active['snapshot'])['policy']
                    require_confirmed(confirm_paths(confirm_widenings), widened_paths(policy, DEFAULT_POLICY))
```

In `peer/superyak_peer/layers.py`, replace

```python
            snapshot = json.loads(active['snapshot'])
            snapshot['audience_users'] = [u for u in snapshot['audience_users'] if u not in users]
```

with

```python
            snapshot = json.loads(active['snapshot'])
            if snapshot.get('charter') is True:  # C14: no audience to narrow, and a no-op revision would move followers
                raise Problem(409, 'A charter has no audience to narrow; sign a new revision or withdraw it')
            snapshot['audience_users'] = [u for u in snapshot['audience_users'] if u not in users]
```

In `peer/superyak_peer/app.py`, replace

```python
    @app.post('/api/layers/{key}/withdraw')
    def layer_withdraw(key: str, request: Request):
        return store.withdraw_layer(actor(request), key)
```

with

```python
    @app.post('/api/layers/{key}/withdraw')
    async def layer_withdraw(key: str, request: Request):
        who = actor(request)
        data = await body(request) if await request.body() else {}  # charter step 4: an empty body is {}, as before
        return store.withdraw_layer(who, key, data.get('confirm_widenings'))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_layers.py tests/test_instructions.py tests/test_signatures.py`
Expected: `74 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/layers.py peer/superyak_peer/app.py peer/tests/test_charter.py
git commit -m "Charter 4a: withdrawing a charter confirms what widens back to the defaults; narrowing one is refused (R8, R9)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. A withdrawal that widens limits silently. In `peer/superyak_peer/layers.py`, replace

   ```python
                       require_confirmed(confirm_paths(confirm_widenings), widened_paths(policy, DEFAULT_POLICY))
   ```

   with

   ```python
                       pass
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_withdrawing_a_charter_confirms_what_returns_to_the_defaults` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

2. The comparison the wrong way round: nothing to confirm. In `peer/superyak_peer/layers.py`, replace

   ```python
                       require_confirmed(confirm_paths(confirm_widenings), widened_paths(policy, DEFAULT_POLICY))
   ```

   with

   ```python
                       require_confirmed(confirm_paths(confirm_widenings), widened_paths(DEFAULT_POLICY, policy))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_withdrawing_a_charter_confirms_what_returns_to_the_defaults` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

3. A no-op narrowing revision written. In `peer/superyak_peer/layers.py`, replace

   ```python
               if snapshot.get('charter') is True:  # C14: no audience to narrow, and a no-op revision would move followers
   ```

   with

   ```python
               if False:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_narrowing_a_charter_is_refused_and_writes_nothing` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

4. An empty body refused as invalid JSON. In `peer/superyak_peer/app.py`, replace

   ```python
           data = await body(request) if await request.body() else {}  # charter step 4: an empty body is {}, as before
   ```

   with

   ```python
           data = await body(request)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_withdrawing_a_charter_confirms_what_returns_to_the_defaults` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/app.py`.

---

### Task 6: The policy in force governs grants (R10-R12)

**Files:**
- Modify: `peer/superyak_peer/charter.py` (`flat_policy`, about 10 lines)
- Modify: `peer/superyak_peer/grants.py` (the import, two refusals, `_grant_policy`, `grant_policy`, `_issued_by_a_ship`, validity, `grant_people`, `make_grant`: about 35 lines)
- Modify: `peer/superyak_peer/app.py` (`GET /api/grants/policy`, 4 lines)
- Test: `peer/tests/test_charter.py` (about 100 lines)

**Interfaces:**
- Consumes: `_policy_in_force` (Task 4); `test_grants.make`, `validity`; `test_grant_tickets.room`, `mention`, `decide`.
- Produces: `charter.flat_policy(policy) -> {max_depth, max_expiry_hours, agent_grant_default_hours, builds_per_ship_per_day, delegable, grantees}` (`grantees` the `people` list or None); `Grants._grant_policy(db)` reads the policy in force; `Grants.grant_policy(actor) -> {max_depth, max_expiry_hours, builds_per_ship_per_day}`; `Grants._issued_by_a_ship(db, link) -> bool`; `grants.NO_GRANTS`, `grants.GRANTEE_NOT_ALLOWED`; `GET /api/grants/policy`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_charter.py`, replace

```python
from test_instructions import OLD_FIELDS, activate, crown, docked, new_layer, ship_client, stored
```

with

```python
from test_grant_tickets import decide, mention, room
from test_grants import make, validity
from test_instructions import OLD_FIELDS, activate, crown, docked, new_layer, ship_client, stored
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def grant_count(store):
    with store.transaction() as db:
        return db.execute('SELECT count(*) FROM grants').fetchone()[0]


def test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap(env):
    """Test 11 (R10, R11, C16): under max_expiry_hours 48 a 49-hour grant is refused, an existing 72-hour grant is
    invalid at the next ticket, and GET /api/grants/policy says 48; withdrawing makes the grant valid again. Under
    builds_per_ship_per_day 1, a ship's second grant build reads. Under max_depth 0 every grant is invalid, and making
    one gets 400 before any other check, with nothing signed. Catches _grant_policy still returning the defaults,
    reading the draft instead of the active revision, and signing a grant invalid from birth."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor = users[0], users[1]
    crown(store, patient)
    serenity, _ = docked(store, patient['id'], 'serenity')
    ops = room(store, patient, 'Ops', doctor, serenity)
    long = make(store, patient, doctor, [serenity], hours=72)
    assert clients[1].get('/api/grants/policy').json() == {'max_depth': 3, 'max_expiry_hours': 720, 'builds_per_ship_per_day': 20}
    law = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'delegation': {'max_expiry_hours': 48}})
    assert sign(clients[0], law).status_code == 200
    assert clients[1].get('/api/grants/policy').json() == {'max_depth': 3, 'max_expiry_hours': 48, 'builds_per_ship_per_day': 20}
    assert validity(store, long) == (False, f'Grant #{long[:4]} lasts longer than the station now allows')
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')
    made = {'grantee': doctor['id'], 'targets': [serenity['id']], 'rooms': '*', 'hours': 49, 'budget': 5}
    assert refusal(clients[0].post('/api/grants', json=made)) == (400, 'hours is a whole number from 1 to 48')
    assert clients[0].post('/api/grants', json={**made, 'hours': 48}).status_code == 201
    withdrawn = clients[0].post(f'/api/layers/{law["id"]}/withdraw', json={'confirm_widenings': ['delegation.max_expiry_hours']})
    assert withdrawn.status_code == 200, withdrawn.text
    assert validity(store, long) == (True, None)
    law = save(clients[0], withdrawn.json(), policy={'version': 1, 'budgets': {'builds_per_ship_per_day': 1}})
    assert sign(clients[0], law).status_code == 200
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('build', 'grant')
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')
    assert [target['ship_builds_left'] for grant in clients[1].get('/api/grants').json() for target in grant['targets']] == [0, 0]
    law = save(clients[0], law, policy={'version': 1, 'delegation': {'max_depth': 0}, 'budgets': {'builds_per_ship_per_day': 1}})
    assert clients[1].get('/api/grants/policy').json()['max_depth'] == 3  # a saved draft binds nothing until it is signed
    assert sign(clients[0], law).status_code == 200
    assert validity(store, long) == (False, f"Grant #{long[:4]} is no longer allowed by the station's policy")
    before = grant_count(store)
    for fields in ({**made, 'hours': 24}, {**made, 'rooms': ['no-such-room'], 'grantee': patient['id'], 'hours': 0}):
        assert refusal(clients[0].post('/api/grants', json=fields)) == (400, "The station's charter allows no grants"), fields
    assert grant_count(store) == before and clients[0].get('/api/grants/policy').json()['max_depth'] == 0


def test_a_grantee_set_in_force_limits_making_validity_and_the_person_list(env):
    """Test 12 (R11, C16): with people [Jenn], a grant to Stanley gets 400 (after G8's step 3, before step 4), Stanley's
    existing grant is invalid at the next ticket, Jenn's stays valid, and GET /api/grants/people lists only Jenn, still
    as a list. Catches testing membership in the grantee object, not its list."""
    app, clients, users, clock = env
    store = app.state.store
    patient, jenn, stanley = users[0], users[1], users[3]
    crown(store, patient)
    serenity, _ = docked(store, patient['id'], 'serenity')
    ops = room(store, patient, 'Ops', jenn, stanley, serenity)
    theirs = make(store, patient, stanley, [serenity], hours=48)
    hers = make(store, patient, jenn, [serenity], hours=48)
    law = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'grantees': {'people': [jenn['id']]}})
    assert sign(clients[0], law).status_code == 200
    made = {'grantee': stanley['id'], 'targets': [serenity['id']], 'rooms': '*', 'hours': 24, 'budget': 5}
    refused = (400, "The station's charter doesn't allow grants to this person")
    assert refusal(clients[0].post('/api/grants', json=made)) == refused
    assert refusal(clients[0].post('/api/grants', json={**made, 'targets': ['no-such-ship']})) == refused  # 3a before 4
    assert refusal(clients[0].post('/api/grants', json={**made, 'grantee': patient['id']})) == (400, 'You cannot grant to yourself')
    assert clients[0].post('/api/grants', json={**made, 'grantee': jenn['id']}).status_code == 201
    assert validity(store, theirs) == (False, f"Grant #{theirs[:4]} is no longer allowed by the station's policy")
    assert validity(store, hers) == (True, None)
    assert decide(store, serenity, mention(store, stanley, ops, serenity)) == ('read', 'none')
    assert decide(store, serenity, mention(store, jenn, ops, serenity)) == ('build', 'grant')
    assert clients[0].get('/api/grants/people').json() == [{'id': jenn['id'], 'name': 'Doctor'}]
    assert clients[1].get('/api/grants/people').json() == []  # the caller is never listed


def test_delegable_governs_links_a_ship_issued_and_never_a_browser_root(env):
    """Test 13 (R12): a hand-made child grant issued by a ship is valid under the defaults and invalid under
    delegable []; the browser root above it stays valid. Catches applying delegable to browser roots, or not at all."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, family = users[0], users[1], users[3]
    crown(store, patient)
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    root = make(store, patient, doctor, [serenity], hours=48)
    child = make(store, rio, family, [serenity], hours=48)  # issued by a ship: only step 5 will make one
    with store.transaction() as db:
        db.execute('UPDATE grants SET parent_id=? WHERE id=?', (root, child))
    assert validity(store, child) == (True, None) and validity(store, root) == (True, None)
    law = new_layer(clients[0], **RULES, charter=True, policy={'version': 1, 'delegation': {'delegable': []}})
    assert sign(clients[0], law).status_code == 200
    assert validity(store, child) == (False, f"Grant #{child[:4]} is no longer allowed by the station's policy")
    assert validity(store, root) == (True, None)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `3 failed, 13 passed`. The failures: test 11 (`{'detail': 'Not Found'}`: no `/api/grants/policy` yet), test 12 (`(201, None) == (400, "The st... this person")`) and test 13 (`(True, None) == (False, "Gran...ion's policy")`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/charter.py`, insert before

```python
def check_draft(db, draft, sealed=False):
```

this, followed by two blank lines:

```python
def flat_policy(policy):
    """C16: a full policy as Grants' readers read it, `grantees` flattened to the `people` list, or None unrestricted."""
    delegation = policy['delegation']
    return {'max_depth': delegation['max_depth'], 'max_expiry_hours': delegation['max_expiry_hours'],
            'agent_grant_default_hours': delegation['agent_grant_default_hours'],
            'builds_per_ship_per_day': policy['budgets']['builds_per_ship_per_day'],
            'delegable': list(delegation['delegable']),
            'grantees': None if policy['grantees'] is None else list(policy['grantees']['people'])}
```

In `peer/superyak_peer/grants.py`, replace

```python
from datetime import datetime, timezone
import json
from .common import REPLACED_ROOMS, Problem, encode, uid
```

with

```python
from datetime import datetime, timezone
import json
from .charter import flat_policy
from .common import REPLACED_ROOMS, Problem, encode, uid
```

In `peer/superyak_peer/grants.py`, replace

```python
REASON_SHAPE = 'A reason is one line of at most 200 characters'
```

with

```python
REASON_SHAPE = 'A reason is one line of at most 200 characters'
NO_GRANTS = "The station's charter allows no grants"  # charter step 4: G8 step 0, while max_depth is 0
GRANTEE_NOT_ALLOWED = "The station's charter doesn't allow grants to this person"  # G8 step 3a
```

In `peer/superyak_peer/grants.py`, replace

```python
    def _grant_policy(self, db):
        """G7: spec A's no-charter defaults. Every check reads the policy through this one function, so step 4 puts the
        charter behind it and validity doesn't change. `grantees` None is the unrestricted set."""
        return {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24, 'builds_per_ship_per_day': 20,
                'delegable': ['direct'], 'grantees': None}
```

with

```python
    def _grant_policy(self, db):
        """G7 as charter step 4 amends it (C16): the policy in force, the active charter revision's or spec A's
        no-charter defaults, flattened: `grantees` is the `people` list, or None for the unrestricted set. Every check
        reads it here, so a change takes effect at the next check and a withdrawal restores the defaults (R10)."""
        return flat_policy(self._policy_in_force(db))

    def grant_policy(self, actor):
        """GET /api/grants/policy (C16): the limits of the policy in force the grants form reads."""
        with self.transaction() as db:
            self._person(db, actor)
            policy = self._grant_policy(db)
            return {key: policy[key] for key in ('max_depth', 'max_expiry_hours', 'builds_per_ship_per_day')}

    def _issued_by_a_ship(self, db, link):
        return db.execute("SELECT 1 FROM users WHERE id=? AND kind='ship'", (link['issuer_id'],)).fetchone() is not None
```

In `peer/superyak_peer/grants.py`, replace

```python
            if len(chain) > policy['max_depth'] or (policy['grantees'] is not None and link['grantee_id'] not in policy['grantees']):
                return False, f"Grant {short} is no longer allowed by the station's policy"
```

with

```python
            if (len(chain) > policy['max_depth'] or (policy['grantees'] is not None and link['grantee_id'] not in policy['grantees'])
                    or (self._issued_by_a_ship(db, link) and not set(json.loads(link['actions'])) <= set(policy['delegable']))):
                return False, f"Grant {short} is no longer allowed by the station's policy"  # delegable: R12, C16
```

In `peer/superyak_peer/grants.py`, replace

```python
        with self.transaction() as db:
            self._person(db, actor)
            return [dict(row) for row in db.execute("SELECT id, name FROM users WHERE kind='person' AND activation_pending=0 "
                                                    'AND id!=? ORDER BY name COLLATE NOCASE, id', (actor,))]
```

with

```python
        with self.transaction() as db:
            self._person(db, actor)
            allowed = self._grant_policy(db)['grantees']  # C16: while a grantee set is in force, only its people
            return [dict(row) for row in db.execute("SELECT id, name FROM users WHERE kind='person' AND activation_pending=0 "
                                                    'AND id!=? ORDER BY name COLLATE NOCASE, id', (actor,))
                    if allowed is None or row['id'] in allowed]
```

In `peer/superyak_peer/grants.py`, replace

```python
            policy = self._grant_policy(db)
            rooms = self._grant_rooms(db, actor, grantee, rooms)
            self._grant_grantee(db, actor, grantee)
            targets = self._grant_targets(db, actor, targets)
```

with

```python
            policy = self._grant_policy(db)
            if policy['max_depth'] == 0:
                raise Problem(400, NO_GRANTS)  # step 0: a grant made now would be invalid from its first moment
            rooms = self._grant_rooms(db, actor, grantee, rooms)
            self._grant_grantee(db, actor, grantee)
            if policy['grantees'] is not None and grantee not in policy['grantees']:
                raise Problem(400, GRANTEE_NOT_ALLOWED)  # step 3a
            targets = self._grant_targets(db, actor, targets)
```

In `peer/superyak_peer/app.py`, replace

```python
    @app.get('/api/grants/people')
    def grant_people(request: Request):
        return store.grant_people(actor(request))
```

with

```python
    @app.get('/api/grants/people')
    def grant_people(request: Request):
        return store.grant_people(actor(request))

    @app.get('/api/grants/policy')
    def grant_policy(request: Request):
        return store.grant_policy(actor(request))  # charter step 4 (C16): the grants form's limits
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_grants.py tests/test_grant_tickets.py`
Expected: `61 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/charter.py peer/superyak_peer/grants.py peer/superyak_peer/app.py peer/tests/test_charter.py
git commit -m "Charter 4a: the policy in force governs every grant: limits, grantee set, delegable, GET /api/grants/policy (R10-R12)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. _grant_policy still the defaults, as step 3 left it. In `peer/superyak_peer/grants.py`, replace

   ```python
           return flat_policy(self._policy_in_force(db))
   ```

   with

   ```python
           return {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24, 'builds_per_ship_per_day': 20, 'delegable': ['direct'], 'grantees': None}
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

2. A grant made and signed under max_depth 0. In `peer/superyak_peer/grants.py`, replace

   ```python
               if policy['max_depth'] == 0:
                   raise Problem(400, NO_GRANTS)
   ```

   with

   ```python
               if False:
                   raise Problem(400, NO_GRANTS)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

3. No step 3a. In `peer/superyak_peer/grants.py`, replace

   ```python
               if policy['grantees'] is not None and grantee not in policy['grantees']:
                   raise Problem(400, GRANTEE_NOT_ALLOWED)  # step 3a
   ```

   with

   ```python
               if False:
                   raise Problem(400, GRANTEE_NOT_ALLOWED)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_grantee_set_in_force_limits_making_validity_and_the_person_list` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

4. Membership tested in the grantee object, not its list. In `peer/superyak_peer/charter.py`, replace

   ```python
               'grantees': None if policy['grantees'] is None else list(policy['grantees']['people'])}
   ```

   with

   ```python
               'grantees': policy['grantees']}
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_grantee_set_in_force_limits_making_validity_and_the_person_list` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

5. Delegable applied to browser roots. In `peer/superyak_peer/grants.py`, replace

   ```python
                       or (self._issued_by_a_ship(db, link) and not set(json.loads(link['actions'])) <= set(policy['delegable']))):
   ```

   with

   ```python
                       or not set(json.loads(link['actions'])) <= set(policy['delegable'])):
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_delegable_governs_links_a_ship_issued_and_never_a_browser_root` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

6. Delegable not checked at all. In `peer/superyak_peer/grants.py`, replace

   ```python
                       or (self._issued_by_a_ship(db, link) and not set(json.loads(link['actions'])) <= set(policy['delegable']))):
   ```

   with

   ```python
                       ):
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_delegable_governs_links_a_ship_issued_and_never_a_browser_root` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

7. The person list unfiltered. In `peer/superyak_peer/grants.py`, replace

   ```python
                       if allowed is None or row['id'] in allowed]
   ```

   with

   ```python
                       ]
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_grantee_set_in_force_limits_making_validity_and_the_person_list` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

8. GET /api/grants/policy fixed at the defaults. In `peer/superyak_peer/grants.py`, replace

   ```python
               return {key: policy[key] for key in ('max_depth', 'max_expiry_hours', 'builds_per_ship_per_day')}
   ```

   with

   ```python
               return {'max_depth': 3, 'max_expiry_hours': 720, 'builds_per_ship_per_day': 20}
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/grants.py`.

9. The policy read from the charter layer's draft, not its active revision. In `peer/superyak_peer/charter.py`, replace

   ```python
           return copy.deepcopy(DEFAULT_POLICY) if active is None else json.loads(active['snapshot'])['policy']
   ```

   with

   ```python
           return copy.deepcopy(DEFAULT_POLICY) if active is None else full_policy(db, json.loads(active['draft']).get('policy'))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/charter.py`.

---

### Task 7: Binding: the charter first for its signer's ships and the residents; the law converted in place (R14, R15)

**Files:**
- Modify: `peer/superyak_peer/instructions.py` (the docstring, `binding_entry`, `_layers_for`, `_charter_pair`, `_own_layers`, `_binding_layers`, `_check_instruction_caps`'s head: about 60 lines)
- Modify: `peer/superyak_peer/layers.py` (the caps call, 1 line)
- Test: `peer/tests/test_instructions.py` (test 14 replaces `test_a_resident_ship_has_no_instructions_in_this_step`; test 15; the oracle, test 23: about 150 lines); `peer/tests/test_charter.py` (test 7, about 45 lines)

**Interfaces:**
- Consumes: `_active_charter`'s rule (a snapshot with `charter: true`); `sign`, `save`, `revision_count` (Tasks 3, 4).
- Produces: `instructions.binding_entry(layer_id, revision, snapshot, signer_id, signer_name, created) -> dict` with `charter`; `Instructions._charter_pair(db, ship) -> (layer_id, revision) | None`; `Instructions._own_layers(db, ship, replace=None) -> list[dict]`, `replace` being `{layer_id, revision, snapshot, created}`; `_binding_layers(db, ship_id, replace=None)` = `_layers_for(db, [pair])` + `_own_layers(db, ship, replace)`; `_check_instruction_caps(db, actor, key, snapshot, revision)`; `_layers_for` in the order given.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_instructions.py`, replace

```python
def test_a_resident_ship_has_no_instructions_in_this_step(env):
    app, clients, users, clock = env
    store = app.state.store
    odo = store.create_station_ship('odo', 'Odo')
    assert instructions_of(app, store.issue_ship_key(odo['id']))['instructions'] == []
```

with

```python
def test_the_charter_binds_its_signers_ships_and_the_residents_first(env):
    """Charter step 4's test 14 (R14, C17, C22), replacing step 2's "a resident ship has no instructions": after the
    conversion the signer's ships have the charter first, then the signer's other layers by creation; Odo and Wormhole
    have the charter only; another owner's ship has none of it; after withdrawal no ship has it. Catches the charter
    reached through rule 2's audience, which is empty, so lost."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    defiant, _ = docked(store, users[1]['id'], 'defiant')
    odo, wormhole = store.create_station_ship('odo', 'Odo'), store.create_station_ship('wormhole', 'Wormhole')
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[serenity['id'], rio['id']])
    assert activate(clients[0], law).status_code == 200
    clock[0] += 1
    house = new_layer(clients[0], kind='instructions', title='House rules', body='Run the tests.', audience_users=[serenity['id']])
    assert activate(clients[0], house).status_code == 200
    theirs = new_layer(clients[1], kind='instructions', title='Their rules', body='x', audience_users=[defiant['id']])
    assert activate(clients[1], theirs).status_code == 200
    assert binding(app, serenity['id']) == [(law['id'], 1), (house['id'], 1)]
    clock[0] += 1
    converted = clients[0].put(f'/api/layers/{law["id"]}', json={'version': law['version'], 'charter': True,
                                                                 'audience_users': []}).json()
    assert activate(clients[0], converted).json()['revision'] == 2
    assert binding(app, serenity['id']) == [(law['id'], 2), (house['id'], 1)]  # the charter first, though signed last
    assert binding(app, rio['id']) == [(law['id'], 2)]
    for resident in (odo, wormhole):
        assert binding(app, resident['id']) == [(law['id'], 2)]
    assert instructions_of(app, store.issue_ship_key(odo['id']))['instructions'] == [[law['id'], 2]]
    assert binding(app, defiant['id']) == [(theirs['id'], 1)]
    with store.transaction() as db:
        found = store._binding_layers(db, odo['id'])
    assert (found[0]['charter'], found[0]['signer_id'], found[0]['signer_name']) == (True, users[0]['id'], 'Patient')
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    assert binding(app, serenity['id']) == [(house['id'], 1)] and binding(app, rio['id']) == []
    assert binding(app, odo['id']) == binding(app, wormhole['id']) == []
    assert binding(app, defiant['id']) == [(theirs['id'], 1)]
```

In `peer/tests/test_instructions.py`, insert after

```python
    again = ship_client(app, key).post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    assert again['id'] == ticket['id'] and 'Version one.' in again['blocks'] and 'Version two.' not in again['blocks']
```

this, leaving two blank lines between them:

```python
def test_a_ticket_renders_the_charter_block_first_in_the_recorded_order(env):
    """Charter step 4's test 15 (R15): a ticket whose owner layer was created before the charter records the charter
    first, and its blocks render in the recorded order. Catches _layers_for re-sorting by created."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    ship, key = docked(store, users[0]['id'], 'serenity')
    house = new_layer(clients[0], kind='instructions', title='House rules', body='Run the tests first.', audience_users=[ship['id']])
    assert activate(clients[0], house).status_code == 200
    clock[0] += 1
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', charter=True)
    assert activate(clients[0], law).status_code == 200
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id']]}).json()['id']
    asked = clients[0].post(f'/api/chats/{room}/messages', json={'client_message_id': 'a', 'body': '@serenity go'}).json()
    ticket = ship_client(app, key).post('/api/ships/me/tickets', json={'message_id': asked['id']}).json()
    assert ticket['instructions'] == [[law['id'], 1], [house['id'], 1]]
    assert ticket['blocks'].index('Be kind.') < ticket['blocks'].index('Run the tests first.')
```

In `peer/tests/test_instructions.py`, replace

```python
def test_binding_matches_an_independent_reading_of_the_rule(env):
    """Spec Testing 2, forbidden exposure 0: for random owners, layers, audiences, kinds, withdrawals and narrowings,
    a ship's binding set is exactly what the rule's text says, computed here without the station's code."""
    app, clients, users, clock = env
    store, rng = app.state.store, random.Random(20261008)
    ships = [docked(store, users[i % 2]['id'], f'ship-{i}') for i in range(4)]
    expected = {s['id']: {} for s, _ in ships}  # ship -> {layer_id: revision}, per the rule
    bound, unbound = 0, 0  # activated cases that bound some ship, and ones that bound none
    for case in range(60):
        author = rng.randrange(2)
        audience = [s['id'] for s, _ in ships if rng.random() < 0.5]
        kind = rng.choice(['instructions', 'instructions', 'note'])
        layer = new_layer(clients[author], kind=kind, title=f'L{case}', body=f'body {case}', audience_users=audience)
        if not audience or rng.random() < 0.2:
            continue
        response = activate(clients[author], layer)
        if response.status_code != 200:
            continue
        revision, owner = response.json()['revision'], users[author]['id']
        binds = [s['id'] for s, _ in ships if kind == 'instructions' and s['id'] in audience and s['owner_id'] == owner]
        for ship_id in binds:
            expected[ship_id][layer['id']] = revision
        bound, unbound = bound + bool(binds), unbound + (not binds)
        if rng.random() < 0.3:
            clients[author].post(f'/api/layers/{layer["id"]}/withdraw')
            for s, _ in ships:
                expected[s['id']].pop(layer['id'], None)
        elif rng.random() < 0.3:
            narrowed = rng.choice(audience)
            out = clients[author].post(f'/api/layers/{layer["id"]}/revoke', json={'revision': revision, 'user_ids': [narrowed]})
            if out.status_code == 200:
                for s, _ in ships:
                    if layer['id'] in expected[s['id']]:
                        expected[s['id']][layer['id']] = out.json()['revision']
                expected[narrowed].pop(layer['id'], None)
    assert bound and unbound and any(expected.values())  # the comparison below is not vacuous
    for s, key in ships:
        got = {lid: rev for lid, rev in instructions_of(app, key)['instructions']}
        assert got == expected[s['id']], s['username']
```

with

```python
def test_binding_matches_an_independent_reading_of_the_rule(env):
    """Spec Testing 2, forbidden exposure 0, and charter step 4's test 23: for random owners, layers, audiences, kinds,
    withdrawals, narrowings and charters (activated, revised, withdrawn and activated again, and a second one refused),
    with residents, each ship's binding is exactly what "Binding" says, in its order: the charter pair first, for a
    resident or a ship its signer owns; then the owner's own active instructions layers that list the ship, by the time
    their revision was written. The expected list is computed here without the station's code."""
    app, clients, users, clock = env
    store, rng = app.state.store, random.Random(20261015)
    crown(store, users[0])  # users[0] signs every charter
    ships = [docked(store, users[i % 2]['id'], f'ship-{i}') for i in range(4)]
    residents = [store.create_station_ship(f'res-{i}', f'Res {i}') for i in range(2)]
    keyed = [(s['id'], s['owner_id'], key) for s, key in ships] + [(r['id'], None, store.issue_ship_key(r['id'])) for r in residents]
    own = {}  # layer id -> [owner, revision, audience, written] while its active revision is ordinary instructions
    drafts, charter = {}, None  # charter layers by id, as last saved; the active one as (layer id, revision)
    seen = dict.fromkeys(('activated', 'revised', 'withdrawn', 'again', 'refused'), 0)
    bound, unbound = 0, 0  # activated ordinary cases that bound some ship, and ones that bound none
    for case in range(80):
        clock[0] += 1
        if rng.random() < 0.25:  # a charter step
            if charter is not None and rng.random() < 0.3:
                assert clients[0].post(f'/api/layers/{charter[0]}/withdraw').status_code == 200
                charter, seen['withdrawn'] = None, seen['withdrawn'] + 1
                continue
            if charter is not None and rng.random() < 0.3:  # a second charter layer while one is active
                other = new_layer(clients[0], kind='instructions', title=f'C{case}', body=f'charter {case}', charter=True)
                drafts[other['id']] = other
                refused = activate(clients[0], other)
                assert (refused.status_code, refused.json()['error']) == (409, 'Another charter is active; its owner must withdraw it first')
                seen['refused'] += 1
                continue
            if charter is not None:
                layer_id, step = charter[0], 'revised'
            elif drafts and rng.random() < 0.5:
                layer_id, step = rng.choice(sorted(drafts)), 'again'
            else:
                made = new_layer(clients[0], kind='instructions', title=f'C{case}', body=f'charter {case}', charter=True)
                drafts[made['id']], layer_id, step = made, made['id'], 'activated'
            drafts[layer_id] = clients[0].put(f'/api/layers/{layer_id}', json={'version': drafts[layer_id]['version'],
                                                                              'body': f'charter {case}'}).json()
            response = activate(clients[0], drafts[layer_id])
            if response.status_code == 200:
                charter, seen[step] = (layer_id, response.json()['revision']), seen[step] + 1
            else:
                assert response.status_code == 409, response.text  # the caps (C23): nothing changes
            continue
        author = rng.randrange(2)
        audience = [s['id'] for s, _ in ships if rng.random() < 0.5]
        kind = rng.choice(['instructions', 'instructions', 'note'])
        layer = new_layer(clients[author], kind=kind, title=f'L{case}', body=f'body {case}', audience_users=audience)
        if not audience or rng.random() < 0.2:
            continue
        response = activate(clients[author], layer)
        if response.status_code != 200:
            continue
        revision, owner = response.json()['revision'], users[author]['id']
        if kind == 'instructions':
            own[layer['id']] = [owner, revision, audience, clock[0]]
        binds = [s['id'] for s, _ in ships if kind == 'instructions' and s['id'] in audience and s['owner_id'] == owner]
        bound, unbound = bound + bool(binds), unbound + (not binds)
        if rng.random() < 0.3:
            clients[author].post(f'/api/layers/{layer["id"]}/withdraw')
            own.pop(layer['id'], None)
        elif rng.random() < 0.3:
            narrowed = rng.choice(audience)
            out = clients[author].post(f'/api/layers/{layer["id"]}/revoke', json={'revision': revision, 'user_ids': [narrowed]})
            if out.status_code == 200 and layer['id'] in own:
                own[layer['id']] = [owner, out.json()['revision'], [s for s in audience if s != narrowed], clock[0]]

    def expected(ship_id, owner):
        pairs = [charter] if charter is not None and owner in (None, users[0]['id']) else []
        mine = sorted((written, lid, rev) for lid, (by, rev, audience, written) in own.items()
                      if owner is not None and by == owner and ship_id in audience)
        return pairs + [(lid, rev) for written, lid, rev in mine]
    assert bound and unbound and all(seen.values()), seen  # the comparison below is not vacuous
    assert charter is not None or any(o for o in own.values())
    for ship_id, owner, key in keyed:
        got = [tuple(pair) for pair in instructions_of(app, key)['instructions']]
        assert got == expected(ship_id, owner), ship_id
```

In `peer/tests/test_charter.py`, replace

```python
import copy
import hashlib
import json
from superyak_peer.charter import DEFAULT_POLICY, full_policy
from superyak_peer.common import Problem, uid
from superyak_peer.identity import verify_record
from test_grant_tickets import decide, mention, room
from test_grants import make, validity
from test_instructions import OLD_FIELDS, activate, crown, docked, new_layer, ship_client, stored
```

with

```python
import copy
import hashlib
import json
import pytest
from superyak_peer.charter import DEFAULT_POLICY, full_policy
from superyak_peer.common import Problem, uid
from superyak_peer.identity import PeerIdentity, verify_record
from test_grant_tickets import decide, mention, room
from test_grants import make, validity
from test_instructions import OLD_FIELDS, activate, binding, crown, docked, new_layer, ship_client, stored
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def test_the_law_becomes_the_charter_in_place_in_one_transaction(env, monkeypatch):
    """Test 7 (R2, R13, R14, C4, C5): an instructions layer at revision 1 (two ships, no policy) becomes a charter in
    place, with no widening to confirm. With the signing failing after the revision is written, the activation rolls
    back and both ships are still bound by (L, 1); without it, both are bound by (L, 2) first, revision 2's record has
    kind instructions-revision, no audience and the default policy, and verifies, and revision 1's signature row is
    unchanged and still verifies. Catches a baseline read from revision 1's missing policy, a write outside the
    activation's transaction, and a record change that breaks old signatures."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    house = new_layer(clients[0], kind='instructions', title='House rules', body='Run the tests.', audience_users=[serenity['id']])
    assert activate(clients[0], house).status_code == 200
    clock[0] += 1
    law = new_layer(clients[0], kind='instructions', title="Station law for Andy's ships", body='Be kind.',
                    audience_users=[serenity['id'], rio['id']])
    assert activate(clients[0], law).status_code == 200
    first = signature_rows(store)[(law['id'], 1)]
    converted = save(clients[0], law, charter=True, audience_users=[])

    def failing(self, record):
        raise ValueError('signing failed')
    monkeypatch.setattr(PeerIdentity, 'sign_record', failing)
    with pytest.raises(ValueError):
        store.activate_layer(users[0]['id'], law['id'], converted['version'])
    monkeypatch.undo()
    assert binding(app, serenity['id']) == [(house['id'], 1), (law['id'], 1)] and binding(app, rio['id']) == [(law['id'], 1)]
    assert revision_count(app, law['id']) == 1
    assert sign(clients[0], converted).json()['revision'] == 2  # nothing to confirm: the defaults are in force (C5)
    assert binding(app, serenity['id']) == [(law['id'], 2), (house['id'], 1)] and binding(app, rio['id']) == [(law['id'], 2)]
    card, rows = card_of(store._station_identity()), signature_rows(store)
    record = stored_record(store, law['id'], 2)
    assert (record['kind'], record['audience_users'], record['policy']) == ('instructions-revision', [], DEFAULT_POLICY)
    assert verify_record(card, record, rows[(law['id'], 2)])
    assert rows[(law['id'], 1)] == first and stored_record(store, law['id'], 1)['policy'] is None
    assert verify_record(card, stored_record(store, law['id'], 1), first)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py`
Expected: `4 failed, 37 passed`. The failures: test 7 (after signing, serenity has `[(house, 1)]`, not `[(law, 2), (house, 1)]`: nothing binds through the charter yet), test 15 (the ticket records `[[house, 1]]` alone), test 14 (serenity after the conversion, the same) and the oracle (a ship's list lacks the charter).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/instructions.py`, replace

```python
"""Which instruction layers bind a ship, the prompt blocks that carry them, and the caps that keep them in one
command-line argument (spec A, sections 1 and 4). Build step 2: only the ship's owner's own active instruction layers
bind it. Grants (step 3) and the charter (step 4) add to this rule; they never replace it."""
```

with

```python
"""Which instruction layers bind a ship, the prompt blocks that carry them, and the caps that keep them in one
command-line argument (spec A, sections 1 and 4). Build step 2: the ship's owner's own active instruction layers bind
it. Charter step 4 puts the station's charter first, for the ships its signer owns and for the residents (merge 4c adds
owners who accept it); it never replaces the owner's own layers."""
```

In `peer/superyak_peer/instructions.py`, insert before

```python
class Instructions:
```

this, followed by two blank lines:

```python
def binding_entry(layer_id, revision, snapshot, signer_id, signer_name, created):
    """One binding layer, as _binding_layers and _layers_for give it; `charter` marks a charter revision."""
    return {'layer_id': layer_id, 'revision': revision, 'title': snapshot['title'], 'body': snapshot['body'],
            'signer_id': signer_id, 'signer_name': signer_name, 'created': created, 'charter': snapshot.get('charter') is True}
```

In `peer/superyak_peer/instructions.py`, replace

```python
    def _layers_for(self, db, pairs):
        """The layers at exactly these (layer_id, revision) pairs, as _binding_layers returns them."""
```

with

```python
    def _layers_for(self, db, pairs):
        """The layers at exactly these (layer_id, revision) pairs, in the order given: a ticket records them in binding
        order, the charter first, and they render in that order, never re-sorted (R15)."""
```

In `peer/superyak_peer/instructions.py`, replace

```python
            if row:
                snap = json.loads(row['snapshot'])
                found.append({'layer_id': layer_id, 'revision': revision, 'title': snap['title'], 'body': snap['body'],
                              'signer_id': row['owner_id'], 'signer_name': row['signer'], 'created': row['created']})
        return sorted(found, key=lambda l: (l['created'], l['layer_id']))
```

with

```python
            if row:
                found.append(binding_entry(layer_id, revision, json.loads(row['snapshot']), row['owner_id'], row['signer'],
                                           row['created']))
        return found
```

In `peer/superyak_peer/instructions.py`, replace

```python
    def _binding_layers(self, db, ship_id, replace=None):
        ship = require(db.execute('SELECT * FROM users WHERE id=?', (ship_id,)).fetchone())
        if ship['kind'] != 'ship' or not ship['owner_id']:
            return []
        signer = db.execute('SELECT name FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['name']
        rows = [(r['layer_id'], r['revision'], json.loads(r['snapshot']), r['created']) for r in db.execute(
            'SELECT layers.id AS layer_id, layer_revisions.revision, layer_revisions.snapshot, layer_revisions.created '
            'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
            'WHERE layers.owner_id=?', (ship['owner_id'],))]
        if replace is not None:
            rows = [r for r in rows if r[0] != replace['layer_id']] + [(replace['layer_id'], replace.get('revision', 0), replace['snapshot'], replace['created'])]
        found = [{'layer_id': lid, 'revision': rev, 'title': snap['title'], 'body': snap['body'], 'signer_id': ship['owner_id'],
                  'signer_name': signer, 'created': created}
                 for lid, rev, snap, created in rows if snap.get('kind') == 'instructions' and ship_id in snap.get('audience_users', [])]
        return sorted(found, key=lambda l: (l['created'], l['layer_id']))

    def _check_instruction_caps(self, db, actor, key, snapshot):
        if not snapshot['audience_users']:
            raise Problem(400, 'Choose at least one ship for these instructions')
        for ship_id in snapshot['audience_users']:
            row = db.execute('SELECT owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if not row or row['owner_id'] != actor:
                continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
            layers = self._binding_layers(db, ship_id, replace={'layer_id': key, 'snapshot': snapshot, 'created': self.clock(), 'revision': 0})
```

with

```python
    def _charter_pair(self, db, ship):
        """Binding step 2 in 4a: (layer_id, revision) of the active charter for a resident (no owner) or for a ship its
        signer owns (C17), else None; merge 4c adds the owners who accept it. A withdrawn charter binds nothing."""
        active = self._active_charter(db)
        if active is not None and ship['owner_id'] in (None, active['owner_id']):
            return active['id'], active['active_revision']
        return None

    def _own_layers(self, db, ship, replace=None):
        """Binding step 3: the owner's own active non-charter instructions layers whose audience lists the ship, by
        (created, layer_id). `replace` ({layer_id, revision, snapshot, created}) stands in for that layer's active
        revision, as if activated now: an activation's caps check."""
        if not ship['owner_id']:
            return []
        signer = db.execute('SELECT name FROM users WHERE id=?', (ship['owner_id'],)).fetchone()['name']
        rows = [(r['layer_id'], r['revision'], json.loads(r['snapshot']), r['created']) for r in db.execute(
            'SELECT layers.id AS layer_id, layer_revisions.revision, layer_revisions.snapshot, layer_revisions.created '
            'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
            'WHERE layers.owner_id=?', (ship['owner_id'],))]
        if replace is not None:
            rows = [r for r in rows if r[0] != replace['layer_id']] + [
                (replace['layer_id'], replace['revision'], replace['snapshot'], replace['created'])]
        found = [binding_entry(lid, rev, snap, ship['owner_id'], signer, created) for lid, rev, snap, created in rows
                 if snap.get('kind') == 'instructions' and snap.get('charter') is not True
                 and ship['id'] in snap.get('audience_users', [])]
        return sorted(found, key=lambda l: (l['created'], l['layer_id']))

    def _binding_layers(self, db, ship_id, replace=None):
        """Spec A rule 1 as charter step 4 amends it ("Binding"): the charter pair first (C22), then the owner's own
        layers. Tickets, the ship route and every caps check read a ship's binding here."""
        ship = require(db.execute('SELECT * FROM users WHERE id=?', (ship_id,)).fetchone())
        if ship['kind'] != 'ship':
            return []
        pair = self._charter_pair(db, ship)
        return self._layers_for(db, [pair] if pair else []) + self._own_layers(db, ship, replace)

    def _check_instruction_caps(self, db, actor, key, snapshot, revision):
        if not snapshot['audience_users']:
            raise Problem(400, 'Choose at least one ship for these instructions')
        replace = {'layer_id': key, 'revision': revision, 'snapshot': snapshot, 'created': self.clock()}
        for ship_id in snapshot['audience_users']:
            row = db.execute('SELECT owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if not row or row['owner_id'] != actor:
                continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
            layers = self._binding_layers(db, ship_id, replace=replace)
```

In `peer/superyak_peer/layers.py`, replace

```python
                    self._check_instruction_caps(db, actor, key, snapshot)
```

with

```python
                    self._check_instruction_caps(db, actor, key, snapshot, row['resource_version'] + 1)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py tests/test_tickets.py tests/test_signatures.py`
Expected: `84 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/instructions.py peer/superyak_peer/layers.py peer/tests/test_instructions.py peer/tests/test_charter.py
git commit -m "Charter 4a: the charter binds its signer's ships and the residents first, in recorded order; the law converts in place (R14, R15)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. No charter pair: the charter reached only through its empty audience, so lost. In `peer/superyak_peer/instructions.py`, replace

   ```python
           pair = self._charter_pair(db, ship)
   ```

   with

   ```python
           pair = None
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_the_charter_binds_its_signers_ships_and_the_residents_first` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

2. The signer's own ships unbound (the signer's acceptance by signing, C17, forgotten). In `peer/superyak_peer/instructions.py`, replace

   ```python
           if active is not None and ship['owner_id'] in (None, active['owner_id']):
   ```

   with

   ```python
           if active is not None and ship['owner_id'] is None:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_binding_matches_an_independent_reading_of_the_rule` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

3. Another owner's ship bound without accepting. In `peer/superyak_peer/instructions.py`, replace

   ```python
           if active is not None and ship['owner_id'] in (None, active['owner_id']):
   ```

   with

   ```python
           if active is not None:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_the_charter_binds_its_signers_ships_and_the_residents_first` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

4. _layers_for re-sorting by created. In `peer/superyak_peer/instructions.py`, replace

   ```python
                   found.append(binding_entry(layer_id, revision, json.loads(row['snapshot']), row['owner_id'], row['signer'],
                                              row['created']))
           return found
   ```

   with

   ```python
                   found.append(binding_entry(layer_id, revision, json.loads(row['snapshot']), row['owner_id'], row['signer'],
                                              row['created']))
           return sorted(found, key=lambda l: (l['created'], l['layer_id']))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_a_ticket_renders_the_charter_block_first_in_the_recorded_order` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

5. The charter sorted among the owner's layers by creation, not first. In `peer/superyak_peer/instructions.py`, replace

   ```python
           return self._layers_for(db, [pair] if pair else []) + self._own_layers(db, ship, replace)
   ```

   with

   ```python
           return sorted(self._layers_for(db, [pair] if pair else []) + self._own_layers(db, ship, replace), key=lambda l: (l['created'], l['layer_id']))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_the_charter_binds_its_signers_ships_and_the_residents_first` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

6. The revision kept when its signing fails. In `peer/superyak_peer/layers.py`, replace

   ```python
               self._sign_revision(db, key, revision)  # spec A step 3, G2: an instructions revision is signed as it is written
   ```

   with

   ```python
               try:
                   self._sign_revision(db, key, revision)
               except ValueError:
                   pass
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_law_becomes_the_charter_in_place_in_one_transaction` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

---

### Task 8: The caps count the charter once, for every ship it binds (R16)

**Files:**
- Modify: `peer/superyak_peer/instructions.py` (`CAPS_REFUSAL`, `over_caps`, `_check_instruction_caps`, `_check_charter_caps`: about 25 lines)
- Modify: `peer/superyak_peer/layers.py` (`activate_layer`: the revision made active, then the charter caps, then the signature; 4 lines)
- Test: `peer/tests/test_charter.py` (about 55 lines)

**Interfaces:**
- Consumes: `_binding_layers` (Task 7); `render_blocks`, `MAX_LAYERS`, `MAX_BYTES`.
- Produces: `instructions.CAPS_REFUSAL = "{ship} would have more than 10 instruction layers or 48,000 bytes of them"`; `instructions.over_caps(layers) -> bool`; `Instructions._check_charter_caps(db, signer_id)`, run by `activate_layer` once the charter revision is written and active, before it is signed; test helper `full_ship(app, client, ship, count)`.

- [ ] **Step 1: Write the failing tests**

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def full_ship(app, client, ship, count):
    """count ordinary layers activated for ship, each a short rule: their layer JSON."""
    made = []
    for n in range(count):
        layer = new_layer(client, kind='instructions', title=f'{ship["name"]} rule {n}', body='short', audience_users=[ship['id']])
        assert activate(client, layer).status_code == 200, n
        made.append(layer)
    return made


def test_the_caps_count_the_charter_once_for_every_ship_it_binds(env):
    """Test 16 (R16, C23): converting a layer whose ship sits at exactly 10 layers succeeds, because the converted layer
    counts once; a ship bound by the charter and 9 own layers gets 409 for a tenth own layer; the signer's ship with 10
    own layers makes the charter's activation 409; each 409 names the ship. Catches reusing _check_instruction_caps
    (which refuses an empty audience), and counting a converted layer as both its old and its new revision."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    full_ship(app, clients[0], rio, 9)
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[rio['id']])
    assert activate(clients[0], law).status_code == 200  # rio-grande: 10 layers
    law = save(clients[0], law, charter=True, audience_users=[])
    assert sign(clients[0], law).status_code == 200  # still 10: the charter and 9
    rules = full_ship(app, clients[0], serenity, 9)
    tenth = new_layer(clients[0], kind='instructions', title='One more', body='short', audience_users=[serenity['id']])
    over = (409, 'Serenity would have more than 10 instruction layers or 48,000 bytes of them')
    assert refusal(activate(clients[0], tenth)) == over
    withdrawn = clients[0].post(f'/api/layers/{law["id"]}/withdraw').json()
    assert activate(clients[0], tenth).status_code == 200  # serenity: 10 own layers
    assert refusal(sign(clients[0], withdrawn)) == over
    assert revision_count(app, law['id']) == 2
    assert clients[0].post(f'/api/layers/{rules[0]["id"]}/withdraw').status_code == 200
    assert sign(clients[0], withdrawn).json()['revision'] == 4  # the withdrawal took number 3


def test_a_charter_too_large_for_a_resident_is_refused_naming_it(env):
    """R16, C23: a charter's activation checks the residents too, though the signer owns no ship: a body of 20,000
    three-byte characters renders past 48,000 bytes. Catches caps checked only for the signer's ships."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    store.create_station_ship('odo', 'Odo')
    heavy = new_layer(clients[0], kind='instructions', title='Station law', body='✓' * 20000, charter=True)
    assert refusal(sign(clients[0], heavy)) == (409, 'Odo would have more than 10 instruction layers or 48,000 bytes of them')
    light = save(clients[0], heavy, body='✓' * 15000)
    assert sign(clients[0], light).status_code == 200
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `2 failed, 17 passed`. The failures: test 16 (`'That ship would have…' != 'Serenity would have…'`: the 409 names no ship) and the resident test (`(200, None) == (409, 'Odo wo...ytes of them')`: no caps at a charter's activation).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/instructions.py`, replace

```python
MAX_LAYERS, MAX_BYTES = 10, 48000
```

with

```python
MAX_LAYERS, MAX_BYTES = 10, 48000
CAPS_REFUSAL = '{ship} would have more than 10 instruction layers or 48,000 bytes of them'  # R16: each 409 names the ship
```

In `peer/superyak_peer/instructions.py`, insert after

```python
def render_blocks(layers, station):
    return PREAMBLE + '\n\n' + '\n\n'.join(render_one(l, station) for l in layers) if layers else ''
```

this, leaving two blank lines between them:

```python
def over_caps(layers):
    """Spec A's caps (R16): more than MAX_LAYERS layers, or more than MAX_BYTES of their rendered blocks."""
    return len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES
```

In `peer/superyak_peer/instructions.py`, replace

```python
        for ship_id in snapshot['audience_users']:
            row = db.execute('SELECT owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if not row or row['owner_id'] != actor:
                continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
            layers = self._binding_layers(db, ship_id, replace=replace)
            if len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES:
                raise Problem(409, 'That ship would have more than 10 instruction layers or 48,000 bytes of them')
```

with

```python
        for ship_id in snapshot['audience_users']:
            row = db.execute('SELECT name, owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
            if not row or row['owner_id'] != actor:
                continue  # it does not bind a ship the activator does not own, so it cannot crowd that ship out
            if over_caps(self._binding_layers(db, ship_id, replace=replace)):  # its binding counts the charter (R16)
                raise Problem(409, CAPS_REFUSAL.format(ship=safe_line(row['name'])))

    def _check_charter_caps(self, db, signer_id):
        """C23 in 4a: a charter's activation changes the binding of every resident and of every ship its signer owns. Each
        is checked with the new revision already active, written in the activation's own transaction, so a 409 rolls
        the write back, and a converted layer counts once, as the charter pair."""
        for ship in db.execute("SELECT id, name FROM users WHERE kind='ship' AND (owner_id IS NULL OR owner_id=?) "
                               'ORDER BY name COLLATE NOCASE, id', (signer_id,)).fetchall():
            if over_caps(self._binding_layers(db, ship['id'])):
                raise Problem(409, CAPS_REFUSAL.format(ship=safe_line(ship['name'])))
```

In `peer/superyak_peer/layers.py`, replace

```python
            db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
            self._sign_revision(db, key, revision)  # spec A step 3, G2: an instructions revision is signed as it is written
            db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
            self.emit(db, 'layer.activated', key, revision, {'owner_id': actor, 'draft_version': version})
```

with

```python
            db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
            db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
            if snapshot.get('charter') is True:
                self._check_charter_caps(db, actor)  # C23, with the new revision active: a 409 rolls this write back
            self._sign_revision(db, key, revision)  # spec A step 3, G2: an instructions revision is signed as it is written
            self.emit(db, 'layer.activated', key, revision, {'owner_id': actor, 'draft_version': version})
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py`
Expected: `43 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/instructions.py peer/superyak_peer/layers.py peer/tests/test_charter.py
git commit -m "Charter 4a: the caps count the charter once for the residents and the signer's ships, and name the ship (R16, C23)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. _check_instruction_caps reused: 400 for the empty audience. In `peer/superyak_peer/layers.py`, replace

   ```python
                   self._check_charter_caps(db, actor)  # C23, with the new revision active: a 409 rolls this write back
   ```

   with

   ```python
                   self._check_instruction_caps(db, actor, key, snapshot, revision)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_caps_count_the_charter_once_for_every_ship_it_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

2. Own layers read at each active layer's latest ordinary revision, so a converted layer counts as both its old revision and the charter. In `peer/superyak_peer/instructions.py`, replace

   ```python
               'FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision=layer_revisions.revision '
   ```

   with

   ```python
               "FROM layers JOIN layer_revisions ON layers.id=layer_revisions.layer_id AND layers.active_revision IS NOT NULL AND layer_revisions.revision=(SELECT max(r.revision) FROM layer_revisions AS r WHERE r.layer_id=layers.id AND json_extract(r.snapshot, '$.charter') IS NOT 1) "
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_caps_count_the_charter_once_for_every_ship_it_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

3. The caps measured before the new revision is active, so they miss the charter. In `peer/superyak_peer/layers.py`, replace

   ```python
               db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
               db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
               if snapshot.get('charter') is True:
                   self._check_charter_caps(db, actor)  # C23, with the new revision active: a 409 rolls this write back
   ```

   with

   ```python
               if snapshot.get('charter') is True:
                   self._check_charter_caps(db, actor)
               db.execute('INSERT INTO layer_revisions VALUES(?,?,?,?,?)', (key, revision, version, encode(snapshot), self.clock()))
               db.execute('UPDATE layers SET active_revision=?,resource_version=? WHERE id=?', (revision, revision, key))
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_caps_count_the_charter_once_for_every_ship_it_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/layers.py`.

4. The residents left unchecked. In `peer/superyak_peer/instructions.py`, replace

   ```python
           for ship in db.execute("SELECT id, name FROM users WHERE kind='ship' AND (owner_id IS NULL OR owner_id=?) "
   ```

   with

   ```python
           for ship in db.execute("SELECT id, name FROM users WHERE kind='ship' AND owner_id=? "
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_charter_too_large_for_a_resident_is_refused_naming_it` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

5. The charter not counted against the 10 layers. In `peer/superyak_peer/instructions.py`, replace

   ```python
       return len(layers) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES
   ```

   with

   ```python
       return len([l for l in layers if not l['charter']]) > MAX_LAYERS or len(render_blocks(layers, 'x' * 12).encode()) > MAX_BYTES
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_caps_count_the_charter_once_for_every_ship_it_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

6. A 409 that does not name the ship. In `peer/superyak_peer/instructions.py`, replace

   ```python
   CAPS_REFUSAL = '{ship} would have more than 10 instruction layers or 48,000 bytes of them'
   ```

   with

   ```python
   CAPS_REFUSAL = 'That ship would have more than 10 instruction layers or 48,000 bytes of them'
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_caps_count_the_charter_once_for_every_ship_it_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

---

### Task 9: Bracketed headers that mark the charter, and the footer's ` · charter rN` (R17, R18)

**Files:**
- Modify: `peer/superyak_peer/instructions.py` (`bracketed`, `render_one`: about 10 lines)
- Modify: `peer/superyak_peer/tickets.py` (`_ticket_json`, about 5 lines)
- Test: `peer/tests/test_instructions.py` (two header strings; test 18, about 30 lines); `peer/tests/test_charter.py` (test 17, about 30 lines)

**Interfaces:**
- Consumes: `binding_entry`'s `charter` (Task 7); `Tickets._footer`; `_layers_for`.
- Produces: `instructions.bracketed(title) -> str`; `render_one` writes `[<title>]` and `charter revision <n>`; `_ticket_json`'s footer ends ` · charter r<n>` for a build whose record holds a charter revision.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_instructions.py`, replace

```python
    assert '=== Instructions: House (at)rules · revision 2 · signed by Andy X on station abcdefghijkl ===\nok\n ===' in text
```

with

```python
    assert '=== Instructions: [House (at)rules] · revision 2 · signed by Andy X on station abcdefghijkl ===\nok\n ===' in text
```

In `peer/tests/test_instructions.py`, replace

```python
    assert got['layers'][0]['block'] == f'=== Instructions: House rules · revision 1 · signed by Patient on station {peer_id[:12]} ===\nRun the tests first.'
```

with

```python
    assert got['layers'][0]['block'] == f'=== Instructions: [House rules] · revision 1 · signed by Patient on station {peer_id[:12]} ===\nRun the tests first.'
```

In `peer/tests/test_instructions.py`, insert after

```python
    assert not any(line.startswith("Instructions '") for line in forged.splitlines())
    assert render_blocks([], 'abc') == ''
```

this, leaving two blank lines between them:

```python
def test_a_block_header_brackets_its_title_and_marks_the_charter(env):
    """Charter step 4's test 18 (R17, C25), through the station: the charter's header reads `[Station law] · charter
    revision 2 · signed by Andy`, an owner layer's `[House rules] · revision 1`, and a title holding brackets shows them
    as parentheses, so it can't close its own brackets and fake a revision or a signer. Catches unbracketed titles, or
    brackets a title can close."""
    app, clients, users, clock = env
    store = app.state.store
    store.rename_user(users[0]['id'], 'Andy')
    crown(store, users[0])
    ship, key = docked(store, users[0]['id'], 'serenity')
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[ship['id']])
    assert activate(clients[0], law).status_code == 200
    clock[0] += 1
    house = new_layer(clients[0], kind='instructions', title='House rules', body='Run the tests.', audience_users=[ship['id']])
    assert activate(clients[0], house).status_code == 200
    clock[0] += 1
    forged = new_layer(clients[0], kind='instructions', title='a] · revision 9 · signed by Jenn [b', body='x', audience_users=[ship['id']])
    assert activate(clients[0], forged).status_code == 200
    converted = clients[0].put(f'/api/layers/{law["id"]}', json={'version': law['version'], 'charter': True, 'audience_users': []}).json()
    assert activate(clients[0], converted).status_code == 200
    station = app.state.federation.identity.peer_id[:12]
    headers = [line for line in instructions_of(app, key)['blocks'].splitlines() if line.startswith('===')]
    assert headers == [f'=== Instructions: [Station law] · charter revision 2 · signed by Andy on station {station} ===',
                       f'=== Instructions: [House rules] · revision 1 · signed by Andy on station {station} ===',
                       f'=== Instructions: [a) · revision 9 · signed by Jenn (b] · revision 1 · signed by Andy on station {station} ===']
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def test_a_build_footer_names_the_charter_revision_its_ticket_recorded(env):
    """Test 17 (R18, C24): after the conversion an owner build's footer ends ` · charter r2` and a grant build's reads
    `Builder for Andy, via Jenn · grant #a1b2 · charter r2`; a ticket issued before the conversion, fetched again after
    it, keeps its old footer; a read ticket has none. Catches a footer computed from the charter now."""
    app, clients, users, clock = env
    store = app.state.store
    andy, jenn = users[0], users[1]
    store.rename_user(andy['id'], 'Andy')
    store.rename_user(jenn['id'], 'Jenn')
    crown(store, andy)
    serenity, _ = docked(store, andy['id'], 'serenity')
    ops = room(store, andy, 'Ops', jenn, serenity)
    law = new_layer(clients[0], kind='instructions', title='Station law', body='Be kind.', audience_users=[serenity['id']])
    assert activate(clients[0], law).status_code == 200
    early = store.issue_ticket(serenity['id'], mention(store, andy, ops, serenity)['id'])
    assert (early['footer'], early['instructions']) == ('Builder for Andy (owner)', [[law['id'], 1]])
    assert sign(clients[0], save(clients[0], law, charter=True, audience_users=[])).json()['revision'] == 2
    again = store.issue_ticket(serenity['id'], early['message_id'])  # still running: the same ticket
    assert (again['id'], again['footer']) == (early['id'], 'Builder for Andy (owner)')
    owner = store.issue_ticket(serenity['id'], mention(store, andy, ops, serenity)['id'])
    assert (owner['footer'], owner['instructions']) == ('Builder for Andy (owner) · charter r2', [[law['id'], 2]])
    grant = make(store, andy, jenn, [serenity], hours=48)
    granted = store.issue_ticket(serenity['id'], mention(store, jenn, ops, serenity)['id'])
    assert granted['footer'] == f'Builder for Andy, via Jenn · grant #{grant[:4]} · charter r2'
    read = store.issue_ticket(serenity['id'], store.send_message(andy['id'], ops, uid(), 'Just talking')['id'])
    assert (read['mode'], read['footer'], read['instructions']) == ('read', '', [[law['id'], 2]])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py`
Expected: `4 failed, 41 passed`. The failures: test 17 (`'Builder for Andy (owner)' != 'Builder for Andy (owner) · charter r2'`), test 18 and the two updated header strings (`=== Instructions: Station law · revision 2 …` without brackets).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/instructions.py`, replace

```python
def render_one(layer, station):
    return (f'=== Instructions: {safe_line(layer["title"], 200)} · revision {layer["revision"]} · signed by '
            f'{safe_line(layer["signer_name"])} on station {str(station)[:12]} ===\n{defuse_body(layer["body"])}')
```

with

```python
def bracketed(title):
    """C25: a title in brackets on one safe line, with `[` and `]` inside it shown as `(` and `)`, so a title can't
    close its brackets and fake a header's revision or signer."""
    return '[' + safe_line(title, 200).replace('[', '(').replace(']', ')') + ']'


def render_one(layer, station):
    revision = ('charter revision' if layer.get('charter') else 'revision') + f' {layer["revision"]}'  # R17
    return (f'=== Instructions: {bracketed(layer["title"])} · {revision} · signed by '
            f'{safe_line(layer["signer_name"])} on station {str(station)[:12]} ===\n{defuse_body(layer["body"])}')
```

In `peer/superyak_peer/tickets.py`, replace

```python
        root_name = safe_line(root['name']) if root else None
        footer = self._footer(db, row, root_name)
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
                'hops': row['hops'], 'instructions': json.loads(row['instructions']),
                'blocks': render_blocks(self._layers_for(db, json.loads(row['instructions'])), station), 'footer': footer,
```

with

```python
        root_name = safe_line(root['name']) if root else None
        layers = self._layers_for(db, json.loads(row['instructions']))
        footer = self._footer(db, row, root_name)
        charter = next((layer for layer in layers if layer['charter']), None)
        if footer and charter is not None:  # R18, C24: from the ticket's record, so a footer never changes after its run
            footer += f' · charter r{charter["revision"]}'
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
                'hops': row['hops'], 'instructions': json.loads(row['instructions']),
                'blocks': render_blocks(layers, station), 'footer': footer,
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py tests/test_tickets.py tests/test_grant_tickets.py tests/test_ship_agent.py`
Expected: `101 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/instructions.py peer/superyak_peer/tickets.py peer/tests/test_instructions.py peer/tests/test_charter.py
git commit -m "Charter 4a: block headers bracket titles and mark the charter; a build footer names the charter revision it recorded (R17, R18)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. An unbracketed title. In `peer/superyak_peer/instructions.py`, replace

   ```python
       return (f'=== Instructions: {bracketed(layer["title"])} · {revision} · signed by '
   ```

   with

   ```python
       return (f'=== Instructions: {safe_line(layer["title"], 200)} · {revision} · signed by '
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_a_block_header_brackets_its_title_and_marks_the_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

2. Brackets a title can close. In `peer/superyak_peer/instructions.py`, replace

   ```python
       return '[' + safe_line(title, 200).replace('[', '(').replace(']', ')') + ']'
   ```

   with

   ```python
       return '[' + safe_line(title, 200) + ']'
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_a_block_header_brackets_its_title_and_marks_the_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

3. The charter not marked. In `peer/superyak_peer/instructions.py`, replace

   ```python
       revision = ('charter revision' if layer.get('charter') else 'revision') + f' {layer["revision"]}'  # R17
   ```

   with

   ```python
       revision = f'revision {layer["revision"]}'
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_instructions.py::test_a_block_header_brackets_its_title_and_marks_the_charter` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

4. A footer computed from the charter now: the early ticket gains ` · charter r2`. In `peer/superyak_peer/tickets.py`, replace

   ```python
           charter = next((layer for layer in layers if layer['charter']), None)
   ```

   with

   ```python
           active = self._active_charter(db)
           charter = {'revision': active['active_revision']} if active else None
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_build_footer_names_the_charter_revision_its_ticket_recorded` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/tickets.py`.

5. A read ticket given a footer. In `peer/superyak_peer/tickets.py`, replace

   ```python
           if footer and charter is not None:
   ```

   with

   ```python
           if charter is not None:
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_build_footer_names_the_charter_revision_its_ticket_recorded` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/tickets.py`.

---

### Task 10: Every person reads the active charter revision's signed record (R19)

**Files:**
- Modify: `peer/superyak_peer/signatures.py` (`revision_signed`, `_may_read_charter_revision`: about 18 lines)
- Test: `peer/tests/test_charter.py` (about 40 lines)

**Interfaces:**
- Consumes: A charter revision's snapshot (`charter: true`, Task 3).
- Produces: `Signatures.revision_signed(actor, layer_id, revision)`: the owner reads every revision; anyone else a charter revision that `Signatures._may_read_charter_revision(db, actor, layer, revision) -> bool` allows (in 4a, the layer's active revision); the same 404 for everything else.

- [ ] **Step 1: Write the failing tests**

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer(env):
    """Test 19 (R19, C26): every signed-in person reads the active charter revision's signed record, even one who owns
    nothing; after a new revision the signer still reads the past one, while a participant gets 404 for it, the same
    answer as for a revision that doesn't exist; an ordinary revision stays its owner's; a ship key gets 403. Catches
    opening every past revision, or the active one to no one."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    ship, key = docked(store, users[0]['id'], 'serenity')
    law = new_layer(clients[0], **RULES, charter=True)
    assert sign(clients[0], law).status_code == 200
    law = save(clients[0], law, body='Be kinder.')
    assert sign(clients[0], law).json()['revision'] == 2

    def path(revision):
        return f'/api/layers/{law["id"]}/revisions/{revision}/signed'
    card = card_of(store._station_identity())
    for client in (clients[1], clients[2], clients[3]):  # a participant, an admin, a participant: none owns anything
        got = client.get(path(2))
        assert got.status_code == 200, got.text
        assert got.json()['record']['policy'] == DEFAULT_POLICY and verify_record(card, got.json()['record'], got.json()['signature'])
    law = save(clients[0], law, body='Be kinder still.')
    assert sign(clients[0], law).json()['revision'] == 3
    assert clients[0].get(path(2)).status_code == 200 and clients[0].get(path(1)).status_code == 200  # the signer's
    for client, revision in ((clients[1], 2), (clients[1], 1), (clients[1], 9), (clients[2], 2), (clients[1], 0)):
        assert refusal(client.get(path(revision))) == (404, 'Not found'), revision
    assert clients[1].get(path(3)).status_code == 200
    assert refusal(clients[1].get('/api/layers/no-such-layer/revisions/1/signed')) == (404, 'Not found')
    ordinary = new_layer(clients[0], **RULES, audience_users=[ship['id']])
    assert sign(clients[0], ordinary).status_code == 200
    assert refusal(clients[1].get(f'/api/layers/{ordinary["id"]}/revisions/1/signed')) == (404, 'Not found')
    assert clients[0].get(f'/api/layers/{ordinary["id"]}/revisions/1/signed').status_code == 200
    assert refusal(ship_client(app, key).get(path(3))) == (403, 'Ship keys cannot use this route')
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    assert refusal(clients[1].get(path(3))) == (404, 'Not found')  # withdrawn: no longer the active charter
    assert clients[0].get(path(3)).status_code == 200
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py`
Expected: `1 failed, 20 passed`. The failure: test 19 (`404 == 200`: a participant who owns nothing can't read the active charter).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/signatures.py`, replace

```python
    def revision_signed(self, actor, layer_id, revision):
        """G6: {station, record, signature} for the layer's owner. Anyone else, and any revision without a signature
        (a note's, or one that doesn't exist), gets 404, so the route never says whether a layer exists."""
        with self.transaction() as db:
            self._owned_layer(db, actor, layer_id)
            if not 1 <= revision <= 2 ** 63 - 1:  # past SQLite's integers sqlite3 raises OverflowError; no such revision
                raise Problem(404, 'Not found')
            row = require(db.execute('SELECT signature FROM revision_signatures WHERE layer_id=? AND revision=?',
                                     (layer_id, revision)).fetchone())
```

with

```python
    def revision_signed(self, actor, layer_id, revision):
        """G6 as charter step 4 amends it (C26): {station, record, signature} for the layer's owner, and for a charter
        revision whoever _may_read_charter_revision lets read it. Anyone else, and any revision without a signature (a
        note's, or one that doesn't exist), gets the same 404, so the route never says whether a layer or a revision
        exists."""
        with self.transaction() as db:
            layer = db.execute('SELECT * FROM layers WHERE id=?', (layer_id,)).fetchone()
            if layer is None or not 1 <= revision <= 2 ** 63 - 1:  # past SQLite's integers sqlite3 raises OverflowError
                raise Problem(404, 'Not found')
            row = require(db.execute('SELECT signature FROM revision_signatures WHERE layer_id=? AND revision=?',
                                     (layer_id, revision)).fetchone())
            charter = db.execute("SELECT 1 FROM layer_revisions WHERE layer_id=? AND revision=? AND "
                                 "json_extract(snapshot, '$.charter')=1", (layer_id, revision)).fetchone()
            if layer['owner_id'] != actor and (charter is None or not self._may_read_charter_revision(db, actor, layer, revision)):
                raise Problem(404, 'Not found')
```

In `peer/superyak_peer/signatures.py`, insert after

```python
            return {'station': self._station_identity(db).peer_id, 'record': self._revision_record(db, layer_id, revision),
                    'signature': row['signature']}
```

this, leaving one blank line between them:

```python
    def _may_read_charter_revision(self, db, actor, layer, revision):
        """C26 in 4a: a person who doesn't own the layer reads a charter revision only while it is the layer's active
        revision, which makes it the active charter; merge 4c adds the people whose acceptance names it."""
        return layer['active_revision'] == revision
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_signatures.py`
Expected: `49 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/signatures.py peer/tests/test_charter.py
git commit -m "Charter 4a: every person reads the active charter revision's signed record; past ones stay the signer's (R19, C26)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Every revision of the active charter's layer opened. In `peer/superyak_peer/signatures.py`, replace

   ```python
           return layer['active_revision'] == revision
   ```

   with

   ```python
           return layer['active_revision'] is not None
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/signatures.py`.

2. The active charter revision to no one but its signer. In `peer/superyak_peer/signatures.py`, replace

   ```python
           return layer['active_revision'] == revision
   ```

   with

   ```python
           return False
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/signatures.py`.

3. Every charter revision, withdrawn or past, opened to everyone. In `peer/superyak_peer/signatures.py`, replace

   ```python
           return layer['active_revision'] == revision
   ```

   with

   ```python
           return True
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/signatures.py`.

4. An ordinary layer's active revision opened to everyone. In `peer/superyak_peer/signatures.py`, replace

   ```python
               if layer['owner_id'] != actor and (charter is None or not self._may_read_charter_revision(db, actor, layer, revision)):
   ```

   with

   ```python
               if layer['owner_id'] != actor and not self._may_read_charter_revision(db, actor, layer, revision):
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/signatures.py`.

---

### Task 11: The ship routes: the `charter` field, and ships drafting a charter (R20, R21, station side)

**Files:**
- Modify: `peer/superyak_peer/instructions.py` (`ship_instructions`, `_charter_status`, `ship_draft`: about 25 lines)
- Test: `peer/tests/test_instructions.py` (one answer gains `charter: None`); `peer/tests/test_charter.py` (about 65 lines)

**Interfaces:**
- Consumes: `_binding_layers`, `_charter_pair`, `binding_entry`'s `charter` (Task 7); `_active_charter` (Task 3); `check_draft` (Task 2).
- Produces: `Instructions._charter_status(db, ship) -> dict | None`; `GET /api/ships/me/instructions`: `layers[].charter`, and `charter: null | {layer_id, revision, binding, accepted}`; `POST /api/ships/me/drafts` takes `title`, `body`, `charter`, `policy`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_instructions.py`, replace

```python
    assert instructions_of(app, docked(app.state.store, users[1]['id'], 'defiant')[1]) == {'instructions': [], 'layers': [], 'blocks': ''}
```

with

```python
    assert instructions_of(app, docked(app.state.store, users[1]['id'], 'defiant')[1]) == {'instructions': [], 'layers': [], 'blocks': '',
                                                                                          'charter': None}
```

In `peer/tests/test_charter.py`, replace

```python
from test_instructions import OLD_FIELDS, activate, binding, crown, docked, new_layer, ship_client, stored
```

with

```python
from test_instructions import OLD_FIELDS, activate, binding, crown, docked, instructions_of, new_layer, ship_client, stored
```

Append to the end of `peer/tests/test_charter.py`, leaving two blank lines after the current last line:

```python
def test_the_ship_route_marks_the_charter_and_says_which_revision_binds(env):
    """Test 20's station part (R20, "Routes"): each layer carries `charter`, and the answer's `charter` is null with
    none active, else {layer_id, revision, binding, accepted}: the active revision, the one binding this ship (or null),
    and whether its owner signed it (always true for a resident). Catches a field that says the active revision binds
    a ship it doesn't bind."""
    app, clients, users, clock = env
    store = app.state.store
    crown(store, users[0])
    serenity, key = docked(store, users[0]['id'], 'serenity')
    defiant, other_key = docked(store, users[1]['id'], 'defiant')
    odo_key = store.issue_ship_key(store.create_station_ship('odo', 'Odo')['id'])
    house = new_layer(clients[0], kind='instructions', title='House rules', body='Run the tests.', audience_users=[serenity['id']])
    assert activate(clients[0], house).status_code == 200
    got = instructions_of(app, key)
    assert got['charter'] is None and [l['charter'] for l in got['layers']] == [False]
    law = new_layer(clients[0], **RULES, charter=True)
    assert sign(clients[0], law).status_code == 200
    got = instructions_of(app, key)
    assert [(l['layer_id'], l['charter']) for l in got['layers']] == [(law['id'], True), (house['id'], False)]
    assert got['charter'] == {'layer_id': law['id'], 'revision': 1, 'binding': 1, 'accepted': True}
    assert instructions_of(app, odo_key)['charter'] == {'layer_id': law['id'], 'revision': 1, 'binding': 1, 'accepted': True}
    assert instructions_of(app, other_key) == {'instructions': [], 'layers': [], 'blocks': '', 'charter': {
        'layer_id': law['id'], 'revision': 1, 'binding': None, 'accepted': False}}
    assert clients[0].post(f'/api/layers/{law["id"]}/withdraw').status_code == 200
    assert [instructions_of(app, k)['charter'] for k in (key, odo_key, other_key)] == [None, None, None]


def test_a_ship_drafts_a_charter_with_a_policy_and_no_audience(env):
    """Test 21's station part (R21, C28): a ship's charter draft has `charter: true`, the policy as written, no
    audience and `drafted_by`; any other key, a policy without a charter and a bad policy get 400; an ordinary draft is
    addressed to the ship as before; a participant owner holds the charter draft but can't sign it. Catches a charter
    draft addressed to the drafting ship."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[1]['id'], 'serenity')  # doctor, a participant, owns it
    serenity = ship_client(app, key)
    policy = {'version': 1, 'delegation': {'max_depth': 2}}
    drafted = serenity.post('/api/ships/me/drafts', json={'title': 'Station charter', 'body': 'Be kind.', 'charter': True,
                                                          'policy': policy})
    assert drafted.status_code == 201, drafted.text
    assert drafted.json() == {'id': drafted.json()['id'], 'title': 'Station charter', 'version': 1, 'state': 'draft',
                              'drafted_by': ship['id']}
    owners = clients[1].get(f'/api/layers/{drafted.json()["id"]}').json()
    assert (owners['charter'], owners['policy'], owners['audience_users'], owners['drafted_by']) == (True, policy, [], ship['id'])
    for body, answer in (
            ({'title': 'T', 'body': 'B', 'charter': True, 'audience_users': [ship['id']]},
             (400, 'A ship draft takes only a title, a body, charter and policy')),
            ({'title': 'T', 'body': 'B', 'policy': policy}, (400, 'A policy belongs only on a charter')),
            ({'title': 'T', 'body': 'B', 'charter': 'yes'}, (400, 'charter is true or false')),
            ({'title': 'T', 'body': 'B', 'charter': True, 'policy': {'version': 1, 'roots': []}},
             (400, 'policy.roots is reserved for step 5'))):
        assert refusal(serenity.post('/api/ships/me/drafts', json=body)) == answer, body
    plain = serenity.post('/api/ships/me/drafts', json={'title': 'Rules', 'body': 'x', 'charter': False}).json()
    assert stored(app, plain['id'])['audience_users'] == [ship['id']] and 'charter' not in stored(app, plain['id'])
    assert refusal(activate(clients[1], owners)) == (403, "Only a super admin can sign the station's charter")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py`
Expected: `3 failed, 45 passed`. The failures: the route test (`KeyError: 'charter'`), the draft test (`400 == 201`: "A ship draft takes only a title and a body") and `test_a_ship_reads_its_binding_instructions_with_each_block` (the answer lacks `charter`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/instructions.py`, replace

```python
    def ship_instructions(self, actor, station):
        with self.transaction() as db:
            layers = self._binding_layers(db, actor)
        return {'instructions': [[l['layer_id'], l['revision']] for l in layers],
                'layers': [{'layer_id': l['layer_id'], 'revision': l['revision'], 'title': safe_line(l['title'], 200),
                            'signer_name': safe_line(l['signer_name']), 'block': render_one(l, station)} for l in layers],
                'blocks': render_blocks(layers, station)}

    def ship_draft(self, actor, data):
        """A ship drafts an instructions layer in its owner's name, addressed to itself. Only the owner can activate it."""
        if set(data) - {'title', 'body'}:
            raise Problem(400, 'A ship draft takes only a title and a body')
```

with

```python
    def ship_instructions(self, actor, station):
        """GET /api/ships/me/instructions. Charter step 4 (R20): each layer says whether it is the charter, and `charter`
        is null while none is active, else the active revision, the revision binding this ship (or null) and whether
        the ship's owner signed it, always true for a resident (merge 4c: or accepted it)."""
        with self.transaction() as db:
            layers = self._binding_layers(db, actor)
            charter = self._charter_status(db, require(db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()))
        return {'instructions': [[l['layer_id'], l['revision']] for l in layers],
                'layers': [{'layer_id': l['layer_id'], 'revision': l['revision'], 'title': safe_line(l['title'], 200),
                            'signer_name': safe_line(l['signer_name']), 'charter': l['charter'],
                            'block': render_one(l, station)} for l in layers],
                'blocks': render_blocks(layers, station), 'charter': charter}

    def _charter_status(self, db, ship):
        """R20: the ship route's `charter`, null while no charter is active, else {layer_id, revision, binding, accepted}:
        the active revision, the revision binding this ship (or null), and whether its owner signed it, always true for
        a resident; merge 4c adds the owners who accepted it."""
        active = self._active_charter(db)
        if active is None:
            return None
        pair = self._charter_pair(db, ship)
        return {'layer_id': active['id'], 'revision': active['active_revision'], 'binding': pair[1] if pair else None,
                'accepted': ship['owner_id'] in (None, active['owner_id'])}

    def ship_draft(self, actor, data):
        """A ship drafts an instructions layer in its owner's name, addressed to itself, or a charter, addressed to no
        ship (C28). Only the owner can activate it, and only a super admin can sign a charter."""
        if set(data) - {'title', 'body', 'charter', 'policy'}:
            raise Problem(400, 'A ship draft takes only a title, a body, charter and policy')
```

In `peer/superyak_peer/instructions.py`, replace

```python
            draft = self._draft(db, owner, {'kind': 'instructions', 'title': data.get('title', 'Untitled'),
                                            'body': data.get('body', ''), 'audience_users': [actor]})
```

with

```python
            fields = {'kind': 'instructions', 'title': data.get('title', 'Untitled'), 'body': data.get('body', ''),
                      'audience_users': [] if data.get('charter') is True else [actor]}
            draft = self._draft(db, owner, {**fields, **{key: data[key] for key in ('charter', 'policy') if key in data}})
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py tests/test_instructions.py tests/test_ship_agent.py`
Expected: `72 passed`.

- [ ] **Step 5: Commit**

```bash
git add peer/superyak_peer/instructions.py peer/tests/test_instructions.py peer/tests/test_charter.py
git commit -m "Charter 4a: the ship route marks the charter and says which revision binds; ships draft charters (R20, R21)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Layers without `charter`. In `peer/superyak_peer/instructions.py`, replace

   ```python
                               'signer_name': safe_line(l['signer_name']), 'charter': l['charter'],
   ```

   with

   ```python
                               'signer_name': safe_line(l['signer_name']),
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_ship_route_marks_the_charter_and_says_which_revision_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

2. The active revision said to bind another owner's ship. In `peer/superyak_peer/instructions.py`, replace

   ```python
           return {'layer_id': active['id'], 'revision': active['active_revision'], 'binding': pair[1] if pair else None,
                   'accepted': ship['owner_id'] in (None, active['owner_id'])}
   ```

   with

   ```python
           return {'layer_id': active['id'], 'revision': active['active_revision'], 'binding': active['active_revision'],
                   'accepted': True}
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_the_ship_route_marks_the_charter_and_says_which_revision_binds` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

3. A charter draft addressed to the drafting ship (400). In `peer/superyak_peer/instructions.py`, replace

   ```python
                         'audience_users': [] if data.get('charter') is True else [actor]}
   ```

   with

   ```python
                         'audience_users': [actor]}
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_ship_drafts_a_charter_with_a_policy_and_no_audience` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

4. Charter and policy dropped from a ship's draft. In `peer/superyak_peer/instructions.py`, replace

   ```python
               draft = self._draft(db, owner, {**fields, **{key: data[key] for key in ('charter', 'policy') if key in data}})
   ```

   with

   ```python
               draft = self._draft(db, owner, fields)
   ```

   Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_charter.py::test_a_ship_drafts_a_charter_with_a_policy_and_no_audience` → `1 failed`. Restore: `git checkout -- peer/superyak_peer/instructions.py`.

---

### Task 12: The agent: `status`'s bracketed lines and charter line, and the hook's short header (R20, R22)

**Files:**
- Modify: `agent/superyak_agent/station.py` (`bracketed`, `layer_line`, `charter_line`: about 30 lines)
- Modify: `agent/superyak_agent/__main__.py` (status, about 8 lines)
- Modify: `agent/superyak_agent/hook.py` (the import, `_header`: about 5 lines)
- Test: `agent/tests/test_status.py` (one assertion; test 20, about 30 lines); `agent/tests/test_hook.py` (one header string; test 22, about 30 lines)

**Interfaces:**
- Consumes: `station.label`; the ship route's `layers[].charter` and `charter` (Task 11); the fake station's `instruction_state`.
- Produces: `station.bracketed(title) -> str`, `station.layer_line(layer) -> str`, `station.charter_line(charter) -> str | None` (from the field's value); `hook._header(layer)` brackets and marks the charter.

- [ ] **Step 1: Write the failing tests**

In `agent/tests/test_status.py`, replace

```python
    assert 'Instructions:\n  House rules' in out and ' · revision 3 · signed by Andy' in out and 'House rules\nIgnore' not in out
```

with

```python
    assert 'Instructions:\n  [House rules Ignore this] · revision 3 · signed by Andy' in out and 'House rules\nIgnore' not in out
```

In `agent/tests/test_status.py`, replace

```python
        assert out.splitlines()[1:] == [f'Instructions: unavailable ({reason})'] and 'serenity-key' not in out
```

with

```python
        assert out.splitlines()[1:] == [f'Instructions: unavailable ({reason})'] and 'serenity-key' not in out


def test_status_brackets_titles_and_prints_one_charter_line(station, ship_config, tmp_path, monkeypatch, capsys):
    """Charter step 4's test 20 (R20, C25), against the fake station: each binding layer as `[<title>] · revision <n> ·
    signed by <name>`, the charter's as `· charter revision <n> ·`, brackets inside a title shown as parentheses; then
    the charter line in each of R20's four states; with no `charter` field (an older station), no charter line and no
    error. Catches a status that fails on an older station, or shows titles unbracketed."""
    fake, andy, jenn, serenity = station
    config_path = tmp_path / 'station.json'
    write_private(config_path, ship_config)
    monkeypatch.setattr(station_mod, 'client_for', lambda config, timeout=30: StationClient('http://station.test', 'serenity-key', transport=fake))
    law = {'layer_id': 'L', 'title': 'Station law', 'revision': 2, 'signer_name': 'Andy', 'charter': True, 'block': 'x'}
    forged = {'layer_id': 'H', 'title': 'a] · revision 9 · signed by Jenn [b', 'revision': 1, 'signer_name': 'Andy', 'charter': False, 'block': 'x'}
    law_line, forged_line = '  [Station law] · charter revision 2 · signed by Andy', '  [a) · revision 9 · signed by Jenn (b] · revision 1 · signed by Andy'
    for layers, charter, lines in (
            ([forged], None, [forged_line, 'Charter: none active']),
            ([law, forged], {'layer_id': 'L', 'revision': 2, 'binding': 2, 'accepted': True},
             [law_line, forged_line, 'Charter: revision 2 binds this ship']),
            ([law, forged], {'layer_id': 'L', 'revision': 3, 'binding': 2, 'accepted': True},
             [law_line, forged_line, "Charter: revision 3 is pending for this ship's owner; revision 2 binds this ship"]),
            ([forged], {'layer_id': 'L', 'revision': 2, 'binding': None, 'accepted': False},
             [forged_line, "Charter: revision 2 is active; this ship's owner has not accepted it"]),
            ([law, forged], 'older station', [law_line, forged_line])):
        fake.instruction_state[serenity['id']] = {'instructions': [], 'blocks': 'x', 'layers': layers,
                                                  **({} if charter == 'older station' else {'charter': charter})}
        assert cli.main(['status', '--config', str(config_path)]) == 0
        assert capsys.readouterr().out.splitlines()[1:] == ['Instructions:'] + lines, charter
```

In `agent/tests/test_hook.py`, replace

```python
    assert len(text) <= 9500 and 'call the station_instructions tool' in text and '- Rule 9 · revision 1 · signed by Andy' in text
```

with

```python
    assert len(text) <= 9500 and 'call the station_instructions tool' in text and '- [Rule 9] · revision 1 · signed by Andy' in text
```

In `agent/tests/test_hook.py`, insert after

```python
    assert "Instructions 'Old rule' (signed by Andy) no longer apply to this ship." in text
    assert prompt(fake, config_path, 's1', sessions) == ''
```

this, leaving two blank lines between them:

```python
def test_the_conversion_reaches_a_session_as_a_changed_charter_block(station, ship_config, tmp_path):
    """Charter step 4's test 22 (R22, C7, C25), against the fake station: a session that saw (L, 1) sees (L, 2) as a
    charter: the notice is the changed preamble and the full new block, with no "no longer apply" line; when it doesn't
    fit, _header shows `[title] · charter revision 2`. Catches a spurious withdrawal line, or an unbracketed header."""
    fake, andy, jenn, serenity, config_path = setup(station, ship_config, tmp_path)
    sessions = tmp_path / 'sessions'
    law(fake, serenity, [('L', 1, 'Station law', 'Be kind.')])
    start(fake, config_path, 's1', sessions)
    start(fake, config_path, 's2', sessions)

    def converted(body):
        block = f'=== Instructions: [Station law] · charter revision 2 · signed by Andy on station abc ===\n{body}'
        fake.instruction_state[serenity['id']] = {
            'instructions': [['L', 2]], 'blocks': 'PREAMBLE\n\n' + block,
            'layers': [{'layer_id': 'L', 'revision': 2, 'title': 'Station law', 'signer_name': 'Andy', 'charter': True, 'block': block}],
            'charter': {'layer_id': 'L', 'revision': 2, 'binding': 2, 'accepted': True}}
        return block
    block = converted('Be kind, always.')
    text = prompt(fake, config_path, 's1', sessions)
    assert text == hook.CHANGE_PREAMBLE + '\n\n' + block and 'no longer apply' not in text
    converted('x' * 9600)
    text = prompt(fake, config_path, 's2', sessions)
    assert text == '\n'.join([hook.CHANGE_PREAMBLE, '- [Station law] · charter revision 2 · signed by Andy', hook.POINTER])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py tests/test_hook.py`
Expected: `4 failed, 103 passed`. The failures: both status tests (titles unbracketed, no charter line), test 22 at its short header (`- Station law · revision 2 · signed by Andy`) and `test_too_much_law_for_a_hook_points_at_the_tool` (`- [Rule 9]`).

- [ ] **Step 3: Write the implementation**

In `agent/superyak_agent/station.py`, insert after

```python
    text = ''.join(c if c.isprintable() else ' ' for c in text).replace('`', '')
    return ' '.join(text.split())[:limit].strip() or 'unknown'
```

this, leaving two blank lines between them:

```python
def bracketed(title):
    """C25: a layer's title in brackets, with `[` and `]` inside it shown as `(` and `)`, as the station's block headers
    write it, so a title can't close its brackets and fake a revision or a signer."""
    return '[' + str(title).replace('[', '(').replace(']', ')') + ']'


def layer_line(layer):
    """A binding layer on one line, as `status` prints it (R20): `[<title>] · revision <n> · signed by <name>`, with
    `charter revision` for the station's charter."""
    kind = 'charter revision' if layer.get('charter') is True else 'revision'
    return f'{bracketed(label(layer.get("title")))} · {kind} {layer.get("revision")} · signed by {label(layer.get("signer_name"))}'


def charter_line(charter):
    """R20: `status`'s one charter line from the ship route's `charter` field (null: none active), or None for a value
    that isn't one. A station older than charter step 4 sends no field, and `status` then prints no line."""
    if charter is None:
        return 'Charter: none active'
    if not isinstance(charter, dict):
        return None
    revision, binding = charter.get('revision'), charter.get('binding')
    if binding == revision:
        return f'Charter: revision {revision} binds this ship'
    if binding is None:
        return f"Charter: revision {revision} is active; this ship's owner has not accepted it"
    return f"Charter: revision {revision} is pending for this ship's owner; revision {binding} binds this ship"
```

In `agent/superyak_agent/__main__.py`, replace

```python
        from .station import StationError, client_for, label
```

with

```python
        from .station import StationError, charter_line, client_for, label, layer_line
```

In `agent/superyak_agent/__main__.py`, replace

```python
            layers = client.instructions().get('layers') or []
            lines = ['Instructions:'] + [f'  {label(layer.get("title"))} · revision {layer.get("revision")} · signed by '
                                         f'{label(layer.get("signer_name"))}' for layer in layers] if layers else ['Instructions: none']
```

with

```python
            answer = client.instructions()
            layers = answer.get('layers') or []
            lines = ['Instructions:'] + [f'  {layer_line(layer)}' for layer in layers] if layers else ['Instructions: none']
            charter = charter_line(answer['charter']) if 'charter' in answer else None  # R20: none from an older station
            if charter:
                lines.append(charter)
```

In `agent/superyak_agent/hook.py`, replace

```python
StationClient, authors, breakout_count_lines, client_version,
```

with

```python
StationClient, authors, bracketed, breakout_count_lines, client_version,
```

In `agent/superyak_agent/hook.py`, replace

```python
def _header(layer):
    return f'- {layer["title"]} · revision {layer["revision"]} · signed by {layer["signer_name"]}'
```

with

```python
def _header(layer):
    """A layer's short header, when the blocks don't fit (R22): its title bracketed, and `charter revision` for the
    station's charter."""
    kind = 'charter revision' if layer.get('charter') is True else 'revision'
    return f'- {bracketed(layer["title"])} · {kind} {layer["revision"]} · signed by {layer["signer_name"]}'
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py tests/test_hook.py`
Expected: `107 passed`.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/station.py agent/superyak_agent/__main__.py agent/superyak_agent/hook.py agent/tests/test_status.py agent/tests/test_hook.py
git commit -m "Charter 4a: status brackets titles and prints one charter line; the hook's short header marks the charter (R20, R22)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Status titles unbracketed. In `agent/superyak_agent/station.py`, replace

   ```python
       return f'{bracketed(label(layer.get("title")))} · {kind} {layer.get("revision")} · signed by {label(layer.get("signer_name"))}'
   ```

   with

   ```python
       return f'{label(layer.get("title"))} · {kind} {layer.get("revision")} · signed by {label(layer.get("signer_name"))}'
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py::test_status_brackets_titles_and_prints_one_charter_line` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

2. Brackets a title can close. In `agent/superyak_agent/station.py`, replace

   ```python
       return '[' + str(title).replace('[', '(').replace(']', ')') + ']'
   ```

   with

   ```python
       return '[' + str(title) + ']'
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py::test_status_brackets_titles_and_prints_one_charter_line` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

3. The charter not marked in status. In `agent/superyak_agent/station.py`, replace

   ```python
       kind = 'charter revision' if layer.get('charter') is True else 'revision'
       return f'{bracketed
   ```

   with

   ```python
       kind = 'revision'
       return f'{bracketed
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py::test_status_brackets_titles_and_prints_one_charter_line` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

4. An older station's missing field read as null: it prints Charter: none active. In `agent/superyak_agent/__main__.py`, replace

   ```python
               charter = charter_line(answer['charter']) if 'charter' in answer else None  # R20: none from an older station
   ```

   with

   ```python
               charter = charter_line(answer.get('charter'))
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py::test_status_brackets_titles_and_prints_one_charter_line` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/__main__.py`.

5. An unaccepted charter said to bind the ship. In `agent/superyak_agent/station.py`, replace

   ```python
       if binding is None:
           return f"Charter: revision {revision} is active; this ship's owner has not accepted it"
   ```

   with

   ```python
       if binding is None:
           return f'Charter: revision {revision} binds this ship'
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_status.py::test_status_brackets_titles_and_prints_one_charter_line` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

6. The hook's short header unbracketed. In `agent/superyak_agent/hook.py`, replace

   ```python
       return f'- {bracketed(layer["title"])} · {kind} {layer["revision"]} · signed by {layer["signer_name"]}'
   ```

   with

   ```python
       return f'- {layer["title"]} · {kind} {layer["revision"]} · signed by {layer["signer_name"]}'
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_hook.py::test_the_conversion_reaches_a_session_as_a_changed_charter_block` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/hook.py`.

7. The hook's short header not marking the charter. In `agent/superyak_agent/hook.py`, replace

   ```python
       kind = 'charter revision' if layer.get('charter') is True else 'revision'
       return f'- {bracketed
   ```

   with

   ```python
       kind = 'revision'
       return f'- {bracketed
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_hook.py::test_the_conversion_reaches_a_session_as_a_changed_charter_block` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/hook.py`.

8. Layers known by (id, revision): the conversion reads as a withdrawal too, with a "no longer apply" line. In `agent/superyak_agent/hook.py`, replace

   ```python
       now_ids = {l['layer_id'] for l in layers}
   ```

   with

   ```python
       now_ids = {(l['layer_id'], l['revision']) for l in layers}
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_hook.py::test_the_conversion_reaches_a_session_as_a_changed_charter_block` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/hook.py`.

---

### Task 13: The agent's draft tool takes `charter` and `policy` (R21)

**Files:**
- Modify: `agent/superyak_agent/station.py` (`draft_instructions`, about 6 lines)
- Modify: `agent/superyak_agent/mcp.py` (`station_draft_instructions` and its schema: about 12 lines)
- Test: `agent/tests/conftest.py` (the fake station's drafts, 4 lines); `agent/tests/test_mcp.py` (about 25 lines)

**Interfaces:**
- Consumes: `POST /api/ships/me/drafts {title, body, charter?, policy?}` (Task 11); `StationError`.
- Produces: `StationClient.draft_instructions(title, body, charter=None, policy=None)`; the tool's `charter` (boolean) and `policy` (object) arguments; the fake station's `draft_bodies` and `old_drafts`.

- [ ] **Step 1: Write the failing tests**

In `agent/tests/conftest.py`, replace

```python
        self.blocks, self.instruction_state, self.drafts = {}, {}, []
```

with

```python
        self.blocks, self.instruction_state, self.drafts = {}, {}, []
        self.draft_bodies, self.old_drafts = [], False  # every draft's JSON; old_drafts: refuse charter and policy, as before step 4
```

In `agent/tests/conftest.py`, replace

```python
        if method == 'POST' and path == '/api/ships/me/drafts':
            payload = json.loads(data)
            self.drafts.append((payload['title'], payload['body']))
```

with

```python
        if method == 'POST' and path == '/api/ships/me/drafts':
            payload = json.loads(data)
            self.draft_bodies.append(payload)
            if self.old_drafts and set(payload) - {'title', 'body'}:
                return 400, b'{"error": "A ship draft takes only a title and a body"}'
            self.drafts.append((payload['title'], payload['body']))
```

In `agent/tests/test_mcp.py`, insert after

```python
    text = call(tools_for(fake), 'station_draft_instructions', title='Proposed', body='Write tests first.')['content'][0]['text']
    assert "Drafted 'Proposed'" in text and fake.drafts == [('Proposed', 'Write tests first.')]
```

this, leaving two blank lines between them:

```python
def test_drafting_a_charter_sends_charter_and_policy_and_an_older_stations_400_is_an_error(station):
    """Charter step 4's test 21, the tool (R21, C28): station_draft_instructions sends `charter` and `policy` when given
    and only then, so a plain draft is exactly as before; an older station's 400 comes back as an error result; the
    tool's schema offers both, and still requires only title and body. Catches a tool that drops them, or sends them
    empty with every draft, which an older station would refuse."""
    fake, andy, jenn, serenity = station
    tools = tools_for(fake)
    policy = {'version': 1, 'delegation': {'max_depth': 2}}
    drafted = call(tools, 'station_draft_instructions', title='Station charter', body='Be kind.', charter=True, policy=policy)
    assert drafted['isError'] is False
    assert drafted['content'][0]['text'] == ("Drafted the charter 'Station charter' (layer L9). It binds nothing until your owner, "
                                             "as a super admin, signs it in the station's web app.")
    assert call(tools, 'station_draft_instructions', title='Rules', body='x')['isError'] is False
    assert fake.draft_bodies == [{'title': 'Station charter', 'body': 'Be kind.', 'charter': True, 'policy': policy},
                                 {'title': 'Rules', 'body': 'x'}]
    fake.old_drafts = True
    refused = call(tools, 'station_draft_instructions', title='Station charter', body='Be kind.', charter=True)
    assert (refused['isError'], refused['content'][0]['text']) == (True, 'station error: 400: A ship draft takes only a title and a body')
    assert call(tools, 'station_draft_instructions', title='Rules', body='x')['isError'] is False
    listed = handle(tools, {'id': 1, 'method': 'tools/list'})['result']['tools']
    schema = next(tool for tool in listed if tool['name'] == 'station_draft_instructions')['inputSchema']
    assert set(schema['properties']) == {'title', 'body', 'charter', 'policy'} and schema['required'] == ['title', 'body']
    assert (schema['properties']['charter']['type'], schema['properties']['policy']['type']) == ('boolean', 'object')
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_mcp.py`
Expected: `1 failed, 56 passed`. The failure: the new test, whose charter draft reads as an ordinary one (`- Drafted the charter …` / `+ Drafted 'Station charter' …`).

- [ ] **Step 3: Write the implementation**

In `agent/superyak_agent/station.py`, replace

```python
    def draft_instructions(self, title, body):
        return self.request('POST', '/api/ships/me/drafts', {'title': title, 'body': body})
```

with

```python
    def draft_instructions(self, title, body, charter=None, policy=None):
        """POST /api/ships/me/drafts. `charter` and `policy` are sent only when given (charter step 4, R21), so a plain
        draft is exactly as before; an older station answers 400 to them, which reaches the tool as an error result."""
        payload = {'title': title, 'body': body}
        payload.update({key: value for key, value in (('charter', charter), ('policy', policy)) if value is not None})
        return self.request('POST', '/api/ships/me/drafts', payload)
```

In `agent/superyak_agent/mcp.py`, replace

```python
    def station_draft_instructions(self, args):
        drafted = self.client.draft_instructions(args['title'], args['body'])
        return (f"Drafted '{label(drafted['title'])}' (layer {drafted['id']}). "
                "Your owner can read, edit and activate it in the station's web app.")
```

with

```python
    def station_draft_instructions(self, args):
        drafted = self.client.draft_instructions(args['title'], args['body'], args.get('charter'), args.get('policy'))
        if args.get('charter') is True:  # charter step 4, C28: a charter draft names no ships
            return (f"Drafted the charter '{label(drafted['title'])}' (layer {drafted['id']}). It binds nothing until your "
                    "owner, as a super admin, signs it in the station's web app.")
        return (f"Drafted '{label(drafted['title'])}' (layer {drafted['id']}). "
                "Your owner can read, edit and activate it in the station's web app.")
```

In `agent/superyak_agent/mcp.py`, replace

```python
    ('station_draft_instructions', "Draft instructions for this ship. A draft binds nothing until your owner reads, edits and activates it in the station's web app.",
     {'title': {'type': 'string', 'description': 'One line, at most 200 characters'}, 'body': {'type': 'string'}}, ['title', 'body']),
```

with

```python
    ('station_draft_instructions', "Draft instructions for this ship, or, with charter true, the station's charter, which names "
     "no ships. A draft binds nothing until your owner reads, edits and activates it in the station's web app; only a super "
     "admin signs a charter.",
     {'title': {'type': 'string', 'description': 'One line, at most 200 characters'}, 'body': {'type': 'string'},
      'charter': {'type': 'boolean', 'description': "True for the station's charter instead of instructions for this ship"},
      'policy': {'type': 'object', 'description': "A charter's policy, version 1 (see the station's API.md, Charter); left out, "
                 'the defaults'}}, ['title', 'body']),
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_mcp.py tests/test_station.py`
Expected: `77 passed`.

- [ ] **Step 5: Commit**

```bash
git add agent/superyak_agent/station.py agent/superyak_agent/mcp.py agent/tests/conftest.py agent/tests/test_mcp.py
git commit -m "Charter 4a: the draft tool sends charter and policy; an older station's 400 is an error result (R21)"
```

- [ ] **Step 6: Check the tests bite**

After the commit, apply each mutation alone, run the one test named, see it fail, and restore the file with `git checkout -- <file>` before the next. Each was seen failing in the dry run.

1. Charter and policy dropped. In `agent/superyak_agent/station.py`, replace

   ```python
           payload.update({key: value for key, value in (('charter', charter), ('policy', policy)) if value is not None})
   ```

   with

   ```python
           pass
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_mcp.py::test_drafting_a_charter_sends_charter_and_policy_and_an_older_stations_400_is_an_error` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

2. Both sent with every draft, so an older station refuses plain drafts too. In `agent/superyak_agent/station.py`, replace

   ```python
           payload.update({key: value for key, value in (('charter', charter), ('policy', policy)) if value is not None})
   ```

   with

   ```python
           payload.update({'charter': charter, 'policy': policy})
   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_mcp.py::test_drafting_a_charter_sends_charter_and_policy_and_an_older_stations_400_is_an_error` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/station.py`.

3. The schema without `charter`. In `agent/superyak_agent/mcp.py`, replace

   ```python
         'charter': {'type': 'boolean', 'description': "True for the station's charter instead of instructions for this ship"},
   ```

   with

   ```python

   ```

   Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_mcp.py::test_drafting_a_charter_sends_charter_and_policy_and_an_older_stations_400_is_an_error` → `1 failed`. Restore: `git checkout -- agent/superyak_agent/mcp.py`.

---

### Task 14: The docs (R23), and the whole suites

**Files:**
- Modify: `peer/API.md` (the layer routes, Instruction layers, a new Charter section, Signed records, Grants, Run tickets: about 95 lines)
- Modify: `agent/README.md` (what binds a ship, the hook, status, drafting: about 15 lines)

**Interfaces:**
- Consumes: Everything above.
- Produces: peer/API.md and agent/README.md describe step 4 as built.

Docs only: no test can fail first. The whole suites are the check.

- [ ] **Step 1: Write the docs**

In `peer/API.md`, replace

```markdown
| GET `/api/layers/{id}/preview` | — | Owner-only saved draft, selected `files`, named `people`, `audience_details`, and `space_versions` |
```

with

```markdown
| GET `/api/layers/{id}/preview` | — | Owner-only saved draft, selected `files`, named `people`, `audience_details`, and `space_versions`; a charter draft adds `charter` (see Charter) |
```

In `peer/API.md`, replace

```markdown
| POST `/api/layers/{id}/activate` | `{version,space_versions?}` | Exact current draft activated; supplied space versions must still match |
| POST `/api/layers/{id}/revoke` | `{revision,public:false,user_ids:[],space_ids:[]}` | Narrowed active revision |
| POST `/api/layers/{id}/withdraw` | none | Draft with no active release |
```

with

```markdown
| POST `/api/layers/{id}/activate` | `{version,space_versions?,confirm_widenings?}` | Exact current draft activated; supplied space versions must still match; a charter's widened paths are confirmed (see Charter) |
| POST `/api/layers/{id}/revoke` | `{revision,public:false,user_ids:[],space_ids:[]}` | Narrowed active revision; 409 for a charter |
| POST `/api/layers/{id}/withdraw` | none, or `{confirm_widenings?}` | Draft with no active release; a charter confirms what widens back to the defaults |
```

In `peer/API.md`, replace

```markdown
| GET `/api/layers/{id}/revisions/{n}/signed` | — | `{station, record, signature}` for an instructions revision; owner only (see Signed records) |
```

with

```markdown
| GET `/api/layers/{id}/revisions/{n}/signed` | — | `{station, record, signature}` for an instructions revision; owner only, but every person reads the active charter revision's (see Signed records) |
```

In `peer/API.md`, replace

```markdown
Ed25519 key (see Signed records).
```

with

```markdown
Ed25519 key (see Signed records). A draft can also carry `charter` and `policy`, which make it the station's
charter (see Charter).
```

In `peer/API.md`, replace

```markdown
**Binding rule.** A ship is bound only by the active instruction layers of its owner whose audience lists
that ship. A resident (no owner) is bound by none. Caps: at most 10 layers and 48,000 bytes of rendered blocks
per ship; an activation that would exceed either returns 409.
```

with

```markdown
**Binding rule.** A ship is bound first by the station's charter, when one is active and the ship is a resident (no
owner) or its owner signed it (see Charter); then by the active instruction layers of its owner whose audience lists
that ship, by creation. A resident is bound by the charter alone. A ticket records the layers in this order and renders
them in it. Caps: at most 10 layers and 48,000 bytes of rendered blocks per ship, the charter counted once; an
activation that would exceed either returns 409 naming the ship.
```

In `peer/API.md`, replace

```markdown
**Block format.** Each layer renders as `=== Instructions: <title> · revision <n> · signed by <owner> on
station <first 12 characters of the station id> ===` followed by the body, all preceded by a fixed preamble
```

with

```markdown
**Block format.** Each layer renders as `=== Instructions: [<title>] · revision <n> · signed by <owner> on
station <first 12 characters of the station id> ===`, or `· charter revision <n> ·` for the charter, followed by the
body; `[` and `]` inside a title show as `(` and `)`, so a title can't close its brackets. All are preceded by a fixed preamble
```

In `peer/API.md`, replace

```markdown
`GET /api/ships/me/instructions` returns what binds the ship now, plus
```

with

```markdown
`GET /api/ships/me/instructions` returns what binds the ship now (each layer marked `charter`, and a `charter` field: see Charter), plus
```

In `peer/API.md`, replace

```markdown
takes only `title` and `body` (anything else is 400) and creates a draft instructions layer owned by the
ship's owner and addressed to the ship, with
```

with

```markdown
takes only `title`, `body`, `charter` and `policy` (anything else is 400) and creates a draft instructions layer owned by
the ship's owner and addressed to the ship (a charter draft to no ship), with
```

In `peer/API.md`, replace

```markdown
## Signed records
```

with

```markdown
## Charter

Spec A step 4, merge 4a (`docs/superpowers/specs/2026-10-15-charter-step4-design.md`): an instructions layer can be the
station's charter. Its policy sets the limits every grant on the station obeys (see Grants), and its active revision
binds the ships its signer owns and the resident ships, first among their instructions. Acceptance by other owners is
merge 4c; until then another owner's ship is bound by its owner's own layers alone.

**Drafts.** `POST /api/layers` and `PUT /api/layers/{id}` take `charter` (true or false) and `policy` (an object, or
null for the defaults). `charter` is stored only when true and `policy` only when set, so a note or an ordinary draft
stores neither. These checks come before every other draft check, in this order: `charter` not a boolean (400
"charter is true or false"); on a save, a layer that has a charter revision and a draft that isn't one (409 "This layer
is the station's charter and stays one; withdraw it to end it"); `charter` on a note (400); a charter with ships in
`audience_users` (400: a charter names no ships); a `policy` without `charter: true` (400); a policy that fails the
schema (400 naming the path). A charter draft keeps its policy as written. A ship drafts one through
`POST /api/ships/me/drafts` with `charter: true` and an optional `policy`; it names no ships, and only a super admin
can sign it.

**Policy, version 1.** Unknown keys at any level and wrong types are refused with 400 naming the path, such as
`policy.delegation.max_depth` (a boolean is never a number, and `3.0` is not a whole number); `roots` and `breaker`
are reserved for step 5. Missing keys take the defaults, filled before the bounds and cross-checks run, and a charter
revision stores the full policy.

| Path | Default | Allowed |
|---|---|---|
| `version` | — | required, 1 |
| `delegation.max_depth` | 3 | whole, 0 to 5 |
| `delegation.max_expiry_hours` | 720 | whole, 1 to 2,160 |
| `delegation.agent_grant_default_hours` | 24, or `max_expiry_hours` if smaller | whole, 1 to 2,160, at most `max_expiry_hours` |
| `delegation.delegable` | `["direct"]` | `direct` at most once; `merge`, `deploy` and `admit` are reserved for spec B |
| `budgets.builds_per_ship_per_day` | 20 | whole, 0 to 500 |
| `grantees` | null (unrestricted) | null, or `{people, ships_of}`: ids of local person accounts, each once, at most 100 together |

**Widened paths.** From a baseline policy to a new one: a number that grows (`delegation.max_depth`,
`delegation.max_expiry_hours`, `delegation.agent_grant_default_hours`, `budgets.builds_per_ship_per_day`), an action
gained (`delegation.delegable:<action>`), a restricted grantee set made null (`grantees`), and, with both restricted, an
id gained (`grantees.people:<id>`, `grantees.ships_of:<id>`). Narrowings are the same paths the other way; prose is
neither. Each list is sorted by path, its items `{path, before, after}`; a policy can widen at most 105 paths.

**Activation.** `POST /api/layers/{id}/activate` takes `confirm_widenings`, a list of paths (absent is `[]`). For a
charter, after the owner's 404, the changed draft's 409, the 409 for a layer that has had a charter revision and a
draft that isn't one, and the draft checks: 403 "Only a super admin can sign the station's charter"; 409 "Another
charter is active; its owner must withdraw it first"; 400 "confirm_widenings is a list of paths" (not a list of at most
105 strings of at most 200 characters); 409 "Confirm exactly these widenings: …" unless it holds exactly the paths that
widen from the policy in force (the active charter's, or the defaults), each once, in any order; and 409 "<ship> would
have more than 10 instruction layers or 48,000 bytes of them" for a resident or a ship of the signer's that the new
revision would put over the caps. The revision is written and signed in one transaction, with `charter: true`, no
audience and the full policy. Any other layer gets 400 "Only a charter has widenings to confirm" for a non-empty list.

**Preview.** For a charter draft, `GET /api/layers/{id}/preview` has `charter: {policy, widenings, narrowings, names,
binds, sha256}`: the full policy, its widened and narrowed paths against the policy in force, `names` (each listed
person id's name), the ships it would bind (`[{id, name, owner_name}]`, residents with `owner_name: null`), and
`{title, body}`, each the hex sha256 of the saved text in UTF-8.

**Withdrawal and narrowing.** `POST /api/layers/{id}/withdraw` (an empty body counts as `{}`) on the active charter needs
`confirm_widenings` holding exactly the paths that widen from its policy to the defaults (409 naming them otherwise). A
withdrawn charter binds no ship, and the defaults are in force again. `POST /api/layers/{id}/revoke` on a charter gets
409 "A charter has no audience to narrow; sign a new revision or withdraw it" and writes nothing.

**Reading.** Every signed-in person reads the active charter revision's signed record through
`GET /api/layers/{id}/revisions/{n}/signed`; every other revision, a charter's included, stays its owner's.
`GET /api/ships/me/instructions` marks each layer with `charter`, and its `charter` is null while none is active, else
`{layer_id, revision, binding, accepted}`: the active revision, the revision binding this ship (null when none does),
and whether the ship's owner signed it (always true for a resident).

## Signed records
```

In `peer/API.md`, replace

```markdown
`policy` is `null`, and `created` is the
  revision's time.
```

with

```markdown
`policy` is the full policy on a charter
  revision and `null` on every other, and `created` is the revision's time.
```

In `peer/API.md`, replace

```markdown
`GET /api/layers/{id}/revisions/{n}/signed` (person) returns `{station, record, signature}` to the layer's owner.
Anyone else, and any revision without a signature, gets 404; a ship key gets 403.
```

with

```markdown
`GET /api/layers/{id}/revisions/{n}/signed` (person) returns `{station, record, signature}` to the layer's owner, and
the active charter revision's to every signed-in person. Anyone else, and any revision without a signature, gets the
same 404; a ship key gets 403.
```

In `peer/API.md`, replace

```markdown
| GET `/api/grants/people` | — | `[{id, name}]`: this station's active people other than the caller, by name |
```

with

```markdown
| GET `/api/grants/people` | — | `[{id, name}]`: this station's active people other than the caller, by name; while the charter restricts grantees, only its `people` |
| GET `/api/grants/policy` | — | `{max_depth, max_expiry_hours, builds_per_ship_per_day}` of the policy in force |
```

In `peer/API.md`, replace

```markdown
**Policy.** With no charter (step 4), `Grants._grant_policy` returns spec A's defaults: `max_depth` 3,
`max_expiry_hours` 720, `agent_grant_default_hours` 24, `builds_per_ship_per_day` 20, `delegable` `["direct"]`, and an
unrestricted grantee set. Every check reads it there, so a narrower policy takes effect at the next check.
```

with

```markdown
**Policy.** `Grants._grant_policy` returns the policy in force: the active charter revision's (see Charter), or, with
no charter active, spec A's defaults: `max_depth` 3, `max_expiry_hours` 720, `agent_grant_default_hours` 24,
`builds_per_ship_per_day` 20, `delegable` `["direct"]`, and an unrestricted grantee set. Its `grantees` is the
charter's `people` list, or null when unrestricted. Every check reads it there, so a change takes effect at the next
check, and a withdrawn charter restores the defaults.
```

In `peer/API.md`, insert before

```markdown
1. `rooms` is `"*"` or a list of 1 to 20 room ids, each once (400).
```

this, as its own line:

```markdown
0. While the policy's `max_depth` is 0: 400 "The station's charter allows no grants".
```

In `peer/API.md`, replace

```markdown
   not the caller (400).
```

with

```markdown
   not the caller (400). With a grantee set in force, the grantee is one of its `people` (400 "The station's charter
   doesn't allow grants to this person").
```

In `peer/API.md`, replace

```markdown
a chain longer than `max_depth` or a grantee outside the grantee set: "Grant #a1b2 is no longer allowed by the
station's policy")
```

with

```markdown
a chain longer than `max_depth`, a grantee outside the grantee set, or a link a ship issued (none until step 5) with an
action outside `delegable`: "Grant #a1b2 is no longer allowed by the station's policy")
```

In `peer/API.md`, replace

```markdown
several links), its names on one line without `@`, and empty otherwise.
```

with

```markdown
several links), each ending ` · charter r<n>` when the ticket's recorded instructions include a charter revision (n is
that recorded revision, so a footer never changes after its run), its names on one line without `@`, and empty
otherwise.
```

In `agent/README.md`, replace

```markdown
**What binds a ship.** Only the owner's own active `instructions` layers that are addressed to the ship. Only
people sign: the ship's owner, in the web app. A ship can draft, but a draft binds nothing until the owner reads,
edits and activates it. The station allows at most 10 layers and 48,000 rendered bytes per ship. Each block names
its title, revision and signer.
```

with

```markdown
**What binds a ship.** First the station's charter, when one is active and the ship's owner signed it (only a super
admin signs one, in the web app) or the ship is a resident such as Odo or Wormhole; then the owner's own active
`instructions` layers that are addressed to the ship. Only people sign. A ship can draft, but a draft binds nothing
until the owner reads, edits and activates it. The station allows at most 10 layers and 48,000 rendered bytes per
ship, the charter included. Each block names its title in brackets, its revision (`charter revision N` for the
charter) and its signer, and a build's footer ends ` · charter rN` when the charter bound its run.
```

In `agent/README.md`, replace

```markdown
If the blocks do not fit, it prints each layer's title, revision and signer,
```

with

```markdown
If the blocks do not fit, it prints each layer's bracketed title, revision and signer,
```

In `agent/README.md`, replace

```markdown
- **`status`.** Prints `Instructions: none`, or one line per layer: title, revision and signer.
```

with

```markdown
- **`status`.** Prints `Instructions: none`, or one line per layer, `[<title>] · revision <n> · signed by <name>`
  (`charter revision <n>` for the charter), then one charter line: `Charter: none active`, `Charter: revision N binds
  this ship`, `Charter: revision N is pending for this ship's owner; revision M binds this ship`, or `Charter: revision
  N is active; this ship's owner has not accepted it`. A station older than the charter gives no charter line.
```

In `agent/README.md`, replace

```markdown
saves a draft for the owner. Nothing changes for the ship until the owner activates it in the web app.
```

with

```markdown
saves a draft for the owner. With `charter: true` and an optional `policy` it drafts the station's charter instead,
which names no ships; only a super admin signs one, and an older station refuses it with an error. Nothing changes
for the ship until the owner activates it in the web app.
```

- [ ] **Step 2: Run the whole suites**

Check first that no whole peer suite is running on the Pi (`pgrep -af "venv/bin/python -m pytest -q -p no:cacheprovider$"` prints nothing), then run `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider` (expected `758 passed`) and `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider` (expected `961 passed`).

- [ ] **Step 3: Commit**

```bash
git add peer/API.md agent/README.md
git commit -m "Charter 4a: API.md and the agent README say what the charter does (R23)"
```

---

## Self-review: every requirement and test to its task

| Spec | Task | Test |
| --- | --- | --- |
| R1 | 2 (3 for C6) | 1: `test_a_policy_refuses_each_bad_value_and_names_its_path`, `test_a_draft_checks_charter_and_policy_first_in_the_spec_order`, `test_a_draft_stores_charter_and_policy_only_when_set` |
| R2 | 1, 3 | 1: `test_a_policy_fills_its_defaults_before_its_cross_check`; 2: `test_a_charter_revision_stores_the_full_policy_and_the_draft_keeps_what_was_written` |
| R3 | 3 | 3: `test_only_a_super_admin_signs_a_charter` |
| R4 | 3 | 4: `test_one_charter_layer_is_active_at_a_time` |
| R5 | 3 | 8: `test_a_charter_stays_a_charter` |
| R6, R7 | 4 | 5: `test_a_charters_widenings_are_confirmed_path_by_path`; 6: `test_one_widened_number_among_twenty_changed_lines_is_refused_until_confirmed`; the preview: `test_the_preview_shows_a_charters_policy_changes_ships_and_hashes` |
| R8 | 5 | 9: `test_narrowing_a_charter_is_refused_and_writes_nothing` |
| R9 | 5 | 10: `test_withdrawing_a_charter_confirms_what_returns_to_the_defaults` (no ship bound after it: test 14) |
| R10, R11 | 6 | 11: `test_the_policy_in_force_governs_making_validity_and_the_per_ship_cap`; 12: `test_a_grantee_set_in_force_limits_making_validity_and_the_person_list` |
| R12 | 6 | 13: `test_delegable_governs_links_a_ship_issued_and_never_a_browser_root` |
| R13 | 3, 7 | 2; 7: `test_the_law_becomes_the_charter_in_place_in_one_transaction` |
| R14 | 7 | 14: `test_the_charter_binds_its_signers_ships_and_the_residents_first`; 7; 23: `test_binding_matches_an_independent_reading_of_the_rule` |
| R15 | 7 | 15: `test_a_ticket_renders_the_charter_block_first_in_the_recorded_order` |
| R16 | 8 | 16: `test_the_caps_count_the_charter_once_for_every_ship_it_binds`, `test_a_charter_too_large_for_a_resident_is_refused_naming_it` |
| R17 | 9 | 18: `test_a_block_header_brackets_its_title_and_marks_the_charter` |
| R18 | 9 | 17: `test_a_build_footer_names_the_charter_revision_its_ticket_recorded` |
| R19 | 10 | 19: `test_the_active_charter_revision_is_signed_for_everyone_and_a_past_one_for_its_signer` |
| R20 | 11, 12 | 20: `test_the_ship_route_marks_the_charter_and_says_which_revision_binds`, `test_status_brackets_titles_and_prints_one_charter_line` |
| R21 | 11, 13 | 21: `test_a_ship_drafts_a_charter_with_a_policy_and_no_audience`, `test_drafting_a_charter_sends_charter_and_policy_and_an_older_stations_400_is_an_error` |
| R22 | 12 | 22: `test_the_conversion_reaches_a_session_as_a_changed_charter_block` |
| R23 | 14 | the whole suites; the docs |

## Deploy

From the spec's Deploy, for 4a. No charter is activated in 4a: Andy signs only once 4b is live (C31).

Each merge goes under section 2: approved in the room, the Pi suites passing. Before each: back up `peer.sqlite3` with
SQLite's backup API. After each: restart the lighthouse and the door; for 4a also the rio-grande, odo and wormhole
watchers (the hook's header, status); then the live check below, and on a failed check revert, restart and announce.
Other machines get the agent changes when they pull and `make dock`.

**Live check, 4a, before any charter (with no person's login).** Rio Grande's `superyak-agent status` on the Pi prints
the law as `[Station law for Andy's ships] · revision 1 · signed by Andy` and "Charter: none active"; its next prompt
prints no change notice.

**The rehearsal (after 4a, and again just before Andy signs, with the reviewed text and the policy Andy chose in Q3).**
On a copy only; the live station gets no charter.

- Copy the live database with SQLite's backup API, never `cp` (it runs in WAL mode), into a scratch directory. Create a
  throwaway identity there, as `station-restore-test` does, but don't run that command or its reconcile: grants and
  ship keys on the copy stay as they are live.
- Open a throwaway store on the copy. As Andy's account, through store methods: save the law's draft with
  `charter: true`, `audience_users: []`, the reviewed text and Andy's policy; preview it (no widenings with Q3 A, or
  exactly the widenings Andy will confirm with Q3 B; it binds Andy's four ships, odo and wormhole); activate it with
  that `confirm_widenings`.
- Check: each of the six ships is bound by the law's new revision first; Rio Grande's blocks start with the charter
  header; an owner ticket ends ` · charter rN`, for a message by Andy that mentions Rio Grande, made by a store call on
  the copy (never a post, so law section 7's "post only as yourself" isn't engaged); the new revision verifies against
  the throwaway card; revision 1's signature row is unchanged.
- With Q3 B: list every grant on the copy that a narrowing makes invalid, so Andy knows before he signs.
- Delete the copy.

**Rollback (a merge before the conversion):** revert, restart, announce. Charter drafts left behind bind nothing on an
older station, and the `grants` table is as step 3 left it (the spec's Mixed versions).
