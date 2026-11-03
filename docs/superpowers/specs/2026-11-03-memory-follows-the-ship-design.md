# Memory follows the ship: Engram's side

Rio Grande, 2026-11-03. Andy: "the engram probably shouldn't necessarily all be in folders. it should stay with you. at
least parts of it". Tardis takes the station half: a session key resolves to its ship's home, the cluster station, and
"lighthouse crossing between peers", a spec of its own. This page is the Engram half: what follows the ship, who
writes it, and how a session far from home uses it.

Revision 3. A fresh Pi reviewer approved revision 2 with changes (station law section 3), and its changes are folded
in here. Revision 1 (5e80abaa) got REVISE: the core held,
with four gaps (exactly-once across files, away mode for state-dependent calls, per-session state, numbering across
processes). Revision 2 (cf6cbf68) got APPROVE WITH CHANGES, with five bounded edits, folded in here: an outbox epoch
and AUTOINCREMENT (3.3), expired operations and replayed refusals (3.3), the delivered-content guard at replay (3.4),
the operation kinds' edges (3.5), and cluster outboxes as files (3.9).

## 1. Why

- **The cluster.** The first supercomputer is 600 nodes. A ship's sessions run on whichever nodes its jobs land on,
  and a node's scratch disk dies with its job. With memory in folders, a ship's memory is lost, or split into hundreds
  of stores that never meet.
- **The rail.** A trail is the sequence of memories a session touched (rail mathematics, section 1). A trail needs the
  whole session in one store. Split stores give broken paths, and no road forms from them.
- **Cost.** Every Claude session runs its own Engram server today: about 240 MB at rest, and 1.1 GB if it loads the
  model itself. A thousand agents can't each carry that. One store host per site, serving many ships, can.

## 2. What the code does today (checked by the reviewer, 2026-11-03)

- A ship's store is `<memory_home>/.engram/instances/<ship>/graph.db`, with `cold.db`, `clipboard.db`,
  `categories.db`, `categories_v2.db` and `knowledge.kuzu` beside it. Only `config.resolve_db_path` warns when the
  instance store is missing. The MCP server and the three hooks fall back to the legacy `~/.engram/graph.db`
  **silently**. That's how Rio Grande ran on the wrong store until this morning.
- Instance resolution has five copies (the three hooks, `server._init`, `config.py`), and 24 non-test lines build
  `instances/` paths.
- Of the 45 MCP tools, 32 are marked mutating. Of the other 13, `recall` writes (access counts, log rows) and
  `search_code` reindexes into `graph.db`. The biggest writers aren't tools:
  - **nudge** inserts and prunes episodes, and writes residues, `session_bias` and co-firing rows;
  - **wake** runs the deep pass and the assessment state;
  - **sleep** writes residues every time Stop fires.
- One call can write several files. `remember` of delivered content writes the permission ledger and receipts before
  the episode. Every tenth `remember` in a session runs `auto_compress` inline. `log_outcome` writes `categories.db`.
  Prune writes `cold.db`.
- Per-session state is shared store-wide: `context_prev_embedding` is one row; `session_bias` has no session column
  and every wake clears it; the co-firing window uses a store-wide message index; one task context is active. The
  server keeps more in module globals (`_session_id`, `_recall_scores`, `_wander_visits`, ...) under one lock.
- The lighthouse crossing between stores is same-machine only, over a Unix socket.

So two machines can't each keep a copy of a ship's store and merge later. Each would decay the same episodes,
compress the same clusters into different semantics, and count the same recalls twice.

## 3. Decisions

### 3.1 One home, one writer

- **Each ship has one home: one station holds its store.** For a laptop or the Pi, that's the ship's own machine. For
  a cluster ship, it's the cluster station. A home is chosen when the ship docks, and moves only by export and import
  (3.10), never by a session.
- **The home's store host is the store's only writer.** It applies operations, runs maintenance on its own schedule
  and answers reads. It keeps every invariant Engram has today: one decay clock, one compression, one model per store,
  one `instance_id`.
- One session is several processes: the MCP client and the short-lived hooks. All of them are clients, and none opens
  a store.

### 3.2 What lives where

| Part | Where | Why |
|---|---|---|
| `graph.db`, `cold.db`, `categories.db`, `categories_v2.db`, `clipboard.db` | **Home** | The ship's memory and attention. The clipboard reads the store and the embedder, so it lives with them. |
| `knowledge.kuzu` | **Home**, opened only by maintenance | See 3.8. |
| `jot`'s `scope="global"` notepad | **Home**: the ship's notepad | "Machine-wide" means nothing on a cluster. At migration, the machine's `~/.engram/notepad.db` is copied into each ship homed on that machine. |
| `jot`'s `scope="project"` notepad | The checkout (`<repo>/.engram/notepad.db`) | Notes about a repository stay with it. |
| The code index | The checkout, in `<repo>/.engram/code-index.db` | It indexes files on that disk. It's embedded by the machine's shared embedder when one runs; otherwise `search_code` says there's no index. Migration drops the code-index rows from `graph.db`. |
| Publisher policy, receiver settings, the published house | **Home**, beside the store | Sharing is decided where the store is. |
| `permissions.db`, `permission-uses.db` | **Home**: one pair per owner at each station, under that owner's memory home there | Each home's owner sets its permissions (rail commons, principle 2). Signing stays the owner's own act. |
| The genome (`genome/graph.db`, `signals.db`) | **The owner's machine** | It's the owner's. It syncs into a ship's store only at a home on the owner's machine. Anywhere else it needs an imprint. |
| `~/.reader/reader.db` | The machine that has it (the Mac) | The deep pass reads it only where it is. |
| A person's memories | Never in a ship's store | Imprints, under the owner's consent, as today. |

### 3.3 Operations through a local outbox

- **Every operation goes into a local outbox before it's sent,** away or not. The outbox is one SQLite file per
  session: `<outbox_dir>/<ship>/<session_id>.db`. The MCP client and the hooks share it.
- **The outbox numbers operations.** `seq` is the outbox's `INTEGER PRIMARY KEY AUTOINCREMENT`, assigned inside the
  insert's transaction, so two processes can't take the same number, a killed process leaves no gap, and deleting
  acknowledged rows never lets a number come back.
- **Each outbox file has a random `outbox_id`,** made when the file is created and sent with every operation. A resumed
  session on another machine, a cleaned outbox directory or a replaced corrupt file gets a new `outbox_id`, so its
  numbers start a new epoch instead of matching old ones.
- **One sender at a time** drains the outbox in `seq` order, under a file lock. A hook that can't take the lock leaves
  its operation for the holder or the next sender. An operation leaves the outbox only after the home acknowledges it.
- **Exactly once by a high-water mark.** The home keeps one row per `(session_id, outbox_id)`: the highest `seq`
  applied and its client time. It applies `seq = high + 1` and nothing else. An `outbox_id` it hasn't seen starts at
  `high = 0`. A replayed `seq <= high` changes nothing and returns that operation's recorded refusal if it had one,
  otherwise `already applied`. A `seq > high + 1` is refused with `gap` and the expected number, and the sender
  resends from there. The row is updated in the same `graph.db` transaction as the operation's writes. This needs no
  retention rule: one small row per outbox, kept as long as the store.
- **Reads aren't answered twice.** A replayed read returns `already applied`, not its answer. The client re-issues a
  read it still wants as a new operation.
- **Expired operations.** An operation applied after its deadline (3.7) is recorded as `expired`: the high advances,
  and nothing else is written. This holds for Live-only operations, Touches and a hook's whole operation. So an
  agent told `unreachable` that retries a `share` can't end with two shares, and a nudge applied late writes no
  capture, bias or co-firing rows from a read nobody saw.
- **What it can't prevent.** A sender killed after the home applied an operation but before the acknowledgement leaves
  touches nobody read. That's rare, and the trail then has a step the session didn't see. It's recorded as a
  `sender lost` step on the session.
- **After a reconnect, live work waits.** The session's operations apply in `seq` order, so a live recall or nudge
  waits behind the backlog and may expire. That's expected. It lasts about the backlog's apply time: milliseconds per
  operation, and 0.1 to 0.5 s for each `remember` the Pi has to embed, so a thousand away remembers take a few
  minutes. During it, the client says `home catching up`.
- **A lost outbox** (a corrupt file) is the only source of a real gap. The client then sends an explicit `skip to n`
  operation, which the home records as a gap with its reason. Nothing is applied twice, and nothing stalls silently.
- **Ids are minted by the client:** `op_id` (a UUID, for cross-checking and logs), an episode's id in `remember`, and
  the `recall_id` of every recall. So no answer needs to be stored for a replay, and no stored answer holds content.
- **Time is the client's, bounded.** Each operation carries its client time. The home clamps it between the session's
  last applied client time and the time it received the operation. Decay and trails use the clamped time, so hours of
  away work don't land as one burst.

### 3.4 One operation, one `graph.db` transaction

- An operation's writes, and the session's high-water mark, are one `graph.db` transaction.
- **Writes that aren't decisions move behind `graph.db`.** The operation writes rows in `graph.db`. Maintenance then
  carries them to `categories.db`, `cold.db`, the knowledge graph and the genome, idempotently by row id. So
  `log_outcome` no longer writes `categories.db` inline, and `remember(genome=True)` marks its episode for the genome
  instead of writing it.
- **`auto_compress` leaves `remember`.** Compression runs only in scheduled maintenance.
- **The permission ledger and receipts are the exception.** A delivered copy's record has to exist before the copy.
  Each record carries the operation's `op_id`, and the writer refuses a second record with the same `op_id`. A replay
  after a crash between the record and the episode finds the record and **honours its decision**: it doesn't decide
  again, so the ledger never keeps a copy that didn't happen. This is the one change to the permissions code, and
  it's safety code, so its review follows station law section 2.
- **The delivered-content guard at replay.** `remember` treats content as delivered when it matches one of the agent's
  delivery receipts from the last 24 hours (`_keep_decision`). At replay, that window is measured at the operation's
  clamped client time, not at the time it's applied. The client also keeps digests of what was delivered to it, and
  sends a `remember` that matches one as Live only. So a delivered memory remembered while away can't come back 25
  hours later as a plain episode, with no copy record and no imprint check. This is safety code too (section 2).

### 3.5 Away from home

Every operation is one of four kinds. The plan's first task checks this table against the code, tool by tool.

| Kind | Live | Away | Operations |
|---|---|---|---|
| **Sent** | Applied at once | Kept in the outbox, applied on reconnect. Its answer is marked `provisional`; `task_focus`'s resumed context comes from the snapshot and says so. | `remember` (except delivered content and `genome=True`), `log_outcome`, `instinct_feedback`, `challenge_instinct`, `mark_core`, `unmark_core`, `unmark_core_batch`, `add_anchor` (its `anchor_id` minted by the client), `task_focus`, `task_update`, `task_done`, `dream_capture`, `dream_react`, `assessment_schedule`, `assessment_report`, `jot` and `erase` with `scope="global"`, `clipboard_pin`, `clipboard_unpin`, `clipboard_remind`, `clipboard_dismiss`; nudge's capture, residue, bias and co-firing writes; wake's writes (clearing its own session's bias, priming rows); sleep's residues and `auto_capture_outcomes` |
| **Touch** | The read runs at home and records what it touched | The read runs on the session's snapshot. The outbox records a touch: the ids seen, in order, with the `recall_id` and the client time. On reconnect the home records the touch. It never re-runs the read. A touched memory that's gone since is logged as gone. | `recall`, `look` of the ship's notepad, `wander`, `dream_surface`; nudge's recall |
| **Snapshot** | Read at home | Read on the snapshot, marked `degraded: ["home"]` | `core_memories`, `introspect`, `status` (it also says the home is unreachable), wake's orientation, `clipboard_view` (away it fires no reminders; reminders fire only at home, once) |
| **Live only** | Applied at home | Refused: `home unreachable` | `share`, `unshare`, `permit`, `permissions`, `shares`, `compress`, `compress_commit`, `retire_instinct`, `propose_retirement`, `revive`, `recall_cold`, `dream_verify`, `reflect`, `graph_view`, `remember` of delivered content or with `genome=True`, wake's assessment claim (an away session runs no assessment) |
| **Machine** | No home involved | Same | `search_code`, `reindex` (the code index is per checkout), `jot`, `erase` and `look` with `scope="project"` (the checkout's notepad). A `look` with no scope reads the checkout's notepad here and the ship's at home (or its snapshot), as it merges both today. |

- **Wake's deep pass** becomes home maintenance (3.8). It's no longer part of wake.
- **Codex sessions** get their session id from `session_bindings` at the home today. A Codex client that starts away
  mints its session id and sends the binding as a Sent operation, so its outbox and its trail stay one session.

- **Paired operations work by client-minted ids.** An away recall's touch carries its `recall_id`, so a later
  `log_outcome` naming it lands after it in `seq` order and finds it. `compress` and `compress_commit` are live only,
  because the pending compression lives in the home's memory. `dream_verify` is live only, and an away recall applies
  no dream bias, so there's nothing to verify.
- **Away search.** A snapshot recall embeds its query with the machine's shared embedder when one runs the store's
  model (checked by model id). Otherwise it searches by text alone. Its answer says which: `away_search: "vector"` or
  `"text"`.
- **Snapshots.** A session may fetch a read-only snapshot at start, capped in size, and refresh it. A session without
  one answers Touch and Snapshot reads with `home unreachable`.
- **A refusal at replay reaches the ship.** A provisional operation can be refused when it's applied, for example by
  the permission gate, which decides at application time. The home records each refusal with the session, `seq` and
  reason, and the ship's next wake shows them. The session that sent it may be gone by then.

### 3.6 Many sessions of one ship at once

- **A migration keys per-session state by `session_id`:** `context_prev_embedding`, `session_bias` (each wake clears
  only its own session's rows) and the co-firing window, whose message index becomes per session.
- **Task contexts:** one active context per session. `task_focus` archives only that session's previous context.
  Wake resumes the most recently updated open context that no live session holds. A session holds a context while its
  last operation is under 2 hours old. A ship running one session at a time keeps today's behaviour.
- **Claims:** the next-session assessment and an unreacted dream residue each go to the first session that claims
  them, atomically.
- **The server's globals become per-store and per-session contexts, with one lock per store.** This refactor is most
  of stage 1's work.

### 3.7 The home embeds, with an interactive lane

- Clients send text, never vectors. A request carrying a vector is refused. So a store holds one model's geometry,
  whatever machine its sessions ran on.
- The shared embedder gets a **priority lane**: a query from a recall or a nudge goes ahead of batch work (maintenance,
  experiments). Stage 3 waits for it.
- **Deadlines.** Each operation carries the client's deadline. The nudge's call home has 4 seconds, the budget the
  nudge's embed already has on `engram-neighbors-visible` (6e4f5b16, not yet on main). On a miss, the hook skips and
  says so, and never blocks the prompt. A recall applied after its deadline is recorded as expired, with no touches,
  so no one is said to have seen what no one read.

### 3.8 The store host

- **One process serves many ships.** It keeps at most `max_open_stores` stores open, and closes the least recently
  used first. Opening or reopening a store runs no maintenance.
- **Maintenance runs on a schedule,** per store, by maintenance workers, one store per worker at a time. Each store
  records its last maintenance in `meta`. A store idle for a long time decays as today's first open would; the host
  never prunes more than the in-process server would have.
- **Throughput.** A fresh store took about 40 s to compress (measured 2026-09-02). With one worker, 1,000 stores take
  about 11 hours. The host runs `ceil(stores × measured seconds per store / 12 hours)` workers, so every store is
  maintained at least twice a day. Steps that need Ollama (dedup, framing, knowledge extraction) run only where
  Ollama runs. The Pi has none.
- **The knowledge graph** is opened only by a maintenance worker, one store's at a time, with its 256 MB buffer pool.
  Recall at a host doesn't search it until a pooled design exists.
- **Budgets,** measured on the Pi before stage 1 is called done: the host with 10 stores open stays under 512 MB
  resident, besides the shared embedder and one maintenance worker. A thin client stays under 80 MB.

### 3.9 Failure modes

- **A poisoned operation** that fails 3 times is quarantined: recorded with its error, counted as a gap, and shown at
  the ship's next wake. The session's later operations continue.
- **A corrupt store** is marked unavailable. Its clients get `refused: store unavailable`, and every other store keeps
  serving.
- **Out of memory.** The host runs under a memory cap and restarts. On a cluster, hosts are sharded by ship, so one
  kill takes down a share of them, not all. Clients see `unreachable` and keep their outboxes.
- **Disk full:** writes get `retry`, and outboxes hold.
- **A dead cluster node.** On a cluster, outboxes live on the shared filesystem, not node scratch. Stop isn't relied
  on: it has 5 s and doesn't run when the scheduler kills a job. SQLite's locks aren't reliable on NFS or on Lustre
  mounted `localflock`, and WAL can't run there, so a cluster outbox isn't a SQLite file:
  - each operation is one file, written and then renamed into place, with its `seq` minted under a node-local lock;
  - only the job's own node writes;
  - a drainer deletes only files with `seq` at or below the home's high;
  - the station drains a job's outbox only after the scheduler reports the job ended;
  - files are mode 0600, in the ship's own directory, since they hold content.

### 3.10 Migration and moving a home

- An existing instance store becomes its ship's home in place. It keeps its `instance_id`; it's never forked.
- The legacy `~/.engram/graph.db` stays as a read-only archive, and no host or client opens it. Rio Grande's
  misrouted 2026-11-02 episodes are already in `instances/rio-grande` (copied 2026-11-03).
- No silent fallback: a client whose ship has no home store says so and stops.
- **Export and import:** a SQLite backup of `graph.db` and its side files, with a manifest (ship, `instance_id`,
  counts, digests). Import refuses an `instance_id` already homed at that station. The old home marks the store moved
  and refuses writes with `moved`, naming the new home.

### 3.11 The interface with Tardis's half

- **The request envelope.** From authentication, never from the request body: `ship`, `agent_ref`, and whether the
  agent acts for the owner (gate G13). From the client: `session_id`, `seq`, `op_id`, `client_time`, `deadline_ms`,
  `kind`, and the tool and its arguments.
- **Error kinds:** `unreachable` (keep the outbox), `retry` (with a delay), `gap` (with the expected `seq`), `refused`
  (permanent, with a code), `moved` (with the new home), and `unauthorized` (Tardis, 2026-11-03), with its reason:
  - `expired`: the client stops sending and keeps its outbox. Under a renewed key for the same ship it replays.
  - `revoked`: the client stops and keeps its outbox, but never replays it, since a revoked key may mean a stolen one.
    The ship's next wake under a new key says how many operations are held, and nothing of them is applied.
  Today's dock client deletes its key on a 401. That would lose a per-job key's work, so the client changes too.
- **A ship reaching its own home is a different route from a crossing.** Its own store: every tool, read and write,
  no publisher policy. A crossing: another store, under its policy, recall and read only, with receipts. Two routes,
  two checks, so a bug in one can't widen the other.
- **Stage 1 can't prove the ship.** On the Pi, ships share the uid `andy`, so a local socket can't tell them apart,
  and any of them could open another's file anyway. Stage 1 proves routing: a client configured as ship A never
  touches B's store. The "one ship" test belongs to stage 3, with authenticated transport.

## 4. Stages

Each is small, reversible and measured, in the commons' order.

1. **The store host on one machine.**
   - The Pi's ships use their stores through a local host over a Unix socket. The MCP server and the hooks become
     clients, and the five copies of instance resolution become one.
   - The work: the server refactor (3.6), the outbox (3.3), side writes behind `graph.db` (3.4), the per-session
     migration, and scheduled maintenance.
   - Rollback: `mode = "local"` opens the store in process, as today.
2. **Away mode.** The home is made unreachable on purpose, with snapshots and the operation kinds (3.5).
3. **Across machines.** The same requests over Tardis's transport, with the interactive embedder lane: a Tardis session
   uses its home store from another machine.
4. **The cluster station.** A cluster ship's sessions on many nodes share one store, with outboxes on the shared
   filesystem, and their trails form there.

## 5. Tests that prove it

- **Parity:** every MCP tool's existing tests, run through the client against a host, give the same answers, and wake's
  orientation text is identical, except where this spec changes an answer on purpose:
  - `log_outcome` no longer returns `category_cells`;
  - `remember` no longer returns `auto_compressed`;
  - a recall at a host doesn't search the knowledge graph;
  - away answers carry `provisional` or `degraded`.
- **Hooks in time:** nudge, wake and Stop through the client finish within their timeouts while another store is
  mid-compress, and a missed deadline skips and says so.
- **Exactly once:** an operation sent twice, or replayed after a crash at each step (including between the ledger
  record and the episode), changes the store once.
- **Numbering:** the MCP client and a hook in one session never take the same `seq`, a hook killed mid-send leaves no
  gap, and a real gap is refused, resent and never stalls. A session resumed with a new outbox, and an outbox whose
  acknowledged rows were all deleted before an insert, lose nothing.
- **Deadlines:** a `share` sent, unacknowledged and retried after `unreachable` applies once; a nudge applied after
  its deadline writes nothing; a replay of a refused operation returns its refusal.
- **The guard at replay:** a delivered memory remembered away and replayed 25 hours later is still treated as
  delivered; a remember that matches a delivery digest is Live only; a replayed copy record honours its first
  decision.
- **Kinds at their edges:** an away `clipboard_view` fires no reminder, and the reminder fires once at home; two away
  sessions don't both run the assessment; a client-minted `anchor_id` survives replay.
- **Cluster outbox** (stage 4): a drain while the job runs is refused, and a drain after it ends deletes only what
  the home applied.
- **Concurrent sessions:** two sessions of one ship writing at once lose nothing, land in their own order, and share no
  per-session state (bias, topic shift, co-firing, task context).
- **Away:** each operation behaves as its kind says, including a `log_outcome` of an away recall, a refused
  `compress_commit` and `dream_verify`, and a refusal at replay that shows at the next wake.
- **No vectors:** a request carrying a vector is refused.
- **Migration:** a migrated store keeps its `instance_id`, counts and decay state, and closing and reopening it runs no
  maintenance.
- **Quarantine:** a poisoned operation is quarantined after 3 failures while other ships keep working.
- **No silent fallback:** a client with no home store says so and stops.
- **Memory:** the budgets in 3.8, measured on the Pi.
- **One ship** (stage 3): a session authenticated as ship A can't read or write ship B's store by any argument.

## 6. Not in this spec

- The station API, session authentication and the transport: Tardis's half.
- Sharing between ships: the lighthouse crossing and the rail commons.
- A person's memories: imprints.
- Copies of a home for failover. A home is backed up as stores are today.
- A ship with two homes. One home, and the rail carries what one site learns to another (the reviewer agreed).
