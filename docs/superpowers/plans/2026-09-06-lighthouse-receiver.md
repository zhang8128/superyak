# Lighthouse Receiver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete an opt-in, measured local Lighthouse crossing with receipts and withdrawal.

**Architecture:** A bounded client validates and fuses opaque publisher traces; a receiver coordinator enforces local policies and persists evidence. A small final-response seam connects it to MCP recall. Disposable pilot and labeling commands make the mechanism reviewable without enabling live sharing.

**Tech Stack:** Existing Python >=3.12, SQLite, jsonschema, Unix sockets, pytest; sibling TypeScript kit for receipt validation.

**Spec:** docs/superpowers/specs/2026-09-06-lighthouse-receiver-design.md

## Global constraints

- Worktree: `/Users/kairos/Projects/engram/.worktrees/lighthouse-receiver`, branch `feat/lighthouse-receiver`, base `eec90fa`.
- Run tests with `/Users/kairos/Projects/engram/.venv/bin/python` from this worktree.
- Never write actual instance/genome databases or restart running MCP/daemon processes.
- Use explicit shares (including eligible personal-lane shares); no automatic work-lane publication.
- Preserve local recall; fail closed on permission, content-integrity, transport and receipt failures.
- Keep receipt schema 0.1 and use defined namespaced extensions for bounded trace snapshots/unknown sources.
- Human usefulness evaluation remains pending. No live receiver configuration is installed.

## Task 1: Bounded client, trace validation and fusion

Files: `lighthouse_client.py`, `tests/test_lighthouse_client.py`.

```python
class NeighborUnavailable(RuntimeError):
    code: str
class LighthouseClient:
    def __init__(self, socket_path, timeout_s=2.0): ...
    def call(self, frame: dict, *, deadline: float | None = None) -> dict: ...
def validate_trace(reply: dict, *, publisher: str, query: str, context: dict, k: int) -> dict: ...
# Returns canonical safe snapshot {publisher,turnId,queryDigest,context,candidates,decision,disclosureId}.
def validate_read(reply: dict, *, selected: list[dict]) -> list[dict]: ...
# Returns verified non-null allowed items only, adding selected layer/lane/contentDigest.
def fuse_traces(traces: dict[str, tuple[float, list[dict]]], k: int) -> list[dict]: ...
# Entries {publisher,memoryId,contentDigest,score,contributions}; same wire/schema shapes as old plan.
```

- [x] Write failing tests for real socket roundtrip, absent socket, partial/trickled frames, cap/timeout, exact context/query binding, bad ranks/IDs/digests, unsupported layers, mismatched/unrequested content, and deterministic RRF.
- [x] Run tests to establish red, implement the bounded client/validators, then run targeted tests.
- [x] Commit owned files and independently review the contract before integration.

## Task 2: Publisher action-policy withdrawal

Files: `lighthouse_daemon.py`, `tests/test_daemon_audiences.py` or a dedicated `tests/test_lighthouse_withdrawal.py`.

- [x] Reproduce cached action permission surviving a policy edit with a real disposable PublisherDaemon.
- [x] Reload a validated policy on every operation and use its one snapshot for action and audience checks. An invalid reload denies/returns unavailable; never reuse stale allow.
- [x] Verify action withdrawal, audience withdrawal and unshare; retain policy-before-retrieval, byte-identical source store and disclosure tests.
- [x] Commit owned files. Coordinate shared tests without editing the client/coordinator files.

## Task 3: Receiver, MCP seam and measurable pilot

Files: `neighbors.py`, `lighthouse_pilot.py`, `lighthouse_label.py`, `tests/test_neighbors.py`, `tests/test_recall_neighbors.py`, `tests/test_lighthouse_pilot.py`, `tests/test_lighthouse_label.py`; small changes to `server.py`, `pyproject.toml`, and usage documentation.

```python
def neighbor_arm(*, query, context, purpose, k, storage, session_id, recall_id,
                 receiver, publishers, socket_path, policy_path, timeout_s=2.0, now=None): ...
# None if no matching policy; otherwise {sources,selected,delivered,receipt_id,degraded,diagnostics}.
def attach_neighbors(response, *, query, context_id, purpose, storage,
                     session_id, receiver, engram_home): ...
# Mutates response only to add neighbors/degraded; missing config/context returns unchanged.
```

- [x] Write coordinator tests for policy-before-query, independent read/inject grants, no-transitive selection, per-publisher weights, live withdrawal, receipt reproducibility/no-content, failure to persist suppressing delivery, and partial unavailable peers.
- [x] Implement strict bounded TOML config, receiver identity/issuer checks, policy rechecks, content budget, immutable snapshot extensions and receipt-before-delivery behavior.
- [x] Add optional declared-context/purpose parameters to MCP recall and one final-response call; test unchanged local results/margins and failure isolation.
- [x] Build a disposable real-socket pilot with a positive crossing, denied control, withdrawal and source-byte integrity; add receiver-owned labeling output compatible with the existing kit.
- [x] Register modules and runnable commands; document that usefulness and remote authentication remain unproven.
- [x] Run focused tests, pilot and sibling kit receipt validation, then the full suite. Independently review and fix substantive findings, commit the completed milestone.

## Execution notes

Task 1 owns only the client and its tests; Task 2 owns publisher reload and its dedicated tests. Parent owns Task 3 while these independent components are built. The old E1 implementation examples are reference only: replace the unbounded socket read, cached permissions and zero digest with the contracts above. No source from the older PostgreSQL service branch is imported.


## Validation result

Completed on the isolated branch: 1,953 tests passed with three existing warnings;
six packaging tests passed. The real socket pilot delivered the allowed share and
withheld receiver-denied, policy-withdrawn and unshared controls. The sibling kit
validated four receipts and two policies. Independent review findings were fixed
with regression tests, including strict publisher selectors/issuer validation and
publisher-owned authorization time. See docs/reports/2026-09-06-lighthouse-receiver.md.
