"""Reproduce an explicitly curated, read-only cleanup of saved Atlas notes."""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

from .legacy import _parse_note
from .render import render_bundle
from .validation import WorkbenchError, normalize_bundle


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _facets(target, additions):
    if not isinstance(additions, dict):
        raise WorkbenchError("facet additions must map axes to lists of nonblank strings")
    for axis, values in additions.items():
        if (not isinstance(axis, str) or not axis.strip() or not isinstance(values, list)
                or any(not isinstance(value, str) or not value.strip() for value in values)):
            raise WorkbenchError("facet additions must map axes to lists of nonblank strings")
        target[axis] = sorted(set(target.get(axis, [])) | set(values))


def _observations(text, item):
    """The exporter writes outgoing requires/enables, but incoming Enabled By."""
    in_dependencies, heading = False, None
    for number, line in enumerate(text.splitlines(), 1):
        if match := re.match(r"^##\s+(.+?)\s*$", line):
            in_dependencies = match[1].casefold() == "dependencies"
            heading = None
        elif match := re.match(r"^###\s+(.+?)\s*$", line):
            heading = match[1] if match[1] in {"Requires", "Enables", "Enabled By"} else None
        elif in_dependencies and heading:
            for target in re.findall(r"\[\[([^\]]+)\]\]", line):
                yield {"note_id": item["id"], "path": item["provenance"]["path"],
                       "line": number, "heading": heading, "target": target}


def _validate_decisions(config, items):
    expected = {"schema_version", "source_manifest_sha256", "layer_facets", "domain_facets",
                "merges", "annotations", "keep_separate"}
    if set(config) != expected or config["schema_version"] != 1:
        raise WorkbenchError("invalid cleanup decision schema")
    used = set()
    for merge in config["merges"]:
        if set(merge) != {"canonical", "aliases", "title", "rationale"} or not merge["aliases"]:
            raise WorkbenchError("invalid merge decision")
        ids = [merge["canonical"], *merge["aliases"]]
        if (len(set(ids)) != len(ids) or set(ids) & used or not set(ids) <= items.keys()
                or not merge["rationale"].strip() or not merge["title"].strip()):
            raise WorkbenchError("merge decision has missing, repeated, or overlapping identities")
        used.update(ids)
    for annotation in config["annotations"]:
        if (set(annotation) != {"id", "facets", "rationale"}
                or annotation["id"] not in items or not annotation["rationale"].strip()):
            raise WorkbenchError("invalid facet annotation")
    for distinction in config["keep_separate"]:
        ids = distinction["ids"]
        if len(set(ids)) < 2 or not set(ids) <= items.keys() or not distinction["rationale"].strip():
            raise WorkbenchError("invalid scope distinction")
    return {alias: merge["canonical"] for merge in config["merges"] for alias in merge["aliases"]}


def clean_vault(vault_path, decisions):
    """Return a portable bundle and reconciliation ledger; never write to the vault.

    Only pinned, explicit decisions merge records. Wikilinks resolve by exact
    saved filename stem, matching the legacy exporter; unresolved links stay in
    the ledger. Neither category placement nor cleanup creates reviewed edges.
    """
    vault = Path(vault_path).resolve(strict=True)
    paths = sorted((vault / "Nodes").rglob("*.md"))
    if not paths:
        raise WorkbenchError("legacy vault has no saved notes")
    original, texts, manifest = {}, {}, {}
    by_stem = defaultdict(list)
    observations = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise WorkbenchError(f"expected regular saved note: {path}")
        item = _parse_note(path, vault)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["provenance"]["sha256"]:
            raise WorkbenchError(f"source changed while reading: {path}")
        if item["id"] in original:
            raise WorkbenchError(f"duplicate original identity: {item['id']}")
        relative = item["provenance"]["path"]
        manifest[relative] = item["provenance"]["sha256"]
        original[item["id"]] = item
        texts[relative] = raw.decode("utf-8")
        by_stem[path.stem].append(item["id"])
        observations.extend(_observations(texts[relative], item))
    if _digest(manifest) != decisions.get("source_manifest_sha256"):
        raise WorkbenchError("source manifest differs from the reviewed snapshot; reassess decisions")
    aliases = _validate_decisions(decisions, original)
    for distinction in decisions["keep_separate"]:
        mapped = {aliases.get(id_, id_) for id_ in distinction["ids"]}
        if len(mapped) != len(distinction["ids"]):
            raise WorkbenchError("merge contradicts a scope distinction")

    items = deepcopy(original)
    for item in items.values():
        layer, domain = item["facets"]["layer"][0], item["facets"]["domain"][0]
        if layer not in decisions["layer_facets"] or domain not in decisions["domain_facets"]:
            raise WorkbenchError(f"unmapped legacy category on {item['id']}: {layer}/{domain}")
        item["provenance"].update(legacy_layer=layer, legacy_domain=domain)
        item["facets"] = {}
        _facets(item["facets"], decisions["layer_facets"][layer])
        _facets(item["facets"], decisions["domain_facets"][domain])
        item["context"] = {
            "classification": "Facets reorganize saved category labels; individual scientific scope has not been reassessed.",
            "legacy_status": "Imported as a proposed question; original kind, claims, scores and citations are not validated here.",
        }
    for annotation in decisions["annotations"]:
        item = items[annotation["id"]]
        _facets(item["facets"], annotation["facets"])
        item["context"]["facet_annotation"] = annotation["rationale"]

    merge_accounts = []
    for merge in decisions["merges"]:
        ids = [merge["canonical"], *merge["aliases"]]
        canonical = items[merge["canonical"]]
        descriptions = []
        for id_ in ids:
            source = original[id_]
            descriptions.append(f"Original formulation ({id_}; {source['title']}):\n{source['summary']}")
            _facets(canonical["facets"], items[id_]["facets"])
        canonical["title"] = merge["title"]
        canonical["summary"] = "\n\n".join(descriptions)
        canonical["context"]["consolidation"] = merge["rationale"]
        canonical["provenance"]["aliases"] = ", ".join(merge["aliases"])
        canonical["provenance"]["contributing_notes"] = _json([original[id_]["provenance"] for id_ in ids])
        merge_accounts.append({**merge, "source_notes": {
            original[id_]["provenance"]["path"]: texts[original[id_]["provenance"]["path"]] for id_ in ids}})
        for alias in merge["aliases"]:
            del items[alias]

    grouped, withheld = defaultdict(list), []
    for observation in observations:
        candidates = by_stem.get(observation["target"], [])
        if len(candidates) != 1:
            withheld.append({**observation, "reason": "missing_target" if not candidates else "ambiguous_target",
                             "candidate_ids": candidates})
            continue
        subject, object_ = observation["note_id"], candidates[0]
        predicate = "requires" if observation["heading"] == "Requires" else "enables"
        if observation["heading"] == "Enabled By":
            subject, object_ = object_, subject
        subject, object_ = aliases.get(subject, subject), aliases.get(object_, object_)
        if subject == object_:
            withheld.append({**observation, "reason": "self_dependency", "canonical_id": subject})
            continue
        grouped[(subject, predicate, object_)].append(observation)

    relations, relation_observations = [], {}
    directions = defaultdict(list)
    for (subject, predicate, object_), accounts in sorted(grouped.items()):
        id_ = "legacy-edge:" + _digest([subject, predicate, object_])
        relations.append({
            "id": id_, "subject": subject, "predicate": predicate, "object": object_,
            "status": "proposed",
            "rationale": "Inherited from saved dependency headings; direction follows the original exporter. Scientific necessity and sufficiency have not been reviewed.",
            "context": {
                "origin": "Legacy vault snapshot; repeated observations are one assertion, not independent evidence.",
                "source_locations": "; ".join(f"{a['path']}:{a['line']} ({a['heading']})" for a in accounts),
            }, "evidence": [],
        })
        relation_observations[id_] = accounts
        direction = (object_, subject) if predicate == "requires" else (subject, object_)
        directions[direction].append(id_)
    opposed = [{"items": [left, right], "forward_relations": ids,
                "reverse_relations": directions[(right, left)]}
               for (left, right), ids in sorted(directions.items())
               if left < right and (right, left) in directions]
    bundle = normalize_bundle({"schema_version": 1, "title": "Atlas — cleaned archive · unreviewed research questions",
                               "sources": [], "items": sorted(items.values(), key=lambda i: i["id"]),
                               "relations": relations})
    retained = sum(map(len, relation_observations.values()))
    audit = {
        "schema_version": 1,
        "scope": "Saved notes only. Cleanup decisions are editorial, not scientific assessments. Original files remain authoritative for unmigrated fields and history.",
        "source_manifest_sha256": _digest(manifest), "source_manifest": manifest,
        "decisions_sha256": _digest(decisions), "decisions": decisions,
        "aliases": aliases, "original_items": sorted(original.values(), key=lambda i: i["id"]),
        "merges": merge_accounts, "relation_observations": relation_observations,
        "withheld_links": withheld, "opposed_dependency_pairs": opposed,
        "counts": {"original_notes": len(original), "canonical_items": len(items), "aliases": len(aliases),
                   "link_observations": len(observations), "retained_link_observations": retained,
                   "relations": len(relations), "deduplicated_link_observations": retained - len(relations),
                   "withheld_link_observations": len(withheld), "opposed_dependency_pairs": len(opposed)},
    }
    return bundle, audit


def write_cleanup(vault_path, decisions, output):
    """Write three complete artifacts into an exclusively created directory."""
    vault, output = Path(vault_path).resolve(strict=True), Path(output)
    if output.resolve().is_relative_to(vault):
        raise WorkbenchError("cleanup output cannot be inside the source vault")
    if output.exists() or output.is_symlink():
        raise WorkbenchError(f"cleanup output already exists: {output}")
    bundle, audit = clean_vault(vault, decisions)
    contents = {"graph.json": json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
                "audit.json": json.dumps(audit, indent=2, ensure_ascii=False) + "\n",
                "index.html": render_bundle(bundle)}
    output.mkdir()  # Exclusive reservation; never replace an existing result.
    written = []
    try:
        for name, content in contents.items():
            path = output / name
            with path.open("x", encoding="utf-8") as stream:
                written.append(path)
                stream.write(content)
    except Exception:
        for path in written:
            path.unlink()
        output.rmdir()
        raise
    return audit["counts"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault", type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new directory outside the source vault")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.decisions.read_text(encoding="utf-8"))
        print(json.dumps(write_cleanup(args.vault, config, args.output), sort_keys=True))
    except (WorkbenchError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
