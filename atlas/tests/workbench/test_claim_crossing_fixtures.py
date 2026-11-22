"""North-star test 5's planted stores are frozen: the committed files are exactly what the generator makes, every
publication is valid, every pair names records that exist, and the policies answer as expected.json says."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ATLAS))
from tests.fixtures.claim_crossing import make_fixtures  # noqa: E402
from workbench.lighthouse_wire import authorize  # noqa: E402
from workbench.sourced import validate_sourced  # noqa: E402

FIXTURES = Path(make_fixtures.__file__).resolve().parent
FILES = [f"{store}.json" for store in make_fixtures.STORES] + ["expected.json"]
ANSWERS = {"copied", "unknown", "same sources", "overlapping", "independent"}


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_the_committed_files_are_exactly_what_the_generator_makes(tmp_path):
    make_fixtures.write(tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (FIXTURES / name).read_bytes(), name


@pytest.mark.parametrize("store", make_fixtures.STORES)
def test_every_publication_is_valid(store):
    validate_sourced(load(f"{store}.json"))


def records(store):
    return {c["payload"]["sentence"]["record_id"]: c for c in load(f"{store}.json")["claims"]}


def test_every_pair_names_records_that_exist_and_an_answer_of_the_spec():
    expected = load("expected.json")
    held = {store: records(store) for store in make_fixtures.STORES}
    carried = {e["claim"]["payload"]["sentence"]["record_id"] for e in load("tardis.json")["carried"]}
    for pair in expected["pairs"]:
        assert pair["answer"] in ANSWERS, pair
        assert pair["a"]["record_id"] in held[pair["a"]["store"]], pair
        if "carried" in pair["b"]:
            assert pair["b"]["carried"] in carried, pair
        else:
            assert pair["b"]["record_id"] in held[pair["b"]["store"]], pair
        link = pair.get("link")
        if link and "unresolved" in link:
            assert link["unresolved"] in expected["unresolved"], pair
        elif link:
            assert link["record_id"] in held[link["store"]], pair
        assert (pair["answer"] == "copied") == (link is not None), pair  # only a copy names its link


def test_every_case_has_at_least_two_pairs_and_every_answer_is_planted():
    pairs = load("expected.json")["pairs"]
    assert all(n >= 2 for n in Counter(p["case"] for p in pairs).values())
    assert {p["answer"] for p in pairs} == ANSWERS


def test_an_unresolved_digest_resolves_to_nothing_published():
    expected = load("expected.json")
    published = {c["digest"]["value"] for s in make_fixtures.STORES for c in load(f"{s}.json")["claims"]}
    assert all(d["value"] not in published for d in expected["unresolved"].values())


def test_the_policies_answer_as_expected():
    for case in load("expected.json")["authorization"]:
        policy = load(f"{case['policy_of']}.json")["policy"]
        assert authorize(policy, case["request"])["allowed"] is case["allowed"], case


def test_every_doi_is_a_synthetic_fixture_doi():
    """Nothing planted names a real DOI: every 10.<registrant>/ in a url or a citation is 10.5555/superyak-fixture-,
    in any case, and the one bare prefix (https://doi.org/10.5555) has no suffix at all."""
    for store in make_fixtures.STORES:
        for source in load(f"{store}.json")["snapshot"]["payload"]["model"]["sources"]:
            if source["keys"]["doi"]:
                assert source["keys"]["doi"].startswith("doi:10.5555/superyak-fixture-"), source
            for text in (source["url"], source["citation"]):
                for found in re.finditer(r"10\.\d{4,9}/\S*", text):
                    assert found.group(0).lower().startswith("10.5555/superyak-fixture-"), source
