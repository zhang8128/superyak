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
    for field in ("matched", "through_chain", "impact", "corrected", "outcome"):
        assert report[field] == expected[field], (name, field)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_applying_a_notice_changes_nothing(tmp_path, name):
    store = tardis_store(tmp_path)
    before = store.export_bundle()
    notices = load("notices.json")
    apply_notice(notices[name], store=store, own=load("tardis.json"), publications=held_publications(),
                 corrections=[notices[h] for h in EXPECTED[name]["holding"]])
    assert store.export_bundle() == before


def test_the_retraction_by_a_new_doi_misses_the_old_record_without_the_correction(tmp_path):
    # N5 reaches t-copied-a-1, keyed by the old DOI, only through the held correction N4 (step 1).
    notices = load("notices.json")
    report = apply_notice(notices["N5"], store=tardis_store(tmp_path), own=load("tardis.json"),
                          publications=held_publications(), corrections=[])
    assert report["matched"] == [] and report["outcome"] == "no impact"


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
