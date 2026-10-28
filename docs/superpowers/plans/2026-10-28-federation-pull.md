# Plan: federation pull, a peer that never listens, and an outbox that doesn't give up

Tardis, 2026-10-28. **Revision 2.**
- Revision 1 (b36f3e5b) got APPROVE WITH CHANGES from a fresh reviewer started on Tardis
  ([review](../reviews/2026-10-28-federation-pull-plan-review.md)).
- **Its three must-fix items are applied here as written** (MF1-MF3). Its verdict says that needs no further round
  before Task 0.
- Its fourteen should-fix items and 25 nits are applied too, each marked with its number. Where the review offered two
  fixes, the one taken is named: SF9 and SF13.
- Rio Grande's question in all hands (f653439a) adds one test and one label, marked **RG**: what a release's owner sees
  when P5 refuses it.

It implements the approved spec `docs/superpowers/specs/2026-10-27-federation-pull-design.md` (revision 4, this
branch) except §2's pairing code, which `tardis/pairing-code` (48981f67) built for v1 cards. Section numbers below
are the spec's. Where the spec leaves a choice open, the plan makes it, marks it **P1** to **P14**, and gives the
reason.

**This is safety code** (who a peer trusts, what leaves a station). It gets a test-first build and each partner's
explicit yes before it merges. Nothing pairs on the live station until pairing-code is merged; nothing pairs in pull
mode until this is.

## Base and order (P1)

- The build happens on this branch, `tardis/federation-pull`. Its first commit merges `tardis/pairing-code`, so the
  spec, its reviews, this plan and the code travel together, and the branch can't merge before pairing-code.
- Agreed merge order: imprints, first-rail, pairing-code, then this. When pairing-code lands, this branch merges main
  and reruns everything.
- Today the live station has 0 `peers` rows (Rio Grande, read-only), and the Pi serves without `--peer-tls`. So no
  pairing, outbox row or federation unit has to be migrated, only the schema.

## What the code looks like today

- `send_pinned` is 60 lines (transport.py:38-97) (nit 21). It checks the hostname (`server_hostname=`, with
  `PROTOCOL_TLS_CLIENT` and the card's certificate as its CA).
  - It compares the pin after the handshake, before the gate and the write.
  - It raises `Problem(403/409)` for every peer answer, so the HTTP status is lost.
  - It maps `HTTPException` to `Problem(409)`.
- `Federation.sync_once` selects `attempts<8 AND next_attempt<=?` rows. It maps `OSError, ValueError, Problem` to
  `failed`, and backs off per row with `min(300, 2**(attempts+1))`, so a row stops after about 254 s.
- `_prepare` does every check and its one write (`UPDATE outbox SET envelope`) inside one `store.transaction()`.
  - The transaction takes `dispatch_gate`: an RLock plus an flock on `dispatch.lock`, re-entrant per thread.
  - Every exception `_prepare` raises comes before that write.
- `system_meta(key, value)` exists (system_author.py:12), and the restore reconcile writes its mark there
  (backups.py:762-763). Nothing records a peer's delivery mode.
- `canonical()` is `json.dumps(sort_keys, separators, ensure_ascii=False)`. `parse()` has one fixed limit,
  `MAX_ENVELOPE`.
- Problems answer `{"error": message}`, and so do the Host and same-origin middlewares (app.py:79 and :87).
- `outbox.next_attempt` is `REAL NOT NULL DEFAULT 0` (peer_store.py:38).

## Decisions the spec leaves open

- **P2 A meta table of federation's own:** `peer_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` in `PEER_SCHEMA`.
  - It is separate from `system_meta` (nit 1). That table belongs to the system author, and the restore reconcile
    writes into it. `federation_mode` is copied as it is.
  - **Writing the mode (MF3):** `INSERT OR IGNORE INTO peer_meta VALUES('federation_mode', ?)`, then the value is read
    back in the same transaction.
    - The same mode is a no-op, so a re-export and every restart of `serve --federation-endpoint` succeed.
    - A different mode raises `ValueError` naming the stored mode.
- **P3 `peer_delivery` gains two columns the spec doesn't list:**
  - `last_problem`: §6 and §7 make `connections` show "certificate differs", a pull's 403 wording and a clock warning.
    The dial runs in `federate`, and `connections` runs in another process.
  - `failing_since` (nit 22): set when `failures` goes from 0 to 1, and cleared on reset. It makes the Ops notice mean
    "failed for a day", not "first failure after a quiet day".
- **P4 The backoff schedule, computed.**
  - On a peer failure, `failures` is incremented first. Then `next_attempt = now + min(cap, 2**min(failures, 12))`
    uses the new value.
  - On a listener, `cap` is 3,600 s: waits of 2, 4, … 2,048 s (4,094 s, about 68 minutes in all), then hourly for good.
  - On a pull peer, `cap` is 300 s: 2, 4, … 256 s (510 s), then every 5 minutes.
  - **The pull keeps its own due time (SF2).** A pull peer's pushes and pulls share one `peer_delivery` row per
    listener, but whether a pull is due is decided by `federate`'s memory, not by `next_attempt`:
    - it is due 60 s after the last pull, or at once on a trigger;
    - after a pull failure, its own 300 s backoff.

    A pull failure is also written to the row (§6: "goes into the per-peer backoff"). A push failure never is, so it
    can't postpone a pull. In pull mode each pass pulls before it pushes. A successful pull resets the row, and pushes
    go again at once.
- **P5 An envelope too large to pull is refused where it waits.**
  - **Why.** The response carries envelopes as JSON strings, so escaping grows them. An envelope under `_prepare`'s
    6 MiB limit could make a response over the transport's 6 MiB + 64 KiB cap. Every pull would then fail at the
    transport, with that row at the head of the queue for good.
  - **What the listener does.** It measures each envelope's encoded form. If that alone can't fit within the cap less
    1 KiB of frame, the row is `refused`, `last_error` = "413 Too large to pull". That is a local outcome, neutral, as
    in §7's table.
  - **What the owner sees (RG).** The refusal is written on the listener, where the release's owner is, so their
    delivery list shows it.
    - It reads "Too large to deliver by pull: make the release smaller", with no Retry, since a retry would be refused
      again.
    - The owner's next, smaller release is a new revision and goes as usual.
  - **The worst case, computed with the real limits (SF4):** 100 files totalling 4 MiB with 120-character names, a body
    of 100,000 U+0001 characters and a title of 200 U+0001 characters. Each control character costs 7 bytes in the
    response, against 4 for `"` or `\`. File names allow no escapes (files.py:46).
    - The envelope is 6,228,581 B, under `_prepare`'s 6,291,456.
    - The response is 6,331,282 B against the 6,356,992 B cap: a margin of 25,710 B (24,686 under the cap less 1 KiB).
    - So every envelope a receiver accepts fits, by about 25 KB.
  - **Keeping it true.** Task 6 tests exactly that release, and PROTOCOL.md carries these numbers, so any later change
    to the body, title or attachment limits has to revisit the cap.
- **P6 Nonces are pruned by the request's `at`, not by arrival.** A row goes once `at < now − 600`. A request with
  `at` 300 s in the future is valid until `at + 300`, so its nonce is kept while a replay could still pass check 5.
  The nonce commits at check 6, before the busy check (nit 7).
- **P7 Every answer to a pull (SF3, nit 7):**

  | Answer | Peer failure (P4)? | Next pull |
  |---|---|---|
  | 2xx with a valid body | no; it resets the row | at once while rounds go on, else 60 s |
  | A 5xx; any network failure; a pin mismatch; a 2xx `PeerAnswer` (no `ok`, a body `parse()` refuses); a missing or over-cap `Content-Length`; 401, 408, 421, 425 or 429 | yes | its own backoff, within 300 s |
  | A body shorter than its `Content-Length` (the deadline timer cut it short; `read` returns short at EOF and doesn't raise) | yes: raised as `TimeoutError` | its own backoff |
  | 409 "busy" | no | a new request (new nonce and `at`) after 5 s; a second "busy" waits 60 s |
  | 409 "replay" | no | a new request at once, once |
  | 403 | no; its wording is stored in `last_problem`, a clock warning separately | 60 s |
  | 404 | no | 5 minutes, kept in `federate`'s memory only: in `peer_delivery` it would also delay pushes to an older listener that just has no pull route |
  | 400, and any other 4xx | no; logged as a bug, acks kept | 60 s |
- **P8 Card commands never replace an identity (SF5).**
  - Only the first card command, with the mode unset, may create `identity.json`.
  - Once `federation_mode` is set, `card --pull` and `card --endpoint` require `identity.json` and never create one.
  - G4b also runs first. It refuses only when signed records exist, which a Mac usually has none of, so it can't be
    the guard by itself.
- **P9 Commands and modes.**
  - `federation-listen` refuses unless the mode is `push`.
  - `federate` runs in any mode, and pulls only when the mode is `pull`.
  - Both check that `peer.sqlite3` exists before touching the directory, so a mistyped `--data-dir` creates nothing
    (nit 18).
  - Both run G4b, require `identity.json`, and never make one.
- **P10 Two new CLI commands, so the Mac can see and retry its deliveries (SF14):**
  - `deliveries --as USER` prints `status()` as safe lines: id, status, `last_error` and the peer's `next_attempt`.
  - `retry KEY --as USER` calls `Federation.retry`.

  Both run after the admin check, and a non-author's `retry` gets 404.
- **P11 "Check delivery now" (SF8):**
  - In a `serve --sync` process, which holds `federation.lock`, the POST makes every peer due and wakes the worker. It
    then waits, for at most about 10 s, for the pass it woke to finish, and returns status, so the person sees fresh
    status.
  - Without `--sync`, it makes every peer due and returns status, and never dials.
  - The worker gets a `try` around each pass that logs and goes on (nit 9). Today one `OperationalError` ends it
    silently.
- **P12 When the puller stops its rounds (SF1):**
  - It ends the `more` loop only when a response carried envelopes and none of them gave a new ack or refusal: an
    envelope it can neither ack nor refuse (§6, "neither") won't spend 10 rounds a minute.
  - A response with no envelopes and `more: true` goes on, still bounded by 10 rounds. That's what a walk that stopped
    at 200 rows or 5 s returns.
  - Then `limit` 0 if acks remain (§6).
  - The request values are `limit` 20 and `budget` 1 MiB (§5) (nit 25).
  - Rounds delay that pass's pushes, which is accepted (nit 19). At worst, 10 rounds each take 5 s of walking plus
    1 MiB at the minimum rate, about 5 minutes on a slow link, once. The Mac's pushes are its own replies, and the
    queue is never lost.
- **P13 A wake is an overrun of the sleep (nit 8).**
  - `federate` measures `time.time()` from the end of one pass to the start of the next. An overrun of more than 30 s
    is treated as a wake, and it pulls at once.
  - It isn't measured start to start, or a pass with 10 slow rounds would read as a wake.
  - **A deviation from what the ships agreed:** "a pull at once after a network change" is dropped. A network change is
    covered by the 60 s interval, and no OS hook is added.
- **P14 Re-pairing makes a peer due.** `pair()` upserts `peer_delivery` on both paths. On the `ON CONFLICT` path it
  sets `failures = 0`, `next_attempt = NULL` and `failing_since = NULL`, since a person just re-paired. `mode` never
  changes there, because a known peer can't change mode (§2).

## What changes

**identity.py**
- `validate_card` accepts v1 exactly as today, and v2 = v1's keys plus `delivery`, with `version` 2,
  `endpoint: null` and `delivery: "pull"`.
  - Refused: a v2 card with an endpoint, a v2 "push", v3, a v1 card with `delivery`, and a v1 card with a null
    endpoint.
- `PeerIdentity.card(endpoint, participant, *, delivery='push')`: `delivery='pull'` requires `endpoint is None` and
  builds v2. v1 bytes are unchanged.
- `sign_pull(request)` and `verify_pull(card, request)`: Ed25519 over the canonical request without `signature`. A bad
  signature raises `Problem(403, 'Peer authentication failed')`.
- The comment beside `RECORD_KEYS` reserves `pull` as a kind.
- `parse(raw, limit=MAX_ENVELOPE)`.

**peer_store.py and db.py**
- `PEER_SCHEMA` gains three tables (nit 3):
  - `peer_meta` (P2);
  - `pull_nonces(origin TEXT NOT NULL, nonce TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY(origin, nonce))`;
  - `peer_delivery`, with these columns:
    - `peer_id TEXT PRIMARY KEY`;
    - `mode TEXT NOT NULL CHECK(mode IN ('push','pull'))`;
    - `failures INTEGER NOT NULL DEFAULT 0`;
    - `next_attempt REAL`, `last_success REAL`, `last_pull REAL` and `failing_since REAL`;
    - `last_problem TEXT`.
- `outbox.last_error TEXT` is added the way db.py adds user columns, guarded by `PRAGMA table_info`.
- The §7 backfill runs at every start, beside db.py's `inbox_received` backfill. It is guarded with
  `WHERE json_valid(card)`, since `json_extract` raises on a card that isn't JSON, and that would stop every `Store()`
  open (nit 4).
- `Store.station_notices()` (ships.py:418) gains the two notices from §8 (nit 22):
  - a pull peer whose last pull, or else its pairing confirmation, is over a day old;
  - a push peer whose `failing_since` is over a day old.

**transport.py**
- **One pinned dial for push and pull (MF1):** `_pinned_socket(card, deadline)` connects, completes the handshake
  and compares the pin. `send_pinned` and `pull_pinned` both use it, so neither can write a byte before the compare.
- **The pin-only dial (§3):**
  - `check_hostname = False`, `CERT_NONE` and TLS 1.3 at minimum. SNI is still sent.
  - The DER certificate's SHA-256 must equal the card's `fingerprint`, or the dial raises `PinMismatch`.
- **Exceptions (nit 5).** `PinMismatch(Exception)`, `PeerAnswer(Exception)` and federation's `Local(Exception)`
  subclass none of `OSError`, `Problem` and `HTTPException`.
  - `PeerAnswer(status, message)`, for a non-2xx response: `message` is the body's `error` when the body parses, else
    `''`.
  - A 2xx without `ok: true`, a body `parse()` refuses, and a reply over 64 KiB each raise
    `PeerAnswer(status, 'Peer did not acknowledge delivery')`.
  - `HTTPException` is no longer wrapped. It goes up as a network failure.
- **`send_pinned`'s own refusals (SF7)** raise `ValueError`, before any socket is opened: an invalid card, or a card
  without an endpoint. Local exceptions arrive wrapped in `Local`, so a bare `ValueError` can only come from here. It
  is classified as `failed` with a peer failure, and its message goes in `last_problem`.
- **`pull_pinned(card, body, *, header_timeout=10, rate=65536)` (§5):**
  - The path is `/federation/pull`, and the response cap is 6 MiB + 64 KiB.
  - It requires `Content-Length`, and refuses one that is missing or over the cap, unread.
  - Its deadline is the headers' arrival plus `Content-Length / rate`, enforced by the same shutdown timer push uses.
  - A body shorter than its declared length raises `TimeoutError` (SF3).

**federation.py**
- `_prepare(key)` becomes a transaction around `_prepare_in(db, key)`, so the pull walk can write `withdrawn` or
  `refused` in the transaction that decided it (§4 step 4).
- `classify(exc)` returns the row status and the peer effect (neutral, failure or reset) from §7's table.
  - Its inputs are:
    - `Obsolete`;
    - `Local(exc)`, a local exception wrapped by the prepare callback;
    - `PinMismatch` and `PeerAnswer`;
    - `ValueError`, from `send_pinned` (SF7);
    - `OSError`, `TimeoutError` and `HTTPException`.
  - **Row-scoped (nit 6):** every 4xx except the peer-scoped ones below. The row becomes `refused`, with `last_error` =
    `"<status> <message>"`.
  - **Peer-scoped:** everything else that isn't a 2xx with `ok`. That includes:
    - any 5xx, any 2xx `PeerAnswer` and any 3xx;
    - 401, 404, 408, 421, 425 and 429;
    - 403 whose message is one of the five §7 names. They are exact strings, at federation.py:343/347,
      identity.py:202, app.py:79 and :87, and peer_routes.py:85.
  - Any exception the table doesn't name is `failed` with a peer failure, and is logged. So an unknown fault retries,
    and is never terminal.
- **In-process senders (SF7).** `sync_once` and `pull_once` convert a `Problem` raised by a `send=` hook into
  `PeerAnswer(status, message)`. That's how `deliver()` (test_federation.py:25-26), test_browser and two_peer_check
  pass `receive`'s answers. In-process tests then take the same path as HTTP.
- **`_reply` (SF13; of the review's two fixes, the first).** For a room the receiver no longer has, it raises
  `403 'Room recipient or epoch changed'` instead of `require`'s 404 (federation.py:459). That makes the answer
  row-scoped, so one such reply can't stall push for good, or come back on every pull.
- `sync_once`:
  - It selects with §7's SQL: mode and due-ness come before `LIMIT`, and there is no `attempts<8`.
  - It marks each row from `classify`. On a peer's first failure in a pass it updates `peer_delivery` (P4), and skips
    that peer's other rows.
  - Delivered and row-scoped outcomes reset the peer.
  - It sets the row's `next_attempt` to 0, since that column is `NOT NULL` (nit 2), and counts `refused`.
  - It runs only while this process holds `federation.lock`: `serve --sync`, or `federate`.
- `pair()`:
  - It compares the effective mode (`card.get('delivery', 'push')`) before `TRUST_KEYS`, so a mismatch is a 409 with
    no `KeyError`.
  - A pull peer pairing a pull card gets 400.
  - It upserts `peer_delivery` (P14).
- **`serve_pull(raw)` (§4), the checks:**
  - It runs checks 1-7 in order, and the nonce commits before the busy check.
  - Check 1 accepts `ack` and `refused` event ids only as 32 lowercase hex. They name the listener's own rows, which
    `uid()` makes, so a maximal request is 9,794 B, under the 16 KiB cap (nit 17).
- **`serve_pull`, the processing:**
  - Acks and refusals are applied in one transaction, then `collect()` runs, then the walk.
  - **The walk.** It covers only the origin's rows (MF2), at most 200 of them. Each row is prepared under its own
    `with store.dispatch_gate:` hold, with the P5 refusal.
    - `OperationalError` leaves the row as it is, both still retried, and nothing is written in the transaction that
      raised it (nit 24).
  - **Stopping.** The walk stops at the limit, the budget, 200 rows or `pull_walk_seconds` (default 5). One
    over-budget envelope is allowed when the response is otherwise empty.
  - **`more`** is true when the origin's `pending` or `failed` count exceeds the envelopes returned.
  - It updates `last_pull` and resets the origin, column by column. The test hook `_between_rows` runs between rows.
- **`pull_once(card, *, send=None)` (§6):**
  - Acks and refusals are kept per peer in memory.
  - Origin check: an envelope string that doesn't parse goes to `receive`, which refuses it with 400. It isn't dropped,
    because its origin can't be read (nit 23). One that parses with another origin is dropped and logged.
  - Then `receive`, with the peer-scoped exceptions.
  - Rounds follow P12, and the answers to the pull itself follow P7.
- **Status, retry and connections:**
  - `connections()` adds mode, `last_success`, `last_pull`, `failures`, `next_attempt`, `failing_since` and
    `last_problem`.
  - `status()` adds the peer's mode, the peer's `next_attempt` (the row's is no longer used) and `last_error`.
  - `retry()` takes `failed` or `refused`, clears `last_error`, and makes the peer due.

**dispatch.py**
- `federation_lock(data_dir)` is an flock on `federation.lock` (`O_NOFOLLOW`, 0600, `LOCK_NB`). A second holder gets
  `ValueError("another process already syncs this directory")`.

**listener.py (new) and __main__.py**
- **`create_listener(data_dir)`** is a small ASGI app, in the door's style:
  - `POST /federation/events` goes to `receive`, capped at 6 MiB.
  - `POST /federation/pull` goes to `serve_pull`, capped at 16 KiB.
  - The caps are read as the body streams. A larger `Content-Length` is refused unread with 413.
  - Both handlers run in a worker thread, so a 5 s walk doesn't block pushes, and "busy" can happen (nit 11).
  - Every other method and path is 404. There is no Host check.
- **`federation-listen --data-dir --host --port 7437`:**
  - P9's checks, and it refuses a host that isn't loopback.
  - It serves `uvicorn` with the identity's certificate and key, `access_log=False`.
- **`federate --data-dir`:**
  - P9's checks, then `federation_lock`.
  - A pass every 5 s. In pull mode, it first runs `pull_once` for each paired push peer whose pull is due (P4, P7,
    P13), then `collect` and `sync_once`.
  - Each step catches and logs its own exceptions. SIGTERM ends it between steps.
- **Card commands.**
  - `card --pull`: G4b and P8; refuses as §1 says; writes the mode (P2); prints the v2 card on stdout and its code on
    stderr.
  - `card --endpoint` and `serve --federation-endpoint` write `push` the same way, and refuse when the mode is `pull`.
  - `pair_command`'s prompt says "fetches from us" for a v2 card's null endpoint (nit 14).
- **Other commands.**
  - `serve --sync` takes `federation_lock` before `uvicorn.run`, and exits 1 with the lock's message when it's taken.
  - `deliveries --as USER` and `retry KEY --as USER` (P10).
  - `describe_connections` prints the new fields as one safe line per contact.

**static/app.js** (§8)
- The pair preview says "fetches from us" for a v2 card's null endpoint (nit 14).
- A pull peer reads "Fetches from us", with its last pull. Its rows read "Waiting for pull".
- `failed` reads "Retrying", with the peer's next attempt.
- `refused` reads "Not delivered (code)", with Retry.
- "413 Too large to pull" reads "Too large to deliver by pull: make the release smaller", with no Retry (RG).
- The status label's fallback (app.js:489, `|| "Saved here"`) no longer turns an unknown status into "Saved here".

**scripts/two_peer_check.py (SF8)**
- It serves with `--sync` (:141, :214), so its `POST /api/sync` checks (:234-300) still deliver under P11.
- With A's own worker running, the lost-ack check (:310-315) races it: the worker can deliver "lost-ack" before the
  checker's `sync_once(send=lose_ack)` does. The checker stops A first and queues that message itself. A failed
  delivery's backoff must also outlast the restarts (:290, :319), or the worker retries before the checker's Retry
  (Tardis, Task 8e).

**pyproject.toml and the packaging test (SF12)**
- `listener.py` goes in both the sdist and the wheel inventories.
- The new tests, the two units and the plist go in the sdist, which `make peer-bundle` shares.
- `tests/test_packaging.py` imports `superyak_peer.listener` explicitly, since `__main__` imports it lazily.

**Units and Makefile (SF10, SF11)**
- `peer/systemd/superyak-federate.service` and `peer/systemd/superyak-federation-listen.service`, each with
  `MemoryMax=256M`.
  - Their `ExecStart` takes `--data-dir ${FEDERATION_DATA}`. The unit's default is
    `Environment=FEDERATION_DATA=%h/.local/share/superyak/lighthouse`, the station's directory, as the other units use.
  - The listener binds `127.0.0.1:7437`.
- A new `make federation-units FEDERATION_DATA=<dir>` installs only the two units, their alert drop-in, and a drop-in
  setting `FEDERATION_DATA`.
  - It is separate from `station-units`, which on Tardis would turn on the Pi's nightly backups and restore tests.
  - Both units go in `ALERTED_SERVICES`.
- `peer/launchd/superyak-federate.plist`, a template that Andy loads himself.

**docs/station-restore.md (SF10)**
- Both units go on the disable loop (:63) and the stop line (:64). Otherwise a reboot mid-restore would start them
  writing into a half-restored database.
- Step 8 enables them with `enable --now`, after the lighthouse, and its `is-active` check lists them (:195).

**Restore classification (SF9; of the review's two fixes, the second)**
- `pull_nonces`, `peer_delivery` and `peer_meta` go in `COORDINATION_TABLES` (test_restore.py:1387-1398): copied as
  they are, with no backups.py change.
- A restored set of nonces is pruned by `at` on the next pull, and a restore takes longer than the 300 s replay window.

**Docs**
- PROTOCOL.md covers v2 cards, the pin-only dial, the pull wire, the per-envelope boundary, the outcome table, retries
  and P5's numbers.
- The peer README and API.md cover the new fields and commands, and the Mac's steps.

## Tests that change

| Test | Change |
|---|---|
| `test_offline_queue_stable_and_bounded` | still `failed == 1`; bounded per peer (§7) |
| `test_exhausted_retry_keeps_event_id_and_rechecks_current_state` | renamed "a peer in backoff isn't dialed until due; `retry` makes it due" (§7) |
| `test_exact_pin_…` | `match='fingerprint differs'` (:233) becomes `PinMismatch` (nit 5) |
| `test_real_https_delivery_…` | `raises((OSError, Problem))` (:60-61) becomes `PinMismatch` (nit 5) |
| `test_trickling_…` | :178: a short body becomes `TimeoutError` (nit 5, SF3) |
| `test_delivery_waiting_acknowledgement_refresh_and_unsaved_state` | uses a sync-enabled app (test_browser.py:53); asserts "Retrying" where it asserted the failed label (SF8) |
| `deliver()` users in test_federation.py | `Problem` from `send=` becomes `PeerAnswer` (SF7); a peer-scoped answer now backs the peer off, so any test with one before more `deliver()` calls makes the peer due again |

## Tasks (test-first; each test is written and seen failing before its code)

Test numbers are §10's groups.

**Task 0: base.** Merge `tardis/pairing-code` into this branch. Record the whole peer suite's count on Tardis,
browser tests included, as the baseline.
- Done at bf16415e: 1,258 passed and 1 skipped, in 44:37 on Tardis.
- The skip is `test_station_units.py:73`, which needs the station host's runtime.

**Task 1: cards and signatures** (`tests/test_identity.py`). Group 1:
- v2 validates, and its variants are refused.
- A v1 card is byte-identical through `validate_card`, `card` and `pair`.

Group 2's identity half: `pairing_code` of a v2 card changes with `signing_key`, and with `participant.id`. Also:
- A pull request's signature doesn't verify as an envelope's, and an envelope's doesn't verify as a pull's.
- `parse` honours `limit`.

**Task 2: schema, modes and pairing** (`tests/test_federation.py`, `tests/test_restore.py`):
- **The mode (MF3):**
  - `card --endpoint` twice, `card --pull` twice (the second after pairing), and two starts of
    `serve --federation-endpoint` all succeed.
  - Each cross-mode case is refused with the stored mode named.
- A v1 prior card against a v2 card gives 409. A pull peer refuses a pull card.
- `pair` upserts `peer_delivery` on both paths, and a re-pair makes the peer due (P14).
- **Backfill:**
  - A store with a paired peer and a pending row, but no `peer_delivery` row, delivers it after reopening (group 10).
  - A store whose `peers` holds a card that isn't JSON still opens (nit 4).
- **Rollback:** pairing-code's `pair()` SQL, `collect`'s outbox insert and `sync_once`'s update still run on a store
  this branch opened.
- The three new tables are listed in `COORDINATION_TABLES` (SF9).

**Task 3: the pin and the transport** (`tests/test_transport.py`). Group 4:
- A dial by a tailnet-style name, with `resolve` mapped to 127.0.0.1, works against a certificate naming only
  `localhost`.
- An expired certificate works, and so does a not-yet-valid one. The test writes `identity.json` with such a
  certificate.
- **Zero bytes before the pin (MF1).** Parametrized over `send_pinned` and `pull_pinned`: a different leaf signed by
  the pinned key raises `PinMismatch`, and the server's socket records zero application bytes.

Group 9's rate half:
- With an injected rate, a body sent faster arrives.
- Headers followed by a stall end by the scaled deadline, on a small body, in a few seconds, as `TimeoutError` (SF3).
- A response over the cap is refused unread. A missing `Content-Length` is refused.

`send_pinned` with a v2 card or an invalid card raises `ValueError` before `resolve` is called (SF7). `PeerAnswer`
carries the status and the `error` text.

**Task 4: one outcome table and per-peer backoff** (`tests/test_federation_outcomes.py`). Group 10 whole:
- Starvation: 25 pull-peer rows and 25 backoff rows ahead of a live row.
- `KeyError` is neutral, and so is `OperationalError`.
- 403 "Unknown remote participant" is refused and resets the peer, and the next row goes in the same pass, through
  `send=` (SF7).
- Parametrized over every listed status and all five 403 strings, so dropping one is caught (nit 13): the
  peer-scoped list is `failed`, and 400, 409 "Revision already used" and 413 are `refused`.
- A 3xx is peer-scoped (nit 6).
- **A reply to a missing room (SF13)** is refused, and the row behind it is delivered.
- P4's schedule, against hard-coded lists for 13 consecutive failures (nit 12):
  - `[2,4,8,16,32,64,128,256,512,1024,2048,3600,3600]`;
  - `[2,4,8,16,32,64,128,256,300,300,300,300,300]`.
- `retry` on `refused`.
- The tests in "Tests that change".
- Group 4's pin half: on push the outcome is `failed`, a peer failure, with "certificate differs" in `connections`.

**Task 5: the pull route** (`tests/test_federation_pull.py`, in process, with `send=` calling `serve_pull`). Groups
5, 6 and 7:
- Exact bytes match push's; ack; a lost response gives one duplicate; `limit` 0.
- A refusal sets `last_error` and leaves `metadata` alone.
- The wrong destination is refused before any nonce row exists.
- Every other refused shape, including an `ack` id that isn't 32 hex (nit 17). An ack naming another peer's row
  changes nothing.
- **Only the origin's rows (MF2).** A listener holds rows for two pull peers and one push peer:
  - each puller gets only envelopes addressed to it;
  - `more` counts only its own rows;
  - neither puller's walk touches the push peer's rows.
- Busy: a forged request during a held pull gets 403, not 409. A second valid one gets 409.
- P6's boundary: `at` = now + 299, replayed at now + 598, gives 409 "replay".
- **The listener (nit 20):** a request with any `Host` header is served, and `serve`'s app has no `/federation/pull`.

**Task 6: boundary and bounds** (same file). Groups 8 and 9:
- 8a and 8b through `_between_rows`.
- 300 obsolete rows: 200 examined, `more` true, and the hook sees the gate's thread-local depth at 0 between rows.
- `pull_walk_seconds` = 0.3, with a hook sleeping 0.1 s, stops early with `more` true.
- **P5, through the real transport:**
  - The worst valid release (SF4) pulls through: 4 MiB of attachments with 120-character names, and a body of
    100,000 U+0001 characters with a title of 200.
  - An envelope made over the pull cap by a test-only `_prepare_in` patch is `refused` "413 Too large to pull", and
    the row behind it arrives in the same pull.
  - **What the owner sees (RG):** `status()` shows that row to its owner as `refused` with that `last_error`, and the
    browser shows "Too large to deliver by pull" with no Retry.

**Task 7: the puller** (same file):
- An envelope from another origin is dropped. One that doesn't parse goes to `receive` and is refused 400 (nit 23).
  `ok` and `duplicate` are acked.
- 403 "Unknown remote participant" from `receive` comes back `refused` on the listener, and the next row arrives.
- Peer-scoped answers are neither acked nor refused.
- Every row of P7's table, with an injected sleep and clock.
  - A busy retry carries a new nonce. A second busy waits 60 s.
  - The 404's 5 minutes leave `peer_delivery` untouched.
- **Rounds (SF1, P12):**
  - 300 obsolete rows then one live row are all pulled in one `pull_once`.
  - The puller's own rounds never get 409.
  - A loop that brings nothing new stops.
  - `limit` 0 is sent when acks remain (nit 20).
- A pin mismatch on a pull is a peer failure, with "certificate differs".
- **Push can't starve pull (SF2):** a listener whose events route answers 500 is still pulled within 300 s, and its
  envelopes arrive.

**Task 8: the processes** (`tests/test_cli.py`, `tests/test_listener.py`, `tests/test_federate.py`). Groups 2's CLI
half, 3, 11, 12 and 13:
- The code `card --pull` prints equals the code `connections` lists after pairing.
- **The peers check (SF6).** A store is paired through `pair` before any card exists, so it has a `peers` row, no
  `identity.json` and no mode. `card --pull` is refused there.
- `card --pull` after `card --endpoint` is refused, and so is the other way round.
- **A lost identity (SF5).** On a pull peer with `peers` rows, `identity.json` is deleted. `card --pull` is refused,
  and no `identity.json` appears.
- `deliveries --as` lists a refused row with its `last_error`. `retry --as` by a non-author gives 404 (P10).
- A second sync process exits, whether it is `federate` or `serve --sync`.
- `federate`:
  - survives a `pull_once` exception;
  - pulls at start, after a recovery and after a sleep overrun (P13);
  - never listens: `bind` and `listen` are patched to fail during a pass;
  - creates nothing in a directory without `peer.sqlite3` (nit 18).
- G4b for both commands.
- `federation-listen` serves only its two routes, refuses a host that isn't loopback, and refuses 6 MiB + 1 and
  16 KiB + 1.
- A `serve` without `--sync`, with `federate` holding the lock, never dials on POST `/api/sync`.
- With `--sync`, the POST returns status after the pass it woke (SF8).
- **End to end over real HTTPS:** two `federation-listen` servers on loopback and a pull peer in process.
  - A room message reaches the pull peer by pull.
  - Its reply reaches the listener by push.
  - A withdrawal arrives on the next pull.

**Task 9: the browser and Ops** (`tests/test_browser.py`, `tests/test_ships.py`):
- §8's labels, RG's label, "fetches from us" in the preview, and the fallback.
- `connections()`'s new fields, shown (nit 20).
- The two notices appear after a day of `failing_since`, or of no pull, using the clock fixture. They don't appear
  before, and not on a first failure after a quiet day (nit 22).

**Task 10: docs, units and packaging:**
- PROTOCOL.md, README and API.md.
- The units, the plist template, `federation-units`, `ALERTED_SERVICES` and the runbook's lines.
- `pyproject.toml` and two_peer_check.py.
- `tests/test_station_units.py` checks that the two units are listed and alerted, and are on the runbook's disable
  line, stop line, step 8 and `is-active` check (SF10).

## Checks before review

- The whole peer suite on Tardis, browser tests included, against Task 0's baseline.
- The wheel builds and imports `superyak_peer.listener` in a clean venv (`make peer-bundle`, and the packaging test,
  SF12). An editable checkout hides a missing module (lessons, tardis).
- **Mutants**, each of which should fail a test:
  - check 2 after the nonce insert;
  - busy taken before the signature;
  - nonces pruned by arrival with 300 s kept;
  - the gate held across the walk;
  - mode filtered after `LIMIT`;
  - a peer-scoped 403 classified as row-scoped;
  - a row-scoped 403 counted as a peer failure;
  - `check_hostname` back on;
  - `CERT_REQUIRED` with dates;
  - `send_pinned` writing before the pin compare;
  - **`pull_pinned` writing the request before the pin compare** (MF1);
  - **the walk without the origin predicate** (MF2);
  - **the mode written with a plain `INSERT`** (MF3);
  - the backfill removed;
  - the puller acking a peer-scoped answer;
  - `federate` binding a socket;
  - P5's refusal removed;
  - `card --pull` skipping the `peers` check (SF6);
  - `card --pull` creating an identity once the mode is set (SF5);
  - a push failure postponing the pull (SF2);
  - P12 stopping on an empty response with `more` (SF1);
  - `_reply` answering 404 for a missing room (SF13).
- **By hand, by Andy:** three throwaway data dirs on Tardis.
  - The two listeners run `federation-listen` on loopback. The third runs `card --pull` and `federate`.
  - Andy pairs them both ways with `pair --as`, typing each code in a real terminal.
  - A ship never types, relays or computes a code (CLAUDE.md).

## Deploy (each step is Andy's yes; nothing here runs on a merge alone)

1. **The Pi and Tardis:**
   - Andy runs `init` on Tardis's peer data directory himself; Tardis has none today.
   - Rio Grande checks that the Pi's lighthouse unit has no `--sync`. Otherwise whichever of it and `federate` starts
     second exits 1 (nit 16).
   - **Andy runs `card --endpoint https://<tailnet name>:7437`** on each machine (nit 15). Its stderr carries the code
     he will type on the Mac, and a ship never sees a code. Identities are unchanged.
   - `make federation-units FEDERATION_DATA=<dir>` on each machine, then the two units enabled (SF11).
   - `tailscale serve --tcp 7437 tcp://127.0.0.1:7437`, a passthrough, so the pinned certificate is the one served.
     The rule limiting shared users to port 443 stays as it is.
2. **The Mac:** Andy runs `init`, then `card --pull`, pairs both ways by typing codes, and loads the LaunchAgent himself
   (law section 7: ships never load a launchd job).
3. **Rollback:**
   - First disable and stop both units (nit 10). Main has neither command, and both units are alerted, so they would
     crash-loop into Ops.
   - Pairings are kept (§9). Main's `send_pinned` refuses a stored v2 card with 400, so those rows go `failed`. After
     rolling forward, the pull takes `failed` rows.
   - `refused` rows sit untouched under main, whose UI has no label for them (Risks).

## Risks

- **Rows never expire now.** A peer that's gone for good is dialed hourly until someone unpairs it, which withdraws
  its rows. That's goal 2, and the Ops notice after a day of failing says so.
- **A pull peer's queue grows on the listener while the Mac sleeps.** It is bounded by what was shared with it, and
  shown as "Waiting for pull". Nothing is dropped.
- **An unrecognised 4xx is terminal until a retry.** With a TCP passthrough no HTTP proxy sits in between, so every
  4xx comes from a peer. If one ever doesn't, the author's Retry, or `retry --as` on the Mac, recovers the row.
- **P5's margin is about 25 KB.** A change to the body, title or attachment limits could break it, which is why
  Task 6 tests the worst case exactly and PROTOCOL.md carries the numbers.
- **Under a rollback, `refused` shows as "Saved here"** in main's UI (app.js:489). It is cosmetic, and a roll forward
  fixes it.
- **Two processes write `peer_delivery`** (`federate`, and the listener's `last_pull` and reset), so every update is
  one column at a time, under the gate's transaction.
