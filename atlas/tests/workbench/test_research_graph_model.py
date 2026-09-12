"""Graph proposals preserve exact evidence, distinctness, and per-link decisions."""

from copy import deepcopy

import pytest


@pytest.fixture
def packet():
    return {"records": [{"id": "finding", "kind": "claim", "title": "Measured prediction error"}],
            "sources": [{"id": "source", "record_id": "finding", "passage_ids": ["p1"]}],
            "document": {"passages": [{"id": "p1", "source_id": "source", "locator": "Abstract",
                "text": "Measured lineage outcomes differed from predicted cell fates in this experiment."}]}}


def question_candidate():
    return {"useful": True, "title": "Which outcome check distinguishes the predictions?",
            "summary": "Identify an outcome check for the discrepancy.", "scope": "The inspected experiment.",
            "limitations": "The abstract does not resolve this local question.",
            "motivation": "Measured and predicted outcomes differ.", "advance": "An independently measured outcome.",
            "parents": ["parent"], "views": ["prediction"], "premises": ["finding"], "duplicate_of": "",
            "evidence": [{"passage_id": "p1", "quote": "Measured lineage outcomes differed from predicted cell fates"}]}


def test_question_must_bind_every_parent_premise_and_quote(packet):
    from workbench.research_graph_model import validate_question
    candidate = question_candidate()
    questions = [{"id": "parent", "title": "How well do predictions work?", "eligible_parent": True}]
    assert validate_question(candidate, packet, questions, ["prediction"])
    for field, value in (("parents", ["invented"]), ("premises", ["invented"]),
                         ("views", ["foreign"]), ("evidence", [{"passage_id": "p1", "quote": "An invented source quotation here"}])):
        changed = deepcopy(candidate)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_question(changed, packet, questions, ["prediction"])


def test_question_review_can_identify_a_paraphrased_duplicate(packet):
    from workbench.research_graph_model import validate_question_review
    result = {"analysis": {"verdict": "duplicate", "reason": "Same requested measurement and system.",
                          "duplicate_of": "parent", "evidence": [{"passage_id": "p1"}], "relations": []}}
    assert validate_question_review(result, packet, question_candidate(), [{"id": "parent"}])["verdict"] == "duplicate"


def test_overlap_requires_an_individual_decision_for_every_link(packet):
    from workbench.research_graph_model import validate_overlap, validate_overlap_review
    candidate = {"links": [{"record_id": "finding", "predicate": "informs", "answer_scope": "", "remaining": "",
                             "rationale": "This observation bears on prediction accuracy.",
                             "evidence": question_candidate()["evidence"]}], "reason": "One supported connection."}
    assert validate_overlap(candidate, packet)
    with pytest.raises(ValueError):
        validate_overlap_review({"analysis": {"decisions": []}}, packet, candidate)
    result = {"analysis": {"decisions": [{"record_id": "finding", "predicate": "informs", "verdict": "uncertain",
                                           "reason": "Scope may not transfer.", "evidence": []}]}}
    decisions = validate_overlap_review(result, packet, candidate)
    assert decisions[0]["verdict"] == "uncertain"


def test_graph_digests_accept_real_model_timings_and_preserve_record_hashes():
    import pytest
    from workbench.research_graph import graph_digest
    from workbench.lighthouse_wire import digest
    record = {"title": "Question?", "evidence": [], "value": 2}
    assert graph_digest(record) == digest(record)["value"]
    response = {"analysis": record, "metrics": {"wall_time_seconds": 1.25}}
    assert graph_digest(response) == graph_digest(dict(reversed(list(response.items()))))
    assert graph_digest(response) != graph_digest(response | {"metrics": {"wall_time_seconds": 2.25}})
    with pytest.raises(ValueError):
        graph_digest({"metrics": float("nan")})


def question_review():
    return {"analysis": {"verdict": "useful", "reason": "A scoped measurable gap.", "duplicate_of": "",
                         "evidence": [{"passage_id": "p1"}], "relations": [
                             {"kind": "parent", "record_id": "parent", "verdict": "supported",
                              "reason": "The measurement resolves a prediction validation subproblem.", "evidence": [{"passage_id": "p1"}]},
                             {"kind": "premise", "record_id": "finding", "verdict": "supported",
                              "reason": "The observed discrepancy motivates this outcome check.", "evidence": [{"passage_id": "p1"}]},
                         ]}}


def test_useful_question_review_requires_one_separate_decision_per_parent_and_premise(packet):
    from workbench.research_graph_model import validate_question_review
    reviewed = validate_question_review(question_review(), packet, question_candidate(), [{"id": "parent"}])
    assert len(reviewed["relations"]) == 2
    for change in ([], question_review()["analysis"]["relations"][:1],
                   question_review()["analysis"]["relations"] * 2):
        changed = question_review()
        changed["analysis"]["relations"] = change
        with pytest.raises(ValueError, match="relation|decision"):
            validate_question_review(changed, packet, question_candidate(), [{"id": "parent"}])


@pytest.mark.parametrize("field,value", [("record_id", "invented"), ("kind", "unknown"),
                                         ("reason", ""), ("verdict", "useful"), ("evidence", [])])
def test_question_relation_review_refuses_missing_scope_or_unsupported_ids(packet, field, value):
    from workbench.research_graph_model import validate_question_review
    changed = question_review()
    changed["analysis"]["relations"][1][field] = value
    with pytest.raises(ValueError):
        validate_question_review(changed, packet, question_candidate(), [{"id": "parent"}])


def test_question_premise_decision_must_cite_that_premises_source(packet):
    from workbench.research_graph_model import validate_question_review
    packet["records"].append({"id": "other", "title": "Other finding"})
    packet["sources"].append({"id": "other-source", "record_id": "other", "passage_ids": ["p2"]})
    packet["document"]["passages"].append({"id": "p2", "source_id": "other-source", "locator": "Abstract", "text": "Another observed outcome."})
    changed = question_review()
    changed["analysis"]["relations"][1]["evidence"] = [{"passage_id": "p2"}]
    with pytest.raises(ValueError, match="own source"):
        validate_question_review(changed, packet, question_candidate(), [{"id": "parent"}])


def test_question_relation_reason_is_bounded_without_shortening_overall_review(packet):
    from workbench.research_graph_model import validate_question_review
    result = question_review()
    result["analysis"]["reason"] = "Overall scoped assessment. " * 40
    result["analysis"]["relations"][0]["reason"] = "x" * 600
    assert validate_question_review(result, packet, question_candidate(), [{"id": "parent"}])
    result["analysis"]["relations"][0]["reason"] += "x"
    with pytest.raises(ValueError, match="bounded"):
        validate_question_review(result, packet, question_candidate(), [{"id": "parent"}])


def test_overlap_review_constrains_decisions_to_proposed_subset(packet):
    from workbench.research_graph_model import review_overlap
    candidate = {'links': [{'record_id': 'finding', 'rationale': 'Located reason',
                           'evidence': question_candidate()['evidence']}], 'reason': 'One relevant record.'}
    class Model:
        def _comparison_data(self, *args):
            return {'candidate': {}}
        def _chat(self, instruction, data, schema):
            assert data['candidate']['review_only_record_ids'] == ['finding']
            decisions = schema['properties']['decisions']
            assert decisions['minItems'] == decisions['maxItems'] == 1
            assert decisions['items']['properties']['record_id']['enum'] == ['finding']
            return {'analysis': {'decisions': [{'record_id': 'finding', 'predicate': 'informs', 'verdict': 'supported',
                                               'reason': 'The evidence addresses the question.',
                                               'evidence': [{'passage_id': 'p1'}]}]}}
    assert len(review_overlap(Model(), {}, packet, candidate)['analysis']['decisions']) == 1


def overlap_candidate(predicate="answers", answer_scope="The inspected mouse experiment.", remaining=""):
    return {"links": [{"record_id": "finding", "predicate": predicate, "answer_scope": answer_scope,
                       "remaining": remaining, "rationale": "The measured discrepancy resolves this scoped comparison.",
                       "evidence": question_candidate()["evidence"]}], "reason": "One scoped relationship."}


@pytest.mark.parametrize("predicate,scope,remaining,kind", [
    ("answers", "The measured mouse lineage discrepancy.", "", "claim"),
    ("partially_answers", "The measured mouse lineage discrepancy.", "Whether it transfers to another lineage.", "claim"),
    ("raises_question", "", "Which independent measurement explains the discrepancy?", "claim"),
    ("informs", "", "", "claim"), ("addresses", "", "", "approach"), ("tests", "", "", "experiment"),
])
def test_overlap_distinguishes_answer_scope_gaps_and_endpoint_kinds(packet, predicate, scope, remaining, kind):
    from workbench.research_graph_model import validate_overlap
    assert validate_overlap(overlap_candidate(predicate, scope, remaining), packet, record_kinds={"finding": kind})


@pytest.mark.parametrize("predicate,scope,remaining,kind", [
    ("answers", "", "", "claim"), ("answers", "The system.", "An unresolved aspect.", "claim"),
    ("partially_answers", "The system.", "", "claim"), ("partially_answers", "", "An unresolved aspect.", "claim"),
    ("raises_question", "Claimed answer.", "A gap.", "claim"), ("raises_question", "", "", "claim"),
    ("informs", "Answer scope.", "", "claim"), ("addresses", "", "A gap.", "approach"),
    ("answers", "The system.", "", "approach"), ("tests", "", "", "claim"),
    ("informs", "", "", "question"), ("unknown", "", "", "claim"),
])
def test_overlap_refuses_ambiguous_answer_fields_and_wrong_kind(packet, predicate, scope, remaining, kind):
    from workbench.research_graph_model import validate_overlap
    with pytest.raises(ValueError):
        validate_overlap(overlap_candidate(predicate, scope, remaining), packet, record_kinds={"finding": kind})


def test_overlap_review_cannot_downgrade_or_change_the_proposed_predicate(packet):
    from workbench.research_graph_model import validate_overlap_review
    candidate = overlap_candidate()
    result = {"analysis": {"decisions": [{"record_id": "finding", "predicate": "informs", "verdict": "supported",
                                          "reason": "This is relevant background.", "evidence": [{"passage_id": "p1"}]}]}}
    with pytest.raises(ValueError, match="predicate"):
        validate_overlap_review(result, packet, candidate)
    result["analysis"]["decisions"][0]["predicate"] = "answers"
    assert validate_overlap_review(result, packet, candidate)[0]["predicate"] == "answers"


@pytest.mark.parametrize("kind,predicate", [("claim", "informs"), ("approach", "addresses"), ("experiment", "tests")])
def test_legacy_overlap_shapes_require_explicit_mode_and_never_mutate_saved_fields(packet, kind, predicate):
    from workbench.research_graph_model import normalize_overlap_candidate, validate_overlap, validate_overlap_review
    candidate = overlap_candidate()
    for field in ("predicate", "answer_scope", "remaining"):
        candidate["links"][0].pop(field)
    before = deepcopy(candidate)
    result = {"analysis": {"decisions": [{"record_id": "finding", "verdict": "supported",
                                          "reason": "The source supports the legacy relation.", "evidence": [{"passage_id": "p1"}]}]}}
    review_before = deepcopy(result)
    with pytest.raises(ValueError):
        validate_overlap(candidate, packet)
    assert validate_overlap(candidate, packet, legacy=True, record_kinds={"finding": kind})
    decisions = validate_overlap_review(result, packet, candidate, legacy=True, record_kinds={"finding": kind})
    assert decisions[0]["predicate"] == predicate
    normalized = normalize_overlap_candidate(candidate, {"finding": kind})
    assert normalized["links"][0] == before["links"][0] | {"predicate": predicate, "answer_scope": "", "remaining": ""}
    assert candidate == before and result == review_before


def test_fresh_overlap_review_receives_legacy_copy_with_exact_predicate(packet):
    from workbench.research_graph_model import review_overlap
    candidate = overlap_candidate()
    for key in ("predicate", "answer_scope", "remaining"):
        candidate["links"][0].pop(key)
    original = deepcopy(candidate)
    class Model:
        def _comparison_data(self, question, source_packet, proposed):
            assert source_packet == packet
            assert proposed["links"][0]["predicate"] == "informs"
            assert proposed["links"][0]["answer_scope"] == proposed["links"][0]["remaining"] == ""
            return {"candidate": {"proposal": proposed}}
        def _chat(self, instructions, data, schema):
            assert "exact predicate" in instructions
            return {"analysis": {"decisions": [{"record_id": "finding", "predicate": "informs", "verdict": "supported",
                                                  "reason": "Scoped background.", "evidence": [{"passage_id": "p1"}]}]}}
    review_overlap(Model(), {}, packet, candidate)
    assert candidate == original


def test_overlap_model_prompt_receives_separate_record_kinds_without_changing_packet(packet):
    from workbench.research_graph_model import overlap
    original = deepcopy(packet)
    class Model:
        def _comparison_data(self, question, source_packet):
            assert source_packet == original
            return {"candidate": {"input_claims": source_packet["records"]}}
        def _chat(self, instructions, data, schema):
            assert data["candidate"]["record_kinds"] == {"finding": "approach"}
            assert all(word in instructions for word in ("answers", "partially_answers", "raises_question", "remaining"))
            return {"analysis": overlap_candidate("addresses", "", "")}
    assert overlap(Model(), {}, packet, record_kinds={"finding": "approach"})
    assert packet == original


def test_legacy_question_review_and_relation_helper_preserve_original_semantics(packet):
    from workbench.research_graph_model import validate_question_review
    from workbench.research_questions import _reviewed_relations
    candidate = question_candidate()
    review = question_review()
    del review["analysis"]["relations"]
    before = deepcopy(review)
    with pytest.raises(ValueError):
        validate_question_review(review, packet, candidate, [{"id": "parent"}])
    decision = validate_question_review(review, packet, candidate, [{"id": "parent"}], legacy=True)
    links = _reviewed_relations(candidate, decision, packet, premise_predicate="informs", legacy=True)
    assert [link["predicate"] for link in links] == ["part_of", "informs"]
    assert all(link["rationale"] == candidate["motivation"] for link in links)
    assert all(link["context"] == {"review_verdict": "useful", "review_reason": decision["reason"]} for link in links)
    assert review == before and "relations" not in decision


def test_new_question_premises_raise_the_question_with_their_own_review(packet):
    from workbench.research_questions import _reviewed_relations
    candidate, decision = question_candidate(), question_review()["analysis"]
    links = _reviewed_relations(candidate, decision, packet)
    assert [link["predicate"] for link in links] == ["part_of", "raises_question"]
    assert links[1]["rationale"] == decision["relations"][1]["reason"]


def test_question_reviewer_uses_the_original_premise_predicate_meaning(packet):
    from workbench.research_graph_model import review_question
    calls = []
    class Model:
        def _comparison_data(self, *args):
            return {"candidate": {}}
        def _chat(self, instruction, data, schema):
            calls.append((instruction, data))
            return question_review()
    model = Model()
    review_question(model, {}, packet, question_candidate(), [{"id": "parent"}], ["prediction"],
                    premise_predicate="informs")
    legacy_instruction, legacy_data = calls[-1]
    assert legacy_data["candidate"]["premise_predicate"] == "informs"
    assert "relevant scoped information" in legacy_instruction
    assert "background" in legacy_instruction and "need not itself raise" in legacy_instruction
    assert "Generic background relevance and shared terms are insufficient" not in legacy_instruction
    assert "specifically raises" not in legacy_instruction
    review_question(model, {}, packet, question_candidate(), [{"id": "parent"}], ["prediction"])
    new_instruction, new_data = calls[-1]
    assert new_data["candidate"]["premise_predicate"] == "raises_question"
    assert "specifically raises" in new_instruction and "unresolved gap" in new_instruction
    assert "SEPARATE relation decision" in legacy_instruction and "SEPARATE relation decision" in new_instruction


def test_overlap_generation_schema_constrains_predicate_and_scope_together(packet):
    import json
    from workbench.research_graph_model import OVERLAP_SCHEMA, overlap
    original = deepcopy(OVERLAP_SCHEMA)
    captured = []
    class Model:
        def _comparison_data(self, *args):
            return {"candidate": {}}
        def _chat(self, instruction, data, schema):
            captured.append(schema)
            return {"analysis": overlap_candidate("informs", "", "")}
    overlap(Model(), {}, packet)
    schema = captured[0]
    branches = schema["properties"]["links"]["items"]["anyOf"]
    assert len(branches) == 4
    expected = {
        frozenset({"informs", "addresses", "tests"}): ({"const": ""}, {"const": ""}),
        frozenset({"answers"}): ({"minLength": 1}, {"const": ""}),
        frozenset({"partially_answers"}): ({"minLength": 1}, {"minLength": 1}),
        frozenset({"raises_question"}): ({"const": ""}, {"minLength": 1}),
    }
    for branch in branches:
        assert branch["type"] == "object" and branch["additionalProperties"] is False
        assert set(branch["required"]) == set(original["properties"]["links"]["items"]["required"])
        properties = branch["properties"]
        constraints = expected.pop(frozenset(properties["predicate"]["enum"]))
        for field, constraint in zip(("answer_scope", "remaining"), constraints):
            assert properties[field].items() >= constraint.items()
    assert not expected
    assert len(json.dumps(schema).encode()) + 10000 < 20000
    assert OVERLAP_SCHEMA == original


def test_partial_answer_review_requires_a_concrete_answer_not_only_background(packet):
    from workbench.research_graph_model import review_overlap
    candidate = overlap_candidate("partially_answers", "Available measurement capabilities.",
                                  "Prediction accuracy was not assessed.")
    original = deepcopy(candidate)
    class Model:
        def _comparison_data(self, question, source_packet, proposed):
            assert proposed == original
            return {"candidate": {"proposal": proposed}}
        def _chat(self, instruction, data, schema):
            assert "absence of a full answer is insufficient" in instruction
            assert "concrete part of the target question" in instruction
            assert "capabilities or topic relevance" in instruction
            assert "Reject the proposed partially_answers link" in instruction
            return {"analysis": {"decisions": [{"record_id": "finding", "predicate": "partially_answers",
                "verdict": "unsupported", "reason": "Capabilities alone do not answer the requested prediction accuracy.",
                "evidence": [{"passage_id": "p1"}]}]}}
    result = review_overlap(Model(), {"title": "How accurately do the models predict outcomes?"}, packet, candidate)
    assert result["analysis"]["decisions"][0]["predicate"] == "partially_answers"
    assert result["analysis"]["decisions"][0]["verdict"] == "unsupported"
    assert candidate == original
