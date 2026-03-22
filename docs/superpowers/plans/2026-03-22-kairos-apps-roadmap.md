# Kairos Applications Layer — Build Roadmap

**Date:** 2026-03-22
**Prerequisite:** Platform (165 tests) + Runtime complete and committed.

## Build Order

| # | App | Source Repo | Tasks | Tests | Dependencies |
|---|-----|-------------|-------|-------|--------------|
| 1 | **Governor** | `why/` | 7 | ~44 | Bus, Memory, LLM, Ledger |
| 2 | **Ratchet** | `code/block-ratchet/` | 7 | ~84 | Bus, Ledger, Memory |
| 3 | **Atlas** | `claw/atlas/` | 8 | ~48 | LLM, Memory, Bus, Ledger |
| 4 | **Arena** | `agi/` | 8 | ~61 | LLM, Memory, Sandbox, Bus, Ledger |

**Total: 30 tasks, ~237 tests**

## Why This Order

1. **Governor first** — it's the observer/orchestrator. Validates bus pub/sub integration since it subscribes to everything. Relatively self-contained. Mostly a clean rewrite (source is scripts + specs, not a structured codebase).

2. **Ratchet second** — well-structured MCP server with 173 existing tests to reference. Exercises bus and ledger heavily. Needed before blocks migration since it manages block lifecycle.

3. **Atlas third** — research engine with complex but well-tested logic. Exercises LLM providers for synthesis and embeddings. Independent of other apps.

4. **Arena last** — most complex, exercises all platform modules including sandbox. Benefits from all other apps being stable since it coordinates goal execution across the system.

## Implementation Plans

- [Governor](2026-03-22-kairos-apps-governor.md) — priority rules, knowledge ratchet, observation via bus
- [Ratchet](2026-03-22-kairos-apps-ratchet.md) — multi-stage validation, tier graph, session coordination
- [Atlas](2026-03-22-kairos-apps-atlas.md) — research DAG, paper fetching, impact scoring, vault sync
- [Arena](2026-03-22-kairos-apps-arena.md) — fitness engine, cohort selection, decomposition, sandboxed execution

## After Apps

Once all four apps pass their tests against the platform:

1. **Blocks migration** — port 15 living blocks from `~/Projects/blocks/`
2. **Plugins** — MCP wrappers for Claude Code (engram plugin, ratchet plugin)
3. **Integration tests** — cross-app flows (Atlas publishes → Arena re-evaluates, Governor directs → Arena executes)
4. **Parallel run** — old and new systems process same inputs, compare outputs

## Validation Gates

Per the design spec:
- **App port:** existing test patterns pass + app can run 10 ticks against platform with zero errors
- **Parallel run:** 48hr dual-write period, outputs compared for consistency
- **Cutover:** new system runs solo for 1 week; old repos archived
