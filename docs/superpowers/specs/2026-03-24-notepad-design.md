# Notepad: Traversable Working Reference

A lightweight reference graph for mid-session use. Not ambient context — a tool
you pick up when you're coding and put down when you're not.

## Problem

Within a session, the same facts get rediscovered multiple times: class names,
API signatures, file paths, dimension mismatches. Memory (episodes, semantics,
instincts) is the wrong tool — these are working references, not experiences
worth compressing. There's no fast way to jot and retrieve them.

## Design

### Nodes

A node is a key-value note with optional tags.

```
jot("embed", "NomicEmbedProvider, 768-dim, in embeddings.py", tags=["api"])
jot("episode_vectors", "vec0, expects 768-dim float[]", tags=["schema"])
jot("emma db", "/sandbox/emma/engram.db, same Storage class", tags=["path"])
```

### Edges

No explicit edge table. Proximity is the graph. Nodes jotted in the same
session or sharing tags are implicitly related. When you `look` something up,
nearby nodes surface alongside the match.

### Scope

Two databases:
- **Global**: `~/.engram/notepad.db` — facts that apply everywhere
- **Project**: `.engram/notepad.db` under project root — project-specific

`look` searches both, project-first.

### MCP Tools

| Tool | Purpose |
|------|---------|
| `jot(key, value, tags?, scope?)` | Write or update a note. Scope defaults to project. |
| `look(query)` | Fuzzy search across keys, values, tags. Returns matches + co-session neighbors. |
| `erase(key)` | Remove a note. |

### Schema

```sql
CREATE TABLE notes (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    tags JSON,
    scope TEXT NOT NULL DEFAULT 'project',
    session_id TEXT,
    accessed_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE notes_fts USING fts5(
    key, value, tags,
    content=notes, content_rowid=rowid
);
```

### Retrieval

`look(query)` does FTS across key, value, and tags. For each match, also returns
other notes from the same session (co-session proximity = implicit edges). Results
are ranked by: FTS relevance first, then accessed_count as tiebreaker.

No embeddings. No vectors. Direct text matching is the right tool for reference
lookup — you roughly know what you're looking for, you just can't remember the
exact value.

### Example

```
# While working, I discover the right embedder
jot("embed", "NomicEmbedProvider, 768-dim, in embeddings.py")
jot("episode_vectors", "vec0, expects 768-dim")

# Later in the same session or next session
look("embed")
# → embed: NomicEmbedProvider, 768-dim, in embeddings.py
#   also jotted nearby: episode_vectors (vec0, expects 768-dim)

look("768")
# → embed: NomicEmbedProvider, 768-dim, in embeddings.py
# → episode_vectors: vec0, expects 768-dim
```

### What This Is Not

- Not memory. Notes don't decay, compress, or form instincts.
- Not ambient context. Nothing loads at session start.
- Not a code index. The tree-sitter indexer handles structure. This handles gotchas.
- Not a wiki. No formatting, no hierarchy. Sticky notes with string.

## Files

| File | Role |
|------|------|
| `notepad.py` | Storage + retrieval logic |
| `server.py` | Three new MCP tools: `jot`, `look`, `erase` |
| `migrations/014_notepad.sql` | Schema (applied to both global and project dbs) |

## Testing

- `jot` creates/updates notes
- `look` finds by key, value substring, tag
- Co-session proximity surfaces related notes
- Project scope searched before global
- `erase` removes notes and FTS entries
- FTS sync triggers work on insert/update/delete
