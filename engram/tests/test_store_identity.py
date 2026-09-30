"""Store identity (migration 028): creation, retroactive, fork, provenance."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

import calibrate
import store_identity
import store_reader
from cli import fork_instance
from federation import InstanceRegistry, sync_genome
from storage import Storage

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meta(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return store_identity.read(conn)
    finally:
        conn.close()


def pre_identity_migrations(tmp_path: Path) -> Path:
    """Every migration before 028: a store as schema 27 left it."""
    mig = tmp_path / "mig027"
    mig.mkdir(exist_ok=True)
    for path in MIGRATIONS.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 27:
            shutil.copyfile(path, mig / path.name)
    return mig


def build_schema27_store(path: Path, tmp_path: Path,
                         episodes: list[tuple[str, str]] = ()) -> None:
    store = Storage(str(path), migrations_dir=str(pre_identity_migrations(tmp_path)))
    try:
        for eid, created_at in episodes:
            store.conn.execute(
                "INSERT INTO episodes (id, session_id, content, created_at)"
                " VALUES (?, 's', ?, ?)", (eid, f"episode {eid}", created_at))
        store.conn.commit()
    finally:
        store.close()


OLD_EPISODES = [("later", "2026-03-02T00:00:00"), ("zeta", "2026-03-01T00:00:00"),
                ("alpha", "2026-03-01T00:00:00")]


def test_new_store_mints_random_identity_at_creation(tmp_path):
    a = Storage(str(tmp_path / "a.db"))
    b = Storage(str(tmp_path / "b.db"))
    try:
        ia, ib = a.instance_identity(), b.instance_identity()
    finally:
        a.close()
        b.close()

    assert ia["instance_id_origin"] == "creation"
    assert ia["instance_id_basis"] == "random"
    assert str(uuid.UUID(ia["instance_id"])) == ia["instance_id"]
    assert ia["instance_id"] != ib["instance_id"]
    assert "forked_from_instance_id" not in ia


def test_identity_survives_reopen(tmp_path):
    db = tmp_path / "graph.db"
    Storage(str(db)).close()
    first = meta(db)
    store = Storage(str(db))
    store.add_episode("e1", "s", "something happened")
    store.close()
    assert meta(db) == first


def test_old_store_gets_deterministic_retroactive_identity(tmp_path):
    original = tmp_path / "original.db"
    build_schema27_store(original, tmp_path, OLD_EPISODES)
    copy = tmp_path / "copy.db"
    shutil.copyfile(original, copy)

    Storage(str(original)).close()
    Storage(str(copy)).close()

    got, other = meta(original), meta(copy)
    # Earliest by (created_at, id): alpha and zeta tie on time, alpha wins.
    expected = store_identity.derive_retroactive_id("alpha", "2026-03-01T00:00:00")
    assert got["instance_id"] == expected == other["instance_id"]
    assert got["instance_id_origin"] == "retroactive"
    assert got["instance_id_basis"] == "earliest_episode"
    assert json.loads(got["instance_id_basis_episode"]) == {
        "id": "alpha", "created_at": "2026-03-01T00:00:00"}


def test_retroactive_id_is_a_stable_contract():
    # Changing the namespace or input encoding would re-identify every old store.
    assert store_identity.derive_retroactive_id("alpha", "2026-03-01T00:00:00") == str(
        uuid.uuid5(uuid.uuid5(uuid.NAMESPACE_URL, "engram:store-identity:retroactive:v1"),
                   "alpha\x1f2026-03-01T00:00:00"))


def test_empty_old_store_gets_random_retroactive_identity(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    build_schema27_store(a, tmp_path)
    shutil.copyfile(a, b)
    Storage(str(a)).close()
    Storage(str(b)).close()

    ia, ib = meta(a), meta(b)
    assert ia["instance_id_origin"] == "retroactive"
    assert ia["instance_id_basis"] == "random"
    assert "instance_id_basis_episode" not in ia
    assert ia["instance_id"] != ib["instance_id"]


def test_existing_identity_is_never_replaced_by_migration(tmp_path):
    db = tmp_path / "graph.db"
    build_schema27_store(db, tmp_path, OLD_EPISODES)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO meta (key, value) VALUES ('instance_id', 'kept')")
    conn.commit()
    conn.close()

    Storage(str(db)).close()
    assert meta(db) == {"instance_id": "kept"}


def test_identity_is_written_with_migration_028_or_not_at_all(tmp_path):
    db = tmp_path / "graph.db"
    build_schema27_store(db, tmp_path, OLD_EPISODES)
    mig = pre_identity_migrations(tmp_path)
    (mig / "028_store_identity.sql").write_text(
        (MIGRATIONS / "028_store_identity.sql").read_text() + "\nTHIS IS NOT SQL;\n")
    with pytest.raises(sqlite3.OperationalError):
        Storage(str(db), migrations_dir=str(mig))
    assert meta(db) == {}
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 27
    conn.close()


def test_read_only_paths_report_but_never_assign_identity(tmp_path):
    db = tmp_path / "graph.db"
    build_schema27_store(db, tmp_path, OLD_EPISODES)
    before = sha(db)

    survey = store_reader.survey(db)
    ro = Storage.open_read_only(db)
    ro.close()

    assert sha(db) == before
    assert meta(db) == {}
    assert survey["identity"]["status"] == "absent"
    assert survey["identity"]["would_assign"]["instance_id"] == (
        store_identity.derive_retroactive_id("alpha", "2026-03-01T00:00:00"))
    assert survey["changes"] == 0


def test_survey_reports_stored_identity(tmp_path):
    db = tmp_path / "graph.db"
    Storage(str(db)).close()
    survey = store_reader.survey(db)
    assert survey["identity"]["status"] == "present"
    assert survey["identity"]["instance_id"] == meta(db)["instance_id"]


def test_survey_of_store_without_meta_table(tmp_path):
    db = tmp_path / "graph.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT,"
        " content TEXT NOT NULL, episode_type TEXT, created_at TEXT NOT NULL);"
        "INSERT INTO episodes VALUES ('a', 's', 'x', 'note', '2026-03-20');")
    conn.close()
    plan = store_reader.survey(db)["identity"]["would_assign"]
    assert plan["instance_id"] == store_identity.derive_retroactive_id("a", "2026-03-20")


def test_calibrate_reports_identity_and_leaves_source_without_one(tmp_path):
    src = tmp_path / "src" / "graph.db"
    src.parent.mkdir()
    build_schema27_store(src, tmp_path, OLD_EPISODES)
    before = sha(src)

    report = calibrate.calibrate(src, tmp_path / "out")

    assert report["source_unchanged"] and sha(src) == before
    assert meta(src) == {}
    assert meta(tmp_path / "out" / "snapshot.db") == {}
    expected = store_identity.derive_retroactive_id("alpha", "2026-03-01T00:00:00")
    ident = report["identity"]
    assert ident["source"]["status"] == "absent"
    assert ident["source"]["would_assign"]["instance_id"] == expected
    assert ident["working"]["instance_id"] == expected
    assert ident["working"]["instance_id_origin"] == "retroactive"
    assert ident["agrees"] is True
    assert meta(tmp_path / "out" / "working.db")["instance_id"] == expected
    assert expected in (tmp_path / "out" / "report.md").read_text()

    # The source migrated later, on its own, arrives at the same identity.
    Storage(str(src)).close()
    assert meta(src)["instance_id"] == expected


def test_calibrate_reports_an_existing_identity(tmp_path):
    src = tmp_path / "graph.db"
    Storage(str(src)).close()
    report = calibrate.calibrate(src, tmp_path / "out")
    ident = report["identity"]
    assert ident["source"]["status"] == "present"
    assert ident["working"]["instance_id"] == ident["source"]["instance_id"]
    assert ident["agrees"] is True


def _genome(engram_dir: Path) -> Path:
    path = engram_dir / "genome" / "graph.db"
    path.parent.mkdir(parents=True)
    genome = Storage(str(path))
    genome.add_episode("gep1", "s1", "user is a mathematician", episode_type="observation")
    genome.mark_core("gep1", tier=2)
    genome.close()
    return path


def test_fork_mints_new_identity_and_records_source(tmp_path):
    genome = _genome(tmp_path)
    genome_id = meta(genome)["instance_id"]
    before = sha(genome)

    fork_instance("alpha", engram_dir=tmp_path)
    fork_instance("beta", engram_dir=tmp_path, from_source="alpha")

    alpha = meta(tmp_path / "instances" / "alpha" / "graph.db")
    beta = meta(tmp_path / "instances" / "beta" / "graph.db")
    assert sha(genome) == before
    assert alpha["instance_id"] not in (genome_id, beta["instance_id"])
    assert alpha["instance_id_origin"] == "fork"
    assert alpha["instance_id_basis"] == "random"
    assert alpha["forked_from_instance_id"] == genome_id
    assert beta["forked_from_instance_id"] == alpha["instance_id"]

    reg = InstanceRegistry(tmp_path / "instances.json").get("alpha")
    assert reg["instance_id"] == alpha["instance_id"]
    assert reg["forked_from_instance_id"] == genome_id

    # A normal open keeps the fork's own identity.
    Storage(str(tmp_path / "instances" / "alpha" / "graph.db")).close()
    assert meta(tmp_path / "instances" / "alpha" / "graph.db") == alpha


def test_fork_of_pre_identity_source_is_not_mistaken_for_it(tmp_path):
    genome = tmp_path / "genome" / "graph.db"
    genome.parent.mkdir()
    build_schema27_store(genome, tmp_path, OLD_EPISODES)
    before = sha(genome)

    fork_instance("alpha", engram_dir=tmp_path)
    fork_db = tmp_path / "instances" / "alpha" / "graph.db"
    assert sha(genome) == before and meta(genome) == {}  # fork never writes its source
    Storage(str(fork_db)).close()  # migration 028 runs on the fork
    Storage(str(genome)).close()   # and, later, on the source

    fork, source = meta(fork_db), meta(genome)
    assert fork["instance_id_origin"] == "fork"
    assert fork["instance_id"] != source["instance_id"]
    assert fork["forked_from_instance_id"] == source["instance_id"]
    assert source["instance_id_origin"] == "retroactive"


def test_genome_sync_keeps_provenance(tmp_path):
    genome = _genome(tmp_path)
    genome_id = meta(genome)["instance_id"]
    before = sha(genome)
    conn = sqlite3.connect(genome)
    created = conn.execute("SELECT created_at FROM episodes WHERE id='gep1'").fetchone()[0]
    conn.close()

    instance = Storage(str(tmp_path / "instance.db"))
    try:
        assert sync_genome(str(genome), instance) == 1
        row = instance.conn.execute(
            "SELECT id, origin_instance_id, origin_id, origin_created_at"
            " FROM episodes WHERE episode_type = 'genome_sync'").fetchone()
    finally:
        instance.close()

    assert sha(genome) == before
    assert row["id"] != "gep1"
    assert (row["origin_instance_id"], row["origin_id"], row["origin_created_at"]) == (
        genome_id, "gep1", created)


def test_genome_sync_backfills_provenance_of_earlier_syncs(tmp_path):
    genome = _genome(tmp_path)
    instance = Storage(str(tmp_path / "instance.db"))
    try:
        sync_genome(str(genome), instance)
        instance.conn.execute(
            "UPDATE episodes SET origin_instance_id = NULL, origin_id = NULL,"
            " origin_created_at = NULL")
        instance.conn.commit()
        assert sync_genome(str(genome), instance) == 0
        row = instance.conn.execute(
            "SELECT origin_id, origin_instance_id FROM episodes").fetchone()
    finally:
        instance.close()
    assert row["origin_id"] == "gep1"
    assert row["origin_instance_id"] == meta(genome)["instance_id"]


def test_provenance_survives_cold_storage_round_trip(tmp_path):
    store = Storage(str(tmp_path / "graph.db"))
    try:
        store.add_episode("e1", "s", "copied memory", embedding=[1.0] + [0.0] * 767)
        store.set_episode_origin("e1", "store-x", "orig-1", "2026-01-01T00:00:00")
        assert store.prune_episode_ids(["e1"]) == 1
        cold = store._cold_storage().execute(
            "SELECT origin_instance_id, origin_id, origin_created_at FROM episodes"
            " WHERE id = 'e1'").fetchone()
        assert tuple(cold) == ("store-x", "orig-1", "2026-01-01T00:00:00")
        store.revive_episode("e1", lambda _text: [1.0] + [0.0] * 767)
        ep = store.get_episode("e1")
    finally:
        store.close()
    assert (ep["origin_instance_id"], ep["origin_id"], ep["origin_created_at"]) == (
        "store-x", "orig-1", "2026-01-01T00:00:00")


def test_cold_db_predating_provenance_columns_is_upgraded(tmp_path):
    cold = sqlite3.connect(tmp_path / "cold.db")
    cold.execute(
        "CREATE TABLE episodes (id TEXT PRIMARY KEY, session_id TEXT, content TEXT NOT NULL,"
        " episode_type TEXT, created_at TEXT NOT NULL, context JSON,"
        " accessed_count INTEGER DEFAULT 0, last_accessed TEXT, compressed INTEGER DEFAULT 0,"
        " decay_strength REAL DEFAULT 0.0, core INTEGER NOT NULL DEFAULT 0, source TEXT,"
        " content_hash TEXT, dormant INTEGER NOT NULL DEFAULT 1,"
        " lane TEXT NOT NULL DEFAULT 'personal')")
    cold.commit()
    cold.close()
    store = Storage(str(tmp_path / "graph.db"))
    try:
        store.add_episode("e1", "s", "memory")
        assert store.prune_episode_ids(["e1"]) == 1
    finally:
        store.close()
