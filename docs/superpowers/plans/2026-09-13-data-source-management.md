# Backend data-source management implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Implementation stays in the existing peer-home worktree; the running demo uses an installed package.

**Goal:** Manage private, account-owned input sources and inspect repeatable imports through the peer backend.

**Architecture:** A small SQLite source registry wraps the existing immutable files and selected-record interchange. Sources have names, descriptions, kinds, enabled state, and optimistic versions. Import receipts link existing files or selected records without granting access or publishing them.

**Tech stack:** Existing Python 3.11+, FastAPI and SQLite; standard-library CSV/JSON validation; no new dependencies.

**Spec:** The design and acceptance criteria below define this first backend slice.

## Design and scope

- `file` sources register previously uploaded, owned files; allow bounded UTF-8 CSV and valid JSON uploads alongside existing supported attachment types. Preserve exact bytes; do not extract or interpret medical data.
- `selected-records` sources accept the existing `superyak.selected-sources.v1` document. Preserve original attribution, hashes, revisions, and immutable conflict handling.
- Sources remain owned by one account. Organization administrators receive no extra access. Source enablement controls future imports, not existing content visibility or sharing layers.
- Registration and correction API: `POST/GET /api/data-sources`, `GET/PATCH /api/data-sources/{id}`. Creation accepts `name`, `kind`, optional `description`; patch requires `version` and accepts `name`, `description`, `enabled`.
- Import API: `POST /api/data-sources/{id}/imports` requires `request_id`, source `version`, and either `file_ids` (1–20) or `document`. A repeated successful request returns its original receipt; reusing its ID with different content fails. A paused source rejects new imports. Correcting metadata with an old version fails.
- `GET /api/data-sources/{id}/imports` exposes success/failure receipts without raw failed payloads; `GET /api/data-sources/{id}/items` lists the linked file metadata or selected records. Lists use bounded `limit` and `offset` parameters.
- All item insertion and a successful receipt commit atomically. Failed imports roll back content and save an error receipt only for a source the caller owns. Previously successful retries may be read even after pausing; they perform no import.
- Existing imported records become members of a default selected-record source on upgrade, without changing records or inventing historical import dates. The existing interchange import endpoint uses that default source and keeps its response shape.
- This slice performs no external retrieval, background work, model calls, or peer delivery. URLs inside source records remain inert attribution.

## Global constraints

- Preserve existing `.engram/home-demo` data and credentials and all prior evidence.
- Retain normal session, owner, CSRF, and same-origin boundaries in demo and ordinary modes.
- Do not restart research, model, or MCP services. Reload only the owned demo after verification.
- Include new source/test files in the standalone package inventories; preserve Apache-2.0 scope.

## Task 1: Registry, import transactions, and file formats

**Files:** create `peer/superyak_peer/data_sources.py`, `peer/tests/test_data_sources.py`; modify `peer/superyak_peer/interchange.py`, `source_routes.py`, `files.py`, and `peer/pyproject.toml`.

**Interfaces:** `DataSources(store, interchange)` provides `create`, `list`, `get`, `update`, `import_items`, `import_default`, `history`, and `items`. `Interchange._import_document(db, actor, value)` imports a validated document inside its caller's transaction; the existing public import method retains validation and transaction ownership.

- [x] Write tests exercising actual API requests, including:

```python
source = patient.post('/api/data-sources', json={'name': 'Uploaded reports', 'kind': 'file'}).json()
assert doctor.get('/api/data-sources/' + source['id']).status_code == 404
paused = patient.patch('/api/data-sources/' + source['id'], json={'version': 1, 'enabled': False})
assert paused.json()['version'] == 2
```

- [x] Verify RED with `peer/.venv/bin/python -m pytest peer/tests/test_data_sources.py -q --tb=short` from the worktree.
- [x] Implement schema/ownership/version checks, per-source item links and import receipts. Reuse exact existing file and record storage. Verify conflict in a multi-record import rolls back all of its new records and links; save only a failure receipt afterward.
- [x] Cover same-key retry/conflict, paused-source denial, failed attempt followed by corrected retry, cross-account/admin denial, CSRF, restart/backfill preservation, pagination, CSV/JSON byte preservation, malformed input, and absence of sharing side effects.
- [x] Run the new tests with auth, interchange and layer suites; fix failures before proceeding.

## Task 2: Package, review, integrate

**Files:** update `peer/API.md`, `peer/README.md`, `peer/MODELS_AND_SOURCES.md`, and `HANDOFF.md`.

- [x] Document actual request/response examples and distinguish source import controls from sharing controls.
- [x] Run the complete peer suite, including real browser and package checks, then request focused code review and address required findings.
- [x] Build a fresh standalone archive and installed package. Before and after the owned demo reload, compare existing content tables and credentials; allow only new source-management tables and session changes.
- [x] Verify the live API with a fresh demo session and read-only catalog calls. Preserve the original demo data and prior runtime records.
Integration follows the implementation checks: commit, merge and push under the user's existing authorization. Record the exact final commit, CI outcome and runtime receipts in `.engram/data-sources-20260913/`; that operational receipt is authoritative for integration status.
