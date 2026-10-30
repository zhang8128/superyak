"""PreToolUse logging hook: append each payload as one JSON line, and say nothing (so it never decides anything)."""
import sys
from pathlib import Path

with Path(__file__).with_name('payloads.jsonl').open('a') as log:
    log.write(sys.stdin.read().strip() + '\n')
