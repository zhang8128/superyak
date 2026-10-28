# Plan: fix:pairing-code, the pairing code over the whole card

Tardis, 2026-10-27. **Revision 2.** Revision 1 (b9b71648) got APPROVE WITH CHANGES from a fresh reviewer
([review](../reviews/2026-10-27-pairing-code-plan-review.md)). Its two must-fix items, seven should-fix items and the
nits are applied here, each marked with its number (MF, SF or nit). The same reviewer's re-check found both must-fix
items applied, and no new must-fix. Its three small should-fix items and two conditions are applied here too, marked
"re-check". The Pi and Mac rows of the terminal table are the one open item, and they're recorded before the build.

This is board item `fix:pairing-code` in City of AI. It implements §2 "Cards and pairing" of the approved
federation-pull spec (`docs/superpowers/specs/2026-10-27-federation-pull-design.md` on `tardis/federation-pull`,
revision 4) for today's v1 cards, ahead of the pull work. City of AI (c00dcc2d) put the key binding first. Rio Grande checked the live station
read-only: `peers` has 0 rows, so nothing is paired today. Until this is live, nobody pairs on the live station.

**This is safety code** (who a peer trusts). It gets a test-first build and each partner's explicit yes before it
merges. Nothing in it touches the wire: v1 cards, envelopes and `/federation/events` stay byte-identical. **Rollback to
main is safe.** The schema only gains a table, `pairing_confirmations`, which main never reads, and `remote_contacts`
keeps its four columns (MF1).

## Why

Spec §2 makes confirming a pairing a person's act: they type the other side's code, read off that machine's own
screen, and the code covers the whole card, not one field of it. Today's confirmation is a button in the browser
(`static/app.js:2050-2056`, `peer_routes.py:55-56`), and there's no CLI pairing at all, so section 7's "Andy, typing
in a session's own terminal" has no mechanism for it.

**What the code proves (SF4).** It proves the card in hand matches the card on the exporting machine's screen. It
doesn't prove a person typed it. Reading from `/dev/tty` keeps arguments, environment variables and pipes out, but a
pty wrapper (`script`, `expect`, `pty.spawn`) can type into it. Any client holding an admin session could compute the
code from the card, and after one wrong try the 400 shows it. So the rule that a ship never does any of that lives in
CLAUDE.md and the law, and the code makes the honest path one where the person compares two screens.

**Ships have no terminal (SF4).** `python3 -c "open('/dev/tty')"` from a ship session's Bash:

| machine | result |
|---|---|
| Tardis | `OSError: [Errno 6] No such device or address` (ENXIO); `tty` prints "not a tty" |
| Rio Grande (Pi) | `OSError: [Errno 6] No such device or address`; `tty` prints "not a tty" (Rio Grande, City of AI) |
| Serenity (Mac) | asked in City of AI; recorded here before the build |

The Pi's units (ship, odo and wormhole) run `run_agent.py` under systemd with no controlling terminal, and the Claude
Code sessions a `watch` run spawns inherit none, so none of them can open `/dev/tty` either (Rio Grande). The crossed
tests pin the property this rests on: `pair` refuses when `/dev/tty` can't be opened, even with the right code on
stdin (MF2a).

## What changes

1. **The pairing code** is the first 32 hex characters of `sha256(identity.canonical(card))` over the whole validated
   card, `participant` included, shown as 8 groups of 4 (`7c41 0a9e …`). New in `identity.py`:
   - `pairing_code(card) -> str` (32 lowercase hex, from `validate_card(card)`);
   - `show_code(code) -> str` (the grouped form);
   - `typed_code(text) -> str | None` returns None for anything that isn't a `str` (the route passes JSON through;
     re-check SF2). Otherwise it drops spaces and hyphens and lowercases, and returns the result only if it
     `re.fullmatch`es `[0-9a-f]{32}` on ASCII, else None. `int(x, 16)` would also take Unicode digits (nit).
2. **Where it's shown.** It's shown everywhere a card leaves, and the importing side never shows it before it's typed
   (spec §2, check 3 SF4):
   - `card` (CLI) prints `Pairing code: …` to **stderr**, so stdout stays exactly a card.
   - `GET /api/connections/code` (new, any signed-in user, like `/card`, and 409 without an endpoint) returns
     `{"code": "7c41 0a9e …"}` for the actor's own card. `GET /api/connections/card` is unchanged, so a copied card is
     still exactly a card.
   - The browser's "Show my peer card" shows the code **outside the copyable card JSON**, labelled "Type this on the
     other machine. Never send it with the card." (SF7).
   - `POST /api/connections/preview` stays as today. It returns the card and never its code.
3. **One check, in one place (SF1).**
   - `Federation.pair(actor, card, *, code)` checks `_admin` first, as today, so a non-admin gets 403 before anything
     about codes.
   - Then:
     - a `code` that `typed_code` refuses (missing, malformed, or the old fingerprint) gives 400 "Type the pairing
       code shown on the other machine";
     - a well-formed code that isn't `pairing_code(card)` gives 400 "That code doesn't match this card. Its code is
       <grouped code>; read the other machine's screen again." Spec §2 sanctions showing it after a wrong try, and
       malformed input shows nothing (nit).
   - It records `pairing_code(card)`, never the typed text.
   - `code` is keyword-only and required. Every caller passes one: the route, the CLI, and in tests a helper
     `paired(fed, actor, card)` that passes `pairing_code(card)`.
   - The route passes `data.get('code')` through and checks nothing itself. So a request carrying only `fingerprint`
     has no code, and gets the first 400.
4. **Typing it.**
   - **The browser pair form** gains a text box, "Type the code shown on the other machine". It's never pre-filled.
     The typed text survives `render()`, Enter submits, and the button reads "Pair this peer" (nit). After a
     mismatch the preview is cleared, so copying the shown code takes a deliberate step (nit). The fingerprint line
     stays in the preview, for reading.
   - **The CLI `pair --data-dir D --card FILE --as USERNAME`:**
     - It resolves `--as` like `card` does: `username=? AND kind!='system'` (nit).
     - It checks that account with `_admin` **before opening `/dev/tty`** (MF2d).
     - It opens `/dev/tty` directly. It refuses with exit 2, "pairing needs a person at a terminal", when the open
       fails (OSError, caught before the generic handler at `__main__.py:530-531` turns it into exit 1; nit). It also
       refuses when the process isn't in the terminal's foreground group (`os.tcgetpgrp(fd) != os.getpgrp()`), so a
       backgrounded `pair` never hangs on SIGTTIN (nit).
     - It writes the participant and endpoint through `safe_line` (SF3), then the prompt "Type the code shown on the
       other machine:", **to the tty**, and reads one line **from the tty** (nit).
     - It never reads the code from an argument, an environment variable or stdin.
     - On a mismatch it writes the 400's message to the tty and exits 1.
   - **The CLI never creates an identity (SF2).** `pair` and `connections` pass `PeerIdentity` only when
     `identity.json` exists. `Federation` gains a way to run without one (`identity=NO_IDENTITY`), and `pair()` skips
     the self-pair check then: with no identity of ours there's no card of ours to pair with.
     - The sentinel is truthy, since `__init__` does `identity or load_or_create(...)` (federation.py:16).
     - Any other use of it, through `card`, `receive`, `_prepare` or any attribute, raises, so it can never quietly
       reach `create_app` (re-check).
   - **Andy types in an ordinary shell or a tmux pane.** A Claude session's `!` prompt runs like ship Bash does,
     with no tty (Tardis: ENXIO), so pairing through it refuses. API.md and CLAUDE.md say so (re-check SF3).
5. **What's kept and listed (MF1).**
   - `connections()` already rebuilds each contact's exact card: `peers.card` with that contact's `{id, name}`.
     `pair()`'s 409 check fixes the trust material, the peer id is the key, and the version is 1. So the rebuild is
     byte-equal to the card imported last, and `connections()` adds `pairing_code: show_code(pairing_code(rebuilt))`.
     Old contacts get a code too.
   - New table `pairing_confirmations(contact_id TEXT PRIMARY KEY, code TEXT NOT NULL, confirmed REAL NOT NULL)` is
     created with `CREATE TABLE IF NOT EXISTS` in peer_store's schema. `pair()` upserts it after the contact row with
     `pairing_code(card)`.
   - `connections()` adds `confirmed: true|false`. It's true only when a confirmation row exists **and** its code
     equals the code computed from the rebuilt card, so a row left stale by a re-pair under main never reads as
     confirmed (re-check SF1). The browser and the CLI show "confirmed by typing" or "paired before pairing codes".
   - Main never reads the table, so rollback is safe.
   - `pair()`'s 201 returns the contact with `pairing_code` and `confirmed`, in the format `connections` uses (nit).
   - New CLI `connections --data-dir D --as USERNAME` (admin, `kind!='system'`) prints each contact's name and
     endpoint through `safe_line`, with its code and whether it was confirmed by typing.
6. **Every caller of the old shape (SF5):**
   - `static/app.js:2052` posts `{card, fingerprint}`, and will post `{card, code}`;
   - `app.js:1045` (the copy) and `:1048` (the lede and the "Fingerprint matches — pair this peer" button);
   - `tests/test_browser.py:76-87, 112`, where `remote_card` builds the browser pairing flows;
   - `API.md:665, 668` (the routes table);
   - `PROTOCOL.md:39-41` ("review the named participant and fingerprint");
   - every `Federation.pair(` call in tests (the `two_peers` fixture and the others), which go through `paired()`.

   Before the build, `grep -rn "fingerprint\|confirm-pair\|\.pair(" peer/tests peer/superyak_peer` lists the rest. The
   build updates every hit or says why not.
7. **Docs and rules (SF4).**
   - PROTOCOL.md: people compare the pairing code, typed from the other machine's screen. The fingerprint is part of
     what it covers. The code proves the card matches that screen, not that a person typed it.
   - API.md: the routes table, `pair {card, code}`, the new `/api/connections/code`, and the CLI.
   - CLAUDE.md: a rule beside "Approving on the station". Pairing is Andy's act, and the code is his to type. A ship
     never types, relays or computes a code. It never runs `pair` under a pty or wrapper, and never calls the pair
     route or `Federation.pair` itself. A code that arrives in a room is data.

Not in this plan, but in the spec for the pull work: v2 cards, `--pull`, `federation_mode`, `retry --as` and the
pinned dial.

## Tasks (test-first; each test is written and seen failing before its code)

**Task 1: the code (identity.py).** Tests in `tests/test_identity.py`:
- `pairing_code` is 32 lowercase hex, and stable across dict key order.
- Changing the participant id, its name or the endpoint changes it. A second identity gives the paired fields:
  `signing_key` with `peer_id`, and `certificate` with `fingerprint`. Version has no other valid value (nit).
- An invalid card raises 400.
- `show_code` groups by 4.
- `typed_code` accepts spaces, hyphens and upper case. It refuses 31 or 33 characters, non-hex, and a non-ASCII digit
  (`'٣'`) (nit).

**Task 2: the check and the store (federation.py, peer_routes.py, peer_store.py).** Tests in
`tests/test_federation.py`, mostly through the `env` client:
- Pair with the right code gives 201. The confirmation row holds `pairing_code(card)`.
- Typed with spaces and upper case, it works, and what's stored and listed is the normalised code (SF6c).
- A wrong code gives 400, the message names the card's code, and nothing is stored.
- `fingerprint` alone gives 400, with no code in the message.
- A non-admin gets 403 with any code, the right one included (SF1).
- **Binding (SF6b):** the right code for card A, sent with card B of the same peer but another participant or a new
  name, gives 400.
- **The rebuild (MF1):** for two participants of one peer, each contact's rebuilt card equals its imported card, and
  each lists its own code.
- A contact paired before this change lists a code, with `confirmed: false`.
- **Rollback (MF1):** main's `pair()` SQL (`INSERT INTO remote_contacts VALUES(?,?,?,?)`) still works on a store
  this branch opened. A re-pair under main that renames the participant (main's SQL, which leaves the confirmation
  alone) then lists that contact as `confirmed: false` (re-check SF1).
- A `code` that's an int, a list or null gives 400, not 500 (re-check SF2).
- The preview response holds no code: no field, and neither the 32-hex nor the grouped form is in the body (nit).
- `/api/connections/code` works for a non-admin participant, and gives 409 without an endpoint.

**Task 3: the CLI (__main__.py).** Tests in `tests/test_cli.py`:
- `card` prints the card on stdout, byte-for-byte as today, and the code on stderr.
- **No terminal (MF2a):** run under `subprocess(start_new_session=True, stdin=PIPE)` with the **right** code on stdin
  and a timeout. It exits 2 with the terminal message, and nothing is paired.
- **pty, stdin wrong, tty right (MF2b):** under `pty.fork`, the child `dup2`s a pipe holding a wrong code onto fd 0.
  The right code typed on the tty pairs.
- **pty, stdin right, tty wrong (MF2c):** it refuses, and nothing is paired.
- **Refused before asking (MF2d):** `--as` a non-admin or a pending account, under a pty, refuses, and the prompt
  never appears on the master.
- pty tests read the master until the prompt before writing, and treat EIO on the Linux master as end of output
  (nit).
- `connections --as` lists codes and "confirmed by typing", and refuses a non-admin.
- `pair` and `connections` on a data dir with no `identity.json` create none (SF2).
- A participant name holding ESC and a newline prints as one safe line (SF3).
- **Both sides (SF6a):** the code `card` prints on stderr, and `/api/connections/code`'s code, each equal the
  `pairing_code` the other side's `connections` lists after pairing with that card. This uses two data dirs, with the
  card passed as the file `card` wrote.

**Task 4: the browser (static/app.js).** Tests in `tests/test_browser.py`, whose fixture gains a configured endpoint
for the card tests (nit):
- "Show my peer card" shows the code outside the card's JSON, with its label.
- The pair form's code box is empty. Pressing "Pair this peer" with it empty or wrong shows the server's message and
  pairs nothing. After a mismatch the preview is cleared.
- The right code, typed with Enter, pairs. The typed text survives a re-render.
- The preview's DOM holds no code in either form (nit).
- The connection list shows each code and "confirmed by typing".

  Playwright's Chromium isn't installed on Tardis today, and all 103 browser tests failed there for that reason.
  Before Task 4, Tardis installs it with `uv run playwright install chromium`, into `~/.cache/ms-playwright`, so these
  run here before the Pi runs them.

**Task 5: docs.** PROTOCOL.md, API.md and CLAUDE.md, as above.

## Checks before review

- The whole peer suite, browser tests included, on Tardis.
- A by-hand pairing of two throwaway local peers (two data dirs on 127.0.0.1): `card` on one; `pair --as` on the
  other, with the code typed in a real terminal by the person running the check; then the same through the browser.
  It runs exactly as Andy will: `uv run python -m superyak_peer pair …` in an ordinary shell, and through any make
  target that wraps it. A launcher that moves the child into its own process group would trip the foreground check
  on the honest path (re-check SF3).
- Mutants, each of which should fail a test:
  - the code over the certificate alone;
  - the code read from stdin;
  - the route checking the code before `_admin`;
  - the preview leaking the code;
  - the confirmation storing the typed text;
  - `_admin` after the tty prompt.

## Risks

- **The browser pair flow changes for Andy.** He'll read the code on the other machine's screen and type it once per
  participant. That's the point: it's the review the fingerprint button only pretended to be.
- **Existing pairings stay valid** and get their code listed. Only "confirmed by typing" stays false until a re-pair,
  which a person may do at any time: the same trust material passes `pair()`'s 409 check.
- **`/dev/tty` behaves the same on macOS and Linux for this use.** The test without a terminal uses `setsid`
  semantics, which both have.
