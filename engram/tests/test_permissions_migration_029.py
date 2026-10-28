"""Migration 029: share identity columns, the placement change counter, and marking new houses (P 12.2, 12.3)."""
from pathlib import Path

from permission_ledger import effective_gate, ledger_path
from tests.permissions_support import (
    counter_row, delete_one_share, house_before_029, house_dir, house_meta, insert_share, make_ledger_unreadable,
    raise_gate, raised_ledger, share_columns, update_one_share,
)
from storage import Storage

MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def test_029_adds_columns_and_a_counter_that_counts_insert_update_and_delete(tmp_path):
    store = Storage(str(house_dir(tmp_path, "lighthouse") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(shared_memories)")}
    assert {"source_instance_id", "record_id"} <= cols and store.placement_changes() == 0
    insert_share(store, memory_id="a", content="x"); update_one_share(store); delete_one_share(store)
    insert_share(store, memory_id="b", content="y")
    assert store.placement_changes() == 4          # a count and highest rowid would miss the delete-then-insert


def test_u16_a_house_created_after_the_raise_gets_the_ledger_id(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    late = Storage(str(house_dir(tmp_path, "late") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    assert late.conn.execute("SELECT value FROM meta WHERE key='permissions_ledger_id'").fetchone()[0] \
        == led.meta()["ledger_id"]


def test_u16_a_house_created_while_the_ledger_cant_be_read_gets_unreadable_and_reads_closed(tmp_path):
    raised_ledger(tmp_path, houses=("lighthouse",)); make_ledger_unreadable(tmp_path)
    late_path = house_dir(tmp_path, "late") / "graph.db"
    Storage(str(late_path), migrations_dir=MIGRATIONS_DIR).close()
    assert house_meta(late_path)["permissions_ledger_id"] == "unreadable"
    assert effective_gate(tmp_path, [late_path]).mode == "closed"


def test_029_with_no_ledger_writes_no_mark(tmp_path):
    path = house_dir(tmp_path, "lighthouse") / "graph.db"
    Storage(str(path), migrations_dir=MIGRATIONS_DIR).close()
    assert "permissions_ledger_id" not in house_meta(path) and not ledger_path(tmp_path).exists()


def test_029_on_a_house_made_by_001_to_028_adds_its_columns_and_counter(tmp_path):
    path = house_before_029(tmp_path, "old")
    assert not {"source_instance_id", "record_id"} & share_columns(path)
    Storage(str(path), migrations_dir=MIGRATIONS_DIR).close()
    assert {"source_instance_id", "record_id"} <= share_columns(path) and counter_row(path) == 0


def test_rs4_a_pre_029_house_restored_after_the_raise_stays_closed_when_a_server_opens_it(tmp_path):
    led = raised_ledger(tmp_path, houses=("lighthouse",))
    restored = house_before_029(tmp_path, "restored")
    Storage(str(restored), migrations_dir=MIGRATIONS_DIR).close()
    assert {"source_instance_id", "record_id"} <= share_columns(restored)
    assert "permissions_ledger_id" not in house_meta(restored)
    assert effective_gate(tmp_path, [restored]).mode == "closed"
    raise_gate(led, "shadow")
    assert effective_gate(tmp_path, [restored]).mode == "shadow"
