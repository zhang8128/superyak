import copy
import json
import subprocess
import sys

import pytest

from workbench.lighthouse import evaluate, publish


AT = "2026-09-07T12:00:00Z"


def bundle():
    return {
        "schema_version": 1, "title": "Synthetic research fixture",
        "sources": [
            {"id": "paper-a", "title": "Synthetic source A", "url": "https://example.org/a", "year": 2026, "citation": "Fixture A"},
            {"id": "private-paper", "title": "Unselected source", "url": "https://example.org/private", "year": 2025, "citation": "Private fixture"},
        ],
        "items": [
            {"id": "question", "kind": "question", "title": "What explains the observation?", "summary": "A question"},
            {"id": "claim", "kind": "claim", "title": "Reported observation", "summary": "Source reports result A within setting X.",
             "status": "source_reported", "context": {"setting": "X"}, "facets": {"topic": ["fate", "regulation"]},
             "evidence": [{"source_id": "paper-a", "locator": "Figure 2", "note": "Limited to setting X"}]},
            {"id": "private", "kind": "claim", "title": "Private unrelated assertion", "summary": "Do not publish this",
             "evidence": [{"source_id": "private-paper", "locator": "Section 3", "note": "private"}]},
        ],
        "relations": [
            {"id": "informs", "subject": "claim", "predicate": "informs", "object": "question", "status": "source_reported",
             "evidence": [{"source_id": "paper-a", "locator": "Figure 2", "note": "Source interpretation"}]},
            {"id": "excluded", "subject": "private", "predicate": "challenges", "object": "claim", "rationale": "Unselected private rationale"},
        ],
        "history": [{"reason": "PRIVATE AUDIT HISTORY"}],
    }


def config(issuer="urn:atlas:personal"):
    return {"issuer": issuer, "name": "Research view", "origin": "urn:atlas:fixture",
            "context": {"id": "research/cell-fate", "path": ["research", "cell-fate"]},
            "item_ids": ["question", "claim"], "issued_at": AT}


def test_publication_contains_only_selected_records_and_their_evidence():
    original = bundle()
    before = copy.deepcopy(original)
    publication = publish(original, config())
    model = publication["snapshot"]["payload"]["model"]
    assert {item["id"] for item in model["items"]} == {"question", "claim"}
    assert [source["id"] for source in model["sources"]] == ["paper-a"]
    assert [relation["id"] for relation in model["relations"]] == ["informs"]
    assert "PRIVATE" not in str(publication) and "Unselected" not in str(publication)
    assert publication["diagnostics"] == {"omitted_relations": 1}
    assert publication["policy"]["payload"]["rules"] == []
    claim = next(c for c in publication["claims"] if c["payload"]["sentence"]["record_id"] == "claim")
    assert evaluate(claim, publication["snapshot"]) == "satisfied"
    assert next(i for i in model["items"] if i["id"] == "claim")["status"] == "source_reported"
    assert original == before


def grant(publisher="urn:atlas:lab"):
    from workbench.lighthouse import PROFILE, SENTENCE
    return {"id": "read-lab", "effect": "allow", "publishers": [publisher], "profiles": [PROFILE["id"]],
            "domains": ["research"], "actions": ["read", "link_overlap"], "contexts": ["research/cell-fate"],
            "claimMediaTypes": [SENTENCE], "purposes": ["research"], "audiences": ["self"],
            "validFrom": "2026-09-01T00:00:00Z", "validUntil": "2026-10-01T00:00:00Z",
            "requiredEvidence": [], "requiredAttestations": []}


def test_overlap_retains_differing_accounts_and_requires_directional_admission():
    from workbench.lighthouse import overlap
    local_config = config()
    local_config["rules"] = [grant()]
    local = publish(bundle(), local_config)
    changed = bundle()
    changed["items"][1]["status"] = "withdrawn"
    changed["items"][1]["summary"] = "This account has been withdrawn."
    remote = publish(changed, config("urn:atlas:lab"))
    result = overlap(local, remote, AT)
    assert result["status"] == "compared"
    shared = {pair["record_id"]: pair for pair in result["record_pairs"]}
    assert shared["question"]["comparison"] == "identical"
    assert shared["claim"]["comparison"] == "different"
    assert [a["publisher"] for a in shared["claim"]["accounts"]] == ["urn:atlas:personal", "urn:atlas:lab"]
    assert [a["record"]["status"] for a in shared["claim"]["accounts"]] == ["source_reported", "withdrawn"]
    assert shared["claim"]["accounts"][1]["sources"][0]["url"] == "https://example.org/a"
    denied = overlap(remote, local, AT)
    assert denied["status"] == "denied" and denied["record_pairs"] == []
    assert "Source reports" not in str(denied)


def test_restriction_preserves_scope_laws_and_does_not_inherit_grants():
    from workbench.lighthouse import restrict, validate_publication
    full_config = config()
    full_config["item_ids"].append("private")
    full_config["rules"] = [grant()]
    full = publish(bundle(), full_config)
    assert restrict(full, full_config["item_ids"], full_config["context"], AT) == full
    middle_context = {"id": "research/cell-fate/evidence", "path": ["research", "cell-fate", "evidence"]}
    end_context = {"id": "research/cell-fate/evidence/claim", "path": ["research", "cell-fate", "evidence", "claim"]}
    middle = restrict(full, ["claim", "question"], middle_context, AT)
    chained = restrict(middle, ["claim"], end_context, AT)
    direct = restrict(full, ["claim"], end_context, AT)
    assert chained["snapshot"]["payload"]["model"] == direct["snapshot"]["payload"]["model"]
    assert chained["snapshot"]["payload"]["context"] == direct["snapshot"]["payload"]["context"]
    assert chained["policy"]["payload"]["rules"] == []
    assert chained["snapshot"]["payload"]["lineage"] == [middle["snapshot"]["digest"]]
    assert validate_publication(chained) == chained
    assert "Private" not in str(chained)


def test_cli_publishes_validates_and_refuses_existing_or_symlink_outputs(tmp_path):
    source, settings, output = (tmp_path / name for name in ("source.json", "config.json", "view.json"))
    source.write_text(json.dumps(bundle()))
    settings.write_text(json.dumps(config()))

    def run(*arguments):
        return subprocess.run([sys.executable, "-m", "workbench.lighthouse", *map(str, arguments)],
                              capture_output=True, text=True)

    result = run("publish", source, settings, "--output", output)
    assert result.returncode == 0, result.stderr
    assert output.is_file()
    saved = output.read_bytes()
    validated = run("validate", output)
    assert validated.returncode == 0 and json.loads(validated.stdout)["valid"]
    assert run("publish", source, settings, "--output", output).returncode == 1
    assert output.read_bytes() == saved
    link = tmp_path / "link.json"
    link.symlink_to(source)
    assert run("publish", source, settings, "--output", link).returncode == 1
    assert json.loads(source.read_text()) == bundle()
    settings.write_text('{"issuer":"urn:one","issuer":"urn:two"}')
    failed = run("publish", source, settings, "--output", tmp_path / "failed.json")
    assert failed.returncode == 1 and "Duplicate JSON key" in failed.stderr
    assert not (tmp_path / "failed.json").exists()


@pytest.mark.parametrize("change", [
    lambda b: b.update(schema_version=2),
    lambda b: b.update(extra="unknown"),
    lambda b: b["items"].append(copy.deepcopy(b["items"][0])),
    lambda b: b["items"][1]["evidence"][0].update(source_id="missing"),
    lambda b: b["items"][1].update(evidence=[]),
    lambda b: b["items"][1].update(status="reviewed"),
    lambda b: b["items"][1].update(kind="protein"),
    lambda b: b["items"][1].update(facets={"topic": "not-a-list"}),
    lambda b: b["sources"][0].update(year=2026.0),
    lambda b: b["sources"][0].update(url="javascript:alert(1)"),
    lambda b: b["relations"][0].update(object="missing"),
    lambda b: b["relations"][0].update(predicate="enables"),
])
def test_invalid_bundle_is_rejected_before_publication(change):
    data = bundle()
    change(data)
    with pytest.raises(ValueError):
        publish(data, config())


@pytest.mark.parametrize("field,value", [("item_ids", []), ("item_ids", ["missing"]),
                                          ("item_ids", ["claim", "claim"]), ("origin", "relative/path")])
def test_invalid_publication_selection_is_rejected(field, value):
    settings = config()
    settings[field] = value
    with pytest.raises(ValueError):
        publish(bundle(), settings)


def test_tampering_and_resealed_semantic_inconsistency_are_rejected():
    from workbench.lighthouse import validate_publication
    from workbench.lighthouse_wire import seal
    publication = publish(bundle(), config())
    publication["snapshot"]["payload"]["model"]["items"][0]["summary"] = "Changed assertion"
    with pytest.raises(ValueError):
        validate_publication(publication)
    old = publication["snapshot"]
    publication["snapshot"] = seal(old["kind"], old["issuer"], old["id"], old["issuedAt"], old["payload"])
    with pytest.raises(ValueError, match="Claim does not match"):
        validate_publication(publication)
    missing = publish(bundle(), config())
    missing["claims"].pop()
    with pytest.raises(ValueError, match="cover"):
        validate_publication(missing)


def test_unsupported_scientific_sentence_is_indeterminate():
    from workbench.lighthouse_wire import seal
    publication = publish(bundle(), config())
    original = publication["claims"][0]
    payload = copy.deepcopy(original["payload"])
    payload["sentence"] = {"biologically_true": True}
    unsupported = seal("Claim", original["issuer"], original["id"], AT, payload)
    assert evaluate(unsupported, publication["snapshot"]) == "indeterminate"


@pytest.mark.parametrize("change", [
    lambda r: r.update(actions=["read"]),
    lambda r: r.update(actions=["link_overlap"]),
    lambda r: r.update(publishers=["urn:atlas:other"]),
    lambda r: r.update(contexts=["other/context"]),
    lambda r: r.update(validUntil="2026-09-06T00:00:00Z"),
    lambda r: r.update(purposes=["marketing"]),
    lambda r: r.update(requiredAttestations=["institution-signature"]),
    lambda r: r.update(effect="deny"),
])
def test_overlap_requires_both_scoped_actions_and_current_direct_grants(change):
    from workbench.lighthouse import overlap
    rule = grant()
    change(rule)
    settings = config()
    settings["rules"] = [rule]
    result = overlap(publish(bundle(), settings), publish(bundle(), config("urn:atlas:lab")), AT)
    assert result["status"] == "denied" and result["record_pairs"] == []
    assert "Reported observation" not in str(result)


def test_equal_local_ids_from_different_origins_do_not_imply_identity():
    from workbench.lighthouse import overlap
    local = config()
    local["rules"] = [grant()]
    other = config("urn:atlas:lab")
    other["origin"] = "urn:atlas:independent-collection"
    result = overlap(publish(bundle(), local), publish(bundle(), other), AT)
    assert result["status"] == "unmapped" and result["record_pairs"] == []


def test_overlap_includes_source_metadata_for_its_returned_relations():
    from workbench.lighthouse import overlap
    data = bundle()
    data["relations"][0]["evidence"][0]["source_id"] = "private-paper"
    settings = config()
    settings["rules"] = [grant()]
    result = overlap(publish(data, settings), publish(data, config("urn:atlas:lab")), AT)
    question = next(pair for pair in result["record_pairs"] if pair["record_id"] == "question")
    account = question["accounts"][0]
    assert account["relations"][0]["evidence"][0]["source_id"] == "private-paper"
    assert {source["id"] for source in account["sources"]} == {"private-paper"}


@pytest.mark.parametrize("ids,context", [
    (["private"], {"id": "research/cell-fate", "path": ["research", "cell-fate"]}),
    (["claim"], {"id": "research", "path": ["research"]}),
    (["claim"], {"id": "unrelated", "path": ["other"]}),
    (["claim"], {"id": "new-name", "path": ["research", "cell-fate"]}),
])
def test_restriction_cannot_expand_or_reinterpret_its_domain(ids, context):
    from workbench.lighthouse import restrict
    with pytest.raises(ValueError):
        restrict(publish(bundle(), config()), ids, context, AT)


def test_same_context_restriction_is_identity_even_at_a_later_time():
    from workbench.lighthouse import restrict
    settings = config()
    full = publish(bundle(), settings)
    later = "2026-09-08T12:00:00Z"
    with pytest.raises(ValueError, match="same context"):
        restrict(full, ["claim"], settings["context"], later)
    assert restrict(full, settings["item_ids"], settings["context"], later) == full
