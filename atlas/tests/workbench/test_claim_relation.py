"""North-star test 5, Tardis's half (T1): the receiver's rule `relation(a, b, held)` on the planted stores. The spec is
docs/superpowers/specs/2026-11-22-claim-crossing-design.md, revision 6 (84fafe71) with amendment 1, "The answers, in
order". The stores and expected.json were fixed in their commit (f51cdebd) before this rule existed. Measure 1: every
pair gets its expected answer and linking digest."""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ATLAS))
from tests.fixtures.claim_crossing import make_fixtures  # noqa: E402
from workbench.sourced import validate_sourced  # noqa: E402
from workbench.sourced_relation import held_claims, relation  # noqa: E402

FIXTURES = Path(make_fixtures.__file__).resolve().parent
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())
PUBLICATIONS = {store: validate_sourced(json.loads((FIXTURES / f"{store}.json").read_text()))
                for store in make_fixtures.STORES}
HELD = held_claims(PUBLICATIONS.values())


def digest_of(ref):
    """The Claim digest an expected.json reference names: a store's own record, a carried copy of another's, or a
    planted unresolved tag."""
    if "unresolved" in ref:
        return EXPECTED["unresolved"][ref["unresolved"]]
    package = PUBLICATIONS[ref["store"]]
    if "carried" in ref:
        [claim] = [e["claim"] for e in package["carried"]
                   if e["claim"]["payload"]["sentence"]["record_id"] == ref["carried"]]
    else:
        [claim] = [c for c in package["claims"] if c["payload"]["sentence"]["record_id"] == ref["record_id"]]
    return claim["digest"]


PAIRS = EXPECTED["pairs"]
IDS = [f'{p["case"]}: {p["a"].get("record_id")} / {p["b"].get("record_id", p["b"].get("carried"))}' for p in PAIRS]


@pytest.mark.parametrize("pair", PAIRS, ids=IDS)
def test_every_planted_pair_gets_its_expected_answer_and_link(pair):
    got = relation(digest_of(pair["a"]), digest_of(pair["b"]), HELD)
    assert got["answer"] == pair["answer"]
    if "link" in pair:
        assert got["link"] == digest_of(pair["link"])
    else:
        assert got["link"] is None


@pytest.mark.parametrize("pair", PAIRS, ids=IDS)
def test_the_answer_doesnt_depend_on_which_claim_is_a(pair):
    a, b = digest_of(pair["a"]), digest_of(pair["b"])
    assert relation(b, a, HELD) == relation(a, b, HELD)


REASONS = {"both empty": "no roots", "one empty": "no roots", "unresolved digest": "unresolved digest"}


@pytest.mark.parametrize("pair", [p for p in PAIRS if p["answer"] == "unknown"],
                         ids=[i for i, p in zip(IDS, PAIRS) if p["answer"] == "unknown"])
def test_every_unknown_says_why(pair):
    got = relation(digest_of(pair["a"]), digest_of(pair["b"]), HELD)
    assert got["reason"] == REASONS.get(pair["case"], "unclear sources")


def test_only_unknown_carries_a_reason_and_every_answer_is_counted_as_planted():
    got = [relation(digest_of(p["a"]), digest_of(p["b"]), HELD) for p in PAIRS]
    assert all((g["reason"] is None) == (g["answer"] != "unknown") for g in got)
    assert Counter(g["answer"] for g in got) == Counter(p["answer"] for p in PAIRS)


def test_a_claim_the_receiver_doesnt_hold_is_refused():
    with pytest.raises(KeyError):
        relation(EXPECTED["unresolved"]["lone-a"], digest_of(PAIRS[0]["a"]), HELD)


# ---- what the planted stores don't pin: three mutants survived them, so each case is built here by hand ------------

from workbench.sourced import source_key  # noqa: E402


def _source(source_id, url, title, year=2024, citation=""):
    record = {"id": source_id, "title": title, "url": url, "year": year, "citation": citation}
    return {**record, "keys": source_key(record)}


def _held(*claims):
    """A receiver's held claims from hand-made parts: each (digest, record id, cited source ids, sources, provenance
    digests). Only the fields relation reads are present."""
    held = {}
    for value, record_id, cited, sources, provenance in claims:
        snapshot = {"digest": {"value": "s-" + value}, "payload": {"model": {
            "items": [{"id": record_id, "evidence": [{"source_id": s} for s in cited]}], "sources": sources}}}
        claim = {"digest": {"value": value}, "payload": {"sentence": {"record_id": record_id},
                                                       "provenance": [{"algorithm": "sha-256", "value": p}
                                                                      for p in provenance]}}
        held[value] = (claim, snapshot)
    return held


def ref(value):
    return {"algorithm": "sha-256", "value": value}


def test_a_strict_subset_of_sources_is_overlapping_not_same_sources():
    one, two = _source("s1", "https://a.example/1", "First"), _source("s2", "https://a.example/2", "Second")
    held = _held(("A", "rA", ["s1"], [one], []), ("B", "rB", ["s1", "s2"], [one, two], []))
    assert relation(ref("A"), ref("B"), held)["answer"] == "overlapping"
    assert relation(ref("B"), ref("A"), held)["answer"] == "overlapping"


def test_sibling_copies_name_the_nearest_shared_digest():
    src = _source("s1", "https://a.example/1", "First")
    held = _held(("A", "rA", ["s1"], [src], ["N"]), ("B", "rB", ["s1"], [src], ["N"]),
                 ("N", "rN", ["s1"], [src], ["F"]), ("F", "rF", ["s1"], [src], []))
    assert relation(ref("A"), ref("B"), held) == {"answer": "copied", "link": ref("N"), "reason": None}


def test_roots_follow_a_copy_when_the_copy_cites_nothing_itself():
    src = _source("s1", "https://a.example/1", "First")
    held = _held(("X", "rX", ["s1"], [src], []), ("A", "rA", [], [], ["X"]),
                 ("B", "rB", ["t1"], [_source("t1", "http://www.a.example/1/", "First")], []))
    assert relation(ref("A"), ref("B"), held) == {"answer": "same sources", "link": None, "reason": None}
