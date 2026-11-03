# Lessons Room Adds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rio Grande adds to the lessons room, with `make station-lessons-add CONTACT=`, a remote account Andy's typed code
or his confirmed listing already vouched for, and a trust-made ship under its owner's live trust, bounded by holds,
pauses and one cap per grant.

**Architecture:** The peer package gains two columns on `pairing_confirmations` (who typed the code, and whether `pair`
showed the lessons line), a `reason` on `member_changes`, and a `lessons_addable` table the listing's CONFIRM run
fills. One new verb in `superyak_peer.lessons` runs every check and then the existing `_add_members` as the room's
recorded ship. A SQL-only helper, called at every site that holds a contact, takes trust-made members out of the
chain with reason `held`, so the restore's raw connection can call it too.

**Tech Stack:** Python 3, SQLite (the peer's `Store`), pytest; the browser client in `peer/superyak_peer/static/app.js`.

**Spec:** `docs/superpowers/specs/2026-11-03-lessons-room-adds-design.md` (approved rev 5). It builds on owner trust
(`docs/superpowers/specs/2026-11-02-machine-trust-design.md`, branch owner-trust, merged into this branch at d1eb34da).

## Global Constraints

- High tier (pairing, identity, room membership). Each task gets a fresh reviewer; the whole branch gets a fresh Pi
  reviewer whose verdict is posted whole; the Pi suites pass before it merges (station law section 2).
- Every refusal writes nothing: each act is one `self.transaction()` (BEGIN IMMEDIATE), and refusals raise before any
  write.
- No code path prints, logs, posts or returns a pairing code. `lessons_addable` stores `sha256(code)` hex, never the
  code. A ship never types a pairing code; tests type them through the existing `paired()` helper only.
- Text bound for the browser goes through `plain_name` (owner_trust.py) and `escapeHtml`/`isolatedName` (app.js);
  CLI text through `plain_name`; Ops notice text through `safe_line` (ships.py:38).
- Any positional `INSERT` into a table this plan widens becomes a named-column insert: federation.py:217,
  tests/test_federation.py:1433, tests/test_join_plan.py:59, 74, 102.
- `CLAUDE.md` is never edited by an implementer. The controller applies the drafted lines (Task 7) after Andy's yes.
- Tests run on the Pi with `cd peer && TMPDIR=/var/tmp .venv/bin/python -m pytest …`.
- Every commit message ends with "Made by Rio Grande." and the `Co-Authored-By` trailer.

## Rulings made in this plan

- **The column is `typed_by`, not `confirmed_by`.** `connections()` already returns a computed `confirmed_by`
  (`'typing'`, `'owner trust'` or None; federation.py:369, app.js:1045). Two things with one name would mislead.
  `typed_by` is the spec's `confirmed_by` column: the admin who typed the code.
- **`lessons_line` is written as shown AND listed.** `Federation.pair` takes `lessons_line_shown` from its caller (the
  CLI passes whether it printed the line; the browser passes back the preview's flag) and writes 1 only when that's
  true and the peer is listed in `pair`'s own transaction.
- **The hold notice is an Ops notice, not a room post.** A restore holds contacts on a raw `sqlite3` connection with no
  `Store` to post through. So every hold, on every path, writes `member_changes` rows (reason `held`), and Odo posts one
  Ops notice per batch from `station_notices`, as it does for adds.
- **Addable excludes current members and contacts Andy removed,** in the listing view as in the add.

## Review Focus

1. **A contact short id that matches two contacts** is refused as ambiguous, writing nothing (Task 4).
2. **Pairing an account on a listed peer when no lessons room is recorded,** or on a peer that isn't its origin: no
   line is shown, and `lessons_line` is 0 (Task 2).
3. **Names carrying bidi controls or format characters** in the pair line, the listing view, the add's output and both
   notices are shown plain, and can't reorder the line (Tasks 2, 3, 4, 7).
4. **An add racing a CONFIRM rerun of the listing:** the add reads `lessons_addable` inside its own transaction, so it
   sees either the old table or the new one, never half (Task 4).
5. **Restoring a backup from before this build** (no `typed_by`, `lessons_line`, `reason` or `lessons_addable`):
   it restores with NULLs and zeros, and its accounts become addable only through the listing view (Task 1).

---

### Task 1: Schema, the pair record, and the restore lists

**Files:**
- Modify: `peer/superyak_peer/db.py:100-135` (the additive ALTER block)
- Modify: `peer/superyak_peer/lessons.py:1439` (`LESSON_SCHEMA`)
- Modify: `peer/superyak_peer/federation.py:164-223` (`Federation.pair`)
- Modify: `peer/superyak_peer/members.py:148` (`_owner_removed`), `members.py:58` (`_record_change`)
- Modify: `peer/superyak_peer/backups.py:389-419` (`COMPARED`), `_usable` callers
- Modify: the positional inserts named in Global Constraints
- Test: `peer/tests/test_lessons_adds.py` (new)

**Interfaces:**
- Produces: columns `pairing_confirmations.typed_by TEXT REFERENCES users(id)` (NULL allowed) and
  `pairing_confirmations.lessons_line INTEGER NOT NULL DEFAULT 0`; `member_changes.reason TEXT` (NULL, or `'held'`);
  table `lessons_addable(contact_id TEXT PRIMARY KEY REFERENCES remote_contacts(id), code_digest TEXT NOT NULL,
  typed_by TEXT, listed REAL NOT NULL)`.
- Produces: `Federation.pair(self, actor, card, *, code, lessons_line_shown=False)`.
- Produces: `_record_change(self, db, change, room_id, member_id, actor_id, grant_id, *, reason=None, **counts)`.
- Produces: the test fixture `adds` in `test_lessons_adds.py`, built on conftest's `lessons_peers`: returns a
  `SimpleNamespace(pi, pi_fed, tardis, tardis_fed, ids, room, key, clock, deliver, pair_new)`, where
  `pair_new(username, *, lessons_line_shown=False)` makes a ship account on Tardis and pairs its card on the Pi by
  Andy's typed code (the way conftest's `paired()` does, passing `lessons_line_shown` through), returning the Pi's
  contact id.

- [ ] **Step 1: Write the failing tests**

```python
def test_pair_records_who_typed_and_whether_the_line_was_shown(adds):
    contact = adds.pair_new('defiant', lessons_line_shown=True)      # Tardis is listed
    row = confirmation(adds.pi, contact)
    assert row['typed_by'] == adds.ids['andy'] and row['lessons_line'] == 1

def test_the_line_flag_needs_the_peer_listed_in_pairs_own_transaction(adds_unlisted):
    contact = adds_unlisted.pair_new('defiant', lessons_line_shown=True)
    assert confirmation(adds_unlisted.pi, contact)['lessons_line'] == 0

def test_a_line_not_shown_is_not_recorded(adds):
    assert confirmation(adds.pi, adds.pair_new('defiant'))['lessons_line'] == 0

def test_owner_removed_skips_held_rows(adds):
    # a 'remove' row with reason 'held' after an 'add' leaves _owner_removed False;
    # an owner 'remove' row with reason NULL after it makes it True
    ...

def test_restore_keeps_the_new_columns_and_table(adds, tmp_path):
    # back up, restore: typed_by, lessons_line, member_changes.reason and lessons_addable rows compare equal

def test_restore_of_a_backup_from_before_the_build(adds, tmp_path):
    # drop the four from a backup copy, restore: typed_by NULL, lessons_line 0, reason NULL, lessons_addable empty
```

`confirmation(store, contact)` reads the `pairing_confirmations` row. `adds_unlisted` is `adds` before the listing's
CONFIRM run names Tardis. Fill in the two bodies marked `...`/comment with the assertions their names state.

- [ ] **Step 2: Run them to see them fail**

Run: `cd peer && TMPDIR=/var/tmp .venv/bin/python -m pytest tests/test_lessons_adds.py -q`
Expected: FAIL (`typed_by` unknown, `lessons_line_shown` unexpected).

- [ ] **Step 3: Implement**

The two columns and `reason` go in db.py's ALTER block with a `PRAGMA table_info` check, as `outbox.last_error`
does (db.py:130-131). `lessons_addable` goes in `LESSON_SCHEMA`. `pair` writes the confirmation with named columns:
`typed_by` is `actor`; `lessons_line` is `1` when `lessons_line_shown` and `SELECT 1 FROM lessons_peers WHERE
peer_id=?` and a recorded `lessons_room` at this origin, all in its transaction. `_owner_removed` adds
`AND (reason IS NULL OR reason != 'held')` to its row query. `COMPARED` gains `pairing_confirmations.typed_by`,
`pairing_confirmations.lessons_line`, `member_changes.reason` and the `lessons_addable` columns; an old file without
them goes through `_usable`'s not-compared path.

- [ ] **Step 4: Run them to see them pass**, plus `tests/test_federation.py tests/test_join_plan.py tests/test_member_changes.py tests/test_moderator_acts.py tests/test_owner_trust_restore.py`
Expected: PASS.

- [ ] **Step 5: Commit**

---

### Task 2: `pair` says what it makes addable, before the code

**Files:**
- Modify: `peer/superyak_peer/__main__.py:366-392` (`pair_command`)
- Modify: `peer/superyak_peer/peer_routes.py:117-126` (preview and pair routes)
- Modify: `peer/superyak_peer/static/app.js:1431` (`connectionsView`), `:2316` (`previewPair`), `:2328` (`confirmPair`)
- Modify: `peer/superyak_peer/lessons.py` (the line's text and the function below)
- Test: `peer/tests/test_lessons_adds.py`, `peer/tests/test_cli.py`, `peer/tests/test_owner_trust_browser.py` (or the
  browser test file that drives the pair box)

**Interfaces:**
- Consumes: Task 1's `pair(..., lessons_line_shown=)`.
- Produces: `lessons_line_for(db, card) -> str | None` in `lessons.py`: the line, or None when the card's peer isn't
  listed, no room is recorded, or this peer isn't the origin. The line's text is exactly:
  `"{name} on {peer12} can be added to the lessons room by {ship} once you type its code; its lessons would reach every ship."`
  with `name = plain_name(card participant name)`, `peer12 = card peer_id[:12]`, `ship` the recorded ship's
  account name.
- Produces: the preview route's JSON gains `lessons_line` (string or null).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_cli_says_the_line_before_its_code_prompt(...):      # in test_cli.py, with in_pty
    out = ...  # the pty's output up to PAIR_PROMPT
    assert out.index('can be added to the lessons room by Rio-Grande') < out.index(PAIR_PROMPT)
    assert confirmation(...)['lessons_line'] == 1

def test_the_cli_says_nothing_for_an_unlisted_peer(...):
    assert 'lessons room' not in out and confirmation(...)['lessons_line'] == 0

def test_no_line_without_a_recorded_room_or_off_the_origin(...):
    assert lessons_line_for(db, card) is None   # each case

def test_the_line_names_a_bidi_name_plainly(adds):
    # a participant named 'Def‮iant' shows as 'Defiant' in the line

def test_the_browser_shows_the_line_beside_the_code_box_and_sends_it_back(...):
    # preview JSON has lessons_line; the rendered form holds it, escaped and isolated; confirmPair posts lessons_line_shown=true
```

Use the recorded ship's account name as the fixture sets it; the test asserts on that name, whatever it is.

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `pair_command` calls `lessons_line_for` after the card is read and before `PAIR_PROMPT`,
  prints the line when there is one, and passes `lessons_line_shown=bool(line)`. The preview route adds
  `lessons_line`; `connectionsView` shows it in the confirm form above `#pair-code`; `confirmPair` sends
  `lessons_line_shown: Boolean(state.pairPreview.lessons_line)`; the pair route passes it through.
- [ ] **Step 4: Run them to see them pass**, plus `tests/test_cli.py` whole.
- [ ] **Step 5: Commit**

---

### Task 3: The listing names the addable accounts

**Files:**
- Modify: `peer/superyak_peer/lessons.py:1005-1063` (`station_lessons_room`), `:768` (`describe_station_room`)
- Test: `peer/tests/test_lessons_adds.py`

**Interfaces:**
- Consumes: Task 1's `lessons_addable`, `typed_by`; owner trust's `code_current(db, contact_id)`.
- Produces: `addable_contacts(db, room, peer_ids) -> list[dict]` in `lessons.py`: per listed peer, every contact on it
  that is code-current, unheld, has no `trust_confirmations` row, isn't a member of the current room and isn't
  `_owner_removed`; each dict `{id, label, user_short, peer_id, code_digest, typed_by}`. The view's dict gains
  `addable` (that list without `code_digest`).
- Produces: the confirm code becomes
  `sha256(encode({'room', 'members', 'peers', 'ship', 'addable': sorted([id, code_digest, typed_by] ...)}))[:8]`.
  A CONFIRM run, in the transaction that replaces `lessons_peers`, replaces `lessons_addable` with one row per
  addable contact (`listed` = now).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_listing_names_each_addable_account(adds):
    contact = adds.pair_new('defiant')
    view = list_view(adds)
    assert [a['id'] for a in view['addable']] == [contact]
    assert 'addable by' in describe_station_room(view) and 'code' not in json.dumps(view['addable'])

def test_members_trust_made_held_and_removed_contacts_are_not_addable(adds): ...

def test_the_confirm_code_changes_when_one_is_added_or_goes_stale(adds):
    before = list_view(adds)['confirm']
    contact = adds.pair_new('defiant'); after_add = list_view(adds)['confirm']
    repair_under_a_new_name(adds, contact); after_stale = list_view(adds)['confirm']
    assert len({before, after_add, after_stale}) == 3

def test_confirm_records_exactly_what_was_shown_and_a_rerun_replaces_it(adds): ...
def test_the_listing_shows_a_bidi_name_plainly(adds): ...
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `describe_station_room` prints, under each listed peer, one line per addable contact:
  `"  {label} ({user_short}) addable by {ship}"`, through `plain_name`. No code or digest is printed.
- [ ] **Step 4: Run them to see them pass**, plus `tests/test_lessons_room.py` whole.
- [ ] **Step 5: Commit**

---

### Task 4: `make station-lessons-add CONTACT=`

**Files:**
- Modify: `peer/superyak_peer/lessons.py` (a `station-add` verb beside `station-room` at :1508, and the method below)
- Modify: `Makefile` (a `station-lessons-add` target beside `station-lessons-room`, Makefile:478)
- Test: `peer/tests/test_lessons_adds.py`

**Interfaces:**
- Consumes: Tasks 1 and 3; `_lessons_chain`, `_add_members(db, owner_id, room, member_ids, carry, actor_id,
  grant_id=None)`, `_owner_removed`, `code_current`, `latest_grant(db, contact_id)`, `trust_state(db, grant_id, now)`,
  `_owner_contact(db, grant_id)`.
- Produces: `Lessons.station_lessons_add(self, contact_prefix) -> dict` with keys `label, user_short, peer12,
  old_room, new_room, lessons_carried`; `describe_lessons_add(result) -> str`:
  `"Added {label} ({user_short}) on {peer12} to the lessons room: room {old6} became {new6}; {n} lessons carried."`
- Produces: `addable_now(db, room, contact_id, now) -> str | None` in `lessons.py`: None when the contact may be
  added, else the refusal text. Task 7's pause notice uses it.
- Produces these refusal texts in `lessons.py` (each a `Problem`, status in brackets):
  - `ADD_NO_ROOM` (409): "No lessons room is recorded at this origin."
  - `ADD_AMBIGUOUS` (400): "{x} matches more than one contact; give more of its id."
  - `ADD_NOT_REMOTE` (404): "{x} isn't a remote contact here."
  - `ADD_UNLISTED` (403): "{label} is on {peer12}, which isn't listed for the lessons room."
  - `ADD_NO_CODE` (403): "{label} has no current typed code here, or it's held."
  - `ADD_NOT_VOUCHED` (403): "{label}'s code wasn't typed by {owner} with the lessons line shown, and the listing {owner} confirmed didn't name it."
  - `ADD_MEMBER` (409): "{label} is already in the lessons room."
  - `ADD_OWNER_REMOVED` (403): "{owner} removed {label} from the lessons room; adding it back is his act."
  - `ADD_TRUST` (403): "{label} was paired by owner trust, and that trust is {state}."
  - `ADD_OWNER_NOT_ADDABLE` (403): "{label}'s owner, {name}, isn't in the lessons room or addable to it."

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize('case', ['unlisted', 'no_code', 'stale', 'held', 'member', 'owner_removed',
                                  'other_admin', 'no_typed_by_not_listed', 'not_remote', 'ambiguous',
                                  'trust_revoked', 'trust_expired', 'trust_paused', 'owner_not_addable'])
def test_each_refusal_writes_nothing(adds, case):
    contact = setup(adds, case)
    before = snapshot(adds.pi)                       # every table's rows
    with pytest.raises(Problem) as refused:
        adds.pi.station_lessons_add(contact[:8])
    assert snapshot(adds.pi) == before and REASON[case] in text_of(refused.value)   # the Problem's message

def test_a_code_typed_with_the_line_shown_is_added(adds): ...
def test_an_account_the_confirmed_listing_named_is_added(adds): ...
def test_the_add_goes_to_the_chains_newest_room(adds):   # after another add moved the chain
def test_success_makes_the_next_room_carries_once_and_names_the_ship(adds):
    result = adds.pi.station_lessons_add(contact[:8])
    # member_changes row: change 'add', actor = the recorded ship, grant_id NULL;
    # the 'added' post names the ship; lessons_carried equals the chain's live lessons, carried once
def test_a_trust_made_ship_is_added_under_a_live_trust_with_its_owner_addable(adds_trusted): ...
def test_a_contact_key_with_a_colon_or_an_empty_chain_is_refused(adds): ...
def test_a_confirm_rerun_that_drops_a_contact_before_the_add_makes_the_add_refuse(adds):
    # listed contact, CONFIRM rerun after it went stale (no longer named), then the add: ADD_NOT_VOUCHED
def test_the_adds_output_shows_a_bidi_label_plainly(adds): ...
```

`adds_trusted` extends `adds` with a live owner trust for Andy's contact on Tardis and one ship paired by
`make station-pair-trusted`'s function (owner trust Task 8). Use test_owner_trust.py's helpers (`export`, `grant`,
`pairs`, `b_ship`); import them rather than copy them.

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** In one transaction:
  1. take the chain's current room (`_lessons_chain(db)[-1]`), refusing an empty chain or a key with `:`;
  2. resolve the contact prefix among `remote_contacts`;
  3. run the checks in the refusal list's order, the code path or the trust path;
  4. call `_add_members(db, owner_id=<room owner>, room, [contact], carry=True, actor_id=lessons_room.ship_id,
     grant_id=None)`.

  The two paths:
  - **Code path,** vouched when either `typed_by == owner and lessons_line == 1`, or a `lessons_addable` row exists
    whose `code_digest` and `typed_by` equal the contact's current ones.
  - **Trust path** (a `trust_confirmations` row and no current typed code): `trust_state(latest_grant)` must be
    `'live'`, and the owner contact must be a member of the current room or pass `addable_now` itself.

  The verb prints `describe_lessons_add`, through `plain_name`.
- [ ] **Step 4: Run them to see them pass**, plus `tests/test_lessons_room.py tests/test_member_changes.py`.
- [ ] **Step 5: Commit**

---

### Task 5: A hold takes trust-made members out of the chain

**Files:**
- Modify: `peer/superyak_peer/lessons.py` (the helper below)
- Modify: every site that inserts into `contact_holds`: `owner_trust.py:139` (`hold_contact`), `federation.py:202-208`
  (pair of an unpaired peer), `federation.py:327-332` (`unpair`, and `retire=True`), `backups.py:810` (`_unpair`),
  `backups.py:852` (`_hold_like_replaced`). Find them all with `grep -n "INTO contact_holds" peer/superyak_peer/*.py`.
- Modify: `peer/superyak_peer/members.py:267` (`remove_participant`)
- Test: `peer/tests/test_lessons_adds.py`, `peer/tests/test_owner_trust_restore.py`

**Interfaces:**
- Produces: `drop_held_from_lessons(db, contact_ids, now, *, every_contact=False) -> list[str]` in `lessons.py`.
  It's SQL only, so a raw `sqlite3` connection works. For each given contact that is in a room of the lessons chain,
  and (unless `every_contact`) has a `trust_confirmations` row, it does what `_remove_member` does to membership:
  deletes from `remote_room_members` in every chain room it's in, and bumps those rooms' `epoch`. It inserts one
  `member_changes` row (`change 'remove'`, `reason 'held'`, `actor_id NULL`, `created = now`, the same `now` for
  the whole batch). It returns the new rows' ids. It posts nothing and emits nothing; a `Store` caller emits
  `chat.membership` for the touched rooms after it returns.
- Retire passes `every_contact=True` with every contact of the retired peer; every other site passes the contacts it
  holds.
- Produces: `remove_participant` accepts a contact whose latest chain row is a `held` removal, records an owner
  removal for it with `_record_change` (no membership change), and returns as a removal does.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize('how', ['revoke', 'unpair', 'pair_of_unpaired_peer', 'restore'])
def test_a_hold_of_a_trust_made_member_takes_it_out_with_reason_held(adds_trusted, how): ...
def test_its_lessons_leave_the_index_on_the_next_run(adds_trusted): ...
def test_a_hold_leaves_a_code_confirmed_member_in(adds_trusted): ...
def test_a_retire_takes_out_every_contact_of_the_peer(adds_trusted): ...
def test_a_ship_recovered_under_a_later_trust_rejoins_by_rio_grandes_add(adds_trusted): ...
def test_andy_can_remove_a_held_contact_and_then_it_stays_out(adds_trusted):
    # remove_participant succeeds; station_lessons_add then refuses ADD_OWNER_REMOVED
def test_every_contact_holds_insert_calls_drop_held_from_lessons():
    # architecture test: each function in superyak_peer whose source inserts INTO contact_holds also calls
    # drop_held_from_lessons (read with ast, as owner trust's Task 6 architecture test reads display queries)
```

- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Call the helper in each site's transaction, right after its `contact_holds` insert.
- [ ] **Step 4: Run them to see them pass**, plus `tests/test_owner_trust.py tests/test_owner_trust_restore.py tests/test_federation.py tests/test_lessons_index.py`.
- [ ] **Step 5: Commit**

---

### Task 6: One grant's ships: a pause lays nothing, and one cap

**Files:**
- Modify: `peer/superyak_peer/lessons.py:1144` (`_lessons_gate`)
- Test: `peer/tests/test_lessons_adds.py`

**Interfaces:**
- Consumes: `latest_grant`, `trust_state`.
- Produces: in `_lessons_gate`, when the author is a remote contact with a `trust_confirmations` row, at the origin:
  - `GRANT_PAUSED` (403), "{label}'s owner trust is paused until {owner} renews it, so it lays no lessons.", when
    `trust_state(latest_grant)` is `'paused'`;
  - `GRANT_CAP` (429), "The ships of one owner trust share 32 live lessons, and they have them.", when the live
    lessons by all contacts whose latest grant is the same reach `LIVE_CAP`.
  These are checked at both doors that call the gate: chats.py:207 and `Federation._reply` (federation.py:1087).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_paused_grants_ship_lays_no_lesson_at_either_door(adds_trusted): ...
def test_two_ships_of_one_grant_share_one_live_cap(adds_trusted):
    # 20 live from ship A, then ship B's 13th is refused GRANT_CAP; another grant's ship is unaffected
def test_a_code_confirmed_author_keeps_its_own_cap(adds): ...
```

- [ ] **Step 2: Run them to see them fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run them to see them pass**, plus `tests/test_lessons_room.py tests/test_lessons_index.py`. - [ ] **Step 5: Commit**

---

### Task 7: Notices, the words that change, and the CLAUDE.md lines

**Files:**
- Modify: `peer/superyak_peer/ships.py:505` (`station_notices`)
- Modify: `peer/superyak_peer/owner_trust.py:64, 365` (`PAUSE_TEXT`, `trust_pauses`)
- Modify: `peer/superyak_peer/join_plan.py:105-110` (the step that names Andy's add)
- Modify: `docs/superpowers/specs/2026-11-02-machine-trust-design.md:95, 132`
- Modify: `peer/README.md` (the lessons-room section)
- Test: `peer/tests/test_lessons_adds.py`, `peer/tests/test_owner_trust.py`

**Interfaces:**
- Produces: in `station_notices`:
  - `lessons-add-<member_changes.id>` for each `add` row in a room of the lessons chain whose actor isn't the room's
    owner: `"{label} ({user_short}) on {peer12} joined the lessons room, added by {ship}."`
  - `lessons-held-<first id of the batch>` for each batch of `held` rows sharing one `created`:
    `"{n} ships left the lessons room when a hold took them out: {labels}."`, naming at most 5 and then
    `"and {k} more"`.

  Every value goes through `safe_line`.
- Produces: `trust_pauses` appends `" {k} of its ships wait for the lessons room until you renew."` when `k`, the
  grant's trust-made contacts that aren't members and that `addable_now` refuses only because the trust is paused,
  is above 0.
- Words: the machine-trust spec's line 95 becomes "A trust-made ship lands in no room but the lessons room, and only
  under a live trust, removed from it by any hold, silenced while its grant is paused, and capped per grant." Its
  line 132 gains ", except that a typed code for an account on a peer listed for the lessons room makes it addable
  there by Rio Grande (lessons-room adds spec)". join_plan's step says Rio Grande adds them with
  `make station-lessons-add CONTACT=`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_add_posts_its_notice_once_keyed_by_its_row(adds): ...     # two station_notices reads, one id
def test_a_hold_batch_posts_one_notice_for_all_its_ships(adds_trusted): ...
def test_the_owners_own_add_posts_no_notice(adds): ...
def test_a_paused_trust_says_how_many_ships_wait_for_the_lessons_room(adds_trusted): ...
def test_notice_names_carrying_bidi_controls_are_plain(adds): ...
```

- [ ] **Step 2: Run them to see them fail.** - [ ] **Step 3: Implement.** - [ ] **Step 4: Run them to see them pass**, plus the whole peer suite once: `cd peer && TMPDIR=/var/tmp .venv/bin/python -m pytest tests -q` (about 80 minutes on the Pi). - [ ] **Step 5: Commit**

**The CLAUDE.md lines, for the controller to apply after Andy's yes** (never by the implementer):
- Line 102's "and he adds his own account and that ship's account on that peer, which makes the chain's next room"
  becomes: "and Rio Grande adds each account Andy vouched for on that peer (his typed code with the lessons line
  shown, or the listing he confirmed) with `make station-lessons-add CONTACT=<contact short id>`, which makes the
  chain's next room and posts a notice in Ops. A trust-made ship joins the same way while its owner's trust is live.
  Removing a member, and adding back one he removed, stay Andy's."
- The pairing paragraph gains: "When the card's account is on a peer listed for the lessons room, `pair` says so
  before the code, because the code also makes it addable there."
