"""The permission ledger's projection digest (docs/superpowers/plans/2026-11-03-projection-digest.md): each test names
its task and the decision it pins."""
import os

from permission_ledger import Ledger, ledger_path


# ---------------------------------------------------------------- Task 0b: what this Python gives the key read

def test_0b_the_key_read_has_pread_and_cloexec_and_needs_no_sqlite_dbpage(tmp_path):
    """D4: the change counter and the journal bytes are read with `os.pread` on a descriptor opened `O_RDONLY |
    O_CLOEXEC`, never with `open()`. This runs wherever the suite runs (Tardis, the Pi, the Mac), so each machine's
    Engram Python says it has both. `sqlite_dbpage` is not relied on: it is missing from the Engram venv's SQLite on
    Tardis (3.53.1), though the system Python's 3.46.1 has it."""
    assert hasattr(os, "pread") and hasattr(os, "O_CLOEXEC")
    Ledger._blank(tmp_path, "ledger-0b").close()
    fd = os.open(ledger_path(tmp_path), os.O_RDONLY | os.O_CLOEXEC)
    try:
        header = os.pread(fd, 100, 0)
        assert header[:16] == b"SQLite format 3\x00"
        assert header[18:20] == b"\x01\x01"                # a rollback journal: the file format bytes D4 pins
        assert os.get_inheritable(fd) is False
    finally:
        os.close(fd)
