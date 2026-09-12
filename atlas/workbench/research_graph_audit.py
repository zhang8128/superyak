"""Fresh audits of captured graph additions, independent of original source audits."""

from copy import deepcopy
import re

from .automation import _directory, _read, _save
from .research_evidence import make_packet
from .research_graph import compose_graph, graph_digest, normalize_proposal
from .research_graph_model import (REVISION, normalize_overlap_candidate, validate_overlap, validate_overlap_review,
                                   validate_question, validate_question_review)
from .research_graph_review import GraphReviewLedger, exclusions
from .research_graph_work import evidence, graph_inputs, nearby_questions
from .validation import WorkbenchError, normalize_bundle


AUDIT_REVISION = "graph-audit-v2"
MAX_INVALID_ATTEMPTS = 3


def _packet_for(packet, identifiers):
    """Keep each source's original passage IDs when selecting one relationship."""
    sources = [deepcopy(s) for s in packet["sources"] if s["record_id"] in identifiers]
    passage_ids = {identifier for source in sources for identifier in source["passage_ids"]}
    return {"records": [deepcopy(r) for r in packet["records"] if r["id"] in identifiers],
            "sources": sources, "document": deepcopy(packet["document"]) | {
                "passages": [deepcopy(p) for p in packet["document"]["passages"] if p["id"] in passage_ids]}}


def _same_source_packet(original, current):
    # make_packet assigns positional IDs. A one-record audit may preserve s2:
    # while the same current source alone would be assigned s1:.
    if original["records"] != current["records"] or len(original["sources"]) != len(current["sources"]):
        return False
    old_passages = {p["id"]: p for p in original["document"]["passages"]}
    new_passages = {p["id"]: p for p in current["document"]["passages"]}
    for old, new in zip(original["sources"], current["sources"]):
        if {k: v for k, v in old.items() if k != "passage_ids"} != {k: v for k, v in new.items() if k != "passage_ids"}:
            return False
        before = [{k: v for k, v in old_passages[p].items() if k != "id"} for p in old["passage_ids"]]
        after = [{k: v for k, v in new_passages[p].items() if k != "id"} for p in new["passage_ids"]]
        if before != after:
            return False
    return original["document"]["coverage"] == current["document"]["coverage"]


def _bind_job(research, snapshot, record, entry):
    context = record["context"]
    job_id = context.get("graph_job_id", "")
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{64}", job_id):
        raise ValueError("Graph record lacks a valid captured job identity")
    job = _read(research.root / "graph-jobs" / (job_id + ".json"))
    if job["id"] != job_id or job["role"] not in {"question", "overlap"}:
        raise ValueError("Graph job identity or role changed")
    if normalize_proposal(job["proposal"], snapshot["views"]) != entry["proposal"]:
        raise ValueError("Graph job proposal differs from its immutable capture")
    captured = entry["proposal"]["context"]
    if ("record_kinds" in job) != ("record_kinds_digest" in captured):
        raise ValueError("Graph record kind binding changed from its immutable capture")
    values = {"candidate": job["candidate"], "review": job["review"], "packet": job["packet"],
              "anchor": job["question"], "questions": job.get("questions", []), "views": job.get("views", [])}
    if "record_kinds" in job:
        values["record_kinds"] = job["record_kinds"]
    if any(captured.get(name + "_digest") != graph_digest(value) for name, value in values.items()):
        raise ValueError("Graph job candidate, review, packet, or question binding changed")
    if (captured.get("worker_role") != job["role"] or captured.get("graph_job_id") != job_id
            or captured.get("worker_revision") != job["revision"]):
        raise ValueError("Graph job capture context changed")
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    packet_ids = {r["id"] for r in job["packet"]["records"]}
    if "record_kinds" in job:
        record_kinds = job["record_kinds"]
        if not isinstance(record_kinds, dict) or set(record_kinds) != packet_ids:
            raise ValueError("Graph record kind map does not cover its captured packet")
    else:
        from .research_graph_model import LEGACY_PREDICATES
        old_kinds = {r["subject"]: kind for r in entry["proposal"]["relations"]
                     for kind, predicate in LEGACY_PREDICATES.items() if r["predicate"] == predicate}
        record_kinds = {identifier: old_kinds.get(identifier, records.get(identifier, {}).get("kind", "claim"))
                        for identifier in packet_ids}
    # The immutable map describes the original request. _review_input checks
    # current full record digests only for this edge's actual dependencies.
    legacy = job["revision"] in {"question-overlap-v1", "question-overlap-v2"}
    # Rebuild the exact saved graph addition to bind question and relation
    # fields, independently of the mutable worker receipt.
    question_id = entry["id"] + ":question"
    original = deepcopy(snapshot["bundle"])
    original["items"] = [r for r in original["items"] if r["id"] != question_id]
    original["relations"] = []
    profiles = {name: {"item_ids": []} for name in snapshot["views"]}
    compose_graph(original, profiles, [entry])
    originals = normalize_bundle(original)
    expected = {r["id"]: r for kind in ("items", "relations") for r in originals[kind]}
    if expected.get(record["id"]) != record:
        raise ValueError("Current graph record differs from its immutable capture")
    candidate = job["candidate"]["analysis"]
    if job["role"] == "question":
        if not validate_question(candidate, job["packet"], job["questions"], job["views"]):
            raise ValueError("Captured question lacks a valid grounded candidate")
        legacy_question = job["revision"] == "question-overlap-v1"
        reviewed = validate_question_review(job["review"], job["packet"], candidate, job["questions"], legacy=legacy_question)
        if reviewed["verdict"] != "useful" or any(r["verdict"] != "supported" for r in reviewed.get("relations", [])):
            raise ValueError("Captured question was not accepted by its bound initial review")
        from .research_questions import _reviewed_relations
        if entry["proposal"]["relations"] != _reviewed_relations(candidate, reviewed, job["packet"],
                premise_predicate="informs" if legacy else "raises_question", legacy=legacy_question):
            raise ValueError("Captured question links differ from their individual source review decisions")
    else:
        if not validate_overlap(candidate, job["packet"], legacy=legacy, record_kinds=record_kinds):
            raise ValueError("Captured overlap has no valid links")
        decisions = validate_overlap_review(job["review"], job["packet"], candidate,
                                            legacy=legacy, record_kinds=record_kinds)
        if not any(d["record_id"] == record["subject"] and d["predicate"] == record["predicate"]
                   and d["verdict"] == "supported" for d in decisions):
            raise ValueError("Captured overlap link lacks its accepted initial review")
        links = normalize_overlap_candidate(candidate, record_kinds)["links"]
        link = next(link for link in links if link["record_id"] == record["subject"])
        decision = next(d for d in decisions if d["record_id"] == record["subject"])
        if (record["object"] != job["question"]["id"] or record["predicate"] != link["predicate"]
                or record["rationale"] != link["rationale"] or record["evidence"] != evidence(link["evidence"], job["packet"])
                or record["context"].get("review_verdict") != decision["verdict"]
                or record["context"].get("review_reason") != decision["reason"]
                or any(record["context"].get(field, "") != link[field] for field in ("answer_scope", "remaining"))):
            raise ValueError("Captured overlap differs from its exact predicate, scope, or source review")
    return job


def _review_input(research, snapshot, record, entry, job, inputs, excluded):
    records = {r["id"]: r for r in snapshot["bundle"]["items"]}
    sources = {r["id"]: r for r in snapshot["bundle"]["sources"]}
    candidate = deepcopy(job["candidate"]["analysis"])
    if job["role"] == "overlap":
        links = [link for link in candidate["links"] if link["record_id"] == record["subject"]]
        if len(links) != 1 or record["object"] != job["question"]["id"]:
            raise ValueError("Captured edge does not match its reviewed overlap candidate")
        candidate = {"links": links, "reason": candidate["reason"]}
        premise_ids = [record["subject"]]
        question_ids = [record["object"]]
    else:
        if record.get("predicate") in {"informs", "raises_question"}:
            premise_ids = [record["subject"]]
            candidate["premises"] = premise_ids
        else:
            premise_ids = candidate["premises"]
        if record.get("predicate") == "part_of":
            candidate["parents"] = [record["object"]]
        question_ids = [*candidate["parents"], job["question"]["id"]]
    packet = _packet_for(job["packet"], set(premise_ids))
    if any(identifier not in inputs for identifier in premise_ids):
        raise ValueError("Graph premise lost current source-support eligibility")
    ordered_ids = [r["id"] for r in packet["records"]]
    if not _same_source_packet(packet, make_packet([inputs[identifier] for identifier in ordered_ids])):
        raise ValueError("Graph source passages or their attribution changed")
    wanted = set(premise_ids) | set(question_ids)
    wanted.update(s["id"] for s in packet["sources"])
    expected = entry["proposal"]["expected"]
    for identifier in wanted:
        current = records.get(identifier, sources.get(identifier))
        if current is None or expected.get(identifier) != graph_digest(current):
            raise ValueError(f"Stale graph input: {identifier}")
        if identifier in excluded or current.get("status") == "withdrawn":
            raise ValueError(f"Graph input lost current eligibility: {identifier}")
    if job["role"] == "question":
        passage_ids = {p["id"] for p in packet["document"]["passages"]}
        candidate["evidence"] = [e for e in candidate["evidence"] if e["passage_id"] in passage_ids]
        question_id = entry["id"] + ":question"
        questions = [q for q in nearby_questions(research, snapshot, candidate["title"], maximum=13)
                     if q["id"] != question_id][:12]
        # Every captured parent remains explicit even if lexical retrieval puts
        # it outside the first comparison page.
        present = {q["id"] for q in questions}
        questions.extend({"id": identifier, "title": records[identifier]["title"],
                          "summary": records[identifier]["summary"], "eligible_parent": True}
                         for identifier in candidate["parents"] if identifier not in present)
    else:
        questions = []
    return packet, candidate, questions


def _state(research, snapshot, record, entry, inputs, excluded):
    job, prepared, invalid = None, None, None
    try:
        if entry is None:
            raise ValueError("Graph record has no immutable capture")
        job = _bind_job(research, snapshot, record, entry)
        prepared = _review_input(research, snapshot, record, entry, job, inputs, excluded)
    except (ValueError, WorkbenchError, OSError, KeyError, TypeError) as error:
        invalid = str(error)
    return job, prepared, invalid


def _binding(research, record, entry, state):
    job, prepared, invalid = state
    return graph_digest({"revision": AUDIT_REVISION, "model_revision": REVISION,
                         "model": research.model.model, "record": record,
                         "capture": entry.get("capture_digest") if entry else None,
                         "job": job, "prepared": list(prepared) if prepared is not None else None, "invalid": invalid})


def audit_graph(research, *, limit=1):
    """Review at most ``limit`` additions; outages never become scientific verdicts."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Graph audit limit must be between one and 1000")
    result = {"reviewed": 0, "held": 0, "errors": [], "record_ids": [], "verdicts": {}}
    if research.should_stop():
        return result
    snapshot = research.inbox.snapshot()
    entries = {entry["id"]: entry for entry in research.inbox._graph_entries(snapshot["views"])}
    ledger = GraphReviewLedger(research.project)
    prior = ledger.current(snapshot)
    inputs, excluded = graph_inputs(research, snapshot), exclusions(research.project, snapshot)
    records = [r for kind in ("items", "relations") for r in snapshot["bundle"][kind]
               if r["context"].get("graph_job_id") and
               r.get("provenance", r["context"]).get("capture") == "graph_draft"]
    records.sort(key=lambda r: (r.get("provenance", r["context"]).get("recorded_at", ""),
                                "predicate" in r, r["id"]))
    attempted = 0
    retry_root = research.root / "graph-audits"
    if retry_root.is_symlink():
        raise ValueError("Graph audit state cannot be a symlink")
    for record in records:
        if attempted >= limit or research.should_stop():
            break
        captured = record.get("provenance", record["context"])
        entry = entries.get(captured.get("graph_draft_id"))
        job, prepared, invalid = _state(research, snapshot, record, entry, inputs, excluded)
        # Include the current relevant packet or binding failure, not unrelated
        # siblings' support. An assessment remains reusable after another edge
        # of the same batch is rejected.
        binding = _binding(research, record, entry, (job, prepared, invalid))
        previous = prior.get(record["id"], {})
        if previous.get("stage") == "audit" and previous.get("result", {}).get("audit_input_digest") == binding:
            continue
        retry_path = retry_root / (binding + ".json")
        attempts = _read(retry_path).get("invalid_attempts", 0) if retry_path.exists() else 0
        if attempts >= MAX_INVALID_ATTEMPTS:
            continue
        attempted += 1
        research.progress(phase="auditing_graph", question=record.get("title", record["object"] if "object" in record else ""))
        if invalid is not None:
            assessment = {"analysis": {"verdict": "uncertain", "reason": invalid, "evidence": []},
                          "model": research.model.model, "audit_input_digest": binding, "input_invalid": True}
            verdict, reason = "uncertain", invalid
        else:
            packet, candidate, questions = prepared
            try:
                if job["role"] == "question":
                    arguments = {"premise_predicate": "informs"} if job["revision"] in {
                        "question-overlap-v1", "question-overlap-v2"} else {}
                    assessment = research.model.review_question(job["question"], packet, candidate, questions, job["views"], **arguments)
                    decision = validate_question_review(assessment, packet, candidate, questions)
                    verdict = {"useful": "supported", "duplicate": "uncertain"}.get(decision["verdict"], decision["verdict"])
                    if decision["verdict"] == "useful":
                        if "predicate" in record:
                            kind, identifier = (("parent", record["object"]) if record["predicate"] == "part_of"
                                                else ("premise", record["subject"]))
                            decision = next(r for r in decision["relations"] if (r["kind"], r["record_id"]) == (kind, identifier))
                            verdict = decision["verdict"]
                        else:
                            rejected = [r for r in decision["relations"] if r["kind"] == "premise" and r["verdict"] != "supported"]
                            if rejected:
                                decision = next((r for r in rejected if r["verdict"] == "unsupported"), rejected[0])
                                verdict = decision["verdict"]
                else:
                    kinds = job.get("record_kinds") or {identifier: inputs[identifier]["record"]["kind"]
                                                        for identifier in (r["id"] for r in packet["records"])}
                    candidate = normalize_overlap_candidate(candidate, kinds)
                    assessment = research.model.review_overlap(job["question"], packet, candidate)
                    decision, = validate_overlap_review(assessment, packet, candidate, record_kinds=kinds)
                    verdict = decision["verdict"]
                reason = decision["reason"]
                assessment = assessment | {"audit_input_digest": binding}
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
                malformed = isinstance(error, (ValueError, KeyError, TypeError))
                _directory(retry_root)
                _save(retry_path, {"version": 1, "binding": binding, "record_id": record["id"],
                                   "invalid_attempts": attempts + int(malformed), "last_error": str(error)}, replace=True)
                result["errors"].append({"record_id": record["id"], "error": str(error),
                                         "kind": "invalid_review" if malformed else "operational",
                                         "input_digest": binding,
                                         "exhausted": malformed and attempts + 1 >= MAX_INVALID_ATTEMPTS})
                continue
        if research.should_stop():
            break
        try:
            with research.inbox._lock():
                current_snapshot = research.inbox.snapshot()
                current_record = next((r for kind in ("items", "relations") for r in current_snapshot["bundle"][kind]
                                       if r["id"] == record["id"]), None)
                if current_record is None:
                    raise ValueError("Graph record disappeared before its audit was saved")
                current_state = _state(research, current_snapshot, current_record, entry,
                                       graph_inputs(research, current_snapshot), exclusions(research.project, current_snapshot))
                current_binding = _binding(research, current_record, entry, current_state)
                if current_binding != binding:
                    reason = current_state[2] or "Graph audit inputs changed during model review; reassess fresh inputs"
                    verdict = "uncertain"
                    assessment = {"analysis": {"verdict": verdict, "reason": reason, "evidence": []},
                                  "model": research.model.model,
                                  "audit_input_digest": current_binding if current_state[2] else binding,
                                  "input_invalid": True}
                ledger.store(current_record, assessment, model=research.model.model, stage="audit", verdict=verdict, reason=reason)
        except (ValueError, WorkbenchError, OSError, KeyError, TypeError) as error:
            result["errors"].append({"record_id": record["id"], "error": str(error), "kind": "operational"})
            continue
        result["reviewed"] += 1
        result["held"] += verdict != "supported"
        result["record_ids"].append(record["id"])
        result["verdicts"][verdict] = result["verdicts"].get(verdict, 0) + 1
    return result
