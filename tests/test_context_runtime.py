import json

import pytest

from context_compile import Budget, ContextCapacityError
from context_runtime import ContextRuntime
from context_store import ContextStore, StoreConflict


class RecordingProvider:
    model = "fixture"
    capabilities = {"strict": True, "count_kind": "provider", "budget_scope": "model_call", "billing": "test"}

    def __init__(self, responses=None):
        self.requests = []
        self.responses = list(responses or [])
        self.counted = []

    def count(self, payload):
        self.counted.append(json.dumps(payload, sort_keys=True))
        return len(json.dumps(payload).encode()) // 3

    def generate(self, payload):
        assert json.dumps(payload, sort_keys=True) == self.counted[-1]
        self.requests.append(payload)
        if self.responses:
            return self.responses.pop(0)
        return answer("A useful answer")

    def close(self):
        pass


def answer(text):
    return {"id": "resp", "status": "completed", "output": [{"type": "message", "role": "assistant", "phase": "final_answer", "content": [{"type": "output_text", "text": text}]}], "usage": {"input_tokens": 10, "output_tokens": 5}}


def test_capture_precedes_generation_and_completed_event_is_idempotent(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    original = provider.generate
    def check_archive(payload):
        assert store.recent("a")[-1]["content"] == "Hello"
        return original(payload)
    provider.generate = check_archive
    runtime = ContextRuntime(store, provider, Budget())
    first = runtime.chat("a", "Hello", event_id="client")
    assert first["response"] == "A useful answer"
    assert runtime.chat("a", "Hello", event_id="client") == first
    assert len(provider.requests) == 1
    assert [e["role"] for e in store.recent("a")] == ["user", "assistant"]
    assert store.manifest("a", first["manifest_id"])["payload_digest"]
    runtime.close()


def test_a_b_a_recalls_original_and_keeps_immediate_referent(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    store.append("t", "user", "Lighthouse pilot: library books, May 12, coordinator Mira.")
    for i in range(30):
        store.append("t", "user", f"Unrelated gardening turn {i}")
        store.append("t", "assistant", "We can plant beans")
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget())
    runtime.chat("t", "Return to the Lighthouse pilot")
    assert "May 12" in json.dumps(provider.requests[-1])
    runtime.chat("t", "Yes, do that")
    assert "Return to the Lighthouse pilot" in json.dumps(provider.requests[-1])
    runtime.close()


def test_explicit_correction_survives_unrelated_turns_without_index(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget())
    runtime.correct("t", "coordinator", "Mira is the coordinator, not Mike")
    for i in range(20):
        store.append("t", "user", f"Garden {i}")
    store.conn.execute("DELETE FROM event_search")
    store.conn.commit()
    runtime.chat("t", "Who is coordinating?")
    assert "Mira is the coordinator, not Mike" in json.dumps(provider.requests[-1])
    assert all(item.get("role") != "developer" for item in provider.requests[-1]["input"])
    runtime.close()


def test_tool_round_recounts_and_preserves_original_provider_items(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    source = store.append("t", "user", "The cow is Étoile")
    items = [{"type": "reasoning", "id": "r", "encrypted_content": "opaque"}, {"type": "function_call", "name": "archive_read", "call_id": "call-1", "arguments": json.dumps({"id": source["id"], "offset": 0, "limit": 200})}]
    provider = RecordingProvider([{"id": "one", "status": "completed", "output": items, "usage": None}, answer("Étoile")])
    runtime = ContextRuntime(store, provider, Budget())
    assert runtime.chat("t", "Read the original")["response"] == "Étoile"
    second = provider.requests[1]["input"]
    assert second[-3:-1] == items
    assert second[-1]["call_id"] == "call-1"
    assert "Étoile" in second[-1]["output"]
    assert len(provider.counted) >= 2
    runtime.close()


def test_tool_cannot_read_another_thread(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    source = store.append("private", "user", "private value")
    provider = RecordingProvider([{"id": "one", "status": "completed", "output": [{"type": "function_call", "name": "archive_read", "call_id": "c", "arguments": json.dumps({"id": source["id"]})}], "usage": None}, answer("Unavailable")])
    runtime = ContextRuntime(store, provider, Budget())
    runtime.chat("public", "Try reading")
    assert "private value" not in json.dumps(provider.requests)
    assert "unavailable" in provider.requests[-1]["input"][-1]["output"].lower()
    runtime.close()


def test_failed_count_does_not_generate_or_lose_user_event(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget(input_ceiling=100, soft_target=50, context_window=300, output_reserve=100, margin=50))
    with pytest.raises(ContextCapacityError):
        runtime.chat("t", "x" * 1000, event_id="one")
    assert len(provider.requests) == 0
    assert store.recent("t")[0]["content"] == "x" * 1000
    with pytest.raises(StoreConflict):
        runtime.chat("t", "x" * 1000, event_id="one")
    runtime.close()


def test_unending_tools_stop_at_configured_call_limit(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    responses = [{"id": str(i), "status": "completed", "output": [{"type": "function_call", "name": "archive_search", "call_id": str(i), "arguments": '{"query":"milk"}'}], "usage": None} for i in range(5)]
    provider = RecordingProvider(responses)
    runtime = ContextRuntime(store, provider, Budget(), max_calls=2)
    with pytest.raises(ContextCapacityError):
        runtime.chat("t", "search milk")
    assert len(provider.requests) == 2
    assert store.status("t")["recent_turns"][0]["status"] == "capacity_stopped"
    runtime.close()


def test_subscription_has_no_duplicate_external_tool_execution(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    provider.capabilities = {"strict": False, "count_kind": "estimate", "budget_scope": "episode", "billing": "subscription"}
    runtime = ContextRuntime(store, provider, Budget())
    result = runtime.chat("t", "hello")
    assert provider.requests[0]["tools"] == []
    assert result["capabilities"]["budget_scope"] == "episode"
    runtime.close()


def test_context_inspection_resolves_pins_to_original_user_source(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    runtime = ContextRuntime(store, RecordingProvider(), Budget())
    runtime.correct("t", "coordinator", "Mira is the coordinator")
    result = runtime.read_source("t", "state:coordinator")
    assert result["text"] == "Mira is the coordinator"
    assert runtime.read_source("other", "state:coordinator").get("error")
    runtime.close()


def test_auxiliary_counts_obey_turn_deadline(tmp_path, monkeypatch):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    clock = [0.0]
    monkeypatch.setattr("context_runtime.time.monotonic", lambda: clock[0])
    def slow_count(payload):
        provider.counted.append(json.dumps(payload, sort_keys=True))
        clock[0] = 500
        return 100
    provider.count = slow_count
    runtime = ContextRuntime(store, provider, Budget(), max_seconds=2)
    with pytest.raises(ContextCapacityError, match="time"):
        runtime.chat("t", "hello")
    assert provider.requests == []
    runtime.close()


def test_failed_oversized_turn_does_not_poison_next_request(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget(input_ceiling=1800, soft_target=1000, context_window=2500, output_reserve=500, margin=100))
    with pytest.raises(ContextCapacityError):
        runtime.chat("t", "x" * 12_000)
    assert runtime.chat("t", "Ignore that oversized question. Hello.")["response"] == "A useful answer"
    assert store.recent("t")[0]["truncated"]
    assert "x" * 1000 not in json.dumps(provider.requests[-1])
    runtime.close()


def test_invalid_correction_leaves_no_archived_half_change(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    runtime = ContextRuntime(store, RecordingProvider(), Budget())
    with pytest.raises(ValueError):
        runtime.correct("t", "", "This correction should be rejected")
    assert store.recent("t") == []
    assert store.state("t") == []
    runtime.close()


def test_retrieval_priority_never_reorders_recent_dialogue(tmp_path):
    store = ContextStore(tmp_path / "runtime.db")
    history = [("user", "I prefer red"), ("assistant", "Would you like the red option?"), ("user", "Actually blue"), ("assistant", "Would you like the blue option?")]
    for role, text in history:
        store.append("t", role, text)
    provider = RecordingProvider()
    runtime = ContextRuntime(store, provider, Budget())
    runtime.chat("t", "Yes, that.")
    evidence = [json.loads(item["content"])["evidence"] for item in provider.requests[-1]["input"][:-1]]
    assert evidence == [text for _, text in history]
    runtime.close()


def test_source_deleted_during_count_is_removed_and_recounted(tmp_path):
    import sqlite3
    from context_sources import EngramSource
    memory = tmp_path / "engram.db"
    with sqlite3.connect(memory) as conn:
        conn.execute("CREATE TABLE episodes(id TEXT,content TEXT,core INTEGER)")
        conn.execute("INSERT INTO episodes VALUES('e','violet secret value',0)")
    store = ContextStore(tmp_path / "runtime.db")
    provider = RecordingProvider()
    count = provider.count
    def revoke(payload):
        with sqlite3.connect(memory) as conn:
            conn.execute("DELETE FROM episodes")
        return count(payload)
    provider.count = revoke
    runtime = ContextRuntime(store, provider, Budget(), sources=(EngramSource(memory),))
    runtime.chat("t", "What was the violet value?")
    assert "violet secret value" not in json.dumps(provider.requests[-1])
    assert len(provider.counted) == 2
    runtime.close()
