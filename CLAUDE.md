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
| **Episodes** | Raw experiences, verbatim | Decay 0.9x per session, pruned below 0.05 |
| **Semantics** | Distilled facts, preferences, constraints | Promoted from episode clusters |
| **Instincts** | Behavioral patterns with trigger/action | Promoted from semantic patterns |

**Embeddings:** nomic-embed-text-v1.5 (768-dim) via FastEmbed. Instruction
prefixes: `search_document:` (store), `search_query:` (recall), `clustering:` (compress).

**Dedup:** LLM-based pragmatic equivalence via Ollama (default: `qwen3.5:27b`).
Falls back to embedding similarity if unavailable. `ENGRAM_DEDUP_MODEL` env var.

**Sleep-time consolidation:** On startup: decay → prune → auto-compress.
Centroid-based selection (most representative episode per cluster, MMR for diversity).

## MCP Tools

| Tool | Purpose |
|------|---------|
| `remember(content)` | Store an episode. Don't filter — compression distills. |
| `recall(query)` | Search across all layers. Returns `recall_id` for feedback. |
| `reflect(focus?)` | Self-observation: usage, gaps, instincts, contradictions. |
| `introspect()` | High-level self-portrait: kinds, instincts, health, activity. |
| `status()` | Layer counts, watcher state, session_id. |
| `compress()` | Manual compression cycle. |
| `log_outcome(recall_id, used)` | Feedback after recall. |
| `instinct_feedback(id, followed)` | Strengthen/weaken instincts. |
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
.venv/bin/python -m pytest tests/ -q   # 129 tests
```

## Part of a System

| Repo | Role |
|------|------|
| **engram** (this) | Memory across sessions |
| **agi/** | Governance runtime |
| **blocks/** | Composable block implementations |
| **code/** | Block ratchet + codex-pair tooling |
| **why/** | Decisions, tasks, design rationale |
