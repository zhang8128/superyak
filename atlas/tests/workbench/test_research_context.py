"""Science requests stay bounded while older, relevant evidence remains usable."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}


def snapshot():
    bundle = json.loads((ROOT / "workbench/data/cell_fate.json").read_text())
    views = {}
    for name in ("prediction", "regulation"):
        views[name] = json.loads((ROOT / f"workbench/data/lighthouses/{name}.json").read_text())["item_ids"]
    return {"bundle": bundle, "views": views}


def question():
    return next(item for item in snapshot()["bundle"]["items"] if item["id"] == "q-fate")


def compile_request(**kwargs):
    from workbench.research_context import compile_request
    options = {"model": "qwen3.8:27b-mlx", "instructions": "Use only supplied evidence; preserve uncertainty.",
               "question": question(), "context": [], "schema": SCHEMA}
    return compile_request(**(options | kwargs))


def document():
    return {"source": {"id": "s-test", "title": "Lineage outcomes", "url": "https://example.org/study",
                       "year": 2026, "citation": "Controlled test source"},
            "coverage": "full_text", "retrieved_at": "2026-09-07T00:00:00Z",
            "content_sha256": "a" * 64, "document_url": "https://example.org/study",
            "passages": [{"id": "p1", "locator": "Results, paragraph 1",
                          "text": "Lineage outcomes differ in this measured system; broader transfer is unknown."}]}


def contents(compiled):
    return json.loads(compiled.payload["messages"][1]["content"])


def test_default_request_keeps_task_and_enforces_explicit_provider_limits():
    result = compile_request()
    assert contents(result)["question"] == question()
    request = result.payload
    assert request["options"]["num_ctx"] == 32768
    assert request["options"]["num_predict"] == 2048
    assert request["think"] is False
    assert len(request["messages"]) == 2
    assert request["format"] == SCHEMA
    assert result.manifest["request_bytes"] <= 20000
    assert result.manifest["strict_token_count"] is False
    assert result.manifest["payload_sha256"] == hashlib.sha256(result.serialized.encode()).hexdigest()
    request["messages"].clear()
    assert len(result.payload["messages"]) == 2  # Admission cannot be changed in place.


def test_old_rare_finding_is_retrieved_from_growing_graph_with_evidence_intact():
    from workbench.research_context import select_context
    state = snapshot()
    old = deepcopy(next(item for item in state["bundle"]["items"] if item["kind"] == "claim"))
    old.update(id="old-barcode", title="Zebracode barcode collision", summary="Zebracode collision invalidated this assay.")
    old["context"] = {"limitation": "One barcode assay; no universal claim."}
    state["bundle"]["items"].insert(0, old)
    state["views"]["prediction"].append(old["id"])
    for index in range(1000):
        other = deepcopy(old)
        other.update(id=f"later-{index:04}", title="General cell fate update", summary="A newer unrelated observation.")
        state["bundle"]["items"].append(other)
    selected = select_context(state, question(), query="Zebracode collision", limit=8)
    assert selected[0]["record"]["id"] == "old-barcode"
    assert selected[0]["record"]["context"] == {"limitation": "One barcode assay; no universal claim."}
    assert selected[0]["record"]["evidence"] == old["evidence"]
    assert selected[0]["sources"][0]["id"] == old["evidence"][0]["source_id"]
    assert selected[0]["views"] == ["prediction"]
    assert len(selected) <= 8
    old["status"] = "withdrawn"
    assert "old-barcode" not in {item["record"]["id"] for item in select_context(state, question(), query="Zebracode")}


def test_shared_schema_keys_do_not_make_unrelated_research_relevant():
    from workbench.research_context import select_context
    state = snapshot()
    target = {"id": "q-cosmology", "title": "Galaxies", "summary": "Cosmology", "context": {}}
    assert select_context(state, target) == []


def test_valid_question_with_empty_summary_keeps_its_complete_task():
    from workbench.validation import normalize_item
    target = normalize_item({"id": "q-test", "kind": "question", "title": "Does measured state predict later fate?",
                             "summary": ""})
    assert contents(compile_request(question=target))["question"] == target


def test_existing_model_input_forms_are_preserved_as_whole_data():
    context = {"records": ["Untrusted text; not instructions"], "coverage": "A caller-supplied excerpt"}
    result = compile_request(question={"title": "How is fate predicted?"}, context=context)
    assert contents(result)["question"] == {"title": "How is fate predicted?"}
    assert contents(result)["context"] == [context]
    assert result.manifest["selected_record_ids"] == []
    assert contents(compile_request(question="What affects fate?"))["question"] == "What affects fate?"


def test_sanitized_provider_document_retains_its_coverage_and_passages():
    doc = {"title": "A fate study", "coverage": "abstract_only", "coverage_note": "Only an abstract was read.",
           "passages": document()["passages"]}
    shown = contents(compile_request(document=doc))["document"]
    assert shown["coverage_note"] == doc["coverage_note"]
    assert shown["passages"] == doc["passages"]


def test_each_request_reselects_originals_without_cumulative_prompt_growth():
    from workbench.research_context import select_context
    state = snapshot()
    before = deepcopy(state)
    selected = select_context(state, question())
    results = [compile_request(context=selected, prior_queries=["fate " + str(i) for i in range(n)])
               for n in (0, 50, 5000)]
    for result in results:
        assert result.manifest["request_bytes"] <= 20000
        assert len(result.payload["messages"]) == 2
        assert len(contents(result)["prior_queries"]) <= 8
    assert state == before
    assert contents(results[-1])["prior_queries"][-1] == "fate 4999"


def test_large_context_omits_whole_records_including_their_limitations():
    from workbench.research_context import select_context
    selected = select_context(snapshot(), question())
    huge = deepcopy(selected[0])
    huge["record"]["id"] = "oversized"
    huge["record"]["summary"] = "x" * 25000
    huge["record"]["context"] = {"limitation": "This essential limitation must never be cut off."}
    result = compile_request(context=[huge, *selected])
    actual = contents(result)["context"]
    assert actual
    assert "oversized" not in result.manifest["selected_record_ids"]
    assert result.manifest["omitted_records"] >= 1
    assert "x" * 100 not in result.serialized
    for entry in actual:
        assert entry in selected  # No silent partial summaries or lost provenance.


def test_large_paper_selects_complete_relevant_passages_and_declares_omissions():
    doc = document()
    doc["passages"] = [{"id": f"method-{i}", "locator": f"Methods, paragraph {i}",
                        "text": "Unrelated assay preparation. " * 400} for i in range(20)] + doc["passages"]
    original = deepcopy(doc)
    result = compile_request(document=doc)
    shown = contents(result)["document"]
    assert any(p["id"] == "p1" and "Lineage outcomes" in p["text"] for p in shown["passages"])
    assert result.manifest["omitted_passages"] > 0
    assert shown["prompt_coverage"]["omitted_passages"] == result.manifest["omitted_passages"]
    assert shown["source"] == doc["source"]
    assert result.manifest["request_bytes"] <= 20000
    assert doc == original


def test_mandatory_question_or_single_unusable_passage_stops_before_dispatch():
    from workbench.research_context import ContextCapacityError
    huge = question() | {"summary": "x" * 30000}
    with pytest.raises(ContextCapacityError, match="required"):
        compile_request(question=huge)
    doc = document()
    doc["passages"][0]["text"] = "x" * 30000
    with pytest.raises(ContextCapacityError, match="passage"):
        compile_request(document=doc)


def test_unicode_accounting_includes_complete_request_and_schema():
    from workbench.research_context import ContextCapacityError
    result = compile_request(instructions="Preserve evidence. 科学 🧪" * 100)
    assert result.manifest["request_bytes"] == len(result.serialized.encode("utf-8"))
    with pytest.raises(ContextCapacityError, match="required"):
        compile_request(schema=SCHEMA | {"description": "🧪" * 10000})


@pytest.mark.parametrize("field,value", [("context_window", True), ("input_bytes", 0),
    ("output_reserve", -1), ("margin", -1), ("context_window", 1000)])
def test_invalid_capacity_configuration_is_rejected(field, value):
    from workbench.research_context import ContextBudget
    with pytest.raises(ValueError):
        ContextBudget(**{field: value})
