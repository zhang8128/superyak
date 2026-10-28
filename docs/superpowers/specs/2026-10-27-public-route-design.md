# The public route: a login in front of everything

Tardis, 2026-10-27. **Revision 3, approved under station law section 3.**
- The first fresh review, of revision 1: REQUEST CHANGES ([review](../reviews/2026-10-27-public-route-review.md)).
- The second, of revision 2: APPROVE WITH CHANGES ([re-check](../reviews/2026-10-27-public-route-recheck.md)).
  Its one must-fix is applied here as written, which it says needs no further round. Its six should-fix items are
  applied too (§2, §3, §4, §6), choosing (a) for known browsers in the must-fix and (b) in should-fix 3.
Branch `tardis/funnel-hardening`, on main f536862, not pushed until the fix ships. Shaped in City of AI (f4556c73,
12d8997d, 945f7040, 774e1cd2, b12d9a66). The detailed audit stays in City of AI. This spec says what each check
enforces.

| Review item | Where revision 2 answers it |
|---|---|
| M1 the ship-key allowance was too narrow | §2: in phase 1 a valid ship key passes for any route |
| M2 a 404 broke the browser's sign-in | §2: refused `/api/*` gets 401 "Sign in required"; everything else gets 404 |
| S1 Goal 4 | Goal 4 restated; §3, the known-device cookie; tailnet sign-in clears a hold; no global hold |
| S2 counters racing the hash | §3, reserve first |
| S3 the threadpool | §3, sign-in lanes (public, tailnet and known browsers), with a full lane answering 429 |
| S4 buckets | §3, the /64 for public sources only, IPv4-mapped addresses unmapped, non-IP sources public |
| S5 the middleware | §2, how the check runs |
| S6 tests | §6 |
| S7 docking over the public route | §4 and §7 |
| S8 phase 2 | §5 |
| S9 federation and other `serve`s | Non-goals, §1 |
| Nits 1-10 | in place |

## Why

Andy, 2026-10-27, on Tailscale Funnel exposing the station's web app on port 443: "public is fine for now. as long as
there is a login."

An advisory audit found that content holds up. No anonymous request reads rooms, messages, files, accounts or titles.
But some anonymous routes act, and the login's guessing budget can be turned against its own users. This spec makes
Andy's sentence literally true: a public request reaches the login and what a signed-in person or a docked ship uses,
and nothing else.

## Goals

1. **Default deny for public requests.** They reach only what §2 lists, and a route added later starts closed.
2. **Signed-in use works over Funnel,** as it does today on the tailnet, including the browser's own handling of an
   expired session.
3. **Tailnet requests are unchanged.**
4. **Nobody can lock anyone out of the tailnet sign-in, or out of a browser that has signed in before.** Each has its
   own sign-in lane and its own counters (§3). A browser new to the station, on the public route, may wait up to an
   hour on a username under attack, or get 429 while a flood fills the public queue. Failed guesses never stall the
   station.
5. No secret lands in a log.

## Non-goals

- Turning Funnel on or off: that's Andy's switch.
- Two-factor sign-in.
- The door on 8443, which is unchanged.
- **Federation.** Pull and its own listener are in the approved federation-pull spec on branch
  `tardis/federation-pull` (05c9ea7), not yet merged.
  - Until that listener exists, `/federation/events` on the main app refuses anonymous public requests (a valid
    session or ship key passes it, as any route, §2).
  - No live peer depends on it: federation has carried no live traffic.

## 1. Which requests are public (nits 1, 2)

A request is **public** when any of these holds:
- it carries a `Tailscale-Funnel-Request` header, with any value. Tailscale sets that header on Funnel traffic and
  strips it from what clients send;
- its client address (`scope['client']`) isn't an IP address;
- its client address is neither loopback nor a tailnet address (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`). IPv4-mapped
  addresses are unmapped first.

`scope['client']` is what uvicorn's `ProxyHeadersMiddleware` sets. `serve` trusts forwarded headers from 127.0.0.1
only, and takes the rightmost untrusted entry, so an internet client can't pass as a tailnet address. A forged
Funnel header only restricts a request further.

Everything else is a **tailnet** request and is handled exactly as today.

**The trust assumption, named:** a request from 127.0.0.1 with no forwarded header is tailnet. So anything that
forwards raw TCP to the port is trusted, `tailscale serve --tcp` or `ssh -L` for example. `serve` refuses
`--proxy-headers` with a non-IPv4-loopback `--host`, since its trusted proxy is 127.0.0.1 only. The check applies to
every `serve`, including a direct TLS bind with no proxy, where every client off loopback and the tailnet is public.

## 2. What a public request may reach (M1, M2, S5, nits 3, 4, 5)

The `public_route` middleware sits first, before the body is read. A public request passes when one of these holds:

| Allowed | Why |
|---|---|
| `GET`/`HEAD /`, `/public/`, `/assets/*` | the app shell and its assets, no data |
| `GET /api/health` | `{"ok": true}` only |
| `POST /api/login` | the login itself |
| `POST /api/invitations/redeem` | an invitation link: a 256-bit token |
| `GET /public/layers/{key}`, `GET /public/layers/{layer_id}/files/{key}` | layers their owner published |
| any route, with a **valid session** | signed-in use (Goal 2) |
| any route, with a **valid ship key** | phase 1 (§5): ships reach `/api/me`, `/api/chats/*`, `/api/mentions` and `/api/ships/*`, and the route's own check still decides |

**What a refusal answers:**
- For `/api/*`: `401 {"error": "Sign in required"}`. That's what `app.js` acts on, so the sign-in page, an expired
  session and the layer editor's sign-in-again panel keep working.
- Anywhere else: 404 `{"error": "Not found"}`.
- Both carry the same security headers as `BrowserBoundary.secure_send`.
- Every route is already named in the public `app.js`, so the 401 hides nothing that's hidden today.

**Closed to anonymous public requests:** dockings and their status polls, access requests (the door on 8443 is their
public route), `/federation/*`, and anything §2's table doesn't list.

**What stays open from outside, deliberately:**
- An invitation link opened anonymously works: the shell, then `invitations/redeem`.
- A docking confirm link (`/#dock?code=…`) shows the shell and asks the person to sign in. Confirming needs a session,
  and a public request can no longer start a docking.

**How the check runs:**
- The allow-list is matched against Starlette's route objects, not path prefixes. Websocket scopes on public requests
  are refused.
- **"Valid" means checked, not present.** New store reads `session_is_valid(token)` and `ship_key_is_valid(key)` do
  the same lookups as `store.session` and `ship_for_key`, but **write nothing**: no `last_used`, no presence. The
  route's own check still runs afterwards, unchanged, and writes those as today.
- The lookup runs in a normal store transaction, in a worker thread (`run_in_threadpool`), as the inbox wait does,
  never on the event loop.
- **Only the classification and the validity lookup are guarded** (re-check should-fix 1).
  - An exception in either answers `503 {"error": "Try again shortly"}` with the security headers, and logs the
    exception's class.
  - It never answers 401 for an internal failure, since the dock client reads 401 as "revoked".
  - The call into the app stays outside the guard, so route errors reach the 500 handler as today, tailnet included.

## 3. The login (S1, S2, S3, S4, nits 6, 7, 8)

`Store.login` keeps its answers: 401 for a wrong name or password, 429 when held, the same for unknown and known
names, and the dummy hash for unknown names kept explicitly, so a 401 takes the same time either way.

**Buckets:**
- A **public** source is its IPv6 /64, or its full IPv4 address.
- A **tailnet** source is its full address, so tailnet nodes never share a bucket.
- A non-IP source is public and gets its own bucket.
- Counter keys are JSON arrays such as `["user-source", "public", source, username]`, unambiguous for any username.
  A source's keys name the request's class, public or tailnet, so a public and a tailnet failure never share a row
  (section 2 review should-fix 4): a Funnel request from a tailnet node has that node's address as its source.

**Holds:**
1. **Per (username, source):** 8 failures in 5 minutes, as today. Someone guessing from elsewhere no longer locks
   Andy out.
2. **Per source:** 40 failures in 5 minutes, as today's `source:` limit.
3. **Username-wide, public only:** after 30 public failures on one username in an hour, public sign-ins to that
   username from a browser without a known-device cookie wait out the hour.
4. **No global hold.** The sign-in lanes (below) bound the cost instead.

- **Known-device cookie,** the OWASP device-cookie pattern in full (re-check should-fix 3(b)):
  - A successful sign-in sets `superyak_device`: a random 256-bit token with HttpOnly, Secure, SameSite=Strict and a
    180-day life.
  - The token is stored hashed as **one row per browser** (user, token hash, expiry, failures, failure reset, attempts,
    attempt reset). A
    sign-in presenting a valid cookie keeps that row and extends it rather than adding one. Expired rows are deleted,
    with at most 20 rows per user (the oldest goes). Logout keeps the cookie.
  - A browser presenting a cookie valid for the username it signs into is exempt from holds 1-3. Its failures count
    against its own token instead: 8 in 5 minutes holds that token only, and they never count toward hold 3.
  - Its public sign-ins count against its token too, successes included: 8 in 5 minutes hold it, so one browser
    signing in over and over can't keep the known browsers' lane full (section 2 review should-fix 1). A success
    resets the failures, never the attempts.
  - A cookie for another user, an expired one or a made-up one exempts nothing.
- **Recovery:** a successful tailnet sign-in clears that username's public hold.

**Reserve first (S2), all of `Store.login` run in a worker thread in its lane (below):**
1. In a short transaction, delete expired `login_attempts` rows. Then, if any applicable hold is at its limit, answer
   429 **without hashing**. Otherwise increment every applicable counter, which reserves the attempt.
2. Outside any transaction, hash (the dummy hash for an unknown name).
3. In a second transaction, re-read the user row and check that the salt and hash haven't changed and that it's still
   an active person, since an activation can change the hash in between.
   - On success: delete the pair's `user-source` row, give back the reservation on the others, and create the session
     and device cookie.
   - On failure: keep the reservation as the counted failure.

**Sign-in lanes (S3, re-check must-fix 1):** login has its own limiters, so it never competes with sync routes for
anyio's shared threads.
- **Public sign-ins:** 2 at a time, with a queue of 8.
- **Tailnet sign-ins:** 1 at a time, with a queue of 4. Public requests never enter this lane.
- **Known browsers:** a public sign-in presenting a `superyak_device` cookie that a side-effect-free read finds valid
  for the username uses a third lane, 1 at a time with a queue of 4. The read runs in a worker before queueing, like
  the middleware's reads. It answers a held token 429, so that token enters no lane; `Store.login` holds it again.
- **A full lane** answers 429 without hashing or counting.

**Old rows:** today's `user:` and `source:` rows go inert at deploy. The new keys are different, so any current hold
ends at deploy, and expired rows are deleted in step 1.

## 4. Logs, and docking from the public route (S7, nit 9)

- `serve` runs uvicorn with `access_log=False`, as `door` does.
- The docking client sends its status-poll secret in an `X-Superyak-Secret` header, not `?secret=`. The station
  accepts both for one release, then refuses the query form.
- The access-request poll goes to the door, whose log is already off.
- **When `make dock` reaches the station by the public route** (re-check should-fix 2), the station answers 401 to
  `POST /api/dockings` and to the status poll `GET /api/dockings/{id}` on public requests. In either case the dock
  client:
  - keeps `docking.json`;
  - prints `STATUS: refused-public (the station docks only over the tailnet. New here: install Tailscale, sign in,
    and accept the station's share link. On one of Andy's machines: check that the station's name resolves through
    MagicDNS)`;
  - **ends the run at once with exit 3.** `refused-public` joins the client's final states, so it never polls on
    until `--wait` runs out.
- **CLAUDE.md:** the docking paragraph gains "`STATUS: refused-public` means stop and relay its message; running
  `make dock` again won't help".
- Phase 2 makes the client always take the tailnet.

## 5. Phases (S8)

1. **Phase 1 (this spec's build):** everything above, with ship keys allowed on public requests for any route.
2. **Phase 2 (its own item, build:ship-tailnet-route):**
   - **Clients:** the agent's `StationClient` and dock client resolve the station's name through MagicDNS
     (`100.100.100.100`) and dial that address, keeping the hostname for TLS SNI and Host. That's a custom
     `HTTPSConnection`, since urllib has no per-request resolver.
   - **The switch:** once every **active** ship reports the client version with that fix, the middleware's ship-key
     line is removed. An active ship is one with an unrevoked key used in the last 14 days, project ships included.
     Odo and Wormhole are on loopback and unaffected.
   - **The refusal:** a ship key on a public request then gets **`421 {"error": "Use the tailnet"}`**. The agent
     treats 421 as retryable, never as revoked (401) or final (403, 404, 409), with an agent test.

## 6. Tests first (S6, nit 5)

1. **The suite runs as tailnet.** A conftest helper builds every `TestClient` with `client=('127.0.0.1', 50000)`.
   Starlette's default host is `"testclient"`, which is not an IP and so is public. A test pins that a non-IP host
   never counts as tailnet.
2. **Classification,** through uvicorn's `ProxyHeadersMiddleware` configured as `serve` configures it (trusted
   127.0.0.1):
   - 127.0.0.1 with `X-Forwarded-For: 203.0.113.5` is public.
   - Several forwarded entries with a public one last are public.
   - Forwarded headers from an untrusted client are ignored.
   - 127.0.0.1 with no forwarded header is tailnet.
   - A tailnet address with a `Tailscale-Funnel-Request` header of any value is public.
   - `::ffff:100.70.202.124` unmaps to tailnet.
3. **Default deny:**
   - A walk over every route object, router-added and mounted ones included, once with no credentials and once with
     a made-up bearer key. Every route outside §2's table answers 401 on `/api/*` and 404 elsewhere, with the
     middleware's exact body and security headers. During the walk, `store.session` and `store.ship_for_key` are
     patched to fail the test, so any route handler that runs is caught (re-check should-fix 5).
   - **Allow-listed routes answer anonymous public requests normally:** `/`, `/public/`, `/assets/app.js` (the
     `/assets` mount matched as a route object), `/api/health`, a published layer and its file, and `POST /api/login`
     (should-fix 6).
   - An expired cookie on `POST /api/dockings` gets 401 and creates no docking, and so does an expired cookie on
     `PUT /api/layers/{key}`.
   - Dockings and access requests are checked with a real id and secret, asserting the key wasn't collected and the
     request wasn't created.
   - A made-up session cookie is refused.
4. **Signed-in use over public:**
   - A real session reaches `/api/me`, `/api/chats` and posting a message.
   - An expired session gets 401 "Sign in required".
   - An anonymous invitation redeem works.
   - A docking confirm without a session is refused, and with one it works.
5. **Ships over public (phase 1):** a valid key reaches every `StationClient` method's route (`/api/me`,
   `/api/chats/{key}`, `/api/chats/{key}/messages`, `/api/mentions`, `/api/ships/me/*`, `/api/ships/directory`).
   A made-up key is refused.
6. **The middleware writes nothing:**
   - A valid ship key is sent to a route that refuses ship keys before any ship lookup (`GET /api/home` gets 403).
     The clock is advanced first, then the test asserts `last_used` and presence are unchanged.
   - A database error in the lookup gives 503 "Try again shortly", never 401.
   - A route's own exception still reaches the 500 handler, on public and tailnet requests alike.
7. **Login:**
   - 8 public failures from one source hold that pair only.
   - 30 public failures from 30 sources hold public sign-ins to the username for a browser without a device cookie,
     but a browser with one, and a tailnet sign-in, still succeed. The tailnet sign-in clears the hold.
   - Two public addresses in one /64 share a source, and two tailnet IPv6 addresses don't.
   - **The reservation is visible while hashing:** `password_hash` is patched to wait on an event, and while it's
     paused, the counter already shows the reservation. Concurrent requests run inside one `with TestClient(app)`,
     so they share one event loop.
   - **Success gives back the reservation:** after 7 failures and a success, the source counter reads 7 and the pair
     row is gone.
   - An activation between the hash and the re-read gives 401.
   - Expired rows are deleted.
   - Held attempts neither hash nor count.
   - **The lanes (must-fix 1):** with the public queue held full, a tailnet sign-in succeeds, and so does a
     known-device public sign-in. The refused public attempt neither hashes nor counts.
   - **The device cookie:**
     - A valid one exempts from holds 1-3, and its failures hold only that token after 8.
     - A cookie for another user, an expired one and a made-up one exempt nothing.
     - A sign-in with a valid cookie adds no row.
     - Logout keeps it.
     - There are at most 20 rows per user.
   - A `user:` row from before the upgrade, at its limit, holds nobody.
   - Unknown and known names answer the same.
8. **Logs and docking:**
   - `serve` builds uvicorn with `access_log=False`.
   - The dock poll's URL carries no `secret=`.
   - The station accepts the header.
   - A public `POST /api/dockings`, and a public 401 on the status poll, each make the dock client print
     `STATUS: refused-public`, keep `docking.json` and exit 3 at once.
9. **Tailnet unchanged:** the whole existing peer suite passes, run as tailnet.

## 7. Deploy (nits 9, 10)

There's no migration beyond the new device-token table. Restart `superyak-lighthouse` on the Pi.

**Live checks after the deploy:**
- From a device off the tailnet (a tailnet machine resolves the name to the tailnet):
  - `/`, `/assets/app.js` and `/api/health` give 200;
  - an anonymous `POST /api/dockings` gives 401;
  - a sign-in works;
  - an expired session brings up the sign-in page;
  - a ship key reaches `/api/chats`.
- On the tailnet: `make dock` reaches the station, run from Tardis and from the Mac.

**Rollback:** the previous commit and a restart. A rolled-back station ignores `X-Superyak-Secret`, so dock clients
from this commit can't collect a key until it's redeployed. Undock nothing meanwhile.

**Merging:** this is safety code, so each partner gives an explicit yes before it merges.

## Open questions

None for Andy. Funnel stays his switch.
