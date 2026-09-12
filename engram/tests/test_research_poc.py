"""Real Engram mechanism tests; only the research boundary is controlled."""
import json
import shutil

import pytest

from research_poc.experiment import CONDITIONS, run_cell, save, read, cell_summary, pin_implementation


class Model:
    def __init__(self, publish=True, verdict="supported"):
        self.calls = []
        self.publish, self.verdict = publish, verdict

    def generate(self, question, document, context):
        self.calls.append(("generate", document["source"]["id"], context))
        return {"private_note": "PRIVATE-" + document["source"]["id"], "publish": self.publish,
                "extraction": {"analysis": {"relevant": True, "title": "Public finding",
                    "summary": "PUBLIC-" + document["source"]["id"], "scope": "This document",
                    "limitations": "Fixture only", "quote": "The measured state predicts fate",
                    "passage_id": "p1", "rationale": "Test"}, "model": "fixture",
                    "metrics": {"prompt_eval_count": 20, "eval_count": 10},
                    "context_manifest": {"selected_record_ids": [c["record"]["id"] for c in context]}}}

    def review(self, question, document, candidate):
        self.calls.append(("review", document["source"]["id"], []))
        return {"analysis": {"verdict": self.verdict, "reason": "Fixture review",
                            "evidence": [{"passage_id": "p1"}]},
                "metrics": {"prompt_eval_count": 30, "eval_count": 5},
                "context_manifest": {"selected_record_ids": []}}


@pytest.fixture
def inputs(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    return {"question": {"id": "q-fate", "title": "What predicts fate?"}, "seed_project": str(seed)}, [
        {"paper": {"id": f"paper{i}"}, "document": {"source": {"id": f"source{i}", "url": f"https://example.org/{i}"},
         "content_sha256": str(i) * 64, "coverage": "abstract_only",
         "passages": [{"id": "p1", "text": "The measured state predicts fate."}]}} for i in range(2)]


@pytest.fixture
def recorder():
    records = {}
    def record(project, **kwargs):
        key = (str(project), kwargs["idempotency_key"])
        records.setdefault(key, {"record_id": kwargs["idempotency_key"], "saved": True})
        assert "PRIVATE-" not in json.dumps(kwargs)
        return records[key]
    return record, records


def fork(seed, target):
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.mark.parametrize("condition", CONDITIONS)
def test_factorial_memory_exposure_and_completed_resume(tmp_path, inputs, recorder, condition):
    prepared, documents = inputs
    model, (record, records) = Model(), recorder
    result = run_cell(tmp_path / condition["id"], condition, prepared, documents, model,
                      rounds=2, record=record, fork=fork)
    generations = [c for c in model.calls if c[0] == "generate"]
    assert len(generations) == 4
    assert generations[0][2] == generations[1][2] == []
    for index, call in enumerate(generations[2:]):
        private = [c for c in call[2] if c["record"]["id"].startswith("private:")]
        shared = [c for c in call[2] if c["record"]["id"].startswith("shared:")]
        assert len(private) == int(condition["individual"])
        assert len(shared) == int(condition["shared"])
        if private:
            assert private[0]["record"]["summary"] == f"PRIVATE-source{index}"
        if shared:
            assert f"PUBLIC-source{1-index}" in json.dumps(shared)
            assert "PRIVATE-" not in json.dumps(shared)
    assert len(records) == (4 if condition["shared"] else 0)
    assert result["completed_turns"] == 4
    assert result["calls"] == 8
    again = run_cell(tmp_path / condition["id"], condition, prepared, documents, model,
                     rounds=2, record=record, fork=fork)
    assert len(model.calls) == 8
    assert again["calls"] == 8


@pytest.mark.parametrize("publish,verdict", [(False, "supported"), (True, "unsupported"), (True, "uncertain")])
def test_publication_requires_choice_and_supported_review(tmp_path, inputs, recorder, publish, verdict):
    prepared, docs = inputs
    record, records = recorder
    model = Model(publish, verdict)
    result = run_cell(tmp_path / "cell", CONDITIONS[-1], prepared, docs, model,
                      rounds=2, record=record, fork=fork)
    assert result["shares"] == 0
    assert records == {}
    assert all(not any(c["record"]["id"].startswith("shared:") for c in ctx)
               for stage, _, ctx in model.calls if stage == "generate")


def test_interrupted_publication_recovers_without_repeating_calls(tmp_path, inputs, recorder):
    prepared, docs = inputs
    real_record, records = recorder
    model = Model()
    def interrupted(*args, **kwargs):
        real_record(*args, **kwargs)
        raise RuntimeError("crash after journal saved")
    root = tmp_path / "cell"
    with pytest.raises(RuntimeError, match="crash"):
        run_cell(root, CONDITIONS[-1], prepared, docs, model, rounds=1, record=interrupted, fork=fork)
    result = run_cell(root, CONDITIONS[-1], prepared, docs, model, rounds=1, record=real_record, fork=fork)
    assert result["completed_turns"] == result["shares"] == len(records) == 2
    assert len(model.calls) == 4


def test_failed_call_is_audited_and_not_silently_retried(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    model = Model()
    def failure(*args):
        raise TimeoutError("unknown remote completion")
    model.generate = failure
    root = tmp_path / "cell"
    with pytest.raises(TimeoutError):
        run_cell(root, CONDITIONS[0], prepared, docs, model, rounds=1, record=record, fork=fork)
    with pytest.raises(RuntimeError, match="retry-interrupted"):
        run_cell(root, CONDITIONS[0], prepared, docs, Model(), rounds=1, record=record, fork=fork)
    result = run_cell(root, CONDITIONS[0], prepared, docs, Model(), rounds=1, record=record, fork=fork, retry_interrupted=True)
    assert result["calls"] == 5
    assert result["failed_or_interrupted_calls"] == 1


def test_communities_are_isolated(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    models = [Model(), Model()]
    for root, model in zip([tmp_path / "factorial", tmp_path / "community"], models):
        run_cell(root, CONDITIONS[-1], prepared, docs, model, rounds=1, record=record, fork=fork)
    assert all(ctx == [] for m in models for stage, _, ctx in m.calls if stage == "generate")


def test_refuses_changed_condition(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    root = tmp_path / "cell"
    run_cell(root, CONDITIONS[0], prepared, docs, Model(), rounds=1, record=record, fork=fork)
    with pytest.raises(ValueError, match="configuration"):
        run_cell(root, CONDITIONS[-1], prepared, docs, Model(), rounds=1, record=record, fork=fork)


def test_returned_result_repairs_interrupted_attempt_accounting(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    root, model = tmp_path / 'cell', Model()
    run_cell(root, CONDITIONS[0], prepared, docs, model, rounds=1, record=record, fork=fork)
    path = root / 'calls/r000-a0-extract/attempt-000.json'
    save(path, read(path) | {'status': 'started'})
    # Simulate a death before the final turn receipt, after the response reached disk.
    (root / 'turns/r000-a0.json').unlink()
    result = run_cell(root, CONDITIONS[0], prepared, docs, model, rounds=1, record=record, fork=fork)
    assert result['failed_or_interrupted_calls'] == 0
    assert len(model.calls) == 4


def test_rejected_response_metrics_count_and_unknown_usage_is_explicit(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    model = Model()
    class InvalidResponse(ValueError):
        result = {'metrics': {'prompt_eval_count': 101, 'eval_count': 51}}
    def failure(*args):
        raise InvalidResponse('bad quote')
    model.generate = failure
    root = tmp_path / 'cell'
    with pytest.raises(InvalidResponse):
        run_cell(root, CONDITIONS[0], prepared, docs, model, rounds=1, record=record, fork=fork)
    result = cell_summary(root)
    assert result['model_reported_prompt_tokens'] == 101
    assert result['model_reported_output_tokens'] == 51
    assert result['token_metrics_complete'] is True
    path = root / 'calls/r000-a0-extract/attempt-000.json'
    attempt = read(path)
    attempt.pop('returned_result')
    save(path, attempt)
    assert cell_summary(root)['token_metrics_complete'] is False


def test_code_changes_require_a_new_run(tmp_path):
    source, root = tmp_path / 'code', tmp_path / 'run'
    source.mkdir()
    (source / 'bridge.py').write_text('original prompt')
    pin_implementation(root, source)
    pin_implementation(root, source)
    (source / 'bridge.py').write_text('different prompt')
    with pytest.raises(ValueError, match='configuration'):
        pin_implementation(root, source)


def test_copying_and_extending_preserves_community_memory(tmp_path, inputs, recorder):
    prepared, docs = inputs
    record, _ = recorder
    original, moved = tmp_path / 'original', tmp_path / 'moved'
    run_cell(original, CONDITIONS[-1], prepared, docs, Model(), rounds=1, record=record, fork=fork)
    shutil.copytree(original, moved)
    model = Model()
    result = run_cell(moved, CONDITIONS[-1], prepared, docs, model, rounds=2, record=record, fork=fork)
    assert result['shares'] == 4
    generations = [c for c in model.calls if c[0] == 'generate']
    assert len(generations) == 2
    assert len(generations[0][2]) == len(generations[1][2]) == 2
