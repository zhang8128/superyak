"""Real Atlas integration; only outbound HTTP is replaced with controlled replies."""

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("ATLAS_TEST_SOURCE", str(ROOT / "atlas")))


@pytest.fixture(scope="module")
def atlas(tmp_path_factory):
    assert (ROOT / "research_poc/atlas_bridge.py").exists(), "Atlas bridge is not implemented"
    assert (SOURCE / "workbench/automation.py").is_file(), f"Missing Atlas source: {SOURCE}"
    bridge = importlib.import_module("research_poc.atlas_bridge")
    root = tmp_path_factory.mktemp("atlas-bridge")
    source = root / "source"
    for original in (SOURCE / "workbench").rglob("*"):
        if original.is_file() and (original.suffix == ".py" or "data" in original.parts
                                   and original.suffix == ".json" or "static" in original.parts):
            target = source / original.relative_to(SOURCE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    for relative in (".atlas/drafts/private.json", "Research/private.md", "secret.key"):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("do not copy")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    prepared = bridge.prepare_atlas(source, root / "run")
    return bridge, root, source, prepared


def test_prepare_freezes_public_source_and_loads_question(atlas):
    bridge, root, source, prepared = atlas
    assert prepared["question"]["id"] == "q-fate"
    assert prepared["question"]["status"] == "proposed"
    frozen = Path(prepared["atlas_code"])
    assert not (frozen / ".atlas").exists()
    assert not (frozen / "Research").exists()
    assert not (frozen / "secret.key").exists()
    assert prepared["manifest"]["dirty"] is True
    for relative, expected in prepared["manifest"]["files"].items():
        assert hashlib.sha256((frozen / relative).read_bytes()).hexdigest() == expected
    original = frozen / "workbench/research_model.py"
    frozen_bytes = original.read_bytes()
    (source / "workbench/research_model.py").write_bytes(b"raise RuntimeError('new live edit')\n")
    assert bridge.prepare_atlas(source, root / "run") == prepared
    assert original.read_bytes() == frozen_bytes
    from workbench import automation
    assert Path(automation.__file__).is_relative_to(frozen)
    assert not (Path(prepared["seed_project"]) / ".atlas").exists()


def test_fork_copies_seed_data_without_journal_or_renewing_grants(atlas, tmp_path):
    bridge, _, _, prepared = atlas
    seed = Path(prepared["seed_project"])
    project = bridge.fork_project(seed, tmp_path / "agent")
    config = "workbench/data/lighthouses/prediction.json"
    assert (project / config).read_bytes() == (seed / config).read_bytes()
    assert not (project / "workbench/research_model.py").exists()
    journal = project / ".atlas/drafts"
    journal.mkdir(parents=True)
    (journal / "existing.json").write_text("preserve me")
    assert bridge.fork_project(seed, project) == project
    assert (journal / "existing.json").read_text() == "preserve me"


def test_activation_refuses_other_atlas_code(atlas, tmp_path):
    _, _, _, prepared = atlas
    program = """
import sys, types
from pathlib import Path
from research_poc.atlas_bridge import prepare_atlas
module = types.ModuleType('workbench')
module.__file__ = '/other/workbench/__init__.py'
sys.modules['workbench'] = module
try:
    prepare_atlas(Path(sys.argv[1]), Path(sys.argv[2]))
except RuntimeError as exc:
    assert 'Atlas' in str(exc)
else:
    raise AssertionError('foreign Atlas imports were accepted')
"""
    result = subprocess.run([sys.executable, "-c", program, prepared["atlas_code"], str(tmp_path)],
                            cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_snapshot_corruption_is_refused(atlas, tmp_path):
    bridge, _, _, prepared = atlas
    run = tmp_path / "corrupt-run"
    shutil.copytree(prepared["atlas_code"], run / "atlas-code")
    target = run / "atlas-code/workbench/research_model.py"
    target.chmod(0o600)
    target.write_text("tampered")
    with pytest.raises(ValueError, match="hash|snapshot|manifest"):
        bridge.prepare_atlas(SOURCE, run)


def literature_reply(doi):
    return {"resultList": {"result": [{"id": "123456", "source": "MED", "doi": doi,
        "title": "A controlled source fixture", "abstractText": "Measured cellular state predicts observed fate in this experiment.",
        "pubYear": "2024", "authorString": "Example A", "pubTypeList": {"pubType": ["Journal Article"]}}]}}


def test_documents_use_real_normalization_and_immutable_retrieval(atlas, tmp_path, monkeypatch):
    bridge, _, _, _ = atlas
    from workbench import research_sources
    from urllib.parse import parse_qs, urlsplit
    requests = []

    def reply(request, timeout, maximum):
        requests.append(request.full_url)
        query = parse_qs(urlsplit(request.full_url).query)["query"][0]
        return literature_reply("10.1038/s41592-024-02303-9" if "02303" in query else "10.1126/science.aaw3381")

    monkeypatch.setattr(research_sources, "_json_response", reply)
    documents = bridge.fetch_documents(tmp_path)
    assert len(documents) == 2
    assert [d["paper"]["doi"] for d in documents] == ["10.1038/s41592-024-02303-9", "10.1126/science.aaw3381"]
    assert documents[0]["document"]["coverage"] == "abstract_only"
    assert documents[0]["document"]["passages"][0]["text"].startswith("Measured cellular state")
    assert bridge.fetch_documents(tmp_path) == documents
    assert len(requests) == 2
    snapshot = next((tmp_path / "documents").glob("*.json"))
    snapshot.chmod(0o600)
    snapshot.write_text("{}")
    with pytest.raises(ValueError, match="hash|snapshot|manifest"):
        bridge.fetch_documents(tmp_path)


def test_missing_literature_errors_without_seed_evidence(atlas, tmp_path, monkeypatch):
    bridge, _, _, _ = atlas
    from workbench import research_sources
    monkeypatch.setattr(research_sources, "_json_response", lambda *args: {"resultList": {"result": []}})
    with pytest.raises(ValueError, match="DOI|paper|article"):
        bridge.fetch_documents(tmp_path, limit=1)
    assert not list((tmp_path / "documents").glob("*.json"))


@pytest.fixture
def document():
    return {"source": {"id": "s-fixture", "title": "Cell fate fixture", "year": 2024,
                       "url": "https://doi.org/10.1038/s41592-024-02303-9", "citation": "Fixture (2024)."},
            "coverage": "abstract_only", "coverage_note": "Only the provider abstract was read.",
            "retrieved_at": "2026-09-12T00:00:00+00:00", "content_sha256": "a" * 64,
            "document_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            "publication_types": ["Journal Article"],
            "passages": [{"id": "p0001", "locator": "Abstract, paragraph 1",
                          "text": "Measured cellular state predicts observed fate in this experiment."}]}


def candidate():
    return {"relevant": True, "title": "State predicts observed fate", "summary": "Measured state predicts fate in this experiment.",
            "scope": "The reported study system", "limitations": "Abstract-only evidence; no independent validation.",
            "passage_id": "p0001", "quote": "Measured cellular state predicts observed fate",
            "rationale": "The observation informs the state-to-fate question."}


def model_response(analysis, model="qwen3.8:27b-mlx"):
    return {"model": model, "done": True, "done_reason": "stop", "prompt_eval_count": 321,
            "eval_count": 52, "message": {"role": "assistant", "content": json.dumps(analysis)}}


def test_model_preserves_source_boundaries_metrics_and_explicit_publication(atlas, document, monkeypatch):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    requests = []

    def reply(request, timeout, maximum):
        if request.full_url.endswith("/tags"):
            return {"models": [{"name": "qwen3.8:27b-mlx", "digest": "model-digest"}]}
        payload = json.loads(request.data)
        requests.append(payload)
        if "publish" in payload["format"]["required"]:
            return model_response(candidate() | {"private_note": "Tentative private comparison.", "publish": False})
        return model_response({"verdict": "supported", "reason": "The supplied source supports the narrow claim.",
                               "evidence": [{"passage_id": "p0001"}]})

    monkeypatch.setattr(research_model, "_json_response", reply)
    model = bridge.AtlasModel()
    assert model.check()["digest"] == "model-digest"
    result = model.generate(prepared["question"], document,
                            [{"record": {"id": "agent-private", "summary": "Background only"}}])
    assert result["publish"] is False
    assert result["private_note"] == "Tentative private comparison."
    assert "private_note" not in result["extraction"]["analysis"]
    assert result["extraction"]["metrics"]["prompt_eval_count"] == 321
    assert result["extraction"]["model"] == "qwen3.8:27b-mlx"
    assert result["extraction"]["context_manifest"]["selected_record_ids"] == ["agent-private"]
    review = model.review(prepared["question"], document, result["extraction"]["analysis"])
    assert review["analysis"]["verdict"] == "supported"
    assert review["context_manifest"]["selected_record_ids"] == []
    assert json.loads(requests[-1]["messages"][1]["content"])["context"] == []
    assert all(payload["options"]["temperature"] == 0 for payload in requests)
    assert all(payload["options"]["num_ctx"] == 16384 for payload in requests)
    for payload, output in zip(requests, [result["extraction"], review]):
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        assert output["context_manifest"]["payload_sha256"] == hashlib.sha256(serialized.encode()).hexdigest()


@pytest.mark.parametrize("change", [{"quote": "This quote is not in the document"},
                                     {"quote": "state"}, {"publish": "yes"},
                                     {"private_note": None}])
def test_invalid_model_output_is_rejected_without_retry(atlas, document, monkeypatch, change):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    requests = []

    def reply(request, *args):
        requests.append(request)
        return model_response(candidate() | {"private_note": "Private", "publish": True} | change)

    monkeypatch.setattr(research_model, "_json_response", reply)
    with pytest.raises(ValueError) as caught:
        bridge.AtlasModel().generate(prepared["question"], document, [])
    assert len(requests) == 1
    assert caught.value.result["metrics"]["prompt_eval_count"] == 321


def test_model_cannot_quote_cached_passage_omitted_from_prompt(atlas, document, monkeypatch):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    document["passages"][0]["text"] += " Measured cellular state fate prediction." * 150
    document["passages"].append({"id": "p0002", "locator": "Body, paragraph 2",
                                 "text": "Second unrelated passage supports nothing. " + "Filler. " * 800})
    monkeypatch.setattr(research_model, "_json_response", lambda *args: model_response(
        candidate() | {"passage_id": "p0002", "quote": "Second unrelated passage supports nothing.",
                       "private_note": "Private", "publish": True}))
    with pytest.raises(ValueError, match="supplied") as caught:
        bridge.AtlasModel().generate(prepared["question"], document, [])
    assert caught.value.result["context_manifest"]["selected_passage_ids"] == ["p0001"]


def test_model_rejects_server_model_substitution(atlas, document, monkeypatch):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    monkeypatch.setattr(research_model, "_json_response", lambda *args: model_response(
        candidate() | {"private_note": "Private", "publish": True}, model="unexpected:latest"))
    with pytest.raises(ValueError, match="identity"):
        bridge.AtlasModel().generate(prepared["question"], document, [])


def test_malformed_response_retains_raw_usage_and_request_manifest(atlas, document, monkeypatch):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    response = model_response({"wrong": "shape"})
    monkeypatch.setattr(research_model, "_json_response", lambda *args: response)
    with pytest.raises(ValueError) as caught:
        bridge.AtlasModel().generate(prepared["question"], document, [])
    assert caught.value.result["response"]["prompt_eval_count"] == 321
    assert caught.value.result["context_manifest"]["selected_passage_ids"] == ["p0001"]


def test_review_model_substitution_retains_usage(atlas, document, monkeypatch):
    bridge, _, _, prepared = atlas
    from workbench import research_model
    response = model_response({"verdict": "supported", "reason": "Narrow claim matches supplied passage.",
                               "evidence": [{"passage_id": "p0001"}]}, model="unexpected:latest")
    monkeypatch.setattr(research_model, "_json_response", lambda *args: response)
    with pytest.raises(ValueError) as caught:
        bridge.AtlasModel().review(prepared["question"], document, candidate())
    assert caught.value.result["metrics"]["prompt_eval_count"] == 321


def test_record_is_attributed_proposed_idempotent_and_exported(atlas, document, tmp_path):
    bridge, _, _, prepared = atlas
    project = bridge.fork_project(Path(prepared["seed_project"]), tmp_path / "cell")
    extraction = {"analysis": candidate(), "model": "qwen3.8:27b-mlx", "metrics": {},
                  "context_manifest": {"selected_passage_ids": ["p0001"], "omitted_passages": 0}}
    review = {"analysis": {"verdict": "supported", "reason": "Supported by the supplied abstract.",
                            "evidence": [{"passage_id": "p0001"}]}, "model": "qwen3.8:27b-mlx",
              "context_manifest": {"selected_record_ids": [], "selected_passage_ids": ["p0001"]}}
    kwargs = dict(question=prepared["question"], paper={"doi": "10.1038/s41592-024-02303-9"},
                  document=document, extraction=extraction, review=review,
                  session_id="poc:cell-a:agent-0", idempotency_key="round:0:paper:0")
    receipt = bridge.record_finding(project, **kwargs)
    assert receipt["recorded"] is True
    assert receipt["session_id"] == "poc:cell-a:agent-0"
    assert receipt["publication_status"] == "current"
    assert (project / "Research/index.html").exists()
    assert (project / "Research/Start Here.md").exists()
    duplicate = bridge.record_finding(project, **kwargs)
    assert duplicate["record_id"] == receipt["record_id"] and duplicate["duplicate"] is True
    from workbench.automation import ResearchInbox
    finding = next(item for item in ResearchInbox(project).snapshot()["bundle"]["items"]
                   if item["id"] == receipt["record_id"])
    assert finding["status"] == "proposed"
    assert finding["context"]["source_support"] == "supported"
    assert finding["evidence"][0]["source_id"] == "s-cellrank"
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1
    review["analysis"]["verdict"] = "uncertain"
    with pytest.raises(ValueError, match="supported"):
        bridge.record_finding(project, **kwargs | {"idempotency_key": "rejected"})
    assert len(list((project / ".atlas/drafts").glob("*.json"))) == 1
