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
