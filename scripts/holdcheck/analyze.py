"""The check's report: each payload's tool and agent_id, the transcript's record for each denied call in both forms
(with Claude Code's own decision fields), and the model's final answer, which says whether the reason reached it."""
import json
from pathlib import Path

HERE = Path(__file__).parent
payloads = [json.loads(line) for line in (HERE / 'payloads.jsonl').read_text().splitlines() if line.strip()]
print('== payloads (one per PreToolUse call the matcher sent)')
for p in payloads:
    print(f"  tool={p.get('tool_name')} agent_id={'set' if p.get('agent_id') else 'absent'} agent_type={p.get('agent_type')}")
print('== server calls (the calls that went through)')
calls = HERE / 'server-calls.jsonl'
print('  ' + ('\n  '.join(calls.read_text().splitlines()) if calls.exists() else 'none'))
for path in sorted({p.get('transcript_path') for p in payloads if p.get('transcript_path')}):
    print('== deny records in', path)
    for line in Path(path).read_text().splitlines():
        if 'HOLDCHECK-LESSON-MARKER' not in line:
            continue
        record = json.loads(line)
        if record.get('type') != 'user':
            continue
        print('  version', record.get('version'), 'entrypoint', record.get('entrypoint'), 'isSidechain', record.get('isSidechain'))
        print('  permissionDecision', json.dumps(record.get('permissionDecision')), 'toolDenialKind', record.get('toolDenialKind'))
        print('  toolUseResult', type(record.get('toolUseResult')).__name__, json.dumps(record.get('toolUseResult')))
        for block in (record.get('message') or {}).get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                print('  tool_result is_error', block.get('is_error'), type(block.get('content')).__name__,
                      json.dumps(block.get('content')))
print('== the model\'s final answer')
for line in (HERE / 'stream.jsonl').read_text().splitlines():
    event = json.loads(line)
    if event.get('type') == 'result':
        print(event.get('result', ''))
