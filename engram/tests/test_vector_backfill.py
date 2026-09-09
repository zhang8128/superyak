"""Startup backfills must release SQLite's writer slot before model work."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import server
from config import EngramConfig
from maintenance import MaintenanceReport
from storage import Storage, _pack_embedding


LAYERS = (
    ("episode", "episodes", "content", "episode_vectors", "episode-vector-backfill"),
    ("semantic", "semantics", "content", "semantic_vectors", "semantic-vector-backfill"),
    ("instinct", "instincts", "action", "instinct_vectors", "instinct-vector-backfill"),
    ("perceptual", "instincts", "action", "instinct_context_vectors", "instinct-perceptual-backfill"),
)


@pytest.fixture
def backfill_store(tmp_db, monkeypatch):
    monkeypatch.setattr(server, "_storage", tmp_db)
    monkeypatch.setattr(server, "_config", EngramConfig())
    monkeypatch.setattr(server, "_session_id", "backfill-test")
    monkeypatch.setattr(server, "_framing_cfg", None)
    # These fixtures have no uncompressed episodes, so startup never calls a model.
    monkeypatch.setattr(server, "_compressor", None)
    yield tmp_db


def _seed(store, layer):
    for number in (1, 2):
        identifier, text = f"memory-{number}", f"remember synthetic detail {number}"
        if layer == "episode":
            store.add_episode(identifier, None, text)
            store.mark_episodes_compressed([identifier])
        elif layer == "semantic":
            store.add_semantic(identifier, text, "fact", 0.5, [0.1] * 768, [])
            store.conn.execute("DELETE FROM semantic_vectors WHERE id = ?", (identifier,))
            store.conn.commit()
        else:
            store.add_instinct(
                identifier, "preference", text, [],
                embedding=[0.1] * 768 if layer == "perceptual" else None,
                notice=None if layer == "perceptual" else "when working",
                implication=None if layer == "perceptual" else "use the detail",
            )


def _track_step_transactions(monkeypatch, store):
    states = []
    original_step = MaintenanceReport.step

    @contextmanager
    def observed_step(report, name):
        with original_step(report, name) as result:
            yield result
        states.append((name, store.conn.in_transaction))

    monkeypatch.setattr(MaintenanceReport, "step", observed_step)
    return states


@pytest.mark.parametrize("layer,table,text_column,vector_table,step", LAYERS)
@pytest.mark.parametrize("failure", [None, "embedding", "vector-write"])
def test_backfill_model_work_releases_writer_and_failure_leaves_no_transaction(
    backfill_store, monkeypatch, layer, table, text_column, vector_table, step,
    failure,
):
    store = backfill_store
    _seed(store, layer)
    peer = Storage(store.db_path)
    peer.conn.execute("PRAGMA busy_timeout=0")
    probes = []
    states = _track_step_transactions(monkeypatch, store)

    def embed(texts, **kwargs):
        # A real independent writer must be able to proceed on every model call.
        with peer.transaction():
            peer.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('writer-probe', ?)",
                (str(len(probes) + 1),),
            )
        probes.append(texts)
        if len(probes) == 2:
            if failure == "embedding":
                raise RuntimeError("synthetic embedding failure")
            if failure == "vector-write":
                # sqlite-vec rejects the wrong dimension during the write;
                # perceptual fields must roll back together with that vector.
                return [[0.2] * 384 for _ in texts]
        return [[0.2] * 768 for _ in texts]

    monkeypatch.setattr(server, "_embeddings", SimpleNamespace(embed=embed))
    try:
        server._run_sleep_maintenance()
        report = MaintenanceReport.load_last(store.conn)
        result = next(item for item in report["steps"] if item["name"] == step)
        assert len(probes) == 2, result
        assert result["ok"] is (failure is None)
        assert store.conn.execute(f"SELECT COUNT(*) FROM {vector_table}").fetchone()[0] == (
            1 if failure else 2
        )
        assert not any(active for _, active in states), states
        assert not store.conn.in_transaction
        if layer == "perceptual" and failure:
            assert store.get_instinct("memory-2")["notice"] is None
    finally:
        peer.close()


@pytest.mark.parametrize("layer,table,text_column,vector_table,step", LAYERS)
@pytest.mark.parametrize("concurrent_change", ["fill", "delete", "edit"])
def test_backfill_rechecks_source_and_existing_vector_after_embedding(
    backfill_store, monkeypatch, layer, table, text_column, vector_table, step,
    concurrent_change,
):
    store = backfill_store
    _seed(store, layer)
    peer = Storage(store.db_path)
    peer.conn.execute("PRAGMA busy_timeout=0")
    calls = 0
    concurrent_vector = _pack_embedding([0.7] * 768)

    def embed(texts, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            with peer.transaction():
                if concurrent_change == "fill":
                    peer.conn.execute(
                        f"INSERT INTO {vector_table}(id, embedding) VALUES (?, ?)",
                        ("memory-1", concurrent_vector),
                    )
                    if layer == "perceptual":
                        peer.conn.execute(
                            "UPDATE instincts SET notice='concurrent notice', "
                            "implication='concurrent implication' WHERE id='memory-1'"
                        )
                elif concurrent_change == "delete":
                    peer.conn.execute(f"DELETE FROM {table} WHERE id='memory-1'")
                else:
                    peer.conn.execute(
                        f"UPDATE {table} SET {text_column}='changed content' WHERE id='memory-1'"
                    )
        return [[0.2] * 768 for _ in texts]

    monkeypatch.setattr(server, "_embeddings", SimpleNamespace(embed=embed))
    try:
        server._run_sleep_maintenance()
        report = MaintenanceReport.load_last(store.conn)
        result = next(item for item in report["steps"] if item["name"] == step)
        assert result["ok"], result
        first = store.conn.execute(
            f"SELECT embedding FROM {vector_table} WHERE id='memory-1'"
        ).fetchone()
        if concurrent_change == "fill":
            assert first[0] == concurrent_vector
            if layer == "perceptual":
                assert store.get_instinct("memory-1")["notice"] == "concurrent notice"
        else:
            assert first is None
        assert store.conn.execute(
            f"SELECT 1 FROM {vector_table} WHERE id='memory-2'"
        ).fetchone() is not None
        assert not store.conn.in_transaction
    finally:
        peer.close()
