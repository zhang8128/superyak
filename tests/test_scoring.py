"""Pure recall scoring shared by recall(), the margin counterfactual, and the replay."""

from datetime import datetime, timedelta, timezone

import pytest

from scoring import DEFAULT_RECENCY_CAP, MODES, score_candidate
from tests.test_recall_margins import engram_server_env  # noqa: F401


def test_modes_are_exactly_tiebreak_and_additive():
    assert MODES == ("tiebreak", "additive")


def test_additive_matches_the_historical_formula():
    s = score_candidate(
        0.8, 0.5, False, mode="additive", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert s == pytest.approx(0.8 * 0.6 + 0.5 * 0.4)


def test_tiebreak_bounds_recency_by_cap():
    fresh = score_candidate(
        0.8, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    stale = score_candidate(
        0.8, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert fresh - stale == pytest.approx(0.02)


def test_tiebreak_clamps_out_of_range_recency_to_its_bounded_domain():
    fresh = score_candidate(
        0.8, 2.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    stale = score_candidate(
        0.8, -1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert fresh - stale == pytest.approx(0.02)


def test_tiebreak_cannot_overturn_a_similarity_gap_wider_than_cap():
    better_old = score_candidate(
        0.84, 0.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    worse_new = score_candidate(
        0.80, 1.0, False, mode="tiebreak", w_sim=0.6, w_rec=0.4, cap=0.02
    )
    assert better_old > worse_new


def test_auto_generated_penalty_applies_in_both_modes():
    for mode in MODES:
        plain = score_candidate(
            0.8, 0.5, False, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02
        )
        auto = score_candidate(
            0.8, 0.5, True, mode=mode, w_sim=0.6, w_rec=0.4, cap=0.02
        )
        assert auto == pytest.approx(plain * 0.7)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        score_candidate(
            0.8,
            0.5,
            False,
            mode="sideways",
            w_sim=0.6,
            w_rec=0.4,
            cap=0.02,
        )


def test_default_cap_is_provisional_near_tie_threshold():
    assert DEFAULT_RECENCY_CAP == 0.02


def test_memory_config_defaults_to_tiebreak():
    from config import MemoryConfig

    cfg = MemoryConfig()
    assert cfg.recency_mode == "tiebreak"
    assert cfg.recency_cap == 0.02


def test_default_toml_declares_recency_keys():
    from config import _DEFAULT_TOML

    assert 'recency_mode = "tiebreak"' in _DEFAULT_TOML
    assert "recency_cap = 0.02" in _DEFAULT_TOML


def test_recall_modes_differ_by_the_recency_term(engram_server_env):
    import server
    from tests.test_recall_margins import seed

    seed(1)
    server._config.memory.recency_mode = "additive"
    additive = server.recall(
        query="episode number 0 about rivers and mapping", uninvited=0
    )["results"][0]["score"]
    server._config.memory.recency_mode = "tiebreak"
    tiebreak = server.recall(
        query="episode number 0 about rivers and mapping", uninvited=0
    )["results"][0]["score"]

    assert additive - tiebreak == pytest.approx(0.4 - 0.02, abs=0.02)


def test_future_timestamp_is_treated_as_fully_recent(engram_server_env):
    import server

    now = datetime.now(timezone.utc)
    exactly_tomorrow = (now + timedelta(days=1)).isoformat()
    assert server._recency_at(exactly_tomorrow, now) == 1.0


def test_both_recall_arms_use_the_configured_mode(
    engram_server_env, monkeypatch
):
    import server
    from tests.test_recall_margins import add_session_bias, seed

    seed(3)
    seen: list[str] = []
    real = server.score_candidate

    def record_mode(*args, **kwargs):
        seen.append(kwargs["mode"])
        return real(*args, **kwargs)

    monkeypatch.setattr(server, "score_candidate", record_mode)
    add_session_bias("rivers and mapping")
    out = server.recall(query="rivers and mapping", uninvited=0)

    assert out["margin"]["stability"]["checked"] is True
    assert set(seen) == {"tiebreak"}
    assert len(seen) >= 2 * 3


def test_memory_config_default_lane_is_personal():
    from config import MemoryConfig, _DEFAULT_TOML

    assert MemoryConfig().default_lane == "personal"
    assert 'default_lane = "personal"' in _DEFAULT_TOML
