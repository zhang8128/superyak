"""session_registry — silent provenance store (spec: 2026-07-11-engram-codex-hooks-design.md)."""
import pytest

from storage import Storage


@pytest.fixture
def store(tmp_path):
    s = Storage(str(tmp_path / "graph.db"))
    yield s
    s.close()


def test_migration_creates_table(store):
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(session_registry)")}
    assert cols == {"session_id", "harness", "model", "repo", "started_at"}


def test_stamp_inserts_row(store):
    store.stamp_session_registry("s1", harness="codex", model="gpt-5.6-sol", repo="/tmp/x")
    row = store.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id='s1'"
    ).fetchone()
    assert tuple(row) == ("codex", "gpt-5.6-sol", "/tmp/x")


def test_stamp_coalesce_merges_without_clobbering(store):
    # Server stamps first (no model), hook stamps later (has model):
    store.stamp_session_registry("s2", harness="codex", model=None, repo="/tmp/x")
    store.stamp_session_registry("s2", harness="codex", model="gpt-5.6-sol", repo="/should/not/clobber")
    row = store.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id='s2'"
    ).fetchone()
    assert row["model"] == "gpt-5.6-sol"   # NULL filled in
    assert row["repo"] == "/tmp/x"          # existing value kept


def test_stamp_empty_session_id_is_noop(store):
    store.stamp_session_registry("", harness="codex", model=None, repo=None)
    n = store.conn.execute("SELECT COUNT(*) FROM session_registry").fetchone()[0]
    assert n == 0


def test_stamp_missing_table_is_swallowed(store):
    store.conn.execute("DROP TABLE session_registry")
    store.stamp_session_registry("s3", harness="codex", model=None, repo=None)  # must not raise


def test_stamp_bad_payload_is_swallowed(store):
    store.stamp_session_registry("s4", harness=object(), model=None, repo=None)  # must not raise
