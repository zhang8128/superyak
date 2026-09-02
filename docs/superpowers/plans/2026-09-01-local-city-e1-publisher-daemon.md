# Local City E1: Publisher Daemon and Receiver Arm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the live engram instance obtain policy-scoped recall from other local instances through a read-only publisher daemon, deliver neighbor content under a separate `neighbors` key, and record Lighthouse receipts and disclosures.

**Architecture:** A daemon opens every published instance store read-only, evaluates a Lighthouse `ConnectionPolicy` before any retrieval, and answers `recall`/`read` frames over a Unix socket. A receiver module fuses neighbor traces by weighted reciprocal rank, requests content only under an `inject_context` grant, writes a schema-validated receipt, and is called once from `recall()` after category influence. Every failure in the neighbor path degrades to the unchanged local result.

**Tech Stack:** Python 3.12, sqlite3 + sqlite-vec, `jsonschema` (new dependency), stdlib `socket`/`socketserver`/`threading`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md` (sections 4.1–4.6, 4.8, 4.9, 5, 6, 7). Shared contracts: `docs/superpowers/plans/2026-09-01-lighthouse-local-city.md` (coordination plan).

## Global Constraints

- Python `>=3.12`; run everything with `.venv/bin/python`.
- The daemon never imports `server.py`. Publisher stores are opened only through `Storage.open_read_only`.
- Publisher retrieval covers `lane = "work"` only and the `episode` and `semantic` layers only. Instincts are never published.
- Policy is deny-by-default; evaluation must match the TypeScript kit byte-for-byte on the vendored fixtures.
- Nothing in the neighbor path may raise into `recall()`. Neighbor material is never merged into `results`.
- Receipts and disclosures never contain query text or memory content.
- Instance paths: store `ENGRAM_HOME/.engram/instances/<name>/graph.db`; policy `ENGRAM_HOME/.engram/instances/<name>/lighthouse-policy.json`; disclosure sidecar `ENGRAM_HOME/.engram/instances/<name>/lighthouse-disclosures.db`; socket default `ENGRAM_HOME/.engram/lighthouse.sock`; daemon config `ENGRAM_HOME/.engram/lighthouse-daemon.toml`.
- Lighthouse constants: profile `urn:lighthouse:profile:engram-recall-trace`, domain `memory.recall`, claim type `application/vnd.engram.recall-rank-claim+json`, audience `self`, purpose `session-recall`, context `{"id": "memory/technical", "path": ["memory", "technical"]}`, RRF constant `60`, transformation `weighted-rrf-v1`, artifact digest algorithm label `sha-256`, content digest algorithm label `sha256`.
- Commit after every task with the trailer:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`

---

### Work package brief (paste to the Codex lead)

- **Base ref:** `main` after the integrator's step-zero commit of the current working tree (margins, dedup/framing fix, research docs). Confirm `git log --oneline -1` shows a commit newer than `affca94` before cutting the branch.
- **Scope:** Read-only store open path, Python policy evaluator with vendored Lighthouse fixtures, socket protocol, publisher daemon with disclosure sidecar, receipt builder and writer with vendored schema, receiver arm with RRF fusion, one call site in `recall()`, exporter formatVersion 1.1 with receipts, labeling CLI, CLAUDE.md rows.
- **Allowed files:** `storage.py` (only: `ReadOnlyStorageError`, `open_read_only`, the `read_only` flag, guards in `_commit`, `transaction`, `close`), `lighthouse_policy.py`, `lighthouse_protocol.py`, `lighthouse_daemon.py`, `lighthouse_receipts.py`, `neighbors.py`, `lighthouse_label.py`, `lighthouse_export.py`, `schemas/lighthouse/recall-receipt.schema.json`, `tests/fixtures/lighthouse/policy/**`, `tests/test_storage_readonly.py`, `tests/test_lighthouse_policy.py`, `tests/test_lighthouse_protocol.py`, `tests/test_lighthouse_daemon.py`, `tests/test_lighthouse_receipts.py`, `tests/test_neighbors.py`, `tests/test_recall_neighbors.py`, `tests/test_lighthouse_export.py`, `tests/test_lighthouse_label.py`, `pyproject.toml` (dependency and `py-modules` additions only), `CLAUDE.md`, and in `server.py` only the block between `results = _observe_category_recall(query, results, recall_id)` and `return response` inside `recall()`.
- **Forbidden files (the seam):** `recall()`'s scoring loop and `_vector_candidates`, the margin block, the lane filter, `remember()`, `dream_verify()`, `hooks/sleep.py`, `config.py`, `margins.py`, `reflection.py`.
- **Acceptance criteria:**
  1. `.venv/bin/python -m pytest tests/test_storage_readonly.py -q` passes; the test asserts `conn.total_changes == 0` and an unchanged sha256 of `graph.db` only (WAL `-wal`/`-shm` side files are excluded) across a vector retrieval, and opens a WAL store whose side files were deleted after the writer closed.
  2. `.venv/bin/python -m pytest tests/test_lighthouse_policy.py -q` passes, including the vendored-fixture parity test and the digest test that reproduces `f12270e190c2961e56e0cc793dfe43199611d406fbedaa22e971156de33d8a3f` for the vendored policy.
  3. `.venv/bin/python -m pytest tests/test_lighthouse_daemon.py -q` passes: policy before retrieval, work lane only, no instincts, disclosure sidecar written, unavailable store answers `PUBLISHER_UNAVAILABLE` (absent file, any `sqlite3.OperationalError` on open, or a pre-migration store whose `episodes` table lacks `lane`), `graph.db` sha256 unchanged after serving.
  4. `.venv/bin/python -m pytest tests/test_neighbors.py tests/test_recall_neighbors.py -q` passes: `neighbors` key present only when a receiver policy applies, never merged into `results`, daemon down leaves the recall response byte-identical apart from `degraded`, margin unaffected, receipt written with `injected == (len(delivered) > 0)`.
  5. `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q` passes with `formatVersion == "1.1"` and a `receipts` section that carries no content or query text.
  6. `.venv/bin/python -m pytest tests/ -q` is green.
  7. `grep -n "import server" lighthouse_daemon.py` returns nothing.
- **Reports to produce:** none beyond test output; the integrator runs the live acceptance script.

---

## File structure

| File | Responsibility |
|---|---|
| `storage.py` | Adds `ReadOnlyStorageError`, `Storage.open_read_only`, `read_only` flag, guards. |
| `lighthouse_protocol.py` | Canonical JSON, artifact digest, frame dataclasses, `encode`/`decode`. |
| `lighthouse_policy.py` | `Policy`, `PolicyRequest`, `Decision`, `load_policy`, evaluation matching the TS kit. |
| `lighthouse_daemon.py` | `PublisherStore`, `PublisherDaemon`, `handle_frame`, disclosure sidecar, CLI. |
| `lighthouse_receipts.py` | `build_receipt`, `validate_receipt`, `write_receipt`. |
| `neighbors.py` | `LighthouseClient`, `fuse_traces`, `neighbor_arm`. |
| `lighthouse_label.py` | Interactive labeling CLI writing `*.labels.json`. |
| `lighthouse_export.py` | `formatVersion` 1.1, `receipts` section. |
| `schemas/lighthouse/recall-receipt.schema.json` | Vendored receipt schema. |
| `tests/fixtures/lighthouse/policy/` | Vendored policy fixtures: `policies/`, `requests/`, `decisions/`. |

---

### Task 1: Read-only store open path

**Files:**
- Modify: `storage.py` (class `Storage`: after `_restore_pragmas`; guards in `_commit` at line 115, `transaction`, `close` at line 289)
- Test: `tests/test_storage_readonly.py`

**Interfaces:**
- Produces: `class ReadOnlyStorageError(RuntimeError)`; `Storage.open_read_only(db_path: str | Path) -> Storage`; attribute `Storage.read_only: bool` (False on normal construction).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage_readonly.py
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path

import pytest

from storage import ReadOnlyStorageError, Storage


def unit(seed: int, dim: int = 768) -> list[float]:
    vec = [0.0] * dim
    vec[seed % dim] = 1.0
    return vec


def build_store(path: Path) -> None:
    store = Storage(str(path))
    store.add_episode(str(uuid.uuid4()), "s", "work fact about rivers",
                      embedding=unit(1), lane="work")
    store.add_episode(str(uuid.uuid4()), "s", "personal fact about rivers",
                      embedding=unit(2), lane="personal")
    store.close()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_open_read_only_serves_vector_search_without_changes(tmp_path):
    """Hashes graph.db only. Live stores are WAL mode, and a read-only
    connection may create or change the -wal and -shm side files; those are
    not the store and are excluded from the digest."""
    db = tmp_path / "graph.db"
    build_store(db)
    before = sha(db)

    ro = Storage.open_read_only(db)
    hits = ro.search_vectors("episode", unit(1), k=2)

    assert ro.read_only is True
    assert len(hits) == 2
    assert ro.conn.total_changes == 0
    assert sha(db) == before
    ro.close()


def test_open_read_only_refuses_mutation(tmp_path):
    db = tmp_path / "graph.db"
    build_store(db)
    ro = Storage.open_read_only(db)

    with pytest.raises(ReadOnlyStorageError):
        with ro.transaction():
            pass
    with pytest.raises((ReadOnlyStorageError, sqlite3.OperationalError)):
        ro.add_log_entry(str(uuid.uuid4()), "recall", "all", [], context={})
    ro.close()


def test_open_read_only_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Storage.open_read_only(tmp_path / "absent.db")


def test_open_read_only_works_when_wal_side_files_are_absent(tmp_path):
    """Every instance store is WAL mode. After the writer closes, the -wal and
    -shm side files may be gone. Python's sqlite3 module (library 3.49.1)
    opens such a store with mode=ro and reads it; the sqlite3 CLI (3.51)
    fails here with "unable to open database file (14)", which is a CLI
    limitation, not a store problem. Verified on the live stores 2026-09-01."""
    db = tmp_path / "graph.db"
    build_store(db)
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)

    ro = Storage.open_read_only(db)
    assert ro.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert ro.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 2
    assert len(ro.search_vectors("episode", unit(1), k=2)) == 2
    ro.close()


def test_normal_storage_is_not_read_only(tmp_path):
    store = Storage(str(tmp_path / "graph.db"))
    assert store.read_only is False
    store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage_readonly.py -q`
Expected: FAIL with `ImportError: cannot import name 'ReadOnlyStorageError'`

- [ ] **Step 3: Implement**

In `storage.py`, above `class Storage`:

```python
class ReadOnlyStorageError(RuntimeError):
    """Raised when a mutation is attempted on a read-only Storage."""
```

In `Storage.__init__`, after `self._transaction_depth = 0`, add `self.read_only = False`.

Add the classmethod after `_restore_pragmas`:

```python
    @classmethod
    def open_read_only(cls, db_path: str | Path) -> "Storage":
        """Open an existing store for retrieval only.

        SQLite URI ``mode=ro`` plus ``query_only`` refuse writes at the
        engine; the ``read_only`` flag makes ``transaction``/``_commit``
        refuse at the API. No migrations, no health rebuild, no WAL
        checkpoint on close: the file's bytes are never touched.

        Never ``immutable=1``: a live session in the publisher's repository
        is a legitimate concurrent writer, and ``immutable`` would read
        inconsistent pages. ``mode=ro`` on a WAL store is safe and, from
        Python's sqlite3 module, opens even when the -wal/-shm side files
        are absent (verified on the live stores 2026-09-01).
        """
        path = Path(db_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        self = cls.__new__(cls)
        self.db_path = str(path)
        self._check_same_thread = False
        # mode=ro only. Do not add immutable=1 (see docstring).
        self.conn = sqlite3.connect(
            f"file:{path.resolve()}?mode=ro", uri=True, check_same_thread=False
        )
        self._conn_closed = False
        self.conn.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._migrations_dir = None
        self.read_only = True
        self.conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        return self
```

At the top of `_commit`:

```python
        if getattr(self, "read_only", False):
            raise ReadOnlyStorageError("storage opened read-only")
```

At the top of `transaction` (before `outermost = ...`):

```python
        if getattr(self, "read_only", False):
            raise ReadOnlyStorageError("storage opened read-only")
```

At the top of `close`, before the cold-connection block:

```python
        if getattr(self, "read_only", False):
            if not self._conn_closed:
                self.conn.close()
                self._conn_closed = True
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage_readonly.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_readonly.py
git commit -m "feat: add read-only Storage open path for publishers"
```

---

### Task 2: Canonical JSON and artifact digests

**Files:**
- Create: `lighthouse_protocol.py`
- Test: `tests/test_lighthouse_protocol.py`

**Interfaces:**
- Produces: `canonical_json(value) -> str`; `artifact_digest(artifact: dict) -> dict` returning `{"algorithm": "sha-256", "value": hex}` over the envelope minus `digest` and `attestations`; `verify_artifact_digest(artifact: dict) -> bool`; `content_digest(text: str) -> dict` returning `{"algorithm": "sha256", "value": hex}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lighthouse_protocol.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lighthouse_protocol import (
    artifact_digest,
    canonical_json,
    content_digest,
    verify_artifact_digest,
)

FIXTURES = Path(__file__).parent / "fixtures" / "lighthouse" / "policy"


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": [1, {"z": None, "a": "é"}], "a": True}) == \
        '{"a":true,"b":[1,{"a":"é","z":null}]}'


def test_canonical_json_rejects_non_finite():
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})


def test_artifact_digest_reproduces_lighthouse_reference_policy():
    policy = json.loads((FIXTURES / "policies" / "workflow-policy.json").read_text())
    assert artifact_digest(policy) == policy["digest"]
    assert verify_artifact_digest(policy) is True


def test_verify_rejects_tampered_artifact():
    policy = json.loads((FIXTURES / "policies" / "workflow-policy.json").read_text())
    policy["issuer"] = "urn:lighthouse:someone-else"
    assert verify_artifact_digest(policy) is False


def test_content_digest_label_is_sha256_without_hyphen():
    assert content_digest("abc") == {
        "algorithm": "sha256",
        "value": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    }
```

- [ ] **Step 2: Vendor the reference policy fixture**

Create `tests/fixtures/lighthouse/policy/policies/workflow-policy.json` as a byte-for-byte copy of `/Users/kairos/Projects/lighthouse/fixtures/policy/workflow-policy.json` (its digest is `f12270e190c2961e56e0cc793dfe43199611d406fbedaa22e971156de33d8a3f`).

```bash
mkdir -p tests/fixtures/lighthouse/policy/{policies,requests,decisions}
cp /Users/kairos/Projects/lighthouse/fixtures/policy/workflow-policy.json tests/fixtures/lighthouse/policy/policies/
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_protocol.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lighthouse_protocol'`

- [ ] **Step 4: Implement**

```python
# lighthouse_protocol.py
"""Lighthouse wire format for the local city: canonical JSON, artifact
digests, and the JSON-lines frames exchanged with the publisher daemon.

Canonical JSON matches the TypeScript kit's ``canonicalize``: recursively
sorted object keys, no whitespace, JSON string escaping, non-finite numbers
rejected. Artifact digests cover the envelope minus ``digest`` and
``attestations`` and carry the label ``sha-256``; content digests carry
``sha256``, matching the Engram recall profile.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL_VERSION = "0.1"
FRAME_KINDS = frozenset({"recall", "recall_result", "read", "read_result", "error"})


def _check_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number is not JSON")
    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, list):
        for item in value:
            _check_finite(item)


def canonical_json(value: Any) -> str:
    _check_finite(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def artifact_digest(artifact: dict) -> dict:
    content = {k: v for k, v in artifact.items() if k not in ("digest", "attestations")}
    return {
        "algorithm": "sha-256",
        "value": hashlib.sha256(canonical_json(content).encode("utf-8")).hexdigest(),
    }


def verify_artifact_digest(artifact: dict) -> bool:
    expected = artifact.get("digest")
    if not isinstance(expected, dict) or expected.get("algorithm") != "sha-256":
        return False
    return artifact_digest(artifact)["value"] == expected.get("value")


def content_digest(text: str) -> dict:
    return {"algorithm": "sha256", "value": hashlib.sha256(text.encode("utf-8")).hexdigest()}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_protocol.py -q`
Expected: 5 passed

- [ ] **Step 6: Register the module and commit**

Add `"lighthouse_protocol",` to the `py-modules` list in `pyproject.toml` (alphabetical, after `"lighthouse_export"`).

```bash
git add lighthouse_protocol.py tests/test_lighthouse_protocol.py tests/fixtures/lighthouse/policy/policies/workflow-policy.json pyproject.toml
git commit -m "feat: add Lighthouse canonical JSON and artifact digests"
```

---

### Task 3: Policy evaluator with vendored fixture parity

**Files:**
- Create: `lighthouse_policy.py`
- Create: `tests/fixtures/lighthouse/policy/requests/recall-request.json`, `tests/fixtures/lighthouse/policy/decisions/recall-request.json`
- Test: `tests/test_lighthouse_policy.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) PolicyRequest(publisher, profile, domain, action, context_id, claim_type, purpose, audience, at: datetime, evidence: tuple[str, ...] = (), attestations: tuple[str, ...] = ())`
  - `@dataclass(frozen=True) Decision(effect: str, rule_id: str | None, code: str | None)` with `to_lighthouse() -> dict` producing exactly `{"allowed": True, "ruleId": id}` or `{"allowed": False, "code": code}` plus `"ruleId"` when present.
  - `class Policy` with `.artifact: dict`, `.issuer: str`, `.rules: list[dict]`, `.decide(req) -> Decision`, `.rule(rule_id) -> dict | None`.
  - `load_policy(path: Path) -> Policy` (raises `PolicyError(code)` with `POLICY_NOT_FOUND`, `POLICY_INVALID`, `DIGEST_MISMATCH`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lighthouse_policy.py
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lighthouse_policy import Decision, Policy, PolicyError, PolicyRequest, load_policy

FIXTURES = Path(__file__).parent / "fixtures" / "lighthouse" / "policy"


def request_from_json(data: dict) -> PolicyRequest:
    return PolicyRequest(
        publisher=data["publisher"], profile=data["profile"], domain=data["domain"],
        action=data["action"], context_id=data["context"], claim_type=data["claimMediaType"],
        purpose=data["purpose"], audience=data["audience"],
        at=datetime.fromisoformat(data["at"].replace("Z", "+00:00")),
        evidence=tuple(data.get("evidence", [])), attestations=tuple(data.get("attestations", [])),
    )


def test_vendored_fixtures_match_typescript_decisions():
    """Every request fixture must decide exactly as the Lighthouse kit did.

    Fixture shapes follow L1's `pnpm policy:fixtures` generator:
      requests/<name>.json  = {"policy": "<file in policies/>", "request": {...}}
      decisions/<name>.json = {"policy": ..., "request": {...}, "decision": <authorize output>}
    The test iterates every file in requests/, so the generated set drops in unchanged.
    """
    cases = sorted((FIXTURES / "requests").glob("*.json"))
    assert cases, "no vendored request fixtures"
    for request_path in cases:
        case = json.loads(request_path.read_text())
        expected = json.loads((FIXTURES / "decisions" / request_path.name).read_text())
        policy = load_policy(FIXTURES / "policies" / case["policy"])
        decision = policy.decide(request_from_json(case["request"])).to_lighthouse()
        assert decision == expected["decision"], request_path.name


def test_load_policy_rejects_digest_mismatch(tmp_path):
    policy = json.loads((FIXTURES / "policies" / "workflow-policy.json").read_text())
    policy["issuer"] = "tampered"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(PolicyError) as err:
        load_policy(path)
    assert err.value.code == "DIGEST_MISMATCH"


def test_load_policy_missing_file():
    with pytest.raises(PolicyError) as err:
        load_policy(Path("/nonexistent/policy.json"))
    assert err.value.code == "POLICY_NOT_FOUND"


def base_request(**overrides) -> PolicyRequest:
    fields = dict(
        publisher="urn:lighthouse:trusted-crew", profile="urn:lighthouse:profile:hyper-modules",
        domain="personal.memory", action="recall", context_id="workflow/orders",
        claim_type="application/vnd.hyper.dependency-claim+json", purpose="debugging",
        audience="self", at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    fields.update(overrides)
    return PolicyRequest(**fields)


def test_no_structural_match_is_no_matching_allow():
    policy = load_policy(FIXTURES / "policies" / "workflow-policy.json")
    decision = policy.decide(base_request(publisher="urn:lighthouse:stranger"))
    assert decision == Decision("deny", None, "NO_MATCHING_ALLOW")


def test_outside_validity():
    policy = load_policy(FIXTURES / "policies" / "workflow-policy.json")
    decision = policy.decide(base_request(at=datetime(2030, 1, 1, tzinfo=timezone.utc)))
    assert decision.code == "OUTSIDE_VALIDITY"


def test_deny_wins_specificity_tie(tmp_path):
    from lighthouse_protocol import artifact_digest
    rule = lambda rid, effect: {
        "id": rid, "effect": effect, "publishers": ["p"], "profiles": ["pr"], "domains": ["d"],
        "actions": ["recall"], "contexts": ["c"], "claimMediaTypes": ["m"], "purposes": ["u"],
        "audiences": ["self"], "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z",
        "requiredEvidence": [], "requiredAttestations": [],
    }
    artifact = {
        "kind": "ConnectionPolicy", "protocolVersion": "0.1", "id": "urn:policy:t",
        "issuedAt": "2026-08-30T12:00:00Z", "issuer": "urn:lighthouse:t",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": [rule("a-allow", "allow"), rule("b-deny", "deny")]},
    }
    artifact["digest"] = artifact_digest(artifact)
    path = tmp_path / "tie.json"
    path.write_text(json.dumps(artifact))
    policy = load_policy(path)
    decision = policy.decide(base_request(
        publisher="p", profile="pr", domain="d", context_id="c", claim_type="m", purpose="u"))
    assert decision == Decision("deny", "b-deny", "EXPLICIT_DENY")


def test_prefix_selector_scores_below_exact(tmp_path):
    from lighthouse_protocol import artifact_digest
    def rule(rid, effect, publishers):
        return {
            "id": rid, "effect": effect, "publishers": publishers, "profiles": ["pr"], "domains": ["d"],
            "actions": ["recall"], "contexts": ["c"], "claimMediaTypes": ["m"], "purposes": ["u"],
            "audiences": ["self"], "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z",
            "requiredEvidence": [], "requiredAttestations": [],
        }
    artifact = {
        "kind": "ConnectionPolicy", "protocolVersion": "0.1", "id": "urn:policy:t",
        "issuedAt": "2026-08-30T12:00:00Z", "issuer": "urn:lighthouse:t",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": [rule("deny-all-urn", "deny", ["urn:*"]), rule("allow-exact", "allow", ["urn:p"])]},
    }
    artifact["digest"] = artifact_digest(artifact)
    path = tmp_path / "prefix.json"
    path.write_text(json.dumps(artifact))
    decision = load_policy(path).decide(base_request(
        publisher="urn:p", profile="pr", domain="d", context_id="c", claim_type="m", purpose="u"))
    assert decision == Decision("allow", "allow-exact", None)
```

- [ ] **Step 2: Vendor the request and expected decision**

Fixture files use the shape L1's generator (`pnpm policy:fixtures`) writes.
`tests/fixtures/lighthouse/policy/requests/recall-request.json`:

```json
{
  "policy": "workflow-policy.json",
  "request": {
    "publisher": "urn:lighthouse:trusted-crew",
    "profile": "urn:lighthouse:profile:hyper-modules",
    "domain": "personal.memory",
    "action": "recall",
    "context": "workflow/orders",
    "claimMediaType": "application/vnd.hyper.dependency-claim+json",
    "purpose": "debugging",
    "audience": "self",
    "at": "2026-09-01T00:00:00Z",
    "evidence": [],
    "attestations": []
  }
}
```

`tests/fixtures/lighthouse/policy/decisions/recall-request.json` repeats `policy`
and `request` and adds the exact `authorize` output object:

```bash
cd /Users/kairos/Projects/lighthouse && pnpm --silent lighthouse authorize fixtures/policy/workflow-policy.json fixtures/policy/recall-request.json
```

```json
{
  "policy": "workflow-policy.json",
  "request": { "...same request object as above..." : "" },
  "decision": {"allowed": true, "ruleId": "allow-crew-debug-recall"}
}
```

(Copy the request object verbatim into the decision file; the placeholder line above stands for that copy.)

Repeat for `inject-request.json`: request `{"policy": "workflow-policy.json", "request": <contents of /Users/kairos/Projects/lighthouse/fixtures/policy/inject-request.json>}`, decision from `authorize` on that pair, which is `{"allowed": false, "code": "EXPLICIT_DENY", "ruleId": "deny-crew-context-injection"}`.

After L1 lands, the integrator replaces these two hand-vendored pairs with the full generated set (14 requests) under `tests/fixtures/lighthouse/policy/`; the parity test iterates every file in `requests/`, so nothing in the test changes.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_policy.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lighthouse_policy'`

- [ ] **Step 4: Implement**

```python
# lighthouse_policy.py
"""Lighthouse ConnectionPolicy evaluation in Python.

Mirrors packages/calculus/src/policy.ts in the Lighthouse kit exactly:
exact selector = 2, ``*``-suffixed prefix selector = 1, eight dimensions
summed; required evidence/attestations must be subsets of the request; no
structural match -> NO_MATCHING_ALLOW; no active match -> OUTSIDE_VALIDITY;
highest score wins, a deny beats an allow at the same score, remaining ties
break on the canonical JSON of the rule id. Deny-by-default, never
transitive: a policy speaks only for its own issuer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_protocol import canonical_json, verify_artifact_digest

_DIMENSIONS = (
    ("publishers", "publisher"), ("profiles", "profile"), ("domains", "domain"),
    ("actions", "action"), ("contexts", "context_id"), ("claimMediaTypes", "claim_type"),
    ("purposes", "purpose"), ("audiences", "audience"),
)


class PolicyError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PolicyRequest:
    publisher: str
    profile: str
    domain: str
    action: str
    context_id: str
    claim_type: str
    purpose: str
    audience: str
    at: datetime
    evidence: tuple[str, ...] = ()
    attestations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    effect: str
    rule_id: str | None
    code: str | None

    def to_lighthouse(self) -> dict:
        if self.effect == "allow":
            return {"allowed": True, "ruleId": self.rule_id}
        out: dict = {"allowed": False, "code": self.code}
        if self.rule_id is not None:
            out["ruleId"] = self.rule_id
        return out

    def to_json(self) -> dict:
        """Wire and receipt shape. ``ruleId`` and ``code`` are always present,
        ``null`` when absent, so canonical JSON matches the TypeScript kit;
        never serialize this through a None-dropping filter."""
        return {"effect": self.effect, "ruleId": self.rule_id, "code": self.code}


def _parse_rfc3339(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pattern_score(pattern: str, value: str) -> int | None:
    if pattern == value:
        return 2
    if pattern.endswith("*") and value.startswith(pattern[:-1]):
        return 1
    return None


def _selector_score(patterns: list[str], value: str) -> int | None:
    best: int | None = None
    for pattern in patterns:
        score = _pattern_score(pattern, value)
        if score is not None and (best is None or score > best):
            best = score
    return best


def _rule_score(rule: dict, req: PolicyRequest) -> int | None:
    total = 0
    for rule_key, req_key in _DIMENSIONS:
        score = _selector_score(rule[rule_key], getattr(req, req_key))
        if score is None:
            return None
        total += score
    if not all(item in req.evidence for item in rule.get("requiredEvidence", [])):
        return None
    if not all(item in req.attestations for item in rule.get("requiredAttestations", [])):
        return None
    return total


class Policy:
    def __init__(self, artifact: dict):
        self.artifact = artifact
        self.issuer = artifact["issuer"]
        self.rules: list[dict] = list(artifact["payload"]["rules"])

    def rule(self, rule_id: str) -> dict | None:
        return next((r for r in self.rules if r["id"] == rule_id), None)

    def decide(self, req: PolicyRequest) -> Decision:
        structural = []
        for rule in self.rules:
            score = _rule_score(rule, req)
            if score is not None:
                structural.append((rule, score))
        if not structural:
            return Decision("deny", None, "NO_MATCHING_ALLOW")
        at = req.at if req.at.tzinfo else req.at.replace(tzinfo=timezone.utc)
        active = []
        for rule, score in structural:
            start, end = _parse_rfc3339(rule["validFrom"]), _parse_rfc3339(rule["validUntil"])
            if start is not None and end is not None and start <= at <= end:
                active.append((rule, score))
        if not active:
            return Decision("deny", None, "OUTSIDE_VALIDITY")
        active.sort(key=lambda item: (
            -item[1], 0 if item[0]["effect"] == "deny" else 1, canonical_json(item[0]["id"])))
        top = active[0][1]
        winner = next((r for r, s in active if s == top and r["effect"] == "deny"), active[0][0])
        if winner["effect"] == "allow":
            return Decision("allow", winner["id"], None)
        return Decision("deny", winner["id"], "EXPLICIT_DENY")


def load_policy(path: Path) -> Policy:
    path = Path(path)
    if not path.is_file():
        raise PolicyError("POLICY_NOT_FOUND")
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PolicyError("POLICY_INVALID") from error
    if not isinstance(artifact, dict) or artifact.get("kind") != "ConnectionPolicy" \
            or artifact.get("protocolVersion") != "0.1" \
            or not isinstance(artifact.get("payload"), dict) \
            or not isinstance(artifact["payload"].get("rules"), list):
        raise PolicyError("POLICY_INVALID")
    if not verify_artifact_digest(artifact):
        raise PolicyError("DIGEST_MISMATCH")
    return Policy(artifact)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_policy.py -q`
Expected: 7 passed

- [ ] **Step 6: Register and commit**

Add `"lighthouse_policy",` to `py-modules` in `pyproject.toml`.

```bash
git add lighthouse_policy.py tests/test_lighthouse_policy.py tests/fixtures/lighthouse/policy pyproject.toml
git commit -m "feat: add Lighthouse policy evaluator with kit parity fixtures"
```

---

### Task 4: Protocol frames

**Files:**
- Modify: `lighthouse_protocol.py`
- Test: `tests/test_lighthouse_protocol.py` (append)

**Interfaces:**
- Produces: `encode(frame: dict) -> bytes` (one line, trailing newline) and `decode(line: bytes) -> dict` raising `FrameError(code)` with `MALFORMED_FRAME` or `PROTOCOL_VERSION_MISMATCH`; builders `recall_frame(...)`, `recall_result_frame(...)`, `read_frame(...)`, `read_result_frame(...)`, `error_frame(code, detail)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_lighthouse_protocol.py`)

```python
from lighthouse_protocol import FrameError, decode, encode, error_frame, recall_frame, read_frame


def test_recall_frame_round_trips():
    frame = recall_frame(
        receiver="engram", publisher="why", context={"id": "memory/technical", "path": ["memory", "technical"]},
        purpose="session-recall", query="rivers", k=5, at="2026-09-01T00:00:00+00:00")
    assert frame["kind"] == "recall" and frame["protocolVersion"] == "0.1"
    assert frame["audience"] == "self"
    assert decode(encode(frame)) == frame
    assert encode(frame).endswith(b"\n") and encode(frame).count(b"\n") == 1


def test_read_frame_carries_ids_and_turn():
    frame = read_frame(receiver="engram", publisher="why",
                       context={"id": "memory/technical", "path": ["memory", "technical"]},
                       purpose="session-recall", turn_id="t1", memory_ids=["m1", "m2"])
    assert frame["memoryIds"] == ["m1", "m2"] and frame["turnId"] == "t1"


def test_decode_rejects_bad_json_and_wrong_version():
    with pytest.raises(FrameError) as err:
        decode(b"{not json\n")
    assert err.value.code == "MALFORMED_FRAME"
    with pytest.raises(FrameError) as err:
        decode(b'{"protocolVersion":"9.9","kind":"recall"}\n')
    assert err.value.code == "PROTOCOL_VERSION_MISMATCH"
    with pytest.raises(FrameError) as err:
        decode(b'{"protocolVersion":"0.1","kind":"dance"}\n')
    assert err.value.code == "MALFORMED_FRAME"


def test_error_frame_shape():
    assert error_frame("PUBLISHER_UNAVAILABLE", "store locked") == {
        "protocolVersion": "0.1", "kind": "error",
        "code": "PUBLISHER_UNAVAILABLE", "detail": "store locked"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_protocol.py -q`
Expected: FAIL with `ImportError: cannot import name 'FrameError'`

- [ ] **Step 3: Implement** (append to `lighthouse_protocol.py`)

```python
class FrameError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def encode(frame: dict) -> bytes:
    return (canonical_json(frame) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    try:
        frame = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FrameError("MALFORMED_FRAME") from error
    if not isinstance(frame, dict) or frame.get("kind") not in FRAME_KINDS:
        raise FrameError("MALFORMED_FRAME")
    if frame.get("protocolVersion") != PROTOCOL_VERSION:
        raise FrameError("PROTOCOL_VERSION_MISMATCH")
    return frame


def _base(kind: str) -> dict:
    return {"protocolVersion": PROTOCOL_VERSION, "kind": kind}


def recall_frame(*, receiver: str, publisher: str, context: dict, purpose: str,
                 query: str, k: int, at: str) -> dict:
    return {**_base("recall"), "receiver": receiver, "publisher": publisher,
            "context": context, "purpose": purpose, "audience": "self",
            "query": query, "k": int(k), "at": at}


def recall_result_frame(*, turn_id: str, query_digest: dict, context: dict,
                        candidates: list[dict], decision: dict, disclosure_id: str | None) -> dict:
    return {**_base("recall_result"), "turnId": turn_id, "queryDigest": query_digest,
            "context": context, "candidates": candidates, "decision": decision,
            "disclosureId": disclosure_id}


def read_frame(*, receiver: str, publisher: str, context: dict, purpose: str,
               turn_id: str, memory_ids: list[str]) -> dict:
    return {**_base("read"), "receiver": receiver, "publisher": publisher,
            "context": context, "purpose": purpose, "turnId": turn_id,
            "memoryIds": list(memory_ids)}


def read_result_frame(*, items: list[dict], disclosure_id: str | None) -> dict:
    return {**_base("read_result"), "items": items, "disclosureId": disclosure_id}


def error_frame(code: str, detail: str = "") -> dict:
    return {**_base("error"), "code": code, "detail": detail}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_protocol.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add lighthouse_protocol.py tests/test_lighthouse_protocol.py
git commit -m "feat: add Lighthouse socket frames"
```

---

### Task 5: Publisher daemon

**Files:**
- Create: `lighthouse_daemon.py`
- Test: `tests/test_lighthouse_daemon.py`

**Interfaces:**
- Consumes: `Storage.open_read_only`, `load_policy`, `PolicyRequest`, frames from Task 4.
- Produces:
  - `class PublisherStore(name: str, db_path: Path, policy_path: Path, disclosures_path: Path)` with `.open()` (lazy, returns bool), `.policy`, `.storage`, `.record_disclosure(event: dict) -> str`, `.store_digest() -> dict`.
  - `class PublisherDaemon(publishers: dict[str, PublisherStore], socket_path: Path, embeddings)` with `.serve_forever()`, `.stop()`, `.handle_frame(frame: dict) -> dict`.
  - `retrieve(store: Storage, embeddings, query: str, k: int) -> list[dict]` returning candidates `{memoryId, rank, layer, lane, contentDigest, similarity}` from work-lane episodes and semantics.
  - `load_daemon_config(path: Path) -> dict` and `main(argv) -> int`.
  - Disclosure sidecar table `disclosures(id TEXT PRIMARY KEY, at TEXT, receiver TEXT, action TEXT, context_id TEXT, purpose TEXT, effect TEXT, rule_id TEXT, code TEXT, memory_ids TEXT)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lighthouse_daemon.py
from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lighthouse_daemon import PublisherDaemon, PublisherStore, retrieve
from lighthouse_protocol import artifact_digest, decode, encode, read_frame, recall_frame
from storage import Storage


class FakeEmbeddings:
    def embed(self, texts, prefix=None):
        out = []
        for text in texts:
            vec = [0.0] * 768
            vec[sum(map(ord, text)) % 768] = 1.0
            out.append(vec)
        return out


def unit(text: str) -> list[float]:
    return FakeEmbeddings().embed([text])[0]


def write_policy(path: Path, *, receiver: str = "engram", actions=("recall", "read")) -> None:
    artifact = {
        "kind": "ConnectionPolicy", "protocolVersion": "0.1", "id": "urn:policy:why",
        "issuedAt": "2026-09-01T00:00:00Z", "issuer": "urn:engram:why",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": [{
            "id": "allow-engram-technical", "effect": "allow",
            "publishers": [f"urn:engram:{receiver}"],
            "profiles": ["urn:lighthouse:profile:engram-recall-trace"],
            "domains": ["memory.recall"], "actions": list(actions),
            "contexts": ["memory/technical"],
            "claimMediaTypes": ["application/vnd.engram.recall-rank-claim+json"],
            "purposes": ["session-recall"], "audiences": ["self"],
            "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z",
            "requiredEvidence": [], "requiredAttestations": []}]},
    }
    artifact["digest"] = artifact_digest(artifact)
    path.write_text(json.dumps(artifact))


def build_publisher(root: Path, name: str = "why") -> PublisherStore:
    inst = root / ".engram" / "instances" / name
    inst.mkdir(parents=True)
    store = Storage(str(inst / "graph.db"))
    store.add_episode(str(uuid.uuid4()), "s", "work: rivers need bridges",
                      embedding=unit("work: rivers need bridges"), lane="work")
    store.add_episode(str(uuid.uuid4()), "s", "personal: rivers at dusk",
                      embedding=unit("rivers"), lane="personal")
    store.close()
    write_policy(inst / "lighthouse-policy.json")
    return PublisherStore(name=name, db_path=inst / "graph.db",
                          policy_path=inst / "lighthouse-policy.json",
                          disclosures_path=inst / "lighthouse-disclosures.db")


CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc).isoformat()


def test_retrieve_returns_work_lane_only(tmp_path):
    pub = build_publisher(tmp_path)
    assert pub.open() is True
    hits = retrieve(pub.storage, FakeEmbeddings(), "rivers", k=5)
    assert hits and all(h["lane"] == "work" for h in hits)
    assert all(h["layer"] in ("episode", "semantic") for h in hits)
    assert hits[0]["rank"] == 1 and hits[0]["contentDigest"]["algorithm"] == "sha256"


def test_handle_recall_denies_before_retrieval(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    frame = recall_frame(receiver="stranger", publisher="why", context=CONTEXT,
                         purpose="session-recall", query="rivers", k=5, at=NOW)
    out = daemon.handle_frame(frame)
    assert out["kind"] == "recall_result"
    assert out["candidates"] == []
    assert out["decision"]["effect"] == "deny" and out["decision"]["code"] == "NO_MATCHING_ALLOW"
    rows = sqlite3.connect(pub.disclosures_path).execute("SELECT effect, receiver FROM disclosures").fetchall()
    assert rows == [("deny", "stranger")]


def test_handle_recall_allows_and_discloses(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    frame = recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                         purpose="session-recall", query="work: rivers need bridges", k=5, at=NOW)
    out = daemon.handle_frame(frame)
    assert out["decision"] == {"effect": "allow", "ruleId": "allow-engram-technical", "code": None}
    assert len(out["candidates"]) == 1
    assert out["queryDigest"]["value"] == hashlib.sha256(b"work: rivers need bridges").hexdigest()
    row = sqlite3.connect(pub.disclosures_path).execute(
        "SELECT action, memory_ids FROM disclosures").fetchone()
    assert row[0] == "recall" and json.loads(row[1]) == [out["candidates"][0]["memoryId"]]


def test_read_requires_read_action(tmp_path):
    pub = build_publisher(tmp_path)
    write_policy(pub.policy_path, actions=("recall",))
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    recall = daemon.handle_frame(recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                                              purpose="session-recall", query="work: rivers need bridges", k=5, at=NOW))
    mid = recall["candidates"][0]["memoryId"]
    out = daemon.handle_frame(read_frame(receiver="engram", publisher="why", context=CONTEXT,
                                         purpose="session-recall", turn_id=recall["turnId"], memory_ids=[mid]))
    assert out["kind"] == "read_result"
    assert out["items"][0]["content"] is None
    assert out["items"][0]["decision"]["code"] == "NO_MATCHING_ALLOW"


def test_read_delivers_content_when_allowed(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    recall = daemon.handle_frame(recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                                              purpose="session-recall", query="work: rivers need bridges", k=5, at=NOW))
    mid = recall["candidates"][0]["memoryId"]
    out = daemon.handle_frame(read_frame(receiver="engram", publisher="why", context=CONTEXT,
                                         purpose="session-recall", turn_id=recall["turnId"], memory_ids=[mid]))
    assert out["items"][0]["content"] == "work: rivers need bridges"
    assert out["items"][0]["decision"]["effect"] == "allow"


def test_unknown_publisher_and_unavailable_store(tmp_path):
    pub = build_publisher(tmp_path)
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    unknown = daemon.handle_frame(recall_frame(receiver="engram", publisher="ghost", context=CONTEXT,
                                               purpose="session-recall", query="x", k=1, at=NOW))
    assert unknown["kind"] == "error" and unknown["code"] == "PUBLISHER_UNAVAILABLE"
    pub.db_path.unlink()
    gone = daemon.handle_frame(recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                                            purpose="session-recall", query="x", k=1, at=NOW))
    assert gone["kind"] == "error" and gone["code"] == "PUBLISHER_UNAVAILABLE"


def test_socket_round_trip_leaves_store_unchanged(tmp_path):
    pub = build_publisher(tmp_path)
    before = hashlib.sha256(pub.db_path.read_bytes()).hexdigest()
    sock_path = tmp_path / "lh.sock"
    daemon = PublisherDaemon({"why": pub}, sock_path, FakeEmbeddings())
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    try:
        daemon.wait_ready(timeout=5)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(sock_path))
            client.sendall(encode(recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                                               purpose="session-recall", query="work: rivers need bridges", k=3, at=NOW)))
            line = client.makefile("rb").readline()
        out = decode(line)
        assert out["kind"] == "recall_result" and len(out["candidates"]) == 1
    finally:
        daemon.stop()
        thread.join(timeout=5)
    assert hashlib.sha256(pub.db_path.read_bytes()).hexdigest() == before


def test_operational_error_on_open_is_publisher_unavailable(tmp_path, monkeypatch):
    pub = build_publisher(tmp_path)

    def refuse(cls, path):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(Storage, "open_read_only", classmethod(refuse))
    daemon = PublisherDaemon({"why": pub}, tmp_path / "s.sock", FakeEmbeddings())
    out = daemon.handle_frame(recall_frame(receiver="engram", publisher="why", context=CONTEXT,
                                           purpose="session-recall", query="x", k=1, at=NOW))
    assert out["kind"] == "error" and out["code"] == "PUBLISHER_UNAVAILABLE"
    assert pub.storage is None


def test_pre_migration_store_without_lane_column_is_unavailable(tmp_path):
    """agi, claw, and gil predate the lane migration: no lane column, nothing publishable."""
    inst = tmp_path / ".engram" / "instances" / "agi"
    inst.mkdir(parents=True)
    conn = sqlite3.connect(inst / "graph.db")
    conn.execute("CREATE TABLE episodes (id TEXT PRIMARY KEY, content TEXT)")
    conn.commit()
    conn.close()
    write_policy(inst / "lighthouse-policy.json")
    pub = PublisherStore(name="agi", db_path=inst / "graph.db",
                         policy_path=inst / "lighthouse-policy.json",
                         disclosures_path=inst / "lighthouse-disclosures.db")
    daemon = PublisherDaemon({"agi": pub}, tmp_path / "s.sock", FakeEmbeddings())
    out = daemon.handle_frame(recall_frame(receiver="engram", publisher="agi", context=CONTEXT,
                                           purpose="session-recall", query="x", k=1, at=NOW))
    assert out["kind"] == "error" and out["code"] == "PUBLISHER_UNAVAILABLE"
    assert pub.storage is None


def test_daemon_never_imports_server():
    import lighthouse_daemon
    source = Path(lighthouse_daemon.__file__).read_text()
    assert "import server" not in source and "from server" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_daemon.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lighthouse_daemon'`

- [ ] **Step 3: Implement**

```python
# lighthouse_daemon.py
"""Publisher daemon for the Lighthouse local city.

One process hosts the publisher side of every local engram instance listed
in its config. Each store is opened read-only (never migrated, never
written); each instance carries its own deny-by-default ConnectionPolicy;
policy is evaluated before any retrieval; retrieval is restricted to the
work lane and to episodes and semantics. Decisions and disclosures are
appended to a sidecar SQLite file beside the store so the store's bytes
never change. This module must never import server.py.

Usage:
    python -m lighthouse_daemon --config ~/.engram/lighthouse-daemon.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import socket
import socketserver
import sqlite3
import sys
import threading
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_policy import Policy, PolicyError, PolicyRequest, load_policy
from lighthouse_protocol import (
    FrameError, content_digest, decode, encode, error_frame,
    read_result_frame, recall_result_frame,
)
from storage import Storage, vec0_distance_to_similarity

logger = logging.getLogger("engram.lighthouse_daemon")

PROFILE = "urn:lighthouse:profile:engram-recall-trace"
DOMAIN = "memory.recall"
CLAIM_TYPE = "application/vnd.engram.recall-rank-claim+json"
PUBLISHED_LAYERS = ("episode", "semantic")

_SIDECAR_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS disclosures ("
    "id TEXT PRIMARY KEY, at TEXT NOT NULL, receiver TEXT NOT NULL, action TEXT NOT NULL, "
    "context_id TEXT NOT NULL, purpose TEXT NOT NULL, effect TEXT NOT NULL, "
    "rule_id TEXT, code TEXT, memory_ids TEXT NOT NULL)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PublisherStore:
    name: str
    db_path: Path
    policy_path: Path
    disclosures_path: Path
    storage: Storage | None = None
    policy: Policy | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def publisher_id(self) -> str:
        return f"urn:engram:{self.name}"

    def open(self) -> bool:
        with self._lock:
            if self.storage is not None and self.policy is not None:
                return True
            try:
                self.policy = load_policy(self.policy_path)
                # mode=ro only, never immutable=1: a live session in the
                # publisher's repository is a legitimate concurrent writer.
                self.storage = Storage.open_read_only(self.db_path)
                columns = {row[1] for row in self.storage.conn.execute("PRAGMA table_info(episodes)")}
                if "lane" not in columns:
                    # Pre-migration instances (agi, claw, gil) have no lane
                    # boundary and therefore nothing publishable.
                    raise sqlite3.OperationalError("episodes.lane missing (pre-migration store)")
            except (PolicyError, FileNotFoundError, sqlite3.Error) as error:
                # Any OperationalError on open (locked, unreadable, absent
                # side files on a CLI-style open, etc.) is PUBLISHER_UNAVAILABLE.
                logger.warning("publisher %s unavailable: %s", self.name, error)
                if self.storage is not None:
                    try:
                        self.storage.close()
                    except Exception:
                        pass
                self.storage = None
                self.policy = None
                return False
            return True

    def reset(self) -> None:
        with self._lock:
            if self.storage is not None:
                try:
                    self.storage.close()
                except Exception:
                    pass
            self.storage = None
            self.policy = None

    def store_digest(self) -> dict:
        return {"algorithm": "sha256", "value": hashlib.sha256(self.db_path.read_bytes()).hexdigest()}

    def record_disclosure(self, event: dict) -> str:
        disclosure_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.disclosures_path)
        try:
            conn.execute(_SIDECAR_SCHEMA)
            conn.execute(
                "INSERT INTO disclosures VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (disclosure_id, _now(), event["receiver"], event["action"], event["context_id"],
                 event["purpose"], event["effect"], event.get("rule_id"), event.get("code"),
                 json.dumps(event.get("memory_ids", []))),
            )
            conn.commit()
        finally:
            conn.close()
        return disclosure_id


def retrieve(store: Storage, embeddings, query: str, k: int) -> list[dict]:
    """Work-lane episodes and semantics ranked by cosine similarity."""
    vector = embeddings.embed([query], prefix="search_query")[0]
    scored: list[tuple[float, str, str, dict]] = []
    for layer in PUBLISHED_LAYERS:
        try:
            hits = store.search_vectors(layer, vector, k=max(k * 4, 8))
        except Exception:
            logger.debug("vector search failed for %s", layer, exc_info=True)
            continue
        for mid, distance in hits:
            row = store.get_episode(mid) if layer == "episode" else store.get_semantic(mid)
            if row is None or (row.get("lane") or "personal") != "work":
                continue
            scored.append((vec0_distance_to_similarity(distance), layer, mid, row))
    scored.sort(key=lambda item: (-item[0], item[2]))
    out = []
    for rank, (sim, layer, mid, row) in enumerate(scored[:k], start=1):
        out.append({"memoryId": mid, "rank": rank, "layer": layer, "lane": "work",
                    "contentDigest": content_digest(row.get("content", "")), "similarity": sim})
    return out


class PublisherDaemon:
    def __init__(self, publishers: dict[str, PublisherStore], socket_path: Path, embeddings):
        self.publishers = publishers
        self.socket_path = Path(socket_path)
        self.embeddings = embeddings
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._ready = threading.Event()

    def _request(self, frame: dict, action: str) -> PolicyRequest:
        at = datetime.fromisoformat(str(frame.get("at", _now())).replace("Z", "+00:00"))
        return PolicyRequest(
            publisher=f"urn:engram:{frame['receiver']}", profile=PROFILE, domain=DOMAIN,
            action=action, context_id=frame["context"]["id"], claim_type=CLAIM_TYPE,
            purpose=frame["purpose"], audience=frame.get("audience", "self"),
            at=at if at.tzinfo else at.replace(tzinfo=timezone.utc))

    def handle_frame(self, frame: dict) -> dict:
        try:
            pub = self.publishers.get(frame.get("publisher"))
            if pub is None or not pub.db_path.is_file() or not pub.open():
                if pub is not None:
                    pub.reset()
                return error_frame("PUBLISHER_UNAVAILABLE", "no such publisher or store unavailable")
            if frame["kind"] == "recall":
                return self._recall(pub, frame)
            if frame["kind"] == "read":
                return self._read(pub, frame)
            return error_frame("MALFORMED_FRAME", f"unexpected kind {frame['kind']}")
        except KeyError as error:
            return error_frame("MALFORMED_FRAME", f"missing {error}")
        except Exception:
            logger.warning("frame handling failed", exc_info=True)
            return error_frame("PUBLISHER_UNAVAILABLE", "internal failure")

    def _recall(self, pub: PublisherStore, frame: dict) -> dict:
        decision = pub.policy.decide(self._request(frame, "recall"))
        turn_id = str(uuid.uuid4())
        candidates: list[dict] = []
        if decision.effect == "allow":
            candidates = retrieve(pub.storage, self.embeddings, frame["query"], int(frame["k"]))
        disclosure_id = pub.record_disclosure({
            "receiver": frame["receiver"], "action": "recall", "context_id": frame["context"]["id"],
            "purpose": frame["purpose"], "effect": decision.effect, "rule_id": decision.rule_id,
            "code": decision.code, "memory_ids": [c["memoryId"] for c in candidates]})
        return recall_result_frame(
            turn_id=turn_id, query_digest=content_digest(frame["query"]), context=frame["context"],
            candidates=[{k: v for k, v in c.items() if k != "similarity"} for c in candidates],
            decision=decision.to_json(), disclosure_id=disclosure_id)

    def _read(self, pub: PublisherStore, frame: dict) -> dict:
        decision = pub.policy.decide(self._request(frame, "read"))
        items = []
        delivered: list[str] = []
        for mid in frame["memoryIds"]:
            content = None
            if decision.effect == "allow":
                row = pub.storage.get_episode(mid) or pub.storage.get_semantic(mid)
                if row is not None and (row.get("lane") or "personal") == "work":
                    content = row.get("content", "")
                    delivered.append(mid)
            items.append({"memoryId": mid, "content": content, "decision": decision.to_json()})
        disclosure_id = pub.record_disclosure({
            "receiver": frame["receiver"], "action": "read", "context_id": frame["context"]["id"],
            "purpose": frame["purpose"], "effect": decision.effect, "rule_id": decision.rule_id,
            "code": decision.code, "memory_ids": delivered})
        return read_result_frame(items=items, disclosure_id=disclosure_id)

    def serve_forever(self) -> None:
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                for line in self.rfile:
                    try:
                        frame = decode(line)
                    except FrameError as error:
                        self.wfile.write(encode(error_frame(error.code, "")))
                        continue
                    self.wfile.write(encode(daemon.handle_frame(frame)))
                    self.wfile.flush()

        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = socketserver.ThreadingUnixStreamServer(str(self.socket_path), Handler)
        self._server.daemon_threads = True
        os.chmod(self.socket_path, 0o600)
        self._ready.set()
        try:
            self._server.serve_forever(poll_interval=0.2)
        finally:
            self._ready.clear()

    def wait_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self.socket_path.exists():
            self.socket_path.unlink()
        for pub in self.publishers.values():
            pub.reset()


def load_daemon_config(path: Path) -> dict:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    publishers = raw.get("publishers")
    if not isinstance(publishers, list) or not all(isinstance(p, str) and p for p in publishers):
        raise ValueError("config needs a non-empty publishers list")
    return {"publishers": publishers, "socket": raw.get("socket")}


def build_publishers(engram_home: Path, names: list[str]) -> dict[str, PublisherStore]:
    out = {}
    for name in names:
        inst = engram_home / ".engram" / "instances" / name
        out[name] = PublisherStore(name=name, db_path=inst / "graph.db",
                                   policy_path=inst / "lighthouse-policy.json",
                                   disclosures_path=inst / "lighthouse-disclosures.db")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lighthouse_daemon")
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket")
    args = parser.parse_args(argv)
    engram_home = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent))
    config = load_daemon_config(Path(args.config))
    socket_path = Path(args.socket or config["socket"] or engram_home / ".engram" / "lighthouse.sock")
    from embeddings import NomicEmbedProvider
    daemon = PublisherDaemon(build_publishers(engram_home, config["publishers"]), socket_path,
                             NomicEmbedProvider())
    logging.basicConfig(level=os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
    logger.info("publishing %s on %s", ", ".join(config["publishers"]), socket_path)
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note: `vec0_distance_to_similarity` is imported from `storage` (it lives at `storage.py:27`); if it is defined under a different name there, import that name instead of redefining it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_daemon.py -q`
Expected: 10 passed

- [ ] **Step 5: Register and commit**

Add `"lighthouse_daemon",` to `py-modules` in `pyproject.toml`.

```bash
git add lighthouse_daemon.py tests/test_lighthouse_daemon.py pyproject.toml
git commit -m "feat: add read-only Lighthouse publisher daemon"
```

---

### Task 6: Receipts with vendored schema

**Files:**
- Create: `schemas/lighthouse/recall-receipt.schema.json`
- Create: `lighthouse_receipts.py`
- Modify: `pyproject.toml` (add `"jsonschema>=4.23"` to `dependencies`, add module to `py-modules`)
- Test: `tests/test_lighthouse_receipts.py`

**Interfaces:**
- Produces:
  - `build_receipt(*, receiver: str, turn_id: str, context: dict, purpose: str, sources: list[dict], selected: list[dict], delivered: list[dict], receiver_rule: str | None, issued_at: str | None = None) -> dict` returning a sealed `RecallReceipt` artifact (envelope + `digest`), with `payload.injected = len(delivered) > 0`.
  - `validate_receipt(receipt: dict) -> None` raising `ReceiptError(code)` with `SCHEMA_INVALID`, `DIGEST_MISMATCH`, `INJECTED_MISMATCH`.
  - `write_receipt(storage, receipt: dict, *, session_id: str | None, recall_id: str) -> str` writing `memory_log` event `lighthouse_receipt`, layer `all`, `target_ids = ["<publisher>:<memoryId>", ...]` for delivered items, `context = {"recall_id", "session_id", "receipt": receipt}`; returns the receipt `id`.

- [ ] **Step 1: Write the vendored schema**

`schemas/lighthouse/recall-receipt.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["protocolVersion", "kind", "id", "issuedAt", "issuer", "payloadMediaType", "payload", "digest"],
  "properties": {
    "protocolVersion": {"const": "0.1"},
    "kind": {"const": "RecallReceipt"},
    "id": {"type": "string", "minLength": 1},
    "issuedAt": {"type": "string", "minLength": 20},
    "issuer": {"type": "string", "minLength": 1},
    "payloadMediaType": {"const": "application/vnd.lighthouse.recall-receipt+json"},
    "attestations": {"type": "array"},
    "extensions": {"type": "object"},
    "digest": {"$ref": "#/$defs/digest"},
    "payload": {
      "type": "object",
      "additionalProperties": false,
      "required": ["turnId", "context", "purpose", "audience", "action", "injected", "transformation", "receiverRule", "sources", "selected", "delivered"],
      "properties": {
        "turnId": {"type": "string", "minLength": 1},
        "context": {"$ref": "#/$defs/context"},
        "purpose": {"type": "string", "minLength": 1},
        "audience": {"const": "self"},
        "action": {"const": "recall"},
        "injected": {"type": "boolean"},
        "transformation": {"const": "weighted-rrf-v1"},
        "receiverRule": {"type": "object", "additionalProperties": false,
          "required": ["ruleId"], "properties": {"ruleId": {"type": ["string", "null"]}}},
        "sources": {"type": "array", "items": {"$ref": "#/$defs/source"}},
        "selected": {"type": "array", "items": {"$ref": "#/$defs/selected"}},
        "delivered": {"type": "array", "items": {"$ref": "#/$defs/delivered"}}
      }
    }
  },
  "$defs": {
    "digest": {"type": "object", "additionalProperties": false, "required": ["algorithm", "value"],
      "properties": {"algorithm": {"type": "string", "minLength": 1}, "value": {"type": "string", "minLength": 1}}},
    "context": {"type": "object", "additionalProperties": false, "required": ["id", "path"],
      "properties": {"id": {"type": "string", "minLength": 1},
        "path": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}}},
    "decision": {"type": "object", "additionalProperties": false, "required": ["effect", "ruleId", "code"],
      "properties": {"effect": {"enum": ["allow", "deny"]}, "ruleId": {"type": ["string", "null"]}, "code": {"type": ["string", "null"]}}},
    "source": {"type": "object", "additionalProperties": false,
      "required": ["publisher", "role", "weight", "storeDigest", "policyDecision", "traceOutcome"],
      "properties": {"publisher": {"type": "string", "minLength": 1}, "role": {"enum": ["local", "remote"]},
        "weight": {"type": "number", "minimum": 0}, "storeDigest": {"$ref": "#/$defs/digest"},
        "policyDecision": {"$ref": "#/$defs/decision"},
        "traceOutcome": {"enum": ["matched", "absent", "context-mismatched", "unavailable", "policy-denied"]}}},
    "selected": {"type": "object", "additionalProperties": false,
      "required": ["publisher", "memoryId", "contentDigest", "score", "contributions"],
      "properties": {"publisher": {"type": "string", "minLength": 1}, "memoryId": {"type": "string", "minLength": 1},
        "contentDigest": {"$ref": "#/$defs/digest"}, "score": {"type": "number"},
        "contributions": {"type": "array", "items": {"type": "object", "additionalProperties": false,
          "required": ["publisher", "rank"], "properties": {"publisher": {"type": "string"}, "rank": {"type": "integer", "minimum": 1}}}}}},
    "delivered": {"type": "object", "additionalProperties": false,
      "required": ["publisher", "memoryId", "readDecision"],
      "properties": {"publisher": {"type": "string", "minLength": 1}, "memoryId": {"type": "string", "minLength": 1},
        "readDecision": {"$ref": "#/$defs/decision"}}}
  }
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_lighthouse_receipts.py
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from lighthouse_protocol import content_digest
from lighthouse_receipts import ReceiptError, build_receipt, validate_receipt, write_receipt
from storage import Storage

CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
ALLOW = {"effect": "allow", "ruleId": "r1", "code": None}


def sample(delivered=True) -> dict:
    return build_receipt(
        receiver="engram", turn_id="turn-1", context=CONTEXT, purpose="session-recall",
        sources=[{"publisher": "urn:engram:why", "role": "remote", "weight": 1.0,
                  "storeDigest": content_digest("store"), "policyDecision": ALLOW,
                  "traceOutcome": "matched"}],
        selected=[{"publisher": "urn:engram:why", "memoryId": "m1", "contentDigest": content_digest("x"),
                   "score": 1 / 61, "contributions": [{"publisher": "urn:engram:why", "rank": 1}]}],
        delivered=[{"publisher": "urn:engram:why", "memoryId": "m1", "readDecision": ALLOW}] if delivered else [],
        receiver_rule="allow-why", issued_at="2026-09-01T00:00:00+00:00")


def test_build_receipt_is_sealed_and_valid():
    receipt = sample()
    assert receipt["kind"] == "RecallReceipt" and receipt["issuer"] == "urn:engram:engram"
    assert receipt["payload"]["injected"] is True
    validate_receipt(receipt)


def test_injected_false_when_nothing_delivered():
    receipt = sample(delivered=False)
    assert receipt["payload"]["injected"] is False
    validate_receipt(receipt)


def test_validate_rejects_unknown_member_and_injected_mismatch():
    receipt = sample()
    receipt["payload"]["extra"] = 1
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "SCHEMA_INVALID"
    receipt = sample()
    receipt["payload"]["injected"] = False
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "DIGEST_MISMATCH"


def test_validate_rejects_injected_mismatch_with_fresh_digest():
    from lighthouse_protocol import artifact_digest
    receipt = sample()
    receipt["payload"]["injected"] = False
    receipt["digest"] = artifact_digest(receipt)
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "INJECTED_MISMATCH"


def test_write_receipt_logs_without_content(tmp_path):
    store = Storage(str(tmp_path / "graph.db"))
    receipt = sample()
    rid = write_receipt(store, receipt, session_id="s1", recall_id="rc1")
    row = store.conn.execute(
        "SELECT layer, target_ids, context FROM memory_log WHERE event_type='lighthouse_receipt'").fetchone()
    assert row["layer"] == "all"
    assert json.loads(row["target_ids"]) == ["urn:engram:why:m1"]
    ctx = json.loads(row["context"])
    assert ctx["recall_id"] == "rc1" and ctx["receipt"]["id"] == rid
    assert "content" not in json.dumps(ctx["receipt"]["payload"]["selected"])
    store.close()


def test_decisions_serialize_with_explicit_nulls_and_store_digest_shape():
    """L1's policyDecision/readDecision always carry ruleId and code (null when
    absent) so canonical JSON matches across Python and TypeScript. json.dumps
    is never called with a None-dropping filter anywhere in the receipt path."""
    from lighthouse_policy import Decision
    from lighthouse_protocol import canonical_json
    assert '"code":null' in canonical_json(Decision("allow", "r1", None).to_json())
    assert '"ruleId":null' in canonical_json(Decision("deny", None, "NO_MATCHING_ALLOW").to_json())
    assert Decision("deny", "d1", "EXPLICIT_DENY").to_json()["ruleId"] == "d1"
    receipt = sample()
    for source in receipt["payload"]["sources"]:
        assert set(source["policyDecision"]) == {"effect", "ruleId", "code"}
        assert source["storeDigest"]["algorithm"] == "sha256"
        assert re.fullmatch(r"[0-9a-f]{64}", source["storeDigest"]["value"])
    for item in receipt["payload"]["delivered"]:
        assert set(item["readDecision"]) == {"effect", "ruleId", "code"}
    assert '"code":null' in canonical_json(receipt)


def test_vendored_schema_matches_lighthouse_when_present():
    kit = Path("/Users/kairos/Projects/lighthouse/schemas/recall-receipt.schema.json")
    if not kit.exists():
        pytest.skip("lighthouse checkout or schema not present")
    ours = json.loads(Path("schemas/lighthouse/recall-receipt.schema.json").read_text())
    assert ours == json.loads(kit.read_text())
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_receipts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lighthouse_receipts'`

- [ ] **Step 4: Add the dependency and implement**

Add `"jsonschema>=4.23",` to `dependencies` in `pyproject.toml`, then `.venv/bin/pip install -e .` (or `uv pip install -e .` if that is how this venv is managed).

```python
# lighthouse_receipts.py
"""Recall receipts: the record that neighbor material entered a mind.

A receipt is a sealed Lighthouse artifact. ``injected`` is true exactly when
something was delivered; the schema is strict (unknown members rejected);
receipts never carry query text or memory content.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from lighthouse_protocol import artifact_digest, verify_artifact_digest
from resources import resource_path

MEDIA_TYPE = "application/vnd.lighthouse.recall-receipt+json"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "lighthouse" / "recall-receipt.schema.json"
_VALIDATOR = jsonschema.Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


class ReceiptError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def build_receipt(*, receiver: str, turn_id: str, context: dict, purpose: str,
                  sources: list[dict], selected: list[dict], delivered: list[dict],
                  receiver_rule: str | None, issued_at: str | None = None) -> dict:
    receipt = {
        "protocolVersion": "0.1",
        "kind": "RecallReceipt",
        "id": f"urn:engram:{receiver}:receipt:{uuid.uuid4()}",
        "issuedAt": issued_at or datetime.now(timezone.utc).isoformat(),
        "issuer": f"urn:engram:{receiver}",
        "payloadMediaType": MEDIA_TYPE,
        "payload": {
            "turnId": turn_id,
            "context": {"id": context["id"], "path": list(context["path"])},
            "purpose": purpose,
            "audience": "self",
            "action": "recall",
            "injected": len(delivered) > 0,
            "transformation": "weighted-rrf-v1",
            "receiverRule": {"ruleId": receiver_rule},
            "sources": sources,
            "selected": selected,
            "delivered": delivered,
        },
    }
    receipt["digest"] = artifact_digest(receipt)
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict) -> None:
    errors = list(_VALIDATOR.iter_errors(receipt))
    if errors:
        raise ReceiptError("SCHEMA_INVALID")
    if not verify_artifact_digest(receipt):
        raise ReceiptError("DIGEST_MISMATCH")
    payload = receipt["payload"]
    if payload["injected"] != (len(payload["delivered"]) > 0):
        raise ReceiptError("INJECTED_MISMATCH")


def write_receipt(storage, receipt: dict, *, session_id: str | None, recall_id: str) -> str:
    validate_receipt(receipt)
    targets = [f"{d['publisher']}:{d['memoryId']}" for d in receipt["payload"]["delivered"]]
    storage.add_log_entry(
        id=str(uuid.uuid4()), event_type="lighthouse_receipt", layer="all", target_ids=targets,
        context={"recall_id": recall_id, "session_id": session_id, "receipt": receipt})
    return receipt["id"]
```

If `resources.resource_path` is the project's way to locate packaged files (it is used by `storage.py` for migrations), replace `_SCHEMA_PATH` with `resource_path("schemas") / "lighthouse" / "recall-receipt.schema.json"` and add `schemas/**` to the package data in `pyproject.toml` the same way `migrations` is included; otherwise keep the `__file__`-relative path and delete the unused `resource_path` import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_receipts.py -q`
Expected: 7 passed (the schema-sync test skips until L1 lands)

- [ ] **Step 6: Register and commit**

Add `"lighthouse_receipts",` to `py-modules`.

```bash
git add lighthouse_receipts.py schemas/lighthouse/recall-receipt.schema.json tests/test_lighthouse_receipts.py pyproject.toml
git commit -m "feat: add Lighthouse recall receipts with strict schema"
```

---

### Task 7: Receiver arm

**Files:**
- Create: `neighbors.py`
- Test: `tests/test_neighbors.py`

**Interfaces:**
- Consumes: frames (Task 4), `load_policy`/`PolicyRequest` (Task 3), `build_receipt`/`write_receipt` (Task 6).
- Produces:
  - `class LighthouseClient(socket_path: Path, timeout_s: float = 2.0)` with `.call(frame: dict) -> dict` raising `NeighborUnavailable` on connect/timeout/frame errors.
  - `fuse_traces(traces: dict[str, tuple[float, list[dict]]], k: int) -> list[dict]` where the key is the publisher id and the value is `(weight, candidates)`; returns selected entries `{publisher, memoryId, contentDigest, score, contributions}` sorted by score descending then canonical identity; raises `ValueError("CONFLICTING_DIGEST")` if the same `(publisher, memoryId)` appears with two digests.
  - `neighbor_arm(*, query, context, purpose, k, storage, session_id, recall_id, receiver, socket_path, policy_path, timeout_s=2.0, now=None) -> dict | None`.
  - Receiver-side policy: rules whose `publishers` name a `urn:engram:<name>`; weight from `extensions["engram:weight"]` on the policy artifact keyed by publisher, default `1.0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_neighbors.py
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lighthouse_daemon import PublisherDaemon, PublisherStore
from lighthouse_protocol import artifact_digest, content_digest
from neighbors import NeighborUnavailable, fuse_traces, neighbor_arm
from storage import Storage
from tests.test_lighthouse_daemon import FakeEmbeddings, build_publisher, unit

CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def write_receiver_policy(path: Path, publishers=("why",), actions=("recall", "read", "inject_context"),
                          weights=None) -> None:
    rules = [{
        "id": f"allow-{p}", "effect": "allow", "publishers": [f"urn:engram:{p}"],
        "profiles": ["urn:lighthouse:profile:engram-recall-trace"], "domains": ["memory.recall"],
        "actions": list(actions), "contexts": ["memory/technical"],
        "claimMediaTypes": ["application/vnd.engram.recall-rank-claim+json"],
        "purposes": ["session-recall"], "audiences": ["self"],
        "validFrom": "2026-01-01T00:00:00Z", "validUntil": "2027-01-01T00:00:00Z",
        "requiredEvidence": [], "requiredAttestations": []} for p in publishers]
    artifact = {
        "kind": "ConnectionPolicy", "protocolVersion": "0.1", "id": "urn:policy:engram",
        "issuedAt": "2026-09-01T00:00:00Z", "issuer": "urn:engram:engram",
        "payloadMediaType": "application/vnd.lighthouse.connection-policy+json",
        "payload": {"rules": rules},
        "extensions": {"engram:weight": {f"urn:engram:{p}": w for p, w in (weights or {}).items()}},
    }
    artifact["digest"] = artifact_digest(artifact)
    path.write_text(json.dumps(artifact))


@pytest.fixture
def city(tmp_path):
    pub = build_publisher(tmp_path, "why")
    receiver_dir = tmp_path / ".engram" / "instances" / "engram"
    receiver_dir.mkdir(parents=True)
    write_receiver_policy(receiver_dir / "lighthouse-policy.json")
    store = Storage(str(receiver_dir / "graph.db"))
    sock = tmp_path / ".engram" / "lighthouse.sock"
    daemon = PublisherDaemon({"why": pub}, sock, FakeEmbeddings())
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    daemon.wait_ready(5)
    yield {"store": store, "sock": sock, "policy": receiver_dir / "lighthouse-policy.json",
           "daemon": daemon, "pub": pub}
    daemon.stop()
    thread.join(5)
    store.close()


def test_fuse_traces_weighted_rrf_and_conflict():
    d1, d2 = content_digest("a"), content_digest("b")
    traces = {
        "urn:engram:why": (1.0, [{"memoryId": "m1", "rank": 1, "contentDigest": d1},
                                 {"memoryId": "m2", "rank": 2, "contentDigest": d2}]),
        "urn:engram:blocks": (2.0, [{"memoryId": "m9", "rank": 1, "contentDigest": d1}]),
    }
    fused = fuse_traces(traces, k=3)
    assert [f["memoryId"] for f in fused] == ["m9", "m1", "m2"]
    assert fused[0]["score"] == pytest.approx(2.0 / 61)
    assert fused[1]["contributions"] == [{"publisher": "urn:engram:why", "rank": 1}]
    with pytest.raises(ValueError, match="CONFLICTING_DIGEST"):
        fuse_traces({"urn:engram:why": (1.0, [{"memoryId": "m1", "rank": 1, "contentDigest": d1},
                                              {"memoryId": "m1", "rank": 2, "contentDigest": d2}])}, k=2)


def test_neighbor_arm_delivers_and_writes_receipt(city):
    out = neighbor_arm(query="work: rivers need bridges", context=CONTEXT, purpose="session-recall", k=3,
                       storage=city["store"], session_id="s", recall_id="r1", receiver="engram",
                       socket_path=city["sock"], policy_path=city["policy"], now=NOW)
    assert out["degraded"] is False
    assert len(out["delivered"]) == 1
    assert out["delivered"][0]["content"] == "work: rivers need bridges"
    assert out["delivered"][0]["publisher"] == "urn:engram:why"
    row = city["store"].conn.execute(
        "SELECT context FROM memory_log WHERE event_type='lighthouse_receipt'").fetchone()
    receipt = json.loads(row["context"])["receipt"]
    assert receipt["id"] == out["receipt_id"] and receipt["payload"]["injected"] is True
    assert receipt["payload"]["sources"][0]["traceOutcome"] == "matched"


def test_neighbor_arm_without_inject_context_delivers_nothing(city):
    write_receiver_policy(city["policy"], actions=("recall", "read"))
    out = neighbor_arm(query="work: rivers need bridges", context=CONTEXT, purpose="session-recall", k=3,
                       storage=city["store"], session_id="s", recall_id="r2", receiver="engram",
                       socket_path=city["sock"], policy_path=city["policy"], now=NOW)
    assert out["selected"] and out["delivered"] == []
    receipt = json.loads(city["store"].conn.execute(
        "SELECT context FROM memory_log WHERE event_type='lighthouse_receipt'").fetchone()["context"])["receipt"]
    assert receipt["payload"]["injected"] is False


def test_neighbor_arm_returns_none_without_policy(city):
    city["policy"].unlink()
    assert neighbor_arm(query="x", context=CONTEXT, purpose="session-recall", k=3, storage=city["store"],
                        session_id="s", recall_id="r3", receiver="engram", socket_path=city["sock"],
                        policy_path=city["policy"], now=NOW) is None
    assert city["store"].conn.execute("SELECT COUNT(*) FROM memory_log WHERE event_type='lighthouse_receipt'").fetchone()[0] == 0


def test_neighbor_arm_degrades_when_daemon_down(city):
    city["daemon"].stop()
    out = neighbor_arm(query="x", context=CONTEXT, purpose="session-recall", k=3, storage=city["store"],
                       session_id="s", recall_id="r4", receiver="engram", socket_path=city["sock"],
                       policy_path=city["policy"], now=NOW)
    assert out["degraded"] is True and out["delivered"] == []
    receipt = json.loads(city["store"].conn.execute(
        "SELECT context FROM memory_log WHERE event_type='lighthouse_receipt'").fetchone()["context"])["receipt"]
    assert receipt["payload"]["sources"][0]["traceOutcome"] == "unavailable"


def test_neighbor_arm_never_raises(city, monkeypatch):
    import neighbors
    monkeypatch.setattr(neighbors, "fuse_traces", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = neighbor_arm(query="work: rivers need bridges", context=CONTEXT, purpose="session-recall", k=3,
                       storage=city["store"], session_id="s", recall_id="r5", receiver="engram",
                       socket_path=city["sock"], policy_path=city["policy"], now=NOW)
    assert out["degraded"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_neighbors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'neighbors'`

- [ ] **Step 3: Implement**

```python
# neighbors.py
"""Receiver arm of the Lighthouse local city.

Called once from recall() after local results are final. Consults the
receiver's own policy for which publishers to ask, fetches opaque traces
over the daemon socket, fuses them by weighted reciprocal rank (constant
60, publisher-qualified identity), requests content only under an
inject_context grant, writes a receipt, and returns a payload that recall()
attaches under the separate ``neighbors`` key. Never raises.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lighthouse_policy import PolicyError, PolicyRequest, load_policy
from lighthouse_protocol import FrameError, canonical_json, decode, encode, read_frame, recall_frame
from lighthouse_receipts import build_receipt, write_receipt

logger = logging.getLogger("engram.neighbors")

RRF_K = 60
PROFILE = "urn:lighthouse:profile:engram-recall-trace"
DOMAIN = "memory.recall"
CLAIM_TYPE = "application/vnd.engram.recall-rank-claim+json"


class NeighborUnavailable(RuntimeError):
    pass


class LighthouseClient:
    def __init__(self, socket_path: Path, timeout_s: float = 2.0):
        self.socket_path = Path(socket_path)
        self.timeout_s = timeout_s

    def call(self, frame: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout_s)
                sock.connect(str(self.socket_path))
                sock.sendall(encode(frame))
                line = sock.makefile("rb").readline()
            if not line:
                raise NeighborUnavailable("empty reply")
            return decode(line)
        except (OSError, FrameError) as error:
            raise NeighborUnavailable(str(error)) from error


def fuse_traces(traces: dict[str, tuple[float, list[dict]]], k: int) -> list[dict]:
    scores: dict[tuple[str, str], dict] = {}
    for publisher, (weight, candidates) in traces.items():
        for cand in candidates:
            key = (publisher, cand["memoryId"])
            entry = scores.setdefault(key, {
                "publisher": publisher, "memoryId": cand["memoryId"],
                "contentDigest": cand["contentDigest"], "score": 0.0, "contributions": []})
            if entry["contentDigest"] != cand["contentDigest"]:
                raise ValueError("CONFLICTING_DIGEST")
            if weight > 0:
                entry["score"] += weight / (RRF_K + int(cand["rank"]))
                entry["contributions"].append({"publisher": publisher, "rank": int(cand["rank"])})
    fused = [e for e in scores.values() if e["score"] > 0]
    fused.sort(key=lambda e: (-e["score"], canonical_json([e["publisher"], e["memoryId"]])))
    return fused[:k]


def _publishers_for(policy, req_base: dict, now: datetime) -> list[tuple[str, float, str | None]]:
    """Publishers the receiver policy allows `recall` from, with weights and the rule that matched."""
    weights = (policy.artifact.get("extensions") or {}).get("engram:weight") or {}
    out = []
    seen = set()
    for rule in policy.rules:
        for pub in rule["publishers"]:
            if pub in seen or pub.endswith("*") or not pub.startswith("urn:engram:"):
                continue
            seen.add(pub)
            decision = policy.decide(PolicyRequest(publisher=pub, action="recall", at=now, **req_base))
            if decision.effect == "allow":
                out.append((pub, float(weights.get(pub, 1.0)), decision.rule_id))
    return out


def neighbor_arm(*, query: str, context: dict, purpose: str, k: int, storage, session_id: str | None,
                 recall_id: str, receiver: str, socket_path: Path, policy_path: Path,
                 timeout_s: float = 2.0, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    try:
        policy = load_policy(policy_path)
    except PolicyError:
        return None
    req_base = {"profile": PROFILE, "domain": DOMAIN, "context_id": context["id"],
                "claim_type": CLAIM_TYPE, "purpose": purpose, "audience": "self"}
    publishers = _publishers_for(policy, req_base, now)
    if not publishers:
        return None

    sources: list[dict] = []
    traces: dict[str, tuple[float, list[dict]]] = {}
    selected: list[dict] = []
    delivered: list[dict] = []
    degraded = False
    client = LighthouseClient(socket_path, timeout_s)
    receiver_rule = publishers[0][2]
    try:
        for pub_id, weight, _rule in publishers:
            name = pub_id.split(":")[-1]
            source = {"publisher": pub_id, "role": "remote", "weight": weight,
                      "storeDigest": {"algorithm": "sha256", "value": "0" * 64},
                      "policyDecision": {"effect": "deny", "ruleId": None, "code": None},
                      "traceOutcome": "unavailable"}
            try:
                reply = client.call(recall_frame(receiver=receiver, publisher=name, context=context,
                                                 purpose=purpose, query=query, k=k, at=now.isoformat()))
            except NeighborUnavailable:
                degraded = True
                sources.append(source)
                continue
            if reply["kind"] != "recall_result":
                degraded = True
                sources.append(source)
                continue
            source["policyDecision"] = reply["decision"]
            if reply["decision"]["effect"] != "allow":
                source["traceOutcome"] = "policy-denied"
            elif reply["context"]["id"] != context["id"]:
                source["traceOutcome"] = "context-mismatched"
            elif not reply["candidates"]:
                source["traceOutcome"] = "absent"
            else:
                source["traceOutcome"] = "matched"
                traces[pub_id] = (weight, reply["candidates"])
            source["_turn"] = reply["turnId"]
            sources.append(source)

        selected = fuse_traces(traces, k) if traces else []

        for pub_id, weight, _rule in publishers:
            wanted = [s["memoryId"] for s in selected if s["publisher"] == pub_id]
            if not wanted:
                continue
            inject = policy.decide(PolicyRequest(publisher=pub_id, action="inject_context", at=now, **req_base))
            if inject.effect != "allow":
                continue
            source = next(s for s in sources if s["publisher"] == pub_id)
            name = pub_id.split(":")[-1]
            try:
                reply = client.call(read_frame(receiver=receiver, publisher=name, context=context,
                                               purpose=purpose, turn_id=source.get("_turn", ""), memory_ids=wanted))
            except NeighborUnavailable:
                degraded = True
                continue
            if reply["kind"] != "read_result":
                degraded = True
                continue
            for item in reply["items"]:
                if item["content"] is not None:
                    delivered.append({"publisher": pub_id, "memoryId": item["memoryId"],
                                      "readDecision": item["decision"], "content": item["content"]})
    except Exception:
        logger.warning("neighbor arm failed (non-fatal)", exc_info=True)
        degraded = True

    for source in sources:
        source.pop("_turn", None)
    receipt_delivered = [{k2: v for k2, v in d.items() if k2 != "content"} for d in delivered]
    receipt_id = None
    try:
        receipt = build_receipt(receiver=receiver, turn_id=recall_id, context=context, purpose=purpose,
                                sources=sources, selected=selected, delivered=receipt_delivered,
                                receiver_rule=receiver_rule)
        receipt_id = write_receipt(storage, receipt, session_id=session_id, recall_id=recall_id)
    except Exception:
        logger.warning("receipt write failed (non-fatal)", exc_info=True)
        degraded = True

    return {"receipt_id": receipt_id, "sources": sources, "selected": selected,
            "delivered": delivered, "degraded": degraded}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_neighbors.py -q`
Expected: 6 passed

- [ ] **Step 5: Register and commit**

Add `"neighbors",` to `py-modules`.

```bash
git add neighbors.py tests/test_neighbors.py pyproject.toml
git commit -m "feat: add Lighthouse receiver arm with RRF fusion and receipts"
```

---

### Task 8: The call site in `recall()`

**Files:**
- Modify: `server.py` (inside `recall()`, between `results = _observe_category_recall(query, results, recall_id)` at line 2332 and `return response`; plus one module-level helper placed next to `_has_active_residue`)
- Test: `tests/test_recall_neighbors.py`

**Interfaces:**
- Consumes: `neighbors.neighbor_arm`.
- Produces: `response["neighbors"]` (payload from Task 7 minus the `degraded` flag), `"neighbors"` appended to `search_errors` when degraded; module helper `_neighbor_paths() -> tuple[Path, Path] | None` returning `(socket_path, policy_path)` or `None` when no instance is bound.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recall_neighbors.py
"""The single call site: recall() gains a `neighbors` key and nothing else changes."""
from __future__ import annotations

import json
import threading

import pytest

import server
from lighthouse_daemon import PublisherDaemon
from tests.test_lighthouse_daemon import FakeEmbeddings, build_publisher
from tests.test_neighbors import write_receiver_policy
from tests.test_recall_margins import engram_server_env, seed  # noqa: F401  (fixture reuse)


@pytest.fixture
def local_city(engram_server_env, tmp_path):
    pub = build_publisher(tmp_path, "why")
    receiver_dir = tmp_path / ".engram" / "instances" / "engram"
    receiver_dir.mkdir(parents=True, exist_ok=True)
    write_receiver_policy(receiver_dir / "lighthouse-policy.json")
    seed()
    server._instance_name = "engram"
    daemon = PublisherDaemon({"why": pub}, tmp_path / ".engram" / "lighthouse.sock", FakeEmbeddings())
    thread = threading.Thread(target=daemon.serve_forever, daemon=True)
    thread.start()
    daemon.wait_ready(5)
    yield daemon
    daemon.stop()
    thread.join(5)


def test_neighbors_key_absent_without_instance(engram_server_env):
    seed()
    out = server.recall(query="rivers and mapping", uninvited=0)
    assert "neighbors" not in out and "degraded" not in out


def test_neighbors_delivered_separately_from_results(local_city):
    out = server.recall(query="work: rivers need bridges", uninvited=0)
    assert "neighbors" in out
    delivered_ids = {d["memoryId"] for d in out["neighbors"]["delivered"]}
    assert delivered_ids and delivered_ids.isdisjoint({r["id"] for r in out["results"]})
    assert "degraded" not in out
    assert out["margin"]["n"] >= 2


def test_daemon_down_degrades_and_leaves_local_result_identical(local_city):
    baseline = server.recall(query="rivers and mapping", uninvited=0)
    local_city.stop()
    out = server.recall(query="rivers and mapping", uninvited=0)
    assert "neighbors" in out["degraded"]
    assert [r["id"] for r in out["results"]] == [r["id"] for r in baseline["results"]]
    assert out["margin"]["top"] == pytest.approx(baseline["margin"]["top"])


def test_receipt_logged_for_the_recall(local_city):
    out = server.recall(query="work: rivers need bridges", uninvited=0)
    row = server._storage.conn.execute(
        "SELECT context FROM memory_log WHERE event_type='lighthouse_receipt' "
        "AND json_extract(context, '$.recall_id') = ?", (out["recall_id"],)).fetchone()
    assert row is not None
    assert json.loads(row["context"])["receipt"]["payload"]["injected"] is True


def test_arm_exception_never_breaks_recall(local_city, monkeypatch):
    monkeypatch.setattr(server.neighbors, "neighbor_arm", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = server.recall(query="rivers and mapping", uninvited=0)
    assert out["results"] and "neighbors" in out["degraded"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recall_neighbors.py -q`
Expected: FAIL with `AttributeError: module 'server' has no attribute 'neighbors'` (or `KeyError: 'neighbors'`)

- [ ] **Step 3: Implement**

At the top of `server.py`, with the other first-party imports:

```python
import neighbors
```

Next to `_has_active_residue()`:

```python
def _neighbor_paths() -> tuple[Path, Path] | None:
    """Socket and receiver-policy paths for the bound instance, or None."""
    if not _instance_name:
        return None
    socket_path = Path(os.environ.get("ENGRAM_LIGHTHOUSE_SOCKET",
                                      ENGRAM_HOME / ".engram" / "lighthouse.sock"))
    policy_path = ENGRAM_HOME / ".engram" / "instances" / _instance_name / "lighthouse-policy.json"
    return socket_path, policy_path
```

In `recall()`, replace the block from `results = _observe_category_recall(query, results, recall_id)` through `response["degraded"] = search_errors` with:

```python
    results = _observe_category_recall(query, results, recall_id)
    if margin is not None and results and results[0]["id"] != delivered_top:
        margin["influenced"] = True

    # Lighthouse neighbors: perspective from other stores, delivered under
    # their own key. Never merged into results; never allowed to raise.
    neighbors_payload = None
    paths = _neighbor_paths()
    if paths is not None:
        try:
            neighbors_payload = neighbors.neighbor_arm(
                query=query,
                context={"id": "memory/technical", "path": ["memory", "technical"]},
                purpose="session-recall", k=max_results, storage=_storage,
                session_id=_session_id, recall_id=recall_id, receiver=_instance_name,
                socket_path=paths[0], policy_path=paths[1])
        except Exception:
            logger.warning("Neighbor arm failed (non-fatal)", exc_info=True)
            neighbors_payload = {"degraded": True}
        if neighbors_payload and neighbors_payload.get("degraded"):
            search_errors.append("neighbors")

    response = {"results": results, "recall_id": recall_id}
    if margin is not None and not _residue_active:
        response["margin"] = margin
    if resonant_results:
        response["resonant"] = resonant_results
    if transfers:
        response["transfers"] = transfers
    if _residue_active:
        response["dreaming"] = True
        response["note"] = "Scores hidden — some memories may be dream-pulled. Use dream_verify(recall_id) after engaging."
    if search_errors:
        response["degraded"] = search_errors
    if neighbors_payload and "receipt_id" in neighbors_payload:
        response["neighbors"] = {k: v for k, v in neighbors_payload.items() if k != "degraded"}
```

Keep the existing `margin["influenced"]` comment and the `knowledge` attachment that follow in the original block exactly as they are; only the neighbor lines are new.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recall_neighbors.py tests/test_recall_margins.py -q`
Expected: all passed (margins tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_recall_neighbors.py
git commit -m "feat: call the Lighthouse receiver arm from recall"
```

---

### Task 9: Exporter formatVersion 1.1 with receipts

**Files:**
- Modify: `lighthouse_export.py` (`export_lighthouse_shadow`, `REQUIRED_SCHEMA`, new `_project_receipts`)
- Modify: `tests/test_lighthouse_export.py` (line 109 expectation, new tests)

**Interfaces:**
- Produces: document `formatVersion: "1.1"` and `receipts: list[dict]` (validated `RecallReceipt` artifacts from `memory_log` rows with `event_type = 'lighthouse_receipt'`, sorted by receipt `id`); `ExportAudit` gains `receipts: int` and `excluded_invalid_receipts: int`.

- [ ] **Step 1: Update and add tests**

Change line 109 of `tests/test_lighthouse_export.py` to `assert document["formatVersion"] == "1.1"`. Append:

```python
def add_receipt_row(connection: sqlite3.Connection, receipt: dict) -> None:
    connection.execute(
        "INSERT INTO memory_log VALUES (?, ?, ?)",
        ("lighthouse_receipt", json.dumps([]), json.dumps({"recall_id": "r", "receipt": receipt})),
    )


def sample_receipt(turn: str = "t1") -> dict:
    from lighthouse_protocol import content_digest
    from lighthouse_receipts import build_receipt
    return build_receipt(
        receiver="engram", turn_id=turn, context={"id": "memory/technical", "path": ["memory", "technical"]},
        purpose="session-recall", sources=[], selected=[], delivered=[], receiver_rule=None,
        issued_at="2026-09-01T00:00:00+00:00")


def test_export_carries_valid_receipts_and_drops_invalid(tmp_path):
    db = tmp_path / "graph.db"
    connection = build_database(db)
    add_receipt_row(connection, sample_receipt("t1"))
    bad = sample_receipt("t2")
    bad["payload"]["injected"] = True
    add_receipt_row(connection, bad)
    connection.commit()
    connection.close()

    document, audit = export_lighthouse_shadow(db, instance="engram-local")
    assert document["formatVersion"] == "1.1"
    assert [r["payload"]["turnId"] for r in document["receipts"]] == ["t1"]
    assert audit.receipts == 1 and audit.excluded_invalid_receipts == 1
    assert "query" not in json.dumps(document)


def test_export_without_receipts_has_empty_list(tmp_path):
    db = tmp_path / "graph.db"
    build_database(db).close()
    document, audit = export_lighthouse_shadow(db, instance="engram-local")
    assert document["receipts"] == [] and audit.receipts == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q`
Expected: FAIL on `formatVersion == "1.1"` and `KeyError: 'receipts'`

- [ ] **Step 3: Implement**

In `lighthouse_export.py`:

```python
from lighthouse_receipts import ReceiptError, validate_receipt
```

Add to `ExportAudit` two fields at the end: `receipts: int = 0` and `excluded_invalid_receipts: int = 0`.

Add after `_project_traces`:

```python
def _project_receipts(connection: sqlite3.Connection) -> tuple[list[dict], int]:
    rows = connection.execute(
        "SELECT context FROM memory_log WHERE event_type = 'lighthouse_receipt'"
    ).fetchall()
    receipts: dict[str, dict] = {}
    invalid = 0
    for row in rows:
        context = _parse_json(row["context"])
        receipt = context.get("receipt") if isinstance(context, dict) else None
        if not isinstance(receipt, dict):
            invalid += 1
            continue
        try:
            validate_receipt(receipt)
        except ReceiptError:
            invalid += 1
            continue
        receipts[str(receipt["id"])] = receipt
    return [receipts[key] for key in sorted(receipts)], invalid
```

In `export_lighthouse_shadow`, after `trace_projection = ...`: `receipts, invalid_receipts = _project_receipts(connection)`; set `"formatVersion": "1.1"`, add `"receipts": receipts` to the document after `"recallTraces"`, and pass `receipts=len(receipts), excluded_invalid_receipts=invalid_receipts` to `ExportAudit`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_export.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add lighthouse_export.py tests/test_lighthouse_export.py
git commit -m "feat: export Lighthouse receipts in shadow documents (1.1)"
```

---

### Task 10: Labeling CLI

**Files:**
- Create: `lighthouse_label.py`
- Test: `tests/test_lighthouse_label.py`

**Interfaces:**
- Consumes: `lighthouse_receipt` rows written by Task 6/7 (`memory_log.context.receipt`).
- Produces: `python -m lighthouse_label --db <graph.db> --instance <name> --output <x.labels.json> [--limit N]`; `collect_turns(connection, limit) -> list[dict]` reading the receiver's `lighthouse_receipt` events (newest first) and returning `{turnId, context, purpose, candidates: [{publisher, memoryId, contentDigest, delivered: bool}]}` built from each receipt's `selected` and `delivered` lists; `label_turns(instance, turns, prompt: Callable[[str], str]) -> dict` producing `{formatVersion: "1.0", instance, turns: [{turnId, context, purpose, relevant, forbidden}]}` with context and purpose copied from the receipt. Historical `recall` rows are not a source of turns: the Lighthouse shadow evaluation scores each holdout turn's own receipt, so receipts must exist before labels. The tool never reads `memory_log.outcome` (a test greps the source).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_lighthouse_label.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lighthouse_label import collect_turns, label_turns, main
from tests.test_lighthouse_export import add_recall, build_database

CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}


def add_receipt(conn: sqlite3.Connection, turn: str, selected_ids: list[str]) -> None:
    from lighthouse_protocol import content_digest
    from lighthouse_receipts import build_receipt
    selected = [{"publisher": "urn:engram:why", "memoryId": mid, "contentDigest": content_digest(mid),
                 "score": 1 / (61 + i), "contributions": [{"publisher": "urn:engram:why", "rank": i + 1}]}
                for i, mid in enumerate(selected_ids)]
    delivered = [{"publisher": "urn:engram:why", "memoryId": selected_ids[0],
                  "readDecision": {"effect": "allow", "ruleId": "r", "code": None}}] if selected_ids else []
    receipt = build_receipt(receiver="engram", turn_id=turn, context=CONTEXT, purpose="session-recall",
                            sources=[], selected=selected, delivered=delivered, receiver_rule="allow-why",
                            issued_at="2026-09-01T00:00:00+00:00")
    conn.execute("INSERT INTO memory_log VALUES (?, ?, ?)",
                 ("lighthouse_receipt", json.dumps([]), json.dumps({"recall_id": turn, "receipt": receipt})))


def test_collect_turns_reads_receipts_not_recall_rows(tmp_path):
    db = tmp_path / "graph.db"
    conn = build_database(db)
    add_recall(conn, "old-recall", "rivers", ["h1"])
    add_receipt(conn, "turn-1", ["e1", "e2"])
    conn.commit()
    conn.close()
    turns = collect_turns(sqlite3.connect(db), limit=10)
    assert [t["turnId"] for t in turns] == ["turn-1"]
    assert turns[0]["context"] == CONTEXT and turns[0]["purpose"] == "session-recall"
    assert [c["memoryId"] for c in turns[0]["candidates"]] == ["e1", "e2"]
    assert turns[0]["candidates"][0]["publisher"] == "urn:engram:why"
    assert turns[0]["candidates"][0]["delivered"] is True
    assert turns[0]["candidates"][1]["delivered"] is False
    assert turns[0]["candidates"][0]["contentDigest"]["algorithm"] == "sha256"


def test_label_turns_builds_labels_document(tmp_path):
    db = tmp_path / "graph.db"
    conn = build_database(db)
    add_receipt(conn, "turn-1", ["e1", "e2"])
    conn.commit()
    conn.close()
    turns = collect_turns(sqlite3.connect(db), limit=10)

    answers = iter(["urn:engram:why:e1", "", "urn:engram:why:e2", ""])
    doc = label_turns("engram", turns, prompt=lambda _text: next(answers))
    assert doc["formatVersion"] == "1.0" and doc["instance"] == "engram"
    assert doc["turns"][0]["turnId"] == "turn-1"
    assert doc["turns"][0]["context"] == CONTEXT and doc["turns"][0]["purpose"] == "session-recall"
    assert doc["turns"][0]["relevant"] == [{"publisher": "urn:engram:why", "memoryId": "e1"}]
    assert doc["turns"][0]["forbidden"] == [{"publisher": "urn:engram:why", "memoryId": "e2"}]


def test_cli_writes_document_and_refuses_existing_output(tmp_path, monkeypatch):
    db = tmp_path / "graph.db"
    conn = build_database(db)
    add_receipt(conn, "turn-1", ["e1"])
    conn.commit()
    conn.close()
    out = tmp_path / "x.labels.json"
    monkeypatch.setattr("builtins.input", lambda _p="": "")
    assert main(["--db", str(db), "--instance", "engram", "--output", str(out)]) == 0
    assert json.loads(out.read_text())["turns"][0]["turnId"] == "turn-1"
    assert main(["--db", str(db), "--instance", "engram", "--output", str(out)]) == 1


def test_labeler_never_reads_outcomes():
    source = Path("lighthouse_label.py").read_text()
    assert "outcome" not in source.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_label.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lighthouse_label'`

- [ ] **Step 3: Implement**

```python
# lighthouse_label.py
"""Receiver-owned relevance labels for Lighthouse evaluation.

Reads the receiver's own recall receipts (memory_log event
``lighthouse_receipt``), presents each turn's publisher-qualified selected
and delivered memories, and asks the person to mark which were relevant and
which were forbidden. The shadow evaluation scores each holdout turn's own
receipt, so receipts must exist before labels. Labels are judgments: this
tool asks; it never infers them from usage signals, and it never reads the
recall log's usage column.

Usage:
    python -m lighthouse_label --db graph.db --instance engram --output engram.labels.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Callable


def collect_turns(connection: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = connection.execute(
        "SELECT context FROM memory_log WHERE event_type = 'lighthouse_receipt' "
        "ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    turns = []
    for (context,) in rows:
        try:
            ctx = json.loads(context or "{}")
        except ValueError:
            continue
        receipt = ctx.get("receipt") if isinstance(ctx, dict) else None
        payload = receipt.get("payload") if isinstance(receipt, dict) else None
        if not isinstance(payload, dict) or not payload.get("turnId"):
            continue
        delivered = {(d["publisher"], d["memoryId"]) for d in payload.get("delivered", [])}
        candidates = [{
            "publisher": s["publisher"], "memoryId": s["memoryId"],
            "contentDigest": s["contentDigest"],
            "delivered": (s["publisher"], s["memoryId"]) in delivered,
        } for s in payload.get("selected", [])]
        turns.append({"turnId": payload["turnId"], "context": payload["context"],
                      "purpose": payload["purpose"], "candidates": candidates})
    return turns


def _parse_ref(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    publisher, _, memory_id = text.rpartition(":")
    if not publisher or not memory_id:
        return None
    return {"publisher": publisher, "memoryId": memory_id}


def label_turns(instance: str, turns: list[dict], prompt: Callable[[str], str]) -> dict:
    labeled = []
    for turn in turns:
        relevant, forbidden = [], []
        shown = ", ".join(
            f"{c['publisher']}:{c['memoryId']}" + (" [delivered]" if c["delivered"] else "")
            for c in turn["candidates"])
        header = f"turn {turn['turnId']} candidates: {shown}"
        while True:
            ref = _parse_ref(prompt(f"{header}\nrelevant (publisher:memoryId, blank to finish): "))
            if ref is None:
                break
            relevant.append(ref)
        while True:
            ref = _parse_ref(prompt(f"{header}\nforbidden (publisher:memoryId, blank to finish): "))
            if ref is None:
                break
            forbidden.append(ref)
        labeled.append({"turnId": turn["turnId"], "context": dict(turn["context"]),
                        "purpose": turn["purpose"], "relevant": relevant, "forbidden": forbidden})
    return {"formatVersion": "1.0", "instance": instance, "turns": labeled}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lighthouse_label")
    parser.add_argument("--db", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists():
        print("output exists", file=sys.stderr)
        return 1
    connection = sqlite3.connect(f"{Path(args.db).resolve().as_uri()}?mode=ro", uri=True)
    try:
        turns = collect_turns(connection, args.limit)
    finally:
        connection.close()
    document = label_turns(args.instance, turns, prompt=input)
    output.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_lighthouse_label.py -q`
Expected: 4 passed

- [ ] **Step 5: Register and commit**

Add `"lighthouse_label",` to `py-modules`.

```bash
git add lighthouse_label.py tests/test_lighthouse_label.py pyproject.toml
git commit -m "feat: add receiver-owned Lighthouse labeling CLI"
```

---

### Task 11: Documentation and full suite

**Files:**
- Modify: `CLAUDE.md` (Architecture: new paragraph after "Tropical margins"; Key Files table: five rows)

- [ ] **Step 1: Add the architecture paragraph**

Insert after the "Tropical margins" paragraph in `CLAUDE.md`:

```markdown
**Lighthouse local city:** Other local instances can supply policy-scoped
recall. A publisher daemon (`python -m lighthouse_daemon --config
.engram/lighthouse-daemon.toml`) opens each published store read-only,
evaluates that instance's `lighthouse-policy.json` (Lighthouse
`ConnectionPolicy`, deny-by-default, matches the TypeScript kit on vendored
fixtures) before any retrieval, serves work-lane episodes and semantics
only, and appends decisions to a disclosure sidecar beside the store. The
receiver arm (`neighbors.py`) runs once per `recall()` after local results
are final, fuses neighbor traces by weighted reciprocal rank, requests
content only under an `inject_context` grant, writes a `RecallReceipt`
(`lighthouse_receipts.py`, strict vendored schema) to `memory_log`, and
returns everything under the separate `neighbors` response key. Neighbor
material is never merged into `results`; the margin is unaffected; daemon
down or any failure yields `degraded: ["neighbors"]` and the unchanged
local result. Spec: docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md.
```

- [ ] **Step 2: Add Key Files rows**

After the `lighthouse_export.py` row (add one if absent):

```markdown
| `lighthouse_export.py` | Read-only shadow export for Lighthouse (formatVersion 1.1, receipts) |
| `lighthouse_daemon.py` | Publisher daemon — read-only stores, policy before retrieval, disclosure sidecar |
| `lighthouse_policy.py` | Python ConnectionPolicy evaluator, parity-tested against the Lighthouse kit |
| `lighthouse_protocol.py` | Canonical JSON, artifact digests, socket frames |
| `lighthouse_receipts.py` | RecallReceipt builder, strict schema validation, memory_log writer |
| `neighbors.py` | Receiver arm — RRF fusion, inject_context gating, `neighbors` payload |
| `lighthouse_label.py` | Receiver-owned relevance labeling CLI |
```

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all passed

Run: `grep -n "import server\|from server" lighthouse_daemon.py neighbors.py lighthouse_policy.py lighthouse_protocol.py lighthouse_receipts.py lighthouse_label.py`
Expected: no output

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: describe the Lighthouse local city in CLAUDE.md"
```

---

## Self-review

**Spec coverage.** 4.1 read-only open: Task 1. 4.2 daemon, policy-before-retrieval, work lane, no instincts, disclosures: Task 5 (disclosures go to a sidecar file so the store's bytes never change; the spec's "publisher's own memory_log" is satisfied by the sidecar, since a read-only store cannot be written). 4.3 protocol and the plaintext-query note: Task 4, Task 5 docstring. 4.4 policy and cross-implementation parity: Task 3. 4.5 receiver arm, RRF 60, inject_context gating, degraded: Task 7 and Task 8. 4.6 receipts: Task 6. 4.7 is L1's. 4.8 exporter: Task 9. 4.9 labeling: Task 10 (turns come from the receiver's `lighthouse_receipt` events, so receipts precede labels). Section 6 failure table: Tasks 5, 7, 8 tests. Section 7 first neighborhood: the integrator writes the two publisher policies and the receiver policy from the fixtures in Tasks 5 and 7 with `validUntil` at cycle close.

**Placeholders.** None. Every step has code or a command.

**Type consistency.** `Decision.to_json()` is the dict shape carried in frames and receipts (`effect`, `ruleId`, `code`); `Decision.to_lighthouse()` is used only for fixture parity. `content_digest` labels `sha256`; `artifact_digest` labels `sha-256`. `neighbor_arm` keyword names match the call site in Task 8. `PublisherStore.publisher_id` is `urn:engram:<name>` and the receiver policy names publishers the same way; the daemon maps a receiver's plain instance name to `urn:engram:<receiver>` when it evaluates its own policy.
