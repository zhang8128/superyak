import json

import pytest

from scripts.context_continuity_pilot import FIXTURE, _compact_prefix, admit, answer_checks, report, run_cells, validate_summary


def test_keyword_presence_does_not_become_a_correctness_verdict():
    payload = {"input": [{"content": "Mira says amber; Robin says black. Source ev-0123456789abcdef01234567"}]}
    raw = json.dumps({"answer": "Mira says black; Robin says amber.", "source_ids": ["ev-0123456789abcdef01234567"]})
    checks = answer_checks(raw, payload, ["ev-0123456789abcdef01234567"])
    assert checks["expected_sources_cited"]
    assert checks["human_correctness"] is None
    assert "correct" not in checks
    assert answer_checks(json.dumps({"answer": "amber", "source_ids": ["invented"]}), payload, [])["unavailable_citations"] == ["invented"]


def test_capacity_and_summary_provenance_fail_explicitly():
    with pytest.raises(ValueError, match="ceiling"):
        admit({"input": "λ" * 20_000})
    with pytest.raises(ValueError, match="source"):
        validate_summary([{ "text": "some fact", "source_ids": ["invented"]}], {"original"})
    with pytest.raises(ValueError, match="cap"):
        validate_summary([{ "text": "x" * 7000, "source_ids": ["original"]}], {"original"})


def test_dispatches_are_durable_and_resume_never_repeats_an_uncertain_call(tmp_path):
    class Provider:
        def generate(self, payload):
            raise RuntimeError("interrupted transport")
        def close(self):
            pass

    cells = [{"cell_id": "one", "probe_id": "probe", "arm": "dynamic", "payload": {"input": []}, "expected_source_ids": []}]
    run_cells(cells, tmp_path, provider_factory=Provider, workers=1)
    assert len((tmp_path / "dispatches.jsonl").read_text().splitlines()) == 1
    # Simulate losing the response journal after the provider was dispatched.
    (tmp_path / "answers.jsonl").unlink()
    run_cells(cells, tmp_path, provider_factory=lambda: pytest.fail("must not replay"), workers=1)
    assert not (tmp_path / "answers.jsonl").exists()


def test_changed_request_cannot_reuse_a_dispatched_cell(tmp_path):
    (tmp_path / "dispatches.jsonl").write_text(json.dumps({"cell_id": "one", "request_digest": "old"}) + "\n")
    cells = [{"cell_id": "one", "probe_id": "probe", "arm": "dynamic", "payload": {"input": []}, "expected_source_ids": []}]
    with pytest.raises(ValueError, match="changed"):
        run_cells(cells, tmp_path, provider_factory=lambda: None, workers=1)


def test_capacity_failure_is_recorded_without_dispatch_and_not_retried(tmp_path):
    cells = [{"cell_id": "large", "probe_id": "probe", "arm": "baseline", "payload": {"input": "x" * 20_000}, "expected_source_ids": []}]
    for _ in range(2):
        run_cells(cells, tmp_path, provider_factory=lambda: pytest.fail("must reject before provider"), workers=1)
    assert not (tmp_path / "dispatches.jsonl").exists()
    records = (tmp_path / "answers.jsonl").read_text().splitlines()
    assert len(records) == 1
    assert "ceiling" in json.loads(records[0])["error"]["message"]


def test_duplicate_cells_cannot_dispatch_twice(tmp_path):
    cell = {"cell_id": "one", "probe_id": "probe", "arm": "baseline", "payload": {"input": []}, "expected_source_ids": []}
    with pytest.raises(ValueError, match="Duplicate"):
        run_cells([cell, cell], tmp_path, provider_factory=lambda: pytest.fail("must not dispatch"))


def test_compaction_resumes_verified_outputs_without_repeating_model_calls(tmp_path):
    calls = []
    class Compactor:
        def generate(self, payload):
            calls.append(payload)
            chunk = json.loads(payload["input"][0]["content"])["append"]
            raw = json.dumps({"summary": [{"text": "A retained fact", "source_ids": [chunk[0]["id"]]}]})
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": raw}]}]}
        def close(self):
            pass

    transcript = [{"id": f"ev-{i:024x}", "role": "user", "content": "detail " * 100} for i in range(40)]
    summary = _compact_prefix(transcript, tmp_path, provider_factory=Compactor)
    assert len(calls) >= 2
    assert _compact_prefix(transcript, tmp_path, provider_factory=lambda: pytest.fail("must use recorded outputs")) == summary


@pytest.mark.parametrize("raw", ["[]", "null", "not JSON", '{"summary":[{"text":"incorrect","source_ids":["invented"]}]}'])
def test_failed_compaction_retains_raw_output_and_raises_a_consistent_error(tmp_path, raw):
    class InvalidCompactor:
        def generate(self, payload):
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": raw}]}], "usage": {"input_tokens": 42}}
        def close(self):
            pass

    with pytest.raises(ValueError):
        _compact_prefix([{"id": "ev-0123456789abcdef01234567", "role": "user", "content": "A fact"}], tmp_path, provider_factory=InvalidCompactor)
    failure = json.loads((tmp_path / "compactions.jsonl").read_text())
    assert failure["raw_answer"] == raw
    assert failure["response"]["usage"]["input_tokens"] == 42


def test_report_rejects_changed_frozen_ground_truth(tmp_path):
    (tmp_path / "cells.json").write_text("[]")
    (tmp_path / "fixture.json").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "configuration.json").write_text('{"fixture_sha256":"different"}')
    with pytest.raises(ValueError, match="fingerprint"):
        report(tmp_path)
