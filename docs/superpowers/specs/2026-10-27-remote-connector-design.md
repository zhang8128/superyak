# The remote connector: your home, from Claude

Revision 1, 2026-10-27. Serenity (the Mac). Board item `spec:remote-connector` (all hands).
Research, with sources: docs/research/2026-10-27-remote-connector-research.md.

## Why

Andy, 2026-10-27: "is superyak something that can be run from claude or chatgpt…", "or scientists or doctors". He is
at a conference this week, meeting people who live in chat apps, not terminals. Superyak's promise is a home whose
owner decides what leaves it, and every use leaves a receipt. The connector keeps that promise inside the chat apps
people already use. They sign in to their own home, see what the chat may read, and can take it back.

## Goals

1. A person adds their home to Claude as a custom connector, by its public address. They sign in to their own
   home in the browser, and Claude can then read what that person can read: their rooms and their messages.
2. Consent stays in the person's browser, on their home. The chat app never answers a consent question for anyone,
   and a ship never stands in for the person.
3. Every tool use leaves a receipt the person can read, and one click in their web app revokes the connection.
4. **A place can say "never to a cloud model".** Content from a room marked that way never appears in any tool
   result, whoever asks. Neither vendor's HIPAA agreement covers custom connectors (research 3), so Superyak itself
   enforces it.

## Non-goals (phase 1)

- **Writing.** No tool posts, claims, shares or changes anything. Phase 1 is read-only.
- **ChatGPT.** Which plans may add a custom server is unconfirmed (research 2). It follows once someone has tested
  with a real account. The tool shapes below already include ChatGPT's `search` and `fetch`, so adding it is
  configuration plus a test.
- **Memory (engram) and the rail's lessons.** Phase 1 reads the home's rooms. Engram stores and lessons come once
  the rail's index exists on every peer.
- **Ships.** Ships keep their bearer keys and station tools. The connector is for people.

## Anti-goals

- A second login. The connector signs in with the home's own accounts, sessions and holds (the public route spec).
- A token that outlives the person's intent: short access tokens, rotating refresh tokens, and one-click revoke.
- Anything clinical reaching a cloud model by default, by mistake, or through a forwarded quote.

## Design

### Where it lives

On each home, in `peer/`, at `https://<home's public name>/mcp`, served by the same app behind the public route. A
home's Funnel name resolves to a public address. Claude refuses tailnet addresses (100.64.0.0/10), so the connector
needs the public route live first (research 5).

### The home is its own authorization server

The home already has accounts, so it authorizes its own tokens. Phase 1 implements the smallest set the MCP
authorization spec and Claude require (research 1, 4):

- `/.well-known/oauth-protected-resource`, per RFC 9728, naming the home as its own authorization server.
- `/.well-known/oauth-authorization-server`, per RFC 8414.
- `/register`, Dynamic Client Registration, accepting only these redirect URIs:
  - `https://claude.ai/api/mcp/auth_callback`;
  - the loopback `http://localhost` and `http://127.0.0.1` callbacks on any port, for Claude Code.

  A registration is rate-limited per source, and an unused registration expires after 24 hours.
- `/authorize`, PKCE S256 only. It shows the home's own sign-in (with the public route's holds), then a consent page
  in plain words: "Claude (claude.ai) wants to read your rooms on this home. It can't post or change anything.
  Rooms marked 'never to a cloud model' stay hidden." The page has **Allow** and **Deny** buttons.
- `/token`, form-encoded. Access tokens last 1 hour. Refresh tokens rotate on every use, last 30 days, and are
  stored hashed. A reused refresh token revokes the whole grant.
- `/mcp`, Streamable HTTP. Without a valid token it answers a plain 401 with
  `WWW-Authenticate: Bearer resource_metadata="…"`. A token is bound to this home's resource URL (its audience) and to
  the person who consented.

The public route's allow-list gains these six routes. Each is reachable without a session, and each checks what it
needs itself: metadata needs nothing, register its rate limit, authorize the sign-in, token its code or refresh
token, and `/mcp` its bearer token. Nothing else changes for public requests.

### The tools (all read-only, annotated `readOnlyHint: true` with a title)

- `rooms()`: the person's current rooms, with title, member names and last activity.
- `read_room(room, limit=30, before=None, since=None)`: messages through chat paging, quoted as data with each
  message's author and time. A result is cut at 100,000 characters and says so.
- `search(query)`: matching messages across the person's rooms, as `{results: [{id, title, url}]}`. This is
  ChatGPT's deep-research shape, and Claude accepts it too.
- `fetch(id)`: one message with its neighbours, as `{id, title, text, url}`.

Each result is the room's text quoted as data, never as instructions. Anything in a room that reads like a command
to the model is just text.

### "Never to a cloud model"

- A room's owner can mark it `cloud: never` in the web app's room settings. A room in a place whose owner set
  `cloud: never` inherits it (phase 2 of org cities).
- A marked room is left out of `rooms()`, and `read_room`, `search` and `fetch` never return its messages. A direct
  request gets "This room's owner keeps it away from cloud models." A **quote** of a marked room's message in another
  room (a reply quote or a forwarded line) is withheld too: the tool shows "[quoted from a room kept away from cloud
  models]".
- The default for a new room is off. The web app shows the mark on every marked room, and the consent page names it.

### Receipts and revoking

- Every tool call writes a receipt: the time, the grant, the tool, which rooms it read (ids, never text), and the
  result's size. The person sees them in the web app under "Connected apps", with the client's name and when it last
  used each grant.
- **Revoke** there ends the grant at once: its access and refresh tokens stop working, and the next `/mcp` call gets
  401. The owner of the home can see and revoke every grant on it.
- Tokens are bearer secrets, so they are never logged. Access logs stay off (public route spec).

### Limits

- `/mcp` allows 60 calls a minute and 2,000 a day per grant. Over that it answers 429 with `Retry-After`.
- A tool call takes at most 30 seconds. Claude allows 240.

### Optional hardening

- **Egress range:** the home may restrict `/mcp` and `/token` to Anthropic's published range (160.79.104.0/21, IPv4)
  and loopback, with a setting that is off by default. It's defense in depth, not the security boundary, so it stays
  optional.

## Order of work

1. The public route (phase 1) is live, a prerequisite (Tardis's branch).
2. Chat paging is live, since `read_room` uses it.
3. **Build:**
   1. the authorization server;
   2. `/mcp` with the four tools;
   3. the `cloud: never` mark and its filter;
   4. receipts and revoking in the web app.
4. Test with a real claude.ai account on Andy's home, from the Mac and from a phone. Then test ChatGPT with a real
   account on the plan Andy has, and write down what worked.

## Tests

- **OAuth:**
  - the metadata documents;
  - registration's redirect allow-list and rate limit;
  - PKCE S256 required, and `plain` refused;
  - a code used once only;
  - refresh rotation, and a reused refresh token revoking the grant;
  - audience binding: a token for another home refused;
  - an expired access token answered 401 with the challenge.
- **Public route:** the six routes reachable without a session, and every other route still refused for a public
  request with only a connector token. A connector token is not a session and not a ship key.
- **Tools:** each tool returns only the consenting person's rooms. Another person's room, and a room the person left,
  give nothing.
- **`cloud: never`:**
  - never in any tool result, by any route;
  - a quote of its message in an unmarked room is withheld;
  - the consent page and the room list show the mark.
- **Receipts and revoking:** one receipt per call, with ids and never text. After revoke the next call is 401, and
  the refresh token is dead.
- **Limits:** a 429 with `Retry-After`, and the 30-second cap.

## Measure (Andy's goal 4)

A person who isn't one of the three ships connects their home to Claude and asks it about their own rooms. The
receipts show the reads, and the person revokes the grant when they're done.

## Decisions

- D1: the home is its own authorization server, not a proxy to an outside identity provider. It already has the
  accounts, and Superyak avoids central services.
- D2: phase 1 is read-only, and Claude first. ChatGPT's plan support is unconfirmed. Its tool shapes are included
  anyway.
- D3: "never to a cloud model" is a room mark Superyak enforces in every tool, quotes included. The vendors' BAAs
  don't cover connectors.
- D4: receipts hold ids, never text, so the record of a read doesn't become another copy of what was read.
- D5: the egress range is optional hardening, off by default. OAuth and the public route are the boundary.
