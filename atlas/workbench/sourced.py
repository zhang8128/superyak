"""North-star test 5: Atlas claims that cross with their sources' identity.

The design is docs/superpowers/specs/2026-11-22-claim-crossing-design.md (revision 6, 84fafe71, approved under station
law section 3). This module sits beside `lighthouse.py`'s projection, under its own profile, and builds on
`lighthouse_wire`'s seal, verify and authorize.

This first part is the source keys and the comparison of two sources. A strong key proves sameness, never difference.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .store import _normalized_title

KEY_FUNCTION = "source_key/1"
DOI_HOSTS = frozenset({"doi.org", "dx.doi.org", "www.doi.org"})
_DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[-._;()/:<>A-Za-z0-9]+", re.IGNORECASE)
_DOI_START = re.compile(r"10\.\d{4,9}/.")  # a prefix, a slash and a suffix: the citation pattern's shape (amendment 1)
_TRAILING = ".,;:"
_PAIRS = {")": "(", "]": "[", ">": "<"}
DEFAULT_PORTS = {"http": 80, "https": 443}


def _strip_trailing(doi: str) -> str:
    """Remove trailing . , ; : and any closing ) ] > while the match holds more closing than opening ones of that
    kind, repeatedly, until none is left (spec E1, G3)."""
    while doi:
        last = doi[-1]
        if last in _TRAILING:
            doi = doi[:-1]
        elif last in _PAIRS and doi.count(last) > doi.count(_PAIRS[last]):
            doi = doi[:-1]
        else:
            break
    return doi


def _doi_from_url(parts) -> str | None:
    """A doi.org url's whole path, decoded and lowercased, never through the regex, so < and > stay in it (C5, D5)."""
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in DOI_HOSTS:
        return None
    path = unquote(parts.path).lstrip("/")
    if path[:4].lower() == "doi:":
        path = path[4:]
    if path.endswith("/"):
        path = path[:-1]
    if not _DOI_START.match(path):
        return None
    return path.lower()


def _doi_from_citation(citation: str) -> str | None:
    """The first DOI in the citation, percent-decoded; none when it holds two distinct ones."""
    found = {_strip_trailing(match).lower() for match in _DOI_IN_TEXT.findall(unquote(citation))}
    found.discard("")
    return found.pop() if len(found) == 1 else None


def _url_key(parts) -> str:
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    if port is not None and port != DEFAULT_PORTS.get(parts.scheme.lower()):
        host = f"{host}:{port}"
    path = parts.path[:-1] if parts.path.endswith("/") else parts.path
    return "url:" + urlunsplit(("https", host, path, parts.query, ""))


def source_key(record: dict) -> dict:
    """An Atlas source's keys: a strong url key (always), a strong DOI key when one is found, and a weak title key."""
    parts = urlsplit(record["url"])
    doi = _doi_from_url(parts)
    if doi is None:
        doi = _doi_from_citation(record.get("citation") or "")
    title = _normalized_title(record.get("title") or "")
    return {"url": _url_key(parts), "doi": f"doi:{doi}" if doi else None,
            "title": f"title:{title}:{record['year']}" if title else None, "fn": KEY_FUNCTION}


def _title_alone(key: dict) -> str | None:
    """The normalised title without the year, as rules 1 and 2 and rule 4 compare it (E4, G1)."""
    if key.get("title") is None:
        return None
    return key["title"].rsplit(":", 1)[0]


def compare_sources(a: dict, b: dict) -> str:
    """Two sources' keys compared by five rules in order; the first that holds wins (D1, E4, G1)."""
    title_a, title_b = _title_alone(a), _title_alone(b)
    same_title = title_a is not None and title_a == title_b
    if a["doi"] and b["doi"] and a["doi"] != b["doi"]:
        return "unclear" if same_title else "distinct"          # rules 2 and 1: a DOI decides
    strong_a = {a["url"], a["doi"]} - {None}
    strong_b = {b["url"], b["doi"]} - {None}
    if strong_a & strong_b or (a["title"] is not None and a["title"] == b["title"]):
        return "match"                                           # rule 3
    if same_title:
        return "unclear"                                         # rule 4: one title, different years
    return "distinct"                                            # rule 5


# --- the sourced publication (spec: "The sourced publication") -------------------------------------------------

from copy import deepcopy  # noqa: E402

from .lighthouse import _bundle, _context, _keys, _list, _record_content, _text, _uri  # noqa: E402
from .lighthouse_wire import digest, seal, verify  # noqa: E402

SOURCED_PROFILE = {"id": "urn:superyak:profile:atlas-sourced", "version": "1"}
SOURCED_SIGNATURE = {"id": "urn:superyak:atlas-sourced", "version": "1"}
SOURCED_SENTENCE = "application/vnd.superyak.atlas-sourced-claim+json"
SOURCED_FORMAT = "atlas-sourced-publication"
ACTIONS = ["read", "link_overlap", "retain", "reshare"]


def _artifact(kind, issuer, issued_at, payload):
    return seal(kind, issuer, f"{issuer}:{kind.lower()}:{digest(payload)['value']}", issued_at, payload)


def _crossing_item(record, issuer):
    """An item as it crosses: no provenance map (sessions and paths), and no reviewer's name. A reviewed record names
    the publishing lighthouse instead, and keeps its time; any other has both fields empty (spec C3, D4)."""
    item = {key: deepcopy(value) for key, value in record.items() if key != "provenance"}
    if item["status"] == "reviewed":
        item["reviewed_by"] = issuer
    else:
        item["reviewed_by"] = item["reviewed_at"] = ""
    return item


def _keyed(source):
    return {**deepcopy(source), "keys": source_key(source)}


def publish_sourced(bundle, config):
    """What lighthouse.publish makes, under the sourced profile: each source carries its keys, each Claim names its
    Snapshot and, for a copy, the Claims it was copied from (config["copied_from"]: item id -> digest references)."""
    _keys(config, {"issuer", "name", "origin", "context", "item_ids", "issued_at"},
          {"rules", "copied_from", "lineage", "carried"})
    issuer = _uri(config["issuer"])
    _uri(config["origin"])
    _text(config["name"])
    _context(config["context"])
    ids = _list(config["item_ids"])
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Select one or more distinct item IDs explicitly")
    normalized = _bundle(bundle)
    selected = set(ids)
    if selected - {item["id"] for item in normalized["items"]}:
        raise ValueError("Unknown selected item ID")
    copied_from = config.get("copied_from", {})
    if set(copied_from) - selected:
        raise ValueError("copied_from names an item that isn't selected")
    items = sorted((i for i in normalized["items"] if i["id"] in selected), key=lambda i: i["id"])
    relations = sorted((r for r in normalized["relations"] if {r["subject"], r["object"]} <= selected),
                       key=lambda r: r["id"])
    referenced = {e["source_id"] for record in items + relations for e in record["evidence"]}
    sources = [_keyed(s) for s in sorted((s for s in normalized["sources"] if s["id"] in referenced),
                                          key=lambda s: s["id"])]
    model = {"schema_version": 1, "origin": config["origin"], "title": normalized["title"], "sources": sources,
             "items": [_crossing_item(i, issuer) for i in items], "relations": deepcopy(relations)}
    snapshot = _artifact("Snapshot", issuer, config["issued_at"], {
        "profile": SOURCED_PROFILE, "signature": SOURCED_SIGNATURE, "context": config["context"], "model": model,
        "lineage": list(config.get("lineage", []))})
    claims = []
    for record in model["items"]:
        provenance = list(copied_from.get(record["id"], []))
        claims.append(_artifact("Claim", issuer, config["issued_at"], {
            "profile": SOURCED_PROFILE, "signature": SOURCED_SIGNATURE, "context": config["context"],
            "sentenceMediaType": SOURCED_SENTENCE,
            "sentence": {"origin": model["origin"], "record_id": record["id"],
                         "content_digest": digest(_record_content(record, model["sources"]))},
            "snapshotDigests": [snapshot["digest"]], "provenance": provenance}))
    policy = _artifact("ConnectionPolicy", issuer, config["issued_at"], {"rules": deepcopy(config.get("rules", []))})
    descriptor = _artifact("LighthouseDescriptor", issuer, config["issued_at"], {
        "name": config["name"], "protocolVersions": ["0.1"], "profiles": [SOURCED_PROFILE], "actions": ACTIONS,
        "artifactEndpoints": [{"kind": a["kind"], "locator": a["id"]} for a in [snapshot, *claims, policy]]})
    carried = [_carried(entry) for entry in _list(config.get("carried", []))]
    return {"format": SOURCED_FORMAT, "version": 1, "descriptor": descriptor, "snapshot": snapshot,
            "claims": claims, "policy": policy, "carried": carried}


def _carried(entry):
    """A foreign Claim kept exactly as its issuer sealed it, with the foreign Snapshot it names (spec C4)."""
    _keys(entry, {"claim", "snapshot"})
    foreign, held = verify(entry["claim"], "Claim"), verify(entry["snapshot"], "Snapshot")
    if foreign["payload"]["snapshotDigests"] != [held["digest"]]:
        raise ValueError("A carried claim doesn't name its carried snapshot")
    return {"claim": deepcopy(foreign), "snapshot": deepcopy(held)}


def validate_sourced(package):
    """Refuses a sourced publication whose artifacts, keys, content digests, snapshot names or crossing rules don't
    hold. The receiver recomputes every key from its record (spec: "A strong key proves sameness")."""
    _keys(package, {"format", "version", "descriptor", "snapshot", "claims", "policy", "carried"})
    if package["format"] != SOURCED_FORMAT or package["version"] != 1:
        raise ValueError("Unsupported sourced publication format")
    descriptor = verify(package["descriptor"], "LighthouseDescriptor")
    snapshot = verify(package["snapshot"], "Snapshot")
    policy = verify(package["policy"], "ConnectionPolicy")
    claims = [verify(c, "Claim") for c in _list(package["claims"])]
    issuer = _uri(descriptor["issuer"])
    if any(a["issuer"] != issuer for a in [snapshot, policy, *claims]):
        raise ValueError("Publication issuers disagree")
    declaration, state = descriptor["payload"], snapshot["payload"]
    if (declaration["profiles"] != [SOURCED_PROFILE] or declaration["actions"] != ACTIONS
            or state["profile"] != SOURCED_PROFILE or state["signature"] != SOURCED_SIGNATURE):
        raise ValueError("Unsupported publication profile")
    model = state["model"]
    _keys(model, {"schema_version", "origin", "title", "sources", "items", "relations"})
    for source in _list(model["sources"]):
        if "keys" not in source:
            raise ValueError("A source carries no keys")
        plain = {k: v for k, v in source.items() if k != "keys"}
        if source["keys"] != source_key(plain):
            raise ValueError(f"Source {plain.get('id')!r} carries keys that don't match its record")
    for item in _list(model["items"]):
        if "provenance" in item:
            raise ValueError("An item carries its provenance map")
        expected = issuer if item.get("status") == "reviewed" else ""
        if item.get("reviewed_by") != expected:
            raise ValueError("An item carries a reviewer's name")
    _bundle({"schema_version": 1, "title": model["title"],
             "sources": [{k: v for k, v in s.items() if k != "keys"} for s in model["sources"]],
             "items": model["items"], "relations": model["relations"]})
    records = {item["id"]: item for item in model["items"]}
    found = set()
    for claim in claims:
        payload = claim["payload"]
        if payload["profile"] != SOURCED_PROFILE or payload["sentenceMediaType"] != SOURCED_SENTENCE:
            raise ValueError("A claim isn't under the sourced profile")
        if payload["snapshotDigests"] != [snapshot["digest"]]:
            raise ValueError("A claim names another snapshot")
        record_id = payload["sentence"]["record_id"]
        if record_id not in records or record_id in found:
            raise ValueError("A claim names no record of its snapshot, or one twice")
        if payload["sentence"]["content_digest"] != digest(_record_content(records[record_id], model["sources"])):
            raise ValueError("A claim's content digest doesn't match its record")
        found.add(record_id)
    if found != set(records):
        raise ValueError("The claims don't cover the snapshot's records")
    expected_endpoints = [{"kind": a["kind"], "locator": a["id"]} for a in [snapshot, *claims, policy]]
    if declaration["artifactEndpoints"] != expected_endpoints:
        raise ValueError("Descriptor references do not match publication artifacts")
    for entry in _list(package["carried"]):
        _carried(entry)
    return package
