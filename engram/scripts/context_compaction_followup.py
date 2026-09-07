#!/usr/bin/env python3
"""A separate 300-second compaction continuation of the frozen first study."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_codex import CodexProvider  # noqa: E402
from scripts import context_continuity_pilot as pilot  # noqa: E402

ARM = "append_compact_300s_followup"
BOUNDED_ARM = "append_compact_bounded_followup"
COMPACTION_TIMEOUT = 300


def project_summary(summary, allowed):
    """Admit a prefix of whole model-written entries, preserving their provenance."""
    pilot.validate_summary(summary, allowed, max_bytes=None)
    admitted = []
    for entry in summary:
        if len(pilot.canonical(admitted + [entry]).encode()) > pilot.SUMMARY_CAP:
            break
        admitted.append(entry)
    return admitted


def _compactor(bounded):
    provider = CodexProvider(timeout=COMPACTION_TIMEOUT)
    if bounded:
        provider.command.extend(["-c", 'model_reasoning_effort="low"'])
    return provider


def _parent_manifest(parent):
    raw = (parent / "sha256.json").read_bytes()
    for name, digest in json.loads(raw).items():
        if Path(name).name != name or hashlib.sha256((parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Parent evidence fingerprint changed")
    return hashlib.sha256(raw).hexdigest()


def _chunk(transcript, summary, offset):
    """Reconstruct admission exactly, to verify the failed request before dispatch."""
    chunk = []
    payload = None
    for entry in transcript[offset:]:
        trial = chunk + [entry]
        candidate = pilot.payload_for(pilot.COMPACT_INSTRUCTIONS, [{"role": "user", "content": pilot.canonical({"previous_summary": summary, "append": trial})}])
        try:
            pilot.admit(candidate)
        except ValueError:
            break
        chunk, payload = trial, candidate
    if payload is None:
        raise ValueError("No compaction chunk fits")
    return offset + len(chunk), payload


def initialize(parent, directory, *, bounded=False):
    parent, directory = Path(parent), Path(directory)
    if parent.resolve() == directory.resolve():
        raise ValueError("Follow-up must use a separate directory")
    fingerprint = _parent_manifest(parent)
    fixture, digest = pilot.load_fixture(parent / "fixture.json")
    parent_config = json.loads((parent / "configuration.json").read_text())
    if digest != parent_config["fixture_sha256"] or parent_config["noise_events"] != pilot.NOISE_EVENTS:
        raise ValueError("Parent fixture or corpus settings changed")
    successful, failed = pilot._records(parent / "compactions.jsonl")
    if successful["step"] != 0 or "error" in successful or failed["step"] != 1 or failed.get("error", {}).get("message") != "Codex episode timeout":
        raise ValueError("Expected one successful summary followed by its recorded timeout")
    _, transcript = pilot._corpus(fixture)
    offset, first = _chunk(transcript[:-6], [], 0)
    if pilot.admit(first) != successful["request_digest"] or offset != successful["through_entries"]:
        raise ValueError("Imported summary request changed")
    pilot.validate_summary(successful["summary"], pilot._ids(first))
    _, second = _chunk(transcript[:-6], successful["summary"], offset)
    if pilot.admit(second) != failed["request_digest"]:
        raise ValueError("Failed continuation request changed")
    config = {**parent_config, "profile": ARM, "parent_manifest_sha256": fingerprint,
              "compaction_timeout_seconds": COMPACTION_TIMEOUT, "answer_timeout_seconds": 120,
              "continuation_request_digest": failed["request_digest"], "historical_answer_records": 200}
    if bounded:
        config.update(profile=BOUNDED_ARM, summary_admission="whole_entry_prefix", compaction_reasoning_effort="low")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "configuration.json"
    if path.exists() and json.loads(path.read_text()) != config:
        raise ValueError("Follow-up configuration changed")
    snapshot = directory / "fixture.json"
    if snapshot.exists() and snapshot.read_bytes() != (parent / "fixture.json").read_bytes():
        raise ValueError("Follow-up fixture fingerprint changed")
    snapshot.write_bytes((parent / "fixture.json").read_bytes())
    pilot._save(path, config)
    imported = {**successful, "imported_from": fingerprint}
    records = pilot._records(directory / "compactions.jsonl")
    if records:
        if records[0] != imported:
            raise ValueError("Imported compaction changed")
    else:
        pilot._journal(directory / "compactions.jsonl", imported)
    return config


def prepare(parent, directory, *, compactor_factory=None, bounded=False):
    parent, directory = Path(parent), Path(directory)
    config = initialize(parent, directory, bounded=bounded)
    cells_path = directory / "cells.json"
    if cells_path.exists():
        return json.loads(cells_path.read_text())
    fixture, _ = pilot.load_fixture(directory / "fixture.json")
    _, transcript = pilot._corpus(fixture)
    failure = None
    try:
        summary = pilot._compact_prefix(transcript[:-6], directory,
            provider_factory=compactor_factory or (lambda: _compactor(bounded)),
            summary_validator=project_summary if bounded else pilot.validate_summary)
    except (ValueError, RuntimeError, KeyError) as exc:
        summary = []
        failure = f"Follow-up compaction unavailable: {type(exc).__name__}: {exc}"
    cells = []
    for original in json.loads((parent / "cells.json").read_text()):
        if original["arm"] != "append_compact_comparator":
            continue
        cell = copy.deepcopy(original)
        cell.update(arm=config["profile"], cell_id=original["probe_id"] + "/" + config["profile"])
        cell.pop("preparation_error", None)
        cell["payload"]["input"][0]["content"] = pilot.canonical({"fallible_compressed_history": summary})
        if failure:
            cell["preparation_error"] = failure
        cells.append(cell)
    if len(cells) != len(fixture["probes"]):
        raise ValueError("Parent comparator cells are incomplete")
    pilot._save(cells_path, cells)
    return cells


def report(parent, directory, *, bounded=False):
    parent, directory = Path(parent), Path(directory)
    config = initialize(parent, directory, bounded=bounded)
    result = pilot.report(directory)
    records = pilot._records(directory / "compactions.jsonl")
    result["scope"] = "Exploratory 300-second compaction continuation; historical comparison arms were generated earlier. Human ratings unset."
    if bounded:
        result["scope"] = "Exploratory whole-entry summary admission with low auxiliary reasoning; historical answers generated earlier. Human ratings unset."
    result["summary_projections"] = []
    for record in records:
        if "error" in record or record.get("imported_from"):
            continue
        original = json.loads(pilot._text(record["response"]))["summary"]
        result["summary_projections"].append({"step": record["step"],
            "raw_summary_bytes": len(pilot.canonical(original).encode()),
            "admitted_summary_bytes": len(pilot.canonical(record["summary"]).encode()),
            "omitted_entries": len(original) - len(record["summary"]),
            "omitted_entry_source_ids": [s for r in original[len(record["summary"]):] for s in r["source_ids"]]})
    result["compaction_usage_and_timing"] = pilot._capture_stats([r for r in records if not r.get("imported_from")])
    result["imported_compaction_usage_and_timing"] = pilot._capture_stats([r for r in records if r.get("imported_from")])
    historical = json.loads((parent / "report.json").read_text())
    result["historical_arms"] = {k: historical["arms"][k] for k in ("dynamic", "local_agent_context")}
    parent_key = json.loads((parent / "review-key.json").read_text())
    historical_review = [r for r in json.loads((parent / "blinded-review.json").read_text())
                        if parent_key[r["review_id"]].split("/")[-1] in result["historical_arms"]]
    combined = historical_review + json.loads((directory / "blinded-review.json").read_text())
    random.Random(pilot.SEED).shuffle(combined)
    pilot._save(directory / "combined-review.json", combined)
    pilot._save(directory / "combined-review-key.json", {
        **{r["review_id"]: {"cell_id": parent_key[r["review_id"]], "origin": "original-study"} for r in historical_review},
        **{k: {"cell_id": v, "origin": config["profile"]} for k, v in json.loads((directory / "review-key.json").read_text()).items()},
    })
    pilot._save(directory / "report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent", type=Path, help="Unpacked original continuity-capture evidence")
    parser.add_argument("directory", type=Path, help="Separate follow-up output directory")
    parser.add_argument("--bounded", action="store_true", help="Separate profile: whole-entry admission and low auxiliary reasoning")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--report", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with pilot._lease(args.directory, "study.lock"):
        if args.run:
            cells = prepare(args.parent, args.directory, bounded=args.bounded)
            pilot.run_cells(cells, args.directory)
        print(json.dumps(report(args.parent, args.directory, bounded=args.bounded), indent=2))


if __name__ == "__main__":
    main()
