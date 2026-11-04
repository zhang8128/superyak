"""engram/daemon.py answers only requests a web page can't forge: a Host it
names (DNS rebinding sends the attacker's name) and, for POST, a JSON body
(a cross-site form can send text/plain or a form encoding with no preflight).
A request with an Origin must come from a host it names too."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

import daemon


class FakeAgent:
    model = "m"
    session_id = "s" * 12
    conversation: list = []
    claude_status = {"state": "off"}

    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return {"ok": True}

    def get_core_episodes(self):
        self.calls.append("core")
        return [{"content": "a core memory"}]

    def recall(self, query):
        self.calls.append(("recall", query))
        return []

    def get_instincts(self):
        return []

    def remember(self, content, core=False, source=None):
        self.calls.append(("remember", content))
        return "e1"

    def chat(self, message):
        self.calls.append(("chat", message))
        return "hi"


@pytest.fixture
def served(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(daemon.DaemonHandler, "agent", agent, raising=False)
    monkeypatch.setattr(daemon.DaemonHandler, "allowed_hosts", daemon.allowed_hosts("127.0.0.1", None))
    server = HTTPServer(("127.0.0.1", 0), daemon.DaemonHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield agent, server.server_address[1]
    server.shutdown()
    server.server_close()


def _ask(port, method, path, headers, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for name, value in headers.items():
        conn.putheader(name, value)
    if body is not None:
        conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    response = conn.getresponse()
    status, data = response.status, response.read()
    conn.close()
    return status, data


@pytest.mark.parametrize("host", ["evil.example:{port}", "evil.example", "127.0.0.1.evil.example:{port}",
                                  "localhost.:{port}", "0.0.0.0:{port}"])
def test_a_host_it_does_not_name_is_refused_before_any_read(served, host):
    agent, port = served
    status, _ = _ask(port, "GET", "/core", {"Host": host.format(port=port)})
    assert status == 403
    assert agent.calls == []


@pytest.mark.parametrize("host", ["localhost:{port}", "127.0.0.1:{port}", "LOCALHOST:{port}", "localhost"])
def test_loopback_names_are_answered(served, host):
    agent, port = served
    status, data = _ask(port, "GET", "/core", {"Host": host.format(port=port)})
    assert status == 200 and json.loads(data)["count"] == 1


@pytest.mark.parametrize("content_type", [None, "text/plain", "text/plain;charset=UTF-8",
                                          "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                                          "application/jsonx"])
def test_a_post_that_is_not_json_is_refused_before_any_write(served, content_type):
    agent, port = served
    headers = {"Host": f"localhost:{port}"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    status, _ = _ask(port, "POST", "/remember", headers, json.dumps({"content": "planted"}).encode())
    assert status == 415
    assert agent.calls == []


@pytest.mark.parametrize("content_type", ["application/json", "Application/JSON; charset=utf-8"])
def test_a_json_post_is_answered(served, content_type):
    agent, port = served
    status, _ = _ask(port, "POST", "/remember", {"Host": f"localhost:{port}", "Content-Type": content_type},
                     json.dumps({"content": "kept"}).encode())
    assert status == 200 and agent.calls == [("remember", "kept")]


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://localhost.evil.example:{port}",
                                    "https://localhost:{port}",
                                    "file://", "not a url"])
def test_an_origin_it_does_not_name_is_refused(served, origin):
    agent, port = served
    status, _ = _ask(port, "POST", "/chat", {"Host": f"localhost:{port}", "Content-Type": "application/json",
                                             "Origin": origin.format(port=port)},
                     json.dumps({"message": "hello"}).encode())
    assert status == 403
    assert agent.calls == []


def test_the_chat_page_own_origin_is_answered(served):
    agent, port = served
    status, _ = _ask(port, "POST", "/chat", {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json",
                                             "Origin": f"http://127.0.0.1:{port}"},
                     json.dumps({"message": "hello"}).encode())
    assert status == 200 and agent.calls == [("chat", "hello")]


def test_the_names_follow_the_bound_host():
    assert daemon.allowed_hosts("127.0.0.1", None) == {"127.0.0.1", "localhost"}
    assert daemon.allowed_hosts("0.0.0.0", "192.168.1.5") == {"127.0.0.1", "localhost", "192.168.1.5"}
    assert daemon.allowed_hosts("100.64.0.7", None) == {"127.0.0.1", "localhost", "100.64.0.7"}
    assert daemon.allowed_hosts("0.0.0.0", None, ["Pi.Tail.Net"]) == {"127.0.0.1", "localhost", "pi.tail.net"}


def test_main_hands_the_handler_its_names(monkeypatch):
    seen = {}

    class Agent(FakeAgent):
        def __init__(self, **kwargs):
            super().__init__()

        def status(self):
            return {"model": "m", "session_id": "s", "episodes": 0, "core": 0, "semantics": 0, "instincts": 0,
                    "claude_enabled": False}

    class Stop(Exception):
        pass

    class Server:
        def __init__(self, address, handler):
            seen["names"] = handler.allowed_hosts

        def serve_forever(self):
            raise Stop

    monkeypatch.setattr(daemon, "LocalAgent", Agent)
    monkeypatch.setattr(daemon, "HTTPServer", Server)
    monkeypatch.setattr(daemon.sys, "argv", ["daemon.py", "--host", "100.64.0.7", "--allow-host", "pi.tail.net"])
    with pytest.raises(Stop):
        daemon.main()
    assert seen["names"] == {"127.0.0.1", "localhost", "100.64.0.7", "pi.tail.net"}


# Review round 1 (the fresh Pi reviewer, with real Firefox): framing, Fetch Metadata, the Origin's port, and edges.

def _headers_of(port, method, path, headers, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for name, value in headers.items():
        conn.putheader(name, value)
    if body is not None:
        conn.putheader("Content-Length", str(len(body)))
    conn.endheaders(body)
    response = conn.getresponse()
    response.read()
    conn.close()
    return response.status, response.headers


@pytest.mark.parametrize("method,path", [("GET", "/"), ("GET", "/core"), ("GET", "/nowhere"), ("OPTIONS", "/chat")])
def test_no_answer_can_be_framed(served, method, path):
    _, port = served
    _status, headers = _headers_of(port, method, path, {"Host": f"localhost:{port}"})
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Content-Security-Policy"] == "frame-ancestors 'none'"


@pytest.mark.parametrize("site", ["cross-site", "same-site", "CROSS-SITE"])
@pytest.mark.parametrize("method,path,body", [("GET", "/core", None), ("GET", "/recall?q=x", None),
                                               ("POST", "/chat", b'{"message": "hello"}')])
def test_a_cross_site_or_same_site_request_is_refused(served, site, method, path, body):
    agent, port = served
    headers = {"Host": f"localhost:{port}", "Sec-Fetch-Site": site, "Sec-Fetch-Mode": "no-cors",
               "Sec-Fetch-Dest": "image"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    status, _ = _ask(port, method, path, headers, body)
    assert status == 403 and agent.calls == []


@pytest.mark.parametrize("dest,path,expected", [("document", "/", 200), ("document", "/chat", 200),
                                                ("iframe", "/", 403), ("document", "/core", 403)])
def test_only_a_top_level_visit_to_the_chat_page_comes_from_another_site(served, dest, path, expected):
    agent, port = served
    status, _ = _ask(port, "GET", path, {"Host": f"localhost:{port}", "Sec-Fetch-Site": "cross-site",
                                         "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": dest})
    assert status == expected
    assert agent.calls == []


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_the_page_own_requests_and_a_typed_address_are_answered(served, site):
    _, port = served
    status, _ = _ask(port, "GET", "/core", {"Host": f"localhost:{port}", "Sec-Fetch-Site": site})
    assert status == 200


@pytest.mark.parametrize("origin", ["http://localhost:8080", "http://127.0.0.1:1", "http://localhost",
                                    "http://127.0.0.1:{port}"])
def test_an_origin_on_another_port_or_name_than_the_host_is_refused(served, origin):
    agent, port = served
    status, _ = _ask(port, "POST", "/chat", {"Host": f"localhost:{port}", "Content-Type": "application/json",
                                             "Origin": origin.format(port=port)}, b'{"message": "hello"}')
    assert status == 403 and agent.calls == []


def test_a_get_with_a_foreign_origin_is_refused(served):
    agent, port = served
    status, _ = _ask(port, "GET", "/core", {"Host": f"localhost:{port}", "Origin": "http://evil.example"})
    assert status == 403 and agent.calls == []


def test_an_origin_that_cannot_be_parsed_is_refused_with_an_answer(served):
    agent, port = served
    status, data = _ask(port, "GET", "/core", {"Host": f"localhost:{port}", "Origin": "http://[evil"})
    assert status == 403 and b"--allow-host" in data and agent.calls == []


def test_a_request_with_no_host_is_answered(served):
    """Host is a forbidden header: a browser always sends one, so a request without it isn't a page's."""
    agent, port = served
    status, _ = _ask(port, "GET", "/core", {})
    assert status == 200 and agent.calls == ["core"]


def test_an_empty_host_binds_like_every_interface_and_allowed_names_lose_their_port():
    assert daemon.allowed_hosts("", "192.168.1.5") == {"127.0.0.1", "localhost", "192.168.1.5"}
    assert daemon.allowed_hosts("127.0.0.1", None, ["Pi.Tail.Net:7432"]) == {"127.0.0.1", "localhost",
                                                                             "pi.tail.net"}
