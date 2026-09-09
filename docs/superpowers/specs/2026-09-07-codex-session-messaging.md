# Codex session questions and replies

User request: let any of Kairos's local Codex sessions ask another session a
question and receive its answer. This follows the merged Engram/Lighthouse
monorepo; saved-memory sharing alone did not provide message delivery.

## Design

Use Codex 0.153.4's native `thread/queue/add` through a short-lived stdio
app-server connection. The owning session notices the shared durable queue;
idle sessions start a turn and busy sessions process it after their current
turn. Closed or interrupted sessions may need to be resumed. Do not resume,
fork, interrupt, change approval settings, or run a replacement for the target.

A disposable probe with two actual Codex app-server processes, one temporary
Codex home, and a local deterministic model endpoint proved cross-process
delivery and correlated reply readback. The queue watcher polls every ten
seconds in the inspected upstream implementation. This is queued messaging,
not synchronous delivery or a guarantee the recipient will answer.

Expose session discovery, asking, and result lookup through a CLI and a small
separate MCP server. Discovery returns names, repository paths, IDs and metadata;
it omits conversation previews. Read-only discovery status is local to the
metadata server and cannot establish another process's liveness.

Send an explicitly attributed peer question with a UUID client message ID.
The recipient answers in its normal conversation, and result lookup finds only
the turn carrying that client ID. Return final assistant text, pending/failure
state, and pagination when a bounded scan needs to continue. Tool output must
not include unrelated turns, prompts, tool bodies, or account credentials.
The sender is derived from Codex MCP request metadata or CLI environment;
reject self-questions when the sender is known. Missing identity is explicit.
Questions are peer requests, not new human authorization for changes.

Use the existing bounded Codex stdio transport. Bound request size, RPC time,
reply size, and history pagination. Never automatically retry a queue mutation:
if the response is lost, return the request ID with unknown submission state
so the caller can inspect it without duplicating the question.

## Installation and boundaries

Register the additional MCP server in Kairos's Codex configuration after
verification, and install a `superyak-sessions` CLI entry point for sessions
already open. New/reconnected MCP clients discover the tools; existing sessions
can use the CLI immediately. Keep Engram's current live bindings and all memory
and Lighthouse policies intact. No cross-account or cross-machine service is
introduced. The bridge uses the current OS user's Codex home.

## Acceptance

- Unit and protocol tests prove caller attribution, self-send rejection,
  exact reply correlation, bounded pagination, failures and ambiguous writes.
- Two disposable real Codex processes prove delivery without resuming the
  recipient, and reply lookup exposes only the matching answer.
- A bounded managed-login smoke test proves a real model can receive and answer
  a synthetic question; no real user work thread is used as a test target.
- MCP initialization and tools work through the installed launcher. Existing
  suites and cross-language Lighthouse checks remain green.
- Document the queue/closed-session/reload limits without claiming every
  historical or remote Codex session is currently online.

## Sources

- Installed Codex CLI 0.153.4: `codex queue --help` and generated app-server schemas.
- [App-server documentation](https://learn.chatgpt.com/docs/app-server).
- [Native queue command](https://github.com/openai/codex/blob/main/codex-rs/tui/src/session_queue_commands.rs).
- [Cross-process queue watcher](https://github.com/openai/codex/blob/main/codex-rs/ext/queue/src/service.rs).
