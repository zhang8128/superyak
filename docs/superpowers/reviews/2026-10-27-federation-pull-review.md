Verdict: REQUEST CHANGES

# Review: Federation pull spec, revision 1

Fresh reviewer under station law section 3, 2026-10-27. I took no part in writing the spec. I reviewed
`docs/superpowers/specs/2026-10-27-federation-pull-design.md` on branch `tardis/federation-pull` (1a4eecc, on 60dd851)
against `peer/superyak_peer/` (federation, identity, transport, peer_routes, peer_store, db, dispatch, app,
`__main__`, backups, signatures, static/app.js), `peer/PROTOCOL.md`, `peer/README.md`, `peer/tests/` and
`docs/station-law.md`. I checked every item below against the code. Line numbers are on 1a4eecc.

The direction is right. A signed pull that returns the stored envelopes is the smallest change that lets a laptop
receive, and `_prepare`'s stored-envelope behaviour makes re-delivery byte-identical. But the spec runs the puller
in a process that listens, which breaks its own premise. It also opens a confidentiality hole at pairing, drops the
final-dispatch boundary, assumes a transport that can't carry the response, and changes push retries in a way that
today's code can't tell apart and that would starve live peers.

## What holds (checked)

- **Push only, and no card without an endpoint.** Both claims are true: `sync_once` only POSTs
  (federation.py:156-185, transport.py:83). `validate_card` needs an `https` endpoint (identity.py:149-154).
  `/api/connections/card` refuses without one (peer_routes.py:39-40).
- **Re-pulls are byte-identical.** The first `_prepare` stores the canonical envelope (federation.py:149-153).
  Later calls re-check authorization and return the same bytes, or raise `Obsolete` if the action changed
  (143-148). The puller's `receive` then sees the same digest and answers duplicate (federation.py:296-301). Tests
  3 and 4 can be built.
- **Acks name rows directly.** `event_id` is the outbox row id (federation.py:150).
- **Status guard.** "Only from `pending` or `failed`" is the same guard that keeps a concurrent withdrawal from being
  overwritten (federation.py:178; test_federation.py:334-348).
- **Ordering.** `event_seq, id` is what `sync_once` uses (federation.py:164).
- **No cross-use of signatures,** provided the pull verifier requires an exact key set (see S4). A pull request has
  `kind` and none of the envelope keys. `verify_envelope` needs the exact envelope key set (identity.py:261).
  `verify_record` needs a `RECORD_KEYS` kind (identity.py:182-184, 291).
- **Nonce window.** 600 s is at least 2 x 300 s, so a nonce can't be pruned while its `at` would still pass.
- **Backups and restore.** Keeping `delivery` inside the card JSON leaves the peers columns unchanged, so `COMPARED`
  (backups.py:380-387) and `PEER_NEEDS` (backups.py:648) need nothing. The reconcile's `_unpair`
  (backups.py:662-674) still mirrors `Federation.unpair`, and a pull from an unpaired peer is refused. A restored
  listener re-offers rows that were already acked, and the puller's receipts absorb them.

## Must fix

1. **The puller runs in a process that listens, which the spec says the Mac must not do** (spec §3, line 88; Why,
   lines 15-16). `serve --federation-pull` is a uvicorn server on 127.0.0.1:7435 (__main__.py:466). The federation
   worker only exists inside that app's lifespan (peer_routes.py:10-25). Law section 6 (station-law.md:59-64) and
   the lane rules (team/README.md:26-36) count loopback listeners. Only Apple binaries can be approved, "never an
   interpreter", and "a lane's turn waits until they are gone". So the Mac either blocks lanes or stops pulling
   during them. Card export has the same problem: the browser route needs that server, and the `card` CLI requires
   `--endpoint` (__main__.py:227).
   - Specify a non-listening process, for example a `federate` command that loops `collect`, `sync_once` and
     `pull_once`, supervised as a LaunchAgent, plus `card --pull`.
   - Or put the loopback-listener question to Andy explicitly; the law leaves it to him.
   - Also say what "never listens" means for how the Mac's own sessions will reach its peer.

2. **For a pull card, the fingerprint people compare doesn't cover the key that can fetch.**
   - Pairing confirms only the TLS certificate fingerprint (peer_routes.py:55-56; app.js:993, "compare the
     fingerprint outside Superyak"). `validate_card` binds `peer_id` to `signing_key` and `fingerprint` to
     `certificate`, but nothing binds the key to the certificate (identity.py:155-161).
   - Today a swapped `signing_key` in an otherwise genuine card can't read anything: pushes still go to the pinned
     real certificate, and the real peer refuses them because the `destination` doesn't match.
   - With pull, someone who swaps `signing_key` and `peer_id` keeps the Mac's public certificate, passes the
     fingerprint check, and pulls everything shared with that contact. The certificate on a pull card is never
     dialed (spec §1, lines 40-41), so for pull it is decoration.
   - Fix: for a pull card, the confirmed value must cover `signing_key`, either the `peer_id` or one digest over
     key and certificate. The preview must show it.
   - This also closes the existing integrity gap: today a swapped key lets someone send events as that peer.

3. **The final-dispatch boundary is dropped.**
   - Push holds `dispatch_gate` from `prepare()` until the request bytes are written (transport.py:77-83). Every
     transaction takes the same gate (db.py:100-104). PROTOCOL.md:178-187 makes this the protocol's rule, and
     test_transport.py:96-123 pins it.
   - The pull route prepares each row in its own transaction. The response is written after the handler returns,
     so a removal, withdrawal or unpair that commits in between still goes out. That window covers up to 20
     prepares plus an 8 MiB write to a laptop on conference Wi-Fi. The spec doesn't mention the gate.
   - Fix: choose one. Either a response that holds the gate across a write with its own deadline, the way push
     does under its 3 s timer, or a documented weaker boundary in PROTOCOL.md with its reason.
   - Add the race test: a withdrawal committed between prepare and write.

4. **`send_pinned` can't carry a pull response** (spec §2, lines 50-51 and 78-79).
   - What's in the way:
     - The path is hard-coded to `/federation/events` (transport.py:83).
     - A response over 64 KiB is refused (transport.py:85-87).
     - `parse()` caps at 6 MiB (identity.py:129).
     - The whole exchange has a 3 s deadline (transport.py:14; PROTOCOL.md:189).
   - An 8 MiB response, a little more when envelopes are embedded as JSON strings, can't arrive. A large row at
     the head of the queue then times out on every cycle, and nothing behind it is ever received.
   - Fix: define the pull transport: path, response cap, a deadline scaled to bytes, and probably a byte budget
     the puller sets.

5. **Poison rows block the queue** (spec §2 step 3, lines 74-77).
   - A `Problem` or `ValueError` from `_prepare` leaves the row pending. The main case is a 413 when the envelope
     is too large (federation.py:151-152), and since that check runs before the envelope is stored, the envelope
     is rebuilt on every pull.
   - The row is picked again first on every pull, because rows are ordered by `event_seq`. Up to `limit` such rows
     starve everything behind them and keep `more` true for all 10 rounds.
   - Any other exception, such as a `KeyError` on bad metadata, fails the whole pull with a 500, every time.
   - Push marks these rows `failed` (federation.py:175-178).
   - Fix: mark the row failed as push does, or keep taking rows until `limit` envelopes are ready. Define `more`.

6. **The rate limit contradicts the puller loop** (spec §2 line 84 against §3 lines 91-94).
   - "At most one every 2 s, or 429" refuses the puller's own back-to-back rounds, and a refused request drops the
     acks it carried.
   - The "final ack-only request with `limit` 1" isn't ack-only, since `limit` is at least 1. The envelope it
     returns stays unacked for 60 s.
   - Fix:
     - Set a spacing for the rounds or allow a burst.
     - Allow `limit` 0 for an ack-only request.
     - Keep acks and refusals until a request carrying them gets a 2xx.
     - Apply the lock and the 429 only after the signature verifies and the nonce is fresh. Otherwise anyone can
       send one junk request every 2 s that names the Mac's origin and keep it from pulling.

7. **Today's code can't tell a 4xx apart from a network failure** (spec §4, lines 102-103).
   - Non-200 answers: `send_pinned` turns every one except 401 and 403 into `Problem(409)`. That includes 429,
     500, 502 and 503 (transport.py:86-87).
   - Dropped connections: `RemoteDisconnected` is also an `HTTPException`, so it becomes `Problem(409)` too
     (transport.py:92-93).
   - Local refusals: a 413 from `_prepare` and a fingerprint mismatch (transport.py:66-67) are `Problem`s as well.
     `sync_once` catches all of these as one case (federation.py:175-176).
   - Network failures and 4xx refusals share the status `failed`, and `sync_once` retries `failed` rows
     automatically (federation.py:164).
   - Fix:
     - Raise a distinct exception that carries the peer's real HTTP status.
     - Make only true 4xx answers permanent, and not 408, 425 or 429.
     - Decide how local `Problem`s are handled.
     - Say which status a network failure leaves. If it is `pending`, then `retry()`'s "only failed" rule
       (federation.py:269-270), the UI's Retry button (app.js:917) and the existing tests change (S13).

8. **Removing the attempt cap lets a dead peer starve live ones** (spec §4, line 101).
   - Rows are taken 20 per pass, oldest first, across all peers (federation.py:164). Each attempt to an offline
     peer can take up to 3 s.
   - About 1,200 rows to one retired or closed-lid peer fill the whole hour with hourly retries. Even a few dozen
     add up to 60 s of delay per pass for every live delivery. The 8-attempt cap bounds this today.
   - Fix: back off per peer. Make one probe per peer and skip that peer's other due rows in the pass when the
     probe fails.
   - Reset a peer's backoff on any success, including a successful pull from it. Then the Mac's outbound rows
     don't wait up to an hour after the lid opens.

9. **"With the code in `metadata`" would corrupt the row** (spec §2 step 2, line 71).
   - `outbox.metadata` holds the event payload, and several places read it:
     - `_prepare` (federation.py:96, 115-123)
     - `_delivery_authority` (federation.py:190-210)
     - `_remote_room` and `_unverified_local_authors` (peer_store.py:110-115, 141-145)
     - `remote_send` (peer_store.py:171-175)
   - Overwriting it breaks a row that `retry()` later offers again.
   - Fix: say "merge under a reserved key" or add a column. A column contradicts §6's "adds `pull_nonces` and
     nothing else".

10. **Re-pairing can't change the mode** (spec §1 line 45-46; Non-goals line 34; §6 line 125).
    - `pair()` reads the previous card whether or not the peer is paired (federation.py:30-34). PROTOCOL.md:44-45
      says "even after unpairing". So "unpairing and pairing again" is refused with 409.
    - If the Mac's identity was ever paired at the Pi or Tardis, "The Mac pairs again as a pull peer" fails. The
      only way out is `station-new-identity`, which invalidates every signature.
    - Adding `delivery` to the compared keys as written raises `KeyError` on a v1 prior card. That turns today's
      idempotent v1 re-pair into a 500.
    - Fix: compare the effective mode, `card.get('delivery', 'push')`. Then either define how mode can change
      after an unpair, or say a new identity is needed.

## Should fix

1. **The backoff figures in Why are wrong** (lines 17-18). With `min(300, 2**(attempts+1))` on the value before the
   increment (federation.py:178), the waits between the 8 attempts are 2, 4, … 128 s. The cap of 300 is never
   reached, and the total is about 254 s plus worker granularity, roughly 4-5 minutes, not 14 (PROTOCOL.md:197). The
   argument gets stronger, but the claim should be correct.
2. **Goal 3 contradicts §4.** "Nothing changes for today's peers" doesn't hold: §4 changes today's push retries,
   statuses and backoff. Say "nothing on the wire changes".
3. **Refuse v2 `push`.** It is accepted but never exported, which gives push two encodings and forces the
   comparison in Must fix 10. Simpler: version 2 means pull.
4. **Spell out the request validation.**
   - Exact key set, `kind == "pull"`, and `type(x) is int` for `version`, `limit`, `at` and `code`. A bool passes
     `isinstance` (identity.py:263 shows the house pattern).
   - Ack ids match the event id grammar (identity.py:268). Each `refused` item has exactly `{event_id, code}`, with
     `code` from 400 to 499.
   - Verify the signature before looking up or inserting the nonce.
   - Insert the nonce under a primary key on (origin, nonce).
   - Reserve `pull` in the comment at identity.py:171-172.
5. **Collect before taking rows.** The pull route must call `collect()` before step 3. The listener's worker runs
   only with `--sync` (peer_routes.py:19), and otherwise no outbox rows exist yet.
6. **Make the worker robust.** The worker has no exception handling (peer_routes.py:12-18), so one exception in
   `pull_once` ends background federation silently, push included. Catch per pass. Up to 10 spaced rounds of
   `pull_once` also delay `sync_once` in the same loop; say whether that's acceptable.
7. **Define how the puller handles errors.**
   - 403, with distinct messages for a stale `at` and for an unpaired origin. A Pi without a hardware clock can come
     up with a wrong time after a reboot.
   - 404 from a peer without the route, and 5xx.
   - Keep acks per listening peer.
   - Report as refused only 4xx `Problem`s from `receive`. Any other exception is neither acked nor refused.
   - Drop envelopes whose `origin` isn't the peer pulled from, so relaying stays a non-goal in code.
8. **Status per peer.** `status()` is per row and filtered by author (federation.py:220-262); it has no "per
   paired peer". The mode and the last pull belong in `connections()` or a separate key of `/api/sync`. Say where
   "last successful pull" is stored. §6 adds no column, and `pull_nonces` is pruned after 600 s.
9. **The web UI isn't covered.**
   - The pair preview shows an empty endpoint for a pull card (app.js:993), and the connection card shows
     "Endpoint: Unavailable" (app.js:898).
   - "Check delivery now" only runs `sync_once` (peer_routes.py:67-71) and should also pull on a pull peer.
   - Pull rows show "0 attempts" and "Pending delivery" forever.
10. **Deploy is incomplete.**
    - Nothing in the repo shows the Pi or Tardis serving `--federation-endpoint`. The station README runs `serve
      --proxy-headers` behind `tailscale serve` without `--peer-tls` (README.md:265-269).
    - The station identity is created with the default SANs, localhost and 127.0.0.1 (signatures.py:81,
      identity.py:211, 220-226), unless `card --endpoint` or `serve --peer-tls` ran first. A pinned dial by
      hostname then fails verification (transport.py:43-59). PROTOCOL.md:17-19 says changing the hostname needs a
      future migration.
    - Say how each listener exposes pinned TLS, for example a second process or a TCP passthrough, and check each
      `peer-cert.pem`.
    - Rollback: old `send_pinned` runs `validate_card` on the stored v2 card and refuses it (transport.py:39). The
      Mac's rows then burn to `failed` with 8 attempts, and after rolling forward only `pending` rows are pulled.
      Say "unpair before rolling back", or reset them.
11. **Two pull peers can never reach each other.** Neither side dials, so the rows wait forever. Refuse pairing a
    pull card on a pull peer, or show it plainly.
12. **Protocol docs.** PROTOCOL.md (the card at 21-45, the wire, retries at 189-199) and README.md:123-141 need
    updates. The spec doesn't list them.
13. **Existing tests that change.** `test_offline_queue_stable_and_bounded` expects `failed == 1`
    (test_transport.py:80). `test_exhausted_retry_keeps_event_id_and_rechecks_current_state` uses `attempts=8`
    (test_transport.py:140-141). Say what each becomes.
14. **Missing tests:**
    - A real-HTTPS pull in test_transport's style, with a pin mismatch.
    - The prepare/write race (Must fix 3).
    - A 6 MiB envelope over pull within the deadline.
    - A poison row that doesn't block later rows.
    - The puller's own loop never hits 429.
    - Unauthenticated requests never cause a 429 for the real origin.
    - Request shape refusals: a bool `limit`, an extra key, and an envelope-shaped or record-shaped body.
    - `pair` answers 409, not 500, for a v1 prior card against a v2 card.
    - The worker survives an exception in `pull_once`.
    - A dead peer doesn't delay a live one.
    - 500, 502, 429 and `RemoteDisconnected` stay retryable, while 409 doesn't.
    - The fingerprint or `peer_id` confirmation for pull cards (Must fix 2).
15. **Flags.** Refuse `--federation-pull` together with `--federation-endpoint`, and say whether it implies the
    worker (`sync_enabled`) or requires `--sync`.

## Nits

1. "`Identity.card`" is `PeerIdentity.card(endpoint, participant)` (identity.py:238), reached through
   `Federation.card` (federation.py:19-22).
2. `2**(attempts+1)` grows without bound once retries never stop. Cap the exponent.
3. Goal 2 lists "delivered, withdrawn or unpaired" but leaves out "refused with 4xx" (§4).
4. Make `at` integer seconds, and state the prune boundary once: a nonce whose `at` is older than now minus 300 s
   can't pass anyway.
5. Stop preparing at the byte budget rather than preparing 20 envelopes of up to 6 MiB first.
6. `send_pinned` should refuse a card without an endpoint before resolving it. Today `urlsplit(None).hostname` is
   `None`, and `getaddrinfo(None, 443)` dials loopback port 443 (transport.py:41-42).
7. The per-origin lock is per process. That is fine for one `serve`, but PROTOCOL.md says several database
   processes share the store gates.
8. Restore edge, the same for push: a listener restored from before an envelope was stored prepares different
   bytes, because `last_activity` comes from the clock (federation.py:85). The puller then answers 409 and the row
   goes `failed`.
9. Open questions:
   - Q1: yes. Add the listener-side counterpart too: a notice when a pull peer hasn't pulled for a day, since its
     rows otherwise pile up unseen.
   - Q2: 60 s is fine, because acks make the interval only a latency question. Also pull immediately after waking
     or a network change, and after a push to that peer succeeds.
