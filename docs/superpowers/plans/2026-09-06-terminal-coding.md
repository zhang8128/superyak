# Terminal Coding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run real terminal coding tasks with automatic archive capture and resumable context episodes.

**Architecture:** A separate CodingProvider hosts native Codex tool episodes. CodingRuntime compiles bounded task context and durably coordinates episodes. The CLI renders progress and resume instructions.

**Tech Stack:** Python 3.12+, SQLite, installed Codex 0.153.4 app-server, pytest.

**Spec:** docs/superpowers/specs/2026-09-06-terminal-coding-design.md

## Global Constraints

- Work in `.worktrees/dynamic-context`, preserving chat and managed ChatGPT authentication.
- No API fallback, new service, or direct use of private authentication endpoints.
- Preserve user goals and corrections; generated checkpoints are attributed evidence.
- No automatic replay after interruption or transport uncertainty.
- Explicitly label episode estimates and internal Codex context limitations.
- Use `/Users/kairos/Projects/engram/.venv/bin/python -m pytest` for tests.

## Task 1: Native coding episode host

Files: create `context_coding_provider.py`, `tests/test_context_coding_provider.py`, and a scripted server fixture under `tests/fixtures/`. Reuse `context_codex._Session`; adjust it only if a compatible optional hook/limit is needed.

Interface:

```python
class CodingProvider:
    # model; capabilities same episode/estimate/subscription semantics as CodexProvider
    def __init__(self, model='gpt-6-astra', cwd=None, timeout=900,
                 soft_tokens=32000, hard_tokens=48000, max_steps=24,
                 approve=None, command=None): ...
    def count(self, payload: dict) -> int: ...
    def episode(self, payload: dict, on_event, tool_handler=None) -> dict: ...
    def close(self): ...

# episode result:
{'status': 'completed', 'checkpoint': {'status': 'continue', 'summary': '...',
 'decisions': [], 'next_steps': ['...'], 'checks': []}, 'usage': {}, 'reason': None}
# Interrupted turns return status='interrupted', checkpoint=None, reason=<text>.
# Transport/deadline/malformed-output failures raise ProviderError after cleanup.
# on_event receives each bounded visible notification, including progress/usage.
# approve receives an approval-request dict and returns bool; absent means decline.
# tool_handler(name, arguments) returns a read-only task-scoped archive result.
# payload.tools advertises only archive_search/archive_read; include their schemas in count.
```

- [x] Write scripted tests proving actual command/file events, workspace sandbox, subscription validation, structured checkpoint validation, soft steer once, hard interrupt, command-step limits, failure cleanup, and no inherited external integrations.
- [x] Run the new tests and observe missing implementation failures.
- [x] Implement the host with fresh ephemeral threads, native shell/edit tools, outputSchema, bounded transport, and scoped turn/event matching. Use `turn/steer` with expectedTurnId; `turn/interrupt` after a hard threshold. Denied escalation must be visible to the agent.
- [x] Run new provider tests plus `tests/test_context_codex.py` (89 tests passed).

## Task 2: Durable task coordination

Files: create `context_coding.py`, `context_coding_memory.py`, `tests/test_context_coding.py`; extend `context_store.py` with indexed `latest_event(thread, kind)`, bounded event pages, and explicit coding search kinds.

Interface:

```python
CodingRuntime(store, provider, budget, sources=(), max_episodes=20, on_event=None)
runtime.run(thread, task=None, resume=False)  # dict status, checkpoint, episodes, reason
runtime.close()
store.latest_event(thread, kind)  # exact bounded original or None
```

- [x] Write tests that run two fake episodes, reopen SQLite, resume a paused task, reject repository mismatch, preserve goal/correction provenance, avoid replaying completed tasks, and pause after interrupted/failed episodes.
- [x] Run tests to confirm failure before implementation.
- [x] Persist `coding_task`, `coding_progress`, and `coding_event` events. Index checkpoint messages and bounded tool observations for recall. Keep small exact events inline and large events in artifacts; attach original IDs to excerpts. Compile the original task, current snapshot, latest checkpoint, pins, and bounded recall using ContextCompiler. Revalidate external selected sources after counting. Save each manifest before dispatch. Provide scoped search/read tools for omitted originals.
- [x] Run coordinator and existing store/compiler/runtime tests.

## Task 3: Terminal command and end-to-end validation

Files: extend `context_cli.py`, `pyproject.toml`, `docs/dynamic-context.md`, and CLI tests.

CLI:

```sh
python context_cli.py --thread feature-x code --repo /path/to/repo 'Implement feature X and run its tests'
python context_cli.py --thread feature-x code --repo /path/to/repo --resume
```

- [x] Test parsing, code-specific provider selection, noninteractive approval denial, terminal rendering, pause exit status, and resume output.
- [x] Implement `code` with `--repo`, `--resume`, `--max-episodes`, `--episode-seconds`, `--soft-tokens`, `--hard-tokens`, and `--max-steps`. Generate a task name when global thread is default; resumption requires the printed task name. Print useful command/file/checkpoint progress with terminal control characters escaped. Retain native workspace sandbox; ask in the terminal only for actual escalation requests.
- [x] Register modules and document runnable commands, limitations, correction/resume behavior, and data location.
- [x] Run focused tests, then a subscription smoke that creates and tests code in a temporary git repository, then full pytest. Review the final diff independently; fix substantive findings and rerun affected checks. Final suite: **1943 passed**, three existing dependency/fork warnings, 201.87 seconds. Working diff and staged diff whitespace checks passed.

## Progress

Plan reviewed against the spec: task 1 provides the episode interface consumed by task 2; task 2 provides the runtime consumed by task 3. Shared `context_codex.py` changes are owned by task 1. Controller owns task 2/store and CLI integration, with independent final review. This assignment permits useful independent provider and persistence work in the same worktree.

Review fixes: added access to older tool evidence (scoped dynamic archive tools, indexed excerpts, original links) and rejected list/dict checkpoint statuses before set membership. Both verified by independent re-review. Live compatibility checks found that Codex's native temporary-directory permissions must remain representable and an empty environments list disables the required shell/file tools; use the default local environment and standard workspace policy.

Final scoped review also verified immediate event capture before turn acknowledgement, native command cleanup across separate process groups, and correct current-episode usage after interruptions. Independent reviewer reran 144 regressions successfully and reproduced native command shutdown without a model call. Provider commit: `4dfd5c6`. Two live subscription smokes passed: real file creation plus tests, and archive retrieval plus two automatic context episodes with an independent test rerun.
