# The lesson-holds per-tool check

For the spec `docs/superpowers/specs/2026-10-30-lesson-holds-on-tool-calls-design.md` ("Before it is built"): on each
ship's Claude Code version, whether a PreToolUse deny's reason reaches the model for the station's post and claim (and
AskUserQuestion, where the tool exists), the deny record's whole shape in the transcript, and whether `agent_id` is set
on a subagent's call. Tardis ran it on 2.1.312 (2026-10-30).

    sh scripts/holdcheck/run.sh

- `stub_station.py`: a `station` MCP server with `station_post` and `station_claim` that post and claim nothing. It logs
  each call that reaches it, so a held call shows as never arriving.
- `log_hook.py`: logs every PreToolUse payload the matcher sends.
- `deny_hook.py`: denies each tool's first call with hold.py's own JSON (`permissionDecision: deny`, a reason ending
  "Call it again if you still want it."), and never a subagent's (`agent_id` set), as hold.py does. The reason is a
  marker, not a lesson: the record's shape depends on how the deny is made, not on its text.
- `prompt.txt`: the session's instructions. `analyze.py`: the report.

`claude -p` has no AskUserQuestion, so that tool, and the interactive entrypoint (the record says `sdk-cli` here), need
one run in an interactive session.
