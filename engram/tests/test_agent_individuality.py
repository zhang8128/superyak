"""Administrative individuality commands and lightweight published retrieval."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from cli import agent_create, house_init
from federation import InstanceRegistry
from sharing import read_shared, share
from storage import Storage


CLI = Path(__file__).resolve().parents[1] / "cli.py"


def run_cli(home, *args, success=True):
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        env={**os.environ, "ENGRAM_HOME": str(home)},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == (0 if success else 1), result.stderr
    assert len(result.stdout.splitlines()) == 1, result.stdout
    output = json.loads(result.stdout)
    assert isinstance(output, dict)
    if not success:
        assert set(output) == {"error"}
    return output


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_cli_uses_engram_home_and_existing_commands(tmp_path):
    home = tmp_path / "selected-home"
    genome_path = home / ".engram" / "genome" / "graph.db"
    genome_path.parent.mkdir(parents=True)
    genome = Storage(str(genome_path))
    genome.close()
    result = run_cli(home, "fork", "alpha")
    assert result["path"] == str(home / ".engram" / "instances" / "alpha" / "graph.db")
    assert set(run_cli(home, "list")["instances"]) == {"alpha"}
    assert run_cli(home, "drop", "alpha") == {"instance": "alpha", "dropped": True}
    assert run_cli(home, "list") == {"instances": {}}
    run_cli(home, "drop", "alpha", success=False)
    run_cli(home, "fork", "beta", "--from", "missing", success=False)


def test_agent_create_full_schema_fresh_identity_and_registry(tmp_path):
    root = tmp_path / ".engram"
    first = run_cli(tmp_path, "agent-create", "agent-alpha")
    assert first == {"instance": "agent-alpha", "path": str(root / "instances" / "agent-alpha" / "graph.db"),
                     "created": True, "seed": "empty"}
    store = Storage(first["path"])
    try:
        tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"episodes", "semantics", "instincts", "shared_memories", "resonances", "episode_vectors"} <= tables
        assert store.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 0
        identity = store.instance_identity()
        assert identity["instance_id_origin"] == "creation"
        assert identity["instance_id_basis"] == "random"
        assert InstanceRegistry(root / "instances.json").get("agent-alpha")["instance_id"] == identity["instance_id"]
    finally:
        store.close()
    second = agent_create("agent-beta", engram_dir=root)
    with sqlite3.connect(second["path"]) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='instance_id'").fetchone()[0] != identity["instance_id"]


def test_existing_agent_is_not_opened_migrated_or_reseeded(tmp_path):
    root = tmp_path / ".engram"
    path = root / "instances" / "agent-old" / "graph.db"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"sentinel old store: even a non-SQLite file must be untouched")
    registry = root / "instances.json"
    registry.write_text('{"agent-old":{"sentinel":true}}')
    before = snapshot(root)
    result = run_cli(tmp_path, "agent-create", "agent-old", "--seed", "genome-core")
    assert result == {"instance": "agent-old", "path": str(path), "created": False, "seed": "genome-core"}
    assert snapshot(root) == before


def test_agent_create_is_idempotent(tmp_path):
    agent_create("agent-repeat", engram_dir=tmp_path)
    before = snapshot(tmp_path)
    assert agent_create("agent-repeat", engram_dir=tmp_path)["created"] is False
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("name", ["agent-a", "agent-a0-", "agent-" + "a" * 63])
def test_agent_names_accept_exact_boundary(tmp_path, name):
    assert agent_create(name, engram_dir=tmp_path)["created"] is True


@pytest.mark.parametrize("name", ["agent-", "agent-A", "alpha", "agent-0", "agent-a_b",
                                  "agent-" + "a" * 64, "agent-a\n", "agent-../../escape"])
def test_agent_names_reject_invalid_before_any_writes(tmp_path, name):
    with pytest.raises(ValueError):
        agent_create(name, engram_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_genome_core_seed_copies_only_core_and_keeps_provenance(tmp_path):
    root = tmp_path / ".engram"
    path = root / "genome" / "graph.db"
    path.parent.mkdir(parents=True)
    genome = Storage(str(path))
    for tier in (0, 1, 2, 3):
        genome.add_episode(id=f"core-{tier}", session_id=None, content=f"synthetic genome tier {tier}")
        # Direct fixture write also exercises the >=2 selection boundary.
        genome.conn.execute("UPDATE episodes SET core=?, source='synthetic/test' WHERE id=?", (tier, f"core-{tier}"))
    genome.conn.commit()
    identity = genome.instance_identity()["instance_id"]
    origins = {r["id"]: r["created_at"] for r in genome.conn.execute("SELECT id, created_at FROM episodes")}
    genome.close()
    before = path.read_bytes()
    created = run_cli(tmp_path, "agent-create", "agent-seeded", "--seed", "genome-core")
    assert created["seed"] == "genome-core"
    store = Storage(created["path"])
    try:
        rows = [dict(r) for r in store.conn.execute("SELECT * FROM episodes")]
        assert {r["origin_id"] for r in rows} == {"core-2", "core-3"}
        for row in rows:
            assert row["id"] != row["origin_id"]
            assert row["origin_instance_id"] == identity
            assert row["origin_created_at"] == origins[row["origin_id"]]
            assert row["source"] == "synthetic/test"
            assert row["episode_type"] == "genome_sync"
        assert store.instance_identity()["instance_id"] != identity
    finally:
        store.close()
    assert path.read_bytes() == before


def test_bad_seed_or_missing_genome_is_json_error_without_store(tmp_path):
    run_cli(tmp_path, "agent-create", "agent-alpha", "--seed", "bad", success=False)
    run_cli(tmp_path, "agent-create", "agent-alpha", "--seed", "genome-core", success=False)
    run_cli(tmp_path, "agent-create", "agent-A", success=False)
    assert not (tmp_path / ".engram").exists()


def test_genome_seed_reads_committed_core_from_live_wal(tmp_path):
    root = tmp_path / ".engram"
    path = root / "genome" / "graph.db"
    path.parent.mkdir(parents=True)
    genome = Storage(str(path))
    try:
        genome.add_episode(id="live-core", session_id=None, content="synthetic core committed to live WAL")
        genome.mark_core("live-core", tier=2)
        genome.conn.commit()
        assert Path(str(path) + "-wal").stat().st_size > 0
        before = genome.conn.total_changes
        created = agent_create("agent-live", seed="genome-core", engram_dir=root)
        store = Storage(created["path"])
        try:
            assert [r[0] for r in store.conn.execute("SELECT origin_id FROM episodes")] == ["live-core"]
        finally:
            store.close()
        assert genome.conn.total_changes == before
    finally:
        genome.close()


def test_house_init_full_schema_and_idempotency_without_policy_changes(tmp_path, monkeypatch):
    import socket
    def no_socket(*_args, **_kwargs):
        pytest.fail("house-init opened a socket")
    monkeypatch.setattr(socket, "socket", no_socket)
    root = tmp_path / ".engram"
    root.mkdir()
    policy = root / "policy.toml"
    policy.write_text("synthetic policy sentinel")
    result = house_init(root)
    assert result == {"path": str(root / "instances" / "lighthouse" / "graph.db"), "created": True}
    conn = sqlite3.connect(result["path"])
    try:
        assert conn.execute("SELECT value FROM meta WHERE key='instance_id_origin'").fetchone()[0] == "creation"
        assert conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0] == 0
    finally:
        conn.close()
    before = snapshot(root)
    assert run_cli(tmp_path, "house-init") == {"path": result["path"], "created": False}
    assert snapshot(root) == before
    assert policy.read_text() == "synthetic policy sentinel"


def test_missing_house_returns_exact_json_without_creating_it(tmp_path):
    assert run_cli(tmp_path, "shared", "--audience", "group:agent-team") == {"shares": [], "house": False}
    assert not (tmp_path / ".engram").exists()


@pytest.fixture
def published(tmp_path):
    root = tmp_path / ".engram"
    house = house_init(root)["path"]
    src = Storage(str(tmp_path / "source.db"))
    pub = Storage(house)
    entries = [
        ("episode", "Alpha ΒETA", "first reason", "group:agent-team", "2026-10-03T08:00:00Z"),
        ("semantic", "Alpha finding", "second Βeta reason", "group:agent-team", "2026-10-03T08:00:00.100000+00:00"),
        ("episode", "Alpha alone", "other reason", "group:agent-team", "2026-10-03T08:00:00.200000Z"),
        ("episode", "Alpha beta commons", "public", "commons", "2026-10-03T08:00:01Z"),
        ("episode", "Alpha beta private group", "restricted", "group:private", "2026-10-03T08:00:02Z"),
    ]
    records = []
    for i, (layer, content, reason, audience, stamp) in enumerate(entries):
        if layer == "episode":
            src.add_episode(id=f"ep-{i}", session_id=None, content=content)
        else:
            src.conn.execute("INSERT INTO semantics (id, content, kind, confidence, created_at, lane) "
                             "VALUES (?, ?, 'fact', 0.8, ?, 'personal')", (f"ep-{i}", content, stamp))
            src.conn.commit()
        records.append(share(source_storage=src, published_storage=pub, source_id=f"ep-{i}", layer=layer,
                             audience=audience, reason=reason, source_instance="agent-alpha", now=stamp))
    # An unshared row in the house cannot be returned as a share.
    pub.add_episode(id="unshared", session_id=None, content="Alpha beta never shared")
    pub.conn.commit()
    src.close()
    pub.close()
    return Path(house), records


def test_shared_exact_shape_audience_query_and_after(tmp_path, published):
    _, records = published
    result = run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--query", "ALPHA βeta")
    assert set(result) == {"shares"}
    assert [r["share_id"] for r in result["shares"]] == [r.share_id for r in records[:2]]
    assert set(result["shares"][0]) == {"share_id", "memory_id", "layer", "source_instance", "reason", "shared_at", "content"}
    assert result["shares"][0]["content"] == "Alpha ΒETA"
    for after in ("2026-10-03T08:00:00Z", "2026-10-03T08:00:00.000000+00:00", "2026-10-03T01:00:00-07:00"):
        result = run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--after", after)
        assert [r["share_id"] for r in result["shares"]] == [r.share_id for r in records[1:3]]
    result = run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--after", records[1].shared_at)
    assert [r["share_id"] for r in result["shares"]] == [records[2].share_id]
    assert len(run_cli(tmp_path, "shared", "--audience", "commons")["shares"]) == 1
    assert run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--query", "Alpha beta NO-MATCH") == {"shares": []}


def test_shared_read_only_connection_and_unchanged_database(tmp_path, published, monkeypatch):
    house, _ = published
    before = house.read_bytes()
    original_connect = sqlite3.connect
    def checked_connect(database, *args, **kwargs):
        assert database.startswith("file:") and database.endswith("?mode=ro")
        assert kwargs["uri"] is True
        conn = original_connect(database, *args, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO meta VALUES ('ro-test', 'must fail')")
        return conn
    monkeypatch.setattr(sqlite3, "connect", checked_connect)
    assert read_shared(house, audience="group:agent-team")["shares"]
    assert house.read_bytes() == before


def test_shared_reads_committed_changes_from_live_wal(published):
    house, records = published
    pub = Storage(str(house))
    try:
        pub.conn.execute("UPDATE shared_memories SET reason='live WAL reason' WHERE share_id=?", (records[0].share_id,))
        pub.conn.commit()
        assert Path(str(house) + "-wal").stat().st_size > 0
        result = read_shared(house, audience="group:agent-team", query="live WAL")
        assert [r["share_id"] for r in result["shares"]] == [records[0].share_id]
    finally:
        pub.close()


def test_shared_does_not_import_storage_embedder_or_heavy_modules(tmp_path, published):
    house, _ = published
    code = """import importlib.abc, sys
class BlockHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'storage', 'embeddings', 'engine', 'fastembed', 'torch', 'numpy', 'sqlite_vec'}:
            raise AssertionError('heavy import: ' + fullname)
sys.meta_path.insert(0, BlockHeavy())
import cli
from sharing import read_shared
assert len(read_shared(sys.argv[1], audience='group:agent-team')['shares']) == 3
"""
    result = subprocess.run([sys.executable, "-c", code, str(house)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_shared_timestamp_order_preserves_microseconds_with_offsets(published):
    house, records = published
    conn = sqlite3.connect(house)
    # The earlier instant has the lexically later timestamp. SQLite julian
    # dates round both instants to the same millisecond.
    conn.execute("UPDATE shared_memories SET shared_at=? WHERE share_id=?",
                 ("2026-10-03T09:00:00.000100+01:00", records[0].share_id))
    conn.execute("UPDATE shared_memories SET shared_at=? WHERE share_id=?",
                 ("2026-10-03T08:00:00.000200Z", records[1].share_id))
    conn.commit()
    conn.close()
    rows = read_shared(house, audience="group:agent-team")["shares"]
    assert [r["share_id"] for r in rows[:2]] == [records[0].share_id, records[1].share_id]
    after = read_shared(house, audience="group:agent-team", after=rows[0]["shared_at"])["shares"]
    assert after[0]["share_id"] == records[1].share_id


def test_shared_limit_defaults_maximum_and_filters_before_limit(tmp_path, published):
    house, _ = published
    conn = sqlite3.connect(house)
    for i in range(210):
        eid = f"extra-{i:03}"
        conn.execute("INSERT INTO episodes (id, content, created_at) VALUES (?, ?, ?)",
                     (eid, "later needle" if i == 209 else "later", "2026-10-04T00:00:00Z"))
        conn.execute("INSERT INTO shared_memories VALUES (?, ?, 'agent-alpha', ?, 'episode', "
                     "'group:agent-team', 'reason', 'unused', '2026-10-04T00:00:00Z')", (eid, eid, eid))
    conn.commit()
    conn.close()
    assert len(run_cli(tmp_path, "shared", "--audience", "group:agent-team")["shares"]) == 20
    assert len(run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--limit", "200")["shares"]) == 200
    matched = run_cli(tmp_path, "shared", "--audience", "group:agent-team", "--query", "needle", "--limit", "1")
    assert matched["shares"][0]["share_id"] == "extra-209"


@pytest.mark.parametrize("args", [("--audience", "world"), ("--audience", "group:UPPER"),
                                  ("--audience", "commons", "--limit", "0"),
                                  ("--audience", "commons", "--limit", "201"),
                                  ("--audience", "commons", "--after", "invalid"), ()])
def test_shared_invalid_parameters_fail_with_json(tmp_path, args):
    run_cli(tmp_path, "shared", *args, success=False)
