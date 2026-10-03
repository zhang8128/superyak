#!/usr/bin/env python3
"""Single launcher for team mode, used by `superyak-runtime team`, the team daemon, and every
worker's MCP server. It needs no installation or PYTHONPATH: it puts this directory on sys.path
and runs superyak_team.mcp.main (MCP over stdio, `teamd ...`, or a CLI op)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from superyak_team.mcp import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
