#!/usr/bin/env python3
"""Ship home and crossing plan, Task 13, in "Checks before review": one crossing end to end, every hop real.

It runs peer/tests/test_crossing_e2e.py in the peer's venv, so the two throwaway peers pair through the test suite's own
`paired` helper and no script computes a pairing code: a ship may run this. Engram's two halves run as subprocesses in
Engram's own venv (`uv run --locked --project engram python -I engram/scripts/crossing_check_engram.py ...`), and talk
to the peers only over the daemon socket and crossing.sock, as in production.

    cd peer && uv run --locked python scripts/crossing_check.py"""
from pathlib import Path
import subprocess
import sys

PEER = Path(__file__).resolve().parent.parent


def main() -> int:
    return subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_crossing_e2e.py'],
                          cwd=PEER).returncode


if __name__ == '__main__':
    raise SystemExit(main())
