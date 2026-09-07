# Engram vs. Published Agent-Memory Research — Grounded Comparison

*2026-07-08. Deep-research harness: 5 search angles → 22 sources fetched → 106
claims extracted → 25 adversarially verified (3-vote, need 2/3 to kill) → 17
confirmed, 8 refuted. 104 agents. Full raw output was task `wjhk096fx`; this is
the distilled, human-readable record.*

## Verdict

Engram's **core mechanisms are grounded prior art, not frontier**. Its layered
episodes→semantics→instincts structure maps onto the Feb-2026 foundation-agent
memory taxonomy; ACT-R power-law decay, sleep-time consolidation, guarded
forgetting, and even "dreaming" random walks all have published counterparts.
Where engram feels most novel (dream residues, wandering) the literature has
partial analogues. Where it may genuinely stand alone (sheaf cohesion,
persistent-homology forgetting, off-device assessment) the evidence is *absence
of a located counterpart*, not verified novelty — those affirmative-novelty
claims failed verification for insufficient support.

The real distinctiveness is **purpose, not mechanism**: the literature optimizes
memory for task performance (QA accuracy, token reduction, benchmark wins);
engram optimizes for a memory whose *subject is its own identity* — one that
dreams, wanders, and assesses itself off-device. The "no counterpart" features
cluster around affect, topology, and self-assessment precisely because nobody
optimizing HotpotQA would build them. That is the emergent boundary.

## Confirmed findings

1. **Layered structure + decay/prune/dedup is standard practice**, not novelty —
   maps onto the foundation-agent taxonomy (arXiv 2602.06052); hygiene ops
   corroborated by MemoryBank, MemGPT/Letta, Mem0, FadeMem.
2. **ACT-R decay has direct precedent** — MemoryBank (Ebbinghaus, AAAI 2024) and
   an ACT-R LLM dialogue agent (HAI 2025). Engram diverges in the decay *law*:
   it uses ACT-R power-law `B = ln(1 + n·t^(−d))`, d=0.5; MemoryBank and SCM use
   exponential decay.
3. **Engram's activation is fully deterministic**; canonical ACT-R (and the HAI
   2025 agent) include a stochastic activation-noise term. Engram's stochasticity
   lives at the *slot* level (uninvited/cold/daydream slots, dream shuffling,
   wander), not in activation scoring. Design gap, not defect — see open Q3.
4. **Sleep-time consolidation is biologically grounded** — Tadros et al. (Nature
   Comms 2022) show unsupervised, input-free replay reduces catastrophic
   forgetting. SCM implements NREM (Hebbian + homeostatic downscaling) + REM
   "dreaming" random walks; Memory Bear runs a sleep self-reflection pass that
   detects conflicting memories (which engram splits into sheaf cohesion).
5. **Largest documented risk = semantic drift via iterative compression.** Each
   lossy pass silently discards low-frequency detail until only a sanitized,
   generic history remains. Engram's episodes→semantics→instincts chain is
   exactly this pattern. One of three cumulative failure modes (poisoning at
   ingestion, drift at consolidation, conflict/hallucination at retrieval) that,
   unlike static RAG, compound because errors re-enter the write loop.
6. **Published remedy = immutable ledger + periodic reconciliation** (SSGM
   Theorem 1: drift O(T·ε) → O(N·ε)). Engram *partially* has the anchor
   (cold.db) but **no reconciliation operator** — and see the caveat below: the
   anchor is weaker than it looks.
7. **Small local models silently corrupt memory writes** at 17–30% malformed-
   output rates ("Anatomy of Agentic Memory", arXiv 2602.19320). Relevant to
   engram's Ollama dedup/framing/knowledge extraction — *but* engram's write
   paths validate JSON and fall back to heuristics on failure (fail-safe), so
   the residual risk is well-formed-but-wrong distillation, not malformed output.
8. **Proactive interference** from stale entries degrades retrieval log-linearly
   toward chance, regardless of context length, resisting prompt-engineering
   (arXiv 2603.14517, PI-LLM 2506.08184). Applies analogically to stale entries
   entering engram's recall stream.
9. **Guarded forgetting has convergent prior art** — Memory Bear's graded
   "pending-forget" soft-deletion ≈ engram's move-to-cold.db instead of
   destructive deletion.
10. **Frontier features are narrower than they appear.** Dream residues/wandering
    have partial counterparts (SCM REM walks, Emotional RAG); conflict-in-sleep
    exists (Memory Bear). Only sheaf cohesion, persistent-homology forgetting,
    and off-device assessment lack a located counterpart — held provisionally.

## Refuted (did NOT survive verification — do not over-claim these)

- "External memory is structurally unnecessary because benchmarks fit in context" (1-2).
- The survey's future-directions list proves engram's features are novel (1-2).
- Episodic→semantic consolidation is rarely automatic, so engram fills a gap (0-3).
- Selective forgetting is almost untested, so engram targets an open frontier (1-2).
- Decay-only is insufficient for proactive interference (1-2) — so do **not**
  claim engram's decay fails here; only that stale accumulation is a real risk.
- Memory bloat as a forgetting rationale (1-2); sleep-consolidation reproducible
  in ACT-R/CLS (0-3); Memory Bear uses the exact ACT-R base-level sum (1-2).

## Caveats

Only three peer-reviewed anchors (MemoryBank AAAI 2024, ACT-R HAI 2025, Tadros
Nature Comms 2022); most sources are 2025–2026 arXiv preprints. SCM and Memory
Bear are single-author/company preprints with grandiose framing — **only their
architectural descriptions are trusted, never their benchmark claims**. Several
engram-specific bridges are the analyst's judgment, not stated in sources
(notably the small-model corruption rate, measured for other models). Fast-moving
literature: "no counterpart" judgments could be overturned by later work.

## Open questions (highest-value things to measure)

1. Does additive promotion + core-exemption actually prevent drift in practice,
   or does prune still leave compressed layers to drift toward generality?
   *(Partially addressed 2026-07-08 by the semantic-fidelity read.)*
2. What is engram's *actual* distillation-fidelity rate for its own models
   (gemma4:31b, nemotron-nano)? *(Embedding-proxy now measurable via
   `reflect(focus="fidelity")`; LLM-judged rate still unmeasured.)*
3. Would an ACT-R activation-noise term help, or does slot-level stochasticity
   already deliver the benefit? *(Bet: already covered. Test before adding.)*
4. Do engram's graph structures exhibit hub dominance / gravity wells?
   *(Answered 2026-07-08: yes — `reflect(focus="vital_signs")` degree-Gini ≈ 0.60;
   instrumented, no remedy built yet.)*

## Follow-through shipped this session

Branch `feat/reflect-drift-instrumentation`:
- **Gravity-well vital sign** (open Q4) — degree-Gini over connected nodes.
- **Semantic-source fidelity read** (open Q1/Q2) — embedding-based, no LLM.
- **Finding:** reconciliation (finding 6) is blocked — prune's `ON DELETE
  CASCADE` severs semantic→source links, so cold.db preserves episode text but
  not the provenance index. The immutable-ledger anchor is weaker than finding 6
  assumed. Substrate fix deferred as an architectural fork.

## Sources

Primary: arXiv 2602.19320 (Anatomy of Agentic Memory), 2602.06052 (foundation-
agent memory survey), 2603.07670, 2603.11768 (SSGM), 2604.20943 (SCM),
2512.20651 (Memory Bear), 2603.14517 + 2506.08184 (proactive interference),
2410.23041 (Emotional RAG), 2202.04579 (Neural Sheaf Diffusion); DOI
10.1145/3765766.3765803 (ACT-R HAI 2025); PMC9755223 / Nature s41467-022-34938-7
(Tadros et al., sleep replay).
