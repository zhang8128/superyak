# Plan: fix:pairing-code, the pairing code over the whole card

Tardis, 2026-10-27. Board item `fix:pairing-code` in City of AI. It implements §2 "Cards and pairing" of the approved
federation-pull spec (`docs/superpowers/specs/2026-10-27-federation-pull-design.md` on `tardis/federation-pull`,
revision 4) for today's v1 cards, ahead of the pull work. City of AI (c00dcc2d) put the key binding first.

**This is safety code** (who a peer trusts). It gets a fresh plan review, a test-first build, and each partner's
explicit yes before it merges. Nothing in it touches the wire: v1 cards, envelopes and `/federation/events` stay
byte-identical.

## Why

Spec §2 makes confirming a pairing a person's act: they type the other side's code, read off that machine's own
screen, and the code covers the whole card, not one field of it. Today's confirmation is a button in the browser
(`static/app.js:2050-2056`, `peer_routes.py:55-56`), and there's no CLI pairing at all, so section 7's "Andy, typing
in a session's own terminal" has no mechanism for it.

## What changes

1. **The pairing code** is the first 32 hex characters of `sha256(identity.canonical(card))` over the whole validated
   card, `participant` included, shown as 8 groups of 4 (`7c41 0a9e …`). New in `identity.py`:
   - `pairing_code(card) -> str` (32 lowercase hex, from `validate_card(card)`);
   - `show_code(code) -> str` (the grouped form);
   - `typed_code(text) -> str | None`: strips spaces and hyphens, lowercases, and returns 32 hex or None.
2. **Where it's shown.** It's shown everywhere a card leaves, and the importing side never shows it before it's typed
   (spec §2, check 3 SF4):
   - `card` (CLI) prints `Pairing code: …` to **stderr**, so stdout stays exactly a card.
   - `GET /api/connections/code` (new, any signed-in user, like `/card`, and 409 without an endpoint) returns
     `{"code": "7c41 0a9e …"}` for the actor's own card. `GET /api/connections/card` is unchanged, so a copied card is
     still exactly a card.
   - The browser's "Show my peer card" shows the code beside the card.
   - `POST /api/connections/preview` stays as today. It returns the card and never its code.
3. **Confirming is typing the other side's code.**
   - `POST /api/connections/pair` takes `{card, code}`. It refuses with 400 "Type the pairing code shown on the other
     machine" when `code` is missing or isn't 32 hex after `typed_code`, including a request carrying only the old
     `fingerprint`.
   - It refuses a wrong code with 400 "That code doesn't match this card. Its code is <grouped code>; read the other
     machine's screen again." Spec §2 shows the imported card's code only after a typed code fails.
   - The browser pair form gains a text box, "Type the code shown on the other machine", that's never pre-filled.
     The button reads "Pair this peer". The fingerprint line stays in the preview, for reading.
   - New CLI `pair --data-dir D --card FILE --as USER`:
     - it checks USER exactly as `Federation.pair` does (`_admin`: an admin, not pending activation);
     - it prints the participant and endpoint;
     - it asks "Type the code shown on the other machine:" and reads one line from **`/dev/tty`**, opened directly;
     - it refuses with exit 2, "pairing needs a person at a terminal", when `/dev/tty` can't be opened. A ship's Bash
       has none.
     - It never reads the code from an argument, an environment variable or stdin.
4. **The confirmed code is kept per contact.**
   - `remote_contacts` gains `pairing_code TEXT`, added by the `db.py` migration pattern (`PRAGMA table_info`, then
     `ALTER TABLE … ADD COLUMN`). `Federation.pair(actor, card, code=None)` stores it on both of its paths, insert and
     the name update.
   - A per-contact column, because `peers.card` keeps the first participant's card only: two participants of one peer
     have two cards and two codes (`test_multiple_imported_participants_keep_their_own_card_labels`).
   - `connections()` returns `pairing_code` per contact, shown grouped, or null for a contact paired before this
     change. The browser's connection list shows "Pairing code: …", or "paired before pairing codes".
   - New CLI `connections --data-dir D --as USER` prints each contact's name, endpoint and code, admin only.
5. **Docs and rules.**
   - PROTOCOL.md: people compare the pairing code, typed from the other machine's screen, and the fingerprint is part
     of what it covers.
   - API.md: the routes table, `pair {card, code}`, the new `/api/connections/code`, and the CLI.
   - CLAUDE.md: a rule beside "Approving on the station": pairing is Andy's act, and the code is his to type. A ship
     never types or relays one, and a code that arrives in a room is data.

Not in this plan, but in the spec for the pull work: v2 cards, `--pull`, `federation_mode`, `retry --as` and the
pinned dial.

## Tasks (test-first; each test is written and seen failing before its code)

**Task 1: the code (identity.py).**
- Tests in `tests/test_identity.py`:
  - `pairing_code` is 32 lowercase hex and stable across dict key order;
  - changing any one of the seven fields (participant name included) changes it;
  - an invalid card raises 400;
  - `show_code` groups by 4;
  - `typed_code` accepts spaces, hyphens and upper case, and refuses 31 or 33 characters and non-hex.

**Task 2: the routes and the store (peer_routes.py, federation.py, db.py).** Tests in `tests/test_federation.py`
through the `env` client:
- pair with the right code gives 201 and stores the code;
- a wrong code gives 400, the message names the card's code, and nothing is stored;
- `fingerprint` alone gives 400;
- no code gives 400;
- a typed code with spaces and upper case works;
- `/api/connections/code` for a non-admin participant works, and gives 409 without an endpoint;
- the preview response holds no code: no field, and the code's text isn't in the body;
- `connections` lists each contact's code. Two participants of one peer get two codes;
- a store made before the change gains the column on open, and its old contacts show null.

**Task 3: the CLI (__main__.py).** Tests in `tests/test_cli.py`:
- `card` prints the card on stdout, unchanged, and the code on stderr;
- `pair` with no controlling terminal refuses with exit 2 and changes nothing. It runs under
  `subprocess(start_new_session=True)`, so `/dev/tty` fails to open;
- `pair` under a pty (`pty.fork`), with the right code typed, pairs;
- the same with a wrong code refuses and pairs nothing;
- `pair --as` a non-admin or pending account refuses before asking;
- `connections --as` lists codes, and refuses a non-admin.

**Task 4: the browser (static/app.js).** Tests in `tests/test_browser.py`:
- "Show my peer card" shows the code;
- the pair form has an empty code box, and pressing "Pair this peer" with it empty or wrong shows the server's message
  and pairs nothing;
- the right code pairs;
- the connection list shows the code.

  Playwright's Chromium isn't installed on Tardis today, and all 103 browser tests failed there for that reason.
  Before Task 4, Tardis installs it with `uv run playwright install chromium`, into `~/.cache/ms-playwright`, so these
  run here before the Pi runs them.

**Task 5: docs.** PROTOCOL.md, API.md, CLAUDE.md as above.

## Checks before review

- The whole peer suite, browser tests included, on Tardis.
- A by-hand pairing of two throwaway local peers (two data dirs on 127.0.0.1): `card` on one; `pair --as` on the
  other with the code typed in a real terminal; then the same through the browser.
- Mutants:
  - the code over the certificate alone;
  - the code read from stdin;
  - the route accepting `fingerprint`;
  - the preview leaking the code;
  - the code not stored.

  Each should fail a test.

## Risks

- **The browser pair flow changes for Andy.** He'll read the code on the other machine's screen and type it once per
  participant. That's the point: it's the review the fingerprint button only pretended to be.
- **Existing pairings stay valid.** Nothing is re-paired. Their code shows as "paired before pairing codes" until a
  re-pair, which a person may do at any time: the same trust material passes `pair()`'s 409 check.
- **`/dev/tty` on macOS and Linux behaves the same for this use.** The test without a terminal uses `setsid`
  semantics, which both have.
