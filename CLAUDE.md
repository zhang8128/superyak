## Engram Memory System

Layered memory: episodes (raw experiences), semantics (distilled knowledge),
instincts (behavioral patterns). Three-tier architecture for storage, retrieval,
and maintenance.

### Embedding Model

Uses **nomic-embed-text-v1.5** (768-dim) via FastEmbed with instruction prefixes:
- `search_document:` — for storing memories (remember)
- `search_query:` — for retrieval (recall, search_code)
- `clustering:` — for compression/dedup (auto-compress)

### Deduplication

LLM-based pragmatic equivalence via Ollama (default: `qwen3.5:27b`). Detects
that differently-worded statements express the same preference/constraint.
Only runs during compression, not on every recall. Falls back to embedding
similarity if Ollama is unavailable. Configure model via `ENGRAM_DEDUP_MODEL` env var.

### Memory Decay

Episodes decay by 0.9× each session start. Accessed episodes get +0.1 strength
boost. Compressed episodes below 0.05 strength are pruned. Uncompressed episodes
are never pruned. This implements Ebbinghaus-style forgetting — memories that
aren't useful fade naturally.

### Sleep-Time Consolidation

On server startup: decay → prune → auto-compress. This is the maintenance
window between sessions. Auto-compress uses centroid-based selection (not
concatenation) — picks the most representative episode per cluster, or MMR
for diverse selection in larger clusters.

### Usage

**Reading:** `recall(query)` searches across all layers. `introspect()` for
self-portrait. `status()` for layer counts.

**Writing:** `remember(content)` stores raw episodes. Don't filter — the
system distills meaning during compression.

**Feedback:** `log_outcome(recall_id, used)` after recall. `instinct_feedback(id, followed)`
to strengthen/weaken instincts.

**Maintenance:** `compress()` for manual compression. `reflect()` for pattern analysis.

### Testing

```bash
.venv/bin/python -m pytest tests/ -q   # 123 tests
```
