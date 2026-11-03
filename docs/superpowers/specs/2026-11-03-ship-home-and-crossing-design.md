# A ship's own home, and lighthouse crossings between peers

**Status:** revision 2, by Tardis. This is the station half of "memory follows the ship".
- Rio Grande's Engram half is approved (branch memory-follows-ship, 8a5df4da), and its section 3.11 is the interface
  this spec meets. Section 5 here proposes one amendment to it.
- Revision 1 (d0cd0ec2) got REVISE from a fresh reviewer, with five Majors and nine should-fix items
  ([review](../reviews/2026-11-03-ship-home-and-crossing-review.md)). Each is answered below, marked M1 to M5 and S1 to
  S9.
- Rio Grande's reading of the audience map (all hands, d7d7e534) gives M1's fix.

## Why

- Andy, 2026-11-03: "the engram probably shouldn't necessarily all be in folders. it should stay with you. at least
  parts of it."
- Engram's lighthouse crossing is same-machine only. A receiver reaches its publishers over the publisher daemon's
  Unix socket (engram/docs/lighthouse-receiver.md). Nothing carries a recall between machines, so the rail commons'
  stage 4, two stores on two machines, has no transport.
- Rio Grande's half makes each ship's home store the only writer, and every session a thin client. Those clients
  need an authenticated way to reach their home.

## Two routes, two checks

| | Own home | Crossing |
|---|---|---|
| **Who asks** | A session of ship S | A receiving store on a paired peer |
| **Which store** | S's own store, at S's home | Another ship's **published house**, at its publisher's peer |
| **What serves it** | The home's store host, the only writer | The publisher's **read-only lighthouse daemon** (M4). Never the store host |
| **What it may do** | Every tool, read and write (the 3.11 envelope) | The local crossing's `query` and `read` frames, unchanged in meaning |
| **What decides** | Authentication alone: it's S's own store | The publisher's policy per operation, then the receiver's |
| **Records** | The host's operation log (Rio Grande's half) | The daemon's sidecar, plus the receiver's `lighthouse_receipt`, linked by `disclosureId` |

They're separate routes, with separate handlers and separate tests. No code path turns an own-home request into a
crossing. A crossing never reaches the store host, so it can't write a store or leave another ship's queries in its
trails.

## 1. Own home

### 1.1 On the same machine (Rio Grande's stages 1 and 2)

- **Where clients connect:** the store host listens on a Unix socket at `<memory_home>/.engram/host.sock`, mode 0600,
  owned by the station's user. No network port.
- **What it proves:** routing only (3.11, "Stage 1 can't prove the ship"). On one uid, every process can read every
  ship's key file. So a client configured as ship A reaches A's store and never B's, but a hostile process under the
  same uid could pose as B.
- **Where `ship` comes from:** the client's configuration, said plainly here. Stage 3 replaces it.

### 1.2 Authenticated (stage 3): a session away from its home machine

This covers both of Rio Grande's stage 3 cases: a Tardis session on another machine reaching Tardis's home, and a
cluster session reaching the cluster station (S7).

**The key is a memory key, issued by the home** (S7). A laptop ship's station key comes from the Pi, not from its
home, so the home can't check it.
- **Issuing:** the home issues each ship it hosts its own memory key at setup, kept in `ship_keys` at the home's peer
  with a `scope` of `memory`. A memory key opens only this route, and a station key never opens it.
- **On a cluster station,** the per-job session key (cluster station spec, section 3) is a memory key of that station
  too. Per-job expiry, and the columns it needs, stay under that spec's review.

**The route** is `POST /api/ships/memory` on the home's main app.
- **What the home sets:** it maps the key to its ship, and sets `ship`, `agent_ref` and whether the agent acts for the
  owner (gate G13) from that, never from the body.
- **The ship-to-store map** is the store host's (Rio Grande's 3.1). The route passes the authenticated ship, and no
  request names a store or a path.
- **What the body carries:** the client's half of the 3.11 envelope only: `session_id`, `seq`, `op_id`,
  `client_time`, `deadline_ms`, `kind`, and the tool and its arguments.
- **How it reaches the store:** the station forwards it to the host's socket and returns the host's answer.

**Limits:**
- **Body:** at most 1 MiB. The client refuses to queue a larger operation, and the tool call gets `refused:
  too_large` at once, so nothing oversize ever holds a `seq`. If one arrives anyway, the station records a refusal at
  the host for that `seq` (below).
- **`deadline_ms`:** 500 to 10,000.
- **Rate:** a per-key limit.

**Reach** (S6): a valid ship key passes the public route for any route (app.py:157-163). A memory key does too, so
this route is reachable wherever the main app is. On a cluster station, compute-node clients count as public
(`is_public`, app.py:68-81) and pass by key. That's intended.

**Answers** (M5). Each row is mapped once and tested once:

| Case | HTTP | Client sees |
|---|---|---|
| Applied | 200 `{status: "applied", result}` | the result |
| Already applied, a replay (3.3) | 200 `{status: "replayed", result?}` | the first result if kept, else an ack |
| Expired at the host (3.3) | 200 `{status: "expired"}` | dropped from the outbox, shown at next wake |
| Busy or disk full, with `Retry-After` | 503 `Retry-After: n` | `retry` |
| `seq` ahead of `high` | 409 `{kind: "gap", expected}` | `gap` |
| Store moved | 409 `{kind: "moved", home}` | `moved` |
| Quarantined, unavailable, or a station-side refusal | 403 `{kind: "refused", code}` | `refused`. A 403 without `code` is treated as `unreachable` |
| Key expired or revoked | 401 | **`unauthorized`** (section 5): stop sending and keep the outbox. The memory client never deletes a key |
| Connection failed, a timeout, or any other 5xx including a 503 without `Retry-After` | (none) | `unreachable`: keep the outbox and back off |

**A station-side refusal never stalls the session.** A 400 or 413 that the station gives, which the host never saw,
is first recorded at the host as `refused` at that `seq`. So `high` advances and later operations continue. Then the
station answers 403 `{kind: "refused", code}`.

**What isolation needs, said plainly:** a key proves the ship only as well as the key is kept. On a cluster, per-job
keys live inside the job, so one ship's job can't read another's key. On one uid on one machine, it can. Real
isolation there needs one uid per ship, which this spec doesn't require.

## 2. Crossing between peers

### 2.1 Who asks, and who can be asked

- **Only listening peers can be asked:** the Pi and Tardis. A crossing is a request to `federation-listen`. Pull peers
  (the Mac, a cluster station) can't be asked.
- **Who can ask, in stage 2:** only push peers. A peer asks through its own local socket (2.4), which a pull peer
  doesn't have. How a pull peer asks without a listener is left for later (section 6).
- **Cluster route B** (cluster station spec, section 2) serves only events and pull, and carries no crossings (S9).
  Extending it is its own review.

### 2.2 Who the receiver is (M1)

The destination builds the receiver's identity from what it has verified, never from what the request claims:

`urn:superyak:<origin peer_id>:store:<receiving instance_id>`

- **Why it can't be mistaken for a local name:** it contains `:`, so it can't match Engram's local `NAME`
  (lighthouse_receiver_config.py:13). A remote name is never judged by a local store's policy, ledger or receiver file.
- **Why it can't be borrowed:** instance ids are self-assigned, and a backup copy keeps its id. Binding the verified
  origin peer stops any paired peer from naming another peer's store to take its audience (Rio Grande's (b)).
- **A store that moves home** keeps its instance id but changes peer, so it loses the grant until its owner grants it
  again. A new home is a new boundary.

**The format changes this needs, named here:**
- **Audience keys:** `engram:audiences` accepts the remote form as a key, in sharing's validation and in
  `_allowed_audiences` (lighthouse_daemon.py:208).
- **Selectors:** `lighthouse_policy`'s selector matching never lets a wildcard (`urn:engram:*`, or any prefix) match
  a remote ref. Only a rule naming that exact ref does.
- **Ledger:** the ledger agent is `agent:<ref>`, and its place is outside the home, so `group:outside-home` applies.
- **No local receiver file:** for a remote ref the publisher reads no receiver-policy file from its own
  `instances/`. The receiver's own policy is checked at the receiver's side (2.4).

**The ship behind the store** must also be a current contact of this peer (S3). Holds and confirmations belong to
contacts (federation.py:78, 151-193), not to peers. So the request names the receiving ship's participant id, and the
destination checks that it's a contact from that origin: not held, with a current typed confirmation by the rule
`connections()` uses. When owner trust and `retired_peers` land, their holds apply through the same check. A ship
becomes such a contact by pairing, or later by owner trust.

### 2.3 The route

`POST /federation/crossing`, on `federation-listen` only (listener.py `ROUTES`), so it's tailnet-only, as 7437 is.

**The request** is canonical JSON with exactly these keys (M3):

| Key | Rule |
|---|---|
| `version` | `1`, an `int` |
| `kind` | `"crossing"`. Reserve `crossing` and `crossing-answer` beside `RECORD_KEYS`, as `pull` is |
| `origin`, `destination` | `peer_id`s |
| `receiver_instance` | the receiving store's `instance_id`, a string that matches the instance id pattern |
| `receiver_ship` | the receiving ship's participant id on the origin peer |
| `publisher_ship` | the asked ship's participant id on this peer |
| `frame` | **the local crossing's own frame**, unchanged: a `query` frame (`purpose`, `context`, query text at most 4,096 characters as lighthouse_client.py:18, `k` at most 20, so the receiver can fuse candidates as neighbors.py:91 does) or a `read` frame (`purpose`, `context`, `turnId`, at most 5 ids). It's validated by lighthouse_protocol's own validators. Its `receiver` and `publisher` fields are **overwritten** by the destination: the receiver with the 2.2 ref, and the publisher with the asked ship's store |
| `deadline_ms` | an `int` from 100 to 10,000: **the time remaining** in the receiver's shared deadline (S1) |
| `nonce` | 32 lowercase hex characters |
| `at` | an `int` Unix time |
| `signature` | Ed25519 over the canonical request without `signature`, by the origin card's `signing_key` |

**Checks before any Engram store, policy or sidecar is opened** (they read and write `peer.sqlite3` only):
1. **Shape:** an exact key set and types, and the body at most **16 KiB** (S2; `ROUTES` caps it per route). Otherwise
   400.
2. **Destination** equals this peer. Otherwise 403.
3. **Origin** is in `peers` and paired. Otherwise 403. Any peer card version may ask, since this isn't pull's v2-only
   check (S3).
4. **Signature, then clock, then nonce,** in `serve_pull`'s order (federation.py:440-455): the signature verifies
   under the stored card's key; `at` is within 5 minutes of this clock; the nonce is inserted, with the restore replay
   floor reused (federation.py:408-419). A replay gets pull's 409 "Replay" (S4).
5. **Contact:** `receiver_ship` is a current, unheld contact from that origin (2.2). Otherwise 403. **This is the
   rollback:** an unpair, a hold, or later a retire, stops crossings at the next request.
6. **Load:** at most 2 crossings in flight per origin and 4 in total. Handlers run on threads (listener.py:79), so 10 s
   crossings can't starve events and pulls. And at most 60 a minute per origin. A whole cluster station's asks share
   that 60, which is said on purpose. Otherwise 429.

**Then the publisher's daemon** (M4). federation-listen hands the rewritten frame to the publisher's own lighthouse
daemon over its local socket, exactly as a local receiver would.
- **Read-only:** the daemon opens the published house read-only (lighthouse_daemon.py:3-9) and runs every check it
  runs today: policy reloaded per operation, purpose and context matched, audience by the 2.2 ref, expiry on its own
  clock, and decisions recorded in its sidecar.
- **Never the private store,** so `unshare` removes a memory from crossings, as it does locally. Never an imprint
  store: the publisher's map refuses one (sharing.py:109-110).

**The sidecar change,** named here: a table `crossing_disclosures(disclosure_id PRIMARY KEY REFERENCES
disclosures(id), origin_peer, receiver_ref, request_digest, nonce, at)`, written in the same sidecar transaction as
the disclosure. The sidecar's existing `disclosures` row keeps the action, context, purpose, effect and memory ids.

**Read ids are bound to their turn:** for the deadline, the daemon keeps `turnId` mapped to the ids selected in that
turn's `query`. A `read` naming any other id is refused. Nothing enforces this today (lighthouse_daemon.py:978-1000),
so it's a code change, named here.

**The answer** is canonical JSON, signed by this peer's key, with exactly:
- `version`;
- `kind: "crossing-answer"`;
- `origin` (this peer) and `destination`;
- `request_digest` (SHA-256 of the canonical signed request) and `nonce` (the request's);
- `frame`: the daemon's `recall_result` or `read_result`, with its `disclosureId`;
- `signature`.

It's capped at 128 KiB, with delivered text at most 32 KiB in total, as locally. **The origin peer verifies it,** not
Engram, since Engram holds no card. Then it hands the frame to the asking host.

### 2.4 The receiver's side

**Which process asks.** Only the receiving home's store host asks, during a live `recall` with a
`lighthouse_context`. It's never inside an open `graph.db` transaction (3.4). A recall made away from home gets no
crossing, and says so in `degraded: ["neighbors"]` (S8).

**The local hop** (S5). The host asks its own peer over the peer's Unix socket,
`<peer data dir>/crossing.sock`, mode 0600. federation-listen opens that socket on push peers.
- **What the peer takes from the caller:** `receiver_instance` and `receiver_ship` come from the home's own host
  configuration, never from the body. The same-uid caveat of 1.1 applies.
- **What the peer does:** it signs, dials the publisher pinned as pull dials, bounded by `deadline_ms`, verifies the
  answer, and returns the frame.
- **No key in Engram:** Engram never holds a peer key. On a pull peer there's no listener, so no socket, and no asking
  in stage 2 (2.1).

**Receiver settings** (S8). `load_settings` refuses unknown keys and non-plain publisher names
(lighthouse_receiver_config.py:26-42). So the format gains a `[[remote_publishers]]` table: `peer_id`, the asked ship's
participant id, and `context`. That's a format change, named here, with at most eight publishers in total, local and
remote.

**The receiver's checks are unchanged in meaning:**
- its policy grants `recall`, `read` and `inject_context` (neighbors.py:121, 139);
- the publisher's ref is `urn:superyak:<peer_id>:ship:<participant id>`;
- a failed receipt write suppresses neighbor content;
- the `lighthouse_receipt` records the publisher's `disclosureId`, which links both sides.

**No silent fallback** (engram-neighbors-visible): an unreachable or refusing remote publisher shows in `neighbors`
and `degraded` by name, with its error.

### 2.5 What "inject" means across peers (M2)

In Engram, delivering read text **is** `inject_context`. The receiver requires it before every read and before
delivery, and the publisher decides each read item as it (lighthouse_daemon.py:604-636). So a crossing that delivers
text needs `inject_context` granted on both sides, and stage 2 grants it.

What's forbidden across peers is narrower and concrete:
- **No unasked text in a session:** remote text never enters the wake or nudge hooks' context. It reaches a session
  only as the result of an explicit `recall` naming a lighthouse context, in that turn.
- **No remote text stored as memory:** delivered remote text is never written into the receiver's store as an
  episode, semantic or instinct. Only the content-free receipt is kept.

## 3. Stages

1. **Own home on the same machine** (1.1), with Rio Grande's stage 1.
2. **One crossing, Pi and Tardis** (rail commons stage 4):
   - Each side publishes its work lane only, to the other's store ref, with recall, read and inject granted on both
     sides for one context.
   - **The measure:** a recall on the Pi that delivers from Tardis's published house, with the daemon's
     `disclosureId` in the Pi's receipt and in Tardis's sidecar. Then lighthouse_sheaf on a few shared topics.
   - **The rollback:** the receiver off, or an unpair.
3. **Own home, authenticated** (1.2): memory keys, a Tardis session from another machine, then cluster sessions with
   the cluster station.

## 4. Tests that prove it

**Crossing:**
- **Rollback:** a held receiving ship and an unpaired peer are each refused at checks 3 or 5, and a probe shows no
  Engram store, policy file or sidecar was opened.
- **Bad requests:** a wrong destination, a replayed nonce, a stale `at` and a bad signature are each refused before
  any Engram read.
- **The audience is a peer and a store:** a second store on an allowed peer, not named, gets nothing. So does the
  right `instance_id` signed by a different paired peer.
- **Selectors:** a policy rule `urn:engram:*` doesn't match a remote ref, and only an exact rule does.
- **A remote ref never reads a local file:** a local instance named like the remote store's id contributes no policy.
- **The frame's own fields are overwritten:** a `receiver` or `publisher` in the frame is ignored.
- **Read binding:** a `read` naming an id not selected in that `turnId` is refused.
- **No hook injection:** after a crossing, the wake and nudge outputs contain no remote text, and no episode holds it.
- **Records:** `unshare` and an imprint store each deliver nothing. Both records link by `disclosureId`, and a failed
  receiver receipt suppresses the text.
- **Deadline and load:** a slow publisher past `deadline_ms` delivers nothing and shows `degraded`. A third concurrent
  crossing from one origin gets 429, while events and pulls keep flowing.
- **Two routes:** a 3.11 write envelope sent to the crossing route is a 400, and the store host's socket is never
  dialed by federation-listen.

**Own home, authenticated:**
- `ship` in the body is ignored.
- A station key on the memory route gets 401.
- An expired memory key gets `unauthorized`, with the outbox kept and the key not deleted.
- A 413 from the station advances `high` at the host, and the next operation applies.
- Each row of the answers table maps as written, including a 503 without `Retry-After` reading as `unreachable`.

## 5. An amendment to Rio Grande's 3.11

Add a sixth error kind, **`unauthorized`**: the key is expired or revoked. The client stops sending, keeps its outbox
for the station's drain (3.9), and shows it at the next wake. On a cluster, a per-job key that expires mid-session
reaches this case. Deleting the outbox there would lose work.

## 6. Not in this spec

- Asking from a pull peer, and an asynchronous crossing to one.
- Crossings over cluster route B.
- Crossings between peers with no pairing.
- One uid per ship on a shared machine.
- The rail's routing (rail-mathematics) and the commons' rules (rail-commons). This only carries their traffic.
