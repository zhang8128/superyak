"""Portable, explicitly scoped Lighthouse views of Atlas research records."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

from .lighthouse_wire import authorize, digest, seal, verify
from .validation import CLAIM_QUESTION_PREDICATES, EXPLICIT_QUESTION_PREDICATES

PROFILE = {"id": "urn:lighthouse:profile:atlas-research", "version": "0.1.0"}
SIGNATURE = {"id": "urn:atlas:research-workbench", "version": "1.0.0"}
SENTENCE = "application/vnd.atlas.record-claim+json"
FORMAT = "atlas-lighthouse-publication"
STATUSES = {"proposed", "source_reported", "reviewed", "withdrawn"}
KINDS = {"question", "approach", "claim", "experiment"}
PREDICATES = {"addresses", "supports", "challenges", "informs", "tests", "uses_method", "part_of", "requires", "enables"} | EXPLICIT_QUESTION_PREDICATES


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError("Missing or unknown object fields")


def _text(value, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError("Expected a nonempty string")
    value.encode("utf-8")
    return value


def _list(value):
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return value


def _mapping(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a string mapping")
    for key, member in value.items():
        _text(key)
        _text(member, True)


def _uri(value):
    _text(value)
    if not urlsplit(value).scheme:
        raise ValueError("Expected an absolute URI")
    return value


def _context(value):
    _keys(value, {"id", "path"})
    _text(value["id"])
    for segment in _list(value["path"]):
        _text(segment)


def _bundle(bundle):
    _keys(bundle, {"schema_version", "title", "sources", "items", "relations"}, {"history"})
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise ValueError("Unsupported workbench schema")
    _text(bundle["title"])
    sources, items, relations = {}, {}, {}
    for source in _list(bundle["sources"]):
        _keys(source, {"id", "title", "url", "year", "citation"})
        for field in ("id", "title", "url", "citation"):
            _text(source[field], field == "citation")
        url = urlsplit(source["url"])
        if url.scheme not in {"http", "https"} or not url.netloc or type(source["year"]) is not int:
            raise ValueError("Invalid source URL or year")
        if source["id"] in sources:
            raise ValueError("Duplicate source ID")
        sources[source["id"]] = deepcopy(source)
    optional = {"status", "context", "evidence", "reviewed_by", "reviewed_at"}
    for relation, records in ((False, bundle["items"]), (True, bundle["relations"])):
        for original in _list(records):
            if relation:
                _keys(original, {"id", "subject", "predicate", "object"}, optional | {"rationale"})
            else:
                _keys(original, {"id", "kind", "title", "summary"}, optional | {"facets", "provenance"})
            record = deepcopy(original)
            _text(record["id"])
            if record["id"] in items or record["id"] in relations:
                raise ValueError("Duplicate item/relation ID")
            record.setdefault("status", "proposed")
            if record["status"] not in STATUSES:
                raise ValueError("Unknown review status")
            for field in ("reviewed_by", "reviewed_at"):
                _text(record.setdefault(field, ""), True)
            if record["status"] == "reviewed" and not all(record[f].strip() for f in ("reviewed_by", "reviewed_at")):
                raise ValueError("Reviewed records require a named reviewer and timestamp")
            _mapping(record.setdefault("context", {}))
            for evidence in _list(record.setdefault("evidence", [])):
                _keys(evidence, {"source_id", "locator"}, {"note"})
                _text(evidence["source_id"])
                _text(evidence["locator"])
                _text(evidence.setdefault("note", ""), True)
                if evidence["source_id"] not in sources:
                    raise ValueError("Dangling evidence source")
            if relation:
                for field in ("subject", "predicate", "object"):
                    _text(record[field])
                _text(record.setdefault("rationale", ""), True)
                if record["predicate"] not in PREDICATES:
                    raise ValueError("Unknown relation predicate")
                relations[record["id"]] = record
            else:
                if record["kind"] not in KINDS:
                    raise ValueError("Unknown record kind")
                _text(record["title"])
                _text(record["summary"], True)
                _mapping(record.setdefault("provenance", {}))
                facets = record.setdefault("facets", {})
                if not isinstance(facets, dict):
                    raise ValueError("Expected facet mapping")
                for key, values in facets.items():
                    _text(key)
                    for value in _list(values):
                        _text(value)
                items[record["id"]] = record
            if (relation or record["kind"] == "claim") and record["status"] in {"source_reported", "reviewed"} and not record["evidence"]:
                raise ValueError("Reported or reviewed assertions require located evidence")
    endpoint_rules = {"addresses": ({"approach"}, {"question"}),
                      "supports": ({"claim"}, {"claim", "approach"}),
                      "challenges": ({"claim"}, {"claim", "approach"}),
                      **{predicate: ({"claim"}, {"question"}) for predicate in CLAIM_QUESTION_PREDICATES},
                      "tests": ({"experiment"}, {"claim", "approach", "question"}),
                      "uses_method": ({"approach", "experiment"}, {"approach"}),
                      "part_of": ({"question"}, {"question"})}
    for relation in relations.values():
        if relation["subject"] not in items or relation["object"] not in items:
            raise ValueError("Dangling relation endpoint")
        left, right = items[relation["subject"]], items[relation["object"]]
        predicate = relation["predicate"]
        if predicate in endpoint_rules:
            starts, ends = endpoint_rules[predicate]
            if left["kind"] not in starts or right["kind"] not in ends:
                raise ValueError("Invalid relation endpoint kinds")
        else:
            if "claim" in {left["kind"], right["kind"]} or left["id"] == right["id"]:
                raise ValueError("Invalid prerequisite endpoints")
            if relation["status"] == "reviewed" and not (relation["context"] and relation["rationale"].strip()):
                raise ValueError("Reviewed prerequisites require scope and rationale")
    result = {"schema_version": 1, "title": bundle["title"], "sources": list(sources.values()),
              "items": list(items.values()), "relations": list(relations.values())}
    digest(result)  # Enforce the profile's portable JSON number/string subset.
    return result


def _record_content(record, sources):
    referenced = {e["source_id"] for e in record["evidence"]}
    return {"record": record, "sources": sorted((s for s in sources if s["id"] in referenced), key=lambda s: s["id"])}


def _artifact(kind, config, payload):
    identifier = f"{config['issuer']}:{kind.lower()}:{digest(payload)['value']}"
    return seal(kind, config["issuer"], identifier, config["issued_at"], payload)


def publish(bundle, config):
    _keys(config, {"issuer", "name", "origin", "context", "item_ids", "issued_at"}, {"rules"})
    _uri(config["issuer"])
    _uri(config["origin"])
    _text(config["name"])
    _context(config["context"])
    ids = _list(config["item_ids"])
    for identifier in ids:
        _text(identifier)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Select one or more distinct item IDs explicitly")
    bundle = _bundle(bundle)
    selected = set(ids)
    if selected - {item["id"] for item in bundle["items"]}:
        raise ValueError("Unknown selected item ID")
    items = sorted((i for i in bundle["items"] if i["id"] in selected), key=lambda i: i["id"])
    relations = sorted((r for r in bundle["relations"] if {r["subject"], r["object"]} <= selected), key=lambda r: r["id"])
    referenced = {e["source_id"] for record in items + relations for e in record["evidence"]}
    sources = sorted((s for s in bundle["sources"] if s["id"] in referenced), key=lambda s: s["id"])
    model = {"schema_version": 1, "origin": config["origin"], "title": bundle["title"],
             "items": items, "relations": relations, "sources": sources}
    return _publication(model, config, [], len(bundle["relations"]) - len(relations))


def _publication(model, config, lineage, omitted):
    snapshot = _artifact("Snapshot", config, {"profile": PROFILE, "signature": SIGNATURE,
                         "context": config["context"], "model": model, "lineage": lineage})
    claims = [_artifact("Claim", config, {
        "profile": PROFILE, "signature": SIGNATURE, "context": config["context"], "sentenceMediaType": SENTENCE,
        "sentence": {"origin": model["origin"], "record_id": record["id"],
                     "content_digest": digest(_record_content(record, model["sources"]))},
        "snapshotDigests": [snapshot["digest"]], "provenance": [],
    }) for record in model["items"]]
    policy = _artifact("ConnectionPolicy", config, {"rules": deepcopy(config.get("rules", []))})
    descriptor = _artifact("LighthouseDescriptor", config, {
        "name": config["name"], "protocolVersions": ["0.1"], "profiles": [PROFILE],
        "actions": ["read", "link_overlap"],
        "artifactEndpoints": [{"kind": a["kind"], "locator": a["id"]} for a in [snapshot, *claims, policy]],
    })
    return {"format": FORMAT, "version": 1, "descriptor": descriptor, "snapshot": snapshot,
            "claims": claims, "policy": policy, "diagnostics": {"omitted_relations": omitted}}


def evaluate(claim, snapshot):
    verify(claim, "Claim")
    verify(snapshot, "Snapshot")
    statement, state = claim["payload"], snapshot["payload"]
    if (statement["profile"] != PROFILE or state["profile"] != PROFILE or statement["signature"] != SIGNATURE
            or state["signature"] != SIGNATURE or statement["sentenceMediaType"] != SENTENCE):
        return "indeterminate"
    sentence = statement["sentence"]
    if not isinstance(sentence, dict) or set(sentence) != {"origin", "record_id", "content_digest"}:
        return "indeterminate"
    model = state["model"]
    if (claim["issuer"] != snapshot["issuer"] or statement["context"] != state["context"]
            or statement["snapshotDigests"] != [snapshot["digest"]] or sentence["origin"] != model["origin"]):
        return "violated"
    record = next((r for r in model["items"] if r["id"] == sentence["record_id"]), None)
    if record is None or digest(_record_content(record, model["sources"])) != sentence["content_digest"]:
        return "violated"
    return "satisfied"


def validate_publication(package):
    _keys(package, {"format", "version", "descriptor", "snapshot", "claims", "policy", "diagnostics"})
    if package["format"] != FORMAT or type(package["version"]) is not int or package["version"] != 1:
        raise ValueError("Unsupported publication format")
    descriptor = verify(package["descriptor"], "LighthouseDescriptor")
    snapshot = verify(package["snapshot"], "Snapshot")
    policy = verify(package["policy"], "ConnectionPolicy")
    claims = _list(package["claims"])
    for claim in claims:
        verify(claim, "Claim")
    issuer = _uri(descriptor["issuer"])
    if any(a["issuer"] != issuer for a in [snapshot, policy, *claims]):
        raise ValueError("Publication issuers disagree")
    declaration, state = descriptor["payload"], snapshot["payload"]
    if (declaration["profiles"] != [PROFILE] or declaration["protocolVersions"] != ["0.1"]
            or declaration["actions"] != ["read", "link_overlap"] or state["profile"] != PROFILE
            or state["signature"] != SIGNATURE):
        raise ValueError("Unsupported publication profile")
    _context(state["context"])
    model = state["model"]
    _keys(model, {"schema_version", "origin", "title", "sources", "items", "relations"})
    _uri(model["origin"])
    normalized = _bundle({key: value for key, value in model.items() if key != "origin"})
    if any(normalized[key] != model[key] for key in normalized):
        raise ValueError("Publication model must include normalized record defaults")
    if not model["items"]:
        raise ValueError("Publication contains no selected records")
    referenced = {e["source_id"] for record in model["items"] + model["relations"] for e in record["evidence"]}
    if referenced != {s["id"] for s in model["sources"]}:
        raise ValueError("Publication contains unreferenced sources")
    expected_ids = {item["id"] for item in model["items"]}
    found = set()
    for claim in claims:
        if evaluate(claim, snapshot) != "satisfied":
            raise ValueError("Claim does not match its publication snapshot")
        identifier = claim["payload"]["sentence"]["record_id"]
        if identifier in found:
            raise ValueError("Duplicate record claim")
        found.add(identifier)
    if found != expected_ids:
        raise ValueError("Publication claims do not cover its selected records")
    expected_endpoints = [{"kind": a["kind"], "locator": a["id"]} for a in [snapshot, *claims, policy]]
    if declaration["artifactEndpoints"] != expected_endpoints:
        raise ValueError("Descriptor references do not match publication artifacts")
    _keys(package["diagnostics"], {"omitted_relations"})
    omitted = package["diagnostics"]["omitted_relations"]
    if type(omitted) is not int or omitted < 0:
        raise ValueError("Invalid projection diagnostics")
    return package


def restrict(package, item_ids, context, issued_at):
    validate_publication(package)
    _context(context)
    old_context = package["snapshot"]["payload"]["context"]
    old_path, new_path = old_context["path"], context["path"]
    if new_path[:len(old_path)] != old_path or (new_path == old_path and context != old_context):
        raise ValueError("Restriction requires the same context or an explicit descendant")
    if new_path != old_path and context["id"] == old_context["id"]:
        raise ValueError("Distinct publication contexts require distinct IDs")
    model = package["snapshot"]["payload"]["model"]
    requested = _list(item_ids)
    for identifier in requested:
        _text(identifier)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("Select one or more distinct item IDs explicitly")
    existing = {r["id"] for r in model["items"]}
    if set(requested) - existing:
        raise ValueError("Restriction cannot add records")
    if context == old_context:
        if set(requested) != existing:
            raise ValueError("Restriction to the same context must preserve the entire view")
        return deepcopy(package)
    config = {"issuer": package["descriptor"]["issuer"], "name": package["descriptor"]["payload"]["name"],
              "origin": model["origin"], "context": context, "item_ids": requested, "issued_at": issued_at}
    projected = publish({k: v for k, v in model.items() if k != "origin"}, config)
    return _publication(projected["snapshot"]["payload"]["model"], config,
                        [package["snapshot"]["digest"]], projected["diagnostics"]["omitted_relations"])


def overlap(receiver, offered, at):
    validate_publication(receiver)
    validate_publication(offered)
    left, right = receiver["snapshot"], offered["snapshot"]
    decisions = {}
    for action in ("read", "link_overlap"):
        decisions[action] = authorize(receiver["policy"], {
            "publisher": right["issuer"], "profile": PROFILE["id"], "domain": "research", "action": action,
            "context": right["payload"]["context"]["id"], "claimMediaType": SENTENCE,
            "purpose": "research", "audience": "self", "at": at, "evidence": [], "attestations": [],
        })
    result = {"receiver": left["issuer"], "publisher": right["issuer"], "decisions": decisions,
              "status": "denied", "record_pairs": []}
    if not all(d["allowed"] for d in decisions.values()):
        return result
    if left["payload"]["model"]["origin"] != right["payload"]["model"]["origin"]:
        return result | {"status": "unmapped", "detail": "Different declared collection origins require an explicit correspondence."}
    result["status"] = "compared"
    left_ids = {r["id"] for r in left["payload"]["model"]["items"]}
    right_ids = {r["id"] for r in right["payload"]["model"]["items"]}
    for identifier in sorted(left_ids & right_ids):
        accounts, fingerprints = [], []
        for package in (receiver, offered):
            snapshot = package["snapshot"]
            model = snapshot["payload"]["model"]
            record = next(r for r in model["items"] if r["id"] == identifier)
            content = _record_content(record, model["sources"])
            fingerprints.append(digest(content))
            claim = next(c for c in package["claims"] if c["payload"]["sentence"]["record_id"] == identifier)
            relations = [r for r in model["relations"] if identifier in {r["subject"], r["object"]}]
            referenced = {e["source_id"] for r in [record, *relations] for e in r["evidence"]}
            account_sources = sorted((s for s in model["sources"] if s["id"] in referenced), key=lambda s: s["id"])
            accounts.append({"publisher": snapshot["issuer"], "publication_context": snapshot["payload"]["context"],
                             "record": deepcopy(record), "sources": deepcopy(account_sources),
                             "snapshot_digest": snapshot["digest"], "claim_digest": claim["digest"],
                             "relations": deepcopy(relations)})
        result["record_pairs"].append({"origin": left["payload"]["model"]["origin"], "record_id": identifier,
                                       "comparison": "identical" if fingerprints[0] == fingerprints[1] else "different",
                                       "accounts": accounts})
    return result


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_number(_):
        raise ValueError("Nonfinite number is not JSON")

    with Path(path).open("rb") as stream:
        content = stream.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024:
        raise ValueError("Input exceeds 32 MiB")
    return json.loads(content.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_number)


def _write_new(path, value):
    path = Path(path)
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".atlas-lighthouse-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and refuses every existing destination,
        # including dangling symlinks. No source/output overwrite is possible.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publication = commands.add_parser("publish", help="Export explicitly selected research records")
    publication.add_argument("bundle")
    publication.add_argument("config")
    publication.add_argument("--output", required=True)
    validation = commands.add_parser("validate", help="Verify one publication's recorded-content integrity")
    validation.add_argument("publication")
    inspection = commands.add_parser("overlap", help="Inspect admitted shared records without merging")
    inspection.add_argument("receiver")
    inspection.add_argument("offered")
    inspection.add_argument("--at", default=None, help="Policy evaluation timestamp (default: current UTC time)")
    args = parser.parse_args(argv)
    try:
        if args.command == "publish":
            package = publish(read_json(args.bundle), read_json(args.config))
            validate_publication(package)
            _write_new(args.output, package)
            result = {"output": str(args.output), "issuer": package["descriptor"]["issuer"],
                      "records": len(package["claims"]), "snapshot_digest": package["snapshot"]["digest"]}
        elif args.command == "validate":
            package = validate_publication(read_json(args.publication))
            result = {"valid": True, "issuer": package["descriptor"]["issuer"], "records": len(package["claims"]),
                      "scope": "recorded content and references; biological truth and publisher identity are not certified"}
        else:
            result = overlap(read_json(args.receiver), read_json(args.offered),
                             args.at or datetime.now(timezone.utc).isoformat())
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2 if result.get("status") in {"denied", "unmapped"} else 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
