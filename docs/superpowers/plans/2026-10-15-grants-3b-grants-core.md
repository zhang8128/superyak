# Spec A step 3, merge 3b: the grants core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person can make, read, revoke and check a station-signed grant that lets another person direct some of
their own ships in some rooms, for some hours, with a daily budget of builds; a restore takes back revoked grants and
spent budgets; and only the lighthouse holds the station key at startup, which no start ever replaces silently.

**Architecture:** `Store` gains `signing=True`; the door and the station commands that never sign open it with
`signing=False`. One lost-identity check (`signatures.refuse_a_lost_identity`) guards every place that could create an
identity, and `station-new-identity` is the deliberate way to a new key. A new `grants.py` mixin holds the tables, the
policy, validity, making, reading and revoking; `signatures.py` builds and signs the grant and revocation records and
serves `/signed`; `backups.py`'s reconcile revokes grants and restores budget uses. Spending (tickets, the page) is
merge 3c.

**Tech Stack:** Python 3.13, FastAPI, SQLite (`sqlite3`, JSON1), `cryptography` (Ed25519), pytest with FastAPI's
`TestClient`. Run tests from `peer/` with `PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider <files>`.

**Spec:** `docs/superpowers/specs/2026-10-15-grants-step3-design.md` at grants-spec `d7a541e` (merged into grants-3b at
`efaabdb`; approved under D8, revision 3, with G4 amended, G4a-G4c approved by their D8 re-checks, and d7a541e's
clarifications from drafting this plan): section 1's G4a, G4b and G4c, and section 2 (G7-G14), Testing 4a, 4b, 4c and
5-10, with API.md's part of G23. Spec A
(`docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`) holds where the step 3 spec is silent. The
survey beside the spec is cited as "survey 3.2" and so on.

**Plan revision 2.** Base: grants-3b at `84ee0f6` (main 57c4322, with 3a's section 2 fixes, and spec d7a541e). The
fresh review of revision 1 (6942e90: APPROVE WITH CHANGES, 0 must-fix, 2 should-fix, 8 nits; it dry-ran every step at
84ee0f6, 860 to 899 passed) is answered here: S1 (Task 2: the restore test imports `PeerIdentity` inside the function),
S2 (Task 3: `--data-dir` required), N1 (Task 2: an unreadable database refuses with its name), N2 (Task 8's mutation),
N3 (the Task 1 and Task 4 anchors), N4 (R14), N5 (Task 9's runbook line), N6 (G4c is its own Task 3, and later tasks
moved up one), N7 (these references and Task 9's numbers) and N8 (the test inserts name their columns). Every task was
dry-run in a scratch worktree: each RED output is the one seen, each GREEN ran, and each Step 5 mutation was applied
alone and failed the test it names; the steps revision 2 changed were dry-run again at 84ee0f6.

Tasks: 1 G4a (who holds the key at startup); 2 G4b (a lost identity is never replaced silently); 3 G4c
(`station-new-identity`); 4 the grants table, policy, validity and the grant's signature (G7, G9, G12); 5 reading
(G11, `/signed`, the people list); 6 making (G8); 7 revoking and the revocation's signature (G10, G12); 8 the restore
reconcile (G13); 9 API.md, the runbook and the whole suite.

## Rulings

Decisions made before this plan (the coordinator's brief), and the ones this plan adds. A fresh reviewer checks each;
Andy can veto any.

| # | Ruling | Why |
| --- | --- | --- |
| R1 | `peer/superyak_peer/grants.py` holds a `Grants` mixin and `GRANT_SCHEMA`: making, validity, revoking, reading, the policy and the people list. Signing stays in `signatures.py`: `_grant_record`, `_revocation_record`, `_sign_grant`, `_sign_revocation`, the revocation backfill, and `grant_signed` (the route method, beside 3a's `revision_signed`). | Given. `signatures.py` owns the station's signatures and their routes. |
| R2 | The grant row is inserted with an empty `signature` and `_sign_grant` fills it from the stored row before the inserting transaction commits. | The column is NOT NULL. One record builder serves both signing and `/signed`, so what was signed and what is served can't drift (a REAL or JSON round trip can't make them differ). Nothing outside the transaction ever sees the empty value; a failed signature rolls the insert back (Task 4 tests it). |
| R3 | The signed record is rebuilt from the row and the station's current peer id, as the spec's table has it; storing each record's bytes beside its signature (3a's final review) is not done. A re-keyed station's old records stop verifying, as the spec's Known limits say for revisions. | Given (decision 2). |
| R4 | The reconcile writes revocations without a signature; the startup backfill signs them. `POST /api/grants/{id}/revoke` signs in its own transaction. | Given (decision 3). |
| R5 | G4a-G4c come first, since they change `Store.__init__` and `signatures.py`, which the grants tasks build on: Task 1 is G4a (who holds the key, one loader), Task 2 is G4b (the lost-identity check everywhere, the restore test's throwaway identity), Task 3 is G4c (`station-new-identity`). G4b's signed records are `revision_signatures` rows from Task 2, and Task 4 extends the same list with grants whose `signature` is set. | Coordinator's ruling. The restore test's throwaway identity must land with G4b's start check, which otherwise fails it on any copy holding a signed revision. G4c is its own task for a smaller review gate (plan review N6); G4b's message names `station-new-identity` one commit early, which is harmless. The grants table only exists from Task 4, so the task that adds it extends the check and tests it. |
| R6 | G4b's grants clause counts `grants` rows whose `signature != ''`, not every row. | The lazy check reads the caller's connection (spec G4b), which sees the row its own transaction is about to sign: counting it would refuse a new station's first grant as a "lost identity". Task 4 tests the first grant on a new station. Now spec text (G4b, d7a541e). |
| R7 | `signing=False` also skips the revocation backfill (Task 7). | The revocation backfill loads the key just as G5's does, and G4a's point is that those openers hold none. Now spec text (G4a, d7a541e). |
| R8 | Task order: identity (1-3), schema and validity (4), reading (5), making (6), revoking (7), reconcile (8), docs (9). Reading comes before making. | G8 returns "the grant as G11 shows it", so G11's view must exist, tested, before the route that returns it. |
| R9 | `RECONCILED_TABLES` gains `grants` and `budget_uses` in Task 4, not with the reconcile (Task 8). | `test_every_table_is_either_reconciled_or_named_coordination` fails the moment the schema has a table in neither list (3a hit this: 61d4ccd). |
| R10 | G11's "issued" includes the issuers of the grants above (a walk), so G10's "issuer of any grant above it" can reach the grant; one Python visibility rule serves the list, revoke and `/signed`. | In step 3 every grant is its own root, so it reads exactly as G11. Without it, G10's rule would always meet G11's 404 first. Now spec text (G11, d7a541e). |
| R11 | `POST /api/grants/{id}/revoke` validates `reason` first (400, which says nothing about the grant), then 404, 403, 409 in the spec's listed order. A missing, `null` or blank reason becomes `revoked`. | The codebase validates input before its transaction; a browser form's empty field must not be a 400. |
| R12 | A grant is expired from its `expires` instant on (`now >= expires`). Budget and ship windows count `created > now - 86400`. `budget_left` and `ship_builds_left` never go below 0. `reason` is present only when the grant is not valid. `revoked_by` is `{id, name}` or null. `POST /api/grants` answers 201. | Each is pinned by a test. The expiry instant and `revoked_by`'s shape are now spec text (G9, G11, d7a541e); the rest are this plan's. |
| R13 | A revocation with no person (the restore) reads `Grant #a1b2 was revoked`, without "by". | The spec's reason names a person; the reconcile records none. |
| R14 | G8's refusals have one message each (constants in `grants.py`), and its integers are JSON integers only (`true`, `24.0`, `"24"` refused). Step 1's shape check (400) runs before its membership check (404); a grantee that isn't a string reaches a 400 (step 2's with listed rooms, step 3's with `"*"`), never a 500. | Distinct messages let the order tests tell which check answered. |
| R15 | G11's forward walk stops with no `current` at a fork or a cycle. | `add_participants` never forks (work board 8.4); only an older or hand-edited database has one. |
| R16 | The reconcile report names each revoked grant with why: `as in the replaced file`, `missing from the replaced file` or `no usable replaced file`, and counts `grants revoked` and `budget uses added`. | Andy learns which grants to make again. |
| R17 | `station-new-identity` refuses an `--endpoint` that isn't `https://HOST...`, and its logic lives in `__main__.py`'s `new_identity_for`. | Its certificate must name a host; the CLI module holds the other station-command helpers. |
| R18 | `docs/station-restore.md` gains three prose lines: grants in "what a restored copy brings back", step 6's "restore identity.json rather than delete it, or, if it is truly lost, run `station-new-identity --data-dir DIR`", and step 7's "make again". | Andy reads the runbook at a restore, not API.md. |

## Global Constraints

- Spec values, verbatim:
  - `CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES users(id), grantee_id TEXT NOT NULL REFERENCES users(id), actions TEXT NOT NULL, targets TEXT NOT NULL, rooms TEXT NOT NULL, expires REAL NOT NULL, budget INTEGER NOT NULL, depth INTEGER NOT NULL, confirm TEXT NOT NULL, parent_id TEXT REFERENCES grants(id), charter_layer_id TEXT, charter_revision INTEGER, follow INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);`
  - `CREATE TABLE IF NOT EXISTS budget_uses(grant_id TEXT NOT NULL REFERENCES grants(id), ticket_id TEXT NOT NULL, created REAL NOT NULL);`
  - `CREATE INDEX IF NOT EXISTS budget_uses_by_grant ON budget_uses(grant_id, created);`
  - In step 3, `actions` is `["direct"]`, `depth` is 0, `confirm` is `none`, and `parent_id`, the charter columns and `follow` are empty. Rows never change, except that revoking fills `revoked`, `revoked_by`, `revoke_reason` and `revocation_signature`.
  - The policy (G7): `max_depth` 3, `max_expiry_hours` 720, `agent_grant_default_hours` 24, `builds_per_ship_per_day` 20, `delegable` `["direct"]`, an unrestricted grantee set; every check reads it through `_grant_policy(db)`.
  - G8's order: 1 rooms (`"*"` or 1 to 20 ids; unknown, remote (`:`), breakout or not-a-member is the same 404); 2 current and with the grantee (400); 3 grantee a person on this station, not a ship, the system author or awaiting activation, and not the caller (400); 4 1 to 20 targets owned by the caller (400); 5 `hours` a whole number 1 to `max_expiry_hours`; 6 `budget` a whole number 1 to 500. A repeated id is refused (400), never merged.
  - G9's order: 1 revoked ("Grant #a1b2 was revoked by Andy"); 2 expired ("Grant #a1b2 expired 2026-10-20 14:00 UTC"); 3 policy: lifetime ("Grant #a1b2 lasts longer than the station now allows"), chain length and grantee set ("... is no longer allowed by the station's policy"); 4 budget ("Grant #a1b2 has used its 5 builds for the last 24 hours"); 5 ownership ("Andy no longer owns Rio Grande"). Short id: `#` and the id's first 4 characters. Names through `safe_line`.
  - G10: issuer, an issuer above, or a target's owner; admin gives nothing; not shown 404, shown but not allowed 403, already revoked 409; `reason` optional, one line, at most 200 characters, default `revoked`.
  - G12 records, exactly: `{kind: "grant", station, id, issuer_id, grantee_id, actions, targets, rooms, expires, budget, depth, confirm, parent_id, charter_layer_id, charter_revision, follow, created}` (actions, targets, rooms parsed) and `{kind: "grant-revocation", station, grant, revoked, revoked_by, reason}`.
  - G13's COMPARED additions: `grants.id`, `grants.revoked`, `grants.revoked_by`, `grants.revoke_reason`, `budget_uses.grant_id`, `budget_uses.ticket_id`, `budget_uses.created`.
  - G4a: `Store(..., signing=True)` by default; `signing=False` for `create_door` and `station-pending`, `station-approve`, `station-deny`, `station-rooms`, `station-bridge`, `station-unbridge`, `station-notices`. G4b: `identity.json` missing (not a file, not a symlink) while signed records exist refuses with a `ValueError` naming the file and `station-new-identity`.
- The station identity is created only inside a transaction that holds the dispatch gate, through `_station_identity()`, and never by an opener that merely starts (3a's plan review M1). Inside a transaction, pass its `db`: a second `BEGIN IMMEDIATE` on a new connection waits out SQLite's 30-second timeout.
- Every `/api/grants` route uses `actor(request)`, so `current_user` refuses a ship key with `{"error": "Ship keys cannot use this route"}` before the store runs.
- Every test is named, written first and seen failing first (or, where a test guards behaviour that already holds, the plan says so and Step 5's mutation shows it bites).
- Repo norms: a new module goes in both `only-include` lists of `peer/pyproject.toml` (sdist and wheel), a new test file in the sdist one; `test_packaging.py` builds and starts the result.
- Superyak's repository only. The merge goes through section 2 of the station law: Rio Grande approves in the room, and the Pi suites pass.

## Review Focus

Inputs no spec test names, most likely to bite a person first. Each is pinned by a test in its task.

1. A JSON `true` for `hours` or `budget`: Python's `bool` is an `int`, so `isinstance` would take it as 1 hour or 1
   build. Refused, as are `24.0` and `"24"` (Task 6, `test_making_a_grant_refuses_each_bad_field_with_its_status`).
2. A new station's first grant, before any `identity.json` exists: the lost-identity check must not count the very row
   being signed, or the first grant fails as a "lost identity" (Task 4,
   `test_a_station_holding_grants_does_not_start_without_its_identity`).
3. The browser sends an empty or all-space revoke reason: it becomes `revoked`, not a 400 (Task 7,
   `test_a_revoke_reason_is_one_line_of_at_most_200_characters`).
4. A display name holding a newline and an `@` (`Andy\n@serenity`) in a validity reason: one safe line, no mention
   (Task 4, `test_a_revoked_grant_names_who_revoked_it_even_once_expired`).
5. A replaced file without the grants tables (the wrong file, or a damaged one): treated as absent, so every grant is
   revoked rather than none compared (Task 8, `test_a_replaced_file_without_the_grants_tables_is_treated_as_absent`).

## Known limits (beyond the spec's)

- `GET /api/grants` reads every grant and applies the visibility rule in Python. A station holds tens of grants.
- `ship_builds_left` counts grant build tickets (`mode='build'`, `basis='grant'`), which only merge 3c writes. This plan
  pins the count with hand-made ticket rows; 3c's test 14 pins it end to end.
- The reconcile report's short ids are 4 characters; two grants sharing one are told apart by issuer and grantee only.
- `create_app` still loads the identity through `Federation(store)` (`PeerIdentity.load_or_create`), a second loader
  beside `_station_identity()`. It runs after the `Store`'s lost-identity check, so G4b holds; on a station with no
  signed records it creates the identity at the lighthouse's first start, as it does today (3a's plan, N8).
- A mutation in Task 1 Step 5 (the room read without its `db`) takes about 70 seconds to fail: it waits out SQLite's
  timeout, which is the stall it shows.

## File Structure

- Modify `peer/superyak_peer/db.py`: `signing=True`, the grants schema and mixin, the revocation backfill.
- Modify `peer/superyak_peer/signatures.py`: `_station_identity(db=None)`, the lost-identity check
  (`SIGNED_RECORDS`, `holds_signed_records`, `refuse_a_lost_identity`, `refuse_a_lost_identity_before_the_store`), and
  the grant and revocation records, signatures, backfill and `grant_signed`.
- Modify `peer/superyak_peer/peer_store.py`: `_own_peer_id(db=None)` through `_station_identity`.
- Modify `peer/superyak_peer/door.py`: `signing=False`.
- Modify `peer/superyak_peer/__main__.py`: `signing=False` for the seven commands, the `serve --peer-tls` check,
  `station-new-identity`.
- Modify `peer/superyak_peer/backups.py`: the restore test's throwaway identity; the grants reconcile.
- Create `peer/superyak_peer/grants.py`: the `Grants` mixin and `GRANT_SCHEMA`.
- Modify `peer/superyak_peer/app.py`: five routes.
- Modify `peer/pyproject.toml`, `peer/API.md`, `docs/station-restore.md`.
- Modify `peer/tests/test_signatures.py` (tests 4a-4c), `peer/tests/test_restore.py` (`RECONCILED_TABLES`).
- Create `peer/tests/test_grants.py` (tests 5-10).

---

### Task 1: Only the lighthouse holds the key at startup (G4a)

**Files:**
- Modify: `peer/superyak_peer/db.py` (`Store.__init__`'s signature, and its last two lines)
- Modify: `peer/superyak_peer/signatures.py` (`_station_identity`, and its three callers in the module)
- Modify: `peer/superyak_peer/peer_store.py` (`_own_peer_id`, `_unverified_local_authors` and its one caller in `_remote_room`)
- Modify: `peer/superyak_peer/door.py` (`create_door`'s `Store(...)`)
- Modify: `peer/superyak_peer/__main__.py` (six `Store(args.data_dir)` calls, for seven commands)
- Test: `peer/tests/test_signatures.py`

**Interfaces:**
- Consumes: `Signatures._load_station_identity`, `_backfill_revision_signatures` (3a); `PeerIdentity.load_or_create`.
- Produces:
  - `Store(data_dir, *, clock=time.time, share_link_file=None, signing=True)`. With `signing=False` the start loads no
    identity and runs no signing backfill.
  - `Signatures._station_identity(self, db=None) -> PeerIdentity`: loads or creates the identity inside a transaction
    (the caller's `db`, or one of its own when given none). Task 2 adds the lost-identity check inside it.
  - `PeerStore._own_peer_id(self, db=None) -> str`, now `self._station_identity(db).peer_id`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_signatures.py`:

```python
def signed_station(tmp_path):
    """A station with one signed revision, a person, a room, a waiting docking and the wormhole ship, so each station
    command below has something to do: (store, owner, ship, room, docking)."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    ship, _ = docked(store, owner['id'], 'serenity')
    law = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.', 'audience_users': [ship['id']]})
    store.activate_layer(owner['id'], law['id'], law['version'])
    store.create_station_ship('wormhole', 'Wormhole')
    room = store.create_room(owner['id'], 'Ops', [])
    return store, owner, ship, room, store.start_docking('defiant', 'bazzite')


def run_cli(capsys, *argv):
    """The CLI's exit code, stdout and stderr."""
    from superyak_peer.__main__ import main
    try:
        main([str(arg) for arg in argv])
        code = 0
    except SystemExit as stopped:
        code = stopped.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_the_door_and_the_station_commands_work_while_the_identity_is_damaged(tmp_path, capsys):
    """G4a, test 4a: a damaged identity.json stops the lighthouse alone. The door takes access requests, and each
    station command that never signs starts and does its work. A revision left unsigned shows they skip the backfill."""
    from fastapi.testclient import TestClient
    from superyak_peer.app import create_app
    from superyak_peer.db import Store
    from superyak_peer.door import create_door
    store, owner, ship, room, docking = signed_station(tmp_path)
    late = store.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Later', 'body': 'x', 'audience_users': [ship['id']]})
    store.activate_layer(owner['id'], late['id'], late['version'])
    with store.transaction() as db:  # unsigned, as from before merge 3a: a backfill here would need the key
        db.execute('DELETE FROM revision_signatures WHERE layer_id=?', (late['id'],))
    (store.data_dir / 'identity.json').write_text('not json')
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)
    with pytest.raises(ValueError, match='identity.json'):
        create_app(store.data_dir, allowed_origins=['http://testserver'])
    door = create_door(store.data_dir)
    assert getattr(door.state.store, '_identity', None) is None
    asked = TestClient(door, base_url='https://door.example:8443').post(
        '/api/access-requests', json={'name': 'Eve', 'contact': 'eve@example.org'})
    assert asked.status_code == 201, asked.text
    data = ['--data-dir', store.data_dir]
    (tmp_path / 'rotation').mkdir()
    for argv in (['station-pending', *data], ['station-notices', *data],
                 ['station-notices', *data, '--backup-dir', tmp_path / 'rotation'],  # the branch that lists alerts too
                 ['station-approve', *data, '--id', docking['id'][:8], '--as', 'andy'],
                 ['station-deny', *data, '--id', asked.json()['id'][:8], '--as', 'andy'],
                 ['station-rooms', *data, '--as', 'andy'], ['station-bridge', *data, '--id', room['id'][:8], '--as', 'andy']):
        code, out, err = run_cli(capsys, *argv)
        assert code == 0 and 'could not be read' not in err, (argv[0], err)
    bridged = next(listed for listed in Store(store.data_dir, signing=False).station_rooms('andy') if listed['bridged'])
    code, out, err = run_cli(capsys, 'station-unbridge', *data, '--id', bridged['id'][:8], '--as', 'andy')
    assert code == 0, err
    with Store(store.data_dir, signing=False).transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures WHERE layer_id=?', (late['id'],)).fetchone()[0] == 0


def test_the_door_holds_no_key_even_when_the_identity_is_sound(tmp_path):
    from superyak_peer.door import create_door
    store, owner, ship, room, docking = signed_station(tmp_path)
    assert (store.data_dir / 'identity.json').is_file()
    assert getattr(create_door(store.data_dir).state.store, '_identity', None) is None


def test_a_store_opened_without_signing_still_signs_what_it_writes(tmp_path):
    """G4a: signing=False holds no key at the start, but an activation through it is still signed, and the first
    signature on a station with no signed records creates the identity (G4)."""
    from superyak_peer.db import Store
    quiet = Store(tmp_path / 'station', signing=False)
    owner = quiet.create_user('owner', 'Owner', 'long-password')
    ship, _ = docked(quiet, owner['id'], 'serenity')
    layer = quiet.create_layer(owner['id'], {'kind': 'instructions', 'title': 'Law', 'body': 'Be kind.', 'audience_users': [ship['id']]})
    assert not (quiet.data_dir / 'identity.json').exists()
    quiet.activate_layer(owner['id'], layer['id'], layer['version'])
    card = card_of(PeerIdentity.load_or_create(quiet.data_dir))
    assert verify_record(card, stored_record(quiet, layer['id'], 1), signature_rows(quiet)[(layer['id'], 1)])


def test_own_peer_id_reads_the_stores_one_identity(tmp_path):
    """G4a: remote rooms read this station's peer id through _station_identity(), the one loader."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    store._identity = other  # whatever the store holds is what _own_peer_id answers
    assert store._own_peer_id() == other.peer_id


def test_own_peer_id_inside_a_room_read_does_not_stall(tmp_path):
    """G4a, test 4c: a remote room's read runs in a transaction and asks for this station's peer id; on a station without
    an identity that creates it through the caller's connection, never a second BEGIN IMMEDIATE that waits 30 s."""
    import json
    import time
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    andy = store.create_user('andy', 'Andy', 'long-password-andy')
    peer = 'ab' * 32
    with store.transaction() as db:
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", (peer,))
        db.execute("INSERT INTO inbox(origin, resource_id, kind, recipient, revision, actor, payload) "
                   "VALUES(?, 'r1', 'room', ?, 1, 'remote-user', ?)", (peer, andy['id'], json.dumps({'title': 'Theirs'})))
    assert not (store.data_dir / 'identity.json').exists()
    started = time.monotonic()
    assert store.get_room(andy['id'], f'{peer}:r1')['title'] == 'Theirs'
    assert time.monotonic() - started < 10 and (store.data_dir / 'identity.json').is_file()
```

`test_own_peer_id_inside_a_room_read_does_not_stall` passes before this task: today's `_own_peer_id` loads the file
outside any transaction. It guards the change below, which moves the load into `_station_identity`'s transaction, and
Step 5's mutation shows it bites.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py`
Expected: 4 failed. The damaged-identity and sound-identity tests fail at `create_door` (the door's store loads the
identity: `ValueError: The station identity .../identity.json could not be loaded (JSONDecodeError)` for the damaged
one, `assert <superyak_peer.identity.PeerIdentity object ...> is None` for the sound one); the signing=False test with
`TypeError: Store.__init__() got an unexpected keyword argument 'signing'`; the `_own_peer_id` test with an
`AssertionError` comparing two different peer ids. The stall test passes (see above).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/db.py`, change `Store.__init__`'s first line to:

```python
    def __init__(self, data_dir: Path, *, clock=time.time, share_link_file=None, signing=True):
```

and replace its last two lines,

```python
        self._load_station_identity()  # spec A step 3, G4: a station that can't load its identity doesn't start
        self._backfill_revision_signatures()  # G5: after the schema, at every start
```

with:

```python
        if signing:  # G4a: the door and the station commands that never sign hold no key, check none and backfill nothing
            self._load_station_identity()  # spec A step 3, G4: a station that can't load its identity doesn't start
            self._backfill_revision_signatures()  # G5: after the schema, at every start
```

In `peer/superyak_peer/signatures.py`, replace `_station_identity` with:

```python
    def _station_identity(self, db=None):
        """The station's one identity loader (G4, G4a): loaded once, or created if missing, always inside a transaction
        that holds the dispatch gate, so two processes can't both create it and a failed create rolls the caller's
        signed write back. A caller inside a transaction passes its db: a second BEGIN IMMEDIATE on a new connection
        would wait out SQLite's timeout (the gate is reentrant; SQLite's write lock is not). With none, it opens one."""
        if getattr(self, '_identity', None) is None:
            if db is None:
                with self.transaction() as own:
                    return self._station_identity(own)
            self._identity = PeerIdentity.load_or_create(self.data_dir)
        return self._identity
```

and pass `db` at the module's three calls, each inside a transaction: every `self._station_identity()` in
`signatures.py` becomes `self._station_identity(db)`. There are three: `'station': self._station_identity().peer_id`
occurs twice (in `_revision_record` and in `revision_signed`; change both occurrences), and
`self._station_identity().sign_record(record)` once (in `_sign_revision`).

In `peer/superyak_peer/peer_store.py`, replace `_own_peer_id` (the method that sets `self._peer_id_cache`) with:

```python
    def _own_peer_id(self, db=None):
        """This station's peer id, from the store's one identity loader (G4a). A read that fails is not kept. Inside a
        transaction pass its db (see Signatures._station_identity)."""
        return self._station_identity(db).peer_id
```

and give `_unverified_local_authors` the room read's connection: its definition becomes
`def _unverified_local_authors(self, db, replies, origin, messages, actor):`, its first line
`own = self._own_peer_id() + ':'` becomes `own = self._own_peer_id(db) + ':'`, and its one caller in `_remote_room`
becomes `self._unverified_local_authors(db, replies, row['origin'], result['messages'], actor)`. (`remote_send` calls
`_own_peer_id()` before its transaction opens, so it stays as it is.)

In `peer/superyak_peer/door.py`, in `create_door`, the store line becomes:

```python
    store = app.state.store = Store(data_dir, clock=clock, signing=False)  # G4a: the door keeps no key in memory
```

In `peer/superyak_peer/__main__.py`, add `, signing=False` to the `Store(args.data_dir)` in each of these six lines
(seven commands: `station-approve` and `station-deny` share one, as do `station-bridge` and `station-unbridge`, and
`station-notices` has two):

```python
            print(describe_pending(Store(args.data_dir, signing=False).station_pending(), time.time(), args.person))
            item, result = Store(args.data_dir, signing=False).station_decide(args.person, args.id, approve)
            print(describe_rooms(args.person, Store(args.data_dir, signing=False).station_rooms(args.person)))
            room, changed = Store(args.data_dir, signing=False).station_bridge(args.person, args.id, bridge)
                print(json.dumps(Store(args.data_dir, signing=False).station_notices(), indent=2))
                    listed = Store(args.data_dir, signing=False).station_notices()
```

`init`, `card`, `bootstrap-super-admin`, `create-ship`, `demo`, `serve` and `create_app` keep the default.

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_federation.py tests/test_door.py tests/test_station_cli.py tests/test_alerts.py`
Expected: all pass. `test_a_failed_identity_read_is_not_cached` (test_federation) still passes: a load that raises
leaves `_identity` unset, so the next call reads again.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_signatures.py`, see the named test fail, restore:
- `Store(data_dir, clock=clock)` in `create_door` (no `signing=False`) → both door tests;
- `if True:` for `if signing:` in `Store.__init__` → the door tests;
- move `self._backfill_revision_signatures()` out of the `if signing:` block (load skipped, backfill still run) → the
  damaged-identity test (the unsigned revision needs the damaged key);
- drop `, signing=False` from any one of the six `__main__.py` lines → the damaged-identity test, naming that command;
- `_own_peer_id` loading its own copy (`PeerIdentity.load_or_create(self.data_dir).peer_id`) → `test_own_peer_id_reads_the_stores_one_identity`;
- `own = self._own_peer_id() + ':'` again in `_unverified_local_authors` → `test_own_peer_id_inside_a_room_read_does_not_stall`,
  after about 70 seconds (the stall itself).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/db.py peer/superyak_peer/signatures.py peer/superyak_peer/peer_store.py peer/superyak_peer/door.py peer/superyak_peer/__main__.py peer/tests/test_signatures.py
git commit -m "Grants 3b: only the lighthouse holds the station key at startup; one identity loader (G4a)"
```

---

### Task 2: A lost identity is not replaced silently (G4b)

**Files:**
- Modify: `peer/superyak_peer/signatures.py` (imports, module-level check, `_load_station_identity`, `_station_identity`)
- Modify: `peer/superyak_peer/__main__.py` (the `serve --peer-tls` branch)
- Modify: `peer/superyak_peer/backups.py` (two lines in `restore_test`)
- Test: `peer/tests/test_signatures.py`

**Interfaces:**
- Consumes: `Store(..., signing=...)`, `_station_identity(db=None)` (Task 1); `PeerIdentity.load_or_create`.
- Produces:
  - `signatures.SIGNED_RECORDS: tuple[tuple[str, str], ...]`, (table, query) pairs; Task 4 adds grants.
  - `signatures.holds_signed_records(db) -> bool`; a table the database lacks holds none.
  - `signatures.refuse_a_lost_identity(data_dir, db) -> None`, raising `ValueError(LOST_IDENTITY...)`.
  - `signatures.refuse_a_lost_identity_before_the_store(data_dir) -> None`: the same, opening `peer.sqlite3` read-only;
    a missing file holds nothing, and one that can't be read raises a `ValueError` naming it.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_signatures.py`:

```python
def test_a_lost_identity_is_not_replaced_silently(tmp_path, capsys, monkeypatch):
    """G4b, test 4b: with a signed revision and identity.json removed, every signing start refuses, naming the file and
    station-new-identity, and none of them makes a key; a signing=False start still opens."""
    import uvicorn
    from superyak_peer.app import create_app
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    (store.data_dir / 'identity.json').unlink()
    for start in (lambda: Store(store.data_dir), lambda: create_app(store.data_dir, allowed_origins=['http://testserver'])):
        with pytest.raises(ValueError, match='identity.json.*station-new-identity'):
            start()
    served = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: served.append(args))  # a start that got this far would serve
    for argv in (['card', '--data-dir', store.data_dir, '--username', 'andy', '--endpoint', 'https://peer.example:7435'],
                 ['serve', '--data-dir', store.data_dir, '--peer-tls']):
        code, out, err = run_cli(capsys, *argv)
        assert code == 1 and 'identity.json' in err and 'station-new-identity' in err, (argv[0], err)
    assert served == [] and not (store.data_dir / 'identity.json').exists()  # no new key from any of them
    Store(store.data_dir, signing=False)


def test_a_station_with_no_signed_records_still_creates_its_identity_at_the_first_signature(tmp_path):
    """G4b keeps G4: a note's revision is not a signed record, so a station holding one and no identity starts, and
    creates none until it signs."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner = store.create_user('owner', 'Owner', 'long-password')
    note = store.create_layer(owner['id'], {'title': 'Note', 'body': 'mine'})
    store.activate_layer(owner['id'], note['id'], note['version'])
    Store(store.data_dir)
    assert not (store.data_dir / 'identity.json').exists()


def test_a_store_without_signing_refuses_to_sign_over_a_lost_identity(tmp_path):
    """G4b's lazy path, test 4a: a signing=False store opens, but an activation through it fails, writing nothing, when
    the station holds signed records and identity.json is missing."""
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    (store.data_dir / 'identity.json').unlink()
    quiet = Store(store.data_dir, signing=False)
    layer = quiet.create_layer(owner['id'], {'kind': 'instructions', 'title': 'More', 'body': 'x', 'audience_users': [ship['id']]})
    with pytest.raises(ValueError, match='identity.json'):
        quiet.activate_layer(owner['id'], layer['id'], layer['version'])
    with quiet.transaction() as db:
        assert db.execute('SELECT active_revision FROM layers WHERE id=?', (layer['id'],)).fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 1
    assert not (store.data_dir / 'identity.json').exists()


def test_the_peer_tls_check_reads_an_old_or_missing_database_without_changing_it(tmp_path):
    """G4b, test 4c: `serve --peer-tls` checks before any Store opens, read-only. A database from before merge 3a (no
    revision_signatures table) and a missing one hold no signed records; neither is created or changed. One that can't
    be read gives a message naming it, not a traceback (plan review N1)."""
    import sqlite3
    from contextlib import closing
    from superyak_peer.signatures import refuse_a_lost_identity_before_the_store
    old = tmp_path / 'old'
    old.mkdir(mode=0o700)
    with closing(sqlite3.connect(old / 'peer.sqlite3')) as db:
        db.execute('CREATE TABLE users(id TEXT PRIMARY KEY)')
        db.commit()
    before = (old / 'peer.sqlite3').read_bytes()
    refuse_a_lost_identity_before_the_store(old)
    assert (old / 'peer.sqlite3').read_bytes() == before and sorted(p.name for p in old.iterdir()) == ['peer.sqlite3']
    missing = tmp_path / 'missing'
    refuse_a_lost_identity_before_the_store(missing)
    assert not missing.exists()
    junk = tmp_path / 'junk'  # unreadable, with no identity.json: it can't rule out signed records, so it refuses
    junk.mkdir(mode=0o700)
    (junk / 'peer.sqlite3').write_bytes(b'not a database, ' * 64)
    with pytest.raises(ValueError, match='peer.sqlite3'):
        refuse_a_lost_identity_before_the_store(junk)


def test_the_restore_test_passes_on_a_copy_holding_signed_records(tmp_path, monkeypatch, capsys):
    """G4b, test 4c: the copy holds a signed revision and has no identity file, so served as it is it would refuse to
    start (exit 22). The restore test gives its scratch directory a throwaway identity, removed with it."""
    from superyak_peer import backups
    from test_restore import restore_test as run_restore_test, runtime_dir
    run = runtime_dir(tmp_path, monkeypatch)
    store, owner, ship, room, docking = signed_station(tmp_path)
    store.send_message(owner['id'], room['id'], 'm1', 'hello')
    rotation = tmp_path / 'backups' / 'station'
    backups.run_backup(store.data_dir, rotation)
    assert run_restore_test('--backup-dir', rotation) == 0, capsys.readouterr().err
    assert capsys.readouterr().out.rstrip().endswith('; users 3, rooms 1, messages 1.')
    assert list(run.iterdir()) == []  # the scratch directory, and the throwaway identity in it, are gone
```

Two of these pass before this task, as guards: the no-signed-records test (G4 already behaves so) and the restore-test
test (nothing refuses a start yet). Step 5's mutations show each bites once the check exists. The lost-identity
message names `station-new-identity`, which Task 3 adds; naming it a commit early is harmless.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py`
Expected: 3 failed. The lost-identity test with `Failed: DID NOT RAISE ValueError` (a start without the file goes
on); the lazy-path test with `AssertionError: Regex pattern did not match` and `Actual message: 'Identity TLS files
differ from saved identity'` (the activation makes a new key, which the old TLS files then contradict); and the
`--peer-tls` test with `ImportError: cannot import name 'refuse_a_lost_identity_before_the_store'`.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/signatures.py`, replace the imports and the schema,

```python
import json
from .common import Problem, require
from .identity import PeerIdentity

SIGNATURE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(layer_id, revision));
'''
```

with:

```python
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from .common import Problem, require
from .identity import PeerIdentity

SIGNATURE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL, PRIMARY KEY(layer_id, revision));
'''
# G4b: the records a new identity would void, as (table, query). A table the database lacks (one from before merge 3a
# or 3b) holds none.
SIGNED_RECORDS = (('revision_signatures', 'SELECT 1 FROM revision_signatures LIMIT 1'),)
LOST_IDENTITY = ('The station identity {path} is missing, and this station holds signed records that a new identity would '
                 'void. Restore the file; if it is truly gone, run station-new-identity. Nothing was signed.')


def holds_signed_records(db):
    """G4b: whether the station holds any record SIGNED_RECORDS names."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return any(table in tables and db.execute(query).fetchone() is not None for table, query in SIGNED_RECORDS)


def refuse_a_lost_identity(data_dir, db):
    """G4b, the lost-identity check: identity.json missing (not a file, not a symlink) while the station holds signed
    records raises a ValueError naming the file."""
    path = Path(data_dir).absolute() / 'identity.json'
    if not path.exists() and not path.is_symlink() and holds_signed_records(db):
        raise ValueError(LOST_IDENTITY.format(path=path))


def refuse_a_lost_identity_before_the_store(data_dir):
    """G4b for `serve --peer-tls`, which checks before any Store opens: the database read-only, so nothing is created or
    migrated; a missing database holds no signed records. One that can't be read (say, a hot journal a read-only
    connection can't roll back) refuses with its name, since it can't rule signed records out."""
    database = Path(data_dir).absolute() / 'peer.sqlite3'
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
                refuse_a_lost_identity(data_dir, db)
        except sqlite3.Error as error:
            raise ValueError(f'{database} could not be read read-only ({type(error).__name__}), so the station cannot tell '
                             'whether it holds signed records; it will not start until the database can be read') from error
```

Replace `_load_station_identity` with:

```python
    def _load_station_identity(self):
        """G4: at a signing start, the identity file federation uses is loaded if it exists (a symlink too, which
        load_or_create refuses), and a store that can't load it doesn't start. A missing one waits for the first
        signature, so a new station's first `card --endpoint` still names its host (plan review M1), unless the station
        holds signed records: then it doesn't start either (G4b)."""
        path = self.data_dir / 'identity.json'
        if path.exists() or path.is_symlink():
            try:
                self._identity = PeerIdentity.load_or_create(self.data_dir)
            except Exception as error:
                raise ValueError(f'The station identity {path} could not be loaded ({type(error).__name__}); '
                                 'the station will not start until it is restored') from error
        else:
            with self.transaction() as db:
                refuse_a_lost_identity(self.data_dir, db)  # G4b: a lost identity is not replaced silently
```

In `_station_identity`, between `return self._station_identity(own)` and `self._identity =
PeerIdentity.load_or_create(self.data_dir)` (the one in `_station_identity`, not the one in `_load_station_identity`),
add, at the indentation of the line after it:

```python
            refuse_a_lost_identity(self.data_dir, db)  # G4b: never a new key over signed records, whoever opened the store
```

In `peer/superyak_peer/__main__.py`, in the `serve` branch's `if args.peer_tls:` block, between
`host = urlsplit(args.federation_endpoint).hostname if args.federation_endpoint else args.host` and
`identity = PeerIdentity.load_or_create(args.data_dir, hosts=...)`, add:

```python
                from .signatures import refuse_a_lost_identity_before_the_store
                refuse_a_lost_identity_before_the_store(args.data_dir)  # G4b: before the identity is loaded or made with its hosts
```

(`main` already turns a `ValueError` into exit 1 with its message.)

In `peer/superyak_peer/backups.py`, in `restore_test`, right before `server, port = _start(scratch)`, add:

```python
        from .identity import PeerIdentity  # here, as Store is below: backups.py stays standard library when imported
        PeerIdentity.load_or_create(scratch)  # G4b: a throwaway identity, so a copy holding signed records starts; removed with it
```

The import stays inside the function, as `restore_test`'s `Store` import does: backups.py's docstring and the backups
spec (S1) keep the module standard library only when it is imported, and `identity.py` imports `cryptography`.
(`tempfile.mkdtemp` made `scratch` mode 0700, and the `finally` removes it.)

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_restore.py tests/test_federation.py tests/test_cli.py tests/test_station_cli.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_signatures.py`, see the named test fail, restore:
- drop the `else:` branch of `_load_station_identity` → `test_a_lost_identity_is_not_replaced_silently`;
- drop the `refuse_a_lost_identity` line in `_station_identity` → `test_a_store_without_signing_refuses_to_sign_over_a_lost_identity`;
- drop the `refuse_a_lost_identity_before_the_store` line in `serve` → `test_a_lost_identity_is_not_replaced_silently`
  (serve makes a key, and the patched `uvicorn.run` records a start);
- `holds_signed_records` querying without the `table in tables` test → the `--peer-tls` test (the old database's
  `no such table` becomes a `ValueError`);
- `if True:` for `if database.is_file():` → the `--peer-tls` test (a read-only connection to a missing file fails,
  and the `ValueError` it becomes is unexpected there);
- drop the `except sqlite3.Error` clause → the `--peer-tls` test (`sqlite3.DatabaseError: file is not a database`, not
  a `ValueError`);
- `SIGNED_RECORDS` naming `layer_revisions` → `test_a_station_with_no_signed_records_still_creates_its_identity_at_the_first_signature` (and others);
- `if path.exists():` for `if path.exists() or path.is_symlink():` in `_load_station_identity` → 3a's `test_a_dangling_identity_symlink_does_not_start`;
- `LOST_IDENTITY` without `run station-new-identity` → `test_a_lost_identity_is_not_replaced_silently`;
- drop the throwaway identity line in `restore_test` → `test_the_restore_test_passes_on_a_copy_holding_signed_records` (exit 22).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/signatures.py peer/superyak_peer/__main__.py peer/superyak_peer/backups.py peer/tests/test_signatures.py
git commit -m "Grants 3b: a lost station identity is never replaced silently (G4b)"
```

---

### Task 3: A deliberate new identity (G4c)

**Files:**
- Modify: `peer/superyak_peer/__main__.py` (a helper before `main`; the `station-new-identity` command)
- Test: `peer/tests/test_signatures.py`

**Interfaces:**
- Consumes: `PeerIdentity.load_or_create`; `signed_station`, `run_cli` (Task 1's test helpers).
- Produces: `__main__.new_identity_for(data_dir, endpoint=None) -> str`, and the command
  `station-new-identity --data-dir DIR [--endpoint https://HOST:PORT]` (`--data-dir` required, no default).

- [ ] **Step 1: Write the failing test**

Append to `peer/tests/test_signatures.py`:

```python
def test_station_new_identity_is_the_one_deliberate_way_to_a_new_key(tmp_path, capsys, monkeypatch):
    """G4c, test 4c: refused while identity.json exists, and without --data-dir; with it lost (its TLS files left behind),
    it moves those aside, creates an identity whose certificate names the endpoint's host, says what changes, leaves the
    database byte for byte the same, and the station starts."""
    from cryptography import x509
    from superyak_peer.db import Store
    store, owner, ship, room, docking = signed_station(tmp_path)
    data, identity = store.data_dir, store.data_dir / 'identity.json'
    kept = identity.read_bytes()
    code, out, err = run_cli(capsys, 'station-new-identity', '--data-dir', data)
    assert code == 1 and 'exists' in err and identity.read_bytes() == kept
    monkeypatch.chdir(tmp_path)  # without --data-dir it refuses; a default would mint a key in the wrong directory
    code, out, err = run_cli(capsys, 'station-new-identity', '--endpoint', 'https://peer.example:7435')
    assert code == 2 and '--data-dir' in err and not (tmp_path / '.engram').exists()
    old_peer = store._station_identity().peer_id
    identity.unlink()  # lost; peer-cert.pem and peer-key.pem survive, as they usually do
    database = (data / 'peer.sqlite3').read_bytes()
    code, out, err = run_cli(capsys, 'station-new-identity', '--data-dir', data, '--endpoint', 'https://peer.example:7435')
    assert code == 0, err
    moved = sorted(path.name for path in data.glob('peer-*.pem.lost-*'))
    assert [name.split('.lost-')[0] for name in moved] == ['peer-cert.pem', 'peer-key.pem']
    new = PeerIdentity.load_or_create(data)
    assert new.peer_id != old_peer and new.peer_id in out
    for words in ('stops verifying', 'pair again', 'unverified', 'stopped'):
        assert words in out, words
    names = x509.load_pem_x509_certificate(new.certificate.encode()).extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert 'peer.example' in names
    assert (data / 'peer.sqlite3').read_bytes() == database
    assert Store(data)._station_identity().peer_id == new.peer_id  # the station starts, on the new key
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py -k new_identity`
Expected: 1 failed, with `assert (2 == 1)` (argparse: invalid choice `station-new-identity`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/__main__.py`, right before `def main(argv=None):`, add:

```python
NEW_IDENTITY = ('New station identity in {path}; the station\'s peer id is now {peer}. Every signature made with the lost '
                'key stops verifying against the new card. The peer id is the key\'s hash, so every paired peer must pair '
                'again with the new card, and replies this station already sent into remote rooms carry the old peer id and '
                'show as unverified. The lighthouse must be stopped while this runs: a running one keeps signing with the '
                'old key until it restarts. Nothing in the database was changed.')


def new_identity_for(data_dir, endpoint=None):
    """G4c: station-new-identity, the one deliberate way to a new key, for an identity.json that is truly lost. It
    refuses while the file exists, moves the lost identity's leftover TLS files aside (PeerIdentity refuses TLS files
    that differ), creates the identity as load_or_create does with the endpoint's host, and never opens the database.
    Returns what it tells Andy."""
    from .identity import PeerIdentity
    from urllib.parse import urlsplit
    import time
    directory = Path(data_dir).absolute()
    path = directory / 'identity.json'
    if path.exists() or path.is_symlink():
        raise ValueError(f'{path} exists, so nothing was changed: station-new-identity only replaces a lost identity')
    host = urlsplit(endpoint).hostname if endpoint else None
    if endpoint and (urlsplit(endpoint).scheme != 'https' or not host):
        raise ValueError('--endpoint is https://HOST:PORT')
    stamp, said = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()), []
    for name in ('peer-cert.pem', 'peer-key.pem'):
        leftover = directory / name
        if leftover.exists() or leftover.is_symlink():
            leftover.rename(directory / f'{name}.lost-{stamp}')
            said.append(f'Moved the lost identity\'s {name} aside to {name}.lost-{stamp}.')
    identity = PeerIdentity.load_or_create(directory, hosts=tuple(dict.fromkeys(['localhost', '127.0.0.1', *([host] if host else [])])))
    return '\n'.join([*said, NEW_IDENTITY.format(path=path, peer=identity.peer_id)])
```

In `main`, right before `notices = commands.add_parser('station-notices', ...)`, add:

```python
    new_identity = commands.add_parser('station-new-identity', help='Trusted local, with the lighthouse stopped: a new station '
                                       'identity on purpose, when identity.json is truly lost; every old signature stops verifying')
    new_identity.add_argument('--data-dir', type=Path, required=True)  # no default: never a key in the wrong place
    new_identity.add_argument('--endpoint', help='https://HOST:PORT, so the new certificate names the host (as card --endpoint does)')
```

and right before `elif args.command == 'demo':`, add:

```python
        elif args.command == 'station-new-identity':
            print(new_identity_for(args.data_dir, args.endpoint))
```

(`main` already turns a `ValueError` or `OSError` into exit 1 with its message; argparse exits 2 without `--data-dir`.)

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_cli.py tests/test_station_cli.py`
Expected: all pass.

- [ ] **Step 5: Check the test bites**

Apply each alone, run `tests/test_signatures.py -k new_identity`, see it fail, restore:
- drop `new_identity_for`'s exists refusal → it replaces a sound key;
- `default=Path('.engram/home')` for `required=True` on `--data-dir` → the run without `--data-dir` exits 0 and makes
  `.engram/home/identity.json` under the test's working directory (its `tmp_path`);
- `pass` for the `leftover.rename(...)` → `PeerIdentity` refuses the old TLS files;
- `hosts=('localhost', '127.0.0.1')` in `new_identity_for` → no `peer.example` in the certificate;
- `NEW_IDENTITY` without its re-pairing sentence → the warning check.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/__main__.py peer/tests/test_signatures.py
git commit -m "Grants 3b: station-new-identity, the one deliberate way to a new station key (G4c)"
```

---

### Task 4: The grants table, the policy, validity, and the grant's signature (G7, G9, G12's grant record)

**Files:**
- Create: `peer/superyak_peer/grants.py`
- Modify: `peer/superyak_peer/signatures.py` (`SIGNED_RECORDS`; `_grant_record`, `_sign_grant` at the end of the class)
- Modify: `peer/superyak_peer/db.py` (an import, the `Store` bases, the `executescript` list)
- Modify: `peer/pyproject.toml` (`"superyak_peer/grants.py",` after `"superyak_peer/files.py",` in both `only-include`
  lists; `"tests/test_grants.py",` after `"tests/test_federation.py",` in the sdist one)
- Modify: `peer/tests/test_restore.py` (`RECONCILED_TABLES`)
- Create: `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `encode`, `uid` (`common.py`); `safe_line` (`ships.py`); `_station_identity(db)` (Task 1);
  `PeerIdentity.sign_record`, `RECORD_KEYS['grant']` (3a).
- Produces:
  - `grants.GRANT_SCHEMA`, `grants.HOUR = 3600`, `grants.DAY = 86400`, `grants.short_id(grant_id) -> '#a1b2'`.
  - `Grants._grant_policy(self, db) -> dict` with keys `max_depth`, `max_expiry_hours`, `agent_grant_default_hours`,
    `builds_per_ship_per_day`, `delegable`, `grantees` (None is unrestricted).
  - `Grants._insert_grant(self, db, issuer_id, grantee_id, targets, rooms, hours, budget) -> str` (the grant id; stored
    and signed in the caller's transaction; the caller has checked every field). Task 6's `make_grant` calls it.
  - `Grants._grant_chain(self, db, grant) -> list[Row]` (the grant first, its root last).
  - `Grants._budget_used(self, db, grant_id, now) -> int`.
  - `Grants._grant_validity(self, db, grant) -> (bool, str | None)`.
  - `Signatures._grant_record(self, db, grant_id) -> dict | None`, `Signatures._sign_grant(self, db, grant_id) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_grants.py`:

```python
"""Grants (spec A step 3, merge 3b: G7-G14 of docs/superpowers/specs/2026-10-15-grants-step3-design.md)."""
import base64
import pytest
from superyak_peer.common import uid
from superyak_peer.grants import short_id
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_record
from test_instructions import docked
from test_signatures import card_of, raw_sign

DAY = 86400


def make(store, issuer, grantee, targets, rooms='*', hours=24, budget=5):
    """A grant stored through the store method POST /api/grants uses once its checks pass (G8): its id."""
    with store.transaction() as db:
        return store._insert_grant(db, issuer['id'], grantee['id'], [ship['id'] for ship in targets], rooms, hours, budget)


def validity(store, grant_id):
    with store.transaction() as db:
        return store._grant_validity(db, db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def charge(store, grant_id, *ages):
    """One budget use per age, that many seconds before now, each under its own ticket id."""
    with store.transaction() as db:
        for age in ages:
            db.execute('INSERT INTO budget_uses(grant_id, ticket_id, created) VALUES(?,?,?)', (grant_id, uid(), store.clock() - age))


def narrowed(store, monkeypatch, **changes):
    """Test 6: the policy narrowed after the grant was made, by replacing _grant_policy (G7's one function)."""
    defaults = type(store)._grant_policy
    monkeypatch.setattr(store, '_grant_policy', lambda db: {**defaults(store, db), **changes})


def revoke_by_hand(store, grant_id, by, reason='revoked'):
    with store.transaction() as db:
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                   (store.clock(), by and by['id'], reason, grant_id))


def test_a_new_grant_is_valid_and_its_short_id_is_four_characters(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    assert validity(store, grant) == (True, None)
    assert short_id(grant) == '#' + grant[:4] and len(short_id(grant)) == 5


def test_a_revoked_grant_names_who_revoked_it_even_once_expired(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    store.rename_user(users[0]['id'], 'Andy\n@serenity')  # a name is a person's text: one safe line in a reason
    grant = make(store, users[0], users[1], [ship], hours=1)
    revoke_by_hand(store, grant, users[0])
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    clock[0] += 3600  # expired too: the revoked reason comes first (test 6)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} was revoked by Andy (at)serenity')
    restored = make(store, users[0], users[1], [ship])
    revoke_by_hand(store, restored, None, 'restored')  # the restore reconcile records no person (G13)
    assert validity(store, restored) == (False, f'Grant #{restored[:4]} was revoked')


def test_a_grant_expires_at_its_expiry_time(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=1)  # made at 1000000.0, so it expires at 1003600.0
    clock[0] += 3599
    assert validity(store, grant) == (True, None)
    clock[0] += 1
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} expired 1970-01-12 14:46 UTC')


def test_a_narrowed_policy_takes_effect_at_the_next_check(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], hours=24)
    policy = f"Grant #{grant[:4]} is no longer allowed by the station's policy"
    for changes, expected in (({'max_expiry_hours': 24}, (True, None)),  # exactly its lifetime still fits
                              ({'max_expiry_hours': 23}, (False, f'Grant #{grant[:4]} lasts longer than the station now allows')),
                              ({'max_depth': 1}, (True, None)),  # a root is a chain of one link
                              ({'max_depth': 0}, (False, policy)),
                              ({'grantees': {users[1]['id']}}, (True, None)),
                              ({'grantees': {users[3]['id']}}, (False, policy))):
        narrowed(store, monkeypatch, **changes)
        assert validity(store, grant) == expected, changes


def test_the_budget_counts_builds_in_the_last_24_hours_only(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship], budget=2)
    charge(store, grant, DAY, DAY - 1)  # exactly 24 hours old no longer counts; a second younger does
    assert validity(store, grant) == (True, None)
    charge(store, grant, 0)
    assert validity(store, grant) == (False, f'Grant #{grant[:4]} has used its 2 builds for the last 24 hours')
    single = make(store, users[0], users[1], [ship], budget=1)
    charge(store, single, 10)
    assert validity(store, single) == (False, f'Grant #{single[:4]} has used its 1 build for the last 24 hours')


def test_an_issuer_who_no_longer_owns_every_target_holds_no_valid_grant(env):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    grant = make(store, users[0], users[1], [serenity, rio])
    with store.transaction() as db:  # by hand: ownership never changes today, but a restored or edited database could
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, grant) == (False, 'Patient no longer owns Rio Grande')


def test_the_first_check_that_fails_is_the_reason(env, monkeypatch):
    """G9's order, one pair of neighbours at a time: each grant fails two checks, and the earlier one is the reason."""
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    spent_and_lost = make(store, users[0], users[1], [rio], budget=1)  # 4 (budget) before 5 (ownership)
    charge(store, spent_and_lost, 10)
    with store.transaction() as db:
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (users[3]['id'], rio['id']))
    assert validity(store, spent_and_lost) == (False, f'Grant #{spent_and_lost[:4]} has used its 1 build for the last 24 hours')
    spent = make(store, users[0], users[1], [serenity], budget=1)  # 3 (policy) before 4 (budget)
    charge(store, spent, 10)
    narrowed(store, monkeypatch, max_depth=0)
    assert validity(store, spent) == (False, f"Grant #{spent[:4]} is no longer allowed by the station's policy")
    long = make(store, users[0], users[1], [serenity], hours=24)  # 2 (expired) before 3 (lifetime)
    narrowed(store, monkeypatch, max_expiry_hours=1)
    clock[0] += DAY
    assert validity(store, long) == (False, f'Grant #{long[:4]} expired 1970-01-13 13:46 UTC')


def grant_row(store, grant_id):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone())


def stored_grant_record(store, grant_id):
    with store.transaction() as db:
        return store._grant_record(db, grant_id)


def test_a_grants_signature_verifies_and_its_record_has_exactly_g12s_keys(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    serenity, _ = docked(store, users[0]['id'], 'serenity')
    rio, _ = docked(store, users[0]['id'], 'rio-grande')
    room = store.create_room(users[0]['id'], 'Ops', [users[1]['id']])
    grant = make(store, users[0], users[1], [serenity, rio], rooms=[room['id']], hours=48, budget=3)
    identity, record, signature = store._station_identity(), stored_grant_record(store, grant), grant_row(store, grant)['signature']
    card = card_of(identity)
    assert set(record) == RECORD_KEYS['grant']
    assert record == {'kind': 'grant', 'station': identity.peer_id, 'id': grant, 'issuer_id': users[0]['id'],
                      'grantee_id': users[1]['id'], 'actions': ['direct'], 'targets': [serenity['id'], rio['id']],
                      'rooms': [room['id']], 'expires': 1000000.0 + 48 * 3600, 'budget': 3, 'depth': 0, 'confirm': 'none',
                      'parent_id': None, 'charter_layer_id': None, 'charter_revision': None, 'follow': 0,
                      'created': 1000000.0}
    assert verify_record(card, record, signature)
    assert not verify_record(card, {**record, 'budget': 4}, signature)  # one changed value
    flipped = bytearray(base64.b64decode(signature))
    flipped[0] ^= 1
    assert not verify_record(card, record, base64.b64encode(bytes(flipped)).decode())
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))  # names another station
    added = {**record, 'session': 'x'}
    assert not verify_record(card, added, raw_sign(identity, added))  # a key a later step might add
    missing = {key: value for key, value in record.items() if key != 'follow'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    forged = {**record, 'station': '0' * 64}
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))  # peer id isn't the key's hash
    anywhere = make(store, users[0], users[1], [serenity])
    assert stored_grant_record(store, anywhere)['rooms'] == '*'  # '"*"' parsed, not the stored text
    assert verify_record(card, stored_grant_record(store, anywhere), grant_row(store, anywhere)['signature'])


def test_a_grant_whose_signing_fails_is_not_stored(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')

    def refuse(self, record):
        raise ValueError('no key')

    monkeypatch.setattr(PeerIdentity, 'sign_record', refuse)
    with pytest.raises(ValueError):
        make(store, users[0], users[1], [ship])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0  # signed in the insert's transaction, or not at all


def test_a_station_holding_grants_does_not_start_without_its_identity(tmp_path):
    """G4b, from merge 3b: a grant is a signed record, so a station holding one refuses to start without identity.json;
    and a new station's first grant still creates the identity (the row being signed doesn't count itself)."""
    from superyak_peer.db import Store
    store = Store(tmp_path / 'station')
    owner, other = store.create_user('owner', 'Owner', 'long-password'), store.create_user('other', 'Other', 'long-password')
    ship, _ = docked(store, owner['id'], 'serenity')
    assert not (store.data_dir / 'identity.json').exists()
    grant = make(store, owner, other, [ship])  # the station's first signature
    assert verify_record(card_of(PeerIdentity.load_or_create(store.data_dir)), stored_grant_record(store, grant),
                         grant_row(store, grant)['signature'])
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM revision_signatures').fetchone()[0] == 0  # the grant is the only record
    (store.data_dir / 'identity.json').unlink()
    with pytest.raises(ValueError, match='identity.json'):
        Store(store.data_dir)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: collection error, `ModuleNotFoundError: No module named 'superyak_peer.grants'`.

- [ ] **Step 3: Write the implementation**

Create `peer/superyak_peer/grants.py`:

```python
"""Grants (spec A step 3, merge 3b; docs/superpowers/specs/2026-10-15-grants-step3-design.md section 2, G7-G14): a
person lets another person direct some of his own ships, in some rooms, for some hours, with a daily budget of builds.
This module holds the tables, the policy, validity, making, revoking and reading. The station's signatures over grants
and revocations live in signatures.py, beside the revisions'. Merge 3c spends grants from tickets.py."""
from datetime import datetime, timezone
import json
from .common import encode, uid
from .ships import safe_line

GRANT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS grants(id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES users(id), grantee_id TEXT NOT NULL REFERENCES users(id), actions TEXT NOT NULL, targets TEXT NOT NULL, rooms TEXT NOT NULL, expires REAL NOT NULL, budget INTEGER NOT NULL, depth INTEGER NOT NULL, confirm TEXT NOT NULL, parent_id TEXT REFERENCES grants(id), charter_layer_id TEXT, charter_revision INTEGER, follow INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, revoked REAL, revoked_by TEXT REFERENCES users(id), revoke_reason TEXT, signature TEXT NOT NULL, revocation_signature TEXT);
CREATE TABLE IF NOT EXISTS budget_uses(grant_id TEXT NOT NULL REFERENCES grants(id), ticket_id TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS budget_uses_by_grant ON budget_uses(grant_id, created);
'''
HOUR, DAY = 3600, 86400


def short_id(grant_id):
    """G9: '#' and the first 4 characters of the id, as in spec A's footers."""
    return '#' + grant_id[:4]


def _utc(moment):
    return datetime.fromtimestamp(moment, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


class Grants:
    def _grant_policy(self, db):
        """G7: spec A's no-charter defaults. Every check reads the policy through this one function, so step 4 puts the
        charter behind it and validity doesn't change. `grantees` None is the unrestricted set."""
        return {'max_depth': 3, 'max_expiry_hours': 720, 'agent_grant_default_hours': 24, 'builds_per_ship_per_day': 20,
                'delegable': ['direct'], 'grantees': None}

    def _insert_grant(self, db, issuer_id, grantee_id, targets, rooms, hours, budget):
        """A root `direct` grant, stored and signed in the caller's transaction; the caller has checked every field (G8).
        Step 3 fixes actions, depth and confirm, and leaves parent_id, the charter columns and follow empty. The row holds
        an empty signature only until _sign_grant fills it, in this transaction (G12). Returns the grant's id."""
        key, now = uid(), self.clock()
        db.execute('INSERT INTO grants(id,issuer_id,grantee_id,actions,targets,rooms,expires,budget,depth,confirm,created,'
                   "signature) VALUES(?,?,?,?,?,?,?,?,0,'none',?,'')",
                   (key, issuer_id, grantee_id, encode(['direct']), encode(targets), encode(rooms), now + hours * HOUR,
                    budget, now))
        self._sign_grant(db, key)
        return key

    def _grant_chain(self, db, grant):
        """G9: the links from this grant up to its root, this grant first. In step 3 every grant is its own root; step 5
        adds parents. A seen set ends a cycle made by hand."""
        chain, seen = [grant], {grant['id']}
        while chain[-1]['parent_id'] is not None:
            parent = db.execute('SELECT * FROM grants WHERE id=?', (chain[-1]['parent_id'],)).fetchone()
            if parent is None or parent['id'] in seen:
                break
            chain.append(parent)
            seen.add(parent['id'])
        return chain

    def _budget_used(self, db, grant_id, now):
        """Builds charged to a grant in the last 24 hours. A use exactly 24 hours old no longer counts (G9, test 6)."""
        return db.execute('SELECT count(*) FROM budget_uses WHERE grant_id=? AND created>?',
                          (grant_id, now - DAY)).fetchone()[0]

    def _grant_validity(self, db, grant):
        """G9: (True, None), or (False, the reason of the first check that fails). Each link, from the grant up to its
        root, is checked in the spec's order: 1 revoked, 2 expired, 3 the policy in force now (lifetime, chain length,
        grantee set), 4 budget, 5 the root's issuer still owns every target. Names are the station's own, through
        safe_line."""
        now, policy = self.clock(), self._grant_policy(db)
        chain = self._grant_chain(db, grant)
        root = chain[-1]
        for link in chain:
            short = short_id(link['id'])
            if link['revoked'] is not None:
                by = db.execute('SELECT name FROM users WHERE id=?', (link['revoked_by'],)).fetchone() if link['revoked_by'] else None
                return False, f'Grant {short} was revoked' + (f' by {safe_line(by["name"])}' if by else '')
            if now >= link['expires']:
                return False, f'Grant {short} expired {_utc(link["expires"])}'
            if link['expires'] - link['created'] > policy['max_expiry_hours'] * HOUR:
                return False, f'Grant {short} lasts longer than the station now allows'
            if len(chain) > policy['max_depth'] or (policy['grantees'] is not None and link['grantee_id'] not in policy['grantees']):
                return False, f"Grant {short} is no longer allowed by the station's policy"
            if self._budget_used(db, link['id'], now) >= link['budget']:
                builds = f'{link["budget"]} build' + ('' if link['budget'] == 1 else 's')
                return False, f'Grant {short} has used its {builds} for the last 24 hours'
            for ship_id in json.loads(link['targets']):
                ship = db.execute('SELECT name, owner_id FROM users WHERE id=?', (ship_id,)).fetchone()
                if ship is None or ship['owner_id'] != root['issuer_id']:
                    issuer = db.execute('SELECT name FROM users WHERE id=?', (root['issuer_id'],)).fetchone()
                    return False, f'{safe_line(issuer["name"])} no longer owns {safe_line(ship["name"]) if ship else "a ship that is gone"}'
        return True, None
```

In `peer/superyak_peer/signatures.py`, replace

```python
SIGNED_RECORDS = (('revision_signatures', 'SELECT 1 FROM revision_signatures LIMIT 1'),)
```

with:

```python
SIGNED_RECORDS = (('revision_signatures', 'SELECT 1 FROM revision_signatures LIMIT 1'),
                  # a grant's row holds an empty signature only inside the transaction that inserts and signs it, which
                  # mustn't count itself: the first grant on a new station creates the identity (G4)
                  ('grants', "SELECT 1 FROM grants WHERE signature!='' LIMIT 1"))
```

change the module docstring's last sentence, which spans a line break (`... Merge 3b adds grants` ends the second
line, and the third is `and revocations here."""`), so that the third line reads `and revocations here (G12)."""`;
and append to `class Signatures`:

```python
    def _grant_record(self, db, grant_id):
        """G12: a grant's record, with exactly RECORD_KEYS['grant'], from its stored row: actions, targets and rooms as
        parsed JSON values, not their stored text. Columns a later step adds stay out, so old signatures keep verifying.
        None for no such grant."""
        row = db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone()
        if row is None:
            return None
        return {'kind': 'grant', 'station': self._station_identity(db).peer_id, 'id': row['id'],
                'issuer_id': row['issuer_id'], 'grantee_id': row['grantee_id'], 'actions': json.loads(row['actions']),
                'targets': json.loads(row['targets']), 'rooms': json.loads(row['rooms']), 'expires': row['expires'],
                'budget': row['budget'], 'depth': row['depth'], 'confirm': row['confirm'], 'parent_id': row['parent_id'],
                'charter_layer_id': row['charter_layer_id'], 'charter_revision': row['charter_revision'],
                'follow': row['follow'], 'created': row['created']}

    def _sign_grant(self, db, grant_id):
        """G12: in the transaction that inserts the grant. The record is built from the stored row, the one grant_signed
        serves, so what was signed and what is served can't drift apart."""
        db.execute('UPDATE grants SET signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._grant_record(db, grant_id)), grant_id))
```

In `peer/superyak_peer/db.py`:
- after `from .signatures import Signatures, SIGNATURE_SCHEMA`, add `from .grants import Grants, GRANT_SCHEMA`;
- the `Store` bases end `..., RoomBoard, Breakouts, Signatures, Grants):`;
- the `executescript(...)` argument ends `+ BREAKOUT_SCHEMA + SIGNATURE_SCHEMA + GRANT_SCHEMA)`.

In `peer/pyproject.toml`, add `"superyak_peer/grants.py",` after `"superyak_peer/files.py",` in both `only-include`
lists, and `"tests/test_grants.py",` after `"tests/test_federation.py",` in the sdist one.

In `peer/tests/test_restore.py`, the last line of `RECONCILED_TABLES` becomes
`    'account_role_changes', 'room_briefs', 'grants', 'budget_uses'}` (R9: the guard test fails the moment the schema
has a table in neither list; Task 8 makes the reconcile read and change both).

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py tests/test_signatures.py tests/test_restore.py tests/test_packaging.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grants.py` (and the file named), see the named test fail, restore:
- `created>=?` in `_budget_used` → `test_the_budget_counts_builds_in_the_last_24_hours_only`;
- `720 * HOUR` for `policy['max_expiry_hours'] * HOUR` → `test_a_narrowed_policy_takes_effect_at_the_next_check`;
- `len(chain) >= policy['max_depth']` → the same test;
- drop the grantee-set clause → the same test;
- `> link['budget']` for `>= link['budget']` → the budget test and the order test;
- `now > link['expires']` → `test_a_grant_expires_at_its_expiry_time` and the order test;
- `by["name"]` without `safe_line` → `test_a_revoked_grant_names_who_revoked_it_even_once_expired`;
- check only `json.loads(link['targets'])[:1]` → `test_an_issuer_who_no_longer_owns_every_target_holds_no_valid_grant`;
- swap checks 1 and 2 → the revoked test; swap 2 and 3, 3 and 4, or 4 and 5 → `test_the_first_check_that_fails_is_the_reason`;
- `'targets': row['targets']` (or `'rooms': row['rooms']`) in `_grant_record` → the record test;
- drop `self._sign_grant(db, key)` → the record test and the signing-fails test;
- wrap `self._sign_grant(db, key)` in `try: ... except ValueError: pass` → `test_a_grant_whose_signing_fails_is_not_stored`;
- drop the grants pair from `SIGNED_RECORDS` → `test_a_station_holding_grants_does_not_start_without_its_identity`;
- `"SELECT 1 FROM grants LIMIT 1"` (every row counted) → the same test, at the first grant;
- drop `"superyak_peer/grants.py",` from the wheel list → `tests/test_packaging.py::test_fresh_extraction_builds_static_wheel_and_starts_without_parent_repo`
  (`ModuleNotFoundError: No module named 'superyak_peer.grants'`);
- drop `'grants', 'budget_uses'` from `RECONCILED_TABLES` → `tests/test_restore.py::test_every_table_is_either_reconciled_or_named_coordination`.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/signatures.py peer/superyak_peer/db.py peer/pyproject.toml peer/tests/test_restore.py peer/tests/test_grants.py
git commit -m "Grants 3b: the grants table, the policy, validity and the grant's signature (G7, G9, G12)"
```

---

### Task 5: Reading grants, their signed records and the people list (G11, G12's route, G21's route, G14)

**Files:**
- Modify: `peer/superyak_peer/grants.py` (an import, one constant, eight methods at the end of the class)
- Modify: `peer/superyak_peer/signatures.py` (`grant_signed` at the end of the class)
- Modify: `peer/superyak_peer/app.py` (three routes after `/api/layers/{key}/revisions/{revision}/signed`)
- Test: `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `_grant_chain`, `_grant_validity`, `_budget_used`, `_grant_policy`, `short_id` (Task 4); `_grant_record`
  (Task 4); `Ships._person`; `actor()` in `app.py`.
- Produces:
  - `grants.NOT_IN_ROOM = 'a room you are not in'`.
  - `Grants._owns_a_target(db, actor, grant) -> bool`, `Grants._grant_visible(db, actor, grant) -> bool`,
    `Grants._visible_grant(db, actor, grant_id) -> Row` (404 otherwise), `Grants._room_label(db, actor, room_id) -> str`,
    `Grants._current_room(db, room_id) -> str | None`, `Grants._grant_view(db, actor, grant) -> dict`.
  - `Grants.list_grants(actor) -> list[dict]`, `Grants.grant_people(actor) -> list[{id, name}]`,
    `Signatures.grant_signed(actor, grant_id) -> {station, record, signature}` (Task 7 adds `revocation`).
  - Routes `GET /api/grants`, `GET /api/grants/people`, `GET /api/grants/{key}/signed`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_grants.py`, change `from test_instructions import docked` to
`from test_instructions import docked, ship_client`, then append:

```python
def listed(client):
    response = client.get('/api/grants')
    assert response.status_code == 200, response.text
    return response.json()


def ids(client):
    return [grant['id'] for grant in listed(client)]


def test_each_person_sees_the_grants_they_issued_hold_or_that_cover_their_ships(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    held = make(store, patient, doctor, [serenity])
    clock[0] += 1
    covering = make(store, patient, doctor, [rio])
    with store.transaction() as db:  # by hand: in step 3 a ship's owner is its grants' issuer
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], rio['id']))
    assert ids(clients[0]) == [covering, held]  # the issuer, newest first
    assert ids(clients[1]) == [covering, held]  # the grantee
    assert ids(clients[3]) == [covering]  # rio-grande's owner now
    assert ids(clients[2]) == []  # an admin with no tie sees nothing
    card = card_of(store._station_identity())
    for client, grant in ((clients[0], held), (clients[1], held), (clients[3], covering)):
        signed = client.get(f'/api/grants/{grant}/signed')
        assert signed.status_code == 200, signed.text
        assert set(signed.json()) == {'station', 'record', 'signature'} and signed.json()['record']['id'] == grant
        assert signed.json()['station'] == store._station_identity().peer_id
        assert verify_record(card, signed.json()['record'], signed.json()['signature'])
    for client, grant in ((clients[3], held), (clients[2], held), (clients[2], covering), (clients[0], 'no-such-grant')):
        assert client.get(f'/api/grants/{grant}/signed').status_code == 404, grant


def test_a_grant_shows_its_people_ships_rooms_budget_and_validity(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    ops = store.create_room(patient['id'], 'Ops', [doctor['id'], serenity['id']])
    grant = make(store, patient, doctor, [serenity, rio], rooms=[ops['id']], hours=24, budget=5)
    other = make(store, patient, family, [serenity])
    charge(store, grant, 10, 20, DAY)  # two in the last 24 hours; one exactly 24 hours old, which no longer counts
    sent = [store.send_message(patient['id'], ops['id'], f'm{n}', f'@serenity {n}')['id'] for n in range(5)]
    with store.transaction() as db:  # serenity's tickets, as merge 3c will write them: two grant builds count
        for message, mode, basis, age in ((sent[0], 'build', 'grant', 10), (sent[1], 'build', 'grant', DAY - 1),
                                          (sent[2], 'build', 'grant', DAY), (sent[3], 'build', 'owner', 10),
                                          (sent[4], 'read', 'none', 10)):
            db.execute("INSERT INTO tickets(id,ship_id,message_id,mode,basis,status,created) VALUES(?,?,?,?,?,'finished',?)",
                       (uid(), serenity['id'], message, mode, basis, clock[0] - age))
    views = {view['id']: view for view in listed(clients[0])}
    assert views[grant] == {
        'id': grant, 'short': '#' + grant[:4], 'issuer': {'id': patient['id'], 'name': 'Patient'},
        'grantee': {'id': doctor['id'], 'name': 'Doctor'},
        'targets': [{'id': serenity['id'], 'name': 'Serenity', 'ship_builds_left': 18},
                    {'id': rio['id'], 'name': 'Rio Grande', 'ship_builds_left': 20}],
        'rooms': [{'id': ops['id'], 'title': 'Ops'}], 'expires': 1000000.0 + DAY, 'budget': 5, 'budget_left': 3,
        'created': 1000000.0, 'revoked': None, 'revoked_by': None, 'revoke_reason': None, 'valid': True}
    assert views[other]['targets'] == [{'id': serenity['id'], 'name': 'Serenity', 'ship_builds_left': 18}]  # every grant's
    assert views[other]['rooms'] == '*' and views[other]['budget_left'] == 5
    charge(store, other, *range(1, 8))  # more uses than its budget (only by hand): none left, never fewer
    revoke_by_hand(store, grant, patient, 'Done for now')
    views = {view['id']: view for view in listed(clients[1])}
    assert views[grant]['valid'] is False and views[grant]['reason'] == f'Grant #{grant[:4]} was revoked by Patient'
    assert (views[grant]['revoked'], views[grant]['revoked_by'], views[grant]['revoke_reason']) == \
        (1000000.0, {'id': patient['id'], 'name': 'Patient'}, 'Done for now')
    views = {view['id']: view for view in listed(clients[0])}
    assert views[other]['budget_left'] == 0 and views[other]['reason'].endswith('has used its 5 builds for the last 24 hours')


def test_room_titles_show_only_to_members_and_a_replaced_room_shows_the_current_one(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    ops = store.create_room(patient['id'], 'Ops', [doctor['id']])
    plans = store.create_room(patient['id'], 'Plans', [doctor['id']])
    grant = make(store, patient, doctor, [serenity], rooms=[ops['id'], plans['id']])
    removed = clients[0].delete(f'/api/chats/{ops["id"]}/participants/{doctor["id"]}')  # the room's owner removes the grantee
    assert removed.status_code == 200, removed.text
    second = clients[0].post(f'/api/chats/{plans["id"]}/participants', json={'member_ids': [family['id']]}).json()
    third = clients[0].post(f'/api/chats/{second["id"]}/participants', json={'member_ids': [organizer['id']]}).json()
    current = {'id': third['id'], 'title': 'Plans'}  # Plans was replaced twice: the grant covers the newest
    assert listed(clients[1])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'a room you are not in'}, {'id': plans['id'], 'title': 'Plans', 'current': current}]
    assert listed(clients[0])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'Ops'}, {'id': plans['id'], 'title': 'Plans', 'current': current}]
    with store.transaction() as db:  # by hand, so serenity's new owner sees the grant: added later, never in Plans itself
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], serenity['id']))
    assert listed(clients[3])[0]['rooms'] == [
        {'id': ops['id'], 'title': 'a room you are not in'},
        {'id': plans['id'], 'title': 'a room you are not in', 'current': current}]
    loop_a = store.create_room(patient['id'], 'Loop A', [doctor['id']])
    loop_b = store.create_room(patient['id'], 'Loop B', [doctor['id']])
    with store.transaction() as db:  # a linked_room_id cycle, made by hand, ends the walk: no current room
        db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (loop_b['id'], loop_a['id']))
        db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (loop_a['id'], loop_b['id']))
    looped = make(store, patient, doctor, [serenity], rooms=[loop_a['id']])
    shown = next(view for view in listed(clients[0]) if view['id'] == looped)
    assert shown['rooms'] == [{'id': loop_a['id'], 'title': 'Loop A'}]


def test_the_people_list_has_active_people_only(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    docked(store, patient['id'], 'serenity')
    store.create_station_ship('odo', 'Odo')  # a resident
    store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')  # awaiting activation
    with store.transaction() as db:
        db.execute("INSERT INTO peers(peer_id, card, paired) VALUES(?, '{}', 1)", ('ab' * 32,))
        db.execute("INSERT INTO remote_contacts(id, peer_id, user_id, name) VALUES('contact-1', ?, 'remote-user', 'Aaron')",
                   ('ab' * 32,))
    people = clients[0].get('/api/grants/people')
    assert people.status_code == 200, people.text
    assert people.json() == [{'id': doctor['id'], 'name': 'Doctor'}, {'id': family['id'], 'name': 'Family'},
                             {'id': organizer['id'], 'name': 'Organizer'}]  # by name; no caller, ship, resident, system author


def test_a_ship_key_gets_403_on_every_grants_route(env):
    """G14: every /api/grants route takes a person session only (spec A Testing 3). The body is current_user's own
    refusal, so no store-level check can be what refused the ship."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    routes = [('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None)]
    for method, path, body in routes:
        response = ship_client(app, key).request(method, path, json=body)
        assert (response.status_code, response.json()) == (403, {'error': 'Ship keys cannot use this route'}), (method, path)
```

Tasks 6 and 7 add `POST /api/grants` and `POST /api/grants/{id}/revoke` to that `routes` list.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: the five new tests fail, four with `AssertionError: {"detail":"Not Found"}` / `assert 404 == 200` (no route
yet) and the ship-key test with `assert (404, {'detail': 'Not Found'}) == (403, {...})`; Task 4's tests pass.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, change `from .common import encode, uid` to `from .common import Problem, encode, uid`;
after `HOUR, DAY = 3600, 86400` add:

```python
NOT_IN_ROOM = 'a room you are not in'  # G11: the title anyone outside a listed room sees
```

and append to `class Grants`:

```python
    def _owns_a_target(self, db, actor, grant):
        ships = json.loads(grant['targets'])
        marks = ','.join('?' * len(ships))
        return bool(ships) and db.execute(f"SELECT 1 FROM users WHERE kind='ship' AND owner_id=? AND id IN ({marks})",
                                          (actor, *ships)).fetchone() is not None

    def _grant_visible(self, db, actor, grant):
        """G11: the caller issued it (or a grant above it, so G10's issuer above can reach it; in step 3 every grant is its
        own root), holds it, or owns one of its ships. No one else sees a grant, an admin included."""
        return (grant['grantee_id'] == actor or any(link['issuer_id'] == actor for link in self._grant_chain(db, grant))
                or self._owns_a_target(db, actor, grant))

    def _visible_grant(self, db, actor, grant_id):
        """The grant, or 404 when there is none or G11 doesn't show it to the caller: the same answer, so no route says
        whether a grant exists."""
        grant = db.execute('SELECT * FROM grants WHERE id=?', (grant_id,)).fetchone() if isinstance(grant_id, str) else None
        if grant is None or not self._grant_visible(db, actor, grant):
            raise Problem(404, 'Not found')
        return grant

    def _room_label(self, db, actor, room_id):
        """G11: a room's title for its members only; anyone else sees NOT_IN_ROOM."""
        row = db.execute('SELECT rooms.title FROM rooms JOIN room_members ON room_members.room_id=rooms.id '
                         'WHERE rooms.id=? AND room_members.user_id=?', (room_id, actor)).fetchone()
        return row['title'] if row else NOT_IN_ROOM

    def _current_room(self, db, room_id):
        """G11: the current room a replaced room now covers, following linked_room_id forward (S5); None for a current
        room. add_participants never forks a chain (work board 8.4), so a fork or a cycle (only an older or hand-edited
        database has one) ends the walk with None too."""
        key, seen = room_id, {room_id}
        while True:
            later = db.execute('SELECT id FROM rooms WHERE linked_room_id=?', (key,)).fetchall()
            if not later:
                return None if key == room_id else key
            if len(later) > 1 or later[0]['id'] in seen:
                return None
            key = later[0]['id']
            seen.add(key)

    def _grant_view(self, db, actor, grant):
        """G11: a grant as its issuer, grantee and target owners see it. Names and titles are people's text, sent as they
        are; the web app escapes them. `reason` is there only when the grant is not valid."""
        now, policy = self.clock(), self._grant_policy(db)

        def person(user_id):
            if user_id is None:
                return None
            row = db.execute('SELECT name FROM users WHERE id=?', (user_id,)).fetchone()
            return {'id': user_id, 'name': row['name'] if row else None}

        targets = []
        for ship_id in json.loads(grant['targets']):
            # G11: the ship's grant builds in the last 24 hours, under every grant. Merge 3c writes these tickets.
            built = db.execute("SELECT count(*) FROM tickets WHERE ship_id=? AND mode='build' AND basis='grant' AND created>?",
                               (ship_id, now - DAY)).fetchone()[0]
            targets.append({**person(ship_id), 'ship_builds_left': max(0, policy['builds_per_ship_per_day'] - built)})
        rooms = json.loads(grant['rooms'])
        if rooms != '*':
            listed = []
            for room_id in rooms:
                entry, current = {'id': room_id, 'title': self._room_label(db, actor, room_id)}, self._current_room(db, room_id)
                if current is not None:
                    entry['current'] = {'id': current, 'title': self._room_label(db, actor, current)}
                listed.append(entry)
            rooms = listed
        valid, reason = self._grant_validity(db, grant)
        view = {'id': grant['id'], 'short': short_id(grant['id']), 'issuer': person(grant['issuer_id']),
                'grantee': person(grant['grantee_id']), 'targets': targets, 'rooms': rooms, 'expires': grant['expires'],
                'budget': grant['budget'], 'budget_left': max(0, grant['budget'] - self._budget_used(db, grant['id'], now)),
                'created': grant['created'], 'revoked': grant['revoked'], 'revoked_by': person(grant['revoked_by']),
                'revoke_reason': grant['revoke_reason'], 'valid': valid}
        if not valid:
            view['reason'] = reason
        return view

    def list_grants(self, actor):
        """G11: GET /api/grants, newest first. A station holds tens of grants, so each is checked here in Python, through
        the one visibility rule the other routes use."""
        with self.transaction() as db:
            rows = db.execute('SELECT * FROM grants ORDER BY created DESC, id DESC').fetchall()
            return [self._grant_view(db, actor, row) for row in rows if self._grant_visible(db, actor, row)]

    def grant_people(self, actor):
        """G21's person list (GET /api/grants/people): this station's active people other than the caller, by name.
        Ships, residents, the system author, accounts awaiting activation and remote contacts are never in it."""
        with self.transaction() as db:
            self._person(db, actor)
            return [dict(row) for row in db.execute("SELECT id, name FROM users WHERE kind='person' AND activation_pending=0 "
                                                    'AND id!=? ORDER BY name, id', (actor,))]
```

In `peer/superyak_peer/signatures.py`, append to `class Signatures`:

```python
    def grant_signed(self, actor, grant_id):
        """G12: GET /api/grants/{id}/signed, {station, record, signature} for anyone G11 shows the grant to; anyone else,
        and an unknown id, gets 404."""
        with self.transaction() as db:
            grant = self._visible_grant(db, actor, grant_id)
            return {'station': self._station_identity(db).peer_id, 'record': self._grant_record(db, grant['id']),
                    'signature': grant['signature']}
```

In `peer/superyak_peer/app.py`, right after the `revision_signed` route (`@app.get('/api/layers/{key}/revisions/{revision}/signed')`
and its two lines), add:

```python
    @app.get('/api/grants')
    def grants(request: Request):
        return store.list_grants(actor(request))  # G14: a person only; current_user gives a ship key 403

    @app.get('/api/grants/people')
    def grant_people(request: Request):
        return store.grant_people(actor(request))

    @app.get('/api/grants/{key}/signed')
    def grant_signed(key: str, request: Request):
        return store.grant_signed(actor(request), key)
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grants.py`, see the named test fail, restore:
- drop `or self._owns_a_target(db, actor, grant)` from `_grant_visible` → the visibility test (rio-grande's owner sees nothing) and the rooms test;
- drop `grant['grantee_id'] == actor or` → the visibility, fields and rooms tests;
- replace the chain walk in `_grant_visible` with nothing (`False`) → the visibility test (the issuer sees only the grant over a ship it still owns);
- let admins see every grant (`is_admin or ...`) → the visibility test;
- `ORDER BY created, id` → the visibility test (oldest first);
- `_room_label` returning the title to anyone → the rooms test;
- `_current_room` returning after one step forward → the rooms test (`second`, not `third`);
- `budget_left` counting every use ever, or without `max(0, ...)` → the fields test;
- count every build ticket (drop `AND basis='grant'`), or `created>=?` there → the fields test (`ship_builds_left` 17);
- the people query without `activation_pending=0`, with `kind!='system'` for `kind='person'`, without `id!=?`, or
  `ORDER BY created, id` → the people test;
- `view['reason'] = reason` always → the fields test (a `reason: None` key appears);
- `member(request)['id']` for `actor(request)` in the list route → the ship-key test (200, not 403);
- `grant_signed` reading the row without `_visible_grant` → the visibility test (others get 200).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/signatures.py peer/superyak_peer/app.py peer/tests/test_grants.py
git commit -m "Grants 3b: reading grants, their signed records and the people list (G11, G12, G14)"
```

---

### Task 6: Making a grant (G8, G14)

**Files:**
- Modify: `peer/superyak_peer/grants.py` (an import, constants, two helpers, four methods at the end of the class)
- Modify: `peer/superyak_peer/app.py` (one route, before `@app.get('/api/grants/people')`)
- Test: `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `REPLACED_ROOMS` (`common.py`); `Breakouts._breakout`; `Ships._person`; `_grant_policy`, `_insert_grant`
  (Task 4); `_grant_view` (Task 5).
- Produces:
  - `grants.MAX_LISTED = 20`, `grants.MAX_BUDGET = 500`, and one message per refusal: `ROOMS_SHAPE`, `ROOM_NOT_YOURS`,
    `ROOM_REPLACED`, `ROOM_WITHOUT_GRANTEE`, `GRANTEE_NOT_PERSON`, `GRANTEE_IS_YOU`, `TARGETS_SHAPE`, `TARGET_NOT_YOURS`,
    `BUDGET_RANGE` (the hours message carries the policy's maximum).
  - `Grants.make_grant(actor, grantee, targets, rooms, hours, budget) -> dict` (G11's view); route `POST /api/grants`
    (201).

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_grants.py`, add `from superyak_peer import grants as G` above `from superyak_peer.grants import short_id`;
in `test_a_ship_key_gets_403_on_every_grants_route`, replace

```python
    routes = [('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None)]
```

with:

```python
    made = {'grantee': users[1]['id'], 'targets': [ship['id']], 'rooms': '*', 'hours': 24, 'budget': 5}
    routes = [('POST', '/api/grants', made), ('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None)]
```

and append:

```python
def fleet(store, owner_id, count):
    """count ships owned by owner_id, written directly (docking allows 20 an hour, and scrypt is slow): their ids."""
    with store.transaction() as db:
        ships = [uid() for _ in range(count)]
        db.executemany("INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind,owner_id) "
                       "VALUES(?,?,?,?,?,0,?,'ship',?)",
                       [(ship, f'fleet-{n}', f'Fleet {n}', b'\0' * 16, b'\0' * 32, store.clock(), owner_id)
                        for n, ship in enumerate(ships)])
    return ships


@pytest.fixture
def station(env, tmp_path):
    """Test 5's station: patient makes grants to doctor. Every refused room is one the caller (and, where it matters,
    the grantee) is in by hand, so the check named is the only one that can refuse it."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    rio, _ = docked(store, patient['id'], 'rio-grande')
    theirs, _ = docked(store, doctor['id'], 'jenn-ship')
    odo = store.create_station_ship('odo', 'Odo')
    pending = store.bootstrap_super_admin('root', 'Root', tmp_path / 'activation.json')
    shared = store.create_room(patient['id'], 'Ops', [doctor['id'], serenity['id'], rio['id']])
    alone = store.create_room(patient['id'], 'Alone', [])
    elsewhere = store.create_room(family['id'], 'Elsewhere', [doctor['id']])
    old = store.create_room(patient['id'], 'Old', [doctor['id']])
    store.add_participants(patient['id'], old['id'], [family['id']])  # Old is replaced now
    side = store.open_breakout(serenity['id'], 'Side', ['rio-grande'])
    remote = 'ab' * 32 + ':room-1'
    with store.transaction() as db:
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)', [(side['id'], patient['id']), (side['id'], doctor['id'])])
        db.execute('INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES(?,?,?,1,NULL)', (remote, patient['id'], 'Remote'))
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)', [(remote, patient['id']), (remote, doctor['id'])])
        system = store.system_author_id(db)
    good = {'grantee': doctor['id'], 'targets': [serenity['id']], 'rooms': [shared['id']], 'hours': 24, 'budget': 5}
    return dict(app=app, clients=clients, users=users, clock=clock, store=store, serenity=serenity, rio=rio,
                theirs=theirs, odo=odo, pending=pending, shared=shared, alone=alone, elsewhere=elsewhere, old=old,
                side=side, remote=remote, system=system, good=good)


def answer(station, client=None, **changes):
    response = (client or station['clients'][0]).post('/api/grants', json={**station['good'], **changes})
    return response.status_code, response.json().get('error')


def test_making_a_grant_refuses_each_bad_field_with_its_status(station):
    s = station
    patient, doctor, organizer, family = s['users']
    for rooms in (['no-such-room'], [s['remote']], [s['side']['id']], [s['elsewhere']['id']]):
        assert answer(s, rooms=rooms) == (404, G.ROOM_NOT_YOURS), rooms  # the same body for each (G8 step 1)
    hours = 'hours is a whole number from 1 to 720'
    for changes, error in (
            ({'rooms': [s['old']['id']]}, G.ROOM_REPLACED), ({'rooms': [s['alone']['id']]}, G.ROOM_WITHOUT_GRANTEE),
            ({'rooms': [s['shared']['id'], s['shared']['id']]}, G.ROOMS_SHAPE), ({'rooms': []}, G.ROOMS_SHAPE),
            ({'rooms': 'everywhere'}, G.ROOMS_SHAPE), ({'rooms': [5]}, G.ROOMS_SHAPE),
            ({'rooms': '*', 'grantee': patient['id']}, G.GRANTEE_IS_YOU),
            ({'rooms': '*', 'grantee': s['serenity']['id']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': s['system']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': s['pending']['id']}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': 'no-such-person'}, G.GRANTEE_NOT_PERSON),
            ({'rooms': '*', 'grantee': ['x']}, G.GRANTEE_NOT_PERSON),
            ({'targets': [s['theirs']['id']]}, G.TARGET_NOT_YOURS), ({'targets': [s['odo']['id']]}, G.TARGET_NOT_YOURS),
            ({'targets': ['no-such-ship']}, G.TARGET_NOT_YOURS), ({'targets': [doctor['id']]}, G.TARGET_NOT_YOURS),
            ({'targets': [s['serenity']['id'], s['serenity']['id']]}, G.TARGETS_SHAPE), ({'targets': []}, G.TARGETS_SHAPE),
            ({'targets': s['serenity']['id']}, G.TARGETS_SHAPE),
            ({'hours': 0}, hours), ({'hours': 721}, hours), ({'hours': 1.5}, hours), ({'hours': True}, hours),
            ({'hours': '24'}, hours), ({'hours': None}, hours),
            ({'budget': 0}, G.BUDGET_RANGE), ({'budget': 501}, G.BUDGET_RANGE), ({'budget': 2.0}, G.BUDGET_RANGE),
            ({'budget': True}, G.BUDGET_RANGE), ({'budget': '5'}, G.BUDGET_RANGE)):
        assert answer(s, **changes) == (400, error), changes
    admin = {'rooms': '*', 'targets': [s['serenity']['id']]}  # an admin's power never reaches another person's ships
    assert answer(s, s['clients'][2], **admin) == (400, G.TARGET_NOT_YOURS)
    with s['store'].transaction() as db:
        assert db.execute('SELECT count(*) FROM grants').fetchone()[0] == 0


def test_making_a_grant_checks_in_the_spec_order(station):
    """G8's order, rooms first: each request fails two steps, and the earlier one answers."""
    s = station
    patient, doctor, organizer, family = s['users']
    assert answer(s, rooms=['no-such-room'], grantee=patient['id'], targets=[s['theirs']['id']], hours=0,
                  budget=0) == (404, G.ROOM_NOT_YOURS)  # 1 before everything
    assert answer(s, rooms=[s['alone']['id'], 'no-such-room']) == (404, G.ROOM_NOT_YOURS)  # every room's 1 before any 2
    assert answer(s, rooms=[s['old']['id']], grantee=patient['id']) == (400, G.ROOM_REPLACED)  # 2 before 3
    assert answer(s, rooms=[s['alone']['id']], grantee=s['serenity']['id']) == (400, G.ROOM_WITHOUT_GRANTEE)  # 2 before 3
    assert answer(s, rooms='*', grantee=patient['id'], targets=[s['theirs']['id']]) == (400, G.GRANTEE_IS_YOU)  # 3 before 4
    assert answer(s, targets=[s['theirs']['id']], hours=0) == (400, G.TARGET_NOT_YOURS)  # 4 before 5
    assert answer(s, hours=721, budget=0) == (400, 'hours is a whole number from 1 to 720')  # 5 before 6


def test_making_a_grant_takes_the_edges_and_refuses_one_past_them(station):
    s = station
    patient, doctor, organizer, family = s['users']
    ships = fleet(s['store'], patient['id'], 21)
    rooms = [s['store'].create_room(patient['id'], f'Room {n}', [doctor['id']])['id'] for n in range(21)]
    assert answer(s, targets=ships) == (400, G.TARGETS_SHAPE)
    assert answer(s, rooms=rooms) == (400, G.ROOMS_SHAPE)
    assert answer(s, targets=ships[:20], rooms=rooms[:20], hours=1, budget=1) == (201, None)
    assert answer(s, hours=720, budget=500) == (201, None)


def test_making_a_grant_reads_the_policy_in_force(station, monkeypatch):
    s = station
    narrowed(s['store'], monkeypatch, max_expiry_hours=24)
    assert answer(s, hours=25) == (400, 'hours is a whole number from 1 to 24')
    assert answer(s, hours=24) == (201, None)


def test_a_grant_made_in_the_browser_is_stored_signed_and_shown(station):
    s = station
    patient, doctor, organizer, family = s['users']
    client = s['clients'][0]
    assert client.post('/api/grants', json=s['good'], headers={'x-csrf-token': 'stale'}).status_code == 403  # CSRF
    made = client.post('/api/grants', json=s['good'])
    assert made.status_code == 201, made.text
    view = made.json()
    assert view == {'id': view['id'], 'short': '#' + view['id'][:4], 'issuer': {'id': patient['id'], 'name': 'Patient'},
                    'grantee': {'id': doctor['id'], 'name': 'Doctor'},
                    'targets': [{'id': s['serenity']['id'], 'name': 'Serenity', 'ship_builds_left': 20}],
                    'rooms': [{'id': s['shared']['id'], 'title': 'Ops'}], 'expires': 1000000.0 + 24 * 3600, 'budget': 5,
                    'budget_left': 5, 'created': 1000000.0, 'revoked': None, 'revoked_by': None, 'revoke_reason': None,
                    'valid': True}
    assert listed(client) == [view]  # the grant as G11 shows it
    row = grant_row(s['store'], view['id'])
    assert (row['actions'], row['depth'], row['confirm'], row['parent_id'], row['charter_layer_id'],
            row['charter_revision'], row['follow']) == ('["direct"]', 0, 'none', None, None, None, 0)
    assert verify_record(card_of(s['store']._station_identity()), stored_grant_record(s['store'], view['id']), row['signature'])
    anywhere = client.post('/api/grants', json={**s['good'], 'rooms': '*'})
    assert anywhere.status_code == 201 and anywhere.json()['rooms'] == '*'
```

The breakout and the remote room hold the caller and the grantee by hand (a person is never in a breakout, and remote
rooms live in the inbox), so only the breakout check and the `:` check can refuse them.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: 6 failed. The refusal, order and edges tests with `AttributeError: module 'superyak_peer.grants' has no
attribute 'ROOM_NOT_YOURS'` (`'TARGETS_SHAPE'` for the edges test); the others with 405 for `POST /api/grants` (only
`GET /api/grants` exists): the ship-key test with `assert (405, {...'Not Allowed'}) == (403, {...})`, the policy test
with `assert (405, None) == (400, 'hours ...from 1 to 24')`, and the browser test with `assert 405 == 403` (its CSRF
request).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, change `from .common import Problem, encode, uid` to
`from .common import REPLACED_ROOMS, Problem, encode, uid`; after the `NOT_IN_ROOM = ...` line add:

```python
MAX_LISTED = 20  # G8 steps 1 and 4: at most 20 rooms and 20 targets
MAX_BUDGET = 500  # G8 step 6, spec A's bound
# G8's refusals, one per check, so a test can tell which check answered.
ROOMS_SHAPE = 'rooms is "*" or a list of 1 to 20 room ids, each listed once'
ROOM_NOT_YOURS = 'Each listed room must be a room you are in'
ROOM_REPLACED = 'A listed room was replaced by a newer linked room; list the current one'
ROOM_WITHOUT_GRANTEE = 'Each listed room must also have the grantee as a member'
GRANTEE_NOT_PERSON = 'The grantee must be an active person on this station'
GRANTEE_IS_YOU = 'You cannot grant to yourself'
TARGETS_SHAPE = 'targets is a list of 1 to 20 ship ids, each listed once'
TARGET_NOT_YOURS = 'Each target must be a ship you own'
BUDGET_RANGE = 'budget is a whole number from 1 to 500'
```

between `short_id` and `_utc` add:

```python
def _whole(value, low, high):
    """G8 steps 5 and 6: a JSON integer in range. bool is an int in Python, so `true` would pass as 1 without the type
    check; 24.0 and "24" are refused too."""
    return type(value) is int and low <= value <= high


def _id_list(value):
    """1 to 20 distinct ids. A repeated id is refused, never merged (G8)."""
    return (isinstance(value, list) and 1 <= len(value) <= MAX_LISTED
            and all(isinstance(item, str) and 0 < len(item) <= 100 for item in value) and len(set(value)) == len(value))
```

and append to `class Grants`:

```python
    def _grant_rooms(self, db, actor, grantee, rooms):
        """G8 steps 1 and 2. Step 1 runs over every listed room before step 2 looks at any, so no answer says anything
        about a room the caller is not in: an unknown id, a remote id, a breakout and a room the caller is not in each
        get the same 404."""
        if rooms == '*':
            return rooms
        if not _id_list(rooms):
            raise Problem(400, ROOMS_SHAPE)
        for room_id in rooms:
            if (':' in room_id or self._breakout(db, room_id) is not None
                    or db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, actor)).fetchone() is None):
                raise Problem(404, ROOM_NOT_YOURS)
        member = grantee if isinstance(grantee, str) else ''  # step 3 refuses a grantee that isn't an id
        for room_id in rooms:
            if db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({REPLACED_ROOMS})', (room_id,)).fetchone():
                raise Problem(400, ROOM_REPLACED)
            if db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, member)).fetchone() is None:
                raise Problem(400, ROOM_WITHOUT_GRANTEE)
        return rooms

    def _grant_grantee(self, db, actor, grantee):
        """G8 step 3: a person on this station, not a ship, the system author or an account awaiting activation, and not
        the caller."""
        row = db.execute('SELECT kind, activation_pending FROM users WHERE id=?', (grantee,)).fetchone() if isinstance(grantee, str) else None
        if row is None or row['kind'] != 'person' or row['activation_pending']:
            raise Problem(400, GRANTEE_NOT_PERSON)
        if grantee == actor:
            raise Problem(400, GRANTEE_IS_YOU)

    def _grant_targets(self, db, actor, targets):
        """G8 step 4: 1 to 20 ships whose owner is the caller. A resident has no owner, and an admin's power never
        reaches another person's ship."""
        if not _id_list(targets):
            raise Problem(400, TARGETS_SHAPE)
        for ship_id in targets:
            if db.execute("SELECT 1 FROM users WHERE id=? AND kind='ship' AND owner_id=?", (ship_id, actor)).fetchone() is None:
                raise Problem(400, TARGET_NOT_YOURS)
        return targets

    def make_grant(self, actor, grantee, targets, rooms, hours, budget):
        """G8: POST /api/grants. The caller is the issuer. Checked in the spec's order, the first failure answers; then
        the row is stored and signed in one transaction (G12) and returned as G11 shows it."""
        with self.transaction() as db:
            self._person(db, actor)
            policy = self._grant_policy(db)
            rooms = self._grant_rooms(db, actor, grantee, rooms)
            self._grant_grantee(db, actor, grantee)
            targets = self._grant_targets(db, actor, targets)
            if not _whole(hours, 1, policy['max_expiry_hours']):
                raise Problem(400, f'hours is a whole number from 1 to {policy["max_expiry_hours"]}')
            if not _whole(budget, 1, MAX_BUDGET):
                raise Problem(400, BUDGET_RANGE)
            key = self._insert_grant(db, actor, grantee, targets, rooms, hours, budget)
            return self._grant_view(db, actor, db.execute('SELECT * FROM grants WHERE id=?', (key,)).fetchone())
```

In `peer/superyak_peer/app.py`, right before `@app.get('/api/grants/people')`, add:

```python
    @app.post('/api/grants', status_code=201)
    async def grant_make(request: Request):
        who, data = actor(request), await body(request)  # a person with CSRF; a ship key gets 403 (G14)
        return store.make_grant(who, data.get('grantee'), data.get('targets'), data.get('rooms'), data.get('hours'),
                                data.get('budget'))

```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grants.py`, see the named test fail, restore:
- drop `':' in room_id or` → the refusal test (the remote room makes a grant);
- drop `self._breakout(db, room_id) is not None or` → the refusal test (the breakout makes a grant);
- drop `and len(set(value)) == len(value)` → the refusal test (a repeated id is merged);
- `MAX_LISTED = 21`, or `19` → the edges test;
- `isinstance(value, int)` in `_whole` → the refusal test (`true` passes);
- `_whole(hours, 0, ...)`, `_whole(budget, 0, ...)` or `MAX_BUDGET = 501` → the refusal test; `MAX_BUDGET = 499` → the edges test;
- `_whole(hours, 1, 720)` → `test_making_a_grant_reads_the_policy_in_force`;
- drop the `ROOM_REPLACED` check → the refusal and order tests;
- drop `or row['activation_pending']` → the refusal test; drop the `GRANTEE_IS_YOU` check → the refusal and order tests;
- let an admin target any ship (`AND (owner_id=? OR is_admin)`) → the refusal test (the admin case);
- one loop for steps 1 and 2 (the step 2 checks inside the step 1 loop) → the order test (`[alone, no-such-room]` gives 400);
- call `_grant_grantee` before `_grant_rooms`, `_grant_targets` before `_grant_grantee`, or check `budget` before
  `hours` → the order test;
- `member(request)['id']` for `actor(request)` in the route → the ship-key test (the body is `_person`'s
  `Only people can do this`, not `Ship keys cannot use this route`).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/app.py peer/tests/test_grants.py
git commit -m "Grants 3b: making a grant, checked in the spec's order (G8, G14)"
```

---

### Task 7: Revoking, the revocation's signature and its startup backfill (G10, G12)

**Files:**
- Modify: `peer/superyak_peer/grants.py` (one constant; two methods at the end of the class)
- Modify: `peer/superyak_peer/signatures.py` (three methods before `grant_signed`; `grant_signed` carries the revocation)
- Modify: `peer/superyak_peer/db.py` (one line in the `if signing:` block)
- Modify: `peer/superyak_peer/app.py` (one route, before `@app.get('/api/grants/{key}/signed')`)
- Test: `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `_grant_chain` (Task 4); `_owns_a_target`, `_visible_grant`, `_grant_view` (Task 5); `short_id`;
  `_station_identity(db)`; `RECORD_KEYS['grant-revocation']` (3a).
- Produces:
  - `grants.REASON_SHAPE`; `Grants._may_revoke(db, actor, grant) -> bool`;
    `Grants.revoke_grant(actor, grant_id, reason=None) -> dict` (G11's view); route `POST /api/grants/{key}/revoke`.
  - `Signatures._revocation_record(db, grant_id) -> dict | None`, `Signatures._sign_revocation(db, grant_id) -> None`,
    `Signatures._backfill_revocation_signatures() -> None` (Task 8's reconcile relies on it);
    `grant_signed` adds `revocation: {record, signature}` once the grant is revoked.

- [ ] **Step 1: Write the failing tests**

In `test_a_ship_key_gets_403_on_every_grants_route`, replace

```python
    routes = [('POST', '/api/grants', made), ('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None)]
```

with:

```python
    routes = [('POST', '/api/grants', made), ('GET', '/api/grants', None), ('GET', '/api/grants/people', None),
              ('GET', f'/api/grants/{grant}/signed', None), ('POST', f'/api/grants/{grant}/revoke', {})]
```

and append to `peer/tests/test_grants.py`:

```python
def revoke(client, grant_id, **body):
    return client.post(f'/api/grants/{grant_id}/revoke', json=body)


def test_the_issuer_or_a_targets_owner_revokes_and_no_one_else(env):
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    rio, _ = docked(store, patient['id'], 'rio-grande')
    first = make(store, patient, doctor, [rio])
    second = make(store, patient, doctor, [rio])
    with store.transaction() as db:  # by hand: in step 3 the target's owner is the issuer, so this splits the two rules
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], rio['id']))
    assert revoke(clients[1], first).status_code == 403  # the grantee sees it but may not revoke it
    assert revoke(clients[2], first).status_code == 404  # an admin with no other tie doesn't see it
    assert revoke(clients[0], 'no-such-grant').status_code == 404
    done = revoke(clients[0], first)  # the issuer, who no longer owns rio-grande
    assert done.status_code == 200, done.text
    assert (done.json()['revoked'], done.json()['revoked_by'], done.json()['revoke_reason'], done.json()['valid'],
            done.json()['reason']) == (1000000.0, {'id': patient['id'], 'name': 'Patient'}, 'revoked', False,
                                       f'Grant #{first[:4]} was revoked by Patient')
    assert revoke(clients[0], first).status_code == 409  # a second revoke
    assert revoke(clients[1], first).status_code == 403  # 403 before 409
    assert revoke(clients[2], first).status_code == 404  # 404 before both
    by_owner = revoke(clients[3], second, reason='Not this week')  # rio-grande's owner, who didn't issue it
    assert by_owner.status_code == 200, by_owner.text
    assert (by_owner.json()['revoked_by']['id'], by_owner.json()['revoke_reason']) == (family['id'], 'Not this week')


def test_the_issuer_of_a_grant_above_may_revoke_it(env):
    """G10's walk, which step 3 never reaches: a child row made by hand, as step 5's delegation will make them."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, _ = docked(store, patient['id'], 'serenity')
    root = make(store, patient, doctor, [serenity])
    child = make(store, doctor, family, [serenity])
    with store.transaction() as db:  # patient now neither issued the child nor owns its ship: only the walk reaches it
        db.execute('UPDATE grants SET parent_id=? WHERE id=?', (root, child))
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (organizer['id'], serenity['id']))
    revoked = revoke(clients[0], child)
    assert revoked.status_code == 200, revoked.text


def test_a_revoke_reason_is_one_line_of_at_most_200_characters(env):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    for reason in ('x' * 201, 'two\nlines', 'two\u2028lines', 'nul\x00', 5, ['x']):
        assert revoke(clients[0], grant, reason=reason).status_code == 400, reason
    assert revoke(clients[0], grant, reason='   ').json()['revoke_reason'] == 'revoked'  # blank is no reason
    longest = make(store, users[0], users[1], [ship])
    assert revoke(clients[0], longest, reason='x' * 200).json()['revoke_reason'] == 'x' * 200


def test_a_revocations_signature_verifies_and_the_signed_route_carries_it(env, tmp_path):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    grant = make(store, users[0], users[1], [ship])
    assert 'revocation' not in clients[1].get(f'/api/grants/{grant}/signed').json()
    clock[0] += 60
    assert revoke(clients[0], grant, reason='Done').status_code == 200
    signed = clients[1].get(f'/api/grants/{grant}/signed').json()  # the grantee reads it too
    identity = store._station_identity()
    card = card_of(identity)
    record, signature = signed['revocation']['record'], signed['revocation']['signature']
    assert set(signed) == {'station', 'record', 'signature', 'revocation'} and set(signed['revocation']) == {'record', 'signature'}
    assert set(record) == RECORD_KEYS['grant-revocation']
    assert record == {'kind': 'grant-revocation', 'station': identity.peer_id, 'grant': grant, 'revoked': 1000060.0,
                      'revoked_by': users[0]['id'], 'reason': 'Done'}
    assert verify_record(card, record, signature)
    assert verify_record(card, signed['record'], signed['signature'])  # the grant's own signature still verifies
    assert not verify_record(card, {**record, 'reason': 'revoked'}, signature)  # one changed value
    assert not verify_record(card, signed['record'], signature)  # a revocation's signature never passes for its grant's
    other = PeerIdentity.load_or_create(tmp_path / 'other')
    named_other = {**record, 'station': other.peer_id}
    assert not verify_record(card, named_other, raw_sign(identity, named_other))
    added = {**record, 'note': 'x'}
    assert not verify_record(card, added, raw_sign(identity, added))
    missing = {key: value for key, value in record.items() if key != 'reason'}
    assert not verify_record(card, missing, raw_sign(identity, missing))
    forged = {**record, 'station': '0' * 64}
    assert not verify_record({**card, 'peer_id': '0' * 64}, forged, raw_sign(identity, forged))


def test_startup_signs_each_unsigned_revocation_once(env, monkeypatch):
    app, clients, users, clock = env
    store = app.state.store
    ship, _ = docked(store, users[0]['id'], 'serenity')
    revoked, kept = make(store, users[0], users[1], [ship]), make(store, users[0], users[1], [ship])
    assert revoke(clients[0], revoked).status_code == 200
    with store.transaction() as db:  # as the restore reconcile leaves a revocation (G13)
        db.execute('UPDATE grants SET revocation_signature=NULL WHERE id=?', (revoked,))
    from superyak_peer.db import Store
    assert grant_row(Store(store.data_dir, signing=False), revoked)['revocation_signature'] is None  # G4a: no backfill there
    restarted = Store(store.data_dir)
    rows = {grant: grant_row(restarted, grant)['revocation_signature'] for grant in (revoked, kept)}
    assert rows[kept] is None  # nothing to sign on a grant still in force
    with restarted.transaction() as db:
        assert verify_record(card_of(restarted._station_identity()), restarted._revocation_record(db, revoked), rows[revoked])
    signed, real = [], PeerIdentity.sign_record
    monkeypatch.setattr(PeerIdentity, 'sign_record', lambda self, record: signed.append(record) or real(self, record))
    Store(store.data_dir)
    assert signed == [] and grant_row(restarted, revoked)['revocation_signature'] == rows[revoked]  # a second start signs nothing
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py`
Expected: 6 failed, each first meeting `POST /api/grants/{id}/revoke`'s 404 (no route yet): the ship-key test with
`assert (404, {'detail': 'Not Found'}) == (403, {...})`, the issuer test with `assert 404 == 403` (the grantee's
request), the reason test with `assert 404 == 400`, and the others with `assert 404 == 200`.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, after `BUDGET_RANGE = ...` add:

```python
REASON_SHAPE = 'A reason is one line of at most 200 characters'
```

and append to `class Grants`:

```python
    def _may_revoke(self, db, actor, grant):
        """G10: the issuer, the issuer of any grant above it (none in step 3, but the walk is the same), or the owner of
        any target ship. Being an admin gives no power over other people's grants."""
        return any(link['issuer_id'] == actor for link in self._grant_chain(db, grant)) or self._owns_a_target(db, actor, grant)

    def revoke_grant(self, actor, grant_id, reason=None):
        """G10: POST /api/grants/{id}/revoke. 404 for anyone G11 doesn't show the grant to, then 403 for one who sees it
        but may not revoke it, then 409 when it is already revoked. The revocation is signed in this transaction (G12).
        A missing or blank reason is `revoked`."""
        if reason is None or (isinstance(reason, str) and not reason.strip()):
            reason = 'revoked'
        if not isinstance(reason, str) or len(reason) > 200 or reason.splitlines() != [reason] or '\x00' in reason:
            raise Problem(400, REASON_SHAPE)
        with self.transaction() as db:
            grant = self._visible_grant(db, actor, grant_id)
            if not self._may_revoke(db, actor, grant):
                raise Problem(403, 'Only its issuer or the owner of one of its ships can revoke this grant')
            if grant['revoked'] is not None:
                raise Problem(409, f'Grant {short_id(grant["id"])} is already revoked')
            db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?',
                       (self.clock(), actor, reason, grant['id']))
            self._sign_revocation(db, grant['id'])
            return self._grant_view(db, actor, db.execute('SELECT * FROM grants WHERE id=?', (grant['id'],)).fetchone())
```

In `peer/superyak_peer/signatures.py`, right before `def grant_signed(`, add:

```python
    def _revocation_record(self, db, grant_id):
        """G12: a revocation's record, with exactly RECORD_KEYS['grant-revocation']; None while the grant is in force."""
        row = db.execute('SELECT id, revoked, revoked_by, revoke_reason FROM grants WHERE id=?', (grant_id,)).fetchone()
        if row is None or row['revoked'] is None:
            return None
        return {'kind': 'grant-revocation', 'station': self._station_identity(db).peer_id, 'grant': row['id'],
                'revoked': row['revoked'], 'revoked_by': row['revoked_by'], 'reason': row['revoke_reason']}

    def _sign_revocation(self, db, grant_id):
        """G12: in the transaction that revokes, or at the next start for a revocation the restore reconcile wrote."""
        db.execute('UPDATE grants SET revocation_signature=? WHERE id=?',
                   (self._station_identity(db).sign_record(self._revocation_record(db, grant_id)), grant_id))

    def _backfill_revocation_signatures(self):
        """G12: at every signing start, each revocation without a signature is signed once. Only the restore reconcile
        writes one (G13): it works on a staged file and holds no key. With none to sign, the identity is never touched,
        so a new station's first card still names its host (G4)."""
        with self.transaction() as db:
            for row in db.execute('SELECT id FROM grants WHERE revoked IS NOT NULL AND revocation_signature IS NULL '
                                  'ORDER BY id').fetchall():
                self._sign_revocation(db, row['id'])

```

and replace `grant_signed` with:

```python
    def grant_signed(self, actor, grant_id):
        """G12: GET /api/grants/{id}/signed, {station, record, signature}, plus revocation: {record, signature} once it
        is revoked, for anyone G11 shows the grant to; anyone else, and an unknown id, gets 404."""
        with self.transaction() as db:
            grant = self._visible_grant(db, actor, grant_id)
            signed = {'station': self._station_identity(db).peer_id, 'record': self._grant_record(db, grant['id']),
                      'signature': grant['signature']}
            if grant['revoked'] is not None:
                signed['revocation'] = {'record': self._revocation_record(db, grant['id']),
                                        'signature': grant['revocation_signature']}
            return signed
```

In `peer/superyak_peer/db.py`, inside the `if signing:` block, after
`self._backfill_revision_signatures()  # G5: after the schema, at every start`, add:

```python
            self._backfill_revocation_signatures()  # spec A step 3, G12: what the restore reconcile revoked
```

In `peer/superyak_peer/app.py`, right before `@app.get('/api/grants/{key}/signed')`, add:

```python
    @app.post('/api/grants/{key}/revoke')
    async def grant_revoke(key: str, request: Request):
        who, data = actor(request), await body(request)
        return store.revoke_grant(who, key, data.get('reason'))

```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py tests/test_signatures.py`
Expected: all pass.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grants.py tests/test_signatures.py`, see the named test fail, restore:
- `_may_revoke` without the issuer clause → the issuer test (403 for the issuer who no longer owns rio-grande) and the walk test;
- `_may_revoke` without `_owns_a_target` → the issuer test (rio-grande's owner gets 403);
- `grant['issuer_id'] == actor` for the walk in `_may_revoke` → `test_the_issuer_of_a_grant_above_may_revoke_it`;
- the grantee allowed (`grant['grantee_id'] == actor or ...`) → the issuer test;
- the 409 check before the 403 check → the issuer test (the grantee gets 409); drop the 409 check → the same;
- `len(reason) > 201` or `> 199`, or drop the `splitlines` check → the reason test;
- `if reason is None:` alone (blank kept) → the reason test;
- drop `self._sign_revocation(db, grant['id'])` → the revocation signature test (`verify_record(..., None)` is False);
- `'reason': 'revoked'` in `_revocation_record` → the revocation signature test;
- `if False:` for `if grant['revoked'] is not None:` in `grant_signed` → the revocation signature test;
- drop the backfill line in `Store.__init__` → the startup test; move it out of the `if signing:` block → the startup test
  (a `signing=False` start signs);
- `WHERE revoked IS NOT NULL '` (re-sign every revocation) → the startup test (a second start signs);
- `self._station_identity()` at the top of `_backfill_revocation_signatures` → 3a's
  `test_a_new_stations_first_card_still_names_its_host` (every start would create the identity);
- `member(request)['id']` for `actor(request)` in the revoke route → the ship-key test.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/signatures.py peer/superyak_peer/db.py peer/superyak_peer/app.py peer/tests/test_grants.py
git commit -m "Grants 3b: revoking, the revocation's signature and its startup backfill (G10, G12)"
```

---

### Task 8: The restore reconcile takes back revoked grants and spent budgets (G13)

**Files:**
- Modify: `peer/superyak_peer/backups.py` (`COMPARED`; three steps and a helper before `_member_name`; the report
  dict, the step lists and `describe_reconcile`)
- Test: `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `_usable`, `COMPARED`, `_not_this_station`, `reconcile`, `describe_reconcile` (`backups.py`); `safe_line`;
  `_backfill_revocation_signatures`, `_revocation_record` (Task 7); `staged`, `reconcile` from `tests/test_restore.py`.
- Produces: `backups.GRANT_COMPARED`, `backups.GRANT_NAMED`, `_grant_line(db, row, how)`,
  `_revoke_every_grant(db, old, now, report)`, `_revoke_grants_like_replaced(db, old, now, report)`,
  `_add_budget_uses_like_replaced(db, old, now, report)`; `report['grants']` as `(short, issuer, grantee, how)`;
  `report['counts']['grants revoked']`, `report['counts']['budget uses added']`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_grants.py`, make the imports:

```python
import base64
from contextlib import closing
import shutil
import sqlite3
import pytest
from superyak_peer import grants as G
from superyak_peer.common import uid
from superyak_peer.grants import short_id
from superyak_peer.identity import PeerIdentity, RECORD_KEYS, verify_record
from test_instructions import docked, ship_client
from test_restore import reconcile as run_reconcile, staged
from test_signatures import card_of, raw_sign
```

and append:

```python
def lighthouse(tmp_path):
    """A station on a clock the test moves, with andy granting jenn: (store, clock, andy, jenn, serenity)."""
    from superyak_peer.db import Store
    clock = [1000000.0]
    store = Store(tmp_path / 'lighthouse', clock=lambda: clock[0])
    andy = store.create_user('andy', 'Andy', 'long-password-andy', is_admin=True)
    jenn = store.create_user('jenn', 'Jenn', 'long-password-jenn')
    serenity, _ = docked(store, andy['id'], 'serenity')
    return store, clock, andy, jenn, serenity


def revocations(path):
    with closing(sqlite3.connect(path)) as db:
        return {row[0]: row[1:] for row in db.execute('SELECT id, revoked, revoked_by, revoke_reason, revocation_signature FROM grants')}


def uses(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT grant_id, ticket_id, created FROM budget_uses ORDER BY grant_id, created').fetchall()


def report_line(out, start):
    return next((line for line in out.splitlines() if line.startswith(start)), None)


def test_the_reconcile_takes_back_revoked_grants_and_spent_budgets(tmp_path, capsys):
    """Test 10, with a replaced file: a grant revoked there is revoked here as it was there, a grant missing there is
    revoked, the budget uses there are added once, and the station's next start signs those revocations."""
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    kept = make(store, andy, jenn, [serenity])  # in force in both files
    clock[0] += 1
    later = make(store, andy, jenn, [serenity])  # revoked after the copy
    clock[0] += 1
    lost = make(store, andy, jenn, [serenity])  # missing from the replaced file
    clock[0] += 1
    early = make(store, andy, jenn, [serenity])  # revoked before the copy: left as it is
    store.revoke_grant(andy['id'], early, 'before the copy')
    charge(store, kept, 100)
    copy = staged(tmp_path, store)  # A
    early_row = revocations(copy)[early]
    clock[0] += 60  # B moves on
    store.revoke_grant(andy['id'], later, 'Not this week')
    charge(store, kept, 50, 10)  # two builds after the copy
    newer = make(store, andy, jenn, [serenity])  # made after the copy: gone after the restore, with its use
    charge(store, newer, 5)
    with store.transaction() as db:  # by hand: grants are never deleted, so a missing one means damage
        db.execute('DELETE FROM grants WHERE id=?', (lost,))
    there = revocations(store.db_path)
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)
    assert code == 0, err
    here = revocations(copy)
    assert here[later] == there[later][:3] + (None,)  # the same time, person and reason; signed at the next start
    assert here[lost][0] is not None and here[lost][1:] == (None, 'restored', None)  # now, with no person
    assert here[kept] == (None, None, None, None) and here[early] == early_row
    assert [(grant, created) for grant, _, created in uses(copy)] == [(kept, clock[0] - 60 - 100), (kept, clock[0] - 50), (kept, clock[0] - 10)]
    assert report_line(out, 'Grants revoked: ') == (f'Grants revoked: #{later[:4]} (andy to jenn, as in the replaced file); '
                                                   f'#{lost[:4]} (andy to jenn, missing from the replaced file).')
    assert 'budget uses added (2)' in report_line(out, 'Taken back: ')
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', store.db_path)  # a second run adds none
    assert code == 0, err
    assert report_line(out, 'Grants revoked: ') is None and 'budget uses added (0)' in report_line(out, 'Taken back: ')
    assert len(uses(copy)) == 3
    live = tmp_path / 'live'
    live.mkdir(mode=0o700)
    shutil.copyfile(store.data_dir / 'identity.json', live / 'identity.json')  # the identity stays put (runbook step 6)
    shutil.copyfile(copy, live / 'peer.sqlite3')
    from superyak_peer.db import Store
    started = Store(live)
    card = card_of(started._station_identity())
    with started.transaction() as db:
        for grant in (later, lost, early):
            row = db.execute('SELECT signature, revocation_signature FROM grants WHERE id=?', (grant,)).fetchone()
            assert verify_record(card, started._revocation_record(db, grant), row['revocation_signature']), grant
            assert verify_record(card, started._grant_record(db, grant), row['signature']), grant


def test_without_a_replaced_file_the_reconcile_revokes_every_grant(tmp_path, capsys):
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    first = make(store, andy, jenn, [serenity])
    clock[0] += 1
    second = make(store, andy, jenn, [serenity])
    clock[0] += 1
    done = make(store, andy, jenn, [serenity])
    store.revoke_grant(andy['id'], done, 'before the copy')
    copy = staged(tmp_path, store)
    done_row = revocations(copy)[done]
    code, out, err = run_reconcile(capsys, '--db', copy)
    assert code == 0, err
    here = revocations(copy)
    for grant in (first, second):
        assert here[grant][1:] == (None, 'restored', None), grant
    assert here[done] == done_row  # already revoked: kept as it was, with its signature
    assert report_line(out, 'Grants revoked: ') == (f'Grants revoked: #{first[:4]} (andy to jenn, no usable replaced file); '
                                                   f'#{second[:4]} (andy to jenn, no usable replaced file).')
    assert 'grants revoked (2)' in report_line(out, 'Taken back: ')


def test_a_replaced_file_without_the_grants_tables_is_treated_as_absent(tmp_path, capsys):
    """G13: the grants columns join COMPARED, so a replaced file lacking them (the wrong file, or a damaged one) is
    treated as absent and the reconcile fails closed: every grant is revoked, rather than none compared."""
    store, clock, andy, jenn, serenity = lighthouse(tmp_path)
    grant = make(store, andy, jenn, [serenity])
    copy = staged(tmp_path, store)
    replaced = copy.parent / 'peer.sqlite3'
    shutil.copyfile(store.db_path, replaced)
    with closing(sqlite3.connect(replaced)) as db:
        db.execute('DROP TABLE budget_uses')
        db.execute('DROP TABLE grants')
        db.commit()
    code, out, err = run_reconcile(capsys, '--db', copy, '--replaced', replaced)
    assert code == 0, err
    assert 'The replaced file was treated as absent (it lacks tables or columns the copy has: ' in out
    assert revocations(copy)[grant][2] == 'restored'
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py -k "reconcile or replaced"`
Expected: 3 failed (the `-k` also selects Task 5's replaced-room test, which passes): the replaced-file test with
`assert (None, None, None, None) == (1000063.0, '...s week', None)` at `here[later]` (nothing was revoked), the
no-replaced test with `assert (None, None, None) == (None, 'restored', None)`, and the absent test with
`assert 'The replaced file was treated as absent (it lacks tables or columns the copy has: ' in 'Usernames and titles
...Compared with the replaced file...'` (today's COMPARED lacks the grants columns, so the file counts as compared).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/backups.py`, the end of `COMPARED`,

```python
            'peers.peer_id', 'peers.paired', 'mentions', 'events')
```

becomes:

```python
            'peers.peer_id', 'peers.paired', 'mentions', 'events',
            # spec A step 3, G13: what the grants steps read from the replaced file
            'grants.id', 'grants.revoked', 'grants.revoked_by', 'grants.revoke_reason', 'budget_uses.grant_id',
            'budget_uses.ticket_id', 'budget_uses.created')
```

Right before `def _member_name(db, table, member):`, add:

```python
GRANT_COMPARED = ('grants.id', 'grants.revoked', 'grants.revoked_by', 'grants.revoke_reason')
GRANT_NAMED = ('grants.issuer_id', 'grants.grantee_id', 'grants.created')  # read from the copy only, for the report


def _grant_line(db, row, how):
    """G13: how the report names a revoked grant: its short id, its issuer's and grantee's usernames, and why."""
    def username(user_id):
        found = db.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
        return found[0] if found else user_id[:6]
    return ('#' + row['id'][:4], username(row['issuer_id']), username(row['grantee_id']), how)


def _revoke_every_grant(db, old, now, report):
    """G13, without a usable replaced file: every grant not yet revoked is revoked now, with reason `restored` and no
    person. The station signs each of these revocations at its next start (signatures.py): the reconcile works on a
    staged file and holds no key."""
    if not _usable(db, None, report, *GRANT_COMPARED, *GRANT_NAMED):
        return
    for row in db.execute('SELECT id, issuer_id, grantee_id FROM grants WHERE revoked IS NULL ORDER BY created, id').fetchall():
        db.execute("UPDATE grants SET revoked=?, revoked_by=NULL, revoke_reason='restored' WHERE id=?", (now, row['id']))
        report['grants'].append(_grant_line(db, row, 'no usable replaced file'))
    report['counts']['grants revoked'] = len(report['grants'])


def _revoke_grants_like_replaced(db, old, now, report):
    """G13, with a usable replaced file: a grant revoked there is revoked here with the same time, person and reason; a
    grant the replaced file lacks is revoked now with reason `restored` and no person (grants are never deleted, so a
    missing one means damage). Signed at the station's next start, as above."""
    if not (_usable(db, old, report, *GRANT_COMPARED) and _usable(db, None, report, *GRANT_NAMED)):
        return
    there = {row[0]: row[1:] for row in old.execute('SELECT id, revoked, revoked_by, revoke_reason FROM grants')}
    for row in db.execute('SELECT id, issuer_id, grantee_id FROM grants WHERE revoked IS NULL ORDER BY created, id').fetchall():
        if row['id'] not in there:
            values, how = (now, None, 'restored'), 'missing from the replaced file'
        elif there[row['id']][0] is not None:
            values, how = there[row['id']], 'as in the replaced file'
        else:
            continue
        db.execute('UPDATE grants SET revoked=?, revoked_by=?, revoke_reason=? WHERE id=?', (*values, row['id']))
        report['grants'].append(_grant_line(db, row, how))
    report['counts']['grants revoked'] = len(report['grants'])


def _add_budget_uses_like_replaced(db, old, now, report):
    """G13: each budget use recorded there, for a grant in both files, is added here unless one with its (grant_id,
    ticket_id) is here already, so a grant's spent budget comes back and a second run adds none."""
    if not _usable(db, old, report, 'grants.id', 'budget_uses.grant_id', 'budget_uses.ticket_id', 'budget_uses.created'):
        return
    both = {row[0] for row in db.execute('SELECT id FROM grants')} & {row[0] for row in old.execute('SELECT id FROM grants')}
    here = {(row[0], row[1]) for row in db.execute('SELECT grant_id, ticket_id FROM budget_uses')}
    added = 0
    for grant_id, ticket_id, created in old.execute('SELECT grant_id, ticket_id, created FROM budget_uses ORDER BY created').fetchall():
        if grant_id in both and (grant_id, ticket_id) not in here:
            db.execute('INSERT INTO budget_uses(grant_id, ticket_id, created) VALUES(?, ?, ?)', (grant_id, ticket_id, created))
            here.add((grant_id, ticket_id))
            added += 1
    report['counts']['budget uses added'] = added


```

(`db` rows are `sqlite3.Row`, `old` rows plain tuples, which is why `here` is built from index pairs.)

In `reconcile`, the report dict's last line `'not_compared': []}` becomes `'not_compared': [], 'grants': []}`, and the
two step lists become:

```python
            if old is None:
                _revoke_owned_ship_keys(db, old, now, report)
                _revoke_every_grant(db, old, now, report)
            else:
                for step in (_revoke_like_replaced, _remove_members_like_replaced, _lower_roles_like_replaced,
                             _close_breakouts_like_replaced, _revoke_grants_like_replaced, _add_budget_uses_like_replaced,
                             _unpair_like_replaced, _report_differences):
```

In `describe_reconcile`, right after the `if report['revoked']:` line and its `lines.append(...)`, add:

```python
    if report['grants']:
        lines.append('Grants revoked: ' + '; '.join(f'{short} ({safe_line(issuer)} to {safe_line(grantee)}, {how})'
                                                   for short, issuer, grantee, how in report['grants']) + '.')
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grants.py tests/test_restore.py tests/test_backups.py`
Expected: all pass. The restore suite's own reports gain nothing (its stations hold no grants), and
`test_reconcile_skips_what_an_older_copy_lacks` still names exactly its two skipped steps (its copy has the grants
tables).

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grants.py tests/test_restore.py`, see the named test fail, restore:
- drop `_revoke_grants_like_replaced` from the step list → the replaced-file test;
- drop `_add_budget_uses_like_replaced` from the step list → the replaced-file test;
- drop the `_revoke_every_grant(...)` line → the no-replaced test;
- `continue` for a grant missing there → the replaced-file test;
- `values = (now, *there[row['id']][1:])` (copy the person and reason, not the time) → the replaced-file test;
- `if grant_id in both:` (no dedupe) → the replaced-file test (the second run adds 2 more);
- `if (grant_id, ticket_id) not in here:` (any grant) → the replaced-file test (`newer`'s use comes back);
- drop `WHERE revoked IS NULL` from `_revoke_every_grant`'s SELECT (revoke an already revoked grant again) → the
  no-replaced test (`done` changes);
- drop the `Grants revoked:` line from `describe_reconcile` → both reconcile tests;
- drop the grants columns from `COMPARED` → `test_a_replaced_file_without_the_grants_tables_is_treated_as_absent`.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/backups.py peer/tests/test_grants.py
git commit -m "Grants 3b: the restore reconcile takes back revoked grants and spent budgets (G13)"
```

---

### Task 9: API.md and the restore runbook (G23's part); the whole suite

**Files:**
- Modify: `peer/API.md` ("## Signed records"; a new "## Grants" section before "## Files"; "## Store interfaces for
  following tasks")
- Modify: `docs/station-restore.md` (three prose lines; no code block changes)

- [ ] **Step 1: Write API.md's part**

In `peer/API.md`, "## Signed records":

1. In its first paragraph, replace the last two sentences (they begin `Every process that opens the store` and end
   `Merge 3a signs one kind:`, across the paragraph's last two lines) with these, wrapped at the paragraph's width:

   ```markdown
   The lighthouse reads `identity.json` at startup when it exists; the door and the station commands that never sign
   don't (see below). It signs three kinds:
   ```

2. After the `instructions-revision` bullet, add:

   ```markdown
   - `grant`: `{kind, station, id, issuer_id, grantee_id, actions, targets, rooms, expires, budget, depth, confirm,
     parent_id, charter_layer_id, charter_revision, follow, created}`, with `actions`, `targets` and `rooms` as parsed
     JSON values. It is signed in the transaction that makes the grant; columns later steps add stay out of it.
   - `grant-revocation`: `{kind, station, grant, revoked, revoked_by, reason}`, signed in the transaction that revokes.
     A revocation the restore reconcile wrote is signed once at the next start.
   ```

3. After the paragraph ending `Anyone else, and any revision without a signature, gets 404; a ship key gets 403.`, add:

   ```markdown
   `GET /api/grants/{id}/signed` (person) returns `{station, record, signature}`, plus `revocation: {record, signature}`
   once the grant is revoked, to anyone `GET /api/grants` shows the grant to. Anyone else gets 404; a ship key gets 403.
   ```

4. In its last paragraph, replace everything from `A station that can't load its identity doesn't start;` to the end
   (`...(the backfill signs only unsigned revisions).`) with:

   ```markdown
   A station that can't load its identity doesn't start. A new station creates it at its first signature, so its first
   card export still names its host; but a station that holds signed records (a revision signature or a grant) and has
   lost `identity.json` refuses to start, and so do `card` and `serve --peer-tls`, rather than make a new key (the message
   names the file). The door and the station commands that never sign (`station-pending`, `station-approve`,
   `station-deny`, `station-rooms`, `station-bridge`, `station-unbridge`, `station-notices`) open the store with
   `Store(..., signing=False)`: they load no key at startup, so a damaged identity stops the lighthouse alone. The
   nightly copies leave out the identity files; the restore test gives its scratch copy a throwaway identity. If
   `identity.json` is truly lost, `station-new-identity --data-dir DIR [--endpoint https://HOST:PORT]`, run with the
   lighthouse stopped, is the one way to a new key: it refuses while the file exists, moves the old `peer-cert.pem` and
   `peer-key.pem` aside with a dated suffix, creates the identity (naming the endpoint's host) and changes nothing in the
   database. Every signature made with the lost key then stops verifying, the station's peer id changes so every paired
   peer pairs again, and replies it already sent into remote rooms show as unverified.
   ```

Right before `## Files`, add:

```markdown
## Grants

A grant lets a person direct some of their own ships in some rooms, for some hours, with a daily budget of builds
(spec A step 3, `docs/superpowers/specs/2026-10-15-grants-step3-design.md`, G7-G14). In this release every grant is a
root `direct` grant from one person to another, made in the browser; merge 3c lets the grantee's mentions spend it.
Every `/api/grants` route takes a person session (CSRF on writes), and a ship key gets 403 on each.

| Method/path | Body | Behavior |
|---|---|---|
| POST `/api/grants` | `{grantee, targets, rooms, hours, budget}` | 201 with the grant as `GET /api/grants` shows it; the caller is the issuer |
| GET `/api/grants` | — | The grants the caller issued, holds, or that cover their ships, newest first |
| POST `/api/grants/{id}/revoke` | `{reason?}` | The revoked grant; for its issuer, an issuer above it, or a target ship's owner |
| GET `/api/grants/{id}/signed` | — | `{station, record, signature}`, plus `revocation` once revoked (see Signed records) |
| GET `/api/grants/people` | — | `[{id, name}]`: this station's active people other than the caller, by name |

**Policy.** With no charter (step 4), `Grants._grant_policy` returns spec A's defaults: `max_depth` 3,
`max_expiry_hours` 720, `agent_grant_default_hours` 24, `builds_per_ship_per_day` 20, `delegable` `["direct"]`, and an
unrestricted grantee set. Every check reads it there, so a narrower policy takes effect at the next check.

**Making.** Checked in this order; the first failure answers:

1. `rooms` is `"*"` or a list of 1 to 20 room ids, each once (400). Each listed room must be one the caller is in: an
   unknown id, a remote id (with `:`), a breakout and a room the caller is not in all get the same 404.
2. Each listed room is current (not replaced by a newer linked room) and has the grantee as a member (400).
3. `grantee` is an active person on this station, not a ship, the system author or an account awaiting activation, and
   not the caller (400).
4. `targets` is a list of 1 to 20 ship ids, each once, every one owned by the caller (400). A resident ship has no
   owner, and an admin's power doesn't reach another person's ships.
5. `hours` is a JSON integer from 1 to `max_expiry_hours`; `expires` is now plus that many hours.
6. `budget` is a JSON integer from 1 to 500.

`true`, `24.0` and `"24"` are not integers. The grant is stored with `actions` `["direct"]`, `depth` 0 and `confirm`
`none`, and signed in the same transaction.

**Validity.** Checked in this order; the first that fails is the `reason`: not revoked ("Grant #a1b2 was revoked by
Andy"; "Grant #a1b2 was revoked" when the restore revoked it); not expired (from its `expires` instant on: "Grant #a1b2
expired 2026-10-20 14:00 UTC"); fits the policy in force now ("Grant #a1b2 lasts longer than the station now allows";
a chain longer than `max_depth` or a grantee outside the grantee set: "Grant #a1b2 is no longer allowed by the
station's policy"); fewer than `budget` builds charged in the last 24 hours, where a use exactly 24 hours old no longer
counts ("Grant #a1b2 has used its 5 builds for the last 24 hours"); and its issuer still owns every target ("Andy no
longer owns Rio Grande"). `#a1b2` is `#` and the id's first 4 characters. Names in reasons are the station's own, on one
safe line.

**Reading.** Each grant has `id`, `short`, `issuer` and `grantee` (`{id, name}`), `targets` (`[{id, name,
ship_builds_left}]`), `rooms` (`"*"`, or for each listed room `{id, title}` plus `current: {id, title}` when newer
linked rooms have replaced it, following the links forward), `expires`, `budget`, `budget_left`, `created`, `revoked`,
`revoked_by` (`{id, name}` or null), `revoke_reason`, `valid`, and `reason` only when it is not valid. A room's title is
shown only to its members; anyone else sees `a room you are not in`. `budget_left` is the budget less the builds charged
to the grant in the last 24 hours; `ship_builds_left` is `builds_per_ship_per_day` less the ship's grant build tickets
in the last 24 hours, under every grant. Neither goes below 0. Names and titles come from people; the web app escapes
them.

**Revoking.** 404 for anyone `GET /api/grants` doesn't show the grant to; 403 for one who sees it but may not revoke it
(its grantee); 409 when it is already revoked. `reason` is one line of at most 200 characters (400 otherwise); missing,
null or blank, it is `revoked`. Being an admin gives no power over other people's grants. The revocation is signed in
the same transaction.

**Restoring.** `station-restore-reconcile` revokes, in the staged copy, each grant revoked in the replaced file (with
its time, person and reason) and each grant the replaced file lacks (reason `restored`), and adds the replaced file's
budget uses for grants in both files, matched on `(grant_id, ticket_id)`. Without a usable replaced file it revokes
every grant with reason `restored` and no person. The report lists each revoked grant by short id, issuer and grantee,
and why. The station signs those revocations at its next start. A grant made after the copy is gone; its issuer makes
it again.
```

In "## Store interfaces for following tasks", after the paragraph that begins `Signatures (spec A step 3):`, add:

```markdown
Grants (spec A step 3): `make_grant(actor,grantee,targets,rooms,hours,budget)`, `list_grants(actor)`,
`revoke_grant(actor,grant_id,reason=None)`, `grant_signed(actor,grant_id)` and `grant_people(actor)` back the routes;
`_grant_validity(db,grant)` returns `(valid, reason)`, and `_grant_policy(db)` is the policy in force.
```

- [ ] **Step 2: The restore runbook**

In `docs/station-restore.md`:
- in "Before you start", replace `old room briefs and peers you had unpaired.` with
  `old room briefs, peers you had unpaired, revoked grants and spent grant budgets.`;
- in step 7, after `Tell the owners of ships whose keys were revoked to dock again.`, add
  `Ask the issuers of the grants the report lists as missing from the replaced file, or revoked with no usable replaced file, to make again any still wanted; a grant made after the copy is gone too.`;
- in step 6, after `The peer identity files stay where they are; nothing here moves them.`, add
  `A station that holds signed records refuses to start without its identity.json; restore the file rather than delete it. If it is truly lost, station-new-identity --data-dir DIR (API.md, Signed records), run with the lighthouse stopped, gives the station a new key on purpose.`

- [ ] **Step 3: Run the whole peer suite**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: everything passes. 84ee0f6 measured 860 passed and 1 skipped; with this plan's 39 new tests (11 in
test_signatures, 28 in test_grants), about 899 passed and 1 skipped, as the fresh review measured. Report the counts, and any failure by name.

- [ ] **Step 4: Commit**

```bash
git add peer/API.md docs/station-restore.md
git commit -m "Grants 3b: API.md's Grants and Signed records, and the restore runbook (G23's part)"
```

---

## After the tasks

- Merge `main` before section 2 review if it moved.
- Section 2: post the head in "Superyak: city of AI" for Rio Grande; the Pi runs both suites. On merge, the deploy
  restarts the lighthouse; the door and Odo's station commands now start without the key.
- A live check, as Andy in the browser console: `POST /api/grants` to a person over one of his ships with `rooms: "*"`,
  `hours: 1`, `budget: 1`; `GET /api/grants` shows it valid; `GET /api/grants/{id}/signed` verifies against the
  station's card (`card --endpoint` prints it); `POST /api/grants/{id}/revoke` with `{}` makes it invalid. Nothing
  spends a grant until merge 3c.

## Self-review: every rule and test to its task

| Spec | Task and test |
| --- | --- |
| G4a, test 4a | 1: door and commands with a damaged identity, the door's `_identity`, signing=False still signs, `_own_peer_id`; 2: the lazy refusal |
| G4b, test 4b | 2: `Store`, `create_app`, `card`, `serve --peer-tls` refuse; signing=False opens; no signed records starts and creates none; 3a's dangling symlink test; 4: grants count, the first grant creates the identity |
| G4c, test 4c | 2: restore test on signed records, the `--peer-tls` check on an old, missing or unreadable database; 3: `station-new-identity`; 1: the room read doesn't stall |
| Schema, G7 | 4: table and index; the policy narrowed through `_grant_policy` (tests 6) |
| G8, test 5 | 6: refusal table (404 body the same for four rooms), order pairs, the edges 1/720, 1/500, 20/21, the policy read, the made grant |
| G9, test 6 | 4: revoked, expired at its instant, lifetime, depth, grantee set, budget at the 24-hour edge, ownership, revoked-and-expired, order pairs |
| G10, test 7 | 7: issuer, target owner, grantee 403, admin 404, 409, order 404/403/409, the walk, reason rules |
| G11, test 9 | 5: who sees what, fields, `budget_left`, `ship_builds_left`, titles only to members, the current room twice replaced, a cycle, the people list |
| G12, test 8 | 4: the grant record and signature and G3's failures; 5: `/signed` and its 404s; 7: the revocation record, signature, `/signed`'s `revocation`, the startup backfill |
| G13, test 10 | 8: revoked as there, missing revoked, budget uses once, a second run adds none, without a replaced file, the report, next start signs; COMPARED |
| G14 | 5, 6, 7: one ship-key test over all five routes, checking `current_user`'s own body |
| G23 (API.md part) | 9 |
