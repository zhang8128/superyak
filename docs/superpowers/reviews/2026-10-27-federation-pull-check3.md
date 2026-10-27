Verdict: APPROVE WITH CHANGES

# Third check: Federation pull spec, revision 3

Third fresh reviewer under station law section 3, 2026-10-27. I took no part in writing the spec or in its two
earlier reviews. I read revision 3 (`docs/superpowers/specs/2026-10-27-federation-pull-design.md`, b1af0a4), the
review of revision 1 and the re-check of revision 2. I checked them against `peer/superyak_peer/` (federation,
identity, transport, peer_routes, peer_store, db, dispatch, signatures, app, `__main__`, backups, chats, layers,
static/app.js), `peer/PROTOCOL.md`, `peer/README.md`, `peer/tests/`, `docs/station-law.md`,
`docs/station-restore.md` and the `Makefile`. The branch changes no code since 60dd851, so line numbers hold. I checked
every item below against the code. I also ran one TLS experiment (described under §3 below).

**What the verdict means.** Revision 3 settles almost everything the re-check raised. The pin-only dial is sound, the
pairing code now has a trusted display on both sides, and push and pull share one outcome table. Two things in that
table would still break delivery if it were built as written (MF1, MF2). Both have small, mechanical fixes, given below.
Apply them as written and the spec can be built without another review round. If either is resolved differently, it
goes back to a reviewer. The should-fixes can be answered in the spec or the plan.

## The re-check's items

| Item | Status | What the code shows, and what remains |
|---|---|---|
| MF1 no code on the exporting side | Resolved | `card` and `card --pull` print the code to stderr, and `connections` lists it. One gap: the Pi's and Tardis's browsers can't show any card. `/api/connections/card` needs `fed.endpoint` (peer_routes.py:39-40), and the station's proxied `serve` has no `--federation-endpoint`, which requires `--peer-tls` (`__main__.py`:455-456; README.md:265-266). So on those machines the trusted display is `card --endpoint` in Andy's own terminal (N11). |
| MF2 probe and selection undefined | Partly | Mode and due-ness are now in the SQL before `LIMIT`, and local failures are neutral. But the table makes every row-scoped 4xx from the peer a peer failure, which stalls the peer (new MF1). The inner `JOIN peer_delivery` drops every peer that has no `peer_delivery` row (new MF2). |
| SF1 pinned certificates expire | Resolved | My experiment confirms it: a `CERT_NONE` dial with a TLS 1.3 minimum accepts an expired, a not-yet-valid and a wrong-name pinned certificate, and stops a wrong DER before any application byte. With `CERT_NONE`, every wrong certificate now becomes `refused` (SF1 below). |
| SF2 a peer doesn't know its mode | Mostly | `federation_mode` is stored once (`system_meta` exists, system_author.py:10). Identities that exist at migration time have no mode, so an existing push station can still be turned into a pull peer, permanently (SF5). |
| SF3 who acts and who confirms | Partly | `--as` and the admin check match the browser routes (auth.py:117-120; federation.py:267-268). But typing the code proves nothing while the importing screen shows that same code. Nothing technical stops a ship either (SF4). |
| SF4 participant not covered | Resolved | The code covers the whole canonical card. Test 2 swaps `participant.id`. |
| SF5 G4b | Resolved | Both commands call `refuse_a_lost_identity_before_the_store` (signatures.py:38-50). `Store(signing=True)` would also refuse (signatures.py:54-68). |
| SF6 no pusher; units | Mostly | `federate` runs everywhere, behind one flock, and both units go into `ALERTED_SERVICES` (Makefile:42) and the runbook's stop line (station-restore.md:64). But "Check delivery now" still runs `sync_once` inside `serve`, outside the lock (SF3). `test_station_units.py`:96 lists the units too and needs the same change. |
| SF7 rollback | Resolved | Main's `send_pinned` refuses a stored v2 card through `validate_card`, with `Problem(400)` (transport.py:39), and `sync_once` marks the row `failed` (federation.py:175-176). The pull takes `failed` rows. See N8 for the units. |
| SF8 unbounded gate | Resolved | The gate is taken per row, with a cap of 200 rows. The walk's wall time can still pass the puller's 10 s header deadline on the Pi (SF6). |
| SF9 destination | Resolved | Check 2 runs before the origin, signature and nonce checks, and test 6 covers it. |
| SF10 deadline | Resolved in design | 10 s, then 64 KiB/s over `Content-Length`: a 5.8 MB response gets about 100 s. Test 9 can't fail when there is no deadline at all (SF7). |
| SF11 terminal 4xx | Over-corrected | "Unknown or unpaired" now retries, but so does every row-scoped refusal, and those stall the peer (MF1). |
| SF12 tests | Mostly | All the items it asked for are listed. A few new tests can't fail, and a few are missing (SF7). |

Re-check nits:
- Resolved: 1 (gate taken directly), 2 (budget cap 6,291,456 on encoded bytes), 3 (puller 409 and 400), 4 (`refused`
  in the result), 5 (moot under `CERT_NONE`), 6 (listener loopback, caps, no Host check), 7 (no pull route on
  `serve`), 9 (300 s pull cap), 10 (`last_pull`), 11 (Andy loads the LaunchAgent), 12 ("Saved here", app.js:487),
  13 (`more`), 14 (code instead of the fingerprint echo) and 15 (the 443 rule, README.md:275).
- Partly resolved: 8. "Check delivery now" makes every peer due, but the route still runs `sync_once` in `serve` (SF3).

## What revision 3 newly decided

**§3, the pin-only dial: sound.**
- I ran `PROTOCOL_TLS_CLIENT` with `check_hostname=False`, `verify_mode=CERT_NONE` and `minimum_version=TLSv1_3`,
  against servers holding P-256 self-signed certificates like identity.py:123-135.
  - `getpeercert(binary_form=True)` returns the leaf's DER under `CERT_NONE`. The dict form is empty, so the code must
    use the binary form.
  - Each of these dials succeeds and the pin matches: an expired certificate, a not-yet-valid one, and one naming only
    `localhost` dialed as `peer.tailnet-x.ts.net`.
  - With a different certificate, the pin compare fails and the server receives no application byte.
  - A TLS 1.2-only server fails with `SSLError`, an `OSError`, so it is a network failure.
- **Proof of the key.** OpenSSL checks the TLS 1.3 CertificateVerify against the presented leaf's key whatever the
  verify mode, so an exact DER match proves the peer holds the card's TLS key.
- **Nothing written early.**
  - Before the compare, the client writes only handshake records. `wrap_socket` completes the handshake, and the
    compare comes before `conn.request` (transport.py:59-67).
  - Python sends no 0-RTT data and doesn't resume sessions unless `session=` is passed.
  - TLS 1.3 has no renegotiation, so the certificate can't change after the check.
- **The remaining issue is the outcome, not the check.** See SF1.

**§7, the outcome table.**
- **Local exceptions.** Every local `_prepare` exception becomes `refused` and is neutral. That is right for
  deterministic failures (a 413, a `KeyError` on bad metadata, a `Problem(404)` from `require`), and it ends the
  re-check's poison-row stall. It is wrong for transient ones (SF2).
- **Peer answers.** The real problem is how the table sorts them: by status code, not by whether the answer is about the
  row or about the peer (MF1).
- **The SQL.** The selection is right for paired peers that have a `peer_delivery` row. Peers paired before the
  migration have none, and the inner join drops them silently (MF2).

**`federation.lock` against `serve --sync`: sound for what it covers.** A whole-life flock in `federate` and in
`serve --sync` stops two lifespan workers. `federation-listen` doesn't need the lock. It never runs `sync_once`, and its
`collect()` is serialized by the gate and `INSERT OR IGNORE` against the UNIQUE key (federation.py:76; peer_store.py:36).
The gap is the browser route `POST /api/sync` (SF3).

**The pairing code: sound as a value.**
- 128 bits over the canonical whole card. `canonical()` is deterministic (identity.py:20-25), so the `card --pull`
  stdout, re-read and canonicalized by `pair`, gives the same code.
- `connections` can recompute it. `peers.card` keeps the first imported card (federation.py:35, the `ON CONFLICT` path
  sets only `paired`), and the participant comes from `remote_contacts` (federation.py:51). The trust keys can't change
  (federation.py:33), and neither can `version` or `delivery`.
- Typing the other side's code is the right act. But it is undermined by the import surfaces showing the code first
  (SF4).

**The per-envelope boundary, with the gate per row: sound and correctly documented.**
- `_prepare` is already one gate-holding transaction (db.py:100-104), so taking the gate directly around it adds only a
  place for the test hook.
- The weaker boundary is stated plainly: a withdrawal that commits after a row is prepared goes out as the next pull's
  `room.withdraw`. The first review offered that as acceptable when it is documented in PROTOCOL.md, which §9 does.
- Acks are applied in step 1, before the walk in step 3. So a returned row that is withdrawn later still ends
  `delivered` when its ack arrives, which is the truth.

**§5, the rate-scaled deadline: sound.**
- The arithmetic holds: 5.8 MB at 64 KiB/s is about 88 s, plus 10 s to the headers.
- The worst-case embedded envelope fits the cap, just:
  - base64 of 4 MiB is 5,592,408 bytes;
  - a 100,000-character body of control characters re-escapes to about 0.7 MB;
  - the total is about 6.33 MB, against 6,356,992.
  - State that, so a later body or attachment limit change doesn't silently break the cap (N6).
- Missing: a test that a stalled response still ends (SF7), and handling for a reply without `Content-Length` (N6).

## New must-fix

**MF1. §7 sorts peer answers by status code, so one row-scoped refusal stalls a peer for ever, and on pull it is
re-offered for ever** (spec §6, §7; federation.py:291-292, 336-339, 352, 358-362, 369, 401-405, 412).
- **What the table says.** Under §7, "any other 4xx" from the peer is `failed` with a peer failure. The peer then backs
  off up to 3600 s, and "that peer's other rows wait".
  - The failing row is still the oldest by `event_seq`, so it is tried first when the peer is next due. It fails
    again, and the backoff climbs.
  - Every other row for that peer, from every local user, waits for ever.
  - Today the same row burns its 8 attempts in about 254 s and then gets out of the way (federation.py:164). So this
    is a regression for existing peers, and it breaks Goal 2.
- **These answers are about one row.** `receive` gives row-scoped 403s and 409s that never clear by retrying:
  - 403 "Unknown remote participant" (federation.py:291-292);
  - "Invalid room authority" and "Recipient absent from roster" (:336-339);
  - "Resource owner cannot change" (:352);
  - 409 "New participants require a new linked room" and "Revision already used" (:358-362);
  - "Message ID already used" (:369, :412);
  - "Room membership required" (:404-405).
- **The first is ordinary on the Pi.**
  - Any local user can put any paired remote contact into a room or a layer audience (`_known_contacts`,
    peer_store.py:42-46; `contacts()`, :48-52).
  - A room event's actor is the room's owner (federation.py:128), and a layer event's actor is its owner (:101).
  - So the first room with a Tardis contact that is owned by a ship, or by anyone whose card Tardis never imported,
    stops all Pi-to-Tardis delivery.
- **Pull has the mirror image.** §6 refuses only the §7 terminal codes, and "anything else is neither, and it is
  offered again".
  - Such a row stays `pending` at the head of the walk, so every round returns it again.
  - With 20 of them, `limit` is spent on the same rows for ever.
  - With one over the budget, the single over-budget envelope is resent every round, up to 5.8 MB, 10 rounds a minute,
    and nothing behind it arrives.
- **Fix (mechanical):**
  - Name the peer-scoped answers. These stay `failed` with a peer failure:
    - network failures, any 5xx, and a 2xx without `ok`;
    - 401, 404, 408, 421, 425 and 429;
    - 403 "Unknown or unpaired peer" and "Peer authentication failed" (identity.py:187);
    - 403 "Unrecognized host" and "Same-origin request required" (app.py:34, :43);
    - 403 "Federation requires HTTPS" (peer_routes.py:80).
  - Every other 4xx means the peer answered about this row. Make it `refused`, with `last_error` holding the status
    and message, and a peer reset. The row's author can retry it once the cause is fixed.
  - The puller refuses every 4xx `Problem` from `receive` except the peer-scoped ones, as the first review's S7 said.
  - If you'd rather keep these rows automatic, the alternative is `failed` with a row-level due time back in the SQL
    `WHERE`. That is more machinery for the same result.
- **Tests:**
  - A row answered 403 "Unknown remote participant" doesn't put its peer in backoff, and the row behind it is delivered
    in the same pass.
  - On pull, a row whose `receive` gives such a 403 comes back `refused` on the listener, and the next row arrives.

**MF2. `sync_once` inner-joins `peer_delivery`, which nothing fills for existing pairings** (spec §7, §9; db.py:82-83).
- §7 copies `mode` "from the card at pairing", and the selection is `… JOIN peer_delivery USING(peer_id) WHERE …
  peer_delivery.mode = 'push'`. §9's migration creates the table and fills nothing.
- **Existing pairings stop.** Every peer paired before the upgrade has no row, so its pending and failed rows are never
  selected again. There is no error: they just stay pending.
- **Restores do the same.** A backup from before the migration comes back the same way. The migration runs on open and
  creates an empty table, and the restore reconcile never re-pairs (backups.py:734-764 only reports).
- **Fix:**
  - At every start, do what db.py:82-83 already does for `inbox_received`: `INSERT OR IGNORE INTO
    peer_delivery(peer_id, mode, failures) SELECT peer_id, COALESCE(json_extract(card, '$.delivery'), 'push'), 0
    FROM peers`.
  - `pair()` upserts the row on both of its paths, the new peer and the `ON CONFLICT` re-pair (federation.py:35).
- **Test:** a store with a paired peer and a pending row, and no `peer_delivery` row, delivers that row after the
  store is reopened.

## New should-fix

**SF1. A pin mismatch is peer-scoped, but §7 refuses the row and resets the peer** (§7's "transport" row; §3).
- **What happens.** With `CERT_NONE`, every certificate that isn't the pinned one reaches the compare. That includes a
  `tailscale serve` TCP forward pointed at the wrong backend, another TLS service on 7437, and a peer after
  `station-new-identity`.
- **Every row goes.** Each mismatch makes the row `refused` and the peer "reachable: reset", and the next row is tried
  at once. So within a few passes every queued row for that peer is refused.
- **Nobody is told.** `failures` stays 0, so §8's "failed for a day" notice never fires.
- **Recovery is slow.** It takes one Retry per row, and only by each row's author (federation.py:267-268).
- **`failed` would be just as safe.** The pin compare comes before any write, so nothing reaches the wrong server
  either way.
- **Fix:**
  - A mismatch is `failed` with a peer failure, and `connections` shows "certificate differs" for that peer.
  - Say what a pull does on a mismatch: a peer failure and the same warning. §6 doesn't say.
- Today the mismatch is `Problem(403)` and burns 8 attempts (transport.py:66-67), so this is not a regression. But it
  goes against Goal 2's own reasoning, and SF11's "states, not decisions".

**SF2. A transient `sqlite3.Error` becomes terminal** (§7, the second local row).
- **The lock is real on the Pi.**
  - The nightly backup reads the live database outside the gate, holding a SHARED lock through `source.backup(copy,
    pages=-1)` (backups.py:222-227).
  - A writer waits 30 s and then gets `OperationalError: database is locked` (db.py:109).
  - A row's first `_prepare` writes its envelope (federation.py:153), so it can hit exactly this.
- **Fix:** keep `IntegrityError`, `KeyError`, `ValueError` and local `Problem`s as `refused`. Make
  `sqlite3.OperationalError` (locked, busy, I/O, full) `failed` and neutral.

**SF3. "Check delivery now" runs `sync_once` outside `federation.lock`** (peer_routes.py:67-71; spec §1, §7).
- `POST /api/sync` calls `fed.sync_once` in the `serve` process. On the Pi, `serve` runs without `--sync` and so
  without the lock, beside `federate`, which is the double send and double backoff the lock exists to prevent.
- §7's "makes every peer due" may mean replacing that call, but it doesn't say so.
- **Fix:** the route makes peers due and returns status. It runs `sync_once` only in a process that holds the lock.
- **Test:** a `serve` without `--sync`, with `federate` holding the lock, never dials on "Check delivery now".

**SF4. Typing the code is not yet a person's act** (spec §2).
- **The import screen shows the answer.** §2 has "the browser's pair preview and `pair --card` show the code of the
  card being imported" and then asks for the other side's code. A person, or a ship, can type the code the importing
  screen just showed, which is the fingerprint echo of N14 again (app.js:1992).
- **Nothing stops a ship.**
  - `--as` is a bare username (`_operator`, ships.py:201-206).
  - The code is computable from the card file itself, as `sha256(canonical(card))[:32]`.
  - So a ship can run `pair --card F --as andy` and pipe in the right code. "So a ship can't confirm for him" is a
    rule, not a mechanism.
- **Fix:**
  - Don't show the imported card's code before it is typed. Show it in `connections` after pairing, and in the
    mismatch message. Test 2 can compare `card --pull`'s code with `connections`' instead of the preview's.
  - Have `pair` read the code from `/dev/tty` and refuse when there is none. A ship's Bash has no terminal. That
    gives section 7's "Andy, typing in a session's own terminal" a mechanism.
  - Add the rule to CLAUDE.md beside `station-approve`.

**SF5. Identities that exist at migration time have no mode** (§1, SF2).
- "The first `card --pull` sets `pull`." On the Pi or Tardis, whose v1 push cards may already be out, one mistaken
  `card --pull` makes the station a pull peer for good:
  - `federate` starts pulling;
  - the station refuses the Mac's pull card;
  - no command changes the mode back.
- **Fix:** `card --pull` refuses an identity that existed before the command, or a store with any `peers` row, unless
  the mode is already `pull`. §2 already says a pull peer is a new data directory with a new identity.

**SF6. The 200-row walk can outlast the puller's 10 s header deadline on the Pi** (§4 step 3, §5).
- **The cost per row.** Each obsolete row costs a `_prepare` transaction, then a second committed transaction for
  `withdrawn`. On the Pi's SD card, in the default rollback journal (db.py:109-115), each commit is several fsyncs.
- **The total.** 200 rows can take 10-20 s. That is the re-check's SF8 scenario, which the 200 cap was meant to bound.
- **The effect.** The puller times out and backs off, and its retry can hit "busy". It heals, because the listener
  commits its progress, but slowly.
- Test 9 runs on a fast disk and can't show this.
- **Fix:** mark `withdrawn` and `refused` in the same transaction as the check, and stop the walk after about 5 s as
  well as after 200 rows. Count that in `more`.

**SF7. Tests that can't fail, and tests that are missing** (§10).
- **Test 9, second bullet, can't fail without a deadline.** With no deadline at all it still passes.
  - Add a stall test: headers, then fewer bytes than 64 KiB/s allows, ends by the scaled deadline.
  - At 80 KiB/s, 5.8 MB takes about 71 s of wall time. Make the rate injectable, so both tests run on a smaller body
    in under a few seconds.
- **The browser route.** `POST /api/connections/pair` must check the typed code on the server.
  - Test that a wrong code is refused.
  - Test that a request carrying only the old `fingerprint` field is refused.
  - "`pair` refuses a mistyped code" reads as the CLI only.
- **The new must-fixes, SF1 and SF3:**
  - MF1's two tests;
  - MF2's reopened-store test;
  - a pin mismatch is `failed` with a peer failure, on push and on pull;
  - SF3's lock test.
- **Test 10's lists.** Add a 2xx whose body `parse()` refuses, which must be `failed` and not a local 400 (N9).

## Nits

1. **`CERT_NONE` order.** Set `check_hostname=False` before `verify_mode=CERT_NONE`; the other order raises
   `ValueError`. Treat `getpeercert(binary_form=True)` returning `None` as a pin failure.
2. **A stale reason in §3.** "It does no Host check, since its 403 would otherwise be terminal" no longer holds, since
   §7 doesn't make 403 terminal. Keep the rule, and change the reason: the listener has no browser to protect.
3. **Typing the code.** Compare it case-insensitively, ignoring spaces and dashes, since it is shown in groups of four.
4. **`connections`' code after a rename.** It is the code of the card as imported. After the participant renames
   themselves, the exporter's `card` prints a different code. Say so, or a later check looks like tampering.
5. **The pull handler.** Make it a plain `def` run in the threadpool. The gate is a per-thread flock with a per-process
   `RLock` (dispatch.py:14-35), and an `async def` would hold it on the event loop.
6. **§5's edges.**
   - Refuse a pull reply without `Content-Length`, or with one above the cap, before reading the body.
   - State the worst case for the embedded envelope (about 6.33 MB against 6,356,992). Then a later body or
     attachment limit change has to revisit the cap.
7. **Rounds delay pushes.** Up to 10 rounds, each up to about 100 s on a slow link, run in the same loop as the Mac's
   `sync_once`, so the Mac's replies can wait minutes. Say that this is accepted, or push between rounds. The
   re-check's S6 asked for this.
8. **Rollback.**
   - Stop and disable the two new units first: main has no `federate` or `federation-listen` command, so they would
     crash-loop and alert.
   - `refused` rows show as "Saved here" on main (app.js:487). That is cosmetic.
9. **`send_pinned` and `pull_pinned`.** Wrap exceptions raised inside `prepare()`, so the table can tell a local
   failure from a transport one. A 2xx whose body `parse()` refuses (transport.py:88) is "a 2xx without `ok`", not a
   local 400.
10. **A foreign `origin` (§6).** Dropping such an envelope leaves the listener's row pending for ever. Refuse it with
    400 instead.
11. **§9, where Andy reads a station's code.** On the Pi and Tardis it is `card --endpoint`'s stderr in his own SSH
    terminal, since their browsers can't show a card (see the re-check's MF1 row above).
12. **Kept acks over 100.** If kept acks and refusals exceed 100 after failures, send them in `limit` 0 batches.
13. **`peer_delivery` on unpair and re-pair.** Reset `failures` and `next_attempt` when a peer is re-paired.
14. **`serve --sync`'s worker** still has no per-pass `try` (peer_routes.py:12-18), so one exception from `collect()`
    ends it silently. `federate` gets one; give it the same.
