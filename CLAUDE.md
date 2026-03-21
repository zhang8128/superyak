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
| **Episodes** | Raw experiences, verbatim | Decay 0.9x per session (rate-limited), pruned below 0.05 |
| **Core episodes** | Formative memories, exempt from decay | Auto-promoted when episodes spawn semantics |
| **Semantics** | Distilled facts, preferences, constraints | Promoted from episode clusters |
| **Instincts** | Perceptual attention directives (notice/implication) | Promoted from semantic patterns, context-gated |

**Embeddings:** nomic-embed-text-v1.5 (768-dim) via FastEmbed. Instruction
prefixes: `search_document:` (store), `search_query:` (recall), `clustering:` (compress).

**Dedup:** LLM-based pragmatic equivalence via Ollama (default: `qwen3.5:27b`).
Falls back to embedding similarity if unavailable. `ENGRAM_DEDUP_MODEL` env var.

**Sleep-time consolidation:** On startup: decay → backfill orphaned vectors → prune → auto-compress.
Decay is rate-limited (30min minimum between applications). Core episodes are exempt.
Centroid-based selection (most representative episode per cluster, MMR for diversity).

**Contextual instincts:** Instincts have dual vectors — a content vector (what it's
about) and a context vector (when it applies). Recall uses context vectors to surface
situationally relevant instincts. Feedback is per-context: followed/overridden in
"building" doesn't cancel out followed/overridden in "reflecting." Instincts are
framed as perceptual attention directives (`notice`: what to attend to, `implication`:
what follows) rather than behavioral rules.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `remember(content, core?, source?)` | Store an episode. `core=True` for formative memories, `source` for provenance. |
| `mark_core(episode_id)` | Retroactively mark an episode as core (exempt from decay). |
| `core_memories()` | List all core episodes. |
| `recall(query)` | Search across all layers. Returns `recall_id` for feedback. |
| `reflect(focus?)` | Self-observation: usage, gaps, instincts, instinct_contexts, contradictions. |
| `introspect()` | High-level self-portrait: kinds, instincts, health, activity. |
| `status()` | Layer counts, watcher state, session_id. |
| `compress()` | Manual compression cycle. |
| `log_outcome(recall_id, used)` | Feedback after recall. |
| `instinct_feedback(id, followed, context?)` | Strengthen/weaken instincts. `context` for situational learning. |
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
| `dedup.py` | LLM-based duplicate detection |
| `indexer.py` | Source code indexing via tree-sitter |
| `watcher.py` | File system watcher for code changes |
| `config.py` | Environment and path configuration |
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
