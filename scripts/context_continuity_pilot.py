#!/usr/bin/env python3
"""Capture a preliminary, synthetic three-arm continuity comparison.

Uses the managed Codex subscription only when explicitly run. Human correctness
and relational-continuity ratings remain unset. See the frozen protocol in docs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_codex import CodexProvider  # noqa: E402
from context_runtime import INSTRUCTIONS  # noqa: E402
from scripts.context_retrieval_benchmark import FIXTURE, load_fixture, run_benchmark  # noqa: E402

MODEL = "gpt-6-astra"
CEILING = 16_000
SUMMARY_CAP = 6000
NOISE_EVENTS = 1000
SEED = 20260906
ANSWER_INSTRUCTIONS = """
For this evaluation, return one JSON object with exactly two fields:
"answer": a natural answer to the latest question, and "source_ids": an array
of the original source IDs supporting it. Use only IDs actually supplied in
your context. If evidence is missing, say what is unknown; do not guess.
Preserve attribution, revisions, uncertainty, and the user's personal meaning.
Do not emit memory, signal, or delegation tags. No external action is available.
"""
COMPACT_INSTRUCTIONS = """Compress the supplied chronological conversation prefix
into a durable, fallible memory. You have no future questions. Preserve names,
precise details, personal meaning, required constraints, corrections and which
earlier claims they replace, unresolved disagreements with speakers, and the
boundary between quoted source text and actual instructions. Routine repetition
may be summarized briefly. Retain original source IDs for each summary entry.
Return only JSON: {"summary": [{"text": "...", "source_ids": ["..."]}]}.
The entire summary array must be at most 6000 UTF-8 bytes. Do not invent IDs.
"""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def admit(payload):
    raw = canonical(payload).encode()
    if len(raw) > CEILING:
        raise ValueError("Supplied envelope exceeds the 16000-byte ceiling")
    return hashlib.sha256(raw).hexdigest()


def payload_for(instructions, inputs):
    return {"model": MODEL, "instructions": instructions, "input": inputs, "tools": [],
            "store": False, "truncation": "disabled", "max_output_tokens": 2048}


def _text(response):
    return "\n".join(part["text"] for item in response.get("output", []) if item.get("type") == "message"
                     for part in item.get("content", []) if part.get("type") == "output_text")


def _ids(value):
    return set(re.findall(r"(?:ev-[A-Za-z0-9_-]+|noise:\d+)", canonical(value)))


def answer_checks(raw, payload, expected):
    result = {"parse_ok": False, "unavailable_citations": [], "expected_sources_cited": False,
              "human_correctness": None, "human_relational_continuity": None}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("answer"), str) or not isinstance(parsed.get("source_ids"), list) or any(not isinstance(x, str) for x in parsed["source_ids"]):
            return result
        cited = set(parsed["source_ids"]) | _ids(parsed["answer"])
        result.update(parse_ok=True, unavailable_citations=sorted(cited - _ids(payload)),
                      expected_sources_cited=set(expected) <= cited)
    except (ValueError, TypeError):
        pass
    return result


def validate_summary(summary, allowed):
    if not isinstance(summary, list) or any(not isinstance(r, dict) or not isinstance(r.get("text"), str)
        or not isinstance(r.get("source_ids"), list) or any(not isinstance(s, str) for s in r["source_ids"]) for r in summary):
        raise ValueError("Malformed summary")
    if len(canonical(summary).encode()) > SUMMARY_CAP:
        raise ValueError("Summary exceeds its byte cap")
    cited = {s for r in summary for s in r["source_ids"]} | _ids(summary)
    if not cited <= allowed:
        raise ValueError("Summary cites an unavailable source")
    return summary


def _journal(path, item):
    with path.open("a") as handle:
        handle.write(canonical(item) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


@contextmanager
def _lease(directory, name):
    with (directory / name).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Evaluation directory is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_cells(cells, directory, *, provider_factory=CodexProvider, workers=2):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with _lease(directory, "answers.lock"):
        return _run_cells(cells, directory, provider_factory=provider_factory, workers=workers)


def _run_cells(cells, directory, *, provider_factory, workers):
    if not 1 <= workers <= 2:
        raise ValueError("At most two concurrent episodes are allowed")
    dispatched = {r["cell_id"]: r for r in _records(directory / "dispatches.jsonl")}
    answered = {r["cell_id"]: r for r in _records(directory / "answers.jsonl")}
    if len({c["cell_id"] for c in cells}) != len(cells):
        raise ValueError("Duplicate evaluation cell")
    pending = []
    for cell in cells:
        digest = hashlib.sha256(canonical(cell["payload"]).encode()).hexdigest()
        previous = dispatched.get(cell["cell_id"], answered.get(cell["cell_id"]))
        if previous is not None:
            if previous["request_digest"] != digest:
                raise ValueError("A previously dispatched request changed")
        else:
            pending.append(cell)
    random.Random(SEED).shuffle(pending)
    lock = threading.Lock()

    def execute(cell):
        digest = hashlib.sha256(canonical(cell["payload"]).encode()).hexdigest()
        started = time.monotonic()
        record = {k: cell[k] for k in ("cell_id", "probe_id", "arm")}
        record["request_digest"] = digest
        provider = None
        try:
            if cell.get("preparation_error"):
                raise ValueError(cell["preparation_error"])
            admit(cell["payload"])
            with lock:
                _journal(directory / "dispatches.jsonl", {"cell_id": cell["cell_id"], "request_digest": digest})
            provider = provider_factory()
            response = provider.generate(cell["payload"])
            raw = _text(response)
            record.update(response=response, raw_answer=raw, checks=answer_checks(raw, cell["payload"], cell["expected_source_ids"]))
        except Exception as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if provider is not None:
                provider.close()
        record["elapsed_seconds"] = time.monotonic() - started
        with lock:
            _journal(directory / "answers.jsonl", record)
            print(f"Captured {cell['cell_id']}", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(execute, pending))


def _corpus(fixture):
    originals = [r for p in fixture["probes"] for r in p["sources"]]
    noise = [{"id": f"noise:{i}", "role": "user" if i % 2 == 0 else "assistant",
              "content": f"Routine check {i:08d}. {fixture['noise']}"} for i in range(NOISE_EVENTS)]
    return originals, originals + noise


def _legacy_payloads(fixture, transcript):
    # Use real recall and formatting, without invoking LocalAgent initialization
    # (which could resolve a live DB/signal bus) or response side effects.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from engine import EngineCore
    from local_agent import LocalAgent
    with tempfile.TemporaryDirectory(prefix="engram-pilot-legacy-") as directory:
        engine = EngineCore(Path(directory) / "synthetic.db")
        try:
            if engine.get_instincts() or engine.get_core_episodes():
                raise ValueError("Synthetic baseline must start without identity memory")
            sources, _ = _corpus(fixture)
            vectors = engine.embeddings.embed([r["content"] for r in sources])
            for source, vector in zip(sources, vectors, strict=True):
                engine.storage.add_episode(id=source["id"], session_id="synthetic-pilot", content=source["content"], embedding=vector)
                engine.storage.set_episode_source(source["id"], source["id"])
            agent = object.__new__(LocalAgent)
            agent._engine, agent.model, agent.instance, agent.enable_claude = engine, MODEL, None, False
            payloads = {}
            for probe in fixture["probes"]:
                agent.conversation = (transcript[-6:] + probe["recent"])[-6:]
                prompt = agent.build_prompt(probe["question"])
                payloads[probe["id"]] = payload_for(agent.build_system_prompt() + ANSWER_INSTRUCTIONS, [{"role": "user", "content": prompt}])
            return payloads
        finally:
            engine.close()


def _compact_prefix(transcript, directory, provider_factory=CodexProvider):
    cache = {r["step"]: r for r in _records(directory / "compactions.jsonl")}
    dispatched = {r["step"]: r for r in _records(directory / "compaction-dispatches.jsonl")}
    summary, offset, step = [], 0, 0
    while offset < len(transcript):
        if step >= 64:
            raise ValueError("Compaction call limit reached")
        chunk = []
        while offset + len(chunk) < len(transcript):
            trial = chunk + [transcript[offset + len(chunk)]]
            candidate = payload_for(COMPACT_INSTRUCTIONS, [{"role": "user", "content": canonical({"previous_summary": summary, "append": trial})}])
            try:
                admit(candidate)
            except ValueError:
                break
            chunk, payload = trial, candidate
        if not chunk:
            raise ValueError("One compaction entry exceeds the envelope ceiling")
        digest = admit(payload)
        if step in dispatched and dispatched[step]["request_digest"] != digest:
            raise ValueError("A dispatched compaction request changed")
        if step in cache:
            record = cache[step]
            if record["request_digest"] != digest or "error" in record:
                raise ValueError("Cached compaction failed or changed; do not silently replay")
        else:
            if step in dispatched:
                raise ValueError("Compaction dispatch is uncertain; do not replay")
            _journal(directory / "compaction-dispatches.jsonl", {"step": step, "request_digest": digest})
            provider = provider_factory()
            started = time.monotonic()
            response = None
            try:
                response = provider.generate(payload)
                value = json.loads(_text(response))
                if not isinstance(value, dict) or "summary" not in value:
                    raise ValueError("Malformed compaction response: expected a summary object")
                summary = validate_summary(value["summary"], _ids(payload))
                record = {"step": step, "request_digest": digest, "summary": summary, "response": response, "elapsed_seconds": time.monotonic() - started, "through_entries": offset + len(chunk)}
                _journal(directory / "compactions.jsonl", record)
            except Exception as exc:
                failure = {"step": step, "request_digest": digest, "elapsed_seconds": time.monotonic() - started,
                           "error": {"type": type(exc).__name__, "message": str(exc)}}
                if response is not None:
                    failure.update(response=response, raw_answer=_text(response))
                _journal(directory / "compactions.jsonl", failure)
                raise
            finally:
                provider.close()
            print(f"Compacted prefix through {offset + len(chunk)}/{len(transcript)} entries", file=sys.stderr, flush=True)
        summary = validate_summary(record["summary"], _ids(payload))
        offset += len(chunk)
        step += 1
    return summary


def prepare(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / "fixture.json"
    if not snapshot.exists():
        snapshot.write_bytes(FIXTURE.read_bytes())
    fixture, digest = load_fixture(snapshot)
    config = {"schema_version": 1, "fixture_sha256": digest, "model": MODEL, "envelope_ceiling_bytes": CEILING,
              "noise_events": NOISE_EVENTS, "summary_cap_bytes": SUMMARY_CAP, "shuffle_seed": SEED,
              "answer_instructions": ANSWER_INSTRUCTIONS, "compaction_instructions": COMPACT_INSTRUCTIONS}
    config_path = directory / "configuration.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("Existing evaluation configuration differs")
    _save(config_path, config)
    if (directory / "cells.json").exists():
        return json.loads((directory / "cells.json").read_text())
    originals, transcript = _corpus(fixture)
    dynamic_path = directory / "dynamic-contexts.jsonl"
    if not dynamic_path.exists():
        measured = run_benchmark(fixture_path=snapshot, noise_counts=(NOISE_EVENTS,), split="all", contexts_path=dynamic_path)
        _save(directory / "dynamic-selection.json", measured)
    dynamic = {r["probe_id"]: r["payload"] for r in _records(dynamic_path)}
    if set(dynamic) != {p["id"] for p in fixture["probes"]}:
        raise ValueError("Dynamic context capture is incomplete; retain it as an interrupted run")
    legacy_path = directory / "legacy-contexts.json"
    if not legacy_path.exists():
        _save(legacy_path, _legacy_payloads(fixture, transcript))
        revision = Path.home() / ".kairos/models/fastembed/models--nomic-ai--nomic-embed-text-v1.5/refs/main"
        _save(directory / "embedding-environment.json", {"source_records": len(originals), "model": "nomic-ai/nomic-embed-text-v1.5", "cached_revision": revision.read_text().strip(), "fastembed_version": importlib.metadata.version("fastembed"), "offline": True})
    legacy = json.loads(legacy_path.read_text())
    # The shared summary includes all but the latest six base entries. Probe
    # preludes are supplied verbatim alongside that six-entry frontier; this
    # prevents silently dropping entries when a probe appends recent referents.
    compaction_error = None
    try:
        summary = _compact_prefix(transcript[:-6], directory)
    except (ValueError, RuntimeError, KeyError) as exc:
        summary = []
        compaction_error = f"Append-and-compact unavailable: {type(exc).__name__}: {exc}"
    cells = []
    for probe in fixture["probes"]:
        selected = dict(dynamic[probe["id"]])
        selected.update(model=MODEL, tools=[], instructions=selected["instructions"] + ANSWER_INSTRUCTIONS)
        compact = payload_for(INSTRUCTIONS + ANSWER_INSTRUCTIONS, [
            {"role": "user", "content": canonical({"fallible_compressed_history": summary})},
            *[{"role": r["role"], "content": canonical({"source_id": r["id"], "evidence": r["content"]})} for r in transcript[-6:] + probe["recent"]],
            {"role": "user", "content": probe["question"]},
        ])
        for arm, payload in (("dynamic", selected), ("local_agent_context", legacy[probe["id"]]), ("append_compact_comparator", compact)):
            cell = {"cell_id": probe["id"] + "/" + arm, "probe_id": probe["id"], "arm": arm,
                    "payload": payload, "expected_source_ids": probe["expected_source_ids"]}
            if arm == "append_compact_comparator" and compaction_error:
                cell["preparation_error"] = compaction_error
            cells.append(cell)
    _save(directory / "cells.json", cells)
    return cells


def _capture_stats(records):
    latencies = sorted(r["elapsed_seconds"] for r in records if "elapsed_seconds" in r)
    usages = [r.get("response", {}).get("usage") for r in records]
    usages = [u for u in usages if isinstance(u, dict)]
    return {"captured": len(records), "errors": sum("error" in r for r in records),
            "parse_failures": sum(not r.get("checks", {}).get("parse_ok", False) for r in records if "error" not in r and "raw_answer" in r),
            "answers_with_unavailable_citations": sum(bool(r.get("checks", {}).get("unavailable_citations")) for r in records),
            "expected_sources_cited": sum(r.get("checks", {}).get("expected_sources_cited", False) for r in records),
            "responses_with_usage": len(usages),
            "reported_input_tokens": sum(u.get("input_tokens", 0) for u in usages),
            "reported_output_tokens": sum(u.get("output_tokens", 0) for u in usages),
            "elapsed_seconds_sum": sum(latencies),
            "latency_seconds_p50": latencies[math.ceil(len(latencies) * .5) - 1] if latencies else None,
            "latency_seconds_p95": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
            "human_correctness": None}


def report(directory):
    directory = Path(directory)
    cells = json.loads((directory / "cells.json").read_text())
    answers = {r["cell_id"]: r for r in _records(directory / "answers.jsonl")}
    dispatches = {r["cell_id"] for r in _records(directory / "dispatches.jsonl")}
    fixture, digest = load_fixture(directory / "fixture.json")
    if digest != json.loads((directory / "configuration.json").read_text())["fixture_sha256"]:
        raise ValueError("Frozen fixture fingerprint changed")
    probes = {p["id"]: p for p in fixture["probes"]}
    arms = {}
    review = []
    for arm in sorted({c["arm"] for c in cells}):
        records = [answers[c["cell_id"]] for c in cells if c["arm"] == arm and c["cell_id"] in answers]
        arms[arm] = _capture_stats(records)
    for cell in cells:
        probe = probes[cell["probe_id"]]
        review.append({"review_id": hashlib.sha256(cell["cell_id"].encode()).hexdigest()[:16], "question": probe["question"], "split": probe["split"],
                       "expected_originals": [r for r in probe["sources"] + probe["recent"] if r["id"] in probe["expected_source_ids"]],
                       "supplied_context": cell["payload"], "answer": answers.get(cell["cell_id"], {}).get("raw_answer"),
                       "error": answers.get(cell["cell_id"], {}).get("error"), "human_correctness": None,
                       "human_relational_continuity": None})
    random.Random(SEED).shuffle(review)
    _save(directory / "blinded-review.json", review)
    _save(directory / "review-key.json", {hashlib.sha256(c["cell_id"].encode()).hexdigest()[:16]: c["cell_id"] for c in cells})
    summary = {"scope": "Preliminary supplied-byte-envelope comparison; human correctness ungraded, internal token parity unverified.",
               "arms": arms, "uncertain_dispatches": sorted(dispatches - answers.keys()),
               "by_split": {split: {arm: _capture_stats([r for r in answers.values() if r["arm"] == arm and probes[r["probe_id"]]["split"] == split]) for arm in arms} for split in ("development", "holdout")},
               "undispatched_cells": [c["cell_id"] for c in cells if c["cell_id"] not in dispatches and c["cell_id"] not in answers],
               "answer_dispatches": len(dispatches),
               "compaction_dispatches": len(_records(directory / "compaction-dispatches.jsonl")),
               "compaction_usage_and_timing": _capture_stats(_records(directory / "compactions.jsonl"))}
    _save(directory / "report.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--run", action="store_true", help="Prepare and generate live subscription-backed answers")
    parser.add_argument("--report", action="store_true", help="Rebuild reports from captured answers without model calls")
    args = parser.parse_args()
    if args.run:
        args.directory.mkdir(parents=True, exist_ok=True)
        with _lease(args.directory, "study.lock"):
            cells = prepare(args.directory)
            run_cells(cells, args.directory)
    elif not args.report:
        parser.error("Choose --run or --report; live generation is explicit")
    print(json.dumps(report(args.directory), indent=2))


if __name__ == "__main__":
    main()
