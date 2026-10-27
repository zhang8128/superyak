"""The selection and the terms (store-copy spec I 5.2, 5.3; plan R26)."""
import uuid
from collections import Counter
from datetime import datetime, timezone

import pytest

from imprint_filter import (IdSet, PlanRefused, Scratch, ScratchMap, base, parse_instant, parse_selection,
                            parse_terms)
from tests.imprint_support import T, ctx, ep, new_store, published_house, selection, share_as

ROUTE_TERMS = dict(audience="place:home/andy", actions="imprint,route", purposes="calibration,trail-evaluation",
                   days=90, operator="andy")
OPEN = dict(lanes="work", layers="episode", since=None, until=None, shared_with=None, exclude_file=None,
            unsourced=False, now=T("2026-10-25"))


def test_lanes_and_the_half_open_window(tmp_path):
    s = new_store(tmp_path, "s")
    for i, at in {"in": "2026-01-01T00:00:00+00:00", "no-zone": "2026-05-01T00:00:00",
                  "just-before": "2026-10-25T17:59:59.999999+00:00", "at-t1": "2026-10-25T18:00:00+00:00",
                  "before": "2025-12-31T23:59:59.999999+00:00", "bad": "yesterday"}.items():
        ep(s, i, at=at)
    ep(s, "personal", lane="personal", at="2026-02-01T00:00:00+00:00")
    counts = Counter()
    got = list(base(s.conn, "episode", selection(since=T("2026-01-01"), until=T("2026-10-25T18:00:00Z")), ctx(s), counts))
    assert got == ["in", "no-zone", "just-before"] and counts["unparseable_time"] == 1


def test_exclude_and_layers(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "a"); ep(s, "b")
    assert list(base(s.conn, "episode", selection(exclude={"b"}), ctx(s), Counter())) == ["a"]
    with pytest.raises(PlanRefused):
        parse_selection(lanes="", layers="episode", since=None, until=None, shared_with=None,
                        exclude_file=None, unsourced=False, now=T("2026-10-25"))


def test_shared_with_matches_instance_layer_audience_and_digest(tmp_path):
    s, pub = new_store(tmp_path, "s"), published_house(tmp_path)
    for i in ("shared", "other-audience", "changed", "other-instance", "other-layer"): ep(s, i)
    share_as(s, pub, "shared", "group:ph"); share_as(s, pub, "other-audience", "group:parks")
    share_as(s, pub, "changed", "group:ph"); s.conn.execute("UPDATE episodes SET content='edited' WHERE id='changed'")
    share_as(s, pub, "other-instance", "group:ph", source_instance_id=str(uuid.uuid4()))  # another store's share of that id
    share_as(s, pub, "other-layer", "group:ph", layer="semantic")         # the id shared as a semantic, not this episode
    got = list(base(s.conn, "episode", selection(shared_with="group:ph"), ctx(s, published=pub), Counter()))
    assert got == ["shared"]


def test_shared_with_and_no_house_admits_nothing(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "a")
    assert list(base(s.conn, "episode", selection(shared_with="group:ph"), ctx(s), Counter())) == []


def test_terms_accept_only_step_one_values():
    assert parse_terms(audience="place:home/andy", actions="imprint,route", purposes="calibration,trail-evaluation",
                       days=90, operator="andy").route
    for bad in [dict(audience="place:home/jenn"), dict(actions="route"), dict(purposes="calibration"),
                dict(days=366), dict(days=0), dict(operator="andy.b", audience="place:home/andy.b")]:
        with pytest.raises(PlanRefused):
            parse_terms(**{**ROUTE_TERMS, **bad})


def test_terms_without_route_and_their_other_refusals():
    t = parse_terms(audience="place:home/andy", actions="imprint", purposes="calibration", days=1, operator="andy")
    assert not t.route and t.actions == {"imprint"} and t.purposes == {"calibration"} and t.days == 1
    assert parse_terms(**{**ROUTE_TERMS, "days": 365}).days == 365
    for bad in [dict(actions="imprint,read"), dict(actions=""), dict(purposes="calibration,trail-evaluation,x"),
                dict(actions="imprint", purposes="calibration,trail-evaluation"), dict(days="90"),
                dict(operator="Andy", audience="place:home/Andy"), dict(audience="group:ph")]:
        with pytest.raises(PlanRefused):
            parse_terms(**{**ROUTE_TERMS, **bad})


def test_parse_selection_values(tmp_path):
    ex = tmp_path / "x.txt"; ex.write_text("a\n\n  b  \n")
    sel = parse_selection(**{**OPEN, "lanes": "work,personal", "layers": "semantic,episode", "since": "2026-01-01",
                             "until": "2026-02-01T00:00:00+01:00", "shared_with": "group:ph",
                             "exclude_file": ex, "unsourced": True})
    assert sel.lanes == {"work", "personal"} and sel.layers == {"episode", "semantic"}
    assert sel.since == T("2026-01-01") and sel.until == T("2026-01-31T23:00:00Z")
    assert sel.shared_with == "group:ph" and sel.exclude == {"a", "b"} and sel.unsourced
    assert parse_selection(**OPEN).until == T("2026-10-25") and parse_selection(**OPEN).since is None
    for bad in [dict(lanes="work,home"), dict(layers=""), dict(layers="instinct"), dict(since="soon"),
                dict(until="soon"), dict(shared_with="everyone"), dict(exclude_file=tmp_path / "missing")]:
        with pytest.raises(PlanRefused):
            parse_selection(**{**OPEN, **bad})


def test_parse_instant():
    assert parse_instant("2026-05-01T00:00:00") == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert parse_instant("2026-05-01T02:00:00+02:00") == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert parse_instant("2026-05-01T00:00:00Z") == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert parse_instant("yesterday") is None and parse_instant(None) is None and parse_instant(7) is None


def test_base_reads_without_holding_the_table(tmp_path):
    s = new_store(tmp_path, "s")
    for i in range(5): ep(s, f"e{i}", at=f"2026-01-0{i + 1}T00:00:00+00:00")
    it = base(s.conn, "episode", selection(), ctx(s), Counter())
    assert next(it) == "e0"
    ep(s, "late", at="2026-01-09T00:00:00+00:00")   # a write while the iterator is open must not break it
    assert list(it)[:3] == ["e1", "e2", "e3"]


def test_semantic_layer(tmp_path):
    s = new_store(tmp_path, "s")
    s.conn.execute("INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash, lane)"
                   " VALUES ('m', 'text', 'fact', 0.5, '2026-02-01T00:00:00+00:00', 0, 'h', 'work')")
    assert list(base(s.conn, "semantic", selection(), ctx(s), Counter())) == ["m"]


def test_idset_keeps_insertion_order_and_membership(tmp_path):
    sc = Scratch(tmp_path / "sc.db")
    ids = IdSet(sc)
    for i in ("b", "a", "b", "c"): ids.add(i)
    assert list(ids) == ["b", "a", "c"] and len(ids) == 3 and "a" in ids and "z" not in ids
    assert list(IdSet(sc)) == []     # each set is its own table


def test_scratchmap_is_a_mapping(tmp_path):
    sc = Scratch(tmp_path / "sc.db")
    m = ScratchMap(sc)
    m["k1"] = {"n": 1}; m["k2"] = [2]; m["k1"] = {"n": 3}
    assert list(m) == ["k1", "k2"] and m["k1"] == {"n": 3} and len(m) == 2 and "k2" in m and "k3" not in m
    assert dict(m.items()) == {"k1": {"n": 3}, "k2": [2]} and m.get("k3") is None
    del m["k1"]
    assert list(m) == ["k2"]
    with pytest.raises(KeyError):
        m["k1"]


def test_scratch_lives_in_its_file_and_stores_temporaries_on_disk(tmp_path):
    path = tmp_path / "sc.db"
    sc = Scratch(path)
    IdSet(sc).add("x")
    sc.close()
    assert path.is_file()
    assert Scratch(path).conn.execute("PRAGMA temp_store").fetchone()[0] == 1   # FILE
