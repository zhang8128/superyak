"""Tests for instinct cluster engine."""

import uuid
import pytest
from clusters import ClusterEngine
from storage import Storage


class FakeEmbeddingProvider:
    """Returns deterministic embeddings with override support."""

    def __init__(self):
        self.override_map: dict[str, list[float]] = {}

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
        import hashlib
        results = []
        for text in texts:
            if text in self.override_map:
                results.append(self.override_map[text])
            else:
                h = hashlib.md5(text.encode()).digest()
                emb = [float(b) / 255.0 for b in h] * 48
                results.append(emb)
        return results

    def dimension(self) -> int:
        return 768


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = Storage(str(db), migrations_dir="migrations")
    yield s
    s.close()


@pytest.fixture
def embeddings():
    return FakeEmbeddingProvider()


@pytest.fixture
def engine(storage, embeddings):
    return ClusterEngine(storage, embeddings)


def _add_instinct(storage, id, action, embedding):
    storage.add_instinct(id, "preference", action, [], embedding=embedding)


def test_seed_clusters_from_embeddings(storage, engine, embeddings):
    """Cold start: cluster instincts by embedding similarity."""
    coding_emb = [1.0] + [0.0] * 767
    sports_emb = [0.0] + [1.0] + [0.0] * 766

    _add_instinct(storage, "c1", "use asyncio.run()", coding_emb)
    _add_instinct(storage, "c2", "restart MCP server", coding_emb)
    _add_instinct(storage, "s1", "watch the ball", sports_emb)
    _add_instinct(storage, "s2", "follow through on swing", sports_emb)

    embeddings.override_map["use asyncio.run()"] = coding_emb
    embeddings.override_map["restart MCP server"] = coding_emb
    embeddings.override_map["watch the ball"] = sports_emb
    embeddings.override_map["follow through on swing"] = sports_emb

    clusters = engine.seed_clusters()
    assert len(clusters) == 2

    for cid in clusters:
        members = storage.get_cluster_members(cid)
        assert len(members) == 2

    for cid in clusters:
        cluster = storage.get_cluster(cid)
        assert cluster["maturity"] == "seeded"


def test_seed_clusters_singleton_distant(storage, engine, embeddings):
    """A distant instinct gets its own cluster."""
    emb_a = [1.0] + [0.0] * 767
    emb_c = [0.0, 0.0] + [1.0] + [0.0] * 765

    _add_instinct(storage, "a1", "thing a1", emb_a)
    _add_instinct(storage, "a2", "thing a2", emb_a)
    _add_instinct(storage, "lone", "unique thing", emb_c)

    embeddings.override_map["thing a1"] = emb_a
    embeddings.override_map["thing a2"] = emb_a
    embeddings.override_map["unique thing"] = emb_c

    clusters = engine.seed_clusters()
    assert len(clusters) >= 2


def test_rederive_from_co_firing(storage, engine, embeddings):
    """With enough co-firing data, clusters re-derive from behavior."""
    emb = [0.1] * 768
    _add_instinct(storage, "a1", "instinct a1", emb)
    _add_instinct(storage, "a2", "instinct a2", emb)
    _add_instinct(storage, "b1", "instinct b1", emb)
    _add_instinct(storage, "b2", "instinct b2", emb)

    embeddings.override_map["instinct a1"] = emb
    embeddings.override_map["instinct a2"] = emb
    embeddings.override_map["instinct b1"] = emb
    embeddings.override_map["instinct b2"] = emb

    for _ in range(10):
        storage.record_co_fire("a1", "a2")
        storage.record_co_fire("b1", "b2")

    clusters = engine.derive_clusters()
    assert len(clusters) == 2

    cluster_members = {}
    for cid in clusters:
        members = storage.get_cluster_members(cid)
        cluster_members[cid] = {m["instinct_id"] for m in members}

    member_sets = list(cluster_members.values())
    assert {"a1", "a2"} in member_sets
    assert {"b1", "b2"} in member_sets


def test_compute_temperament(storage, engine):
    """Temperament emerges from follow/override ratio."""
    emb = [0.1] * 768
    _add_instinct(storage, "i1", "one", emb)
    _add_instinct(storage, "i2", "two", emb)
    storage.create_cluster("c1")
    storage.add_to_cluster("i1", "c1")
    storage.add_to_cluster("i2", "c1")

    for _ in range(10):
        storage.record_co_fire("i1", "i2", followed=True)

    temp = engine.compute_temperament("c1")
    assert temp < 0.3  # conservative

    for _ in range(10):
        storage.record_co_fire("i1", "i2", followed=False)

    temp = engine.compute_temperament("c1")
    assert temp > 0.3  # more exploratory
