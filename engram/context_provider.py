"""Explicitly billed Responses transport for the bounded context runtime.

The compiler owns the count/dispatch gate. This adapter disallows hidden server
conversation state and only accepts fields covered by the counting endpoint.
"""

from __future__ import annotations

import http.client
import io
import json
import math
import os
import time
from collections.abc import Callable


class ProviderError(RuntimeError):
    """A provider could not safely complete the requested operation."""


_CONTEXT_FIELDS = frozenset({
    "model", "instructions", "input", "tools", "truncation", "reasoning",
    "text", "tool_choice", "parallel_tool_calls", "personality",
})
_REQUEST_FIELDS = _CONTEXT_FIELDS | {"store", "max_output_tokens", "include"}
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("Responses API call deadline exceeded")
    return seconds


class _DeadlineReader(io.RawIOBase):
    """Refresh the timeout before each socket read, including HTTP headers."""

    def __init__(self, raw, sock, deadline):
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        # Retain the real socket.makefile reference counting so responses with
        # Connection: close can still read their body after HTTPConnection.close.
        raw = self.sock.makefile(mode, buffering=0)
        return io.BufferedReader(_DeadlineReader(raw, self.sock, self.deadline))


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ProviderError("Provider payload must be finite JSON") from exc


def _request(payload: dict, model: str) -> dict:
    if not isinstance(payload, dict) or set(payload) - _REQUEST_FIELDS:
        raise ProviderError("Unsupported or hidden-state provider request field")
    if payload.get("model") != model:
        raise ProviderError("Request model does not match configured provider model")
    if payload.get("store") is not False or payload.get("truncation") != "disabled":
        raise ProviderError("Requests require store=false and truncation=disabled")
    reserve = payload.get("max_output_tokens")
    if type(reserve) is not int or reserve <= 0:
        raise ProviderError("max_output_tokens must be a positive integer")
    if not isinstance(payload.get("input"), (str, list)):
        raise ProviderError("Request input must be text or a list of provider items")
    if "instructions" in payload and not isinstance(payload["instructions"], str):
        raise ProviderError("Request instructions must be text")
    if not isinstance(payload.get("tools", []), list):
        raise ProviderError("Request tools must be a list")
    if any(not isinstance(tool, dict) or tool.get("type") != "function" for tool in payload.get("tools", [])):
        raise ProviderError("Bounded requests support only client-executed function tools")
    encoded = _json_bytes(payload)
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ProviderError("Provider request exceeds byte limit")
    return json.loads(encoded)


def _validate_response(result: dict) -> dict:
    if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
        raise ProviderError("Malformed provider response id")
    if not isinstance(result.get("status"), str) or result["status"] not in {"completed", "incomplete", "failed", "cancelled"}:
        raise ProviderError("Malformed or nonterminal provider response status")
    if not isinstance(result.get("output"), list):
        raise ProviderError("Malformed provider output")
    for item in result["output"]:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise ProviderError("Malformed provider output item")
        if item["type"] == "function_call":
            if any(not isinstance(item.get(k), str) for k in ("call_id", "name", "arguments")):
                raise ProviderError("Malformed provider function call")
        if item["type"] == "message":
            if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                raise ProviderError("Malformed provider message")
            for part in item["content"]:
                if not isinstance(part, dict) or not isinstance(part.get("type"), str) or part["type"] not in {"output_text", "refusal"}:
                    raise ProviderError("Malformed provider message content")
                field = "text" if part["type"] == "output_text" else "refusal"
                if not isinstance(part.get(field), str):
                    raise ProviderError("Malformed provider message text")
    usage = result.get("usage")
    if usage is not None:
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
            raise ProviderError("Malformed provider usage")
    return result


class ResponsesProvider:
    """Official HTTPS Responses API; no retry or subscription fallback."""

    capabilities = {"strict": True, "budget_scope": "model_call", "count_kind": "provider", "billing": "api"}

    def __init__(self, model: str, api_key: str | None = None, timeout: float = 60,
                 transport: Callable[[str, dict], dict] | None = None):
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("An explicit API model is required")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ProviderError("Provider timeout must be positive and finite")
        self.model = model
        self.timeout = timeout
        self._api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        if transport is None and (not isinstance(self._api_key, str) or not self._api_key.strip()):
            raise ProviderError("Explicit API mode requires OPENAI_API_KEY")
        self._transport = transport

    def with_timeout(self, seconds: float) -> ResponsesProvider:
        """Return an independent call view capped by this provider's timeout."""
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ProviderError("Provider timeout must be positive and finite")
        return ResponsesProvider(self.model, api_key=self._api_key,
                                 timeout=min(seconds, self.timeout), transport=self._transport)

    def _https(self, path: str, payload: dict) -> dict:
        # A fixed origin and no redirect handling prevent endpoint overrides from
        # leaking archives or credentials to an unrelated service.
        deadline = time.monotonic() + self.timeout
        connection = http.client.HTTPSConnection("api.openai.com", timeout=self.timeout)
        connection.response_class = lambda sock, **kwargs: http.client.HTTPResponse(
            _DeadlineSocket(sock, deadline), **kwargs)
        original_send = connection.send

        def send_with_deadline(data):
            if connection.sock is None:
                connection.timeout = _remaining(deadline)
                connection.connect()
            connection.sock.settimeout(_remaining(deadline))
            original_send(data)

        connection.send = send_with_deadline
        response = None
        try:
            connection.request("POST", path, body=_json_bytes(payload), headers={
                "Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json",
            })
            response = connection.getresponse()
            if response.status != 200:
                raise ProviderError(f"Responses API HTTP {response.status}")
            chunks = []
            size = 0
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderError("Provider response exceeds byte limit")
                chunks.append(chunk)
            result = json.loads(b"".join(chunks))
            _remaining(deadline)
            return result
        except TimeoutError as exc:
            raise ProviderError("Responses API call timeout") from exc
        finally:
            if response is not None:
                response.close()
            connection.close()

    def _call(self, path: str, payload: dict) -> dict:
        try:
            result = (self._transport or self._https)(path, payload)
            if not isinstance(result, dict):
                raise ProviderError("Malformed provider response envelope")
            if len(_json_bytes(result)) > MAX_RESPONSE_BYTES:
                raise ProviderError("Provider response exceeds byte limit")
            return result
        except ProviderError:
            raise
        except Exception as exc:
            # Do not put service response bodies, credentials, or archive text
            # into public errors. The caller owns explicit retry decisions.
            raise ProviderError("Responses API transport failed") from exc

    def count(self, payload: dict) -> int:
        request = _request(payload, self.model)
        result = self._call("/v1/responses/input_tokens", {k: v for k, v in request.items() if k in _CONTEXT_FIELDS})
        count = result.get("input_tokens")
        if type(count) is not int or count < 0:
            raise ProviderError("Malformed provider input token count")
        return count

    def generate(self, payload: dict) -> dict:
        return _validate_response(self._call("/v1/responses", _request(payload, self.model)))

    def close(self) -> None:
        """HTTP connections are closed after each operation."""
