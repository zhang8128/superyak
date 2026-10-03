# Always-on lighthouse on the smart Pi

Status: approved by Andy, 2026-10-03.

## Goal

The Raspberry Pi `smart` (Nebula `10.43.0.16`) hosts an always-on Superyak peer
where Andy, Jenn and later collaborators leave messages. A resident agent reads
rooms about every 30 seconds and replies. Jenn can clone the repository, request
an account, and Andy approves the request from his phone over Tailscale. Claude
Code on the Pi also gets the read-only aDNA tools.

## Components

### 1. Lighthouse service

- The Pi joins Andy's tailnet as `smart`.
- User systemd unit `superyak-lighthouse.service` runs the existing peer
  `serve` command on `127.0.0.1:7435` with data in
  `~/.local/share/superyak/lighthouse`. Linger is enabled so it survives reboots.
- `tailscale serve` publishes it as `https://smart.<tailnet>.ts.net` with a
  Tailscale-issued certificate. That URL is the server's only browser origin.
- Andy is the first super admin via `bootstrap-super-admin`; he sets his own
  password with the one-use activation token.
- The Nebula service is unchanged. Nebula/aDNA peering (for example Voyager on
  the supercomputer) later uses the peer's existing signed federation; it is not
  part of this change.

### 2. Responder agent ("Mal")

- Ordinary participant account `mal`; its password is in a mode-0600 file
  beside the lighthouse data. It is never an admin.
- `superyak-responder.service` signs in through the HTTP API, polls
  `/api/chats` every 30 seconds, and reads rooms whose `last_activity` changed.
- For each new message not written by Mal, it calls `claude -p` with the recent
  room history and posts the reply with `client_message_id = reply-<message id>`,
  so a retry after a crash cannot post a duplicate.
- Claude runs with no shell or file-edit tools; only the read-only aDNA MCP tools
  are allowed. One call at a time under a systemd memory cap.
- A cursor file records the last handled message per room. On first sight of a
  room, Mal answers only messages newer than its own join (no backlog replay
  beyond the latest message).
- Failures are logged and retried next cycle; three failures on one message post
  a short "I couldn't answer this" note and move on.

### 3. Access requests (peer feature)

Store mixin `AccessRequests` and routes:

| Method/path | Who | Behavior |
| --- | --- | --- |
| POST `/api/access-requests` | anyone who can reach the server | `{name, contact, note}` → `{id, secret, expires}`, 201 |
| GET `/api/access-requests/{id}?secret=` | requester | `{status}`; once approved, includes the invitation token exactly once |
| GET `/api/access-requests` | admin | pending and recent requests |
| POST `/api/access-requests/{id}/approve` | admin | creates a 7-day invitation; status `approved` |
| POST `/api/access-requests/{id}/deny` | admin | status `denied` |

- Only the secret's hash is stored. Requests expire after 7 days.
- Limits: name/contact 200 characters, note 2,000; at most 5 requests per source
  address per hour and 50 pending in total (429 otherwise).
- The invitation token is stored only until the requester picks it up, then cleared.
- The admin Accounts view lists pending requests with Approve/Deny buttons.
- Notification: the responder runs on the same host as a trusted local worker.
  Each cycle it reads new pending request names through the local CLI
  `access-requests --pending --data-dir …` (no HTTP route, no admin session) and
  posts "<name> is asking for access — approve in Accounts" once per request to
  the room titled `Lighthouse` that Andy shares with Mal.

`peer/scripts/request_access.py` (`make request-access LIGHTHOUSE=https://…`):
asks for name/contact/note, submits, polls every 30 seconds, then prompts for a
username and password and redeems the invitation.

### 4. aDNA tools

Clone `aDNA-Network/aDNA.aDNA`, build its `mcp` server, and register it in
Claude Code at user scope as `adna`. The responder's allowlist is
`mcp__adna__*`.

## Testing

- pytest: request creation, limits, expiry, approve/deny by admin only,
  single pickup of the token, non-admin rejection, event emission.
- Responder unit test against a temporary peer with a fake `claude` command.
- Live check on the Pi: request → approve → redeem → message → Mal replies.
