# Question and Overlap Implementation Plan

> **For agentic workers:** Execute the approved slices with the implementation,
> parallel-agent, and verification skills. Preserve all other sessions' changes.

**Goal:** Let the default Qwen rotation generate grounded questions and connect
existing evidence to several questions, with durable capture and fair scheduling.

**Architecture:** Extend the immutable inbox with atomic graph proposals.
Separate original evidence binding from subsequent relation assessments. Add
question and overlap workers, reusing attributed source packets and the existing
single-process rotation.

**Tech Stack:** Python 3.11+, standard library, existing Ollama/MCP/pytest support.

**Spec:** `docs/superpowers/specs/2026-09-09-question-overlap-design.md` (approved).

## Global constraints

- Do not edit immutable live drafts/publications or broadly stage/reset the checkout.
- Existing version-one drafts and receipts remain compatible.
- All generated questions and relationships remain scientifically `proposed`.
- One new question and at most three overlap links per turn; 12 active questions
  initially, including two pinned seed questions; configurable agenda limits.
- No automatic publication-scope expansion; selected views stay explicit.
- Use `no_proxy='*'` for macOS test subprocesses (documented urllib/fork issue).
- Preserve personal Obsidian annotations and stable readable filenames.
- Restore the live worker with the new defaults after copied-graph verification.

## 1. Atomic graph proposals

Files: `workbench/research_graph.py`, `workbench/automation.py`,
`workbench/automation_mcp.py`, `tests/workbench/test_research_graph.py`.

Public interface: `ResearchInbox.record_graph(proposal, session_id, *, guard=None)`;
`graph_digest(value)` in `research_graph.py` for input binding. The optional
worker guard receives the current snapshot under the inbox lock and raises on
lost eligibility. It is not persisted or exposed through CLI/MCP input.

Proposal shape:

```python
{
    "idempotency_key": "stable-job-key",
    "question": None,  # or title, summary, context, facets, evidence, views
    "relations": [{"subject": "existing-claim", "predicate": "informs",
                   "object": "existing-question", "rationale": "Located reason",
                   "context": {}, "evidence": []}],
    "expected": {"existing-claim": graph_digest(claim),
                 "existing-question": graph_digest(question)},
    "context": {"worker_role": "overlap"},
}
```

`$question` references the new question in the same batch. The recorder assigns
all IDs and provenance. Receipts expose `recorded`, `duplicate`,
`graph_draft_id`, `record_ids`, `relation_ids`, `publication_status`, and views.

- [x] Write failing public-interface tests for existing-item links, multiple
  parents, atomic question/links, retry, stale inputs, invalid/reversed links,
  cycle rejection, duplicate edges, source attribution, and publication failure.
- [x] Add versioned `.atlas/graph-drafts` entries and deterministic composition.
  Keep original `.atlas/drafts` entries untouched. Enforce bounded journal size.
- [x] Add CLI `record-graph` and MCP `atlas_record_graph`, preserving attribution.
- [x] Run graph and automation tests; verify old snapshots and receipts.

## 2. Evidence and review compatibility

Files: `workbench/research_evidence.py`, `workbench/research_review.py`,
`workbench/research_connections.py`, their focused tests.

Public interface: `eligible_inputs(research, snapshot)` returns a mapping of
record ID to `{record, document, anchors, question_id, source}` as today;
`make_packet(inputs)` returns `{records, sources, document}` with attributed
whole required passages for one or more inputs. Connector wrappers remain
compatible. `question_links(snapshot, record_id)` returns eligible current
question IDs, with original job question retained only as provenance.

- [x] Write regressions proving additional links do not break an original audit,
  while mutations/removal of original relation IDs still fail binding.
- [x] Validate original relations by their exact recorded IDs and full content.
- [x] Extract reusable evidence packets without relaxing source binding.
- [x] Permit bounded cross-question connector pairs; preserve current-job review.
- [x] Run review/connection tests, including negative-premise propagation.

## 3. Overlap worker and graph assessments

Files: `workbench/research_overlap.py`, `workbench/research_graph_review.py`,
`workbench/research_model.py`, `tests/workbench/test_research_overlap.py`.

Public interface: `OverlapWorker(research).cycle()`. Graph workers use the
existing `research` object (`inbox`, `root`, `model`, `session_id`, `progress`,
`should_stop`) and return the rotation's existing result fields plus link counts.

- [x] Add durable candidate/job selection and a cursor over old/new pairs.
- [x] Add fresh propose/review model calls with exact supplied IDs and passages.
- [x] Record justified links via `record_graph`, with locked eligibility recheck.
- [x] Preserve held/no-op/retry jobs; separately assess later graph relations.
- [x] Verify shared findings, independent link rejection, malformed model output,
  stale input rejection, unchanged-pair suppression, and restart recovery.

## 4. Question worker and agenda

Files: `workbench/research_questions.py`, `workbench/research_agenda.py`,
`workbench/research_model.py`, `tests/workbench/test_research_questions.py`,
`tests/workbench/test_research_agenda.py`.

Public interfaces: `QuestionWorker(research).cycle()`;
`QuestionAgenda(project).eligible(snapshot, question_ids=None)`;
`QuestionAgenda(project).researched(question_id)`;
`QuestionAgenda(project).overlapped(question_id)`;
`QuestionAgenda(project).status(snapshot)`.

- [x] Generate at most one evidence-grounded question with explicit scope,
  motivation, answer-advancing observation, existing-question comparison,
  selected views, parent IDs, and evidence-record IDs.
- [x] Review usefulness and distinctness separately from scientific truth.
- [x] Capture question plus initial incoming evidence and outgoing parent links.
- [x] Keep seeds pinned, rotate other slots fairly, mark overlap attempts and
  research turns, and suspend unsupported premises without changing stored status.
- [x] Test duplicate paraphrases, multi-parent questions, no-op outcomes, bounded
  activation, fair scheduling/restart, and no recursive generation before research.

## 5. Default rotation, integration, human views

Files: `workbench/research_workers.py`, `workbench/research_service.py`,
`workbench/research_runner.py`, `workbench/research_monitor.py`,
`workbench/research_views.py`, related tests and guides.

- [x] Default to research/audit/question/overlap/connect; preserve explicit overrides.
- [x] Apply agenda to research scheduling and expose states/role metrics.
- [x] Reuse existing scoped assertions across publication/question jobs when
  identity is established; attach a link instead of duplicating the assertion.
- [x] Render all related questions and their reasons, parents/subquestions,
  and agenda status without duplicating Obsidian notes.
- [x] Run full tests and review changed code against the approved spec.
- [x] Run bounded real-Qwen question/overlap trials on a copied live graph,
  inspect outputs, record receipts/results, then refresh/restart the live worker.

## Verification record

Baseline and delivery commands/results are recorded as work completes. Only
completed, verified slices are checked off; no implementation success is inferred
from a proposed design or model-generated output.


Delivery verification: `no_proxy='*' python -m pytest -q` — **626 passed**
in 197.86 seconds. `git diff --check` and `python -m compileall -q workbench`
passed. Three bounded code reviews covered atomic capture, evidence integrity,
scheduling, replay, and human views. See the delivery report for real-Qwen and
live-worker results.
