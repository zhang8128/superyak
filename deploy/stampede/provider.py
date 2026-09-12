"""Bounded, credential-free client for an explicitly local inference service."""

from __future__ import annotations

import http.client
import json
import math
import time
from urllib.parse import urlsplit

from context_provider import _DeadlineSocket, _remaining


MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024


class LocalModelError(RuntimeError):
    """A local model call did not produce a validated completed response."""


class LocalModel:
    def __init__(self, base_url: str, model: str, *, seed: int = 0,
                 protocol: str = "synthetic", reasoning_effort: str | None = None):
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid local model endpoint") from exc
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path.rstrip("/") not in {"", "/v1"}
                or parsed.query or parsed.fragment
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError("Model endpoint must be credential-free loopback HTTP at /v1")
        if not isinstance(model, str) or not model.strip() or len(model) > 512:
            raise ValueError("An explicit local model name is required")
        if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
            raise ValueError("Model seed must be a nonnegative 32-bit integer")
        if protocol not in ("synthetic", "kimi-k3", "glm-5.3"):
            raise ValueError("Unknown local model protocol")
        if reasoning_effort is not None and (
                protocol == "synthetic" or reasoning_effort not in ("low", "high", "max")):
            raise ValueError("Lead reasoning effort must be low, high, or max")
        self.base_url = base_url
        self.host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
        self.port = port or 80
        self.model = model
        self.seed = seed
        self.protocol = protocol
        self.reasoning_effort = reasoning_effort or "max"

    def _valid_message(self, message: dict) -> bool:
        if (not isinstance(message, dict)
                or message.get("role") not in ("system", "user", "assistant")
                or not isinstance(message.get("content"), str)):
            return False
        if self.protocol == "synthetic" or message["role"] != "assistant":
            return set(message) == {"role", "content"}
        # Keep the complete returned assistant object for that agent's next turn.
        # This text-only boundary does not execute or resolve tool calls.
        if message.get("tool_calls") or message.get("function_call"):
            return False
        reasoning = message.get("reasoning_content")
        return (isinstance(reasoning, str)
                or (reasoning is None and self.protocol != "kimi-k3"))

    def generate(self, messages: list[dict], *, max_tokens: int = 512,
                 timeout_s: float = 120) -> dict:
        if type(max_tokens) is not int or not 1 <= max_tokens <= 32768:
            raise ValueError("Output token limit must be between 1 and 32768")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 3600:
            raise ValueError("Request timeout must be positive, finite, and at most 3600 seconds")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 64:
            raise ValueError("One to 64 text messages are required")
        for message in messages:
            if not self._valid_message(message):
                raise ValueError("Local research message is invalid for the configured protocol")
        payload = {
            "model": self.model, "messages": messages, "max_tokens": max_tokens,
            "stream": False, "seed": self.seed, "temperature": 0.6,
        }
        if self.protocol == "synthetic":
            payload.update(response_format={"type": "json_object"},
                           chat_template_kwargs={"enable_thinking": False})
        else:
            payload["reasoning_effort"] = self.reasoning_effort
            if self.protocol == "glm-5.3":
                payload["chat_template_kwargs"] = {"clear_thinking": False}
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ValueError("Local model request is not valid UTF-8 JSON") from exc
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("Local model request exceeds its byte budget")
        deadline = time.monotonic() + timeout_s
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout_s)
        # Reuse Engram's absolute-deadline reader, including slow HTTP headers.
        connection.response_class = lambda sock, **kwargs: http.client.HTTPResponse(
            _DeadlineSocket(sock, deadline), **kwargs
        )
        try:
            connection.request("POST", "/v1/chat/completions", body=encoded,
                               headers={"Content-Type": "application/json", "Connection": "close"})
            _remaining(deadline)
            with connection.getresponse() as response:
                if response.status != 200:
                    raise LocalModelError(f"Local model HTTP status {response.status}")
                length = response.getheader("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE_BYTES):
                    raise LocalModelError("Local model response exceeds its byte budget or has invalid framing")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                _remaining(deadline)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise LocalModelError("Local model response exceeds its byte budget")
            result = json.loads(body)
        except LocalModelError:
            raise
        except (OSError, TimeoutError, http.client.HTTPException, ValueError, UnicodeError) as exc:
            raise LocalModelError(f"Local model request failed: {type(exc).__name__}") from exc
        finally:
            connection.close()
        if not isinstance(result, dict) or result.get("model") != self.model:
            raise LocalModelError("Local model response does not match the configured model")
        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise LocalModelError("Local model response needs one completed choice")
        choice = choices[0]
        message = choice.get("message")
        if (choice.get("finish_reason") != "stop" or not isinstance(message, dict)
                or message.get("role") != "assistant" or message.get("tool_calls")
                or not isinstance(message.get("content"), str) or not message["content"].strip()):
            raise LocalModelError("Local model response is incomplete or is not an assistant text answer")
        if self.protocol != "synthetic":
            if not self._valid_message(message):
                raise LocalModelError("Local model assistant state is invalid for the configured protocol")
            try:
                json.dumps(message, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError, TypeError) as exc:
                raise LocalModelError("Local model assistant state is not valid UTF-8 JSON") from exc
        usage = result.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise LocalModelError("Local model usage is malformed")
        counts = {}
        for source, target in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens")):
            value = (usage or {}).get(source)
            if value is not None and (type(value) is not int or value < 0):
                raise LocalModelError("Local model usage is malformed")
            counts[target] = value
        completed = {"text": message["content"], "model": self.model,
                     "request_id": result.get("id"), "seed": self.seed, **counts}
        if self.protocol != "synthetic":
            completed["assistant_message"] = message
        return completed
