Verdict: APPROVE WITH CHANGES (0 must-fix, 3 should-fix, 7 nits)

# Build review: the public route, phase 1

I reviewed the build as a fresh reviewer. I took no part in the spec, its reviews or the build. The diff reviewed is
`f536862..0786c15` on `tardis/funnel-hardening`, against spec revision 3 and the plan's readings. I read the code and
the locked libraries' sources (FastAPI 0.141.1, Starlette 1.6.0, uvicorn 0.52.4, anyio 4.15.1). I ran the suites and
probed the middleware in-process with a scratch script outside the worktree. Nothing in the worktree was changed, and
nothing touched the live station. Weaknesses are described only as far as a fix needs.

## Suites

| Run | Result |
|---|---|
| `peer`: `tests/test_public_route.py tests/test_login.py` | 86 passed |
| `peer`: whole suite | 943 passed, 1 skipped, 103 failed. All 103 failures are in `test_browser.py`: run alone, it fails 103 of 103, the known missing-Playwright environment issue |
| `agent`: whole suite (`--extra dev`) | 758 passed |

## What holds up

1. **No anonymous public path is left open.**
   - **Matching.** `PublicRoute.allowed` (`app.py:153-163`) walks `app.router.routes` with each route's own `matches()`,
     the same way `APIRouter.app` dispatches: the first full match, else the first partial one. It also reads the same
     `scope['path']`. So the middleware's answer and the router's choice can't disagree, and the probe is a shallow
     copy, so nothing leaks into the real dispatch. I checked that FastAPI's `_IncludedRouter.matches` restores its
     scope keys in `finally`.
   - **`listed`.** `listed` (`app.py:166-167`) admits only an `APIRoute` or a `Mount` whose template and method are in
     `PUBLIC_ROUTES`. The included router (federation, connections, sync) is one `_IncludedRouter` object, so it never
     lists, which is the safe direction. The `/assets` `Mount` lists for GET and HEAD only.
   - **When nothing matches, or the router would redirect.** The middleware refuses before any redirect, and the router
     consults `_low_priority_routes` only for frontend routes, which this app doesn't use.
   - **Odd forms all checked out.** I probed trailing and doubled slashes, case, encoded slashes, dot segments,
     lowercase and unusual methods, HEAD, OPTIONS, empty and relative paths, and NUL. Every one was refused (401 under
     `/api/`, 404 elsewhere), or reached only an allow-listed route. Under `/assets`, that meant StaticFiles' own 404
     and its traversal guard.
   - **Websockets and credentials.** Public websockets are closed before any lookup. A request carrying a session or
     key passes only when `session_is_valid` or `ship_key_is_valid` finds it valid. Those two reads use the same
     conditions as `store.session` and `ship_for_key` (`auth.py`, `ships.py:112-121`) and write nothing.
2. **Classification** (`app.py:52-65`).
   - The Funnel header counts with any value. A missing or non-IP client is public, and IPv4-mapped addresses are
     unmapped.
   - In uvicorn 0.52.4, the forwarded address is the rightmost untrusted entry, with 127.0.0.1 the only trusted proxy.
     Tailscale sets `X-Forwarded-For` and `Tailscale-Funnel-Request` itself, so an internet client can't present a
     tailnet or loopback address.
3. **The 401, 404 and 503 answers.**
   - Refusals carry the shared `SECURITY_HEADERS`. Only the classification and the lookup sit inside the guard. The
     call into the app is outside it, so route errors still reach the 500 handler; tests cover this on public and
     tailnet requests.
   - `app.js` handles the 401: the boot's `/api/local-demo` probe lands on `showLogin("")`, and an expired session and
     the layer editor's panel act on 401 as before.
   - The dock client never sees 401 for an internal failure.
4. **Signed-in, ship and tailnet use.**
   - The conftest default `client=('127.0.0.1', 50000)` keeps the existing suite on the tailnet, and every test that
     wants a public client passes its own.
   - `test_auth.py`'s local-demo "remote" client moved to a tailnet address, so it still reaches the route's own
     loopback check. A new public assertion was added beside it.
   - `test_restore.py` classifies `login_devices` as coordination. That's correct: a device row grants no access, users
     are never deleted, and the foreign key can't break a reconcile.
   - The schema runs `CREATE TABLE IF NOT EXISTS` at every `Store` open, so the migration is additive and the door and
     the CLIs pick it up.
5. **The login** (`auth.py:130-187`).
   - **Reserve first.** Step 1 deletes expired rows, refuses a held attempt before any hash, or reserves on every
     applicable counter, all under the store's process-wide lock. The hash runs outside any transaction; before this
     build it ran inside the lock, on the event loop.
   - **Step 3 and the give-back.** Step 3 re-reads the salt, hash, activation and kind. Success deletes the pair row,
     gives back the others within their own window, and clears the public username hold on a tailnet success. Failure
     keeps the reservation.
   - **Unknown names** take the dummy hash, and 401 and 429 answer alike for unknown and known names.
   - **Counter keys** are JSON arrays, and public IPv6 sources group by /64.
   - **The device cookie.**
     - It's 256 bits, stored hashed, HttpOnly, Secure, SameSite=Strict and lasts 180 days.
     - A valid cookie keeps and extends its row. A new row prunes expired rows and caps the user at 20.
     - A valid cookie exempts its browser from holds 1-3 and counts failures on its own token instead, 8 in 5 minutes.
     - A cookie for another user, an expired one or a made-up one exempts nothing. Logout keeps it.
   - **The lanes.**
     - Each lane's anyio `CapacityLimiter` is built outside a loop as a `CapacityLimiterAdapter`. It binds lazily, and
       its asyncio waits make a fresh `Event` each time, so one app on uvicorn's single loop is correct.
     - A full lane raises 429 before `Store.login` runs, so it neither hashes nor counts.
     - Lanes take no tokens from the default thread limiter. Public requests never enter the tailnet lane.
6. **Docking.**
   - The poll sends `X-Superyak-Secret`, and the station prefers the header and still takes `?secret=`.
   - A 401 on `POST /api/dockings` or on the poll prints the spec's line, keeps `docking.json` (nothing is written on
     the POST path) and ends the run with 3 at once. The tests cover this with fakes (`slept == []`) and against the
     real station (`sleep=pytest.fail`).
   - `serve` keeps no access log.
   - The Pi's unit is recorded as `127.0.0.1:7435` (`HANDOFF.md:161`), and `--host` defaults to `127.0.0.1`. The README
     command and the Makefile `home` targets pass no `--host`, and the restore test uses `--host 127.0.0.1` without
     proxy headers. None of these is refused.
7. **Every §6 test exists** (6.1 to 6.8), and I traced each one to a failure it would show if the behaviour were wrong.
   - The walk patches `store.session` and `store.ship_for_key`, and asserts the exact body, the headers and unchanged
     row counts. It runs over `iter_route_contexts`, so a route added later is walked automatically.
   - "Writes nothing" advances the clock before checking.
   - The reservation test pauses the hash.
   - The lane test fills the public lane inside one `with TestClient`. A lane that queued without bound would deadlock
     it until the 20 s release timeout, and `test_the_lanes_sizes` pins the sizes.
   - The activation-race test fails if step 3 used the step-1 row.

## Must-fix

None.

## Should-fix

1. **Deploy: check the Pi unit's `--host` before restarting** (`__main__.py:458-467`; spec §7; re-check nit 12, not
   carried into the spec or the plan).
   - **The risk:** `serve --proxy-headers` now refuses `localhost`, `::1` and any non-IPv4 host. The unit isn't in the
     repository, so if its `ExecStart` names one of those, the restart fails and `Restart=always` loops with the station
     down.
   - **Why it's probably fine:** `HANDOFF.md:161` records 127.0.0.1:7435.
   - **The fix:** before `systemctl --user restart superyak-lighthouse`, read its `ExecStart`: `systemctl --user cat
     superyak-lighthouse`. Add this step to §7's deploy list.
2. **README: name the trust assumption where the operator reads it** (`peer/README.md:262-276`).
   - **The risk:** spec §1 says anything forwarding raw TCP to the port is trusted as tailnet, and the operator doc
     doesn't say so. If 443 were ever published in a TCP mode (`tailscale serve`/`funnel` with `--tcp` or
     `--tls-terminated-tcp`), every public request would arrive from 127.0.0.1 with no forwarded or Funnel header. It
     would count as tailnet, silently voiding this whole change.
   - **The fix:** add one sentence: publish the app only through HTTP `serve`/`funnel` (as shown), never a TCP mode.
3. **Pin path normalisation in a test** (`peer/tests/test_public_route.py`).
   - **The gap:** the walk sends one concrete path per template. The odd forms in "What holds up" 1 are refused today
     because the middleware uses the router's own matcher, but no test would catch a later refactor to prefix or
     string matching.
   - **The fix:** add a small parametrized test that sends a handful of such forms as public requests and asserts
     `refused()` (or, under `/assets`, a 404 with no file content). Keep the cases in the test, not in docs.

## Nits

1. **`CLAUDE.md:24-25`, "running `make dock` again won't help".**
   - **When it's wrong:** with Funnel answering 443, a newly approved requester without Tailscale now gets
     `refused-public` where they used to get `waiting-for-station`. Once they've installed Tailscale and accepted the
     share, running it again does help.
   - **The fix:** "won't help until they've done what it says". This is spec §4's wording, so fix it there too.
2. **The counter keys don't mark public or tailnet** (`auth.py:26-44`).
   - **The issue:** a public IPv4 source and a tailnet source with the same address get the same key. That happens
     only for a Funnel-flagged request from a loopback or tailnet client, which isn't reachable from the internet
     through `tailscale serve`.
   - **The fix:** adding `public` or `tailnet` to the key would rule it out by construction.
3. **The tailnet lane is shared by every tailnet user, shared users included** (`app.py:257`, `296-301`).
   - **The issue:** a shared user flooding sign-ins can get Andy's tailnet sign-in refused with 429 while the flood
     lasts. That's far better than before (a stall of the whole station), and the spec sized the lanes this way, but
     Goal 4's "nobody" reads wider.
   - **The fix:** a tailnet sign-in with a valid device cookie could use the known lane.
4. **The test name over-claims** (`test_login.py:155`): `..._and_never_goes_below_zero` tests only the window. Below
   zero can't be reached anyway, since give-backs never exceed the reservations in their window. Drop the clause.
5. **The walk uses a private FastAPI helper** (`test_public_route.py:171`). An upgrade would break the walk with an
   `ImportError`. That's loud, not silent, so it's acceptable, but it's worth a comment.
6. **Public requests to `/public` and `/api/health/` get 404 and 401** where the tailnet gets Starlette's 307 slash
   redirect. It's harmless: the share link is `/public/?layer=`.
7. **`SignInLane.inside` assumes one event loop** (`app.py:169-186`). That's true under uvicorn. A docstring line
   saying so would keep a future test from sharing a lane across portals, which the current tests correctly avoid.
