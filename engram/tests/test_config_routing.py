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


# --- an instance's name is a name, never a path -------------------------------------

import importlib.util
import sys
from pathlib import Path

import pytest

ENGRAM = Path(__file__).resolve().parents[1]
NOT_NAMES = ["../../../planted", "a/b", "..", ".", " engram", "engram ", "x" * 65, "-lead", "with.dot", "n\u00e9",
             "tab\there", "a\\b", "real\\n"]
NOT_STRINGS = ["5", '["engram"]', "{ name = 1 }", "true"]
NAMES = ["real", "rio-grande", "a_b", "A1", "x" * 64, "0"]


def _homes(tmp_path):
    """A home with a default store and an instance `real`, a project, and a store planted outside the home."""
    home, project, planted = tmp_path / "home", tmp_path / "project", tmp_path / "planted"
    for folder in (home / ".engram", home / ".engram" / "instances" / "real", planted):
        folder.mkdir(parents=True)
        (folder / "graph.db").touch()
    (project / ".engram").mkdir(parents=True)
    return home, project, planted


def _bind(project, value, quoted=True):
    text = f'instance = "{value}"\n' if quoted else f"instance = {value}\n"
    (project / ".engram" / "config.toml").write_text(text)


def test_a_project_cannot_name_a_store_by_its_absolute_path(tmp_path, monkeypatch, caplog):
    # The fault: `home / ".engram" / "instances" / name / "graph.db"` with a name that is an absolute path IS that path.
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    home, project, planted = _homes(tmp_path)
    _bind(project, str(planted))

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        resolved = config.resolve_db_path(home, project)

    assert resolved == home / ".engram" / "graph.db"
    assert "Ignoring this project's instance binding" in caplog.text
    assert str(planted) not in caplog.text  # what the folder wrote is not repeated into the log


@pytest.mark.parametrize("value", NOT_NAMES)
def test_a_binding_that_is_not_a_plain_name_is_passed_over(tmp_path, monkeypatch, caplog, value):
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    home, project, planted = _homes(tmp_path)
    _bind(project, value)

    with caplog.at_level(logging.WARNING, logger="engram.config"):
        resolved = config.resolve_db_path(home, project)

    assert resolved == home / ".engram" / "graph.db"
    assert home in resolved.resolve().parents and planted not in resolved.resolve().parents
    assert "Ignoring this project's instance binding" in caplog.text


@pytest.mark.parametrize("value", NOT_STRINGS)
def test_a_binding_that_is_not_text_is_passed_over_and_nothing_raises(tmp_path, monkeypatch, value):
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    home, project, _ = _homes(tmp_path)
    _bind(project, value, quoted=False)
    assert config.resolve_instance_name(config.load_config(project)) is None
    assert config.resolve_db_path(home, project) == home / ".engram" / "graph.db"


@pytest.mark.parametrize("value", NAMES)
def test_a_plain_name_still_binds(tmp_path, monkeypatch, value):
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    home, project, _ = _homes(tmp_path)
    store = home / ".engram" / "instances" / value / "graph.db"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.touch()
    _bind(project, value)
    assert config.resolve_db_path(home, project) == store


def test_a_binding_passed_over_leaves_the_owners_default_in_force(tmp_path, monkeypatch):
    home, project, planted = _homes(tmp_path)
    _bind(project, str(planted))
    monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", " real ")
    assert config.resolve_db_path(home, project) == home / ".engram" / "instances" / "real" / "graph.db"


@pytest.mark.parametrize("value", NOT_NAMES + ["/somewhere/else"])
def test_a_default_that_is_not_a_plain_name_is_passed_over(tmp_path, monkeypatch, caplog, value):
    home, project, _ = _homes(tmp_path)
    monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", value)
    with caplog.at_level(logging.WARNING, logger="engram.config"):
        named = config.resolve_instance_name(config.load_config(project))
    assert named == (value.strip() if value.strip() == "engram" else None)  # " engram" is a name once its spaces go
    assert config.resolve_db_path(home, project) == home / ".engram" / "graph.db"


def test_the_server_opens_the_default_store_when_a_project_names_a_path(tmp_path, monkeypatch):
    # The server's own start-up, stopped where it opens the store.
    import server
    import storage

    home, project, planted = _homes(tmp_path)
    _bind(project, str(planted))
    monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
    monkeypatch.setattr(server, "ENGRAM_HOME", home)
    monkeypatch.setattr(server, "DB_PATH", home / ".engram" / "graph.db")
    monkeypatch.setattr(server, "PROJECT_ROOT", project)
    for name in ("_initialized", "_config", "_instance_name"):
        monkeypatch.setattr(server, name, False if name == "_initialized" else None)
    seen = {}

    def stop_at_the_store(path, **kwargs):
        seen["db"] = Path(path)
        raise RuntimeError("far enough")

    monkeypatch.setattr(storage, "Storage", stop_at_the_store)
    with pytest.raises(RuntimeError, match="far enough"):
        server._init_unlocked()
    assert seen["db"] == home / ".engram" / "graph.db"


def _hook(name):
    spec = importlib.util.spec_from_file_location(f"engram_{name}_hook_for_names", ENGRAM / "hooks" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hook_binding(module):
    found = module._load_instance_config()
    return found[0] if isinstance(found, tuple) else found


@pytest.mark.parametrize("hook", ["wake", "sleep", "nudge"])
def test_each_hook_passes_over_a_binding_or_a_default_that_is_not_a_plain_name(tmp_path, monkeypatch, hook):
    home, project, planted = _homes(tmp_path)
    module = _hook(hook)
    monkeypatch.setattr(module, "PROJECT_ROOT", project)
    monkeypatch.setattr(module, "ENGRAM_HOME", home)
    for value in [str(planted)] + NOT_NAMES:
        _bind(project, value)
        monkeypatch.delenv("ENGRAM_DEFAULT_INSTANCE", raising=False)
        assert _hook_binding(module) is None, value
        monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", "real")
        assert _hook_binding(module) == "real", value
    for value in NOT_STRINGS:
        _bind(project, value, quoted=False)
        assert _hook_binding(module) == "real", value
    _bind(project, "real")
    for value in [str(planted), "../x", "a/b"]:
        monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", value)
        assert _hook_binding(module) == "real"
        (project / ".engram" / "config.toml").unlink()
        assert _hook_binding(module) is None, value
        _bind(project, "real")
    monkeypatch.setenv("ENGRAM_DEFAULT_INSTANCE", " real ")
    (project / ".engram" / "config.toml").unlink()
    assert _hook_binding(module) == "real"


def test_the_name_rule_is_one_rule_in_its_three_places():
    import lighthouse_receiver_config

    sys.path.insert(0, str(ENGRAM / "hooks"))
    try:
        import harness
    finally:
        sys.path.remove(str(ENGRAM / "hooks"))
    harness.instance_name("warm")  # the hooks compile theirs on first use
    assert config.INSTANCE_NAME.pattern == lighthouse_receiver_config.NAME.pattern == harness._INSTANCE_NAME.pattern
    for value in NAMES:
        assert config.valid_instance_name(value) and harness.instance_name(value) == value
    for value in NOT_NAMES + [None, 5, ["engram"], b"engram"]:
        assert not config.valid_instance_name(value) and harness.instance_name(value) is None


def test_the_local_agent_refuses_a_name_that_is_not_a_plain_name(tmp_path, monkeypatch):
    import local_agent

    home, _, planted = _homes(tmp_path)
    monkeypatch.setattr(local_agent, "ENGRAM_HOME", home)
    monkeypatch.setattr(local_agent, "DB_PATH", home / ".engram" / "graph.db")
    assert local_agent.resolve_instance_db(None) == home / ".engram" / "graph.db"
    assert local_agent.resolve_instance_db("real") == home / ".engram" / "instances" / "real" / "graph.db"
    for value in [str(planted), "../../../planted", "a/b", ".."]:
        with pytest.raises(FileNotFoundError, match="An instance's name is"):
            local_agent.resolve_instance_db(value)
