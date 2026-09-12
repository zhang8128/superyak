"""Explicit answer vocabulary is additive across capture and portable publication."""

import json

import pytest

from test_lighthouse import bundle, config
from test_research_graph import inbox, proposal, question
from workbench.lighthouse import evaluate, publish, restrict, validate_publication
from workbench.research_graph import graph_digest, normalize_proposal
from workbench.validation import WorkbenchError, normalize_bundle


EXPLICIT = ("answers", "partially_answers", "raises_question")


@pytest.mark.parametrize("predicate", EXPLICIT)
def test_answer_predicate_round_trips_as_claim_to_question_without_required_context(predicate):
    original = bundle()
    original["relations"][0]["predicate"] = predicate
    normalized = normalize_bundle(original)
    assert normalized["relations"][0]["context"] == {}
    publication = publish(normalized, config())
    assert validate_publication(json.loads(json.dumps(publication))) == publication
    relation, = publication["snapshot"]["payload"]["model"]["relations"]
    assert (relation["subject"], relation["predicate"], relation["object"]) == ("claim", predicate, "question")
    claim = next(c for c in publication["claims"] if c["payload"]["sentence"]["record_id"] == "claim")
    assert evaluate(claim, publication["snapshot"]) == "satisfied"
    assert next(r for r in publication["snapshot"]["payload"]["model"]["items"] if r["id"] == "claim")["status"] == "source_reported"


@pytest.mark.parametrize("predicate", EXPLICIT)
@pytest.mark.parametrize("subject,object_id", [("question", "claim"), ("question", "question"),
                                             ("claim", "claim"), ("method", "question"), ("experiment", "question")])
def test_answer_predicate_rejects_reversed_and_wrong_endpoint_kinds(predicate, subject, object_id):
    original = bundle()
    original["items"] += [{"id": "method", "kind": "approach", "title": "A method", "summary": "A method"},
                          {"id": "experiment", "kind": "experiment", "title": "An experiment", "summary": "An experiment"}]
    original["relations"][0].update(subject=subject, object=object_id, predicate=predicate)
    with pytest.raises(WorkbenchError, match="endpoint types"):
        normalize_bundle(original)
    with pytest.raises(ValueError, match="endpoint kinds"):
        publish(original, config())


def test_all_explicit_links_preserve_original_claims_memberships_and_generic_links(inbox):
    old = inbox.record_graph(proposal(inbox), "legacy-session")
    old_path = inbox.state / "graph-drafts" / (old["graph_draft_id"] + ".json")
    old_entry = old_path.read_bytes()
    old_generation = inbox.state / "publications" / old["generation"]
    old_artifacts = {p: p.read_bytes() for p in old_generation.glob("*.json")}
    before = inbox.snapshot()
    raw = proposal(inbox, [("c-cellrank", "answers", "q-fate"),
                           ("c-cellrank", "partially_answers", "q-regulation"),
                           ("c-cellrank", "raises_question", "q-regulation")], key="explicit-links")
    raw["relations"][0]["context"].update(answer_scope="The inspected system.", remaining="")
    raw["relations"][1]["context"].update(answer_scope="The measured cell type.", remaining="Other cell types are unresolved.")
    raw["relations"][2]["context"].update(answer_scope="", remaining="Which measurement resolves the discrepancy?")
    result = inbox.record_graph(raw, "answer-session")
    after = inbox.snapshot()
    assert result["record_ids"] == [] and result["recorded"] and result["publication_status"] == "current"
    assert after["views"] == before["views"] and after["bundle"]["items"] == before["bundle"]["items"]
    assert after["bundle"]["sources"] == before["bundle"]["sources"]
    relations = {r["id"]: r for r in after["bundle"]["relations"]}
    assert {relations[identifier]["predicate"] for identifier in result["relation_ids"]} == set(EXPLICIT)
    assert all(relations[identifier]["status"] == "proposed" for identifier in result["relation_ids"])
    assert all(relations[r["id"]] == r for r in before["bundle"]["relations"])
    assert old_path.read_bytes() == old_entry
    assert all(path.read_bytes() == content for path, content in old_artifacts.items())
    assert inbox._read_generation(old["generation"])[0]["generation"] == old["generation"]
    replay = inbox.record_graph(raw, "answer-session")
    assert replay["duplicate"] and replay["relation_ids"] == result["relation_ids"]
    assert replay["generation"] == result["generation"]
    legacy_replay = inbox.record_graph(proposal(inbox), "legacy-session")
    assert legacy_replay["duplicate"] and legacy_replay["relation_ids"] == old["relation_ids"]


@pytest.mark.parametrize("predicate", EXPLICIT)
def test_answer_graph_capture_still_requires_located_existing_source_evidence(inbox, predicate):
    raw = proposal(inbox, [("c-cellrank", predicate, "q-fate")])
    raw["relations"][0]["evidence"] = []
    with pytest.raises(ValueError, match="source evidence"):
        inbox.record_graph(raw, "session-a")
    raw["relations"][0]["evidence"] = [{"source_id": "missing", "locator": "Abstract", "note": "Source account."}]
    with pytest.raises(ValueError, match="unknown source"):
        inbox.record_graph(raw, "session-a")
    assert not list((inbox.state / "graph-drafts").glob("*.json"))


def test_generated_question_can_capture_initial_raises_question_link_atomically(inbox):
    raw = proposal(inbox, [("c-cellrank", "raises_question", "$question"),
                           ("$question", "part_of", "q-fate")], question=question())
    result = inbox.record_graph(raw, "session-a")
    new_question, = result["record_ids"]
    snapshot = inbox.snapshot()
    assert any(r["subject"] == "c-cellrank" and r["predicate"] == "raises_question" and r["object"] == new_question
               for r in snapshot["bundle"]["relations"])
    assert new_question in snapshot["views"]["prediction"] and new_question not in snapshot["views"]["regulation"]


def test_explicit_vocabulary_exports_preserve_generic_relevance():
    from workbench.validation import CLAIM_QUESTION_PREDICATES, EXPLICIT_QUESTION_PREDICATES
    assert EXPLICIT_QUESTION_PREDICATES == frozenset(EXPLICIT)
    assert CLAIM_QUESTION_PREDICATES == frozenset({"informs", *EXPLICIT})


def test_unselected_answer_endpoints_never_expand_lighthouse_membership():
    original = bundle()
    original["relations"][0]["predicate"] = "answers"
    publication = publish(original, config())
    narrow = restrict(publication, ["claim"], {"id": "research/cell-fate/claim", "path": ["research", "cell-fate", "claim"]},
                      config()["issued_at"])
    assert [r["id"] for r in narrow["snapshot"]["payload"]["model"]["items"]] == ["claim"]
    assert narrow["snapshot"]["payload"]["model"]["relations"] == []
    assert narrow["policy"]["payload"]["rules"] == publication["policy"]["payload"]["rules"] == []


def test_old_publication_and_graph_proposal_hashes_are_unchanged():
    assert publish(bundle(), config())["snapshot"]["digest"]["value"] == "7f9c63ea933c932d2270f078c7c1f24e604e10117ff87ac22cf8113eea118f94"
    raw = {"idempotency_key": "legacy", "question": None, "relations": [
        {"subject": "claim", "predicate": "informs", "object": "question", "rationale": "Scoped background.",
         "context": {}, "evidence": [{"source_id": "paper-a", "locator": "Figure 2", "note": "Original observation."}]}],
        "expected": {"claim": "0" * 64, "question": "1" * 64}, "context": {}}
    assert graph_digest(normalize_proposal(raw, ["prediction"])) == "5d4ab045d7ec644804eea92d433cabb8c4418f97fe7807d068cfe10aed058ada"
