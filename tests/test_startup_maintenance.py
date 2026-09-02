"""Sleep-time maintenance must not block the MCP handshake.

Claude Code gives an MCP server 30 s to connect. On 2026-09-02 the first
session bound to a fresh instance store spent ~40 s in startup compression
(genome replicated, then auto-compressed) and the client gave up, leaving the
session without memory tools. The served entry point now defers maintenance
to a background thread that holds the same lifecycle barrier as tool calls;
library and test callers of _init() keep the inline behavior.
"""

from __future__ import annotations

import threading
import time

import server

from tests.test_server_registry import engram_server_env  # noqa: F401  (fixture)


def test_init_runs_sleep_maintenance_inline_by_default(engram_server_env, monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_run_sleep_maintenance", lambda guarded=False: calls.append(("inline", guarded)))

    server._init()

    assert calls == [("inline", False)]
    assert server._sleep_maintenance_deferred is False
    assert server._sleep_maintenance_thread is None
    assert "maintenance_pending" not in server.status()


def test_initialize_pre_serving_returns_before_maintenance_finishes(engram_server_env, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_maintenance(guarded=False):
        with server._maintenance_step_scope(guarded):
            started.set()
            release.wait(10)
            finished.set()

    monkeypatch.setattr(server, "_run_sleep_maintenance", slow_maintenance)

    t0 = time.monotonic()
    server._initialize_pre_serving()
    returned_after = time.monotonic() - t0

    try:
        assert server._initialized is True
        assert started.wait(5), "deferred maintenance thread never started"
        assert not finished.is_set(), "pre-serving waited for maintenance"
        assert server._sleep_maintenance_deferred is True
        assert returned_after < 5
    finally:
        release.set()
        server._sleep_maintenance_thread.join(10)

    assert finished.is_set()
    assert server._sleep_maintenance_deferred is False
    assert "maintenance_pending" not in server.status()


def test_deferred_maintenance_holds_the_lifecycle_barrier(engram_server_env, monkeypatch):
    """A tool call that arrives during a deferred maintenance step waits for that step."""
    started = threading.Event()
    release = threading.Event()

    def slow_maintenance(guarded=False):
        assert guarded is True
        with server._maintenance_step_scope(guarded):
            started.set()
            release.wait(10)

    monkeypatch.setattr(server, "_run_sleep_maintenance", slow_maintenance)
    server._initialize_pre_serving()
    assert started.wait(5)

    results = []
    caller = threading.Thread(target=lambda: results.append(server.status()), daemon=True)
    caller.start()
    caller.join(0.5)
    try:
        assert caller.is_alive(), "status() ran while maintenance held the barrier"
    finally:
        release.set()
        caller.join(10)
        server._sleep_maintenance_thread.join(10)

    assert results and results[0]["session_id"] == server._session_id
    assert "maintenance_pending" not in results[0]


def test_deferred_maintenance_records_its_report(engram_server_env):
    """The real pass runs to completion in the background and lands in status()."""
    server._initialize_pre_serving()
    thread = server._sleep_maintenance_thread
    assert thread is not None
    thread.join(60)
    assert not thread.is_alive()

    report = server.status().get("last_maintenance")
    assert report is not None
    assert report["ok"] is True


def test_compressor_can_defer_and_discard_knowledge_feeds(engram_server_env):
    server._init()
    compressor = server._compressor
    fed = []
    compressor._knowledge_graph = type("KG", (), {"feed": lambda self, eps, semantic_content="": fed.append((eps, semantic_content))})()
    # The served init turns on background feeds; this test exercises the
    # defer/flush/discard mechanics through the synchronous path.
    compressor.background_knowledge_feeds = False

    compressor.pending_knowledge_feeds = [([{"id": "e1"}], "sem-1")]
    assert compressor.flush_knowledge_feeds() == 1
    assert fed == [([{"id": "e1"}], "sem-1")]
    assert compressor.pending_knowledge_feeds == []

    compressor.pending_knowledge_feeds = [([{"id": "e2"}], "sem-2"), ([{"id": "e3"}], "sem-3")]
    assert compressor.discard_knowledge_feeds() == 2
    assert fed == [([{"id": "e1"}], "sem-1")]
    assert compressor.pending_knowledge_feeds == []


def test_startup_auto_compress_skips_knowledge_feeds(engram_server_env, monkeypatch):
    from maintenance import MaintenanceReport

    server._init()
    monkeypatch.setattr(server._storage, "get_uncompressed_episodes", lambda: [{"id": "x"}])

    seen = []

    class StubCompressor:
        defer_knowledge_feeds = False

        def __init__(self):
            self.pending_knowledge_feeds = []

        def auto_compress(self):
            seen.append(self.defer_knowledge_feeds)
            self.pending_knowledge_feeds = [([{"id": "x"}], "sem")] * 2
            return {}

        def discard_knowledge_feeds(self):
            dropped = len(self.pending_knowledge_feeds)
            self.pending_knowledge_feeds = []
            return dropped

    stub = StubCompressor()
    monkeypatch.setattr(server, "_compressor", stub)

    report = MaintenanceReport()
    with report.step("auto-compress"):
        server._startup_auto_compress(report)

    assert seen == [True]
    assert stub.defer_knowledge_feeds is False
    assert stub.pending_knowledge_feeds == []
    assert report.steps[0]["pending"] == 1
    assert report.steps[0]["knowledge_feeds_skipped"] == 2
    assert report.ok
