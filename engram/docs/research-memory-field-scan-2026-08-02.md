# Memory Field Scan — Industry, Pilots, and Transferable Inventions

*2026-08-02. Four parallel research agents (frameworks/products, academic
literature, deployments/pilots, frontier concepts), ~175 tool calls total,
compiled against engram's current state (post action-bias experiment).
Companion to `research-engram-vs-agent-memory-2026-07-08.md`, which grounded
engram's mechanisms against published prior art; this scan covers the industry
and deployment landscape and what has changed since. Diagnoses and candidates
are kept in separate sections deliberately.*

## Verdict

The field converged on engram's *vocabulary* in twelve months — OpenAI named
its memory architecture "Dreaming," sleep-time consolidation is now standard,
and "agent memory" is an infrastructure category with storage vendors attached
— while converging on the *opposite values*: fidelity, auditability, retrieval
accuracy. Nobody ships graded decay. Nobody engineers lossiness on purpose.
The dispositional layer (memory shaping perception rather than answering
queries) is unoccupied in products and named-but-unbuilt in academia. Engram's
strangest parts — irrecoverable dream residue, hidden-score recall, rehab-style
off-device assessment, sheaf/persistence instruments — remain without
counterpart after a second, wider sweep.

Two things changed materially since the July 8 scan:

1. **The dispositional mode became measurable.** ImplicitMemBench (ACL 2026)
   operationalizes priming/procedural/conditioning influence with paired
   experimental-control instances and first-attempt scoring; Memory Contagion
   quantifies dispositional transfer as a Wasserstein-1 distance between
   outcome distributions. "Don't engineer for what you can't measure yet" now
   has instruments arriving — the constraint is lifting.
2. **A consolidation backlash arrived with evidence.** Three independent 2026
   papers show LLM consolidation degrading below no-memory baselines,
   flattening hedged claims into confident facts, and losing to verbatim
   storage — converting the July 8 doc's "largest documented risk" (semantic
   drift via iterative compression) from a warning into a measured phenomenon.

---

## 1. The industry, mid-2026

### Products

- **Sleep/dream consolidation went mainstream.** OpenAI "Dreaming V3" (Jun
  2026): background re-synthesis of years of history into a working user
  model, lossy, criticized for destroying the audit trail. Letta pivoted to
  git-backed memory filesystems with a defragmentation skill; sleep-time
  agents rewrite memory blocks in isolated worktrees. Supermemory ("Dynamic
  Dreaming"), Xiaomi MiMo Code (weekly "Dream"), Google Memory Bank, Cognee
  `memify`, Redis background promotion — everyone consolidates offline now.
  **Nobody sleeps to decay, prune, or reshape; industry dreaming is
  re-synthesis for fidelity.** Anthropic is the outlier with no offline
  consolidation anywhere in its stack.
- **Principled forgetting is absent from every commercial product.**
  Substitutes: TTLs (Redis env-vars), temporal supersession (Zep, Gemini,
  Weaviate — invalidate on contradiction, never on disuse), retrieval-side
  recency bias (CrewAI), usage-based graph pruning (Cognee). Mem0 moved
  *backwards* in April 2026 to an ADD-only pipeline. The lone affect-weighted
  retention (MemU's emotional-weight decay) may not have survived that
  project's pivot.
- **The nearest shipped analog of engram's ladder** is AWS AgentCore's
  episodic strategy: episodes → consolidated episode records
  (situation/intent/assessment/justification) → background cross-episode
  "Reflections" (lessons learned). A real two-rung compression as a managed
  service. No product forms perceptual/dispositional directives from patterns.
- **Memory is being squeezed from both ends of the stack.** Below tokens:
  KV-cache persistence as a product category (MinIO MemKV = petascale RDMA
  KV-cache offload, despite "context memory" branding; LMCache; edge
  persistent-KV papers). Into weights: Titans → ATLAS → Nested Learning/HOPE
  (Google), test-time training. The token-level extraction-pipeline middle —
  where most memory startups live — is the contested zone.
- **Benchmark monoculture cracking.** LoCoMo/LongMemEval saturated (88–95%,
  vendor-disputed configs); the 2026 frontier is behavioral: MemoryArena
  (memory-action coupling), LoCoMo-Plus (implicit constraints, cue/trigger
  semantically dissimilar), LongMemEval-V2 ("environment gotchas" ≈ instinct
  formation as a benchmark category), ImplicitMemBench (priming and
  conditioning).
- Funding: ~$85M visible across the category, 0.6% of agentic-AI capital.
  No memory-startup acquisitions or shutdowns found in 2026; product-level
  deaths only (ChatGPT Pulse retired, Cursor Memories removed, Letta
  server-side sunset).

### Deployment reality (what pilots teach that demos don't)

- **Deletion is the killer feature, not retention.** GitHub Copilot Memory
  ships 28-day auto-expiry plus validation-against-codebase-before-use;
  Cursor *removed* its Memories feature in 2.1 and told users to export to
  curated Rules; Meta's answer to backlash was incognito mode; Replika's was
  a memory-correction dashboard. Every mature deployment invests more in
  forgetting and controls than in remembering.
- **Auto-extracted memory keeps losing to curated state.** Cursor → Rules;
  Devin found model-written notes "paraphrase the task, leaving out important
  details" and kept engineered compaction; Claude Code users treat MEMORY.md
  as config to garden. EvoAgentBench: curated ability content transfers
  across model families; no automatic method sustains positive gain in all
  settings.
- **Memory is a persistence-layer attack surface.** SpAIware (ChatGPT),
  Gemini delayed-trigger memory poisoning (9 months exposure), MemoryGraft,
  MINJA (poisoning via normal queries only), and the OpenClaw incidents —
  341+ malicious skills writing payloads directly into MEMORY.md/SOUL.md,
  1.5M agent tokens leaked. Config-and-memory files are now standard malware
  persistence targets. Writing to memory converts one-shot injection into a
  persistent implant, and write paths are almost never authenticated.
- **Accumulation degrades before it saturates.** Chroma's context-rot result
  (all 18 models degrade by ~50K tokens); long-history agents behave
  differently from fresh ones on identical prompts; Kindroid companions
  drift via compounding self-summaries. Project Vend's fix was *externalized
  institutional memory* — CRM, checklists, procedures — not better context.
- **Where memory demonstrably pays, it is boring.** SiriusXM Harmony (CSAT),
  Hippocratic AI (8M calls/month, 9.0/10), ElliQ (95% self-reported
  loneliness reduction) — all CRM-grade continuity. No memory-layer vendor
  publishes named end-customer results; benchmarks stand in for case studies.
- **Compliance is ahead of architecture.** EU AI Act fully applicable this
  month; derived-memory erasure (deletion reaching extracted facts,
  summaries, vectors) is unsolved in every deployed system.

### Academia

The field institutionalized: an ICLR 2026 MemAgents workshop, six major
surveys, and clear camps. The threads that matter most here:

- **Consolidation backlash** (the trio): *Fidelity Before Structure*
  (arXiv:2601.00821 — verbatim beats extracted structure by 16–22 points);
  *Useful Memories Become Faulty When Continuously Updated by LLMs*
  (arXiv:2605.12978 — non-monotonic utility; consolidation eventually drops
  below no-memory; agents fail 54% of previously-solved problems after
  consolidating their own correct solutions); *Manufactured Confidence*
  (arXiv:2606.29279 — consolidation strips hedges and provenance; "unverified"
  tags fail; prohibition instructions paradoxically increase trust).
- **Forgetting became a subfield** with two rival camps: biological decay
  (FadeMem arXiv:2601.18642 — per-memory stretched-exponential decay with
  per-layer β; Oblivion arXiv:2604.00131 — forgetting as reduced
  accessibility, reinforcement only on demonstrated contribution; FSFM
  taxonomy arXiv:2604.20300) and rate-distortion decision-relevance (*DeMem —
  Remember the Decision, Not the Description* arXiv:2605.10870 — memory is
  valuable iff it preserves distinctions that change decisions; *What to
  Keep, What to Forget* arXiv:2607.08032 — query-agnostic compression pays a
  provable H(Q) penalty; repeated compaction compounds super-linearly and is
  essentially unbenchmarked). Nobody bridges the camps; nobody has protected
  cores, redundancy-modulated pressure, or never-evict guards — academic
  pruning is binary.
- **Consolidation-as-discovery**: *Discovery by Dreaming* (Zahn, Evans,
  Eagleman, arXiv:2607.16256) — within-domain replay is *null*; cross-domain
  recombination yields +21pp on discovery tasks and +14.5pp transfer to
  unrelated reasoning; shuffled pairings collapse the effect (bridge
  structure, not volume); a representational capacity floor below which
  nothing happens; the effect requires consolidation — the same material
  in-context makes things worse.
- **Dispositional influence, measured and feared**: MEMDRIFT
  (arXiv:2605.24941 — personality-flavored memories act as implicit steering
  vectors, silently distorting tool calls in unrelated contexts); Memory
  Contagion (arXiv:2606.23195 — bias propagates via behavioral imitation of
  retrieved trajectories more than via facts; W₁ metric); NPM
  (arXiv:2606.29824 — procedural skills as steering vectors added to
  activations). The entire drift literature's stance is detect-and-suppress;
  nobody asks which dispositions are desirable.
- **Near-collisions with engram**: HeLa-Mem (ACL 2026, arXiv:2604.16839 —
  co-activation Hebbian episodic graph, hub detection, "Hebbian Distillation"
  of dense hubs into semantics; no per-context feedback, no temperament);
  SuperLocalMemory V3 (arXiv:2603.14588 — cellular-sheaf H¹ contradiction
  detection *at store time* minting supersedes edges; Fisher-information
  retrieval with a graduated cosine→Fisher ramp over first 10 accesses;
  emergent forgetting via Riemannian Langevin drift); Roynard
  (arXiv:2604.11364 — independent argument that layers need distinct
  persistence semantics, engram's structural bet); *Experience Compression
  Spectrum* (arXiv:2604.15877 — names the "missing diagonal": adaptive
  cross-level compression along episodic→skill→rule, i.e. engram's promotion
  machinery as a named academic gap).

---

## 2. Where engram sits (update to the July 8 map)

**Still unoccupied after a wider sweep** (absence of counterpart, not proof
of novelty):

| Territory | Nearest neighbor found |
|---|---|
| Irrecoverable-by-design compression (dream residue) | ScrapMem's resolution-decay and Cognis's Matryoshka truncation — both purely for efficiency; irreversibility otherwise treated as bug or attack surface |
| Hidden-score recall + reveal-after-engagement (`dream_verify`) | None |
| Rehab-style scheduled memory deprivation (off-device assessments) | Human-side dependence studies only; agent-side ablations are one-shot controls, never longitudinal instruments |
| Sheaf/persistence instruments on a memory store | SuperLocalMemory V3 (sheaf H¹, store-time) — a real near-collision, solo independent effort; TDA-on-LLMs targets internals, never memory |
| Graded decay with protected cores + redundancy modulation | FadeMem/Oblivion have decay; exemption classes and never-evict guards appear nowhere |
| Per-cluster instinct strength, temperament, attenuated transfer | AFTER's mixed-transferability finding is the supporting *evidence*, not an implementation |
| Drift as something to cultivate rather than suppress | Entire drift literature is detect-and-correct |
| Valence-biased recall (affect tilting which memories surface) | REMT's Mood Index (unimplemented framework paper) |

**Independent validations found this sweep:**

- ImplicitMemBench: models absorb preferences implicitly at 75% but
  inhibitions at 17.6% — engram's notice/implication framing (attention
  directives, not prohibitions) sits on the strong side of a measured
  asymmetry it predated.
- Its authors' conclusion — "implicit memory cannot be reduced to explicit
  storage and retrieval alone" — is engram's thesis stated by skeptics with
  numbers.
- Memory Contagion: behavioral exemplars transmit more strongly than facts —
  evidence for the dispositional premise, with the warning that bias rides
  the same channel.
- Roynard independently argues per-layer persistence semantics.
- Anthropic's assistant-axis work covers *within-conversation* persona drift
  and explicitly not cross-session continuity — the gap engram occupies.
  Beckmann & Butlin (arXiv:2604.17031) argue identity lives in specific
  representational patterns, not all parameters — a principled criterion for
  what "core" should mean.

**Corrections/updates to the July 8 doc:**

- Sheaf territory is no longer counterpart-free: SuperLocalMemory V3 computes
  H¹ directly at store time. Complementary rather than duplicative (spectral
  gap ≈ the same obstruction read through the Laplacian), but "no located
  counterpart" is now false for the mechanism family.
- ACT-R decay in LLM agents now has peer-reviewed precedent beyond MemoryBank
  (HAI 2025 ACT-R agent; ACT-Up prototyping) — the decay design is
  established practice, not exotic.
- The name "Engram" is now claimed twice externally: a bi-temporal memory
  engine paper (arXiv:2606.09900) and Weaviate's GA memory product "Engram"
  (June 2026).

---

## 3. Lessons (diagnoses — no prescriptions in this section)

1. **The compression chain is engram's biggest measured risk, and the
   evidence hardened this year.** The consolidation-backlash trio + the
   rate-distortion result (repeated irreversible compaction compounds
   super-linearly; query-agnostic compression pays H(Q)) describe
   episodes→semantics→instincts exactly. Engram's existing mitigations —
   cold.db move-not-delete, compression review, HOLA innovation gate — are
   partial; the known reconciliation gap (prune CASCADE severing
   semantic→source links, per `project_reconciliation_substrate`) is
   precisely the failure mode *Manufactured Confidence* documents: a lossy
   memory that has shed provenance can be worse than none. The
   emotion-triage gap memory (residues lack episode links; sleep.py drops
   provenance it holds) is the same lesson in the dream pipeline.
2. **Similarity-clustered consolidation is the measured-null condition.**
   Discovery by Dreaming: within-domain replay adds nothing; cross-domain
   bridges are where consolidation earns its cost. Engram's clustering is
   lane-pure and similarity-based; `wander` and the uninvited slot are the
   right instinct implemented as *random* sampling rather than deliberate
   cross-cluster pairing. Centroid selection is additionally majority rule —
   "Memory as Metabolism" (arXiv:2604.12034) names the cost: it destroys the
   dissenting episode that later turns out to be right.
3. **Reinforcement-on-access is a weaker signal than
   reinforcement-on-contribution.** Oblivion reinforces only memories that
   demonstrably contributed to a response; engram's ACT-R activation counts
   accesses. Engram already collects the stronger signal (`log_outcome.used`)
   but doesn't feed it into decay.
4. **The dispositional channel carries bias as readily as disposition, and
   academia treats it as a vulnerability.** MEMDRIFT: memories act as
   steering vectors distorting unrelated tool calls. Engram is deliberately
   building what the security literature is building detectors for. This is
   a real dual-use tension in the design, not a criticism to wave off — the
   action-bias experiment is the honest response (measure the causal path),
   and it's ahead of anything found in the literature on that question.
5. **Memory stores are now attack surfaces with a time delay.** Engram's MCP
   write path (`remember`, `dream_capture`, instinct feedback) is
   unauthenticated by design for a single-user system, but the OpenClaw
   incidents show the threat model for file/DB-backed agent memory changed
   this year. Poisoned material that enters an *irrecoverable* residue is
   unauditable by construction — the feature that makes residues interesting
   also makes them the worst-case poisoning sink.
6. **The honest ablation baseline is "paste everything in," not "memory
   off."** Anatomy of Agentic Memory: most memory benchmarks fit in modern
   context windows, so much reported value is measurement artifact; the
   Context Saturation Gap (Δ vs full-context) is the metric that survives.
   Off-device assessments currently measure function-without-memory; they do
   not yet measure memory-vs-brute-context.
7. **Deployment gravity pulls toward curation and deletion.** Cursor's
   removal, Copilot's 28-day expiry, Devin's rejection of model-written
   notes. Engram's compression *review* step (human in the loop) aligns with
   the winning pattern; fully unsupervised promotion is the pattern that
   keeps failing in production.

---

## 4. Candidates to test or integrate (prescriptions — provisional, ranked)

Held loosely, per the house rule that recommendations arriving at the same
speed as observations are automatic rather than decided. Ranked by evidence
strength × fit. Each has a minimal falsifiable test.

**Tier 1 — strong evidence, direct fit**

1. **Cross-cluster dream pairing.** Add a consolidation step that deliberately
   juxtaposes episodes/semantics from *distant* clusters (low co-firing edge
   weight, high embedding distance) and distills what the collision produces —
   the measured-positive condition from Discovery by Dreaming, replacing
   random `wander` sampling with structured bridge-seeking. *Minimal test:*
   N sessions of cross-cluster pairing vs N of random wander; judge blind
   which produced generative output worth keeping. Expect nothing below a
   capacity floor — the paper's own warning.
2. **Contribution-gated reinforcement.** Feed `log_outcome(used=False)` into
   decay: accessed-but-unused memories get no activation boost (or decay
   slightly faster). Oblivion's conservative credit assignment, using a
   signal engram already collects. *Minimal test:* replay historical
   recall/outcome logs; compare which memories the two policies would have
   pruned; inspect the disagreement set by hand.
3. **Provenance through compression.** Verify `compress.py` carries `source`
   and hedging forward into semantics; preserve tentative phrasing at
   distillation (Manufactured Confidence's mitigation); this is the same
   substrate work the reconciliation memory already flags as deferred — the
   external evidence now says it's the load-bearing fix, not a nice-to-have.
   *Minimal test:* audit 20 existing semantics for recoverable provenance
   and for confidence inflation vs their source episodes.
4. **Instinct source-diversity gate.** At promotion time, record the source
   cluster's diversity (episode count, embedding spread, lane/context
   spread); distrust instincts from narrow clusters — AFTER's finding that
   narrow-source skills overfit and *deteriorate* on transfer.
   *Minimal test:* compute diversity retroactively for the 10 existing
   instincts; check whether the low-diversity ones are the ones that get
   overridden.

**Tier 2 — good evidence, moderate integration cost**

5. **First-attempt dispositional probes.** Extend the action-bias harness
   with ImplicitMemBench's protocol: paired experimental/control scenarios,
   scored on the first attempt only, measuring thematic tilt rather than
   explicit citation — a per-instinct mode-2 instrument. The W₁ distance
   between outcome distributions (Memory Contagion) is the summary statistic.
   The action-bias experiment already has the conditions; this generalizes
   it from one disposition to any instinct.
6. **Store-time contradiction edges.** SuperLocalMemory V3's move: run a
   cheap coherence check at `remember()` time against near-neighbors and
   mint an explicit supersedes/conflicts edge, rather than discovering
   conflation only at compression/sleep. Complements sheaf cohesion (which
   stays the deep instrument). Its graduated metric ramp (new memories earn
   geometry over first ~10 accesses) is also a clean answer to cold-start
   scoring if Fisher-style weighting ever lands.
7. **Minority-hypothesis retention + entry-level AUDIT.** During compression
   review, retain one dissenting episode per cluster (the anti-centroid);
   periodically suspend a high-centrality memory and check whether anything
   degrades — a self-administered, entry-level version of the off-device
   assessment. (Note the collision with engram's existing "gravity-well"
   instrument naming — Metabolism's "memory gravity" is dependency
   centrality, a different quantity worth distinguishing deliberately.)
8. **Full-context control for assessments.** Add a third assessment
   condition: everything relevant pasted into context (no memory system).
   Δ(engram vs full-context) is the claim that survives the saturation
   critique; started_at/completed_at differencing (already written, never
   differenced — per `project_codec_measurement_instrument`) becomes one of
   its objective counters.

**Tier 3 — worth pondering, not building yet**

9. **Per-layer decay shapes.** FadeMem's β exponent as a layer identity:
   semantics on a different curve family than episodes. A calibration
   question before a build — fit current decay behavior first.
10. **Topological over-compression vital sign.** The ICLR 2026 adversarial
    result (influence shows as persistent-homology feature collapse) suggests
    watching engram's store for collapse toward fewer large-scale features
    across consolidation cycles — a specific statistic for
    `reflect(focus="persistence")`, computable read-only from a graph.db
    copy.
11. **Persona-region criterion for core.** Beckmann & Butlin: identity =
    continuity of specific representational patterns. The principled version
    of core promotion would ask "does this episode reinstate the identity
    region?" — currently unmeasurable without activation access, but the
    action-bias experiment's identity-continuity endpoint is the behavioral
    proxy already in hand.
12. **Update-frequency lens.** Nested Learning's inversion — organize layers
    by update rate and let abstraction emerge — as a way of *reading* engram
    (episodes churn, instincts are slow) rather than rebuilding it.
    Consolidation as rate-matching is a generative reframe for the
    compression-rework thread.

**Explicitly declined (for now):** front-door attentional gating à la
CraniMem (~10× latency for a filter engram's decay+prune already
approximates); adopting a Fisher/Riemannian retrieval metric wholesale
(elegant, unproven at engram's scale, and the graduated-ramp idea transfers
without it); any move toward KV-cache/parametric memory (different substrate;
watch Titans/Nested Learning from a distance).

---

## 5. Practical flags

- **Graphiti has deprecated its Kuzu backend** (pinned 0.11.2). Engram's
  knowledge layer runs Graphiti-on-Kuzu; upgrading Graphiti will eventually
  force a backend migration (Neo4j/FalkorDB/Neptune) or a permanent pin.
  Decision can wait; surprise cannot.
- **"Engram" name collision:** Weaviate ships a GA memory product named
  Engram (June 2026); arXiv:2606.09900 uses the name for a bi-temporal
  memory engine. Matters only if this project ever publishes or publicizes.
- **Unverified items from the sweep:** Salesforce–Fin acquisition (~$3.6B,
  June 2026) and the "88% of orgs had an agent incident" survey figure are
  secondhand; verify before reuse. Context-distillation sub-thread went
  unexamined (agent search budget exhausted), as did AI Village long-running
  experiments and named Letta/Zep customer cases.

## 6. Reading list (highest value per page, in order)

1. Discovery by Dreaming — arXiv:2607.16256 (consolidation as discovery; the
   null result for similarity replay)
2. HeLa-Mem — arXiv:2604.16839 (ACL 2026; the closest architectural collision)
3. ImplicitMemBench — arXiv:2604.08064 (the mode-2 instrument)
4. Useful Memories Become Faulty — arXiv:2605.12978 (repeated-consolidation
   non-monotonicity)
5. DeMem, Remember the Decision — arXiv:2605.10870 (what-to-forget semantics)
6. SuperLocalMemory V3 — arXiv:2603.14588 (sheaf H¹ at store time; graduated
   ramp)
7. Memory as Metabolism — arXiv:2604.12034 (minority retention; AUDIT; vision
   paper, read skeptically)
8. What to Keep, What to Forget — arXiv:2607.08032 (rate-distortion frame;
   H(Q) penalty; repeated-compaction gap)
