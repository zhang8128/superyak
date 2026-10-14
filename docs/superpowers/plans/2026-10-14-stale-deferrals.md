# Stale Deferrals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A station deferral stops counting as waiting for the session (the R26 unread mark, R27 `deferred_here`) once
it is past the 120-minute bound or the ship has answered the mention.

**Architecture:** One helper on the station, `_waiting_deferrals`, next to `_defer` in tickets.py, applies the rule
(under `DEFER_BOUND_SECONDS`, not `_answered`) and returns the waiting ids oldest first. inbox.py calls it once per
page after its loop; chats.py calls it for the room's deferrals. Reads stay read-only.

**Tech Stack:** Python (FastAPI peer, SQLite), pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-stale-deferrals-design.md`, revision 2, approved under D8 (d40d1f7).

**Status:** revision 2, for the same reviewer's re-check. Revision 1 (e62be36) had the fresh reviewer's verdict, APPROVE
WITH CHANGES (2 should-fix, 4 nits; room message 6752a4a7): see "Review map".

## Global Constraints

- Waiting means: `now - first_deferred < DEFER_BOUND_SECONDS` (the ticket path's `>=` is the complement) **and**
  `not self._answered(db, ship_id, message_id)` (R7: the ship's own reply, never a kind message).
- The helper returns a list ordered by `first_deferred`, oldest first.
- R26: inbox.py collects the page's mentioned ids and calls the helper **once per page, after its loop** (the loop can
  close a breakout, which drops that room's deferrals; checking after keeps today's result for those).
- R27: chats.py passes the room's deferred ids; `deferred_here` is the helper's result, present only when non-empty
  (R35).
- No row is deleted or changed on read (R24). The ticket path is unchanged.
- No agent file changes.

## Review Focus

1. A mention exactly at the bound: no longer waits (test 1 checks 7199 listed, 7200 not; the `<=` mutation fails it).
2. A person's reply to the mention: it still waits (test 2's first half).
3. The ship's claim message replying to the mention: it still waits (test 3, a guard).
4. A breakout closed on first sight in the same unread page: the helper runs after the loop, so a closure's dropped rows
   are gone first. No test can tell the order apart, and none is needed: a waiting deferral means a mention (an
   ordinary message) under two hours old in that room, and a breakout closes only after seven days without one, so the
   two never meet on one read. The order is kept as defence.
6. Two waiting deferrals in a room: `deferred_here` lists the older first (test 4, a guard; the order-by-id mutation
   fails it).
5. A ship in several rooms: `deferred_here` lists only this room's (the chats query filters by room, unchanged).

---

### Task 1: The waiting rule, in one helper, for R26 and R27

**Files:**
- Modify: `peer/superyak_peer/tickets.py` (a new `_waiting_deferrals`, right before `_defer`)
- Modify: `peer/superyak_peer/chats.py` (the R27 block in `send_message`, about lines 100-105)
- Modify: `peer/superyak_peer/inbox.py` (the unread loop, about lines 139-160)
- Test: `peer/tests/test_deferrals.py`: the four tests at the end are already committed (8e93d0f, 8ed1d48, f67b893). No
  test changes in this task.
- Modify: `docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md` (R26, R27 wording)

**Interfaces:**
- Produces: `Tickets._waiting_deferrals(self, db, ship_id, message_ids) -> list[str]`, the given ids with a waiting
  deferral for `ship_id`, oldest `first_deferred` first.

- [ ] **Step 1: Run the tests**

If the peer environment is missing, first run `cd peer && uv sync --locked --python 3.13`.
Run: `cd peer && uv run --locked python -m pytest -q tests/test_deferrals.py`
Expected: 2 failed, 23 passed. The failures:
- `test_a_deferral_past_the_bound_no_longer_counts_as_waiting`: `'deferred_here' not in ...` at the post after the bound;
- `test_a_deferral_the_ship_answered_no_longer_counts_as_waiting`: `'deferred_here' not in ...` at the post after the
  ship's reply.

`test_a_ships_kind_message_never_counts_as_its_answer` and `test_deferred_here_lists_the_oldest_deferral_first` pass
(guards).

- [ ] **Step 2: The code**

In `peer/superyak_peer/tickets.py`, right before `    def _defer(self, db, ship, message):`, add:

```python
    def _waiting_deferrals(self, db, ship_id, message_ids):
        """Stale deferrals spec: of the given mentions, those whose deferral still waits for the session, oldest first.
        A deferral waits while it is under DEFER_BOUND_SECONDS (the ticket path's >=, below) and the ship hasn't
        answered the mention (R7). One that no longer waits keeps its row for the watcher's next ask (R24)."""
        ids = list(dict.fromkeys(message_ids))
        if not ids:
            return []
        now = self.clock()
        rows = db.execute(f'SELECT message_id, first_deferred FROM deferrals WHERE ship_id=? AND message_id IN '
                          f'({",".join("?" * len(ids))}) ORDER BY first_deferred', (ship_id, *ids)).fetchall()
        return [r['message_id'] for r in rows
                if now - r['first_deferred'] < DEFER_BOUND_SECONDS and not self._answered(db, ship_id, r['message_id'])]

```

In `peer/superyak_peer/chats.py`, replace

```python
            if reply_to is None:  # R27: this ship's deferred mentions here that still wait for a reply_to
                waiting = [r[0] for r in db.execute('''SELECT deferrals.message_id FROM deferrals JOIN messages
                    ON messages.id=deferrals.message_id WHERE deferrals.ship_id=? AND messages.room_id=?
                    ORDER BY deferrals.first_deferred''', (actor, key))]
                if waiting:
```

with

```python
            if reply_to is None:  # R27: this ship's deferred mentions here that still wait (stale deferrals spec)
                held = [r[0] for r in db.execute('''SELECT deferrals.message_id FROM deferrals JOIN messages
                    ON messages.id=deferrals.message_id WHERE deferrals.ship_id=? AND messages.room_id=?''', (actor, key))]
                waiting = self._waiting_deferrals(db, actor, held)
                if waiting:
```

(the next two lines, `# R35: ...` and `sent['deferred_here'] = waiting`, stay).

In `peer/superyak_peer/inbox.py`, change `            messages, sources, breakout_rooms = [], {}, set()` to
`            messages, sources, breakout_rooms, asked = [], {}, set(), []`, and replace

```python
                if mentioned and db.execute('SELECT 1 FROM deferrals WHERE ship_id=? AND message_id=?', (actor, found['id'])).fetchone():
                    item['deferred'] = {'author_verified': item['author'], 'would_be': 'read'}  # R26
                messages.append(item)
```

with

```python
                messages.append(item)
                if mentioned:
                    asked.append(found['id'])
            waiting = set(self._waiting_deferrals(db, actor, asked))  # R26, once per page, after any breakout closed
            for item in messages:
                if item['message_id'] in waiting:
                    item['deferred'] = {'author_verified': item['author'], 'would_be': 'read'}
```

Indentation: 16 spaces (the loop body) for `messages.append(item)` and `if mentioned:`; 20 for `asked.append(...)`;
12 for `waiting = ...` and the `for item in messages:` loop, which sit right after the loop and before the line that
follows it today (`on_watch = self._session_on_writable_watch(...)`).

In `docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md`:
- R26: "An unread item that is one of this ship's deferred mentions carries" → "An unread item that is one of this
  ship's deferred mentions that still waits (under the bound and not yet answered by the ship; stale deferrals spec)
  carries";
- R27: "lists this ship's deferred mentions in that room in its result" → "lists this ship's deferred mentions in that
  room that still wait in its result".

- [ ] **Step 3: Run the tests**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_deferrals.py tests/test_inbox.py tests/test_breakouts.py`
Expected: all pass (72).

- [ ] **Step 4: Mutation checks**, one at a time, each restored before the next (set `PYTHONDONTWRITEBYTECODE=1`; run
  `tests/test_deferrals.py`):
  - drop `now - r['first_deferred'] < DEFER_BOUND_SECONDS and ` from the helper: test 1 fails;
  - change `<` to `<=` there: test 1 fails (at exactly the bound);
  - drop ` and not self._answered(db, ship_id, r['message_id'])`: test 2 fails;
  - replace `self._answered(...)` with a plain `message_replies` join on the ship (no `message_kinds` exclusion): test 3
    fails;
  - make inbox.py's `waiting` the set of all this ship's deferral rows: tests 1 and 2 fail;
  - make chats.py's `waiting = held`: tests 1 and 2 fail;
  - change the helper's `ORDER BY first_deferred` to `ORDER BY message_id`: test 4 fails.

- [ ] **Step 5: The peer suite**

Run: `make check-peer`. Expected: every test passes (main's 574 on this Mac, plus 4: 578). Name any failure.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/tickets.py peer/superyak_peer/chats.py peer/superyak_peer/inbox.py docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md
git commit -m "Stale deferrals: a deferral past the bound or answered by the ship stops counting as waiting (R26, R27)"
```

---

## Deploy (Rio Grande, after the merge under law section 2)

1. Back up the database, merge with `--no-ff`, push, then restart the lighthouse (after the push, so the version check
   stays on); check the journal and `grep 'version check'`.
2. Ships need nothing: no agent change.
3. Announce it.

## Self-review notes

- **Spec coverage:** the rule, the helper, R26, R27, the amended wording and requirements 1-6: Task 1.
- **Dry run:** every block applied as written in a scratch worktree (revision 1 at d40d1f7, reproduced by the plan
  reviewer at e62be36): RED 2 failed and 22 passed; GREEN 71; all six mutations fail exactly the tests named;
  `make check-peer` 577. Revision 2 adds test 4 (f67b893): it passes before and after the change, and the order-by-id
  mutation fails it; the counts become 23, 72 and 578.
- **Merge note:** ship-status-fixes changes tickets.py's `_decided` and the INSERT, not `_defer` or `_answered`; the two
  branches should merge cleanly in either order.


## Review map (revision 2: the plan review of e62be36)

| # | Finding | Change |
|---|---|---|
| S1 | the after-the-loop order untested | Review Focus 4 explains why no read can tell it apart (a waiting deferral means a mention under 2 h; a breakout closes after 7 days without one); kept as defence |
| S2 | oldest-first untested | test 4, a guard whose ids sort the other way; Step 4's seventh mutation |
| N3 | the indentation sentence | given in spaces |
| N4 | no setup line | Step 1 starts with `uv sync` |
| N5 | `dict.fromkeys` unobserved | no change: an equivalent mutant, harmless |
| N6 | the dry run's hash | both hashes named |
