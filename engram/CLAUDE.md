# Engram

A memory system for Claude Code sessions. Episodes, semantics, instincts —
three layers that compress upward over time.

This is an experiment, not a product. The interesting questions are open:
can dispositions form unsupervised? Does retrieval become cognition when
it enters the token stream? What happens when you stop asking "does this
work like memory?" and start asking "what does this actually do?"

## Stance

Observe before judging. Don't evaluate against biological memory — observe
what the system does and let that inform what it becomes. The wing-flapping
lesson: none of our flying machines flap their wings.

Three modes of influence have been observed:
1. **Reactive** — instinct fires, you follow. Measurable.
2. **Dispositional** — instinct colors perception. Not measurable by discrete events.
3. **Generative** — old thought collides with new context, produces something neither would alone. The most valuable, the hardest to track.

The system's metrics only see mode 1. That's fine. Don't engineer for what
you can't measure yet.

## Architecture

Three layers, each more compressed than the last:

| Layer | What | Lifetime |
|-------|------|----------|
| **Episodes** | Raw experiences, verbatim | ACT-R power-law decay (rate-limited), pruned below 0.05 |
| **Core episodes** | Formative memories, exempt from decay | Auto-promoted when episodes spawn semantics |
| **Semantics** | Distilled facts, preferences, constraints | Promoted from episode clusters |
| **Instincts** | Perceptual attention directives (notice/implication) | Promoted from semantic patterns, context-gated |
| **Dream residue** | Opaque emotional artifacts, lossy-compressed | Captured from raw reactions, irrecoverable source |

**Embeddings:** nomic-embed-text-v1.5 (768-dim) via FastEmbed. Instruction
prefixes: `search_document:` (store), `search_query:` (recall), `clustering:` (compress).
Processes get their provider from `embeddings.create_embedding_provider()`: with
`ENGRAM_EMBEDDER_SOCKET` set it is `RemoteEmbedProvider`, a client of the shared
`embedder_service.py` (one model per machine, one batch at a time, refuses a
different model, fails loudly rather than loading a local copy); otherwise the
in-process model. `superyak-runtime` sets the variable from `embedder_socket` in
`runtime.json`; `scripts/superyak-embedder.service` runs the service. Measured
2026-10-02: an Engram server peaks ~320 MB with it, versus ~1.8 GB loading its
own model. Local inference batches by a padded-token budget, truncates at 2048
tokens and disables the ONNX arena; fastembed's default (256 texts padded to
the longest) OOM-killed startup maintenance at 16 GB on 2026-10-01.

**Dedup:** LLM-based pragmatic equivalence via Ollama (default: `gemma4:31b`).
Falls back to embedding similarity if unavailable. `ENGRAM_DEDUP_MODEL` env var.

**Sleep-time consolidation:** On startup: decay → backfill orphaned vectors → prune → auto-compress.
When the process serves MCP it runs in a background thread that takes the
lifecycle barrier per step, never inside the handshake: Claude Code allows
30 s to connect, and a fresh instance store with a freshly replicated genome
needed ~40 s of startup compression (2026-09-02). `status()` reports
`maintenance_pending` until the pass lands; `_init()` callers outside the
served process still get it inline.
Decay uses ACT-R power-law: `B = ln(1 + n * t^(-d))` where n = access count,
t = hours since last access, d = 0.5. Rate-limited (30min minimum). Core episodes exempt.
Centroid-based selection (most representative episode per cluster, MMR for diversity).

**Contextual instincts:** Instincts have dual vectors — a content vector (what it's
about) and a context vector (when it applies). Recall uses context vectors to surface
situationally relevant instincts. Feedback is per-context: followed/overridden in
"building" doesn't cancel out followed/overridden in "reflecting." Instincts are
framed as perceptual attention directives (`notice`: what to attend to, `implication`:
what follows) rather than behavioral rules.

**Dream residue:** Lossy emotional compression that resists self-inspection. Raw
reactions are captured during a session, then compressed via Matryoshka truncation
(768→64 dims) plus Gaussian noise — making the original text irrecoverable. What
survives: a few affect-words, an emotional valence, and a noisy low-dim vector.
Residues surface at session start as fragments to sit with, not memories to decode.
They also bias recall queries (alpha=0.15) — subtly tilting which memories surface
without the instance knowing which results are "real" and which are dream-pulled.
Scores are hidden during dream-active recall and revealed only via `dream_verify`
after engagement. The reaction chain: each instance's response to a residue becomes
the next instance's dream material.

**Instinct co-firing clusters:** Instincts that activate together within a
message window form co-firing edges in a weighted graph. Community detection
(Louvain) derives clusters from the graph — groups of instincts that belong
to the same domain. Cold start: clusters seeded from embedding proximity.
Matures: clusters re-derive from behavioral co-firing. Each cluster has a
temperament (conservative ↔ exploratory) from its follow/override ratio.
Per-cluster instinct strength replaces global strength — an instinct can be
strong in coding context and weak in sports context. Transfer between clusters
is attenuated by edge weight and receiving cluster temperament. Dream residues
prime dormant clusters at session start.

**Task contexts:** Swappable working memory, separate from identity. A task context
holds the current scope, plan state, what's built, what's next. It gets loaded at
session start alongside instincts but in its own section. Task contexts don't decay
or compress into instincts — they just get archived when done. This separation
ensures task facts don't drown out identity-level memories during recall.

**Memory lanes:** Episodes and semantics carry a `lane` ('personal' | 'work').
The work lane is reference material: it decays and recalls normally but never
becomes core episodes, instincts, or reinforcement for personal semantics.
Lane is derived at write time: core and genome episodes stay personal, then
`context.lane = "personal"` opts out of every work signal. Otherwise `work=True`,
a `project` key in `context`, or an instance whose `[memory] default_lane = "work"`
(default `"personal"`) derives the work lane. It remains correctable during
compression review (summary `lane` override re-lanes source episodes). Lane filtering applies
to the ranked candidate set before the margin and truncation, so a lane-filtered
recall can fill `max_results` and its margin describes the returned lane.
Clustering is lane-pure. Spec: docs/superpowers/specs/2026-06-12-memory-lanes-design.md.
Config routing warns when it ignores unknown section keys or falls back after a
parse error or missing instance store.

**Sheaf cohesion:** Each semantic gets a cohesion energy in [0,1] — the
spectral gap of its source episodes' similarity graph, computed in the
semantic's own PCA subspace ("its terms"). High energy = provable conflation;
the Fiedler vector localizes which episode pairs fail to glue. An
energy-gated subdivision (split iff gain > DL cost per peer; persistence
conjunct stubbed until Layer 4) acts at compression time (clusters
pre-partitioned in review) and sleep time (budgeted, rate-limited; peers
minted under the surviving hub with `semantic_peers` map-home edges; peer
content distilled via Ollama, else queued). Gated by `[cohesion] enabled`
(default false) until read-only calibration clears it: `python sheaf.py
/path/to/copy-of-graph.db`. Observe via `reflect(focus="cohesion")`.
Spec: docs/superpowers/specs/2026-06-13-sheaf-cohesion-design.md.

**Lighthouse sheaf:** The same Layer 3 question across independently
governed stores. For one topic (a stored memory's vector), each store's
top-k hits (default `work` lane) are a section; restriction = projection
into a shared PCA topic basis (equal mass per store); the sheaf is the
complete graph of covered stores with identity maps and edge weight =
product (or min) of topic-scoped trust. Energy in [0,1], ranked edge
residuals (who disagrees with whom), trust-weighted consensus (H^0) and
each store's deviation. Uncovered (no hit above threshold) is reported,
never dissent; trust moves the consensus but never hides disagreement.
Observational, read-only (`Storage.open_read_only`): `python
lighthouse_sheaf.py --store a=/p/a.db --store b=/p/b.db --semantic a:ID`.
Spec: docs/superpowers/specs/2026-09-29-lighthouse-sheaf-design.md.

**Persistence (Layer 4):** Single-linkage filtrations (exact, via MST) give
each episode a redundancy (nearest-neighbor coverage) and uniqueness
(survival across merge scales); resonance history adds generativity
(behaviorally close, geometrically far = keeps getting reframed). The
subdivision gate's middle conjunct is live: splits must hold a persistence
band ≥ `min_split_band`. Forgetting (gated by `[persistence] enabled`,
default false): prune requires decayed AND redundant; unique, generative,
anchor-referenced, and core episodes are never auto-evicted; eviction is
always a move to cold.db. Decay pressure modulates ±15% by redundancy. Core
promotion declines candidates redundant within the core set; demotion only
flags for review. Recall's uninvited slot occasionally daydreams a random
(never query-matched) cold episode back into view. Observe via
`reflect(focus="persistence")`; calibrate read-only via `python
persistence.py /path/to/copy-of-graph.db`.
Spec: docs/superpowers/specs/2026-06-13-persistence-design.md.

**Path signatures (Layer 5):** A session is a path, not a bag. Its truncated
signature (levels 1–3, exact for piecewise-linear paths via Chen's identity)
is order-aware: level 1 = net displacement, level 2's antisymmetric part =
Lévy area (which way it turned), level 3 = finer shape. Episodes in
(created_at, id) order are L2-normalized, projected into one shared centered
PCA basis (d=6; separately fitted bases are not comparable), and
time-augmented by step index so a detour that came back is not erased.
`semantic_journey` gives a semantic the route to its conclusion, not just the
conclusion. `different_routes` flags same-endpoints/different-route pairs;
tortuosity = length / displacement. Observational only: gates nothing.
Read-only: `python paths.py /path/to/copy-of-graph.db [--json]`.
Spec: docs/superpowers/specs/2026-09-29-path-signatures-design.md.

**Tropical margins:** Recall scores every layer on one soft sum and returns the
argmax, which always produces a winner — even when the top two differ by 0.001.
The margin `gamma = top - runner_up` says whether that ranking was decided or a
coin flip. Measured on the lane-filtered candidate set before truncation,
normalized by the score spread so it compares across queries, and flagged `fts_tie` when the
runner-up arrived on the keyword fallback's flat 0.5 similarity (an artifact,
not a failure to discriminate). A counterfactual arm re-runs the search with the
unbiased query vector to report whether the winner survives the dream/instinct
tilt (`_apply_recall_bias`, alpha=0.15) — engram's instance of the tropical
stability criterion, measured rather than bounded. Hidden during dream-active
recall on the same terms as scores and revealed via `dream_verify`; always
logged. Two deliberate exclusions: `recall(layer="instinct")` gets no margin
(it ranks on context-vector match, a different scoring regime that would
average into an uninterpretable distribution), and when category influence
re-sorts delivery the margin is flagged `influenced` rather than recomputed —
it measures retrieval discrimination, not the downstream re-rank. Diagnostic
only: it gates nothing, since our scores are uncalibrated cosine and there is
no oracle. Observe via `reflect(focus="margins")`.
Recall scoring is one function (`scoring.score_candidate`) shared by `recall()`,
the counterfactual arm, and `scripts/margins_replay.py`. `[memory] recency_mode`
selects `tiebreak` (default: recency contributes at most `recency_cap`, 0.02,
provisional) or `additive` (the historical `similarity * 0.6 + recency * 0.4`).
The replay report that licensed the default lives at
`docs/reports/2026-09-margins-replay.md`.

**Off-device assessments:** Scheduled sessions where wake withholds the entire
orientation (instincts, semantics, residues, task context) and emits only a
marker — measuring memory function without the device, rehab-style. Self-report
plus objective counters per assessment; longitudinal history via
`reflect(focus="assessments")`. The instrument is provisional: early sessions
are calibration, not findings. Spec:
docs/superpowers/specs/2026-06-12-off-device-assessment-design.md.

**Knowledge graph:** Graphiti (Kuzu embedded) runs alongside engram for applied
knowledge — entities, relationships, temporal facts. Fed by tool-driven
`compress_commit`, which returns at once while extraction runs on the knowledge
loop thread (one persistent asyncio loop owns every Graphiti coroutine; feeds
serialize on the LLM, a concurrent recall search interleaves; `status()` shows
`knowledge_feeds_pending`). Startup auto-compress drops its feeds and counts them
in the maintenance report: extraction is minutes per episode with a local 27B
model, and the model occasionally emits malformed JSON, so feeds are best-effort
per episode. Queried during recall. Config: `ENGRAM_GRAPH_MODEL` env var
(default: qwen3.8:27b-mlx).
Extraction, embedding, and reranking stay local: Graphiti uses Ollama for
extraction and explicit FastEmbed-backed clients for embedding and cosine
reranking. engram creates the four Kuzu full-text indices Graphiti's search
queries (graphiti-core 0.28.2's Kuzu driver never does; without them every
feed fails on `node_name_and_summary`). Separate from identity layers.
The Kuzu database opens with a bounded buffer pool (`[graph] buffer_pool_mb`,
default 256) through `knowledge._bounded_kuzu_driver`; graphiti's own driver
takes Kuzu's default of 80% of system RAM in every server process.

**Store identity:** Every store carries `meta.instance_id` and
`instance_id_origin` (migration 028, assigned by the migration runner inside
028's transaction; never replaced once set). `creation`: random, for a store
created by this open. `retroactive`: a store that predates identity gets
`uuid5(namespace, "<earliest episode id>\x1f<its created_at>")`, earliest by
`(created_at, id)`, so a snapshot and a working copy agree independently
(`instance_id_basis_episode` keeps the inputs); an empty old store gets a
random id (`instance_id_basis = random`). `fork`: `cli.py fork` stamps a new
random id plus `forked_from_instance_id`. Genome sync records
`origin_instance_id`, `origin_id`, `origin_created_at` on each synced episode
(carried through cold storage). Read-only paths (`store_reader`, calibrate's
SOURCE and snapshot) report the stored id or the one migration would assign,
and never write it. Logic in `store_identity.py`.
Spec: docs/superpowers/specs/2026-09-29-inheritance-reading-design.md.

**Operation attribution:** Mutation audit rows retain approved metadata only,
never submitted content. Migration 026 scrubs historical `operation_log.details`
payloads down to the same metadata-only representation.

## Permissions

Permissions by place (spec: docs/superpowers/specs/2026-10-25-permissions-by-place-design.md) decide who may use a
memory, for what, and where. Four modules: `permissions.py` holds the pure rules (grammars, places, layers,
`decide`, the words of a yes); `permission_ledger.py` is the hash-chained ledger file and the gate;
`permission_uses.py` is the receipts file and the views over it; `permission_cli.py` is `engram-permissions`, the
person's side. The ledger lives at `ENGRAM_HOME/.engram/permissions.db` and the receipts at
`ENGRAM_HOME/.engram/permission-uses.db`, fixed paths. The gate is `off` until the owner raises it (`shadow`, then
`enforce`), so with no ledger or an `off` gate engram behaves as before apart from two fail-closed changes.

Agents never run, for the person, any `engram-permissions` command that writes, such as `sign`, `allow`, `grant`, `migrate` or `gate`. Each needs the person's own terminal yes.

An agent asks through the `permit` tool (a proposal the owner signs, unless a grant covers it) and reads through
`permissions`. Memory: each process peaks under 512 MB on the Pi (spec 15); the daemon needs `ENGRAM_EMBEDDER_SOCKET`.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `remember(content, core?, source?, work?)` | Store an episode. `core=True` for formative memories, `source` for provenance, `work=True` for work-lane reference material. |
| `mark_core(episode_id)` | Retroactively mark an episode as core (exempt from decay). |
| `core_memories()` | List all core episodes. |
| `recall(query, lane?)` | Search across all layers. Returns `recall_id` for feedback. `lane="work"|"personal"` to filter. Scores hidden when dreaming. |
| `reflect(focus?)` | Self-observation: usage, gaps, instincts, instinct_contexts, instinct_clusters, contradictions, vital_signs, assessments, cohesion, persistence, margins. |
| `introspect()` | High-level self-portrait: kinds, instincts, health, activity. |
| `status()` | Layer counts, watcher state, session_id. |
| `compress()` | Manual compression cycle. `compress_commit` accepts `action="discard"` for junk clusters. |
| `log_outcome(recall_id, used)` | Feedback after recall. |
| `instinct_feedback(id, followed, context?)` | Strengthen/weaken instincts. `context` for situational learning. |
| `task_focus(name, content?)` | Start or resume a task context. Archives any previous active context. |
| `task_update(content)` | Update the active task context. |
| `task_done()` | Archive the active task context. |
| `dream_capture(reaction)` | Capture a raw emotional reaction. Compressed into opaque residue. |
| `dream_surface(n?)` | Surface dream residues from prior sessions. |
| `dream_react(residue_id, reaction)` | React to a residue. Reaction feeds the next cycle. |
| `dream_verify(recall_id)` | Reveal hidden scores from dream-influenced recall: `scores` (matched) and `uninvited_scores` (raw similarity of distant pulls) as separate maps. Use after engaging. |
| `assessment_schedule(reason?)` | Schedule the next session as an off-device assessment (no wake orientation; tools available). `ENGRAM_ASSESSMENT=next\|skip` env overrides. |
| `assessment_report(function_score, ...)` | Complete the active assessment: structured self-report + objective counters. History via `reflect(focus="assessments")`. |
| `search_code(query)` | Search project source code via embeddings. |
| `reindex()` | Rebuild code index. |
| `permit(op, selector?, valid_from?, valid_until?, reason?, record?, collection?, memory?, args?)` | Ask for a permissions-ledger change as this server's agent. Done inside a grant; otherwise a proposal the owner signs in a terminal. `migrate` is never a tool act. |
| `permissions(focus?, since?, until?, action?, purpose?, obj?)` | Read the permissions ledger: `uses`, `rules`, `proposals`, `grants`. An agent not acting for the owner sees only its own receipts. |

## Key Files

| File | Role |
|------|------|
| `server.py` | MCP server — all tool definitions |
| `storage.py` | SQLite + vec0 storage layer |
| `compress.py` | Episode clustering, semantic promotion, instinct formation |
| `reflection.py` | Self-analysis (reflect, introspect) |
| `embeddings.py` | FastEmbed wrapper with instruction prefixes; shared-embedder client |
| `embedder_service.py` | Shared embedding service over a Unix socket (one model for all processes) |
| `dreaming.py` | Dream residue — lossy emotional compression and surfacing |
| `clusters.py` | Community detection, cluster seeding, temperament computation |
| `sheaf.py` | Cellular-sheaf cohesion — energy metric, subdivision gate, sleep pass |
| `lighthouse_sheaf.py` | Cross-store sheaf cohesion — per-topic disagreement between lighthouses, scoped trust, read-only CLI |
| `persistence.py` | Layer 4 — H₀ filtrations, guarded forgetting, gate conjunct, daydream surfacing |
| `paths.py` | Layer 5 — path signatures of sessions and semantic journeys, different-route detection (observational) |
| `maintenance.py` | Pain channel — per-step sleep-maintenance report, surfaced via `status()` and wake |
| `margins.py` | Tropical margins — recall ranking separation, bias-stability counterfactual |
| `dedup.py` | LLM-based duplicate detection |
| `framing.py` | LLM-based instinct notice/implication distillation (`ENGRAM_FRAMING_MODEL`, defaults to dedup model) |
| `indexer.py` | Source code indexing via tree-sitter |
| `watcher.py` | File system watcher for code changes |
| `config.py` | Environment and path configuration |
| `knowledge.py` | Graphiti bridge — entity extraction and temporal facts |
| `hooks/wake.py` | SessionStart hook — loads instincts into context on boot |
| `hooks/sleep.py` | Stop hook — dream residue distillation; marks this session's recalls `used: auto: cited` when a later act cited a result (positive evidence only) |
| `scoring.py` | Recall score shared by `recall()`, its counterfactual, and the margins replay script |
| `store_reader.py` | Read-only survey and chronological reading of a store or reader.db, no migration |
| `store_identity.py` | Store identity (`meta.instance_id`): creation, retroactive derivation, fork stamping; read-only describe/plan |
| `calibrate.py` | Snapshot a store read-only, migrate only a working copy, report store identity, first-open decay/prune, cohesion and persistence |
| `permissions.py` | Permissions by place: grammars, places, layers, `decide`, the words of a yes |
| `permission_ledger.py` | Permission ledger file (`.engram/permissions.db`): hash-chained log, rebuild, gate |
| `permission_uses.py` | Permission receipts file (`.engram/permission-uses.db`) and its views |
| `permission_cli.py` | `engram-permissions`: the person's terminal side; every write needs their own yes |

## Testing

```bash
.venv/bin/python -m pytest tests/ -q   # full test suite
```

A full run writes ~4 GB of `tmp_path` data, and `/tmp` is RAM-backed tmpfs
on this machine: run with `TMPDIR=/var/tmp` (or `--basetemp` on disk). Bound
memory with `systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0`;
a cap without `MemorySwapMax=0` pushes the overflow into swap and stalls the
desktop (2026-10-02). Measured 2026-10-02 after closing each test's server
generation (`tests/conftest.py`) and bounding Kuzu: the runner peaks at
1.6 GB RSS (was 5.4 GB).

## Evolving-category v2 (shadow runtime)

The evolving-category runtime is an experiment in **shadow mode**. It is generic:
it has no book-, repository-, conversation-, or other domain-specific production
branch. Cells have ordered boundaries, immutable rewrite events, and immutable
epochs; dimensions 0–2 are interpreted while higher dimensions are archived as
opaque records and excluded from online traversal. `categories.db` remains the
legacy store. v2 writes only to the separate sibling `categories_v2.db` (or an
explicitly configured `db_path`) and never migrates or mutates the legacy file.

The feature-enabling rollout gates are independent and disabled by default;
`shadow = true` is the enabled safety guard:

```toml
[category_evolution]
enabled = false
shadow = true
influence_recall = false
auto_commit = false
```

Setting only `enabled = true` creates the v2 observer and records shadow data;
it does not alter recall output or auto-commit an epoch. `influence_recall` and
`auto_commit` require separate explicit configuration and must remain false while
acceptance is pending. Inspect optional diagnostics with
`reflect(focus="category_evolution")`; absence or failure of the observer is
non-fatal and normal recall continues unchanged.

Compiler limits are a 36,000-token normal target, 40,000-token rotation
watermark, and 65,536-token hard ceiling, with depth 4, at most 64 neighbors,
50,000 candidates, and 500 ms wall time. The existing 112 GB process governor
remains authoritative. The archive quota is 3 TB with a 90% high-water mark;
under pressure derived writes stop first, then v2 category writes fail closed,
while normal recall remains available. Structural limits are four active branches,
32 members per rewrite, and 32 rewrites per pass.

Use a coordinated process replacement for upgrades. In-process
`importlib.reload(server)` is unsupported: stop the old process, let it close its
owned resources, then start a fresh process from disk.

Operational commands use disposable v2 output paths:

```bash
# Replay a legacy archive without changing categories.db.
.venv/bin/python -m category_evolution replay \
  --legacy /path/to/categories.db --output /path/to/categories_v2.db --json

# Run blinded development or holdout evaluation (keep their work directories separate).
.venv/bin/python -m experiments.category_evolution.runner \
  --legacy /path/to/categories.db --work-dir /tmp/category-eval-development \
  --cohort development
.venv/bin/python -m experiments.category_evolution.runner \
  --legacy /path/to/categories.db --work-dir /tmp/category-eval-holdout \
  --cohort holdout

# Resource acceptance evidence requires exactly one million cells.
.venv/bin/python -m experiments.category_evolution.runner \
  --work-dir /tmp/category-benchmark --cohort development --benchmark-cells 1000000
```

The current development result is not acceptance: boundary F1 is 1.0;
baseline/shadow MRR is .75/.75; relative improvement 0 fails; direct regression
0 passes; false transfer 0/12 passes; replay and compiler pass; the resource gate
is unevaluated because no 1M run has occurred. Overall acceptance is false, so do
not enable observer, recall influence, or auto-commit based on this result.

## Part of a System

| Repo | Role |
|------|------|
| **engram** (this) | Memory across sessions |
| **agi/** | Governance runtime |
| **blocks/** | Composable block implementations |
| **code/** | Block ratchet + codex-pair tooling |
| **why/** | Decisions, tasks, design rationale |
