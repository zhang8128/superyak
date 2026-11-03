# A ship's own home, and lighthouse crossings between peers

**Status:** revision 3, by Tardis. This is the station half of "memory follows the ship". Rio Grande's Engram half is
approved (branch memory-follows-ship), and its section 3.11 is the interface this spec meets.

**History:**
- **Revision 1** (d0cd0ec2) got REVISE: five Majors and nine should-fix items
  ([review](../reviews/2026-11-03-ship-home-and-crossing-review.md)).
- **Revision 2** (821df03c) got REVISE on re-check ([re-check](../reviews/2026-11-03-ship-home-and-crossing-recheck.md)).
  Three items needed decisions (A, B, C), with leftovers S-a to S-f. This revision makes those decisions:
  - **A:** one ledger agent per home stands for every remote store.
  - **B:** remote deliveries are recorded locally, and `remember` refuses them in every gate mode.
  - **C:** Tardis is a pull peer, so stage 2 runs Tardis asking and the Pi answering.
- Rio Grande split `unauthorized` into `expired` and `revoked` in its 3.11 (9d2f7ac6), and section 1.2 says which one
  a 401 means.

## Why

- Andy, 2026-11-03: "the engram probably shouldn't necessarily all be in folders. it should stay with you. at least
  parts of it."
- Engram's lighthouse crossing is same-machine only. A receiver reaches its publishers over the publisher daemon's
  Unix socket (engram/docs/lighthouse-receiver.md). So the rail commons' stage 4, two stores on two machines, has no
  transport.
- Rio Grande's half makes each ship's home store the only writer, and every session a thin client. Those clients
  need an authenticated way to reach their home.

## Two routes, two checks

| | Own home | Crossing |
|---|---|---|
| **Who asks** | A session of ship S | A receiving store's home, through its own peer |
| **Which store** | S's own store, at S's home | Another ship's **published house**, at a listening peer |
| **What serves it** | The home's store host, the only writer | The publisher's **read-only lighthouse daemon**. Never the store host |
| **What it may do** | Every tool, read and write (the 3.11 envelope) | The local crossing's `query` and `read` frames, unchanged in meaning |
| **What decides** | Authentication alone | The publisher's policy, audience map and ledger per operation, then the receiver's policy |
| **Records** | The host's operation log | The publisher daemon's sidecar and the publisher peer's `crossings` table, plus the receiver's receipt and its local delivery record, all linked by `disclosureId` |

They're separate routes, with separate handlers and separate tests. A crossing never reaches a store host, so it
can't write a store or lay a trail.

## 1. Own home

### 1.1 On the same machine (Rio Grande's stages 1 and 2)

- **Where clients connect:** the store host listens on `<memory_home>/.engram/host.sock`, mode 0600, owned by the
  station's user. No network port.
- **What it proves:** routing only (3.11). On one uid, a hostile process could pose as another ship. The envelope's
  `ship` comes from the client's configuration here, said plainly.

### 1.2 Authenticated (stage 3): a session away from its home machine

This covers a Tardis session on another machine reaching Tardis's home, and a cluster session reaching the cluster
station.

**What a home needs first:** a running `serve` (its main app) and a ship user for each ship it hosts. Tardis has
neither today. It runs a pull peer with `federate` only (C). So stage 3 starts on a home that serves.

**A memory key, issued by the home.** A laptop ship's station key comes from the Pi, not from its home.
- **The changes this needs, named here:**
  - `ship_keys` gains a `scope` column (`station` or `memory`), by migration, with existing rows becoming `station`.
  - `ship_for_key` and `ship_key_is_valid` (ships.py:119-143) take the required scope. A memory key opens only
    `/api/ships/memory`, and a station key never opens it.
- **On a cluster station,** the per-job session key (cluster station spec, section 3) is a memory key there. Its
  expiry columns stay under that spec's review.

**The route** is `POST /api/ships/memory`.
- **From the key:** the home maps the key to its ship, and sets `ship`, `agent_ref` and G13 from that. The store host
  maps ship to store (3.1).
- **From the body:** the client's half of the envelope only: `session_id`, `outbox_id`, `seq`, `op_id`,
  `client_time`, `deadline_ms`, `kind`, and the tool and its arguments.
  - `outbox_id` is in the body because the high-water mark is keyed by it (3.3). 3.11 should list it too, and that's
    asked of Rio Grande.
- **Reach** (S-d): tailnet-only, as imprints are (app.py:250-255). The public route refuses it, **except on a cluster
  station,** where compute-node clients count as public (`is_public`) and must reach it by key.

**Limits:**
- the body is at most 1 MiB;
- `deadline_ms` is 500 to 10,000;
- each key gets a rate limit.

The client never queues an operation over the cap; the tool call gets `refused: too_large` at once.

**Answers.** Each row is mapped once and tested once:

| Case | HTTP | Client does |
|---|---|---|
| Applied | 200 `{status: "applied", result}` | uses the result |
| A replay, already applied | 200 `{status: "replayed"}` | an ack; no stored answer is kept (3.3) |
| Expired at the host | 200 `{status: "expired"}` | drops it, shown at next wake |
| Busy or disk full, with `Retry-After` | 503 `Retry-After: n` | `retry` |
| `seq` ahead of `high` | 409 `{kind: "gap", expected}` | `gap` |
| Moved | 409 `{kind: "moved", home}` | `moved` |
| Refused at the host | 403 `{kind: "refused", code}` | `refused`. A 403 without `code` reads as `unreachable` |
| Refused at the station before the host (a 400 or 413 on a body the client did send) | 400 or 413 `{kind: "refused", code, seq?}` | sends 3.3's `skip to n` for that `seq`, so `high` advances, then continues. With no `seq` it can name, it stops and shows the gap at next wake |
| Key expired | 401 `{kind: "expired"}` | **`expired`** (Rio Grande's 3.11): stops, keeps the outbox, and replays under a renewed key for the same ship |
| Key revoked | 401 `{kind: "revoked"}` | **`revoked`**: stops, holds the outbox and never replays it. The next wake under a new key says how many operations are held |
| Any other 401 | 401 | read as `revoked`, the safe reading |
| Connection failed, a timeout, any other 5xx, or a 503 without `Retry-After` | (none) | `unreachable`: keeps the outbox and backs off |

The memory client never deletes a key, unlike the dock client (dock.py:67-71). Off a cluster there's no station drain,
so a held or expired outbox stays on that machine until a renewed key replays it, or the owner discards it.

**What isolation needs:** a key proves the ship only as well as the key is kept. Per-job keys on a cluster live inside
the job. On one uid on one machine, any process can read any ship's key, and real isolation there needs one uid per
ship, which this spec doesn't require.

## 2. Crossing between peers

### 2.1 Who asks, and who can be asked

- **Only listening peers can be asked.** A crossing is a request to `federation-listen`, which runs on push peers. The
  Pi is one. Tardis isn't: its peer is a pull peer (`peer_meta.federation_mode = 'pull'`), running `federate` only,
  and a peer's mode never changes (pull spec, section 1). So **nothing can ask Tardis** until Tardis has a push
  identity, which is a new data directory and outside this spec.
- **Any peer with a long-running federation process can ask.** It asks through its own local socket (2.4):
  - on push peers, `federation-listen` opens it;
  - on pull peers, `federate` does. It's a Unix socket, not a network listener.
  - On the Mac, law section 6 governs listeners while a browser lane runs, so the Mac asks only once that's settled
    (section 6 below).
- **Cluster route B** carries no crossings.

### 2.2 Who the receiver is, and how the publisher judges it

**The receiver ref.** The destination builds it from what it has verified:

`urn:superyak:<origin peer_id>:store:<receiving instance_id>`

- It contains `:`, so it can't match a local `NAME`, and is never judged by a local store's files.
- It binds the verified origin, so a paired peer can't name another peer's store to take its audience.
- A store that moves home loses its grants until they're granted again.

**The publisher's three checks,** each on its own terms:
1. **Policy** (`lighthouse-policy.json`):
   - a rule must name the exact ref;
   - selector matching never lets a wildcard or prefix match a `urn:superyak:` ref. That's a code change at
     lighthouse_policy.py:78-83 and the rule selector at lighthouse_daemon.py:785-798.
2. **Audience map** (`engram:audiences`): it accepts the remote form as a key, in sharing's validation and in
   `_allowed_audiences` (lighthouse_daemon.py:208-236; also :958 and :988-992).
3. **The permission ledger (A).** Agent names can't hold `:` (permissions.py:104, 138-139), and an unregistered
   requester is refused (permissions.py:2062-2067).
   - **One reserved ledger agent per home, `remote-stores`,** stands for every remote ref. The home's owner registers
     it once, with the place `outside-home`.
   - Every crossing is judged in the ledger as `agent:remote-stores` at `outside-home`. So every ledger rule that
     keeps a memory inside the home holds for every crossing.
   - The audience map and policy, by exact ref, decide which remote store sees what.
   - Until the owner registers it, every crossing is refused (`UNKNOWN_REQUESTER`), so a home fails closed.
   - Local instance creation refuses the name `remote-stores`.
   - The ledger sites that take a local name (lighthouse_daemon.py:483-486 agent and place, :499-512 the receiver's
     policy file) branch on a remote ref: the reserved agent, and no local receiver file.

That's one owner act per home, ever, not one per store. This is safety code under law section 2.

**The ship behind the store** must be a current contact of the publisher's peer from that origin: not held, with a
current typed confirmation by the rule `connections()` uses. Holds belong to contacts (federation.py:78, 151-193). When
owner trust and `retired_peers` land, their holds apply through the same check.

### 2.3 The route

`POST /federation/crossing`, on `federation-listen` only, added to listener.py's `ROUTES` with a 16 KiB cap.

**The request** is canonical JSON with exactly these keys:

| Key | Rule |
|---|---|
| `version` | `1`, an `int` |
| `kind` | `"crossing"`. Reserve `crossing` and `crossing-answer` beside `RECORD_KEYS` |
| `origin`, `destination` | `peer_id`s |
| `receiver_instance` | the receiving store's `instance_id`, which must match the instance id pattern |
| `receiver_ship` | the receiving ship's participant id on the origin |
| `publisher_ship` | the asked ship's participant id on this peer |
| `frame` | the local crossing's own `query` frame (`purpose`, `context`, query text at most 4,096 characters, `k` at most 20) or `read` frame (`purpose`, `context`, `turnId`, at most 5 ids), validated by lighthouse_protocol. The destination **overwrites** its `receiver` with the 2.2 ref, and its `publisher` with the daemon name that `publisher_ship` maps to (below) |
| `deadline_ms` | an `int` from 100 to 10,000: the time remaining in the receiver's shared deadline |
| `nonce` | 32 lowercase hex characters |
| `at` | an `int` Unix time |
| `signature` | Ed25519 by the origin card's `signing_key`, over the canonical request without `signature` |

**`publisher_ship` to daemon publisher** (S-b): the publisher's peer keeps a map, in its peer config, from a hosted
ship's participant id to the published house's daemon name. A ship that isn't mapped is refused with 404, before any
Engram read.

**Checks before any Engram store, policy, ledger or sidecar is opened** (they touch `peer.sqlite3` only):
1. **Shape:** an exact key set and types, at most 16 KiB. Otherwise 400.
2. **Destination** equals this peer. Otherwise 403.
3. **Origin** is a paired peer, of any card version. Otherwise 403.
4. **Signature, then clock, then nonce,** in `serve_pull`'s order (federation.py:440-455): `at` within 5 minutes; the
   nonce inserted under the restore replay floor (federation.py:408-419). A replay gets 409 "Replay".
5. **Contact:** `receiver_ship` is a current, unheld contact from that origin (2.2). Otherwise 403. This is the
   rollback: an unpair or a hold stops crossings at the next request.
6. **Mapped:** `publisher_ship` maps to a daemon publisher. Otherwise 404.
7. **Load:** at most 2 crossings in flight per origin and 4 in total, so events and pulls aren't starved (listener.py:79).
   At most 60 a minute per origin; a whole cluster station's asks share that. Otherwise 429.

**Then the daemon.** federation-listen sends the rewritten frame to the publisher's read-only daemon over its local
socket. The daemon runs every check it runs today, plus 2.2's: policy reloaded per operation, purpose and context, the
exact-ref audience, the ledger as `remote-stores` at `outside-home`, expiry on its own clock, and its sidecar
`disclosures` row. It never touches the private store, so `unshare` removes a memory from crossings. It never serves
an imprint store (sharing.py:109-110).

**Read ids are bound** (S-f): for 30 seconds after a `query`, the daemon keeps `turnId` mapped to (the receiver ref,
the publisher, the candidate ids it actually returned). A `read` that differs in any of those is refused. That's a code
change at lighthouse_daemon.py:978-1000, named here.

**The crossings table** (S-c): the daemon learns only the frame, so the peer keeps the network half. After the daemon
answers with its `disclosureId`, federation-listen writes a row to `crossings(disclosure_id PRIMARY KEY, origin_peer,
receiver_ref, request_digest, nonce, at)` in `peer.sqlite3`. If that write fails, it returns 503 and no answer. The
daemon's sidecar row and this row link by `disclosureId`.

**The answer** is canonical JSON, signed by this peer, with exactly these keys:
- `version`;
- `kind: "crossing-answer"`;
- `origin` and `destination`;
- `request_digest` (SHA-256 of the canonical signed request) and `nonce`;
- `frame`: the daemon's `recall_result` or `read_result`, with its `disclosureId`;
- `signature`.

It's at most 128 KiB, with delivered text at most 32 KiB, as locally. The asking peer verifies the answer before
handing on the frame.

### 2.4 The receiver's side

- **Which process asks:** only the receiving home's store host, during a live `recall` with a `lighthouse_context`.
  Never inside an open `graph.db` transaction (3.4). An away recall gets no crossing, and says so in
  `degraded: ["neighbors"]`.
- **The local hop** goes over `<peer data dir>/crossing.sock`, mode 0600.
  - One host serves many ships, so the request names its `receiver_instance` and `receiver_ship`. The peer checks
    both against the home's own host configuration, so it's a store this home hosts, for that ship. A store not
    hosted here is refused. The same-uid caveat of 1.1 applies.
  - The peer signs, dials the publisher pinned (bounded by `deadline_ms`), verifies the answer, and returns the frame.
    Engram never holds a peer key.
- **Receiver settings:** `[[remote_publishers]]`, a format change to lighthouse_receiver_config.py:26-42, gives
  `peer_id`, the asked ship's participant id and `context`. At most eight publishers in total, local and remote.
- **The receiver's own checks** are unchanged: its policy grants `recall`, `read` and `inject_context`
  (neighbors.py:121, 139). The publisher's ref there is `urn:superyak:<peer_id>:ship:<participant id>` (neighbors.py:80,
  88, 117 take a `urn:engram:` prefix today, a named change). A failed receipt write suppresses content.
- **No silent fallback:** an unreachable or refusing remote publisher shows in `neighbors` and `degraded` by name.

### 2.5 What "inject" means across peers, and what's enforced (B)

In Engram, delivering read text **is** `inject_context`. So a crossing that delivers text needs it granted on both
sides, and stage 2 grants it. Two things are forbidden across peers, and each is enforced:

1. **No unasked text in a session.** Remote text never enters the wake or nudge hooks' output. Those hooks run no
   crossing: only `recall` with a lighthouse context does, in that turn.
2. **No remote text stored as memory.**
   - **The record:** the receiving home records every remote delivery locally, in its own `permission-uses.db`, in a
     `remote_deliveries` table. Each row holds the `disclosureId`, the content digest of each delivered item's
     normalized text, and digests of each of its sentences of 12 words or more. The table is created on first use.
     A failed record suppresses the delivery, as a failed receipt does.
   - **The guard:** `remember` refuses text whose digest, or any of whose sentence digests, matches a remote
     delivery. It does so in **every** gate mode, not only `enforce`, since today's guard reads only local
     deliveries and does nothing with the gate off (server.py:2104-2109).
   - **What it doesn't catch, said plainly:** a paraphrase. A model that restates remote text in its own words is
     making its own memory, and the receipt records that it saw the source.

## 3. Stages

1. **Own home on the same machine** (1.1), with Rio Grande's stage 1.
2. **One crossing: Tardis asks, the Pi answers** (rail commons stage 4, one direction):
   - **Setup:** the Pi publishes its work lane only, to Tardis's store ref. The Pi's owner registers `remote-stores`
     once. Recall, read and inject are granted on both sides for one context. Tardis's `federate` opens
     `crossing.sock`.
   - **The measure:** a recall on Tardis that delivers from the Pi's published house, with the same `disclosureId` in
     Tardis's receipt, in its `remote_deliveries`, in the Pi daemon's sidecar and in the Pi peer's `crossings`. Then
     lighthouse_sheaf on a few shared topics.
   - **The rollback:** the receiver off, or an unpair.
   - **The other direction** waits for a push identity on Tardis.
3. **Own home, authenticated** (1.2), on a home that serves, then cluster sessions.

## 4. Tests that prove it

**Crossing, refusals:**
- A held receiving ship and an unpaired origin are refused, and a probe shows no Engram store, policy, ledger or
  sidecar was opened.
- A wrong destination, a replayed nonce, a stale `at`, a bad signature and an unmapped `publisher_ship` are each
  refused before any Engram read.

**Crossing, who sees what:**
- **Audience:** a second store on an allowed peer gets nothing, and so does the right `instance_id` signed by another
  paired peer.
- **Selectors:** `urn:engram:*` doesn't match a remote ref; only an exact rule does.
- **Ledger:** with `remote-stores` unregistered, every crossing is refused. With it registered at `outside-home`, a
  memory the ledger keeps at home isn't delivered.
- **No local file:** a local instance named like the remote id contributes no policy and no ledger row.
- **Frame:** the frame's own `receiver` and `publisher` are overwritten.
- **Read binding:** a `read` with a mismatched `turnId`, receiver, publisher or id is refused, and so is one after
  30 seconds.

**Crossing, records and limits:**
- **Inject:** after a crossing, the wake and nudge outputs hold no remote text. `remember` of a delivered item, or of
  one of its sentences, is refused with the gate off, in shadow and in enforce.
- **Records:** `unshare` and an imprint store deliver nothing. A failed `crossings` write returns no answer. A failed
  receiver record suppresses the text. All four records link by `disclosureId`.
- **Deadline and load:** a slow publisher past `deadline_ms` delivers nothing and shows `degraded`. A third concurrent
  crossing from one origin gets 429 while events and pulls flow.
- **Two routes:** a 3.11 envelope on the crossing route is a 400, and federation-listen never dials a store host's
  socket.

**Own home, authenticated:**
- `ship` in the body is ignored.
- A station key on the memory route gets 401, and a memory key on any other route gets 401.
- Expired and revoked keys answer their kinds. Expired replays under a renewed key; revoked never replays.
- A 413 for `seq` n leads to `skip to n`, and the next operation applies.
- From Funnel, the route is refused except on a cluster station.
- Each row of the answers table maps as written.

## 5. Asked of Rio Grande's 3.11

- **List `outbox_id`** in the client's half of the envelope.
- **The 401 body** carries `kind: "expired"` or `kind: "revoked"`, and anything else reads as revoked (1.2).

## 6. Not in this spec

- A push identity for Tardis, and so the other direction of stage 2.
- The Mac asking, until law section 6's listener rule is settled for a Unix socket.
- An asynchronous crossing to pull peers.
- Crossings over cluster route B.
- Peers with no pairing.
- One uid per ship.
- The rail's routing and the commons' rules.
