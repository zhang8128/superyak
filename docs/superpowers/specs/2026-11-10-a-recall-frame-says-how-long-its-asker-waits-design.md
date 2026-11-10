# A recall frame says how long its asker waits

Tardis, 2026-11-10. The second half of the embedder split agreed with Rio Grande on 2026-11-09. The first half is on
main: the shared embedder drops a request whose caller gave up (`remaining_ms`, train-1110, 25533151). Its client
half, which sends its own response timeout, is `tardis/embed-remaining-ms`. This spec carries a crossing's deadline
from the asker down to the publisher's embed.

## 1. Why

A crossing's asker waits about a second. The publisher it reaches builds its embedder client with the 900 s default
(`lighthouse_daemon.py`, `RemoteEmbedProvider(embedder_socket)`), so the publisher's query embed waits up to 900 s
after the asker has gone. On the Pi on 2026-11-09, a short text took 74 s behind abandoned requests. The embedder can
drop a request whose caller gave up, but only when the request says how long its caller waits, and today the
publisher doesn't know.

## 2. The field

A `recall` frame may carry `remainingMs`: how many milliseconds its asker will still wait, counted from when the frame
is sent.
- It is optional. A frame without it is served as today.
- When present, it is a finite number ≥ 0, an int or a float but not a bool. Anything else is `MALFORMED_FRAME`.
- Only `recall` frames take it. A `read` frame embeds nothing, so the field isn't defined there. Like any other key
  `_validate_read` doesn't name, it is ignored.
- The protocol version stays `0.1`. `_required` checks only that fields are present, so a publisher without this
  change ignores the field, and a frame without it is still valid at a publisher with it.

## 3. Who sets it

Each client that already keeps a deadline sets the field from that deadline at the moment it sends:
`remainingMs = max(0, end − now) × 1000`, on the frame it encodes. It never changes the frame its caller passed in.
- `LighthouseClient.call` (engram), from its `end`: its own timeout, or the caller's deadline if that's sooner.
- `daemon_call` (peer, `crossing.py`), from the deadline `_answer` computes from the request's `deadline_ms`.
- The hosting peer always sets the field itself, replacing any `remainingMs` that a remote asker's frame holds. The
  asker's own `deadline_ms` is what bounds it, as it bounds the daemon call today.

## 4. What the publisher does with it

- `handle_frame` stamps the frame's arrival on its own monotonic clock.
- When `retrieve` embeds the query, it passes what's left: `remainingMs − (now − arrival)`, at least 0.
- The embedder client sends `min(what's left, its own response timeout)` as `remaining_ms`, and sets its socket
  timeout to the same minimum. **So an asker can shorten the publisher's embed but never lengthen it.** A frame with
  `remainingMs` of 10⁹ still gets the publisher's own timeout.
- Only `RemoteEmbedProvider.embed` takes the new keyword (`remaining_ms=None`). A publisher with no embedder socket
  loads its model in process, has no queue to wait in, and `retrieve` doesn't pass the keyword to it.
- When the embedder answers `expired`, or the client's socket times out first, the frame is answered as an embedder
  failure is today: `PUBLISHER_UNAVAILABLE`. One info line names the expiry and its numbers, with no traceback. The
  asker has gone, so nobody reads the answer.
- Nothing else in the frame's path gets a deadline: the store search, the ledger and the receipts run as today.

## 5. What doesn't change

Nothing hashes or stores a whole frame. Rio Grande read this at main 29be1533:
- the audit row writes named fields;
- the result carries `content_digest(frame["query"])`;
- `_bind_turn` keeps the receiver, publisher, ids and time;
- `remote_deliveries` digests the delivered texts;
- the clients' `canonical_json` is only the wire encoding.

So no digest, receipt or disclosure changes. The cold call (the model's first load after it was dropped for being
idle, 1.8 to 2.6 s on the Pi, and the 25 s call seen on 11-04) is not this spec's problem. A deadline makes a cold
call fail sooner. It doesn't make it faster.

## 6. Tests

Each one fails without the change it covers:
1. `LighthouseClient.call` and `daemon_call` send `remainingMs` from their deadline. The frame their caller passed is
   unchanged.
2. The hosting peer replaces a `remainingMs` in a remote asker's frame with its own.
3. The publisher passes the clamped value to the embed: a small `remainingMs` lowers it, a huge one doesn't raise it,
   and a frame without it gets the publisher's own timeout.
4. Bad values (−1, NaN, a string, a bool, 10⁴⁰⁰ written as an integer) are `MALFORMED_FRAME`. A `read` frame with one
   is served as before.
5. End to end, the shape of `test_a_client_that_gave_up_costs_the_lane_nothing`: a recall with `remainingMs` of 200,
   queued behind a batch that holds the embedder's lane, is dropped when the lane frees. The service logs it, its
   text is never embedded, and a live request behind it runs.
6. A publisher without an embedder socket serves a frame with `remainingMs` as before.

## 7. Decisions

- **D1:** recall frames only, since only a recall embeds.
- **D2:** the asker can shorten the embed, never lengthen it (Rio Grande's clamp).
- **D3:** the hosting peer sets the field from its own deadline and never trusts a remote asker's value.
- **D4:** no protocol version bump, because both mixes of old and new still work.
- **D5:** an expired embed gets today's answer and no new error code.
