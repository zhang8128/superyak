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

if __name__ == '__main__' and sys.argv[1:2] == ['lessons-hook']:
    # The lessons hook has 150 ms at a prompt in all (first rail spec section 8): it skips __main__, whose station
    # client import alone costs about 40 ms.
    from superyak_agent.lessons_hook import main as lessons_hook  # noqa: E402
    sys.exit(lessons_hook(sys.argv[2:]))

from superyak_agent.__main__ import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
