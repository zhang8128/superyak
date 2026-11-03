# Owner Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person's ships, on a machine whose person account Andy paired with a typed code, pair here without a code each, within a trust Andy grants once in the browser, so a thousand ships don't need a thousand codes.

**Architecture:** The exporting peer signs a `ship-assertion` record with the key in its paired card (identity.py). A new `owner_trust.py` holds the append-only `owner_trust` table, the trust confirmations, the cap and one invariant, `settle_owner_trust`: a trust whose owner is held is revoked, and a ship whose latest trust is revoked is held. `Federation.pair_trusted` checks everything in one transaction; unpair, revoke and restore call the invariant.

**Tech Stack:** Python 3, SQLite, FastAPI, `cryptography` (Ed25519), pytest, Playwright for the one browser test.

**Spec:** `docs/superpowers/specs/2026-11-02-machine-trust-design.md` (approved, revision 4, with S11 and N13). Read it before any task; the spec wins over this plan where they differ.

**Branch:** build on `owner-trust`, cut from current `main` with `spec-machine-trust` merged in so the spec and this plan travel with the code. The spec branch is 18 commits behind main.

## Global Constraints

- High tier (pairing, identity, keys): every task's reviewer is fresh and on the Pi, and the whole peer suite passes before the train (lesson 26).
- An assertion lives at most 30 days (`expires - issued <= 30 * 86400`); one whose `issued` is more than 300 seconds after now is refused.
- An owner trust lasts at most 90 days, whole days 1 to 90, and can be renewed.
- At most 200 contacts per owner trust per UTC day, counted from `trust_confirmations`.
- A ship's name fullmatches `SHIP_NAME` (ships.py:15) and differs, by `casefold()`, from every local user's `name` and `username` and from every remote contact's name that has no trust confirmation.
- The contact's stored name is exactly `ship of <owner name>: <ship name>`.
- The grant reads exactly: `ships owned by <name> on <peer 12> may be paired by this station's ships, until <YYYY-MM-DD>` (UTC date).
- `connections()` and the CLI say exactly `confirmed by owner trust`.
- Every refusal writes nothing, except a cap refusal, which writes only its `trust_cap_refusals` count.
- `owner_trust` is append-only: SQLite triggers abort any UPDATE or DELETE on it.
- No new command prints, shows or computes a pairing code. A ship never grants, renews or revokes a trust; those routes take a person's session (`current_user`), and a ship key gets 403.
- Every name in a notice or a CLI line goes through `safe_line`.
- New modules and test files join both lists in `peer/pyproject.toml` (wheel and sdist), as `join_plan.py` did.

## Review Focus

1. An assertion whose `issued` or `expires` is a bool, a float, NaN, a string or out of range: refused as invalid, never a crash or a pass. (Task 1)
2. Two ships pairing at once at 199 of the cap: one pairs, one is refused; the count and the insert share the `BEGIN IMMEDIATE` transaction. (Task 3)
3. Andy unpairs the owner's peer and later pairs it again with a typed code: the old trust stays revoked and its ships stay held; only a new grant and fresh assertions bring them back. (Task 4)
4. `pair-trusted` given a missing file, a directory, a non-JSON or 7 MB file, or an assertion with extra keys: one line on stderr, exit 1, nothing written. (Task 3)
5. An owner name holding a newline, `@rio-grande` or 300 characters: the digest is one safe line that mentions no one, and the stored label still starts `ship of `. (Task 6)

---

### Task 1: The signed ship assertion and `export-ship`

**Files:**
- Modify: `peer/superyak_peer/identity.py` (RECORD_KEYS, two new functions)
- Modify: `peer/superyak_peer/__main__.py` (an `export-ship` subcommand beside `card`)
- Test: `peer/tests/test_owner_trust.py` (new; its fixtures serve Tasks 1 to 4 and 6)

**Interfaces:**
- Produces: `RECORD_KEYS['ship-assertion'] = frozenset({'kind', 'station', 'ship_id', 'ship_name', 'owner_id', 'issued', 'expires'})`; `ASSERTION_DAYS = 30`; `FUTURE_SLACK = 300`.
- Produces: `make_ship_assertion(identity: PeerIdentity, *, ship_id: str, ship_name: str, owner_id: str, now: int, days: int = 30) -> dict`, returning `{'record': <record>, 'signature': <base64>}` (exactly those two keys), signed with `identity.sign_record`.
- Produces: `check_ship_assertion(card: dict, assertion: dict, now: float) -> dict`, returning the record or raising `Problem(400, <reason>)`. It uses `verify_record(card, record, signature)` and then the times: ints only (`type(x) is int`, so no bool), `issued <= now + 300`, `expires > now`, `0 < expires - issued <= 30 * 86400`.
- Produces: CLI `export-ship --data-dir D --username <ship> (--endpoint URL | --pull) --out DIR`, writing `DIR/<ship>.card.json` and `DIR/<ship>.assertion.json`. The card is `identity.card(endpoint, {'id': ship.id, 'name': ship.username})`: the username, which docking already holds to SHIP_NAME (ruling: users.name may be capitalised and would fail SHIP_NAME). It never makes an identity (refuse when `identity.json` is missing, as `federate` does), and it prints the two paths and no code.

- [ ] **Step 1: Write the failing tests.** Fixture `machine(tmp_path)`: a Store with person `andy-b` (admin), ship `tardis` owned by him (via `Ships._new_ship`), an identity, and `Federation(store, endpoint='https://localhost:7435')`.
  - `test_an_assertion_verifies_under_its_peers_card`: `check_ship_assertion(card, make_ship_assertion(...), now)` returns the record with `ship_name == 'tardis'`.
  - `test_an_assertion_signed_by_another_key_or_edited_is_refused`: another peer's identity signs it → 400; the `record['ship_name']` edited after signing → 400.
  - `test_an_expired_or_long_or_future_assertion_is_refused`: `expires == now` → 400; `expires - issued == 30 * 86400 + 1` → 400; `issued == now + 301` → 400; `issued == now + 300` passes.
  - `test_assertion_times_must_be_whole_seconds` (Review Focus 1): `issued` of `True`, `1.5`, `float('nan')`, `'1'` → 400 each, never another exception.
  - `test_export_ship_writes_a_card_and_assertion_and_no_code`: run the CLI by `subprocess` (as test_join_plan.py does); both files exist, the assertion checks under the card, and stdout and stderr contain no 32-hex run and no `show_code` grouping (`re.search(r'[0-9a-f]{4}( [0-9a-f]{4}){7}', out)` is None).
  - `test_export_ship_refuses_a_person_and_an_ownerless_ship`: `--username andy-b` → exit 1, "not a ship"; a station ship from `create_station_ship('odo', 'Odo')` → exit 1, "owner"; nothing written in `--out`.

- [ ] **Step 2: Run them to see them fail.** `cd peer && uv run --locked pytest tests/test_owner_trust.py -q` → FAIL, `ImportError: make_ship_assertion`.

- [ ] **Step 3: Implement** the RECORD_KEYS entry, the two functions in identity.py, and `export-ship` in `__main__.py`. Owner check: `ship.kind == 'ship'`, `ship.owner_id` names a user whose `kind == 'person'`. `owner_id` in the record is that person's `users.id`, which is the participant id on the person card the station paired.

- [ ] **Step 4: Run them to see them pass.** Same command → 6 passed.

- [ ] **Step 5: Commit.** `git add peer/superyak_peer/identity.py peer/superyak_peer/__main__.py peer/tests/test_owner_trust.py peer/pyproject.toml && git commit -m "Owner trust 1: the peer-signed ship assertion and export-ship"`

### Task 2: The owner trust table, granting and renewing

**Files:**
- Create: `peer/superyak_peer/owner_trust.py`
- Modify: `peer/superyak_peer/db.py:28-98` (import, mixin, schema in the `executescript`)
- Test: `peer/tests/test_owner_trust.py`

**Interfaces:**
- Produces: `OWNER_TRUST_SCHEMA`, with:
  - `owner_trust(seq INTEGER PRIMARY KEY AUTOINCREMENT, grant_id TEXT NOT NULL, event TEXT NOT NULL CHECK(event IN ('grant','renew','revoke')), peer_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, until REAL, by_id TEXT, at REAL NOT NULL, reason TEXT)`, plus triggers `owner_trust_no_update` and `owner_trust_no_delete` that `RAISE(ABORT, 'owner_trust is append-only')`;
  - `trust_confirmations(id TEXT PRIMARY KEY, contact_id TEXT NOT NULL, grant_id TEXT NOT NULL, assertion TEXT NOT NULL, acting_ship_id TEXT NOT NULL, confirmed REAL NOT NULL, day TEXT NOT NULL)`;
  - `trust_cap_refusals(grant_id TEXT NOT NULL, day TEXT NOT NULL, refused INTEGER NOT NULL, PRIMARY KEY(grant_id, day))`;
  - `retired_peers(peer_id TEXT PRIMARY KEY, retired REAL NOT NULL, by_id TEXT)`.
- Produces: `TRUST_DAYS = 90`; `code_current(db, contact_id: str) -> bool`, the rule `connections()` uses now (federation.py:189: the confirmation's code equals `pairing_code` of the stored card with this contact's participant, and the peer is paired). Task 6 makes `connections()` call it.
- Produces: `live_trust(db, peer_id: str, owner_user_id: str, now: float) -> sqlite3.Row | None`, the unrevoked trust for that owner with its latest `until`, or None. A grant is revoked once any of its rows is `revoke`.
- Produces on `Store` (mixin `OwnerTrust`): `grant_owner_trust(actor, contact_id, *, days, password, source, public=True, device=None) -> dict` and `renew_owner_trust(actor, grant_id, *, days, password, source, public=True, device=None) -> dict`. Both return `{'grant_id', 'until', 'text'}`, where `text` is the Global Constraints grant line. Both take `_admin(db, actor)` and `check_password_attempt` (as `confirm_imprint` does, imprints.py:948), and refuse 401 on a wrong password.

- [ ] **Step 1: Write the failing tests.** Fixture `paired(tmp_path)`: station Store `A` (admin `andy`) and machine `B` from Task 1's fixture; A pairs B's `andy-b` card with `code=pairing_code(card)`, as `two_peers` does (tests/test_federation.py:20).
  - `test_a_grant_reads_as_the_spec_says`: `text == f"ships owned by Andy B on {peer[:12]} may be paired by this station's ships, until {date}"` for `days=90`.
  - `test_a_grant_needs_the_admins_password_and_whole_days_1_to_90`: a wrong password → 401; `days` of 0, 91, `'90'`, `True` → 400; nothing written in `owner_trust` each time.
  - `test_a_grant_needs_a_code_typed_for_that_contact`: a contact whose `pairing_confirmations` row is deleted → 409; a held contact → 409; a second grant while one is live → 409 ("renew it").
  - `test_renewing_extends_and_owner_trust_is_append_only`: renew adds a `renew` row with a later `until`; `UPDATE owner_trust SET until=0` and `DELETE FROM owner_trust` each raise `sqlite3.IntegrityError` (RAISE(ABORT) surfaces as IntegrityError).

- [ ] **Step 2: Run them to see them fail.** `cd peer && uv run --locked pytest tests/test_owner_trust.py -q -k "grant or renew"` → FAIL, no `grant_owner_trust`.

- [ ] **Step 3: Implement** `owner_trust.py` and wire it into `Store` and the schema. The tables are created with the rest of the schema; an older store gains them at open, as every `CREATE TABLE IF NOT EXISTS` does.

- [ ] **Step 4: Run them to see them pass,** then the whole file → all passed.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 2: the append-only owner_trust table, granted and renewed with the admin's password"`

### Task 3: `pair-trusted` and the cap

**Files:**
- Modify: `peer/superyak_peer/federation.py` (new `Federation.pair_trusted`)
- Modify: `peer/superyak_peer/__main__.py` (`pair-trusted` subcommand)
- Test: `peer/tests/test_owner_trust.py`

**Interfaces:**
- Consumes: `check_ship_assertion` (Task 1); `live_trust`, `code_current`, the tables (Task 2).
- Produces: `Federation.pair_trusted(actor: str, card: dict, assertion: dict) -> dict`, returning the contact row plus `{'confirmed_by': 'owner trust', 'grant_id': ...}`. `actor` is a local `users.id` with `kind='ship'` and an owner; anyone else is 403.
- Produces: `TRUST_CAP = 200`; CLI `pair-trusted --data-dir D --card FILE --assertion FILE --as <ship username>`: exit 0 with `Paired <safe label>, confirmed by owner trust.`, exit 1 with the refusal's message. It needs no terminal and reads each file with `identity.parse(raw)` (limit `MAX_ENVELOPE`).

The checks, in this order, all inside one `self.store.transaction()`, each refusal a `Problem` raised before any write:
1. `validate_card(card)`; its peer is in `peers` with `paired=1` and not in `retired_peers`.
2. The card equals the stored card apart from `participant`: `canonical({**stored, 'participant': card['participant']}) == canonical(card)`.
3. `check_ship_assertion(stored_card, assertion, now)` passes, and `record['ship_id'] == card['participant']['id']` and `record['ship_name'] == card['participant']['name']`.
4. The owner is the contact `(record['station'], record['owner_id'])` on that peer: it exists, it isn't held, `code_current` holds, and it has no `trust_confirmations` row.
5. `live_trust(db, peer, owner_id, now)` exists, and `record['issued']` is after every `revoke` row's `at` for that owner (S8, one rule for new ships and re-paired ones).
6. The name fullmatches `SHIP_NAME` and doesn't collide (Global Constraints).
7. `(peer, ship_id)` isn't in `remote_contacts` (Task 4 adds the one exception).
8. Fewer than 200 `trust_confirmations` rows for this grant with today's UTC `day`. At the cap, the transaction raises; then, in a second transaction, `INSERT ... ON CONFLICT(grant_id, day) DO UPDATE SET refused=refused+1`; then the 429 is raised to the caller.

On success: insert `remote_contacts` with name `ship of <owner name>: <ship name>`, and a `trust_confirmations` row (the assertion's canonical JSON, the acting ship, now, today's day).

- [ ] **Step 1: Write the failing tests.** Fixture `trusted(paired)`: Task 2's fixture plus a live grant, and B's `export-ship` output for `tardis`. One test per spec refusal, each asserting the Problem and that `remote_contacts`, `trust_confirmations` and `owner_trust` row counts are unchanged:
  - `test_no_trust`, `test_an_expired_trust` (store clock past `until`: a new ship is refused, and a ship paired before it expired is still paired and not held), `test_a_trust_whose_owners_code_was_never_typed` (the confirmation deleted after granting), `test_a_held_owner` (a `contact_holds` row for the owner);
  - `test_a_card_whose_other_fields_differ` (endpoint changed), `test_a_participant_that_differs_from_the_assertions`;
  - `test_a_forged_card_from_a_public_card` (B's person card with a new `participant` and no assertion signed for it → refused at check 3);
  - `test_an_owner_on_another_peer` (M3): a third peer C, paired, whose contact shares `andy-b`'s user id; an assertion signed by C naming that id, for a trust granted on B's owner → refused;
  - `test_names_that_fail_ship_name_or_collide`: `Tardis`, `andy`, `andy-b` (a local username), and the remote person contact's own name casefolded → each refused;
  - `test_a_contact_that_already_exists` (the same card twice);
  - `test_the_cap`: 200 pair, the 201st → 429 with `trust_cap_refusals.refused == 1` and nothing else written;
  - `test_two_pairings_at_the_cap_pair_one` (Review Focus 2): 199 rows seeded, two threads, each with its own `Federation` on its own `Store` over the same directory → exactly one succeeds;
  - `test_pair_trusted_cli_refuses_bad_files` (Review Focus 4): a missing path, a directory, `not json`, a 7 MB file, an assertion with an extra key → exit 1, one stderr line, counts unchanged;
  - `test_a_ship_pairs_and_shows_its_owner_first`: the success path; the contact's name is `ship of Andy B: tardis`.

- [ ] **Step 2: Run them to see them fail.** `uv run --locked pytest tests/test_owner_trust.py -q -k "not grant and not renew"` → FAIL, no `pair_trusted`.

- [ ] **Step 3: Implement** `pair_trusted` and the CLI.

- [ ] **Step 4: Run them to see them pass,** then the whole file.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 3: pair-trusted, every check in one transaction, and the cap of 200 a day"`

### Task 4: Ending a trust: revoke, holds, retire

**Files:**
- Modify: `peer/superyak_peer/owner_trust.py` (`settle_owner_trust`, `hold_contact`, `revoke_owner_trust`)
- Modify: `peer/superyak_peer/federation.py:101-164` (`pair` refuses a retired peer and settles; `unpair(..., retire=False)` settles; `pair_trusted`'s held-ship exception)
- Test: `peer/tests/test_owner_trust.py`

**Interfaces:**
- Produces: `hold_contact(db, contact: sqlite3.Row, now: float) -> None`, doing what `_hold_like_replaced` does for one contact (backups.py:813): a `contact_holds` row, its `pairing_confirmations` gone, its pending and failed outbox rows withdrawn, and the inbox payloads it authored nulled.
- Produces: `settle_owner_trust(db, now: float) -> list[str]`, the grant ids it revoked. (a) Every unrevoked grant whose owner contact is missing or held, whose peer is unpaired or retired, or whose owner fails `code_current` gets a `revoke` row with reason `owner held` and `by_id` NULL. (b) Every contact whose latest `trust_confirmations` row (by `confirmed`) names a revoked grant, and which isn't held, is held with `hold_contact`.
- Produces: `Store.revoke_owner_trust(actor, grant_id) -> dict`, returning `{'grant_id', 'held': <count>}`, admin only, 409 when already revoked (no second row).
- Produces: `Federation.unpair(actor, contact_id, *, retire: bool = False)`. With `retire`, it writes `retired_peers(peer, now, actor)` before settling. Ruling: there is no `unpair` CLI today, so the spec's `unpair --retire` is this flag, reached from the browser in Task 7.
- Changes `pair()`: a peer id in `retired_peers` is refused (409, "This peer was retired; it comes back only as a new identity") before the code is compared. Once its writes are done, `pair()` calls `settle_owner_trust`.
- Changes `pair_trusted` check 7: an existing contact passes only if it's held, its latest `trust_confirmations` grant is revoked and belonged to the same `(peer, owner)`, and the live trust's first `grant` row is later than that revocation. The re-pair deletes the hold and adds a new `trust_confirmations` row.

- [ ] **Step 1: Write the failing tests.**
  - `test_revoking_holds_every_ship_and_withdraws_their_outbox`: two ships paired, one pending outbox row queued for each by hand; revoke → both held, outbox `withdrawn`, `held == 2`; revoke again → 409, still one `revoke` row.
  - `test_holding_the_owner_holds_its_ships_and_dates_it` (N13): unpair B → the trust has a `revoke` row (reason `owner held`) and both ships are held.
  - `test_repairing_the_owners_peer_does_not_bring_the_trust_back` (Review Focus 3): unpair B, then `pair` B's person card with its code → the owner is live again, the trust stays revoked, the ships stay held, and `pair_trusted` with the old assertion is refused.
  - `test_a_held_ship_repairs_only_under_a_later_trust_and_a_fresh_assertion`: revoke, grant anew, re-pair with an assertion issued before the revocation → refused; with one issued after → paired, hold gone.
  - `test_pair_refuses_a_retired_peer_whatever_code_is_typed` (S11): `unpair(retire=True)`, then `pair` with the right code → 409; `retired_peers` holds it.

- [ ] **Step 2: Run them to see them fail.** `-k "revok or hold or retire or repair"` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** `tests/test_owner_trust.py` and `tests/test_federation.py tests/test_federation_pull.py` → all passed. Those are pair's and unpair's own suites, and nothing in them may change.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 4: revoking and any hold of the owner hold its ships; a retired peer never pairs again"`

### Task 5: Restore never brings a revoked trust back

**Files:**
- Modify: `peer/superyak_peer/backups.py` (two steps and the report; the step lists at backups.py:1452-1466)
- Test: `peer/tests/test_owner_trust_restore.py` (new; use `tests/test_restore.py`'s helpers for a staged copy and a replaced file)

**Interfaces:**
- Consumes: `settle_owner_trust`, `OWNER_TRUST_SCHEMA` (Tasks 2 and 4).
- Produces: `_keep_trust_like_replaced(db, old, now, report)`, in the replaced-file list after `_hold_like_replaced`. For each `revoke` row in `old` whose `grant_id` has rows here but no `revoke`, insert it here with the same `at`, `by_id` and `reason`. For each `retired_peers` row in `old` that's missing here, insert it and `_unpair(db, old, peer, report)` when that peer is paired.
- Produces: `_revoke_every_trust(db, old, now, report)`, in the no-replaced-file list. Every unrevoked grant gets a `revoke` row with reason `restored`, and `report` gains the line `TRUST_RETIREMENTS_NOT_KEPT = 'Peers retired since the copy were not kept: unpair them as retired again before anything pairs.'`
- After both lists, and before `_unpair_named`, `settle_owner_trust(db, now)` runs. A copy from before this build first gains the tables, one `CREATE` statement at a time (`executescript` would commit the reconcile, backups.py:861).
- `report['trusts']`: `(grant short id, owner name, how)`, printed through `safe_line` beside `report['held']`.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_revocation_after_the_copy_is_kept`: copy taken with the trust live and one ship paired; revoke live; restore the copy with the replaced file → the trust is revoked, the ship held.
  - `test_a_retirement_after_the_copy_is_kept`: retire live after the copy; restore → `retired_peers` has it, the peer is unpaired, and `pair` refuses it.
  - `test_without_a_replaced_file_every_trust_is_revoked`: restore with none → every trust revoked (`restored`), its ships held, and the report carries `TRUST_RETIREMENTS_NOT_KEPT`.
  - `test_a_copy_from_before_owner_trust_restores`: the copy's tables dropped first → the reconcile succeeds and the tables exist.

- [ ] **Step 2: Run them to see them fail.** `uv run --locked pytest tests/test_owner_trust_restore.py -q` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** the new file plus `tests/test_restore.py tests/test_backups.py` → all passed.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 5: a restore re-applies revocations and retirements made after the copy, and settles"`

### Task 6: Seeing it: connections, the daily digest, `station-trust-list`

**Files:**
- Modify: `peer/superyak_peer/federation.py:166-194` (`connections`)
- Modify: `peer/superyak_peer/__main__.py` (`contact_state`, `describe_connections`, a `station-trust-list` subcommand)
- Modify: `peer/superyak_peer/ships.py:487` (`station_notices` appends the digests)
- Modify: `peer/superyak_peer/owner_trust.py` (`trust_digests`, `trust_list`)
- Modify: `Makefile` (`station-trust-list`, beside `station-rooms`)
- Test: `peer/tests/test_owner_trust.py`

**Interfaces:**
- `connections()` gives each contact `confirmed_by`: `'typing'`, `'owner trust'` or None. A trust contact is confirmed when it has a `trust_confirmations` row, isn't held and its peer is paired. Each code-confirmed contact also gets `owner_trust`: `{'grant_id', 'until', 'live'}` or None. `contact_state` returns `confirmed by owner trust` for a trust contact.
- `trust_digests(db, now) -> list[dict]`: one notice per grant per UTC day that ended in the last 7 days and had a pairing or a cap refusal. Its id is `trust-digest-<grant_id[:12]>-<YYYY-MM-DD>`. Ruling on N12: a notice is posted once the day has ended, because the watcher refuses a changed text under a used id (agent/superyak_agent/watch.py:368). Its text is `Owner trust, <day>: <n> ship(s) of <owner> on <peer 12> paired by <acting ships>[; <r> refused at the cap of 200]. Full ids: make station-trust-list on the Pi.`, with every name through `safe_line`.
- `trust_list(db) -> list[dict]` and CLI `station-trust-list --data-dir D`: one line per trust (grant short id, owner, peer 12, until, live or revoked and why), then each of its ships with the full participant id, the acting ship and when.

- [ ] **Step 1: Write the failing tests.**
  - `test_connections_say_confirmed_by_owner_trust`: a trust ship → `confirmed_by == 'owner trust'`, `confirmed is True`, `pairing_code is None`; the owner → `confirmed_by == 'typing'` with `owner_trust['live'] is True`; `describe_connections` holds `confirmed by owner trust`.
  - `test_the_digest_comes_once_the_day_ends`: three ships today → no digest; clock past UTC midnight → one notice with `3 ship(s)`, the peer's 12 and the acting ship.
  - `test_the_digest_is_one_safe_line` (Review Focus 5): owner name `'Andy\n@rio-grande ' + 'x' * 300` → no `\n`, no `@rio-grande`, and the label still starts `ship of `.
  - `test_station_trust_list_names_full_ids`: the CLI lists the ship's full participant id.

- [ ] **Step 2: Run them to see them fail.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** the file plus `tests/test_ships.py tests/test_ship_agent.py`, which hold the station_notices tests → all passed.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 6: connections say confirmed by owner trust; a daily digest in Ops; station-trust-list"`

### Task 7: The browser: grant, renew, revoke, retire

**Files:**
- Modify: `peer/superyak_peer/peer_routes.py` (routes beside `/api/connections/pair`)
- Modify: `peer/superyak_peer/static/app.js` (`connectionGroup`, about line 992)
- Test: `peer/tests/test_owner_trust_browser.py` (new; the server fixture as in `tests/test_imprint_browser.py`)

**Interfaces:**
- `POST /api/connections/{contact_id}/trust` takes `{days, password}` and returns 201 with `grant_owner_trust`'s dict. `POST /api/owner-trust/{grant_id}/renew` takes `{days, password}`. `POST /api/owner-trust/{grant_id}/revoke` takes `{}`. Each takes `current_user` (a person with CSRF, so a ship key gets 403). The two password routes run in `app.state.sign_in_lane` as `imprint_confirm` does (app.py:882).
- `DELETE /api/connections/{contact_id}` with `{"retire": true}` calls `unpair(..., retire=True)`.
- The UI. Under each code-confirmed person contact, a button "Trust ships owned by <name>" opens a form. The form shows the grant line, a days field (default 90, min 1, max 90), a password field and Grant. A live trust shows its line, Renew and Revoke. A trust contact shows "ship of <owner>: <name>, confirmed by owner trust". The unpair control gains "Unpair as retired (this machine may be compromised)". Names are escaped as the view already escapes them.

- [ ] **Step 1: Write the failing tests.**
  - `test_a_ship_key_cannot_grant_or_revoke` (TestClient): 403 on all three routes with a ship's bearer key.
  - `test_a_wrong_password_is_counted_as_a_sign_in` (TestClient): 401, and a failed attempt is recorded as `/api/login` records one.
  - `test_granting_in_the_browser` (Playwright): open Connections, press the button, the grant line shows verbatim, Grant without a password does nothing, Grant with it shows the live trust and Revoke.

- [ ] **Step 2: Run them to see them fail.** `uv run --locked pytest tests/test_owner_trust_browser.py -q` → FAIL.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run** the file plus `tests/test_browser.py` → all passed.

- [ ] **Step 5: Commit.** `git commit -m "Owner trust 7: grant, renew and revoke in the browser with the admin's password; unpair as retired"`

### Task 8: The law lines and the make target

**Files:**
- Modify: `CLAUDE.md` ("Pairing peers (every machine)")
- Modify: `Makefile` (`station-pair-trusted CARD= ASSERTION= SHIP=`)
- Modify: `peer/pyproject.toml` (confirm every new file is listed), `docs/checklists.md` if a checklist names pairing

- [ ] **Step 1: Add the target.** `station-pair-trusted` refuses a missing `CARD`, `ASSERTION` or `SHIP` with a usage line, then runs `pair-trusted --data-dir "$(STATION_DATA)" --card "$(CARD)" --assertion "$(ASSERTION)" --as "$(SHIP)"`.
- [ ] **Step 2: Draft the CLAUDE.md lines,** appended to "Pairing peers": "Within an owner trust, a ship may pair another machine's ship with no code: on that machine, `export-ship --username <ship>` writes its card and a signed assertion; here, `make station-pair-trusted CARD= ASSERTION= SHIP=<this ship>`. The trust is Andy's act alone, granted, renewed and revoked in the station's browser with his password, and a ship never grants, renews or revokes one, runs it under a pty or a wrapper, or types the password. `make station-trust-list` names every ship paired that way; Odo's daily digest in Ops counts them." These lines bind the ships, so they land only with Andy's yes in the harness (spec, "What it costs Andy"). Ask him once, in the room, with the text.
- [ ] **Step 3: Run the whole peer suite.** `cd peer && uv run --locked pytest -q` → all passed (lesson 26). Then `make -n station-pair-trusted CARD=a ASSERTION=b SHIP=c` prints the command.
- [ ] **Step 4: Commit.** `git commit -m "Owner trust 8: make station-pair-trusted, and the pairing law's new lines"`

## After the tasks

A fresh Pi reviewer reads the whole branch (High tier), and its verdict is posted whole. Then the branch goes into a train with `make merge-sitting`, run from a shell, never from a woken run. On the Pi, Andy's acts in order are: his yes to the CLAUDE.md lines, then one grant in the browser for his contact on Tardis's peer. The first real use is the tardis ship: `export-ship` on Tardis's machine, then `make station-pair-trusted` here, with no code.
