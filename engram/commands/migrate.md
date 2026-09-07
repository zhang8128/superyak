---
description: Import existing MEMORY.md entries into the Engram knowledge graph
---

Migrate flat MEMORY.md memory entries into the Engram knowledge graph.
This is a one-time operation that:

1. Reads the project's MEMORY.md index file
2. Reads each referenced memory file
3. Extracts entities and relationships from each entry
4. Stores them in the Engram graph with proper typing and linking

After migration, the knowledge graph replaces MEMORY.md for persistent memory.

Call `engram.remember()` with the content of each memory entry to import it.
