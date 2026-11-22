"""North-star test 5, Measure 3, stage 1 (engram/experiments/northstar/PREREG-test5-measure3.md, approved at 64f8a41c):
REL's answer for every T1 × P1 claim pair, and each record's sources with their keys, written for stage 2 in engram.
Atlas has no numpy and engram's tests mustn't import `workbench`, so the work is split at this file."""
import json
import sys
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ATLAS))
from tests.fixtures.claim_crossing import make_fixtures  # noqa: E402
from workbench.measure3_answers import answers  # noqa: E402
from workbench.sourced import publish_sourced  # noqa: E402

FIXTURES = Path(make_fixtures.__file__).resolve().parent


def load(store):
    return json.loads((FIXTURES / f"{store}.json").read_text())


def test_every_cross_pair_of_the_first_publications_gets_one_rel_answer():
    pi, tardis = load("pi"), load("tardis")
    out = answers(tardis, pi)
    t_ids = sorted(c["payload"]["sentence"]["record_id"] for c in tardis["claims"])
    p_ids = sorted(c["payload"]["sentence"]["record_id"] for c in pi["claims"])
    assert [(r["t"], r["p"]) for r in out["pairs"]] == [(t, p) for t in t_ids for p in p_ids]
    assert {r["rel"] for r in out["pairs"]} <= {"copied", "unknown", "same sources", "overlapping", "independent"}
    assert all((r["reason"] is None) == (r["rel"] != "unknown") for r in out["pairs"])


def test_each_record_lists_its_sources_with_keys_and_strong_url():
    pi, tardis = load("pi"), load("tardis")
    out = answers(tardis, pi)
    for side, package in (("T", tardis), ("P", pi)):
        sources = {s["id"]: s for s in package["snapshot"]["payload"]["model"]["sources"]}
        for item in package["snapshot"]["payload"]["model"]["items"]:
            listed = out["records"][side][item["id"]]
            assert [s["id"] for s in listed] == [e["source_id"] for e in item.get("evidence", [])]
            for s in listed:
                assert s["keys"] == sources[s["id"]]["keys"]
                assert s["strong_url"] in (True, False)


def test_the_answers_match_the_planted_expected_pairs():
    """Every planted pi × tardis pair in expected.json is a cross pair here, with the same answer (Measure 1's)."""
    pi, tardis = load("pi"), load("tardis")
    by_pair = {(r["t"], r["p"]): r["rel"] for r in answers(tardis, pi)["pairs"]}
    expected = json.loads((FIXTURES / "expected.json").read_text())["pairs"]
    checked = 0
    for pair in expected:
        a, b = pair["a"], pair["b"]
        if a.get("store") == "pi" and b.get("store") == "tardis" and "record_id" in a and "record_id" in b:
            assert by_pair[(b["record_id"], a["record_id"])] == pair["answer"], pair["case"]
            checked += 1
    assert checked >= 30


def _publication(issuer, sources, items):
    bundle = {"schema_version": 1, "title": issuer, "sources": sources, "items": items, "relations": []}
    return publish_sourced(bundle, {
        "issuer": issuer, "name": issuer, "origin": f"{issuer}:collection",
        "context": {"id": f"{issuer}:context", "path": ["research"]}, "item_ids": [i["id"] for i in items],
        "issued_at": "2026-11-22T18:00:00Z", "rules": [], "copied_from": {}, "carried": []})


def test_recovery_preprint_against_its_journal_version_is_independent_under_rel():
    """The pre-registration's named case, run at the pinned code (its checklist line, and the reviewer's V2): the
    medRxiv preprint and the NEJM version have two DOIs and different titles, so rule 1 decides them distinct, and REL
    answers independent. That's a dangerous error, which the page counts rather than tunes away."""
    preprint = {"id": "t-recovery", "title": "Effect of Hydroxychloroquine in Hospitalized Patients with COVID-19: "
                "Preliminary results from a multi-centre, randomized, controlled trial", "year": 2020,
                "url": "https://www.medrxiv.org/content/10.1101/2020.07.15.20151852v1",
                "citation": "doi:10.1101/2020.07.15.20151852"}
    journal = {"id": "p-recovery", "title": "Effect of Hydroxychloroquine in Hospitalized Patients with Covid-19",
               "year": 2020, "url": "https://doi.org/10.1056/NEJMoa2022926", "citation": "doi:10.1056/NEJMoa2022926"}

    def claim(rid, sid):
        return {"id": rid, "kind": "claim", "title": f"RECOVERY mortality ({rid})", "summary": "A real finding.",
                "status": "source_reported", "evidence": [{"source_id": sid, "locator": "abstract"}]}
    t = _publication("urn:superyak:peer:" + "a" * 64, [preprint], [claim("T-rec", "t-recovery")])
    p = _publication("urn:superyak:peer:" + "b" * 64, [journal], [claim("P-rec", "p-recovery")])
    [pair] = answers(t, p)["pairs"]
    assert pair["rel"] == "independent"


def test_a_package_that_fails_validation_is_refused():
    pi, tardis = load("pi"), load("tardis")
    tardis["snapshot"]["payload"]["model"]["title"] = "edited"
    with pytest.raises(Exception):
        answers(tardis, pi)


# --- freeze_check(): the builder rules, checked at the freeze (W5, VA10) ---------------------------------------------

from workbench.measure3_answers import freeze_check  # noqa: E402


def collection(n_sources=15, n_items=10, **change):
    sources = [{"id": f"s{i}", "title": f"Paper {i}", "year": 2021, "url": f"https://doi.org/10.5555/p{i}",
                "citation": f"doi:10.5555/p{i}"} for i in range(n_sources)]
    items = [{"id": f"r{i}", "kind": "claim", "title": f"Record {i}", "summary": "x", "status": "source_reported",
              "evidence": [{"source_id": f"s{i % n_sources}", "locator": "p1"}]} for i in range(n_items)]
    for key, value in change.items():
        sid, field = key.split("__")
        next(s for s in sources if s["id"] == sid)[field] = value
    return {"schema_version": 1, "title": "T", "sources": sources, "items": items, "relations": []}


def registry(sources):
    """A fake Crossref/PubMed lookup: each source's record, keyed by its id."""
    return {s["id"]: {"doi": s["citation"][4:], "title": s["title"], "year": s["year"]} for s in sources}


def check(bundle, records=None):
    records = registry(collection()["sources"]) if records is None else records
    return freeze_check(bundle, lambda source: records.get(source["id"]))


def test_a_collection_that_matches_its_records_passes():
    assert check(collection()) == {"deviations": [], "without_record": []}


def test_sizes_and_evidence_are_refused_outside_the_ranges():
    assert any("sources" in d for d in check(collection(n_sources=14), registry(collection(n_sources=14)["sources"]))["deviations"])
    assert any("records" in d for d in check(collection(n_items=26))["deviations"])
    bundle = collection()
    bundle["items"][0]["evidence"] = []
    assert any("cites no source" in d for d in check(bundle)["deviations"])


def test_a_title_year_or_doi_that_differs_from_the_record_is_a_deviation():
    got = check(collection(s0__title="My own title", s1__year=2020, s2__citation="see the journal"))["deviations"]
    assert any("s0" in d and "title" in d for d in got)
    assert any("s1" in d and "year" in d for d in got)
    assert any("s2" in d and "DOI" in d for d in got)


def test_the_doi_key_must_be_the_items_own():
    """W5: a doi.org url to another version gives a DOI key that isn't the item's own DOI."""
    got = check(collection(s3__url="https://doi.org/10.1101/2020.07.15.20151852"))["deviations"]
    assert any("s3" in d and "DOI key" in d for d in got)


def test_an_item_with_no_record_keeps_its_fields_and_is_listed():
    records = registry(collection()["sources"])
    del records["s4"]
    assert check(collection(), records) == {"deviations": [], "without_record": ["s4"]}
