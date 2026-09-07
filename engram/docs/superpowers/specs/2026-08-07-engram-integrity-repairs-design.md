# Engram Integrity Repairs Design

**Date:** 2026-08-07  
**Status:** Approved

## Goal

Repair five validated defects without changing Engram's public MCP tool names or
response shapes:

1. operation attribution retains content that should decay or be irrecoverable;
2. compression commits can partially apply and consume their retry token;
3. failed migrations can leave a half-applied schema;
4. the knowledge graph silently falls back to Graphiti's OpenAI embedder; and
5. the built wheel omits required runtime modules and assets.

The work includes a one-time scrub of sensitive payloads already stored in the
live operation log. Audit identity, timing, outcome, and target IDs remain.

## Constraints

- Preserve the user's current uncommitted changes.
- Keep all existing MCP tool names and response shapes compatible.
- Keep attribution fail-open: an audit failure must not block a domain mutation.
- Keep optional knowledge-graph failure non-fatal.
- Never send knowledge-graph content to OpenAI implicitly.
- Make data-integrity guarantees enforceable with failure-injection tests.

## Approach

Use a targeted integrity refactor rather than isolated symptom patches or a
general storage rewrite. The changes introduce narrowly scoped boundaries for
audit sanitization and compression transactions, make migration application
atomic, explicitly supply Graphiti's embedder, and correct distribution
metadata and assets.

## Privacy and Retention

### Future operations

Operation attribution will pass tool arguments through a centralized,
operation-aware sanitizer before serializing `details`. The sanitizer uses a
strict allowlist. It retains non-content metadata such as IDs, booleans, counts,
action names, lane, scope, model, harness, repository, outcome, and timestamps.

Content-bearing fields are excluded, including:

- episode and semantic `content`;
- dream `reaction` values;
- instinct challenge `evidence` and retirement reasons;
- task-context text;
- clipboard and notepad text;
- assessment narrative fields and notes; and
- compression summaries.

Unknown fields are dropped. Nested objects are not serialized wholesale.
`target_ids` remains the mechanism for associating audit rows with affected
records.

### Historical scrub

Migration 026 rewrites existing `operation_log.details` with the same strict
allowlist. Unrecognized or malformed historical payloads become `{}`. The
migration preserves operation name, session ID, harness, model, repository,
timestamp, target IDs, and outcome.

The scrub is deliberately irreversible because retaining the original payload
would continue violating the forgetting and dream-residue guarantees.

### Verification

Regression tests write unique markers through `remember`, `dream_capture`,
`dream_react`, task, clipboard, notepad, and compression tools. The markers
must not appear in `operation_log.details`. Dream-capture text must exist only
in its deliberately lossy representation.

## Compression Transactions

### Validation

Before the first write, `compress_commit` validates the complete request:

- the number of summaries matches the number of pending clusters;
- action is one of `new`, `reinforce`, or `discard`;
- kind is an allowed semantic kind;
- lane is `personal` or `work`;
- non-discard summaries have non-empty content; and
- reinforce summaries resolve a valid semantic ID.

Validation failures leave the database and pending compression unchanged.

### Unit of work

The pending `compress_id` remains registered until the commit succeeds. All
database writes produced by one compression commit execute in a single SQLite
transaction. Storage operations used inside that path support deferred commit
behavior so a nested helper cannot finalize partial state.

On failure, the transaction rolls back semantic rows, source links, vectors,
episode lane and compressed flags, core promotions, resonances, subdivision
events, persistence changes, instincts, cluster updates, and log entries. The
pending state remains available for a corrected retry.

External knowledge-graph feeding occurs only after the SQLite transaction has
committed. Its failure remains non-fatal and cannot roll back local memory.

### Verification

Failure injection covers early, middle, and late commit stages. Each test
asserts unchanged database state, a usable connection, and a retryable
`compress_id`. A successful retry must apply exactly once.

## Atomic Migrations

Each migration and its `schema_version` insertion form one transaction. Any
error triggers an explicit rollback before `Storage` initialization re-raises.
The next startup therefore sees the pre-migration schema.

Migration execution will account for SQLite `executescript` transaction
semantics rather than assuming an outer Python transaction remains active. A
failure-injection migration containing valid DDL followed by invalid SQL must
leave neither the DDL object nor a version record behind, and the connection
must remain reusable.

## Knowledge Graph Embeddings

Graphiti receives both:

- the existing Ollama-compatible extraction client; and
- an explicit local/Ollama-compatible embedder.

Engram will not allow Graphiti to construct its default OpenAI embedder. The
integration must not inspect or depend on `OPENAI_API_KEY`. If the installed
Graphiti API cannot accept the configured local embedder, initialization emits
one concise diagnostic, closes opened resources, disables the graph, and lets
the memory server continue.

Tests instantiate the real integration boundary with controlled clients and
assert that no OpenAI embedder is constructed.

## Packaging

Distribution configuration will include every runtime Python module and the
non-Python assets required at runtime:

- migrations;
- prompts;
- hooks and hook configuration; and
- the Engram skill definition.

An isolated-wheel smoke test builds the wheel, installs it into a clean
environment with dependencies, imports the server outside the repository,
initializes a temporary database, and lists MCP tools. The test must fail if a
runtime import or migration asset is absent.

## Documentation

Update the documented test count and knowledge-graph configuration to match
verified behavior. Document that operation attribution stores metadata only
and that migration 026 removes historical content payloads.

## Verification Plan

Implementation follows test-driven development for each defect:

1. add one minimal regression test and observe the expected failure;
2. implement the smallest root-cause fix;
3. run the focused test to green;
4. run the affected subsystem tests; and
5. proceed to the next defect.

Final verification includes:

- the complete pytest suite;
- byte compilation;
- an isolated wheel build, installation, import, and MCP tool listing;
- an isolated real MCP lifecycle and restart-persistence test;
- audit-marker and historical-scrub checks;
- compression and migration failure injection; and
- a final Git status check proving unrelated working-tree changes were
  preserved.

## Non-Goals

- Redesigning the entire storage layer around repositories or a general unit of
  work framework.
- Changing recall ranking, compression mathematics, or memory-layer policy.
- Making the optional knowledge graph a hard dependency.
- Rewriting existing user changes in deduplication, framing, or session
  binding.
