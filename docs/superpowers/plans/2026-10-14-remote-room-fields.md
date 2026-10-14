# Remote Room Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A received room's `linked_room_id` is its origin's own earlier room or nothing, and its activity in the chat
list counts only up to when this station received it.

**Architecture:** federation.py's `_apply` refuses a bad `linked_room_id` and records this station's receive time in a
new `inbox_received` table; db.py backfills that table at start; peer_store.py's `_remote_room` drops a stored bad
`linked_room_id` and clamps the origin's claimed activity to the receive time, while this station's queued replies
count at their own time.

**Tech Stack:** Python (FastAPI peer, SQLite), pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-remote-room-fields-design.md`, revision 2, approved under D8 (b6dc010; the
type-check mutation line corrected by this plan's dry run, 2d4ee40).

**Status:** revision 2, for the same reviewer's re-check. Revision 1 (fd22b65) had the fresh reviewer's verdict, APPROVE
WITH CHANGES (2 should-fix, 2 nits; room message c04b09d5): see "Review map".

## Global Constraints

- `linked_room_id` is `None` or a `str` that fully matches `re.escape(origin) + r':[A-Za-z0-9_-]{1,64}'`, where `origin` is
  the envelope's origin (at receive) or the inbox row's origin (in the view). At receive, anything else is refused with
  `Problem(400, 'Invalid linked room')`; in the view, it shows as `None`.
- `inbox_received(origin, resource_id, recipient, received REAL NOT NULL, PRIMARY KEY(origin, resource_id, recipient))` is a
  new table. `inbox` is unchanged (its positional INSERT must keep working after a rollback).
- `received` is written with `self.store.clock()` whenever a room event stores a non-null payload for a recipient, in the
  same transaction.
- At every start, `INSERT OR IGNORE` backfills `received` = now for stored room rows that have none.
- In the view: `claimed = max(snapshot last_activity, origin messages' created)`; if an `inbox_received` row exists,
  `claimed = min(claimed, received)`; `last_activity = max([claimed] + this station's queued replies' created)`.
- Message `created` and order inside the room are unchanged.
- No agent file changes.

## Review Focus

1. A roster alone claiming `last_activity` 2^53 (no later message to overwrite it): clamped (test, and the
   "received only on room.message" mutation).
2. A local room named as the linked room under this station's own peer id: refused only by the origin prefix (test).
3. An honest linked room from `add_participants` on the origin: still received (guard test).
4. This station's queued reply after the room arrived: still moves the room to its own time (guard test).
5. A database from before this change: the backfill gives every stored room a row, so the clamp applies from the first
   read (`test_a_room_stored_before_the_change_is_clamped_after_the_next_start`). A second event refreshes `received`,
   and a restart leaves existing rows alone (`test_received_follows_each_event_and_a_restart_leaves_it`).

---

### Task 1: The linked-room rule, the receive time, and the clamp

**Files:**
- Modify: `peer/superyak_peer/federation.py` (`_apply`: the snapshot checks; the inbox write)
- Modify: `peer/superyak_peer/peer_store.py` (`PEER_SCHEMA`; `_remote_room`)
- Modify: `peer/superyak_peer/db.py` (the migration block, after the F3 column)
- Test: `peer/tests/test_federation.py`: the fourteen tests at the end are already committed (ef36222, 3ceecd2,
  b6dc010, 2d4ee40, f27065f). No test changes in this task.

**Interfaces:**
- Produces: the `inbox_received` table; `_remote_room`'s clamped `last_activity` and checked `linked_room_id`.

- [ ] **Step 1: Run the tests**

If the peer environment is missing, first run `cd peer && uv sync --locked --python 3.13`.
Run: `cd peer && uv run --locked python -m pytest -q tests/test_federation.py`
Expected: 12 failed, 53 passed. The twelve: the six `linked_room_is_its_origins_own_or_none` cases ("DID NOT RAISE"),
the roster and message activity tests (`[False, False] == [True, True]`), `test_a_stored_bad_linked_room_shows_as_none`,
`test_the_inbox_received_table_is_added_once_and_inbox_is_unchanged`, and the backfill and refresh/restart tests (no
`inbox_received` table yet). The honest-linked-room and queued-reply tests pass (guards).

- [ ] **Step 2: The code**

In `peer/superyak_peer/federation.py`, in `_apply`, right after the timestamp loop:

```python
            for field in ('created','last_activity'):
                if type(p.get(field)) not in (int,float) or not 0 <= p[field] <= 2**53:
                    raise Problem(400, 'Invalid room timestamp')
```

add:

```python
            linked = p.get('linked_room_id')  # remote room fields: the origin's own earlier room, or nothing
            if linked is not None and not (isinstance(linked, str) and re.fullmatch(re.escape(origin) + r':[A-Za-z0-9_-]{1,64}', linked)):
                raise Problem(400, 'Invalid linked room')
```

In the same function, right after the line that starts `            db.execute('INSERT INTO inbox VALUES(?,?,?,?,?,?,?)`
(and before `            if action == 'room.withdraw':`), add:

```python
            if kind == 'room' and payload is not None:  # remote room fields: this station's own time, for the list's clamp
                db.execute('INSERT INTO inbox_received VALUES(?,?,?,?) ON CONFLICT(origin,resource_id,recipient) DO UPDATE SET received=excluded.received',
                           (origin, rid, recipient, self.store.clock()))
```

In `peer/superyak_peer/peer_store.py`, in `PEER_SCHEMA`, right after the `CREATE TABLE IF NOT EXISTS inbox(...);` line, add:

```
CREATE TABLE IF NOT EXISTS inbox_received(origin TEXT NOT NULL, resource_id TEXT NOT NULL, recipient TEXT NOT NULL, received REAL NOT NULL, PRIMARY KEY(origin,resource_id,recipient));
```

In `peer/superyak_peer/db.py`, right after `                db.execute('ALTER TABLE tickets ADD COLUMN first_deferred REAL')`
(inside the same `with` block, at the `ticket_columns = ...` line's indentation, 12 spaces), add:

```python
            # remote room fields: a received room stored before inbox_received existed gets this start's time, once
            db.execute("INSERT OR IGNORE INTO inbox_received SELECT origin, resource_id, recipient, ? FROM inbox "
                       "WHERE kind='room' AND payload IS NOT NULL", (self.clock(),))
```

In `peer/superyak_peer/peer_store.py`, in `_remote_room`, right after
`        result.update({'id':key, 'origin':row['origin'], 'epoch':row['revision']})`, add:

```python
        linked = result.get('linked_room_id')  # remote room fields: the view's backstop for what an older receiver stored
        if linked is not None and not (isinstance(linked, str) and re.fullmatch(re.escape(row['origin']) + r':[A-Za-z0-9_-]{1,64}', linked)):
            result['linked_room_id'] = None
        claimed = max([result['last_activity']] + [m['created'] for m in result['messages']])
        arrived = db.execute('SELECT received FROM inbox_received WHERE origin=? AND resource_id=? AND recipient=?',
                             (row['origin'], row['resource_id'], actor)).fetchone()
        if arrived is not None:  # remote room fields: the origin's claims count only up to when this station received them
            claimed = min(claimed, arrived['received'])
        queued = []
```

Replace `                result['messages'].append({**local, 'state':delivery['status']})` with:

```python
                queued.append({**local, 'state':delivery['status']})
                result['messages'].append(queued[-1])
```

and replace `        result['last_activity'] = max([result['last_activity']] + [m['created'] for m in result['messages']])` with:

```python
        result['last_activity'] = max([claimed] + [m['created'] for m in queued])  # this station's queued replies at their own time
```

- [ ] **Step 3: Run the tests**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_federation.py`
Expected: 65 passed.

- [ ] **Step 4: Mutation checks**, one at a time, each restored before the next (set `PYTHONDONTWRITEBYTECODE=1` and
  clear `__pycache__` between them; run `tests/test_federation.py`):
  - delete the two-line receive check (`linked = ...` is kept; remove the `if ... raise` pair): all six linked cases fail;
  - replace `re.escape(origin) + r':[A-Za-z0-9_-]{1,64}'` at receive with `r'[0-9a-f]{64}:[A-Za-z0-9_-]{1,64}'` (any
    station's prefix): the `another-station` and `a-local-room` cases fail;
  - in the view, replace `result['linked_room_id'] = None` with `pass`: `test_a_stored_bad_linked_room_shows_as_none`
    fails;
  - replace `claimed = min(claimed, arrived['received'])` with `pass`: both activity tests fail;
  - clamp the queued replies too (wrap the final `max(...)` in `min(..., arrived['received'] if arrived else 2**60)`):
    `test_this_stations_queued_reply_still_moves_a_received_room` fails;
  - change `if kind == 'room' and payload is not None:  # remote room fields` to `if action == 'room.message' and payload
    is not None:  # remote room fields`: the roster activity test fails;
  - delete the `CREATE TABLE IF NOT EXISTS inbox_received(...)` line: every test errors at store start (the backfill
    reads the missing table);
  - delete the db.py backfill (`db.execute("INSERT OR IGNORE INTO inbox_received ...`): the backfill test fails;
  - change `DO UPDATE SET received=excluded.received` at receive to `DO NOTHING`: the refresh/restart test fails;
  - change the backfill's `INSERT OR IGNORE` to `INSERT OR REPLACE`: the refresh/restart test fails.

  Not a mutation: removing only `isinstance(linked, str) and` at receive. `receive()` already turns the `TypeError` a
  non-string raises into a 400, so the type guard is defence (measured).

- [ ] **Step 5: The peer suite**

Run: `make check-peer`. Expected: every test passes (main's 587 on this Mac, plus 14: 601). Name any failure.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/federation.py peer/superyak_peer/peer_store.py peer/superyak_peer/db.py
git commit -m "Remote room fields: a received room's linked room is its origin's own; its listed activity counts only up to arrival"
```

---

## Deploy (Rio Grande, after the merge under law section 2)

1. Back up the database (a new table), merge with `--no-ff`, push, then restart the lighthouse (after the push, so the
   version check stays on; the table and backfill run at start). Check the journal and `grep 'version check'`.
2. Ships need nothing: no agent change.
3. Announce it.

## Self-review notes

- **Spec coverage:** F1 (receive and view), F2 (the table, the backfill, the clamp) and requirements 1-7: Task 1.
- **Dry run:** revision 1's blocks applied as written in a scratch worktree at b6dc010 plus the guard tests (the plan
  reviewer reproduced them at fd22b65): RED 10 failed and 53 passed; GREEN 63; the first seven mutations fail exactly
  the tests named; the `isinstance`-only removal survives, as stated; `make check-peer` 599. Revision 2 adds the two
  tests (f27065f): RED 12/53, GREEN 65, and the three new mutations each fail exactly their named test. `make check-peer`
  at revision 2: 601.

## Review map (revision 2: the plan review of fd22b65)

| # | Finding | Change |
|---|---|---|
| S1 | the backfill unguarded | `test_a_room_stored_before_the_change_is_clamped_after_the_next_start`; the "no backfill" mutation |
| S2 | receive refresh and restart idempotence unguarded | `test_received_follows_each_event_and_a_restart_leaves_it`; the `DO NOTHING` and `OR REPLACE` mutations |
| N3 | the seventh mutation understated | "every test errors at store start" |
| N4 | the dry run's base | both bases named |
