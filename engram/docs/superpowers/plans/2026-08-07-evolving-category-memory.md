# Contextual Stochastic Memory Program Plan

**Status:** Approved design; execute the linked plans in order

The research-backed design is split into two independently testable builds:

1. [Contextual Stochastic Recall](2026-08-07-contextual-stochastic-recall.md)
   implements the event store, sticky context posterior, sparse joint
   context-memory activation, reversible-context simulator, replay tooling, and
   fail-open server shadow integration.
2. [Durable Skill Transfer](2026-08-07-durable-skill-transfer.md) depends on the
   first plan and implements durable skill cores, context transport, fast local
   residuals, guarded consolidation, categorical path witnesses, and the dormant
   skill experiment.

Do not start the second plan until the first plan's full verification and
Experiment A acceptance report are committed. Neither plan authorizes live
ranking influence or automatic durable-core consolidation.
