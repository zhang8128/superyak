"""Resumable paper jobs that capture sourced, proposed research claims."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote
import uuid

from .automation import MAX_DRAFTS, ResearchInbox, _directory, _now, _read, _save
from .render import write_rendered_bundle
from .research_model import AnalysisValidationError
from .validation import WorkbenchError


ERRORS = (ValueError, RuntimeError, OSError, WorkbenchError, KeyError, TypeError)
ANALYSIS_FIELDS = {"relevant", "title", "summary", "scope", "limitations", "passage_id", "quote", "rationale"}


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _publication_ids(source):
    from .research_reuse import publication_ids
    return publication_ids(source)


def validate_analysis(result, document):
    analysis = result.get("analysis")
    if not isinstance(analysis, dict) or type(analysis.get("relevant")) is not bool:
        raise ValueError("model relevance must be boolean")
    if set(analysis) - ANALYSIS_FIELDS:
        raise ValueError("unknown model analysis fields")
    if not analysis["relevant"]:
        return None
    if set(analysis) != ANALYSIS_FIELDS:
        raise ValueError("incomplete model analysis")
    for key, value in analysis.items():
        if key != "relevant" and (not isinstance(value, str) or not value.strip() or len(value) > 4000):
            raise ValueError(f"invalid model analysis field: {key}")
    passages = {p["id"]: p for p in document["passages"]}
    passage = passages.get(analysis["passage_id"])
    quote = analysis["quote"]
    if passage is None or quote not in passage["text"] or not 4 <= len(quote.split()) <= 25:
        raise ValueError("model quote must match 4–25 words in the selected retrieved passage")
    return analysis, passage


def prepare_draft(job, question, snapshot, extracted):
    analysis, passage = extracted
    document = job["document"]
    source = document["source"]
    identifiers = _publication_ids(source)
    if job["paper"].get("doi"):
        identifiers.add("doi:" + job["paper"]["doi"].casefold())
    if job["paper"].get("provider_source") == "MED":
        identifiers.add("pmid:" + job["paper"]["provider_id"])
    existing_sources = snapshot["bundle"]["sources"]
    exact = next((existing for existing in existing_sources if existing["id"] == source["id"]), None)
    source = exact or next((existing for existing in existing_sources
                            if identifiers & _publication_ids(existing)), source)
    review = job.get("source_review")
    annotations = ({
        "source_support": "supported",
        "source_review_revision": review["revision"],
        "source_review_model": review["result"]["model"],
        "source_review_reason": review["result"]["analysis"]["reason"],
        "source_review_input_digest": review["input_digest"],
    } if review else {})
    return {
        "idempotency_key": "paper-job:" + job["id"], "kind": "claim",
        "title": analysis["title"], "summary": analysis["summary"],
        "views": sorted(name for name, ids in snapshot["views"].items() if question["id"] in ids),
        "context": {
            "scope": analysis["scope"], "limitations": analysis["limitations"],
            "source_coverage": document["coverage"], "source_retrieved_at": document["retrieved_at"],
            "source_coverage_note": document.get("coverage_note", document["coverage"]),
            "source_content_sha256": document["content_sha256"],
            "source_document": document["document_url"], "model": job["extraction"]["model"],
            **({"prompt_context_mode": "dynamic",
                "prompt_passage_ids": json.dumps(job["extraction"]["context_manifest"]["selected_passage_ids"]),
                "prompt_omitted_passages": str(job["extraction"]["context_manifest"]["omitted_passages"])}
               if job["extraction"].get("context_manifest") else {}),
            **annotations,
            "assessment": "Automated extraction and separate source-support check; not independent scientific review.",
        },
        "facets": question["facets"], "sources": [source],
        "evidence": [{"source_id": source["id"], "locator": passage["locator"],
                      "note": f"Retrieved passage: “{analysis['quote']}”. {analysis['rationale']}"}],
        "links": [{"predicate": "informs", "target": question["id"], "rationale": analysis["rationale"]}],
    }


class ResearchRunner:
    """Own job persistence; the service owns single-worker locking and cadence."""

    def __init__(self, project, *, provider, model, question_ids=None, should_stop=lambda: False,
                 progress=lambda **values: None, batch_size=3):
        self.inbox = ResearchInbox(project)
        self.project = self.inbox.project
        self.root = self.project / ".atlas/research"
        for directory in (self.project / ".atlas", self.root, self.root / "jobs"):
            _directory(directory)
        self.provider, self.model = provider, model
        self.question_ids = question_ids
        self.should_stop, self.progress = should_stop, progress
        if type(batch_size) is not int or not 1 <= batch_size <= 5:
            raise ValueError("batch_size must be between 1 and 5")
        self.batch_size = batch_size
        identity_file = self.root / "identity.json"
        if not identity_file.exists():
            _save(identity_file, {"session_id": "ollama-research:" + str(uuid.uuid4()), "created_at": _now()})
        self.session_id = _read(identity_file)["session_id"]
        self.state_file = self.root / "frontier.json"
        self.state = _read(self.state_file) if self.state_file.exists() else {
            "version": 1, "next_question": 0, "frontiers": {}}
        if self.state.get("version") != 1:
            raise ValueError("unsupported research frontier version")

    def _checkpoint(self):
        _save(self.state_file, self.state, replace=True)

    def _questions(self, snapshot):
        from .research_agenda import QuestionAgenda
        from .research_graph_review import exclusions
        return QuestionAgenda(self.project).eligible(snapshot, self.question_ids,
            excluded_ids=exclusions(self.project, snapshot))

    def _context(self, question, snapshot, query=""):
        from .research_context import select_context
        from .research_graph_review import exclusions
        excluded = exclusions(self.project, snapshot)
        filtered = snapshot | {"bundle": snapshot["bundle"] | {
            "items": [r for r in snapshot["bundle"]["items"] if r["id"] not in excluded],
            "relations": [r for r in snapshot["bundle"]["relations"]
                          if r["id"] not in excluded and r["subject"] not in excluded and r["object"] not in excluded]}}
        return select_context(filtered, question, query=query)

    def _fill(self, question, frontier, context):
        if not frontier.get("query") or frontier.get("cursor") is None:
            self.progress(phase="planning", question=question["title"])
            query = self.model.plan(question, context, frontier.get("queries", [])[-8:])
            if not isinstance(query, str) or not query.strip() or len(query) > 1000:
                raise ValueError("model search query must be nonblank and at most 1000 characters")
            frontier.update(query=query, cursor="*")
            frontier["plan_context"] = getattr(self.model, "last_context_manifest", None)
            frontier.setdefault("queries", []).append(query)
            frontier["queries"] = frontier["queries"][-20:]
            self._checkpoint()
        if self.should_stop():
            return
        self.progress(phase="searching", query=frontier["query"], question=question["title"])
        page = self.provider.search(frontier["query"], cursor=frontier["cursor"], limit=5)
        frontier["skipped_metadata"] = page.get("skipped", [])
        for paper in page["papers"]:
            if not isinstance(paper.get("key"), str) or not paper["key"].strip():
                raise ValueError("retrieved paper lacks stable identity")
            id_ = _key({"question": question["id"], "paper": paper["key"]})
            path = self.root / "jobs" / f"{id_}.json"
            if path.exists():
                job = _read(path)
                if job["status"] in {"recorded", "linked", "skipped", "failed", "held"}:
                    continue
            else:
                from .research_reuse import cached_document
                job = {"version": 1, "id": id_, "question_id": question["id"],
                       "paper": paper, "query": frontier["query"], "status": "pending",
                       "attempts": 0, "created_at": _now()}
                if cached := cached_document(self, paper):
                    job.update(document=cached[0], document_reused_from=cached[1])
                _save(path, job)
            if id_ not in frontier["pending"]:
                frontier["pending"].append(id_)
        frontier["cursor"] = page["next_cursor"]
        self._checkpoint()

    def _recover_failed(self, question, frontier):
        revision = getattr(self.model, "analysis_revision", None)
        if not revision:
            return
        for path in sorted((self.root / "jobs").glob("*.json")):
            job = _read(path)
            attempted = {job.get("analysis_revision")}
            for recovery in job.get("recoveries", []):
                attempted.update((recovery.get("analysis_revision"), recovery.get("previous_revision")))
            if (job["question_id"] != question["id"] or job["status"] != "failed"
                    or "draft" in job or revision in attempted):
                continue
            if (job.get("last_error_kind") != "invalid_analysis"
                    and not job.get("last_error", "").startswith(("analysis quote ", "model quote "))):
                continue
            job.setdefault("recoveries", []).append({
                "analysis_revision": revision, "previous_revision": job.get("analysis_revision"),
                "previous_attempts": job["attempts"], "previous_error": job["last_error"],
                "recovered_at": _now(),
            })
            job.update(status="retry", generation_attempts=0, analysis_revision=revision)
            # Retain the original job, submission identity, and rejection history.
            # Queue first so a crash before the job save can be retried safely.
            if job["id"] not in frontier["pending"]:
                frontier["pending"].append(job["id"])
                self._checkpoint()
            _save(path, job, replace=True)
            self.progress(phase="recovering", paper=job["paper"].get("title", job["id"]))

    def _process(self, id_, question, snapshot, context, result):
        path = self.root / "jobs" / f"{id_}.json"
        job = _read(path)
        if job["status"] in {"recorded", "linked", "skipped", "failed", "held"}:
            return True
        try:
            from .research_reuse import cached_document, resume_reuse, reuse_claim
            if "reuse" in job:
                return resume_reuse(self, job, result)
            if "document" not in job:
                if cached := cached_document(self, job["paper"]):
                    job.update(document=cached[0], document_reused_from=cached[1])
                else:
                    self.progress(phase="reading", paper=job["paper"].get("title", job["paper"]["key"]))
                    job["document"] = self.provider.read(job["paper"])
                _save(path, job, replace=True)
            if self.should_stop():
                return False
            already_captured = "draft" in job and (self.inbox.state / "drafts" /
                (self.inbox._identifier(self.session_id, job["draft"]["idempotency_key"]) + ".json")).exists()
            if not already_captured:
                snapshot = self.inbox.snapshot()
                active = {item["id"]: item for item in self._questions(snapshot)}
                if question["id"] not in active:
                    raise ValueError("The research question is no longer active in its configured views")
                question = active[question["id"]]
                context = self._context(question, snapshot, query=job["document"]["source"]["title"])
                if "draft" not in job and not job.get("candidate_validated"):
                    self.progress(phase="analyzing", paper=job["document"]["source"]["title"])
                    # Invalid extractions may be regenerated; review retries keep the candidate.
                    feedback = {}
                    if revision := getattr(self.model, "analysis_revision", None):
                        job["analysis_revision"] = revision
                        if job.get("rejected_extractions"):
                            feedback["previous_rejection"] = job["rejected_extractions"][-1]
                    job["extraction"] = self.model.extract(question, job["document"], context, **feedback)
                    _save(path, job, replace=True)
                try:
                    extracted = validate_analysis(job["extraction"], job["document"])
                except ValueError as error:
                    raise AnalysisValidationError(str(error), job["extraction"]) from error
                if extracted is None:
                    job.update(status="skipped", completed_at=_now())
                    _save(path, job, replace=True)
                    result["skipped"] += 1
                    return True
                job["candidate_validated"] = True
                _save(path, job, replace=True)
                if "draft" in job:
                    from .research_review import assert_same_draft
                    assert_same_draft(job["draft"], prepare_draft(job, question, snapshot, extracted))
                if self.should_stop():
                    return False
                from .research_review import assess
                self.progress(phase="reviewing", paper=job["document"]["source"]["title"])
                job["source_review"] = assess(self.model, question, job["document"],
                                              extracted[0], job.get("source_review"))
                _save(path, job, replace=True)
                if job["source_review"]["result"]["analysis"]["verdict"] != "supported":
                    job.update(status="held", completed_at=_now())
                    _save(path, job, replace=True)
                    result["held"] += 1
                    return True
                if "draft" not in job:
                    reused = reuse_claim(self, job, question, snapshot, extracted[0], result)
                    if reused is not None:
                        return reused
                    job["draft"] = prepare_draft(job, question, snapshot, extracted)
                    _save(path, job, replace=True)  # Persist exact submission before capture.
            if self.should_stop():
                return False
            self.progress(phase="recording", paper=job["document"]["source"]["title"])
            receipt = self.inbox.record(job["draft"], self.session_id)
            job.update(receipt=receipt, status="recorded", completed_at=_now())
            _save(path, job, replace=True)
            result["replayed" if receipt["duplicate"] else "saved"] += 1
            result["record_ids"].append(receipt["record_id"])
            if receipt["publication_status"] != "current":
                result["errors"].append({"job": id_, "error": receipt["error"], "recorded": True})
            return True
        except ERRORS as error:
            from .research_review import SourceReviewError
            job.setdefault("generation_attempts", job["attempts"])
            job["attempts"] += 1
            if isinstance(error, AnalysisValidationError):
                job.setdefault("rejected_extractions", []).append({
                    "attempt": job["attempts"], "error": str(error), "result": error.result,
                })
            if isinstance(error, SourceReviewError):
                job.setdefault("rejected_reviews", []).append({
                    "attempt": job["attempts"], "error": str(error), "result": error.result,
                })
            # Outages and prepared submissions remain recoverable, including a
            # capture whose response/receipt was lost. Only invalid retrieved
            # data/model answers exhaust their local generation attempts.
            invalid = isinstance(error, SourceReviewError) or (isinstance(error, ValueError) and "draft" not in job)
            if invalid:
                job["generation_attempts"] += 1
            job.update(status="failed" if invalid and job["generation_attempts"] >= 3 else "retry",
                       last_error=str(error), updated_at=_now(),
                       last_error_kind="invalid_review" if isinstance(error, SourceReviewError) else
                       "invalid_analysis" if isinstance(error, AnalysisValidationError) else "operational")
            _save(path, job, replace=True)
            result["errors"].append({"job": id_, "error": str(error), "attempts": job["attempts"],
                                    **({"kind": "invalid_review"} if isinstance(error, SourceReviewError) else
                                       {"kind": "invalid_analysis"} if isinstance(error, AnalysisValidationError) else {})})
            return job["status"] == "failed"

    def _publish_browser(self):
        manifest = self.inbox.refresh()
        bundle_path = self.project / ".atlas/publications" / manifest["generation"] / "bundle.json"
        write_rendered_bundle(_read(bundle_path), self.root / "index.html", self.root / "unused.db")
        return manifest

    def _recover_captures(self, snapshot, result):
        """Recover saved submissions before requiring space or an active question."""
        pending = []
        for path in sorted((self.root / "jobs").glob("*.json")):
            job = _read(path)
            if job["status"] not in {"pending", "retry"}:
                continue
            captured = "draft" in job and (self.inbox.state / "drafts" /
                (self.inbox._identifier(self.session_id, job["draft"]["idempotency_key"]) + ".json")).exists()
            graph_id = job.get("reuse", {}).get("graph_job_id")
            graph_path = self.root / "graph-jobs" / (str(graph_id) + ".json")
            prepared_graph = bool(graph_id and graph_path.exists() and "proposal" in _read(graph_path))
            if captured or prepared_graph:
                pending.append(job)
        records = {item["id"]: item for item in snapshot["bundle"]["items"]}
        for job in sorted(pending, key=lambda row: (row["created_at"], row["id"]))[:self.batch_size]:
            if self.should_stop():
                break
            question = records.get(job["question_id"], {"id": job["question_id"]})
            result.setdefault("question_id", job["question_id"])
            if self._process(job["id"], question, snapshot, {}, result):
                frontier = self.state["frontiers"].get(job["question_id"], {})
                if job["id"] in frontier.get("pending", []):
                    frontier["pending"].remove(job["id"])
                    self._checkpoint()
        return bool(pending)

    def cycle(self):
        started = time.monotonic()
        result = {"saved": 0, "replayed": 0, "skipped": 0, "held": 0, "errors": [], "record_ids": [],
                  "publication_status": "pending", "live_graph": str(self.root / "index.html")}
        try:
            snapshot = self.inbox.snapshot()
            at_capacity = sum(item["provenance"].get("capture") in {"session_draft", "graph_draft"}
                              for item in snapshot["bundle"]["items"]) >= MAX_DRAFTS
            if not self._recover_captures(snapshot, result):
                questions = self._questions(snapshot)
                question = questions[0]
                result["question_id"] = question["id"]
                frontier = self.state["frontiers"].setdefault(question["id"], {"pending": []})
                context = self._context(question, snapshot)
                if not self.should_stop() and not at_capacity:
                    self._recover_failed(question, frontier)
                if not self.should_stop() and not at_capacity and not frontier["pending"]:
                    self._fill(question, frontier, context)
                for id_ in list(frontier["pending"])[:self.batch_size]:
                    if self.should_stop():
                        break
                    if at_capacity and "draft" not in _read(self.root / "jobs" / f"{id_}.json"):
                        continue
                    if self._process(id_, question, snapshot, context, result):
                        frontier["pending"].remove(id_)
                        self._checkpoint()
                self.state["next_question"] += 1
                self._checkpoint()
                if not self.should_stop() and not at_capacity:
                    from .research_agenda import QuestionAgenda
                    QuestionAgenda(self.project).researched(question["id"])
                if at_capacity:
                    result["errors"].append({"error": "Research inbox is at capacity; new analysis is paused, saved publications can still recover"})
        except ERRORS as error:
            if str(error) == "no active questions in the configured research views":
                result.update(skipped=result["skipped"] + 1, reason=str(error))
            else:
                result["errors"].append({"error": str(error)})
        if not self.should_stop():
            try:
                self.progress(phase="publishing")
                manifest = self._publish_browser()
                result.update(publication_status="current", generation=manifest["generation"],
                              draft_count=manifest["draft_count"], research_views=manifest["research_views"])
            except ERRORS as error:
                result["errors"].append({"error": str(error)})
        result["seconds"] = round(time.monotonic() - started, 2)
        from .research_graph_work import agenda_status
        result["question_agenda"] = agenda_status(self, self.inbox.snapshot())
        return result
