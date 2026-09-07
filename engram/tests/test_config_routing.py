from __future__ import annotations

import logging

import config


def test_unknown_memory_key_keeps_configured_instance_routing(
    tmp_path, caplog
):
    engram_home = tmp_path / "engram-home"
    project_root = tmp_path / "project"
    instance_db = (
        engram_home
        / ".engram"
        / "instances"
        / "lighthouse"
        / "graph.db"
    )
    instance_db.parent.mkdir(parents=True)
    instance_db.touch()
    config_dir = project_root / ".engram"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        'instance = "lighthouse"\n\n'
        "[memory]\n"
        "future_memory_option = true\n"
    )

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = config.load_config(project_root)
        resolved = config.resolve_db_path(engram_home, project_root)

    assert loaded.instance == "lighthouse"
    assert resolved == instance_db
    assert "future_memory_option" in caplog.text


def test_invalid_toml_warns_with_config_and_fallback_paths(tmp_path, caplog):
    engram_home = tmp_path / "engram-home"
    project_root = tmp_path / "project"
    fallback = engram_home / ".engram" / "graph.db"
    config_dir = project_root / ".engram"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(
        "[memory]\n"
        "max_recall_results = 10\n"
        "[memory]\n"
        "max_recall_results = 20\n"
    )

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        resolved = config.resolve_db_path(engram_home, project_root)

    assert resolved == fallback
    assert str(config_path) in caplog.text
    assert str(fallback) in caplog.text
    assert "memory" in caplog.text


def test_missing_named_instance_warns_with_store_and_fallback(tmp_path, caplog):
    engram_home = tmp_path / "engram-home"
    project_root = tmp_path / "project"
    fallback = engram_home / ".engram" / "graph.db"
    missing_store = (
        engram_home
        / ".engram"
        / "instances"
        / "missing-city"
        / "graph.db"
    )
    config_dir = project_root / ".engram"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text('instance = "missing-city"\n')

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        resolved = config.resolve_db_path(engram_home, project_root)

    assert resolved == fallback
    assert str(missing_store) in caplog.text
    assert str(fallback) in caplog.text
