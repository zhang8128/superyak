from copy import deepcopy

import neighbors
from tests.test_recall_margins import engram_server_env, seed


def test_default_recall_does_not_invoke_receiver(engram_server_env, monkeypatch):
    server = engram_server_env
    seed(2)
    def fail(*a, **kw): raise AssertionError("receiver should be off")
    monkeypatch.setattr(neighbors, "attach_neighbors", fail)
    result = server.recall("rivers", uninvited=0)
    assert result["results"]
    assert "neighbors" not in result


def test_explicit_context_attaches_after_local_recall(engram_server_env, monkeypatch):
    server = engram_server_env
    seed(2)
    seen = {}
    def attach(response, **kw):
        seen.update(response=deepcopy(response), args=kw)
        response["neighbors"] = {"delivered": [{"memoryId": "remote"}]}
    monkeypatch.setattr(neighbors, "attach_neighbors", attach)
    result = server.recall("rivers", uninvited=0, lighthouse_context="memory/technical")
    assert {k: v for k, v in result.items() if k != "neighbors"} == seen["response"]
    assert seen["args"]["context_id"] == "memory/technical"
    assert all(row["id"] != "remote" for row in result["results"])


def test_unexpected_receiver_error_preserves_local_response(engram_server_env, monkeypatch):
    server = engram_server_env
    seed(2)
    def fail(*a, **kw): raise RuntimeError("bad neighbor")
    monkeypatch.setattr(neighbors, "attach_neighbors", fail)
    result = server.recall("rivers", uninvited=0, lighthouse_context="memory/technical")
    assert result["results"]
    assert "neighbors" in result["degraded"]


def test_instinct_only_recall_remains_local(engram_server_env, monkeypatch):
    server = engram_server_env
    def fail(*a, **kw): raise AssertionError("instincts are local")
    monkeypatch.setattr(neighbors, "attach_neighbors", fail)
    assert "neighbors" not in server.recall("rivers", layer="instinct", lighthouse_context="memory/technical")
