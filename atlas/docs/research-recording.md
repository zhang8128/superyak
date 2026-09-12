# Recording research across local sessions

Atlas has a shared local draft inbox and automatic Lighthouse refresh. Sessions
can retrieve context, record a sourced finding, and leave it available to later
sessions. Choosing and summarizing the finding is agent-driven, guided by the
project instructions and MCP tool descriptions. Once the session records it,
validation, deduplication, attribution, and publication refresh are automatic.

## Tools and commands

An explicitly configured Atlas MCP connection exposes these tools. Superyak
setup installs the optional dependency but does not configure a connection:

| Tool | Behavior |
| --- | --- |
| `atlas_context(query, limit)` | Search records and sources, retaining scope and review status. |
| `atlas_record(draft)` | Save a proposed draft and refresh its selected views. |
| `atlas_record_graph(proposal)` | Atomically save one question with its links, or add links between existing records. |
| `atlas_refresh()` | Recover publication or incorporate changed pilot/view configuration. |
| `atlas_status()` | Show saved counts, current generation, errors, and current-time overlap admission. |

From the Superyak root, use `make atlas` after `make atlas-demo`. The default
project is `.engram/atlas/project`; set `ATLAS_PROJECT=/absolute/path/to/project`
to choose another configured project. The MCP server's destination is fixed at
startup and may differ. The environment also contains
`atlas/.venv/bin/atlas-research`; when invoking it directly, pass
`--project /absolute/path/to/project` before the command. Setup does not configure
a global launcher or connect a server.

```sh
make atlas ATLAS_ARGS='context CellRank'
make atlas ATLAS_ARGS='status'
make atlas ATLAS_ARGS='record /absolute/path/to/finding.json --session my-research-session'
make atlas ATLAS_ARGS='refresh'
```

The CLI takes its session identity from `CODEX_THREAD_ID` when `--session` is
omitted. An operator outside Codex must supply `--session` with their actual
local attribution label. MCP prefers the request's
`threadId` over the server's inherited session environment. These are local
provenance identifiers, not authenticated researcher credentials.

## A draft

The JSON below illustrates the format, using a source ID from the pilot. Only
submit it after actually checking that source and deciding the draft is useful;
setup and smoke tests do not add sample findings to the live inbox.

```json
{
  "idempotency_key": "cellrank-outcome-check-1",
  "kind": "question",
  "title": "Which measured outcomes could check the inferred fates?",
  "summary": "Identify an independent outcome measurement before transferring the inferred fate model to another system.",
  "views": ["prediction"],
  "context": {"scope": "A proposed follow-up to the local cell-fate pilot"},
  "evidence": [
    {"source_id": "s-cellrank", "locator": "Abstract", "note": "The inference still needs a scoped outcome check."}
  ]
}
```

Required fields are `idempotency_key`, `kind`, `title`, `summary`, and `views`.
Kinds are `question`, `approach`, `claim`, and `experiment`. Optional `context`
is a string map; `facets` maps axes to lists of strings. `sources` can add new
source records with `id`, `title`, `url`, integer `year`, and `citation`.
Evidence entries require `source_id`, `locator`, and `note`; a cited source must
already be in the base/inbox or supplied with the draft. Reusing a source ID for
different metadata is a conflict.

Optional `links` connect the new draft to an existing record. Each has
`predicate`, `target`, and `rationale`; Atlas's existing endpoint-kind rules
apply. For example, a new claim can `inform` a question using predicate
`informs`. The relation, like the draft, remains `proposed`.

Unknown fields are refused, including `status`, reviewer fields, and a supplied
`session_id`. The server attaches capture provenance. Drafts are bounded to
64 KiB, and the initial inbox supports 1,000 drafts and up to eight views.

## Receipts and recovery

For overlapping question relationships, use `atlas_record_graph` or
`make atlas ATLAS_ARGS='record-graph /absolute/path/to/proposal.json'`.
The proposal requires a stable
`idempotency_key`, `question` (a new question object or `null`), `relations`,
and `expected` digests of every existing endpoint. Optional `context` is a
string map. Each relation contains `subject`, `predicate`, `object`, `rationale`,
and optional `evidence` and `context`. `$question` refers to the question being
created in that atomic batch. Its fields are `title`, `summary`, `views` and
optional `context`, `facets`, `evidence`. Evidence references existing sources.

Compute bindings with `workbench.research_graph.graph_digest(record)` against
the exact current records, not a rendered note. Additional bindings can protect
consulted sources. The recorder rejects changed inputs, duplicate existing
edges and parent cycles. Existing-only batches allow at most three relations;
a new question allows eight. The recorder owns all IDs and proposed status.
This separate journal does not modify a finding's original source account.

Claim-to-question predicates are `informs`, `answers`, `partially_answers` and
`raises_question`. Answers remain claims, so one claim can answer several
questions and several claims can offer competing answers to one question.
Use `answers` only for a direct response covering the question's explicit
scope, `partially_answers` for a bounded response with a named remainder,
and `raises_question` for a specific gap or tension. Put scope and the remaining
issue in the relation's `context` (`answer_scope`, `remaining`) and explain the
connection in `rationale`, with located evidence. The automated overlap worker
requires those scope fields and a separate exact-predicate review. Manual
recording retains its existing schema; recording alone is not review.
Existing `supports`/`challenges` claim links and `part_of` question links compose
with these relationships. All new records and links remain proposed.

Graph receipts use `graph_draft_id`, `record_ids` and `relation_ids`, alongside
the same `recorded`, `duplicate` and publication fields. New question membership
uses explicitly selected views; connecting two existing records does not extend
either record's publication membership. Graph capture belongs in
`.atlas/graph-drafts/`, which is immutable like the original draft journal.

Successful recording returns `recorded: true`, `record_id`, `session_id`,
`duplicate`, selected `views`, `publication_status`, and a generation identifier.
Keep the idempotency key stable across retries of the same finding. Same
session/key/content returns its existing record; different content under the
same key fails. Different sessions retain their separate accounts.

If refresh fails after capture, the receipt still says `recorded: true` and
`publication_status: pending`, with the error and recovery instruction. The
draft is saved. Run `refresh`, then check status. The CLI returns exit code 2
for this saved-but-pending result, 1 for an input/operational error, and 0 for
success. MCP returns the saved receipt as a normal result so the partial success
is explicit. A busy writer error occurs before that call submits a record;
retry later using the same key.

`status` distinguishes `current`, `pending`, and `invalid` publications. It
evaluates overlap admission at the current time. Refresh never renews grants;
the pilot's original example grant still expires on 2026-10-07. A corrupt or
missing immutable generation produces a visible error and retains the draft
journal; it is not silently overwritten.

## Files and scope

The configuration is
[`lighthouse-automation.json`](../workbench/data/lighthouse-automation.json).
It selects the checked-in base bundle and the existing prediction/regulation
view configs. New records join only the views explicitly named in their draft.

`.atlas/drafts/` contains immutable attributed entries. Complete derived
generations live in `.atlas/publications/`; `.atlas/current.json` identifies the
last complete generation. Each generation includes a portable `bundle.json`,
each Lighthouse publication, both directional overlap reports, and a manifest.
`status` returns their paths. The combined bundle can be imported into a new
ordinary workbench database for rendering or further assessment. The original
pilot, saved demonstration artifacts, existing databases, and browser are not
modified by recording. Local inbox state is excluded from Git.

All stored research retains its epistemic status. Recording creates proposed
drafts, not scientific validation. The first version has no background model
job, transcript scraping, automatic peer notifications, or policy renewal.
Native session messaging remains available separately for authorized questions.
