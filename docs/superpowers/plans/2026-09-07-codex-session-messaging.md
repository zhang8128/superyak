# Codex session messaging implementation plan

**Goal:** One local Codex session can discover another, ask it a question, and
retrieve the correlated reply through Superyak.

**Architecture:** A narrow session bridge calls Codex's native durable queue
and paginated history APIs over the existing bounded stdio transport. CLI and
MCP entry points share this bridge; no new message database or target runtime.

**Tech stack:** Python 3.13, existing MCP dependency, Codex CLI 0.153.4.

**Spec:** [Session messaging](../specs/2026-09-07-codex-session-messaging.md).

## Tasks

1. Implement `engram/session_bridge.py` test-first in
   `engram/tests/test_session_bridge.py`: discovery metadata, native queue
   submission, UUID request handles, exact reply lookup, bounded pagination
   and explicit uncertainty. Reuse `context_codex._Session` for transport.
2. Add `engram/session_cli.py` with `list`, `ask`, `result`, and `mcp` commands;
   expose three MCP tools with caller metadata. Add meaningful CLI/MCP protocol
   tests and include both modules/entry point in packaging.
3. Turn the disposable two-process probe into a reproducible test/pilot,
   including a busy recipient and unrelated earlier answer. Run the normal
   suites and independent standards/spec reviews, correcting findings.
4. Document commands and limits, install the additional MCP configuration and
   local CLI wrapper, verify the installed MCP handshake, and run a bounded
   synthetic managed-login exchange. Publish source and validation in Superyak.

Existing memory stores, MCP bindings, and Lighthouse policies are outside this
change. Installation adds session messaging beside them. Sending to a session
does not authorize it to perform unrelated changes.
