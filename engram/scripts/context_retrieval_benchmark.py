#!/usr/bin/env python3
"""Measure fixed-source recall before making claims about conversational quality.

The fixture and answer key are synthetic. This runner measures evidence supplied
by the real runtime selector/compiler, never grades an invented model response.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_compile import Budget  # noqa: E402
from context_runtime import ContextRuntime, INSTRUCTIONS, TOOLS  # noqa: E402
from context_store import ContextStore  # noqa: E402


FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/context_retrieval/probes.json"
THREAD = "synthetic-retrieval-benchmark"
BUDGET = Budget(input_ceiling=16_000, soft_target=8_000, context_window=24_000,
                output_reserve=2048, margin=512, max_candidates=32,
                max_count_attempts=4, require_strict=True)


class ByteCounter:
    model = "synthetic-retrieval-byte-counter"
    capabilities = {"strict": True, "budget_scope": "model_call", "count_kind": "synthetic_utf8_json_bytes", "billing": "synthetic_none"}

    def count(self, payload):
        return len(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())

    def close(self):
        pass


def load_fixture(path=FIXTURE):
    raw = Path(path).read_bytes()
    fixture = json.loads(raw)
    ids = set()
    for probe in fixture["probes"]:
        if probe["id"] in ids or probe["split"] not in {"development", "holdout"}:
            raise ValueError("Duplicate probe or invalid split")
        ids.add(probe["id"])
        originals = {r["id"] for r in probe["sources"] + probe["recent"]}
        if not probe["expected_source_ids"] or not set(probe["expected_source_ids"]) <= originals:
            raise ValueError("Expected evidence has no original")
        if not set(probe["required_source_ids"]) <= originals:
            raise ValueError("Required evidence has no original")
    return fixture, hashlib.sha256(raw).hexdigest()


def _seed(store, fixture):
    # Bulk writes only speed disposable fixture setup; timed retrieval uses the
    # unmodified store/selector APIs. Event IDs are stable across every arm.
    with store._write():
        for probe in fixture["probes"]:
            for source in probe["sources"]:
                store._insert_event(THREAD, source["role"], source["content"], "message", source["id"], None, {})
                store._insert_event("foreign-thread", source["role"], source["content"], "message", "foreign:" + source["id"], None, {})


@contextmanager
def _probe_context(store, probe):
    # Every probe starts from the same archive snapshot at a given scale. No
    # generated answer or another probe's recent referent enters its history.
    try:
        for source in probe["recent"]:
            store.append(THREAD, source["role"], source["content"], event_id=source["id"])
        if probe["pin"]:
            pin = probe["pin"]
            store.set_state(THREAD, pin["key"], pin["content"], pin["source_id"])
        yield
    finally:
        with store._write():
            store.conn.execute("DELETE FROM state WHERE thread=?", (THREAD,))
            for source in probe["recent"]:
                store.conn.execute("DELETE FROM event_search WHERE event_id=? AND thread=?", (source["id"], THREAD))
                store.conn.execute("DELETE FROM events WHERE id=? AND thread=?", (source["id"], THREAD))


def _percentile(values, quantile):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize(rows):
    if not rows:
        return {"probes": 0}
    return {
        "probes": len(rows),
        "all_expected_sources_rate": sum(r["all_expected_sources_selected"] for r in rows) / len(rows),
        "mean_source_recall": sum(r["source_recall"] for r in rows) / len(rows),
        "archive_timeout_rate": sum(r["archive_timeout"] for r in rows) / len(rows),
        "required_constraint_failures": sum(not r["required_constraints_present"] for r in rows),
        "foreign_source_count": sum(r["foreign_source_count"] for r in rows),
        "selection_ms_p50": _percentile([r["selection_ms"] for r in rows], .5),
        "selection_ms_p95": _percentile([r["selection_ms"] for r in rows], .95),
        "max_candidates": max(r["candidate_count"] for r in rows),
        "max_input_bytes": max(r["input_bytes"] for r in rows),
    }


def run_benchmark(*, noise_counts=(0, 1000, 10_000, 25_000), split="development", probe_ids=None, contexts_path=None, fixture_path=FIXTURE):
    if not noise_counts or any(type(n) is not int or not 0 <= n <= 1_000_000 for n in noise_counts):
        raise ValueError("Noise counts must be integers between zero and one million")
    if split not in {"development", "holdout", "all"}:
        raise ValueError("Invalid split")
    fixture, digest = load_fixture(fixture_path)
    probes = [p for p in fixture["probes"] if (split == "all" or p["split"] == split) and (probe_ids is None or p["id"] in probe_ids)]
    if not probes or (probe_ids is not None and set(probe_ids) != {p["id"] for p in probes}):
        raise ValueError("No matching probes or an unknown probe ID")
    rows = []
    output = Path(contexts_path).open("x") if contexts_path else nullcontext(None)
    started = time.monotonic()
    with output as contexts, tempfile.TemporaryDirectory(prefix="engram-retrieval-") as directory:
        store = ContextStore(Path(directory) / "archive.db")
        runtime = ContextRuntime(store, ByteCounter(), BUDGET)
        try:
            _seed(store, fixture)
            previous = 0
            for noise in sorted(set(noise_counts)):
                with store._write():
                    for i in range(previous, noise):
                        store._insert_event(THREAD, "user" if i % 2 == 0 else "assistant", f"Routine check {i:08d}. {fixture['noise']}", "message", f"noise:{i}", None, {})
                previous = noise
                for probe in probes:
                    with _probe_context(store, probe):
                        tick = time.monotonic()
                        candidates, coverage = runtime._candidates(THREAD, probe["question"], "current-unarchived-probe")
                        selected = runtime.compiler.compile(instructions=INSTRUCTIONS, current=probe["question"], candidates=candidates, active_items=(), provider=runtime.provider, tools=TOOLS)
                        elapsed_ms = (time.monotonic() - tick) * 1000
                        ids = {c["source_id"] for c in selected.manifest["selected"]}
                        expected = set(probe["expected_source_ids"])
                        row = {
                            "probe_id": probe["id"], "family": probe["family"], "split": probe["split"], "noise_events": noise,
                            "expected_source_ids": sorted(expected), "selected_source_ids": sorted(ids),
                            "all_expected_sources_selected": expected <= ids,
                            "source_recall": len(ids & expected) / len(expected),
                            "required_constraints_present": set(probe["required_source_ids"]) <= ids,
                            "foreign_source_count": sum(source.startswith("foreign:") for source in ids),
                            "archive_timeout": any(c.get("coverage") == "incomplete" for c in coverage),
                            "selection_ms": elapsed_ms, "candidate_count": len(candidates),
                            "input_bytes": selected.manifest["input_tokens"],
                        }
                        rows.append(row)
                        if contexts:
                            contexts.write(json.dumps({"probe_id": probe["id"], "noise_events": noise, "payload": selected.payload}, ensure_ascii=False) + "\n")
        finally:
            runtime.close()
    return {
        "schema_version": 1, "fixture_sha256": digest, "split": split,
        "scope": "Synthetic source-selection benchmark; no model answers, human review, live tokenizer, richer Engram recall, or production rollout evaluated.",
        "search_deadline_ms": ContextStore.SEARCH_TIMEOUT_SECONDS * 1000,
        "input_count_unit": "canonical JSON UTF-8 bytes", "input_ceiling": BUDGET.input_ceiling,
        "elapsed_seconds": time.monotonic() - started,
        "by_scale": {str(n): summarize([r for r in rows if r["noise_events"] == n]) for n in sorted(set(noise_counts))},
        "by_family": {family: summarize([r for r in rows if r["family"] == family]) for family in sorted({r["family"] for r in rows})},
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--noise-counts", type=int, nargs="+", default=[0, 1000, 10_000, 25_000])
    parser.add_argument("--split", choices=("development", "holdout", "all"), default="development")
    parser.add_argument("--contexts", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(noise_counts=args.noise_counts, split=args.split, contexts_path=args.contexts), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
