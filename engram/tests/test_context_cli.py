import http.client
import json
import threading

import pytest

from context_cli import build_parser, resolve_paths, make_server
from context_compile import Budget
from context_runtime import ContextRuntime
from context_store import ContextStore


class Provider:
    model = "fixture"
    capabilities = {"strict": False, "budget_scope": "episode", "billing": "subscription", "count_kind": "estimate"}
    def count(self, payload):
        return len(json.dumps(payload)) // 4
    def generate(self, payload):
        return {"id": "r", "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Hello"}]}], "usage": None}
    def close(self):
        pass


def test_default_subscription_and_named_instance_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    args = build_parser().parse_args(["--instance", "mira", "chat", "hello"])
    assert args.provider == "codex"
    data, memory = resolve_paths(args)
    assert data == tmp_path / ".engram" / "instances" / "mira" / "context-runtime"
    assert memory == tmp_path / ".engram" / "instances" / "mira" / "graph.db"
    with pytest.raises(ValueError):
        resolve_paths(build_parser().parse_args(["--instance", "../escape", "chat", "hello"]))


def test_lighthouse_is_explicit_and_uses_existing_named_receiver(tmp_path, monkeypatch):
    from context_cli import make_runtime, validate_lighthouse_args
    import context_codex
    monkeypatch.setenv('ENGRAM_HOME', str(tmp_path))
    monkeypatch.setattr(context_codex, 'CodexProvider', lambda **kw: Provider())
    common = ['--instance', 'mira', '--lighthouse-context', 'memory/technical',
              '--lighthouse-purpose', 'session-recall']
    args = build_parser().parse_args(common + ['chat', 'hello'])
    directory, memory = resolve_paths(args)
    memory.parent.mkdir(parents=True)
    memory.touch()
    runtime = make_runtime(args, ContextStore(directory / 'context.db'), memory)
    assert [s.mode for s in runtime.sources] == ['sqlite_lexical', 'lighthouse']
    runtime.close()
    for argv in [common + ['code', '--repo', str(tmp_path), 'task'],
                 ['--lighthouse-context', 'memory/technical', 'chat'],
                 common + ['--engram-db', str(tmp_path / 'unrelated.db'), 'chat']]:
        args = build_parser().parse_args(argv)
        _, selected_memory = resolve_paths(args)
        with pytest.raises(ValueError, match='Lighthouse'):
            validate_lighthouse_args(args, selected_memory)


def test_http_chat_context_and_thread_isolation(tmp_path):
    runtime = ContextRuntime(ContextStore(tmp_path / "runtime.db"), Provider(), Budget())
    server = make_server(runtime, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    try:
        conn.request("GET", "/")
        page = conn.getresponse()
        assert page.status == 200
        assert b"Context in use" in page.read()
        conn.request("POST", "/chat", json.dumps({"thread_id": "a", "event_id": "one", "message": "Hi"}), {"Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 200
        result = json.loads(response.read())
        assert result["response"] == "Hello"
        conn.request("GET", "/context?thread_id=a")
        context = conn.getresponse()
        assert json.loads(context.read())["capabilities"]["budget_scope"] == "episode"
        conn.request("GET", "/context?thread_id=b")
        other = conn.getresponse()
        assert json.loads(other.read()) is None
        conn.request("POST", "/chat", "{}", {"Content-Type": "application/json", "Origin": "https://untrusted.example"})
        rejected = conn.getresponse()
        assert rejected.status == 403
        rejected.read()
        conn.request("POST", "/chat", "{}", {"Content-Type": "text/plain"})
        rejected = conn.getresponse()
        assert rejected.status == 415
        rejected.read()
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        worker.join()
        runtime.close()


def test_http_rejects_bad_json_and_oversized_length(tmp_path):
    runtime = ContextRuntime(ContextStore(tmp_path / "runtime.db"), Provider(), Budget())
    server = make_server(runtime, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for body in ("[]", "{", '{"thread_id": "x", "message": 3}', '{"message":' + '['*10000 + '0' + ']'*10000 + '}'):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
            conn.request("POST", "/chat", body, {"Content-Type": "application/json"})
            response = conn.getresponse()
            assert response.status == 400
            response.read()
            conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
        conn.request("POST", "/chat", b"", {"Content-Type": "application/json", "Content-Length": "99999999"})
        response = conn.getresponse()
        assert response.status == 413
        response.read()
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
        runtime.close()
