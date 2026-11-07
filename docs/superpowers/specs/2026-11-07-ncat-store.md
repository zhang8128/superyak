# The n-category store: a ship's memory use, kept as cells

Rio Grande, 2026-11-07, for Andy's "get a performant n category theory graph system up and running as a core component".
It's stage 3 of the plan on issue #2, built on Tardis's kernel (`2026-11-07-ncat-kernel.md`, approved with changes at
272c8f52). It needs a fresh reviewer, like any spec. It stays observational: nothing in recall reads it.

## What it's for

The kernel holds cells in memory and forgets them when the process ends. This store keeps them: which memories exist,
which uses joined them, and which sessions walked which paths. It's built from the ship's own Engram store. Rails, cost
and the sheaf (stages 4 to 6) are computed from what it holds, without re-reading Engram.

## The cells, from memory use

- **0-cell:** a memory, by its id. The store reads ids, never text.
- **1-generator, a road:** memory *a* then memory *b*, each used in one session, *a* before *b* with no used memory
  between them. There's one road per ordered pair, however often it's walked. A road from a memory to itself is allowed:
  the kernel's shape is unrolled per cell, so a loop doesn't make two uses commute.
- **A session:** the composite of its roads in order, a 1-cell. A session with one used memory is that memory's
  identity. Two sessions that walked the same roads in the same order are the same cell, and the store keeps one.
- **2-generators and up:** none in this stage. Stage 4 adds detours, a 2-cell from a path to a cheaper one, by a rule it
  will state. The tables below already hold any dimension.

**Used** means what E1′ meant: in `memory_log`, `event_type = 'recall'`, `context.session_id` names the session,
`target_ids` the memories returned, and `outcome LIKE 'used%'` marks them used (`scripts/rail_e1_prime.py`'s
`RECALL_SQL`, on branch `rail-mathematics`). That's per recall row, not per memory: one `log_outcome` marks every memory
that recall returned as used. It's coarse, and it's what the log records, so the store says so rather than guess.

**Order, exactly:**
- A session's used rows are sorted by their timestamp parsed to UTC, then by `memory_log.id`. A timestamp with no
  timezone is taken as UTC, which is how Engram writes them, and counted. Raw strings aren't
  compared, because mixed formats would change the order.
- Within a row, `target_ids` are taken in order with repeats dropped, keeping the first, as E1′ does. So a repeat inside
  one row makes no a→a road; the same memory used in two rows in a row does.
- Skipped and counted: a row with invalid JSON, no session id, an unparsable timestamp, or a `target_ids` that isn't a
  list of strings. A memory id that no longer names a memory (erased, see below) is dropped from its session, counted.

## The file

`ncat.db`, by default in the Engram store's directory, separate from it: nothing in `graph.db` changes. It's mode 0600,
like the store. It's derived and disposable: each run rebuilds it whole from the current log, into a temporary file in
the same directory, then renames it over the old one. The temporary file is created 0600 from the start, written with a
rollback journal (not WAL) so no `-wal` or `-shm` file follows it, closed, fsynced, renamed, and then its directory is
fsynced. So within a file nothing changes after it's written, a session
that spans two runs is simply whole in the second, and a recall whose outcome arrived later is read right next time.

| Table | Holds |
|---|---|
| `generator(id, dim, source, target, kind, ref, key)` | Generators in creation order, each with its kernel key. `source` and `target` are the ends' keys (none for an object). `kind` is `object` or `road` for now, and `ref` is the memory id or the ordered pair. |
| `composite(key, dim, recipe)` | Each held cell once, by the kernel's `key()`. The recipe is the expression that built it: a generator id, or (k, left key, right key). |
| `session(session_id, key, used)` | Each session's cell, and how many used memories it walked. |
| `road_use(road, session_id, step)` | Each walk of a road, so its weight is a count, not a guess. |
| `ingest(read_at, rows_read, rows_skipped, skip_reasons, engram_store, kernel)` | The run that wrote this file; `kernel` is a digest of the kernel's C source. |

**Generator ids are deterministic,** because the kernel's keys depend on creation order (the reviewer ran it): objects by
memory id, sorted; then roads by (source id, target id), sorted. A recipe names composites by key, never by a kernel id.
So the same log gives the same file, whatever the row order.

Opening the store makes a fresh `NCat` with an explicit `budget_words` and replays `generator` in id order. Replay
also checks that order (objects sorted by memory, then roads sorted by pair, each road's ends the objects its pair
names), a composite's dimension, a session's count, and that a session's key is its own walk in `road_use`, so a
swapped ref or a moved key is caught, not only a changed recipe. An unreadable or missing file is the same error. A composite
is rebuilt from its recipe when it's first asked for, and its key is checked against the stored one. A mismatch exits
with code 2 and a message, and touches nothing, because it means the kernel or the file changed under it. The fix is a
rebuild.

## Writes are checked

A generator or composite row is written only after the kernel accepted it. A refusal is counted in `ingest` and nothing
else about that cell is written. The whole rebuild is one transaction on the temporary file, so a crash leaves the old
`ncat.db` untouched and a stray temporary file, which the next run removes. One run at a time: an exclusive `flock` on
`ncat.db.lock`, which the system releases if the process dies, so the lock file's existence alone means nothing. A second
run exits saying another holds it.

## Reading Engram

`ncat-store rebuild --engram <path to graph.db> [--store <path to ncat.db>]` opens Engram with a `mode=ro` URI and
`query_only`, inside one read transaction, and reads `memory_log`'s recall rows and the ids in the episode and semantic
tables. Memory ids and session ids are opaque strings; no content, query text or vector is read. A WAL store opened
read-only may still need to write its `-shm` file. If it can't, the run stops and says so, rather than open the store
some other way: it runs as the store's owner.

**Erasure:** an erased memory's id leaves the next rebuild, because only ids still in the store become cells: ids in
`episodes`, `semantics` or `instincts`. A `target_ids` entry naming anything else is dropped and counted. When a person
erases everything, or removes the store, `ncat.db` must be deleted with it. Between an
erase and the next run the old file still holds it. So a rebuild runs after every erase, or hourly at most, whichever
the wiring stage can arrange; until then that window is a stated limit. An erased memory between two others joins
them: a, b, c with b erased gives a road from a to c, by the rule above. In this stage it's run on this
ship's own store only, by hand or on a timer, never inside a served process: the kernel's reviewer asked for that until
its GIL and memory-budget fixes land.

## What it costs, as budgets for the tests

On the Pi, measured before this stage is called done:
- Rebuild from 10,000 recall rows in under 10 s, including the SQLite reads.
- Open a store of 100,000 generators in under 2 s.
- Rebuild a session of 200 roads from its recipe in under 5 ms.
- Keep the process under 256 MB, or say what drove it over: the kernel's resident memory runs about 5.7 times its counted
  words, by the reviewer's measure.

## Tests

- **Replay:** the same file opened twice gives the same keys, and a rebuild from the same log gives the same file content.
- **Determinism:** the same `memory_log` rows, inserted in another order, give the same keys.
- **Late outcomes:** a recall marked used after a first rebuild is in the second.
- **Erasure:** a memory removed from the store is gone from the next file, with its roads and its sessions' cells.
- **Skips:** each skip reason is counted, and a repeat inside one row makes no a→a road.
- **One writer:** a second rebuild while one holds the lock exits without touching the file.
- **Checked writes:** a generator the kernel refuses leaves no row, and its refusal is counted.
- **Crash:** killing a rebuild leaves the old file opening and replaying, and the next run clears the temporary file.
- **Integrity:** a tampered recipe or key is caught on open.
- **Loops and order:** a→b→a and b→a→b differ, and a session walking a→a→a is one road used twice.
- **Read-only:** a rebuild changes nothing in `graph.db`, and `ncat.db` is mode 0600.
- **The budgets above,** on the Pi, recorded.

## Rejected

- **Incremental ingest by timestamp:** outcomes and `target_ids` are updated after a row is written, so a row read early
  stays wrong, and sessions straddle runs. A whole rebuild costs seconds at this size, and an incremental design can come
  when a measure asks for it.

- **Storing cells in `graph.db`:** that mixes a derived structure into the person's store, and one bug could cost them
  memories.
- **One generator per walk:** that would make a road walked a thousand times a thousand generators, and stage 4's cost
  needs a count per road, not copies.
- **Reading text to label cells:** nothing here needs it, and it would cross the store-reading rule Andy hasn't ruled on.
