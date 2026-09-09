# Session messaging verification — 2026-09-07

Two independent Codex sessions exchanged a question and its correlated answer
through the new MCP tools. The tools and terminal launcher were then installed
locally alongside the existing Engram server.

## Managed-login exchange

Environment: macOS, Codex CLI 0.153.4, Python 3.13.5, managed ChatGPT login,
`gpt-6-astra`. Two disposable persistent threads shared the user's existing
Codex home and used a temporary working directory. Both had read-only sandboxes;
inherited MCP servers, hooks, plugins, shell tools, and memory integrations were
disabled for these test threads. Only the requester enabled `superyak_sessions`.

1. The receiver was given a randomly generated synthetic codeword and replied
   `READY`. The requester was not given that codeword.
2. The requester called `session_ask` exactly once with the receiver's thread ID.
3. The receiver processed the queued question in its own conversation and
   answered with the codeword.
4. The requester called `session_result` and returned exactly the same codeword.
5. The stored peer question identified the requester's actual MCP thread ID,
   rather than the parent process's inherited identity.
6. Both test processes were closed and their synthetic threads archived. The
   installed MCP server could still retrieve the correlated reply afterward.

The passing exchange took **26.24 seconds**, including initialization and three
model turns. No existing user work thread was used as a test recipient. This is
a functional smoke result, not a delivery-latency benchmark or reliability claim.

The first smoke exposed an observer-status bug: Codex's history API reports an
in-progress turn owned by another app-server as `interrupted`, with no completion
timestamp. The receiver answered, but the requester stopped polling too early.
A deterministic two-process regression reproduced the failure in **0.77 seconds**
by holding the synthetic model's answer open. The bridge now reports
`pending_unknown` when that interruption has no recorded end and continues
bounded polling. Recorded interruptions remain terminal. This behavior matches
Codex's [`normalize_thread_turns_status` implementation](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/request_processors/thread_processor.rs).

## Automated verification

- Full Engram suite: **2,219 passed, 2 opt-in host checks skipped** in 160.59
  seconds. Both host configuration checks were then run explicitly against the
  existing Engram installation and passed.
- Messaging protocol, CLI/MCP, and native delivery tests: **26 passed**. The
  native fixture uses two real Codex processes and a local synthetic Responses
  endpoint, covering busy, currently answering, and idle recipients.
- Lighthouse build, lint, typecheck, **129 tests**, and conformance proofs passed.
- Interoperability passed: **2 matching schemas, 7 socket checks, 4 validated
  receipts**.
- Independent standards and specification reviews found an incomplete-queue
  pagination ambiguity. It was fixed with explicit `pending_unknown`, polling,
  documentation, and a regression test. Both reviews subsequently cleared the
  final production/test delta, including the cross-process status correction.

Reproduce the messaging checks with:

```sh
cd engram
uv run --locked --extra dev python -m pytest tests/test_session_bridge.py tests/test_session_cli.py tests/test_session_delivery.py -q
```

The separate CI job installs pinned Codex 0.153.4; it requires no credentials.
The managed-login smoke is a manual measurement and is not run by normal CI.

## Local installation

The global Codex configuration now has an additional `superyak_sessions` MCP
entry bound to the Superyak checkout's installed entry point. A semantic
comparison against a private configuration backup verified that all other
configuration remained identical. `~/.local/bin/superyak-sessions` links to the
same entry point. CLI discovery and the installed MCP handshake passed; the
server exposed exactly `sessions_list`, `session_ask`, and `session_result`.

New/reconnected clients load the MCP tools. Already-open sessions can use the
CLI and receive native queued questions. Both endpoints must use the same local
Codex home; closed or interrupted recipients may need resuming. See the
[usage guide](../codex-sessions.md) for status and history limits.
