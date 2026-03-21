---
description: Rebuild the Engram code intelligence index from scratch
---

Call the `engram.search_code` tool with a test query to trigger incremental indexing,
or for a full rebuild, tell the user this will re-parse all source files in the project
using Tree-sitter and update the knowledge graph with current symbol definitions.

Steps:
1. Call `engram.get_architecture()` to see current index stats
2. Note: full reindex is handled internally by the MCP server when you indicate a full rebuild is needed
