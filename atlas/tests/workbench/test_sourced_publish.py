"""North-star test 5's sourced publication: publish_sourced and validate_sourced, as the approved spec fixes them
(docs/superpowers/specs/2026-11-22-claim-crossing-design.md, "The sourced publication")."""
from copy import deepcopy

import pytest

from workbench.lighthouse_wire import digest, seal, verify
from workbench.sourced import (SOURCED_PROFILE, SOURCED_SENTENCE, publish_sourced, source_key, validate_sourced)

ISSUER = "urn:superyak:fixture:pi"


def bundle():
    sources = [
        {"id": "pi-S1", "title": "A study of X", "url": "https://doi.org/10.5555/superyak-fixture-a1", "year": 2024,
         "citation": "Vale A. (2024)"},
        {"id": "pi-S2", "title": "Another study", "url": "https://journal.example/b/7", "year": 2023, "citation": ""},
    ]
    items = [
        {"id": "C1", "kind": "claim", "title": "X raises Y", "summary": "A result.", "status": "source_reported",
         "evidence": [{"source_id": "pi-S1", "locator": "Fig. 1", "note": "main result"}],
         "provenance": {"session": "abc", "path": "/home/someone/notes.md"}},
        {"id": "C2", "kind": "claim", "title": "Y lowers Z", "summary": "", "status": "reviewed",
         "reviewed_by": "Dr Ann Vale", "reviewed_at": "2026-11-20T10:00:00Z",
         "evidence": [{"source_id": "pi-S2", "locator": "Table 2"}]},
        {"id": "Q1", "kind": "question", "title": "Does X matter?", "summary": ""},
    ]
    return {"schema_version": 1, "title": "Fixture collection", "sources": sources, "items": items, "relations": []}


def config(**changes):
    base = {"issuer": ISSUER, "name": "Pi fixture", "origin": "urn:superyak:fixture:pi:collection",
            "context": {"id": "urn:superyak:fixture:context", "path": ["research"]}, "item_ids": ["C1", "C2"],
            "issued_at": "2026-11-22T00:00:00Z"}
    base.update(changes)
    return base


def test_every_artifact_passes_the_strict_validator_and_uses_the_sourced_profile():
    package = publish_sourced(bundle(), config())
    for artifact in [package["descriptor"], package["snapshot"], package["policy"], *package["claims"]]:
        verify(artifact)
        assert artifact["issuer"] == ISSUER
    assert package["snapshot"]["payload"]["profile"] == SOURCED_PROFILE
    assert all(c["payload"]["profile"] == SOURCED_PROFILE for c in package["claims"])
    assert package["descriptor"]["payload"]["profiles"] == [SOURCED_PROFILE]
    assert package["descriptor"]["payload"]["actions"] == ["read", "link_overlap", "retain", "reshare"]


def test_each_source_carries_its_recomputed_keys():
    model = publish_sourced(bundle(), config())["snapshot"]["payload"]["model"]
    for source in model["sources"]:
        plain = {k: v for k, v in source.items() if k != "keys"}
        assert source["keys"] == source_key(plain)
    assert {s["id"] for s in model["sources"]} == {"pi-S1", "pi-S2"}  # only the sources the selected items cite


def test_no_session_path_or_reviewer_name_crosses():
    model = publish_sourced(bundle(), config())["snapshot"]["payload"]["model"]
    items = {i["id"]: i for i in model["items"]}
    assert "provenance" not in items["C1"]                       # session ids and paths stay home
    assert items["C1"]["reviewed_by"] == "" and items["C1"]["reviewed_at"] == ""
    assert items["C2"]["reviewed_by"] == ISSUER                  # a reviewed record names the lighthouse, not a person
    assert items["C2"]["reviewed_at"] == "2026-11-20T10:00:00Z"
    assert "Dr Ann Vale" not in str(publish_sourced(bundle(), config()))


def test_each_claim_names_its_snapshot_and_its_content():
    package = publish_sourced(bundle(), config())
    snapshot = package["snapshot"]
    claims = {c["payload"]["sentence"]["record_id"]: c for c in package["claims"]}
    assert set(claims) == {"C1", "C2"}
    for claim in claims.values():
        assert claim["payload"]["sentenceMediaType"] == SOURCED_SENTENCE
        assert claim["payload"]["snapshotDigests"] == [snapshot["digest"]]
        assert claim["payload"]["provenance"] == []


def test_a_copy_names_the_claims_it_was_copied_from():
    original = publish_sourced(bundle(), config())["claims"][0]["digest"]
    package = publish_sourced(bundle(), config(issuer="urn:superyak:fixture:tardis", copied_from={"C1": [original]}))
    claims = {c["payload"]["sentence"]["record_id"]: c for c in package["claims"]}
    assert claims["C1"]["payload"]["provenance"] == [original]
    assert claims["C2"]["payload"]["provenance"] == []


def test_the_publication_is_reproducible():
    assert publish_sourced(bundle(), config()) == publish_sourced(bundle(), config())


def test_validate_accepts_what_publish_makes():
    package = publish_sourced(bundle(), config())
    assert validate_sourced(package) is package


def _reseal(artifact, issuer=None):
    issuer = issuer or artifact["issuer"]
    payload = artifact["payload"]
    return seal(artifact["kind"], issuer, f"{issuer}:{artifact['kind'].lower()}:{digest(payload)['value']}",
                artifact["issuedAt"], payload)


def _rebuild(package):
    """Reseal every artifact from its (tampered) payload, so only validate_sourced's own checks can refuse it."""
    package["snapshot"] = _reseal(package["snapshot"])
    claims = []
    for claim in package["claims"]:
        claim["payload"]["snapshotDigests"] = [package["snapshot"]["digest"]]
        claims.append(_reseal(claim))
    package["claims"] = claims
    package["policy"] = _reseal(package["policy"])
    package["descriptor"]["payload"]["artifactEndpoints"] = [
        {"kind": a["kind"], "locator": a["id"]} for a in [package["snapshot"], *claims, package["policy"]]]
    package["descriptor"] = _reseal(package["descriptor"])
    return package


def test_a_rebuilt_untampered_publication_still_validates():
    package = _rebuild(publish_sourced(bundle(), config()))
    assert validate_sourced(package) is package


@pytest.mark.parametrize("tamper, message", [
    ("a source labelled with another's DOI", "keys that don't match"),
    ("a source's keys removed", "carries no keys"),
    ("a session path left in an item", "provenance map"),
    ("a reviewer's name left in an item", "reviewer's name"),
    ("the old profile", "Unsupported publication profile"),
])
def test_validate_refuses_a_tampered_snapshot(tamper, message):
    package = deepcopy(publish_sourced(bundle(), config()))
    snapshot = package["snapshot"]["payload"]
    if tamper == "a source labelled with another's DOI":
        snapshot["model"]["sources"][1]["keys"]["doi"] = "doi:10.5555/superyak-fixture-a1"
    elif tamper == "a source's keys removed":
        del snapshot["model"]["sources"][0]["keys"]
    elif tamper == "a session path left in an item":
        snapshot["model"]["items"][0]["provenance"] = {"path": "/home/someone"}
    elif tamper == "a reviewer's name left in an item":
        snapshot["model"]["items"][1]["reviewed_by"] = "Dr Ann Vale"
    elif tamper == "the old profile":
        snapshot["profile"] = {"id": "urn:lighthouse:profile:atlas-research", "version": "0.1.0"}
    with pytest.raises(ValueError, match=message):
        validate_sourced(_rebuild(package))


def test_validate_refuses_a_claim_whose_content_digest_was_changed():
    package = _rebuild(deepcopy(publish_sourced(bundle(), config())))
    package["claims"][0]["payload"]["sentence"]["content_digest"] = digest({"other": 1})
    package["claims"][0] = _reseal(package["claims"][0])
    with pytest.raises(ValueError, match="content digest"):
        validate_sourced(package)


def test_validate_refuses_a_claim_naming_another_snapshot():
    package = deepcopy(publish_sourced(bundle(), config()))
    package["claims"][0]["payload"]["snapshotDigests"] = [digest({"other": 2})]
    package["claims"][0] = _reseal(package["claims"][0])
    with pytest.raises(ValueError, match="another snapshot"):
        validate_sourced(package)


def test_validate_refuses_a_claim_from_another_issuer():
    package = deepcopy(publish_sourced(bundle(), config()))
    package["claims"][0] = _reseal(package["claims"][0], issuer="urn:superyak:fixture:tardis")
    with pytest.raises(ValueError, match="issuers disagree"):
        validate_sourced(package)


def test_validate_refuses_descriptor_endpoints_that_dont_match():
    package = deepcopy(publish_sourced(bundle(), config()))
    package["descriptor"]["payload"]["artifactEndpoints"] = package["descriptor"]["payload"]["artifactEndpoints"][:1]
    package["descriptor"] = _reseal(package["descriptor"])
    with pytest.raises(ValueError, match="Descriptor references"):
        validate_sourced(package)
