# Superyak team mode

A lead (Claude Code or Codex) runs a team of Codex (`gpt-6.1-sol`) and Claude Code workers:
**builders** implement in their own git worktree, **collaborators** research, debate and write
documents read-only. Teams coordinate in a Slack thread per task, publish plans as canvases, and
use local plus shared engram memory. See [docs/team-mode.md](../docs/team-mode.md).

```sh
superyak-runtime team status          # CLI (any op: start, list, spawn, message, collect, end, ...)
superyak-runtime team                 # MCP server over stdio (Claude Code and Codex use this)
make check-team                       # tests (mock agents, no network)
```
