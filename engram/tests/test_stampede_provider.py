"""The local model boundary preserves endpoint, response, and deadline semantics."""

import importlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def provider_module():
    try:
        return importlib.import_module("deploy.stampede.provider")
    except ModuleNotFoundError:
        pytest.fail("The explicit local model provider has not been implemented")


@pytest.fixture
def service():
    responses = []
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append({"path": self.path, "headers": dict(self.headers),
                             "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            status, value, delay = responses.pop(0)
            try:
                if delay:
                    time.sleep(delay)
                body = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(status)
                if status == 307:
                    self.send_header("Location", "http://example.invalid/v1/chat/completions")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", responses, requests
    server.shutdown()
    server.server_close()
    thread.join()


def completion(**changes):
    result = {"id": "chatcmpl-fixture", "model": "test-model",
              "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"note":"observed"}'}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}}
    result.update(changes)
    return result


def test_generation_keeps_messages_and_accounts_for_actual_usage(provider_module, service, monkeypatch):
    endpoint, responses, requests = service
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leave-process")
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:99")
    responses.append((200, completion(), 0))
    model = provider_module.LocalModel(endpoint, "test-model", seed=9)
    result = model.generate([{"role": "user", "content": "Inspect the supplied evidence."}], max_tokens=80)
    assert result["text"] == '{"note":"observed"}'
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 7
    assert result["model"] == "test-model"
    assert requests[0]["path"] == "/v1/chat/completions"
    assert requests[0]["body"]["messages"] == [{"role": "user", "content": "Inspect the supplied evidence."}]
    assert requests[0]["body"]["max_tokens"] == 80
    assert requests[0]["body"]["seed"] == 9
    assert requests[0]["body"]["response_format"] == {"type": "json_object"}
    assert requests[0]["body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert not any(k.lower() == "authorization" for k in requests[0]["headers"])


def test_missing_usage_remains_unknown(provider_module, service):
    endpoint, responses, _ = service
    answer = completion()
    answer.pop("usage")
    responses.append((200, answer, 0))
    result = provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}])
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None


@pytest.mark.parametrize("answer", [
    completion(model="different-model"),
    completion(choices=[]),
    completion(usage={"prompt_tokens": -1, "completion_tokens": 3}),
    completion(usage={"prompt_tokens": True, "completion_tokens": 3}),
    completion(choices=[{"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}]),
    completion(choices=[{"message": {"role": "assistant", "content": "half an answer"}, "finish_reason": "length"}]),
    b"not json",
])
def test_bad_or_incomplete_responses_cannot_be_counted_as_completed(provider_module, service, answer):
    endpoint, responses, _ = service
    responses.append((200, answer, 0))
    with pytest.raises(RuntimeError):
        provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}])


@pytest.mark.parametrize("status", [307, 400, 500])
def test_http_errors_and_redirects_do_not_retry_elsewhere(provider_module, service, status):
    endpoint, responses, requests = service
    responses.append((status, {"error": "private debug details"}, 0))
    with pytest.raises(RuntimeError) as error:
        provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}])
    assert "private debug details" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize("endpoint", ["https://example.com/v1", "http://10.0.0.1:9000/v1", "http://user:secret@localhost/v1", "http://localhost/v1?token=x", "http://localhost/v1#x", "http://localhost/other", "http://localhost:0/v1"])
def test_only_explicit_credential_free_local_serving_is_accepted(provider_module, endpoint):
    with pytest.raises(ValueError):
        provider_module.LocalModel(endpoint, "test-model")


def test_delayed_response_is_bounded(provider_module, service):
    endpoint, responses, _ = service
    responses.append((200, completion(), .5))
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}], timeout_s=.05)
    assert time.monotonic() - started < .4


def test_large_response_is_rejected_before_parsing(provider_module, service, monkeypatch):
    endpoint, responses, _ = service
    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 128)
    responses.append((200, b"x" * 1024, 0))
    with pytest.raises(RuntimeError):
        provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}])


@pytest.mark.parametrize("kwargs", [{"max_tokens": 0}, {"timeout_s": float("nan")}, {"max_tokens": True}])
def test_invalid_request_limits_do_not_reach_server(provider_module, service, kwargs):
    endpoint, _, requests = service
    with pytest.raises(ValueError):
        provider_module.LocalModel(endpoint, "test-model").generate([{"role": "user", "content": "x"}], **kwargs)
    assert requests == []


@pytest.mark.parametrize("protocol", ["kimi-k3", "glm-5.3"])
def test_lead_turn_preserves_complete_assistant_state_without_disabling_thinking(provider_module, service, protocol):
    endpoint, responses, requests = service
    first = completion()
    first["choices"][0]["message"].update(
        reasoning_content="Synthetic protocol fixture: source version one.",
        tool_calls=[], refusal=None,
    )
    responses.extend([(200, first, 0), (200, first, 0)])
    model = provider_module.LocalModel(endpoint, "test-model", protocol=protocol, reasoning_effort="low")
    history = [{"role": "user", "content": "Read version one."}]
    result = model.generate(history)
    assert result["assistant_message"] == first["choices"][0]["message"]
    history.extend([result["assistant_message"], {"role": "user", "content": "Now use the correction."}])
    model.generate(history)
    assert requests[1]["body"]["messages"][1] == first["choices"][0]["message"]
    for request in requests:
        body = request["body"]
        assert body["reasoning_effort"] == "low"
        assert "response_format" not in body
        assert body.get("chat_template_kwargs", {}).get("enable_thinking") is not False
        if protocol == "glm-5.3":
            assert body["chat_template_kwargs"]["clear_thinking"] is False
    # A shared provider has no accumulated conversation of its own.
    responses.append((200, first, 0))
    model.generate([{"role": "user", "content": "A different researcher."}])
    assert requests[2]["body"]["messages"] == [{"role": "user", "content": "A different researcher."}]


@pytest.mark.parametrize("protocol,reasoning", [("kimi-k3", None), ("kimi-k3", 3), ("glm-5.3", {})])
def test_invalid_lead_state_cannot_be_returned_as_a_completed_turn(provider_module, service, protocol, reasoning):
    endpoint, responses, _ = service
    answer = completion()
    answer["choices"][0]["message"]["reasoning_content"] = reasoning
    responses.append((200, answer, 0))
    with pytest.raises(provider_module.LocalModelError):
        provider_module.LocalModel(endpoint, "test-model", protocol=protocol).generate(
            [{"role": "user", "content": "x"}])


@pytest.mark.parametrize("options", [
    {"protocol": "unknown"},
    {"protocol": "kimi-k3", "reasoning_effort": "medium"},
    {"reasoning_effort": "high"},
])
def test_invalid_protocol_settings_fail_before_sending(provider_module, service, options):
    endpoint, _, requests = service
    with pytest.raises(ValueError):
        provider_module.LocalModel(endpoint, "test-model", **options)
    assert requests == []


def test_text_probe_rejects_tool_execution_requests_even_in_lead_mode(provider_module, service):
    endpoint, responses, _ = service
    answer = completion()
    answer["choices"][0].update(finish_reason="tool_calls")
    answer["choices"][0]["message"].update(
        reasoning_content="Synthetic protocol fixture.",
        tool_calls=[{"id": "call-1", "type": "function", "function": {"name": "read", "arguments": "{}"}}],
    )
    responses.append((200, answer, 0))
    with pytest.raises(provider_module.LocalModelError):
        provider_module.LocalModel(endpoint, "test-model", protocol="kimi-k3").generate(
            [{"role": "user", "content": "x"}])
