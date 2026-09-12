# Explicit Answer Relationships Implementation Plan

> **For agentic workers:** Use the implementation, parallel-dispatch and
> verification skills for the independent slices below. The user explicitly
> approved planning and implementation; no additional approval gate is needed.

**Goal:** Let claims explicitly answer, partially answer and raise questions,
with evidence-bound worker review and readable shared graph notes.

**Architecture:** Extend the current relation vocabulary and graph workers.
Preserve old capture/job formats, and bind new overlap decisions to their exact
predicate and scoped answer. Update human views and neighborhood consumers.

**Tech Stack:** Python 3.11+, existing standard-library/Ollama/MCP/pytest stack.

**Spec:** `docs/superpowers/specs/2026-09-09-answer-relations-design.md`.

## Global constraints

- Preserve the shared dirty checkout; no broad staging, resetting or commits.
- Never edit `.atlas/drafts`, `.atlas/graph-drafts` or publication versions in place.
- Keep all model additions scientifically proposed; do not close questions.
- Keep one question/turn and three overlap links/turn, 12 active agenda slots.
- Retain explicit view membership, grants, five default roles and operator options.
- Use `no_proxy='*'` for Python startup/tests on this Mac.
- Pause the live worker during edits; restore its saved options after validation.

## Task 1: Vocabulary, recorder and publication

Files: `workbench/validation.py`, `workbench/lighthouse.py`,
`workbench/research_graph.py`, `workbench/automation_mcp.py`, focused schema,
Lighthouse and recorder tests.

Interface: export `CLAIM_QUESTION_PREDICATES` and
`EXPLICIT_QUESTION_PREDICATES` from validation. First is informs plus the three
new predicates; second is the three new predicates only. New predicates permit
claim subjects and question objects. Existing APIs retain their signatures.

- [x] Add failing public recorder/publication cases for all three predicates,
  reversed kinds, replay, multiple question targets and unchanged memberships.
- [x] Extend both validators and graph proposal allow-list; preserve legacy
  graph entry normalization and generation hashes for old data.
- [x] Update MCP descriptions and run vocabulary/recording/publication tests.

Representative assertions:
```python
assert saved['record_ids'] == []
assert after['views'] == before['views']
assert {r['predicate'] for r in new_relations} == {'answers', 'partially_answers', 'raises_question'}
assert inbox.record_graph(proposal, session)['duplicate']
```

## Task 2: Explicit worker proposals and fresh review

Files: `workbench/research_graph_model.py`, `research_overlap.py`,
`research_questions.py`, `research_model.py`, model and worker tests.

Bump graph worker revision to `question-overlap-v3`. New overlap links contain
`record_id`, `predicate`, `rationale`, `answer_scope`, `remaining`, `evidence`.
Review decisions contain `record_id`, `predicate`, `verdict`, `reason`, `evidence`.
Validators receive `legacy=False` by default; legacy mode accepts old field sets
and infers the old fixed kind predicate, while still validating IDs/evidence.
`Ollama.overlap(question, packet, *, record_kinds=None)` supplies the separately
bound kind map; `review_overlap` keeps its signature and normalizes old proposals
for a fresh exact-predicate assessment without changing saved candidates.

`_reviewed_relations(candidate, decision, packet, *, premise_predicate='raises_question')`
creates new question motivation links; audit/replay callers explicitly request
`informs` for old question jobs. Question proposal/review schemas remain compatible.

- [x] Write failing full/partial/gap distinction tests and review-predicate mismatch
  rejection; update central GraphModel fixtures with explicit scoped decisions.
- [x] Implement prompts/validation, empty remainder for full answers, nonblank
  remainder for partial answers and question motivation, proper endpoint kinds.
- [x] Classify old generic pairs once per v3 revision, skip duplicate generic
  fallback links, retain pending legacy work and exact prepared capture replay.
- [x] Capture new question premise links as raises_question, with existing
  independent per-link reasons/evidence; run model/worker tests.

## Task 3: Compatibility, context, audits and reuse

Files: `workbench/research_graph_work.py`, `research_graph_audit.py`,
`research_graph_review.py`, `research_evidence.py`, `research_reuse.py`, related tests.

- [x] Bind new `record_kinds` maps in job capture context and under-lock guards;
  leave old packet contents and legacy capture hashes unchanged.
- [x] Audit initial/pending v2 jobs with their old schemas and predicate semantics.
  For new jobs bind the stored edge predicate, scoped answer and review decision.
- [x] Expand question neighbor/reuse queries to all claim-question predicates;
  preserve original source ownership and independent edge exclusions.
- [x] Propagate rejected initial raises_question links to generated questions;
  do not let a later rejected answer invalidate the source finding.
- [x] Verify old receipts/reviews, outages, stale inputs and mixed typed links.

Representative assertions:
```python
assert original_claim_id not in exclusions(project, snapshot)
assert rejected_answer_edge_id in exclusions(project, snapshot)
assert generated_question_id in exclusions(project, rejected_initial_gap_snapshot)
assert question_links(snapshot, claim_id) == {'q-fate', 'q-regulation'}
```

## Task 4: Human views and delivery

Files: `workbench/research_views.py`, browser rendering if needed,
`tests/workbench/test_research_graph_views.py`, operating/recording guides,
`docs/reports/2026-09-09-answer-relations.md` and results JSON.

- [x] Test and render separate answer/partial/motivation groups, reciprocal claim
  links, answer scope/remainder and latest bound assessments with one note/record.
- [x] Review the integrated changes and run full pytest, compileall and diff checks.
- [x] Run a bounded real-Qwen trial on a copy; record outcomes including no-ops.
- [x] Restore live worker settings, verify current publication and human export,
  and record saved IDs or remaining errors in the delivery report.
