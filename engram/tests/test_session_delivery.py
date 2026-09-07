"""Real Codex processes, synthetic local model, no login or live user sessions."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from context_codex import _Session
from session_bridge import Sessions


@pytest.mark.skipif(shutil.which("codex") is None, reason="requires Codex 0.153.4; covered by the session delivery CI job")
def test_native_queue_reaches_busy_and_idle_sessions_and_correlates_replies(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    requests = []
    busy_started, release_busy = threading.Event(), threading.Event()
    answer_started, release_answer = threading.Event(), threading.Event()

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            index = len(requests)
            if index == 2:
                busy_started.set()
                if not release_busy.wait(20):
                    self.send_error(500, "fixture was not released")
                    return
            if index == 3:
                answer_started.set()
                if not release_answer.wait(20):
                    self.send_error(500, "answer fixture was not released")
                    return
            answers = {1: "UNRELATED_PRIOR_REPLY", 2: "EXISTING_WORK_FINISHED",
                       3: "BUSY_SESSION_REPLY", 4: "IDLE_SESSION_REPLY"}
            item = {"id": f"msg-{index}", "type": "message", "role": "assistant", "status": "completed",
                    "phase": "final_answer", "content": [{"type": "output_text", "text": answers[index], "annotations": []}]}
            events = [
                {"type": "response.created", "response": {"id": f"resp-{index}", "status": "in_progress"}},
                {"type": "response.output_item.added", "output_index": 0, "item": item},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {
                    "id": f"resp-{index}", "status": "completed", "output": [item],
                    "usage": {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}}},
            ]
            payload = "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    (tmp_path / "config.toml").write_text(f'''
model = "gpt-6-astra"
model_provider = "fixture"
approval_policy = "never"
sandbox_mode = "read-only"
[features]
hooks = false
plugins = false
apps = false
memories = false
shell_tool = false
unified_exec = false
[model_providers.fixture]
name = "fixture"
base_url = "http://127.0.0.1:{model.server_port}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
''')
    peers = []
    try:
        for _ in range(2):
            peer = _Session(["codex", "app-server", "--stdio"], tmp_path, 70)
            peers.append(peer)
            peer.rpc("initialize", {"clientInfo": {"name": "superyak-test", "version": "0.1"},
                                    "capabilities": {"experimentalApi": True}})
            peer.send({"method": "initialized", "params": {}})
        owner, control = peers
        target = owner.rpc("thread/start", {"cwd": str(tmp_path)})["thread"]["id"]
        bridge = Sessions(control)

        def completed():
            while True:
                event = owner.next_event()
                if event.get("method") == "turn/completed":
                    assert event["params"]["turn"]["status"] == "completed"
                    return

        owner.rpc("turn/start", {"threadId": target, "input": [{"type": "text", "text": "Earlier unrelated task"}]})
        completed()
        owner.rpc("turn/start", {"threadId": target, "input": [{"type": "text", "text": "Existing busy task"}]})
        assert busy_started.wait(10)
        busy_request = bridge.ask(target, "Synthetic peer question while busy")
        assert busy_request["status"] == "queued"
        assert bridge.result(busy_request["request_id"])["status"] == "queued"
        release_busy.set()
        completed()
        assert answer_started.wait(15)
        # A different app-server reads persisted history while the owner is
        # still generating. This must not be reported as a terminal failure.
        assert bridge.result(busy_request["request_id"])["status"] in {"running", "pending_unknown"}
        release_answer.set()
        completed()
        reply = bridge.result(busy_request["request_id"])
        assert reply["status"] == "completed" and reply["answer"] == "BUSY_SESSION_REPLY"
        assert "UNRELATED" not in json.dumps(reply)

        idle_request = bridge.ask(target, "Synthetic peer question while idle")
        completed()
        assert bridge.result(idle_request["request_id"])["answer"] == "IDLE_SESSION_REPLY"
        assert len(requests) == 4
        assert "Synthetic peer question while busy" in json.dumps(requests[2]["input"])
        assert "Synthetic peer question while idle" in json.dumps(requests[3]["input"])
    finally:
        release_busy.set()
        release_answer.set()
        for peer in peers:
            peer.close()
        model.shutdown()
        model.server_close()
