"""Tests for the sheaf cohesion layer — config, math, gate."""

from config import load_config


class TestCohesionConfig:
    def test_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.15
        assert cfg.cohesion.variance_threshold == 0.90
        assert cfg.cohesion.max_subspace_dim == 8
        assert cfg.cohesion.min_episodes == 3
        assert cfg.cohesion.sleep_budget == 3

    def test_toml_override(self, tmp_path):
        (tmp_path / ".engram").mkdir()
        (tmp_path / ".engram" / "config.toml").write_text(
            "[cohesion]\ndl_cost = 0.3\nsleep_budget = 1\n")
        cfg = load_config(tmp_path)
        assert cfg.cohesion.dl_cost == 0.3
        assert cfg.cohesion.sleep_budget == 1
