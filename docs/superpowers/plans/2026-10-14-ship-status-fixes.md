# Ship Status Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two R37 budget gaps from the ship-status re-review. F1 is already done in b04d516.
- F2: a hand-listed deferred entry is charged once.
- F3: a lost `run` response no longer over-charges a deferral the station held.

**Architecture:**
- F2 is watcher-only, in watch.py's `defer` branch. A new deferred entry records the station's `first_deferred`; a
  listed entry without one is charged at its first `defer`.
- F3 is station-only. `tickets` gains a nullable `first_deferred` column (an additive migration in db.py), written when
  a run resolves a held deferral, and echoed by `_decided` (gated on `decisions`) on issue and on every re-send.
- R37's sparing rule is unchanged: only the station's word spares.

**Tech Stack:** Python 3.11+, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-ship-status-fixes-design.md`, revision 2, approved under D8 (c16a733).

**How work runs:** a fresh reviewer approves this plan. Each task gets a fresh implementer and a review, then a
whole-branch review. Rio Grande approves the merge and the Pi suites must pass (law section 2).

## Global Constraints

- **F2 acts only in the `defer` branch.** A `run` answer stays with the existing `held` check (watch.py:155-162).
- **F2's recorded value only ever causes a charge, never a spare.**
- **F3's echo lives in `_decided`,** gated on `decisions`. Never in `_ticket_json`, which `finish_ticket` and
  no-`decisions` answers share, so an old watcher never sees a new key (R23).
- **The migration is additive:** `ALTER TABLE tickets ADD COLUMN first_deferred REAL` only if absent, in db.py's
  existing PRAGMA block. Every read of `tickets` is by column name, so an old binary is unaffected.
- **R37's two revised sentences** are already in the spec. The ship-status spec's own R37 text is updated in Task 2
  (docs).

## Review Focus

1. **A watcher state from before F2:** entries without `first_deferred`. They're charged at most once more, at their
   next `defer`, never at a `run` (Task 1: `test_a_hand_listed_entry_the_station_then_defers_is_charged_once` and
   the normal-path test).
2. **A station restarted mid-run:** a running ticket issued before the migration has `first_deferred` NULL, so its
   re-send carries none, as today (Task 2: the column test checks NULL on old rows).
3. **An old watcher (no `decisions`):** never sees `first_deferred`, on issue or re-send (Task 2).
4. **A person's hand-listed mention:** never charged, since only ship mentions spend the budget, but its entry still
   records `first_deferred` (Task 1).
5. **A breakout mention:** keeps its mark, and its budget is still per author across breakouts (Task 1: the N1 test's
   updated entry).

---

### Task 1: Watcher, a hand-listed entry is charged once (F2)

**Files:**
- Modify: `agent/superyak_agent/watch.py` (the `defer` branch, about lines 143-152)
- Modify: `agent/tests/test_watch_deferral.py`: the two reproduction tests, already in the worktree uncommitted, at
  the end of the file. The F3 agent test's retry already carries `first_deferred=1.0`. Plus two new tests, and N1's
  expected entry.

- [ ] **Step 1: The tests**

The worktree already holds, uncommitted at the end of `agent/tests/test_watch_deferral.py`:
- `test_a_hand_listed_entry_the_station_then_defers_is_charged_once` (F2's reproduction);
- `test_a_lost_run_response_for_a_deferral_the_station_held_is_not_charged_again` (F3's agent side, modelling the
  fixed station: its retry answer carries `first_deferred=1.0`).

Keep both as they are. Append:

```python
def test_a_normally_deferred_ship_mention_is_charged_once_across_defers(station, ship_config, tmp_path):
    """F2: a ship's mention charged at entry and then deferred records the station's first_deferred, so later defers
    and the run that resolves the deferral never charge it again."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    for _ in range(3):
        assert w.cycle() == 0
    first = fake.decide[asked['id']]['first_deferred']
    assert w.state['deferred'][0]['first_deferred'] == first
    fake.decide[asked['id']] = {'id': 'held-1', 'mode': 'read', 'basis': 'none', 'footer': '', 'blocks': '',
                                'status': 'running', 'decision': 'run', 'first_deferred': first}
    w.cycle()
    assert len(runner.calls) == 1 and len(w.state['ship_exchanges'][f'{room}:{defiant["id"]}']) == 1


def test_an_over_budget_hand_listed_entry_gets_the_pause_note_at_its_defer(station, ship_config, tmp_path):
    """F2: charged at its first defer and over the hour's budget, the hand-listed entry gets the pause note and
    leaves the list, as an over-budget new mention does."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    w.state['ship_exchanges'][f'{room}:{defiant["id"]}'] = [w.clock()] * 5
    w.cycle()
    assert runner.calls == [] and w.state['deferred'] == []
    assert sum('Pausing my replies' in b for b in bodies(fake, room)) == 1


def test_a_persons_hand_listed_entry_is_never_charged(station, ship_config, tmp_path):
    """F2 (plan review of 4fa215b, should-fix 1): the hour's budget is for ships only (R12). A person's hand-listed
    entry, deferred again and again with that key's budget already spent, is never charged and never paused."""
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity a person question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    key, spent = f'{room}:{jenn["id"]}', [w.clock()] * 5
    w.state['ship_exchanges'][key] = list(spent)  # a guard that counted people would pause here
    for _ in range(3):
        assert w.cycle() == 0
    assert runner.calls == [] and len(w.state['deferred']) == 1
    assert not any('Pausing my replies' in b for b in bodies(fake, room))
    assert w.state['ship_exchanges'][key] == spent


def test_a_hand_listed_entry_deferred_again_and_again_is_charged_once(station, ship_config, tmp_path):
    """F2: the first defer charges a hand-listed ship entry and records the station's first_deferred on it, so the
    defers after it charge nothing more."""
    fake, andy, jenn, serenity = station
    defiant = fake.user('defiant', 'Defiant', 'ship', jenn['id'], key='defiant-key')
    room = fake.room('Ops', andy, jenn, serenity, defiant)
    asked = fake.say(room, defiant, '@serenity a ship question')
    defer(fake, asked)
    runner = FakeRunner()
    w = watcher(fake, ship_config, tmp_path, runner)
    w.me = w.client.me()
    _listed(w, fake, asked)
    for _ in range(3):
        assert w.cycle() == 0
    assert len(w.state['ship_exchanges'][f'{room}:{defiant["id"]}']) == 1
    assert len(w.state['deferred']) == 1 and runner.calls == []
    assert not any('Pausing my replies' in b for b in bodies(fake, room))
```

In `test_a_deferred_breakout_mention_keeps_its_mark_and_its_budget`, change the expected entry
`{'message_id': asked['id'], 'room_id': room, 'author': rio, 'seq': 1, 'breakout': True}` to
`{'message_id': asked['id'], 'room_id': room, 'author': rio, 'seq': 1, 'breakout': True,
'first_deferred': fake.decide[asked['id']]['first_deferred']}`.

- [ ] **Step 2: Run them to verify which fail**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_watch_deferral.py`
Expected:
- these fail: `test_a_hand_listed_entry_the_station_then_defers_is_charged_once` (0 charges),
  `test_a_normally_deferred_ship_mention_is_charged_once_across_defers` (no `first_deferred` on the entry),
  `test_an_over_budget_hand_listed_entry_gets_the_pause_note_at_its_defer` (no pause note) and the N1 test (no new key);
- `test_a_lost_run_response_for_a_deferral_the_station_held_is_not_charged_again` passes, because it models the fixed
  station;
- `test_a_hand_listed_entry_deferred_again_and_again_is_charged_once` passes (the first defer already charges and
  records), and Step 5's third mutation is what makes it fail;
- `test_a_persons_hand_listed_entry_is_never_charged` passes: it guards against a wrong fix (the charge applied to a
  person), and Step 5's second mutation is what makes it fail.

Report the exact list.

- [ ] **Step 3: The code**

In `agent/superyak_agent/watch.py`, replace the `defer` branch's `elif not listed:` block:

```python
                    elif not listed:  # a breakout's mark is kept: its budget and its 404 depend on it (breakouts R5, R12)
                        self.state['deferred'].append({k: mention[k] for k in ('message_id', 'room_id', 'author', 'seq')}
                                                      | ({'breakout': True} if mention.get('breakout') else {}))
```

with:

```python
                    elif not listed:  # a breakout's mark is kept: its budget and its 404 depend on it (breakouts R5, R12)
                        # ship-status fixes F2: the station's own first_deferred, recorded when this watcher, which
                        # charged the mention at entry, lists it. It only ever decides a charge, never a spare (R37).
                        self.state['deferred'].append({k: mention[k] for k in ('message_id', 'room_id', 'author', 'seq')}
                                                      | ({'breakout': True} if mention.get('breakout') else {})
                                                      | ({'first_deferred': ticket['first_deferred']}
                                                         if 'first_deferred' in ticket else {}))
                    else:
                        entry = next(d for d in self.state['deferred'] if d['message_id'] == mid)
                        if 'first_deferred' not in entry:  # F2: hand-listed, never charged: charged here, once
                            if author['kind'] == 'ship' and not self._ship_budget(mention):
                                self._remember(mid)
                                self.save()
                                return True, self._pause_note(mention)
                            entry['first_deferred'] = ticket.get('first_deferred')
```

The `self.save()` and `return True, 0` after the block stay as they are.

- [ ] **Step 4: Run them, then the agent suite**

Run: `cd agent && uv run --locked --extra dev python -m pytest -q tests/test_watch_deferral.py`. Expected: all pass.
Run: `make check-agent`. Expected: every test passes (main's count plus 6). Name any failure.

- [ ] **Step 5: Mutation checks**, one at a time, each restored before the next:
  - remove the `| ({'first_deferred': ...} if 'first_deferred' in ticket else {})` term:
    `test_a_normally_deferred_ship_mention_is_charged_once_across_defers` fails;
  - remove `author['kind'] == 'ship' and ` from the new branch's budget check:
    `test_a_persons_hand_listed_entry_is_never_charged` fails;
  - remove `entry['first_deferred'] = ticket.get('first_deferred')`:
    `test_a_hand_listed_entry_deferred_again_and_again_is_charged_once` fails.

  Confirm with `git diff --stat` that watch.py matches your change.

- [ ] **Step 6: Commit**

```bash
git add agent/superyak_agent/watch.py agent/tests/test_watch_deferral.py
git commit -m "Ship status fixes F2: a hand-listed deferred entry is charged once, at its first defer"
```

---

### Task 2: Station, a re-sent run carries the deferral it resolved (F3)

**Files:**
- Modify: `peer/superyak_peer/db.py` (the additive migration block, about lines 63-75)
- Modify: `peer/superyak_peer/tickets.py` (`issue_ticket`'s INSERT and `_decided`; remove the issue-time
  `first_deferred` lines 74-75, which `_decided` now covers)
- Modify: `docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md` (R37's two sentences, as the fixes spec
  words them)
- Test: `peer/tests/test_deferrals.py` (append)

- [ ] **Step 1: The failing tests**

Append to `peer/tests/test_deferrals.py`:

```python
def test_a_run_from_a_deferral_carries_first_deferred_on_every_resend(env):
    """Ship-status fixes F3: the station keeps the deferral a run resolved on its ticket, and says so on issue and on
    every re-send to a watcher asking for decisions, so a retry after a lost answer is spared on the station's word
    (R37). An old watcher never sees the key (R23)."""
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    on_watch(session)
    first = ask(watcher, asked['id']).json()['first_deferred']
    on_watch(session, minutes=0)
    ran = ask(watcher, asked['id']).json()
    assert ran['decision'] == 'run' and ran['first_deferred'] == first
    again = ask(watcher, asked['id']).json()
    assert again['id'] == ran['id'] and again['first_deferred'] == first
    assert 'first_deferred' not in ask(watcher, asked['id'], decisions=False).json()


def test_a_run_never_deferred_carries_no_first_deferred(env):
    app, clients, users, clock, store, ship, session, watcher, room = setup(env)
    asked = say(clients[1], room, 'a', '@serenity a question')
    ran = ask(watcher, asked['id']).json()
    assert ran['decision'] == 'run' and 'first_deferred' not in ran
    assert 'first_deferred' not in ask(watcher, asked['id']).json()


def test_the_tickets_column_is_added_once(tmp_path):
    from superyak_peer.db import Store
    Store(tmp_path / 'p')
    store = Store(tmp_path / 'p')  # a second start changes nothing
    with store.transaction() as db:
        names = [r['name'] for r in db.execute('PRAGMA table_info(tickets)')]
    assert names.count('first_deferred') == 1
```

Before Step 2, check that `Store(path)` needs no other argument (db.py `Store.__init__`). If it does, pass what
conftest's `env` fixture passes.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_deferrals.py`
Expected:
- `test_a_run_from_a_deferral_carries_first_deferred_on_every_resend` fails at `again['first_deferred']` (KeyError:
  today's re-send carries none);
- the column test fails (no such column);
- `test_a_run_never_deferred_carries_no_first_deferred` passes, because it's a guard.

- [ ] **Step 3: The code**

In `peer/superyak_peer/db.py`, inside the additive migration block, after the `access_requests` columns, add:

```python
            ticket_columns = {row['name'] for row in db.execute('PRAGMA table_info(tickets)')}
            if 'first_deferred' not in ticket_columns:  # ship-status fixes F3: the deferral a run resolved, on its ticket
                db.execute('ALTER TABLE tickets ADD COLUMN first_deferred REAL')
```

In `peer/superyak_peer/tickets.py`, `issue_ticket`:
- change the INSERT to write the held deferral's time:
  `db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,instructions,status,created,first_deferred) VALUES(?,?,?,?,?,?,?,?,?,?)', (key, actor, message_id, mode, basis, root, bound, 'running', self.clock(), held['first_deferred'] if held is not None else None))`;
- delete the two lines after `decided = self._decided(...)` that add `first_deferred` (`if decisions and held is not
  None: ...`), since `_decided` now does it for issue and re-send alike.

Replace `_decided` with:

```python
    def _decided(self, db, row, station, decisions):
        ticket = self._ticket_json(db, row, station)
        if not decisions:
            return ticket  # R23: an old watcher's answer is exactly today's
        decided = dict(ticket, decision='run')
        if row['first_deferred'] is not None:  # F3: on issue and on every re-send, the station's own record (R37)
            decided['first_deferred'] = row['first_deferred']
        return decided
```

In the ship-status spec (`docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md`, R37), make the two
sentence changes the fixes spec gives (its F3 "Two sentences of R37 change"), verbatim.

- [ ] **Step 4: Run them, then the peer suite**

Run: `cd peer && uv run --locked python -m pytest -q tests/test_deferrals.py`. Expected: all pass.
Run: `make check-peer`. Expected: every test passes (main's count plus 3, plus F1's 1 already on the branch). Name
any failure.

- [ ] **Step 5: Mutation checks:**
- move the echo into `_ticket_json` (add `first_deferred` there): the `decisions=False` assertion fails;
- remove the echo from `_decided`: the re-send test fails.

Restore both.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/db.py peer/superyak_peer/tickets.py peer/tests/test_deferrals.py docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md
git commit -m "Ship status fixes F3: a re-sent run carries the deferral it resolved, kept on its ticket (R37)"
```

---

## Deploy (Rio Grande, after the merge under law section 2)

1. Back up the database (as for version check), merge with `--no-ff`, push, and run the guard.
2. Before restarting the Pi's ship watcher, look at its state file's `deferred` list for ship-authored entries: they
   will be charged once more at their next `defer`, so say so in the announcement (step 5).
   Restart the five units. The lighthouse's start runs the migration (one column). Check the journal for errors and
   `PRAGMA table_info(tickets)` for `first_deferred`. Confirm the version check:
   `journalctl --user --user-unit superyak-lighthouse --since '-2 min' --no-pager | grep 'version check'` should show
   `superyak: version check on: <HEAD 12>, N behind`.
3. **Watch the journal across the first real ticket calls** after the restart (`journalctl --user --user-unit
   superyak-lighthouse -f` until a ship's watcher has asked for tickets, or 15 minutes). A running ticket issued before
   the migration has no `first_deferred` and is read through the new `_decided`; the plan review's simulation of that
   row showed the key omitted and no error, and this confirms it on the real table. Any traceback: `git revert -m 1 <merge>`, push, restart the units. No database restore is needed:
   main's code runs on the migrated schema.
4. **Live check:** the peer test path, not the live watcher. With `decisions`, a deferral, the watch ended and a
   repeated ask on the Pi's station give the same ticket carrying `first_deferred` both times. Use a scratch station
   (`Store` in a temp folder), not the live one, so nothing is posted.
5. Announce it. Ships update by pulling main: watch.py is a runtime file, so the version check prompts them.

## Self-review notes

- **Spec coverage:**
  - F2: Task 1.
  - F3: Task 2.
  - F1: done (b04d516).
  - Requirements: 1 is F1; 2 is Task 1; 3, 4 and 5 are Task 2.
  - The spec's R37 sentence changes: Task 2, Step 3.
- **Dry run:** every block was run as written in a scratch worktree at the plan's base plus the two uncommitted
  reproduction tests.
  - **RED:** Task 1 fails exactly the four tests Step 2 names, and the lost-run test passes; Task 2 fails its two, and
    the guard passes.
  - **GREEN:** test_watch_deferral 27 (the person-authored test of revision 2 and the final review's test included) and test_deferrals 24 pass.
  - **Mutations,** all caught:
    - the F2 record term removed fails the normal-path test and N1;
    - the F3 echo removed fails the re-send test (and test_only_the_stations_own_deferral_row_marks_a_reask);
    - the echo leaking into `_ticket_json`'s path fails the `decisions=False` assertion.
  - **Full suites:** `make check-agent` 631, `make check-peer` 532.
  - **Revision 2:** the person-authored test passes with the code and fails with the guard removed; `make check-agent`
    632; after the final review's hand-listed record test, 633.
- **Accepted, outside this fix** (plan review nit 4): a ship's budget and deferred list live in each watcher's own state
  file, so a ship watched from two machines enforces the five-an-hour budget on each. Pre-existing, not a regression.

## Review map (revision 2: the plan review of 4fa215b, room message 766b63c0)

| # | Finding | Change |
|---|---|---|
| S1 | no test covered F2's author-kind guard | `test_a_persons_hand_listed_entry_is_never_charged`; Step 5's second mutation |
| S2 | no live read of an old ticket row | Deploy step 3 watches the journal across the first real ticket calls |
| N3 | asymmetric None handling, unreachable | no change: `_defer()` always carries `first_deferred` on a defer |
| N4 | two machines double the budget | noted above as accepted, pre-existing |
| N5 | `is not None` untested at clock 0 | no change: the code is right; a station clock of 0 doesn't occur |
