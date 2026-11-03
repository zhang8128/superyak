# A ship's own home, and lighthouse crossings between peers

**Status:** draft 1, by Tardis. This is the station half of "memory follows the ship". Rio Grande's Engram half is
approved (branch memory-follows-ship, 8a5df4da), and its section 3.11 is the interface this spec meets. Shaped in
"Superyak: all hands" (c03d1253, 8b63b590, 2ba0fa1b, 6e2ee85c, 9db071b5). A fresh reviewer comes next.

## Why

- Andy, 2026-11-03: "the engram probably shouldn't necessarily all be in folders. it should stay with you. at least
  parts of it."
- Engram's lighthouse crossing is same-machine only. A receiver reaches its publishers over a local Unix socket
  (engram/docs/lighthouse-receiver.md). Nothing carries a recall between machines, so the rail commons' stage 4, two
  stores on two machines, has no transport.
- Rio Grande's half makes each ship's home store the only writer, and every session a thin client. Those clients
  need an authenticated way to reach their home.

## Two routes, two checks

| | Own home | Crossing |
|---|---|---|
| **Who asks** | A session of ship S | A receiving store on a paired peer |
| **Which store** | S's own store, at S's home | Another ship's store, at its publisher's peer |
| **What it may do** | Every tool, read and write (the 3.11 envelope) | `recall` and `read` only. Never `inject_context` across peers |
| **What decides** | Authentication alone: it's S's own store | The publisher's policy, per operation, plus the receiver's |
| **Receipts** | The home's operation log (Rio Grande's half) | Both sides, as `lighthouse_receipt` events |

They're separate routes, with separate handlers and separate tests, so a bug in one can't widen the other. No code
path turns an own-home request into a crossing, or a crossing into a write.

## 1. Own home

### 1.1 On the same machine (stages 1 and 2 of Rio Grande's half)

- **The store host listens on a Unix socket** at `<memory_home>/.engram/host.sock`, mode 0600, owned by the station's
  user. Clients connect there. Nothing listens on a network port for this.
- **What it proves:** routing only (3.11, "Stage 1 can't prove the ship"). On one uid, every process can read every
  ship's key file. So a client configured as ship A reaches A's store and never B's, but a hostile process under the
  same uid could pose as B.
- **The envelope's `ship`** comes from the client's configuration here. The spec says so plainly, and stage 3 replaces
  it.

### 1.2 Authenticated (stage 3), for sessions away from the home machine

**The route** is `POST /api/ships/memory` on the home station's main app.
- **Authentication:** a ship key the home station issued. On a cluster station, that's a per-job session key (cluster
  station spec, section 3).
- **What the station sets:** it maps the key to its ship, and the ship to its store. It sets `ship`, `agent_ref` and
  whether the agent acts for the owner (gate G13) from that authentication, never from the body.
- **What the body carries:** the client's half of the 3.11 envelope only: `session_id`, `seq`, `op_id`,
  `client_time`, `deadline_ms`, `kind`, and the tool and its arguments.
- **How it reaches the store:** the station forwards it to the store host over the local socket in 1.1, and returns
  the host's answer.

**Limits:**
- the request body is at most 1 MiB;
- `deadline_ms` is between 500 and 10,000, and the host gives up at the deadline;
- each ship gets a per-key rate limit, and a 429 maps to `retry`.

**The public route:** a valid ship key already passes the public route's check (public-route spec, section 2). Ship
keys reach a named list of routes, and this route joins that list by name. An expired or revoked key fails exactly as
a revoked key does today: 401, which the client reads as "revoked". `unreachable` is reserved for a connection that
fails.

**Error kinds,** mapped once and tested once each:

| Host answer | HTTP | Client sees |
|---|---|---|
| applied, or replayed with no change | 200 | the result |
| busy, disk full | 503 with `Retry-After` | `retry` |
| `seq` ahead of the high-water mark | 409 `{expected}` | `gap` |
| store moved | 409 `{home}` | `moved` |
| quarantined, unavailable, policy | 403 `{code}` | `refused` |
| connection failed, or a station 5xx | (none) | `unreachable`, and the outbox is kept |

**What isolation needs, said plainly:** a key proves the ship only as well as the key is kept. On a cluster,
per-job keys live inside the job, so one ship's job can't read another ship's key. On one uid on one machine, it can.
Real isolation there needs one uid per ship, which this spec doesn't require.

## 2. Crossing between peers

### 2.1 Who can be asked

- **Only peers that listen.** A crossing is a request to `federation-listen`, which runs on push peers only (the Pi,
  Tardis). Pull peers (the Mac, a cluster station) **only receive**: their stores can ask, but nothing can ask them.
- **The deadline is why.** A recall has 2 to 10 s, and an answer delivered on the next pull would arrive after the
  turn that asked. An asynchronous crossing, as a neighbor result delivered later, is out of scope until we need it.

### 2.2 The route

`POST /federation/crossing`, on `federation-listen` only, so it's tailnet-only and reached as 7437 is today.

**The request** is canonical JSON with exactly these keys:

| Key | Rule |
|---|---|
| `version` | `1`, an `int` |
| `kind` | `"crossing"`. Reserve the mark beside `RECORD_KEYS`, as `pull` is |
| `origin` | the asking peer's `peer_id` |
| `destination` | this peer's `peer_id` |
| `receiver` | the asking store's `instance_id`, and its ship's participant id on the origin peer |
| `publisher` | the ship whose store is asked, by participant id on this peer |
| `action` | `"recall"` or `"read"` |
| `context` | the declared lighthouse context, which must match both policies |
| `query` | for `recall`: the query text, at most 2,000 characters. For `read`: memory ids from an earlier delivery, at most 5 |
| `limit` | an `int` from 1 to 5 |
| `deadline_ms` | an `int` from 2,000 to 10,000 |
| `nonce` | 32 lowercase hex characters, refused if seen in the last 24 hours |
| `at` | an `int` Unix time, within 5 minutes of the publisher's clock |
| `signature` | Ed25519 over the canonical request without `signature`, by the origin card's `signing_key` |

**Checks, in order.** Each refusal reads no store and no policy file:
1. **Shape:** any other key set, an oversize body (cap 1 MiB) or a bad type is a 400.
2. **Destination** equals this peer. Otherwise 403.
3. **Origin** is a paired peer: not held, not retired, and with a current typed confirmation, or owner trust for a
   ship. Otherwise 403. **This is the rollback:** an unpair, a hold or a retire stops crossings at the next request.
4. **Signature** verifies under the stored card's key. **Freshness:** `at` is within 5 minutes and the nonce is new.
   Otherwise 403.
5. **Rate:** at most 60 crossings a minute per origin peer. Otherwise 429.

**Then the publisher's own checks,** exactly as the local daemon makes them today (lighthouse-receiver.md,
"Withdraw"):
- it reloads the publisher store's `lighthouse-policy.json` per operation;
- `action` must be granted to an audience that names this **receiving store**, by `instance_id` and the origin peer;
  a peer alone never matches;
- the context must match;
- expiry is read on the publisher's clock.

The query runs against the **published house** only, never the private store, so `unshare` removes a memory from
crossings as it does locally. Nothing from an imprint is ever eligible.

**The response** is signed by this peer's key and holds:
- the same `neighbors` shape the local crossing returns: `sources`, `selected`, `delivered` with digests, the
  publisher's decisions and a `receipt_id`;
- delivered text capped at 32 KiB in total, as locally.

The receiver verifies the signature before it records anything or shows any text.

**Receipts on both sides:**
- **The publisher** writes a content-free receipt in the published house's log: origin, receiving store, action,
  context, query digest, delivered ids and digests.
- **The receiver** writes its `lighthouse_receipt` as today, with the publisher's `receipt_id` in it. The two ids
  link the crossing end to end.
- A failed receipt write on the receiver suppresses neighbor content, as locally.

### 2.3 The receiver's side

- **`lighthouse-receiver.toml` names a remote publisher** by peer id and ship, instead of a socket path. It's at most
  eight publishers in total, local and remote. The rest of the format is unchanged.
- **Which peer answers:** the client sends the crossing through the receiving machine's own peer, which signs it and
  makes the call. So only a machine's peer key signs, and Engram processes hold no peer key.
- **No silent fallback** (engram-neighbors-visible): an unreachable or refusing remote publisher shows in
  `neighbors` and `degraded` by name, with its error kind.

## 3. Stages

1. **Own home on the same machine** (1.1), with Rio Grande's stage 1.
2. **One crossing, Pi and Tardis.** The rail commons' stage 4: each publishes its work lane only, to the other's store,
   recall and read, no inject. The measure is a recall on the Pi that reaches Tardis's published house, with matching
   receipt ids on both sides, then lighthouse_sheaf on a few shared topics. The rollback is the receiver off, or an
   unpair.
3. **Own home, authenticated** (1.2), for cluster sessions, with the cluster station.

## 4. Tests that prove it

**Crossing:**
- **A held peer, a retired peer and an unpaired peer** are each refused at check 3, and a probe shows no policy
  file and no store was opened.
- **Wrong destination, a replayed nonce, a stale `at` and a bad signature** are each refused before any read.
- **The audience is a store:** a second store on an allowed peer, not named in the audience, gets nothing.
- **`inject_context` across peers** is refused by shape, since `action` takes only `recall` and `read`.
- **An unshared memory** is never delivered after `unshare`.
- **No imprint:** a policy that names an imprint store is refused.
- **Receipts:** both receipt ids are present and they link. A failed receiver receipt suppresses the text.
- **The deadline:** a slow publisher past `deadline_ms` delivers nothing, and the receiver shows `degraded`.
- **Two routes:** a request to the crossing route carrying a 3.11 write envelope is a 400, and an own-home request
  can't name another ship's store.

**Own home, authenticated:**
- `ship` in the body is ignored, so the authenticated ship decides.
- An expired per-job key gets 401.
- Each row of the error table maps as written.

## 5. Not in this spec

- An asynchronous crossing to pull peers.
- Inject across peers.
- Crossings between peers with no pairing.
- One uid per ship on a shared machine.
- The rail's routing (rail-mathematics) and the commons' rules (rail-commons). This only carries their traffic.
