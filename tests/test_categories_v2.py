"""Behavioral tests for the immutable evolving-category SQLite store."""

from __future__ import annotations

import hashlib
import os
import sqlite3

import pytest

import categories as categories_module

from categories import (
    ArchivePressure,
    Boundary,
    CategoryQuotaExceeded,
    CellDraft,
    EvolvingCategoryStore,
    WeightVector,
)


@pytest.fixture
def v2_store(tmp_path):
    connection = sqlite3.connect(tmp_path / "categories_v2.db")
    store = EvolvingCategoryStore(connection)
    yield store
    store.close()


def make_v2_store(database, **kwargs):
    return EvolvingCategoryStore(sqlite3.connect(database), **kwargs)


def test_archive_pressure_stages(tmp_path):
    """Catches a quota boundary that classifies either 90% threshold incorrectly."""
    size = {"value": 0}
    store = make_v2_store(
        tmp_path / "quota.db",
        quota_bytes=1_000,
        high_watermark_ratio=0.90,
        size_provider=lambda _path: size["value"],
    )

    size["value"] = 899
    assert store.pressure() == ArchivePressure("normal", 899, 1_000)
    size["value"] = 900
    assert store.pressure() == ArchivePressure("derived_blocked", 900, 1_000)
    size["value"] = 1_000
    assert store.pressure() == ArchivePressure("writes_blocked", 1_000, 1_000)
    store.close()


def test_hard_quota_blocks_cell_write_without_hiding_existing_reads(tmp_path):
    """Catches a hard-limit write path that commits a cell or blocks reads."""
    size = {"value": 0}
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=100, size_provider=lambda _path: size["value"]
    )
    store.create_cell(CellDraft("existing", 0, "existing"))

    size["value"] = 100
    with pytest.raises(CategoryQuotaExceeded):
        store.create_cell(CellDraft("new", 0, "new"))

    assert store.get_cell("existing")["content"] == "existing"
    assert store.get_cell("new") is None
    store.close()


def test_derived_transaction_explicitly_skips_at_high_water_mark(tmp_path):
    """Catches derived maintenance that presents a high-water skip as a write."""
    size = {"value": 90}
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=100, size_provider=lambda _path: size["value"]
    )

    with store.derived_transaction() as connection:
        assert connection is None

    assert store.connection.execute("SELECT COUNT(*) FROM cat_snapshots").fetchone()[0] == 0
    store.close()


def test_failed_quota_check_preserves_caller_transaction(tmp_path):
    """Catches quota denial committing or rolling back caller-owned work."""
    size = {"value": 0}
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=100, size_provider=lambda _path: size["value"]
    )
    connection = store.connection
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES ('caller', 'work', '{}', 'now')"
    )
    size["value"] = 100

    with pytest.raises(CategoryQuotaExceeded):
        store.create_cell(CellDraft("blocked", 0, "blocked"))

    assert connection.in_transaction
    assert connection.execute("SELECT kind FROM cat_events WHERE id = 'caller'").fetchone()[0] == "work"
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM cat_events WHERE id = 'caller'").fetchone()[0] == 0
    store.close()


def test_default_size_provider_counts_only_current_database_and_sidecars(tmp_path):
    """Catches size accounting that misses WAL/SHM data or follows a replaced database."""
    database = tmp_path / "quota.db"
    store = make_v2_store(database, quota_bytes=1_000_000)
    wal = database.with_name(f"{database.name}-wal")
    shm = database.with_name(f"{database.name}-shm")
    wal.write_bytes(b"wal-bytes")
    shm.write_bytes(b"shm-bytes")

    expected = database.stat().st_size + wal.stat().st_size + shm.stat().st_size
    assert store.pressure().used_bytes == expected
    store.close()


def test_invalid_size_provider_fails_closed_without_disabling_pressure_reads(tmp_path):
    """Catches malformed measurements being interpreted as free archive capacity."""
    with pytest.raises(CategoryQuotaExceeded):
        make_v2_store(tmp_path / "quota.db", quota_bytes=100, size_provider=lambda _path: -1)


def test_default_size_provider_fails_closed_when_original_database_is_unlinked(tmp_path):
    """Catches an unlinked live archive being measured as zero bytes."""
    database = tmp_path / "quota.db"
    store = make_v2_store(database, quota_bytes=1_000_000)

    database.unlink()

    assert store.pressure() == ArchivePressure("writes_blocked", 1_000_000, 1_000_000)
    store.close()


@pytest.mark.parametrize("mutation", ["renamed", "replacement", "symlink"])
def test_default_size_provider_rejects_retargeted_main_database_path(tmp_path, mutation):
    """Catches path retargeting that measures a different file as this archive."""
    database = tmp_path / "quota.db"
    store = make_v2_store(database, quota_bytes=1_000_000)
    original = tmp_path / "original.db"
    database.rename(original)
    if mutation == "renamed":
        pass
    elif mutation == "replacement":
        replacement = tmp_path / "replacement.db"
        replacement.write_bytes(b"replacement")
        replacement.replace(database)
    else:
        target = tmp_path / "target.db"
        target.write_bytes(b"target")
        database.symlink_to(target)

    assert store.pressure().state == "writes_blocked"
    store.close()


def test_default_size_provider_accepts_a_hardlink_to_the_original_database(tmp_path):
    """Catches identity checks that reject the same live database under a hard link."""
    database = tmp_path / "quota.db"
    store = make_v2_store(database, quota_bytes=1_000_000)
    original = tmp_path / "original.db"
    database.rename(original)
    os.link(original, database)

    assert store.pressure().state == "normal"
    store.close()


def test_default_size_provider_detects_replacement_between_path_resolution_and_open(tmp_path, monkeypatch):
    """Catches a pathname race that switches databases after identity capture."""
    database = tmp_path / "quota.db"
    store = make_v2_store(database, quota_bytes=1_000_000)
    replacement = tmp_path / "replacement.db"
    replacement.write_bytes(b"replacement")
    real_open = categories_module.os.open
    replaced = False

    def race_open(path, flags, *args):
        nonlocal replaced
        if Path(path) == database and not replaced:
            replaced = True
            replacement.replace(database)
        return real_open(path, flags, *args)

    monkeypatch.setattr(categories_module.os, "open", race_open)
    assert store.pressure().state == "writes_blocked"
    store.close()


def test_pressure_uses_exact_decimal_watermark_math_for_large_quotas(tmp_path):
    """Catches floating-point rounding admitting a huge archive above 90%."""
    quota = 10**40 + 7
    threshold = (quota * 9 + 9) // 10
    size = {"value": threshold - 1}
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=quota, size_provider=lambda _path: size["value"]
    )

    assert store.pressure().state == "normal"
    size["value"] = threshold
    assert store.pressure().state == "derived_blocked"
    store.close()


def test_falsey_size_provider_is_used_instead_of_replaced_by_default(tmp_path):
    """Catches a valid falsey provider being silently discarded."""
    class FalseyProvider:
        def __bool__(self):
            return False

        def __call__(self, _path):
            return 9

    store = make_v2_store(tmp_path / "quota.db", quota_bytes=10, size_provider=FalseyProvider())
    assert store.pressure().state == "derived_blocked"
    store.close()


def test_hard_quota_rejects_fresh_store_before_creating_schema(tmp_path):
    """Catches constructor schema DDL bypassing a hard archive quota."""
    database = tmp_path / "quota.db"
    with pytest.raises(CategoryQuotaExceeded):
        make_v2_store(database, quota_bytes=1, size_provider=lambda _path: 1)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name GLOB 'cat_*'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_store_owned_commit_failure_rolls_back_pending_rows(tmp_path):
    """Catches a deferred-FK COMMIT error leaving an owned transaction open."""
    store = make_v2_store(tmp_path / "quota.db")
    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute("PRAGMA defer_foreign_keys = ON")
            connection.execute(
                "INSERT INTO cat_cells (id, dimension, content, payload_json, content_hash, created_at, context_id) "
                "VALUES ('bad', 0, 'bad', '{}', 'hash', 'now', 'missing')"
            )

    assert not store.connection.in_transaction
    assert store.get_cell("bad") is None
    store.close()


def test_schema_uses_prefixed_tables_and_enforces_foreign_keys(v2_store):
    names = {
        row[0]
        for row in v2_store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {
        "cat_schema_version",
        "cat_events",
        "cat_contexts",
        "cat_cells",
        "cat_boundaries",
        "cat_weight_observations",
        "cat_rewrites",
        "cat_rewrite_members",
        "cat_epochs",
        "cat_epoch_parents",
        "cat_snapshots",
    } <= names
    assert v2_store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        v2_store.create_cell(CellDraft("orphan", 0, "orphan", context_id="missing"))


def test_constructor_rejects_active_transaction_without_mutating_caller(tmp_path):
    connection = sqlite3.connect(tmp_path / "caller.db")
    connection.execute("CREATE TABLE caller_sentinel (value TEXT)")
    connection.execute("BEGIN")
    connection.execute("INSERT INTO caller_sentinel VALUES ('pending')")

    with pytest.raises(ValueError, match="active transaction"):
        EvolvingCategoryStore(connection)

    assert connection.in_transaction
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    assert connection.execute("SELECT value FROM caller_sentinel").fetchone()[0] == "pending"
    connection.rollback()
    assert connection.execute("SELECT COUNT(*) FROM caller_sentinel").fetchone()[0] == 0
    connection.close()


def test_dimension_one_requires_zero_cell_boundaries(v2_store):
    v2_store.create_cell(CellDraft("a", 0, "a"))
    v2_store.create_cell(CellDraft("b", 0, "b"))
    arrow = CellDraft(
        "f",
        1,
        "a to b",
        (Boundary("source", 0, "a"), Boundary("target", 0, "b")),
    )

    assert v2_store.create_cell(arrow) == "f"
    with pytest.raises(ValueError, match="dimension-1 cell requires"):
        v2_store.create_cell(CellDraft("broken", 1, "broken"))


def test_boundaries_are_returned_in_side_and_position_order(v2_store):
    for cell_id in ("a", "b", "c", "d"):
        v2_store.create_cell(CellDraft(cell_id, 0, cell_id))
    v2_store.create_cell(
        CellDraft(
            "higher",
            4,
            "opaque",
            (
                Boundary("target", 1, "d"),
                Boundary("source", 1, "b"),
                Boundary("source", 0, "a"),
                Boundary("target", 0, "c"),
            ),
        )
    )

    assert v2_store.get_boundaries("higher") == [
        Boundary("source", 0, "a"),
        Boundary("source", 1, "b"),
        Boundary("target", 0, "c"),
        Boundary("target", 1, "d"),
    ]
    assert v2_store.get_boundaries("higher", side="target") == [
        Boundary("target", 0, "c"),
        Boundary("target", 1, "d"),
    ]


def test_higher_cell_is_opaque(v2_store):
    v2_store.create_cell(CellDraft("higher", 5, "opaque", payload={"k": "v"}))

    assert v2_store.get_cell("higher")["payload"] == {"k": "v"}
    assert v2_store.is_interpretable("higher") is False


def test_cell_content_hash_is_canonical_sha256(v2_store):
    content = "A stable cell\n"
    v2_store.create_cell(CellDraft("fixed", 0, content, payload={"z": 2, "a": [1]}))

    cell = v2_store.get_cell("fixed")
    assert cell["content_hash"] == hashlib.sha256(content.encode()).hexdigest()
    assert v2_store.connection.execute(
        "SELECT payload_json FROM cat_cells WHERE id = 'fixed'"
    ).fetchone()[0] == '{"a":[1],"z":2}'


def test_cell_is_sql_immutable(v2_store):
    v2_store.create_cell(CellDraft("fixed", 0, "original"))

    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            "UPDATE cat_cells SET content='changed' WHERE id='fixed'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute("DELETE FROM cat_cells WHERE id='fixed'")

    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute("UPDATE cat_schema_version SET version = 2")


@pytest.fixture
def immutable_rows(v2_store):
    event_id = v2_store.append_event("created", {})
    context_id = v2_store.create_context({"mode": "test"})
    v2_store.create_cell(CellDraft("cell", 0, "cell", context_id=context_id))
    observation_id = v2_store.observe_weight(
        "cell", context_id, WeightVector(0, 0, 0, 0, 0, 0, 0), evidence_event_id=event_id
    )
    connection = v2_store.connection
    connection.execute(
        "INSERT INTO cat_boundaries (cell_id, side, position, boundary_id) "
        "VALUES ('cell', 'source', 0, 'cell')"
    )
    connection.execute("INSERT INTO cat_rewrites (id, created_at) VALUES ('rewrite', 'now')")
    connection.execute(
        """
        INSERT INTO cat_rewrite_members (rewrite_id, role, position, external_id)
        VALUES ('rewrite', 'input', 0, 'external')
        """
    )
    connection.execute("INSERT INTO cat_epochs (id, created_at) VALUES ('parent', 'now')")
    connection.execute("INSERT INTO cat_epochs (id, created_at) VALUES ('child', 'now')")
    connection.execute(
        "INSERT INTO cat_epoch_parents (epoch_id, position, parent_id) "
        "VALUES ('child', 0, 'parent')"
    )
    return {
        "cat_schema_version": ("version = 1", ()),
        "cat_events": ("id = ?", (event_id,)),
        "cat_contexts": ("id = ?", (context_id,)),
        "cat_cells": ("id = 'cell'", ()),
        "cat_boundaries": ("cell_id = 'cell' AND side = 'source' AND position = 0", ()),
        "cat_weight_observations": ("id = ?", (observation_id,)),
        "cat_rewrites": ("id = 'rewrite'", ()),
        "cat_rewrite_members": ("rewrite_id = 'rewrite' AND role = 'input' AND position = 0", ()),
        "cat_epochs": ("id = 'child'", ()),
        "cat_epoch_parents": ("epoch_id = 'child' AND position = 0", ()),
    }


@pytest.mark.parametrize("table", [
    "cat_schema_version",
    "cat_events",
    "cat_contexts",
    "cat_cells",
    "cat_boundaries",
    "cat_weight_observations",
    "cat_rewrites",
    "cat_rewrite_members",
    "cat_epochs",
    "cat_epoch_parents",
])
def test_every_immutable_table_rejects_update_and_delete(v2_store, immutable_rows, table):
    where, parameters = immutable_rows[table]

    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            f"UPDATE {table} SET rowid = rowid WHERE {where}", parameters
        )
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(f"DELETE FROM {table} WHERE {where}", parameters)


def test_snapshots_are_replaceable(v2_store):
    v2_store.connection.execute(
        """
        INSERT INTO cat_snapshots (id, active_cell_ids_json, content_hash, created_at)
        VALUES ('snapshot', '[]', 'original', 'now')
        """
    )

    v2_store.connection.execute(
        "UPDATE cat_snapshots SET content_hash = 'replacement' WHERE id = 'snapshot'"
    )
    assert v2_store.connection.execute(
        "SELECT content_hash FROM cat_snapshots WHERE id = 'snapshot'"
    ).fetchone()[0] == "replacement"
    v2_store.connection.execute("DELETE FROM cat_snapshots WHERE id = 'snapshot'")
    assert v2_store.connection.execute(
        "SELECT COUNT(*) FROM cat_snapshots WHERE id = 'snapshot'"
    ).fetchone()[0] == 0

def test_contexts_deduplicate_canonical_feature_maps(v2_store):
    first = v2_store.create_context({"z": [2, 1], "a": {"b": True}})
    second = v2_store.create_context({"a": {"b": True}, "z": [2, 1]})

    assert first == second
    assert v2_store.connection.execute(
        "SELECT features_json FROM cat_contexts WHERE id = ?", (first,)
    ).fetchone()[0] == '{"a":{"b":true},"z":[2,1]}'


def test_weight_observations_are_ranged_append_only_and_latest(v2_store):
    v2_store.create_cell(CellDraft("cell", 0, "cell"))
    context_id = v2_store.create_context({"mode": "test"})
    old = WeightVector(0.1, 0.2, 0.3, -0.4, 0.5, 0.6, 0.7)
    current = WeightVector(0.8, 0.9, 1.0, 0.4, 0.3, 0.2, 0.1)
    old_id = v2_store.observe_weight("cell", context_id, old)
    assert v2_store.observe_weight("cell", context_id, current) != old_id

    assert v2_store.latest_weight("cell", context_id) == current
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            "UPDATE cat_weight_observations SET relevance = 0.0 WHERE id = ?",
            (old_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.observe_weight(
            "cell", context_id, WeightVector(1.1, 0, 0, 0, 0, 0, 0)
        )


def test_append_event_canonicalizes_payload_and_transaction_does_not_commit_caller(v2_store):
    event_id = v2_store.append_event("created", {"z": 1, "a": [True, None]})

    assert v2_store.connection.execute(
        "SELECT payload_json FROM cat_events WHERE id = ?", (event_id,)
    ).fetchone()[0] == '{"a":[true,null],"z":1}'

    v2_store.connection.execute("BEGIN")
    v2_store.create_cell(CellDraft("rolled-back", 0, "temporary"))
    assert v2_store.connection.in_transaction
    v2_store.connection.rollback()
    assert v2_store.get_cell("rolled-back") is None


def test_failed_nested_write_rolls_back_only_its_savepoint(v2_store):
    connection = v2_store.connection
    connection.execute("BEGIN")
    v2_store.append_event("caller-work", {}, event_id="caller-event")

    with pytest.raises(sqlite3.IntegrityError):
        v2_store.create_cell(CellDraft("invalid", 0, "invalid", context_id="missing"))

    assert connection.in_transaction
    assert connection.execute(
        "SELECT kind FROM cat_events WHERE id = 'caller-event'"
    ).fetchone()[0] == "caller-work"
    assert v2_store.get_cell("invalid") is None
    connection.rollback()
    assert connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE id = 'caller-event'"
    ).fetchone()[0] == 0


def test_rewrite_members_and_epochs_have_schema_constraints(v2_store):
    v2_store.connection.execute(
        "INSERT INTO cat_rewrites (id, created_at) VALUES ('rewrite', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            """
            INSERT INTO cat_rewrite_members
                (rewrite_id, role, position, cell_id, external_id)
            VALUES ('rewrite', 'invalid', 0, 'both', 'external')
            """
        )
    v2_store.connection.execute(
        "INSERT INTO cat_epochs (id, created_at) VALUES ('epoch', 'now')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        v2_store.connection.execute(
            "INSERT INTO cat_epoch_parents (epoch_id, position, parent_id) "
            "VALUES ('epoch', -1, 'parent')"
        )


def test_one_committed_epoch_per_rewrite_is_database_enforced(v2_store):
    """Catches application races creating two epochs for one immutable rewrite."""
    connection = v2_store.connection
    connection.execute("INSERT INTO cat_rewrites (id, created_at) VALUES ('once', 'now')")
    connection.execute(
        "INSERT INTO cat_epochs (id, rewrite_id, created_at) VALUES ('first', 'once', 'now')"
    )

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        connection.execute(
            "INSERT INTO cat_epochs (id, rewrite_id, created_at) "
            "VALUES ('second', 'once', 'now')"
        )


def _arrow(store, cell_id, source, target):
    store.create_cell(
        CellDraft(
            cell_id,
            1,
            cell_id,
            (Boundary("source", 0, source), Boundary("target", 0, target)),
        )
    )


def test_dimension_two_interpretation_requires_nonempty_composable_equal_endpoint_paths(v2_store):
    """Catches dimension-2 interpretation accepting gaps, empties, or unequal endpoints."""
    for cell_id in ("a", "b", "c"):
        v2_store.create_cell(CellDraft(cell_id, 0, cell_id))
    _arrow(v2_store, "ab", "a", "b")
    _arrow(v2_store, "bc", "b", "c")
    _arrow(v2_store, "ac", "a", "c")
    _arrow(v2_store, "ca", "c", "a")

    assert v2_store.validate_path(("ab", "bc")) == ("a", "c")
    with pytest.raises(ValueError, match="nonempty"):
        v2_store.validate_path(())
    with pytest.raises(ValueError, match="composable"):
        v2_store.validate_path(("ab", "ca"))

    v2_store.create_cell(
        CellDraft(
            "valid-two",
            2,
            "two paths a to c",
            (
                Boundary("source", 0, "ab"),
                Boundary("source", 1, "bc"),
                Boundary("target", 0, "ac"),
            ),
        )
    )
    v2_store.create_cell(
        CellDraft(
            "invalid-two",
            2,
            "different endpoints",
            (Boundary("source", 0, "ab"), Boundary("target", 0, "ca")),
        )
    )
    v2_store.create_cell(CellDraft("empty-two", 2, "no paths"))
    v2_store.create_cell(CellDraft("opaque-three", 3, "opaque"))

    assert v2_store.is_interpretable("valid-two") is True
    assert v2_store.is_interpretable("invalid-two") is False
    assert v2_store.is_interpretable("empty-two") is False
    assert v2_store.is_interpretable("opaque-three") is False
