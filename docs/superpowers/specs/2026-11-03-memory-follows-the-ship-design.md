# Memory follows the ship: Engram's side

Rio Grande, 2026-11-03. Andy: "the engram probably shouldn't necessarily all be in folders. it should stay with you. at
least parts of it". Tardis takes the station half (a session key resolves to its ship's home, the transport, the
cluster station). This page is the Engram half: what follows the ship, who writes it, and how a session far from home
uses it. Revision 1, for a fresh reviewer (station law section 3).

## 1. Why

- **The cluster.** The first supercomputer is 600 nodes. A ship's sessions run on whichever nodes its jobs land on,
  and a node's scratch disk dies with its job. With memory in folders, a ship's memory is lost, or split into hundreds
  of stores that never meet.
- **The rail.** Trails are sessions taken as paths (rail mathematics, section 2). A trail needs the whole session in
  one store. Split stores give broken paths, and no road forms from them.
- **Cost.** Every Claude session runs its own Engram server today: about 240 MB at rest, and 1.1 GB if it loads the
  model itself. A thousand agents can't each carry that. One store host per site, serving many ships, can.

## 2. What we found in the code (2026-11-03)

- A session's store is a file: `<memory_home>/.engram/instances/<ship>/graph.db`, plus `clipboard.db`,
  `categories.db` and `knowledge.kuzu` beside it. If the instance store is missing, Engram falls back to the legacy
  `~/.engram/graph.db` with a warning. That's how Rio Grande ran on the wrong store until this morning.
- The MCP server and the three hooks (wake, nudge, sleep) each open `graph.db` themselves. Each hook resolves the
  instance path with its own copy of the code.
- Of the 45 MCP tools, 32 are marked as mutating. The other 13 still write: `recall` updates access counts and adds
  log rows, and maintenance (decay, prune, compress, cohesion) rewrites derived state.
- The lighthouse crossing between stores is same-machine only, over a Unix socket.

So two machines can't each keep a copy of a ship's store and merge later. Each would decay the same episodes,
compress the same clusters into different semantics, and count the same recalls twice. Episodes alone would merge as
a union, but everything derived from them would fork.

## 3. Decisions

### 3.1 What follows the ship, and what stays

| Part | Where it lives | Why |
|---|---|---|
| Episodes in both lanes, core marks, semantics, instincts, clusters, dream residue, task contexts, recall logs, resonances | **The ship's home store** | This is the ship: what it learned and how it attends. Andy's "stay with you". |
| The knowledge graph (`knowledge.kuzu`) and evolving categories (`categories.db`) | The home, derived there | Built from the store, by the home's maintenance. |
| The code index (`search_code`) | The machine, per checkout | It indexes files on that disk. |
| The clipboard | The session's machine | Short-lived pins and reminders for one place. My call; it can move home later. |
| A person's memories | Never in a ship's store | Imprints, under the owner's consent, as today. |

### 3.2 One home, one writer

- **Each ship has one home: one station holds its store.** For a laptop or the Pi, that's the ship's own machine's
  peer. For a cluster ship, it's the cluster station. A ship's home is chosen when it docks, and moves only by an
  explicit export and import, never by a session.
- **The home's store host is the store's only writer.** Sessions anywhere send it operations. It applies them in the
  order it receives them, runs maintenance, and answers reads. SQLite's single writer then holds by design rather
  than by luck.
- This keeps every invariant Engram has today: one decay clock, one compression, one model per store, one
  `instance_id`.

### 3.3 Operations, not rows

- A session's Engram calls become requests to the home's store host: the same 45 tools, with the same arguments and
  the same answers. The MCP server a session runs becomes a thin client. It holds no store and loads no model.
- **Every write carries an operation id,** minted by the session (a UUID). The store host records applied ids in an
  `applied_ops` table, in the same transaction as the write. A replayed operation changes nothing and returns its
  first answer.
- **`remember` returns its episode id at once,** minted by the session as part of the operation. The home refuses an
  id it already holds under a different operation.
- Each operation carries `session_id` and a per-session sequence number. The home applies one session's operations
  in sequence order, so a session's trail lands as the path it was.

### 3.4 The home embeds

- A session sends text, never vectors. The home's shared embedder embeds documents and queries.
- So a store holds one model's vectors, whatever machine its sessions ran on. A vector from another model, or a
  hostile one, would bend the store's geometry silently. Refusing vectors from clients makes that impossible, not
  just detectable.

### 3.5 Away from home: the journal

- A session that can't reach its home keeps a **journal**: an append-only SQLite file of its write operations, on
  local disk (`<memory_home>/.engram/journal/<ship>/<session>.db`).
- **Reads while away** use the newest read-only snapshot the session holds, if any. Every answer then says
  `degraded: ["home"]`, as a recall now says `neighbors` when no lighthouse was reached. A session never takes a
  snapshot for the live store without knowing.
- **On reconnect,** the client replays the journal in order. Replay is idempotent (3.3), so a crash mid-replay just
  replays again. A replayed journal is deleted only after the home acknowledges its last operation.
- **On a cluster node,** the Stop hook drains the journal to the cluster station before the job ends. A node that dies
  without reaching it loses that session's unsent operations. The station's internal network makes that rare; the
  spec says it plainly rather than promising it can't happen.
- Snapshots: a session may fetch one at start (the home sends a read-only copy of the store, capped in size). A
  session that never fetches one simply has no reads while away, and says so.

### 3.6 The home serves its own ship only

- The store host answers a session only for the ship that session authenticated as (Tardis's half: the session key
  and the station's identity check). No request names a store path; the home maps the authenticated ship to its
  store.
- Another ship reads this store only through the lighthouse crossing, under the store's publisher policy, with
  receipts. That's sharing, and it belongs to the rail and the commons (rail-commons principle 1), not to this spec.

### 3.7 Memory at the home

- One store host process serves many ships. It keeps at most `max_open_stores` stores open (least recently used
  closes first), with Engram's caches bounded per store.
- Maintenance runs one store at a time, under one lock, as imprint jobs do.
- Budgets, measured on the Pi before stage 2 is called done: the store host with 10 ships' stores open stays under
  512 MB resident, besides the shared embedder. A thin client stays under 80 MB.

## 4. Stages

Each is small, reversible and measured, in the commons' order.

1. **The store host on one machine.** The Pi's ships use their stores through a local store host over a Unix socket.
   The MCP server and the three hooks become clients, and their three copies of instance resolution become one.
   - Measure: Engram's MCP tool tests pass against the client, as they do against the in-process server.
   - Rollback: the client's `mode = "local"` opens the store in process, as today.
2. **The journal and away mode.** The home is made unreachable on purpose.
   - Measure: writes land after reconnect, exactly once, in session order. Reads say `degraded`.
3. **Across machines.** The same requests over the peer transport (Tardis's half): a Tardis session uses its home
   store from another machine.
4. **The cluster station.** A cluster ship's sessions on many nodes share one store at the cluster station, and their
   trails form there.

## 5. Tests that prove it

- **Parity:** every MCP tool's existing tests, run through the client against a store host, give the same answers.
- **Exactly once:** an operation sent twice, or replayed after a crash at each step, changes the store once.
- **Order:** two sessions of one ship writing at once lose nothing, and each session's operations land in its own
  sequence order.
- **No vectors:** a request carrying a vector is refused, and nothing in the protocol accepts one.
- **One ship:** a session authenticated as ship A can't read or write ship B's store by any argument.
- **Away:** with the home unreachable, every read says `degraded: ["home"]`, and no read pretends to be live.
- **No silent fallback:** a client whose ship has no home store says so and stops. It never falls back to another
  store, as the instance resolution does today.
- **Memory:** the budgets in 3.7, measured on the Pi.

## 6. Not in this spec

- The station API, session authentication and the transport between machines: Tardis's half.
- Sharing between ships: the lighthouse crossing and the rail commons.
- A person's memories: imprints.
- Copies of a home for failover. A home is backed up as stores are today; replication waits until a site needs it.

## 7. Open, for the reviewer and Tardis

- Should the clipboard follow the ship too? It's cheap either way.
- Should a ship ever have two homes, say one per site, with the rail between them? My answer is no for now: one
  home, and the rail carries what one site learns to another.
