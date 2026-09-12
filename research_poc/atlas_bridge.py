"""Bounded local research through a frozen, isolated Atlas workbench snapshot."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PILOT_DOIS = ("10.1038/s41592-024-02303-9", "10.1126/science.aaw3381")
STATIC_ASSETS = {"workbench/static/page.html", "workbench/static/workbench.css", "workbench/static/workbench.js"}
_FROZEN: Path | None = None


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Snapshot requires a regular file: {path}")
    return json.loads(path.read_bytes())


def _save_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(_bytes(value))
        output.flush()
        os.fsync(output.fileno())
    try:
        temporary.chmod(0o444)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _allowed(relative):
    return (relative.startswith("workbench/") and relative.endswith(".py")
            or relative.startswith("workbench/data/") and relative.endswith(".json")
            or relative in STATIC_ASSETS)


def _public_files(source, *, data_only=False):
    for path in sorted((source / "workbench").rglob("*")):
        relative = path.relative_to(source).as_posix()
        if _allowed(relative) and (not data_only or relative.startswith("workbench/data/")):
            if not path.is_file() or path.is_symlink() or path.resolve() != source / relative:
                raise ValueError(f"Atlas snapshot refuses linked or nonregular source: {relative}")
            yield relative, path


def _verify(code):
    if code.is_symlink():
        raise ValueError("Atlas snapshot directory cannot be a symlink")
    manifest = _read(code / "manifest.json")
    actual = {relative: _sha(path.read_bytes()) for relative, path in _public_files(code)}
    if manifest.get("version") != 1 or actual != manifest.get("files") or not actual:
        raise ValueError("Atlas snapshot manifest hashes do not match frozen files")
    return manifest


def _activate(code):
    global _FROZEN
    for name, module in list(sys.modules.items()):
        if name == "workbench" or name.startswith("workbench."):
            location = getattr(module, "__file__", None)
            if not location or not Path(location).resolve().is_relative_to(code):
                raise RuntimeError("Another Atlas code snapshot is already imported; use a fresh process")
    if _FROZEN is not None and _FROZEN != code:
        raise RuntimeError("Another Atlas snapshot is active; use a fresh process")
    if str(code) not in sys.path:
        sys.path.insert(0, str(code))
    _FROZEN = code


def _atlas(module):
    if _FROZEN is None:
        raise RuntimeError("Call prepare_atlas before using the Atlas bridge")
    return importlib.import_module("workbench." + module)


def prepare_atlas(atlas_source: Path, run_dir: Path) -> dict:
    """Freeze public code/data, seed a fresh project, and read its q-fate context."""
    source, run = Path(atlas_source).resolve(), Path(run_dir).resolve()
    run.mkdir(parents=True, exist_ok=True)
    code = run / "atlas-code"
    if not code.exists():
        git_revision = subprocess.run(["git", "-C", str(source), "rev-parse", "--verify", "HEAD"],
                                      capture_output=True, text=True)
        git_status = subprocess.run(["git", "-C", str(source), "status", "--porcelain"],
                                    capture_output=True, text=True)
        manifest = {"version": 1, "source": str(source),
                    "git_revision": git_revision.stdout.strip() if git_revision.returncode == 0 else None,
                    "dirty": bool(git_status.stdout.strip()) if git_status.returncode == 0 else None,
                    "files": {}}
        temporary = Path(tempfile.mkdtemp(prefix=".atlas-code-", dir=run))
        try:
            for relative, path in _public_files(source):
                content = path.read_bytes()
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                destination.chmod(0o444)
                manifest["files"][relative] = _sha(content)
            _save_once(temporary / "manifest.json", manifest)
            os.rename(temporary, code)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    manifest = _verify(code)
    _activate(code)
    seed = fork_project(code, run / "seed-project")
    context = _atlas("automation").ResearchInbox(seed).context("q-fate")
    questions = [entry["record"] for entry in context["records"] if entry["record"]["id"] == "q-fate"]
    if len(questions) != 1 or questions[0]["kind"] != "question":
        raise ValueError("Atlas pilot must contain exactly one q-fate question")
    context_path = run / "atlas-context.json"
    if not context_path.exists():
        _save_once(context_path, context)
    elif _read(context_path) != context:
        raise ValueError("Isolated Atlas seed context changed")
    return {"question": questions[0], "atlas_code": str(code), "seed_project": str(seed), "manifest": manifest}


def fork_project(seed_project: Path, destination: Path) -> Path:
    """Copy public seed data only; preserve an existing destination and journal."""
    seed = Path(seed_project).resolve(strict=True)
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("Atlas project destination cannot be a symlink")
    destination = destination.resolve()
    if destination == seed:
        raise ValueError("Atlas fork must have a distinct destination")
    files = list(_public_files(seed, data_only=True))
    if not files:
        raise ValueError("Atlas seed has no public data")
    if destination.exists():
        for relative, path in files:
            target = destination / relative
            if target.is_symlink() or not target.is_file() or target.read_bytes() != path.read_bytes():
                raise ValueError("Existing Atlas project seed configuration differs")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".seed-project-", dir=destination.parent))
    try:
        for relative, path in files:
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        os.rename(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def fetch_documents(run_dir: Path, *, limit=2) -> list[dict]:
    """Retrieve the two pilot DOIs through Europe PMC; never invent substitute evidence."""
    if type(limit) is not int or not 1 <= limit <= len(PILOT_DOIS):
        raise ValueError("Document limit must be 1 or 2")
    provider = _atlas("research_sources").EuropePMC()
    root = Path(run_dir) / "documents"
    root.mkdir(parents=True, exist_ok=True)
    documents = []
    for index, doi in enumerate(PILOT_DOIS[:limit]):
        path = root / f"{index:02d}-{_sha(doi.encode())[:16]}.json"
        if not path.exists():
            papers = provider.search(f'DOI:"{doi}"', limit=5)["papers"]
            papers = [paper for paper in papers if paper.get("doi", "").casefold() == doi]
            if len(papers) != 1:
                raise ValueError(f"Expected one readable Europe PMC article for DOI {doi}")
            paper = papers[0]
            snapshot = {"paper": paper, "document": provider.read(paper)}
            _save_once(path, snapshot | {"hashes": {key: _sha(_bytes(value)) for key, value in snapshot.items()}})
        saved = _read(path)
        if (set(saved) != {"paper", "document", "hashes"}
                or saved["paper"].get("doi") != doi
                or saved["hashes"] != {key: _sha(_bytes(saved[key])) for key in ("paper", "document")}):
            raise ValueError("Document snapshot hashes or DOI do not match")
        _atlas("research_model")._document_data(saved["document"])
        documents.append({key: saved[key] for key in ("paper", "document")})
    return documents


class AtlasModel:
    """One bounded local model call per generation/review, without client retries."""

    def __init__(self, model="qwen3.8:27b-mlx", timeout=90):
        budget = _atlas("research_context").ContextBudget(context_window=16384, input_bytes=12000,
                                                        output_reserve=1200, margin=1024)
        self._client = _atlas("research_model").Ollama(model, timeout=timeout, context_budget=budget)
        self.model = self._client.model

    def check(self):
        return self._client.check()

    def _invoke(self, function, *args):
        self._client.last_response = self._client.last_context_manifest = None
        try:
            return function(*args)
        except (ValueError, RuntimeError, OSError) as error:
            if not hasattr(error, "result"):
                error.result = getattr(self._client, "last_response", None) or {
                    "context_manifest": self._client.last_context_manifest}
            raise

    def generate(self, question: dict, document: dict, context: list[dict]) -> dict:
        module = _atlas("research_model")
        schema = deepcopy(module.ANALYSIS_SCHEMA)
        schema["properties"].update(private_note={"type": "string"}, publish={"type": "boolean"})
        schema["required"] += ["private_note", "publish"]
        result = self._invoke(self._client._chat,
            "Analyze the current article only. Prior context records are background for relevance, "
            "never evidence. Claims, passage_id and quotes must come exclusively from document.passages. "
            "If relevant, propose one narrowly scoped claim with nonblank title, summary, scope, limitations, "
            "passage_id, quote and rationale. Copy 4–25 contiguous words exactly, preserving capitalization, "
            "punctuation and spacing. Never quote or borrow claims from prior context. Preserve study system "
            "and uncertainty; do not imply causality or general validation. State abstract_only or "
            "full_text_excerpt coverage in limitations and identify reviews or preprints when indicated. "
            "If the passages cannot support a relevant claim, set relevant=false, leave unsupported fields "
            "empty, and give a brief rationale. Return private_note as your private tentative reflection "
            "and publish as your explicit boolean decision whether this candidate should be shared after "
            "source review. You may decline publication. Private notes are never source evidence. "
            "Return only the schema fields; no invented IDs, citations, URLs or review status.",
            {"question": question, "context": context, "document": module._document_data(document)}, schema)
        fields = dict(result["analysis"])
        private_note, publish = fields.pop("private_note"), fields.pop("publish")
        if not isinstance(private_note, str) or len(private_note) > 4000 or type(publish) is not bool:
            raise module.AnalysisValidationError("private_note must be bounded text and publish must be boolean", result)
        extraction = result | {"analysis": fields}
        if any(not isinstance(fields[key], str) for key in module.ANALYSIS_STRINGS):
            raise module.AnalysisValidationError("analysis text fields must be strings", result)
        try:
            checked = _atlas("research_runner").validate_analysis(extraction, document)
        except ValueError as error:
            raise module.AnalysisValidationError(str(error), result) from error
        if checked and fields["passage_id"] not in result["context_manifest"]["selected_passage_ids"]:
            raise module.AnalysisValidationError("Quote must come from a passage supplied in this request", result)
        if result["model"] != self.model:
            raise module.AnalysisValidationError("Actual model identity differs from the requested fixed model", result)
        return {"extraction": extraction, "private_note": private_note, "publish": publish}

    def review(self, question, document, candidate):
        result = self._invoke(self._client.review, question, document, candidate)
        if result["model"] != self.model:
            raise _atlas("research_review").SourceReviewError(
                "Actual reviewer identity differs from the requested fixed model", result)
        return result


def record_finding(project: Path, *, question: dict, paper: dict, document: dict,
                   extraction: dict, review: dict, session_id: str, idempotency_key: str) -> dict:
    """Record only valid supported candidates, attributed to the calling research agent."""
    runner, reviewer = _atlas("research_runner"), _atlas("research_review")
    checked = runner.validate_analysis(extraction, document)
    if checked is None:
        raise ValueError("Only relevant candidates can be recorded")
    if reviewer.validate_review(review, document)["verdict"] != "supported":
        raise ValueError("Only source-supported candidates can be recorded")
    if not isinstance(extraction.get("model"), str) or not extraction["model"].strip():
        raise ValueError("Extraction must identify the actual model")
    manifest = extraction.get("context_manifest", {})
    if checked[0]["passage_id"] not in manifest.get("selected_passage_ids", []):
        raise ValueError("Candidate quote must identify a passage supplied to extraction")
    source_review = {"revision": reviewer.REVIEW_REVISION, "result": review,
                     "input_digest": reviewer.review_input_digest(review["model"], question, document, extraction["analysis"])}
    inbox = _atlas("automation").ResearchInbox(project)
    job = {"id": idempotency_key, "paper": paper, "document": document,
           "extraction": extraction, "source_review": source_review}
    draft = runner.prepare_draft(job, question, inbox.snapshot(), checked)
    draft["idempotency_key"] = idempotency_key
    return inbox.record(draft, session_id)
