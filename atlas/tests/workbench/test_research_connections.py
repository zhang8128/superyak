"""Connections need two attributed sources, a separate review, and replay safety."""

from copy import deepcopy
import json

import pytest

from test_research_runner import project, runner, document, Model


def proposal(packet):
    return {"relevant": True, "title": "Two studies motivate checking predictions against measured outcomes",
            "summary": "Both supplied studies report mismatches between predictions and measured lineage outcomes.",
            "scope": "The two supplied mouse studies.", "limitations": "Abstracts only; no universal conclusion.",
            "rationale": "These scoped observations bear on the active question.",
            "links": [{"target": r["id"], "predicate": "supports", "rationale": "The comparison corroborates this scoped mismatch."}
                      for r in packet["records"]],
            "evidence": [{"passage_id": p["id"], "quote": "Measured lineage outcomes differed from predicted cell fates"}
                         for p in packet["document"]["passages"]]}


class ConnectorModel(Model):
    def connect(self, question, packet):
        return {"model": self.model, "analysis": proposal(packet), "metrics": {}, "context_manifest": {}}

    def review_connection(self, question, packet, candidate):
        return {"model": self.model, "metrics": {},
                "analysis": {"verdict": "supported", "reason": "Both supplied sources support the scoped comparison.",
                             "evidence": [{"passage_id": p["id"]} for p in packet["document"]["passages"]]},
                "context_manifest": {"selected_record_ids": [],
                                     "selected_passage_ids": [p["id"] for p in packet["document"]["passages"]]}}


@pytest.fixture
def researcher(project):
    worker = runner(project)
    worker.model = ConnectorModel()
    assert worker.cycle()["saved"] == 1
    second = document()
    second["source"].update(id="epmc:MED:456", title="Another controlled lineage study",
                            url="https://europepmc.org/article/MED/456", citation="Other authors. 2026.")
    worker.provider.search = lambda *args, **kwargs: {"papers": [{"key": "MED:456"}], "next_cursor": None}
    worker.provider.read = lambda *args: second
    assert worker.cycle()["saved"] == 1
    return worker


def test_connector_records_two_source_relationships_once(researcher):
    from workbench.research_connections import ConnectionWorker

    result = ConnectionWorker(researcher).cycle()
    assert result["saved"] == 1, result
    snapshot = researcher.inbox.snapshot()
    created = next(r for r in snapshot["bundle"]["items"] if r["id"] == result["record_ids"][0])
    assert created["context"]["worker_role"] == "connect"
    assert created["status"] == "proposed"
    assert len({e["source_id"] for e in created["evidence"]}) == 2
    links = [r for r in snapshot["bundle"]["relations"] if r["subject"] == created["id"]]
    assert sorted(r["predicate"] for r in links) == ["informs", "supports", "supports"]
    assert ConnectionWorker(researcher).cycle()["saved"] == 0


@pytest.mark.parametrize("verdict", ["unsupported", "uncertain"])
def test_connection_reviewer_can_hold_a_well_formed_candidate(researcher, verdict):
    from workbench.research_connections import ConnectionWorker

    review = researcher.model.review_connection
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = verdict
        return result
    researcher.model.review_connection = reject
    result = ConnectionWorker(researcher).cycle()
    assert result["held"] == 1 and result["saved"] == 0
    assert len(list((researcher.project / ".atlas/drafts").glob("*.json"))) == 2


@pytest.mark.parametrize("change", ["invented_quote", "invented_target", "same_source_only"])
def test_connector_refuses_unattributed_output(researcher, change):
    from workbench.research_connections import ConnectionWorker

    original = researcher.model.connect
    def malformed(*args):
        result = original(*args)
        if change == "invented_quote":
            result["analysis"]["evidence"][0]["quote"] = "An invented quotation that is absent"
        elif change == "invented_target":
            result["analysis"]["links"][0]["target"] = "not-supplied"
        else:
            result["analysis"]["evidence"] = result["analysis"]["evidence"][:1]
        return result
    researcher.model.connect = malformed
    result = ConnectionWorker(researcher).cycle()
    assert result["saved"] == 0 and result["errors"]


def test_connector_retries_same_candidate_after_reviewer_outage(researcher):
    from workbench.research_connections import ConnectionWorker

    review = researcher.model.review_connection
    researcher.model.review_connection = lambda *args: (_ for _ in ()).throw(RuntimeError("review offline"))
    assert ConnectionWorker(researcher).cycle()["errors"]
    researcher.model.connect = lambda *args: pytest.fail("A retry must retain the earlier candidate")
    researcher.model.review_connection = review
    assert ConnectionWorker(researcher).cycle()["saved"] == 1


def test_connector_excludes_rejected_inputs_and_does_not_change_originals(researcher):
    from workbench.research_connections import ConnectionWorker
    from workbench.research_review import review_backlog

    original = {p: p.read_bytes() for p in (researcher.project / ".atlas/drafts").glob("*.json")}
    review = researcher.model.review
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review = reject
    assert review_backlog(researcher.project, researcher.model, limit=1)["reviewed"] == 1
    researcher.model.connect = lambda *args: pytest.fail("Two eligible sources are required")
    result = ConnectionWorker(researcher).cycle()
    assert result["saved"] == 0 and result["skipped"] == 1
    assert all(p.read_bytes() == value for p, value in original.items())


def test_later_rejection_also_removes_dependent_comparisons_from_context(researcher):
    from workbench.research_connections import ConnectionWorker
    from workbench.research_review import review_backlog, ReviewLedger

    connection = ConnectionWorker(researcher).cycle()["record_ids"][0]
    review = researcher.model.review
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review = reject
    review_backlog(researcher.project, researcher.model, limit=1)
    assert connection in ReviewLedger(researcher.project).excluded(researcher.inbox.snapshot())


def test_connection_capture_replays_without_regeneration_after_receipt_loss(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker

    record = researcher.inbox.record
    def lost_receipt(*args):
        record(*args)
        raise OSError("receipt lost after capture")
    monkeypatch.setattr(researcher.inbox, "record", lost_receipt)
    assert ConnectionWorker(researcher).cycle()["errors"]
    monkeypatch.setattr(researcher.inbox, "record", record)
    researcher.model.connect = lambda *args: pytest.fail("Captured candidates must replay unchanged")
    researcher.model.review_connection = researcher.model.connect
    result = ConnectionWorker(researcher).cycle()
    assert result["replayed"] == 1 and result["saved"] == 0
    assert len(list((researcher.project / ".atlas/drafts").glob("*.json"))) == 3


def test_changed_prepared_connection_cannot_bypass_its_review(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker

    record = researcher.inbox.record
    monkeypatch.setattr(researcher.inbox, "record", lambda *args: (_ for _ in ()).throw(RuntimeError("capture offline")))
    assert ConnectionWorker(researcher).cycle()["errors"]
    path = next((researcher.root / "connections").glob("*.json"))
    job = json.loads(path.read_text())
    job["draft"]["summary"] = "This is an unreviewed replacement claim."
    path.write_text(json.dumps(job))
    monkeypatch.setattr(researcher.inbox, "record", record)
    result = ConnectionWorker(researcher).cycle()
    assert result["saved"] == 0 and result["errors"]


def test_connection_model_calls_have_fresh_attributed_context(researcher, monkeypatch):
    from workbench.research_connections import eligible_inputs, make_packet
    from workbench.research_model import Ollama
    from test_research_model import transport, completion, MODEL

    snapshot = researcher.inbox.snapshot()
    packet = make_packet(list(eligible_inputs(researcher, snapshot).values()))
    question = researcher._questions(snapshot)[0]
    candidate = proposal(packet)
    verdict = researcher.model.review_connection(question, packet, candidate)["analysis"]
    requests = transport(monkeypatch, [completion(candidate), completion(verdict)])
    model = Ollama(MODEL)
    model.connect(question, packet)
    model.review_connection(question, packet, candidate)
    for request, _ in requests:
        payload = json.loads(request.data)
        assert len(payload["messages"]) == 2
        data = json.loads(payload["messages"][1]["content"])
        assert data["context"] == []
        assert data["candidate"]["input_claims"] == packet["records"]
        assert {p["id"] for p in data["document"]["passages"]} == {p["id"] for p in packet["document"]["passages"]}
        assert len(data["document"]["sources"]) == 2
    assert json.loads(json.loads(requests[1][0].data)["messages"][1]["content"])["candidate"]["proposal"] == candidate


def test_connection_publication_failure_remains_recoverable(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker
    publish = researcher._publish_browser
    monkeypatch.setattr(researcher, "_publish_browser", lambda: (_ for _ in ()).throw(ValueError("render unavailable")))
    assert ConnectionWorker(researcher).cycle()["saved"] == 1
    monkeypatch.setattr(researcher, "_publish_browser", publish)
    assert ConnectionWorker(researcher).cycle()["replayed"] == 1


def test_review_cache_cannot_approve_a_changed_candidate(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker
    worker = ConnectionWorker(researcher)
    monkeypatch.setattr(worker, "_draft", lambda job: (_ for _ in ()).throw(RuntimeError("interrupted before draft")))
    assert worker.cycle()["errors"]
    path = next(worker.root.glob("*.json"))
    job = json.loads(path.read_text())
    job["candidate"]["analysis"]["summary"] = "An assertion the previous reviewer never saw."
    path.write_text(json.dumps(job))
    researcher.model.review_connection = lambda *args: (_ for _ in ()).throw(RuntimeError("fresh review required"))
    result = ConnectionWorker(researcher).cycle()
    assert result["saved"] == 0 and "fresh review required" in str(result["errors"])


def test_canonical_model_response_does_not_hide_eligible_claims(researcher):
    from workbench.research_connections import eligible_inputs
    for path in (researcher.root / "jobs").glob("*.json"):
        job = json.loads(path.read_text())
        job["source_review"]["result"]["model"] += ":latest"
        path.write_text(json.dumps(job))
    assert len(eligible_inputs(researcher, researcher.inbox.snapshot())) == 2


def test_auditor_can_reject_a_comparison_with_valid_parents(researcher):
    from workbench.research_connections import ConnectionWorker
    from workbench.research_review import review_backlog, ReviewLedger
    identifier = ConnectionWorker(researcher).cycle()["record_ids"][0]
    review = researcher.model.review_connection
    def reject(*args):
        result = review(*args)
        result["analysis"]["verdict"] = "unsupported"
        return result
    researcher.model.review_connection = reject
    result = review_backlog(researcher.project, researcher.model, record_ids=[identifier], limit=1)
    assert result["verdicts"] == {"unsupported": 1}
    assert ReviewLedger(researcher.project).excluded(researcher.inbox.snapshot()) == {identifier}


def test_original_comparison_binding_allows_an_independent_later_relation(researcher):
    from workbench.research_connections import ConnectionWorker, bound_connection

    identifier = ConnectionWorker(researcher).cycle()["record_ids"][0]
    job = json.loads(next((researcher.root / "connections").glob("*.json")).read_text())
    snapshot = researcher.inbox.snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)
    original = next(r for r in snapshot["bundle"]["relations"] if r["id"] == f"{identifier}:link:2")
    snapshot["bundle"]["relations"].append(deepcopy(original) | {
        "id": "later-comparison-overlap", "object": "q-regulation", "rationale": "A later scoped relevance assessment."})
    assert bound_connection(snapshot, job, record)[2] == job["candidate"]["analysis"]


@pytest.mark.parametrize("change", ["substituted_id", "context", "evidence", "status"])
def test_original_comparison_relations_require_exact_identity_and_content(researcher, change):
    from workbench.research_connections import ConnectionWorker, bound_connection

    identifier = ConnectionWorker(researcher).cycle()["record_ids"][0]
    job = json.loads(next((researcher.root / "connections").glob("*.json")).read_text())
    snapshot = researcher.inbox.snapshot()
    record = next(r for r in snapshot["bundle"]["items"] if r["id"] == identifier)
    original = next(r for r in snapshot["bundle"]["relations"] if r["id"] == f"{identifier}:link:0")
    if change == "substituted_id":
        original["id"] = "substituted-comparison-link"
    else:
        original[change] = {"context": {}, "evidence": [], "status": "source_reported"}[change]
    with pytest.raises(ValueError):
        bound_connection(snapshot, job, record)


def test_connector_can_compare_sources_from_disjoint_question_groups(project):
    from workbench.research_connections import ConnectionWorker, eligible_inputs

    worker = runner(project)
    worker.model = ConnectorModel()
    first = worker.cycle()["record_ids"][0]
    second = document()
    second["source"].update(id="epmc:MED:456", title="Another controlled lineage study",
                            url="https://europepmc.org/article/MED/456", citation="Other authors. 2026.")
    worker.provider.search = lambda *args, **kwargs: {"papers": [{"key": "MED:456"}], "next_cursor": None}
    worker.provider.read = lambda *args: second
    worker.question_ids = ["q-regulation"]
    other = worker.cycle()["record_ids"][0]
    worker.question_ids = None
    inputs = eligible_inputs(worker, worker.inbox.snapshot())
    assert inputs[first]["question_id"] != inputs[other]["question_id"]
    result = ConnectionWorker(worker).cycle()
    assert result["saved"] == 1, result
    job = json.loads(next((worker.root / "connections").glob("*.json")).read_text())
    assert {r["id"] for r in job["packet"]["records"]} == {first, other}
    assert len({e["source_id"] for e in job["draft"]["evidence"]}) == 2


def test_connector_uses_added_question_links_instead_of_job_ownership(researcher):
    from workbench.research_connections import ConnectionWorker, eligible_inputs

    snapshot = researcher.inbox.snapshot()
    inputs = eligible_inputs(researcher, snapshot)
    for identifier in inputs:
        original = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier)
        snapshot["bundle"]["relations"].append(deepcopy(original) | {
            "id": f"later-overlap:{identifier}", "object": "q-regulation"})
    researcher.question_ids = ["q-regulation"]
    job = ConnectionWorker(researcher)._select(snapshot, inputs)
    assert job is not None
    assert job["question"]["id"] == "q-regulation"
    assert {item["question_id"] for item in inputs.values()} == {"q-fate"}


def test_connector_bounds_the_pair_shortlist_before_building_packets(researcher, monkeypatch):
    from workbench import research_connections

    snapshot = researcher.inbox.snapshot()
    template = next(iter(research_connections.eligible_inputs(researcher, snapshot).values()))
    edge = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == template["record"]["id"])
    inputs = {}
    for index in range(40):
        item = deepcopy(template)
        identifier = f"shortlist-record-{index:02d}"
        item["record"]["id"] = identifier
        item["source"]["id"] = f"shortlist-source-{index:02d}"
        inputs[identifier] = item
        snapshot["bundle"]["items"].append(item["record"])
        snapshot["bundle"]["relations"].append(deepcopy(edge) | {
            "id": f"shortlist-edge-{index:02d}", "subject": identifier,
            "object": "q-fate" if index % 2 else "q-regulation"})
    packet_calls = []
    make = research_connections.make_packet
    def packet(items):
        packet_calls.append([item["record"]["id"] for item in items])
        return make(items)
    monkeypatch.setattr(research_connections, "make_packet", packet)
    assert research_connections.ConnectionWorker(researcher)._select(snapshot, inputs) is not None
    assert len({identifier for pair in packet_calls for identifier in pair}) <= 12
    assert len(packet_calls) <= 66


def test_connection_selection_cursor_advances_after_noop_and_restart(project):
    from workbench.research_connections import ConnectionWorker

    worker = runner(project)
    worker.cycle()
    assert ConnectionWorker(worker).cycle()["skipped"] == 1
    path = worker.root / "connection-selection.json"
    first = json.loads(path.read_text())["next_offset"]
    assert ConnectionWorker(runner(project)).cycle()["skipped"] == 1
    assert json.loads(path.read_text())["next_offset"] == first + 1


def test_connector_omits_independently_rejected_question_links(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker, eligible_inputs
    from workbench import research_graph_review

    snapshot = researcher.inbox.snapshot()
    inputs = eligible_inputs(researcher, snapshot)
    excluded = set()
    for identifier in inputs:
        original = next(r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier)
        edge_id = f"independent-link:{identifier}"
        snapshot["bundle"]["relations"].append(deepcopy(original) | {"id": edge_id, "object": "q-regulation"})
        excluded.add(edge_id)
    researcher.question_ids = ["q-regulation"]
    connector = ConnectionWorker(researcher)
    job = connector._select(snapshot, inputs)
    assert job is not None
    monkeypatch.setattr(researcher.inbox, "snapshot", lambda: snapshot)
    assert connector._still_current(job)
    monkeypatch.setattr(research_graph_review, "exclusions", lambda *args: excluded)
    assert len(eligible_inputs(researcher, snapshot)) == 2
    assert connector._select(snapshot, inputs) is None
    assert not connector._still_current(job)


@pytest.mark.parametrize("excluded_kind", ["question", "input"])
def test_connector_omits_excluded_anchors_and_inputs(researcher, monkeypatch, excluded_kind):
    from workbench.research_connections import ConnectionWorker, eligible_inputs
    from workbench import research_graph_review

    snapshot = researcher.inbox.snapshot()
    inputs = eligible_inputs(researcher, snapshot)
    connector = ConnectionWorker(researcher)
    job = connector._select(snapshot, inputs)
    excluded = {job["question"]["id"] if excluded_kind == "question" else next(iter(inputs))}
    monkeypatch.setattr(research_graph_review, "exclusions", lambda *args: excluded)
    assert connector._select(snapshot, inputs) is None
    assert not connector._still_current(job)


def test_connector_empty_agenda_is_ineligible_but_other_agenda_errors_surface(researcher, monkeypatch):
    from workbench.research_connections import ConnectionWorker, eligible_inputs

    snapshot = researcher.inbox.snapshot()
    inputs = eligible_inputs(researcher, snapshot)
    connector = ConnectionWorker(researcher)
    job = connector._select(snapshot, inputs)
    monkeypatch.setattr(researcher, "_questions", lambda *args: (_ for _ in ()).throw(
        ValueError("no active questions in the configured research views")))
    assert connector._select(snapshot, inputs) is None
    assert not connector._still_current(job)
    assert connector.cycle()["skipped"] == 1
    monkeypatch.setattr(researcher, "_questions", lambda *args: (_ for _ in ()).throw(
        ValueError("Invalid question agenda schema or version")))
    with pytest.raises(ValueError, match="Invalid question agenda"):
        connector._select(snapshot, inputs)
    with pytest.raises(ValueError, match="Invalid question agenda"):
        connector._still_current(job)
