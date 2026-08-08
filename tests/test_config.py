"""Tests for engram config v2 — watcher, community, ranking sections."""

from __future__ import annotations

import pytest

from config import EngramConfig, SignalsConfig, load_config


def test_resource_path_uses_installed_share_when_source_asset_is_absent(
    tmp_path, monkeypatch,
):
    import resources

    installed_root = tmp_path / "share" / "engram"
    marker = installed_root / "migrations" / "001.sql"
    marker.parent.mkdir(parents=True)
    marker.write_text("SELECT 1;")
    monkeypatch.setattr(resources, "_SOURCE_ROOT", tmp_path / "missing-source")
    monkeypatch.setattr(resources, "_INSTALL_ROOT", installed_root)

    assert resources.resource_path("migrations/001.sql") == marker


def test_resource_path_prefers_checked_out_source_asset(tmp_path, monkeypatch):
    import resources

    source_root = tmp_path / "source"
    installed_root = tmp_path / "share" / "engram"
    source_marker = source_root / "prompts" / "classify.txt"
    installed_marker = installed_root / "prompts" / "classify.txt"
    source_marker.parent.mkdir(parents=True)
    installed_marker.parent.mkdir(parents=True)
    source_marker.write_text("source")
    installed_marker.write_text("installed")
    monkeypatch.setattr(resources, "_SOURCE_ROOT", source_root)
    monkeypatch.setattr(resources, "_INSTALL_ROOT", installed_root)

    assert resources.resource_path("prompts/classify.txt") == source_marker


def test_resource_path_rejects_absolute_path():
    import resources

    with pytest.raises(ValueError, match="must be relative"):
        resources.resource_path("/etc/hosts")


def test_resource_path_rejects_parent_traversal():
    import resources

    with pytest.raises(ValueError, match="parent traversal"):
        resources.resource_path("../migrations/001.sql")


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
    assert config.compression.instinct_confidence == 0.75
    assert config.reflection.enabled is True
    assert config.reflection.log_retention_days == 90
    assert config.reflection.staleness_days == 30
    assert config.memory.similarity_weight == 0.6
    assert config.memory.recency_weight == 0.4


def test_federation_config_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert cfg.instance is None
    assert cfg.session_context is None
    assert cfg.signals.retention_days == 30


def test_federation_config_with_instance(tmp_path):
    engram_dir = tmp_path / ".engram"
    engram_dir.mkdir()
    (engram_dir / "config.toml").write_text(
        'instance = "agi"\nsession_context = "building"\n\n[signals]\nretention_days = 60\n'
    )
    cfg = load_config(tmp_path)
    assert cfg.instance == "agi"
    assert cfg.session_context == "building"
    assert cfg.signals.retention_days == 60


def test_category_evolution_config_defaults():
    cfg = EngramConfig().category_evolution
    assert (cfg.enabled, cfg.shadow, cfg.influence_recall, cfg.auto_commit) == (
        False, True, False, False,
    )
    assert cfg.archive_quota_bytes == 3_000_000_000_000
    assert cfg.archive_high_watermark_ratio == 0.90
    assert cfg.interpreted_max_dimension == 2
    assert cfg.max_traversal_depth == 4
    assert cfg.max_neighbors == 64
    assert cfg.max_candidates == 50_000
    assert cfg.compile_wall_time_ms == 500
    assert cfg.consolidation_event_interval == 250
    assert cfg.consolidation_rewrite_budget == 32
    assert cfg.max_rewrite_members == 32
    assert cfg.max_active_branches == 4
    assert cfg.soft_boundary_threshold == 0.35
    assert cfg.hard_boundary_threshold == 0.65
    assert cfg.hard_boundary_confirmations == 2


def test_category_evolution_config_loads_independent_gates(tmp_path):
    config_dir = tmp_path / ".engram"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[category_evolution]\n"
        "enabled = true\nshadow = true\n"
        "influence_recall = false\nauto_commit = false\n"
        "max_candidates = 1234\n"
    )
    cfg = load_config(tmp_path).category_evolution
    assert cfg.enabled is True
    assert cfg.influence_recall is False
    assert cfg.auto_commit is False
    assert cfg.max_candidates == 1234
