#!/usr/bin/env python3
"""Single launcher for superyak-agent: `make dock`, the station MCP server, the Claude Code hook
and the watcher service all run this file with an absolute interpreter. It needs no install:
it puts this directory and the sibling team/ (team mode's fencing, redaction, sandbox and
hardened git helpers) on sys.path."""
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit('superyak-agent needs Python 3.11 or newer')

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'team')]

from superyak_agent.__main__ import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
