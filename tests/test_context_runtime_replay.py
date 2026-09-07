import copy

import pytest

from context_compile import Budget
from scripts.context_runtime_replay import (
    ExactPayloadMismatch,
    ReplayConfig,
    SyntheticReplayProvider,
    run_replay,
)


def test_short_replay_measures_real_runtime_calls_and_bounded_archive_growth(tmp_path):
    report = run_replay(
        ReplayConfig(
            model_calls=6,
            warmup_calls=2,
            archive_path=tmp_path / "replay.db",
            artifact_bytes=32_768,
            max_retained_growth_bytes=8_000_000,
        )
    )

    assert report["result"] == {"ok": True, "kind": "synthetic_mechanical_acceptance"}
    assert report["calls"] == {
        "requested_generation_calls": 6,
        "actual_generation_calls": 6,
        "count_operations": 6,
        "counted_payload_dispatch_matches": 6,
        "tool_calls": 3,
        "tool_continuations": 3,
        "completed_turns": 3,
    }
    assert report["budget"]["all_generation_calls_compliant"] is True
    assert report["budget"]["max_input_count"] <= report["budget"]["input_ceiling"]
    assert (
        report["budget"]["max_input_count"]
        + report["budget"]["output_reserve"]
        + report["budget"]["margin"]
        <= report["budget"]["context_window"]
    )
    assert report["candidates"]["all_manifests_within_bound"] is True
    assert report["candidates"]["max_observed"] <= report["candidates"]["bound"]
    assert report["candidates"]["archive_search_deadline_ms"] == 50
    assert report["candidates"]["archive_retrieval_incomplete_manifests"] == 0
    assert report["tools"]["call_output_pair_checks"] == 3
    assert report["tools"]["max_decoded_page_bytes"] == 4096
    assert report["tools"]["large_artifact_bytes"] == 32_768
    assert report["archive"]["events_after_warmup"] > report["archive"]["events_at_start"]
    assert report["archive"]["events_at_end"] > report["archive"]["events_after_warmup"]
    assert report["usage"]["responses_with_usage"] == 6
    assert report["allocations"]["method"] == (
        "tracemalloc.get_traced_memory after gc.collect; Python-traced allocation bytes only, "
        "not process RSS or SQLite native allocations"
    )
    assert report["allocations"]["retained_growth_within_bound"] is True


def test_synthetic_provider_rejects_dispatch_that_differs_from_counted_payload():
    budget = Budget(
        input_ceiling=131_072,
        soft_target=65_536,
        context_window=262_144,
        output_reserve=4096,
        margin=1024,
        max_candidates=32,
        require_strict=True,
    )
    provider = SyntheticReplayProvider("a" * 64, 32_768, budget)
    payload = {
        "model": provider.model,
        "instructions": "synthetic",
        "input": [{"role": "user", "content": "probe"}],
        "tools": [],
        "store": False,
        "truncation": "disabled",
        "max_output_tokens": budget.output_reserve,
    }
    provider.count(payload)
    changed = copy.deepcopy(payload)
    changed["instructions"] = "changed after counting"

    with pytest.raises(ExactPayloadMismatch, match="counted payload"):
        provider.generate(changed)
