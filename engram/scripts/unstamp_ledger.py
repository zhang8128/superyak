"""The way back if the projection digest is ever reverted (docs/superpowers/plans/2026-11-03-projection-digest.md, the
re-check's decided items). Code from before the digest opens only version 1 ledgers, and a stamped ledger is version 2.
This sets `schema_version` to "1", deletes `meta.projection` and `meta.projection_parts`, and removes the marker beside
the ledger (`permissions.verified`), so that code reads the ledger again; nothing checks its digest after that.

It writes the ledger, so it shows the change and asks the person's yes at the terminal, as every writing act of
`engram-permissions` does. Stop every Engram process first.

    cd engram && .venv/bin/python -I scripts/unstamp_ledger.py [ENGRAM_HOME]

Exit 0 when the ledger was unstamped, 3 when the code was not typed, 1 when there is no stamped ledger or no
terminal."""
import sqlite3
import sys
from pathlib import Path

ENGRAM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGRAM))

import permission_cli  # noqa: E402
from permission_ledger import MARKER, Ledger, LedgerUnreadable, ledger_path  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    home = Path(argv[0]) if argv else permission_cli._home()
    path = ledger_path(home)
    try:
        led = Ledger.open_read_only(home)
    except (FileNotFoundError, LedgerUnreadable) as e:
        print(f"refused: no ledger to unstamp ({e})", file=sys.stderr)
        return 1
    try:
        version = led.meta().get("schema_version")
    finally:
        led.close()
    if version != "2":
        print(f"refused: {path} is a version {version} ledger, not one stamped with the projection digest (version 2)",
              file=sys.stderr)
        return 1
    words = (f"Unstamp the permission ledger at {path}, so that code from before the projection digest reads it again. "
             "Nothing checks the ledger's digest after this. Stop every Engram process first.")
    change = "\n".join([f"change: in {path}", "  set schema_version to 1",
                        "  delete meta.projection and meta.projection_parts", f"  remove {path.with_name(MARKER)}"])
    try:
        said_yes = permission_cli.confirm(words, change)
    except permission_cli.NoTerminal as e:
        print(f"refused: {e}; the yes is typed at the terminal", file=sys.stderr)
        return 1
    if not said_yes:
        print("That was not the code. Nothing was written.", file=sys.stderr)
        return 3
    conn = sqlite3.connect(path, isolation_level=None, timeout=5)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        conn.execute("DELETE FROM meta WHERE key IN ('projection', 'projection_parts')")
        conn.execute("COMMIT")
    finally:
        conn.close()
    path.with_name(MARKER).unlink(missing_ok=True)
    print(f"Unstamped {path}: version 1, with no projection digest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
