"""End-to-end integration test for instinct co-firing clusters."""

import hashlib
import uuid
import pytest
from storage import Storage
from compress import Compressor
from clusters import ClusterEngine
from reflection import Reflector


class FakeEmbeddingProvider:
    def __init__(self):
        self.override_map: dict[str, list[float]] = {}

    def embed(self, texts: list[str], **_kwargs) -> list[list[float]]:
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


def test_full_cluster_lifecycle(storage, embeddings):
    """Instinct → cluster seed → co-fire → re-derive → temperament → reflect."""
    compressor = Compressor(storage, embeddings)
    engine = ClusterEngine(storage, embeddings)
    reflector = Reflector(storage)

    # 1. Create semantics that will produce instincts
    coding_emb = embeddings.embed(["always restart MCP after code changes"])[0]
    sports_emb = embeddings.embed(["watch the ball into contact point"])[0]

    storage.add_semantic(
        str(uuid.uuid4()), "always restart MCP after code changes",
        kind="constraint", confidence=0.9, embedding=coding_emb,
        source_episode_ids=[],
    )
    storage.add_semantic(
        str(uuid.uuid4()), "check imports before running",
        kind="constraint", confidence=0.9, embedding=coding_emb,
        source_episode_ids=[],
    )
    storage.add_semantic(
        str(uuid.uuid4()), "watch the ball into contact point",
        kind="preference", confidence=0.9, embedding=sports_emb,
        source_episode_ids=[],
    )
    storage.add_semantic(
        str(uuid.uuid4()), "follow through on every swing",
        kind="preference", confidence=0.9, embedding=sports_emb,
        source_episode_ids=[],
    )

    # 2. Compression creates instincts and seeds clusters
    created = compressor._check_instinct_creation()
    assert created >= 2

    instincts = storage.get_all_instincts()
    assert len(instincts) >= 2

    # Each instinct should have a cluster
    for inst in instincts:
        strengths = storage.get_instinct_cluster_strengths(inst["id"])
        assert len(strengths) >= 1

    # 3. Simulate co-firing
    coding_instincts = [i for i in instincts if "MCP" in i["action"] or "import" in i["action"]]
    sports_instincts = [i for i in instincts if "ball" in i["action"] or "swing" in i["action"]]

    if len(coding_instincts) >= 2:
        for _ in range(10):
            storage.record_co_fire(
                coding_instincts[0]["id"], coding_instincts[1]["id"], followed=True
            )

    if len(sports_instincts) >= 2:
        for _ in range(10):
            storage.record_co_fire(
                sports_instincts[0]["id"], sports_instincts[1]["id"], followed=True
            )

    # 4. Re-derive clusters from co-firing
    cluster_ids = engine.derive_clusters()
    assert len(cluster_ids) >= 1

    # 5. Check temperament (all followed → conservative)
    for cid in cluster_ids:
        cluster = storage.get_cluster(cid)
        if cluster["member_count"] >= 2:
            assert cluster["temperament"] < 0.5  # conservative

    # 6. Reflect shows clusters
    result = reflector.reflect(focus="instinct_clusters")
    assert "instinct_clusters" in result
    assert len(result["instinct_clusters"]) >= 1

    for c in result["instinct_clusters"]:
        assert "members" in c
        assert "temperament" in c
        assert "maturity" in c
