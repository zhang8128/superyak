#!/bin/sh
# The lesson-holds per-tool check (spec docs/superpowers/specs/2026-10-30-lesson-holds-on-tool-calls-design.md,
# "Before it is built"): an isolated `claude -p` with only a logging hook and a deny hook shaped as hold.py's, against
# a stub `station` server that posts and claims nothing. None of this machine's own hooks, settings or MCP servers load
# (--setting-sources project from a new folder, --strict-mcp-config). Run it from anywhere: sh scripts/holdcheck/run.sh
# It writes only in this folder (logs, gitignored) and in one new temporary folder, the session's own.
set -eu
D=$(cd "$(dirname "$0")" && pwd)
W=$(mktemp -d)
mkdir -p "$W/.claude"
cat > "$W/.claude/settings.json" <<EOF
{"hooks": {"PreToolUse": [{"matcher": "AskUserQuestion|mcp__station__station_post|mcp__station__station_claim",
  "hooks": [{"type": "command", "command": "python3 -I '$D/log_hook.py'", "timeout": 10},
            {"type": "command", "command": "python3 -I '$D/deny_hook.py'", "timeout": 10}]}]}}
EOF
printf '{"mcpServers": {"station": {"command": "python3", "args": ["-I", "%s/stub_station.py"]}}}\n' "$D" > "$W/mcp.json"
rm -f "$D/payloads.jsonl" "$D/server-calls.jsonl" "$D"/denied-*
cd "$W"
claude --version
claude -p "$(cat "$D/prompt.txt")" --setting-sources project --strict-mcp-config --mcp-config "$W/mcp.json" \
  --allowedTools "mcp__station__station_post,mcp__station__station_claim,AskUserQuestion,Task,Agent" \
  --output-format stream-json --verbose --include-hook-events --max-turns 25 > "$D/stream.jsonl"
python3 -I "$D/analyze.py"
