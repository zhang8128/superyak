"""Behavioral tests for the immutable evolving-category SQLite store."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
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
from category_compile import CategoryCompiler
from category_evolution import EvolutionEngine


@pytest.fixture
def v2_store(tmp_path):
    connection = sqlite3.connect(tmp_path / "categories_v2.db")
    store = EvolvingCategoryStore(connection)
    yield store
    store.close()


def make_v2_store(database, **kwargs):
    return EvolvingCategoryStore(sqlite3.connect(database), **kwargs)


def seed_v2_schema(database):
    seeded = make_v2_store(database)
    seeded.close()


def create_supported_cat_vectors(database):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    connection = sqlite3.connect(database)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    connection.execute(
        "CREATE VIRTUAL TABLE cat_vectors "
        "USING vec0(cell_id TEXT PRIMARY KEY, embedding float[768])"
    )
    connection.commit()
    connection.close()


def database_identity(database):
    canonical = database.resolve(strict=True)
    metadata = canonical.stat()
    return canonical, (metadata.st_dev, metadata.st_ino)


def assert_vector_layout_rejected_at_hard_quota(database):
    before_bytes = database.read_bytes()
    before_mtime = database.stat().st_mtime_ns
    connection = sqlite3.connect(database)
    try:
        with pytest.raises(CategoryQuotaExceeded):
            EvolvingCategoryStore(connection, quota_bytes=1, size_provider=lambda _path: 1)
        assert not connection.in_transaction
    finally:
        connection.close()
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime


@pytest.mark.parametrize("alias_kind", ["direct", "symlink", "hardlink"])
def test_protected_database_alias_is_rejected_before_schema_initialization(
    tmp_path, alias_kind
):
    """Canonical paths and existing file identities protect legacy databases."""
    protected = tmp_path / "categories.db"
    connection = sqlite3.connect(protected)
    connection.execute("CREATE TABLE legacy_marker(value TEXT)")
    connection.commit()
    connection.close()
    candidate = protected
    if alias_kind == "symlink":
        candidate = tmp_path / "candidate-link.db"
        candidate.symlink_to(protected.name)
    elif alias_kind == "hardlink":
        candidate = tmp_path / "candidate-hardlink.db"
        os.link(protected, candidate)

    candidate_connection = sqlite3.connect(candidate)
    try:
        with pytest.raises(ValueError, match="protected database"):
            EvolvingCategoryStore(
                candidate_connection,
                protected_database_identities=(database_identity(protected),),
            )
    finally:
        candidate_connection.close()

    check = sqlite3.connect(protected)
    try:
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name GLOB 'cat_*'"
        ).fetchone()[0] == 0
        assert check.execute("SELECT COUNT(*) FROM legacy_marker").fetchone()[0] == 0
    finally:
        check.close()


def test_archive_pressure_stages(tmp_path):
    """Catches a quota boundary that classifies either 90% threshold incorrectly."""
    size = {"value": 0}
    seed_v2_schema(tmp_path / "quota.db")
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
    seed_v2_schema(tmp_path / "quota.db")
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=1_000_000,
        size_provider=lambda _path: size["value"],
    )
    store.create_cell(CellDraft("existing", 0, "existing"))

    size["value"] = 1_000_000
    with pytest.raises(CategoryQuotaExceeded):
        store.create_cell(CellDraft("new", 0, "new"))

    assert store.get_cell("existing")["content"] == "existing"
    assert store.get_cell("new") is None
    store.close()


def test_hard_quota_rejects_write_that_would_cross_with_sqlite_sidecars(tmp_path):
    database = tmp_path / "reserved-quota.db"
    store = make_v2_store(database)
    store.connection.execute("PRAGMA journal_mode = WAL")
    store.create_cell(CellDraft("existing", 0, "existing"))
    baseline = store._default_size_provider(database)
    assert baseline is not None
    store._quota_bytes = baseline + 8 * 1024

    with pytest.raises(CategoryQuotaExceeded):
        store.append_event("bounded", {"content": "x" * (16 * 1024)})

    assert store.get_cell("existing")["content"] == "existing"
    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE kind = 'bounded'"
    ).fetchone()[0] == 0
    pressure = store.pressure()
    assert pressure.used_bytes <= pressure.quota_bytes
    store.close()


def test_wal_reservation_upper_bounds_commit_visible_sidecar_growth(tmp_path):
    """A commit cannot publish into the hard-blocked state after admission."""
    database = tmp_path / "wal-reservation.db"
    store = make_v2_store(database, quota_bytes=10**9)
    store.connection.execute("PRAGMA journal_mode = WAL")
    store.connection.execute("PRAGMA wal_autocheckpoint = 0")
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.rollback()
    payload = {"blob": "x" * 700_000}
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    reservation = store._write_reservation("event", "probe", payload_json)
    used_before = store._default_size_provider(database)
    assert used_before is not None
    store._quota_bytes = used_before + reservation + 1

    store.append_event("probe", payload, event_id="event")

    pressure = store.pressure()
    assert pressure.used_bytes < pressure.quota_bytes
    assert pressure.state != "writes_blocked"
    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE id = 'event'"
    ).fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize(
    "page_size", [512, 1_024, 2_048, 8_192, 16_384, 32_768, 65_536]
)
def test_wal_reservation_scales_with_valid_database_page_size(tmp_path, page_size):
    """Commit-frame admission is safe for every supported large SQLite page size."""
    database = tmp_path / f"wal-pages-{page_size}.db"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA page_size = {page_size}")
    assert connection.execute("PRAGMA page_size").fetchone()[0] == page_size
    store = EvolvingCategoryStore(connection, quota_bytes=10**9)
    store.connection.execute("PRAGMA journal_mode = WAL")
    store.connection.execute("PRAGMA wal_autocheckpoint = 0")
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.rollback()
    payload = {"blob": "x" * 24_576}
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    reservation = store._write_reservation("event", "probe", payload_json)
    used_before = store._default_size_provider(database)
    assert used_before is not None
    store._quota_bytes = used_before + reservation + 1

    store.append_event("probe", payload, event_id="event")

    pressure = store.pressure()
    assert pressure.used_bytes < pressure.quota_bytes
    assert pressure.state != "writes_blocked"
    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE id = 'event'"
    ).fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize("page_size", [4_096, 16_384, 65_536])
def test_wal_reservation_covers_table_and_unique_index_splits(tmp_path, page_size):
    """One logical context row reserves every b-tree changed by its commit."""
    database = tmp_path / f"wal-context-{page_size}.db"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA page_size = {page_size}")
    store = EvolvingCategoryStore(connection, quota_bytes=10**9)
    store.connection.execute("PRAGMA journal_mode = WAL")
    store.connection.execute("PRAGMA wal_autocheckpoint = 0")
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.rollback()
    split_index = {4_096: 74, 16_384: 64, 65_536: 18}[page_size]
    for index in range(split_index):
        store.create_context(
            {"blob": f"{index:04d}" + "x" * 3_500},
            context_id=f"context-{index}",
        )
    features = {"blob": f"{split_index:04d}" + "x" * 3_500}
    features_json = json.dumps(features, sort_keys=True, separators=(",", ":"))
    identifier = f"context-{split_index}"
    reservation = store._write_reservation(identifier, features_json)
    used_before = store._default_size_provider(database)
    assert used_before is not None
    outstanding_wal = Path(f"{database}-wal").stat().st_size
    store._quota_bytes = used_before + outstanding_wal + reservation + 1

    store.create_context(features, context_id=identifier)

    pressure = store.pressure()
    assert pressure.used_bytes < pressure.quota_bytes
    assert pressure.state != "writes_blocked"
    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_contexts WHERE id = ?", (identifier,)
    ).fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize("page_size", [4_096, 16_384])
def test_wal_reservation_covers_variable_bytes_duplicated_in_unique_index(
    tmp_path, page_size
):
    """Payload bytes reserve both their table and UNIQUE-index representations."""
    database = tmp_path / f"wal-context-bytes-{page_size}.db"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA page_size = {page_size}")
    store = EvolvingCategoryStore(connection, quota_bytes=10**9)
    store.connection.execute("PRAGMA journal_mode = WAL")
    store.connection.execute("PRAGMA wal_autocheckpoint = 0")
    store.connection.commit()
    store.connection.execute("BEGIN IMMEDIATE")
    store.connection.rollback()
    features = {"blob": "x" * 200_000}
    features_json = json.dumps(features, sort_keys=True, separators=(",", ":"))
    reservation = store._write_reservation("context", features_json)
    used_before = store._default_size_provider(database)
    assert used_before is not None
    store._quota_bytes = used_before + reservation + 1

    store.create_context(features, context_id="context")

    pressure = store.pressure()
    assert pressure.used_bytes < pressure.quota_bytes
    assert pressure.state != "writes_blocked"
    store.close()


def test_wal_autocheckpoint_duplication_is_reserved_before_commit(tmp_path):
    """Outstanding WAL frames cannot be duplicated into main past hard quota."""
    database = tmp_path / "wal-autocheckpoint.db"
    store = make_v2_store(database, quota_bytes=10**9)
    assert store.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    store.connection.execute("PRAGMA wal_autocheckpoint = 0")
    payload_json = json.dumps({"blob": "x" * 3_500}, separators=(",", ":"))
    store.connection.executemany(
        "INSERT INTO cat_events VALUES (?, 'prefill', ?, 'now')",
        ((f"prefill-{index:04d}", payload_json) for index in range(1_100)),
    )
    store.connection.commit()
    wal = Path(f"{database}-wal")
    page_size = store.connection.execute("PRAGMA page_size").fetchone()[0]
    assert (wal.stat().st_size - 32) // (page_size + 24) > 1_000
    store.connection.execute("PRAGMA wal_autocheckpoint = 1000")
    reservation = store._write_reservation("tiny", "probe", "{}")
    used_before = store._default_size_provider(database)
    assert used_before is not None
    store._quota_bytes = used_before + reservation + 1

    with pytest.raises(CategoryQuotaExceeded):
        store.append_event("probe", {}, event_id="tiny")

    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE id = 'tiny'"
    ).fetchone()[0] == 0
    pressure = store.pressure()
    assert pressure.used_bytes < pressure.quota_bytes
    assert pressure.state != "writes_blocked"
    store.close()


def test_disposition_rewrite_identifier_is_bounded_before_projection(v2_store):
    """A bounded event cannot expand an unbounded identifier into two indexes."""
    rewrite_id = "r" * (categories_module.MAX_CATEGORY_IDENTIFIER_BYTES + 1)

    with pytest.raises(ValueError, match="rewrite identifier byte limit"):
        v2_store.append_event("rewrite_proposed", {"rewrite_id": rewrite_id})

    assert v2_store.connection.execute(
        "SELECT COUNT(*) FROM cat_events WHERE kind = 'rewrite_proposed'"
    ).fetchone()[0] == 0
    assert v2_store.connection.execute(
        "SELECT COUNT(*) FROM cat_pending_rewrites"
    ).fetchone()[0] == 0


def test_schema_upgrade_backfills_only_still_pending_historical_rewrites(tmp_path):
    """The derived pending projection is complete on the first predecessor reopen."""
    database = tmp_path / "pre-pending-projection.db"
    store = make_v2_store(database)
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_proposed")
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_terminal")
    store.connection.execute("DROP TABLE cat_pending_rewrites")
    store.connection.commit()
    with store.transaction() as connection:
        for rewrite_id in ("still-pending", "already-terminal"):
            event_id = store.append_event(
                "rewrite_proposed", {"rewrite_id": rewrite_id}
            )
            connection.execute(
                "INSERT INTO cat_rewrites VALUES (?, NULL, ?, '{}', 'now')",
                (rewrite_id, event_id),
            )
        store.append_event(
            "rewrite_rejected", {"rewrite_id": "already-terminal"}
        )
    store.close()

    upgraded = make_v2_store(database)
    try:
        assert tuple(
            str(row[0])
            for row in upgraded.connection.execute(
                "SELECT rewrite_id FROM cat_pending_rewrites ORDER BY rewrite_id"
            )
        ) == ("still-pending",)
    finally:
        upgraded.close()


def test_wal_schema_upgrade_reserves_commit_visible_growth(tmp_path):
    """Adding the pending projection cannot publish beyond the hard quota."""
    database = tmp_path / "quota-predecessor.db"
    store = make_v2_store(database)
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_proposed")
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_terminal")
    store.connection.execute("DROP TABLE cat_pending_rewrites")
    store.connection.commit()
    assert store.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    store.connection.commit()
    store.close()

    connection = sqlite3.connect(database)
    connection.execute("BEGIN IMMEDIATE")
    connection.rollback()
    baseline = sum(
        candidate.stat().st_size
        for candidate in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            Path(f"{database}-journal"),
        )
        if candidate.exists()
    )
    try:
        with pytest.raises(CategoryQuotaExceeded):
            EvolvingCategoryStore(connection, quota_bytes=baseline + 1_024)
    finally:
        connection.close()

    check = sqlite3.connect(database)
    try:
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='cat_pending_rewrites'"
        ).fetchone()[0] == 0
    finally:
        check.close()


def test_wal_schema_upgrade_reserves_projected_identifier_bytes(tmp_path):
    """Backfill admission includes large predecessor IDs copied into projection."""
    database = tmp_path / "large-id-predecessor.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA page_size = 512")
    store = EvolvingCategoryStore(connection)
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_proposed")
    store.connection.execute("DROP TRIGGER cat_events_pending_rewrite_terminal")
    store.connection.execute("DROP TABLE cat_pending_rewrites")
    rewrite_id = "r" * 500_000
    payload_json = json.dumps(
        {"rewrite_id": rewrite_id}, sort_keys=True, separators=(",", ":")
    )
    store.connection.execute(
        "INSERT INTO cat_events VALUES ('proposal', 'rewrite_proposed', ?, 'now')",
        (payload_json,),
    )
    store.connection.execute(
        "INSERT INTO cat_rewrites VALUES (?, NULL, 'proposal', '{}', 'now')",
        (rewrite_id,),
    )
    store.connection.commit()
    assert store.connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    store.close()

    connection = sqlite3.connect(database)
    connection.execute("BEGIN IMMEDIATE")
    connection.rollback()
    baseline = sum(
        candidate.stat().st_size
        for candidate in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            Path(f"{database}-journal"),
        )
        if candidate.exists()
    )
    try:
        with pytest.raises(CategoryQuotaExceeded):
            EvolvingCategoryStore(connection, quota_bytes=baseline + 500_000)
    finally:
        connection.close()

    check = sqlite3.connect(database)
    try:
        assert check.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='cat_pending_rewrites'"
        ).fetchone()[0] == 0
    finally:
        check.close()


@pytest.mark.parametrize(
    ("operation", "table"),
    [
        (lambda store: store.append_event("large", {"x": "x" * (1024 * 1024 + 1)}), "cat_events"),
        (lambda store: store.create_context({"x": "x" * (256 * 1024 + 1)}), "cat_contexts"),
        (lambda store: store.create_cell(CellDraft("large-content", 0, "x" * (1024 * 1024 + 1))), "cat_cells"),
        (lambda store: store.create_cell(CellDraft("large-payload", 0, "ok", payload={"x": "x" * (256 * 1024 + 1)})), "cat_cells"),
    ],
)
def test_variable_payloads_are_bounded_before_sql(v2_store, operation, table):
    before = v2_store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    with pytest.raises(ValueError, match="byte limit"):
        operation(v2_store)

    assert v2_store.connection.execute(
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()[0] == before


def test_derived_transaction_explicitly_skips_at_high_water_mark(tmp_path):
    """Catches derived maintenance that presents a high-water skip as a write."""
    size = {"value": 90_000}
    seed_v2_schema(tmp_path / "quota.db")
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=100_000, size_provider=lambda _path: size["value"]
    )

    with store.derived_transaction() as connection:
        assert connection is None

    assert store.connection.execute("SELECT COUNT(*) FROM cat_snapshots").fetchone()[0] == 0
    store.close()


def test_derived_transaction_reports_late_high_water_rollback_as_skipped(tmp_path):
    """A post-body pressure transition is a clean skip, never a second yield."""
    size = {"value": 0}
    seed_v2_schema(tmp_path / "late-derived.db")
    store = make_v2_store(
        tmp_path / "late-derived.db",
        quota_bytes=1_000,
        high_watermark_ratio=0.9,
        size_provider=lambda _path: size["value"],
    )
    write = None

    with store.derived_transaction() as connection:
        assert connection is not None
        write = connection
        size["value"] = 900
        connection.execute(
            "INSERT INTO cat_snapshots VALUES ('late', NULL, '[]', 'hash', 'now')"
        )

    assert write is not None and write.committed is False
    assert store.connection.execute(
        "SELECT COUNT(*) FROM cat_snapshots WHERE id = 'late'"
    ).fetchone()[0] == 0
    assert not store.connection.in_transaction
    store.close()


def test_failed_quota_check_preserves_caller_transaction(tmp_path):
    """Catches quota denial committing or rolling back caller-owned work."""
    size = {"value": 0}
    seed_v2_schema(tmp_path / "quota.db")
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=100_000, size_provider=lambda _path: size["value"]
    )
    connection = store.connection
    connection.execute("BEGIN")
    connection.execute(
        "INSERT INTO cat_events (id, kind, payload_json, created_at) VALUES ('caller', 'work', '{}', 'now')"
    )
    size["value"] = 100_000

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
    seed_v2_schema(database)
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
    seed_v2_schema(database)
    store = make_v2_store(database, quota_bytes=1_000_000)

    database.unlink()

    assert store.pressure() == ArchivePressure("writes_blocked", 1_000_000, 1_000_000)
    store.close()


@pytest.mark.parametrize("mutation", ["renamed", "replacement", "symlink"])
def test_default_size_provider_rejects_retargeted_main_database_path(tmp_path, mutation):
    """Catches path retargeting that measures a different file as this archive."""
    database = tmp_path / "quota.db"
    seed_v2_schema(database)
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
    seed_v2_schema(database)
    store = make_v2_store(database, quota_bytes=1_000_000)
    original = tmp_path / "original.db"
    database.rename(original)
    os.link(original, database)

    assert store.pressure().state == "normal"
    store.close()


def test_default_size_provider_detects_replacement_between_path_resolution_and_open(tmp_path, monkeypatch):
    """Catches a pathname race that switches databases after identity capture."""
    database = tmp_path / "quota.db"
    seed_v2_schema(database)
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


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm"])
def test_default_size_provider_rejects_fifo_without_blocking(tmp_path, suffix):
    """Catches quota measurement hanging while opening an attacker-controlled FIFO."""
    database = tmp_path / "quota.db"
    seed_v2_schema(database)
    store = make_v2_store(database, quota_bytes=1_000_000)
    candidate = Path(f"{database}{suffix}")
    if suffix:
        candidate.unlink(missing_ok=True)
    else:
        database.unlink()
    os.mkfifo(candidate)

    assert store.pressure().state == "writes_blocked"
    with pytest.raises(CategoryQuotaExceeded):
        store.append_event("blocked", {})
    store.close()


def test_default_size_provider_fallback_rejects_symlink(tmp_path, monkeypatch):
    """Catches platforms without O_NOFOLLOW following a sidecar symlink."""
    database = tmp_path / "quota.db"
    seed_v2_schema(database)
    store = make_v2_store(database, quota_bytes=1_000_000)
    target = tmp_path / "target"
    target.write_bytes(b"target")
    wal = Path(f"{database}-wal")
    wal.symlink_to(target)
    monkeypatch.delattr(categories_module.os, "O_NOFOLLOW", raising=False)

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

    seed_v2_schema(tmp_path / "quota.db")
    store = make_v2_store(
        tmp_path / "quota.db", quota_bytes=10, size_provider=FalseyProvider()
    )
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


def test_default_size_provider_rejects_fresh_schema_that_cannot_fit(tmp_path):
    """Fresh schema DDL cannot publish physical files beyond the hard quota."""
    database = tmp_path / "physical-quota.db"
    connection = sqlite3.connect(database)
    try:
        with pytest.raises(CategoryQuotaExceeded):
            EvolvingCategoryStore(connection, quota_bytes=1_024)
        assert not connection.in_transaction
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name GLOB 'cat_*'"
        ).fetchone()[0] == 0
    finally:
        connection.close()

    physical_bytes = sum(
        path.stat().st_size
        for path in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            Path(f"{database}-journal"),
        )
        if path.exists()
    )
    assert physical_bytes < 1_024


def test_current_schema_reopens_at_hard_quota_without_a_schema_write(tmp_path):
    """Catches restart migration attempting DDL after the archive is already full."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.create_cell(CellDraft("existing", 0, "existing"))
    seeded.close()
    before = database.stat().st_mtime_ns

    reopened = make_v2_store(database, quota_bytes=1, size_provider=lambda _path: 1)
    assert reopened.get_cell("existing")["content"] == "existing"
    assert reopened.pressure().state == "writes_blocked"
    with pytest.raises(CategoryQuotaExceeded):
        reopened.create_cell(CellDraft("blocked", 0, "blocked"))
    reopened.close()
    assert database.stat().st_mtime_ns == before


def test_incomplete_schema_still_requires_quota_before_migration(tmp_path):
    """Catches a partial current-looking schema bypassing the hard-quota migration gate."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    connection = sqlite3.connect(database)
    connection.execute("DROP INDEX idx_cat_epochs_rewrite_unique")
    connection.commit()
    connection.close()

    with pytest.raises(CategoryQuotaExceeded):
        make_v2_store(database, quota_bytes=1, size_provider=lambda _path: 1)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'idx_cat_epochs_rewrite_unique'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_current_core_schema_provisions_missing_vectors_only_when_normal(tmp_path):
    """Catches fast-path reopen leaving an available optional vector table absent."""
    sqlite_vec = pytest.importorskip("sqlite_vec")
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()

    connection = sqlite3.connect(database)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    reopened = EvolvingCategoryStore(
        connection, quota_bytes=100_000_000, size_provider=lambda _path: 0
    )
    assert reopened.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'cat_vectors'"
    ).fetchone()[0] == 1
    reopened.close()


@pytest.mark.parametrize("used", [90, 100])
def test_current_core_schema_skips_missing_vector_provisioning_under_pressure(tmp_path, used):
    """Catches high/hard reopen issuing optional vector DDL or changing the database."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    before = database.stat().st_mtime_ns

    reopened = make_v2_store(database, quota_bytes=100, size_provider=lambda _path: used)
    assert reopened.get_cell("absent") is None
    assert reopened.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'cat_vectors'"
    ).fetchone()[0] == 0
    reopened.close()
    assert database.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    ("admission_used", "expected_state"),
    [(90, "derived_blocked"), (100, "writes_blocked")],
)
def test_optional_vector_admission_race_is_a_read_only_skip(
    tmp_path, admission_used, expected_state
):
    """Catches normal preflight racing to high or hard pressure during admission."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.create_cell(CellDraft("existing", 0, "existing"))
    seeded.close()
    before = database.stat().st_mtime_ns
    measurements = [0, admission_used, admission_used]
    measurement_paths = []

    def sequence_provider(path):
        measurement_paths.append(path)
        return measurements[len(measurement_paths) - 1]

    reopened = make_v2_store(
        database,
        quota_bytes=100,
        size_provider=sequence_provider,
    )

    assert reopened.get_cell("existing")["content"] == "existing"
    assert reopened.pressure().state == expected_state
    assert measurement_paths == [database, database, database]
    assert not reopened.connection.in_transaction
    assert reopened.connection.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE name = 'cat_vectors' OR name LIKE 'cat_vectors_%'"
    ).fetchone()[0] == 0
    reopened.close()
    assert database.stat().st_mtime_ns == before


def test_optional_vector_schema_reserves_commit_visible_wal_growth(tmp_path):
    """Derived vec0 provisioning skips before DDL when schema growth lacks room."""
    sqlite_vec = pytest.importorskip("sqlite_vec")
    database = tmp_path / "vector-quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    connection = sqlite3.connect(database)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    connection.rollback()
    baseline = sum(
        candidate.stat().st_size
        for candidate in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
            Path(f"{database}-journal"),
        )
        if candidate.exists()
    )

    reopened = EvolvingCategoryStore(
        connection,
        quota_bytes=baseline + 1_024,
        high_watermark_ratio=0.999999,
    )
    try:
        assert reopened.connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name = 'cat_vectors' OR name LIKE 'cat_vectors_%'"
        ).fetchone()[0] == 0
        assert reopened.pressure().state == "normal"
    finally:
        reopened.close()


def test_lone_bogus_vector_shadow_requires_migration_at_hard_quota(tmp_path):
    """Catches a same-named shadow being treated as supported vector absence."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE cat_vectors_chunks (value TEXT)")
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_real_vector_shadows_without_the_main_table_require_migration_at_hard_quota(tmp_path):
    """Catches a partial real vec0 layout being accepted without its virtual table."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA writable_schema = ON")
    connection.execute("DELETE FROM sqlite_master WHERE name = 'cat_vectors'")
    connection.execute("PRAGMA writable_schema = OFF")
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_vec0_layout_missing_one_shadow_requires_migration_at_hard_quota(tmp_path):
    """Catches a damaged real vec0 layout being accepted from main-table DDL alone."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE cat_vectors_vector_chunks00")
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_vec0_shadow_with_the_wrong_object_type_requires_migration_at_hard_quota(tmp_path):
    """Catches a permitted shadow name bypassing its required SQLite object type."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE cat_vectors_info")
    connection.execute(
        "CREATE VIEW cat_vectors_info AS "
        "SELECT 'CREATE_VERSION' AS key, 'v0.1.7' AS value"
    )
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_tampered_real_vec0_shadow_definition_requires_migration_at_hard_quota(tmp_path):
    """Catches writable_schema edits to a vec0 shadow definition being ignored."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA writable_schema = ON")
    cursor = connection.execute(
        "UPDATE sqlite_master SET sql = REPLACE(sql, 'value any', 'value blob') "
        "WHERE type = 'table' AND name = 'cat_vectors_info'"
    )
    assert cursor.rowcount == 1
    connection.execute("PRAGMA writable_schema = OFF")
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_extra_known_vec0_shadow_requires_migration_at_hard_quota(tmp_path):
    """Catches a metadata-layout shadow being accepted by the non-metadata schema."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE cat_vectors_metadatachunks00(rowid PRIMARY KEY, data BLOB NOT NULL)"
    )
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_ordinary_cat_vectors_table_requires_migration_at_hard_quota(tmp_path):
    """Catches an ordinary same-named table being mistaken for the vec0 virtual table."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE cat_vectors (cell_id TEXT PRIMARY KEY, embedding BLOB)")
    connection.commit()
    connection.close()

    assert_vector_layout_rejected_at_hard_quota(database)


def test_genuine_vec0_layout_is_current_and_reopens_without_a_write(tmp_path):
    """Catches exact preflight rejecting sqlite-vec's complete supported layout."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.create_cell(CellDraft("existing", 0, "existing"))
    seeded.close()
    create_supported_cat_vectors(database)
    before = database.stat().st_mtime_ns

    reopened = make_v2_store(database, quota_bytes=1, size_provider=lambda _path: 1)

    assert reopened.get_cell("existing")["content"] == "existing"
    assert not reopened.connection.in_transaction
    reopened.close()
    assert database.stat().st_mtime_ns == before


def test_supported_vec0_reopen_without_extension_keeps_exact_traversal(
    tmp_path, monkeypatch
):
    """Optional vector unavailability cannot disable exact category reads."""
    database = tmp_path / "vector-reopen.db"
    seeded = make_v2_store(database)
    seeded.create_cell(CellDraft("seed", 0, "exact seed"))
    EvolutionEngine(seeded).create_root_epoch("root", ("seed",))
    seeded.close()
    create_supported_cat_vectors(database)

    import sqlite_vec

    attempts = []

    def unavailable(_connection):
        attempts.append(True)
        raise sqlite3.OperationalError("extension unavailable")

    monkeypatch.setattr(sqlite_vec, "load", unavailable)
    reopened = make_v2_store(database)
    compiler = CategoryCompiler(reopened)
    try:
        compiled = compiler.compile("root", None, ("seed",), 0)
        assert [cell.id for cell in compiled.cells] == ["seed"]
        assert attempts
    finally:
        compiler.close()
        reopened.close()


def test_incoherent_vec0_layout_fails_closed_at_normal_pressure_before_schema_ddl(tmp_path):
    """Catches normal migration layering IF NOT EXISTS over damaged vector state."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    create_supported_cat_vectors(database)
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE cat_vectors_vector_chunks00")
    connection.commit()
    before_bytes = database.read_bytes()
    before_mtime = database.stat().st_mtime_ns
    statements = []
    connection.set_trace_callback(statements.append)

    with pytest.raises(RuntimeError, match="incoherent optional vector schema"):
        EvolvingCategoryStore(connection, quota_bytes=100, size_provider=lambda _path: 0)

    assert not connection.in_transaction
    assert not any(statement.lstrip().upper().startswith("CREATE") for statement in statements)
    connection.close()
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime


def test_unexpected_category_object_is_not_a_current_core_schema(tmp_path):
    """Catches exact-core preflight silently accepting an extra cat_* trigger/table."""
    database = tmp_path / "quota.db"
    seeded = make_v2_store(database)
    seeded.close()
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE cat_unexpected (value TEXT)")
    connection.commit()
    connection.close()

    with pytest.raises(CategoryQuotaExceeded):
        make_v2_store(database, quota_bytes=1, size_provider=lambda _path: 1)


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
        "cat_pending_rewrites",
        "cat_rewrite_members",
        "cat_epochs",
        "cat_epoch_parents",
        "cat_epoch_members",
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
    connection.execute(
        "INSERT INTO cat_epoch_members (epoch_id, position, cell_id) "
        "VALUES ('parent', 0, 'cell')"
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
        "cat_epoch_members": ("epoch_id = 'parent' AND position = 0", ()),
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
    "cat_epoch_members",
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
