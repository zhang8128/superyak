# Fresh owner mentions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An owner's mention more than 24 hours old, or one the ship already answered, gets a read-only ticket (basis
`old` or `answered`) instead of a builder ticket, and the watcher tells the read-only run why.

**Architecture:** One helper, `Tickets._mention_stale`, in peer/superyak_peer/tickets.py decides freshness, and
`_mode_for` uses it for the owner rule. On the agent side, `build_prompt` gains a `limited` keyword, and the watcher
passes the ticket's basis when it is `old` or `answered`. No schema change.

**Tech Stack:** Python 3.11, FastAPI and SQLite (peer), the agent watcher, pytest.

**Spec:** docs/superpowers/specs/2026-10-15-owner-mention-fresh-design.md (revision 3, approved under D8).

## Global Constraints

- `MENTION_FRESH_SECONDS = 86400`. Fresh means `abs(now - created) <= 86400`, with `created` an `int` or `float`, not a
  `bool`, and finite. Exactly 86,400 seconds still builds.
- The basis values are exactly `old` and `answered`. `old` is checked before `answered`.
- The decision is made at issue only. The order of `issue_ticket`'s steps doesn't change.
- The prompt sentences are exactly as in the spec's "The change". Any other basis, or none, and build mode, leave the
  prompt byte for byte as today.
- Each amended spec line carries the note "(fresh owner mentions spec)".
- Commits end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Pi rules: only one full peer suite at a time (check
  `pgrep -af "venv/bin/python -m pytest -q -p no:cacheprovider$"`); never touch ~/.local/share/superyak or ~/.superyak;
  no servers on ports 7435 or 7436; restore mutations with `git checkout -- <file>`, never `-p`; no `rm -rf` in a
  script.

## Review Focus

1. A `created` that is text, infinite or far in the future. It must read `old` and never raise (500s become watcher
   retries and then the fallback note). Task 1, test 3 and test 4.
2. A running build ticket sent again after the mention turns 24 hours old. It must return the same build ticket, not
   re-decide. Task 1, test 6.
3. A downgraded mention when a writable session is on watch. It must defer, and the session's unread item must say
   `would_be: read`. Task 1, test 5.
4. A ticket basis the watcher doesn't know (`grant`, a list, a number). It must give the plain prompt and never a
   `TypeError`. Task 2, test 10.
5. A current watcher with a full deferred list asks without `decisions`, so `answered` reaches it. Task 2, test 11.

---

### Task 1: The station: `_mention_stale`, the owner rule, tests and docs

**Files:**
- Modify: `peer/superyak_peer/tickets.py`: the constant, `_mention_stale` after `_answered`, and `_mode_for`.
- Test: `peer/tests/test_tickets.py`, which gets tests 1-4 and 6-8 of the spec. `peer/tests/test_deferrals.py` gets
  test 5.
- Modify docs, each with the note "(fresh owner mentions spec)":
  - `peer/API.md`, the "Run tickets" paragraph (around line 888);
  - `docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`, section 4, rules 2 and 4 (around lines
    300-303);
  - `docs/superpowers/specs/2026-10-10-ship-status-and-claims-design.md`, lines 60, 165, 174 and 402: "owner mentions
    never defer" becomes "fresh owner mentions never defer";
  - `docs/superpowers/specs/2026-10-14-watch-default-design.md`, line 133: "an owner's mention still builds" becomes
    "an owner's fresh mention still builds".

**Interfaces:**
- Produces: `Tickets._mention_stale(db, ship_id, message) -> None | 'old' | 'answered'`, where `message` is a
  `messages` row. Grants 3c calls it. Also `MENTION_FRESH_SECONDS` in `superyak_peer.tickets`.

- [ ] **Step 1: Write the failing tests.** Use `setup`, `say` and `ticket` from test_tickets.py, the `clock` list from
  `env` (`clock[0] += n` moves the station clock), and `post` and `sources` (lines 101-110) for the label. For
  hand-edited rows, use `with store.transaction() as db: db.execute('UPDATE messages SET created=? WHERE id=?', ...)`
  where `store = app.state.store`.

```python
def test_an_owner_mention_builds_for_exactly_a_day_then_reads_old(env):
    """Fresh owner mentions R1, R2, R9: exactly 86,400 s still builds; just after, read with basis old, and a reply
    under that ticket is labelled a read-only run with basis old."""
    app, clients, users, clock, ship, serenity, room = setup(env)
    edge = say(clients[0], room, 'a', '@serenity add notes')
    late = say(clients[0], room, 'b', '@serenity add more notes')
    clock[0] += 86400
    got = ticket(serenity, edge['id']).json()
    assert (got['mode'], got['basis']) == ('build', 'owner')
    clock[0] += 0.5
    got = ticket(serenity, late['id']).json()
    assert (got['mode'], got['basis'], got['root_id'], got['footer']) == ('read', 'old', None, '')
    assert post(serenity, room, 'reply-late', 'That was a day ago', got['id']).status_code == 201
    assert sources(clients[0], room)['That was a day ago'] == {
        'kind': 'run', 'mode': 'read', 'basis': 'old', 'root_name': None, 'answering': late['id']}


def test_an_answered_owner_mention_reads_answered_without_decisions(env):
    """Fresh owner mentions R3: only the ship's own reply_to answer counts (R7). The uncounted answers are checked on
    the helper, because a ticket there would stay running and come back on a later ask. Lives in test_deferrals.py,
    for its reply, ask and HEADERS helpers."""
    app, clients, users, clock = env
    store = app.state.store
    ship, key = docked(store, users[0]['id'])
    other, other_key = docked(store, users[0]['id'], name='tardis')
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], other['id']]}).json()['id']
    session, watcher, tardis = ship_client(app, key, **HEADERS), ship_client(app, key), ship_client(app, other_key)
    first = say(clients[0], room, 'a', '@serenity first')
    reply(tardis, room, 't', 'not me', first['id'])
    with store.transaction() as db:
        mid = uid()
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (mid, room, ship['id'], 'claim-x', 'claim', 1, clock[0]))
        db.execute("INSERT INTO message_kinds VALUES(?, 'claim')", (mid,))
        db.execute('INSERT INTO message_replies VALUES(?, ?)', (mid, first['id']))
        row = db.execute('SELECT * FROM messages WHERE id=?', (first['id'],)).fetchone()
        assert store._mention_stale(db, ship['id'], row) is None
    second = say(clients[0], room, 'b', '@serenity second')
    reply(session, room, 'r2', 'done already', second['id'])
    got = ask(watcher, second['id'], decisions=False).json()
    assert (got['mode'], got['basis']) == ('read', 'answered')
    third = say(clients[0], room, 'c', '@serenity third')
    reply(session, room, 'r3', 'on it', third['id'])
    assert ask(watcher, third['id']).json() == {'decision': 'answered', 'message_id': third['id']}
    assert table(store, 'deferrals') == []
```

  The kind-message insert copies `test_a_system_message_never_starts_a_run_or_counts_as_answered`. Write the rest of the
  spec's tests the same way, named for what they check:
  - test 3: `created` set to `float('inf')`, and to `'abc'`, gives `read`, `old` with status 200;
  - test 4: `created` set to `clock[0] + 90000` gives `read`, `old`, and `clock[0] + 60` still builds;
  - test 5, in test_deferrals.py: an owner mention, `clock[0] += 86401`, the session on watch, then `ask` gives
    `defer`. The session's unread item for that mention (the session client's `GET /api/ships/me/unread`, as the
    deferral tests read it) has `deferred.would_be == 'read'`;
  - test 6: a builder ticket issued at `created + 84600` (23.5 hours), then `clock[0] += 3600` and asked again: the
    same ticket id, still `build`;
  - test 7: a non-owner's mention at 48 hours gives `read`, `none`;
  - test 8: an owner mention the ship answered, at 25 hours, without decisions, gives `read`, `old`.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `cd peer && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_tickets.py tests/test_deferrals.py -k "day or answered or created or old or running or owner"`
  Expected: the new tests marked "fails today" in the spec fail, with `build` where `read` is expected. The guard
  tests pass.

- [ ] **Step 3: Implement.** In peer/superyak_peer/tickets.py, add `import math` and the constant beside
  `TICKET_LIFETIME`:

```python
MENTION_FRESH_SECONDS = 86400  # fresh owner mentions: within a day of the ticket, either side (step 3's G15 bound)
```

  Add after `_answered`:

```python
    def _mention_stale(self, db, ship_id, message):
        """Fresh owner mentions: None while the mention may build, else why not. 'old' unless `created` is a finite int or
        float within MENTION_FRESH_SECONDS of now on either side; then 'answered' (R7). Grants step 3's 3c calls it too."""
        created = message['created']
        if (isinstance(created, bool) or not isinstance(created, (int, float))
                or (isinstance(created, float) and not math.isfinite(created))
                or abs(self.clock() - created) > MENTION_FRESH_SECONDS):
            return 'old'
        if self._answered(db, ship_id, message['id']):
            return 'answered'
        return None
```

  Change `_mode_for`:

```python
    def _mode_for(self, db, ship, message):
        """Spec A rule 2, bounded (fresh owner mentions spec): the owner's own fresh mention builds; an old or answered
        one reads, its basis saying why; everything else reads."""
        author = require(db.execute('SELECT id,kind FROM users WHERE id=?', (message['author_id'],)).fetchone())
        mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (message['id'], ship['id'])).fetchone()
        owner = ship['owner_id']
        if owner and mentioned and author['kind'] == 'person' and author['id'] == owner:
            stale = self._mention_stale(db, ship['id'], message)
            return ('build', 'owner', owner) if stale is None else ('read', stale, None)
        return 'read', 'none', None
```

- [ ] **Step 4: Run them and watch them pass,** with the whole of test_tickets.py and test_deferrals.py.

- [ ] **Step 5: The docs.** Make the five doc edits listed under Files, each with the note.
  - The API.md sentence becomes: "...In this step, `build` with basis `owner` goes to a message by the ship's owner (a
    person) that mentions the ship and is fresh: posted within 24 hours of the ticket, and not yet answered by the ship.
    An owner's mention that isn't fresh gets `read` with basis `old` or `answered` (fresh owner mentions spec).
    Everything else, and every resident ship, gets `read` with basis `none`."
  - The spec amendments are worded exactly as the spec's "Amended rules".

- [ ] **Step 6: Commit.**

```bash
git add peer/superyak_peer/tickets.py peer/tests/test_tickets.py peer/tests/test_deferrals.py peer/API.md docs/superpowers/specs/
git commit -m "Fresh owner mentions, station: an old or answered owner mention gets a read-only ticket (R1-R7, R9)"
```

- [ ] **Step 7: Mutations, after the commit.** Run each alone, run the new tests, then restore with
  `git checkout -- peer/superyak_peer/tickets.py`:
  - `>` in place of `abs(...) >`, that is, drop the `abs`. Test 4 should fail;
  - `<` in place of `>` in the bound. Test 1 should fail;
  - no `isinstance` checks. Test 3 should fail with a 500;
  - `answered` checked before `old`. Test 8 should fail;
  - `_mode_for` ignoring the helper. Tests 1, 2 and 5 should fail.

### Task 2: The watcher: the `limited` prompt, tests and README

**Files:**
- Modify: `agent/superyak_agent/watch.py`: `LIMITED_SENTENCES`, `build_prompt`, and the call at line 184.
- Modify: `agent/README.md` line 50.
- Test: `agent/tests/test_watch.py` gets tests 9 and 10. `agent/tests/test_watch_deferral.py` gets test 11.

**Interfaces:**
- Consumes: ticket JSON with `mode` and `basis` (`old` and `answered` from Task 1).
- Produces: `build_prompt(room, mention, ship, mode, limited=None)`.

- [ ] **Step 1: Write the failing tests.** Copy today's prompt first, so the byte-for-byte check has something to
  compare against:

```python
def test_a_limited_read_prompt_says_why_and_nothing_else_changes(...):
    # build view and mention as test_watch.py:50-56 does
    plain_read = build_prompt(view, mention, 'serenity', 'read')
    plain_build = build_prompt(view, mention, 'serenity', 'build')
    old = build_prompt(view, mention, 'serenity', 'read', limited='old')
    answered = build_prompt(view, mention, 'serenity', 'read', limited='answered')
    assert 'more than 24 hours old, so this run is read-only' in old
    assert 'already answered this mention in this room' in answered
    for prompt in (old, answered):
        assert "can ask the ship's owner" not in prompt and "from the ship's owner" not in prompt
    for value in (None, 'none', 'grant', ['old'], 5):
        assert build_prompt(view, mention, 'serenity', 'read', limited=value) == plain_read
    for value in (None, 'old', 'answered'):
        assert build_prompt(view, mention, 'serenity', 'build', limited=value) == plain_build
```

  Then:
  - test 10: a watcher whose fake station returns `{mode: 'read', basis: 'old'}` (use conftest's `ticket_override`)
    passes `limited='old'` to the runner's prompt. One with basis `none`, `grant` or no basis gives the plain prompt.
    FakeRunner records the prompt.
  - test 11, in test_watch_deferral.py: copy the full-list setup of lines 40-56. The override ticket is
    `{mode: 'read', basis: 'answered'}`. Assert that the request had no `decisions`, as line 56 does, and that the
    recorded prompt has the answered sentence.

- [ ] **Step 2: Run them and watch them fail.**
  Run: `cd agent && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_watch.py tests/test_watch_deferral.py`
  Expected: `TypeError: build_prompt() got an unexpected keyword argument 'limited'`, and the watcher tests fail.

- [ ] **Step 3: Implement.** In watch.py, above `build_prompt`:

```python
LIMITED_SENTENCES = {  # fresh owner mentions: why an owner's (or, with grants 3c, a grantee's) mention runs read-only
    'old': ('This mention is more than 24 hours old, so this run is read-only. If the request needs changes, say what '
            'you would do, and that a new message will start a builder run if it is still wanted.'),
    'answered': ('This ship has already answered this mention in this room, so this run is read-only. Say so, and that '
                 'a new message will start a builder run if more is wanted.'),
}
```

  In `build_prompt`, add the parameter `limited=None`, and make the read branch:

```python
    else:
        why = LIMITED_SENTENCES.get(limited) if isinstance(limited, str) else None
        task = ('You are in read-only mode: you can read and search the repository and use the aDNA tools, but '
                'you cannot run commands or change files. '
                + (why or f'If the request needs changes, say what you would do and that '
                           f'{label(author["name"])} can ask the ship\'s owner.'))
```

  At the call (line 184):

```python
                basis = ticket.get('basis')
                limited = basis if isinstance(basis, str) and basis in LIMITED_SENTENCES else None
                result = self.runner.run(mode, build_prompt(room, mention, self.config['ship'], mode, limited=limited), mid,
                                           instructions=ticket.get('blocks') or '')
```

- [ ] **Step 4: Run the tests and watch them pass,** with the whole agent suite.
- [ ] **Step 5: README.** Change line 50 to "...an owner's fresh mention (posted within 24 hours, not yet answered by
  the ship) still runs as a builder;".
- [ ] **Step 6: Commit.**
- [ ] **Step 7: Mutations, after the commit.** Run each alone, and restore after each:
  - the call passes `limited=None` always. Tests 10 and 11 should fail;
  - the `isinstance(limited, str)` guard is dropped. Test 9's list value should raise;
  - the old sentence is replaced by the plain one. Test 9 should fail.

## Deploy (after section 2 approval: Serenity, or a fresh Pi reviewer whose verdict is posted whole)

1. Back up the live database with SQLite's online backup to
   `~/.local/share/superyak/backups/peer-<stamp>-pre-owner-mention-fresh.sqlite3`, mode 0600, as the earlier merges
   did. Check its size isn't zero.
2. Build the merge on a detached main in the branch's worktree, and run the peer, agent and team suites there. Then
   merge into main (main clean and equal to origin/main), and check that the merge tree equals the tested one.
3. Restart `superyak-lighthouse`, `superyak-door`, `superyak-ship`, `superyak-odo` and `superyak-wormhole`, and each
   `superyak-ship-*` unit. Check all are active. `https://smart.tail7db420.ts.net/api/me` should answer 401.
4. The live check, needing no person's login. Copy the live database with SQLite's backup API into the scratchpad
   (never `cp`), open the copy with a throwaway Store with a fixed clock, and issue tickets there for one owner mention
   older than a day and one fresh one. Check `read`/`old` and `build`/`owner`, then delete the copy.
5. Push main, restart the lighthouse again so the version check names the new HEAD, and check its log with
   `journalctl --user-unit superyak-lighthouse`.
6. Announce in City of AI. Tell each machine to update, because its watcher gets the new prompt only then.

Rollback: before the push, `git reset --hard ORIG_HEAD` after checking ORIG_HEAD is the old main, then restart as in
step 3. No schema change, so the database needs nothing. Tickets already issued with basis `old` or `answered` read as
plain read tickets under old code.
