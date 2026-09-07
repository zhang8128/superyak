import json

import pytest

from scripts.context_retrieval_benchmark import load_fixture, run_benchmark


def test_fixed_fixture_has_disjoint_splits_and_source_grounded_expectations():
    fixture, digest = load_fixture()
    assert len(digest) == 64
    probes = fixture["probes"]
    assert len(probes) == 100
    assert len({p["id"] for p in probes}) == 100
    assert {p["split"] for p in probes} == {"development", "holdout"}
    for probe in probes:
        originals = {row["id"] for row in probe["sources"] + probe["recent"]}
        assert set(probe["expected_source_ids"]) <= originals
        assert set(probe["required_source_ids"]) <= originals


def test_benchmark_measures_sources_without_supplying_answers_to_selector(tmp_path):
    results = run_benchmark(noise_counts=(0,), split="development", probe_ids=("explicit_correction-01", "recent_reference-01", "unicode-01"), contexts_path=tmp_path / "contexts.jsonl")
    assert len(results["rows"]) == 3
    assert all(row["all_expected_sources_selected"] for row in results["rows"])
    assert all(row["required_constraints_present"] for row in results["rows"])
    assert all(row["foreign_source_count"] == 0 for row in results["rows"])
    contexts = [json.loads(line) for line in (tmp_path / "contexts.jsonl").read_text().splitlines()]
    fixture, _ = load_fixture()
    recent_ids = [r["id"] for p in fixture["probes"] if p["id"] == "recent_reference-01" for r in p["recent"]]
    assert len(contexts) == 3
    for context in contexts:
        serialized = json.dumps(context["payload"])
        assert "expected_source_ids" not in serialized
        assert "answer_terms" not in serialized
        # Temporary pronoun referents from another probe must never leak in.
        if context["probe_id"] != "recent_reference-01":
            assert all(source_id not in serialized for source_id in recent_ids)


def test_invalid_benchmark_configuration_fails_before_creating_outputs(tmp_path):
    destination = tmp_path / "contexts.jsonl"
    with pytest.raises(ValueError):
        run_benchmark(noise_counts=(-1,), contexts_path=destination)
    assert not destination.exists()
