"""The selection and the terms (store-copy spec I 5.2, 5.3; plan R26)."""
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone

import pytest

import store_reader
from imprint_filter import (IdSet, People, PlanRefused, Refusals, Scratch, ScratchMap, Shipped, base, check_owner,
                            check_source, cosubject_rows, cosubjects_of, parse_instant, parse_selection,
                            parse_terms, people)
from permissions import subjects_of
from tests.imprint_support import (GENOME_ID, NOW, T, add_subject, base_ids, copy_of, ctx, deny, empty_old_store,
                                   ep, forbid_state, future_store, iid, imprint_file, ledger, link_copies,
                                   new_store, published_house, published_house_file, ref_of, remove_cosubject,
                                   retire, retire_place, selection, share_as)

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


def test_co_subjects_and_unsettled_lanes_stay_home_and_are_counted(tmp_path):
    s = new_store(tmp_path, "s"); home = tmp_path / "home"
    for i in ("plain", "about-jenn", "pending", "other-lane", "no-note"): ep(s, i)
    led = ledger(home, owner="sam", store=s, cosubjects={"about-jenn": "person:jenn"},
                 lane_notes={"pending": "pending", "other-lane": "personal", "plain": "work"})
    c, counts = ctx(s, ledger=led, home=False), Counter()
    got = list(base(s.conn, "episode", selection(), c, counts))
    assert got == ["no-note", "plain"]                   # one created_at, so id order
    assert counts["needs_yes"] == 1 and people(c.scratch, "needs_yes") == People(1, (("person:jenn", 1),), 0)
    assert counts["lane_unsettled"] == 2 and not [k for k in counts if "person:" in k]   # no key per person (S3)
    assert sorted(base(s.conn, "episode", selection(), ctx(s, ledger=None), Counter())) == sorted(
        ["plain", "about-jenn", "pending", "other-lane", "no-note"])

def test_in_the_owners_home_co_subjects_ship_and_are_carried(tmp_path):
    s = new_store(tmp_path, "s"); home = tmp_path / "home"
    for i in ("plain", "about-jenn", "about-two"): ep(s, i)
    led = ledger(home, owner="andy", store=s, cosubjects={"about-jenn": "person:jenn",
                                                          "about-two": ["person:jenn", "person:lee"]})
    c, counts = ctx(s, ledger=led, owner="andy", home=True), Counter()
    assert sorted(base(s.conn, "episode", selection(), c, counts)) == ["about-jenn", "about-two", "plain"]
    assert counts["others_memories"] == 2 and people(c.scratch, "others") == People(
        2, (("person:jenn", 2), ("person:lee", 1)), 0)
    rows = list(cosubject_rows(Shipped(("about-jenn", "about-two", "plain"), ()), c))
    assert rows == [("about-jenn", "episode", "person:jenn"), ("about-two", "episode", "person:jenn"),
                    ("about-two", "episode", "person:lee")]
    assert list(cosubject_rows(Shipped(("plain",), ()), ctx(s, ledger=None, owner="andy", home=True))) == []

def test_only_effective_co_subjects_are_carried(tmp_path):
    s = new_store(tmp_path, "s"); ep(s, "m3"); ep(s, "m4")
    led = ledger(tmp_path / "home", owner="andy", store=s,
                 cosubjects={"m3": "person:jenn", "m4": ["person:andy", "person:lee"]})   # m4 also names the owner
    remove_cosubject(led, "m3", "person:jenn", by="person:jenn")        # her own act (P 7.4)
    c = ctx(s, ledger=led, owner="andy", home=True)
    assert list(cosubject_rows(Shipped(("m3", "m4"), ()), c)) == [("m4", "episode", "person:lee")]   # never the owner (nit 5)

def test_a_co_subjects_no_keeps_the_memory_home(tmp_path, monkeypatch):    # I 5.2 denied(m); the check's M1
    s = new_store(tmp_path, "s")
    for i in ("about-jenn", "about-lee", "plain"): ep(s, i)
    read_cal = dict(actions=["read"], purposes=["calibration"])
    led = ledger(tmp_path / "home", owner="andy", store=s,
                 cosubjects={"about-lee": "person:lee", "about-jenn": "person:jenn"},
                 denies={"person:lee": [deny(**read_cal)],                                     # lee said no
                         "person:jenn": [deny(**read_cal, revoked=True), deny(**read_cal, valid_until=NOW - 1),
                                         deny(**read_cal, audience=["place:la-county/parks"])]})   # none refuses
    c, counts = ctx(s, ledger=led, owner="andy", home=True, now=NOW), Counter()
    assert sorted(base(s.conn, "episode", selection(), c, counts)) == ["about-jenn", "plain"]
    assert people(c.scratch, "said_no").named == (("person:lee", 1),) and counts["others_memories"] == 1
    assert list(cosubject_rows(Shipped(("about-jenn", "plain"), ()), c)) == [("about-jenn", "episode", "person:jenn")]
    roads = ledger(tmp_path / "h2", owner="andy", store=s, cosubjects={"about-lee": "person:lee"},
                   denies={"person:lee": [deny(kinds=["road", "trail"], actions=["route"], purposes=["trail-evaluation"])]})
    assert "about-lee" in base_ids(s, roads, route=False) and "about-lee" not in base_ids(s, roads, route=True)
    for kinds in (["trail"], ["road"]):                          # G18 CD1: a no on trails alone, or roads alone, also holds
        one = ledger(tmp_path / f"one-{kinds[0]}", owner="andy", store=s, cosubjects={"about-lee": "person:lee"},
                     denies={"person:lee": [deny(kinds=kinds, actions=["route"], purposes=["trail-evaluation"])]})
        assert "about-lee" in base_ids(s, one, route=False) and "about-lee" not in base_ids(s, one, route=True), kinds
    calm = ledger(tmp_path / "h3", owner="andy", store=s, cosubjects={"about-lee": "person:lee"})
    forbid_state(monkeypatch)                                  # any Ledger.state() call fails the test (the re-check's S5)
    calm_ctx = ctx(s, ledger=calm, owner="andy", home=True, now=NOW)
    assert not Refusals(calm, calm_ctx).any
    assert sorted(base(s.conn, "episode", selection(), calm_ctx, Counter())) == ["about-jenn", "about-lee", "plain"]

def test_a_copy_carries_what_its_source_gains_after_the_copy(tmp_path):   # I 5.2; the re-check's RM1 (P 6.3 item 1, 7.4)
    src = f"mem:{GENOME_ID}/episode/g1"                    # genome sync's source (federation.py:207-213)
    for owner, home in (("andy", True), ("sam", False)):
        s = new_store(tmp_path / owner, "s"); ep(s, "copy"); ep(s, "plain")
        led = ledger(tmp_path / owner / "home", owner=owner, store=s)
        copy_of(led, ref_of(s, "copy"), src)                  # Ledger.record_copy: the source has no co-subject yet
        add_subject(led, src, "person:jenn")                  # recorded on the source after the copy
        assert led.cosubjects(ref_of(s, "copy")) == frozenset()          # the copy's own rows don't name her
        assert cosubjects_of(led, ref_of(s, "copy"), owner=owner) == frozenset(
            subjects_of(led.state(), ref_of(s, "copy"), NOW)) - {f"person:{owner}"} == {"person:jenn"}
        c, counts = ctx(s, ledger=led, owner=owner, home=home), Counter()
        got = sorted(base(s.conn, "episode", selection(), c, counts))
        if home:
            assert got == ["copy", "plain"] and counts["others_memories"] == 1
            assert list(cosubject_rows(Shipped(("copy", "plain"), ()), c)) == [("copy", "episode", "person:jenn")]
        else:
            assert got == ["plain"] and people(c.scratch, "needs_yes").named == (("person:jenn", 1),)
    s = new_store(tmp_path / "far", "s"); ep(s, "far")
    led = ledger(tmp_path / "far" / "home", owner="andy", store=s)
    chain = [ref_of(s, "far")] + [f"mem:{GENOME_ID}/episode/c{k}" for k in range(1, 6)]
    link_copies(led, chain); add_subject(led, chain[5], "person:kim")    # 5 links up: past MAX_COPY_CHAIN
    assert cosubjects_of(led, chain[0], owner="andy") == frozenset()

def test_what_the_permissions_spec_refuses_whole_stays_home(tmp_path):   # I 5.2 bound, retired; RM1, S1
    s = new_store(tmp_path, "s")
    for i in ("nine", "eight", "about-ava", "about-ava-home", "about-parks", "plain"): ep(s, i)
    led = ledger(tmp_path / "home", owner="andy", store=s,
                 cosubjects={"nine": "person:kim", "about-ava": "person:ava", "about-parks": "place:la-county/parks"})
    src = f"mem:{GENOME_ID}/episode/g1"
    copy_of(led, ref_of(s, "nine"), src); copy_of(led, ref_of(s, "eight"), src)
    for p in range(7): add_subject(led, src, f"person:p{p}")   # after both copies; never refused for them (P 7.4)
    retire(led, "person:ava")                                  # the owner is an admin (permission_ledger.py:204, :1076-1078)
    add_subject(led, ref_of(s, "about-ava-home"), "person:bo"); retire_place(led, "place:home/bo")
    retire_place(led, "place:la-county/parks")                 # a retired place co-subject keeps nothing home
    c, counts = ctx(s, ledger=led, owner="andy", home=True, now=NOW), Counter()
    assert sorted(base(s.conn, "episode", selection(), c, counts)) == ["about-parks", "eight", "plain"]
    assert counts["bound"] == 1 and counts["retired"] == 2      # nine: andy, kim and the source's 7 are 9 subjects
    assert people(c.scratch, "retired") == People(2, (("person:ava", 1), ("person:bo", 1)), 0)
    assert len(list(cosubject_rows(Shipped(("eight",), ()), c))) == 7

def test_source_owner_d37(tmp_path):
    s = new_store(tmp_path, "s"); home = tmp_path / "home"
    with pytest.raises(PlanRefused, match="not registered"):
        check_owner(ledger(home, owner="sam", store=None), iid(s), "sam")
    with pytest.raises(PlanRefused, match="person:jenn"):
        check_owner(ledger(tmp_path / "h2", owner="sam", store=s, store_owner="person:jenn"), iid(s), "sam")
    check_owner(None, iid(s), "sam")                     # no ledger: the owner's word stands

def test_refused_sources(tmp_path):
    home = tmp_path / "engram"
    for path, why in [(published_house_file(home), "published house"), (imprint_file(tmp_path), "imprint"),
                      (empty_old_store(tmp_path), "no identity"), (future_store(tmp_path), "newer than this code")]:
        with pytest.raises(PlanRefused, match=why):
            check_source(path, store_reader.connect(path, immutable=True), engram_home=home)

def test_rf4_store_paths_resolve_before_refusals(tmp_path):
    home = tmp_path / "engram"; pub = published_house_file(home)
    link = tmp_path / "link.db"; link.symlink_to(pub)
    dotted = home / ".engram" / "instances" / "x" / ".." / "lighthouse" / "graph.db"
    root = tmp_path / "imprints"; inside = root / "c0a8" / "imprint.db"; inside.parent.mkdir(parents=True)
    shutil.copyfile(new_store(tmp_path, "plain").db_path, inside)
    for path in (link, dotted, inside):
        with pytest.raises(PlanRefused):
            check_source(path, store_reader.connect(path, immutable=True), engram_home=home, imprint_roots=[root])
