# A visitor's first hour, review 3: the re-check of draft 3 (e05c3616), verbatim

The same fresh reviewer read the diff from d70becc6 to e05c3616, the spec's "can't show" lines, and the repository's
tracked files, looking for any `.claude/` or `.mcp.json`. It ran nothing of the walk.

---

**Re-check of draft 3 (e05c3616): APPROVED WITH REQUIRED CHANGES**

Draft 3 makes all six of review 2's changes, X1 to X6. Of the authors' choices, (a) a Sonnet walker, (c) counting the
150 calls from the transcript and capping wall time with `timeout 3600`, and (d) no `--setting-sources` flag are sound.
On (d): the repo has no `.claude/` directory or `.mcp.json`, so only CLAUDE.md loads, which is exactly what a visitor
meets, and the decline rule covers it. Choice (b), `bypassPermissions`, holds only with change 1 below, and choice (e),
the reused config directory, only with change 2.

**Required**

1. **The outside-write rule would end every walk (b).** Claude Code writes its own session state into
   `CLAUDE_CONFIG_DIR`, and tools like make, uv and Python write temp files to `/tmp`. Both are writes outside the walk
   directory. Nothing stops a walk at the moment of a write either, since scoring happens afterwards. Fix: judge the
   rule on the walker's own explicit writes, meaning Write or Edit paths and Bash commands that name a path outside the
   walk directory. Exempt the harness's config directory and the temp and cache files that tools make for themselves,
   as reads already are. Score no step after the first outside write.

2. **Reusing the config directory can carry state from one walk to the next (e).** Claude Code keeps sessions, project
   history (`.claude.json`) and other state in that directory, so walk N+1 could load what walk N left behind. Fix:
   before each walk, delete everything in the directory except the files Andy's sign-in created, named once at
   sign-in. Put the directory's file list in the report.

3. **"What this can't show" contradicts (a).** Line 153 still says the walker is "the same model as the ships that
   wrote these docs". Fix: say it's Sonnet, a different model from the ships' Opus but the same family, so the docs may
   still read more easily to it than to a person.

**Advisory**

- `--allowedTools` pre-approves tools; it doesn't restrict them, and under `bypassPermissions` it changes nothing. Say
  so, or use `--disallowedTools` if a limit is meant.
- `timeout` stops `claude`, not processes the walker started in the background, such as a `make home-demo` server. Run
  each walk in its own process group or a `systemd-run --user --scope`, and kill that group when the walk ends.
- When the agent walks end, revoke the walker's sign-in as well as deleting its file.

**Read:** the diff from d70becc6 to e05c3616, the spec's "can't show" lines, and the repo's tracked files, for any
`.claude/` or `.mcp.json`.
