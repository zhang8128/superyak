"""Task 10: the ledger file (P 5.5, 5.6): schema, hash-chained log, projections, state(seq), rebuild, U8, U9, RF5."""
import multiprocessing
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import permission_ledger
from permission_ledger import Ledger, LedgerUnreadable, ledger_path, new_id
from permissions import RuleError, decide
from tests.permissions_support import T, home_use


def agent_row(name, acts_for="person:andy", seq="@seq"):
    return {"insert": [{"table": "agents", "row": {"id": f"agent:{name}", "acts_for": acts_for,
                                                   "created_seq": seq}}]}


def small_ledger(tmp_path):
    """create plus ten registry rows written through _append."""
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    for i in range(10):
        led._append("register-agent", f"agent:a{i}", "person:andy", "terminal", agent_row(f"a{i}"),
                    at=T("2026-11-01") + i + 1)
    return led


def flip_one_byte_in_log_body(path, seq):
    con = sqlite3.connect(path)
    con.execute("UPDATE ledger_log SET body = 'X' || substr(body, 2) WHERE seq = ?", (seq,))
    con.commit()
    con.close()


def test_init_writes_meta_owner_and_home(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    meta = led.meta()
    assert meta["schema_version"] == "1" and meta["owner"] == "person:andy" and uuid.UUID(meta["ledger_id"])
    assert meta["admins"] == "person:andy"
    st = led.state()
    assert st.persons["person:andy"].home == "place:home/andy"
    assert st.places["place:home/andy"].is_root == 1 and len(st.places["place:home/andy"].pseudonym_salt) == 16
    assert [r.person for r in st.place_stewards["place:home/andy"]] == ["person:andy"]
    assert ledger_path(tmp_path) == tmp_path / ".engram" / "permissions.db"
    assert led.seq() == 1 and st.seq_at == {1: T("2026-11-01")}


def test_create_refuses_a_second_ledger_and_a_bad_handle(tmp_path):
    with pytest.raises(RuleError):
        Ledger.create(tmp_path, "Bad Handle", now=1)
    Ledger.create(tmp_path, "andy", now=1)
    with pytest.raises(FileExistsError):
        Ledger.create(tmp_path, "andy", now=2)


def test_new_id_is_prefix_and_32_lowercase_hex():
    a, b = new_id("r-"), new_id("r-")
    assert a != b and len(a) == 34 and a.startswith("r-") and int(a[2:], 16) >= 0 and a[2:] == a[2:].lower()


def test_u8_the_log_chain_verifies_and_one_changed_byte_fails(tmp_path):
    led = small_ledger(tmp_path)
    assert led.verify() is None
    led.close()
    flip_one_byte_in_log_body(ledger_path(tmp_path), seq=4)
    assert Ledger.open(tmp_path).verify() == 4


def test_verify_finds_a_deleted_row_and_a_broken_link(tmp_path):
    led = small_ledger(tmp_path)
    led.close()
    con = sqlite3.connect(ledger_path(tmp_path))
    con.execute("DELETE FROM ledger_log WHERE seq = 3")
    con.commit()
    con.close()
    assert Ledger.open(tmp_path).verify() == 3


def test_the_first_prev_digest_is_64_zeros(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=1)
    assert led.conn.execute("SELECT prev_digest FROM ledger_log WHERE seq=1").fetchone()[0] == "0" * 64


def test_rebuild_gives_the_same_tables(tmp_path):
    led = small_ledger(tmp_path)
    copy = Ledger.open(led.rebuild(tmp_path / "copy.db"))
    assert copy.tables() == led.tables() and copy.verify() is None


def test_rebuild_refuses_an_existing_ledger(tmp_path):
    led = small_ledger(tmp_path)
    with pytest.raises(FileExistsError):
        led.rebuild(tmp_path)


def test_state_at_an_older_seq_hides_later_rows(tmp_path):
    led = small_ledger(tmp_path)
    assert led.seq() == 11
    assert len(led.state().agents) == 10
    assert sorted(led.state(4).agents) == ["agent:a0", "agent:a1", "agent:a2"]
    assert led.state(1).agents == {} and led.state(4).seq == 4
    with pytest.raises(ValueError):
        led.state(99)


def test_state_cuts_removals_and_revocations_at_the_asked_seq(tmp_path):
    led = small_ledger(tmp_path)
    led._append("retire-agent", "agent:a0", "person:andy", "terminal",
                {"update": [{"table": "agents", "where": {"id": "agent:a0"}, "set": {"retired_seq": "@seq"}}]},
                at=T("2026-11-02"))
    assert led.state().agents["agent:a0"].retired_seq == 12
    assert led.state(11).agents["agent:a0"].retired_seq is None


def test_a_place_name_is_read_from_its_register_place_row(tmp_path):
    led = small_ledger(tmp_path)
    led._append("register-place", "place:la-county/public-health", "person:andy", "terminal",
                {"name": "Public Health", "insert": [
                    {"table": "places", "row": {"id": "place:la-county/public-health", "is_root": 1,
                                                "created_seq": "@seq", "pseudonym_salt": "00" * 16}}]},
                at=T("2026-11-02"))
    assert led.state().names["place:la-county/public-health"] == "Public Health"
    assert led.state().names["place:home/andy"] == "andy"


def test_every_log_column_is_kept(tmp_path):
    led = small_ledger(tmp_path)
    seq = led._append("allow", "r-" + "1" * 32, "agent:x", "tool", agent_row("zz"), under_grant="g-" + "2" * 32,
                      proposal_id="p-" + "3" * 32, at=T("2026-11-03"))
    row = led.tables()["ledger_log"][seq - 1]
    assert (row["seq"], row["at"], row["kind"], row["actor"], row["channel"], row["under_grant"],
            row["proposal_id"]) == (12, T("2026-11-03"), "allow", "agent:x", "tool", "g-" + "2" * 32, "p-" + "3" * 32)


def test_a_bad_projection_writes_nothing(tmp_path):
    led = small_ledger(tmp_path)
    before = led.tables()
    for body in ({"insert": [{"table": "nosuch", "row": {}}]},
                 {"insert": [{"table": "agents", "row": {"id": "agent:q"}}]},
                 {"insert": [{"table": "agents", "row": {"id": "agent:a0", "acts_for": "p", "created_seq": 1}}]},
                 {"update": [{"table": "agents", "where": {"id": "agent:none"}, "set": {"retired_seq": 1}}]}):
        with pytest.raises(RuleError):
            led._append("x", "y", "person:andy", "terminal", body, at=5)
    assert led.tables() == before and led.verify() is None


def test_every_table_takes_a_row_through_append(tmp_path):
    led = small_ledger(tmp_path)
    r = "r-" + "a" * 32
    sel = {"audience": ["self"], "requesters": "*", "objects": {"kinds": ["memory"], "stores": "*", "layers": "*",
           "lanes": "*", "collections": "*", "memories": "*"}, "actions": "*", "purposes": "*"}
    body = {"insert": [
        {"table": "records", "row": {"id": r, "layer": "place:home/andy", "effect": "allow", "selector": sel,
                                      "valid_from": 1, "anchor": 1, "backing": "person", "set_by": "person:andy",
                                      "channel": "terminal", "reason": "t", "created": 1, "created_seq": "@seq"}},
        {"table": "permission_grants", "row": {"id": "g-" + "b" * 32, "issuer": "person:andy",
                                               "grantee": "agent:a1", "layer": "place:home/andy",
                                               "ops": ["recall"], "envelope": sel, "max_days": 3, "depth": 0,
                                               "expires": 9, "created": 1, "created_seq": "@seq"}},
        {"table": "proposals", "row": {"id": "p-" + "c" * 32, "by_agent": "agent:a1", "for_person": "person:andy",
                                       "kind": "allow", "body": {"k": 1}, "created": 1, "expires": 9,
                                       "status": "pending"}},
        {"table": "groups", "row": {"id": "group:g", "owner": "person:andy", "created_seq": "@seq"}},
        {"table": "copies", "row": {"object": "mem:K/episode/c", "source": "mem:S/episode/m", "added_seq": "@seq"}},
        {"table": "lane_notes", "row": {"object": "mem:S/episode/m", "lane": "personal", "at": 4, "seq": "@seq"}},
    ]}
    seq = led._append("batch", "x", "person:andy", "terminal", body, at=T("2026-11-04"))
    st = led.state()
    assert st.records[r].created_seq == seq and st.grants["g-" + "b" * 32].created_seq == seq
    assert st.copy_seqs["mem:K/episode/c"] == seq
    assert led.tables()["permission_grants"][0]["ops"] == '["recall"]'
    assert Ledger.open(led.rebuild(tmp_path / "copy")).tables() == led.tables()
    led._append("revoke", r, "person:andy", "terminal",
                {"update": [{"table": "records", "where": {"id": r},
                             "set": {"revoked": "@at", "revoked_by": "person:andy", "revoke_reason": "x",
                                     "revoked_seq": "@seq"}}]}, at=T("2026-11-05"))
    assert led.state(seq).records[r].revoked is None and led.state().records[r].revoked == T("2026-11-05")


def test_u9_read_only_open_changes_no_byte(tmp_path):
    small_ledger(tmp_path).close()
    before = ledger_path(tmp_path).read_bytes()
    ro = Ledger.open_read_only(tmp_path)
    ro.state()
    ro.state(1)
    ro.verify()
    assert ro.conn.total_changes == 0 and ledger_path(tmp_path).read_bytes() == before
    assert sorted(p.name for p in (tmp_path / ".engram").iterdir()) == ["permissions.db"]
    with pytest.raises(sqlite3.OperationalError):
        ro.conn.execute("DELETE FROM meta")
    with pytest.raises(sqlite3.OperationalError):
        ro._append("x", "y", "z", "terminal", {}, at=1)


def test_read_only_open_of_a_missing_or_unreadable_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        Ledger.open_read_only(tmp_path)
    with pytest.raises(FileNotFoundError):
        Ledger.open(tmp_path)
    (tmp_path / ".engram").mkdir()
    ledger_path(tmp_path).write_bytes(b"this is not a database" * 100)
    with pytest.raises(LedgerUnreadable):
        Ledger.open_read_only(tmp_path)
    with pytest.raises(LedgerUnreadable):
        Ledger.open(tmp_path)


def test_a_hot_journal_leaves_a_reader_unreadable_until_a_writer_opens(tmp_path):
    small_ledger(tmp_path).close()
    crash = ("import os, sqlite3, sys\n"
             "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
             "c.execute('PRAGMA cache_size=2')\n"
             "c.execute('BEGIN IMMEDIATE')\n"
             "c.execute(\"UPDATE ledger_log SET body = body || printf('%.30000c', 'x')\")\n"
             "os._exit(0)\n")
    subprocess.run([sys.executable, "-c", crash, str(ledger_path(tmp_path))], check=True)
    assert ledger_path(tmp_path).with_name("permissions.db-journal").exists()
    with pytest.raises(LedgerUnreadable) as e:
        Ledger.open_read_only(tmp_path)
    assert "writing open" in str(e.value)
    led = Ledger.open(tmp_path)          # a writing open rolls the journal back
    assert led.verify() is None
    led.close()
    Ledger.open_read_only(tmp_path).state()


def _append_fifty(args):
    home, who, n = args
    led = Ledger.open(home)
    for i in range(n):
        led._append("register-agent", f"agent:{who}{i}", "person:andy", "terminal", agent_row(f"{who}{i}"),
                    at=T("2026-12-01") + i)
    led.close()


def test_rf5_two_writers_keep_one_chain(tmp_path):
    small_ledger(tmp_path).close()
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(2) as pool:
        pool.map(_append_fifty, [(tmp_path, "x", 50), (tmp_path, "y", 50)])
    led = Ledger.open(tmp_path)
    seqs = [row["seq"] for row in led.tables()["ledger_log"]]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) == 111 and led.verify() is None
    assert len(led.state().agents) == 110
    assert Ledger.open(led.rebuild(tmp_path / "copy.db")).tables() == led.tables()


# ---------------------------------------------------------------- Task 13B: hardening (P 5.5, 5.6)

def test_rebuild_refuses_an_edited_log_and_writes_nothing(tmp_path):
    led = small_ledger(tmp_path)
    led.close()
    flip_one_byte_in_log_body(ledger_path(tmp_path), seq=4)
    led = Ledger.open(tmp_path)
    dest = tmp_path / "copy"
    with pytest.raises(RuleError, match="seq 4"):
        led.rebuild(dest)
    assert not ledger_path(dest).exists() and not dest.exists()


def test_rebuild_refuses_a_replay_whose_digest_differs(tmp_path, monkeypatch):
    led = small_ledger(tmp_path)
    led.close()
    con = sqlite3.connect(ledger_path(tmp_path))
    con.execute("UPDATE ledger_log SET digest = ? WHERE seq = 4", ("f" * 64,))
    con.commit()
    con.close()
    led = Ledger.open(tmp_path)
    monkeypatch.setattr(Ledger, "verify", lambda self: None)     # the chain check is bypassed; the replay must catch it
    dest = tmp_path / "copy"
    with pytest.raises(RuleError, match="seq 4"):
        led.rebuild(dest)
    assert not ledger_path(dest).exists()


def test_a_rebuild_that_raises_leaves_no_file_and_a_retry_works(tmp_path, monkeypatch):
    led = small_ledger(tmp_path)
    dest = tmp_path / "copy"
    real = Ledger._project

    def boom(self, body, seq, at):
        if seq == 5:
            raise RuntimeError("disk gone")
        return real(self, body, seq, at)

    monkeypatch.setattr(Ledger, "_project", boom)
    with pytest.raises(RuntimeError):
        led.rebuild(dest)
    assert not ledger_path(dest).exists()
    assert list(ledger_path(dest).parent.glob("*")) == []
    monkeypatch.setattr(Ledger, "_project", real)
    assert Ledger.open(led.rebuild(dest)).tables() == led.tables()


def pragmas(led):
    return tuple(led.conn.execute(f"PRAGMA {name}").fetchone()[0] for name in ("journal_mode", "synchronous"))


def test_a_rebuild_replays_unsynced_with_its_journal_in_memory_and_the_copy_opens_like_any_ledger(tmp_path,
                                                                                                monkeypatch):
    """fix:ledger-rebuild-writes: the .rebuilding file is thrown away on any failure, so its rows need no fsync and
    no journal file. (Measured outside the suite: a U24 rebuild wrote about 21 times the fixture's size on the Pi, and
    a 2,002-row log 4.4 times on Tardis, 1.0 after; 27408fb's message has the method.)"""
    led = small_ledger(tmp_path)
    seen = []
    real = Ledger._append

    def spy(self, *args, **kw):
        if self.path.name.endswith(".rebuilding"):
            seen.append(pragmas(self))
        return real(self, *args, **kw)

    monkeypatch.setattr(Ledger, "_append", spy)
    dest = led.rebuild(tmp_path / "copy")
    assert seen == [("memory", 0)] * led.seq()
    copy = Ledger.open(dest)
    assert pragmas(copy) == pragmas(Ledger.open(tmp_path))  # the modes were the build's connection's, not the file's
    assert copy.tables() == led.tables() and copy.verify() is None
    assert [p.name for p in ledger_path(dest).parent.iterdir()] == ["permissions.db"]


def test_a_torn_rebuilding_file_left_by_a_power_loss_is_removed_before_the_next_rebuild(tmp_path):
    """Rio Grande's case: a pulled plug runs no `finally`, and an unsynced file can be torn any way at all. The next
    rebuild deletes it, and its journal, before it starts, and never opens it."""
    led = small_ledger(tmp_path)
    final = ledger_path(tmp_path / "copy")
    final.parent.mkdir(parents=True)
    torn = final.with_name("permissions.db.rebuilding")
    torn.write_bytes(b"SQLite format 3\x00" + os.urandom(8192))
    final.with_name("permissions.db.rebuilding-journal").write_bytes(os.urandom(4096))
    copy = Ledger.open(led.rebuild(tmp_path / "copy"))
    assert copy.tables() == led.tables() and copy.verify() is None
    assert [p.name for p in final.parent.iterdir()] == ["permissions.db"]


@pytest.mark.parametrize("fresh", [True, False])
def test_a_rebuild_syncs_its_file_then_renames_it_then_syncs_the_folders(tmp_path, monkeypatch, fresh):
    """The ledger's folder after the rename, and, when the rebuild made the folders, their own entries too (the fresh
    Pi reviewer's nit), so a power loss can neither tear the copy nor drop it."""
    led = small_ledger(tmp_path)
    dest = tmp_path / "copy"
    if not fresh:
        ledger_path(dest).parent.mkdir(parents=True)
    calls, real_replace = [], os.replace
    monkeypatch.setattr(permission_ledger, "_fsync_file", lambda path: calls.append(("file", path.name)))
    monkeypatch.setattr(permission_ledger, "_fsync_directory", lambda path: calls.append(("folder", Path(path))))
    monkeypatch.setattr(os, "replace", lambda a, b: (calls.append(("rename", Path(a).name, Path(b).name)),
                                                     real_replace(a, b))[1])
    led.rebuild(dest)
    folders = [ledger_path(dest).parent] + ([dest, dest.parent] if fresh else [])
    assert calls == [("file", "permissions.db.rebuilding"), ("rename", "permissions.db.rebuilding", "permissions.db"),
                     *[("folder", folder) for folder in folders]]


def test_the_sync_helpers_fsync_the_file_and_the_folders(tmp_path, monkeypatch):
    led = small_ledger(tmp_path)
    synced, real_fsync = [], os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(os.fstat(fd).st_ino), real_fsync(fd))[1])
    dest = led.rebuild(tmp_path / "copy")
    final = ledger_path(dest)
    assert synced == [p.stat().st_ino for p in (final, final.parent, dest, tmp_path)]  # rename keeps the inode


def test_a_folder_sync_that_fails_after_the_rename_raises_and_leaves_the_good_copy(tmp_path, monkeypatch):
    led = small_ledger(tmp_path)

    def broken(path):
        raise OSError("sync failed")

    monkeypatch.setattr(permission_ledger, "_fsync_directory", broken)
    with pytest.raises(OSError, match="sync failed"):
        led.rebuild(tmp_path / "copy")
    monkeypatch.undo()
    copy = Ledger.open(tmp_path / "copy")
    assert copy.tables() == led.tables() and copy.verify() is None


def test_state_reads_log_tables_and_meta_in_one_transaction(tmp_path):
    led = small_ledger(tmp_path)
    other = Ledger._open(tmp_path, False, 50)
    wrote = []

    class Proxy:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def execute(self, sql, *a):
            if "FROM agents" in sql and not wrote:
                wrote.append(1)
                try:
                    other._append("register-agent", "agent:late", "person:andy", "terminal",
                                  {**agent_row("late"), "meta": {"admins": "person:late"}}, at=T("2026-11-02"))
                except sqlite3.OperationalError:
                    pass          # blocked by the open read transaction, which is the point
            return self.conn.execute(sql, *a)

    led.conn = Proxy(led.conn)
    st = led.state()
    assert st.seq == max(st.seq_at) == 11
    assert st.meta["admins"] == "person:andy"          # the meta of seq 11, whether or not the late write got in
