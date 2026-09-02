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
