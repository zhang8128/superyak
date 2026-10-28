Verdict: APPROVE WITH CHANGES

# Review: federation pull implementation plan, revision 1

Fresh reviewer, 2026-10-28. I took no part in writing the plan, the spec or its three reviews. I read the plan
(`docs/superpowers/plans/2026-10-28-federation-pull.md`, revision 1), the approved spec (revision 4) and the three
spec reviews. I checked them against the worktree `tardis/pairing-code` at 48981f67: `peer/superyak_peer/` (transport,
federation, identity, peer_store, db, dispatch, signatures, peer_routes, app, door, `__main__`, files, common, ships,
system_author, static/app.js), `peer/tests/` (transport, federation, restore, browser, cli, packaging, station_units),
`peer/pyproject.toml`, `peer/scripts/two_peer_check.py`, the `Makefile` and `docs/station-restore.md`. I ran one small
script on SQLite 3.53 and the repo's Python to check the SQL and the size arithmetic. Its numbers are quoted below.

**What the verdict means.** The architecture is right. So are most of the decisions and nearly every statement about
today's code. Three things must change before Task 0 (MF1-MF3). Each has a small, concrete fix, given below. Apply them
as written and the build can start without another review round. If any of them is resolved differently, it goes back
to a reviewer. The should-fixes can be answered in the plan's next revision. None of them changes the spec.

## Must-fix

**MF1. Nothing tests that a pull checks the pin before it writes. A signed pull request works as a bearer credential
for 300 s.** (Plan: Task 3, group 4, third bullet; Task 7, last bullet; the mutant "the pin compared after the write".)
- **What the plan tests.** The "zero application bytes" test is named only for "a dial" in Task 3, which is
  `send_pinned`'s group. Task 7 checks only a pull mismatch's *outcome*: a peer failure, with "certificate differs". The
  mutant list doesn't say which function the mutant is applied to. `pull_pinned` is new code with its own path,
  response cap and deadline. Nothing listed fails if it writes the request before the compare.
- **Why it matters more on pull than on push.**
  - The listener never authenticates the TLS client. A pull is authorised only by checks 2-6: the signature, `at`,
    the nonce and the destination (spec §4).
  - Say a request reaches the wrong server: a `tailscale serve` forward pointed at the wrong backend, another TLS
    service on 7437, or a peer after `station-new-identity` (check 3's SF1 list).
  - That server can replay the request to the real listener within 300 s. The destination matches, and the nonce is
    fresh because the original never arrived.
  - So the listener answers *it* with the pull peer's envelopes: private content, up to the signed `limit` and
    `budget`.
  - On push, writing early leaks one envelope. On pull, it hands out a key to the queue.
- **Fix.**
  - Have one dial helper, for example `_pinned_socket(card, deadline)`, that connects, completes the handshake and
    compares the pin. Use it in both `send_pinned` and `pull_pinned`, and say so in the plan.
  - Parametrize the zero-application-bytes test over both functions.
  - Add the mutant "`pull_pinned` writes the request before the pin compare".

**MF2. No test pins the pull route's main confidentiality property: a pull returns only the origin's rows.** (Plan:
§4 "the walk"; Task 5; the mutant list.)
- **Why the walk's filter is the only guard.**
  - `_prepare` builds whatever row it is given, addressed to that row's own contact (federation.py:209,
    `destination=contact['peer_id']`). It doesn't know who is pulling.
  - So the walk's `WHERE` clause alone keeps peer Y's envelopes out of peer X's response.
  - If that filter is wrong (it joins on the contact only, or drops the peer predicate), X receives Y's signed
    plaintext. X's `receive` then refuses it on destination, but X has already read it.
- **What the plan has.** Task 5 tests only "an ack naming another peer's row changes nothing". That covers acks, not
  the walk.
- **Fix.**
  - Add a test with a listener holding rows for two pull peers and one push peer.
  - Each puller gets only envelopes addressed to it.
  - `more` counts only its own rows.
  - Neither puller's walk touches the push peer's rows.
  - Add the mutant "walk without the origin predicate".

**MF3. P2's "written with INSERT only, so a second write raises" breaks every re-export and every restart.** (Plan:
P2; Task 2, "written once and refused twice".)
- **Where the mode is written more than once.**
  - `card --endpoint` is run again to re-export: deploy step 1 "re-exports each card".
  - `serve --federation-endpoint` writes the mode at every start (README.md:131, API.md:652).
  - `card --pull` re-exports after pairing. The mode is already `pull` then, and §1 allows it.
- **What a literal INSERT does.**
  - The second run raises `sqlite3.IntegrityError`.
  - `main()` catches only `(Problem, ValueError, OSError)` (`__main__.py`:642), so it ends in a traceback.
  - On a push station, the lighthouse-style `serve` stops coming up after its first restart.
- **What the test misses.** Task 2's test can't tell a same-mode rewrite from a mode change.
- **Fix.**
  - Run `INSERT OR IGNORE INTO peer_meta VALUES('federation_mode', ?)`, then read the value back in the same
    transaction.
  - The same mode is a no-op. A different mode raises `ValueError` naming the stored mode.
  - Tests:
    - `card --endpoint` twice, `card --pull` twice (the second after pairing), and two starts of
      `serve --federation-endpoint` all succeed;
    - each cross-mode case is refused.

## Should-fix

**SF1. P12 stops the rounds on an empty response, which undoes `more`'s purpose.** (P12; spec §4 "Response", check 3 SF6.)
- The spec makes `more` true when the walk stopped at 200 rows or about 5 s, so that the puller carries on.
- A walk that only withdrew or refused rows returns `envelopes: []` with `more: true`. Under P12 that round "brings
  nothing new", so the loop ends and the next pull waits 60 s.
- With 1,000 obsolete rows at the head, live rows wait about 5 minutes. On the Pi's SD card, where 5 s may cover far
  fewer than 200 rows, they wait longer.
- **Fix.** End the loop only when the response carried envelopes and none of them gave a new ack or refusal. An empty
  response with `more` goes on, still bounded by the 10 rounds.
- **Test.** 300 obsolete rows, then one live row, all pulled in one `pull_once`.

**SF2. On a pull peer, failing pushes can stop pulls entirely, which falsifies P4's own claim.** (P4: "a pull at least
every 300 s whatever pushes did"; federate: "skipping peers in backoff".)
- **How it happens.**
  - A pass runs `sync_once` and then the due pulls, and both share the listener's one `peer_delivery` row.
  - When the backoff expires, `sync_once` pushes first. The push fails and re-arms `next_attempt`, so the pull step
    finds the peer in backoff and skips it, every time.
  - So a persistent peer-scoped push failure that doesn't affect `/federation/pull` means the Mac never pulls from
    that listener. One example is a 5xx on one poison row: a bug in `receive`, since 5xx is peer-scoped by §7.
  - Then nothing reaches the Mac from that listener, not just that row's queue.
- **Fix.**
  - In pull mode, pull before pushing in each pass.
  - Give the pull its own due time: 60 s, the triggers, or `next_attempt` after a *pull* failure.
  - A push failure must never postpone a pull past 300 s.
- **Test.** A listener whose events route answers 500 is still pulled within 300 s, and its envelopes arrive.

**SF3. P7 doesn't cover every answer to the pull itself.** (P7; `pull_pinned`.)
- **What's missing.** P7 names 400, 403, 404, 5xx, network and pin. It leaves out:
  - a 2xx `PeerAnswer`: no `ok`, a body `parse()` refuses, or a body shorter than its `Content-Length`;
  - a missing or over-cap `Content-Length`;
  - 401, 408, 413, 421, 425 and 429.
- **A stalled response doesn't raise.**
  - When the deadline timer shuts the socket down mid-body, `HTTPResponse.read(amt)` returns the bytes it has at EOF
    without raising `IncompleteRead`.
  - Today that becomes `Problem(400)` from `parse()` (transport.py:85-88; `test_trickling_response_has_total_deadline`
    relies on it). Under the plan it becomes a 2xx `PeerAnswer`, which P7 doesn't classify.
- **Fix.**
  - A body shorter than its declared length raises `TimeoutError`, a network failure.
  - A 2xx `PeerAnswer`, a missing or over-cap length, and 401, 408, 421, 425 and 429 are peer failures under P4.
  - Any other 4xx is handled like 400: logged, acks kept, next pull at 60 s.
  - State where the 404's 5-minute wait lives: in `federate`'s memory, never in `peer_delivery`. Written there, it
    would also delay pushes to an older listener that simply has no pull route.

**SF4. P5's test isn't the worst case. Control characters cost the most, not `"`.** (P5; Task 6.)
- **Cost per character.** In the response, a body character costs 7 bytes when it is a control character
  (`\u0001` → `\\u0001`), and 4 bytes when it is `"` or `\`.
  - `text()` allows control characters in the body (100,000 characters) and in the title (200; common.py:41-44).
  - File names allow no escapes (`[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}`, files.py:46).
- **Computed with the real limits:** 100 files totalling 4 MiB with 120-character names, a 100,000 × U+0001 body and a
  200 × U+0001 title.

  | Release | Envelope | Pull response | Margin under 6,356,992 |
  |---|---|---|---|
  | U+0001 body and title | 6,228,581 B (under `_prepare`'s 6,291,456) | 6,331,282 B | 25,710 B (24,686 under cap − 1 KiB) |
  | `"` body (the plan's) | 5,827,781 B | 6,030,682 B | 326,310 B |
- **What that means.** P5's claim holds, but by 25 KB. The plan's test leaves 325 KB of slack, so it would still pass
  after a limit change that breaks the real worst case.
- **Fix.**
  - Use the U+0001 release in Task 6.
  - Put these numbers in P5 and in PROTOCOL.md, so a later change to the body, title or attachment limits has to
    revisit the cap (check 3 N6).

**SF5. P8's mechanism doesn't do what P8 says.** (P8; signatures.py:16-19, 30-35.)
- **What G4b checks.** It refuses only when `identity.json` is missing *and* the store holds signed records:
  instructions revisions, or signed grants.
- **Why that misses the Mac.**
  - A pull peer usually holds no signed records, so G4b passes.
  - Once the mode is `pull`, §1's "identity existed before" refusal no longer applies.
  - So `card --pull` on a Mac whose `identity.json` was lost silently makes a new identity, which is the case P8
    exists to stop.
- **Fix.**
  - Once `federation_mode` is set, `card --pull` and `card --endpoint` require `identity.json` and never create one.
  - Only the first card command, with the mode unset, creates an identity.
- **Test.** On a pull peer with `peers` rows, delete `identity.json`. `card --pull` is refused, and no
  `identity.json` appears.

**SF6. The `card --pull` peers-check test can't catch its mutant.** (Task 8, second bullet; the mutant "`card --pull`
skipping the `peers` check".)
- "`card --pull` on an identity with `peers` rows" is already refused by the "identity existed before" rule. So a
  version without the peers check still passes the test.
- **Fix.** Build the store by pairing through the CLI before any card exists. `pair` works with `NO_IDENTITY`
  (`federation_here`, `__main__.py`:256-261). The store then has a `peers` row, no `identity.json` and no mode, and
  `card --pull` must be refused.

**SF7. Decide what an in-process `send=` raises.** (classify; Tasks 4, 5 and 7, which run "in process, with `send=`".)
- **The conflict.**
  - `deliver()` (test_federation.py:25-26), test_browser and two_peer_check all pass `receive`'s bare `Problem`
    straight out of `send`.
  - Under the plan's classify, a bare `Problem` is "an exception the table doesn't name": `failed`, with a peer failure.
  - So the in-process tests would test a different classification from the HTTP path. Task 4's "403 Unknown remote
    participant is refused and resets the peer" could not pass through `send=`.
  - The new per-peer backoff can also change existing tests in which one refusal precedes more `deliver()` calls.
- **Fix.**
  - `sync_once` and `pull_once` convert a `Problem` raised by a `send=` hook into `PeerAnswer(status, message)`. That
    is unambiguous, since local exceptions arrive wrapped in `Local`.
  - Say which exception `send_pinned` raises for its own refusals (an invalid card, or no endpoint), and how that is
    classified.

**SF8. P11 breaks Andy's two-peer checker and a browser test, and the plan lists neither.** (P11; "Tests that change".)
- **The browser test.** `test_delivery_waiting_acknowledgement_refresh_and_unsaved_state` (test_browser.py:1406-1474)
  clicks "Check delivery now" and expects "Delivered". Its app is built without `sync_enabled` (test_browser.py:53), so
  under P11 the click never dials.
- **The checker.** `scripts/two_peer_check.py` serves without `--sync` (:141, :214). It relies on `POST /api/sync`
  delivering (:234-300), so every delivery check in it fails.
- **The UX.** Even with `--sync`, the POST returns before the woken pass runs, so the person sees stale status after
  "Delivery status refreshed" (app.js:2070).
- **Fix.**
  - In a `--sync` process, the POST waits, bounded at about 10 s, for the pass it woke to finish, then returns status.
  - Move the checker to `--sync` (or a `federate`), and the browser test to a sync-enabled app.
  - List both in the plan, with the "failed" label text the browser test asserts, which §8 changes to "Retrying".

**SF9. The restore classification names a category that doesn't exist.** (Plan: "`test_restore`'s table list
classifies".)
- **What the test has.** Exactly two lists: `RECONCILED_TABLES`, "read or changed by a step", and
  `COORDINATION_TABLES`, "copied as they are" (test_restore.py:1387-1398).
- **What the plan asks for.** `pull_nonces` "emptied on restore" needs a new reconcile step in backups.py, and the plan's
  "What changes" doesn't list backups.py.
- **Fix, either of these:**
  - add the step, list backups.py, and put `pull_nonces` in `RECONCILED_TABLES`; or
  - classify `pull_nonces` as coordination. A restored set of nonces is pruned by `at` on the next pull, and the
    restore itself takes longer than the 300 s replay window.
- Name the lists for `peer_delivery` and `peer_meta` too (coordination).

**SF10. The runbook needs the two new units on its disable line and in step 8, not only on the stop line.** (Units;
docs/station-restore.md.)
- **What the runbook promises.**
  - The restore keeps only the lighthouse and the door enabled, "so if the Pi restarts mid-restore only those two
    start again" (:32).
  - That's why :63 disables the ship, odo and wormhole.
  - Step 8 starts everything again in order (:188-196).
- **Why the stop line alone fails.** If `federate` and `federation-listen` are only stopped (:64), they stay enabled. A
  restart mid-restore then starts them, and they write into a half-restored database: `receive`, `serve_pull` and
  `sync_once` all write.
- **Fix.**
  - Add both units to the disable loop (:63).
  - Add them to step 8's `enable --now`, after the lighthouse, and to its `is-active` check (:195).
  - Have `test_station_units` check those lines.

**SF11. Deploying to Tardis with `make station-units` installs the Pi's whole unit set.** (Deploy step 1; Makefile:255-261.)
- **What the target does.**
  - It refuses without `$(STATION_DATA)/peer.sqlite3`, "station host only".
  - It enables the backup and restore-test timers.
  - It writes alert drop-ins for five services.
- **On Tardis,** that starts nightly backups and restore tests of its peer database, and adds drop-ins for units
  Tardis doesn't run.
- **Fix.**
  - Add a `federation-units` target that installs only the two units and their alert drop-in, with the data
    directory as a variable.
  - State each unit's `ExecStart` data directory.

**SF12. The release inventories list every file, and the plan doesn't touch them.** (pyproject.toml sdist
`only-include` from :33, wheel from :148: "list individual files, never source directories".)
- **What's missing.**
  - `listener.py` belongs in both inventories.
  - The new tests, the two units and the plist belong in the sdist, which `make peer-bundle` shares.
- **The check would miss it.** The packaging test's server start never imports `superyak_peer.listener`, because
  `__main__` imports it lazily. So "the wheel builds and imports `listener.py`" needs an explicit import in that test.
- **Fix.** Add `pyproject.toml` to "What changes", and add the import to the packaging test.

**SF13. `receive` can give a row-scoped 404, and §7 treats every 404 as peer-scoped.** (classify; federation.py:459.)
- **Where the 404 comes from.** `_reply` does `require(...rooms...)`, which raises `Problem(404, 'Not found')` for a
  reply to a room the receiver no longer has, for example after a restore from an older copy.
- **What that does.**
  - On push, the peer backs off hourly for ever, and every row behind it waits.
  - On pull, the row is offered again for ever. Twenty such rows at the head stop the pull peer's queue.
- **Fix, either of these:**
  - `_reply` raises `403 'Room recipient or epoch changed'` for a missing room, which is row-scoped; or
  - classify treats a 404 whose `error` is exactly "Not found" from `/federation/events` as row-scoped. The listener's
    catch-all 404 then needs a different body.
- **Test.** A reply to a missing room is refused, and the row behind it is delivered.

**SF14. `retry KEY --as USER` has no way to find KEY on the Mac.** (P10.)
- Nothing in the CLI lists deliveries, and the Mac has no browser (§1). So a `refused` row on the pull peer can't be
  found to retry.
- **Fix.** Add `deliveries --as USER`: `status()` as safe lines, with id, status, `last_error` and the peer's
  `next_attempt`. Run it after the same admin check.

## Nits

1. **"There is no meta table."** `system_meta(key, value)` exists (system_author.py:12). Either use it, or say why
   `peer_meta` is separate: the restore reconcile writes its mark into `system_meta` (backups.py:762-763).
2. **The row's `next_attempt` can't be NULL.** It is `NOT NULL DEFAULT 0` (peer_store.py:38), and setting it to NULL
   raises `IntegrityError` (checked). "Clears" must mean 0.
3. **Declare `peer_delivery`'s columns.**
   - `failures INTEGER NOT NULL DEFAULT 0`. Otherwise `NULL+1` stays NULL, `2**min(NULL,12)` is NULL, and a failing
     peer is due at once, with no backoff.
   - `mode TEXT NOT NULL CHECK(mode IN ('push','pull'))`.
4. **The backfill can stop the store opening.** `json_extract` raises "malformed JSON" on a card that isn't JSON
   (checked), which would stop every `Store()` open. Guard it with `json_valid(card)`.
5. **Base classes and the existing tests they affect.** Name `PeerAnswer`'s and `PinMismatch`'s base classes, and list
   the transport tests that change:
   - `test_exact_pin_…` (`match='fingerprint differs'`, :233);
   - `test_real_https_delivery_…` (`raises((OSError,Problem))`, :60-61);
   - `test_trickling_…` (:178).
6. **3xx is unnamed.** "Any status outside 200-599" leaves 3xx unclassified. Say instead: everything except a 2xx with
   `ok` and the non-listed 4xx statuses is peer-scoped.
7. **The busy retry.**
   - It must build a new request, with a new nonce and `at`. The busy request's nonce was committed at check 6, so
     reusing it gets "replay".
   - Say that the nonce commits before the busy check.
   - Say what a second "busy" does: no failure, and the next pull at 60 s.
8. **P13's wake.**
   - Measure the overrun of the sleep (from the end of one pass to the start of the next), not start to start. A pass
     with 10 slow rounds would otherwise read as a wake every time.
   - "A network change, at once" is dropped from what the ships agreed. Say so as a deviation.
9. **The `serve --sync` worker** (peer_routes.py:12-18) still has no per-pass `try` (check 3 nit 14). With the new SQL
   and writes, an `OperationalError` ends it silently.
10. **Rollback.** Disable and stop both units first (check 3 nit 8). Main has neither command, and both units are
    alerted, so they would crash-loop into Ops.
11. **The listener's handlers.** Run `receive` and `serve_pull` in a worker thread (check 3 nit 5). On the event loop,
    a 5 s walk blocks pushes, and "busy" can never happen.
12. **P4's test.** Compare against hard-coded lists, not the formula:
    - `[2,4,8,…,2048,3600,3600]`;
    - `[2,…,256,300,300,300,300,300]`.
13. **The scoped lists' tests.** Parametrize all five 403 strings and every listed status, so dropping one string is
    caught.
14. **A v2 card's null endpoint.** `pair_command`'s prompt (`__main__.py`:293-294) and the browser's pair preview
    (app.js:1057) print it as "None" or empty. Say "fetches from us".
15. **Deploy step 1.** Name Andy as the one who runs `card --endpoint` on the Pi and Tardis. Its stderr carries the code
    he will type on the Mac.
16. **Check the lighthouse unit has no `--sync`.** Otherwise whichever of it and `federate` starts second exits 1.
17. **The pull body cap.** With 100-character ids, which check 1 allows, a maximal request is 23,394 B, over the
    16 KiB cap (computed). With the real 32-hex ids it is 9,794 B. Either say the cap assumes `uid` ids, or narrow the
    ack id pattern to 32 hex.
18. **A mistyped `--data-dir`.** `federate` creates `federation.lock` in it before refusing. Check `peer.sqlite3`
    first, as `station-new-identity` does.
19. **Rounds delay pushes** (check 3 nit 7). Say that's accepted, or run `sync_once` between rounds.
20. **Spec items with no listed test:** "no Host check" (§3), "serve has no pull route" (§1), `connections()`'s new
    fields (§8), and "then `limit` 0 if acks remain" (§6).
21. **"`send_pinned` (97 lines)".** That's the file. `send_pinned` itself is 60 lines (transport.py:38-97).
22. **The Ops "failed for a day" notice.** "Failures > 0 and last success over a day old" fires on the first failure
    after a quiet day.
    - A `failing_since` column, set when failures go from 0 to 1 and cleared on reset, gives "failed for a day".
    - Say what a pull peer that has never pulled shows: fall back to its confirmation time.
23. **An envelope string that doesn't parse.** The puller can't read its origin. Pass it to `receive`, which refuses it
    with 400, instead of dropping it.
24. **`OperationalError` in the walk.** Leave the row as it is. Don't write in the transaction that raised it.
25. **State the puller's request values:** `limit` 20, `budget` 1 MiB (§5).

## Checked and found correct (no need to redo)

- **Statements about today's code.**
  - `sync_once`'s selection, its exception tuple and the per-row backoff, about 254 s in all (federation.py:223, :234,
    :237).
  - `_prepare` is one gate-holding transaction with one write, and every raise comes before it (federation.py:146-213;
    db.py:104-108). The gate is a re-entrant RLock plus an flock (dispatch.py).
  - `canonical`/`parse` and `MAX_ENVELOPE` (identity.py:18-48).
  - `{"error": …}` from the handler and both middlewares (app.py:79, :87, :291).
  - The five 403 strings exist exactly: federation.py:343/347, identity.py:202, app.py:79, :87, peer_routes.py:85.
  - The app.js:489 fallback, ships.py:418 and the runbook's stop line at station-restore.md:64.
- **The pin.**
  - The pin compare already comes before the gate and the write (transport.py:66-83).
  - `CERT_NONE` with TLS 1.3, `getpeercert(binary_form=True)` and SNI is sound, as check 3's experiment showed.
  - The Task 3 tests (a tailnet name through a patched `resolve`, expired and not-yet-valid certificates, a leaf signed
    by the pinned key) catch the `check_hostname` and `CERT_REQUIRED` mutants.
- **classify with `Local`.** It fits `send_pinned`'s structure, provided `Local` subclasses none of `OSError`, `Problem`
  or `HTTPException`. Unwrapping `HTTPException` is right: `RemoteDisconnected` is also an `OSError`, and
  `IncompleteRead` isn't.
- **P4's arithmetic.** With a 3,600 s cap, the waits are 2 to 2,048 s (4,094 s, about 68 min), then hourly. With a
  300 s cap, they are 2 to 256 s (510 s), then every 5 minutes.
- **P6.** It is sound. With `at` = t0+299 replayed at t0+598, the clock check passes (299 ≤ 300) and the nonce is kept,
  so the answer is 409. The arrival-plus-300 s mutant prunes the nonce and lets the replay through, so the test
  catches it.
- **The SQL.**
  - §7's selection runs with the extra `JOIN peer_delivery USING(peer_id)`: no ambiguity on SQLite 3.53.
  - The backfill gives `pull` for v2 cards and `push` for `'{}'` and v1 cards.
  - Mode and due-ness come before `LIMIT`, and the 25+25 starvation test catches the after-`LIMIT` mutant.
- **Rollback.**
  - No `INSERT INTO outbox VALUES` exists anywhere (checked). Pairing-code's positional inserts into `peers`,
    `remote_contacts` and `pairing_confirmations` are untouched by new tables.
  - Main's `send_pinned` refuses a v2 card with 400 (transport.py:39), and the pull takes `failed` rows afterwards.
- **The mode rules in `pair()`.** A v1 prior meets a v2 card with 409 even through `TRUST_KEYS`' endpoint, so there is
  no `KeyError`. A pull peer refuses a pull card. P14's upsert on both paths is sound.
- **P1, P3, P9, P10 and P14** are consistent with the spec. So are G4b for `federate` and `federation-listen`
  (signatures.py:38-50) and the whole-life `federation.lock`.
- **Coverage.** Every requirement in spec §1 and §3-§10, and every §10 test group, has a place in the plan, except the
  gaps named above (SF8, SF9, SF14 and nit 20).
- **Mutants caught by the listed tests:**
  - check 2 after the nonce insert;
  - busy before the signature;
  - nonce pruning by arrival;
  - the gate held across the walk;
  - mode after `LIMIT`;
  - both 403 misclassifications;
  - `check_hostname`;
  - `CERT_REQUIRED`;
  - the backfill removed;
  - the puller acking a peer-scoped answer;
  - `federate` binding a socket;
  - P5 removed, because the exact `last_error` differs.
- **Mutants not caught:** the pin after the write, on pull (MF1), and `card --pull` skipping the peers check (SF6).
- **No new way for a ship to pair or type a code.**
  - `pair()` still requires the typed code.
  - Nothing echoes an imported card's code.
  - `card --pull`'s code goes to the exporting terminal, and the deploy names Andy for it (see nit 15 for step 1).
  - The automated end-to-end test computes codes in-process, which is test code and not a ship acting on a live
    pairing.
