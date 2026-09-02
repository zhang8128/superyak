# B0 neighbor spike, census result

*2026-09-01. Lane B0 of the Lighthouse local city cycle. Read-only, against
SQLite backups of the instance stores. Recommendation first; the spike's
retrieval step did not run because the census made it moot.*

**Recommendation for `why` and `blocks` as publishers: no-go.** Both stores
hold zero work-lane rows, so the publisher daemon's work-lane-only rule would
return nothing from either. The recommendation needs no hand-judging: there
is nothing to judge.

**Neighborhood amended.** The spec's first neighborhood is now `engram`
receiving from a new `lighthouse` instance bound to `~/Projects/lighthouse`
(spec section 7, amended the same day). The spike's retrieval and judging
steps are to be re-run against `lighthouse` once it holds at least 30
work-lane episodes, and E1's receiver arm waits for that result.

## Census

| Instance | Episodes | Work-lane episodes | Work-lane semantics | Recalls logged | Last episode |
|---|---|---|---|---|---|
| engram | 312 | 54 | 24 | 305 | 2026-09-02 |
| why | 69 | 0 | 0 | 54 | 2026-03-21 |
| blocks | 69 | 0 | 0 | 54 | 2026-03-21 |
| agi | schema predates the lane column | | | | |
| claw | schema predates the lane column | | | | |
| gil | schema predates the lane column | | | | |
| code | store does not open | | | | |
| smart | empty directory | | | | |

Overlap by content hash:

| Pair | Shared episodes |
|---|---|
| why and blocks | 69 of 69 |
| why and engram | 46 of 69 |

The two candidate publishers are the same March 2026 snapshot under two
names. The 23 episodes they hold that `engram` does not are personal lane and
five months stale.

## Why the city has one house

Unbound projects route to the default instance. Every session in every
repository since spring has written to `engram`. The other instance
directories are either pre-migration relics or empty. This is a routing
outcome, not neglect, and it is the reason the second publisher has to be
created rather than found.

## What was done about it

- `~/Projects/lighthouse/.engram/config.toml` now binds that repository to
  instance `lighthouse`, with `[memory] default_lane = "work"` (read once
  E2's setting lands; until then, E3 re-lanes the store after E2 merges).
- `.engram/instances/lighthouse/graph.db` was created with the current schema
  (76 tables, lane column present) and is empty.
- Sessions in the lighthouse repository, including the L1 Codex team's, will
  populate it during this cycle.

## Re-run condition

```bash
sqlite3 "file:$HOME/Projects/engram/.engram/instances/lighthouse/graph.db?mode=ro" \
  "SELECT COUNT(*) FROM episodes WHERE lane='work'"
```

When this returns 30 or more, run Task B0 of the coordination plan with
`lighthouse` as the neighbor. The go threshold stays provisional: at least 4
of 20 hand-judged novel candidates useful at their turn.

## Artifacts

Store backups and the unrun spike script stayed in the session scratchpad and
were not preserved. Nothing here contains memory content.
