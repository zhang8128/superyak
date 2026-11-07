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
`RECALL_SQL`, on branch `rail-mathematics`). A session's used memories are taken in timestamp order, ties by recall id
then the order in `target_ids`. Rows with no session id or invalid JSON are counted and skipped.

## The file

`ncat.db`, beside the Engram store and separate from it: nothing in `graph.db` changes. It's append-only, in WAL mode.

| Table | Holds |
|---|---|
| `generator(id, dim, source, target, kind, ref)` | Generators in creation order. `source` and `target` are composite keys (dimension 0: the object's key). `kind` is `object` or `road` for now, and `ref` is the memory id or the ordered pair. |
| `composite(key, dim, recipe)` | Each held cell once, by the kernel's `key()`. The recipe is the expression that built it: a generator id, or (k, left key, right key). |
| `session(session_id, key, recalls, used, read_at)` | Each session's cell and its counts. |
| `road_use(road, session_id, step)` | Each walk of a road, so its weight is a count, not a guess. |
| `ingest(read_at, rows_read, rows_skipped, last_timestamp, engram_store)` | Each run, so a rerun starts where the last ended. |

Opening the store makes a fresh `NCat` and replays `generator` in id order. A composite is rebuilt from its recipe when
it's first asked for, and its key is checked against the stored one. A mismatch stops with an error, because it means the
kernel or the file changed under it.

## Writes are checked

A generator or composite row is written only after the kernel accepted it, in the same transaction as the counts. A
refusal is recorded in `ingest` and nothing else is written. So the file holds only cells the kernel holds, and a crash
mid-run leaves the last whole transaction.

## Reading Engram

`ncat-store ingest --engram <path to graph.db> --store <path to ncat.db>` opens Engram with a `mode=ro` URI and
`query_only`, inside one read transaction, and reads only `memory_log`'s recall rows newer than the last run's timestamp.
Memory ids and session ids are opaque strings; no content, query text or vector is read. In this stage it's run on this
ship's own store only, by hand or on a timer, never inside a served process: the kernel's reviewer asked for that until
its GIL and memory-budget fixes land.

## What it costs, as budgets for the tests

On the Pi, measured before this stage is called done:
- Ingest 10,000 recall rows in under 10 s.
- Open a store of 100,000 generators in under 2 s.
- Rebuild a session of 200 roads from its recipe in under 5 ms.
- Keep the process under 256 MB, or say what drove it over: the kernel's resident memory runs about 5.7 times its counted
  words, by the reviewer's measure.

## Tests

- **Replay:** the same file opened twice gives the same keys, and a rerun of ingest adds nothing.
- **Determinism:** the same `memory_log` rows, inserted in another order, give the same cells.
- **Checked writes:** a generator the kernel refuses leaves no row, and its refusal is counted.
- **Crash:** killing ingest between transactions leaves a file that opens and replays.
- **Integrity:** a tampered recipe or key is caught on open.
- **Loops and order:** a→b→a and b→a→b differ, and a session walking a→a→a is one road used twice.
- **Read-only:** ingest on a store opened read-only by another process changes nothing in `graph.db`.
- **The budgets above,** on the Pi, recorded.

## Rejected

- **Storing cells in `graph.db`:** that mixes a derived structure into the person's store, and one bug could cost them
  memories.
- **One generator per walk:** that would make a road walked a thousand times a thousand generators, and stage 4's cost
  needs a count per road, not copies.
- **Reading text to label cells:** nothing here needs it, and it would cross the store-reading rule Andy hasn't ruled on.
