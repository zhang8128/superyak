# Federation pull: a peer that never listens, and an outbox that doesn't give up

Tardis, 2026-10-27. **Revision 4, approved under station law section 3.**
- Revision 1 got REQUEST CHANGES from the first review ([review](../reviews/2026-10-27-federation-pull-review.md)).
- Revision 2 got REQUEST CHANGES from the second ([re-check](../reviews/2026-10-27-federation-pull-recheck.md)).
- Revision 3 got APPROVE WITH CHANGES from the third ([check 3](../reviews/2026-10-27-federation-pull-check3.md)).
  Its two must-fix items are applied here as written, which its verdict says needs no further round. Its seven
  should-fix items are applied too: SF1 and SF2 in §7, SF3 in §1 and §7, SF4 in §2, SF5 in §1, SF6 in §4, and SF7
  in §10.

Branch `tardis/federation-pull`, on 60dd851. Shaped in "Superyak: all hands" (a9221f76, 7338393b, d2960bd3, e54ba1eb,
59c43e5d and 1b83820e) and City of AI (c00dcc2d: the key binding goes first, as fix:pairing-code). Nothing here is
built.

| Re-check item | Where revision 3 answers it |
|---|---|
| MF1 no code on the exporting side | §2: `card` and "Show my peer card" print the code, and `connections` lists it |
| MF2 probe and selection undefined | §7: one outcome table for push and pull; mode and due-ness in the SQL before `LIMIT` |
| SF1 pinned certificates expire | §3: verify by the exact DER pin alone |
| SF2 a peer doesn't know its mode | §1: `federation_mode`, stored once |
| SF3 who acts and who confirms | §2: `--as`, an admin check, and Andy types the other side's code |
| SF4 participant not covered | §2: the code hashes the whole card |
| SF5 G4b | §1 and §3: both new commands refuse a lost identity |
| SF6 no pusher; units | §1 and §9: `federate` runs everywhere; one sync process per data directory; alerts and runbook |
| SF7 rollback | §9: keep pairings |
| SF8 unbounded gate | §4: the gate per row, and a cap on rows examined |
| SF9 destination | §4, check 2 |
| SF10 deadline | §5: a minimum rate |
| SF11 terminal 4xx | §7: terminal codes are named; everything else retries |
| SF12 tests | §10 |
| Nits 1-15 | in place, as noted |

## Why

Andy, 2026-10-27: "Remember this should be peer to peer as well." The ships agreed (d2960bd3) that lessons travel as
posts in a federated room, and that each peer answers its own sessions. Federation on main can't carry that between
our three machines yet:

1. **Push only.** `Federation.sync_once` POSTs each outbox row to the other peer's `/federation/events`. Nothing
   fetches. A peer that never listens can send but never receive. The Mac must not listen: law section 6 counts every
   listener, loopback included, while a browser lane runs, and approves no interpreter. It is also a laptop on
   conference Wi-Fi behind a relay.
2. **The outbox gives up after about four minutes.** Waits of 2, 4, … 128 s (`min(300, 2**(attempts+1))` before the
   increment, while `attempts<8`), about 254 s. After that a person has to retry.
3. **Nothing can be dialed yet.** The pinned dial checks the hostname against the certificate (`server_hostname=`),
   identities name only `localhost`, and the Pi's station serves behind `tailscale serve` without `--peer-tls`. The
   certificates also expire after 365 days and can't be replaced (PROTOCOL.md), so even a working dial would stop a
   year after each identity was made.

## Goals

1. A peer that never listens receives everything a listening peer would have pushed to it: the same signed envelopes,
   through the same `receive`.
2. No paired peer's delivery is lost to time. A row ends only when delivered, withdrawn (obsolete or unpaired), or
   refused for good by a named terminal code (§7).
3. Nothing on the wire changes for v1 peers: v1 cards, `/federation/events` and envelopes stay byte-identical.
   Retries, statuses, backoff, the pinned dial's checks and the pairing confirmation do change, and that is stated.

## Non-goals

Relays, NAT traversal, discovery, the lessons index (the first-rail spec), a web UI on a pull peer, and changing a
known identity's mode.

## 1. Processes and modes (M1, SF2, SF5, SF6)

- **`federation_mode`** is stored once in the store's meta: `pull`, or `push`.
  - The first `card --pull` sets `pull`. The first `card --endpoint` or `serve --federation-endpoint` sets `push`.
  - The other kind of command is refused after that, so one identity never exports both kinds of card.
  - `card --pull` refuses, unless the mode is already `pull`, an identity that existed before the command, or a store
    with any `peers` row. So a mistaken `card --pull` can never turn the Pi or Tardis into a pull peer (check 3 SF5).
- **"Check delivery now"** (`POST /api/sync` in `serve`) only makes every peer due and returns status. `sync_once`
  runs only in the process that holds `federation.lock` (check 3 SF3).
- **`python -m superyak_peer federate --data-dir D`** is the one sync process for a data directory, on every peer.
  - It has no listening socket.
  - Each pass runs `collect` and `sync_once`. On a pull peer it also runs `pull_once` for each paired push peer every
    60 s, and at once after starting, after a pass that succeeds following a failed one, and after a push to that peer
    succeeds.
  - Each pass catches and logs its own exceptions.
  - It holds `federation.lock` (an flock in the data directory) for its whole life, and `serve --sync` takes the same
    lock. A second sync process for one data directory exits with "another process already syncs this directory",
    so rows are never sent twice or backed off twice.
- **`federation-listen`**, on push peers only, is described in §3.
- **G4b:** both `federate` and `federation-listen` call `refuse_a_lost_identity_before_the_store` before loading the
  identity, as `serve --peer-tls` does, so a lost `identity.json` is never silently replaced.
- **The Mac's sessions reach their own peer in process,** through the store. A browser UI on the Mac's peer would need
  a listener, which is Andy's to approve under section 6, and is out of scope.
- `serve` gains no pull route (nit 7). The main app is public through Funnel on the Pi.

## 2. Cards and pairing (M2, M10, SF3, SF4, S11, nit 14)

- **A v2 card** has v1's keys with `endpoint: null`, plus `"delivery": "pull"`. Version 2 means pull, and there is no
  v2 push.
  - `validate_card` accepts v1 exactly as today, and v2 exactly as above.
  - `send_pinned` refuses a card without an endpoint before resolving anything.
- **The pairing code** is the first 32 hex characters of `sha256(canonical(card))`, the whole card, `participant`
  included, shown in groups of four. It is shown in every place a card leaves or arrives (MF1):
  - `card` and `card --pull` print the code to stderr, computed from the machine's own identity and account, so stdout
    stays a card.
  - "Show my peer card" in the browser shows it beside the card.
  - The importing side never shows the imported card's code before it is typed. It shows it in `connections` after
    pairing, and in the message when a typed code doesn't match (check 3 SF4).
  - `connections` lists each paired peer's code, for later checks.
- **Confirming a pairing is a person's act.**
  - `pair --card FILE --as USER` checks `USER` the way `Federation.pair` does (an admin, not pending activation).
  - It then asks for **the other side's code, typed in full**, not "yes", **read from `/dev/tty`**. It refuses when
    there is no terminal. A ship's Bash has none, so this gives section 7's "Andy, typing in a session's own terminal"
    a mechanism.
  - Andy reads that code on the exporting machine's own screen, so comparing only the first and last groups stops
    being possible.
  - The browser's pair form asks for the code the same way, and the server checks it.
    `POST /api/connections/pair` refuses a wrong code, and refuses a request carrying only the old `fingerprint`
    field. It stops echoing `fingerprint` (peer_routes.py:55-56).
  - CLAUDE.md gains the rule beside `station-approve`: pairing is Andy's act, and the code is his to type.
  - `connections --as USER` and `retry KEY --as USER` check what the browser routes check: admin, and the row's
    delivery authority.
- **The Mac's account:** Andy runs `init` on the Mac's data directory himself and types the password. Law section 7
  forbids a ship typing it.
- **`pair()`** compares the effective mode, `card.get('delivery', 'push')`, so a v1 prior card meets a v2 card with a
  409, not a `KeyError`. A known `peer_id` can't change mode. A pull peer is a new data directory with a new identity.
- **A pull peer refuses to pair a pull card,** since two pull peers can never reach each other.

## 3. The pinned dial, and the federation listener (SF1, SF5, nits 5, 6, 15)

- **Verify by the exact DER pin, nothing else.**
  - The pinned context uses `CERT_NONE` and TLS 1.3 at minimum, so there is no renegotiation.
  - After the handshake, and before any byte is written, the peer's DER certificate's SHA-256 must equal the card's
    `fingerprint`. Otherwise the outcome is `refused` (§7).
  - The TLS 1.3 handshake signature proves the peer holds the pinned certificate's key. The certificate's names and
    dates add nothing to an exact pin, and checking them is what made today's identities undialable by tailnet name,
    and would end every dial a year after an identity was made.
  - Identities and signatures stay as they are.
- **`federation-listen --data-dir D --host 127.0.0.1 --port 7437`:**
  - It serves only `/federation/events` and `/federation/pull`, over the identity's TLS files.
  - It refuses a host that isn't loopback, as `door` does.
  - It caps request bodies at 6 MiB for events and 16 KiB for pull.
  - It does no Host check, since its 403 would otherwise be terminal.
  - It runs on the Pi and Tardis, reached through a Tailscale TCP passthrough on the tailnet name, port 7437.
  - The Tailscale rule that limits shared users to port 443 stays, so 7437 is reachable only by Andy's machines.
  - Section 6 governs listeners on the Mac only.

## 4. The pull route (M3, M5, M6, M9, SF8, SF9, nits 1, 2, 13)

`POST /federation/pull`, on `federation-listen` only.

**Request:** canonical JSON with exactly these keys.

| Key | Rule |
|---|---|
| `version` | `1`, an `int` (`type(x) is int`, so a bool is refused) |
| `kind` | `"pull"`; mark `pull` reserved in identity.py's comment beside `RECORD_KEYS` |
| `origin` | the puller's `peer_id` |
| `destination` | this peer's `peer_id` |
| `nonce` | 32 lowercase hex characters |
| `at` | an `int` Unix time |
| `limit` | an `int` from 0 to 20; 0 means acks only |
| `budget` | an `int` number of encoded response bytes, from 65,536 to 6,291,456 (matching the transport cap, nit 2) |
| `ack` | at most 100 event ids, each matching the envelope's event id pattern |
| `refused` | at most 100 objects of exactly `{event_id, code}`, with `code` an `int` from 400 to 499 |
| `signature` | Ed25519 over the canonical request without `signature`, by the card's `signing_key` |

**Checks, in order:**
1. **Shape.** Any other key set is a 400, so no envelope or record body passes.
2. **Destination** equals this peer's `peer_id` (SF9). Otherwise 403 "not addressed to this peer". This is the
   defence against one listener replaying a puller's request at another.
3. **Origin** is a paired peer with a v2 card. Otherwise 403 "unknown or unpaired peer", or 403 "not a pull peer".
4. **Signature.** Otherwise 403.
5. **Clock:** `at` within 300 s. Otherwise 403 "clocks differ by more than 5 minutes".
6. **Nonce:** inserted under the primary key `(origin, nonce)`. If it is already there, 409 "replay". Rows older than
   600 s are pruned.
7. **Busy:** a per-origin lock. If a pull from this origin is already running, 409 "busy". Only a request that passed
   checks 4-6 can be busy, and there is no time spacing.

**Processing:**
1. Acks become `delivered`. Refusals become `refused`, with the code in the new column `outbox.last_error`
   (`metadata` is never written). Only rows of `origin`'s contacts, and only from `pending` or `failed`. Idempotent.
2. `collect()`.
3. Walk `origin`'s rows in `pending` or `failed`, ordered by `event_seq, id`, **examining at most 200 rows** per pull.
   Each row is prepared under its own hold of `dispatch_gate`, taken directly, never through a transaction (nit 1),
   exactly as push takes the gate per row (SF8).
4. Each row's local outcome follows §7's table. A `withdrawn` or `refused` mark is written in the same transaction as
   the check that decided it (check 3 SF6). A local outcome never stops the walk, and it never makes a 500.
5. Stop at `limit` envelopes, at `budget` encoded bytes, at 200 rows examined, or after about 5 s of walking
   (check 3 SF6). If nothing else is ready, one envelope over the budget is still sent, up to the transport cap, so a
   large row can't block the queue.

**Response:** `{"ok": true, "envelopes": [<canonical envelope text>, …], "more": <bool>}`. `more` is true when rows
remain beyond those examined, in `pending` or `failed` and not refused or withdrawn in this pass (nit 13). That
includes rows left because the walk stopped at 5 s.

**The pull boundary is per envelope (M3).** Each envelope's release is decided under the gate when it is prepared, as
push decides under the gate when it writes. A withdrawal committed before a row is prepared is honoured: that row
comes back withdrawn. A withdrawal committed after a row was prepared isn't recalled from this response, and it goes
out as the next pull's `room.withdraw`. PROTOCOL.md states this, and tests 8a and 8b pin both halves.

A row becomes `delivered` only when an ack names it. A lost response costs one duplicate, which `receive`'s receipts
absorb.

## 5. The pull transport (M4, SF10)

`pull_pinned(card, body)` uses §3's pinned TLS, with:
- path `/federation/pull`;
- a response cap of 6 MiB plus 64 KiB;
- `parse()` given an explicit size limit for this path only;
- a deadline of 10 s to the response headers, then a minimum rate of 64 KiB/s over the declared `Content-Length`.
  A 5.8 MB response gets about 100 s on a slow link, and a stalled one still ends.

The puller asks for a budget of 1 MiB.

## 6. The puller (S7, nit 3)

`pull_once(card)` keeps acks and refusals per listening peer until a request carrying them gets a 2xx.
- **Each returned envelope:**
  - If its `origin` isn't the peer pulled from, it is dropped.
  - Otherwise it goes to `receive()`. "ok" or "duplicate" is acked. Every 4xx `Problem` from `receive` is refused,
    except the peer-scoped answers listed in §7 (check 3 MF1). Anything else is neither, and it is offered again on
    the next pull.
- **A pin mismatch** on a pull is a peer failure, and `connections` shows "certificate differs" for that peer
  (check 3 SF1).
- **Rounds:** up to 10 while `more`, then `limit` 0 if acks remain.
- **Answers to the pull itself:**
  - 409 "busy": wait 5 s, then try once more.
  - 409 "replay": a new nonce at once.
  - 400: logged as a bug; acks are kept.
  - 403: logged with its wording and shown by `connections`, a clock warning separately.
  - 404: the peer has no pull route yet; wait 5 minutes.
- **Backoff for a pull target:** a 5xx or a network failure goes into the per-peer backoff, capped at 300 s for pulls
  (nit 9), because pulling is the Mac's only way to learn that a listener is back.

## 7. One outcome table for push and pull (M5, M7, M8, MF2, SF11, nits 4, 8, 12)

| Where | What happens | Row becomes | Peer |
|---|---|---|---|
| local | `_prepare` raises `Obsolete` | `withdrawn` | neutral |
| local | `_prepare` raises `sqlite3.OperationalError` (locked, busy, I/O, full; the nightly backup's lock on the Pi) | `failed` | neutral (check 3 SF2) |
| local | `_prepare` raises any other exception (413 and other local `Problem`s, `ValueError`, `KeyError`, `IntegrityError` …) | `refused`, `last_error` = code or class name | neutral |
| transport | the pin doesn't match | `failed`; `connections` shows "certificate differs" | failure (check 3 SF1) |
| peer | 2xx with `{"ok": true}` | `delivered` | reset |
| peer | a **peer-scoped** answer: any 5xx; a 2xx without `ok`, or one whose body `parse()` refuses, or a reply over 64 KiB; 401, 404, 408, 421, 425 and 429; 403 "Unknown or unpaired peer" and "Peer authentication failed"; 403 "Unrecognized host" and "Same-origin request required"; 403 "Federation requires HTTPS" | `failed` | failure |
| peer | **every other 4xx**: the peer answered about this row (for example 403 "Unknown remote participant", 409 "Revision already used", 400, 413) | `refused`, `last_error` = status and message | reset (check 3 MF1) |
| network | `OSError`, a timeout, or any `HTTPException` (`RemoteDisconnected`, `IncompleteRead` …) | `failed` | failure |

- **Neutral and row-scoped outcomes never block a peer.** The next row is tried at once, so neither a poison row nor
  a row the peer refuses can stall the queue behind it. The row's author can retry a `refused` row once its cause is
  fixed.
- **`transport.PeerAnswer(status, message)`** carries the real HTTP status and message, which is what tells a
  peer-scoped answer from a row-scoped one.
- **Per-peer backoff:** a table `peer_delivery(peer_id PRIMARY KEY, mode, failures, next_attempt, last_success,
  last_pull)`.
  - `mode` is copied from the card at pairing. `pair()` upserts the row on both of its paths, the new peer and the
    `ON CONFLICT` re-pair.
  - **Backfill at every start** (check 3 MF2), as db.py does for `inbox_received`:
    `INSERT OR IGNORE INTO peer_delivery(peer_id, mode, failures) SELECT peer_id,
    COALESCE(json_extract(card, '$.delivery'), 'push'), 0 FROM peers`. Pairings made before the upgrade, and
    stores restored from older backups, keep sending.
  - `sync_once` selects with mode and due-ness in the SQL `WHERE`, before `LIMIT`:
    `… JOIN peer_delivery USING(peer_id) WHERE status IN ('pending','failed') AND peer_delivery.mode = 'push' AND
    (peer_delivery.next_attempt IS NULL OR peer_delivery.next_attempt <= ?) ORDER BY event_seq, id LIMIT ?`.
    A pull peer's queue, or a peer in backoff, never fills the page that live peers need.
  - **Failure:** on a peer's first failure in a pass, `failures + 1`,
    `next_attempt = now + min(3600, 2**min(failures, 12))`, and that peer's other rows wait for the next pass.
  - **Reset:** `failures = 0` and `next_attempt = NULL`. Any reset outcome does it, and so does a successful pull from
    that peer, or a verified pull it makes here.
  - **`last_pull`** means "last pulled from it" on a pull peer, and "last pulled from us" on a listener (nit 10).
    Columns are updated one by one, since two processes can write the table.
- **The row-level `next_attempt` is no longer consulted.** It is cleared when a row is attempted, and `status()`
  reports the peer's `next_attempt` instead (re-check N8). Row `attempts` are still counted, for display only.
- `sync_once`'s result counts `refused` too (nit 4).
- **`retry(key)`** works on `failed` or `refused`, and makes the row's peer due.
- **"Check delivery now"** makes every peer due (nit 8), and never runs `sync_once` outside `federation.lock` (§1).
- **Tests that change:**
  - `test_offline_queue_stable_and_bounded`: still `failed == 1`, bounded per peer.
  - `test_exhausted_retry_keeps_event_id_and_rechecks_current_state`: becomes "a peer in backoff isn't dialed until
    due; `retry` makes it due; the event id and the re-check are unchanged".

## 8. Status and the web UI (S8, S9, nits 8, 12)

- `connections()` gains, per peer: mode, pairing code, `last_success`, `last_pull`, `failures`, `next_attempt`.
- **The listener's UI:**
  - Pairing asks for the code (§2).
  - A pull peer's card shows "Fetches from us" and its last pull.
  - Rows for a pull peer show "Waiting for pull".
  - `failed` reads "Retrying", with the peer's next attempt.
  - `refused` reads "Not delivered (code)", with Retry, and a refused reply no longer shows "Saved here"
    (app.js:487).
- A notice in Ops when a pull peer hasn't pulled for a day, or a push peer has failed for a day.

## 9. Deploy and rollback (SF6, SF7, nit 11)

- **Migrations:** `pull_nonces`, `peer_delivery`, `outbox.last_error` and the meta key `federation_mode`.
- **The Pi and Tardis:**
  - Two systemd user units with `MemoryMax`: `federation-listen`, and `federate` as the one sync process.
  - The Tailscale TCP passthrough on 7437.
  - Cards re-exported with `https://<tailnet name>:7437`; identities unchanged.
  - Both units are added to `ALERTED_SERVICES` (Makefile) and to the restore runbook's stop line
    (docs/station-restore.md), so neither writes into a database being restored.
- **The Mac:**
  - Andy runs `init` himself.
  - `card --pull` (mode `pull`).
  - Andy pairs both ways by typing codes.
  - `federate` runs as a LaunchAgent from the pinned runtime. Andy loads it himself: law section 7 says ships never
    load a launchd job.
- **Rollback:** keep the pairings (SF7). Main's `send_pinned` refuses a stored v2 card with a `Problem(400)`, so those
  rows go `failed`. After rolling forward, the pull takes `failed` rows, with no retry needed.
- **Docs:** PROTOCOL.md (cards, the pairing code, the pin-only dial, the pull wire, the per-envelope pull boundary,
  the outcome table, retries) and the peer README change in the same branch.

## 10. Tests first

1. Cards and pairing:
   - A v2 card validates. A v2 card with an endpoint, any v2 "push", and v3 are refused.
   - A v1 card is byte-identical through `validate_card`, `card` and `pair`.
   - A v1 prior card against a v2 card gives 409.
   - A pull peer refuses a pull card.
2. **The pairing code (MF1, SF4, check 3 SF4):**
   - The code `card --pull` prints equals the code `connections` lists after pairing.
   - Swapping `signing_key` changes it, and so does swapping `participant.id`.
   - `pair` refuses a mistyped code, and refuses to run without a terminal.
   - The browser route refuses a wrong code, and refuses a request carrying only the old `fingerprint` field.
   - A non-admin's `pair` and `connections` are refused, and `retry` by a non-author gives 404.
   - `card --pull` on an identity that already has `peers` rows is refused.
3. **Modes:**
   - `card --endpoint` after `card --pull` is refused, and the other way round.
   - A second sync process on one data directory exits.
4. **The pin (SF1, check 3 SF1):**
   - A real-HTTPS dial by tailnet name to a certificate that names only `localhost` works.
   - An expired pinned certificate still works, and so does a not-yet-valid one.
   - A different certificate, even one signed by the pinned key, is caught before any byte is written. On push and
     on pull, it is `failed` with a peer failure, and `connections` shows "certificate differs".
5. **Pull wire:**
   - A pull returns exactly the bytes push would have sent.
   - An ack delivers.
   - A lost response gives one duplicate.
   - `limit` 0 acks only.
   - A refusal sets `last_error` and leaves `metadata` unchanged.
6. **Refused requests:**
   - The wrong `destination`, before any nonce is stored (SF9).
   - A replayed nonce, a stale `at`, a bad signature, an unpaired origin and a push-mode origin.
   - A bool `limit`, an extra key, and envelope-shaped and record-shaped bodies.
   - An ack naming another peer's row changes nothing.
7. **Busy:** unverified requests never make the real origin busy, and the puller's own rounds never get 409.
8. **The boundary (SF12):**
   - 8a: a withdrawal committed while a pull is walking, before a row is prepared, makes that row come back withdrawn.
   - 8b: a withdrawal committed after a row was prepared arrives as the next pull's `room.withdraw`. A test hook
     between rows forces both interleavings.
9. **Bounds:**
   - 300 obsolete rows at the head of a pull peer's queue: the pull examines 200, `more` is true, and the gate is
     never held across rows. With a slow-commit hook, the walk stops at about 5 s, and `more` is true.
   - The minimum rate is injectable. A body sent faster than the rate arrives. A stall, headers then fewer bytes than
     the rate allows, ends by the scaled deadline. Both run on a small body in a few seconds.
10. **Starvation and outcomes (MF2, check 3 MF1, MF2, SF2, SF3):**
    - With 25 queued rows for a pull peer and 25 for a peer in backoff, both ahead of a live peer's row, the live row
      is delivered in one pass.
    - A first row whose `_prepare` raises `KeyError` doesn't put its peer in backoff, and the row behind it goes out.
    - One whose `_prepare` raises `sqlite3.OperationalError` stays `failed` and neutral.
    - A row answered 403 "Unknown remote participant" becomes `refused` without putting its peer in backoff, and the
      row behind it is delivered in the same pass.
    - On pull, a row whose `receive` gives that 403 comes back `refused` on the listener, and the next row arrives.
    - Peer-scoped answers are `failed`: 500, 502, 429, 403 "Unknown or unpaired peer", a 2xx whose body `parse()`
      refuses, `RemoteDisconnected` and `IncompleteRead`.
    - Row-scoped answers are `refused`: 400, 409 "Revision already used" and 413.
    - A store with a paired peer and a pending row, but no `peer_delivery` row, delivers that row after the store is
      reopened.
    - A `serve` without `--sync`, with `federate` holding the lock, never dials on "Check delivery now".
11. **`federate`:**
    - It survives an exception in `pull_once`.
    - It pulls at start and after a recovery.
    - It **never listens**: the test fails on any `bind` or `listen` during a pass.
12. **G4b (SF5):** `federate` and `federation-listen` refuse to start when `identity.json` is missing beside an existing
    store.
13. **`federation-listen`:**
    - It serves only the two routes; anything else is 404.
    - It refuses a host that isn't loopback.
    - It refuses a 6 MiB + 1 event body, and a 16 KiB + 1 pull body.

## Open questions

None for Andy. The ships agreed on a 60 s pull interval, with a pull at once after a wake, a network change or a push.
