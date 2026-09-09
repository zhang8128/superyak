"""Observable questions/replies at the Codex protocol boundary."""

import json
import pytest

from session_bridge import Sessions
from context_provider import ProviderError


SENDER = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
CLIENT = "33333333-3333-4333-8333-333333333333"
HANDLE = f"sq1:{TARGET}:{CLIENT}"


class Peer:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, method, params):
        self.calls.append((method, params))
        return self.responses[method]


def test_session_discovery_exposes_metadata_without_private_previews():
    peer = Peer({"thread/list": {"data": [{
        "id": TARGET, "name": "Parser work", "cwd": "/work/parser",
        "preview": "Private conversation text", "status": {"type": "notLoaded"},
        "source": "cli", "parentThreadId": None, "canAcceptDirectInput": True,
    }], "nextCursor": "next-page"}})
    result = Sessions(peer).list()
    assert result["sessions"] == [{
        "id": TARGET, "name": "Parser work", "cwd": "/work/parser",
        "availability": "unknown", "source": "cli",
    }]
    assert result["next_cursor"] == "next-page"
    assert "Private conversation" not in str(result)


def test_ask_queues_an_attributed_question_without_resuming_the_target():
    class QueuePeer(Peer):
        def rpc(self, method, params):
            if method == "thread/queue/add":
                self.calls.append((method, params))
                return {"queuedSubmission": {
                    "id": "native-queue-id", "clientUserMessageId": params["clientUserMessageId"],
                }}
            return super().rpc(method, params)

    peer = QueuePeer({"thread/read": {"thread": {
        "id": TARGET, "source": "cli", "canAcceptDirectInput": True,
    }}})
    result = Sessions(peer).ask(TARGET, "Which parser file did you change?", sender=SENDER)
    assert result["status"] == "queued"
    assert result["request_id"].startswith(f"sq1:{TARGET}:")
    methods = [method for method, _ in peer.calls]
    assert methods == ["thread/read", "thread/queue/add"]
    queued = peer.calls[-1][1]
    assert queued["threadId"] == TARGET
    assert queued["clientUserMessageId"] == result["request_id"].split(":")[-1]
    text = queued["input"][0]["text"]
    assert SENDER in text and "Which parser file did you change?" in text
    assert "not new human authorization" in text


def test_self_question_is_rejected_before_any_rpc():
    peer = Peer({})
    with pytest.raises(ValueError, match="your own session"):
        Sessions(peer).ask(SENDER, "Any update?", sender=SENDER)
    assert peer.calls == []


def test_result_returns_only_the_final_answer_to_the_correlated_question():
    peer = Peer({"thread/turns/list": {"data": [
        {"id": "other", "status": "completed", "items": [
            {"type": "userMessage", "clientId": "unrelated"},
            {"type": "agentMessage", "phase": "final_answer", "text": "Private unrelated answer"},
        ]},
        {"id": "matching", "status": "completed", "items": [
            {"type": "userMessage", "clientId": CLIENT, "content": "Private prompt"},
            {"type": "agentMessage", "phase": "commentary", "text": "I am checking"},
            {"type": "commandExecution", "aggregatedOutput": "Private command output"},
            {"type": "agentMessage", "phase": "final_answer", "text": "I changed parser.py."},
        ]},
    ], "nextCursor": None}})
    result = Sessions(peer).result(HANDLE)
    assert result == {"request_id": HANDLE, "target_session": TARGET,
                      "status": "completed", "turn_id": "matching", "answer": "I changed parser.py."}
    assert "Private" not in str(result) and "I am checking" not in str(result)


def test_result_does_not_confuse_queue_acceptance_with_an_answer():
    peer = Peer({
        "thread/turns/list": {"data": [], "nextCursor": None},
        "thread/queue/list": {"data": [{"id": "q", "clientUserMessageId": CLIENT}], "nextCursor": None},
    })
    result = Sessions(peer).result(HANDLE)
    assert result["status"] == "queued"
    assert "answer" not in result


def test_large_history_can_be_continued_without_exposing_it():
    peer = Peer({"thread/turns/list": {"data": [], "nextCursor": "older-turns"},
                 "thread/queue/list": {"data": [], "nextCursor": None}})
    result = Sessions(peer).result(HANDLE)
    assert result["status"] == "searching"
    assert result["next_cursor"] == "older-turns"


def test_lost_queue_acknowledgment_keeps_handle_and_does_not_retry():
    class LostAck(Peer):
        def rpc(self, method, params):
            self.calls.append((method, params))
            if method == "thread/queue/add":
                raise ProviderError("connection closed")
            return {"thread": {"id": TARGET, "source": "cli"}}

    peer = LostAck({})
    result = Sessions(peer).ask(TARGET, "What changed?", SENDER)
    assert result["status"] == "submission_unknown"
    assert result["request_id"].startswith(f"sq1:{TARGET}:")
    assert [name for name, _ in peer.calls].count("thread/queue/add") == 1


@pytest.mark.parametrize("thread", [
    {"parentThreadId": SENDER}, {"canAcceptDirectInput": False},
    {"ephemeral": True}, {"source": {"subAgent": "reviewer"}},
])
def test_noninteractive_targets_are_rejected_before_queueing(thread):
    peer = Peer({"thread/read": {"thread": {"id": TARGET, "source": "cli", **thread}}})
    with pytest.raises(ValueError, match="persistent interactive"):
        Sessions(peer).ask(TARGET, "What changed?", SENDER)
    assert [name for name, _ in peer.calls] == ["thread/read"]


@pytest.mark.parametrize("target,question", [("not-a-uuid", "Question?"), (TARGET, ""), (TARGET, "🦊" * 2001)])
def test_invalid_or_oversized_questions_do_not_reach_codex(target, question):
    peer = Peer({})
    with pytest.raises(ValueError):
        Sessions(peer).ask(target, question, SENDER)
    assert peer.calls == []


@pytest.mark.parametrize("status,completed_at,expected", [
    ("inProgress", None, "running"), ("failed", 123, "failed"),
    ("interrupted", 123, "interrupted"), ("interrupted", None, "pending_unknown"),
])
def test_unfinished_or_failed_turns_do_not_publish_partial_answers(status, completed_at, expected):
    peer = Peer({"thread/turns/list": {"data": [{"id": "turn", "status": status, "completedAt": completed_at, "items": [
        {"type": "userMessage", "clientId": CLIENT},
        {"type": "agentMessage", "text": "Incomplete response", "phase": None},
    ]}], "nextCursor": None}})
    result = Sessions(peer).result(HANDLE)
    assert result["status"] == expected and "answer" not in result


def test_older_unphased_models_return_only_the_last_message_and_flag_truncation():
    peer = Peer({"thread/turns/list": {"data": [{"id": "turn", "status": "completed", "items": [
        {"type": "userMessage", "clientId": CLIENT},
        {"type": "agentMessage", "text": "Intermediate thought", "phase": None},
        {"type": "agentMessage", "text": "🦊" * 20000, "phase": None},
    ]}], "nextCursor": None}})
    result = Sessions(peer).result(HANDLE)
    assert result["answer"] == "🦊" * 16384
    assert result["answer_truncated"] is True


def test_result_continuation_stays_with_the_requested_session():
    peer = Peer({"thread/turns/list": {"data": [], "nextCursor": None},
                 "thread/queue/list": {"data": [], "nextCursor": None}})
    result = Sessions(peer).result(HANDLE, cursor="older-turns")
    assert result["status"] == "not_found" and "answer" not in result
    assert peer.calls[0][1]["cursor"] == "older-turns"
    assert all(params["threadId"] == TARGET for _, params in peer.calls)


def test_incomplete_queue_page_cannot_be_reported_as_absence():
    peer = Peer({"thread/turns/list": {"data": [], "nextCursor": None},
                 "thread/queue/list": {"data": [], "nextCursor": "100"}})
    result = Sessions(peer).result(HANDLE)
    assert result["status"] == "pending_unknown"
    assert "answer" not in result
