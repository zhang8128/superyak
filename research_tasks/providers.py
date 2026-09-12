"""Atlas analysis and source review over explicitly local model transports."""

from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import urlsplit

from deploy.stampede.provider import LocalModel
from workbench.research_context import ContextBudget, compile_request
from workbench.research_model import Ollama, UNTRUSTED


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Model JSON content contains a duplicate object key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Model JSON content contains a nonfinite number")


class Completions(Ollama):
    """Reuse Atlas prompts, selection and validation with a completions endpoint.

    Complete assistant state is retained in artifacts. Each operation compiles
    a fresh system/user conversation; source review never inherits extraction
    reasoning, prior graph records, or an accumulated assistant history.
    """

    def __init__(self, model: str, endpoint: str, *, protocol="research", timeout=120,
                 output_tokens=1800, seed=0, reasoning_effort=None):
        name = model.strip() if isinstance(model, str) else model
        self.local = LocalModel(endpoint, name, seed=seed, protocol=protocol,
                                reasoning_effort=reasoning_effort)
        parsed = urlsplit(endpoint)
        super().__init__(name, f"{parsed.scheme}://{parsed.netloc}", timeout,
                         context_budget=ContextBudget(output_reserve=output_tokens))
        if self.timeout > 3600:
            raise ValueError("Request timeout must be at most 3600 seconds")
        self.last_response = None
        self.last_request = None

    def _chat(self, instruction: str, data: dict, schema: dict) -> dict:
        self.last_response = None
        self.last_request = None
        self.last_context_manifest = None
        instructions = (UNTRUSTED + instruction + "\nRequired JSON schema: "
                        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        compiled = compile_request(
            model=self.model, instructions=instructions, question=data["question"],
            context=data["context"], schema=schema, document=data.get("document"),
            prior_queries=data.get("prior_queries", []),
            previous_rejection=data.get("previous_rejection"), candidate=data.get("candidate"),
            required_passage_ids=data.get("required_passage_ids", ()), budget=self.context_budget)
        manifest = {**compiled.manifest, "backend": "completions", "protocol": self.local.protocol,
                    "compiled_payload_sha256": compiled.manifest["payload_sha256"]}
        self.last_context_manifest = manifest
        started = time.monotonic()
        response = None
        try:
            response = self.local.generate(compiled.payload["messages"],
                max_tokens=self.context_budget.output_reserve, timeout_s=self.timeout,
                request_byte_limit=self.context_budget.input_limit)
        finally:
            # These artifacts are available even when provider validation fails.
            request = self.local.last_request
            self.last_request = request
            if request is not None:
                encoded = request.encode("utf-8")
                manifest.update(request_bytes=len(encoded),
                                payload_sha256=hashlib.sha256(encoded).hexdigest())
            self.last_response = {
                "response": response if response is not None else {
                    "raw_response": self.local.last_response, "raw_body": self.local.last_response_body},
                "request": request, "context_manifest": manifest}
        elapsed = time.monotonic() - started
        analysis = json.loads(response["text"], object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
        json.dumps(analysis, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if not isinstance(analysis, dict) or set(analysis) != set(schema["required"]):
            raise ValueError("Model JSON content does not match the required shape")
        return {"analysis": analysis, "model": response["model"], "response": response,
                "metrics": {"input_tokens": response["input_tokens"],
                            "output_tokens": response["output_tokens"], "wall_time_seconds": elapsed},
                "context_manifest": manifest}


def create_model(backend: str, model: str, endpoint: str, *, protocol="research", timeout=120,
                 output_tokens=1800, seed=0, reasoning_effort=None):
    """Create a local Atlas-compatible model without downloading or checking it."""
    if backend == "ollama":
        if protocol != "research" or reasoning_effort is not None:
            raise ValueError("Ollama research does not accept native lead protocol options")
        return Ollama(model, endpoint, timeout, context_budget=ContextBudget(output_reserve=output_tokens))
    if backend == "completions":
        return Completions(model, endpoint, protocol=protocol, timeout=timeout,
                           output_tokens=output_tokens, seed=seed, reasoning_effort=reasoning_effort)
    raise ValueError("Research backend must be ollama or completions")
