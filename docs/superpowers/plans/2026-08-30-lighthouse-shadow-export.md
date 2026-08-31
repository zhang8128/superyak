# Lighthouse Historical Shadow Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Engram exporter that turns work-lane memories and eligible historical recall logs into Lighthouse's opaque portable recall-trace profile.

**Architecture:** A standalone flat Python module opens SQLite directly with URI `mode=ro` and `PRAGMA query_only=ON`; it never imports Engram `Storage` or server code. Pure projection helpers build a deterministic document plus aggregate audit counts, and a thin CLI writes a new file exclusively. Lighthouse remains the normative validator, so final acceptance includes projecting a temporary real export through the existing adapter.

**Tech Stack:** Python 3.12+, standard-library `sqlite3`, `hashlib`, `json`, `argparse`, `dataclasses`, `pathlib`; pytest 9; Lighthouse TypeScript adapter for cross-repository validation.

**Spec:** `docs/superpowers/specs/2026-08-30-lighthouse-shadow-export-design.md`

## Global Constraints

- Export only literal `lane = "work"` episodes and semantics; exclude instincts and every personal or mixed-lane trace.
- Emit no raw memory content, query text, session ID, outcome, timestamp, score, margin, source label, or personal-memory identifier.
- Use SQLite URI `mode=ro`, `PRAGMA query_only=ON`, a deferred read transaction, and explicit `SELECT` statements only.
- Do not import `storage.py`, `server.py`, `sqlite-vec`, embeddings, or any MCP runtime.
- Recompute SHA-256 over source text and require equality with stored `content_hash` before discarding the text.
- Drop an entire trace if any candidate is outside the exported work set; never compact a mixed trace into a misleading work-only ranking.
- Output exactly portable format version `1.0` rooted at context `memory/technical` with compact sorted-key JSON and one final newline.
- The CLI must refuse to overwrite an existing output path and must emit only aggregate counts or stable error codes.
- Do not change recall behavior, access counts, migrations, live logging, personal memory, or any Hyper repository.

---

### Task 1: Read-only schema and work-memory projection

**Files:**
- Create: `lighthouse_export.py`
- Create: `tests/test_lighthouse_export.py`

**Interfaces:**
- Consumes: a path to a migrated Engram SQLite database and a non-empty instance name.
- Produces: `ExportError`, immutable `ExportAudit`, and `export_lighthouse_shadow(database: Path, *, instance: str) -> tuple[dict[str, object], ExportAudit]`.
- Later tasks extend the document's initially empty `edges` and `recallTraces` arrays without changing this public signature.

- [ ] **Step 1: Write the minimal SQLite fixture and failing work-memory test**

Create `tests/test_lighthouse_export.py` with a local schema builder that does not import `Storage`:

```python
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from lighthouse_export import ExportError, export_lighthouse_shadow


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE episodes (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT,
            lane TEXT NOT NULL
        );
        CREATE TABLE semantics (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT,
            lane TEXT NOT NULL
        );
        CREATE TABLE semantic_sources (
            semantic_id TEXT NOT NULL,
            episode_id TEXT NOT NULL
        );
        CREATE TABLE memory_log (
            event_type TEXT NOT NULL,
            target_ids JSON,
            context JSON
        );
        """
    )
    return connection


def add_memory(
    connection: sqlite3.Connection,
    table: str,
    memory_id: str,
    content: str,
    lane: str,
) -> None:
    assert table in {"episodes", "semantics"}
    connection.execute(
        f"INSERT INTO {table} (id, content, content_hash, lane) VALUES (?, ?, ?, ?)",
        (memory_id, content, digest(content), lane),
    )


def test_exports_only_opaque_work_memories_without_mutating_source(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work-episode", "private technical text", "work")
    add_memory(connection, "episodes", "personal-episode", "private relationship text", "personal")
    add_memory(connection, "semantics", "work-semantic", "private distilled fact", "work")
    connection.commit()
    connection.close()
    before = database.read_bytes()

    document, audit = export_lighthouse_shadow(database, instance="engram-test")

    assert document["formatVersion"] == "1.0"
    assert document["instance"] == "engram-test"
    assert document["context"] == {
        "id": "memory/technical",
        "path": ["memory", "technical"],
    }
    assert [memory["id"] for memory in document["memories"]] == [
        "work-episode",
        "work-semantic",
    ]
    assert document["memories"][0] == {
        "id": "work-episode",
        "layer": "episode",
        "contentDigest": {"algorithm": "sha256", "value": digest("private technical text")},
        "contextPath": ["memory", "technical"],
        "lane": "work",
        "origin": "lived",
    }
    serialized = json.dumps(document)
    assert "private technical text" not in serialized
    assert "private relationship text" not in serialized
    assert audit.work_episodes == 1
    assert audit.work_semantics == 1
    assert database.read_bytes() == before
```

- [ ] **Step 2: Run the focused test and confirm the module is absent**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py::test_exports_only_opaque_work_memories_without_mutating_source -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'lighthouse_export'`.

- [ ] **Step 3: Implement strict read-only opening, schema preflight, audit type, and memory projection**

Create `lighthouse_export.py` with these public types and stable error shape:

```python
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO


TECHNICAL_CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
REQUIRED_SCHEMA = {
    "episodes": {"id", "content", "content_hash", "lane"},
    "semantics": {"id", "content", "content_hash", "lane"},
    "semantic_sources": {"semantic_id", "episode_id"},
    "memory_log": {"event_type", "target_ids", "context"},
}


class ExportError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExportAudit:
    work_episodes: int
    work_semantics: int
    provenance_edges: int
    omitted_provenance_edges: int
    eligible_traces: int
    excluded_empty: int
    excluded_malformed: int
    excluded_duplicate_candidates: int
    excluded_outside_work_set: int
```

Implement `_open_readonly(database)` with `database.resolve().as_uri() + "?mode=ro"`, `uri=True`, `row_factory=sqlite3.Row`, `PRAGMA query_only=ON`, and `BEGIN`. Reject a missing/non-file path as `DATABASE_NOT_FOUND`. Implement `_preflight` by reading `PRAGMA table_info` only for constant names in `REQUIRED_SCHEMA`, raising `MISSING_TABLE` or `MISSING_COLUMN` without including source values.

Implement `_content_digest(content, stored)` to require strings, recompute UTF-8 SHA-256, and raise `CONTENT_HASH_MISMATCH` unless it equals the stored lowercase 64-hex value. Implement work-memory row projection for episodes (`lived`) and semantics (`organic`), reject cross-table ID collisions as `DUPLICATE_MEMORY_ID`, sort by ID, initialize empty edges/traces, assert `connection.total_changes == 0`, roll back the read transaction, and close in `finally`.

- [ ] **Step 4: Add failing schema/hash cases before broadening behavior**

Append tests that assert:

```python
def test_rejects_missing_schema_and_hash_mismatch(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    sqlite3.connect(missing).close()
    with pytest.raises(ExportError, match="MISSING_TABLE"):
        export_lighthouse_shadow(missing, instance="test")

    database = tmp_path / "hash.db"
    connection = build_database(database)
    connection.execute(
        "INSERT INTO episodes VALUES (?, ?, ?, ?)",
        ("work", "source text", "0" * 64, "work"),
    )
    connection.commit()
    connection.close()
    with pytest.raises(ExportError, match="CONTENT_HASH_MISMATCH"):
        export_lighthouse_shadow(database, instance="test")


@pytest.mark.parametrize("instance", ["", "   "])
def test_rejects_blank_instance(tmp_path: Path, instance: str) -> None:
    database = tmp_path / "graph.db"
    build_database(database).close()
    with pytest.raises(ExportError, match="INVALID_INSTANCE"):
        export_lighthouse_shadow(database, instance=instance)
```

- [ ] **Step 5: Run the task tests and commit the core projection**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q`

Expected: all Task 1 tests pass.

Commit:

```bash
git add lighthouse_export.py tests/test_lighthouse_export.py
git commit -m "feat: export opaque work memories read-only"
```

### Task 2: Provenance, historical traces, and deterministic exclusion

**Files:**
- Modify: `lighthouse_export.py`
- Modify: `tests/test_lighthouse_export.py`

**Interfaces:**
- Consumes: the Task 1 work-memory map and the same read-only SQLite transaction.
- Produces: portable provenance edges, eligible ranked recall traces, and complete immutable `ExportAudit` counts through the existing public function.

- [ ] **Step 1: Write failing provenance and honest whole-trace filtering tests**

Add helpers and a test:

```python
def add_recall(connection: sqlite3.Connection, recall_id: str, query: str, ids: list[str]) -> None:
    connection.execute(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        ("recall", json.dumps(ids), json.dumps({
            "recall_id": recall_id,
            "query": query,
            "session_id": "must-not-export",
            "margin": {"must": "not export"},
        })),
    )


def test_exports_provenance_and_only_complete_work_traces(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work-episode", "work text", "work")
    add_memory(connection, "episodes", "personal-episode", "personal text", "personal")
    add_memory(connection, "semantics", "work-semantic", "fact text", "work")
    connection.executemany(
        "INSERT INTO semantic_sources VALUES (?, ?)",
        [("work-semantic", "work-episode"), ("work-semantic", "personal-episode")],
    )
    add_recall(connection, "eligible", "technical query", ["work-semantic", "work-episode"])
    add_recall(connection, "mixed", "private query", ["work-episode", "personal-episode"])
    add_recall(connection, "unknown", "unknown query", ["work-episode", "missing"])
    connection.commit()
    connection.close()

    document, audit = export_lighthouse_shadow(database, instance="test")

    assert document["edges"] == [{
        "source": "work-episode",
        "target": "work-semantic",
        "type": "provenance",
        "weight": 1.0,
        "directed": True,
    }]
    assert document["recallTraces"] == [{
        "turnId": "eligible",
        "queryDigest": {"algorithm": "sha256", "value": digest("technical query")},
        "contextPath": ["memory", "technical"],
        "candidates": [
            {"memoryId": "work-semantic", "rank": 1},
            {"memoryId": "work-episode", "rank": 2},
        ],
    }]
    serialized = json.dumps(document)
    for forbidden in ("technical query", "private query", "personal-episode", "must-not-export"):
        assert forbidden not in serialized
    assert audit.provenance_edges == 1
    assert audit.omitted_provenance_edges == 1
    assert audit.eligible_traces == 1
    assert audit.excluded_outside_work_set == 2
```

- [ ] **Step 2: Run the new test and verify the empty arrays fail expectations**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py::test_exports_provenance_and_only_complete_work_traces -q`

Expected: FAIL because `edges` and `recallTraces` are still empty.

- [ ] **Step 3: Implement provenance and trace classification**

Add `_project_edges(connection, memory_ids)` that selects all semantic provenance rows, emits an edge only when both IDs are in `memory_ids`, counts omissions, and sorts with a compact sorted-key JSON key.

Add `_project_traces(connection, memory_ids)` that selects only recall rows, parses JSON with `json.loads`, and classifies each row in this order:

1. non-object context, blank/missing `recall_id` or query, non-array targets, or non-string target → `excluded_malformed`;
2. empty targets → `excluded_empty`;
3. repeated target ID → `excluded_duplicate_candidates`;
4. any target outside `memory_ids` → `excluded_outside_work_set`;
5. otherwise emit the trace and increment `eligible_traces`.

Track every well-formed non-empty recall ID before scope filtering. A repeated recall ID raises `DUPLICATE_RECALL_TRACE`. Compute the query digest before discarding the query, preserve candidate order, number ranks from one, and sort emitted traces by `turnId`.

- [ ] **Step 4: Add malformed, duplicate-candidate, duplicate-turn, and insertion-order tests**

Add tests with no raw-value assertions in error messages:

```python
def test_classifies_malformed_empty_and_duplicate_candidate_logs(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work", "work text", "work")
    connection.executemany(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        [
            ("recall", "not-json", "not-json"),
            ("recall", "[]", json.dumps({"recall_id": "empty", "query": "q"})),
            ("recall", json.dumps(["work", "work"]), json.dumps({"recall_id": "dupe", "query": "q"})),
        ],
    )
    connection.commit()
    connection.close()

    _, audit = export_lighthouse_shadow(database, instance="test")
    assert audit.excluded_malformed == 1
    assert audit.excluded_empty == 1
    assert audit.excluded_duplicate_candidates == 1


def test_rejects_duplicate_recall_identity(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    add_memory(connection, "episodes", "work", "work text", "work")
    add_recall(connection, "same", "first secret", ["work"])
    add_recall(connection, "same", "second secret", ["work"])
    connection.commit()
    connection.close()
    with pytest.raises(ExportError, match="DUPLICATE_RECALL_TRACE"):
        export_lighthouse_shadow(database, instance="test")
```

For determinism, build two databases with the same logical memories, edges,
and logs inserted in reverse order and assert `document_one == document_two`
and `audit_one == audit_two`.

- [ ] **Step 5: Run all exporter tests and commit historical trace projection**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q`

Expected: all Task 1-2 tests pass.

Commit:

```bash
git add lighthouse_export.py tests/test_lighthouse_export.py
git commit -m "feat: export historical work recall traces"
```

### Task 3: Exclusive CLI, privacy-safe diagnostics, and packaging

**Files:**
- Modify: `lighthouse_export.py`
- Modify: `tests/test_lighthouse_export.py`
- Modify: `pyproject.toml` in the isolated worktree only; add `"lighthouse_export"` to `tool.setuptools.py-modules` without changing dependency declarations.

**Interfaces:**
- Consumes: `export_lighthouse_shadow` and `ExportAudit` from Tasks 1-2.
- Produces: `write_lighthouse_shadow(output: Path, document: dict[str, object]) -> None` and `main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int`.

- [ ] **Step 1: Write failing CLI success, overwrite, and non-leakage tests**

Add:

```python
from io import StringIO

from lighthouse_export import main


def test_cli_writes_canonical_export_and_safe_audit(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    connection = build_database(database)
    memory_id = "00000000-0000-4000-8000-000000000001"
    recall_id = "00000000-0000-4000-8000-000000000002"
    add_memory(connection, "episodes", memory_id, "raw memory secret", "work")
    add_recall(connection, recall_id, "raw query secret", [memory_id])
    connection.commit()
    connection.close()
    output = tmp_path / "local.engram.json"
    stdout, stderr = StringIO(), StringIO()

    code = main(
        ["--db", str(database), "--instance", "engram-test", "--output", str(output)],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stdout.getvalue() == ""
    written = output.read_text(encoding="utf-8")
    assert written.endswith("\n") and not written.endswith("\n\n")
    assert written == json.dumps(json.loads(written), ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n"
    diagnostics = json.loads(stderr.getvalue())
    assert diagnostics["ok"] is True
    assert diagnostics["audit"]["eligible_traces"] == 1
    assert "raw memory secret" not in written
    assert "raw query secret" not in written
    for secret in ("raw memory secret", "raw query secret", memory_id, recall_id):
        assert secret not in stdout.getvalue() + stderr.getvalue()


def test_cli_refuses_overwrite_without_changing_existing_file(tmp_path: Path) -> None:
    database = tmp_path / "graph.db"
    build_database(database).close()
    output = tmp_path / "existing.engram.json"
    output.write_text("keep-me", encoding="utf-8")
    stderr = StringIO()
    code = main(
        ["--db", str(database), "--instance", "test", "--output", str(output)],
        stdout=StringIO(),
        stderr=stderr,
    )
    assert code == 1
    assert output.read_text(encoding="utf-8") == "keep-me"
    assert json.loads(stderr.getvalue()) == {"ok": False, "code": "OUTPUT_EXISTS"}
```

Use an opaque memory ID such as a UUID in the success test if checking that
diagnostics do not contain IDs; the portable output itself necessarily contains
exported work IDs.

- [ ] **Step 2: Run the CLI tests and verify `main` is absent**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q`

Expected: collection fails because `main` is not exported.

- [ ] **Step 3: Implement exclusive canonical writing and injectable CLI streams**

Implement `write_lighthouse_shadow` with `output.open("x", encoding="utf-8")` and compact `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"`. If writing fails after creation, unlink only that newly created output and re-raise. Map `FileExistsError` to `ExportError("OUTPUT_EXISTS")`.

Implement `main` with required `--db`, `--instance`, and `--output` arguments. On success, emit exactly one compact sorted-key JSON audit object to stderr and nothing to stdout:

```json
{"audit":{"eligible_traces":1,"excluded_duplicate_candidates":0,"excluded_empty":0,"excluded_malformed":0,"excluded_outside_work_set":0,"omitted_provenance_edges":0,"provenance_edges":0,"work_episodes":1,"work_semantics":0},"ok":true}
```

On any expected export/filesystem error, emit only the corresponding stable
code, for example `{"code":"DATABASE_NOT_FOUND","ok":false}`. Do not include
exception text, paths, source values, or trace IDs. Add the standard
`if __name__ == "__main__": raise SystemExit(main())` entrypoint.

- [ ] **Step 4: Add the module to packaging without absorbing unrelated work**

In the isolated worktree, add exactly this entry to `tool.setuptools.py-modules`:

```toml
    "lighthouse_export",
```

Place it alphabetically after `knowledge`. Do not add dependencies or console
scripts. The supported invocation remains `python -m lighthouse_export`.

- [ ] **Step 5: Run exporter tests, package build checks, and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_lighthouse_export.py -q
.venv/bin/python -m build --wheel --outdir /tmp/engram-lighthouse-wheel
```

If `build` is not installed, replace the second command with:

```bash
.venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /tmp/engram-lighthouse-wheel .
```

Inspect the wheel with `unzip -l` and require `lighthouse_export.py` to appear.

Commit:

```bash
git add lighthouse_export.py tests/test_lighthouse_export.py pyproject.toml
git commit -m "feat: add privacy-safe shadow export CLI"
```

### Task 4: Real-data interoperability validation and handoff

**Files:**
- Modify only if verification uncovers a defect: `lighthouse_export.py`, `tests/test_lighthouse_export.py`, or `docs/superpowers/specs/2026-08-30-lighthouse-shadow-export-design.md`.
- Do not add the real export, its IDs, or its digests to the Engram repository.

**Interfaces:**
- Consumes: the packaged CLI from Task 3, Engram's local `.engram/graph.db`, and Lighthouse's existing `engramAdapter.project`.
- Produces: ephemeral aggregate counts and one sealed Lighthouse snapshot digest; no retained corpus.

- [ ] **Step 1: Run the complete focused and repository verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_lighthouse_export.py -q
.venv/bin/python -m pytest -q
git diff --check main...HEAD
```

Expected: exporter tests and the full existing suite pass; the feature diff has no whitespace errors. If unrelated pre-existing tests fail, record their exact baseline status and prove no new failures with a base-commit worktree before proceeding.

- [ ] **Step 2: Create one temporary real export**

Create a fresh directory, retain its exact returned path in a task-specific
variable, and run from the Engram feature worktree:

```bash
ENGRAM_SHADOW_TMP="$(mktemp -d /tmp/engram-shadow-export.XXXXXX)"
.venv/bin/python -m lighthouse_export \
  --db /Users/kairos/Projects/engram/.engram/graph.db \
  --instance engram-local \
  --output "$ENGRAM_SHADOW_TMP/local.engram.json"
```

Expected stderr: `ok: true`, 15 work memories, 12 eligible traces, and no source values. Counts may legitimately increase if new work memories or recalls are recorded during implementation; treat the observed counts as measurements, not fixed test constants.

- [ ] **Step 3: Project the temporary export through Lighthouse**

From `/Users/kairos/Projects/lighthouse`, run:

```bash
node --input-type=module --eval '
import { engramAdapter } from "./adapters/engram/dist/index.js";
const snapshot = await engramAdapter.project({
  root: process.argv[1],
  id: "urn:snapshot:engram-historical-shadow",
  issuer: "urn:lighthouse:engram-local",
  issuedAt: "2026-08-30T12:00:00Z",
});
const model = snapshot.payload.model;
process.stdout.write(JSON.stringify({
  digest: snapshot.digest.value,
  memories: model.memories.length,
  edges: model.edges.length,
  traces: model.recallTraces.length,
}) + "\n");
' "$ENGRAM_SHADOW_TMP/local.engram.json"
```

Expected: exit 0, one digest, and counts only. Do not print the snapshot model.

- [ ] **Step 4: Remove the temporary export and confirm source boundaries**

After validation, first require the recorded path to match the dedicated temp
prefix, then remove only that directory and confirm it no longer exists:

```bash
case "$ENGRAM_SHADOW_TMP" in
  /tmp/engram-shadow-export.*) ;;
  *) exit 1 ;;
esac
rm -R -- "$ENGRAM_SHADOW_TMP"
test ! -e "$ENGRAM_SHADOW_TMP"
git -C /Users/kairos/Projects/engram status --short
git -C /Users/kairos/Projects/lighthouse status --short --branch
```

Expected: the original Engram worktree retains exactly its pre-existing user
changes plus integrated exporter commits and Lighthouse remains clean. Confirm
from the executed command set that every write target was confined to Engram,
Lighthouse, or the exact temporary directory; no Hyper path is an allowed write
target. Report that the temporary export was deleted and was not retained.

- [ ] **Step 5: Request independent standards and spec review**

Review the pinned feature diff on two axes:

- Standards: read-only SQLite enforcement, strict errors, privacy-safe CLI,
  deterministic serialization, packaging, and test quality.
- Spec: every source/output field, whole-trace filtering, aggregate audit,
  non-mutation, evidence boundary, and successful Lighthouse projection.

Fix every Critical and Important finding test-first, rerun Steps 1-4, and
commit focused fixes.

- [ ] **Step 6: Finish the development branch**

Use `superpowers:verification-before-completion`, then
`superpowers:finishing-a-development-branch`. The approved integration choice
is local merge into `main`; preserve all pre-existing staged and unstaged user
changes. If Git refuses integration because `pyproject.toml` also contains the
user's uncommitted `margins` module entry, stop cleanup, preserve the feature
worktree, and integrate only after proving a non-destructive merge path.
