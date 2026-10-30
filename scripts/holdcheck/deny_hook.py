"""PreToolUse deny hook shaped as hold.py's (build-lesson-tool-holds 9b26db2a): JSON on stdout with
hookSpecificOutput.permissionDecision 'deny' and a reason ending in RERUN_TOOL, on each tool's first call only, and
never on a subagent's call (agent_id set), as hold.py:47 does."""
import json
import sys
from pathlib import Path

payload = json.loads(sys.stdin.read())
tool = payload.get('tool_name') or ''
if payload.get('agent_id') is None:
    marker = Path(__file__).with_name(f'denied-{tool}')
    if not marker.exists():
        marker.write_text('1')
        reason = ('HOLDCHECK-LESSON-MARKER: a test lesson for ' + tool + '.\n\n'
                  'Call it again if you still want it.')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                 'permissionDecisionReason': reason}}))
