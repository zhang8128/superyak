"""Deterministic request selection and full-payload budget admission."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


class ContextCapacityError(RuntimeError):
    """Required content or an unsupported counter prevents safe dispatch."""


@dataclass(frozen=True)
class Budget:
    input_ceiling: int = 24_000
    soft_target: int = 12_000
    context_window: int = 40_000
    output_reserve: int = 8_000
    margin: int = 1000
    max_candidates: int = 64
    max_count_attempts: int = 12
    require_strict: bool = False

    def __post_init__(self):
        for field in ("input_ceiling", "soft_target", "context_window", "output_reserve", "max_candidates", "max_count_attempts"):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if type(self.margin) is not int or self.margin < 0 or self.soft_target > self.input_ceiling:
            raise ValueError("Invalid margin or soft target")
        if self.context_window <= self.output_reserve + self.margin:
            raise ValueError("No room for input after output reserve")


@dataclass(frozen=True)
class Candidate:
    id: str
    role: str
    representations: tuple[str, ...]
    score: float = 0.0
    required: bool = False
    reason: str = "recall"
    dependencies: tuple[str, ...] = ()
    sequence: int | None = None
    version: str | None = None
    source_id: str | None = None

    def __post_init__(self):
        if not self.id or self.role not in {"user", "assistant"} or not self.representations or not all(isinstance(x, str) for x in self.representations):
            raise ValueError("Candidate needs an ID, evidence role and text representations")
        if not math.isfinite(self.score):
            raise ValueError("Candidate score must be finite")


@dataclass(frozen=True)
class CompiledRequest:
    serialized: str
    manifest: dict

    @property
    def payload(self):
        # Callers receive a copy; the counted request cannot be mutated in place.
        return json.loads(self.serialized)


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_active_items(items):
    pending = set()
    seen = set()
    for item in items:
        kind = item.get("type")
        if kind == "function_call":
            call_id = item.get("call_id")
            if not call_id or call_id in seen:
                raise ValueError("Missing or duplicate tool call ID")
            pending.add(call_id)
            seen.add(call_id)
        elif kind == "function_call_output":
            if item.get("call_id") not in pending:
                raise ValueError("Tool output has no preceding call")
            pending.remove(item["call_id"])
    if pending:
        raise ValueError("Cannot dispatch unanswered tool calls")


class ContextCompiler:
    def __init__(self, budget: Budget):
        self.budget = budget

    def compile(self, *, instructions, current, candidates, active_items, provider, tools=()):
        budget = self.budget
        caps = provider.capabilities
        if budget.require_strict and not caps.get("strict"):
            raise ContextCapacityError("Provider supports episode selection only; strict mode requires a verified request counter")
        validate_active_items(active_items)
        if not isinstance(current, str) or not isinstance(instructions, str):
            raise ValueError("Instructions and current message must be text")
        required = [c for c in candidates if c.required]
        if len(required) > budget.max_candidates:
            raise ContextCapacityError("Too many required context entries")
        optional = sorted((c for c in candidates if not c.required), key=lambda c: (-c.score, c.id))
        optional = optional[:budget.max_candidates - len(required)]
        bounded = required + optional
        lookup = {c.id: c for c in bounded}
        if len(lookup) != len(bounded):
            raise ValueError("Duplicate candidate IDs")
        def closure(key, visiting=()):
            if key in visiting:
                raise ValueError("Context dependency cycle")
            if key not in lookup:
                return None
            result = []
            for dependency in lookup[key].dependencies:
                nested = closure(dependency, visiting + (key,))
                if nested is None:
                    return None
                result.extend(nested)
            return list(dict.fromkeys(result + [key]))
        closures = {c.id: closure(c.id) for c in bounded}
        selected = {}
        for candidate in required:
            bundle = closures[candidate.id]
            if bundle is None:
                raise ContextCapacityError("Required context has a missing dependency")
            for key in bundle:
                selected[key] = 0  # Required material always uses its original representation.
        mandatory = dict(selected)

        def payload(selection):
            # Selection priority is not conversation order. External evidence
            # precedes chronological dialogue; active explicit notes follow it.
            def order(key):
                c = lookup[key]
                if key.startswith("state:"):
                    return (2, 0, key)
                return (1, c.sequence, key) if c.sequence is not None else (0, 0, key)
            evidence = [{"role": lookup[key].role, "content": _encode({"source_id": lookup[key].source_id or key, "kind": lookup[key].reason, "sequence": lookup[key].sequence, "version": lookup[key].version or lookup[key].source_id, "representation": selection[key], "evidence": lookup[key].representations[selection[key]]})} for key in sorted(selection, key=order)]
            return {"model": provider.model, "instructions": instructions, "input": evidence + [{"role": "user", "content": current}] + list(active_items), "tools": list(tools), "store": False, "truncation": "disabled", "max_output_tokens": budget.output_reserve}

        # Planning estimates are deliberately separate from the admission count.
        def estimate(selection):
            return max(1, len(_encode(payload(selection)).encode()) // 4)
        for candidate in optional:
            bundle = closures[candidate.id]
            if bundle is None or candidate.id in selected:
                continue
            trial = dict(selected)
            for key in bundle:
                trial.setdefault(key, 0)
            # Progressively reduce only optional evidence. Provenance stays attached.
            while estimate(trial) > budget.soft_target:
                reducible = [k for k in reversed(trial) if k not in mandatory and trial[k] + 1 < len(lookup[k].representations)]
                if not reducible:
                    break
                trial[reducible[0]] += 1
            if estimate(trial) <= budget.soft_target:
                selected = trial

        limit = min(budget.input_ceiling, budget.context_window - budget.output_reserve - budget.margin)
        count_attempts = 0
        while True:
            request = payload(selected)
            serialized = _encode(request)
            count = provider.count(json.loads(serialized))
            count_attempts += 1
            if type(count) is not int or count < 0:
                raise ContextCapacityError("Provider returned an invalid input count")
            if count <= limit:
                break
            if selected == mandatory:
                raise ContextCapacityError("RequiredContextTooLarge: instructions, current message, explicit notes or active provider episode exceed capacity")
            # Remove a candidate plus any selected dependents; never orphan evidence.
            removable = [k for k in reversed(selected) if k not in mandatory]
            removed = {removable[0]}
            for key in list(selected):
                if any(dep in removed for dep in closures[key] or []):
                    removed.add(key)
            selected = {k: v for k, v in selected.items() if k not in removed or k in mandatory}
            if count_attempts >= budget.max_count_attempts - 1:
                selected = dict(mandatory)
            if count_attempts >= budget.max_count_attempts:
                raise ContextCapacityError("Context count attempt limit reached")
        manifest = {"compiler_version": 2, "model": provider.model, "capabilities": dict(caps), "selected_ids": list(selected), "selected": [{"id": key, "source_id": lookup[key].source_id or key, "reason": lookup[key].reason, "sequence": lookup[key].sequence, "version": lookup[key].version or lookup[key].source_id, "representation": index, "required": key in mandatory, "dependencies": list(lookup[key].dependencies)} for key, index in selected.items()], "omitted_count": len(candidates) - len(selected), "input_tokens": count, "input_ceiling": limit, "output_reserve": budget.output_reserve, "context_window": budget.context_window, "margin": budget.margin, "count_attempts": count_attempts, "payload_digest": hashlib.sha256(serialized.encode()).hexdigest(), "active_items": len(active_items)}
        return CompiledRequest(serialized, manifest)
