"""North-star test 5's Measure 2: a source notice reaches what the receiver built on the source, as a report that
changes nothing (spec: "Notices, and how they're applied", steps 1 to 6). Notices and their expected reports are in
tests/fixtures/claim_crossing/, made by make_fixtures.py before apply_notice existed."""
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ATLAS))
from tests.fixtures.claim_crossing import make_fixtures  # noqa: E402
from workbench import Store  # noqa: E402
from workbench.lighthouse_wire import digest, seal  # noqa: E402
from workbench.sourced import apply_notice, validate_notice  # noqa: E402

FIXTURES = Path(make_fixtures.__file__).resolve().parent


def load(name):
    return json.loads((FIXTURES / name).read_text())


def tardis_store(tmp_path):
    """Tardis's own Atlas store, holding the records of its publication."""
    model = load("tardis.json")["snapshot"]["payload"]["model"]
    store = Store(tmp_path / "tardis.db", create=True)
    store.import_bundle({"schema_version": 1, "title": model["title"],
                         "sources": [{k: v for k, v in s.items() if k != "keys"} for s in model["sources"]],
                         "items": model["items"], "relations": model["relations"]})
    return store


def held_publications():
    return [load(name) for name in ("tardis.json", "pi.json", "pi-corrected.json", "third.json")]


EXPECTED = load("notices-expected.json")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_notice_gives_its_expected_report(tmp_path, name):
    notices, expected = load("notices.json"), EXPECTED[name]
    report = apply_notice(notices[name], store=tardis_store(tmp_path), own=load("tardis.json"),
                          publications=held_publications(), corrections=[notices[h] for h in expected["holding"]])
    assert report["notice"] == notices[name]["digest"]
    for field in ("matched", "unclear", "through_chain", "impact", "corrected", "outcome"):
        assert report[field] == expected[field], (name, field)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_applying_a_notice_changes_nothing(tmp_path, name):
    store = tardis_store(tmp_path)
    before = store.export_bundle()
    notices = load("notices.json")
    apply_notice(notices[name], store=store, own=load("tardis.json"), publications=held_publications(),
                 corrections=[notices[h] for h in EXPECTED[name]["holding"]])
    assert store.export_bundle() == before


def test_without_the_correction_the_old_record_is_unclear_not_no_impact(tmp_path):
    # N5 matches t-copied-a-1, keyed by the old DOI, only through the held correction N4 (step 1). Without N4 the two
    # DOIs differ and the titles agree, so the comparison says "unclear" (rule 2): the report lists it, and its outcome
    # is "unclear", never "no impact" (amendment 4).
    notices = load("notices.json")
    report = apply_notice(notices["N5"], store=tardis_store(tmp_path), own=load("tardis.json"),
                          publications=held_publications(), corrections=[])
    corrected = load("pi-corrected.json")["snapshot"]["digest"]["value"]
    assert report["matched"] == [] and report["through_chain"] == [] and report["impact"] is None
    assert report["unclear"] == [{"source_id": "t-copied-a-1",
                                  "with": {"snapshot": corrected, "record_id": "pi-copied-a-1-v2"}}]
    assert report["outcome"] == "unclear"


def _reseal(notice):
    payload = notice["payload"]
    return seal("Claim", notice["issuer"], f"{notice['issuer']}:claim:{digest(payload)['value']}", notice["issuedAt"],
                payload)


def test_a_notice_whose_keys_dont_match_its_record_is_refused():
    notice = deepcopy(load("notices.json")["N2"])
    notice["payload"]["sentence"]["keys"]["doi"] = "doi:10.5555/superyak-fixture-copied-a"
    with pytest.raises(ValueError, match="keys"):
        validate_notice(_reseal(notice), held_publications())


def test_a_notice_naming_a_record_its_snapshot_lacks_is_refused():
    notice = deepcopy(load("notices.json")["N1"])
    notice["payload"]["sentence"]["record_id"] = "pi-no-such-source"
    with pytest.raises(ValueError, match="record"):
        validate_notice(_reseal(notice), held_publications())


def test_every_notice_is_valid():
    for notice in load("notices.json").values():
        validate_notice(notice, held_publications())


def _forged(sentence, snapshots):
    # sealed by the Pi with the right keys, naming a Snapshot the Pi didn't issue (the transport reviewer's R3)
    return make_fixtures.seal_notice(sentence, snapshots, make_fixtures.issuer("pi"), make_fixtures.context("pi"),
                                     make_fixtures.AT)


def _tardis_source(record_id):
    snapshot = load("tardis.json")["snapshot"]
    return snapshot, next(s for s in snapshot["payload"]["model"]["sources"] if s["id"] == record_id)


def test_a_notice_naming_a_snapshot_another_issuer_issued_is_refused():
    tardis, source = _tardis_source("t-copied-a-1")
    corrected = load("pi-corrected.json")["snapshot"]
    new = next(s for s in corrected["payload"]["model"]["sources"] if s["id"] == "pi-copied-a-1-v2")
    correction = _forged({"notice": "correction",
                          "old": {"snapshot": tardis["digest"], "record_id": source["id"], "keys": source["keys"]},
                          "new": {"snapshot": corrected["digest"], "record_id": new["id"], "keys": new["keys"]},
                          "reason": "A correction of another store's record."}, [tardis, corrected])
    retraction = _forged({"notice": "retraction", "record_id": source["id"], "keys": source["keys"],
                          "reason": "A retraction of another store's record."}, [tardis])
    for notice in (correction, retraction):
        with pytest.raises(ValueError, match="another issuer"):
            validate_notice(notice, held_publications())


def _publication(store, sources, items, **extra):
    bundle = {"schema_version": 1, "title": f"Small {store}", "sources": sources, "items": items, "relations": []}
    return make_fixtures.publish_sourced(bundle, {
        "issuer": make_fixtures.issuer(store), "name": f"Small {store}", "origin": f"urn:superyak:fixture:{store}:small",
        "context": make_fixtures.context(store), "item_ids": [i["id"] for i in items], "issued_at": make_fixtures.AT,
        **extra})


def _claim(record_id, source_id):
    return {"id": record_id, "kind": "claim", "title": f"Claim {record_id}", "summary": "", "status": "source_reported",
            "evidence": [{"source_id": source_id, "locator": "p1"}]}


def test_a_correction_whose_only_results_are_unclear_lists_each_pair_in_order(tmp_path):
    # amendment 4, both of its rules: t-x has a third DOI and the same title and year (rule 2); t-y is kept by an arXiv
    # url a year earlier (rule 4). Each is unclear against the old and the new record, so four entries, sorted.
    doi = "https://doi.org/10.5555/superyak-fixture-small-"
    one = {"id": "p-old", "title": "A small study", "url": doi + "old", "year": 2024, "citation": ""}
    two = {"id": "p-new", "title": "A small study", "url": doi + "new", "year": 2024, "citation": ""}
    pi_one, pi_two = _publication("pi", [one], [_claim("P1", "p-old")]), _publication("pi", [two], [_claim("P1", "p-new")])
    # the correction's old side gets the larger Snapshot digest, so gathering order (old, then new) differs from the
    # report's sorted order, and the sort is pinned
    (pi_old, old_source), (pi_new, new_source) = sorted([(pi_one, one), (pi_two, two)],
                                                        key=lambda p: p[0]["snapshot"]["digest"]["value"], reverse=True)
    tardis = _publication("tardis", [
        {"id": "t-x", "title": "A small study", "url": doi + "third", "year": 2024, "citation": ""},
        {"id": "t-y", "title": "A small study", "url": "https://arxiv.org/abs/2311.00001", "year": 2023, "citation": ""}],
        [_claim("T1", "t-x"), _claim("T2", "t-y")])
    model = tardis["snapshot"]["payload"]["model"]
    store = Store(tmp_path / "small.db", create=True)
    store.import_bundle({"schema_version": 1, "title": model["title"], "items": model["items"], "relations": [],
                         "sources": [{k: v for k, v in s.items() if k != "keys"} for s in model["sources"]]})

    def side(package, source):
        keys = next(s["keys"] for s in package["snapshot"]["payload"]["model"]["sources"] if s["id"] == source["id"])
        return {"snapshot": package["snapshot"]["digest"], "record_id": source["id"], "keys": keys}

    correction = make_fixtures.seal_notice({"notice": "correction", "old": side(pi_old, old_source),
                                            "new": side(pi_new, new_source), "reason": "A fictional DOI change."},
                                           [pi_old["snapshot"], pi_new["snapshot"]], make_fixtures.issuer("pi"),
                                           make_fixtures.context("pi"), make_fixtures.AT)
    report = apply_notice(correction, store=store, own=tardis, publications=[tardis, pi_old, pi_new])
    snapshots = sorted([pi_old["snapshot"]["digest"]["value"], pi_new["snapshot"]["digest"]["value"]])
    by_snapshot = {pi_old["snapshot"]["digest"]["value"]: old_source["id"], pi_new["snapshot"]["digest"]["value"]: new_source["id"]}
    assert report["unclear"] == [{"source_id": s, "with": {"snapshot": d, "record_id": by_snapshot[d]}}
                                 for s in ("t-x", "t-y") for d in snapshots]
    assert report["matched"] == [] and report["through_chain"] == [] and report["corrected"] == []
    assert report["impact"] is None and report["outcome"] == "unclear"
