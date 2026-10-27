"""The section 2 re-check of permissions-core 914113d (for Serenity): each test names its item."""
import sqlite3

from permission_ledger import Gate, Ledger, effective_gate, houses, ledger_path
from tests.permissions_support import raise_gate, raised_ledger


def _meta(home) -> dict:
    con = sqlite3.connect(ledger_path(home))
    try:
        return dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()


def _put_meta(home, meta: dict) -> None:
    """The `meta` page as it was: every key set back to `meta`'s value, and no other key."""
    con = sqlite3.connect(ledger_path(home))
    try:
        con.execute("DELETE FROM meta")
        con.executemany("INSERT INTO meta VALUES(?, ?)", meta.items())
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- must-fix 1: the gate checks the log's tail

def test_must_fix_1_a_gate_whose_meta_page_tore_old_reads_closed_never_the_older_mode(tmp_path):
    """The ledger raised to `shadow`, then to `enforce`. A copy taken mid-commit keeps the `enforce` act's log row
    but not its `meta` page: the gate reads `shadow` and the head is one row back. Under shadow an unreadable ledger
    sends the frame to the legacy path, which serves what enforce refuses, so the gate must read closed."""
    led = raised_ledger(tmp_path, mode="shadow")
    before = _meta(tmp_path)
    raise_gate(led, "enforce", now="2026-11-03")
    top = led.seq()
    led.close()
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("enforce", None)
    _put_meta(tmp_path, before)
    assert before["gate"] == "shadow" and before["head"].startswith(f"{top - 1}:")
    gate = effective_gate(tmp_path, houses(tmp_path))
    assert gate.mode == "closed" and f"meta.head names seq {top - 1}" in gate.cause
    assert "verify" in gate.cause


def test_must_fix_1_a_ledger_with_no_head_yet_reads_its_gate_as_before(tmp_path):
    """A ledger made before R48 has no head until its next write: its gate reads as it did."""
    raised_ledger(tmp_path, mode="shadow").close()
    meta = _meta(tmp_path)
    del meta["head"]
    _put_meta(tmp_path, meta)
    assert effective_gate(tmp_path, houses(tmp_path)) == Gate("shadow", None)
    led = Ledger.open_read_only(tmp_path)
    try:
        assert led.state().meta["gate"] == "shadow"
    finally:
        led.close()
