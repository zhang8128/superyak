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


# --- settings that act on a store come from the store's home -------------------

def _write(root, text):
    folder = root / ".engram"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_text(text)


def _routed(home, project):
    return config.with_store_settings(config.load_config(project), home, project)


def test_a_store_switched_on_in_its_home_stays_on_from_another_folder(tmp_path, caplog):
    # The fault this fixes: a session started in any other folder read that folder's default file, which says off.
    home, project = tmp_path / "home", tmp_path / "project"
    _write(home, "[cohesion]\nenabled = true\ndl_cost = 0.05\n\n[category_evolution]\nenabled = true\nshadow = true\n")
    project.mkdir()

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(home, project)  # load_config makes the project's file from defaults, as a first session does

    assert (project / ".engram" / "config.toml").exists()
    assert loaded.cohesion.enabled is True and loaded.cohesion.dl_cost == 0.05
    assert loaded.category_evolution.enabled is True and loaded.category_evolution.shadow is True
    assert loaded.persistence.enabled is False  # the home's file leaves it out: defaults, which are off
    assert caplog.text == ""  # the project asked for nothing the store lacks


def test_only_the_three_store_sections_move(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    _write(home, '[cohesion]\nenabled = true\n\n[memory]\ndefault_lane = "personal"\n\n[compression]\nauto_threshold = 99\n')
    _write(project, 'instance = "lighthouse"\n\n[memory]\ndefault_lane = "work"\n\n[compression]\nauto_threshold = 7\n')

    loaded = _routed(home, project)

    assert loaded.cohesion.enabled is True
    assert loaded.instance == "lighthouse"
    assert loaded.memory.default_lane == "work" and loaded.compression.auto_threshold == 7
    assert config.STORE_SECTIONS == ("cohesion", "persistence", "category_evolution")


def test_a_project_cannot_switch_a_store_gate_on_and_is_told_which_file_decides(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    _write(home, "[cohesion]\nenabled = false\n")
    _write(project, "[cohesion]\nenabled = true\ndl_cost = 0.01\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(home, project)

    assert loaded.cohesion.enabled is False and loaded.cohesion.dl_cost == config.CohesionConfig().dl_cost
    assert loaded.persistence.enabled is False  # forgetting never starts from a project's file
    assert "Ignoring [cohesion] enabled" in caplog.text
    assert "Ignoring [persistence] enabled" in caplog.text
    assert str(project / ".engram" / "config.toml") in caplog.text
    assert str(home / ".engram" / "config.toml") in caplog.text


def test_a_home_with_no_config_gives_defaults_and_gets_no_file(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    _write(project, "[cohesion]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(home, project)

    assert loaded.cohesion == config.CohesionConfig()
    assert loaded.persistence == config.PersistenceConfig()
    assert loaded.category_evolution == config.CategoryEvolutionConfig()
    assert not (home / ".engram").exists()  # reading a store's settings writes nothing into its home
    assert "Ignoring [cohesion] enabled" in caplog.text
    assert "Could not read" not in caplog.text  # a home with no file is ordinary, not a fault


def test_a_home_config_that_cannot_be_read_leaves_the_gates_off_and_says_so(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    _write(home, "[cohesion\nenabled = true\n")
    _write(project, "[cohesion]\nenabled = true\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(home, project)

    assert loaded.cohesion.enabled is False and loaded.persistence.enabled is False
    assert "Could not read the store's config" in caplog.text
    assert str(home / ".engram" / "config.toml") in caplog.text


def test_when_the_project_is_the_home_nothing_changes(tmp_path, caplog):
    home = tmp_path / "home"
    _write(home, "[cohesion]\nenabled = true\ndl_cost = 0.05\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(home, home)

    assert loaded.cohesion.enabled is True and loaded.cohesion.dl_cost == 0.05
    assert loaded.persistence.enabled is True
    assert caplog.text == ""


def test_the_server_routes_its_config_through_the_store(tmp_path, monkeypatch):
    # The server's own start-up, not a stand-in: the config it keeps must be the routed one.
    import server

    home, project = tmp_path / "home", tmp_path / "project"
    _write(home, "[cohesion]\nenabled = true\ndl_cost = 0.05\n")
    project.mkdir()
    monkeypatch.setattr(server, "ENGRAM_HOME", home)
    monkeypatch.setattr(server, "PROJECT_ROOT", project)
    seen = {}

    def stop_after_config(config_value):
        seen["config"] = config_value
        raise RuntimeError("far enough")

    monkeypatch.setattr(server, "resolve_instance_name", stop_after_config)
    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_config", None)  # start-up sets it; this puts the old one back afterwards
    try:
        server._init_unlocked()
    except RuntimeError as stopped:
        assert str(stopped) == "far enough"
    assert seen["config"].cohesion.enabled is True and seen["config"].cohesion.dl_cost == 0.05
