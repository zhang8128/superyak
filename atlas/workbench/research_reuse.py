"""Reuse cached publications and link already captured, scoped assertions."""

from copy import deepcopy
import re
from urllib.parse import unquote

from .automation import _now, _read, _save
from .research_evidence import eligible_inputs, question_links
from .validation import CLAIM_QUESTION_PREDICATES


TERMINAL = {"linked", "recorded", "held", "skipped", "failed"}


def publication_ids(value):
    """Resolve provider aliases without equating papers by their titles."""
    identities = set()
    url = value.get("url", "").rstrip("/")
    if url:
        identities.add("url:" + url)
    text = unquote(" ".join(str(value.get(key) or "") for key in ("url", "citation", "doi", "key")))
    for doi in re.findall(r"10\.\d{4,9}/[^\s<>\"?#]+", text, re.IGNORECASE):
        identities.add("doi:" + doi.rstrip(".,;)").casefold())
    for pattern in (r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", r"europepmc\.org/article/MED/(\d+)"):
        if match := re.search(pattern, url, re.IGNORECASE):
            identities.add("pmid:" + match[1])
    for pmcid in re.findall(r"\bPMC\d+\b", " ".join((url, value.get("pmcid", ""), value.get("key", ""))), re.IGNORECASE):
        identities.add("pmcid:" + pmcid.upper())
    provider, identifier = value.get("provider_source"), value.get("provider_id", value.get("id"))
    if provider == "MED" and str(identifier).isdigit():
        identities.add("pmid:" + str(identifier))
    if key := value.get("key"):
        identities.add("provider-key:" + key)
        if match := re.fullmatch(r"(?:europepmc:)?MED:(\d+)", key, re.IGNORECASE):
            identities.add("pmid:" + match[1])
    if isinstance(value.get("source"), dict):
        identities.update(publication_ids(value["source"]))
    return identities


def _jobs(research):
    return (_read(path) for path in sorted((research.root / "jobs").glob("*.json")))


def _job_publications(job):
    return publication_ids(job["paper"]) | publication_ids(job.get("document", {}).get("source", {}))


def cached_document(research, paper):
    """Return the original complete cached document and its owning read job."""
    identities = publication_ids(paper)
    for job in _jobs(research):
        if "document" in job and identities & _job_publications(job):
            return deepcopy(job["document"]), job.get("document_reused_from", job["id"])
    return None


def _assertion(candidate):
    # Case and punctuation can distinguish biological assertions; normalize only space.
    return tuple(" ".join(candidate[key].split()) for key in ("summary", "scope", "quote"))


def matching_claim(research, snapshot, job, candidate):
    """Match one original supported claim, never a publication alone."""
    from .research_graph_review import exclusions
    inputs = eligible_inputs(research, snapshot)
    rejected = exclusions(research.project, snapshot)
    identities, assertion = _job_publications(job), _assertion(candidate)
    for original in _jobs(research):
        identifier = original.get("receipt", {}).get("record_id")
        if (original.get("status") == "recorded" and identifier in inputs and identifier not in rejected
                and identities & _job_publications(original)
                and _assertion(original["extraction"]["analysis"]) == assertion):
            return inputs[identifier]
    return None


def _save_job(research, job):
    _save(research.root / "jobs" / (job["id"] + ".json"), job, replace=True)


def resume_reuse(research, job, result):
    """Resume the same graph submission, including a captured but lost receipt."""
    from .research_overlap import OverlapWorker
    worker = OverlapWorker(research)
    reuse = job["reuse"]
    graph = _read(worker.root / (reuse["graph_job_id"] + ".json"))
    if (graph["role"] != "overlap" or graph["question"]["id"] != job["question_id"]
            or [r["id"] for r in graph["packet"]["records"]] != [reuse["record_id"]]):
        raise ValueError("Claim reuse job does not match its saved question and finding")
    outcome = worker.run(graph) if graph["status"] not in {"held", "failed", "skipped"} else {
        "errors": [], "held": int(graph["status"] == "held"), "skipped": int(graph["status"] == "skipped")}
    job["status"] = "linked" if graph["status"] == "recorded" else graph["status"]
    job["attempts"] = graph["attempts"]
    if "receipt" in graph:
        # A graph receipt has record_ids/relation_ids, never the original record_id.
        job["receipt"] = deepcopy(graph["receipt"])
    if graph.get("last_error"):
        job["last_error"] = graph["last_error"]
    if job["status"] in TERMINAL:
        job["completed_at"] = _now()
    _save_job(research, job)
    for key in ("links_added", "replayed", "held", "skipped"):
        result[key] = result.get(key, 0) + outcome.get(key, 0)
    result.setdefault("relation_ids", []).extend(outcome.get("relation_ids", []))
    if job.get("receipt", {}).get("recorded"):
        result.setdefault("reused_record_ids", []).append(reuse["record_id"])
    result["errors"].extend(outcome["errors"])
    return job["status"] in TERMINAL


def reuse_claim(research, job, question, snapshot, candidate, result):
    """Return None for a novel assertion, otherwise persist/run a narrowed overlap."""
    from .research_graph import graph_digest
    from .research_graph_model import REVISION
    from .research_graph_review import exclusions
    from .research_graph_work import bounded_packet
    from .research_overlap import OverlapWorker
    item = matching_claim(research, snapshot, job, candidate)
    if item is None:
        return None
    identifier = item["record"]["id"]
    rejected = exclusions(research.project, snapshot)
    existing = [r for r in snapshot["bundle"]["relations"] if r["subject"] == identifier
                and r["predicate"] in CLAIM_QUESTION_PREDICATES and r["object"] == question["id"] and r["status"] != "withdrawn"]
    if existing:
        valid = question["id"] in question_links(snapshot, identifier, excluded_relations=rejected)
        job.update(status="linked" if valid else "held", completed_at=_now(),
                   reuse={"record_id": identifier, "relation_ids": [r["id"] for r in existing], "existing": True},
                   reason="The existing finding already has a current connection to this question." if valid else
                          "The existing finding's question link is excluded by its automated assessment.")
        _save_job(research, job)
        result.setdefault("links_added", 0)
        if valid:
            result.setdefault("reused_record_ids", []).append(identifier)
            result.setdefault("relation_ids", []).extend(r["id"] for r in existing if r["id"] not in rejected)
        else:
            result["held"] += 1
        return True
    packet = bounded_packet([item])
    if packet is None:
        job.update(status="held", completed_at=_now(), reason="The existing assertion's required passages exceed the overlap packet limit.",
                   reuse={"record_id": identifier})
        _save_job(research, job)
        result["held"] += 1
        return True
    worker = OverlapWorker(research)
    pair_key = graph_digest({"revision": REVISION, "model": research.model.model, "question": question, "input": item})
    graph = worker.new_job(question, packet, pair_keys=[pair_key], reuse_source_job_id=job["id"])
    graph_path = worker.root / (graph["id"] + ".json")
    # A crash may have saved the graph job before saving this reference.
    if not graph_path.exists():
        worker.save(graph)
    job["reuse"] = {"record_id": identifier, "graph_job_id": graph["id"]}
    _save_job(research, job)
    return resume_reuse(research, job, result)
