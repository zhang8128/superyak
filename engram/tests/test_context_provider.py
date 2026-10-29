"""Exercise the provider's request boundary without sending billable requests."""

import copy
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import socket
import threading
import time

import pytest


def request():
    return {
        "model": "test-model", "instructions": "Keep attribution.",
        "input": [{"role": "user", "content": "Hello 🦊"}],
        "tools": [{"type": "function", "name": "archive_search", "parameters": {"type": "object"}}],
        "store": False, "truncation": "disabled", "max_output_tokens": 64,
        "include": ["reasoning.encrypted_content"],
    }


def response():
    return {
        "id": "resp_1", "status": "completed",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
            {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "archive_search", "arguments": "{}"},
            {"type": "message", "id": "msg_1", "role": "assistant", "content": [{"type": "output_text", "text": "Hello", "annotations": []}]},
        ],
        "usage": {"input_tokens": 31, "output_tokens": 8, "total_tokens": 39},
    }


def test_count_and_generate_share_all_context_fields_and_preserve_output():
    from context_provider import ResponsesProvider

    sent = []
    def transport(path, payload):
        sent.append((path, copy.deepcopy(payload)))
        return {"object": "response.input_tokens", "input_tokens": 31} if path.endswith("input_tokens") else response()

    provider = ResponsesProvider("test-model", transport=transport)
    original = request()
    assert provider.count(original) == 31
    assert provider.generate(original) == response()
    assert original == request()
    assert sent[0][0] == "/v1/responses/input_tokens"
    assert sent[0][1] == {k: v for k, v in request().items() if k not in {"store", "max_output_tokens", "include"}}
    assert sent[1] == ("/v1/responses", request())
    assert provider.capabilities == {"strict": True, "budget_scope": "model_call", "count_kind": "provider", "billing": "api"}
    provider.close()


def test_missing_api_credentials_fail_before_network(monkeypatch):
    from context_provider import ProviderError, ResponsesProvider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        ResponsesProvider("test-model")


@pytest.mark.parametrize("change", [
    {"model": "different"}, {"store": True}, {"truncation": "auto"},
    {"max_output_tokens": 0}, {"max_output_tokens": True},
    {"previous_response_id": "hidden"}, {"conversation": "hidden"}, {"prompt": {"id": "hidden"}},
])
def test_unsafe_or_uncounted_request_fields_fail_before_dispatch(change):
    from context_provider import ProviderError, ResponsesProvider

    def forbidden(*_):
        pytest.fail("Invalid payload reached transport")
    provider = ResponsesProvider("test-model", transport=forbidden)
    payload = request() | change
    with pytest.raises(ProviderError):
        provider.count(payload)
    with pytest.raises(ProviderError):
        provider.generate(payload)


@pytest.mark.parametrize("bad_count", [{}, {"input_tokens": -1}, {"input_tokens": True}, {"input_tokens": "31"}])
def test_malformed_count_never_becomes_an_estimate(bad_count):
    from context_provider import ProviderError, ResponsesProvider

    provider = ResponsesProvider("test-model", transport=lambda *_: bad_count)
    with pytest.raises(ProviderError, match="count"):
        provider.count(request())


def test_count_transport_failure_is_a_provider_error_without_retry():
    from context_provider import ProviderError, ResponsesProvider

    calls = []
    def failing(path, _payload):
        calls.append(path)
        raise TimeoutError("private server diagnostics")
    with pytest.raises(ProviderError) as caught:
        ResponsesProvider("test-model", transport=failing).count(request())
    assert calls == ["/v1/responses/input_tokens"]
    assert "private server diagnostics" not in str(caught.value)


@pytest.mark.parametrize("change", [
    {"id": None}, {"status": "in_progress"}, {"status": []}, {"output": ["malformed"]},
    {"output": [{"type": "function_call", "call_id": "missing_name"}]},
    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text"}]}]},
    {"output": [{"type": "message", "role": "assistant", "content": [{"type": []}]}]},
    {"usage": {"input_tokens": -1, "output_tokens": 2}},
])
def test_malformed_generation_response_is_rejected(change):
    from context_provider import ProviderError, ResponsesProvider

    provider = ResponsesProvider("test-model", transport=lambda *_: response() | change)
    with pytest.raises(ProviderError):
        provider.generate(request())


def test_incomplete_output_and_original_status_remain_inspectable():
    from context_provider import ResponsesProvider

    expected = response() | {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}
    provider = ResponsesProvider("test-model", transport=lambda *_: expected)
    assert provider.generate(request()) == expected


def test_hosted_tools_cannot_bypass_the_external_model_call_gate():
    from context_provider import ProviderError, ResponsesProvider

    def forbidden(*_):
        pytest.fail("Hosted tool reached transport")
    provider = ResponsesProvider("test-model", transport=forbidden)
    with pytest.raises(ProviderError, match="function tools"):
        provider.generate(request() | {"tools": [{"type": "web_search"}]})


def test_https_transport_uses_only_official_origin_and_never_follows_redirects(monkeypatch):
    import context_provider
    from context_provider import ProviderError, ResponsesProvider

    calls = []
    class Connection(http.client.HTTPConnection):
        def __init__(self, host, timeout):
            calls.append((host, timeout))
        def request(self, method, path, body, headers):
            calls.append((method, path, headers["Authorization"]))
        def getresponse(self):
            return type("Redirect", (), {"status": 307, "close": lambda _self: None})()
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(context_provider.http.client, "HTTPSConnection", Connection)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid")
    provider = ResponsesProvider("test-model", api_key="synthetic", timeout=7)
    with pytest.raises(ProviderError, match="307"):
        provider.generate(request())
    assert calls == [("api.openai.com", 7), ("POST", "/v1/responses", "Bearer synthetic"), "closed"]


def test_http_response_is_bounded_before_json_decoding(monkeypatch):
    import context_provider
    from context_provider import ProviderError, ResponsesProvider

    calls = []
    class Connection(http.client.HTTPConnection):
        status = 200
        def __init__(self, *_args, **_kwargs):
            pass
        def request(self, *_args, **_kwargs):
            pass
        def getresponse(self):
            return self
        def read1(self, limit):
            calls.append(limit)
            return b"x" * limit
        def close(self):
            calls.append("closed")
    monkeypatch.setattr(context_provider, "MAX_RESPONSE_BYTES", 32)
    monkeypatch.setattr(context_provider.http.client, "HTTPSConnection", Connection)
    with pytest.raises(ProviderError, match="byte limit"):
        ResponsesProvider("test-model", api_key="synthetic").generate(request())
    assert calls == [33, "closed", "closed"]


def test_timeout_views_keep_independent_limits_for_concurrent_calls(monkeypatch):
    import context_provider
    from context_provider import ResponsesProvider

    limits = []
    barrier = threading.Barrier(2)
    class Connection(http.client.HTTPConnection):
        status = 200
        def __init__(self, _host, timeout):
            limits.append(timeout)
            self.body = json.dumps(response()).encode()
        def request(self, *_args, **_kwargs):
            barrier.wait(timeout=2)
        def getresponse(self):
            return self
        def read1(self, limit):
            data, self.body = self.body[:limit], self.body[limit:]
            return data
        read = read1
        def close(self):
            pass
    monkeypatch.setattr(context_provider.http.client, "HTTPSConnection", Connection)
    original = ResponsesProvider("test-model", api_key="synthetic", timeout=5)
    short, long = original.with_timeout(0.5), original.with_timeout(1)
    with ThreadPoolExecutor(2) as pool:
        jobs = [pool.submit(p.generate, request()) for p in (short, long)]
        assert [job.result()["status"] for job in jobs] == ["completed", "completed"]
    assert sorted(limits) == [0.5, 1]
    assert original.timeout == 5
    assert short.with_timeout(10).timeout == 0.5


def test_timeout_view_preserves_injected_count_transport():
    from context_provider import ResponsesProvider
    original = ResponsesProvider("test-model", transport=lambda *_: {"input_tokens": 12})
    assert original.with_timeout(1).count(request()) == 12


def read_request(sock):
    """The whole HTTP request a fake peer was sent: its headers, then Content-Length bytes of body. http.client sends
    the headers and the body in two writes, so one recv can return the headers alone; a peer that answered then and
    closed made the client's body write fail with BrokenPipeError (a CI flake, run 40861047803)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            return data
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    length = next((int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")[1:]
                   if line.lower().startswith(b"content-length:")), 0)
    while len(rest) < length:
        chunk = sock.recv(65536)
        if not chunk:
            break
        rest += chunk
    return head + b"\r\n\r\n" + rest


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_trickling_http_response_cannot_extend_overall_call_deadline(monkeypatch, phase):
    """Use real HTTP parsing over a socket pair; only TLS/network setup is replaced."""
    import context_provider
    from context_provider import ProviderError, ResponsesProvider

    client, server = socket.socketpair()
    stopped = threading.Event()
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = client
            self.sock.settimeout(self.timeout)
    def peer():
        try:
            server.settimeout(2)
            read_request(server)
            prefix = b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n"
            if phase == "body":
                prefix += b"\r\n"
            else:
                prefix += b"X-Trickle: "
            server.sendall(prefix)
            for _ in range(80):
                if stopped.wait(0.02):
                    break
                server.sendall(b" ")
        except OSError:
            pass
        finally:
            server.close()
    thread = threading.Thread(target=peer)
    thread.start()
    monkeypatch.setattr(context_provider.http.client, "HTTPSConnection", Connection)
    started = time.monotonic()
    try:
        with pytest.raises(ProviderError):
            ResponsesProvider("test-model", api_key="synthetic", timeout=0.15).generate(request())
        assert time.monotonic() - started < 0.6
    finally:
        stopped.set()
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_deadline_reader_preserves_http_body_after_connection_close(monkeypatch):
    import context_provider
    from context_provider import ResponsesProvider

    client, server = socket.socketpair()
    body = json.dumps(response()).encode()
    class Connection(http.client.HTTPConnection):
        def connect(self):
            self.sock = client
    def peer():
        try:
            server.settimeout(2)
            read_request(server)  # all of it, so the close below can't land before the client's body write
            server.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                           + str(len(body)).encode() + b"\r\n\r\n" + body)
        finally:
            server.close()
    thread = threading.Thread(target=peer)
    thread.start()
    monkeypatch.setattr(context_provider.http.client, "HTTPSConnection", Connection)
    try:
        assert ResponsesProvider("test-model", api_key="synthetic", timeout=1).generate(request()) == response()
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
