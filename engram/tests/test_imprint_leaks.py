"""The leak checks L1 to L4 on a finished package (store-copy spec I 6.4, D34)."""
import sqlite3
import uuid

from imprint_checks import UUID_TOKEN, l1_values, l2_fts, l3_vec0, l4_raw
from tests.imprint_support import (load_vec, plant_index_only_term, poke_invalid_slot, put_value_across_page_boundary,
                                   rename_rowids_id, writable_copy, written, written_with_x_star)


def test_l2_fails_an_index_entry_with_no_content_row_that_integrity_check_passes(tmp_path):
    conn = writable_copy(written(tmp_path))
    plant_index_only_term(conn, "episode_fts", rowid=999, term="orphan")
    # raises if the index is inconsistent (P38); the review measured that it does not here
    conn.execute("INSERT INTO episode_fts(episode_fts) VALUES('integrity-check')")
    assert l2_fts(conn, tmp_path / "scratch") != []


def test_l3_fails_a_non_zero_invalid_slot_and_an_unknown_id(tmp_path):
    a, b = writable_copy(written(tmp_path)), writable_copy(written(tmp_path, name="b"))
    poke_invalid_slot(a, "episode_vectors", byte=0x7F)
    rename_rowids_id(b, "episode_vectors", to=str(uuid.uuid4()))
    assert l3_vec0(a, None) != [] and l3_vec0(b, None) != []


def test_l1_finds_a_uuid_split_across_an_overflow_page(tmp_path):
    left_out = str(uuid.uuid4())
    conn = writable_copy(written(tmp_path))
    put_value_across_page_boundary(conn, "episodes", "content", left_out)
    assert l1_values(conn, frozenset({left_out})) != []


def test_a_clean_package_passes_all_four(tmp_path):
    path, x_star, expected = written_with_x_star(tmp_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    load_vec(conn)
    assert l1_values(conn, x_star) == l2_fts(conn, tmp_path / "s") == l3_vec0(conn, expected) == l4_raw(path, x_star) == []


def test_rf3_honest_unicode_package_passes_every_leak_check(tmp_path):
    texts = ["Jenn drove me to the clinic 🚗", "café naïve façade", "東京で会議", "x" * 5000, "ﬁ ligature and ß"]
    path, x_star, expected = written_with_x_star(tmp_path, contents=texts)
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    load_vec(conn)
    assert l1_values(conn, x_star) == l2_fts(conn, tmp_path / "s") == l3_vec0(conn, expected) == l4_raw(path, x_star) == []


def test_l3_fails_a_vector_that_is_not_the_expected_bytes_and_names_no_value(tmp_path):
    path, _, expected = written_with_x_star(tmp_path)
    conn = writable_copy(path)
    some = next(iter(expected["episode_vectors"]))
    expected["episode_vectors"][some] = "0" * 64
    lines = l3_vec0(conn, expected)
    assert lines and not any(some in line for line in lines)


def test_l4_finds_a_token_across_a_chunk_edge_and_the_pattern_ignores_case(tmp_path):
    token = str(uuid.uuid4())
    f = tmp_path / "raw.bin"
    f.write_bytes(b"\0" * (2**20 - 10) + token.upper().encode() + b"\0" * 100)
    assert l4_raw(f, frozenset({token})) != []
    assert UUID_TOKEN.search(token.upper())
    assert l4_raw(f, frozenset()) == []
