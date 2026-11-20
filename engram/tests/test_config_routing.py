from __future__ import annotations

import logging
from pathlib import Path

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


# --- settings that act on a store come from the config beside that store -------

def _write(folder, text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_text(text)


def _store(home, instance=None):
    """A store's graph.db under a home: the default store, or a named instance. Returns its path."""
    folder = home / ".engram" / "instances" / instance if instance else home / ".engram"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "graph.db").touch()
    return folder / "graph.db"


def _routed(db_path, project):
    return config.with_store_settings(config.load_config(project), db_path, project)


ON = "[cohesion]\nenabled = true\ndl_cost = 0.05\n\n[category_evolution]\nenabled = true\nshadow = true\n"


def test_a_store_switched_on_stays_on_from_another_folder(tmp_path, caplog):
    # The fault this fixes: a session started in any other folder read that folder's default file, which says off.
    home, project = tmp_path / "home", tmp_path / "project"
    db = _store(home)
    _write(home / ".engram", ON)
    project.mkdir()

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(db, project)  # load_config makes the project's file from defaults, as a first session does

    assert (project / ".engram" / "config.toml").exists()
    assert loaded.cohesion.enabled is True and loaded.cohesion.dl_cost == 0.05
    assert loaded.category_evolution.enabled is True and loaded.category_evolution.shadow is True
    assert loaded.persistence.enabled is False  # the store's file leaves it out: defaults, which are off
    assert caplog.text == ""  # the project asked for nothing the store lacks


def test_a_gate_on_for_one_store_is_not_on_for_another_in_the_same_home(tmp_path, caplog):
    # The reader's finding on 281a9cb8: one home holds several stores, and a gate is calibrated against one of them.
    home, project = tmp_path / "home", tmp_path / "project"
    default, alpha, beta = _store(home), _store(home, "alpha"), _store(home, "beta")
    _write(home / ".engram", ON)                                   # the default store's own file
    _write(alpha.parent, "[cohesion]\nenabled = true\ndl_cost = 0.11\n")  # alpha's own file
    project.mkdir()                                                 # beta has none

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        for_default, for_alpha, for_beta = (_routed(db, project) for db in (default, alpha, beta))

    assert (for_default.cohesion.enabled, for_default.cohesion.dl_cost) == (True, 0.05)
    assert (for_alpha.cohesion.enabled, for_alpha.cohesion.dl_cost) == (True, 0.11)
    assert for_alpha.category_evolution.enabled is False  # the home's file is the default store's, not alpha's
    assert for_beta.cohesion == config.CohesionConfig() and for_beta.category_evolution.enabled is False
    assert for_beta.persistence.enabled is False
    assert not (beta.parent / "config.toml").exists()  # reading a store's settings writes nothing beside it
    assert caplog.text == ""


def test_a_named_instance_with_no_store_falls_back_to_the_default_store_and_its_file(tmp_path):
    # resolve_db_path sends a binding to a store that isn't there to the default store, so its file decides.
    home, project = tmp_path / "home", tmp_path / "project"
    default = _store(home)
    _write(home / ".engram", ON)
    _write(project / ".engram", 'instance = "missing"\n')

    db = config.resolve_db_path(home, project)

    assert db == default
    assert _routed(db, project).cohesion.enabled is True


def test_only_the_three_store_sections_move(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    db = _store(home, "lighthouse")
    _write(db.parent, '[cohesion]\nenabled = true\n\n[memory]\ndefault_lane = "personal"\n\n[compression]\nauto_threshold = 99\n')
    _write(project / ".engram", 'instance = "lighthouse"\n\n[memory]\ndefault_lane = "work"\n\n[compression]\nauto_threshold = 7\n')

    loaded = _routed(db, project)

    assert loaded.cohesion.enabled is True
    assert loaded.instance == "lighthouse"
    assert loaded.memory.default_lane == "work" and loaded.compression.auto_threshold == 7
    assert config.STORE_SECTIONS == ("cohesion", "persistence", "category_evolution")


def test_a_project_cannot_switch_a_store_gate_on_and_is_told_which_file_decides(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    db = _store(home, "alpha")
    _write(db.parent, "[cohesion]\nenabled = false\n")
    _write(project / ".engram", "[cohesion]\nenabled = true\ndl_cost = 0.01\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(db, project)

    assert loaded.cohesion.enabled is False and loaded.cohesion.dl_cost == config.CohesionConfig().dl_cost
    assert loaded.persistence.enabled is False  # forgetting never starts from a project's file
    assert "Ignoring [cohesion] enabled" in caplog.text
    assert "Ignoring [persistence] enabled" in caplog.text
    assert str(project / ".engram" / "config.toml") in caplog.text
    assert str(db.parent / "config.toml") in caplog.text


def test_a_store_with_no_config_gives_defaults_and_gets_no_file(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    db = _store(home, "alpha")
    _write(home / ".engram", ON)  # the default store's file must not reach alpha
    _write(project / ".engram", "[cohesion]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(db, project)

    assert loaded.cohesion == config.CohesionConfig()
    assert loaded.persistence == config.PersistenceConfig()
    assert loaded.category_evolution == config.CategoryEvolutionConfig()
    assert not (db.parent / "config.toml").exists()
    assert "Ignoring [cohesion] enabled" in caplog.text
    assert "Could not read" not in caplog.text  # a store with no file is ordinary, not a fault


def test_a_store_config_that_cannot_be_read_leaves_the_gates_off_and_says_so(tmp_path, caplog):
    home, project = tmp_path / "home", tmp_path / "project"
    db = _store(home, "alpha")
    _write(db.parent, "[cohesion\nenabled = true\n")
    _write(project / ".engram", "[cohesion]\nenabled = true\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(db, project)

    assert loaded.cohesion.enabled is False and loaded.persistence.enabled is False
    assert "Could not read the store's config" in caplog.text
    assert str(db.parent / "config.toml") in caplog.text


def test_when_the_project_is_the_default_stores_home_nothing_changes(tmp_path, caplog):
    home = tmp_path / "home"
    db = _store(home)
    _write(home / ".engram", "[cohesion]\nenabled = true\ndl_cost = 0.05\n\n[persistence]\nenabled = true\n")

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        loaded = _routed(db, home)

    assert loaded.cohesion.enabled is True and loaded.cohesion.dl_cost == 0.05
    assert loaded.persistence.enabled is True
    assert caplog.text == ""


def _server_config_at_the_store(tmp_path, monkeypatch, project_text):
    """The server's own start-up, stopped where it opens the store: the config it holds then, and the store's path."""
    import server
    import storage

    home, project = tmp_path / "home", tmp_path / "project"
    _store(home)
    _write(home / ".engram", "[cohesion]\nenabled = true\ndl_cost = 0.05\n")
    alpha = _store(home, "alpha")
    _write(alpha.parent, "[cohesion]\nenabled = true\ndl_cost = 0.11\n")
    _store(home, "beta")
    _write(project / ".engram", project_text)
    monkeypatch.setattr(server, "ENGRAM_HOME", home)
    monkeypatch.setattr(server, "DB_PATH", home / ".engram" / "graph.db")
    monkeypatch.setattr(server, "PROJECT_ROOT", project)
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    monkeypatch.setattr(server, "_initialized", False)
    monkeypatch.setattr(server, "_config", None)  # start-up sets these; this puts the old ones back afterwards
    monkeypatch.setattr(server, "_instance_name", None)
    seen = {}

    def stop_at_the_store(path, **kwargs):
        seen["db"], seen["config"] = Path(path), server._config
        raise RuntimeError("far enough")

    monkeypatch.setattr(storage, "Storage", stop_at_the_store)
    try:
        server._init_unlocked()
    except RuntimeError as stopped:
        assert str(stopped) == "far enough"
    return home, seen


def test_the_server_reads_the_gates_beside_the_store_it_opens(tmp_path, monkeypatch):
    home, seen = _server_config_at_the_store(tmp_path, monkeypatch, 'instance = "alpha"\n')
    assert seen["db"] == home / ".engram" / "instances" / "alpha" / "graph.db"
    assert (seen["config"].cohesion.enabled, seen["config"].cohesion.dl_cost) == (True, 0.11)


def test_the_server_leaves_an_uncalibrated_instance_off_though_its_home_is_on(tmp_path, monkeypatch):
    home, seen = _server_config_at_the_store(tmp_path, monkeypatch, 'instance = "beta"\n')
    assert seen["db"] == home / ".engram" / "instances" / "beta" / "graph.db"
    assert seen["config"].cohesion == config.CohesionConfig()


def test_the_server_with_no_instance_reads_the_default_stores_file(tmp_path, monkeypatch):
    home, seen = _server_config_at_the_store(tmp_path, monkeypatch, "")
    assert seen["db"] == home / ".engram" / "graph.db"
    assert (seen["config"].cohesion.enabled, seen["config"].cohesion.dl_cost) == (True, 0.05)
