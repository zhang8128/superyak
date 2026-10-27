# The public route, phase 1: implementation plan

**Spec:** docs/superpowers/specs/2026-10-27-public-route-design.md, revision 3 (approved). Phase 1 only: §1-§4, the
§6 tests and §7's code side (the device-token table). Phase 2 (§5: the MagicDNS client, 421) is out of scope.

**Branch:** `tardis/funnel-hardening`, local only, never pushed. Each task is test-first: the §6 tests, seen failing,
then the code, then green, then one commit. New peer test files join the sdist inventory in `peer/pyproject.toml`.

## Tasks, in order

1. **Every TestClient runs as tailnet; which requests are public** (§1, §6.1, §6.2).
   `peer/tests/conftest.py` (the helper: every `TestClient` defaults to `client=('127.0.0.1', 50000)`),
   `peer/superyak_peer/app.py` (`is_public`, the tailnet ranges, `TRUSTED_PROXY`), new
   `peer/tests/test_public_route.py`. Tests: a non-IP host is public; the six classification cases through uvicorn's
   `ProxyHeadersMiddleware` with `trusted_hosts=TRUSTED_PROXY`. Comes first: the middleware would refuse every
   default `testclient` request.
2. **Side-effect-free validity reads** (§2 "Valid means checked"). `auth.py` `session_is_valid`, `ships.py`
   `ship_key_is_valid`. Tests: the same answers as `store.session` / `ship_for_key` for valid, expired, revoked,
   pending and made-up credentials, and neither writes `last_used` nor presence.
3. **The `public_route` middleware** (§2). `app.py`: `PublicRoute`, outermost (added after `BrowserBoundary`), the
   allow-list matched against the route object the router dispatches to, 401/404 refusals and the 503 guard, all
   with `BrowserBoundary`'s security headers (one shared constant). Tests: §6.3 (the walk with no credentials and
   with a made-up key, `store.session`/`ship_for_key` patched to fail; the allow-listed routes; expired cookies on
   `POST /api/dockings` and `PUT /api/layers/{key}`; real docking and access-request ids; a made-up cookie), §6.4,
   §6.5 (every `StationClient` method over a public transport), §6.6. `test_auth.py`'s local-demo "remote" client
   moves to a tailnet address so it still reaches the route's own loopback check.
4. **The login: buckets, holds, reserve first** (§3). `auth.py` `login_source`, `Store.login` in three steps,
   JSON counter keys, holds 1-3, tailnet recovery. New `peer/tests/test_login.py`: §6.7's holds, /64 and tailnet
   IPv6, the visible reservation, the give-back, the activation race, expired rows, held attempts, old `user:` rows,
   unknown and known names.
5. **The known-device cookie** (§3, §7's table). `db.py`/`auth.py`: `login_devices` (user, token hash, expiry,
   failures, failure reset), `device_is_valid`; `app.py` sets `superyak_device`. Tests: §6.7's device bullets.
6. **Sign-in lanes** (§3). `app.py`: public 2+8, tailnet 1+4, known browsers 1+4, all of `Store.login` in a worker
   under its lane's limiter; a full lane answers 429 without hashing or counting. Tests: §6.7's lanes bullet.
7. **`serve`** (§1, §4). `__main__.py`: `access_log=False`; `--proxy-headers` needs an IPv4 loopback `--host`;
   uvicorn's trusted proxy is `TRUSTED_PROXY`. Tests: §6.8's first bullet and the refused hosts.
8. **The docking poll's secret in a header** (§4). `app.py` reads `X-Superyak-Secret` (or `?secret=`);
   `agent/superyak_agent/station.py` `request(..., headers=)`; `dock.py` sends the header. Tests: the station accepts
   the header; the poll's URL carries no `secret=`.
9. **`STATUS: refused-public`** (§4). `dock.py`: a 401 on `POST /api/dockings` or on the poll prints the spec's line,
   keeps `docking.json` and ends the run with 3. Tests: agent fakes, and the real station over a public transport
   (`peer/tests/test_ship_agent.py`).
10. **Docs** (§4). `CLAUDE.md`'s docking line; `peer/API.md` and `peer/README.md` where they state the old behaviour.
11. **Whole suites:** peer and agent, once.

## Readings the spec leaves open (decided here, not deviations)

- A known browser's successful sign-in resets its token's failures, as success deletes the pair's row elsewhere.
- "The oldest goes" at 20 device rows: the row with the earliest expiry, that is the one signed in with longest ago.
- A non-IP source's bucket is its host string; a missing client is `unknown`.

## Open issues

None yet.
