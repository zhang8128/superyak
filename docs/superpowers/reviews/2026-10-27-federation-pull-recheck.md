Verdict: REQUEST CHANGES

# Re-check: Federation pull spec, revision 2

Second fresh reviewer under station law section 3, 2026-10-27. I took no part in writing the spec or in its first
review. I read revision 2 (`docs/superpowers/specs/2026-10-27-federation-pull-design.md`, c9e7160), the first review,
and revision 1 (1a4eecc), and checked them against `peer/superyak_peer/` (federation, identity, transport, peer_routes,
peer_store, db, dispatch, door, app, `__main__`, signatures, backups, static/app.js), `peer/PROTOCOL.md`,
`peer/README.md`, `peer/tests/`, `docs/station-law.md`, `docs/station-restore.md` and the `Makefile`. The branch
changes no code since 60dd851, so line numbers hold on both. I checked every item below against the code, and ran one
TLS experiment (the §3 note).

Revision 2 is a real improvement. The non-listening `federate` process settles M1, the v2 card and the mode rule settle
M10 and S3, and the pull wire is now specified tightly enough to build. Two things still block approval. The pairing
code has no trusted display on the side that exports the card, so M2's comparison has nothing to compare against. And
the per-peer backoff that answers M8 leaves its probe and its row selection undefined, in a way that lets a pull peer's
queue, or one bad row, stall live push peers.

## The first review's items

| Item | Status | What the code shows, and what remains |
|---|---|---|
| M1 the puller listened | Resolved | `federate` has no listening socket and `card --pull` replaces the browser export. Nothing tests the "never listens" property (SF12). |
| M2 fingerprint didn't cover the key | Partly | The code covers `signing_key` and `certificate`, and the import surfaces show it. No export surface shows it (MF1). It also leaves out `participant` (SF4). |
| M3 dispatch boundary | Resolved in design | The documented pull boundary is accurate. Test 8 passes even with no gate at all (SF12). The gate hold is unbounded (SF8). |
| M4 transport | Partly | Path, cap, deadline and parse limit are defined. The deadline is a fixed 20 s, not scaled to bytes as asked, so a large head-of-queue row can block a slow link (SF10). |
| M5 poison rows | Resolved for pull | §4 step 4 catches everything. Push has the same hole, now made worse by the probe (MF2). |
| M6 rate limit | Resolved | The lock comes after steps 3-5, `limit` 0 means acks only, and acks are kept until a 2xx (§6). |
| M7 4xx versus network | Partly | `PeerAnswer` and `refused` are defined. Push still doesn't classify local `_prepare` failures other than 413, `HTTPException`s other than `RemoteDisconnected`, or a 200 without `ok` (transport.py:85-93) (MF2). |
| M8 dead peers starve live ones | Partly | A per-peer table and a probe exist, but what counts as a failed probe is undefined. Rows may be skipped after the `LIMIT` (federation.py:164), and the row-level `next_attempt` is left unspecified (MF2). |
| M9 metadata | Resolved | The new `outbox.last_error` column, and test 5 checks that `metadata` is unchanged. |
| M10 re-pairing | Resolved | The effective mode is compared with `.get`, and a pull peer gets a new identity. Note that `endpoint` already differs (null versus string), so federation.py:33 would refuse a mode change even without it. |
| S1 Why figures | Resolved | 2+4+…+128 = 254 s matches federation.py:178 and the `attempts<8` limit at :164. |
| S2 Goal 3 | Resolved | |
| S3 v2 push | Resolved | Version 2 means pull. |
| S4 request validation | Resolved, one gap | The `destination` rule is in the table but not in the check order, and no test covers it (SF9). |
| S5 collect first | Resolved | §4 processing step 2. |
| S6 worker robustness | Partly | `federate` catches each pass. `serve`'s lifespan worker is still unguarded (peer_routes.py:12-18) if a listener uses it to push. How far up to 10 pull rounds delay `sync_once` isn't discussed (SF6). |
| S7 puller errors | Mostly | 403, 404, 5xx and network failures are covered. The puller's handling of 409 (busy or replay) and 400 answers isn't specified (N3). |
| S8 per-peer status | Resolved | `peer_delivery` feeds `connections()`. |
| S9 web UI | Resolved for delivery rows | A refused reply still shows "Saved here" in the room view (N12). |
| S10 deploy | Partly | Hostname and exposure are solved. Still missing: who pushes on the Pi and Tardis, the units, certificate expiry, and the rollback advice destroys data (SF1, SF6, SF7). |
| S11 two pull peers | Partly | The rule is stated, but a peer keeps no record of its own mode (SF2). |
| S12 protocol docs | Resolved | §9. |
| S13 existing tests | Resolved | Both rewrites still check what they claim. |
| S14 missing tests | Resolved as listed | Some of the new tests can't fail (SF12). |
| S15 flags | Moot | `--federation-pull` is gone. |

First review's nits:
- Nit 2: the peer formula caps its exponent, but the row formula is unspecified (MF2).
- Nits 3, 4, 5 and 6: resolved.
- Nit 7: a per-process lock is fine with one `federation-listen`.
- Nit 8: that restore edge now ends `refused` instead of `failed`, which is acceptable.
- Nit 9: adopted.

## The questions I was asked to press on

**§3, no hostname check.**
- As an identity check it is sufficient. The DER pin is compared after the handshake and before any byte is written
  (transport.py:66-67, 79-83), and `validate_card` binds the fingerprint to the certificate (identity.py:62-64).
- No other certificate can pass:
  - One that doesn't chain to the card's certificate fails the handshake.
  - One that does chain (the card's certificate is CA:TRUE, pathlen 0, identity.py:135, so it can sign leaves) is
    stopped by the pin. test_transport.py:186-237 already proves that.
- I ran `check_hostname=False` with `CERT_REQUIRED` and the card's certificate as the only root:
  - A dial by a tailnet name against a localhost-only certificate succeeds, and the pin matches.
  - An expired pinned certificate fails with `SSLCertVerificationError: certificate has expired`, and so does a
    not-yet-valid one. Both are `OSError`s.
- So the same reasoning that drops the hostname check should drop the date check (SF1).

**The pairing code.**
- The hash input is unambiguous. It is canonical JSON of a two-key object (sorted keys; strings quoted and escaped,
  identity.py:20-25), so no two different (key, certificate) pairs encode the same way.
- 128 bits is ample. The attacker needs a second preimage of a code that an honest peer generated; collisions don't
  help, because the attacker doesn't choose the honest card.
- The weaknesses are around the code, not in it:
  - nothing on the exporting side shows it (MF1);
  - people compare only the first and last groups (SF3);
  - `participant` isn't covered (SF4).

**The pull boundary under the gate.**
- It holds if the whole pull runs in one worker thread and returns bytes. `DispatchGate` is a per-process `RLock`
  plus a per-thread flock descriptor (dispatch.py:14-35), so enter and exit must happen on the same thread. An
  `async` handler that awaited inside the gate would stall that process's event loop.
- Uvicorn writes after the handler returns. That doesn't matter: the envelope strings are fixed under the gate, so
  even a dict that FastAPI serializes afterwards changes nothing.
- Across processes, the flock serializes the pull with every `serve` transaction (db.py:100-104). The documented
  boundary is accurate.
- The cost is a station-wide write freeze for the length of the loop (SF8). The gate must also be held directly,
  never through a transaction (N1).

**Per-peer backoff.**
- The probe and the row selection are MF2.
- `status()` still reports the row's `next_attempt` (federation.py:259), which no longer says when the row will go
  (N8).
- `retry()` making the peer due is fine.
- The restore reconcile's `_unpair` (backups.py:662-673) still mirrors `Federation.unpair` and leaves `refused` rows
  alone, which is consistent.
- A restored `peer_delivery` holds absolute times in the past, and a restored `pull_nonces` table is bounded by the
  300 s `at` window. Both are harmless.

**`federation-listen` as a second process.** It coordinates correctly through the flock. What's missing is G4b
(SF5), a pusher and wiring for its unit (SF6), and its own bounds (N6).

**The CLI and how pairing is authorized today.** The CLI is inconsistent with it (SF3).

## New must-fix

**MF1. The pairing code has no trusted display on the exporting side** (spec §1, §2, §8, §9).
- §2 makes the code "the value people compare out of band", and §9 says "both sides comparing the pairing code".
  But the spec shows the code only where a card is imported: the browser preview and `pair --card`.
- The export surfaces show only the card:
  - `card` prints JSON and nothing else (`__main__.py`:410).
  - "Show my peer card" flashes the raw JSON (app.js:1631-1638).
  - The code is not a card field.
- So the person has nothing trusted to compare the importer's code against. Recomputing it from the received file
  is circular, and that leaves M2's key-swap hole open in practice.
- Fix:
  - `card` and `card --pull` print the code computed from the machine's own identity, to stderr so stdout stays a
    card.
  - "Show my peer card" shows it.
  - `connections` lists each paired peer's code for later checks.
- Test: the code that `card --pull` prints equals the code `pair` previews for that file, and differs once the
  file's `signing_key` is swapped.

**MF2. Push row outcomes and the per-peer probe are undefined where it matters** (spec §7; federation.py:164-180).
- **Selection before `LIMIT`.** `sync_once` takes 20 rows across all peers in `event_seq` order (federation.py:164).
  - §7 says it "skips every row of a peer that isn't due", and test 2 says it "never dials a pull peer". If either
    skip happens after the `LIMIT`, then 20 or more queued rows of a pull peer fill every page, and so do the rows
    of a peer in backoff. The Pi's rows for the Mac pile up whenever the lid is closed.
  - Live push peers then starve, which is M8 again by a new route.
  - The spec must put mode and due-ness in the SQL `WHERE`, before the `LIMIT`.
- **What a probe failure is.** "If the probe fails" isn't defined.
  - If a local `_prepare` failure counts, a bad row at the head of a peer's queue fails every probe. The row is
    always first by `event_seq`, so the peer's backoff climbs to 3600 s, never resets, and every row behind it
    waits forever. That is M5 again.
  - It is also undefined which row probes next after the first row is withdrawn (`Obsolete`) or refused. The peer
    answered a refusal, so it is reachable.
- **Unclassified push outcomes.** §7 maps peer 4xx, `_prepare` 413 and a pin mismatch to `refused`, and network
  failures, 5xx, 408, 425 and 429 to `failed`. It doesn't place:
  - a `_prepare` `Problem` other than 413, or a `ValueError`. §4 step 4 calls these `refused` for pull, so the two
    paths disagree.
  - any other exception. Today `except (OSError, ValueError, Problem)` (federation.py:175) lets `KeyError`,
    `TypeError` and `sqlite3.Error` escape and abort the whole pass at that row, on every pass.
  - an `HTTPException` other than `RemoteDisconnected`. `IncompleteRead` is what the watchdog produces
    (transport.py:69-76).
  - a 200 without `ok`, or a reply over 64 KiB (transport.py:85-90).
- **The row-level `next_attempt`.** Its fate isn't stated. If federation.py:164 still filters on it, with :178
  setting it, then after a peer recovers each of its rows still waits up to 300 s. That contradicts "any success
  resets the peer", and it is what M8 asked to avoid for the Mac after the lid opens.
- Fix:
  - Give push the same local-failure table as §4 step 4.
  - Count only peer answers and network failures as probe outcomes. A delivery or a peer refusal resets the peer;
    a local failure or `Obsolete` is neutral, and the next row probes.
  - Filter by mode and due-ness in SQL.
  - Stop consulting the row `next_attempt`, or clear it when the peer resets.
- Tests:
  - A first row whose `_prepare` raises doesn't put its peer in backoff.
  - With more than `limit` rows queued for a pull peer, and more than `limit` for a peer in backoff, ahead of a live
    peer's row, the live row is delivered in one pass.

## New should-fix

**SF1. Pinned certificates expire after 365 days, and nothing can replace them** (§3, §9).
- The certificate's lifetime and the rules around it:
  - `not_valid_after` is now + 365 days (identity.py:134; PROTOCOL.md:16).
  - A known peer's certificate can't change (federation.py:33; PROTOCOL.md:44-45).
  - There is no rotation (PROTOCOL.md:18-19).
- My experiment shows that `CERT_REQUIRED` refuses an expired pinned certificate. That is an `OSError`, so under §7
  the row is `failed` and the peer is probed hourly for ever.
- When the Pi's identity was made:
  - `Federation.__init__` creates the identity at the first `serve` (app.py:139, federation.py:16), and the station
    code dates from early October 2026.
  - So around October 2027 every pinned dial to the Pi fails. The only way out is `station-new-identity`, which voids
    every signature.
- A dialer whose clock is behind fails the same way ("not yet valid"). The spec itself expects that of a Pi without
  a clock battery (§4 step 4).
- §3's "existing identities … stay valid" is true of names, not of dates.
- Fix options:
  - Verify by the exact DER pin alone (for example `CERT_NONE`). The handshake signature still proves the peer holds
    the pinned key, and the pin is checked before any write.
  - Or specify a rotation.
  - Either way, add a test with an expired pinned certificate.

**SF2. A peer has no record of its own mode** (§1, §2).
- "A pull peer refuses to pair a pull card" and "`pull_once` for each paired push peer" both need the peer to know
  whether it is a pull peer.
- Nothing stores that. `identity.json` holds two keys and a certificate (identity.py:137), and `card --pull` and
  `card --endpoint` can both run on the same identity.
- Specify:
  - a mode stored once;
  - `card --endpoint` refused on a pull peer, and `card --pull` on a peer that has exported or served an endpoint;
  - `federate` pulls only on a pull peer. Otherwise a push peer running it gets §4 step 2's 403 "not a pull peer"
    every 60 s.

**SF3. The CLI doesn't say who is acting, or who confirms** (§1, §9).
- **Who acts.**
  - `Federation.pair` and `connections` require an admin who isn't activation-pending (federation.py:29, 50;
    auth.py:117-120).
  - `retry` requires the row's own delivery authority, and never admin authority (federation.py:267-268;
    PROTOCOL.md:209).
  - The station CLIs name the actor with `--as` and check it (ships.py:201-206).
  - §1 gives only `card --pull` an account. `pair`, `connections` and `retry` have none.
- **The Mac's account.** `pair` needs an admin on the Mac's peer.
  - `init` creates one, but it prompts for a 12-character password (`__main__.py`:421). Law section 7 forbids a ship
    typing a person's password, and a peer with no listener has no use for one.
  - Say that Andy runs `init` himself, or add a password-less owner for a peer that never listens.
- **Who confirms.** Pairing a pull card lets that key fetch everything shared with the contact.
  - Make it Andy's act, as with `station-approve`: he reads the code on two independent screens.
  - Have `pair` ask for the other side's code instead of "yes". That stops a ship confirming for him, and it defeats
    people comparing only the first and last groups. Matching those two groups takes about 2^32 key generations.

**SF4. The pairing code leaves out `participant`** (§2).
- A tamperer can keep the genuine key and certificate and change `participant.id` to another account on that peer,
  keeping the shown name. The code still matches.
- Releases then go to that account. `receive` accepts any recipient that exists locally (federation.py:293-295), and
  the Pi has many accounts.
- Hash the whole canonical card. Each card is compared on its own import anyway.

**SF5. G4b in the new commands** (§1, §3).
- `serve --peer-tls` runs `refuse_a_lost_identity_before_the_store` before it loads the identity for its TLS files
  (`__main__.py`:449-451; signatures.py:38-50). It has to, because `PeerIdentity.load_or_create` silently creates a
  new key when `identity.json` is missing (identity.py:122-139).
- `federation-listen` needs the same TLS files, so it has the same shape. On the Pi, which holds signed records, a
  start after `identity.json` was lost would mint a new key and void every signature.
- Require the G4b check in `federation-listen` and `federate`, and test it.

**SF6. Nothing pushes on the Pi or Tardis, and the new unit isn't wired** (§1, §9).
- **No pusher.**
  - §9 runs only `federation-listen` there. It "serves … nothing else", and §4 says it runs without the push worker.
  - The station's `serve` has no `--sync` (README.md:265-266), and `federate` is deployed only on the Mac.
  - So nothing ever pushes between the Pi and Tardis. Both are push peers, and §4 step 2 refuses pulls between them.
- Name the pusher on each listener, for example `federate` with pulls off (SF2).
- Allow exactly one `sync_once` process per data directory:
  - `_sync_lock` is per process (federation.py:17, 159), so `serve --sync` plus `federate` would send rows twice and
    double-count backoff.
  - If `serve --sync` is the pusher, its worker needs the same per-pass `try` (peer_routes.py:12-18).
- Wire the new unit:
  - Add it to `ALERTED_SERVICES` (Makefile:42).
  - Add it to the restore runbook's stop line (docs/station-restore.md:64). Otherwise it keeps writing acks and
    nonces into a database that is being restored.

**SF7. The rollback advice destroys data and isn't needed** (§9).
- Why "unpair pull peers first" is harmful: unpairing withdraws every pending and failed row for that peer and
  nulls its received content (federation.py:43-45; PROTOCOL.md:46-48). Withdrawn rows never come back, so "retry
  resets the rows that burned to failed" can't reach them.
- Why it isn't needed:
  - Main handles a stored v2 card without a 500. `send_pinned`'s `validate_card` raises `Problem(400)`, and the row
    goes to `failed` (transport.py:39; federation.py:175-176). `receive` uses only `peer_id` and `signing_key`
    (identity.py:166, 184).
  - Revision 2's pull takes `failed` rows (§4 step 3), so rows that burned during a rollback are pulled after
    rolling forward, with no retry.
- Say: keep pairings during a rollback.

**SF8. The pull holds the station-wide gate for an unbounded time** (§4 steps 3-6).
- Every Store transaction in every process takes this gate (db.py:100-104), so the browser, ships, the door and
  Odo all wait while a pull holds it.
- Rows that yield no envelope (withdrawn, refused or failed) count against neither `limit` nor `budget`.
- Example: the room's epoch moves during a week away. Hundreds of the Mac's queued rows then turn `Obsolete`.
  - Each costs a rollback plus a committed mark, in the default rollback journal on the Pi's SD card. No WAL is
    configured.
  - All of it happens with the station frozen, and past the puller's 20 s.
- Push takes the gate per row (transport.py:79-83).
- Holding the gate across the loop buys little. `_prepare` re-checks each row under the gate, so holding it per row
  gives the same per-envelope boundary.
- Bound the rows examined per pull (counting the ones that yield nothing), or take the gate per row and state the
  boundary per envelope.

**SF9. `destination` is not in the check order, and not tested** (§4, test 6).
- It is the only defence against a listener replaying a puller's signed request to another listener within 300 s:
  - The nonce table is each listener's own.
  - Origin, signature and `at` all pass at the second listener.
- That second listener would then hand the replaying listener the envelopes meant for the puller.
- Add the check to step 1 or 2, before the nonce, and add it to test 6.

**SF10. The deadline isn't scaled to bytes** (M4's remainder, §5).
- The single over-budget envelope can reach about 5.8 MB: 4 MiB of attachments in base64 (layers.py:46-47) plus a
  100,000-character body.
- Delivering that in 20 s takes about 2.3 Mbit/s sustained. The conference Wi-Fi behind a relay that the Why section
  describes may not manage it.
- A response that times out is never acked, so it stays at the head. Every pull re-sends it, and nothing behind it
  arrives until the Mac is on a faster link.
- Test 9 runs on loopback, so it can't show this.
- Scale the deadline to the response size, for example a minimum rate once the headers arrive.

**SF11. Some 4xx answers that §7 makes terminal are states, not decisions** (§7).
- Cases:
  - A receiver answers 403 "Unknown or unpaired peer" until it has paired the sender (federation.py:286-288).
    Sharing works as soon as one side pairs, so the first deliveries before the other side pairs back are refused
    for good.
  - A host mismatch (app.py:33-34) or "Federation requires HTTPS" (peer_routes.py:79-80) is a misconfiguration.
- Today these retry 8 times.
- Make "unknown or unpaired" and configuration refusals retryable under the peer's backoff, or give them a code the
  sender can tell apart.

**SF12. Tests that can't fail, and tests that are missing** (§10).
- Test 8 passes with no gate at all: a withdrawal committed after serialization can't reach that response either
  way. Add the interleaving case: a withdrawal attempted while the pull is preparing either blocks until the
  response bytes exist, or is honoured.
- Test 10 needs more than `limit` queued rows for the dead peer, and for a pull peer, ahead of the live row (MF2).
- Nothing tests that `federate` never listens, which is M1's whole premise under law section 6. For example, fail
  on `bind` or `listen` during a pass.
- No tests cover:
  - MF1 (the exporter's code);
  - SF5 (G4b in the new commands);
  - SF9 (`destination`);
  - SF3 (a non-admin's `pair` or `connections` is refused, and `retry` by a non-author gives 404).

## Nits

1. Hold `store.dispatch_gate` directly across the loop, never a transaction. A nested `_prepare` would wait out
   SQLite's 30 s on a second connection, as the comment at signatures.py:71-75 explains.
2. Budget and cap don't match:
   - The listener accepts budgets up to 8 MiB, but the puller's cap is 6 MiB plus 64 KiB. Cap `budget` at what the
     transport accepts.
   - Whether the cap leaves room for the escaping that comes with embedding envelopes as JSON strings depends on the
     4 MiB attachment and 100,000-character limits, not on the 6 MiB envelope cap. State that, or count `budget` on
     the encoded bytes.
3. Say what the puller does with a 409 (busy or replay) and a 400 answer to its pull.
4. `sync_once`'s result dict and `result[status] += 1` need `refused` (federation.py:158, 180).
5. How a wrong certificate fails:
   - A certificate that doesn't chain fails as `SSLCertVerificationError`, an `OSError`, so §7 counts it as
     `failed`. Only a leaf signed by the pinned key reaches the fingerprint comparison. Say which "a pin mismatch is
     refused" means.
   - Also consider `OP_NO_RENEGOTIATION`, or a TLS 1.3 minimum, so a TLS 1.2 server can't change certificates after
     the pin check.
6. `federation-listen` should:
   - refuse a bind that isn't loopback, as `door` does (`__main__.py`:425-430);
   - bound request bodies: 6 MiB for events and a few KiB for pull;
   - skip a Host check. Its 403 would now be terminal.
7. "`serve` gains nothing" (§1) contradicts "on `serve --peer-tls`, for tests" (§4). Never mount the pull route on a
   proxied `serve`: the main app is public through Funnel (app.py:173-174).
8. Delivery status and actions now say the wrong thing:
   - "Check delivery now" should make every peer due, or it does nothing for an hour.
   - `failed` now means "retrying", so "Failed to send" (app.js:487) and the row's `next_attempt` in `status()`
     mislead.
9. One hour is a long backoff for pulls. Pulls are the Mac's only way to learn a listener is back, so give them a
   shorter cap.
10. `peer_delivery.last_pull` means "pulled from it" on the Mac and "pulled here" on the Pi; say so. Two processes
    write that table, so update it column by column.
11. Say that Andy loads the LaunchAgent. Law section 7: ships never "load a launchd job".
12. A reply's `state` is the outbox status (peer_store.py:115, 175). A `refused` reply shows "Saved here" in the room
    (app.js:487).
13. Define `more` as "rows beyond those returned, not failed in this pass". Today every non-empty response sets it,
    and a listener-side failed row keeps all 10 rounds busy every minute.
14. The browser pairing still echoes `fingerprint` (peer_routes.py:55-56), and app.js:1992 copies it from the preview
    without the person typing anything. Echo the code instead, or drop the echo.
15. Keep the Tailscale rule that limits shared users to port 443 (README.md:275), so 7437 stays reachable only by
    Andy's machines.
