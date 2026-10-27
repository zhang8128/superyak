# The public route: a login in front of everything

Tardis, 2026-10-27, revision 1, for a fresh reviewer under station law section 3. Branch `tardis/funnel-hardening`,
on main f536862. Shaped in City of AI (f4556c73, 12d8997d, 945f7040, 774e1cd2, b12d9a66). Nothing here is built. The
detailed audit stays in City of AI until this ships. This spec says what each check enforces.

## Why

Andy, 2026-10-27, on Tailscale Funnel exposing the station's web app on port 443: "public is fine for now. as long as
there is a login."

An advisory audit found that content holds up. No anonymous request reads rooms, messages, files, accounts or titles.
But some anonymous routes act, and the login's guessing budget can be turned against its own users. This spec makes
Andy's sentence literally true: a public request reaches the login and what a signed-in person uses, and nothing else.

## Goals

1. **Default deny for public requests.** They reach only an allow-list. A route added later starts closed.
2. **Signed-in use works over Funnel,** as it does today on the tailnet. People at a conference sign in and use the
   app.
3. **Tailnet requests are unchanged.** Ships, the door and the station's own tools keep working.
4. **The login can't be used to lock people out,** and failed guesses can't stall the station.
5. No secret lands in a log.

## Non-goals

Turning Funnel off or on (Andy's switch); two-factor sign-in; the door (port 8443, unchanged); federation, which has
its own listener in the federation-pull spec.

## 1. Which requests are public

A request is **public** when either holds:
- it carries `Tailscale-Funnel-Request: ?1`, which Tailscale sets on Funnel traffic and strips from what clients send;
- its client address (uvicorn's, from the forwarded headers it trusts from 127.0.0.1 only) is neither loopback nor a
  tailnet address (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`).

The second condition is the positive check: if a different proxy ever sits in front, its requests start public, so
they start closed. A request with neither marker is a **tailnet** request and is handled exactly as today.

## 2. What a public request may reach

The `public_route` middleware sits first, before the body is read. A public request passes only when one of these
holds; otherwise it gets 404 `{"error": "Not found"}`, the same answer as a missing route.

| Allowed | Why |
|---|---|
| `GET /`, `GET /public/`, `GET /assets/*` | the app shell and its assets, no data |
| `GET /api/health` | `{"ok": true}` only |
| `POST /api/login`, `POST /api/logout` | the login itself |
| `POST /api/invitations/redeem` | an invitation link, a 256-bit token |
| `GET /public/layers/{key}`, `GET /public/layers/{layer_id}/files/{key}` | layers their owner published |
| any route, with a **valid session** | signed-in use (Goal 2) |
| `/api/ships/me/*`, with a **valid ship key** | phase 1 only (§5) |

- **"Valid" means checked, not present.** The middleware looks the session token up the way `store.session` does, and
  the ship key the way `ship_member` does: one indexed read in a read-only transaction. A made-up cookie or key gets
  the 404. The route still runs its own authorization afterwards, unchanged.
- **Closed to public requests:** anonymous dockings and their status polls, anonymous access requests (the door on
  8443 is their public route), `/federation/*`, and anything that isn't listed above.

## 3. The login

`Store.login` changes in four ways. The same answers stay: 401 for a wrong name or password, 429 when held, never
saying which names exist.
1. **The hard lock is per (username, source).** 8 failures in 5 minutes, as today, but counted per username and
   source together. Someone guessing from elsewhere no longer locks Andy out.
2. **A slower, username-wide backoff applies to public requests only.** After 30 public failures on one username in
   an hour, public sign-ins to it wait out the hour. Tailnet sign-ins are never held by it, so Andy can always sign in
   from his own machines.
3. **A source is its /64 for IPv6**, and its full address for IPv4, so rotating addresses inside one IPv6 network
   counts as one source. A global budget also applies: after 300 public failures in an hour, public sign-ins
   wait out the hour, while tailnet sign-ins don't.
4. **Hashing happens outside the database transaction,** in a worker thread (`run_in_threadpool`). The counters are
   read and written in short transactions before and after. A guess no longer holds the store's write lock or the
   event loop for the length of a scrypt.

The counters live in the existing `login_attempts` table, with key prefixes `user-source:`, `user-public:` and
`public:` beside today's `source:`. The `user:` key is no longer written, and old rows age out by their `reset`.

## 4. Logs

- `serve` runs uvicorn with `access_log=False`, as `door` already does.
- The docking client sends its status-poll secret in an `X-Superyak-Secret` header, not in `?secret=`. The station
  accepts both for one release, then the query form is refused.

## 5. Phases

1. **Phase 1 (this spec's build):** everything above. Ship keys stay allowed on public requests, because the Mac's
   ships reach the station through Funnel whenever its resolver takes the public DNS answer (Serenity, 774e1cd2).
2. **Phase 2 (its own small item):** ship clients resolve the station's name through MagicDNS (`100.100.100.100`) and
   keep the hostname for TLS and Host, so they always use the tailnet. Once every ship's client reports a version
   with that fix (the version check already exists), the middleware's ship-key line is removed, and public ship
   requests are closed too.

## 6. Tests first

1. **Classification:**
   - The Funnel header makes a request public.
   - A forwarded source of `203.0.113.5` or `2001:db8::5` makes it public.
   - `127.0.0.1`, `100.70.202.124` and `fd7a:115c:a1e0::1` don't.
   - A client-sent `Tailscale-Funnel-Request` from a tailnet address still counts as public, so it fails closed.
2. **Default deny, for a public request:**
   - Every route in `app.routes` that isn't in the allow-list answers 404 without a session. The test walks the
     route table, so a new route is covered automatically.
   - A made-up session cookie gets 404.
   - A real session reaches `/api/me`, `/api/chats` and posting a message.
   - Anonymous `POST /api/dockings`, `POST /api/access-requests` and `GET /api/dockings/{key}` get 404 on public
     requests, and work as today on tailnet requests.
3. **Ship keys, phase 1:** a valid key reaches `/api/ships/me/unread` publicly, and a made-up key gets 404.
4. **Login:**
   - 8 public failures from one source hold that (username, source), but not the same username from another public
     source.
   - 30 public failures from 30 sources hold public sign-ins to that username, but a tailnet sign-in with the right
     password succeeds.
   - Two addresses in one IPv6 /64 share a source.
   - The global public budget holds public sign-ins but not tailnet ones.
   - A wrong name and a wrong password answer the same.
   - A test hook shows the hash runs while no store transaction is open.
5. **Logs:**
   - `serve` builds uvicorn with `access_log=False`.
   - The dock client's poll carries no `secret=` in its URL.
   - The station accepts the header.
6. **Tailnet unchanged:** the existing peer suite passes with no request marked public.

## 7. Deploy

There's no migration. Restart `superyak-lighthouse` on the Pi. Live checks after the deploy:
- Through the public ingress, `/` gives 200, `/api/health` gives 200, and an anonymous `POST /api/dockings` gives 404.
- On the tailnet, `make dock` still reaches the station.
- A sign-in through Funnel works.

Rollback is the previous commit, and a restart. Safety code, so each partner gives an explicit yes before the merge
(law section 8, draft).

## Open questions

None for Andy. Funnel stays his switch.
