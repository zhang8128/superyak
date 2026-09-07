"""Local app-server protocol peer: no model, credentials, or network access."""

import json
import os
from pathlib import Path
import sys
import time


scenario, log_path = sys.argv[1:3]
log = Path(log_path)


def record(value):
    with log.open("a") as handle:
        handle.write(json.dumps(value) + "\n")


def emit(value):
    print(json.dumps(value), flush=True)


def event(method, **params):
    emit({"method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", **params}})


record({"pid": os.getpid(), "cwd": os.getcwd(), "api_key_present": "OPENAI_API_KEY" in os.environ})
for raw in sys.stdin:
    message = json.loads(raw)
    record(message)
    method = message.get("method")
    if method == "initialize":
        if scenario == "delayed":
            time.sleep(0.3)
        if scenario == "timeout":
            time.sleep(20)
        if scenario == "stdout_flood":
            sys.stdout.write("x" * 100000)
            sys.stdout.flush()
            time.sleep(20)
        if scenario == "stderr_flood":
            sys.stderr.write("x" * 100000)
            sys.stderr.flush()
            time.sleep(20)
        if scenario == "malformed":
            print("bad-json", flush=True)
            continue
        if scenario == "exit":
            sys.exit(3)
        result = {"userAgent": "fixture"}
    elif method == "initialized":
        continue
    elif method == "account/read":
        result = {"account": {"type": "apiKey"} if scenario == "api_account" else {"type": "chatgpt", "email": None, "planType": "pro"}, "requiresOpenaiAuth": True}
    elif method == "model/list":
        model = "other-model" if scenario == "missing_model" else "gpt-6-astra"
        result = {"data": [{"id": model, "model": model, "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}], "nextCursor": None}
    elif method == "config/read":
        result = {"config": {"mcp_servers": {"fixture_mcp": {"command": "must-never-run"}}}, "origins": {}}
        if scenario == "redacted_config":
            result["config"]["mcp_servers"]["fixture_mcp"]["tool_timeout_sec"] = ""
    elif method == "thread/start":
        if "tool_timeout_sec" in message["params"]["config"]["mcp_servers"]["fixture_mcp"]:
            emit({"id": message["id"], "error": {"code": -32600, "message": "invalid type for redacted MCP timeout"}})
            continue
        result = {
            "thread": {"id": "thread-1", "ephemeral": True},
            "model": "wrong" if scenario == "changed_model" else "gpt-6-astra",
            "modelProvider": "openai", "cwd": os.getcwd(),
            "approvalPolicy": "never", "sandbox": {"type": "readOnly", "networkAccess": False},
        }
        if scenario == "unsafe_sandbox":
            result["sandbox"] = {"type": "dangerFullAccess"}
    elif method == "turn/start":
        acknowledgment = {"id": message["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}}
        if scenario != "early_events":
            emit(acknowledgment)
        if scenario == "approval":
            emit({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {"threadId": "thread-1", "turnId": "turn-1", "itemId": "exec-1", "command": "touch /must-not-exist"}})
            continue
        if scenario == "wrong_turn":
            event("turn/completed", turn={"id": "other-turn", "status": "completed", "items": [{"type": "agentMessage", "id": "wrong", "text": "Wrong answer", "phase": "final_answer"}]})
        event("item/completed", item={"id": "internal-1", "type": "commandExecution", "command": "true", "status": "completed"})
        event("item/completed", item={"id": "comment-1", "type": "agentMessage", "phase": "commentary", "text": "Working…"})
        event("item/agentMessage/delta", itemId="answer-1", delta="Answer")
        final = {"id": "answer-1", "type": "agentMessage", "phase": "final_answer", "text": "Answer 🦊"}
        if scenario != "final_in_turn":
            event("item/completed", item=final)
        usage = {"inputTokens": 90, "outputTokens": 9, "cachedInputTokens": 10, "reasoningOutputTokens": 4, "totalTokens": 99}
        event("thread/tokenUsage/updated", tokenUsage={"last": usage, "total": usage, "modelContextWindow": 100000})
        if scenario == "early_events":
            emit(acknowledgment)
        status = "failed" if scenario == "failed_turn" else "completed"
        event("turn/completed", turn={"id": "turn-1", "status": status, "items": [final], "error": {"message": "private error"} if status == "failed" else None})
        continue
    elif message.get("id") == "approval-1":
        assert message.get("result") == {"decision": "decline"}
        event("turn/completed", turn={"id": "turn-1", "status": "completed", "items": [{"id": "answer-1", "type": "agentMessage", "phase": "final_answer", "text": "Denied"}]})
        continue
    else:
        emit({"id": message.get("id"), "error": {"code": -32601, "message": "unexpected method"}})
        continue
    emit({"id": message["id"], "result": result})
    if method == "thread/start" and scenario == "blocked_input":
        time.sleep(20)
