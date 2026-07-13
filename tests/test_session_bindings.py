import sqlite3

import pytest

from storage import Storage


@pytest.fixture
def store(tmp_path):
    value = Storage(str(tmp_path / "graph.db"))
    yield value
    value.close()


def test_migration_creates_exact_binding_schema(store):
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(session_bindings)")}
    assert cols == {"run_key", "session_id", "bound_at"}


def test_bind_resolve_rebind_and_clear(store):
    store.bind_session("codex:10", "session-a")
    assert store.resolve_session_binding("codex:10") == "session-a"
    store.bind_session("codex:10", "session-b")
    assert store.resolve_session_binding("codex:10") == "session-b"
    store.clear_session_binding("codex:10", session_id="session-a")
    assert store.resolve_session_binding("codex:10") == "session-b"
    store.clear_session_binding("codex:10", session_id="session-b")
    assert store.resolve_session_binding("codex:10") is None


def test_concurrent_run_keys_are_isolated(store):
    store.bind_session("codex:10", "session-a")
    store.bind_session("codex:11", "session-b")
    assert store.resolve_session_binding("codex:10") == "session-a"
    assert store.resolve_session_binding("codex:11") == "session-b"


def test_binding_operations_fail_open_without_table(store):
    store.conn.execute("DROP TABLE session_bindings")
    store.bind_session("codex:10", "session-a")
    assert store.resolve_session_binding("codex:10") is None
    store.clear_session_binding("codex:10")


def test_empty_binding_inputs_are_noops(store):
    store.bind_session("", "session-a")
    store.bind_session("codex:10", "")
    assert store.conn.execute("SELECT COUNT(*) FROM session_bindings").fetchone()[0] == 0


def test_malformed_binding_payload_is_swallowed(store):
    store.bind_session(object(), "session-a")
    assert store.resolve_session_binding("codex:missing") is None
