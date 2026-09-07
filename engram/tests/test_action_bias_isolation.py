from pathlib import Path

import pytest

from experiments.action_bias.isolation import isolated_environment, isolated_fixture


def test_fixture_is_copied_initialized_and_destroyed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n")
    scratch = tmp_path / "scratch"
    live = tmp_path / "live-engram"
    live.mkdir()
    with isolated_fixture(source, scratch, live) as isolation:
        assert isolation.fixture_root != source
        assert (isolation.fixture_root / "app.py").read_text() == "VALUE = 1\n"
        assert (isolation.fixture_root / ".git").is_dir()
        fixture_path = isolation.fixture_root
    assert not fixture_path.exists()


def test_live_path_overlap_is_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="live Engram"):
        with isolated_fixture(source, source / "scratch", source):
            pass


def test_environment_repoints_all_engram_paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    with isolated_fixture(source, tmp_path / "scratch", live) as isolation:
        env = isolated_environment({
            "HOME": "/Users/test",
            "ENGRAM_HOME": str(live),
            "CLAUDE_CONFIG_DIR": "/Users/test/.claude",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
        }, isolation)
        assert env["ENGRAM_WAKE"] == "skip"
        assert env["ENGRAM_HOME"] == str(isolation.engram_home)
        assert env["ENGRAM_PROJECT_ROOT"] == str(isolation.fixture_root)
        assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
        assert env["CLAUDE_CONFIG_DIR"] == str(isolation.claude_config_dir)
        assert isolation.claude_config_dir.is_dir()
        assert isolation.claude_config_dir.parent == isolation.empty_mcp_config.parent
        assert "/Users/test/.claude" not in env.values()
        assert str(live) not in {env["ENGRAM_HOME"], env["ENGRAM_PROJECT_ROOT"]}
