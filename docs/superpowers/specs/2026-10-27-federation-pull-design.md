# Federation pull: a peer that never listens, and an outbox that doesn't give up

Tardis, 2026-10-27, revision 1, for a fresh reviewer under station law section 3. Branch `tardis/federation-pull`, on
60dd851. Shaped in "Superyak: all hands" (messages a9221f76, 7338393b, d2960bd3, e54ba1eb and 59c43e5d). The
first-rail spec's peer-to-peer revision depends on it. Nothing here is built.

## Why

Andy, 2026-10-27: "Remember this should be peer to peer as well." The ships agreed (d2960bd3) that lessons travel
between machines as posts in a federated room, and that each peer answers its own sessions. Federation on main
can't carry that between our three machines yet, for two reasons found by reading it:

1. **Push only.** `Federation.sync_once` POSTs each outbox row to the other peer's `/federation/events`
   (`transport.send_pinned`). No route fetches what is waiting for you. A peer that never listens can send but never
   receive. The Mac must never listen: law section 6 (D9-D11) lets only macOS's own services listen while a browser
   lane runs, and it is a laptop on conference Wi-Fi behind a relay (Serenity, 7338393b).
2. **The outbox gives up.** A row retries only while `attempts<8`, with backoff `min(300, 2**(attempts+1))` seconds
   (4, 8, 16 … 300). That's about 14 minutes. After that, the row stays `failed` until a person presses retry. A lid
   closed for an hour loses delivery.

A peer that can't listen also can't export a card today. `validate_card` requires an `https` endpoint, and
`/api/connections/card` refuses without one.

## Goals

1. A peer that never listens receives everything a listening peer would have pushed to it: the same signed
   envelopes, checked the same way.
2. No paired peer's delivery is lost to time: rows wait until they are delivered, withdrawn or unpaired.
3. Nothing changes for today's peers. v1 cards, push, `/federation/events` and the receipts stay byte-identical.

## Non-goals

A relay (a peer fetching on behalf of a third), NAT traversal, discovery, a lessons index (the first-rail spec), and
changing a paired peer from push to pull without re-pairing.

## 1. Cards: version 2 adds `delivery`

- A v2 card has the v1 keys plus `delivery`, either `"push"` or `"pull"`. When `delivery` is `"pull"`, `endpoint`
  is `null`. When it is `"push"`, `endpoint` follows v1's rules.
- `certificate` and `fingerprint` stay required, so the shape is one shape. A pull peer's certificate is never
  dialed.
- `validate_card` accepts v1 exactly as today (push implied) and v2 as above. Anything else is refused.
- `Identity.card` writes v1 when the peer has an endpoint, and v2 `pull` when started with `--federation-pull` and no
  endpoint. A peer never exports v2 `push`, so today's cards don't change.
- `pair` keeps refusing changed trust material. `delivery` joins the compared fields, so changing mode means unpairing
  and pairing again.

## 2. The pull route

`POST /federation/pull` on a listening peer. HTTPS only, as `/federation/events`. The puller dials it with
`send_pinned`'s TLS pinning (the listening peer's certificate and fingerprint from its card). The listening peer
authenticates the puller by signature, not by TLS.

**Request**, canonical JSON:
`{"version": 1, "kind": "pull", "origin", "destination", "nonce", "at", "limit", "ack", "refused", "signature"}`

| Field | Rule |
|---|---|
| `origin` | the puller's `peer_id`; its card must be paired here with `delivery: "pull"` |
| `destination` | this peer's `peer_id` |
| `nonce` | 32 lowercase hex characters, never seen from this origin in the last 600 s |
| `at` | the puller's Unix time, within 300 s of this peer's clock |
| `limit` | 1 to 20 |
| `ack` | up to 100 event ids the puller accepted (including duplicates) |
| `refused` | up to 100 `{event_id, code}` pairs the puller's `receive` refused, with code an HTTP status |
| `signature` | Ed25519 over the canonical request without `signature`, by the card's `signing_key` |

**Processing**, in one transaction for the acks and one per envelope prepared:
1. Verify the request against the pinned card. A bad signature, an unpaired or push-mode origin, a stale `at` or a
   reused nonce is 403. The nonce is stored in `pull_nonces(origin, nonce, at)`, pruned past 600 s.
2. Mark each acked event id `delivered`, and each refused one `failed`, with the code in `metadata`. Only outbox rows
   whose contact belongs to `origin` are touched, and only from `pending` or `failed`. Unknown ids are ignored.
   Acking is idempotent.
3. Take up to `limit` rows for `origin`'s contacts in `pending` (not `failed`), ordered by `event_seq, id`, as
   `sync_once` orders them. For each, call `_prepare(row id)`, the same authorization re-check and the same stored
   envelope push would send. `Obsolete` marks the row `withdrawn`, as push does. A `Problem` or `ValueError` leaves
   it pending and skips it for this pull.
4. Answer `{"ok": true, "envelopes": [<canonical envelope text>…], "more": <bool>}`, at most 8 MiB in total. One
   envelope is always sent if any is ready (each is at most 6 MiB already).

A row is never marked delivered because it was sent, only when an ack names it. A response lost on the way costs
one duplicate, which `receive`'s receipts already absorb.

**One pull at a time per origin** (a lock), and at most one every 2 s, or 429.

## 3. The puller

- `serve --federation-pull` (no `--federation-endpoint`) makes a peer pull-only. The federation worker, which today
  runs `sync_once` every 5 s, also runs `pull_once` for each paired push peer every 60 s, and at once when the
  process starts.
- `pull_once(card)` sends a request with the acks and refusals from the last round, feeds each returned envelope to
  `receive()` unchanged (same `verify_envelope`, receipts and `_apply`), and records each event id as acked, or as
  refused with the `Problem`'s status. It repeats while `more` is true, up to 10 rounds, then sends a final
  ack-only request with `limit` 1.
- The pull peer's own outgoing events still push to listening peers through `sync_once`. Only receiving changes.
- `status` shows, per paired peer, its delivery mode and the last successful pull.

## 4. Push: no paired peer is given up on

- `sync_once` skips rows whose contact's peer has a v2 `pull` card. Those rows wait for a pull.
- For push peers, drop `attempts<8`. Backoff becomes `min(3600, 2**(attempts+1))` seconds, so retries settle at one
  an hour. A row ends only when delivered, withdrawn (obsolete or unpaired) or refused by the other peer with 4xx.
  A 4xx stays `failed` after one try, as it is not a network problem.
- `retry` keeps its meaning: it resets `attempts` and `next_attempt`.

## 5. Tests first

1. A v2 pull card validates; a v2 pull card with an endpoint, a v2 push card without one, and v3 are refused. A v1
   card is byte-identical through `validate_card`, `card` and `pair`.
2. `sync_once` never dials a pull peer, and its rows stay `pending`.
3. A pull returns exactly the bytes `send_pinned` would have POSTed for the same rows. The puller's `receive`
   accepts them, and the room shows the messages.
4. An ack marks rows delivered, and a second pull returns nothing. A lost response, pulled again, gives a duplicate,
   accepted once, with no double `_apply`.
5. A refused envelope comes back in `refused` and its row goes `failed`, not delivered.
6. These are refused: a replayed nonce, a stale `at`, a bad signature, an unpaired origin, a push-mode origin, and a
   pull for another peer's rows (an ack naming another peer's row changes nothing).
7. An obsolete row (the member left the room) comes back as `room.withdraw` or is withdrawn, as push would do.
8. A push row to an unreachable peer is still retried after 8 attempts, at most hourly.
9. 429 for a second pull within 2 s, and for concurrent pulls from one origin.

## 6. Deploy

A peer migration adds `pull_nonces` and nothing else. Cards are read per pairing, so no data moves. The Pi and Tardis
stay push and gain the route. The Mac pairs again as a pull peer once its pinned runtime exists (Serenity's
`runtime-install`), so serving never runs from its dev checkout.

## Open questions for the reviewer and the ships

1. Should a push peer that can't be reached for a day show a notice in Ops? That's a station notice, and cheap.
2. Is 60 s the right pull interval for a laptop? Shorter wakes Wi-Fi more often, longer delays lessons.
