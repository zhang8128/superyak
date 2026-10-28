"""Every table has a rule (I 6.2, D4)."""
import ast

import pytest

from imprint_filter import (CITING_OPERATIONS, DIGEST_TABLES, HOOK_TABLES, TABLE_RULES, UnclassifiedTable,
                            check_package_tables, classify_source, is_shadow)
from tests.imprint_support import ENGRAM_DIR as ENGRAM, add_hook_tables, hook_ddl_names, new_store


def table_names(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]


def virtual_tables(conn):
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%'")]


def literal_assigned(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def test_every_table_classified(tmp_path):
    store = new_store(tmp_path, "all"); add_hook_tables(store.conn)    # DDL read from hooks/nudge.py and hooks/wake.py
    virtual = virtual_tables(store.conn)
    for name in table_names(store.conn):
        assert name in TABLE_RULES or is_shadow(name, virtual), name
    assert hook_ddl_names() <= set(TABLE_RULES)      # every CREATE TABLE in the hooks, session_bias included
    assert set(HOOK_TABLES) | {"session_bias"} == hook_ddl_names()


def test_a_source_only_table_is_not_copied_and_is_named(tmp_path):
    store = new_store(tmp_path, "s"); store.conn.execute("CREATE TABLE my_notes(id TEXT PRIMARY KEY)")
    assert classify_source(store.conn).unnamed == ("my_notes",)


def test_a_package_table_without_a_rule_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.delitem(TABLE_RULES, "anchors")
    with pytest.raises(UnclassifiedTable, match="anchors"):
        check_package_tables(new_store(tmp_path, "p").conn)


def test_citing_operations_match_the_stop_hook():
    tree = ast.parse((ENGRAM / "hooks" / "sleep.py").read_text())
    assert CITING_OPERATIONS == literal_assigned(tree, "CITING_OPERATIONS")


def test_the_rules_follow_the_spec(tmp_path):
    assert set(TABLE_RULES.values()) == {"filtered", "dropped", "rebuilt", "built", "never"}
    assert list(TABLE_RULES)[:3] == ["episodes", "semantics", "instincts"]
    assert [t for t, r in TABLE_RULES.items() if r == "built"] == ["imprint_subjects"]
    assert [t for t, r in TABLE_RULES.items() if r == "never"] == [f"sqlite_stat{i}" for i in range(1, 5)]
    assert TABLE_RULES["session_bias"] == "dropped" and all(TABLE_RULES[t] == "dropped" for t in HOOK_TABLES)
    assert len(DIGEST_TABLES) == 11 and DIGEST_TABLES[-1] == "imprint_subjects"
    assert all(TABLE_RULES[t] in ("filtered", "built") for t in DIGEST_TABLES)
    assert is_shadow("episode_vectors_chunks", ["episode_vectors"]) and not is_shadow("episodes", ["episode_vectors"])


def test_classify_source_splits_the_rules(tmp_path):
    store = new_store(tmp_path, "c"); add_hook_tables(store.conn)
    store.conn.execute("CREATE TABLE zeta(id TEXT)"); store.conn.execute("CREATE TABLE alpha(id TEXT)")
    got = classify_source(store.conn)
    assert "episodes" in got.copied and "episode_fts" not in got.copied and "imprint_subjects" not in got.copied
    assert "instincts" in got.dropped and "context_threads" in got.dropped and "episodes" not in got.dropped
    assert got.unnamed == ("alpha", "zeta")


def test_a_dropped_table_is_empty_in_a_fresh_package(tmp_path):
    """Check 9 (I 6.2): every dropped table is empty. A migration that seeds a table (029's counter row) makes it rebuilt."""
    store = new_store(tmp_path, "fresh")
    present = set(table_names(store.conn))
    for name, rule in TABLE_RULES.items():
        if rule == "dropped" and name in present:
            assert store.conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == 0, name
    assert TABLE_RULES["shared_memories_changes"] == "rebuilt"
