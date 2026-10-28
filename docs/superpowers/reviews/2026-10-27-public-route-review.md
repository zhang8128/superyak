Verdict: REQUEST CHANGES (2 must-fix, 9 should-fix, 10 nits)

# Review: the public route spec, revision 1

Fresh reviewer under station law section 3. I took no part in writing it. I reviewed
`docs/superpowers/specs/2026-10-27-public-route-design.md` at dad2275 against the code on that branch (main f536862),
the ship agent, and uvicorn 0.52.4 / Starlette 1.6.0 as locked in `peer/uv.lock`. Read-only. I made no requests to the
live station. Exploit detail is left out on purpose. Weaknesses are described only as far as a fix needs.

## What holds up

- **Classification is sound for the deployed topology.** `serve` trusts forwarded headers only from 127.0.0.1
  (`peer/superyak_peer/__main__.py:488`). tailscaled sets `X-Forwarded-For` from the connection's own source address.
  uvicorn 0.52.4 takes the rightmost entry it doesn't trust, so an internet client can't present a tailnet address. A
  forged `Tailscale-Funnel-Request` only makes a request more restricted. The tailnet ranges are right.
- I found no anonymous path left open. The allow-list covers the flows a person starts from outside. The invitation
  link needs only redeem and login (`static/app.js:1666-1675`, `1724-1728`). The docking confirm link keeps its code
  through sign-in, then uses session routes (`app.js:1662-1665`, `957-965`). Public layer pages use their two
  `/public/layers/...` routes. Allowing confirm with a session is right: it takes a session, CSRF and the code
  (`ships.py:163-169`).
- Validating in an ASGI middleware before the body is read is feasible. Everything it needs is in `scope['headers']`.
  The cost is one extra indexed lookup per public request that carries a cookie or key, and tailnet requests pay
  nothing. Should-fix 5 lists what the implementation has to get right.
- `access_log=False` on `serve`, the header for the docking secret, and leaving the door alone are all right.

## Must-fix

1. **§2 table, ship-key row, and §6.3: `/api/ships/me/*` is too narrow for phase 1. It breaks the ships phase 1
   exists to keep, and it can drop a reply.** The ship client also uses its key on `/api/me`, `/api/chats`,
   `/api/chats/{key}`, `.../messages`, `.../claims`, `.../board*`, `/api/ships/directory` and `/api/mentions`
   (`agent/superyak_agent/station.py:136-243`). The station accepts ships there through `member()`
   (`peer/superyak_peer/app.py:218-223, 245-247, 545-599, 623-625`). On the Funnel path (§5's own case for the Mac):
   - the watcher can't start (`watch.py:100` calls `me()`, `:108` calls `mentions()`);
   - the hook's room summary fails (`hook.py:568-569`), and so do the MCP read, post, claim, board and mentions tools;
   - `make dock` on a docked Mac stops with a traceback, because a 404 from `/api/me` is re-raised (`dock.py:59-63`);
   - **data loss:** if a run's reply is the call that goes out by the public route, the watcher treats the 404 as
     final. It logs, forgets the reply and marks the mention done (`watch.py:233-247`).

   **Fix:** in phase 1, a request with a **valid ship key** passes for any route. The route's own check still decides:
   `current_user` already refuses a bearer key with 403 (`app.py:90-91`), so person-only routes stay closed to ships.
   Phase 2 then removes that one line. Test 3 should call every `StationClient` method once over a public request.

2. **§2 "otherwise it gets 404": the browser needs 401 to notice that a session ended, so signed-in use over Funnel
   doesn't work as it does today (Goal 2).** `app.js` sends people back to sign-in only on 401:
   - `refresh` (`1148`);
   - the layer editor's sign-in-again panel, which keeps unsaved text and saves it after sign-in (`1214-1222`);
   - `loadDocking` (`963`);
   - grants (`778`, `784`), the board (`820`), participants (`1538`) and logout (`1621`).

   Sessions last 24 hours (`auth.py:100`). After an expiry, a revoke, or a logout in another tab, a public user would
   see "Not found" errors instead of the sign-in prompt, and the layer editor's sign-in-again path wouldn't open. Every
   first public visit would also show the sign-in page with "Not found" as its error (`app.js:1686-1695`).

   **Fix:** under `/api/`, answer **401 `{"error": "Sign in required"}`**, the same answer as `current_user`
   (`auth.py:110`), for every refused path whether or not the route exists. Answer 404 elsewhere. A uniform 401 hides
   as much as 404 does, because every route is already listed in the public `/assets/app.js`.
   - Boot still lands on sign-in: the `/api/local-demo` probe gets 401 and `showLogin("")` runs (`app.js:1681-1695`).
   - With must-fix 1 in place, a valid ship key never meets this refusal in phase 1, so `dock.py:62-65` ("401 means
     revoked, delete `station.json`") can't misfire. A made-up key gets 401, as today (`ships.py:106`).
   - **Test:** a public request with an expired cookie gets 401 on `GET /api/home` and on `PUT /api/layers/{key}`.

## Should-fix

1. **§3.2, §3.3: Goal 4 isn't met for public sign-ins.** The username-wide public backoff (30 an hour) and the
   global public budget (300 an hour) are holds that refuse even the right password.
   - **Thresholds are reachable:** at the per-source rates §3 keeps (8 per pair and 40 per source in 5 minutes), a
     few sources reach either one well inside the hour.
   - **The global hold blocks everyone:** it stops every public sign-in, which is Goal 2's conference case.
   - **Shared NAT:** people at one venue share an IPv4 source, so one guesser there can hold everyone's per-source
     budget.
   - **Andy's own claim:** "Andy can always sign in from his own machines" holds only on the tailnet path, and §5
     says his Mac sometimes takes the public path.

   Either restate Goal 4 with Andy's agreement ("can't lock anyone out of tailnet sign-in; public sign-in can be held
   for up to an hour"), or change the mechanism:
   - **Known-device cookie:** set at a successful sign-in, it exempts that browser from the username-wide and global
     holds (the OWASP device-cookie pattern).
   - **Cap concurrent hashing** (should-fix 3) instead of a global hold.
   - **Recovery:** a tailnet sign-in clears that username's public hold.

2. **§3.4: the counters race the hash.** If counters are read before the hash and written after it, concurrent
   guesses all see the same count under the limit, and all of them hash. A budget then becomes the limit plus the
   number of concurrent requests in each window.
   - **Reserve first:** increment every counter that applies in the first transaction, refusing if any is at its
     limit. Hash. On success, delete the pair's `user-source:` row and give back the others.
   - **Say what success clears.** Today it clears only `user:` (`auth.py:98`).
   - **Re-read the user row in the second transaction.** Check that the salt and hash haven't changed and that the
     row is still an active person. An activation can change the hash in between (`auth.py:215`).
   - **Test:** N concurrent wrong guesses from one source get at most 8 answers of 401 for that pair; the rest get 429.

3. **§3.4: moving the hash to a worker thread moves the stall without removing it.** `run_in_threadpool` shares
   anyio's default 40-thread limit with every `def` route. Each scrypt hash (n=16384, r=8) takes 16 MiB, so a burst
   can use about 640 MiB and queue every sync route behind it (the second half of Goal 4).
   - **Give login hashes their own small limiter** (1 or 2), and answer 429 without hashing when its queue is full.
   - **Run the counter transactions off the event loop too.** The login route is `async` (`app.py:186-189`), and the
     store gate is a blocking `flock` (`dispatch.py:22`). The simplest version runs all of `Store.login` in a worker,
     with the hash outside any transaction, under that limiter.

4. **§3.3: how sources are grouped into buckets.**
   - **Tailnet IPv6:** as written, the /64 rule also applies to the tailnet. Every tailnet IPv6 address of one format
     falls in a single /64 (`fd7a:115c:a1e0::/64` for current addresses). Every node that connects over IPv6 would
     share one `source:` and `user-source:` budget, so one member's failures would hold everyone, Andy included. That
     is a change to tailnet behaviour (Goal 3). Use the /64 for public sources only, and full addresses on the tailnet.
   - **IPv4-mapped addresses:** unmap `::ffff:a.b.c.d` before grouping. Otherwise every such client falls into `::/64`.
   - **Unreadable sources:** a missing client, or one that isn't an IP, is public and gets its own bucket.

5. **§2: how the middleware works.**
   - **There's no read-only transaction.** `Store.transaction` always takes the process-wide `flock` and
     `BEGIN IMMEDIATE` (`db.py:100-113`, `dispatch.py:16-27`). Say "a normal store transaction", or define a read path.
   - **"The way `ship_member` does" isn't side-effect free.** `ship_for_key` writes `last_used` and presence
     (`ships.py:107-109`). The middleware needs a lookup that writes nothing; otherwise both are written twice per
     request.
   - **Run the lookup in a worker thread.** The inbox wait's comment is the precedent (`app.py:267-269`).
   - **Catch errors in the middleware and refuse.** It sits outside FastAPI's exception handlers, so a `Problem` or a
     database error it raises becomes a 500.
   - **Add the security headers to its refusal.** The refusal bypasses `BrowserBoundary.secure_send`, so it needs
     the same headers added directly.

6. **§6: tests that can't fail, or are missing.**
   - **Route walk.** `GET /api/dockings/{key}` and `GET /api/access-requests/{key}` already answer 404 themselves when
     given made-up parameters (`ships.py:353-354`, `access_requests.py:55-56`). With must-fix 2 the answers differ
     (401). Otherwise, use a real id and secret, and assert that the key wasn't collected. Walk once with no
     credentials and once with a made-up bearer key, and include router-added and mounted routes.
   - **Classification.** Test through uvicorn's `ProxyHeadersMiddleware`, configured as `serve` configures it, with
     the client at 127.0.0.1 plus `X-Forwarded-For`. Otherwise the tests set client tuples uvicorn never produces. Add
     cases: several forwarded entries with a public one last; forwarded headers from an untrusted client are ignored;
     127.0.0.1 with no forwarded header is tailnet (by design: local processes).
   - **§6.6 can't pass as written.** Starlette's `TestClient` gives the client host `"testclient"`, which the
     positive check treats as public. There are 57 `TestClient(...)` constructions across 24 files in `peer/tests/`, conftest included. Say how they
     run as tailnet, for example a conftest helper that passes `client=('127.0.0.1', …)`. A non-IP host must never
     count as tailnet.
   - **Ships.** Add public calls to `/api/chats/{key}/messages`, `/api/me` and `/api/mentions` (must-fix 1).
   - **Login.** Add tests for concurrency (should-fix 2) and for tailnet IPv6 not being grouped into one source. Show
     that held attempts neither hash nor count. Show that a `user:` row from before the upgrade, at the limit, holds
     nobody afterwards.

7. **§2 "Closed to public requests", §5: docking from a tailnet machine that takes the public answer.** §5 keeps
   ship keys public because the Mac sometimes takes the public DNS answer. On those runs, the same Mac's `make dock`
   gets 404 from `POST /api/dockings` or from the status poll. It then stops with a `StationError` that nothing catches
   (`dock.py:123`, `140`; `agent/superyak_agent/__main__.py:172`). This also covers re-docking after a revoke and
   project docks.
   - **Keeping the route closed is right.** The spec should still say what happens on those runs.
   - **Preferred:** move phase 2's tailnet resolution into the dock client now.
   - **At least:** have dock print a `STATUS:` line that names the cause.
   - **Deploy check:** run §7's "`make dock` still reaches the station" from the Mac.

8. **§5, phase 2.**
   - **Define "every ship".** It should mean ships with an unrevoked key used in the last N days
     (`ship_keys.last_used`), project ships included. Odo and Wormhole on loopback aren't affected.
   - **Choose a refusal the agent retries.** In phase 2, a ship key on the public route needs an answer the agent
     retries, not one that makes it drop work or undock. `watch.py:238/256/309` treat 403, 404 and 409 as final.
     `dock.py:62-65` and `install.py:437,476` treat 401 as revoked. Something like 421 with a message would fit, plus
     an agent test.
   - **Size the client change.** Python's urllib has no per-request resolver. The client has to dial the MagicDNS
     answer while keeping the hostname for SNI and Host. That's doable, but it's more than a one-line change.

9. **Non-goals and §2: federation and other peers.** The "federation-pull spec" isn't in the repo (only
   `2026-10-14-federation-followups-design.md` exists). Cite where it is.
   - **Scope:** the middleware applies to every `serve`, including direct TLS binds with no proxy
     (`__main__.py:478`). There, every client that isn't on loopback or the tailnet becomes public.
   - **Federation:** `/federation/events` (`peer_routes.py:77-81`) from a non-tailnet peer is refused until that
     other listener exists.
   - Say so, and say whether any live peer depends on either.

## Nits

1. **§1:** count the Funnel header as public when it's present with any value, not only `?1`.
2. **§1: name the trust assumption.** A request from 127.0.0.1 with no forwarded header is tailnet, so anything that
   forwards raw TCP to the port is trusted, for example `tailscale serve --tcp` or `ssh -L`.
   `serve --host ::1 --proxy-headers` would have the same effect: the trusted proxy is `127.0.0.1` only, so a proxy on
   `::1` makes everything look like loopback. `serve` could refuse that combination.
3. **§2:**
   - Decide whether HEAD counts as GET for the shell and assets.
   - Match the allow-list against Starlette's route objects, not path prefixes.
   - Refuse websocket scopes on public requests.
4. **§2:**
   - `POST /api/logout` needs a session anyway (`app.py:324-326`), so listing it adds nothing.
   - The session row still admits `/federation/*`, so it is closed only to anonymous requests. Say "no anonymous".
5. **§2:** add a sentence and a test for the docking confirm link and the invitation link opened anonymously. Both
   work under the session row and the allow-list (see "What holds up").
6. **§3: build the counter keys unambiguously.** Login usernames are arbitrary text up to 254 characters
   (`auth.py:76`) and can contain `:`. Put the source first, or use a JSON array.
7. **§3: "old rows age out by their reset" isn't accurate.** Nothing deletes `login_attempts` rows. Old `user:` rows
   become inert, and any current hold ends at deploy. Delete rows whose reset has passed inside the counter
   transaction, which also keeps the new username-by-source keys bounded.
8. **§3:** keep the dummy hash for unknown names (`auth.py:89-90`) explicit, so the 401 takes the same time after the
   hash moves.
9. **§4:**
   - The access-request status poll also carries `?secret=` (`dock.py:84`). It goes to the door, whose access log is
     already off, so this is only worth a mention.
   - **Rollback:** a rolled-back station ignores the header, so dock clients from this commit can't collect a key
     until the station is deployed again. Note this in §7.
10. **§7:**
    - **Testing "through the public ingress":** a tailnet machine with MagicDNS resolves the name to the tailnet, so
      run that check from a device off the tailnet.
    - **Add live checks:** a ship key reaches `/api/chats` through Funnel (must-fix 1), and an expired session through
      Funnel brings up the sign-in page (must-fix 2).
