# Dynamic Context Runtime Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent provider work and review. Execute the tightly coupled archive/compiler/runtime work together with test-driven development.

**Goal:** Ship an opt-in, usable Engram conversation runtime with automatic durable recall/capture, inspectable bounded selection, a subscription-backed Codex adapter, and a separately configured strict Responses adapter.

**Architecture:** SQLite stores exact events and derived search/state outside model context. A compiler freezes selected context and a provider gate counts it before dispatch. Codex is an episode-level adapter until its internal request assembly can expose the stronger contract.

**Tech Stack:** Python >=3.12, SQLite/FTS5, standard-library HTTP/subprocess, existing pytest environment; existing Engram recall through an explicit optional adapter.

**Spec:** `docs/superpowers/specs/2026-09-05-dynamic-context-runtime-design.md`

## Global Constraints

- No automatic fallback from subscription to API billing.
- No change to existing Codex sessions or the legacy daemon backend.
- All strict adapter calls include total input counting and output reserve; never silently truncate mandatory input or provider continuation items.
- Retrieved material is evidence, not developer instructions. Capture preserves speaker/source attribution.
- Future category influence, remote Lighthouse sources, medical pilots, and unverified Codex core changes remain gated as specified.
- Worktree: `.worktrees/dynamic-context`, branch `feat/dynamic-context`.
- Run Python with `/Users/kairos/Projects/engram/.venv/bin/python` from this worktree.

## Shared Interfaces

Providers expose `model: str`, `capabilities: dict`, `count(payload: dict) -> int`, `generate(payload: dict) -> dict`, and `close()`. Capabilities include `strict: bool`, `budget_scope: model_call|episode`, `count_kind: provider|estimate`, and `billing: api|subscription`.

Generation uses Responses-shaped input and output. Output includes `id`, `status`, `output` (original ordered provider items), and `usage`; a final message contains `content: [{type: output_text, text: ...}]`. The Codex adapter translates its final text to that envelope and declares episode scope; it does not expose its internal tools as calls for Engram to re-execute.

`ContextStore(path)` owns durable thread events, artifacts, state, turns, manifests, and indexing. `ContextCompiler(Budget(...)).compile(instructions, current, candidates, active_items, provider)` returns a frozen counted request and manifest. `ContextRuntime(store, provider, budget, sources=()).chat(thread_id, message, event_id=None)` owns capture, retrieval, compilation, model/tool steps, and returns a JSON-serializable response plus manifest reference.

## Task 1: Durable archive and compiler

Files: create `context_store.py`, `context_compile.py`; tests `tests/test_context_store.py`, `tests/test_context_compile.py`.

- [x] Write failing tests for idempotent exact user/assistant capture, thread-scoped search, persistent corrections/pins, artifact bounds/deletion, restart after interrupted turns, and full-request overflow.

```python
def test_latest_correction_survives_reopen(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    store.set_state("t", "name", "Mira", source_id="user-correction")
    store.close()
    reopened = ContextStore(tmp_path / "context.db")
    assert reopened.state("t")[0]["content"] == "Mira"
```

- [x] Run the two test files and verify failure from missing functionality.
- [x] Implement SQLite schema versioning, write transactions, bounded event windows and FTS5 candidates, scoped artifacts, and atomic turn completion. Store the full archive outside prunable Engram episodes. Failed/in-progress turn IDs are never transparently replayed into provider calls.
- [x] Implement typed budgets, candidates with ordered representations/dependencies, deterministic selection, role-preserving messages, complete active provider groups, bounded recounting, and immutable serialized requests. Required overflow produces an error before generation; estimates never advertise strict guarantees.

```python
result = compiler.compile(instructions="runtime policy", current="hello",
                          candidates=[], active_items=[], provider=provider)
assert result.manifest["input_tokens"] + result.manifest["output_reserve"] <= 256
```

- [x] Run behavioral tests including 10,000 synthetic compile cycles with Unicode and growing candidate archives; inspect counters and bounded selection rather than matching implementation text.
- [x] Commit archive/compiler and tests after review.

## Task 2: Provider adapters

Files: create `context_provider.py`, `context_codex.py`; tests `tests/test_context_provider.py`, `tests/test_context_codex.py`.

- [x] Write failing tests around actual transport boundaries: count endpoint payload, disabled truncation and storage, missing credentials, failed counts, malformed responses, process timeout/oversized output, account mismatch, model selection, and no API fallback.

```python
assert CodexProvider(...).capabilities["budget_scope"] == "episode"
assert ResponsesProvider(...).capabilities["billing"] == "api"
```

- [x] Implement `ProviderError`, Responses HTTP calls via an injectable transport, and strict response validation. Count only the same context-bearing fields later sent to generation. Use API credentials only for the explicitly selected API provider.
- [x] Implement Codex app-server stdio transport against the installed generated schema: initialize, account/read, model/list, fresh ephemeral thread/start, turn/start, final event collection, and shutdown. Use managed ChatGPT login; require ChatGPT auth. Limit process time and bytes; use a controlled working directory/read-only sandbox and deny requested effects. Report internal token usage when available without claiming preflight counts.
- [x] Test against a scripted local subprocess protocol fixture; perform a minimal synthetic live subscription smoke if available. No private archive is used in the smoke.
- [x] Commit adapter files and tests after review.

## Task 3: Runtime and automatic memory sources

Files: create `context_runtime.py`, `context_sources.py`; tests `tests/test_context_runtime.py`, `tests/test_context_sources.py`.

- [x] Write failing integration tests using the real archive/compiler and a deterministic provider double: recording before dispatch, archival after answer, restart, A-B-A retrieval, index lag, tool pairs and opaque items, thread isolation, capacity stops, and absent reinforcement on mere selection.
- [x] Implement a per-thread cross-process lease, durable client-event idempotency, explicit failed/interrupted status, and original output-item capture. Finish answer/capture in a transaction and retain manifest references for inspection.
- [x] Implement bounded archive search plus immediate recent-event/correction overlay. Add an optional read-only Engram adapter that preserves record IDs/layers and records its simpler retrieval mode. No full server import or blind promotion of all dialogue to personal facts.
- [x] Implement strict-provider read-only `archive.search` and paginated `archive.read` tools with bounds and original call IDs. Preserve the active episode in every counted continuation and cap steps, results, and elapsed time. Codex owns its own tool execution.
- [x] Run failure tests and long-session replay; confirm recovery does not duplicate provider calls for the same completed event ID.
- [x] Commit runtime/source changes after review.

## Task 4: Usable CLI, local chat, and inspection

Files: create `context_cli.py`, `context_chat.html`; modify `pyproject.toml`; tests `tests/test_context_cli.py`; document `docs/dynamic-context.md`.

- [x] Write failing tests for command defaults, instance-path isolation, required API model limits, JSON responses, HTTP body bounds, thread routing, error status, and manifest inspection.
- [x] Implement `python -m context_cli chat|serve|status|inspect` with subscription default and explicit API selection. Require a validated/configured context window for strict API mode. Keep all data in an explicit runtime directory and default HTTP to loopback.
- [x] Provide a small chat view with persistent thread ID, escaped message rendering, and optional context inspector/correction controls. Use automatic recall/capture in ordinary chat; manual memory calls are not required. Keep the old UI/backend intact.
- [x] Register modules/data files and document exact startup commands, capability limits, archive retention/deletion, failure recovery, tests, and the unimplemented core integration boundary.
- [x] Run targeted tests, full existing suite, packaging smoke, and a synthetic subscription smoke. Review the whole branch and address findings before presenting the result.

## Coverage and scope record

The first version implements local durable capture/indexing without LLM summaries or automatic semantic promotion. It uses exact current dialogue plus explicit user corrections/pins and selected original passages. This avoids making an unvalidated extractor authoritative. The model can search and read archived material in strict mode. Rich contextual inference and human continuity evaluation remain separate experiments; mechanical test success does not establish the proposed 95% continuity pilot gate.

The Codex protocol schema exposes no full-request counting/replacement method. This version can ship a useful subscription episode adapter, alongside the complete strict gate for explicitly configured Responses calls. It must not label the subscription route as satisfying the stronger per-sample contract.

## Execution result

Implemented on `feat/dynamic-context`. Final suite: 1,848 passed, three existing warnings. The independent review is clear after regression fixes for chronology, source invalidation, atomic corrections, failed-turn continuity, nested JSON, and artifact deletion/write recovery. Subscription provider and two-episode archive integration smokes succeeded using synthetic content. No live API-billed request was made. The local chat is running on port 7433 against the engram instance; the implementation branch/worktree is retained for review. See `docs/dynamic-context.md` for supported capabilities and the explicitly deferred quality pilot/Codex core integration.
