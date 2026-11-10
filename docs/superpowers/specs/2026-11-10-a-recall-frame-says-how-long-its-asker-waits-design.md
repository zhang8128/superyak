# A recall frame says how long its asker waits

Tardis, 2026-11-10, revision 2, after a fresh Pi reviewer's verdict on revision 1 (c92aa5ec): approve with five
shoulds and four nits, all taken here. Its re-check approved revision 2 (443bb3c4); its two new nits are folded in. This is the second half of the embedder split agreed with Rio Grande on
2026-11-09. The first half is on main: the shared embedder drops a request whose caller gave up (`remaining_ms`,
train-1110, 25533151). Its client half, which sends its own response timeout, is `tardis/embed-remaining-ms` and
rides train-1112. This spec carries an asker's deadline down to the publisher's embed. Code is cited at main 298472cf.

## 1. Why

A crossing's asker waits at most `deadline_ms`, which is capped at 10 s (`CROSSING_DEADLINE`, identity.py). The
publisher it reaches builds its embedder client with the 900 s default (`lighthouse_daemon.py`,
`RemoteEmbedProvider(embedder_socket)`), so the publisher's query embed waits up to 900 s after the asker has gone.
Under enforce it waits while holding one of the daemon's `FRAMES_AT_ONCE` slots, not only a thread. On the Pi on
2026-11-09, a short text took 74 s behind abandoned requests. The embedder can drop a request whose caller gave up,
but only when the request says how long its caller waits. Today the publisher doesn't know.

## 2. The field

A `recall` frame sent to a lighthouse daemon may carry `remainingMs`. It is the most milliseconds its asker will
still wait, counted from when the frame is sent. It is an upper bound, not an exact figure: each clock starts a
little after the one before it, so the publisher can hold an embed a moment longer than the asker waits, but never
drop one the asker still waits for.
- It is optional. A frame without it is served as today.
- When present, the daemon's validator checks three things, in this order:
  1. `isinstance(v, (int, float)) and not isinstance(v, bool)`;
  2. `math.isfinite(float(v))`, where an `OverflowError` (`10**400` written as an integer) counts as not finite;
  3. `v >= 0`.

  Anything that fails is `MALFORMED_FRAME`. A very large finite value such as 10³⁰⁰ is valid, and the clamp in
  section 4 reduces it to the publisher's own timeout. Nothing downstream uses the raw value: the daemon converts the
  checked value to a float once, and every later sum and minimum runs on that float.
- Only `recall` frames take it. A `read` frame embeds nothing, so the field isn't defined there. `_validate_read`
  ignores it like any key it doesn't name.
- The protocol version stays `0.1`. `_validate_recall` uses `_required`, which checks only that fields are present.
  So a daemon without this change ignores the field, and a frame without it is still valid at a daemon with it.

## 3. Who sets it

Only a client that talks to a lighthouse daemon directly sets the field. Two do, and each sets it from the deadline
it already keeps, at the moment it sends: `remainingMs = max(0, end − now) × 1000`. Each computes the value after
validating its caller's frame, puts it in a copy of the frame, never in its caller's, and validates the copy again
before it encodes it.
- **`LighthouseClient.call`** (engram, lighthouse_client.py), for a local asker of a local daemon. It uses `end`: its
  own timeout, or the caller's deadline if that comes sooner.
- **`daemon_call`** (peer, crossing.py), for a crossing on its hosting peer. It uses the deadline `_answer` computes
  from the request's `deadline_ms`.

**A crossing's asker never sets the field, and the crossing request doesn't change.**
- A crossing's asker uses `ask_crossing` / `CrossingClient` (lighthouse_client.py). These send a signed request to the
  asker's own peer.
- The hosting peer refuses any frame whose keys aren't exactly its `FRAME_KEYS[kind]` (`crossing_frame_ok`,
  identity.py). So a frame carrying `remainingMs` is refused at the shape check.
- `FRAME_KEYS` stays exactly as it is. That keeps the asker's request, its signature and `crossing_digest` unchanged.
  `crossing_digest` is a hash of the whole signed request, frame included: the one place a whole frame is hashed.
- `CrossingClient` and `ask_crossing` change nothing. For a crossing, the asker's `deadline_ms` reaches the publisher
  as the hosting peer's own deadline. `daemon_call` adds the field to the frame it sends the daemon, after the request
  has been checked and digested.

## 4. What the publisher does with it

- **Arrival:** `handle_frame` stamps the frame's arrival on its own monotonic clock.
- **What's left:** when `retrieve` embeds the query, it passes what's left: `remainingMs − (now − arrival)`.
- **The clamp, in one place, the embedder client:**
  - `RemoteEmbedProvider.embed` takes a keyword, `remaining_ms=None`.
  - It sends `min(remaining_ms, its own response timeout × 1000)` as `remaining_ms`, and uses the same minimum, in
    seconds, as that call's socket timeout.
  - **So an asker can shorten the publisher's embed but never lengthen it.** A frame with `remainingMs` of 10⁹ still
    gets the publisher's own timeout.
- **Per call, never on the instance:** the daemon shares one provider across its threads. So the minimum is passed as
  an argument to `_call` and is never written to the instance. Otherwise two concurrent frames would overwrite each
  other's timeout.
- **Nothing left:** when what's left is 0 or less, the client raises the expiry without connecting at all. A socket
  timeout of 0 would mean non-blocking, not expired.
- **The model check:** the first embed on a fresh provider asks the service for its model (`{"op": "info"}`). That
  call gets the same minimum. The service answers it without taking the lane, so it is fast, but it doesn't escape
  the deadline.
- **A local model:** only `RemoteEmbedProvider.embed` takes the keyword. A publisher with no embedder socket loads
  its model in process and has no queue to wait in, so `retrieve` doesn't pass the keyword to it.
- **The expiry has its own exception:** `EmbedderExpired`, a subclass of `EmbedderUnavailableError`. The client raises
  it in three cases: when it has nothing left before connecting, when the service answers `expired`, and when its own
  socket times out on a call whose minimum came from the asker. When the publisher's own timeout was the smaller, a
  socket timeout is today's plain unavailable failure, not an expiry. A caller that catches `EmbedderUnavailableError`
  today still catches it.
- **How an expired recall is answered:**
  - The daemon catches `EmbedderExpired` by type in `handle_frame`, beside `FrameError` and `_LedgerBusyFrame` and
    before the generic `except Exception`, so the frame aborts. Catching it inside `_recall` and carrying on would
    call `record_disclosure` and return an allow with no candidates, which this spec forbids.
  - It logs one info line naming the expiry and its numbers (what was left at arrival, and the time taken), with no
    traceback.
  - It answers `PUBLISHER_UNAVAILABLE`, the code an embedder failure gets today, with the detail text "the asker's
    deadline passed". Today's failure says "internal failure", which this isn't. The code stays the same, so no asker
    needs to change.
  - The catch must keep what today's failure already does. The expiry happens inside `_rank_recall`, before
    `record_disclosure`, inside an open ledger side that holds a `_frames` slot and closes it in `finally`. So an
    expired recall writes no disclosure row and no receipt, and it releases its slot. That's the right outcome,
    because nothing was delivered.
- **Nothing else gets a deadline:** the store search, the ledger and the receipts run as today.

## 5. What doesn't change

- **No digest, receipt or disclosure.** The engram daemon hashes no whole frame. I read it again at 298472cf:
  - `record_disclosure` writes named fields;
  - the result carries `content_digest(frame["query"])`;
  - `_bind_turn` keeps the receiver, publisher, ids and time;
  - `_request` builds the policy request from named keys;
  - the clients' `canonical_json` is only the wire encoding.

  The peer does hash a whole signed request, frame included (`crossing_digest`). Section 3 keeps the field out of
  that request entirely, and adds it to the frame only on the hosting side, after the digest.
- **A cold call.** The model's first load after it was dropped for being idle takes 1.8 to 2.6 s on the Pi, and a
  25 s call was seen on 11-04, a station report. A deadline makes a cold call fail sooner. It doesn't make it
  faster.

## 6. Tests

Each one fails without the change it covers:
1. `LighthouseClient.call` and `daemon_call` send `remainingMs` from their deadline. The frame their caller passed is
   unchanged.
2. **The hosting peer:** a direct `_answer` test with a mock `daemon_call` shows the frame sent to the daemon carries
   the peer's value. A crossing request whose frame carries `remainingMs` is still refused with the shape error, and
   `FRAME_KEYS` is unchanged.
3. **The clamp:** a small `remainingMs` lowers the embed's `remaining_ms` and socket timeout. A huge one (10⁹, 10³⁰⁰)
   doesn't raise them. A frame without it gets the publisher's own timeout.
4. **Bad values:** −1, NaN, a string, a bool and `10**400` written as an integer are `MALFORMED_FRAME`, both at the
   daemon and in `LighthouseClient.call`, which raises `NeighborUnavailable` for its own bad value. A `read` frame
   with the field is served as before.
5. **End to end,** in the shape of `test_a_client_that_gave_up_costs_the_lane_nothing`:
   - A recall with `remainingMs` of 200 queues behind a batch, and the batch's first unit is held on a gate, not on
     time.
   - The gate opens only after the recall's deadline has passed by the service's own clock.
   - The recall is dropped. The assertion is on the service's log line and on its text never being embedded, not on
     timing. A live request behind it still runs.
   - The expired recall writes no disclosure row, and its `_frames` slot is free afterwards.
6. **Zero and concurrency:**
   - A `remainingMs` of 0 raises `EmbedderExpired` without connecting to the embedder.
   - Two concurrent frames with different values each get their own `remaining_ms` and socket timeout.
7. **The answer:** an expired recall is answered `PUBLISHER_UNAVAILABLE` with "the asker's deadline passed", logged at
   info with no traceback.
8. **A publisher without an embedder socket** serves a frame with `remainingMs` as before.

## 7. Decisions

- **D1:** recall frames only, since only a recall embeds.
- **D2:** the asker can shorten the embed, never lengthen it (Rio Grande's clamp), in one place: the embedder
  client, per call.
- **D3:** only the clients that talk to a daemon set the field. A crossing's request, its `FRAME_KEYS`, its signature
  and its digest don't change, and its asker's `deadline_ms` reaches the publisher through the hosting peer.
- **D4:** no protocol version bump, because both mixes of old and new still work.
- **D5:** an expired embed raises `EmbedderExpired`. It is answered with today's code, `PUBLISHER_UNAVAILABLE`, its
  own detail text and an info line, and it writes no disclosure.
