# Research Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a usable local evidence workbench for cell-fate prediction and gene-regulatory inference.

**Architecture:** A new standard-library Python package owns an independent SQLite store and portable JSON bundles. Explicit record semantics replace legacy category-based inferences. An offline HTML export lets the user inspect the pilot without starting services.

**Tech Stack:** Python >=3.11, SQLite, argparse, HTML/CSS/JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-research-workbench-design.md`

## Global Constraints

- Python >=3.11; Python standard library only at runtime; pytest for development.
- New code lives in `workbench/`; never import the legacy `atlas/` runtime.
- Existing Atlas code, saved vault files, and Docker data are read-only inputs and must not be modified.
- SQLite workbench databases have an application/schema marker; refuse unrelated existing databases before writing.
- All scientific content is local; no implicit network calls, background workers, paid models, services, or telemetry.
- Categories are multiple annotations and never determine identity, dependency direction, or research priority.
- Import is atomic and idempotent for identical IDs/content; conflicting IDs fail without partial changes.
- Every source-reported/reviewed claim and every reviewed scientific relation has explicit source evidence with a locator.
- Proposed, source-reported, reviewed and withdrawn remain visibly distinct. Reviewed requires a named reviewer and timestamp; imported legacy records remain proposed.
- Dependency traversal uses reviewed, active relations only, reversing `requires` and following `enables`; it reports reachability, not scientific importance. Withdrawn endpoints and relations are excluded.
- HTML must escape all supplied content, reject unsafe URL schemes, work without external assets, and provide accessible search/filter controls.
- A bundled pilot is a small literature-backed demonstration, not comprehensive coverage, expert adjudication, or a clinical recommendation.


Tests use real temporary SQLite databases and filesystem inputs. No runtime dependencies or network calls. Execute in `/Users/kairos/Projects/atlas-workbench` on `feat/research-workbench`. Use `/Users/kairos/Projects/engram/.venv/bin/python` for the available Python 3.13/pytest environment; no dependency installation into the archived project.

## Files and boundaries

- `workbench/store.py` owns persistence and state changes; `workbench/validation.py` owns bundle/type/semantic validation; `workbench/legacy.py` reads old notes; `workbench/__main__.py` owns CLI parsing.
- `workbench/render.py` and `workbench/static/` own the self-contained view. `workbench/data/cell_fate.json` contains source-backed pilot content.
- `tests/workbench/` covers real behavior; `docs/workbench/` records source checks and evaluation; `artifacts/cell-fate-workbench.html` is the reviewable output.
- No legacy `atlas/` implementation changes are needed because its inference machinery is not imported into the new workbench.

### Task 1: Evidence store, state transitions and CLI

**Files:** Create `workbench/__init__.py`, `workbench/store.py`, `workbench/validation.py`, `workbench/legacy.py`, `workbench/__main__.py`, `tests/workbench/test_store.py`, `tests/workbench/test_legacy.py`, `tests/workbench/test_cli.py`, `pyproject.toml` (pytest paths/package metadata only as needed).

**Interfaces:** Produce the complete Store, bundle and CLI interfaces from the spec, except render which is Task 2. Preserve JSON field names exactly. CLI dispatch may import `render` only when the render subcommand is used. Consumes standard library only.

- [x] Write behavioral tests before implementation and record red output. Use this initial identity fixture and extend it with literal source/relation records from the spec:

```python
def test_multi_facet_record_keeps_one_identity(tmp_path):
    bundle = {'schema_version': 1, 'title': 'Test', 'sources': [],
              'items': [{'id': 'q', 'kind': 'question', 'title': 'Cell fate',
                         'summary': 'Predict fate',
                         'facets': {'subject': ['gene regulation'],
                                    'scale': ['molecular', 'cellular']}}],
              'relations': []}
    with Store(tmp_path / 'test.db', create=True) as store:
        store.import_bundle(bundle)
        assert [x['id'] for x in store.search(facets={'scale': 'molecular'})] == ['q']
        assert [x['id'] for x in store.search(facets={'scale': 'cellular'})] == ['q']
        assert len(store.export_bundle()['items']) == 1
```

- [x] Test atomic rejection of bad/dangling evidence, conflicting IDs, unknown fields, invalid endpoint types, blank review fields, unrelated database files, and failed status promotions. Test exact-repeat import, cross-facet normalized duplicate candidates, multi-hop/cyclic dependency direction, unreviewed exclusion, withdrawal/history, and missing-database read commands. Test a malformed vault note rolling back a batch and hash all source bytes before/after.
- [x] Implement validation and real SQLite storage with explicit transaction boundaries. Use parameterized SQL, normalized canonical record JSON for equality, and a schema/application marker. Use `requires` reverse adjacency and `enables` forward adjacency only after active/reviewed filtering. Return records, never numeric funding/importance scores.

```python
# Canonical prerequisite projection after validating active reviewed edges:
src, dst = ((edge['object'], edge['subject'])
            if edge['predicate'] == 'requires'
            else (edge['subject'], edge['object']))
```

- [x] Implement the CLI and read-only legacy adapter. Exercise commands with subprocess against temporary DBs; invalid input must produce nonzero status and leave data unchanged. Use `json.dumps` for stdout and an error handler for user-facing failures.
- [x] Run `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Users/kairos/Projects/engram/.venv/bin/python -m pytest tests/workbench -q -p no:cacheprovider`; fix failures, self-review, commit only Task 1 files, and record test evidence.

### Task 2: Literature-backed pilot, usable HTML view and evaluation

**Files:** Create `workbench/render.py`, `workbench/static/` as needed, `workbench/data/cell_fate.json`, `tests/workbench/test_render.py`, `tests/workbench/test_pilot.py`, `docs/workbench/pilot-sources.md`, `docs/workbench/evaluation.md`, `WORKBENCH.md`, `artifacts/cell-fate-workbench.html`. Modify CLI only for render integration and root README to point to the workbench.

**Interfaces:** Consumes `Store.export_bundle()` and `Store.search()`. Produce `render_bundle(bundle: dict) -> str` and CLI `render --output FILE`. Sources/items/relations follow Task 1 schema. Research notes supplied by the controller are starting evidence, not approval to invent scientific claims.

- [x] Write failing tests exercising rendered data and command behavior: unsafe text/URL handling, source locator visibility, proposed/withdrawn status, no-results/filter controls, atomic output, refusal to overwrite the database or source input, and a full pilot import→export→render round trip. Include a literal malicious string such as `</script><script>alert(1)</script>` to prove it stays data.
- [x] Verify at least six primary publications; write scoped paraphrases with locators and limitations into the pilot. Include the two questions, three approaches, eight claims and two experiments required by the spec. Avoid marking anything expert-reviewed. Keep source-derived prose per publication concise and copyrighted quotations within permitted limits.
- [x] Implement a self-contained accessible HTML page with question-led navigation, search, multi-facet filtering, record details, evidence links, typed relations and history. Escape HTML; embed JSON with `<`, `>` and `&` safely encoded; use DOM textContent for user-controlled strings. Render controls and explicit empty states without external resources.
- [x] Write the quick start and evaluation sheet. Include source coverage limits and the distinction between software validation and future expert/user evaluation. Document JSON editing/import conflicts and review/withdrawal flows.
- [x] Run the complete workbench suite and CLI smoke flow. Generate the pilot artifact in a temporary DB, inspect the page with available browser tools or a headless browser, and verify the source links. Commit only Task 2 files and record test evidence.

## Completion checks

- [x] Task-scoped reviews and one whole-branch review; fix material findings.
- [x] All owned workbench tests pass; legacy offline tests remain at their established baseline when run from the archived checkout without source changes. Concurrent Lighthouse work is outside this delivery review.
- [x] A user can open `artifacts/cell-fate-workbench.html` and follow a scoped claim to a primary source.
- [x] Archived source/vault fingerprints are unchanged; owned changes are committed and concurrent work is preserved.
- [x] Report shipped capabilities, validation, pilot limits and the next human evaluation. Do not claim all six long-term roadmap stages are finished.
