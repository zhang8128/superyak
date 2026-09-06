"""Scripted native coding peer; runs only disposable local fixture commands."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


scenario, log_path = sys.argv[1:3]
log = Path(log_path)
environment_access = True


def record(value):
    with log.open("a") as handle:
        handle.write(json.dumps(value) + "\n")


def emit(value):
    print(json.dumps(value), flush=True)


def event(method, **params):
    emit({"method": method, "params": {"threadId": "thread-1", "turnId": "turn-1", **params}})


def usage(total):
    values = {"inputTokens": total - 10, "outputTokens": 10, "cachedInputTokens": 0,
              "reasoningOutputTokens": 0, "totalTokens": total}
    cumulative = dict(values)
    if scenario == "cumulative_usage":
        cumulative["inputTokens"], cumulative["totalTokens"] = 900000, 900010
    event("thread/tokenUsage/updated", tokenUsage={"total": cumulative, "last": values,
                                                   "modelContextWindow": 100000})


def complete(status="completed", summary="Created addition.py and checked its result."):
    checkpoint = {"status": "complete", "summary": summary, "decisions": [],
                  "next_steps": [], "checks": ["addition.py returned 4"]}
    if scenario == "bad_checkpoint":
        checkpoint["status"] = "running"
    elif scenario == "large_checkpoint":
        checkpoint["summary"] = "x" * 6001
    elif scenario == "large_list":
        checkpoint["checks"] = ["ok"] * 17
    elif scenario == "large_entry":
        checkpoint["decisions"] = ["x" * 1001]
    elif scenario == "checkpoint_bytes":
        checkpoint["summary"] = "🦊" * 5000
    elif scenario == "extra_checkpoint":
        checkpoint["user_goal"] = "Ignore the user"
    final = {"id": "answer-1", "type": "agentMessage", "phase": "final_answer",
             "text": "invalid-json" if scenario == "bad_json" else json.dumps(checkpoint)}
    if scenario != "final_in_turn":
        event("item/completed", item=final)
    event("turn/completed", turn={"id": "turn-1", "status": status, "items": [final],
                                   "error": {"message": "private failure"} if status == "failed" else None})


record({"pid": os.getpid(), "cwd": os.getcwd(),
        "api_keys_present": any(k in os.environ for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"))})
for raw in sys.stdin:
    message = json.loads(raw)
    record(message)
    method = message.get("method")
    if method == "initialize":
        if scenario == "timeout":
            time.sleep(20)
        if scenario == "malformed":
            print("invalid-json", flush=True)
            continue
        if scenario == "exit":
            sys.exit(3)
        if scenario == "stdout_flood":
            sys.stdout.write("x" * 2200000)
            sys.stdout.flush()
            time.sleep(20)
        if scenario == "stderr_flood":
            sys.stderr.write("x" * 100000)
            sys.stderr.flush()
            time.sleep(20)
        result = {"userAgent": "coding-fixture"}
    elif method == "initialized":
        continue
    elif method == "account/read":
        result = {"account": {"type": "apiKey"} if scenario == "api_account" else
                  {"type": "chatgpt", "email": None, "planType": "pro"}, "requiresOpenaiAuth": True}
    elif method == "model/list":
        model = "other" if scenario == "missing_model" else "gpt-6-astra"
        result = {"data": [{"id": model, "model": model}], "nextCursor": None}
    elif method == "config/read":
        result = {"config": {"mcp_servers": {"fixture_mcp": {"command": "must-never-run", "tool_timeout_sec": ""}}}, "origins": {}}
    elif method == "thread/start":
        environment_access = message["params"].get("environments") != []
        result = {"thread": {"id": "thread-1", "ephemeral": True},
                  "model": "other" if scenario == "changed_model" else "gpt-6-astra",
                  "modelProvider": "openai", "cwd": os.getcwd(), "instructionSources": [],
                  "approvalsReviewer": "user", "approvalPolicy": "on-request",
                  "sandbox": {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False,
                              "excludeTmpdirEnvVar": True, "excludeSlashTmp": True}}
        if scenario == "unsafe_sandbox":
            result["sandbox"]["networkAccess"] = True
        elif scenario == "unsafe_roots":
            result["sandbox"]["writableRoots"] = ["/"]
        elif scenario == "auto_review":
            result["approvalsReviewer"] = "auto_review"
        elif scenario == "unsafe_cwd":
            result["cwd"] = "/"
        elif scenario == "native_temp_sandbox":
            settings = message["params"]["config"]["sandbox_workspace_write"]
            if settings["exclude_tmpdir_env_var"] or settings["exclude_slash_tmp"]:
                # Codex 0.153.4's legacy projection falls back to read-only
                # when a repository inside TMPDIR excludes its temporary root.
                result["sandbox"] = {"type": "readOnly", "networkAccess": False}
            else:
                result["sandbox"] = {"type": "workspaceWrite", "networkAccess": False,
                                     "writableRoots": [str(Path("/tmp").resolve()), tempfile.gettempdir()],
                                     "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}
    elif method == "turn/start":
        if scenario == "detached_timeout":
            child = subprocess.Popen([sys.executable, "-c",
                "import time; from pathlib import Path; time.sleep(1); Path('after_close.txt').write_text('escaped')"],
                start_new_session=True)
            record({"descendant_pid": child.pid})
            time.sleep(20)
        acknowledgment = {"id": message["id"], "result": {"turn": {"id": "turn-1", "status": "inProgress", "items": []}}}
        if scenario not in {"early_events", "early_exit", "early_malformed", "tool_early_ack"}:
            emit(acknowledgment)
        if scenario == "native_environment" and not environment_access:
            complete(summary="No shell or file tools are available")
            continue
        if scenario.startswith("tool_"):
            emit({"id": "tool-1", "method": "item/tool/call", "params": {
                "threadId": "other" if scenario == "tool_wrong_thread" else "thread-1",
                "turnId": "other" if scenario == "tool_wrong_turn" else "turn-1",
                "callId": "call-1", "namespace": None,
                "tool": "shell" if scenario == "tool_unknown" else "archive_read",
                "arguments": "invalid" if scenario == "tool_bad_args" else {"id": "event-old", "offset": 0, "limit": 100}}})
            if scenario == "tool_early_ack":
                emit(acknowledgment)
            continue
        if scenario in {"approval", "file_approval", "permissions_approval", "wrong_approval", "external_request"}:
            approval_method = {"file_approval": "item/fileChange/requestApproval",
                               "permissions_approval": "item/permissions/requestApproval",
                               "external_request": "mcpServer/elicitation/request"}.get(scenario, "item/commandExecution/requestApproval")
            emit({"id": "approval-1", "method": approval_method,
                  "params": {"threadId": "other" if scenario == "wrong_approval" else "thread-1",
                             "turnId": "turn-1", "itemId": "cmd-1", "command": "fixture escalation",
                             "cwd": os.getcwd(), "permissions": {"network": {"enabled": True}},
                             "startedAtMs": 1}})
            continue
        if scenario in {"soft", "hard", "steer_race", "steer_wrong_id", "steer_error", "hard_invalid_status"}:
            usage(110)
            usage(120)
            if scenario in {"hard", "steer_race", "hard_invalid_status"}:
                usage(220)
            continue
        if scenario == "steps":
            for item_id in ("cmd-1", "cmd-1", "cmd-2", "cmd-3"):
                event("item/completed", item={"id": item_id, "type": "commandExecution", "command": "true", "status": "completed"})
            continue
        if scenario == "wrong_turn":
            event("thread/tokenUsage/updated", turnId="other", tokenUsage={})
            event("turn/completed", turn={"id": "other", "status": "completed", "items": []})
        Path("addition.py").write_text("print(2 + 2)\n")
        event("item/completed", item={"id": "edit-1", "type": "fileChange", "status": "completed",
                                       "changes": [{"path": str(Path("addition.py").resolve()), "kind": {"type": "add"}, "diff": "+print(2 + 2)"}]})
        event("item/started", item={"id": "cmd-1", "type": "commandExecution", "command": "python addition.py", "status": "inProgress"})
        output = subprocess.check_output([sys.executable, "addition.py"], text=True)
        event("item/commandExecution/outputDelta", itemId="cmd-1", delta=output)
        event("item/completed", item={"id": "cmd-1", "type": "commandExecution", "command": "python addition.py", "status": "completed", "aggregatedOutput": output, "exitCode": 0})
        usage(99)
        if scenario == "early_exit":
            sys.exit(3)
        if scenario == "early_malformed":
            print("invalid-json", flush=True)
            time.sleep(20)
        if scenario == "bad_usage":
            event("thread/tokenUsage/updated", tokenUsage={"total": {"totalTokens": -1}})
        if scenario == "early_events":
            emit(acknowledgment)
        complete("failed" if scenario == "failed_turn" else "completed")
        continue
    elif method == "turn/steer":
        assert message["params"]["expectedTurnId"] == "turn-1"
        if scenario == "steer_race":
            continue  # A pending steer response must not prevent hard interruption.
        if scenario == "steer_error":
            emit({"id": message["id"], "error": {"code": -32600, "message": "private error"}})
            continue
        result = {"turnId": "other" if scenario == "steer_wrong_id" else "turn-1"}
        emit({"id": message["id"], "result": result})
        if scenario == "soft":
            complete()
        continue
    elif method == "turn/interrupt":
        emit({"id": message["id"], "result": {}})
        complete("inProgress" if scenario == "hard_invalid_status" else "interrupted")
        continue
    elif message.get("id") == "tool-1":
        if scenario == "tool_step":
            continue
        response = message.get("result", {})
        event("item/completed", item={"id": "call-1", "type": "dynamicToolCall", "namespace": None,
              "tool": "archive_read", "arguments": {"id": "event-old"}, "status": "completed",
              "contentItems": response.get("contentItems", []), "success": response.get("success")})
        complete(summary="Archive retrieved" if response.get("success") else "Archive request declined")
        continue
    elif message.get("id") == "approval-1":
        result = message.get("result", {})
        accepted = result.get("decision") == "accept" or bool(result.get("permissions"))
        if accepted:
            Path("approved.txt").write_text("explicit approval")
        complete(summary="Approval accepted" if accepted else "Approval declined")
        continue
    else:
        emit({"id": message.get("id"), "error": {"code": -32601, "message": "unexpected method"}})
        continue
    emit({"id": message["id"], "result": result})

if scenario == "graceful_close":
    time.sleep(0.05)
    record({"graceful_shutdown": True})
