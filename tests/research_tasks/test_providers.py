"""Portable research uses Atlas validation over explicit local HTTP fixtures."""

import base64
import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT, ROOT / "atlas", ROOT / "engram"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))


def create_model(*args, **kwargs):
    try:
        module = importlib.import_module("research_tasks.providers")
    except ModuleNotFoundError as error:
        pytest.fail(f"Portable research provider adapter is missing: {error}")
    return module.create_model(*args, **kwargs)


@pytest.fixture
def service():
    responses, requests = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append({"path": self.path, "headers": dict(self.headers),
                             "body": json.loads(body), "raw_body": body})
            value = responses.pop(0)
            encoded = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", responses, requests
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def document():
    return {"source": {"id": "s-fixture", "title": "Fictional MG methods observation"},
            "coverage": "abstract_only", "coverage_note": "Fixture abstract only.",
            "publication_types": ["Journal Article"], "passages": [{
                "id": "p0001", "locator": "abstract", "text":
                "The fictional cohort showed altered receptor measurements after treatment."}]}


@pytest.fixture
def analysis():
    return {"relevant": True, "title": "Fictional receptor measurement change",
            "summary": "The fictional cohort had changed receptor measurements.",
            "scope": "This fictional cohort and supplied abstract.",
            "limitations": "Abstract only; no causal conclusion.",
            "passage_id": "p0001", "quote": "showed altered receptor measurements after treatment",
            "rationale": "Receptor measurements inform the fictional methods question."}


def completion(analysis, **message_fields):
    return {"id": "chatcmpl-fixture", "model": "fixture-model", "created": 123,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(analysis), **message_fields},
                "logprobs": None}],
            "usage": {"prompt_tokens": 222, "completion_tokens": 61, "total_tokens": 283,
                      "completion_tokens_details": {"reasoning_tokens": 20}},
            "provider_metadata": {"fixture": True}}


def test_ollama_uses_atlas_selection_and_configured_output_reserve(service, document, analysis):
    from workbench.research_model import Ollama

    endpoint, responses, requests = service
    responses.append({"model": "fixture-model", "done": True, "done_reason": "stop",
                      "message": {"role": "assistant", "content": json.dumps(analysis)}})
    model = create_model("ollama", "fixture-model", endpoint, output_tokens=777, timeout=4)
    result = model.extract("Which receptor measurements changed?", document, [])
    assert isinstance(model, Ollama)
    assert result["analysis"] == analysis
    assert requests[0]["path"] == "/api/chat"
    assert requests[0]["body"]["options"]["num_predict"] == 777
    assert model.context_budget.output_reserve == 777
    assert model.timeout == 4
    assert model.last_request.encode() == requests[0]["raw_body"]
    assert model.last_response["response"]["message"]["content"] == json.dumps(analysis)


@pytest.mark.parametrize("protocol", ["research", "kimi-k3", "glm-5.3"])
def test_completions_retains_full_reply_and_reviews_in_fresh_conversation(
        service, document, analysis, protocol, monkeypatch):
    endpoint, responses, requests = service
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-secret-must-not-leave-process")
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:99")
    first = completion(analysis, reasoning_content="EXTRACTION_ONLY_REASONING",
                       tool_calls=[], refusal=None, provider_state={"opaque": [1, "α"]})
    review = {"verdict": "supported", "reason": "The cited passage describes these measurements.",
              "evidence": [{"passage_id": "p0001"}]}
    second = completion(review, reasoning_content="Independent source review.", provider_state={"opaque": 2})
    responses.extend([first, second])
    options = {"reasoning_effort": "low"} if protocol != "research" else {}
    model = create_model("completions", "fixture-model", endpoint + "/v1",
                                   protocol=protocol, output_tokens=777, seed=9, **options)
    context = [{"record": {"id": "i-prior", "summary": "PRIOR_CONTEXT_MARKER"}}]
    extracted = model.extract("Which receptor measurements changed?", document, context)
    assert extracted["analysis"] == analysis
    assert extracted["response"]["raw_response"] == first
    assert extracted["response"]["assistant_message"] == first["choices"][0]["message"]
    assert extracted["metrics"]["input_tokens"] == 222
    assert extracted["metrics"]["output_tokens"] == 61
    assert model.last_response["response"] == extracted["response"]
    assert model.last_request.encode() == requests[0]["raw_body"]
    assert json.loads(extracted["response"]["raw_body"]) == first
    assessed = model.review("Which receptor measurements changed?", document, extracted["analysis"])
    assert assessed["analysis"] == review
    assert assessed["response"]["raw_response"] == second
    assert model.last_request.encode() == requests[1]["raw_body"]
    assert assessed["context_manifest"]["selected_record_ids"] == []
    assert assessed["context_manifest"]["selected_passage_ids"] == ["p0001"]
    assert "EXTRACTION_ONLY_REASONING" not in requests[1]["raw_body"].decode()
    assert "PRIOR_CONTEXT_MARKER" not in requests[1]["raw_body"].decode()
    for request, result in zip(requests, [extracted, assessed]):
        payload = request["body"]
        assert request["path"] == "/v1/chat/completions"
        assert [message["role"] for message in payload["messages"]] == ["system", "user"]
        assert "untrusted" in payload["messages"][0]["content"].lower()
        assert '"additionalProperties":false' in payload["messages"][0]["content"]
        assert payload["max_tokens"] == 777
        assert payload["seed"] == 9
        assert "response_format" not in payload
        assert not any(key.lower() == "authorization" for key in request["headers"])
        assert result["context_manifest"]["payload_sha256"] == hashlib.sha256(request["raw_body"]).hexdigest()
        assert result["context_manifest"]["request_bytes"] == len(request["raw_body"])
        assert len(request["raw_body"]) <= result["context_manifest"]["input_byte_limit"]
        if protocol == "research":
            assert payload["chat_template_kwargs"]["enable_thinking"] is False
            assert "reasoning_effort" not in payload
        else:
            assert payload["reasoning_effort"] == "low"
            assert payload.get("chat_template_kwargs", {}).get("enable_thinking") is not False
            if protocol == "glm-5.3":
                assert payload["chat_template_kwargs"]["clear_thinking"] is False


@pytest.mark.parametrize("text", ["prefix {\"query\":\"x\"}", '```json\n{"query":"x"}\n```',
                                  '{"query":"x"} trailing', '{"query":"first","query":"second"}',
                                  '{"query":NaN}', '{"query":"\\ud800"}', '[]'])
def test_malformed_json_is_retained_without_repair_or_retry(service, text):
    endpoint, responses, requests = service
    answer = completion({})
    answer["choices"][0]["message"]["content"] = text
    responses.append(answer)
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises(ValueError):
        model.plan("A fixture question", [], [])
    assert len(requests) == 1
    assert model.last_response["response"]["raw_response"] == answer
    assert model.last_response["response"]["assistant_message"]["content"] == text


def test_invalid_quote_preserves_raw_reply_in_atlas_validation_error(service, document, analysis):
    endpoint, responses, requests = service
    answer = completion(analysis | {"quote": "Unmatched invented quote from another paper"})
    responses.append(answer)
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises(ValueError, match="exactly match") as caught:
        model.extract("Which receptor measurements changed?", document, [])
    assert caught.value.result["response"]["raw_response"] == answer
    assert len(requests) == 1


@pytest.mark.parametrize("protocol", ["research", "kimi-k3", "glm-5.3"])
@pytest.mark.parametrize("field,value", [
    ("tool_calls", [{"id": "call-1", "function": {"name": "read", "arguments": "{}"}}]),
    ("function_call", {"name": "read", "arguments": "{}"}),
    ("refusal", "Fixture refusal"),
])
def test_tool_requests_and_refusals_are_retained_and_rejected(
        service, document, analysis, protocol, field, value):
    endpoint, responses, requests = service
    answer = completion(analysis, reasoning_content="Fixture reasoning.", **{field: value})
    responses.append(answer)
    model = create_model("completions", "fixture-model", endpoint, protocol=protocol)
    with pytest.raises((ValueError, RuntimeError)):
        model.extract("Which receptor measurements changed?", document, [])
    assert model.last_response["response"]["raw_response"] == answer
    assert len(requests) == 1


@pytest.mark.parametrize("change", [
    {"model": "wrong-model"}, {"choices": []},
    {"usage": {"prompt_tokens": -1}},
    {"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "partial"}}]},
])
def test_invalid_provider_reply_survives_boundary_validation(service, document, analysis, change):
    endpoint, responses, requests = service
    answer = completion(analysis) | change
    responses.append(answer)
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises((ValueError, RuntimeError)):
        model.extract("Which receptor measurements changed?", document, [])
    assert model.last_response["response"]["raw_response"] == answer
    assert len(requests) == 1


def test_malformed_http_json_body_is_preserved(service):
    endpoint, responses, requests = service
    responses.append(b'{"id":"broken fixture"')
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises(RuntimeError):
        model.plan("A fixture question", [], [])
    assert model.last_response["response"]["raw_response"] == {"raw_body": '{"id":"broken fixture"'}
    assert len(requests) == 1


@pytest.mark.parametrize("body", [b'{"model":"fixture-model","count":NaN}',
                                  b'{"model":"fixture-model","model":"second"}',
                                  b'{"model":"fixture-model","metadata":"\\ud800"}'])
def test_invalid_outer_json_remains_exact_and_safe_to_checkpoint(service, body):
    endpoint, responses, requests = service
    responses.append(body)
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises(RuntimeError):
        model.plan("A fixture question", [], [])
    assert model.last_response["response"]["raw_response"] == {"raw_body": body.decode()}
    json.dumps(model.last_response, ensure_ascii=False, allow_nan=False).encode()
    assert len(requests) == 1


def test_invalid_utf8_http_body_is_preserved_losslessly(service):
    endpoint, responses, requests = service
    body = b'{"value":"\xff"}'
    responses.append(body)
    model = create_model("completions", "fixture-model", endpoint)
    with pytest.raises(RuntimeError):
        model.plan("A fixture question", [], [])
    raw = model.last_response["response"]["raw_response"]
    assert base64.b64decode(raw["raw_body_base64"]) == body
    assert len(requests) == 1


@pytest.mark.parametrize("backend", ["ollama", "completions"])
def test_preflight_failure_clears_previous_request_artifacts(service, backend):
    endpoint, responses, requests = service
    analysis = {"query": "fixture query"}
    if backend == "ollama":
        responses.append({"model": "fixture-model", "done": True, "done_reason": "stop",
                          "message": {"role": "assistant", "content": json.dumps(analysis)}})
    else:
        responses.append(completion(analysis))
    model = create_model(backend, "fixture-model", endpoint)
    assert model.plan("A fixture question", [], []) == "fixture query"
    assert model.last_request.encode() == requests[0]["raw_body"]
    with pytest.raises(ValueError):
        model.plan("", [], [])
    assert model.last_request is None
    assert model.last_response is None
    assert len(requests) == 1


@pytest.mark.parametrize("backend", ["ollama", "completions"])
@pytest.mark.parametrize("endpoint", ["https://127.0.0.1/v1", "http://remote.invalid", "http://user:secret@localhost"])
def test_model_endpoints_are_explicit_credential_free_loopback(backend, endpoint):
    with pytest.raises(ValueError):
        create_model(backend, "fixture-model", endpoint)


@pytest.mark.parametrize("backend,options", [
    ("other", {}), ("completions", {"protocol": "unknown"}),
    ("completions", {"protocol": "research", "reasoning_effort": "high"}),
    ("ollama", {"protocol": "kimi-k3"}), ("ollama", {"reasoning_effort": "high"}),
    ("completions", {"output_tokens": True}), ("completions", {"timeout": 3601}),
])
def test_invalid_options_fail_before_request(service, backend, options):
    endpoint, _, requests = service
    with pytest.raises(ValueError):
        create_model(backend, "fixture-model", endpoint, **options)
    assert requests == []


def test_actual_completion_request_is_bounded_before_http(service):
    from workbench.research_context import ContextBudget

    endpoint, _, requests = service
    model = create_model("completions", "fixture-model", endpoint)
    model.context_budget = ContextBudget(input_bytes=100)
    with pytest.raises(ValueError):
        model.plan("A fixture question", [], [])
    assert requests == []


def test_local_research_protocol_enforces_dispatch_byte_budget(service):
    from deploy.stampede.provider import LocalModel

    endpoint, _, requests = service
    try:
        model = LocalModel(endpoint, "fixture-model", protocol="research")
    except ValueError as error:
        pytest.fail(f"Research protocol is missing: {error}")
    with pytest.raises(ValueError, match="byte budget"):
        model.generate([{"role": "user", "content": "x" * 300}], request_byte_limit=200)
    assert requests == []


def test_shared_provider_keeps_each_concurrent_response_bound_to_its_call(service):
    from deploy.stampede.provider import LocalModel

    endpoint, responses, requests = service
    responses.extend([completion({"query": "first answer"}), completion({"query": "second answer"})])
    barrier = threading.Barrier(2)

    class InterleavedModel(LocalModel):
        def __setattr__(self, name, value):
            super().__setattr__(name, value)
            if name == "last_response_body" and value is not None:
                # Schedule both replies at the diagnostic snapshot boundary.
                barrier.wait(timeout=3)

    model = InterleavedModel(endpoint, "fixture-model")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(model.generate, [{"role": "user", "content": "A fixture query"}])
                   for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert {json.loads(result["text"])["query"] for result in results} == {"first answer", "second answer"}
    for result in results:
        assert json.loads(result["raw_body"]) == result["raw_response"]
    assert len(requests) == 2
