# Research recording implementation plan

Approved scope: [design](../specs/2026-09-07-research-recording-design.md).
Existing Atlas baseline: 135 workbench tests pass at `ab68724`.

1. Fix Engram capture against a migrated temporary Storage schema in the
   isolated Superyak worktree. Assert actual persisted prompt/session/source
   metadata and healthy nudge output, then correct the schema mismatch and any
   immediately blocking capture fields. Run capture and harness regressions.
2. Add a failing public-boundary Atlas test:
   `ResearchInbox(project).record(draft, session_id="session-a")` must produce a
   durable `proposed` record, a publication receipt, and explicit view membership.
   Implement `workbench/automation.py` and the checked-in pilot binding. Add
   idempotency, failure recovery, source/record protection, and concurrency tests
   one behavior at a time; use the real normalized workbench schema.
3. Add CLI subprocess tests for `python -m workbench.automation --project PATH
   record NOTE --session SESSION`, `context`, `refresh`, and `status`. Implement
   JSON stdout, bounded input, and actionable nonzero errors.
4. Add `workbench/automation_mcp.py` with the four tools and trusted request
   metadata attribution. Verify calls over real stdio, including refusal of a
   forged session field and accurate durable-save/refresh-error receipts.
5. Add project agent instructions and a concise human guide. Install launchers
   and the additive MCP registration, initialize the real inbox with the
   existing pilot, and measure an isolated Codex record-and-refresh round trip.
6. Run all workbench tests and native Lighthouse validation of refreshed
   artifacts. Inspect the final patch against the spec, preserve other-session
   files, commit owned changes, install the verified live Engram hook fix, and
   send the research owner the exact updated usage and results.

The user already approved the workflow. Routine implementation, isolated
worktrees, installation, and verification continue under that authorization.
