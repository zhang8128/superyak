from concurrent.futures import ThreadPoolExecutor

import pytest

from context_store import ContextStore, StoreConflict, ThreadBusy


def test_exact_capture_idempotence_and_thread_search(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    first = store.append("a", "user", "The cow is named Étoile.", event_id="client-1")
    assert store.append("a", "user", "The cow is named Étoile.", event_id="client-1") == first
    with pytest.raises(StoreConflict):
        store.append("a", "user", "Different input", event_id="client-1")
    store.append("b", "user", "Étoile belongs to another account")
    assert [r["content"] for r in store.search("a", "Étoile")] == ["The cow is named Étoile."]
    assert len(store.recent("a")) == 1
    store.close()
    reopened = ContextStore(tmp_path / "context.db")
    assert reopened.event("a", first["id"])["content"] == "The cow is named Étoile."
    assert reopened.event("b", first["id"]) is None
    reopened.close()


def test_correction_is_durable_and_requires_local_source(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    original = store.append("t", "user", "Call the cow Etoile")
    store.set_state("t", "cow-name", "Etoile", original["id"])
    correction = store.append("t", "user", "Correction: her name is Étoile")
    store.set_state("t", "cow-name", "Étoile", correction["id"])
    with pytest.raises(StoreConflict):
        store.set_state("other", "cow-name", "stolen", correction["id"])
    store.close()
    reopened = ContextStore(tmp_path / "context.db")
    assert reopened.state("t")[0]["content"] == "Étoile"
    assert reopened.state("t")[0]["source_id"] == correction["id"]
    reopened.close()


def test_scoped_paged_artifacts_and_deletion(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    artifact = store.put_artifact("a", b"abcdefghij")
    assert store.read_artifact("a", artifact, offset=3, limit=4) == b"defg"
    with pytest.raises(KeyError):
        store.read_artifact("b", artifact)
    with pytest.raises(ValueError):
        store.read_artifact("a", artifact, limit=100_000_000)
    store.append("a", "tool", "a result", metadata={"artifact_id": artifact})
    store.forget_thread("a")
    assert store.recent("a") == []
    with pytest.raises(KeyError):
        store.read_artifact("a", artifact)
    assert not list(store.artifact_dir.glob("*"))
    store.close()


def test_turn_completion_and_interruption_are_not_replayed(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    turn = store.begin_turn("a", "request-1", "hello")
    with pytest.raises(StoreConflict):
        store.begin_turn("a", "request-1", "hello")
    store.finish_turn(turn["id"], {"response": "hi"})
    assert store.begin_turn("a", "request-1", "hello")["result"]["response"] == "hi"
    with pytest.raises(StoreConflict):
        store.begin_turn("a", "request-1", "different")
    interrupted = store.begin_turn("a", "request-2", "continue")
    store.close()
    reopened = ContextStore(tmp_path / "context.db")
    assert reopened.turn(interrupted["id"])["status"] == "running"
    with pytest.raises(StoreConflict):
        reopened.begin_turn("a", "request-2", "continue")
    reopened.close()


def test_thread_lease_excludes_other_store_but_not_other_thread(tmp_path):
    one = ContextStore(tmp_path / "context.db")
    two = ContextStore(tmp_path / "context.db")
    with one.lease("a"):
        with pytest.raises(ThreadBusy):
            with two.lease("a"):
                pass
        with two.lease("b"):
            two.append("b", "user", "independent")
    with two.lease("a"):
        two.append("a", "user", "released")
    one.close()
    two.close()


def test_recent_and_search_do_not_materialize_full_large_events(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    event = store.append("t", "assistant", "needle " + "λ" * 100_000)
    assert len(store.recent("t")[0]["content"]) <= 8192
    assert store.recent("t")[0]["truncated"] is True
    assert len(store.search("t", "needle")[0]["content"]) <= 8192
    assert len(store.event("t", event["id"])["content"]) == 100_007
    store.close()


def test_manifests_and_event_capture_are_thread_scoped(tmp_path):
    store = ContextStore(tmp_path / "context.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: store.append("t", "user", f"item {i}"), range(20)))
    assert len(store.recent("t", limit=30)) == 20
    mid = store.save_manifest("t", {"selected": ["one"], "input_tokens": 20})
    assert store.manifest("t", mid)["input_tokens"] == 20
    assert store.manifest("other", mid) is None
    store.close()


def test_forget_failure_never_restores_references_to_deleted_files(tmp_path, monkeypatch):
    from pathlib import Path
    store = ContextStore(tmp_path / "context.db")
    first = store.put_artifact("t", b"first")
    second = store.put_artifact("t", b"second")
    store.append("t", "user", "delete these")
    original = Path.unlink
    calls = []
    def fail_second(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise PermissionError("simulated artifact cleanup failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_second)
    with pytest.raises(PermissionError):
        store.forget_thread("t")
    assert store.recent("t") == []
    for artifact in (first, second):
        with pytest.raises(KeyError):
            store.read_artifact("t", artifact)
    monkeypatch.setattr(Path, "unlink", original)
    store.collect_artifacts()
    assert not list(store.artifact_dir.glob("*"))
    store.close()


def test_failed_artifact_reference_insert_can_be_cleaned_after_restart(tmp_path):
    import sqlite3
    store = ContextStore(tmp_path / "context.db")
    store.conn.execute("CREATE TRIGGER reject_artifact BEFORE INSERT ON artifacts BEGIN SELECT RAISE(ABORT, 'simulated failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.put_artifact("t", b"private orphaned output")
    store.close()
    reopened = ContextStore(tmp_path / "context.db")
    reopened.forget_thread("t")
    assert not list(reopened.artifact_dir.glob("*"))
    reopened.close()
