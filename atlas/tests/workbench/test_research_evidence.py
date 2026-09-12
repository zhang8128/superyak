"""Shared packets retain original passages and current graph membership."""

from copy import deepcopy

import pytest

from test_research_runner import project
from test_research_connections import researcher


@pytest.mark.parametrize("count", [1, 2, 3])
def test_packet_preserves_each_whole_required_passage(researcher, count):
    from workbench.research_evidence import eligible_inputs, make_packet

    inputs = list(eligible_inputs(researcher, researcher.inbox.snapshot()).values())
    third = deepcopy(inputs[-1])
    third["record"]["id"] = "third-evidence-record"
    third["source"]["id"] = "third-source"
    inputs = (inputs + [third])[:count]
    before = deepcopy(inputs)
    packet = make_packet(inputs)
    assert len(packet["records"]) == len(packet["sources"]) == count
    for index, item in enumerate(inputs, 1):
        source = packet["sources"][index - 1]
        assert source["record_id"] == item["record"]["id"]
        for passage in item["document"]["passages"]:
            if passage["id"] not in item["anchors"]:
                continue
            identifier = f"s{index}:{passage['id']}"
            assert identifier in source["passage_ids"]
            assert passage | {"id": identifier, "source_id": item["source"]["id"]} in packet["document"]["passages"]
    if count == 2:
        assert packet["document"]["source"]["title"] == "Comparison of two attributed source excerpts"
    assert inputs == before


def test_packet_refuses_missing_required_source_passages(researcher):
    from workbench.research_evidence import eligible_inputs, make_packet

    inputs = list(eligible_inputs(researcher, researcher.inbox.snapshot()).values())
    inputs[0]["anchors"].append("missing-original-passage")
    with pytest.raises(ValueError):
        make_packet(inputs)
    with pytest.raises(ValueError):
        make_packet([])


def test_question_links_come_from_current_live_question_edges(researcher):
    from workbench.research_evidence import eligible_inputs, question_links

    snapshot = researcher.inbox.snapshot()
    identifier = next(iter(eligible_inputs(researcher, snapshot)))
    original = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier)
    snapshot["bundle"]["relations"].extend([
        deepcopy(original) | {"id": "later-link", "object": "q-regulation"},
        deepcopy(original) | {"id": "withdrawn-link", "status": "withdrawn", "object": "unknown-question"},
        deepcopy(original) | {"id": "non-question-link", "object": "c-markov"},
    ])
    assert question_links(snapshot, identifier) == {"q-fate", "q-regulation"}
    assert question_links(snapshot, identifier, excluded_relations={"later-link"}) == {"q-fate"}
    original["status"] = "withdrawn"
    assert question_links(snapshot, identifier) == {"q-regulation"}
    next(r for r in snapshot["bundle"]["items"] if r["id"] == "q-regulation")["status"] = "withdrawn"
    assert question_links(snapshot, identifier) == set()


def test_additional_question_link_cannot_restore_rejected_evidence(researcher):
    from workbench.research_evidence import eligible_inputs
    from workbench.research_review import review_backlog

    identifier = next(iter(eligible_inputs(researcher, researcher.inbox.snapshot())))
    review = researcher.model.review
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review = reject
    assert review_backlog(researcher.project, researcher.model, record_ids=[identifier])["reviewed"] == 1
    snapshot = researcher.inbox.snapshot()
    original = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier)
    snapshot["bundle"]["relations"].append(deepcopy(original) | {"id": "new-overlap", "object": "q-regulation"})
    assert identifier not in eligible_inputs(researcher, snapshot)


def test_graph_journal_overlap_preserves_original_evidence_eligibility(researcher):
    from workbench.research_evidence import eligible_inputs, question_links
    from workbench.research_graph import graph_digest
    from workbench.research_review import review_backlog

    snapshot = researcher.inbox.snapshot()
    inputs = eligible_inputs(researcher, snapshot)
    identifier, item = next(iter(inputs.items()))
    question = next(r for r in snapshot["bundle"]["items"] if r["id"] == "q-regulation")
    draft_path = researcher.inbox.state / "drafts" / f"{identifier}.json"
    original = draft_path.read_bytes()
    receipt = researcher.inbox.record_graph({
        "idempotency_key": "evidence-overlap-integration", "question": None,
        "relations": [{"subject": identifier, "predicate": "informs", "object": question["id"],
                       "rationale": "This scoped observation motivates an outcome check for regulation.",
                       "context": {"scope": item["record"]["context"]["scope"]},
                       "evidence": item["record"]["evidence"]}],
        "expected": {identifier: graph_digest(item["record"]), question["id"]: graph_digest(question)},
        "context": {"worker_role": "overlap"},
    }, researcher.session_id)
    assert receipt["recorded"]
    updated = researcher.inbox.snapshot()
    assert identifier in eligible_inputs(researcher, updated)
    assert question_links(updated, identifier) == {"q-fate", "q-regulation"}
    assert review_backlog(researcher.project, researcher.model, record_ids=[identifier])["reviewed"] == 1
    assert draft_path.read_bytes() == original
