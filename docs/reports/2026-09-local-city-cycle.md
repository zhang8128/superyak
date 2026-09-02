# Local city cycle record

## Base refs

- engram main: 195439d537ebc2d5e84d61b6c66dd7b5c03dc59c (step zero, 2026-09-01)
- lighthouse main: 0a6fae7e515ce6f0e9c2e9e0a70a5094a13027f9 (2026-09-01)

## B0

Census 2026-09-01: no-go for `why` and `blocks` (zero work-lane rows,
identical March snapshots). Neighborhood amended to `lighthouse`, a new
instance bound to `~/Projects/lighthouse` (lighthouse commit b9dc702).
Spike re-runs against `lighthouse` at 30 work-lane episodes. Report:
`docs/reports/2026-09-b0-neighbor-spike.md`.

## Step zero

Working tree committed as 195439d; 1490 tests passed on that tree. The live
MCP server in the integrator session was already running this code (margins
data visible through reflect before the commit), so no restart was needed
for step zero. Every later engram merge still requires one.

## Outcome coverage baseline

Last 30 days at cycle start: 14 of 31 recalls carry an outcome.

## Teams launched (2026-09-01 evening)

- lighthouse `team-lighthouse-local-city-l1`: first launch at 19:30 failed on
  MCP tool approval (codex 0.152 denies MCP calls under approval_policy=never
  unless the tool's approval_mode is "approve"; launcher fixed in codex-team
  b9b35cb). Relaunched 19:42 from lighthouse main b9dc702; lead confirmed
  both devs via team_status(); brief delivered through the tmux paste buffer.
- engram `team-engram-local-city-e`: launched 19:46 from engram main 5fb3804;
  dev1 = E1, dev2 = E2; brief delivered the same way, with the seam rule, the
  B0 gate on the receiver arm, and a reference-only note about the branch
  `feature/engram-lighthouses`.

## Prior art noted

`feature/engram-lighthouses` (2026-08-27..28, 48 commits, ~35k lines): a
Postgres-backed multi-user Lighthouse service inside engram (lighthouse/
package: mesh API, gluing, overlaps, invalidation, GitLab authority via Hyper
Coordinator, own MCP server), spec approved 2026-08-27. Three days later the
protocol repo chose a sibling-repository design. Kairos's decision this cycle:
reference only; nothing merged or imported; the service can become a publisher
later.

## Overnight log (2026-09-01 late)

- 20:0x The lighthouse instance binding was broken from 19:11 until
  lighthouse commit 760b88e. Two causes in sequence: the config I appended
  duplicated the `[memory]` table (TOML parse error), and after fixing that,
  `default_lane` is not yet a `MemoryConfig` field, so engram's loader raised
  on it. Either way `resolve_db_path` swallows the exception and silently
  falls back to the default store. Consequence: the L1 team's three Codex
  sessions woke into the `engram` store (three `session_start` rows there
  at 19:42) and will stay bound to it for their lifetime. The `lighthouse`
  store has zero rows. The B0 gate cannot open overnight; the receiver arm
  waits. The binding now resolves correctly for any session started in
  `~/Projects/lighthouse` from here on. `default_lane = "work"` returns to
  that config once E2 lands.
- Follow-up defect for the engram lanes (not done overnight): a project
  config that fails to parse silently reroutes memory to a different store.
  `resolve_db_path` should fail loudly, or at least log at WARNING with the
  parse error, and `MemoryConfig` should ignore unknown keys with a warning
  instead of raising.
- L1 lead escalation, authorized narrowly: `schemas/lighthouse-descriptor.schema.json`
  regenerated (kind enum gains RecallReceipt only) and `biome.json` gains one
  exclusion for `fixtures/policy-conformance` so canonical fixture bytes
  survive lint. Both added to the WP allowed list for those changes only.
- Engram team: the dev2/lead pair tripped the loop guard (8 messages per
  30 minutes) on ordinary WP setup traffic. Cleared with `codex-team reset`.
  Standing decisions given to the lead: devs use the main checkout's
  interpreter read-only (`/Users/kairos/Projects/engram/.venv/bin/python`)
  with their worktree as cwd and a per-dev `UV_CACHE_DIR` under /private/tmp,
  because linked worktrees carry no venv and the sandbox denies ~/.cache/uv;
  message traffic is batched one send per WP event. `jsonschema` 4.26.0 was
  already importable from the shared venv, so E1's tests can import it; the
  pyproject change stays on E1's branch.
- Follow-up for codex-team: `up` should provision an interpreter per worktree
  (symlink or uv sync) and set UV_CACHE_DIR in the launch scripts; the loop
  guard's default budget is too tight for a two-message brief plus
  acceptance relay.
- Both teams' devs could not commit: codex 0.152's workspace-write sandbox
  keeps a linked worktree's gitdir read-only, so `git commit` failed on
  `<repo>/.git/worktrees/<name>/index.lock` in every dev worktree. Verified
  with `codex sandbox` on a scratch repo: default config fails; an explicit
  `sandbox_workspace_write.writable_roots=["<repo>/.git"]` commits cleanly
  with cwd, /tmp, and $TMPDIR still writable; a narrower grant errors on
  `packed-refs.lock`. Launcher fixed with a test (codex-team 617df61), the
  six live launch scripts patched, the four dev panes respawned in place
  (`tmux respawn-pane -k`, pane ids preserved, worktrees untouched with all
  uncommitted work). Leads kept their context and were told to re-send
  assignments; leads get relaunched before integration. Uncommitted work at
  relaunch: L1 dev1 (RecallReceipt schema, protocol tests), L1 dev2 (policy
  fixtures, generator, biome exclusion), E dev1 (read-only Storage, protocol,
  policy tests), E dev2 (replay report, scoring.py, tests).
- Live verification of the sandbox fix: engram dev1 made the previously
  blocked commit from its relaunched pane (`011624d feat: add read-only
  Storage open path for publishers` on team/local-city-e/dev1). No git
  denials in any dev pane since the relaunch.
- Lighthouse team: dev1 committed Task 1 (`da8afa9` RecallReceipt artifact
  kind), dev2 committed Task 7 (`7e24d29` policy conformance fixtures);
  lead started cross challenge reviews. The dev1/lead pair tripped the loop
  guard a second time on legitimate traffic (16 and 15 messages per pair in
  30 minutes during the relaunch and review cadence); reset again, leads
  told to batch. The guard's 8-per-30-minutes default is a constant in
  codex-team's server.py; raising it for future teams and making it
  env-configurable is the next launcher change.
- E1 pre-gate complete: seven commits on team/local-city-e/dev1 (read-only
  Storage, canonical JSON and digests, policy evaluator with kit parity
  fixtures, socket frames, publisher daemon, receipts with strict schema,
  exporter 1.1). Full suite 1528 passed, 1 failed on the packaging lock
  check because the plan's `jsonschema>=4.23` direct dependency needs a
  uv.lock refresh. Decisions given to the lead: uv.lock refresh authorized
  on dev1's branch (its own commit, diff limited to jsonschema); the B0 gate
  stays closed tonight; dev1 gets one narrow extra WP, E1x, for the routing
  defect found tonight (load_config tolerates unknown keys with a WARNING,
  resolve_db_path logs its fallback instead of failing silently), limited
  to config.py's load_config/resolve_db_path and a new test file so it does
  not touch E2's MemoryConfig. This is an integrator decision outside the
  approved spec's lane scope; it is small, tested, and reversible.
