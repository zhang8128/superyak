# Federation pull: a peer that never listens, and an outbox that doesn't give up

Tardis, 2026-10-27. **Revision 2**, after a fresh review of revision 1 (REQUEST CHANGES: 10 must-fix, 15 should-fix,
9 nits; [the review](../reviews/2026-10-27-federation-pull-review.md)). It goes to a second fresh reviewer under station
law section 3. Branch `tardis/federation-pull`, on 60dd851. Shaped in "Superyak: all hands" (messages a9221f76,
7338393b, d2960bd3, e54ba1eb, 59c43e5d and 1b83820e). The first-rail spec's peer-to-peer revision depends on it.
Nothing here is built.

| Review item | Where revision 2 answers it |
|---|---|
| M1 the puller listened | §1, a `federate` process and CLI with no listener |
| M2 the fingerprint didn't cover the key | §2, the pairing code |
| M3 the dispatch boundary | §4, prepared and serialized under the gate, plus a documented pull boundary |
| M4 the transport | §5, `pull_pinned` |
| M5 poison rows | §4, step 4 |
| M6 the rate limit | §4, the check order: only verified requests can be refused as busy, plus ack-only `limit` 0 |
| M7 4xx versus network | §7, `PeerAnswer` and the `refused` status |
| M8 dead peers starving live ones | §7, per-peer backoff |
| M9 metadata | §4 and §9, a new `outbox.last_error` column |
| M10 re-pairing | §2, mode is fixed for an identity |

## Why

Andy, 2026-10-27: "Remember this should be peer to peer as well." The ships agreed (d2960bd3) that lessons travel as
posts in a federated room, and that each peer answers its own sessions. Federation on main can't carry that between
our three machines yet:

1. **Push only.** `Federation.sync_once` POSTs each outbox row to the other peer's `/federation/events`
   (`transport.send_pinned`). Nothing fetches what is waiting. A peer that never listens can send but never receive.
   The Mac must not listen: law section 6 (D9-D11) counts every listener, loopback included, while a browser lane
   runs, and approves no interpreter. It is also a laptop on conference Wi-Fi behind a relay (Serenity, 7338393b).
2. **The outbox gives up after about four minutes.** A row retries while `attempts<8`, waiting
   `min(300, 2**(attempts+1))` s computed before the increment: 2, 4, … 128 s, about 254 s in all. After that the row
   stays `failed` until a person retries it. A lid closed for five minutes loses delivery.
3. **Nothing can be dialed yet.** The pinned dial checks the hostname against the certificate's names
   (`transport.py`, `server_hostname=`), and a station identity names only `localhost` and `127.0.0.1` unless
   `card --endpoint` ran first. The Pi's station serves behind `tailscale serve` without `--peer-tls`. So no peer of
   ours can be reached by a pinned dial today.

## Goals

1. A peer that never listens receives everything a listening peer would have pushed to it: the same signed envelopes,
   checked by the same `receive`.
2. No paired peer's delivery is lost to time. A row ends only when delivered, withdrawn (obsolete or unpaired), or
   refused by the other peer with a 4xx.
3. Nothing on the wire changes for v1 peers. v1 cards, `/federation/events` and the envelopes stay byte-identical.
   Retries, statuses and backoff do change (§7), and that is stated, not hidden.

## Non-goals

A relay (a peer fetching for a third), NAT traversal, discovery, the lessons index (the first-rail spec), a web UI on
a pull peer, and changing a known identity's mode.

## 1. A peer that never listens (M1)

- **`python -m superyak_peer federate --data-dir D`** is a loop with no listening socket. Each pass runs `collect`,
  `sync_once` (pushing to push peers) and, every 60 s, `pull_once` for each paired push peer. It also pulls at once
  when it starts, after a pass that succeeds following a failed one (a network change or a wake), and after a push
  to that peer succeeds. Each pass catches and logs its own exceptions, so one bad pass never stops federation
  (S6). On the Mac it runs as a LaunchAgent from the pinned runtime (build:runtime-install), and elsewhere as a
  systemd user unit with `MemoryMax`.
- **The CLI does what a pull peer's browser can't:** `card --pull --username U` exports a v2 card (no endpoint).
  `pair --card FILE` previews the card with its pairing code (§2) and pairs only after the person types `yes`.
  `connections` lists peers, mode, last success, last pull and backoff. `retry KEY` resets a row.
- **How the Mac's sessions reach their own peer:** in process, through the store. The lessons hook and index read the
  local database through a library call, never over HTTP. A browser UI on the Mac's peer would need a listener, and
  that is Andy's to approve under section 6. It is out of scope.
- `serve` gains nothing. Revision 1's `--federation-pull` flag is gone.

## 2. Cards: version 2 means pull, and the pairing code (M2, M10, S3, S11)

- A **v2 card** has v1's keys with `endpoint: null`, plus `"delivery": "pull"`. Version 2 means pull; there is no v2
  push. `validate_card` accepts v1 exactly as today and v2 exactly as above, and refuses anything else.
  `send_pinned` refuses a card without an endpoint before resolving anything (nit 6).
- **The pairing code** is the first 32 hex characters of `sha256(canonical({"signing_key", "certificate"}))`, shown in
  groups of four. For a v2 card it is the value people compare out of band. The TLS fingerprint isn't shown, because a
  pull card's certificate is never dialed. For a v1 card, the browser preview and `pair` show the code beside the
  fingerprint. That starts closing today's integrity gap (a swapped key could send as the peer) without breaking v1
  pairing.
- **`pair()`** also compares the effective mode, `card.get('delivery', 'push')`, so a v1 prior card meets a v2 card
  with a 409, not a `KeyError`. A known `peer_id` can't change mode, even after unpairing, as PROTOCOL.md already says
  of all trust material. A pull peer is a new data directory with a new identity. The Mac has never been a peer, so
  nothing old blocks it.
- **Two pull peers can't reach each other,** so a pull peer refuses to pair a pull card (S11).

## 3. A pinned dial needs no hostname (S10)

- A pinned dial trusts exactly one certificate, and it compares that certificate's fingerprint after the handshake.
  The hostname check adds nothing to that, and it is what makes today's identities, which name only `localhost`,
  undialable by tailnet name.
- So the pinned context sets `check_hostname = False`, keeps `CERT_REQUIRED` with the card's certificate as its only
  trust root, and keeps the fingerprint comparison. Existing identities, and the signatures made with them, stay
  valid.
- **A listener for federation only:** `federation-listen --data-dir D --host 127.0.0.1 --port 7437` serves
  `/federation/events` and `/federation/pull` over pinned TLS and nothing else, the way `door` serves two routes. On
  the Pi and Tardis it is reached through a Tailscale TCP passthrough on the tailnet name, port 7437. The card's
  endpoint is `https://<tailnet name>:7437`. Section 6 governs listeners on the Mac only, and this listener runs on
  the Pi and Tardis.

## 4. The pull route (M3, M5, M6, M9, S4, S5)

`POST /federation/pull`, on `federation-listen` (and on `serve --peer-tls`, for tests).

**Request:** canonical JSON with exactly these keys.

| Key | Rule |
|---|---|
| `version` | `1`, an `int` (`type(x) is int`, so a bool is refused) |
| `kind` | `"pull"`, which marks `pull` reserved in identity.py's comment beside `RECORD_KEYS` |
| `origin` | the puller's `peer_id` |
| `destination` | this peer's `peer_id` |
| `nonce` | 32 lowercase hex characters |
| `at` | the puller's Unix time, an `int` |
| `limit` | an `int` from 0 to 20; 0 means acks only |
| `budget` | an `int` number of bytes, from 65,536 to 8,388,608 |
| `ack` | at most 100 event ids, each matching the envelope's event id pattern |
| `refused` | at most 100 objects of exactly `{event_id, code}`, with code an `int` from 400 to 499 |
| `signature` | Ed25519 over the canonical request without `signature`, by the card's `signing_key` |

**Checks, in this order:**
1. The shape. Any other key set is a 400, so no envelope or record body passes.
2. `origin` is a paired peer with a v2 card. Otherwise 403 "unknown or unpaired peer", or 403 "not a pull peer".
3. The signature. Otherwise 403.
4. `at` is within 300 s of this peer's clock. Otherwise 403 "clocks differ by more than 5 minutes", worded apart from
   step 2, since a Pi without a clock battery can boot with the wrong time.
5. The nonce is inserted under the primary key `(origin, nonce)`. If it is already there, 409 replay. Rows older than
   600 s are pruned.
6. A per-origin lock. If a pull from this origin is already running, 409 "busy". Only a request that passed 3-5 can be
   refused as busy, so a stranger naming the Mac can't keep it from pulling. There is no time spacing, so the
   puller's own rounds run back to back.

**Processing:**
1. Each acked id becomes `delivered`, and each refused id becomes `refused` with its code in **`outbox.last_error`**,
   a new column. `metadata` holds the event payload and is never written. Only rows whose contact belongs to
   `origin`, and only from `pending` or `failed`. Unknown ids are ignored. Acking is idempotent.
2. `collect()` first, so rows exist even when this listener runs without the push worker (S5).
3. **Under `dispatch_gate`:** take `origin`'s rows in `pending` or `failed`, ordered by `event_seq, id`.
4. For each row, `_prepare`. `Obsolete` marks it `withdrawn`. A `Problem` or `ValueError` marks it `refused`, with
   `last_error` "too large" for a 413, as push would. Any other exception marks it `failed`, with the exception's
   class name in `last_error`. Every exception is caught, so there is never a 500, and a poison row never blocks the
   rows behind it (M5).
5. Stop at `limit` envelopes or `budget` bytes. If nothing else is ready, one envelope over the budget is sent
   anyway, up to the 6 MiB envelope cap, so a large row can't block the queue.
6. Serialize the response body while still holding the gate, then release it and return the bytes.

**Response:** `{"ok": true, "envelopes": [<canonical envelope text>, …], "more": <bool>}`. `more` is true when
`origin` still has rows in `pending` or `failed`.

**The pull boundary (M3).** Push holds the gate until its request bytes are written (PROTOCOL.md's final-dispatch
rule). Pull holds it until its response bytes are serialized. A withdrawal or unpair committed after that moment isn't
recalled from that response. It is delivered as the next envelope (`room.withdraw`, or nothing once unpaired), on the
next pull. The window is the response's time on the wire, at most the pull deadline (§5). PROTOCOL.md states this as
the pull boundary, and a race test pins it.

A row is marked delivered only when an ack names it, never because it was sent. A lost response costs one duplicate,
which `receive`'s receipts already absorb.

## 5. The pull transport (M4)

`pull_pinned(card, body)` uses the same pinned TLS as `send_pinned`, with:
- path `/federation/pull`;
- a response cap of 6 MiB plus 64 KiB, enough for the one envelope over budget;
- a 20 s deadline for the whole exchange (push keeps its 3 s);
- `parse()` taking an explicit size limit for this path only. The envelope limit stays as it is everywhere else.

The puller asks for a budget of 1 MiB.

## 6. The puller (S7)

`pull_once(card)` keeps acks and refusals per listening peer until a request carrying them gets a 2xx.
- For each returned envelope:
  - If its `origin` isn't the peer pulled from, it is dropped, so relaying stays a non-goal in code.
  - Otherwise it goes to `receive()` unchanged. "ok" or "duplicate" is acked. A 4xx `Problem` is refused with its
    status. Anything else is neither acked nor refused, and it is logged and offered again on the next pull.
- It repeats while `more`, up to 10 rounds, then sends `limit` 0 if acks remain.
- 403s are logged with their wording and shown by `connections` (a clock warning separately).
- A 404 means the peer has no pull route yet, and it waits an hour.
- A 5xx or a network failure goes into the per-peer backoff (§7).

## 7. Push: refusals end, and dead peers don't starve live ones (M7, M8, S13)

- **`transport.PeerAnswer(status)`** carries the peer's real HTTP status. Network failures (`OSError`, timeouts,
  `RemoteDisconnected`) stay a separate exception.
- **Row outcomes:**
  - `delivered`.
  - `refused`: the peer answered a 4xx other than 408, 425 or 429; or `_prepare` raised 413; or the pinned
    fingerprint differed. This status is terminal until `retry`.
  - `failed`: a network failure, a 5xx, or a 408, 425 or 429. It is retried by backoff.
  - `last_error` holds the code or the reason.
- **Per-peer backoff:** a table `peer_delivery(peer_id PRIMARY KEY, failures, next_attempt, last_success, last_pull)`.
  - `sync_once` skips every row of a peer that isn't due yet.
  - A due peer's first row is a probe. If the probe fails: `failures + 1`,
    `next_attempt = now + min(3600, 2**min(failures, 12))`, and the rest of that peer's rows wait.
  - Any success resets the peer: a push to it, a pull from it, or a verified pull it makes here.
  - Row `attempts` are still counted for display, with no cap. So one dead peer costs at most one 3 s probe per due
    pass.
- **`retry(key)`** works on `failed` or `refused`, and also makes the row's peer due.
- **Tests that change:**
  - `test_offline_queue_stable_and_bounded` still expects `failed == 1`. It is bounded per peer now, not by the
    attempt cap.
  - `test_exhausted_retry_keeps_event_id_and_rechecks_current_state` becomes: a peer in backoff isn't dialed until
    due; `retry` makes it due; the stored event id and the authorization re-check are unchanged.

## 8. Status and the web UI (S8, S9)

- `connections()` gains, per peer: mode, `last_success`, `last_pull`, `failures` and `next_attempt`, from
  `peer_delivery`.
- **The listener's web UI:**
  - The pair preview shows the pairing code, and for a v2 card, "Pull peer: it fetches from us; no endpoint".
  - A pull peer's connection card shows "Fetches from us" with the last pull, instead of an endpoint.
  - Rows for a pull peer show "Waiting for pull", not attempts.
  - Refused rows show their code, with Retry.
- A notice in Ops when a pull peer hasn't pulled for a day, or a push peer has failed for a day (review Q1).

## 9. Deploy and rollback

- **Migrations:** `pull_nonces`, `peer_delivery` and `outbox.last_error`.
- **The Pi and Tardis:**
  - `federation-listen` under a systemd user unit with `MemoryMax`.
  - The Tailscale TCP passthrough on 7437.
  - Their cards re-exported with the endpoint `https://<tailnet name>:7437`. Their identities are unchanged, by §3.
- **The Mac:** a new data directory and identity, `federate` as a LaunchAgent from the pinned runtime, and pairing by
  CLI with both sides comparing the pairing code.
- **Rollback:** unpair pull peers first, because an older peer refuses v2 cards in `validate_card`. After rolling
  forward again, `retry` resets the rows that burned to `failed` meanwhile.
- **Docs:** PROTOCOL.md (cards, the pull wire, the pull boundary, retries) and the peer README change in the same
  branch (S12).

## 10. Tests first

1. Cards and pairing:
   - A v2 card validates. A v2 card with an endpoint, any v2 "push" card, and v3 are refused.
   - A v1 card is byte-identical through `validate_card`, `card` and `pair`.
   - A v1 prior card against a v2 card gives 409, not 500.
   - A pull peer refuses a pull card.
   - The pairing code covers the key: swapping the key changes the code.
2. `sync_once` never dials a pull peer, and `send_pinned` refuses a card without an endpoint before resolving.
3. A real-HTTPS pull, in `test_transport`'s style:
   - It returns exactly the bytes push would have sent for the same rows.
   - The puller's `receive` accepts them.
   - A pin mismatch is refused.
   - A dial by tailnet name works against an identity whose certificate names only `localhost`.
4. Acks and duplicates:
   - An ack marks a row delivered, and the next pull returns nothing.
   - A lost response, pulled again, gives a duplicate that is applied once.
   - A `limit` 0 request acks and returns no envelopes.
5. Refusals: a refused envelope's row becomes `refused` with its code in `last_error`, and `metadata` is unchanged.
6. Refused requests:
   - A replayed nonce, a stale `at` (worded apart), a bad signature, an unpaired origin, a push-mode origin.
   - A bool `limit`, an extra key, an envelope-shaped body and a record-shaped body.
   - An ack naming another peer's row changes nothing.
7. Busy: unverified requests never make the real origin busy, and the puller's own back-to-back rounds never get 409.
8. The race (M3): a withdrawal committed after serialization arrives as the next pull's `room.withdraw`.
9. Poison rows:
   - A row whose `_prepare` raises doesn't block the rows behind it.
   - A 6 MiB envelope arrives within the 20 s deadline.
10. Push outcomes:
    - 500, 502, 429 and `RemoteDisconnected` stay `failed` and retryable. 409 becomes `refused`.
    - A dead peer costs one probe per due pass, and a live peer's rows aren't delayed.
    - A success resets the backoff.
11. The `federate` loop survives an exception in `pull_once`, and pulls at start and after a recovery.
12. `federation-listen` serves only the two federation routes; anything else is 404.

## Open questions

None for Andy. For the ships: a pull interval of 60 s, plus a pull at once after a wake, a network change or a push.
The review agreed that acks make the interval only a matter of latency.
