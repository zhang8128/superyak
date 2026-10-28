# Plan: federation pull, a peer that never listens, and an outbox that doesn't give up

Tardis, 2026-10-28. **Revision 1, for a fresh reviewer** (law section 3 reviews specs; this plan goes to a fresh
reviewer too, as fix:pairing-code's did, and not to Serenity, whose queue holds four branches).

It implements the approved spec `docs/superpowers/specs/2026-10-27-federation-pull-design.md` (revision 4, this
branch) except §2's pairing code, which `tardis/pairing-code` (48981f67) built for v1 cards. Section numbers below
are the spec's. Where the spec leaves a choice open, the plan makes it, marks it **P1** to **P14**, and gives the
reason, so the reviewer can overrule any of them.

**This is safety code** (who a peer trusts, what leaves a station). It gets a test-first build and each partner's
explicit yes before it merges. Nothing pairs on the live station until pairing-code is merged; nothing pairs in pull
mode until this is.

## Base and order (P1)

- The build happens on this branch, `tardis/federation-pull`. Its first commit merges `tardis/pairing-code`, so the
  spec, its three reviews, this plan and the code travel together, and the branch can't merge before pairing-code.
- Agreed merge order: imprints, first-rail, pairing-code, then this. When pairing-code lands, this branch merges main
  and reruns everything.
- Today the live station has 0 `peers` rows (Rio Grande, read-only), and the Pi serves without `--peer-tls`. So no
  pairing, outbox row or federation unit has to be migrated, only the schema.

## What the code looks like today

- `transport.send_pinned` (97 lines) checks the hostname (`server_hostname=`, `PROTOCOL_TLS_CLIENT` with the card's
  certificate as its CA). It raises `Problem(403/409)` for every peer answer, so the HTTP status is lost, and it maps
  `HTTPException` to `Problem(409)`.
- `Federation.sync_once` selects `attempts<8 AND next_attempt<=?` rows, maps `OSError, ValueError, Problem` to
  `failed`, and backs off per row: `min(300, 2**(attempts+1))`, so a row stops after about 254 s.
- `_prepare` does every check and its one write (`UPDATE outbox SET envelope`) inside one `store.transaction()`, which
  takes `dispatch_gate` (an RLock plus an flock on `dispatch.lock`, re-entrant per thread). Every exception it raises
  comes before that write.
- There is no meta table, and nothing records a peer's delivery mode.
- `canonical()` is `json.dumps(sort_keys, separators, ensure_ascii=False)`. `parse()` has one fixed limit,
  `MAX_ENVELOPE`.
- Problems answer `{"error": message}`. So do the Host and same-origin middlewares (app.py:79 and :87).

## Decisions the spec leaves open

- **P2 A meta table.** `peer_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` in `PEER_SCHEMA`. It holds
  `federation_mode`, written with `INSERT` only, so a second write raises and nothing changes the mode.
- **P3 `peer_delivery.last_problem`.** Text, cleared on reset. §6 and §7 make `connections` show "certificate
  differs", a pull's 403 wording and a clock warning. The dial runs in `federate` and `connections` in another
  process, so the words need a column. It is the one column the spec doesn't list.
- **P4 The backoff schedule, computed.** On a peer failure, `failures` is incremented first, then
  `next_attempt = now + min(cap, 2**min(failures, 12))` uses the new value. On a listener, `cap` is 3,600 s: waits of
  2, 4, … 2,048 s (about 68 minutes in all), then hourly for good. On a pull peer, `cap` is 300 s for every dial it
  makes, pushes included: 2, 4, … 256 s, then every 5 minutes. A pull peer's pushes and pulls to one listener share
  that listener's one `peer_delivery` row, and §6 wants a pull at least every 300 s whatever pushes did. A successful
  pull resets the row, so pushes go again at once.
- **P5 An envelope too large to pull is refused where it waits.** The response carries envelopes as JSON strings, so
  each `"` and `\` in an envelope costs one more byte. A release body of 100,000 `"` characters adds about 200,000
  bytes. An envelope under `_prepare`'s 6 MiB limit could then make a response over the transport's 6 MiB + 64 KiB cap.
  Every pull would then fail at the transport, with that row at the head of the queue for good. So the listener
  measures each envelope's encoded form. If it alone can't fit within the cap less 1 KiB of frame, the row is
  `refused`, `last_error` = "413 Too large to pull". That's a local outcome, neutral, as in §7's table.
  - By our count, every envelope a receiver accepts fits: attachments are at most 4 MiB, or 5.6 MB as base64, which
    has no escapes. Task 6 tests that with the largest valid release rather than trusting the count.
- **P6 Nonces are pruned by the request's `at`, not by arrival.** A row goes once `at < now − 600`. A request with
  `at` 300 s in the future is valid until `at + 300`, so its nonce is kept while a replay could still pass check 5.
- **P7 A pull answered 400, 403 or 404 isn't a peer failure.** 400 and 403 are logged, and 403's wording is stored in
  `last_problem`; the next pull comes at the regular 60 s. 404 waits 5 minutes (§6). Only a 5xx, a network failure or
  a pin mismatch counts as a failure for P4.
- **P8 `card --pull` runs the G4b check too.** It is a new command path that makes an identity. A pull peer whose
  `identity.json` was lost must not get a new one silently, any more than `federate` may.
- **P9 Commands and modes.** `federation-listen` refuses unless the mode is `push`. `federate` runs in any mode, and
  pulls only when the mode is `pull`. Both refuse to start without `identity.json`, after G4b, and never make one.
- **P10 `retry KEY --as USER` is a new CLI command.** §2 names it, and it doesn't exist yet. It calls
  `Federation.retry` after the admin check, so a non-author gets 404.
- **P11 "Check delivery now" wakes the worker.** In a `serve --sync` process, which holds `federation.lock`, the POST
  makes every peer due and sets the worker's wake event. Without `--sync` it makes every peer due and returns status;
  it never dials.
- **P12 The puller stops its rounds when a round brings nothing new.** A round with no new ack and no new refusal ends
  the `more` loop. Otherwise an envelope the puller can neither ack nor refuse (§6, "neither") would keep `more` true,
  and spend 10 rounds every minute fetching it again.
- **P13 A wake is a wall-clock gap.** The open question settled on a pull at once after a wake, a network change or a
  push. `federate` treats a gap of more than 30 s beyond the pass interval between passes, measured with
  `time.time()`, as a wake and pulls at once. A network change is covered by the 60 s interval. No OS hook is added.
- **P14 Re-pairing makes a peer due.** `pair()` upserts `peer_delivery` on both paths. On the `ON CONFLICT` path it
  sets `failures = 0` and `next_attempt = NULL`, since a person just re-paired. `mode` never changes there, because a
  known peer can't change mode (§2).

## What changes

**identity.py**
- `validate_card` accepts v1 exactly as today, and v2 = v1's keys plus `delivery`, with `version` 2,
  `endpoint: null` and `delivery: "pull"`. Anything else is refused: a v2 card with an endpoint, a v2 "push", v3, a v1
  card with `delivery`, or a v1 card with a null endpoint.
- `PeerIdentity.card(endpoint, participant, *, delivery='push')`: `delivery='pull'` requires `endpoint is None` and
  builds v2. v1 bytes are unchanged.
- `sign_pull(request)` and `verify_pull(card, request)`. These are Ed25519 over the canonical request without
  `signature`. A bad signature raises `Problem(403, 'Peer authentication failed')`.
- The comment beside `RECORD_KEYS` reserves `pull` as a kind.
- `parse(raw, limit=MAX_ENVELOPE)`.

**peer_store.py and db.py**
- `PEER_SCHEMA` gains:
  - `peer_meta` (P2);
  - `pull_nonces(origin, nonce, at, PRIMARY KEY(origin, nonce))`;
  - `peer_delivery(peer_id PRIMARY KEY, mode, failures, next_attempt, last_success, last_pull, last_problem)`.
- `outbox.last_error TEXT` is added the way db.py adds user columns, guarded by `PRAGMA table_info`.
- The §7 backfill runs at every start, beside db.py's `inbox_received` backfill.
- `Store.station_notices()` (ships.py:418) gains the two notices from §8:
  - a pull peer that hasn't pulled for a day;
  - a push peer whose `failures > 0` and whose last success, or else its pairing confirmation, is over a day old.

**transport.py**
- **The pin-only dial (§3):**
  - `check_hostname = False`, `CERT_NONE` and TLS 1.3 at minimum.
  - After the handshake and before the gate is taken, the DER certificate's SHA-256 must equal the card's
    `fingerprint`, or the dial raises `PinMismatch`. It's caught before any byte is written.
  - SNI is still sent.
- `PeerAnswer(status, message)`:
  - For a non-2xx response, `message` is the body's `error` when the body parses, else `''`.
  - A 2xx without `ok: true`, a body `parse()` refuses, and a reply over 64 KiB each raise
    `PeerAnswer(status, 'Peer did not acknowledge delivery')`.
- `HTTPException` is no longer wrapped. It goes up to the outcome table as a network failure.
- `send_pinned` refuses a card without an endpoint before `resolve`.
- `pull_pinned(card, body, *, header_timeout=10, rate=65536)` (§5):
  - The path is `/federation/pull`, and the response cap is 6 MiB + 64 KiB.
  - It requires `Content-Length` and refuses one over the cap unread.
  - Its deadline is the headers' arrival plus `Content-Length / rate`, enforced by the same shutdown timer push uses.

**federation.py**
- `_prepare(key)` becomes a transaction around `_prepare_in(db, key)`, so the pull walk can write `withdrawn` or
  `refused` in the transaction that decided it (§4 step 4).
- `classify(exc)` returns the row status and the peer effect (neutral, failure or reset) from §7's table. Its inputs
  are `Obsolete`; a local exception, wrapped as `Local(exc)` by the prepare callback, so local and peer exceptions
  can't be confused; `PinMismatch`; `PeerAnswer`; and `OSError`, `TimeoutError` and `HTTPException`. Peer-scoped
  answers:
  - any 5xx, any 2xx `PeerAnswer`, and 401, 404, 408, 421 and 425;
  - 429;
  - 403 whose message is one of the five §7 names (exact strings, from federation.py, identity.py:202, app.py:79 and
    :87, and peer_routes.py);
  - any status outside 200-599, since there are no redirects.

  Every other 4xx is row-scoped: `refused`, `last_error` = `"<status> <message>"`. Any exception the table doesn't
  name is `failed` with a peer failure and is logged, so an unknown fault retries and is never terminal.
- `sync_once`:
  - It selects with §7's SQL, which has mode and due-ness before `LIMIT` and no `attempts<8`.
  - It marks each row from `classify`. On a peer's first failure in a pass it updates `peer_delivery` (P4) and skips
    that peer's other rows.
  - Delivered and row-scoped outcomes reset the peer.
  - It clears the row's `next_attempt`. It counts `refused`.
  - It runs only while this process holds `federation.lock`: `serve --sync`, or `federate`.
- `pair()`:
  - It compares the effective mode (`card.get('delivery', 'push')`) before `TRUST_KEYS`, so a mismatch is a 409 with
    no `KeyError`.
  - A pull peer pairing a pull card gets 400.
  - It upserts `peer_delivery` (P14).
- `serve_pull(raw)` (§4):
  - It runs checks 1-7 in order.
  - Then it processes: acks and refusals in one transaction; `collect()`; and the walk, of at most 200 rows, each
    under its own `with store.dispatch_gate:` hold, with the P5 refusal.
  - It stops at the limit, the budget, 200 rows or `pull_walk_seconds` (default 5). One over-budget envelope is
    allowed when the response is otherwise empty.
  - `more` is true when the origin's `pending` or `failed` count exceeds the envelopes returned.
  - It updates `last_pull` and resets the origin column by column.
  - The test hook `_between_rows` runs between rows.
- `pull_once(card, *, send=None)` (§6): acks and refusals kept per peer in memory, the origin check, `receive`, the
  peer-scoped exceptions, rounds (P12) and the answers to the pull itself (P7).
- `connections()` adds mode, `last_success`, `last_pull`, `failures`, `next_attempt` and `last_problem`. `status()`
  adds the peer's mode, `next_attempt` (the row's is no longer used) and `last_error`. `retry()` takes `failed` or
  `refused`, clears `last_error`, and makes the peer due.

**dispatch.py**
- `federation_lock(data_dir)` is an flock on `federation.lock` (`O_NOFOLLOW`, 0600, `LOCK_NB`). A second holder gets
  `ValueError("another process already syncs this directory")`.

**listener.py (new) and __main__.py**
- `create_listener(data_dir)` is a small ASGI app, in the door's style:
  - `POST /federation/events` goes to `receive`, capped at 6 MiB.
  - `POST /federation/pull` goes to `serve_pull`, capped at 16 KiB. The cap is read as the body streams, and a larger
    `Content-Length` is refused unread with 413.
  - Every other method and path is 404. There's no Host check.
- `federation-listen --data-dir --host --port 7437`:
  - It refuses a host that isn't loopback, and runs G4b.
  - It requires `identity.json` and push mode (P9).
  - It serves `uvicorn` with the identity's certificate and key, `access_log=False`.
- `federate --data-dir`:
  - It takes `federation_lock` first, then runs G4b and requires the identity.
  - A pass every 5 s runs `collect` and `sync_once`. In pull mode it also runs `pull_once` for each paired push peer
    that is due (60 s, the triggers in §1, P13), skipping peers in backoff.
  - Each step catches and logs its own exceptions. SIGTERM ends it between steps.
- `card --pull`: G4b (P8); refuses as §1 says; writes the mode; prints the v2 card on stdout and its code on stderr.
  `card --endpoint` and `serve --federation-endpoint` write `push`, or refuse when the mode is `pull`.
- `serve --sync` takes `federation_lock` before `uvicorn.run`, and exits 1 with the lock's message when it's taken.
- `retry KEY --as USER` (P10).
- `describe_connections` prints the new fields as one safe line per contact.

**static/app.js** (§8)
- The pair form is unchanged from pairing-code.
- A pull peer reads "Fetches from us", with its last pull. Its rows read "Waiting for pull".
- `failed` reads "Retrying", with the peer's next attempt.
- `refused` reads "Not delivered (code)", with Retry. The status label's fallback (app.js:489, `|| "Saved here"`) no
  longer turns an unknown status into "Saved here".

**Units, Makefile, docs**
- New units:
  - `peer/systemd/superyak-federate.service` (`MemoryMax=256M`);
  - `peer/systemd/superyak-federation-listen.service` (`MemoryMax=256M`, `127.0.0.1:7437`).
- Both units go in `STATION_UNITS` and `ALERTED_SERVICES`, and on the restore runbook's stop line
  (`docs/station-restore.md:64`).
- `peer/launchd/superyak-federate.plist`, a template that Andy loads himself.
- `test_restore`'s table list classifies:
  - `pull_nonces`: ephemeral, emptied on restore;
  - `peer_delivery`: coordination, kept, with the backfill covering older copies;
  - `peer_meta`: kept.
- PROTOCOL.md covers v2 cards, the pin-only dial, the pull wire, the per-envelope boundary, the outcome table and
  retries. The peer README and API.md cover the new fields, the commands and the Mac's steps.

## Tasks (test-first; each test is written and seen failing before its code)

Test numbers are §10's groups.

**Task 0: base.** Merge `tardis/pairing-code` into this branch. Record the whole peer suite's count on Tardis,
browser tests included, as the baseline.

**Task 1: cards and signatures** (`tests/test_identity.py`). Group 1:
- v2 validates, and its variants are refused.
- A v1 card is byte-identical through `validate_card`, `card` and `pair`.

Group 2's identity half: `pairing_code` of a v2 card changes with `signing_key`, and with `participant.id`. Also:
- A pull request's signature doesn't verify as an envelope's, and an envelope's doesn't verify as a pull's.
- `parse` honours `limit`.

**Task 2: schema, modes and pairing** (`tests/test_federation.py`, `tests/test_restore.py`):
- The mode is written once and refused twice.
- A v1 prior card against a v2 card gives 409. A pull peer refuses a pull card.
- `pair` upserts `peer_delivery` on both paths, and a re-pair makes the peer due (P14).
- Backfill: a store with a paired peer and a pending row, but no `peer_delivery` row, delivers it after reopening
  (group 10).
- **Rollback:** pairing-code's `pair()` SQL, `collect`'s outbox insert and `sync_once`'s update still run on a store
  this branch opened.
- The restore table list classifies the three new tables.

**Task 3: the pin and the transport** (`tests/test_transport.py`). Group 4:
- A dial by a tailnet-style name, with `resolve` mapped to 127.0.0.1, works against a certificate naming only
  `localhost`.
- An expired certificate works, and so does a not-yet-valid one. The test writes `identity.json` with such a
  certificate.
- A different leaf signed by the pinned key raises `PinMismatch`, and the server's socket records zero application
  bytes.

Group 9's rate half:
- With an injected rate, a body sent faster arrives.
- Headers followed by a stall end by the scaled deadline, on a small body, in a few seconds.
- A response over the cap is refused unread. A missing `Content-Length` is refused.
- `send_pinned` on a v2 card raises before `resolve` is called.

`PeerAnswer` carries the status and the `error` text.

**Task 4: one outcome table and per-peer backoff** (`tests/test_federation_outcomes.py`). Group 10 whole:
- Starvation (25 pull-peer rows and 25 backoff rows ahead of a live row).
- `KeyError` is neutral, and so is `OperationalError`.
- 403 "Unknown remote participant" is refused and resets the peer, and the next row goes in the same pass.
- The peer-scoped list and the row-scoped list.
- P4's schedule, checked against the formula for 13 consecutive failures on each cap.
- `retry` on `refused`.

The two §7 tests change as the spec says:
- `test_offline_queue_stable_and_bounded`;
- `test_exhausted_retry_keeps_event_id_and_rechecks_current_state`, renamed to "a peer in backoff isn't dialed until
  due".

Group 4's pin half: on push the outcome is `failed`, a peer failure, with "certificate differs" in `connections`.

**Task 5: the pull route** (`tests/test_federation_pull.py`, in process, with `send=` calling `serve_pull`).
- Groups 5, 6 and 7:
  - Exact bytes match push's; ack; a lost response gives one duplicate; `limit` 0.
  - A refusal sets `last_error` and leaves `metadata` alone.
  - The wrong destination is refused before any nonce row exists.
  - Every other refused shape. An ack naming another peer's row changes nothing.
- Busy: a forged request during a held pull gets 403, not 409. A second valid one gets 409.
- P6's boundary: `at` = now + 299, replayed at now + 598, gives 409 "replay".

**Task 6: boundary and bounds** (same file). Groups 8 and 9:
- 8a and 8b through `_between_rows`.
- 300 obsolete rows: 200 examined, `more` true, and the hook sees the gate's thread-local depth at 0 between rows.
- `pull_walk_seconds` = 0.3 with a hook sleeping 0.1 s stops early with `more` true.
- P5: the largest valid release (4 MiB of attachments, a 100,000-`"` body) pulls through the real transport. An
  envelope made over the pull cap by a test-only `_prepare_in` patch is `refused` "413 Too large to pull", and the row
  behind it arrives.

**Task 7: the puller** (same file):
- An envelope from another origin is dropped. `ok` and `duplicate` are acked.
- 403 "Unknown remote participant" from `receive` comes back `refused` on the listener, and the next row arrives.
- Peer-scoped answers are neither acked nor refused.
- Answers to the pull: busy retries once after 5 s, with an injected sleep. Replay retries with a new nonce. 400 keeps
  the acks. 403 stores its wording. 404 waits 5 minutes. A 5xx or `OSError` backs off within 300 s (P4, P7).
- The puller's own 10 rounds never get 409. P12 stops a loop that brings nothing new.
- A pin mismatch on a pull is a peer failure, with "certificate differs".

**Task 8: the processes** (`tests/test_cli.py`, `tests/test_listener.py`, `tests/test_federate.py`). Groups 2's CLI
half, 3, 11, 12 and 13:
- The code `card --pull` prints equals the code `connections` lists after pairing.
- `card --pull` on an identity with `peers` rows is refused, and so is `card --pull` after `card --endpoint`, and the
  other way round.
- `retry --as` by a non-author gives 404.
- A second sync process (`federate`, or `serve --sync`) exits.
- `federate` survives a `pull_once` exception and pulls at start and after a recovery. It never listens: `bind` and
  `listen` are patched to fail during a pass.
- G4b for both commands.
- `federation-listen` serves only its two routes, refuses a host that isn't loopback, and refuses 6 MiB + 1 and
  16 KiB + 1.
- A `serve` without `--sync`, with `federate` holding the lock, never dials on POST `/api/sync`.
- **End to end over real HTTPS:** two `federation-listen` servers on loopback and a pull peer in process. A room
  message reaches the pull peer by pull. Its reply reaches the listener by push. A withdrawal arrives on the next pull.

**Task 9: the browser and Ops** (`tests/test_browser.py`, `tests/test_ships.py`): §8's labels, and P5's and the
fallback's. The two notices appear after a day, using the clock fixture, and not before.

**Task 10: docs and units.** PROTOCOL.md, README, API.md, units, the plist template, the Makefile and the runbook.
`tests/test_station_units.py` checks the two new units are listed, alerted and on the stop line.

## Checks before review

- The whole peer suite on Tardis, browser tests included, against Task 0's baseline.
- The wheel builds and imports `listener.py` in a clean venv (`make peer-bundle`; packaging test). An editable
  checkout hides a missing module (lessons, tardis).
- Mutants, each of which should fail a test:
  - check 2 after the nonce insert;
  - busy taken before the signature;
  - nonces pruned by arrival with 300 s kept;
  - the gate held across the walk;
  - mode filtered after `LIMIT`;
  - a peer-scoped 403 classified as row-scoped;
  - a row-scoped 403 counted as a peer failure;
  - `check_hostname` back on;
  - `CERT_REQUIRED` with dates;
  - the pin compared after the write;
  - the backfill removed;
  - the puller acking a peer-scoped answer;
  - `federate` binding a socket;
  - P5's refusal removed;
  - `card --pull` skipping the `peers` check.
- **By hand, by Andy:** three throwaway data dirs on Tardis. The two listeners run `federation-listen` on loopback,
  and the third runs `card --pull` and `federate`. Andy pairs them both ways with `pair --as`, typing each code in a
  real terminal. A ship never types, relays or computes a code (CLAUDE.md).

## Deploy (each step is Andy's yes; nothing here runs on a merge alone)

1. The Pi and Tardis:
   - Andy runs `init` on Tardis's peer data directory himself; Tardis has none today.
   - `card --endpoint https://<tailnet name>:7437` re-exports each card; identities are unchanged.
   - `make station-units`, then the two units enabled.
   - `tailscale serve --tcp 7437 tcp://127.0.0.1:7437`, a passthrough, so the pinned certificate is the one served.
   - The rule limiting shared users to port 443 stays as it is.
2. The Mac: Andy runs `init`, then `card --pull`, pairs both ways by typing codes, and loads the LaunchAgent himself
   (law section 7: ships never load a launchd job).
3. Rollback keeps pairings (§9). Main's `send_pinned` refuses a stored v2 card with 400, so those rows go `failed`;
   after rolling forward, the pull takes `failed` rows. `refused` rows sit untouched under main, whose UI has no label
   for them (Risks).

## Risks

- **Rows never expire now.** A peer that's gone for good is dialed hourly until someone unpairs it, which withdraws
  its rows. That's goal 2, and the Ops notice after a day says so.
- **A pull peer's queue grows on the listener while the Mac sleeps.** It is bounded by what was shared with it, and
  shown as "Waiting for pull". Nothing is dropped.
- **An unrecognised 4xx is terminal until a retry.** With a TCP passthrough no HTTP proxy sits in between, so every
  4xx comes from a peer. If one ever doesn't, the author's Retry recovers the row.
- **Under a rollback, `refused` shows as "Saved here"** in main's UI (app.js:489). It is cosmetic, and a roll forward
  fixes it.
- **Two processes write `peer_delivery`** (`federate`, and the listener's `last_pull` and reset), so every update is
  one column at a time, under the gate's transaction.
