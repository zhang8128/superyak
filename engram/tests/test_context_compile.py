import copy
import json

import pytest

from context_compile import Budget, Candidate, ContextCompiler, ContextCapacityError


class ByteCounter:
    model = "fixture"
    capabilities = {"strict": True, "count_kind": "provider", "budget_scope": "model_call", "billing": "test"}

    def count(self, payload):
        return len(json.dumps(payload, ensure_ascii=False).encode())


def test_whole_payload_is_counted_and_immutable():
    provider = ByteCounter()
    compiler = ContextCompiler(Budget(input_ceiling=2000, soft_target=1000, context_window=2400, output_reserve=300, margin=100))
    result = compiler.compile(instructions="Policy", current="Étoile", candidates=[], active_items=[], provider=provider)
    payload = result.payload
    assert payload["input"][-1] == {"role": "user", "content": "Étoile"}
    assert result.manifest["input_tokens"] == provider.count(payload)
    assert result.manifest["input_tokens"] + 400 <= 2400
    payload["instructions"] = "changed"
    assert result.payload["instructions"] == "Policy"
    assert result.payload["store"] is False
    assert result.payload["truncation"] == "disabled"


def test_required_overflow_never_drops_current_input_or_tool_items():
    compiler = ContextCompiler(Budget(input_ceiling=500, soft_target=400, context_window=700, output_reserve=100, margin=100))
    with pytest.raises(ContextCapacityError):
        compiler.compile(instructions="Policy", current="x" * 1000, candidates=[], active_items=[], provider=ByteCounter())
    with pytest.raises(ContextCapacityError):
        compiler.compile(instructions="Policy", current="hi", candidates=[], active_items=[{"type": "reasoning", "encrypted_content": "x" * 1000}], provider=ByteCounter())


def test_optional_context_eviction_preserves_provenance_and_required_notes():
    compiler = ContextCompiler(Budget(input_ceiling=1400, soft_target=900, context_window=1700, output_reserve=200, margin=100))
    candidates = [
        Candidate("correction", "user", ("The cow's name is Mira",), required=True, reason="explicit correction"),
        Candidate("old", "assistant", ("x" * 2000, "Old account of the cow"), score=1),
        Candidate("unrelated", "user", ("y" * 2000,), score=0.1),
    ]
    result = compiler.compile(instructions="Policy", current="name?", candidates=candidates, active_items=[], provider=ByteCounter())
    rendered = json.dumps(result.payload)
    assert "Mira" in rendered
    assert "unrelated" not in result.manifest["selected_ids"]
    assert result.manifest["input_tokens"] <= 1400
    assert all(item["role"] != "developer" for item in result.payload["input"] if "role" in item)
    assert "correction" in rendered


def test_dependencies_are_kept_together_and_cycles_rejected():
    compiler = ContextCompiler(Budget(input_ceiling=2000, soft_target=1900, context_window=2400, output_reserve=300, margin=100))
    candidates = [Candidate("claim", "user", ("derived fact",), score=10, dependencies=("source",)), Candidate("source", "user", ("source text",))]
    result = compiler.compile(instructions="Policy", current="hi", candidates=candidates, active_items=[], provider=ByteCounter())
    assert set(result.manifest["selected_ids"]) == {"claim", "source"}
    missing = [Candidate("claim", "user", ("derived fact",), dependencies=("absent",))]
    result = compiler.compile(instructions="Policy", current="hi", candidates=missing, active_items=[], provider=ByteCounter())
    assert result.manifest["selected_ids"] == []
    with pytest.raises(ValueError):
        compiler.compile(instructions="Policy", current="hi", candidates=[Candidate("a", "user", ("a",), dependencies=("a",))], active_items=[], provider=ByteCounter())


def test_active_provider_items_keep_order_and_pairs():
    active = [{"type": "reasoning", "id": "r", "encrypted_content": "opaque"}, {"type": "function_call", "name": "archive_search", "call_id": "c", "arguments": "{}"}, {"type": "function_call_output", "call_id": "c", "output": "[]"}]
    original = copy.deepcopy(active)
    compiler = ContextCompiler(Budget(input_ceiling=2500, soft_target=2000, context_window=3000, output_reserve=400, margin=100))
    result = compiler.compile(instructions="Policy", current="search", candidates=[], active_items=active, provider=ByteCounter())
    assert result.payload["input"][-3:] == original
    assert active == original
    with pytest.raises(ValueError):
        compiler.compile(instructions="Policy", current="search", candidates=[], active_items=active[:2], provider=ByteCounter())


def test_estimator_cannot_claim_strict_mode():
    provider = ByteCounter()
    provider.capabilities = {**provider.capabilities, "strict": False, "count_kind": "estimate", "budget_scope": "episode"}
    compiler = ContextCompiler(Budget(require_strict=True))
    with pytest.raises(ContextCapacityError):
        compiler.compile(instructions="Policy", current="hi", candidates=[], active_items=[], provider=provider)


def test_ten_thousand_calls_hold_budget_and_candidate_bound():
    compiler = ContextCompiler(Budget(input_ceiling=1200, soft_target=800, context_window=1500, output_reserve=200, margin=100, max_candidates=8))
    for i in range(10_000):
        candidates = [Candidate(f"{i}-{j}", "user", ("a memory λ " * (j + 1),), score=j) for j in range(12)]
        result = compiler.compile(instructions="Policy", current=f"turn {i}", candidates=candidates, active_items=[], provider=ByteCounter())
        assert result.manifest["input_tokens"] + 300 <= 1500
        assert len(result.manifest["selected_ids"]) <= 8
