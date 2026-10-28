Verdict: APPROVE WITH CHANGES (1 must-fix, 6 should-fix, 13 nits)

# Recheck: the public route spec, revision 2

I'm a second fresh reviewer under station law section 3, and I took no part in writing the spec or its first review. I
reviewed `docs/superpowers/specs/2026-10-27-public-route-design.md` at 172501c against the code on that branch, the ship
agent, and uvicorn 0.52.4, Starlette 1.6.0, FastAPI 0.141.1 and anyio 4.15.1 as locked in `peer/uv.lock`. I read the
installed sources where behaviour mattered. This review was read-only and made no requests to the live station.
Weaknesses are described only as far as a fix needs.

## The first review's items

| Item | Status in revision 2 |
|---|---|
| M1 ship-key allowance too narrow | **Resolved.** A valid key passes for any route in phase 1. The route still decides: `current_user` refuses a key with 403 (`app.py:90-91`). With valid keys never refused, the watcher's 404-as-final path (`watch.py:233-247`) can't drop a reply. |
| M2 404 broke the browser | **Resolved.** Refused `/api/*` gets 401 "Sign in required". I checked `app.js`: boot (`1680-1695`; the `/api/local-demo` probe's 401 lands on `showLogin("")`), `refresh` (`1148`), the layer editor's sign-in-again panel (`1215`) and `loadDocking` (`963`) all keep working. |
| S1 Goal 4 | **Resolved for the holds, reopened by the limiter.** The device cookie, tailnet recovery and dropping the global hold answer it. But the shared login queue is a new global lockout (new must-fix 1), and Goal 4 still overclaims for same-source guessers (new should-fix 3). |
| S2 counters racing the hash | **Resolved in design.** Reserve first, give back on success, re-read in step 3. Its concurrency test can pass by luck (new should-fix 5). |
| S3 threadpool | **Resolved for the stall.** All of `Store.login` runs in a worker under a dedicated limiter. See new must-fix 1. |
| S4 buckets | **Resolved.** The /64 grouping is for public sources only, IPv4-mapped addresses are unmapped, and a non-IP source is public. |
| S5 middleware | **Resolved**, apart from what the error path answers and how far it reaches (new should-fix 1). |
| S6 tests | **Mostly resolved.** The conftest helper, classification through `ProxyHeadersMiddleware`, real ids and secrets, both walks, ships, IPv6 and old rows are all in. Some tests can still pass when the behaviour is wrong (new should-fix 5 and 6). |
| S7 docking over the public route | **Partly.** `POST /api/dockings` is handled. The status poll isn't, and the message misses the newcomer's case (new should-fix 2). |
| S8 phase 2 | **Resolved.** "Active" is defined, 421 is retryable, and the client change is sized. The dock client is the one exception (nit 9). |
| S9 federation and other `serve`s | **Resolved.** The citation checks out: branch `tardis/federation-pull` at 05c9ea7 holds `docs/superpowers/specs/2026-10-27-federation-pull-design.md`. Scope and the refusal are stated. |
| Nits 1-10 | **All resolved** in place. |

## What holds up

- **Classification.** In uvicorn 0.52.4, `get_trusted_client_address` walks the forwarded list from the right and takes
  the first untrusted entry, with 127.0.0.1 the only trusted proxy. An internet client therefore can't present a
  tailnet or loopback address. The Funnel header backs this up, and the §7 off-tailnet check (an anonymous
  `POST /api/dockings` gives 401) is the live proof. Run it before calling the fix done.
- **No anonymous path that acts stays open.** The allow-list holds only the login, redeem (it acts only with a valid
  token, `auth.py:205-223`), health, the shell, assets and the published layers. Dockings, access requests and
  `/federation/*` are closed to anonymous public requests. The only clients of those routes are `dock.py` and
  `app.js`, and the access-request flow goes to the door (`Makefile:23`, `dock.py:76-84`).
- **The known-device cookie is sound as an exemption from hold 3.** It is random, stored hashed, HttpOnly and bound to
  one user. It exempts only from the username-wide public hold, so a cookie for one account never helps against
  another. It grants no route access, and the middleware ignores it.
- **Reserve first is right.** Step 1 runs under the store's process-wide lock (`db.py:100-104`, `dispatch.py:154-165`),
  so no more than the limit can pass for any counter. Answering a held attempt before hashing removes the cost.
- **421 is already retryable in the watcher.** `watch.py:238`, `256` and `309` re-raise anything outside 403, 404 and
  409, and the reply is stored before posting (`watch.py:230-232`).

## Must-fix

1. **§3, the login limiter: one shared queue lets a public flood refuse tailnet sign-ins, and sign-ins from known
   browsers, with 429. That's a new global lockout, and it contradicts Goal 4.**
   - The limiter of 2 with a queue of 8 serves every sign-in. All of `Store.login` runs under it, step 1 included, so
     held attempts take queue places too.
   - A sustained burst of anonymous public sign-in attempts can keep more than ten in flight. Per-source holds don't
     prevent this: held attempts still pass through the queue, and public sources (IPv6 /64s above all) are cheap.
   - While the queue is full, Andy's tailnet sign-in, with the right password, gets 429. So does a browser that has
     signed in before. Goal 4 says neither can happen. Goal 3 is also affected: no tailnet sign-in is refused for
     capacity today.
   - This is still better than today, where the hash runs on the event loop (`app.py:186-189`) and a flood stalls the
     whole station. But the spec now promises more than this design gives.

   **Fix, to apply as written:**
   - **The public queue:** the limiter of 2 with a queue of 8 serves public sign-ins only.
   - **Tailnet sign-ins** use their own limiter: 1 at a time, with a queue of 4, which public requests never enter.
   - **Browsers that have signed in before:** choose one of these.
     - (a) A public sign-in presenting a `superyak_device` cookie that a side-effect-free read finds valid for the
       username uses a third limiter, also 1 at a time with a queue of 4. The read runs in a worker before queueing,
       like the middleware's reads.
     - (b) Goal 4 adds: "While a flood fills the public sign-in queue, public sign-ins, known browsers included, get
       429 until it ends."
   - **A full lane** answers 429 without hashing or counting.
   - **§6.7 adds:** with the public queue held full, a tailnet sign-in succeeds (and, with (a), so does a known-device
     public sign-in), and the refused public attempt neither hashes nor counts.

## Should-fix

1. **§2, "Any exception in the middleware refuses the request (401 or 404)": limit how far the guard reaches, and
   answer 503.**
   - **401 means "revoked" to the dock client.** `dock.py:58-65` deletes `station.json` when `me()` gets 401. So a
     transient database error in the public lookup would undock a docked machine running `make dock`. Its key would
     stay live on the station, and docking again would need approval.
   - **401 is also wrong for the browser** when the session is in fact valid.
   - **The guard can reach too far.** In FastAPI, user middleware sits between `ServerErrorMiddleware` and
     `ExceptionMiddleware` (`fastapi/applications.py:1033-1061`). Route exceptions other than `Problem` pass up
     through `public_route`. If the guard wraps the call into the app, every route error becomes a 401, tailnet
     requests included (Goal 3), and an error after the response has started breaks the send.
   - **Fix:** guard only the classification and the validity lookup, and answer an internal failure with
     `503 {"error": "Try again shortly"}` plus the security headers. Keep the call into the app outside the guard, so
     route errors reach the 500 handler as today.

2. **§4, the dock client on the public route.**
   - **The status poll is also refused.** `GET /api/dockings/{id}` gets 401 on public requests. A docking started over
     the tailnet and polled on a run that resolved publicly still stops with an uncaught `StationError` (`dock.py:123`).
     Treat a 401 there the same way: print the same STATUS line, keep `docking.json`, and add a test.
   - **The message misses newcomers.** `_reachable()` counts any HTTP answer as reachable (`dock.py:108-115`), and the
     public route answers 401. So a newly approved requester without Tailscale now lands on `refused-public`, not
     `waiting-for-station`. The message should name both causes: install Tailscale, sign in and accept the share link;
     on a tailnet machine, check MagicDNS.
   - **Say whether `refused-public` ends the run.** It isn't in `FINAL` (`dock.py:14`), so as `run()` stands
     (`dock.py:47-53`) it keeps polling until `--wait` runs out, then exits 3. State that it ends the run at once
     with 3.
   - **Update CLAUDE.md.** Its docking paragraph says to run `make dock` again on exit 3 until docked, so it should say
     that `refused-public` means stop and relay the message.

3. **Goal 4 still overclaims for browsers that have signed in before.**
   - **Holds 1 and 2 still apply to them.** The device cookie exempts only from hold 3, so someone guessing from the
     same public IPv4 address (shared NAT, CGNAT, a venue) or the same IPv6 /64 can hold a known browser, 5 minutes
     at a time.
   - **The /64 widens the shared bucket.** Many public Wi-Fi networks put every client in one /64. This is the right
     trade-off, but Goal 4 should be accurate.
   - **Fix, one of:**
     - (a) Add to Goal 4: "...except by someone guessing from that browser's own public address or IPv6 /64, 5 minutes
       at a time."
     - (b) Give the device cookie OWASP's full form: a valid cookie exempts its browser from holds 1-3, and that
       browser's failures count against its device token instead (for example, 8 in 5 minutes holds that token only).
       §3 cites the OWASP pattern, and this per-device limit is part of it.

4. **§3, the device cookie's lifecycle.** "Stored hashed per user" can be read as one token per user. Built that way,
   each sign-in would drop the exemption from every other browser the person uses. Say:
   - one row per browser;
   - a sign-in presenting a valid cookie keeps it (or rotates it in place) instead of adding a row;
   - expired rows are deleted, and there's a per-user cap;
   - logout keeps the cookie;
   - whether a valid-cookie browser's failures count toward hold 3 (or toward the token, under should-fix 3(b)).

5. **§6, tests that can pass when the behaviour is wrong.**
   - **§6.3, the walk:**
     - **The problem:** it asserts only the status. With a made-up bearer key, the `member()` routes answer 401
       themselves ("Invalid ship key", `ships.py:105-106`). With no credentials, every `current_user` route answers
       the same 401 "Sign in required" itself (`auth.py:109-110`).
     - **The fix:** assert the exact body and the security headers, or patch `store.session` and
       `store.ship_for_key` to fail during the walk, so any route handler that runs fails the test.
   - **§6.6, "writes nothing":**
     - **The problem:** the fixture clock is fixed (`conftest.py:7-8`), so a second write of `last_used` is
       invisible.
     - **The fix:** send a valid key to a route that refuses ship keys before any ship lookup (`GET /api/home` gets
       403 at `app.py:90-91`). Advance the clock, then assert that `last_used` and presence are unchanged.
   - **§6.7, the concurrency test:**
     - **The problem:** with only 2 concurrent, a read-then-write implementation goes past 8 only when two attempts
       straddle the limit at the same moment, so the test can pass by luck.
     - **The fix:** pause the hash (patch `password_hash` to wait on an event), and assert that the counter already
       shows the reservation while it's paused.
     - **Share one event loop.** Run concurrent requests inside one `with TestClient(app)`. Outside it, each request
       gets its own portal and event loop (`starlette/testclient.py:349`), and an anyio limiter shared across loops
       misbehaves.
   - **§6.4, the expired session:**
     - **The problem:** most session routes give the same 401 themselves.
     - **The fix:** also test a route that checks no session: an expired cookie on `POST /api/dockings` gets 401 and
       creates no docking. Also test `PUT /api/layers/{key}`, as the first review asked.

6. **§6, missing tests.**
   - **Allow-listed routes answer anonymous public requests normally:** `/`, `/public/`, `/assets/app.js`,
     `/api/health`, a published layer and its file, and `POST /api/login`. Matching the `/assets` `Mount` as a route
     object is the likeliest slip, and §7 checks only `/` and `/api/health`, so add `/assets/app.js` to the live
     checks.
   - **No exemption** from a device cookie for another user, an expired one, or a made-up one.
   - **Success gives back the reservation:** after 7 failures and a success, the source counter reads 7 and the pair
     row is gone. An activation between the hash and the re-read gives 401, and expired rows are deleted.

## Nits

1. **§2, middleware order.** "Sits first" means outermost, so it is added after `BrowserBoundary`: `add_middleware`
   inserts at the front (`app.py:148`). Match the allow-list before any lookup, since browsers send the session cookie
   with every asset.
2. **§2, parsing.** Read the cookie with Starlette's parser and the key with `bearer_key` (`app.py:84-86`), so the
   middleware sees what the route sees.
3. **§2, websockets.** Refuse a websocket by closing it, since no HTTP response is valid there. None exist today.
4. **§1, a missing client.** Say that a missing `scope['client']` counts as public.
5. **§3, the give-back.** Decrement only within the same window (the same `reset`), and never below zero.
6. **§3, expired rows.** Index `login_attempts(reset)` or bound the delete: step 1 runs under the process-wide store
   lock.
7. **§3, redeem.** `redeem` is an `async` route doing store work on the event loop (`app.py:354-357`). It's now one of
   only two anonymous POSTs, so run it in a worker too, with a valid token's hash under the public login limiter.
8. **Goal 4, the wait.** "May wait up to an hour" is really "while the attack goes on, an hour at a time". Someone who
   never uses the tailnet has no recovery except a known browser.
9. **§5, phase 2.** `dock.py:58-63` re-raises any status from `me()` other than 401, so a 421 stops `make dock` with a
   traceback. Include the dock client in "the agent treats 421 as retryable".
10. **§6.5, the list of routes.** The parenthetical leaves out `/api/chats`, the claims and release routes, and the
    board routes. Either complete it or say "including".
11. **§6, the device cookie in tests.** The cookie is always `Secure`, so tests that use it need an `https://`
    base URL; httpx won't send it to `http://testserver`.
12. **§7, `--host`.** `serve` will now refuse `--proxy-headers` with `--host localhost` or `::1`. Check the Pi unit's
    `ExecStart` before restarting, since the unit isn't in the repo.
13. **§6.7, the full queue.** "The limiter's full queue answers 429 without hashing" should add "and without counting".

## Applying these

Must-fix 1 is small and mechanical: one paragraph in §3, one test in §6.7, and, if option (b) is chosen, one sentence
in Goal 4. Applied exactly as written above, it needs no further review round. The should-fix items are also
self-contained and need no further round if applied as written. They should land before the build starts, because
should-fix 1 and 2 change behaviour the agent depends on, and should-fix 5 and 6 decide whether the tests can catch a
regression.
