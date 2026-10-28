# Plan review: fix:pairing-code (revision 1, b9b71648)

A fresh reviewer agent started on Tardis, which took no part in writing the plan, briefed with the plan, the approved
federation-pull spec and the code, not the author's conclusions (station law section 3). Its verdict, whole. Every
item is applied in plan revision 2.

VERDICT: APPROVE WITH CHANGES

(Bash failed with EDQUOT throughout, so I read every file with Read and could not grep. Where I name existing callers,
I name only ones I opened.)

Must-fix:
1. Plan §4 / Task 2, the `pairing_code` column. Main's `pair()` inserts into this table by position, `INSERT INTO
   remote_contacts VALUES(?,?,?,?)` (federation.py:36). Once the migration adds a fifth column, rolling back to main
   makes every pair and re-pair fail with an OperationalError, which surfaces as a 500. The plan has no rollback note.
   The column also leaves every pairing that exists today showing null, but spec §2 and §8 say `connections` lists
   each paired peer's code "for later checks". The column isn't needed. `connections()` already rebuilds each
   contact's exact card (federation.py:51): `peers.card` plus that contact's `{id, name}`. The 409 check
   (federation.py:33) plus the `peer_id` key and `version==1` make that rebuild byte-equal to the card that was
   imported. Change: compute `pairing_code` in `connections()` from the rebuilt card, so old contacts get a code too.
   If you want to record that a code was typed, write it to a new table (`pairing_confirmations(contact_id, code,
   confirmed)`). Main's code ignores an unknown table, so rollback stays safe. Show "confirmed by typing" or "paired
   before pairing codes" from that table. Drop the column test and add a rebuilt-equals-imported test for two
   participants of one peer.
2. Task 3, the stdin mutant isn't really tested. With `pty.fork` the tty is also fds 0, 1 and 2, so an implementation
   that reads stdin passes the pty test. The no-terminal test never puts the right code on stdin. Change:
   - (a) No terminal: `start_new_session=True`, `stdin=PIPE` carrying the right code, a timeout. Expect exit 2, the
     terminal message, and nothing paired.
   - (b) pty: in the child, `dup2` a pipe holding a wrong code (or /dev/null) onto fd 0. The right code typed on the
     tty pairs.
   - (c) The reverse of (b), right code on stdin and wrong on the tty, refuses.
   - (d) Run "non-admin or pending refuses before asking" under a pty and assert the prompt never appears. Otherwise,
     when Andy runs pytest from a terminal, a check in the wrong order blocks on his tty. Without a tty it fails
     through the exit-2 path instead.

Should-fix:
1. Plan §3, one check in one place. Verify the code inside `Federation.pair`, after `_admin` (federation.py:29), and
   store `pairing_code(card)`, never the typed text. Today's plan splits the check between the route and the CLI, and
   the route (peer_routes.py:53-57) would answer a non-admin 400 before 403.
2. The CLI must not create an identity. `Federation(store, …)` calls `load_or_create` when no identity is passed
   (federation.py:16). So `pair` or `connections` on a new data dir would mint an identity naming only localhost. The
   first `card --endpoint` would then no longer name its host, the M1 property signatures.py:56-57 protects. Pass an
   identity only when identity.json exists, and skip the self-pair check otherwise.
3. Untrusted text reaches the terminal. `validate_card` checks the participant name with `text()`, which allows ESC,
   CR and newline (common.py:41-44). The endpoint check refuses only whitespace (identity.py:56). `pair` and
   `connections` print both, so print them through `safe_line`, as station-pending does (__main__.py:59).
4. The threat model needs stating. `/dev/tty` blocks arguments, environment variables and pipes. It doesn't block a
   pty wrapper (`script`, `expect`, `pty.spawn`), and the plan's own test is that recipe. Any HTTP client holding an
   admin session can compute the code from the card, and the mismatch 400 hands it over anyway. Change:
   - Say in PROTOCOL.md that the code proves the card matches the exporting screen, not that a person typed it.
   - Make the CLAUDE.md rule also forbid a ship running `pair` under any pty, computing a code from a card, or calling
     the pair route or `Federation.pair`.
   - "A ship's Bash has none" is unverified. Run `python3 -c "open('/dev/tty')"` from a ship session on Tardis, the
     Pi and the Mac, and record the result in the plan.
5. Existing callers of the old shape aren't listed:
   - app.js:2052 posts `{card, fingerprint}`;
   - app.js:1048 has the "Fingerprint matches — pair this peer" button and the lede, and line 1045 has the copy;
   - test_browser.py builds `remote_card` for browser pairing flows (76-87, 112);
   - API.md:665 and 668;
   - PROTOCOL.md:39-41 ("review the named participant and fingerprint").

   List and update them all, and grep tests/ for `fingerprint` and `confirm-pair`.
6. Test gaps:
   - (a) Spec §10.2's first bullet, adapted to v1: the code `card` prints on stderr, and the code "Show my peer card"
     shows, each equals the code the other side's `connections` lists after pairing. Without it, a code computed over
     the indent=2 text passes every one-side test.
   - (b) A route-level binding test: the right code for card A (same peer, other participant or renamed) sent with
     card B gives 400.
   - (c) "Typed with spaces and upper case works" should also assert that the stored or listed code is the normalised
     one.
7. Browser: `showCard` puts the card JSON in a flash (app.js:1693). Show the code outside the copyable JSON, labelled
   "type this on the other machine; never send it with the card". Otherwise one copy carries both through the same
   untrusted channel.

Nits:
- Task 1's "any one of seven fields" can't be done as written. `version` has no other valid value.
  `signing_key`+`peer_id` and `certificate`+`fingerprint` only change in pairs, so use a second identity for them.
- `typed_code`: match `[0-9a-f]{32}` on ASCII. `int(x, 16)` accepts Unicode digits. Add a non-ASCII digit to the
  refusal test.
- Opening /dev/tty raises OSError, and the generic handler at __main__.py:530-531 turns that into exit 1. Catch it
  first to get exit 2.
- Write the prompt and the mismatch line to /dev/tty, not stdout. A backgrounded `pair` hangs on SIGTTIN; consider
  checking `tcgetpgrp`.
- pty test: read until the prompt before writing. An implementation that flushes type-ahead would otherwise flake.
  Handle EIO when reading the master on Linux.
- `--as` is a username. Resolve it with `kind!='system'`, as `card` does (__main__.py:463).
- The 201 from `pair` returns `SELECT *` (federation.py:37). Use the same code format `connections` uses.
- The "preview holds no code" check should look for both the 32-hex and the grouped form, plus a DOM check in the
  browser.
- Keep the typed code across `render()`, which rebuilds the panel from a template (app.js:1048). Make Enter submit.
  Clearing the preview after a mismatch would make copying the disclosed code a deliberate act.
- The mismatch disclosure itself is what spec §2 sanctions ("in the message when a typed code doesn't match"). Not
  disclosing on malformed input is right.
- The browser fixture creates its app with no endpoint (test_browser.py:52), so the "Show my peer card shows the code"
  test needs one configured.

## Re-check of revision 2, by the same reviewer, whole

RE-CHECK: APPROVE WITH CHANGES

(Bash still fails with EDQUOT, so I read everything with Read. I re-read revision 2 and federation.py lines 260-417,
where `receive` and `_apply` live, and found no writer of `remote_contacts.name` other than `pair()`.)

Must-fix items:
- MF1: applied.
  - **Rollback:** `remote_contacts` keeps its four columns, so main's positional INSERT (federation.py:36) still
    works. The table is created in PEER_SCHEMA, which runs on every open, so old stores gain it. The rollback test
    pins this.
  - **Rebuild:** byte-equal for each contact.
    - `peers.card` goes through `encode`, and `json.loads` gives back the same strings and the int 1, so `canonical`
      matches.
    - The 409 check fixes signing_key, certificate, fingerprint and endpoint. `peer_id` is the key, and
      `validate_card` forces version 1 and exactly seven keys.
    - The participant is replaced from the contact row. A renaming re-pair updates that row (`ON CONFLICT … SET
      name=excluded.name`) and the confirmation in the same transaction, so the rebuild equals the last imported card.
- MF2 (a)-(d): applied, and the tests now tell a tty read from a stdin read.
  - (a) gives the right code on stdin with no ctty, so an implementation that reads stdin pairs and the test fails.
  - (b) and (c) cross the two inputs. `dup2` onto fd 0 doesn't change the ctty that `pty.fork`'s `login_tty` set.
  - (d) puts the order (admin check, then prompt) under a pty, and the mutant list includes "`_admin` after the tty
    prompt".
  - The `tcgetpgrp` check passes in a `pty.fork` child. TIOCSCTTY makes the session's group the foreground group on
    both Linux and macOS.

New must-fix: none.

New should-fix (small, can go into the build):
1. Define `confirmed` as "a confirmation row exists **and** its code equals the code computed from the rebuilt card",
   not just "a row exists". Here is how they can drift: roll back to main, re-pair with a renamed participant (main
   updates the name but not the confirmation), then roll forward. A stale row would still read "confirmed by typing".
   Add that case to the rollback test.
2. The route passes `data.get('code')` through unchecked, so `typed_code` must return None for anything that isn't a
   str. Otherwise a code of `123` or `[…]` hits `.replace` and the server answers 500. Add a route test for an int and
   a list.
3. The foreground-group check could refuse the honest path if a launcher puts the child in its own process group. Run
   the by-hand check exactly as Andy will: `uv run python -m superyak_peer pair …`, and through any make target. One
   more thing to say in the API.md / CLAUDE.md text: Andy can't pair through a Claude session's `!` prompt, because it
   runs the same way ship Bash does, which has no tty (Tardis: ENXIO). He types in an ordinary shell or tmux pane.

Should-fix and nits:
- SF1-SF7 and every nit are applied as I meant them.
- SF4 is still open in one place: the Pi and Mac rows of the /dev/tty table are pending. If either opens /dev/tty,
  revision 2 should say what follows before the build.
- SF2 (NO_IDENTITY): sound. `pair()` skips the self-pair check, and `connections()` never touches the identity. Two
  conditions:
  - the sentinel must stay truthy, because `__init__` does `identity or load_or_create(...)` (federation.py:16);
  - it should raise on any other use, such as `card`, `receive` or `_prepare`, so it can never quietly reach
    `create_app`.
- Making `code` required and keyword-only is fine. The grep step at plan line 110 covers callers outside tests too. A
  production `.pair(` that it misses would fail loudly with a TypeError, not pair silently.

All three re-check should-fix items and both conditions are applied in revision 2, marked "re-check".
