#!/usr/bin/env python3
"""Measure bounded ContextRuntime behavior with a deterministic fake provider.

This is a mechanical acceptance harness. Its counter treats each UTF-8 byte in
the canonical JSON request as one synthetic admission unit; it is not a live
model tokenizer or a continuity-quality evaluation.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import gc
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context_compile import Budget  # noqa: E402
from context_runtime import ContextRuntime  # noqa: E402
from context_store import ContextStore  # noqa: E402


SYNTHETIC_MODEL = "synthetic-context-runtime-replay"
SYNTHETIC_MARKER = b"SYNTHETIC ARCHIVE FIXTURE - NO PRIVATE DATA\n"
SYNTHETIC_ANSWER = (
    "The synthetic archive fixture confirms that the requested page was read "
    "within its configured bound."
)
PAGE_BYTES = 4096
RUNTIME_CANDIDATE_BOUND = 32
ALLOCATION_METHOD = (
    "tracemalloc.get_traced_memory after gc.collect; Python-traced allocation "
    "bytes only, not process RSS or SQLite native allocations"
)


class ReplayFailure(RuntimeError):
    """A typed replay failure with a stable command-line exit status."""

    exit_status = 4


class ReplayConfigurationError(ReplayFailure):
    exit_status = 2


class ReplayInvariantError(ReplayFailure):
    exit_status = 3


class ExactPayloadMismatch(ReplayInvariantError):
    """The generated request differs from the immediately preceding count."""


def _default_budget() -> Budget:
    return Budget(
        input_ceiling=131_072,
        soft_target=65_536,
        context_window=262_144,
        output_reserve=4096,
        margin=1024,
        max_candidates=RUNTIME_CANDIDATE_BOUND,
        max_count_attempts=4,
        require_strict=True,
    )


@dataclass(frozen=True)
class ReplayConfig:
    model_calls: int = 10_000
    warmup_calls: int = 200
    archive_path: Path | None = None
    artifact_bytes: int = 1_048_576
    max_retained_growth_bytes: int = 33_554_432
    budget: Budget = field(default_factory=_default_budget)

    def __post_init__(self) -> None:
        if type(self.model_calls) is not int or self.model_calls < 4 or self.model_calls % 2:
            raise ReplayConfigurationError("model_calls must be an even integer of at least 4")
        if (
            type(self.warmup_calls) is not int
            or self.warmup_calls < 2
            or self.warmup_calls % 2
            or self.warmup_calls >= self.model_calls
        ):
            raise ReplayConfigurationError(
                "warmup_calls must be an even integer between 2 and model_calls"
            )
        if (
            type(self.artifact_bytes) is not int
            or not PAGE_BYTES * 2 <= self.artifact_bytes <= ContextStore.MAX_ARTIFACT_BYTES
        ):
            raise ReplayConfigurationError(
                f"artifact_bytes must be between {PAGE_BYTES * 2} and "
                f"{ContextStore.MAX_ARTIFACT_BYTES}"
            )
        if type(self.max_retained_growth_bytes) is not int or self.max_retained_growth_bytes < 0:
            raise ReplayConfigurationError("max_retained_growth_bytes must be non-negative")
        if self.archive_path is not None and Path(self.archive_path).exists():
            raise ReplayConfigurationError("archive_path must not already exist")
        if self.budget.max_candidates < 26:
            raise ReplayConfigurationError(
                "budget.max_candidates must cover the runtime's bounded recent/search candidate set"
            )


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SyntheticReplayProvider:
    """Alternates a bounded archive read with a fixed, source-grounded answer."""

    model = SYNTHETIC_MODEL
    capabilities = {
        "strict": True,
        "count_kind": "synthetic_utf8_json_bytes",
        "budget_scope": "model_call",
        "billing": "synthetic_none",
    }

    def __init__(self, artifact_id: str, artifact_bytes: int, budget: Budget):
        self.artifact_id = artifact_id
        self.artifact_bytes = artifact_bytes
        self.budget = budget
        self.count_operations = 0
        self.generation_calls = 0
        self.payload_matches = 0
        self.tool_calls = 0
        self.tool_continuations = 0
        self.call_output_pair_checks = 0
        self.responses_with_usage = 0
        self.usage_input_units = 0
        self.usage_output_units = 0
        self.max_input_count = 0
        self.max_decoded_page_bytes = 0
        self.max_tool_output_payload_bytes = 0
        self._last_counted_serialized: str | None = None
        self._last_count: int | None = None

    def count(self, payload: dict) -> int:
        serialized = _canonical(payload)
        count = len(serialized.encode("utf-8"))
        self.count_operations += 1
        self._last_counted_serialized = serialized
        self._last_count = count
        return count

    def generate(self, payload: dict) -> dict:
        serialized = _canonical(payload)
        if self._last_counted_serialized is None or serialized != self._last_counted_serialized:
            raise ExactPayloadMismatch("dispatched request differs from the exact counted payload")
        if self._last_count is None:
            raise ExactPayloadMismatch("dispatched request has no exact counted payload")
        input_count = self._last_count
        self._last_counted_serialized = None
        self._last_count = None
        if input_count > self.budget.input_ceiling:
            raise ReplayInvariantError("generation exceeded the configured input ceiling")
        if input_count + self.budget.output_reserve + self.budget.margin > self.budget.context_window:
            raise ReplayInvariantError("generation exceeded input plus output reserve and margin")
        if payload.get("max_output_tokens") != self.budget.output_reserve:
            raise ReplayInvariantError("generation did not reserve the configured output allowance")

        self.generation_calls += 1
        self.payload_matches += 1
        self.responses_with_usage += 1
        self.usage_input_units += input_count
        self.max_input_count = max(self.max_input_count, input_count)
        if self.generation_calls % 2:
            self.tool_calls += 1
            output_units = 48
            output = [
                {
                    "type": "reasoning",
                    "id": "synthetic-reasoning",
                    "encrypted_content": "synthetic-opaque-state",
                },
                {
                    "type": "function_call",
                    "name": "archive_read",
                    "call_id": "synthetic-archive-read",
                    "arguments": _canonical(
                        {"id": self.artifact_id, "offset": 0, "limit": PAGE_BYTES}
                    ),
                },
            ]
            response_id = "synthetic-tool-response"
        else:
            self._verify_tool_continuation(payload)
            self.tool_continuations += 1
            output_units = 24
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": SYNTHETIC_ANSWER}],
                }
            ]
            response_id = "synthetic-answer-response"
        self.usage_output_units += output_units
        return {
            "id": response_id,
            "status": "completed",
            "output": output,
            "usage": {
                "input_tokens": input_count,
                "output_tokens": output_units,
                "total_tokens": input_count + output_units,
            },
        }

    def _verify_tool_continuation(self, payload: dict) -> None:
        items = payload.get("input")
        if not isinstance(items, list) or len(items) < 3:
            raise ReplayInvariantError("tool continuation omitted its active item group")
        reasoning, call, result = items[-3:]
        if [item.get("type") for item in (reasoning, call, result)] != [
            "reasoning",
            "function_call",
            "function_call_output",
        ]:
            raise ReplayInvariantError("tool continuation changed active item ordering")
        if call.get("call_id") != result.get("call_id") or call.get("call_id") != "synthetic-archive-read":
            raise ReplayInvariantError("tool continuation did not preserve the call/output pair")
        try:
            arguments = json.loads(call["arguments"])
            tool_output = json.loads(result["output"])
            page = base64.b64decode(tool_output["data"], validate=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReplayInvariantError("archive tool continuation was not valid bounded data") from exc
        if arguments != {"id": self.artifact_id, "offset": 0, "limit": PAGE_BYTES}:
            raise ReplayInvariantError("archive tool request changed before continuation")
        if len(page) != PAGE_BYTES or not page.startswith(SYNTHETIC_MARKER):
            raise ReplayInvariantError("archive tool returned the wrong synthetic page")
        if tool_output.get("next_offset") != PAGE_BYTES:
            raise ReplayInvariantError("large archive read did not remain paginated")
        self.call_output_pair_checks += 1
        self.max_decoded_page_bytes = max(self.max_decoded_page_bytes, len(page))
        self.max_tool_output_payload_bytes = max(
            self.max_tool_output_payload_bytes, len(result["output"].encode("utf-8"))
        )

    def close(self) -> None:
        pass


def _synthetic_artifact(size: int) -> bytes:
    repeats = (size + len(SYNTHETIC_MARKER) - 1) // len(SYNTHETIC_MARKER)
    return (SYNTHETIC_MARKER * repeats)[:size]


def _archive_counts(store: ContextStore, thread: str) -> dict[str, int]:
    with store._lock:
        events = store.conn.execute(
            "SELECT count(*) FROM events WHERE thread=?", (thread,)
        ).fetchone()[0]
        turns = store.conn.execute(
            "SELECT count(*) FROM turns WHERE thread=?", (thread,)
        ).fetchone()[0]
        manifests = store.conn.execute(
            "SELECT count(*) FROM manifests WHERE thread=?", (thread,)
        ).fetchone()[0]
        artifact_row = store.conn.execute(
            "SELECT count(*),coalesce(sum(size),0) FROM artifacts WHERE thread=?", (thread,)
        ).fetchone()
    return {
        "events": events,
        "turns": turns,
        "manifests": manifests,
        "artifacts": artifact_row[0],
        "artifact_payload_bytes": artifact_row[1],
    }


def _candidate_measurements(store: ContextStore, thread: str, bound: int) -> dict:
    manifests = 0
    max_observed = 0
    max_selected = 0
    incomplete_archive_retrievals = 0
    archive_search_deadline_ms = store.SEARCH_TIMEOUT_SECONDS * 1000
    with store._lock:
        cursor = store.conn.execute(
            "SELECT data FROM manifests WHERE thread=?", (thread,)
        )
        for row in cursor:
            manifest = json.loads(row[0])
            selected = len(manifest["selected_ids"])
            observed = selected + manifest["omitted_count"]
            manifests += 1
            max_selected = max(max_selected, selected)
            max_observed = max(max_observed, observed)
            if selected > bound or observed > bound:
                raise ReplayInvariantError(
                    f"manifest candidate count {observed} exceeded bound {bound}"
                )
            incomplete = [
                item
                for item in manifest.get("source_coverage", ())
                if item.get("mode") == "archive_fts"
                and item.get("coverage") == "incomplete"
            ]
            if incomplete:
                incomplete_archive_retrievals += 1
                if any(
                    item.get("deadline_ms") != archive_search_deadline_ms
                    for item in incomplete
                ):
                    raise ReplayInvariantError(
                        "manifest reported an unexpected archive search deadline"
                    )
    return {
        "bound": bound,
        "manifests_checked": manifests,
        "max_observed": max_observed,
        "max_selected": max_selected,
        "all_manifests_within_bound": True,
        "archive_search_deadline_ms": archive_search_deadline_ms,
        "archive_retrieval_incomplete_manifests": incomplete_archive_retrievals,
    }


def _measure_at(path: Path, config: ReplayConfig, progress: Callable[[int, int], None] | None) -> dict:
    thread = "synthetic-runtime-replay"
    own_tracer = not tracemalloc.is_tracing()
    if own_tracer:
        tracemalloc.start()
    started = time.monotonic()
    runtime: ContextRuntime | None = None
    try:
        store = ContextStore(path)
        artifact_id = store.put_artifact(thread, _synthetic_artifact(config.artifact_bytes))
        provider = SyntheticReplayProvider(artifact_id, config.artifact_bytes, config.budget)
        runtime = ContextRuntime(store, provider, config.budget, max_calls=2, max_seconds=60)
        archive_start = _archive_counts(store, thread)
        warmup_turns = config.warmup_calls // 2
        total_turns = config.model_calls // 2

        for turn in range(total_turns):
            result = runtime.chat(
                thread,
                f"Synthetic replay turn {turn:08d} λ: read the bounded fixture page.",
                event_id=f"synthetic-replay-{turn:08d}",
            )
            if result.get("response") != SYNTHETIC_ANSWER:
                raise ReplayInvariantError("runtime returned a non-synthetic or ungrounded answer")
            completed_calls = provider.generation_calls
            if turn + 1 == warmup_turns:
                gc.collect()
                warmup_current, warmup_peak = tracemalloc.get_traced_memory()
                archive_warmup = _archive_counts(store, thread)
                tracemalloc.reset_peak()
            if progress is not None:
                progress(completed_calls, config.model_calls)

        gc.collect()
        end_current, end_phase_peak = tracemalloc.get_traced_memory()
        archive_end = _archive_counts(store, thread)
        retained_growth = end_current - warmup_current
        if retained_growth > config.max_retained_growth_bytes:
            raise ReplayInvariantError(
                f"Python-traced retained allocation growth {retained_growth} exceeded "
                f"bound {config.max_retained_growth_bytes}"
            )
        if provider.generation_calls != config.model_calls:
            raise ReplayInvariantError("runtime did not execute the requested generation calls")
        if provider.count_operations != provider.generation_calls:
            raise ReplayInvariantError("generations did not each have exactly one bounded count")
        if provider.payload_matches != provider.generation_calls:
            raise ReplayInvariantError("not every dispatched payload matched its exact count")
        if provider.tool_continuations != total_turns:
            raise ReplayInvariantError("not every synthetic tool call received a continuation")
        candidates = _candidate_measurements(store, thread, config.budget.max_candidates)
        if candidates["manifests_checked"] != provider.generation_calls:
            raise ReplayInvariantError("archive did not retain one manifest per generation call")

        elapsed = time.monotonic() - started
        return {
            "schema_version": 1,
            "result": {"ok": True, "kind": "synthetic_mechanical_acceptance"},
            "scope": {
                "provider": "deterministic synthetic provider; no network or model calls",
                "counter_certification": "synthetic only; not a live tokenizer certification",
                "continuity_accuracy": "not evaluated",
                "private_data": "none",
            },
            "configuration": {
                "model_calls": config.model_calls,
                "warmup_calls": config.warmup_calls,
                "artifact_bytes": config.artifact_bytes,
                "max_retained_growth_bytes": config.max_retained_growth_bytes,
                "archive_disposition": "retained" if config.archive_path is not None else "temporary_deleted",
            },
            "calls": {
                "requested_generation_calls": config.model_calls,
                "actual_generation_calls": provider.generation_calls,
                "count_operations": provider.count_operations,
                "counted_payload_dispatch_matches": provider.payload_matches,
                "tool_calls": provider.tool_calls,
                "tool_continuations": provider.tool_continuations,
                "completed_turns": total_turns,
            },
            "budget": {
                "count_method": (
                    "canonical JSON UTF-8 byte length; one byte is one synthetic admission unit"
                ),
                "count_unit": "synthetic_utf8_json_bytes",
                "input_ceiling": config.budget.input_ceiling,
                "output_reserve": config.budget.output_reserve,
                "margin": config.budget.margin,
                "context_window": config.budget.context_window,
                "max_input_count": provider.max_input_count,
                "all_generation_calls_compliant": True,
            },
            "candidates": candidates,
            "tools": {
                "tool": "archive_read",
                "read_only": True,
                "requested_page_bytes": PAGE_BYTES,
                "max_decoded_page_bytes": provider.max_decoded_page_bytes,
                "max_serialized_tool_output_bytes": provider.max_tool_output_payload_bytes,
                "large_artifact_bytes": config.artifact_bytes,
                "call_output_pair_checks": provider.call_output_pair_checks,
            },
            "usage": {
                "responses_with_usage": provider.responses_with_usage,
                "reported_input_units": provider.usage_input_units,
                "reported_output_units": provider.usage_output_units,
                "reported_total_units": provider.usage_input_units + provider.usage_output_units,
            },
            "archive": {
                "events_at_start": archive_start["events"],
                "events_after_warmup": archive_warmup["events"],
                "events_at_end": archive_end["events"],
                "event_growth_after_warmup": archive_end["events"] - archive_warmup["events"],
                "turns_at_end": archive_end["turns"],
                "manifests_at_end": archive_end["manifests"],
                "artifacts_at_end": archive_end["artifacts"],
                "artifact_payload_bytes_at_end": archive_end["artifact_payload_bytes"],
                "path": str(path) if config.archive_path is not None else None,
            },
            "allocations": {
                "method": ALLOCATION_METHOD,
                "tracer_started_by_replay": own_tracer,
                "current_bytes_after_warmup": warmup_current,
                "peak_bytes_during_warmup": warmup_peak,
                "current_bytes_at_end": end_current,
                "peak_bytes_after_warmup": end_phase_peak,
                "peak_python_traced_bytes": max(warmup_peak, end_phase_peak),
                "retained_growth_bytes": retained_growth,
                "retained_growth_bound_bytes": config.max_retained_growth_bytes,
                "retained_growth_within_bound": True,
            },
            "timing": {
                "elapsed_seconds": elapsed,
                "generation_calls_per_second": provider.generation_calls / elapsed,
            },
        }
    finally:
        if runtime is not None:
            runtime.close()
        if own_tracer:
            tracemalloc.stop()


def run_replay(
    config: ReplayConfig = ReplayConfig(),
    *,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Run the replay against an explicit or automatically deleted archive."""
    if config.archive_path is not None:
        return _measure_at(Path(config.archive_path), config, progress)
    with tempfile.TemporaryDirectory(prefix="engram-context-runtime-replay-") as directory:
        return _measure_at(Path(directory) / "archive.db", config, progress)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-calls", type=int, default=10_000)
    parser.add_argument("--warmup-calls", type=int, default=200)
    parser.add_argument("--archive", type=Path, help="retain the new replay archive at this path")
    parser.add_argument("--artifact-bytes", type=int, default=1_048_576)
    parser.add_argument("--max-retained-growth-bytes", type=int, default=33_554_432)
    parser.add_argument("--progress-every", type=int, default=1000)
    parser.add_argument("--indent", type=int, default=2)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.progress_every < 0:
            raise ReplayConfigurationError("progress_every must be non-negative")
        config = ReplayConfig(
            model_calls=args.model_calls,
            warmup_calls=args.warmup_calls,
            archive_path=args.archive,
            artifact_bytes=args.artifact_bytes,
            max_retained_growth_bytes=args.max_retained_growth_bytes,
        )
        last_reported = 0

        def progress(completed: int, total: int) -> None:
            nonlocal last_reported
            if args.progress_every and (
                completed == total or completed - last_reported >= args.progress_every
            ):
                print(f"synthetic generation calls: {completed}/{total}", file=sys.stderr)
                last_reported = completed

        report = run_replay(config, progress=progress)
    except ReplayFailure as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "result": {"ok": False},
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "exit_status": exc.exit_status,
                    },
                },
                indent=args.indent,
                sort_keys=True,
            )
        )
        return exc.exit_status
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "result": {"ok": False},
                    "error": {
                        "type": "ReplayExecutionError",
                        "cause": type(exc).__name__,
                        "message": str(exc),
                        "exit_status": ReplayFailure.exit_status,
                    },
                },
                indent=args.indent,
                sort_keys=True,
            )
        )
        return ReplayFailure.exit_status
    print(json.dumps(report, indent=args.indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
