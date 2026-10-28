"""Task 30: F1, the conformance fixtures (P 15, 17).

Each file in tests/fixtures/permissions/f1 is one ledger state (the P 5.5 tables, `seq`, `seq_at`, `meta`, `names`)
and cases: a use or a bulk use (each carrying its copy h), the legacy layers the case runs with, and the decision any
conforming implementation must give (`allowed`, `cited`, `refusal`, `until`, `horizon`). The expected values were
written by hand from P 5 and 6; this runner only compares them with what `decide` and `decide_bulk` return.
Times are UTC seconds."""
import json
from pathlib import Path

import pytest

from permissions import BulkUse, LegacyLayer, State, Use, decide, decide_bulk

FIXTURES = sorted((Path(__file__).parent / "fixtures" / "permissions" / "f1").glob("*.json"))


def load_state(doc) -> State:
    return State.from_tables(doc["tables"], seq=doc["seq"], seq_at={int(k): v for k, v in doc["seq_at"].items()},
                             meta=doc["meta"], names=doc.get("names", {}))


def legacy_layers(case) -> list:
    return [LegacyLayer(layer["name"], lambda u, x, ok=frozenset(layer["allows"]): x in ok)
            for layer in case.get("legacy", ())]


def run_case(state: State, case):
    """Decide the case's use, or its bulk use, with the legacy layers the case names."""
    legacy = legacy_layers(case)
    if "use" in case:
        u = dict(case["use"])
        u["names"] = tuple(u.get("names", ()))
        u["shows"] = frozenset(u.get("shows", ()))
        return decide(state, Use(**u), legacy=legacy)
    b = dict(case["bulk"])
    names = b.pop("names", {})
    b["objects"] = tuple(b["objects"])
    return decide_bulk(state, BulkUse(**b, names=lambda o: names.get(o, ())), legacy=legacy)


def kind_of(case) -> str:
    if "bulk" in case:
        if case["bulk"]["copy"].startswith("imprint:"):
            return "imprint-evaluation"
        return "bulk-named" if case["bulk"]["named"] else "bulk-counted"
    obj = case["use"]["obj"]
    return obj.split(":", 1)[0] if obj.startswith(("road:", "trail:")) else "single"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_f1_fixture(path):
    doc = json.loads(path.read_text())
    s = load_state(doc)
    assert doc["cases"], path.stem
    for case in doc["cases"]:
        got = run_case(s, case)
        assert {k: got.to_json()[k] for k in case["expected"]} == case["expected"], (path.stem, case.get("note"))


def all_cases():
    return [c for p in FIXTURES for c in json.loads(p.read_text())["cases"]]


def test_f1_has_every_kind_of_case():
    assert {kind_of(c) for c in all_cases()} >= {
        "single", "road", "trail", "bulk-named", "bulk-counted", "imprint-evaluation"}
    assert all("copy" in (c.get("use") or c["bulk"]) for c in all_cases())


def test_f1_has_every_refusal_code_and_the_expected_keys():
    codes = {c["expected"]["refusal"]["code"] for c in all_cases() if c["expected"]["refusal"]}
    assert codes >= {"UNKNOWN_REQUESTER", "RETIRED", "NO_LAYER", "BOUND", "DENIED", "EXPIRED", "GRANT_INVALID",
                     "NOT_YET", "NO_ALLOW", "LEGACY_DENY"}
    assert all(set(c["expected"]) == {"allowed", "cited", "refusal", "until", "horizon"} for c in all_cases())
