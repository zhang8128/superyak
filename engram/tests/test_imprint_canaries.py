"""The anti-goal test: no planted canary survives the build (store-copy spec I 16, "Canaries"; anti-goal Leakage)."""
from imprint import build, make_plan
from tests.imprint_support import (HOME, EH, any_value_contains, any_vec0_slot_equals, canary_store, fts_vocab_contains,
                                   open_package, plan_args, planted_vectors)

NOW = 1_761_415_451


def test_no_canary_survives_the_build(tmp_path):
    store, canaries = canary_store(tmp_path)
    plan = make_plan(*plan_args(tmp_path, store=lambda _: store, route=True))
    built = build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    conn = open_package(built.dir / "imprint.db")
    raw = (built.dir / "imprint.db").read_bytes()
    assert canaries and len(set(canaries)) == len(canaries)
    for c in canaries:
        assert not any_value_contains(conn, c), c
        assert not fts_vocab_contains(conn, c), c
        assert c.encode() not in raw and c.encode("latin-1", "ignore") not in raw, c
    vectors = planted_vectors(store)
    assert vectors and not any_vec0_slot_equals(conn, vectors)
    assert not any(v in raw for v in vectors)


def test_the_fixture_plants_what_the_checks_look_for(tmp_path):
    """The helpers find every canary and vector where they were planted, so the clean result above is not vacuous."""
    import sqlite3

    store, canaries = canary_store(tmp_path)
    sides = [sqlite3.connect(tmp_path / n) for n in ("cold.db", "categories.db", "categories_v2.db", "clipboard.db",
                                                      "notepad.db")]
    for c in canaries:
        assert any_value_contains(store.conn, c) or any(any_value_contains(s, c) for s in sides), c
    assert any_vec0_slot_equals(store.conn, planted_vectors(store))
    assert any(fts_vocab_contains(store.conn, c) for c in canaries)
    assert any(c.startswith("uncharacteristic") for c in canaries)
