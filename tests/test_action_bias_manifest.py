import json
from pathlib import Path

import pytest

from experiments.action_bias.manifest import (
    build_run_matrix,
    load_manifest,
    manifest_hash,
    validate_manifest,
)


def write_manifest(tmp_path: Path, **overrides) -> Path:
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    data = {
        "schema_version": 1,
        "experiment_id": "pilot-test",
        "stage": "pilot",
        "random_seed": 17,
        "repeat_count": 1,
        "fallback_tokenizer": "whitespace-v1",
        "conditions": {
            "off_device": "",
            "placebo": "alpha beta gamma delta",
            "existing_instinct": "one two three four",
            "counterfactual_seed": "red blue green gold",
        },
        "harnesses": {
            "claude": {"binary": "claude", "model": "claude-fable-5", "timeout_seconds": 120},
            "codex": {"binary": "codex", "model": "gpt-5.6-sol", "timeout_seconds": 120},
        },
        "grader": {"binary": "claude", "model": "claude-fable-5", "timeout_seconds": 120},
        "scenarios": [{"id": "s1", "fixture": str(fixture), "prompt": "Explore this. Do not edit."}],
    }
    data.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_manifest_builds_deterministic_full_matrix(tmp_path):
    path = write_manifest(tmp_path)
    manifest = load_manifest(path)
    assert validate_manifest(manifest, tmp_path) == []
    first = build_run_matrix(manifest)
    second = build_run_matrix(manifest)
    assert first == second
    assert len(first) == 8
    assert {r.condition_id for r in first} == {
        "off_device", "placebo", "existing_instinct", "counterfactual_seed"
    }
    assert {r.harness_id for r in first} == {"claude", "codex"}


def test_manifest_hash_changes_with_content(tmp_path):
    path = write_manifest(tmp_path)
    before = manifest_hash(path)
    data = json.loads(path.read_text())
    data["random_seed"] = 18
    path.write_text(json.dumps(data))
    assert manifest_hash(path) != before


def test_validation_rejects_length_band_and_missing_fixture(tmp_path):
    path = write_manifest(tmp_path)
    data = json.loads(path.read_text())
    data["conditions"]["counterfactual_seed"] = "one two three four five six seven eight"
    data["scenarios"][0]["fixture"] = str(tmp_path / "missing")
    path.write_text(json.dumps(data))
    errors = validate_manifest(load_manifest(path), tmp_path)
    assert any("15%" in e for e in errors)
    assert any("fixture" in e for e in errors)


def test_load_rejects_unknown_condition(tmp_path):
    path = write_manifest(tmp_path)
    data = json.loads(path.read_text())
    data["conditions"]["full_orientation"] = "not allowed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="conditions"):
        load_manifest(path)
