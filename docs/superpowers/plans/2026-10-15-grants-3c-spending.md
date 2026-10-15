# Spec A step 3, merge 3c: spending a grant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person's fresh mention of someone else's ship builds under a grant they hold, in a room the grant covers
and the issuer is in, while the grant is valid and within its budget and the ship's daily cap; the reply's footer and
label say whose grant it spent; a revoke stops the watcher's retries; and a Grants page lets a person make, read and
revoke grants.

**Architecture:** `tickets.py` decides basis `grant` in `_mode_for` through a new `_spendable_grant` (3b's
`_grant_validity`, `_grant_chain` and `_grant_policy`, and fresh owner mentions' `_mention_stale`), records the chain
and charges `budget_uses` in the ticket's own transaction, re-checks a running grant ticket when it is asked for again
(`_grant_lapsed`, a 409 saved with `keep=True`), and writes the footer and the source's `via_name`. `grants.py` gains
the one per-ship count the cap and the page share, and the walk back along `linked_room_id`. The agent's
`source_label` and the web app's label add ", via <grantee>"; the read-only prompt points to a grant or the Grants
page. The web app gains the Grants page. There is no schema change.

**Tech Stack:** Python 3.13, FastAPI, SQLite, pytest with FastAPI's `TestClient` (peer), the agent suite's fake station
(`agent/tests/conftest.py`), Playwright (`peer/tests/test_browser.py`), plain JavaScript and CSS. Peer tests run from
`peer/` with `PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider <files>`; agent tests
from `agent/` with `PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider <files>`.

**Spec:** `docs/superpowers/specs/2026-10-15-grants-step3-design.md` (approved under D8, revision 3, with its later
notes), section 3 (G15-G23), Testing 11-20 and its Review Focus. G15 and G19 are aligned with the fresh owner mentions
spec (`docs/superpowers/specs/2026-10-15-owner-mention-fresh-design.md`, approved under D8, landed on main at 3f2973b
and so in this base): `_mention_stale`, `MENTION_FRESH_SECONDS` (86,400) and its `old` and `answered` basis values.
Spec A (`docs/superpowers/specs/2026-10-08-instruction-layers-and-grants-design.md`) holds where both are silent.

**Base:** grants-3b at `6841ce0`, on branch grants-3c. When this plan was drafted, 3b was under its section 2 review on
the Pi. That review has since passed (Rio Grande, APPROVE WITH MINORS), and 3b is merged and deployed as main `d5843b8`,
whose tree equals `6841ce0`, so no anchor below changes. If 3b or main changes before building, rebase grants-3c and
re-check the anchors first: every edit below names its text exactly, so a moved anchor fails loudly instead of landing in
the wrong place. The review's one minor (nothing pinned the pre-check's read-only open) and Rio Grande's ruling on a
replaced room's `current` are Task 0, with tests.

**Dry run.** Every task was dry-run in a scratch worktree at `6841ce0`. Each RED output below is the one seen, each GREEN
ran, and each Step 5 mutation was applied alone and failed the test it names. The code blocks are the dry run's own
strings: applying every step in order to `6841ce0` reproduced the dry run's tree byte for byte, and replaying the tasks
one by one on it gave each RED and GREEN below. At the end the peer suite ran 932 passed and 1 skipped (907 at
`6841ce0`, plus this plan's 25 tests) and the agent suite 753 passed (751 plus 2).

Tasks: 0 3b's section 2 review (the read-only pre-check pinned, `current` without an id for a non-member); 1 the ticket
basis `grant` (G15, G16, the per-ship cap, the oldest grant, `old` and `answered`); 2 a re-sent grant ticket re-checked,
and 409 (G18); 3 the footer, the source's `via_name`, both labels (G17); 4 the read-only prompt and runs.py's docstring
(G19); 5 the Grants page (G20-G22); 6 API.md, the agent README and the whole suites (G23).

## Rulings

Decisions made before this plan (the coordinator's brief, and Rio Grande's section 2 ruling on 3b), and the ones this
plan adds. A fresh reviewer checks each; Andy can veto any.

| # | Ruling | Why |
| --- | --- | --- |
| R1 | A grantee's mention that a grant would otherwise let build, kept back only by `_mention_stale` (`old` or `answered`), reads with that basis; any other refusal reads with basis `none`. `_mention_stale` is asked only once a grant qualifies, so an old mention without a qualifying grant still says `none`. | Given (spec G15 as aligned with the fresh owner mentions spec): the labels agree for owners and grantees, and fresh owner mentions' R5 test (a non-owner's 48-hour-old mention reads `none`) keeps holding. |
| R2 | G18's re-check on a re-send covers G9's revocation, expiry, policy and ownership checks and the root issuer's membership of the message's room; not the budget or the per-ship cap. A failed re-check finishes the ticket and raises `Problem(409, reason, keep=True)`, so the finish is saved and the watcher's fallback note, sent with the finished ticket's id, gets 409 and goes out unlabelled (`_post_unlabelled`). | Given. `_grant_validity` gains `budget=True`; the re-send passes `budget=False`. |
| R3 | The page uses `GET /api/grants`, `POST /api/grants`, `POST /api/grants/{id}/revoke` and `GET /api/grants/people` exactly as 3b built them (the shapes in `grants.py`'s `_grant_view` and `grant_people`; `POST /api/grants` answers 201 with the view, revoke 200 with it, errors `{error}`). | Given. No route changes. |
| R4 | A grant's `current` room, shown to a viewer who is not a member of that room, carries no id: `current: {title: "a room you are not in"}`; a member still gets `{id, title}`. The listed room's own `id` stays for every viewer. | Rio Grande's ruling in 3b's section 2 review (room message a3fb9216), with the Pi reviewer's view: the id confers nothing, but no non-member needs it. It narrows G11's "(id and title)"; the coordinator adds the spec note. The listed room's id is in the grant's signed record, which `/signed` serves to the same viewers, so hiding it in the view would hide nothing. My own reading before the ruling was "keep as built" (ids are random and every room route answers a non-member 404), which the ruling supersedes. |
| R5 | The `serve --peer-tls` pre-check's read-only open is pinned by a database with a hot journal, not by spying on `sqlite3.connect`'s URI. | It tests the property (nothing is played back or written), not one spelling of it: `mode=rwc` and no mode both fail it, and a future read-only spelling still passes. |
| R6 | Seven tasks: Task 0 for 3b's review items, then the brief's six. Task 3 also carries the web app's one-line label change and its browser test, since both are G17. | The coordinator asked for the review items in a first task or a task 0. The label belongs with the source it reads. |
| R7 | `_mode_for` returns `(mode, basis, root_id, chain)`, chain being the grant rows root first (empty for owner and read tickets). Its only caller is `issue_ticket`. | The ticket needs the chain to record it and to charge each link. |
| R8 | Placement: `_spendable_grant`, `_grant_lapsed`, `_via_name` and `_footer` go in `tickets.py`; `_ship_grant_builds` and `_rooms_back` in `grants.py`, beside `_budget_used` and `_current_room`. | Tickets decide; grants know grants and their rooms. |
| R9 | One count, `_ship_grant_builds(db, ship_id, now)` (grant build tickets, `created > now - 86400`), serves G15's cap and G11's `ship_builds_left`. | The page can never say a ship has builds left that the ticket refuses. |
| R10 | "Local" is checked (`':'` in the room id) though a ticket's message is a `messages` row and a remote room's messages are `peer_messages`; test 11 writes a remote-id room by hand, as 3b's G8 test did. The ship's own membership is not checked in `_spendable_grant`: `issue_ticket` answers 404 for a ship outside the room before `_mode_for` runs, so that check could never fail there. | A check that costs one comparison and a test that can fail; a check that can't fail is left out. |
| R11 | A message `created` that isn't a number passes "made no later than the message", so `_mention_stale` reads it `old`, as it does an owner's (fresh owner mentions R4). | A naive `grant['created'] <= created` raises `TypeError` on text (a 500); R4's rule is never to raise. |
| R12 | A failed re-check's reasons: G9's own, `"<issuer> is no longer in this room"` (the name through `safe_line`), and `"The grant behind this run is gone"` for a chain whose grant row is missing (only by hand). | The spec names G9's reasons only. The 409 reaches the watcher, which logs it; no person reads it. |
| R13 | `via_name` appears only on a grant run's source; every other source is byte for byte as before. The ticket JSON gains no field: the footer carries the names. | Existing tests compare whole source dicts (owner, read, `old`); spec G17 lists `via_name` for grant runs. |
| R14 | The web app's label for a grant run is "builder run for Andy, via Jenn", its existing form plus ", via <via_name>", the same words as the agent's `source_label`. | Spec G17 and test 17 write the web label as "builder for Andy, via Jenn", but the web app's owner label is already "builder run for Andy" (`test_a_room_shows_which_ship_messages_came_from_runs`); one label for both readers. Reported as a spec ambiguity. |
| R15 | G19 with fresh owner mentions: when `limited` is `old` or `answered`, its reason sentence replaces the prompt's last sentence; otherwise the last sentence is G19's ("... can ask the ship's owner for a grant, or check the Grants page."). Never both. | Spec G19's "keeps both, the reason line first" read with fresh owner mentions' "Order with grants step 3" (the limited sentence replaces the last sentence when set, G19's is used otherwise) and its test 9 (a limited prompt never says "can ask the ship's owner"). A grantee whose mention is a day old holds a grant already. |
| R16 | The page's lists: "Held by you" is every listed grant whose grantee is the caller; "Given by you" is every other listed grant (the ones the caller issued, and, only after a hand edit in step 3, ones over ships the caller owns, which G10 lets them revoke). Revoke shows on "Given by you" for a grant not yet revoked; the station decides (403, 409). | G11's list holds exactly those grants; every one not held is one the caller has power over. |
| R17 | No click guard on the Grants page. The ask takes the Revoke button's place with its question first, so the second press of a hurried double click lands on text, at desktop and phone widths; a test pins it, and its mutation (the buttons first) shows the danger. Cancel gets the focus, and the confirm is away from where Revoke was, as on the board. | The board's guard exists because a re-render moved another control under the pointer; here nothing moves under it. One write at a time still holds (R18). |
| R18 | One grant write at a time (`state.grantSaving`), for making and revoking, and the list is read again after each. | A double click on "Make grant" would otherwise make two grants: no 409 stops a second POST. |
| R19 | The page checks three things before sending: a person, at least one ship, and at least one room (or "Any room you share with them"). Everything else, a budget that isn't a whole number from 1 to 500 among them, is the station's own message. | The station's messages for those three name JSON fields ("rooms is "*" or a list of 1 to 20 room ids ..."). |
| R20 | No `maxlength` on the revoke reason. | The station counts code points and a browser counts UTF-16 units (the board's Review Focus 5); the station's 400 says so. |
| R21 | Entering `#grants` reloads the home data (ships and rooms) and then the grants and the people list, as the Board route reloads. The draft form is kept in `state.grantForm` through re-renders, and read from the form itself, so a room ticked for one person and gone from the next person's list is dropped. | The room list must be the one the station would accept now. |
| R22 | `agent/README.md`'s watcher paragraphs name grant builds, the grant footer, the new label and the stopped retry. | G23 names API.md only, but the README is where a ship's owner reads what the watcher does; it would be wrong after this merge. |

## Global Constraints

- Spec values, verbatim:
  - G15: build with basis `grant` when "the ship is mentioned in the message, the ship has an owner, and the author is a person other than that owner, and a grant G meets all of these": G's grantee is the author, G's targets include the ship, and `direct` is in G's actions; G covers the message's room R (R current, local and not a breakout; G's rooms `"*"`, or R or a room R replaced is listed, walking back along `linked_room_id` with a seen set); "when the ticket is issued, the author, the ship and G's root issuer are all members of R"; "G is valid now (G9), and no link in its chain says `confirm: each`"; "G was created no later than the message (equal times count), the message was posted at most 24 hours before the ticket (exactly 24 hours still counts), and the ship has not answered it" (`_mention_stale(db, ship_id, message)`, `abs(now - created) <= 86400`); "the ship has had fewer than `builds_per_ship_per_day` grant build tickets in the last 24 hours, under any grant. Owner builds are not counted".
  - "When several grants qualify, the oldest one is used (by `created`, then `id`)"; a grant that fails a condition is skipped and the next oldest tried.
  - `builds_per_ship_per_day` is 20, read through `_grant_policy(db)`.
  - G16: "The ticket records basis `grant`, `root_id` as the root's issuer, and `chain` as the grant ids, root first. The station inserts one `budget_uses` row per link in the same transaction. One message that mentions two ships under one grant charges it once per ship's ticket."
  - G17: footer `Builder for <root>, via <grantee> · grant #a1b2`, names through `safe_line`; several links read `grants #a1b2 > #c3d4`; source `{kind: "run", mode: "build", basis: "grant", root_name, via_name, answering}`; the agent's `source_label` "appends ", via <via_name>" when the source has one".
  - G18: "A grant `build` is never deferred, because only `read` decisions are"; a re-send re-checks "G9's revocation, expiry, policy and ownership checks, and the root issuer's membership of the room. It does not re-check the budget or the per-ship cap"; on failure "the ticket is finished and the request gets 409 with the reason", saved with `keep=True`.
  - G19: the read-only prompt says the author "can ask the ship's owner for a grant, or check the Grants page"; runs.py's docstring gains "or a person the owner granted".
  - G21's line: "Their mentions start builder runs of your ships on your machine. A run can read your repository and uses your model time, and its reply is posted in the room." How long: 1 day, 3 days, 7 days or 30 days, 7 days chosen first. Builds a day: 1 to 500, 5 filled in. Specific rooms chosen first, or "Any room you share with them" (`"*"`).
  - G22: "Revoke" asks first, in place, like the board's Drop, with an optional reason; one write at a time; every value escaped.
  - `TICKET_LIFETIME` 7,200 s; `MENTION_FRESH_SECONDS` 86,400.
- Production SQL names its columns (the `INSERT INTO budget_uses(grant_id,ticket_id,created)` and `tickets(...)` lists).
- Every test is named, written first and seen failing first, or, where it guards behaviour that already holds, the plan
  says so and Step 5's mutation shows it bites.
- Browser tests wait for what they click: Playwright's locators wait for the rendered page, and each test waits for a
  locator the render shows before it acts. The Grants page has no click guard (R17), so its tests need no `settle`.
- Repo norms: a new test file goes in the sdist `only-include` list of `peer/pyproject.toml`.
- Superyak's repository only. The merge goes through section 2 of the station law: Rio Grande approves in the room, and
  the Pi suites pass.

## Review Focus

Inputs no spec test names, most likely to bite a person first. Each is pinned by a test in its task.

1. A grantee whose display name holds a newline and `@rio-grande`: the footer is posted in the room under the build's
   reply, so an unsafe name would mention rio-grande and start its run. The names go through `safe_line` (Task 3,
   `test_a_grantees_name_never_mentions_anyone_in_the_footer_or_the_label`).
2. A double click on "Make grant": no 409 stops a second POST, so it would make two grants and double the person's
   builds. One write at a time; the test counts the POSTs (Task 5, `test_a_double_click_on_make_grant_makes_one_grant`).
3. Andy is the station's admin, and `/api/ships` gives an admin every ship: a form listing Jenn's ships would offer
   grants the station refuses. The form lists only ships whose `owner_id` is the caller (Task 5,
   `test_an_admin_is_offered_only_his_own_ships`).
4. Changing the chosen person after ticking rooms: a room the new person isn't in must not be sent (G8 step 2 would
   refuse the grant), and a replaced room must never be offered (Task 5,
   `test_choosing_another_person_rebuilds_the_rooms_and_drops_the_ones_they_are_not_in`).
5. Andy adds a member while a granted build runs: the room is replaced, and a re-send that re-ran all of G15 would
   refuse the run mid-way. The re-send checks only the issuer's membership of the message's room (Task 2,
   `test_a_resend_after_the_room_gains_a_member_keeps_its_ticket`).

## Known limits (beyond the spec's)

- `_spendable_grant` reads every grant the author holds and checks each in Python. A person holds a handful.
- The 409 reason of a failed re-check is logged by the watcher, not shown to people; the fallback note says only that
  the ship couldn't answer.
- The page reads ships and rooms when `#grants` is entered; a room made in another tab shows after the page is entered
  again.
- Task 1's walk mutation (dropping the seen list) makes the cycle test hang; run it under `timeout 60` (coreutils;
  `gtimeout` on a Mac with Homebrew) to see exit 124.
- Task 5's RED takes about three minutes: each of its six tests waits 30 s for the Grants link that isn't there yet.

## File Structure

- Modify `peer/superyak_peer/grants.py`: `_member_title` and `current` without an id (Task 0); `_ship_grant_builds`,
  `_rooms_back` (Task 1); `_grant_validity(..., budget=True)` (Task 2).
- Modify `peer/superyak_peer/tickets.py`: the module docstring, `_in_room`, `_made_by`, `_mode_for`, `_spendable_grant`,
  the ticket's chain and budget uses (Task 1); `_grant_lapsed` and the re-send path (Task 2); `_via_name`, `_footer`,
  `_ticket_json`, `_sources` (Task 3).
- Modify `agent/superyak_agent/station.py` (`source_label`, Task 3), `agent/superyak_agent/watch.py` (`build_prompt`,
  Task 4), `agent/superyak_agent/runs.py` (its docstring, Task 4).
- Modify `peer/superyak_peer/static/app.js` (the label, Task 3; the Grants page, Task 5) and `app.css` (Task 5).
- Modify `peer/pyproject.toml` (Task 1), `peer/API.md` (Tasks 0 and 6), `agent/README.md` (Task 6).
- Create `peer/tests/test_grant_tickets.py` (tests 11-19). Modify `peer/tests/test_signatures.py` and
  `peer/tests/test_grants.py` (Task 0), `peer/tests/test_ship_agent.py` (Tasks 2 and 3), `peer/tests/test_browser.py`
  (Tasks 3 and 5), `agent/tests/test_station.py` (Task 3), `agent/tests/test_watch.py` (Task 4).

---

### Task 0: 3b's section 2 review: the read-only pre-check pinned, and `current` without an id for a non-member

**Files:**
- Modify: `peer/superyak_peer/grants.py` (`_room_label`, and the `current` lines in `_grant_view`)
- Modify: `peer/API.md` ("## Grants", **Reading.**)
- Test: `peer/tests/test_signatures.py`, `peer/tests/test_grants.py`

**Interfaces:**
- Consumes: `refuse_a_lost_identity_before_the_store` (3b, `signatures.py`); `_current_room`, `NOT_IN_ROOM` (3b).
- Produces: `Grants._member_title(db, actor, room_id) -> str | None`; a replaced listed room's `current` is
  `{id, title}` for a member of the current room and `{title: "a room you are not in"}` for anyone else.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_signatures.py`, insert before

```python
def test_the_restore_test_passes_on_a_copy_holding_signed_records(tmp_path, monkeypatch, capsys):
```

this:

```python
def hot_journal(directory):
    """A database left as a crash leaves it: a rollback journal that must be played back before the next read. A writer
    whose cache holds two pages spills its changes into the file mid-transaction, so the journal is synced and hot;
    the pair is copied while that transaction is still open."""
    import shutil
    import sqlite3
    from contextlib import closing
    live = directory.parent / f'{directory.name}-live'
    live.mkdir(mode=0o700)
    directory.mkdir(mode=0o700)
    with closing(sqlite3.connect(live / 'peer.sqlite3')) as db:
        db.execute('CREATE TABLE revision_signatures(layer_id TEXT NOT NULL, revision INTEGER NOT NULL, signature TEXT NOT NULL)')
        db.executemany('INSERT INTO revision_signatures(layer_id, revision, signature) VALUES(?, 1, ?)',
                       [(f'l{n}', 'x' * 500) for n in range(200)])
        db.commit()
    with closing(sqlite3.connect(live / 'peer.sqlite3', isolation_level=None)) as db:
        db.execute('PRAGMA cache_size=2')
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE revision_signatures SET signature=?', ('y' * 500,))
        for name in ('peer.sqlite3', 'peer.sqlite3-journal'):
            shutil.copyfile(live / name, directory / name)
        db.execute('ROLLBACK')
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def test_the_peer_tls_check_never_plays_back_a_hot_journal(tmp_path):
    """3b's section 2 review: the `serve --peer-tls` check opens the database read-only. A read-write connection that
    only reads changes nothing in a clean database, so test 4c alone can't tell; a hot journal can. Read-only, SQLite
    may not play it back, so the check refuses, naming the database, and leaves both files exactly as they were. A
    read-write connection would play the journal back, delete it, and then read the signed rows."""
    from superyak_peer.signatures import refuse_a_lost_identity_before_the_store
    crashed = tmp_path / 'crashed'
    before = hot_journal(crashed)
    assert sorted(before) == ['peer.sqlite3', 'peer.sqlite3-journal']
    with pytest.raises(ValueError, match='peer.sqlite3 could not be read read-only'):
        refuse_a_lost_identity_before_the_store(crashed)
    assert {path.name: path.read_bytes() for path in crashed.iterdir()} == before


```

In `peer/tests/test_grants.py`, replace

```python
    assert listed(clients[1])[0]['rooms'][1]['current'] == {'id': third['id'], 'title': 'a room you are not in'}
```

with

```python
    assert listed(clients[1])[0]['rooms'][1]['current'] == {'title': 'a room you are not in'}  # no id (3b's section 2 review)
```

`test_the_peer_tls_check_never_plays_back_a_hot_journal` passes before this task: the pre-check already opens with
`?mode=ro`. It guards that open, which test 4c can't (a read-write connection that only reads changes no byte of a clean
database), and Step 5's mutations show it bites.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_grants.py`
Expected: `1 failed, 55 passed`. The failure is
`test_room_titles_show_only_to_members_and_a_replaced_room_shows_the_current_one`, at the changed line:
`AssertionError: assert {'id': '...', 'title': 'a room you are not in'} == {'title': 'a room you are not in'}` (pytest:
"Left contains 1 more item: {'id': '...'}"). The hot-journal test passes (see above).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, replace

```python
    def _room_label(self, db, actor, room_id):
        """G11: a room's title for its members only; anyone else sees NOT_IN_ROOM."""
        row = db.execute('SELECT rooms.title FROM rooms JOIN room_members ON room_members.room_id=rooms.id '
                         'WHERE rooms.id=? AND room_members.user_id=?', (room_id, actor)).fetchone()
        return row['title'] if row else NOT_IN_ROOM

```

with

```python
    def _member_title(self, db, actor, room_id):
        """A room's title when the caller is a member of it, else None."""
        row = db.execute('SELECT rooms.title FROM rooms JOIN room_members ON room_members.room_id=rooms.id '
                         'WHERE rooms.id=? AND room_members.user_id=?', (room_id, actor)).fetchone()
        return row['title'] if row else None

    def _room_label(self, db, actor, room_id):
        """G11: a room's title for its members only; anyone else sees NOT_IN_ROOM."""
        title = self._member_title(db, actor, room_id)
        return NOT_IN_ROOM if title is None else title

```

In `peer/superyak_peer/grants.py`, replace

```python
                if current is not None:
                    entry['current'] = {'id': current, 'title': self._room_label(db, actor, current)}
```

with

```python
                if current is not None:  # 3b's section 2 review: no id for a non-member, who has no use for it
                    title = self._member_title(db, actor, current)
                    entry['current'] = {'title': NOT_IN_ROOM} if title is None else {'id': current, 'title': title}
```

In `peer/API.md`, replace

```markdown
ship_builds_left}]`), `rooms` (`"*"`, or for each listed room `{id, title}` plus `current: {id, title}` when newer
linked rooms have replaced it, following the links forward), `expires`, `budget`, `budget_left`, `created`, `revoked`,
```

with

```markdown
ship_builds_left}]`), `rooms` (`"*"`, or for each listed room `{id, title}` plus `current` when newer linked rooms
have replaced it, following the links forward: `{id, title}` for a member of that room, `{title}` alone for anyone
else), `expires`, `budget`, `budget_left`, `created`, `revoked`,
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_signatures.py tests/test_grants.py`
Expected: `56 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run the file named, see the named test fail, restore:
- `'?mode=rwc'` for `'?mode=ro'` in `refuse_a_lost_identity_before_the_store` → `tests/test_signatures.py::test_the_peer_tls_check_never_plays_back_a_hot_journal`
  ("Regex pattern did not match": the journal is played back and deleted, the signed rows are read, and the refusal is
  the lost-identity one);
- `''` for `'?mode=ro'` (no mode) → the same test;
- `entry['current'] = {'id': current, 'title': NOT_IN_ROOM if title is None else title}` (the id for everyone) →
  `tests/test_grants.py::test_room_titles_show_only_to_members_and_a_replaced_room_shows_the_current_one`;
- `entry['current'] = {'title': NOT_IN_ROOM if title is None else title}` (no id for anyone) → the same test (a member's
  `current` lacks its id).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/API.md peer/tests/test_signatures.py peer/tests/test_grants.py
git commit -m "Grants 3c: the --peer-tls pre-check pinned read-only, and a replaced room's current room carries no id for a non-member (3b's section 2 review)"
```

---

### Task 1: The ticket basis `grant` (G15, G16, the per-ship cap, the oldest grant, `old` and `answered`)

**Files:**
- Modify: `peer/superyak_peer/grants.py` (two methods, one line in `_grant_view`)
- Modify: `peer/superyak_peer/tickets.py` (the docstring and imports, two helpers before `class Tickets`, `issue_ticket`'s
  insert, `_mode_for`)
- Modify: `peer/pyproject.toml` (the sdist list)
- Create: `peer/tests/test_grant_tickets.py`

**Interfaces:**
- Consumes: `_grant_chain`, `_grant_validity`, `_grant_policy`, `_insert_grant` (3b); `_mention_stale`, `_breakout`,
  `REPLACED_ROOMS`; test helpers `make`, `charge`, `revoke_by_hand` (`test_grants.py`).
- Produces:
  - `Grants._ship_grant_builds(db, ship_id, now) -> int`, `Grants._rooms_back(db, room_id) -> list[str]` (the room
    first, then each room it replaced).
  - `Tickets._mode_for(db, ship, message) -> (mode, basis, root_id, chain_rows)`;
    `Tickets._spendable_grant(db, ship, message) -> list[Row] | None` (root first).
  - A grant ticket: `basis='grant'`, `root_id` the root's issuer, `chain` the grant ids root first, one `budget_uses` row
    per link at the ticket's `created`.

- [ ] **Step 1: Write the failing tests**

Create `peer/tests/test_grant_tickets.py`:

```python
"""Spending a grant (spec A step 3, merge 3c: G15-G18 of docs/superpowers/specs/2026-10-15-grants-step3-design.md)."""
import json
from superyak_peer import grants as G
from superyak_peer.common import uid
from test_grants import charge, make, revoke_by_hand

DAY = 86400


def ships(store, owner_id, *names):
    """Ships written directly, as test_grants' fleet() writes them (docking allows 20 an hour, and scrypt is slow):
    {username: {id, username}}. owner_id None makes a resident, which has no owner."""
    made = {}
    with store.transaction() as db:
        for name in names:
            key = uid()
            db.execute("INSERT INTO users(id,username,name,salt,password_hash,is_admin,created,kind,owner_id) "
                       "VALUES(?,?,?,?,?,0,?,'ship',?)",
                       (key, name, name.replace('-', ' ').title(), b'\0' * 16, b'\0' * 32, store.clock(), owner_id))
            made[name] = {'id': key, 'username': name}
    return made


def room(store, owner, title, *members):
    return store.create_room(owner['id'], title, [member['id'] for member in members])['id']


def mention(store, author, room_id, *targets):
    """A message by author that mentions each target ship, posted through the store (a person's login lasts a day, and
    these tests move the clock further)."""
    body = ' '.join(f'@{ship["username"]}' for ship in targets) + ' please fix the notes'
    return store.send_message(author['id'], room_id, uid(), body)


def decide(store, ship, message):
    """The ticket's (mode, basis), as POST /api/ships/me/tickets decides it for a watcher that asks without decisions."""
    got = store.issue_ticket(ship['id'], message['id'])
    return got['mode'], got['basis']


def ticket_row(store, ship, message):
    with store.transaction() as db:
        return dict(db.execute('SELECT * FROM tickets WHERE ship_id=? AND message_id=?', (ship['id'], message['id'])).fetchone())


def uses(store, grant_id):
    with store.transaction() as db:
        return [dict(row) for row in db.execute('SELECT grant_id, ticket_id, created FROM budget_uses WHERE grant_id=? '
                                                'ORDER BY created, ticket_id', (grant_id,))]


def test_only_the_owner_and_a_valid_grantee_in_a_room_with_the_issuer_build(env):
    """Test 11 and spec Review Focus 2: spec A Testing 1 without directs, as one table, authors first, then grant states
    for one grantee. Each case has its own ship, so each grant names only the ship its case mentions."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    names = ('own', 'valid', 'none', 'other-ship', 'decoy', 'other-room', 'spent', 'expired', 'revoked', 'after', 'same',
             'day', 'older', 'answered', 'left', 'star', 'removed', 'by-ship', 'side', 'far', 'each', 'instruct')
    s = ships(store, patient['id'], *names)
    s.update(ships(store, None, 'odo'))
    defiant = ships(store, doctor['id'], 'defiant')['defiant']
    ops = room(store, patient, 'Ops', doctor, organizer, defiant, s['odo'],
               *[s[name] for name in names if name not in ('left', 'star', 'removed', 'side', 'far')])
    other = room(store, patient, 'Other', doctor, s['other-room'])
    left = room(store, patient, 'Left', doctor, s['left'])
    theirs = room(store, doctor, 'Theirs', s['star'])  # doctor's room with patient's ship, without patient
    shared = room(store, doctor, 'Shared', patient, s['removed'])  # doctor's room; doctor will remove patient
    side = room(store, patient, 'Side', doctor, s['side'])
    far = 'ab' * 32 + ':room-1'  # a remote room's id, written by hand, with its members and a message
    with store.transaction() as db:
        db.execute('INSERT INTO breakouts(room_id, creator_id, created) VALUES(?,?,?)', (side, s['side']['id'], clock[0]))
        db.execute('INSERT INTO rooms(id, owner_id, title, epoch, linked_room_id) VALUES(?,?,?,1,NULL)', (far, patient['id'], 'Far'))
        db.executemany('INSERT INTO room_members(room_id, user_id) VALUES(?,?)',
                       [(far, patient['id']), (far, doctor['id']), (far, s['far']['id'])])
    grant = {name: make(store, patient, doctor, [s[name]], hours=48)
             for name in ('valid', 'decoy', 'spent', 'revoked', 'day', 'older', 'answered', 'left', 'star', 'side',
                          'far', 'each', 'instruct')}
    grant['other-room'] = make(store, patient, doctor, [s['other-room']], rooms=[other], hours=48)
    grant['removed'] = make(store, patient, doctor, [s['removed']], rooms=[shared], hours=48)
    grant['expired'] = make(store, patient, doctor, [s['expired']], hours=24)  # expired by the time it is asked
    grant['by-ship'] = make(store, patient, defiant, [s['by-ship']], hours=48)  # to a ship, by hand: G8 refuses it
    grant['odo'] = make(store, patient, doctor, [s['odo']], hours=48)  # over a resident, by hand: G8 refuses it
    revoke_by_hand(store, grant['revoked'], patient)
    with store.transaction() as db:  # by hand: step 3 never writes either
        db.execute("UPDATE grants SET confirm='each' WHERE id=?", (grant['each'],))
        db.execute("""UPDATE grants SET actions='["instruct"]' WHERE id=?""", (grant['instruct'],))
    clock[0] += 100
    asked = {'older': mention(store, doctor, ops, s['older'])}  # 86,400.5 s before the tickets
    clock[0] += 0.5
    asked['day'] = mention(store, doctor, ops, s['day'])  # exactly 86,400 s before the tickets
    clock[0] += DAY - 52
    asked['after'] = mention(store, doctor, ops, s['after'])
    clock[0] += 1
    grant['after'] = make(store, patient, doctor, [s['after']], hours=48)  # made a second after the message
    clock[0] += 1
    grant['same'] = make(store, patient, doctor, [s['same']], hours=48)
    asked['same'] = mention(store, doctor, ops, s['same'])  # posted in the second the grant was made
    asked['own'] = mention(store, patient, ops, s['own'])
    asked['other person'] = mention(store, organizer, ops, s['valid'])
    asked['by-ship'] = mention(store, defiant, ops, s['by-ship'])
    asked['odo'] = mention(store, doctor, ops, s['odo'])
    for name in ('valid', 'none', 'spent', 'expired', 'revoked', 'answered', 'each', 'instruct'):
        asked[name] = mention(store, doctor, ops, s[name])
    asked['other-ship'] = mention(store, doctor, ops, s['other-ship'])  # doctor's grant names decoy, not this ship
    asked['other-room'] = mention(store, doctor, ops, s['other-room'])  # its grant lists Other only
    store.send_message(s['answered']['id'], ops, uid(), 'Already on it', None, asked['answered']['id'])
    asked['left'] = mention(store, doctor, left, s['left'])
    store.remove_participant(patient['id'], left, doctor['id'])  # the author no longer in the room
    asked['star'] = mention(store, doctor, theirs, s['star'])
    asked['removed'] = mention(store, doctor, shared, s['removed'])
    store.remove_participant(doctor['id'], shared, patient['id'])  # the room's owner removed the issuer
    asked['side'] = mention(store, doctor, side, s['side'])
    with store.transaction() as db:
        db.execute("INSERT INTO messages(id, room_id, author_id, client_message_id, body, epoch, created) "
                   "VALUES('far-1', ?, ?, 'far-1', '@far please', 1, ?)", (far, doctor['id'], clock[0]))
        db.execute("INSERT INTO mentions(message_id, room_id, user_id) VALUES('far-1', ?, ?)", (far, s['far']['id']))
    asked['far'] = {'id': 'far-1'}
    charge(store, grant['spent'], 1, 2, 3, 4, 5)  # its 5 builds, used in the last minute
    clock[0] += 50  # the tickets: 86,400 s after 'day' was posted
    target = {'other person': s['valid']}
    got = {name: decide(store, target.get(name, s.get(name)), message) for name, message in asked.items()}
    assert got == {
        'own': ('build', 'owner'), 'valid': ('build', 'grant'), 'same': ('build', 'grant'), 'day': ('build', 'grant'),
        'older': ('read', 'old'), 'answered': ('read', 'answered'),
        'other person': ('read', 'none'), 'by-ship': ('read', 'none'), 'odo': ('read', 'none'), 'none': ('read', 'none'),
        'other-ship': ('read', 'none'), 'other-room': ('read', 'none'), 'spent': ('read', 'none'),
        'expired': ('read', 'none'), 'revoked': ('read', 'none'), 'after': ('read', 'none'), 'left': ('read', 'none'),
        'star': ('read', 'none'), 'removed': ('read', 'none'), 'side': ('read', 'none'), 'far': ('read', 'none'),
        'each': ('read', 'none'), 'instruct': ('read', 'none')}


def test_a_grant_build_records_its_grant_and_charges_it_once(env):
    """G16: basis grant, root_id the root's issuer, chain the grant ids root first, and one budget_uses row per link in
    the ticket's transaction, at the ticket's time. An owner build and a read charge nothing."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, organizer, s)
    grant = make(store, patient, doctor, [s], hours=48)
    asked, owners, others = mention(store, doctor, ops, s), mention(store, patient, ops, s), mention(store, organizer, ops, s)
    clock[0] += 5
    assert [decide(store, s, m) for m in (asked, owners, others)] == [('build', 'grant'), ('build', 'owner'), ('read', 'none')]
    row = ticket_row(store, s, asked)
    assert (row['root_id'], json.loads(row['chain'])) == (patient['id'], [grant])
    assert uses(store, grant) == [{'grant_id': grant, 'ticket_id': row['id'], 'created': clock[0]}]
    assert json.loads(ticket_row(store, s, owners)['chain']) == [] and json.loads(ticket_row(store, s, others)['chain']) == []
    with store.transaction() as db:
        assert db.execute('SELECT count(*) FROM budget_uses').fetchone()[0] == 1


def test_a_spent_budget_reads_until_its_builds_are_a_day_old_and_two_ships_share_it(env):
    """Test 13 and spec Review Focus 4: after `budget` builds the next mention reads; a build exactly 24 hours old no longer
    counts; builds of either ship count against one grant's budget."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    grant = make(store, patient, doctor, [serenity, rio], hours=48, budget=2)
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('build', 'grant')
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('build', 'grant')  # the other ship, the same budget
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('read', 'none')
    clock[0] += DAY - 1
    assert decide(store, serenity, mention(store, doctor, ops, serenity)) == ('read', 'none')  # a second short of a day
    clock[0] += 1
    assert decide(store, rio, mention(store, doctor, ops, rio)) == ('build', 'grant')  # the first two are a day old now
    assert next(view for view in store.list_grants(patient['id']) if view['id'] == grant)['budget_left'] == 1


def test_the_21st_grant_build_of_a_ship_in_a_day_reads_across_grants_and_owner_builds_never_count(env):
    """Test 14: builds_per_ship_per_day (20) counts grant build tickets under every grant; the 21st reads though its own
    grant has budget left, and it builds again once those builds are a day old. ship_builds_left shows the ship's
    count on the other grant."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, family, serenity)
    first = make(store, patient, doctor, [serenity], hours=48, budget=12)
    second = make(store, patient, family, [serenity], hours=48, budget=12)
    left = lambda viewer, grant: next(view for view in store.list_grants(viewer['id']) if view['id'] == grant)['targets'][0]['ship_builds_left']
    assert [decide(store, serenity, mention(store, doctor, ops, serenity)) for _ in range(12)] == [('build', 'grant')] * 12
    assert left(family, second) == 8  # the first grant's builds count on the second's ship
    assert [decide(store, serenity, mention(store, patient, ops, serenity)) for _ in range(3)] == [('build', 'owner')] * 3
    assert left(family, second) == 8  # owner builds don't count
    assert [decide(store, serenity, mention(store, family, ops, serenity)) for _ in range(8)] == [('build', 'grant')] * 8
    assert left(family, second) == 0 and left(patient, first) == 0
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('read', 'none')  # the 21st; 4 left on its grant
    clock[0] += DAY - 1
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('read', 'none')
    clock[0] += 1
    assert decide(store, serenity, mention(store, family, ops, serenity)) == ('build', 'grant')


def test_the_oldest_grant_is_charged_and_the_next_when_it_has_no_budget(env, monkeypatch):
    """Test 15 and spec Review Focus 1: of two valid grants the oldest (by created, then id) is charged, and only it; once it
    has no budget left, the newer one is."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    older = make(store, patient, doctor, [serenity], hours=48, budget=1)
    clock[0] += 1
    newer = make(store, patient, doctor, [serenity], hours=48, budget=5)
    first, second = mention(store, doctor, ops, serenity), mention(store, doctor, ops, serenity)
    assert decide(store, serenity, first) == ('build', 'grant') and json.loads(ticket_row(store, serenity, first)['chain']) == [older]
    assert (len(uses(store, older)), len(uses(store, newer))) == (1, 0)
    assert decide(store, serenity, second) == ('build', 'grant') and json.loads(ticket_row(store, serenity, second)['chain']) == [newer]
    assert (len(uses(store, older)), len(uses(store, newer))) == (1, 1)
    monkeypatch.setattr(G, 'uid', iter(['f' * 32, '0' * 32]).__next__)  # made in one second: the id decides
    made_first = make(store, patient, doctor, [rio], hours=48)
    made_second = make(store, patient, doctor, [rio], hours=48)
    third = mention(store, doctor, ops, rio)
    assert (made_first, made_second) == ('f' * 32, '0' * 32)
    assert decide(store, rio, third) == ('build', 'grant') and json.loads(ticket_row(store, rio, third)['chain']) == ['0' * 32]


def test_a_grant_naming_a_room_follows_it_forward_and_never_builds_in_a_replaced_room(env):
    """Test 16 and spec Review Focus 3: X becomes X' and then X'' as members are added; a grant naming X builds in each
    current room, and a mention in X or X', once replaced, reads. A linked_room_id cycle made by hand ends the walk."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    x = room(store, patient, 'Plans', doctor, serenity)
    grant = make(store, patient, doctor, [serenity], rooms=[x], hours=48, budget=20)
    early = mention(store, doctor, x, serenity)  # posted while X was current, asked once it is replaced
    x1 = store.add_participants(patient['id'], x, [family['id']])['id']
    assert decide(store, serenity, mention(store, doctor, x1, serenity)) == ('build', 'grant')
    x2 = store.add_participants(patient['id'], x1, [organizer['id']])['id']
    assert decide(store, serenity, mention(store, doctor, x2, serenity)) == ('build', 'grant')
    assert decide(store, serenity, early) == ('read', 'none')
    assert decide(store, serenity, mention(store, doctor, x, serenity)) == ('read', 'none')
    assert decide(store, serenity, mention(store, doctor, x1, serenity)) == ('read', 'none')
    loop_a, loop_b = room(store, patient, 'Loop A', doctor), room(store, patient, 'Loop B', doctor)
    looped = room(store, patient, 'Looped', doctor, serenity)
    with store.transaction() as db:  # Looped replaced Loop A, which replaced Loop B, which replaced Loop A
        for key, replaced in ((looped, loop_a), (loop_a, loop_b), (loop_b, loop_a)):
            db.execute('UPDATE rooms SET linked_room_id=? WHERE id=?', (replaced, key))
    assert decide(store, serenity, mention(store, doctor, looped, serenity)) == ('read', 'none')  # the walk ends
    make(store, patient, doctor, [serenity], rooms=[loop_b], hours=48)
    assert decide(store, serenity, mention(store, doctor, looped, serenity)) == ('build', 'grant')  # Loop B is on the walk
    assert len(uses(store, grant)) == 2


def test_one_message_naming_two_ships_under_one_grant_with_one_build_left(env):
    """Test 19 and spec Review Focus 5: the first ship's ticket builds and spends the last build; the second reads."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'serenity', 'rio-grande')
    serenity, rio = s['serenity'], s['rio-grande']
    ops = room(store, patient, 'Ops', doctor, serenity, rio)
    grant = make(store, patient, doctor, [serenity, rio], hours=48, budget=2)
    charge(store, grant, 10)
    both = mention(store, doctor, ops, serenity, rio)
    assert decide(store, serenity, both) == ('build', 'grant')
    assert decide(store, rio, both) == ('read', 'none')
    assert [use['ticket_id'] for use in uses(store, grant)][1:] == [ticket_row(store, serenity, both)['id']]


def test_a_grantees_mention_with_an_unusable_created_reads_old_and_never_raises(env):
    """G15 with fresh owner mentions R4: a created that is text or infinite can't be compared with the grant's; the
    ticket reads old, as an owner's would, and the request never fails."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    ops = room(store, patient, 'Ops', doctor, serenity)
    make(store, patient, doctor, [serenity], hours=48)
    for value in (float('inf'), 'abc'):
        asked = mention(store, doctor, ops, serenity)
        with store.transaction() as db:
            db.execute('UPDATE messages SET created=? WHERE id=?', (value, asked['id']))
        assert decide(store, serenity, asked) == ('read', 'old'), value
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py`
Expected: `8 failed`, each because a grantee's mention reads `('read', 'none')` today. Test 11's table shows five
differing rows: `valid`, `same` and `day` expect `('build', 'grant')`, `older` expects `('read', 'old')` and `answered`
expects `('read', 'answered')`. The others fail at their first grant build (`At index 0 diff: 'read' != 'build'`), and
the unusable-created test with `AssertionError: inf` (`'none' != 'old'`).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, insert before

```python
    def _grant_validity(self, db, grant):
```

this:

```python
    def _ship_grant_builds(self, db, ship_id, now):
        """A ship's grant build tickets in the last 24 hours, under every grant: G11's ship_builds_left and G15's per-ship
        cap read this one count, so the page and the ticket can't disagree. Owner builds never count."""
        return db.execute("SELECT count(*) FROM tickets WHERE ship_id=? AND mode='build' AND basis='grant' AND created>?",
                          (ship_id, now - DAY)).fetchone()[0]

```

In `peer/superyak_peer/grants.py`, replace

```python
            # G11: the ship's grant builds in the last 24 hours, under every grant. Merge 3c writes these tickets.
            built = db.execute("SELECT count(*) FROM tickets WHERE ship_id=? AND mode='build' AND basis='grant' AND created>?",
                               (ship_id, now - DAY)).fetchone()[0]
```

with

```python
            built = self._ship_grant_builds(db, ship_id, now)  # G11: under every grant, as G15's cap counts them
```

In `peer/superyak_peer/grants.py`, insert before

```python
    def _current_room(self, db, room_id):
```

this:

```python
    def _rooms_back(self, db, room_id):
        """G15: a room and every room it replaced, walking back along linked_room_id, the room itself first. A seen list
        ends the walk at a cycle made by hand, so it always ends."""
        walked, key = [], room_id
        while key is not None and key not in walked:
            walked.append(key)
            row = db.execute('SELECT linked_room_id FROM rooms WHERE id=?', (key,)).fetchone()
            key = row['linked_room_id'] if row else None
        return walked

```

In `peer/superyak_peer/tickets.py`, replace

```python
"""Run tickets: just before a run, the station decides its mode and records it (spec A, section 4). Step 1 of the
build moves today's rule here unchanged: the ship's owner, mentioning it, gets a builder; everyone else gets a
read-only run. Later steps add grants and directs to the same decision."""
import json
import math
from .common import Problem, require, text, uid
```

with

```python
"""Run tickets: just before a run, the station decides its mode and records it (spec A, section 4). The ship's owner,
mentioning it, gets a builder; so does a person holding a grant over it (spec A step 3, G15); everyone else gets a
read-only run. Step 5 adds directs to the same decision."""
import json
import math
from .common import REPLACED_ROOMS, Problem, require, text, uid
```

In `peer/superyak_peer/tickets.py`, insert before

```python
class Tickets:
```

this:

```python
def _in_room(db, room_id, user_id):
    return db.execute('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', (room_id, user_id)).fetchone() is not None


def _made_by(grant, created):
    """G15: the grant was made no later than the message (equal times count). A `created` that isn't a number can't be
    compared: it passes here, and _mention_stale reads it `old`, so the read's basis says old, as an owner's would."""
    return not isinstance(created, (int, float)) or grant['created'] <= created


```

In `peer/superyak_peer/tickets.py`, replace

```python
            mode, basis, root = self._mode_for(db, ship, message)
```

with

```python
            mode, basis, root, chain = self._mode_for(db, ship, message)
```

In `peer/superyak_peer/tickets.py`, replace

```python
            key = uid()
            bound = json.dumps([[l['layer_id'], l['revision']] for l in self._binding_layers(db, actor)])
            db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,instructions,status,created,first_deferred) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (key, actor, message_id, mode, basis, root, bound, 'running', self.clock(), held['first_deferred'] if held is not None else None))
```

with

```python
            key, now = uid(), self.clock()
            bound = json.dumps([[l['layer_id'], l['revision']] for l in self._binding_layers(db, actor)])
            db.execute('INSERT INTO tickets(id,ship_id,message_id,mode,basis,root_id,chain,instructions,status,created,first_deferred) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (key, actor, message_id, mode, basis, root, json.dumps([link['id'] for link in chain]), bound, 'running',
                        now, held['first_deferred'] if held is not None else None))
            for link in chain:  # G16: one budget use per link, in the ticket's own transaction
                db.execute('INSERT INTO budget_uses(grant_id,ticket_id,created) VALUES(?,?,?)', (link['id'], key, now))
```

In `peer/superyak_peer/tickets.py`, replace

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

with

```python
    def _mode_for(self, db, ship, message):
        """Spec A section 4, rules 2 and 3 (step 3's basis grant, G15), bounded by fresh owner mentions: the owner's own
        fresh mention builds; so does a person's fresh mention under the oldest grant that covers it. An old or answered
        mention that would otherwise build reads, its basis saying why; everything else reads, basis none. Returns
        (mode, basis, root_id, chain), chain being the spent grant's rows, root first."""
        author = require(db.execute('SELECT id,kind FROM users WHERE id=?', (message['author_id'],)).fetchone())
        mentioned = db.execute('SELECT 1 FROM mentions WHERE message_id=? AND user_id=?', (message['id'], ship['id'])).fetchone()
        owner = ship['owner_id']
        if not (owner and mentioned and author['kind'] == 'person'):
            return 'read', 'none', None, []
        if author['id'] == owner:
            stale = self._mention_stale(db, ship['id'], message)
            return ('build', 'owner', owner, []) if stale is None else ('read', stale, None, [])
        chain = self._spendable_grant(db, ship, message)
        if chain is None:
            return 'read', 'none', None, []
        stale = self._mention_stale(db, ship['id'], message)  # G15: age and answered decide only the read's basis
        return ('build', 'grant', chain[0]['issuer_id'], chain) if stale is None else ('read', stale, None, [])

    def _spendable_grant(self, db, ship, message):
        """G15, every condition but the mention's age and answer (the caller asks _mention_stale): the chain, root first,
        of the oldest grant (by created, then id) that lets this message's author direct this ship in this room now, or
        None. issue_ticket has already refused (404) a ship that isn't in the room."""
        room_id, author_id, now = message['room_id'], message['author_id'], self.clock()
        if (':' in room_id or self._breakout(db, room_id) is not None
                or db.execute(f'SELECT 1 FROM rooms WHERE id=? AND id IN ({REPLACED_ROOMS})', (room_id,)).fetchone()
                or not _in_room(db, room_id, author_id)):
            return None  # R must be local, not a breakout and current, and the author still in it
        if self._ship_grant_builds(db, ship['id'], now) >= self._grant_policy(db)['builds_per_ship_per_day']:
            return None  # the per-ship cap, under every grant; owner builds never count
        covered = self._rooms_back(db, room_id)
        for grant in db.execute('SELECT * FROM grants WHERE grantee_id=? ORDER BY created, id', (author_id,)).fetchall():
            rooms = json.loads(grant['rooms'])
            if (ship['id'] not in json.loads(grant['targets']) or 'direct' not in json.loads(grant['actions'])
                    or (rooms != '*' and not any(key in rooms for key in covered)) or not _made_by(grant, message['created'])):
                continue
            chain = self._grant_chain(db, grant)[::-1]  # root first
            if (_in_room(db, room_id, chain[0]['issuer_id']) and all(link['confirm'] != 'each' for link in chain)
                    and self._grant_validity(db, grant)[0]):
                return chain
        return None

```

In `peer/pyproject.toml`, insert before

```toml
    "tests/test_grants.py",
```

this:

```toml
    "tests/test_grant_tickets.py",
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py tests/test_tickets.py tests/test_grants.py tests/test_deferrals.py tests/test_inbox.py tests/test_packaging.py`
Expected: `103 passed`. The owner and deferral tests are unchanged by the 4-tuple; 3b's `ship_builds_left` test now reads
the shared count.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grant_tickets.py` (and the file named), see the named test fail, restore:
- `ORDER BY created DESC, id`, or `ORDER BY created` (no id) in `_spendable_grant` → `test_the_oldest_grant_is_charged_and_the_next_when_it_has_no_budget`;
- drop `':' in room_id or` → test 11 (`far` builds);
- drop the `self._breakout(db, room_id) is not None` clause → test 11 (`side` builds);
- drop the `REPLACED_ROOMS` clause → `test_a_grant_naming_a_room_follows_it_forward_and_never_builds_in_a_replaced_room`;
- drop `or not _in_room(db, room_id, author_id)` → test 11 (`left` builds);
- drop the per-ship cap, or `>` for its `>=` → `test_the_21st_grant_build_of_a_ship_in_a_day_reads_across_grants_and_owner_builds_never_count`;
- `covered = [room_id]` (no walk back) → the room-walk test;
- `while key is not None:` in `_rooms_back` (no seen list) → the room-walk test never ends; run
  `cd peer && PYTHONDONTWRITEBYTECODE=1 timeout 60 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py`
  and see exit 124 after five tests pass;
- drop the targets clause, the `'direct'` clause or the rooms clause → test 11 (`none` and `other-ship`, `instruct`, or
  `other-room` build; the rooms one fails the room-walk test too);
- `grant['created'] < created` in `_made_by` → test 11 (`same` reads) and six more;
- `return grant['created'] <= created` alone in `_made_by` → `test_a_grantees_mention_with_an_unusable_created_reads_old_and_never_raises`
  (`TypeError` on the text);
- `True` for `_in_room(db, room_id, chain[0]['issuer_id'])` → test 11 (`star`, `removed` build);
- drop the `confirm` clause → test 11 (`each` builds);
- drop `and self._grant_validity(db, grant)[0]` → test 11 (`expired`, `revoked`, `spent`) and the budget, oldest and
  two-ship tests;
- `return ('build', 'grant', chain[0]['issuer_id'], chain)` without the stale branch → test 11 (`older`, `answered`
  build) and the unusable-created test; `('read', 'none', None, [])` in that branch → the same two;
- ask `_mention_stale` before `_spendable_grant` (return its basis whenever it isn't None) → `tests/test_tickets.py::test_a_non_owners_old_mention_is_read_with_basis_none`;
- drop the `budget_uses` insert → the G16, budget, oldest, room-walk and two-ship tests;
- `'[]'` for the chain's `json.dumps(...)` → the G16 and oldest tests;
- `created>=?`, or no `AND basis='grant'`, in `_ship_grant_builds` → the 21st-build test and
  `tests/test_grants.py::test_a_grant_shows_its_people_ships_rooms_budget_and_validity`;
- `if not (owner and mentioned):` (no person check) → test 11 (`by-ship` builds).

(The root's order in the chain and the charge to every link are only visible with two links; Task 3's two-link test
pins them.)

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/tickets.py peer/pyproject.toml peer/tests/test_grant_tickets.py
git commit -m "Grants 3c: a grantee's fresh mention builds under the oldest grant that covers it, and charges it (G15, G16)"
```

---

### Task 2: A re-sent grant ticket is re-checked, and refused with 409 (G18)

**Files:**
- Modify: `peer/superyak_peer/grants.py` (`_grant_validity`)
- Modify: `peer/superyak_peer/tickets.py` (the re-send path in `issue_ticket`, `_grant_lapsed` before `_answered`)
- Test: `peer/tests/test_grant_tickets.py`, `peer/tests/test_ship_agent.py`

**Interfaces:**
- Consumes: Task 1's chain and `_in_room`; `Problem(..., keep=True)` (`common.py`, committed by `db.py`'s
  `_transaction`); the watcher's 409 path and `_post_unlabelled` (`agent/superyak_agent/watch.py`, unchanged).
- Produces: `Grants._grant_validity(db, grant, budget=True)`; `Tickets._grant_lapsed(db, ticket, message) -> str | None`;
  a re-send of a lapsed grant ticket finishes it (`status='finished'`, `finished` now) and answers 409 `{error: reason}`.

- [ ] **Step 1: Write the failing tests**

In `peer/tests/test_grant_tickets.py`, replace

```python
import json
from superyak_peer import grants as G
from superyak_peer.common import uid
from test_grants import charge, make, revoke_by_hand
```

with

```python
import json
import pytest
from superyak_peer import grants as G
from superyak_peer.common import Problem, uid
from test_grants import charge, make, narrowed, revoke_by_hand
from test_presence import HEADERS, docked, ship_client
```

Append to `peer/tests/test_grant_tickets.py`, after two blank lines:

```python
def ask(watcher, message, decisions=False):
    return watcher.post('/api/ships/me/tickets', json={'message_id': message['id'], **({'decisions': ['defer', 'answered']} if decisions else {})})


def test_a_revoke_before_the_ticket_reads_and_after_it_the_resend_is_refused_and_finished(env):
    """Test 12: revoked between the mention and the ticket, the mention reads. Revoked between a ticket and its re-send,
    the re-send gets 409 with the reason, the ticket reads finished (saved with the refusal), a post carrying it gets
    409, and asking again is the finished ticket's 409."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, key = docked(store, patient['id'])
    watcher = ship_client(app, key)
    ops = room(store, patient, 'Ops', doctor, serenity)
    early = make(store, patient, doctor, [serenity], hours=48)
    first = mention(store, doctor, ops, serenity)
    assert clients[0].post(f'/api/grants/{early}/revoke', json={}).status_code == 200
    assert (ask(watcher, first).json()['mode'], ask(watcher, first).json()['basis']) == ('read', 'none')
    later = make(store, patient, doctor, [serenity], hours=48)
    second = mention(store, doctor, ops, serenity)
    issued = ask(watcher, second).json()
    assert (issued['mode'], issued['basis']) == ('build', 'grant')
    assert clients[0].post(f'/api/grants/{later}/revoke', json={'reason': 'Done for now'}).status_code == 200
    again = ask(watcher, second)
    assert (again.status_code, again.json()) == (409, {'error': f'Grant #{later[:4]} was revoked by Patient'})
    assert (ticket_row(store, serenity, second)['status'], ticket_row(store, serenity, second)['finished']) == ('finished', clock[0])
    labelled = watcher.post(f'/api/chats/{ops}/messages', json={'client_message_id': f'reply-{second["id"]}',
                                                                'body': "I couldn't answer this one.", 'ticket_id': issued['id']})
    assert (labelled.status_code, labelled.json()) == (409, {'error': 'This ticket cannot label a message here'})
    assert (ask(watcher, second).status_code, ask(watcher, second).json()) == (409, {'error': 'This message has already been answered'})


def test_a_resent_grant_ticket_is_the_same_ticket_and_charges_nothing_more(env):
    """Test 12, G18: a re-send re-checks neither the budget nor the per-ship cap, which the ticket already paid: one that
    spent its grant's last build, and the ship's 20th grant build of the day, come back as they were, charging nothing."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, key = docked(store, patient['id'])
    watcher = ship_client(app, key)
    ops = room(store, patient, 'Ops', doctor, serenity)
    earlier = [store.send_message(patient['id'], ops, f'old-{n}', 'earlier work')['id'] for n in range(19)]
    with store.transaction() as db:  # 19 grant builds of serenity today, written by hand
        db.executemany("INSERT INTO tickets(id,ship_id,message_id,mode,basis,status,created) VALUES(?,?,?,'build','grant','finished',?)",
                       [(uid(), serenity['id'], message_id, clock[0]) for message_id in earlier])
    grant = make(store, patient, doctor, [serenity], hours=48, budget=1)
    asked = mention(store, doctor, ops, serenity)
    issued = ask(watcher, asked).json()
    assert (issued['mode'], issued['basis']) == ('build', 'grant')
    clock[0] += 600
    again = ask(watcher, asked)
    assert again.status_code == 200 and (again.json()['id'], again.json()['mode']) == (issued['id'], 'build')
    assert ask(watcher, asked, decisions=True).json()['decision'] == 'run'
    assert len(uses(store, grant)) == 1


def test_a_resend_after_the_room_gains_a_member_keeps_its_ticket(env):
    """Plan Review Focus 5: the owner adds a member while a granted build runs, so the room is replaced. The re-send checks
    only that the issuer is still in the message's room, which he is; whether the room is current was decided at issue."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity = ships(store, patient['id'], 'serenity')['serenity']
    plans = room(store, patient, 'Plans', doctor, serenity)
    make(store, patient, doctor, [serenity], rooms=[plans], hours=48)
    asked = mention(store, doctor, plans, serenity)
    issued = store.issue_ticket(serenity['id'], asked['id'])
    store.add_participants(patient['id'], plans, [family['id']])
    assert store.issue_ticket(serenity['id'], asked['id'])['id'] == issued['id']


def refused(store, ship, message):
    with pytest.raises(Problem) as caught:
        store.issue_ticket(ship['id'], message['id'])
    return caught.value.status, caught.value.message, ticket_row(store, ship, message)['status']


def test_a_resend_is_refused_once_the_grant_expires_ownership_moves_the_issuer_leaves_or_the_policy_narrows(env, monkeypatch):
    """G18's other re-checks: G9's expiry, ownership and policy, and the root issuer's membership of the room. A grant
    row that is gone (only by hand) refuses too. Each refusal finishes the ticket."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    s = ships(store, patient['id'], 'expiring', 'moved', 'left', 'gone', 'narrowed')
    ops = room(store, patient, 'Ops', doctor, *[s[name] for name in ('expiring', 'moved', 'gone', 'narrowed')])
    theirs = room(store, doctor, 'Theirs', patient, s['left'])  # doctor's room, so doctor can remove patient
    expiring = make(store, patient, doctor, [s['expiring']], hours=1)
    grants = {name: make(store, patient, doctor, [s[name]], hours=48) for name in ('moved', 'gone', 'narrowed')}
    grants['left'] = make(store, patient, doctor, [s['left']], rooms=[theirs], hours=48)
    asked = {name: mention(store, doctor, theirs if name == 'left' else ops, s[name]) for name in s}
    clock[0] += 3599
    for name in s:
        assert store.issue_ticket(s[name]['id'], asked[name]['id'])['mode'] == 'build', name
    clock[0] += 1  # the expiring grant's expiry instant
    assert refused(store, s['expiring'], asked['expiring']) == (409, f'Grant #{expiring[:4]} expired 1970-01-12 14:46 UTC', 'finished')
    with store.transaction() as db:  # by hand: ownership never changes today
        db.execute('UPDATE users SET owner_id=? WHERE id=?', (family['id'], s['moved']['id']))
        db.execute('DELETE FROM budget_uses WHERE grant_id=?', (grants['gone'],))
        db.execute('DELETE FROM grants WHERE id=?', (grants['gone'],))
    assert refused(store, s['moved'], asked['moved']) == (409, 'Patient no longer owns Moved', 'finished')
    assert refused(store, s['gone'], asked['gone']) == (409, 'The grant behind this run is gone', 'finished')
    store.remove_participant(doctor['id'], theirs, patient['id'])
    assert refused(store, s['left'], asked['left']) == (409, 'Patient is no longer in this room', 'finished')
    narrowed(store, monkeypatch, max_expiry_hours=24)
    assert refused(store, s['narrowed'], asked['narrowed']) == (
        409, f'Grant #{grants["narrowed"][:4]} lasts longer than the station now allows', 'finished')


def test_a_grant_build_is_never_deferred_but_another_persons_mention_is(env):
    """Test 18: only read decisions defer (ship status S10), so a grantee's build runs while the ship's session holds a
    writable watch; another person's mention of the same ship still defers to that session."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, key = docked(store, patient['id'])
    session, watcher = ship_client(app, key, **HEADERS), ship_client(app, key)
    ops = room(store, patient, 'Ops', doctor, organizer, serenity)
    make(store, patient, doctor, [serenity], hours=48)
    assert session.post('/api/ships/me/watch', json={'minutes': 20, 'writable': True}).status_code == 200
    granted, other = mention(store, doctor, ops, serenity), mention(store, organizer, ops, serenity)
    decided = ask(watcher, granted, decisions=True).json()
    assert (decided['decision'], decided['mode'], decided['basis']) == ('run', 'build', 'grant')
    assert ask(watcher, other, decisions=True).json()['decision'] == 'defer'
```

In `peer/tests/test_ship_agent.py`, insert before

```python
def test_the_hook_reads_the_real_stations_instructions_and_hears_a_withdrawal(env, tmp_path):
```

this:

```python
def granted_room(env, tmp_path):
    """Patient's ship serenity in Ops with doctor, who holds a grant over it (merge 3c): (app, clients, users, clock,
    ship, key, room, grant, config)."""
    app, clients, users, clock = env
    ship, key = docked_ship(app.state.store, users[0]['id'])
    room = clients[0].post('/api/chats', json={'title': 'Ops', 'member_ids': [ship['id'], users[1]['id']]}).json()['id']
    made = clients[0].post('/api/grants', json={'grantee': users[1]['id'], 'targets': [ship['id']], 'rooms': [room],
                                                'hours': 24, 'budget': 5})
    assert made.status_code == 201, made.text
    config = {'station': 'http://testserver', 'origin': None, 'ship': 'serenity', 'ship_id': ship['id'], 'ship_name': 'Serenity',
              'owner_id': users[0]['id'], 'key': key, 'workspace': str(tmp_path), 'machine': 'test-host'}
    return app, clients, users, clock, ship, key, room, made.json(), config


def test_a_revoke_between_tries_stops_the_retry_and_the_fallback_goes_out_unlabelled(env, tmp_path):
    """G18, test 12, through the real station: a grantee's mention gets a builder ticket and its run fails; the owner
    revokes the grant; the watcher's retry gets 409, so it runs nothing and posts the fallback note, which the finished
    ticket can't label, so it goes out unlabelled, as a reply to the mention. Nothing asks again."""
    from superyak_agent.station import StationClient
    from superyak_agent.watch import FALLBACK, Watcher
    app, clients, users, clock, ship, key, room, grant, config = granted_room(env, tmp_path)
    asked = clients[1].post(f'/api/chats/{room}/messages', json={'client_message_id': 'g', 'body': '@serenity add a NOTES file'}).json()
    calls = []

    class Failing:
        def run(self, mode, prompt, message_id, instructions=''):
            calls.append(mode)
            raise RuntimeError('model unavailable')
    watcher = Watcher(StationClient('http://testserver', key, transport=transport_for(app)), config, tmp_path / 'state.json', Failing())
    assert watcher.cycle() == 0 and calls == ['build']
    assert clients[0].post(f'/api/grants/{grant["id"]}/revoke', json={}).status_code == 200
    assert watcher.cycle() == 1 and calls == ['build']
    reply = clients[0].get(f'/api/chats/{room}').json()['messages'][-1]
    assert (reply['body'], reply['source'], reply['reply_to']) == (FALLBACK, {'kind': 'post'}, asked['id'])
    assert watcher.cycle() == 0 and calls == ['build']


```

`test_a_resent_grant_ticket_is_the_same_ticket_and_charges_nothing_more`,
`test_a_resend_after_the_room_gains_a_member_keeps_its_ticket` and
`test_a_grant_build_is_never_deferred_but_another_persons_mention_is` pass before this task: nothing re-checks a re-send
yet, and only read decisions defer. They guard the re-check's limits and G18's first sentence; Step 5 shows each bites.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py tests/test_ship_agent.py`
Expected: `3 failed, 33 passed`: the test 12 refusal (`assert (200, {'id': ..., 'mode': 'build', ...}) == (409, {'error': 'Grant #... was revoked by Patient'})`),
the re-check table (`Failed: DID NOT RAISE Problem`, at the expiry), and the real watcher's
`test_a_revoke_between_tries_stops_the_retry_and_the_fallback_goes_out_unlabelled` (`assert (0 == 1)` at the second
cycle: the retry got the running ticket and ran again).

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/grants.py`, replace

```python
    def _grant_validity(self, db, grant):
        """G9: (True, None), or (False, the reason of the first check that fails). Each link, from the grant up to its
        root, is checked in the spec's order: 1 revoked, 2 expired, 3 the policy in force now (lifetime, chain length,
        grantee set), 4 budget, 5 the root's issuer still owns every target. Names are the station's own, through
        safe_line."""
```

with

```python
    def _grant_validity(self, db, grant, budget=True):
        """G9: (True, None), or (False, the reason of the first check that fails). Each link, from the grant up to its
        root, is checked in the spec's order: 1 revoked, 2 expired, 3 the policy in force now (lifetime, chain length,
        grantee set), 4 budget, 5 the root's issuer still owns every target. Names are the station's own, through
        safe_line. budget=False skips check 4, for a ticket that has already paid (G18)."""
```

In `peer/superyak_peer/grants.py`, replace

```python
            if self._budget_used(db, link['id'], now) >= link['budget']:
```

with

```python
            if budget and self._budget_used(db, link['id'], now) >= link['budget']:
```

In `peer/superyak_peer/tickets.py`, replace

```python
            if existing:
                if self._ticket_running(existing):
                    return self._decided(db, existing, station, decisions)
```

with

```python
            if existing:
                if self._ticket_running(existing):
                    lapsed = self._grant_lapsed(db, existing, message) if existing['basis'] == 'grant' else None
                    if lapsed is not None:  # G18: finished and saved with the refusal, so it can never label a post
                        db.execute("UPDATE tickets SET status='finished',finished=? WHERE id=?", (self.clock(), existing['id']))
                        raise Problem(409, lapsed, keep=True)
                    return self._decided(db, existing, station, decisions)
```

In `peer/superyak_peer/tickets.py`, insert before

```python
    def _answered(self, db, ship_id, message_id):
```

this:

```python
    def _grant_lapsed(self, db, ticket, message):
        """G18: a running grant ticket asked for again. None while its grant still holds, else why not: G9's revocation,
        expiry, policy and ownership checks, then the root issuer's membership of the message's room. Not the budget or
        the per-ship cap, which this ticket already paid."""
        links = [db.execute('SELECT * FROM grants WHERE id=?', (key,)).fetchone() for key in json.loads(ticket['chain'])]
        if not links or any(link is None for link in links):
            return 'The grant behind this run is gone'
        valid, reason = self._grant_validity(db, links[-1], budget=False)
        if not valid:
            return reason
        if not _in_room(db, message['room_id'], links[0]['issuer_id']):
            issuer = db.execute('SELECT name FROM users WHERE id=?', (links[0]['issuer_id'],)).fetchone()
            return f'{safe_line(issuer["name"])} is no longer in this room'
        return None

```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py tests/test_ship_agent.py tests/test_tickets.py tests/test_deferrals.py`
Expected: `85 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_grant_tickets.py tests/test_ship_agent.py` (or the file named), see the named test
fail, restore:
- `raise Problem(409, lapsed)` (no `keep=True`) → test 12's refusal (the ticket still reads running), the re-check table,
  and the real watcher's test (the fallback note is labelled with the build's ticket);
- `self._grant_validity(db, links[-1])` (the budget re-checked) → `test_a_resent_grant_ticket_is_the_same_ticket_and_charges_nothing_more`;
- `lapsed = (None if self._spendable_grant(db, ship, message) else 'lapsed') if existing['basis'] == 'grant' else None`
  (all of G15 again) → the same test, `test_a_resend_after_the_room_gains_a_member_keeps_its_ticket`, test 12 and the
  re-check table;
- `if False:` for the membership re-check → the re-check table (`left`);
- `lapsed = None` (no re-check) → test 12, the re-check table and the real watcher's test;
- `if existing['mode'] == 'build'` for `if existing['basis'] == 'grant'` → `tests/test_tickets.py`'s three re-send tests
  (an owner ticket has no chain, so it reads "gone");
- `UPDATE tickets SET status='finished' WHERE id=?` without `finished` → test 12 (`finished` is None);
- `if decisions and self._writable_on_watch(db, actor):` (no `mode == 'read'`) → `test_a_grant_build_is_never_deferred_but_another_persons_mention_is`;
- drop the two "gone" lines in `_grant_lapsed` → the re-check table (`TypeError` on the missing row).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/grants.py peer/superyak_peer/tickets.py peer/tests/test_grant_tickets.py peer/tests/test_ship_agent.py
git commit -m "Grants 3c: a re-sent grant ticket is checked again, and finished with 409 when the grant lapsed (G18)"
```

---

### Task 3: The footer, the source's `via_name`, and both labels (G17)

**Files:**
- Modify: `peer/superyak_peer/tickets.py` (an import, `_via_name` and `_footer` before `_ticket_json`, `_sources`)
- Modify: `agent/superyak_agent/station.py` (`source_label`)
- Modify: `peer/superyak_peer/static/app.js` (`sourceLabel`)
- Test: `peer/tests/test_grant_tickets.py`, `peer/tests/test_ship_agent.py`, `peer/tests/test_browser.py`,
  `agent/tests/test_station.py`

**Interfaces:**
- Consumes: `short_id` (3b, `grants.py`); `safe_line`; Task 1's chain; `label` (agent).
- Produces: `Tickets._via_name(db, chain_ids) -> str | None`, `Tickets._footer(db, row, root_name) -> str`; a grant run's
  source carries `via_name`; `source_label` and the web app's `sourceLabel` give "builder run for <root>, via <grantee>".

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_grant_tickets.py`, after two blank lines:

```python
def test_a_grant_builds_footer_and_source_name_the_root_the_grantee_and_the_grant(env):
    """Test 17, G17: the footer is `Builder for <root>, via <grantee> · grant #a1b2`, and a reply posted with the ticket
    has source {kind, mode, basis, root_name, via_name, answering}. A chain of two links, made by hand as step 5 will
    make them, reads `grants #root > #child`."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, key = docked(store, patient['id'])
    watcher = ship_client(app, key)
    ops = room(store, patient, 'Ops', doctor, family, serenity)
    grant = make(store, patient, doctor, [serenity], hours=48)
    asked = mention(store, doctor, ops, serenity)
    issued = ask(watcher, asked).json()
    assert (issued['footer'], issued['root_name'], issued['chain']) == (f'Builder for Patient, via Doctor · grant #{grant[:4]}', 'Patient', [grant])
    posted = watcher.post(f'/api/chats/{ops}/messages', json={'client_message_id': f'reply-{asked["id"]}', 'body': 'Added notes',
                                                              'ticket_id': issued['id']})
    assert posted.status_code == 201, posted.text
    shown = {m['body']: m['source'] for m in clients[0].get(f'/api/chats/{ops}').json()['messages']}
    assert shown['Added notes'] == {'kind': 'run', 'mode': 'build', 'basis': 'grant', 'root_name': 'Patient',
                                    'via_name': 'Doctor', 'answering': asked['id']}
    child = make(store, doctor, family, [serenity], hours=48)
    later = mention(store, family, ops, serenity)
    with store.transaction() as db:  # by hand: step 5's delegation makes such a child; step 3 never spends one
        db.execute('UPDATE grants SET parent_id=? WHERE id=?', (grant, child))
    relayed = store.issue_ticket(serenity['id'], later['id'])
    assert relayed['footer'] == f'Builder for Patient, via Family · grants #{grant[:4]} > #{child[:4]}'
    assert (relayed['root_id'], relayed['chain'], len(uses(store, grant)), len(uses(store, child))) == (
        patient['id'], [grant, child], 2, 1)  # G16: one budget use per link


def test_a_grantees_name_never_mentions_anyone_in_the_footer_or_the_label(env):
    """Plan Review Focus 1: the footer is posted in the room under the build's reply, so a grantee named "Jenn\n@rio-grande"
    must not mention rio-grande (which would start its run): the names are the station's own, through safe_line."""
    app, clients, users, clock = env
    store = app.state.store
    patient, doctor, organizer, family = users
    serenity, key = docked(store, patient['id'])
    watcher = ship_client(app, key)
    ops = room(store, patient, 'Ops', doctor, serenity)
    store.rename_user(doctor['id'], 'Jenn\n@rio-grande')
    grant = make(store, patient, doctor, [serenity], hours=48)
    asked = mention(store, doctor, ops, serenity)
    issued = ask(watcher, asked).json()
    assert issued['footer'] == f'Builder for Patient, via Jenn (at)rio-grande · grant #{grant[:4]}'
    watcher.post(f'/api/chats/{ops}/messages', json={'client_message_id': 'r', 'body': 'Added notes', 'ticket_id': issued['id']})
    source = next(m['source'] for m in clients[0].get(f'/api/chats/{ops}').json()['messages'] if m['body'] == 'Added notes')
    assert source['via_name'] == 'Jenn (at)rio-grande'
```

In `peer/tests/test_ship_agent.py`, insert before

```python
def test_the_hook_reads_the_real_stations_instructions_and_hears_a_withdrawal(env, tmp_path):
```

this:

```python
def test_a_grantees_mention_builds_through_the_real_station_and_its_label_says_via_whom(env, tmp_path):
    """G17, test 17, through the real station: the watcher runs the grantee's mention as a builder, posts the ticket's
    footer, and the agent's source_label reads the reply as "builder run for Patient, via Doctor"."""
    from superyak_agent.runs import RunResult
    from superyak_agent.station import StationClient, source_label
    from superyak_agent.watch import Watcher
    app, clients, users, clock, ship, key, room, grant, config = granted_room(env, tmp_path)
    clients[1].post(f'/api/chats/{room}/messages', json={'client_message_id': 'g', 'body': '@serenity add a NOTES file'})
    calls = []

    class Runner:
        def run(self, mode, prompt, message_id, instructions=''):
            calls.append(mode)
            return RunResult('Added notes')
    watcher = Watcher(StationClient('http://testserver', key, transport=transport_for(app)), config, tmp_path / 'state.json', Runner())
    assert watcher.cycle() == 1 and calls == ['build']
    reply = clients[0].get(f'/api/chats/{room}').json()['messages'][-1]
    assert reply['body'] == f'Added notes\n\nBuilder for Patient, via Doctor · grant {grant["short"]}'
    assert source_label(reply) == 'builder run for Patient, via Doctor'


```

In `agent/tests/test_station.py`, insert before

```python
def test_labels_never_raise_on_a_source_kind_or_author_kind_they_do_not_know():
```

this:

```python
def test_a_grant_runs_label_says_via_whom():
    """Grants step 3, G17, test 17: source_label appends ", via <via_name>" when the source has one, so run prompts and
    hooks read a grantee's build as such. A via_name that isn't text adds nothing, and one is collapsed to one line."""
    grant = {'kind': 'run', 'mode': 'build', 'basis': 'grant', 'root_name': 'Andy', 'via_name': 'Jenn', 'answering': 'm1'}
    assert source_label({'source': grant}) == 'builder run for Andy, via Jenn'
    assert source_label({'source': {**grant, 'via_name': 'Jenn\n`x`'}}) == 'builder run for Andy, via Jenn x'
    for odd in (None, '', ['Jenn'], 5):
        assert source_label({'source': {**grant, 'via_name': odd}}) == 'builder run for Andy', odd
    assert source_label({'source': {key: value for key, value in grant.items() if key != 'via_name'}}) == 'builder run for Andy'
    assert source_label({'source': {**grant, 'root_name': None}}) == 'builder run'


```

In `peer/tests/test_browser.py`, insert before

```python
def test_a_room_labels_the_station_notice_by_id_never_by_name(browser_peer):
```

this:

```python
def test_a_grantees_build_reply_is_labelled_with_the_grantee(browser_peer):
    """G17, test 17: a reply from a grant's builder run shows "builder run for Alex Patient, via <grantee>", and a grantee
    name written as HTML shows as text."""
    base, store, users = browser_peer["base_url"], browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    room = store.create_room(users["patient"]["id"], "Ops", [ship["id"], users["doctor"]["id"]])
    store.rename_user(users["doctor"]["id"], "<b>Dr. Morgan</b>")
    store.make_grant(users["patient"]["id"], users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    asked = store.send_message(users["doctor"]["id"], room["id"], "a", "@serenity add notes")
    ticket = store.issue_ticket(ship["id"], asked["id"])
    store.send_message(ship["id"], room["id"], f"reply-{asked['id']}", "Added notes", ticket["id"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.goto(f"{base}/#chats/{room['id']}")
            page.reload()
            label = page.locator(".message", has_text="Added notes").locator(".message-source")
            expect(label).to_have_text("builder run for Alex Patient, via <b>Dr. Morgan</b>")
            assert page.locator(".message-source b").count() == 0


```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py tests/test_ship_agent.py`
Expected: `3 failed, 36 passed`: the footer test (`At index 0 diff: '' != 'Builder for Patient, via Doctor · grant #...'`),
the safe-name test (`assert '' == 'Builder for ...'`) and the real watcher's (`assert 'Added notes' == 'Added notes\n\nBuilder for Patient, via Doctor · grant #...'`).

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_browser.py -k grantees_build`
Expected: `1 failed`: `Locator expected to have text 'builder run for Alex Patient, via <b>Dr. Morgan</b>'`,
`Actual value: builder run for Alex Patient`.

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_station.py`
Expected: `1 failed, 19 passed`: `assert 'builder run for Andy' == 'builder run for Andy, via Jenn'`.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/tickets.py`, replace

```python
from .instructions import render_blocks
```

with

```python
from .grants import short_id
from .instructions import render_blocks
```

In `peer/superyak_peer/tickets.py`, replace

```python
    def _ticket_json(self, db, row, station=''):
        root = db.execute('SELECT name FROM users WHERE id=?', (row['root_id'],)).fetchone() if row['root_id'] else None
        root_name = safe_line(root['name']) if root else None
        footer = f'Builder for {root_name} (owner)' if row['mode'] == 'build' and row['basis'] == 'owner' and root_name else ''
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
```

with

```python
    def _via_name(self, db, chain):
        """G17: the person a grant run builds for, beside the root: the grantee of the chain's last link (in step 3 the
        mention's author), on one safe line, or None."""
        row = db.execute('SELECT users.name FROM grants JOIN users ON users.id=grants.grantee_id WHERE grants.id=?',
                         (chain[-1],)).fetchone() if chain else None
        return safe_line(row['name']) if row else None

    def _footer(self, db, row, root_name):
        """Spec A's footers, written without @: `Builder for Andy (owner)`, and for a grant (G17) `Builder for Andy, via
        Jenn · grant #a1b2`, or `grants #a1b2 > #c3d4` for a chain of several links (step 5)."""
        if row['mode'] != 'build' or not root_name:
            return ''
        if row['basis'] == 'owner':
            return f'Builder for {root_name} (owner)'
        chain = json.loads(row['chain'])
        via = self._via_name(db, chain)
        if row['basis'] != 'grant' or not via:
            return ''
        return f'Builder for {root_name}, via {via} · {"grant" if len(chain) == 1 else "grants"} {" > ".join(map(short_id, chain))}'

    def _ticket_json(self, db, row, station=''):
        root = db.execute('SELECT name FROM users WHERE id=?', (row['root_id'],)).fetchone() if row['root_id'] else None
        root_name = safe_line(root['name']) if root else None
        footer = self._footer(db, row, root_name)
        return {'id': row['id'], 'ship_id': row['ship_id'], 'message_id': row['message_id'], 'mode': row['mode'],
                'basis': row['basis'], 'root_id': row['root_id'], 'root_name': root_name, 'chain': json.loads(row['chain']),
```

In `peer/superyak_peer/tickets.py`, replace

```python
        runs = {r['message_id']: {'kind': 'run', 'mode': r['mode'], 'basis': r['basis'],
                                  'root_name': safe_line(r['root_name']) if r['root_name'] else None, 'answering': r['answering']}
                for r in db.execute('SELECT message_sources.message_id, tickets.mode, tickets.basis, tickets.message_id AS answering, '
                                    'users.name AS root_name FROM message_sources JOIN tickets ON tickets.id=message_sources.ticket_id '
                                    'JOIN messages ON messages.id=message_sources.message_id LEFT JOIN users ON users.id=tickets.root_id '
                                    'WHERE messages.room_id=?', (room_id,))}
```

with

```python
        runs = {r['message_id']: {'kind': 'run', 'mode': r['mode'], 'basis': r['basis'],
                                  'root_name': safe_line(r['root_name']) if r['root_name'] else None, 'answering': r['answering'],
                                  # G17: a grant run names its grantee too; every other source is exactly as before
                                  **({'via_name': self._via_name(db, json.loads(r['chain']))} if r['basis'] == 'grant' else {})}
                for r in db.execute('SELECT message_sources.message_id, tickets.mode, tickets.basis, tickets.chain, '
                                    'tickets.message_id AS answering, users.name AS root_name FROM message_sources '
                                    'JOIN tickets ON tickets.id=message_sources.ticket_id JOIN messages ON messages.id=message_sources.message_id '
                                    'LEFT JOIN users ON users.id=tickets.root_id WHERE messages.room_id=?', (room_id,))}
```

In `agent/superyak_agent/station.py`, replace

```python
            return f'builder run for {label(source["root_name"])}' if source.get('root_name') else 'builder run'
```

with

```python
            if not source.get('root_name'):
                return 'builder run'
            via = source.get('via_name')  # grants step 3, G17: a grantee's build names the grantee too
            return f'builder run for {label(source["root_name"])}' + (f', via {label(via)}' if isinstance(via, str) and via else '')
```

In `peer/superyak_peer/static/app.js`, replace

```javascript
  if (source.kind === "run") return source.mode === "build" ? (source.root_name ? `builder run for ${source.root_name}` : "builder run") : "read-only run";
```

with

```javascript
  // A grant's builder run names its grantee too (grants step 3, G17). Escaped where it is shown.
  if (source.kind === "run") return source.mode === "build" ? (source.root_name ? `builder run for ${source.root_name}${source.via_name ? `, via ${source.via_name}` : ""}` : "builder run") : "read-only run";
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_grant_tickets.py tests/test_ship_agent.py tests/test_tickets.py tests/test_inbox.py`
Expected: `69 passed` (test_tickets' whole-dict sources for owner and read runs are unchanged: R13).

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_browser.py -k "grantees_build or ship_messages_came or station_notice_by_id"`
Expected: `3 passed`.

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_station.py tests/test_watch.py tests/test_hook_inbox.py`
Expected: `77 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run the file named, see the named test fail, restore:
- `return row['name'] if row else None` in `_via_name` (no `safe_line`) → `test_a_grantees_name_never_mentions_anyone_in_the_footer_or_the_label`;
- `grants` always, or `grant` always, for the plural choice in `_footer` → the footer test (and the safe-name test for
  `grants`);
- `map(short_id, chain[::-1])` → the footer test (the two-link order);
- `grants.issuer_id` for `grants.grantee_id` in `_via_name` → the footer and safe-name tests;
- `'via_name': ...` on every run's source (no basis condition) → `tests/test_tickets.py::test_a_reply_with_its_ticket_is_labelled_as_that_run`
  and `::test_an_owner_mention_builds_for_exactly_a_day_then_reads_old`;
- no `via_name` in `_sources` → the footer and safe-name tests and the real watcher's test;
- Task 1's code, seen only with two links: `for link in chain[-1:]:` for the budget uses, `chain[-1]['issuer_id']` for the
  root, or `self._grant_chain(db, grant)` without `[::-1]` → the footer test;
- agent: `if via else ''` (no `isinstance`), no `via` part, or `{via}` for `{label(via)}` → `agent/tests/test_station.py::test_a_grant_runs_label_says_via_whom`;
- web: drop `${source.via_name ? ... : ""}` → `test_a_grantees_build_reply_is_labelled_with_the_grantee`; and the
  existing `escapeHtml(sourceLabel(message))` in `messageMarkup` written without `escapeHtml` → the same test (a `<b>`
  element appears).

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/tickets.py agent/superyak_agent/station.py peer/superyak_peer/static/app.js peer/tests/test_grant_tickets.py peer/tests/test_ship_agent.py peer/tests/test_browser.py agent/tests/test_station.py
git commit -m "Grants 3c: a grant build's footer and label say whose grant it spent (G17)"
```

---

### Task 4: The read-only prompt points to a grant, and runs.py's docstring (G19)

**Files:**
- Modify: `agent/superyak_agent/watch.py` (`build_prompt`'s read-mode sentence)
- Modify: `agent/superyak_agent/runs.py` (its docstring)
- Test: `agent/tests/test_watch.py`

**Interfaces:**
- Consumes: `LIMITED_SENTENCES` and `build_prompt(..., limited=None)` (fresh owner mentions).
- Produces: the read-mode prompt's last sentence: the `limited` reason when set, else "If the request needs changes, say
  what you would do and that <author> can ask the ship's owner for a grant, or check the Grants page."

- [ ] **Step 1: Write the failing tests**

In `agent/tests/test_watch.py`, replace

```python
             "do and that Andy can ask the ship's owner.\n")
```

with

```python
             "do and that Andy can ask the ship's owner for a grant, or check the Grants page.\n")
```

In `agent/tests/test_watch.py`, insert before

```python
def test_the_watcher_passes_an_old_basis_to_the_prompt(station, ship_config, tmp_path):
```

this:

```python
def test_a_grantees_read_prompt_points_to_a_grant_and_a_limited_one_says_only_why(station, ship_config):
    """Grants step 3, G19, beside fresh owner mentions R8: a read-only run tells a person who isn't the owner that they
    can ask the ship's owner for a grant, or check the Grants page. When the ticket's basis is old or answered, its
    reason line replaces that sentence: a grantee whose mention is a day old holds a grant already."""
    from superyak_agent.watch import LIMITED_SENTENCES
    fake, andy, jenn, serenity = station
    room = fake.room('Ops', andy, jenn, serenity)
    asked = fake.say(room, jenn, '@serenity fix it')
    view = fake.view(fake.rooms[room])
    mention = {'message_id': asked['id'], 'room_id': room, 'author': jenn, 'body': asked['body']}
    assert build_prompt(view, mention, 'serenity', 'read').endswith(
        "If the request needs changes, say what you would do and that Jenn can ask the ship's owner for a grant, or "
        "check the Grants page.\n")
    for limited in ('old', 'answered'):
        prompt = build_prompt(view, mention, 'serenity', 'read', limited=limited)
        assert prompt.endswith(f'cannot run commands or change files. {LIMITED_SENTENCES[limited]}\n'), limited
        assert 'Grants page' not in prompt and 'for a grant' not in prompt, limited


```

The changed `READ_TAIL` is the one other tests compare whole read prompts with, so they fail too until the prompt
changes.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_watch.py`
Expected: `7 failed, 35 passed`: `test_a_limited_read_prompt_says_why_and_nothing_else_changes`, the new test, and the
five cases of `test_the_watcher_gives_the_plain_read_prompt_for_any_other_basis`, each on the old last sentence.

- [ ] **Step 3: Write the implementation**

In `agent/superyak_agent/watch.py`, replace

```python
        why = LIMITED_SENTENCES.get(limited) if isinstance(limited, str) else None
        task = ('You are in read-only mode: you can read and search the repository and use the aDNA tools, but '
                'you cannot run commands or change files. '
                + (why or f'If the request needs changes, say what you would do and that '
                           f'{label(author["name"])} can ask the ship\'s owner.'))
```

with

```python
        why = LIMITED_SENTENCES.get(limited) if isinstance(limited, str) else None  # the reason line comes first (G19)
        task = ('You are in read-only mode: you can read and search the repository and use the aDNA tools, but '
                'you cannot run commands or change files. '
                + (why or f'If the request needs changes, say what you would do and that '
                           f'{label(author["name"])} can ask the ship\'s owner for a grant, or check the Grants page.'))
```

In `agent/superyak_agent/runs.py`, replace

```python
"""One Claude run per mention: read-only for everyone, builder for the ship's owner."""
```

with

```python
"""One Claude run per mention: read-only for everyone, builder for the ship's owner or a person the owner granted."""
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider tests/test_watch.py tests/test_watch_deferral.py tests/test_runs.py`
Expected: `92 passed`.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run `tests/test_watch.py`, see the named test fail, restore:
- `+ ((why + ' ') if why else '') + (f'If the request ...` (both sentences when limited) → the new test,
  `test_a_limited_read_prompt_says_why_and_nothing_else_changes` and `test_the_watcher_passes_an_old_basis_to_the_prompt`;
- the old sentence (`can ask the ship\'s owner.'`) → the seven tests of Step 2.

The docstring has no test; it is read in review.

- [ ] **Step 6: Commit**

```bash
git add agent/superyak_agent/watch.py agent/superyak_agent/runs.py agent/tests/test_watch.py
git commit -m "Grants 3c: a read-only run points to a grant or the Grants page; runs.py names granted builders (G19)"
```

---

### Task 5: The Grants page (G20-G22)

**Files:**
- Modify: `peer/superyak_peer/static/app.js` (identity reset, route, sidebar link, the page's functions before the
  board's write helper, `loadRoute`, `render`'s view and title maps, the submit, click, input and change handlers)
- Modify: `peer/superyak_peer/static/app.css` (four rules after `.carry-board ul`)
- Test: `peer/tests/test_browser.py`

**Interfaces:**
- Consumes: R3's routes; `state.ships` (`/api/ships`, with `owner_id`), `state.home.chats` (`list_rooms`: `member_ids`,
  `linked_room_id`, `breakout`, `origin`); `escapeHtml`, `formatDate`, `setFlash`, `render`, `loadData`, `showLogin`,
  `identityKey`, `pathPart` (app.js).
- Produces: route `#grants` with the sidebar link "Grants"; `loadGrants`, `grantRoomsWith`, `grantRoomChoices`,
  `grantForm`, `readGrantForm`, `grantItem`, `grantsView`, `grantWrite`, `makeGrant`; state `grants`, `grantPeople`,
  `grantForm`, `grantAsk`, `grantSaving`.

- [ ] **Step 1: Write the failing tests**

Append to `peer/tests/test_browser.py`, after two blank lines:

```python
def grant_station(browser_peer):
    """Grants step 3's page (G20-G22): patient owns serenity, in a room with doctor whose title is HTML, and in a room
    without doctor; doctor's display name is HTML too. (store, users, ship, room, lone)."""
    store, users = browser_peer["app"].state.store, browser_peer["users"]
    started = store.start_docking("serenity", "andy-mac")
    ship = store.confirm_docking(users["patient"]["id"], started["id"], started["code"])
    store.rename_user(users["doctor"]["id"], "<img src=x onerror=alert(1)>")
    room = store.create_room(users["patient"]["id"], "<b>City</b> of AI", [users["doctor"]["id"], ship["id"]])
    lone = store.create_room(users["patient"]["id"], "Just me", [ship["id"]])
    return store, users, ship, room, lone


def fill_grant(page, person, *rooms):
    page.get_by_label("Person").select_option(label=person)
    page.get_by_label("Serenity").check()
    for title in rooms:
        page.get_by_label(title).check()


def test_a_grant_is_made_on_the_page_held_by_its_grantee_and_revoked_after_the_ask(browser_peer):
    """Test 20, G20-G22: the patient makes a grant, choosing from a person list without ships or himself, and sees it
    under "Given by you"; the doctor sees it under "Held by you", with no Revoke; Revoke asks in place, revokes nothing
    before the confirm, and then revokes with its reason. A grantee name and a room title written as HTML show as text."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor = users["patient"]["id"], users["doctor"]["id"]
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            expect(page.get_by_role("heading", name="Grants", level=1)).to_be_visible()
            expect(page.get_by_text("Their mentions start builder runs of your ships on your machine. A run can read your "
                                    "repository and uses your model time, and its reply is posted in the room.")).to_be_visible()
            assert page.get_by_label("Person").locator("option").all_inner_texts() == [
                "Choose a person", "<img src=x onerror=alert(1)>", "Sam Family", "Taylor Organizer"]
            expect(page.get_by_label("How long")).to_have_value("168")
            expect(page.get_by_label("Builds a day")).to_have_value("5")
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI")
            expect(page.get_by_label("Just me")).to_have_count(0)  # it doesn't hold the doctor
            expect(page.get_by_label("These rooms")).to_be_checked()
            page.get_by_role("button", name="Make grant").click()
            item = page.locator(".grants-given .grant-item")
            expect(item).to_have_count(1)
            made = store.list_grants(patient)[0]
            expect(page.locator(".notice", has_text=f"Grant {made['short']} made.")).to_be_visible()
            expect(item).to_contain_text(f"{made['short']} To <img src=x onerror=alert(1)>")
            expect(item).to_contain_text("Serenity, 20 grant builds left for the ship")
            expect(item).to_contain_text("Rooms: <b>City</b> of AI")
            expect(item).to_contain_text("5 of 5 builds left in the last 24 hours")
            expect(item.locator(".badge")).to_have_text("Valid")
            assert page.locator("#main-content img, #main-content b").count() == 0
            assert (made["grantee"]["id"], [r["id"] for r in made["rooms"]], made["expires"] - made["created"], made["budget"]) == (
                doctor, [room["id"]], 7 * 86400, 5)
        with signed_in_browser(playwright, browser_peer, "doctor") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            held = page.locator(".grants-held .grant-item")
            expect(held).to_contain_text(f"{made['short']} From Alex Patient")
            expect(held.get_by_role("button")).to_have_count(0)
            expect(page.locator(".grants-given .grant-item")).to_have_count(0)
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            item.get_by_role("button", name=f"Revoke {made['short']}").click()
            expect(item).to_contain_text(f"Revoke {made['short']}? Their mentions stop starting builder runs at once")
            expect(item.get_by_role("button", name="Cancel")).to_be_focused()
            assert store.list_grants(patient)[0]["revoked"] is None  # nothing before the confirm
            item.get_by_label("Reason (optional)").fill("Done for now")
            item.get_by_role("button", name=f"Yes, revoke {made['short']}").click()
            expect(item).to_contain_text(f"Not valid Grant {made['short']} was revoked by Alex Patient")
            expect(page.locator(".notice", has_text=f"Grant {made['short']} revoked.")).to_be_visible()
            expect(item.get_by_role("button")).to_have_count(0)
    assert store.list_grants(patient)[0]["revoke_reason"] == "Done for now"


def test_a_double_click_on_make_grant_makes_one_grant(browser_peer):
    """Plan Review Focus 2: a second submit while the first is on its way would make a second grant, doubling the person's
    builds; the page sends one write at a time. The POSTs are counted, so a station that refused the second one could
    not pass for a page that sent one."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            posts = []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and request.url.endswith("/api/grants") else None)
            page.get_by_role("link", name="Grants", exact=True).click()
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI")
            page.get_by_role("button", name="Make grant").dblclick()
            expect(page.locator(".grants-given .grant-item")).to_have_count(1)
            page.wait_for_timeout(300)
            assert len(posts) == 1, posts
    assert len(store.list_grants(users["patient"]["id"])) == 1


def test_an_admin_is_offered_only_his_own_ships(browser_peer):
    """Plan Review Focus 3: Andy is the station's admin, and /api/ships gives an admin every ship; the form offers only the
    ships he owns, since a grant over anyone else's is refused (G8 step 4)."""
    store, users, ship, room, lone = grant_station(browser_peer)
    started = store.start_docking("defiant", "taylor-pc")
    store.confirm_docking(users["organizer"]["id"], started["id"], started["code"])
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "organizer") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            ships = page.locator("#grant-form input[name='grant-ship']")
            expect(ships).to_have_count(1)
            expect(page.get_by_label("Defiant")).to_be_visible()
            expect(page.get_by_label("Serenity")).to_have_count(0)


def test_choosing_another_person_rebuilds_the_rooms_and_drops_the_ones_they_are_not_in(browser_peer):
    """Plan Review Focus 4: rooms ticked for one person stay only if the next person is in them too, so the page never sends
    a room the grantee isn't in (G8 step 2 would refuse it); a room both share keeps its tick."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient, doctor, family = users["patient"]["id"], users["doctor"]["id"], users["family"]["id"]
    both = store.create_room(patient, "Both of them", [doctor, family, ship["id"]])
    old = store.create_room(patient, "Old", [family])
    store.add_participants(patient, old["id"], [users["organizer"]["id"]])  # a newer "Old" replaces it
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient") as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            fill_grant(page, "<img src=x onerror=alert(1)>", "<b>City</b> of AI", "Both of them")
            page.get_by_label("Person").select_option(label="Sam Family")
            expect(page.get_by_label("<b>City</b> of AI")).to_have_count(0)
            expect(page.get_by_label("Both of them")).to_be_checked()
            expect(page.get_by_label("Old", exact=True)).to_have_count(1)  # the current one only
            page.get_by_label("Person").select_option(label="<img src=x onerror=alert(1)>")
            expect(page.get_by_label("<b>City</b> of AI")).not_to_be_checked()  # dropped, not kept for later
            page.get_by_label("Person").select_option(label="Sam Family")
            page.get_by_role("button", name="Make grant").click()
            expect(page.locator(".grants-given .grant-item")).to_contain_text("To Sam Family")
    made = store.list_grants(patient)[0]
    assert (made["grantee"]["id"], [r["id"] for r in made["rooms"]]) == (family, [both["id"]])


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 960}, {"width": 390, "height": 844}])
def test_a_hurried_double_click_on_revoke_only_opens_the_ask(browser_peer, viewport):
    """G22: the ask takes Revoke's place with its question first, so the second press of a hurried double click lands on
    text, at desktop and phone widths: the ask stays open and nothing is revoked or cancelled."""
    base = browser_peer["base_url"]
    store, users, ship, room, lone = grant_station(browser_peer)
    patient = users["patient"]["id"]
    made = store.make_grant(patient, users["doctor"]["id"], [ship["id"]], [room["id"]], 24, 5)
    with sync_playwright() as playwright:
        with signed_in_browser(playwright, browser_peer, "patient", viewport=viewport) as (page, _):
            page.get_by_role("link", name="Grants", exact=True).click()
            item = page.locator(".grants-given .grant-item")
            revoke = item.get_by_role("button", name=f"Revoke {made['short']}")
            revoke.scroll_into_view_if_needed()  # mouse clicks go to viewport coordinates
            double_click_apart(page, revoke)
            page.wait_for_timeout(600)
            expect(item).to_contain_text(f"Revoke {made['short']}?")
    assert store.list_grants(patient)[0]["revoked"] is None
```

`settle` isn't used: the page has no click guard (R17), and every click waits on the locator it clicks.
`double_click_apart` is the board tests' helper, already in the file.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_browser.py -k "grant_is_made or make_grant_makes_one or admin_is_offered or another_person or double_click_on_revoke"`
Expected, after about three minutes: `6 failed`, each with `playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.`
on `get_by_role("link", name="Grants", exact=True)`.

- [ ] **Step 3: Write the implementation**

In `peer/superyak_peer/static/app.js`, replace

```javascript
state.board = null; state.boardView = null; state.layerEdits = {};
```

with

```javascript
state.board = null; state.boardView = null; state.grants = null; state.grantPeople = null; state.grantForm = null; state.grantAsk = null; state.layerEdits = {};
```

In `peer/superyak_peer/static/app.js`, replace

```javascript
["home", "chats", "board", "layers", "shared", "spaces", "research", "search", "connections"].includes(route)
```

with

```javascript
["home", "chats", "board", "grants", "layers", "shared", "spaces", "research", "search", "connections"].includes(route)
```

In `peer/superyak_peer/static/app.js`, insert after

```javascript
        ${navLink("board", "Board", "☰")}
```

this:

```javascript
        ${navLink("grants", "Grants", "✧")}
```

In `peer/superyak_peer/static/app.js`, insert before

```javascript
// One board write at a time: a second click while one is on its way would get 409 for the first one's own work and
```

this:

```javascript
// Grants step 3 (G20-G22): the grants a person gave and holds, a form to make one, and Revoke, which asks first.
// Every name, title and reason is people's text or the station's, escaped where shown.
const GRANT_HOURS = [[24, "1 day"], [72, "3 days"], [168, "7 days"], [720, "30 days"]];

async function loadGrants() {
  const who = identityKey(state.me);
  try {
    const [grants, people] = await Promise.all([api("/api/grants"), api("/api/grants/people")]);
    if (identityKey(state.me) === who) { state.grants = grants; state.grantPeople = people; }
  } catch (error) {
    if (error.status === 401) throw error;
    if (identityKey(state.me) === who) { state.grants = null; state.grantPeople = null; }
  }
}

// G21: the current local rooms that hold the caller (every room in the list does) and the chosen person. A breakout, a
// received room and a room a newer linked room replaced can't be granted (G8 steps 1 and 2).
function grantRoomsWith(personId) {
  const chats = state.home?.chats || [];
  return chats.filter((room) => !room.origin && !room.breakout && !chats.some((other) => !other.origin && other.linked_room_id === room.id)
    && (room.member_ids || []).includes(personId));
}

function grantDraft() {
  return state.grantForm || { grantee: "", ships: [], rooms: [], anyRoom: false, hours: 168, budget: "5" };
}

function grantRoomChoices(draft) {
  if (!draft.grantee) return `<legend>Rooms</legend><p class="meta">Choose a person first; the rooms you share with them show here.</p>`;
  const rooms = grantRoomsWith(draft.grantee);
  const listed = rooms.length ? rooms.map((room) => `<label class="choice"><input type="checkbox" name="grant-room" value="${escapeHtml(room.id)}"${draft.rooms.includes(room.id) ? " checked" : ""}><span class="choice-copy"><strong>${escapeHtml(room.title)}</strong></span></label>`).join("")
    : `<p class="meta">You share no current room with them.</p>`;
  return `<legend>Rooms</legend><label class="choice"><input type="radio" name="grant-scope" value="listed"${draft.anyRoom ? "" : " checked"}><span class="choice-copy"><strong>These rooms</strong></span></label><div class="choices grant-room-list">${listed}</div><label class="choice"><input type="radio" name="grant-scope" value="*"${draft.anyRoom ? " checked" : ""}><span class="choice-copy"><strong>Any room you share with them</strong><small>Rooms made later too. A run builds only in a room you are in.</small></span></label>`;
}

function grantForm() {
  const draft = grantDraft(), mine = (state.ships || []).filter((ship) => ship.owner_id === state.me.id);  // an admin is sent every ship
  const intro = `<p>Their mentions start builder runs of your ships on your machine. A run can read your repository and uses your model time, and its reply is posted in the room.</p>`;
  const body = !mine.length ? `<p class="meta">You have no ships to grant. Dock a machine's agent first.</p>`
    : `<form id="grant-form"><div class="field"><label for="grant-person">Person</label><select class="input" id="grant-person" name="grantee"><option value="">Choose a person</option>${(state.grantPeople || []).map((person) => `<option value="${escapeHtml(person.id)}"${person.id === draft.grantee ? " selected" : ""}>${escapeHtml(person.name)}</option>`).join("")}</select></div><fieldset class="field"><legend>Ships</legend><div class="choices">${mine.map((ship) => `<label class="choice"><input type="checkbox" name="grant-ship" value="${escapeHtml(ship.id)}"${draft.ships.includes(ship.id) ? " checked" : ""}><span class="choice-copy"><strong>${escapeHtml(ship.name)}</strong></span></label>`).join("")}</div></fieldset><fieldset class="field grant-rooms">${grantRoomChoices(draft)}</fieldset><div class="field"><label for="grant-hours">How long</label><select class="input" id="grant-hours" name="hours">${GRANT_HOURS.map(([hours, label]) => `<option value="${hours}"${hours === draft.hours ? " selected" : ""}>${label}</option>`).join("")}</select></div><div class="field"><label for="grant-budget">Builds a day</label><input class="input" id="grant-budget" name="budget" type="number" min="1" max="500" step="1" value="${escapeHtml(draft.budget)}"></div><button class="button" type="submit">Make grant</button></form>`;
  return `<section class="section grant-make" aria-labelledby="grant-make-title"><h2 id="grant-make-title">Let someone build your ships</h2>${intro}${body}</section>`;
}

function readGrantForm(form) {
  const checked = (name) => [...form.querySelectorAll(`[name="${name}"]:checked`)].map((input) => input.value);
  return { grantee: form.elements.grantee.value, ships: checked("grant-ship"), rooms: checked("grant-room"),
           anyRoom: form.querySelector('[name="grant-scope"]:checked')?.value === "*", hours: Number(form.elements.hours.value), budget: form.elements.budget.value };
}

function grantRoomsText(grant) {
  if (grant.rooms === "*") return "Any room you share with them";
  return grant.rooms.map((room) => room.current ? `${room.title} (replaced; now covers ${room.current.title})` : room.title).join(", ");
}

// The ask takes the Revoke button's place with its question first, so a hurried second press lands on text; Cancel
// gets the focus, as the board's Drop does.
function grantItem(grant, given) {
  const short = escapeHtml(grant.short);
  const ships = grant.targets.map((ship) => `${ship.name}, ${ship.ship_builds_left} grant build${ship.ship_builds_left === 1 ? "" : "s"} left for the ship`).join("; ");
  const status = grant.valid ? '<span class="badge active">Valid</span>' : `<span class="badge failed">Not valid</span> ${escapeHtml(grant.reason || "")}`;
  let controls = "";
  if (given && grant.revoked == null) {
    const ask = state.grantAsk?.id === grant.id ? state.grantAsk : null;
    controls = ask
      ? `<div class="board-ask grant-ask" role="group" aria-label="Revoke ${short}?"><p>Revoke ${short}? Their mentions stop starting builder runs at once; a run already going finishes.</p><div class="field"><label for="grant-reason">Reason (optional)</label><input class="input" id="grant-reason" value="${escapeHtml(ask.reason)}"></div><div class="button-row"><button class="button secondary" type="button" data-action="grant-cancel" data-id="${escapeHtml(grant.id)}">Cancel</button><button class="button danger" type="button" data-action="grant-revoke-confirm" data-id="${escapeHtml(grant.id)}" aria-label="Yes, revoke ${short}">Yes, revoke</button></div></div>`
      : `<div class="button-row"><button class="button danger secondary" type="button" data-action="grant-revoke" data-id="${escapeHtml(grant.id)}" aria-label="Revoke ${short}">Revoke</button></div>`;
  }
  return `<li class="grant-item" data-id="${escapeHtml(grant.id)}"><p><code>${short}</code> ${escapeHtml(given ? `To ${grant.grantee?.name}` : `From ${grant.issuer?.name}`)} ${status}</p><p class="meta">Ships: ${escapeHtml(ships)}</p><p class="meta">Rooms: ${escapeHtml(grantRoomsText(grant))}</p><p class="meta">${escapeHtml(`${grant.budget_left} of ${grant.budget} builds left in the last 24 hours · expires ${formatDate(grant.expires)}`)}</p>${controls}</li>`;
}

function grantsView() {
  const head = `<header class="page-head"><div><p class="eyebrow">Your ships</p><h1>Grants</h1><p class="lede">A grant lets another person's mentions start builder runs of your ships, in rooms you share, for a while, with a daily budget of builds.</p></div></header>`;
  if (!Array.isArray(state.grants)) return `${head}<p class="meta">Grants could not be read. Refresh to try again.</p>`;
  const me = state.me.id, held = state.grants.filter((grant) => grant.grantee?.id === me), given = state.grants.filter((grant) => grant.grantee?.id !== me);
  const list = (grants, mine, none) => grants.length ? `<ul class="grant-list">${grants.map((grant) => grantItem(grant, mine)).join("")}</ul>` : `<p class="meta">${none}</p>`;
  return `${head}${grantForm()}<section class="section grants-given" aria-labelledby="grants-given-title"><h2 id="grants-given-title" tabindex="-1">Given by you</h2>${list(given, true, "You haven't let anyone build your ships.")}</section><section class="section grants-held" aria-labelledby="grants-held-title"><h2 id="grants-held-title">Held by you</h2>${list(held, false, "No one has let you build their ships.")}</section>`;
}

// One grant write at a time (G22): a second click while one is on its way would make a second grant or meet the first
// one's revoke. The list is read again after every write, so it shows what the station holds.
async function grantWrite(path, json, message, saved = () => {}) {
  if (state.grantSaving) return;
  state.grantSaving = true;
  const who = identityKey(state.me);
  try {
    const answer = await api(path, { method: "POST", json });
    if (identityKey(state.me) !== who) return;
    saved(answer);
    state.grantAsk = null;
    setFlash(message(answer));
  } catch (error) {
    if (error.status === 401) { showLogin("Your session ended. Sign in again; text in an open form has not been sent."); return; }
    if (identityKey(state.me) === who) setFlash(error.message, true);
  } finally {
    state.grantSaving = false;
    if (state.me && identityKey(state.me) === who) {
      try { await loadGrants(); } catch (_) { /* the list below says it could not be read */ }
      if (routeParts().route === "grants") render();
    }
  }
}

async function makeGrant(form) {
  if (state.grantSaving) return;
  const draft = state.grantForm = readGrantForm(form), rooms = draft.anyRoom ? "*" : draft.rooms;
  const missing = !draft.grantee ? "Choose a person." : !draft.ships.length ? "Choose at least one ship." : rooms !== "*" && !rooms.length ? "Choose at least one room, or any room you share with them." : null;
  if (missing) { setFlash(missing, true); render(); return; }
  // The station refuses a budget that isn't a whole number from 1 to 500, and says so.
  await grantWrite("/api/grants", { grantee: draft.grantee, targets: draft.ships, rooms, hours: draft.hours, budget: Number(draft.budget) },
                   (grant) => `Grant ${grant.short} made.`, () => { state.grantForm = null; });
}

```

In `peer/superyak_peer/static/app.js`, insert before

```javascript
  if (route === "board") { try { await loadData(); }
```

this:

```javascript
  if (route === "grants") { try { await loadData(); } catch (_) { /* the view below reads what it can */ } await loadGrants(); }
```

In `peer/superyak_peer/static/app.js`, replace

```javascript
board: boardView, layers: layersView,
```

with

```javascript
board: boardView, grants: grantsView, layers: layersView,
```

In `peer/superyak_peer/static/app.js`, replace

```javascript
board: "Board", layers: "My sharing layers",
```

with

```javascript
board: "Board", grants: "Grants", layers: "My sharing layers",
```

In `peer/superyak_peer/static/app.js`, insert after

```javascript
  if (form.id === "board-post-form") await postBoardItem(form);
```

this:

```javascript
  if (form.id === "grant-form") await makeGrant(form);
```

In `peer/superyak_peer/static/app.js`, insert before

```javascript
  if (action === "remove-participant") await removeParticipant(target.dataset.id);
```

this:

```javascript
  if (action === "grant-revoke") {
    state.grantAsk = { id: target.dataset.id, reason: "" };
    render();
    document.querySelector('.grant-ask [data-action="grant-cancel"]')?.focus();  // the safe choice
  }
  if (action === "grant-cancel") {
    state.grantAsk = null;
    render();
    document.querySelector(`.grant-item[data-id="${CSS.escape(target.dataset.id)}"] [data-action="grant-revoke"]`)?.focus();
  }
  if (action === "grant-revoke-confirm" && state.grantAsk?.id === target.dataset.id) {
    const grant = (state.grants || []).find((item) => item.id === target.dataset.id);
    await grantWrite(`/api/grants/${pathPart(target.dataset.id)}/revoke`, { reason: state.grantAsk.reason }, () => `Grant ${grant?.short || ""} revoked.`);
    document.querySelector("#grants-given-title")?.focus();
  }
```

In `peer/superyak_peer/static/app.js`, insert after

```javascript
  if (event.target.id === "board-outcome" && state.boardDone) state.boardDone.outcome = event.target.value;
```

this:

```javascript
  if (event.target.closest("#grant-form")) state.grantForm = readGrantForm(event.target.form);  // kept through a re-render
  if (event.target.id === "grant-reason" && state.grantAsk) state.grantAsk.reason = event.target.value;
```

In `peer/superyak_peer/static/app.js`, insert after

```javascript
  if (event.target.id === "file-upload") await uploadFile(event.target);
```

this:

```javascript
  if (event.target.id === "grant-person") {
    // The draft is read from the form, so a room ticked for someone else, gone from the new list, is dropped.
    const form = event.target.form;
    state.grantForm = readGrantForm(form);
    form.querySelector(".grant-rooms").innerHTML = grantRoomChoices(state.grantForm);
  }
```

In `peer/superyak_peer/static/app.css`, insert after

```css
.carry-board ul { margin: 6px 0 0; padding-left: 18px; overflow-wrap: anywhere; }
```

this:

```css
.grant-list { list-style: none; margin: 0; padding: 0; }
.grant-item { padding: 10px 0; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
.grant-item p { margin: 0 0 6px; }
.grant-make form { display: grid; gap: 12px; max-width: 720px; }
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider tests/test_browser.py -k "grant or admin_is_offered or another_person or double_click_on_revoke"`
Expected: `7 passed` (Task 3's label test is selected too). The dry run ran them three more times: 7 passed each time.

- [ ] **Step 5: Check the tests bite**

Apply each alone, run the test named (`-k` with its name), see it fail, restore:
- `state.grantSaving = false;` for `state.grantSaving = true;` in `grantWrite` → `test_a_double_click_on_make_grant_makes_one_grant`;
- `mine = (state.ships || []);` (every ship) in `grantForm` → `test_an_admin_is_offered_only_his_own_ships`;
- drop the `form.querySelector(".grant-rooms").innerHTML = ...` line → `test_choosing_another_person_rebuilds_the_rooms_and_drops_the_ones_they_are_not_in`;
- `rooms: [...new Set([...(state.grantForm?.rooms || []), ...checked("grant-room")])]` in `readGrantForm` (a draft that
  remembers hidden ticks) → the same test;
- drop the `linked_room_id` clause in `grantRoomsWith` → the same test (two rooms called "Old");
- the ask's button row first, before its question → `test_a_hurried_double_click_on_revoke_only_opens_the_ask`, both
  widths (the second press cancels);
- `${given ? ... : ...}` without `escapeHtml`, `${room.title}` in `grantRoomChoices`, `Rooms: ${grantRoomsText(grant)}`,
  or `${person.name}` in the options, each unescaped → `test_a_grant_is_made_on_the_page_held_by_its_grantee_and_revoked_after_the_ask`;
- revoke at once on "grant-revoke" (no ask) → the same test; drop the Cancel focus line → the same test;
- `if (grant.revoked == null)` (Revoke on held grants too) → the same test;
- `hours: 24` for `hours: 168` in `grantDraft` → the same test;
- `?.value !== "listed"` for `?.value === "*"` in `readGrantForm` (any room first) → the same test;
- `{}` for `{ reason: state.grantAsk.reason }` → the same test.

- [ ] **Step 6: Commit**

```bash
git add peer/superyak_peer/static/app.js peer/superyak_peer/static/app.css peer/tests/test_browser.py
git commit -m "Grants 3c: the Grants page: given and held, a form to let someone build your ships, and Revoke that asks first (G20-G22)"
```

---

### Task 6: API.md and the agent README (G23); the whole suites

**Files:**
- Modify: `peer/API.md` ("## Grants", "## Store interfaces for following tasks", "## Run tickets")
- Modify: `agent/README.md` ("## The watcher" and "### Taking the watch")

- [ ] **Step 1: Write the docs**

In `peer/API.md`, replace

```markdown
root `direct` grant from one person to another, made in the browser; merge 3c lets the grantee's mentions spend it.
```

with

```markdown
root `direct` grant from one person to another, made in the browser, and the grantee's mentions spend it through run
tickets (see Run tickets). The web app's Grants page lists them and makes and revokes them.
```

In `peer/API.md`, replace

```markdown
`_grant_validity(db,grant)` returns `(valid, reason)`, and `_grant_policy(db)` is the policy in force.
```

with

```markdown
`_grant_validity(db,grant,budget=True)` returns `(valid, reason)`, and `_grant_policy(db)` is the policy in force.
`Tickets._spendable_grant(db,ship,message)` returns the chain a ticket spends, root first, or None (G15).
```

In `peer/API.md`, replace

```markdown
mentions the ship and is fresh: posted within 24 hours of the ticket, and not yet answered by the ship. An owner's
mention that isn't fresh gets `read` with basis `old` or `answered` (fresh owner mentions spec). Everything else, and every resident ship,
gets `read` with basis `none`. Any member of the
message's room can get a ticket. Ticket: `{id, ship_id, message_id, mode, basis, root_id, root_name, chain,
hops, instructions, blocks, footer, status, created}`. `footer` is `Builder for <owner> (owner)` for a build,
written without `@`, and empty otherwise. Asking again for the same message returns the same ticket while it is
`running`, so the watcher's retries share one decision. Once it is finished, or 7,200 s after it was created,
asking again gets 409.
```

with

```markdown
mentions the ship and is fresh: posted within 24 hours of the ticket, and not yet answered by the ship.

`build` with basis `grant` (spec A step 3, G15-G18) goes to a fresh message that mentions the ship, by another person
who holds a grant over it (see Grants), when all of these hold: the grant's targets include the ship, `direct` is in
its actions and no link in its chain says `confirm: each`; its rooms are `"*"`, or list the message's room or a room
it replaced (following `linked_room_id` back); the message's room is current, local and not a breakout; the author,
the ship and the grant's issuer are all members of it when the ticket is issued; the grant is valid then (see Grants)
and was made no later than the message; and the ship has had fewer than `builds_per_ship_per_day` (20) grant build
tickets in the last 24 hours, under any grant (owner builds don't count). Of several grants, the oldest that qualifies
(by `created`, then id) is used. A grant ticket records `root_id` (the grant's issuer) and `chain` (the grant ids,
root first), and charges each grant in the chain one budget use in the ticket's own transaction, so a message that
mentions two ships charges a grant once per ship's ticket.

An owner's or a grantee's mention that would build but isn't fresh gets `read` with basis `old` or `answered` (fresh
owner mentions spec). Everything else, and every resident ship, gets `read` with basis `none`. Any member of the
message's room can get a ticket. Ticket: `{id, ship_id, message_id, mode, basis, root_id, root_name, chain,
hops, instructions, blocks, footer, status, created}`. `footer` is `Builder for <owner> (owner)` for an owner build
and `Builder for <issuer>, via <grantee> · grant #a1b2` for a grant build (`grants #a1b2 > #c3d4` for a chain of
several links), its names on one line without `@`, and empty otherwise. Asking again for the same message returns
the same ticket while it is `running`, so the watcher's retries share one decision. For a grant ticket the station
first checks the grant again: not revoked, not expired, within the policy, its issuer still owning every target and
still in the message's room. It doesn't check the budget or the per-ship cap again, which the ticket already paid. If
a check fails, the ticket is finished and the request gets 409 with the reason; the watcher then posts its fallback
note, which the finished ticket can't label, and stops retrying. A run already under way finishes. A grant build is
never deferred to the ship's session on watch: only a read decision is. Once a ticket is finished, or 7,200 s after
it was created, asking again gets 409.
```

In `peer/API.md`, replace

```markdown
`{kind:"run", mode, basis, root_name, answering}` for a ticketed reply, `{kind:"post"}` for anything else a ship
```

with

```markdown
`{kind:"run", mode, basis, root_name, answering}` for a ticketed reply (with `via_name`, the grantee, when the basis is
`grant`), `{kind:"post"}` for anything else a ship
```

In `agent/README.md`, replace

```markdown
It is never cut; earlier messages keep 2,000 characters, with a note where cut. An owner's fresh mention (within 24 hours, not yet answered), from a person the station verified,
```

with

```markdown
It is never cut; earlier messages keep 2,000 characters, with a note where cut. An owner's fresh mention (within 24 hours, not yet answered), from a person the station verified,
or a fresh mention by a person the owner granted builds of this ship on the station's Grants page,
```

In `agent/README.md`, replace

```markdown
- the station defers this ship's watcher's read-only runs; an owner's fresh mention (posted within 24 hours, not yet answered by the ship) still runs as a builder;
```

with

```markdown
- the station defers this ship's watcher's read-only runs; an owner's fresh mention (posted within 24 hours, not yet answered by the ship), or a grantee's under a valid grant, still runs as a builder;
```

In `agent/README.md`, replace

```markdown
the station's footer ("Builder for Andy (owner)"), and the station labels the reply as that run. People and
agents see the label beside the author's name: "builder run for Andy", "read-only run", or "no run ticket" for
anything else a ship posts.
```

with

```markdown
the station's footer ("Builder for Andy (owner)", or "Builder for Andy, via Jenn · grant #a1b2" under a grant), and
the station labels the reply as that run. People and agents see the label beside the author's name: "builder run for
Andy", "builder run for Andy, via Jenn", "read-only run", or "no run ticket" for anything else a ship posts. When a
grant is revoked between a run's tries, the station refuses the retry (409) and the watcher posts its fallback note
unlabelled.
```

- [ ] **Step 2: Run the whole suites**

Run: `cd peer && PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m pytest -q -p no:cacheprovider`
Expected: everything passes: `932 passed, 1 skipped` (907 and 1 skipped at `6841ce0`, plus 25: 1 in test_signatures, 15
in test_grant_tickets, 2 in test_ship_agent, 7 in test_browser), about six minutes.

Run: `cd agent && PYTHONDONTWRITEBYTECODE=1 uv run --locked --extra dev python -m pytest -q -p no:cacheprovider`
Expected: `753 passed` (751 plus 2).

Report the counts, and any failure by name.

- [ ] **Step 3: Commit**

```bash
git add peer/API.md agent/README.md
git commit -m "Grants 3c: API.md's basis grant and the agent README's grant builds (G23)"
```

---

## After the tasks

- Merge `main` before section 2 review if it moved.
- Section 2: post the head in "Superyak: city of AI" for Rio Grande; the Pi runs both suites. On merge, the deploy
  restarts the lighthouse (tickets, the page) and the door; each machine's watcher picks up the prompt and the label when
  it updates. No schema change, so no migration; back up the database first, as always.
- A live check, as Andy: make a grant to Jenn on the Grants page over one ship, in one room they share, 1 day, 1 build;
  Jenn mentions the ship there; the reply ends `Builder for Andy, via Jenn · grant #....` and is labelled "builder run
  for Andy, via Jenn"; her next mention reads (budget used); Andy revokes, and the page shows why it is no longer valid.

## Self-review: every rule and test to its task

| Spec | Task and test |
| --- | --- |
| 3b section 2 minor (pre-check read-only) | 0: `test_the_peer_tls_check_never_plays_back_a_hot_journal` |
| Rio Grande's `current` ruling (R4) | 0: 3b's rooms test, its M1 line |
| G15, test 11 | 1: the table (owner, grantee, another person, a ship, a resident; none, valid, expired, revoked, another ship, another room, budget used, made after, same second, exactly 24 hours, older, answered, author gone, `"*"` without the issuer, issuer removed; and breakout, remote, `confirm: each`, no `direct`) |
| G15 oldest grant, test 15 | 1: oldest charged, the next when spent, `created` then id |
| G15 per-ship cap, test 14 | 1: the 21st reads across two grants, owner builds don't count, `ship_builds_left` on the other grant, the 24-hour edge |
| G15 room walk, test 16 | 1: X, X', X''; a replaced room reads; a hand-made cycle ends |
| G15 `old`/`answered` (R1) | 1: test 11's `older` and `answered`; fresh owner mentions' non-owner test; the unusable `created` |
| G16 | 1: root_id, chain, one use at the ticket's time; 3: one use per link with two links |
| Test 13 | 1: budget reads, the 24-hour edge, two ships share one budget |
| Test 19 | 1: two ships, one build left |
| G18, test 12 | 2: revoke before the ticket reads; after it 409, finished, a post with it 409, asked again 409; a re-send charges nothing (last build, 20th build); the real watcher's unlabelled fallback |
| G18 re-check scope (R2) | 2: expiry, ownership, membership, policy, a missing grant; a member added keeps the ticket |
| Test 18 | 2: a grant build isn't deferred; another person's mention is |
| G17, test 17 | 3: footer and source; two links; the real watcher's footer and `source_label`; the web label; `source_label`'s odd values |
| G19 | 4: the new sentence; a limited prompt says only why |
| runs.py docstring | 4 (review) |
| G20, G21, G22, test 20 | 5: make, given, held, revoke after the ask, HTML as text; one write at a time; an admin's own ships; the person switch; the hurried double click |
| G23 | 0 (the `current` line), 6 |
