# Always-on Lighthouse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Superyak peer on the smart Pi as an always-on lighthouse over Tailscale, with access requests approved from Andy's phone and a resident agent (Mal) answering room messages every 30 seconds.

**Architecture:** The peer gains an `AccessRequests` store mixin and routes, plus a `--proxy-headers` serve option so it works behind `tailscale serve`. A separate `superyak_peer.responder` module polls the HTTP API as the `mal` participant and calls `claude -p`. A requester script lets Jenn submit, wait and redeem. systemd user units keep both running.

**Tech Stack:** Python 3.13, FastAPI/uvicorn, SQLite, pytest, systemd user units, Tailscale serve, Claude Code CLI.

Spec: [`docs/superpowers/specs/2026-10-03-always-on-lighthouse-design.md`](../specs/2026-10-03-always-on-lighthouse-design.md)

## Global Constraints

- Request limits: name/contact 200 characters, note 2,000; requests expire after 7 days (604800 s); invitation lifetime 7 days.
- Rate limit: behind a proxy every client shares one source, so the limit is global: 20 new requests per hour and 50 pending.
- Only the request secret's SHA-256 is stored; the invitation token is returned once and then cleared.
- Mal is a participant, never an admin; its Claude call has no shell/edit tools.
- Poll interval 30 seconds. Reply `client_message_id` = `reply-<message id>`.
- No changes to `nebula-1043-dd.service`.

---

### Task 1: Access requests in the peer store and API

**Files:**
- Create: `peer/superyak_peer/access_requests.py`
- Modify: `peer/superyak_peer/db.py` (schema + mixin), `peer/superyak_peer/app.py` (routes), `peer/superyak_peer/__main__.py` (`access-requests --pending` CLI, `--proxy-headers`)
- Test: `peer/tests/test_access_requests.py`

**Interfaces:**
- Produces: `Store.request_access(name, contact, note) -> {id, secret, expires}`; `Store.access_request_status(id, secret) -> {status, token?, expires}`; `Store.access_requests(actor) -> [row]`; `Store.decide_access_request(actor, id, approve: bool) -> row`; `Store.pending_access_requests() -> [{id,name,created}]` (trusted local only).
- Routes: as in the spec table. CLI: `superyak-peer access-requests --pending --data-dir D` prints JSON list.

- [ ] Write failing tests: create→pending; anonymous status with wrong secret is 404; admin approve → status returns token once, second read has no token; token redeems an account; deny; participant gets 403 on list/approve; expiry after 604801 s; 21st request in an hour → 429; oversized note → 400.
- [ ] Run `uv run --locked pytest tests/test_access_requests.py -q` → fail.
- [ ] Implement mixin (table `access_requests(id, name, contact, note, secret_hash, status, token, created, expires, decided_by, decided)`), routes, CLI.
- [ ] Run the new tests and the full peer suite → pass.
- [ ] Commit `peer: add access requests approved by admins`.

### Task 2: Accounts view lists access requests

**Files:** Modify `peer/superyak_peer/static/app.js`; Test: `peer/tests/test_browser.py` (one Playwright case if browsers are installed, else API-level only).

- [ ] Load `/api/access-requests` for admins alongside accounts; render "Access requests" with name, contact, note, age and Approve / Deny buttons; actions POST and reload.
- [ ] Run peer suite; commit `peer: show access requests to admins`.

### Task 3: Requester script

**Files:** Create `peer/scripts/request_access.py`; Modify root `Makefile` (`request-access` target, `LIGHTHOUSE` variable).

- [ ] Script (stdlib only, so Jenn needs nothing but Python 3): prompt name/contact/note → POST with `Origin` = base URL → save `{id, secret}` to `~/.superyak/access-request.json` (0600) so it resumes → poll status every 30 s → on approval prompt username/password (getpass) → POST redeem → print sign-in URL.
- [ ] Test against a live `TestClient`-backed server is covered by Task 1; run the script by hand in Task 6.
- [ ] Commit `peer: add request-access script`.

### Task 4: Responder (Mal)

**Files:** Create `peer/superyak_peer/responder.py`; Test `peer/tests/test_responder.py`.

**Interfaces:** `Responder(base_url, username, password, state_path, ask, data_dir=None)`, `Responder.cycle() -> int` (replies posted). `ask(history: list[dict], room_title: str) -> str` default runs `claude -p` with `--allowedTools mcp__adna__*` and `--disallowedTools Bash,Edit,Write,NotebookEdit`.

- [ ] Failing tests with a fake `ask` against a temp app over `TestClient`: replies once to a new message; never replies to itself; restart (new Responder, same state file) posts nothing new; first sight of a room skips history before the latest message; three failures post a fallback note; pending access request posts one notice in the `Lighthouse` room.
- [ ] Implement; `python -m superyak_peer.responder --base-url … --credentials FILE --state FILE --data-dir D` loops every 30 s.
- [ ] Tests pass; commit `peer: add Mal room responder`.

### Task 5: aDNA MCP

- [ ] Clone `https://github.com/aDNA-Network/aDNA.aDNA` to `~/aDNA/aDNA.aDNA`, build `mcp/` per its README, `claude mcp add --scope user adna -- <command>`, verify a search call.

### Task 6: Deploy on the Pi

- [ ] `loginctl enable-linger andy`.
- [ ] Data `~/.local/share/superyak/lighthouse`; `bootstrap-super-admin --username andy --name Andy` → activation file; create `mal` with a random password stored in `mal-credentials.json` (0600).
- [ ] `~/.config/systemd/user/superyak-lighthouse.service` and `superyak-responder.service` (MemoryMax=2G, Restart=always); enable and start.
- [ ] `sudo tailscale serve --bg 7435` (HTTPS → 127.0.0.1:7435); serve with `--proxy-headers --origin https://smart.<tailnet>.ts.net`.
- [ ] Live check: request → approve → redeem → message Mal → reply.
- [ ] Update HANDOFF.md and README; commit.
