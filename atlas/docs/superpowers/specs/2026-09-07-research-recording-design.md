# Session research recording and Lighthouse refresh

Kairos approved fixing Engram's automatic capture and then connecting automatic
draft recording and view refresh. This implements that first measurable slice.

## Behavior

Local sessions get `atlas_context`, `atlas_record`, `atlas_refresh`, and
`atlas_status` tools plus equivalent CLI commands. A project instruction tells
research sessions to load context, record substantive findings as drafts with
sources and scope, and report the resulting receipt. Ordinary implementation
updates and complete transcripts are not research records. Choosing and
summarizing a finding is agent-driven; storage, deduplication, validation, and
refresh after a record are deterministic.

The configured base is the portable cell-fate pilot. The two existing view
configurations retain their origins, issuers, scopes, and policy windows.
Every new draft explicitly names one or both configured views. New drafts are
always `proposed`, with the actual calling session and capture time attached.
Their optional links use existing Atlas predicates and endpoint validation.
They do not overwrite or promote the pilot's records.

## Durable boundary

`workbench.automation.ResearchInbox(project)` owns `.atlas/` under its configured
project. `record(draft, session_id)` validates a draft, atomically saves an
immutable JSON entry, then refreshes publications. Idempotency is scoped to the
session and the caller's stable `idempotency_key`; same-key different content is
a conflict. The receipt separates `recorded` from `publication_status`, so a
refresh failure cannot cause an uncertain duplicate submission. `refresh()`
can recover publication after a saved record. New sessions can inspect pending
refresh state with `status()`.

Draft fields: required `idempotency_key`, `kind`, `title`, `summary`, `views`;
optional `context`, `facets`, `sources`, `evidence`, `links`. Each link has
`predicate`, `target`, and `rationale`. Source/evidence/context/facet structures
follow workbench v1. Unknown fields, reviewed status, missing evidence sources,
source-ID conflicts, invalid links, unsupported kinds, and unknown views fail
before storage. Draft JSON is bounded to 64 KiB. Missing or blank session IDs fail.

Drafts are the authoritative inbox; a combined portable bundle and publications
are derived outputs. The inbox does not write into another session's database.
It validates against the actual workbench schema, preserves complete evidence
closure, and can be imported into an ordinary Store. Its own state is excluded
from Git. Immutable generation directories are keyed by input content, and an
atomic `current.json` pointer exposes a complete generation. Unchanged refresh
does not create a new version. Publications use the original configured policy
windows without extending them. Context reports evaluate policy at current time.

File locks serialize local writers with a bounded busy error. State directories,
entries, and pointers reject symlinks. Partial refresh leaves the saved draft
and last complete generation available, and status exposes the mismatch.

## Session interface

The MCP server receives a fixed project path at startup. Tool arguments cannot
redirect its store. Session identity comes from Codex `threadId` request metadata
before environment fallback, not from draft content. CLI uses `CODEX_THREAD_ID`
or an explicit operator `--session` argument. MCP is an optional launcher
dependency; workbench recording and CLI remain standard-library Python 3.11+.

Install a separate `atlas_research` MCP entry and a local CLI launcher. Existing
sessions can use the launcher immediately; new/reconnected clients load MCP
tools. Project instructions explain the automatic research workflow and exact
receipt semantics. This slice adds no background model jobs, autonomous peer
messaging, acknowledgement loops, or policy renewal. Those remain separately
measurable extensions.

## Verification

Tests use temporary projects and the actual pilot/configuration format. Verify
durable sourced draft capture, attributed idempotency/conflicts, optional graph
links, refreshed view membership, unchanged refresh identity, failure recovery,
concurrent writes, protected source files, strict validation, and current-time
policy expiry. Exercise the CLI and MCP over real stdio. A combined Store import
and native TypeScript artifact check verify interoperability. A real local Codex
smoke run must find a known research record, save an explicitly labeled test
draft in an isolated project, and observe its new publication receipt.

The independent Engram fix is developed in the Superyak monorepo and installed
into the live hook checkout only after migrated-schema tests pass. No live
database migration or synthetic memory probe is needed.
