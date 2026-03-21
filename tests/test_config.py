"""Tests for engram config v2 — watcher, community, ranking sections."""

from __future__ import annotations

from config import EngramConfig, load_config


def test_config_has_watcher_defaults():
    cfg = EngramConfig()
    assert cfg.watcher.enabled is True
    assert cfg.watcher.debounce_ms == 500
    assert ".py" in cfg.watcher.extensions


def test_config_has_community_defaults():
    cfg = EngramConfig()
    assert cfg.communities.min_size == 3
    assert cfg.communities.max_depth == 3
    assert cfg.communities.cache_ttl_seconds == 300


def test_config_has_ranking_defaults():
    cfg = EngramConfig()
    assert cfg.ranking.similarity_weight == 0.5
    assert cfg.ranking.recency_weight == 0.3
    assert cfg.ranking.degree_weight == 0.2


def test_config_loads_watcher_from_toml(tmp_path):
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    (engram_dir / "config.toml").write_text(
        '[watcher]\nenabled = false\ndebounce_ms = 1000\nextensions = [".py", ".rb"]\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.watcher.enabled is False
    assert cfg.watcher.debounce_ms == 1000
    assert cfg.watcher.extensions == [".py", ".rb"]


def test_config_loads_ranking_from_toml(tmp_path):
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    (engram_dir / "config.toml").write_text(
        "[ranking]\nsimilarity_weight = 0.7\nrecency_weight = 0.2\ndegree_weight = 0.1\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.ranking.similarity_weight == 0.7
    assert cfg.ranking.recency_weight == 0.2
    assert cfg.ranking.degree_weight == 0.1


def test_config_existing_extraction_provider_still_loads(tmp_path):
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    (engram_dir / "config.toml").write_text('[extraction]\nprovider = "heuristic"\n')
    cfg = load_config(tmp_path)
    assert cfg.extraction.provider == "heuristic"


def test_v3_config_sections(tmp_path):
    from config import load_config
    config = load_config(tmp_path)
    assert config.compression.auto_threshold == 10
    assert config.compression.cluster_similarity == 0.75
    assert config.compression.reinforce_threshold == 0.70
    assert config.compression.instinct_confidence == 0.5
    assert config.reflection.enabled is True
    assert config.reflection.log_retention_days == 90
    assert config.reflection.staleness_days == 30
    assert config.memory.similarity_weight == 0.6
    assert config.memory.recency_weight == 0.4
