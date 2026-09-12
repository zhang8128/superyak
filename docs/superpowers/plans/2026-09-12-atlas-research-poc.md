# Atlas research POC Implementation Plan

> **For agentic workers:** Use the existing delegated Atlas bridge and context-profile tasks; the controller implements and verifies the experiment. Do not change the active Atlas checkout.

**Goal:** Run and inspect genuine public-source research with separate individual and explicitly shared Engram memory before Stampede access.

**Architecture:** Snapshot the current Atlas workbench's public implementation and pilot data into an isolated run. Atlas supplies document normalization, source-grounded extraction/review, attributed proposed drafts and browser/Obsidian exports. Superyak supplies durable individual stores, explicit audience-bound sharing and four crossed memory conditions. A fifth isolated community retains its identities across rounds.

**Tech Stack:** Python 3.13, existing Engram SQLite/sharing, Atlas workbench, Europe PMC, the already loaded local Qwen model.

**Spec:** User-approved local research/Intel separation; this document defines the bounded first experiment.

## Constraints and experiment

- Preserve all existing uncommitted Superyak and Atlas work; use the isolated worktree.
- Never use or alter Atlas's existing research journal. Snapshot only workbench Python, public JSON data and the three required static browser assets, with hashes and dirty revision metadata.
- Two logical researchers, two rounds, two fixed primary papers about measured cell state and cell fate. Swap document assignments in round two. Same question, prompt, model and source cache across conditions.
- Cross individual memory off/on with shared memory off/on. Keep the continuing community outside the four-cell comparison. Freeze memory inputs at each round boundary; exclude an author's own shared entries from that author's shared recall.
- Private notes stay in their owner's Engram store. Only explicit model publication choices passing a separate source-only review can enter the cell's published Engram store and isolated Atlas journal. All outputs remain available to the operator in the local audit.
- Cap local model concurrency at two; no downloads or paid provisioning. Record actual calls, errors, context admission, timing and model-reported token counts. Do not infer capacity or research benefit from this small run.
- Checkpoint each returned model call before applying memory/publication. Stable IDs repair interrupted application without duplicate findings. An interrupted remote call cannot promise exactly once execution; require an explicit retry flag and retain its attempt record.
- Repeat a completed run with zero new model calls. Permit explicit extension of only the continuing community.

## Task 1: Real Atlas bridge (delegated)

Files: research_poc/atlas_bridge.py; engram/tests/test_atlas_poc_bridge.py.

Interfaces: prepare_atlas(source, run) returns question, frozen code, seed project and manifest; fetch_documents(run, limit=2) returns paper/document pairs; fork_project(seed,destination); AtlasModel.check/generate/review; record_finding(project, question, paper, document, extraction, review, session_id, idempotency_key).

- [x] Test source snapshot isolation, hash checks, source retrieval/coverage, extraction validation, source-only review, publication and idempotency using real Atlas and mocked HTTP only.
- [x] Implement and pass those tests.

## Task 2: Durable memory experiment (controller)

Files: research_poc/experiment.py, research_poc/__main__.py, research_poc/__init__.py; engram/tests/test_research_poc.py; Makefile; docs/atlas-research-poc.md.

- [x] Write failing tests for all four memory exposures, explicit publication and unsupported rejection, interruption recovery, completed resume and community isolation.
- [x] Implement round barriers, individual/shared Engram stores, durable model response files, Atlas recording, bounded concurrent cells, and readable result report.
- [x] Run tests with actual SQLite/sharing and deterministic model/source boundaries.

## Task 3: Live verification and handoff

- [x] Run the same executable with Europe PMC and local Qwen; inspect source attribution, actual admitted context, drafts and browser/Obsidian outputs.
- [x] Repeat the completed run and verify zero additional requests and unchanged finding counts.
- [x] Review integration and run appropriate regressions; resolve substantive findings.
- [x] Publish local documentation with measured results and limitations; integrate committed changes without disturbing existing work. Preserve raw run artifacts under ignored .engram/research-poc.
