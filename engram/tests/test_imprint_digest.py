"""The package's rows and the plan digest (store-copy spec I 5.4, 7.1, D22, D42, R5, R26)."""
import hashlib

import pytest

from imprint_filter import (DIGEST_TABLES, FILTER, canonical, contents_of, package_rows, plan_digest, row_key,
                            scope_of, sha256_value)
from tests.imprint_support import ctx, digest_ledger, digest_store, selection, terms

SCOPE = {"lanes": ["work"], "layers": ["episode", "semantic"], "since": None, "until": "2026-10-25T18:00:00Z",
         "shared_with": None, "unsourced_semantics": False}


def test_canonical_is_the_peers_form_and_refuses_floats():
    assert canonical({"b": [1, "é", None, True], "a": {"z": 0}}) == '{"a":{"z":0},"b":[1,"é",null,true]}'.encode()
    for bad in ({"x": 1.5}, {"x": float("nan")}, {"x": [object()]}):
        with pytest.raises(ValueError):
            canonical(bad)


def test_the_digest_input_has_exactly_the_eleven_tables_sorted_by_canonical_bytes():
    rows = {t: [] for t in DIGEST_TABLES} | {"semantic_sources": [{"semantic_id": "s2", "episode_id": "e1"},
                                                                 {"semantic_id": "s1", "episode_id": "e9"}]}
    expected = hashlib.sha256(canonical({"filter": "imprint-filter-v1", "scope": SCOPE, "rows": {
        t: ([["s1", "e9"], ["s2", "e1"]] if t == "semantic_sources" else []) for t in DIGEST_TABLES}})).hexdigest()
    assert plan_digest(SCOPE, rows) == expected


def test_a_repeated_key_stays_repeated():
    row = {"semantic_id": "s1", "episode_id": "e1"}
    rows = {t: [] for t in DIGEST_TABLES} | {"semantic_sources": [row, dict(row)]}
    expected = hashlib.sha256(canonical({"filter": FILTER, "scope": SCOPE, "rows": {
        t: ([["s1", "e1"], ["s1", "e1"]] if t == "semantic_sources" else []) for t in DIGEST_TABLES}})).hexdigest()
    assert plan_digest(SCOPE, rows) == expected


def test_measured_numbers_are_not_keys_but_content_is(tmp_path):
    s = digest_store(tmp_path)
    before = plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows)
    s.conn.execute("UPDATE episodes SET accessed_count = accessed_count + 7, last_accessed = '2026-10-25T17:00:00+00:00'")
    s.conn.execute("UPDATE resonances SET co_occurrences = co_occurrences + 1")
    assert plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows) == before
    s.conn.execute("UPDATE episodes SET content = content || '!' WHERE id = 'e1'")
    assert plan_digest(SCOPE, package_rows(s.conn, selection(), terms(), ctx(s)).rows) != before


def test_contents_names_only_non_empty_tables(tmp_path):
    s = digest_store(tmp_path)
    rows = package_rows(s.conn, selection(), terms(route=False), ctx(s)).rows
    got = contents_of(rows)
    assert set(got) <= set(DIGEST_TABLES) and "memory_log" not in got and "operation_log" not in got
    assert got == {"episodes": 2, "semantics": 1, "episode_vectors": 2, "semantic_vectors": 1,
                   "semantic_sources": 1, "resonances": 1}


def test_the_streamed_digest_equals_the_whole_object(tmp_path):
    s = digest_store(tmp_path, every_table=True, cosubjects=True)      # at home, with imprint_subjects rows
    led = digest_ledger(tmp_path, s)
    pr = package_rows(s.conn, selection(), terms(route=True), ctx(s, home=True, ledger=led, owner="andy"))
    rows = pr.rows
    assert set(contents_of(rows)) == set(DIGEST_TABLES)
    whole = {t: sorted((row_key(t, r) for r in rows[t]), key=canonical) for t in DIGEST_TABLES}
    expected = hashlib.sha256(canonical({"filter": FILTER, "scope": SCOPE, "rows": whole})).hexdigest()
    assert plan_digest(SCOPE, rows) == expected and len(DIGEST_TABLES) == 11 and "imprint_subjects" in DIGEST_TABLES
    assert pr.others == {"memories": 2, "people": 2}      # e1 (jenn) and s1 (lee, jenn)
    assert plan_digest(SCOPE, rows) == expected           # a lookup starts a new cursor each time


def test_others_is_zero_away_from_home_and_without_a_ledger(tmp_path):
    s = digest_store(tmp_path)
    assert package_rows(s.conn, selection(), terms(), ctx(s, home=True)).others == {"memories": 0, "people": 0}


def test_row_keys_follow_the_table(tmp_path):
    h = sha256_value
    assert sha256_value(None) == "" and sha256_value("a") == hashlib.sha256(b"a").hexdigest()
    assert sha256_value(b"\x00\x01") == hashlib.sha256(b"\x00\x01").hexdigest()
    assert row_key("subdivision_events", {"id": "d", "parent_id": "p", "peer_ids": '["b","a"]'}) == ["d", "p", ["a", "b"]]
    assert row_key("memory_log", {"id": "l", "timestamp": "t", "event_type": "recall", "layer": "episode",
                                  "target_ids": '["x"]', "context": '{"a":1}', "outcome": None}) == [
        "l", "t", "recall", "episode", ["x"], {"a": 1}, None]
    assert row_key("episodes", {"id": "e", "lane": "work", "created_at": "c", "session_id": None,
                                "content": "x", "context": None}) == ["e", "work", "c", None, h("x"), ""]
    assert row_key("imprint_subjects", {"memory_id": "e", "layer": "episode", "subject": "person:j"}) == [
        "e", "episode", "person:j"]


def test_scope_of_is_the_requests_scope():
    sel = selection(since=0, lanes=frozenset({"work", "personal"}), shared_with="lee", unsourced=True)
    assert scope_of(sel) == {"lanes": ["personal", "work"], "layers": ["episode", "semantic"],
                             "since": "1970-01-01T00:00:00Z", "until": "2026-10-25T18:00:00Z",
                             "shared_with": "lee", "unsourced_semantics": True}
    assert scope_of(selection())["since"] is None
