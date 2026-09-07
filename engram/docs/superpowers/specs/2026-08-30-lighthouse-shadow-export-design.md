# Lighthouse Historical Shadow Export

**Date:** 2026-08-30

**Status:** Approved under the standing Engram/Lighthouse build authority

**Scope:** A read-only Engram exporter that produces the portable
`*.engram.json` recall-trace profile already implemented by Lighthouse. This
increment prepares honest historical replay inputs. It does not infer relevance
labels or claim recall improvement.

## Purpose

Lighthouse now has a strict adapter and offline evaluation apparatus for opaque
Engram recall traces. Its current proof uses synthetic fixtures. Engram already
contains real historical recall logs, including ranked memory IDs and the raw
query used for retrieval, but it has no safe way to project those records into
the portable profile.

This increment exports the smallest real corpus that can test the boundary:
work-lane episodes and semantics, their provenance, and historical recall
traces containing only those memories. Raw content and queries are hashed
inside Engram and never enter the portable document.

The local database currently contains 15 work-lane memories and 12 historical
recalls whose non-empty candidate lists are entirely work-lane material. That
is enough to validate the export path without broadening scope to personal or
relational memory.

## Approaches Considered

### Instrument only future recalls

The live recall path could write portable shadow events from now onward. This
would capture future context more precisely, but it would modify a high-risk
runtime path and provide no historical corpus. It remains a later option after
the offline format proves useful.

### Export through `Storage`

The exporter could instantiate Engram's `Storage` class and use its getters.
That class loads `sqlite-vec`, runs migrations, restores write-oriented
pragmas, checks vector health, and exposes mutation methods. Those behaviors
are appropriate for the live system and inappropriate for a proof whose first
claim is non-mutation.

### Direct read-only SQLite projection

The selected approach opens the database with SQLite URI `mode=ro`, enables
`PRAGMA query_only=ON`, starts a deferred read transaction, and issues only
explicit `SELECT` statements. It imports neither `Storage` nor the MCP server.
This makes the trust boundary small enough to audit and works against existing
history.

## Public Interface

A new standalone module, `lighthouse_export.py`, exposes:

```python
export_lighthouse_shadow(
    database: Path,
    *,
    instance: str,
) -> tuple[dict, ExportAudit]
```

The module also provides a CLI:

```text
python -m lighthouse_export \
  --db /path/to/graph.db \
  --instance engram-local \
  --output /new/path/local.engram.json
```

The output path must not already exist. Successful execution writes one
canonical compact JSON document and emits an aggregate audit record to stderr.
The audit contains counts only, never memory IDs, queries, sessions, content,
or per-trace details.

No server tool is added. Export remains an explicit offline administrative
action.

## Source Boundary

The exporter reads only these tables and columns:

- `episodes`: `id`, `content`, `content_hash`, `lane`;
- `semantics`: `id`, `content`, `content_hash`, `lane`;
- `semantic_sources`: `semantic_id`, `episode_id`;
- `memory_log`: `event_type`, `target_ids`, `context`.

It does not read embeddings, access counts, strengths, timestamps, session
bindings, outcomes, personal contexts, category stores, cold storage,
knowledge graphs, or federation databases.

Schema preflight checks the required tables and columns before reading data.
Missing structure fails with a stable diagnostic rather than silently emitting
an empty or partial document.

## Memory Projection

Only rows with literal `lane = "work"` are eligible. Episodes project as:

```json
{
  "id": "<source-local ID>",
  "layer": "episode",
  "contentDigest": {"algorithm": "sha256", "value": "<digest>"},
  "contextPath": ["memory", "technical"],
  "lane": "work",
  "origin": "lived"
}
```

Semantics use `layer: "semantic"` and `origin: "organic"`. Instincts are
excluded because they have no lane boundary and can encode personal behavioral
material.

The exporter recomputes SHA-256 over the in-database text and requires it to
match the stored `content_hash`. A missing or mismatched hash fails the export.
The text itself is discarded immediately after hashing and never enters the
output or audit.

## Provenance Projection

Each `semantic_sources` row becomes a directed edge only when both its episode
and semantic survive the work-lane filter:

```json
{
  "source": "<episode ID>",
  "target": "<semantic ID>",
  "type": "provenance",
  "weight": 1.0,
  "directed": true
}
```

Cross-lane and dangling provenance is omitted. Omission is counted in the
aggregate audit.

## Historical Trace Projection

Only `memory_log` rows with `event_type = "recall"` are considered. A trace is
eligible when:

1. `context` is a JSON object containing non-empty string `recall_id` and
   `query` members;
2. `target_ids` is a non-empty JSON array of unique non-empty strings;
3. every target ID belongs to the exported work-lane memory set.

The exporter drops an entire ineligible trace rather than removing personal or
unknown candidates and pretending the remaining ranking was what retrieval
produced. Aggregate counters distinguish malformed, empty, duplicate,
personal-or-unknown, and eligible traces.

An eligible row projects as:

```json
{
  "turnId": "<recall_id>",
  "queryDigest": {"algorithm": "sha256", "value": "<digest>"},
  "contextPath": ["memory", "technical"],
  "candidates": [
    {"memoryId": "<first target>", "rank": 1}
  ]
}
```

The query is used only to compute the digest. Session ID, outcome, margin,
timestamp, raw score, and all other log context are ignored.

If two rows claim the same `(recall_id, contextPath)`, export fails as ambiguous
instead of selecting one.

## Output and Determinism

The document root is fixed to:

```json
{
  "formatVersion": "1.0",
  "context": {
    "id": "memory/technical",
    "path": ["memory", "technical"]
  }
}
```

The caller supplies the non-empty `instance`. Memories sort by ID, edges by
their complete canonical value, traces by turn ID, and candidates preserve the
logged order with ranks compacted from one. JSON object keys are sorted and
the file ends with one newline. Database row order and filesystem paths never
enter the document.

The Lighthouse adapter remains the normative validator. A successful Engram
export is not considered interoperable until Lighthouse projects it into a
sealed snapshot.

## Error Handling and Non-Mutation

- A missing database, blank instance, existing output, or incompatible schema
  fails before output creation.
- Hash mismatches and duplicate trace identity fail the complete export.
- Individual legacy recall rows that cannot form an honest trace are excluded
  and counted by reason.
- Output uses exclusive creation. A failure removes any incomplete new file.
- The SQLite connection is URI read-only and query-only. The module never calls
  `commit`, migrations, vector loading, or Engram mutation APIs.
- The live validation run writes only to an OS temporary directory and does not
  retain the resulting export.

## Testing and Acceptance

Unit tests build minimal SQLite fixtures without importing `Storage` and prove:

- exact portable shape with no raw content or query fields;
- work-only memory, provenance, and trace filtering;
- whole-trace exclusion when one candidate is personal or unknown;
- stable aggregate exclusion counts;
- stored hash verification;
- deterministic output across insertion orders;
- stable diagnostics for malformed JSON, duplicate candidates, duplicate turn
  IDs, missing schema, and existing output paths;
- source database bytes and SQLite `total_changes` remain unchanged;
- the CLI never leaks raw source values through stdout or stderr.

Repository acceptance requires the full Engram test suite relevant to the
module, a clean focused diff, and projection of a temporary real export through
the Lighthouse adapter. The live validation report records only counts and the
sealed snapshot digest.

## Evidence Boundary

Historical `log_outcome` is per recall, not per selected memory. It cannot be
converted into receiver-owned relevance or forbidden labels without inventing
evidence. This increment therefore stops after producing validated replay
inputs.

The next increment is a local labeling queue that allows the receiver to review
technical turns and explicitly mark publisher-qualified memories relevant,
forbidden, or neither. Only then can Lighthouse run historical local-versus-
neighbor metrics.

## Deferred Work

- Personal, relational, instinct, or mixed-lane export.
- Automatic relevance inference from `used` outcomes.
- Changes to live recall logging or delivery order.
- Neighbor content delivery, context injection, retention, or resharing.
- Encryption, Starshine attestations, networking, and revocation.
- A reusable Lighthouse replay-manifest CLI and comparative historical report.
