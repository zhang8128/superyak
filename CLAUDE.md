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

**Dedup:** LLM-based pragmatic equivalence via Ollama (default: `qwen3.5:27b`).
Falls back to embedding similarity if unavailable. `ENGRAM_DEDUP_MODEL` env var.

**Sleep-time consolidation:** On startup: decay → backfill orphaned vectors → prune → auto-compress.
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

**Knowledge graph:** Graphiti (Kuzu embedded) runs alongside engram for applied
knowledge — entities, relationships, temporal facts. Fed during compression,
queried during recall. Config: `ENGRAM_GRAPH_MODEL` env var (default: nemotron-nano).
Separate from identity layers.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `remember(content, core?, source?)` | Store an episode. `core=True` for formative memories, `source` for provenance. |
| `mark_core(episode_id)` | Retroactively mark an episode as core (exempt from decay). |
| `core_memories()` | List all core episodes. |
| `recall(query)` | Search across all layers. Returns `recall_id` for feedback. Scores hidden when dreaming. |
| `reflect(focus?)` | Self-observation: usage, gaps, instincts, instinct_contexts, instinct_clusters, contradictions. |
| `introspect()` | High-level self-portrait: kinds, instincts, health, activity. |
| `status()` | Layer counts, watcher state, session_id. |
| `compress()` | Manual compression cycle. |
| `log_outcome(recall_id, used)` | Feedback after recall. |
| `instinct_feedback(id, followed, context?)` | Strengthen/weaken instincts. `context` for situational learning. |
| `task_focus(name, content?)` | Start or resume a task context. Archives any previous active context. |
| `task_update(content)` | Update the active task context. |
| `task_done()` | Archive the active task context. |
| `dream_capture(reaction)` | Capture a raw emotional reaction. Compressed into opaque residue. |
| `dream_surface(n?)` | Surface dream residues from prior sessions. |
| `dream_react(residue_id, reaction)` | React to a residue. Reaction feeds the next cycle. |
| `dream_verify(recall_id)` | Reveal hidden scores from dream-influenced recall. Use after engaging. |
| `search_code(query)` | Search project source code via embeddings. |
| `reindex()` | Rebuild code index. |

## Key Files

| File | Role |
|------|------|
| `server.py` | MCP server — all tool definitions |
| `storage.py` | SQLite + vec0 storage layer |
| `compress.py` | Episode clustering, semantic promotion, instinct formation |
| `reflection.py` | Self-analysis (reflect, introspect) |
| `embeddings.py` | FastEmbed wrapper with instruction prefixes |
| `dreaming.py` | Dream residue — lossy emotional compression and surfacing |
| `clusters.py` | Community detection, cluster seeding, temperament computation |
| `dedup.py` | LLM-based duplicate detection |
| `indexer.py` | Source code indexing via tree-sitter |
| `watcher.py` | File system watcher for code changes |
| `config.py` | Environment and path configuration |
| `knowledge.py` | Graphiti bridge — entity extraction and temporal facts |
| `hooks/wake.py` | SessionStart hook — loads instincts into context on boot |

## Testing

```bash
.venv/bin/python -m pytest tests/ -q   # 179 tests
```

## Part of a System

| Repo | Role |
|------|------|
| **engram** (this) | Memory across sessions |
| **agi/** | Governance runtime |
| **blocks/** | Composable block implementations |
| **code/** | Block ratchet + codex-pair tooling |
| **why/** | Decisions, tasks, design rationale |
